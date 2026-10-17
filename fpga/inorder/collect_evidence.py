#!/usr/bin/env python3
"""Bind existing bare-core synthesis reports to their exact exported RTL and GSIM receipt."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utilization(text):
    rows = [line.split("|")[1:-1] for line in text.splitlines()
            if re.match(r"^\|\s*FiveStageCore\s*\|", line)]
    if len(rows) != 1 or len(rows[0]) != 11:
        raise ValueError("unexpected hierarchical utilization shape")
    values = [int(value.strip()) for value in rows[0][2:]]
    return dict(zip(("lut", "logic_lut", "lutram", "srl", "ff", "bram36", "bram18", "uram", "dsp"), values))


def timing(text):
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.match(r"^\s*WNS\(ns\)\s+TNS\(ns\)", line):
            values = lines[index + 2].split()
            if len(values) != 12:
                raise ValueError("unexpected timing summary shape")
            return {"wns_ns": float(values[0]), "tns_ns": float(values[1]),
                    "setup_failing_endpoints": int(values[2]), "setup_total_endpoints": int(values[3]),
                    "whs_ns": float(values[4]), "wpws_ns": float(values[8])}
    raise ValueError("missing clock timing summary")


def worst_path(text):
    def field(pattern):
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            raise ValueError("missing worst-path field: " + pattern)
        return match.group(1).strip()
    return {"source": field(r"^  Source:\s+(.+)$"),
            "destination": field(r"^  Destination:\s+(.+)$"),
            "data_path_ns": float(field(r"^  Data Path Delay:\s+([0-9.]+)ns")),
            "logic_levels": int(field(r"^  Logic Levels:\s+([0-9]+)"))}


def route_status(text):
    def count(label):
        match = re.search(r"# of " + label + r"\.+\s+:\s+([0-9]+)\s+:", text)
        if not match:
            raise ValueError("missing route status: " + label)
        return int(match.group(1))
    return {"routable_nets": count("routable nets"), "fully_routed_nets": count("fully routed nets"),
            "nets_with_routing_errors": count("nets with routing errors")}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rtl", required=True, type=Path)
    ap.add_argument("--reports", required=True, type=Path)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--physical", type=Path)
    ap.add_argument("--route-log", type=Path)
    ap.add_argument("--route-script", type=Path)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("refusing to overwrite evidence")
    manifest_path = args.rtl / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    receipt = json.loads(args.receipt.read_text())
    if (manifest["status"] != "PASS_BARE_CORE_RTL_EXPORT_ONLY" or
            receipt["status"] != "PASS_FIVE_STAGE_INTEGER_FOUNDATION_ONLY" or
            manifest["gsim_receipt_sha256"] != sha(args.receipt)):
        ap.error("RTL/GSIM binding failed")
    for name, digest in manifest["files_sha256"].items():
        if sha(args.rtl / name) != digest:
            ap.error("exported input drift: " + name)
    for name, digest in manifest["acceptance_sources_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift after GSIM/export: " + name)
    log = args.log.read_text(errors="replace")
    if "ORBITAL_I1_OOC_BATCH_PASS_SYNTHESIS_ONLY_NO_BIT" not in log:
        ap.error("synthesis batch did not complete")
    profiles = {}
    for name in manifest["profiles"]:
        folder = args.reports / name
        hierarchy = (folder / "hierarchical_utilization.rpt").read_text()
        summary = (folder / "timing_synth.rpt").read_text()
        setup = (folder / "setup_synth.rpt").read_text()
        if "Design State : Synthesized" not in hierarchy or not re.search(r"Design State\s+: Synthesized", setup):
            ap.error("report design state is not synthesis-only: " + name)
        resource = utilization(hierarchy)
        clock = timing(summary)
        if name != "rv64-lutram" and resource["bram36"] + resource["bram18"] < 2:
            ap.error("RF block-RAM mapping failed")
        if name == "rv64-no-m" and resource["dsp"] != 0:
            ap.error("disabled M retained DSPs")
        if name == "rv64-dsp" and resource["dsp"] <= 0:
            ap.error("DSP multiplier missing")
        profiles[name] = {"resources": resource, "synthesis_estimated_timing": clock,
            "synthesis_estimated_timing_met": clock["wns_ns"] >= 0 and clock["whs_ns"] >= 0 and clock["wpws_ns"] >= 0,
            "worst_path": worst_path(setup),
            "reports_sha256": {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()}}
    result = {"status": "PASS_SYNTHESIS_MAPPING_ONLY", "part": manifest["part"],
        "pipeline": receipt["pipeline"], "export_manifest_sha256": sha(manifest_path),
        "gsim_receipt_sha256": sha(args.receipt), "synthesis_log_sha256": sha(args.log),
        "target_mhz": manifest["design_target_mhz_not_qualified"], "profiles": profiles,
        "routed_frequency_qualified": False, "board_qualified": False,
        "scope": "Bare five-stage core. Estimated synthesis timing, not routed or SoC timing. "
                 "No cache/MMU/FPU/SoC performance comparison is implied."}
    if any((args.physical, args.route_log, args.route_script)):
        if not all((args.physical, args.route_log, args.route_script)):
            ap.error("all three physical evidence arguments are required together")
        if sha(args.route_script) != sha(ROOT / "fpga/inorder/route_ooc.tcl"):
            ap.error("routed implementation script does not match current entry point")
        route_log = args.route_log.read_text(errors="replace")
        if "ORBITAL_I1_OOC_ROUTE_COMPLETE" not in route_log:
            ap.error("physical implementation did not complete")
        folder = args.physical
        summary = (folder / "timing_routed.rpt").read_text()
        if not re.search(r"Design State\s+: Routed", summary):
            ap.error("not a routed timing report")
        context = (folder / "context.txt").read_text()
        if ("BARE_CORE_INTERNAL_PATHS_ONLY_NOT_SOC_NOT_BOARD" not in context or
                "clock_period_ns=5.000 assumed_external_clock_source=BUFGCE_" not in context):
            ap.error("explicit standalone clock context missing")
        clock = timing(summary)
        routed = route_status((folder / "route_status.rpt").read_text())
        met = (clock["wns_ns"] >= 0 and clock["whs_ns"] >= 0 and clock["wpws_ns"] >= 0 and
               routed["routable_nets"] == routed["fully_routed_nets"] and routed["nets_with_routing_errors"] == 0)
        result["standalone_routed_default_profile"] = {
            "internal_ooc_timing_met": met, "target_mhz": 200, "context": context.strip(),
            "resources": utilization((folder / "hierarchical_utilization.rpt").read_text()),
            "timing": clock, "route_status": routed,
            "worst_path": worst_path((folder / "setup_routed.rpt").read_text()),
            "input_synth_dcp_sha256": profiles["rv64-dsp"]["reports_sha256"]["synthesized.dcp"],
            "route_script_sha256": sha(args.route_script), "route_log_sha256": sha(args.route_log),
            "reports_sha256": {p.name: sha(p) for p in sorted(folder.iterdir()) if p.is_file()},
            "boundary_i_o_qualified": False, "soc_qualified": False, "board_qualified": False}
        result["scope"] = "Bare five-stage core. Standalone internal routed timing only under explicit " \
                          "external BUFGCE assumption. Not SoC/board qualification or benchmark parity."
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "profiles": profiles, "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
