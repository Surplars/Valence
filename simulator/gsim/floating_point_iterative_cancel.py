#!/usr/bin/env python3
"""Add active iterative-cancellation evidence without changing frozen FP models."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--proof", action="append", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        raise RuntimeError("unsafe tag")
    output = common.BUILD / ("fpga-fpu-cancel-" + args.tag)
    if (output / "receipt.json").exists():
        raise RuntimeError("preserve completed evidence")
    output.mkdir(parents=True, exist_ok=True)
    cxx, compiler = common.compiler()
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    fixtures = [Path(__file__), common.HERE / "harness/floating_point_iterative_cancel.cpp",
        common.HERE / "harness/floating_point_full.cpp", common.HERE / "run.py"]
    before = {str(p.relative_to(common.ROOT)): digest(p) for p in fixtures}
    results, models, artifacts = [], {}, {}
    for proof_path in args.proof:
        proof_path = proof_path.resolve()
        proof = json.loads(proof_path.read_text())
        if proof["status"] != "PASS_FUNCTIONAL_RESOURCE_CANDIDATE":
            raise RuntimeError("unqualified hardware model receipt")
        # Check every frozen artifact, not just the chosen generated C++ model.
        for relative, expected in proof["artifact_sha256"].items():
            if digest(common.ROOT / relative) != expected:
                raise RuntimeError("frozen model artifact changed: " + relative)
        vectors = proof_path.parent / "vectors.txt"
        if digest(vectors) != proof["vector_sha256"]:
            raise RuntimeError("frozen independent vector file changed")
        directories = sorted({(common.ROOT / p).parent for p in proof["artifact_sha256"]
            if p.endswith("FloatingPointFullGsim0.cpp")})
        for source in directories:
            directory = output / source.name
            directory.mkdir(parents=True, exist_ok=True)
            sources = sorted(source.glob("FloatingPointFullGsim[0-9]*.cpp"))
            model = [source / "FloatingPointFullGsim.h", source / "FloatingPointFullGsim.fir", *sources]
            model_hashes = {str(p.relative_to(common.ROOT)): digest(p) for p in model}
            common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-I" + str(source), "-I" + str(common.HERE / "harness"),
                *sources, common.HERE / "harness/floating_point_iterative_cancel.cpp", "-ldl",
                "-o", directory / "run"], log=directory / "compile.log")
            common.run([directory / "run", vectors], env=env, log=directory / "test.log", timeout=120)
            negative = subprocess.run([str(directory / "run"), str(vectors), "--omit-cancel"],
                env=env, capture_output=True, text=True, timeout=30)
            if negative.returncode != 1 or "idle request credit" not in negative.stderr:
                raise RuntimeError("omitted cancellation negative control did not reject: " + negative.stderr)
            (directory / "negative.log").write_text(negative.stdout + negative.stderr)
            results.append({"test": source.name, "positive": (directory / "test.log").read_text().strip(),
                "negative": negative.stderr.strip(), "negative_exit": negative.returncode})
            print(results[-1]["positive"], flush=True)
            models[source.name] = {"receipt": str(proof_path), "receipt_sha256": digest(proof_path),
                "vector_sha256": digest(vectors), "model_sha256": model_hashes}
            if model_hashes != {str(p.relative_to(common.ROOT)): digest(p) for p in model}:
                raise RuntimeError("frozen model changed during cancellation proof")
            for path in directory.iterdir():
                if path.is_file():
                    artifacts[str(path.relative_to(common.ROOT))] = digest(path)
    after = {str(p.relative_to(common.ROOT)): digest(p) for p in fixtures}
    if before != after:
        raise RuntimeError("cancellation fixture changed during proof")
    (output / "receipt.json").write_text(json.dumps({"status": "PASS_ACTIVE_ITERATIVE_CANCELLATION",
        "compiler": compiler, "fixture_sha256": before, "models": models, "results": results,
        "artifact_sha256": artifacts,
        "limits": "Frozen GSIM models only; no new hardware generation, synthesis or timing claim."}, indent=2) + "\n")
    print("FP_ITERATIVE_CANCELLATION_PROOF_PASS " + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
