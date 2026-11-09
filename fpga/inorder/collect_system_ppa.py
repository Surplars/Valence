#!/usr/bin/env python3
"""Collect routed managed-I1 DUT timing, resource scope, and bounded CDC evidence."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def resources(path):
    names = ["lut", "logic_lut", "lutram", "srl", "ff", "bram36", "bram18", "uram", "dsp"]
    result, stack = {}, []
    for line in path.read_text().splitlines():
        cells = line.split("|")[1:-1]
        if len(cells) != 11 or not cells[2].strip().isdigit():
            continue
        label = cells[0].strip()
        depth = (len(cells[0]) - len(cells[0].lstrip()) - 1) // 2
        count = dict(zip(names, map(lambda cell: int(cell.strip()), cells[2:])))
        if label.startswith("("):
            if label == "(I1System300Context)":
                result["top_local_includes_fixture"] = count
            continue
        stack = stack[:depth]
        stack.append(label)
        key = "/".join(stack[1:]) or "top"
        result[key] = count
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    hierarchy = resources(root / "impl/utilization_hierarchical.rpt")
    fixture = hierarchy["top_local_includes_fixture"]["ff"]
    # Every top-local FF is an explicitly declared port-capture register.
    # The top-local LUTRAM is hoisted DUT logic and remains in DUT totals.
    assert fixture == 624, "review changed port-capture fixture before subtracting registers"
    total = hierarchy["top"]
    dut = {**total, "ff": total["ff"] - fixture}
    timing = {row["domain"]: {
        "setup_ns": float(row["setup_ns"]), "hold_ns": float(row["hold_ns"]),
        "negative_setup_endpoints": int(row["negative_setup_endpoints"]),
        "negative_hold_endpoints": int(row["negative_hold_endpoints"])
    } for row in rows(root / "audit-dut/internal_result.tsv")}
    assert set(timing) == {"cpu", "vpu", "system"}
    covered = rows(root / "impl/cdc_coverage.tsv")
    assert covered, "missing bounded crossing coverage"
    skew = (root / "impl/bus_skew.rpt").read_text()
    assert "VIOLATED" not in skew, "bounded CDC bus skew violation"
    cdc_slack = min(float(row["slack_ns"]) for row in covered)
    internal_pass = all(domain["setup_ns"] >= 0 and domain["hold_ns"] >= 0 for domain in timing.values())
    report = {
        "status": "ROUTED_DUT_300MHZ_MET" if internal_pass and cdc_slack >= 0 else "ROUTED_DUT_300MHZ_NOT_MET",
        "scope": "independent CPU/VPU/always-on fabric; DUT register-to-register timing",
        "clock_target_mhz": {"cpu": 300, "vpu": 300, "system": 300},
        "vivado_threads": 8, "resources_including_fixture": total,
        "port_capture_fixture_ff": fixture, "DUT_including_clock_backend": dut,
        "hierarchy": hierarchy, "DUT_timing": timing,
        "bounded_CDC": {"paths": len(covered), "minimum_slack_ns": cdc_slack,
                        "bus_skew_violations": False},
        "external_IO_and_board_signoff": False,
        "functional_export_receipt_sha256": hashlib.sha256((root / "export-receipt.json").read_bytes()).hexdigest(),
        "evidence_sha256": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for directory in [root / "impl", root / "audit-dut"]
            for p in sorted(directory.iterdir()) if p.suffix in [".rpt", ".tsv", ".xdc"]}
    }
    (root / "physical-summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"], dut, timing)


if __name__ == "__main__":
    main()
