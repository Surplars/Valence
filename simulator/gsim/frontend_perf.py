#!/usr/bin/env python3
"""Passive frontend attribution with one reused RV64GC/2GiB board model.

Runs one selected profile. Compare receipts only with identical payload hashes.
No core rebuild, CAD, Linux, full GSIM, asynchronous Ethernet model, or official CoreMark score.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import run as common
import throughput_perf as perf
from control_stage import negative
from memory_capacity_geometry import verify_memory_geometry


def board_rows(text, roi_allowed):
    rows = []
    for line in text.splitlines():
        if not line.startswith("BOARD_IPC "):
            continue
        row = dict(item.split("=", 1) for item in line.split()[1:])
        if not roi_allowed and not row["name"].startswith("whole_run_"):
            continue
        row = {key: value if key == "name" else float(value) if key == "ipc" else int(value)
               for key, value in row.items()}
        if (row["zero_commit"] + row["single_commit"] + row["dual_commit"] != row["cycles"] or
                row["single_commit"] + 2 * row["dual_commit"] != row["retired"]):
            raise RuntimeError("Board retirement histogram mismatch")
        rows.append(row)
    return rows


def verify_instruction_geometry(fir, lines):
    block = re.search(r"^  module InstructionLineCache\s*:.*?(?=^  (?:module|extmodule) |\Z)", fir, re.M | re.S)
    if not block:
        raise RuntimeError("InstructionLineCache module missing from emitted FIR")
    body = block[0]
    sets = lines // 2
    tag_bits = 58 - (sets.bit_length() - 1)
    facts = [f"regreset valid : UInt<1>[2][{sets}]", f"reg tags : UInt<{tag_bits}>[2][{sets}]",
             f"smem data_0 : UInt<512>[{sets}]", f"smem data_1 : UInt<512>[{sets}]"]
    if not all(fact in body for fact in facts) or len(re.findall(r"smem data_\d+ :", body)) != 2:
        raise RuntimeError("Emitted instruction-cache geometry does not match requested capacity")
    return {"status": "PASS_EMITTED_GEOMETRY", "facts": facts, "sets": sets, "ways": 2,
            "line_bits": 512, "tag_bits": tag_bits, "capacity_bytes": sets*2*64}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--profile", choices=("staged-fetch-feedback", "staged-load-issue", "staged-fetch-turnover", "staged-fetch-turnover-mlp4"), required=True)
    ap.add_argument("--firmware-dir", type=Path, help="Reuse the exact prior firmware directory for A/B")
    ap.add_argument("--instruction-cache-lines", type=int, choices=(8, 32), default=8)
    ap.add_argument("--coremark-only", action="store_true", help="Refresh passive baseline telemetry without repeating unchanged DDR/GC controls")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("frontend-perf-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    memory_entries = 4 if a.profile == "staged-fetch-turnover-mlp4" else 2
    report = {"memory_entries": memory_entries, "backend_ownership_probes": False, "status": "RUNNING", "profile": a.profile, "issue_width": 2,
              "workload_scope": "coremark_only" if a.coremark_only else "coremark_ddr_gc",
              "isa": "rv64gc", "board_clock_hz": 100000000, "uart_baud": 460800,
              "ddr_bytes": 2147483648, "data_cache_ways": 2, "instruction_prefetch": True,
              "instruction_line_cache": {"bytes": 64*a.instruction_cache_lines, "lines": a.instruction_cache_lines, "line_bytes": 64, "sets": a.instruction_cache_lines//2, "ways": 2},
              "fetch_packet_words": 2, "effective_instruction_line_prefetch": False,
              "instruction_prefetch_semantics": "requested flag true; line prefetch requires four-word fetch and is disabled here",
              "hardware_source_sha256": perf.hardware_sources(),
              "limitations": ["board uses real CPU/cache/TL/AXI but synthetic sparse AXI latency",
                  "no independently clocked Ethernet/CMU or DMA contention",
                  "one CoreMark iteration only, not an official score",
                  "50MHz firmware reporting constant; compare raw guest ticks, not printed rates",
                  "stall flags overlap and cannot be summed into a CPI stack",
                  "FPU coverage is short context/ISA smoke, not numerical throughput",
                  "no physical board, DDR PHY, routed timing, or Linux qualification"]}
    input_paths = [Path(__file__), common.HERE / "run.py", common.HERE / "harness/core.cpp",
        common.HERE / "harness/board_boot.cpp", common.HERE / "harness/frontend_observer.h", common.HERE / "harness/performance_observer.h",
        common.ROOT / "src/test/scala/ooo/BoardSocGsimMain.scala",
        common.ROOT / "src/test/scala/ooo/ThroughputPerfGsim.scala"]
    input_paths.append(common.HERE / "memory_capacity_geometry.py")
    if memory_entries == 4:
        input_paths.append(common.HERE / "harness/memory_capacity_observer.h")
    input_paths += list((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    report["measurement_source_sha256"] = {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in input_paths}
    (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        report["toolchain_lock"] = common.LOCK
        report["cxx_version"] = subprocess.check_output([cxx, "--version"], text=True).splitlines()[0]
        firmware = out / "firmware"
        if a.firmware_dir:
            shutil.copytree(a.firmware_dir.resolve(), firmware)
        else:
            common.coremark_setup(False)
            common.run(["python3", common.ROOT / "fpga/firmware/build_coremark.py", "--out", firmware,
                        "--iterations", "1", "--clock-hz", "50000000", "--memory", "ddr"],
                       log=out / "coremark-build.log")
            common.run(["python3", common.ROOT / "fpga/firmware/build_ddr_bench.py", "--out", firmware],
                       log=out / "ddr-build.log")
            source = common.ROOT / "fpga/firmware"
            common.run(["riscv64-unknown-elf-gcc", "-march=rv64gc", "-mabi=lp64d", "-mcmodel=medany",
                        "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--build-id=none",
                        "-Wl,--defsym=BOARD_RAM_BYTES=536870912", "-T" + str(source / "sample_app.ld"),
                        source / "rv64gc_smoke.S", "-o", firmware / "rv64gc_smoke.elf"], log=out / "gc-build.log")
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", firmware / "rv64gc_smoke.elf",
                        firmware / "rv64gc_smoke.bin"])
        report["firmware_sha256"] = {p.name: perf.sha256(p) for p in firmware.glob("*.bin")}
        dis = subprocess.check_output(["riscv64-unknown-elf-objdump", "-d", firmware / "coremark_board.elf"], text=True)
        def rdtime(name):
            block = dis.split("<" + name + ">:", 1)[1].split("\n\n", 1)[0]
            return int(re.search(r"^\s*([0-9a-f]+):.*\brdtime\b", block, re.M)[1], 16)
        start, stop = rdtime("start_time"), rdtime("stop_time")
        report["coremark_roi"] = {"start_rdtime_retire_pc": hex(start), "stop_rdtime_retire_pc": hex(stop),
                                  "boundaries": "inclusive retirement cycles; guest timer sampling can differ"}
        model = out / "board-model"
        model.mkdir()
        common.run(["mill", "-i", "IonSoC.test.runMain", "ooo.BoardSocGsimMain", model, "ddr", "100000000",
                    a.profile, "460800", "2", "2", "1", "rv64gc", "2147483648", "1", str(a.instruction_cache_lines)], log=model / "elaborate.log")
        fir_text = (model / "BoardSocGsim.fir").read_text()
        report["memory_geometry_verification"] = verify_memory_geometry(fir_text, memory_entries)
        report["instruction_cache_geometry_verification"] = verify_instruction_geometry(fir_text, a.instruction_cache_lines)
        if "0h100200000" not in fir_text:
            raise RuntimeError("2GiB upper address bound missing from board FIR")
        common.run([gsim, "--threads=1", "--dir=" + str(model), model / "BoardSocGsim.fir"], log=model / "generate.log")
        cflags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                  "-I" + str(model), "-I" + str(common.HERE / "harness")]
        objects = []
        for source in sorted(model.glob("BoardSocGsim[0-9]*.cpp")):
            obj = source.with_suffix(".o")
            common.run([cxx, *cflags, "-c", source, "-o", obj], log=source.with_suffix(".compile.log"))
            objects.append(obj)
        report["board"] = {}
        workloads = [("board_coremark", "coremark_board")]
        if not a.coremark_only:
            workloads += [("ddr_bench_app", "ddr_bench"), ("rv64gc_board", "rv64gc_smoke")]
        for stem, image in workloads:
            text = (common.HERE / "harness" / (stem + ".cpp")).read_text()
            for marker in ("#undef main", "Test test(rom);", "        return 0;"):
                if text.count(marker) != 1:
                    raise RuntimeError("Harness instrumentation anchor changed: " + marker)
            text = text.replace("#undef main", '#undef main\n#include "frontend_observer.h"')
            text = text.replace("Test test(rom);", "Test test(rom);\n FrontendObserver perf; perf.startPc=" +
                str(start if stem == "board_coremark" else 0) + "ULL; perf.endPc=" +
                str(stop if stem == "board_coremark" else 0) + "ULL;")
            anchor = "        bool passed = false;" if stem == "rv64gc_board" else "        for (size_t offset"
            pos = text.index(anchor)
            chain = """        struct Observers { FrontendObserver *perf; void (*old)(SBoardSocGsim &,void *); void *context; } observers{&perf,test.observer,test.observerContext};
        test.observer=[](SBoardSocGsim &d,void *p){auto &o=*static_cast<Observers*>(p);FrontendObserver::sample(d,o.perf);if(o.old)o.old(d,o.context);}; test.observerContext=&observers;
"""
            text = text[:pos] + chain + text[pos:]
            text = text.replace("        return 0;", "        perf.report();\n        return 0;")
            if memory_entries == 4:
                text = text.replace("frontend_observer.h", "memory_capacity_observer.h").replace("FrontendObserver", "MemoryCapacityObserver")
            driver = out / (stem + ".cpp")
            driver.write_text(text)
            binary = out / stem
            common.run([cxx, *cflags, "-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000", "-DBOARD_UART_BAUD=460800",
                "-DUART_EXTRA_STOP_BITS=0", "-DDDR_MODEL=1", "-DBOARD_DDR_BYTES=2147483648ULL",
                "-DAPP_TIMEBASE_HZ=50000000", *objects, driver, "-ldl", "-o", binary], log=out / (stem + "-compile.log"))
            trace = out / (stem + ".retired-pcs.bin")
            run_env = {**env, "FRONTEND_RETIRE_TRACE": str(trace)} if stem == "board_coremark" else env
            common.run([binary, firmware / (image + ".bin")], env=run_env, log=out / (stem + ".log"), timeout=600)
            log = (out / (stem + ".log")).read_text()
            report["board"][stem] = {"counters": board_rows(log, stem == "board_coremark"), "log": log}
            if stem == "board_coremark":
                if not trace.is_file() or trace.stat().st_size == 0 or trace.stat().st_size % 8:
                    raise RuntimeError("Retired PC stream trace missing or malformed")
                report["board"][stem]["retired_pc_stream"] = {
                    "sha256": perf.sha256(trace), "instructions": trace.stat().st_size//8,
                    "path": str(trace.relative_to(common.ROOT)),
                    "encoding": "little-endian uint64 PC, ordered commit lanes, start/stop rdtime instructions inclusive",
                    "limitations": "PC sequence only; register/value correctness uses independent workload oracles"}
            if stem == "rv64gc_board":
                negative(binary, (firmware / (image + ".bin"),), "firmware independent anchor/context failure", out / "gc-negative.log")
        report["status"] = "PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL"
    except Exception as error:
        report["status"] = "FAIL_SHORT_PERFORMANCE"
        report["failure"] = str(error)
        raise
    finally:
        if (perf.hardware_sources() != report["hardware_source_sha256"] or
                report["measurement_source_sha256"] != {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in input_paths}):
            report["status"] = "FAIL_SOURCE_DRIFT"
        tracked = [*out.rglob("*.fir"), *out.rglob("*.cpp"), *out.rglob("*.h"), *out.rglob("*.log")]
        tracked += [Path(__file__), common.HERE / "harness/core.cpp", common.HERE / "harness/board_boot.cpp",
                    common.HERE / "harness/frontend_observer.h", common.HERE / "harness/performance_observer.h", common.ROOT / "src/test/scala/ooo/BoardSocGsimMain.scala",
                    common.ROOT / "src/test/scala/ooo/ThroughputPerfGsim.scala"]
        report["executable_sha256"] = {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in
            [*(out / "board-model").glob("*.o"), *(out / name for name in ("board_coremark", "ddr_bench_app", "rv64gc_board"))] if p.is_file()}
        report["artifact_sha256"] = {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in tracked}
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL":
        raise RuntimeError(report["status"])
    print(out / "receipt.json")


if __name__ == "__main__":
    main()
