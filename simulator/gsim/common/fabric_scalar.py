#!/usr/bin/env python3
"""Bounded shared scalar-arbiter regression; qualified existing tools/classes only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bringup import (Guard, ROOT, HERE, sha, require, executable, classpath_manifest,
                     verify_classpath_unchanged, validate_qualification)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gsim-source", type=Path, required=True)
    parser.add_argument("--gsim-bin", required=True)
    parser.add_argument("--gsim-qualification", type=Path, required=True)
    parser.add_argument("--cxx", required=True)
    parser.add_argument("--java", required=True)
    parser.add_argument("--java-classpath-file", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    require(not out.exists(), "fresh output directory required")
    out.mkdir(parents=True)
    guard = Guard(out)
    receipt = {"status": "RUNNING", "scope": "shared two-lane scalar arbitration, actual response "
               "ownership and ordered reservation clear only; no CPU/CDC/board claim"}

    def save():
        receipt["steps"] = guard.records
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    try:
        source = args.gsim_source.resolve()
        binary = executable(args.gsim_bin, "gsim-bin")
        cxx = executable(args.cxx, "cxx")
        java = executable(args.java, "java")
        lock = json.loads((HERE / "config/toolchain.json").read_text())
        revision = guard.run("gsim-revision", ["git", "rev-parse", "HEAD"], cwd=source).strip()
        changed = guard.run("gsim-changed", ["git", "diff", "HEAD", "--name-only"], cwd=source).splitlines()
        diff = guard.run("gsim-patch", ["git", "diff", "HEAD", "--binary"], cwd=source)
        qualification = json.loads(args.gsim_qualification.read_text())
        validate_qualification(qualification, source, binary, cxx, revision, changed,
                               hashlib.sha256(diff.encode()).hexdigest(), lock)
        cp, compiled = classpath_manifest(args.java_classpath_file.resolve(),
                                          "platform.CommonMachineFabricScalarGsimMain")
        paths = [ROOT / "build.mill", ROOT / "AGENTS.md", Path(__file__),
                 HERE / "bringup.py", HERE / "config/toolchain.json", HERE / "common/fabric_scalar.cpp"]
        paths += list((ROOT / "src/main/scala").rglob("*.scala"))
        paths += list((ROOT / "src/test/scala/platform").glob("*.scala"))
        inputs = {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}
        receipt.update(inputs=inputs, compiled=compiled, tools={
            "gsim_revision": revision, "gsim_sha256": sha(binary), "cxx_sha256": sha(cxx),
            "java_sha256": sha(java), "qualification_sha256": sha(args.gsim_qualification)})
        save()
        model = out / "model"
        guard.run("emit", [java, "-Xmx2g", "-XX:ActiveProcessorCount=2", "-cp", cp,
                           "platform.CommonMachineFabricScalarGsimMain", model], timeout=180)
        fir = model / "CommonFabricScalarArbiter.fir"
        require(fir.is_file(), "missing emitted shared scalar arbiter")
        guard.run("generate", [binary, "--threads=1", "--dir=" + str(model), fir], timeout=180)
        units = sorted(model.glob("CommonFabricScalarArbiter[0-9]*.cpp"))
        require(bool(units), "missing generated GSIM units")
        run = model / "run"
        guard.run("compile", [cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all", "-I" + str(model), *units,
                              HERE / "common/fabric_scalar.cpp", "-o", run], timeout=300)
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
        positive = guard.run("positive", [run], env=env)
        require("COMMON_FABRIC_SCALAR_PASS " in positive, "shared scalar oracle completion missing")
        counts = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", positive)}
        require(counts.get("native", 0) == 218 and counts.get("native_responses") == 218 and
                counts.get("scalar_responses") == 218 and counts.get("writes", 0) > 0 and
                counts.get("writes") == counts.get("write_responses") and
                counts.get("clear") == 2 and counts.get("clear_responses") == 2 and
                counts.get("max_outstanding") == 16 and counts.get("request_ii1", 0) >= 16 and
                counts.get("response_ii1", 0) >= 16 and counts.get("fairness", 0) >= 64 and
                all(counts.get(key, 0) > 0 for key in ("held_req", "held_rsp", "errors", "faults",
                                                      "lookup", "no_lookup")),
                "shared scalar oracle coverage/count mismatch")
        negative = guard.run("negative", [run, "--inject-mismatch"], env=env, expected=1)
        require("SCALAR lane/owner/payload oracle mismatch" in negative and "PASS" not in negative,
                "negative scalar owner oracle did not reject corruption")
        require(not any(s in positive + negative for s in ("AddressSanitizer", "runtime error:",
                                                         "UndefinedBehaviorSanitizer")), "sanitizer failure")
        verify_classpath_unchanged(compiled)
        require(all(sha(ROOT / p) == expected for p, expected in inputs.items()), "source drift during test")
        receipt.update(status="PASS_SHARED_FABRIC_SCALAR", counts=counts,
                       positive=positive.strip(), negative=negative.strip(),
                       artifacts={str(p.relative_to(out)): sha(p) for p in (fir, run)})
    except BaseException as error:
        receipt.update(status="FAIL", error=str(error))
        save()
        raise
    save()
    print(json.dumps({"status": receipt["status"], "receipt": str(out / "receipt.json")}))


if __name__ == "__main__":
    main()
