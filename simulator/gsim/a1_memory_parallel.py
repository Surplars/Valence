#!/usr/bin/env python3
"""Bounded actual A1 memory-profile checks; no full GSIM, Linux or timing claim.

Explicit stages allow one shared Scala compile and a frozen combined batch.
Independent host oracles cover four accepted LSU owners, killed-token drain,
serial MMIO/AMO admission, real Sv39/PMP/fault/recovery and source-reversed cache
fills with only two response credits. Tile emitters separately inspect the real
CPU composition, not an ideal-memory benchmark masquerading as a board result.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import bound_store_replay_common as portable

ROOT = Path(__file__).resolve().parents[2]
MODELS = {
    "lsu": ("platform.CommonA1MemoryLsuMain", "CanonicalStoreLsuGsim", ["4"],
            "canonical_store_lsu.cpp", ["A1_MEMORY_PARALLEL=1", "CANONICAL_HANDOFF=1",
                                       "CANONICAL_TEST_RAM_BASE=0x80200000ULL"],
            ["A1_MEMORY_LSU_FOUR_OWNER_PASS", "A1_MEMORY_LSU_HELD_COMPLETION_PASS slots=4 accepted=3 cycles=3",
             "CANONICAL_STORE_LSU_PASS"],
            [("--inject-payload", "LSU payload no longer belongs to the independently accepted start")]),
    "lsu2": ("platform.CommonA1MemoryLsuMain", "CanonicalStoreLsuGsim", ["2"],
            "canonical_store_lsu.cpp", ["A1_MEMORY_PARALLEL=1", "CANONICAL_HANDOFF=1",
                "A1_MEMORY_OWNER_SLOTS=2", "CANONICAL_TEST_RAM_BASE=0x80200000ULL"],
            ["A1_MEMORY_LSU_HELD_COMPLETION_PASS slots=2 accepted=1 cycles=1", "CANONICAL_STORE_LSU_PASS"],
            [("--inject-payload", "LSU payload no longer belongs to the independently accepted start")]),
    "backend-memory": ("platform.CommonA1MemoryBackendMain", "CanonicalVirtualStoreBackendGsim", ["memory"],
            "canonical_virtual_store_backend.cpp", ["A1_MEMORY_PARALLEL=1", "PRECHECK_ENABLED=1",
                "CANONICAL_STORE_OVERLAP=1", "VIRTUAL_LOAD_TEST_RAM_BASE=0x80200000ULL",
                "VIRTUAL_LOAD_TEST_RAM_BYTES=0x80000000ULL"],
            ["CANONICAL_BACKEND_CASE name=a1_four_warm_owners", "CANONICAL_BACKEND_PASS enabled=1"],
            [("--inject-result", "independent architectural result mismatch"),
             ("--inject-cancel-retirement", "faulted store allowed the younger load or dependent full token to retire")]),
    "backend-combined": ("platform.CommonA1MemoryBackendMain", "CanonicalVirtualStoreBackendGsim", ["combined"],
            "canonical_virtual_store_backend.cpp", ["A1_MEMORY_PARALLEL=1", "PRECHECK_ENABLED=1",
                "CANONICAL_STORE_OVERLAP=1", "VIRTUAL_LOAD_TEST_RAM_BASE=0x80200000ULL",
                "VIRTUAL_LOAD_TEST_RAM_BYTES=0x80000000ULL"],
            ["CANONICAL_BACKEND_CASE name=a1_four_warm_owners", "CANONICAL_BACKEND_PASS enabled=1"],
            [("--inject-result", "independent architectural result mismatch"),
             ("--inject-cancel-retirement", "faulted store allowed the younger load or dependent full token to retire")]),
    "cache": ("platform.CommonA1MemoryCacheMain", "CommonA1MemoryCacheGsim", [],
              "a1_memory_parallel_cache.cpp", [], ["A1_MEMORY_CACHE_PASS"],
              [("--inject-mismatch", "CPU independent data mismatch")]),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["freeze", "config", "emit", "generate", "build", "run"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", default="lsu,lsu2,backend-combined,cache")
    portable.add_paths(parser, ROOT)
    args = parser.parse_args()
    root = args.source_root.resolve()
    tools = portable.tool_paths(args, parser)
    names = args.models.split(",")
    if len(set(names)) != len(names) or any(name not in MODELS for name in names):
        parser.error("unknown or duplicate model")
    extra = [root / "simulator/gsim/a1_memory_parallel.py"]
    extra += [root / "simulator/gsim/harness" / name for name in (
        "canonical_store_lsu.cpp", "canonical_store_oracle.h", "canonical_virtual_store_backend.cpp",
        "virtual_load_test_memory.h", "a1_memory_parallel_cache.cpp", "coherent_read_mshr.cpp")]
    def inputs():
        return portable.source_inputs(root, extra)
    if portable.preflight(args, inputs(), tools):
        return
    output = args.output.resolve()
    receipt_path = output / "receipt.json"
    if args.stage == "freeze":
        output.mkdir(parents=True, exist_ok=False)
        receipt = {"schema": "a1-memory-parallel-v1", "status": "FROZEN", "models": names,
            "source_commit": portable.source_revision(root), "inputs": inputs(),
            "tools": portable.tool_binding(tools), "commands": [],
            "scope": "actual Selected-derived LSU/backend/DTLB/L1D components; no full CPU/board/frequency result",
            "capacity": {"issue": 2, "rob": 16, "prf": 48, "lsu": 4, "store_buffer": 2,
                         "dtlb": 16, "cache_mshrs": 2, "cache_responses": 2, "cache_writebacks": 2},
            "limits": ["Four LSU owners do not mean four external cache misses.",
                       "CPU native responses remain ordered; reverse completion is tested at TL sources.",
                       "Cache driver exercises legacy D with whole-line input idle.",
                       "Decoded backend has ideal external data/PTE services; not full-platform bandwidth."]}
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
        print("A1_MEMORY_INPUTS_FROZEN", output)
        return
    receipt = json.loads(receipt_path.read_text())
    assert receipt["schema"] == "a1-memory-parallel-v1" and receipt["inputs"] == inputs(), "source drift"
    assert receipt["tools"] == portable.tool_binding(tools), "tool drift"
    assert all(name in receipt["models"] for name in names), "model absent from frozen batch"
    def save():
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    def run(label, command, markers=(), negative=False, timeout=1800):
        assert receipt["inputs"] == inputs(), "source drift during combined gate"
        portable.check_tools(receipt["tools"])
        log = output / (label + ".log")
        start = time.monotonic()
        with log.open("x") as stream:
            result = subprocess.run(portable.command_args(command, tools), cwd=root,
                stdout=stream, stderr=subprocess.STDOUT, timeout=timeout,
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0:halt_on_error=1",
                     "UBSAN_OPTIONS": "halt_on_error=1:print_stacktrace=1"})
        text = log.read_text(errors="replace")
        receipt["commands"].append({"label": label, "command": list(map(str, command)),
            "exit": result.returncode, "seconds": round(time.monotonic() - start, 3),
            "sha256": portable.sha(log), "negative_control": negative})
        save()
        assert (result.returncode != 0 if negative else result.returncode == 0) and all(
            marker in text for marker in markers), label + "\n" + text[-6000:]
        print(label, "PASS", flush=True)
    try:
        if args.stage == "config":
            run("config", [tools["mill"], "-i", "-j", "1", "IonSoC.test.testOnly",
                "platform.CommonA1MemoryProfileSpec"])
        else:
            for name in names:
                main, top, parameters, driver, definitions, markers, negatives = MODELS[name]
                model = output / name
                if args.stage == "emit":
                    model.mkdir(exist_ok=False)
                    run(name + "-emit", [tools["mill"], "-i", "-j", "1", "IonSoC.test.runMain",
                        main, model, *parameters])
                elif args.stage == "generate":
                    run(name + "-generate", [tools["gsim"], "--threads=1", "--cpp-max-size-KB=1024",
                        "--dir=" + str(model), model / (top + ".fir")])
                elif args.stage == "build":
                    flags = ["-std=c++20", "-O1", "-g0", "-fsanitize=address,undefined",
                             "-fno-sanitize-recover=all", "-I" + str(model), *["-D" + d for d in definitions]]
                    objects = []
                    for i, source in enumerate(sorted(model.glob(top + "[0-9]*.cpp"))):
                        obj = source.with_suffix(".o")
                        run(name + "-compile-" + str(i), [tools["cxx"], *flags, "-c", source, "-o", obj])
                        objects.append(obj)
                    assert objects, "no generated model source"
                    run(name + "-link", [tools["cxx"], *flags, root / "simulator/gsim/harness" / driver,
                        *objects, "-ldl", "-o", model / "run"])
                else:
                    run(name + "-positive", [model / "run"], markers, timeout=180)
                    for i, (option, marker) in enumerate(negatives):
                        run(name + "-negative-" + str(i), [model / "run", option], [marker], True, timeout=180)
        receipt["status"] = args.stage.upper() + "_PASS_COMPONENT_ONLY"
        save()
    except BaseException as error:
        receipt["status"] = args.stage.upper() + "_FAILED_PRESERVE_EVIDENCE"
        receipt["error"] = str(error)
        save()
        raise


if __name__ == "__main__":
    main()
