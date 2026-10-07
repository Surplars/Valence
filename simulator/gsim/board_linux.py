#!/usr/bin/env python3
"""Focused exact-image Linux boot on DDR50 two-issue/2-way board configuration."""
import argparse
from pathlib import Path
import subprocess
import re
import sys
from run import ROOT, setup, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--max-cycles", type=int, default=500_000_000)
    parser.add_argument("--rootfs", choices=("minimal", "busybox"), default="busybox")
    args = parser.parse_args()
    if args.max_cycles < 1 or not args.image.is_file():
        parser.error("provide an existing image and a positive cycle limit")
    disassembly = subprocess.check_output(["riscv64-linux-gnu-objdump", "-d",
        "--disassemble=semihosting_enabled", args.image.with_suffix(".elf")], text=True)
    probe = re.search(r"^\s*([0-9a-f]+):.*\bebreak\b", disassembly, re.MULTILINE)
    if not probe:
        parser.error("missing exact OpenSBI semihosting probe symbol in companion ELF")
    gsim, cxx = setup(False)
    test(gsim, cxx, "board-linux-ddr50-" + args.rootfs, "ooo.BoardSocGsimMain", "BoardSocGsim", "board_linux.cpp",
         parameters=("ddr", "50000000", "early-issue", "115200", "2", "2", "1"),
         runtime_args=(args.image.resolve(), str(args.max_cycles)),
         defines={"DDR_MODEL": 1, "BOARD_CPU_HZ": 50000000, "BOARD_UART_BAUD": 115200,
                  "UART_DIVISOR": 1, "UART_EXTRA_STOP_BITS": 0,
                  "SEMHOST_PROBE_PC": "0x" + probe.group(1) + "ULL",
                  "ROOTFS_BUSYBOX": int(args.rootfs == "busybox")}, sanitizer=False, timeout=3600)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"GSIM board Linux: {error}", file=sys.stderr)
        sys.exit(1)
