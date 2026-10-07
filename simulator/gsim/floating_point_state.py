#!/usr/bin/env python3
"""Small FP transaction test; reuses an explicitly selected pinned GSIM binary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import run as common

source = Path(os.environ.get("GSIM_SOURCE", common.SOURCE)).resolve()
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
if revision != common.LOCK["revision"]:
    raise RuntimeError("GSIM revision mismatch")
if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True).strip():
    raise RuntimeError("GSIM source has tracked changes")
gsim = source / "build/gsim/gsim"
cxx, version = common.compiler()
output = common.test(gsim, cxx, "floating-point-state-m1", "ooo.FloatingPointStateGsimMain",
                     "FloatingPointStateGsim", "floating_point_state.cpp", timeout=30)
negative = subprocess.run([str(output / "run"), "--inject-mismatch"],
    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, capture_output=True, text=True, timeout=30)
(output / "negative.log").write_text(negative.stdout + negative.stderr)
if negative.returncode != 1 or "FP oracle mismatch" not in negative.stderr:
    raise RuntimeError("Negative control did not fail for the intended oracle mismatch")
inputs = [common.ROOT / "src/main/scala/core/ooo/FloatingPointState.scala",
          common.ROOT / "src/test/scala/ooo/FloatingPointStateGsim.scala",
          common.HERE / "harness/floating_point_state.cpp"]
(output / "receipt.json").write_text(json.dumps({"status": "PASS", "gsim_revision": revision,
    "compiler": version, "positive_exit": 0, "negative_exit": negative.returncode,
    "source_sha256": {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
    "limits": "Standalone state/transaction module; no CPU ISA, arithmetic, LSU, Linux or timing claim."}, indent=2)+"\n")
print("FP_STATE_M1_ACCEPTANCE: PASS (negative control rejected)")
