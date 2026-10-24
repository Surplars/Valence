#!/usr/bin/env python3
"""A2 two-owner fetch: unchanged byte oracle, explicit specialization control and matched warm ROI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import a1_fetch_supply as supply
import run as common

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def negative(executable, output, flag, reason, marker=None):
    result = subprocess.run([str(executable), flag], capture_output=True, text=True, timeout=30,
                            env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    log = result.stdout + result.stderr
    (output / (flag[2:] + ".log")).write_text(log)
    assert result.returncode != 0 and reason in log and (not marker or marker in log), (flag, log)
    assert "ERROR: AddressSanitizer" not in log and "runtime error:" not in log, log
    return {"flag": flag, "exit": result.returncode, "reason": reason}


def parse_warm(log):
    rows = {}
    for line in log.splitlines():
        if line.startswith("A1_FETCH_SUPPLY "):
            row = dict(item.split("=", 1) for item in line.split()[1:])
            name = row.pop("scenario")
            assert name not in rows
            rows[name] = {k: int(v) for k, v in row.items()}
    assert len(rows) == 6 and "PASS A2_WARM_SUPPLY" in log
    for name, row in rows.items():
        if not name.startswith("warmup_"):
            assert row["gets"] == row["dbeats"] == row["walks"] == row["pte_reads"] == 0
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gsim", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    args = parser.parse_args()
    assert re.fullmatch(r"[A-Za-z0-9_-]+", args.tag)
    output = common.BUILD / args.tag
    assert not output.exists(), "fresh output required"
    gsim = args.gsim.resolve(strict=True)
    cxx, compiler = common.compiler()
    baseline = json.loads(args.baseline.read_text())
    sources = sorted((common.ROOT / "src/main/scala").rglob("*.scala")) + [
        common.ROOT / "src/test/scala/ooo/A1FetchSupplyGsim.scala",
        common.ROOT / "src/test/scala/ooo/A2FetchConfigurationSpec.scala",
        common.ROOT / "src/test/scala/ooo/InstructionPermissionGsim.scala",
        common.ROOT / "src/test/scala/ooo/FetchCompletionLedgerGsim.scala",
        common.ROOT / "src/test/scala/ooo/FetchDemandOwnersGsim.scala",
        HERE / "a2_fetch.py", HERE / "a1_fetch_supply.py", HERE / "a1_fetch_supply/driver.cpp",
        HERE / "a1_fetch_supply/oracle.h", HERE / "a1_fetch_supply/oracle_test.cpp",
        HERE / "harness/instruction_permission.cpp", HERE / "run.py",
    ] + sorted((HERE / "a2_fetch").glob("*.cpp"))
    inputs = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    gsim_sha = sha(gsim)
    host = supply.oracle_only(cxx)
    controls, checks, models = [], [], {}
    for name, main, top, driver, negatives, defines in (
        ("owners", "ooo.FetchDemandOwnersGsimMain", "FetchDemandOwnersGsim", "owners.cpp", [
            ("--unowned", "fetch response has no accepted demand owner", "INJECT unowned"),
            ("--inject-held", "independent held demand payload mismatch", "INJECT held")], {}),
        ("ledger", "ooo.FetchCompletionLedgerGsimMain", "FetchCompletionLedgerGsim", "ledger.cpp", [
            ("--wrong-generation", "fetch completion generation mismatch", "INJECT generation"),
            ("--duplicate", "fetch completion duplicated a terminal owner", "INJECT duplicate"),
            ("--unowned", "fetch completion has no reserved global owner", "INJECT unowned"),
            ("--inject-result", "independent ordered ledger result mismatch", "INJECT result")], {}),
        ("engine", "ooo.PipelinedInstructionTranslationGsimMain", "InstructionPermissionGsim", "engine.cpp", [
            ("--inject-mismatch", "independent two-owner ordered response mismatch", None),
            ("--unowned-physical", "physical fetch response has no route owner", "INJECT unowned physical")],
            {"PACKET_WORDS": 2, "RETIMED_PERMISSIONS": 1, "ALIGNED_PACKET": 1}),
    ):
        model = common.test(gsim, cxx, f"{args.tag}/{name}", main, top, f"../a2_fetch/{driver}",
                            defines=defines, timeout=30)
        checks.append({"name": name, "log": (model / "test.log").read_text().strip()})
        for flag, reason, marker in negatives:
            controls.append({"model": name, **negative(model / "run", model, flag, reason, marker)})
    for label, slots, aligned in (("original", 1, False), ("aligned-control", 1, True), ("two-owner", 2, True)):
        model = common.test(gsim, cxx, f"{args.tag}/{label}", "ooo.A2FetchSupplyGsimMain", "A1FetchSupplyGsim",
                            "../a1_fetch_supply/driver.cpp", parameters=(str(slots), str(aligned).lower()),
                            defines={}, timeout=120)
        rows = supply.parse((model / "test.log").read_text())
        if label != "two-owner":
            assert rows == baseline["scenarios"], (label, "default or aligned specialization changed a baseline field")
        else:
            assert max(row["vmax_inflight"] for row in rows.values()) == 2, "two-owner pipeline was not active"
            for case, row in rows.items():
                for key in ("verified", "faults", "instruction_hash"):
                    assert row[key] == baseline["scenarios"][case][key], (case, key, "architectural byte stream changed")
        for flag, reason in (
            ("--inject-pc", "consumed PC duplicated, skipped, or from old path"),
            ("--inject-data", "instruction differs from independent memory bytes"),
            ("--inject-tval", "fault tval is not first failing required parcel"),
            ("--inject-source", "D without source owner"),
        ):
            if label == "two-owner":
                controls.append({"model": label, **negative(model / "run", model, flag, reason)})
        # Reuse this very generated model for the retained-cache witness. No
        # second elaboration, no synthetic data injection or shorter service.
        warm = model / "run-warm"
        common.run([cxx, "-std=c++20", "-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                    "-I" + str(model), *sorted(model.glob("A1FetchSupplyGsim[0-9]*.cpp")),
                    HERE / "a2_fetch/warm.cpp", "-ldl", "-o", warm], log=model / "warm-compile.log")
        common.run([warm], log=model / "warm.log", timeout=120,
                   env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        warm_rows = parse_warm((model / "warm.log").read_text())
        models[label] = {"slots": slots, "alignedSinglePage": aligned, "scenarios": rows, "warm": warm_rows}
    assert models["original"]["warm"] == models["aligned-control"]["warm"], "specialization altered warm supply"
    comparisons = {}
    for case, after in models["two-owner"]["scenarios"].items():
        before = models["aligned-control"]["scenarios"][case]
        matched = all(after[k] == before[k] for k in ("gets", "dbeats", "get_extent_hash"))
        comparisons[case] = {"beforeCycles": before["work_cycles"], "afterCycles": after["work_cycles"],
                             "deltaCycles": after["work_cycles"] - before["work_cycles"],
                             "matchedExternalTraffic": matched,
                             "beforeVirtualPacketBytes": 8 * before["vrequests"],
                             "afterVirtualPacketBytes": 8 * after["vrequests"],
                             "beforeGets": before["gets"], "afterGets": after["gets"],
                             "beforeBeats": before["dbeats"], "afterBeats": after["dbeats"]}
    warm_comparisons = {}
    for case, after in models["two-owner"]["warm"].items():
        if case.startswith("warmup_"):
            continue
        before = models["aligned-control"]["warm"][case]
        assert all(before[k] == after[k] for k in ("verified", "faults", "instruction_hash", "gets", "dbeats", "get_extent_hash"))
        assert after["work_cycles"] < before["work_cycles"], (case, "local concurrency did not improve whole-front supply")
        warm_comparisons[case] = {"beforeCycles": before["work_cycles"], "afterCycles": after["work_cycles"],
                                  "beforeVirtualPacketBytes": 8 * before["vrequests"],
                                  "afterVirtualPacketBytes": 8 * after["vrequests"], "tlGets": 0}
    assert inputs == {str(p.relative_to(common.ROOT)): sha(p) for p in sources}, "source drift during A2 run"
    assert gsim_sha == sha(gsim)
    receipt = {"status": "PASS_A2_TWO_OWNER_FETCH_WITH_MATCHED_WARM_SUPPLY", "sourceSha256": inputs,
               "gsimSha256": gsim_sha, "compiler": compiler, "hostOracle": host.strip(),
               "serviceLaw": supply.SERVICE_LAW, "unitChecks": checks, "negativeControls": controls,
               "models": models, "comparison": comparisons, "warmComparison": warm_comparisons,
               "limits": ["No core IPC/300MHz/PPA claim; real CPU retirement is a separate root-coordinated check",
                          "Two owners with unchanged current/current+8 demand range do not provide final 8B/cycle",
                          "Changed Get extent/count rows are not matched-external-traffic speed claims",
                          "Packet-byte counts include fault-only/denied transport slots, not necessarily actual memory reads",
                          "Native ordered untagged physical replies assume exactly once; TL source oracle remains independent"]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("PASS A2 real frontend owner pipeline; retained-cache zero-TL-traffic supply improved")


if __name__ == "__main__":
    main()
