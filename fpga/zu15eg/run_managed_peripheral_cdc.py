#!/usr/bin/env python3
"""Only production ingress/gate/bridge/counter CDC primitives; no UART/MAC engine xsim."""
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
    if args.output.exists(): parser.error("fresh output required")
    here = Path(__file__).resolve().parent
    inputs = [*sorted(args.rtl.glob("*.sv")), here / "managed_peripheral_cdc_tb.sv", here / "cdc_run.tcl",
              args.vivado_bin.parent / "data/verilog/src/glbl.v", Path(__file__)]
    before = {str(p): digest(p) for p in inputs}
    if len(inputs) < 8: parser.error("incomplete CDC export")
    if any("GmiiFrame" in p.name or "UartConsole" in p.name for p in inputs):
        parser.error("CDC-only authorization: real MAC/UART engines forbidden")
    args.output.mkdir(parents=True)
    for p in inputs: shutil.copy2(p, args.output / p.name)
    report = {"status": "RUNNING", "scope": __doc__, "input_sha256": before,
              "board_verified": False, "routed_timing_verified": False, "bit_generated": False}
    failed = False
    def run(tool, argv, log):
        process = subprocess.Popen([str(args.vivado_bin / (tool + ".bat")), *argv], cwd=args.output,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            output, _ = process.communicate(timeout=90)
        except subprocess.TimeoutExpired:
            # Windows .bat timeout otherwise leaves xelab descendants holding
            # the pipe indefinitely. Kill ONLY this invocation's process tree.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            output, _ = process.communicate(timeout=10)
            (args.output / log).write_text(output)
            raise RuntimeError(tool + " timeout (local child process tree stopped)")
        (args.output / log).write_text(output)
        return process.returncode, output
    try:
        for tool, argv, log in (
            ("xvlog", ["--sv", *[p.name for p in inputs if p.suffix in (".sv", ".v")]], "compile.log"),
            ("xelab", ["managed_peripheral_cdc_tb", "glbl", "-L", "unisims_ver", "--snapshot", "managed_ingress",
                "--debug", "typical", "--mt", "4", "--timescale", "1ns/1ps"], "elaborate.log")):
            code, output = run(tool, argv, log)
            if code: raise RuntimeError(log + ": " + output[-1800:])
        code, output = run("xsim", ["managed_ingress", "-tclbatch", "cdc_run.tcl"], "positive.log")
        if code or "MANAGED_PERIPHERAL_CDC_PASS" not in output:
            raise RuntimeError("positive failed: " + output[-1800:])
        report["summary"] = [s for s in output.splitlines() if "CDC_PASS" in s]
        for flag, marker in (("data", "managed ingress independent byte oracle mismatch"),
            ("counter", "managed ingress independent counter oracle mismatch")):
            code, negative = run("xsim", ["managed_ingress", "-tclbatch", "cdc_run.tcl",
                "-testplusarg", "inject_" + flag], "negative-" + flag + ".log")
            if marker not in negative or "MANAGED_PERIPHERAL_CDC_PASS" in negative:
                raise RuntimeError("independent negative did not reject: " + flag)
        report.update(status="PASS_MANAGED_PERIPHERAL_CDC_SHORT", physical_gate_model_verified=True,
            asynchronous_reset_verified=True, independent_negatives="passed")
    except BaseException as error:
        failed = True
        report.update(status="FAIL_MANAGED_PERIPHERAL_CDC_SHORT", failure=str(error))
    finally:
        if before != {str(p): digest(p) for p in inputs}:
            failed=True;report.update(status="FAIL_INPUT_DRIFT", failure="input drift")
        report["output_sha256"]={p.name:digest(p) for p in args.output.glob("*.log")}
        (args.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
