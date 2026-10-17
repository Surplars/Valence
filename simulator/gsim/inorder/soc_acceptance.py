#!/usr/bin/env python3
"""Batched I1 TL/DDR/UART/M-IRQ bring-up and standard O2/O3 short CoreMark. Never synthesize."""
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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [ROOT / "build.mill", ROOT / "AGENTS.md"]
    for folder, pattern in (("src/main/scala", "*.scala"), ("src/test/scala/inorder", "*.scala"),
                            ("simulator/gsim/harness", "five_stage*.cpp"),
                            ("simulator/gsim/harness", "five_stage*.h"),
                            ("simulator/gsim/inorder", "*.py"), ("simulator/gsim/inorder", "*.S"),
                            ("simulator/gsim/inorder", "*.ld"), ("simulator/gsim/inorder/coremark_port", "*")):
        paths += [p for p in (ROOT / folder).rglob(pattern) if p.is_file()]
    paths += [ROOT / f"simulator/gsim/payloads/coremark_port/{name}" for name in ("start.S", "link.ld")]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("five-stage-soc-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite prior evidence")
    output.mkdir(parents=True)
    frozen = sources()
    receipt = {"status": "RUNNING", "source_sha256": frozen, "checks": {}, "benchmarks": {},
        "scope": "Independent five-stage RV64IM bare SoC + reused DDR bridge/UART/timer, M-mode IRQs; "
                 "no Linux/AIA/DMA/GMAC, no new Vivado/frequency/resource/board qualification.",
        "pipeline": ["IF", "ID", "EX", "MEM", "WB"], "ooo_rerun": False,
        "ddr": {"base": "0x80200000", "bytes": 2147483648, "axi_width": 64, "axi_address_width": 32,
                "physical_end_exclusive": "0x100200000", "translation": "subtract base BEFORE narrowing",
                "slots": [1, 2], "service": "bounded random AXI backpressure, first read response 3..15 cycles"},
        "physical_qualified": False, "formal_coremark": False}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version,
            "gcc": subprocess.check_output(["riscv64-unknown-elf-gcc", "--version"], text=True).splitlines()[0]}
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"], log=output / "scala.log")

        def model(name, main_name, top, driver, flags=(), width=64, defines=()):
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", main_name, out, width, *flags],
                       log=out / "elaborate.log")
            common.run([gsim, "--threads=1", f"--dir={out}", out / (top + ".fir")], log=out / "generate.log")
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                        f"-DDUT_XLEN={width}", "-I" + str(out), *sorted(out.glob(top + "[0-9]*.cpp")),
                        *defines, ROOT / "simulator/gsim/harness" / driver, "-o", out / "run"],
                       log=out / "compile.log", timeout=900)
            return out

        for width in (64, 32):
            out = model(f"tl{width}", "inorder.FiveStageTileLinkMain", "FiveStageTileLink",
                        "five_stage_tilelink.cpp", width=width)
            common.run([out / "run"], env=env, log=out / "test.log", timeout=60)
            receipt["checks"][f"tl{width}"] = (out / "test.log").read_text().strip()
            bad = subprocess.run([str(out / "run"), "--bad-source"], env=env, capture_output=True, text=True)
            (out / "negative.log").write_text(bad.stdout + bad.stderr)
            if bad.returncode == 0 or "TileLink response metadata mismatch" not in bad.stdout + bad.stderr:
                raise RuntimeError("TL metadata negative control did not reject mutation")
            receipt["checks"][f"tl{width}-negative"] = "PASS_REJECTED_WRONG_SOURCE"

        for name, width, capacity in (("cache-error64", 64, 512), ("cache-error32", 32, 512),
                                      ("cache-error-disabled", 64, 0)):
            out = model(name, "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
                        [f"--dcache={capacity}", "--overlap-write-lookup"], width,
                        [f"-DCACHE_BYTES={capacity}"])
            common.run([out / "run"], env=env, log=out / "test.log", timeout=60)
            receipt["checks"][name] = (out / "test.log").read_text().strip()

        fast = ["--icache=2048", "--dcache=2048", "--predictor=64", "--early-memory-issue", "--overlap-write-lookup"]
        payload = output / "payload"
        payload.mkdir()
        here = ROOT / "simulator/gsim/inorder"
        flags = ["-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
                 "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
                 "-nostdlib", "-nostartfiles"]
        common.run(["riscv64-unknown-elf-gcc", *flags, "-T" + str(here / "soc_link.ld"),
                    here / "soc_smoke.S", "-o", payload / "soc.elf"], log=payload / "soc-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload / "soc.elf", payload / "soc.bin"],
                   log=payload / "soc-objcopy.log")
        for name, options in (("soc-fast", fast), ("soc-small", ["--soc-ddr-one", "--no-m"])):
            out = model(name, "inorder.FiveStageSocMain", "FiveStageSoc", "five_stage_soc.cpp",
                        [*options, "--soc-no-bootrom"])
            common.run([out / "run", payload / "soc.bin"], env=env, log=out / "test.log", timeout=180)
            receipt["checks"][name] = (out / "test.log").read_text().strip()
            bad = subprocess.run([str(out / "run"), str(payload / "soc.bin"), "--inject"], env=env,
                                 capture_output=True, text=True, timeout=60)
            (out / "negative.log").write_text(bad.stdout + bad.stderr)
            if bad.returncode == 0 or "bare SoC guest fail path" not in bad.stdout + bad.stderr:
                raise RuntimeError("bare SoC DDR mutation did not reject corruption")
            receipt["checks"][name + "-negative"] = "PASS_REJECTED_DDR_CORRUPTION"
        # Removal profile is elaborated, not claimed as an executing UART/IRQ platform.
        stripped = output / "soc-stripped"
        stripped.mkdir()
        common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageSocMain", stripped, 64,
                    "--soc-no-uart", "--soc-no-timer", "--soc-no-irq", "--soc-ddr-one", "--no-m",
                    "--soc-no-bootrom"],
                   log=stripped / "elaborate.log")
        fir = (stripped / "FiveStageSoc.fir").read_text()
        if any("module " + module in fir for module in ("UartConsole", "MachineTimer", "FiveStageMulDiv")):
            raise RuntimeError("disabled IP was still instantiated")
        receipt["checks"]["stripped-profile"] = "PASS_ELABORATED_IP_REMOVAL_ONLY"

        coremark = Path("/home/openion/Valence/simulator/build/coremark-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=coremark, text=True).strip()
        if revision != "1f483d5b8316753a742cbf5590caf5bd0a4e4777" or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=coremark, text=True):
            raise RuntimeError("standard CoreMark source pin/cleanliness mismatch")
        out = model("coremark-fast", "inorder.FiveStageCachedMain", "FiveStageCachedCore",
                    "five_stage_coremark.cpp", fast)
        port = here / "coremark_port"
        old = ROOT / "simulator/gsim/payloads/coremark_port"
        receipt["coremark_payloads"] = {}
        for optimization in ("O2", "O3"):
            target = payload / optimization
            target.mkdir()
            cflags = ["-" + optimization, *flags, "-DITERATIONS=1", "-DPERFORMANCE_RUN=1", "-DTOTAL_DATA_SIZE=2000",
                      f'-DCOMPILER_FLAGS="-{optimization} -march=rv64im_zicsr_zifencei -mabi=lp64"']
            guest = [coremark / f for f in ("core_list_join.c", "core_main.c", "core_matrix.c", "core_state.c", "core_util.c")]
            common.run(["riscv64-unknown-elf-gcc", *cflags, "-I" + str(port), "-I" + str(coremark),
                        "-T" + str(old / "link.ld"), old / "start.S", *guest, port / "core_portme.c", "-lgcc",
                        "-o", target / "coremark.elf"], log=target / "build.log")
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", target / "coremark.elf", target / "coremark.bin"],
                       log=target / "objcopy.log")
            symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", target / "coremark.elf"], text=True)
            (target / "symbols.txt").write_text(symbols)
            values = {line.split()[-1]: int(line.split()[0], 16) for line in symbols.splitlines() if len(line.split()) == 3}
            receipt["coremark_payloads"][optimization] = {"flags": cflags, "source_commit": revision,
                "sha256": sha(target / "coremark.bin"), "bytes": (target / "coremark.bin").stat().st_size}
            for delay in (1, 12):
                command = [out / "run", target / "coremark.bin", hex(values["coremark_validation_errors"]),
                           hex(values["coremark_elapsed_ticks"]), hex(values["coremark_crcs"]), delay]
                log = out / f"{optimization}-l{delay}.log"
                common.run(command, env=env, log=log, timeout=240)
                line = log.read_text().strip()
                if not line.startswith("MATCHED_COREMARK_PASS "):
                    raise RuntimeError("missing standard CRC + independent CPU gate")
                result = json.loads(line.split(" ", 1)[1])
                result["roi_ipc"] = result["roi_instructions"] / result["roi_ticks"]
                result["short_iterations_per_mhz"] = 1e6 / result["roi_ticks"]
                receipt["benchmarks"][f"{optimization}-l{delay}"] = result
                print(f"{optimization}-l{delay}: " + json.dumps(result), flush=True)
            bad = subprocess.run(list(map(str, [*command, "--inject"])), env=env, capture_output=True, text=True)
            (out / f"{optimization}-negative.log").write_text(bad.stdout + bad.stderr)
            if bad.returncode == 0 or "independent register oracle mismatch" not in bad.stderr:
                raise RuntimeError("CoreMark mutation was not rejected")
            receipt["checks"][optimization + "-negative"] = "PASS_REJECTED_REGISTER_MUTATION"
            cohort = [receipt["benchmarks"][f"{optimization}-l{delay}"] for delay in (1, 12)]
            if len({(r["trace_fnv64"], r["retired"], r["crcfinal"]) for r in cohort}) != 1:
                raise RuntimeError("architectural stream differed within one optimization cohort")
        reference_path = ROOT / "build/gsim/five-stage-cache-20261013-throughput-r4/receipt.json"
        reference = json.loads(reference_path.read_text())
        for delay in (1, 12):
            for field in ("roi_ticks", "roi_instructions", "retired", "trace_fnv64", "crcfinal"):
                if receipt["benchmarks"][f"O2-l{delay}"][field] != reference["benchmarks"][f"i1-throughput-fast-l{delay}"][field]:
                    raise RuntimeError("O2 baseline drift after adding MMIO metadata")
        receipt["o2_frozen_reference"] = {"path": str(reference_path), "sha256": sha(reference_path)}
        if sources() != frozen:
            raise RuntimeError("source drift during batched acceptance")
        receipt["status"] = "PASS_I1_TILELINK_BARE_SOC_O2_O3_SHORT_ONLY"
    except BaseException as error:
        receipt["status"] = "FAILED"
        receipt["error"] = str(error)
        raise
    finally:
        receipt["artifacts_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
            if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}))


if __name__ == "__main__":
    main()
