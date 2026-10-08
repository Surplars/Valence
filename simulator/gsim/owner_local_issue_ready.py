#!/usr/bin/env python3
"""Explicit local-ready ablation: independent event oracle and matched short NEMU matrix."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re

import run as common
from control_stage import core_payloads
from issue_frontend_storage import sha, negative, verify_reference
from throughput_perf import DEFINES, EXPECTED_KEYS, parse_measurements, compare_measurements


def sources():
    paths = sorted((common.ROOT / 'src').rglob('*.scala')) + [Path(__file__),
        common.HERE / 'harness/owner_local_issue_ready.cpp', common.HERE / 'harness/rename_fault_candidates.cpp',
        common.HERE / 'harness/core.cpp', common.HERE / 'harness/load_timing.h',
        common.HERE / 'issue_frontend_storage.py']
    return {str(p.relative_to(common.ROOT)): sha(p) for p in paths}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--phase', choices=['unit', 'core'], default='unit')
    ap.add_argument('--build-run', action='store_true')
    ap.add_argument('--reference-root', type=Path)
    a = ap.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.tag):
        ap.error('invalid tag')
    before = sources()
    if not a.build_run:
        print(json.dumps({'status': 'PREFLIGHT_ONLY', 'phase': a.phase, 'inputs': len(before),
            'physical_area_timing': 'unverified', 'scheduling_restriction': False}))
        return
    if a.phase == 'core' and not a.reference_root:
        ap.error('--reference-root required; no automatic reference build/download')
    out = common.BUILD / a.tag
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'RUNNING', 'phase': a.phase, 'inputs': before, 'cases': {}, 'negative': {},
        'physical_area_timing': 'unverified', 'scheduling_restriction': False}
    try:
        common.run(['mill', '-i', 'IonSoC.test.testOnly', 'ooo.OwnerLocalIssueReadySpec',
            'ooo.FpgaIssueStorageSpec'], log=out / 'contracts.log')
        gsim, cxx = common.setup(False)
        if a.phase == 'unit':
            model = common.test(gsim, cxx, a.tag + '/ready', 'ooo.OwnerLocalIssueReadyGsimMain',
                'OwnerLocalIssueReadyGsim', 'owner_local_issue_ready.cpp', defines={})
            report['cases']['ready'] = (model / 'test.log').read_text()
            report['negative']['ready'] = negative(model / 'run', (), '--inject-mismatch',
                'owner-local issue readiness differs from independent scoreboard and promises', model / 'negative.log')
            rename = common.test(gsim, cxx, a.tag + '/allocation', 'ooo.RenameFaultCandidatesGsimMain',
                'RenameFaultCandidatesGsim', 'rename_fault_candidates.cpp', parameters=('48',),
                defines={'PHYSICAL_REGS': 48})
            report['cases']['allocation'] = (rename / 'test.log').read_text()
            report['negative']['allocation'] = negative(rename / 'run', (), '--inject-mismatch',
                'fault-aware RAW source mapping', rename / 'negative.log')
            report['cones'] = {}
            for local in (False, True):
                path = out / ('local-cone' if local else 'global-cone'); path.mkdir()
                common.run(['mill', '-i', 'IonSoC.test.runMain', 'ooo.IssueReadyConeMain', path,
                    *(['local'] if local else [])], log=path / 'emit.log')
                fir = path / 'IssueReadyCone.fir'
                hw = path / 'IssueReadyCone.hw.mlir'
                common.run(['firtool', fir, '--ir-hw', '--disable-all-randomization', '-o', hw], log=path / 'lower.log')
                text = hw.read_text()
                counts = Counter(re.findall(r'\b((?:comb|seq|hw)\.[A-Za-z0-9_]+)\b', text))
                report['cones'][str(local)] = {'operations': dict(counts),
                    'input_physical_mentions': len(re.findall(r'%io_physical\b', text)),
                    'dynamic_ready_reads_chirrtl': fir.read_text().count('dshr(io.physical,'),
                    'new_state': counts.get('seq.compreg', 0), 'physical_mapping': 'unverified'}
            if report['cones']['False']['dynamic_ready_reads_chirrtl'] != 32 or \
                    report['cones']['True']['dynamic_ready_reads_chirrtl'] != 0:
                raise RuntimeError('expected ready-read structural ablation missing')
        else:
            ref, used = verify_reference(a.reference_root.resolve()); report['reference'] = used
            payloads = core_payloads(out)
            report['payloads'] = {str(p): sha(p) for p in payloads}
            keys = EXPECTED_KEYS | {('throughput_hint_alias_loop', 1)} | {
                ('throughput_serial_load_alu_address', latency) for latency in (1, 12)}
            baseline = baseline_timing = None
            for local in (False, True):
                name = 'local' if local else 'global'
                model = common.test(gsim, cxx, a.tag + '/' + name, 'ooo.ThroughputPerfGsimMain',
                    'IntegerCoreGsim', 'core.cpp', parameters=('staged-fetch-turnover', 'banked-rob',
                        'shared-store-reads', 'lvt-prf', 'load-issue-forwarding', 'banked-issue-payload',
                        'banked-fetch-hints', *(('owner-local-issue-ready',) if local else ())),
                    runtime_args=(ref, *payloads, '--throughput-short'), defines={**DEFINES,
                        'REGISTERED_FETCH_PACKET': 1, 'FPGA_STORAGE_OBSERVE': 1, 'FETCH_HINT_ALIAS_BENCH': 1,
                        'SERIAL_LOAD_ALU_BENCH': 1, 'LOAD_TIMING_OBSERVE': 1}, timeout=180)
                log = (model / 'test.log').read_text()
                rows = parse_measurements(log, expected_programs=15, expected_keys=keys)
                timing = [json.loads(line[len('LOAD_TIMING '):]) for line in log.splitlines() if line.startswith('LOAD_TIMING ')]
                report['cases'][name] = rows
                report.setdefault('load_timing', {})[name] = timing
                if not local:
                    baseline, baseline_timing = rows, timing
                else:
                    report['comparison'] = compare_measurements(baseline, rows)
                    if rows != baseline or timing != baseline_timing:
                        raise RuntimeError('owner-local issue readiness changed timing/events')
                for mode in ('pipeline-recovery', 'timing-smoke'):
                    common.run([model / 'run', ref, *payloads, '--' + mode], log=model / (mode + '.log'),
                        env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'}, timeout=180)
                report['negative'][name] = negative(model / 'run', (ref, *payloads), '--inject-mismatch',
                    'NEMU register mismatch', model / 'negative.log')
        report['status'] = 'PASS_' + a.phase.upper()
    except Exception as error:
        report['status'] = 'FAIL'; report['error'] = str(error); raise
    finally:
        report['artifacts'] = {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name != 'receipt.json'}
        if sources() != before:
            report['status'] = 'FAIL_SOURCE_CHANGED'
        (out / 'receipt.json').write_text(json.dumps(report, indent=2) + '\n')
        if sources() != before:
            raise RuntimeError('source changed during proof')
    print(json.dumps({'status': report['status'], 'receipt': str(out / 'receipt.json')}))


if __name__ == '__main__':
    main()
