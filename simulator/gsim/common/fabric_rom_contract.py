#!/usr/bin/env python3
"""Bounded default-vs-complete ROM contract check using existing qualified tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
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
    receipt = {"status": "RUNNING", "scope": "ROM physical bank fill and original TL extent; no PMP authorization claim"}

    def save():
        receipt["steps"] = guard.records
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    try:
        source = args.gsim_source.resolve()
        binary = executable(args.gsim_bin, "gsim-bin")
        cxx = executable(args.cxx, "cxx")
        java = executable(args.java, "java")
        revision = guard.run("gsim-revision", ["git", "rev-parse", "HEAD"], cwd=source).strip()
        changed = guard.run("gsim-changed", ["git", "diff", "HEAD", "--name-only"], cwd=source).splitlines()
        diff = guard.run("gsim-patch", ["git", "diff", "HEAD", "--binary"], cwd=source)
        validate_qualification(json.loads(args.gsim_qualification.read_text()), source, binary, cxx,
                               revision, changed, hashlib.sha256(diff.encode()).hexdigest(),
                               json.loads((HERE / "config/toolchain.json").read_text()))
        main_class = "platform.CommonInstructionRomContractGsimMain"
        cp, compiled = classpath_manifest(args.java_classpath_file.resolve(), main_class)
        paths = [ROOT / "build.mill", ROOT / "AGENTS.md", Path(__file__), HERE / "common/fabric_rom_contract.cpp"]
        paths += list((ROOT / "src/main/scala").rglob("*.scala"))
        paths += list((ROOT / "src/test/scala/platform").glob("*.scala"))
        inputs = {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}
        receipt.update(inputs=inputs, compiled=compiled, tools={"gsim_revision": revision,
            "gsim_sha256": sha(binary), "cxx_sha256": sha(cxx), "java_sha256": sha(java),
            "qualification_sha256": sha(args.gsim_qualification)})
        save()
        model = out / "model"
        guard.run("emit", [java, "-Xmx1g", "-XX:ActiveProcessorCount=2", "-cp", cp, main_class, model], timeout=120)
        fir = model / "CommonInstructionRomContractGsim.fir"
        require(fir.is_file(), "missing emitted ROM contract fixture")
        guard.run("generate", [binary, "--threads=1", "--dir=" + str(model), fir], timeout=120)
        units = sorted(model.glob("CommonInstructionRomContractGsim[0-9]*.cpp"))
        require(bool(units), "missing generated GSIM units")
        run = model / "run"
        guard.run("compile", [cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all", "-I" + str(model), *units,
                              HERE / "common/fabric_rom_contract.cpp", "-o", run], timeout=120)
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
        positive = guard.run("positive", [run], env=env)
        require("ROM_CONTRACT_PASS replies=22 denied=6 held_checks=88" in positive,
                "ROM default/full extent oracle completion missing")
        negatives = {}
        for label in ("misaligned", "bad-mask"):
            negative = guard.run(label, [run, "--" + label], env=env, expected=-signal.SIGABRT)
            require("instruction ROM manager accepts aligned 1/2/4/8-byte Get only" in negative and
                    "PASS" not in negative, "original ROM assertion did not reject " + label)
            negatives[label] = negative.strip()
        require(not any(s in positive + str(negatives) for s in
                        ("AddressSanitizer", "runtime error:", "UndefinedBehaviorSanitizer")), "sanitizer failure")
        verify_classpath_unchanged(compiled)
        require(all(sha(ROOT / p) == expected for p, expected in inputs.items()), "source drift during test")
        receipt.update(status="PASS_ROM_BEAT_CONTRACT", positive=positive.strip(), negatives=negatives,
                       artifacts={str(p.relative_to(out)): sha(p) for p in (fir, run)})
    except BaseException as error:
        receipt.update(status="FAIL", error=str(error))
        save()
        raise
    save()
    print(json.dumps({"status": receipt["status"], "receipt": str(out / "receipt.json")}))


if __name__ == "__main__":
    main()
