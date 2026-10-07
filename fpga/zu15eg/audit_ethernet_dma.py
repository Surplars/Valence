#!/usr/bin/env python3
"""Strict combined candidate audit; archive native CAD evidence into WSL."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
from audit_ethernet_batch import resources


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_files(directory, recorded):
    for name, digest in recorded.items():
        if sha(directory / name) != digest:
            raise RuntimeError("input/artifact drift: " + str(directory / name))


def hierarchy_resources(path, instance):
    for line in path.read_text().splitlines():
        columns = [x.strip() for x in line.split("|")[1:-1]]
        if columns and columns[0] == instance:
            return {"lut": int(columns[2]), "ff": int(columns[6]), "ramb36": int(columns[7]),
                    "ramb18": int(columns[8]), "uram": int(columns[9]), "dsp": int(columns[10])}
    raise RuntimeError("missing hierarchical resources: " + instance)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("native_root", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--archive", type=Path)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[2]
    native = a.native_root.resolve()
    export_path = native / "export-receipt.json"
    export = json.loads(export_path.read_text())
    if not export.get("packet_dma") or export["profile"] != "staged-fetch-feedback":
        raise RuntimeError("wrong candidate")
    check_files(root, export["export_inputs_sha256"])
    check_files(native / "soc-rtl", export["soc_rtl_sha256"])
    check_files(native / "core-rtl", export["cpu_modules_sha256"])
    check_files(native / "soc-rtl", export["cpu_modules_sha256"])
    short_path = Path(export["short_receipt"])
    if sha(short_path) != export["short_receipt_sha256"]:
        raise RuntimeError("short receipt drift")
    short = json.loads(short_path.read_text())
    if short["status"] != "passed":
        raise RuntimeError("functional gate failed")
    # The production elaboration exercised in the short gate is the exact RTL
    # synthesized here, not just a behavioral wrapper with similar parameters.
    if short["production_rtl"] != export["soc_rtl_sha256"]:
        raise RuntimeError("CAD RTL differs from accepted production elaboration")
    cpu = native / "reports/MachineCore"
    soc = native / "reports/EthernetSocTop"
    log_path = native / "cad.log"
    log = log_path.read_text(errors="replace")
    for marker in ("ETHERNET_SOC_REAL_IP_SYNTH_COMPLETE", "ETHERNET_CPU_BATCH_COMPLETE",
                   "ETHERNET_DMA_STREAM_CDC_COUNT 4"):
        if marker not in log:
            raise RuntimeError("missing completed stage: " + marker)
    if re.search(r"(?m)^ERROR:|Timing 38-470", log):
        raise RuntimeError("CAD errors/reference-clock mismatch")
    for name in (cpu / "post_synth.dcp", cpu / "post_route.dcp", soc / "integrated_post_synth.dcp"):
        if not name.is_file():
            raise RuntimeError("missing checkpoint: " + str(name))
    paths = list(csv.DictReader((cpu / "path_metrics.tsv").open(), delimiter="\t"))
    metrics = {(row["scope"], row["delay_type"]): row for row in paths}
    setup = float(metrics[("internal", "max")]["slack_ns"])
    hold = float(metrics[("internal", "min")]["slack_ns"])
    cdc = (soc / "post_synth_cdc.rpt").read_text()
    cdc_counts = {key: {"severity": severity, "count": int(count)} for key, severity, count in
                  re.findall(r"(?m)^(CDC-\d+)\s+(Info|Warning|Critical)\s+(\d+)\s+", cdc)}
    if not cdc_counts:
        raise RuntimeError("missing CDC summary")
    fifo_buses = re.findall(r"VALENCE_CDC_BOUNDED (readGraySync_stage0|writeGraySync_stage0) "
                           r"starts=(\d+) ends=(\d+) budget=([\d.]+)", log)
    if len(fifo_buses) != 8 or any(int(x[1]) != 5 or int(x[2]) != 5 or float(x[3]) != 8.0 for x in fifo_buses):
        raise RuntimeError("four FIFO Gray-pointer physical constraints not applied")
    cdc_path = native / "cdc-xsim-r1/receipt.json"
    cdc_short = json.loads(cdc_path.read_text())
    if cdc_short["status"] != "PASS_CDC_SHORT_RTL":
        raise RuntimeError("CDC short RTL gate failed")
    for name, digest in cdc_short["input_sha256"].items():
        # Native Python recorded UNC input names; validate staged copies by
        # basename and current WSL sources separately below.
        filename = name.replace("\\", "/").rsplit("/", 1)[-1]
        if sha(native / "cdc-xsim-r1" / filename) != digest:
            raise RuntimeError("CDC staged input drift: " + filename)
        source = root / ("fpga/zu15eg" if filename in {"cdc_tb.sv", "cdc_run.tcl"}
                         else "build/fpga/ethernet-dma-20261004-r2/cdc-rtl") / filename
        if sha(source) != digest:
            raise RuntimeError("CDC source drift: " + filename)
    baseline_path = root / "build/fpga/axi-ethernet-20261004-r1/audit-final-r1.json"
    baseline = json.loads(baseline_path.read_text())
    old_cpu = root / "build/fpga/axi-ethernet-20261004-r1/native-final-r1/core-rtl/MachineCore.sv"
    def header(file):
        match = re.search(r"(?s)module MachineCore\s*\(.*?\);", file.read_text())
        if not match:
            raise RuntimeError("missing CPU interface")
        return re.sub(r"\s+", "", match[0])
    same_ports = header(old_cpu) == header(native / "core-rtl/MachineCore.sv")
    report = {
        "status": "PASS_CPU_INTERNAL_OOC" if setup >= 0 and hold >= 0 else "FAIL_CPU_INTERNAL_TIMING",
        "profile": "staged-fetch-feedback", "packet_dma": True, "isa": "rv64gc", "issue_width": 2,
        "cpu_period_ns": 10, "ethernet_period_ns": 8, "reference_period_ns": 3,
        "cpu_setup_slack_ns": setup, "cpu_hold_slack_ns": hold, "cpu_paths": paths,
        "cpu_post_route_resources": resources(cpu / "post_route_utilization.rpt"),
        "soc_post_synth_resources": hierarchy_resources(soc / "post_synth_utilization.rpt", "EthernetSocTop"),
        "network_dma_post_synth_resources": hierarchy_resources(soc / "post_synth_utilization.rpt", "packetDma"),
        "baseline": {"receipt": str(baseline_path), "sha256": sha(baseline_path),
            "setup_ns": baseline["cpu_setup_slack_ns"], "hold_ns": baseline["cpu_hold_slack_ns"],
            "resources": baseline["cpu_post_route_resources"], "same_production_cpu_ports": same_ports},
        "real_ip_integration_synthesis": "PASS_ZERO_UNRESOLVED_FUNCTIONAL_BLACKBOXES",
        "four_stream_cdc_instances": 4, "gray_pointer_buses_bounded": 8, "cdc_summary": cdc_counts,
        "integration_cdc_status": "UNQUALIFIED_CRITICALS_PRESENT" if any(
            x["severity"] == "Critical" and x["count"] for x in cdc_counts.values()) else "UNQUALIFIED_NOT_ROUTED",
        "physical_cdc_routed_verified": False, "cdc_short_receipt_sha256": sha(cdc_path),
        "short_receipt_sha256": sha(short_path), "export_receipt_sha256": sha(export_path),
        "scope": "short DMA/coherence/TL + real-IP integration synthesis + CPU-only OOC route; not whole-board/network qualification",
        "dma_routed_timing_verified": False, "linux_network_driver_verified": False,
        "on_board_network_verified": False, "whole_board_timing_verified": False, "bit_generated": False,
        "license": "MAC Design_Linking in saved real IP status; hardware authorization remains unproven",
        "limits": ["single descriptor/channel, max 2048 bytes, scalar coherent memory traffic; no SG/rings/line-rate claim",
            "TX DMA completion is enqueue into CDC, not PHY transmit completion",
            "CDC criticals/warnings are reported, not waived; no joint routed skew/delay or PHY IO signoff",
            "saved CPU instruction tests protect unchanged core; new packet/concurrency tests use actual coherent fabric but no full CPU network firmware"],
    }
    chosen = [export_path, log_path, native / "cad.jou"]
    for folder in ("core-rtl", "soc-rtl", "fpga", "reports", "cdc-xsim-r1"):
        chosen += [f for f in (native / folder).rglob("*") if f.is_file() and
                   f.suffix in {".sv", ".v", ".tcl", ".rpt", ".tsv", ".dcp", ".edf", ".log", ".json", ".xdc"}]
    recorded = {str(f.relative_to(native)): sha(f) for f in sorted(set(chosen))}
    if a.archive:
        archive = a.archive.resolve()
        archive.mkdir(parents=True, exist_ok=False)
        for name, digest in recorded.items():
            target = archive / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(native / name, target)
            if sha(target) != digest:
                raise RuntimeError("archive byte mismatch: " + name)
        # Preserve dirty-worktree source inputs as evidence, without committing,
        # replacing the user's working tree, or copying license contents.
        snapshot = archive / "source-inputs"
        for name, digest in export["export_inputs_sha256"].items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / name, target)
            if sha(target) != digest:
                raise RuntimeError("source snapshot mismatch: " + name)
        audit_tools = archive / "audit-tools"
        audit_tools.mkdir()
        report["audit_tools_sha256"] = {}
        for name in ("audit_ethernet_dma.py", "audit_ethernet_batch.py"):
            source = root / "fpga/zu15eg" / name
            shutil.copy2(source, audit_tools / name)
            report["audit_tools_sha256"][name] = sha(source)
        report["archive"] = {"directory": str(archive), "files": len(recorded),
                              "bytes": sum((native / name).stat().st_size for name in recorded),
                              "source_inputs_sha256": export["export_inputs_sha256"]}
    check_files(root, export["export_inputs_sha256"])
    check_files(native, recorded)
    report["files_sha256"] = recorded
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("status", "cpu_setup_slack_ns", "cpu_hold_slack_ns",
        "cpu_post_route_resources", "soc_post_synth_resources", "cdc_summary")}, indent=2))


if __name__ == "__main__":
    main()
