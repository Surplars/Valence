#!/usr/bin/env python3
"""Versioned exact raw-PMP change publication candidate; source-only by default.

This explicit entry adds published raw PMP changes to timing/CDC v1. Matched
CPU traffic and focused PMP boundaries pass; physical qualification remains open.
--emit exports native RTL only; it never runs Vivado or creates a bitstream.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import board_timing_cdc
import export as exporter

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "board-pmp-publication-profile-v1.json"
MANIFEST_SHA256 = "7e12930ef8c787532c5a3ee8712fc8f639f4a3dff20d80d343cf11a0f024216c"


def load_manifest():
    content = MANIFEST.read_bytes()
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("PMP publication v1 manifest changed; review and new qualification required")
    spec = json.loads(content)
    board_timing_cdc.load_manifest()
    if spec["rollback"]["manifest_sha256"] != board_timing_cdc.MANIFEST_SHA256:
        raise RuntimeError("PMP publication rollback manifest changed")
    return spec


def native_options():
    return list(load_manifest()["native_options"])


def expected_constructor():
    """Complete reviewed expectation; this is not an executed-constructor receipt."""
    load_manifest()
    expected = copy.deepcopy(board_timing_cdc.expected_constructor())
    expected["profile"]["publishedPmpChanges"] = True
    expected["core"]["publishedPmpChanges"] = True
    return expected


def compare_constructor(actual):
    if json.dumps(actual, sort_keys=True) != json.dumps(expected_constructor(), sort_keys=True):
        raise RuntimeError("actual complete constructor differs from PMP publication v1")


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
