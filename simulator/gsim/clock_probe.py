#!/usr/bin/env python3
"""Qualify pinned GSIM clock scheduling; no CPU regression, Vivado, or CDC signoff."""
import argparse
import json
import os
import subprocess
from run import BUILD, HERE, LOCK, setup, test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="independent-clock-probe-20261002")
    args = parser.parse_args()
    if not args.output.replace("-", "").replace("_", "").isalnum():
        parser.error("output must be a simple artifact name")
    output = BUILD / args.output
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "gsim_revision": LOCK["revision"],
              "independent_edges_verified": False, "cdc_signoff": False,
              "cpu_rtl_changed": False, "vendor_changed": False}
    (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        gsim, cxx = setup(False)
        test(gsim, cxx, args.output, "ooo.IndependentClockProbeGsimMain",
             "IndependentClockProbeGsim", "independent_clock_probe.cpp",
             runtime_args=("--observe",), defines={}, timeout=30)
        observation = json.loads((output / "test.log").read_text())
        required = subprocess.run([str(output / "run")], capture_output=True, text=True,
                                  timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
        (output / "required.log").write_text(required.stdout + required.stderr)
        supported = observation["independent_edges_verified"]
        reset_supported = observation["async_reset"]["verified"]
        accepted = supported and reset_supported
        if accepted:
            if required.returncode != 0:
                raise RuntimeError("clock observation and required acceptance disagree")
        elif required.returncode != 1 or "independent clock edge/reset contract mismatch" not in required.stderr:
            raise RuntimeError("unsupported clock capability did not fail the original edge contract")
        report.update(status="clock-and-reset-verified" if accepted else "clock-or-reset-not-supported",
                      observation=observation, independent_edges_verified=supported,
                      async_reset_verified=reset_supported,
                      required_contract_exit_code=required.returncode,
                      qualification_complete=True,
                      implication="Clock probe only; not bridge correctness/CDC/RDC/board timing evidence."
                      if accepted else "Do not use unmodified independently clocked GSIM wrappers as dual-clock acceptance evidence.")
    except Exception as error:
        report.update(status="probe-failed", error=str(error), qualification_complete=False)
        raise
    finally:
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
