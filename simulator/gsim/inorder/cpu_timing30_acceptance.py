#!/usr/bin/env python3
"""Affected I1 batch30 checks only; exact old payloads, no full suite or Vivado."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import RLock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(HERE))
from coherent_network_acceptance import qualification_sources
from soc_acceptance import sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--reference", type=Path, default=ROOT /
        "build/gsim/i1-coherent-network-timing25-20261016-r4/receipt.json")
    ap.add_argument("--reuse-compiles", type=Path,
        help="exact-hash artifacts only, never reuse PASS status or skip execution")
    ap.add_argument("--baseline", type=Path, default=ROOT /
        "build/gsim/i1-cpu-timing29-20261016-r1/receipt.json")
    ap.add_argument("--retirement-overlap", choices=("none", "reads", "all"), default="all",
        help="explicit measured candidate only; reusable hardware defaults remain OFF")
    ap.add_argument("--direct-fast-data-issue", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("i1-cpu-timing30-" + args.tag)
    output.mkdir(exist_ok=False)
    frozen = qualification_sources()
    prior = json.loads(args.reference.read_text())
    baseline = json.loads(args.baseline.read_text())
    if baseline["status"] != "PASS_I1_CPU_TIMING29_AFFECTED_SHORT_ONLY":
        raise RuntimeError("exact previous affected-short PASS performance baseline required")
    stopped = json.loads((args.reference.parent / "stop-summary.json").read_text())
    if not stopped["target_cpu_configuration_pass"] or stopped["raw_receipt_sha256"] != sha(args.reference):
        raise RuntimeError("exact user-stopped, target-passed reference required")
    selected_flags = list(prior["cpu_flags"]["cpu-coherent"])
    if args.retirement_overlap != "none":
        selected_flags += ["--overlap-data-retirement"]
    if args.retirement_overlap == "reads":
        selected_flags += ["--read-only-data-retirement"]
    if args.direct_fast_data_issue:
        selected_flags += ["--direct-fast-data-issue"]
    receipt = {"status": "RUNNING", "checks": {}, "source_sha256": frozen,
        "reference": str(args.reference), "reference_sha256": sha(args.reference),
        "reference_scope": "target subset passed; original full receipt remains FAIL(-15)",
        "baseline": str(args.baseline), "baseline_sha256": sha(args.baseline),
        "cpu_flags": {"cpu-coherent": selected_flags},
        "retirement_overlap": args.retirement_overlap,
        "direct_fast_data_issue": args.direct_fast_data_issue,
        "stream_execution_workers": 2,
        "cache_bytes_each": 32768, "cpu_target_hz": 300000000,
        "physical_qualified": False, "board_qualified": False, "formal_coremark": False,
        "scope": "affected indexed-IT-proof/PMP-fragment/DT-fault-payload/native-carry-select/FP-compare/onehot-maintenance checks; not full prior212 suite"}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    result_lock = RLock()
    def save():
        with result_lock:
            (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    save()
    try:
        gs = Path("/home/openion/Valence/simulator/build/gsim-src")
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=gs, text=True).strip()
        if revision != common.LOCK["revision"] or subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=gs, text=True):
            raise RuntimeError("GSIM pin/cleanliness mismatch")
        gsim = gs / "build/gsim/gsim"
        cxx, version = common.compiler()
        receipt["tools"] = {"gsim_revision": revision, "gsim_sha256": sha(gsim), "cxx": version}
        compiled = json.loads(args.reuse_compiles.read_text()) if args.reuse_compiles else None
        if compiled and compiled["tools"] != receipt["tools"]:
            raise RuntimeError("compiled-model tool mismatch")
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
                   log=output / "scala.log")

        def payload(name):
            p = args.reference.parent / name
            if sha(p) != prior["artifact_sha256"][name]:
                raise RuntimeError("old payload drift: " + name)
            receipt.setdefault("payload_sha256", {})[name] = sha(p)
            return p

        def link(out, top, driver, binary="run", defines=(), width=64):
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-DDUT_XLEN=" + str(width), "-I" + str(out),
                *defines, *sorted(out.glob(top + "[0-9]*.o")),
                ROOT / "simulator/gsim/harness" / driver, "-o", out / binary],
                log=out / (binary + "-link.log"), timeout=900)

        def model(name, entry, top, driver, flags=(), defines=(), width=64):
            print("BUILD", name, flush=True)
            out = output / name
            out.mkdir()
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder." + entry,
                out, width, *flags], log=out / "elaborate.log")
            fir = out / (top + ".fir")
            previous = args.reuse_compiles.parent / name if compiled else None
            if previous and (previous / fir.name).is_file() and sha(fir) == \
                    compiled["artifact_sha256"].get(name + "/" + fir.name):
                import shutil
                artifacts = [p for p in previous.iterdir() if p.suffix in (".o", ".h", ".cpp")]
                if not any(p.suffix == ".o" for p in artifacts):
                    raise RuntimeError("missing exact old compilation")
                for p in artifacts:
                    if sha(p) != compiled["artifact_sha256"].get(name + "/" + p.name):
                        raise RuntimeError("compiled artifact drift: " + p.name)
                    shutil.copy2(p, out / p.name)
                receipt.setdefault("exact_compilation_reuse", {})[name] = {
                    "receipt": str(args.reuse_compiles), "receipt_sha256": sha(args.reuse_compiles),
                    "fresh_fir_sha256": sha(fir), "checks_reused": False}
                link(out, top, driver, defines=defines, width=width)
                return out
            parser = fir
            # Pinned GSIM accepts the explicit old/new/undefined token, but
            # its CHIRRTL grammar predates Chisel's comma before that token.
            # Preserve "old" semantics; normalize ONLY this delimiter for
            # our named cache SRAMs, never delete the read-under-write mode.
            original = fir.read_text()
            normalized, old_delimiters = re.subn(
                r"(?m)^(\s*smem dataWays_\S+ : [^\n,]+), old(?= @\[[^\n]*$)",
                r"\1 old", original)
            if old_delimiters or fir.stat().st_size % 4096 == 0:
                parser = out / (top + ".gsim-input.fir")
                parser.write_text(normalized + "\n")
                if old_delimiters:
                    receipt.setdefault("fir_parser_compat", {})[name] = {
                        "only_explicit_old_separator": old_delimiters,
                        "read_under_write": "old",
                        "original_fir_sha256": sha(fir),
                        "parser_fir_sha256": sha(parser)}
            common.run([gsim, "--threads=1", "--dir=" + str(out), parser],
                log=out / "generate.log", timeout=900)
            def compile_one(source):
                common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all", "-I" + str(out), "-c", source,
                    "-o", source.with_suffix(".o")], log=out / (source.stem + "-compile.log"), timeout=900)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(compile_one, sorted(out.glob(top + "[0-9]*.cpp"))))
            link(out, top, driver, defines=defines, width=width)
            return out

        def check(name, out, argv=(), negative=None, binary="run"):
            common.run([out / binary, *argv], env=env, log=out / (name + ".log"), timeout=300)
            text = (out / (name + ".log")).read_text().strip()
            with result_lock:
                receipt["checks"][name] = text
            print(text, flush=True)
            if negative:
                bad_args, expected = negative
                bad = subprocess.run([str(out / binary), *map(str, bad_args)], env=env,
                    capture_output=True, text=True, timeout=300)
                (out / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or expected not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control did not reject: " + name)
                with result_lock:
                    receipt["checks"][name + "-negative"] = "PASS_EXPECTED_INDEPENDENT_ORACLE_REJECTION"
            save()

        for capacity in (256, 32768):
            name = "write-commit-" + str(capacity)
            out = model(name, "I1DataCacheCommitMain", "I1DataCacheCommitFixture",
                "five_stage_cache_write_commit.cpp", ["--cache-bytes=" + str(capacity)])
            check(name, out, negative=(["--wrong-forward"],
                "independent masked store/read collision oracle"))
        for width in (32, 64):
            for staged in (False, True):
                name = "pmp-" + str(width) + ("-registered" if staged else "-direct")
                out = model(name, "I1PmpTimingMain", "I1PmpTimingFixture",
                    "five_stage_pmp_timing.cpp", ["--staged"] if staged else [],
                    ["-DI1_PMP_REGISTERED=1"] if staged else [], width=width)
                check(name, out, negative=(["--wrong-permission"], "independent PMP full-interval/priority oracle"))
                if staged and "held_input_noise_checks=768" not in receipt["checks"][name]:
                    raise RuntimeError("missing independent held PMP capture/noise coverage")
        for width in (32, 64):
            name = "execute-" + str(width)
            out = model(name, "FiveStageExecuteDatapathMain", "I1ExecuteDatapathFixture",
                "five_stage_execute_datapath.cpp", ["--pipeline=fpga8", "--timing-cuts"],
                ["-DDUT_TIMING_CUTS=1"], width=width)
            check(name, out, negative=(["--wrong-result"], "independent EX operand/ALU/result oracle"))
        for instruction, fast, split in ((False, False, False), (False, True, False),
                                         (False, True, True), (True, False, False)):
            name = "translation-" + ("if" if instruction else "data-split" if split else "data-fast" if fast else "data")
            flags = ["--timing-cuts", "--atomic"] + (["--fast-data-translation"] if fast else [])
            defines = ["-DI1_MACHINE_OFF_FAST=1"] if fast or instruction else []
            if split:
                flags += ["--split-data-candidates", "--tlb=8"]
                defines += ["-DI1_SPLIT_DATA_CANDIDATES=1"]
                if args.direct_fast_data_issue:
                    flags += ["--direct-fast-data-issue"]
                if args.retirement_overlap != "none":
                    flags += ["--overlap-data-retirement"]
                    defines += ["-DI1_RETIREMENT_OVERLAP=1"]
            if instruction:
                flags += ["--instruction", "--split-candidates", "--window=board", "--tlb=8"]
                defines += ["-DI1_INSTRUCTION_TRANSLATION=1", "-DI1_INSTRUCTION_PMA=1",
                    "-DI1_SPLIT_INSTRUCTION_CANDIDATES=1", "-DI1_PMA_BOARD=1"]
            out = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                "five_stage_translation.cpp", flags, defines)
            check(name, out, negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
            if instruction and "I1_INDEXED_IF_PROOF_REPLACEMENT_PASS" not in receipt["checks"][name]:
                raise RuntimeError("missing indexed IF proof owner replacement/collision coverage")
            if instruction:
                check(name + "-pma", out, negative=(["--wrong-pma"], "independent instruction PMA/noAllocate oracle"))
            if split and "I1_DATA_CANDIDATES_PASS candidate_select_mask=3" not in receipt["checks"][name]:
                raise RuntimeError("missing independently exercised late DT candidate selection")
        vectors = ROOT / "build/gsim/i1-fd-jtag-timing-20261015-r4/vectors.txt"
        vector_receipt = json.loads((vectors.parent / "receipt.json").read_text())
        if sha(vectors) != vector_receipt["vectors_sha256"]:
            raise RuntimeError("independent SoftFloat vector drift")
        receipt["vectors_sha256"] = sha(vectors)
        for profile in ("f", "fd"):
            name = "fp-" + profile
            out = model(name, "I1FloatingPointMain", "I1FloatingPointGsim",
                "five_stage_fp_numerical.cpp", ["--timing-cuts"] + (["--d"] if profile == "fd" else []),
                ["-DI1_TIMING_CUTS=1"])
            check(name, out, [vectors, profile],
                negative=([vectors, profile, "--inject-mismatch"], "FP full mismatch: SoftFloat value"))
            check(name + "-completion", out, [vectors, profile],
                negative=([vectors, profile, "--inject-completion"],
                    "FP full mismatch: registered completion owner status"))
        name = "instruction-cache-pma"
        out = model(name, "I1InstructionCachePmaMain", "I1InstructionCachePmaFixture",
            "five_stage_coherent_if_pma.cpp", ["--cache-bytes=32768"],
            ["-DI1_IF_CACHE_BYTES=32768"])
        check(name, out, negative=(["--wrong-data"], "independent coherent IF byte oracle"))
        check(name + "-policy", out,
            negative=(["--wrong-hint"], "trusted coherent IF cacheability contradicts physical/noAllocate policy"))
        for capacity in (256, 32768):
            name = "cache-pair-" + str(capacity)
            out = model(name, "I1CoherentPairGsimMain", "I1CoherentPairGsim",
                "five_stage_coherence.cpp", ["--cuts", "--two-way", "--bandwidth",
                    "--ordered-admission", "--cache-bytes=" + str(capacity)],
                ["-DI1_PAIR_CACHE_BYTES=" + str(capacity), "-DI1_COHERENT_TWO_WAY",
                    "-DI1_HOME_WRITE_PIPELINE", "-DI1_ORDERED_ADMISSION"])
            check(name, out, negative=(["--wrong-data"], "independent dirty-owner byte oracle"))
            check(name + "-stream", out,
                negative=(["--wrong-stream"], "independent ordinary cohort byte/order oracle"))
        name = "cpu-coherent"
        flags = receipt["cpu_flags"][name]
        out = model(name, "FiveStageSocGsimMain", "FiveStageSoc",
            "five_stage_privilege_soc.cpp", flags, ["-DI1_COHERENT_READBACK"])
        privilege = payload("privilege.bin")
        check(name + "-precise-privilege", out, [privilege],
            negative=([privilege, "--wrong-result"], "independent privileged SoC result ledger oracle"))
        stream_tasks = []
        for mode in ("bare", "sv39"):
            for large, delay in ((False, 3), (True, 3), (True, 80)):
                image = payload("stream64k.bin" if large else "stream.bin")
                argv = [image, "--" + mode + "-throughput"] + (["--large-stream"] if large else [])
                if delay == 80:
                    argv += ["--memory-latency=80"]
                key = name + ("-64k-" if large else "-") + mode + ("-latency80" if delay == 80 else "")
                negative = ([*argv, "--wrong-stream"], "independent streaming READ checksum") if not large else None
                stream_tasks.append((key, argv, negative))
        def stream_check(task):
            key, argv, negative = task
            check(key, out, argv, negative=negative)
            old = baseline["stream_comparison"][key]["new"]
            new = json.loads(receipt["checks"][key].split(" ", 1)[1])
            with result_lock:
                receipt.setdefault("stream_comparison", {})[key] = {
                    "old": old, "new": new,
                    "copy_change_percent": 100 * (new["copy_ticks"] / old["copy_ticks"] - 1)}
                save()
            if new["bytes"] == 65536 and sum(new[k] for k in ("read_ticks", "write_ticks", "copy_ticks")) > \
                    sum(old[k] for k in ("read_ticks", "write_ticks", "copy_ticks")):
                raise RuntimeError("known failed aggregate stream performance gate: " + key)
        # Separate processes share only immutable model/payload files; each
        # test has its own memory, deterministic service law and unique log.
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(stream_check, stream_tasks))
        link(out, "FiveStageSoc", "five_stage_ca_soc.cpp", "ca", ["-DI1_COHERENT_READBACK"])
        ca = payload("ca.bin")
        check(name + "-ca", out, [ca], binary="ca", negative=([ca, "--wrong-result"],
            "independent C/A completion/alias/boundary oracle"))
        check(name + "-ca-page-end", out, [ca, "--compressed-boundary"], binary="ca")
        link(out, "FiveStageSoc", "five_stage_fp_soc.cpp", "fp", ["-DI1_COHERENT_READBACK"])
        corpus = payload("fd-corpus.bin")
        count = prior["cpu_fp_corpus"]["cases"]
        check(name + "-fd-corpus", out, [corpus, count], binary="fp",
            negative=([corpus, count, "--wrong-result"],
                "independent FP actual CPU result/flags/context ledger oracle"))
        check(name + "-fd-context", out, [payload("fd-context.bin"), 32, "--faults"], binary="fp")
        link(out, "FiveStageSoc", "five_stage_soc_coremark.cpp", "coremark", ["-DI1_COHERENT_READBACK"])
        elf = payload("coremark/coremark.elf")
        symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n", elf], text=True)
        values = {parts[2]: int(parts[0], 16) for line in symbols.splitlines()
            if len(parts := line.split()) == 3}
        cm_argv = [payload("coremark/coremark.bin"), *[hex(values[k]) for k in (
            "coremark_validation_errors", "coremark_crcs", "coremark_phase", "coremark_validated",
            "coremark_duration_warnings")]]
        check(name + "-coremark-o3", out, cm_argv, binary="coremark",
            negative=([*cm_argv, "--inject"], "CoreMark independent register oracle mismatch"))
        check(name + "-fetch-control", out, [payload("coremark/fetch-control.bin"), "--smoke"],
            binary="coremark")
        result = json.loads(receipt["checks"][name + "-coremark-o3"].split(" ", 1)[1])
        result["roi_ipc"] = result["roi_instructions"] / result["roi_ticks"]
        receipt["benchmarks"] = {name: result}
        receipt["coremark_comparison"] = {"old": baseline["benchmarks"][name], "new": result,
            "pre_batch26": prior["benchmarks"][name]}
        receipt["performance_gates"] = {
            "coremark_recovered_pre_batch26": result["roi_ticks"] <= prior["benchmarks"][name]["roi_ticks"],
            "coremark_no_regression_vs_batch29": result["roi_ticks"] <= baseline["benchmarks"][name]["roi_ticks"]}
        for key, item in receipt["stream_comparison"].items():
            if item["new"]["bytes"] != 65536:
                continue
            old_total = sum(item["old"][k] for k in ("read_ticks", "write_ticks", "copy_ticks"))
            new_total = sum(item["new"][k] for k in ("read_ticks", "write_ticks", "copy_ticks"))
            receipt["performance_gates"][key + "_aggregate_nonregression"] = new_total <= old_total
            for metric in ("read_ticks", "write_ticks", "copy_ticks"):
                receipt["performance_gates"][key + "_" + metric + "_nonregression"] = \
                    item["new"][metric] <= item["old"][metric]
        if not all(receipt["performance_gates"].values()):
            raise RuntimeError("candidate failed CoreMark recovery/aggregate stream performance gate")
        if qualification_sources() != frozen:
            raise RuntimeError("source/oracle drift during acceptance")
        receipt["status"] = "PASS_I1_CPU_TIMING30_AFFECTED_SHORT_ONLY"
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(output)): sha(p)
            for p in output.rglob("*") if p.is_file() and p.name != "receipt.json"}
        save()
        print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
