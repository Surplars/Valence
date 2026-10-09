#!/usr/bin/env python3
"""Revalidate both one-flag pairs and join their byte-identical middle execution.

Reports the same-source both-OFF to both-ON total effect. No model or guest is
built, and no missing fourth factorial cell is inferred.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
POSITIVE_FILES = ('positive.log', 'positive-traffic.tsv', 'positive-hot-stage.tsv', 'positive-frontend.tsv')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('history_off', 'history_on', 'prefix_off', 'prefix_on'):
        parser.add_argument('--' + name.replace('_', '-'), required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    require(not args.out.exists(), 'output must be fresh')
    args.out.mkdir(parents=True)
    paths = {name: getattr(args, name).resolve() for name in ('history_off', 'history_on', 'prefix_off', 'prefix_on')}
    state = {name: json.loads(path.read_text()) for name, path in paths.items()}
    commands = []
    for fixture, left, right, filename in (
        ('monitor_bandwidth_fetch_history_v1', 'history_off', 'history_on', 'history-comparison.json'),
        ('monitor_bandwidth_fetch_prefix_v2', 'prefix_off', 'prefix_on', 'prefix-comparison.json'),
    ):
        command = [sys.executable, '-B', str(HERE / 'fixtures' / fixture / 'compare.py'),
                   str(paths[left]), str(paths[right]), '--out', str(args.out.resolve() / filename)]
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (args.out / (filename + '.log')).write_text(completed.stdout)
        require(completed.returncode == 0, 'strict original comparator rejected: ' + fixture)
        commands.append(command)
    middle = {}
    for name in POSITIVE_FILES:
        a, b = paths['history_on'].parent / name, paths['prefix_off'].parent / name
        require(a.stat().st_size == b.stat().st_size and sha(a) == sha(b), 'middle execution is not byte-identical: ' + name)
        middle[name] = {'bytes': a.stat().st_size, 'sha256': sha(a)}
    require(state['history_on']['result'] == state['prefix_off']['result'], 'middle parsed observation differs')
    for key in ('model_receipt_sha256', 'model_plan', 'model_artifacts', 'model_register_schema'):
        require(state['history_on'][key] == state['prefix_off'][key], 'middle model differs: ' + key)
    for key in ('model_source_inputs', 'host_compiler', 'guest_manifest_sha256', 'guest',
                'shared_dma_profile', 'source_freeze', 'production_source_tree',
                'compress_debug', 'external_fixture_inputs', 'debug_compression_tools'):
        require(all(x[key] == state['history_off'][key] for x in state.values()), 'shared input differs: ' + key)
    observers = {}
    for x in state.values():
        relevant = {name: digest for name, digest in x['fixture_inputs'].items()
                    if Path(name).suffix in ('.cpp', '.h', '.S', '.ld') or name in ('stage_schema.json', 'history_schema.json')}
        if observers:
            require(observers == relevant, 'observer/guest/schema source differs')
        observers = relevant
    first, last = state['history_off']['result'], state['prefix_on']['result']
    require(set(first['intervals']) == set(last['intervals']), 'interval set differs')
    rows = [{'name': name, 'both_off_ticks': value['actual_ticks'], 'both_on_ticks': last['intervals'][name]['actual_ticks'],
             'rate_change_percent': 100 * (value['actual_ticks'] / last['intervals'][name]['actual_ticks'] - 1)}
            for name, value in first['intervals'].items()]
    output = {'status': 'PASS_STRICT_SAME_SOURCE_FETCH_PREFIX_TRIAD',
              'production_commit': state['history_off']['source_freeze'],
              'input_receipts': {k: {'path': str(v), 'sha256': sha(v)} for k, v in paths.items()},
              'strict_revalidation_commands': commands,
              'strict_revalidation_outputs': {p.name: sha(p) for p in args.out.iterdir() if p.is_file()},
              'byte_identical_middle_execution': middle, 'identical_observer_guest_schema_inputs': observers,
              'intervals': rows, 'script_sha256': sha(__file__),
              'limits': ['Unchanged archived GCC14.2 ELF, not the unavailable board GCC13.2 binary.',
                         'Three same-source configurations; no fresh history-OFF/prefix-ON fourth cell is inferred.',
                         'rdtime kernel and separately recorded flush intervals retain all original work and overhead.',
                         'No model/guest rebuild, synthesis, FPGA timing or board performance claim.']}
    (args.out / 'receipt.json').write_text(json.dumps(output, indent=2) + '\n')
    for row in rows:
        print(row)
    print(output['status'], args.out / 'receipt.json')


if __name__ == '__main__':
    main()
