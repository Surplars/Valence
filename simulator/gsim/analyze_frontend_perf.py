#!/usr/bin/env python3
"""Verify passive frontend probes against the archived same-BIN baseline."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def rows(text, prefix):
    result = []
    for line in text.splitlines():
        if line.startswith(prefix + ' '):
            row = dict(pair.split('=', 1) for pair in line.split()[1:])
            result.append({k: int(v) if re.fullmatch(r'[0-9]+', v) else v for k, v in row.items()})
    return result


def analyze(current, baseline, candidate=False):
    result = {'equivalence': {}, 'observations': {}, 'limitations': [
        'Event matrix overlaps; it is not an additive causal CPI breakdown.',
        'Adapter phases partition cycles by interface predicates; unclassified phase is retained explicitly.',
        'Correction-to-next-retirement can retire older work and does not identify correct-path retirement.',
        'Correction latency stops at first event or is superseded by another correction; censored windows are reported.',
        'Local non-inclusive redirects include branches and other local redirects; successor correction is not synonymous with misprediction.',
        'InstructionRom registered window internals and InstructionLineCache hit/refill state are not exposed in this first probe pass.',
        'Read-only taps are sampled at the existing harness post-step boundary, like legacy retirement counters.',
        'No physical board, routed timing, long Linux, numerical FPU throughput, or official CoreMark score.'
    ]}
    receipt = json.loads((current / 'receipt.json').read_text())
    assert receipt['status'] == 'PASS_SHORT_PERFORMANCE_AND_FUNCTIONAL', receipt['status']
    for name in ('board_coremark', 'ddr_bench_app', 'rv64gc_board'):
        if name not in receipt['board']:
            continue
        text = (current / (name + '.log')).read_text()
        old = (baseline / (name + '.log')).read_text()
        before, after = rows(old, 'BOARD_IPC'), rows(text, 'BOARD_IPC')
        if name != 'board_coremark':
            before = [r for r in before if r['name'].startswith('whole_run_')]
            after = [r for r in after if r['name'].startswith('whole_run_')]
        if not candidate:
            assert before == after, (name, 'retirement/cycle/cache counters changed', before, after)
        # Drop only added passive telemetry; original guest/UART output must be byte-for-byte identical.
        old_lines = [l for l in old.splitlines() if not l.startswith(('BOARD_IPC ', 'FRONTEND_', 'ICACHE_', 'RETIRE_PC_STREAM ', 'BACKEND_'))]
        new_lines = [l for l in text.splitlines() if not l.startswith(('BOARD_IPC ', 'FRONTEND_', 'ICACHE_', 'RETIRE_PC_STREAM ', 'BACKEND_'))]
        if not candidate:
            assert old_lines == new_lines, (name, 'original guest output changed')
        else:
            # Harnesses independently reject bad signatures; also require CoreMark CRC text unchanged.
            crc_before = [l for l in old_lines if 'crc' in l.lower()]
            crc_after = [l for l in new_lines if 'crc' in l.lower()]
            assert crc_before == crc_after, (name, 'CRC output changed')
            result.setdefault('performance_comparison', {})[name] = {'baseline': before, 'candidate': after}
            if name == 'board_coremark':
                ticks_before = int(re.search(r'Total ticks\s*:\s*(\d+)', old)[1])
                ticks_after = int(re.search(r'Total ticks\s*:\s*(\d+)', text)[1])
                result['performance_comparison'][name].update(guest_ticks_baseline=ticks_before, guest_ticks_candidate=ticks_after, guest_cycle_reduction_percent=100*(ticks_before-ticks_after)/ticks_before)
        hist = rows(text, 'FRONTEND_HIST')
        phases = rows(text, 'FRONTEND_PHASE')
        for h in hist:
            assert sum(h[f'occupancy_{i}'] for i in range(5)) == h['cycles']
            for kind in ('supply', 'capture', 'rename'):
                assert sum(h[f'{kind}_{i}'] for i in range(3)) == h['cycles']
            matching = [p for p in phases if p['name'] == h['name']]
            assert sum(p['cycles'] for p in matching) == h['cycles']
            old_counter = after[0] if h['name'] == 'whole_run' else after[1]
            assert sum(p['head_empty'] for p in matching) == old_counter['head_empty']
            assert sum(p['zero_commit'] for p in matching) == old_counter['zero_commit']
            event_rows = [e for e in rows(text, 'FRONTEND_EVENT') if e['name'] == h['name']]
            assert all(0 <= e['head_empty'] <= e['cycles'] and 0 <= e['zero_commit'] <= e['cycles'] for e in event_rows)
            size_rows = [g for g in rows(text, 'FRONTEND_GET_SIZE') if g['name'] == h['name']]
            if size_rows:
                gets = next(e['cycles'] for e in event_rows if e['event'] == 'fetch_tl_get')
                assert sum(g['count'] for g in size_rows) == gets
                assert sum(g['count'] for g in rows(text, 'FRONTEND_GET_LINE') if g['name'] == h['name']) == gets
            backend_zero = [r for r in rows(text, 'BACKEND_ZERO_COMMIT') if r['name'] == h['name']]
            if backend_zero:
                assert sum(r['cycles'] for r in backend_zero) == old_counter['zero_commit']
                ex = next(r['cycles'] for r in backend_zero if r['state'] == 'executing')
                assert sum(r['cycles'] for r in rows(text, 'BACKEND_EXECUTING') if r['name'] == h['name']) == ex
            cache_states = [r for r in rows(text, 'ICACHE_STATE') if r['name'] == h['name']]
            if cache_states:
                assert sum(r['cycles'] for r in cache_states) == h['cycles']
                assert sum(r['head_empty'] for r in cache_states) == old_counter['head_empty']
                assert sum(r['zero_commit'] for r in cache_states) == old_counter['zero_commit']
                wait = next(e for e in event_rows if e['event'] == 'physical_wait_no_reply')
                assert sum(r['physical_wait_no_reply'] for r in cache_states) == wait['cycles']
                assert sum(r['physical_wait_no_reply_head_empty'] for r in cache_states) == wait['head_empty']
                ce = {r['event']: r['cycles'] for r in rows(text, 'ICACHE_EVENT') if r['name'] == h['name']}
                assert ce['accepted_hit'] + ce['accepted_miss'] + ce['accepted_fallback'] == ce['request']
                lat = [r for r in rows(text, 'ICACHE_LATENCY') if r['name'] == h['name']]
                boundary = next(r for r in rows(text, 'ICACHE_BOUNDARY') if r['name'] == h['name'])
                assert sum(r['transactions'] for r in lat) + boundary['orphan_replies'] == ce['response']
                assert sum(r['transactions'] for r in lat) + boundary['request_pending'] == ce['request']
                assert sum(r['count'] for r in rows(text, 'ICACHE_TL_SOURCE') if r['name'] == h['name']) == ce['tl_a_fire']
                for r in lat:
                    bins = [b for b in rows(text, 'ICACHE_LATENCY_BIN') if b['name'] == h['name'] and b['class'] == r['class']]
                    assert sum(b['count'] for b in bins) == r['transactions']

        assert hist[0]['cycles'] == after[0]['cycles']
        if name == 'board_coremark':
            assert hist[1]['cycles'] == after[1]['cycles']
        result['equivalence'][name] = 'PASS independent harness and CRC checks; performance may differ' if candidate else 'PASS exact original log and all existing counters'
        result['observations'][name] = {prefix: rows(text, prefix) for prefix in (
            'FRONTEND_HIST', 'FRONTEND_EVENT', 'FRONTEND_PHASE', 'FRONTEND_CORRECTION', 'FRONTEND_GET_SIZE', 'FRONTEND_GET_LINE', 'ICACHE_EVENT', 'ICACHE_STATE', 'ICACHE_TL_SOURCE', 'ICACHE_LATENCY', 'ICACHE_LATENCY_BIN', 'ICACHE_BOUNDARY', 'BACKEND_ZERO_COMMIT', 'BACKEND_EXECUTING', 'BACKEND_REQUEST', 'RETIRE_PC_STREAM')}
    for file in (current / 'firmware').glob('*.bin'):
        assert file.read_bytes() == (baseline / 'firmware' / file.name).read_bytes(), file.name
    result['equivalence']['firmware'] = 'PASS all BIN bytes identical'
    result['status'] = 'PASS_CANDIDATE_FUNCTIONAL_PERFORMANCE' if candidate else 'PASS_PASSIVE_PROBE_EQUIVALENCE'
    (current / 'frontend-analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    return result

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('current', type=Path)
    ap.add_argument('baseline', type=Path)
    ap.add_argument('--candidate', action='store_true', help='Allow measured cycle/retirement changes while checking independent workload oracles and BIN equality')
    args = ap.parse_args()
    print(json.dumps(analyze(args.current, args.baseline, args.candidate)['equivalence'], indent=2))
