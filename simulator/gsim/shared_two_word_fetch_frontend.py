#!/usr/bin/env python3
"""Short paired configured SynchronousFetch check; no whole-board/physical claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common

EXPECTED_GSIM = 'f00067c6158db342927ad0d746109ad745298fd4ebe9707fd951998069587116'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--gsim', type=Path, required=True)
    parser.add_argument('--board-export', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('unsafe tag')
    gsim = args.gsim.resolve(strict=True)
    board = args.board_export.resolve(strict=True)
    assert sha(gsim) == EXPECTED_GSIM, 'requires reviewed isolated repaired GSIM; does not replace installed baseline'
    output = common.BUILD / args.tag
    assert not output.exists(), 'fresh output required'
    files = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [common.ROOT / name for name in (
        'src/test/scala/ooo/SharedTwoWordFetchFrontendGsim.scala',
        'src/test/scala/ooo/ThreeProofRowNativeProfile.scala',
        'simulator/gsim/compact_fetch_keys/compact_fetch_frontend.cpp',
        'simulator/gsim/compact_fetch_keys/compact_fetch_frontend_oracle.h',
        'simulator/gsim/shared_two_word_fetch_frontend.py', 'simulator/gsim/run.py')]
    sources = {str(p.relative_to(common.ROOT)): sha(p) for p in files}
    board_hash = sha(board)
    cxx, version = common.compiler()
    output = common.test(gsim, cxx, args.tag, 'ooo.SharedTwoWordFetchFrontendGsimMain',
                         'SharedTwoWordFetchFrontendGsim', '../compact_fetch_keys/compact_fetch_frontend.cpp', parameters=(str(board),),
                         defines={'CACHE_SETS': 16, 'FETCH_WINDOW': 1, 'FETCH_STAGED': 1,
                                  'SHARED_TWO_WORD_FRONTEND_PAIR': 1}, timeout=120)
    text = (output / 'test.log').read_text()
    assert 'SHARED_TWO_WORD_FRONTEND_PAIR_PASS' in text
    controls = []
    for flag, reason in (
            ('--inject-oracle-mismatch', 'COMPACT_FRONTEND_ORACLE request PMP mask'),
            ('--inject-pair-mismatch', 'shared two-word frontend full IO mismatch')):
        result = subprocess.run([str(output / 'run'), flag], text=True, capture_output=True,
                                timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        log = result.stdout + result.stderr
        (output / (flag[2:] + '.log')).write_text(log)
        assert result.returncode != 0 and reason in log, (flag, result.returncode, log)
        assert not any(x in log for x in ('ERROR: AddressSanitizer', 'runtime error:'))
        controls.append({'flag': flag, 'exit': result.returncode, 'logSha256': sha(output / (flag[2:] + '.log'))})
    assert sources == {str(p.relative_to(common.ROOT)): sha(p) for p in files}, 'sources changed during check'
    assert sha(gsim) == EXPECTED_GSIM and sha(board) == board_hash, 'input changed during check'
    (output / 'receipt.json').write_text(json.dumps({
        'status': 'PASS_PAIRED_CONFIGURED_SYNCHRONOUS_FETCH_ONLY',
        'sourceSha256': sources, 'gsimPath': str(gsim), 'gsimSha256': EXPECTED_GSIM,
        'compiler': version, 'boardExportSha256': board_hash,
        'configuration': json.loads((output / 'experimental-frontend-config.json').read_text()),
        'negativeControls': controls, 'negativeControlScope': 'oracle and comparison-observer injection, not DUT source mutants',
        'validityScope': 'full deterministic OFF/ON IO equality; independent oracle only on owned/offered transactions',
        'pmpOracleScope': 'one raw PMP entry active, remaining fifteen OFF; broad raw states are separate helper proof',
        'cancellationScope': 'actual enable/pause/invalidate/suppress/context preparation cancellation, stale accepted replies, whole-interface reset with external obligation discarded',
        'liveCsrChurn': 'adversarial isolation stimulus, not permission to violate architectural drain barrier',
        'frontendQualificationScope': 'bounded 16-set same-config OFF/ON paired fixture with independent owner/cache/PMP oracle', 'wholeBoardQualified': False, 'physicalQualification': False,
        'testLogSha256': sha(output / 'test.log'),
        'artifactSha256': {str(p.relative_to(output)): sha(p) for p in sorted(output.rglob('*'))
                           if p.is_file() and p.name != 'receipt.json'}}, indent=2) + '\n')
    print('PASS_CONFIGURED_FRONTEND_PAIR_ONLY; independent cache/owner oracle and two observer negatives; no whole-board/physical claim')


if __name__ == '__main__':
    main()
