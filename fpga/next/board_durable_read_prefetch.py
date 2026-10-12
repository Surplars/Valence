#!/usr/bin/env python3
"""Explicit complete durable READ/ready STORE candidate; source-only by default.

This optional experiment preserves the published rollback and recommended defaults.
--emit exports native RTL only. It does not imply physical qualification.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import board_bound_store_prefetch as rollback
import export as exporter

MANIFEST = Path(__file__).with_name("board-durable-read-prefetch-profile-v1.json")
MANIFEST_SHA256 = "0dbe7ba7360a6314a8f9bf289a7d42cc6c5c68ed94c02cd147e263b24d97210e"


def load_manifest():
    raw = MANIFEST.read_bytes()
    if hashlib.sha256(raw).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("durable READ v1 manifest changed; review and qualification required")
    spec = json.loads(raw)
    rollback.load_manifest()
    if spec["rollback"]["manifest_sha256"] != rollback.MANIFEST_SHA256:
        raise RuntimeError("durable READ rollback manifest changed")
    return spec


def native_options():
    return list(load_manifest()["native_options"])


def expected_constructor():
    """Full executed object, checked against the complete published rollback."""
    spec = load_manifest()
    expected = copy.deepcopy(rollback.expected_constructor())
    for section in ("profile", "core"):
        expected[section]["pendingReadyStoreBypass"] = True
    for section in ("profile", "cache"):
        for key in ("durableReadPrefetchCandidate", "readPrefetchBehindStore"):
            expected[section][key] = True
    historical = copy.deepcopy(expected)
    for section in ("profile", "cache"):
        for field in ("internalLineGrant", "concurrentReadStorePrefetch", "memoryScheduleOverlap"):
            if historical[section].pop(field) is not False:
                raise RuntimeError("historical entry must keep line Grant / dual-origin prefetch off")
    for section in ("profile", "core"):
        if historical[section].pop("taggedStoreReturns") is not False:
            raise RuntimeError("historical optional entry must keep tagged store returns off")
        if historical[section].pop("pendingStoreEarlyLoadCredits") != 1:
            raise RuntimeError("published durable READ profile retains one early-load credit")
    if historical != spec["constructor_profile"]:
        raise RuntimeError("complete durable READ constructor differs from executed reference")
    return expected


def compare_constructor(actual):
    if json.dumps(actual, sort_keys=True) != json.dumps(expected_constructor(), sort_keys=True):
        raise RuntimeError("actual complete constructor differs from durable READ v1")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--print-native-options", action="store_true")
    args = parser.parse_args(argv)
    spec = load_manifest()
    expected_constructor()
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
