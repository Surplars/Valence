#!/usr/bin/env python3
"""Affected FP CPU + current-profile board checks; never a full GSIM/Linux run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    a = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.tag):
        ap.error("Unsafe tag")
    out = common.BUILD / ("rv64gc-native-" + a.tag)
    out.mkdir(parents=True, exist_ok=False)
    inputs = [p for base in ("src/main/scala", "third_party/berkeley-hardfloat/src/main/scala")
              for p in sorted((common.ROOT / base).rglob("*.scala"))]
    inputs += [common.ROOT / "build.mill", Path(__file__), common.HERE / "rv64gc_board.py", common.HERE / "run.py"]
    inputs += [common.ROOT / "src/test/scala/ooo" / name for name in
               ("FloatingPointCpuGsim.scala", "FloatingPointFullGsim.scala", "BoardSocGsimMain.scala", "ManagedBoardSocMain.scala")]
    inputs += [common.HERE / "harness" / name for name in
               ("floating_point_full_cpu.cpp", "rv64gc_board.cpp", "board_boot.cpp")]
    inputs += [common.ROOT / "fpga/firmware" / name for name in ("rv64gc_smoke.S", "sample_app.ld")]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in inputs}
    (out / "inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    reference_dir = common.BUILD / "floating-point-full-20261004-nan-cut-r1"
    reference = json.loads((reference_dir / "receipt.json").read_text())
    vectors = reference_dir / "vectors.txt"
    if reference["status"] != "PASS_FUNCTIONAL_CANDIDATE" or sha(vectors) != reference["vector_sha256"]:
        raise RuntimeError("Independent SoftFloat vector evidence mismatch")
    dependencies = json.loads((common.HERE / "config/floating-point-dependencies.json").read_text())
    for name, expected in dependencies["local_sources_sha256"].items():
        if sha(common.ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != expected:
            raise RuntimeError("HardFloat source drift: " + name)
    gsim, cxx = common.setup(False)
    cpu = common.test(gsim, cxx, "rv64gc-native-" + a.tag + "-cpu",
                      "ooo.FloatingPointFullCpuGsimMain", "FloatingPointCpuGsim", "floating_point_full_cpu.cpp",
                      runtime_args=(vectors,), defines={}, timeout=120)
    negative = subprocess.run([str(cpu / "run"), str(vectors), "--inject-mismatch"],
                              env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
                              capture_output=True, text=True, timeout=120)
    (out / "cpu-negative.log").write_text(negative.stdout + negative.stderr)
    if negative.returncode != 1 or "FP full CPU mismatch: independent integer result" not in negative.stderr:
        raise RuntimeError("FP CPU negative control did not reject the intended mismatch")
    common.run(["python3", common.HERE / "rv64gc_board.py", "--tag", a.tag,
                "--profile", "staged-fetch-feedback"], log=out / "board-runner.log", timeout=1200)
    board_receipt = common.BUILD / ("rv64gc-board-" + a.tag) / "receipt.json"
    board = json.loads(board_receipt.read_text())
    if board["status"] != "PASS_BOARD_FUNCTIONAL_SMOKE" or board["timing_profile"] != "staged-fetch-feedback":
        raise RuntimeError("Current-profile board proof missing")
    if before != {str(p.relative_to(common.ROOT)): sha(p) for p in inputs}:
        raise RuntimeError("Hardware or oracle changed during short batch")
    result = {"status": "PASS_RV64GC_NATIVE_AFFECTED_SHORT", "isa": "rv64gc", "issue_width": 2,
              "cpu_hz": 100000000, "uart_baud": 460800, "timing_profile": "staged-fetch-feedback",
              "source_sha256": before, "vectors_sha256": sha(vectors),
              "independent_reference_receipt_sha256": sha(reference_dir / "receipt.json"),
              "cpu_log": (cpu / "test.log").read_text(), "cpu_negative_exit": negative.returncode,
              "board_receipt": str(board_receipt), "board_receipt_sha256": sha(board_receipt),
              "board_log": board["log"],
              "cpu_artifact_sha256": {str(p.relative_to(common.ROOT)): sha(p) for p in cpu.iterdir()
                                      if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))},
              "limits": ["Two affected models only; not full GSIM, Linux or ISA certification.",
                         "Board model has current CPU/cache/AXI profile, not managed UART/GMAC CDC.",
                         "Native peripheral protocols/CDC require their separate unchanged proofs.",
                         "No FPGA timing/resource or real-board qualification."]}
    (out / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print("PASS_RV64GC_NATIVE_AFFECTED_SHORT", result["cpu_log"], result["board_log"], flush=True)


if __name__ == "__main__":
    main()
