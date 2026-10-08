#!/usr/bin/env python3
"""Explicit 32 KiB I/D candidate and bounded independent checks. No full regression."""
import argparse
import hashlib
import json
import re
import os
import subprocess
from pathlib import Path
import run as common
from data_cache_geometry import verify
from frontend_perf import verify_instruction_geometry
from memory_capacity_geometry import verify_memory_geometry
from control_stage import negative

CONFIG = Path(__file__).parent / 'config/cache32k-candidate.json'

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--phase', choices=('checks', 'board-fir', 'managed-export'), required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): ap.error('Unsafe tag')
    cfg = json.loads(CONFIG.read_text())
    out = common.BUILD / ('cache32k-' + args.phase + '-' + args.tag)
    command = ['mill', '-i', 'IonSoC.test.runMain',
               'ooo.ManagedBoardSocMain' if args.phase == 'managed-export' else 'ooo.BoardSocGsimMain',
               str(out), *cfg['managed_export_args' if args.phase == 'managed-export' else 'board_gsim_args']]
    if args.dry_run:
        print(json.dumps({'configuration': cfg, 'output': str(out), 'command': command if args.phase != 'checks' else
            ['I-cache 512 lines, D-cache 512 lines, full coherent home plus DMA; corruption negatives']}, indent=2))
        return
    out.mkdir(parents=True, exist_ok=False)
    sources = sorted((common.ROOT / 'src').rglob('*.scala')) + [CONFIG, Path(__file__),
        *[common.HERE / 'harness' / p for p in ('instruction_line_cache.cpp', 'coherent_cache_ways.cpp', 'ethernet_packet_dma.cpp')]]
    def hashes(): return {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {'configuration': cfg, 'source_sha256': hashes(), 'status': 'RUNNING'}
    try:
        if args.phase == 'checks':
            gsim, cxx = common.setup(False)
            report['checks'] = {}
            cases = [('icache', 'ooo.InstructionLineCacheGsimMain', 'InstructionLineCacheGsim',
                      'instruction_line_cache.cpp', ('no-prefetch', '2', 'lines=512'),
                      {'PACKET_WORDS': 2, 'CACHE_LINES': 512}, 'instruction cache returned incorrect code'),
                     ('dcache', 'ooo.CoherentCacheWaysGsimMain', 'CoherentCacheWaysGsim',
                      'coherent_cache_ways.cpp', (2, 512), {'CACHE_WAYS': 2, 'CACHE_LINES': 512}, 'CPU data mismatch'),
                     ('directory', 'ip.EthernetDmaCoherenceGsimMain', 'EthernetDmaCoherenceGsim',
                      'ethernet_packet_dma.cpp', (512,), {'COHERENT_DMA': 1, 'DCACHE_CAPACITY': 512},
                      'TX independent byte oracle mismatch')]
            for name, main, top, harness, params, defines, error in cases:
                target = common.test(gsim, cxx, str(out.relative_to(common.BUILD) / name), main, top, harness,
                                     parameters=params, defines=defines)
                fir = (target / (top + '.fir')).read_text()
                geometry = verify_instruction_geometry(fir, 512) if name == 'icache' else verify(fir, 512, home=name == 'directory')
                if name == 'dcache':
                    result = subprocess.run([target / 'run', '--inject-corruption'], capture_output=True,
                        text=True, timeout=120, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                    (target / 'negative.log').write_text(result.stdout + result.stderr)
                    assert result.returncode == 1 and error in result.stdout + result.stderr
                else:
                    negative(target / 'run', (), error, target / 'negative.log')
                report['checks'][name] = {'geometry': geometry, 'log': (target / 'test.log').read_text(), 'negative': 'PASS'}
                (out / 'progress.json').write_text(json.dumps(report, indent=2) + '\n')
        else:
            common.run(command, log=out / 'elaborate.log')
            if args.phase == 'board-fir':
                fir = (out / 'BoardSocGsim.fir').read_text()
                report['instruction_geometry'] = verify_instruction_geometry(fir, 512)
                report['data_geometry'] = verify(fir, 512)
                report['lsu_geometry'] = verify_memory_geometry(fir, 2)
                assert '0h100200000' in fir
        assert hashes() == report['source_sha256'], 'source drift during checks'
        report['status'] = 'PASS_' + args.phase.upper().replace('-', '_')
    except Exception as e:
        report['status'] = 'FAIL'; report['error'] = str(e); raise
    finally:
        report['artifact_sha256'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(out / 'receipt.json')

if __name__ == '__main__': main()
