#!/usr/bin/env python3
"""One narrow checked-adapter oracle. Source preparation is not run approval.

The host authors requests, proof premises, PMP/VM state, service responses and
external completion events. DUT route taps are coverage only, never ownership.
No CPU, real store-proof minting, TLB, page walker, cache or Home is instantiated.
"""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import subprocess
import sys
sys.dont_write_bytecode = True
from ports import (INPUTS, OUTPUTS, INPUT_WIDTHS, OUTPUT_WIDTHS, REQUEST,
                   REQUEST_WIDTHS, RESPONSE, PROOF, ORIGIN, FROZEN, ROUTES)

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parent
BASE, BYTES = 0x80200000, 0x80000000
LIMIT = BASE + BYTES
NAME = 'posted-owner-held-physical-ingress-read'
TRACE_BUDGET = 128 * 1024
TASK_BUDGET = 16 * 1024 * 1024
FREE_FLOOR = 800 * 1024 * 1024
SCOPE = ('selected actual registered DataTranslationAdapter; authored proof/context '
         'and external memory responsibility; no CPU/TLB/walker/cache/Home claim')


class Violation(RuntimeError):
    pass


def need(ok, anchor, detail):
    if not ok:
        raise Violation(anchor + ': ' + str(detail))


def group(state, prefix, names):
    return {n: state[prefix + '.' + n] for n in names}


def fields(prefix, value):
    return {prefix + '.' + n: v for n, v in value.items()}


def side(state, prefix, names):
    return group(state, prefix + '.bits', names) if state[prefix + '.valid'] else None


def side_inputs(prefix, names, value):
    return {prefix + '.valid': int(value is not None),
            **fields(prefix + '.bits', value or dict.fromkeys(names, 0))}


def token(proof):
    return (proof['token.index'], proof['token.tag'])


def request(address, handle, **changes):
    r = dict.fromkeys(REQUEST, 0)
    r.update(address=address, returnHandle=handle, size=3, mask=255,
             atomicOp=0x15, data=0xCAFECAFE10293847, translationEpoch=0x31415926)
    r.update(changes)
    return r


def proof_for(r, epoch):
    return {'token.index': 9, 'token.tag': 0xFEDCBA9876543219, 'epoch': epoch,
            **{n: r[n] for n in ['address', 'data', 'mask', 'size']},
            'headAuthorized': 1, 'physicalPmpAllowed': 1, 'originalPhysical': 1,
            'integerOrigin': 1, 'legacyPostedAccepted': 1, 'finalChecked': 0}


def narrow_pmp_allows(state, address, byte_count, write=False):
    """Authored one-region TOR contract, deliberately no RTL PMP summaries."""
    need(state['vmState.dataPrivilege'] == 1 and state['vmState.satp'] == 0,
         'NARROW_VM_PREMISE', 'supervisor bare context required')
    need(state['pmpCfg.0'] == 0 and state['pmpAddr.0'] == BASE // 4 and
         state['pmpCfg.1'] == 0x0F and state['pmpAddr.1'] == LIMIT // 4 and
         all(state['pmpCfg.' + str(n)] == 0 and state['pmpAddr.' + str(n)] == 0
             for n in range(2, 16)), 'NARROW_TOR_PREMISE', 'exact authored RWX aperture')
    return BASE <= address and address + byte_count <= LIMIT


def expected_physical(item, state):
    r = item['request']
    need(not any(r[n] for n in ['virtualized', 'precheckedLoad', 'atomic', 'uncached']),
         'NARROW_REQUEST_PREMISE', item['id'])
    size = 1 << r['size']
    intended = set(range(r['address'], r['address'] + size))
    actual_lanes = {(r['address'] & ~7) + n for n in range(8) if r['mask'] & (1 << n)}
    shape = r['address'] % size == 0 and actual_lanes == intended
    allowed = narrow_pmp_allows(state, r['address'], size, bool(r['write']))
    need(shape and allowed, 'NARROW_ALLOWED_REQUEST', item['id'])
    next_line = (r['address'] // 64 + 1) * 64
    hint = int(next_line // 4096 == r['address'] // 4096 and
               narrow_pmp_allows(state, next_line, 64))
    # Both load and naturally aligned store next-line hints are enabled in this
    # exact profile. Incoming hint is deliberately zero and must be overwritten.
    physical = {**r, 'precheckedLoad': 0, 'translationEpoch': 0,
                'prefetchNextAllowed': hint}
    qualified = int(bool(item['qualified'] and not r['write'] and item['proof'] is None))
    proof = {**item['proof'], 'finalChecked': 1} if item['proof'] else None
    return physical, qualified, proof


class Ledger:
    """Track ingress ownership, pending FIFO, physical handles and external tokens.

    The first three views account for adapter work. External cache responsibility
    is a distinct environmental obligation and is never retired by a CPU reply.
    All views advance only from accepted public handshakes or authored completion.
    """
    def __init__(self):
        self.accepted = {}
        self.pending = []
        self.physical = {}
        self.external = {}
        self.completed = set()
        self.seen = set()
        self.replied = set()
        self.holds = {}
        self.routes = dict.fromkeys(ROUTES, 0)
        self.counts = dict.fromkeys(['ingress', 'physical', 'physical_responses',
                                    'upstream_responses', 'external_completions',
                                    'held_qualified_cycles', 'busy_read_handshakes'], 0)
        self.context = None
        self.expected_epoch = None
        self.last_cycle = 0

    def adapter_live(self):
        return bool(self.accepted)

    def drained(self):
        need(not (self.accepted or self.pending or self.physical or self.external or self.holds),
             'FINAL_OWNER_DRAIN', {'accepted': list(self.accepted), 'pending': self.pending,
                                   'physical': list(self.physical), 'external': list(self.external),
                                   'held': list(self.holds)})

    def hold(self, channel, valid, ready, payload, anchor):
        if channel in self.holds:
            need(valid and payload == self.holds[channel], anchor, channel)
        if valid and not ready:
            self.holds[channel] = copy.deepcopy(payload)
        else:
            self.holds.pop(channel, None)

    def complete_external(self, completions):
        for value in completions:
            t = tuple(value)
            need(t in self.external and self.external[t]['responded'],
                 'EXTERNAL_COMPLETION_OWNER', t)
            need(t not in self.completed, 'EXTERNAL_COMPLETE_ONCE', t)
            del self.external[t]
            self.completed.add(t)
            self.counts['external_completions'] += 1

    def observe(self, frame):
        i, a, offer = frame['input'], frame['actual'], frame['offer']
        self.complete_external(frame['external_complete'])
        need(bool(i['posted.externalBusy']) == bool(self.external),
             'EXTERNAL_BUSY_OWNER', 'only separately completed accepted posted owners may clear busy')
        need(bool(i['posted.aggregateDrained']) == (not self.adapter_live() and not self.external),
             'AGGREGATE_DRAIN_OWNER', a['cycle'])
        need(bool(a['idle']) == (not self.adapter_live()), 'ADAPTER_IDLE_OWNER', a['cycle'])
        need(a['cycle'] > self.last_cycle, 'CYCLE_MONOTONIC', a['cycle'])
        self.last_cycle = a['cycle']
        current_context = {n: i[n] for n in INPUTS if n.startswith(('vmState.', 'pmpCfg.', 'pmpAddr.'))}
        if frame['phase'] == 'setup':
            need(not self.adapter_live() and not self.external and not i['virtual.request.valid'],
                 'SETUP_DRAIN_PREMISE', a['cycle'])
        else:
            if self.context is None:
                self.context = current_context
                self.expected_epoch = (a['posted.contextEpoch'], a['loadPrecheck.epoch'])
            need(current_context == self.context and not i['pmpRawChanged'] and not i['precheckFlush'] and
                 not a['posted.contextChanging'] and a['loadPrecheck.stable'],
                 'ACCEPTED_STABLE_CONTEXT', a['cycle'])
            need((a['posted.contextEpoch'], a['loadPrecheck.epoch']) == self.expected_epoch,
                 'ACCEPTED_STABLE_EPOCH', a['cycle'])
        need(not a['translation.request.valid'] and not a['translationPeek.request.valid'] and
             not a['loadPrecheck.response.valid'] and not a['canonicalStoreCertificate.valid'],
             'NO_UNEXPECTED_TRANSLATION_OR_CERTIFICATE', a['cycle'])
        need(not a['checkedFault'] and not a['pageFault'], 'NO_NARROW_FAULT', a['cycle'])
        old_pending = list(self.pending)
        ufire = bool(i['virtual.request.valid'] and a['virtual.request.ready'])
        pfire = bool(a['physical.request.valid'] and i['physical.request.ready'])
        rfire = bool(i['physical.response.valid'] and a['physical.response.ready'])
        vfire = bool(a['virtual.response.valid'] and i['virtual.response.ready'])
        if i['virtual.request.valid']:
            need(offer is not None and group(i, 'virtual.request.bits', REQUEST) == offer['request'],
                 'AUTHORED_INGRESS_REQUEST', a['cycle'])
            need(side(i, 'posted.upstreamProof', PROOF) == offer['proof'] and
                 i['collectionRead'] == offer['qualified'] and
                 not i['canonicalStoreOrigin.valid'] and not i['frozenStoreProof.valid'],
                 'AUTHORED_INGRESS_SIDECARS', a['cycle'])
        self.hold('ingress', i['virtual.request.valid'], a['virtual.request.ready'],
                  offer, 'HELD_INGRESS_REQUEST')
        # A physical offer must belong to a previously accepted request. A same
        # cycle new ingress cannot satisfy this check: checked is registered.
        physical_payload = None
        if a['physical.request.valid']:
            need(bool(old_pending), 'REGISTERED_PHYSICAL_OWNER', a['cycle'])
            item = self.accepted[old_pending[0]]
            expected, qualified, proof = expected_physical(item, i)
            actual = group(a, 'physical.request.bits', REQUEST)
            need(actual == expected, 'PHYSICAL_184BIT_PAYLOAD', {'actual': actual, 'expected': expected})
            need(a['physicalCollectionRead'] == qualified, 'PHYSICAL_QUALIFICATION', item['id'])
            need(side(a, 'posted.requestProof', PROOF) == proof, 'PHYSICAL_POSTED_PROOF', item['id'])
            need(not self.external or qualified or proof is not None,
                 'OLDER_EXTERNAL_ORDER', item['id'])
            physical_payload = {'request': actual, 'qualified': qualified, 'proof': proof}
            if qualified and not i['physical.request.ready']:
                self.counts['held_qualified_cycles'] += 1
                need(bool(self.external), 'HELD_READ_RETAINS_OLDER_OWNER', item['id'])
            if pfire:
                h = actual['returnHandle']
                need(h not in self.physical, 'PHYSICAL_HANDLE_REUSE', h)
                self.physical[h] = {'id': item['id'], 'request': expected, 'proof': proof}
                self.pending.pop(0)
                self.counts['physical'] += 1
                if qualified and self.external:
                    self.counts['busy_read_handshakes'] += 1
                if proof:
                    t = token(proof)
                    need(t not in self.external and t not in self.completed, 'POSTED_TOKEN_REUSE', t)
                    self.external[t] = {'id': item['id'], 'responded': False}
        else:
            need(not a['physicalCollectionRead'] and not a['posted.requestProof.valid'],
                 'SIDECAR_WITHOUT_PHYSICAL_REQUEST', a['cycle'])
        self.hold('physical', a['physical.request.valid'], i['physical.request.ready'],
                  physical_payload, 'HELD_PHYSICAL_REQUEST_AND_SIDECARS')
        need(bool(a['physicalRequest']) == pfire and bool(a['checkedDequeue']) == pfire,
             'PHYSICAL_HANDSHAKE_TAPS', a['cycle'])
        # Route counts are passive coverage and cannot create any owner above.
        for name in ROUTES:
            self.routes[name] += a[name]
        if a['ingressPass']:
            need(ufire and a['checkedEnqueue'] and not a['ingressQueued'],
                 'PHYSICAL_INGRESS_ROUTE', a['cycle'])
        if ufire:
            h = offer['request']['returnHandle']
            need(offer['id'] not in self.seen and
                 all(v['request']['returnHandle'] != h for v in self.accepted.values()),
                 'INGRESS_OWNER_ONCE', offer['id'])
            if offer['proof']:
                need(offer['proof'] == proof_for(offer['request'], a['posted.contextEpoch']),
                     'AUTHORED_POSTED_AUTHORITY_PREMISE', offer['id'])
            self.accepted[offer['id']] = copy.deepcopy(offer)
            self.pending.append(offer['id'])
            self.seen.add(offer['id'])
            self.counts['ingress'] += 1
        response = None
        response_owner = None
        if i['physical.response.valid']:
            response = group(i, 'physical.response.bits', RESPONSE)
            h = response['returnHandle']
            need(h in self.physical, 'PHYSICAL_RESPONSE_OWNER', h)
            response_owner = self.physical[h]
            need(response == frame['service'], 'AUTHORED_SERVICE_RESPONSE', response)
            need(a['physical.response.ready'] == i['virtual.response.ready'],
                 'RESPONSE_BACKPRESSURE', h)
        need(bool(a['virtual.response.valid']) == (response is not None),
             'UPSTREAM_RESPONSE_VALID', a['cycle'])
        if response:
            actual = group(a, 'virtual.response.bits', RESPONSE)
            need(actual['returnHandle'] == response['returnHandle'], 'RESPONSE_EXACT_HANDLE', actual)
            need(actual['data'] == response['data'], 'RESPONSE_EXACT_DATA', actual)
            need(actual['error'] == response['error'] and actual['pageFault'] == response['pageFault'],
                 'RESPONSE_EXACT_STATUS', actual)
        self.hold('physical_response', i['physical.response.valid'], a['physical.response.ready'],
                  response, 'HELD_SERVICE_RESPONSE')
        self.hold('virtual_response', a['virtual.response.valid'], i['virtual.response.ready'],
                  response, 'HELD_UPSTREAM_RESPONSE')
        need(rfire == vfire, 'ONE_TO_ONE_RESPONSE_TRANSFER', a['cycle'])
        if rfire:
            ident = response_owner['id']
            need(ident not in self.replied, 'RESPONSE_ONCE', ident)
            if response_owner['proof']:
                need(not response['error'] and not response['pageFault'], 'POSTED_SUCCESS_PREMISE', ident)
                self.external[token(response_owner['proof'])]['responded'] = True
            self.replied.add(ident)
            del self.accepted[ident]
            del self.physical[response['returnHandle']]
            self.counts['physical_responses'] += 1
            self.counts['upstream_responses'] += 1


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def resources_ok():
    total = sum(p.stat().st_size for p in TASK.rglob('*') if p.is_file())
    fs = os.statvfs(TASK)
    need(total <= TASK_BUDGET and fs.f_bavail * fs.f_frsize >= FREE_FLOOR,
         'RESOURCE_LIMIT', {'task_bytes': total, 'free_bytes': fs.f_bavail * fs.f_frsize})


class Scenario:
    def __init__(self, driver, out):
        self.out = out
        self.model = Ledger()
        self.state = dict.fromkeys(INPUTS, 0)
        self.offer_item = self.service = None
        self.cycles = 0
        self.stderr_path = out / (NAME + '.stderr')
        self.stderr = self.stderr_path.open('x')
        self.trace_path = out / (NAME + '.jsonl.gz')
        need(not self.trace_path.exists(), 'PRESERVE_EXISTING_TRACE', self.trace_path)
        self.trace = gzip.open(self.trace_path, 'wt', encoding='utf-8', compresslevel=6)
        self.child = subprocess.Popen([str(driver.resolve())], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.stderr, text=True,
                                     bufsize=1, preexec_fn=no_core_dump,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})

    def raw(self, updates=None, *, checked=True, phase='active', complete=()):
        self.state.update(updates or {})
        remaining = set(self.model.external) - {tuple(t) for t in complete}
        self.state['posted.externalBusy'] = int(bool(remaining))
        self.state['posted.aggregateDrained'] = int(not self.model.adapter_live() and not remaining)
        need(set(self.state) == set(INPUTS) and
             all(isinstance(v, int) and 0 <= v < 1 << INPUT_WIDTHS[n] for n, v in self.state.items()),
             'INPUT_SCALAR_SCHEMA', self.state)
        wire = ' '.join(n + '=' + str(self.state[n]) for n in INPUTS)
        self.child.stdin.write(wire + '\n'); self.child.stdin.flush()
        selector = selectors.DefaultSelector()
        selector.register(self.child.stdout, selectors.EVENT_READ)
        ready = selector.select(timeout=10); selector.close()
        need(bool(ready), 'DRIVER_OBSERVATION_TIMEOUT', NAME)
        line = self.child.stdout.readline()
        need(bool(line), 'DRIVER_EXIT', self.child.poll())
        actual = json.loads(line)
        self.cycles += 1
        need(set(actual) == set(OUTPUTS) | {'cycle'} and actual['cycle'] == self.cycles and
             all(isinstance(actual[n], int) and 0 <= actual[n] < 1 << OUTPUT_WIDTHS[n] for n in OUTPUTS),
             'OUTPUT_SCALAR_SCHEMA', actual)
        frame = {'input': dict(self.state), 'actual': actual, 'wire_input': wire,
                 'wire_output': line.rstrip('\n'), 'checked': checked, 'phase': phase,
                 'offer': copy.deepcopy(self.offer_item), 'service': copy.deepcopy(self.service),
                 'external_complete': list(complete)}
        self.trace.write(json.dumps(frame, separators=(',', ':')) + '\n'); self.trace.flush()
        need(self.trace_path.stat().st_size <= TRACE_BUDGET, 'TRACE_BUDGET', self.trace_path)
        if checked:
            self.model.observe(frame)
            if self.state['virtual.request.valid'] and actual['virtual.request.ready']:
                self.state['virtual.request.valid'] = 0
                self.offer_item = None
                self.state.update(side_inputs('posted.upstreamProof', PROOF, None))
                self.state['collectionRead'] = 0
            if self.state['physical.response.valid'] and actual['physical.response.ready']:
                self.state['physical.response.valid'] = 0
                self.service = None
        return actual

    def tick(self, **updates):
        return self.raw(updates)

    def offer(self, item):
        need(not self.state['virtual.request.valid'], 'NO_OFFER_REPLACEMENT', item['id'])
        self.offer_item = copy.deepcopy(item)
        self.state.update({'virtual.request.valid': 1, 'collectionRead': item['qualified'],
                           **fields('virtual.request.bits', item['request']),
                           **side_inputs('posted.upstreamProof', PROOF, item['proof'])})

    def wait(self, predicate, anchor, limit=24):
        for _ in range(limit):
            a = self.tick()
            if predicate(a):
                return a
        raise Violation(anchor + ': bounded no-progress')

    def response(self, handle, data, *, held_cycles=0):
        need(handle in self.model.physical, 'SERVICE_STIMULUS_OWNER', handle)
        self.service = dict(returnHandle=handle, data=data, error=0, pageFault=0)
        self.state.update({'physical.response.valid': 1,
                           **fields('physical.response.bits', self.service)})
        for _ in range(held_cycles):
            a = self.tick(**{'virtual.response.ready': 0})
            need(a['virtual.response.valid'] and not a['physical.response.ready'],
                 'RESPONSE_STALL_OBSERVED', handle)
        a = self.tick(**{'virtual.response.ready': 1})
        need(a['physical.response.ready'] and a['virtual.response.valid'],
             'REAL_RESPONSE_HANDSHAKE', handle)

    def setup(self):
        self.raw({'reset': 1}, checked=False, phase='reset')
        self.raw({'reset': 1}, checked=False, phase='reset')
        self.raw({'reset': 0}, checked=False, phase='reset')
        a = self.raw({'vmState.dataPrivilege': 1, 'pmpCfg.1': 0x0F,
                      'pmpAddr.0': BASE // 4, 'pmpAddr.1': LIMIT // 4, 'pmpRawChanged': 1,
                      'virtual.response.ready': 1, 'physical.request.ready': 1,
                      'translation.request.ready': 1}, phase='setup')
        need(a['posted.contextChanging'] and a['idle'], 'PUBLISHED_CONTEXT_CHANGE_PULSE', a['cycle'])
        stable = 0
        for _ in range(12):
            a = self.raw({'pmpRawChanged': 0}, phase='setup')
            good = (a['loadPrecheck.stable'] and not a['posted.contextChanging'] and
                    a['posted.contextEpoch'] == 1 and a['loadPrecheck.epoch'] == 1)
            stable = stable + 1 if good else 0
            if stable == 2:
                return a['posted.contextEpoch']
        raise Violation('STABLE_CONTEXT_EPOCH: did not observe epoch one stable twice')

    def stop(self):
        if self.child.poll() is None:
            try:
                self.child.stdin.write('quit\n'); self.child.stdin.flush()
                self.child.wait(timeout=5)
            except (BrokenPipeError, subprocess.TimeoutExpired):
                self.child.kill(); self.child.wait(timeout=5)
        self.stderr.close(); self.trace.close()


def narrow(s):
    epoch = s.setup()
    store_req = request(BASE + 0x80, 4, write=1, data=0xFEDCBA9876543210)
    store = {'id': 'older-posted-store', 'request': store_req,
             'qualified': 0, 'proof': proof_for(store_req, epoch)}
    s.offer(store)
    s.wait(lambda a: 4 in s.model.physical, 'POSTED_STORE_REACHES_PHYSICAL')
    need(token(store['proof']) in s.model.external, 'EXTERNAL_OWNER_CREATED_FROM_REAL_STORE', NAME)
    s.response(4, 0x1020304050607080)
    s.tick()
    need(not s.model.adapter_live() and s.model.external[token(store['proof'])]['responded'],
         'REAL_REPLY_RETAINS_EXTERNAL_OWNER', NAME)

    read_req = request(BASE + 0x208, 2)
    read = {'id': 'qualified-bare-read', 'request': read_req, 'qualified': 1, 'proof': None}
    before = dict(s.model.routes)
    s.state['physical.request.ready'] = 0
    s.offer(read)
    s.wait(lambda a: bool(a['physical.request.valid']), 'QUALIFIED_READ_PROGRESS_WHILE_BUSY')
    for _ in range(3):
        a = s.tick()
        need(a['physical.request.valid'] and a['physicalCollectionRead'] and
             s.state['posted.externalBusy'], 'QUALIFIED_READ_HELD_WITH_OLDER_OWNER', a['cycle'])
    a = s.tick(**{'physical.request.ready': 1})
    need(a['physical.request.valid'] and a['physicalCollectionRead'] and
         2 in s.model.physical and s.state['posted.externalBusy'], 'BUSY_READ_ACCEPTED_ONCE', a['cycle'])
    s.response(2, 0xA5F0B6E1C7D29834, held_cycles=2)
    s.tick(); s.tick()
    need(token(store['proof']) in s.model.external and not s.model.adapter_live(),
         'READ_RETURN_DOES_NOT_CLEAR_OLDER_OWNER', NAME)
    need(s.model.routes['ingressPass'] - before['ingressPass'] == 1 and
         s.model.routes['checkedEnqueue'] - before['checkedEnqueue'] == 1 and
         s.model.routes['checkedDequeue'] - before['checkedDequeue'] == 1,
         'NONVACUOUS_REGISTERED_PHYSICAL_ROUTE', s.model.routes)
    # No busy shortcut: only this explicitly authored older completion clears it.
    s.raw(complete=[token(store['proof'])])
    for _ in range(3):
        a = s.tick()
        need(a['idle'] and not a['physical.request.valid'] and not a['virtual.response.valid'],
             'FINAL_IDLE_NO_DUPLICATES', a['cycle'])
    s.model.drained()
    need(s.model.counts['ingress'] == s.model.counts['physical'] ==
         s.model.counts['physical_responses'] == s.model.counts['upstream_responses'] == 2 and
         s.model.counts['external_completions'] == s.model.counts['busy_read_handshakes'] == 1 and
         s.model.counts['held_qualified_cycles'] >= 4,
         'NARROW_EXACT_CARDINALITIES', s.model.counts)
    return {'name': NAME, 'status': 'PASS', 'cycles': s.cycles,
            'counts': s.model.counts, 'route_taps': s.model.routes,
            'scope': SCOPE, 'request_bits_compared': sum(REQUEST_WIDTHS.values()),
            'not_exercised': ['read identity route and queued/spill route', 'denied bare filtering',
                              'actual translated/prechecked fault placeholders', 'response errors',
                              'OFF equivalence and full CPU/backend/cache/Home integration']}


def bindings(driver):
    paths = [HERE / n for n in ['ports.py', 'gen_driver.py', 'cases.py', 'ORACLE_PLAN.md', 'driver.cpp']]
    paths += [TASK / 'source/CollectionReadTranslationGsim.scala',
              TASK / 'translation-on/CollectionReadTranslationGsim.h',
              TASK / 'translation-on/actual-core.json',
              ROOT / 'store-full-line-progress-stagec-r1/source/DataTranslationAdapter.scala',
              ROOT / 'store-full-line-progress-stagec-r1/source/PostedCollectionRead.scala',
              ROOT / 'ethernet-mac-cpu-line275-r1/model/actual-combined-timing-repair-gsim.json', driver]
    return [{'path': str(p.resolve()), 'bytes': p.stat().st_size,
             'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--case', choices=[NAME], required=True)
    args = parser.parse_args()
    resources_ok()
    need(args.out.resolve().is_relative_to(TASK.resolve()), 'OUTPUT_WITHIN_TASK_BUDGET', args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    result_path = args.out / (NAME + '.result.json')
    need(not result_path.exists(), 'PRESERVE_EXISTING_RESULT', result_path)
    source_bindings = bindings(args.driver)
    scenario = Scenario(args.driver, args.out)
    try:
        result = narrow(scenario)
    finally:
        scenario.stop()
    need(scenario.child.returncode == 0, 'POSITIVE_DRIVER_EXIT', scenario.child.returncode)
    need(bindings(args.driver) == source_bindings, 'BOUND_SOURCES_UNCHANGED', NAME)
    resources_ok()
    result.update(driver_exit=scenario.child.returncode, bindings=source_bindings,
                  trace_bytes=scenario.trace_path.stat().st_size,
                  trace_format='gzip JSONL exact complete scalar input/output with authored events')
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print('CHECKED_TRANSLATION_CASE ' + NAME + ' PASS', flush=True)


if __name__ == '__main__':
    main()
