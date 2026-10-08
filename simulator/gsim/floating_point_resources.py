#!/usr/bin/env python3
"""Matched baseline/FPGA resource proof: SoftFloat, cycle contract and RAM geometry.

Uses the preserved baseline configuration and FPGA resource configuration from
one frozen source snapshot. Does not measure FPGA LUTs or routed timing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from zipfile import ZipFile
import run as common

REVISION = "a0c6494cdc11865811dec815d5c0049fba9d82a8"
ARCHIVE_SHA256 = "90493f9ad6c9760b2b1ca91251b8e7a3bb616b2935808d243e158a432a514f98"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--state-only", action="store_true")
    parser.add_argument("--cpu", action="store_true")
    parser.add_argument("--memory", action="store_true")
    parser.add_argument("--rtl", action="store_true")
    parser.add_argument("--profiles", nargs="+", choices=("baseline", "round", "fpga"),
                        default=("baseline", "round", "fpga"))
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        raise RuntimeError("unsafe tag")
    output = common.BUILD / ("fpga-fpu-" + args.tag)
    if (output / "receipt.json").exists():
        raise RuntimeError("preserve completed evidence; use a fresh tag")
    output.mkdir(parents=True, exist_ok=True)
    sources = [common.ROOT / "build.mill"]
    for directory in ("src/main/scala", "src/test/scala", "third_party/berkeley-hardfloat/src/main/scala"):
        sources += sorted((common.ROOT / directory).rglob("*.scala"))
    sources += sorted((common.HERE / "harness").glob("floating_point*"))
    sources += [common.HERE / "harness" / name for name in ("isa_model.h", "muldiv_model.h", "reference.h")]
    sources += [Path(__file__), common.HERE / "run.py", common.HERE / "config/floating-point-dependencies.json"]
    before = {str(p.relative_to(common.ROOT)): digest(p) for p in sources}
    git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=common.ROOT, text=True).strip()
    dependency = json.loads((common.HERE / "config/floating-point-dependencies.json").read_text())
    for name, expected in dependency["local_sources_sha256"].items():
        if digest(common.ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != expected:
            raise RuntimeError("pinned HardFloat source mismatch: " + name)
    (output / "inputs.json").write_text(json.dumps(before, indent=2) + "\n")
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "ASAN_OPTIONS": "detect_leaks=0"}
    source = Path(os.environ.get("GSIM_SOURCE", common.SOURCE)).resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if revision != common.LOCK["revision"] or subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True).strip():
        raise RuntimeError("GSIM revision/source mismatch")
    gsim = source / "build/gsim/gsim"
    cxx, compiler = common.compiler()
    common.run(["mill", "-i", "IonSoC.test.compile"], log=output / "scala.log")
    common.run(["mill", "-i", "IonSoC.test.testOnly", "ooo.FloatingPointResourceSpec"],
               log=output / "resource-config.log")
    results, artifacts = [], {}

    def record(directory, label):
        results.append({"test": label, "exit": 0, "log": (directory / "test.log").read_text().strip()})
        for path in directory.iterdir():
            if path.is_file():
                artifacts[str(path.relative_to(common.ROOT))] = digest(path)

    for mode in args.profiles:
        directory = common.test(gsim, cxx, "fpga-fpu-" + args.tag + "-state-" + mode,
            "ooo.FloatingPointStateGsimMain", "FloatingPointStateGsim", "floating_point_state.cpp",
            parameters=(mode,), defines={}, timeout=60)
        negative = subprocess.run([str(directory / "run"), "--inject-mismatch"], env=env,
            capture_output=True, text=True, timeout=60)
        if negative.returncode != 1 or "FP oracle mismatch" not in negative.stderr:
            raise RuntimeError("state negative control did not reject")
        (directory / "negative.log").write_text(negative.stdout + negative.stderr)
        record(directory, "state-" + mode)
    vector_sha256 = None
    if not args.state_only:
        archive = Path(os.environ["SOFTFLOAT_ARCHIVE"])
        if digest(archive) != ARCHIVE_SHA256:
            raise RuntimeError("SoftFloat archive hash mismatch")
        reference = output / "softfloat"
        prefix = "berkeley-softfloat-3-" + REVISION + "/"
        reference_hashes = {}
        with ZipFile(archive) as z:
            for entry in z.infolist():
                if entry.is_dir():
                    continue
                if not entry.filename.startswith(prefix):
                    raise RuntimeError("unexpected archive prefix")
                relative = entry.filename[len(prefix):]
                target = (reference / relative).resolve()
                if not target.is_relative_to(reference.resolve()):
                    raise RuntimeError("unsafe archive member")
                data = z.read(entry)
                if target.exists() and target.read_bytes() != data:
                    raise RuntimeError("reference source modified")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                reference_hashes[relative] = hashlib.sha256(data).hexdigest()
        build = reference / "build/Linux-x86_64-GCC"
        common.run(["make", "-j2"], cwd=build, log=output / "softfloat-build.log")
        common.run(["g++", "-std=c++20", "-O2", "-I" + str(reference / "source/include"),
            common.HERE / "harness/floating_point_full_vectors.cpp", build / "softfloat.a", "-o", output / "oracle"],
            log=output / "oracle-build.log")
        vectors = output / "vectors.txt"
        common.run([output / "oracle", vectors, "--stress", output / "negative"], log=output / "oracle.log")
        count = len(vectors.read_text().splitlines())
        if count != 73960:
            raise RuntimeError("stress vector count mismatch")
        vector_sha256 = digest(vectors)
        (output / "softfloat-inputs.json").write_text(json.dumps(reference_hashes, indent=2) + "\n")
        traces = {}
        for mode in args.profiles:
            trace = output / (mode + "-latency.txt")
            runtime = (vectors, "fd", "--expected-vectors=" + str(count), "--latency-trace=" + str(trace))
            directory = common.test(gsim, cxx, "fpga-fpu-" + args.tag + "-numerical-" + mode,
                "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim", "floating_point_full.cpp",
                parameters=("fd", mode), defines={}, runtime_args=runtime, timeout=300)
            for flag, reason in (("mismatch", "SoftFloat value"), ("flags", "SoftFloat flags"),
                                 ("boxing", "SoftFloat value"), ("rounding", "SoftFloat value")):
                negative = subprocess.run([str(directory / "run"), str(vectors), "fd",
                    "--expected-vectors=" + str(count), "--inject-" + flag], env=env,
                    capture_output=True, text=True, timeout=120)
                if negative.returncode != 1 or reason not in negative.stderr:
                    raise RuntimeError("numerical negative control failed: " + flag + negative.stderr)
                (directory / ("negative-" + flag + ".log")).write_text(negative.stdout + negative.stderr)
            for wrong in ("unfused", "double-rounded"):
                wrong_vectors = output / ("negative-" + wrong + ".txt")
                negative = subprocess.run([str(directory / "run"), str(wrong_vectors), "fd",
                    "--expected-vectors=1"], env=env, capture_output=True, text=True, timeout=30)
                if negative.returncode != 1 or "SoftFloat value" not in negative.stderr:
                    raise RuntimeError("one-round negative control failed: " + wrong + negative.stderr)
                (directory / ("negative-" + wrong + ".log")).write_text(negative.stdout + negative.stderr)
            record(directory, "numerical-" + mode)
            traces[mode] = trace.read_bytes()
        if len(set(traces.values())) != 1:
            raise RuntimeError("per-vector opcode/format latency changed")
        if args.cpu:
            for mode in args.profiles:
                directory = common.test(gsim, cxx, "fpga-fpu-" + args.tag + "-cpu-" + mode,
                    "ooo.FloatingPointFullCpuGsimMain", "FloatingPointCpuGsim", "floating_point_full_cpu.cpp",
                    parameters=(mode,), defines={}, runtime_args=(vectors,), timeout=300)
                negative = subprocess.run([str(directory / "run"), str(vectors), "--inject-mismatch"],
                    env=env, capture_output=True, text=True, timeout=120)
                if negative.returncode != 1 or "independent integer result/flags readback" not in negative.stderr:
                    raise RuntimeError("FP CPU negative control failed: " + negative.stderr)
                (directory / "negative.log").write_text(negative.stdout + negative.stderr)
                record(directory, "cpu-" + mode)
        if args.memory:
            common.run(["g++", "-std=c++20", "-O2", "-I" + str(reference / "source/include"),
                common.HERE / "harness/floating_point_vectors.cpp", build / "softfloat.a",
                "-o", output / "memory-oracle"], log=output / "memory-oracle-build.log")
            memory_vectors = output / "memory-vectors.txt"
            common.run([output / "memory-oracle", memory_vectors], log=output / "memory-oracle.log")
            for mode in args.profiles:
                for memory_mode in ("direct", "buffered"):
                    directory = common.test(gsim, cxx, "fpga-fpu-" + args.tag + "-memory-" + mode + "-" + memory_mode,
                        "ooo.FloatingPointMemoryCpuGsimMain", "FloatingPointCpuGsim", "floating_point_cpu.cpp",
                        parameters=(memory_mode, mode), defines={"FP_MEMORY": 1},
                        runtime_args=(memory_vectors,), timeout=300)
                    for flag, reason in (("--inject-mismatch", "commit value/metadata"),
                            ("--inject-fp-memory", "FP architectural RF"),
                            ("--inject-memory-request", "FP memory request payload")):
                        negative = subprocess.run([str(directory / "run"), str(memory_vectors), flag],
                            env=env, capture_output=True, text=True, timeout=60)
                        if negative.returncode != 1 or reason not in negative.stderr:
                            raise RuntimeError("precise FP memory negative control failed: " + flag + negative.stderr)
                        (directory / (flag.removeprefix("--") + ".log")).write_text(negative.stdout + negative.stderr)
                    record(directory, "memory-" + mode + "-" + memory_mode)
    if args.rtl:
        for mode in args.profiles:
            rtl = output / ("rtl-" + mode)
            common.run(["mill", "-i", "IonSoC.test.runMain", "ooo.FloatingPointResourceRtlMain", rtl, mode],
                log=output / ("rtl-" + mode + ".log"))
            for path in rtl.rglob("*.sv"):
                artifacts[str(path.relative_to(common.ROOT))] = digest(path)
    after = {str(p.relative_to(common.ROOT)): digest(p) for p in sources}
    if before != after:
        raise RuntimeError("source changed during proof; receipt withheld")
    receipt = {"status": "PASS_FUNCTIONAL_RESOURCE_CANDIDATE", "gsim_revision": revision,
        "compiler": compiler, "git_commit": git_commit, "source_sha256": before, "artifact_sha256": artifacts, "results": results,
        "softfloat_archive_sha256": None if args.state_only else ARCHIVE_SHA256,
        "vector_sha256": vector_sha256, "profiles": args.profiles,
        "latency_equal": None if args.state_only else len(args.profiles) > 1,
        "limits": "GSIM and structural evidence only. FPGA LUT/RAM mapping, routed timing and board behavior unmeasured."}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("FPGA_FPU_RESOURCE_PROOF_PASS " + str(output / "receipt.json"))


if __name__ == "__main__":
    main()
