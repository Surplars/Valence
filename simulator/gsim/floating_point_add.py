#!/usr/bin/env python3
"""Pinned HardFloat FADD.S/FSUB.S vs independently built SoftFloat (GSIM only)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile
import run as common

REVISION = "a0c6494cdc11865811dec815d5c0049fba9d82a8"
ARCHIVE_SHA256 = "90493f9ad6c9760b2b1ca91251b8e7a3bb616b2935808d243e158a432a514f98"
output = common.BUILD / "floating-point-add-reference"
output.mkdir(parents=True, exist_ok=True)
archive = Path(os.environ.get("SOFTFLOAT_ARCHIVE", str(output / f"softfloat-{REVISION}.zip")))
if not archive.is_file():
    raise RuntimeError(f"Set SOFTFLOAT_ARCHIVE to pinned archive: https://codeload.github.com/ucb-bar/berkeley-softfloat-3/zip/{REVISION}")
if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
    raise RuntimeError("SoftFloat archive SHA256 mismatch")
source = output / "source"
prefix = f"berkeley-softfloat-3-{REVISION}/"
source_hashes = {}
with ZipFile(archive) as z:
    for entry in z.infolist():
        if entry.is_dir():
            continue
        if not entry.filename.startswith(prefix):
            raise RuntimeError("Unexpected SoftFloat archive prefix")
        relative = entry.filename[len(prefix):]
        target = (source / relative).resolve()
        if not target.is_relative_to(source.resolve()):
            raise RuntimeError("Unsafe archive member")
        data = z.read(entry)
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError(f"Modified reference source: {relative}")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        source_hashes[relative] = hashlib.sha256(data).hexdigest()

reference_build = source / "build/Linux-x86_64-GCC"
common.run(["make", "-j2"], cwd=reference_build, log=output / "softfloat-build.log")
common.run(["g++", "-std=c++20", "-O2", "-I" + str(source / "source/include"),
            common.HERE / "harness/floating_point_vectors.cpp", reference_build / "softfloat.a",
            "-o", output / "vectors"], log=output / "vector-build.log")
vectors = output / "vectors.txt"
common.run([output / "vectors", vectors], log=output / "vector-test.log")
print((output / "vector-test.log").read_text(), end="", flush=True)

gsim_source = Path(os.environ.get("GSIM_SOURCE", common.SOURCE)).resolve()
read_env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gsim_source, text=True, env=read_env).strip()
if revision != common.LOCK["revision"] or subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gsim_source, text=True, env=read_env).strip():
    raise RuntimeError("GSIM source/revision mismatch")
gsim = gsim_source / "build/gsim/gsim"
cxx, version = common.compiler()
results = []
for name, main, top, harness, negative_reason in [
    ("floating-point-add-m2", "ooo.FloatingPointAddGsimMain", "FloatingPointAddGsim", "floating_point_add.cpp", "FP add mismatch: SoftFloat value"),
    ("floating-point-add-state-m2", "ooo.FloatingPointAddStateGsimMain", "FloatingPointAddStateGsim", "floating_point_add_state.cpp", "FP integration mismatch: SoftFloat value"),
]:
    test_output = common.test(gsim, cxx, name, main, top, harness, runtime_args=(vectors,), timeout=60)
    negative = subprocess.run([str(test_output / "run"), str(vectors), "--inject-mismatch"],
        env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, capture_output=True, text=True, timeout=30)
    (test_output / "negative.log").write_text(negative.stdout + negative.stderr)
    if negative.returncode != 1 or negative_reason not in negative.stderr:
        raise RuntimeError(f"{name}: negative control did not reject intended value mismatch")
    results.append({"test": name, "positive_exit": 0, "negative_exit": 1,
                    "positive": (test_output / "test.log").read_text().strip(), "negative": negative.stderr.strip()})
inputs = [common.ROOT / "build.mill", common.HERE / "floating_point_add.py",
          common.HERE / "run.py", common.HERE / "config/floating-point-dependencies.json"]
inputs += list((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").glob("*.scala"))
inputs += [common.ROOT / p for p in ["src/main/scala/core/ooo/OooParams.scala",
    "src/main/scala/core/ooo/FloatingPointState.scala", "src/main/scala/core/ooo/FloatingPointAdd.scala",
    "src/test/scala/ooo/FloatingPointStateGsim.scala", "src/test/scala/ooo/FloatingPointAddGsim.scala"]]
inputs += [common.HERE / "harness" / p for p in ["floating_point_vectors.cpp", "floating_point_add.cpp", "floating_point_add_state.cpp"]]
(output / "receipt.json").write_text(json.dumps({"status": "PASS", "gsim_revision": revision,
    "compiler": version, "softfloat_revision": REVISION, "softfloat_archive_sha256": ARCHIVE_SHA256,
    "softfloat_specialization": "8086-SSE; after-rounding tininess; canonicalize output NaNs for RISC-V; explicit flags mapping",
    "softfloat_source_hashes": source_hashes,
    "vector_sha256": hashlib.sha256(vectors.read_bytes()).hexdigest(), "results": results,
    "source_sha256": {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    "limits": "FADD.S/FSUB.S producer and isolated state integration only. Synthetic register setup is not FP memory. No CPU F/D or board timing claim."}, indent=2)+"\n")
print("FP_ADD_M2_ACCEPTANCE: PASS (both negative controls rejected)")
