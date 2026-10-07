#!/usr/bin/env python3
"""Build the UART-downloadable destructive DDR memory tester; no Vivado required."""
import argparse
from pathlib import Path
import shutil
import subprocess


def main():
    source = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=source.parents[1] / "build/fpga/ddr-test")
    parser.add_argument("--prefix", default="riscv64-unknown-elf-")
    parser.add_argument("--cpu-hz", type=int, default=50_000_000)
    parser.add_argument("--baud", type=int, default=1_500_000)
    args = parser.parse_args()
    if not 6_000_000 <= args.cpu_hz <= 200_000_000:
        parser.error("CPU clock must be in 6..200 MHz")
    if args.baud not in (115200, 1500000):
        parser.error("UART baud must be 115200 or 1500000")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for tool in ("gcc", "objcopy", "size"):
        if not shutil.which(args.prefix + tool):
            parser.error(f"missing tool: {args.prefix + tool}")
    elf = output / "ddr_test.elf"
    subprocess.run([args.prefix + "gcc", "-march=rv64im_zicsr_zifencei", "-mabi=lp64",
                    "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0", "-O2",
                    "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
                    "-ffunction-sections", "-fdata-sections", "-nostdlib", "-nostartfiles",
                    "-Wall", "-Wextra", "-Werror", "-Wl,--gc-sections", "-Wl,--no-relax",
                    f"-DCPU_HZ={args.cpu_hz}ULL", f"-DUART_BAUD={args.baud}U",
                    "-Wl,--defsym=BOARD_RAM_BYTES=536870912",
                    f"-T{source / 'sample_app.ld'}",
                    "-Wl,--defsym=DDR_TEST_PROGRAM_LIMIT=0x80400000",
                    f"-Wl,-Map,{output / 'ddr_test.map'}",
                    str(source / "sample_start.S"), str(source / "ddr_test.c"),
                    "-o", str(elf)], check=True)
    # Linker enforces the program/BSS vs test-region boundary via DDR_TEST_PROGRAM_LIMIT.
    subprocess.run([args.prefix + "objcopy", "-O", "binary", str(elf),
                    str(output / "ddr_test.bin")], check=True)
    subprocess.run([args.prefix + "size", str(elf)], check=True)
    print(f"Outputs: {output}")


if __name__ == "__main__":
    main()
