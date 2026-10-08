#!/usr/bin/env python3
"""Short host-only media policy/statistics oracles; no kernel, board or image build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    output = args.output.resolve()
    if output.exists():
        parser.error("use a fresh result directory")
    cc = shutil.which(args.cc)
    if not cc:
        parser.error("existing C compiler required")
    inputs = [here / name for name in ("valence_gmac.c", "valence_media_policy.h",
              "test_media_stats.c", "test_managed_media_policy.c", "test_media_stats.py")]
    before = {p.name: sha(p) for p in inputs}
    output.mkdir(parents=True)
    report = {"status": "running", "source_sha256": before, "compiler": cc,
              "scope": "host-only policy/CSR-map/coherent-32bit-sampling oracle",
              "kernel_module_compile": False, "on_board_verified": False, "checks": {}}
    environment = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        for stem, marker in (("managed_media_policy", "MANAGED_MEDIA_POLICY_PASS"),
                             ("media_stats", "MEDIA_STATS_PASS")):
            binary = output / stem
            command = [cc, "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                       str(here / ("test_" + stem + ".c")), "-o", str(binary)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=60)
            (output / (stem + "-compile.log")).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(stem + " compile failed")
            result = subprocess.run([str(binary)], capture_output=True, text=True,
                                    env=environment, timeout=60)
            text = result.stdout + result.stderr
            (output / (stem + ".log")).write_text(text)
            if result.returncode or marker not in text:
                raise RuntimeError(stem + " positive failed")
            report["checks"][stem] = {"command": command, "executable_sha256": sha(binary),
                                      "summary": text.strip()}
        result = subprocess.run([str(output / "media_stats"), "--inject-mismatch"],
                                capture_output=True, text=True, env=environment, timeout=60)
        text = result.stdout + result.stderr
        (output / "media_stats-negative.log").write_text(text)
        if result.returncode != 1 or "independent counter value mismatch" not in text:
            raise RuntimeError("negative oracle failed to reject")
        report["checks"]["media_stats"]["negative_oracle"] = "rejected"
        report["status"] = "passed_host_only"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if before != {p.name: sha(p) for p in inputs}:
            report.update(status="failed", failure="source/test input drift")
        report["logs_sha256"] = {p.name: sha(p) for p in sorted(output.glob("*.log"))}
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] == "failed":
        raise RuntimeError(report["failure"])
    print(report["status"] + " receipt=" + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
