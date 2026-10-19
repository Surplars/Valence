#!/usr/bin/env python3
"""One short C/A-default-OFF M-only ROM regression, independent of enabled-profile acceptance."""
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sources, sha

def main():
    output = ROOT / "build/gsim" / sys.argv[1]
    if output.exists() or output.parent != ROOT / "build/gsim":
        raise RuntimeError("fresh evidence basename required")
    output.mkdir()
    frozen = sources()
    cxx, _ = common.compiler()
    gsim = Path("/home/openion/Valence/simulator/build/gsim-src/build/gsim/gsim")
    flags = ["--icache=2048", "--dcache=2048", "--predictor=128", "--dsp-tiled",
             "--early-memory-issue", "--overlap-write-lookup"]
    common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageSocGsimMain", output, 64, *flags],
               log=output / "elaborate.log")
    fir = (output / "FiveStageSoc.fir").read_text()
    for module in ("FiveStageCompressed", "FiveStageFetchAligner", "FiveStageAtomicMemory", "FiveStageAddressTranslation"):
        if "module " + module in fir:
            raise RuntimeError("disabled hardware remained: " + module)
    common.run([gsim, "--threads=1", f"--dir={output}", output / "FiveStageSoc.fir"],
               log=output / "generate.log")
    common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-DDUT_XLEN=64", "-DI1_HAS_ROM=1", "-I" + str(output),
                *sorted(output.glob("FiveStageSoc[0-9]*.cpp")),
                ROOT / "simulator/gsim/harness/five_stage_soc.cpp", "-o", output / "run"],
               log=output / "compile.log")
    baseline = ROOT / "build/gsim/five-stage-privilege-20261014-r6/baseline.bin"
    common.run([output / "run", baseline, ROOT / "src/main/resources/inorder/bootrom.hex"],
               log=output / "test.log", env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
    if sources() != frozen:
        raise RuntimeError("source drift during default-OFF regression")
    receipt = {"status": "PASS_C_A_DEFAULT_OFF_M_ONLY_ROM_SOC", "source_sha256": frozen,
               "checker_sha256": sha(Path(__file__)), "payload_sha256": sha(baseline), "flags": flags,
               "physical_qualified": False, "test": (output / "test.log").read_text(),
               "artifact_sha256": {str(p.relative_to(output)): sha(p) for p in output.rglob("*") if p.is_file()}}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print(receipt["test"], flush=True)
if __name__ == "__main__":
    main()
