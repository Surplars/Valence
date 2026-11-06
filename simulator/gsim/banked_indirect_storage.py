#!/usr/bin/env python3
"""Focused logical-16 banked/register storage acceptance. No CPU runtime or board qualification."""
import json
import os
import subprocess

from run import BUILD, run, setup, test


NEGATIVES = {
    "--inject-mismatch": ("cycle=300 lane=0", "prediction training oracle mismatch"),
    "--inject-table-hit": ("GSIM prediction training: PASS", "directed indirect table hit mismatch"),
    "--inject-table-target-high": ("GSIM prediction training: PASS", "directed indirect table target mismatch"),
    "--inject-bank-stale-hit": ("GSIM directed indirect: PASS", "banked=owner-0-to-1-stale-A",
                                "expected_hit=0 actual_hit=1", "banked indirect table hit mismatch"),
}


def check_negatives(output):
    for flag, markers in NEGATIVES.items():
        result = subprocess.run([str(output / "run"), flag], capture_output=True, text=True, timeout=120,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0",
                                     "UBSAN_OPTIONS": "halt_on_error=1"})
        log = result.stdout + result.stderr
        (output / (flag[2:] + ".log")).write_text(log)
        if result.returncode != 1 or not all(marker in log for marker in markers):
            raise RuntimeError(f"negative control did not reach its expected mismatch: {flag}")


def main():
    output = BUILD / "banked-indirect-storage"
    output.mkdir(parents=True, exist_ok=True)
    run(["mill", "-i", "IonSoC.test.testOnly", "ooo.BankedIndirectStorageSpec"],
        log=output / "contracts.log")
    gsim, cxx = setup(False)
    summaries = {}
    for mode in ("reg", "banked"):
        result = test(gsim, cxx, "banked-indirect-storage/" + mode,
                      "ooo.BankedIndirectStorageGsimMain", "BankedIndirectStorageGsim",
                      "banked_indirect_storage.cpp", parameters=(mode,),
                      defines={"TRAIN_WIDTH": 2, "COMPRESSED": 1, "DELAYED_TRAINING": 1})
        check_negatives(result)
        summaries[mode] = (result / "test.log").read_text()
    if summaries["reg"] != summaries["banked"]:
        raise RuntimeError("matched storage modes produced different independent coverage results")
    (output / "results.json").write_text(json.dumps({"status": "PASS", "modes": summaries,
        "negative_controls_per_mode": list(NEGATIVES), "cpu_runtime_verified": False,
        "production_selector_available": False}, indent=2) + "\n")
    print("GSIM banked indirect storage: PASS (matched component pair and eight reached negative controls)")


if __name__ == "__main__":
    main()
