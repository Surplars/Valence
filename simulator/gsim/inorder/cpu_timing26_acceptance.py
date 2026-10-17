#!/usr/bin/env python3
"""Affected I1 batch26 checks only; exact old payloads, no full suite or Vivado."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys

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
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    output = ROOT / "build/gsim" / ("i1-cpu-timing26-" + args.tag)
    output.mkdir(exist_ok=False)
    frozen = qualification_sources()
    prior = json.loads(args.reference.read_text())
    stopped = json.loads((args.reference.parent / "stop-summary.json").read_text())
    if not stopped["target_cpu_configuration_pass"] or stopped["raw_receipt_sha256"] != sha(args.reference):
        raise RuntimeError("exact user-stopped, target-passed reference required")
    receipt = {"status": "RUNNING", "checks": {}, "source_sha256": frozen,
        "reference": str(args.reference), "reference_sha256": sha(args.reference),
        "reference_scope": "target subset passed; original full receipt remains FAIL(-15)",
        "cpu_flags": {"cpu-coherent": prior["cpu_flags"]["cpu-coherent"]},
        "cache_bytes_each": 32768, "cpu_target_hz": 300000000,
        "physical_qualified": False, "board_qualified": False, "formal_coremark": False,
        "scope": "affected PMP/translation/FP/cache/actual-CPU checks, not full prior212 suite"}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    def save():
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
            if fir.stat().st_size % 4096 == 0:
                parser = out / (top + ".gsim-input.fir")
                parser.write_bytes(fir.read_bytes() + b"\n")
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
            receipt["checks"][name] = text
            print(text, flush=True)
            if negative:
                bad_args, expected = negative
                bad = subprocess.run([str(out / binary), *map(str, bad_args)], env=env,
                    capture_output=True, text=True, timeout=300)
                (out / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or expected not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control did not reject: " + name)
                receipt["checks"][name + "-negative"] = "PASS_EXPECTED_INDEPENDENT_ORACLE_REJECTION"
            save()

        for width in (32, 64):
            for staged in (False, True):
                name = "pmp-" + str(width) + ("-registered" if staged else "-direct")
                out = model(name, "I1PmpTimingMain", "I1PmpTimingFixture",
                    "five_stage_pmp_timing.cpp", ["--staged"] if staged else [],
                    ["-DI1_PMP_REGISTERED=1"] if staged else [], width=width)
                check(name, out, negative=(["--wrong-permission"], "independent PMP full-interval/priority oracle"))
        for instruction, fast in ((False, False), (False, True), (True, False)):
            name = "translation-" + ("if" if instruction else "data-fast" if fast else "data")
            flags = ["--timing-cuts", "--atomic"] + (["--fast-data-translation"] if fast else [])
            defines = []
            if instruction:
                flags += ["--instruction", "--split-candidates", "--window=board", "--tlb=8"]
                defines = ["-DI1_INSTRUCTION_TRANSLATION=1", "-DI1_INSTRUCTION_PMA=1",
                    "-DI1_SPLIT_INSTRUCTION_CANDIDATES=1", "-DI1_PMA_BOARD=1"]
            out = model(name, "FiveStageTranslationMain", "FiveStageTranslationHarness",
                "five_stage_translation.cpp", flags, defines)
            check(name, out, negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
            if instruction:
                check(name + "-pma", out, negative=(["--wrong-pma"], "independent instruction PMA/noAllocate oracle"))
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
        flags = prior["cpu_flags"][name]
        out = model(name, "FiveStageSocGsimMain", "FiveStageSoc",
            "five_stage_privilege_soc.cpp", flags, ["-DI1_COHERENT_READBACK"])
        privilege = payload("privilege.bin")
        check(name + "-precise-privilege", out, [privilege],
            negative=([privilege, "--wrong-result"], "independent privileged SoC result ledger oracle"))
        for mode in ("bare", "sv39"):
            for large, delay in ((False, 3), (True, 3), (True, 80)):
                image = payload("stream64k.bin" if large else "stream.bin")
                argv = [image, "--" + mode + "-throughput"] + (["--large-stream"] if large else [])
                if delay == 80:
                    argv += ["--memory-latency=80"]
                key = name + ("-64k-" if large else "-") + mode + ("-latency80" if delay == 80 else "")
                check(key, out, argv, negative=([*argv, "--wrong-stream"],
                    "independent streaming READ checksum") if not large else None)
                old = json.loads(prior["checks"][key].split(" ", 1)[1])
                new = json.loads(receipt["checks"][key].split(" ", 1)[1])
                receipt.setdefault("stream_comparison", {})[key] = {
                    "old": old, "new": new,
                    "copy_change_percent": 100 * (new["copy_ticks"] / old["copy_ticks"] - 1)}
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
        receipt["coremark_comparison"] = {"old": prior["benchmarks"][name], "new": result}
        if qualification_sources() != frozen:
            raise RuntimeError("source/oracle drift during acceptance")
        receipt["status"] = "PASS_I1_CPU_TIMING26_AFFECTED_SHORT_ONLY"
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
