#!/usr/bin/env python3
"""R1 static circular payload: independent storage/packet checks and exact P1 two-owner supply."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

import a1_fetch_supply as supply
import a2_fetch
import fetch_owner_context as owner_context
import run as common

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline", type=Path, required=True, help="retained P1 frontend leaf receipt")
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh evidence directory required"
    baseline = json.loads(args.baseline.read_text())
    assert baseline["status"] == "PASS_P1_OWNER_CONTRACT_AND_EXACT_A2_SUPPLY"
    reference = baseline["models"]["two-owner"]
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/A1FetchSupplyGsim.scala",
        common.ROOT / "src/test/scala/ooo/CircularFetchStorageGsim.scala",
        common.ROOT / "src/test/scala/ooo/CircularFetchStorageSpec.scala",
        common.ROOT / "src/test/scala/ooo/RegisteredFetchPacketGsim.scala",
        HERE / "r1_fetch.py", HERE / "run.py", HERE / "a1_fetch_supply.py", HERE / "a2_fetch.py",
        HERE / "fetch_owner_context.py", HERE / "circular_fetch_storage/driver.cpp",
        HERE / "harness/registered_fetch_packet.cpp", HERE / "a1_fetch_supply/driver.cpp",
        HERE / "a1_fetch_supply/oracle.h", HERE / "a1_fetch_supply/oracle_test.cpp", HERE / "a2_fetch/warm.cpp",
    ]
    inputs = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    tool_hash = sha(gsim)
    host_oracle = supply.oracle_only(cxx)
    negatives = []
    storage = common.test(gsim, cxx, f"{args.tag}/storage", "ooo.CircularFetchStorageGsimMain",
                          "CircularFetchStorageGsim", "../circular_fetch_storage/driver.cpp",
                          defines={}, timeout=60)
    storage_log = (storage / "test.log").read_text()
    assert storage_log.count("PASS CIRCULAR_FETCH_STORAGE ") == 1
    for flag, diagnostic, marker in (
        ("--inject-read-slot", "CIRCULAR_FETCH_STORAGE_ORACLE read-slot pc mismatch", "INJECT read-slot"),
        ("--inject-next-pc", "CIRCULAR_FETCH_STORAGE_ORACLE next-pc mismatch", "INJECT next-pc"),
    ):
        negatives.append({"model": "storage", **owner_context.negative(
            storage / "run", storage, flag, diagnostic, marker)})

    # One small model contains both implementations, observed every cycle. The
    # existing unchanged event-deque/ISA host remains the independent oracle.
    packet = common.test(gsim, cxx, f"{args.tag}/paired-packet", "ooo.RegisteredFetchPacketGsimMain",
                         "RegisteredFetchPacketGsim", "registered_fetch_packet.cpp",
                         parameters=("2", "parallel-validation", "hints32", "split-cursor", "banked-hints",
                                     "circular-payload", "compare-legacy"),
                         defines={"FETCH_WIDTH": 2, "COMPRESSED": 1, "HINT_ENTRIES": 32}, timeout=60)
    packet_log = (packet / "test.log").read_text()
    assert "GSIM registered fetch packet: PASS width=2" in packet_log
    assert "module CircularFetchInstructionStorage" in (packet / "RegisteredFetchPacketGsim.fir").read_text()
    negatives.append({"model": "paired-packet", **a2_fetch.negative(packet / "run", packet,
        "--inject-mismatch", "fetch packet oracle mismatch")})

    frontend = common.test(gsim, cxx, f"{args.tag}/two-owner", "ooo.A2FetchSupplyGsimMain", "A1FetchSupplyGsim",
                           "../a1_fetch_supply/driver.cpp", parameters=("2", "true", "--circular-fetch-payload"),
                           defines={}, timeout=120)
    fir = frontend / "A1FetchSupplyGsim.fir"
    assert "module CircularFetchInstructionStorage" in fir.read_text(), "R1 was not connected to real supply chain"
    rows = supply.parse((frontend / "test.log").read_text())
    assert rows == reference["scenarios"], "R1 changed a P1 two-owner cold supply field"
    for flag, diagnostic in (
        ("--inject-pc", "consumed PC duplicated, skipped, or from old path"),
        ("--inject-data", "instruction differs from independent memory bytes"),
        ("--inject-tval", "fault tval is not first failing required parcel"),
        ("--inject-source", "D without source owner"),
    ):
        negatives.append({"model": "two-owner", **a2_fetch.negative(frontend / "run", frontend, flag, diagnostic)})
    warm = frontend / "run-warm"
    common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                "-I" + str(frontend), *sorted(frontend.glob("A1FetchSupplyGsim[0-9]*.cpp")),
                HERE / "a2_fetch/warm.cpp", "-ldl", "-o", warm], log=frontend / "warm-compile.log")
    common.run([warm], log=frontend / "warm.log", timeout=120,
               env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    warm_rows = a2_fetch.parse_warm((frontend / "warm.log").read_text())
    assert warm_rows == reference["warm"], "R1 changed a P1 two-owner warm supply field"
    fields = sum(len(row) for row in rows.values()) + sum(len(row) for row in warm_rows.values())
    assert fields == 570, "unexpected cold/warm metric schema"
    assert inputs == {str(path.relative_to(common.ROOT)): sha(path) for path in sources}, "R1 source drift"
    assert tool_hash == sha(gsim), "R1 tool drift"
    receipt = {
        "status": "PASS_R1_CIRCULAR_STORAGE_AND_EXACT_P1_TWO_OWNER_SUPPLY",
        "sourceSha256": inputs, "gsimSha256": tool_hash, "compiler": compiler,
        "baselineSha256": sha(args.baseline), "hostOracle": host_oracle.strip(),
        "unitChecks": {"storage": storage_log.strip(), "pairedPacket": packet_log.strip()},
        "negativeControls": negatives, "models": {"two-owner": {"scenarios": rows, "warm": warm_rows}},
        "exactComparedFields": fields, "serviceLaw": supply.SERVICE_LAW,
        "frontendFirSha256": sha(fir), "frontendExecutableSha256": sha(frontend / "run"),
        "contract": {"capacityInstructions": 4, "inputWidth": 2, "outputWidth": 2,
                     "minimumLatencyCycles": 1, "initiationIntervalCycles": 1,
                     "credit": "old occupancy only, no consumed-credit bypass", "extraPipelineCycles": 0},
        "limits": ["No new stage, no wider demand range, no cache/translation/physical owner change",
                   "Two new full-payload bank/read-selection paths trade against removed late compaction writes",
                   "No measured Fmax, area, synthesis complexity, STA, CDC or board claim",
                   "Only two-owner frontend rebuilt; original/single-page profiles not rerun",
                   "Actual R1/M2/combined CPU checks are separately coordinated, not implied by this receipt"],
    }
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"PASS R1 circular storage and exact P1 two-owner supply: {fields} metric fields")


if __name__ == "__main__":
    main()
