#!/usr/bin/env python3
"""Bounded combined frontend acceptance; reuse a byte-verified frozen CPU baseline."""
import argparse
import json
import os
from pathlib import Path
import re
from run import BUILD, HERE, ROOT, run, setup, test
from control_stage import core_payloads, negative, reference
import throughput_perf as perf


def firmware(output, stem):
    source = ROOT / "fpga/firmware"
    elf, image = output / (stem + ".elf"), output / (stem + ".bin")
    run(["riscv64-unknown-elf-gcc", "-march=rv64gc", "-mabi=lp64d", "-mcmodel=medany",
         "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax", "-Wl,--build-id=none",
         "-Wl,--defsym=BOARD_RAM_BYTES=536870912", "-T" + str(source / "sample_app.ld"),
         source / (stem + ".S"), "-o", elf], log=output / (stem + "-build.log"))
    run(["riscv64-unknown-elf-objcopy", "-O", "binary", elf, image])
    if stem == "fetch_permission_smoke":
        import subprocess
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", elf], text=True)
        found = {name:int(address, 16) for address, name in
                 re.findall(r"(?m)^([0-9a-f]+)\s+\w\s+(trap_entry|failure)$", symbols)}
        if set(found) != {"trap_entry", "failure"} or any(address % 4 for address in found.values()):
            raise RuntimeError("test mtvec entries are not actually 4-byte aligned")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("unsafe tag")
    name = "fetch-feedback-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    # Freeze DUT, relevant wrappers, firmware and harnesses, not only main RTL.
    inputs = [path for folder in ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala")
              for path in sorted((ROOT / folder).rglob("*.scala"))]
    inputs += [ROOT / "build.mill", Path(__file__), HERE / "run.py",
               *[HERE / "harness" / n for n in ("registered_fetch_packet.cpp", "pmp_checker.cpp", "core.cpp",
                                               "rv64gc_board.cpp", "board_boot.cpp")],
               *[ROOT / "fpga/firmware" / n for n in ("rv64gc_smoke.S", "fetch_permission_smoke.S", "sample_app.ld")]]
    def digest_inputs():
        return {str(p.relative_to(ROOT)):perf.sha256(p) for p in inputs}
    before = digest_inputs()
    report = {"status":"running", "profile":"staged-fetch-feedback", "issue_width":2,
              "source_sha256":before, "checks":{}, "profiles":{},
              "scope":"short queue/PMP/NEMU and shared-model production GC+permission smoke",
              "not_covered":["independent clock CPU simulation", "Ethernet packets/DMA", "Linux", "board timing"],
              "routed_timing_verified":False, "on_board_verified":False}
    env = {**os.environ, "ASAN_OPTIONS":"detect_leaks=0"}
    try:
        run(["mill", "-i", "IonSoC.test.testOnly", "ooo.FetchFeedbackTimingSpec", "ooo.EthernetTimingSpec"],
            log=output / "contracts.log")
        gsim, cxx = setup(False)
        for width, compressed in ((2, True), (2, False), (4, True)):
            stem = f"reservoir{width}-" + ("mixed" if compressed else "plain")
            model = test(gsim, cxx, name + "/" + stem, "ooo.RegisteredFetchPacketGsimMain",
                "RegisteredFetchPacketGsim", "registered_fetch_packet.cpp",
                parameters=(str(width), "parallel-validation", "hints32", "split-cursor",
                            "mixed" if compressed else "plain"),
                defines={"FETCH_WIDTH":width, "COMPRESSED":int(compressed), "HINT_ENTRIES":32})
            negative(model / "run", (), "fetch packet oracle mismatch", model / "negative.log")
            report["checks"][stem] = (model / "test.log").read_text()
        model = test(gsim, cxx, name + "/permission", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim",
                     "pmp_checker.cpp", parameters=("raw-prefix", "word-span", "balanced"), defines={})
        negative(model / "run", (), "PMP oracle mismatch", model / "negative.log")
        report["checks"]["permission"] = (model / "test.log").read_text()
        ref = reference()
        payloads = core_payloads(output)
        keys = perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)}
        previous = json.loads(args.baseline.read_text())
        baseline = previous["profiles"]["staged-ethernet"]
        old_model = Path(baseline["model_directory"])
        if (previous["status"] != "passed" or previous["reference_sha256"] != perf.sha256(ref) or
                previous["harness_sha256"] != perf.sha256(HERE / "harness/core.cpp") or
                baseline["executable_sha256"] != perf.sha256(old_model / "run") or
                baseline["model_fir_sha256"] != perf.sha256(old_model / "IntegerCoreGsim.fir")):
            raise RuntimeError("frozen baseline/reference/harness mismatch")
        run([old_model / "run", ref, *payloads, "--throughput-short"], env=env,
            log=output / "baseline-throughput.log", timeout=180)
        old_rows = perf.parse_measurements((output / "baseline-throughput.log").read_text(), 13, keys)
        if old_rows != baseline["measurements"]:
            raise RuntimeError("frozen baseline replay changed")
        report["profiles"]["staged-ethernet"] = {"measurements":old_rows,
            "reused_frozen_receipt_sha256":perf.sha256(args.baseline),
            "executable_sha256":perf.sha256(old_model / "run")}
        model = test(gsim, cxx, name + "/core", "ooo.ThroughputPerfGsimMain", "IntegerCoreGsim", "core.cpp",
            parameters=("staged-fetch-feedback",), runtime_args=(ref, *payloads, "--throughput-short"),
            defines={**perf.DEFINES, "REGISTERED_FETCH_PACKET":1, "FETCH_HINT_ALIAS_BENCH":1},
            timeout=180, run_log="throughput.log")
        for mode in ("--timing-smoke", "--pipeline-recovery"):
            run([model / "run", ref, *payloads, mode], env=env,
                log=model / (mode[2:] + ".log"), timeout=180)
        text = (model / "pipeline-recovery.log").read_text()
        witnesses = re.search(r"slot0HeldLane1Progress=(\d+) olderLane0BranchResolution=(\d+) aluForwardingHits=(\d+)", text)
        if not witnesses or not all(int(v) > 0 for v in witnesses.groups()):
            raise RuntimeError("missing independent issue/recovery witnesses")
        negative(model / "run", (ref, *payloads), "NEMU register mismatch", model / "negative.log")
        new_rows = perf.parse_measurements((model / "throughput.log").read_text(), 13, keys)
        report["profiles"]["staged-fetch-feedback"] = {"measurements":new_rows,
            "recovery_witnesses":list(map(int, witnesses.groups())),
            "model_fir_sha256":perf.sha256(model / "IntegerCoreGsim.fir"),
            "executable_sha256":perf.sha256(model / "run")}
        report["comparisons"] = perf.compare_measurements(old_rows, new_rows)
        gc = firmware(output, "rv64gc_smoke")
        permission = firmware(output, "fetch_permission_smoke")
        board = test(gsim, cxx, name + "/board", "ooo.BoardSocGsimMain", "BoardSocGsim", "rv64gc_board.cpp",
            parameters=("ddr", "100000000", "staged-fetch-feedback", "460800", "2", "2", "1", "rv64gc"),
            runtime_args=(gc,), defines={"UART_DIVISOR":1, "BOARD_CPU_HZ":100000000,
                "BOARD_UART_BAUD":460800, "UART_EXTRA_STOP_BITS":0, "DDR_MODEL":1}, timeout=120)
        negative(board / "run", (gc,), "firmware independent anchor/context failure", board / "negative-gc.log")
        run([board / "run", permission, "--fetch-permission"], env=env,
            log=board / "permission.log", timeout=120)
        negative(board / "run", (permission, "--fetch-permission"),
                 "firmware independent anchor/context failure", board / "negative-permission.log")
        report["checks"]["rv64gc"] = (board / "test.log").read_text()
        report["checks"]["permission_revoke_restore"] = (board / "permission.log").read_text()
        report["board_model"] = {"model_fir_sha256":perf.sha256(board / "BoardSocGsim.fir"),
                                 "executable_sha256":perf.sha256(board / "run")}
        report["status"] = "passed"
    except BaseException as error:
        report["status"] = "failed"
        report["failure"] = str(error)
        raise
    finally:
        if before != digest_inputs():
            report["status"] = "failed"
            report["failure"] = "source drift during batch"
        (output / "receipt.json").write_text(json.dumps(report, indent=2)+"\n")
    if report["status"] != "passed":
        raise RuntimeError(report["failure"])
    for row in report["comparisons"]:
        print(f"A/B {row['name']} RAM={row['memory_latency']} "
              f"cycles {row['baseline_cycles']} -> {row['candidate_cycles']}", flush=True)
    print(f"FETCH_FEEDBACK_SHORT_PASS receipt={output / 'receipt.json'}", flush=True)


if __name__ == "__main__":
    main()
