#!/usr/bin/env python3
"""Short two-issue A/B, one model per profile, ISA + NEMU on every retirement.

Reuses saved GSIM translation units when supplied; never runs CAD, full GSIM,
Linux, UART protocol acceptance, or claims a formal CoreMark/FPGA result.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from run import BUILD, HERE, ROOT, compiler, run, setup, test
from control_stage import core_payloads, negative, reference

PROFILES = ("staged-control-heads", "staged-throughput")
DEFINES = {"ROB_ENTRIES": 16, "PHYSICAL_REGS": 48, "TAG_BITS": 64, "MEMORY_ENTRIES": 2,
           "REGISTERED_BRANCH_REDIRECT": 1, "REGISTERED_RESPONSE_OWNERS": 1,
           "REGISTERED_MEMORY_ADDRESS": 1, "BRANCH_ENTRIES": 32,
           "STORE_BUFFER_ENTRIES": 2, "DELAYED_PREDICTION_TRAINING": 1}
EXPECTED_KEYS = {(name, 1) for name in (
    "throughput_independent_alu", "throughput_dependent_alu", "throughput_dual_dependency",
    "throughput_not_taken_mixed", "throughput_direct_jumps", "throughput_taken_loop")}
EXPECTED_KEYS |= {(name, latency) for name in (
    "throughput_load_use", "throughput_memory_alu_mix", "throughput_compiled_sum") for latency in (1, 12)}
SAVED_BASELINE = {
    "IntegerCoreGsim.fir": "fbf67b2bcc77f6efb93df6f2d3e0277e0032974274ad7f0c1d56d6b7b9e0498a",
    "IntegerCoreGsim.h": "640b29c42d2fe710604f50873b333492e35d8cd4758d01dfa4bcfad9acfb2fff",
    "IntegerCoreGsim0.cpp": "a1b628d05fccaa1b94fbdc8c098fdcb66d67cc011873dbe9dbd9d4511d9712b3"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def hardware_sources():
    return {str(path.relative_to(ROOT)): sha256(path)
            for path in sorted((ROOT / "src/main/scala").rglob("*.scala"))}


def parse_measurements(text, expected_programs=12, expected_keys=None):
    expected_keys = EXPECTED_KEYS if expected_keys is None else expected_keys
    rows = [json.loads(line[4:]) for line in text.splitlines() if line.startswith("IPC ")]
    if f"GSIM short two-issue throughput + NEMU: PASS programs={expected_programs} " not in text:
        raise RuntimeError("short throughput completion marker missing")
    if len(rows) != len(expected_keys) or {(r["name"], r["memory_latency"]) for r in rows} != expected_keys:
        raise RuntimeError("short throughput workloads missing or duplicated")
    for row in rows:
        cycles, retired = row["cycles"], row["retired"]
        if not isinstance(cycles, int) or cycles <= 0 or not isinstance(retired, int) or retired <= 0:
            raise RuntimeError("invalid cycle/retirement counts")
        if row["rob"] != 16 or row["physical"] != 48 or row["memory_entries"] != 2:
            raise RuntimeError("performance geometry differs from two-issue board baseline")
        for stage in ("commit", "issue", "rename"):
            if sum(row[f"{width}_{stage}_cycles"] for width in ("zero", "single", "dual")) != cycles:
                raise RuntimeError(f"{stage} histogram accounting mismatch")
        if row["single_commit_cycles"] + 2 * row["dual_commit_cycles"] != retired:
            raise RuntimeError("retirement accounting mismatch")
        if row["single_issue_cycles"] + 2 * row["dual_issue_cycles"] != row["issued"]:
            raise RuntimeError("issue accounting mismatch")
        if not math.isclose(row["ipc"], retired / cycles, rel_tol=1e-7):
            raise RuntimeError("reported IPC differs from measured retirement counts")
        row["dual_issue_fraction"] = row["dual_issue_cycles"] / cycles
        row["dual_commit_fraction"] = row["dual_commit_cycles"] / cycles
        row["average_rob_occupancy"] = row["rob_occupancy_sum"] / cycles
    return rows


def compare_measurements(baseline, candidate):
    old = {(row["name"], row["memory_latency"]): row for row in baseline}
    comparisons = []
    for new in candidate:
        previous = old[(new["name"], new["memory_latency"])]
        if previous["retired"] != new["retired"]:
            raise RuntimeError("A/B retired different architectural instruction streams")
        ratio = previous["cycles"] / new["cycles"]
        comparisons.append({"name": new["name"], "memory_latency": new["memory_latency"],
            "baseline_cycles": previous["cycles"], "candidate_cycles": new["cycles"],
            "baseline_ipc": previous["ipc"], "candidate_ipc": new["ipc"],
            "same_clock_speedup": ratio, "candidate_clock_ratio_to_break_even": 1 / ratio,
            "baseline_dual_issue_fraction": previous["dual_issue_fraction"],
            "candidate_dual_issue_fraction": new["dual_issue_fraction"],
            "baseline_dual_commit_fraction": previous["dual_commit_fraction"],
            "candidate_dual_commit_fraction": new["dual_commit_fraction"]})
    return comparisons


def build_reused(cxx, saved, output, profile):
    saved = saved.resolve()
    sources = sorted(saved.glob("IntegerCoreGsim[0-9]*.cpp"))
    if not sources or not (saved / "IntegerCoreGsim.fir").is_file():
        raise RuntimeError("saved GSIM model source/FIR missing")
    manifest = saved / "model-profile.json"
    expected = profile == PROFILES[0] and len(sources) == 1 and all(
        (saved / name).is_file() and sha256(saved / name) == digest for name, digest in SAVED_BASELINE.items())
    if manifest.is_file():
        metadata = json.loads(manifest.read_text())
        expected |= metadata.get("profile") == profile and metadata.get("files_sha256") == {
            p.name: sha256(p) for p in [saved / "IntegerCoreGsim.fir", saved / "IntegerCoreGsim.h", *sources]}
    if not expected:
        raise RuntimeError(f"{profile} model provenance/hash mismatch: {saved}")
    flags = {**DEFINES, "REGISTERED_FETCH_PACKET": int(profile == PROFILES[1])}
    run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         *(f"-D{k}={v}" for k, v in flags.items()), "-I" + str(saved), *sources,
         HERE / "harness/core.cpp", "-ldl", "-o", output / "run"], log=output / "compile.log")
    return saved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline-model", type=Path,
                        help="reuse archived staged-control-heads GSIM sources, not its old harness executable")
    parser.add_argument("--candidate-model", type=Path,
                        help="reuse current staged-throughput GSIM sources produced by ThroughputPerfGsimMain")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    output = BUILD / ("throughput-perf-" + args.tag)
    if output.exists():
        parser.error("output exists; use a fresh tag to preserve A/B evidence")
    output.mkdir(parents=True)
    report = {"status": "running", "issue_width": 2, "rob_entries": 16, "physical_registers": 48,
        "memory_entries": 2, "branch_predictor_entries": 32, "profiles": {},
        "measurement_scope": "bare core, board backend geometry/timing; ideal raw instruction device, synthetic RAM",
        "compressed_frontend_or_board_cache_covered_here": False,
        "issue_count_definition": "new dispatch to execution slots plus store-preparation grants and newly started memory/M/CSR operations; a store can count at preparation and LSU start, so this is not unique architectural instructions; no resident-slot recount",
        "rename_count_definition": "accepted0/1 are actual rename, not raw fetch capture",
        "stall_limit": "raw_input_present_no_rename is observational, not a causal allocation stall after fetch decoupling",
        "timing_scope": "reset startup through last architectural retirement; memory drain reported separately",
        "clock_assumption": "same frequency ratios only; multiply by separately verified candidate/baseline clock ratio",
        "routed_timing_verified": False, "on_board_verified": False,
        "harness_sha256": sha256(HERE / "harness/core.cpp"),
        "hardware_source_sha256": hardware_sources()}
    evidence = output / "results.json"
    try:
        cxx, version = compiler()
        report["compiler"] = version
        gsim = None
        ref = reference()
        payloads = core_payloads(output)
        report["reference_sha256"] = sha256(ref)
        report["payload_sha256"] = {str(p): sha256(p) for p in payloads}
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
        for profile, saved in zip(PROFILES, (args.baseline_model, args.candidate_model)):
            destination = output / profile
            destination.mkdir()
            if saved:
                model = build_reused(cxx, saved, destination, profile)
                run([destination / "run", ref, *payloads, "--throughput-short"], env=env,
                    log=destination / "throughput.log", timeout=180)
            else:
                if gsim is None:
                    gsim, cxx = setup(False)
                model = test(gsim, cxx, str(destination.relative_to(BUILD)), "ooo.ThroughputPerfGsimMain",
                    "IntegerCoreGsim", "core.cpp", parameters=(profile,),
                    runtime_args=(ref, *payloads, "--throughput-short"),
                    defines={**DEFINES, "REGISTERED_FETCH_PACKET": int(profile == PROFILES[1])},
                    timeout=180, run_log="throughput.log")
                (model / "model-profile.json").write_text(json.dumps({"profile": profile, "files_sha256": {
                    p.name: sha256(p) for p in [model / "IntegerCoreGsim.fir", model / "IntegerCoreGsim.h",
                                              *sorted(model.glob("IntegerCoreGsim[0-9]*.cpp"))]}}, indent=2) + "\n")
            # The same newly linked harness/model is used for correctness and
            # measurement; corruption must still be rejected by independent NEMU.
            run([destination / "run", ref, *payloads, "--timing-smoke"], env=env,
                log=destination / "timing-smoke.log", timeout=180)
            if profile == PROFILES[1]:
                run([destination / "run", ref, *payloads, "--pipeline-recovery"], env=env,
                    log=destination / "pipeline-recovery.log", timeout=180)
                recovery = (destination / "pipeline-recovery.log").read_text()
                witnesses = re.search(r"GSIM pipeline recovery \+ NEMU: PASS .*"
                    r"slot0HeldLane1Progress=(\d+) olderLane0BranchResolution=(\d+) aluForwardingHits=(\d+)",
                    recovery)
                if not witnesses or not all(int(value) > 0 for value in witnesses.groups()):
                    raise RuntimeError("pipeline recovery witnesses missing")
                report["pipeline_recovery_witnesses"] = dict(zip(
                    ("slot0_held_lane1_progress", "older_lane0_branch_resolution", "alu_forwarding_hits"),
                    map(int, witnesses.groups())))
            negative(destination / "run", (ref, *payloads), "NEMU register mismatch", destination / "negative.log")
            text = (destination / "throughput.log").read_text()
            print(text, end="", flush=True)
            report["profiles"][profile] = {"status": "passed", "model_directory": str(model),
                "model_fir_sha256": sha256(model / "IntegerCoreGsim.fir"),
                "model_sources_sha256": {p.name: sha256(p) for p in sorted(model.glob("IntegerCoreGsim[0-9]*.cpp"))},
                "executable_sha256": sha256(destination / "run"),
                "measurements": parse_measurements(text)}
        report["comparisons"] = compare_measurements(*(report["profiles"][p]["measurements"] for p in PROFILES))
        report["same_clock_geomean_speedup"] = math.exp(sum(math.log(r["same_clock_speedup"])
            for r in report["comparisons"]) / len(report["comparisons"]))
        report["status"] = "passed"
        report["performance_acceptance"] = "measurements available; regressions require engineering review, not hidden by correctness pass"
        for row in report["comparisons"]:
            print(f"A/B {row['name']} RAM={row['memory_latency']} "
                  f"cycles {row['baseline_cycles']} -> {row['candidate_cycles']} "
                  f"same-clock x{row['same_clock_speedup']:.4f}", flush=True)
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError, KeyError):
        report["status"] = "failed"
        raise
    finally:
        changed = hardware_sources() != report["hardware_source_sha256"]
        if changed:
            report["status"] = "failed"
            report["failure"] = "Hardware source changed during A/B measurement"
        evidence.write_text(json.dumps(report, indent=2) + "\n")
        if changed:
            raise RuntimeError(report["failure"])
    print(f"Short two-issue A/B: {report['status']}; evidence: {evidence}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError, KeyError) as error:
        print(f"GSIM throughput: {error}", file=sys.stderr)
        sys.exit(1)
