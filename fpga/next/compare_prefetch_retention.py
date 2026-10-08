#!/usr/bin/env python3
"""Compare source-identical selected-board prefetch retention profiles."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fields(line):
    return {key: float(value) if '.' in value else int(value)
            for key, value in re.findall(r'([A-Za-z0-9_]+)=([0-9]+(?:\.[0-9]+)?)', line)}


def parse(text):
    result = {'regions': {}, 'traffic_total': None}
    for line in text.splitlines():
        if line.startswith('BOARD_IPC '):
            name = re.search(r'\bname=(\S+)', line).group(1)
            result['regions'][name] = {'cpu': fields(line)}
        for prefix, key in [('STEADY_AXI ', 'ownership'), ('STEADY_PREFETCH ', 'prefetch'),
                            ('STEADY_TRAFFIC ', 'traffic')]:
            if line.startswith(prefix):
                values = fields(line)
                names = list(result['regions'])
                region = values.pop('region')
                if region >= len(names):
                    raise RuntimeError('orphan region counters')
                result['regions'][names[region]][key] = values
        if line.startswith('BOARD_MEMORY_TRAFFIC '):
            result['traffic_total'] = fields(line)
    if result['traffic_total'] is None or not result['regions']:
        raise RuntimeError('missing passive accounting')
    for region in result['regions'].values():
        if set(region) != {'cpu', 'ownership', 'prefetch', 'traffic'}:
            raise RuntimeError('incomplete region accounting')
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--one', type=Path, required=True)
    ap.add_argument('--retained', type=Path, required=True)
    ap.add_argument('--original-control', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    paths = {'one': args.one.resolve(), 'retained': args.retained.resolve()}
    receipts = {key: json.loads(path.read_text()) for key, path in paths.items()}
    if receipts['one']['inputs'] != receipts['retained']['inputs']:
        raise RuntimeError('comparison source inputs differ')
    plans = {key: value['plan']['parameters'] for key, value in receipts.items()}
    tail = plans['retained'][len(plans['one']):]
    if plans['retained'][:len(plans['one'])] != plans['one'] or tail not in (
            ['--prefetch-candidate-cycles=3'], ['--prefetch-candidate-cycles=16']):
        raise RuntimeError('profile delta is not one permitted lifetime option')
    logs = {}
    for key, receipt in receipts.items():
        if receipt['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
            raise RuntimeError('incomplete board proof')
        for name, digest in receipt['artifacts'].items():
            if sha(paths[key].parent / name) != digest:
                raise RuntimeError('artifact drift: ' + name)
        logs[key] = {}
        for name, row in receipt['tests'].items():
            path = paths[key].parent / row['log']
            if sha(path) != row['log_sha256']:
                raise RuntimeError('test log drift: ' + name)
            logs[key][name] = path.read_bytes()
    # Added passive counters and the default-one implementation must preserve
    # every original raw workload line; only the named new accounting rows drop.
    control_path = args.original_control.resolve()
    control = json.loads(control_path.read_text())
    if control['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
        raise RuntimeError('original selected control is not qualified')
    control_hashes = {}
    for name in ('gc', 'steady', 'independent', 'virtual'):
        old = control_path.parent / control['tests'][name]['log']
        if sha(old) != control['tests'][name]['log_sha256']:
            raise RuntimeError('original control log drift')
        stripped = b''.join(line for line in logs['one'][name].splitlines(keepends=True)
            if not line.startswith((b'STEADY_PREFETCH ', b'STEADY_TRAFFIC ', b'BOARD_MEMORY_TRAFFIC ')))
        if stripped != old.read_bytes():
            raise RuntimeError('default-one changed original architecture/timing: ' + name)
        control_hashes[name] = sha(old)
    for name in ('firmware/rv64gc.bin', 'firmware/steady.bin', 'firmware/independent.bin',
                 'firmware/virtual/guest.bin'):
        if receipts['one']['artifacts'][name] != receipts['retained']['artifacts'][name]:
            raise RuntimeError('executed guest bytes differ: ' + name)
    result = {'schema': 'valence-fpga-next-prefetch-retention-comparison-v1',
        'status': 'PASS_SOURCE_MATCHED_BOARD_COMPARISON',
        'source_commit': receipts['retained']['git_head'],
        'comparison_script': {'path': 'fpga/next/compare_prefetch_retention.py',
                              'sha256': sha(Path(__file__))},
        'inputs_sha256': hashlib.sha256(json.dumps(receipts['one']['inputs'], sort_keys=True).encode()).hexdigest(),
        'profile_delta': tail, 'source_inputs_identical': True,
        'receipts': {key: {'path': str(path), 'sha256': sha(path)} for key, path in paths.items()},
        'original_control': {'path': str(control_path), 'sha256': sha(control_path),
                             'raw_logs_preserved_after_named_passive_rows_removed': control_hashes},
        'workloads': {},
        'limits': ['Controlled host DDR model; no physical bandwidth, resources or timing claim',
                   'ROI traffic counts accepted AXI offers and actual data beats, including instruction traffic',
                   'ROI boundary may split transaction ownership; total counters end at the same guest completion condition',
                   'The inherited useful event counts tracked-address read consumption; it is not independently guaranteed to be a cache hit on an invalidation/replacement edge',
                   'Prefetch busy includes token and accepted owner lifetime; no bounded external response or trap-latency claim',
                   'Functional PASS does not automatically select a performance option']}
    for workload in ('steady', 'independent'):
        parsed = {key: parse(value[workload].decode()) for key, value in logs.items()}
        if list(parsed['one']['regions']) != list(parsed['retained']['regions']):
            raise RuntimeError('workload regions differ')
        result['workloads'][workload] = {'profiles': parsed, 'cycle_comparison': {}}
        for name, old in parsed['one']['regions'].items():
            new = parsed['retained']['regions'][name]
            if old['cpu']['retired'] != new['cpu']['retired']:
                raise RuntimeError('ROI retired instruction count changed: ' + name)
            result['workloads'][workload]['cycle_comparison'][name] = {
                'one': old['cpu']['cycles'], 'retained': new['cpu']['cycles'],
                'speedup': old['cpu']['cycles'] / new['cpu']['cycles'],
                'cycle_change_percent': 100 * (new['cpu']['cycles'] / old['cpu']['cycles'] - 1)}
    architecture = {key: receipt['virtual_metrics']['architecture'] for key, receipt in receipts.items()}
    for name in ('signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause', 'trap_tval', 'lsr_reads'):
        if architecture['one'][name] != architecture['retained'][name]:
            raise RuntimeError('virtual architectural outcome differs: ' + name)
    result['virtual'] = {key: receipt['virtual_metrics'] for key, receipt in receipts.items()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'])


if __name__ == '__main__':
    main()
