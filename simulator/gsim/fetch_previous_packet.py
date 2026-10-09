#!/usr/bin/env python3
"""Bounded registered fetch-window history checks, OFF/ON at capacities 3 and 5."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.tag):
        parser.error("Unsafe tag")
    out = common.BUILD / ("fetch-previous-packet-" + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    sources = [common.ROOT / name for name in (
        "src/main/scala/core/ooo/RegisteredFetchWindow.scala",
        "src/main/scala/core/ooo/ParallelFetchAlignment.scala",
        "src/test/scala/ooo/RegisteredFetchWindowGsim.scala",
        "simulator/gsim/harness/registered_fetch_window.cpp",
        "simulator/gsim/fetch_previous_packet.py", "simulator/gsim/run.py", "build.mill")]
    before = {str(path.relative_to(common.ROOT)): sha(path) for path in sources}
    receipt = dict(status="RUNNING", source_sha256=before, checks={}, model_sha256={},
                   limits=["Isolated OFF/ON window and existing mixed16/32 alignment helper only.",
                           "No full CPU/board simulation, Linux, FPGA timing, or implementation proof."],
                   oracle="Time-indexed maps of literal 64-bit addresses; no compressed DUT key algorithm.")
    env = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0"}
    try:
        gsim, cxx = common.setup(False)
        for capacity in (3, 5):
            for history in (False, True):
                name = f"capacity-{capacity}-history-{int(history)}"
                model = common.test(
                    gsim, cxx, out.name + "/" + name,
                    "ooo.RegisteredFetchWindowGsimMain", "RegisteredFetchWindowGsim",
                    "registered_fetch_window.cpp",
                    parameters=(str(capacity), "true") if history else (str(capacity),),
                    defines={"WINDOW_CAPACITY": capacity, "WINDOW_PREVIOUS_PACKET": int(history)},
                    timeout=120)
                receipt["checks"][name] = {"positive": (model / "test.log").read_text().strip(), "negative": {}}
                negatives = ("mismatch", "lost-tag", "context", "access-fault", "page-fault",
                             "invalidation", "priority", "capture") if history else ("mismatch",)
                for negative in negatives:
                    result = subprocess.run([str(model / "run"), "--inject-" + negative],
                                            env=env, capture_output=True, text=True, timeout=120)
                    log = result.stdout + result.stderr
                    (model / ("negative-" + negative + ".log")).write_text(log)
                    if (result.returncode != 1 or "fetch window independent oracle mismatch:" not in log or
                            "negative=" + negative not in log):
                        raise RuntimeError("Independent negative control not rejected at its witness: " +
                                           name + "/" + negative)
                    receipt["checks"][name]["negative"][negative] = log.strip()
                receipt["model_sha256"][name] = {
                    str(path.relative_to(common.ROOT)): sha(path) for path in model.iterdir()
                    if path.is_file() and (path.name == "run" or path.suffix in (".fir", ".cpp", ".h"))}
                (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if before != {str(path.relative_to(common.ROOT)): sha(path) for path in sources}:
            raise RuntimeError("Window/oracle source changed during suite; receipt withheld")
        receipt["status"] = "PASS_FETCH_PREVIOUS_PACKET_AFFECTED_SHORT"
    except Exception as error:
        receipt["status"] = "FAILED"
        receipt["failure"] = str(error)
        raise
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(receipt["status"], flush=True)


if __name__ == "__main__":
    main()
