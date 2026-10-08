#!/usr/bin/env python3
"""Real cache/home/atomic-DMA/AXI integration. Small models only, never a CPU simulation."""
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
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): ap.error('Unsafe tag')
    cases = [(1, 2), (2, 2), (4, 4)]
    if args.dry_run:
        print(json.dumps({'cases': cases, 'lines': 512, 'ways': 2, 'axi_slots': 4, 'burst_beats': 8,
            'scope': 'real cache/home/atomic-DMA/AXI, independent backing and request oracle; no CPU'}, indent=2)); return
    out = common.BUILD / ('cache-home-mshr-' + args.tag)
    out.mkdir(parents=True, exist_ok=False)
    paths = sorted((common.ROOT / 'src').rglob('*.scala')) + [Path(__file__),
        common.HERE / 'harness/coherent_cache_home.cpp', common.HERE / 'harness/board_ddr_multiid.h']
    def hashes(): return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report = {'status': 'RUNNING', 'source_sha256': hashes(), 'cases': {},
              'scope': 'cache/home/atomic-DMA/AXI integration; no CPU/Linux/physical DDR/timing result',
              'fixed': {'lines': 512, 'ways': 2, 'axi_read_slots': 4, 'max_burst_beats': 8,
                        'host_read_latency': 32, 'steady_replacement_lines': 1024}}
    try:
        gsim, cxx = common.setup(False)
        for mshrs, responses in cases:
            name = f'm{mshrs}-r{responses}'
            target = common.test(gsim, cxx, str(out.relative_to(common.BUILD) / name),
                'ooo.CoherentCacheHomeGsimMain', 'CoherentCacheHomeGsim', 'coherent_cache_home.cpp',
                parameters=(mshrs, 512, responses),
                defines={'READ_MSHRS': mshrs, 'CACHE_LINES': 512, 'RESPONSE_ENTRIES': responses}, timeout=180)
            fir = (target / 'CoherentCacheHomeGsim.fir').read_text()
            cache = module(fir, 'CoherentLineCache' if mshrs == 1 else 'NonBlockingCoherentLineCache')
            home = module(fir, 'CoherentLineHome' if mshrs == 1 else 'NonBlockingCoherentLineHome')
            assert 'reg tags : UInt<50>[512]' in cache
            assert all(f'smem data_{i} : UInt<8>[8][512]' in cache for i in range(8))
            assert 'regreset owned : UInt<1>[512]' in home
            if mshrs > 1:
                assert f'regreset phase : UInt<3>[{mshrs}]' in cache
                assert f'regreset phase : UInt<3>[{mshrs}]' in home
                assert f'regreset responseOwned : UInt<1>[{responses}]' in cache
            assert 'regreset active : UInt<1>[4]' in module(fir, 'TileLinkAxi4OutstandingBridge')
            assert 'reg readData : UInt<64>[8]' in module(fir, 'TileLinkAxi4BurstBridge')
            log = (target / 'test.log').read_text()
            assert f'CACHE_HOME_PASS mshrs={mshrs}' in log
            negative = subprocess.run([target / 'run', '--inject-mismatch'], capture_output=True, text=True,
                timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            (target / 'negative.log').write_text(negative.stdout + negative.stderr)
            assert negative.returncode != 0 and 'CPU independent byte oracle mismatch' in negative.stdout + negative.stderr
            report['cases'][name] = {'log': log, 'negative': 'PASS', 'geometry': 'PASS',
                'generated_cpp_bytes': sum(p.stat().st_size for p in target.glob('CoherentCacheHomeGsim[0-9]*.cpp'))}
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
