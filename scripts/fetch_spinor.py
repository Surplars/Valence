#!/usr/bin/env python3
"""Fetch or explicitly verify the locked Spinor snapshot within this workspace."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    lock = json.loads((ROOT / "simulator/gsim/config/spinor-integration.json").read_text())
    target = ROOT / lock["source_root"]
    if not args.verify_only:
        if target.exists():
            parser.error("snapshot already exists; use --verify-only")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--no-checkout", lock["repository"], target], check=True)
        subprocess.run(["git", "-C", target, "fetch", "--depth=1", "origin", lock["commit"]], check=True)
        subprocess.run(["git", "-C", target, "checkout", "--detach", lock["commit"]], check=True)
    head = subprocess.check_output(["git", "-C", target, "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", target, "status", "--porcelain"], text=True)
    if head != lock["commit"] or dirty:
        raise RuntimeError("Spinor source must be the clean locked commit")
    print("SPINOR_SOURCE_VERIFIED", head, target)


if __name__ == "__main__":
    main()
