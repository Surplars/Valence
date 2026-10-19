#!/usr/bin/env python3
"""Version board-only Tcl changes without replacing any synthesized hardware."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    args = parser.parse_args()
    root = args.board.resolve()
    if root.parent != Path("/mnt/e/VM/Share/Valence-rtl") or not root.name.startswith("orbital-i1-board-zu15eg-"):
        raise SystemExit("Not an isolated I1 real-board directory")
    here = Path(__file__).resolve().parent
    names = ("board_constraints.tcl", "network_cdc.tcl", "resume_board.tcl",
             "report_board.tcl", "inspect_board.tcl")
    manifest_path = root / "board-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # Do not allow a retry to conceal any changed RTL, ROM, pins, IP or other script.
    for name, digest in manifest["staged_sha256"].items():
        if sha(root / name) != digest:
            raise SystemExit(f"Staged input changed before revision: {name}")
    history = manifest.get("script_revisions", [])
    if not history and "script_revision" in manifest:
        history = [manifest["script_revision"]]
    number = len(history) + 1
    initial = root / ("board-manifest-initial.json" if number == 1 else
                      f"board-manifest-before-script-revision-{number}.json")
    if initial.exists():
        raise SystemExit("Preserve existing initial manifest")
    shutil.copy2(manifest_path, initial)
    revision = {
        "number": number,
        "reason": "Board-only Tcl endpoint corrections; constant IRQ proof and explicit async pad launch pins.",
        "initial_manifest_sha256": sha(initial),
        "hardware_and_pin_files_unchanged": True,
        "cpu_and_ip_synthesis_reused": True,
        "changed_scripts": {},
    }
    for name in names:
        source = here / name
        relative = f"scripts/{name}"
        previous = manifest["staged_sha256"].get(relative)
        shutil.copy2(source, root / relative)
        digest = sha(source)
        manifest["source_sha256"][str(source)] = digest
        manifest["staged_sha256"][relative] = digest
        revision["changed_scripts"][relative] = {"before": previous, "after": digest}
    manifest["script_revision"] = revision
    manifest["script_revisions"] = history + [revision]
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(revision, indent=2))


if __name__ == "__main__":
    main()
