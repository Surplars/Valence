#!/usr/bin/env python3
"""Bounded genuine guarded FP bridge evidence; actual H+FP stays disabled."""
import argparse
import json
import os
from pathlib import Path
import subprocess
from fractions import Fraction

import run as common

MARKER = 'GUARDED_FP_BRIDGE_SUMMARY'
STANDARD_MARKER = 'GUARDED_FP_BRIDGE_STANDARD_PASS'
TIMEOUT = 120
TRACE_LIMIT = 4 * 1024 * 1024
CYCLE_LIMIT = 2048
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



START_WIDTHS = {'token_index': 4, 'token_tag': 64, 'pc': 64,
                'instruction': 32, 'operand': 64, 'operand2': 64}
COMPLETE_WIDTHS = {'token_index': 4, 'token_tag': 64, 'data': 64,
    'nextPc': 64, 'exception': 1, 'cause': 64, 'tval': 64,
    'guestFault_guestPageFault': 1, 'guestFault_guestAddress': 1,
    'guestFault_guestPhysicalAddress': 64, 'guestFault_implicitPte': 1}

def prefixed(prefix, fields):
    return {prefix + key: value for key, value in fields.items()}

INPUT_WIDTHS = {'start_valid': 1, 'complete_ready': 1, 'translationActive': 1,
    'csr_valid': 1, 'csr_bits_address': 12, 'csr_bits_operation': 2,
    'csr_bits_write': 1, 'csr_bits_value': 64, 'status_valid': 1,
    'status_bits_address': 12, 'status_bits_data': 64, 'statusReadAddress': 12,
    'mret': 1, 'sret': 1, **prefixed('start_bits_', START_WIDTHS)}
for _lane in range(2):
    INPUT_WIDTHS.update({f'commit{_lane}_valid': 1, f'commit{_lane}_bits_index': 4,
                         f'commit{_lane}_bits_tag': 64})
STATE_WIDTHS = {'ownerActive': 1, 'ownerToken_index': 4, 'ownerToken_tag': 64,
    'contextMemoryEpoch': 1, 'hMemoryEpoch': 1, 'fpMemoryEpoch': 1,
    'completionSeen': 1, 'statePhase': 2, 'busy': 1, 'virtualized': 1,
    'hostFs': 2, 'hostSd': 1, 'guestFs': 2, 'guestSd': 1, 'fcsr': 8,
    **{f'fpr_{n}': 64 for n in range(32)}}
OUTPUT_WIDTHS = {**STATE_WIDTHS, 'start_ready': 1, 'issueAccepted': 1,
    'complete_valid': 1, 'completionAccepted': 1, 'retired': 1,
    'retireMatches': 2, 'retireAccepted': 1, 'mutation_valid': 1,
    'mutation_bits_guest': 1, 'csr_ready': 1, 'csrRead': 64, 'csrIllegal': 1,
    'status_ready': 1, 'statusReadData': 64, 'statusShadow': 1,
    **prefixed('complete_bits_', COMPLETE_WIDTHS)}
POST_WIDTHS = {key: width for key, width in STATE_WIDTHS.items()
               if key not in ('contextMemoryEpoch', 'hMemoryEpoch', 'fpMemoryEpoch')}

def scalar_map(row, widths, label):
    keys(row, widths, label)
    for key, width in widths.items():
        need(unsigned(row[key], width), 'invalid raw ' + label + '.' + key)


def exact(actual, expected, label):
    """Strict JSON equality: booleans/floats must not masquerade as integers."""
    need(type(actual) is type(expected), 'invalid type: ' + label)
    if type(expected) is dict:
        keys(actual, expected, label)
        for key, value in expected.items(): exact(actual[key], value, label + '.' + key)
    elif type(expected) is list:
        need(len(actual) == len(expected), 'length mismatch: ' + label)
        for n, value in enumerate(expected): exact(actual[n], value, label + '.' + str(n))
    else:
        need(actual == expected, 'mismatch: ' + label)


def box(value):
    return 0xffffffff00000000 | (value & 0xffffffff)


def finite_positive(bits, double):
    """Decode positive normal IEEE values as exact rationals, without host floats."""
    fraction_bits, exponent_bits = (52, 11) if double else (23, 8)
    bias = (1 << (exponent_bits - 1)) - 1
    exponent = (bits >> fraction_bits) & ((1 << exponent_bits) - 1)
    need(bits >> (fraction_bits + exponent_bits) == 0 and 0 < exponent < (1 << exponent_bits) - 1,
         'add operand outside frozen positive normal subset')
    significand = (1 << fraction_bits) | (bits & ((1 << fraction_bits) - 1))
    power = exponent - bias - fraction_bits
    return Fraction(significand << max(power, 0), 1 << max(-power, 0))


def add_ieee(left, right, double, rounding):
    """Exact rational addition with independent RNE/RUP rounding for frozen cases."""
    need(rounding in (0, 3), 'rounding outside frozen RNE/RUP subset')
    fraction_bits, exponent_bits = (52, 11) if double else (23, 8)
    value = finite_positive(left, double) + finite_positive(right, double)
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if value < Fraction(1 << max(exponent, 0), 1 << max(-exponent, 0)): exponent -= 1
    shift = fraction_bits - exponent
    scaled = value * Fraction(1 << max(shift, 0), 1 << max(-shift, 0))
    whole, remainder = divmod(scaled.numerator, scaled.denominator)
    if remainder and (rounding == 3 or 2 * remainder > scaled.denominator or
                      2 * remainder == scaled.denominator and whole & 1): whole += 1
    if whole == 1 << (fraction_bits + 1):
        whole >>= 1
        exponent += 1
    bias = (1 << (exponent_bits - 1)) - 1
    need(0 < exponent + bias < (1 << exponent_bits) - 1, 'rounded value outside normal subset')
    encoded = ((exponent + bias) << fraction_bits) | (whole - (1 << fraction_bits))
    return encoded if double else box(encoded), int(bool(remainder))


def operation(command, state):
    """Decode only independently encoded tested ISA operations, never DUT fields."""
    inst = command['instruction']
    need(inst & 127 == 0x53, 'not an OP-FP instruction')
    funct7, funct3 = inst >> 25, (inst >> 12) & 7
    rd, rs1, rs2 = (inst >> 7) & 31, (inst >> 15) & 31, (inst >> 20) & 31
    double = bool(funct7 & 1)
    a, b = state[f'fpr_{rs1}'], state[f'fpr_{rs2}']
    result = {'destination': rd, 'writesFp': False, 'writesFlags': False,
              'flags': 0, 'latency': 4, 'value': 0}
    if funct7 in (0x78, 0x79):
        need(rs2 == 0 and funct3 == 0, 'reserved FMV-to-FP')
        result.update(value=command['operand'] if double else box(command['operand']), writesFp=True)
    elif funct7 in (0, 1):
        rounding = state['fcsr'] >> 5 if funct3 == 7 else funct3
        if not double:
            need(a >> 32 == b >> 32 == 0xffffffff, 'frozen add requires boxed operands')
            a &= 0xffffffff
            b &= 0xffffffff
        value, flags = add_ieee(a, b, double, rounding)
        result.update(value=value, flags=flags, writesFp=True, writesFlags=True, latency=5)
    elif funct7 == 0x50 and funct3 == 2:
        # The single frozen FEQ.S compares a signaling NaN and positive one.
        need(a == box(0x7f800001) and b == box(0x3f800000), 'unfrozen FEQ operands')
        result.update(value=0, flags=16, writesFlags=True)
    elif funct7 in (0x70, 0x71):
        need(rs2 == 0 and funct3 in (0, 1), 'reserved move/class')
        if funct3 == 1:
            need(double and a == 0x3ff0000000000000, 'unfrozen FCLASS operand')
            result['value'] = 64
        else:
            result['value'] = a if double else (a & 0xffffffff) | (0xffffffff00000000 if a & 0x80000000 else 0)
    else:
        raise RuntimeError('instruction outside frozen operation subset')
    return result


class Replay:
    """Input-only pipeline/architectural ledger, including source-audited fixed latency.

    Expected values, permissions, ownership and timing never come from observations.
    start at cycle N yields completed state at N+4 (misc) or N+5 (shared add).
    """
    def __init__(self):
        self.state = dict.fromkeys(STATE_WIDTHS, 0)
        self.command = None
        self.result = None
        self.guest = 0
        self.age = 0
        self.spv = 0
        self.counts = dict.fromkeys(('issued', 'completion_accepts', 'owner_retired_pulses',
            'successful_active_owner_retirements', 'inactive_owner_pulses', 'fp_retire_accepted',
            'csr_mutations', 'fp_architectural_mutations', 'fpr_writes',
            'fflags_updates', 'host_dirty_events', 'guest_dirty_events'), 0)

    def observe(self, i):
        s = self.state
        o = s.copy()
        idle = s['statePhase'] == 0
        mask = sum(int(i[f'commit{n}_valid'] and
            i[f'commit{n}_bits_index'] == s['ownerToken_index'] and
            i[f'commit{n}_bits_tag'] == s['ownerToken_tag']) << n for n in range(2))
        completed = s['statePhase'] == 3
        ready = int(idle and not i['status_valid'] and not i['csr_valid'])
        retire = int(completed and bool(mask) and self.command is not None and
            self.command['token_index'] == s['ownerToken_index'] and
            self.command['token_tag'] == s['ownerToken_tag'])
        csr_ready = int(idle and not i['status_valid'])
        allowed = bool(s['hostFs'] and (not s['virtualized'] or s['guestFs']))
        illegal = int(i['csr_bits_address'] not in (1, 2, 3) or not allowed or i['csr_bits_operation'] == 3)
        csr_mutation = int(i['csr_valid'] and csr_ready and i['csr_bits_write'] and not illegal)
        mutation = int(csr_mutation or retire and (self.result['writesFp'] or self.result['writesFlags']))
        offered = int(completed and not s['completionSeen'])
        o.update(start_ready=ready, issueAccepted=ready * i['start_valid'],
            complete_valid=offered, completionAccepted=offered * i['complete_ready'],
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
        if self.command is None and not csr_mutation: del o['mutation_bits_guest']
        if completed:
            response = dict.fromkeys(COMPLETE_WIDTHS, 0)
            response.update(token_index=self.command['token_index'], token_tag=self.command['token_tag'],
                nextPc=self.command['pc'] + 4, data=self.result['value'])
            o.update(prefixed('complete_bits_', response))
        return o

    def step(self, i):
        o = self.observe(i)
        s, count = self.state, self.counts
        if i['status_valid'] or i['csr_valid'] or i['mret'] or i['sret']:
            need(not s['busy'] and not s['ownerActive'], 'context replacement with live owner')
        if i['status_valid']:
            address, data = i['status_bits_address'], i['status_bits_data']
            if address == 0x300 or address == 0x100 and not s['virtualized']: s['hostFs'] = (data >> 13) & 3
            if address == 0x200 or address == 0x100 and s['virtualized']: s['guestFs'] = (data >> 13) & 3
            if address == 0x600: self.spv = (data >> 7) & 1
        if i['sret']: s['virtualized'], self.spv = self.spv, 0
        need(not i['mret'], 'M-origin outside scope')
        if i['csr_valid'] and o['csr_ready'] and i['csr_bits_write'] and not o['csrIllegal']:
            count['csr_mutations'] += 1
            value, op, address = i['csr_bits_value'], i['csr_bits_operation'], i['csr_bits_address']
            value = value if op == 0 else o['csrRead'] | value if op == 1 else o['csrRead'] & ~value
            if address == 1: s['fcsr'] = (s['fcsr'] & 224) | (value & 31)
            elif address == 2: s['fcsr'] = ((value & 7) << 5) | (s['fcsr'] & 31)
            else: s['fcsr'] = value & 255
        if o['completionAccepted']:
            need(s['ownerActive'], 'accepted completion without owner')
            s['completionSeen'] = 1
            count['completion_accepts'] += 1
        if o['retired']:
            count['owner_retired_pulses'] += 1
            count['successful_active_owner_retirements' if s['ownerActive'] else 'inactive_owner_pulses'] += 1
            s['ownerActive'] = 0
        if o['retireAccepted']:
            need(s['completionSeen'], 'retirement before completion acceptance')
            count['fp_retire_accepted'] += 1
            s['statePhase'] = 0
            if self.result['writesFp']:
                s[f"fpr_{self.result['destination']}"] = self.result['value']
                count['fpr_writes'] += 1
            if self.result['writesFlags']:
                s['fcsr'] |= self.result['flags']
                count['fflags_updates'] += 1
        if o['mutation_valid']:
            s['hostFs'] = 3
            if o['mutation_bits_guest']: s['guestFs'] = 3
            if o['retireAccepted']:
                count['fp_architectural_mutations'] += 1
                count['host_dirty_events'] += 1
                count['guest_dirty_events'] += o['mutation_bits_guest']
        if o['statePhase'] in (1, 2):
            self.age += 1
            s['statePhase'] = 3 if self.age == self.result['latency'] else 2
        if o['issueAccepted']:
            need(not o['ownerActive'], 'issue overwrote live owner')
            self.command = {key: i['start_bits_' + key] for key in START_WIDTHS}
            self.guest = s['virtualized']
            need(s['hostFs'] and (not self.guest or s['guestFs']), 'illegal FP permission')
            self.result = operation(self.command, s)
            self.age = 1
            s.update(statePhase=1, completionSeen=0, ownerActive=1,
                     ownerToken_index=self.command['token_index'], ownerToken_tag=self.command['token_tag'])
            count['issued'] += 1
        s['busy'] = int(s['statePhase'] != 0)
        s['hostSd'], s['guestSd'] = int(s['hostFs'] == 3), int(s['guestFs'] == 3)
        return o

NEGATIVE_PHASES = {'numerical_value': 'op7_complete_hold_0', 'boxed_single': 'op9_retire',
    'rounding_selection': 'op10_complete_hold_0', 'premature_mutation': 'op7_wait_0',
    'fflags_accumulation': 'op12_retire', 'guest_dirty': 'op9_retire',
    'duplicate_completion': 'op0_retire_hold_0', 'refill_credit': 'op7_retire'}
NEGATIVES = tuple(NEGATIVE_PHASES)


def defaults():
    return {**dict.fromkeys(INPUT_WIDTHS, 0), 'translationActive': 1,
            'csr_bits_address': 3, 'statusReadAddress': 0x100}


def recipe():
    words = (0xf20080d3, 0xf2008153, 0xf00081d3, 0xf0008253, 0xf20082d3,
        0xf2008353, 0xf00083d3, 0x02208053, 0xe2000653, 0x0041f453, 0x004184d3,
        0x0262f553, 0xa033a6d3, 0xe2029753, 0xe00407d3, 0xe2050853)
    seeds = (0x3ff8000000000000, 0x4002000000000000, 0x3f800000, 0x33800000,
        0x3ff0000000000000, 0x3ca0000000000000, 0x7f800001)
    result = []
    for n, word in enumerate(words):
        result.append({**defaults(), 'start_valid': 1, 'start_bits_instruction': word,
            'start_bits_operand': seeds[n] if n < 7 else 0, 'start_bits_pc': 0x80000000 + 4*n,
            'start_bits_token_index': 1 if n == 15 else n % 14 + 1,
            'start_bits_token_tag': 0x945600000000000f if n == 15 else 0x1456000000000001 + n,
            'translationActive': int(n < 9)})
    return result


def plan(schedule):
    need(schedule in SCHEDULES, 'unknown schedule')
    ready_hold, retire_hold = (1, 2) if schedule == 'baseline' else (4, 5)
    rows = []
    guest = False
    def blank(): return {**defaults(), 'translationActive': int(not guest)}
    def add(phase, **updates): rows.append((phase, {**blank(), **updates}))
    def status(phase, address, data):
        add(phase, status_valid=1, status_bits_address=address, status_bits_data=data)
    def csr(phase, write): add(phase, csr_valid=1, csr_bits_write=int(write), csr_bits_value=96)
    def grant(command, lane, valid=1, wrong_tag=False, wrong_index=False):
        return {f'commit{lane}_valid': valid,
            f'commit{lane}_bits_index': command['start_bits_token_index'] ^ int(wrong_index),
            f'commit{lane}_bits_tag': command['start_bits_token_tag'] ^ ((1 << 63) if wrong_tag else 0)}
    for lane in range(2): add(f'cold_lane{lane}', **{f'commit{lane}_valid': 1})
    status('setup_host', 0x300, 2 << 13)
    status('setup_guest', 0x200, 2 << 13)
    csr('host_csr_write', True)
    csr('host_csr_read', False)
    commands = recipe()
    for n, command in enumerate(commands):
        if n in (7, 9, 12, 13):
            status(f'op{n}_host_clean', 0x300, 2 << 13)
            status(f'op{n}_vs_clean', 0x200, 2 << 13)
        if n == 9:
            status('guest_spv', 0x600, 128)
            add('guest_enter', sret=1)
            guest = True
            csr('guest_csr_write', True)
            csr('guest_csr_read', False)
            status('guest_csr_host_clean', 0x300, 2 << 13)
            status('guest_csr_vs_clean', 0x200, 2 << 13)
        prefix = f'op{n}_'
        add(prefix + 'issue', **{**command, **(grant(commands[7], 1) if n == 8 else {})})
        latency = 5 if n in (7, 9, 10, 11) else 4
        for j in range(latency): add(prefix + f'wait_{j}')
        for j in range(ready_hold): add(prefix + f'complete_hold_{j}')
        add(prefix + 'accept', complete_ready=1)
        for j in range(retire_hold): add(prefix + f'retire_hold_{j}', complete_ready=1)
        add(prefix + 'wrong_tag', **grant(command, 0, wrong_tag=True))
        add(prefix + 'wrong_index', **grant(command, 1, wrong_index=True))
        add(prefix + 'invalid', **grant(command, 0, valid=0))
        add(prefix + 'retire', **{**(commands[8] if n == 7 else {}), **grant(command, n % 2)})
        if n != 7:
            for lane in range(2): add(prefix + f'repeat{lane}', **grant(command, lane))
    add('final_idle_0')
    add('final_idle_1')
    return rows


def header(schedule):
    return {'type': 'header', 'schema': 1, 'component_only': True,
        'guest_fd_cpu_execution': False, 'real_fp_arithmetic': True,
        'cycle_limit': CYCLE_LIMIT, 'schedule': schedule,
        'ready_hold': 1 if schedule == 'baseline' else 4,
        'retire_hold': 2 if schedule == 'baseline' else 5, 'recipe': recipe()}


EXPECTED_COUNTS = {'issued': 16, 'completion_accepts': 16, 'owner_retired_pulses': 49,
    'successful_active_owner_retirements': 16, 'inactive_owner_pulses': 33,
    'fp_retire_accepted': 16, 'csr_mutations': 2, 'fp_architectural_mutations': 12,
    'fpr_writes': 11, 'fflags_updates': 5, 'host_dirty_events': 12, 'guest_dirty_events': 4}


def expected_summary(schedule):
    return {**EXPECTED_COUNTS, 'schema': 1, 'component_only': 1,
        'guest_fd_cpu_execution': 0, 'real_fp_arithmetic': 1, 'cycles': len(plan(schedule))}


def check_summary(row, schedule): exact(row, expected_summary(schedule), 'summary')


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
    need(ledger.state['fcsr'] == 113 and ledger.state['hostFs'] == ledger.state['guestFs'] == 2,
         'final flags and clean no-write state')
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
    need(clean_text(path) == f'GUARDED_FP_CHECK[{name}] cycle={cycle} phase={phase}\n',
         'negative missed exact named checker')
    rows = check_trace(trace, 'baseline')
    need(any(row['phase'] == phase for row in rows), 'negative target trace missing')


def native_run(output, arguments, log_name, env):
    path = output / log_name
    with path.open('x') as log:
        result = subprocess.run([str(output / 'run'), *arguments], cwd=common.ROOT,
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=TIMEOUT)
    return path, result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=common.BUILD / 'guarded-fp-bridge')
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink(), 'fresh output directory required')
    output = args.output.resolve()
    gsim, cxx = common.setup(False)
    os.environ['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    first_trace = output / 'raw-baseline.jsonl'
    built = common.test(gsim, cxx, str(output), 'ooo.GuardedFpBridgeGsimMain',
        'GuardedFpBridgeGsim', 'guarded_fp_bridge.cpp',
        runtime_args=('--schedule', 'baseline', '--trace', str(first_trace)),
        sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=TIMEOUT,
        mill_module='IonSoC.guardedFpBridge')
    need(built == output, 'generated model destination changed')
    summaries = [check_positive(output / 'test.log', 'baseline', first_trace)]
    second_trace = output / 'raw-staggered.jsonl'
    log, code = native_run(output, ('--schedule', 'staggered', '--trace', str(second_trace)), 'staggered.log', env)
    need(type(code) is int and code == 0, 'staggered execution failed')
    summaries.append(check_positive(log, 'staggered', second_trace))
    for name in NEGATIVES:
        trace = output / ('negative-' + name + '.jsonl')
        log, code = native_run(output, ('--schedule', 'baseline', '--negative', name, '--trace', str(trace)),
                               'negative-' + name + '.log', env)
        check_negative(log, name, code, trace)
    receipt = {'schema': 1, 'component_only': True, 'guest_fd_cpu_execution': False,
        'real_fp_arithmetic': True, 'schedules': summaries, 'negatives': list(NEGATIVES)}
    with (output / 'entry-summary.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(STANDARD_MARKER)


if __name__ == '__main__': main()
