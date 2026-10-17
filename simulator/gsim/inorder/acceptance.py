#!/usr/bin/env python3
"""Fresh short Orbital-I1 GSIM acceptance. No legacy/OoO simulation, Linux or Vivado."""
import argparse
import hashlib
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


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [ROOT / "build.mill", Path(__file__).resolve(), ROOT / "simulator/gsim/harness/five_stage.cpp",
             ROOT / "simulator/gsim/harness/five_stage_register_file.cpp"]
    for folder in ("src/main/scala/core/inorder", "src/main/scala/isa", "src/test/scala/inorder"):
        paths += sorted((ROOT / folder).glob("*.scala"))
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("five-stage-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite previous evidence")
    output.mkdir(parents=True)
    frozen = sources()
    receipt = {"status": "RUNNING", "scope": "New single-issue five-stage RV32/RV64 IM M-only core. "
        "Independent instruction/PC/register/store-byte/exception oracle and handshake checks. "
        "Not full ISA certification, Linux, cache, SoC integration, routed timing or board performance.",
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "source_sha256": frozen, "pipeline": ["IF", "ID", "EX", "MEM", "WB"], "variants": {}}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        source = Path(os.environ.get("VALENCE_GSIM_SOURCE", "/home/openion/Valence/simulator/build/gsim-src"))
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
        if revision != common.LOCK["revision"]:
            raise RuntimeError("GSIM revision mismatch")
        if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True):
            raise RuntimeError("pinned GSIM source is dirty")
        gsim = source / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["toolchain"] = {**common.LOCK, "compiler": version, "binary_sha256": sha(gsim)}
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")
        rf = output / "register-file"
        rf.mkdir()
        common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageRegisterFileMain", rf, 64],
                   log=rf / "elaborate.log")
        common.run([gsim, "--threads=1", f"--dir={rf}", rf / "SynchronousRegisterFile.fir"],
                   log=rf / "generate.log")
        common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                   "-I" + str(rf), *sorted(rf.glob("SynchronousRegisterFile[0-9]*.cpp")),
                   ROOT / "simulator/gsim/harness/five_stage_register_file.cpp", "-o", rf / "run"],
                   log=rf / "compile.log")
        common.run([rf / "run"], env=env, log=rf / "test.log")
        receipt["register_file"] = (rf / "test.log").read_text().strip()
        profiles = [("rv64-dsp", 64, True, []), ("rv64-iterative", 64, True, ["--iterative"]),
                    ("rv64-interlock", 64, True, ["--no-memory-bypass"]),
                    ("rv32-dsp", 32, True, []), ("rv64-no-m", 64, False, ["--no-m"]),
                    ("rv64-lutram", 64, True, ["--rf-distributed"])]
        for name, xlen, m, flags in profiles:
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageMain", out, xlen, *flags],
                       log=out / "elaborate.log")
            common.run([gsim, "--threads=1", f"--dir={out}", out / "FiveStageCore.fir"],
                       log=out / "generate.log")
            common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                       "-fno-sanitize-recover=all", f"-DDUT_XLEN={xlen}", f"-DDUT_HAS_M={int(m)}",
                       f"-DDUT_MEM_BYPASS={int('--no-memory-bypass' not in flags)}",
                       "-I" + str(out), *sorted(out.glob("FiveStageCore[0-9]*.cpp")),
                       ROOT / "simulator/gsim/harness/five_stage.cpp", "-o", out / "run"],
                       log=out / "compile.log")
            common.run([out / "run"], env=env, log=out / "test.log", timeout=120)
            result = (out / "test.log").read_text()
            if "FIVE_STAGE_PASS" not in result:
                raise RuntimeError("missing full short acceptance marker")
            negative = subprocess.run([out / "run", "--inject-register-mismatch"], env=env, cwd=ROOT,
                                      capture_output=True, text=True, timeout=60)
            (out / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode == 0 or "independent register oracle mismatch" not in negative.stderr:
                raise RuntimeError("independent register negative control did not reject")
            receipt["variants"][name] = {"xlen": xlen, "with_m": m, "arguments": flags,
                "cases": [line for line in result.splitlines() if line.startswith("FIVE_STAGE_CASE_PASS")],
                "summary": result.splitlines()[-1], "negative_rejected": True}
            print(receipt["variants"][name]["summary"], flush=True)
        if sources() != frozen:
            raise RuntimeError("source drift during acceptance")
        receipt["status"] = "PASS_FIVE_STAGE_INTEGER_FOUNDATION_ONLY"
    except BaseException as error:
        receipt["status"] = "FAILED"
        receipt["error"] = str(error)
        raise
    finally:
        receipt["artifacts_sha256"] = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}, indent=2))


if __name__ == "__main__":
    main()
