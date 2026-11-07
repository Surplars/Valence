#!/usr/bin/env python3
"""Focused real-platform guest IMSIC claim/threshold/isolation checks using GSIM."""
import argparse
import os
import subprocess

import run as common


def require_marker(path, marker):
    if marker not in path.read_text():
        raise RuntimeError(f"{marker} missing from {path}")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    output = common.test(
        gsim, cxx, "aia-guest-claims", "ooo.HypervisorPlatformGsimMain",
        "HypervisorPlatformGsim", "aia_guest_claims.cpp", defines={},
        cxx_flags=("-fbracket-depth=4096",), timeout=600,
    )
    require_marker(output / "test.log", "AIA_GUEST_CLAIMS_ALL_PASS cases=2")
    summaries = [line.split()[1] for line in (output / "test.log").read_text().splitlines()
                 if line.startswith("AIA_GUEST_CLAIMS_PASS ") and len(line.split()) > 1]
    if summaries != ["schedule=open", "schedule=stalled"]:
        raise RuntimeError("expected exactly the open and stalled schedule summaries")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    for mode, diagnostic in (
        ("wrong-claim", "FAIL independent guest claim result"),
        ("wrong-file", "FAIL independent guest file isolation"),
    ):
        path = output / (mode + ".log")
        with path.open("w") as log:
            result = subprocess.run(
                [str(output / "run"), "--" + mode], cwd=common.ROOT,
                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=600,
            )
        if result.returncode != 1:
            raise RuntimeError(f"{mode} returned {result.returncode}, expected 1")
        require_marker(path, diagnostic)
        text = path.read_text()
        if "AddressSanitizer" in text or "runtime error:" in text:
            raise RuntimeError(f"{mode} had a sanitizer failure")
    print("AIA_GUEST_CLAIMS_STANDARD_PASS")


if __name__ == "__main__":
    main()
