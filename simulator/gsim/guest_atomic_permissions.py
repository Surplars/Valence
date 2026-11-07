#!/usr/bin/env python3
"""VS-origin final-SPA PMP denial and instruction execution with A disabled, using GSIM."""
import argparse
import os
import subprocess

import run as common


CASES = ("lr_w", "lr_d", "sc_w", "sc_d", "amo_w", "amo_d")
SCHEDULES = ("1", "2")
PROFILES = (("pmp", "GuestAtomicPmpGsim", {}),
            ("a_off", "GuestAtomicDisabledGsim", {"GUEST_ATOMIC_DISABLED": 1}))
NEGATIVE_DIAGNOSTIC = "FAIL independent atomic permission cause"


def check_positive(path, profile):
    text = path.read_text()
    if any(error in text for error in ("FAIL ", "AddressSanitizer", "runtime error:")):
        raise RuntimeError("positive execution contains a failure diagnostic")
    rows = [dict(field.split("=", 1) for field in line.split()[1:])
            for line in text.splitlines() if line.startswith("GUEST_ATOMIC_PERMISSIONS_PASS ")]
    expected = {(profile, case, schedule) for case in CASES for schedule in SCHEDULES}
    actual = [(row.get("profile"), row.get("case"), row.get("schedule")) for row in rows]
    if len(actual) != len(expected) or set(actual) != expected:
        raise RuntimeError("expected exactly every profile case and schedule")
    for row in rows:
        if any(int(row.get(key, "0")) <= 0 for key in ("cycles", "commits", "checks", "readbacks", "ptes", "parcels")):
            raise RuntimeError("permission summaries require positive execution counts")
        if row.get("traps") != "1" or row.get("atomicRequests") != "0":
            raise RuntimeError("expected one trap and zero physical atomic requests")
        readbacks = 3 if profile == "pmp" and row["case"].startswith("lr_") else 5
        if (row.get("forbiddenOffers") != "0" or row.get("clears") != "1"
                or row.get("readbacks") != str(readbacks)):
            raise RuntimeError("permission proof requires exact clear, readback and forbidden-offer counts")
        for key in ("dataTranslationsBeforeTrap", "dataPteOffersBeforeTrap"):
            value = int(row.get(key, "-1"))
            if (profile == "a_off" and value != 0) or (profile == "pmp" and value <= 0):
                raise RuntimeError("permission proof has invalid pretrap data-translation observations")
    marker = f"GUEST_ATOMIC_PERMISSIONS_ALL_PASS profile={profile} cases=6 runs=12"
    if text.splitlines().count(marker) != 1:
        raise RuntimeError("expected exactly one complete profile marker")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    for profile, model, defines in PROFILES:
        output = common.test(
            gsim, cxx, "guest-atomic-permissions/" + profile, "ooo." + model + "Main",
            model, "guest_atomic_permissions.cpp", defines=defines,
            cxx_flags=("-fbracket-depth=4096",), timeout=600,
        )
        check_positive(output / "test.log", profile)
        path = output / "wrong-cause.log"
        with path.open("w") as log:
            result = subprocess.run(
                [str(output / "run"), "--wrong-cause"], cwd=common.ROOT,
                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=600,
            )
        text = path.read_text()
        if result.returncode != 1:
            raise RuntimeError(f"{profile} wrong-cause returned {result.returncode}, expected 1")
        if not text.rstrip().endswith(NEGATIVE_DIAGNOSTIC):
            raise RuntimeError("independent cause diagnostic missing from end of negative log")
        if "AddressSanitizer" in text or "runtime error:" in text:
            raise RuntimeError("sanitizer failure is not an expected negative control")
    print("GUEST_ATOMIC_PERMISSIONS_STANDARD_PASS")


if __name__ == "__main__":
    main()
