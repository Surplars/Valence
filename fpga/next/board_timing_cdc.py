#!/usr/bin/env python3
"""Versioned timing/CDC board candidate; defaults to source-only preflight.

This explicit entry selects dirty retry, read-prefetch demand adoption and atomic
PMP publication. It does not promote the candidate to a qualified board release.
--emit exports native RTL only; it never runs Vivado or creates a bitstream.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import board_release
import export as exporter

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "board-timing-cdc-profile-v1.json"
MANIFEST_SHA256 = "f8d871a68a29d506e2303047450a04694f6c08c8532c2df3f2405381b8228610"


def load_manifest():
    content = MANIFEST.read_bytes()
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("timing/CDC v1 manifest changed; review and new qualification required")
    spec = json.loads(content)
    board_release.load_manifest()
    if spec["rollback"]["manifest_sha256"] != board_release.MANIFEST_SHA256:
        raise RuntimeError("timing/CDC rollback manifest changed")
    return spec


def native_options():
    return list(load_manifest()["native_options"])


def expected_constructor():
    """Complete reviewed expectation; this is not an executed-constructor receipt."""
    load_manifest()
    expected = copy.deepcopy(json.loads((HERE / "board-performance-constructors.json").read_text())["B"])
    expected["profile"]["experimentalTriSpeedEthernet"] = True
    for field in ("readPrefetchDirtyRetry", "readPrefetchDemandAdoption"):
        expected["profile"][field] = True
        expected["cache"][field] = True
    expected["profile"]["registeredPmpRegions"] = True
    expected["core"]["registeredPmpRegions"] = True
    return expected


def compare_constructor(actual):
    if actual != expected_constructor():
        raise RuntimeError("actual complete constructor differs from timing/CDC v1")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--emit", action="store_true")
    parser.add_argument("--print-native-options", action="store_true")
    args = parser.parse_args(argv)
    spec = load_manifest()
    if args.print_native_options:
        if args.output is not None or args.emit:
            parser.error("--print-native-options cannot be combined with --output or --emit")
        print(json.dumps(native_options()))
        return
    if args.output is None:
        parser.error("--output is required")
    options = ["--output", str(args.output), *(x for x in native_options() if x != "--selected")]
    if args.emit:
        options.append("--emit")
    exporter.main(options, expected_profile_sha256=spec["export_profile_sha256"])


if __name__ == "__main__":
    main()
