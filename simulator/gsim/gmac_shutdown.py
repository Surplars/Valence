#!/usr/bin/env python3
"""Focused real ManagedGmac/DMA RX shutdown regression; aliased clocks only.

Run from a shell that sourced scripts/cloud/env.sh. Does not run broad GSIM,
CPU/Linux, synthesis or implementation, and makes no independent-clock proof.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from run import BUILD, HERE, ROOT, setup, test


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    paths = list((ROOT / "src/main/scala/ip").rglob("*.scala"))
    paths += [ROOT / "src/test/scala/ip/GmacShutdownGsim.scala", ROOT / "build.mill",
              HERE / "harness/gmac_shutdown.cpp", HERE / "harness/gmii_reference.h",
              Path(__file__), HERE / "run.py", HERE / "config/toolchain.json", ROOT / "scripts/cloud/env.sh"]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("unsafe tag")
    if not os.environ.get("VALENCE_CLOUD_ENV"):
        parser.error("source scripts/cloud/env.sh before building")
    name = "gmac-shutdown-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    before = inputs()
    report = {"status": "RUNNING", "source_sha256": before,
              "scope": "real ManagedGmac, CDC structures, native adapter and EthernetPacketDma",
              "clock_model": "all clocks aliased; sampled reset workaround for pinned GSIM",
              "independent_clock_cdc_verified": False, "physical_gate_verified": False,
              "board_verified": False, "linux_boot_verified": False,
              "routed_timing_verified": False, "bit_generated": False}
    try:
        gsim, cxx = setup(False)
        model = test(gsim, cxx, name + "/integration", "ip.GmacShutdownGsimMain",
                     "GmacShutdownGsim", "gmac_shutdown.cpp")
        report["integration"] = {"summary": (model / "test.log").read_text().strip(),
                                 "fir_sha256": digest(model / "GmacShutdownGsim.fir"),
                                 "executable_sha256": digest(model / "run")}
        report["negative_checks"] = {}
        for flag, marker in (
            ("payload", "RX shutdown independent frame payload oracle mismatch"),
            ("status", "RX shutdown independent status-tail oracle mismatch"),
            ("drain", "RX shutdown independent premature-drain oracle mismatch"),
            ("memory", "RX shutdown independent memory/canary oracle mismatch"),
        ):
            result = subprocess.run([str(model / "run"), "--inject-" + flag],
                                    capture_output=True, text=True, timeout=120,
                                    env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            (model / ("negative-" + flag + ".log")).write_text(result.stdout + result.stderr)
            if result.returncode != 1 or marker not in result.stderr:
                raise RuntimeError("independent negative oracle did not reject: " + flag)
            report["negative_checks"][flag] = "PASS"
        report["status"] = "PASS_GMAC_SHUTDOWN_SINGLE_CLOCK"
    except BaseException as error:
        report.update(status="FAILED", failure=str(error))
        raise
    finally:
        if inputs() != before:
            report.update(status="FAILED", failure="input drift during shutdown verification")
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_GMAC_SHUTDOWN_SINGLE_CLOCK":
        raise RuntimeError(report["failure"])
    print(report["status"], "receipt=" + str(output / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
