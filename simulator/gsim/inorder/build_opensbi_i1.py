#!/usr/bin/env python3
"""Build untouched stock OpenSBI in a fresh independent O= folder; no OoO firmware modifications."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def run(argv, log, cwd=ROOT):
    with log.open("w") as f:
        subprocess.run(list(map(str, argv)), cwd=cwd, stdout=f, stderr=subprocess.STDOUT, check=True)
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--source", type=Path, default=Path("/home/openion/Valence/simulator/build/opensbi-v1.9"))
    args = ap.parse_args()
    output = args.output.resolve()
    source = args.source.resolve()
    if output.exists():
        ap.error("fresh output required")
    if source == output or source in output.parents:
        ap.error("independent O= outside stock source required")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True):
        ap.error("stock OpenSBI source must be clean")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != "cbf9f6734dd85a982c63e3cb5db7ffe09da839ca":
        ap.error("expected pinned local OpenSBI v1.9")
    output.mkdir(parents=True)
    def assembly(name, linker):
        run(["riscv64-unknown-elf-gcc", "-march=rv64imac_zicsr_zifencei", "-mabi=lp64",
             "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
             "-T" + str(HERE / linker), HERE / (name + ".S"), "-o", output / (name + ".elf")],
            output / (name + "-build.log"))
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / (name + ".elf"),
             output / (name + ".bin")], output / (name + "-objcopy.log"))
    assembly("opensbi_shim", "soc_link.ld")
    assembly("opensbi_handoff", "opensbi_handoff.ld")
    dtc = shutil.which("dtc")
    if not dtc:
        raise RuntimeError("dtc absent")
    run([dtc, "-I", "dts", "-O", "dtb", "-o", output / "orbital-i1.dtb", HERE / "opensbi_i1.dts"],
        output / "dtc.log")
    command = ["make", "-j" + str(min(8, os.cpu_count() or 1)), "-C", source, "O=" + str(output / "stock"),
               "PLATFORM=generic", "CROSS_COMPILE=riscv64-linux-gnu-",
               "PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei", "PLATFORM_RISCV_ABI=lp64",
               "FW_TEXT_START=0x80280000", "FW_JUMP=y", "FW_DYNAMIC=n", "FW_PAYLOAD=n",
               "FW_JUMP_ADDR=0x80400000", "FW_JUMP_FDT_ADDR=0x80500000"]
    run(command, output / "opensbi-build.log")
    stock = output / "stock/platform/generic/firmware"
    for name in ("fw_jump.bin", "fw_jump.elf"):
        shutil.copyfile(stock / name, output / name)
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True):
        raise RuntimeError("stock OpenSBI changed")
    segments = [{"file": "opensbi_shim.bin", "address": "0x80200000"},
                {"file": "fw_jump.bin", "address": "0x80280000"},
                {"file": "opensbi_handoff.bin", "address": "0x80400000"},
                {"file": "orbital-i1.dtb", "address": "0x80500000"}]
    manifest = {"status": "BUILT_ONLY_NOT_BOOT_QUALIFIED", "opensbi_source": str(source),
                "opensbi_revision": revision, "stock_source_modified": False, "build_command": list(map(str, command)),
                "isa": "rv64imac_zicsr_zifencei_svade", "abi": "lp64", "cpu_hz": 100000000,
                "uart_baud": 460800, "segments": segments, "S_payload_is_not_Linux": True,
                "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in
                                  [Path(__file__), HERE / "opensbi_i1.dts", HERE / "opensbi_shim.S",
                                   HERE / "opensbi_handoff.S", HERE / "opensbi_handoff.ld", HERE / "soc_link.ld"]},
                "files_sha256": {p.name: sha(p) for p in output.iterdir() if p.is_file()}}
    for s in manifest["segments"]:
        s["bytes"] = (output / s["file"]).stat().st_size
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"manifest": str(output / "manifest.json"), "segments": segments}), flush=True)
if __name__ == "__main__":
    main()
