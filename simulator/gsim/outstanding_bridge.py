#!/usr/bin/env python3
"""Matched serial / four-slot bridge-only GSIM checks. No CPU or physical claims."""
import json
import os
import re
import subprocess
from pathlib import Path
from run import BUILD, HERE, ROOT, setup, test


def main():
    gsim, cxx = setup(False)
    report = {"scope": "independent bridge GSIM only", "routed_timing_verified": False,
              "board_verified": False, "axi_bits": 64, "max_burst_beats": 16,
              "device_read_latency_cycles": 32, "models": {}}
    for slots in (1, 4):
        out = test(gsim, cxx, f"outstanding-bridge-{slots}", "ooo.TileLinkAxi4OutstandingGsimMain",
                   "TileLinkAxi4Bridge", "tilelink_axi4_outstanding.cpp", parameters=(str(slots),), defines={})
        rows = [dict(zip(("mode", "stress", "cycles", "transactions", "dbeats", "peak", "reordered"), m))
                for m in re.findall(r"OUTSTANDING_PASS mode=(\w+) stress=(\d+) cycles=(\d+) transactions=(\d+) dbeats=(\d+) peak=(\d+) reordered=(\d+)", (out / "test.log").read_text())]
        if len(rows) != 6 or "OUTSTANDING_ALL_PASS" not in (out / "test.log").read_text():
            raise RuntimeError("incomplete bridge coverage")
        report["models"][str(slots)] = rows
        for arg, anchor in (("--bad-last", "AXI read ID or RLAST mismatch"),
                            ("--bad-id", "AXI read ID or RLAST mismatch" if slots == 1 else "AXI R response has no live read owner"),
                            ("--inject-data", "independent TL data oracle mismatch")):
            p = subprocess.run([str(out / "run"), arg], capture_output=True, text=True,
                               env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}, timeout=120)
            (out / (arg[2:] + ".log")).write_text(p.stdout + p.stderr)
            if p.returncode == 0 or anchor not in p.stdout + p.stderr:
                raise RuntimeError("negative test did not reject: " + arg)
        if slots == 4 and not any(int(r["reordered"]) > 0 for r in rows):
            raise RuntimeError("reordering was not exercised")
    report["speedup"] = {mode: int(report["models"]["1"][i]["cycles"]) /
                         int(report["models"]["4"][i]["cycles"])
                         for i, mode in enumerate(("reads", "mixed"))}
    report["status"] = "passed"
    (BUILD / "outstanding-bridge.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
