#!/usr/bin/env python3
"""Focused engine-result holding and read-MSHR tests; no board or full regression."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from data_cache_geometry import module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--phase', choices=('engines', 'cache'), required=True)
    parser.add_argument('--lines', type=int, default=512)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): parser.error('Unsafe tag')
    if args.lines < 8 or args.lines > 512 or args.lines & (args.lines - 1): parser.error('lines must be8..512 power of two')
    cases = [('fill', 'ooo.TileLinkLineFillGsimMain', 'TileLinkLineFillGsim', 'line_fill.cpp', (), {}),
             ('acquire', 'ooo.TileLinkLineAcquireGsimMain', 'TileLinkLineAcquireGsim', 'line_acquire.cpp', (), {}),
             ('write', 'ooo.TileLinkLineWriteGsimMain', 'TileLinkLineWriteGsim', 'line_write.cpp', (), {})]
    if args.phase == 'cache':
        cases = [(f'cache-m{m}', 'ooo.CoherentReadMshrGsimMain', 'CoherentReadMshrGsim', 'coherent_read_mshr.cpp',
                  (m, args.lines, 2, 8), {'READ_MSHRS': m, 'CACHE_LINES': args.lines, 'CACHE_WAYS': 2}) for m in (1, 2, 4)]
    if args.dry_run:
        print(json.dumps(cases, indent=2)); return
    out = common.BUILD / ('read-mshr-' + args.phase + '-' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted((common.ROOT / 'src').rglob('*.scala')) + [Path(__file__),
        *[common.HERE / 'harness' / c[3] for c in cases]]
    def hashes(): return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'status': 'RUNNING', 'source_sha256': hashes(), 'cases': {},
              'scope': 'standalone engines/cache only; no real-home or board result'}
    try:
        gsim, cxx = common.setup(False)
        for name, main, top, harness, params, defines in cases:
            target = common.test(gsim, cxx, str(out.relative_to(common.BUILD) / name), main, top, harness,
                                 parameters=params, defines=defines, timeout=120)
            report['cases'][name] = {'log': (target / 'test.log').read_text()}
            if args.phase == 'cache':
                mshrs = params[0]
                fir = (target / (top + '.fir')).read_text()
                cache = module(fir, 'CoherentLineCache' if mshrs == 1 else 'NonBlockingCoherentLineCache')
                sets = args.lines // 2
                tag_bits = 58 - (sets.bit_length() - 1)
                assert f'reg tags : UInt<{tag_bits}>[{args.lines}]' in cache
                assert all(f'smem data_{bank} : UInt<8>[8][{args.lines}]' in cache for bank in range(8))
                if mshrs > 1:
                    assert f'regreset phase : UInt<3>[{mshrs}]' in cache
                    assert 'regreset responseOwned : UInt<1>[8]' in cache
                report['cases'][name]['geometry'] = {'lines': args.lines, 'ways': 2, 'mshrs': mshrs,
                    'response_entries': 8, 'tag_bits': tag_bits}
                result = subprocess.run([target / 'run', '--inject-mismatch'], capture_output=True, text=True,
                    timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                (target / 'negative.log').write_text(result.stdout + result.stderr)
                assert result.returncode != 0 and 'CPU independent data mismatch' in result.stdout + result.stderr
                report['cases'][name]['negative'] = 'PASS'
            (out / 'progress.json').write_text(json.dumps(report, indent=2) + '\n')
        assert hashes() == report['source_sha256'], 'source drift'
        report['status'] = 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        report['artifacts'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': main()
