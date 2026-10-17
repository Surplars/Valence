#!/usr/bin/env python3
"""Focused recovery-candidate component check; no CPU, board or timing claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, help='Explicit repaired GSIM binary; leaves pinned baseline untouched')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('unsafe tag')
    if args.gsim:
        gsim = args.gsim.resolve(strict=True)
        cxx, _ = common.compiler()
    else:
        gsim, cxx = common.setup(False)
    sources = [common.ROOT / p for p in (
        'src/main/scala/core/ooo/frontend/PacketFetchPmp.scala',
        'src/main/scala/core/ooo/mmu/PhysicalMemoryProtection.scala',
        'src/main/scala/core/ooo/mmu/InstructionTranslationAdapter.scala',
        'src/main/scala/core/ooo/platform/memory/InstructionRom.scala',
        'src/test/scala/ooo/SharedTwoWordFetchPmpGsim.scala',
        'src/test/scala/ooo/SharedTwoWordFetchPmpSpec.scala',
        'simulator/gsim/harness/shared_two_word_fetch_pmp.cpp',
        'simulator/gsim/shared_two_word_fetch_pmp.py')]
    before = {str(p.relative_to(common.ROOT)): sha(p) for p in sources}
    binary_hash = sha(gsim)
    output = common.test(gsim, cxx, args.tag, 'ooo.SharedTwoWordFetchPmpGsimMain',
                         'SharedTwoWordFetchPmpGsim', 'shared_two_word_fetch_pmp.cpp', timeout=120)
    assert 'SHARED_TWO_WORD_PMP_PASS' in (output / 'test.log').read_text()
    for name, reason in (
            ('granule', 'word PMP requires complete decoded four-byte region granules'),
            ('alignment', 'shared fetch PMP requires an eight-byte aligned packet')):
        negative = subprocess.run([str(output / 'run'), '--contract-' + name], capture_output=True,
                                  text=True, timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        text = negative.stdout + negative.stderr
        (output / ('contract-' + name + '.log')).write_text(text)
        assert negative.returncode != 0 and reason in text
        assert 'NEGATIVE_CONTROL_ESCAPED' not in text
    assert before == {str(p.relative_to(common.ROOT)): sha(p) for p in sources}, 'source changed during proof'
    assert binary_hash == sha(gsim), 'GSIM binary changed during proof'
    (output / 'candidate-receipt.json').write_text(json.dumps({
        'status': 'PASS_COMPONENT_ONLY', 'source_sha256': before,
        'gsim_path': str(gsim), 'gsim_sha256': binary_hash,
        'decoded_domain': '65-bit bounds, complete active four-byte granules',
        'raw_domain': '54-bit raw addresses, baseline 56-bit physical mask truncation',
        'unbounded_napot_oracle': 'not equivalent above 2^56 for max54-ones encoding',
        'caller_behavior': 'UNVERIFIED', 'physical_metrics': 'UNMEASURED'}, indent=2) + '\n')
    print('PASS_COMPONENT_ONLY; granule/alignment rejection checked; physical metrics UNMEASURED')


if __name__ == '__main__':
    main()
