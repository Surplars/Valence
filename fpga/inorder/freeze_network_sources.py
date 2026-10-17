#!/usr/bin/env python3
"""Retain exact source bytes for a long-running, already-exported OOC candidate."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    manifest_path = args.package.resolve() / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    if manifest["status"] != "PASS_SHORT_TESTED_NETWORK_RTL_EXPORT_ONLY":
        ap.error("existing exactly qualified export required")
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        ap.error("fresh in-worktree build archive required")
    groups = {key: manifest[key] for key in ("source_sha256", "exporter_sha256", "source_resources")}
    files = {}
    for group in groups.values():
        for name, digest in group.items():
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                ap.error("relative source name required")
            if name in files and files[name] != digest:
                ap.error("conflicting source digests")
            files[name] = digest
            if sha(ROOT / name) != digest:
                ap.error("source already drifted: " + name)
    output.mkdir(parents=True)
    for name, digest in files.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
        if sha(target) != digest:
            ap.error("source changed while archiving: " + name)
    result = {"status": "FROZEN_QUALIFIED_NETWORK_SOURCE_BYTES_ONLY",
              "rtl_manifest_sha256": sha(manifest_path), "groups": groups,
              "files_sha256": files,
              "scope": "Exact historical candidate bytes; no qualification of future workspace edits",
              "physical_qualified": False, "board_qualified": False}
    (output / "receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    print("FROZEN_NETWORK_SOURCES", len(files), output,
          "receipt_sha256=" + sha(output / "receipt.json"))


if __name__ == "__main__":
    main()
