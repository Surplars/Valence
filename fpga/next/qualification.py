#!/usr/bin/env python3
"""Source-bound module promotion checks. Functional acceptance is not FPGA signoff.

An evidence document is a reviewable index into actual artifact files, not proof
by itself. This checker rejects missing, stale or self-contradictory evidence and
keeps structural estimates separate from real implementation results.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys

SCHEMA = "valence-fpga-next-module-evidence-v1"
HASH = re.compile(r"[0-9a-f]{64}\Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_file(root: Path, name: str) -> Path:
    path = Path(name)
    if not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name or "\\" in name:
        raise ValueError("unsafe relative evidence path: " + name)
    target = root / path
    if any(root.joinpath(*path.parts[:n]).is_symlink() for n in range(1, len(path.parts) + 1)):
        raise ValueError("linked evidence path: " + name)
    if not target.is_file():
        raise ValueError("missing evidence file: " + name)
    return target


def snapshot(root: Path, selected_sources=()) -> dict[str, str]:
    files = [p for folder in ("src/main/scala", "third_party/berkeley-hardfloat/src/main/scala")
             for p in (root / folder).rglob("*.scala")]
    # Blackbox resources are executable RTL inputs, including the JTAG transport.
    resources = root / "src/main/resources"
    if resources.exists():
        files += [p for p in resources.rglob("*") if p.is_file()]
    files += [root / "build.mill", root / ".mill-version"]
    # Native wrappers and constraints are selected per board/export. Require an
    # explicit safe path rather than treating every unrelated experiment as used.
    files += [relative_file(root, name) for name in selected_sources]
    return {p.relative_to(root).as_posix(): sha(relative_file(root, p.relative_to(root).as_posix()))
            for p in sorted(set(files))}


def check_mapping(root: Path, mapping: dict, label: str, errors: list[str]) -> None:
    if not isinstance(mapping, dict) or not mapping:
        errors.append(label + " inventory is empty")
        return
    for name, digest in mapping.items():
        try:
            if not isinstance(digest, str) or not HASH.fullmatch(digest):
                raise ValueError("invalid SHA256: " + str(name))
            if sha(relative_file(root, name)) != digest:
                raise ValueError("changed evidence file: " + name)
        except (OSError, TypeError, ValueError) as error:
            errors.append(label + ": " + str(error))


def finite_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validate(evidence: dict, source_root: Path, artifact_root: Path) -> dict:
    errors: list[str] = []
    physical_errors: list[str] = []
    if evidence.get("schema") != SCHEMA:
        errors.append("unsupported evidence schema")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", str(evidence.get("module", ""))):
        errors.append("module needs a stable lowercase name")
    if evidence.get("change_kind") not in ("optimization", "new-interface", "verification-only"):
        errors.append("unsupported change kind")
    check_mapping(source_root, evidence.get("candidate_sources", {}), "candidate source", errors)
    required = evidence.get("required_sources", [])
    if not isinstance(required, list) or not required or not set(required) <= set(evidence.get("candidate_sources", {})):
        errors.append("required module source inventory is absent or incomplete")
    check_mapping(artifact_root, evidence.get("artifacts", {}), "artifact", errors)
    tests = evidence.get("tests", [])
    if not isinstance(tests, list) or not tests:
        errors.append("no independently checked tests")
        tests = []
    positive = [t for t in tests if t.get("kind") == "positive"]
    negative = [t for t in tests if t.get("kind") == "negative"]
    if not positive or not any(t.get("independent_oracle") is True for t in positive):
        errors.append("missing independent positive oracle")
    if not negative:
        errors.append("missing deliberate mismatch/illegal-state negative control")
    artifacts = evidence.get("artifacts", {})
    for test in tests:
        if test.get("kind") not in ("positive", "negative"):
            errors.append("invalid test kind: " + str(test.get("name")))
        if not isinstance(test.get("command"), list) or not test["command"] or not all(isinstance(x, str) for x in test["command"]):
            errors.append("test lacks exact command: " + str(test.get("name")))
        if test.get("log") not in artifacts:
            errors.append("test log is not hash bound: " + str(test.get("name")))
        expected, actual = test.get("expected_exit"), test.get("actual_exit")
        if not isinstance(expected, int) or isinstance(expected, bool) or actual != expected:
            errors.append("wrong/unrecorded test exit: " + str(test.get("name")))
        if test.get("kind") == "positive" and actual != 0:
            errors.append("positive test failed: " + str(test.get("name")))
        if test.get("kind") == "negative" and (actual == 0 or not test.get("rejection_anchor")):
            errors.append("negative test did not prove intended rejection: " + str(test.get("name")))
        log_name = test.get("log")
        try:
            log = relative_file(artifact_root, log_name).read_text(errors="replace")
            for anchor in test.get("required_anchors", []):
                if not anchor or anchor not in log:
                    errors.append("test anchor missing: " + str(test.get("name")))
            if test.get("kind") == "negative" and test.get("rejection_anchor") not in log:
                errors.append("intended negative anchor absent: " + str(test.get("name")))
        except (OSError, TypeError, ValueError):
            pass  # The hash-bound artifact check reports missing/unsafe paths.
    baseline = evidence.get("baseline", {})
    if evidence.get("change_kind") == "optimization":
        if not re.fullmatch(r"[0-9a-f]{40}", str(baseline.get("source_commit", ""))):
            errors.append("optimization lacks immutable baseline revision")
        if baseline.get("status") != "PASS" or baseline.get("receipt") not in artifacts:
            errors.append("optimization lacks a passed hash-bound baseline receipt")
        else:
            try:
                baseline_document = json.loads(relative_file(artifact_root, baseline["receipt"]).read_text())
                if not str(baseline_document.get("status", "")).upper().startswith("PASS"):
                    errors.append("baseline receipt itself is not passed")
            except (OSError, ValueError, TypeError, AttributeError):
                errors.append("baseline receipt is not readable JSON")
        if not evidence.get("performance"):
            errors.append("optimization has no measured latency/throughput comparison")
    topology = evidence.get("storage_topology", [])
    if not isinstance(topology, list):
        errors.append("storage topology must be a list")
    else:
        for memory in topology:
            for field in ("width_bits", "depth", "read_ports", "write_ports", "read_latency_cycles"):
                if not isinstance(memory.get(field), int) or isinstance(memory.get(field), bool) or memory[field] < 0:
                    errors.append("invalid memory port geometry: " + str(memory.get("name")))
            if memory.get("collision_policy") not in ("forbidden-and-asserted", "old-data", "new-data-bypass", "explicit-priority"):
                errors.append("unspecified collision policy: " + str(memory.get("name")))
    comparisons = []
    for metric in evidence.get("performance", []):
        a, b = metric.get("baseline"), metric.get("candidate")
        if not finite_number(a) or not finite_number(b) or a < 0 or b < 0 or not metric.get("unit"):
            errors.append("invalid performance measurement: " + str(metric.get("name")))
            continue
        if metric.get("evidence") not in artifacts:
            errors.append("performance measurement lacks hash-bound evidence: " + str(metric.get("name")))
        direction = metric.get("direction")
        if direction not in ("lower", "higher", "equal"):
            errors.append("unspecified performance direction: " + str(metric.get("name")))
            continue
        meets = b <= a if direction == "lower" else b >= a if direction == "higher" else b == a
        comparisons.append({"name": metric.get("name"), "unit": metric["unit"],
                            "baseline": a, "candidate": b, "meets_baseline": meets,
                            "candidate_over_baseline": b / a if a else None})
        if not meets and not metric.get("accepted_tradeoff"):
            errors.append("unreviewed performance regression: " + str(metric.get("name")))
    physical = evidence.get("physical")
    if physical is None:
        physical_errors.append("no source-matched FPGA implementation result")
    else:
        if physical.get("kind") != "routed":
            physical_errors.append("physical result is not routed implementation")
        if physical.get("candidate_sources") != evidence.get("candidate_sources"):
            physical_errors.append("physical result does not match candidate sources")
        if physical.get("clock_hz") != 100000000:
            physical_errors.append("physical result changed the 100 MHz CPU contract")
        for field in ("setup_wns_ns", "hold_whs_ns"):
            if not finite_number(physical.get(field)) or physical[field] < 0:
                physical_errors.append("missing/failing physical " + field)
        if physical.get("constraints_changed") is not False:
            physical_errors.append("constraints are changed or unverified")
        check_mapping(artifact_root, physical.get("reports", {}), "physical report", physical_errors)
        check_mapping(source_root, physical.get("constraints", {}), "physical constraint", physical_errors)
    experimental = not errors
    return {
        "schema": "valence-fpga-next-promotion-result-v1",
        "module": evidence.get("module"),
        "experimental_integration_eligible": experimental,
        "source_matched_routed_result": experimental and not physical_errors,
        "status": "REJECTED" if errors else "FUNCTIONAL_CANDIDATE_PHYSICAL_PENDING" if physical_errors else "ROUTED_CANDIDATE_BOARD_PENDING",
        "errors": errors, "physical_pending": physical_errors, "performance": comparisons,
        "limits": ["A checked evidence index does not replace reviewing its independent oracle and source change.",
                   "FIR/memory/FF-bit structural metrics are not LUT/resource measurements.",
                   "Even routed timing does not prove board, PHY, Linux or full CDC behavior."]
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="operation", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    snap.add_argument("--output", type=Path, required=True)
    snap.add_argument("--include", action="append", default=[],
                      help="selected native wrapper/constraint/resource path, relative to source root; repeat as needed")
    check = sub.add_parser("check")
    check.add_argument("evidence", type=Path)
    check.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    check.add_argument("--artifact-root", type=Path, required=True)
    check.add_argument("--output", type=Path)
    args = ap.parse_args()
    if args.operation == "snapshot":
        result = {"schema": "valence-fpga-next-source-snapshot-v1", "sha256": snapshot(args.source_root.resolve(), args.include)}
    else:
        result = validate(json.loads(args.evidence.read_text()), args.source_root.resolve(), args.artifact_root.resolve())
    rendered = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")
    return 2 if result.get("status") == "REJECTED" else 0


if __name__ == "__main__":
    sys.exit(main())
