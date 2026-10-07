#!/usr/bin/env python3
"""Focused two/four-wide compressed fetch, packet/wrap boundary and fault checks."""
import subprocess
import sys
from run import setup, test


def main():
    gsim, cxx = setup(False)
    for width in (2, 4):
        test(gsim, cxx, f"fetch-offsets-{width}", "ooo.FetchOffsetsGsimMain",
             "FetchOffsetsGsim", "fetch_offsets.cpp", parameters=(str(width),),
             defines={"FETCH_WIDTH": width}, sanitizer=True)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM fetch offsets: {error}", file=sys.stderr)
        sys.exit(1)
