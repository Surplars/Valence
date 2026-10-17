#!/usr/bin/env python3
"""Bind the completed I1 SoC synthesis to source/RTL/GSIM and archive small reports in WSL."""
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
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--partial-console", action="store_true",
                    help="Use explicitly labelled native stdout end fragments; not a complete warning log")
    args = ap.parse_args()
    package = args.package.resolve()
    output = args.output.resolve()
    manifest = json.loads((package / "manifest.json").read_text())
    if manifest["status"] != "PASS_TESTED_I1_SOC_RTL_EXPORT_ONLY":
        ap.error("tested frozen I1 RTL required")
    for name, digest in manifest["files_sha256"].items():
        if sha(package / name) != digest:
            ap.error("RTL/export artifact drift: " + name)
    for name, digest in manifest["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift since GSIM/export: " + name)
    for name, digest in manifest["exporter_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("exporter drift since export: " + name)
    acceptance = Path(manifest["receipt"])
    if sha(acceptance) != manifest["receipt_sha256"]:
        ap.error("GSIM receipt drift")
    reports = package / "reports"
    result = json.loads((reports / "result.json").read_text())
    requested_period_ns = 1e9 / manifest["target_hz"]
    actual_period_ns = 1000 / result["target_mhz"]
    # Vivado stores STA periods in integer picoseconds (e.g. 300MHz's
    # 3.333333333ns becomes 3.333ns). This is tool precision, not a new target.
    if abs(actual_period_ns - requested_period_ns) > 0.000501:
        ap.error("reported STA target differs from the frozen RTL manifest")
    result["requested_target_hz"] = manifest["target_hz"]
    result["actual_period_ns"] = actual_period_ns
    fragments = sorted(package.glob("console-end-part-*.log"))
    if args.partial_console:
        if not fragments or not fragments[0].read_text().startswith("# PARTIAL native stdout capture"):
            ap.error("explicitly labelled native console fragments required")
        log = "".join(p.read_text() for p in fragments)
        if "synth_design completed successfully" not in log:
            ap.error("native synthesis completion not captured")
    else:
        log = (package / "vivado_synth.log").read_text()
    reused = manifest.get("reused_synthesis")
    if reused:
        provenance = package / "checkpoint-provenance"
        previous = json.loads((provenance / "manifest.json").read_text())
        if sha(provenance / "manifest.json") != reused["manifest_sha256"]:
            ap.error("checkpoint manifest provenance drift")
        if sha(provenance / "vivado_synth.log") != reused["log_sha256"]:
            ap.error("checkpoint synthesis log provenance drift")
        if sha(package / "reused_synthesized.dcp") != reused["checkpoint_sha256"]:
            ap.error("checkpoint bytes drift")
        for key in ("source_sha256", "flags", "top", "target_hz"):
            if previous[key] != manifest[key]:
                ap.error("resumed checkpoint qualification mismatch: " + key)
        for name, digest in previous["files_sha256"].items():
            if (Path(name).suffix in (".sv", ".xdc") and "/" not in name) or name == "bootrom.hex":
                if sha(package / name) != digest:
                    ap.error("resumed checkpoint RTL/XDC mismatch: " + name)
        if "synth_design completed successfully" not in (provenance / "vivado_synth.log").read_text():
            ap.error("missing completed original synthesis")
        if "ORBITAL_I1_REUSED_EXACT_SYNTHESIS NO_NEW_SYNTHESIS" not in log:
            ap.error("missing report-only checkpoint resume marker")
    if "ORBITAL_I1_COMPLETE_SOC_SYNTH_DONE" not in log or result["status"] != "COMPLETE_SYNTHESIS_ONLY_NOT_ROUTED":
        ap.error("completed synthesis with RAM/ROM gates required")
    if "Net Memory in module/entity storage_512x64 does not have driver" in log:
        ap.error("ROM initialization disappeared in synthesis")
    mapping = (reports / "ram_dsp_mapping.txt").read_text()
    if "rom_nonzero_init=1" not in mapping:
        ap.error("physical initialized BootROM proof missing")
    if manifest.get("floating_enabled"):
        if result.get("fpr_bram_primitives", 0) < 3 or not result.get("bscan_shape_checked"):
            ap.error("FPR BRAM and USER2 timing-boundary gates required")
        if "VALENCE_JTAG_CHAIN_PASS USER2" not in log or "BSCAN_EVENT_CLOCK_PATHS_FULLY_TIMED" not in log:
            ap.error("missing scoped USER2/event-clock constraint audit")
    summary = (reports / "timing_synth.rpt").read_text()
    timing_row = re.search(r"(?m)^\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)"
                           r"\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)", summary)
    if not timing_row:
        raise RuntimeError("Vivado timing summary row shape changed")
    result["hold_whs_ns"] = float(timing_row[5])
    result["hold_ths_ns"] = float(timing_row[6])
    result["hold_failing_endpoints"] = int(timing_row[7])
    result["setup_failing_endpoints"] = int(timing_row[3])
    result["all_synthesis_timing_met"] = result["setup_wns_ns"] >= 0 and result["hold_whs_ns"] >= 0
    cpu_row = re.search(r"(?m)^orbital_i1_cpu\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)"
                        r"\s+([+-]?\d+\.\d+)\s+([+-]?\d+\.\d+)\s+(\d+)\s+(\d+)", summary)
    if cpu_row:
        result["cpu_hold_whs_ns"] = float(cpu_row[5])
        result["cpu_hold_failing_endpoints"] = int(cpu_row[7])
    utilization = {}
    text = (reports / "utilization.rpt").read_text()
    for label in ("CLB LUTs", "CLB Registers", "LUT as Memory", "Block RAM Tile", "DSPs"):
        match = re.search(r"(?m)^\|\s*" + re.escape(label) + r"\*?\s*\|\s*([\d.]+)", text)
        if not match:
            raise RuntimeError("Vivado utilization report shape changed: " + label)
        utilization[label] = float(match[1]) if "." in match[1] else int(match[1])
    internal = (reports / "setup_internal_synth.rpt").read_text()
    fields = {}
    for label in ("Source", "Destination", "Data Path Delay"):
        match = re.search(r"(?m)^\s*" + re.escape(label) + r":\s*(.+)", internal)
        if match:
            fields[label] = match[1].strip()
    partitions = {}
    for name in ("csr", "instruction_translation", "data_translation", "dcache", "non_fp_endpoint",
                 "fp_arithmetic_s", "fp_arithmetic_d", "fp_misc_s", "fp_misc_d",
                 "core_recovery", "icache", "fetch_aligner", "decode_stage", "execute_stage",
                 "operand_hold", "address_stage", "completion_stage"):
        report = reports / ("setup_" + name + "_synth.rpt")
        if not report.exists():
            continue
        text = report.read_text()
        entry = {}
        for label in ("Source", "Destination", "Data Path Delay", "Logic Levels"):
            match = re.search(r"(?m)^\s*" + re.escape(label) + r":\s*(.+)", text)
            if match:
                entry[label] = match[1].strip()
        match = re.search(r"Slack \((?:VIOLATED|MET)\)\s*:\s*([+-]?\d+\.\d+)ns", text)
        if not match:
            ap.error("missing partition timing path: " + name)
        entry["setup_wns_ns"] = float(match[1])
        partitions[name] = entry
    comparison = None
    comparison_root = reports / "ex-wb-comparison"
    if comparison_root.exists():
        values = json.loads((comparison_root / "result.json").read_text())
        comparison_log = package / "vivado_ex_wb_comparison.log"
        log_text = comparison_log.read_text()
        if "I1_EX_WB_COMPARISON_DONE TWO_EXISTING_CHECKPOINTS NO_SYNTHESIS NO_CONSTRAINT_CHANGES" not in log_text:
            ap.error("EX/WB report-only comparison did not complete")
        rows = re.findall(
            r"(?m)^I1_EX_WB_REPORT_ONLY name=(baseline|current) period=([\d.]+) "
            r"ex_data_wns=([+-]?[\d.]+) wb_control_wns=([+-]?[\d.]+) checkpoint=(.+)$", log_text)
        if len(rows) != 2 or {row[0] for row in rows} != {"baseline", "current"}:
            ap.error("EX/WB native log input ledger missing/ambiguous")
        checkpoints = {}
        for label, period, ex_wns, wb_wns, native_path in rows:
            if abs(float(period) - actual_period_ns) > 0.000001:
                ap.error("EX/WB comparison changed the clock")
            if (float(ex_wns) != values[label]["ex_result_data_wns_ns"] or
                    float(wb_wns) != values[label]["wb_control_wns_ns"]):
                ap.error("EX/WB result differs from native log")
            native_path = native_path.strip()
            if re.match(r"^[A-Za-z]:/", native_path):
                checkpoint = Path("/mnt/" + native_path[0].lower() + native_path[2:])
            else:
                checkpoint = Path(native_path)
            checkpoint = checkpoint.resolve()
            if not checkpoint.is_file():
                ap.error("comparison checkpoint no longer exists")
            if label == "current" and checkpoint != (reports / "synthesized_constrained.dcp").resolve():
                ap.error("comparison current DCP is not this exact synthesis")
            checkpoints[label] = {"path": str(checkpoint), "sha256": sha(checkpoint)}
            for name in ("ex_result_data", "wb_control"):
                path = comparison_root / label / ("setup_" + name + "_synth.rpt")
                if not path.is_file():
                    ap.error("missing EX/WB comparison path report")
        stage_rows = re.findall(
            r"(?m)^I1_STAGE_REPORT_ONLY name=(baseline|current) stage=([a-z_]+) wns=([+-]?[\d.]+)$", log_text)
        if stage_rows:
            stages = {"decode_stage", "execute_stage", "operand_hold", "address_stage", "completion_stage"}
            expected_rows = {(label, stage) for label in ("baseline", "current") for stage in stages}
            if len(stage_rows) != 10 or {(label, stage) for label, stage, _ in stage_rows} != expected_rows:
                ap.error("stage comparison ledger missing/ambiguous")
            for label, stage, slack in stage_rows:
                path = comparison_root / label / ("setup_" + stage + "_synth.rpt")
                if not path.is_file():
                    ap.error("missing stage comparison path report")
                match = re.search(r"Slack \((?:VIOLATED|MET)\)\s*:\s*([+-]?\d+\.\d+)ns", path.read_text())
                if (not match or float(match[1]) != float(slack) or
                        values[label][stage + "_wns_ns"] != float(slack)):
                    ap.error("stage comparison JSON/native/path mismatch")
        comparison = {"scope": "REPORT_ONLY_TWO_EXISTING_CONSTRAINED_DCPS_NO_SYNTHESIS",
                      "values": values, "checkpoints": checkpoints,
                      "script_sha256": sha(ROOT / "fpga/inorder/report_ex_wb_comparison.tcl"),
                      "log_sha256": sha(comparison_log)}
    if output.exists():
        ap.error("fresh physical evidence output required")
    output.mkdir(parents=True)
    shutil.copytree(reports, output / "reports", ignore=shutil.ignore_patterns("*.dcp"))
    shutil.copyfile(package / "manifest.json", output / "rtl-manifest.json")
    if args.partial_console:
        for p in fragments:
            shutil.copy2(p, output / p.name)
    else:
        shutil.copyfile(package / "vivado_synth.log", output / "vivado_synth.log")
    if comparison:
        shutil.copyfile(comparison_log, output / "vivado_ex_wb_comparison.log")
        shutil.copyfile(ROOT / "fpga/inorder/report_ex_wb_comparison.tcl", output / "report_ex_wb_comparison.tcl")
    mhz = int(round(result["target_mhz"]))
    receipt = {"status": ("SYNTHESIS_SETUP_MEETS_" + str(mhz) + "MHZ_ONLY" if result["setup_wns_ns"] >= 0
                          else "SYNTHESIS_SETUP_FAILS_" + str(mhz) + "MHZ_ESTIMATE"),
               "scope": manifest["synthesis_scope"] + "; SYNTHESIS_ONLY_NOT_PLACED_OR_ROUTED",
               "physical_qualified": False, "board_qualified": False, "bit_generated": False,
               "pipeline": manifest["pipeline"], "flags": manifest["flags"],
               "reused_synthesis": reused,
               "console_complete": not args.partial_console,
               "console_scope": "partial native completion/gates stdout" if args.partial_console else "native log",
               "package": str(package), "rtl_manifest_sha256": sha(package / "manifest.json"),
               "gsim_receipt": str(acceptance), "gsim_receipt_sha256": sha(acceptance),
               "source_sha256": manifest["source_sha256"], "synthesis": result, "utilization": utilization,
               "worst_internal": fields, "timing_partitions": partitions,
               "ex_wb_comparison": comparison,
               "collector_sha256": sha(Path(__file__)),
               "reports_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print(json.dumps({k: receipt[k] for k in ("status", "synthesis", "utilization", "worst_internal")}, indent=2))
    print("RECEIPT", output / "receipt.json", flush=True)
if __name__ == "__main__":
    main()
