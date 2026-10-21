#!/usr/bin/env python3
"""Bounded shared machine-fabric regression; explicit existing tools and compiled classes only."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run as common
from bringup import (Guard, ROOT, HERE, sha, require, executable, classpath_manifest,
                     verify_classpath_unchanged, validate_qualification)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--gsim-source", type=Path)
    parser.add_argument("--gsim-bin")
    parser.add_argument("--gsim-qualification", type=Path)
    parser.add_argument("--cxx")
    parser.add_argument("--java")
    parser.add_argument("--java-classpath-file", type=Path)
    parser.add_argument("--runtime-maintenance", action="store_true")
    parser.add_argument("--cloud-tools", action="store_true",
                        help="use clean pinned repository GSIM and coordinated Mill emitter")
    args = parser.parse_args()
    out = args.out.resolve()
    require(not out.exists(), "fresh output directory required")
    out.mkdir(parents=True)
    guard = Guard(out)
    receipt = {"status": "RUNNING", "scope": "real shared ROM/MMIO/atomic/DMA/Home/DDR fabric only; no CPU/CDC/board claim"}

    def save():
        receipt["steps"] = guard.records
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    try:
        main_class = "platform.CommonMachineFabricRuntimeGsimMain" if args.runtime_maintenance else "platform.CommonMachineFabricGsimMain"
        top = "CommonMachineFabricFlatGsim" if args.cloud_tools else "CommonMachineFabric"
        if args.cloud_tools:
            main_class = "platform.CommonMachineFabricFlatGsimMain"
            binary, cxx = common.setup(False)
            source = common.SOURCE
            compiled = None
            tool_record = {"mode": "clean-pinned-repository-tools", "gsim_sha256": sha(binary),
                           "gsim_revision": common.LOCK["revision"], "cxx": str(cxx)}
        else:
            require(all((args.gsim_source, args.gsim_bin, args.gsim_qualification,
                         args.cxx, args.java, args.java_classpath_file)),
                    "explicit tools, qualification, and compiled classpath required without --cloud-tools")
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
            cp, compiled = classpath_manifest(args.java_classpath_file.resolve(), main_class)
            tool_record = {"gsim_revision": revision, "gsim_sha256": sha(binary), "cxx_sha256": sha(cxx),
                           "java_sha256": sha(java), "qualification_sha256": sha(args.gsim_qualification)}
        paths = [ROOT / "build.mill", ROOT / "AGENTS.md", Path(__file__),
                 HERE / "common/fabric_machine.cpp"]
        paths += list((ROOT / "src/main/scala").rglob("*.scala"))
        paths += list((ROOT / "src/test/scala/platform").glob("*.scala"))
        inputs = {str(p.relative_to(ROOT)): sha(p) for p in sorted(set(paths))}
        receipt.update(inputs=inputs, compiled=compiled, tools=tool_record)
        save()
        model = out / "model"
        if args.cloud_tools:
            guard.run("emit", ["mill", "-i", "IonSoC.test.runMain", main_class, model,
                               str(args.runtime_maintenance).lower()], timeout=180)
        else:
            guard.run("emit", [java, "-Xmx2g", "-XX:ActiveProcessorCount=2", "-cp", cp,
                               main_class, model], timeout=180)
        fir = model / (top + ".fir")
        require(fir.is_file(), "missing emitted shared fabric")
        guard.run("generate", [binary, "--threads=1", "--dir=" + str(model), fir], timeout=180)
        units = sorted(model.glob(top + "[0-9]*.cpp"))
        require(bool(units), "missing generated GSIM units")
        # GSIM retains top-level Vec fields as C++ fixed-array accessors.
        # This test-only facade gives the driver explicit lane names; it does
        # not alter DUT logic or derive any oracle expectation from the DUT.
        header = (model / (top + ".h")).read_text()
        facade = ['#include "' + top + '.h"', 'struct FabricDut : S' + top + ' {']
        if args.cloud_tools:
            for name, typ in re.findall(r"void (set_io\$\$[A-Za-z0-9_$]+)\((\w+) val\);", header):
                alias = name.replace("__", "$$")
                if alias == name:
                    continue
                facade.append(f"    void {alias}({typ} value) {{ {name}(value); }}")
            for typ, name in re.findall(r"(\w+) (get_io\$\$[A-Za-z0-9_$]+)\(\)(?: const)?;", header):
                alias = name.replace("__", "$$")
                if alias == name:
                    continue
                facade.append(f"    {typ} {alias}() {{ return {name}(); }}")
        arrays = []
        for name, typ, count in re.findall(
                r"void (set_io\$\$tile\$\$(?:scalar|coherent|lineGrant)\$\$[A-Za-z0-9_$]+)\(const (\w+) \(&val\)\[(\d+)\]\);", header):
            base, tail = name.split("$$", 3)[2:]
            storage = "values_" + name.replace("$", "_")
            arrays.append(f"    {typ} {storage}[{count}]{{}};")
            for lane in range(int(count)):
                alias = name.replace("$$" + base + "$$", "$$" + base + "_" + str(lane) + "$$")
                facade.append(f"    void {alias}({typ} value) {{ {storage}[{lane}] = value; {name}({storage}); }}")
        for typ, name, count in re.findall(
                r"const (\w+) \(&(get_io\$\$tile\$\$(?:scalar|coherent|lineGrant)\$\$[A-Za-z0-9_$]+)\(\) const\)\[(\d+)\];", header):
            base = name.split("$$", 3)[2]
            for lane in range(int(count)):
                alias = name.replace("$$" + base + "$$", "$$" + base + "_" + str(lane) + "$$")
                facade.append(f"    {typ} {alias}() {{ return {name}()[{lane}]; }}")
        require(args.cloud_tools or len(arrays) >= 20, "missing retained top-level Vec bindings")
        facade += arrays + ['};']
        (model / "fabric_machine_vec_api.h").write_text("\n".join(facade) + "\n")
        run = model / "run"
        guard.run("compile", [cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                              "-fno-sanitize-recover=all", *(["-DRUNTIME_MAINTENANCE"] if args.runtime_maintenance else []), "-I" + str(model), *units,
                              HERE / "common/fabric_machine.cpp", "-o", run], timeout=600)
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
        positive = guard.run("positive", [run], env=env)
        require("COMMON_MACHINE_FABRIC_PASS " in positive and "epochs=2 dma_words=16 post_status_clear=1" in positive,
                "shared machine fabric oracle completion missing")
        if args.runtime_maintenance:
            require("RUNTIME_EPOCH_HOLD_PASS" in positive, "runtime epoch hold oracle missing")
            # Normalize assertion abort/exit status, but require the exact DUT
            # diagnostic. A driver timeout or fallback throw is not evidence.
            assertion_probe = (
                "import subprocess,sys; p=subprocess.run(sys.argv[1:],capture_output=True,text=True); "
                "s=p.stdout+p.stderr; print(s,end=''); "
                "sys.exit(0 if p.returncode != 0 and "
                "'runtime resume is early, duplicate, or has a stale epoch' in s "
                "and 'assertion did not fire' not in s else 1)"
            )
            for mode in ("--early-resume", "--wrong-resume", "--duplicate-resume"):
                guard.run("reject" + mode, [sys.executable, "-c", assertion_probe, run, mode], env=env)
        negative = guard.run("negative", [run, "--inject-mismatch"], env=env, expected=1)
        require("FABRIC memory/MMIO independent oracle mismatch" in negative and "PASS" not in negative,
                "negative fabric data oracle did not reject corruption")
        require(not any(s in positive + negative for s in ("AddressSanitizer", "runtime error:",
                                                         "UndefinedBehaviorSanitizer")), "sanitizer failure")
        if compiled is not None:
            verify_classpath_unchanged(compiled)
        require(all(sha(ROOT / p) == expected for p, expected in inputs.items()), "source drift during test")
        receipt.update(status="PASS_SHARED_MACHINE_FABRIC", positive=positive.strip(), negative=negative.strip(),
                       artifacts={str(p.relative_to(out)): sha(p) for p in (fir, run)})
    except BaseException as error:
        receipt.update(status="FAIL", error=str(error))
        save()
        raise
    save()
    print(json.dumps({"status": receipt["status"], "receipt": str(out / "receipt.json")}))


if __name__ == "__main__":
    main()
