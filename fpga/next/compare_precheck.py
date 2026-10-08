#!/usr/bin/env python3
"""Validate two frozen board receipts and report inherited precheck tradeoffs."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--off', type=Path, required=True)
    parser.add_argument('--on', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    paths = {'off': args.off.resolve(), 'on': args.on.resolve()}
    receipts = {k: json.loads(p.read_text()) for k, p in paths.items()}
    if receipts['off']['inputs'] != receipts['on']['inputs']:
        raise RuntimeError('source mismatch; this comparison requires identical source inputs')
    plans = {k: r['plan']['parameters'] for k, r in receipts.items()}
    if '--virtual-ram-load-precheck' in plans['off'] or plans['on'] != plans['off'] + ['--virtual-ram-load-precheck']:
        raise RuntimeError('profile changes extend beyond the precheck option')
    for k, receipt in receipts.items():
        if receipt['status'] != 'PASS_FPGA_NEXT_BOARD_SUITE':
            raise RuntimeError('incomplete board proof: ' + k)
        for name, digest in receipt['artifacts'].items():
            if sha(paths[k].parent / name) != digest:
                raise RuntimeError('artifact drift: ' + name)
        for test in receipt['tests'].values():
            if sha(paths[k].parent / test['log']) != test['log_sha256']:
                raise RuntimeError('test-log drift: ' + test['log'])
    result = {
        'schema': 'valence-fpga-next-virtual-precheck-comparison-v1',
        'status': 'PASS_MATCHED_INHERITED_OPTION_REQUALIFICATION',
        'source_commit': receipts['on']['git_head'], 'source_inputs_identical': True,
        'receipts': {k: {'path': str(p), 'sha256': sha(p)} for k, p in paths.items()},
        'physical_workloads_byte_identical': {}, 'virtual': {}, 'architectural_invariants': {},
        'limits': ['Inherited precheck option, not a new architecture invention',
                   'Warm-loop result does not generalize to cold or dependent loads',
                   'Cancellation witness means an accepted LSU owner remains tracked; it is not a physical AXI-phase classification',
                   'No physical resources, routed timing or board qualification; base default remains off']}
    for name in ['gc', 'steady', 'independent']:
        logs = {k: paths[k].parent / r['tests'][name]['log'] for k, r in receipts.items()}
        if logs['off'].read_bytes() != logs['on'].read_bytes():
            raise RuntimeError('physical workload changed: ' + name)
        result['physical_workloads_byte_identical'][name] = sha(logs['off'])
    for name, off in receipts['off']['virtual_metrics']['roi'].items():
        on = receipts['on']['virtual_metrics']['roi'][name]
        for key in ['retired', 'pc_trace', 'physical_requests', 'physical_replies']:
            if off[key] != on[key]:
                raise RuntimeError('ROI architecture differs: ' + name + '/' + key)
        result['virtual'][name] = {'off': off, 'on': on,
            'speedup': off['cycles'] / on['cycles'],
            'cycle_change_percent': 100 * (on['cycles'] / off['cycles'] - 1)}
    for key in ['signature_hash', 'retired', 'pc_trace', 'traps', 'trap_pc', 'trap_cause', 'trap_tval', 'lsr_reads']:
        values = {k: r['virtual_metrics']['architecture'][key] for k, r in receipts.items()}
        if values['off'] != values['on']:
            raise RuntimeError('architecture differs: ' + key)
        result['architectural_invariants'][key] = values['on']
    result['cancelled_outstanding_cycles'] = {
        k: r['virtual_metrics']['architecture']['cancelled_outstanding_cycles'] for k, r in receipts.items()}
    if result['cancelled_outstanding_cycles']['on'] <= 0:
        raise RuntimeError('missing enabled-precheck cancellation witness')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(result['status'])


if __name__ == '__main__':
    main()
