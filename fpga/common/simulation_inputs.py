#!/usr/bin/env python3
"""Validate vendor TAP model identities before using the public independent oracle."""
import argparse
import importlib.util
from pathlib import Path
import sys
import manifest as gate


def validate(root, vendor):
    script = root / 'simulator/jtag/run_xsim.py'
    spec = importlib.util.spec_from_file_location('public_jtag_oracle', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profile = module.select_model('vivado-2025.1-xczu15eg')
    actual = {name: gate.sha(vendor / name) for name in profile['source_sha256']}
    module.validate_vendor_hashes(profile, actual)
    return actual


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True, type=Path)
    p.add_argument('--vendor', required=True, type=Path)
    a = p.parse_args()
    try:
        print(validate(a.root, a.vendor))
    except (ValueError, OSError, RuntimeError) as e:
        print('COMMON_VENDOR_MODEL_BLOCKED: ' + str(e), file=sys.stderr)
        sys.exit(1)
