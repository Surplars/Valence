#!/usr/bin/env python3
"""One short batch: arithmetic/PMP, AXI-Lite, real two-issue CPU A/B. No CAD."""
import argparse
import json
import os
import re
from run import BUILD, HERE, run, setup, test
from control_stage import core_payloads, negative, reference
from throughput_perf import (DEFINES, EXPECTED_KEYS, compare_measurements,
                             hardware_sources, parse_measurements, sha256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("invalid tag")
    name = "ethernet-stage-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    sources = hardware_sources()
    report = {"status": "running", "issue_width": 2, "profiles": {},
              "hardware_source_sha256": sources,
              "scope": "short GSIM; no independent-clock simulation, Ethernet packets or board qualification",
              "routed_timing_verified": False, "on_board_verified": False}
    receipt = output / "receipt.json"
    try:
        gsim, cxx = setup(False)
        for stem, main, top, harness, parameters, anchor in (
            ("arithmetic", "ooo.TimingArithmeticGsimMain", "TimingArithmeticGsim",
             "timing_arithmetic.cpp", (), "timing arithmetic independent oracle mismatch"),
            ("axi-lite", "ooo.RegisterAxiLiteGsimMain", "RegisterAxiLiteGsim",
             "register_axi_lite.cpp", (), "AXI register independent oracle mismatch"),
            ("pmp", "ooo.PmpCheckerGsimMain", "PmpCheckerGsim",
             "pmp_checker.cpp", ("packet", "word-span", "balanced"), "PMP oracle mismatch"),
        ):
            model = test(gsim, cxx, name + "/" + stem, main, top, harness,
                         parameters=parameters, defines={})
            negative(model / "run", (), anchor, model / "negative.log")
            report[stem] = {"status": "passed", "model_fir_sha256": sha256(model / (top + ".fir")),
                            "harness_sha256": sha256(HERE / "harness" / harness)}
        ref = reference()
        payloads = core_payloads(output)
        report["reference_sha256"] = sha256(ref)
        report["harness_sha256"] = sha256(HERE / "harness/core.cpp")
        env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
        keys = EXPECTED_KEYS | {("throughput_hint_alias_loop", 1)}
        for profile in ("staged-gmac-ready", "staged-ethernet"):
            model = test(gsim, cxx, name + "/" + profile, "ooo.ThroughputPerfGsimMain",
                         "IntegerCoreGsim", "core.cpp", parameters=(profile,),
                         runtime_args=(ref, *payloads, "--throughput-short"),
                         defines={**DEFINES, "REGISTERED_FETCH_PACKET": 1, "FETCH_HINT_ALIAS_BENCH": 1},
                         timeout=180, run_log="throughput.log")
            for mode in ("--timing-smoke", "--pipeline-recovery"):
                run([model / "run", ref, *payloads, mode], env=env,
                    log=model / (mode[2:] + ".log"), timeout=180)
            recovery = (model / "pipeline-recovery.log").read_text()
            witnesses = re.search(r"GSIM pipeline recovery \+ NEMU: PASS .*"
                                  r"slot0HeldLane1Progress=(\d+) olderLane0BranchResolution=(\d+) aluForwardingHits=(\d+)", recovery)
            if not witnesses or not all(int(v) > 0 for v in witnesses.groups()):
                raise RuntimeError("pipeline recovery witnesses missing")
            negative(model / "run", (ref, *payloads), "NEMU register mismatch", model / "negative.log")
            text = (model / "throughput.log").read_text()
            print(text, end="", flush=True)
            report["profiles"][profile] = {"status": "passed", "model_directory": str(model),
                "model_fir_sha256": sha256(model / "IntegerCoreGsim.fir"),
                "executable_sha256": sha256(model / "run"),
                "measurements": parse_measurements(text, expected_programs=13, expected_keys=keys),
                "recovery_witnesses": list(map(int, witnesses.groups()))}
        report["comparisons"] = compare_measurements(*(report["profiles"][p]["measurements"]
            for p in ("staged-gmac-ready", "staged-ethernet")))
        report["status"] = "passed"
    except BaseException:
        report["status"] = "failed"
        raise
    finally:
        changed = hardware_sources() != sources
        if changed:
            report["status"] = "failed"
            report["failure"] = "hardware source changed during verification"
        receipt.write_text(json.dumps(report, indent=2) + "\n")
        if changed:
            raise RuntimeError(report["failure"])
    print(f"ETHERNET_STAGE_PASS receipt={receipt}", flush=True)


if __name__ == "__main__":
    main()
