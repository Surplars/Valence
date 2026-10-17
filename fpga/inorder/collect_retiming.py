#!/usr/bin/env python3
"""Archive 200/300MHz STA from the same already synthesized I1 netlist; never imply new hardware."""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sha

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--base", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    package = args.package.resolve()
    base = args.base.resolve()
    original = json.loads(base.read_text())
    if original["status"] != "SYNTHESIS_SETUP_MEETS_100MHZ_ONLY":
        ap.error("exact original source/RTL-bound synthesis receipt required")
    checkpoint = Path(original["package"]) / "reports/synthesized.dcp"
    results = {}
    for mhz in (200, 300):
        folder = package / "reports" / ("cpu" + str(mhz))
        result = json.loads((folder / "result.json").read_text())
        summary = (folder / "timing_synth.rpt").read_text()
        row = re.search(r"(?m)^\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)"
                        r"\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)", summary)
        if not row or result["target_mhz"] != mhz:
            raise RuntimeError("target/summary mismatch")
        result["setup_failing_endpoints"] = int(row[3])
        result["hold_whs_ns"] = float(row[5])
        result["hold_failing_endpoints"] = int(row[7])
        result["timing_closed"] = False
        results[str(mhz)] = result
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh archive required")
    shutil.copytree(package / "reports", output / "reports")
    receipt = {"status": "TARGET_200_300_REANALYSIS_ONLY_NOT_MET_NOT_ROUTED",
               "base_receipt": str(base), "base_receipt_sha256": sha(base),
               "checkpoint": str(checkpoint), "checkpoint_sha256": sha(checkpoint),
               "targets": results, "no_additional_synthesis": True,
               "current_hardware_is_five_stage_baseline": True,
               "new_user_direction": "pipeline depth may expand; evaluate 7-8-stage FPGA-first CPU toward 300MHz",
               "physical_qualified": False, "bit_generated": False,
               "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps(results, indent=2))
    print("RECEIPT", output / "receipt.json", flush=True)
if __name__ == "__main__":
    main()
