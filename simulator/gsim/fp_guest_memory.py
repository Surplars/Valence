#!/usr/bin/env python3
"""Owned FP guest-memory components only; actual-core H+FP remains disabled."""
import argparse
import csv
import json
import os
from pathlib import Path
import re
import subprocess

import run as common

PROFILES = (
    ('memory', 'ooo.FpGuestMemoryGsimMain', 'FpGuestMemoryGsim', 'fp_guest_memory.cpp', 'raw-trace.jsonl'),
    ('buffer', 'ooo.FpGuestResponseBufferGsimMain', 'FpGuestResponseBufferGsim', 'fp_guest_response_buffer.cpp', 'raw-trace.csv'),
)
MARKERS = {'memory': 'FP_GUEST_MEMORY_PASS', 'buffer': 'FP_GUEST_RESPONSE_BUFFER_PASS'}
MEMORY_EXACT = {
    'matrix_cases': 50, 'setup_loads': 25, 'commands': 75, 'faults': 30,
    'physical_requests': 49, 'physical_responses': 49, 'lsu_accepts': 75,
    'adapter_accepts': 71, 'buffer_responses': 71, 'wrong_tags': 150,
    'wrong_indices': 75, 'denied_head': 75, 'mutations': 35,
    'context_before_accept': 75, 'context_after_capture': 71, 'pma_checks': 53,
}
MEMORY_ARRAYS = {'fault_rows': [20, 4, 6, 4, 4, 4, 4, 4], 'mode_rows': [6, 6, 38], 'op_rows': [14, 14, 11, 11]}
MEMORY_NEGATIVES = {
    'faultclass': 'precise load/store fault class mismatch',
    'gpa': 'unshifted GPA or stale metadata mismatch',
    'physical_address': 'physical SPA mismatch',
    'physical_mask': 'physical byte mask mismatch',
    'fpdata': 'raw FP load/store completion data mismatch',
    'token': 'full completion token mismatch',
    'state_mutation': 'FPR/fcsr/FS changed outside an accepted successful load or authorized idle CSR access',
    'guest_address': 'routed accepted guest address provenance missing',
}
BUFFER_NEGATIVES = {
    'metadata-mismatch': ('BUFFER_METADATA_MISMATCH', 2),
    'return-handle-mismatch': ('BUFFER_RETURN_HANDLE_MISMATCH', 1),
    'occupancy-mismatch': ('BUFFER_OCCUPANCY_MISMATCH', 0),
    'ordering-mismatch': ('BUFFER_ORDERING_MISMATCH', 0),
}
BUFFER_MODES = ('queue_flow', 'queue_registered', 'registered_head', 'empty_head_flow')
BUFFER_POSITIVE = ('held_inputs', 'held_outputs', 'full_cycles', 'full_pop_no_credit', 'empty_capture',
                   'head_replacement', 'tail_promotion', 'request_transfers', 'request_holds', 'requests_while_full')


def need(value, message):
    if not value:
        raise RuntimeError(message)


def unique_object(pairs):
    value = dict(pairs)
    need(len(value) == len(pairs), 'duplicate evidence field')
    return value


def integer(row, key):
    value = row.get(key)
    need(type(value) is int and value >= 0, 'missing or invalid unsigned evidence field: ' + key)
    return value


def clean_text(path):
    raw = path.read_bytes()
    need(all(value >= 32 or value in (9, 10, 13) for value in raw), 'nontext control byte in evidence')
    text = raw.decode('utf-8')
    need('AddressSanitizer' not in text and 'runtime error:' not in text, 'sanitizer failure is not evidence')
    return text



def memory_case_names():
    ops = ('flw', 'fsw', 'fld', 'fsd')
    cases = []
    for mode in range(3):
        for op in ops:
            for lane in ((0, 4) if op in ('flw', 'fsw') else (0,)):
                cases.append((f'success_{mode}_{op}_{lane}', op))
    for op in ops:
        for fault in ('misaligned', 'vs_page', 'explicit_guest', 'implicit_guest', 'pmp', 'pma', 'bus'):
            cases.append((fault + '_' + op, op))
    for op in ops:
        cases.append(('vu_' + op + ('_user_allowed' if op in ('fsw', 'fld') else '_supervisor_denied'), op))
    return [name for case, op in cases for name in (('setup_' + case, case) if op in ('fsw', 'fsd') else (case,))]


def check_positive(path, profile, trace):
    text = clean_text(path)
    need('FP_GUEST_MEMORY_CHECK[' not in text and 'FP_GUEST_RESPONSE_BUFFER_FAIL' not in text,
         'positive component execution contains failure')
    marker = MARKERS[profile]
    lines = text.rstrip().splitlines()
    footers = [line[len(marker) + 1:] for line in lines if line.startswith(marker + ' ')]
    need(len(footers) == 1 and lines[-1] == marker + ' ' + footers[0], 'expected one final component summary')
    row = json.loads(footers[0], object_pairs_hook=unique_object)
    need(isinstance(row, dict) and row.get('component_only') is True and row.get('guest_fd_execution') is False,
         'component-only evidence scope changed')
    need(trace.is_file() and 0 < trace.stat().st_size < (20 if profile == 'memory' else 10) * 1024 * 1024,
         'missing or excessive raw component trace')
    if profile == 'memory':
        need(integer(row, 'schema') == 1 and isinstance(row.get('schedules'), list) and len(row['schedules']) == 2,
             'two memory schedules required')
        for index, schedule in enumerate(row['schedules']):
            need(isinstance(schedule, dict) and integer(schedule, 'schedule') == index, 'memory schedule identity mismatch')
            need(all(integer(schedule, key) == value for key, value in MEMORY_EXACT.items()), 'memory directed coverage incomplete')
            for key, expected in MEMORY_ARRAYS.items():
                actual = schedule.get(key)
                need(isinstance(actual, list) and all(type(v) is int for v in actual) and actual == expected,
                     'memory matrix differs: ' + key)
            need(0 < integer(schedule, 'cycles') <= 30000 and schedule.get('drained') is True, 'memory owner not drained or trace bound exceeded')
            need(integer(schedule, 'pte_requests') == integer(schedule, 'pte_responses') > 0, 'PTE credit mismatch')
            need(integer(schedule, 'held_physical') > 0 and integer(schedule, 'held_pte') > 0 and
                 integer(schedule, 'held_completions') >= 450, 'memory backpressure evidence missing')
        expected_cases = memory_case_names()
        counts, completed, active, active_edges = [0, 0], [0, 0], [None, None], [0, 0]
        last_schedule = 0
        with trace.open() as stream:
            for line in stream:
                edge = json.loads(line, object_pairs_hook=unique_object)
                need(isinstance(edge, dict), 'memory trace edge must be an object')
                index = integer(edge, 'schedule')
                need(index in (0, 1) and last_schedule <= index, 'memory trace schedule ordering')
                last_schedule = index
                event = edge.get('event')
                if event in ('memory_init', 'memory_final'):
                    need(integer(edge, 'cycle') == counts[index] and isinstance(edge.get('bytes'), list),
                         'memory endpoint snapshot boundary mismatch')
                    if event == 'memory_init':
                        need(active[index] is None and completed[index] < len(expected_cases) and
                             edge.get('case') == expected_cases[completed[index]] and isinstance(edge.get('ptes'), list),
                             'memory trace case matrix mismatch')
                        active[index], active_edges[index] = edge['case'], 0
                    else:
                        need(edge.get('case') == active[index] and active[index] is not None and active_edges[index] > 0,
                             'memory endpoint final has no observed command')
                        active[index] = None
                        completed[index] += 1
                    continue
                counts[index] += 1
                need(integer(edge, 'cycle') == counts[index], 'memory trace cycle gap')
                if event == 'idle_init':
                    need(counts[index] <= 3 and active[index] is None and
                         isinstance(edge.get('set_fs'), list) and len(edge['set_fs']) == 2 and
                         isinstance(edge.get('csr'), list) and len(edge['csr']) == 5,
                         'missing raw idle initialization inputs')
                    integer(edge, 'fs'); integer(edge, 'fcsr')
                else:
                    need(event is None and counts[index] > 3 and edge.get('case') == active[index] and active[index] is not None,
                         'memory edge outside accepted case scope')
                    lengths = {'command': 6, 'context': 11, 'handshake': 5, 'retire': 5, 'pte': 6,
                               'physical': 7, 'virtual_request': 2, 'pma': 6, 'adapter_response': 4,
                               'buffer_response': 3, 'pipeline': 2, 'converted': 12, 'complete': 2,
                               'state': 4, 'fpr': 32, 'idle': 4}
                    need(all(isinstance(edge.get(key), list) and len(edge[key]) == length for key, length in lengths.items()),
                         'missing raw memory interface observation')
                    active_edges[index] += 1
        need(active == [None, None] and completed == [75, 75] and
             counts == [s['cycles'] for s in row['schedules']], 'memory raw trace/summary count mismatch')
    else:
        exact = {'configs': 16, 'capacity': 2, 'cycles': 732, 'cycle_limit': 1024,
                 'idle_resets': 2, 'reset_cycles': 4, 'trace_rows': 11712}
        need(all(integer(row, key) == value for key, value in exact.items()), 'buffer schedule/configuration count mismatch')
        need(integer(row, 'trace_bytes') == trace.stat().st_size, 'buffer raw trace byte count mismatch')
        need(isinstance(row.get('lanes'), list) and len(row['lanes']) == 16, 'all buffer lanes required')
        for index, lane in enumerate(row['lanes']):
            metadata, tagged, flow = bool((index // 2) % 2), bool(index % 2), index // 4 in (0, 3)
            need(integer(lane, 'lane') == index and lane.get('mode') == BUFFER_MODES[index // 4] and
                 lane.get('metadata') is metadata and lane.get('tagged') is tagged, 'buffer lane identity mismatch')
            need(integer(lane, 'accepted') == integer(lane, 'consumed') > 300 and integer(lane, 'max_occupancy') == 2,
                 'buffer conservation/capacity evidence incomplete')
            need(all(integer(lane, key) > 0 for key in BUFFER_POSITIVE), 'buffer ownership coverage missing')
            need(integer(lane, 'continuous_accepted') == 128 and integer(lane, 'continuous_consumed') == (128 if flow else 127),
                 'buffer continuous transfer evidence differs')
            need((integer(lane, 'empty_bypass') > 0 if flow else integer(lane, 'empty_bypass') == 0) and
                 integer(lane, 'status_mask') == 15, 'buffer mode/status coverage differs')
            need(all(integer(lane, key) > 0 if metadata else integer(lane, key) == 0
                     for key in ('metadata_changes', 'metadata_clears', 'high_gpa')) and
                 integer(lane, 'metadata_mask') == (255 if metadata else 1), 'buffer metadata coverage differs')
            need((integer(lane, 'high_handle') > 0 if tagged else integer(lane, 'high_handle') == 0) and
                 integer(lane, 'handle_mask') == ((1 << 64) - 1 if tagged else 1), 'buffer handle coverage differs')
        count = 0
        with trace.open(newline='') as stream:
            reader = csv.DictReader(stream)
            need(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames) and
                 {'cycle', 'lane', 'reset', 'input_valid', 'input_ready', 'output_valid', 'output_ready'} <= set(reader.fieldnames),
                 'buffer raw trace header missing or duplicate')
            for edge in reader:
                need(None not in edge and all(value is not None for value in edge.values()), 'malformed buffer trace row')
                need(edge['cycle'].isdecimal() and edge['lane'].isdecimal() and
                     int(edge['cycle']) == count // 16 and int(edge['lane']) == count % 16, 'buffer trace ordering/gap')
                count += 1
        need(count == row['trace_rows'], 'buffer raw trace row count mismatch')
    return row


def check_negative(path, profile, name, returncode):
    text = clean_text(path)
    need(returncode == 1, 'negative must exit exactly one')
    need(all(marker not in text for marker in MARKERS.values()), 'negative unexpectedly passed')
    lines = text.rstrip().splitlines()
    if profile == 'memory':
        need(lines == [f'FP_GUEST_MEMORY_CHECK[{name}]: {MEMORY_NEGATIVES[name]}'], 'memory negative missed its named checker')
    else:
        label, lane = BUFFER_NEGATIVES[name]
        need(len(lines) == 2, 'buffer negative requires injection and named failure')
        match = re.fullmatch(r'FP_GUEST_RESPONSE_BUFFER_NEGATIVE ' + re.escape(name) + r' lane=' + str(lane) + r' cycle=(\d+)', lines[0])
        need(match is not None and lines[1] == f'FP_GUEST_RESPONSE_BUFFER_FAIL {label} lane={lane} cycle={match[1]}',
             'buffer negative missed its named checker')


def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    gsim, cxx = common.setup(False)
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    for profile, main_class, model, driver, trace_name in PROFILES:
        trace = common.BUILD / 'fp-guest-memory' / profile / trace_name
        output = common.test(gsim, cxx, 'fp-guest-memory/' + profile, main_class, model, driver,
                             runtime_args=('--trace', str(trace)), cxx_flags=('-fbracket-depth=4096',),
                             timeout=120, mill_module='IonSoC.fpGuestMemoryPreparation')
        check_positive(output / 'test.log', profile, trace)
        negatives = MEMORY_NEGATIVES if profile == 'memory' else BUFFER_NEGATIVES
        for name in negatives:
            path = output / ('negative-' + name + '.log')
            with path.open('w') as log:
                result = subprocess.run([str(output / 'run'), '--negative', name], cwd=common.ROOT,
                                        stdout=log, stderr=subprocess.STDOUT, env=env, timeout=120)
            check_negative(path, profile, name, result.returncode)
    print('FP_GUEST_MEMORY_STANDARD_PASS')


if __name__ == '__main__':
    main()
