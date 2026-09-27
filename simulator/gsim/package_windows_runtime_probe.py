#!/usr/bin/env python3
"""Package existing GSIM-generated C++ models for a native Windows runtime probe.

This tests the generated models and harness on Windows. It does not port the
GSIM FIRRTL-to-C++ compiler or the Linux/NEMU differential-test library.
"""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build/gsim"
OUTPUT = ROOT / "build/gsim-windows-runtime-probe.zip"

CASES = {"smoke": (BUILD / "smoke", "GsimSmoke", "smoke.cpp")}


def main():
    files = []
    for case, (directory, top, harness) in CASES.items():
        model = sorted(directory.glob(f"{top}[0-9]*.cpp"))
        header = directory / f"{top}.h"
        driver = ROOT / "simulator/gsim/harness" / harness
        if not model or not header.is_file():
            raise SystemExit(f"Missing {case} model; run 'make gsim-smoke' first")
        files.extend((path, f"{case}/{path.name}") for path in [header, *model])
        files.append((driver, f"{case}/{harness}"))

    files.append((Path(__file__).with_name("run_windows_runtime_probe.bat"),
                  "run_windows_runtime_probe.bat"))
    files.append((Path(__file__).with_name("windows-runtime-probe.md"), "README.md"))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(OUTPUT, "w", compression=ZIP_DEFLATED) as archive:
        for source, destination in files:
            if source.suffix == ".bat":
                archive.writestr(destination, source.read_text().replace("\n", "\r\n"))
            else:
                archive.write(source, destination)
    print(OUTPUT)


if __name__ == "__main__":
    main()
