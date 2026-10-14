#!/usr/bin/env python3
"""Focused multiplier owner-lifetime component oracle; no CPU or physical build."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from run import BUILD, setup, test

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    if not args.tag.replace('-', '').replace('_', '').isalnum():
        parser.error('unsafe tag')
    root = BUILD / ('mul-owner-lifetime-' + args.tag)
    root.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'RUNNING', 'scope': 'component only', 'default_enabled': False,
               'full_cpu': False, 'physical_metrics': 'UNMEASURED', 'cases': {}}
    try:
        gsim, cxx = setup(False)
        for registered in (False, True):
            logs = {}
            for bounded in (False, True):
                mode = ('registered' if registered else 'direct')
                side = ('bounded' if bounded else 'reference')
                key = side + '-' + mode
                output = test(gsim, cxx, str(root.relative_to(BUILD) / key),
                    'ooo.PipelinedMultiplyLifetimeGsimMain', 'PipelinedMultiplyLifetimeGsim',
                    'pipelined_mul_lifetime.cpp', parameters=(mode, 'bounded' if bounded else 'original'),
                    defines={'REGISTERED_MULTIPLY_OPERANDS': int(registered)})
                logs[side] = (output / 'test.log').read_text()
                if logs[side].count('GSIM PipelinedMultiply: PASS') != 5:
                    raise RuntimeError('missing reset/coverage cases')
                receipt['cases'][key] = logs[side]
                with (output / 'observation-negative.log').open('w') as f:
                    result = subprocess.run([output / 'run', '--inject-mismatch'], stdout=f,
                        stderr=subprocess.STDOUT, timeout=120,
                        env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                negative = (output / 'observation-negative.log').read_text()
                if result.returncode != 1 or 'FAIL pipelined arithmetic mismatch' not in negative:
                    raise RuntimeError('observation negative did not fail as expected')
            if logs['reference'] != logs['bounded']:
                raise RuntimeError('matched reference/candidate coverage differs')
        receipt['status'] = 'PASS_COMPONENT_ONLY'
    except Exception as error:
        receipt['status'] = 'FAIL'
        receipt['error'] = str(error)
        raise
    finally:
        (root / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

if __name__ == '__main__':
    main()
