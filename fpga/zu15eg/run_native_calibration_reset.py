"""Short xsim of the actual board reset fragment; no CPU or whole-board sim."""
import argparse
import hashlib
import json
from pathlib import Path
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
    top = here / "soc_top_gmac_ddr.sv"
    tb = here / "native_calibration_reset_tb.sv"
    protected = {str(f): sha(f) for f in (top, tb, Path(__file__))}
    text = top.read_text()
    fragment = text[text.index("    wire phy_reset_request ="):text.index("    wire [7:0] gmii_tx_data")]
    assert "| ~delay_ready;" in fragment
    wrapper = """`timescale 1ns/1ps
module native_calibration_reset_fragment(
 input clk_aon, clk_tx, eth_rxc, board_reset, ui_reset, mmcm_locked, soc_reset, delay_ready,
 output eth_reset_gate, tx_reset, rx_reset);
 wire clk_rx;
"""
    suffix = "\nassign tx_reset=tx_reset_pipe[2]; assign rx_reset=rx_reset_pipe[2];\nendmodule\n"
    a.output.mkdir(parents=True)
    (a.output / tb.name).write_bytes(tb.read_bytes())
    (a.output / "run.tcl").write_text("run all\nquit\n")
    report = {"status": "RUNNING", "input_sha256": protected,
              "scope": "Actual PHY/TX/RX board reset fragment, UNISIM IBUF/BUFG; no CPU",
              "negative_checks": {}, "bit_generated": False}
    def run(tool, args, log):
        result = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                                capture_output=True, text=True, timeout=90)
        output = result.stdout + result.stderr
        (a.output / log).write_text(output)
        return result.returncode, output
    failed = False
    try:
        for case in ("positive", "negative-phy", "negative-tx"):
            current = fragment
            if case == "negative-phy":
                current = current.replace("~mmcm_locked | ~delay_ready;", "~mmcm_locked;", 1)
            if case == "negative-tx":
                current = current.replace("wire tx_reset_request = soc_reset | ~delay_ready;",
                                          "wire tx_reset_request = soc_reset;", 1)
            (a.output / "fragment.sv").write_text(wrapper + current + suffix)
            for tool, args in (
                ("xvlog", ["--sv", "fragment.sv", tb.name,
                           str(a.vivado_bin.parent / "data/verilog/src/glbl.v")]),
                ("xelab", ["native_calibration_reset_tb", "glbl", "-L", "unisims_ver",
                           "--snapshot", "cal_reset_" + case, "--timescale", "1ns/1ps"])):
                code, output = run(tool, args, case + "-" + tool + ".log")
                if code: raise RuntimeError(case + " " + tool + ": " + output[-1200:])
            code, output = run("xsim", ["cal_reset_" + case, "-tclbatch", "run.tcl"], case + ".log")
            if case == "positive":
                if code or "PASS_NATIVE_CALIBRATION_RESET" not in output or "Fatal:" in output:
                    raise RuntimeError("Positive failed: " + output[-2000:])
            elif "Fatal: Calibration unavailable reset oracle" not in output or "PASS_NATIVE" in output:
                raise RuntimeError("Independent oracle did not reject " + case)
            else: report["negative_checks"][case] = "PASS"
        (a.output / "fragment.sv").write_text(wrapper + fragment + suffix)
        report["status"] = "PASS_NATIVE_CALIBRATION_RESET_SHORT"
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_CALIBRATION_RESET_SHORT", failure=str(error))
    finally:
        if protected != {name: sha(Path(name)) for name in protected}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="Source changed during validation")
        report["output_sha256"] = {f.name: sha(f) for f in a.output.glob("*.log")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
