#!/usr/bin/env python3
"""M3 completed canonical join and actual four-slot turnover, not a CPU/PPA claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def negative(executable, output, flag, diagnostic, marker, hardware=False):
    result = subprocess.run([str(executable), flag], capture_output=True, text=True, timeout=60,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    target = output / (flag[2:] + ".log")
    target.write_text(log)
    assert (result.returncode != 0 if hardware else result.returncode == 1), (flag, result.returncode, log)
    assert marker in log and diagnostic in log, (flag, result.returncode, log)
    assert "assertion did not fire" not in log, (flag, log)
    assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log, log
    return {"flag": flag, "exit": result.returncode, "diagnostic": diagnostic, "marker": marker,
            "hardwareAssertion": hardware, "logSha256": sha(target)}


def build(gsim, cxx, output, main, top, driver):
    output.mkdir(parents=True)
    host = HERE / "harness" / driver
    common.run(["mill", "-i", "IonSoC.test.runMain", main, output], log=output / "elaborate.log")
    common.run([gsim, "--threads=1", f"--dir={output}", output / f"{top}.fir"], log=output / "generate.log")
    flags = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-I" + str(output)]
    # Reject actual generated-header API mismatches before compiling the model.
    common.run([cxx, *flags, "-fsyntax-only", host], log=output / "header-syntax.log")
    objects = []
    for source in [*sorted(output.glob(top + "[0-9]*.cpp")), host]:
        obj = output / (source.stem + ".o")
        common.run([cxx, *flags, "-c", source, "-o", obj], log=output / (source.stem + "-compile.log"))
        objects.append(obj)
    common.run([cxx, *flags, *objects, "-ldl", "-o", output / "run"], log=output / "link.log")
    common.run([output / "run"], env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"},
               timeout=60, log=output / "test.log")
    return {"firSha256": sha(output / (top + ".fir")), "headerSha256": sha(output / (top + ".h")),
            "executableSha256": sha(output / "run"), "log": (output / "test.log").read_text()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh evidence directory required"
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/M3CanonicalForwardPredicateGsim.scala",
        common.ROOT / "src/test/scala/ooo/CompletedCanonicalForwardGsim.scala",
        common.ROOT / "src/test/scala/platform/M3CompletedForwardProfileSpec.scala",
        HERE / "harness/m3_canonical_forward_predicate.cpp", HERE / "harness/completed_canonical_forward.cpp",
        HERE / "m3_completed_forwarding.py", HERE / "run.py",
    ]
    inputs = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    tool = sha(gsim)
    models, negatives = {}, []
    for label, emitter, top, host, marker in (
        ("predicate", "ooo.M3CanonicalForwardPredicateGsimMain", "M3CanonicalForwardPredicateGsim",
         "m3_canonical_forward_predicate.cpp", "M3_CANONICAL_PREDICATE_PASS "),
        ("turnover", "ooo.CompletedCanonicalForwardGsimMain", "CompletedCanonicalForwardGsim",
         "completed_canonical_forward.cpp", "A1_M3_COMPLETED_FORWARD_PASS "),
    ):
        directory = output / label
        models[label] = build(gsim, cxx, directory, emitter, top, host)
        assert models[label]["log"].count(marker) == 1, models[label]["log"]
        controls = [("--inject-result", "M3 predicate independent byte/owner/epoch oracle mismatch",
                     "INJECT M3 predicate result", False)] if label == "predicate" else [
            ("--inject-owner", "canonical forwarding replaces the same successful completed store with exact owner epoch and bytes",
             "A1_M3_INJECT owner", True),
            ("--inject-data", "canonical forwarding replaces the same successful completed store with exact owner epoch and bytes",
             "A1_M3_INJECT data", True),
            ("--inject-observation", "M3_ORACLE_DATA: independently extracted source bytes/sign extension differ",
             "A1_M3_INJECT observation", False),
        ]
        for flag, diagnostic, witness, hardware in controls:
            negatives.append({"model": label, **negative(directory / "run", directory, flag,
                                                          diagnostic, witness, hardware)})
    assert inputs == {str(path.relative_to(common.ROOT)): sha(path) for path in sources}, "source drift"
    assert tool == sha(gsim), "tool drift"
    receipt = {"status": "PASS_M3_COMPLETED_CANONICAL_COMPONENT_CONTRACTS", "sourceSha256": inputs,
               "gsimSha256": tool, "compiler": compiler, "models": models, "negativeControls": negatives,
               "contract": {"predicateLatency": 0, "predicateII": 1, "addedRequestCredits": 0,
                            "turnover": "same successful completed store slot only; held completion gives no credit"},
               "limits": ["No actual CPU cycle claim from component tests", "No arbitrary in-flight PMP/context mutation",
                          "No new timing, area, Fmax, 300MHz, board, or shared-DDR claim"]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS M3 completed canonical component contracts")


if __name__ == "__main__":
    main()
