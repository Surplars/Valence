#!/usr/bin/env python3
"""Focused 128 KiB ROM Native/TileLink interface boundary and backpressure check."""
from run import setup, test

if __name__ == "__main__":
    gsim, cxx = setup(False)
    test(gsim, cxx, "board-rom", "ooo.BoardRomGsimMain", "BoardRomGsim", "board_rom.cpp")
