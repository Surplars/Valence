#!/usr/bin/env python3
"""Diagnostic only: compare existing source/hash-bound OFF/ON models with dense CPU requests."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sha

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    prior = json.loads(args.receipt.read_text())
    # A failed candidate may be diagnosed, but is NEVER upgraded to PASS or
    # used to export RTL by this script. Preserve its exact failure and hash.
    if not prior.get("overlap_data_retirement"):
        ap.error("paired retirement candidate models required")
    for name, digest in prior["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift: " + name)
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh diagnostic output required")
    output.mkdir(parents=True)
    source = ROOT / "fpga/inorder/tests/retirement_stream.S"
    linker = ROOT / "simulator/gsim/inorder/soc_link.ld"
    for source_file, archived_name in ((source, "source-input.S"), (linker, "linker-input.ld"),
                                       (Path(__file__), "measurement-input.py")):
        shutil.copy2(source_file, output / archived_name)
    compile_flags = ["riscv64-unknown-elf-gcc", "-march=rv64imafdc_zicsr_zifencei", "-mabi=lp64",
                "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                "-T" + str(linker)]
    common.run([*compile_flags, source, "-o", output / "stream.elf"], log=output / "build.log")
    common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / "stream.elf",
                output / "stream.bin"], log=output / "objcopy.log")
    measurements = {}
    for enabled, name in ((False, "soc-fd-retirement-off"), (True, "soc-fd-fpga8")):
        model = args.receipt.parent / name
        for path in model.iterdir():
            if path.is_file() and (path.suffix in (".fir", ".h", ".o", ".cpp") or path.name == "privilege"):
                if sha(path) != prior["artifact_sha256"].get(str(path.relative_to(args.receipt.parent))):
                    ap.error("model/driver artifact drift: " + str(path))
        for mode in ("bare", "sv39"):
            log = output / (str(int(enabled)) + "-" + mode + ".log")
            common.run([model / "privilege", output / "stream.bin", "--" + mode + "-throughput"],
                       log=log, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=60)
            row = json.loads(log.read_text().strip().split(" ", 1)[1])
            measurements[str(int(enabled)) + "-" + mode] = row
    common.run([*compile_flags, "-DI1_DENSE_MUTATION=1", source, "-o", output / "wrong.elf"],
               log=output / "negative-build.log")
    common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / "wrong.elf",
                output / "wrong.bin"], log=output / "negative-objcopy.log")
    negative = {}
    for enabled, name in ((False, "soc-fd-retirement-off"), (True, "soc-fd-fpga8")):
        for mode in ("bare", "sv39"):
            bad = subprocess.run([str(args.receipt.parent / name / "privilege"),
                str(output / "wrong.bin"), "--" + mode + "-throughput"], cwd=ROOT,
                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, capture_output=True, text=True, timeout=60)
            key = str(int(enabled)) + "-" + mode
            (output / ("negative-" + key + ".log")).write_text(bad.stdout + bad.stderr)
            if bad.returncode == 0 or "independent S-mode streaming byte oracle" not in bad.stdout + bad.stderr:
                raise RuntimeError("dense stream independent data mutation not rejected: " + key)
            negative[key] = "PASS_REJECTED_GUEST_DATA_MUTATION"
    for mode in ("bare", "sv39"):
        on, off = measurements["1-" + mode], measurements["0-" + mode]
        for field in ("bytes", "axi_reads", "axi_writes"):
            if on[field] != off[field]:
                raise RuntimeError("paired dense stream traffic mismatch: " + mode + "/" + field)
    common.run([*compile_flags, "-DI1_DENSE_WRITE_ONLY=1", source, "-o", output / "write-only.elf"],
               log=output / "write-only-build.log")
    common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / "write-only.elf",
                output / "write-only.bin"], log=output / "write-only-objcopy.log")
    isolated = {}
    for enabled, name in ((False, "soc-fd-retirement-off"), (True, "soc-fd-fpga8")):
        for mode in ("bare", "sv39"):
            key = str(int(enabled)) + "-" + mode
            log = output / ("write-only-" + key + ".log")
            common.run([args.receipt.parent / name / "privilege", output / "write-only.bin",
                        "--" + mode + "-throughput"], log=log,
                       env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=60)
            isolated[key] = json.loads(log.read_text().strip().split(" ", 1)[1])
    if prior.get("read_only_data_retirement"):
        for mode in ("bare", "sv39"):
            if isolated["0-" + mode]["write_ticks"] != isolated["1-" + mode]["write_ticks"]:
                raise RuntimeError("read-only replacement changes isolated WRITE cycles: " + mode)
    result = {"status": "COMPLETE_RETIREMENT_DENSE_DIAGNOSTIC_ONLY_NOT_PROMOTION",
        "candidate_receipt_sha256": sha(args.receipt), "candidate_status": prior["status"],
        "candidate_error": prior.get("error"), "measurements": measurements, "negative": negative,
        "read_only_mode": prior.get("read_only_data_retirement", False), "isolated_write": isolated,
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (source, linker, Path(__file__))},
        "limits": "same one-owner CPU/cache; new unrolled binary, NOT comparable to old scalar loop or a formal score",
        "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["measurements"], indent=2))
if __name__ == "__main__":
    main()
