#!/usr/bin/env python3
"""Build the DDR50/115200 CPU-visible DDR benchmark; no RTL/Vivado changes."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    source = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/fpga/ddr-bench-50m")
    parser.add_argument("--prefix", default="riscv64-unknown-elf-")
    parser.add_argument("--cpu-hz", type=int, default=50_000_000)
    parser.add_argument("--baud", type=int, default=115200,
                        help="Inherited BootROM baud, banner only; does not reconfigure UART")
    args = parser.parse_args()
    if not 6_000_000 <= args.cpu_hz <= 200_000_000:
        parser.error("CPU clock must be in 6..200 MHz")
    if args.baud <= 0 or args.baud * 16 > args.cpu_hz:
        parser.error("UART reference (16*baud) must fit the CPU clock")
    for tool in ("gcc", "objcopy", "size", "objdump"):
        if not shutil.which(args.prefix + tool):
            parser.error(f"missing tool: {args.prefix + tool}")
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    elf = output / "ddr_bench.elf"
    subprocess.run([
        args.prefix + "gcc", "-march=rv64im_zicsr_zifencei", "-mabi=lp64",
        "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0", "-O2",
        "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
        "-ffunction-sections", "-fdata-sections", "-nostdlib", "-nostartfiles",
        "-Wall", "-Wextra", "-Werror", "-Wl,--gc-sections", "-Wl,--no-relax",
        f"-DCPU_HZ={args.cpu_hz}ULL", f"-DUART_BAUD={args.baud}U",
        "-Wl,--defsym=BOARD_RAM_BYTES=536870912",
        "-Wl,--defsym=DDR_TEST_PROGRAM_LIMIT=0x80400000",
        f"-T{source / 'sample_app.ld'}", f"-Wl,-Map,{output / 'ddr_bench.map'}",
        str(source / "sample_start.S"), str(source / "ddr_bench.c"), "-o", str(elf)
    ], check=True)
    image = output / "ddr_bench.bin"
    subprocess.run([args.prefix + "objcopy", "-O", "binary", str(elf), str(image)], check=True)
    subprocess.run([args.prefix + "size", str(elf)], check=True)
    if not 0 < image.stat().st_size <= 2 * 1024 * 1024:
        raise RuntimeError("flat binary overlaps destructive benchmark region")
    # Retain the actual instructions for timing-kernel audit.
    with (output / "ddr_bench.dis").open("w") as stream:
        subprocess.run([args.prefix + "objdump", "-d", str(elf)], stdout=stream, check=True)
    print(f"Outputs: {output}")
    print(f"Target: {args.cpu_hz} Hz / inherited {args.baud} baud; {image.stat().st_size} bytes")
    print("RAM app only; do not regenerate/program the bitstream.")


if __name__ == "__main__":
    main()
