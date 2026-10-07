"""Private short SDR-data/serializer-clock boundary test. No CPU/bit claim."""
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
    if a.output.exists(): ap.error("fresh evidence directory required")
    here = Path(__file__).resolve().parent
    inputs = [here / n for n in ("native_tx_overlap_serial_probe.sv", "native_tx_overlap_serial_tb.sv", "native_tx_reset_boundary.sv")]
    inputs += [Path(__file__), a.vivado_bin.parent / "data/verilog/src/glbl.v"]
    before = {str(p): sha(p) for p in inputs}
    a.output.mkdir(parents=True)
    for p in inputs:
        if p.suffix in (".sv", ".v"): shutil.copy2(p, a.output / p.name)
    shutil.copy2(Path(__file__), a.output / "executed_runner.py")
    (a.output / "run.tcl").write_text("run all\nquit\n")
    report = {"status": "RUNNING", "input_sha256": before, "negative_checks": {}, "bit_generated": False,
              "scope": "private TX serializer/SDR-data pad and reset boundary only; not board STA/CDC/CPU proof"}

    def run(tool, args, log):
        p = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                           capture_output=True, text=True, timeout=90)
        output = p.stdout + p.stderr
        (a.output / log).write_text(output)
        return p.returncode, output

    failed = False
    try:
        code, output = run("xvlog", ["--sv", *[p.name for p in a.output.glob("*.sv")], "glbl.v"], "compile.log")
        if code: raise RuntimeError(output[-2400:])
        code, output = run("xelab", ["native_tx_overlap_serial_tb", "glbl", "-L", "unisims_ver", "-L", "secureip",
                                   "--snapshot", "tx_overlap_serial", "--timescale", "1ns/1ps"], "elaborate.log")
        if code: raise RuntimeError(output[-2400:])
        negatives = {"corrupt_data": ("PHY_RISING_SYMBOL",), "corrupt_control": ("PHY_FALLING_SYMBOL",),
                     "bad_phase": ("TXC_RISE_NOT_2NS", "TXC_FALL_NOT_6NS", "PHY_SETUP_EYE"),
                     "duplicate_breach": ("OVERLAP_SERIAL_UNUSED_EDGE_CHANGED", "PHY_SETUP_EYE"),
                     "quarter_breach": ("OVERLAP_SERIAL_UNUSED_EDGE_CHANGED", "PHY_SETUP_EYE"),
                     "seam_breach": ("OVERLAP_SERIAL_UNUSED_EDGE_CHANGED", "PHY_SETUP_EYE")}
        for case in ("positive", *negatives):
            args = ["tx_overlap_serial", "-tclbatch", "run.tcl"]
            if case != "positive": args += ["-testplusarg", case]
            code, output = run("xsim", args, case + ".log")
            if case == "positive":
                if code or "PASS_NATIVE_TX_OVERLAP_SERIAL_SHORT" not in output or "Fatal:" in output:
                    raise RuntimeError(output[-2400:])
            elif "Fatal:" not in output or not any(s in output for s in negatives[case]) or "PASS_NATIVE_TX_OVERLAP_SERIAL_SHORT" in output:
                raise RuntimeError("independent oracle did not reject " + case + ": " + output[-1200:])
            else: report["negative_checks"][case] = "PASS"
        report["status"] = "PASS_NATIVE_TX_OVERLAP_SERIAL_SHORT"
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_TX_OVERLAP_SERIAL_SHORT", failure=str(error))
    finally:
        if before != {str(p): sha(p) for p in inputs}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="Source drift")
        report["output_sha256"] = {p.name: sha(p) for p in a.output.iterdir()
                                  if p.is_file() and p.suffix in (".sv", ".v", ".log", ".tcl", ".py")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()


