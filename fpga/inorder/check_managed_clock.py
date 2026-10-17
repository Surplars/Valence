#!/usr/bin/env python3
"""Short real-BUFGCE/retention CDC proof of the explicit balanced I1 clock option."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rtl", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--vivado", required=True, type=Path)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh output evidence required")
    top = args.rtl / "ManagedClockCdcTop.sv"
    if not top.exists() or "ContinuousClockBuffer" not in top.read_text():
        ap.error("export the explicit --balanced physical clock fixture")
    inputs = [*sorted(args.rtl.glob("*.sv")), HERE / "managed_clock_cdc_tb.sv",
              ROOT / "fpga/zu15eg/cdc_run.tcl", args.vivado / "data/verilog/src/glbl.v"]
    source_paths = [ROOT / name for name in (
        "src/main/scala/ip/clock/FpgaClockResources.scala",
        "src/main/scala/ip/bus/PeripheralClockControl.scala",
        "src/main/scala/ip/bus/ClockDomainCrossing.scala",
        "src/main/scala/ip/bus/CdcDataChannels.scala",
        "src/test/scala/inorder/I1ManagedClockCdcTop.scala",
        "fpga/inorder/managed_clock_cdc_tb.sv", "fpga/inorder/check_managed_clock.py")]
    frozen = {p.as_posix(): sha(p) for p in [*source_paths, *inputs]}
    output.mkdir(parents=True)
    for path in inputs:
        shutil.copy2(path, output / path.name)
    receipt = {"status": "RUNNING", "cases": {}, "physical_qualified": False, "board_qualified": False,
        "source_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in source_paths},
        "input_sha256": frozen,
        "scope": "two actual parallel BUFGCEs; always-running control plus gated retention; NOT routed timing"}
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    def run(name, arguments):
        command = [str(args.vivado / "bin" / (name + ".bat")), *arguments]
        if any('"' in x or "\n" in x for x in command):
            raise RuntimeError("unsafe simulator token")
        result = subprocess.run(" ".join('"' + x + '"' for x in command), cwd=output,
                                capture_output=True, text=True, timeout=120)
        return result.returncode, result.stdout + result.stderr
    save()
    try:
        for name, arguments in (
            ("xvlog", ["--sv", *[p.name for p in inputs if p.suffix in (".sv", ".v")]]),
            ("xelab", ["managed_clock_cdc_tb", "glbl", "-L", "unisims_ver",
                       "--snapshot", "balanced_clock_cdc", "--debug", "typical", "--timescale", "1ns/1ps"])):
            code, log = run(name, arguments)
            (output / (name + ".log")).write_text(log)
            if code:
                raise RuntimeError(name + " failed: " + log[-1800:])
        for key, injection in (("positive", None), ("negative", "inject_clock"), ("negative-mailbox", "inject_mailbox")):
            negative = injection is not None
            code, log = run("xsim", ["balanced_clock_cdc", "-tclbatch", "cdc_run.tcl",
                *(["-testplusarg", injection] if negative else [])])
            (output / (key + ".log")).write_text(log)
            if negative:
                marker = ("independent mailbox data/order/epoch oracle mismatch" if injection == "inject_mailbox"
                          else "physical stopped-clock independent oracle mismatch")
                if marker not in log or "MANAGED_CLOCK_CDC_PASS" in log:
                    raise RuntimeError("independent stopped-clock negative was not rejected")
                receipt["cases"][key] = "PASS_REJECTED_INDEPENDENT_CLOCK_OR_MAILBOX_MUTATION"
            elif code or "MANAGED_CLOCK_CDC_PASS clock_cases=3 actual_BUFGCE=2 raw_running=PASS" not in log:
                raise RuntimeError("balanced clock/retention proof failed: " + log[-1800:])
            else:
                receipt["cases"][key] = "PASS_3_RAW_CLOCK_RATES_BUSY_DRAIN_WAKE_RESET_MISSING_SOURCE"
            save()
        if frozen != {p.as_posix(): sha(p) for p in [*source_paths, *inputs]}:
            raise RuntimeError("clock proof inputs drifted")
        receipt["status"] = "PASS_I1_BALANCED_CLOCK_CDC_SHORT"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {p.relative_to(output).as_posix(): sha(p)
            for p in output.glob("*") if p.is_file() and p.name != "receipt.json"}
        save()
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}))


if __name__ == "__main__":
    main()
