#!/usr/bin/env python3
"""Freeze-check initialization-only board repair against the unchanged RTL baseline."""
import argparse
import json
from pathlib import Path
from export_board_cpu import ROOT, sha, validate_bootrom_proof


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads((args.board / "board-manifest.json").read_text())
    old = json.loads((args.baseline / "board-manifest.json").read_text())
    for key in ("flags", "cpu_hz", "uart_hz", "aon_hz", "ddr_ui_hz", "cache_bytes_each", "ddr_bytes", "mac"):
        if manifest[key] != old[key]:
            raise RuntimeError("board configuration changed: " + key)
    for collection, root in (("source_sha256", ROOT), ("source_resources", ROOT),
                             ("files_sha256", args.board), ("reused_ip_sha256", args.board / "project")):
        for name, digest in manifest[collection].items():
            if sha(root / name) != digest:
                raise RuntimeError(collection + " drift: " + name)
    before = {p.name: sha(p) for p in (args.baseline / "rtl").glob("*.sv")}
    after = {p.name: sha(p) for p in (args.board / "rtl").glob("*.sv")}
    if before != after or not before:
        raise RuntimeError("initialization-only repair changed RTL")
    for p in (args.board / "board").iterdir():
        if sha(p) != sha(args.baseline / "board" / p.name):
            raise RuntimeError("board wrapper/constraints changed: " + p.name)
    proof = validate_bootrom_proof(Path(manifest["bootrom_short_proof"]["receipt"]), manifest["flags"])
    if proof != manifest["bootrom_short_proof"]:
        raise RuntimeError("BootROM proof changed")
    result = {"status": "PASS_INITIALIZATION_ONLY_STAGE", "identical_rtl_files": len(before),
        "manifest_sha256": sha(args.board / "board-manifest.json"),
        "baseline": str(args.baseline), "baseline_manifest_sha256": sha(args.baseline / "board-manifest.json"),
        "bootrom_short_proof": proof, "physical_pass_inherited": False,
        "pre_synth_child_project_macro_rebound": True}
    report = args.board / "bootrom-prebuild-audit.json"
    if report.exists():
        if json.loads(report.read_text()) != result:
            raise RuntimeError("frozen prebuild audit changed")
    else:
        report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "identical_rtl_files": len(before)}, indent=2))


if __name__ == "__main__":
    main()
