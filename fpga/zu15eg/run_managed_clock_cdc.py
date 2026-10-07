#!/usr/bin/env python3
"""Native short xsim of actual BUFGCE and retention handshake CDC only."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rtl", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    args = parser.parse_args()
    if args.output.exists(): parser.error("use a fresh output directory")
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    inputs = [*sorted(args.rtl.glob("*.sv")), here / "managed_clock_cdc_tb.sv", here / "cdc_run.tcl",
              args.vivado_bin.parent / "data/verilog/src/glbl.v"]
    sources = [root / name for name in ("src/main/scala/ip/clock/FpgaClockResources.scala",
        "src/main/scala/ip/bus/PeripheralClockControl.scala", "src/main/scala/ip/bus/ClockDomainCrossing.scala",
        "src/test/scala/ip/ClockManagementGsim.scala")]
    before = {str(p): digest(p) for p in inputs + sources + [Path(__file__)]}
    protected = {str(p): digest(p) for p in (root / "src/main/scala/core").rglob("*.scala")}
    if len(inputs) < 6: parser.error("incomplete exported clock CDC RTL")
    args.output.mkdir(parents=True)
    for p in inputs: shutil.copy2(p, args.output / p.name)
    report = {"status": "RUNNING", "scope": "BUFGCE/retention-handshake CDC only, no CMU CSR or CPU",
              "input_sha256": before, "protected_cpu_sha256": protected,
              "board_verified": False, "routed_timing_verified": False, "bit_generated": False}
    def run(tool, argv, log):
        result = subprocess.run([str(args.vivado_bin / (tool + ".bat")), *argv], cwd=args.output,
            capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        (args.output / log).write_text(output)
        return result.returncode, output
    failed = False
    try:
        for tool, argv, log in (
            ("xvlog", ["--sv", *[p.name for p in inputs if p.suffix in (".sv", ".v")]], "compile.log"),
            ("xelab", ["managed_clock_cdc_tb", "glbl", "-L", "unisims_ver", "--snapshot", "managed_clock_cdc",
                "--debug", "typical", "--timescale", "1ns/1ps"], "elaborate.log")):
            code, output = run(tool, argv, log)
            if code: raise RuntimeError(log + ": " + output[-2400:])
        code, output = run("xsim", ["managed_clock_cdc", "-tclbatch", "cdc_run.tcl"], "positive.log")
        if code or "MANAGED_CLOCK_CDC_PASS clock_cases=3 actual_BUFGCE=1" not in output:
            raise RuntimeError("positive failed: " + output[-2400:])
        code, negative = run("xsim", ["managed_clock_cdc", "-tclbatch", "cdc_run.tcl",
            "-testplusarg", "inject_clock"], "negative-clock.log")
        if "physical stopped-clock independent oracle mismatch" not in negative or "MANAGED_CLOCK_CDC_PASS" in negative:
            raise RuntimeError("independent physical-clock negative oracle did not reject")
        report.update(status="PASS_MANAGED_CLOCK_GATE_CDC_SHORT", physical_gate_model_verified=True,
            independent_negative="passed", positive_summary=[s for s in output.splitlines() if "CDC_PASS" in s])
    except BaseException as error:
        failed=True
        report.update(status="FAIL_MANAGED_CLOCK_GATE_CDC_SHORT", failure=str(error))
    finally:
        if before != {str(p): digest(p) for p in inputs + sources + [Path(__file__)]} or \
                protected != {name: digest(Path(name)) for name in protected}:
            failed=True
            report.update(status="FAIL_INPUT_DRIFT", failure="source/RTL drift during validation")
        report["output_sha256"] = {p.name: digest(p) for p in args.output.glob("*.log")}
        (args.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
