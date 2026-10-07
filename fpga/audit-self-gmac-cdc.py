#!/usr/bin/env python3
"""Fail-closed evidence audit; scoped CDC OOC, never board/gate/PMU signoff."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_ROOT = "\\\\wsl.localhost\\Ubuntu-24.04\\home\\openion\\Valence\\"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(name):
    if not name.startswith(WINDOWS_ROOT): raise ValueError("source outside named WSL project")
    return Path(*name[len(WINDOWS_ROOT):].split("\\"))


def require(condition, message):
    if not condition: raise ValueError(message)


def slacks(path):
    found = [float(n) for n in re.findall(r"Slack\s*\([^)]*\)\s*:\s*([-+]?\d+\.\d+)ns", path.read_text())]
    require(found and all(math.isfinite(n) for n in found), "missing/invalid timing: " + str(path))
    return found


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("functional", type=Path)
    p.add_argument("native", type=Path)
    p.add_argument("output", type=Path)
    a = p.parse_args()
    require(not a.output.exists(), "refusing to overwrite audit")
    receipt = a.functional / "receipt.json"
    functional = json.loads(receipt.read_text())
    require(functional["status"] == "PASS_NATIVE_GMAC_CDC_CLOCK_POLICY_SHORT", "functional checks failed")
    require(functional["negative_checks"] == {key: "passed" for key in ("frame", "config", "event", "clock")},
            "independent negatives missing")
    require(any("bidirectional_beats=20480 config_copies=640" in line for line in functional["positive_summary"]),
            "coverage summary changed")
    for name, expected in functional["input_sha256"].items():
        rel = relative(name)
        require(digest(a.functional / "frozen-inputs" / rel) == expected, "frozen input drift: " + str(rel))
        if rel.parts[0] in ("src", "build.mill"):
            require(digest(ROOT / rel) == expected, "qualified live source drift: " + str(rel))
    for name, expected in functional["protected_cpu_dma_sha256"].items():
        require(digest(ROOT / relative(name)) == expected, "protected CPU/DMA changed")
    for name, expected in functional["output_sha256"].items():
        require(digest(a.functional / name) == expected, "functional log drift: " + name)
    rtl = list((a.native / "inputs/rtl").glob("*.sv"))
    require(len(rtl) >= 4, "empty native RTL")
    for path in rtl:
        require(digest(path) == digest(a.functional / path.name), "functional/CAD RTL differs: " + path.name)
    review = a.native / "review-r2"
    require((review / "reviewed_route.dcp").stat().st_size > 1000, "missing routed review DCP")
    setup = min(slacks(review / "internal_setup.rpt"))
    hold = min(slacks(review / "internal_hold.rpt"))
    require(setup >= 0 and hold >= 0, "internal timing failed")
    payload = {}
    for name in ("txFifo", "rxFifo"):
        values = slacks(review / (name + "_payload.rpt"))
        require(len(values) == 38 and min(values) >= 0, "RAM payload not fully bounded or failed")
        payload[name] = {"capture_bits": 38, "max_delay_budget_ns": 8, "min_slack_ns": min(values)}
    skew = [tuple(map(float, n)) for n in re.findall(
        r"^\s+Slow\s+([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s+([-+]?\d+\.\d+)\s*$",
        (review / "bus_skew.rpt").read_text(), re.M)]
    require(len(skew) == 10 and all(r == 8 and actual >= 0 and slack >= 0 for r, actual, slack in skew),
            "expected Gray/held/RAM skew constraints missing or failed")
    cdc = (review / "cdc.rpt").read_text()
    counts = {key: {"severity": severity, "count": int(count)} for key, severity, count in
              re.findall(r"^(CDC-\d+)\s+(Info|Warning|Critical)\s+(\d+)\s+", cdc, re.M)}
    require(counts == {"CDC-3": {"severity": "Info", "count": 11},
                       "CDC-6": {"severity": "Warning", "count": 4},
                       "CDC-15": {"severity": "Warning", "count": 212}}, "unexpected CDC topology/severity")
    rows = re.findall(r"^\s*\d+\s+CDC-\d+\s+(?:Info|Warning|Critical)\s+.*$", cdc, re.M)
    require(len(rows) == 227 and all("Max Delay Datapath Only" in row for row in rows),
            "CDC endpoint missing bounded max-delay constraint")
    util = (a.native / "reports/post_route_utilization.rpt").read_text()
    resources = {}
    for name, label in (("lut", "CLB LUTs"), ("ff", "CLB Registers"), ("lutram", "LUT as Memory"),
                        ("bram_tiles", "Block RAM Tile"), ("dsp", "DSPs")):
        match = re.search(r"\|\s*" + re.escape(label) + r"\s*\|\s*([\d.]+)\s*\|", util)
        require(match is not None, "resource missing: " + label)
        resources[name] = float(match[1])
    require(resources["lut"] < 1500 and resources["ff"] < 2000 and resources["lutram"] > 0,
            "unexpected small-FIFO resource expansion")
    require("NATIVE_GMAC_CDC_REVIEW_DONE same_route_no_synthesis" in (a.native / "review-r2.log").read_text(),
            "review did not complete")
    report = {"status": "PASS_SCOPED_CDC_RETENTION_MODULE_OOC", "functional_receipt": str(receipt),
              "functional_receipt_sha256": digest(receipt), "clock_periods_ns": {"control": 10, "tx": 8, "rx": 8},
              "internal_setup_slack_ns": setup, "internal_hold_slack_ns": hold,
              "resources": resources, "fifo_ram_payload": payload,
              "bus_skew_constraint_count": len(skew), "min_bus_skew_slack_ns": min(s[2] for s in skew),
              "cdc_counts": counts, "cdc_endpoint_count": len(rows), "cdc_critical_count": 0,
              "cdc_warnings_removed_or_waived": False,
              "cdc_warning_scope": "4 Gray synchronizers; 136 atomic held bits and 76 owned RAM capture bits",
              "ooc_clock_source_locations_defined": False, "io_budgets_signed_off": False,
              "physical_gate_verified": False, "production_pmu_mmio_connected": False,
              "whole_gmac_or_board_verified": False, "new_cpu_timing_measurement": False, "bit_generated": False,
              "auditor_sha256": digest(Path(__file__)), "native_file_sha256":
              {str(path.relative_to(a.native)): digest(path) for path in sorted(a.native.rglob("*")) if path.is_file()}}
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"])
    print(json.dumps({key: report[key] for key in ("resources", "internal_setup_slack_ns", "internal_hold_slack_ns",
                                                  "fifo_ram_payload", "min_bus_skew_slack_ns", "cdc_counts")}))


if __name__ == "__main__": main()
