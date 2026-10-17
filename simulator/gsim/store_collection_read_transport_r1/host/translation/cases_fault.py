#!/usr/bin/env python3
"""One original translated-PMP fault placeholder behind a real external owner.

Use a valid Sv39 demand request and a separately accepted delayed successful
translation reply. Final physical PMP denial takes the original checkPhysical
fault path. No bare-fault, prechecked-certificate, CPU, TLB or walker claim.
Source preparation is not authority to execute the driver.
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
from ports import (INPUTS, REQUEST, REQUEST_WIDTHS, RESPONSE, PROOF, ROUTES,
                   TRANSLATION_REQUEST_WIDTHS, TRANSLATION_RESPONSE_WIDTHS)

HERE, TASK = base.HERE, base.TASK
BASE, LIMIT = base.BASE, base.LIMIT
DENY_LOW, DENY_END = BASE + 0x200, BASE + 0x280
VA, PA = 0x40000208, BASE + 0x208
SATP = (8 << 60) | (0x5A << 44) | 0x12345
NAME = 'translated-pmp-fault-retains-older-owner'
FAULT_ID = 'translated-read-pmp-fault'
SCOPE = ('actual delayed translated checkPhysical PMP fault placeholder and older-external ordering; '
         'authored translation service, no bare-fault/CPU/TLB/walker/cache/Home claim')
need, group, fields, side = base.need, base.group, base.fields, base.side
token, request, proof_for = base.token, base.request, base.proof_for
TRANSLATION_REPLY = {'physicalAddress': PA, 'pageFault': 0, 'accessFault': 0,
                     'level': 0, 'napot': 0, 'global': 0, 'pbmt': 0}
FAULT_REPLY = {'returnHandle': 2, 'data': 0, 'error': 1, 'pageFault': 0}


def permission(state, address, byte_count):
    need(state['vmState.dataPrivilege'] == 1 and state['vmState.satp'] == SATP and
         state['vmState.sum'] == state['vmState.mxr'] == 0,
         'SV39_CONTEXT_PREMISE', 'S-mode Sv39 ASID/root context')
    cfg = [0, 0x0F, 0x08, 0x0F] + [0] * 12
    addr = [BASE // 4, DENY_LOW // 4, DENY_END // 4, LIMIT // 4] + [0] * 12
    need(all(state['pmpCfg.' + str(n)] == cfg[n] and
             state['pmpAddr.' + str(n)] == addr[n] for n in range(16)),
         'FAULT_TOR_LAYOUT', 'exact allowed / denied / allowed regions')
    return byte_count > 0 and all(BASE <= b < LIMIT and not DENY_LOW <= b < DENY_END
                                  for b in range(address, address + byte_count))


def expected_store(item, state):
    r = item['request']
    need(item['id'] == 'older-posted-store' and r['write'] and
         not any(r[n] for n in ['virtualized', 'precheckedLoad', 'atomic', 'uncached']) and
         r['address'] == BASE + 0x80 and r['size'] == 3 and r['mask'] == 255 and
         permission(state, r['address'], 8), 'PERMITTED_POSTED_STORE_PREMISE', item['id'])
    next_line = (r['address'] // 64 + 1) * 64
    hint = int(next_line // 4096 == r['address'] // 4096 and permission(state, next_line, 64))
    return ({**r, 'precheckedLoad': 0, 'translationEpoch': 0, 'prefetchNextAllowed': hint},
            {**item['proof'], 'finalChecked': 1})


def expected_translation(item, state):
    r = item['request']
    need(item['id'] == FAULT_ID and r['address'] == VA and r['size'] == 3 and
         r['mask'] == 255 and r['virtualized'] == 1 and
         not any(r[n] for n in ['write', 'precheckedLoad', 'atomic', 'uncached']) and
         item['proof'] is None and item['qualified'] == 1 and VA % 8 == PA % 8 == 0 and
         VA % 4096 == PA % 4096 and not permission(state, PA, 8),
         'LEGAL_TRANSLATED_PMP_DENIED_PREMISE', item['id'])
    return dict(virtualAddress=VA, rootPpn=0x12345, asid=0x5A, mode=8,
                privilege=1, access=0, sum=0, mxr=0)


class FaultLedger(base.Ledger):
    def __init__(self):
        super().__init__()
        self.translation_pending = False
        self.translation_accepted_cycle = None
        self.translation_replied = False
        self.fault_visible_cycle = None
        self.local_reply_from = None
        self.counts.update(translation_requests=0, translation_responses=0,
                           fault_busy_samples=0, local_fault_allocations=0,
                           local_fault_responses=0, held_fault_samples=0)

    def drained(self):
        super().drained()
        need(not self.translation_pending, 'FINAL_TRANSLATION_OWNER_DRAIN', NAME)

    def observe(self, frame):
        i, a, offer = frame['input'], frame['actual'], frame['offer']
        old_external = bool(self.external)
        self.complete_external(frame['external_complete'])
        need(bool(i['posted.externalBusy']) == bool(self.external),
             'EXTERNAL_BUSY_OWNER', 'only explicit completion clears the actual posted responsibility')
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
        need(not a['translationPeek.request.valid'] and not a['loadPrecheck.response.valid'] and
             not a['canonicalStoreCertificate.valid'] and not a['pageFault'],
             'NO_UNEXPECTED_PEEK_CERTIFICATE_OR_PAGEFAULT', a['cycle'])
        need(not a['physicalCollectionRead'] and not a['checkedRead'],
             'VIRTUAL_SOURCE_EXCLUDED_FROM_QUALIFICATION', a['cycle'])
        old_pending = list(self.pending)
        ufire = bool(i['virtual.request.valid'] and a['virtual.request.ready'])
        pfire = bool(a['physical.request.valid'] and i['physical.request.ready'])
        rfire = bool(i['physical.response.valid'] and a['physical.response.ready'])
        vfire = bool(a['virtual.response.valid'] and i['virtual.response.ready'])
        tfire = bool(a['translation.request.valid'] and i['translation.request.ready'])
        trfire = bool(i['translation.response.valid'] and a['translation.response.ready'])
        if i['virtual.request.valid']:
            need(offer is not None and group(i, 'virtual.request.bits', REQUEST) == offer['request'],
                 'AUTHORED_INGRESS_REQUEST', a['cycle'])
            need(side(i, 'posted.upstreamProof', PROOF) == offer['proof'] and
                 i['collectionRead'] == offer['qualified'] and
                 not i['canonicalStoreOrigin.valid'] and not i['frozenStoreProof.valid'],
                 'AUTHORED_INGRESS_SIDECARS', a['cycle'])
        self.hold('ingress', i['virtual.request.valid'], a['virtual.request.ready'],
                  offer, 'HELD_INGRESS_REQUEST')

        translation = None
        if a['translation.request.valid']:
            need(FAULT_ID in self.accepted and not self.translation_replied,
                 'REGISTERED_TRANSLATION_REQUEST_OWNER', a['cycle'])
            translation = group(a, 'translation.request.bits', TRANSLATION_REQUEST_WIDTHS)
            need(translation == expected_translation(self.accepted[FAULT_ID], i),
                 'EXACT_TRANSLATION_VA_CONTEXT_ACCESS', translation)
            if tfire:
                need(not self.translation_pending, 'TRANSLATION_REQUEST_ONCE', a['cycle'])
                self.translation_pending = True
                self.translation_accepted_cycle = a['cycle']
                self.counts['translation_requests'] += 1
        self.hold('translation_request', a['translation.request.valid'], i['translation.request.ready'],
                  translation, 'HELD_TRANSLATION_REQUEST')
        if i['translation.response.valid']:
            need(self.translation_pending and self.translation_accepted_cycle < a['cycle'] and not tfire,
                 'DELAYED_REPLY_REQUIRES_ACCEPTED_TRANSLATION', a['cycle'])
            need(group(i, 'translation.response.bits', TRANSLATION_RESPONSE_WIDTHS) == TRANSLATION_REPLY,
                 'AUTHORED_SUCCESSFUL_TRANSLATION_REPLY', a['cycle'])
        self.hold('translation_response', i['translation.response.valid'], a['translation.response.ready'],
                  TRANSLATION_REPLY if i['translation.response.valid'] else None, 'HELD_TRANSLATION_REPLY')
        if trfire:
            need(not self.translation_replied, 'TRANSLATION_RESPONSE_ONCE', a['cycle'])
            self.translation_pending = False
            self.translation_replied = True
            self.counts['translation_responses'] += 1

        payload = None
        if a['physical.request.valid']:
            need(bool(old_pending), 'REGISTERED_PHYSICAL_OWNER', a['cycle'])
            item = self.accepted[old_pending[0]]
            need(item['id'] != FAULT_ID, 'FAULT_NEVER_ISSUES_PHYSICAL_REQUEST', a['cycle'])
            expected, proof = expected_store(item, i)
            actual = group(a, 'physical.request.bits', REQUEST)
            need(actual == expected, 'PHYSICAL_184BIT_PAYLOAD', {'actual': actual, 'expected': expected})
            need(side(a, 'posted.requestProof', PROOF) == proof, 'PHYSICAL_POSTED_PROOF', item['id'])
            payload = {'request': actual, 'qualified': 0, 'proof': proof}
            if pfire:
                h = actual['returnHandle']
                need(h not in self.physical, 'PHYSICAL_HANDLE_REUSE', h)
                self.physical[h] = {'id': item['id'], 'request': expected, 'proof': proof}
                self.pending.pop(0)
                self.counts['physical'] += 1
                t = token(proof)
                need(t not in self.external and t not in self.completed, 'POSTED_TOKEN_REUSE', t)
                self.external[t] = {'id': item['id'], 'responded': False}
        else:
            need(not a['posted.requestProof.valid'], 'PROOF_WITHOUT_PHYSICAL_REQUEST', a['cycle'])
        self.hold('physical', a['physical.request.valid'], i['physical.request.ready'],
                  payload, 'HELD_PHYSICAL_REQUEST_AND_SIDECARS')
        need(bool(a['physicalRequest']) == pfire, 'PHYSICAL_HANDSHAKE_TAP', a['cycle'])

        if a['checkedFault']:
            need(FAULT_ID in self.accepted and self.translation_replied,
                 'CHECKED_FAULT_HAS_ORIGINAL_TRANSLATED_OWNER', a['cycle'])
            if self.fault_visible_cycle is None:
                self.fault_visible_cycle = a['cycle']
            if self.external:
                need(not a['checkedDequeue'] and not a['physical.request.valid'] and
                     not a['virtual.response.valid'], 'FAULT_WAITS_FOR_REAL_OLDER_OWNER', a['cycle'])
                self.counts['fault_busy_samples'] += 1
        # The scenario completes the older owner only after a real fault head has
        # been observed. Ownership remains the accepted virtual ID until reply.
        # This passive checked tap verifies allocation timing, never creates it.
        allocate_fault = bool(frame['external_complete'])
        if allocate_fault:
            need(old_external and not self.external and not self.physical and
                 self.pending == [FAULT_ID] and self.translation_replied and
                 self.fault_visible_cycle is not None and self.fault_visible_cycle < a['cycle'] and
                 a['checkedFault'] and a['checkedDequeue'] and not a['physical.request.valid'] and
                 not a['virtual.response.valid'] and self.local_reply_from is None,
                 'FAULT_ALLOCATES_ONLY_AFTER_TRUE_OLDER_COMPLETION', a['cycle'])
            self.local_reply_from = a['cycle'] + 1
            self.counts['local_fault_allocations'] += 1
        need(bool(a['checkedDequeue']) == (pfire or allocate_fault),
             'CHECKED_STORE_OR_FAULT_DEQUEUE', a['cycle'])
        for name in ROUTES:
            self.routes[name] += a[name]
        if ufire:
            h = offer['request']['returnHandle']
            need(offer['id'] not in self.seen and
                 all(v['request']['returnHandle'] != h for v in self.accepted.values()),
                 'INGRESS_OWNER_ONCE', offer['id'])
            if offer['proof']:
                expected_store(offer, i)
                need(offer['proof'] == proof_for(offer['request'], a['posted.contextEpoch']),
                     'AUTHORED_POSTED_AUTHORITY_PREMISE', offer['id'])
            else:
                expected_translation(offer, i)
                need(offer['request']['translationEpoch'] == a['loadPrecheck.epoch'],
                     'AUTHORED_CURRENT_CONTEXT_EPOCH', a['cycle'])
            self.accepted[offer['id']] = copy.deepcopy(offer)
            self.pending.append(offer['id'])
            self.seen.add(offer['id'])
            self.counts['ingress'] += 1

        response = None
        owner = None
        local = (self.local_reply_from is not None and a['cycle'] >= self.local_reply_from and
                 FAULT_ID not in self.replied)
        if local:
            need(FAULT_ID in self.accepted and not i['physical.response.valid'] and
                 not a['physical.response.ready'] and not a['physical.request.valid'],
                 'FAULT_REPLY_HAS_NO_PHYSICAL_SERVICE', a['cycle'])
            response = FAULT_REPLY
            if not i['virtual.response.ready']:
                self.counts['held_fault_samples'] += 1
        elif i['physical.response.valid']:
            response = group(i, 'physical.response.bits', RESPONSE)
            h = response['returnHandle']
            need(h in self.physical and h == 4, 'PHYSICAL_RESPONSE_STORE_OWNER', h)
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
                  group(i, 'physical.response.bits', RESPONSE) if i['physical.response.valid'] else None,
                  'HELD_SERVICE_RESPONSE')
        self.hold('virtual_response', a['virtual.response.valid'], i['virtual.response.ready'],
                  response, 'HELD_UPSTREAM_RESPONSE')
        need(rfire == (vfire and not local), 'LOCAL_VERSUS_PHYSICAL_RESPONSE_TRANSFER', a['cycle'])
        if vfire:
            ident = FAULT_ID if local else owner['id']
            need(ident not in self.replied, 'RESPONSE_ONCE', ident)
            if local:
                need(self.pending == [FAULT_ID], 'FAULT_RETIRES_ITS_EXACT_ACCEPTED_OWNER', a['cycle'])
                self.pending.pop(0)
                self.counts['local_fault_responses'] += 1
            else:
                need(not response['error'] and not response['pageFault'], 'POSTED_SUCCESS_PREMISE', ident)
                self.external[token(owner['proof'])]['responded'] = True
                del self.physical[response['returnHandle']]
                self.counts['physical_responses'] += 1
            self.replied.add(ident)
            del self.accepted[ident]
            self.counts['upstream_responses'] += 1


class Scenario(base.Scenario):
    def __init__(self, driver, out):
        self.out = out
        self.model = FaultLedger()
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

    def raw(self, *args, **kwargs):
        a = super().raw(*args, **kwargs)
        if self.state['translation.response.valid'] and a['translation.response.ready']:
            self.state['translation.response.valid'] = 0
        return a

    def setup(self):
        self.raw({'reset': 1}, checked=False, phase='reset')
        self.raw({'reset': 1}, checked=False, phase='reset')
        self.raw({'reset': 0}, checked=False, phase='reset')
        a = self.raw({'vmState.dataPrivilege': 1, 'vmState.satp': SATP,
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


def fault(s):
    epoch = s.setup()
    r = request(BASE + 0x80, 4, write=1, data=0xF1E2D3C4B5A69788)
    store = {'id': 'older-posted-store', 'request': r, 'qualified': 0, 'proof': proof_for(r, epoch)}
    s.offer(store)
    s.wait(lambda a: 4 in s.model.physical, 'POSTED_STORE_REACHES_PHYSICAL')
    s.response(4, 0x1020304050607080)
    s.tick()
    need(not s.model.adapter_live() and s.model.external[token(store['proof'])]['responded'],
         'REAL_POSTED_RETURN_RETAINS_EXTERNAL_OWNER', NAME)

    before = dict(s.model.routes)
    r = request(VA, 2, virtualized=1, translationEpoch=epoch, prefetchNextAllowed=1)
    read = {'id': FAULT_ID, 'request': r, 'qualified': 1, 'proof': None}
    s.offer(read)
    s.wait(lambda a: s.model.translation_pending, 'ACTUAL_TRANSLATION_REQUEST_ACCEPTED')
    s.tick()  # Retain actual demand ownership before the separately authored reply.
    a = s.raw({'translation.response.valid': 1,
               **fields('translation.response.bits', TRANSLATION_REPLY)})
    need(a['translation.response.ready'] and s.model.translation_replied,
         'ACTUAL_DELAYED_TRANSLATION_REPLY_ACCEPTED', a['cycle'])
    s.wait(lambda a: bool(a['checkedFault']), 'ORIGINAL_TRANSLATED_PMP_FAULT_REACHES_CHECKED')
    for _ in range(4):
        a = s.tick()
        need(a['checkedFault'] and not a['checkedRead'] and not a['checkedDequeue'] and
             not a['physical.request.valid'] and not a['virtual.response.valid'] and
             s.state['posted.externalBusy'], 'HELD_FAULT_BEHIND_OLDER_OWNER', a['cycle'])
    need(s.model.routes['translatedEnqueue'] - before['translatedEnqueue'] == 1 and
         s.model.routes['translatedDequeue'] - before['translatedDequeue'] == 1 and
         s.model.routes['checkedEnqueue'] - before['checkedEnqueue'] == 1 and
         s.model.routes['ingressPass'] - before['ingressPass'] == 0 and
         s.model.routes['identityPass'] - before['identityPass'] == 0,
         'NONVACUOUS_ORIGINAL_TRANSLATED_CHECKPHYSICAL_PATH', s.model.routes)

    a = s.raw({'virtual.response.ready': 0}, complete=[token(store['proof'])])
    need(a['checkedDequeue'] and not a['physical.request.valid'] and not a['virtual.response.valid'],
         'FAULT_ALLOCATION_PRECEDES_LOCAL_REPLY', a['cycle'])
    for _ in range(3):
        a = s.tick()
        need(a['virtual.response.valid'] and not a['physical.response.ready'] and
             not a['physical.request.valid'], 'HELD_LOCAL_FAULT_RESPONSE', a['cycle'])
    a = s.tick(**{'virtual.response.ready': 1})
    need(a['virtual.response.valid'] and not a['physical.request.valid'],
         'LOCAL_FAULT_RETURN_ONCE', a['cycle'])
    for _ in range(3):
        a = s.tick()
        need(a['idle'] and not a['physical.request.valid'] and not a['virtual.response.valid'],
             'FINAL_IDLE_NO_DUPLICATES', a['cycle'])
    s.model.drained()
    c = s.model.counts
    need(c['ingress'] == c['upstream_responses'] == 2 and
         c['physical'] == c['physical_responses'] == c['external_completions'] == 1 and
         c['translation_requests'] == c['translation_responses'] == 1 and
         c['local_fault_allocations'] == c['local_fault_responses'] == 1 and
         c['fault_busy_samples'] >= 5 and c['held_fault_samples'] == 3,
         'FAULT_EXACT_CARDINALITIES', c)
    return {'name': NAME, 'status': 'PASS', 'cycles': s.cycles, 'scope': SCOPE,
            'counts': c, 'route_taps': s.model.routes, 'request_bits_compared': sum(REQUEST_WIDTHS.values()),
            'fault_placeholder': {'returnHandle': 2, 'checked_fault_first_cycle': s.model.fault_visible_cycle,
                                  'local_reply_first_cycle': s.model.local_reply_from,
                                  'physical_requests': 0, 'physical_service_responses': 0},
            'not_claimed': ['bare access-fault synthesis', 'prechecked certificate or stale epoch handling',
                            'qualified identity/spill coverage', 'real TLB/page-walker permission service',
                            'CPU/backend/cache/Home integration']}


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
        result = fault(scenario)
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
