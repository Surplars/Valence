#!/usr/bin/env python3
"""Short standalone resolution-mailbox qualification; not backend integration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess

import run as common

OWNED = (
    "src/main/scala/core/ooo/frontend/BranchResolutionMailbox.scala",
    "src/main/scala/core/ooo/config/OooParams.scala",
    "src/main/scala/core/ooo/interfaces/BackendTypes.scala",
    "src/test/scala/ooo/BranchResolutionMailboxGsim.scala",
    "src/test/scala/ooo/BranchResolutionMailboxSpec.scala",
    "simulator/gsim/harness/branch_resolution_mailbox.cpp",
    "simulator/gsim/branch_resolution_mailbox.py",
    "simulator/gsim/run.py",
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    return {name: sha(common.ROOT / name) for name in OWNED if (common.ROOT / name).is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must be a fresh filesystem-safe evidence label")
    before = inputs()
    if not args.build_run:
        print(json.dumps({"status": "PREFLIGHT_ONLY", "inputs": before,
            "backend_connected": False, "capacity": 1, "minimum_latency": 1, "II": 1}))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "inputs": before, "backend_connected": False,
        "scope": "standalone mailbox with executable physical-source lifecycle oracle",
        "capacity": 1, "minimum_latency": 1, "II": 1, "timing_and_cpu_performance": "UNVERIFIED"}
    try:
        gsim = common.SOURCE / "build/gsim/gsim"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.SOURCE, text=True).strip()
        if revision != common.LOCK["revision"] or not gsim.is_file():
            raise RuntimeError("prebuilt pinned GSIM required; this script does not install tools")
        cxx, compiler = common.compiler()
        report.update(compiler=compiler, gsim_revision=revision, gsim_sha256=sha(gsim))
        model = common.test(gsim, cxx, args.tag + "/model", "ooo.BranchResolutionMailboxGsimMain",
            "BranchResolutionMailboxGsim", "branch_resolution_mailbox.cpp", defines={})
        normal = (model / "test.log").read_text()
        if "BRANCH_RESOLUTION_MAILBOX_PASS" not in normal:
            raise RuntimeError("standalone positive oracle marker absent")
        report["positive"] = normal
        report["negative"] = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        for flag, marker, rejection in (
            ("--inject-mismatch", "BRANCH_RESOLUTION_NEGATIVE_REACHED", "independent capture oracle mismatch"),
            ("--duplicate-source", "BRANCH_RESOLUTION_DUPLICATE_REACHED", "resolution sources must own distinct full tokens"),
        ):
            result = subprocess.run([str(model / "run"), flag], capture_output=True, text=True,
                timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            log = result.stdout + result.stderr
            path = out / (flag[2:] + ".log")
            path.write_text(log)
            if result.returncode == 0 or marker not in log or rejection not in log or \
                    "AddressSanitizer" in log or "runtime error:" in log:
                raise RuntimeError("negative did not reach its exact independent/ownership rejection: " + flag)
            report["negative"][flag] = {"status": "REJECTED", "returncode": result.returncode,
                "marker": marker, "rejection": rejection, "log_sha256": sha(path)}
        report["status"] = "PASS_STANDALONE_MAILBOX"
    except Exception as error:
        report.update(status="FAIL", failure=str(error))
        raise
    finally:
        report["inputs_unchanged"] = inputs() == before
        if not report["inputs_unchanged"]:
            report["status"] = "FAIL_INPUT_DRIFT"
        report["artifacts"] = {str(path.relative_to(out)): sha(path) for path in sorted(out.rglob("*"))
            if path.is_file() and path.name != "receipt.json"}
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_STANDALONE_MAILBOX":
        raise RuntimeError(report["status"])
    print(json.dumps({"status": report["status"], "evidence": str(out), "backend_connected": False}))


if __name__ == "__main__":
    main()
