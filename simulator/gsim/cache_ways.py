#!/usr/bin/env python3
"""Focused one/two-way L1 alias, masked-write, dirty eviction, probe and flush checks."""
import subprocess
import sys
from run import setup, test


def main():
    gsim, cxx = setup(False)
    for ways in (1, 2):
        test(gsim, cxx, f"coherent-cache-ways{ways}", "ooo.CoherentCacheWaysGsimMain",
             "CoherentCacheWaysGsim", "coherent_cache_ways.cpp",
             parameters=(str(ways),), defines={"CACHE_WAYS": ways}, sanitizer=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM cache ways: {error}", file=sys.stderr)
        sys.exit(1)
