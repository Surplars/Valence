"""Short proof of selected production TX clock/RGMII/reset, not whole-board STA."""
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
    compile_inputs = [here / n for n in ("native_gmac_divided_clock.sv", "native_rgmii.sv",
                      "native_tx_reset_boundary.sv", "native_tx_word_reset_boundary.sv", "native_tx_quarter_board_tb.sv")]
    compile_inputs.append(a.vivado_bin.parent / "data/verilog/src/glbl.v")
    top = here / "soc_top_gmac_ddr.sv"
    inputs = compile_inputs + [top, Path(__file__)]
    before = {str(p): sha(p) for p in inputs}
    text = top.read_text()
    assert "parameter TX_QUARTER_DDR = 1" in text and "parameter HARDWARE_PHY_INIT = 0" in text
    assert "native_gmac_quarter_clock clock_dut" in text
    assert ".TX_QUARTER_DDR(TX_QUARTER_DDR && FPGA_TX_CLOCK_SHIFT)" in text
    a.output.mkdir(parents=True)
    for p in compile_inputs: shutil.copy2(p, a.output / p.name)
    shutil.copy2(top, a.output / "sealed_soc_top_gmac_ddr.sv.txt")
    shutil.copy2(Path(__file__), a.output / "executed_runner.py")
    (a.output / "run.tcl").write_text("run all\nquit\n")
    report = dict(status="RUNNING", input_sha256=before, negative_checks={}, bit_generated=False,
                  actual_board_tx=True, clock_architecture="common_clk250_dedicated_oddr",
                  physical_tx_phase_ns=2.0, phy_tx_delay_enabled=False, phy_rx_delay_enabled=True,
                  hardware_phy_init_enabled=False, mac_hz=125000000, pad_hz=250000000,
                  scope="selected production TX clock/RGMII/reset modules and top-selection identity; no CPU/SDF/whole-board STA")

    def run(tool, args, log):
        p = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                           capture_output=True, text=True, timeout=90)
        output = p.stdout + p.stderr
        (a.output / log).write_text(output)
        return p.returncode, output

    failed = False
    try:
        code, output = run("xvlog", ["--sv", *[p.name for p in compile_inputs]], "compile.log")
        if code: raise RuntimeError(output[-2400:])
        code, output = run("xelab", ["native_tx_quarter_board_tb", "glbl", "-L", "unisims_ver", "-L", "secureip",
                                   "--snapshot", "tx_quarter_board", "--timescale", "1ns/1ps"], "elaborate.log")
        if code: raise RuntimeError(output[-2400:])
        negatives = {"corrupt_data": ("PHY_RISING_SYMBOL",), "corrupt_control": ("PHY_FALLING_SYMBOL",),
                     "bad_phase": ("TXC_RISE_NOT_2NS", "TXC_FALL_NOT_6NS", "PHY_SETUP_EYE"),
                     "duplicate_breach": ("QUARTER_DDR_UNUSED_EDGE_CHANGED", "PHY_SETUP_EYE"),
                     "capture_breach": ("PHY_RISING_SYMBOL", "PHY_FALLING_SYMBOL", "PHY_SETUP_EYE"),
                     "phase_stop": ("TXC_PERIOD", "TXC_RISE_NOT_2NS", "TXC_FALL_NOT_6NS", "PHY_SETUP_EYE")}
        for case in ("positive", *negatives):
            args = ["tx_quarter_board", "-tclbatch", "run.tcl"]
            if case != "positive": args += ["-testplusarg", case]
            code, output = run("xsim", args, case + ".log")
            if case == "positive":
                if code or "PASS_NATIVE_TX_QUARTER_BOARD_SHORT" not in output or "Fatal:" in output:
                    raise RuntimeError(output[-2400:])
            elif "Fatal:" not in output or not any(s in output for s in negatives[case]) or "PASS_NATIVE_TX_QUARTER_BOARD_SHORT" in output:
                raise RuntimeError("independent oracle did not reject " + case + ": " + output[-1200:])
            else: report["negative_checks"][case] = "PASS"
        report["status"] = "PASS_NATIVE_TX_QUARTER_BOARD_SHORT"
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_TX_QUARTER_BOARD_SHORT", failure=str(error))
    finally:
        if before != {str(p): sha(p) for p in inputs}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="Source drift")
        report["output_sha256"] = {p.name: sha(p) for p in a.output.iterdir()
                                  if p.is_file() and p.suffix in (".sv", ".v", ".log", ".tcl", ".py", ".txt")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
