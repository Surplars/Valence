"""Prove a source-matched local clock repair, not whole-board signoff."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path, required=True)
    ap.add_argument("--inputs", type=Path, required=True)
    ap.add_argument("--short", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parents[2]
    if args.out.exists():
        raise RuntimeError("Preserve existing evidence")
    frozen = json.loads(args.inputs.read_text())
    assert frozen["status"] == "PASS_INPUTS_AND_SHORT_BOUNDARY_NOT_BOARD_SIGNOFF"
    for name, expected in frozen["candidate_sha256"].items():
        assert sha(args.parent / name) == expected, f"Parent changed: {name}"
    proof = json.loads(args.short.read_text())
    assert proof["status"] == "PASS_NATIVE_TIMING_SHORT"
    for name, expected in proof["source_sha256"].items():
        assert sha(repo / name) == expected, f"Short-proof input changed: {name}"
    old = (args.parent / "board/native_rgmii.sv").read_text()
    original = "            .DATAOUT(delayed_rx[lane]), .CLK(delay_clock), .CE(1'b0), .INC(1'b0),"
    replacement = (
        "            // UG571: CLK is unused in FIXED mode. REFCLK remains 500MHz on\n"
        "            // IDELAYCTRL; do not clock the slower dynamic-control port with it.\n"
        "            .DATAOUT(delayed_rx[lane]), .CLK(1'b0), .CE(1'b0), .INC(1'b0),"
    )
    assert old.count(original) == 1
    current = repo / "fpga/zu15eg/native_rgmii.sv"
    assert current.read_text() == old.replace(original, replacement)
    boundary = args.parent / "boundary-fixed-clock"
    assert sha(current) == sha(boundary / "native_rgmii.sv")
    tb = repo / "fpga/zu15eg/native_rgmii_tb.sv"
    assert sha(tb) == sha(boundary / tb.name)
    assert sha(tb) == sha(args.parent / "boundary-calibrated" / tb.name)
    positive = (boundary / "positive.log").read_text()
    assert "PASS_RGMII_DDR_BOUNDARY" in positive
    assert "Fatal:" not in positive and "Error:" not in positive
    for name, failure in (("negative-tx.log", "Fatal: TX ordered byte"),
                          ("negative-rx.log", "Fatal: RX ordered byte")):
        log = (boundary / name).read_text()
        assert failure in log and "PASS_RGMII" not in log
    args.out.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "status": "PASS_SOURCE_MATCHED_FIXED_CLK_REPAIR_NOT_BOARD_SIGNOFF",
        "parent_inputs_sha256": sha(args.inputs),
        "short_receipt_sha256": sha(args.short),
        "unchanged_short_source_count": len(proof["source_sha256"]),
        "unchanged_frozen_candidate_count": len(frozen["candidate_sha256"]),
        "old_boundary_sha256": sha(args.parent / "board/native_rgmii.sv"),
        "fixed_boundary_sha256": sha(current),
        "repair_script_sha256": sha(repo / "fpga/zu15eg/repair_rgmii_fixed_clock.tcl"),
        "positive_and_two_negatives": "PASS",
        "scope": "Only five FIXED IDELAYE3 CLK inputs: 500MHz -> GND. REFCLK unchanged.",
        "bit_generated": False,
    }
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
