#!/usr/bin/env python3
"""Focused opt-in guest LR/SC and AMO checks on the real same-clock platform."""
import argparse
import os
import subprocess

import run as common


CASES = ("clean", "ecall", "vs_write_denied", "g_write_denied",
         "rom_lr_denied", "mmio_amo_denied", "misaligned")
SCHEDULES = ("1", "2")
NEGATIVE_DIAGNOSTIC = "FAIL independent atomic result"


def check_positive(path):
    text = path.read_text()
    if any(error in text for error in ("FAIL ", "AddressSanitizer", "runtime error:")):
        raise RuntimeError("positive execution contains a failure diagnostic")
    rows = [dict(field.split("=", 1) for field in line.split()[1:])
            for line in text.splitlines() if line.startswith("GUEST_ATOMICS_PASS ")]
    expected = {(case, schedule) for case in CASES for schedule in SCHEDULES}
    actual = [(row.get("case"), row.get("schedule")) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RuntimeError("expected exactly every guest atomic case and schedule")
    for row in rows:
        if any(int(row.get(key, "0")) <= 0 for key in ("cycles", "commits", "checks")):
            raise RuntimeError("guest atomic summaries require positive execution counts")
    marker = f"GUEST_ATOMICS_ALL_PASS cases={len(CASES)} runs={len(expected)}"
    if text.splitlines().count(marker) != 1:
        raise RuntimeError("expected exactly one complete guest atomic marker")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    output = common.test(
        gsim, cxx, "guest-atomics", "ooo.GuestAtomicsPlatformGsimMain",
        "GuestAtomicsPlatformGsim", "guest_atomics.cpp", defines={},
        cxx_flags=("-fbracket-depth=4096",), timeout=600,
    )
    check_positive(output / "test.log")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    path = output / "wrong-atomic.log"
    with path.open("w") as log:
        result = subprocess.run(
            [str(output / "run"), "--wrong-atomic"], cwd=common.ROOT,
            stdout=log, stderr=subprocess.STDOUT, env=env, timeout=600,
        )
    text = path.read_text()
    if result.returncode != 1:
        raise RuntimeError(f"wrong-atomic returned {result.returncode}, expected 1")
    if not text.rstrip().endswith(NEGATIVE_DIAGNOSTIC):
        raise RuntimeError("independent atomic diagnostic missing from end of negative log")
    if "AddressSanitizer" in text or "runtime error:" in text:
        raise RuntimeError("sanitizer failure is not an expected negative control")
    print("GUEST_ATOMICS_STANDARD_PASS")


if __name__ == "__main__":
    main()
