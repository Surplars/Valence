#!/usr/bin/env python3
"""One short frontend batch: independent PMP/queue oracles + two-issue NEMU IPC A/B."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test
from control_stage import core_payloads, negative, reference
import throughput_perf as perf

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    name = "gmac-ready-" + args.tag
    output = BUILD / name
    if output.exists():
        parser.error("fresh evidence directory required")
    output.mkdir(parents=True)
    sources = perf.hardware_sources()
    report = {"status":"RUNNING", "hardware_source_sha256":sources, "issue_width":2,
        "scope":"bare CPU IPC; separate compressed reservoir and packet PMP oracles",
        "not_covered":["whole-board timing", "physical GMAC", "Linux", "independent clock CPU GSIM"],
        "profiles":{}, "checks":{}}
    try:
        gsim, cxx = setup(False)
        pmp = test(gsim, cxx, name + "/pmp", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim",
            "pmp_checker.cpp", parameters=("packet", "word-span"), defines={})
        negative(pmp / "run", (), "PMP oracle mismatch", pmp / "negative.log")
        report["checks"]["pmp"] = (pmp / "test.log").read_text()
        for width in (2, 4):
            model = test(gsim, cxx, name + f"/reservoir{width}", "ooo.RegisteredFetchPacketGsimMain",
                "RegisteredFetchPacketGsim", "registered_fetch_packet.cpp",
                parameters=(str(width), "parallel-validation", "hints32"),
                defines={"FETCH_WIDTH":width, "COMPRESSED":1, "HINT_ENTRIES":32})
            negative(model / "run", (), "fetch packet oracle mismatch", model / "negative.log")
            report["checks"][f"reservoir{width}"] = (model / "test.log").read_text()
        ref = reference()
        payloads = core_payloads(output)
        expected_keys = perf.EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)}
        # Strict parser still checks every histogram and retired instruction count.
        def parse(text):
            return perf.parse_measurements(text, expected_programs=13, expected_keys=expected_keys)
        env = {**os.environ, "ASAN_OPTIONS":"detect_leaks=0"}
        for profile in ("staged-throughput", "staged-gmac-ready"):
            model = test(gsim, cxx, name + "/" + profile, "ooo.ThroughputPerfGsimMain",
                "IntegerCoreGsim", "core.cpp", parameters=(profile,),
                runtime_args=(ref, *payloads, "--throughput-short"),
                defines={**perf.DEFINES, "REGISTERED_FETCH_PACKET":1, "FETCH_HINT_ALIAS_BENCH":1},
                timeout=180, run_log="throughput.log")
            run([model / "run", ref, *payloads, "--timing-smoke"], env=env,
                log=model / "timing-smoke.log", timeout=180)
            run([model / "run", ref, *payloads, "--pipeline-recovery"], env=env,
                log=model / "pipeline-recovery.log", timeout=180)
            negative(model / "run", (ref, *payloads), "NEMU register mismatch", model / "negative.log")
            report["profiles"][profile] = {"measurements":parse((model / "throughput.log").read_text()),
                "models_sha256":{p.name:perf.sha256(p) for p in model.glob("IntegerCoreGsim*")},
                "harness_sha256":perf.sha256(HERE / "harness/core.cpp")}
        report["comparisons"] = perf.compare_measurements(*[row["measurements"] for row in report["profiles"].values()])
        report["same_clock_geomean_speedup"] = math.exp(sum(math.log(r["same_clock_speedup"])
            for r in report["comparisons"]) / len(report["comparisons"]))
        report["status"] = "PASS_SHORT_FUNCTIONAL_AND_IPC"
    except Exception as error:
        report["status"] = "FAIL_SHORT_BATCH"
        report["failure"] = str(error)
        raise
    finally:
        if perf.hardware_sources() != sources:
            report["status"] = "FAIL_INPUT_DRIFT"
        (output / "receipt.json").write_text(json.dumps(report, indent=2)+"\n")
    if report["status"] != "PASS_SHORT_FUNCTIONAL_AND_IPC":
        raise RuntimeError(report["status"])
    for row in report["comparisons"]:
        print(f"A/B {row['name']} RAM={row['memory_latency']} "
            f"cycles {row['baseline_cycles']} -> {row['candidate_cycles']} x{row['same_clock_speedup']:.4f}", flush=True)

if __name__ == "__main__":
    main()
