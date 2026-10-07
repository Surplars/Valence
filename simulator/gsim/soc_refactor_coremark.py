#!/usr/bin/env python3
"""Same-binary one-iteration tick comparison on two cached production board models.

No model generation, full GSIM, Linux or CAD. This is a CRC/performance regression,
not a valid CoreMark score, hardware measurement, or three-issue qualification.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cached_board(path, current):
    proof = json.loads(path.read_text())
    assert proof["status"] == "PASS_BOARD_FUNCTIONAL_SMOKE"
    assert (proof["isa"], proof["issue_width"], proof["clock_profile_hz"], proof["uart_baud"],
            proof["timing_profile"]) == ("rv64imafdc_zicsr_zifencei", 2, 100000000, 460800,
                                         "staged-fetch-feedback")
    # Historical A is deliberately old hardware, not reusable current CPU evidence.
    if current:
        for name, digest in proof["source_sha256"].items():
            assert sha(common.ROOT / name) == digest, "Current model source drift: " + name
    for mapping in (proof["files"], proof["gsim_models_sha256"]):
        for name, digest in mapping.items():
            assert sha(common.ROOT / name) == digest, "Cached board artifact drift: " + name
    fir = [common.ROOT / name for name in proof["files"] if Path(name).name == "BoardSocGsim.fir"]
    assert len(fir) == 1, "Exactly one cached production board model required"
    return fir[0].parent, proof


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--current", type=Path, required=True)
    a = ap.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", a.tag), "Unsafe tag"
    out = common.BUILD / ("soc-refactor-coremark-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    sources = [common.HERE / "harness/board_coremark.cpp", common.HERE / "harness/board_boot.cpp",
               common.HERE / "run.py", Path(__file__), common.ROOT / "fpga/firmware/build_coremark.py"]
    sources += sorted((common.ROOT / "fpga/firmware/coremark_port").glob("*"))
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in sources if p.is_file()}
    receipt = dict(status="RUNNING", source_sha256=before, isa="rv64gc", issue_width=2,
                   cpu_hz=100000000, uart_baud=460800, model_generation=False,
                   measurements={}, model_receipts={}, limits=[
                       "One iteration CRC/ticks only; NOT a valid CoreMark score or FPGA measurement.",
                       "Static independent DDR latency/backpressure model; not actual MIG/DRAM latency.",
                       "Historical model A is not proof for current sources.",
                       "No Linux context scheduling, asynchronous CDC or three-issue qualification."])
    try:
        _, cxx = common.setup(False)
        firmware = out / "firmware"
        common.run([sys.executable, common.ROOT / "fpga/firmware/build_coremark.py", "--out", firmware,
                    "--iterations", "1", "--clock-hz", "100000000", "--memory", "ddr"],
                   log=out / "firmware-build.log", timeout=180)
        image = firmware / "coremark_board.bin"
        receipt["image_sha256"] = sha(image)
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
        for name, proof_path in (("baseline", a.baseline.resolve()), ("current", a.current.resolve())):
            model, proof = cached_board(proof_path, current=name == "current")
            binary = out / (name + "-run")
            # Only a different bounded harness is compiled; FIR/C++ is the exact
            # cached production model. Never overwrite its passed binary or logs.
            common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", "-DUART_DIVISOR=1", "-DBOARD_CPU_HZ=100000000",
                        "-DBOARD_UART_BAUD=460800", "-DUART_EXTRA_STOP_BITS=0", "-DDDR_MODEL=1",
                        "-I" + str(model), *sorted(model.glob("BoardSocGsim[0-9]*.cpp")),
                        common.HERE / "harness/board_coremark.cpp", "-ldl", "-o", binary],
                       log=out / (name + "-compile.log"), timeout=600)
            log = out / (name + ".log")
            common.run([binary, image], env=env, log=log, timeout=180)
            text = log.read_text()
            found = re.search(r"GSIM compact board CoreMark: PASS ticks=(\d+) imageBytes=(\d+) "
                              r"cyclesWithUart=(\d+) readBursts=(\d+) writeBursts=(\d+)", text)
            assert found, "Missing CRC/tick validation: " + name
            receipt["measurements"][name] = dict(zip(
                ("ticks", "image_bytes", "cycles_with_uart", "read_bursts", "write_bursts"),
                map(int, found.groups())))
            receipt["model_receipts"][name] = dict(path=str(proof_path), sha256=sha(proof_path),
                                                      model=str(model), scope="current" if name == "current" else "historical")
            # Recheck all cached artifacts after executing the extra driver.
            cached_board(proof_path, current=name == "current")
        assert before == {str(p.relative_to(common.ROOT)): sha(p) for p in sources if p.is_file()}
        old = receipt["measurements"]["baseline"]["ticks"]
        new = receipt["measurements"]["current"]["ticks"]
        receipt["tick_delta_percent"] = (new - old) * 100.0 / old
        receipt["same_frequency_throughput_ratio"] = old / new
        receipt["status"] = "PASS_SAME_BINARY_BOARD_COREMARK_COMPARE"
    except BaseException as error:
        receipt.update(status="FAILED", failure=str(error))
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], json.dumps(receipt["measurements"]),
          "tick_delta_percent=" + str(receipt["tick_delta_percent"]), flush=True)


if __name__ == "__main__":
    main()
