#!/usr/bin/env python3
"""Randomize typed FP instruction/format/rounding order on frozen numerical models."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import run as common


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--proof", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--seed", type=lambda x: int(x, 0), default=0xFDFD20261008)
    args = parser.parse_args()
    if not args.tag.replace("-", "").replace("_", "").isalnum():
        raise RuntimeError("unsafe tag")
    proof_path = args.proof.resolve()
    proof = json.loads(proof_path.read_text())
    if proof["status"] != "PASS_FUNCTIONAL_RESOURCE_CANDIDATE":
        raise RuntimeError("qualified frozen model receipt required")
    for name, expected in proof["artifact_sha256"].items():
        if digest(common.ROOT / name) != expected:
            raise RuntimeError("frozen model artifact changed: " + name)
    source = proof_path.parent / "vectors.txt"
    if digest(source) != proof["vector_sha256"]:
        raise RuntimeError("independent source vector hash mismatch")
    output = common.BUILD / ("fpga-fpu-mixed-" + args.tag)
    if (output / "receipt.json").exists():
        raise RuntimeError("preserve completed mixed-stream evidence")
    output.mkdir(parents=True, exist_ok=True)
    records = source.read_text().splitlines()
    mixed = list(records)
    random.Random(args.seed).shuffle(mixed)
    if Counter(records) != Counter(mixed):
        raise RuntimeError("mixed stream must preserve every exact oracle vector")
    vectors = output / "vectors.txt"
    vectors.write_text("\n".join(mixed) + "\n")
    functions = [(int(r.split()[0], 16) & 0xFE00007F, int(r.split()[1], 16)) for r in mixed]
    transitions = sum(a != b for a, b in zip(functions, functions[1:]))
    results, traces, executables = [], [], {}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    binaries = sorted({common.ROOT / p for p in proof["artifact_sha256"]
        if p.endswith("/run") and "-numerical-" in p})
    for binary in binaries:
        trace = output / (binary.parent.name + "-latency.txt")
        result = subprocess.run([str(binary), str(vectors), "fd", "--expected-vectors=" + str(len(mixed)),
            "--latency-trace=" + str(trace)], env=env, capture_output=True, text=True, timeout=300)
        (output / (binary.parent.name + ".log")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError("mixed typed stream failed: " + result.stderr)
        traces.append(trace.read_bytes())
        results.append({"model": binary.parent.name, "exit": 0, "log": result.stdout.strip()})
        executables[str(binary.relative_to(common.ROOT))] = digest(binary)
        print(result.stdout.strip(), flush=True)
    if len(traces) < 2 or len(set(traces)) != 1:
        raise RuntimeError("mixed-stream per-vector latency differs")
    receipt = {"status": "PASS_RANDOM_TYPED_FP_STREAM", "source_receipt": str(proof_path),
        "source_receipt_sha256": digest(proof_path), "oracle_vector_sha256": digest(source),
        "mixed_vector_sha256": digest(vectors), "seed": args.seed, "vectors": len(mixed),
        "opcode_format_rounding_transitions": transitions, "exact_vector_multiset_preserved": True,
        "executable_sha256": executables, "results": results,
        "latency_sha256": hashlib.sha256(traces[0]).hexdigest(),
        "limits": "Frozen direct numerical models. Architectural register-address randomization is covered separately by state tests."}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("FP_MIXED_TYPED_STREAM_PASS " + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
