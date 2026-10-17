#!/usr/bin/env python3
"""Batched short I1 BootROM/reset/PLIC/boot-owned JTAG acceptance. No synthesis or long CPU benchmark."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sources, sha


def frozen_sources():
    result = sources()
    for folder, pattern in (("fpga/inorder/bootrom", "*"), ("src/main/resources/debug", "*.sv"),
                            ("src/main/resources/inorder", "*"), ("simulator/gsim/harness", "five_stage*.h")):
        for path in (ROOT / folder).glob(pattern):
            if path.is_file():
                result[str(path.relative_to(ROOT))] = sha(path)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("five-stage-boot-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite evidence")
    output.mkdir(parents=True)
    frozen = frozen_sources()
    receipt = {"status": "RUNNING", "source_sha256": frozen, "checks": {}, "physical_qualified": False,
        "scope": "Executing five-stage M-only SoC, 4KiB dual-port ROM, startup reset, PLIC, logical boot-only DMI; "
                 "BSCAN shell elaboration only, no TAP/CDC/board/Vivado/Linux qualification.",
        "jtag": {"enabled_default": False, "shared_user_chain": [2, 3, 4], "download_bytes": 67108864,
                 "not_architectural_debug": True, "address_bits": 32, "ddr_map_bytes": 2147483648}}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        common.run(["python3", ROOT / "fpga/inorder/bootrom/build.py", "--output", output / "firmware"],
                   log=output / "rom-build.log")
        rom = ROOT / "src/main/resources/inorder/bootrom.hex"
        if rom.read_text().splitlines() != (output / "firmware/bootrom.hex").read_text().splitlines():
            raise RuntimeError("default ROM does not reproduce from checked assembly")
        receipt["bootrom"] = json.loads((output / "firmware/manifest.json").read_text())
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"], log=output / "scala.log")

        def model(name, main_name, top, driver, flags=(), defines=(), rom_init=False):
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", main_name, out, 64, *flags],
                       log=out / "elaborate.log")
            common.run([gsim, "--threads=1", f"--dir={out}", out / (top + ".fir")], log=out / "generate.log")
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        "-DDUT_XLEN=64", "-I" + str(out), *sorted(out.glob(top + "[0-9]*.cpp")), *defines,
                        ROOT / "simulator/gsim/harness" / driver, "-o", out / "run"],
                       log=out / "compile.log", timeout=900)
            return out

        def check(name, out, argv=(), negative=None):
            common.run([out / "run", *argv], log=out / (name + ".log"), env=env, timeout=180)
            receipt["checks"][name] = (out / (name + ".log")).read_text().strip()
            if negative:
                bad_args, message = negative
                bad = subprocess.run([str(out / "run"), *map(str, bad_args)], env=env, capture_output=True,
                                     text=True, timeout=180)
                (out / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or message not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control not rejected: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_INDEPENDENT_MUTATION"

        out = model("plic", "inorder.FiveStagePlicMain", "FiveStagePlicHarness", "five_stage_plic.cpp")
        check("plic", out, negative=(["--wrong-claim"], "PLIC reply payload/side-effect oracle"))
        for enabled in (True, False):
            name = "startup-rom" if enabled else "startup-preloaded"
            out = model(name, "inorder.FiveStageStartupMain", "FiveStageStartup", "five_stage_startup.cpp",
                        [] if enabled else ["--soc-no-bootrom"], [f"-DI1_HAS_ROM={int(enabled)}"])
            check(name, out)
        out = model("rom", "inorder.FiveStageBootRomMain", "FiveStageBootRomHarness", "five_stage_boot_rom.cpp", [rom])
        check("rom", out, [rom], negative=([rom, "--wrong-byte"], "ROM held reply/data/deny oracle"))

        here = ROOT / "simulator/gsim/inorder"
        payload = output / "soc.bin"
        common.run(["riscv64-unknown-elf-gcc", "-march=rv64i_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany",
                    "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-T" + str(here / "soc_link.ld"),
                    here / "soc_smoke.S", "-o", output / "soc.elf"], log=output / "soc-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / "soc.elf", payload],
                   log=output / "soc-objcopy.log")
        fast = ["--icache=2048", "--dcache=2048", "--predictor=64", "--early-memory-issue", "--overlap-write-lookup"]
        for name, options in (("soc-rom", fast), ("soc-preloaded-small", ["--soc-no-bootrom", "--soc-ddr-one", "--no-m"]),
                              ("soc-jtag", [*fast, "--soc-jtag"])):
            has_rom = "--soc-no-bootrom" not in options
            out = model(name, "inorder.FiveStageSocGsimMain", "FiveStageSoc", "five_stage_soc.cpp", options,
                        [f"-DI1_HAS_ROM={int(has_rom)}"])
            argv = [payload, rom] if has_rom else [payload]
            if name == "soc-jtag":
                check(name, out, [*argv, "--jtag"])
                check("soc-jtag-crc-reject", out, [*argv, "--jtag", "--bad-crc"])
                check("soc-jtag-crc-retry", out, [*argv, "--jtag", "--retry"])
            else:
                check(name, out, argv, negative=([*argv, "--inject"], "bare SoC guest fail path"))
        # FPGA shell: real BSCAN resources, but DO NOT use GSIM to pretend to simulate vendor primitive/CDC.
        for name, options in (("fpga-jtag-user2", [*fast, "--soc-jtag", "--soc-user-chain=2"]),
                              ("fpga-no-jtag", fast),
                              ("soc-stripped", ["--soc-no-uart", "--soc-no-timer", "--soc-no-irq", "--no-m"])):
            out = output / name
            out.mkdir()
            main_name = "inorder.FiveStageFpgaShellMain" if name.startswith("fpga") else "inorder.FiveStageSocMain"
            common.run(["mill", "-i", "OrbitalI1.test.runMain", main_name, out, 64, *options], log=out / "elaborate.log")
            fir = next(out.glob("*.fir")).read_text()
            if "romInitialize" in fir or "initialize : { flip valid" in fir:
                raise RuntimeError("physical design contains test ROM write input")
            if name == "fpga-jtag-user2" and ("ValenceBscanDebugPort" not in fir or "JTAG_CHAIN = 2" not in fir):
                raise RuntimeError("shared USER2 BSCAN absent")
            if name == "fpga-no-jtag" and ("ValenceBscanDebugPort" in fir or "module JtagRamLoader" in fir):
                raise RuntimeError("disabled JTAG did not disappear")
            if name == "soc-stripped" and any("module " + m in fir for m in ("Plic", "UartConsole", "MachineTimer", "FiveStageMulDiv")):
                raise RuntimeError("disabled IP did not disappear")
            receipt["checks"][name] = "PASS_ELABORATION_ONLY_NO_PHYSICAL_SIGNOFF"
        if frozen_sources() != frozen:
            raise RuntimeError("source drift during batch")
        receipt["status"] = "PASS_I1_BOOTROM_RESET_PLIC_LOGICAL_JTAG_SHORT_ONLY"
    except Exception as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}, indent=2))


if __name__ == "__main__":
    main()
