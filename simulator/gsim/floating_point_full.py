#!/usr/bin/env python3
"""Bounded full RV64 F/D candidate acceptance. GSIM only; pinned SoftFloat oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile
import run as common

REVISION = "a0c6494cdc11865811dec815d5c0049fba9d82a8"
ARCHIVE_SHA256 = "90493f9ad6c9760b2b1ca91251b8e7a3bb616b2935808d243e158a432a514f98"

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="20261003")
    args = parser.parse_args()
    if not args.tag or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.tag):
        raise RuntimeError("Unsafe evidence tag")
    output = common.BUILD / ("floating-point-full-" + args.tag)
    if (output / "receipt.json").exists():
        raise RuntimeError("Receipt exists; use a fresh evidence tag")
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "ASAN_OPTIONS": "detect_leaks=0"}
    archive = Path(os.environ.get("SOFTFLOAT_ARCHIVE", str(common.ROOT /
        f"build/fd-handoff/20261003-windows/fd-evidence/dependencies/softfloat-{REVISION}.zip")))
    if digest(archive) != ARCHIVE_SHA256:
        raise RuntimeError("SoftFloat archive mismatch")
    source = output / "softfloat"
    prefix = f"berkeley-softfloat-3-{REVISION}/"
    reference_hashes = {}
    with ZipFile(archive) as z:
        for entry in z.infolist():
            if entry.is_dir():
                continue
            if not entry.filename.startswith(prefix):
                raise RuntimeError("Unexpected reference archive prefix")
            relative = entry.filename[len(prefix):]
            target = (source / relative).resolve()
            if not target.is_relative_to(source.resolve()):
                raise RuntimeError("Unsafe archive member")
            data = z.read(entry)
            if target.exists() and target.read_bytes() != data:
                raise RuntimeError("Modified independent reference: " + relative)
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            reference_hashes[relative] = hashlib.sha256(data).hexdigest()
    gsim_source = Path(os.environ.get("GSIM_SOURCE", common.SOURCE)).resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gsim_source, env=env, text=True).strip()
    if revision != common.LOCK["revision"] or subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gsim_source, env=env, text=True).strip():
        raise RuntimeError("GSIM revision/source mismatch")
    dependency = json.loads((common.HERE / "config/floating-point-dependencies.json").read_text())
    for name, sha in dependency["local_sources_sha256"].items():
        if digest(common.ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != sha:
            raise RuntimeError("Vendored source mismatch: " + name)
    sources = [common.ROOT / "build.mill", common.ROOT / "src/main/scala/isa/Compressed.scala"]
    sources += sorted((common.ROOT / "src/main/scala/core/ooo").glob("*.scala"))
    sources += sorted((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").glob("*.scala"))
    sources += sorted((common.ROOT / "src/test/scala/ooo").glob("FloatingPoint*.scala"))
    sources += sorted((common.HERE / "harness").glob("floating_point*.cpp"))
    sources += [common.HERE / "floating_point_full.py", common.HERE / "run.py",
        common.HERE / "config/floating-point-dependencies.json"]
    sources += [common.ROOT / "src/test/scala/ooo/OooParamsSpec.scala",
        common.ROOT / "src/test/scala/ooo/MachineCoreGsim.scala"]
    sources += [common.HERE / "harness" / name for name in
        ("machine.cpp", "isa_model.h", "muldiv_model.h", "reference.h")]
    sources += [common.HERE / "config/reference-lock.json"]
    before = {str(p.relative_to(common.ROOT)): digest(p) for p in sources}
    (output / "inputs.json").write_text(json.dumps(before, indent=2)+"\n")
    # All instruction groups are implemented before this first consolidated compile.
    common.run(["mill", "-i", "IonSoC.test.compile"], log=output / "scala.log", timeout=300)
    common.run(["mill", "-i", "IonSoC.test.testOnly", "ooo.OooParamsSpec", "--",
        "-z", "F/D configuration"], log=output / "configuration.log", timeout=120)
    reference_build = source / "build/Linux-x86_64-GCC"
    common.run(["make", "-j4"], cwd=reference_build, log=output / "softfloat-build.log")
    common.run(["g++", "-std=c++20", "-O2", "-I" + str(source / "source/include"),
        common.HERE / "harness/floating_point_full_vectors.cpp", reference_build / "softfloat.a",
        "-o", output / "oracle"], log=output / "oracle-build.log")
    vectors = output / "vectors.txt"
    common.run([output / "oracle", vectors], log=output / "oracle-test.log")
    print((output / "oracle-test.log").read_text(), end="", flush=True)
    cxx, compiler = common.compiler()
    gsim = gsim_source / "build/gsim/gsim"
    results, artifacts = [], {}
    tests = [
        ("numerical-fd", "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim", "floating_point_full.cpp", ("fd",), (vectors, "fd")),
        ("numerical-f", "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim", "floating_point_full.cpp", ("f",), (vectors, "f")),
        ("numerical-small", "ooo.FloatingPointFullGsimMain", "FloatingPointFullGsim", "floating_point_full.cpp", ("small",), (vectors, "small")),
        ("compressed", "ooo.FloatingPointCompressedGsimMain", "FloatingPointCompressedGsim", "floating_point_compressed.cpp", (), ()),
        ("cpu", "ooo.FloatingPointFullCpuGsimMain", "FloatingPointCpuGsim", "floating_point_full_cpu.cpp", (), (vectors,)),
    ]
    for suffix, emitter, top, harness, parameters, runtime in tests:
        directory = common.test(gsim, cxx, f"floating-point-full-{args.tag}-{suffix}",
            emitter, top, harness, parameters=parameters, runtime_args=runtime, defines={}, timeout=120)
        results.append({"test": suffix, "exit": 0, "log": (directory / "test.log").read_text().strip()})
        if suffix != "compressed":
            negative = subprocess.run([str(directory / "run"), *map(str,runtime), "--inject-mismatch"],
                env=env, capture_output=True, text=True, timeout=120)
            (directory / "negative.log").write_text(negative.stdout + negative.stderr)
            expected = "FP full CPU mismatch: independent integer result" if suffix == "cpu" else "FP full mismatch: SoftFloat value"
            if negative.returncode != 1 or expected not in negative.stderr:
                raise RuntimeError("Negative control did not reject intended mismatch: " + suffix + negative.stderr)
            results.append({"negative": suffix, "exit": 1, "reason": negative.stderr.strip()})
        fir = (directory / f"{top}.fir").read_text()
        if suffix in ("numerical-f", "numerical-small") and any(
            marker in fir for marker in ("module FloatingPointAddD", "module FloatingPointMultiplyD",
                "module FloatingPointFusedD", "module FloatingPointDivSqrtD", "module FloatingPointMiscD")):
            raise RuntimeError("D units present in F-only hardware")
        if suffix == "numerical-small" and any(marker in fir for marker in
            ("module FloatingPointMultiply", "module FloatingPointFused", "module FloatingPointDivSqrt",
             "module INToRecFN", "module RecFNToIN")):
            raise RuntimeError("Pruned producer was instantiated")
        for p in directory.iterdir():
            if p.is_file() and (p.name=="run" or p.suffix in (".fir",".cpp",".h")):
                artifacts[str(p.relative_to(common.ROOT))]=digest(p)
    # Existing precise-memory oracle retains faults/PMP/stalls/wrong-path checks,
    # but uses fresh real-CPU models after the new numerical dispatcher was wired.
    old_vectors = common.BUILD / "floating-point-add-reference/vectors.txt"
    old_reference = json.loads((old_vectors.parent / "receipt.json").read_text())
    if old_reference["status"] != "PASS" or digest(old_vectors) != old_reference["vector_sha256"]:
        raise RuntimeError("M4 independent vector receipt mismatch")
    for mode in ("direct", "buffered"):
        directory = common.test(gsim, cxx, f"floating-point-full-{args.tag}-memory-{mode}",
            "ooo.FloatingPointMemoryCpuGsimMain", "FloatingPointCpuGsim", "floating_point_cpu.cpp",
            parameters=(mode,), defines={"FP_MEMORY":1}, runtime_args=(old_vectors,), timeout=90)
        results.append({"test":"memory-"+mode,"exit":0,"log":(directory/"test.log").read_text().strip()})
        for flag, reason in (
            ("--inject-mismatch","FP CPU mismatch: commit value/metadata"),
            ("--inject-fp-memory","FP CPU mismatch: FP architectural RF"),
            ("--inject-memory-request","FP CPU mismatch: FP memory request payload")):
            negative = subprocess.run([str(directory/"run"),str(old_vectors),flag],
                env=env,capture_output=True,text=True,timeout=60)
            (directory/(flag.removeprefix("--")+".log")).write_text(negative.stdout+negative.stderr)
            if negative.returncode!=1 or reason not in negative.stderr:
                raise RuntimeError("Memory negative control failed: "+mode+flag)
            results.append({"negative":"memory-"+mode+flag,"exit":1,"reason":negative.stderr.strip()})
        for p in directory.iterdir():
            if p.is_file() and (p.name=="run" or p.suffix in (".fir",".cpp",".h")):
                artifacts[str(p.relative_to(common.ROOT))]=digest(p)
    nemu = common.BUILD / "nemu-src/build/riscv64-nemu-interpreter-so"
    nemu_receipt = json.loads((common.BUILD / "reference-used.json").read_text())
    nemu_lock = json.loads((common.HERE / "config/reference-lock.json").read_text())
    if nemu_receipt["revision"] != nemu_lock["revision"] or digest(nemu) != nemu_receipt["library_sha256"]:
        raise RuntimeError("NEMU reference lock mismatch")
    for mode in ("disabled","enabled"):
        directory = common.test(gsim,cxx,f"floating-point-full-{args.tag}-integer-{mode}",
            "ooo.FloatingPointIntegerRegressionGsimMain","MachineCoreGsim","machine.cpp",
            parameters=(mode,),defines={},runtime_args=(nemu,),timeout=120)
        results.append({"test":"integer-"+mode,"exit":0,"log":(directory/"test.log").read_text().strip()})
        negative=subprocess.run([str(directory/"run"),str(nemu),"--inject-mismatch"],
            env=env,capture_output=True,text=True,timeout=60)
        (directory/"negative.log").write_text(negative.stdout+negative.stderr)
        if negative.returncode!=1 or "commit data/nextPC" not in negative.stderr:
            raise RuntimeError("Integer negative control failed")
        results.append({"negative":"integer-"+mode,"exit":1,"reason":negative.stderr.strip()})
        for p in directory.iterdir():
            if p.is_file() and (p.name=="run" or p.suffix in (".fir",".cpp",".h")):
                artifacts[str(p.relative_to(common.ROOT))]=digest(p)
    after = {str(p.relative_to(common.ROOT)): digest(p) for p in sources}
    if before != after:
        raise RuntimeError("Sources changed during batch; receipt withheld")
    receipt = {"status":"PASS_FUNCTIONAL_CANDIDATE", "gsim_revision":revision, "compiler":compiler,
        "softfloat_revision":REVISION, "softfloat_archive_sha256":ARCHIVE_SHA256,
        "softfloat_source_sha256":reference_hashes, "vector_sha256":digest(vectors),
        "nemu_library_sha256":digest(nemu), "nemu_limits":"FPU_NONE: integer regression only, never the FP numerical oracle",
        "source_sha256":before, "artifact_sha256":artifacts, "results":results,
        "limits":"Not Linux context-switch acceptance, external RTL cross-check or FPGA timing/area signoff. F/D defaults off; only explicit complete ISA profiles advertise F/D in misa/DT, never experimental subsets."}
    (output / "receipt.json").write_text(json.dumps(receipt,indent=2)+"\n")
    print("FP_FULL_FUNCTIONAL_ACCEPTANCE: PASS")

if __name__ == "__main__":
    main()
