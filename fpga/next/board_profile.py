#!/usr/bin/env python3
"""One reviewed A/B argument source for native and CPU-path qualification.

A is the current posted-performance-v3 baseline. B retains its capacities and
adds the eight-setting bandwidth batch. Neither selection identifies the image
currently programmed on a board. Native independent-clock/physical validation
is separate from the GSIM CPU/cache/translation/fabric/external-DDR experiment.

The historical performance.py preset remains unchanged. This entry defaults to
B and exports only when --emit is explicit; no Vivado or bitstream operation.
"""
import argparse
import hashlib
import json
from pathlib import Path

import export as exporter

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "board-performance-profile.json"
MANIFEST_SHA256 = "1fc8470f0689c96ec53ac446e5d9a265f5eae8244a160e51b450d0d0abee69bd"


def load_manifest():
    content = MANIFEST.read_bytes()
    if hashlib.sha256(content).hexdigest() != MANIFEST_SHA256:
        raise RuntimeError("frozen board A/B manifest changed; review and requalification required")
    return json.loads(content)


def native_options(mode):
    """Exact arguments after the output directory; shared by both emitters."""
    if mode not in ("A", "B"):
        raise ValueError("choose A or B explicitly")
    return list(load_manifest()["modes"][mode]["native_options"])


def compare_constructor(mode, actual):
    """Compare every reported product field, including false/default values.

    This checks constructors only. It does not replace inspection of actual
    instantiated core/cache/TLB/DMA/bridge parameters and active components.
    """
    expected = json.loads((HERE / "board-performance-constructors.json").read_text())[mode]
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
        expected[section]["pendingVirtualStoreProofSlots"] = 1
    for section in ("profile", "cache"):
        expected[section]["readPrefetchStoreHold"] = False
        expected[section]["durableReadPrefetchCandidate"] = False
        expected[section]["readPrefetchBehindStore"] = False
    if actual != expected:
        raise RuntimeError("actual complete constructor differs from frozen mode " + mode)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("A", "B"), default="B",
        help="B is the optimization candidate; A restores the original v3 profile")
    parser.add_argument("--output", type=Path, help="fresh native output directory")
    parser.add_argument("--emit", action="store_true", help="emit native RTL; default is preflight only")
    parser.add_argument("--print-native-options", action="store_true",
        help="print the exact shared native/GSIM argument list without building")
    args = parser.parse_args(argv)
    spec = load_manifest()["modes"][args.mode]
    if args.print_native_options:
        if args.output is not None or args.emit:
            parser.error("--print-native-options cannot be combined with --output or --emit")
        print(json.dumps(spec["native_options"]))
        return
    if args.output is None:
        parser.error("--output is required for preflight or native export")
    # export.py's default is exactly --selected. All other arguments are passed
    # byte-for-byte; its full-profile hash gate runs before creating any output.
    options = ["--output", str(args.output),
        *(option for option in spec["native_options"] if option != "--selected")]
    if args.emit:
        options.append("--emit")
    exporter.main(options, expected_profile_sha256=spec["export_profile_sha256"])


if __name__ == "__main__":
    main()
