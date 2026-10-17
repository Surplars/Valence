#!/usr/bin/env python3
"""One coherent short C/A module batch, independent of the ISA decoder/control under test."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sha

def sources():
    paths = [ROOT / "build.mill", ROOT / "AGENTS.md", Path(__file__)]
    paths += list((ROOT / "src/main/scala").rglob("*.scala"))
    paths += list((ROOT / "src/test/scala/inorder").rglob("*.scala"))
    paths += [ROOT / ("simulator/gsim/harness/" + f) for f in
              ("five_stage_compressed.cpp", "five_stage_fetch_aligner.cpp", "five_stage_atomic.cpp")]
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("five-stage-ca-units-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite evidence")
    output.mkdir(parents=True)
    frozen = sources()
    receipt = {"status": "RUNNING", "source_sha256": frozen, "checks": {}, "physical_qualified": False,
               "scope": "C exhaustive expansion, parcel alignment/errors, single-writer physical RAM LR/SC/AMO"}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")
        for width in (32, 64):
            for topic, main, top, driver, mutation, error in (
                    ("compressed", "FiveStageCompressedMain", "FiveStageCompressed", "five_stage_compressed.cpp",
                     "--wrong-expansion", "independent exhaustive C expansion oracle"),
                    ("parcels", "FiveStageFetchAlignerMain", "FiveStageFetchAligner", "five_stage_fetch_aligner.cpp",
                     "--wrong-parcel", "independent C parcel byte oracle"),
                    ("atomic", "FiveStageAtomicMain", "FiveStageAtomicMemory", "five_stage_atomic.cpp",
                     "--wrong-amo", "independent LR_SC_AMO result oracle")):
                name = topic + str(width)
                print("BUILD", name, flush=True)
                out = output / name
                out.mkdir()
                common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder." + main, out, width],
                           log=out / "elaborate.log")
                common.run([gsim, "--threads=1", f"--dir={out}", out / (top + ".fir")],
                           log=out / "generate.log")
                common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                            "-fno-sanitize-recover=all", f"-DDUT_XLEN={width}", "-I" + str(out),
                            *sorted(out.glob(top + "[0-9]*.cpp")), ROOT / "simulator/gsim/harness" / driver,
                            "-o", out / "run"], log=out / "compile.log", timeout=900)
                common.run([out / "run"], log=out / "test.log", env=env, timeout=120)
                receipt["checks"][name] = (out / "test.log").read_text().strip()
                print(receipt["checks"][name], flush=True)
                bad = subprocess.run([str(out / "run"), mutation], env=env, capture_output=True,
                                     text=True, timeout=120)
                (out / "negative.log").write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or error not in bad.stdout + bad.stderr:
                    raise RuntimeError("independent mutation was not rejected: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_INDEPENDENT_MUTATION"
        if sources() != frozen:
            raise RuntimeError("source drift during C/A units")
        receipt["status"] = "PASS_I1_C_A_MODULES_SHORT_ONLY"
    except Exception as error:
        receipt["status"] = "FAIL"; receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)
if __name__ == "__main__":
    main()
