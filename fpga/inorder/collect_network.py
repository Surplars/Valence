#!/usr/bin/env python3
"""Archive one exact-tested network synthesis and all unresolved physical gates."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
from audit_network_cdc import audit
from export_network import user_stopped_diagnostic_scope

ROOT = Path(__file__).resolve().parents[2]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def path_entry(path):
    text = path.read_text()
    result = {}
    slack = re.search(r"Slack \((?:VIOLATED|MET)\)\s*:\s*([+-]?\d+\.\d+)ns", text)
    if not slack:
        raise ValueError("missing actual timing path: " + str(path))
    result["slack_ns"] = float(slack[1])
    for label in ("Source", "Destination", "Data Path Delay", "Logic Levels", "Clock Path Skew"):
        match = re.search(r"(?m)^\s*" + re.escape(label) + r":\s*(.+)", text)
        if match:
            result[label] = match[1].strip()
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--previous", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--user-stopped-diagnostic", action="store_true",
                    help="Explicitly collect unqualified user-stopped diagnostic STA; normal gate stays strict")
    args = ap.parse_args()
    package = args.package.resolve()
    reports = package / "reports"
    manifest = json.loads((package / "manifest.json").read_text())
    diagnostic = manifest["status"] == "DIAGNOSTIC_USER_STOPPED_TARGET_CPU_RTL_EXPORT_NOT_FULL_QUALIFICATION"
    if diagnostic != args.user_stopped_diagnostic:
        ap.error("diagnostic manifest requires explicit diagnostic collection scope")
    if not diagnostic and manifest["status"] != "PASS_SHORT_TESTED_NETWORK_RTL_EXPORT_ONLY":
        ap.error("exact qualified network export required")
    for group in ("source_sha256", "exporter_sha256", "source_resources"):
        for name, digest in manifest[group].items():
            if sha(ROOT / name) != digest:
                ap.error("source/exporter drift: " + name)
    for name, digest in manifest["files_sha256"].items():
        if sha(package / name) != digest:
            ap.error("exported RTL drift: " + name)
    for field in ("receipt", "cdc_receipt", "managed_clock_receipt"):
        digest = {"receipt": "receipt_sha256", "cdc_receipt": "cdc_sha256",
                  "managed_clock_receipt": "managed_clock_sha256"}[field]
        if sha(Path(manifest[field])) != manifest[digest]:
            ap.error("proof receipt drift: " + field)
    short = json.loads(Path(manifest["receipt"]).read_text())
    if diagnostic:
        evidence = manifest["diagnostic_evidence"]
        for field, digest in (("summary", "summary_sha256"),
                              ("performance_reference", "performance_reference_sha256")):
            if sha(Path(evidence[field])) != evidence[digest]:
                ap.error("diagnostic evidence drift: " + field)
        try:
            verified = user_stopped_diagnostic_scope(
                short, json.loads(Path(evidence["summary"]).read_text()),
                json.loads(Path(evidence["performance_reference"]).read_text()), manifest["receipt_sha256"])
        except (ValueError, KeyError) as error:
            ap.error(str(error))
        if any(evidence.get(k) != v for k, v in verified.items()):
            ap.error("diagnostic scope ledger differs from original stopped evidence")
        if (sha(package / "I1NetworkFpgaShell.fir") != evidence["fresh_network_fir_sha256"] or
                sha(package / "network-elaboration-reference/I1NetworkFpgaShell.fir") !=
                evidence["fresh_network_fir_sha256"]):
            ap.error("fresh diagnostic shell identity differs")
    for name, digest in short["artifact_sha256"].items():
        if sha(Path(manifest["receipt"]).parent / name) != digest:
            ap.error("GSIM artifact drift: " + name)
    result = json.loads((reports / "result.json").read_text())
    log = (package / "vivado_synth.log").read_text()
    if result["status"] != "COMPLETE_NETWORK_SYNTHESIS_ONLY_NOT_ROUTED" or \
            "I1_NETWORK_SYNTHESIS_DONE" not in log or "synth_design completed successfully" not in log:
        ap.error("completed one-shot synthesis with netlist/clock/RAM gates required")
    for marker in ("I1_NATIVE_BOUNDARIES_CONFIRMED", "I1_PARALLEL_BUFG_ROOTS_CONFIRMED",
                   "BSCAN_EVENT_CLOCK_PATHS_FULLY_TIMED", "I1_NETWORK_CDC_BOUNDS"):
        if marker not in log:
            ap.error("missing real-netlist gate: " + marker)
    if manifest.get("coherent_whole_line"):
        for marker in ("I1_LINE_REQUEST_BOUNDARIES_CONFIRMED", "I1_SERIALIZED_HOME_WRITER_CONFIRMED"):
            if marker not in log:
                ap.error("missing exact selected whole-line/compact-writer gate")
    if result["cpu_target_hz"] != 300000000 or \
            result["native_timing_boundaries"] != manifest["native_timing_boundary_count"]:
        ap.error("selected target/topology changed")
    fields = {}
    text = (reports / "utilization.rpt").read_text()
    for label in ("CLB LUTs", "CLB Registers", "LUT as Memory", "Block RAM Tile", "DSPs"):
        match = re.search(r"(?m)^\|\s*" + re.escape(label) + r"\*?\s*\|\s*([\d.]+)", text)
        if not match:
            ap.error("missing resource row: " + label)
        fields[label] = float(match[1]) if "." in match[1] else int(match[1])
    paths = {p.stem: path_entry(p) for p in reports.glob("setup_*_synth.rpt")}
    if abs(paths["setup_cpu_synth"]["slack_ns"] - result["cpu_setup_wns_ns"]) > 0.000001:
        ap.error("result/path report CPU setup mismatch")
    paths["hold"] = path_entry(reports / "hold_synth.rpt")
    paths["hold_cpu"] = path_entry(reports / "hold_cpu_synth.rpt")
    summary = (reports / "timing_synth.rpt").read_text()
    global_row = re.search(r"(?m)^\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)"
                           r"\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)", summary)
    if not global_row:
        ap.error("missing global setup/hold summary")
    cdc = audit((reports / "cdc.rpt").read_text())
    cdc.update({"report_sha256": sha(reports / "cdc.rpt"),
                "clock_short_receipt_sha256": manifest["managed_clock_sha256"]})
    hold_comparison = None
    hold_root = reports / "hold-comparison"
    if hold_root.exists():
        hold_log = package / "vivado_hold_compare.log"
        text = hold_log.read_text()
        if "I1_HOLD_REPORT_ONLY_DONE TWO_EXISTING_DCPS NO_SYNTHESIS NO_CONSTRAINT_CHANGES NO_ROUTE" not in text:
            ap.error("hold comparison is incomplete")
        values = json.loads((hold_root / "result.json").read_text())
        checkpoints = {}
        for label in ("baseline", "current"):
            rows = re.findall(r"(?m)^I1_HOLD_CHECKPOINT_COMPARE name=" + label +
                              r" family=(\w+) whs=([+-]?[\d.]+) checkpoint=(.+)$", text)
            if len(rows) != 3:
                ap.error("hold comparison ledger incomplete: " + label)
            for family, slack, native in rows:
                if values[label][family + "_whs_ns"] != float(slack) or \
                        path_entry(hold_root / label / ("hold_" + family + ".rpt"))["slack_ns"] != float(slack):
                    ap.error("hold JSON/native/report mismatch")
                native = native.strip()
                checkpoint = Path("/mnt/" + native[0].lower() + native[2:]) if re.match(
                    r"^[A-Za-z]:/", native) else Path(native)
                if label == "current" and checkpoint.resolve() != (reports / "synthesized_constrained.dcp").resolve():
                    ap.error("comparison uses a different current checkpoint")
                checkpoints[label] = {"path": str(checkpoint), "sha256": sha(checkpoint)}
            setup_rows = re.findall(r"(?m)^I1_SETUP_CHECKPOINT_COMPARE name=" + label +
                                    r" family=(\w+) wns=([+-]?[\d.]+) checkpoint=(.+)$", text)
            if setup_rows:
                expected = {"line_writer", "cache_metadata", "cache_replacement"}
                if any(row[0] in {"ex_packet", "fetch_admission", "dma"} for row in setup_rows):
                    expected |= {"ex_packet", "fetch_admission", "dma"}
                if any(row[0] in {"instruction_translation", "instruction_cache", "cache_probe"}
                       for row in setup_rows):
                    expected |= {"instruction_translation", "instruction_cache", "cache_probe"}
                if {r[0] for r in setup_rows} != expected or len(setup_rows) != len(expected):
                    ap.error("setup checkpoint comparison ledger incomplete")
                for family, slack, native in setup_rows:
                    if values[label][family + "_setup_wns_ns"] != float(slack) or \
                            path_entry(hold_root / label / ("setup_" + family + ".rpt"))["slack_ns"] != float(slack):
                        ap.error("setup comparison JSON/native/report mismatch")
                    native = native.strip()
                    checkpoint = Path("/mnt/" + native[0].lower() + native[2:]) if re.match(
                        r"^[A-Za-z]:/", native) else Path(native)
                    if str(checkpoint) != checkpoints[label]["path"]:
                        ap.error("setup comparison uses a different checkpoint")
        hold_comparison = {"values": values, "checkpoints": checkpoints, "scope": "READ_ONLY_NO_CONSTRAINT_CHANGES",
                           "script_sha256": sha(Path(__file__).with_name("report_network_hold.tcl")),
                           "log_sha256": sha(hold_log)}
    storage_comparison = None
    storage_root = reports / "storage-comparison"
    if storage_root.exists():
        storage_log = package / "vivado_storage_compare.log"
        storage_text = storage_log.read_text()
        if "I1_STORAGE_REPORT_ONLY_DONE TWO_EXISTING_DCPS NO_SYNTHESIS NO_CONSTRAINT_CHANGES NO_ROUTE" not in storage_text:
            ap.error("storage comparison is incomplete")
        storage_values = json.loads((storage_root / "result.json").read_text())
        expected = {"instruction_bram_inputs", "ddr_payload_capture", "instruction_victim", "plic_live_csr"}
        storage_checkpoints = {}
        for label in ("baseline", "current"):
            rows = re.findall(r"(?m)^I1_STORAGE_CHECKPOINT_COMPARE name=" + label +
                              r" family=(\w+) wns=([+-]?[\d.]+) checkpoint=(.+)$", storage_text)
            if len(rows) != 4 or {row[0] for row in rows} != expected:
                ap.error("storage comparison ledger incomplete: " + label)
            for family, slack, native in rows:
                if storage_values[label][family + "_wns_ns"] != float(slack) or \
                        path_entry(storage_root / label / ("setup_" + family + ".rpt"))["slack_ns"] != float(slack):
                    ap.error("storage JSON/native/report mismatch")
                native = native.strip()
                checkpoint = Path("/mnt/" + native[0].lower() + native[2:]) if re.match(
                    r"^[A-Za-z]:/", native) else Path(native)
                if label == "current" and checkpoint.resolve() != (reports / "synthesized_constrained.dcp").resolve():
                    ap.error("storage comparison uses a different current checkpoint")
                if hold_comparison and str(checkpoint) != hold_comparison["checkpoints"][label]["path"]:
                    ap.error("storage and hold comparisons use different checkpoints")
                entry = {"path": str(checkpoint), "sha256": sha(checkpoint)}
                if label in storage_checkpoints and storage_checkpoints[label] != entry:
                    ap.error("storage families use different checkpoints")
                storage_checkpoints[label] = entry
        storage_comparison = {
            "values": storage_values, "checkpoints": storage_checkpoints,
            "scope": "READ_ONLY_SYNTHESIZED_CHECKPOINTS_NOT_ROUTED",
            "script_sha256": sha(Path(__file__).with_name("report_network_storage.tcl")),
            "log_sha256": sha(storage_log)}
    previous = json.loads(args.previous.read_text())
    previous_short = ROOT / previous["short_receipt"]
    if sha(previous_short) != previous["short_receipt_sha256"]:
        ap.error("previous comparison GSIM receipt drift")
    old_short = json.loads(previous_short.read_text())
    stream = {}
    fields_compared = ("mode", "bytes", "cycles", "read_ticks", "write_ticks", "copy_ticks",
                       "retired", "axi_reads", "axi_writes",
                       "axi_read_latency_floor", "axi_write_latency_floor")
    for key, value in short["checks"].items():
        if key.startswith("cpu-coherent-") and value.startswith("I1_PRIVILEGED_STREAM_PASS "):
            if key not in old_short["checks"]:
                ap.error("previous matched CPU streaming scenario missing: " + key)
            new = json.loads(value.split(" ", 1)[1])
            old = json.loads(old_short["checks"][key].split(" ", 1)[1])
            stream[key] = {"old": {k: old[k] for k in fields_compared},
                           "new": {k: new[k] for k in fields_compared},
                           "same": all(old[k] == new[k] for k in fields_compared)}
    if args.output.exists():
        ap.error("preserve previous physical evidence")
    args.output.mkdir(parents=True)
    shutil.copytree(reports, args.output / "reports", ignore=shutil.ignore_patterns("*.dcp"))
    shutil.copy2(package / "manifest.json", args.output / "rtl-manifest.json")
    shutil.copy2(package / "vivado_synth.log", args.output / "vivado_synth.log")
    if diagnostic:
        shutil.copy2(Path(evidence["summary"]), args.output / "diagnostic-stop-summary.json")
        shutil.copy2(Path(evidence["performance_reference"]),
                     args.output / "diagnostic-performance-reference.json")
    if hold_comparison:
        shutil.copy2(hold_log, args.output / "vivado_hold_compare.log")
        shutil.copy2(Path(__file__).with_name("report_network_hold.tcl"),
                     args.output / "report_network_hold.tcl")
    if storage_comparison:
        shutil.copy2(storage_log, args.output / "vivado_storage_compare.log")
        shutil.copy2(Path(__file__).with_name("report_network_storage.tcl"),
                     args.output / "report_network_storage.tcl")
    shutil.copy2(Path(manifest["managed_clock_receipt"]), args.output / "managed-clock-receipt.json")
    for field, subdir in (("managed_clock_receipt", "managed-clock-proof"),
                          ("cdc_receipt", "user2-cdc-proof")):
        origin = Path(manifest[field])
        proof = json.loads(origin.read_text())
        archive = args.output / subdir
        archive.mkdir()
        shutil.copy2(origin, archive / "receipt.json")
        for name, digest in proof["artifact_sha256"].items():
            source = origin.parent / name.replace("\\", "/")
            if sha(source) != digest:
                ap.error("CDC proof artifact drift: " + name)
            target = archive / name.replace("\\", "/")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    (args.output / "cdc-review.json").write_text(json.dumps(cdc, indent=2) + "\n")
    actual_setup = float(global_row[1])
    actual_hold = float(global_row[5])
    receipt = {"status": "NETWORK_SYNTHESIS_ONLY_TIMING_OR_CDC_PENDING",
        "top": manifest["top"], "part": manifest["part"], "cpu_target_hz": 300000000,
        "cache_bytes_each": 32768, "native_boundaries": result["native_timing_boundaries"], "line_engine_entries": 2,
        "coherent_bandwidth": bool(manifest.get("coherent_bandwidth")),
        "coherent_whole_line": bool(manifest.get("coherent_whole_line")),
        "line_read_request_boundaries": manifest.get("line_read_request_boundaries", 0),
        "home_write_payload_owners": manifest.get("home_write_payload_owners"),
        "coherent_control_revision": manifest.get("coherent_control_revision"),
        "parallel_instruction_way_reads": bool(manifest.get("parallel_instruction_way_reads")),
        "parallel_instruction_ram_bindings": manifest.get("parallel_instruction_ram_bindings", {}),
        "prepared_ddr_payload": bool(manifest.get("prepared_ddr_payload")),
        "parallel_instruction_candidates": bool(manifest.get("parallel_instruction_candidates")),
        "disjoint_instruction_transitions": bool(manifest.get("disjoint_instruction_transitions")),
        "parallel_backend_control": bool(manifest.get("parallel_backend_control")),
        "registered_id_serial_class": bool(manifest.get("registered_id_serial_class")),
        "prepared_native_requests": bool(manifest.get("prepared_native_requests")),
        "local_cache_metadata": bool(manifest.get("local_cache_metadata")),
        "cpu_setup_wns_ns": result["cpu_setup_wns_ns"],
        "cpu_hold_whs_ns": paths["hold_cpu"]["slack_ns"],
        "cpu_hold_scope": "clock-group query includes declared OOC input delays; not register-to-register only",
        "hold_checkpoint_comparison": hold_comparison,
        "storage_checkpoint_comparison": storage_comparison,
        "overall_setup_wns_ns": actual_setup, "overall_hold_whs_ns": actual_hold,
        "synthesis_setup_and_hold_met": actual_setup >= 0 and actual_hold >= 0,
        "full_synthesis_runs": 1, "utilization": fields, "paths": paths,
        "previous_receipt_sha256": sha(args.previous),
        "cpu_wns_improvement_ns": round(result["cpu_setup_wns_ns"] - previous["cpu_setup_wns_ns"], 3),
        "lut_reduction": (previous["lut"] if "lut" in previous else previous["utilization"]["CLB LUTs"])
                         - fields["CLB LUTs"],
        "ff_reduction": (previous["ff"] if "ff" in previous else previous["utilization"]["CLB Registers"])
                        - fields["CLB Registers"],
        "short_receipt": manifest["receipt"], "short_receipt_sha256": manifest["receipt_sha256"],
        "short_checks": len(short["checks"]), "benchmarks": short.get("benchmarks"),
        "bandwidth_comparison": short.get("bandwidth_comparison"),
        "stream_comparison": stream,
        "matched_stream_scenarios": len(stream),
        "matched_stream_cycle_counts_unchanged": len(stream) == 12 and all(r["same"] for r in stream.values()),
        "cdc_review": {k: v for k, v in cdc.items() if k != "critical_rows"},
        "physical_qualified": False, "board_qualified": False, "cdc_signed_off": False,
        "routed": False, "bit_generated": False,
        "package": str(package), "checkpoint_sha256": {
            p.name: sha(p) for p in reports.glob("*.dcp")},
        "collector_sha256": sha(Path(__file__)), "auditor_sha256": sha(Path(__file__).with_name("audit_network_cdc.py")),
        "evidence_sha256": {str(p.relative_to(args.output)): sha(p)
                           for p in args.output.rglob("*") if p.is_file()},
        "scope": "32K+32K RV64GC/Sv39/TL-C/managed tri-speed network OOC, not board MIG/RGMII/clock-IP signoff"}
    if diagnostic:
        receipt["status"] = "DIAGNOSTIC_NETWORK_SYNTHESIS_FULL_SHORT_INCOMPLETE_NOT_QUALIFIED"
        receipt["diagnostic_evidence"] = evidence
        receipt["full_short_qualified"] = False
        receipt["raw_short_status"] = short["status"]
        receipt["scope"] += "; explicit diagnostic only, user-stopped full short suite incomplete"
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({k: receipt[k] for k in ("status", "cpu_setup_wns_ns", "cpu_hold_whs_ns",
          "overall_hold_whs_ns", "cpu_wns_improvement_ns", "utilization", "short_checks", "cdc_review")}, indent=2))
    print("RECEIPT", args.output / "receipt.json")


if __name__ == "__main__":
    main()
