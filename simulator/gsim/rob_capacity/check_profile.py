#!/usr/bin/env python3
"""Compare every actual constructor field against a separately frozen expectation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from backend_capacity_geometry import verify_backend_capacity
from memory_capacity_geometry import verify_memory_geometry
from posted_cpu.verify_model import verify_posted_model


def equal(actual, expected, path="profile"):
    if type(actual) is not type(expected):
        raise ValueError(path + ": JSON type differs")
    if isinstance(expected, dict):
        if set(actual) != set(expected):
            raise ValueError(path + ": complete key set differs")
        for key, value in expected.items():
            equal(actual[key], value, path + "." + key)
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            raise ValueError(path + ": count differs")
        for index, value in enumerate(expected):
            equal(actual[index], value, path + "." + str(index))
    elif actual != expected:
        raise ValueError(path + ": value differs")


def expected_profile(name):
    manifest = json.loads((HERE / "expected-inputs.json").read_text())
    if name not in manifest["profiles"]:
        raise ValueError("unknown frozen capacity profile")
    path = HERE / (name + ".json")
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["profiles"][name]:
        raise ValueError("frozen expectation hash differs")
    return json.loads(path.read_text())


def verify_actual(actual, expected):
    equal(actual["entryProfile"], expected["profile"], "actual.entryProfile")
    equal(actual["expectedCore"], expected["core"], "actual.expectedCore")
    equal(actual["qualificationInherited"], False, "actual.qualificationInherited")
    equal(actual["allActualParametersEqualExpected"], True, "actual.allActualParametersEqualExpected")
    expected_tl = dict(addrWidth=64, dataWidth=64, sourceBits=3, sinkBits=1, sizeBits=3)
    counts = {}
    for key, field, count in (("coreParameters", "core", 6), ("cacheConcurrency", "cache", 3),
                              ("ddrParameters", "ddr", 2)):
        records = actual[key]
        if len(records) != count or len({r["instancePath"] for r in records}) != count:
            raise ValueError(key + ": final module records absent or duplicated")
        for record in records:
            equal(record["values"], expected[field], key + "." + record["instancePath"])
        counts[key] = count
    if not actual["cacheTileLinkParameters"]:
        raise ValueError("actual cache TL parameters absent")
    for record in actual["cacheTileLinkParameters"]:
        equal(record["values"], expected_tl, "actual.cacheTileLinkParameters")
    counts["cacheTileLinkParameters"] = len(actual["cacheTileLinkParameters"])
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--fir", type=Path)
    args = parser.parse_args()
    expected = expected_profile(args.profile)
    equal(json.loads((args.directory / "profile.json").read_text()), expected)
    result = dict(status="PASS_FULL_CAPACITY_PROFILE", profile=args.profile, core_fields=len(expected["core"]))
    actual = args.directory / "actual-parameters.json"
    if actual.exists():
        result["actual_parameter_counts"] = verify_actual(json.loads(actual.read_text()), expected)
    if args.fir:
        fir = args.fir.read_text()
        rob, regs = expected["core"]["robEntries"], expected["core"]["physicalRegs"]
        result["backend"] = verify_backend_capacity(fir, rob, regs)
        result["memory"] = verify_memory_geometry(fir, expected["core"]["memoryEntries"])
        result["posted"] = verify_posted_model(fir, True, rob_entries=rob)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
