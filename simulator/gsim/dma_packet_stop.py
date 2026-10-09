#!/usr/bin/env python3
"""Focused real packet STOP/restart while coherent copy lines share atomic/cache/home/AXI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import run as common


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--line-entries', type=int, choices=(1,2,4), default=1)
    parser.add_argument('--line-yield-cycles', type=int, choices=(0, 4, 16), default=0)
    parser.add_argument('--rebuild-driver', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.tag):
        parser.error('unsafe tag')
    name = 'dma-packet-stop-' + args.tag
    output = common.BUILD / name
    sources = sorted((common.ROOT / 'src/main/scala').rglob('*.scala')) + [
        common.ROOT / 'src/test/scala/ooo/DmaPacketStopGsim.scala',
        common.HERE / 'harness/dma_packet_stop.cpp', common.HERE / 'harness/dma_coherent_ddr.h',
        Path(__file__).resolve()]
    hashes = lambda: {str(p.relative_to(common.ROOT)): digest(p) for p in sources}
    report = {'status': 'RUNNING', 'line_yield_cycles': args.line_yield_cycles,'line_entries':args.line_entries,
              'source_sha256': hashes(), 'cases': [], 'negative_controls': {},
              'scope': 'Real EthernetPacketDma and MemoryCopyDma; production scalar arbiter/adapter, atomic boundary, coherent cache/mixed home, TileLink/AXI; independent host DDR and software-generation oracle. No MAC/CDC/PHY, CPU execution, physical DDR, routed timing, or explicit hardware generation tags.',
              'geometry': {'cache_lines': 512, 'cache_ways': 2, 'copy_bytes': 32768,
                           'packet_scalar_bytes': 8, 'copy_line_bytes': 64,
                           'posted_tx_slots': 4, 'posted_rx_slots': 4, 'memory_credits': 4}}
    if args.dry_run:
        print(json.dumps(report, indent=2)); return
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    try:
        if args.rebuild_driver:
            previous = json.loads((output / 'receipt.json').read_text())
            if previous['line_yield_cycles'] != args.line_yield_cycles or previous.get('line_entries',1)!=args.line_entries:
                raise RuntimeError('cannot change RTL parameters during driver rebuild')
            for path, value in previous['source_sha256'].items():
                if path.startswith('src/') and report['source_sha256'].get(path) != value:
                    raise RuntimeError('RTL or fixture changed: ' + path)
            for path, value in previous['artifacts_sha256'].items():
                if path.endswith(('.fir', '.h', '.cpp')) and digest(output / path) != value:
                    raise RuntimeError('generated model changed: ' + path)
            cxx, _ = common.compiler()
            common.run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-DDMA_LINE_ENTRIES='+str(args.line_entries), '-DDMA_LINE_YIELD_CYCLES=' + str(args.line_yield_cycles),
                        '-I' + str(output), *sorted(output.glob('DmaPacketStopGsim[0-9]*.cpp')),
                        common.HERE / 'harness/dma_packet_stop.cpp', '-ldl', '-o', output / 'run'],
                       log=output / 'compile.log')
            common.run([output / 'run'], log=output / 'test.log', timeout=180, env=env)
        else:
            if (output / 'run').exists():
                raise RuntimeError('choose a fresh tag or --rebuild-driver')
            gsim, cxx = common.setup(False)
            common.test(gsim, cxx, name, 'ooo.DmaPacketStopGsimMain', 'DmaPacketStopGsim',
                        'dma_packet_stop.cpp', parameters=(args.line_yield_cycles,args.line_entries),
                        defines={'DMA_LINE_YIELD_CYCLES': args.line_yield_cycles,'DMA_LINE_ENTRIES':args.line_entries}, timeout=180)
        log = (output / 'test.log').read_text()
        if 'DMA_PACKET_STOP_LINE_PASS' not in log:
            raise RuntimeError('PASS anchor absent')
        for line in log.splitlines():
            if line.startswith('PACKET_LINE_CASE '):
                report['cases'].append(dict(field.split('=', 1) for field in line.split()[1:]))
        for mutation, anchor in [('tx-byte', 'packet TX independent generation byte oracle mismatch'),
                                 ('rx-byte', 'CPU independent cache byte oracle mismatch'),
                                 ('stale-owner', 'packet completion generation/owner oracle mismatch')]:
            result = subprocess.run([str(output / 'run'), '--mutate=' + mutation], capture_output=True,
                                    text=True, timeout=180, env=env)
            message = result.stdout + result.stderr
            (output / ('negative-' + mutation + '.log')).write_text(message)
            if result.returncode != 1 or anchor not in message:
                raise RuntimeError('negative oracle did not reject as expected: ' + mutation + '\n' + message)
            report['negative_controls'][mutation] = {'status': 'EXPECTED_FAILURE', 'anchor': anchor}
        if hashes() != report['source_sha256']:
            raise RuntimeError('source drift during run')
        report['status'] = 'PASS'
    except BaseException as error:
        report.update(status='FAIL', error=str(error)); raise
    finally:
        report['artifacts_sha256'] = {str(p.relative_to(output)): digest(p) for p in output.rglob('*')
                                     if p.is_file() and p.name != 'receipt.json'}
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'receipt': str(output / 'receipt.json'),
                      'cases': report['cases'], 'negative_controls': report['negative_controls']}, indent=2))


if __name__ == '__main__':
    main()
