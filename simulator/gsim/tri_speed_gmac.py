#!/usr/bin/env python3
"""Focused opt-in tri-speed MAC logic/ownership acceptance; never physical/board qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test

MODELS = (
    ("frames", "ip.TriSpeedFramesGsimMain", "TriSpeedFramesGsim", "trispeed_gmac_frames.cpp",
     "tri-speed TX independent wire oracle mismatch", {}),
    ("ingress", "ip.EthernetIngressGsimMain", "EthernetIngressGsim", "ethernet_physical_ingress.cpp",
     "physical ingress independent frame oracle mismatch", {}),
    ("phy", "ip.Rtl8211fPhyManagerGsimMain", "Rtl8211fPhyManager", "rtl8211f_phy_manager.cpp",
     "PHY independent register oracle mismatch", {}),
    ("transition", "ip.EthernetMediaTransitionGsimMain", "EthernetMediaTransition", "ethernet_media_transition.cpp",
     "media independent ownership oracle mismatch", {}),
    ("mdio-owner", "ip.ManagedMdioArbiterGsimMain", "ManagedMdioArbiter", "managed_mdio_arbiter.cpp",
     "MDIO independent command-owner oracle mismatch", {}),
    ("mdio-wire", "ip.TriSpeedMdioClause22GsimMain", "MdioClause22", "mdio_clause22.cpp",
     "MDIO independent wire oracle mismatch", {"MDIO_DIVIDER": 40}),
    ("csr", "ip.TriSpeedControlGsimMain", "TriSpeedControlGsim", "trispeed_gmac_control.cpp",
     "tri-speed CSR independent 64-bit oracle mismatch", {}),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    files = sorted((ROOT / "src/main/scala").rglob("*.scala"))
    files += sorted((ROOT / "src/test/scala").rglob("*.scala"))
    files += [HERE / "harness" / row[3] for row in MODELS]
    files += [HERE / "harness/gmii_reference.h", HERE / "tri_speed_gmac.py", HERE / "run.py",
              HERE / "config/toolchain.json", ROOT / "build.mill",
              ROOT / "fpga/zu15eg/native_rgmii_trispeed.sv", ROOT / "fpga/zu15eg/native_tx_common_delay.sv"]
    files += [ROOT / "fpga/firmware" / name for name in ("valence_gmac.h", "netboot_board.c",
        "test_netboot_board.c", "linux_net/valence_gmac.c", "linux_net/valence_media_policy.h")]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(files))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--models", default="all", help="comma-separated focused model names, or all")
    parser.add_argument("--no-rtl", action="store_true", help="skip production export; report that gap explicitly")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag): parser.error("unsafe tag")
    selected = {r[0] for r in MODELS} if args.models == "all" else set(args.models.split(","))
    if not selected or not selected <= {r[0] for r in MODELS}: parser.error("unknown model")
    name = "tri-speed-gmac-" + args.tag
    out = BUILD / name
    out.mkdir(parents=True, exist_ok=False)
    before = inputs()
    report = {"status": "running", "source_sha256": before,
        "scope": "single-clock functional and independently scheduled logical ownership models",
        "independent_clock_cdc_verified": False, "native_ddr_pins_verified": False,
        "synthesis_verified": False, "routed_timing_verified": False, "on_board_verified": False,
        "bit_generated": False, "production_export_run": not args.no_rtl, "models": {}}
    try:
        if not args.no_rtl:
            run(["mill", "-i", "IonSoC.test.runMain", "ip.TriSpeedManagedGmacRtlMain", out / "rtl", "hardware"],
                log=out / "production-export.log")
            report["production_rtl_sha256"] = {str(p.relative_to(out / "rtl")): digest(p)
                for p in sorted((out / "rtl").rglob("*.sv"))}
            if not report["production_rtl_sha256"]: raise RuntimeError("empty production export")
        gsim, cxx = setup(False)
        for stem, main, top, harness, marker, defines in MODELS:
            if stem not in selected: continue
            model = test(gsim, cxx, name + "/" + stem, main, top, harness, defines=defines, timeout=240)
            negative = subprocess.run([str(model / "run"), "--inject-mismatch"], capture_output=True,
                text=True, timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            (model / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode != 1 or marker not in negative.stdout + negative.stderr:
                raise RuntimeError("independent mismatch injection did not fail: " + stem)
            report["models"][stem] = {"status": "passed", "negative_oracle": "passed",
                "model_directory": str(model), "fir_sha256": digest(model / (top + ".fir")),
                "executable_sha256": digest(model / "run"),
                "summary": (model / "test.log").read_text().strip()}
        report["status"] = "passed_focused_logic_only"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if inputs() != before: report.update(status="failed", failure="source/test input changed during acceptance")
        (out / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "passed_focused_logic_only": raise RuntimeError(report["failure"])
    print("TRI_SPEED_GMAC_LOGIC_PASS receipt=" + str(out / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
