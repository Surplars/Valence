"""Archive board-only ECO proof; CPU tests are reusable only if ALL inputs match."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parent", type=Path, required=True)
    ap.add_argument("--reset", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[2]
    if a.out.exists(): ap.error("preserve existing evidence")
    original = root / "build/fpga/native-timing-20261004-r1"
    previous = json.loads((original / "fixed-clock-inputs-r2.json").read_text())
    short_path = root / "build/gsim/native-timing-20261004-r3/receipt.json"
    short = json.loads(short_path.read_text())
    assert short["status"] == "PASS_NATIVE_TIMING_SHORT"
    for name, expected in short["source_sha256"].items():
        assert sha(root / name) == expected, "CPU short proof drift: " + name
    old_inputs = json.loads((original / "inputs-resume-r2.json").read_text())
    for name, expected in old_inputs["candidate_sha256"].items():
        assert sha(a.parent / name) == expected, "Parent snapshot drift: " + name
    dcp = a.parent / "implementation-fixed-clock/routed.dcp"
    assert sha(dcp) == "e9c02309a4180763f8b8637596ab18e26d5da6d4348086b2ab75e789f447f0d3"
    top = root / "fpga/zu15eg/soc_top_gmac_ddr.sv"
    expected_top = (a.parent / "board/soc_top_gmac_ddr.sv").read_text()
    changes = (
        ("    // Release PHY reset after 10ms on the un-gated AON clock. The carrier",
         "    // Keep PHY and TX reset asserted until all replicated IDELAYCTRLs are\n"
         "    // calibrated. Reassert on RDY loss; release is synchronized per domain.\n"
         "    // Release PHY reset after 10ms on the un-gated AON clock. The carrier"),
        ("wire phy_reset_request = board_reset | ui_reset | ~mmcm_locked;",
         "wire phy_reset_request = board_reset | ui_reset | ~mmcm_locked | ~delay_ready;"),
        ("    always @(posedge clk_tx or posedge soc_reset)\n        if (soc_reset) tx_reset_pipe <= 3'b111;",
         "    wire tx_reset_request = soc_reset | ~delay_ready;\n"
         "    always @(posedge clk_tx or posedge tx_reset_request)\n        if (tx_reset_request) tx_reset_pipe <= 3'b111;"))
    for old, new in changes:
        assert expected_top.count(old) == 1, "Unrecognized parent reset fragment"
        expected_top = expected_top.replace(old, new)
    assert top.read_text() == expected_top, "Unverified board top changes"
    assert sha(root / "fpga/zu15eg/native_rgmii.sv") == sha(a.parent / "boundary-fixed-clock/native_rgmii.sv")
    reset = json.loads((a.reset / "receipt.json").read_text())
    assert reset["status"] == "PASS_NATIVE_CALIBRATION_RESET_SHORT"
    assert reset["negative_checks"] == {"negative-phy": "PASS", "negative-tx": "PASS"}
    for name, expected in reset["input_sha256"].items():
        assert sha(Path(name)) == expected, "Reset proof drift: " + name
    bus = (a.candidate / "bus_skew.rpt").read_text()
    assert "Slack (VIOLATED)" not in bus
    skews = [float(value) for value in re.findall(r"Slack \(MET\)\s*:\s*([-+\d.]+)ns", bus)]
    assert skews and min(skews) >= 0
    timing = (a.candidate / "timing_summary.rpt").read_text()
    table = timing[timing.index("| Design Timing Summary"):]
    match = re.search(r"^\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\s+(\d+)\s*$", table, re.M)
    assert match, "Timing summary not parseable"
    values = match.groups()
    met = float(values[0]) >= 0 and float(values[4]) >= 0 and float(values[8]) >= 0
    a.out.mkdir(parents=True)
    for folder, source in (("reset", a.reset), ("routed", a.candidate)):
        dest = a.out / folder
        dest.mkdir()
        for f in source.iterdir():
            if f.is_file() and f.suffix in (".rpt", ".log", ".json", ".sv", ".tcl"):
                shutil.copy2(f, dest / f.name)
    names = ("soc_top_gmac_ddr.sv", "native_board_constraints.tcl", "native_gmac_pins.xdc",
             "repair_native_signoff.tcl", "review_native_io_options.tcl", "run_native_calibration_reset.py",
             "native_calibration_reset_tb.sv", "audit_native_local_signoff.py")
    frozen = a.out / "inputs"
    frozen.mkdir()
    for name in names: shutil.copy2(root / "fpga/zu15eg" / name, frozen / name)
    result = {
        "status": "ROUTED_TIMING_MET_PENDING_OTHER_SIGNOFF" if met else "CPU100_MET_BOARD_RGMII_TIMING_NOT_MET",
        "date": "2026-10-05", "issue_width": 2, "cpu_hz": 100000000,
        "aon_uart_hz": 50000000, "uart_baud": 460800, "f_d_enabled": False,
        "bit_generated": False, "bit_generation_deferred_by_user": True,
        "short_receipt_sha256": sha(short_path), "unchanged_short_inputs": len(short["source_sha256"]),
        "unchanged_parent_candidate_files": len(old_inputs["candidate_sha256"]),
        "parent_dcp_sha256": sha(dcp), "reset_receipt_sha256": sha(a.reset / "receipt.json"),
        "board": {"setup_wns_ns": float(values[0]), "setup_tns_ns": float(values[1]),
                  "setup_failing_endpoints": int(values[2]), "hold_whs_ns": float(values[4]),
                  "hold_ths_ns": float(values[5]), "hold_failing_endpoints": int(values[6]),
                  "pulse_slack_ns": float(values[8]), "pulse_failing_endpoints": int(values[10])},
        "bus_skew": {"status": "ALL_MET", "checks": len(skews), "minimum_slack_ns": min(skews),
                     "warning": "Actual(ns) is NOT Slack(ns); old negative-actual misparse corrected"},
        "input_sha256": {str(f.relative_to(root)): sha(f) for f in (root / "fpga/zu15eg" / n for n in names)},
        "report_sha256": {f.name: sha(f) for f in a.candidate.glob("*.rpt")},
        "routed_dcp": str(a.candidate / "routed.dcp"), "routed_dcp_sha256": sha(a.candidate / "routed.dcp"),
        "limitations": ["No board or FPU-enabled qualification; no bit generated.",
                        "Current source constraints also request managed/raw root alignment; diagnostic saved separately.",
                        "Only added reset gates and clock-root placement; CPU RTL/cycle behavior unchanged."]}
    (a.out / "completion.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"], "CPU-proof inputs=", result["unchanged_short_inputs"], "bus-skew-min=", min(skews))


if __name__ == "__main__": main()
