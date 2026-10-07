#!/usr/bin/env python3
"""Short original GMII TX/RX + native DMA adapter batch; no CPU/PHY/CDC/CAD claim."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    paths = list((ROOT / "src/main/scala/ip/ethernet").glob("*.scala"))
    paths += list((ROOT / "src/test/scala/ip").glob("SelfGmac*.scala"))
    paths += [ROOT / "src/main/scala/ip/dma/EthernetPacketDma.scala",
              ROOT / "src/main/scala/ip/bus/RegisterArbiter.scala", ROOT / "src/main/scala/ip/bus/RegisterPort.scala",
              ROOT / "build.mill", HERE / "self_gmac_frames.py", HERE / "run.py", HERE / "config/toolchain.json"]
    paths += [HERE / "harness" / name for name in
              ("gmii_reference.h", "self_gmac_frames.cpp", "self_gmac_adapter.cpp", "self_gmac_dma.cpp")]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}


def protected_sources():
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / "src/main/scala").rglob("*.scala"))
            if "ip/ethernet/" not in str(p.relative_to(ROOT))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag): parser.error("unsafe tag")
    name = "self-gmac-frames-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    before, protected = inputs(), protected_sources()
    report = {"status": "running", "scope": "single-clock GMII frame engines and real DMA/native adapter",
              "source_sha256": before, "protected_main_source_sha256": protected,
              "single_clock_dma_framing_verified": False, "independent_clock_cdc_verified": False,
              "rgmii_verified": False, "on_board_verified": False, "routed_timing_verified": False,
              "ten_g_mac_pcs_verified": False, "bit_generated": False}
    try:
        run(["mill", "-i", "IonSoC.test.testOnly", "ip.SelfGmacParamsSpec"], log=output / "scala.log")
        run(["mill", "-i", "IonSoC.test.runMain", "ip.SelfGmacFramesRtlMain", output / "rtl"],
            log=output / "production-export.log")
        report["production_rtl_sha256"] = {str(p.relative_to(output / "rtl")): digest(p)
            for p in sorted((output / "rtl").rglob("*.sv"))}
        if not report["production_rtl_sha256"]: raise RuntimeError("empty RTL export")
        gsim, cxx = setup(False)
        for stem, main, top, harness, marker in (
            ("frames", "ip.SelfGmacFramesGsimMain", "SelfGmacFramesGsim", "self_gmac_frames.cpp",
             "GMII TX independent wire oracle mismatch"),
            ("adapter", "ip.SelfGmacAdapterGsimMain", "EthernetDmaFrameAdapter", "self_gmac_adapter.cpp",
             "DMA adapter independent status oracle mismatch"),
            ("dma", "ip.SelfGmacDmaGsimMain", "SelfGmacDmaGsim", "self_gmac_dma.cpp",
             "GMAC DMA independent TX wire oracle mismatch"),
        ):
            model = test(gsim, cxx, name + "/" + stem, main, top, harness)
            negative = subprocess.run([str(model / "run"), "--inject-mismatch"], capture_output=True,
                text=True, timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            (model / "negative.log").write_text(negative.stdout + negative.stderr)
            if negative.returncode != 1 or marker not in negative.stdout + negative.stderr:
                raise RuntimeError("independent negative oracle failed: " + stem)
            report[stem] = {"status": "passed", "independent_negative": "passed",
                "fir_sha256": digest(model / (top + ".fir")), "executable_sha256": digest(model / "run"),
                "summary": (model / "test.log").read_text().strip()}
        report.update(status="passed_single_clock_frames_dma_only", single_clock_dma_framing_verified=True)
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if inputs() != before or protected_sources() != protected:
            report.update(status="failed", failure="input or protected SoC/DMA source drift")
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "passed_single_clock_frames_dma_only": raise RuntimeError(report["failure"])
    print("SELF_GMAC_FRAMES_DMA_PASS receipt=" + str(output / "receipt.json"), flush=True)


if __name__ == "__main__": main()
