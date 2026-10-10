#!/usr/bin/env python3
"""Export the recommended posted-performance-v2 preset.

The selected DMA4/LSU4/D16 profile enables posted merging, posted/PF coexistence
and the PF-only initial head offer. Returnflow and prechecked request flow stay
OFF. --disable-posted-prefetch restores the original posted-only recommendation;
--disable-posted turns all three dependent features OFF. Generic defaults stay
OFF. These fixed controls accept no arbitrary hardware overrides.
No Linux/Sv39 posted early-ACK, mapped PPA/STA or live-FPGA claim.
"""
import argparse
from pathlib import Path

import export as exporter

NAME = "posted-performance-v2"
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
# Full reviewed 65-field profiles live in performance-profile.json.
# Any drift fails before output. Boolean keys preserve the default/full-disable
# host API; the explicit legacy control has a separate frozen digest.
PROFILE_SHA256 = {
    False: "2cc9e279db5c560a590dd5ae2e5bc30f6f68fcfb035994bac8ba6c34dd100955",
    True: "7fc45c2c9422ba59b87222de62800e335b0427e90c146c724e1d14330e266b3e",
}
LEGACY_PROFILE_SHA256 = "0d5a8f122b68a889d61324d73804a3cbda0b8085ff49eb275ca697e2412a5a53"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, required=True, help="fresh output directory")
    parser.add_argument("--emit", action="store_true", help="emit native RTL; default is preflight only")
    control = parser.add_mutually_exclusive_group()
    control.add_argument("--disable-posted", action="store_true",
        help="turn posted merging and both dependent PF options OFF")
    control.add_argument("--disable-posted-prefetch", action="store_true",
        help="restore the original posted-only recommendation; coexistence and head offer OFF")
    args = parser.parse_args(argv)
    enabled = not args.disable_posted
    options = ["--output", str(args.output), *OPTIONS]
    if enabled:
        options.append("--posted-store-merge")
        if not args.disable_posted_prefetch:
            options += ["--posted-prefetch-coexistence", "--posted-prefetch-head-offer"]
    if args.emit:
        options.append("--emit")
    # Deliberately no hardware override or passthrough: reference/storage, debug,
    # translated-response and prechecked-request flow are separate experiments.
    digest = LEGACY_PROFILE_SHA256 if args.disable_posted_prefetch else PROFILE_SHA256[enabled]
    exporter.main(options, expected_profile_sha256=digest)


if __name__ == "__main__":
    main()
