#!/usr/bin/env python3
"""Expand the reviewed CPU B profile with tri-speed MAC and USER2 RAM download.

Default is read-only preflight; --emit generates native RTL only. USER2 remains
a candidate until the new synthesized netlist passes require_jtag_chain.tcl.
This entry neither runs Vivado nor generates/programs a bitstream.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import board_profile
import export as exporter

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "board-release-profile.json"
MANIFEST_SHA256 = "b9ec8315031d44ae41dd6a3188628f8766adfc67fef991453636cd4eb4857991"


def load_manifest():
    content = MANIFEST.read_bytes()
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("board release manifest changed; review required")
    spec = json.loads(content)
    if spec["cpu_profile"]["sha256"] != board_profile.MANIFEST_SHA256:
        raise RuntimeError("board release CPU profile changed; requalification required")
    board_profile.load_manifest()
    return spec


def native_options():
    spec = load_manifest()
    options = board_profile.native_options(spec["cpu_profile"]["mode"])
    position = options.index(spec["perimeter_options_after"]) + 1
    return options[:position] + spec["perimeter_options"] + options[position:]


def compare_constructor(actual):
    """Complete constructor equality, permitting the single MAC selector leaf.

    JTAG is an FpgaNextSocTop argument, outside FpgaNextConfig; its actual native
    primitive, loader, aperture and arbitration must be audited separately.
    """
    load_manifest()
    expected = copy.deepcopy(json.loads((HERE / "board-performance-constructors.json").read_text())["B"])
    expected["profile"]["experimentalTriSpeedEthernet"] = True
    # Keep the published snapshot frozen; the new optional policies are explicitly OFF.
    expected["profile"]["readPrefetchDirtyRetry"] = False
    expected["cache"]["readPrefetchDirtyRetry"] = False
    expected["profile"]["readPrefetchDemandAdoption"] = False
    expected["cache"]["readPrefetchDemandAdoption"] = False
    expected["profile"].setdefault("registeredPmpRegions", False)
    expected["core"].setdefault("registeredPmpRegions", False)
    expected["profile"].setdefault("publishedPmpChanges", False)
    expected["core"].setdefault("publishedPmpChanges", False)
    for section in ("profile", "core"):
        expected[section]["frozenStoreProofTransport"] = False
        expected[section]["pendingVirtualStoreProof"] = False
        expected[section]["boundHeadStoreOverlap"] = False
        expected[section]["pendingReadyStoreBypass"] = False
        expected[section]["taggedStoreReturns"] = False
        expected[section]["pendingVirtualStoreProofSlots"] = 1
        expected[section]["pendingStoreEarlyLoadCredits"] = 1
    for section in ("profile", "cache"):
        expected[section]["readPrefetchStoreHold"] = False
        expected[section]["durableReadPrefetchCandidate"] = False
        expected[section]["readPrefetchBehindStore"] = False
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise RuntimeError("complete release constructor differs from B plus tri-speed selector")


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
