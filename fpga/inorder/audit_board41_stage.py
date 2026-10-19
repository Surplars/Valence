#!/usr/bin/env python3
"""Freeze batch41 staged sources/IP/constraints after fresh CPU and BootROM proof."""
import argparse
import json
from pathlib import Path
from export_board_cpu import ROOT, sha, validate_bootrom_proof
from board_short_proof import validate_bandwidth41, validate_bandwidth42, validate_bandwidth43, validate_bandwidth44


def main(batch=41):
    if batch not in (41, 42, 43, 44):
        raise ValueError("explicit stage auditor profile required")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    args = ap.parse_args()
    board, baseline = args.board.resolve(), args.baseline.resolve()
    manifest = json.loads((board/"board-manifest.json").read_text())
    old = json.loads((baseline/"board-manifest.json").read_text())
    for key in ("flags", "cpu_hz", "uart_hz", "aon_hz", "ddr_ui_hz", "cache_bytes_each", "ddr_bytes", "mac"):
        if manifest[key] != old[key]:
            raise RuntimeError("board configuration changed: "+key)
    for collection, root in (("source_sha256", ROOT), ("source_resources", ROOT),
                             ("files_sha256", board), ("reused_ip_sha256", board/"project")):
        for name, digest in manifest[collection].items():
            if sha(root/name) != digest:
                raise RuntimeError(collection+" drift: "+name)
    for p in (board/"board").iterdir():
        if sha(p) != sha(baseline/"board"/p.name):
            raise RuntimeError("board wrapper/constraints changed: "+p.name)
    if manifest["reused_ip_sha256"] != old["reused_ip_sha256"]:
        raise RuntimeError("MIG/clock/AXI CDC IP checkpoint changed")
    short_path = Path(manifest["short_receipt"])
    short = json.loads(short_path.read_text())
    validate = {41: validate_bandwidth41, 42: validate_bandwidth42, 43: validate_bandwidth43,
                44: validate_bandwidth44}[batch]
    _, short_proof = validate(short, short_path, ROOT)
    if short["source_sha256"] != manifest["source_sha256"]:
        raise RuntimeError("exported RTL is not bound to the newly tested sources")
    proof = validate_bootrom_proof(Path(manifest["bootrom_short_proof"]["receipt"]), manifest["flags"])
    if proof != manifest["bootrom_short_proof"]:
        raise RuntimeError("BootROM proof changed")
    before = {p.name: sha(p) for p in (baseline/"rtl").glob("*.sv")}
    after = {p.name: sha(p) for p in (board/"rtl").glob("*.sv")}
    result = dict(status="PASS_BATCH"+str(batch)+"_STAGE_NOT_TIMING", manifest_sha256=sha(board/"board-manifest.json"),
        baseline=str(baseline), baseline_manifest_sha256=sha(baseline/"board-manifest.json"),
        bootrom_short_proof=proof, short_proof=short_proof, audited_rtl_files=len(after),
        identical_rtl_files=sum(before.get(n)==h for n, h in after.items()),
        changed_rtl_files=sorted(n for n, h in after.items() if before.get(n)!=h),
        removed_rtl_files=sorted(set(before)-set(after)),
        multiclock_constraints_and_ip_unchanged=True, original_ooo_sources_unchanged=True,
        physical_pass_inherited=False, pre_synth_child_project_macro_rebound=True,
        auditor_sha256=sha(Path(__file__)))
    output = board/"bootrom-prebuild-audit.json"
    if output.exists():
        raise RuntimeError("preserve previous prebuild audit")
    output.write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k: result[k] for k in ("status", "audited_rtl_files", "identical_rtl_files",
        "changed_rtl_files", "removed_rtl_files")}, indent=2))


if __name__ == "__main__":
    main()
