#!/usr/bin/env python3
"""Three-domain owner/selector components only; actual-core H+FP stays guarded."""
import argparse
import json
import os
from pathlib import Path
import subprocess

import run as common


MARKER = 'MEMORY_DOMAIN_SELECTOR_SUMMARY'
STANDARD_MARKER = 'MEMORY_DOMAIN_SELECTOR_STANDARD_PASS'
TIMEOUT = 120
TRACE_LIMIT = 12 * 1024 * 1024
CYCLE_LIMIT = 4096
SCHEDULE_CYCLES = {'baseline': 877, 'staggered': 1261}
NEGATIVE_LOCATIONS = {
    'owner': (0, 58), 'classification': (0, 3), 'request_payload': (0, 45),
    'request_exclusion': (0, 45), 'response_payload': (0, 49),
    'response_exclusion': (0, 49), 'metadata': (0, 49), 'handle': (1, 45),
    'stall': (0, 46), 'busy': (0, 3), 'retirement': (0, 66),
}
SCHEDULES = ('baseline', 'staggered')
NEGATIVES = ('owner', 'classification', 'request_payload', 'request_exclusion',
             'response_payload', 'response_exclusion', 'metadata', 'handle',
             'stall', 'busy', 'retirement')
REQUEST_FIELDS = ['address', 'data', 'epoch', 'handle', 'size', 'mask', 'op',
                  'write', 'atomic', 'virtualized', 'prechecked', 'hint', 'uncached']
REPLY_FIELDS = ['data', 'gpa', 'handle', 'error', 'page', 'guest_page_fault',
                'guest_address', 'implicit_pte']
REQUEST_WIDTHS = (64, 64, 32, 5, 2, 8, 5, 1, 1, 1, 1, 1, 1)
REPLY_WIDTHS = (64, 64, 5, 1, 1, 1, 1, 1)
# H 1.0 fixed source/destination-register probes, independently enumerated.
H_FORMS = tuple(0x60004073 | (size << 26) | (variant << 20) | (9 << 15) | (7 << 7)
                for size in range(4) for variant in ((0, 1) if size < 3 else (0,))) + tuple(
    0x60004073 | (size << 26) | (3 << 20) | (9 << 15) | (7 << 7) for size in (1, 2)) + tuple(
    0x62004073 | (size << 26) | (11 << 20) | (9 << 15) for size in range(4))
INPUT_ARRAYS = {'start': (1, 4, 64, 32), 'complete': (1, 4, 64),
                'request_valid': (1, 1, 1), 'response_ready': (1, 1, 1),
                'native_response': REPLY_WIDTHS, 'busy': (1, 1, 1, 1, 1)}
INPUT_SCALARS = {'native_request_ready': 1, 'native_response_valid': 1,
                 'architectural_fp_busy': 1}
OUTPUT_ARRAYS = {'owner': (1, 4, 64, 1, 1, 1), 'decode': (1, 1, 1, 1),
                 'request_ready': (1, 1, 1), 'response_valid': (1, 1, 1),
                 'native_request': REQUEST_WIDTHS}
OUTPUT_SCALARS = {'domain': 2, 'retired': 1, 'retire_matches': 2, 'busy': 1,
                  'cpu_busy': 1, 'architecture_only': 1, 'native_request_valid': 1,
                  'native_response_ready': 1}
LANE_COUNTERS = ('starts', 'completions', 'retirements', 'request_stalls',
                 'response_stalls', 'response_delay', 'post_response_holds',
                 'wrong_tag', 'wrong_index', 'arithmetic_overlap', 'busy_masks',
                 'metadata_mask', 'status_mask', 'h_forms', 'handles',
                 'sustained_requests', 'sustained_turnovers')


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def unique_object(pairs):
    value = dict(pairs)
    need(len(value) == len(pairs), 'duplicate evidence field')
    return value


def unsigned(value, width=64):
    return type(value) is int and 0 <= value < (1 << width)


def keys(row, expected, label):
    need(type(row) is dict and set(row) == set(expected), 'missing or unexpected ' + label + ' field')


def vector(value, widths, label):
    need(type(value) is list and len(value) == len(widths) and
         all(unsigned(item, width) for item, width in zip(value, widths)),
         'missing or invalid raw ' + label)


def clean_text(path, limit=TRACE_LIMIT):
    need(path.is_file() and 0 < path.stat().st_size <= limit, 'missing, empty or excessive evidence: ' + str(path))
    raw = path.read_bytes()
    need(all(value >= 32 or value in (9, 10, 13) for value in raw), 'nontext control byte in evidence')
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError as error:
        raise RuntimeError('non-UTF-8 evidence') from error
    need('Sanitizer' not in text and 'runtime error:' not in text, 'sanitizer failure is not evidence')
    need(text.endswith('\n'), 'truncated evidence line')
    return text


def object_row(text):
    try:
        row = json.loads(text, object_pairs_hook=unique_object)
    except ValueError as error:
        raise RuntimeError('malformed JSON evidence') from error
    need(type(row) is dict, 'evidence row must be an object')
    return row


def header(schedule):
    return {'event': 'header', 'schema': 1, 'schedule': schedule,
            'component_only': True, 'guest_fd_execution': False, 'cycle_limit': CYCLE_LIMIT,
            'cases_per_lane': 64, 'stream_requests': 8, 'request_fields': REQUEST_FIELDS, 'reply_fields': REPLY_FIELDS}


def check_interfaces(lane):
    keys(lane, ('input', 'output'), 'lane')
    i, o = lane['input'], lane['output']
    keys(i, (*INPUT_ARRAYS, *INPUT_SCALARS, 'commits', 'request'), 'input')
    keys(o, (*OUTPUT_ARRAYS, *OUTPUT_SCALARS, 'response'), 'output')
    for row, arrays, scalars in ((i, INPUT_ARRAYS, INPUT_SCALARS), (o, OUTPUT_ARRAYS, OUTPUT_SCALARS)):
        for key, widths in arrays.items():
            vector(row[key], widths, key)
        for key, width in scalars.items():
            need(unsigned(row[key], width), 'invalid raw scalar: ' + key)
    for row, key, count, widths in ((i, 'commits', 2, (1, 4, 64)),
                                     (i, 'request', 3, REQUEST_WIDTHS), (o, 'response', 3, REPLY_WIDTHS)):
        need(type(row[key]) is list and len(row[key]) == count, 'invalid raw matrix: ' + key)
        for value in row[key]:
            vector(value, widths, key)
    need(o['domain'] < 3, 'invalid memory domain')


def expected_lane(schedule, lane):
    # Frozen stimulus arithmetic, never learned from a model's reported totals.
    staggered = schedule == 'staggered'
    owners = 40 if lane == 0 else 32
    transfers = [40, 16, 16] if lane == 0 else [40, 0, 32]
    return {'name': ('guest', 'host')[lane], 'requests': transfers, 'responses': transfers.copy(),
            'starts': owners, 'completions': owners, 'retirements': owners,
            'request_stalls': 64 * (3 if staggered else 2),
            'response_stalls': 64 * (3 if staggered else 2),
            'response_delay': 64 * (3 if staggered else 1),
            'post_response_holds': owners * (5 if staggered else 3),
            'wrong_tag': owners * 2, 'wrong_index': owners * 2,
            'arithmetic_overlap': 0 if lane else 8, 'busy_masks': (1 << 32) - 1,
            'metadata_mask': 1 if lane else 255, 'status_mask': 15,
            'h_forms': 0 if lane else 8191, 'handles': 131071 if lane else 1,
            'sustained_requests': 8, 'sustained_turnovers': 7, 'drained': True}


def check_summary(row, schedule):
    keys(row, ('schema', 'component_only', 'guest_fd_execution', 'schedule', 'cycles',
               'idle_resets', 'lanes'), 'summary')
    need(type(row['schema']) is int and row['schema'] == 1 and row['component_only'] is True and
         row['guest_fd_execution'] is False, 'component-only evidence scope changed')
    need(row['schedule'] == schedule and unsigned(row['cycles']) and
         row['cycles'] == SCHEDULE_CYCLES[schedule] and
         type(row['idle_resets']) is int and row['idle_resets'] == 1, 'schedule totals changed')
    need(type(row['lanes']) is list and len(row['lanes']) == 2, 'two lane summaries required')
    for index, lane in enumerate(row['lanes']):
        expected = expected_lane(schedule, index)
        keys(lane, expected, 'lane summary')
        for key in LANE_COUNTERS:
            need(unsigned(lane[key]), 'invalid lane counter: ' + key)
        for key in ('requests', 'responses'):
            vector(lane[key], (64, 64, 64), key)
        need(lane['drained'] is True and lane == expected, 'directed lane coverage incomplete')


def check_trace(path, schedule, summary):
    lines = clean_text(path).splitlines()
    need(len(lines) == summary['cycles'] + 2, 'raw trace cycle count mismatch')
    first = object_row(lines[0])
    expected_header = header(schedule)
    keys(first, expected_header, 'trace header')
    need(first == expected_header and first['component_only'] is True and first['guest_fd_execution'] is False and
         all(type(first[key]) is int for key in ('schema', 'cycle_limit', 'cases_per_lane', 'stream_requests')),
         'raw trace header mismatch')
    totals = [{'requests': [0, 0, 0], 'responses': [0, 0, 0],
               **dict.fromkeys(LANE_COUNTERS, 0)} for _ in range(2)]
    pending, responded = [False, False], [False, False]
    for cycle, line in enumerate(lines[1:-1], 1):
        edge = object_row(line)
        keys(edge, ('event', 'cycle', 'reset', 'lanes'), 'cycle')
        need(edge['event'] == 'cycle' and type(edge['cycle']) is int and edge['cycle'] == cycle,
             'raw trace cycle gap or ordering mismatch')
        need(unsigned(edge['reset'], 1) and edge['reset'] == int(cycle <= 2),
             'only the initial idle reset is in scope')
        need(type(edge['lanes']) is list and len(edge['lanes']) == 2, 'missing raw lane observations')
        for index, lane in enumerate(edge['lanes']):
            check_interfaces(lane)
            if edge['reset']:
                continue
            i, o, counts = lane['input'], lane['output'], totals[index]
            domain = o['domain']
            request_fires = [a & b for a, b in zip(i['request_valid'], o['request_ready'])]
            response_fires = [a & b for a, b in zip(o['response_valid'], i['response_ready'])]
            request_fire = o['native_request_valid'] & i['native_request_ready']
            response_fire = i['native_response_valid'] & o['native_response_ready']
            need(sum(request_fires) == request_fire and sum(response_fires) == response_fire and
                 request_fires[domain] == request_fire and response_fires[domain] == response_fire,
                 'raw selected-client/native transfer mismatch')
            for port in range(3):
                counts['requests'][port] += request_fires[port]
                counts['responses'][port] += response_fires[port]
            counts['response_delay'] += int(pending[index] and not i['native_response_valid'])
            counts['post_response_holds'] += int(o['owner'][0] and responded[index] and not o['retired'])
            for valid, token_index, token_tag in i['commits']:
                if valid and o['owner'][0]:
                    counts['wrong_tag'] += int(token_index == o['owner'][1] and token_tag != o['owner'][2])
                    counts['wrong_index'] += int(token_tag == o['owner'][2] and token_index != o['owner'][1])
            if i['start'][0]:
                responded[index] = False
                if index == 0 and i['start'][3] in H_FORMS:
                    counts['h_forms'] |= 1 << H_FORMS.index(i['start'][3])
            if response_fire:
                pending[index] = False
                responded[index] = responded[index] or bool(o['owner'][0])
            if request_fire:
                pending[index] = True
            counts['starts'] += i['start'][0]
            counts['completions'] += i['complete'][0]
            counts['retirements'] += o['retired']
            counts['request_stalls'] += o['native_request_valid'] & (1 - i['native_request_ready'])
            counts['response_stalls'] += i['native_response_valid'] & (1 - o['native_response_ready'])
            counts['arithmetic_overlap'] += int(request_fire and o['owner'][0] and domain == 0)
            counts['busy_masks'] |= 1 << sum(bit << n for n, bit in enumerate(i['busy']))
            if request_fire:
                counts['handles'] |= 1 << o['native_request'][3]
            if response_fire:
                reply = o['response'][domain]
                counts['metadata_mask'] |= 1 << (reply[5] | (reply[6] << 1) | (reply[7] << 2))
                counts['status_mask'] |= 1 << (reply[3] | (reply[4] << 1))
            if 35 <= cycle <= 43:
                counts['sustained_requests'] += request_fire
                counts['sustained_turnovers'] += request_fire & response_fire
                need(domain == 0 and request_fire == int(cycle <= 42) and
                     response_fire == int(cycle >= 36), 'sustained stream has a transfer bubble')
            if cycle > summary['cycles'] - 2:
                need(not o['owner'][0] and not o['native_request_valid'] and
                     not i['native_response_valid'] and not o['busy'] and not pending[index],
                     'raw final state is not drained')
    for index, counts in enumerate(totals):
        for key, value in counts.items():
            need(value == summary['lanes'][index][key], 'raw trace/summary mismatch: ' + key)
    final = object_row(lines[-1])
    keys(final, ('event', 'summary'), 'trace footer')
    need(final['event'] == 'summary', 'missing raw trace summary')
    check_summary(final['summary'], schedule)
    need(final['summary'] == summary, 'raw trace/stdout summaries differ')


def check_positive(path, schedule, trace):
    text = clean_text(path)
    lines = text.splitlines()
    need(len(lines) == 1 and lines[0].startswith(MARKER + ' ') and
         'PASS' not in text and 'MEMORY_DOMAIN_SELECTOR_CHECK[' not in text,
         'expected exactly one component summary and no other output')
    summary = object_row(lines[0][len(MARKER) + 1:])
    check_summary(summary, schedule)
    check_trace(trace, schedule, summary)
    return summary


def check_negative(path, name, returncode):
    need(type(returncode) is int and returncode == 1, 'negative must exit exactly one')
    lane, cycle = NEGATIVE_LOCATIONS[name]
    need(clean_text(path) == f'MEMORY_DOMAIN_SELECTOR_CHECK[{name}]: lane={lane} cycle={cycle}\n',
         'negative missed its exact named checker')


def native_run(output, arguments, log_name, env):
    path = output / log_name
    with path.open('x') as log:
        result = subprocess.run([str(output / 'run'), *arguments], cwd=common.ROOT,
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=TIMEOUT)
    return path, result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=common.BUILD / 'memory-domain-selector')
    args = parser.parse_args()
    # Reject even an empty directory or dangling symlink. No model/class reuse.
    need(not args.output.exists() and not args.output.is_symlink(), 'fresh output directory required')
    output = args.output.resolve()
    gsim, cxx = common.setup(False)
    os.environ['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    first_trace = output / 'raw-baseline.jsonl'
    built = common.test(gsim, cxx, str(output), 'ooo.MemoryDomainSelectorGsimMain',
                        'MemoryDomainSelectorGsim', 'memory_domain_selector.cpp',
                        runtime_args=('--schedule', 'baseline', '--trace', str(first_trace)),
                        sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=TIMEOUT,
                        mill_module='IonSoC.memoryDomainSelector')
    need(built == output, 'generated model destination changed')
    summaries = [check_positive(output / 'test.log', 'baseline', first_trace)]
    second_trace = output / 'raw-staggered.jsonl'
    log, code = native_run(output, ('--schedule', 'staggered', '--trace', str(second_trace)),
                           'staggered.log', env)
    need(code == 0, 'staggered execution failed')
    summaries.append(check_positive(log, 'staggered', second_trace))
    for name in NEGATIVES:
        log, code = native_run(output, ('--schedule', 'baseline', '--negative', name),
                               'negative-' + name + '.log', env)
        check_negative(log, name, code)
    receipt = {'schema': 1, 'component_only': True, 'guest_fd_execution': False,
               'schedules': summaries, 'negatives': list(NEGATIVES)}
    with (output / 'entry-summary.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(STANDARD_MARKER)


if __name__ == '__main__':
    main()
