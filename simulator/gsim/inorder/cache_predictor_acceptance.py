#!/usr/bin/env python3
"""One batched short GSIM gate: cache/predictor ownership + matched bare CoreMark, no Vivado."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    paths = [ROOT / "build.mill", Path(__file__).resolve(), ROOT / "simulator/gsim/run.py",
             ROOT / "simulator/gsim/config/toolchain.json"]
    for folder, pattern in (("src/main/scala", "*.scala"), ("src/test/scala/inorder", "*.scala"),
                            ("simulator/gsim/inorder/coremark_port", "*")):
        paths += [p for p in (ROOT / folder).rglob(pattern) if p.is_file()]
    paths += [ROOT / "src/test/scala/ooo/InorderMatchedCoremark.scala"]
    paths += list((ROOT / "third_party/berkeley-hardfloat/src").rglob("*.scala"))
    paths += sorted((ROOT / "simulator/gsim/harness").glob("five_stage*.cpp"))
    paths += [ROOT / f"simulator/gsim/payloads/coremark_port/{f}" for f in ("start.S", "link.ld")]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--coremark-source", type=Path,
                    default=Path("/home/openion/Valence/simulator/build/coremark-src"))
    ap.add_argument("--reuse-models", type=Path, help="Reuse ONLY source/recipe/artifact-hash-identical models; rerun tests")
    ap.add_argument("--inorder-throughput", action="store_true",
                    help="Test only affected I1 throughput candidates; do NOT rerun the frozen OoO model")
    ap.add_argument("--reference-receipt", type=Path, help="Frozen previous matched receipt for throughput mode")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    if args.inorder_throughput != bool(args.reference_receipt):
        ap.error("--inorder-throughput requires --reference-receipt, used only in that mode")
    output = ROOT / "build/gsim" / ("five-stage-cache-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite earlier evidence")
    output.mkdir(parents=True)
    frozen = sources()
    receipt = {"status": "RUNNING", "source_sha256": frozen,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "scope": "Short RV64IM bare-core comparison, NOT >=10s formal CoreMark, full VL100, Linux, "
                 "NaxRiscv performance, synthesis or board timing.",
        "pipeline": ["IF", "ID", "EX", "MEM", "WB"],
        "cache": {"ic_bytes": 2048, "dc_bytes": 2048, "line_bytes": 64, "ways": 1,
                  "write_policy": "write-through, no-write-allocate", "payload_bits": 32768,
                  "tags": "synchronous RAM", "predictor": "64-entry tagged BTB + 2-bit counter; distributed RAM"},
        "ooo": {"source": "unchanged IntegerCore at this worktree HEAD", "issue": 2, "commit": 2,
                "rob": 32, "prf": 64, "memory_entries": 4, "store_buffer": 4, "bht": 64,
                "fetch": "64-bit synchronous word, two aligned RV64IM instructions; no C", "sv39": False,
                "machine_system": True, "pmp_entries": 0},
        "service_law": "Identical shared 64-bit round-robin I/D server, one capture/arbitration cycle plus "
                       "1 or 12 first-response service cycles (and waiting behind the other owner), "
                       "one beat/cycle afterwards, at most one owner per cache, real store acknowledgements.",
        "checks": {}, "benchmarks": {}, "new_configuration_physical_qualified": False}
    if args.inorder_throughput:
        receipt["scope"] = "Short I1-only early MEM ownership / write-through tag overlap / tiled DSP batch. " \
            "Frozen OoO results are read-only historical references, NOT rerun or new measurements. " \
            "Not formal CoreMark, Linux, synthesis, DSP mapping or board timing."
        receipt["throughput_options"] = {"early_memory_issue":
            "EX transfer into an empty slot or retiring fault-free non-memory MEM packet; never behind a memory reply",
            "overlap_write_lookup": "write-through burst dispatch overlaps synchronous tag capture",
            "dsp_tiled": "unsigned 32-bit products, carry-save recombination, registered high-half sign correction",
            "geometry_unchanged": True, "queue_capacity_unchanged": True,
            "stall_counters": "whole run; overlapping causes, not additive ROI cycle attribution"}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        source = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=source, text=True):
            raise RuntimeError("pinned GSIM revision/cleanliness mismatch")
        gsim = source / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["toolchain"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version,
            "guest_cc": subprocess.check_output(["riscv64-unknown-elf-gcc", "--version"], text=True).splitlines()[0]}
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"], log=output / "scala.log")

        def model(name, main, top, driver, flags=(), defines=(), module="OrbitalI1", sanitizer=True):
            out = output / name
            out.mkdir()
            if module == "OrbitalI1":
                dependencies = {p: h for p, h in frozen.items() if p == "build.mill" or
                    p.startswith(("src/main/scala/core/inorder/", "src/main/scala/isa/", "src/test/scala/inorder/"))}
            else:
                dependencies = {p: h for p, h in frozen.items() if p == "build.mill" or
                    p.startswith(("src/main/scala/", "third_party/berkeley-hardfloat/src/")) or
                    p == "src/test/scala/ooo/InorderMatchedCoremark.scala"}
            for filename in (driver, "five_stage.cpp"):
                key = "simulator/gsim/harness/" + filename
                dependencies[key] = frozen[key]
            recipe = {"main": main, "top": top, "module": module, "flags": list(flags),
                      "defines": list(defines), "sanitizer": sanitizer, "optimization": "-O1",
                      "cxx": version, "gsim_sha256": sha(gsim), "dependencies_sha256": dependencies}
            if args.reuse_models:
                candidate = args.reuse_models.resolve() / name
                manifest_path = candidate / "model-manifest.json"
                if manifest_path.is_file():
                    manifest = json.loads(manifest_path.read_text())
                    if manifest["recipe"] == recipe:
                        for filename, digest in manifest["artifacts_sha256"].items():
                            if Path(filename).name != filename or sha(candidate / filename) != digest:
                                raise RuntimeError("reused model artifact/path drift")
                            shutil.copy2(candidate / filename, out / filename)
                        shutil.copy2(manifest_path, out / "model-manifest.json")
                        receipt.setdefault("reused_models", {})[name] = {"path": str(candidate),
                            "manifest_sha256": sha(manifest_path), "test_results_reused": False}
                        print("REUSED_HASH_IDENTICAL_MODEL " + name + "; running fresh checks", flush=True)
                        return out
            arguments = [out, 64, *flags] if module == "OrbitalI1" else [out]
            # RV32 component profile supplies its own width before the optional flags.
            if "-DDUT_XLEN=32" in defines:
                arguments[1] = 32
            common.run(["mill", "-i", module + ".test.runMain", main, *arguments], log=out / "elaborate.log")
            common.run([gsim, "--threads=1", f"--dir={out}", out / (top + ".fir")], log=out / "generate.log")
            options = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if sanitizer else []
            common.run([cxx, "-std=c++20", "-O1", *options, *defines, "-I" + str(out),
                        *sorted(out.glob(top + "[0-9]*.cpp")), ROOT / "simulator/gsim/harness" / driver,
                        "-o", out / "run"], log=out / "compile.log", timeout=900)
            artifacts = {p.name: sha(p) for p in out.iterdir() if p.is_file() and
                         (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
            (out / "model-manifest.json").write_text(json.dumps({"recipe": recipe,
                "artifacts_sha256": artifacts}, indent=2) + "\n")
            return out

        components = [
            ("cache64", "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
             ["--dcache=512"], ["-DCACHE_BYTES=512"]),
            ("cache-disabled", "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
             [], ["-DCACHE_BYTES=0"]),
            ("cache64-flow", "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
             ["--dcache=512", "--flow-hits"], ["-DCACHE_BYTES=512", "-DCACHE_FLOW=1"]),
            ("cache32", "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
             ["--dcache=512"], ["-DCACHE_BYTES=512", "-DDUT_XLEN=32"]),
            ("predictor", "inorder.FiveStagePredictorMain", "FiveStageBranchPredictor", "five_stage_predictor.cpp",
             ["--predictor=64"], []),
            ("integer-no-prediction", "inorder.FiveStageMain", "FiveStageCore", "five_stage.cpp", [], []),
            ("integer-prediction", "inorder.FiveStageMain", "FiveStageCore", "five_stage.cpp", ["--predictor=64"], [])]
        if args.inorder_throughput:
            components = [
                ("cache-overlap64", "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
                 ["--dcache=512", "--overlap-write-lookup"], ["-DCACHE_BYTES=512"]),
                ("cache-overlap32", "inorder.FiveStageCacheMain", "FiveStageWordCache", "five_stage_cache.cpp",
                 ["--dcache=512", "--overlap-write-lookup"], ["-DCACHE_BYTES=512", "-DDUT_XLEN=32"]),
                ("integer-early64", "inorder.FiveStageMain", "FiveStageCore", "five_stage_early_memory.cpp",
                 ["--early-memory-issue", "--dsp-tiled"], []),
                ("integer-early32", "inorder.FiveStageMain", "FiveStageCore", "five_stage_early_memory.cpp",
                 ["--early-memory-issue", "--dsp-tiled"], ["-DDUT_XLEN=32"]),
                ("integer-early-no-m", "inorder.FiveStageMain", "FiveStageCore", "five_stage_early_memory.cpp",
                 ["--early-memory-issue", "--no-m"], ["-DDUT_HAS_M=0"]),
                ("mdu-tiled64", "inorder.FiveStageMulDivMain", "FiveStageMulDiv", "five_stage_mul_div.cpp",
                 ["--dsp-tiled"], []),
                ("mdu-tiled32", "inorder.FiveStageMulDivMain", "FiveStageMulDiv", "five_stage_mul_div.cpp",
                 ["--dsp-tiled"], ["-DDUT_XLEN=32"])]
        for name, main_name, top, driver, flags, defines in components:
            out = model(name, main_name, top, driver, flags, defines)
            common.run([out / "run"], env=env, log=out / "test.log", timeout=180)
            receipt["checks"][name] = (out / "test.log").read_text().splitlines()[-1]
            if name.startswith("mdu-"):
                negative = subprocess.run([str(out / "run"), "--inject"], env=env, cwd=ROOT,
                                          capture_output=True, text=True, timeout=60)
                (out / "negative.log").write_text(negative.stdout + negative.stderr)
                if negative.returncode == 0 or "independent MDU oracle mismatch" not in negative.stderr:
                    raise RuntimeError("MDU independent mutation was not rejected")
                receipt.setdefault("negative_component_controls", {})[name] = "PASS_REJECTED_MDU_MUTATION"
            if name.startswith("integer-early"):
                for flag, anchor in (("--inject-register-mismatch", "independent register oracle mismatch"),
                                     ("--inject-store-mismatch", "independent store intent data mismatch")):
                    negative = subprocess.run([str(out / "run"), flag], env=env, cwd=ROOT,
                                              capture_output=True, text=True, timeout=60)
                    (out / (flag.removeprefix("--") + ".log")).write_text(negative.stdout + negative.stderr)
                    if negative.returncode == 0 or anchor not in negative.stderr:
                        raise RuntimeError("early MEM independent mutation was not rejected")
                receipt.setdefault("negative_component_controls", {})[name] = "PASS_REJECTED_REGISTER_AND_STORE_MUTATIONS"
            print(receipt["checks"][name], flush=True)

        coremark = args.coremark_source.resolve()
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=coremark, text=True).strip()
        if revision != "1f483d5b8316753a742cbf5590caf5bd0a4e4777" or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=coremark, text=True):
            raise RuntimeError("CoreMark pinned source mismatch")
        payload = output / "payload"
        payload.mkdir()
        port = ROOT / "simulator/gsim/inorder/coremark_port"
        old_port = ROOT / "simulator/gsim/payloads/coremark_port"
        cflags = ["-O2", "-march=rv64im_zicsr_zifencei", "-mabi=lp64", "-mcmodel=medany", "-mno-relax",
                  "-msmall-data-limit=0", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-nostdlib",
                  "-nostartfiles", "-DITERATIONS=1", "-DPERFORMANCE_RUN=1", "-DTOTAL_DATA_SIZE=2000"]
        guest_sources = [coremark / f for f in ("core_list_join.c", "core_main.c", "core_matrix.c",
                                              "core_state.c", "core_util.c")]
        common.run(["riscv64-unknown-elf-gcc", *cflags, "-I" + str(port), "-I" + str(coremark),
                    "-T" + str(old_port / "link.ld"), old_port / "start.S", *guest_sources,
                    port / "core_portme.c", "-lgcc", "-o", payload / "coremark.elf"], log=payload / "build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload / "coremark.elf",
                    payload / "coremark.bin"], log=payload / "objcopy.log")
        common.run(["riscv64-unknown-elf-gcc", *cflags, "-T" + str(old_port / "link.ld"),
                    port / "cache_smoke.S", "-o", payload / "cache-smoke.elf"], log=payload / "smoke-build.log")
        common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", payload / "cache-smoke.elf",
                    payload / "cache-smoke.bin"], log=payload / "smoke-objcopy.log")
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", payload / "coremark.elf"], text=True)
        (payload / "symbols.txt").write_text(symbols)
        values = {line.split()[-1]: int(line.split()[0], 16) for line in symbols.splitlines() if len(line.split()) == 3}
        receipt["payload"] = {"coremark_revision": revision, "flags": cflags,
            "binary_sha256": sha(payload / "coremark.bin"), "bytes": (payload / "coremark.bin").stat().st_size,
            "symbols": {name: hex(values[name]) for name in ("coremark_validation_errors", "coremark_elapsed_ticks", "coremark_crcs")}}
        profiles = [("i1-no-cache-no-prediction", []), ("i1-cache-no-prediction", ["--icache=2048", "--dcache=2048"]),
                    ("i1-cache-prediction", ["--icache=2048", "--dcache=2048", "--predictor=64"]),
                    ("ooo-two-issue-matched-cache", [])]
        if args.inorder_throughput:
            base_flags = ["--icache=2048", "--dcache=2048", "--predictor=64"]
            profiles = [("i1-cache-prediction", base_flags),
                ("i1-early-memory", [*base_flags, "--early-memory-issue"]),
                ("i1-overlap-write", [*base_flags, "--overlap-write-lookup"]),
                ("i1-tiled-multiply", [*base_flags, "--dsp-tiled"]),
                ("i1-throughput-fast", [*base_flags, "--early-memory-issue", "--overlap-write-lookup"]),
                ("i1-throughput-combined", [*base_flags, "--early-memory-issue", "--overlap-write-lookup", "--dsp-tiled"])]
        for name, flags in profiles:
            ooo = name.startswith("ooo")
            out = model(name, "ooo.InorderMatchedOooCoremarkMain" if ooo else "inorder.FiveStageCachedMain",
                        "InorderMatchedOooCoremark" if ooo else "FiveStageCachedCore", "five_stage_coremark.cpp",
                        flags, ["-DDUT_OOO=1"] if ooo else [], module="IonSoC" if ooo else "OrbitalI1")
            common.run([out / "run", payload / "cache-smoke.bin", 0, 0, 0, 12],
                       env=env, log=out / "smoke.log", timeout=60)
            receipt["checks"][name + "-cached-cpu-smoke"] = (out / "smoke.log").read_text().strip()
            for delay in (1, 12):
                command = [out / "run", payload / "coremark.bin", hex(values["coremark_validation_errors"]),
                           hex(values["coremark_elapsed_ticks"]), hex(values["coremark_crcs"]), delay]
                common.run(command, env=env, log=out / f"test-l{delay}.log", timeout=240)
                line = (out / f"test-l{delay}.log").read_text().strip()
                if not line.startswith("MATCHED_COREMARK_PASS "):
                    raise RuntimeError("missing architectural/CRC benchmark gate")
                result = json.loads(line.split(" ", 1)[1])
                # The raw common driver initializes this counter to zero, but the OoO adapter
                # does not expose a branch-only event. Never present that placeholder as a measurement.
                result["mispredicts_observed"] = not ooo
                if ooo:
                    result["mispredicts"] = None
                result["roi_ipc"] = result["roi_instructions"] / result["roi_ticks"]
                result["short_iterations_per_mhz"] = 1e6 / result["roi_ticks"]
                receipt["benchmarks"][name + f"-l{delay}"] = result
                print(name + f"-l{delay}: " + json.dumps(result), flush=True)
            negative = subprocess.run(list(map(str, [*command, "--inject"])), cwd=ROOT, env=env,
                                      capture_output=True, text=True, timeout=60)
            (out / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode == 0 or "independent register oracle mismatch" not in negative.stderr:
                raise RuntimeError("CoreMark independent oracle mutation was not rejected")
            receipt.setdefault("negative_controls", {})[name] = "PASS_REJECTED_REGISTER_MUTATION"
        results = list(receipt["benchmarks"].values())
        if len({(r["trace_fnv64"], r["retired"], r["crcfinal"]) for r in results}) != 1:
            raise RuntimeError("identical image did not produce an identical retired PC/instruction stream and final CRC")
        if sources() != frozen:
            raise RuntimeError("source drift during acceptance")
        if sha(gsim) != receipt["toolchain"]["gsim_sha256"]:
            raise RuntimeError("GSIM binary drift during acceptance")
        if args.inorder_throughput:
            reference = json.loads(args.reference_receipt.read_text())
            if reference["status"] != "PASS_CACHE_PREDICTOR_MATCHED_SHORT_COREMARK_ONLY" or \
                    reference["payload"] != receipt["payload"] or reference["service_law"] != receipt["service_law"]:
                raise RuntimeError("frozen reference payload/service/qualification mismatch")
            for delay in (1, 12):
                key = f"i1-cache-prediction-l{delay}"
                for field in ("roi_ticks", "roi_instructions", "cycles", "retired", "trace_fnv64", "crcfinal"):
                    if receipt["benchmarks"][key][field] != reference["benchmarks"][key][field]:
                        raise RuntimeError("unchanged I1 baseline differs from frozen reference")
            receipt["frozen_reference"] = {"path": str(args.reference_receipt.resolve()),
                "sha256": sha(args.reference_receipt), "ooo_rerun": False,
                "benchmarks": {k: v for k, v in reference["benchmarks"].items() if k.startswith("ooo-")}}
            receipt["status"] = "PASS_I1_THROUGHPUT_BATCH_SHORT_ONLY"
        else:
            receipt["status"] = "PASS_CACHE_PREDICTOR_MATCHED_SHORT_COREMARK_ONLY"
    except BaseException as error:
        receipt["status"] = "FAILED"
        receipt["error"] = str(error)
        raise
    finally:
        receipt["artifacts_sha256"] = {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob("*"))
            if p.is_file() and p.name != "receipt.json"}
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}, indent=2))


if __name__ == "__main__":
    main()
