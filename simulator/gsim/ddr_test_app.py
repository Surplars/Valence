#!/usr/bin/env python3
"""Focused test of the exact downloadable DDR tester: auto-smoke + return to ROM."""
import argparse
import subprocess
import sys
from run import BUILD, ROOT, run, setup, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timing-profile", choices=("baseline", "early-issue", "queued-memory", "registered-response"),
                        help="Override the board hardware timing profile; otherwise use BoardSocConfig.")
    args = parser.parse_args()
    name = "ddr-test-app" + (f"-{args.timing_profile}" if args.timing_profile else "")
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "firmware"
    run([sys.executable, ROOT / "fpga/firmware/build.py", "--out", firmware,
         "--cpu-hz", "50000000", "--ddr"], log=output / "firmware-build.log")
    run([sys.executable, ROOT / "fpga/firmware/build_ddr_test.py", "--out", firmware],
        log=output / "application-build.log")
    gsim, cxx = setup(False)
    test(gsim, cxx, name, "ooo.BoardSocGsimMain", "BoardSocGsim", "ddr_test_app.cpp",
         parameters=("ddr", "50000000") + ((args.timing_profile,) if args.timing_profile else ()),
         runtime_args=(firmware / "bootrom.bin", firmware / "ddr_test.bin"),
         defines={"UART_DIVISOR": 1, "BOARD_CPU_HZ": 50000000, "DDR_MODEL": 1},
         sanitizer=True, timeout=300)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM DDR test application: {error}", file=sys.stderr)
        sys.exit(1)
