#!/usr/bin/env python3
"""Repackage an authenticated existing Linux/rootfs for a different board clock.

No kernel rebuild, source downloads or upstream edits. The output is unverified
on hardware until the user boots it. Kernel/rootfs bytes are reused unchanged.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess

from build_linux import (HERE, ROOT, LOAD, KERNEL, DTB, RAM_END, OPENSBI_LOCK,
                         clean_revision, digest, image_header, opensbi_setup,
                         run, validate_payload)


def fdt_u32(blob, node, property_name):
    """Read a cell from the DTB itself; dtc text may render cells as strings."""
    magic, total, off_struct, off_strings = struct.unpack_from(">4I", blob)
    if magic != 0xd00dfeed or total != len(blob):
        raise RuntimeError("Invalid flattened device tree")
    cursor, stack, values = off_struct, [], []
    while cursor < off_strings:
        token = struct.unpack_from(">I", blob, cursor)[0]
        cursor += 4
        if token == 1:
            end = blob.index(0, cursor)
            stack.append(blob[cursor:end].decode())
            cursor = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, nameoff = struct.unpack_from(">2I", blob, cursor)
            cursor += 8
            start = off_strings + nameoff
            name = blob[start:blob.index(0, start)].decode()
            if "/".join(stack) == node and name == property_name:
                if size != 4:
                    raise RuntimeError(f"Not a single DTB cell: {node}/{name}")
                values.append(struct.unpack_from(">I", blob, cursor)[0])
            cursor = (cursor + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            break
        else:
            raise RuntimeError("Invalid DTB structure token")
    if len(values) != 1:
        raise RuntimeError(f"Missing/duplicate DTB property: {node}/{property_name}")
    return values[0]


def board_dts(template, cpu_hz, uart_baud):
    if not 6_000_000 <= cpu_hz <= 200_000_000 or cpu_hz % 1_000_000:
        raise ValueError("CPU clock must be whole MHz, 6..200 MHz")
    if uart_baud not in (115200, 460800, 1500000) or uart_baud * 16 > cpu_hz:
        raise ValueError("Unsupported UART reference clock")
    fields = {
        'model = "Valence ZU15EG PL DDR50 single-hart";': f'model = "Valence ZU15EG PL DDR{cpu_hz // 1_000_000} single-hart";',
        'timebase-frequency = <50000000>;': f'timebase-frequency = <{cpu_hz}>;',
        'clock-frequency = <1843200>;': f'clock-frequency = <{uart_baud * 16}>;',
        'current-speed = <115200>;': f'current-speed = <{uart_baud}>;',
        'stdout-path = "serial0:115200n8";': f'stdout-path = "serial0:{uart_baud}n8";',
    }
    for old, new in fields.items():
        if template.count(old) != 1:
            raise RuntimeError(f"DTS template contract changed: {old}")
        template = template.replace(old, new)
    return template


def validate_base(base, manifest):
    for name in ("Image", "linux.config"):
        expected = manifest["files"][name]
        path = base / name
        if path.stat().st_size != expected["bytes"] or digest(path) != expected["sha256"]:
            raise RuntimeError(f"Reused kernel/config provenance mismatch: {name}")
    config = (base / "linux.config").read_text().splitlines()
    for required in ("CONFIG_64BIT=y", "CONFIG_MMU=y", "CONFIG_RISCV_SBI=y",
                     "CONFIG_HVC_RISCV_SBI=y", "CONFIG_BINFMT_ELF=y", "CONFIG_CMDLINE_FORCE=y",
                     "CONFIG_BINFMT_SCRIPT=y", "CONFIG_MULTIUSER=y", "CONFIG_UNIX98_PTYS=y",
                     "CONFIG_RD_GZIP=y", "CONFIG_INITRAMFS_COMPRESSION_GZIP=y"):
        if required not in config:
            raise RuntimeError(f"Missing reused kernel capability: {required}")
    if "CONFIG_FPU=y" in config or "CONFIG_SMP=y" in config or manifest["rootfs"] != "busybox":
        raise RuntimeError("Expected single-hart, soft-float BusyBox kernel")
    if manifest["issue_width"] != 2 or manifest["ram_bytes"] != 0x20000000:
        raise RuntimeError("Incompatible board memory/issue profile")
    return image_header(base / "Image")


def build(args):
    base, out = args.base.resolve(), args.out.resolve()
    if out == base or out.exists():
        raise RuntimeError("Select a fresh output directory; preserve existing kernel")
    manifest = json.loads((base / "manifest.json").read_text())
    runtime_size = validate_base(base, manifest)
    source = ROOT / "simulator/build/linux"
    if clean_revision(source) != manifest["linux_revision"]:
        raise RuntimeError("Linux revision differs from reused kernel")
    opensbi = opensbi_setup(False)
    if clean_revision(opensbi) != manifest["opensbi_revision"] or manifest["opensbi_revision"] != OPENSBI_LOCK["revision"]:
        raise RuntimeError("OpenSBI revision differs from provenance")
    dts_text = board_dts((HERE / "linux-ddr50.dts").read_text(), args.cpu_hz, args.uart_baud)
    out.mkdir(parents=True)
    label = f"ddr{args.cpu_hz // 1_000_000}_uart{args.uart_baud}"
    dts, dtb = out / f"valence-{label}.dts", out / f"valence-{label}.dtb"
    dts.write_text(dts_text)
    dtc = base / "linux/scripts/dtc/dtc"
    run([dtc, "-I", "dts", "-O", "dtb", "-o", dtb, dts])
    for node, name, value in (("/cpus", "timebase-frequency", args.cpu_hz),
                            ("/soc/serial@10000000", "clock-frequency", args.uart_baud * 16),
                            ("/soc/serial@10000000", "current-speed", args.uart_baud)):
        if fdt_u32(dtb.read_bytes(), node, name) != value:
            raise RuntimeError(f"DTB clock/baud mismatch: {name}")
    if dtb.stat().st_size + 8192 > 0x10000:
        raise RuntimeError("DTB exceeds relocation slot")
    image = base / "Image"
    fw_out = out / "opensbi"
    run(["make", f"-j{args.jobs}", "PLATFORM=generic", "CROSS_COMPILE=riscv64-linux-gnu-",
         "PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei", "PLATFORM_RISCV_ABI=lp64",
         "FW_TEXT_START=0x80200000", "FW_DYNAMIC=n", "FW_JUMP=n", "FW_PAYLOAD=y",
         "FW_PAYLOAD_OFFSET=0x200000", "FW_PAYLOAD_FDT_ADDR=0x80300000", "FW_FDT_PADDING=8192",
         f"FW_FDT_PATH={dtb}", f"FW_PAYLOAD_PATH={image}", f"O={fw_out}"],
        cwd=opensbi, log=out / "opensbi-build.log", timeout=600)
    firmware = fw_out / "platform/generic/firmware/fw_payload.bin"
    elf = firmware.with_suffix(".elf")
    symbols = {parts[2]: int(parts[0], 16) for line in
               subprocess.check_output(["riscv64-linux-gnu-nm", elf], text=True).splitlines()
               if len(parts := line.split()) == 3}
    if symbols.get("_fw_start") != LOAD or symbols.get("payload_bin") != KERNEL:
        raise RuntimeError("Firmware/kernel entry mismatch")
    if not LOAD < symbols.get("_fw_end", RAM_END) <= DTB:
        raise RuntimeError("Resident firmware overlaps DTB")
    fdt_offset = symbols.get("fw_fdt_bin", 0) - LOAD
    combined = firmware.read_bytes()
    if fdt_offset < 0 or combined[fdt_offset:fdt_offset + dtb.stat().st_size] != dtb.read_bytes():
        raise RuntimeError("OpenSBI does not embed the selected clock/baud DTB")
    padding = validate_payload(combined, image.read_bytes())
    result = out / f"opensbi_linux_{label}.bin"
    for src, dest in ((firmware, result), (elf, out / f"opensbi_linux_{label}.elf"),
                      (image, out / "Image"), (base / "linux.config", out / "linux.config")):
        shutil.copyfile(src, dest)
    # Do not inherit an earlier simulation attempt as evidence for this image.
    data = {key: manifest[key] for key in ("linux_revision", "opensbi_revision", "linux_version",
            "rootfs", "initramfs", "userland", "issue_width", "ram_base", "ram_bytes", "entry",
            "kernel_entry", "dtb_relocation", "bootrom_reserved", "console")}
    data.update(cpu_hz=args.cpu_hz, uart_baud=args.uart_baud, uart_reference_hz=args.uart_baud * 16,
                kernel_runtime_bytes=runtime_size, static_firmware_end=hex(symbols["_fw_end"]),
                payload_alignment_padding_bytes=padding, on_board_verified=False, gsim_verified=False,
                reused_kernel_manifest={"path": str(base / "manifest.json"),
                                        "sha256": digest(base / "manifest.json")},
                builder_sha256=digest(Path(__file__)),
                files={p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in
                       (result, result.with_suffix(".elf"), out / "Image", out / "linux.config", dtb, dts)})
    (out / "manifest.json").write_text(json.dumps(data, indent=2) + "\n")
    print(f"READY: {result} ({result.stat().st_size} bytes), CPU={args.cpu_hz}, UART={args.uart_baud}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=ROOT / "build/fpga/linux-ddr50-busybox")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cpu-hz", type=int, required=True)
    parser.add_argument("--uart-baud", type=int, required=True)
    parser.add_argument("--jobs", type=int, default=16)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        build(args)
    except (RuntimeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Linux repackage: {error}\n")
