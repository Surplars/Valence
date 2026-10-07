"""Short independent centered-TXC and pin-level RTL8211F initialization checks."""
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
    ap.add_argument("--rtl", type=Path, default=Path(r"E:\VM\Share\Valence-rtl\native-timing-20261004-r1\rtl"))
    ap.add_argument("--vivado-bin", type=Path, default=Path(r"E:\Xilinx\2025.1\Vivado\bin"))
    ap.add_argument("--clock-only", action="store_true", help="Affected software-PHY board mode only")
    ap.add_argument("--pll-pair", action="store_true", help="Local TX PLL plus separate calibration PLL")
    ap.add_argument("--calibrated-clock", action="store_true", help="Shared raw clock and calibrated TXC cascade")
    ap.add_argument("--divider-clock", action="store_true", help="Two DIV4s with common physical REF500 source")
    a = ap.parse_args()
    if sum((a.pll_pair, a.calibrated_clock, a.divider_clock))>1: ap.error("select one clock architecture")
    if a.output.exists(): ap.error("use a fresh directory")
    here = Path(__file__).resolve().parent
    inputs = [here / n for n in ("native_gmac_clocks.sv", "native_rgmii.sv", "native_tx90_tb.sv",
                                 "native_tx_reset_boundary.sv", "native_phy_tx_init.sv", "native_phy_tx_init_tb.sv")]
    inputs += [a.rtl / "MdioClause22.sv", Path(__file__), a.vivado_bin.parent / "data/verilog/src/glbl.v"]
    if a.pll_pair: inputs.append(here / "native_gmac_pll_pair.sv")
    if a.divider_clock: inputs.append(here / "native_gmac_divided_clock.sv")
    if a.calibrated_clock: inputs += [here / n for n in ("native_tx_common_delay.sv", "native_tx_calibrated_tb.sv", "native_rx_clock.sv")]
    before = {str(f): sha(f) for f in inputs}
    a.output.mkdir(parents=True)
    for f in inputs:
        if f.suffix in (".sv", ".v"): shutil.copy2(f, a.output / f.name)
    if a.pll_pair:
        tb = a.output / "native_tx90_tb.sv"
        original = tb.read_text()
        if original.count("native_gmac_eth_clock clock_dut") != 1:
            raise RuntimeError("TX oracle clock instance changed unexpectedly")
        tb.write_text(original.replace("native_gmac_eth_clock clock_dut", "native_gmac_pll_pair clock_dut"))
    if a.divider_clock:
        tb = a.output / "native_tx90_tb.sv"
        original = tb.read_text()
        if original.count("native_gmac_eth_clock clock_dut")!=1: raise RuntimeError("TX oracle clock instance changed")
        rewritten=original.replace("native_gmac_eth_clock clock_dut", "native_gmac_divided_clock clock_dut")
        pad_anchor=".tx_source(source), .tx_forward_source(forward_source), .delay_source(ref_source), .locked(locked));"
        if rewritten.count(pad_anchor)!=1: raise RuntimeError("TX clock wiring oracle anchor changed")
        rewritten=rewritten.replace(pad_anchor, pad_anchor.replace(".tx_source(source)", ".tx_source(source), .tx_pad_source(pad_source)"))
        rewritten=rewritten.replace("wire source, forward_source, ref_source, locked, raw, forward_clock, ref_clock;", "wire source, pad_source, forward_source, ref_source, locked, raw, forward_clock, ref_clock;")
        if rewritten.count(".tx_pad_clock(raw)")!=1: raise RuntimeError("TX pad clock oracle anchor changed")
        rewritten=rewritten.replace(".tx_pad_clock(raw)", ".tx_pad_clock(pad_source)")
        rewritten=rewritten.replace("real last_raw=0, last_forward=0, last_ref=0;", """real last_raw=0, last_forward=0, last_ref=0;
    always @(posedge pad_source) if(locked) begin
        #0.002;
        if(raw!==1'b1 || $realtime-last_raw>0.003) $fatal(1,"Pad-only clock must have raw phase");
    end""")
        marker="repeat(8) @(negedge raw);\n        end"
        if rewritten.count(marker)!=1: raise RuntimeError("Cold-relock oracle anchor changed")
        rewritten=rewritten.replace(marker, "repeat(8) @(negedge raw);\n            if(epoch<2) begin\n                cold_reset=1; last_raw=0; last_forward=0; last_ref=0;\n                #123.17; cold_reset=0; wait(locked); repeat(10) @(negedge raw);\n            end\n        end")
        tb.write_text(rewritten)
    (a.output / "run.tcl").write_text("run all\nquit\n")
    report = {"status": "RUNNING", "input_sha256": before, "physical_tx_phase_ns": 2.0,
              "phy_tx_delay_enabled": False, "phy_rx_delay_enabled": True,
              "scope": "TX boundary and independent pin-level PHY only; no CPU/SDF/hardware claim",
              "bit_generated": False, "positive_cases": [], "negative_checks": {}}
    report["clock_architecture"] = "local_pll_pair" if a.pll_pair else "mmcm_quarter_phase"
    if a.divider_clock: report["clock_architecture"]="common_ref500_div4_phases"
    if a.divider_clock: report["pad_clock_isolated"] = True
    if a.calibrated_clock:
        report["clock_architecture"] = "shared_clock_calibrated_txc"
        report.pop("physical_tx_phase_ns")
        report["calibrated_clock_delay_programmed_ps"] = 1600
    def run(tool, args, log):
        p = subprocess.run([str(a.vivado_bin / (tool + ".bat")), *args], cwd=a.output,
                           capture_output=True, text=True, timeout=90)
        output = p.stdout + p.stderr
        (a.output / log).write_text(output)
        return p.returncode, output
    failed = False
    try:
        code, output = run("xvlog", ["--sv", *[f.name for f in a.output.glob("*.sv")], "glbl.v"], "compile.log")
        if code: raise RuntimeError(output[-2000:])
        tops = [("native_tx_calibrated_tb" if a.calibrated_clock else "native_tx90_tb", "tx90")]
        if not a.clock_only: tops.append(("native_phy_tx_init_tb", "phy_init"))
        for top, snapshot in tops:
            code, output = run("xelab", [top, "glbl", "-L", "unisims_ver", "--snapshot", snapshot,
                                          "--timescale", "1ns/1ps"], snapshot + "-elaborate.log")
            if code: raise RuntimeError(output[-2400:])
        for case in ("positive", "corrupt_data", "corrupt_control", "bad_phase"):
            args = ["tx90", "-tclbatch", "run.tcl"]
            if case != "positive": args += ["-testplusarg", case]
            code, output = run("xsim", args, "tx90-" + case + ".log")
            if case == "positive":
                if code or "PASS_NATIVE_TX90_SHORT" not in output or "Fatal:" in output:
                    raise RuntimeError(output[-2400:])
                report["positive_cases"].append("tx90")
            elif "Fatal:" not in output or "PASS_NATIVE_TX90_SHORT" in output:
                raise RuntimeError("TX oracle failed to reject " + case)
            else: report["negative_checks"][case] = "PASS"
        phy_cases = () if a.clock_only else ("positive", "phy0", "phy31", "no_phy", "wrong_id", "no_ack",
                     "page_stuck", "tx_stuck", "rx_stuck", "restore_stuck")
        for case in phy_cases:
            args = ["phy_init", "-tclbatch", "run.tcl"]
            if case != "positive": args += ["-testplusarg", case]
            code, output = run("xsim", args, "phy-" + case + ".log")
            if code or "PASS_NATIVE_PHY_TX_INIT" not in output or "Fatal:" in output:
                raise RuntimeError(case + ": " + output[-2400:])
            report["positive_cases"].append("phy-" + case)
        report["status"] = ("PASS_NATIVE_TX_CALIBRATED_SHORT" if a.calibrated_clock else "PASS_NATIVE_TX90_SHORT") if a.clock_only else "PASS_NATIVE_TX90_PHY_SHORT"
        report["hardware_phy_init_enabled"] = not a.clock_only
    except BaseException as error:
        failed = True
        report.update(status="FAIL_NATIVE_TX90_PHY_SHORT", failure=str(error))
    finally:
        if before != {str(f): sha(f) for f in inputs}:
            failed = True
            report.update(status="FAIL_INPUT_DRIFT", failure="Source drift")
        report["output_sha256"] = {f.name: sha(f) for f in a.output.iterdir()
                                  if f.is_file() and f.suffix in (".sv", ".v", ".log", ".tcl")}
        (a.output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    if failed: raise SystemExit(report.get("failure", "failed"))


if __name__ == "__main__": main()
