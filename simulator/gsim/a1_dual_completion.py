#!/usr/bin/env python3
"""Bounded dual-owner selector and real-A1 backend qualification, not a full regression.

Use the already prepared pinned toolchain. No CAD, Verilator, Linux, installation,
clock/Fmax claim, or replacement of the independent architectural oracle.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources(phase):
    files = sorted((common.ROOT / "src/main/scala").rglob("*.scala"))
    files += [common.ROOT / item for item in (
        "src/test/scala/ooo/DualCompletionSelectorGsim.scala",
        "src/test/scala/ooo/A1DualBackendGsim.scala",
        "simulator/gsim/harness/dual_completion_selector.cpp",
        "simulator/gsim/harness/a1_dual_backend.cpp",
        "simulator/gsim/a1_dual_completion.py")]
    if phase == "selector":
        files = [path for path in files if path.name not in ("a1_dual_backend.cpp", "A1DualBackendGsim.scala")]
    return {str(path.relative_to(common.ROOT)): sha(path) for path in files if path.is_file()}


def negative(binary, marker, out):
    result = subprocess.run([str(binary), "--inject-mismatch"], capture_output=True, text=True,
        timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    text = result.stdout + result.stderr
    out.write_text(text)
    if result.returncode == 0 or marker not in text or "AddressSanitizer" in text or "runtime error:" in text:
        raise RuntimeError("independent negative control did not reach its intended oracle")
    return {"status": "REJECTED", "returncode": result.returncode, "marker": marker, "log_sha256": sha(out)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--phase", choices=("selector", "backend"), default="selector")
    ap.add_argument("--build-run", action="store_true")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("tag must be a fresh filesystem-safe evidence label")
    before = sources(args.phase)
    if not args.build_run:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "phase": args.phase, "inputs": len(before),
            "issue_writeback_commit_widths": [2, 2, 2], "timing_and_board": "UNVERIFIED"}))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "phase": args.phase, "inputs": before, "cases": {}, "negative": {},
        "scope": "metadata selector" if args.phase == "selector" else
            "decoded real A1 backend in M-mode/Bare; no frontend/cache/TLB service qualification",
        "timing_and_board": "UNVERIFIED", "new_result_stage": False,
        "writeback_ports": 2, "dispatch_tickets": 2}
    try:
        gsim = common.SOURCE / "build/gsim/gsim"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.SOURCE, text=True).strip()
        if revision != common.LOCK["revision"] or not gsim.is_file():
            raise RuntimeError("prebuilt pinned GSIM is required; this runner never installs tools")
        cxx, version = common.compiler()
        report["compiler"] = version
        report["gsim"] = {"revision": revision, "sha256": sha(gsim)}
        if args.phase == "selector":
            model = common.test(gsim, cxx, args.tag + "/selector", "ooo.DualCompletionSelectorGsimMain",
                "DualCompletionSelectorGsim", "dual_completion_selector.cpp", defines={})
            report["cases"]["selector"] = (model / "test.log").read_text()
            report["negative"]["selector"] = negative(model / "run",
                "dual completion independent owner oracle mismatch", out / "selector-negative.log")
        else:
            rows = {}
            for topology in ("legacy", "dual-owner"):
                model = common.test(gsim, cxx, args.tag + "/" + topology,
                    "soc.core.ooo.A1DualBackendGsimMain", "A1DualBackendGsim", "a1_dual_backend.cpp",
                    parameters=(topology,), defines={"A1_DUAL_OWNER": int(topology == "dual-owner")}, timeout=180)
                text = (model / "test.log").read_text()
                if "A1_DUAL_BACKEND_PASS" not in text:
                    raise RuntimeError("backend independent acceptance marker absent")
                parsed = [json.loads(line[len("A1_BACKEND_METRIC "):]) for line in text.splitlines()
                    if line.startswith("A1_BACKEND_METRIC ")]
                if not parsed or len({row["name"] for row in parsed}) != len(parsed):
                    raise RuntimeError("backend cycle measurements missing or duplicated")
                rows[topology] = {row["name"]: row for row in parsed}
                report["cases"][topology] = parsed
                report.setdefault("effective_parameters", {})[topology] = json.loads(
                    (model / "effective-parameters.json").read_text())
                report["negative"][topology] = negative(model / "run", "A1_NEGATIVE_REACHED",
                    out / (topology + "-negative.log"))
            if rows["legacy"].keys() != rows["dual-owner"].keys():
                raise RuntimeError("backend pair executed different programs")
            report["comparison"] = []
            for name, old in rows["legacy"].items():
                new = rows["dual-owner"][name]
                if old["retired"] != new["retired"]:
                    raise RuntimeError("backend pair retired different instruction streams")
                report["comparison"].append({"name": name, "baseline_cycles": old["cycles"],
                    "candidate_cycles": new["cycles"], "retired": new["retired"],
                    "same_clock_speedup": old["cycles"] / new["cycles"]})
        report["status"] = "PASS_" + args.phase.upper()
    except Exception as error:
        report.update(status="FAIL", failure=str(error))
        raise
    finally:
        after = sources(args.phase)
        report["inputs_unchanged"] = before == after
        if before != after:
            report["status"] = "FAIL_INPUT_DRIFT"
        report["artifacts"] = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob("*"))
            if path.is_file() and path.name != "receipt.json"}
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if not report["status"].startswith("PASS_"):
        raise RuntimeError(report["status"])
    print(json.dumps({"status": report["status"], "evidence": str(out),
        "comparison": report.get("comparison", [])}, indent=2))


if __name__ == "__main__":
    main()
