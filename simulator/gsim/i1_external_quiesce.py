#!/usr/bin/env python3
"""Short real-I1 architectural stop/resume test. Not cache/fabric/clock-gating qualification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import run as common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="focused")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.tag.replace("-", "").replace("_", "").isalnum():
        parser.error("tag must contain only letters, digits, hyphens, or underscores")
    name = "i1-external-quiesce-" + args.tag
    if args.dry_run:
        print(json.dumps({"name": name, "top": "I1ExternalQuiesceHarness", "clock": "single",
                          "scope": "real fpga8 CPU architectural stop only", "negative": "--wrong-retire"}))
        return
    output = common.BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    paths = sorted((common.ROOT / "src/main/scala/core/inorder").glob("*.scala")) + [
        *sorted((common.ROOT / "src/main/scala/isa").rglob("*.scala")),
        common.ROOT / "src/test/scala/inorder/I1ExternalQuiesceMain.scala",
        *sorted((common.ROOT / "src/main/scala").rglob("CommonI1*.scala")),
        common.HERE / "harness/i1_external_quiesce.cpp", common.HERE / "run.py",
        common.HERE / "config/toolchain.json", Path(__file__).resolve()]
    def hashes():
        return {str(path.relative_to(common.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in paths}
    report = {"status": "RUNNING", "source_sha256": hashes(),
              "scope": "CPU architectural stop/resume only; no cache/fabric drain, CDC, PLL or physical timing claim"}
    try:
        gsim, cxx = common.setup(False)
        common.test(gsim, cxx, name, "inorder.I1ExternalQuiesceMain", "I1ExternalQuiesceHarness",
                    "i1_external_quiesce.cpp", defines={}, timeout=180)
        log = (output / "test.log").read_text()
        if "I1_EXTERNAL_QUIESCE_PASS" not in log:
            raise RuntimeError("positive test omitted completion marker")
        result = subprocess.run([output / "run", "--wrong-retire"], capture_output=True, text=True,
                                timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        negative = result.stdout + result.stderr
        (output / "wrong-retire.log").write_text(negative)
        if result.returncode == 0 or "independent register-result oracle" not in negative:
            raise RuntimeError("wrong architectural-result oracle was not rejected")
        if hashes() != report["source_sha256"]:
            raise RuntimeError("test sources changed during run")
        report.update(status="PASS", positive_log=log, wrong_retire="REJECTED")
    except BaseException as error:
        report.update(status="FAIL", error=str(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
