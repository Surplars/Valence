#!/usr/bin/env python3
"""Same IM binary with C front end enabled: cycle diagnostic, not a formal score or full-board benchmark."""
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
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--baseline", type=Path, help="Source/artifact-bound earlier SAME C-enabled configuration")
    ap.add_argument("--require-no-cycle-regression", action="store_true",
                    help="Reject a same-binary C-frontend ROI slowdown before promoting timing RTL")
    args = ap.parse_args()
    if args.require_no_cycle_regression and not args.baseline:
        ap.error("a matched --baseline is required for the no-regression gate")
    prior = json.loads(args.receipt.read_text())
    if prior["status"] != "PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY":
        ap.error("qualified timing-cut source required")
    for name, digest in prior["source_sha256"].items():
        if sha(ROOT / name) != digest:
            ap.error("source drift: " + name)
    baseline = ROOT / "build/gsim/inorder-pipeline-20261014-r3"
    base_proof = json.loads((baseline / "receipt.json").read_text())
    image = baseline / "coremark.bin"
    if sha(image) != base_proof["artifact_sha256"]["coremark.bin"]:
        ap.error("same-binary baseline drift")
    values = {s.split()[-1]: int(s.split()[0], 16) for s in
              (baseline / "coremark-symbols.txt").read_text().splitlines() if len(s.split()) == 3}
    output = args.output.resolve()
    if output.exists():
        ap.error("fresh evidence required")
    output.mkdir(parents=True)
    flags = ["--pipeline=fpga8", "--timing-cuts", "--dsp-tiled", "--early-memory-issue",
             "--overlap-write-lookup", "--icache=2048", "--dcache=2048", "--predictor=128", "--c"]
    earlier = None
    if args.baseline:
        earlier = json.loads(args.baseline.read_text())
        if (earlier["status"] != "PASS_SAME_IM_BINARY_C_FRONTEND_DIAGNOSTIC_ONLY" or
                earlier["flags"] != flags or earlier["image_sha256"] != sha(image)):
            ap.error("same C profile and immutable binary baseline required")
        for name, digest in earlier["artifact_sha256"].items():
            if sha(args.baseline.parent / name) != digest:
                ap.error("earlier C model/evidence drift: " + name)
    common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageCachedMain",
                output, "64", *flags], log=output / "elaborate.log")
    gs = Path("/home/openion/Valence/simulator/build/gsim-src")
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip() != common.LOCK["revision"]:
        raise RuntimeError("GSIM revision mismatch")
    gsim = gs / "build/gsim/gsim"
    if sha(gsim) != prior["tools"]["gsim_sha256"]:
        raise RuntimeError("GSIM executable drift")
    original_input = output / "FiveStageCachedCore.fir"
    gsim_input = original_input
    if original_input.stat().st_size % 4096 == 0:
        gsim_input = output / "FiveStageCachedCore.gsim-input.fir"
        gsim_input.write_bytes(original_input.read_bytes() + b"\n")
    common.run([gsim, "--threads=1", "--dir=" + str(output), gsim_input],
               log=output / "generate.log")
    cxx, identity = common.compiler()
    if identity != prior["tools"]["cxx"]:
        raise RuntimeError("compiler identity mismatch")
    binary = output / "run"
    common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-DDUT_XLEN=64", "-I" + str(output), *sorted(output.glob("FiveStageCachedCore[0-9]*.cpp")),
                ROOT / "simulator/gsim/harness/five_stage_coremark.cpp", "-o", binary],
               log=output / "compile.log", timeout=900)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    measurements = {}
    arguments = [image, hex(values["coremark_validation_errors"]), hex(values["coremark_elapsed_ticks"]),
                 hex(values["coremark_crcs"])]
    for delay in (1, 12):
        log = output / ("l" + str(delay) + ".log")
        common.run([binary, *arguments, delay], log=log, env=env, timeout=180)
        row = json.loads(log.read_text().strip().split(" ", 1)[1])
        reference = prior["benchmarks"]["timing-O3-l" + str(delay)]
        for field in ("trace_fnv64", "retired", "crcfinal", "roi_instructions"):
            if row[field] != reference[field]:
                raise RuntimeError("same IM instruction/register stream mismatch: " + field)
        measurements[str(delay)] = {
            "with_c_frontend": row, "without_c_frontend": reference,
            "extra_roi_cycles_percent": (row["roi_ticks"] / reference["roi_ticks"] - 1) * 100}
        if earlier:
            before = earlier["measurements"][str(delay)]["with_c_frontend"]
            for field in ("trace_fnv64", "retired", "crcfinal", "roi_instructions"):
                if before[field] != row[field]:
                    raise RuntimeError("same C-profile architectural stream mismatch: " + field)
            measurements[str(delay)]["earlier_same_c_frontend"] = before
            measurements[str(delay)]["same_c_roi_cycle_reduction_percent"] = (
                1 - row["roi_ticks"] / before["roi_ticks"]) * 100
            if args.require_no_cycle_regression and row["roi_ticks"] > before["roi_ticks"]:
                raise RuntimeError("same-frequency C-frontend O3 ROI regression at latency " + str(delay))
    bad = subprocess.run([str(binary), *map(str, arguments), "12", "--inject"], env=env,
                         capture_output=True, text=True, timeout=180, cwd=ROOT)
    (output / "negative.log").write_text(bad.stdout + bad.stderr)
    if bad.returncode == 0 or "independent register oracle mismatch" not in bad.stdout + bad.stderr:
        raise RuntimeError("independent mutation not rejected")
    for name, digest in prior["source_sha256"].items():
        if sha(ROOT / name) != digest:
            raise RuntimeError("source drift during fetch diagnostic: " + name)
    receipt = {"status": "PASS_SAME_IM_BINARY_C_FRONTEND_DIAGNOSTIC_ONLY",
               "gsim_receipt_sha256": sha(args.receipt), "flags": flags,
               "source_sha256": {str(Path(__file__).relative_to(ROOT)): sha(Path(__file__))},
               "image_sha256": sha(image), "compiler": identity, "measurements": measurements,
               "baseline": ({"path": str(args.baseline.resolve()), "sha256": sha(args.baseline)}
                            if args.baseline else None),
               "same_c_cycle_regression_allowed": not args.require_no_cycle_regression,
               "parser_input": {"original_sha256": sha(original_input), "parser_sha256": sha(gsim_input),
                                "newline_padding_bytes": int(gsim_input != original_input)},
               "negative": "PASS_REJECTED_INDEPENDENT_REGISTER_MUTATION",
               "scope": "SAME RV64IM O3 standard2000B binary, C decoder enabled but no compressed instructions; "
                        "no PMP/Sv39/SoC/FPU/physical qualification; not a formal >=10s CoreMark score",
               "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "measurements": measurements}))


if __name__ == "__main__":
    main()
