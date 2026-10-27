#!/usr/bin/env python3
"""One tiny GSIM model: disposable numerical store row, not backend performance evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import subprocess

import run as common
import m2_r1_compile_gate as compile_gate

INPUTS = (
    "src/main/scala/core/ooo/lsu/PreparedHeadStoreOperands.scala",
    "src/main/scala/core/ooo/config/OooParams.scala",
    "src/main/scala/core/ooo/interfaces/BackendTypes.scala",
    "src/test/scala/ooo/PreparedHeadStoreOperandsGsim.scala",
    "simulator/gsim/harness/prepared_head_store_operands.cpp",
    "simulator/gsim/prepared_head_store_operands.py",
    "simulator/gsim/run.py",
    "simulator/gsim/m2_r1_compile_gate.py",
    "simulator/gsim/config/toolchain.json",
)
REJECTIONS = {
    "empty": "prepared head store consume requires registered valid",
    "dead": "prepared head store consume requires live owner",
    "prehead": "prepared head store consume requires current head",
    "index": "prepared head store consume requires exact full token",
    "tag": "prepared head store consume requires exact full token",
    "high-tag": "prepared head store consume requires exact full token",
    "flush": "prepared head store consume forbidden during flush",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs():
    return {name: sha(common.ROOT / name) for name in INPUTS}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--build-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must be a fresh filesystem-safe evidence label")
    before = inputs()
    report = {
        "status": "PREFLIGHT_ONLY", "inputs": before, "backend_connected": False,
        "scope": "standalone registered numerical preparation row with independent finite host scoreboard",
        "capacity": 1, "minimum_latency": 1, "prehead_refresh_II": 1,
        "same_edge_head_consume_recapture": False, "token_shapes": [[16, 64], [8, 9]],
        "raw_registered_output": True, "timing_and_cpu_performance": "UNVERIFIED",
    }
    if not args.build_run:
        print(json.dumps(report))
        return
    out = common.BUILD / args.tag
    out.mkdir(parents=True, exist_ok=False)
    report["status"] = "RUNNING"
    try:
        gsim = common.SOURCE / "build/gsim/gsim"
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.SOURCE, text=True).strip()
        changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=common.SOURCE, text=True)
        if revision != common.LOCK["revision"] or changes or not gsim.is_file():
            raise RuntimeError("clean prebuilt pinned GSIM required; this script does not install tools")
        cxx, compiler = common.compiler()
        report.update(compiler=compiler, gsim_revision=revision, gsim_sha256=sha(gsim))
        compile_gate.install()
        model = common.test(gsim, cxx, args.tag + "/model", "ooo.PreparedHeadStoreOperandsGsimMain",
            "PreparedHeadStoreOperandsGsim", "prepared_head_store_operands.cpp", defines={})
        normal = (model / "test.log").read_text()
        if "PREPARED_HEAD_STORE_OPERANDS_PASS" not in normal:
            raise RuntimeError("positive independent oracle marker absent")
        report["positive"] = normal
        report["negative"] = {}
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        cases = [("--illegal-" + name, "PREPARED_HEAD_STORE_NEGATIVE_REACHED case=" + name,
            "Assertion failed: " + rejection, True) for name, rejection in REJECTIONS.items()]
        cases.append(("--inject-observation", "PREPARED_HEAD_STORE_OBSERVATION_REACHED",
            "independent raw payload mismatch standard", False))
        for flag, reached, rejection, hardware in cases:
            result = subprocess.run([str(model / "run"), flag], capture_output=True, text=True,
                timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            log = result.stdout + result.stderr
            path = out / (flag[2:] + ".log")
            path.write_text(log)
            if result.returncode == 0 or reached not in log or rejection not in log or \
                    "AddressSanitizer" in log or "runtime error:" in log:
                raise RuntimeError("negative missed its exact reached rejection: " + flag)
            report["negative"][flag] = {"status": "REJECTED", "returncode": result.returncode,
                "hardware_assertion": hardware, "marker": reached, "rejection": rejection,
                "log_sha256": sha(path)}
        report["status"] = "PASS_STANDALONE_PREPARED_HEAD_STORE"
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
    if report["status"] != "PASS_STANDALONE_PREPARED_HEAD_STORE":
        raise RuntimeError(report["status"])
    print(json.dumps({"status": report["status"], "evidence": str(out), "backend_connected": False}))


if __name__ == "__main__":
    main()
