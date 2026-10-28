#!/usr/bin/env python3
"""Read-only gate for the exact qualified two-issue model/object; never rebuilds."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("control", "candidate"), required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--object", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(not args.out.exists(), "output already exists; do not overwrite evidence")
    pins = json.loads((HERE / "pinned-inputs.json").read_text())
    for relative, expected in pins["fixture_files"].items():
        require(sha(HERE / relative) == expected, "fixture source drift: " + relative)
    for relative, expected in pins["repository_inputs"].items():
        require(sha(ROOT / relative) == expected, "shared repository input drift: " + relative)
    model = pins["models"][args.role]
    require(sha(args.receipt) == model["object_receipt_sha256"], "qualified object receipt drift")
    receipt = json.loads(args.receipt.read_text())
    require(receipt["role"] == args.role and receipt["compiler_sha256"] == pins["tools"]["compiler"]["sha256"], "role/compiler mismatch")
    require(receipt["status"] == "PASS_FRESH_OBJECT_BUILD_NO_CPU_EXECUTION" and not receipt["hardware_generation"], "unexpected object receipt status/scope")
    require(receipt["flags"] == pins["host_flags"], "object compiler flags mismatch")
    for key, filename in (("generated_cpp_sha256", model["cpp_name"]), ("generated_header_sha256", model["header_name"])):
        require(sha(args.model_dir / filename) == model[key] == receipt[key], "generated model bytes mismatch: " + filename)
    require(sha(args.object) == model["object_sha256"] == receipt["object_sha256"], "compiled model object mismatch")
    alias = HERE / "aliases" / args.role / "CommonA1BenchmarkGsim.h"
    require(sha(alias) == pins["fixture_files"][str(alias.relative_to(HERE))], "model alias mismatch")
    result = {"status": "PASS_EXACT_MODEL_OBJECT_BINDING_ONLY", "role": args.role,
              "object_sha256": sha(args.object), "receipt_sha256": sha(args.receipt),
              "DUT_generated": False, "CPU_executed": False, "pins_sha256": sha(HERE / "pinned-inputs.json")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("BRANCH_MODEL_BINDING_FAIL " + str(error), file=sys.stderr)
        sys.exit(1)
