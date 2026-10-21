#!/usr/bin/env python3
"""Same-clock channel conservation only, NOT independent-clock CDC qualification."""
import os
import subprocess
from run import setup, test

gsim, cxx = setup(False)
output = test(gsim, cxx, "cmu-r3-axi-same-clock", "ip.Axi4CdcSameClockMain", "Axi4CdcSameClock",
              "axi_cdc_channels.cpp", defines={})
negative = subprocess.run([str(output / "run"), "--inject-mismatch"], text=True, capture_output=True,
                          timeout=30, env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
(output / "negative.log").write_text(negative.stdout + negative.stderr)
if negative.returncode != 1 or "AXI CDC independent channel oracle mismatch" not in negative.stderr:
    raise RuntimeError("negative oracle did not reject injected corruption")
print("Negative oracle rejected; multi-clock acceptance remains native xsim work.")
