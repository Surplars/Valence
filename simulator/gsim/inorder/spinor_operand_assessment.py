#!/usr/bin/env python3
"""Check CPU scalar operands against Spinor's native Command; no CPU execution claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    output = parser.parse_args().output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        parser.error("fresh output within clone build/ required")
    values = json.loads((ROOT / "out/SpinorHost/test/runClasspath.json").read_text())["value"]
    paths = [Path(v.split(":", 3)[3]) for v in values]
    runtime = os.pathsep.join(str(p) for p in paths if p.exists())
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    locked = json.loads((ROOT / "simulator/gsim/config/spinor-integration.json").read_text())
    source = ROOT / locked["source_root"]
    names = [ROOT / "integration/spinor/src/main/scala/SpinorScalarOperands.scala",
             ROOT / "integration/spinor/src/test/scala/SpinorScalarOperandsMain.scala",
             ROOT / "simulator/gsim/harness/i1_spinor_operands.cpp", Path(__file__).resolve(),
             ROOT / "build.mill", ROOT / "simulator/gsim/config/spinor-integration.json",
             source / "src/main/scala/vpu/interface/Protocol.scala", source / "src/main/scala/vpu/config/Parameters.scala"]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in names}
    receipt = {"status": "RUNNING", "scope": __doc__, "source_sha256": frozen,
               "gsim_sha256": sha(gsim), "commands": []}

    def run(argv, log, negative=False):
        argv = list(map(str, argv)); receipt["commands"].append({"argv": argv, "log": log})
        with (output / log).open("w") as f:
            result = subprocess.run(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = (output / log).read_text()
        if negative:
            if result.returncode == 0 or "independent Spinor scalar operand ABI oracle mismatch" not in text:
                raise RuntimeError("negative was not rejected: " + log)
        elif result.returncode:
            raise RuntimeError("command failed: " + log)
        return text
    try:
        top = "SpinorScalarOperandsFixture"
        run(["java", "-cp", runtime, "spinor_integration.SpinorScalarOperandsMain", output], "elaborate.log")
        run([gsim, "--threads=1", "--dir=" + str(output), output / (top + ".fir")], "generate.log")
        run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-I" + str(output), *sorted(output.glob(top + "[0-9]*.cpp")),
             ROOT / "simulator/gsim/harness/i1_spinor_operands.cpp", "-o", output / "run"], "compile.log")
        receipt["summary"] = run([output / "run"], "positive.log").strip()
        for option in ["--truncate-token", "--zero-f0"]:
            run([output / "run", option], option[2:] + ".log", True)
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift: " + name)
        receipt["status"] = "PASS_NATIVE_SPINOR_SCALAR_OPERAND_AND_TOKEN_ORACLES"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error)); raise
    finally:
        receipt["artifact_sha256"] = {p.name: sha(p) for p in output.iterdir()
                                      if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], receipt["summary"], flush=True)


if __name__ == "__main__":
    main()
