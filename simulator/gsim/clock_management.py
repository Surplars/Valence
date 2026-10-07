#!/usr/bin/env python3
"""Short CMU CSR/policy/TL and both production MMIO router variants; no CPU/bit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag): parser.error("unsafe tag")
    name = "clock-management-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    paths = list((ROOT / "src/main/scala").rglob("*.scala"))
    paths += [ROOT / "src/test/scala/ip/ClockManagementGsim.scala",
              ROOT / "src/test/scala/ip/ClockManagementSpec.scala", HERE / "harness/clock_management.cpp",
              Path(__file__), HERE / "run.py", HERE / "config/toolchain.json", ROOT / "build.mill"]
    before = {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}
    report = {"status": "running", "scope": "single-clock CMU CSR/TL/router/policy only",
              "source_sha256": before, "physical_gate_verified": False, "board_verified": False,
              "cpu_runtime_verified": False, "bit_generated": False}
    try:
        run(["mill", "-i", "IonSoC.test.testOnly", "ip.ClockManagementSpec"], log=output / "scala.log")
        run(["mill", "-i", "IonSoC.test.runMain", "ip.ClockManagementRtlMain", output / "rtl"],
            log=output / "rtl-export.log")
        gsim, cxx = setup(False)
        for mode, top, defines in (
            ("register", "ClockManagementGsim", {}),
            ("tl", "ClockManagementTlGsim", {"CMU_TL": 1}),
            ("serial", "ClockManagementRouterGsim", {"CMU_ROUTER": 1}),
            ("parallel", "ClockManagementRouterGsim", {"CMU_ROUTER": 1}),
        ):
            model = test(gsim, cxx, name + "/" + mode, "ip.ClockManagementGsimMain", top,
                         "clock_management.cpp", parameters=(mode,), defines=defines)
            negative = subprocess.run([str(model / "run"), "--inject-mismatch"], capture_output=True,
                text=True, timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            (model / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode != 1 or "CMU independent register oracle mismatch" not in negative.stderr:
                raise RuntimeError("independent negative oracle did not reject: " + mode)
            report[mode] = {"status": "passed", "independent_negative": "passed",
                "summary": (model / "test.log").read_text().strip(),
                "fir_sha256": digest(model / (top + ".fir")), "executable_sha256": digest(model / "run")}
        report["status"] = "PASS_CMU_SCOPED_GSIM"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if before != {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}:
            report.update(status="failed", failure="input source drift during validation")
        report["rtl_sha256"] = {str(p.relative_to(output)): digest(p)
                               for p in sorted((output / "rtl").rglob("*.sv"))}
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_CMU_SCOPED_GSIM": raise RuntimeError(report["failure"])
    print("CMU_SCOPED_PASS receipt=" + str(output / "receipt.json"), flush=True)


if __name__ == "__main__": main()
