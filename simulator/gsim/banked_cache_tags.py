#!/usr/bin/env python3
"""Opt-in FPGA tag topology proof with unchanged protocol drivers and paired replay.

The tests use real RTL with independent CPU/coherence/backing-memory oracles.
Memory geometry and ports are structural facts, not physical LUT/BRAM estimates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common
from data_cache_geometry import module

CASES = {
    'data-cross4g': ('ooo.CoherentReadMshrGsimMain', 'CoherentReadMshrGsim',
        'coherent_read_mshr.cpp', (2, 512, 2, 8, 1, 0xffff0000),
        {'READ_MSHRS': 2, 'CACHE_LINES': 512, 'CACHE_WAYS': 2,
         'CACHE_BASE': '0xffff0000ULL', 'COMPACT_TAG_TEST': 1}, 'NonBlockingCoherentLineCache'),
    'data-oneway': ('ooo.CoherentReadMshrGsimMain', 'CoherentReadMshrGsim',
        'coherent_read_mshr.cpp', (2, 16, 1, 8, 0, 0x80010000),
        {'READ_MSHRS': 2, 'CACHE_LINES': 16, 'CACHE_WAYS': 1}, 'NonBlockingCoherentLineCache'),
    'instruction': ('ooo.InstructionLineCacheGsimMain', 'InstructionLineCacheGsim',
        'instruction_line_cache.cpp', ('off', 4, 'lines=512', 'compact-tags'),
        {'PACKET_WORDS': 4, 'CACHE_LINES': 512, 'COMPACT_TAG_TEST': 1}, 'InstructionLineCache'),
    'instruction-prefetch': ('ooo.InstructionLineCacheGsimMain', 'InstructionLineCacheGsim',
        'instruction_line_prefetch.cpp', ('prefetch', 4, 'lines=512', 'compact-tags'),
        {'PACKET_WORDS': 4, 'CACHE_LINES': 512, 'COMPACT_TAG_TEST': 1}, 'InstructionLineCache'),
    'cache-home': ('ooo.CoherentCacheHomeGsimMain', 'CoherentCacheHomeGsim',
        'coherent_cache_home.cpp', (2, 512, 2, 1, 2, 1, 4, 1, 0),
        {'READ_MSHRS': 2, 'CACHE_LINES': 512, 'RESPONSE_ENTRIES': 2,
         'AXI_SLOTS': 4, 'MIXED_MODEL': 1, 'MIXED_RTL': 1}, 'NonBlockingCoherentLineCache'),
    'prefetch-owner': ('ooo.CoherentCacheHomeGsimMain', 'CoherentCacheHomeGsim',
        'prefetch_owner.cpp', (2, 8, 2, 1, 2, 1, 4, 1, 1),
        {'READ_MSHRS': 2, 'CACHE_LINES': 8, 'RESPONSE_ENTRIES': 2,
         'AXI_SLOTS': 4, 'MIXED_MODEL': 1, 'MIXED_RTL': 1}, 'NonBlockingCoherentLineCache'),
    'data-prefetch': ('ooo.CoherentCacheHomeGsimMain', 'CoherentCacheHomeGsim',
        'data_prefetch.cpp', (2, 512, 2, 1, 2, 1, 4, 1, 1),
        {'READ_MSHRS': 2, 'CACHE_LINES': 512, 'RESPONSE_ENTRIES': 2,
         'AXI_SLOTS': 4, 'MIXED_MODEL': 1, 'PREFETCH_BENCHMARK_MODEL': 1,
         'PREFETCH_ENABLED': 1}, 'NonBlockingCoherentLineCache'),
}


def geometry(fir, cache_name, banked):
    body = module(fir, cache_name)
    banks = re.findall(r'cmem (\w*tagBanks\w*) : UInt<(\d+)>\[(\d+)\]', body)
    if banked:
        assert banks, 'banked tag memories not emitted'
        assert not re.search(r'reg tags\b', body), 'flat tag registers remain'
        for name, _, _ in banks:
            reads = len(re.findall(r'read mport \w+ = ' + re.escape(name) + r'\[', body))
            writes = len(re.findall(r'write mport \w+ = ' + re.escape(name) + r'\[', body))
            assert reads in (1, 2) and writes == 1, (name, reads, writes)
        assert 'regreset valid' in body
    else:
        assert not banks and 'reg tags :' in body, 'legacy topology changed'
    return {'banks': [{'name': name, 'bits': int(bits), 'depth': int(depth)}
                      for name, bits, depth in banks],
            'physical_mapping': 'UNMEASURED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--case', action='append', choices=sorted(CASES))
    parser.add_argument('--build-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): parser.error('unsafe tag')
    cases = args.case or list(CASES)
    if not args.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'cases': cases, 'models': 2*len(cases),
                          'physical_mapping': 'UNMEASURED'}, indent=2)); return
    output = common.BUILD / args.tag
    output.mkdir(parents=True, exist_ok=False)
    paths = sorted((common.ROOT/'src').rglob('*.scala')) + [Path(__file__)] + [
        common.HERE/'harness'/name for name in sorted({case[2] for case in CASES.values()})]
    def hashes():
        return {str(path.relative_to(common.ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
    report = {'status': 'RUNNING', 'source_sha256': hashes(), 'cases': {},
              'scope': 'paired focused module/integration RTL checks; no CPU or FPGA result'}
    try:
        gsim, cxx = common.setup(False)
        for name in cases:
            main, top, harness, parameters, defines, cache = CASES[name]
            pair = {}
            for banked in (False, True):
                layout = 'banked' if banked else 'registers'
                model = common.test(gsim, cxx, f'{args.tag}/{name}-{layout}', main, top, harness,
                    parameters=(*parameters, *(('--banked-cache-tags',) if banked else ())),
                    defines=defines, timeout=180)
                log = (model/'test.log').read_text()
                structure = geometry((model/(top+'.fir')).read_text(), cache, banked)
                negative = subprocess.run([model/'run', '--corrupt-writeback' if name == 'prefetch-owner' else '--inject-mismatch'], capture_output=True,
                    text=True, timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                (model/'negative.log').write_text(negative.stdout + negative.stderr)
                assert negative.returncode != 0 and ('FAIL' in negative.stdout + negative.stderr), name
                if name == 'prefetch-owner':
                    live = subprocess.run([model/'run', '--live-prefetch-dirty'], capture_output=True,
                        text=True, timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                    (model/'live-prefetch-dirty.log').write_text(live.stdout + live.stderr)
                    assert live.returncode != 0 and 'prefetch must never generate dirty victim writeback' in live.stdout + live.stderr
                pair[layout] = {'log': log, 'geometry': structure, 'negative': 'PASS'}
                report['cases'][name] = pair
                (output/'progress.json').write_text(json.dumps(report, indent=2)+'\n')
            assert pair['registers']['log'] == pair['banked']['log'], (name, 'paired deterministic outcomes differ')
            pair['replay'] = 'CYCLE_AND_COUNTER_EQUIVALENT'
        assert hashes() == report['source_sha256'], 'source changed during proof'
        report['status'] = 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        (output/'receipt.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
