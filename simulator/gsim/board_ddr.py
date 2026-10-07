#!/usr/bin/env python3
"""Focused configurable-clock serial-download regression with the AXI DDR backend."""
import argparse
import subprocess
import sys
from run import BUILD, ROOT, run, setup, test

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-hz", type=int, default=50_000_000)
    parser.add_argument("--baud", type=int, default=1_500_000)
    parser.add_argument("--timing-profile", default="early-issue",
                        help="Use the exact board timing profile under test")
    parser.add_argument("--extra-stop-bit", action="store_true",
                        help="legacy relaxed sender; default is continuous 8N1")
    args = parser.parse_args()
    if not 6_000_000 <= args.cpu_hz <= 200_000_000:
        parser.error("CPU clock must be in 6..200 MHz")
    if args.baud <= 0 or args.baud * 16 > args.cpu_hz:
        parser.error("UART reference (16*baud) must fit the CPU clock")
    name = f"board-ddr-fifo-{args.cpu_hz}-{args.baud}-" + ("gap" if args.extra_stop_bit else "8n1")
    if args.timing_profile != "early-issue":
        name += "-" + args.timing_profile
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    firmware = output / "firmware"
    run([sys.executable, ROOT / "fpga/firmware/build.py", "--out", firmware,
         "--uart-divisor", "1", "--cpu-hz", str(args.cpu_hz), "--ddr"],
        log=output / "firmware-build.log")
    gsim, cxx = setup(False)
    test(gsim, cxx, name, "ooo.BoardSocGsimMain", "BoardSocGsim", "board_boot.cpp",
         parameters=("ddr", str(args.cpu_hz), args.timing_profile, str(args.baud), "2", "2", "1"),
         runtime_args=(firmware / "bootrom.bin", firmware / "sample_app.bin"),
         defines={"UART_DIVISOR": 1, "BOARD_CPU_HZ": args.cpu_hz, "DDR_MODEL": 1, "BOARD_UART_BAUD": args.baud,
                  "UART_EXTRA_STOP_BITS": int(args.extra_stop_bit)},
         sanitizer=True, timeout=600)

if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM board DDR: {error}", file=sys.stderr)
        sys.exit(1)
