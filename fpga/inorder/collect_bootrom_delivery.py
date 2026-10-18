#!/usr/bin/env python3
"""Record a repaired bit only after independent file/report/ROM checks pass."""
import argparse
import csv
import json
from pathlib import Path
import re
from export_board_cpu import ROOT, sha, validate_bootrom_proof


def critical_cdc(path):
    result = set()
    for line in path.read_text().splitlines():
        if re.match(r"\s*\d+\s+CDC-\d+\s+Critical\s", line):
            fields = line.split()
            result.add((fields[1], *fields[-2:]))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board", type=Path, required=True)
    ap.add_argument("--reports", type=Path, required=True)
    ap.add_argument("--baseline-reports", type=Path, required=True)
    args = ap.parse_args()
    board = args.board.resolve(); reports = args.reports.resolve()
    if board not in reports.parents or board.parent != Path("/mnt/e/VM/Share/Valence-rtl"):
        ap.error("explicit isolated board/report paths required")
    out = board / "bitstream"; destination = out / "delivery.json"
    if destination.exists():
        ap.error("preserve previous delivery")
    manifest = json.loads((board / "board-manifest.json").read_text())
    for collection, root in (("files_sha256", board), ("source_sha256", ROOT),
                             ("reused_ip_sha256", board / "project")):
        for name, digest in manifest[collection].items():
            if sha(root / name) != digest:
                raise RuntimeError(collection + " changed: " + name)
    proof = validate_bootrom_proof(Path(manifest["bootrom_short_proof"]["receipt"]), manifest["flags"])
    if proof != manifest["bootrom_short_proof"]:
        raise RuntimeError("short proof changed")
    golden = (board / "rtl/bootrom.hex").read_text().splitlines()
    audit = json.loads((board / "bootrom-prebuild-audit.json").read_text())
    if audit.get("manifest_sha256") != sha(board / "board-manifest.json"):
        raise RuntimeError("prebuild audit refers to another board")
    fresh_checker = audit.get("status") in ("PASS_BATCH41_STAGE_NOT_TIMING", "PASS_BATCH42_STAGE_NOT_TIMING",
                                           "PASS_BATCH43_STAGE_NOT_TIMING", "PASS_BATCH44_STAGE_NOT_TIMING")
    synth_rom = board / ("reports/bootrom_post_synth.txt" if fresh_checker else
                         "release-audit/bootrom_post_synth_full64.txt")
    for path in (synth_rom, reports / "bootrom_post_route.txt", out / "bootrom_pre_bit.txt"):
        lines = path.read_text().splitlines()
        if len(lines) != 514 or not lines[0].startswith("I1_BOOTROM_NETLIST_PASS") or lines[2:] != golden:
            raise RuntimeError("actual full-word netlist evidence mismatch: " + str(path))
    timing = (out / "timing_summary.rpt").read_text()
    if "All user specified timing constraints are met." not in timing:
        raise RuntimeError("timing not met")
    matches = re.findall(r"(?m)^\s*((?:-?\d+\.\d+\s+){2}\d+\s+\d+\s+"
                         r"(?:-?\d+\.\d+\s+){2}\d+\s+\d+\s+"
                         r"(?:-?\d+\.\d+\s+){2}\d+\s+\d+)\s*$", timing)
    if len(matches) != 1:
        raise RuntimeError("ambiguous design-wide timing summary")
    numbers = matches[0].split()
    if any(float(numbers[n]) < 0 for n in (0, 4, 8)) or any(float(numbers[n]) != 0 for n in (1, 2, 5, 6, 9, 10)):
        raise RuntimeError("setup/hold/pulse failures")
    domains = list(csv.DictReader((reports / "domains.tsv").open(), delimiter="\t"))
    wanted = {"CPU300": 3.3333333333, "DDR_UI250": 4.0, "AON50": 20.0, "UART50": 20.0}
    if {(r["domain"], r["delay"]) for r in domains} != {(n, d) for n in wanted for d in ("max", "min")}:
        raise RuntimeError("domain coverage missing")
    if any(abs(float(r["period_ns"]) - wanted[r["domain"]]) > 0.002 or float(r["slack_ns"]) < 0 for r in domains):
        raise RuntimeError("domain frequency/timing failed")
    cdc = critical_cdc(reports / "cdc.rpt")
    baseline_cdc = critical_cdc(args.baseline_reports / "cdc.rpt")
    if len(cdc) != 9 or cdc != baseline_cdc:
        raise RuntimeError("CDC critical endpoints changed; review required")
    skews = re.findall(r"Slack \((MET|VIOLATED)\)\s*:\s*(-?[\d.]+)ns", (reports / "bus_skew.rpt").read_text())
    if not skews or any(state != "MET" or float(value) < 0 for state, value in skews):
        raise RuntimeError("bus skew not met")
    bit = out / "orbital_i1_rv64gc_cpu300_i32k_d32k_uart460800_jtag65_nomac_bootrom.bit"
    if bit.stat().st_size < 1000000 or "BIT_GENERATED_FROM_REVIEWED_ROUTED_DCP" not in (out / "result.txt").read_text():
        raise RuntimeError("bit generation result missing")
    result = {"status": "PASS_REPAIRED_ROM_ROUTED_TIMING_BIT_NOT_BOARD_TESTED", "bit": str(bit),
        "bit_sha256": sha(bit), "bit_bytes": bit.stat().st_size,
        "board_manifest_sha256": sha(board / "board-manifest.json"),
        "checkpoint": str(reports / "real_board_routed.dcp"),
        "checkpoint_sha256": sha(reports / "real_board_routed.dcp"),
        "setup_ns": float(numbers[0]), "hold_ns": float(numbers[4]), "pulse_width_ns": float(numbers[8]),
        "domains": domains, "bootrom_short": proof, "bus_skew_constraints_met": len(skews),
        "existing_cdc_critical_endpoints": sorted(cdc), "full_cdc_signoff": False, "board_tested": False,
        "source_resource_revisions_after_export": {name: {"exported": digest, "current": sha(ROOT / name)}
            for name, digest in manifest["source_resources"].items() if sha(ROOT / name) != digest},
        "report_format_note": "Full64 display and comparison in all three netlist gates." if fresh_checker else
                              "Frozen synthesis checker compared all 64 bits; release checker fixes only Tcl hex formatting."
                              " Actual full-width content is re-read from synthesis and selected routed DCPs.",
        "release_tools_sha256": {p.name: sha(p) for p in (board / "release-tools").glob("*.tcl")},
        "collector_sha256": sha(Path(__file__)),
        "reports_sha256": {str(p.relative_to(board)): sha(p) for directory in (out, reports, board / "release-audit")
            for p in (directory.iterdir() if directory.exists() else [])
            if p.is_file() and p.suffix in (".rpt", ".txt", ".tsv")}}
    changed = result["source_resource_revisions_after_export"]
    if set(changed) - {"fpga/inorder/audit_board_bootrom.tcl"}:
        raise RuntimeError("unexpected post-export source-tool changes")
    if fresh_checker and changed:
        raise RuntimeError("batch41 release requires unchanged frozen source tools")
    destination.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "bit_sha256", "setup_ns", "hold_ns")}, indent=2))


if __name__ == "__main__":
    main()
