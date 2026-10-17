#!/usr/bin/env python3
"""Archive a routed internal OOC diagnostic; never issue board/bit qualification."""
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

def path_result(path):
    text = path.read_text()
    result = {}
    for label in ("Source", "Destination", "Data Path Delay", "Logic Levels"):
        match = re.search(r"(?m)^\s*" + re.escape(label) + r":\s*(.+)", text)
        if not match:
            raise RuntimeError("missing routed path field: " + label)
        result[label] = match[1].strip()
    match = re.search(r"Slack \((?:VIOLATED|MET)\)\s*:\s*([+-]?\d+\.\d+)ns", text)
    if not match:
        raise RuntimeError("missing routed slack")
    result["slack_ns"] = float(match[1])
    return result

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--synth-receipt", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads((args.package / "manifest.json").read_text())
    for name, digest in manifest["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("qualified source drift: " + name)
    for name, digest in manifest["files_sha256"].items():
        if sha(args.package / name) != digest:
            raise RuntimeError("qualified input drift: " + name)
    synthesis = json.loads(args.synth_receipt.read_text())
    if synthesis["rtl_manifest_sha256"] != sha(args.package / "manifest.json"):
        raise RuntimeError("synthesis provenance mismatch")
    physical = args.package / "physical-diagnostic"
    log = args.package / "vivado_route_diagnostic.log"
    if "I1_INTERNAL_OOC_ROUTING_DONE NOT_BOARD_NOT_MIG_NO_BIT" not in log.read_text():
        raise RuntimeError("missing actual route completion marker")
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh archive required")
    output.mkdir(parents=True)
    for p in physical.glob("*.rpt"):
        shutil.copy2(p, output / p.name)
    shutil.copy2(log, output / log.name)
    shutil.copy2(args.package / "vivado_routed_internal.log", output / "vivado_routed_internal.log")
    result = {"status": "ROUTED_INTERNAL_OOC_FAILS_300MHZ_NO_BIT",
        "target_hz": manifest["target_hz"], "physical_qualified": False, "board_qualified": False,
        "bit_generated": False, "source_sha256": manifest["source_sha256"],
        "synthesis_receipt_sha256": sha(args.synth_receipt),
        "rtl_manifest_sha256": sha(args.package / "manifest.json"),
        "original_package": str(args.package.resolve()),
        "routed_dcp_sha256": sha(physical / "routed.dcp"),
        "setup": path_result(physical / "setup_internal_routed.rpt"),
        "internal_hold": path_result(physical / "hold_internal_routed.rpt"),
        "global_hold": path_result(physical / "hold_routed.rpt"),
        "scope": "internal shell only; hypothetical BUFGCE location, synchronous zero-budget placeholder I/O. "
                 "No real board clock/MIG, DDR CDC, pin/DRC/board signoff. Do not infer board Fmax.",
        "collector_sha256": sha(Path(__file__)),
        "archive_sha256": {str(p.relative_to(output)): sha(p) for p in output.iterdir() if p.is_file()}}
    if result["setup"]["slack_ns"] >= 0:
        raise RuntimeError("review status for unexpectedly nonnegative setup; still not board signoff")
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "setup", "internal_hold", "global_hold")}, indent=2))
if __name__ == "__main__":
    main()
