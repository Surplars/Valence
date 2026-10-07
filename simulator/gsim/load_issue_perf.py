#!/usr/bin/env python3
"""Short two-issue integer NEMU + RV64GC/2GiB board performance evidence.

Runs one selected profile. Compare receipts only with identical payload hashes.
No CAD, Linux, full GSIM, asynchronous Ethernet model, or official CoreMark score.
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
from control_stage import core_payloads, reference, negative


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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--profile", choices=("staged-fetch-feedback", "staged-load-issue"), required=True)
    ap.add_argument("--firmware-dir", type=Path, help="Reuse the exact prior firmware directory for A/B")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("load-issue-perf-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "RUNNING", "profile": a.profile, "issue_width": 2,
              "isa": "rv64gc", "board_clock_hz": 100000000, "uart_baud": 460800,
              "ddr_bytes": 2147483648, "data_cache_ways": 2, "instruction_prefetch": True,
              "hardware_source_sha256": perf.hardware_sources(),
              "limitations": ["bare core is integer/uncompressed with ideal input and synthetic RAM",
                  "board uses real CPU/cache/TL/AXI but synthetic sparse AXI latency",
                  "no independently clocked Ethernet/CMU or DMA contention",
                  "one CoreMark iteration only, not an official score",
                  "50MHz firmware reporting constant; compare raw guest ticks, not printed rates",
                  "stall flags overlap and cannot be summed into a CPI stack",
                  "FPU coverage is short context/ISA smoke, not numerical throughput",
                  "no physical board, DDR PHY, routed timing, or Linux qualification"]}
    input_paths = [Path(__file__), common.HERE / "run.py", common.HERE / "harness/core.cpp",
        common.HERE / "harness/board_boot.cpp", common.HERE / "harness/performance_observer.h",
        common.ROOT / "src/test/scala/ooo/BoardSocGsimMain.scala",
        common.ROOT / "src/test/scala/ooo/ThroughputPerfGsim.scala"]
    input_paths += list((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    report["measurement_source_sha256"] = {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in input_paths}
    (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        ref = reference()
        payloads = core_payloads(out)
        report["reference_sha256"] = perf.sha256(ref)
        report["core_payload_sha256"] = {p.name: perf.sha256(p) for p in payloads}
        flags = {**perf.DEFINES, "REGISTERED_FETCH_PACKET": 1,
                 "FETCH_HINT_ALIAS_BENCH": 1, "SERIAL_LOAD_ALU_BENCH": 1}
        core = common.test(gsim, cxx, str(out.relative_to(common.BUILD)) + "/core",
            "ooo.ThroughputPerfGsimMain", "IntegerCoreGsim", "core.cpp", parameters=(a.profile,),
            runtime_args=(ref, *payloads, "--throughput-short"), defines=flags,
            timeout=180, run_log="throughput.log")
        keys = perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)} | {
            ("throughput_serial_load_alu_address", latency) for latency in (1, 12)}
        report["core"] = perf.parse_measurements((core / "throughput.log").read_text(),
            expected_programs=15, expected_keys=keys)
        for mode in ("timing-smoke", "pipeline-recovery"):
            common.run([core / "run", ref, *payloads, "--" + mode], env=env,
                       log=core / (mode + ".log"), timeout=180)
        negative(core / "run", (ref, *payloads), "NEMU register mismatch", core / "negative.log")
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
                    a.profile, "460800", "2", "2", "1", "rv64gc", "2147483648"], log=model / "elaborate.log")
        if "0h100200000" not in (model / "BoardSocGsim.fir").read_text():
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
        for stem, image in (("board_coremark", "coremark_board"), ("ddr_bench_app", "ddr_bench"), ("rv64gc_board", "rv64gc_smoke")):
            text = (common.HERE / "harness" / (stem + ".cpp")).read_text()
            for marker in ("#undef main", "Test test(rom);", "        return 0;"):
                if text.count(marker) != 1:
                    raise RuntimeError("Harness instrumentation anchor changed: " + marker)
            text = text.replace("#undef main", '#undef main\n#include "performance_observer.h"')
            text = text.replace("Test test(rom);", "Test test(rom);\n PerfObserver perf; perf.startPc=" +
                str(start if stem == "board_coremark" else 0) + "ULL; perf.endPc=" +
                str(stop if stem == "board_coremark" else 0) + "ULL;")
            anchor = "        bool passed = false;" if stem == "rv64gc_board" else "        for (size_t offset"
            pos = text.index(anchor)
            chain = """        struct Observers { PerfObserver *perf; void (*old)(SBoardSocGsim &,void *); void *context; } observers{&perf,test.observer,test.observerContext};
        test.observer=[](SBoardSocGsim &d,void *p){auto &o=*static_cast<Observers*>(p);PerfObserver::sample(d,o.perf);if(o.old)o.old(d,o.context);}; test.observerContext=&observers;
"""
            text = text[:pos] + chain + text[pos:]
            text = text.replace("        return 0;", "        perf.report();\n        return 0;")
            driver = out / (stem + ".cpp")
            driver.write_text(text)
            binary = out / stem
            common.run([cxx, *cflags, "-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000", "-DBOARD_UART_BAUD=460800",
                "-DUART_EXTRA_STOP_BITS=0", "-DDDR_MODEL=1", "-DBOARD_DDR_BYTES=2147483648ULL",
                "-DAPP_TIMEBASE_HZ=50000000", *objects, driver, "-ldl", "-o", binary], log=out / (stem + "-compile.log"))
            common.run([binary, firmware / (image + ".bin")], env=env, log=out / (stem + ".log"), timeout=600)
            log = (out / (stem + ".log")).read_text()
            report["board"][stem] = {"counters": board_rows(log, stem == "board_coremark"), "log": log}
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
                    common.HERE / "harness/performance_observer.h", common.ROOT / "src/test/scala/ooo/BoardSocGsimMain.scala",
                    common.ROOT / "src/test/scala/ooo/ThroughputPerfGsim.scala"]
        report["artifact_sha256"] = {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in tracked}
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL":
        raise RuntimeError(report["status"])
    print(out / "receipt.json")


if __name__ == "__main__":
    main()
