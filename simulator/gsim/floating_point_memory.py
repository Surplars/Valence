#!/usr/bin/env python3
"""M4 bounded FP memory CPU acceptance; independent bytes/oracle and pinned GSIM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import run as common


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="m4", help="fresh evidence tag; old receipts are never overwritten")
    args = parser.parse_args()
    if not args.tag or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in args.tag):
        raise RuntimeError("Invalid evidence tag")
    output = common.BUILD / ("floating-point-memory-" + args.tag)
    if (output / "receipt.json").exists():
        raise RuntimeError("Receipt already exists; choose a fresh --tag to preserve evidence")
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "ASAN_OPTIONS": "detect_leaks=0"}
    source = Path(os.environ.get("GSIM_SOURCE", common.SOURCE)).resolve()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, env=env, text=True).strip()
    if revision != common.LOCK["revision"] or subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, env=env, text=True).strip():
        raise RuntimeError("Pinned GSIM revision/source mismatch")
    gsim = source / "build/gsim/gsim"
    reference = common.BUILD / "floating-point-add-reference"
    vectors = reference / "vectors.txt"
    reference_receipt = json.loads((reference / "receipt.json").read_text())
    if reference_receipt["status"] != "PASS" or digest(vectors) != reference_receipt["vector_sha256"]:
        raise RuntimeError("Pinned SoftFloat vector receipt mismatch")
    nemu = Path(os.environ["NEMU_REFERENCE"])
    nemu_receipt = json.loads(Path(os.environ["NEMU_RECEIPT"]).read_text())
    lock = json.loads((common.HERE / "config/reference-lock.json").read_text())
    if nemu_receipt["revision"] != lock["revision"] or digest(nemu) != nemu_receipt["library_sha256"]:
        raise RuntimeError("Pinned NEMU reference receipt mismatch")
    cxx, compiler = common.compiler()
    results = []
    artifacts = {}

    def retained(name, argv, reason=None):
        p = subprocess.run([str(common.BUILD / name / "run"), *map(str, argv)],
                           env=env, capture_output=True, text=True, timeout=60)
        (output / (name + ("-negative" if reason else "-recheck") + ".log")).write_text(p.stdout + p.stderr)
        if p.returncode != (1 if reason else 0) or (reason and reason not in p.stderr):
            raise RuntimeError("Retained milestone recheck failed: " + name + p.stderr)
        print(p.stdout or p.stderr, end="", flush=True)
        results.append({"retained_model": name, "exit": p.returncode, "reason": reason})
        artifacts[str((common.BUILD / name / "run").relative_to(common.ROOT))] = digest(common.BUILD / name / "run")

    # Recheck retained, previously bound M1/M2/M3 models without regenerating or
    # overwriting their receipts. Fresh M3 and M4 CPU elaborations follow below.
    retained("floating-point-state-m1", ())
    retained("floating-point-state-m1", ("--inject-mismatch",), "FP oracle mismatch")
    retained("floating-point-add-m2", (vectors,))
    retained("floating-point-add-m2", (vectors, "--inject-mismatch"), "FP add mismatch: SoftFloat value")
    retained("floating-point-add-state-m2", (vectors,))
    retained("floating-point-add-state-m2", (vectors, "--inject-mismatch"), "FP integration mismatch: SoftFloat value")
    retained("floating-point-cpu-m3", (vectors,))
    retained("floating-point-cpu-m3", (vectors, "--inject-mismatch"), "FP CPU mismatch: commit value/metadata")

    common.run(["mill", "-i", "IonSoC.test"], log=output / "scala.log", timeout=240)

    def negative(directory, flag, reason):
        p = subprocess.run([str(directory / "run"), str(vectors), flag], env=env,
                           capture_output=True, text=True, timeout=60)
        (directory / (flag.removeprefix("--") + ".log")).write_text(p.stdout + p.stderr)
        if p.returncode != 1 or reason not in p.stderr:
            raise RuntimeError("Strict negative control failed: " + flag + p.stderr)
        return {"flag": flag, "exit": p.returncode, "reason": reason}

    # Fresh numeric producer/state models are mandatory after changing arithmetic
    # pipeline boundaries. Retained milestone binaries alone cannot validate it.
    for unit, main, top, harness, reason in [
        ("add", "ooo.FloatingPointAddGsimMain", "FloatingPointAddGsim",
         "floating_point_add.cpp", "FP add mismatch: SoftFloat value"),
        ("add-state", "ooo.FloatingPointAddStateGsimMain", "FloatingPointAddStateGsim",
         "floating_point_add_state.cpp", "FP integration mismatch: SoftFloat value"),
    ]:
        directory = common.test(gsim, cxx, output.name + "-" + unit, main,
                                top, harness, runtime_args=(vectors,), timeout=60)
        negatives = [negative(directory, "--inject-mismatch", reason)]
        results.append({"unit": unit, "positive_exit": 0,
                        "positive": (directory / "test.log").read_text(), "negative_controls": negatives})
        for p in [directory / "run", directory / (top + ".fir"), directory / (top + ".h"),
                  *directory.glob(top + "[0-9]*.cpp")]:
            artifacts[str(p.relative_to(common.ROOT))] = digest(p)
    for mode in ["subset", "direct", "buffered"]:
        directory = common.test(gsim, cxx, output.name + "-" + mode,
            "ooo.FloatingPointCpuGsimMain" if mode == "subset" else "ooo.FloatingPointMemoryCpuGsimMain",
            "FloatingPointCpuGsim", "floating_point_cpu.cpp", parameters=() if mode == "subset" else (mode,),
            defines={} if mode == "subset" else {"FP_MEMORY": 1}, runtime_args=(vectors,), timeout=90)
        negatives = [negative(directory, "--inject-mismatch", "FP CPU mismatch: commit value/metadata")]
        if mode != "subset":
            negatives += [negative(directory, "--inject-fp-memory", "FP CPU mismatch: FP architectural RF"),
                          negative(directory, "--inject-memory-request", "FP CPU mismatch: FP memory request payload")]
        results.append({"mode": mode, "positive_exit": 0, "positive": (directory / "test.log").read_text(),
                        "negative_controls": negatives})
        for p in [directory / "run", directory / "FloatingPointCpuGsim.fir",
                  directory / "FloatingPointCpuGsim.h", *directory.glob("FloatingPointCpuGsim[0-9]*.cpp")]:
            artifacts[str(p.relative_to(common.ROOT))] = digest(p)
    for mode in ["disabled", "enabled"]:
        directory = common.test(gsim, cxx, output.name + "-integer-" + mode,
            "ooo.FloatingPointIntegerRegressionGsimMain", "MachineCoreGsim", "machine.cpp",
            parameters=(mode,), defines={}, runtime_args=(nemu,), timeout=120)
        p = subprocess.run([str(directory / "run"), str(nemu), "--inject-mismatch"],
                           env=env, capture_output=True, text=True, timeout=60)
        (directory / "negative.log").write_text(p.stdout + p.stderr)
        if p.returncode != 1 or "commit data/nextPC" not in p.stderr:
            raise RuntimeError("Integer differential negative control failed")
        results.append({"integer": mode, "positive_exit": 0, "negative_exit": 1,
                        "positive": (directory / "test.log").read_text()})
        for p in [directory / "run", directory / "MachineCoreGsim.fir",
                  directory / "MachineCoreGsim.h", *directory.glob("MachineCoreGsim[0-9]*.cpp")]:
            artifacts[str(p.relative_to(common.ROOT))] = digest(p)
    paths = list((common.ROOT / "src/main/scala/core/ooo").glob("*.scala"))
    paths += list((common.ROOT / "third_party/berkeley-hardfloat/src/main/scala").glob("*.scala"))
    paths += [common.ROOT / p for p in ["build.mill", "src/test/scala/ooo/FloatingPointCpuGsim.scala",
              "src/test/scala/ooo/MachineCoreGsim.scala", "src/test/scala/ooo/OooParamsSpec.scala",
              "src/test/scala/ooo/FloatingPointAddGsim.scala", "src/test/scala/ooo/FloatingPointStateGsim.scala"]]
    paths += [common.HERE / p for p in ["floating_point_memory.py", "run.py", "config/toolchain.json",
              "config/reference-lock.json", "config/floating-point-dependencies.json", "harness/floating_point_cpu.cpp",
              "harness/machine.cpp", "harness/isa_model.h", "harness/muldiv_model.h", "harness/reference.h",
              "harness/floating_point_add.cpp", "harness/floating_point_add_state.cpp"]]
    (output / "receipt.json").write_text(json.dumps({"status": "PASS", "milestone": "M4 bounded FP memory",
        "repository": str(common.ROOT), "base_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=common.ROOT, env=env, text=True).strip(),
        "gsim_revision": revision, "compiler": compiler, "softfloat_revision": reference_receipt["softfloat_revision"],
        "vector_sha256": digest(vectors), "nemu_library_sha256": digest(nemu), "results": results,
        "artifact_sha256": artifacts,
        "source_sha256": {str(p.relative_to(common.ROOT)): digest(p) for p in paths},
        "limits": "Experimental bounded CPU subset incl FLW/FSW/FLD/FSD; default off, misa F/D off. "
                  "Injected page-fault response checks are not pagetable/OS FP-context proof. "
                  "Remaining F/D arithmetic, compressed FP memory, second RTL backend and FPGA timing unverified."}, indent=2)+"\n")
    print("FP_MEMORY_M4_ACCEPTANCE: PASS (both memory configurations, fresh M3, integer off/on, strict negatives)")


if __name__ == "__main__":
    main()
