#!/usr/bin/env python3
"""Read-only byte, input and historical evidence validation; never executes a DUT."""
import hashlib
import json
import re
import sys
from pathlib import Path
sys.dont_write_bytecode = True
from prepare_inputs import generated_guests, generated_controls
HERE = Path(__file__).resolve().parent

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())

def verify_records(records):
    assert len(records) == 31
    positive = [r for r in records if r['kind'] in ('original', 'corrected')]
    negative = [r for r in records if r['kind'] == 'negative']
    trace = [r for r in records if r['kind'] == 'passive_trace']
    assert len(positive) == 24 and len(trace) == 2
    diagnostics = {'value': 'INDEPENDENT_COMPLETION_VALUE', 'owner': 'INDEPENDENT_FULL_TOKEN_COMPLETION_ADMISSION',
                   'replacement': 'OLD_VALUE_REFILL_OPERAND', 'trap': 'trap', 'stale_response': 'UNKNOWN_FULL_TOKEN'}
    assert {r['control'] for r in negative} == set(diagnostics) and len(negative) == 5
    for row in records:
        for key in ['raw_log_sha256', 'original_receipt_sha256']: assert re.fullmatch('[0-9a-f]{64}', row[key])
        assert row['sanitizer_clean'] and not row.get('timeout', False)
        if row['kind'] == 'negative':
            assert row['status'] == 'PASS_EXPECTED_REJECTION' and row['exit'] == 1
            assert row['mutation_applied'] and row['mutation_anchor'] == 'B1_MUTATION_APPLIED name='+row['control']
            assert row['diagnostic'] == diagnostics[row['control']] and not row['functional_pass_anchor_present']
        else:
            assert row['status'] == 'PASS_FUNCTIONAL' and row['exit'] == 0 and row['functional_pass_anchor_present']
            actual = row['case']
            assert actual['name'] == row['name'] and actual['enabled'] == (row['mode'] == 'on')
    for name in {r['name'] for r in positive}:
        pair = {r['mode']: r['case'] for r in positive if r['name'] == name}
        assert set(pair) == {'off', 'on'}
        for key in ['cycles', 'retired', 'architectural_hash']: assert pair['off'][key] == pair['on'][key]
        if name == 'D1-bare-p0-x2-gated':
            assert pair['off']['observations']['held_captures'] == 0
            assert pair['on']['observations']['held_captures'] == 1
            assert pair['on']['observations']['held_C1_accepted'] == 1
        else: assert pair['on']['observations'].get('held_captures', 0) == 0
    return {'functional_passes': len(positive), 'passive_trace_repeats': len(trace), 'reached_negatives': len(negative)}

def check():
    assert not sys.flags.optimize, 'Python assertions must remain enabled'
    manifest = read(HERE/'manifest.json')
    actual = {p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file() and p.name != 'manifest.json'}
    assert actual == set(manifest['files']), 'fixture file set drift'
    for name, digest in manifest['files'].items():
        path = HERE/name
        assert not path.is_symlink() and sha(path) == digest, name
        assert (b'/' + b'workspace/') not in path.read_bytes(), 'nonportable workspace path: '+name
        assert path.suffix not in {'.bin', '.o', '.elf', '.fir', '.pyc', '.so'}, name
    provenance = read(HERE/'provenance.json')
    for name, digest in provenance['reused_host_files'].items(): assert sha(HERE/name) == digest, name
    for name, item in provenance['source_files'].items():
        if item['treatment'] == 'EXACT_BYTES': assert sha(HERE/name) == item['source_sha256'], name
    generated_guests()
    schedule = read(HERE/'schedule.json')
    assert len(schedule['case_order']) == 11 and schedule['mode_order'] == ['off', 'on']
    assert schedule['cycles_per_reset'] == 30000 and schedule['timeout_seconds_per_reset'] == 120
    controls = generated_controls()
    assert set(controls) == set(schedule['case_order']) | {'D1-bare-p0-x2-gated'}
    frozen = read(HERE/'evidence/causal-freeze.json')
    assert sha(HERE/'evidence/causal-freeze.json') == provenance['causal_guest_freeze_sha256'] == 'ae21643c1f18e6df7bce21921e52623ed3f3a97b4de4bd3d5854967108817196'
    assert hashlib.sha256(controls['D1-bare-p0-x2-gated']).hexdigest() == frozen['input_sha256']
    final = read(HERE/'evidence/final-combined-projection.json')
    assert final['original_final_combined_sha256'] == '5ab6363f6e1c0487f115a095c96a50068f6e6ce1f1a9c2e23552a7ccee3de9df'
    assert final['qualified'] is False and final['scope']['default'] == 'OFF'
    assert final['scope']['joint_on'] == 'UNMEASURED'
    assert final['negative_controls']['NOT_REACHED'] == ['priority', 'kill']
    assert len(final['remaining_missing_witnesses']) == 5
    rows = read(HERE/'evidence/results.json')['records']
    counts = verify_records(rows)
    edges = {r['cycle']: r for r in read(HERE/'evidence/causal-causal-edges.json')}
    assert (edges[780]['s0_index'], edges[780]['s0_tag']) == (14, 49)
    assert edges[780]['s0_occupied'] == edges[780]['s1_capture'] == 1 and edges[780]['s0_deqReady'] == 0
    assert (edges[781]['s1_index'], edges[781]['s1_tag']) == (15, 50)
    assert edges[781]['s0_deqReady'] == edges[781]['c1_accepted'] == 1
    assert edges[782]['mul_start'] == edges[783]['lsu_start'] == 1
    assert edges[782]['s0_occupied'] == edges[783]['s0_occupied'] == 0
    for name in ['binding_memory_generate.py', 'binding_memory_core_generate.py']:
        text = (HERE/name).read_text()
        assert "type=Path,required=True" in text and 'required field binding incomplete' in text
    return {'status': 'PASS_READ_ONLY_FIXTURE_CHECK_NO_BUILD_NO_DUT_RUN', **counts, 'manifest_files': len(manifest['files']), 'reused_host_files': len(provenance['reused_host_files'])}

if __name__ == '__main__': print(json.dumps(check(), indent=2))
