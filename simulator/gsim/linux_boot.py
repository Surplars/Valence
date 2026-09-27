#!/usr/bin/env python3
"""Build a local Linux source snapshot and boot it behind pinned OpenSBI in GSIM."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

from run import BUILD, COREMARK_SOURCE, HERE, OPENSBI_LOCK, coremark_setup, opensbi_setup, run, setup, test


LINUX_ORIGIN = Path(os.environ.get("VALENCE_LINUX_SOURCE", "~/board/linux")).expanduser().resolve()
LINUX_SOURCE = BUILD / "linux-source"
LINUX_OUTPUT = BUILD / "linux-riscv"
LINUX_BOOT = BUILD / "linux-boot"
CONFIG_VERSION = 4


def write_if_changed(path, content):
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def coremark_binary():
    coremark_setup(False)
    port = HERE / "payloads/linux_coremark"
    sources = [COREMARK_SOURCE / name for name in
               ("core_main.c", "core_list_join.c", "core_matrix.c", "core_state.c", "core_util.c")]
    dependencies = [*sources, port / "start.S", port / "core_portme.c", port / "core_portme.h",
                    HERE / "payloads/linux-syscall.h", Path(__file__)]
    binary = LINUX_OUTPUT / "coremark"
    if not binary.exists() or binary.stat().st_mtime_ns < max(path.stat().st_mtime_ns for path in dependencies):
        run(["riscv64-linux-gnu-gcc", "-O2", "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax",
             "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib", "-static", "-no-pie",
             "-Wl,--build-id=none", "-Wl,--no-relax", "-Wl,-e,_start", "-I" + str(port), "-I" + str(COREMARK_SOURCE),
             port / "start.S", port / "core_portme.c", *sources, "-lgcc", "-o", binary])
    return binary


def source_snapshot():
    if not (LINUX_ORIGIN / "Makefile").is_file():
        raise RuntimeError(f"Linux source tree missing: {LINUX_ORIGIN}")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=LINUX_ORIGIN,
                                       text=True).strip()
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "."],
                      cwd=LINUX_ORIGIN).returncode:
        raise RuntimeError("Linux source has tracked changes; snapshot requires a clean revision")
    marker = LINUX_SOURCE / ".valence-source-revision"
    if marker.is_file():
        if marker.read_text().strip() != revision or not (LINUX_SOURCE / "Makefile").is_file():
            raise RuntimeError("Linux HEAD changed; move aside build/gsim/linux-source and build/gsim/linux-riscv")
        return revision
    if LINUX_SOURCE.exists() and any(LINUX_SOURCE.iterdir()):
        raise RuntimeError(f"refusing to overwrite nonempty Linux source snapshot: {LINUX_SOURCE}")
    LINUX_SOURCE.mkdir(parents=True, exist_ok=True)
    print(f"+ snapshot Linux {revision} from {LINUX_ORIGIN}", flush=True)
    archive = subprocess.Popen(["git", "archive", "HEAD"], cwd=LINUX_ORIGIN, stdout=subprocess.PIPE)
    try:
        extracted = subprocess.run(["tar", "-xf", "-", "-C", str(LINUX_SOURCE)],
                                   stdin=archive.stdout, check=False)
    finally:
        archive.stdout.close()
    if archive.wait() or extracted.returncode:
        raise RuntimeError("Linux source snapshot failed")
    marker.write_text(revision + "\n")
    return revision


def kernel_image():
    revision = source_snapshot()
    LINUX_OUTPUT.mkdir(parents=True, exist_ok=True)
    coremark = coremark_binary()
    init_source = HERE / "payloads/linux-init.c"
    init_header = HERE / "payloads/linux-syscall.h"
    init_binary = LINUX_OUTPUT / "valence-init"
    if not init_binary.exists() or init_binary.stat().st_mtime_ns < max(
            init_source.stat().st_mtime_ns, init_header.stat().st_mtime_ns, Path(__file__).stat().st_mtime_ns):
        run(["riscv64-linux-gnu-gcc", "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax", "-O2",
             "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib", "-static",
             "-no-pie", "-Wl,--build-id=none", "-Wl,--no-relax", "-Wl,-e,_start", init_source,
             "-o", init_binary])
    initramfs_list = LINUX_OUTPUT / "initramfs.list"
    write_if_changed(initramfs_list,
                     f"dir /dev 755 0 0\nnod /dev/console 600 0 0 c 5 1\n"
                     f"dir /bin 755 0 0\nfile /init {init_binary} 755 0 0\n"
                     f"file /bin/coremark {coremark} 755 0 0\n")
    config_marker = LINUX_OUTPUT / ".valence-config.json"
    expected = {"version": CONFIG_VERSION, "revision": revision,
                "init_source_sha256": hashlib.sha256(init_source.read_bytes() + init_header.read_bytes()).hexdigest()}
    config_file = LINUX_OUTPUT / ".config"
    saved = json.loads(config_marker.read_text()) if config_marker.exists() else {}
    config_digest = hashlib.sha256(config_file.read_bytes()).hexdigest() if config_file.exists() else ""
    if any(saved.get(key) != value for key, value in expected.items()) or saved.get("config_sha256") != config_digest:
        base = ["make", f"O={LINUX_OUTPUT}", "ARCH=riscv", "CROSS_COMPILE=riscv64-linux-gnu-"]
        run([*base, "tinyconfig"], cwd=LINUX_SOURCE, log=LINUX_OUTPUT / "config.log")
        enabled = ["PRINTK", "TTY", "SERIAL_8250", "SERIAL_8250_CONSOLE",
                   "SERIAL_OF_PLATFORM", "SERIAL_EARLYCON", "SERIAL_EARLYCON_RISCV_SBI",
                   "NONPORTABLE", "HVC_RISCV_SBI", "BLK_DEV_INITRD", "BINFMT_ELF",
                   "DEVTMPFS", "DEVTMPFS_MOUNT", "PROC_FS", "SYSFS", "TMPFS", "CMDLINE_FORCE"]
        disabled = ["EFI", "SMP", "FPU", "VT", "VT_CONSOLE", "CONSOLE_TRANSLATIONS", "DUMMY_CONSOLE"]
        flags = [item for name in enabled for item in ("--enable", name)] + [
            item for name in disabled for item in ("--disable", name)]
        run([LINUX_SOURCE / "scripts/config", "--file", LINUX_OUTPUT / ".config", *flags,
             "--set-val", "SERIAL_8250_NR_UARTS", "1",
             "--set-val", "SERIAL_8250_RUNTIME_UARTS", "1",
             "--set-str", "INITRAMFS_SOURCE", str(initramfs_list),
             "--set-str", "CMDLINE",
             "earlycon=sbi console=hvc0 rdinit=/init loglevel=7"])
        run([*base, "olddefconfig"], cwd=LINUX_SOURCE, log=LINUX_OUTPUT / "config.log")
        config_marker.write_text(json.dumps({**expected,
            "config_sha256": hashlib.sha256(config_file.read_bytes()).hexdigest()}, indent=2) + "\n")
    run(["make", f"O={LINUX_OUTPUT}", "ARCH=riscv", "CROSS_COMPILE=riscv64-linux-gnu-",
         "-j" + os.environ.get("LINUX_BUILD_JOBS", "8"), "Image"],
        cwd=LINUX_SOURCE, log=LINUX_OUTPUT / "kernel-build.log", timeout=1800)
    image = LINUX_OUTPUT / "arch/riscv/boot/Image"
    with image.open("rb") as stream:
        header = stream.read(64)
    if (header[0x30:0x35] != b"RISCV" or struct.unpack_from("<Q", header, 8)[0] != 0x200000 or
            struct.unpack_from("<Q", header, 16)[0] > (1 << 26) - 0x200000):
        raise RuntimeError("Linux Image is invalid or exceeds the GSIM RAM layout")
    (LINUX_BOOT / "source-used.json").write_text(json.dumps({
        "origin": str(LINUX_ORIGIN), "revision": revision, "image_bytes": image.stat().st_size
    }, indent=2) + "\n")
    return image


def boot_images():
    LINUX_BOOT.mkdir(parents=True, exist_ok=True)
    image = kernel_image()
    source = opensbi_setup(False)
    dtb = LINUX_BOOT / "valence.dtb"
    run(["dtc", "-I", "dts", "-O", "dtb", "-o", dtb, HERE / "payloads/linux.dts"])
    firmware_build = LINUX_BOOT / "firmware-build"
    run(["make", "-j" + os.environ.get("OPENSBI_BUILD_JOBS", "4"), "PLATFORM=generic",
         "CROSS_COMPILE=riscv64-linux-gnu-", f"PLATFORM_RISCV_ISA={OPENSBI_LOCK['march']}",
         f"PLATFORM_RISCV_ABI={OPENSBI_LOCK['abi']}", "FW_TEXT_START=0x80040000",
         "FW_JUMP_ADDR=0x80200000", "FW_JUMP_FDT_ADDR=0x800c0000",
         f"FW_FDT_PATH={dtb}", f"O={firmware_build}"],
        cwd=source, log=LINUX_BOOT / "firmware-build.log")
    firmware = firmware_build / "platform/generic/firmware/fw_jump.bin"
    reset = LINUX_BOOT / "reset"
    run(["riscv64-linux-gnu-gcc", f"-march={OPENSBI_LOCK['march']}", "-mabi=lp64",
         "-nostdlib", "-nostartfiles", "-static", "-no-pie", "-Wl,--build-id=none",
         "-Wl,--no-relax", "-T", HERE / "payloads/opensbi-reset.ld",
         HERE / "payloads/opensbi-reset.S", "-o", reset.with_suffix(".elf")])
    run(["riscv64-linux-gnu-objcopy", "-O", "binary", reset.with_suffix(".elf"),
         reset.with_suffix(".bin")])
    if not (0 < reset.with_suffix(".bin").stat().st_size <= 8192 and
            0 < firmware.stat().st_size < 0x70000):
        raise RuntimeError("OpenSBI firmware exceeds Linux boot layout")
    return reset.with_suffix(".bin"), firmware, image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("setup", "test", "console", "profile"))
    parser.add_argument("--issue-width", type=int, choices=(2, 4), default=2)
    parser.add_argument("--cache-mode", choices=("direct", "coherent"), default="direct")
    parser.add_argument("--cache-lines", type=int, choices=(128, 256), default=128)
    parser.add_argument("--profile-cycles", type=int, default=2_000_000)
    args = parser.parse_args()
    if args.profile_cycles <= 0:
        parser.error("--profile-cycles must be positive")
    if args.cache_mode == "direct" and args.cache_lines != 128:
        parser.error("--cache-lines requires --cache-mode coherent")
    if args.action == "setup":
        LINUX_BOOT.mkdir(parents=True, exist_ok=True)
        kernel_image()
        return
    gsim, cxx = setup(False)
    images = boot_images()
    interactive = args.action == "console"
    name = "linux-platform" if args.issue_width == 2 else "linux-platform-4issue"
    if args.cache_mode == "coherent":
        name += "-l1"
        if args.cache_lines != 128:
            name += f"-{args.cache_lines}"
    test(gsim, cxx, name, "ooo.LinuxPlatformGsimMain",
         "LinuxPlatformGsim", "linux_platform.cpp",
         parameters=(str(args.issue_width), args.cache_mode, str(args.cache_lines)),
         runtime_args=(*images, "--console") if interactive else
             (*images, f"--profile={args.profile_cycles}") if args.action == "profile" else images,
         defines={"LINUX_ISSUE_WIDTH": args.issue_width,
                  "LINUX_COHERENT_L1": int(args.cache_mode == "coherent"),
                  "LINUX_CACHE_LINES": args.cache_lines}, sanitizer=False,
         timeout=1800, interactive=interactive,
         run_log=f"profile-{args.profile_cycles}.log" if args.action == "profile" else "test.log")


if __name__ == "__main__":
    main()
