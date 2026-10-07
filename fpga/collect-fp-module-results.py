#!/usr/bin/env python3
"""Collect immutable 10 ns FPU OOC results; never infer board qualification."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

TOPS = [
    "FloatingPointAddS", "FloatingPointMultiplyS", "FloatingPointFusedS",
    "FloatingPointDivSqrtS", "FloatingPointMiscS",
    "FloatingPointAddD", "FloatingPointMultiplyD", "FloatingPointFusedD",
    "FloatingPointDivSqrtD", "FloatingPointMiscD",
    "FloatingPointState", "FloatingPointExecute", "FloatingPointSystem",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(report_root, rtl_root):
    modules = {}
    for top in TOPS:
        directory = report_root / top
        table = directory / "path_metrics.tsv"
        required = [table, directory / "post_route_utilization.rpt",
                    directory / "post_route_timing.rpt", directory / "post_route.dcp"]
        if not all(p.is_file() for p in required):
            modules[top] = {"status": "PENDING"}
            continue
        with table.open() as stream:
            paths = {}
            for row in csv.DictReader(stream, delimiter="\t"):
                key = row["scope"] + "_" + row["delay_type"]
                paths[key] = {
                    "slack_ns": float(row["slack_ns"]),
                    "data_delay_ns": float(row["data_delay_ns"]),
                    "logic_levels": int(row["logic_levels"]),
                    "startpoint": row["startpoint"], "endpoint": row["endpoint"],
                }
        if not {"all_max", "all_min", "internal_max", "internal_min"} <= paths.keys():
            raise RuntimeError(f"Incomplete sequential path metrics: {table}")
        utilization = (directory / "post_route_utilization.rpt").read_text()
        resources = {}
        for name, label in (("lut", "CLB LUTs"), ("ff", "CLB Registers"), ("dsp", "DSPs")):
            match = re.search(r"\|\s*" + label + r"\s*\|\s*(\d+)\s*\|", utilization)
            if not match:
                raise RuntimeError(f"Missing resource {label}: {directory}")
            resources[name] = int(match[1])
        internal_pass = paths["internal_max"]["slack_ns"] >= 0 and paths["internal_min"]["slack_ns"] >= 0
        modules[top] = {
            "status": "INTERNAL_SETUP_HOLD_MET" if internal_pass else "INTERNAL_TIMING_FAILED",
            "paths": paths, "resources": resources,
            "files": {p.name: digest(p) for p in required},
            "board_qualified": False,
        }
    completed = [value for value in modules.values() if value["status"] != "PENDING"]
    full = len(completed) == len(TOPS)
    all_internal = full and all(value["status"] == "INTERNAL_SETUP_HOLD_MET" for value in completed)
    return {
        "schema_version": 1,
        "status": ("INTERNAL_SETUP_HOLD_MET_BOUNDARY_UNQUALIFIED" if all_internal else
                   "INTERNAL_TIMING_FAILED" if full else "PARTIAL"),
        "part": "xczu15eg-ffvb1156-2-i", "period_ns": 10.0,
        "completed_modules": len(completed), "expected_modules": len(TOPS),
        "rtl_sha256": {str(p.relative_to(rtl_root)): digest(p) for p in sorted(rtl_root.rglob("*.sv"))},
        "modules": modules,
        "limitations": [
            "OOC module measurements do not qualify integrated core or board timing.",
            "Zero input/output delays are comparison conventions, not physical interface budgets.",
            "Reset input is excluded from the OOC boundary delay budget.",
            "All-scope boundary hold must be reported separately; it is not hidden or waived.",
            "This collector does not establish functional correctness or source/RTL equivalence.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path)
    parser.add_argument("rtl", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Evidence output already exists; choose a fresh path")
    result = collect(args.reports.resolve(), args.rtl.resolve())
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(f'{result["status"]}: {result["completed_modules"]}/{result["expected_modules"]}')
    for top, value in result["modules"].items():
        if value["status"] != "PENDING":
            path = value["paths"]["internal_max"]
            print(f'{top}: internal WNS={path["slack_ns"]:+.3f}ns, '
                  f'data={path["data_delay_ns"]:.3f}ns, resources={value["resources"]}')
    return 0 if result["completed_modules"] == len(TOPS) else 2


if __name__ == "__main__":
    raise SystemExit(main())
