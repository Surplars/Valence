#!/usr/bin/env python3
"""Matched R5 ISA switch assessment: cached-CPU GSIM checks and frozen Vivado RTL."""
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

PROFILES = {"im": [], "ima": ["--a"], "imc": ["--c"], "imf": ["--f"],
            "imfd": ["--f", "--d"], "imafdc": ["--a", "--c", "--f", "--d"]}
BASE_FLAGS = ["64", "--pipeline=fpga8", "--timing-cuts", "--dsp-tiled", "--predictor=128",
              "--icache=32768", "--dcache=32768"]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", choices=PROFILES, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--rtl-output", type=Path, required=True)
    args = ap.parse_args()
    output, rtl = args.output.resolve(), args.rtl_output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        ap.error("fresh output under the WSL clone build/ required")
    if rtl.exists() or not rtl.is_relative_to(Path("/mnt/e/VM/Share/Valence-rtl/Valence-InOrder")):
        ap.error("fresh RTL output under the designated Windows root required")
    if os.environ.get("VALENCE_WORK_ROOT") != str(ROOT):
        ap.error("source .local-dev/env.sh")
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    subprocess.run(["mill", "-i", "OrbitalI1.test.runClasspath"], cwd=ROOT, check=True)
    paths = [Path(v.split(":", 3)[3]) for v in
             json.loads((ROOT / "out/OrbitalI1/test/runClasspath.json").read_text())["value"]]
    runtime = os.pathsep.join(str(p) for p in paths if p.exists())
    sources = sorted((ROOT / "src/main/scala/core/inorder").glob("*.scala"))
    sources += sorted((ROOT / "src/test/scala/inorder").glob("*.scala"))
    sources += [Path(__file__).resolve(), ROOT / "fpga/inorder/core300_ooc.tcl"]
    sources += [ROOT / "simulator/gsim/harness" / f for f in
                ["five_stage.cpp", "five_stage_coremark.cpp", "i1_prediction_metrics.h", "i1_extensions.cpp",
                 "i1_compressed_reference.h"]]
    frozen = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    flags = BASE_FLAGS + PROFILES[args.profile]
    defines = ["-DI1_COREMARK_PREDICTION=1"] + ["-DI1_WITH_" + flag[2:].upper() + "=1"
              for flag in PROFILES[args.profile]]
    if "--c" in PROFILES[args.profile]:
        defines += ["-DI1_COREMARK_COMPRESSED=1", "-DDUT_HAS_C=1"]
    receipt = {"status": "RUNNING", "profile": args.profile, "flags": flags,
               "baseline_commit": "fbcb215d0441917b691792badc83c56cb815cef5",
               "source_sha256": frozen,
               "compiled_class_sha256": {str(p.relative_to(ROOT)): sha(p)
                   for module in ["OrbitalI1", "OrbitalI1/test"]
                   for p in (ROOT / "out" / module / "compile.dest/classes").rglob("*.class")},
               "gsim_sha256": sha(gsim), "commands": [],
               "scope": "single-issue R5 cached CPU; no SoC/peripherals; short functional gates",
               "physical_qualified": False, "coremark": []}

    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

    def run(argv, log, negative=None):
        argv = [str(v) for v in argv]
        receipt["commands"].append({"argv": argv, "log": str(log)})
        save()
        with log.open("w") as stream:
            result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = log.read_text()
        if negative:
            if result.returncode == 0 or negative not in text:
                raise RuntimeError("independent mutation was not rejected: " + str(log))
        elif result.returncode:
            raise RuntimeError("command failed: " + str(log))
        return text

    try:
        top = "I1PerformanceCachedCore"
        run(["java", "-cp", runtime, "inorder.I1PerformanceCachedMain", output, *flags], output / "elaborate.log")
        run([gsim, "--threads=1", "--dir=" + str(output), output / (top + ".fir")], output / "generate.log")
        generated = sorted(output.glob(top + "[0-9]*.cpp"))
        objects = [p.with_suffix(".o") for p in generated]
        compile_flags = [cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                         "-fno-sanitize-recover=all", *defines, "-I" + str(output)]
        # Compile shared model objects once for both architectural and CoreMark drivers.
        for source, obj in zip(generated, objects):
            run([*compile_flags, "-c", source, "-o", obj], obj.with_suffix(".compile.log"))
        for name, driver in [("extensions", "i1_extensions.cpp"), ("coremark", "five_stage_coremark.cpp")]:
            run([*compile_flags, *objects, ROOT / "simulator/gsim/harness" / driver,
                 "-o", output / name], output / (name + "-compile.log"))
        receipt["functional"] = run([output / "extensions"], output / "functional.log").strip()
        run([output / "extensions", "--inject"], output / "functional-negative.log",
            "extension independent integer value oracle")
        print(args.profile, receipt["functional"], flush=True)
        payload = ROOT / "build/i1-numerical-20261103-r1/coremark-r2/payload/coremark.bin"
        if sha(payload) != "bc0bc1c5b5fdd7b4960b6e472d0a5d7aaf75eca748fdf7cd669904d1b2aba43b":
            raise RuntimeError("frozen CoreMark image drift")
        receipt["payload_sha256"] = sha(payload)
        for latency in [1, 12]:
            argv = [output / "coremark", payload, "0x8001081c", "0x80010800", "0x80010808", latency]
            text = run(argv, output / ("coremark-l" + str(latency) + ".log"))
            def row(prefix):
                return json.loads(next(l[len(prefix):] for l in text.splitlines() if l.startswith(prefix)))
            result = {**row("MATCHED_COREMARK_PASS "), **row("I1_COREMARK_PREDICTION "), "latency": latency}
            result["ipc"] = result["roi_instructions"] / result["roi_ticks"]
            result["branch_accuracy"] = result["roi_correct"] / result["roi_branches"]
            receipt["coremark"].append(result)
            print(args.profile, "CoreMark", latency, "cycles", result["roi_ticks"], "IPC", result["ipc"], flush=True)
            save()
        run([*argv, "--inject"], output / "coremark-negative.log", "CoreMark independent register oracle mismatch")
        rtl.mkdir(parents=True)
        run(["java", "-cp", runtime, "inorder.I1Core300Main", rtl, *flags], output / "rtl-elaborate.log")
        receipt["rtl_sha256"] = {p.name: sha(p) for p in sorted(rtl.glob("*.sv"))}
        receipt["rtl_root"] = str(rtl)
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift during assessment: " + name)
        receipt["status"] = "PASS_GSIM_READY_FOR_VIVADO"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error))
        raise
    finally:
        save()
    print(json.dumps({"profile": args.profile, "status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
