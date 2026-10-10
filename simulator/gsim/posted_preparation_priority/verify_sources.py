#!/usr/bin/env python3
"""Check archived qualification-source bytes without loading their executors."""
import ast
import hashlib
import json
from pathlib import Path


def main():
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "source-origins.json").read_text())
    if manifest["schema"] != "posted-preparation-priority-tracked-source-origins-v1":
        raise SystemExit("Unknown qualification source manifest")
    entries = manifest["snapshots"]
    expected = {entry["path"] for entry in entries}
    if len(entries) != len(expected):
        raise SystemExit("Duplicate qualification source manifest entry")
    actual = {str(p.relative_to(root)) for p in (root / "source_snapshots").rglob("*") if p.is_file()}
    if actual != expected:
        raise SystemExit("Qualification snapshot inventory changed")
    for entry in entries:
        path = root / entry["path"]
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise SystemExit("Qualification snapshot bytes changed: " + entry["path"])
        if path.suffix == ".py":
            ast.parse(path.read_text(), filename=str(path))
        elif path.suffix == ".json":
            json.loads(path.read_text())
    wrapper = root.parents[2] / manifest["wrapper"]["path"]
    if hashlib.sha256(wrapper.read_bytes()).hexdigest() != manifest["wrapper"]["sha256"]:
        raise SystemExit("Tracked focused wrapper differs from executed snapshot")
    print(json.dumps({"status": "PASS_QUALIFICATION_SOURCE_SNAPSHOTS_ONLY", "files": len(entries),
                      "tracked_wrapper_byte_identity": True,
                      "DUT_executed": False, "runtime_reverified": False}))


if __name__ == "__main__":
    main()
