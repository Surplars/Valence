#!/usr/bin/env python3
"""Self-designed GMAC foundation only; short TL/CRC/MDIO checks, no CPU/CAD/PHY claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from run import BUILD, HERE, ROOT, run, setup, test


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    paths = list((ROOT / "src/main/scala/ip/ethernet").glob("*.scala"))
    paths += list((ROOT / "src/test/scala/ip").glob("SelfGmac*.scala"))
    paths += [ROOT / "src/main/scala/bus/tilelink/TileLink.scala", ROOT / "build.mill",
              ROOT / "fpga/firmware/valence_gmac.h", HERE / "self_gmac.py", HERE / "run.py",
              HERE / "config/toolchain.json"]
    paths += [HERE / "harness" / name for name in
              ("ethernet_crc32.cpp", "mdio_clause22.cpp", "tilelink_gmac_control.cpp")]
    return {str(path.relative_to(ROOT)): digest(path) for path in sorted(paths)}


def protected_sources():
    return {str(path.relative_to(ROOT)): digest(path)
            for path in sorted((ROOT / "src/main/scala").rglob("*.scala"))
            if "ip/ethernet/" not in str(path.relative_to(ROOT))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag): parser.error("unsafe tag")
    name = "self-gmac-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    before, protected = inputs(), protected_sources()
    report = {"status": "running", "scope": "standalone native TL-UL CSR, CRC8/64 and MDIO Clause22",
              "source_sha256": before, "protected_main_source_sha256": protected,
              "mac_frame_engine_verified": False, "integrated_dma_verified": False,
              "rgmii_verified": False, "10g_mac_pcs_verified": False,
              "on_board_verified": False, "routed_timing_verified": False,
              "bit_generated": False}
    try:
        run(["mill", "-i", "IonSoC.test.testOnly", "ip.SelfGmacParamsSpec"], log=output / "scala.log")
        run(["mill", "-i", "IonSoC.test.runMain", "ip.SelfGmacFoundationRtlMain", output / "rtl"],
            log=output / "production-export.log")
        report["production_rtl_sha256"] = {str(p.relative_to(output / "rtl")): digest(p)
            for p in sorted((output / "rtl").rglob("*.sv"))}
        if not report["production_rtl_sha256"]: raise RuntimeError("empty production RTL export")
        run(["riscv64-unknown-elf-gcc", "-march=rv64imac_zicsr_zifencei", "-mabi=lp64", "-ffreestanding",
             "-Wall", "-Wextra", "-Werror", "-include", ROOT / "fpga/firmware/valence_gmac.h",
             "-x", "c", "-c", "/dev/null", "-o", output / "software-api.o"], log=output / "software-api.log")
        gsim, cxx = setup(False)
        for stem, main, top, harness, marker in (
            ("crc", "ip.EthernetCrc32GsimMain", "EthernetCrc32Gsim", "ethernet_crc32.cpp",
             "Ethernet CRC independent oracle mismatch"),
            ("mdio", "ip.MdioClause22GsimMain", "MdioClause22", "mdio_clause22.cpp",
             "MDIO independent wire oracle mismatch"),
            ("tl", "ip.TileLinkGmacControlGsimMain", "TileLinkGmacControl", "tilelink_gmac_control.cpp",
             "TL GMAC independent CSR oracle mismatch"),
        ):
            model = test(gsim, cxx, name + "/" + stem, main, top, harness)
            result = subprocess.run([str(model / "run"), "--inject-mismatch"], capture_output=True,
                text=True, timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            (model / "negative.log").write_text(result.stdout + result.stderr)
            if result.returncode != 1 or marker not in result.stdout + result.stderr:
                raise RuntimeError("independent negative check did not reject corruption: " + stem)
            report[stem] = {"status": "passed", "independent_negative": "passed",
                "fir_sha256": digest(model / (top + ".fir")), "executable_sha256": digest(model / "run"),
                "summary": (model / "test.log").read_text().strip()}
            if stem == "tl":
                result = subprocess.run([str(model / "run"), "--inject-mdio-mismatch"], capture_output=True,
                    text=True, timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                (model / "negative-mdio.log").write_text(result.stdout + result.stderr)
                if result.returncode != 1 or "TL GMAC MDIO independent wire oracle mismatch" not in result.stdout + result.stderr:
                    raise RuntimeError("integrated MDIO negative check did not reject corruption")
                report[stem]["integrated_mdio_independent_negative"] = "passed"
        report["status"] = "passed_foundation_only"
    except BaseException as error:
        report.update(status="failed", failure=str(error))
        raise
    finally:
        if inputs() != before or protected_sources() != protected:
            report.update(status="failed", failure="input/unchanged SoC source drift")
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "passed_foundation_only": raise RuntimeError(report["failure"])
    print("SELF_GMAC_FOUNDATION_PASS receipt=" + str(output / "receipt.json"), flush=True)


if __name__ == "__main__": main()
