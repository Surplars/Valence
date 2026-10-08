#!/usr/bin/env python3
"""Read-only expected-input verification. Any discrepancy exits nonzero."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, expected):
    root = root.resolve()
    def linked(path):
        parts = path.relative_to(root).parts
        return any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1))
    failures = []
    current = root / "inputs.json"
    if not current.is_file() or current.is_symlink():
        failures.append({"path": "inputs.json", "error": "missing or linked manifest"})
    elif digest(current) != expected["expected_inputs_json_sha256"]:
        failures.append({"path": "inputs.json", "error": "manifest hash mismatch", "actual": digest(current)})
    actual = set()
    for folder in expected["directories"]:
        directory = root / folder
        if not directory.is_dir() or linked(directory):
            failures.append({"path": folder, "error": "missing or linked directory"})
            continue
        for path in directory.rglob("*"):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                failures.append({"path": name, "error": "linked immutable input"})
            elif path.is_file():
                actual.add(name)
    required = set(expected["sha256"])
    for name in sorted(required - actual):
        failures.append({"path": name, "error": "missing"})
    for name in sorted(actual - required):
        failures.append({"path": name, "error": "unexpected input"})
    for name in sorted(required & actual):
        value = digest(root / name)
        if value != expected["sha256"][name]:
            failures.append({"path": name, "error": "hash mismatch", "actual": value,
                             "expected": expected["sha256"][name]})
    return {"status": "FAIL" if failures else "PASS_IMMUTABLE_INPUT_IDENTITY_ONLY",
            "root": str(root), "checked_files": len(required & actual), "failures": failures,
            "timing_or_hardware_qualified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected", type=Path, default=Path(__file__).with_name("expected-local-inputs.json"))
    args = parser.parse_args()
    result = verify(args.root, json.loads(args.expected.read_text()))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if not result["failures"] else 1)


if __name__ == "__main__":
    main()
