#!/usr/bin/env python3
"""Build one UART-loadable OpenSBI + Linux/initramfs image for DDR50/115200.

Local, clean source checkouts only; no downloads and no upstream source edits.
The board monitor passes a1=0, so OpenSBI embeds and relocates its own DTB.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
from run import OPENSBI_LOCK, opensbi_setup, run  # noqa: E402
import linux_boot  # noqa: E402
from memory_layout import MemoryLayout

LOAD = 0x80200000
KERNEL = 0x80400000
DTB = 0x80300000
RAM_END = 0xA0200000
MONITOR = RAM_END - 0x4000
CONFIG_VERSION = 3


def board_dts(isa, cpu_hz, uart_baud, memory_bytes=0x20000000):
    """Generate discovery for the explicitly selected RTL, never infer F/D."""
    if isa not in ("rv64imac", "rv64gc"):
        raise RuntimeError("Unsupported Linux ISA profile: " + isa)
    if not 6000000 <= cpu_hz <= 200000000 or not 0 < uart_baud <= cpu_hz // 16:
        raise RuntimeError("Invalid CPU / UART profile")
    text = (HERE / "linux-ddr50.dts").read_text()
    layout = MemoryLayout(memory_bytes)
    replacements = {
        'riscv,isa = "rv64imac_zicsr_zifencei";':
            'riscv,isa = "' + ("rv64imafdc" if isa == "rv64gc" else "rv64imac") + '_zicsr_zifencei";',
        "timebase-frequency = <50000000>;": f"timebase-frequency = <{cpu_hz}>;",
        'stdout-path = "serial0:115200n8";': f'stdout-path = "serial0:{uart_baud}n8";',
        "clock-frequency = <1843200>;": f"clock-frequency = <{uart_baud * 16}>;",
        "current-speed = <115200>;": f"current-speed = <{uart_baud}>;",
        'model = "Valence ZU15EG PL DDR50 single-hart";':
            f'model = "OpenIon Valence VL100 / Orbital-A1 / {isa} {cpu_hz // 1000000}MHz";',
        'compatible = "openion,valence-ddr50";':
            'compatible = "openion,valence-vl100", "openion,valence-ddr50";',
        'compatible = "riscv";':
            'compatible = "openion,orbital-a1", "riscv";',
        'reg = <0x0 0x80200000 0x0 0x20000000>;':
            f'reg = <0x0 0x80200000 0x0 0x{memory_bytes:x}>;',
        'monitor@a01fc000': f'monitor@{layout.monitor:x}',
        'reg = <0x0 0xa01fc000 0x0 0x4000>;':
            f'reg = <0x0 0x{layout.monitor:x} 0x0 0x4000>;',
    }
    for before, after in replacements.items():
        if text.count(before) != 1:
            raise RuntimeError("Board DTS template mismatch: " + before)
        text = text.replace(before, after)
    return text


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_revision(source):
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "."], cwd=source).returncode:
        raise RuntimeError(f"Tracked modifications in upstream source: {source}")
    return revision


def image_header(image, monitor=MONITOR):
    header = image.read_bytes()[:64]
    if len(header) != 64 or header[0x30:0x38] != b"RISCV\0\0\0" or header[0x38:0x3c] != b"RSC\x05":
        raise RuntimeError("Invalid RISC-V Linux Image magic")
    offset, size, flags = struct.unpack_from("<QQQ", header, 8)
    if offset != 0x200000 or flags & 1 or size < image.stat().st_size or KERNEL + size > monitor:
        raise RuntimeError("Linux Image alignment/endianness/runtime size exceeds board memory layout")
    return size


def validate_payload(combined, kernel_bytes, monitor=MONITOR):
    payload_end = KERNEL - LOAD + len(kernel_bytes)
    padding = combined[payload_end:]
    # fw_payload.S aligns .payload to 16 bytes. GAS can retain section-tail
    # padding after R_RISCV_ALIGN relaxation; the linker then aligns to 8.
    # Allow only their bounded zero padding, never a differing/truncated Image.
    max_padding = (16 - 1) + (8 - 1)
    if (combined[KERNEL - LOAD:payload_end] != kernel_bytes or len(padding) > max_padding
            or any(padding) or len(combined) > monitor - LOAD):
        raise RuntimeError("Payload mismatch or image overlaps monitor memory")
    return len(padding)


def busybox_rootfs_lines(userland, coremark):
    """Stage only the supported BusyBox userland, including from an older build."""
    rootfs_sources = HERE / "linux_rootfs"
    busybox = userland / "busybox-linux/busybox"
    user_manifest = json.loads((userland / "manifest.json").read_text())
    for binary in (busybox,):
        if digest(binary) != user_manifest["binaries"][binary.name]["sha256"]:
            raise RuntimeError(f"Rootfs executable provenance mismatch: {binary}")
    applets = set((userland / "busybox-linux/busybox.links").read_text().splitlines())
    dirs = {"/dev", "/dev/pts", "/proc", "/sys", "/tmp", "/run", "/root", "/etc", "/bin", "/sbin",
            "/usr", "/usr/bin", "/usr/sbin", "/usr/share", "/usr/share/licenses"}
    lines = [f"dir {name} {'1777' if name == '/tmp' else '755'} 0 0" for name in sorted(dirs)]
    lines += ["nod /dev/console 600 0 0 c 5 1", "nod /dev/null 666 0 0 c 1 3",
              f"file /bin/busybox {busybox} 755 0 0",
              f"file /bin/coremark {coremark} 755 0 0"]
    lines += [f"slink {name} /bin/busybox 777 0 0" for name in sorted(applets)]
    lines += [f"file {target} {rootfs_sources / name} {mode} 0 0" for name, target, mode in (
        ("init", "/init", "755"), ("profile", "/etc/profile", "644"), ("passwd", "/etc/passwd", "644"),
        ("group", "/etc/group", "644"), ("os-release", "/etc/os-release", "644"))]
    lines += [f"file /usr/share/licenses/{name} {path} 644 0 0" for name, path in (
        ("busybox", ROOT / "simulator/build/busybox-1.37.0/LICENSE"),
        ("musl", ROOT / "simulator/build/musl-1.2.5/COPYRIGHT"))]
    return lines, {"busybox": user_manifest["binaries"]["busybox"]}


def build(args):
    source = args.source.resolve()
    if not (source / "Makefile").is_file():
        raise RuntimeError(f"Missing local Linux source: {source}")
    revision = clean_revision(source)
    opensbi = opensbi_setup(False)
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "source.json"
    identity = {"linux_revision": revision, "opensbi_revision": OPENSBI_LOCK["revision"],
                "rootfs": args.rootfs, "isa_profile": args.isa,
                "cpu_hz": args.cpu_hz, "uart_baud": args.uart_baud}
    if marker.exists() and json.loads(marker.read_text()) != identity:
        raise RuntimeError("Source revision changed; select a new --out directory")
    marker.write_text(json.dumps(identity, indent=2) + "\n")
    kernel_out = output / "linux"
    kernel_out.mkdir(exist_ok=True)
    # Reuse the existing pinned EEMBC algorithm and Linux soft-float syscall port.
    linux_boot.LINUX_OUTPUT = kernel_out
    coremark = linux_boot.coremark_binary()
    payloads = ROOT / "simulator/gsim/payloads"
    init = kernel_out / "valence-init"
    run(["riscv64-linux-gnu-gcc", "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax", "-O2",
         "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib", "-static", "-no-pie",
         "-Wl,--build-id=none", "-Wl,--no-relax", "-Wl,-e,_start", payloads / "linux-init.c", "-o", init])
    initramfs = kernel_out / "initramfs.list"
    initramfs.write_text(f"dir /dev 755 0 0\nnod /dev/console 600 0 0 c 5 1\n"
                        f"dir /bin 755 0 0\nfile /init {init} 755 0 0\n"
                        f"file /bin/coremark {coremark} 755 0 0\n")
    userland = args.userland.resolve()
    rootfs_sources = HERE / "linux_rootfs"
    if args.rootfs == "busybox":
        lines, user_binaries = busybox_rootfs_lines(userland, coremark)
        initramfs.write_text("\n".join(lines) + "\n")
    make = ["make", f"O={kernel_out}", "ARCH=riscv", "CROSS_COMPILE=riscv64-linux-gnu-"]
    config = kernel_out / ".config"
    config_marker = kernel_out / "config-used.json"
    expected = {"version": CONFIG_VERSION, **identity,
                "builder_sha256": digest(Path(__file__)),
                "dts_template_sha256": digest(HERE / "linux-ddr50.dts"),
                "init_sha256": digest(payloads / "linux-init.c"),
                "syscall_sha256": digest(payloads / "linux-syscall.h")}
    if args.rootfs == "busybox":
        expected["rootfs_sources"] = {p.name: digest(p) for p in rootfs_sources.iterdir() if p.is_file()}
        expected["userland_binaries"] = user_binaries
    saved = json.loads(config_marker.read_text()) if config_marker.exists() else {}
    if any(saved.get(k) != v for k, v in expected.items()) or saved.get("config_sha256") != (
            digest(config) if config.exists() else ""):
        run([*make, "tinyconfig"], cwd=source, log=output / "config.log")
        enabled = ["PRINTK", "TTY", "SERIAL_8250", "SERIAL_8250_CONSOLE", "SERIAL_OF_PLATFORM",
                   "SERIAL_EARLYCON", "SERIAL_EARLYCON_RISCV_SBI", "NONPORTABLE", "HVC_RISCV_SBI",
                   "BLK_DEV_INITRD", "BINFMT_ELF", "DEVTMPFS", "DEVTMPFS_MOUNT", "PROC_FS",
                   "SYSFS", "TMPFS", "CMDLINE_FORCE"]
        if args.rootfs == "busybox":
            enabled += ["BINFMT_SCRIPT", "UNIX98_PTYS", "MULTIUSER", "FUTEX", "POSIX_TIMERS", "EPOLL",
                        "RD_GZIP", "INITRAMFS_COMPRESSION_GZIP"]
        disabled = ["EFI", "SMP", "VT", "VT_CONSOLE", "CONSOLE_TRANSLATIONS", "DUMMY_CONSOLE"]
        (enabled if args.isa == "rv64gc" else disabled).append("FPU")
        if args.rootfs == "busybox":
            disabled += ["INITRAMFS_COMPRESSION_NONE"]
        flags = [x for name in enabled for x in ("--enable", name)] + [
            x for name in disabled for x in ("--disable", name)]
        run([source / "scripts/config", "--file", config, *flags,
             "--set-val", "SERIAL_8250_NR_UARTS", "1", "--set-val", "SERIAL_8250_RUNTIME_UARTS", "1",
             "--set-str", "INITRAMFS_SOURCE", str(initramfs), "--set-str", "CMDLINE",
             "earlycon=sbi console=hvc0 rdinit=/init loglevel=7"])
        run([*make, "olddefconfig"], cwd=source, log=output / "config-final.log")
        config_marker.write_text(json.dumps({**expected, "config_sha256": digest(config)}, indent=2) + "\n")
    text = config.read_text()
    for required in ("CONFIG_64BIT=y", "CONFIG_MMU=y", "CONFIG_RISCV_SBI=y", "CONFIG_HVC_RISCV_SBI=y",
                     "CONFIG_BINFMT_ELF=y", "CONFIG_CMDLINE_FORCE=y"):
        if required not in text.splitlines():
            raise RuntimeError(f"Required Linux config not enabled: {required}")
    if args.rootfs == "busybox":
        for required in ("CONFIG_BINFMT_SCRIPT=y", "CONFIG_MULTIUSER=y", "CONFIG_UNIX98_PTYS=y",
                         "CONFIG_RD_GZIP=y", "CONFIG_INITRAMFS_COMPRESSION_GZIP=y"):
            if required not in text.splitlines():
                raise RuntimeError(f"Required BusyBox config not enabled: {required}")
    if ("CONFIG_FPU=y" in text.splitlines()) != (args.isa == "rv64gc"):
        raise RuntimeError("Linux FPU configuration does not match the explicit RTL ISA profile")
    if "CONFIG_SMP=y" in text.splitlines():
        raise RuntimeError("Unsupported SMP configuration")
    run([*make, f"-j{args.jobs}", "Image"], cwd=source, log=output / "kernel-build.log", timeout=2400)
    image = kernel_out / "arch/riscv/boot/Image"
    runtime_size = image_header(image)
    dtc = kernel_out / "scripts/dtc/dtc"
    dtb = output / "valence-ddr50.dtb"
    dts = output / "valence-board.dts"
    dts.write_text(board_dts(args.isa, args.cpu_hz, args.uart_baud))
    run([dtc, "-I", "dts", "-O", "dtb", "-o", dtb, dts])
    if dtb.stat().st_size + 8192 > 0x10000:
        raise RuntimeError("DTB exceeds reserved relocation slot")
    firmware_out = output / "opensbi"
    run(["make", f"-j{args.jobs}", "PLATFORM=generic", "CROSS_COMPILE=riscv64-linux-gnu-",
         "PLATFORM_RISCV_ISA=rv64imac_zicsr_zifencei", "PLATFORM_RISCV_ABI=lp64",
         "FW_TEXT_START=0x80200000", "FW_DYNAMIC=n", "FW_JUMP=n", "FW_PAYLOAD=y",
         "FW_PAYLOAD_OFFSET=0x200000", "FW_PAYLOAD_FDT_ADDR=0x80300000", "FW_FDT_PADDING=8192",
         f"FW_FDT_PATH={dtb}", f"FW_PAYLOAD_PATH={image}", f"O={firmware_out}"],
        cwd=opensbi, log=output / "opensbi-build.log", timeout=600)
    firmware = firmware_out / "platform/generic/firmware/fw_payload.bin"
    elf = firmware.with_suffix(".elf")
    symbols = dict((name, int(address, 16)) for address, kind, name in (
        line.split() for line in subprocess.check_output(["riscv64-linux-gnu-nm", elf], text=True).splitlines()
        if len(line.split()) == 3))
    if symbols.get("_fw_start") != LOAD or symbols.get("payload_bin") != KERNEL:
        raise RuntimeError("Unexpected firmware/kernel entry layout")
    if not LOAD < symbols.get("_fw_end", RAM_END) <= DTB:
        raise RuntimeError("Resident firmware overlaps relocated DTB")
    combined = firmware.read_bytes()
    kernel_bytes = image.read_bytes()
    payload_padding = validate_payload(combined, kernel_bytes)
    result = output / "opensbi_linux_ddr50.bin"
    shutil.copyfile(firmware, result)
    shutil.copyfile(image, output / "Image")
    shutil.copyfile(elf, output / "opensbi_linux_ddr50.elf")
    shutil.copyfile(config, output / "linux.config")
    manifest = {**identity, "linux_version": subprocess.check_output(
        [*make, "-s", "kernelrelease"], cwd=source, text=True).strip(),
        "cpu_hz": args.cpu_hz, "uart_baud": args.uart_baud, "uart_reference_hz": args.uart_baud * 16,
        "riscv_isa": "rv64imafdc_zicsr_zifencei" if args.isa == "rv64gc" else "rv64imac_zicsr_zifencei",
        "kernel_fpu": args.isa == "rv64gc", "linux_fp_context_verified": False,
        "issue_width": 2, "ram_base": hex(LOAD), "ram_bytes": 0x20000000,
        "entry": hex(LOAD), "kernel_entry": hex(KERNEL), "dtb_relocation": hex(DTB),
        "kernel_runtime_bytes": runtime_size, "static_firmware_end": hex(symbols["_fw_end"]),
        "payload_zero_padding_bytes": payload_padding,
        "bootrom_reserved": [hex(MONITOR), hex(RAM_END)],
        "initramfs": ("BusyBox 1.37.0 ash + CoreMark; static RV64IMAC/lp64 musl" if
                      args.rootfs == "busybox" else "minimal /init command loop + static soft-float CoreMark"),
        "console": "SBI DBCN hvc0 polling; no Linux AIA/UART external IRQ claim",
        "files": {p.name: {"bytes": p.stat().st_size, "sha256": digest(p)} for p in (
            result, output / "Image", dtb, dts, output / "linux.config", output / "opensbi_linux_ddr50.elf")},
        "on_board_verified": False, "gsim_verified": False}
    if args.rootfs == "busybox":
        manifest["userland"] = user_manifest
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"READY: {result} ({len(combined)} bytes), entry={LOAD:#x}, Linux={KERNEL:#x}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "simulator/build/linux")
    parser.add_argument("--out", type=Path, default=ROOT / "build/fpga/linux-ddr50-busybox")
    parser.add_argument("--rootfs", choices=("busybox", "minimal"), default="busybox")
    parser.add_argument("--isa", choices=("rv64imac", "rv64gc"), default="rv64imac",
                        help="must match BoardSocMain ISA profile; GC enables Linux FPU context handling")
    parser.add_argument("--cpu-hz", type=int, default=50000000)
    parser.add_argument("--uart-baud", type=int, default=115200)
    parser.add_argument("--userland", type=Path, default=ROOT / "build/fpga/linux-userland")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 8, 16))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if not 6000000 <= args.cpu_hz <= 200000000 or not 0 < args.uart_baud <= args.cpu_hz // 16:
        parser.error("invalid CPU frequency / UART baud profile")
    build(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Board Linux build: {error}", file=sys.stderr)
        sys.exit(1)
