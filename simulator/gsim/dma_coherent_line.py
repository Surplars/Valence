#!/usr/bin/env python3
"""Source-bound integrated DMA/cache/home/AXI measurements, independent host DDR and byte oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--line', action='store_true')
    ap.add_argument('--line-yield-cycles', type=int, default=0)
    ap.add_argument('--smoke', action='store_true')
    ap.add_argument('--rebuild-driver', action='store_true', help='Reuse hash-verified generated RTL and rebuild only changed C++ driver')
    ap.add_argument('--reuse', action='store_true', help='Run an already generated matching binary')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag): ap.error('Unsafe tag')
    if not 0 <= args.line_yield_cycles <= 64 or (args.line_yield_cycles and not args.line):
        ap.error('Line yield must be in 0..64 and nonzero yield requires --line')
    name = 'dma-coherent-line-' + args.tag
    out = common.BUILD / name
    sources = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        common.ROOT / 'src/test/scala/ooo/DmaCoherentLineGsim.scala', Path(__file__),
        common.HERE / 'harness/dma_coherent_line.cpp', common.HERE / 'harness/dma_coherent_ddr.h']
    hashes = lambda: {str(p.relative_to(common.ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    report = {'status': 'RUNNING', 'line': args.line, 'line_yield_cycles': args.line_yield_cycles, 'clock_MHz': 100,
              'scope': 'MemoryCopyDma + real cache + atomic boundary + mixed home + AXI host DDR model; no CPU execution/physical DDR/timing',
              'source_sha256': hashes(), 'host': {'R_delay': 32, 'B_delay': 40, 'read_credits': 4,
              'write_credits': 2, 'max_burst_beats': 16, 'stall_moduli': [7, 11, 5]},
              'geometry': {'base': '0x80200000', 'bytes': 2147483648, 'tags': 'compact+banked', 'cache_lines': 512, 'cache_ways': 2, 'read_mshrs': 2, 'response_entries': 2, 'writeback_entries': 2, 'prefetch': False},
              'payload_bytes': [512, 4096, 131072], 'negative_controls': {}}
    if args.dry_run:
        print(json.dumps(report, indent=2)); return
    out.mkdir(parents=True, exist_ok=True)
    try:
        if args.rebuild_driver:
            previous = json.loads((out / 'receipt.json').read_text())
            if previous['line'] != args.line or previous.get('line_yield_cycles', 0) != args.line_yield_cycles:
                raise RuntimeError('Cannot change RTL mode while reusing a model')
            for path, digest in previous['source_sha256'].items():
                if path.startswith('src/') and report['source_sha256'].get(path) != digest:
                    raise RuntimeError('DUT/wrapper source changed; refusing generated model reuse: ' + path)
            for path, digest in previous['artifacts_sha256'].items():
                if path.endswith(('.fir', '.h', '.cpp')) and hashlib.sha256((out / path).read_bytes()).hexdigest() != digest:
                    raise RuntimeError('Generated model artifact changed: ' + path)
            cxx, _ = common.compiler()
            common.run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-DDMA_LINE_ENABLED=' + str(int(args.line)), '-DDMA_LINE_YIELD_CYCLES=' + str(args.line_yield_cycles), '-I' + str(out),
                        *sorted(out.glob('DmaCoherentLineGsim[0-9]*.cpp')), common.HERE / 'harness/dma_coherent_line.cpp',
                        '-ldl', '-o', out / 'run'], log=out / 'compile.log')
            (out / 'binary-source.json').write_text(json.dumps(report['source_sha256'], indent=2) + '\n')
            common.run([out / 'run', *(['--smoke'] if args.smoke else [])], log=out / 'test.log', timeout=1200,
                       env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        elif not args.reuse:
            if (out / 'run').exists(): raise RuntimeError('Existing binary: choose a fresh tag or --reuse')
            gsim, cxx = common.setup(False)
            common.test(gsim, cxx, name, 'ooo.DmaCoherentLineGsimMain', 'DmaCoherentLineGsim',
                        'dma_coherent_line.cpp', parameters=(int(args.line), args.line_yield_cycles),
                        defines={'DMA_LINE_ENABLED': int(args.line), 'DMA_LINE_YIELD_CYCLES': args.line_yield_cycles}, runtime_args=('--smoke',) if args.smoke else (), timeout=1200)
            (out / 'binary-source.json').write_text(json.dumps(report['source_sha256'], indent=2) + '\n')
        else:
            previous = json.loads((out / 'receipt.json').read_text())
            if previous['line'] != args.line or previous.get('line_yield_cycles', 0) != args.line_yield_cycles:
                raise RuntimeError('Cannot change RTL mode while reusing a model')
            if json.loads((out / 'binary-source.json').read_text()) != report['source_sha256']:
                raise RuntimeError('Source mismatch: cannot reuse stale generated model')
            common.run([out / 'run', *(['--smoke'] if args.smoke else [])], log=out / 'test.log', timeout=1200,
                       env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        report['cases'] = []; report['cpu_port_only'] = []; report['combined'] = []
        for line in (out / 'test.log').read_text().splitlines():
            if line.startswith('DMA_BENCH '):
                report['cases'].append({k: float(v) if '.' in v else int(v) for k, v in
                                        (field.split('=', 1) for field in line.split()[1:])})
        for line in (out / 'test.log').read_text().splitlines():
            if line.startswith('CPU_PORT_ONLY '):
                report['cpu_port_only'].append({k: float(v) if '.' in v else int(v) for k, v in
                                        (field.split('=', 1) for field in line.split()[1:])})
        for line in (out / 'test.log').read_text().splitlines():
            if line.startswith('DMA_CPU_COMBINED '):
                report['combined'].append({k: float(v) if '.' in v else int(v) for k, v in
                                        (field.split('=', 1) for field in line.split()[1:])})
        assert 'DMA_COHERENT_LINE_PASS' in (out / 'test.log').read_text()
        for mutation, anchor in [('drop-write', 'DMA independent destination byte oracle mismatch'),
                                 ('corrupt-write', 'DMA independent destination byte oracle mismatch'),
                                 ('early-ack', 'DMA completion before final AXI B')]:
            p = subprocess.run([out / 'run', '--mutate=' + mutation], capture_output=True, text=True, timeout=180,
                               env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
            (out / ('negative-' + mutation + '.log')).write_text(p.stdout + p.stderr)
            if p.returncode == 0 or anchor not in p.stdout + p.stderr: raise RuntimeError('Negative did not reject: ' + mutation)
            report['negative_controls'][mutation] = {'status': 'PASS', 'rejected': anchor}
        if hashes() != report['source_sha256']: raise RuntimeError('Source drift during run')
        report['status'] = 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        report['artifacts_sha256'] = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in out.rglob('*') if p.is_file() and p.name != 'receipt.json'}
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': main()
