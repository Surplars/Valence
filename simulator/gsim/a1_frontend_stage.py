#!/usr/bin/env python3
"""Fresh-model, zero-added-cycle frontend stage acceptance against a frozen receipt.

Run only after the coordinated Scala compile. This wrapper never compiles Scala
itself or reruns the baseline. It preserves the existing byte/permission oracle
and requires every scenario metric, not an aggregate average, to match exactly.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/gsim"
HOST_INPUTS = (
    "src/test/scala/ooo/A1FetchSupplyGsim.scala",
    "simulator/gsim/a1_fetch_supply.py",
    "simulator/gsim/a1_fetch_supply/driver.cpp",
    "simulator/gsim/a1_fetch_supply/oracle.h",
    "simulator/gsim/a1_fetch_supply/oracle_test.cpp",
    "simulator/gsim/run.py",
)
SCALA_ROOTS = ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def source_guard(root, manifest):
    files = manifest["files"]
    for path, digest in files.items():
        require((root / path).is_file() and sha(root / path) == digest,
                "frozen compiled input drift: " + path)
    actual = {str(path.relative_to(root)) for directory in SCALA_ROOTS
              for path in (root / directory).rglob("*.scala")}
    expected = {path for path in files if path.endswith(".scala")}
    require(actual == expected, "Scala files added or removed after compile freeze")


def host_guard(root, baseline):
    for path in HOST_INPUTS:
        require(path in baseline["sourceSha256"], "baseline omitted host input: " + path)
        require(sha(root / path) == baseline["sourceSha256"][path],
                "S1 must not change existing fixture/service/oracle: " + path)


def compare(baseline, candidate):
    expected_status = "PASS_BOUNDED_A1_FRONTEND_SUPPLY_ONLY"
    require(baseline.get("status") == candidate.get("status") == expected_status,
            "both independent functional receipts must pass")
    for key in ("configuration", "serviceLaw", "compiler", "gsimSha256"):
        require(baseline[key] == candidate[key], "unmatched frontend stage " + key)
    require(set(baseline["scenarios"]) == set(candidate["scenarios"]), "scenario set changed")
    rows = []
    for name, before in baseline["scenarios"].items():
        after = candidate["scenarios"][name]
        differences = {key: {"before": before.get(key), "after": after.get(key)}
                       for key in sorted(set(before) | set(after))
                       if key not in before or key not in after or before[key] != after[key]}
        rows.append({"scenario": name, "identical": not differences,
                     "before_work_cycles": before["work_cycles"],
                     "after_work_cycles": after["work_cycles"],
                     "before_verified": before["verified"], "after_verified": after["verified"],
                     "differences": differences})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-freeze", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--compile-receipt", type=Path, required=True)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)), "fresh filesystem-safe tag required")
    freeze = json.loads(args.baseline_freeze.read_text())
    baseline_path = Path(freeze["baseline_receipt"])
    baseline = json.loads(baseline_path.read_text())
    manifest = json.loads(args.source_manifest.read_text())
    compiled = json.loads(args.compile_receipt.read_text())
    require(compiled["exit"] == 0 and not compiled["source_drift"], "coordinated compile must pass")
    require(compiled["source_manifest_sha256"] == sha(args.source_manifest), "compile bound another freeze")
    require(sha(baseline_path) == freeze["baseline_receipt_sha256"], "baseline receipt drift")
    require(sha(args.gsim) == baseline["gsimSha256"], "GSIM tool changed")
    for path, digest in freeze["model_artifacts"].items():
        require(sha(Path(freeze["model_directory"]) / path) == digest, "baseline model artifact drift")
    source_guard(ROOT, manifest)
    host_guard(ROOT, baseline)
    model = BUILD / args.tag
    require(not model.exists(), "candidate must emit/generate/build in a new model directory")
    evidence = BUILD / (args.tag + "-comparison")
    evidence.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-B", str(ROOT / "simulator/gsim/a1_fetch_supply.py"),
               "--gsim", str(args.gsim.resolve()), "--tag", args.tag,
               "--compare", str(baseline_path.resolve())]
    report = {
        "schema": "a1-zero-cycle-frontend-stage-v1", "status": "RUNNING",
        "baseline_freeze_sha256": sha(args.baseline_freeze),
        "baseline_receipt_sha256": sha(baseline_path),
        "compile_receipt_sha256": sha(args.compile_receipt),
        "source_manifest_sha256": sha(args.source_manifest),
        "runner_sha256": sha(Path(__file__)), "command": command,
        "scope": "fresh real frontend module chain, reduced I-cache, bounded consumer; not CPU IPC",
        "metric_boundaries": "work/consume histograms are ROI-only; requests/latency/total TL include drain",
        "baseline_rerun": False, "candidate_fresh_model": True,
    }
    try:
        with (evidence / "fresh-model.log").open("x") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                    env=os.environ, timeout=1800)
        report["child_exit"] = result.returncode
        require(result.returncode == 0, "candidate frontend build or independent oracle failed")
        candidate_path = model / "receipt.json"
        candidate = json.loads(candidate_path.read_text())
        report["candidate_receipt_sha256"] = sha(candidate_path)
        report["cases"] = compare(baseline, candidate)
        source_guard(ROOT, manifest)
        host_guard(ROOT, baseline)
        report["status"] = ("PASS_S1_ALL_SCENARIO_FIELDS_IDENTICAL" if all(
            row["identical"] for row in report["cases"]) else "FAIL_S1_ZERO_CYCLE_EQUIVALENCE")
    except Exception as error:
        report.update(status="FAIL_PRESERVE_EVIDENCE", error=str(error))
        raise
    finally:
        report["model_artifacts"] = {str(path.relative_to(model)): sha(path)
                                     for path in sorted(model.rglob("*")) if path.is_file()}
        report["log_artifacts"] = {path.name: sha(path) for path in evidence.glob("*.log")}
        (evidence / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    require(report["status"] == "PASS_S1_ALL_SCENARIO_FIELDS_IDENTICAL", report["status"])
    print(report["status"], evidence)


if __name__ == "__main__":
    main()
