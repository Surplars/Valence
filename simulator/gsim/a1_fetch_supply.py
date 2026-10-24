#!/usr/bin/env python3
"""One bounded real-module A1 frontend model; byte oracle, not an executing CPU."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import run as common

HERE = Path(__file__).resolve().parent
SERVICE_LAW = {
    "version": 1,
    "tl_first_beat_latency_from_accepted_a": "7 cycles; redirect case 17 cycles",
    "tl_following_beat_latency": 1,
    "pte_latency_from_accepted_request": 3,
    "stalled_a_ready": "cycle modulo 7 not in {1, 2}",
    "stalled_d_offer": "cycle modulo 5 != 2, irrevocable once offered",
    "stalled_pte_ready": "cycle modulo 5 != 1",
    "stalled_consumer_budget": "zero when cycle modulo 23 < 9; otherwise up to two",
    "traffic": "fixed independently generated instruction byte streams and instruction counts; no prefetch",
}
CONFIGURATION = {
    "base": "FpgaNextConfig.Selected.coreParams",
    "rename_lanes": 2,
    "packet_bytes": 8,
    "packet_cache_sets": 16,
    "packet_cache_ways": 2,
    "reservoir_instructions": 4,
    "physical_instruction_cache_lines": 8,
    "common_a1_physical_instruction_cache_lines": 512,
    "physical_instruction_cache_ways": 2,
    "line_bytes": 64,
    "instruction_prefetch": False,
    "itlb_entries": 8,
    "sv39_levels": 3,
    "nonleaf_pte_cache_entries": 4,
    "fabric": "host TL and PTE service, not Common fabric/CDC/ROM/DDR timing",
    "backend": "bounded consumer only, no decode/rename/execute/retirement",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def oracle_only(cxx):
    with tempfile.TemporaryDirectory(prefix="a1-fetch-oracle-") as directory:
        executable = Path(directory) / "oracle"
        subprocess.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined",
                        "-fno-sanitize-recover=all", str(HERE / "a1_fetch_supply/oracle_test.cpp"),
                        "-o", str(executable)], check=True)
        result = subprocess.run([str(executable)], text=True, capture_output=True, timeout=30,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout, end="")
        return result.stdout


def parse(log):
    result = {}
    for line in log.splitlines():
        if not line.startswith("A1_FETCH_SUPPLY "):
            continue
        values = dict(item.split("=", 1) for item in line.split()[1:])
        name = values.pop("scenario")
        assert name not in result, f"duplicate scenario {name}"
        result[name] = {key: int(value) for key, value in values.items()}
        row = result[name]
        for prefix, count in (("raw", 3), ("captured", 3), ("consumed", 3), ("occupancy", 5)):
            assert sum(row[f"{prefix}{i}"] for i in range(count)) == row["work_cycles"]
        assert row["consumed1"] + 2 * row["consumed2"] == row["verified"]
    assert len(result) == 9, f"expected nine distinct completed scenarios, got {len(result)}"
    assert "PASS A1_FETCH_SUPPLY" in log
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-only", action="store_true")
    parser.add_argument("--gsim", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--compare", type=Path, help="prior receipt with the identical fixture/service law")
    args = parser.parse_args()
    cxx, compiler = common.compiler()
    host_log = oracle_only(cxx)
    if args.oracle_only:
        return
    if not args.gsim or not args.tag or not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("hardware run requires --gsim PATH and a safe, fresh --tag")
    gsim = args.gsim.resolve(strict=True)
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh output required"
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/A1FetchSupplyGsim.scala",
        HERE / "a1_fetch_supply.py", HERE / "a1_fetch_supply/driver.cpp",
        HERE / "a1_fetch_supply/oracle.h", HERE / "a1_fetch_supply/oracle_test.cpp", HERE / "run.py"]
    inputs = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    gsim_sha = sha(gsim)
    output = common.test(gsim, cxx, args.tag, "ooo.A1FetchSupplyGsimMain", "A1FetchSupplyGsim",
                         "../a1_fetch_supply/driver.cpp", defines={}, timeout=120)
    scenarios = parse((output / "test.log").read_text())
    controls = []
    for flag, reason in (
        ("--inject-pc", "consumed PC duplicated, skipped, or from old path"),
        ("--inject-data", "instruction differs from independent memory bytes"),
        ("--inject-tval", "fault tval is not first failing required parcel"),
        ("--inject-source", "D without source owner"),
    ):
        result = subprocess.run([str(output / "run"), flag], text=True, capture_output=True,
                                timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        log = result.stdout + result.stderr
        (output / (flag[2:] + ".log")).write_text(log)
        assert result.returncode != 0 and reason in log, (flag, result.returncode, log)
        assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log
        controls.append({"flag": flag, "reason": reason, "exit": result.returncode})
    assert inputs == {str(path.relative_to(common.ROOT)): sha(path) for path in sources}, "sources changed during run"
    assert gsim_sha == sha(gsim), "GSIM executable changed during run"
    comparison = None
    if args.compare:
        prior = json.loads(args.compare.read_text())
        assert prior["configuration"] == CONFIGURATION and prior["serviceLaw"] == SERVICE_LAW
        assert set(prior["scenarios"]) == set(scenarios)
        comparison = {}
        for name, row in scenarios.items():
            old = prior["scenarios"][name]
            for key in ("verified", "faults", "instruction_hash"):
                assert old[key] == row[key], (name, key, "different completed instruction stream")
            traffic_matched = all(old[key] == row[key] for key in ("gets", "dbeats", "get_extent_hash"))
            comparison[name] = {"trafficMatched": traffic_matched, "beforeCycles": old["work_cycles"],
                                "afterCycles": row["work_cycles"],
                                "performanceComparisonQualified": traffic_matched}
    receipt = {
        "status": "PASS_BOUNDED_A1_FRONTEND_SUPPLY_ONLY", "configuration": CONFIGURATION,
        "serviceLaw": SERVICE_LAW, "scenarios": scenarios, "comparison": comparison,
        "sourceSha256": inputs, "gsimSha256": gsim_sha, "compiler": compiler,
        "hostOracle": host_log.strip(), "negativeControls": controls,
        "negativeControlScope": "observation mutations plus independent host ownership negatives, not DUT source mutants",
        "limits": ["Not core IPC, ISA compliance, whole-Common-platform latency, PPA or 300 MHz evidence",
                   "Eight-line physical cache is deliberately smaller than Common A1; no capacity speedup claim",
                   "No predictor training benchmark, SFENCE context-change stress or simultaneous I/D PTW contention",
                   "Two instruction owners are supported by the independent ledger, not implemented by this DUT"],
        "testLogSha256": sha(output / "test.log"),
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS bounded A1 frontend supply and four independent observation negatives; no CPU IPC/physical claim")


if __name__ == "__main__":
    main()
