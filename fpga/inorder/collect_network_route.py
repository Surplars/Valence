#!/usr/bin/env python3
"""Archive a bounded network OOC implementation, never qualify a board or bit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from audit_network_cdc import audit
from collect_network import path_entry
from collect_route_optimization import routing, summary, timing_met

ROOT = Path(__file__).resolve().parents[2]
STAGES = ("placed", "pre_route_physopt", "first_route", "final_route")
SCOPES = ("setup_global", "hold_global", "setup_internal", "hold_internal",
          "setup_cpu", "hold_cpu", "hold_cpu_internal", "hold_uart_raw_to_gated")
INTERNAL_SCOPES = ("setup_cpu_internal", "setup_core_internal", "hold_core_internal")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stage_results(text, log):
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    if tuple(row["stage"] for row in rows) != STAGES:
        raise ValueError("incomplete or duplicate implementation stages")
    for row in rows:
        marker = re.search(
            r"(?m)^I1_NETWORK_PHYSICAL_STAGE stage=" + row["stage"] +
            r" CPU_WNS=([+-]?\d+\.\d+) CPU_CLOCK_GROUP_WHS=([+-]?\d+\.\d+)$", log)
        if not marker or [float(marker[1]), float(marker[2])] != [
                row["cpu_setup_wns_ns"], row["cpu_clock_group_hold_whs_ns"]]:
            raise ValueError("stage ledger/native log mismatch")
    return rows


def result_flags(paths, values, route):
    # Keep CPU/group/internal/global and functional CDC qualification distinct.
    return {
        "cpu_clock_group_setup_met": paths["setup_cpu"]["slack_ns"] >= 0,
        "cpu_clock_group_hold_met": paths["hold_cpu"]["slack_ns"] >= 0,
        "cpu_internal_hold_met": paths["hold_cpu_internal"]["slack_ns"] >= 0,
        "cpu_internal_setup_met": paths["setup_cpu_internal"]["slack_ns"] >= 0,
        "core_internal_setup_and_hold_met": all(paths[key]["slack_ns"] >= 0
            for key in ("setup_core_internal", "hold_core_internal")),
        "internal_setup_and_hold_met": all(
            paths[key]["slack_ns"] >= 0 for key in ("setup_internal", "hold_internal")),
        "all_timed_paths_met": timing_met(values),
        "route_has_no_errors_or_gaps": route["routed_without_errors"] and
            route["nets with explicit gaps"] == 0,
        "physical_qualified": False, "board_qualified": False,
        "cdc_signed_off": False, "bit_generated": False,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--synth-receipt", type=Path, required=True)
    ap.add_argument("--physical", type=Path, required=True)
    ap.add_argument("--route-log", type=Path, required=True)
    ap.add_argument("--script-sha256", required=True)
    ap.add_argument("--internal-audit", type=Path, required=True)
    ap.add_argument("--internal-audit-log", type=Path, required=True)
    ap.add_argument("--source-snapshot", type=Path,
                    help="Optional exact historical source archive, not permission to accept drift")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    package = args.package.resolve()
    physical = args.physical.resolve()
    script = ROOT / "fpga/inorder/route_network_diagnostic.tcl"
    if sha(script) != args.script_sha256:
        ap.error("implementation entry point changed after launch")
    manifest_path = package / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    synth = json.loads(args.synth_receipt.read_text())
    if manifest["top"] != "I1NetworkFpgaShell" or synth["cpu_target_hz"] != 300000000:
        ap.error("selected network/300MHz target changed")
    if synth["short_receipt_sha256"] != manifest["receipt_sha256"]:
        ap.error("qualified synthesis/RTL short receipt mismatch")
    if sha(Path(manifest["receipt"])) != manifest["receipt_sha256"]:
        ap.error("qualified short receipt drift")
    source_root = ROOT
    snapshot = None
    workspace_drift = []
    if args.source_snapshot:
        snapshot = json.loads((args.source_snapshot / "receipt.json").read_text())
        if snapshot["status"] != "FROZEN_QUALIFIED_NETWORK_SOURCE_BYTES_ONLY" or \
                snapshot["rtl_manifest_sha256"] != sha(manifest_path):
            ap.error("historical source snapshot belongs to a different candidate")
        source_root = args.source_snapshot.resolve()
    for group in ("source_sha256", "exporter_sha256", "source_resources"):
        if snapshot and snapshot["groups"][group] != manifest[group]:
            ap.error("historical source ledger differs from qualified manifest")
        for name, digest in manifest[group].items():
            if sha(source_root / name) != digest:
                ap.error("qualified source/exporter/resource drift: " + name)
            if source_root != ROOT and (not (ROOT / name).is_file() or sha(ROOT / name) != digest):
                workspace_drift.append(name)
    for name, digest in manifest["files_sha256"].items():
        if sha(package / name) != digest:
            ap.error("qualified exported input drift: " + name)
    checkpoint = package / "reports/synthesized_constrained.dcp"
    if sha(checkpoint) != synth["checkpoint_sha256"]["synthesized_constrained.dcp"]:
        ap.error("implementation input differs from completed qualified synthesis")
    context = (physical / "context.txt").read_text()
    expected_input = "E:" + str(checkpoint)[len("/mnt/e"):] if str(checkpoint).startswith("/mnt/e/") else str(checkpoint)
    if "input_checkpoint=" + expected_input not in context:
        ap.error("implementation context uses a different checkpoint")
    log = args.route_log.read_text()
    if "I1_NETWORK_INTERNAL_OOC_ROUTING_DONE CPU300MHz NOT_BOARD_NOT_MIG_NO_BIT" not in log:
        ap.error("implementation did not complete")
    if "ERROR:" in log or "synth_design completed successfully" in log:
        ap.error("implementation failed or unexpectedly reran synthesis")
    for port, site in (("io_clockIn", "BUFGCE_X0Y0"),
                       ("io_alwaysOnClock", "BUFGCE_X0Y1"),
                       ("io_macRxClock", "BUFGCE_X0Y2")):
        if f"I1_NETWORK_OOC_CLOCK_CONTEXT port={port} site={site} NOT_BOARD_SIGNOFF" not in log:
            ap.error("changed/missing hypothetical external clock context")
    repairs = re.findall(r"(?m)^I1_NETWORK_POST_ROUTE_REPAIR count=([01]) ", log)
    if len(repairs) != 1:
        ap.error("bounded post-route pass ledger missing")
    for marker in ("I1_NETWORK_CDC_BOUNDS", "I1_PARALLEL_BUFG_ROOTS_CONFIRMED"):
        if marker not in log:
            ap.error("missing post-opt clock/CDC structure gate")
    stages = stage_results((physical / "stages.jsonl").read_text(), log)
    paths = {}
    for scope in SCOPES:
        paths[scope] = path_entry(physical / (scope + ".rpt"))
        marker = re.search(r"(?m)^I1_NETWORK_ROUTED_PATH scope=" + scope +
                           r" slack=([+-]?\d+\.\d+)$", log)
        if not marker or float(marker[1]) != paths[scope]["slack_ns"]:
            ap.error("routed native log/path mismatch: " + scope)
    if stages[-1]["cpu_setup_wns_ns"] != paths["setup_cpu"]["slack_ns"]:
        ap.error("final milestone/routed CPU mismatch")
    internal_log = args.internal_audit_log.read_text()
    if "I1_NETWORK_ROUTE_INTERNAL_AUDIT_DONE NO_SYNTHESIS_NO_IMPLEMENTATION_NO_CONSTRAINT_CHANGES" not in internal_log:
        ap.error("same-checkpoint read-only internal timing audit incomplete")
    internal_values = json.loads((args.internal_audit / "result.json").read_text())
    for scope in INTERNAL_SCOPES:
        paths[scope] = path_entry(args.internal_audit / (scope + ".rpt"))
        marker = re.search(r"(?m)^I1_NETWORK_ROUTED_INTERNAL scope=" + scope +
                           r" slack=([+-]?\d+\.\d+) checkpoint=(.+)$", internal_log)
        expected_routed = str(physical / "routed.dcp")
        if expected_routed.startswith("/mnt/e/"):
            expected_routed = "E:" + expected_routed[len("/mnt/e"):]
        if not marker or float(marker[1]) != paths[scope]["slack_ns"] or \
                float(marker[1]) != internal_values[scope] or marker[2].strip() != expected_routed:
            ap.error("internal audit JSON/report/log/same-checkpoint mismatch")
    values = summary((physical / "timing_final_route.rpt").read_text())
    route = routing((physical / "route_status.rpt").read_text())
    cdc = audit((physical / "cdc.rpt").read_text())
    checks = {name: int(count) for name, count in re.findall(
        r"(?m)^\d+\.\s+checking\s+(\w+)\s+\((\d+)\)",
        (physical / "check_timing.rpt").read_text())}
    if "unconstrained_internal_endpoints" not in checks:
        ap.error("missing actual clock/unconstrained audit")
    families = {path.stem: path_entry(path) for path in physical.glob("setup_*.rpt")
                if path.stem not in paths and not any(path.stem.endswith("_" + stage) for stage in STAGES)}
    fields = {}
    utilization = (physical / "utilization.rpt").read_text()
    for name in ("CLB LUTs", "CLB Registers", "LUT as Memory", "Block RAM Tile", "DSPs"):
        match = re.search(r"(?m)^\|\s*" + re.escape(name) + r"\*?\s*\|\s*([\d.]+)", utilization)
        if not match:
            ap.error("missing mapped resource count: " + name)
        fields[name] = float(match[1]) if "." in match[1] else int(match[1])
    result = {
        "status": "NETWORK_INTERNAL_OOC_ROUTED_RESULTS_NOT_BOARD_NO_BIT",
        "target_hz": 300000000, "cache_bytes_each": 32768,
        "scope": "Network SoC OOC; hypothetical external CPU/AON/RX BUFG context. "
                 "Real board Clock Wizard/MIG/RGMII IOB/pins are outside. "
                 "External clock routing gaps and I/O/CDC failures are NOT waived.",
        "stages": stages, "post_route_repair_passes": int(repairs[0]),
        "path_scopes": paths, "families": families, "timing_summary": values,
        "route_status": route, "check_timing": checks, "utilization": fields,
        "cdc_review": {k: v for k, v in cdc.items() if k != "critical_rows"},
        "package": str(package), "physical_output": str(physical),
        "synthesis_receipt": str(args.synth_receipt.resolve()),
        "synthesis_receipt_sha256": sha(args.synth_receipt),
        "rtl_manifest_sha256": sha(manifest_path),
        "input_constrained_dcp_sha256": sha(checkpoint),
        "routed_dcp_sha256": sha(physical / "routed.dcp"),
        "first_routed_dcp_sha256": sha(physical / "first_routed.dcp"),
        "route_script_sha256": sha(script), "collector_sha256": sha(Path(__file__)),
        "internal_audit_script_sha256": sha(ROOT / "fpga/inorder/report_network_route_internal.tcl"),
        "helper_sha256": {name: sha(ROOT / "fpga/inorder" / name) for name in (
            "collect_network.py", "collect_route_optimization.py", "audit_network_cdc.py")},
        "source_sha256": manifest["source_sha256"],
        "historical_source_snapshot": str(source_root) if snapshot else None,
        "source_snapshot_receipt_sha256": sha(source_root / "receipt.json") if snapshot else None,
        "workspace_drift_since_historical_candidate": sorted(set(workspace_drift)),
        "workspace_edits_qualified_by_this_receipt": False,
        **result_flags(paths, values, route),
    }
    if args.output.exists():
        ap.error("preserve existing physical archive")
    args.output.mkdir(parents=True)
    for path in physical.iterdir():
        if path.is_file() and path.suffix in (".rpt", ".txt", ".jsonl"):
            shutil.copy2(path, args.output / path.name)
    shutil.copytree(args.internal_audit, args.output / "internal-audit")
    helpers = [ROOT / "fpga/inorder" / name for name in (
        "audit_network_cdc.py", "collect_network.py", "collect_route_optimization.py")]
    for path in (args.route_log, args.internal_audit_log, script, Path(__file__),
                 ROOT / "fpga/inorder/report_network_route_internal.tcl", *helpers):
        shutil.copy2(path, args.output / path.name)
    (args.output / "cdc-review.json").write_text(json.dumps(cdc, indent=2) + "\n")
    result["evidence_sha256"] = {str(path.relative_to(args.output)): sha(path)
                                for path in args.output.rglob("*") if path.is_file()}
    (args.output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "status", "stages", "timing_summary", "route_status",
        "cpu_clock_group_setup_met", "cpu_internal_hold_met", "all_timed_paths_met")}, indent=2))


if __name__ == "__main__":
    main()
