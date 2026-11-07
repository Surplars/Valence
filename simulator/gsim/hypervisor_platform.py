#!/usr/bin/env python3
"""Focused single-clock H/AIA platform and VS-origin PMA checks using pinned GSIM."""
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
        gsim, cxx, "hypervisor-platform", "ooo.HypervisorPlatformGsimMain",
        "HypervisorPlatformGsim", "hypervisor_platform.cpp", defines={},
        cxx_flags=("-fbracket-depth=4096",), timeout=600,
    )
    require_marker(output / "test.log", "HYPERVISOR_PLATFORM_PASS")
    # Reuse the emitted model, without another Mill elaboration or GSIM generation.
    # common.test builds a linked executable, not reusable object files, so the
    # second independent driver recompiles the same model translation units.
    common.run([
        cxx, "-std=c++20", "-O1", "-g", "-fbracket-depth=4096",
        "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
        "-I" + str(output), *sorted(output.glob("HypervisorPlatformGsim[0-9]*.cpp")),
        common.HERE / "harness/platform_pma_exceptions.cpp", "-ldl", "-o", output / "pma",
    ], log=output / "pma-compile.log")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    common.run([output / "pma"], env=env, log=output / "pma.log", timeout=600)
    require_marker(output / "pma.log", "PLATFORM_VS_PMA_EXCEPTIONS_PASS")
    # Exit 1 alone is insufficient: require the independent value oracle's reason.
    with (output / "negative.log").open("w") as log:
        result = subprocess.run([str(output / "run"), "--wrong-memory"], cwd=common.ROOT,
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=600)
    if result.returncode != 1:
        raise RuntimeError(f"wrong-memory control returned {result.returncode}, expected 1")
    require_marker(output / "negative.log", "independent platform store value")
    print((output / "pma.log").read_text(), end="")
    print("HYPERVISOR_PLATFORM_STANDARD_PASS")


if __name__ == "__main__":
    main()
