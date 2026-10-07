#!/usr/bin/env python3
"""Batched short control-path acceptance, with one reused board model; no Vivado."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from run import BUILD, HERE, ROOT, build_c_payload, run, setup, test
from staged_fabric import board_apps

CHECKS = ("contracts", "capacity", "fetch", "core", "vm", "board")


def reference():
    # Reuse only a byte-verified, pinned reference. No vendor checkout changes.
    library = BUILD / "nemu-src/build/riscv64-nemu-interpreter-so"
    used_file = BUILD / "reference-used.json"
    lock = json.loads((HERE / "config/reference-lock.json").read_text())
    config_hash = hashlib.sha256((HERE / "config/rv64-integer-ref_defconfig").read_bytes()).hexdigest()
    if library.is_file() and used_file.is_file():
        used = json.loads(used_file.read_text())
        if (all(used.get(k) == v for k, v in lock.items()) and used.get("config_sha256") == config_hash and
                used.get("library_sha256") == hashlib.sha256(library.read_bytes()).hexdigest()):
            print("Reusing byte-verified pinned NEMU reference", flush=True)
            return library
    from reference import build_reference
    return build_reference()


def negative(binary, arguments, message, output):
    result = subprocess.run([binary, *arguments, "--inject-mismatch"], capture_output=True, text=True,
                            timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    output.write_text(result.stdout + result.stderr)
    if result.returncode != 1 or message not in result.stdout + result.stderr:
        raise RuntimeError("independent oracle failed to reject injected corruption")
    print(f"Negative oracle: PASS {message}", flush=True)


def core_payloads(output):
    payloads = []
    for stem in ("integer-program", "branch-program"):
        payload = output / stem
        run(["riscv64-unknown-elf-gcc", "-march=rv64i", "-mabi=lp64", "-mno-relax",
             "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/integer-program.ld",
             HERE / f"payloads/{stem}.S", "-o", payload.with_suffix(".elf")],
            log=output / f"{stem}-build.log")
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
             payload.with_suffix(".elf"), payload.with_suffix(".bin")])
        payloads.append(payload.with_suffix(".bin"))
    payloads.append(build_c_payload())
    return payloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="20261001")
    parser.add_argument("--only", nargs="+", choices=CHECKS, default=list(CHECKS),
                        help="affected failure diagnosis only; subsets record partial-pass")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    name = f"control-stage-{args.tag}"
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    report = {"profile": "staged-control", "issue_width": 2, "status": "running",
              "checks_requested": args.only, "synthesis_run": False, "routed_timing_verified": False}
    evidence = output / "results.json"
    evidence.write_text(json.dumps(report, indent=2) + "\n")
    try:
        if "contracts" in args.only:
            run(["mill", "-i", "IonSoC.test.testOnly", "ooo.ControlTimingSpec", "ooo.StagedFabricSpec",
                 "ooo.OooParamsSpec"], log=output / "contracts.log")
            print((output / "contracts.log").read_text(), end="", flush=True)
        gsim, cxx = setup(False)
        if "capacity" in args.only:
            capacity = test(gsim, cxx, name + "/capacity", "ooo.RenameCapacityGsimMain",
                            "RenameCapacityGsim", "rename_capacity.cpp", defines={})
            negative(capacity / "run", (), "rename capacity mismatch", capacity / "negative.log")
        ref = reference() if set(args.only) & {"fetch", "core"} else None
        if "fetch" in args.only:
            for width in (2, 4):
                fetch = test(gsim, cxx, name + f"/fetch{width}", "ooo.FetchOffsetsGsimMain",
                             "FetchOffsetsGsim", "fetch_offsets.cpp",
                             parameters=(str(width), "stable-fault-metadata"),
                             defines={"FETCH_WIDTH": width, "STABLE_FAULT_METADATA": 1})
                negative(fetch / "run", (), "mixed-length instruction mismatch", fetch / "negative.log")
            test(gsim, cxx, name + "/fetch-uncompressed", "ooo.FpgaFetchGsimMain",
                 "FpgaFetchGsim", "fpga_fetch.cpp", parameters=("plain", "stable-fault-metadata"),
                 runtime_args=(ref,), defines={})
        if "core" in args.only:
            payloads = core_payloads(output)
            core = test(gsim, cxx, name + "/core", "ooo.IntegerCoreGsimMain", "IntegerCoreGsim", "core.cpp",
                        parameters=("32", "64", "64", "8", "plain", "plain", "plain", "plain", "plain", "0",
                            "registered-branch", "4", "registered-owners", "registered-memory-address",
                            "registered-retirement", "registered-load-replay", "early-recovery-issue-block",
                            "precomplete-mispredicted-branch", "parallel-rename-admission"),
                        runtime_args=(ref, *payloads), defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64,
                            "TAG_BITS": 64, "MEMORY_ENTRIES": 8, "REGISTERED_BRANCH_REDIRECT": 1,
                            "REGISTERED_RESPONSE_OWNERS": 1, "REGISTERED_MEMORY_ADDRESS": 1})
            negative(core / "run", (ref, *payloads), "NEMU register mismatch", core / "negative.log")
        if "vm" in args.only:
            payload = output / "vm-data"
            run(["riscv64-unknown-elf-gcc", "-march=rv64ia_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                 HERE / "payloads/vm-data.S", "-o", payload.with_suffix(".elf")], log=output / "vm-build.log")
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                 payload.with_suffix(".elf"), payload.with_suffix(".bin")])
            test(gsim, cxx, name + "/vm", "ooo.VmDataPlatformGsimMain", "VmDataPlatformGsim",
                 "vm_data_platform.cpp", parameters=("coherent", "compact", "buffered-response",
                     "registered-physical-owners", "registered-retirement", "registered-load-replay",
                     "early-recovery-issue-block", "precomplete-mispredicted-branch", "staged-fabric", "staged-control"),
                 runtime_args=(payload.with_suffix(".bin"), "--coherent"), defines={})
        if "board" in args.only:
            report.update(board_apps(gsim, cxx, output, profile="staged-control"))
        report["status"] = "passed" if set(args.only) == set(CHECKS) else "partial-pass"
    except (RuntimeError, subprocess.SubprocessError, OSError):
        report["status"] = "failed"
        raise
    finally:
        evidence.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Short control-stage batch: {report['status']}; evidence: {evidence}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM control-stage batch: {error}", file=sys.stderr)
        sys.exit(1)
