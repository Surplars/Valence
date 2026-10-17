#!/usr/bin/env python3
"""One batched I1 optional F/D + boot JTAG qualification. No synthesis or Linux simulation."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(ROOT / "simulator/gsim/inorder"))
from soc_acceptance import sources, sha
from ca_acceptance import FLAGS
from fp_payload import generate

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--timing-cuts", action="store_true", help="Qualify the optional fpga8 timing cuts")
    ap.add_argument("--fast-data-translation", action="store_true",
                    help="Qualify optional full-page PMP read/write proofs in existing D-TLB entries")
    ap.add_argument("--overlap-data-retirement", action="store_true",
                    help="Consume/replace one registered D reply; no additional owner or posted store")
    ap.add_argument("--read-only-data-retirement", action="store_true",
                    help="Restrict CPU retirement replacement to read-to-read; keep store boundaries")
    ap.add_argument("--reuse-models", type=Path,
                    help="Reuse ONLY artifact/tool/hash-identical models after fresh exact FIR elaboration; rerun tests")
    ap.add_argument("--performance-baseline", type=Path,
                    help="Require same flags and no ROI/Bare/Sv39 cycle regression versus a passing short receipt")
    args = ap.parse_args()
    if args.fast_data_translation and not args.timing_cuts:
        ap.error("fast data qualification requires timing-cut registered addresses")
    if args.overlap_data_retirement and not args.timing_cuts:
        ap.error("retirement overlap requires registered timing-cut memory owners")
    if args.read_only_data_retirement and not args.overlap_data_retirement:
        ap.error("read-only replacement requires the explicit retirement switch")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe fresh tag required")
    output = ROOT / "build/gsim" / ("i1-fd-jtag-" + args.tag)
    if output.exists():
        ap.error("refusing to overwrite evidence")
    output.mkdir(parents=True)
    def capture():
        result = sources()
        for folder in ("third_party/berkeley-hardfloat/src/main/scala", "src/main/resources/debug",
                       "src/main/resources/inorder"):
            for file in (ROOT / folder).rglob("*"):
                if file.is_file():
                    result[str(file.relative_to(ROOT))] = sha(file)
        for name in ("src/main/resources/inorder/bootrom.hex", "simulator/gsim/harness/floating_point_full_vectors.cpp",
                     "simulator/gsim/harness/tilelink_axi4_mixed.cpp",
                     "simulator/gsim/config/floating-point-dependencies.json", "simulator/gsim/run.py"):
            result[name] = sha(ROOT / name)
        return result
    frozen = capture()
    flags = [*FLAGS, "--pipeline=fpga8", "--f", "--d", "--soc-jtag"]
    cuts = ["--timing-cuts"] if args.timing_cuts else []
    data_cuts = ["--fast-data-translation"] if args.fast_data_translation else []
    retirement_cuts = ["--overlap-data-retirement"] if args.overlap_data_retirement else []
    if args.read_only_data_retirement:
        retirement_cuts += ["--read-only-data-retirement"]
    flags += cuts + data_cuts + retirement_cuts
    receipt = {"status": "RUNNING", "source_sha256": frozen, "checks": {}, "soc_flags": flags,
        "pipeline": ["IF", "ID", "RF", "EX", "ADDR", "MEM", "CMP", "WB"], "pipeline_profile": "fpga8",
        "isa": "rv64imafdc_zicsr_zifencei_svade", "xlen": 64, "cpu_hz": 100000000, "uart_baud": 460800,
        "jtag_chain": 2, "jtag_default_off": True, "f_default_off": True, "d_default_off": True,
        "initial_fp_xlen_scope": "RV64 only; RV32 floating requests rejected at elaboration",
        "fp_issue": "conservative serial FP: older drain, one numerical owner, WB-only FPR/fflags/FS changes",
        "fp_storage": "three synchronous 1R1W RAM replicas, FLEN32 for F / FLEN64 for FD, no payload reset",
        "fp_resources": "shared per-format rounders and multiply/fused significand product",
        "physical_qualified": False, "linux_boot_qualified": False, "complete_debug_implemented": False,
        "ooo_modified": False, "atomic_contract": "single hart exclusive runtime writer; no live DMA",
        "fast_data_translation": args.fast_data_translation,
        "overlap_data_retirement": args.overlap_data_retirement,
        "read_only_data_retirement": args.read_only_data_retirement,
        "data_owner_contract": "one blocking D-cache owner; unchanged 4-entry TLB / 2 DDR slots / 1 write credit"}
    performance_prior = None
    if args.performance_baseline:
        performance_prior = json.loads(args.performance_baseline.read_text())
        if (performance_prior["status"] != "PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY" or
                [f for f in performance_prior["soc_flags"] if f not in
                 ("--overlap-data-retirement", "--read-only-data-retirement")] !=
                [f for f in flags if f not in ("--overlap-data-retirement", "--read-only-data-retirement")]):
            ap.error("matched passing timing-cut configuration required for performance baseline")
        receipt["performance_baseline"] = {"path": str(args.performance_baseline.resolve()),
                                          "sha256": sha(args.performance_baseline)}
    def save():
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        dependency = json.loads((ROOT / "simulator/gsim/config/floating-point-dependencies.json").read_text())
        for name, digest in dependency["local_sources_sha256"].items():
            if sha(ROOT / "third_party/berkeley-hardfloat/src/main/scala" / name) != digest:
                raise RuntimeError("HardFloat source drift: " + name)
        archive = ROOT / ("build/dependencies/softfloat-" + dependency["softfloat"]["revision"] + ".zip")
        if sha(archive) != dependency["softfloat"]["archive_sha256"]:
            raise RuntimeError("independent SoftFloat archive hash mismatch")
        prefix = "berkeley-softfloat-3-" + dependency["softfloat"]["revision"] + "/"
        reference = output / "softfloat"
        with ZipFile(archive) as zipped:
            for entry in zipped.infolist():
                if entry.is_dir():
                    continue
                if not entry.filename.startswith(prefix):
                    raise RuntimeError("unexpected reference prefix")
                relative = entry.filename[len(prefix):]
                target = (reference / relative).resolve()
                if not target.is_relative_to(reference.resolve()):
                    raise RuntimeError("unsafe reference member")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zipped.read(entry))
        receipt["softfloat"] = {"revision": dependency["softfloat"]["revision"], "archive_sha256": sha(archive),
            "files_sha256": {str(p.relative_to(reference)): sha(p) for p in reference.rglob("*") if p.is_file()}}
        ref_build = reference / "build/Linux-x86_64-GCC"
        common.run(["make", "-j4"], cwd=ref_build, log=output / "softfloat-build.log")
        common.run(["g++", "-std=c++20", "-O2", "-I" + str(reference / "source/include"),
                    ROOT / "simulator/gsim/harness/floating_point_full_vectors.cpp", ref_build / "softfloat.a",
                    "-o", output / "oracle"], log=output / "oracle-build.log")
        common.run([output / "oracle", output / "vectors.txt"], log=output / "oracle-test.log")
        receipt["checks"]["softfloat-known-answers"] = (output / "oracle-test.log").read_text().strip()
        receipt["vectors_sha256"] = sha(output / "vectors.txt")
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        prior = None
        if args.reuse_models:
            prior = json.loads(args.reuse_models.read_text())
            if prior["tools"] != receipt["tools"]:
                raise RuntimeError("reused model tool mismatch")
            receipt["reuse_models_receipt"] = {"path": str(args.reuse_models.resolve()),
                                              "sha256": sha(args.reuse_models)}
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")
        options = ["-std=c++20", "-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        def model(name, entry, top, choices=(), width=64):
            print("BUILD", name, flush=True)
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder." + entry, out, width, *choices],
                       log=out / "elaborate.log")
            key = name + "/" + top + ".fir"
            previous = args.reuse_models.parent / name if prior else None
            previous_cpp = sorted(previous.glob(top + "[0-9]*.cpp")) if previous else []
            complete_model = bool(previous and (previous / (top + ".h")).is_file() and previous_cpp and
                                  all(p.with_suffix(".o").is_file() for p in previous_cpp))
            identical = bool(prior and complete_model and
                             prior["artifact_sha256"].get(key) == sha(out / (top + ".fir")))
            original_input = out / (top + ".fir")
            gsim_input = original_input
            if original_input.stat().st_size % 4096 == 0:
                # Pinned GSIM readFile mmap(size+1) writes NUL at EOF. A
                # page-aligned file gives SIGBUS there (before FIR parsing).
                # Preserve original CHIRRTL exactly for source/export/reuse;
                # record a separate parser input with ONE whitespace byte.
                # No simulator, expression, test stimulus or oracle is changed.
                gsim_input = out / (top + ".gsim-input.fir")
                gsim_input.write_bytes(original_input.read_bytes() + b"\n")
                receipt.setdefault("gsim_input_padding", {})[name] = {
                    "reason": "PINNED_GSIM_READFILE_PAGE_ALIGNED_EOF_SIGBUS",
                    "original_bytes": original_input.stat().st_size,
                    "original_sha256": sha(original_input), "padding": "one newline byte",
                    "parser_input": str(gsim_input.relative_to(output)), "parser_sha256": sha(gsim_input)}
            if identical:
                for path in previous.iterdir():
                    if path.is_file() and path.suffix in (".h", ".cpp", ".o"):
                        key = name + "/" + path.name
                        if sha(path) != prior["artifact_sha256"].get(key):
                            raise RuntimeError("reused model artifact drift: " + key)
                        shutil.copy2(path, out / path.name)
                receipt.setdefault("reused_models", {})[name] = "EXACT_FIR_TOOL_ARTIFACT_IDENTITY; TESTS_RERUN"
            else:
                common.run([gsim, "--threads=1", f"--dir={out}", gsim_input],
                           log=out / "generate.log")
            objects = []
            for source in sorted(out.glob(top + "[0-9]*.cpp")):
                obj = source.with_suffix(".o")
                if not obj.is_file():
                    common.run([cxx, *options, "-I" + str(out), "-c", source, "-o", obj],
                               log=obj.with_suffix(".log"), timeout=900)
                objects.append(obj)
            def driver(name, file, defines=()):
                binary = out / name
                common.run([cxx, *options, f"-DDUT_XLEN={width}", *defines, "-I" + str(out), *objects,
                            ROOT / "simulator/gsim/harness" / file, "-o", binary],
                           log=out / (name + "-compile.log"), timeout=900)
                return binary
            return out, driver
        def check(name, binary, argv=(), negative=None, timeout=240):
            print("RUN", name, flush=True)
            log = binary.parent / (name + ".log")
            common.run([binary, *argv], env=env, log=log, timeout=timeout)
            receipt["checks"][name] = log.read_text().strip()
            print(receipt["checks"][name], flush=True)
            save()
            if negative:
                flag, message = negative
                bad = subprocess.run([str(binary), *map(str, argv), flag], env=env,
                                     capture_output=True, text=True, timeout=timeout, cwd=ROOT)
                log.with_name(name + "-negative.log").write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or message not in bad.stdout + bad.stderr:
                    raise RuntimeError("independent negative not rejected: " + name)
                receipt["checks"][name + "-negative"] = "PASS_REJECTED_INDEPENDENT_MUTATION"
                save()
        if args.timing_cuts:
            for width in (32, 64):
                for enabled in (False, True):
                    name = "timing-ex-datapath-" + str(width) + "-" + str(int(enabled))
                    out, build = model(name, "FiveStageExecuteDatapathMain", "I1ExecuteDatapathFixture",
                        ["--pipeline=fpga8", *(["--timing-cuts"] if enabled else [])], width)
                    check(name, build("run", "five_stage_execute_datapath.cpp",
                        ["-DDUT_TIMING_CUTS=" + str(int(enabled))]),
                        negative=("--wrong-result", "independent EX operand/ALU/result oracle"))
            for capacity, window, fast in ((4, "aligned", True), (4, "shifted", True),
                    (4, "board", True), (2, "aligned", True), (8, "aligned", True),
                    (16, "aligned", True), (4, "aligned", False)):
                name = "timing-if-pma-" + str(capacity) + "-" + window + "-" + str(int(fast))
                choices = ["--instruction", "--timing-cuts", "--tlb=" + str(capacity),
                    "--window=" + window, *(["--no-fast-instruction"] if not fast else [])]
                out, build = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness", choices)
                definitions = ["-DI1_INSTRUCTION_TRANSLATION=1", "-DI1_INSTRUCTION_PMA=1"]
                if window == "shifted":
                    definitions += ["-DI1_PMA_SHIFTED=1"]
                if window == "board":
                    definitions += ["-DI1_PMA_BOARD=1"]
                check(name, build("run", "five_stage_translation.cpp", definitions),
                    negative=("--wrong-pma", "independent instruction PMA/noAllocate oracle"))
            for width, capacity in ((32, 512), (64, 512), (64, 0)):
                name = "timing-read-pma-cache-" + str(width) + "-" + str(capacity)
                out, build = model(name, "FiveStageCacheMain", "FiveStageWordCache",
                    ["--pipeline=fpga8", "--timing-cuts", "--flow-hits", "--read-pma",
                     "--dcache=" + str(capacity), "--overlap-write-lookup"], width)
                binary = build("run", "five_stage_cache_read_pma.cpp", ["-DCACHE_BYTES=" + str(capacity)])
                check(name, binary,
                    negative=("--wrong-hint", "trusted IF cacheability contradicts physical/noAllocate policy"))
                bad = subprocess.run([str(binary), "--wrong-data"], env=env,
                    capture_output=True, text=True, timeout=60, cwd=ROOT)
                (out / "read-pma-wrong-data.log").write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or "independent read-only PMA byte oracle" not in bad.stdout + bad.stderr:
                    raise RuntimeError("independent read PMA byte mutation was not rejected")
                receipt["checks"][name + "-data-negative"] = "PASS_REJECTED_INDEPENDENT_BYTE_MUTATION"
                save()
            for enabled in (False, True):
                name = "timing-data-auth-" + ("on" if enabled else "off")
                out, build = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                    ["--timing-cuts", "--atomic", *(["--fast-data-translation"] if enabled else [])])
                check(name, build("run", "five_stage_translation.cpp", ["-DI1_RETIREMENT_OVERLAP=0"]),
                      negative=("--wrong-page", "independent Sv39/PMP/page-vs-access fault oracle"))
                receipt.setdefault("data_auth_benchmarks", {})[name] = [
                    json.loads(line.split(" ", 1)[1]) for line in receipt["checks"][name].splitlines()
                    if line.startswith("I1_DATA_AUTH_PERF ")]
                if len(receipt["data_auth_benchmarks"][name]) != 2:
                    raise RuntimeError("missing matched Bare/Sv39 alternating read/write proof measurements")
                save()
                if args.overlap_data_retirement:
                    name = "timing-data-retirement-" + ("fast" if enabled else "slow")
                    out, build = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                        ["--timing-cuts", "--atomic", "--overlap-data-retirement",
                         *(["--fast-data-translation"] if enabled else [])])
                    check(name, build("run", "five_stage_translation.cpp", ["-DI1_RETIREMENT_OVERLAP=1"]),
                          negative=("--wrong-retirement", "independent replacement owner/data/error oracle"))
            for width in (32, 64):
                name = "timing-window-" + str(width)
                out, build = model(name, "I1AddressWindowMain", "I1AddressWindowFixture", width=width)
                check(name, build("run", "five_stage_address_window.cpp"),
                      negative=("--wrong-window", "independent byte-window bounds oracle"))
            out, build = model("timing-predictor-c", "FiveStagePredictorMain", "FiveStageBranchPredictor",
                               ["--c", "--pipeline=fpga8", "--timing-cuts", "--predictor=128"])
            check("timing-predictor-c", build("run", "five_stage_predictor_c.cpp"),
                  negative=("--wrong-target", "independent C folded BTB full-PC/length/target oracle"))
            for width in (32, 64):
                name = "timing-parcels-" + str(width)
                out, build = model(name, "FiveStageFetchAlignerMain", "FiveStageFetchAligner",
                                   ["--timing-cuts"], width)
                check(name, build("run", "five_stage_fetch_aligner.cpp", ["-DI1_TIMING_CUTS=1"]),
                      negative=("--wrong-parcel", "independent C parcel byte oracle"))
            for width, capacity, flow in ((32, 512, False), (64, 512, False),
                                          (64, 512, True), (64, 0, False)):
                name = "timing-cache-" + str(width) + "-" + str(capacity) + "-" + str(int(flow))
                out, build = model(name, "FiveStageCacheMain", "FiveStageWordCache",
                    ["--pipeline=fpga8", "--timing-cuts", "--dcache=" + str(capacity),
                     "--overlap-write-lookup", *(["--flow-hits"] if flow else [])], width)
                check(name, build("run", "five_stage_cache.cpp", ["-DCACHE_BYTES=" + str(capacity)]))
            for registers in (False, True):
                name = "timing-route-" + str(int(registers))
                out, build = model(name, "FiveStageRouteMain", "FiveStageTileLinkRoute",
                                   ["--timing-cuts", *(["--registers"] if registers else [])])
                binary = build("run", "five_stage_route.cpp",
                               ["-DI1_TIMING_CUTS=1", "-DALLOW_REGISTERS=" + str(int(registers))])
                check(name, binary, negative=("--wrong-route", "independent route destination oracle"))
            out, build = model("timing-axi", "I1BusTimingMain", "TileLinkAxi4Bridge")
            check("timing-axi", build("run", "tilelink_axi4_mixed.cpp", ["-DMAX_BURST_BEATS=8"]),
                  negative=("--inject-data", "independent TL data oracle mismatch"))
            binary = build("capture", "five_stage_axi_capture.cpp")
            check("timing-axi-capture", binary,
                  negative=("--inject", "independent R capture byte oracle"))
            bad = subprocess.run([str(binary), "--bad-id"], env=env, capture_output=True, text=True, timeout=60)
            (out / "capture-bad-id.log").write_text(bad.stdout + bad.stderr)
            if bad.returncode == 0 or "AXI R response has no live read owner" not in bad.stdout + bad.stderr:
                raise RuntimeError("zero-delay unowned R was not rejected")
            receipt["checks"]["timing-axi-capture-bad-id"] = "PASS_REJECTED_UNOWNED_AXI_ID"
        for profile in ("f", "fd"):
            out, build = model("numerical-" + profile, "I1FloatingPointMain", "I1FloatingPointGsim",
                               [*(["--d"] if profile == "fd" else []), *cuts])
            if profile == "f":
                fir = (out / "I1FloatingPointGsim.fir").read_text()
                if any("module I1FloatingPoint" + kind + "D" in fir for kind in
                       ("SharedArithmetic", "RoundCuts", "RawAdd", "RawAddCuts", "RawMultiplyFused",
                        "RawMultiplyFusedCuts", "RawDivSqrt", "Misc")):
                    raise RuntimeError("D numerical hardware survives F-only elaboration")
                if "module I1FloatingPointNarrowRoundCuts" in fir:
                    raise RuntimeError("D-to-S narrow rounder survives F-only elaboration")
            binary = build("run", "five_stage_fp_numerical.cpp",
                           ["-DI1_TIMING_CUTS=" + str(int(args.timing_cuts))])
            check("numerical-" + profile, binary, [output / "vectors.txt", profile],
                  ("--inject-mismatch", "FP full mismatch: SoftFloat value"))
        out, build = model("compressed-fd", "I1FloatingPointCompressedMain", "I1FloatingPointCompressedGsim")
        check("compressed-fd", build("run", "five_stage_fp_compressed.cpp"))
        here = ROOT / "simulator/gsim/inorder"
        def payload(name, source, linker="fp_link.ld", definitions=()):
            common.run(["riscv64-unknown-elf-gcc", "-march=rv64imafdc_zicsr_zifencei", "-mabi=lp64",
                        "-mcmodel=medany", "-mno-relax", "-nostdlib", "-nostartfiles", "-Wl,--no-relax",
                        *definitions, "-T" + str(here / linker), source, "-o", output / (name + ".elf")],
                       log=output / (name + "-build.log"))
            common.run(["riscv64-unknown-elf-objcopy", "-O", "binary", output / (name + ".elf"),
                        output / (name + ".bin")], log=output / (name + "-objcopy.log"))
            return output / (name + ".bin")
        corpus = {}
        context = {}
        for profile in ("f", "fd"):
            generated = output / ("corpus-" + profile + ".S")
            details = generate(output / "vectors.txt", generated, profile == "fd")
            receipt.setdefault("cpu_corpus", {})[profile] = details
            corpus[profile] = payload("corpus-" + profile, generated)
            context[profile] = payload("context-" + profile, here / "fp_context.S",
                                      definitions=["-DHAVE_D=" + str(int(profile == "fd"))])
        scalar = payload("scalar-privilege", here / "privilege_smoke.S", "privilege_link.ld")
        stream = payload("scalar-stream", here / "privilege_throughput.S", "soc_link.ld")
        ca = payload("ca-smoke", here / "ca_smoke.S", "soc_link.ld")
        for pipeline in (("fpga8",) if args.timing_cuts else ("compact5", "balanced7", "fpga8")):
            out, build = model("soc-fd-" + pipeline, "FiveStageSocGsimMain", "FiveStageSoc",
                               [*FLAGS, "--f", "--d", "--pipeline=" + pipeline, *cuts, *data_cuts, *retirement_cuts])
            binary = build("floating", "five_stage_fp_soc.cpp", ["-DI1_HAS_ROM=1"])
            count = receipt["cpu_corpus"]["fd"]["cases"]
            check(pipeline + "-fd-corpus", binary, [corpus["fd"], count],
                  ("--wrong-result", "independent FP actual CPU result/flags/context ledger oracle"), timeout=360)
            check(pipeline + "-fd-context-memory", binary, [context["fd"], 32, "--faults"])
            if pipeline == "fpga8":
                binary = build("ca", "five_stage_ca_soc.cpp", ["-DI1_HAS_ROM=1"])
                check("fd-ca-cross-page", binary, [ca],
                      negative=("--wrong-result", "independent C/A completion/alias/boundary oracle"))
                check("fd-ca-page-end", binary, [ca, "--compressed-boundary"])
                binary = build("privilege", "five_stage_privilege_soc.cpp", ["-DI1_HAS_ROM=1"])
                check("fd-scalar-privilege", binary, [scalar])
                check("fd-bare-stream", binary, [stream, "--bare-throughput"])
                check("fd-sv39-stream", binary, [stream, "--sv39-throughput"])
        if args.fast_data_translation:
            out, build = model("soc-fd-auth-off", "FiveStageSocGsimMain", "FiveStageSoc",
                [*FLAGS, "--f", "--d", "--pipeline=fpga8", *cuts, *retirement_cuts])
            binary = build("privilege", "five_stage_privilege_soc.cpp", ["-DI1_HAS_ROM=1"])
            check("fd-auth-off-bare-stream", binary, [stream, "--bare-throughput"])
            check("fd-auth-off-sv39-stream", binary, [stream, "--sv39-throughput"])
        if args.overlap_data_retirement:
            out, build = model("soc-fd-retirement-off", "FiveStageSocGsimMain", "FiveStageSoc",
                [*FLAGS, "--f", "--d", "--pipeline=fpga8", *cuts, *data_cuts])
            binary = build("privilege", "five_stage_privilege_soc.cpp", ["-DI1_HAS_ROM=1"])
            check("fd-retirement-off-bare-stream", binary, [stream, "--bare-throughput"])
            check("fd-retirement-off-sv39-stream", binary, [stream, "--sv39-throughput"])
        out, build = model("soc-f-only", "FiveStageSocGsimMain", "FiveStageSoc",
                           [*FLAGS, "--f", "--pipeline=fpga8", *cuts, *data_cuts, *retirement_cuts])
        binary = build("floating", "five_stage_fp_soc.cpp", ["-DI1_HAS_ROM=1"])
        check("f-only-corpus", binary, [corpus["f"], receipt["cpu_corpus"]["f"]["cases"]])
        check("f-only-context-d-illegal", binary, [context["f"], 32, "--faults"])
        out, build = model("soc-fd-jtag", "FiveStageSocGsimMain", "FiveStageSoc", flags)
        binary = build("floating", "five_stage_fp_soc.cpp", ["-DI1_HAS_ROM=1"])
        check("fd-jtag-download-context", binary, [context["fd"], 32, "--jtag", "--faults"],
              ("--wrong-result", "independent FP actual CPU result/flags/context ledger oracle"))
        check("fd-jtag-crc-retry-context", binary, [context["fd"], 32, "--retry", "--faults"])
        for width in (32, 64):
            out, build = model("default-off" + str(width), "FiveStageMain", "FiveStageCore",
                               ["--pipeline=fpga8", "--dsp-tiled", "--early-memory-issue", *cuts], width)
            fir = (out / "FiveStageCore.fir").read_text()
            if any("module " + name in fir for name in ("I1FloatingPointExecute", "SynchronousFloatingRegisterFile")):
                raise RuntimeError("default-off floating hardware did not disappear")
            check("default-off-integer" + str(width), build("run", "five_stage_early_memory.cpp",
                  ["-DDUT_PIPELINE_STAGES=8", "-DI1_TIMING_CUTS=" + str(int(args.timing_cuts))]))
            if args.timing_cuts:
                match = re.search(r"I1_LATE_RECOVERY_PASS overlap_cycles=(\d+) .+", receipt["checks"]["default-off-integer" + str(width)])
                if not match or int(match[1]) == 0:
                    raise RuntimeError("missing late redirect/MDU/older-memory proof")
                receipt["checks"]["timing-late-recovery" + str(width)] = match[0]
                save()
        if args.timing_cuts:
            out, build = model("default-off-no-m64", "FiveStageMain", "FiveStageCore",
                ["--no-m", "--pipeline=fpga8", "--early-memory-issue", *cuts])
            fir = (out / "FiveStageCore.fir").read_text()
            if any("module " + name in fir for name in
                    ("FiveStageMulDiv", "I1FloatingPointExecute", "SynchronousFloatingRegisterFile")):
                raise RuntimeError("M/F/D disabled hardware did not disappear")
            check("default-off-no-m64", build("run", "five_stage_early_memory.cpp",
                ["-DDUT_PIPELINE_STAGES=8", "-DI1_TIMING_CUTS=1", "-DDUT_HAS_M=0"]))
        shell = output / "shell-user2"
        shell.mkdir()
        common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder.FiveStageFpgaShellMain",
                    shell, 64, *flags, "--soc-user-chain=2"], log=shell / "elaborate.log")
        fir = (shell / "FiveStageFpgaShell.fir").read_text()
        transport_name = "ValenceI1BscanDebugPort" if args.timing_cuts else "ValenceBscanDebugPort"
        if transport_name not in fir or "JtagRamLoader" not in fir:
            raise RuntimeError("shared JTAG shell was not connected")
        receipt["checks"]["shell-user2"] = "PASS_ELABORATION_ONLY_NOT_TAP_CDC_BOARD_QUALIFICATION"
        if args.timing_cuts:
            baseline = ROOT / "build/gsim/inorder-pipeline-20261014-r3"
            old_receipt = json.loads((baseline / "receipt.json").read_text())
            symbols = (baseline / "coremark-symbols.txt").read_text()
            values = {line.split()[-1]: int(line.split()[0], 16) for line in symbols.splitlines()
                      if len(line.split()) == 3}
            if sha(baseline / "coremark.bin") != old_receipt["artifact_sha256"]["coremark.bin"]:
                raise RuntimeError("same-binary CoreMark baseline drift")
            out, build = model("timing-coremark", "FiveStageCachedMain", "FiveStageCachedCore",
                               ["--pipeline=fpga8", "--timing-cuts", "--dsp-tiled", "--early-memory-issue",
                                "--overlap-write-lookup", "--icache=2048", "--dcache=2048", "--predictor=128"])
            binary = build("run", "five_stage_coremark.cpp")
            for delay in (1, 12):
                name = "timing-O3-l" + str(delay)
                check(name, binary, [baseline / "coremark.bin", hex(values["coremark_validation_errors"]),
                      hex(values["coremark_elapsed_ticks"]), hex(values["coremark_crcs"]), delay],
                      negative=("--inject", "independent register oracle mismatch") if delay == 12 else None)
                measured = json.loads(receipt["checks"][name].split(" ", 1)[1])
                old = old_receipt["benchmarks"]["fpga8-O3-l" + str(delay)]
                for field in ("trace_fnv64", "retired", "crcfinal", "roi_instructions"):
                    if measured[field] != old[field]:
                        raise RuntimeError("same-binary architectural stream mismatch: " + field)
                receipt.setdefault("benchmarks", {})[name] = measured
        if args.overlap_data_retirement:
            paired = {}
            for mode in ("bare", "sv39"):
                on = json.loads(receipt["checks"]["fd-" + mode + "-stream"].split(" ", 1)[1])
                off = json.loads(receipt["checks"]["fd-retirement-off-" + mode + "-stream"].split(" ", 1)[1])
                for field in ("bytes", "axi_reads", "axi_writes"):
                    if on[field] != off[field]:
                        raise RuntimeError("retirement pair work/traffic mismatch: " + mode + "/" + field)
                for field in ("read_ticks", "write_ticks", "copy_ticks"):
                    if on[field] > off[field]:
                        raise RuntimeError("retirement pair throughput regression: " + mode + "/" + field)
                paired[mode] = {field: {"off": off[field], "on": on[field]}
                    for field in ("read_ticks", "write_ticks", "copy_ticks")}
            receipt["retirement_paired_performance"] = paired
        if performance_prior:
            comparisons = {}
            for name, measured in receipt["benchmarks"].items():
                previous = performance_prior["benchmarks"][name]
                for field in ("trace_fnv64", "retired", "crcfinal", "roi_instructions"):
                    if measured[field] != previous[field]:
                        raise RuntimeError("prior same-binary stream mismatch: " + name + "/" + field)
                if measured["roi_ticks"] > previous["roi_ticks"]:
                    raise RuntimeError("same-frequency O3 ROI regression: " + name)
                comparisons[name] = {"before": previous["roi_ticks"], "after": measured["roi_ticks"]}
            for name in ("fd-bare-stream", "fd-sv39-stream",
                         "fd-auth-off-bare-stream", "fd-auth-off-sv39-stream"):
                measured = json.loads(receipt["checks"][name].split(" ", 1)[1])
                previous = json.loads(performance_prior["checks"][name].split(" ", 1)[1])
                for field in ("bytes", "axi_reads", "axi_writes"):
                    if measured[field] != previous[field]:
                        raise RuntimeError("matched stream work/traffic differs: " + name + "/" + field)
                for field in ("read_ticks", "write_ticks", "copy_ticks"):
                    if measured[field] > previous[field]:
                        raise RuntimeError("same-frequency stream regression: " + name + "/" + field)
                comparisons[name] = {field: {"before": previous[field], "after": measured[field]}
                    for field in ("read_ticks", "write_ticks", "copy_ticks")}
            receipt["matched_performance"] = comparisons
        if capture() != frozen:
            raise RuntimeError("source drift during F/D JTAG acceptance")
        receipt["timing_cuts"] = args.timing_cuts
        receipt["instruction_pma"] = ("existing proof rows hold exact physical page/PMA; "
            "parallel VPN proof match for TLB2/4/8, indexed TLB16+; "
            "no new owner, no added fetch hit cycle; private read-only cache boundary"
            if args.timing_cuts else "DISABLED")
        receipt["execution_datapath"] = ("folded one-hot ALU operands, shared SRL/SRA, parallel word packing, "
            "ID result mask, CMP-to-WB recovery class, admitted-owner-only payload; no extra stage or cycle"
            if args.timing_cuts else "DISABLED")
        receipt["active_recovery"] = ("WB-only active-stage recovery: IRQ commits only after backend is empty; "
            "real IRQ trap/frontend redirect/reservation clear retained; no new stage or bubble"
            if args.timing_cuts else "DISABLED")
        receipt["batch11_control"] = ("ID numerical legality/rounding/source-presence capture; "
            "owner-first forwarding/hazards; owner-local MDU/FP completion; exact RF/ID/IF lookahead; "
            "direction-shared/narrow-word barrel, shared comparator, ALU result mask folded before packing"
            if args.timing_cuts else "DISABLED")
        receipt["status"] = ("PASS_I1_PARAMETERIZED_FD_JTAG_TIMING_CUTS_SHORT_ONLY" if args.timing_cuts
                             else "PASS_I1_PARAMETERIZED_FD_JTAG_SHORT_ONLY")
    except BaseException as error:
        receipt["status"] = "FAIL"; receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p) for p in output.rglob("*")
                                      if p.is_file() and p.name != "receipt.json"}
        save()
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)
if __name__ == "__main__":
    main()
