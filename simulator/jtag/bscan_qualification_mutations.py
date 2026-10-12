#!/usr/bin/env python3
"""Compatibility entrypoint for the versioned phased fault controls.

Original nine-mutant source and qualified receipt are preserved unchanged in
simulator/jtag/evidence/bscan-prephase. Its immediate-revoke expectation remains
an old-contract counterexample, never relabeled as a phased-contract pass.
"""
from bscan_fault_phase_run import main
if __name__ == "__main__":
    import sys
    sys.argv.append("--mutants-only")
    raise SystemExit(main())
