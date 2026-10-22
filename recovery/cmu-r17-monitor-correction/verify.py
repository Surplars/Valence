#!/usr/bin/env python3
"""Read-only verification of the archived r17 monitor-correction evidence."""
import json
import os
from pathlib import Path
import replay

HERE = Path(__file__).resolve().parent


def main():
    replay.require(os.environ.get('VALENCE_CLOUD_ENV'), 'source scripts/cloud/env.sh first')
    manifest, old, emission, historical, command, rtl = replay.validate_inputs()
    archive = HERE/'replay-r1'
    receipt = json.loads((archive/'receipt.json').read_text())
    replay.require(receipt['status'] == 'PASS_HISTORICAL_R17_OBSERVATION_MONITOR_REPLAY',
                   'correction receipt is not PASS')
    replay.require(receipt['positive_simulations_run'] == 0 and receipt['negative_simulations_run'] == 3,
                   'unexpected replay scope')
    replay.require(receipt['current_production_source_qualified'] is False,
                   'historical evidence relabeled as current qualification')
    replay.require(len(receipt['cases']) == 3 and all(c['accepted'] for c in receipt['cases']),
                   'missing/rejected negative case')
    for path, digest in receipt['input_sha256'].items():
        replay.verify(path, digest)
    for name, digest in receipt['logs_sha256'].items():
        replay.verify(archive/name, digest)
    binary = Path(receipt['compile']['command'][receipt['compile']['command'].index('-o')+1])
    replay.verify(binary, receipt['compiled_sha256'])
    replay.verify(binary.parent/'receipt.json', replay.sha(archive/'receipt.json'))
    replay.require(receipt['complete_original_rtl_inventory_sha256'] == old['rtl_sha256'],
                   'archived RTL hashes differ')
    proof = receipt['positive_mode_proof']
    replay.require(proof == json.loads((HERE/'positive-mode-proof.json').read_text()),
                   'positive-mode proof changed')
    for case in receipt['cases']:
        replay.require(case['returncode'] == 1 and not case['timed_out'] and
                       not case['disk_floor_breached'] and case['process_reaped'] and
                       case['timeout_seconds'] == 180 and case['command'][1] == '-i',
                       'negative execution bounds/outcome mismatch')
    print('PASS: three observation-side negatives; zero positive reruns; original evidence unchanged')


if __name__ == '__main__':
    main()
