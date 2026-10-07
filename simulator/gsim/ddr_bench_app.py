#!/usr/bin/env python3
"""Direct-load exact DDR50/115200 benchmark smoke; no slow UART upload or PHY claim."""
import argparse
import re
import subprocess
import sys
from run import BUILD, ROOT, run, setup, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-ways", type=int, choices=(1, 2), default=2)
    parser.add_argument("--issue-width", type=int, choices=(2, 4), default=2)
    parser.add_argument("--no-instruction-prefetch", action="store_true")
    parser.add_argument("--timing-profile", choices=("early-issue", "registered-replay", "staged-fabric", "staged-control"), default="early-issue")
    parser.add_argument("--tag", default="20261001", help="separate focused optimization artifacts")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must contain only letters, digits, underscores or hyphens")
    name = f"ddr-bench-app-50000000-115200-ways{args.cache_ways}-{args.tag}"
    if args.issue_width != 2:
        name += f"-issue{args.issue_width}"
    if args.no_instruction_prefetch:
        name += "-noprefetch"
    if args.timing_profile != "early-issue":
        name += "-" + args.timing_profile
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "firmware"
    run([sys.executable, ROOT / "fpga/firmware/build_ddr_bench.py", "--out", firmware],
        log=output / "application-build.log")
    gsim, cxx = setup(False)
    test(gsim, cxx, name, "ooo.BoardSocGsimMain", "BoardSocGsim", "ddr_bench_app.cpp",
         parameters=("ddr", "50000000", args.timing_profile, "115200", str(args.cache_ways), str(args.issue_width),
                     "0" if args.no_instruction_prefetch else "1"),
         runtime_args=(firmware / "ddr_bench.bin",),
         defines={"UART_DIVISOR": 1, "BOARD_CPU_HZ": 50000000, "BOARD_UART_BAUD": 115200,
                  "UART_EXTRA_STOP_BITS": 0, "DDR_MODEL": 1},
         sanitizer=True, timeout=600)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM DDR benchmark: {error}", file=sys.stderr)
        sys.exit(1)
