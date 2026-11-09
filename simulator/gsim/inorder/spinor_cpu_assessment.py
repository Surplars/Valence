#!/usr/bin/env python3
"""Execute real I1 + Spinor on a same-clock GSIM fixture (physical RAM, no CDC acceptance)."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("fresh output within clone build/ required")
    values = json.loads((ROOT / "out/SpinorHost/test/runClasspath.json").read_text())["value"]
    runtime = os.pathsep.join(str(p) for v in values if (p := Path(v.split(":", 3)[3])).exists())
    subprocess.run([sys.executable, ROOT / "scripts/fetch_spinor.py", "--verify-only"], check=True)
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    source = ROOT / json.loads((ROOT / "simulator/gsim/config/spinor-integration.json").read_text())["source_root"]
    inputs = [ROOT / "build.mill", Path(__file__).resolve(),
              ROOT / "simulator/gsim/config/spinor-integration.json",
              ROOT / "simulator/gsim/harness/i1_spinor_cpu.cpp",
              ROOT / "simulator/gsim/harness/five_stage_coremark.cpp",
              ROOT / "simulator/gsim/harness/five_stage.cpp"]
    for directory in [source / "src/main/scala", ROOT / "src/main/scala/core/inorder",
                      ROOT / "integration/spinor", ROOT / "third_party/berkeley-hardfloat/src/main/scala"]:
        inputs += sorted(directory.rglob("*.scala"))
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    for p in inputs:
        target = output / "source-at-model" / p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, target)
    receipt = {"status": "RUNNING", "scope": __doc__, "source_sha256": frozen,
               "gsim_sha256": sha(gsim), "commands": [], "misa_v_advertised": False,
               "virtual_vector_memory_qualified": False, "physical_timing_qualified": False,
               "fixture_same_clock": True, "production_independent_cpu_vpu_clocks": True,
               "cdc_qualified": False, "soc_interconnect_present": False, "cmu_present": False}
    def run(argv, log, negative=False):
        argv = list(map(str, argv))
        receipt["commands"].append({"argv": argv, "log": log})
        with (output / log).open("w") as f:
            result = subprocess.run(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = (output / log).read_text()
        if negative:
            if result.returncode == 0 or "CPU vector independent" not in text:
                raise RuntimeError("negative not rejected: " + log)
        elif result.returncode:
            raise RuntimeError("command failed: " + log)
        return text
    try:
        top = "I1SpinorCoreFixture"
        run(["java", "-cp", runtime, "spinor_integration.I1SpinorCoreMain", output], "elaborate.log")
        raw = output / (top + ".fir")
        normalized = output / (top + ".gsim.fir")
        lines = []
        for line in raw.read_text().splitlines(True):
            if not re.match(r"\s*smem\b", line):
                line = re.sub(r"\bold\b", "i1_spinor_old", line)
            lines.append(line)
        normalized.write_text("".join(lines))
        receipt["normalization"] = {"kind": "ALPHA_RENAME_ONLY", "raw_sha256": sha(raw),
                                    "normalized_sha256": sha(normalized)}
        run([gsim, "--threads=1", "--dir=" + str(output), normalized], "generate.log")
        parts = sorted(output.glob(top + "[0-9]*.cpp"))
        flags = [cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-I" + str(output)]
        def compile_part(part):
            obj = part.with_suffix(".o")
            run([*flags, "-c", part, "-o", obj], part.stem + ".compile.log")
            return obj
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            objects = list(pool.map(compile_part, parts))
        run([*flags, *objects, ROOT / "simulator/gsim/harness/i1_spinor_cpu.cpp",
             "-o", output / "run"], "driver-compile.log")
        receipt["summary"] = run([output / "run"], "positive.log").strip()
        if receipt["summary"].count("I1_SPINOR_CPU_PASS") != 2:
            raise RuntimeError("missing both memory-service gates")
        for option in ["--inject-value", "--inject-flags"]:
            run([output / "run", option], option[2:] + ".log", True)
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift: " + name)
        receipt["status"] = "PASS_REAL_CPU_SPINOR_PHYSICAL_VECTOR_PROGRAM_AND_TWO_NEGATIVES"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error))
        raise
    finally:
        receipt["artifact_sha256"] = {p.name: sha(p) for p in output.iterdir() if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], receipt["summary"], flush=True)


if __name__ == "__main__":
    main()
