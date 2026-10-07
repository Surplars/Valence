#!/usr/bin/env python3
"""Affected short checks only; no CPU/Linux execution or Vivado timing claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from run import ROOT, BUILD, HERE, setup, test, run

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', default='20261006-r1')
    parser.add_argument('--reuse', type=Path, help='reuse byte-identical successful affected checks')
    args = parser.parse_args()
    if not args.tag.replace('-', '').isalnum(): parser.error('unsafe tag')
    name = 'network-boot-checks-' + args.tag
    output = BUILD / name
    output.mkdir(parents=True, exist_ok=False)
    sources = list((ROOT / 'src/main/scala').rglob('*.scala'))
    sources += [ROOT / 'src/test/scala/ooo/NetworkProbeGsim.scala',
                ROOT / 'src/test/scala/ooo/CoherentCacheWaysGsim.scala',
                ROOT / 'src/test/scala/ip/EthernetPacketDmaGsim.scala']
    sources += [HERE / 'harness' / n for n in
                ('coherent_cache_ways.cpp', 'network_probe.cpp', 'network_refill_probe.cpp', 'ethernet_packet_dma.cpp')]
    before = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    report = {'status': 'running', 'source_sha256': before,
              'scope': 'cache/probe/FIFO/home and packet DMA only; NOT CPU/Linux/board/timing',
              'on_board_verified': False, 'routed_timing_verified': False, 'checks': {}}
    try:
        gsim, cxx = setup(False)
        old = {}
        if args.reuse:
            old = json.loads(args.reuse.read_text())
            if old.get('status') != 'passed':
                raise RuntimeError('can only reuse a fully passed receipt')
            for path, value in old['source_sha256'].items():
                if before.get(path) != value:
                    raise RuntimeError('cannot reuse changed source: ' + path)
        rows = []
        for ways in (1, 2):
            rows += [(f'cache{ways}', 'ooo.CoherentCacheWaysGsimMain', 'CoherentCacheWaysGsim',
                      'coherent_cache_ways.cpp', (str(ways),), {'CACHE_WAYS': ways}, None),
                     (f'fifo-home{ways}', 'ooo.NetworkProbeGsimMain', 'NetworkProbeGsim',
                      'network_probe.cpp', (str(ways),), {}, 'DMA independent dirty/clean byte oracle mismatch')]
        rows += [('packet-dma', 'ip.EthernetPacketDmaGsimMain', 'EthernetPacketDma',
                  'ethernet_packet_dma.cpp', (), {}, 'TX independent byte oracle mismatch')]
        for stem, main_name, top, harness, params, defines, anchor in rows:
            if stem in old.get('checks', {}):
                model = args.reuse.resolve().parent / stem
                row = old['checks'][stem]
                if digest(model / (top + '.fir')) != row['fir_sha256'] or digest(model / 'run') != row['executable_sha256']:
                    raise RuntimeError('saved model drift: ' + stem)
                report['checks'][stem] = {**row, 'reused_from': str(model)}
                continue
            model = test(gsim, cxx, name + '/' + stem, main_name, top, harness,
                         parameters=params, defines=defines, sanitizer=True, timeout=120)
            if anchor:
                bad = subprocess.run([str(model / 'run'), '--inject-mismatch'],
                                     capture_output=True, text=True, timeout=120,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
                (model / 'negative.log').write_text(bad.stdout + bad.stderr)
                if bad.returncode != 1 or anchor not in bad.stdout + bad.stderr:
                    raise RuntimeError('negative oracle failed: ' + stem)
            report['checks'][stem] = {'status': 'passed', 'fir_sha256': digest(model / (top + '.fir')),
                                     'executable_sha256': digest(model / 'run')}
        for ways in (1, 2):
            stem = 'cache' + str(ways)
            model = Path(report['checks'][stem].get('reused_from', output / stem))
            binary = output / ('refill-probe' + str(ways))
            run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
                 '-fno-sanitize-recover=all', '-DCACHE_WAYS=' + str(ways), '-I' + str(model),
                 *sorted(model.glob('CoherentCacheWaysGsim[0-9]*.cpp')),
                 HERE / 'harness/network_refill_probe.cpp', '-ldl', '-o', binary],
                log=output / ('refill-build' + str(ways) + '.log'))
            run([binary], log=output / ('refill-test' + str(ways) + '.log'),
                env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, timeout=120)
            report['checks']['refill' + str(ways)] = {'status': 'passed', 'executable_sha256': digest(binary)}
        # Fault injection recreates ONLY the old inability to accept a probe
        # during bypassResponse; it is not an exact old whole-SoC checkpoint.
        model = Path(report['checks']['fifo-home2'].get('reused_from', output / 'fifo-home2'))
        fir = (model / 'NetworkProbeGsim.fir').read_text()
        needle = 'node _io_tl_b_ready_T_11 = eq(state, UInt<4>(0h8))'
        if fir.count(needle) != 1:
            raise RuntimeError('fault-injection point drift')
        control = output / 'probe-disabled-control'
        control.mkdir()
        (control / 'NetworkProbeGsim.fir').write_text(fir.replace(needle,
                    'node _io_tl_b_ready_T_11 = UInt<1>(0h0)'))
        run([gsim, '--threads=1', '--dir=' + str(control), control / 'NetworkProbeGsim.fir'],
            log=control / 'generate.log')
        run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
             '-fno-sanitize-recover=all', '-I' + str(control),
             *sorted(control.glob('NetworkProbeGsim[0-9]*.cpp')), HERE / 'harness/network_probe.cpp',
             '-ldl', '-o', control / 'run'], log=control / 'compile.log')
        bad = subprocess.run([str(control / 'run')], capture_output=True, text=True, timeout=120,
                             env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        (control / 'test.log').write_text(bad.stdout + bad.stderr)
        if bad.returncode != 1 or 'DMA/CPU/home circular wait' not in bad.stdout + bad.stderr:
            raise RuntimeError('probe-disabled control did not reproduce the bounded deadlock')
        report['checks']['probe-disabled-control'] = {
            'status': 'expected_deadlock_detected', 'fir_sha256': digest(control / 'NetworkProbeGsim.fir'),
            'scope': 'single ready-capability mutation; not exact old RTL and not a board trace'}
        if before != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
            raise RuntimeError('RTL/test source drift')
        report['status'] = 'passed'
    except BaseException as error:
        report.update(status='failed', failure=str(error))
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')

if __name__ == '__main__':
    main()
