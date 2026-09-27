#!/usr/bin/env python3
"""Export a small Chisel design as a directory for native Windows Arcilator validation."""

from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = ROOT / "build/arcilator/smoke"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["mill", "-i", "IonSoC.test.runMain", "ooo.GsimSmokeMain", str(OUT)],
                   cwd=ROOT, check=True)
    firrtl = OUT / "GsimSmoke.fir"
    if not firrtl.is_file() or "circuit GsimSmoke" not in firrtl.read_text():
        raise SystemExit("Chisel did not produce the expected GsimSmoke circuit")
    for name in ("smoke.cpp", "compile-smoke.ps1"):
        shutil.copyfile(HERE / name, OUT / name)
    print(OUT)


if __name__ == "__main__":
    main()
