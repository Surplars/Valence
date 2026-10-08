#!/usr/bin/env python3
"""Reduce three qualified prefetch-policy profiles to exact workload/traffic rows."""
import argparse
import json
from pathlib import Path
from compare_prefetch_retention import parse, sha


def load_board(path):
    data = json.loads(path.read_text())
    if data['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
        raise RuntimeError('incomplete board suite: ' + str(path))
    for name, digest in data['artifacts'].items():
        if sha(path.parent / name) != digest:
            raise RuntimeError('changed artifact: ' + name)
    for row in data['tests'].values():
        if sha(path.parent / row['log']) != row['log_sha256']:
            raise RuntimeError('changed log: ' + row['log'])
    return data


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('default', 'read', 'copy'):
        ap.add_argument('--' + name, type=Path, required=True)
    ap.add_argument('--default-mixed', type=Path,
        help='optional sealed mixed replay when the historical default model predates those guests')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    paths = {name: getattr(args, name).resolve() for name in ('default', 'read', 'copy')}
    receipts = {name: load_board(path) for name, path in paths.items()}
    if receipts['read']['inputs'] != receipts['copy']['inputs']:
        raise RuntimeError('store-history off/on sources differ')
    expected = receipts['read']['plan']['parameters']
    enabled = list(receipts['copy']['plan']['parameters'])
    if '--prefetch-candidate-cycles=3' not in expected or enabled.count('--prefetch-break-on-store') != 1:
        raise RuntimeError('unexpected policy parameters')
    enabled.remove('--prefetch-break-on-store')
    if expected != enabled:
        raise RuntimeError('policy comparison changes additional parameters')
    default_parameters = [p for p in receipts['default']['plan']['parameters'] if p != '--prefetch-candidate-cycles=1']
    read_controls = [p for p in expected if p != '--prefetch-candidate-cycles=3']
    if default_parameters != read_controls:
        raise RuntimeError('default control changes settings beyond the one-attempt policy')
    mixed = None
    if args.default_mixed:
        mixed_path = args.default_mixed.resolve()
        mixed = json.loads(mixed_path.read_text())
        if mixed['status'] != 'PASS_RETENTION1_MIXED_REPLAY' or mixed['qualified_receipt_sha256'] != sha(paths['default']):
            raise RuntimeError('mixed replay lacks the selected default model binding')
        for name, digest in mixed['artifacts'].items():
            if sha(mixed_path.parent / name) != digest:
                raise RuntimeError('mixed replay artifact drift: ' + name)
        for row in mixed['commands']:
            if sha(mixed_path.parent / row['log']) != row['sha256']:
                raise RuntimeError('mixed replay log drift')
    result = {'schema': 'valence-prefetch-policy-scorecard-v1', 'status': 'PASS_THREE_POLICY_SCORECARD',
        'checker_sha256': sha(Path(__file__)),
        'parser_sha256': sha(Path(__file__).with_name('compare_prefetch_retention.py')),
        'receipts': {name: {'path': str(path), 'sha256': sha(path), 'source_commit': receipts[name]['git_head']}
                     for name, path in paths.items()},
        'default_mixed_replay': None if mixed is None else {'path': str(mixed_path), 'sha256': sha(mixed_path)},
        'default_policy': 'one attempt, history clear disabled',
        'profile_labels': {'default': 'one attempt', 'read': 'three attempts',
                          'copy': 'three attempts plus accepted-store history clear'},
        'rows': {},
        'limits': ['Host fixed-DDR cycles/handshakes, not physical bandwidth or mapped PPA',
                   'Read/copy policy models have identical source inputs; historical default mixed replay separately binds its qualified saved model and current guest/host',
                   'All regions execute identical guest bytes; compiler ELF metadata need not be identical',
                   'AXI counters are ROI handshakes and may include non-source traffic or split a transaction at a marker',
                   'No workload weighting or universal/default performance improvement is inferred']}
    for workload in ('steady', 'independent', 'mixed16', 'mixed64'):
        observations = {}
        for profile, receipt in receipts.items():
            if profile == 'default' and workload not in receipt['tests']:
                if mixed is None:
                    raise RuntimeError('missing default mixed workload')
                period = workload.removeprefix('mixed')
                source = mixed_path.parent / ('test-' + workload + '.log')
                guest = mixed['cases'][period]['bin_sha256']
            else:
                source = paths[profile].parent / receipt['tests'][workload]['log']
                guest = receipt['artifacts']['firmware/' + workload + '.bin']
            expected_guest = receipts['read']['artifacts']['firmware/' + workload + '.bin']
            if guest != expected_guest:
                raise RuntimeError('guest bytes differ: ' + workload + '/' + profile)
            observations[profile] = parse(source.read_text())
        regions = list(observations['default']['regions'])
        if any(list(value['regions']) != regions for value in observations.values()):
            raise RuntimeError('region layout differs')
        for name in regions:
            values = {profile: value['regions'][name] for profile, value in observations.items()}
            if len({value['cpu']['retired'] for value in values.values()}) != 1:
                raise RuntimeError('architectural workload size differs')
            row = {'workload': workload, 'region': name, 'profiles': {}}
            for profile, value in values.items():
                row['profiles'][profile] = {'cycles': value['cpu']['cycles'],
                    'retired': value['cpu']['retired'], 'traffic': value['traffic'],
                    'prefetch_events': value['prefetch'], 'read_misses': value['cpu']['read_miss'],
                    'write_misses': value['cpu']['write_miss']}
            result['rows'][workload + '/' + name] = row
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'])


if __name__ == '__main__':
    main()
