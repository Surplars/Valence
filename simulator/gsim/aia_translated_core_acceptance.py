#!/usr/bin/env python3
"""Build the real translated OoO core plus APLIC/IMSIC from qualified classes.

Only the new wrapper is compiled here. The clean core's completed 369-source
compile and test, unchanged source manifest, classes, and dependencies are
verified and frozen. No local production sources or synthetic translation paths
are used. --generate-only prepares the model without a harness or native link;
--resume revalidates those exact artifacts before linking the eventual harness.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = "simulator/gsim/fixtures/AiaTranslatedCoreGsim.scala"
HARNESS = "simulator/gsim/harness/aia_translated_core.cpp"
SELF = "simulator/gsim/aia_translated_core_acceptance.py"
TOP = "AiaTranslatedCoreGsim"
EXPECTED_SOURCES = {
    "core/ooo/integration/HypervisorMachineCore.scala": "fde5dc68b99a0762d0d4410617e4834423ace44dfb60b784f162c5dee259efa6",
    "core/ooo/system/MachineSystemUnit.scala": "816f1bc0639d8dc6c58778df3641b9957af9208151d7d9bd60bdffaa39e9e303",
    "ip/interrupt/Aplic.scala": "8c25ef5fa744a02cb575b9e88b0d25d6799b62fbe74aa41b3ca1987f7b73cfbd",
    "ip/interrupt/Imsic.scala": "1499071bb0fc1a48dc8d4a3cb1aa4a2a46169a8f7ed6bca166f0d16f683c2d26",
    "platform/CommonInterruptFabric.scala": "b1bfe470ed65fb32508bd74992a2e9ec62b3c2f5c875ec6fd28165cedf6a0b5a",
    "core/ooo/system/AiaHartControl.scala": "6bf31f1bd22522ec9ee51f205d5481cb2aeb9f67f7e3d2636e682940b977d50e",
    "core/ooo/system/HypervisorGuestInterrupts.scala": "37031aeaa3eb1b18d8ee55dfa026ae6c521e8df834716164604025bc1a6a3213",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(path):
    path = Path(path)
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob("*")) if p.is_file()}


def pin(path):
    path = Path(path)
    assert path.exists(), path
    return sha(path) if path.is_file() else tree(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--core-root", type=Path, required=True)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--cxx", type=Path, required=True)
    parser.add_argument("--generate-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--link-permit-file", type=Path, help="resource-coordination gate before native linking")
    parser.add_argument("--pass-marker", default="AIA_GSTAGE_ALL_CHAINS_PASS")
    parser.add_argument("--negative-argument", default="--wrong-destination")
    parser.add_argument("--negative-marker", default="independent MSI guest destination")
    args = parser.parse_args()
    assert not (args.generate_only and args.resume), "choose initial generation or resume"
    out = args.output.resolve()
    core = args.core_root.resolve()
    build = core / "system-build"
    frozen = out / "prepared-core-classes"
    tools = {str(p.resolve()): sha(p) for p in [args.gsim, args.cxx]}
    if args.resume:
        record = json.loads((out / "receipt.json").read_text())
        assert record["status"] == "GENERATED_NOT_RUN", "resume requires a completed generate-only build"
        assert record["core_root"] == str(core) and record["tools"] == tools, "resume input drift"
    else:
        out.mkdir(parents=True, exist_ok=False)
        record = {
            "status": "RUNNING", "commands": [], "core_root": str(core),
            "scope": "Same DUT: scalar C fetch, nested IF/data translation, real APLIC/IMSIC, actual OoO retirement",
            "acceptance_passed": False, "guest_os_boot_qualified": False, "physical_timing_qualified": False,
            "inputs": {p: sha(ROOT / p) for p in [FIXTURE, SELF]}, "tools": tools,
        }

    def save():
        (out / "receipt.json").write_text(json.dumps(record, indent=2) + "\n")

    def run(argv, name, negative=False):
        argv = list(map(str, argv))
        start = time.monotonic()
        with (out / name).open("w") as log:
            result = subprocess.run(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=600,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"})
        record["commands"].append({"argv": argv, "exit": result.returncode,
                                   "seconds": time.monotonic() - start, "log": name})
        save()
        text = (out / name).read_text()
        if negative:
            assert result.returncode == 1 and args.negative_marker in text, text[-10000:]
        else:
            assert result.returncode == 0, text[-10000:]
        return text

    def validate_inputs():
        assert record["inputs"] == {p: sha(ROOT / p) for p in record["inputs"]}, "fixture input drift"
        assert record["tools"] == {p: sha(p) for p in record["tools"]}, "native tool drift"
        for path, digest in record["core_source_pins"].items():
            assert sha(path) == digest, "qualified source changed: " + path
        assert tree(build / "classes") == record["prepared_core_class_pins"], "prepared class drift"
        assert tree(frozen) == record["prepared_core_class_pins"], "frozen class drift"
        for path, digest in record["external_classpath_pins"].items():
            assert pin(path) == digest, "dependency drift: " + path
        for path, digest in record["scala_tool_pins"].items():
            assert sha(path) == digest, "Scala tool drift: " + path
        assert sha(record["scala_plugin"]) == record["scala_plugin_sha256"], "Scala plugin drift"
        for name, digest in record["core_build_manifest_pins"].items():
            assert sha(build / name) == digest, "qualified build manifest drift: " + name

    try:
        if args.resume:
            validate_inputs()
            for path, digest in record["artifacts"].items():
                assert sha(out / path) == digest, "generated artifact drift: " + path
            record["status"] = "RUNNING"
        else:
            completed = json.loads((build / "commands.json").read_text())
            assert completed[-1]["name"] == "test" and all(x["exit"] == 0 for x in completed), "unqualified core"
            source_pins = json.loads((build / "sources.json").read_text())
            assert len(source_pins) == 369, "unexpected prepared source count"
            assert source_pins == json.loads((build / "sources-before.json").read_text()), "compilation source drift"
            assert all(sha(path) == digest for path, digest in source_pins.items()), "current source drift"
            compile_argv = completed[0]["argv"]
            assert set(x for x in compile_argv if x.endswith(".scala")) == set(source_pins), "compile source mismatch"
            for name, digest in EXPECTED_SOURCES.items():
                assert source_pins[str(core / "src/main/scala" / name)] == digest, name
            record["core_source_pins"] = source_pins
            record["prepared_core_commands"] = completed
            record["core_build_manifest_pins"] = {
                name: sha(build / name) for name in ["commands.json", "sources.json", "sources-before.json"]
            }
            class_pins = tree(build / "classes")
            shutil.copytree(build / "classes", frozen)
            assert tree(frozen) == class_pins and tree(build / "classes") == class_pins, "class copy drift"
            record["prepared_core_class_pins"] = class_pins
            prefix = compile_argv[:compile_argv.index("-d")]
            classpath = prefix[prefix.index("-classpath") + 1]
            record["external_classpath_pins"] = {name: pin(name) for name in classpath.split(":")}
            record["scala_tool_pins"] = {name: sha(name) for name in prefix[prefix.index("-cp") + 1].split(":")}
            plugin = next(x[len("-Xplugin:"):] for x in prefix if x.startswith("-Xplugin:"))
            record["scala_plugin"] = plugin
            record["scala_plugin_sha256"] = sha(plugin)
            classes = out / "wrapper-classes"
            classes.mkdir()
            prefix[prefix.index("-classpath") + 1] = str(frozen) + ":" + classpath
            save()
            run([*prefix, "-d", classes, ROOT / FIXTURE], "wrapper-compile.log")
            runtime = str(classes) + ":" + str(frozen) + ":" + classpath
            run([compile_argv[0], "-Xmx2g", "-XX:ActiveProcessorCount=2", "-cp", runtime,
                 "ooo." + TOP + "Main", out], "emit.log")
            fir = out / (TOP + ".fir")
            # GSIM's parser requires a sentinel beyond a page-aligned input.
            if fir.stat().st_size % 4096 == 0:
                fir.write_bytes(fir.read_bytes() + b"\n")
            run([args.gsim, "--threads=1", "--dir=" + str(out), fir], "generate.log")
            validate_inputs()
            if args.generate_only:
                record["status"] = "GENERATED_NOT_RUN"
                print("Generated " + str(out / (TOP + ".h")) + "; native acceptance not run.", flush=True)
                return

        if args.link_permit_file:
            record["status"] = "WAITING_LINK_PERMIT"
            save()
            while not args.link_permit_file.exists():
                time.sleep(1)
            record["status"] = "RUNNING"
        record["inputs"][HARNESS] = sha(ROOT / HARNESS)
        record["acceptance_markers"] = {"positive": args.pass_marker, "negative_argument": args.negative_argument,
                                        "negative": args.negative_marker}
        validate_inputs()
        save()
        run([args.cxx, "-std=c++20", "-O1", "-fbracket-depth=4096", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=all", "-I" + str(out), *sorted(out.glob(TOP + "[0-9]*.cpp")),
             ROOT / HARNESS, "-ldl", "-o", out / "run"], "link.log")
        result = run([out / "run"], "run.log")
        assert args.pass_marker in result, result[-10000:]
        print(result, flush=True)
        run([out / "run", args.negative_argument], "negative.log", negative=True)
        validate_inputs()
        record["status"] = "PASS_FINITE_AIA_TRANSLATED_CHAIN"
        record["acceptance_passed"] = True
    except BaseException as error:
        record["status"] = "FAIL"
        record["error"] = repr(error)
        raise
    finally:
        record["artifacts"] = {
            str(path.relative_to(out)): sha(path) for path in sorted(out.rglob("*"))
            if path.is_file() and path.name != "receipt.json"
        }
        save()


if __name__ == "__main__":
    main()
