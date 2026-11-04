#!/usr/bin/env python3
"""Independent C/A and SoftFloat F/D gates for the R5 ISA resource assessment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        ap.error("fresh output within clone build/ required")
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    paths = [Path(v.split(":", 3)[3]) for v in
             json.loads((ROOT / "out/OrbitalI1/test/runClasspath.json").read_text())["value"]]
    runtime = os.pathsep.join(str(p) for p in paths if p.exists())
    receipt = {"status": "RUNNING", "gsim_sha256": sha(gsim), "commands": [], "checks": {}}

    def run(argv, log, negative=None, cwd=ROOT):
        argv = [str(v) for v in argv]
        receipt["commands"].append({"argv": argv, "cwd": str(cwd), "log": str(log)})
        with log.open("w") as stream:
            result = subprocess.run(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        text = log.read_text()
        if negative:
            if result.returncode == 0 or negative not in text:
                raise RuntimeError("independent mutation was not rejected: " + str(log))
        elif result.returncode:
            raise RuntimeError("command failed: " + str(log))
        return text

    try:
        dep = json.loads((ROOT / "simulator/gsim/config/floating-point-dependencies.json").read_text())["softfloat"]
        dependency = json.loads((ROOT / "simulator/gsim/config/floating-point-dependencies.json").read_text())
        for name, digest in dependency["local_sources_sha256"].items():
            if sha(ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != digest:
                raise RuntimeError("pinned local HardFloat source drift: " + name)
        archive = ROOT / ("build/dependencies/softfloat-" + dep["revision"] + ".zip")
        if sha(archive) != dep["archive_sha256"]:
            raise RuntimeError("pinned SoftFloat archive drift")
        reference = output / "softfloat"
        prefix = "berkeley-softfloat-3-" + dep["revision"] + "/"
        with ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                if entry.is_dir():
                    continue
                if not entry.filename.startswith(prefix):
                    raise RuntimeError("unexpected pinned archive prefix")
                target = (reference / entry.filename[len(prefix):]).resolve()
                if not target.is_relative_to(reference.resolve()):
                    raise RuntimeError("archive path escapes reference root")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zipped.read(entry))
        ref_build = reference / "build/Linux-x86_64-GCC"
        run(["make", "-j2"], output / "softfloat-build.log", cwd=ref_build)
        run([cxx, "-std=c++20", "-O2", "-I" + str(reference / "source/include"),
             ROOT / "simulator/gsim/harness/floating_point_full_vectors.cpp", ref_build / "softfloat.a",
             "-o", output / "oracle"], output / "oracle-build.log")
        receipt["oracle"] = run([output / "oracle", output / "vectors.txt"], output / "oracle.log").strip()
        receipt["softfloat"] = {**dep, "vectors_sha256": sha(output / "vectors.txt")}
        cases = [
            ("compressed", "FiveStageCompressedMain", "FiveStageCompressed", "five_stage_compressed.cpp",
             ["64"], ["-DDUT_XLEN=64"], [], "--wrong-expansion", "independent exhaustive C expansion oracle"),
            ("parcels", "I1FetchParcelTimingMain", "I1FetchParcelTimingFixture", "five_stage_fetch_aligner.cpp",
             ["64"], ["-DDUT_XLEN=64", "-DI1_TIMING_CUTS=1", "-DI1_SCALAR_PARCEL_FIXTURE=1"], [], "--wrong-parcel", "independent C parcel byte oracle"),
            ("atomic", "FiveStageAtomicMain", "FiveStageAtomicMemory", "five_stage_atomic.cpp",
             ["64"], ["-DDUT_XLEN=64"], [], "--wrong-amo", "independent LR_SC_AMO result oracle")]
        cases.append(("fp-compressed", "I1FloatingPointCompressedMain", "I1FloatingPointCompressedGsim",
                      "five_stage_fp_compressed.cpp", [], [], [], "--wrong-expansion",
                      "independent compressed immediate/register expansion"))
        for profile in ["f", "fd"]:
            cases.append(("fp-" + profile, "I1FloatingPointMain", "I1FloatingPointGsim", "five_stage_fp_numerical.cpp",
                          ["--timing-cuts"] + (["--d"] if profile == "fd" else []), ["-DI1_TIMING_CUTS=1"],
                          [output / "vectors.txt", profile], "--inject-mismatch", "FP full mismatch: SoftFloat value"))
        source_paths = sorted((ROOT / "src/main/scala/core/inorder").glob("*.scala"))
        source_paths += sorted((ROOT / "third_party/berkeley-hardfloat/src/main/scala").glob("*.scala"))
        source_paths += [Path(__file__).resolve(), ROOT / "simulator/gsim/harness/i1_compressed_reference.h"]
        source_paths += [ROOT / "simulator/gsim/harness" / c[3] for c in cases]
        frozen = {str(p.relative_to(ROOT)): sha(p) for p in source_paths}
        receipt["source_sha256"] = frozen
        for name, entry, top, driver, flags, defines, arguments, mutation, error in cases:
            folder = output / name
            folder.mkdir()
            run(["java", "-cp", runtime, "inorder." + entry, folder, *flags], folder / "elaborate.log")
            run([gsim, "--threads=1", "--dir=" + str(folder), folder / (top + ".fir")], folder / "generate.log")
            run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 *defines, "-I" + str(folder), *sorted(folder.glob(top + "[0-9]*.cpp")),
                 ROOT / "simulator/gsim/harness" / driver, "-o", folder / "run"], folder / "compile.log")
            text = run([folder / "run", *arguments], folder / "positive.log")
            run([folder / "run", *arguments, mutation], folder / "negative.log", error)
            receipt["checks"][name] = {"summary": text.strip(), "negative_rejected": True}
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(name, text.strip(), flush=True)
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift during numerical gates")
        receipt["status"] = "PASS_INDEPENDENT_C_A_F_FD_SHORT_GATES"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)


if __name__ == "__main__":
    main()
