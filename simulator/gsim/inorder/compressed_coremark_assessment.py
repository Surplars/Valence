#!/usr/bin/env python3
"""Use existing GSIM models to compare fixed IM code and real compressed CoreMark code."""
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
from extensions_assessment import PROFILES


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", type=Path, required=True)
    ap.add_argument("--profiles", nargs="+", choices=PROFILES, default=list(PROFILES),
                    help="profiles to assess using existing models (default: all)")
    ap.add_argument("--compressed-model", type=Path, required=True, help="qualified exhaustive C GSIM model directory")
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    models, output = args.models.resolve(), args.output.resolve()
    compressed_model = args.compressed_model.resolve()
    if output.exists() or not all(p.is_relative_to(ROOT / "build") for p in [models, output, compressed_model]):
        ap.error("existing models and fresh output within clone build/ required")
    output.mkdir(parents=True)
    gsim, cxx = common.setup(False)
    receipt = {"status": "RUNNING", "commands": [], "profiles": {}, "requested_profiles": args.profiles,
               "gsim_sha256": sha(gsim)}

    def run(argv, log, negative=None):
        argv = [str(v) for v in argv]
        receipt["commands"].append({"argv": argv, "log": str(log)})
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
        source = ROOT / "simulator/build/coremark-src"
        if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip() != "1f483d5b8316753a742cbf5590caf5bd0a4e4777":
            raise RuntimeError("CoreMark source pin drift")
        if subprocess.check_output(["git", "status", "--porcelain"], cwd=source, text=True).strip():
            raise RuntimeError("CoreMark algorithms must stay pristine")
        port = ROOT / "simulator/gsim/inorder/coremark_port"
        startup = ROOT / "simulator/gsim/payloads/coremark_port"
        gcc = "riscv64-unknown-elf-gcc"
        compiler = subprocess.check_output([gcc, "--version"], text=True).splitlines()[0]
        flags = ["-O3", "-march=rv64imc_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
                 "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib",
                 "-nostartfiles", "-DITERATIONS=1", "-DPERFORMANCE_RUN=1", "-DTOTAL_DATA_SIZE=2000",
                 '-DCOMPILER_FLAGS="-O3 -march=rv64imc_zicsr_zifencei -mabi=lp64 ITERATIONS=1 TOTAL_DATA_SIZE=2000"',
                 '-DCOMPILER_VERSION="' + compiler + '"', '-DMEM_LOCATION="GSIM matched cached CPU/service"']
        run([gcc, *flags, "-I" + str(port), "-I" + str(source), "-T" + str(startup / "link.ld"),
             startup / "start.S", *[source / n for n in
             ["core_list_join.c", "core_main.c", "core_matrix.c", "core_state.c", "core_util.c"]],
             port / "core_portme.c", "-lgcc", "-o", output / "coremark-c.elf"], output / "payload-build.log")
        run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / "coremark-c.elf", output / "coremark-c.bin"],
            output / "objcopy.log")
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", output / "coremark-c.elf"], text=True)
        (output / "symbols.txt").write_text(symbols)
        values = {l.split()[-1]: int(l.split()[0], 16) for l in symbols.splitlines() if len(l.split()) == 3}
        receipt["compressed_payload"] = {"flags": flags, "sha256": sha(output / "coremark-c.bin"),
                                         "bytes": (output / "coremark-c.bin").stat().st_size, "symbols": values}
        paths = [ROOT / "simulator/gsim/harness" / n for n in
                 ["five_stage.cpp", "five_stage_coremark.cpp", "i1_prediction_metrics.h", "i1_extensions.cpp",
                  "five_stage_compressed.cpp", "i1_compressed_reference.h"]]
        paths += [Path(__file__).resolve()]
        frozen = {str(p.relative_to(ROOT)): sha(p) for p in paths}
        receipt["source_sha256"] = frozen
        # The shared C oracle must retain the original exhaustive expansion contract.
        cmodel = compressed_model
        run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
             "-DDUT_XLEN=64", "-I" + str(cmodel), *sorted(cmodel.glob("FiveStageCompressed[0-9]*.cpp")),
             ROOT / "simulator/gsim/harness/five_stage_compressed.cpp", "-o", output / "compressed-check"],
             output / "compressed-compile.log")
        receipt["exhaustive_compressed"] = run([output / "compressed-check"], output / "compressed-positive.log").strip()
        run([output / "compressed-check", "--wrong-expansion"], output / "compressed-negative.log",
            "independent exhaustive C expansion oracle")
        for name in args.profiles:
            extra = PROFILES[name]
            parent = models / name
            previous = json.loads((parent / "receipt.json").read_text())
            if previous["status"] != "PASS_GSIM_READY_FOR_VIVADO" or previous["gsim_sha256"] != sha(gsim):
                raise RuntimeError("unqualified parent GSIM model")
            folder = output / name
            folder.mkdir()
            objects = sorted(parent.glob("I1PerformanceCachedCore[0-9]*.o"))
            defines = ["-DI1_COREMARK_PREDICTION=1"] + ["-DI1_WITH_" + f[2:].upper() + "=1" for f in extra]
            if "--c" in extra:
                defines += ["-DI1_COREMARK_COMPRESSED=1", "-DDUT_HAS_C=1"]
            compile_flags = [cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                             "-fno-sanitize-recover=all", *defines, "-I" + str(parent)]
            for binary, driver in [("extensions", "i1_extensions.cpp"), ("coremark", "five_stage_coremark.cpp")]:
                run([*compile_flags, *objects, ROOT / "simulator/gsim/harness" / driver, "-o", folder / binary],
                    folder / (binary + "-compile.log"))
            result = {"parent_receipt_sha256": sha(parent / "receipt.json"),
                      "model_fir_sha256": sha(parent / "I1PerformanceCachedCore.fir"),
                      "model_object_sha256": {p.name: sha(p) for p in objects}, "fixed_im": [], "compressed": []}
            result["functional"] = run([folder / "extensions"], folder / "functional.log").strip()
            run([folder / "extensions", "--inject"], folder / "functional-negative.log",
                "extension independent integer value oracle")
            for kind in ["fixed_im"] + (["compressed"] if "--c" in extra else []):
                image = ROOT / "build/i1-numerical-20261103-r1/coremark-r2/payload/coremark.bin" if kind == "fixed_im" else output / "coremark-c.bin"
                addresses = ["0x8001081c", "0x80010800", "0x80010808"] if kind == "fixed_im" else [
                    hex(values[k]) for k in ["coremark_validation_errors", "coremark_elapsed_ticks", "coremark_crcs"]]
                for latency in [1, 12]:
                    argv = [folder / "coremark", image, *addresses, latency]
                    text = run(argv, folder / (kind + "-l" + str(latency) + ".log"))
                    def row(prefix):
                        return json.loads(next(l[len(prefix):] for l in text.splitlines() if l.startswith(prefix)))
                    value = {**row("MATCHED_COREMARK_PASS "), **row("I1_COREMARK_PREDICTION "), "latency": latency}
                    value["ipc"] = value["roi_instructions"] / value["roi_ticks"]
                    perf = dict(token.split("=", 1) for token in
                                next(l for l in text.splitlines() if l.startswith("I1_PERF ")).split()[1:])
                    value["whole_program_length_repairs"] = int(perf["length_repairs"])
                    value["frontend_length_repairs"] = int(perf["frontend_length_repairs"])
                    result[kind].append(value)
                    print(name, kind, latency, value["roi_ticks"], value["ipc"], flush=True)
                run([*argv, "--inject"], folder / (kind + "-negative.log"), "CoreMark independent register oracle mismatch")
                run([*argv, "--inject-prediction-observer"], folder / (kind + "-prediction-negative.log"),
                    "prediction observation mismatch")
                if kind == "compressed":
                    run([*argv, "--inject-length-observer"], folder / "compressed-length-negative.log",
                        "independent frontend length repair oracle")
            if any(a[k] != dict(b, branch_accuracy=b["roi_correct"]/b["roi_branches"])[k]
                   for a, b in zip(previous["coremark"], result["fixed_im"]) for k in a):
                raise RuntimeError("extended software oracle changed the fixed-binary measurements")
            receipt["profiles"][name] = result
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        for name, digest in frozen.items():
            if sha(ROOT / name) != digest:
                raise RuntimeError("source drift")
        receipt["status"] = "PASS_FIXED_BINARY_AND_REAL_COMPRESSED_COREMARK"
    except BaseException as error:
        receipt.update(status="FAIL", error=repr(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)


if __name__ == "__main__":
    main()
