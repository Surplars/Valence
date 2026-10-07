#!/usr/bin/env python3
"""Same-binary compact board-width CoreMark regression; one iteration, NOT a score."""
import argparse
import re
import subprocess
import sys
from run import BUILD, ROOT, run, setup, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issue-width", type=int, choices=(2, 4), nargs="+", default=[2, 4])
    parser.add_argument("--tag", default="20261001", help="separate A/B artifact names")
    parser.add_argument("--no-instruction-prefetch", action="store_true")
    parser.add_argument("--timing-profile", choices=("early-issue", "registered-replay", "staged-fabric", "staged-control"), default="early-issue")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must contain only letters, digits, underscores or hyphens")
    firmware = BUILD / f"board-coremark-width-{args.tag}" / "firmware"
    firmware.parent.mkdir(parents=True, exist_ok=True)
    run([sys.executable, ROOT / "fpga/firmware/build_coremark.py", "--out", firmware,
         "--iterations", "1", "--clock-hz", "50000000", "--memory", "ddr"],
        log=firmware.parent / "application-build.log")
    gsim, cxx = setup(False)
    for width in args.issue_width:
        suffix = "-noprefetch" if args.no_instruction_prefetch else ""
        if args.timing_profile != "early-issue":
            suffix += "-" + args.timing_profile
        test(gsim, cxx, f"board-coremark-compact{width}-{args.tag}{suffix}",
             "ooo.BoardSocGsimMain", "BoardSocGsim", "board_coremark.cpp",
             parameters=("ddr", "50000000", args.timing_profile, "115200", "2", str(width),
                         "0" if args.no_instruction_prefetch else "1"),
             runtime_args=(firmware / "coremark_board.bin",),
             defines={"UART_DIVISOR": 1, "BOARD_CPU_HZ": 50000000,
                      "BOARD_UART_BAUD": 115200, "UART_EXTRA_STOP_BITS": 0, "DDR_MODEL": 1},
             sanitizer=True, timeout=600)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM board CoreMark: {error}", file=sys.stderr)
        sys.exit(1)
