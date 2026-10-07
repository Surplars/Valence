#!/usr/bin/env python3
"""Focused instruction-line cache packets: 64/128-bit, eight-byte offsets, precise fallback."""
import subprocess
import sys
from run import setup, test


def main():
    gsim, cxx = setup(False)
    for words in (2, 4):
        test(gsim, cxx, f"instruction-packet{words}-20261001",
             "ooo.InstructionLineCacheGsimMain", "InstructionLineCacheGsim",
             "instruction_line_cache.cpp", parameters=("no-prefetch", str(words)),
             defines={"PACKET_WORDS": words})


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as error:
        print(f"GSIM instruction packet: {error}", file=sys.stderr)
        sys.exit(1)
