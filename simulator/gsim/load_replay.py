#!/usr/bin/env python3
"""Focused zero-latency load replay selection with an independent circular ROB oracle."""
import os
import subprocess
from run import setup, test


def main():
    gsim, cxx = setup(False)
    output = test(gsim, cxx, "load-replay-selector-20261001", "ooo.LoadReplaySelectorGsimMain",
                  "LoadReplaySelectorGsim", "load_replay_selector.cpp", timeout=120)
    with (output / "negative-test.log").open("w") as stream:
        result = subprocess.run([output / "run", "--inject-mismatch"], stdout=stream,
                                stderr=subprocess.STDOUT, timeout=30,
                                env={**os.environ, "ASAN_OPTIONS": "detect_leaks=0"})
    if result.returncode != 1 or "independent oracle mismatch" not in (output / "negative-test.log").read_text():
        raise RuntimeError("replay selector mismatch was not rejected")
    print("GSIM load replay selector negative oracle: PASS", flush=True)


if __name__ == "__main__":
    main()
