#!/usr/bin/env python3
"""Record a completed candidate's real route; never reinterpret failed STA as a pass."""
import argparse
import csv
import json
from pathlib import Path
import re
from export_board_cpu import ROOT, sha, validate_bootrom_proof
from collect_bootrom_delivery import critical_cdc


def collect(board, reports, baseline):
    manifest = json.loads((board / "board-manifest.json").read_text())
    for collection, parent in (("files_sha256", board), ("source_sha256", ROOT),
                               ("source_resources", ROOT), ("reused_ip_sha256", board / "project")):
        for name, digest in manifest[collection].items():
            if sha(parent / name) != digest:
                raise RuntimeError("Frozen input drift: " + collection + "/" + name)
    proof = validate_bootrom_proof(Path(manifest["bootrom_short_proof"]["receipt"]), manifest["flags"])
    if proof != manifest["bootrom_short_proof"]:
        raise RuntimeError("BootROM proof drift")
    short_path = Path(manifest["short_receipt"])
    if sha(short_path) != manifest["short_receipt_sha256"]:
        raise RuntimeError("Short receipt drift")
    short = json.loads(short_path.read_text())
    if short["status"] != "PASS_I1_BANDWIDTH44_AFFECTED_SHORT_ONLY":
        raise RuntimeError("Explicit complete batch44 short proof required")
    golden = (board / "rtl/bootrom.hex").read_text().splitlines()
    for path in (board / "reports/bootrom_post_synth.txt", reports / "bootrom_post_route.txt"):
        lines = path.read_text().splitlines()
        if len(lines) != 514 or not lines[0].startswith("I1_BOOTROM_NETLIST_PASS") or lines[2:] != golden:
            raise RuntimeError("ROM content mismatch: " + str(path))
    timing = (reports / "timing_summary.rpt").read_text()
    rows = re.findall(r"(?m)^\s*((?:-?\d+\.\d+\s+){2}\d+\s+\d+\s+"
        r"(?:-?\d+\.\d+\s+){2}\d+\s+\d+\s+"
        r"(?:-?\d+\.\d+\s+){2}\d+\s+\d+)\s*$", timing)
    if len(rows) != 1:
        raise RuntimeError("Ambiguous timing summary")
    n = rows[0].split()
    passed = all(float(n[i]) >= 0 for i in (0, 4, 8)) and all(float(n[i]) == 0 for i in (1, 2, 5, 6, 9, 10))
    if passed != ("All user specified timing constraints are met." in timing):
        raise RuntimeError("Timing checks disagree")
    cdc = critical_cdc(reports / "cdc.rpt")
    if len(cdc) != 9 or cdc != critical_cdc(baseline / "cdc.rpt"):
        raise RuntimeError("CDC critical endpoint change requires review")
    skews = re.findall(r"Slack \((MET|VIOLATED)\)\s*:\s*(-?[\d.]+)ns", (reports / "bus_skew.rpt").read_text())
    if len(skews) != 20 or any(s != "MET" or float(v) < 0 for s, v in skews):
        raise RuntimeError("Bus skew coverage/failure")
    resource = (reports / "utilization_flat.rpt").read_text()
    def utilization(label):
        return float(re.search(r"^\| " + re.escape(label) + r"\s+\|\s*([\d.]+)", resource, re.M)[1])
    route = (reports / "route_status.rpt").read_text()
    def nets(label):
        return int(re.search(re.escape(label) + r"\.+\s*:\s*(\d+)", route)[1])
    if nets("# of routable nets") != nets("# of fully routed nets") or nets("# of nets with routing errors"):
        raise RuntimeError("Route incomplete")
    domains = list(csv.DictReader((reports / "domains.tsv").open(), delimiter="\t"))
    wanted = {"CPU300":3.333, "DDR_UI250":4.0, "AON50":20.0, "UART50":20.0}
    if {(r["domain"],r["delay"]) for r in domains} != {(d,t) for d in wanted for t in ("max","min")} or any(
            abs(float(r["period_ns"])-wanted[r["domain"]])>0.002 for r in domains):
        raise RuntimeError("Incomplete/changed clock domains")
    targets = list(csv.DictReader((reports / "target_timing.tsv").open(), delimiter="\t"))
    if len(targets) != 6:
        raise RuntimeError("Target STA coverage incomplete")
    result = dict(status="BATCH44_SHORT_BOOTROM_PASS_CPU300_" + ("TIMING_PASS" if passed else "TIMING_FAIL_NO_BIT"),
        board=str(board), reports=str(reports), board_manifest_sha256=sha(board / "board-manifest.json"),
        checkpoint_sha256=sha(reports / "real_board_routed.dcp"), cpu_hz=300000000, cache_bytes_each=32768,
        mac=False, multiclock_unchanged=True, setup_ns=float(n[0]), tns_ns=float(n[1]),
        setup_failing_endpoints=int(n[2]), hold_ns=float(n[4]), pulse_width_ns=float(n[8]), domains=domains,
        resources={label:utilization(label) for label in ("CLB LUTs","CLB Registers","Block RAM Tile","DSPs")},
        short_receipt=str(short_path), short_checks=len(short["checks"]),
        performance_gates=short["performance_gates"], stream_comparison=short["stream_comparison"],
        coremark_comparison=short["coremark_comparison"], bootrom_short=proof,
        synthesized_and_routed_rom_exact_bytes=4096, routed_nets=nets("# of fully routed nets"),
        existing_cdc_critical_endpoints=sorted(cdc), full_cdc_signoff=False,
        bus_skew_checks=len(skews), bus_skew_worst_ns=min(float(v) for _,v in skews), target_paths=targets,
        implementation_runs=1, bounded_postroute_attempts=int(reports.name != "reports"),
        bit_generated=(board / "bitstream/delivery.json").is_file(), board_tested=False, source_resource_drift=False,
        report_sha256={str(p.relative_to(board)):sha(p) for directory in (board / "reports",reports)
            for p in directory.iterdir() if p.is_file() and p.suffix in (".rpt",".tsv",".txt")},
        collector_sha256=sha(Path(__file__)))
    output = board / "batch44-result.json"
    if output.exists():
        raise RuntimeError("Preserve existing final result")
    output.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({k:result[k] for k in ("status","setup_ns","tns_ns","hold_ns","resources","target_paths")},indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--board",type=Path,required=True)
    ap.add_argument("--reports",choices=("reports","postroute-r1"),required=True)
    ap.add_argument("--baseline-reports",type=Path,required=True)
    args = ap.parse_args()
    board = args.board.resolve()
    if board.parent != Path("/mnt/e/VM/Share/Valence-rtl") or not board.name.startswith("orbital-i1-cpu300-board-"):
        ap.error("Explicit isolated board path required")
    collect(board,board/args.reports,args.baseline_reports.resolve())
