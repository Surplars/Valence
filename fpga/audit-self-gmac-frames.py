#!/usr/bin/env python3
"""Bind short framing checks to original module route reports; never board qualification."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok, why):
    if not ok: raise RuntimeError(why)


def resource(text, label):
    match = re.search(r"\|\s*" + re.escape(label) + r"\*?\s*\|\s*([0-9.]+)\s*\|", text)
    require(match is not None, "missing utilization: " + label)
    value = float(match.group(1))
    return int(value) if value.is_integer() else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("functional_receipt", type=Path)
    parser.add_argument("archived_native", type=Path)
    parser.add_argument("fresh_output", type=Path)
    args = parser.parse_args()
    require(not args.fresh_output.exists(), "preserve previous audits")
    evidence = json.loads(args.functional_receipt.read_text())
    require(evidence["status"] == "passed_single_clock_frames_dma_only", "functional batch not passed")
    for source, expected in {**evidence["protected_main_source_sha256"], **evidence["source_sha256"]}.items():
        require(sha(ROOT / source) == expected, "source drift: " + source)
    for name, expected in evidence["production_rtl_sha256"].items():
        require(sha(args.functional_receipt.parent / "rtl" / name) == expected, "functional RTL drift: " + name)
        require(sha(args.archived_native / "rtl" / name) == expected, "CAD RTL drift: " + name)
    for stem, top in (("frames", "SelfGmacFramesGsim"), ("adapter", "EthernetDmaFrameAdapter"),
                      ("dma", "SelfGmacDmaGsim")):
        report = evidence[stem]
        model = args.functional_receipt.parent / stem
        require(report["status"] == "passed" and report["independent_negative"] == "passed", "model not passed")
        require(sha(model / "run") == report["executable_sha256"], "executable drift: " + stem)
        require(sha(model / (top + ".fir")) == report["fir_sha256"], "FIR drift: " + stem)
    modules = {}
    for top, period in (("GmiiFrameTx", 8.0), ("GmiiFrameRx", 8.0), ("EthernetDmaFrameAdapter", 10.0)):
        directory = args.archived_native / "reports" / top
        value = json.loads((directory / "result.json").read_text())
        require(value["top"] == top and value["period_ns"] == period, "wrong module/period")
        require(value["part"] == "xczu15eg-ffvb1156-2-i", "wrong part")
        for key in ("internal_setup_wns_ns", "internal_hold_whs_ns", "all_setup_wns_ns", "all_hold_whs_ns"):
            require(math.isfinite(value[key]), "invalid slack: " + key)
        require(value["internal_timing_pass"] ==
            (value["internal_setup_wns_ns"] >= 0 and value["internal_hold_whs_ns"] >= 0), "timing status mismatch")
        text = (directory / "post_route_utilization.rpt").read_text()
        value["resources"] = {"lut": resource(text, "CLB LUTs"), "ff": resource(text, "CLB Registers"),
            "bram_tiles": resource(text, "Block RAM Tile"), "dsp": resource(text, "DSPs")}
        if top in ("GmiiFrameTx", "GmiiFrameRx"):
            require(0.5 <= value["resources"]["bram_tiles"] <= 1,
                    "2KiB packet buffer did not infer one block RAM: " + top)
            require(value["resources"]["lut"] < 4000 and value["resources"]["ff"] < 2000,
                    "packet RAM expanded into logic/registers: " + top)
        require((directory / "post_route.dcp").stat().st_size > 0, "missing routed checkpoint")
        modules[top] = value
    files = {str(p.relative_to(args.archived_native)): sha(p)
             for p in sorted(args.archived_native.rglob("*")) if p.is_file()}
    passed = all(v["internal_timing_pass"] and v["all_setup_wns_ns"] >= 0 for v in modules.values())
    result = {"status": "PASS_GMAC_MODULE_INTERNAL_OOC" if passed else "FAIL_GMAC_MODULE_TIMING",
              "functional_receipt": str(args.functional_receipt), "functional_receipt_sha256": sha(args.functional_receipt),
              "modules": modules, "native_file_sha256": files, "auditor_sha256": sha(Path(__file__)),
              "whole_board_signed_off": False, "cdc_or_phy_verified": False,
              "new_cpu_timing_measurement": False, "bit_generated": False}
    args.fresh_output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "modules": modules}, indent=2))
    if not passed: raise RuntimeError("module timing is not qualified; preserve evidence")


if __name__ == "__main__": main()
