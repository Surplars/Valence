#!/usr/bin/env python3
"""Short packet/cache/home checks; no CPU/Linux simulation or FPGA timing claim."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from run import ROOT, BUILD, HERE, run, setup, test


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compile_driver(cxx, model, harness, binary, log):
    run([cxx, '-std=c++20', '-O1', '-g', '-fsanitize=address,undefined',
         '-fno-sanitize-recover=all', '-I' + str(model),
         *sorted(model.glob('NetworkProbeGsim[0-9]*.cpp')), HERE / 'harness' / harness,
         '-ldl', '-o', binary], log=log, timeout=180)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--control-receipt', type=Path,
                        help='sealed pre-fix network_boot_checks receipt for expected-deadlock controls')
    parser.add_argument('--controls-only', action='store_true',
                        help='run only the historical FIR controls; never report current RTL passed')
    args = parser.parse_args()
    if not args.tag.replace('-', '').isalnum():
        parser.error('unsafe tag')
    if args.controls_only and not args.control_receipt:
        parser.error('--controls-only requires --control-receipt')
    output = BUILD / ('network-packet-pressure-' + args.tag)
    output.mkdir(parents=True, exist_ok=False)
    sources = sorted((ROOT / 'src/main/scala').rglob('*.scala'))
    sources += [ROOT / 'src/test/scala/ooo/NetworkProbeGsim.scala',
                HERE / 'harness/network_packet_pressure.cpp', HERE / 'harness/network_probe.cpp',
                Path(__file__).resolve()]
    before = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    report = {'status': 'running', 'source_sha256': before, 'checks': {}, 'controls': {},
              'scope': 'cache/atomic/FIFO/home modules only; no executing CPU/Linux/PHY/MIG or timing claim',
              'on_board_verified': False, 'routed_timing_verified': False,
              'controls_only': args.controls_only}
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}
    try:
        gsim, cxx = setup(False)
        if not args.controls_only:
            for ways, lines, mode in ((1, 4, 'default'), (2, 4, 'default'), (2, 32, 'production')):
                stem = f'cache{ways}-lines{lines}'
                model = test(gsim, cxx, output.name + '/' + stem, 'ooo.NetworkProbeGsimMain',
                             'NetworkProbeGsim', 'network_packet_pressure.cpp',
                             parameters=(str(ways), str(lines), mode), defines={},
                             sanitizer=True, timeout=30)
                negative = subprocess.run([str(model / 'run'), '--inject-mismatch'],
                                          capture_output=True, text=True, timeout=30, env=env)
                (model / 'negative.log').write_text(negative.stdout + negative.stderr)
                if negative.returncode != 1 or 'DMA pressure dirty byte oracle mismatch' not in negative.stdout + negative.stderr:
                    raise RuntimeError('negative data oracle failed: ' + stem)
                compile_driver(cxx, model, 'network_probe.cpp', model / 'probe-regression',
                               model / 'probe-build.log')
                run([model / 'probe-regression'], log=model / 'probe-regression.log', env=env, timeout=30)
                print((model / 'probe-regression.log').read_text(), end='', flush=True)
                report['checks'][stem] = {'status': 'passed', 'pressure_cases': 48, 'probe_cases': 8,
                                         'negative_oracle': 'expected_failure',
                                         'fir_sha256': digest(model / 'NetworkProbeGsim.fir'),
                                         'executable_sha256': digest(model / 'run')}
        if args.control_receipt:
            receipt_path = args.control_receipt.resolve()
            old = json.loads(receipt_path.read_text())
            if old.get('status') != 'passed':
                raise RuntimeError('control receipt must be fully passed')
            report['control_receipt'] = {'path': str(receipt_path), 'sha256': digest(receipt_path)}
            for ways in (1, 2):
                stem = f'fifo-home{ways}'
                old_fir = receipt_path.parent / stem / 'NetworkProbeGsim.fir'
                if digest(old_fir) != old['checks'][stem]['fir_sha256']:
                    raise RuntimeError('sealed control FIR drift: ' + stem)
                model = output / ('old-control' + str(ways))
                model.mkdir()
                shutil.copyfile(old_fir, model / 'NetworkProbeGsim.fir')
                run([gsim, '--threads=1', '--dir=' + str(model), model / 'NetworkProbeGsim.fir'],
                    log=model / 'generate.log')
                compile_driver(cxx, model, 'network_packet_pressure.cpp', model / 'run', model / 'compile.log')
                result = subprocess.run([str(model / 'run')], capture_output=True, text=True, timeout=30, env=env)
                message = result.stdout + result.stderr
                (model / 'test.log').write_text(message)
                if result.returncode != 1 or 'packet/cache/atomic/home pressure bounded liveness failure' not in message:
                    raise RuntimeError('historical control did not reproduce bounded deadlock: ' + stem)
                print(f'EXPECTED_OLD_HOME_DEADLOCK ways={ways}\n' + message, flush=True)
                report['controls'][stem] = {'status': 'expected_deadlock_detected',
                                           'fir_sha256': digest(old_fir),
                                           'executable_sha256': digest(model / 'run'),
                                           'scope': 'exact sealed module FIR, not a recorded physical-board trace'}
        if before != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
            raise RuntimeError('source drift during checks')
        report['status'] = 'expected_controls_confirmed' if args.controls_only else 'passed'
    except BaseException as error:
        report.update(status='failed', failure=str(error))
        raise
    finally:
        (output / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
