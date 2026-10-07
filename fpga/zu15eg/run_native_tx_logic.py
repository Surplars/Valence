"""Bounded independent TX pad oracle, all bytes/control symbols/reset epochs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output", type=Path)
    ap.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    a = ap.parse_args()
    if a.output.exists(): ap.error("use a fresh output directory")
    here = Path(__file__).resolve().parent
    inputs = [here / n for n in ("native_rx_clock.sv", "native_rgmii.sv", "native_tx_logic_tb.sv")]
    inputs += [Path(__file__), a.vivado_bin.parent / "data/verilog/src/glbl.v"]
    before = {str(f): sha(f) for f in inputs}
    a.output.mkdir(parents=True)
    for f in inputs:
        if f.suffix in (".sv", ".v"): shutil.copy2(f, a.output / f.name)
    (a.output / "run.tcl").write_text("run all\nquit\n")
    report = {"status": "RUNNING", "input_sha256": before,
              "scope": "TX DDR boundary only; no CPU, no SDF or hardware claim",
              "expected_bytes": 3072, "control_encodings": 4, "reset_epochs": 3,
              "negative_checks": {}, "bit_generated": False}
    def run(tool, args, log):
        p = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                           capture_output=True, text=True, timeout=90)
        output = p.stdout + p.stderr
        (a.output / log).write_text(output)
        return p.returncode, output
    failed = False
    try:
        for tool, args, log in (
            ("xvlog", ["--sv", "native_rx_clock.sv", "native_rgmii.sv", "native_tx_logic_tb.sv", "glbl.v"], "compile.log"),
            ("xelab", ["native_tx_logic_tb", "glbl", "-L", "unisims_ver", "--snapshot", "tx_logic",
                       "--timescale", "1ns/1ps"], "elaborate.log")):
            code, output = run(tool, args, log)
            if code: raise RuntimeError(log + ": " + output[-2000:])
        for case in ("positive", "corrupt_data", "corrupt_control"):
            args = ["tx_logic", "-tclbatch", "run.tcl"]
            if case != "positive": args += ["-testplusarg", case]
            code, output = run("xsim", args, case + ".log")
            if case == "positive":
                if code or "PASS_NATIVE_TX_LOGIC_SHORT" not in output or "Fatal:" in output:
                    raise RuntimeError("Positive: " + output[-2400:])
            elif "Fatal:" not in output or "PASS_NATIVE_TX_LOGIC_SHORT" in output:
                raise RuntimeError("Independent oracle did not reject " + case)
            else: report["negative_checks"][case] = "PASS"
        report["status"] = "PASS_NATIVE_TX_LOGIC_SHORT"
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_TX_LOGIC_SHORT", failure=str(error))
    finally:
        if before != {str(f): sha(f) for f in inputs}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="TX proof input drift")
        report["output_sha256"] = {f.name: sha(f) for f in a.output.iterdir()
                                  if f.is_file() and f.suffix in (".log", ".sv", ".v", ".tcl")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
