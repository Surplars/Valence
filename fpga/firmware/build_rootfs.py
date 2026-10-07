#!/usr/bin/env python3
"""Static RV64IMAC/lp64 BusyBox + actual fastfetch, using isolated musl.

Sources/tools are downloaded separately into simulator/build/downloads.
No system install, source checkout edits, or host ABI libraries in target links.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
from run import run  # noqa: E402

ARCHIVES = {
    "musl-1.2.5.tar.gz": "a9a118bbe84d8764da0ea0d28b3ab3fae8477fc7e4085d90102b8596fc7c75e4",
    "busybox-1.37.0.tar.bz2": "3311dff32e746499f4df0d5df04d7eb396382d7e108bb9250e7b519b837043a4",
    "fastfetch-2.69.0.tar.gz": "d0e42faf307e39e7b531d632745a56e4eb558a6545f557280099c622562355ee",
    "cmake-3.31.6-linux-x86_64.tar.gz": "5a1133ff103c71eb5120e2cc3de922733e7d8a26a98ae716397e8676adb367bf",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_elf(path):
    header = subprocess.check_output(["riscv64-unknown-elf-readelf", "-h", path], text=True)
    program = subprocess.check_output(["riscv64-unknown-elf-readelf", "-l", path], text=True)
    if "RISC-V" not in header or "soft-float ABI" not in header or "INTERP" in program:
        raise RuntimeError(f"Not a static RISC-V soft-float executable: {path}")
    # Check the linked ELF's ISA declaration as well as its ABI. No F/D/V allowed.
    attrs = subprocess.check_output(["riscv64-unknown-elf-readelf", "-A", path], text=True)
    isa = re.search(r'Tag_RISCV_arch: "([^"]+)"', attrs)
    if not isa or re.search(r"_(f|d|v)[0-9]", isa.group(1)):
        raise RuntimeError(f"Unsupported linked ISA: {attrs}")


def build(output, jobs):
    sources = ROOT / "simulator/build"
    downloads = sources / "downloads"
    for name, expected in ARCHIVES.items():
        if name.startswith("cmake-") and shutil.which("cmake"):
            continue
        archive = downloads / name
        suffix = "-linux-x86_64.tar.gz" if name.startswith("cmake-") else (
            ".tar.bz2" if name.endswith(".bz2") else ".tar.gz")
        extracted = sources / name.removesuffix(suffix)
        if name.startswith("cmake-"):
            extracted = sources / name.removesuffix(".tar.gz")
        if archive.is_file() and sha(archive) != expected:
            raise RuntimeError(f"Wrong pinned archive: {archive}")
        if not extracted.exists():
            if not archive.is_file():
                raise RuntimeError(f"Missing source and pinned archive: {archive}")
            run(["tar", "-xf", archive, "-C", sources])
        elif not archive.is_file():
            print(f"Using existing extracted source/tool: {extracted} (archive absent)", flush=True)
    output.mkdir(parents=True, exist_ok=True)
    sysroot = output / "sysroot"
    musl = sources / "musl-1.2.5"
    musl_out = output / "musl"
    musl_out.mkdir(exist_ok=True)
    cc = "riscv64-unknown-elf-gcc -march=rv64imac -mabi=lp64"
    run([musl / "configure", "--target=riscv64-linux-musl", "--disable-shared",
         f"--prefix={sysroot}", f"--syslibdir={sysroot / 'lib'}", f"CC={cc}", "CFLAGS=-Os",
         "AR=riscv64-unknown-elf-ar", "RANLIB=riscv64-unknown-elf-ranlib"],
        cwd=musl_out, log=output / "musl-config.log")
    run(["make", f"-j{jobs}"], cwd=musl_out, log=output / "musl-build.log")
    run(["make", "install"], cwd=musl_out, log=output / "musl-install.log")
    # Bare-metal GCC has the correct lp64 multilib libgcc and CRTs. Its CRT
    # names are non-PIE; using these prevents accidental lp64d glibc linkage.
    specs = sysroot / "lib/musl-gcc.specs"
    original_specs = subprocess.check_output(["sh", musl / "tools/musl-gcc.specs.sh",
        sysroot / "include", sysroot / "lib", sysroot / "lib/ld-musl-riscv64.so.1"], text=True)
    specs.write_text(original_specs.split("*esp_link:", 1)[0].rstrip().replace("Scrt1.o", "crt1.o").replace(
        "crtbeginS.o", "crtbegin.o").replace("crtendS.o", "crtend.o") + "\n\n*lib:\n-lc\n\n")
    for name in ("linux", "asm", "asm-generic", "mtd", "scsi", "sound", "video", "drm"):
        run(["cp", "-a", f"/usr/riscv64-linux-gnu/include/{name}", sysroot / "include"])
    wrapper = output / "riscv64-valence-musl-gcc"
    wrapper.write_text(f'#!/bin/sh\nexec riscv64-unknown-elf-gcc -march=rv64imac -mabi=lp64 '
                       f'-D__linux__=1 -D__unix__=1 -specs="{specs}" "$@"\n')
    wrapper.chmod(0o755)
    smoke = output / "libc-smoke.c"
    smoke.write_text('#include <stdio.h>\nint main(void) { return printf("soft-float %.2f\\n", 1.25) < 0; }\n')
    run([wrapper, "-static", "-Os", smoke, "-o", output / "libc-smoke"], log=output / "libc-smoke.log")
    verify_elf(output / "libc-smoke")
    busybox = sources / "busybox-1.37.0"
    busy_out = output / "busybox-linux"
    busy_out.mkdir(exist_ok=True)
    make = ["make", f"O={busy_out}", "ARCH=riscv", "CROSS_COMPILE=riscv64-unknown-elf-", f"CC={wrapper}"]
    run([*make, "defconfig"], cwd=busybox, log=output / "busybox-config.log")
    run([sources / "linux/scripts/config", "--file", busy_out / ".config",
         "--enable", "STATIC", "--disable", "PIE", "--disable", "TC",
         "--disable", "SHA1_HWACCEL", "--disable", "SHA256_HWACCEL",
         "--set-str", "EXTRA_CFLAGS", "-Os", "--set-str", "EXTRA_LDFLAGS", "-static"])
    # defconfig is complete; avoid interactive prompts when editing existing bools.
    run([*make, f"-j{jobs}"], cwd=busybox, log=output / "busybox-build.log", timeout=900)
    run([*make, "busybox.links"], cwd=busybox, log=output / "busybox-links.log")
    busy_binary = busy_out / "busybox"
    verify_elf(busy_binary)
    fastfetch = sources / "fastfetch-2.69.0"
    cmake = shutil.which("cmake") or sources / "cmake-3.31.6-linux-x86_64/bin/cmake"
    fast_out = output / "fastfetch"
    keep_modules = {"title", "separator", "os", "host", "kernel", "uptime", "shell", "terminal",
                    "cpu", "memory", "swap", "disk", "locale", "break", "colors", "custom", "version"}
    module_flags = [f"-DMODULE_DISABLE_{p.name.upper()}=ON" for p in (fastfetch / "src/modules").iterdir()
                    if p.is_dir() and p.name not in keep_modules]
    optional = re.findall(r'(?:option|cmake_dependent_option)\((ENABLE_[A-Z0-9_]+)',
                          (fastfetch / "CMakeLists.txt").read_text())
    run([cmake, "-S", fastfetch, "-B", fast_out, "-G", "Unix Makefiles",
         "-DCMAKE_SYSTEM_NAME=Linux", "-DCMAKE_SYSTEM_PROCESSOR=riscv64",
         f"-DCMAKE_C_COMPILER={wrapper}", "-DCMAKE_C_FLAGS=-Os", "-DCMAKE_EXE_LINKER_FLAGS=-static",
         "-DCMAKE_BUILD_TYPE=MinSizeRel", "-DIS_MUSL=ON", "-DBINARY_LINK_TYPE=static",
         "-DBUILD_FLASHFETCH=OFF", "-DBUILD_TESTS=OFF", "-DSET_TWEAK=OFF",
         "-DDEFAULT_STRUCTURE=Title:Separator:OS:Host:Kernel:Uptime:CPU:Memory:Shell",
         *[f"-D{name}=OFF" for name in optional], *module_flags],
        log=output / "fastfetch-config.log")
    run([cmake, "--build", fast_out, "--target", "fastfetch", "--clean-first", "--parallel", str(jobs)],
        log=output / "fastfetch-build.log", timeout=900)
    fast_binary = fast_out / "fastfetch"
    verify_elf(fast_binary)
    for binary in (busy_binary, fast_binary):
        run(["riscv64-unknown-elf-strip", "--strip-unneeded", binary])
    manifest = {"isa": "rv64imac", "abi": "lp64", "link": "static musl 1.2.5",
                "host_cmake": subprocess.check_output([cmake, "--version"], text=True).splitlines()[0],
                "archives": ARCHIVES, "binaries": {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)}
                                                        for p in (busy_binary, fast_binary)}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("ROOTFS BINARIES READY: " + str(output), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/fpga/linux-userland")
    parser.add_argument("--jobs", type=int, default=16)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        build(args.out.resolve(), args.jobs)
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"Rootfs build: {error}", file=sys.stderr)
        sys.exit(1)
