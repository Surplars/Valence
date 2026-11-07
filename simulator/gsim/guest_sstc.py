#!/usr/bin/env python3
"""Focused guest Sstc CSR/pending and actual-core timer checks using GSIM."""
import argparse
import os
import subprocess

import run as common


def summary_lines(path, prefix):
    text = path.read_text()
    if any(diagnostic in text for diagnostic in ("FAIL ", "AddressSanitizer", "runtime error:")):
        raise RuntimeError(f"failure diagnostic in {path}")
    return [line for line in text.splitlines() if line.startswith(prefix)]


def negative(output, mode, diagnostic):
    path = output / (mode + ".log")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    with path.open("w") as log:
        result = subprocess.run(
            [str(output / "run"), "--" + mode], cwd=common.ROOT,
            stdout=log, stderr=subprocess.STDOUT, env=env, timeout=600,
        )
    text = path.read_text()
    if result.returncode != 1:
        raise RuntimeError(f"{mode} returned {result.returncode}, expected 1")
    if not text.rstrip().endswith(diagnostic):
        raise RuntimeError(f"{diagnostic} missing from end of {path}")
    if "AddressSanitizer" in text or "runtime error:" in text:
        raise RuntimeError(f"{mode} had a sanitizer failure")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    msu = common.test(
        gsim, cxx, "guest-sstc/msu", "ooo.HypervisorSystemGsimMain",
        "HypervisorSystemGsim", "guest_sstc.cpp", defines={},
        cxx_flags=("-fbracket-depth=4096",), timeout=600,
    )
    summaries = summary_lines(msu / "test.log", "GUEST_SSTC_MSU_PASS ")
    if len(summaries) != 1:
        raise RuntimeError("expected exactly one MSU summary")
    counts = dict(field.split("=", 1) for field in summaries[0].split()[1:])
    if any(int(counts.get(key, "0")) <= 0 for key in ("cases", "commands", "checks")):
        raise RuntimeError("MSU summary requires positive cases, commands and checks")
    negative(msu, "wrong-compare", "FAIL independent guest compare signature")

    core = common.test(
        gsim, cxx, "guest-sstc/core", "ooo.GuestSstcCoreGsimMain",
        "GuestSstcCoreGsim", "guest_sstc_core.cpp", defines={},
        cxx_flags=("-fbracket-depth=4096",), timeout=600,
    )
    summaries = summary_lines(core / "test.log", "GUEST_SSTC_CORE_PASS ")
    if [line.split()[1] for line in summaries] != ["schedule=open", "schedule=stalled"]:
        raise RuntimeError("expected exactly the open and stalled core summaries")
    if (core / "test.log").read_text().splitlines().count("GUEST_SSTC_CORE_ALL_PASS cases=2") != 1:
        raise RuntimeError("expected one complete core marker")
    negative(core, "wrong-timer", "FAIL independent guest timer signature")
    print("GUEST_SSTC_STANDARD_PASS")


if __name__ == "__main__":
    main()
