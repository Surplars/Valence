#!/usr/bin/env python3
"""Dual-FS component preparation; actual-core H+FP remains disabled."""
import argparse
import json
import os
import re
import subprocess

import run as common


PROFILES = (
    ("dual", "ooo.DualFsPreparationGsimMain", "DualFsPreparationGsim", "dual_fs_preparation.cpp"),
    ("host", "ooo.FloatingPointStateGsimMain", "FloatingPointStateGsim", "floating_point_state.cpp"),
)
MARKERS = {"dual": "DUAL_FS_PREPARATION_PASS", "host": "FP_STATE_PASS"}
EXACT = {
    "schema": 1, "permission_rows": 32, "command_denials": 11,
    "csr_matrix_accesses": 192, "csr_matrix_denials": 66, "host_off": 8, "guest_off": 3,
    "live_owner_changes": 2, "fpr_registers": 32, "forwarding_checks": 64,
    "older_commit_younger_flush": 32, "image_saves": 5, "image_restores": 5,
    "initial_retention_contexts": 2, "status_alias_pairs": 16, "rounding_denials": 6,
}
MINIMUM = {
    "cycles": 1, "issued": 1, "retired": 1, "producer_requests": 1,
    "stale_results": 41, "held_completions": 51, "wrong_retire_tags": 31,
    "wrong_retire_indices": 31, "denied_head_retires": 31, "blocked_context": 31,
    "csr_host_events": 1, "csr_guest_events": 1, "retire_host_events": 1,
    "retire_guest_events": 1, "fault_retirements": 1,
}
NEGATIVES = {
    "dual": {
        "host-permission": r"DUAL_FS_CHECK\[host_permission\]: FP request with host FS Off",
        "guest-permission": r"DUAL_FS_CHECK\[guest_permission\]: FP request with guest FS Off",
        "status-target": r"DUAL_FS_CHECK\[status_target\]: guest sstatus changed host FS",
        "guest-dirty": r"DUAL_FS_CHECK\[guest_dirty\]: guest mutation did not dirty VS FS",
        "fault-mutation": r"DUAL_FS_CHECK\[fault_mutation\]: fault retirement emitted mutation",
    },
    "host": {"inject-mismatch": r"FP oracle mismatch: fcsr commit state at cycle 100"},
}


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def clean_text(path):
    raw = path.read_bytes()
    need(all(value >= 32 or value in (9, 10, 13) for value in raw), "nontext control byte in state evidence")
    text = raw.decode("utf-8")
    need("AddressSanitizer" not in text and "runtime error:" not in text,
         "sanitizer failure is not state evidence")
    return text


def unique_object(pairs):
    result = dict(pairs)
    need(len(result) == len(pairs), "duplicate state summary field")
    return result


def integer(row, key):
    value = row.get(key)
    need(type(value) is int and value >= 0, "missing or invalid unsigned state field: " + key)
    return value


def check_positive(path, profile):
    text = clean_text(path)
    need("DUAL_FS_CHECK[" not in text and "FP oracle mismatch:" not in text and "FAIL " not in text,
         "positive state execution contains failure")
    marker = MARKERS[profile]
    lines = [line[len(marker) + 1:] for line in text.splitlines() if line.startswith(marker + " ")]
    need(len(lines) == 1, "expected one complete state summary")
    need(text.rstrip().splitlines()[-1] == marker + " " + lines[0], "state summary must be final")
    if profile == "dual":
        row = json.loads(lines[0], object_pairs_hook=unique_object)
        need(isinstance(row, dict), "state summary must be an object")
        need(all(integer(row, key) == value for key, value in EXACT.items()), "incomplete dual-FS directed coverage")
        need(all(integer(row, key) >= value for key, value in MINIMUM.items()), "missing dual-FS boundary coverage")
        need(row.get("evidence") == "component_only" and row.get("synthetic_results") is True and
             row.get("guest_fd_execution") is False, "state evidence must retain component-only scope")
        traces = [json.loads(line[len("DUAL_FS_TRACE "):], object_pairs_hook=unique_object)
                  for line in text.splitlines() if line.startswith("DUAL_FS_TRACE ")]
        need(0 < len(traces) == integer(row, "cycles") <= 20000, "missing or excessive raw state trace")
        need(all(isinstance(trace, dict) and type(trace.get("cycle")) is int and trace["cycle"] == index and
                 isinstance(trace.get("in"), dict) and isinstance(trace.get("out"), dict)
                 for index, trace in enumerate(traces)), "nonsequential or malformed raw state trace")
        return row
    pairs = [field.split("=", 1) for field in lines[0].split()]
    need(all(len(pair) == 2 for pair in pairs), "malformed host-state summary")
    row = unique_object(pairs)
    for key, minimum in {"cycles": 1, "issued": 451, "retired": 401, "stale": 401,
                         "blocked_context": 601, "box_canonicalized": 51,
                         "flush_send": 6, "flush_wait": 6, "flush_done": 6}.items():
        need(row.get(key, "").isdecimal() and int(row[key]) >= minimum, "incomplete host-state coverage: " + key)
    for key, value in {"illegal": "28", "reset_boundaries": "4", "simultaneous_response_flush": "1",
                       "immediate_forwarding": "32x3", "older_commit_younger_flush": "32"}.items():
        need(row.get(key) == value, "wrong host-state directed coverage: " + key)
    return row


def check_negative(path, profile, name, returncode):
    text = clean_text(path)
    need(returncode == 1, "state negative must exit exactly one")
    need(all(marker not in text for marker in MARKERS.values()), "state negative unexpectedly passed")
    need(profile != "dual" or "DUAL_FS_TRACE " in text, "dual-FS negative lacks raw execution trace")
    lines = text.rstrip().splitlines()
    need(lines and re.fullmatch(NEGATIVES[profile][name], lines[-1]),
         "state negative did not reach its named independent oracle")


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", "UBSAN_OPTIONS": "halt_on_error=1"}
    for profile, main, model, driver in PROFILES:
        output = common.test(gsim, cxx, "dual-fs-preparation/" + profile, main, model, driver,
                             cxx_flags=("-fbracket-depth=4096",), timeout=120,
                             mill_module="IonSoC.dualFsPreparation")
        check_positive(output / "test.log", profile)
        for name in NEGATIVES[profile]:
            argument = "--negative=" + name if profile == "dual" else "--inject-mismatch"
            path = output / ("negative-" + name + ".log")
            with path.open("w") as log:
                result = subprocess.run([str(output / "run"), argument], cwd=common.ROOT,
                                        stdout=log, stderr=subprocess.STDOUT, env=env, timeout=120)
            check_negative(path, profile, name, result.returncode)
    print("DUAL_FS_PREPARATION_STANDARD_PASS")


if __name__ == "__main__":
    main()
