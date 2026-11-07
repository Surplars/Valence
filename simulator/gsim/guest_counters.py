#!/usr/bin/env python3
"""Opt-in H basic counters: independent edge/MSU checks and actual-core GSIM execution."""
import argparse
import os
import re
import subprocess

import run as common


PROFILES = (
    ("bank", "BasicCounterBankGsim", "basic_counter_bank.cpp", {}),
    ("system", "GuestCountersSystemGsim", "guest_counters_system.cpp", {}),
    ("absent", "GuestCountersAbsentSystemGsim", "guest_counters_system.cpp", {"GUEST_COUNTERS_ABSENT": 1}),
    ("platform", "GuestCountersPlatformGsim", "guest_counters_platform.cpp", {}),
)
MARKERS = {
    "bank": "BASIC_COUNTER_BANK_PASS", "system": "GUEST_COUNTERS_SYSTEM_PASS",
    "absent": "GUEST_COUNTERS_ABSENT_PASS", "platform": "GUEST_COUNTERS_PLATFORM_PASS",
}
BANK_COVERAGE = {
    "zero_commit_edges": 25, "single_commit_edges": 23, "dual_commit_edges": 6,
    "owner_tag_misses": 7, "owner_index_misses": 7, "delayed_writes": 7,
    "pending_edges": 28, "cycle_wraps": 1, "instret_wraps": 1, "inhibit_transitions": 5,
}
CASE_TRAPS = {"vs": 3, "vs-h-denied": 5, "vu-s-denied": 5, "vs-m-priority": 7}
NEGATIVES = {
    "bank": {
        "cycle": r"BASIC_COUNTER_BANK_FAIL cycle edge oracle edge=[0-9]+",
        "instret": r"BASIC_COUNTER_BANK_FAIL instret edge oracle edge=[0-9]+",
        "owner-tag": r"BASIC_COUNTER_BANK_FAIL inhibit edge oracle edge=[0-9]+",
        "owner-index": r"BASIC_COUNTER_BANK_FAIL inhibit edge oracle edge=[0-9]+",
        "write-precedence": r"BASIC_COUNTER_BANK_FAIL cycle edge oracle edge=[0-9]+",
    },
    "system": {
        "sampled-data": r"GUEST_COUNTERS_FAIL sampled independent CSR data",
        "exception-cause": r"GUEST_COUNTERS_FAIL precise counter access cause",
        "retire-owner": r"GUEST_COUNTERS_FAIL inhibit every edge",
        "denied-side-effect": r"GUEST_COUNTERS_FAIL instret every edge",
    },
    "absent": {"exception-cause": r"GUEST_COUNTERS_FAIL precise counter access cause"},
    "platform": {
        "retired-value": r"FAIL independent retired value",
        "counter-edge": r"FAIL independent cycle edge",
        "fault-count": r"FAIL independent instret edge",
        "trap-cause": r"FAIL independent trap cause",
    },
}


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def clean_text(path):
    raw = path.read_bytes()
    need(all(value >= 32 or value in (9, 10, 13) for value in raw), "nontext control byte in counter evidence")
    text = raw.decode("utf-8")
    need("AddressSanitizer" not in text and "runtime error:" not in text, "sanitizer failure is not counter evidence")
    return text


def number(row, key):
    value = row.get(key, "")
    need(value.isdecimal(), "missing or invalid unsigned counter summary field: " + key)
    return int(value)


def rows_for(text, marker):
    rows = []
    for line in text.splitlines():
        if not line.startswith(marker + " "):
            continue
        pairs = [field.split("=", 1) for field in line.split()[1:]]
        need(all(len(pair) == 2 for pair in pairs), "malformed counter summary")
        row = dict(pairs)
        need(len(row) == len(pairs), "duplicate counter summary field")
        rows.append(row)
    return rows


def check_positive(path, profile):
    text = clean_text(path)
    need("FAIL " not in text, "positive counter execution contains failure")
    rows = rows_for(text, MARKERS[profile])
    if profile == "platform":
        expected = {(case, str(schedule)) for case in CASE_TRAPS for schedule in (1, 2)}
        keys = [(row.get("case"), row.get("schedule")) for row in rows]
        need(len(keys) == len(expected) and set(keys) == expected, "expected every counter platform case and schedule exactly once")
        for row in rows:
            need(all(number(row, key) > 0 for key in ("cycles", "activeCycles", "commits", "checks", "dual", "commitHolds")),
                 "counter platform requires positive execution and backpressure coverage")
            need(number(row, "cycles") >= number(row, "activeCycles"), "counter active cycles exceed total edges")
            need(number(row, "compressed") >= 10 and number(row, "writeHolds") == 1, "counter C/write-hold coverage is incomplete")
            need(number(row, "traps") == CASE_TRAPS[row["case"]], "wrong precise counter trap count")
            for key in ("cycle", "instret", "inhibit", "terminalFetchOwners"):
                number(row, key)
            need(number(row, "inhibit") in (0, 1, 4, 5), "counter inhibit contains unsupported bits")
            owners = []
            for key in ("accepted", "returned"):
                parts = row.get(key, "").split(",")
                need(len(parts) == 2 and all(part.isdecimal() for part in parts), "malformed physical counter owner totals")
                owners.append([int(part) for part in parts])
            accepted, returned = owners
            need(accepted[0] == returned[0] == CASE_TRAPS[row["case"]] and
                 accepted[1] >= returned[1] > 0 and
                 accepted[1] - returned[1] == number(row, "terminalFetchOwners"), "counter physical ownership does not drain or balance")
        need(text.splitlines().count("GUEST_COUNTERS_ALL_PASS cases=4 runs=8") == 1,
             "expected one complete counter platform marker")
        return
    need(len(rows) == 1, "expected one complete counter component marker")
    row = rows[0]
    need(number(row, "edges") > 0 and number(row, "checks") > 0, "empty counter component execution")
    if profile == "bank":
        need(all(number(row, key) == value for key, value in BANK_COVERAGE.items()), "counter bank coverage differs from directed contract")
        need(number(row, "edges") == 56 and number(row, "checks") == 165, "counter bank edge oracle is incomplete")
        return
    need(number(row, "commands") > 0, "empty counter MSU command stream")
    present = profile == "system"
    expected = {"permission_cases": 80, "permission_cy": 40, "permission_ir": 40,
                **{"permission_" + mode: 16 for mode in ("M", "HS", "U", "VS", "VU")},
                **{"permission_mask" + str(mask): 10 for mask in range(8)}}
    need(all(number(row, key) == (value if present else 0) for key, value in expected.items()), "counter permission matrix is incomplete")
    need(number(row, "absence_cases") == (0 if present else 23), "counter absence proof is incomplete")


def check_negative(path, profile, name, returncode):
    text = clean_text(path)
    need(returncode == 1, "counter negative must exit exactly one")
    need(MARKERS[profile] not in text and "GUEST_COUNTERS_ALL_PASS" not in text, "counter negative unexpectedly completed successfully")
    lines = text.rstrip().splitlines()
    need(lines and re.fullmatch(NEGATIVES[profile][name], lines[-1]), "counter negative did not reach its named independent oracle")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    for profile, model, driver, defines in PROFILES:
        output = common.test(gsim, cxx, "guest-counters/" + profile, "ooo." + model + "Main", model, driver,
                             defines=defines, cxx_flags=("-fbracket-depth=4096",), timeout=600,
                             mill_module="IonSoC.guestCounters")
        check_positive(output / "test.log", profile)
        for name in NEGATIVES[profile]:
            path = output / ("negative-" + name + ".log")
            with path.open("w") as log:
                result = subprocess.run([str(output / "run"), "--negative-control=" + name], cwd=common.ROOT,
                                        stdout=log, stderr=subprocess.STDOUT, env=env, timeout=600)
            check_negative(path, profile, name, result.returncode)
    print("GUEST_COUNTERS_STANDARD_PASS")


if __name__ == "__main__":
    main()
