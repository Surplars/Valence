#!/usr/bin/env python3
"""Denied-bare qualification filter, preserving the historical trusted-bare path.

This is a synthetic violation of the upstream ordinary-load PMP premise. It
tests the new qualification filter and older-external ordering, not a new bare
access-fault mechanism. Source preparation does not authorize a DUT invocation.
The first source suite, generated driver and API receipt remain immutable.
"""
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
import cases as base
from ports import INPUTS, REQUEST, REQUEST_WIDTHS, RESPONSE, PROOF, ROUTES

HERE, TASK, ROOT = base.HERE, base.TASK, base.ROOT
BASE, LIMIT = base.BASE, base.LIMIT
DENY_LOW, DENY_END = BASE + 0x200, BASE + 0x280
NAME = 'denied-bare-filter-retains-older-owner'
SCOPE = ('synthetic upstream-PMP-trust violation at actual registered bare path; '
         'qualification filtering and older-owner ordering only; no synthesized bare fault')
need, group, fields, side = base.need, base.group, base.fields, base.side
token, request, proof_for = base.token, base.request, base.proof_for


def permission(state, address, byte_count):
    """Evaluate only the explicit three-interval stimulus, not RTL decisions."""
    need(state['vmState.dataPrivilege'] == 1 and state['vmState.satp'] == 0,
         'DENIED_VM_PREMISE', 'supervisor bare context')
    cfg = [0, 0x0F, 0x08, 0x0F] + [0] * 12
    addr = [BASE // 4, DENY_LOW // 4, DENY_END // 4, LIMIT // 4] + [0] * 12
    need(all(state['pmpCfg.' + str(n)] == cfg[n] and
             state['pmpAddr.' + str(n)] == addr[n] for n in range(16)),
         'DENIED_TOR_LAYOUT', 'exact allowed / denied / allowed regions')
    accesses = set(range(address, address + byte_count))
    return bool(accesses) and all(BASE <= b < LIMIT and not DENY_LOW <= b < DENY_END
                                  for b in accesses)


def expected_physical(item, state):
    r = item['request']
    need(not any(r[n] for n in ['virtualized', 'precheckedLoad', 'atomic', 'uncached']),
         'BARE_REQUEST_PREMISE', item['id'])
    size = 1 << r['size']
    intended = set(range(r['address'], r['address'] + size))
    lanes = {(r['address'] & ~7) + n for n in range(8) if r['mask'] & (1 << n)}
    need(r['address'] % size == 0 and lanes == intended and
         BASE <= r['address'] and r['address'] + size <= LIMIT,
         'BARE_ALIGNED_APERTURE_SHAPE', item['id'])
    current_allowed = permission(state, r['address'], size)
    if item['id'] == 'older-posted-store':
        need(r['write'] and current_allowed and item['proof'] is not None,
             'POSTED_STORE_PERMISSION_PREMISE', item['id'])
    else:
        need(item['id'] == 'synthetic-denied-bare-read' and not r['write'] and
             r['address'] == BASE + 0x208 and not current_allowed and
             item['qualified'] == 1 and item['proof'] is None,
             'SYNTHETIC_DENIED_READ_PREMISE', item['id'])
    next_line = (r['address'] // 64 + 1) * 64
    hint = int(next_line // 4096 == r['address'] // 4096 and permission(state, next_line, 64))
    expected = {**r, 'precheckedLoad': 0, 'translationEpoch': 0,
                'prefetchNextAllowed': hint}
    qualified = int(bool(item['qualified'] and not r['write'] and
                         item['proof'] is None and current_allowed))
    proof = {**item['proof'], 'finalChecked': 1} if item['proof'] else None
    return expected, qualified, proof


class DeniedLedger(base.Ledger):
    """Reuse immutable owner/hold primitives, with an explicit denied-case oracle.

    No monkey-patching or substituted DUT samples. This observation method is
    local because the frozen baseline intentionally permits only its RWX region.
    All ownership still comes from public handshakes or authored completion.
    """
    def __init__(self):
        super().__init__()
        self.counts.update(denied_busy_samples=0, held_denied_samples=0,
                           denied_physical_handshakes=0)

    def observe(self, frame):
        i, a, offer = frame['input'], frame['actual'], frame['offer']
        self.complete_external(frame['external_complete'])
        need(bool(i['posted.externalBusy']) == bool(self.external),
             'EXTERNAL_BUSY_OWNER', 'only explicit completion clears accepted external responsibility')
        need(bool(i['posted.aggregateDrained']) == (not self.adapter_live() and not self.external),
             'AGGREGATE_DRAIN_OWNER', a['cycle'])
        need(bool(a['idle']) == (not self.adapter_live()), 'ADAPTER_IDLE_OWNER', a['cycle'])
        need(a['cycle'] > self.last_cycle, 'CYCLE_MONOTONIC', a['cycle'])
        self.last_cycle = a['cycle']
        context = {n: i[n] for n in INPUTS if n.startswith(('vmState.', 'pmpCfg.', 'pmpAddr.'))}
        if frame['phase'] == 'setup':
            need(not self.adapter_live() and not self.external and not i['virtual.request.valid'],
                 'SETUP_DRAIN_PREMISE', a['cycle'])
        else:
            if self.context is None:
                self.context = context
                self.expected_epoch = (a['posted.contextEpoch'], a['loadPrecheck.epoch'])
            need(context == self.context and not i['pmpRawChanged'] and not i['precheckFlush'] and
                 not a['posted.contextChanging'] and a['loadPrecheck.stable'],
                 'ACCEPTED_STABLE_CONTEXT', a['cycle'])
            need((a['posted.contextEpoch'], a['loadPrecheck.epoch']) == self.expected_epoch,
                 'ACCEPTED_STABLE_EPOCH', a['cycle'])
        need(not a['translation.request.valid'] and not a['translationPeek.request.valid'] and
             not a['loadPrecheck.response.valid'] and not a['canonicalStoreCertificate.valid'],
             'NO_UNEXPECTED_TRANSLATION_OR_CERTIFICATE', a['cycle'])
        need(not a['checkedFault'] and not a['pageFault'],
             'HISTORICAL_BARE_PATH_DOES_NOT_SYNTHESIZE_FAULT', a['cycle'])
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
        if 'synthetic-denied-bare-read' in self.accepted and self.external:
            need('synthetic-denied-bare-read' in self.pending and
                 not a['physical.request.valid'] and not a['physicalCollectionRead'] and
                 not a['checkedRead'] and not a['virtual.response.valid'] and not a['checkedDequeue'],
                 'DENIED_QUALIFICATION_CANNOT_BYPASS_OLDER_OWNER', a['cycle'])
            self.counts['denied_busy_samples'] += 1
        payload = None
        if a['physical.request.valid']:
            need(bool(old_pending), 'REGISTERED_PHYSICAL_OWNER', a['cycle'])
            item = self.accepted[old_pending[0]]
            expected, qualified, proof = expected_physical(item, i)
            actual = group(a, 'physical.request.bits', REQUEST)
            need(actual == expected, 'PHYSICAL_184BIT_PAYLOAD', {'actual': actual, 'expected': expected})
            need(a['physicalCollectionRead'] == qualified == 0,
                 'DENIED_OR_STORE_NEVER_QUALIFIED', item['id'])
            need(side(a, 'posted.requestProof', PROOF) == proof, 'PHYSICAL_POSTED_PROOF', item['id'])
            need(not self.external or proof is not None, 'OLDER_EXTERNAL_ORDER', item['id'])
            payload = {'request': actual, 'qualified': qualified, 'proof': proof}
            if item['id'] == 'synthetic-denied-bare-read':
                need(not self.external and self.counts['external_completions'] == 1,
                     'DENIED_PHYSICAL_ONLY_AFTER_REAL_COMPLETION', a['cycle'])
                if not i['physical.request.ready']:
                    self.counts['held_denied_samples'] += 1
            if pfire:
                h = actual['returnHandle']
                need(h not in self.physical, 'PHYSICAL_HANDLE_REUSE', h)
                self.physical[h] = {'id': item['id'], 'request': expected, 'proof': proof}
                self.pending.pop(0)
                self.counts['physical'] += 1
                if item['id'] == 'synthetic-denied-bare-read':
                    self.counts['denied_physical_handshakes'] += 1
                if proof:
                    t = token(proof)
                    need(t not in self.external and t not in self.completed, 'POSTED_TOKEN_REUSE', t)
                    self.external[t] = {'id': item['id'], 'responded': False}
        else:
            need(not a['physicalCollectionRead'] and not a['posted.requestProof.valid'],
                 'SIDECAR_WITHOUT_PHYSICAL_REQUEST', a['cycle'])
        self.hold('physical', a['physical.request.valid'], i['physical.request.ready'],
                  payload, 'HELD_PHYSICAL_REQUEST_AND_SIDECARS')
        need(bool(a['physicalRequest']) == pfire and bool(a['checkedDequeue']) == pfire,
             'PHYSICAL_HANDSHAKE_TAPS', a['cycle'])
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
            # Check the authored request against fixed PMP premises even while
            # denied and invisible at the physical port.
            expected_physical(offer, i)
            if offer['proof']:
                need(offer['proof'] == proof_for(offer['request'], a['posted.contextEpoch']),
                     'AUTHORED_POSTED_AUTHORITY_PREMISE', offer['id'])
            self.accepted[offer['id']] = copy.deepcopy(offer)
            self.pending.append(offer['id'])
            self.seen.add(offer['id'])
            self.counts['ingress'] += 1
        response = None
        owner = None
        if i['physical.response.valid']:
            response = group(i, 'physical.response.bits', RESPONSE)
            h = response['returnHandle']
            need(h in self.physical, 'PHYSICAL_RESPONSE_OWNER', h)
            owner = self.physical[h]
            need(response == frame['service'], 'AUTHORED_SERVICE_RESPONSE', response)
            need(a['physical.response.ready'] == i['virtual.response.ready'], 'RESPONSE_BACKPRESSURE', h)
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
            ident = owner['id']
            need(ident not in self.replied, 'RESPONSE_ONCE', ident)
            need(not response['error'] and not response['pageFault'],
                 'AUTHORED_SUCCESSFUL_PHYSICAL_SERVICE', ident)
            if owner['proof']:
                self.external[token(owner['proof'])]['responded'] = True
            self.replied.add(ident)
            del self.accepted[ident]
            del self.physical[response['returnHandle']]
            self.counts['physical_responses'] += 1
            self.counts['upstream_responses'] += 1


class Scenario(base.Scenario):
    # Only construction and setup differ. Immutable complete-frame transport,
    # authored offer/response helpers and process cleanup are inherited unchanged.
    def __init__(self, driver, out):
        self.out = out
        self.model = DeniedLedger()
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
                                     bufsize=1, preexec_fn=base.no_core_dump,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})

    def setup(self):
        self.raw({'reset': 1}, checked=False, phase='reset')
        self.raw({'reset': 1}, checked=False, phase='reset')
        self.raw({'reset': 0}, checked=False, phase='reset')
        a = self.raw({'vmState.dataPrivilege': 1,
                      'pmpCfg.1': 0x0F, 'pmpCfg.2': 0x08, 'pmpCfg.3': 0x0F,
                      'pmpAddr.0': BASE // 4, 'pmpAddr.1': DENY_LOW // 4,
                      'pmpAddr.2': DENY_END // 4, 'pmpAddr.3': LIMIT // 4,
                      'pmpRawChanged': 1, 'virtual.response.ready': 1,
                      'physical.request.ready': 1, 'translation.request.ready': 1}, phase='setup')
        need(a['posted.contextChanging'] and a['idle'], 'PUBLISHED_CONTEXT_CHANGE_PULSE', a['cycle'])
        stable = 0
        for _ in range(12):
            a = self.raw({'pmpRawChanged': 0}, phase='setup')
            good = (a['loadPrecheck.stable'] and not a['posted.contextChanging'] and
                    a['posted.contextEpoch'] == 1 and a['loadPrecheck.epoch'] == 1)
            stable = stable + 1 if good else 0
            if stable == 2:
                return a['posted.contextEpoch']
        raise base.Violation('STABLE_CONTEXT_EPOCH: did not observe epoch one stable twice')


def denied(s):
    epoch = s.setup()
    r = request(BASE + 0x80, 4, write=1, data=0xF1E2D3C4B5A69788)
    store = {'id': 'older-posted-store', 'request': r, 'qualified': 0, 'proof': proof_for(r, epoch)}
    s.offer(store)
    s.wait(lambda a: 4 in s.model.physical, 'POSTED_STORE_REACHES_PHYSICAL')
    s.response(4, 0x1020304050607080)
    s.tick()
    need(not s.model.adapter_live() and s.model.external[token(store['proof'])]['responded'],
         'REAL_POSTED_RETURN_RETAINS_EXTERNAL_OWNER', NAME)

    r = request(BASE + 0x208, 2, prefetchNextAllowed=1)
    read = {'id': 'synthetic-denied-bare-read', 'request': r, 'qualified': 1, 'proof': None}
    before = dict(s.model.routes)
    s.offer(read)
    a = s.wait(lambda a: read['id'] in s.model.accepted, 'DENIED_READ_ACCEPTED_INTO_REGISTERED_PATH')
    need(a['ingressPass'] and a['checkedEnqueue'] and not a['physical.request.valid'],
         'NONVACUOUS_DENIED_REGISTERED_INGRESS', a['cycle'])
    for _ in range(5):
        a = s.tick()
        need(s.state['physical.request.ready'] and s.state['posted.externalBusy'] and
             not a['physical.request.valid'] and not a['physicalCollectionRead'] and
             not a['checkedRead'] and not a['checkedFault'] and not a['virtual.response.valid'],
             'DENIED_READ_ORDERED_BEHIND_REAL_EXTERNAL_OWNER', a['cycle'])
    need(s.model.pending == [read['id']] and not s.model.physical and
         token(store['proof']) in s.model.external,
         'DENIED_ACCEPTED_OWNER_RETAINED', NAME)

    a = s.raw({'physical.request.ready': 0}, complete=[token(store['proof'])])
    need(a['physical.request.valid'] and not a['physicalCollectionRead'] and
         not a['checkedFault'] and not a['virtual.response.valid'],
         'HISTORICAL_BARE_REQUEST_AFTER_OLDER_DRAIN', a['cycle'])
    for _ in range(2):
        s.tick()
    a = s.tick(**{'physical.request.ready': 1})
    need(a['physical.request.valid'] and not a['physicalCollectionRead'] and 2 in s.model.physical,
         'DENIED_BARE_PHYSICAL_HANDSHAKE_ONCE', a['cycle'])
    s.response(2, 0xD15EA5ED01234567, held_cycles=2)
    for _ in range(3):
        a = s.tick()
        need(a['idle'] and not a['physical.request.valid'] and not a['virtual.response.valid'],
             'FINAL_IDLE_NO_DUPLICATES', a['cycle'])
    s.model.drained()
    need(s.model.routes['ingressPass'] - before['ingressPass'] == 1 and
         s.model.routes['checkedEnqueue'] - before['checkedEnqueue'] == 1 and
         s.model.routes['checkedDequeue'] - before['checkedDequeue'] == 1,
         'NONVACUOUS_DENIED_CHECKED_PATH', s.model.routes)
    need(s.model.counts['ingress'] == s.model.counts['physical'] ==
         s.model.counts['physical_responses'] == s.model.counts['upstream_responses'] == 2 and
         s.model.counts['external_completions'] == s.model.counts['denied_physical_handshakes'] == 1 and
         s.model.counts['denied_busy_samples'] >= 5 and s.model.counts['held_denied_samples'] >= 3 and
         s.model.counts['busy_read_handshakes'] == 0,
         'DENIED_EXACT_CARDINALITIES', s.model.counts)
    return {'name': NAME, 'status': 'PASS', 'cycles': s.cycles, 'scope': SCOPE,
            'counts': s.model.counts, 'route_taps': s.model.routes,
            'request_bits_compared': sum(REQUEST_WIDTHS.values()),
            'expected_witness': ['accepted permitted posted store and actual matching return',
                                 'separate retained external owner', 'accepted checked bare read',
                                 'no qualification, physical issue, or local fault while older owner remains',
                                 'explicit older completion', 'one nonqualified physical request and actual return'],
            'not_claimed': ['bare access-fault synthesis', 'CPU upstream permission correctness',
                            'translated/prechecked fault coverage', 'qualified identity/spill coverage',
                            'CPU/TLB/walker/cache/Home integration']}


def bindings(driver):
    paths = [Path(__file__).resolve(), HERE / 'API_RECEIPT.json']
    return base.bindings(driver) + [
        {'path': str(p), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in paths]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--case', choices=[NAME], required=True)
    args = parser.parse_args()
    base.resources_ok()
    need(args.out.resolve().is_relative_to(TASK.resolve()), 'OUTPUT_WITHIN_TASK_BUDGET', args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    result_path = args.out / (NAME + '.result.json')
    need(not result_path.exists(), 'PRESERVE_EXISTING_RESULT', result_path)
    source_bindings = bindings(args.driver)
    scenario = Scenario(args.driver, args.out)
    try:
        result = denied(scenario)
    finally:
        scenario.stop()
    need(scenario.child.returncode == 0, 'POSITIVE_DRIVER_EXIT', scenario.child.returncode)
    need(bindings(args.driver) == source_bindings, 'BOUND_SOURCES_UNCHANGED', NAME)
    base.resources_ok()
    result.update(driver_exit=scenario.child.returncode, bindings=source_bindings,
                  trace_bytes=scenario.trace_path.stat().st_size,
                  trace_format='gzip JSONL exact complete scalar input/output with authored events')
    result_path.write_text(json.dumps(result, indent=2) + '\n')
    print('CHECKED_TRANSLATION_CASE ' + NAME + ' PASS', flush=True)


if __name__ == '__main__':
    main()
