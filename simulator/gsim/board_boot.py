#!/usr/bin/env python3
"""Focused serial-pin boot/download regression for the 128 KiB / 1 MiB board profile.

Uses the board's divisor-1 1.5 Mbaud firmware. This verifies
protocol/CPU/memory behavior, not the FPGA BMG/XPM implementation or 40 MHz timing.
"""
import subprocess
import sys

from run import BUILD, ROOT, run, setup, test


def main():
    output = BUILD / "board-boot"
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "firmware"
    run([sys.executable, ROOT / "fpga/firmware/build.py",
         "--out", firmware, "--uart-divisor", "1"],
        log=output / "firmware-build.log")
    gsim, cxx = setup(False)
    test(gsim, cxx, "board-boot", "ooo.BoardSocGsimMain", "BoardSocGsim", "board_boot.cpp",
         runtime_args=(firmware / "bootrom.bin", firmware / "sample_app.bin"),
         defines={"UART_DIVISOR": 1}, sanitizer=True, timeout=300)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM board boot: {error}", file=sys.stderr)
        sys.exit(1)
