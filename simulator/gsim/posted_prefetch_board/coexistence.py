#!/usr/bin/env python3
"""Explicit coexistence Board model/runtime entry point; fresh qualification required."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
from profiles import COEXISTENCE
import run_board as runner

if __name__ == '__main__':
    try:
        sys.exit(runner.main(contract=COEXISTENCE, launcher=Path(__file__)))
    except Exception as error:
        print("FAIL_PREFLIGHT:", error, file=sys.stderr)
        sys.exit(1)
