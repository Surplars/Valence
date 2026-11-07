#!/usr/bin/env python3
"""Bounded real FP memory/fault consumer qualification; actual H+FP stays disabled."""
import argparse
import json
import os
from pathlib import Path
import subprocess

import run as common

MARKER = 'GUARDED_FP_FAULT_RECOVERY_SUMMARY'
STANDARD_MARKER = 'GUARDED_FP_FAULT_RECOVERY_STANDARD_PASS'
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

CONTEXT_WIDTHS = {'virtualAddress': 64, 'vsatp': 64, 'hgatp': 64, 'virtualized': 1,
    'effectivePrivilege': 2, 'access': 2, 'size': 3, 'vsSum': 1, 'vsMxr': 1,
    'hsMxr': 1, 'forceExecute': 1, 'epoch': 8}
FAULT_WIDTHS = {'guestPageFault': 1, 'guestAddress': 1, 'guestPhysicalAddress': 64, 'implicitPte': 1}
REQUEST_WIDTHS = {'atomic': 1, 'atomicOp': 5, 'address': 64, 'write': 1, 'size': 2,
    'data': 64, 'mask': 8, 'virtualized': 1, 'precheckedLoad': 1,
    'translationEpoch': 32, 'prefetchNextAllowed': 1, 'uncached': 1}
RESPONSE_WIDTHS = {'data': 64, 'error': 1, 'pageFault': 1}
TRAP_WIDTHS = {'pc': 64, 'cause': 64, 'tval': 64, 'guestAddress': 1,
    'guestPhysicalAddress': 64, 'implicitPte': 1}
INPUT_WIDTHS = {'start_valid': 1, 'complete_ready': 1,
    'csr_valid': 1, 'csr_bits_address': 12, 'csr_bits_operation': 2,
    'csr_bits_write': 1, 'csr_bits_value': 64, 'status_valid': 1,
    'status_bits_address': 12, 'status_bits_data': 64, 'statusReadAddress': 12,
    'mret': 1, 'sret': 1, **prefixed('start_bits_', START_WIDTHS),
    **prefixed('context_', CONTEXT_WIDTHS), 'hostSatp': 64, 'pmpTop': 54,
    'pmpPermission': 3, 'pmaDenied': 1, 'trap_valid': 1,
    **prefixed('trap_bits_', TRAP_WIDTHS), 'physical_request_ready': 1,
    'physical_response_valid': 1, **prefixed('physical_response_bits_', RESPONSE_WIDTHS),
    'pte_request_ready': 1, 'pte_response_valid': 1, 'pte_response_bits_data': 64,
    'pte_response_bits_error': 1}
for _lane in range(2):
    INPUT_WIDTHS.update({f'commit{_lane}_valid': 1, f'commit{_lane}_bits_index': 4,
                         f'commit{_lane}_bits_tag': 64})
STATE_WIDTHS = {'ownerActive': 1, 'ownerToken_index': 4, 'ownerToken_tag': 64,
    'completionSeen': 1, 'statePhase': 2, 'busy': 1, 'virtualized': 1,
    'hostFs': 2, 'hostSd': 1, 'guestFs': 2, 'guestSd': 1, 'fcsr': 8,
    'hstatus': 64, 'htval': 64, **{f'fpr_{n}': 64 for n in range(32)}}
OUTPUT_WIDTHS = {**STATE_WIDTHS, 'start_ready': 1, 'issueAccepted': 1,
    'complete_valid': 1, 'completionAccepted': 1, 'retired': 1,
    'retireMatches': 2, 'retireAccepted': 1, 'mutation_valid': 1,
    'mutation_bits_guest': 1, 'csr_ready': 1, 'csrRead': 64, 'csrIllegal': 1,
    'status_ready': 1, 'statusReadData': 64, 'statusShadow': 1,
    **prefixed('complete_bits_', COMPLETE_WIDTHS), 'contextMemoryEpoch': 1,
    'hMemoryEpoch': 1, 'fpMemoryEpoch': 1, 'translationActive': 1,
    'selectorDomain': 2, 'selectorBusy': 1, 'memoryDrained': 1,
    'contextReplaceAllowed': 1, 'executeValid': 1, 'executeFire': 1,
    'stateCompleteValid': 1, 'memoryBusy': 1, 'adapterIdle': 1,
    'translatorIdle': 1, 'responseBufferIdle': 1, 'completionCount': 2,
    'adapterFire': 1, 'responseEpoch': 8, 'physical_request_valid': 1,
    **prefixed('physical_request_bits_', REQUEST_WIDTHS), 'physical_response_ready': 1,
    'pte_request_valid': 1, 'pte_request_bits': 64, 'pte_response_ready': 1,
    'physicalCheck_valid': 1,
    **prefixed('physicalCheck_bits_', {'address': 64, 'size': 2, 'access': 2, 'atomic': 1, 'forceExecute': 1}),
    'virtualRequest_valid': 1, **prefixed('virtualRequest_bits_', REQUEST_WIDTHS),
    'adapterResponse_valid': 1, **prefixed('adapterResponse_bits_', RESPONSE_WIDTHS),
    'adapterResponseFire': 1, **prefixed('adapterFault_', FAULT_WIDTHS),
    'bufferedResponse_valid': 1, **prefixed('bufferedResponse_bits_', RESPONSE_WIDTHS),
    'bufferedResponseFire': 1, **prefixed('bufferedFault_', FAULT_WIDTHS),
    'pipelineComplete_valid': 1, **prefixed('pipelineComplete_bits_', COMPLETE_WIDTHS),
    'convertedResult_valid': 1,
    **prefixed('convertedResult_bits_', {**{k: v for k, v in COMPLETE_WIDTHS.items() if k not in ('data', 'nextPc')},
                                      'value': 64, 'flags': 5})}
POST_WIDTHS = STATE_WIDTHS

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


class PageFault(Exception):
    def __init__(self, guest, address, implicit=False):
        self.guest, self.address, self.implicit = guest, address, implicit


class Translation:
    """Independent Sv39/Sv39x4 walk over frozen physical PTE words.

    The access list is an oracle for actual external PTE requests, including
    nested translation of every implicit VS page-table read. No DUT result or
    scenario label is used to choose the resulting address or exception.
    """
    def __init__(self, ptes):
        self.ptes = dict(ptes)
        self.reads = []

    def read(self, address):
        self.reads.append(address)
        return self.ptes.get(address, 0)

    def walk(self, address, root, access, guest, implicit=False, g_root=0):
        if root >> 60 == 0:
            return address
        need(root >> 60 == 8, 'only Sv39/Sv39x4 is frozen')
        if guest:
            if address >> 41: raise PageFault(True, address, implicit)
        else:
            high = address >> 39
            if high != ((1 << 25) - 1 if address & (1 << 38) else 0):
                raise PageFault(False, address)
        table = (root & ((1 << 44) - 1)) << 12
        for level in (2, 1, 0):
            width = 11 if guest and level == 2 else 9
            slot = table + ((address >> (12 + 9 * level)) & ((1 << width) - 1)) * 8
            physical = self.walk(slot, g_root, 0, True, True) if not guest and g_root else slot
            pte = self.read(physical)
            valid, read, write, execute, user = (bool(pte & (1 << n)) for n in range(5))
            if not valid or write and not read or pte >> 54:
                raise PageFault(guest, address, implicit)
            if read or execute:
                # Frozen VS privilege is S, SUM/MXR are clear. G-stage always
                # checks U, including implicit supervisor PTE reads.
                permitted = read if access == 0 else write
                if not permitted or user != guest or not pte & 64 or access == 1 and not pte & 128:
                    raise PageFault(guest, address, implicit)
                ppn = (pte >> 10) & ((1 << 44) - 1)
                low = 12 + 9 * level
                if ppn & ((1 << (9 * level)) - 1): raise PageFault(guest, address, implicit)
                return (ppn << 12) | (address & ((1 << low) - 1))
            if level == 0 or pte & (16 | 64 | 128):
                raise PageFault(guest, address, implicit)
            table = ((pte >> 10) & ((1 << 44) - 1)) << 12
        raise AssertionError('unreachable walk')

    def translate(self, address, vsatp, hgatp, access):
        gpa = self.walk(address, vsatp, access, False, g_root=hgatp)
        return self.walk(gpa, hgatp, access, True), gpa


def signed(value, width):
    return value - (1 << width) if value & (1 << (width - 1)) else value


def decode(command, state, memory, ptes, context):
    """Input-derived RV64 D moves/memory outcome, independent of hardware decode."""
    inst = command['instruction']
    op, rd, rs1, rs2 = inst & 127, (inst >> 7) & 31, (inst >> 15) & 31, (inst >> 20) & 31
    result = dict(data=0, exception=0, cause=0, tval=0, guestPageFault=0,
                  guestAddress=0, guestPhysicalAddress=0, implicitPte=0,
                  writes=False, rd=rd, address=None, physical=None, store=False, ptes=[])
    if not state['hostFs'] or state['virtualized'] and not state['guestFs']:
        result.update(exception=1, cause=2, tval=inst)
        return result
    if op == 0x53:
        need((inst >> 12) & 7 == 0 and rs2 == 0, 'reserved FP move')
        if inst >> 25 == 0x79:
            result.update(data=command['operand'], writes=True)
        elif inst >> 25 == 0x71:
            result['data'] = state[f'fpr_{rs1}']
        else: raise RuntimeError('instruction outside frozen D move subset')
        return result
    need(op in (7, 0x27) and (inst >> 12) & 7 == 3, 'instruction outside frozen FLD/FSD subset')
    store = op == 0x27
    immediate = ((inst >> 25) << 5) | rd if store else inst >> 20
    address = (command['operand'] + signed(immediate, 12)) & ((1 << 64) - 1)
    result.update(address=address, store=store, writes=not store)
    if address & 7:
        result.update(exception=1, cause=6 if store else 4, tval=address,
                      guestAddress=context['virtualized'])
        return result
    walker = Translation(ptes)
    try:
        physical, gpa = walker.translate(address, context['vsatp'], context['hgatp'], int(store))
    except PageFault as fault:
        result.update(exception=1, cause=(23 if store else 21) if fault.guest else (15 if store else 13),
                      tval=address, guestPageFault=int(fault.guest), guestAddress=context['virtualized'],
                      guestPhysicalAddress=fault.address if fault.guest else 0, implicitPte=int(fault.implicit))
    else:
        result.update(physical=physical, cause=7 if store else 5, tval=address, guestAddress=context['virtualized'], data=0 if store else sum(memory.get(physical + n, 0) << (8*n) for n in range(8)))
        result['storeData'] = state[f'fpr_{rs2}'] if store else 0
    result['ptes'] = walker.reads
    return result

class Replay:
    """Independent input-derived architectural and request ownership ledger.

    Memory service progress is observed through genuine ready/valid handshakes;
    expected addresses, bytes, faults and architectural writes are derived from
    instructions, page tables and accepted input context, never producer values.
    """
    def __init__(self, ptes, memory):
        self.state = dict.fromkeys(STATE_WIDTHS, 0)
        self.state['hstatus'] = 2 << 32
        self.memory, self.ptes = dict(memory), dict(ptes)
        self.command = self.result = self.context = None
        self.owner_memory = False
        self.guest = 0
        self.cycle = 0
        self.issue_cycle = -1
        self.pte_index = 0
        self.pte_pending = self.physical_pending = None
        self.adapter_count = self.physical_count = self.buffer_count = self.execute_count = 0
        self.held = {}
        self.counts = dict.fromkeys(('issued', 'completion_accepts', 'successful', 'faults',
            'retirements', 'traps', 'fpr_writes', 'csr_mutations', 'pte_requests',
            'pte_responses', 'physical_requests', 'physical_responses'), 0)

    def check_fields(self, observed, expected, label):
        for key, value in expected.items():
            need(observed[key] == value, f'{label}.{key}: expected {value}, got {observed[key]}')

    def envelope(self):
        c, r = self.command, self.result
        return {'token_index': c['token_index'], 'token_tag': c['token_tag'],
            'data': r['data'], 'nextPc': c['pc'] + 4, 'exception': r['exception'],
            'cause': r['cause'], 'tval': r['tval'],
            **{'guestFault_' + k: r[k] for k in FAULT_WIDTHS}}

    def held_port(self, o, valid, ready, prefix, widths):
        value = {k: o[prefix + k] for k in widths}
        if valid in self.held:
            need(o[valid] and value == self.held[valid], 'held payload changed: ' + valid)
        if o[valid] and not ready: self.held[valid] = value
        else: self.held.pop(valid, None)

    def step(self, i, o, post, label):
        s, count = self.state, self.counts
        self.check_fields(o, s, 'pre ' + label)
        need(not i['mret'], 'M-origin outside frozen scope')
        idle = s['statePhase'] == 0
        complete = s['statePhase'] == 3 and not i['trap_valid']
        mask = sum(int(i[f'commit{n}_valid'] and
            i[f'commit{n}_bits_index'] == s['ownerToken_index'] and
            i[f'commit{n}_bits_tag'] == s['ownerToken_tag']) << n for n in range(2))
        ready = int(idle and not i['trap_valid'] and not i['status_valid'] and not i['csr_valid'])
        accepted = ready * i['start_valid']
        offered = int(complete and not s['completionSeen'])
        accepted_complete = offered * i['complete_ready']
        retired = int(bool(mask) and complete and self.command is not None)
        allowed = bool(s['hostFs'] and (not s['virtualized'] or s['guestFs']))
        csr_ready = int(idle and not i['trap_valid'] and not i['status_valid'])
        csr_illegal = int(i['csr_bits_address'] not in (1, 2, 3) or not allowed or i['csr_bits_operation'] == 3)
        csr_write = int(i['csr_valid'] and csr_ready and i['csr_bits_write'] and not csr_illegal)
        mutation = int(csr_write or retired and not self.result['exception'] and self.result['writes'])
        drained = int(not o['memoryBusy'] and not o['selectorBusy'] and o['adapterIdle'] and
                      o['translatorIdle'] and o['responseBufferIdle'] and o['completionCount'] == 0)
        replace = int(idle and not s['ownerActive'] and drained)
        self.check_fields(o, dict(start_ready=ready, issueAccepted=accepted, complete_valid=offered,
            completionAccepted=accepted_complete, stateCompleteValid=int(complete),
            retired=int(bool(mask)), retireMatches=mask, retireAccepted=retired,
            mutation_valid=mutation, csr_ready=csr_ready, csrIllegal=csr_illegal,
            csrRead={1: s['fcsr'] & 31, 2: s['fcsr'] >> 5, 3: s['fcsr']}.get(i['csr_bits_address'], 0),
            status_ready=replace, memoryDrained=drained, contextReplaceAllowed=replace,
            selectorBusy=o['memoryBusy'], selectorDomain=2 if s['ownerActive'] and self.owner_memory else 0,
            fpMemoryEpoch=int(s['ownerActive'] and self.owner_memory), hMemoryEpoch=0,
            contextMemoryEpoch=int(s['ownerActive'] and self.owner_memory),
            translationActive=int(bool(i['context_virtualized'] or i['context_effectivePrivilege'] != 3 and i['hostSatp'] >> 60)),
            executeValid=int(s['statePhase'] == 1 and not i['trap_valid'])), 'contract ' + label)
        if mutation:
            need(o['mutation_bits_guest'] == (s['virtualized'] if csr_write else self.guest), 'mutation owner mismatch')
        if self.command is not None:
            need(all(i['context_' + k] == value for k, value in self.context.items()), 'live translation context replaced')
            need(i['pmpTop'] == (1 << 54) - 1 and i['pmpPermission'] == 7 and not i['pmaDenied'], 'PMP/PMA context changed')
        self.held_port(o, 'complete_valid', i['complete_ready'], 'complete_bits_', COMPLETE_WIDTHS)
        self.held_port(o, 'pte_request_valid', i['pte_request_ready'], '', ('pte_request_bits',))
        self.held_port(o, 'physical_request_valid', i['physical_request_ready'], 'physical_request_bits_', REQUEST_WIDTHS)
        self.held_port(o, 'adapterResponse_valid', o['adapterResponseFire'], 'adapterResponse_bits_', RESPONSE_WIDTHS)
        self.held_port(o, 'bufferedResponse_valid', o['bufferedResponseFire'], 'bufferedResponse_bits_', RESPONSE_WIDTHS)
        if i['status_valid'] or i['csr_valid'] or i['sret']:
            need(replace and not i['trap_valid'] and not accepted, 'context write outside full FP lifecycle idle')
        need(not o['executeFire'] or o['executeValid'], 'execute fire without offer')
        if o['executeFire']:
            self.execute_count += 1
            need(self.command is not None and self.execute_count == 1 and self.result['cause'] != 2, 'denial execute or duplicate execution')
        if self.command is not None and self.result['cause'] == 2:
            need(not any(o[k] for k in ('executeValid', 'virtualRequest_valid', 'pte_request_valid',
                'physical_request_valid', 'adapterResponse_valid', 'pipelineComplete_valid')), 'denied instruction side effect')
        if o['virtualRequest_valid']:
            need(self.command is not None and self.result['address'] is not None and
                 not self.result['address'] & 7 and self.result['cause'] != 2, 'invalid virtual memory offer')
            self.check_fields(o, {'virtualRequest_bits_address': self.result['address'],
                'virtualRequest_bits_write': int(self.result['store']), 'virtualRequest_bits_size': 3,
                'virtualRequest_bits_mask': 255, 'virtualRequest_bits_atomic': 0}, 'virtual request')
        if o['adapterFire']:
            self.adapter_count += 1
            need(o['virtualRequest_valid'] and self.adapter_count == 1, 'duplicate adapter request')
        if o['pte_request_valid']:
            need(self.result is not None and self.adapter_count == 1 and self.pte_index < len(self.result['ptes']), 'unexpected PTE offer')
            need(o['pte_request_bits'] == self.result['ptes'][self.pte_index], 'independent PTE walk address mismatch')
            if i['pte_request_ready']:
                need(self.pte_pending is None, 'PTE request overwrote response owner')
                self.pte_pending = o['pte_request_bits']
                self.pte_index += 1
                count['pte_requests'] += 1
        if i['pte_response_valid']:
            need(self.pte_pending is not None, 'PTE response without request')
            need(i['pte_response_bits_data'] == self.ptes.get(self.pte_pending, 0) and not i['pte_response_bits_error'], 'PTE response not from physical image')
            if o['pte_response_ready']:
                self.pte_pending = None
                count['pte_responses'] += 1
        if o['physical_request_valid']:
            need(self.result is not None and not self.result['exception'] and self.result['physical'] is not None,
                 'final physical access for fault or move')
            r = self.result
            expected = dict.fromkeys(REQUEST_WIDTHS, 0)
            expected.update(address=r['physical'], size=3, mask=255, write=int(r['store']),
                            data=r['storeData'] if r['store'] else 0)
            # A load's unused request data is not an architectural input.
            if not r['store']: del expected['data']
            self.check_fields(o, prefixed('physical_request_bits_', expected), 'physical request')
            need(self.pte_index == len(r['ptes']) and self.pte_pending is None, 'physical request before walk drained')
            if i['physical_request_ready']:
                self.physical_count += 1
                need(self.physical_pending is None and self.physical_count == 1, 'duplicate physical access')
                self.physical_pending = sum(self.memory.get(r['physical'] + n, 0) << (8*n) for n in range(8))
                if r['store']:
                    for n in range(8): self.memory[r['physical'] + n] = (r['storeData'] >> (8*n)) & 255
                count['physical_requests'] += 1
        if i['physical_response_valid']:
            need(self.physical_pending is not None, 'physical response without owner')
            need(i['physical_response_bits_data'] == self.physical_pending and
                 not i['physical_response_bits_error'] and not i['physical_response_bits_pageFault'], 'physical response not from byte image')
            if o['physical_response_ready']:
                self.physical_pending = None
                count['physical_responses'] += 1
        if self.result is not None:
            r = self.result
            for prefix, fault_prefix in (('adapterResponse', 'adapterFault_'), ('bufferedResponse', 'bufferedFault_')):
                if o[prefix + '_valid']:
                    need(self.adapter_count == 1 and self.pte_index == len(r['ptes']) and self.pte_pending is None and self.physical_pending is None,
                         'response before real memory service drain')
                    self.check_fields(o, prefixed(fault_prefix, {key: r[key] for key in FAULT_WIDTHS}), prefix + ' provenance')
                    self.check_fields(o, {prefix + '_bits_error': r['exception'], prefix + '_bits_pageFault': 0}, prefix + ' status')
                    if not r['store']: need(o[prefix + '_bits_data'] == r['data'], prefix + ' byte data')
            if o['bufferedResponseFire']:
                self.buffer_count += 1
                need(self.buffer_count == 1, 'duplicate buffered response')
            if o['pipelineComplete_valid']:
                need(self.owner_memory and self.execute_count == 1, 'memory completion lacks command')
                self.check_fields(o, prefixed('pipelineComplete_bits_', self.envelope()), 'pipeline envelope')
            if o['convertedResult_valid']:
                need(s['statePhase'] == 2 and self.execute_count == 1, 'result without waiting instruction')
                need(o['pipelineComplete_valid'] if self.owner_memory else self.cycle == self.issue_cycle + 3,
                     'producer result timing/lifetime mismatch')
                expected = self.envelope(); expected['value'] = expected.pop('data'); expected.pop('nextPc'); expected['flags'] = 0
                self.check_fields(o, prefixed('convertedResult_bits_', expected), 'converted result')
            if complete:
                self.check_fields(o, prefixed('complete_bits_', self.envelope()), 'completion envelope')
                need(self.pte_index == len(r['ptes']) and self.pte_pending is None and self.physical_pending is None,
                     'completion before PTE/native drain')
                if r['address'] is not None and r['cause'] not in (2, 4):
                    need(self.adapter_count == self.buffer_count == 1, 'memory response path incomplete')
                if not r['exception'] and r['physical'] is not None: need(self.physical_count == 1, 'missing physical access')
        if accepted_complete:
            need(s['ownerActive'] and not s['completionSeen'], 'duplicate or unowned completion')
            s['completionSeen'] = 1
            count['completion_accepts'] += 1
            if self.result['exception']:
                need(drained, 'exception owner release before memory drain')
                s['ownerActive'] = 0
                count['faults'] += 1
            else: count['successful'] += 1
        if mask:
            need(not self.result or not self.result['exception'] or not s['busy'], 'fault token must never commit')
            s['ownerActive'] = 0
        if retired:
            need(s['completionSeen'] and not self.result['exception'], 'retirement before success acceptance')
            count['retirements'] += 1
            if self.result['writes']:
                s[f"fpr_{self.result['rd']}"] = self.result['data']
                count['fpr_writes'] += 1
            s['statePhase'] = 0
        elif i['trap_valid']:
            need(self.command is not None and self.result['exception'] and s['completionSeen'] and
                 not s['ownerActive'] and s['busy'] and drained and self.pte_pending is None and
                 self.physical_pending is None and not accepted and not mask and s['virtualized'],
                 'trap is not drained authorized VS fault consumption')
            expected = {k: self.result[k] for k in TRAP_WIDTHS if k != 'pc'}
            expected['pc'] = self.command['pc']
            self.check_fields(i, prefixed('trap_bits_', expected), 'external trap envelope')
            s['statePhase'], s['completionSeen'], s['virtualized'] = 0, 0, 0
            s['hstatus'] = (2 << 32) | 128 | 256 | (self.result['guestAddress'] << 6)
            s['htval'] = self.result['guestPhysicalAddress'] >> 2 if self.result['cause'] == 21 else 0
            count['traps'] += 1
        elif o['convertedResult_valid']:
            s['statePhase'] = 3
        elif o['executeFire']:
            s['statePhase'] = 2
        if i['status_valid']:
            address, data = i['status_bits_address'], i['status_bits_data']
            if address == 0x300 or address == 0x100 and not s['virtualized']: s['hostFs'] = (data >> 13) & 3
            if address == 0x200 or address == 0x100 and s['virtualized']: s['guestFs'] = (data >> 13) & 3
            if address == 0x600: s['hstatus'] = (2 << 32) | (data & (64 | 128 | 256 | 512 | 0x700000))
            need(address in (0x300, 0x200, 0x100, 0x600), 'unexpected setup CSR')
        if i['sret']:
            need(not s['virtualized'], 'guest SRET outside scope')
            s['virtualized'] = (s['hstatus'] >> 7) & 1
            s['hstatus'] &= ~128
        if csr_write:
            need(i['csr_bits_address'] == 3 and i['csr_bits_operation'] == 0, 'only frozen fcsr setup write')
            s['fcsr'] = i['csr_bits_value'] & 255
            count['csr_mutations'] += 1
        if mutation:
            s['hostFs'] = 3
            if o['mutation_bits_guest']: s['guestFs'] = 3
        if accepted:
            need(not o['ownerActive'] and drained, 'new command before prior full lifecycle drain')
            self.command = {key: i['start_bits_' + key] for key in START_WIDTHS}
            self.context = {key: i['context_' + key] for key in CONTEXT_WIDTHS}
            self.guest = s['virtualized']
            self.result = decode(self.command, s, self.memory, self.ptes, self.context)
            self.owner_memory = self.command['instruction'] & 127 in (7, 0x27)
            self.pte_index = self.adapter_count = self.physical_count = self.buffer_count = self.execute_count = 0
            self.issue_cycle = self.cycle
            s.update(statePhase=3 if self.result['cause'] == 2 else 1, completionSeen=0,
                ownerActive=1, ownerToken_index=self.command['token_index'], ownerToken_tag=self.command['token_tag'])
            count['issued'] += 1
        s['busy'] = int(s['statePhase'] != 0)
        s['hostSd'], s['guestSd'] = int(s['hostFs'] == 3), int(s['guestFs'] == 3)
        self.check_fields(post, s, 'post ' + label)
        if not s['busy']: self.command = self.result = self.context = None
        self.cycle += 1

MODE = 8 << 60
SEED = 0x7ff0123456789abc
LOADED = 0x400921fb54442d18
FAULT_COMMANDS = (3, 5, 7, 9)


def defaults():
    return {**dict.fromkeys(INPUT_WIDTHS, 0), 'csr_bits_address': 3,
        'statusReadAddress': 0x100, 'context_effectivePrivilege': 1,
        'context_size': 3, 'context_epoch': 81, 'pmpTop': (1 << 54) - 1, 'pmpPermission': 7}


def recipe():
    rows = []
    for n in range(11):
        row = defaults()
        row.update(start_valid=1, start_bits_token_index=5,
            start_bits_token_tag=0x135700000000007b ^ ((n + 1) << 33) ^ ((n & 1) << 63),
            start_bits_pc=0x80200000 + 4*n,
            start_bits_instruction=0xf2008053 if n == 0 else 0x0000b027 if n == 2 else 0xe2008153 if n >= 4 and n % 2 == 0 else 0x0000b087,
            start_bits_operand=SEED if n == 0 else 0x12345080 if n == 2 else 0x12345001 if n == 7 else 0x112345028 if n == 9 else 0x12345000)
        if n: row.update(context_virtualized=1, context_vsatp=0 if n == 9 else MODE | 0x100, context_hgatp=MODE | 0x200)
        rows.append(row)
    return rows


def initial_ptes():
    # Independent literal physical address calculation, not imported from C++.
    def leaf(address, permissions): return (address >> 12 << 10) | permissions
    table = {0x200000: leaf(0x40000000, 0x53),
             0x200010: leaf(0x406000, 1), 0x406000: leaf(0x407000, 1),
             0x407000: leaf(0xc0000000, 0xd7),
             0x200020: leaf(0x40c000, 1),
             0x40c000 + ((0x112345028 >> 21) & 511)*8: leaf(0x40d000, 1),
             0x40d000 + ((0x112345028 >> 12) & 511)*8: leaf(0x60005000, 0xc7),
             0x40100000: leaf(0x101000, 1),
             0x40101000 + ((0x12345000 >> 21) & 511)*8: leaf(0x102000, 1),
             0x40102000 + ((0x12345000 >> 12) & 511)*8: leaf(0x80000000, 0xc7)}
    return table


def initial_bytes():
    memory = {at: 0x91 + at % 23 for base in (0xc0000000, 0xc0000080) for at in range(base - 8, base + 16)}
    memory.update({0xc0000000 + n: (LOADED >> (8*n)) & 255 for n in range(8)})
    return memory


def image(memory): return [[key, value] for key, value in sorted(memory.items())]


def header(schedule):
    return {'type': 'header', 'schema': 1, 'component_only': True,
        'guest_fd_cpu_execution': False, 'real_fp_memory': True, 'external_trap_stimulus': True,
        'cycle_limit': CYCLE_LIMIT, 'schedule': schedule, 'recipe': recipe(),
        'ptes': image(initial_ptes()), 'bytes': image(initial_bytes())}


def planned_inputs(schedule, waits):
    need(schedule in SCHEDULES, 'unknown schedule')
    need(len(waits) == 11 and all(type(n) is int and 1 <= n <= 320 for n in waits), 'invalid bounded command waits')
    rows, context = [], defaults()
    stagger = schedule == 'staggered'
    def blank(): return {**defaults(), **{key: val for key, val in context.items() if key.startswith('context_')}}
    def add(label, **values): rows.append((label, {**blank(), **values}))
    def status(label, address, value): add(label, status_valid=1, status_bits_address=address, status_bits_data=value)
    def grant(n, lane):
        return {f'commit{lane}_valid': 1, f'commit{lane}_bits_index': 5,
                f'commit{lane}_bits_tag': recipe()[n]['start_bits_token_tag']}
    status('setup_host', 0x300, 2 << 13); status('setup_guest', 0x200, 2 << 13)
    add('setup_fcsr', csr_valid=1, csr_bits_write=1, csr_bits_value=0x75)
    for n, command in enumerate(recipe()):
        context = command
        prefix = f'op{n}_'
        add(prefix + 'context')
        status(prefix + 'host_fs', 0x300, (0 if n == 3 else 2) << 13)
        status(prefix + 'guest_fs', 0x200, (0 if n == 5 else 2) << 13)
        if n == 1 or n >= 4 and n % 2 == 0:
            status(prefix + 'spv', 0x600, 128); add(prefix + 'guest_enter', sret=1)
        add(prefix + 'issue', **command)
        for j in range(waits[n]): add(prefix + f'wait_{j}')
        for j in range(4 if stagger else 1): add(prefix + f'complete_hold_{j}')
        add(prefix + 'accept', complete_ready=1)
        if n in FAULT_COMMANDS:
            for j in range(6 if stagger else 3): add(prefix + f'fault_pending_{j}', start_valid=1, start_bits_instruction=0xe2008153)
            add(prefix + 'trap', trap_valid=1, trap_bits_pc=command['start_bits_pc'],
                trap_bits_cause=2 if n < 7 else 4 if n == 7 else 21,
                trap_bits_tval=0x0000b087 if n < 7 else command['start_bits_operand'],
                trap_bits_guestAddress=int(n >= 7), trap_bits_guestPhysicalAddress=0x112345028 if n == 9 else 0)
            add(prefix + 'flushed')
        else:
            for j in range(5 if stagger else 2): add(prefix + f'retire_hold_{j}', complete_ready=1)
            wrong = grant(n, 0); wrong['commit0_bits_tag'] ^= 1 << 63
            add(prefix + 'wrong_tag', **wrong)
            add(prefix + 'retire', **grant(n, n % 2))
        add(prefix + 'inactive_token', **grant(n, n % 2)); add(prefix + 'idle')
    add('final_idle')
    return rows


class Service:
    """Frozen external response scheduling, independently checked at every row."""
    def __init__(self, schedule):
        self.stagger = schedule == 'staggered'
        self.pending = {'pte': False, 'physical': False}
        self.held_offers = {'pte': 0, 'physical': 0}
        self.delay = {'pte': 0, 'physical': 0}
        self.data = {'pte': 0, 'physical': 0}
        self.memory = initial_bytes()

    def inputs(self, cycle):
        s = self.stagger
        fields = {port + '_request_ready': int(self.held_offers[port] >= (3 if s else 1))
                  for port in self.pending}
        for port in self.pending:
            fields[port + '_response_valid'] = int(self.pending[port] and self.delay[port] == 0)
            fields[port + '_response_bits_data'] = self.data[port]
        return fields

    def step(self, i, o):
        for port in self.pending:
            if o[port + '_request_valid'] and not i[port + '_request_ready']:
                self.held_offers[port] += 1
            if self.delay[port]: self.delay[port] -= 1
            if i[port + '_response_valid'] and o[port + '_response_ready']: self.pending[port] = False
            if o[port + '_request_valid'] and i[port + '_request_ready']:
                need(not self.pending[port], 'external service overwritten')
                self.held_offers[port] = 0
                self.pending[port] = True; self.delay[port] = 4 if self.stagger else 2
                if port == 'pte': self.data[port] = initial_ptes().get(o['pte_request_bits'], 0)
                else:
                    address = o['physical_request_bits_address'] & ~7
                    need(all(address + n in self.memory for n in range(8)), 'physical access outside frozen byte image')
                    self.data[port] = sum(self.memory[address + n] << (8*n) for n in range(8))
                    if o['physical_request_bits_write']:
                        for n in range(8):
                            if o['physical_request_bits_mask'] & (1 << n):
                                self.memory[address + n] = (o['physical_request_bits_data'] >> (8*n)) & 255


EXPECTED_COUNTS = {'issued': 11, 'completion_accepts': 11, 'successful': 7, 'faults': 4,
    'retirements': 7, 'traps': 4, 'fpr_writes': 2, 'csr_mutations': 1,
    'pte_requests': 21, 'pte_responses': 21, 'physical_requests': 2, 'physical_responses': 2}


def check_trace(path, schedule):
    lines = clean_text(path).splitlines()
    need(2 < len(lines) <= CYCLE_LIMIT + 2, 'raw cycle bound')
    exact(object_row(lines[0]), header(schedule), 'header')
    rows = [object_row(line) for line in lines[1:-1]]
    waits = [sum(row.get('phase', '').startswith(f'op{n}_wait_') for row in rows) for n in range(11)]
    plan = planned_inputs(schedule, waits)
    need(len(plan) == len(rows), 'raw cycle count mismatch')
    ledger, service = Replay(initial_ptes(), initial_bytes()), Service(schedule)
    for number, (row, (phase, stimulus)) in enumerate(zip(rows, plan)):
        keys(row, ('type', 'cycle', 'phase', 'in', 'pre', 'post'), 'cycle')
        exact([row['type'], row['cycle'], row['phase']], ['cycle', number, phase], 'cycle order')
        scalar_map(row['in'], INPUT_WIDTHS, 'in'); scalar_map(row['pre'], OUTPUT_WIDTHS, 'pre')
        scalar_map(row['post'], POST_WIDTHS, 'post')
        expected = {**stimulus, **service.inputs(number)}
        exact(row['in'], expected, 'frozen service and caller inputs ' + phase)
        if '_wait_' in phase:
            n, j = map(int, phase[2:].split('_wait_'))
            need(row['pre']['complete_valid'] == int(j == waits[n] - 1), 'wait must stop at first completion offer')
        ledger.step(row['in'], row['pre'], row['post'], phase)
        service.step(row['in'], row['pre'])
        if number + 1 < len(rows):
            need(type(rows[number + 1].get('pre')) is dict, 'missing next raw observation')
            exact(row['post'], {key: rows[number + 1]['pre'].get(key) for key in POST_WIDTHS}, 'linked post observation')
    need(not any(service.pending.values()) and not ledger.state['busy'] and not ledger.state['ownerActive'], 'final lifecycle not drained')
    exact(ledger.counts, EXPECTED_COUNTS, 'coverage')
    expected_memory = initial_bytes()
    expected_memory.update({0xc0000080 + n: (SEED >> (8*n)) & 255 for n in range(8)})
    exact(image(ledger.memory), image(expected_memory), 'store and neighbor-byte oracle')
    exact(image(service.memory), image(expected_memory), 'external memory final')
    exact(object_row(lines[-1]), {'type': 'footer', 'cycles': len(rows), 'complete': True,
                                'bytes': image(expected_memory)}, 'footer')
    need(ledger.state['fcsr'] == 0x75 and ledger.state['hostFs'] == ledger.state['guestFs'] == 2,
         'final fcsr and Clean status preservation')
    return rows

NEGATIVE_PHASES = {'denial_side_effect': 'op3_complete_hold_0',
    'wrong_cause': 'op7_complete_hold_0', 'wrong_tval': 'op7_complete_hold_0',
    'guest_metadata': 'op9_complete_hold_0', 'premature_owner_release': 'op1_complete_hold_0',
    'incomplete_release_drain': 'op9_accept', 'incomplete_trap_drain': 'op7_trap',
    'false_start_credit': 'op3_fault_pending_0', 'duplicate_completion': 'op3_fault_pending_0',
    'fault_mutation': 'op3_trap', 'recovery_readback': 'op4_complete_hold_0'}
NEGATIVES = tuple(NEGATIVE_PHASES)


def expected_summary(rows, schedule):
    return {'schema': 1, 'component_only': 1, 'guest_fd_cpu_execution': 0,
        'real_fp_memory': 1, 'external_trap_stimulus': 1,
        'issued': 11, 'completion_accepts': 11, 'successful': 7, 'exceptional': 4,
        'retirements': 7, 'traps': 4, 'recoveries': 4, 'fpr_writes': 2, 'mutations': 2,
        'pte_requests': 21, 'pte_responses': 21, 'physical_requests': 2, 'physical_responses': 2,
        'execute_accepts': 9, 'adapter_accepts': 3, 'buffer_responses': 3, 'pipeline_results': 4,
        'inactive_tokens': 11, 'cycles': len(rows),
        'held_pte': sum(r['pre']['pte_request_valid'] and not r['in']['pte_request_ready'] for r in rows),
        'held_physical': sum(r['pre']['physical_request_valid'] and not r['in']['physical_request_ready'] for r in rows),
        'fault_pending_cycles': 12 if schedule == 'baseline' else 24}


def check_positive(path, schedule, trace):
    lines = clean_text(path).splitlines()
    need(len(lines) == 1 and lines[0].startswith(MARKER + ' '), 'expected one exact summary only')
    summary = object_row(lines[0][len(MARKER) + 1:])
    rows = check_trace(trace, schedule)
    expected = expected_summary(rows, schedule)
    need(expected['held_pte'] == (21 if schedule == 'baseline' else 63) and
         expected['held_physical'] == (2 if schedule == 'baseline' else 6), 'external stall coverage differs')
    exact(summary, expected, 'summary')
    for field, expected_count in (('executeFire', 9), ('adapterFire', 3), ('bufferedResponseFire', 3), ('pipelineComplete_valid', 4)):
        need(sum(row['pre'][field] for row in rows) == expected_count, 'observed handshake coverage ' + field)
    return summary


def check_negative(path, name, returncode, trace):
    need(type(returncode) is int and returncode == 1, 'negative must exit exactly one')
    need(name in NEGATIVE_PHASES, 'unknown negative')
    rows = check_trace(trace, 'baseline')
    matches = [row for row in rows if row['phase'] == NEGATIVE_PHASES[name]]
    need(len(matches) == 1, 'negative target missing or duplicated')
    row = matches[0]
    need(clean_text(path) == f"GUARDED_FP_FAULT_CHECK[{name}] cycle={row['cycle']} phase={row['phase']}\n",
         'negative missed exact named checker')


def native_run(output, arguments, log_name, env):
    path = output / log_name
    with path.open('x') as log:
        result = subprocess.run([str(output / 'run'), *arguments], cwd=common.ROOT,
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=TIMEOUT)
    return path, result.returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=common.BUILD / 'guarded-fp-fault-recovery')
    args = parser.parse_args()
    need(not args.output.exists() and not args.output.is_symlink(), 'fresh output directory required')
    output = args.output.resolve()
    gsim, cxx = common.setup(False)
    os.environ['UBSAN_OPTIONS'] = 'halt_on_error=1'
    env = {**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0', 'UBSAN_OPTIONS': 'halt_on_error=1'}
    first_trace = output / 'raw-baseline.jsonl'
    built = common.test(gsim, cxx, str(output), 'ooo.GuardedFpFaultRecoveryGsimMain',
        'GuardedFpFaultRecoveryGsim', 'guarded_fp_fault_recovery.cpp',
        runtime_args=('--schedule', 'baseline', '--trace', str(first_trace)),
        sanitizer=True, cxx_flags=('-fbracket-depth=4096',), timeout=TIMEOUT,
        mill_module='IonSoC.guardedFpFaultRecovery')
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
        'real_fp_memory': True, 'external_trap_stimulus': True,
        'schedules': summaries, 'negatives': list(NEGATIVES)}
    with (output / 'entry-summary.json').open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(STANDARD_MARKER)


if __name__ == '__main__': main()
