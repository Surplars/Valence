#!/usr/bin/env python3
"""Bounded real I1 operand-helper GSIM test with independently rejected legacy leakage controls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common


NEGATIVES = [f"--legacy-zero-n{n}" for n in (1, 4, 7, 10)] + [
    f"--legacy-first-n{n}" for n in (4, 7, 10)
] + ["--legacy-override-enabled", "--legacy-register-disabled"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="focused")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("tag must contain only letters, digits, hyphens, or underscores")
    name = "i1-operand-singleton-" + args.tag
    scope = "isolated real production operand/overrideOperand helpers; no CPU or physical timing claim"
    if args.dry_run:
        print(json.dumps({"name": name, "top": "I1OperandSingletonFixture", "clock": "single",
                          "width": 64, "counts": list(range(1, 11)) + [20],
                          "negative_controls": NEGATIVES, "scope": scope}))
        return

    output = common.BUILD / name
    output.mkdir(parents=True, exist_ok=True)
    sources = [common.ROOT / "src/main/scala/core/inorder/I1ExecuteDatapath.scala",
               common.ROOT / "src/test/scala/inorder/I1OperandSingletonMain.scala",
               common.HERE / "harness/i1_operand_singleton.cpp", Path(__file__).resolve(),
               common.HERE / "run.py", common.HERE / "config/toolchain.json"]

    def hashes():
        return {str(path.relative_to(common.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sources}

    receipt = {"status": "RUNNING", "scope": scope, "source_sha256": hashes(), "controls": []}
    try:
        gsim, cxx = common.setup(False)
        common.test(gsim, cxx, name, "inorder.I1OperandSingletonMain", "I1OperandSingletonFixture",
                    "i1_operand_singleton.cpp", defines={}, timeout=60)
        positive = (output / "test.log").read_text()
        if "I1_OPERAND_SINGLETON_PASS widths=64 counts=1,2,3,4,5,6,7,8,9,10,20" not in positive:
            raise RuntimeError("positive production-helper test omitted completion marker")
        receipt["positive_log"] = positive
        for flag in ["--legacy-controls", *NEGATIVES]:
            result = subprocess.run([output / "run", flag], capture_output=True, text=True,
                                    timeout=60, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
            text = result.stdout + result.stderr
            log = output / (flag[2:] + ".log")
            log.write_text(text)
            if any(marker in text for marker in ("ERROR: AddressSanitizer", "runtime error:",
                                                 "UndefinedBehaviorSanitizer")):
                raise RuntimeError(f"sanitizer failure in {flag}")
            if flag == "--legacy-controls":
                if result.returncode != 0 or "I1_OPERAND_LEGACY_CONTROLS_PASS" not in text:
                    raise RuntimeError("unaffected legacy arities did not pass independent oracle")
                verdict = "PASS_UNAFFECTED_ARITIES"
            else:
                if (result.returncode != 1 or f"REACHED {flag} test-only exact legacy helper" not in text
                        or f"I1_OPERAND_MASKED_OR_MISMATCH case={flag}" not in text
                        or "NEGATIVE_CONTROL_ESCAPED" in text):
                    raise RuntimeError(f"legacy negative control was not rejected at its intended case: {flag}")
                verdict = "REJECTED_AT_EXPLICIT_WITNESS"
            receipt["controls"].append({"flag": flag, "exit": result.returncode, "verdict": verdict,
                                        "log": log.name,
                                        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
            print(f"{flag}: {verdict}", flush=True)
        if hashes() != receipt["source_sha256"]:
            raise RuntimeError("test sources changed during run")
        receipt["status"] = "PASS"
    except BaseException as error:
        receipt.update(status="FAIL", error=str(error))
        raise
    finally:
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    main()
