#!/usr/bin/env python3
"""Run stock OpenSBI on the already source-qualified F/D SoC model."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sha

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--receipt", type=Path, required=True)
    ap.add_argument("--firmware", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    prior = json.loads(args.receipt.read_text())
    for name, digest in prior["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("qualified source drift: " + name)
    firmware = json.loads(args.firmware.read_text())
    for name, digest in firmware["files_sha256"].items():
        if sha(args.firmware.parent / name) != digest:
            raise RuntimeError("stock firmware drift: " + name)
    model = args.receipt.parent / "soc-fd-fpga8"
    for p in model.glob("FiveStageSoc*"):
        if p.is_file() and p.suffix in (".fir", ".o", ".cpp", ".h"):
            if sha(p) != prior["artifact_sha256"][str(p.relative_to(args.receipt.parent))]:
                raise RuntimeError("model bytes differ: " + str(p))
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh output required")
    output.mkdir(parents=True)
    cxx, identity = common.compiler()
    binary = output / "opensbi"
    common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-DDUT_XLEN=64", "-DI1_HAS_ROM=1",
                "-I" + str(model), *sorted(model.glob("FiveStageSoc[0-9]*.o")),
                ROOT / "simulator/gsim/harness/five_stage_opensbi.cpp", "-o", binary],
               log=output / "compile.log", timeout=900)
    segments = [args.firmware.parent / row["file"] for row in firmware["segments"]]
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    common.run([binary, *segments], env=env, log=output / "test.log", timeout=360)
    bad = subprocess.run([str(binary), *map(str, segments), "--wrong-handoff"], cwd=ROOT,
                         env=env, capture_output=True, text=True, timeout=360)
    (output / "negative.log").write_text(bad.stdout + bad.stderr)
    if bad.returncode == 0 or "independent stock OpenSBI handoff ledger oracle" not in bad.stdout + bad.stderr:
        raise RuntimeError("handoff negative not rejected")
    receipt = {"status": "PASS_STOCK_OPENSBI_FD_TIMING_S_HANDOFF_SHORT_ONLY",
               "gsim_receipt_sha256": sha(args.receipt), "firmware_manifest_sha256": sha(args.firmware),
               "compiler": identity, "physical_qualified": False, "linux_boot_qualified": False,
               "checks": {"boot": (output / "test.log").read_text().splitlines()[-1],
                          "negative": "PASS_REJECTED_WRONG_S_HANDOFF"},
               "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt["checks"]))
if __name__ == "__main__":
    main()
