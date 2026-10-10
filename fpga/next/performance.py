#!/usr/bin/env python3
"""Export the recommended posted-performance-v1 preset.

Qualified Bare WRITE throughput improves 91.23%; COPY throughput falls 15.25%
(17.9973% more COPY cycles). This is a workload tradeoff, not a suite-wide gain.
The preset enables posted merging by default; --disable-posted changes only that
selection. Generic export.py and FpgaNextConfig defaults remain unchanged.
No Linux/Sv39 posted early-ACK, mapped PPA/STA or live-FPGA claim.
"""
import argparse
from pathlib import Path

import export as exporter

NAME = "posted-performance-v1"
# Exact original qualified flags. Use the existing exporter and hardware parser;
# do not duplicate FpgaNextConfig or OooParams defaults here.
OPTIONS = (
    "--lsu-entries", "4", "--data-translation-entries", "16",
    "--virtual-ram-load-precheck", "--physical-load-ingress-flow",
    "--load-order-older-retire", "--fetch-previous-packet",
    "--dma-line-transfers", "--dma-line-entries", "4",
    "--prepared-store-lookahead", "--store-next-line-prefetch",
    "--store-prefetch-mru-insertion",
)
# Canonical JSON (sorted keys, compact separators) of all 63 export profile
# fields from the sealed native receipts for source 0658f2d4a543ba5849498af626eec0a248363540.
# Any field/value/geometry drift fails before creating output or invoking Mill.
PROFILE_SHA256 = {
    False: "977c6286c5e1366c4b05f2522439b8c69ee3e54d998b6db2d845e8b83f1782c2",
    True: "d5fdbfe1a830ac9977a65295c78d25da7864f56303c4e591664921f713375be0",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="fresh output directory")
    parser.add_argument("--emit", action="store_true", help="emit native RTL; default is preflight only")
    parser.add_argument("--disable-posted", action="store_true",
        help="reproduce the qualified OFF control with every other setting identical")
    args = parser.parse_args(argv)
    enabled = not args.disable_posted
    options = ["--output", str(args.output), *OPTIONS]
    if enabled:
        options.append("--posted-store-merge")
    if args.emit:
        options.append("--emit")
    # Deliberately no hardware override or passthrough: reference/storage, debug,
    # translated-response and prechecked-request flow are separate experiments.
    exporter.main(options, expected_profile_sha256=PROFILE_SHA256[enabled])


if __name__ == "__main__":
    main()
