#!/usr/bin/env python3
"""Opt-in immutable issue/fetch RAM proof; short GSIM only, no CAD or downloads."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

import run as common
from control_stage import core_payloads
from throughput_perf import DEFINES, EXPECTED_KEYS, parse_measurements, compare_measurements


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    paths = sorted((common.ROOT / 'src').rglob('*.scala')) + [Path(__file__),
        common.HERE / 'harness/banked_issue_payload.cpp', common.HERE / 'harness/registered_fetch_packet.cpp',
        common.HERE / 'harness/integer.cpp', common.HERE / 'harness/core.cpp',
        common.HERE / 'issue_storage_census.py', common.HERE / 'harness/load_timing.h']
    return {str(p.relative_to(common.ROOT)): sha(p) for p in paths}


def negative(binary, args, flag, message, output):
    result = subprocess.run([str(binary), *map(str, args), flag], capture_output=True, text=True,
        timeout=180, env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
    output.write_text(result.stdout + result.stderr)
    if result.returncode == 0 or message not in result.stdout + result.stderr:
        raise RuntimeError('negative oracle did not reject ' + flag)
    return {'returncode': result.returncode, 'required_message': message, 'log_sha256': sha(output)}


def verify_reference(root):
    library = root / 'nemu-src/build/riscv64-nemu-interpreter-so'
    used = json.loads((root / 'reference-used.json').read_text())
    lock = json.loads((common.HERE / 'config/reference-lock.json').read_text())
    if any(used.get(k) != v for k, v in lock.items()) or used.get('config_sha256') != \
            sha(common.HERE / 'config/rv64-integer-ref_defconfig') or used.get('library_sha256') != sha(library):
        raise RuntimeError('pinned NEMU provenance does not match')
    return library, used


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--phase', choices=['unit', 'core'], default='unit')
    ap.add_argument('--build-run', action='store_true')
    ap.add_argument('--unit-subset', choices=['payload', 'fetch', 'backend'], nargs='+',
                    default=['payload', 'fetch', 'backend'])
    ap.add_argument('--reference-root', type=Path)
    a = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        ap.error('invalid tag')
    before = sources()
    if not a.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'phase': a.phase, 'source_files': len(before),
                          'synthesis': False, 'latency_delta_target': 0, 'issue_width': 2}))
        return
    if a.phase == 'core' and not a.reference_root:
        ap.error('--reference-root is required; no automatic reference build/download')
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'phase': a.phase, 'inputs': before, 'cases': {}, 'negative': {},
        'synthesis': False, 'routed_timing': 'unverified', 'board': 'unverified',
        'unit_checks_requested': a.unit_subset if a.phase == 'unit' else []}
    try:
        common.run(['mill', '-i', 'IonSoC.test.testOnly', 'ooo.FpgaIssueStorageSpec', 'ooo.FpgaStorageSpec'],
            log=out / 'contracts.log')
        gsim, cxx = common.setup(False)
        if a.phase == 'unit':
            if 'payload' in a.unit_subset:
                payload = common.test(gsim, cxx, a.tag + '/issue-payload', 'ooo.BankedIssuePayloadGsimMain',
                    'BankedIssuePayloadGsim', 'banked_issue_payload.cpp', defines={})
                report['cases']['issue-payload'] = (payload / 'test.log').read_text()
                for flag, message in [('--inject-payload-mismatch', 'immutable issue payload oracle mismatch'),
                                      ('--inject-bank-collision', 'issue allocation writes must occupy distinct parity banks')]:
                    report['negative'][flag] = negative(payload / 'run', (), flag, message,
                        payload / (flag.removeprefix('--') + '.log'))
            if 'fetch' in a.unit_subset:
                for width, compressed, hints in [(2, True, 32), (2, False, 32), (4, True, 8)]:
                    pair = []
                    for enabled in (False, True):
                        name = f'fetch-w{width}-c{int(compressed)}-h{hints}-' + ('ram' if enabled else 'registers')
                        flags = (('plain',) if not compressed else ()) + (('hints32',) if hints == 32 else ()) + \
                            (('banked-hints',) if enabled else ())
                        model = common.test(gsim, cxx, a.tag + '/' + name, 'ooo.RegisteredFetchPacketGsimMain',
                            'RegisteredFetchPacketGsim', 'registered_fetch_packet.cpp',
                            parameters=(str(width), 'parallel-validation', 'split-cursor', *flags),
                            defines={'FETCH_WIDTH': width, 'COMPRESSED': int(compressed), 'HINT_ENTRIES': hints})
                        pair.append((model / 'test.log').read_text())
                        report['cases'][name] = pair[-1]
                        for flag, message in [('--inject-mismatch', 'fetch packet oracle mismatch'),
                                              ('--inject-hint-mismatch', 'hint successor/prediction/path validation mismatch')]:
                            report['negative'][name + flag] = negative(model / 'run', (), flag, message,
                                model / (flag.removeprefix('--') + '.log'))
                    if pair[0] != pair[1]:
                        raise RuntimeError('fetch event/cycle/coverage pair differs')
            if 'backend' in a.unit_subset:
                pair = []
                for enabled in (False, True):
                    name = 'backend-' + ('ram' if enabled else 'registers')
                    flags = ('banked-issue-payload',) if enabled else ()
                    model = common.test(gsim, cxx, a.tag + '/' + name, 'ooo.IntegerBackendGsimMain',
                        'IntegerBackendGsim', 'integer.cpp', parameters=('16', '48', '64', *flags),
                        defines={'ROB_ENTRIES': 16, 'PHYSICAL_REGS': 48, 'TAG_BITS': 64})
                    pair.append((model / 'test.log').read_text())
                    report['cases'][name] = pair[-1]
                    report['negative'][name] = negative(model / 'run', (), '--inject-fault-mismatch',
                        'precise head exception payload', model / 'negative-tval.log')
                if pair[0] != pair[1]:
                    raise RuntimeError('backend event/cycle/coverage pair differs')
        else:
            ref, used = verify_reference(a.reference_root.resolve())
            report['reference'] = used
            payloads = core_payloads(out)
            report['payload_sha256'] = {str(p): sha(p) for p in payloads}
            baseline = None
            for name, flags in [('registers', ()), ('issue-ram', ('banked-issue-payload',)),
                                ('hints-ram', ('banked-fetch-hints',)),
                                ('both-ram', ('banked-issue-payload', 'banked-fetch-hints'))]:
                model = common.test(gsim, cxx, a.tag + '/' + name, 'ooo.ThroughputPerfGsimMain',
                    'IntegerCoreGsim', 'core.cpp', parameters=('staged-fetch-turnover',
                        'banked-rob', 'shared-store-reads', 'lvt-prf', 'load-issue-forwarding', *flags),
                    runtime_args=(ref, *payloads, '--throughput-short'),
                    defines={**DEFINES, 'REGISTERED_FETCH_PACKET': 1, 'FPGA_STORAGE_OBSERVE': 1,
                        'FETCH_HINT_ALIAS_BENCH': 1, 'SERIAL_LOAD_ALU_BENCH': 1, 'LOAD_TIMING_OBSERVE': 1}, timeout=180)
                keys = EXPECTED_KEYS | {('throughput_hint_alias_loop', 1)} | {
                    ('throughput_serial_load_alu_address', latency) for latency in (1, 12)}
                rows = parse_measurements((model / 'test.log').read_text(), expected_programs=15, expected_keys=keys)
                report['cases'][name] = rows
                timing = [json.loads(line[len('LOAD_TIMING '):]) for line in (model / 'test.log').read_text().splitlines()
                          if line.startswith('LOAD_TIMING ')]
                if len(timing) != 15:
                    raise RuntimeError('missing passive load timing rows')
                report.setdefault('load_timing', {})[name] = timing
                if name != 'registers' and timing != report['load_timing']['registers']:
                    raise RuntimeError('zero-latency storage changed load timing events')
                if baseline is None:
                    baseline = rows
                else:
                    report.setdefault('comparisons', {})[name] = compare_measurements(baseline, rows)
                    if baseline != rows:
                        raise RuntimeError(name + ' changed the zero-latency cycle/counter contract')
                common.run([model / 'run', ref, *payloads, '--pipeline-recovery'],
                    env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, log=model / 'pipeline-recovery.log', timeout=180)
                report['negative'][name] = negative(model / 'run', (ref, *payloads), '--inject-mismatch',
                    'NEMU register mismatch', model / 'negative-register.log')
        from issue_storage_census import census
        report['storage_census'] = {}
        for fir in sorted(out.rglob('*.fir')):
            lowered = fir.with_suffix('.lowered.mlir')
            common.run(['firtool', fir, '--ir-fir', '--disable-all-randomization', '-o', lowered],
                log=fir.parent / 'lower.log')
            data = census(lowered.read_text())
            lowered.with_suffix('.census.json').write_text(json.dumps(data, indent=2) + '\n')
            report['storage_census'][str(fir.parent.relative_to(out))] = data
        report['status'] = 'PASS_' + a.phase.upper() + ('_PARTIAL' if a.phase == 'unit' and
            set(a.unit_subset) != {'payload', 'fetch', 'backend'} else '')
    except Exception as error:
        report['status'] = 'FAIL'
        report['error'] = str(error)
        raise
    finally:
        report['artifacts_sha256'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*'))
            if p.is_file() and p.name != 'receipt.json'}
        if before != sources():
            report['status'] = 'FAIL_SOURCE_CHANGED'
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
        if before != sources():
            raise RuntimeError('sources changed during proof')
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json')}))


if __name__ == '__main__':
    main()
