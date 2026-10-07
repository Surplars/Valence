#!/usr/bin/env python3
"""Build the pinned EEMBC CoreMark as a Valence ROM-monitor RAM application."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = Path(__file__).resolve().parent
SOURCE = ROOT / "simulator/build/coremark-src"
REVISION = "1f483d5b8316753a742cbf5590caf5bd0a4e4777"
BENCHMARK_FILES = (
    "core_main.c", "core_list_join.c", "core_matrix.c",
    "core_state.c", "core_util.c",
)
MAX_IMAGE_BYTES = 992 * 1024


def run(command, **kwargs):
    print("+ " + " ".join(map(str, command)), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def check_source():
    if not all((SOURCE / name).is_file() for name in BENCHMARK_FILES):
        raise RuntimeError("CoreMark source is missing; run make coremark-setup")
    revision = subprocess.check_output(
        ["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    changes = subprocess.check_output(
        ["git", "-C", str(SOURCE), "status", "--porcelain", "--untracked-files=no"],
        text=True).strip()
    if revision != REVISION or changes:
        raise RuntimeError("CoreMark source is not the clean pinned revision")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/fpga/firmware")
    parser.add_argument("--iterations", type=int, default=0,
                        help="0 auto-calibrates a valid >=10 second run (default)")
    parser.add_argument("--prefix", default="riscv64-unknown-elf-")
    parser.add_argument("--clock-hz", type=int, default=40000000)
    parser.add_argument("--memory", choices=("ram", "ddr"), default="ram")
    parser.add_argument("--march", choices=("rv64im_zicsr_zifencei", "rv64imc_zicsr_zifencei"),
                        default="rv64im_zicsr_zifencei",
                        help="Integer ISA only; ABI remains lp64 and default image is unchanged")
    args = parser.parse_args()
    if not 0 <= args.iterations <= 0x7fffffff:
        parser.error("iterations must be in 0..2147483647")
    if not 6000000 <= args.clock_hz <= 200000000:
        parser.error("clock-hz must be in 6000000..200000000")
    check_source()

    gcc, objcopy, size = [args.prefix + name for name in ("gcc", "objcopy", "size")]
    for tool in (gcc, objcopy, size):
        if not shutil.which(tool):
            parser.error(f"missing tool: {tool}")
    version = subprocess.check_output([gcc, "-dumpfullversion"], text=True).strip()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    elf = output / "coremark_board.elf"
    image = output / "coremark_board.bin"
    linker = FIRMWARE / "sample_app.ld"
    start = FIRMWARE / "sample_start.S"
    port = FIRMWARE / "coremark_port"
    memory = "1 MiB on-chip UltraRAM" if args.memory == "ram" else "PL DDR via write-back L1"
    location = f"code and data in {memory} at {args.clock_hz} Hz"
    flags = [
        "-O2", f"-march={args.march}", "-mabi=lp64",
        f'-DCOREMARK_COMPILER_FLAGS="-O2 -march={args.march} -mabi=lp64"',
        "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0",
        "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
        "-ffunction-sections", "-fdata-sections", "-nostdlib", "-nostartfiles",
        "-Wl,--gc-sections", "-Wl,--no-relax",
        f"-DCOREMARK_ITERATIONS={args.iterations}",
        f"-DCPU_HZ={args.clock_hz}ULL",
        f'-DMEM_LOCATION="{location}"',
        f'-DCOREMARK_COMPILER_VERSION="riscv64-unknown-elf-gcc {version}"',
        "-I", str(port), "-I", str(SOURCE),
        "-T", str(linker), f"-Wl,-Map,{output / 'coremark_board.map'}",
    ]
    run([gcc, *flags, str(start), str(port / "core_portme.c"),
         *(str(SOURCE / name) for name in BENCHMARK_FILES),
         "-lgcc", "-o", str(elf)])
    run([objcopy, "-O", "binary", str(elf), str(image)])
    run([size, str(elf)])
    length = image.stat().st_size
    if not 0 < length <= MAX_IMAGE_BYTES:
        raise RuntimeError(f"RAM application size {length} exceeds {MAX_IMAGE_BYTES}")
    print(f"CoreMark revision: {REVISION}")
    print(f"RAM application: {image} ({length} bytes)")
    isa = "RV64IMC" if args.march == "rv64imc_zicsr_zifencei" else "RV64IM"
    print(f"Target: {isa}, 0x80200000, {args.clock_hz} Hz, {args.memory}; ROM bitstream is unchanged")


if __name__ == "__main__":
    main()
