#!/usr/bin/env python3
"""Export a small Chisel design for native Windows Arcilator validation."""

import os
from pathlib import Path
import shutil
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "build/arcilator/smoke"
PACKAGE = ROOT / "build/arcilator-windows-smoke.zip"


def find_firtool():
    selected = os.environ.get("FIRTOOL") or shutil.which("firtool")
    if selected:
        return Path(selected)
    cached = sorted((Path.home() / ".cache/llvm-firtool").glob("*/bin/firtool"))
    if cached:
        return cached[-1]
    raise SystemExit("firtool not found; set FIRTOOL to its executable path")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["mill", "-i", "IonSoC.test.runMain", "ooo.GsimSmokeMain", str(OUT)],
                   cwd=ROOT, check=True)
    firrtl = OUT / "GsimSmoke.fir"
    hw_mlir = OUT / "GsimSmoke.mlir"
    subprocess.run([str(find_firtool()), str(firrtl), "--ir-hw", "-o", str(hw_mlir)],
                   cwd=ROOT, check=True)
    if "hw.module @GsimSmoke" not in hw_mlir.read_text():
        raise SystemExit("firtool did not produce the expected GsimSmoke HW module")
    with ZipFile(PACKAGE, "w", compression=ZIP_DEFLATED) as archive:
        for source in (firrtl, hw_mlir, HERE / "smoke.cpp", HERE / "README.md"):
            archive.write(source, source.name)
        archive.write(HERE / "compile-smoke.ps1", "compile-smoke.ps1")
    print(PACKAGE)


if __name__ == "__main__":
    main()
