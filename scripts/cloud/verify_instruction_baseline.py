#!/usr/bin/env python3
"""Freeze baseline permission models and prove their original positive/negative checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'simulator/gsim'))
import run

BASE = run.BUILD / 'cloud-baseline-20261007'
CONFIGS = [
    ('2-1-0', 2, 1, 0, ('2', 'retimed')),
    ('2-1-1', 2, 1, 1, ('2', 'retimed', 'aligned')),
    ('4-1-1', 4, 1, 1, ('4', 'retimed', 'aligned')),
    ('2-0-0', 2, 0, 0, ('2',)),
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (BASE / 'instruction-permission-receipt.json').exists():
        raise RuntimeError('Refusing to overwrite a frozen baseline receipt')
    sources = [p for prefix in ('src/main/scala', 'src/test/scala', 'third_party/berkeley-hardfloat/src/main/scala')
               for p in sorted((ROOT / prefix).rglob('*.scala'))]
    sources += [ROOT / 'simulator/gsim/harness/instruction_permission.cpp', ROOT / 'build.mill']
    before = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    gsim, cxx = run.setup(False)
    results = []
    for key, words, retimed, aligned, parameters in CONFIGS:
        name = 'cloud-baseline-20261007/instruction-permission-' + key
        output = run.test(gsim, cxx, name, 'ooo.InstructionPermissionGsimMain',
                          'InstructionPermissionGsim', 'instruction_permission.cpp', parameters=parameters,
                          defines={'PACKET_WORDS': words, 'RETIMED_PERMISSIONS': retimed, 'ALIGNED_PACKET': aligned},
                          timeout=180)
        negative = subprocess.run([str(output / 'run'), '--inject-mismatch'],
                                  env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'},
                                  capture_output=True, text=True, timeout=180)
        (output / 'negative.log').write_text(negative.stdout + negative.stderr)
        if negative.returncode != 1 or 'GSIM instruction permission: FAIL independent I-fetch permission oracle mismatch' not in negative.stderr:
            raise RuntimeError('Negative oracle did not reject the mismatch: ' + key)
        results.append({'configuration': key, 'positive_log': (output / 'test.log').read_text(),
                        'negative_exit': negative.returncode, 'negative_log': negative.stderr,
                        'files': {str(p.relative_to(ROOT)): digest(p) for p in sorted(output.iterdir()) if p.is_file()}})
    if before != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise RuntimeError('Sources changed during baseline generation')
    receipt = {'status': 'PASS_FROZEN_INSTRUCTION_PERMISSION_BASELINE',
               'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               'source_sha256': before, 'configurations': results,
               'limits': ['Focused adapter checks only; no CPU/board/timing or throughput claim.']}
    (BASE / 'instruction-permission-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(receipt['status'])


if __name__ == '__main__':
    main()
