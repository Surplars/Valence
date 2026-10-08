#!/usr/bin/env python3
"""Isolated compact-tag proof; no board execution or physical mapping claims."""
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): ap.error('unsafe tag')
    cases = []
    for m, compact in ((1, 0), (1, 1), (2, 0), (2, 1), (4, 1)):
        cases.append((f'data-m{m}-compact{compact}', 'ooo.CoherentReadMshrGsimMain',
            'CoherentReadMshrGsim', 'coherent_read_mshr.cpp', (m, 512, 2, 8, compact, 0xffff0000),
            {'READ_MSHRS': m, 'CACHE_LINES': 512, 'CACHE_WAYS': 2,
             'CACHE_BASE': '0xffff0000ULL', 'COMPACT_TAG_TEST': 1}))
    for m in (1, 2, 4):
        cases.append((f'home-m{m}', 'ooo.HomeMshrGsimMain', 'HomeMshrGsim', 'home_mshr.cpp',
            (m, 1, 0xfffff000), {'HOME_ENTRIES': m, 'HOME_BASE': '0xfffff000ULL', 'COMPACT_TAG_TEST': 1}))
    cases.append(('home-m1-parallel', 'ooo.HomeMshrGsimMain', 'HomeMshrGsim', 'home_mshr.cpp',
        (1, 1, 0xfffff000, 1), {'HOME_ENTRIES': 1, 'HOME_BASE': '0xfffff000ULL', 'COMPACT_TAG_TEST': 1}))
    for words in (2, 4):
        cases.append((f'instruction-w{words}', 'ooo.InstructionLineCacheGsimMain',
            'InstructionLineCacheGsim', 'instruction_line_cache.cpp', ('off', words, 'lines=512', 'compact-tags'),
            {'PACKET_WORDS': words, 'CACHE_LINES': 512, 'COMPACT_TAG_TEST': 1}))
    cases.append(('instruction-prefetch', 'ooo.InstructionLineCacheGsimMain', 'InstructionLineCacheGsim',
        'instruction_line_prefetch.cpp', ('prefetch', 4, 'lines=512', 'compact-tags'),
        {'PACKET_WORDS': 4, 'CACHE_LINES': 512, 'COMPACT_TAG_TEST': 1}))
    if args.dry_run:
        print(json.dumps(cases, indent=2)); return
    out = common.BUILD / ('compact-tags-' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted((common.ROOT/'src').rglob('*.scala')) + [Path(__file__),
        *[common.HERE/'harness'/h for h in sorted({c[3] for c in cases})]]
    def hashes(): return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'status': 'RUNNING', 'source_sha256': hashes(), 'cases': {},
              'scope': 'independent cache/home/instruction oracles; no CPU/physical area/timing result'}
    try:
        gsim, cxx = common.setup(False)
        for name, main, top, harness, params, defines in cases:
            target = common.test(gsim, cxx, str(out.relative_to(common.BUILD)/name), main, top, harness,
                parameters=params, defines=defines, timeout=180)
            entry = {'log': (target/'test.log').read_text()}
            fir = (target/(top+'.fir')).read_text()
            if name.startswith('data-'):
                m, _, _, _, compact, _ = params
                cache = module(fir, 'CoherentLineCache' if m == 1 else 'NonBlockingCoherentLineCache')
                bits = 19 if compact else 50
                assert f'reg tags : UInt<{bits}>[512]' in cache
                assert all(f'smem data_{i} : UInt<8>[8][512]' in cache for i in range(8))
                negative = [('--inject-mismatch', 'CPU independent data mismatch')]
            elif name.startswith('home-'):
                m = params[0]
                home = module(fir, 'CoherentLineHome' if m == 1 else 'NonBlockingCoherentLineHome')
                assert f'reg {"ownedTags" if m == 1 else "tags"} : UInt<27>[16]' in home
                negative = [('--inject-data', 'independent Grant data mismatch'),
                    ('--bad-aperture', 'home accepts an aligned' if m == 1 else 'home accepts only an aligned unowned'),
                    ('--bad-release-aperture', 'invalid voluntary line release' if m == 1 else 'release has no committed directory owner')]
            else:
                assert 'reg tags : UInt<18>[2][256]' in module(fir, 'InstructionLineCache')
                negative = [('--inject-mismatch', 'FAIL')]
            entry['negative'] = {}
            for flag, expected in negative:
                r = subprocess.run([target/'run', flag], capture_output=True, text=True, timeout=180,
                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                log = r.stdout+r.stderr
                (target/(flag[2:]+'.log')).write_text(log)
                assert r.returncode != 0 and expected in log, (name, flag, log[-1000:])
                entry['negative'][flag] = 'PASS'
            report['cases'][name] = entry
            (out/'progress.json').write_text(json.dumps(report, indent=2)+'\n')
        assert hashes() == report['source_sha256'], 'source drift'
        report['status'] = 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        (out/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')

if __name__ == '__main__': main()
