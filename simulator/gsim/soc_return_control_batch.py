#!/usr/bin/env python3
"""One affected batch: system capture, FP recoding, store class, PMP and TL return.

Finish the source batch before invoking this entry. No full GSIM/Linux/CAD.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import run as common
from control_stage import core_payloads, reference
import throughput_perf as perf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--coremark-baseline", type=Path, required=True)
    ap.add_argument("--resume-units", type=Path,
                    help="Resume only the recorded bridge negative-exit wrapper rejection, with exact FIR checks.")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("soc-return-control-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    sources = [p for base in ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala")
               for p in sorted((common.ROOT / base).rglob("*.scala"))]
    sources += [p for p in sorted((common.HERE / "harness").iterdir()) if p.is_file()]
    sources += [common.ROOT / "build.mill", Path(__file__), common.HERE / "run.py",
                common.HERE / "control_stage.py", common.HERE / "throughput_perf.py",
                common.HERE / "rv64gc_native_short.py", common.HERE / "rv64gc_board.py",
                common.HERE / "soc_refactor_coremark.py"]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    receipt = dict(status="RUNNING", source_sha256=before, checks={}, issue_width=2,
                   isa="rv64gc", cpu_hz=100000000, uart_baud=460800,
                   cycle_contract={"system_dispatch_added_cycles": 1, "fp_div_sqrt_added_cycles": 1,
                                   "pmp_added_cycles": 0, "tl_return_added_cycles": 0,
                                   "store_class_added_cycles": 0},
                   limits=["Affected bounded checks only; not full GSIM/Linux/ISA certification.",
                           "No physical CDC/SDF/FPGA timing or bit release proof."])
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}

    def save():
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    try:
        save()
        reusable = None
        if a.resume_units:
            reusable = a.resume_units.resolve()
            if not reusable.is_relative_to(common.BUILD.resolve()):
                raise RuntimeError("Reuse must stay inside GSIM evidence directory")
            old = json.loads((reusable / "receipt.json").read_text())
            if old["status"] != "FAILED" or old.get("failure") != (
                    "Independent negative control not rejected: bridge-generic"):
                raise RuntimeError("Only the known negative-exit wrapper failure permits isolated reuse")
            runner_name = str(Path(__file__).relative_to(common.ROOT))
            changes = {name for name in set(before) | set(old["source_sha256"])
                       if before.get(name) != old["source_sha256"].get(name)}
            if changes != {runner_name} or sha(reusable / "executed_runner.py") != old["source_sha256"][runner_name]:
                raise RuntimeError("Hardware, oracle or fixture changed; no isolated reuse")
            negative_text = (reusable / "bridge-generic/negative.log").read_text()
            if "terminate called after throwing an instance of 'std::runtime_error'" not in negative_text or (
                    "TileLink bridge response data, error or order mismatch" not in negative_text):
                raise RuntimeError("Unexpected original negative failure; no reuse")
            receipt["reuse"] = dict(origin=str(reusable), changes=sorted(changes),
                                   original_receipt_sha256=sha(reusable / "receipt.json"),
                                   original_compile_sha256=sha(reusable / "compile.log"),
                                   contract="Unchanged hardware/oracles + exact fresh FIR + rerun positive/negative checks")
        else:
            common.run(["mill", "-i", "IonSoC.test.compile"], log=out / "compile.log", timeout=300)
        gsim, cxx = common.setup(False)

        def unit(name, emitter, top, harness, message, parameters=(), runtime=(), defines=None):
            logs = out / name
            if reusable and name in old.get("model_sha256", {}):
                model = reusable / name
                if old["model_sha256"][name] != {path: sha(common.ROOT / path)
                                                  for path in old["model_sha256"][name]}:
                    raise RuntimeError("Old isolated artifact drift: " + name)
                common.run(["mill", "-i", "IonSoC.test.runMain", emitter, logs, *parameters],
                           log=out / (name + "-elaborate-recheck.log"), timeout=120)
                if sha(logs / (top + ".fir")) != sha(model / (top + ".fir")):
                    raise RuntimeError("Fresh isolated FIR differs: " + name)
                common.run([model / "run", *runtime], env=env, log=logs / "test.log", timeout=180)
            else:
                model = common.test(gsim, cxx, out.name + "/" + name, emitter, top, harness,
                                    parameters=parameters, runtime_args=runtime, defines=defines or {}, timeout=180)
            receipt["checks"][name] = (logs / "test.log").read_text().strip()
            artifacts = {str(p.relative_to(common.ROOT)): sha(p) for p in model.iterdir()
                         if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
            negative = subprocess.run([str(model / "run"), *map(str, runtime), "--inject-mismatch"],
                                      env=env, capture_output=True, text=True, timeout=180)
            (logs / "negative.log").write_text(negative.stdout + negative.stderr)
            # This existing bridge driver has an uncaught std::runtime_error:
            # its intended oracle rejection is SIGABRT, not exit(1). Do not
            # accept arbitrary signals or sanitizer failures as a negative PASS.
            expected_exit = -6 if top == "OrderedTileLinkBridge" else 1
            if negative.returncode != expected_exit or message not in negative.stdout + negative.stderr or (
                    expected_exit == -6 and "terminate called after throwing an instance of 'std::runtime_error'"
                    not in negative.stderr):
                raise RuntimeError("Independent negative control not rejected: " + name)
            receipt["checks"][name + "-negative"] = message
            receipt.setdefault("negative_exit", {})[name] = negative.returncode
            if artifacts != {path: sha(common.ROOT / path) for path in artifacts}:
                raise RuntimeError("Generated/reused model changed while running: " + name)
            receipt.setdefault("model_sha256", {})[name] = artifacts
            save()
            return model

        unit("arithmetic", "ooo.TimingArithmeticGsimMain", "TimingArithmeticGsim", "timing_arithmetic.cpp",
             "timing arithmetic independent oracle mismatch")
        for width in (2, 4):
            unit("pmp-packet-" + str(width), "ooo.PmpCheckerGsimMain", "PmpCheckerGsim", "pmp_checker.cpp",
                 "PMP oracle mismatch", parameters=("packet", "word-span", "balanced", "width=" + str(width)))
        unit("pmp-prefix", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim", "pmp_checker.cpp",
             "PMP oracle mismatch", parameters=("raw-prefix", "word-span", "balanced"))
        unit("bridge-generic", "ooo.OrderedTileLinkBridgeGsimMain", "OrderedTileLinkBridge", "tilelink_bridge.cpp",
             "TileLink bridge response data, error or order mismatch")
        unit("bridge-mixed-flow", "ooo.OrderedTileLinkBridgeGsimMain", "OrderedTileLinkBridge", "tilelink_bridge.cpp",
             "TileLink bridge response data, error or order mismatch", parameters=("mixed", "flow", "partial"),
             defines={"ORDERED_WRITES": 1, "ALLOW_WRITE_ERRORS": 1, "MIXED_ACCESSES": 1,
                      "FLOW_HEAD_RESPONSE": 1, "ALLOW_PARTIAL_WRITES": 1})
        vector_dir = common.BUILD / "floating-point-full-20261004-nan-cut-r1"
        vector_receipt = json.loads((vector_dir / "receipt.json").read_text())
        vectors = vector_dir / "vectors.txt"
        if vector_receipt["status"] != "PASS_FUNCTIONAL_CANDIDATE" or sha(vectors) != vector_receipt["vector_sha256"]:
            raise RuntimeError("Independent SoftFloat evidence mismatch")
        receipt["softfloat_vector_sha256"] = sha(vectors)
        for profile in ("fd", "f", "small"):
            unit("fp-numerical-" + profile, "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim",
                 "floating_point_full.cpp", "FP full mismatch", parameters=(profile,), runtime=(vectors, profile))
        ref = reference()
        payloads = core_payloads(out)
        model = common.test(gsim, cxx, out.name + "/integer-core", "ooo.ThroughputPerfGsimMain",
                            "IntegerCoreGsim", "core.cpp", parameters=("staged-fetch-feedback",),
                            defines={**perf.DEFINES, "REGISTERED_FETCH_PACKET": 1, "FETCH_HINT_ALIAS_BENCH": 1},
                            runtime_args=(ref, *payloads, "--throughput-short"), timeout=180)
        receipt["checks"]["integer-core"] = (model / "test.log").read_text().strip()
        receipt["integer_measurements"] = perf.parse_measurements((model / "test.log").read_text(), 13,
            perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)})
        for mode in ("--timing-smoke", "--pipeline-recovery"):
            common.run([model / "run", ref, *payloads, mode], env=env, log=model / (mode[2:] + ".log"), timeout=180)
            receipt["checks"][mode[2:]] = (model / (mode[2:] + ".log")).read_text().strip()
        negative = subprocess.run([str(model / "run"), str(ref), *map(str, payloads), "--inject-mismatch"],
                                  env=env, capture_output=True, text=True, timeout=180)
        (model / "negative.log").write_text(negative.stdout + negative.stderr)
        if negative.returncode != 1 or "NEMU register mismatch" not in negative.stdout + negative.stderr:
            raise RuntimeError("Independent CPU negative control not rejected")
        receipt["checks"]["integer-core-negative"] = "NEMU register mismatch"
        save()
        common.run([sys.executable, common.HERE / "rv64gc_native_short.py", "--tag", a.tag],
                   log=out / "native.log", timeout=1800)
        native = common.BUILD / ("rv64gc-native-" + a.tag) / "receipt.json"
        if json.loads(native.read_text())["status"] != "PASS_RV64GC_NATIVE_AFFECTED_SHORT":
            raise RuntimeError("Real RV64GC CPU/current board proof failed")
        receipt["native_receipt"] = str(native)
        receipt["native_receipt_sha256"] = sha(native)
        save()
        current = common.BUILD / ("rv64gc-board-" + a.tag) / "receipt.json"
        common.run([sys.executable, common.HERE / "soc_refactor_coremark.py", "--tag", a.tag,
                    "--baseline", a.coremark_baseline.resolve(), "--current", current],
                   log=out / "coremark.log", timeout=1500)
        coremark = common.BUILD / ("soc-refactor-coremark-" + a.tag) / "receipt.json"
        if json.loads(coremark.read_text())["status"] != "PASS_SAME_BINARY_BOARD_COREMARK_COMPARE":
            raise RuntimeError("Same-binary CoreMark CRC/tick comparison failed")
        receipt["coremark_receipt"] = str(coremark)
        receipt["coremark_receipt_sha256"] = sha(coremark)
        if before != {str(p.relative_to(common.ROOT)): sha(p) for p in sources}:
            raise RuntimeError("Source/oracle changed during affected batch")
        receipt["status"] = "PASS_SOC_RETURN_CONTROL_AFFECTED_SHORT"
    except BaseException as error:
        receipt.update(status="FAILED", failure=str(error))
        raise
    finally:
        save()
    print(receipt["status"], json.dumps(receipt["checks"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
