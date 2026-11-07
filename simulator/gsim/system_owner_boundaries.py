#!/usr/bin/env python3
"""Accepted-event owner/selector boundary probes, not an executing H+FP CPU."""
import argparse
import json
import os
from pathlib import Path
import subprocess

import run as common


MARKER = 'SYSTEM_OWNER_BOUNDARIES_SUMMARY'
STANDARD_MARKER = 'SYSTEM_OWNER_BOUNDARIES_STANDARD_PASS'
TIMEOUT = 120
TRACE_LIMIT = 1024 * 1024
CYCLE_LIMIT = 256
SCHEDULES = ('baseline', 'staggered')
SCHEDULE_CYCLES = {'baseline': 88, 'staggered': 136}
REQUEST_FIELDS = ['address', 'data', 'epoch', 'size', 'mask', 'op', 'write',
                  'atomic', 'virtualized', 'prechecked', 'hint', 'uncached']
REPLY_FIELDS = ['data', 'error', 'page']
REQUEST_WIDTHS = (64, 64, 32, 2, 8, 5, 1, 1, 1, 1, 1, 1)
REPLY_WIDTHS = (64, 1, 1)
OWNER_WIDTHS = (1, 4, 64, 1, 1, 1)
INPUT_ARRAYS = {'start': (1, 4, 64, 32), 'complete': (1, 4, 64, 1),
                'request_valid': (1, 1, 1), 'response_ready': (1, 1, 1),
                'native_response': REPLY_WIDTHS, 'busy': (1, 1, 1, 1, 1)}
INPUT_SCALARS = {'native_request_ready': 1, 'native_response_valid': 1}
OUTPUT_ARRAYS = {'owner': OWNER_WIDTHS, 'request_ready': (1, 1, 1),
                 'response_valid': (1, 1, 1), 'native_request': REQUEST_WIDTHS}
OUTPUT_SCALARS = {'domain': 2, 'retired': 1, 'retire_matches': 2, 'busy': 1,
                  'cpu_busy': 1, 'native_request_valid': 1, 'native_response_ready': 1}
# Independent fixed H 1.0 HLV.B and RV64 FLD encodings, not DUT decoder outputs.
H_WORD, FP_WORD = 0x6004c3f3, 0x0004b387
DOMAINS = (1, 2, 1, 2, 1, 1, 2, 1)
TOKENS = tuple((index + 1, 0x8000000100000055 + (index << 32)) for index in range(8))
EXCEPTIONAL = frozenset((0, 1, 5, 6))
NEGATIVE_LOCATIONS = {'exception_release': 18, 'retire_capture': 37, 'exception_capture': 70,
                      'inactive_match': 3, 'high_tag': 6, 'index_match': 7,
                      'valid_qualification': 5, 'epoch_clear': 18, 'domain_switch': 37}
NEGATIVES = tuple(NEGATIVE_LOCATIONS)


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def unsigned(value, width=64):
    return type(value) is int and 0 <= value < (1 << width)


def keys(row, expected, label):
    need(type(row) is dict and set(row) == set(expected), 'missing or unexpected ' + label + ' field')


def vector(value, widths, label):
    need(type(value) is list and len(value) == len(widths) and
         all(unsigned(item, width) for item, width in zip(value, widths)), 'invalid raw ' + label)


def unique_object(pairs):
    value = dict(pairs)
    need(len(value) == len(pairs), 'duplicate evidence field')
    return value


def object_row(text):
    try:
        row = json.loads(text, object_pairs_hook=unique_object)
    except ValueError as error:
        raise RuntimeError('malformed JSON evidence') from error
    need(type(row) is dict, 'evidence row must be an object')
    return row


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


def header(schedule):
    return {'event': 'header', 'schema': 1, 'schedule': schedule, 'component_only': True,
            'guest_fd_execution': False, 'cycle_limit': CYCLE_LIMIT, 'owners': 8,
            'request_fields': REQUEST_FIELDS, 'reply_fields': REPLY_FIELDS}


def plan(schedule):
    """Frozen accepted-event recipe; repeated phase names are intentional holds."""
    s, d, r, h = (1, 1, 1, 1) if schedule == 'baseline' else (2, 3, 2, 3)
    phases = ['reset', 'reset'] + ['probe_reset_' + str(n) for n in range(6)]
    for index, name in enumerate('ABCDEFGH'):
        if name in 'ABCF':
            phases.append('start_' + name)
        phases += ['request_stall_' + name] * s + ['request_' + name] + ['delay_' + name] * d
        phases += ['response_stall_' + name] * r + ['response_' + name, 'drain_' + name]
        if index not in EXCEPTIONAL:
            phases.append('complete_' + name)
        phases += ['hold_' + name] * h
        phase = ('release' if name in 'AB' else 'retire_capture' if name in 'CD' else
                 'exception_capture' if name in 'FG' else 'retire')
        phases.append(phase + '_' + name)
        if name == 'E':
            phases += ['probe_retained_' + str(n) for n in range(6)]
    return phases + ['final', 'final']


def probe_commits(token, number):
    index, tag = token
    quiet = [[0, 0, 0], [0, 0, 0]]
    if number < 2:
        quiet[number] = [1, index, tag]
    elif number == 2:
        quiet = [[0, index, tag], [0, index, tag]]
    elif number == 3:
        quiet[0] = [1, index, tag ^ (1 << 63)]
    elif number == 4:
        quiet[1] = [1, index ^ 1, tag]
    return quiet


def controls(phase):
    """Expected event qualifiers and full tokens, independent of raw summaries."""
    start, complete, commits = None, None, [[0, 0, 0], [0, 0, 0]]
    if phase.startswith('probe_'):
        token = (0, 0) if phase.startswith('probe_reset_') else TOKENS[4]
        commits = probe_commits(token, int(phase[-1]))
    elif phase not in ('reset', 'final'):
        index = ord(phase[-1]) - ord('A')
        token = TOKENS[index]
        if phase.startswith('start_'):
            start = index
        if phase.startswith('complete_'):
            complete = [1, *token, 0]
        if phase.startswith(('release_', 'exception_capture_')):
            complete = [1, *token, 1]
        if phase.startswith('retire_'):
            commits[int(index in (3, 7))] = [1, *token]
        if phase.startswith(('retire_capture_', 'exception_capture_')):
            start = index + 1
        if phase.startswith('hold_'):
            commits = [[1, token[0], token[1] ^ (1 << 63)], [1, token[0] ^ 1, token[1]]]
    return start, complete, commits


def check_interfaces(edge):
    i, o = edge['input'], edge['output']
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
    if edge['post'] is not None:
        keys(edge['post'], ('owner', 'domain'), 'post')
        vector(edge['post']['owner'], OWNER_WIDTHS, 'post owner')
        need(unsigned(edge['post']['domain'], 2) and edge['post']['domain'] < 3, 'invalid post domain')


def expected_summary(schedule):
    staggered = schedule == 'staggered'
    return {'schema': 1, 'component_only': True, 'guest_fd_execution': False,
            'schedule': schedule, 'cycles': SCHEDULE_CYCLES[schedule], 'idle_resets': 1,
            'requests': [0, 5, 3], 'responses': [0, 5, 3], 'starts': 8,
            'successful_completions': 4, 'exceptional_completions': 4, 'active_retirements': 4,
            'retire_capture': 2, 'exception_capture': 2, 'inactive_matches': 4, 'retired_pulses': 8,
            'request_stalls': 16 if staggered else 8, 'response_stalls': 16 if staggered else 8,
            'response_delay': 24 if staggered else 8, 'drain_cycles': 8,
            'hold_cycles': 24 if staggered else 8, 'wrong_tag': 26 if staggered else 10,
            'wrong_index': 26 if staggered else 10, 'invalid_matches': 2, 'drained': True}


def check_summary(row, schedule):
    expected = expected_summary(schedule)
    keys(row, expected, 'summary')
    for key, value in expected.items():
        if type(value) is int:
            need(unsigned(row[key]), 'invalid summary integer: ' + key)
        elif type(value) is bool:
            need(row[key] is value, 'component scope or drained state changed')
        elif type(value) is list:
            vector(row[key], (64, 64, 64), key)
    need(row == expected, 'directed boundary coverage incomplete')


def check_trace(path, schedule, summary):
    lines = clean_text(path).splitlines()
    phases = plan(schedule)
    need(len(lines) == summary['cycles'] + 2 and len(phases) == summary['cycles'],
         'raw trace cycle count mismatch')
    first = object_row(lines[0])
    expected_header = header(schedule)
    keys(first, expected_header, 'trace header')
    need(first == expected_header and first['component_only'] is True and first['guest_fd_execution'] is False and
         all(type(first[key]) is int for key in ('schema', 'cycle_limit', 'owners')), 'raw trace header mismatch')
    rows = [object_row(line) for line in lines[1:-1]]
    count_keys = tuple(key for key in summary if key not in
                       ('schema', 'component_only', 'guest_fd_execution', 'schedule', 'cycles',
                        'idle_resets', 'requests', 'responses', 'drained'))
    totals = {**dict.fromkeys(count_keys, 0), 'requests': [0, 0, 0], 'responses': [0, 0, 0]}
    owner, domain = [0, 0, 0, 0, 0, 0], 0
    pending = None
    current = None
    completed, responded, drained = set(), set(), set()
    retired_owners, exception_owners = set(), set()
    held_request = held_response = None
    for number, (edge, phase) in enumerate(zip(rows, phases), 1):
        keys(edge, ('event', 'cycle', 'reset', 'phase', 'input', 'output', 'post'), 'cycle')
        need(edge['event'] == 'cycle' and type(edge['cycle']) is int and edge['cycle'] == number,
             'raw trace cycle gap or ordering mismatch')
        need(edge['phase'] == phase, 'frozen boundary phase changed')
        need(unsigned(edge['reset'], 1) and edge['reset'] == int(number <= 2),
             'only the initial inactive reset is in scope')
        check_interfaces(edge)
        i, o = edge['input'], edge['output']
        need(o['owner'] == owner and o['domain'] == domain, 'raw owner transition or domain mismatch')
        start, complete, commits = controls(phase)
        need(i['start'][0] == int(start is not None), 'accepted start phase changed')
        if start is not None:
            word = H_WORD if DOMAINS[start] == 1 else FP_WORD
            need(i['start'] == [1, *TOKENS[start], word], 'accepted start token or instruction changed')
        need(i['complete'][0] == int(complete is not None), 'accepted completion phase changed')
        if complete is not None:
            need(i['complete'] == complete, 'accepted completion token or exception changed')
        need(i['commits'] == commits, 'frozen full-token commit probe changed')
        if complete is None:
            need(i['complete'][3] == 1, 'invalid exceptional completion probe missing')
        for valid, index, tag in i['commits']:
            need(not valid or (index, tag) not in (TOKENS[n] for n in EXCEPTIONAL),
                 'an exceptional token must never be committed')
        matches = [int(valid and [index, tag] == owner[1:3]) for valid, index, tag in i['commits']]
        mask = sum(bit << lane for lane, bit in enumerate(matches))
        need(sum(matches) <= 1 and o['retire_matches'] == mask and o['retired'] == int(bool(mask)),
             'raw valid/full-token retirement match mismatch')
        totals['retired_pulses'] += int(bool(mask))
        totals['inactive_matches'] += int(bool(mask) and not owner[0])
        totals['wrong_tag'] += sum(int(valid and index == owner[1] and tag != owner[2])
                                   for valid, index, tag in i['commits'])
        totals['wrong_index'] += sum(int(valid and index != owner[1] and tag == owner[2])
                                     for valid, index, tag in i['commits'])
        totals['invalid_matches'] += int(phase.startswith('probe_') and
                                         any(not valid and [index, tag] == owner[1:3]
                                             for valid, index, tag in i['commits']) and phase.endswith('_2'))
        request_phase = phase.startswith(('request_', 'request_stall_'))
        response_phase = phase.startswith(('response_', 'response_stall_'))
        expected_requests = [int(request_phase and port == domain) for port in range(3)]
        need(i['request_valid'] == expected_requests and i['native_response_valid'] == int(response_phase),
             'native traffic escaped its frozen phase')
        need(i['native_request_ready'] == int(not phase.startswith('request_stall_')) and
             i['response_ready'] == [int(not (phase.startswith('response_stall_') and port == domain))
                                     for port in range(3)], 'native service schedule changed')
        need(o['native_request_valid'] == i['request_valid'][domain] and
             o['request_ready'] == [int(port == domain) * i['native_request_ready'] for port in range(3)] and
             o['response_valid'] == [int(port == domain) * i['native_response_valid'] for port in range(3)] and
             o['native_response_ready'] == i['response_ready'][domain], 'raw selected-client handshake mismatch')
        need(o['native_request'] == i['request'][domain] and
             all(reply == i['native_response'] for reply in o['response']), 'raw native payload routing mismatch')
        busy_phase = phase.startswith(('delay_', 'response_', 'response_stall_'))
        need(i['busy'] == [int(busy_phase and port == domain) for port in range(5)],
             'memory busy phase changed')
        need(o['busy'] == int(any(i['busy'])) and o['cpu_busy'] == int(any(i['busy'][:4])),
             'raw memory busy aggregation mismatch')
        need(not owner[0] or not i['busy'][0], 'integer busy overlaps a protected owner')
        request_fire = o['native_request_valid'] & i['native_request_ready']
        response_fire = i['native_response_valid'] & o['native_response_ready']
        request_packet = (domain, tuple(o['native_request']))
        response_packet = (domain, tuple(i['native_response']))
        if held_request is not None:
            need(o['native_request_valid'] and request_packet == held_request, 'held request payload changed')
        if held_response is not None:
            need(i['native_response_valid'] and response_packet == held_response, 'held response payload changed')
        held_request = request_packet if o['native_request_valid'] and not i['native_request_ready'] else None
        held_response = response_packet if i['native_response_valid'] and not o['native_response_ready'] else None
        totals['request_stalls'] += int(held_request is not None)
        totals['response_stalls'] += int(held_response is not None)
        totals['response_delay'] += int(pending is not None and not i['native_response_valid'])
        if request_fire:
            need(owner[0] and pending is None and current not in responded, 'native request ownership mismatch')
            pending = current
            totals['requests'][domain] += 1
        if response_fire:
            need(owner[0] and pending == current and current not in responded, 'native response lacks its request')
            need(i['native_response'][1:] == [int(current in EXCEPTIONAL), 0], 'synthetic response scope changed')
            pending = None
            responded.add(current)
            totals['responses'][domain] += 1
        boundary = start is not None or complete is not None or (mask and owner[0])
        quiet = pending is None and not any(i['request_valid']) and not i['native_response_valid'] and not any(i['busy'])
        if boundary or phase.startswith('drain_'):
            need(quiet, 'boundary requires drained quiet native memory')
        if phase.startswith('drain_'):
            need(current in responded and current not in drained, 'quiet drain lacks an accepted response')
            drained.add(current)
            totals['drain_cycles'] += 1
        if phase.startswith('hold_'):
            need(owner[0] and current in drained, 'post-drain hold lost its owner')
            totals['hold_cycles'] += 1
        if complete is not None:
            need(owner[0] and owner[1:3] == i['complete'][1:3] and current in drained and current not in completed,
                 'completion lacks its active full-token owner and prior native drain')
            completed.add(current)
            totals['exceptional_completions' if complete[3] else 'successful_completions'] += 1
            if complete[3]:
                exception_owners.add(current)
        if mask and owner[0]:
            need(current in completed and current not in EXCEPTIONAL and current not in retired_owners,
                 'active retirement lacks one successful completion')
            retired_owners.add(current)
            totals['active_retirements'] += 1
        totals['retire_capture'] += int(start is not None and bool(mask) and bool(owner[0]))
        totals['exception_capture'] += int(start is not None and complete is not None and bool(complete[3]))
        next_owner, next_domain = owner.copy(), domain
        if edge['reset']:
            need(not owner[0] and pending is None, 'reset with live ownership is outside scope')
            next_owner, next_domain = [0, 0, 0, 0, 0, 0], 0
        elif mask or (complete is not None and complete[3]):
            next_owner = [0, *owner[1:3], 0, 0, 0]
            next_domain = 0
        if start is not None:
            need(not owner[0] or mask or (complete is not None and complete[3]), 'capture overwrote a live owner')
            current = start
            totals['starts'] += 1
            next_domain = DOMAINS[start]
            next_owner = [1, *TOKENS[start], 1, int(next_domain == 1), int(next_domain == 2)]
        if number < len(rows):
            expected_post = {'owner': next_owner, 'domain': next_domain}
            need(edge['post'] == expected_post, 'raw post-edge owner or domain mismatch')
            next_output = rows[number].get('output')
            need(type(next_output) is dict and edge['post'] ==
                 {'owner': next_output.get('owner'), 'domain': next_output.get('domain')},
                 'post state was not linked to the next observed output')
        else:
            need(edge['post'] is None, 'final row must not invent an unobserved post state')
        if phase == 'final':
            need(not owner[0] and domain == 0 and quiet and not o['busy'], 'raw final state is not drained')
        owner, domain = next_owner, next_domain
    need(completed == set(range(8)) and retired_owners == {2, 3, 4, 7} and exception_owners == EXCEPTIONAL,
         'owner completion/release ledger incomplete')
    for key, value in totals.items():
        need(value == summary[key], 'raw trace/summary mismatch: ' + key)
    final = object_row(lines[-1])
    keys(final, ('event', 'summary'), 'trace footer')
    need(final['event'] == 'summary', 'missing raw trace summary')
    check_summary(final['summary'], schedule)
    need(final['summary'] == summary, 'raw trace/stdout summaries differ')


def check_positive(path, schedule, trace):
    text = clean_text(path)
    lines = text.splitlines()
    need(len(lines) == 1 and lines[0].startswith(MARKER + ' ') and 'PASS' not in text,
         'expected exactly one component summary and no other output')
    summary = object_row(lines[0][len(MARKER) + 1:])
    check_summary(summary, schedule)
    check_trace(trace, schedule, summary)
    return summary


def check_negative(path, name, returncode):
    need(type(returncode) is int and returncode == 1, 'negative must exit exactly one')
    need(clean_text(path) == f'SYSTEM_OWNER_BOUNDARIES_CHECK[{name}]: cycle={NEGATIVE_LOCATIONS[name]}\n',
         'negative missed its exact named checker')


def native_run(output, arguments, log_name, env):
    path = output / log_name
    with path.open('x') as log:
        result = subprocess.run([str(output / 'run'), *arguments], cwd=common.ROOT,
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=TIMEOUT)
    return path, result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=common.BUILD / 'system-owner-boundaries')
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink(), 'fresh output directory required')
    output = args.output.resolve()
    gsim, cxx = common.setup(False)
    os.environ['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    first_trace = output / 'raw-baseline.jsonl'
    built = common.test(gsim, cxx, str(output), 'ooo.SystemOwnerBoundariesGsimMain',
                        'SystemOwnerBoundariesGsim', 'system_owner_boundaries.cpp',
                        runtime_args=('--schedule', 'baseline', '--trace', str(first_trace)),
                        sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=TIMEOUT,
                        mill_module='IonSoC.systemOwnerBoundaries')
    need(built == output, 'generated model destination changed')
    summaries = [check_positive(output / 'test.log', 'baseline', first_trace)]
    second_trace = output / 'raw-staggered.jsonl'
    log, code = native_run(output, ('--schedule', 'staggered', '--trace', str(second_trace)),
                           'staggered.log', env)
    need(type(code) is int and code == 0, 'staggered execution failed')
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
