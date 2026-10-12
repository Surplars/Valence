#!/usr/bin/env python3
"""Explicit optional bound-store/prefetch combination; source-only by default.

Keeps the complete published PMP board and enables four reviewed policies with
one proof slot. Bounded compact-source gates pass; physical qualification remains open.
--emit exports native RTL only; it never runs Vivado or creates a bitstream.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import board_pmp_publication
import export as exporter

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "board-bound-store-prefetch-profile-v1.json"
MANIFEST_SHA256 = "6f098035333e6a0d9ccf035df0a4f5da23fdd67e4aa60dfa3c305522e5ae8708"


def load_manifest():
    content = MANIFEST.read_bytes()
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("bound-store/prefetch v1 manifest changed; review and new qualification required")
    spec = json.loads(content)
    board_pmp_publication.load_manifest()
    if spec["rollback"]["manifest_sha256"] != board_pmp_publication.MANIFEST_SHA256:
        raise RuntimeError("bound-store/prefetch rollback manifest changed")
    return spec


def native_options():
    return list(load_manifest()["native_options"])


def expected_constructor():
    """Complete reviewed expectation; this is not an executed-constructor receipt."""
    load_manifest()
    expected = copy.deepcopy(board_pmp_publication.expected_constructor())
    for section in ("profile", "core"):
        for field in ("frozenStoreProofTransport", "pendingVirtualStoreProof", "boundHeadStoreOverlap"):
            expected[section][field] = True
        expected[section]["pendingVirtualStoreProofSlots"] = 1
        expected[section]["pendingStoreEarlyLoadCredits"] = 1
    for section in ("profile", "cache"):
        expected[section]["readPrefetchStoreHold"] = True
    spec = load_manifest()
    # The archived 53/148-field reference stays byte-frozen. The only later
    # constructor fields are explicitly default in both complete products.
    historical = copy.deepcopy(expected)
    for section in ("profile", "cache"):
        for field in ("internalLineGrant", "concurrentReadStorePrefetch", "memoryScheduleOverlap"):
            if historical[section].pop(field) is not False:
                raise RuntimeError("historical entry must keep line Grant / dual-origin prefetch off")
    for section in ("profile", "core"):
        if historical[section].pop("taggedStoreReturns") is not False:
            raise RuntimeError("historical optional entry must keep tagged store returns off")
        if historical[section].pop("pendingStoreEarlyLoadCredits") != 1:
            raise RuntimeError("historical optional entry must retain one early-load credit")
        if historical[section].pop("pendingReadyStoreBypass") is not False:
            raise RuntimeError("historical optional entry must keep ready-store bypass off")
    for section in ("profile", "cache"):
        for field in ("durableReadPrefetchCandidate", "readPrefetchBehindStore"):
            if historical[section].pop(field) is not False:
                raise RuntimeError("historical optional entry must keep durable READ policies off")
    if historical != spec["constructor_profile"]:
        raise RuntimeError("complete optional constructor differs from executed historical reference")
    return expected


def compare_constructor(actual):
    if json.dumps(actual, sort_keys=True) != json.dumps(expected_constructor(), sort_keys=True):
        raise RuntimeError("actual complete constructor differs from bound-store/prefetch v1")


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
