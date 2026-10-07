#!/usr/bin/env python3
"""Bounded real-CPU FP subset acceptance, then integer-only system regression."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import run as common

output = common.BUILD / "floating-point-cpu-m3"
output.mkdir(parents=True, exist_ok=True)
gsim_source = Path(os.environ.get("GSIM_SOURCE", common.SOURCE)).resolve()
env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "ASAN_OPTIONS": "detect_leaks=0"}
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gsim_source, env=env, text=True).strip()
if revision != common.LOCK["revision"]:
    raise RuntimeError("GSIM revision mismatch")
if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=gsim_source, env=env, text=True).strip():
    raise RuntimeError("GSIM source has tracked modifications")
gsim = gsim_source / "build/gsim/gsim"
reference_dir = common.BUILD / "floating-point-add-reference"
vectors = reference_dir / "vectors.txt"
reference_receipt = json.loads((reference_dir / "receipt.json").read_text())
if reference_receipt["status"] != "PASS" or hashlib.sha256(vectors.read_bytes()).hexdigest() != reference_receipt["vector_sha256"]:
    raise RuntimeError("Pinned M2 SoftFloat vectors missing or modified; run gsim-fp-add-test first")
cxx, compiler = common.compiler()

def negative(directory, args, reason):
    p = subprocess.run([str(directory / "run"), *map(str, args)], env=env,
                       capture_output=True, text=True, timeout=60)
    (directory / "negative.log").write_text(p.stdout + p.stderr)
    if p.returncode != 1 or reason not in p.stderr:
        raise RuntimeError("Negative control did not fail for intended mismatch: " + str(directory))

common.test(gsim, cxx, output.name, "ooo.FloatingPointCpuGsimMain", "FloatingPointCpuGsim",
            "floating_point_cpu.cpp", runtime_args=(vectors,), timeout=60)
negative(output, (vectors, "--inject-mismatch"), "FP CPU mismatch: commit value/metadata")
if "--cpu-only" in sys.argv:
    print("FP_CPU_M3_SUBSET: PASS (negative rejected; integer regression pending)")
    raise SystemExit(0)

nemu = Path(os.environ["NEMU_REFERENCE"])
nemu_receipt = json.loads(Path(os.environ["NEMU_RECEIPT"]).read_text())
lock = json.loads((common.HERE / "config/reference-lock.json").read_text())
if nemu_receipt["revision"] != lock["revision"] or hashlib.sha256(nemu.read_bytes()).hexdigest() != nemu_receipt["library_sha256"]:
    raise RuntimeError("NEMU reference provenance mismatch")
regressions = []
for mode in ["disabled", "enabled"]:
    directory = common.test(gsim, cxx, "fp-integer-"+mode+"-m3", "ooo.FloatingPointIntegerRegressionGsimMain",
        "MachineCoreGsim", "machine.cpp", parameters=(mode,), defines={}, runtime_args=(nemu,), timeout=120)
    negative(directory, (nemu, "--inject-mismatch"), "commit data/nextPC")
    regressions.append({"mode": mode, "positive_exit": 0, "negative_exit": 1,
                        "log": str((directory / "test.log").relative_to(common.ROOT))})

paths = list((common.ROOT / "src/main/scala/core/ooo").glob("*.scala"))
paths += list((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").glob("*.scala"))
paths += [common.ROOT / p for p in ["build.mill", "src/test/scala/ooo/FloatingPointCpuGsim.scala",
          "src/test/scala/ooo/MachineCoreGsim.scala"]]
paths += [common.HERE / p for p in ["floating_point_cpu.py", "run.py", "harness/floating_point_cpu.cpp",
    "harness/machine.cpp", "harness/isa_model.h", "harness/muldiv_model.h", "harness/reference.h"]]
(output / "receipt.json").write_text(json.dumps({"status": "PASS", "gsim_revision": revision,
    "compiler": compiler, "softfloat_revision": reference_receipt["softfloat_revision"],
    "vector_sha256": reference_receipt["vector_sha256"], "nemu_library_sha256": nemu_receipt["library_sha256"],
    "cpu_positive": (output / "test.log").read_text(), "cpu_negative_exit": 1, "integer_regressions": regressions,
    "source_sha256": {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
    "limits": "Experimental FMV.W.X/FMV.X.W/FADD.S/FSUB.S only; misa F/D disabled; no memory/D/board timing claim."}, indent=2)+"\n")
print("FP_CPU_M3_ACCEPTANCE: PASS (real CPU, both integer configurations, strict negatives)")
