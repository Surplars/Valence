#!/usr/bin/env python3
"""Pinned GSIM toolchain and independent new-backend regressions; no Verilator fallback."""

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
BUILD = ROOT / "build/gsim"
SOURCE = ROOT / "simulator/build/gsim-src"
LOCK = json.loads((HERE / "config/toolchain.json").read_text())
OPENSBI_LOCK = json.loads((HERE / "config/opensbi.json").read_text())
OPENSBI_SOURCE = ROOT / "simulator/build/opensbi-v1.9"


def run(args, *, cwd=ROOT, log=None, timeout=600, env=None):
    print("+ " + " ".join(map(str, args)), flush=True)
    if log:
        with log.open("w") as stream:
            result = subprocess.run(list(map(str, args)), cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout, env=env)
        if result.returncode:
            print(log.read_text()[-12000:], file=sys.stderr)
            raise RuntimeError(f"command failed ({result.returncode}); full log: {log}")
    else:
        subprocess.run(list(map(str, args)), cwd=cwd, check=True, timeout=timeout, env=env)


def compiler():
    cxx = os.environ.get("GSIM_CXX", "clang++")
    version = subprocess.check_output([cxx, "--version"], text=True)
    match = re.search(r"clang version (\d+)", version)
    if not match or int(match[1]) < LOCK["minimum_clang_major"]:
        raise RuntimeError("GSIM_CXX must select Clang 19 or newer")
    return cxx, version.splitlines()[0]


def setup(fetch):
    BUILD.mkdir(parents=True, exist_ok=True)
    if not (SOURCE / ".git").exists():
        if not fetch:
            raise RuntimeError("GSIM source missing; run make gsim-setup first (requires network)")
        if SOURCE.exists() and any(SOURCE.iterdir()):
            raise RuntimeError(f"refusing to overwrite nonempty source directory: {SOURCE}")
        SOURCE.mkdir(parents=True, exist_ok=True)
        run(["git", "init", SOURCE])
        run(["git", "remote", "add", "origin", LOCK["repository"]], cwd=SOURCE)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE,
                                           text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        revision = ""
    if not revision and fetch:
        run(["git", "fetch", "--depth=1", "origin", LOCK["revision"]], cwd=SOURCE)
        run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=SOURCE)
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    if revision != LOCK["revision"]:
        raise RuntimeError(f"GSIM revision mismatch: {revision}; expected {LOCK['revision']}")
    changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                      cwd=SOURCE, text=True)
    if changes:
        raise RuntimeError("GSIM checkout has tracked modifications; pinned tests require clean sources")
    cxx, version = compiler()
    run(["make", "-j" + os.environ.get("GSIM_BUILD_JOBS", "4"), f"CXX={cxx}", "build-gsim"],
        cwd=SOURCE, log=BUILD / "toolchain-build.log")
    (BUILD / "toolchain-used.json").write_text(json.dumps({**LOCK, "compiler": version}, indent=2) + "\n")
    return SOURCE / "build/gsim/gsim", cxx


def opensbi_setup(fetch):
    if not (OPENSBI_SOURCE / ".git").exists():
        if not fetch:
            raise RuntimeError("OpenSBI v1.9 source missing; run make gsim-opensbi-setup first")
        if OPENSBI_SOURCE.exists() and any(OPENSBI_SOURCE.iterdir()):
            raise RuntimeError(f"refusing to overwrite nonempty source directory: {OPENSBI_SOURCE}")
        run(["git", "clone", "--depth=1", "--branch", OPENSBI_LOCK["tag"],
             OPENSBI_LOCK["repository"], OPENSBI_SOURCE])
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=OPENSBI_SOURCE, text=True).strip()
    if revision != OPENSBI_LOCK["revision"]:
        raise RuntimeError(f"OpenSBI revision mismatch: {revision}; expected {OPENSBI_LOCK['revision']}")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                               cwd=OPENSBI_SOURCE, text=True):
        raise RuntimeError("OpenSBI checkout has tracked modifications")
    return OPENSBI_SOURCE


def build_opensbi():
    source = opensbi_setup(False)
    output = BUILD / "opensbi-v1.9"
    output.mkdir(parents=True, exist_ok=True)
    dtb = output / "valence.dtb"
    run(["dtc", "-I", "dts", "-O", "dtb", "-o", dtb, HERE / "payloads/opensbi.dts"])
    firmware_build = output / "firmware-build"
    run(["make", "-j" + os.environ.get("OPENSBI_BUILD_JOBS", "4"), "PLATFORM=generic",
         "CROSS_COMPILE=riscv64-linux-gnu-",
         f"PLATFORM_RISCV_ISA={OPENSBI_LOCK['march']}", f"PLATFORM_RISCV_ABI={OPENSBI_LOCK['abi']}",
         "FW_TEXT_START=0x80040000", "FW_JUMP_ADDR=0x80100000",
         "FW_JUMP_FDT_ADDR=0x800c0000", f"FW_FDT_PATH={dtb}", f"O={firmware_build}"],
        cwd=source, log=output / "firmware-build.log")
    firmware = firmware_build / "platform/generic/firmware/fw_jump.bin"
    images = []
    for name in ("reset", "next"):
        stem = output / name
        run(["riscv64-linux-gnu-gcc", f"-march={OPENSBI_LOCK['march']}", "-mabi=lp64",
             "-nostdlib", "-nostartfiles", "-static", "-no-pie", "-Wl,--build-id=none",
             "-Wl,--no-relax", "-T", HERE / f"payloads/opensbi-{name}.ld",
             HERE / f"payloads/opensbi-{name}.S", "-o", stem.with_suffix(".elf")])
        run(["riscv64-linux-gnu-objcopy", "-O", "binary", stem.with_suffix(".elf"),
             stem.with_suffix(".bin")])
        images.append(stem.with_suffix(".bin"))
    if not (0 < images[0].stat().st_size <= 8192 and
            0 < firmware.stat().st_size < 0xb0000 and 0 < images[1].stat().st_size <= 0x10000):
        raise RuntimeError("OpenSBI boot images exceed the ROM or RAM layout")
    return images[0], firmware, images[1]


def test(gsim, cxx, name, main, top, harness, parameters=(), runtime_args=(), defines=None,
         sanitizer=True, timeout=120, interactive=False, run_log="test.log"):
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    run(["mill", "-i", "IonSoC.test.runMain", main, output, *parameters], log=output / "elaborate.log")
    if name.startswith("cached-") and "module SharedReadCache" not in (output / f"{top}.fir").read_text():
        raise RuntimeError("cached target was elaborated without SharedReadCache")
    # GSIM can emit a different number of translation units after a source edit.
    for old in output.glob(top + "[0-9]*.cpp"):
        old.unlink()
    try:
        run([gsim, "--threads=1", f"--dir={output}", output / f"{top}.fir"], log=output / "generate.log")
    except RuntimeError:
        # GSIM can abort with an opaque expression-tree assertion on combinational cycles.
        # Diagnose only a failed emit, so normal focused tests pay no extra tool startup cost.
        cached = sorted((Path.home() / ".cache/llvm-firtool").glob("*/bin/firtool"))
        firtool = os.environ.get("FIRTOOL") or shutil.which("firtool") or (cached[-1] if cached else None)
        if firtool:
            try:
                diagnostic = subprocess.run([str(firtool), str(output / f"{top}.fir"), "--verilog",
                                             "-o", os.devnull], capture_output=True, text=True, timeout=30)
                if diagnostic.returncode and diagnostic.stderr:
                    (output / "firtool-diagnostic.log").write_text(diagnostic.stderr)
                    print(f"firtool circuit diagnosis: {diagnostic.stderr.splitlines()[0]}\n"
                          f"full diagnosis: {output / 'firtool-diagnostic.log'}", file=sys.stderr)
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise
    flags = []
    if defines is not None:
        flags = [f"-D{k}={v}" for k, v in defines.items()]
    elif parameters:
        flags = [f"-DROB_ENTRIES={parameters[0]}", f"-DPHYSICAL_REGS={parameters[1]}",
                 f"-DTAG_BITS={parameters[2]}"]
    run([cxx, "-std=c++20", "-O1" if sanitizer else "-O2", "-g",
         *(["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitizer else []),
         *flags, "-I" + str(output),
         *sorted(output.glob(top + "[0-9]*.cpp")), HERE / "harness" / harness, "-ldl", "-o", output / "run"],
        log=output / "compile.log")
    # LeakSanitizer cannot use ptrace in restricted execution environments; ASan/UBSan remain enabled.
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    if interactive:
        run([output / "run", *runtime_args], env=env, timeout=None)
    else:
        run([output / "run", *runtime_args], env=env, log=output / run_log, timeout=timeout)
        print((output / run_log).read_text(), end="", flush=True)
    return output


def build_c_payload():
    # Build a freestanding C workload using only the currently implemented RV64I subset.
    payload = BUILD / "bare-program"
    run(["riscv64-unknown-elf-gcc", "-march=rv64i", "-mabi=lp64", "-mcmodel=medany", "-mno-relax", "-O2",
         "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
         "-T", HERE / "payloads/bare-program.ld", HERE / "payloads/bare-start.S", HERE / "payloads/bare-memory.c",
         "-o", payload.with_suffix(".elf")], log=BUILD / "bare-program-build.log")
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text", payload.with_suffix(".elf"),
         payload.with_suffix(".bin")], log=BUILD / "bare-program-binary.log")
    return payload.with_suffix(".bin")


COREMARK_SOURCE = ROOT / "simulator/build/coremark-src"
COREMARK_REVISION = "1f483d5b8316753a742cbf5590caf5bd0a4e4777"


def coremark_setup(fetch=False):
    if not (COREMARK_SOURCE / ".git").exists():
        if not fetch:
            raise RuntimeError("CoreMark source missing; run make coremark-setup first")
        COREMARK_SOURCE.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "https://github.com/eembc/coremark.git", COREMARK_SOURCE])
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=COREMARK_SOURCE, text=True).strip()
    changes = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
                                      cwd=COREMARK_SOURCE, text=True)
    if changes:
        raise RuntimeError("CoreMark checkout has tracked modifications")
    if revision != COREMARK_REVISION:
        if not fetch:
            raise RuntimeError(f"CoreMark revision mismatch: {revision}; expected {COREMARK_REVISION}")
        run(["git", "checkout", "--detach", COREMARK_REVISION], cwd=COREMARK_SOURCE)


def build_coremark():
    coremark_setup()
    port = HERE / "payloads/coremark_port"
    payload = BUILD / "coremark"
    sources = [COREMARK_SOURCE / name for name in
               ("core_main.c", "core_list_join.c", "core_matrix.c", "core_state.c", "core_util.c")]
    run(["riscv64-unknown-elf-gcc", "-O2", "-march=rv64imac_zba_zbb_zbs_zicsr", "-mabi=lp64",
         "-mcmodel=medany", "-mno-relax", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
         "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,-Map=" + str(payload.with_suffix(".map")),
         "-I" + str(port), "-I" + str(COREMARK_SOURCE), "-T", port / "link.ld", port / "start.S",
         port / "core_portme.c", *sources, "-lgcc", "-o", payload.with_suffix(".elf")],
        log=BUILD / "coremark-build.log")
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload.with_suffix(".elf"),
         payload.with_suffix(".bin")])
    if payload.with_suffix(".bin").stat().st_size > 16384:
        raise RuntimeError("CoreMark ROM image exceeds 16 KiB")
    return payload.with_suffix(".bin")


def annotate_coremark_hotspots(report, elf):
    hotspots = (report.get("head_stall_hotspots", []) + report.get("store_blocked_load_hotspots", []) +
                report.get("redirect_hotspots", []))
    if not hotspots:
        return
    disassembly = subprocess.check_output(
        ["riscv64-unknown-elf-objdump", "-d", "--no-show-raw-insn", elf], text=True)
    instructions = {}
    for line in disassembly.splitlines():
        match = re.match(r"^\s*([0-9a-f]+):\s+(.+)$", line)
        if match:
            instructions[int(match.group(1), 16)] = match.group(2).strip()
    pcs = [item["pc"] for item in hotspots]
    locations = subprocess.check_output(
        ["riscv64-unknown-elf-addr2line", "-e", elf, "-f", *[hex(pc) for pc in pcs]], text=True)
    symbols = locations.splitlines()[::2]
    if len(symbols) != len(pcs):
        raise RuntimeError("CoreMark hotspot symbol lookup was incomplete")
    for item, symbol in zip(hotspots, symbols):
        item["pc_hex"] = hex(item["pc"])
        item["function"] = symbol
        item["instruction"] = instructions.get(item["pc"], "")


def build_machine_boot(uart=True, dma=False, timer=False, atomic=False, latency=False, split=False,
                       coherent=False):
    BUILD.mkdir(parents=True, exist_ok=True)
    if latency and (uart or dma or timer or atomic):
        raise ValueError("latency firmware is a RAM-only workload")
    if split and (uart or dma or timer or atomic or latency):
        raise ValueError("split-bank firmware is a RAM-only workload")
    if latency:
        name, definitions = "machine-boot-latency", ["-DLATENCY_BOOT=1"]
    elif split:
        name, definitions = "machine-boot-tilelink-split", ["-DTILELINK_SPLIT_BOOT=1"]
    elif atomic:
        name, definitions = "machine-boot-atomic", ["-DATOMIC_BOOT=1", "-DDMA_COPY=1"]
    elif timer:
        name, definitions = "machine-boot-timer", ["-DTIMER_BOOT=1"]
    elif dma:
        name, definitions = "machine-boot-dma", ["-DDMA_COPY=1"]
    elif uart:
        name, definitions = "machine-boot", ["-DUART_CONSOLE=1"]
    else:
        name, definitions = "machine-boot-ram", []
    if coherent:
        if not (dma or atomic):
            raise ValueError("coherent boot variant requires DMA or atomic traffic")
        name += "-coherent"
        definitions.append("-DCOHERENT_DMA_PROBE=1")
        if atomic:
            definitions.append("-DCOHERENT_ATOMIC_PROBE=1")
    payload = BUILD / name
    run(["riscv64-unknown-elf-gcc", *definitions, ("-march=rv64ia_zicsr" if atomic else "-march=rv64i_zicsr"), "-mabi=lp64", "-mcmodel=medany", "-mno-relax", "-O2",
         "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
         "-T", HERE / "payloads/machine-boot.ld", HERE / "payloads/machine-boot.S", HERE / "payloads/machine-boot.c",
         "-o", payload.with_suffix(".elf")], log=BUILD / "machine-boot-build.log")
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload.with_suffix(".elf"), payload.with_suffix(".bin")])
    symbols = {line.split()[2]: line.split()[0] for line in subprocess.check_output(
        ["riscv64-unknown-elf-nm", payload.with_suffix(".elf")], text=True).splitlines() if len(line.split()) == 3}
    image = payload.with_suffix(".bin").read_bytes()
    if len(image) > 8192 or len(image) % 4 or int(symbols["boot_trap"], 16) != 0x80001000:
        raise RuntimeError("invalid machine ROM image layout")
    image = image.ljust(8192, b"\0")
    words = [int.from_bytes(image[i:i+4], "little") for i in range(0, len(image), 4)]
    for bank in range(2):
        (BUILD / f"{payload.name}-bank{bank}.hex").write_text("".join(f"{word:08x}\n" for word in words[bank::2]))
    return ("unused", payload.with_suffix(".bin"), symbols["boot_done"], symbols["boot_trigger"])


def build_sstc_boot():
    BUILD.mkdir(parents=True, exist_ok=True)
    payload = BUILD / "machine-sstc"
    run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
         "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
         HERE / "payloads/machine-sstc.S", "-o", payload.with_suffix(".elf")],
        log=BUILD / "machine-sstc-build.log")
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload.with_suffix(".elf"),
         payload.with_suffix(".bin")])
    symbols = {line.split()[2]: line.split()[0] for line in subprocess.check_output(
        ["riscv64-unknown-elf-nm", payload.with_suffix(".elf")], text=True).splitlines() if len(line.split()) == 3}
    image = payload.with_suffix(".bin").read_bytes()
    if len(image) > 8192 or len(image) % 4 or int(symbols["boot_trap"], 16) != 0x80001000:
        raise RuntimeError("invalid Sstc ROM image layout")
    return ("unused", payload.with_suffix(".bin"), symbols["boot_done"], symbols["boot_trigger"])


def build_privilege_uart_boot():
    BUILD.mkdir(parents=True, exist_ok=True)
    payload = BUILD / "machine-privilege-uart"
    run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
         "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
         HERE / "payloads/machine-privilege-uart.S", "-o", payload.with_suffix(".elf")],
        log=BUILD / "machine-privilege-uart-build.log")
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload.with_suffix(".elf"),
         payload.with_suffix(".bin")])
    symbols = {line.split()[2]: line.split()[0] for line in subprocess.check_output(
        ["riscv64-unknown-elf-nm", payload.with_suffix(".elf")], text=True).splitlines() if len(line.split()) == 3}
    image = payload.with_suffix(".bin").read_bytes()
    if len(image) > 8192 or len(image) % 4 or int(symbols["boot_trap"], 16) != 0x80001000:
        raise RuntimeError("invalid privilege UART ROM image layout")
    return ("unused", payload.with_suffix(".bin"), symbols["boot_done"], symbols["boot_trigger"])


def build_machine_aia_s_uart():
    BUILD.mkdir(parents=True, exist_ok=True)
    payload = BUILD / "machine-aia-s-uart"
    run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
         "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
         HERE / "payloads/machine-aia-s-uart.S", "-o", payload.with_suffix(".elf")],
        log=BUILD / "machine-aia-s-uart-build.log")
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload.with_suffix(".elf"),
         payload.with_suffix(".bin")])
    symbols = {line.split()[2]: line.split()[0] for line in subprocess.check_output(
        ["riscv64-unknown-elf-nm", payload.with_suffix(".elf")], text=True).splitlines() if len(line.split()) == 3}
    image = payload.with_suffix(".bin").read_bytes()
    if len(image) > 8192 or len(image) % 4 or int(symbols["supervisor_trap"], 16) != 0x80001000:
        raise RuntimeError("invalid S UART ROM image layout")
    return payload.with_suffix(".bin"), symbols["supervisor_wait"], symbols["boot_done"], symbols["boot_fail"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["ram-range", "cache-core", "cache-platform", "cache", "atomic-core", "atomic", "atomic-memory8", "atomic8-platform", "timer", "dma", "shared-data", "uart", "aia-supervisor-uart", "machine-aia-s-uart", "machine-boot", "machine-platform", "machine-platform-memory8", "machine-platform-latency", "tilelink-dual-latency", "tilelink-platform", "tilelink-platform-flow", "tilelink-split-platform", "tilelink-dual-platform", "tilelink-dual-split-platform", "tilelink-dual-split-coherent", "tilelink-coherent-platform", "tilelink-coherent-evict", "tilelink-coherent-fencei", "tilelink-two-hart-coherent", "tilelink-burst-ram", "tilelink-line-fill", "tilelink-line-write", "tilelink-line-probe", "tilelink-line-acquire", "tilelink-fetch", "tilelink-crossbar", "tilelink-router", "tilelink-arbiter", "delayed-ram", "axi-bridge", "tilelink-bridge", "tilelink-bridge-flow", "tilelink-axi4-bridge", "sstc-platform", "privilege-uart-platform", "pmp-fetch-platform", "pmp", "sv-walker", "soc-translation", "vm-data-platform", "vm-data-coherent-platform", "vm-data-compact-coherent-platform", "vm-data-compact-coherent-buffered-platform", "vm-data-compact-coherent-registered-platform", "vm-instruction-platform", "vm-instruction-coherent-platform", "vm-instruction-wide", "opensbi-setup", "opensbi-platform", "opensbi-console", "coremark-setup", "coremark", "coremark-tune", "issue-peak-4", "coremark-cache", "coremark-coherent", "coremark-delay12", "coremark-cache-delay12", "coremark-coherent-delay12", "setup", "smoke", "muldiv", "pipelined-mul", "imsic", "aplic", "wired-machine", "mapped-machine", "router", "machine", "backend", "backend-recovery4", "backend-recovery8", "backend-recovery16", "backend-move-alias", "integer", "predictor", "store-buffer", "store-buffer-registered", "fpga-fetch", "instruction-cache", "instruction-line-cache", "instruction-ipc", "platform", "core", "core-memory8", "core-branch-pipeline", "core-fast-store", "core-fast-memory", "core-move-alias", "core-word-bypass", "core-indirect", "ipc", "test"])
    parser.add_argument("--rob", type=int, default=32)
    parser.add_argument("--burst", action="store_true", help="test the direct TL-to-AXI4 INCR burst path")
    parser.add_argument("--burst-beats", type=int, choices=(16, 256), default=16)
    parser.add_argument("--axi-address-width", type=int, choices=(32, 64), default=64)
    parser.add_argument("--issue-width", type=int, choices=(2, 4), default=2)
    parser.add_argument("--instruction-cache-lines", type=int, choices=(0, 16, 32, 64, 128, 256, 512), default=32)
    parser.add_argument("--frontend-cache-sets", type=int, choices=(64, 128, 256))
    parser.add_argument("--compressed-body", action="store_true")
    parser.add_argument("--long-body", action="store_true")
    parser.add_argument("--instruction-prefetch", action="store_true")
    parser.add_argument("--ram-delay", type=int, choices=(0, 4, 12), default=0)
    parser.add_argument("--rename-width", type=int, choices=(2, 4))
    parser.add_argument("--commit-width", type=int, choices=(2, 4))
    parser.add_argument("--physical", type=int, default=64)
    parser.add_argument("--memory-entries", type=int, default=4)
    parser.add_argument("--store-buffer-entries", type=int, default=4)
    parser.add_argument("--completion-width", type=int, choices=(2, 4))
    parser.add_argument("--flow-tilelink-response", action="store_true")
    parser.add_argument("--fast-buffered-store-retire", action="store_true")
    parser.add_argument("--fast-head-load-retire", action="store_true")
    parser.add_argument("--load-completion-bypass", action="store_true")
    parser.add_argument("--move-alias", action="store_true")
    parser.add_argument("--word-bypass", action="store_true")
    parser.add_argument("--indirect-entries", type=int, choices=(0, 16, 32, 64), default=0)
    parser.add_argument("--branch-entries", type=int, choices=(64, 128, 256), default=256)
    parser.add_argument("--recovery-width", type=int, choices=(1, 2, 4, 8, 16), default=4)
    parser.add_argument("--registered-owners", action="store_true")
    parser.add_argument("--registered-physical-owners", action="store_true",
                        help="cut physical arbiter/atomic empty-owner response flow (focused IP/VM tests)")
    parser.add_argument("--registered-local-response", action="store_true")
    parser.add_argument("--registered-memory-requests", action="store_true")
    parser.add_argument("--registered-memory-address", action="store_true")
    parser.add_argument("--registered-retirement", action="store_true")
    parser.add_argument("--registered-load-replay", action="store_true")
    parser.add_argument("--early-recovery-issue-block", action="store_true")
    parser.add_argument("--precomplete-mispredicted-branch", action="store_true")
    args = parser.parse_args()
    if args.registered_physical_owners and args.action not in (
            "atomic", "atomic-memory8", "shared-data", "vm-data-compact-coherent-buffered-platform"):
        parser.error("--registered-physical-owners supports atomic/shared-data or compact buffered VM data only")
    if args.registered_retirement and args.action != "vm-data-compact-coherent-buffered-platform" and not (
            args.registered_memory_address and args.registered_owners):
        parser.error("registered retirement comparison requires the combined memory boundaries")
    if args.early_recovery_issue_block and args.action not in (
            "core-branch-pipeline", "vm-data-compact-coherent-buffered-platform"):
        parser.error("early recovery issue blocking requires a registered-branch comparison target")
    if args.precomplete_mispredicted_branch and (args.action not in (
            "core-branch-pipeline", "vm-data-compact-coherent-buffered-platform") or
            not args.registered_retirement):
        parser.error("precompleted branches require a registered-retirement comparison target")
    if args.registered_load_replay and (args.action not in (
            "core-branch-pipeline", "vm-data-compact-coherent-buffered-platform") or
            not args.registered_retirement or not args.early_recovery_issue_block or
            (args.action == "core-branch-pipeline" and not args.registered_memory_address)):
        parser.error("registered load replay requires staged memory, retirement and early recovery blocking")
    if args.registered_local_response and args.action not in (
            "core-branch-pipeline", "vm-data-compact-coherent-buffered-platform"):
        parser.error("registered local responses require a buffered comparison target")
    if args.registered_memory_requests and args.action not in (
            "core-branch-pipeline", "vm-data-compact-coherent-buffered-platform"):
        parser.error("registered memory requests require a buffered comparison target")
    frontend_cache_sets = (args.frontend_cache_sets if args.frontend_cache_sets is not None else
                           (128 if (args.rename_width or args.issue_width) >= 4 else 64))
    if args.action == "aia-supervisor-uart":
        gsim, cxx = setup(False)
        test(gsim, cxx, "aia-supervisor-uart", "ip.AiaSupervisorUartGsimMain",
             "AiaSupervisorUartGsim", "aia_supervisor_uart.cpp", sanitizer=False)
        return
    if args.action == "machine-aia-s-uart":
        gsim, cxx = setup(False)
        test(gsim, cxx, "machine-aia-s-uart", "ooo.MachineCoreGsimMain", "MachineCoreGsim",
             "machine_aia_s_uart.cpp", parameters=(32, 64, 64, "synchronous"),
             runtime_args=build_machine_aia_s_uart())
        return
    if args.action == "instruction-ipc":
        if args.compressed_body and args.long_body:
            raise ValueError("long instruction IPC body currently uses 32-bit instructions")
        gsim, cxx = setup(False)
        name = f"instruction-ipc-w{args.issue_width}-l{args.instruction_cache_lines}" + (
            "-packed" if args.compressed_body else "") + (
            "-long" if args.long_body else "") + (
            f"-f{frontend_cache_sets}-d{args.ram_delay}")
        test(gsim, cxx, name, "ooo.MachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
             parameters=(32, 64, 64, "tilelink-dual", 4, args.ram_delay, args.instruction_cache_lines,
                         args.issue_width, "compressed", frontend_cache_sets),
             runtime_args=("--instruction-ipc", args.issue_width, args.instruction_cache_lines,
                           frontend_cache_sets,
                           *(("packed",) if args.compressed_body else
                             ("long",) if args.long_body else ())),
             defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1}, sanitizer=False, timeout=120)
        return
    if args.action == "opensbi-setup":
        opensbi_setup(True)
        return
    if args.action == "coremark-setup":
        coremark_setup(fetch=True)
        return
    if args.action == "issue-peak-4":
        gsim, cxx = setup(False)
        test(gsim, cxx, "issue-peak-4", "ooo.CoremarkPlatformGsimMain", "CoremarkPlatformGsim",
             "issue_peak.cpp", parameters=("direct", "0", "4", "4", "32", "64", "4", "4", "4",
                                           "flow-response", "fast-store", "fast-load", "256", "8"),
             defines={"ROB_ENTRIES": 32}, sanitizer=False)
        return
    if args.action in ("coremark", "coremark-tune", "coremark-cache", "coremark-coherent", "coremark-delay12", "coremark-cache-delay12", "coremark-coherent-delay12"):
        payload = build_coremark()
        gsim, cxx = setup(False)
        cached = "cache" in args.action
        coherent = "coherent" in args.action
        ram_delay = 12 if args.action.endswith("delay12") else 0
        variant = ("-coherent" if coherent else "-cache" if cached else "") + ("-delay12" if ram_delay else "")
        tuned = args.action == "coremark-tune"
        config = (args.rename_width or args.issue_width, args.commit_width or args.issue_width,
                  args.rob, args.physical, args.memory_entries, args.store_buffer_entries,
                  args.completion_width or args.issue_width) if tuned else (2, 2, 32, 64, 4, 4, 2)
        if tuned:
            variant += "-n{}-c{}-r{}-p{}-m{}-s{}-x{}".format(*config)
            if args.flow_tilelink_response:
                variant += "-flow-response"
            if args.fast_buffered_store_retire:
                variant += "-fast-store"
            if args.fast_head_load_retire:
                variant += "-fast-load"
            if args.load_completion_bypass:
                variant += "-load-bypass"
            if args.move_alias:
                variant += "-move-alias"
            if args.word_bypass:
                variant += "-word-bypass"
            if args.indirect_entries:
                variant += f"-indirect{args.indirect_entries}"
            if frontend_cache_sets != 64:
                variant += f"-fetch{frontend_cache_sets}"
            variant += f"-b{args.branch_entries}-w{args.recovery_width}"
        output = test(gsim, cxx, "coremark" + variant + "-platform",
                      "ooo.CoremarkPlatformGsimMain", "CoremarkPlatformGsim", "coremark_platform.cpp",
                      parameters=("coherent" if coherent else "cache" if cached else "direct", str(ram_delay),
                                  *map(str, config), "flow-response" if tuned and args.flow_tilelink_response else "plain",
                                  "fast-store" if tuned and args.fast_buffered_store_retire else "plain",
                                  "fast-load" if tuned and args.fast_head_load_retire else "plain",
                                  str(args.branch_entries if tuned else 256),
                                  str(args.recovery_width if tuned else 4),
                                  "load-bypass" if tuned and args.load_completion_bypass else "plain",
                                  "move-alias" if tuned and args.move_alias else "plain",
                                  "word-bypass" if tuned and args.word_bypass else "plain",
                                  str(args.indirect_entries if tuned else 0),
                                  str(frontend_cache_sets if tuned else 64)),
                      runtime_args=(payload,), defines={"ROB_ENTRIES": config[2]},
                      sanitizer=False, timeout=600)
        match = re.search(r"^COREMARK (\{.*\})$", (output / "test.log").read_text(), re.MULTILINE)
        if not match:
            raise RuntimeError("CoreMark output record missing")
        report = {"source_revision": COREMARK_REVISION, "march": "rv64imac_zba_zbb_zbs_zicsr",
                  "iterations": 1, "reportable_score": False, "shared_read_cache": cached,
                  "coherent_line_cache": coherent,
                  "shared_read_cache_lines": 128 if cached else 0, "ram_response_delay": ram_delay,
                  "rename_width": config[0], "commit_width": config[1], "completion_width": config[6],
                  "rob_entries": config[2], "physical_regs": config[3],
                  "memory_entries": config[4], "store_buffer_entries": config[5],
                  "flow_tilelink_response": tuned and args.flow_tilelink_response,
                  "fast_buffered_store_retire": tuned and args.fast_buffered_store_retire,
                  "fast_head_load_retire": tuned and args.fast_head_load_retire,
                  "load_completion_bypass": tuned and args.load_completion_bypass,
                  "move_alias": tuned and args.move_alias,
                  "mul_word_preview_bypass": tuned and args.word_bypass,
                  "indirect_target_entries": args.indirect_entries if tuned else 0,
                  "frontend_cache_sets": frontend_cache_sets if tuned else 64,
                  "branch_predictor_entries": args.branch_entries if tuned else 256,
                  "recovery_width": args.recovery_width if tuned else 4,
                  **json.loads(match.group(1))}
        annotate_coremark_hotspots(report, payload.with_suffix(".elf"))
        (BUILD / ("coremark" + variant + ".json")).write_text(
            json.dumps(report, indent=2) + "\n")
        return
    if args.action == "machine-boot":
        build_machine_boot()
        return
    gsim, cxx = setup(args.action == "setup")
    if args.action in ("tilelink-two-hart-coherent", "test"):
        test(gsim, cxx, "two-hart-coherent", "ooo.TwoHartCoherentGsimMain",
             "TwoHartCoherentGsim", "two_hart_coherent.cpp", defines={}, sanitizer=False)
        if args.action == "tilelink-two-hart-coherent":
            return
    if args.action in ("opensbi-platform", "opensbi-console"):
        images = build_opensbi()
        test(gsim, cxx, "opensbi-platform", "ooo.OpenSbiPlatformGsimMain",
             "OpenSbiPlatformGsim", "opensbi_platform.cpp",
             runtime_args=(*images, "--console") if args.action == "opensbi-console" else images,
             defines={}, sanitizer=False, timeout=None if args.action == "opensbi-console" else 180,
             interactive=args.action == "opensbi-console")
        return
    if args.action == "tilelink-coherent-fencei":
        test(gsim, cxx, args.action, "ooo.MachineCoreGsimMain",
             "MachineCoreGsim", "machine.cpp",
             parameters=(32, 64, 64, "tilelink-coherent-evict", 4, 0, 16),
             runtime_args=("--ram-exec",),
             defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1,
                      "COHERENT_FENCEI": 1}, timeout=120)
        return
    if args.action in ("tilelink-coherent-platform", "tilelink-coherent-evict",
                       "tilelink-dual-split-coherent"):
        evict = args.action == "tilelink-coherent-evict"
        split = args.action == "tilelink-dual-split-coherent"
        output = test(gsim, cxx, args.action, "ooo.MachineCoreGsimMain",
                      "MachineCoreGsim", "machine.cpp",
                      parameters=(32, 64, 64, "tilelink-dual-split-coherent" if split else
                                  "tilelink-coherent-evict" if evict else "tilelink-coherent"),
                      runtime_args=(*build_machine_boot(uart=False, split=True), "--external-irq")
                          if split else build_machine_boot(),
                      defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1,
                               "SPLIT_COHERENT": int(split)}, timeout=240)
        for name, runtime in (("dma", (*build_machine_boot(uart=False, dma=True, coherent=True), "--dma")),
                              ("atomic", (*build_machine_boot(uart=False, atomic=True, coherent=True), "--atomic"))):
            run([output / "run", *runtime], log=output / f"{name}-boot.log",
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=240)
            print((output / f"{name}-boot.log").read_text(), end="", flush=True)
        log = (output / "dma-boot.log").read_text()
        releases = [int(value) for value in re.findall(r"COHERENCE releaseDataBeats=(\d+)", log)]
        probes = [int(value) for value in re.findall(r"probeAckDataBeats=(\d+)", log)]
        if evict and (len(releases) != 3 or min(releases) < 8):
            raise RuntimeError("small-cache regression did not exercise dirty ReleaseData eviction")
        if not evict and (len(probes) != 3 or min(probes) < 8):
            raise RuntimeError("full-cache regression did not exercise dirty DMA ProbeAckData")
        return
    if args.action in ("tilelink-line-fill", "test"):
        test(gsim, cxx, "tilelink-line-fill", "ooo.TileLinkLineFillGsimMain",
             "TileLinkLineFillGsim", "line_fill.cpp", defines={})
        test(gsim, cxx, "tilelink-line-fill-ram", "ooo.TileLinkLineFillRamGsimMain",
             "TileLinkLineFillRamGsim", "line_fill_ram.cpp", defines={})
        if args.action == "tilelink-line-fill":
            return
    if args.action in ("tilelink-line-write", "test"):
        test(gsim, cxx, "tilelink-line-write", "ooo.TileLinkLineWriteGsimMain",
             "TileLinkLineWriteGsim", "line_write.cpp", defines={})
        test(gsim, cxx, "tilelink-line-rw", "ooo.TileLinkLineReadWriteRamGsimMain",
             "TileLinkLineReadWriteRamGsim", "line_read_write_ram.cpp", defines={})
        if args.action == "tilelink-line-write":
            return
    if args.action in ("tilelink-line-probe", "test"):
        output = test(gsim, cxx, "tilelink-line-probe", "ooo.TileLinkLineProbeGsimMain",
                      "TileLinkLineProbeGsim", "line_probe.cpp", defines={})
        log = output / "invalid-c-interleave.log"
        with log.open("w") as stream:
            result = subprocess.run([output / "run", "--inject-interleave"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "line probe C burst interleaved or changed source" not in log.read_text():
            raise RuntimeError("interleaved TileLink C burst was not rejected")
        print("GSIM TileLink line probe malformed C burst: PASS", flush=True)
        if args.action == "tilelink-line-probe":
            return
    if args.action in ("tilelink-line-acquire", "test"):
        output = test(gsim, cxx, "tilelink-line-acquire", "ooo.TileLinkLineAcquireGsimMain",
                      "TileLinkLineAcquireGsim", "line_acquire.cpp", defines={})
        log = output / "invalid-d-interleave.log"
        with log.open("w") as stream:
            result = subprocess.run([output / "run", "--inject-interleave"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "line acquire D burst interleaved or changed source" not in log.read_text():
            raise RuntimeError("interleaved TileLink GrantData burst was not rejected")
        print("GSIM TileLink line acquire malformed D burst: PASS", flush=True)
        if args.action == "tilelink-line-acquire":
            return
    if args.action in ("atomic8-platform", "test"):
        payload = BUILD / "atomic8-platform"
        run(["riscv64-unknown-elf-gcc", "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax",
             "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/integer-program.ld",
             HERE / "payloads/atomic8-platform.S", "-o", payload.with_suffix(".elf")],
            log=BUILD / "atomic8-platform-build.log")
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
             payload.with_suffix(".elf"), payload.with_suffix(".bin")])
        image = payload.with_suffix(".bin")
        image.write_bytes(image.read_bytes().ljust((image.stat().st_size + 3) & ~3, b"\0"))
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-g", payload.with_suffix(".elf")], text=True)
        fault_pc = next(int(line.split()[0], 16) for line in symbols.splitlines()
                        if line.split()[-1] == "atomic8_fault")
        test(gsim, cxx, "atomic8-platform", "ooo.Atomic8PlatformGsimMain", "Atomic8PlatformGsim",
             "atomic8_platform.cpp", runtime_args=(image, hex(fault_pc)), sanitizer=False)
        if args.action == "atomic8-platform":
            return
    if args.action in ("sv-walker", "test"):
        test(gsim, cxx, "sv-walker", "ooo.SvWalkerGsimMain", "SvWalkerGsim", "sv_walker.cpp",
             parameters=("5",), defines={})
        if args.action == "sv-walker":
            return
    if args.action in ("soc-translation", "test"):
        test(gsim, cxx, "translation-platform", "ooo.TranslationPlatformGsimMain",
             "TranslationPlatformGsim", "translation_platform.cpp")
        if args.action == "soc-translation":
            return
    if args.action in ("vm-data-platform", "vm-data-coherent-platform",
                       "vm-data-compact-coherent-platform",
                       "vm-data-compact-coherent-buffered-platform",
                       "vm-data-compact-coherent-registered-platform", "test"):
        coherent = args.action in ("vm-data-coherent-platform",
                                   "vm-data-compact-coherent-platform",
                                   "vm-data-compact-coherent-buffered-platform",
                                   "vm-data-compact-coherent-registered-platform")
        compact = args.action in ("vm-data-compact-coherent-platform",
                                  "vm-data-compact-coherent-buffered-platform",
                                  "vm-data-compact-coherent-registered-platform")
        buffered = args.action in ("vm-data-compact-coherent-buffered-platform",
                                   "vm-data-compact-coherent-registered-platform")
        registered = args.action == "vm-data-compact-coherent-registered-platform" or args.registered_local_response
        payload = BUILD / "vm-data"
        run(["riscv64-unknown-elf-gcc", "-march=rv64ia_zicsr", "-mabi=lp64", "-mno-relax",
             "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
             HERE / "payloads/vm-data.S", "-o", payload.with_suffix(".elf")],
            log=BUILD / "vm-data-build.log")
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
             payload.with_suffix(".elf"), payload.with_suffix(".bin")])
        vm_name = args.action if coherent else "vm-data-platform"
        if args.early_recovery_issue_block:
            vm_name += "-early-recovery"
        if args.registered_retirement:
            vm_name += "-retirement"
        if args.precomplete_mispredicted_branch:
            vm_name += "-precomplete-branch"
        if args.registered_load_replay:
            vm_name += "-registered-load-replay"
        if args.registered_local_response:
            vm_name += "-registered-local-response"
        if args.registered_memory_requests:
            vm_name += "-registered-memory-requests"
        if args.registered_physical_owners:
            vm_name += "-registered-physical-owners"
        test(gsim, cxx, vm_name, "ooo.VmDataPlatformGsimMain",
             "VmDataPlatformGsim", "vm_data_platform.cpp",
             parameters=tuple(name for name, enabled in (("coherent", coherent), ("compact", compact),
                                                          ("buffered-response", buffered),
                                                          ("registered-local-response", registered),
                                                          ("registered-memory-requests", args.registered_memory_requests),
                                                          ("registered-physical-owners", args.registered_physical_owners),
                                                          ("early-recovery-issue-block", args.early_recovery_issue_block),
                                                          ("registered-retirement", args.registered_retirement),
                                                          ("registered-load-replay", args.registered_load_replay),
                                                          ("precomplete-mispredicted-branch", args.precomplete_mispredicted_branch)) if enabled),
             runtime_args=(payload.with_suffix(".bin"), "--coherent") if coherent else
                (payload.with_suffix(".bin"),), defines={})
        if args.action in ("vm-data-platform", "vm-data-coherent-platform",
                           "vm-data-compact-coherent-platform",
                           "vm-data-compact-coherent-buffered-platform",
                           "vm-data-compact-coherent-registered-platform"):
            return
    if args.action in ("vm-instruction-platform", "vm-instruction-coherent-platform", "vm-instruction-wide", "test"):
        coherent = args.action == "vm-instruction-coherent-platform"
        wide = args.action == "vm-instruction-wide"
        images = []
        for suffix, definitions in (("", []), ("-cross", ["-DCROSS_PAGE=1"])):
            payload = BUILD / ("vm-instruction" + suffix)
            run(["riscv64-unknown-elf-gcc", *definitions, "-march=rv64imac_zicsr", "-mabi=lp64", "-mno-relax",
                 "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T", HERE / "payloads/machine-boot.ld",
                 HERE / "payloads/vm-instruction.S", "-o", payload.with_suffix(".elf")],
                log=BUILD / (payload.name + "-build.log"))
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text",
                 payload.with_suffix(".elf"), payload.with_suffix(".bin")])
            binary = payload.with_suffix(".bin")
            image = binary.read_bytes()
            binary.write_bytes(image.ljust((len(image) + 3) & ~3, b"\0"))
            images.append(binary)
        test(gsim, cxx, args.action if (coherent or wide) else "vm-instruction-platform", "ooo.VmInstructionPlatformGsimMain",
             "VmInstructionPlatformGsim", "vm_instruction_platform.cpp",
             parameters=("coherent",) if coherent else ("wide",) if wide else (),
             runtime_args=images, defines={})
        if args.action in ("vm-instruction-platform", "vm-instruction-coherent-platform", "vm-instruction-wide"):
            return
    if args.action in ("ram-range", "test"):
        output = test(gsim, cxx, "ram-range", "soc.core.ooo.SpeculativeRamRangeGsimMain",
                      "SpeculativeRamRangeGsim", "speculative_ram_range.cpp")
        result = subprocess.run([output / "run", "--inject-mismatch"], capture_output=True, text=True,
                                timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "range oracle mismatch" not in result.stderr:
            raise RuntimeError("range oracle negative test failed")
        print("GSIM range oracle mismatch injection: PASS", flush=True)
        if args.action == "ram-range":
            return
    if args.action in ("pmp", "test"):
        output = test(gsim, cxx, "pmp", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim", "pmp_checker.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "PMP oracle mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("PMP oracle negative test failed")
        print("GSIM PMP oracle mismatch injection: PASS", flush=True)
        if args.action == "pmp":
            return
    if args.action == "delayed-ram":
        test(gsim, cxx, "delayed-ram", "ooo.DelayedRamGsimMain", "SynchronousDataRam", "delayed_ram.cpp")
        test(gsim, cxx, "delayed-ram-pipeline3", "ooo.DelayedRamGsimMain", "SynchronousDataRam",
             "delayed_ram.cpp", parameters=(3,), defines={})
        return
    if args.action == "axi-bridge":
        output = test(gsim, cxx, "axi-bridge", "ooo.OrderedAxi4BridgeGsimMain", "OrderedAxi4Bridge",
                      "axi_bridge.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "bridge response data, error or order mismatch" not in (
                output / "negative-test.log").read_text():
            raise RuntimeError("AXI bridge reference mismatch injection was not detected")
        print("GSIM AXI bridge mismatch injection: PASS", flush=True)
        with (output / "write-error-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-write-error"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "AXI memory window must guarantee successful writes" not in (
                output / "write-error-test.log").read_text():
            raise RuntimeError("AXI write-error assertion was not detected")
        print("GSIM AXI bridge write-error assertion: PASS", flush=True)
        return
    if args.action == "tilelink-axi4-bridge":
        if args.burst:
            long_burst = args.burst_beats == 256
            name = "tilelink-axi4-burst256" if long_burst else (
                "tilelink-axi4-burst32" if args.axi_address_width == 32 else "tilelink-axi4-burst")
            output = test(gsim, cxx, name,
                          "ooo.TileLinkAxi4BridgeGsimMain",
                          "TileLinkAxi4Bridge", "tilelink_axi4_burst.cpp",
                          parameters=(str(args.axi_address_width), "4", "burst", str(args.burst_beats)),
                          runtime_args=("--long-burst",) if long_burst else (),
                          defines={}, timeout=240 if long_burst else 120)
            if long_burst:
                return
            if args.axi_address_width == 32:
                with (output / "high-address.log").open("w") as stream:
                    result = subprocess.run([output / "run", "--high-address"], stdout=stream,
                                            stderr=subprocess.STDOUT, timeout=120,
                                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                if result.returncode == 0 or "AXI address truncation" not in (
                        output / "high-address.log").read_text():
                    raise RuntimeError("32-bit burst bridge accepted a truncated TL address")
                print("GSIM TL-AXI4 burst 32-bit address rejection: PASS", flush=True)
            with (output / "bad-rlast.log").open("w") as stream:
                result = subprocess.run([output / "run", "--bad-rlast"], stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=120,
                                        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            if result.returncode == 0 or "AXI read ID or RLAST mismatch" not in (
                    output / "bad-rlast.log").read_text():
                raise RuntimeError("AXI RLAST protocol assertion was not detected")
            print("GSIM TL-AXI4 malformed RLAST rejection: PASS", flush=True)
            return
        output = test(gsim, cxx, "tilelink-axi4-bridge", "ooo.TileLinkAxi4BridgeGsimMain",
                      "TileLinkAxi4Bridge", "tilelink_axi4_bridge.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "TileLink-to-AXI response data, source or order mismatch" not in (
                output / "negative-test.log").read_text():
            raise RuntimeError("TileLink-to-AXI reference mismatch injection was not detected")
        print("GSIM TileLink-to-AXI4 mismatch injection: PASS", flush=True)
        narrow = test(gsim, cxx, "tilelink-axi4-bridge32", "ooo.TileLinkAxi4BridgeGsimMain",
                      "TileLinkAxi4Bridge", "tilelink_axi4_bridge.cpp",
                      parameters=("32",), defines={})
        with (narrow / "high-address-test.log").open("w") as stream:
            result = subprocess.run([narrow / "run", "--high-address"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "AXI address truncation" not in (
                narrow / "high-address-test.log").read_text():
            raise RuntimeError("32-bit AXI bridge failed to reject a truncated address")
        print("GSIM TileLink-to-AXI4 32-bit address rejection: PASS", flush=True)
        write_log = output / "write-stream.log"
        run([output / "run", "--write-stream"], log=write_log,
            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
        print(write_log.read_text(), end="", flush=True)
        baseline = test(gsim, cxx, "tilelink-axi4-bridge-write1", "ooo.TileLinkAxi4BridgeGsimMain",
                        "TileLinkAxi4Bridge", "tilelink_axi4_bridge.cpp",
                        parameters=("64", "1"), runtime_args=("--write-stream",),
                        defines={"MAX_WRITES": 1})
        stream_pattern = r"write stream: PASS writes=256 cycles=(\d+) peakWrites=(\d+)"
        optimized = re.search(stream_pattern, write_log.read_text())
        reference = re.search(stream_pattern, (baseline / "test.log").read_text())
        if not optimized or not reference or int(optimized[2]) != 4 or int(reference[2]) != 1 or (
                int(optimized[1]) >= int(reference[1])):
            raise RuntimeError("pipelined AXI writes did not improve the matched write stream")
        (BUILD / "tilelink-axi4-write-stream.json").write_text(json.dumps({
            "requests": 256, "max_writes_1_cycles": int(reference[1]),
            "max_writes_4_cycles": int(optimized[1])
        }, indent=2) + "\n")
        return
    if args.action == "tilelink-bridge-flow":
        test(gsim, cxx, "tilelink-bridge-mixed-flow", "ooo.OrderedTileLinkBridgeGsimMain",
             "OrderedTileLinkBridge", "tilelink_bridge.cpp", parameters=("mixed", "flow"),
             defines={"ORDERED_WRITES": 1, "ALLOW_WRITE_ERRORS": 1, "MIXED_ACCESSES": 1,
                      "FLOW_HEAD_RESPONSE": 1})
        return
    if args.action == "tilelink-bridge":
        output = test(gsim, cxx, "tilelink-bridge", "ooo.OrderedTileLinkBridgeGsimMain",
                      "OrderedTileLinkBridge", "tilelink_bridge.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "TileLink bridge response data, error or order mismatch" not in (
                output / "negative-test.log").read_text():
            raise RuntimeError("TileLink bridge reference mismatch injection was not detected")
        print("GSIM TileLink bridge mismatch injection: PASS", flush=True)
        test(gsim, cxx, "tilelink-bridge-ordered-writes", "ooo.OrderedTileLinkBridgeGsimMain",
             "OrderedTileLinkBridge", "tilelink_bridge.cpp", parameters=("ordered",),
             defines={"ORDERED_WRITES": 1, "ALLOW_WRITE_ERRORS": 1})
        test(gsim, cxx, "tilelink-bridge-mixed", "ooo.OrderedTileLinkBridgeGsimMain",
             "OrderedTileLinkBridge", "tilelink_bridge.cpp", parameters=("mixed",),
             defines={"ORDERED_WRITES": 1, "ALLOW_WRITE_ERRORS": 1, "MIXED_ACCESSES": 1})
        test(gsim, cxx, "tilelink-bridge-banked-writes", "ooo.OrderedTileLinkBridgeGsimMain",
             "OrderedTileLinkBridge", "tilelink_bridge.cpp", parameters=("banked",),
             defines={"BANKED_WRITES": 1})
        return
    if args.action == "tilelink-router":
        output = test(gsim, cxx, "tilelink-router", "ip.TileLinkRouterGsimMain",
                      "TileLinkRouterGsim", "tilelink_router.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "TileLink router response data, source or route mismatch" not in (
                output / "negative-test.log").read_text():
            raise RuntimeError("TileLink router mismatch injection was not detected")
        print("GSIM TileLink router mismatch injection: PASS", flush=True)
        with (output / "wrong-owner-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-wrong-owner"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "TileLink bank response has no matching source" not in (
                output / "wrong-owner-test.log").read_text():
            raise RuntimeError("TileLink router wrong-bank response was not rejected")
        print("GSIM TileLink router wrong-owner injection: PASS", flush=True)
        return
    if args.action == "tilelink-arbiter":
        output = test(gsim, cxx, "tilelink-arbiter", "ip.TileLinkArbiterGsimMain",
                      "TileLinkArbiterGsim", "tilelink_arbiter.cpp")
        for argument, diagnostic in (("--inject-mismatch", "TileLink arbiter response data, source or destination mismatch"),
                                     ("--inject-wrong-source", "Two-master TileLink response has no matching source")):
            log = output / (argument[2:] + ".log")
            with log.open("w") as stream:
                result = subprocess.run([output / "run", argument], stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=120,
                                        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            if result.returncode == 0 or diagnostic not in log.read_text():
                raise RuntimeError(f"TileLink arbiter negative check failed: {argument}")
            print(f"GSIM TileLink arbiter {argument[2:]}: PASS", flush=True)
        return
    if args.action == "tilelink-fetch":
        output = test(gsim, cxx, "tilelink-fetch", "ooo.InstructionTileLinkBridgeGsimMain",
                      "InstructionTileLinkBridge", "tilelink_fetch.cpp")
        for argument, diagnostic in (("--inject-mismatch", "TileLink fetch packet data or alignment mismatch"),
                                     ("--inject-wrong-source", "instruction TileLink response has no matching Get")):
            log = output / (argument[2:] + ".log")
            with log.open("w") as stream:
                result = subprocess.run([output / "run", argument], stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=120,
                                        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            if result.returncode == 0 or diagnostic not in log.read_text():
                raise RuntimeError(f"TileLink fetch negative check failed: {argument}")
            print(f"GSIM TileLink fetch {argument[2:]}: PASS", flush=True)
        return
    if args.action == "tilelink-crossbar":
        output = test(gsim, cxx, "tilelink-crossbar", "ip.TileLinkCrossbarGsimMain",
                      "TileLinkCrossbarGsim", "tilelink_crossbar.cpp")
        for argument, diagnostic in (("--inject-mismatch", "TileLink crossbar D source, data or owner mismatch"),
                                     ("--inject-wrong-source", "Two-master TileLink response has no matching source")):
            log = output / (argument[2:] + ".log")
            with log.open("w") as stream:
                result = subprocess.run([output / "run", argument], stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=120,
                                        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            if result.returncode == 0 or diagnostic not in log.read_text():
                raise RuntimeError(f"TileLink crossbar negative check failed: {argument}")
            print(f"GSIM TileLink crossbar {argument[2:]}: PASS", flush=True)
        test(gsim, cxx, "tilelink-crossbar-burst", "ip.TileLinkCrossbarGsimMain",
             "TileLinkCrossbarGsim", "tilelink_burst.cpp")
        return
    if args.action == "tilelink-burst-ram":
        output = test(gsim, cxx, "tilelink-burst-ram", "ooo.TileLinkBurstRamGsimMain",
                      "TileLinkBurstRamGsim", "tilelink_burst_ram.cpp")
        log = output / "invalid-burst-control.log"
        with log.open("w") as stream:
            result = subprocess.run([output / "run", "--inject-control"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "PutFullData burst changed control, source or mask" not in log.read_text():
            raise RuntimeError("malformed TileLink burst was not rejected")
        print("GSIM TileLink burst RAM malformed control: PASS", flush=True)
        test(gsim, cxx, "tilelink-split-burst-ram", "ooo.TileLinkSplitBurstRamGsimMain",
             "TileLinkSplitBurstRamGsim", "tilelink_burst_ram.cpp", defines={"SPLIT_BANK": 1})
        return
    if args.action in ("tilelink-platform", "tilelink-platform-flow", "tilelink-split-platform",
                       "tilelink-dual-platform", "tilelink-dual-split-platform"):
        split = args.action in ("tilelink-split-platform", "tilelink-dual-split-platform")
        dual = args.action in ("tilelink-dual-platform", "tilelink-dual-split-platform")
        cases = (("ram", (*build_machine_boot(uart=False, split=split), "--external-irq")),
                 ("dma", (*build_machine_boot(uart=False, dma=True), "--dma")),
                 ("atomic", (*build_machine_boot(uart=False, atomic=True), "--atomic")))
        output = test(gsim, cxx, args.action, "ooo.MachineCoreGsimMain", "MachineCoreGsim",
                      "machine.cpp", parameters=(32, 64, 64,
                      "tilelink-dual-split" if dual and split else "tilelink-dual" if dual else
                      "tilelink-split" if split else "tilelink-flow" if args.action == "tilelink-platform-flow" else "tilelink"),
                      runtime_args=cases[0][1],
                      defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
        fir = (output / "MachineCoreGsim.fir").read_text()
        if " of OrderedTileLinkBridge" not in fir or " of TileLinkDataRamAdapter" not in fir:
            raise RuntimeError("TileLink platform path was not elaborated")
        if split and " of TwoBankTileLinkRouter" not in fir:
            raise RuntimeError("split TileLink platform was elaborated without its router")
        if dual and any(f" of {module}" not in fir for module in
                        ("InstructionTileLinkBridge", "TileLinkInstructionRomAdapter",
                         "TwoMasterTwoBankTileLinkCrossbar", "TwoMasterTileLinkArbiter")):
            raise RuntimeError("dual-master TileLink platform was elaborated without fetch and arbitration")
        for name, runtime in cases[1:]:
            log = output / f"{name}-boot.log"
            run([output / "run", *runtime], log=log,
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print(log.read_text(), end="", flush=True)
        if dual:
            for boundary, option in (("high", "--fetch-fault"), ("low", "--fetch-fault-low")):
                fault_log = output / f"fetch-fault-{boundary}.log"
                run([output / "run", option], log=fault_log,
                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
                print(fault_log.read_text(), end="", flush=True)
            ram_exec_log = output / "ram-exec.log"
            run([output / "run", "--ram-exec"], log=ram_exec_log,
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print(ram_exec_log.read_text(), end="", flush=True)
        measurements = []
        for name, filename in (("ram", "test.log"), ("dma", "dma-boot.log"),
                               ("atomic", "atomic-boot.log")):
            log_text = (output / filename).read_text()
            rows = re.findall(rf"^{name} boot seed=(\d+) cycles=(\d+) result=(\d+)",
                              log_text, re.M)
            fetch_rows = re.findall(
                r"^FETCH_WAIT seed=(\d+) total=(\d+) duringDma=(\d+) "
                r"enabled=(\d+) enabledDuringDma=(\d+)$", log_text, re.M)
            if len(rows) != 3 or any(int(result) != 376 for _, _, result in rows):
                raise RuntimeError(f"TileLink platform {name} measurements incomplete")
            if len(fetch_rows) != len(rows) or any(fetch[0] != row[0] for row, fetch in zip(rows, fetch_rows)):
                raise RuntimeError(f"TileLink platform {name} fetch profile incomplete")
            measurements.extend({
                "name": name, "seed": int(seed), "cycles": int(cycles),
                "fetch_wait_cycles": int(fetch[1]), "fetch_wait_dma_cycles": int(fetch[2]),
                "fetch_wait_enabled_cycles": int(fetch[3]),
                "fetch_wait_enabled_dma_cycles": int(fetch[4])
            } for (seed, cycles, _), fetch in zip(rows, fetch_rows))
        (BUILD / f"{args.action}.json").write_text(json.dumps({
            "topology": ("Fetch+DataPort-TileLink-two-bank-RAM" if split else
                         "Fetch+DataPort-TileLink-ROM+RAM") if dual else
                        ("DataPort-TileLink-two-bank-RAM" if split else "DataPort-TileLink-ordered-DataPort-RAM"),
            "ordered_writes": not split,
            "model_sha256": hashlib.sha256((output / "MachineCoreGsim.fir").read_bytes()).hexdigest(),
            "measurements": measurements
        }, indent=2) + "\n")
        return
    if args.action == "sstc-platform":
        runtime = (*build_sstc_boot(), "--sstc")
        for name, params in (("sstc-platform-small", (8, 36, 64, "synchronous")),
                             ("sstc-platform", (32, 64, 64, "synchronous"))):
            test(gsim, cxx, name, "ooo.MachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
                 parameters=params, runtime_args=runtime,
                 defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
        return
    if args.action in ("privilege-uart-platform", "test"):
        runtime = (*build_privilege_uart_boot(), "--privilege-uart")
        output = test(gsim, cxx, "privilege-uart-platform", "ooo.MachineCoreGsimMain", "MachineCoreGsim",
                      "machine.cpp", parameters=(32, 64, 64, "synchronous"), runtime_args=runtime,
                      defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
        with (output / "serial-negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", *runtime, "--inject-serial"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "boot serial output mismatch" not in (output / "serial-negative-test.log").read_text():
            raise RuntimeError("privilege UART serial oracle negative test failed")
        print("GSIM privilege UART serial mismatch injection: PASS", flush=True)
        if args.action == "privilege-uart-platform":
            return
    if args.action in ("pmp-fetch-platform", "test"):
        runtime = (*build_privilege_uart_boot(), "--privilege-uart")
        test(gsim, cxx, "pmp-fetch-platform", "ooo.MachineCoreGsimMain", "MachineCoreGsim",
             "machine.cpp", parameters=(32, 64, 64, "tilelink-dual"), runtime_args=runtime,
             defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
        if args.action == "pmp-fetch-platform":
            return
    if args.action in ("cache", "test"):
        output = test(gsim, cxx, "cache", "ip.CacheGsimMain", "SharedReadCache", "cache.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "cache response mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("cache negative check failed")
        print("GSIM cache mismatch injection: PASS", flush=True)
    if args.action in ("atomic-core", "cache-core", "test"):
        from reference import build_reference
        reference = build_reference()
        core_cases = [("atomic-core-small", 8, 36, False), ("atomic-core", 32, 64, False)]
        if args.action != "atomic-core":
            core_cases += [("cached-core-small", 8, 36, True), ("cached-core", 32, 64, True)]
        for name, rob, physical, cached in core_cases:
            output = test(gsim, cxx, name, "ooo.AtomicCoreGsimMain", "AtomicCoreGsim", "atomic_core.cpp",
                          parameters=(rob, physical, 64, "cache" if cached else "plain"), runtime_args=(reference,),
                          defines={"CACHED_CORE": int(cached)})
        measurements = []
        for name, rob, physical, cached in core_cases:
            for line in (BUILD / name / "test.log").read_text().splitlines():
                if line.startswith("ATOMIC_CORE "):
                    fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
                    measurements.append({"rob": rob, "physical": physical,
                                         **{k: v if k == "name" else int(v) for k, v in fields.items()}})
        (BUILD / "cache-core.json").write_text(json.dumps(measurements, indent=2) + "\n")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", reference, "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "atomic core commit mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("atomic core oracle negative test failed")
        print("GSIM atomic core mismatch injection: PASS", flush=True)
    if args.action in ("atomic", "atomic-memory8", "test"):
        sizes = (4096, 8192) if args.action == "test" else (8192,) if args.action == "atomic-memory8" else (4096,)
        for size in sizes:
            atomic_name = "atomic" if size == 4096 else "atomic-memory8"
            if args.registered_physical_owners:
                atomic_name += "-registered-physical-owners"
            output = test(gsim, cxx, atomic_name, "ip.AtomicGsimMain",
                          "AtomicMemory", "atomic.cpp",
                          parameters=(size, "registered-owners") if args.registered_physical_owners else (size,),
                          defines={"RAM_BYTES": size,
                                   "REGISTERED_PHYSICAL_OWNERS": int(args.registered_physical_owners)})
            with (output / "negative-test.log").open("w") as stream:
                result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                        stderr=subprocess.STDOUT, timeout=120,
                                        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            if result.returncode != 1 or "atomic response mismatch" not in (output / "negative-test.log").read_text():
                raise RuntimeError(f"{size}-byte atomic oracle negative test failed")
            print(f"GSIM {size}-byte atomic mismatch injection: PASS", flush=True)
    if args.action in ("timer", "test"):
        output = test(gsim, cxx, "timer", "ip.TimerGsimMain", "MachineTimer", "timer.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "timer response mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("timer oracle negative test failed")
        print("GSIM timer mismatch injection: PASS", flush=True)
    if args.action in ("dma", "test"):
        output = test(gsim, cxx, "dma", "ip.DmaGsimMain", "MemoryCopyDma", "dma.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "copy data mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("DMA oracle negative test failed")
        print("GSIM DMA mismatch injection: PASS", flush=True)
    if args.action in ("shared-data", "test"):
        shared_name = "shared-data-registered-physical-owners" if args.registered_physical_owners else "shared-data"
        output = test(gsim, cxx, shared_name, "ooo.SharedDataGsimMain", "SharedDataGsim", "shared_data.cpp",
                      parameters=("registered-owners",) if args.registered_physical_owners else (),
                      defines={"REGISTERED_PHYSICAL_OWNERS": int(args.registered_physical_owners)})
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "response data mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("shared memory oracle negative test failed")
        print("GSIM shared memory mismatch injection: PASS", flush=True)
    if args.action in ("uart", "test"):
        output = test(gsim, cxx, "uart", "ip.UartGsimMain", "UartConsole", "uart.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "serial byte mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("UART oracle negative test failed")
        print("GSIM UART mismatch injection: PASS", flush=True)
        formats = test(gsim, cxx, "uart-formats", "ip.UartGsimMain", "UartConsole", "uart_formats.cpp")
        with (formats / "negative-test.log").open("w") as stream:
            result = subprocess.run([formats / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "TX wire format mismatch" not in (formats / "negative-test.log").read_text():
            raise RuntimeError("UART format oracle negative test failed")
        print("GSIM UART format mismatch injection: PASS", flush=True)
    if args.action == "machine-platform-memory8":
        ram_runtime = (*build_machine_boot(uart=False), "--external-irq")
        dma_runtime = (*build_machine_boot(uart=False, dma=True), "--dma")
        atomic_runtime = (*build_machine_boot(uart=False, atomic=True), "--atomic")
        output = test(gsim, cxx, "machine-platform-memory8", "ooo.MachineCoreGsimMain", "MachineCoreGsim",
                      "machine.cpp", parameters=(32, 64, 64, "synchronous", 8), runtime_args=ram_runtime,
                      defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
        if "inst slots_7 of LoadStoreUnit" not in (output / "MachineCoreGsim.fir").read_text():
            raise RuntimeError("8-slot machine platform was elaborated without its eighth LSU slot")
        for name, runtime in (("dma", dma_runtime), ("atomic", atomic_runtime)):
            run([output / "run", *runtime], log=output / f"{name}-boot.log",
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print((output / f"{name}-boot.log").read_text(), end="", flush=True)
        measurements = []
        for filename in ("test.log", "dma-boot.log", "atomic-boot.log"):
            measurements.extend({"name": kind, "seed": int(seed), "cycles": int(cycles)}
                                for kind, seed, cycles in re.findall(
                                    r"^(ram|dma|atomic) boot seed=(\d+) cycles=(\d+)",
                                    (output / filename).read_text(), re.M))
        if len(measurements) != 9:
            raise RuntimeError("8-slot platform measurements missing")
        (BUILD / "platform-memory8.json").write_text(json.dumps({"rob": 32, "physical": 64,
            "memory_entries": 8, "cached": False, "model_sha256": hashlib.sha256(
                (output / "MachineCoreGsim.fir").read_bytes()).hexdigest(),
            "measurements": measurements}, indent=2) + "\n")
        return
    if args.action in ("machine-platform-latency", "tilelink-dual-latency"):
        tilelink = args.action == "tilelink-dual-latency"
        delay = 40
        runtime = (*build_machine_boot(uart=False, latency=True), "--external-irq")
        measurements = []
        committed = {}
        for slots in (4, 8):
            output = test(gsim, cxx, f"{args.action}{slots}", "ooo.MachineCoreGsimMain",
                          "MachineCoreGsim", "machine.cpp",
                          parameters=(32, 64, 64, "tilelink-dual" if tilelink else "synchronous", slots, delay),
                          runtime_args=runtime,
                          defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
            fir = (output / "MachineCoreGsim.fir").read_text()
            if f"inst slots_{slots - 1} of LoadStoreUnit" not in fir or f"inst slots_{slots} of LoadStoreUnit" in fir:
                raise RuntimeError(f"incorrect LSU slot count in {slots}-slot delayed platform")
            if tilelink and any(f" of {module}" not in fir for module in
                                ("OrderedTileLinkBridge", "InstructionTileLinkBridge",
                                 "TwoMasterTwoBankTileLinkCrossbar", "TileLinkDataRamAdapter")):
                raise RuntimeError("delayed TileLink platform did not elaborate the dual-master RAM path")
            log_text = (output / "test.log").read_text()
            rows = re.findall(r"^ram boot seed=(\d+) cycles=(\d+) result=(\d+)", log_text, re.M)
            summary = re.search(r"^GSIM MachinePlatform: PASS programs=3 commits=(\d+)", log_text, re.M)
            if len(rows) != 3 or not summary or any(int(result) != 376 for _, _, result in rows):
                raise RuntimeError(f"incomplete delayed-platform measurements for {slots} slots")
            committed[slots] = int(summary[1])
            measurements.extend({"memory_entries": slots, "seed": int(seed), "cycles": int(cycles)}
                                for seed, cycles, _ in rows)
            if slots == 8:
                for name, boot_runtime in (("dma", (*build_machine_boot(uart=False, dma=True), "--dma")),
                                           ("atomic", (*build_machine_boot(uart=False, atomic=True), "--atomic"))):
                    log = output / f"{name}-boot.log"
                    run([output / "run", *boot_runtime], log=log, timeout=120,
                        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                    if len(re.findall(rf"^{name} boot seed=", log.read_text(), re.M)) != 3:
                        raise RuntimeError(f"incomplete delayed-platform {name} validation")
        if committed[4] != committed[8]:
            raise RuntimeError("4/8-slot delayed platforms retired different instruction counts")
        (BUILD / ("tilelink-dual-latency.json" if tilelink else "platform-latency.json")).write_text(json.dumps({
            "topology": "Fetch+DataPort-TileLink-ROM+RAM" if tilelink else "direct ROM+RAM",
            "response_delay": delay,
            "latency_from": "accepted synchronous RAM response", "response_queue_entries": 8,
            "commits_per_configuration": committed[4],
            "validation": "RAM on 4/8 slots; DMA and atomic on 8 slots, three seeds each",
            "measurements": measurements}, indent=2) + "\n")
        return
    if args.action in ("machine-platform", "cache-platform", "test"):
        runtime = build_machine_boot()
        baseline = (*build_machine_boot(uart=False), "--external-irq")
        dma_runtime = (*build_machine_boot(uart=False, dma=True), "--dma")
        atomic_runtime = (*build_machine_boot(uart=False, atomic=True), "--atomic")
        timer_runtime = (*build_machine_boot(uart=False, timer=True), "--timer")
        sstc_runtime = (*build_sstc_boot(), "--sstc")
        platform_cases = [("machine-platform-small", (8, 36, 64, "synchronous")),
                          ("machine-platform", (32, 64, 64, "synchronous"))]
        if args.action != "machine-platform":
            platform_cases += [("cached-platform-small", (8, 36, 64, "cached")),
                               ("cached-platform", (32, 64, 64, "cached"))]
        for name, params in platform_cases:
            output = test(gsim, cxx, name, "ooo.MachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
                          parameters=params, runtime_args=runtime, defines={"MAPPED_APLIC": 1, "SYNCHRONOUS_MACHINE": 1})
            run([output / "run", *baseline], log=output / "ram-baseline.log",
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print((output / "ram-baseline.log").read_text(), end="", flush=True)
            run([output / "run", *dma_runtime], log=output / "dma-boot.log",
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print((output / "dma-boot.log").read_text(), end="", flush=True)
            run([output / "run", *timer_runtime], log=output / "timer-boot.log",
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print((output / "timer-boot.log").read_text(), end="", flush=True)
            if params[3] == "synchronous":
                run([output / "run", *sstc_runtime], log=output / "sstc-boot.log",
                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
                print((output / "sstc-boot.log").read_text(), end="", flush=True)
            run([output / "run", *atomic_runtime], log=output / "atomic-boot.log",
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            print((output / "atomic-boot.log").read_text(), end="", flush=True)
        boot_measurements = []
        for name, params in platform_cases:
            for filename in ("test.log", "ram-baseline.log", "dma-boot.log", "timer-boot.log", "atomic-boot.log"):
                for kind, seed, cycles in re.findall(r"^(uart|ram|dma|timer|atomic) boot seed=(\d+) cycles=(\d+)",
                                                   (BUILD / name / filename).read_text(), re.M):
                    boot_measurements.append({"name": kind, "rob": params[0], "physical": params[1],
                                              "cached": params[3] == "cached", "seed": int(seed), "cycles": int(cycles)})
        (BUILD / "cache-platform.json").write_text(json.dumps(boot_measurements, indent=2) + "\n")
        stall_measurements = []
        for name, params in platform_cases:
            for filename in ("test.log", "ram-baseline.log", "dma-boot.log", "timer-boot.log", "atomic-boot.log"):
                seen = {}
                for line in (BUILD / name / filename).read_text().splitlines():
                    if line.startswith("CACHE_STALL "):
                        fields = dict(re.findall(r"(\w+)=([^ ]+)", line))
                        scope, seed = fields.pop("scope"), int(fields.pop("seed"))
                        seen[(scope, seed)] = {key: int(value) for key, value in fields.items()}
                    boot = re.match(r"(uart|ram|dma|timer|atomic) boot seed=(\d+) cycles=(\d+)", line)
                    if boot:
                        kind, seed, cycles = boot.group(1), int(boot.group(2)), int(boot.group(3))
                        if ("boot", seed) not in seen:
                            raise RuntimeError("platform stall counters missing from boot")
                        stall_measurements.append({"name": kind, "rob": params[0], "physical": params[1],
                                                   "cached": params[3] == "cached", "seed": seed, "cycles": cycles,
                                                   "boot": seen.pop(("boot", seed)),
                                                   "dma": seen.pop(("dma", seed), None)})
        if len(stall_measurements) != len(boot_measurements):
            raise RuntimeError("platform stall counter coverage mismatch")
        (BUILD / "cache-stalls.json").write_text(json.dumps(stall_measurements, indent=2) + "\n")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", *runtime, "--inject-mmio"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "commit data/nextPC" not in (output / "negative-test.log").read_text():
            raise RuntimeError("machine platform oracle negative test failed")
        print("GSIM machine platform mismatch injection: PASS", flush=True)
        with (output / "serial-negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", *runtime, "--inject-serial"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "boot serial output mismatch" not in (output / "serial-negative-test.log").read_text():
            raise RuntimeError("machine platform serial oracle negative test failed")
        print("GSIM boot serial mismatch injection: PASS", flush=True)
    if args.action in ("router", "mapped-machine", "test"):
        output = test(gsim, cxx, "register-router", "ooo.CoreRegisterRouterGsimMain", "CoreRegisterRouter", "router.cpp")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "ordered response mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("router oracle negative test failed")
        print("GSIM router mismatch injection: PASS", flush=True)
    if args.action in ("mapped-machine", "test"):
        from reference import build_reference
        reference = build_reference()
        for name, params in [("mapped-machine-small", (8, 36, 64, "mapped")), ("mapped-machine", (32, 64, 64, "mapped"))]:
            output = test(gsim, cxx, name, "ooo.MachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
                          parameters=params, runtime_args=(reference,), defines={"MAPPED_APLIC": 1})
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", reference, "--inject-mmio"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "commit data/nextPC" not in (output / "negative-test.log").read_text():
            raise RuntimeError("mapped MMIO oracle negative test failed")
        print("GSIM mapped MMIO mismatch injection: PASS", flush=True)
    if args.action in ("aplic", "test"):
        for sources in (31, 63):
            output = test(gsim, cxx, f"aplic-{sources}", "ip.AplicGsimMain", "Aplic", "aplic.cpp",
                          parameters=(sources,), defines={"APLIC_SOURCES": sources})
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "unexpected MSI identity/count" not in (output / "negative-test.log").read_text():
            raise RuntimeError("APLIC MSI oracle negative test failed")
        print("GSIM APLIC mismatch injection: PASS", flush=True)
    if args.action in ("wired-machine", "test"):
        from reference import build_reference
        reference = build_reference()
        test(gsim, cxx, "wired-machine", "ooo.MachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
             parameters=(32, 64, 64, "wired"), runtime_args=(reference,), defines={"WIRED_APLIC": 1})
    if args.action in ("machine", "test"):
        from reference import build_reference
        reference = build_reference()
        for name, parameters in [("machine-small", (8, 36, 64)), ("machine", (32, 64, 64))]:
            output = test(gsim, cxx, name, "ooo.MachineCoreGsimMain", "MachineCoreGsim", "machine.cpp",
                 parameters=parameters, runtime_args=(reference,))
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", reference, "--inject-mismatch"], stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "commit data/nextPC" not in (output / "negative-test.log").read_text():
            raise RuntimeError("machine CSR oracle negative test failed")
        print("GSIM machine CSR mismatch injection: PASS", flush=True)
        with (output / "interrupt-negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", reference, "--inject-interrupt"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "trap metadata" not in (output / "interrupt-negative-test.log").read_text():
            raise RuntimeError("machine interrupt oracle negative test failed")
        print("GSIM machine interrupt mismatch injection: PASS", flush=True)
    if args.action in ("imsic", "test"):
        for identities, guests in [(63, 1), (127, 2), (2047, 0)]:
            output = test(gsim, cxx, f"imsic-{identities}", "ip.ImsicGsimMain", "Imsic", "imsic.cpp",
                          parameters=(identities, guests), defines={"IMSIC_IDENTITIES": identities, "IMSIC_GUESTS": guests})
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "CSR response mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("IMSIC oracle negative test failed")
        print("GSIM IMSIC mismatch injection: PASS", flush=True)
    if args.action in ("pipelined-mul", "test"):
        test(gsim, cxx, "pipelined-mul", "ooo.PipelinedMultiplyGsimMain", "PipelinedMultiplyGsim", "pipelined_mul.cpp")
    if args.action in ("muldiv", "test"):
        test(gsim, cxx, "muldiv", "ooo.MultiplyDivideGsimMain", "MultiplyDivide", "muldiv.cpp")
    if args.action in ("platform", "test"):
        from reference import build_reference
        reference = build_reference()
        payload = build_c_payload()
        output = test(gsim, cxx, "platform", "ooo.SynchronousPlatformGsimMain", "SynchronousPlatformGsim", "platform.cpp",
                      runtime_args=(reference, payload))
        measurements = [json.loads(line[9:]) for line in (output / "test.log").read_text().splitlines() if line.startswith("PLATFORM ")]
        report = {"scope": "two-issue ROB32/PRF64, synchronous Chisel ROM and byte-write RAM, sequential fetch prefetch, four-entry store buffer, no caches/MMU/CSR",
                  "window": "core release through last normal retirement; RAM/program initialization and post-run RAM scan excluded",
                  "toolchain": json.loads((BUILD / "toolchain-used.json").read_text()),
                  "reference": json.loads((BUILD / "reference-used.json").read_text()),
                  "payload_sha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                  "model_sha256": hashlib.sha256((output / "SynchronousPlatformGsim.fir").read_bytes()).hexdigest(),
                  "measurements": measurements}
        (BUILD / "platform-ipc.json").write_text(json.dumps(report, indent=2) + "\n")
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", reference, payload, "--inject-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "NEMU register mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("synchronous platform NEMU negative test failed")
        print("GSIM synchronous platform NEMU mismatch injection: PASS", flush=True)
    if args.action in ("fpga-fetch", "test"):
        from reference import build_reference
        test(gsim, cxx, "fpga-fetch", "ooo.FpgaFetchGsimMain", "FpgaFetchGsim", "fpga_fetch.cpp",
             runtime_args=(build_reference(),))
    if args.action == "instruction-cache":
        test(gsim, cxx, "instruction-cache", "ooo.FpgaFetchGsimMain", "FpgaFetchGsim",
             "instruction_cache.cpp", parameters=("compressed-cache",), defines={})
    if args.action == "instruction-line-cache":
        test(gsim, cxx, "instruction-line-prefetch" if args.instruction_prefetch else
             "instruction-line-cache", "ooo.InstructionLineCacheGsimMain", "InstructionLineCacheGsim",
             "instruction_line_prefetch.cpp" if args.instruction_prefetch else "instruction_line_cache.cpp",
             parameters=("prefetch",) if args.instruction_prefetch else (), defines={})
    if args.action in ("smoke", "test"):
        test(gsim, cxx, "smoke", "ooo.GsimSmokeMain", "GsimSmoke", "smoke.cpp")
    if args.action in ("predictor", "core", "test"):
        test(gsim, cxx, "predictor", "ooo.BranchPredictorGsimMain", "BranchPredictorGsim", "predictor.cpp")
    if args.action in ("store-buffer", "store-buffer-registered", "test"):
        registered = args.action == "store-buffer-registered"
        owners = args.registered_owners
        for entries in ((2,) if registered or owners else (1, 2, 8, 4)):
            name = "store-buffer-owners-2" if owners else "store-buffer-registered-2" if registered else (
                "store-buffer" if entries == 4 else f"store-buffer-{entries}")
            output = test(gsim, cxx, name, "ooo.StoreBufferGsimMain", "StoreBufferGsim", "store_buffer.cpp",
                          parameters=(entries, "registered-owners") if owners else
                                     (entries, "registered-local-response") if registered else (entries,),
                          defines={"BUFFER_ENTRIES": entries, "REGISTER_LOCAL_RESPONSE": int(registered)})
        if registered or owners:
            return
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-write-error"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode == 0 or "platform violated guaranteed RAM write success" not in (output / "negative-test.log").read_text():
            raise RuntimeError("guaranteed RAM write error was not detected")
        print("GSIM StoreBuffer write-error contract injection: PASS (violation rejected)", flush=True)
        with (output / "read-negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", "--inject-read-mismatch"], stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "load forwarding/value mismatch" not in (output / "read-negative-test.log").read_text():
            raise RuntimeError("StoreBuffer load oracle negative test failed")
        print("GSIM StoreBuffer read mismatch injection: PASS", flush=True)
    if args.action in ("backend-recovery4", "test"):
        test(gsim, cxx, "backend-recovery4", "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp",
             parameters=("32", "64", "64", "4"),
             defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64, "TAG_BITS": 64, "RECOVERY_WIDTH": 4})
    if args.action in ("backend-recovery8", "test"):
        test(gsim, cxx, "backend-recovery8", "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp",
             parameters=("32", "64", "64", "8"),
             defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64, "TAG_BITS": 64, "RECOVERY_WIDTH": 8})
    if args.action == "backend-recovery16":
        test(gsim, cxx, "backend-recovery16", "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp",
             parameters=("32", "64", "64", "16"),
             defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64, "TAG_BITS": 64, "RECOVERY_WIDTH": 16})
    if args.action == "backend-move-alias":
        test(gsim, cxx, "backend-move-alias", "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp",
             parameters=("32", "64", "64", "16", "move-alias"),
             defines={"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64, "TAG_BITS": 64,
                      "RECOVERY_WIDTH": 16, "MOVE_ALIAS": 1})
    if args.action in ("backend", "test"):
        for name, parameters in [("backend-small", (8, 36, 64)), ("backend", (32, 64, 64)),
                                 ("backend-tag-limit", (8, 36, 8))]:
            test(gsim, cxx, name, "ooo.RenameRobGsimMain", "RenameRobGsim", "backend.cpp", parameters)
    if args.action in ("integer", "test"):
        for name, parameters in [("integer-small", (8, 36, 64)), ("integer", (32, 64, 64))]:
            test(gsim, cxx, name, "ooo.IntegerBackendGsimMain", "IntegerBackendGsim", "integer.cpp", parameters)
    if args.action in ("core", "core-memory8", "core-branch-pipeline", "core-fast-store", "core-fast-memory", "core-move-alias",
                       "core-word-bypass", "core-indirect", "ipc", "test"):
        from reference import build_reference
        reference = build_reference()
        payloads = []
        for stem in ("integer-program", "branch-program"):
            payload = BUILD / stem
            run(["riscv64-unknown-elf-gcc", "-march=rv64i", "-mabi=lp64", "-mno-relax", "-nostdlib", "-nostartfiles",
                 "-Wl,--no-relax", "-T", HERE / "payloads/integer-program.ld", HERE / "payloads" / (stem + ".S"), "-o", payload.with_suffix(".elf")],
                log=BUILD / (stem + "-build.log"))
            run(["riscv64-unknown-elf-objcopy", "-O", "binary", "--only-section=.text", payload.with_suffix(".elf"),
                 payload.with_suffix(".bin")], log=BUILD / (stem + "-binary.log"))
            payloads.append(payload.with_suffix(".bin"))
        payloads.append(build_c_payload())
        configurations = [("core-small", (8, 36, 64)), ("core", (32, 64, 64))]
        if args.action == "ipc": configurations = configurations[1:]
        if args.action == "core-memory8": configurations = [("core-memory8", (32, 64, 64, 8))]
        if args.action == "core-branch-pipeline": configurations = [((
            "core-registered-memory-address-owners-retirement" if args.registered_retirement else
            "core-registered-memory-address-owners" if args.registered_memory_address and args.registered_owners else
            "core-registered-memory-address" if args.registered_memory_address else
            "core-registered-owners" if args.registered_owners else "core-branch-pipeline") +
            ("-early-recovery" if args.early_recovery_issue_block else "") +
            ("-precomplete-branch" if args.precomplete_mispredicted_branch else "") +
            ("-registered-load-replay" if args.registered_load_replay else "") +
            ("-registered-local-response" if args.registered_local_response else "") +
            ("-registered-memory-requests" if args.registered_memory_requests else ""),
            (32, 64, 64, 8, "plain", "plain", "plain", "plain", "plain", "0", "registered-branch", "4",
             *(("registered-owners",) if args.registered_owners else ()),
             *(("registered-local-response",) if args.registered_local_response else ()),
             *(("registered-memory-requests",) if args.registered_memory_requests else ()),
             *(("registered-memory-address",) if args.registered_memory_address else ()),
             *(("registered-retirement",) if args.registered_retirement else ()),
             *(("registered-load-replay",) if args.registered_load_replay else ()),
             *(("early-recovery-issue-block",) if args.early_recovery_issue_block else ()),
             *(("precomplete-mispredicted-branch",) if args.precomplete_mispredicted_branch else ())))]
        if args.action == "core-fast-store": configurations = [("core-fast-store", (32, 64, 64, 4, "fast-store"))]
        if args.action == "core-fast-memory": configurations = [("core-fast-memory", (32, 64, 64, 4, "fast-store", "fast-load", "load-bypass"))]
        if args.action == "core-move-alias": configurations = [("core-move-alias", (32, 64, 64, 4,
            "fast-store", "fast-load", "load-bypass", "move-alias"))]
        if args.action == "core-word-bypass": configurations = [("core-word-bypass", (32, 64, 64, 4,
            "fast-store", "fast-load", "load-bypass", "plain", "word-bypass"))]
        if args.action == "core-indirect": configurations = [("core-indirect", (32, 64, 64, 4,
            "fast-store", "fast-load", "load-bypass", "plain", "word-bypass", "16"))]
        if args.action == "test": configurations.append(("core-fast-store", (32, 64, 64, 4, "fast-store")))
        if args.action == "test": configurations.append(("core-fast-memory", (32, 64, 64, 4, "fast-store", "fast-load", "load-bypass")))
        measurements = []
        for name, parameters in configurations:
            definitions = ({"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64, "TAG_BITS": 64, "MEMORY_ENTRIES": 8,
                            **({"REGISTERED_BRANCH_REDIRECT": 1} if args.action == "core-branch-pipeline" else {}),
                            **({"REGISTERED_RESPONSE_OWNERS": 1} if args.registered_owners else {}),
                            **({"REGISTERED_MEMORY_ADDRESS": 1} if args.registered_memory_address else {})}
                           if args.action in ("core-memory8", "core-branch-pipeline") else
                           {"ROB_ENTRIES": 32, "PHYSICAL_REGS": 64, "TAG_BITS": 64,
                            **({"FAST_HEAD_LOAD": 1} if name in ("core-fast-memory", "core-move-alias",
                                                                "core-word-bypass", "core-indirect") else {}),
                            **({"INDIRECT_ENTRIES": 16} if name == "core-indirect" else {})}
                           if name in ("core-fast-store", "core-fast-memory", "core-move-alias",
                                       "core-word-bypass", "core-indirect") else None)
            output = test(gsim, cxx, name, "ooo.IntegerCoreGsimMain", "IntegerCoreGsim", "core.cpp", parameters,
                          (reference, *payloads, *(("--ipc",) if args.action == "ipc" else ())), defines=definitions)
            measurements.extend(json.loads(line[4:]) for line in (output / "test.log").read_text().splitlines() if line.startswith("IPC "))
        memory_slots = 8 if args.action in ("core-memory8", "core-branch-pipeline") else 4
        report = {"scope": f"bare core, ideal two-wide instruction supply, 64-entry commit-trained bimodal conditional predictor, direct JAL and adjacent AUIPC/JALR target prediction, no caches/MMU/CSR, {memory_slots}-slot LSU, oldest-ready load selection with overlap replay, ROB-indexed speculative store preparation and known-address disambiguation, four-entry irrevocable store buffer for guaranteed-success RAM writes, disjoint reads overlap pending write responses through {memory_slots + 1} shared owner credits, ordered responses and stores, early RAM loads and byte-wise store forwarding, shared two-issue budget",
                  "recovery_width": 4 if args.action == "core-branch-pipeline" else 1,
                  "registered_response_owners": args.action == "core-branch-pipeline" and args.registered_owners,
                  "registered_memory_address": args.action == "core-branch-pipeline" and args.registered_memory_address,
                  "registered_rob_retirement": args.action == "core-branch-pipeline" and args.registered_retirement,
                  "early_recovery_issue_block": args.action == "core-branch-pipeline" and args.early_recovery_issue_block,
                  "registered_load_replay": args.action == "core-branch-pipeline" and args.registered_load_replay,
                  "registered_local_response": args.action == "core-branch-pipeline" and args.registered_local_response,
                  "registered_memory_requests": args.action == "core-branch-pipeline" and args.registered_memory_requests,
                  "precomplete_mispredicted_branch": args.action == "core-branch-pipeline" and args.precomplete_mispredicted_branch,
                  "window": "first supply cycle through last retirement inclusive; reset and post-run checking excluded",
                  "toolchain": json.loads((BUILD / "toolchain-used.json").read_text()),
                  "reference": json.loads((BUILD / "reference-used.json").read_text()),
                  "payload_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in payloads},
                  "model_sha256": {name: hashlib.sha256((BUILD / name / "IntegerCoreGsim.fir").read_bytes()).hexdigest()
                                   for name, _ in configurations},
                  "payload_compiler": subprocess.check_output(["riscv64-unknown-elf-gcc", "--version"], text=True).splitlines()[0],
                  "measurements": measurements}
        report_stem = ("ipc-memory8" if args.action == "core-memory8" else
                       ("ipc-registered-memory-address-owners-retirement" if args.registered_retirement else
                        "ipc-registered-memory-address-owners" if args.registered_memory_address and args.registered_owners else
                        "ipc-registered-memory-address" if args.registered_memory_address else
                        "ipc-registered-owners" if args.registered_owners else "ipc-branch-pipeline")
                       if args.action == "core-branch-pipeline" else
                       "ipc-fast-store" if args.action == "core-fast-store" else
                       "ipc-fast-memory" if args.action == "core-fast-memory" else
                       "ipc-move-alias" if args.action == "core-move-alias" else
                       "ipc-word-bypass" if args.action == "core-word-bypass" else
                       "ipc-indirect" if args.action == "core-indirect" else "ipc")
        if args.early_recovery_issue_block:
            report_stem += "-early-recovery"
        if args.precomplete_mispredicted_branch:
            report_stem += "-precomplete-branch"
        if args.registered_load_replay:
            report_stem += "-registered-load-replay"
        if args.registered_local_response:
            report_stem += "-registered-local-response"
        if args.registered_memory_requests:
            report_stem += "-registered-memory-requests"
        (BUILD / f"{report_stem}.json").write_text(json.dumps(report, indent=2) + "\n")
        with (BUILD / f"{report_stem}.csv").open("w") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(measurements[0]))
            writer.writeheader()
            writer.writerows(measurements)
        if args.action == "ipc": return
        # Prove the live NEMU comparison fails closed, without resynchronizing a mismatching DUT.
        with (output / "negative-test.log").open("w") as stream:
            result = subprocess.run([output / "run", reference, *payloads, "--inject-mismatch"],
                                    stdout=stream, stderr=subprocess.STDOUT, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        if result.returncode != 1 or "NEMU register mismatch" not in (output / "negative-test.log").read_text():
            raise RuntimeError("NEMU mismatch-injection test failed to detect corruption")
        print("GSIM NEMU mismatch injection: PASS (corruption rejected)", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM: {error}", file=sys.stderr)
        sys.exit(1)
