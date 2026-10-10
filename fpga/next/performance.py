#!/usr/bin/env python3
"""Export the recommended posted-performance-v3 preset.

The selected DMA4/LSU4/D16 profile enables posted merging, posted/PF coexistence,
the PF-only initial head offer and canonical virtual-store overlap. Returnflow
and prechecked request flow stay OFF. --disable-canonical-store-overlap restores
the v2 recommendation; --disable-posted-prefetch restores posted-only controls;
--disable-posted turns all three posted features OFF. Generic defaults stay OFF.
No whole-Linux throughput, overlapping COPY read misses, mapped PPA/STA or live-FPGA claim.
"""
import argparse
from pathlib import Path

import export as exporter

NAME = "posted-performance-v3"
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
# Full reviewed 66-field profiles live in performance-profile.json.
# Any drift fails before output. Boolean keys preserve the default/full-disable
# host API; the explicit legacy control has a separate frozen digest.
PROFILE_SHA256 = {
    False: "0cb9aab138f18b395ef28cb4680cdb0a5f9b6d4921d9be0e24775534181eb3a4",
    True: "44712cdbf652f729cdd906e8fe5c719e69c34b9dff2b4ca2a82c0abd8e781001",
}
LEGACY_PROFILE_SHA256 = "51fea43e1c91ab7f6b3b5c922092f8e0de92145d002bc7b2d2b119bc27a42838"
# Exact v2 behavior after removing only the canonical treatment.
CANONICAL_OFF_PROFILE_SHA256 = {'legacy-posted': '144ba2d7a51c3204be134cf520719aa086a5471e0bcfbad5482542847a114dad', 'off': 'c77662ebf46c9fa1e01f44fd3c04237c20729de1e2c1e4261550ea4d6fa701f1', 'on': 'a3f4206313693e1a44b0fd8e84ed96ea2488abbd7a92bd840b2ab5a3062c65fe'}


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
    parser.add_argument("--disable-canonical-store-overlap", action="store_true",
        help="restore v2 behavior by independently disabling canonical virtual-store overlap")
    args = parser.parse_args(argv)
    enabled = not args.disable_posted
    options = ["--output", str(args.output), *OPTIONS]
    if enabled:
        options.append("--posted-store-merge")
        if not args.disable_posted_prefetch:
            options += ["--posted-prefetch-coexistence", "--posted-prefetch-head-offer"]
    if not args.disable_canonical_store_overlap:
        options.append("--canonical-virtual-store-overlap")
    if args.emit:
        options.append("--emit")
    # Deliberately no hardware override or passthrough: reference/storage, debug,
    # translated-response and prechecked-request flow are separate experiments.
    digest = LEGACY_PROFILE_SHA256 if args.disable_posted_prefetch else PROFILE_SHA256[enabled]
    if args.disable_canonical_store_overlap:
        mode = "legacy-posted" if args.disable_posted_prefetch else "on" if enabled else "off"
        digest = CANONICAL_OFF_PROFILE_SHA256[mode]
    exporter.main(options, expected_profile_sha256=digest)


if __name__ == "__main__":
    main()
