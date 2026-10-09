#!/usr/bin/env python3
"""Read-only complete NEMU audit; optionally write a new, separate summary.

Requires all twelve positive cases and all six corruption negatives. Revalidates
source/guest/model/reference hashes and exact command/log/binary bindings. Does
not execute a compiler, guest, model or reference; never edits the run receipt.
"""
import argparse
import json
from pathlib import Path

import cpu_flow_board_nemu as replay


def audit(receipt, inputs=None):
    receipt = Path(receipt).resolve()
    out = receipt.parent
    state = replay.load(receipt)
    require = replay.require
    require(state.get('schema') == replay.SCHEMA and state.get('status') == replay.PASS, 'completed integrated NEMU receipt required')
    require(state.get('scope') == replay.SCOPE, 'scope/claim drift')
    require(all(state.get(key) == value for key, value in replay.ZERO_COUNTERS.items()), 'rebuild/resynchronization claim drift')
    snapshot = state['inputs']
    if inputs is None:
        inputs = replay.Inputs(snapshot['source_root'], snapshot['flow_receipt'], snapshot['reference_cache'],
                               recorded_root=snapshot['recorded_root'], compiler=snapshot['compiler'])
    require(snapshot == inputs.snapshot, 'reconstructed input snapshot drift')
    require(state.get('reference') == inputs.used, 'reference attestation drift')
    replay.compare_pairs(state['cases'])
    expected_negatives = {label + '-negative-nemu-' + mode for label in replay.LABELS for mode in replay.NEGATIVES}
    require(set(state.get('negatives', {})) == expected_negatives, 'incomplete/unexpected negative set')
    expected_steps = {label + '-' + case + '-' + step for label in replay.LABELS for case in replay.CASES for step in ('link', 'run')}
    require(set(state['steps']) == expected_steps | expected_negatives, 'incomplete/unexpected replay step set')
    summary = {'schema': 'valence-integrated-board-hot-nemu-audit-v1', 'status': 'PASS_FINAL_AUDIT',
               'receipt_sha256': replay.sha(receipt), 'flow_receipt_sha256': replay.sha(inputs.flow_path),
               'scope': replay.SCOPE, 'cases': {}, 'negatives': {}, 'totals': {}}

    def step(name, command, expected=0, products=None):
        record = state['steps'][name]
        require(record['command'] == list(map(str, command)), 'command binding mismatch: ' + name)
        require(record['exit'] == expected, 'exit mismatch: ' + name)
        log = replay.contained(out, record['log'])
        require(replay.sha(log) == record['log_sha256'], 'log hash mismatch: ' + name)
        require(record['artifacts'] == (products or {}), 'artifact binding mismatch: ' + name)
        for path, digest in record['artifacts'].items():
            require(replay.sha(replay.contained(out, path)) == digest, 'binary hash mismatch: ' + name)
        return log.read_text()

    for label in replay.LABELS:
        for case in replay.CASES:
            key = label + '-' + case
            record = state['cases'][key]
            binary = out / label / case / 'run'
            guest = inputs.cases[case]['directory'] / 'guest.bin'
            require(record['guest_sha256'] == replay.sha(guest), 'guest hash mismatch: ' + key)
            step(key + '-link', inputs.command(label, case, out), products={str(binary.relative_to(out)): record['binary_sha256']})
            text = step(key + '-run', [binary, guest, inputs.so])
            counters = replay.nemu_counters(text)
            require(record['nemu'] == counters, 'NEMU log/counter mismatch: ' + key)
            require(record.get('hot_result_exactly_unchanged') is True, 'missing hot-result check: ' + key)
            require(replay.line(text, 'HOT_RESULT') == inputs.original_results[key], 'hot measurement changed: ' + key)
            summary['cases'][key] = {'hot_result_exactly_unchanged': True, **counters}
            for metric in ('guest_pc_checks', 'guest_retire_edges', 'dual_retire_edges',
                           'guest_gpr_edges', 'gpr_value_checks', 'final_memory_bytes'):
                summary['totals'][metric] = summary['totals'].get(metric, 0) + int(counters[metric])
        binary = out / label / 'read-4096/run'
        guest = inputs.cases['read-4096']['directory'] / 'guest.bin'
        for mode, anchor in replay.NEGATIVES.items():
            name = label + '-negative-nemu-' + mode
            require(state['negatives'][name] == {'expected_exit': 1, 'required_anchor': anchor}, 'negative expectation drift: ' + name)
            text = step(name, [binary, guest, inputs.so, '--inject-nemu-' + mode], expected=1)
            require(anchor in text and 'NEMU_PASS' not in text, 'negative checker did not reject: ' + name)
            summary['negatives'][name] = {'exit': 1, 'anchor': anchor, 'log_sha256': state['steps'][name]['log_sha256']}
    inputs.guard()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--summary', type=Path, help='Optional new summary path; existing files are never overwritten')
    args = parser.parse_args()
    summary = audit(args.receipt)
    if args.summary:
        replay.require(args.summary.resolve() != args.receipt.resolve(), 'summary cannot overwrite the receipt')
        with args.summary.open('x') as stream:
            stream.write(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'status': summary['status'], 'receipt_sha256': summary['receipt_sha256'],
                      'cases': len(summary['cases']), 'negatives': len(summary['negatives']),
                      'scope': replay.SCOPE, 'totals': summary['totals']}, indent=2))


if __name__ == '__main__':
    main()
