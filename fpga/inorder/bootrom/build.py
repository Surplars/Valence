#!/usr/bin/env python3
"""Compile stackless I1 BootROM into a fresh build folder; do not edit source hex."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    if args.output.exists():
        ap.error("fresh output directory required")
    args.output.mkdir(parents=True)
    here = Path(__file__).resolve().parent
    flags = ["-march=rv64i_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
             "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T" + str(here / "link.ld")]
    subprocess.run(["riscv64-unknown-elf-gcc", *flags, here / "start.S", "-o", args.output / "bootrom.elf"], check=True)
    subprocess.run(["riscv64-unknown-elf-objcopy", "-O", "binary", args.output / "bootrom.elf",
                    args.output / "bootrom.bin"], check=True)
    image = (args.output / "bootrom.bin").read_bytes()
    if not image or len(image) > 4096:
        raise RuntimeError("invalid ROM size")
    padded = image + bytes(4096 - len(image))
    text = "".join(f"{int.from_bytes(padded[n:n+8], 'little'):016x}\n" for n in range(0, 4096, 8))
    (args.output / "bootrom.hex").write_text(text)
    (args.output / "manifest.json").write_text(json.dumps({"bytes": len(image), "flags": flags,
        "image_sha256": hashlib.sha256(image).hexdigest(), "hex_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (here / "start.S", here / "link.ld")}}, indent=2))
    print(f"I1_BOOTROM_BUILD_PASS bytes={len(image)} capacity=4096")


if __name__ == "__main__":
    main()
