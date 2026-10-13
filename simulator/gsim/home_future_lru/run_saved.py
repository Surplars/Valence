#!/usr/bin/env python3
"""Check retained evidence or explicitly rerun its saved strict host/model pair.

No model build, compiler, native export, network, or physical tool is invoked.
Restore the two private evidence archives together, then pass their directory.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
from source_bridge import sha, need


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def read(path):
    return json.loads(path.read_text())


def check_source():
    record = read(HERE / 'evidence.json')
    entry = module('future_lru_entry', ROOT / 'fpga/next/board_home_future_lru.py')
    final, base, profile = entry.load_profile()
    for row in record['host_sources'].values():
        need(sha(ROOT / row['source']) == row['sha256'], 'strict host source changed: ' + row['source'])
    need(sha(ROOT / record['result_contract']['path']) == record['result_contract']['sha256'],
         'original independent result contract changed')
    return record, profile


def check_evidence(directory, record, profile):
    for name, expected in record['evidence_files'].items():
        need(sha(directory / name) == expected, 'retained evidence changed: ' + name)
    first = read(directory / 'run-r1/receipt.json')
    bridge = read(directory / 'host-bridge-r1/receipt.json')
    need(first['status'] == 'FAILED_STOPPED_PRESERVE_EVIDENCE', 'first failure must remain recorded')
    need(first['options'] == profile['native_options'], 'actual emitted option vector changed')
    need(sha(directory / 'run-r1/on/profile.json') == profile['tested_profile_sha256'] and
         sha(directory / 'run-r1/on/actual-fabric.json') == profile['tested_actual_fabric_sha256'],
         'actual constructed profile changed')
    actual = read(directory / 'run-r1/on/actual-fabric.json')
    need(actual['futureHome']['futureHomeWayReservation'] is True and
         actual['cache']['storePrefetchLruVictim'] is True and
         actual['cache']['storePrefetchMruInsertion'] is True and
         actual['eagerPrefix']['eagerFetchPrefixSelect'] is False, 'host policy differs from actual DUT')
    for name, expected in first['built_model'].items():
        need(sha(directory / 'run-r1/on' / name) == expected, 'saved model artifact changed: ' + name)
    need(sha(directory / 'host-bridge-r1/run') == bridge['binary_sha256'], 'saved strict executable changed')
    for name, row in record['host_sources'].items():
        need(sha(directory / 'host-bridge-r1/host' / name) == row['sha256'], 'saved strict host differs: ' + name)
    for name, expected in first['contract']['guest'].items():
        need(sha(directory / 'run-r1/guest' / name) == expected, 'saved guest changed')
    contract = module('original_result_contract', ROOT / record['result_contract']['path'])
    for name, total in record['original_law_inclusive_cycles'].items():
        command = next(x for x in bridge['commands'] if x['label'] == name)
        log = directory / 'host-bridge-r1' / (name + '.log')
        need(sha(log) == command['log_sha256'] and command['exit'] == 0, 'saved positive log changed')
        old = bridge['cases'][name]
        row = contract.capture_result(log.read_text(), directory / 'host-bridge-r1' / name, old, actual)
        need(row['inclusive_cycles'] == total and row['functional_fields_captured'] == 105 and row['raw'] == old['raw'],
             'original independent capture changed')
        policy = read(directory / 'host-bridge-r1' / name / 'policy-audit.json')
        need(policy == old['policy_audit'] and policy['status'] == 'PASS_ACCEPTED_EVENT_POLICY_HISTORY' and
             policy['store_prefetch_lru'] == 1 and policy['history_checks'] == 256 * (policy['samples'] - 4),
             'accepted-event policy/history evidence changed')
    for label, anchor in record['negative_anchors'].items():
        command = next(x for x in bridge['commands'] if x['label'] == label)
        log = directory / 'host-bridge-r1' / (label + '.log')
        need(command['exit'] == command['expected'] == 1 and command['anchor'] == anchor and
             sha(log) == command['log_sha256'] and anchor in log.read_text(), 'original negative anchor changed: ' + label)
    return bridge, actual, contract


def rerun(directory, output, activation, record, bridge, actual, contract):
    first = read(directory / "run-r1/receipt.json")
    need(sha(activation) == first["tools"]["activate"]["sha256"], "qualified activation script changed")
    output.mkdir(parents=True, exist_ok=False)
    binary = (directory / 'host-bridge-r1/run').resolve()
    guest = (directory / 'run-r1/guest/guest.bin').resolve()
    cases = [('sv39', 1, 65536, 2, [], None), ('bare', 0, 65536, 2, [], None)]
    cases += [(name + '-negative', 1, 4096, 1, ['--inject-' + name], None) for name in ('read', 'memory', 'trap')]
    cases += [('mutation-' + name, 1, 4096, 1, [], name) for name in ('policy', 'history')]
    for label, mode, size, reps, extra, mutation in cases:
        work = output / label; work.mkdir()
        env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'PYTHONDONTWRITEBYTECODE': '1'}
        env.pop('CPU_LRU_ORACLE_MUTATION', None)
        if mutation:
            env['CPU_LRU_ORACLE_MUTATION'] = mutation
        command = ['/bin/bash', '--noprofile', '--norc', '-c', 'source "$1"; shift; exec "$@"',
                   'qualified-saved-replay', str(activation), str(binary), str(guest), str(mode), '2', str(size), str(reps), *extra]
        result = subprocess.run(command,
                                cwd=work, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (output / (label + '.log')).write_text(result.stdout)
        if label in record['original_law_inclusive_cycles']:
            need(result.returncode == 0, 'saved positive execution failed: ' + label)
            old = bridge['cases'][label]
            row = contract.capture_result(result.stdout, work, old, actual)
            need(row['inclusive_cycles'] == record['original_law_inclusive_cycles'][label] and row['raw'] == old['raw'],
                 'saved execution differs from retained result: ' + label)
            need(read(work / 'policy-audit.json') == old['policy_audit'], 'rerun policy history differs')
        else:
            need(result.returncode == 1 and record['negative_anchors'][label] in result.stdout,
                 'rerun missed original negative anchor: ' + label)
    return {'status': 'PASS_RERUN_SAVED_STRICT_HOST_MODEL', 'cases': 2, 'negative_controls': 5,
            'new_dut_models': 0, 'new_compiles': 0, 'physical_qualification': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    ap.add_argument('--evidence', type=Path)
    ap.add_argument('--rerun', action='store_true')
    ap.add_argument('--activation', type=Path, help='exact qualified toolchain activation script; required for replay')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    if args.rerun and (args.evidence is None or args.output is None or args.activation is None):
        ap.error('--rerun requires --evidence, --activation, and a new --output directory')
    if (args.output is not None or args.activation is not None) and not args.rerun:
        ap.error('--output and --activation require --rerun')
    record, profile = check_source()
    result = {'status': 'PASS_CURRENT_SOURCE_AND_EXPERIMENTAL54_CONFIG', 'hardware_executed': False}
    if args.evidence is not None:
        directory = args.evidence.resolve()
        bridge, actual, contract = check_evidence(directory, record, profile)
        result['status'] = 'PASS_RETAINED_EVIDENCE_RECAPTURE'
        if args.rerun:
            result = rerun(directory, args.output.resolve(), args.activation.resolve(), record, bridge, actual, contract)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
