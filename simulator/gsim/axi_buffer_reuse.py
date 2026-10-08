#!/usr/bin/env python3
"""Focused AXI slot-payload proof and exact baseline/candidate bus replay.

First run on the preserved pre-change source with --expect-layout split, then
run on the candidate with --baseline <baseline-output-directory>. This script
never swaps RTL, downloads tools, runs a broad regression, or invokes synthesis.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common

CASES = ((1, 0, False), (4, 0, True), (4, 2, False), (4, 2, True))
HARNESS = common.HERE / "harness/tilelink_axi4_buffer_reuse.cpp"
HARNESS_DEPENDENCIES = (HARNESS, common.HERE / "harness/tilelink_axi4_mixed_channels.cpp", Path(__file__))
TOP = "TileLinkAxi4Bridge"
ALLOWED_RTL_DIFFERENCES = {
    "src/main/scala/core/ooo/TileLinkAxi4BurstBridge.scala",
    "src/main/scala/core/ooo/TileLinkAxi4OutstandingBridge.scala",
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes():
    paths = sorted((common.ROOT / "src").rglob("*.scala")) + list(HARNESS_DEPENDENCIES)
    return {str(path.relative_to(common.ROOT)): sha256(path.read_bytes()) for path in paths}


def receipt_path(path):
    return path / "receipt.json" if path.is_dir() else path


def trace_summary(path):
    lines = path.read_bytes().splitlines(keepends=True)
    inputs = b"".join(line for line in lines if line.startswith(b"I "))
    outputs = b"".join(line for line in lines if line.startswith(b"O "))
    if not inputs or len(lines) != 2 * len(inputs.splitlines()):
        raise AssertionError(f"incomplete input/output trace: {path}")
    return {"sha256": sha256(b"".join(lines)), "inputs_sha256": sha256(inputs),
            "outputs_sha256": sha256(outputs), "cycles": len(lines) // 2}


def inspect_layout(path, expected):
    fir = path.read_text()
    modules = re.split(r"(?m)^\s*(?:(?:public|private)\s+)?module\s+", fir)
    lane = [part for part in modules[1:] if re.match(r"TileLinkAxi4BurstBridge(?:_\d+)?\s*:", part)]
    if not lane:
        raise AssertionError("FIR does not contain the burst-lane module")
    structures = []
    for module in lane:
        shared = len(re.findall(r"\bcmem\s+payload\s*:", module))
        read_ports = len(re.findall(r"\bread\s+mport\s+\S+\s*=\s*payload\[", module))
        write_ports = len(re.findall(r"\bwrite\s+mport\s+\S+\s*=\s*payload\[", module))
        old_arrays = re.findall(r"\breg(?:reset)?\s+(readData|writeData)\s*:", module)
        info = {"shared_payload_memories": shared, "payload_read_ports": read_ports,
                "payload_write_ports": write_ports, "old_payload_arrays": sorted(old_arrays)}
        if expected == "shared":
            assert shared == 1 and read_ports == 1 and write_ports == 1 and not old_arrays, info
        else:
            assert shared == 0 and sorted(old_arrays) == ["readData", "writeData"], info
        structures.append(info)
    return {"expected": expected, "lanes": structures,
            "scope": "CHIRRTL structure only; physical RAM inference/resources/timing unverified"}


def compare_reports(baseline_path, candidate_path):
    old_path, new_path = receipt_path(baseline_path), receipt_path(candidate_path)
    old, new = json.loads(old_path.read_text()), json.loads(new_path.read_text())
    assert old["status"] == new["status"] == "PASS", "comparison requires two completed passing runs"
    assert old["cases"].keys() == new["cases"].keys(), "case matrix changed"
    changed = {key for key in old["source_sha256"].keys() | new["source_sha256"].keys()
               if old["source_sha256"].get(key) != new["source_sha256"].get(key)}
    assert changed <= ALLOWED_RTL_DIFFERENCES, f"uncontrolled source or oracle drift: {sorted(changed)}"
    comparisons = {}
    for name, case in new["cases"].items():
        prior = old["cases"][name]
        assert prior["parameters"] == case["parameters"], f"parameter drift: {name}"
        a, b = old_path.parent / name / "trace.txt", new_path.parent / name / "trace.txt"
        summary_a, summary_b = trace_summary(a), trace_summary(b)
        assert summary_a == prior["trace"] and summary_b == case["trace"], "saved trace changed"
        if a.read_bytes() != b.read_bytes():
            lines_a, lines_b = a.read_bytes().splitlines(), b.read_bytes().splitlines()
            index = next((i for i, (x, y) in enumerate(zip(lines_a, lines_b)) if x != y),
                         min(len(lines_a), len(lines_b)))
            raise AssertionError(f"same-input cycle replay mismatch in {name}, trace line {index + 1}")
        comparisons[name] = {"status": "PASS", "exact_cycle_replay": True, **summary_b}
    return {"status": "PASS", "baseline": str(old_path.resolve()),
            "candidate": str(new_path.resolve()), "changed_sources": sorted(changed), "cases": comparisons}


def reuse_toolchain():
    """Validate the already-built pinned checkout without rebuilding/installing."""
    source = common.SOURCE
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    assert revision == common.LOCK["revision"], "GSIM revision mismatch"
    dirty = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True)
    assert not dirty, "GSIM checkout has tracked modifications"
    gsim = source / "build/gsim/gsim"
    assert gsim.is_file(), "pinned GSIM executable is missing"
    cxx, _ = common.compiler()
    return gsim, cxx


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag")
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--expect-layout", choices=("split", "shared"), default="shared")
    ap.add_argument("--reuse-toolchain", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BASELINE", "CANDIDATE"))
    args = ap.parse_args()
    if args.compare:
        print(json.dumps(compare_reports(*args.compare), indent=2))
        return
    matrix = [{"name": f"s{slots}-b8-w{writes}-u{int(unordered)}",
               "parameters": [slots, 8, 3, writes, int(unordered)]}
              for slots, writes, unordered in CASES]
    if args.dry_run:
        print(json.dumps({"cases": matrix, "layout": args.expect_layout,
                          "negative_controls": ["--inject-read", "--inject-write"],
                          "baseline": str(args.baseline) if args.baseline else None}, indent=2))
        return
    if not args.tag or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", args.tag):
        ap.error("--tag must be a nonempty filename-safe label")
    out = common.BUILD / ("axi-buffer-reuse-" + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "source_sha256": source_hashes(), "cases": {},
              "scope": "focused GSIM lane-payload and AW/W ownership only; no CPU/physical-performance claim"}
    try:
        gsim, cxx = reuse_toolchain() if args.reuse_toolchain else common.setup(False)
        for case, (slots, writes, unordered) in zip(matrix, CASES):
            name = case["name"]
            defines = {"AXI_SLOTS": slots, "MAX_BURST_BEATS": 8, "WRITE_CREDITS": writes}
            if unordered:
                defines["UNORDERED_TL"] = 1
            trace = out / name / "trace.txt"
            target = common.test(gsim, cxx, str(out.relative_to(common.BUILD) / name),
                                 "ooo.TileLinkAxi4OutstandingGsimMain", TOP, HARNESS.name,
                                 parameters=case["parameters"], defines=defines,
                                 runtime_args=("--trace", trace), timeout=180)
            log = (target / "test.log").read_text()
            assert "BUFFER_REUSE_ALL_PASS" in log, "success marker missing"
            if writes:
                assert "REUSE_DENIED_LIVE_PAYLOAD_PASS" in log and "QUEUED_WRITE_PASS" in log
            entry = {**case, "status": "PASS", "log": log, "trace": trace_summary(trace),
                     "layout": inspect_layout(target / (TOP + ".fir"), args.expect_layout), "negative": {}}
            for flag, anchor in (("--inject-read", "independent reuse read-data oracle mismatch"),
                                 ("--inject-write", "W independent payload/strobe/last mismatch")):
                result = subprocess.run([target / "run", flag], capture_output=True, text=True,
                                        timeout=180, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                output = result.stdout + result.stderr
                (target / (flag[2:] + ".log")).write_text(output)
                assert result.returncode != 0 and anchor in output, (name, flag, output[-1500:])
                entry["negative"][flag] = "PASS"
            report["cases"][name] = entry
            assert source_hashes() == report["source_sha256"], "source drift during test run"
            (out / "progress.json").write_text(json.dumps(report, indent=2) + "\n")
        report["status"] = "PASS"
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
        if args.baseline:
            comparison = compare_reports(args.baseline, out)
            (out / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
            report["comparison"] = comparison
    except BaseException as error:
        report["status"] = "FAIL"
        report["error"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
