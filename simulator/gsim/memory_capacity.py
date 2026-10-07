#!/usr/bin/env python3
"""Bounded opt-in selected-profile memoryEntries 2 -> 4 experiment.

No default replacement, full GSIM, Linux, synthesis or physical timing claims.
One candidate board model is reused for matched RVC CoreMark, DDR and RV64GC.
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
from analyze_frontend_perf import rows
from memory_capacity_geometry import verify_memory_geometry, verify_store_geometry

BASELINE = "staged-fetch-turnover"
CANDIDATE = "staged-fetch-turnover-mlp4"
RVC_HASH = "05b9a01d74a03389433ef942fef7056827331be18a91e0795f6456cee51fdac5"
PC_HASH = "142a5aafefa1eabaa2b76f5d7c42baa1cb31de1c6fd95384652ea4e936aa84fa"


def manifest(paths):
    return {str(p.relative_to(common.ROOT)): perf.sha256(p) for p in paths if p.is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--cancellation-proof", type=Path, help="Reuse byte-verified selected cancellation model/executable")
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("memory-capacity-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    source_paths = sorted((common.ROOT / "src").rglob("*.scala"))
    source_paths += sorted((common.HERE / "harness").glob("*"))
    source_paths += sorted(common.HERE.glob("*.py"))
    source_paths += sorted((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").rglob("*.scala"))
    before = manifest(source_paths)
    report = {"status": "RUNNING", "baseline_profile": BASELINE, "candidate_profile": CANDIDATE,
              "source_sha256": before, "changes": {"memory_entries": [2, 4], "lsu_request_fifo": [2, 4],
              "lsu_owner_fifo": [2, 4], "store_buffer_physical_owner_credits": [3, 5]},
              "fixed": {"issue_width": 2, "rename_width": 2, "commit_width": 2, "completion_width": 2,
              "rob": 16, "prf": 48, "tag_bits": 64, "predictor": 32, "store_write_entries": 2,
              "instruction_cache_lines": 32, "instruction_cache_bytes": 2048, "data_cache_ways": 2,
              "isa": "rv64gc", "fpu": True, "cpu_hz": 100000000, "uart_baud": 460800,
              "ddr_bytes": 2147483648, "load_issue_forwarding": False},
              "downstream_unchanged": {"translation_ingress": 2, "translated": 8, "checked": 2,
              "translation_owner": 8, "return_buffer": 2, "mapped_platform_owner": 8,
              "cache_hit_response": 2, "active_cache_misses": 1},
              "limits": ["No default change or physical timing/resource/board claim",
              "Bare-core fixture has ideal uncompressed instruction device and synthetic RAM; board covers exact frontend",
              "Existing two-slot owner ledgers are disabled, not generalized",
              "Scalar occupancy includes live loads/stores; accepted independent-load witness is separate",
              "Capacity-exclusion attribution is prior evidence, not projected cycles saved"], "core": {}}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        common.run(["mill", "-i", "IonSoC.test.testOnly", "ooo.MemoryCapacitySpec", "ooo.FetchTurnoverTimingSpec"], log=out / "contracts.log")
        common.run(["python3", "-m", "unittest", "discover", "-s", str(common.HERE),
                    "-p", "throughput_perf_test.py"], log=out / "parser-tests.log")
        common.run(["python3", "-m", "unittest", "discover", "-s", str(common.HERE),
                    "-p", "memory_capacity_geometry_test.py"], log=out / "geometry-tests.log")
        gsim, cxx = common.setup(False)
        report["toolchain_lock"] = common.LOCK
        report["compiler"] = subprocess.check_output([cxx, "--version"], text=True).splitlines()[0]
        # New selected-profile cancellation/reuse fixture is part of this bounded batch.
        if a.cancellation_proof:
            proof_path = a.cancellation_proof.resolve()
            proof = json.loads(proof_path.read_text())
            assert proof["status"] == "PASS_SELECTED_CANCELLATION"
            required = [*sorted((common.ROOT / "src/main/scala").rglob("*.scala")),
                        common.ROOT / "src/test/scala/ooo/MemoryCapacityBackendGsim.scala",
                        common.HERE / "harness/memory_capacity_backend.cpp"]
            assert proof["source_sha256"] == {str(p): perf.sha256(p) for p in required}
            assert all(perf.sha256(Path(p)) == digest for p, digest in proof["files_sha256"].items())
            cancellation = Path(proof["model_directory"])
            executable = Path(proof["executable"])
            model_files = [*cancellation.glob("MemoryCapacityBackendGsim.fir"), *cancellation.glob("MemoryCapacityBackendGsim.h"), *cancellation.glob("MemoryCapacityBackendGsim[0-9]*.cpp"), executable]
            assert all(str(p) in proof["files_sha256"] for p in model_files)
            report["cancellation_reuse_proof_sha256"] = perf.sha256(proof_path)
            log_dir = out / "cancellation-reused"
            log_dir.mkdir()
            common.run([executable], env=env, log=log_dir / "test.log", timeout=120)
        else:
            cancellation = common.test(gsim, cxx, str(out.relative_to(common.BUILD)) + "/cancellation",
                "ooo.MemoryCapacityBackendGsimMain", "MemoryCapacityBackendGsim", "memory_capacity_backend.cpp", defines={})
            executable = cancellation / "run"
            log_dir = cancellation
        report["cancellation_emitted_geometry"] = verify_memory_geometry(
            (cancellation / "MemoryCapacityBackendGsim.fir").read_text(), 4)
        result = subprocess.run([executable, "--inject-oracle-error"], env=env,
                                capture_output=True, text=True, timeout=120)
        (log_dir / "negative.log").write_text(result.stdout + result.stderr)
        assert result.returncode == 1 and "independent completion data mismatch for instruction 8" in result.stderr
        report["cancellation_log"] = (log_dir / "test.log").read_text()
        report["cancellation_model_sha256"] = manifest([*cancellation.glob("MemoryCapacityBackendGsim.fir"), *cancellation.glob("MemoryCapacityBackendGsim.h"), *cancellation.glob("MemoryCapacityBackendGsim[0-9]*.cpp"), executable])
        ref = reference()
        payloads = core_payloads(out)
        report["reference_sha256"] = perf.sha256(ref)
        report["core_payload_sha256"] = manifest(payloads)
        for profile, slots in ((BASELINE, 2), (CANDIDATE, 4)):
            model = common.test(gsim, cxx, str(out.relative_to(common.BUILD)) + "/" + profile,
                "ooo.ThroughputPerfGsimMain", "IntegerCoreGsim", "core.cpp", parameters=(profile,),
                runtime_args=(ref, *payloads, "--throughput-short"),
                defines={**perf.DEFINES, "MEMORY_ENTRIES": slots, "REGISTERED_FETCH_PACKET": 1},
                timeout=180, run_log="throughput.log")
            geometry = verify_memory_geometry((model / "IntegerCoreGsim.fir").read_text(), slots)
            measured = perf.parse_measurements((model / "throughput.log").read_text(),
                expected_geometry={"rob": 16, "physical": 48, "memory_entries": slots})
            report["core"][profile] = {"memory_entries": slots, "emitted_geometry": geometry, "measurements": measured,
                "model_sha256": manifest([*model.glob("*.fir"), *model.glob("*.h"), *model.glob("*.cpp"), model / "run"])}
            if slots == 4:
                for mode in ("timing-smoke", "pipeline-recovery", "memory-capacity"):
                    common.run([model / "run", ref, *payloads, "--" + mode], env=env,
                               log=model / (mode + ".log"), timeout=180)
                negative(model / "run", (ref, *payloads), "NEMU register mismatch", model / "negative.log")
                memory = (model / "memory-capacity.log").read_text()
                witness = [json.loads(line[4:]) for line in memory.splitlines() if line.startswith("IPC ")]
                independent = next(r for r in witness if r["name"] == "independent_loads" and r["memory_latency"] == 12)
                assert independent["max_outstanding"] == 4
                assert "GSIM memory capacity + NEMU: PASS slots=4 programs=6 " in memory
                report["selected_core_memory_witnesses"] = witness
        report["core_comparisons"] = perf.compare_measurements(*(report["core"][p]["measurements"] for p in (BASELINE, CANDIDATE)))
        # StoreBuffer uses exactly these five parameters; speculative range is the fixture's RAM.
        # Its default memoryEntries=4 is independently checked in the emitted FIR below.
        stores = common.test(gsim, cxx, str(out.relative_to(common.BUILD)) + "/store-buffer",
            "ooo.StoreBufferGsimMain", "StoreBufferGsim", "store_buffer.cpp", parameters=(2, "registered-owners"),
            defines={"BUFFER_ENTRIES": 2, "REGISTER_LOCAL_RESPONSE": 0})
        report["store_buffer_emitted_geometry"] = verify_store_geometry((stores / "StoreBufferGsim.fir").read_text(), 4)
        report["store_buffer_model_sha256"] = manifest([*stores.glob("*.fir"), *stores.glob("*.h"), *stores.glob("*.cpp"), stores / "run"])
        for mode, expected in (("inject-write-error", "platform violated guaranteed RAM write success"),
                               ("inject-read-mismatch", "load forwarding/value mismatch")):
            result = subprocess.run([stores / "run", "--" + mode], env=env, capture_output=True, text=True, timeout=120)
            (stores / (mode + ".log")).write_text(result.stdout + result.stderr)
            assert result.returncode != 0 and expected in result.stdout + result.stderr
        firmware = out / "firmware"
        shutil.copytree(common.BUILD / "frontend-perf-combined32-20261007/firmware", firmware)
        exact = common.BUILD / "coremark-rvc-20261007/rv64imc"
        for source in exact.glob("coremark_board.*"):
            shutil.copy2(source, firmware / source.name)
        assert perf.sha256(firmware / "coremark_board.bin") == RVC_HASH
        assert perf.sha256(firmware / "coremark_board.elf") == "5aed635e1e8678e0951de2c27ef20eed4051bc6f13a8025da6effee993e4ec26"
        report["firmware_sha256"] = manifest(firmware.glob("*"))
        common.run(["python3", common.HERE / "frontend_perf.py", "--tag", "mlp4-" + a.tag,
                    "--profile", CANDIDATE, "--instruction-cache-lines", "32", "--firmware-dir", firmware],
                   log=out / "board-runner.log", timeout=2400)
        board_dir = common.BUILD / ("frontend-perf-mlp4-" + a.tag)
        board_path = board_dir / "receipt.json"
        board = json.loads(board_path.read_text())
        assert board["status"] == "PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL"
        assert board["memory_entries"] == 4 and not board["backend_ownership_probes"]
        assert board["firmware_sha256"]["coremark_board.bin"] == RVC_HASH
        baseline_path = common.BUILD / "frontend-rvc-pair-20261007/receipt.json"
        baseline = json.loads(baseline_path.read_text())
        assert baseline["status"] == "PASS_MATCHED_RV64IMC_PAIR" and baseline["firmware_bin_sha256"] == RVC_HASH
        b = baseline["runs"]["combined32"]
        assert b["ticks"] == 486605 and b["counters"][1]["cycles"] == 486606
        c = board["board"]["board_coremark"]
        log = c["log"]
        def architectural_guest(text):
            guest = text.split("GSIM compact board CoreMark:", 1)[0].splitlines()
            return [line for line in guest if not line.startswith(("Total ticks", "Total time", "Iterations/Sec"))]
        assert architectural_guest(log) == architectural_guest((baseline_path.parent / "combined32.log").read_text())
        assert c["retired_pc_stream"]["sha256"] == b["retired_pc_stream_sha256"] == PC_HASH
        assert (board_dir / "board_coremark.retired-pcs.bin").read_bytes() == (baseline_path.parent / "combined32.retired-pcs.bin").read_bytes()
        assert [line for line in log.splitlines() if "crc" in line.lower()] == b["crc_lines"]
        assert c["counters"][1]["retired"] == b["counters"][1]["retired"] == 360528
        ticks = int(re.search(r"Total ticks\s*:\s*(\d+)", log)[1])
        live = rows(log, "MEMORY_LIVE")
        roi_live = {int(r["slots"]): int(r["cycles"]) for r in live if r["name"] == "coremark_roi"}
        assert set(roi_live) == set(range(5)) and sum(roi_live.values()) == c["counters"][1]["cycles"]
        report["board_comparison"] = {"baseline_ticks": b["ticks"], "candidate_ticks": ticks,
            "baseline_roi_cycles": b["counters"][1]["cycles"], "candidate_roi_cycles": c["counters"][1]["cycles"],
            "same_clock_speedup": b["ticks"] / ticks, "tick_reduction_percent": 100 * (b["ticks"] - ticks) / b["ticks"],
            "retired_pc_sha256": PC_HASH, "roi_live_slot_cycles": roi_live,
            "baseline_receipt_sha256": perf.sha256(baseline_path), "candidate_receipt_sha256": perf.sha256(board_path),
            "candidate_receipt": str(board_path)}
        report["status"] = "PASS_BOUNDED_MEMORY_CAPACITY_EXPERIMENT"
    except Exception as error:
        report["status"] = "FAIL_BOUNDED_MEMORY_CAPACITY_EXPERIMENT"
        report["failure"] = str(error)
        raise
    finally:
        if before != manifest(source_paths):
            report["status"] = "FAIL_SOURCE_DRIFT"
        report["artifact_sha256"] = manifest(p for p in out.rglob("*") if p.is_file() and p.name != "receipt.json")
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    assert report["status"] == "PASS_BOUNDED_MEMORY_CAPACITY_EXPERIMENT"
    print(json.dumps(report["board_comparison"], indent=2), flush=True)


if __name__ == "__main__":
    main()
