#!/usr/bin/env python3
"""Archive same-checkpoint I1 OOC route evidence; never qualify a board/bit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(text):
    number = r"([+-]?\d+\.\d+)"
    count = r"(\d+)"
    row = re.search(r"(?m)^\s*" + r"\s+".join(
        [number, number, count, count] * 3) + r"\s*$", text)
    if not row:
        raise ValueError("missing full setup/hold/pulse summary")
    names = ("setup_wns_ns", "setup_tns_ns", "setup_failing_endpoints", "setup_total_endpoints",
             "hold_whs_ns", "hold_ths_ns", "hold_failing_endpoints", "hold_total_endpoints",
             "pulse_wpws_ns", "pulse_tpws_ns", "pulse_failing_endpoints", "pulse_total_endpoints")
    return {name: (int(value) if "endpoints" in name else float(value))
            for name, value in zip(names, row.groups())}


def path_result(text):
    result = {}
    for label in ("Source", "Destination", "Data Path Delay", "Logic Levels"):
        match = re.search(r"(?m)^\s*" + re.escape(label) + r":\s*(.+)", text)
        if not match:
            raise ValueError("missing routed path field: " + label)
        result[label] = match[1].strip()
    match = re.search(r"Slack \((?:VIOLATED|MET)\)\s*:\s*([+-]?\d+\.\d+)ns", text)
    if not match:
        raise ValueError("missing routed path slack")
    result["slack_ns"] = float(match[1])
    return result


def routing(text):
    result = {}
    for name in ("routable nets", "fully routed nets", "nets with routing errors", "nets with explicit gaps"):
        match = re.search(r"# of " + re.escape(name) + r"\.+\s*:\s*(\d+)\s*:", text)
        if not match:
            raise ValueError("missing native route status: " + name)
        result[name] = int(match[1])
    result["routed_without_errors"] = (
        result["routable nets"] == result["fully routed nets"] and
        result["nets with routing errors"] == 0)
    return result


def timing_met(values):
    return all(values[name] >= 0 for name in ("setup_wns_ns", "hold_whs_ns", "pulse_wpws_ns")) and all(
        values[name] == 0 for name in (
            "setup_failing_endpoints", "hold_failing_endpoints", "pulse_failing_endpoints"))


def bus_skew(text):
    slacks = [float(value) for value in re.findall(
        r"Slack \((?:MET|VIOLATED)\)\s*:\s*([+-]?\d+\.\d+)ns", text)]
    requirements = [float(value) for value in re.findall(r"(?m)^Requirement:\s*(\d+\.\d+)ns", text)]
    endpoints = [int(value) for value in re.findall(r"(?m)^Endpoints:\s*(\d+)", text)]
    if len(slacks) != 2 or requirements != [8.0, 8.0] or sorted(endpoints) != [34, 41]:
        raise ValueError("held-bundle skew constraints missing or changed")
    return {"slack_ns": slacks, "endpoints": endpoints, "met": min(slacks) >= 0}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--synth-receipt", type=Path, required=True)
    ap.add_argument("--physical", type=Path, required=True)
    ap.add_argument("--audit", type=Path, required=True)
    ap.add_argument("--route-log", type=Path, required=True)
    ap.add_argument("--audit-log", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    package = args.package.resolve()
    manifest = json.loads((package / "manifest.json").read_text())
    for name, digest in manifest["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise ValueError("qualified source drift: " + name)
    for name, digest in manifest["files_sha256"].items():
        if sha(package / name) != digest:
            raise ValueError("qualified exported input drift: " + name)
    synth = json.loads(args.synth_receipt.read_text())
    if synth["rtl_manifest_sha256"] != sha(package / "manifest.json"):
        raise ValueError("synthesis manifest provenance mismatch")
    checkpoint = package / "reports/synthesized_constrained.dcp"
    if sha(checkpoint) != synth["ex_wb_comparison"]["checkpoints"]["current"]["sha256"]:
        raise ValueError("route input is not the qualified constrained synthesis")
    route_log = args.route_log.read_text()
    audit_log = args.audit_log.read_text()
    if "I1_INTERNAL_OOC_ROUTING_DONE NOT_BOARD_NOT_MIG_NO_BIT" not in route_log:
        raise ValueError("missing actual implementation completion")
    if "I1_ROUTE_OPTIMIZATION_REPORT_DONE NO_CLOCK_OR_EXCEPTION_CHANGES NOT_BOARD_NO_BIT" not in audit_log:
        raise ValueError("missing completed read-only routed audit")
    if "I1_OOC_HYPOTHETICAL_CLOCK_SITE=BUFGCE_X0Y0 NOT_BOARD_SIGNOFF" not in route_log:
        raise ValueError("review the changed OOC clock-source context")
    if not all(marker in route_log for marker in (
            "BSCAN_EVENT_CLOCK_PATHS_FULLY_TIMED NO_MULTICYCLE NO_ASYNC_CLOCK_GROUP",
            "BSCAN_POSITIVE_PAYLOAD_STAGE bits=67 FUNCTIONAL_RESETS_TIMED")):
        raise ValueError("missing scoped USER2 constraints")
    for marker in ("VALENCE_JTAG_CHAIN_PASS USER2", "BSCAN_POSITIVE_QUALIFICATION present=2"):
        if marker not in audit_log:
            raise ValueError("routed USER2 structure audit missing")
    if "ERROR:" in route_log or "ERROR:" in audit_log:
        raise ValueError("Vivado error in physical evidence")
    values = summary((args.audit / "timing_summary.rpt").read_text())
    route = routing((args.audit / "route_status.rpt").read_text())
    skew = bus_skew((args.audit / "bus_skew.rpt").read_text())
    utilization = {}
    utilization_text = (args.physical / "utilization.rpt").read_text()
    for name in ("CLB LUTs", "CLB Registers", "LUT as Memory", "Block RAM Tile", "DSPs"):
        match = re.search(r"(?m)^\|\s*" + re.escape(name) + r"\*?\s*\|\s*([\d.]+)", utilization_text)
        if not match:
            raise ValueError("missing routed resource count: " + name)
        utilization[name] = float(match[1]) if "." in match[1] else int(match[1])
    checks = dict(re.findall(
        r"(?m)^\d+\.\s+checking\s+(\w+)\s+\((\d+)\)", (args.audit / "check_timing.rpt").read_text()))
    if not checks or "unconstrained_internal_endpoints" not in checks:
        raise ValueError("missing native unconstrained/clock checks")
    check_counts = {name: int(value) for name, value in checks.items()}
    scopes = {}
    for scope in ("setup_global", "hold_global", "setup_internal", "hold_internal", "setup_cpu", "hold_cpu"):
        scopes[scope] = path_result((args.audit / (scope + ".rpt")).read_text())
        marker = re.search(r"(?m)^I1_ROUTED_PATH scope=" + scope + r" slack=([+-]?\d+\.\d+)$", audit_log)
        if not marker or abs(float(marker[1]) - scopes[scope]["slack_ns"]) > 0.00001:
            raise ValueError("native report/log scope mismatch: " + scope)
    partitions = {p.stem[len("setup_"):]: path_result(p.read_text()) for p in args.audit.glob("setup_*.rpt")
                  if p.stem not in ("setup_global", "setup_internal", "setup_cpu")}
    met = timing_met(values) and route["routed_without_errors"] and skew["met"] and not any(check_counts.values())
    result = {
        "status": ("ROUTED_INTERNAL_OOC_TIMING_MET_300MHZ_NOT_BOARD_NO_BIT" if met
                   else "ROUTED_INTERNAL_OOC_FAILS_300MHZ_NO_BIT"),
        "ooc_timing_met": met, "physical_qualified": False, "board_qualified": False, "bit_generated": False,
        "target_hz": manifest["target_hz"], "pipeline": manifest["pipeline"], "flags": manifest["flags"],
        "scope": "Independent I1 shell, hypothetical BUFGCE_X0Y0, synchronous zero-budget placeholder I/O; "
                 "no real board clock/MIG/DDR pins, no board signoff, no bit. "
                 "External clock net explicit gaps are reported, not silently waived.",
        "timing_summary": values, "route_status": route, "check_timing": check_counts,
        "bus_skew": skew, "utilization": utilization,
        "path_scopes": scopes, "partitions": partitions,
        "source_sha256": manifest["source_sha256"],
        "rtl_manifest_sha256": sha(package / "manifest.json"),
        "synthesis_receipt_sha256": sha(args.synth_receipt),
        "input_constrained_dcp_sha256": sha(checkpoint),
        "routed_dcp_sha256": sha(args.physical / "routed.dcp"),
        "collector_sha256": sha(Path(__file__)),
        "audit_script_sha256": sha(ROOT / "fpga/inorder/report_route_optimization.tcl"),
        "route_script_sha256": sha(package / "route_diagnostic.tcl"),
    }
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh physical evidence archive required")
    output.mkdir(parents=True)
    for directory, label in ((args.physical, "physical"), (args.audit, "audit")):
        destination = output / label
        destination.mkdir()
        for p in directory.glob("*.rpt"):
            shutil.copy2(p, destination / p.name)
    for path in (args.route_log, args.audit_log, ROOT / "fpga/inorder/report_route_optimization.tcl",
                 ROOT / "fpga/inorder/collect_route_optimization.py"):
        shutil.copy2(path, output / path.name)
    result["archive_sha256"] = {str(p.relative_to(output)): sha(p)
                                for p in output.rglob("*") if p.is_file()}
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in (
        "status", "timing_summary", "route_status", "path_scopes")}, indent=2))


if __name__ == "__main__":
    main()
