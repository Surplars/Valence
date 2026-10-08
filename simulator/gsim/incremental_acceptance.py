#!/usr/bin/env python3
"""One frozen selected Board model, bounded affected tests, resumable checkpoints.

Does not reuse archived performance or timing, run Linux, or create a bitstream.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zlib
import run as common
from mshr_occupancy import validate

FLAGS = ("--compact-tags", "--identity-data-flow", "--banked-rob",
         "--shared-store-reads", "--ddr-write-slots=2", "--cache-writebacks=2",
         "--overlap-writeback-refill", "--unordered-ddr-responses", "--lvt-prf",
         "--data-next-line-prefetch")
PARAMETERS = ("ddr", "100000000", "staged-fetch-turnover", "460800", "2", "2",
              "1", "rv64gc", "2147483648", "0", "512", "0", "512", "4", "16",
              "2", "2", "1", *FLAGS)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def marker(elf, name):
    dis = subprocess.check_output(["riscv64-unknown-elf-objdump", "-d", elf], text=True)
    section = dis.split("<" + name + ">:", 1)[1].split("\n\n", 1)[0]
    pcs = re.findall(r"^\s*([0-9a-f]+):.*\brdtime\b", section, re.M)
    if len(pcs) != 1:
        raise RuntimeError("Missing/ambiguous timing marker: " + name)
    return int(pcs[0], 16)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--prefetch-proof", type=Path, required=True)
    ap.add_argument("--prf-proof", type=Path, required=True)
    ap.add_argument("--monitor-proof", type=Path, required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--refresh-coremark-harness", action="store_true",
                    help="resume after an audited harness-only correction; preserve the failed receipt")
    ap.add_argument("--jobs", type=int, choices=range(1, 5), default=2)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("unsafe tag")
    out = common.BUILD / ("incremental-" + a.tag)
    if out.exists() and not a.resume:
        ap.error("output exists; use --resume or a fresh tag")
    out.mkdir(parents=True, exist_ok=True)
    model, fw = out / "model", out / "firmware"
    model.mkdir(exist_ok=True)
    fw.mkdir(exist_ok=True)
    inputs = sorted((common.ROOT / "src").rglob("*.scala"))
    inputs += sorted((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    inputs += sorted((common.HERE / "harness").glob("*.h"))
    inputs += [common.HERE / "harness" / n for n in
               ("board_boot.cpp", "board_coremark.cpp", "board_memory_steady.cpp", "rv64gc_board.cpp", "board_menu.cpp")]
    inputs += sorted((common.ROOT / "fpga/firmware").rglob("*.c"))
    inputs += sorted((common.ROOT / "fpga/firmware").rglob("*.h"))
    inputs += [common.ROOT / n for n in ("build.mill", ".mill-version", "fpga/firmware/sample_app.ld",
               "fpga/firmware/sample_start.S", "fpga/firmware/rv64gc_smoke.S", "fpga/firmware/build_coremark.py",
               "simulator/gsim/payloads/board_memory_steady.c", "simulator/gsim/run.py",
               "simulator/gsim/mshr_occupancy.py", "simulator/gsim/incremental_acceptance.py")]
    proofs = [a.prefetch_proof.resolve(), a.prf_proof.resolve(), a.monitor_proof.resolve()]
    for proof in proofs:
        if not json.loads(proof.read_text())["status"].upper().startswith("PASS"):
            raise RuntimeError("Prerequisite not passed: " + str(proof))
    rom = proofs[2].parent / "firmware/bootrom.bin"
    inputs += proofs + [rom]
    frozen = {str(p): sha(p) for p in inputs}
    receipt = out / "receipt.json"
    state = json.loads(receipt.read_text()) if receipt.exists() else {
        "status": "RUNNING", "inputs": frozen, "parameters": PARAMETERS,
        "steps": {}, "artifacts": {}, "commands": [], "tests": {}}
    if a.refresh_coremark_harness:
        if not a.resume or state["status"] != "FAIL":
            raise RuntimeError("Harness refresh requires a failed resumable checkpoint")
        changed = {p for p in set(frozen) | set(state["inputs"])
                   if frozen.get(p) != state["inputs"].get(p)}
        allowed = {str(Path(__file__).resolve()), str(common.HERE / "harness/board_coremark.cpp")}
        if not changed <= allowed:
            raise RuntimeError("Refresh refused non-harness input drift: " + repr(changed))
        backup = out / ("receipt-before-harness-refresh-" + str(time.time_ns()) + ".json")
        backup.write_text(json.dumps(state, indent=2) + "\n")
        state.setdefault("harness_refreshes", []).append({"prior_receipt": str(backup),
            "prior_sha256": sha(backup), "changed_inputs": sorted(changed),
            "hardware_model_and_objects_rebuilt": False})
        state["inputs"] = frozen
        for name in ("coremark-link", "test-coremark"):
            state["steps"].pop(name, None)
        state["tests"].pop("coremark", None)
        state["artifacts"].pop(str(out / "coremark"), None)
    if state["inputs"] != frozen or tuple(state["parameters"]) != PARAMETERS:
        raise RuntimeError("Source/profile drift; use a fresh tag")

    def save():
        receipt.write_text(json.dumps(state, indent=2) + "\n")

    def guard():
        for path, digest in frozen.items():
            if sha(path) != digest:
                raise RuntimeError("Frozen input changed: " + path)
        for path, digest in state["artifacts"].items():
            if sha(path) != digest:
                raise RuntimeError("Checkpoint artifact changed: " + path)

    def command(cmd, name, timeout=600, expected=0, anchor=None):
        log = out / (name + ".log")
        attempt = 0
        while log.exists():
            attempt += 1
            log = out / (name + ".retry" + str(attempt) + ".log")
        print("+ " + " ".join(map(str, cmd)), flush=True)
        began = time.monotonic()
        with log.open("w") as stream:
            p = subprocess.run(list(map(str, cmd)), cwd=common.ROOT, stdout=stream,
                               stderr=subprocess.STDOUT, timeout=timeout,
                               env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = log.read_text()
        result = {"cmd": list(map(str, cmd)), "log": str(log), "log_sha256": sha(log),
                  "exit": p.returncode, "seconds": time.monotonic() - began}
        if p.returncode != expected or (anchor and anchor not in text):
            raise RuntimeError(str(log) + "\n" + text[-4000:])
        return result

    def step(name, cmd, products=(), **kwargs):
        guard()
        if name not in state["steps"]:
            record = command(cmd, name, **kwargs)
            state["commands"].append(record)
            state["steps"][name] = record
            for p in products:
                state["artifacts"][str(p)] = sha(p)
            save()
        return state["steps"][name]

    gsim, cxx = common.setup(False)
    flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    defines = ["-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000", "-DBOARD_UART_BAUD=460800",
               "-DUART_EXTRA_STOP_BITS=0", "-DDDR_MODEL=1", "-DBOARD_DDR_BYTES=2147483648ULL",
               "-DDDR_MULTI_ID_MODEL=1", "-DDDR_BENCHMARK_MODEL=1", "-DDDR_READ_CREDITS=8",
               "-DDDR_READ_LATENCY=32", "-DDDR_READ_BEAT_GAP=1", "-DBOARD_CYCLE_LIMIT=12000000ULL"]
    state["status"] = "RUNNING"
    state.pop("error", None)
    save()
    try:
        f = common.ROOT / "fpga/firmware"
        elf, image = fw / "rv64gc.elf", fw / "rv64gc.bin"
        step("gc-build", ["riscv64-unknown-elf-gcc", "-march=rv64gc", "-mabi=lp64d", "-mcmodel=medany",
             "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--build-id=none",
             "-Wl,--defsym=BOARD_RAM_BYTES=2147483648", "-Wl,--defsym=BOARD_MONITOR_BASE=4294934528",
             "-T", f / "sample_app.ld", f / "rv64gc_smoke.S", "-o", elf], [elf])
        step("gc-bin", ["riscv64-unknown-elf-objcopy", "-O", "binary", elf, image], [image])
        steady = fw / "steady.elf"
        step("steady-build", ["riscv64-unknown-elf-gcc", "-O2", "-march=rv64im_zicsr_zifencei",
             "-mabi=lp64", "-mcmodel=medany", "-mno-relax", "-msmall-data-limit=0", "-ffreestanding",
             "-fno-builtin", "-fno-stack-protector", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
             "-Wl,--gc-sections", "-ffunction-sections", "-fdata-sections", "-DCPU_HZ=100000000ULL",
             "-DUART_BAUD=460800", "-Wl,--defsym=BOARD_RAM_BYTES=2147483648",
             "-Wl,--defsym=BOARD_MONITOR_BASE=4294934528", "-T", f / "sample_app.ld",
             f / "sample_start.S", common.HERE / "payloads/board_memory_steady.c", "-lgcc", "-o", steady], [steady])
        step("steady-bin", ["riscv64-unknown-elf-objcopy", "-O", "binary", steady, fw / "steady.bin"], [fw / "steady.bin"])
        step("coremark-build", [sys.executable, f / "build_coremark.py", "--out", fw / "coremark",
             "--iterations", "1", "--clock-hz", "100000000", "--memory", "ddr",
             "--march", "rv64imc_zicsr_zifencei"], [fw / "coremark/coremark_board.bin", fw / "coremark/coremark_board.elf"])
        step("elaborate", ["mill", "-i", "IonSoC.test.runMain", "ooo.BoardSocGsimMain", model, *PARAMETERS], [model / "BoardSocGsim.fir"])
        step("generate", [gsim, "--threads=1", "--dir=" + str(model), model / "BoardSocGsim.fir"],
             timeout=900)
        fir = (model / "BoardSocGsim.fir").read_text()
        for token in ("module OwnerBankedPhysicalRegisterFile", "module BankedRobPayload",
                      "module MixedCoherentLineHome", "module NonBlockingCoherentLineCache"):
            if token not in fir:
                raise RuntimeError("Selected hardware not emitted: " + token)
        validate(common.ROOT, model / "BoardSocGsim.h", 2, "board$platform$privateCache$")
        sources = sorted(model.glob("BoardSocGsim[0-9]*.cpp"))
        if not sources:
            raise RuntimeError("GSIM generated no model units")
        for p in [model / "BoardSocGsim.h", *sources]:
            state["artifacts"].setdefault(str(p), sha(p))
        save()
        pending = [p for p in sources if "compile-" + p.stem not in state["steps"]]
        with ThreadPoolExecutor(max_workers=a.jobs) as pool:
            tasks = {p: pool.submit(command, [cxx, *flags, "-I" + str(model), "-c", p, "-o", p.with_suffix(".o")],
                                   "compile-" + p.stem, 900) for p in pending}
            for p, future in tasks.items():
                r = future.result()
                state["steps"]["compile-" + p.stem] = r
                state["commands"].append(r)
                state["artifacts"][str(p.with_suffix(".o"))] = sha(p.with_suffix(".o"))
                save()
        objects = [p.with_suffix(".o") for p in sources]
        harness = common.HERE / "harness"
        for name, source, extra in (
            ("gc", "rv64gc_board.cpp", []), ("coremark", "board_coremark.cpp", []),
            ("steady", "board_memory_steady.cpp", ["-DMODEL_MSHRS=2",
             "-DSTEADY_START_PC=" + str(marker(steady, "steady_start")) + "ULL",
             "-DSTEADY_STOP_PC=" + str(marker(steady, "steady_stop")) + "ULL"]),
            ("menu", "board_menu.cpp", ["-DBOARD_MENU_MONITOR=1"])):
            step(name + "-link", [cxx, *flags, *defines, *extra, "-I" + str(model),
                 harness / source, *objects, "-ldl", "-o", out / name], [out / name])
        cases = [("gc", [out / "gc", image], "RV64GC_BOARD_PASS", 0),
                 ("gc-negative", [out / "gc", image, "--inject-mismatch"], "firmware independent anchor/context failure", 1),
                 ("coremark", [out / "coremark", fw / "coremark/coremark_board.bin"], "GSIM compact board CoreMark: PASS", 0),
                 ("steady", [out / "steady", fw / "steady.bin"], "BOARD_MEMORY_STEADY_PASS", 0)]
        for case in ("crc", "diagnostics"):
            cases.append(("menu-" + case, [out / "menu", rom, case, rom.stat().st_size,
                          hex(zlib.crc32(rom.read_bytes()))], "MENU_RETURN_LOCK_PASS", 0))
        for name, cmd, anchor, expected in cases:
            r = step("test-" + name, cmd, timeout=900, anchor=anchor, expected=expected)
            state["tests"][name] = r
            save()
            print(Path(r["log"]).read_text()[-2500:], flush=True)
        guard()
        state["status"] = "PASS_SELECTED_BOARD_FUNCTIONAL"
        state["limitations"] = ["No measured FPGA timing/CDC", "No GMAC path in this CPU wrapper",
            "No Linux/FPU scheduler test", "CoreMark is one iteration, not a valid score",
            "No matched full-CPU performance baseline; archived gains are not claimed"]
    except BaseException as e:
        state["status"] = "FAIL"
        state["error"] = str(e)
        raise
    finally:
        save()
    print("PASS_SELECTED_BOARD_FUNCTIONAL " + str(receipt), flush=True)


if __name__ == "__main__":
    main()
