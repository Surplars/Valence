#!/usr/bin/env python3
"""Build an isolated explicit-edge GSIM candidate from the verified initialization epoch."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("fresh output under the approved clone build/ required")
    original, cxx = common.setup(False)
    source = output / "source"
    shutil.copytree(original.parents[2], source, ignore=shutil.ignore_patterns("build"))
    patch = ROOT / "simulator/gsim/tool_fixes/explicit-clock-edges.patch"
    subprocess.run(["git", "apply", "--check", patch], cwd=source, check=True)
    subprocess.run(["git", "apply", patch], cwd=source, check=True)
    with (output / "build.log").open("w") as log:
        subprocess.run(["make", "-j2", "CXX=" + cxx, "GSIM_VERSION=93b8cd23-explicit-edges", "build-gsim"],
                       cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
    print(source / "build/gsim/gsim")
    print("Candidate only: run qualify_clock_edges.py before hardware use.")


if __name__ == "__main__":
    main()
