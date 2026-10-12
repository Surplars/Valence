#!/usr/bin/env python3
"""Explicit optional full-board two-proof-row/two-early-credit profile.

The durable READ rollback and generic defaults retain one row and one credit.
Source preflight is the default; --emit exports native RTL only. Neither is
physical qualification, a board run, or permission to change the service law.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import board_durable_read_prefetch as rollback
import export as exporter

MANIFEST = Path(__file__).with_name("board-dual-proof-credit-profile-v1.json")
MANIFEST_SHA256 = "c9fe9f22561f566a9c6d185b9f0e24f8e526335e5e216e65476c698e43433cbd"
CAPACITIES = ("pendingVirtualStoreProofSlots", "pendingStoreEarlyLoadCredits")


def load_manifest():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("dual proof/credit v1 manifest changed; review and qualification required")
    spec = json.loads(raw)
    rollback.load_manifest()
    if spec["rollback"]["manifest_sha256"] != rollback.MANIFEST_SHA256:
        raise RuntimeError("dual proof/credit rollback manifest changed")
    return spec


def native_options():
    return list(load_manifest()["native_options"])


def _compare(actual, expected, label):
    # Full JSON equality, including numeric/Boolean types and all nested fields.
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise RuntimeError("complete " + label + " differs from dual proof/credit v1")


def _dual_capacity(section):
    for field in CAPACITIES:
        if type(section[field]) is not int or section[field] != 1:
            raise RuntimeError("durable READ rollback must retain one proof row and one early credit")
        section[field] = 2


def expected_constructor():
    """Bridge only the two capacities from the complete current rollback."""
    spec = load_manifest()
    expected = copy.deepcopy(rollback.expected_constructor())
    for section in ("profile", "core"):
        _dual_capacity(expected[section])
    historical = copy.deepcopy(expected)
    for section in ("profile", "core"):
        if historical[section].pop("taggedStoreReturns") is not False:
            raise RuntimeError("historical dual-credit entry must keep tagged returns off")
    _compare(historical, spec["constructor_profile"], "constructor expectation")
    return expected


def expected_fabric():
    """Add the sole historical default on the expected side, then change 1/1 to 2/2."""
    spec = load_manifest()
    expected = copy.deepcopy(rollback.load_manifest()["executed_fabric"])
    if "pendingStoreEarlyLoadCredits" in expected["cpu"]:
        raise RuntimeError("durable READ fabric schema changed; review its explicit default bridge")
    expected["cpu"]["pendingStoreEarlyLoadCredits"] = 1
    _dual_capacity(expected["cpu"])
    _compare(expected, spec["executed_fabric"], "fabric expectation")
    expected["cpu"]["taggedStoreReturns"] = False
    return expected


def compare_constructor(actual):
    _compare(actual, expected_constructor(), "actual constructor")


def compare_fabric(actual):
    _compare(actual, expected_fabric(), "actual fabric")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--print-native-options", action="store_true")
    args = parser.parse_args(argv)
    spec = load_manifest()
    expected_constructor()
    expected_fabric()
    if args.print_native_options:
        if args.output is not None or args.emit:
            parser.error("--print-native-options cannot be combined with --output or --emit")
        print(json.dumps(native_options()))
        return
    if args.output is None:
        parser.error("--output is required")
    options = ["--output", str(args.output), *(o for o in native_options() if o != "--selected")]
    if args.emit:
        options.append("--emit")
    exporter.main(options, expected_profile_sha256=spec["export_profile_sha256"])


if __name__ == "__main__":
    main()
