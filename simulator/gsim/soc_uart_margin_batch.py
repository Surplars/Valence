#!/usr/bin/env python3
"""Three timing cuts + actual CPU short checks, no full GSIM or Linux simulation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from control_stage import core_payloads, reference
import throughput_perf as perf


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("Unsafe tag")
    out = common.BUILD / ("soc-uart-margin-" + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    sources = [p for folder in ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala")
               for p in sorted((common.ROOT / folder).rglob("*.scala"))]
    sources += [p for folder in ("simulator/gsim/harness", "simulator/gsim/payloads")
                for p in sorted((common.ROOT / folder).rglob("*")) if p.is_file()]
    sources += [common.ROOT / "build.mill", Path(__file__), common.HERE / "run.py",
                common.HERE / "control_stage.py", common.HERE / "throughput_perf.py",
                common.HERE / "rv64gc_native_short.py", common.HERE / "rv64gc_board.py"]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    receipt = dict(status="RUNNING", source_sha256=before, checks={}, issue_width=2,
                   isa="rv64gc", cpu_hz=100000000, uart_baud=460800,
                   cycle_contract="No added issue, execution or memory preparation cycle; window latency=1/II=1.",
                   limits=["Affected short models only; no Linux/full ISA simulation or FPGA timing proof.",
                           "Performance comparison is against recorded same-harness workload counts."])
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        def unit(name, emitter, top, harness, message, parameters=(), defines=None):
            model = common.test(gsim, cxx, out.name + "/" + name, emitter, top, harness,
                                parameters=parameters, defines=defines or {}, timeout=180)
            receipt["checks"][name] = (model / "test.log").read_text().strip()
            negative = subprocess.run([str(model / "run"), "--inject-mismatch"],
                                      env=env, capture_output=True, text=True, timeout=180)
            (model / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode != 1 or message not in negative.stdout + negative.stderr:
                raise RuntimeError("Independent oracle negative control not rejected: " + name)
            receipt.setdefault("model_sha256", {})[name] = {
                str(p.relative_to(common.ROOT)): sha(p) for p in model.iterdir()
                if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
            receipt["checks"][name + "-negative"] = message
            (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        for capacity in (3, 5):
            unit("fetch-window-" + str(capacity), "ooo.RegisteredFetchWindowGsimMain", "RegisteredFetchWindowGsim",
                 "registered_fetch_window.cpp", "fetch window independent oracle mismatch",
                 parameters=(str(capacity),), defines={"WINDOW_CAPACITY": capacity})
        unit("head-selection", "ooo.RegisteredHeadSelectionGsimMain", "RegisteredHeadSelectionGsim",
             "registered_head_selection.cpp", "registered head independent oracle mismatch")
        ref, payloads = reference(), core_payloads(out)
        model = common.test(gsim, cxx, out.name + "/integer-core", "ooo.ThroughputPerfGsimMain",
                            "IntegerCoreGsim", "core.cpp", parameters=("staged-fetch-feedback",),
                            defines={**perf.DEFINES, "REGISTERED_FETCH_PACKET": 1, "FETCH_HINT_ALIAS_BENCH": 1},
                            runtime_args=(ref, *payloads, "--throughput-short"), timeout=180)
        receipt["checks"]["integer-core"] = (model / "test.log").read_text().strip()
        measurements = perf.parse_measurements((model / "test.log").read_text(), 13,
                        perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)})
        baseline_path = common.BUILD / "soc-return-control-soc-return-control-20261006-r3-resume/receipt.json"
        baseline = json.loads(baseline_path.read_text())
        if baseline["status"] != "PASS_SOC_RETURN_CONTROL_AFFECTED_SHORT":
            raise RuntimeError("Recorded two-issue baseline did not pass")
        # Workload construction and every-retirement oracle must be identical.
        for name in ("simulator/gsim/harness/core.cpp", "src/test/scala/ooo/ThroughputPerfGsim.scala",
                     "simulator/gsim/control_stage.py", "simulator/gsim/throughput_perf.py"):
            if baseline["source_sha256"].get(name) != before[name]:
                raise RuntimeError("Performance workload/oracle drift: " + name)
        receipt["integer_measurements"] = measurements
        receipt["baseline_receipt_sha256"] = sha(baseline_path)
        receipt["performance_comparison"] = perf.compare_measurements(baseline["integer_measurements"], measurements)
        for mode in ("--timing-smoke", "--pipeline-recovery"):
            common.run([model / "run", ref, *payloads, mode], env=env, log=model / (mode[2:] + ".log"), timeout=180)
            receipt["checks"][mode[2:]] = (model / (mode[2:] + ".log")).read_text().strip()
        negative = subprocess.run([str(model / "run"), str(ref), *map(str, payloads), "--inject-mismatch"],
                                  env=env, capture_output=True, text=True, timeout=180)
        (model / "negative.log").write_text(negative.stdout + negative.stderr)
        if negative.returncode != 1 or "NEMU register mismatch" not in negative.stdout + negative.stderr:
            raise RuntimeError("Independent CPU negative control not rejected")
        receipt.setdefault("model_sha256", {})["integer-core"] = {
            str(p.relative_to(common.ROOT)): sha(p) for p in model.iterdir()
            if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        common.run(["python3", common.HERE / "rv64gc_native_short.py", "--tag", args.tag],
                   log=out / "native.log", timeout=1800)
        native = common.BUILD / ("rv64gc-native-" + args.tag) / "receipt.json"
        if json.loads(native.read_text())["status"] != "PASS_RV64GC_NATIVE_AFFECTED_SHORT":
            raise RuntimeError("Actual RV64GC CPU/current compressed board proof failed")
        receipt["native_receipt"] = str(native)
        receipt["native_receipt_sha256"] = sha(native)
        if before != {str(p.relative_to(common.ROOT)): sha(p) for p in sources}:
            raise RuntimeError("Source/oracle drift during batch; receipt withheld")
        receipt["status"] = "PASS_SOC_UART_MARGIN_AFFECTED_SHORT"
    except Exception as error:
        receipt["status"] = "FAILED"
        receipt["failure"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)


if __name__ == "__main__":
    main()
