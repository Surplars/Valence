#!/usr/bin/env python3
"""Two focused legacy/default GMAC boundary checks for the opt-in RX-stop change."""
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("unsafe tag")
    name = "gmac-stop-boundaries-" + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    paths = list((ROOT / "src/main/scala/ip").rglob("*.scala"))
    paths += [ROOT / "src/test/scala/ip" / file for file in ("SelfGmacGsim.scala", "SelfGmacFramesGsim.scala")]
    paths += [HERE / "harness" / file for file in
              ("self_gmac_frames.cpp", "tilelink_gmac_control.cpp", "gmii_reference.h")]
    paths += [Path(__file__), HERE / "run.py", HERE / "config/toolchain.json", ROOT / "build.mill"]
    before = {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}
    report = {"status": "RUNNING", "scope": __doc__, "source_sha256": before,
              "checks": {}, "independent_clock_cdc_verified": False, "board_verified": False}
    try:
        gsim, cxx = setup(False)
        for stem, emitter, top, harness, negatives in (
            ("control", "ip.TileLinkGmacControlGsimMain", "TileLinkGmacControl", "tilelink_gmac_control.cpp",
             (("--inject-mismatch", "TL GMAC independent CSR oracle mismatch"),
              ("--inject-mdio-mismatch", "TL GMAC MDIO independent wire oracle mismatch"))),
            ("frames", "ip.SelfGmacFramesGsimMain", "SelfGmacFramesGsim", "self_gmac_frames.cpp",
             (("--inject-mismatch", "GMII TX independent wire oracle mismatch"),)),
        ):
            model = test(gsim, cxx, name + "/" + stem, emitter, top, harness)
            row = {"summary": (model / "test.log").read_text().strip(), "negative_checks": {}}
            for flag, marker in negatives:
                negative = subprocess.run([str(model / "run"), flag], capture_output=True, text=True,
                                          timeout=120, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
                (model / (flag[2:] + ".log")).write_text(negative.stdout + negative.stderr)
                if negative.returncode != 1 or marker not in negative.stdout + negative.stderr:
                    raise RuntimeError("Independent boundary negative did not reject: " + flag)
                row["negative_checks"][flag] = marker
            row["model_sha256"] = {str(p.relative_to(ROOT)): digest(p) for p in model.iterdir()
                                   if p.is_file() and (p.name == "run" or p.suffix in (".fir", ".cpp", ".h"))}
            report["checks"][stem] = row
        report["status"] = "PASS_GMAC_STOP_DEFAULT_BOUNDARIES"
    except BaseException as error:
        report.update(status="FAILED", failure=str(error))
        raise
    finally:
        if before != {str(p.relative_to(ROOT)): digest(p) for p in sorted(paths)}:
            report.update(status="FAILED", failure="source/oracle drift during boundary checks")
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["status"] != "PASS_GMAC_STOP_DEFAULT_BOUNDARIES":
        raise RuntimeError(report["failure"])
    print(report["status"], "receipt=" + str(output / "receipt.json"), flush=True)


if __name__ == "__main__":
    main()
