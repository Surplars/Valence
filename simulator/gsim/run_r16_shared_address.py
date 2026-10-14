#!/usr/bin/env python3
"""Exact R16 bounded shared-address gate. No production compile, CPU or physical run."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

HERE = Path(__file__).resolve().parent
PUBLIC_ROOT = HERE.parents[1]
SUPPORT = HERE / "r16_shared_address"
CATALOG = SUPPORT / "qualified_inputs.json"
TOP = "R16SharedAddressGsim"
SOURCE_BASELINE = {"commit": "2fa6a4b320814ad2b142d5bf0009c1d2d5475233",
                   "tree": "35d748735d08200d4eea9e397d401b56d463addb",
                   "selection": "Explicit historical source closure; newer default-OFF alternatives are not silently accepted"}
NATIVE = "src/test/scala/ooo/R16SharedAddressNative.scala"
FIXTURE = "src/test/scala/core/ooo/R16SharedAddressGsim.scala"
BAD_RUNTIME = ("AddressSanitizer", "UndefinedBehaviorSanitizer", "LeakSanitizer", "runtime error:",
               "Assertion failed:", "Assertion `", "assertion failed", "Segmentation fault")
FLAGS = ["-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]


def need(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def local(root, name):
    need(isinstance(name, str) and name and not Path(name).is_absolute() and ".." not in Path(name).parts,
         "unsafe relative manifest path: " + str(name))
    path = root / name
    need(path.resolve().is_relative_to(root.resolve()), "manifest path escapes root: " + name)
    return path


def inventory(root):
    need(root.is_dir(), "missing directory: " + str(root))
    result = {}
    for path in sorted(root.rglob("*")):
        need(not path.is_symlink(), "symlink in inventoried input: " + str(path))
        if path.is_file():
            result[str(path.relative_to(root))] = sha(path)
    return result


def check_hashes(root, entries):
    for name, digest in entries.items():
        path = local(root, name)
        need(path.is_file() and sha(path) == digest, "missing or changed input: " + str(path))


def catalog():
    value = read(CATALOG)
    need(value.get("schema") == "exact-r16-shared-address-inputs-v1", "unsupported frozen input catalog")
    return value


def validate_repo(root, data):
    # Extra source files are allowed, but every original compiled input must still match.
    check_hashes(root, data["sources"])
    check_hashes(PUBLIC_ROOT, data["publicInputs"])


def classes(path):
    if path.is_dir():
        return {str(p.relative_to(path)) for p in path.rglob("*.class")}
    with zipfile.ZipFile(path) as archive:
        return {name for name in archive.namelist() if name.endswith(".class")}


def validate_classpath(root, data):
    result, application = [], set()
    for entry in data["classpath"]:
        path = local(root, entry["path"])
        if "files" in entry:
            need(inventory(path) == entry["files"], "classpath inventory mismatch: " + str(path))
        else:
            need(path.is_file() and sha(path) == entry["sha256"], "classpath JAR mismatch: " + str(path))
        found = classes(path) if entry["role"] != "resource" else set()
        if entry["role"] == "resource":
            need(not list(path.rglob("*.class")), "resource entry contains application classes")
        current = {name for name in found if name.startswith(("soc/", "ooo/"))}
        if entry["role"] == "dependency":
            need(not current, "dependency has application fallback classes")
        need(not current & application, "duplicate application class fallback")
        application |= current
        result.append(path)
    need("soc/core/ooo/IntegerBackend.class" in application and
         "ooo/TimingReady73Profile$.class" in application, "missing exact application classes")
    return result


def validate_inputs(args, data):
    validate_repo(args.repo_root, data)
    need(args.frozen_root is not None, "--frozen-root is required; no implicit Mill/classpath fallback")
    original = local(args.frozen_root, data["compileReceipt"])
    need(original.is_file() and sha(original) == data["compilerReceiptSha256"], "original compiler receipt changed")
    receipt = read(original)
    need(receipt.get("status") == "PASS_NEW_INDEPENDENT_CLASSES" and receipt["sources"] == data["sources"],
         "source/compile receipt binding mismatch")
    for entry in data["classpath"]:
        if entry["role"] in ("main", "test"):
            prefix = "classes-" + entry["role"] + "/"
            expected = {key[len(prefix):]: value for key, value in receipt["classes"].items() if key.startswith(prefix)}
            need(entry["files"] == expected, "original compiled class inventory binding mismatch")
    return validate_classpath(args.frozen_root, data)


def validate_frozen(args, data, negative=False):
    validate_inputs(args, data)
    check_hashes(args.frozen_root, data["originalEvidence"])
    check_hashes(args.frozen_root, data["frozenInputs"])
    for entry in data["frozenInventories"]:
        need(inventory(local(args.frozen_root, entry["path"])) == entry["files"],
             "frozen model/class inventory mismatch: " + entry["path"])
    if negative:
        original = local(args.repo_root, data["mutation"]["source"])
        mutant = local(args.frozen_root, data["mutation"]["mutantPath"])
        before, after = data["mutation"]["before"], data["mutation"]["after"]
        content = original.read_bytes()
        need(content.count(before.encode()) == 1 and content.replace(before.encode(), after.encode()) == mutant.read_bytes(),
             "negative is not the exact single real source mutation")


def fresh_compiler():
    spec = importlib.util.spec_from_file_location("r16_fresh_compiler", HERE / "compile_r16_shared_address.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def selected_inputs(args, data):
    if getattr(args, "classes_dir", None) is not None:
        need(args.frozen_root is None, "select fresh --classes-dir or historical --frozen-root, never both")
        return fresh_compiler().verify(args.classes_dir, args.repo_root, data)
    return validate_inputs(args, data)


def fresh_tool(args, name):
    path, digest = getattr(args, name), getattr(args, name + "_sha256", None)
    need(path is not None and digest is not None and re.fullmatch(r"[0-9a-f]{64}", digest),
         "fresh build requires --" + name + " and --" + name + "-sha256")
    path = path.resolve()
    need(path.is_file() and os.access(path, os.X_OK) and sha(path) == digest, "fresh tool hash mismatch: " + name)
    return path


def fresh_gsim_setup(args):
    need(args.gsim_setup_receipt is not None, "fresh build requires --gsim-setup-receipt from make gsim-setup")
    lock = read(args.repo_root / "simulator/gsim/config/toolchain.json")
    need(lock.get("repository") == "https://github.com/OpenXiangShan/gsim.git" and
         lock.get("revision") == "93b8cd23edd3228807c4f2a08c19c3936a463cb2" and
         lock.get("minimum_clang_major") == 19, "repository GSIM toolchain lock changed")
    receipt = read(args.gsim_setup_receipt)
    need(all(receipt.get(key) == value for key, value in lock.items()), "GSIM setup receipt does not match repository lock")
    return {"lock": lock, "setupReceiptSha256": sha(args.gsim_setup_receipt)}


def tool(args, data, name):
    path = getattr(args, name)
    need(path is not None, "build requires explicit --" + name)
    path = path.resolve()
    need(path.is_file() and os.access(path, os.X_OK) and sha(path) == data["tools"][name]["sha256"],
         "pinned tool hash mismatch: " + name)
    if name == "java":
        check_hashes(path.parent.parent, data["tools"][name]["runtimeFiles"])
    return path


def launch(command, cwd, log, timeout):
    # Caller must provide the installed matching toolchain/runtime. Never install a fallback.
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    for variable in ("CLASSPATH", "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS"):
        env.pop(variable, None)
    start = time.monotonic()
    with log.open("x") as stream:
        process = subprocess.run(list(map(str, command)), cwd=cwd, env=env,
                                 stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    text = log.read_text(errors="replace")
    record = {"argv": list(map(str, command)), "exit": process.returncode,
              "seconds": round(time.monotonic() - start, 4), "logSha256": sha(log)}
    return process.returncode, text, record


def check_runtime(code, text, expected, negative=False):
    need(not any(marker in text for marker in BAD_RUNTIME), "runtime/assertion failure is not an independent oracle result")
    if negative:
        need(code == 1 and text.strip() == "FAIL independent row payload mismatch",
             "source negative did not reach the exact independent payload oracle")
        return None
    need(code == 0 and "FAIL " not in text, "positive host did not succeed")
    lines = [line for line in text.splitlines() if line.startswith("RESULT ")]
    need(len(lines) == 1, "one complete RESULT is required")
    counts = {key: int(value) for key, value in re.findall(r"(\w+)=(\d+)", lines[0])}
    need(counts == expected, "fixed-seed bounded witness counts changed")
    need(counts["accepted"] == counts["retired"] + counts["cancelled"] and
         counts["requests"] == counts["responses"], "conservation failed")
    return counts


def check_trace(path, data, exact=True):
    # One compact observation line and one width-complete public snapshot per cycle.
    lines = path.read_text().splitlines()
    cycles = data["expectedCounts"]["cycles"]
    need(len(lines) == 2 * cycles, "missing/truncated trace")
    for index in range(cycles):
        need(lines[2 * index].split()[0] == str(index), "nonconsecutive trace cycle")
        need(len(lines[2 * index + 1].split()) == data["snapshotWords"], "public snapshot has wrong serialized width")
    if exact:
        need(sha(path) == data["expectedTraceSha256"], "trace differs from the qualified fixed-seed gate")


def validate_abi(headers, data):
    for side, header in headers.items():
        content = header.read_text()
        signatures = re.findall(r"^((?:void set_[\w$]+|[^;{}\n]+ get_[\w$]+)\([^;\n]*\);)$", content, re.M)
        need(signatures == data["scalarAbi"][side], "scalar-port ABI changed: " + side)


def build(args, data):
    classpath = selected_inputs(args, data)
    fresh = getattr(args, "classes_dir", None) is not None
    java, gsim, cxx = ((fresh_tool(args, name) if fresh else tool(args, data, name))
                       for name in ("java", "gsim", "cxx"))
    setup = fresh_gsim_setup(args) if fresh else None
    need(args.out is not None and not args.out.exists(), "build requires a fresh --out")
    args.out.mkdir(parents=True)
    receipt = {"schema": "exact-r16-shared-address-build-v1", "status": "FAIL",
               "catalogSha256": sha(CATALOG), "runnerSha256": sha(Path(__file__)), "commands": [],
               "productionRecompiled": fresh, "fullCpu": False, "physicalRun": False,
               "inputMode": "FRESH_SOURCE_CLASSES" if fresh else "HISTORICAL_FROZEN_CLASSES",
               "sourceBaseline": SOURCE_BASELINE, "productionSourceInputs": data["sources"],
               "tools": {name: {"path": str(path), "sha256": sha(path)} for name, path in
                         (("java", java), ("gsim", gsim), ("cxx", cxx))}, "gsimSetup": setup}
    if fresh:
        receipt["freshClassesDirectory"] = str(args.classes_dir)
        receipt["freshClassesReceiptSha256"] = sha(args.classes_dir / "classes.json")
    try:
        jars = [p for p in classpath if p.suffix == ".jar"]
        plugin = next(p for p in jars if p.name == "chisel-plugin_2.13.17-7.3.0.jar")
        if not fresh:
            native_classes, gsim_classes = args.out / "classes-native", args.out / "classes-gsim"
            for destination, source, dependencies in ((native_classes, NATIVE, classpath),
                                                     (gsim_classes, FIXTURE, [native_classes, *classpath])):
                destination.mkdir()
                command = [java, "-Xmx2g", "-XX:ActiveProcessorCount=2", "-cp", os.pathsep.join(map(str, jars)),
                           "scala.tools.nsc.Main", "-language:reflectiveCalls", "-Xplugin:" + str(plugin),
                           "-classpath", os.pathsep.join(map(str, dependencies)), "-d", destination,
                           local(PUBLIC_ROOT, source)]
                code, _, row = launch(command, args.repo_root, args.out / (destination.name + ".log"), args.timeout)
                receipt["commands"].append(row)
                need(code == 0 and list(destination.rglob("*.class")), "bounded wrapper compile failed")
            cp = os.pathsep.join(map(str, [gsim_classes, native_classes, *classpath]))
        else:
            cp = os.pathsep.join(map(str, classpath))
        for side in ("off", "on"):
            target = args.out / side
            command = [java, "-Xmx4g", "-XX:ActiveProcessorCount=2", "-Dchisel.project.root=" + str(args.repo_root),
                       "-cp", cp, "soc.core.ooo.R16SharedAddressGsimMain", target, side]
            code, _, row = launch(command, args.repo_root, args.out / ("emit-" + side + ".log"), args.timeout)
            receipt["commands"].append(row)
            need(code == 0 and read(target / "actual-core.json") == data["actualCore"][side],
                 "emit failed or complete 177-field actual constructor changed")
            command = [gsim, "--threads=1", "--cpp-max-size-KB=1024", "--dir=" + str(target), target / (TOP + ".fir")]
            code, _, row = launch(command, args.repo_root, args.out / ("generate-" + side + ".log"), args.timeout)
            receipt["commands"].append(row)
            need(code == 0, "GSIM generation failed")
        validate_abi({s: args.out / s / (TOP + ".h") for s in ("off", "on")}, data)
        for side in ("off", "on"):
            target = args.out / side
            units = sorted(target.glob(TOP + "[0-9]*.cpp"))
            need(units, "missing GSIM translation units")
            objects = []
            for source in units:
                output = source.with_suffix(".o")
                command = [cxx, *FLAGS, "-I" + str(target), "-c", source, "-o", output]
                code, _, row = launch(command, args.repo_root, source.with_suffix(".log"), args.timeout)
                receipt["commands"].append(row)
                need(code == 0, "GSIM model compilation failed")
                objects.append(output)
            command = [cxx, *FLAGS, "-DSHARED=" + str(int(side == "on")), "-I" + str(target),
                       "-I" + str(SUPPORT), SUPPORT / "host.cpp", *objects, "-o", target / "run"]
            code, _, row = launch(command, args.repo_root, args.out / ("link-" + side + ".log"), args.timeout)
            receipt["commands"].append(row)
            need(code == 0 and (target / "run").is_file(), "host link failed")
        selected_inputs(args, data)
        receipt["status"] = "BUILT_NOT_RUN"
        receipt["artifacts"] = inventory(args.out)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
        raise
    finally:
        write(args.out / "build.json", receipt)
    return {"status": receipt["status"], "buildReceiptSha256": sha(args.out / "build.json")}


def validate_build(args, data):
    need(args.build_dir is not None, "run requires --build-dir")
    receipt = read(args.build_dir / "build.json")
    need(receipt.get("schema") == "exact-r16-shared-address-build-v1" and receipt.get("status") == "BUILT_NOT_RUN",
         "not a completed bounded build")
    selected_inputs(args, data)
    fresh = getattr(args, "classes_dir", None) is not None
    need(receipt.get("productionRecompiled") is fresh, "fresh/historical class mode mismatch")
    if fresh:
        need(receipt["freshClassesDirectory"] == str(args.classes_dir) and
             receipt["freshClassesReceiptSha256"] == sha(args.classes_dir / "classes.json"), "fresh class receipt changed")
    need(receipt["catalogSha256"] == sha(CATALOG) and receipt["runnerSha256"] == sha(Path(__file__)),
         "runner/catalog changed since build")
    actual = inventory(args.build_dir)
    actual.pop("build.json", None)
    need(actual == receipt["artifacts"], "model/class/binary closure changed since build")
    for side in ("off", "on"):
        need(read(args.build_dir / side / "actual-core.json") == data["actualCore"][side], "actual profile changed")
    validate_abi({s: args.build_dir / s / (TOP + ".h") for s in ("off", "on")}, data)


def run(args, data, frozen=False, negative=False):
    if frozen:
        validate_frozen(args, data, negative)
        binaries = {s: local(args.frozen_root, p) for s, p in
                    data["binaries"]["negative" if negative else "positive"].items()}
    else:
        validate_build(args, data)
        binaries = {s: args.build_dir / s / "run" for s in ("off", "on")}
    need(args.out is not None and not args.out.exists(), "run requires a fresh --out")
    args.out.mkdir(parents=True)
    receipt = {"schema": "exact-r16-shared-address-run-v1", "status": "FAIL", "fullCpu": False,
               "physicalRun": False, "catalogSha256": sha(CATALOG), "runnerSha256": sha(Path(__file__)),
               "publicOutputFields": 244, "serializedWordsPerCycle": data["snapshotWords"],
               "reusedQualifiedBinary": frozen, "sourceNegative": negative, "commands": [],
               "productionRecompiled": getattr(args, "classes_dir", None) is not None,
               "sourceBaseline": SOURCE_BASELINE,
               "qualificationMode": "FRESH_SOURCE_POSITIVE_PAIR" if getattr(args, "classes_dir", None) is not None
                                    else "HISTORICAL_EXACT_INPUTS",
               "sanitizers": "ASan/UBSan; LeakSanitizer disabled (ptrace environment limitation)"}
    try:
        for side, binary in binaries.items():
            trace, log = args.out / (side + ".trace"), args.out / (side + ".log")
            code, text, row = launch([binary, "1", trace], args.out, log, args.timeout)
            row.update(side=side, binarySha256=sha(binary))
            receipt["commands"].append(row)
            row["counts"] = check_runtime(code, text, data["expectedCounts"], negative)
            need(trace.is_file(), "missing trace")
            row["traceSha256"] = sha(trace)
            if not negative:
                check_trace(trace, data)
            else:
                need(sha(trace) == data["negativeTraceSha256"], "wrong negative failure point")
        if not negative:
            for extension in ("trace", "log"):
                need((args.out / ("off." + extension)).read_bytes() == (args.out / ("on." + extension)).read_bytes(),
                     "OFF/ON " + extension + " differs")
        if frozen:
            validate_frozen(args, data, negative)
        else:
            validate_build(args, data)
        receipt["status"] = ("PASS_REAL_SOURCE_WRONG_LANES_REJECTED_BY_INDEPENDENT_ROW_ORACLE" if negative
                             else "PASS_FRESH_EXACT_R16_FULL_WIDTH_COMPONENT_PAIR" if getattr(args, "classes_dir", None) is not None
                             else "PASS_EXACT_R16_SCOPED_GSIM_PAIR")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        receipt["error"] = str(error)
        raise
    finally:
        write(args.out / "receipt.json", receipt)
    return {"status": receipt["status"], "receiptSha256": sha(args.out / "receipt.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("verify", "verify-frozen", "verify-negative", "build", "run",
                                           "run-frozen", "run-negative-frozen"))
    parser.add_argument("--repo-root", type=Path, default=HERE.parents[1])
    parser.add_argument("--frozen-root", type=Path, help="directory preserving the catalog's relative frozen input paths")
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--classes-dir", type=Path, help="fresh classes from compile_r16_shared_address.py; no frozen inputs required")
    parser.add_argument("--gsim-setup-receipt", type=Path, help="fresh builds: build/gsim/toolchain-used.json from make gsim-setup")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=int, default=600, help="seconds per bounded subprocess")
    for name in ("java", "gsim", "cxx"):
        parser.add_argument("--" + name, type=Path, help="explicit executable")
        parser.add_argument("--" + name + "-sha256", help="fresh build executable pin; historical mode uses catalog pin")
    args = parser.parse_args()
    for key in ("repo_root", "frozen_root", "build_dir", "classes_dir", "gsim_setup_receipt", "out"):
        if getattr(args, key) is not None:
            setattr(args, key, getattr(args, key).resolve())
    try:
        need(args.timeout > 0, "timeout must be positive")
        need(not (args.classes_dir is not None and args.stage in
                  ("verify-frozen", "verify-negative", "run-frozen", "run-negative-frozen")),
             "fresh --classes-dir cannot be combined with a historical frozen stage")
        data = catalog()
        if args.stage == "verify":
            selected_inputs(args, data)
            result = {"status": "INPUTS_VERIFIED_NOT_BUILT_OR_RUN"}
        elif args.stage.startswith("verify-"):
            validate_frozen(args, data, args.stage == "verify-negative")
            result = {"status": "FROZEN_INPUTS_VERIFIED_NOT_RUN"}
        elif args.stage == "build":
            result = build(args, data)
        else:
            result = run(args, data, args.stage != "run", args.stage == "run-negative-frozen")
        print(json.dumps(result, sort_keys=True))
    except (OSError, ValueError, KeyError, IndexError, StopIteration, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        parser.exit(2, "R16 gate rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
