#!/usr/bin/env python3
"""Compare the source-identical accepted-store history off/on board experiment."""
import argparse
import json
from pathlib import Path
from compare_prefetch_retention import fields, parse, sha


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--off', type=Path, required=True)
    ap.add_argument('--on', type=Path, required=True)
    ap.add_argument('--prior-three', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    paths = {'off': args.off.resolve(), 'on': args.on.resolve()}
    receipts = {key: json.loads(path.read_text()) for key, path in paths.items()}
    if receipts['off']['inputs'] != receipts['on']['inputs']:
        raise RuntimeError('policy comparison source inventories differ')
    plans = {key: receipt['plan'] for key, receipt in receipts.items()}
    on_parameters = list(plans['on']['parameters'])
    if on_parameters.count('--prefetch-break-on-store') != 1:
        raise RuntimeError('enabled policy flag missing/ambiguous')
    on_parameters.remove('--prefetch-break-on-store')
    if on_parameters != plans['off']['parameters'] or '--prefetch-candidate-cycles=3' not in on_parameters:
        raise RuntimeError('profile difference exceeds the store-history policy')
    expected_suite = ['rv64gc', 'steady', 'independent-lines', 'virtual-context', 'mixed-store16', 'mixed-store64']
    if any(plan['guest_suite'] != expected_suite for plan in plans.values()):
        raise RuntimeError('missing six-workload suite')
    logs = {}
    for key, receipt in receipts.items():
        if receipt['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
            raise RuntimeError('incomplete full board suite')
        for name, digest in receipt['artifacts'].items():
            if sha(paths[key].parent / name) != digest:
                raise RuntimeError('artifact drift: ' + name)
        logs[key] = {}
        for name, row in receipt['tests'].items():
            path = paths[key].parent / row['log']
            if sha(path) != row['log_sha256']:
                raise RuntimeError('test log drift: ' + name)
            logs[key][name] = path.read_bytes()
    prior_path = args.prior_three.resolve()
    prior = json.loads(prior_path.read_text())
    if prior['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
        raise RuntimeError('unqualified prior three-attempt control')
    original = {}
    for name in ('gc', 'steady', 'independent', 'virtual'):
        path = prior_path.parent / prior['tests'][name]['log']
        if sha(path) != prior['tests'][name]['log_sha256'] or path.read_bytes() != logs['off'][name]:
            raise RuntimeError('default-off changed original workload: ' + name)
        original[name] = sha(path)
    for name in ('rv64gc', 'steady', 'independent', 'mixed16', 'mixed64'):
        key = 'firmware/' + name + '.bin'
        if receipts['off']['artifacts'][key] != receipts['on']['artifacts'][key]:
            raise RuntimeError('executed guest bytes differ: ' + name)
    if receipts['off']['artifacts']['firmware/virtual/guest.bin'] != receipts['on']['artifacts']['firmware/virtual/guest.bin']:
        raise RuntimeError('virtual guest bytes differ')
    result = {'schema': 'valence-fpga-next-store-history-comparison-v1',
        'status': 'PASS_MATCHED_STORE_HISTORY_ABLATION',
        'source_commit': receipts['on']['git_head'], 'source_inputs_identical': True,
        'receipts': {key: {'path': str(path), 'sha256': sha(path)} for key, path in paths.items()},
        'analysis_sources': {path.name: sha(path) for path in
            [Path(__file__), Path(__file__).with_name('compare_prefetch_retention.py')]},
        'prior_control': {'path': str(prior_path), 'sha256': sha(prior_path), 'raw_logs_preserved': original},
        'workloads': {}, 'mixed_execution_witnesses': {},
        'limits': ['Controlled host DDR model; no physical bandwidth or mapped PPA claim',
                   'One accepted-store history policy ablation; no owner, credit or permission expansion',
                   'Physical source accepts may include legal speculation; retired fixed-guest LDs and scratch store ordinals are independently checked',
                   'Historical useful-event telemetry is not independently a fully hidden miss count',
                   'Functional PASS does not automatically promote a workload-dependent policy']}
    for workload in ('steady', 'independent', 'mixed16', 'mixed64'):
        parsed = {key: parse(group[workload].decode()) for key, group in logs.items()}
        if list(parsed['off']['regions']) != list(parsed['on']['regions']):
            raise RuntimeError('region identity mismatch')
        cycles = {}
        for name, old in parsed['off']['regions'].items():
            new = parsed['on']['regions'][name]
            if old['cpu']['retired'] != new['cpu']['retired']:
                raise RuntimeError('architectural workload size differs')
            cycles[name] = {'off': old['cpu']['cycles'], 'on': new['cpu']['cycles'],
                'speedup': old['cpu']['cycles'] / new['cpu']['cycles'],
                'cycle_change_percent': 100 * (new['cpu']['cycles'] / old['cpu']['cycles'] - 1)}
        result['workloads'][workload] = {'profiles': parsed, 'cycle_comparison': cycles}
        if workload.startswith('mixed'):
            result['mixed_execution_witnesses'][workload] = {}
            expected_stores = 3072 // int(workload.removeprefix('mixed'))
            for key, group in logs.items():
                rows = [line for line in group[workload].decode().splitlines() if line.startswith('MIXED_ACCEPTED_REQUESTS ')]
                if len(rows) != 1:
                    raise RuntimeError('missing/ambiguous live mixed request witness')
                counts = fields(rows[0])
                if counts['architectural_source_loads'] != 24576 or counts['scratch_stores'] != expected_stores:
                    raise RuntimeError('mixed architectural workload contract differs')
                if 'overwritten_store_value_address_omission_negatives=3' not in group[workload].decode():
                    raise RuntimeError('missing intermediate-store negative controls')
                result['mixed_execution_witnesses'][workload][key] = counts
    for name in ('signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause', 'trap_tval', 'lsr_reads'):
        if receipts['off']['virtual_metrics']['architecture'][name] != receipts['on']['virtual_metrics']['architecture'][name]:
            raise RuntimeError('virtual architectural outcome differs: ' + name)
    result['virtual'] = {key: receipt['virtual_metrics'] for key, receipt in receipts.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'])


if __name__ == '__main__':
    main()
