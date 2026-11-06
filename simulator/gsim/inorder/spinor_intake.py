#!/usr/bin/env python3
"""Build the locked real Spinor isolated top and run short native-port GSIM gates."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
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
    lock_path = ROOT / "simulator/gsim/config/spinor-integration.json"
    lock = json.loads(lock_path.read_text())
    source = ROOT / lock["source_root"]
    subprocess.run([sys.executable, ROOT / "scripts/fetch_spinor.py", "--verify-only"], check=True)
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    paths = [Path(v.split(":", 3)[3]) for v in
             json.loads((ROOT / "out/SpinorI1/runClasspath.json").read_text())["value"]]
    runtime = os.pathsep.join(str(p) for p in paths if p.exists())
    inputs = [Path(__file__).resolve(), lock_path, ROOT / "build.mill", ROOT / "scripts/fetch_spinor.py",
              ROOT / "simulator/gsim/harness/i1_spinor_intake.cpp", source / "tests/m61_isolated_driver.cc"]
    inputs += sorted((source / "src/main/scala").rglob("*.scala"))
    hardfloat = source / "third_party/berkeley-hardfloat/src/main/scala"
    for p in sorted(hardfloat.glob("*.scala")):
        local = ROOT / "third_party/berkeley-hardfloat/src/main/scala" / p.name
        if sha(p) != sha(local):
            raise RuntimeError("shared HardFloat differs: " + p.name)
        inputs += [p, local]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    receipt = {"status": "RUNNING", "scope": __doc__, "lock": lock, "source_sha256": frozen,
               "gsim_sha256": sha(gsim), "commands": [], "cpu_v_extension_qualified": False,
               "physical_qualified": False, "toolchain_note": "Unmodified pinned sources compiled with Valence Scala/Chisel; upstream numerical/physical qualifications are not inherited."}

    def run(argv, log, negative=None):
        argv = list(map(str, argv))
        receipt["commands"].append({"argv": argv, "log": log})
        with (output / log).open("w") as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = (output / log).read_text()
        if negative:
            if result.returncode == 0 or negative not in text:
                raise RuntimeError("negative was not rejected: " + str(output / log))
        elif result.returncode:
            raise RuntimeError("command failed: " + str(output / log))
        return text

    try:
        top = "I1SpinorIsolated"
        run(["java", "-cp", runtime, "vpu.GenerateIsolated", "--out", output, "--name", top,
             "--preset", "standard", "--fcsr-owner", "host", "--format", "fir"], "elaborate.log")
        raw = output / (top + ".fir")
        text = raw.read_text()
        if not re.search(r"\bwire old : UInt<64>", text) or re.search(r"\bi1_spinor_old\b", text):
            raise RuntimeError("unexpected pinned GSIM identifier normalization input")
        count = 0
        lines = []
        # Match upstream's alpha-only workaround for GSIM's reserved OLD token.
        # Preserve genuine memory read-under-write attributes verbatim.
        for line in text.splitlines(True):
            if not re.match(r"\s*smem\b", line):
                line, n = re.subn(r"\bold\b", "i1_spinor_old", line)
                count += n
            lines.append(line)
        normalized = output / (top + ".gsim.fir")
        normalized.write_text("".join(lines))
        receipt["normalization"] = {"kind": "ALPHA_RENAME_ONLY", "occurrences": count,
                                    "raw_sha256": sha(raw), "normalized_sha256": sha(normalized)}
        run([gsim, "--threads=1", "--dir=" + str(output), normalized], "generate.log")
        objects = []
        flags = [cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-I" + str(output)]
        for part in sorted(output.glob(top + "[0-9]*.cpp")):
            obj = part.with_suffix(".o")
            run([*flags, "-c", part, "-o", obj], part.stem + ".compile.log")
            objects.append(obj)
        run([*flags, "-DHOST_FCSR=1", "-DENABLE_FP=1", "-DDUT_CLASS=S" + top,
             '-DDUT_HEADER="' + top + '.h"', "-I" + str(source / "tests"), *objects,
             ROOT / "simulator/gsim/harness/i1_spinor_intake.cpp", "-ldl", "-o", output / "run"],
            "driver-compile.log")
        receipt["summary"] = run([output / "run"], "positive.log").strip()
        if "I1_SPINOR_NATIVE_INTAKE_PASS" not in receipt["summary"]:
            raise RuntimeError("missing native integration gate completion")
        for option, diagnostic in [("--wrong-grant", "EXPECTED wrong grant rejected without publication"),
                                   ("--wrong-rf", "RF mismatch"), ("--wrong-csr", "CSR mismatch")]:
            run([output / "run", option], option[2:] + ".log", diagnostic)
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift: " + name)
        receipt["status"] = "PASS_SPINOR_NATIVE_ISOLATED_PORTS_CONTEXT_MEMORY_FP_AND_THREE_NEGATIVES"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error))
        raise
    finally:
        receipt["artifact_sha256"] = {p.name: sha(p) for p in output.iterdir()
                                      if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], receipt["summary"], flush=True)


if __name__ == "__main__":
    main()
