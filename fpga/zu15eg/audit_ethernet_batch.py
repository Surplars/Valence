#!/usr/bin/env python3
"""Record real-IP linking, CPU register timing and byte-exact partition reuse."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resources(path):
    text = path.read_text()
    values = {}
    for key, pattern in (("lut", r"CLB LUTs\*?"), ("ff", r"CLB Registers"), ("dsp", r"DSPs")):
        match = re.search(r"\|\s*" + pattern + r"\s*\|\s*(\d+)\s*\|", text)
        if not match:
            raise RuntimeError("missing resource: " + key)
        values[key] = int(match[1])
    return values


def cpu_graph(old, new):
    pending, visited, hashes = ["MachineCore"], set(), {}
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        before, after = old / (name + ".sv"), new / (name + ".sv")
        if sha(before) != sha(after):
            raise RuntimeError("cached CPU differs: " + name)
        hashes[name + ".sv"] = sha(after)
        pending.extend(child for child in re.findall(r"(?m)^\s*(\w+)\s+\w+\s*\(", before.read_text())
                       if (old / (child + ".sv")).is_file())
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("native_root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    native = args.native_root.resolve()
    cpu = native / "reports-r2/MachineCore"
    soc = native / "reports-r2/EthernetSocTop_cdc_r2"
    paths = list(csv.DictReader((cpu / "path_metrics.tsv").open(), delimiter="\t"))
    metrics = {(row["scope"], row["delay_type"]): row for row in paths}
    setup = float(metrics[("internal", "max")]["slack_ns"])
    hold = float(metrics[("internal", "min")]["slack_ns"])
    log = (native / "ethernet_link_r5.log").read_text()
    if "ETHERNET_LINK_ONLY_COMPLETE" not in log or not (soc / "integrated_post_synth.dcp").is_file():
        raise RuntimeError("real-IP integration checkpoint/completion proof missing")
    if "Timing 38-470" in log:
        raise RuntimeError("MAC reference clock mismatch remains")
    hashes = cpu_graph(native / "core-rtl", native / "soc-rtl-r2")
    cdc_text = (soc / "post_synth_cdc.rpt").read_text()
    cdc_counts = {key: {"severity":severity, "count":int(count)} for key, severity, count in
                  re.findall(r"(?m)^(CDC-\d+)\s+(Info|Warning|Critical)\s+(\d+)\s+", cdc_text)}
    functional = root / "build/gsim/ethernet-stage-20261004-r2/receipt.json"
    board = root / "build/gsim/rv64gc-board-ethernet-20261004-r1/receipt.json"
    if json.loads(functional.read_text())["status"] != "passed":
        raise RuntimeError("CPU short batch did not pass")
    if json.loads(board.read_text())["status"] != "PASS_BOARD_FUNCTIONAL_SMOKE":
        raise RuntimeError("RV64GC board mechanisms did not pass")
    reset_log = native / "reset-xsim-r1/xsim.log"
    if "ETHERNET_ASYNC_RESET_PASS" not in reset_log.read_text():
        raise RuntimeError("actual asynchronous reset RTL proof missing")
    unit_log = root / "build/gsim/ethernet-reset-20261004-r3/test.log"
    if "ETHERNET_RESET_IRQ_PASS" not in unit_log.read_text():
        raise RuntimeError("synchronous count/IRQ unit proof missing")
    report = {"status": "PASS_CPU_INTERNAL_OOC" if setup >= 0 and hold >= 0 else "FAIL_CPU_INTERNAL_TIMING",
        "profile":"staged-ethernet", "isa":"rv64gc", "issue_width":2,
        "cpu_period_ns":10, "ethernet_period_ns":8, "delay_reference_period_ns":3,
        "real_ip_integration_synthesis":"PASS_ZERO_UNRESOLVED_FUNCTIONAL_BLACKBOXES",
        "cpu_setup_slack_ns":setup, "cpu_hold_slack_ns":hold,
        "cpu_paths":paths, "cpu_post_route_resources":resources(cpu / "post_route_utilization.rpt"),
        "same_cpu_dependency_modules_sha256":hashes,
        "cdc_summary":cdc_counts,
        "license":"Design_Linking remains after supplied license; no MAC bit authorization established",
        "comparison_limit":"production compiler-pruned CPU ports differ from previous bare MachineCore OOC; no pure resource A/B claimed",
        "scope":"integrated synthesis + CPU-only route; NOT whole-board, PHY IO, network DMA or Linux qualification",
        "on_board_verified":False, "whole_board_timing_verified":False, "bit_generated":False,
        "cpu_functional_receipt_sha256":sha(functional), "rv64gc_mechanism_receipt_sha256":sha(board),
        "files_sha256":{str(p.relative_to(native)):sha(p) for p in (
            cpu / "post_route.dcp", cpu / "path_metrics.tsv", cpu / "post_route_utilization.rpt",
            soc / "integrated_post_synth.dcp", soc / "post_synth_cdc.rpt", soc / "post_synth_timing.rpt",
            native / "ethernet_link_r5.log", native / "rom-ip/blk_mem_gen_0.dcp", reset_log)}}
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","cpu_setup_slack_ns","cpu_hold_slack_ns",
          "cpu_post_route_resources","real_ip_integration_synthesis","cdc_summary")}, indent=2))


if __name__ == "__main__":
    main()
