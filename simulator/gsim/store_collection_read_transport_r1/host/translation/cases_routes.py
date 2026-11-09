#!/usr/bin/env python3
"""Qualified identity and translated-spill routing with real retained ownership.

Fill both checked slots, free one on the same edge as an ingress acceptance,
then use that registered vacancy for identity. Refill checked before forcing a
different request into translated storage. No new DUT or baseline-source edits.
This source file does not authorize a DUT run.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.dont_write_bytecode = True
import cases as base
from ports import INPUTS, REQUEST_WIDTHS

HERE, TASK, BASE = base.HERE, base.TASK, base.BASE
NAME = 'qualified-identity-spill-and-handle-reuse'
need, token, request, proof_for = base.need, base.token, base.request, base.proof_for
SCOPE = ('actual qualified bare identity and translated-queue spill routes; all read '
         'handshakes while a separately retained real posted external owner remains; '
         'no CPU/TLB/walker/cache/Home integration claim')


class RouteLedger(base.Ledger):
    """Unchanged baseline oracle plus public-handshake history and legal credits."""
    def __init__(self):
        super().__init__()
        self.ingress_history = []
        self.physical_history = []
        self.reply_history = []
        self.peak_physical_owners = 0
        self.max_integer_owners = 0

    def observe(self, frame):
        i, a = frame['input'], frame['actual']
        pfire = bool(a['physical.request.valid'] and i['physical.request.ready'])
        vfire = bool(a['virtual.response.valid'] and i['virtual.response.ready'])
        offered_owner = self.pending[0] if self.pending else None
        returning_owner = self.physical.get(i['physical.response.bits.returnHandle'])
        # This performs the full frozen oracle: accepted ownership, FIFO order,
        # all 184 bits, qualification/proof, held channels, returns and context.
        super().observe(frame)
        if i['virtual.request.valid'] and a['virtual.request.ready']:
            item = frame['offer']
            self.ingress_history.append({'id': item['id'], 'handle': item['request']['returnHandle'],
                                         'cycle': a['cycle']})
        if pfire:
            self.physical_history.append({'id': offered_owner,
                                          'handle': a['physical.request.bits.returnHandle'],
                                          'cycle': a['cycle'], 'qualified': a['physicalCollectionRead'],
                                          'external_busy': i['posted.externalBusy']})
        if vfire:
            need(returning_owner is not None, 'ROUTE_REPLY_PUBLIC_OWNER', a['cycle'])
            self.reply_history.append({'id': returning_owner['id'],
                                       'handle': a['virtual.response.bits.returnHandle'],
                                       'cycle': a['cycle']})
        need(set(self.physical) <= set(range(6)) and len(self.physical) <= 6,
             'SELECTED_SIX_LEGAL_HANDLES', list(self.physical))
        integer_count = len(set(self.physical) & set(range(4)))
        need(integer_count <= 4, 'FOUR_INTEGER_RETURN_CREDITS', integer_count)
        self.peak_physical_owners = max(self.peak_physical_owners, len(self.physical))
        self.max_integer_owners = max(self.max_integer_owners, integer_count)


class Scenario(base.Scenario):
    # The original stable RWX setup, transport, requests, response service,
    # process cleanup and complete scalar trace format are reused unchanged.
    def __init__(self, driver, out):
        self.out = out
        self.model = RouteLedger()
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


def read(ident, address, handle, size, mask, serial):
    r = request(address, handle, size=size, mask=mask, atomicOp=0x10 + serial,
                data=0xA0B0C0D000000000 + serial, translationEpoch=0x9ABC0000 + serial,
                prefetchNextAllowed=int(ident == 'E-reused-handle'))
    return {'id': ident, 'request': r, 'qualified': 1, 'proof': None}


def routes(s):
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
    witness = {}
    A = read('A-checked-head', BASE + 0x200, 0, 3, 0xFF, 1)
    B = read('B-checked-tail', BASE + 0x20C, 1, 2, 0xF0, 2)
    C = read('C-identity-read', BASE + 0x212, 2, 1, 0x0C, 3)
    D = read('D-translated-spill', BASE + 0x219, 3, 0, 0x02, 4)
    E = read('E-reused-handle', BASE + 0xFC8, 2, 3, 0xFF, 5)

    # Both checked entries are filled before the third read is offered.
    s.state['physical.request.ready'] = 0
    s.offer(A)
    a = s.tick()
    need(a['virtual.request.ready'] and a['ingressPass'] and a['checkedEnqueue'] and
         not a['physical.request.valid'], 'FIRST_CHECKED_SLOT_FILLED', a['cycle'])
    s.offer(B)
    a = s.tick()
    need(a['virtual.request.ready'] and a['ingressPass'] and a['checkedEnqueue'] and
         a['physical.request.valid'] and a['physical.request.bits.returnHandle'] == 0,
         'SECOND_CHECKED_SLOT_FILLED', a['cycle'])
    need(s.model.pending == [A['id'], B['id']] and not s.model.physical,
         'TWO_ACCEPTED_UNISSUED_CHECKED_OWNERS', s.model.pending)

    # checked.enq.ready is false while full even though A dequeues on this edge.
    # C must enter ingress now; the next cycle sees the newly available slot.
    s.offer(C)
    a = s.tick(**{'physical.request.ready': 1})
    need(a['virtual.request.ready'] and a['ingressQueued'] and not a['ingressPass'] and
         not a['identityPass'] and not a['checkedEnqueue'] and not a['translatedEnqueue'] and
         a['physicalRequest'] and a['physical.request.bits.returnHandle'] == 0,
         'C_QUEUED_AS_A_FREES_CHECKED_SLOT', a['cycle'])
    witness['C_ingress_cycle'] = a['cycle']
    a = s.tick(**{'physical.request.ready': 0})
    need(a['identityPass'] and a['checkedEnqueue'] and not a['translatedEnqueue'] and
         not a['ingressPass'] and not a['ingressQueued'] and
         a['physical.request.valid'] and a['physical.request.bits.returnHandle'] == 1 and
         a['physicalCollectionRead'] and s.state['posted.externalBusy'],
         'C_REAL_QUALIFIED_IDENTITY_TRANSFER', a['cycle'])
    witness['C_identity_checked_cycle'] = a['cycle']
    need(s.model.pending == [B['id'], C['id']] and set(s.model.physical) == {0},
         'IDENTITY_PRESERVES_FIFO_AND_OLDER_RESPONSE_OWNER', s.model.pending)

    # B and C occupy both checked entries. D is accepted into actual ingress,
    # then must spill to translated storage because no checked vacancy is made.
    s.offer(D)
    a = s.tick()
    need(a['virtual.request.ready'] and a['ingressQueued'] and not a['ingressPass'] and
         not a['checkedEnqueue'] and not a['translatedEnqueue'],
         'D_QUEUED_BEHIND_TWO_CHECKED_OWNERS', a['cycle'])
    witness['D_ingress_cycle'] = a['cycle']
    a = s.tick()
    need(a['translatedEnqueue'] and not a['translatedDequeue'] and not a['identityPass'] and
         not a['checkedEnqueue'] and a['physical.request.valid'] and
         a['physical.request.bits.returnHandle'] == 1 and a['physicalCollectionRead'],
         'D_REAL_TRANSLATED_SPILL_ENQUEUE', a['cycle'])
    witness['D_translated_enqueue_cycle'] = a['cycle']
    for _ in range(2):
        a = s.tick()
        need(not a['translatedDequeue'] and not a['checkedEnqueue'] and
             a['physical.request.valid'] and a['physical.request.bits.returnHandle'] == 1 and
             a['physicalCollectionRead'] and s.state['posted.externalBusy'],
             'B_HELD_WITH_C_CHECKED_AND_D_TRANSLATED', a['cycle'])

    a = s.tick(**{'physical.request.ready': 1})
    need(a['physicalRequest'] and a['physical.request.bits.returnHandle'] == 1 and
         not a['translatedDequeue'], 'B_DRAINS_BEFORE_TRANSLATED_HEAD', a['cycle'])
    a = s.tick()
    need(a['physicalRequest'] and a['physical.request.bits.returnHandle'] == 2 and
         a['translatedDequeue'] and a['checkedEnqueue'] and not a['identityPass'],
         'D_TRANSLATED_DEQUEUE_WHILE_OLDER_C_ISSUES', a['cycle'])
    witness['C_physical_cycle'] = a['cycle']
    witness['D_translated_dequeue_checked_cycle'] = a['cycle']
    a = s.tick()
    need(a['physicalRequest'] and a['physical.request.bits.returnHandle'] == 3 and
         a['physicalCollectionRead'] and s.state['posted.externalBusy'],
         'D_QUALIFIED_PHYSICAL_AFTER_REAL_SPILL', a['cycle'])
    witness['D_physical_cycle'] = a['cycle']
    need(set(s.model.physical) == {0, 1, 2, 3} and not s.model.pending,
         'FOUR_DISTINCT_INTEGER_RETURN_OWNERS', list(s.model.physical))

    # Actual returned ownership, not physical request acceptance, permits reuse.
    s.response(2, 0xC2C2C2C201234567, held_cycles=2)
    witness['C_actual_reply_cycle'] = s.cycles
    need(C['id'] in s.model.replied and C['id'] not in s.model.accepted and
         2 not in s.model.physical and set(s.model.physical) == {0, 1, 3},
         'HANDLE_TWO_FREED_ONLY_BY_ACTUAL_C_REPLY', list(s.model.physical))
    s.state['physical.request.ready'] = 0
    s.offer(E)
    a = s.tick()
    need(a['virtual.request.ready'] and a['ingressPass'] and a['checkedEnqueue'] and
         a['cycle'] > witness['C_actual_reply_cycle'], 'LEGAL_REUSE_AFTER_ACTUAL_REPLY', a['cycle'])
    witness['E_reused_ingress_cycle'] = a['cycle']
    for _ in range(2):
        a = s.tick()
        need(a['physical.request.valid'] and a['physical.request.bits.returnHandle'] == 2 and
             a['physical.request.bits.address'] == E['request']['address'] and
             not a['physical.request.bits.prefetchNextAllowed'] and a['physicalCollectionRead'] and
             s.state['posted.externalBusy'], 'REUSED_HANDLE_HAS_NEW_HELD_PAYLOAD', a['cycle'])
    a = s.tick(**{'physical.request.ready': 1})
    need(a['physicalRequest'] and a['physical.request.bits.returnHandle'] == 2 and
         s.model.physical[2]['id'] == E['id'], 'REUSED_HANDLE_NEW_PHYSICAL_OWNER', a['cycle'])
    witness['E_physical_cycle'] = a['cycle']
    s.response(2, 0xE2E2E2E276543210, held_cycles=1)
    witness['E_actual_reply_cycle'] = s.cycles
    s.response(0, 0xA0A0A0A098765432)
    s.response(3, 0xD3D3D3D3F0E1D2C3, held_cycles=1)
    witness['D_actual_reply_cycle'] = s.cycles
    s.response(1, 0xB1B1B1B111223344)
    s.tick(); s.tick()
    need(not s.model.adapter_live() and token(store['proof']) in s.model.external,
         'ALL_READ_REPLIES_STILL_RETAIN_OLDER_EXTERNAL_OWNER', NAME)
    s.raw(complete=[token(store['proof'])])
    for _ in range(3):
        a = s.tick()
        need(a['idle'] and not a['physical.request.valid'] and not a['virtual.response.valid'],
             'FINAL_IDLE_NO_DUPLICATES', a['cycle'])
    s.model.drained()

    read_routes = {n: s.model.routes[n] - before[n] for n in before}
    need(read_routes == {'ingressPass': 3, 'identityPass': 1, 'ingressQueued': 2,
                         'translatedEnqueue': 1, 'translatedDequeue': 1,
                         'checkedEnqueue': 5, 'checkedDequeue': 5},
         'EXACT_QUALIFIED_ROUTE_WITNESS', read_routes)
    need([x['id'] for x in s.model.physical_history] ==
         ['older-posted-store', A['id'], B['id'], C['id'], D['id'], E['id']],
         'EXACT_PHYSICAL_FIFO_ORDER', s.model.physical_history)
    need([x['id'] for x in s.model.reply_history] ==
         ['older-posted-store', C['id'], E['id'], A['id'], D['id'], B['id']],
         'EXACT_TAGGED_RETURN_AND_REUSE_ORDER', s.model.reply_history)
    need(all(x['qualified'] == x['external_busy'] == 1 for x in s.model.physical_history[1:]),
         'ALL_FIVE_READS_ACCEPT_WHILE_REAL_OLDER_BUSY', s.model.physical_history)
    c = s.model.counts
    need(c['ingress'] == c['physical'] == c['physical_responses'] == c['upstream_responses'] == 6 and
         c['external_completions'] == 1 and c['busy_read_handshakes'] == 5 and
         c['held_qualified_cycles'] >= 8 and s.model.peak_physical_owners == 4 and
         s.model.max_integer_owners == 4,
         'ROUTE_EXACT_CARDINALITIES_AND_CREDITS', c)
    return {'name': NAME, 'status': 'PASS', 'cycles': s.cycles, 'scope': SCOPE,
            'counts': c, 'route_taps': s.model.routes, 'read_route_taps': read_routes,
            'witness_cycles': witness, 'physical_order': s.model.physical_history,
            'reply_order': s.model.reply_history, 'ingress_order': s.model.ingress_history,
            'peak_physical_owners': s.model.peak_physical_owners,
            'request_bits_compared': sum(REQUEST_WIDTHS.values()),
            'not_claimed': ['exhaustion of all six legal handles', 'translation faults or real TLB service',
                            'CPU/backend minting/cache/Home integration']}


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
        result = routes(scenario)
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
