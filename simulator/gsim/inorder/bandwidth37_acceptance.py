#!/usr/bin/env python3
"""One affected I1 bandwidth batch: fixed owners/caches, no Vivado or Linux."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simulator/gsim"))
import run as common
sys.path.insert(0, str(Path(__file__).resolve().parent))
from coherent_network_acceptance import qualification_sources
from soc_acceptance import sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--components-only", action="store_true")
    ap.add_argument("--reuse-components", type=Path)
    ap.add_argument("--reuse-compiles", type=Path,
        help="only exact fresh FIR and hashed object/header files; every check re-executes")
    ap.add_argument("--baseline", type=Path, default=ROOT /
        "build/gsim/i1-bandwidth36-20261017-r4/receipt.json")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        ap.error("safe unique tag required")
    out = ROOT / "build/gsim" / ("i1-bandwidth37-" + args.tag)
    out.mkdir(exist_ok=False)
    baseline = json.loads(args.baseline.read_text())
    if baseline["status"] != "PASS_I1_BANDWIDTH36_AFFECTED_SHORT_ONLY":
        raise RuntimeError("exact previous short PASS receipt required")
    frozen = qualification_sources()
    flags = baseline["cpu_flags"] + [
        "--coherent-read-overlap", "--data-reply-handoff"]
    receipt = {"status": "RUNNING", "checks": {}, "source_sha256": frozen,
        "baseline": str(args.baseline), "baseline_sha256": sha(args.baseline),
        "cpu_flags": flags, "cache_bytes_each": 32768, "ddr_slots": 2, "write_slots": 1,
        "components_only": args.components_only, "physical_qualified": False,
        "board_qualified": False, "formal_coremark": False,
        "scope": "MMU registered reply / existing ADDR read-owner handoff; paired independent Home reads; "
            "existing acquire/release contexts and two backing slots, no new payload queues"}
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}

    def save():
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

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
        if baseline["tools"] != receipt["tools"]:
            raise RuntimeError("baseline tools mismatch")
        compiled = json.loads(args.reuse_compiles.read_text()) if args.reuse_compiles else None
        if compiled and compiled["tools"] != receipt["tools"]:
            raise RuntimeError("compile cache tools mismatch")
        common.run(["mill", "-i", "OrbitalI1.test.testOnly", "inorder.FiveStageConfigSpec"],
            log=out / "scala.log")

        def link(directory, top, driver, binary="run", defines=()):
            common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                "-fno-sanitize-recover=all", "-DDUT_XLEN=64", "-I" + str(directory),
                *defines, *sorted(directory.glob(top + "[0-9]*.o")),
                ROOT / "simulator/gsim/harness" / driver, "-o", directory / binary],
                log=directory / (binary + "-link.log"), timeout=900)

        def model(name, entry, top, driver, options=(), defines=()):
            directory = out / name
            directory.mkdir()
            print("BUILD", name, flush=True)
            common.run(["mill", "-i", "OrbitalI1.test.runMain", "inorder." + entry,
                directory, 64, *options], log=directory / "elaborate.log")
            fir = directory / (top + ".fir")
            previous = args.reuse_compiles.parent / name if compiled else None
            if previous and (previous / fir.name).is_file() and \
                    sha(fir) == compiled["artifact_sha256"].get(name + "/" + fir.name):
                import shutil
                for artifact in previous.iterdir():
                    if artifact.suffix in (".o", ".h", ".cpp"):
                        if sha(artifact) != compiled["artifact_sha256"].get(name + "/" + artifact.name):
                            raise RuntimeError("compile artifact drift")
                        shutil.copy2(artifact, directory / artifact.name)
                if not list(directory.glob(top + "[0-9]*.o")):
                    raise RuntimeError("missing exact object cache")
                receipt.setdefault("exact_compile_reuse", {})[name] = {
                    "receipt": str(args.reuse_compiles), "fresh_fir_sha256": sha(fir),
                    "checks_reused": False}
                link(directory, top, driver, defines=defines)
                return directory
            original = fir.read_text()
            normalized, count = re.subn(
                r"(?m)^(\s*smem dataWays_\S+ : [^\n,]+), old(?= @\[[^\n]*$)",
                r"\1 old", original)
            parser = directory / (top + ".gsim-input.fir")
            parser.write_text(normalized + "\n")
            receipt.setdefault("parser_compat", {})[name] = {
                "only_old_delimiter_count": count, "read_under_write": "old"}
            common.run([gsim, "--threads=1", "--dir=" + str(directory), parser],
                log=directory / "generate.log", timeout=900)
            def compile_one(source):
                common.run([cxx, "-std=c++20", "-O1", "-fsanitize=address,undefined",
                    "-fno-sanitize-recover=all", "-I" + str(directory), "-c", source,
                    "-o", source.with_suffix(".o")],
                    log=directory / (source.stem + "-compile.log"), timeout=900)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(compile_one, sorted(directory.glob(top + "[0-9]*.cpp"))))
            link(directory, top, driver, defines=defines)
            return directory

        def check(name, directory, argv=(), negative=None, binary="run"):
            common.run([directory / binary, *argv], env=env,
                log=directory / (name + ".log"), timeout=300)
            value = (directory / (name + ".log")).read_text().strip()
            receipt["checks"][name] = value
            print(value, flush=True)
            if negative:
                bad_args, expected = negative
                bad = subprocess.run([str(directory / binary), *map(str, bad_args)],
                    env=env, capture_output=True, text=True, timeout=300, cwd=ROOT)
                (directory / (name + "-negative.log")).write_text(bad.stdout + bad.stderr)
                if bad.returncode == 0 or expected not in bad.stdout + bad.stderr:
                    raise RuntimeError("negative control did not reject: " + name)
                receipt["checks"][name + "-negative"] = "PASS_EXPECTED_ORACLE_REJECTION"
            save()

        if args.reuse_components:
            prior = json.loads(args.reuse_components.read_text())
            if prior["status"] != "PASS_I1_BANDWIDTH37_COMPONENTS_ONLY" or \
                    prior["source_sha256"] != frozen or prior["tools"] != receipt["tools"]:
                raise RuntimeError("exact source/tool-bound component receipt required")
            receipt["checks"].update(prior["checks"])
            receipt["component_evidence"] = {"path": str(args.reuse_components),
                "sha256": sha(args.reuse_components), "rerun": False}
        else:
            home = model("home-read-pair", "I1HomeReadPairMain", "I1HomeReadPairFixture",
                "five_stage_home_read_pair.cpp")
            check("home-read-pair", home,
                negative=(["--wrong-word"], "independent paired Home eight-word/error/source oracle"))
            mmu = model("mmu", "FiveStageTranslationMain", "FiveStageTranslationHarness",
                "five_stage_translation.cpp", ["--fast-data-translation", "--timing-cuts",
                    "--atomic", "--overlap-data-retirement", "--direct-fast-data-issue",
                    "--indexed-data-proofs", "--split-data-candidates", "--data-reply-handoff"],
                ["-DI1_DATA_REPLY_HANDOFF", "-DI1_SPLIT_DATA_CANDIDATES"])
            check("mmu-handoff", mmu,
                negative=(["--wrong-page"], "independent Sv39/PMP/page-vs-access fault oracle"))
            for capacity, overlap in ((256, False), (256, True), (32768, True)):
                name = "pair-" + str(capacity) + ("-overlap" if overlap else "-serial")
                options = ["--cuts", "--two-way", "--bandwidth", "--ordered-admission",
                    "--cache-bytes=" + str(capacity), "--line-grants", "--miss-turnover", "--writeback-overlap"]
                if overlap:
                    options += ["--read-overlap"]
                directory = model(name, "I1CoherentPairGsimMain", "I1CoherentPairGsim",
                    "five_stage_coherence.cpp", options,
                    ["-DI1_PAIR_CACHE_BYTES=" + str(capacity), "-DI1_COHERENT_TWO_WAY",
                     "-DI1_HOME_WRITE_PIPELINE", "-DI1_ORDERED_ADMISSION", "-DI1_MISS_TURNOVER"] +
                    (["-DI1_READ_OVERLAP"] if overlap else []))
                check(name, directory,
                    negative=(["--wrong-data"], "independent dirty-owner byte oracle"))
                check(name + "-stream", directory,
                    negative=(["--wrong-stream"], "independent ordinary cohort byte/order oracle"))
        if args.components_only:
            receipt["status"] = "PASS_I1_BANDWIDTH37_COMPONENTS_ONLY"
        else:
            prior_vectors = Path(json.loads(Path(baseline["baseline"]).read_text())["reference"])
            vectors = json.loads(prior_vectors.read_text())
            def payload(name):
                path = prior_vectors.parent / name
                if sha(path) != vectors["artifact_sha256"][name]:
                    raise RuntimeError("frozen old payload drift: " + name)
                receipt.setdefault("payload_sha256", {})[name] = sha(path)
                return path
            directory = model("cpu", "FiveStageSocGsimMain", "FiveStageSoc",
                "five_stage_privilege_soc.cpp", flags, ["-DI1_COHERENT_READBACK"])
            privilege = payload("privilege.bin")
            check("precise-privilege", directory, [privilege],
                negative=([privilege, "--wrong-result"], "independent privileged SoC result ledger oracle"))
            tasks = []
            for mode in ("bare", "sv39"):
                for large, delay in ((False, 3), (True, 3), (True, 80)):
                    image = payload("stream64k.bin" if large else "stream.bin")
                    argv = [image, "--" + mode + "-throughput"] + (["--large-stream"] if large else [])
                    if delay != 3:
                        argv += ["--memory-latency=" + str(delay)]
                    key = "cpu-coherent-" + ("64k-" if large else "") + mode + \
                        ("-latency80" if delay != 3 else "")
                    tasks.append((key, argv))
            for key, argv in tasks:
                check(key, directory, argv)
                current = json.loads(receipt["checks"][key].split(" ", 1)[1])
                old = baseline["stream_comparison"][key]["new"]
                if current["bytes"] != old["bytes"]:
                    raise RuntimeError("stream byte-count mismatch")
                receipt.setdefault("stream_comparison", {})[key] = {"old": old, "new": current,
                    "percent": {k: 100 * (current[k] / old[k] - 1)
                        for k in ("read_ticks", "write_ticks", "copy_ticks")}}
                save()
            link(directory, "FiveStageSoc", "five_stage_ca_soc.cpp", "ca", ["-DI1_COHERENT_READBACK"])
            check("ca", directory, [payload("ca.bin")], binary="ca")
            check("ca-boundary", directory, [payload("ca.bin"), "--compressed-boundary"], binary="ca")
            link(directory, "FiveStageSoc", "five_stage_fp_soc.cpp", "fp", ["-DI1_COHERENT_READBACK"])
            check("fd-context", directory, [payload("fd-context.bin"), 32, "--faults"], binary="fp")
            link(directory, "FiveStageSoc", "five_stage_soc_coremark.cpp", "coremark",
                ["-DI1_COHERENT_READBACK"])
            symbols = subprocess.check_output(["riscv64-unknown-elf-nm", "-n",
                payload("coremark/coremark.elf")], text=True)
            values = {s[2]: int(s[0], 16) for line in symbols.splitlines()
                if len(s := line.split()) == 3}
            argv = [payload("coremark/coremark.bin"), *[hex(values[k]) for k in (
                "coremark_validation_errors", "coremark_crcs", "coremark_phase", "coremark_validated",
                "coremark_duration_warnings")]]
            check("coremark-o3", directory, argv, binary="coremark",
                negative=([*argv, "--inject"], "CoreMark independent register oracle mismatch"))
            result = json.loads(receipt["checks"]["coremark-o3"].split(" ", 1)[1])
            receipt["coremark_comparison"] = {"old": baseline["coremark_comparison"]["new"], "new": result}
            receipt["performance_gates"] = {"coremark": result["roi_ticks"] <=
                baseline["coremark_comparison"]["new"]["roi_ticks"]}
            for key, item in receipt["stream_comparison"].items():
                if item["new"]["bytes"] == 65536:
                    for metric in ("read_ticks", "write_ticks", "copy_ticks"):
                        receipt["performance_gates"][key + "/" + metric] = \
                            item["new"][metric] <= item["old"][metric]
            if not all(receipt["performance_gates"].values()):
                raise RuntimeError("performance candidate regressed; preserve failed receipt")
            receipt["status"] = "PASS_I1_BANDWIDTH37_AFFECTED_SHORT_ONLY"
        if qualification_sources() != frozen:
            raise RuntimeError("source drift during acceptance")
    except BaseException as error:
        receipt["status"] = "FAIL"
        receipt["error"] = repr(error)
        raise
    finally:
        receipt["artifact_sha256"] = {str(p.relative_to(out)): sha(p)
            for p in out.rglob("*") if p.is_file() and p.name != "receipt.json"}
        save()
        print(json.dumps({"status": receipt["status"], "receipt": str(out / "receipt.json")}), flush=True)


if __name__ == "__main__":
    main()
