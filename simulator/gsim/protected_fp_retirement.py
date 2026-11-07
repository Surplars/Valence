#!/usr/bin/env python3
"""Bounded protected FP retirement component evidence; actual H+FP stays disabled."""
import argparse
import json
import os
from pathlib import Path
import subprocess

import run as common

MARKER = 'PROTECTED_FP_RETIREMENT_SUMMARY'
STANDARD_MARKER = 'PROTECTED_FP_RETIREMENT_STANDARD_PASS'
TIMEOUT = 120
TRACE_LIMIT = 1024 * 1024
CYCLE_LIMIT = 512
SCHEDULES = ('baseline', 'staggered')

def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def unsigned(value, width=64):
    return type(value) is int and 0 <= value < (1 << width)


def keys(row, expected, label):
    need(type(row) is dict and set(row) == set(expected), 'missing or unexpected ' + label + ' field')


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



COMMAND_WIDTHS = {'token_index': 4, 'token_tag': 64, 'instruction': 32,
                  **{f'sources_{n}': 5 for n in range(3)},
                  **{f'checkSingleBox_{n}': 1 for n in range(3)},
                  'integerSource': 64, 'destination': 5, 'singleResult': 1,
                  'writesFp': 1, 'writesFlags': 1, 'usesRounding': 1, 'rounding': 3}
RESULT_WIDTHS = {'token_index': 4, 'token_tag': 64, 'value': 64, 'flags': 5,
                 'exception': 1, 'cause': 6, 'tval': 64,
                 'guestFault_guestPageFault': 1, 'guestFault_guestAddress': 1,
                 'guestFault_guestPhysicalAddress': 64, 'guestFault_implicitPte': 1}

def prefixed(prefix, fields):
    return {prefix + key: value for key, value in fields.items()}

INPUT_WIDTHS = {'issue_valid': 1, 'execute_ready': 1, 'result_valid': 1,
                'completeAccept': 1, 'csr_valid': 1, 'csr_bits_address': 12,
                'csr_bits_operation': 2, 'csr_bits_write': 1, 'csr_bits_value': 64,
                'status_valid': 1, 'status_bits_address': 12, 'status_bits_data': 64,
                'statusReadAddress': 12, 'mret': 1, 'sret': 1,
                **prefixed('issue_bits_', COMMAND_WIDTHS), **prefixed('result_bits_', RESULT_WIDTHS)}
for _lane in range(2):
    INPUT_WIDTHS.update({f'commit{_lane}_valid': 1, f'commit{_lane}_bits_index': 4,
                         f'commit{_lane}_bits_tag': 64})
STATE_WIDTHS = {'ownerActive': 1, 'ownerToken_index': 4, 'ownerToken_tag': 64,
                'contextMemoryEpoch': 1, 'hMemoryEpoch': 1, 'fpMemoryEpoch': 1,
                'completionSeen': 1, 'statePhase': 2, 'busy': 1, 'virtualized': 1,
                'hostFs': 2, 'hostSd': 1, 'guestFs': 2, 'guestSd': 1, 'fcsr': 8,
                **{f'fpr_{n}': 64 for n in range(32)}}
OUTPUT_WIDTHS = {**STATE_WIDTHS, 'issue_ready': 1, 'issueAccepted': 1, 'execute_valid': 1,
                 'result_ready': 1, 'complete_valid': 1, 'completionAccepted': 1,
                 'retired': 1, 'retireMatches': 2, 'retireAccepted': 1,
                 'mutation_valid': 1, 'mutation_bits_guest': 1,
                 'csr_ready': 1, 'csrRead': 64, 'csrIllegal': 1,
                 'status_ready': 1, 'statusReadData': 64, 'statusShadow': 1,
                 **prefixed('execute_bits_command_', COMMAND_WIDTHS),
                 **{f'execute_bits_operands_{n}': 64 for n in range(3)},
                 'execute_bits_rounding': 3, **prefixed('complete_bits_', RESULT_WIDTHS)}


def scalar_map(row, widths, label):
    keys(row, widths, label)
    for key, width in widths.items():
        need(unsigned(row[key], width), 'invalid raw ' + label + '.' + key)


class Replay:
    """Input-only transition ledger. Observations never feed expected state."""
    def __init__(self):
        self.state = dict.fromkeys(STATE_WIDTHS, 0)
        self.command = None
        self.response = None
        self.guest = 0
        self.operands = [0, 0, 0]
        self.rounding = 0
        self.spv = 0
        self.counts = dict.fromkeys(('issued', 'completion_accepts', 'owner_retired_pulses',
            'successful_active_owner_retirements', 'inactive_owner_pulses', 'fp_retire_accepted',
            'successful_fp_retirements', 'fp_architectural_mutations', 'fpr_writes',
            'fflags_updates', 'host_dirty_events', 'guest_dirty_events'), 0)

    def observe(self, i):
        s = self.state
        o = s.copy()
        idle = s['statePhase'] == 0
        csr_valid = i['csr_valid'] and not i['status_valid']
        ready = int(idle and not i['status_valid'] and not i['csr_valid'])
        mask = sum(int(i[f'commit{n}_valid'] and
            i[f'commit{n}_bits_index'] == s['ownerToken_index'] and
            i[f'commit{n}_bits_tag'] == s['ownerToken_tag']) << n for n in range(2))
        complete = int(s['statePhase'] == 3)
        retire = int(complete and bool(mask) and self.command is not None and
            self.command['token_index'] == s['ownerToken_index'] and
            self.command['token_tag'] == s['ownerToken_tag'])
        csr_ready = int(idle and not i['status_valid'])
        allowed = bool(s['hostFs'] and (not s['virtualized'] or s['guestFs']))
        illegal = int(i['csr_bits_address'] not in (1, 2, 3) or not allowed or i['csr_bits_operation'] == 3)
        csr_mutation = int(csr_valid and csr_ready and i['csr_bits_write'] and not illegal)
        mutation = int(csr_mutation or retire and (self.command['writesFp'] or self.command['writesFlags']))
        o.update(issue_ready=ready, issueAccepted=ready * i['issue_valid'],
            execute_valid=int(s['statePhase'] == 1), result_ready=1, complete_valid=complete,
            completionAccepted=int(complete and i['completeAccept'] and not s['completionSeen']),
            retired=int(bool(mask)), retireMatches=mask, retireAccepted=retire,
            mutation_valid=mutation, mutation_bits_guest=s['virtualized'] if csr_mutation else self.guest,
            csr_ready=csr_ready, csrIllegal=illegal, status_ready=int(idle),
            csrRead={1: s['fcsr'] & 31, 2: s['fcsr'] >> 5, 3: s['fcsr']}.get(i['csr_bits_address'], 0))
        address = i['statusReadAddress']
        shadow = int(s['virtualized'] and address == 0x100)
        fs = s['hostFs'] if address == 0x300 or address == 0x100 and not shadow else s['guestFs']
        status = (fs << 13) | (int(fs == 3) << 63)
        o['statusShadow'] = shadow
        o['statusReadData'] = status if address == 0x300 or address == 0x100 and not shadow else ((2 << 32) | status if address == 0x200 or shadow else 0)
        if self.command is None and not csr_mutation:
            del o['mutation_bits_guest']
        if self.command is not None:
            o.update(prefixed('execute_bits_command_', self.command))
            o.update({f'execute_bits_operands_{n}': value for n, value in enumerate(self.operands)})
            o['execute_bits_rounding'] = self.rounding
        if self.response is not None:
            o.update(prefixed('complete_bits_', self.response))
        return o

    def step(self, i):
        o = self.observe(i)
        s, count = self.state, self.counts
        if i['status_valid'] or i['csr_valid'] or i['mret'] or i['sret']:
            need(not s['busy'] and not s['ownerActive'], 'context replacement with live owner')
        if i['status_valid']:
            address, data = i['status_bits_address'], i['status_bits_data']
            if address == 0x300 or address == 0x100 and not s['virtualized']:
                s['hostFs'] = (data >> 13) & 3
            if address == 0x200 or address == 0x100 and s['virtualized']:
                s['guestFs'] = (data >> 13) & 3
            if address == 0x600:
                self.spv = (data >> 7) & 1
        if i['sret']:
            s['virtualized'], self.spv = self.spv, 0
        need(not i['mret'], 'M-origin outside scope')
        if i['csr_valid'] and o['csr_ready'] and i['csr_bits_write'] and not o['csrIllegal']:
            value, op, address = i['csr_bits_value'], i['csr_bits_operation'], i['csr_bits_address']
            value = value if op == 0 else o['csrRead'] | value if op == 1 else o['csrRead'] & ~value
            if address == 1: s['fcsr'] = (s['fcsr'] & 224) | (value & 31)
            elif address == 2: s['fcsr'] = ((value & 7) << 5) | (s['fcsr'] & 31)
            else: s['fcsr'] = value & 255
        if o['completionAccepted']:
            need(s['ownerActive'] and self.response['token_index'] == s['ownerToken_index'] and
                 self.response['token_tag'] == s['ownerToken_tag'], 'accepted completion owner mismatch')
            s['completionSeen'] = 1
            count['completion_accepts'] += 1
        if o['retired']:
            count['owner_retired_pulses'] += 1
            count['successful_active_owner_retirements' if s['ownerActive'] else 'inactive_owner_pulses'] += 1
            s['ownerActive'] = 0
        if o['retireAccepted']:
            need(s['completionSeen'], 'retirement before downstream completion acceptance')
            count['fp_retire_accepted'] += 1
            count['successful_fp_retirements'] += 1
            s['statePhase'] = 0
            if self.command['writesFp']:
                value = self.response['value']
                if self.command['singleResult']: value = 0xffffffff00000000 | (value & 0xffffffff)
                s[f"fpr_{self.command['destination']}"] = value
                count['fpr_writes'] += 1
            if self.command['writesFlags']:
                s['fcsr'] |= self.response['flags']
                count['fflags_updates'] += 1
        if o['mutation_valid']:
            s['hostFs'] = 3
            if o['mutation_bits_guest']: s['guestFs'] = 3
            if o['retireAccepted']:
                count['fp_architectural_mutations'] += 1
                count['host_dirty_events'] += 1
                count['guest_dirty_events'] += o['mutation_bits_guest']
        if i['result_valid'] and o['statePhase'] == 2:
            result = {key: i['result_bits_' + key] for key in RESULT_WIDTHS}
            if all(result[key] == self.command[key] for key in ('token_index', 'token_tag')):
                need(not result['exception'], 'fault outside scope')
                self.response = result
                s['statePhase'] = 3
        if o['execute_valid'] and i['execute_ready']: s['statePhase'] = 2
        if o['issueAccepted']:
            need(not o['ownerActive'], 'issue overwrote owner')
            self.command = {key: i['issue_bits_' + key] for key in COMMAND_WIDTHS}
            self.guest = s['virtualized']
            need(s['hostFs'] and (not self.guest or s['guestFs']), 'illegal FP permission')
            self.operands = []
            for n in range(3):
                value = s[f"fpr_{self.command[f'sources_{n}']}"]
                if self.command[f'checkSingleBox_{n}'] and value >> 32 != 0xffffffff: value = 0xffffffff7fc00000
                self.operands.append(value)
            self.rounding = s['fcsr'] >> 5 if self.command['rounding'] == 7 else self.command['rounding']
            need(not self.command['usesRounding'] or self.rounding <= 4, 'illegal rounding')
            self.response = dict.fromkeys(RESULT_WIDTHS, 0)
            for key in ('token_index', 'token_tag'): self.response[key] = self.command[key]
            s.update(statePhase=1, completionSeen=0, ownerActive=1,
                     ownerToken_index=self.command['token_index'], ownerToken_tag=self.command['token_tag'])
            count['issued'] += 1
        s['busy'] = int(s['statePhase'] != 0)
        s['hostSd'], s['guestSd'] = int(s['hostFs'] == 3), int(s['guestFs'] == 3)
        return o

POST_WIDTHS = {key: width for key, width in STATE_WIDTHS.items()
               if key not in ('busy', 'contextMemoryEpoch', 'hMemoryEpoch', 'fpMemoryEpoch')}
NEGATIVE_PHASES = {'inactive_retire_accepted': 'cold_lane0', 'full_token': 'op0_hold_execute_0',
                   'premature_fpr': 'op0_hold_execute_0', 'fflags_loss': 'op0_retire',
                   'guest_dirty': 'op1_retire', 'duplicate_retire': 'op0_repeat0',
                   'refill_credit': 'op2_retire'}
NEGATIVES = tuple(NEGATIVE_PHASES)


def defaults():
    return {**dict.fromkeys(INPUT_WIDTHS, 0), 'execute_ready': 1,
            'csr_bits_address': 3, 'statusReadAddress': 0x100}


def recipe():
    words = (0x02007053, 0x000072d3, 0xc2007353, 0xe20293d3)
    tags = (0x1456000000000001, 0x2456000000000002, 0x3456000000000003, 0xb456000000000003)
    values = (0x400921fb54442d18, 0x123456783f400000, 0x1234, 0x80)
    result = []
    for n in range(4):
        i = defaults()
        i.update(issue_valid=1, issue_bits_token_index=3 if n == 3 else n + 1,
            issue_bits_token_tag=tags[n], issue_bits_instruction=words[n],
            issue_bits_destination=0 if n == 0 else n + 4, issue_bits_sources_0=5 if n == 3 else 0, issue_bits_sources_2=words[n] >> 27,
            issue_bits_singleResult=int(n == 1), issue_bits_writesFp=int(n < 2),
            issue_bits_writesFlags=int(n < 3), issue_bits_usesRounding=int(n < 3),
            issue_bits_rounding=7 if n < 3 else 1,
            issue_bits_checkSingleBox_0=int(n == 1), issue_bits_checkSingleBox_1=int(n == 1),
            issue_bits_checkSingleBox_2=int(n == 1),
            result_bits_token_index=3 if n == 3 else n + 1, result_bits_token_tag=tags[n],
            result_bits_value=values[n], result_bits_flags=1 << (n + 1))
        result.append(i)
    return result


def plan(schedule):
    need(schedule in SCHEDULES, 'unknown schedule')
    execute_hold, completed_hold = (1, 2) if schedule == 'baseline' else (3, 5)
    rows = []
    def add(phase, **updates):
        rows.append((phase, {**defaults(), **updates}))
    def grant(command, lane, valid=1, wrong_tag=False, wrong_index=False):
        return {f'commit{lane}_valid': valid,
                f'commit{lane}_bits_index': command['issue_bits_token_index'] ^ int(wrong_index),
                f'commit{lane}_bits_tag': command['issue_bits_token_tag'] ^ ((1 << 63) if wrong_tag else 0)}
    cold = defaults()
    add('cold_lane0', **grant(cold, 0))
    add('cold_lane1', **grant(cold, 1))
    add('cold_invalid', **grant(cold, 0, valid=0))
    add('cold_tag', **grant(cold, 0, wrong_tag=True))
    add('cold_index', **grant(cold, 1, wrong_index=True))
    add('setup_host', status_valid=1, status_bits_address=0x300, status_bits_data=2 << 13)
    add('setup_fcsr', csr_valid=1, csr_bits_write=1, csr_bits_value=97)
    add('clean_host', status_valid=1, status_bits_address=0x300, status_bits_data=2 << 13)
    add('setup_guest', status_valid=1, status_bits_address=0x200, status_bits_data=2 << 13)
    commands = recipe()
    for n, command in enumerate(commands):
        if n == 1:
            add('guest_host_clean', status_valid=1, status_bits_address=0x300, status_bits_data=2 << 13)
            add('guest_vs_clean', status_valid=1, status_bits_address=0x200, status_bits_data=2 << 13)
            add('guest_spv', status_valid=1, status_bits_address=0x600, status_bits_data=1 << 7)
            add('guest_enter', sret=1)
        if n == 2:
            add('flags_host_clean', status_valid=1, status_bits_address=0x300, status_bits_data=2 << 13)
            add('flags_vs_clean', status_valid=1, status_bits_address=0x200, status_bits_data=2 << 13)
        prefix = f'op{n}_'
        issue = command.copy()
        add(prefix + 'issue', **{**issue, **(grant(commands[2], 1) if n == 3 else {})})
        for hold in range(execute_hold):
            add(prefix + f'hold_execute_{hold}', execute_ready=0, **grant(command, hold % 2, wrong_tag=True))
        add(prefix + 'execute')
        result = {key: value for key, value in command.items() if key.startswith('result_')}
        result['result_valid'] = 1
        add(prefix + 'stale_result', **{**result, 'result_bits_token_tag': command['issue_bits_token_tag'] ^ (1 << 63), **grant(command, 1, wrong_index=True)})
        add(prefix + 'result', **result, **grant(command, 1, valid=0))
        for hold in range(completed_hold): add(prefix + f'complete_hold_{hold}', completeAccept=1)
        add(prefix + 'wrong_tag', **grant(command, 0, wrong_tag=True))
        add(prefix + 'wrong_index', **grant(command, 1, wrong_index=True))
        add(prefix + 'invalid', **grant(command, 0, valid=0))
        refill = commands[3].copy() if n == 2 else {}
        add(prefix + 'retire', **{**refill, **grant(command, n % 2)})
        if n != 2:
            add(prefix + 'repeat0', **grant(command, 0))
            add(prefix + 'repeat1', **grant(command, 1))
    add('final_idle_0')
    add('final_idle_1')
    return rows


def header(schedule):
    return {'type': 'header', 'schema': 1, 'component_only': True, 'guest_fd_execution': False,
            'cycle_limit': CYCLE_LIMIT, 'schedule': schedule,
            'execute_hold': 1 if schedule == 'baseline' else 3,
            'completed_hold': 2 if schedule == 'baseline' else 5, 'recipe': recipe()}


def exact(actual, expected, label):
    """JSON equality must not confuse true/1, false/0, or float/integer."""
    need(type(actual) is type(expected), 'invalid type: ' + label)
    if type(expected) is dict:
        keys(actual, expected, label)
        for key, value in expected.items(): exact(actual[key], value, label + '.' + key)
    elif type(expected) is list:
        need(len(actual) == len(expected), 'length mismatch: ' + label)
        for n, value in enumerate(expected): exact(actual[n], value, label + '.' + str(n))
    else:
        need(actual == expected, 'mismatch: ' + label)


EXPECTED_COUNTS = {'issued': 4, 'completion_accepts': 4, 'owner_retired_pulses': 13,
    'successful_active_owner_retirements': 4, 'inactive_owner_pulses': 9,
    'fp_retire_accepted': 4, 'successful_fp_retirements': 4, 'fp_architectural_mutations': 3,
    'fpr_writes': 2, 'fflags_updates': 3, 'host_dirty_events': 3, 'guest_dirty_events': 2}


def expected_summary(schedule):
    return {**EXPECTED_COUNTS, 'schema': 1, 'component_only': 1, 'guest_fd_execution': 0,
            'cycles': len(plan(schedule))}


def check_summary(row, schedule):
    exact(row, expected_summary(schedule), 'summary')


def check_trace(path, schedule, summary=None):
    lines = clean_text(path).splitlines()
    planned = plan(schedule)
    need(len(planned) <= CYCLE_LIMIT and len(lines) == len(planned) + 2, 'raw cycle count mismatch')
    exact(object_row(lines[0]), header(schedule), 'header')
    ledger = Replay()
    rows = [object_row(line) for line in lines[1:-1]]
    for number, (row, (phase, stimulus)) in enumerate(zip(rows, planned), 1):
        keys(row, ('type', 'cycle', 'phase', 'in', 'pre', 'post'), 'cycle')
        exact([row['type'], row['cycle'], row['phase']], ['cycle', number - 1, phase], 'cycle order')
        scalar_map(row['in'], INPUT_WIDTHS, 'in')
        scalar_map(row['pre'], OUTPUT_WIDTHS, 'pre')
        exact(row['in'], stimulus, 'frozen inputs ' + phase)
        expected = ledger.step(stimulus)
        for key, value in expected.items():
            need(row['pre'][key] == value, f'raw pre mismatch {phase}.{key}')
        scalar_map(row['post'], POST_WIDTHS, 'post')
        exact(row['post'], {key: ledger.state[key] for key in POST_WIDTHS}, 'post ' + phase)
        if number < len(rows):
            next_pre = rows[number].get('pre')
            need(type(next_pre) is dict and all(row['post'][key] == next_pre.get(key) for key in POST_WIDTHS),
                 'post state not linked to next observation')
    exact(object_row(lines[-1]), {'type': 'footer', 'cycles': len(planned), 'complete': True}, 'footer')
    need(not ledger.state['busy'] and not ledger.state['ownerActive'], 'undrained final state')
    exact(ledger.counts, EXPECTED_COUNTS, 'coverage ledger')
    if summary is not None: check_summary(summary, schedule)
    return rows


def check_positive(path, schedule, trace):
    lines = clean_text(path).splitlines()
    need(len(lines) == 1 and lines[0].startswith(MARKER + ' '), 'expected one summary only')
    summary = object_row(lines[0][len(MARKER) + 1:])
    check_summary(summary, schedule)
    check_trace(trace, schedule, summary)
    return summary


def check_negative(path, name, returncode, trace):
    need(type(returncode) is int and returncode == 1, 'negative must exit exactly one')
    phase = NEGATIVE_PHASES[name]
    cycle = next(n for n, (label, _) in enumerate(plan('baseline')) if label == phase)
    need(clean_text(path) == f'PROTECTED_FP_CHECK[{name}] cycle={cycle} phase={phase}\n',
         'negative missed exact named checker')
    rows = check_trace(trace, 'baseline')
    need(any(row['phase'] == NEGATIVE_PHASES[name] for row in rows), 'negative target trace missing')


def native_run(output, arguments, log_name, env):
    path = output / log_name
    with path.open('x') as log:
        result = subprocess.run([str(output / 'run'), *arguments], cwd=common.ROOT,
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=TIMEOUT)
    return path, result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=common.BUILD / 'protected-fp-retirement')
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink(), 'fresh output directory required')
    output = args.output.resolve()
    gsim, cxx = common.setup(False)
    os.environ['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    first_trace = output / 'raw-baseline.jsonl'
    built = common.test(gsim, cxx, str(output), 'ooo.ProtectedFpRetirementGsimMain',
                        'ProtectedFpRetirementGsim', 'protected_fp_retirement.cpp',
                        runtime_args=('--schedule', 'baseline', '--trace', str(first_trace)),
                        sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=TIMEOUT,
                        mill_module='IonSoC.protectedFpRetirement')
    need(built == output, 'generated model destination changed')
    summaries = [check_positive(output / 'test.log', 'baseline', first_trace)]
    second_trace = output / 'raw-staggered.jsonl'
    log, code = native_run(output, ('--schedule', 'staggered', '--trace', str(second_trace)),
                           'staggered.log', env)
    need(type(code) is int and code == 0, 'staggered execution failed')
    summaries.append(check_positive(log, 'staggered', second_trace))
    for name in NEGATIVES:
        log, code = native_run(output, ('--schedule', 'baseline', '--negative', name, '--trace', str(output / ('negative-' + name + '.jsonl'))),
                               'negative-' + name + '.log', env)
        check_negative(log, name, code, output / ('negative-' + name + '.jsonl'))
    receipt = {'schema': 1, 'component_only': True, 'guest_fd_execution': False,
               'schedules': summaries, 'negatives': list(NEGATIVES)}
    with (output / 'entry-summary.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(STANDARD_MARKER)


if __name__ == '__main__':
    main()
