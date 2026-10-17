#!/usr/bin/env python3
"""Independent StoreBuffer boundary oracle; launches only an already-built driver.

Source preparation does not authorize execution. Qualification and memory service
are environmental premises, not observations of ROB, PMP, cache, Home, or DMA.
One complete scalar assignment line corresponds to one driver step/observation.
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
from ports import INPUTS, OUTPUTS, REQUEST, RESPONSE, PROOF, ORIGIN, FROZEN

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
ROOT = TASK.parent
BASE = 0x80200000
LIMIT = BASE + 0x80000000
TRACE_BUDGET = 512 * 1024
SCOPE = 'real StoreBuffer boundary, authored qualification and synthetic memory; no CPU/cache/Home/PMP integration claim'


class Violation(RuntimeError):
    pass


class DriverFailure(RuntimeError):
    pass


def need(ok, anchor, detail):
    if not ok:
        raise Violation(anchor + ': ' + str(detail))


def group(state, prefix, names):
    return {n: state[prefix + '.' + n] for n in names}


def fields(prefix, value):
    return {prefix + '.' + k: v for k, v in value.items()}


def sideband(state, prefix, names):
    return group(state, prefix + '.bits', names) if state[prefix + '.valid'] else None


def side_inputs(prefix, names, value):
    return {prefix + '.valid': int(value is not None),
            **fields(prefix + '.bits', value or dict.fromkeys(names, 0))}


def token(proof):
    return (proof['token.index'], proof['token.tag'])


def natural_mask(address, size):
    return sum(1 << ((address & 7) + b) for b in range(1 << size))


def request(address=BASE + 0x200, size=3, handle=0, **changes):
    value = dict.fromkeys(REQUEST, 0)
    value.update(address=address, size=size, returnHandle=handle,
                 mask=natural_mask(address, size), translationEpoch=0x31415926,
                 prefetchNextAllowed=1)
    value.update(changes)
    return value


def proof_for(req, serial):
    return {'token.index': serial % 16, 'token.tag': 0xD00D000000000000 + serial,
            'epoch': 0x89ABCDEF, **{n: req[n] for n in ['address', 'data', 'mask', 'size']},
            'headAuthorized': 1, 'physicalPmpAllowed': 1, 'originalPhysical': 1,
            'integerOrigin': 1, 'legacyPostedAccepted': 0, 'finalChecked': 0}


def is_buffered(item):
    r = item['request']
    return bool(r['write'] and not r['atomic'] and not r['virtualized'] and
                not r['precheckedLoad'] and item['frozen'] is None and
                BASE <= r['address'] and r['address'] + (1 << r['size']) <= LIMIT)


def byte_addresses(req):
    beat = req['address'] & ~7
    return {beat + lane for lane in range(8) if req['mask'] & (1 << lane)}


def qualified(item, stores):
    """Enumerate byte intents and outstanding ordering, independently of RTL nets."""
    r = item['request']
    if not item['qualified'] or item['proof'] or item['frozen']:
        return False
    if any(r[n] for n in ['write', 'atomic', 'virtualized', 'precheckedLoad', 'uncached']):
        return False
    if r['size'] not in range(4):
        return False
    width = 1 << r['size']
    intended = set(range(r['address'], r['address'] + width))
    if r['address'] % width or not (BASE <= r['address'] and r['address'] + width <= LIMIT):
        return False
    if byte_addresses(r) != intended or r['mask'] > 255:
        return False
    return all(s['issued'] and not (intended & byte_addresses(s['item']['request'])) for s in stores)


class Ledger:
    """Accepted request, external handle, upstream reply, and posted token ledgers.

    Synthetic byte memory changes only on an accepted matching memory response.
    A downstream posted obligation survives that response until its separately
    authored completion event. externalPostedBusy is derived only from that set.
    """
    def __init__(self):
        self.memory = {}
        self.stores = []
        self.direct = {}
        self.acks = []
        self.owners = {}
        self.external = {}
        self.seen = set()
        self.completed = set()
        self.tail = 0
        self.holds = {}
        self.counts = dict.fromkeys(['accepted_requests', 'memory_requests', 'memory_responses',
                                   'direct_responses', 'local_responses', 'posted_completions',
                                   'external_completions'], 0)
        self.reset_discards = []

    def word(self, address):
        beat = address & ~7
        return sum(self.memory.get(beat + b, ((beat + b) * 29 + 11) & 255) << (8*b) for b in range(8))

    def commit(self, item):
        r = item['request']
        if r['write']:
            address = item['frozen']['physicalAddress'] if item['frozen'] else r['address']
            for lane in range(8):
                if r['mask'] & (1 << lane):
                    self.memory[(address & ~7) + lane] = (r['data'] >> (lane*8)) & 255

    def complete_external(self, tokens):
        for t in tokens:
            t = tuple(t)
            need(t in self.external and self.external[t]['responded'],
                 'EXTERNAL_COMPLETION_OWNER', t)
            del self.external[t]
            self.counts['external_completions'] += 1

    def hold(self, name, valid, ready, payload, anchor):
        if name in self.holds:
            need(valid and payload == self.holds[name], anchor, name + ' changed or withdrew')
        if valid and not ready:
            self.holds[name] = copy.deepcopy(payload)
        else:
            self.holds.pop(name, None)

    def reset(self, up, fast, state):
        ids = sorted({s['item']['id'] for s in self.stores} |
                     {x['id'] for x in self.direct.values()} | {a['id'] for a in self.acks})
        self.reset_discards.append({'accepted_request_ids': ids,
                                   'memory_owner_handles': sorted(self.owners),
                                   'local_posted_tokens': [list(token(s['item']['proof'])) for s in self.stores if s['item']['proof']],
                                   'external_posted_tokens': [list(t) for t in self.external],
                                   'unaccepted_upstream_offer': up['id'] if up and state['upstream.request.valid'] else None,
                                   'unaccepted_fast_offer': fast['id'] if fast and state['fastStore.valid'] else None,
                                   'held_memory_response': bool(state['memory.response.valid']),
                                   'held_channels': sorted(self.holds)})
        # These are views of the same owners, not counts to add together.
        self.stores.clear(); self.direct.clear(); self.acks.clear(); self.owners.clear()
        self.external.clear(); self.holds.clear(); self.tail = 0

    def observe(self, frame):
        i, a, up, fast = frame['input'], frame['actual'], frame['upstream'], frame['fast']
        self.complete_external(frame.get('external_complete', []))
        need(bool(i['externalPostedBusy']) == bool(self.external), 'EXTERNAL_BUSY_OWNER',
             'busy must remain true until every accepted downstream posted obligation completes')
        need(bool(a['busy']) == bool(self.stores or self.direct or self.acks),
             'LOCAL_BUSY_OWNER', 'local busy disagrees with accepted unfinished requests')
        old_stores = copy.deepcopy(self.stores)
        old_memory_hold = self.holds.get('memory_request')
        ufire = bool(i['upstream.request.valid'] and a['upstream.request.ready'])
        ffire = bool(i['fastStore.valid'] and a['fastStore.ready'])
        mfire = bool(a['memory.request.valid'] and i['memory.request.ready'])
        rfire = bool(i['memory.response.valid'] and a['memory.response.ready'])
        need(not a['forwarded'], 'NO_UNPLANNED_LOCAL_FORWARD', 'suite requests real memory service')
        for name, item, valid, ready, names in [
                ('upstream', up, i['upstream.request.valid'], a['upstream.request.ready'], REQUEST),
                ('fast', fast, i['fastStore.valid'], a['fastStore.ready'], REQUEST[1:])]:
            prefix = 'upstream.request' if name == 'upstream' else 'fastStore'
            if valid:
                need(item is not None, 'AUTHORED_REQUEST', name)
                need(group(i, prefix + '.bits', names) == {n: item['request'][n] for n in names},
                     'AUTHORED_REQUEST_PAYLOAD', name)
                proof_prefix = 'upstreamProof' if name == 'upstream' else 'fastProof'
                need(sideband(i, proof_prefix, PROOF) == item['proof'], 'AUTHORED_PROOF', name)
                if name == 'upstream':
                    need(sideband(i, 'upstreamCanonicalStoreOrigin', ORIGIN) == item['canonical'] and
                         sideband(i, 'upstreamFrozenStoreProof', FROZEN) == item['frozen'] and
                         i['upstreamCollectionHeadRead'] == item['qualified'], 'AUTHORED_SIDECARS', name)
            self.hold(name, valid, ready, item, 'ENV_HELD_REQUEST')
        self.hold('memory_response_input', i['memory.response.valid'], a['memory.response.ready'],
                  group(i, 'memory.response.bits', RESPONSE), 'ENV_HELD_RESPONSE')

        # Acceptance is determined by genuine handshakes, never valid alone.
        for item, accepted, fast_path in [(up, ufire, False), (fast, ffire, True)]:
            if not accepted:
                continue
            need(item['id'] not in self.seen, 'ACCEPT_REQUEST_ONCE', item['id'])
            self.seen.add(item['id']); self.counts['accepted_requests'] += 1
            if fast_path or is_buffered(item):
                need(len(self.stores) < 2, 'STORE_CAPACITY', item['id'])
                if fast_path:
                    p = item['proof']
                    need(p is not None and all(p[n] for n in ['headAuthorized', 'physicalPmpAllowed', 'originalPhysical', 'integerOrigin']) and
                         not p['legacyPostedAccepted'] and not p['finalChecked'], 'FAST_PROOF_PREMISE', item['id'])
                self.stores.append({'item': copy.deepcopy(item), 'slot': self.tail, 'issued': False})
                self.tail = (self.tail + 1) % 2
                if not fast_path:
                    self.acks.append({'id': item['id'], 'returnHandle': item['request']['returnHandle'],
                                      'data': 0, 'error': 0, 'pageFault': 0})
            else:
                h = item['request']['returnHandle']
                need(h not in self.direct, 'DIRECT_HANDLE_REUSE', h)
                self.direct[h] = copy.deepcopy(item)

        if a['memory.request.valid']:
            actual_request = group(a, 'memory.request.bits', REQUEST)
            h = actual_request['returnHandle']
            is_store = h in (4, 5)
            if is_store:
                candidates = [s for s in self.stores if not s['issued']]
                need(bool(candidates), 'MEMORY_STORE_OWNER', h)
                entry = candidates[0]; item = entry['item']
                expected_request = {**item['request'], 'returnHandle': 4 + entry['slot']}
                expected_proof = {**item['proof'], 'legacyPostedAccepted': 1} if item['proof'] else None
                expected_canonical = expected_frozen = None
                expected_qualified = 0
            else:
                need(up is not None and i['upstream.request.valid'] and not is_buffered(up),
                     'MEMORY_DIRECT_OWNER', h)
                item = up; expected_request = item['request']
                expected_proof = item['proof']; expected_canonical = item['canonical']; expected_frozen = item['frozen']
                expected_qualified = old_memory_hold['qualified'] if old_memory_hold else int(qualified(item, old_stores))
            need(actual_request == expected_request, 'MEMORY_REQUEST_PAYLOAD',
                 {'actual': actual_request, 'expected': expected_request})
            if old_memory_hold:
                need(a['memoryCollectionHeadRead'] == old_memory_hold['qualified'],
                     'HELD_COLLECTION_QUALIFICATION', 'held direct qualification changed')
            need(a['memoryCollectionHeadRead'] == expected_qualified,
                 'COLLECTION_READ_ELIGIBILITY', item['id'])
            need(sideband(a, 'memoryProof', PROOF) == expected_proof, 'MEMORY_POSTED_PROOF', item['id'])
            need(sideband(a, 'memoryCanonicalStoreOrigin', ORIGIN) == expected_canonical and
                 sideband(a, 'memoryFrozenStoreProof', FROZEN) == expected_frozen,
                 'MEMORY_DIRECT_SIDECARS', item['id'])
            memory_payload = {'request': actual_request, 'proof': expected_proof,
                              'canonical': expected_canonical, 'frozen': expected_frozen,
                              'qualified': a['memoryCollectionHeadRead']}
            if mfire:
                need(h not in self.owners and len(self.owners) < 5, 'MEMORY_OWNER_CREDIT', h)
                need(is_store or ufire, 'DIRECT_ACCEPTANCE_HANDSHAKE', h)
                self.owners[h] = {'item': copy.deepcopy(item), 'store': is_store,
                                  'request': copy.deepcopy(expected_request)}
                self.counts['memory_requests'] += 1
                if is_store:
                    entry['issued'] = True
                    if item['proof']:
                        t = token(item['proof'])
                        need(t not in self.external and t not in self.completed, 'POSTED_TOKEN_REUSE', t)
                        self.external[t] = {'responded': False, 'item': copy.deepcopy(item)}
        else:
            memory_payload = None
            need(not a['memoryCollectionHeadRead'], 'QUALIFICATION_WITHOUT_REQUEST', a['cycle'])
        self.hold('memory_request', a['memory.request.valid'], i['memory.request.ready'],
                  memory_payload, 'HELD_MEMORY_REQUEST')
        if ufire and not is_buffered(up):
            need(mfire and a['memory.request.bits.returnHandle'] == up['request']['returnHandle'],
                 'DIRECT_ACCEPTANCE_HANDSHAKE', up['id'])

        response_owner = None
        if i['memory.response.valid']:
            h = i['memory.response.bits.returnHandle']
            need(h in self.owners, 'MEMORY_RESPONSE_OWNER', h)
            response_owner = self.owners[h]
            if response_owner['store']:
                need(self.stores and 4 + self.stores[0]['slot'] == h and self.stores[0]['issued'],
                     'ORDERED_STORE_RESPONSE', h)
                need(not i['memory.response.bits.error'] and not i['memory.response.bits.pageFault'],
                     'GUARANTEED_STORE_SUCCESS_PREMISE', h)
                need(a['memory.response.ready'], 'STORE_RESPONSE_READY', h)
            else:
                need(h in self.direct, 'DIRECT_RESPONSE_OWNER', h)
                need(not self.acks, 'SCENARIO_RESPONSE_COLLISION', h)
                need(bool(a['memory.response.ready']) == bool(i['upstream.response.ready']),
                     'DIRECT_RESPONSE_BACKPRESSURE', h)
        expected_response = None
        if self.acks:
            expected_response = {n: self.acks[0][n] for n in RESPONSE}
        elif response_owner and not response_owner['store']:
            expected_response = group(i, 'memory.response.bits', RESPONSE)
        need(bool(a['upstream.response.valid']) == (expected_response is not None),
             'UPSTREAM_RESPONSE_VALID', a['cycle'])
        if expected_response:
            actual_response = group(a, 'upstream.response.bits', RESPONSE)
            need(actual_response['returnHandle'] == expected_response['returnHandle'],
                 'DIRECT_RESPONSE_HANDLE', actual_response)
            need(actual_response['data'] == expected_response['data'], 'DIRECT_RESPONSE_DATA', actual_response)
            need(all(actual_response[n] == expected_response[n] for n in ['error', 'pageFault']),
                 'DIRECT_RESPONSE_STATUS', actual_response)
        else:
            actual_response = None
        self.hold('upstream_response', a['upstream.response.valid'], i['upstream.response.ready'],
                  actual_response, 'HELD_UPSTREAM_RESPONSE')
        completion = None
        if rfire and response_owner['store'] and response_owner['item']['proof']:
            completion = token(response_owner['item']['proof'])
        need(bool(a['postedCompleted.valid']) == (completion is not None),
             'POSTED_COMPLETION_VALID', a['cycle'])
        if completion is not None:
            actual_token = (a['postedCompleted.bits.index'], a['postedCompleted.bits.tag'])
            need(actual_token == completion and completion not in self.completed,
                 'POSTED_COMPLETION_TOKEN', {'actual': actual_token, 'expected': completion})
            self.completed.add(completion); self.counts['posted_completions'] += 1
        if a['upstream.response.valid'] and i['upstream.response.ready']:
            if self.acks:
                self.acks.pop(0); self.counts['local_responses'] += 1
            else:
                need(rfire, 'DIRECT_RESPONSE_TRANSFER', expected_response)
                del self.direct[expected_response['returnHandle']]
                self.counts['direct_responses'] += 1
        if rfire:
            self.counts['memory_responses'] += 1
            if not i['memory.response.bits.error'] and not i['memory.response.bits.pageFault']:
                self.commit(response_owner['item'])
            if response_owner['store']:
                self.stores.pop(0)
                if response_owner['item']['proof']:
                    self.external[token(response_owner['item']['proof'])]['responded'] = True
            del self.owners[i['memory.response.bits.returnHandle']]

    def drained(self):
        need(not (self.stores or self.direct or self.acks or self.owners or self.external or self.holds),
             'FINAL_OWNER_DRAIN', {'stores': len(self.stores), 'direct': list(self.direct),
                                   'owners': list(self.owners), 'external': list(self.external), 'holds': list(self.holds)})


def no_core_dump():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class Scenario:
    def __init__(self, driver, out, name):
        self.name, self.out = name, Path(out)
        self.stderr_path = self.out / (name + '.stderr')
        self.stderr = self.stderr_path.open('w')
        self.trace = gzip.open(self.out / (name + '.jsonl.gz'), 'wt', encoding='utf-8', compresslevel=6)
        self.child = subprocess.Popen([str(Path(driver).resolve())], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1,
                                     preexec_fn=no_core_dump,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        self.model = Ledger(); self.serial = 0; self.cycles = 0
        self.state = dict.fromkeys(INPUTS, 0); self.up = self.fast = None
        self.raw({'reset': 1}, checked=False); self.raw({'reset': 1}, checked=False)
        self.raw({'reset': 0}, checked=False)
        self.state.update({'upstream.response.ready': 1, 'memory.request.ready': 1})

    def item(self, req=None, *, posted=False, qualified_read=1, canonical=False, frozen=False):
        self.serial += 1
        req = request() if req is None else req
        origin = {'token.index': self.serial % 16, 'token.tag': 0xCA11000000000000 + self.serial,
                  'epoch': 0x7ABCDEF0} if canonical else None
        frozen_proof = {'address': req['address'], 'physicalAddress': BASE + 0x1000 + (req['address'] & 4095),
                        'size': req['size'], 'mask': req['mask']} if frozen else None
        return {'id': self.serial, 'request': req, 'qualified': qualified_read,
                'proof': proof_for(req, self.serial) if posted else None,
                'canonical': origin, 'frozen': frozen_proof}

    def store(self, address=BASE, size=3, value=0xFEDCBA9876543210):
        data = (value & ((1 << (8 << size)) - 1)) << (8 * (address & 7))
        return self.item(request(address, size, write=1, data=data), posted=True, qualified_read=0)

    def offer(self, item, fast=False):
        if fast:
            need(not self.state['fastStore.valid'], 'ENV_REPLACE_OFFER', 'fast')
            self.fast = item
            self.state.update({'fastStore.valid': 1, **fields('fastStore.bits', {n: item['request'][n] for n in REQUEST[1:]}),
                               **side_inputs('fastProof', PROOF, item['proof'])})
        else:
            need(not self.state['upstream.request.valid'], 'ENV_REPLACE_OFFER', 'upstream')
            self.up = item
            self.state.update({'upstream.request.valid': 1, **fields('upstream.request.bits', item['request']),
                               'upstreamCollectionHeadRead': item['qualified'],
                               **side_inputs('upstreamProof', PROOF, item['proof']),
                               **side_inputs('upstreamCanonicalStoreOrigin', ORIGIN, item['canonical']),
                               **side_inputs('upstreamFrozenStoreProof', FROZEN, item['frozen'])})

    def raw(self, updates=None, *, checked=True, external_complete=(), reset_event=None):
        self.state.update(updates or {})
        need(set(self.state) == set(INPUTS) and all(isinstance(v, int) and 0 <= v < 2**64 for v in self.state.values()),
             'SCALAR_PROTOCOL', 'every field must be a declared unsigned scalar <=64 bits')
        wire = ' '.join(k + '=' + str(v) for k, v in self.state.items())
        try:
            self.child.stdin.write(wire + '\n'); self.child.stdin.flush()
        except BrokenPipeError:
            pass
        selector = selectors.DefaultSelector(); selector.register(self.child.stdout, selectors.EVENT_READ)
        available = selector.select(timeout=10); selector.close()
        if not available:
            raise DriverFailure('DRIVER_OBSERVATION_TIMEOUT: ' + self.name)
        line = self.child.stdout.readline()
        if not line:
            code = self.child.wait(timeout=5); self.stderr.flush()
            self.trace.write(json.dumps({'input': dict(self.state), 'wire_input': wire,
                                         'wire_output': None, 'actual': None, 'checked': False,
                                         'upstream': self.up, 'fast': self.fast,
                                         'driver_exit': code}, separators=(',', ':')) + '\n')
            self.trace.flush()
            raise DriverFailure(f'DRIVER_EXIT {code}: ' + self.stderr_path.read_text())
        try:
            actual = json.loads(line)
        except json.JSONDecodeError as error:
            raise DriverFailure('DRIVER_NON_JSON: ' + line) from error
        self.cycles += 1
        need(set(actual) == set(OUTPUTS) | {'cycle'}, 'DRIVER_OUTPUT_SCHEMA', sorted(actual))
        frame = {'input': dict(self.state), 'actual': actual, 'wire_input': wire, 'wire_output': line.rstrip('\n'),
                 'upstream': copy.deepcopy(self.up), 'fast': copy.deepcopy(self.fast), 'checked': checked,
                 'external_complete': list(external_complete), 'reset_event': reset_event}
        self.trace.write(json.dumps(frame, separators=(',', ':')) + '\n'); self.trace.flush()
        need(sum(p.stat().st_size for p in self.out.glob('*.jsonl.gz')) <= TRACE_BUDGET,
             'TRACE_BUDGET', 'compressed raw input/output traces exceeded 512 KiB')
        if checked:
            self.model.observe(frame)
            if self.state['upstream.request.valid'] and actual['upstream.request.ready']:
                self.state['upstream.request.valid'] = 0; self.up = None
            if self.state['fastStore.valid'] and actual['fastStore.ready']:
                self.state['fastStore.valid'] = 0; self.fast = None
            if self.state['memory.response.valid'] and actual['memory.response.ready']:
                self.state['memory.response.valid'] = 0
        return actual

    def tick(self, *, up=None, fast=None, complete=(), **updates):
        if up is not None: self.offer(up)
        if fast is not None: self.offer(fast, fast=True)
        # Events are independently authored, and logged for replay before this sample.
        remaining = set(self.model.external) - {tuple(t) for t in complete}
        updates['externalPostedBusy'] = int(bool(remaining))
        return self.raw(updates, external_complete=complete)

    def respond(self, handle, *, hold=0, error=0, page_fault=0):
        need(handle in self.model.owners, 'RESPONSE_STIMULUS_OWNER', handle)
        owner = self.model.owners[handle]; r = owner['item']['request']
        data = 0 if r['write'] else self.model.word(r['address'])
        payload = {'memory.response.valid': 1, **fields('memory.response.bits',
                   {'returnHandle': handle, 'data': data, 'error': error, 'pageFault': page_fault})}
        for _ in range(hold):
            a = self.tick(**{**payload, 'upstream.response.ready': 0})
            need(not a['memory.response.ready'], 'HELD_RESPONSE_PREMISE', self.name)
        a = self.tick(**{**payload, 'upstream.response.ready': 1})
        need(a['memory.response.ready'], 'RESPONSE_HANDSHAKE', handle)
        return a

    def seed_external(self):
        item = self.store(BASE + 0x80)
        a = self.tick(fast=item, **{'memory.request.ready': 1})
        need(a['fastStore.ready'] and a['memory.request.valid'], 'SEED_POSTED_ACCEPTANCE', self.name)
        self.respond(a['memory.request.bits.returnHandle'])
        need(token(item['proof']) in self.model.external, 'EXTERNAL_OBLIGATION_REMAINS', self.name)
        return item

    def reset_all(self):
        record = {'upstream': copy.deepcopy(self.up), 'fast': copy.deepcopy(self.fast), 'input': dict(self.state)}
        self.model.reset(self.up, self.fast, self.state)
        self.state = dict.fromkeys(INPUTS, 0); self.up = self.fast = None
        self.raw({'reset': 1}, checked=False, reset_event=record)
        self.raw({'reset': 1}, checked=False); self.raw({'reset': 0}, checked=False)
        self.state.update({'upstream.response.ready': 1, 'memory.request.ready': 1})

    def stop(self):
        if self.child.poll() is None:
            try: self.child.stdin.write('quit\n'); self.child.stdin.flush()
            except BrokenPipeError: pass
            self.child.wait(timeout=5)
        self.stderr.close(); self.trace.close()

    def finish(self):
        need(not self.state['upstream.request.valid'] and not self.state['fastStore.valid'] and not self.state['memory.response.valid'],
             'FINAL_OFFER_DRAIN', self.name)
        self.model.drained()
        a = self.tick()
        need(not a['busy'] and not a['upstream.response.valid'] and not a['memory.request.valid'] and not a['postedCompleted.valid'],
             'FINAL_IDLE', self.name)
        self.stop()
        need(self.child.returncode == 0, 'POSITIVE_DRIVER_EXIT', self.child.returncode)
        return {'name': self.name, 'status': 'PASS', 'cycles': self.cycles, 'driver_exit': self.child.returncode,
                'counts': self.model.counts, 'reset_discarded': self.model.reset_discards}


def case_held_smoke(s):
    older = s.seed_external()
    read = s.item(request(handle=2))
    a = s.tick(up=read, **{'memory.request.ready': 0})
    need(a['memory.request.valid'] and a['memoryCollectionHeadRead'] and not a['upstream.request.ready'],
         'HELD_COLLECTION_OFFER', s.name)
    younger = s.store(BASE + 0x100, value=0x0123456789ABCDEF)
    a = s.tick(fast=younger)
    need(a['fastStore.ready'] and a['memoryCollectionHeadRead'], 'FAST_ENQUEUE_DURING_HELD_READ', s.name)
    s.tick(); s.tick()
    a = s.tick(**{'memory.request.ready': 1})
    need(a['upstream.request.ready'] and a['memoryCollectionHeadRead'], 'HELD_READ_ACCEPT_ONCE', s.name)
    a = s.tick()
    need(a['memory.request.valid'] and not a['memoryCollectionHeadRead'], 'YOUNGER_STORE_DRAINS_AFTER_HELD', s.name)
    s.respond(a['memory.request.bits.returnHandle'])
    s.respond(2, hold=2)
    s.tick(complete=[token(younger['proof'])])
    s.tick(complete=[token(older['proof'])])


def case_held_lanes(s):
    older = s.seed_external()
    for handle in range(4):
        for size in range(4):
            for lane in range(0, 8, 1 << size):
                read = s.item(request(BASE + 0x200 + lane, size, handle))
                a = s.tick(up=read, **{'memory.request.ready': 0})
                need(a['memory.request.valid'] and a['memoryCollectionHeadRead'] and not a['upstream.request.ready'],
                     'HELD_COLLECTION_OFFER', [handle, size, lane])
                younger = s.store(BASE + 0x100, value=0x1020304050607080 + s.serial)
                a = s.tick(fast=younger)
                need(a['fastStore.ready'] and a['memoryCollectionHeadRead'], 'FAST_ENQUEUE_DURING_HELD_READ', s.serial)
                s.tick(); s.tick()
                a = s.tick(**{'memory.request.ready': 1})
                need(a['upstream.request.ready'] and a['memoryCollectionHeadRead'], 'HELD_READ_ACCEPT_ONCE', s.serial)
                a = s.tick()
                need(a['memory.request.valid'] and not a['memoryCollectionHeadRead'], 'YOUNGER_STORE_DRAINS_AFTER_HELD', s.serial)
                s.respond(a['memory.request.bits.returnHandle'])
                s.respond(handle, hold=2)
                s.tick(complete=[token(younger['proof'])])
    s.tick(complete=[token(older['proof'])])


def case_unissued(s):
    store = s.store()
    s.tick(fast=store, **{'memory.request.ready': 0})
    read = s.item(request())
    a = s.tick(up=read)
    need(not a['upstream.request.ready'] and not a['memoryCollectionHeadRead'], 'UNISSUED_STORE_BLOCKS', s.name)
    a = s.tick(**{'memory.request.ready': 1})
    need(not a['upstream.request.ready'], 'UNISSUED_STORE_BLOCKS', s.name)
    sh = a['memory.request.bits.returnHandle']
    a = s.tick()
    need(a['upstream.request.ready'] and a['memoryCollectionHeadRead'], 'ISSUED_DISJOINT_READ_PROGRESS', s.name)
    s.respond(0); s.respond(sh); s.tick(complete=[token(store['proof'])])


def case_byte_overlap(s):
    store = s.store(BASE + 0x200, size=0, value=0xA7)
    a = s.tick(fast=store); sh = a['memory.request.bits.returnHandle']
    a = s.tick(up=s.item(request(BASE + 0x201, size=0, handle=1)))
    need(a['upstream.request.ready'] and a['memoryCollectionHeadRead'], 'DISJOINT_BYTE_SAME_BEAT', s.name)
    s.respond(1)
    a = s.tick(up=s.item(request(BASE + 0x200, size=0, handle=2)))
    need(not a['upstream.request.ready'] and not a['memory.request.valid'], 'OVERLAP_BYTE_BLOCKS', s.name)
    s.tick(); s.respond(sh)
    a = s.tick()
    need(a['upstream.request.ready'] and a['memoryCollectionHeadRead'], 'OVERLAP_DRAINS_THEN_READS', s.name)
    need(s.model.word(BASE + 0x200) & 255 == 0xA7, 'STORE_BYTE_COMMIT', s.name)
    s.respond(2, hold=1); s.tick(complete=[token(store['proof'])])


def case_fast_overlap(s):
    older = s.seed_external(); younger = s.store(BASE + 0x200, size=1, value=0xB6C7)
    a = s.tick(up=s.item(request(BASE + 0x200, size=1)), fast=younger)
    need(a['fastStore.ready'] and not a['upstream.request.ready'] and not a['memory.request.valid'],
         'FAST_OVERLAP_BLOCKS_NEW_DIRECT', s.name)
    a = s.tick(); sh = a['memory.request.bits.returnHandle']
    need(a['memory.request.valid'] and not a['memoryCollectionHeadRead'], 'FAST_OVERLAP_DRAIN', s.name)
    a = s.tick(); need(not a['upstream.request.ready'], 'FAST_OVERLAP_REMAINS_BLOCKED', s.name)
    s.respond(sh)
    a = s.tick(); need(a['upstream.request.ready'], 'FAST_OVERLAP_COMPLETED_READ', s.name)
    s.respond(0); s.tick(complete=[token(older['proof']), token(younger['proof'])])


def case_credits(s):
    first, second = s.store(BASE), s.store(BASE + 8)
    s.tick(fast=first); s.tick(fast=second)
    for h in [0, 1, 2]:
        a = s.tick(up=s.item(request(BASE + 0x200 + 8*h, handle=h)))
        need(a['upstream.request.ready'], 'CREDIT_SETUP', h)
    a = s.tick(up=s.item(request(BASE + 0x218, handle=3)))
    need(not a['upstream.request.ready'] and not a['memory.request.valid'] and a['requestStallCause'] == 5,
         'FIVE_OWNER_CREDIT_EXHAUSTION', s.name)
    s.respond(1, hold=2)
    a = s.tick(); need(a['upstream.request.ready'], 'CREDIT_RETURN_PROGRESS', s.name)
    s.respond(3, error=1); s.respond(0, hold=1); s.respond(2, page_fault=1)
    s.respond(4); s.respond(5)
    s.tick(complete=[token(first['proof']), token(second['proof'])])


def case_invalid_shapes(s):
    variants = [
        ('wrong-mask', {'mask': 0x7F}), ('zero-mask', {'mask': 0}),
        ('odd-half', {'address': BASE + 0x201, 'size': 1, 'mask': 0x06}),
        ('misaligned-word', {'address': BASE + 0x202, 'size': 2, 'mask': 0x3C}),
        ('misaligned-dword', {'address': BASE + 0x204, 'mask': 0xF0}),
        ('uncached', {'uncached': 1}), ('virtual-read', {'virtualized': 1}),
        ('prechecked', {'precheckedLoad': 1}), ('atomic', {'atomic': 1, 'atomicOp': 3}),
        ('outside-ram', {'address': 0x1000}), ('unqualified', {})]
    for name, changes in variants:
        older = s.seed_external()
        r = request(); r.update(changes)
        read = s.item(r, qualified_read=int(name != 'unqualified'))
        for cycle in range(3):
            a = s.tick(up=read if cycle == 0 else None)
            need(not a['upstream.request.ready'] and not a['memory.request.valid'] and not a['memoryCollectionHeadRead'],
                 'INVALID_SHAPE_BUSY_STALL', name)
        # Retain the exact stalled request while its real ordering blocker ends.
        a = s.tick(complete=[token(older['proof'])])
        need(a['upstream.request.ready'] and a['memory.request.valid'] and not a['memoryCollectionHeadRead'],
             'LEGACY_DIRECT_AFTER_EXTERNAL_DRAIN', name)
        s.respond(0)


def case_canonical(s):
    for frozen in [False, True]:
        older = s.seed_external()
        item = s.item(request(0x40001000, write=1, virtualized=1, data=0x9988776655443322), canonical=True, frozen=frozen)
        a = s.tick(up=item)
        need(not a['upstream.request.ready'] and not a['upstream.response.valid'], 'CANONICAL_ORDERING_STALL', frozen)
        a = s.tick(complete=[token(older['proof'])], **{'memory.request.ready': 0})
        need(a['memory.request.valid'] and not a['memoryCollectionHeadRead'] and not a['upstream.response.valid'],
             'CANONICAL_ACTUAL_DIRECT', frozen)
        s.tick()
        a = s.tick(**{'memory.request.ready': 1})
        need(a['upstream.request.ready'] and not a['upstream.response.valid'], 'NO_EARLY_CANONICAL_ACK', frozen)
        s.respond(0, hold=1)


def case_local_ack(s):
    item = s.store(BASE + 0x20)
    a = s.tick(up=item, **{'upstream.response.ready': 0})
    need(a['upstream.request.ready'] and a['upstream.response.valid'] and not a['memoryCollectionHeadRead'],
         'POSTED_LOCAL_ACK', s.name)
    sh = a['memory.request.bits.returnHandle']
    s.tick(); s.tick(**{'upstream.response.ready': 1})
    s.respond(sh); s.tick(complete=[token(item['proof'])])


def case_reset(s):
    first = s.store(BASE); s.tick(fast=first)
    s.tick(up=s.item(request(handle=0)))
    held = s.item(request(BASE + 0x208, handle=1))
    s.tick(up=held, **{'memory.request.ready': 0, 'upstream.response.ready': 0,
                      'memory.response.valid': 1, 'memory.response.bits.returnHandle': 0,
                      'memory.response.bits.data': s.model.word(BASE + 0x200)})
    s.tick(fast=s.store(BASE + 8))
    s.reset_all()
    need(len(s.model.reset_discards[-1]['accepted_request_ids']) == 3 and
         len(s.model.reset_discards[-1]['memory_owner_handles']) == 2,
         'COORDINATED_RESET_ACCOUNTING', s.model.reset_discards[-1])
    s.tick(up=s.item(request(handle=3))); s.respond(3)


POSITIVES = {
    'held-read-fast-store-smoke': case_held_smoke,
    'held-read-fast-store-all-lanes': case_held_lanes,
    'unissued-versus-issued-store': case_unissued,
    'same-beat-byte-overlap': case_byte_overlap,
    'simultaneous-fast-overlap': case_fast_overlap,
    'five-credits-out-of-order-returns': case_credits,
    'invalid-shapes-preserve-stalled-request': case_invalid_shapes,
    'canonical-frozen-direct-ordering': case_canonical,
    'upstream-posted-held-local-ack': case_local_ack,
    'coordinated-reset-counts-discarded-owners': case_reset,
}
NEGATIVES = {
    'rtl-held-qualification-change': 'held collection read lost its original request/qualification',
    'rtl-illegal-response-owner': 'StoreBuffer return lost its direct or ordered drain owner',
    'rtl-read-with-posted-proof': 'Assertion failed at PostedStoreCpu.scala:45',
    'rtl-malformed-frozen-proof': 'frozen store proof requires the matching actual ordinary virtual-store origin and shape',
}


def negative(s, name):
    if name == 'rtl-held-qualification-change':
        s.seed_external(); s.tick(up=s.item(), **{'memory.request.ready': 0})
        bad = {'upstreamCollectionHeadRead': 0}
    elif name == 'rtl-illegal-response-owner':
        bad = {'memory.response.valid': 1, 'memory.response.bits.returnHandle': 3}
    elif name == 'rtl-read-with-posted-proof':
        s.offer(s.item(posted=True)); bad = {}
    else:
        item = s.item(request(0x40001000, write=1, virtualized=1), canonical=True, frozen=True)
        item['frozen']['physicalAddress'] += 1
        s.offer(item); bad = {}
    caught = None
    try:
        s.raw(bad, checked=False); s.raw(checked=False)
    except DriverFailure as error:
        caught = str(error)
    s.stop()
    log = s.stderr_path.read_text()
    need(caught is not None and s.child.returncode in (-6, 134) and NEGATIVES[name] in log,
         'EXPECTED_RTL_ASSERTION', {'name': name, 'exit': s.child.returncode, 'diagnostic': caught, 'stderr': log})
    need('AddressSanitizer' not in log and 'runtime error:' not in log,
         'SANITIZER_NOT_EXPECTED_ASSERTION', name)
    return {'name': name, 'status': 'EXPECTED_RTL_ASSERTION', 'driver_exit': s.child.returncode,
            'anchor': NEGATIVES[name], 'cycles_before_assertion': s.cycles}


def replay(records):
    model = Ledger()
    for frame in records:
        if frame.get('reset_event'):
            e = frame['reset_event']; model.reset(e['upstream'], e['fast'], e['input'])
        if frame['checked']:
            model.observe(frame)
    model.drained()


MUTATIONS = {
    'observed-held-qualification': ('held-read-fast-store-all-lanes', 'HELD_COLLECTION_QUALIFICATION'),
    'observed-response-handle': ('five-credits-out-of-order-returns', 'DIRECT_RESPONSE_HANDLE'),
    'observed-response-data': ('held-read-fast-store-all-lanes', 'DIRECT_RESPONSE_DATA'),
    'observed-posted-token': ('held-read-fast-store-all-lanes', 'POSTED_COMPLETION_TOKEN'),
}


def mutate(out, name):
    source, anchor = MUTATIONS[name]
    with gzip.open(Path(out) / (source + '.jsonl.gz'), 'rt', encoding='utf-8') as f:
        records = [json.loads(line) for line in f]
    replay(copy.deepcopy(records))
    prior_held = False; chosen = None
    for frame in records:
        if not frame['checked']: continue
        i, a = frame['input'], frame['actual']
        if name == 'observed-held-qualification' and prior_held and a['memory.request.valid'] and a['memoryCollectionHeadRead']:
            a['memoryCollectionHeadRead'] ^= 1; chosen = frame; break
        if name in ('observed-response-handle', 'observed-response-data') and a['upstream.response.valid']:
            key = 'upstream.response.bits.' + ('returnHandle' if name.endswith('handle') else 'data')
            a[key] ^= 1; chosen = frame; break
        if name == 'observed-posted-token' and a['postedCompleted.valid']:
            a['postedCompleted.bits.tag'] ^= 1; chosen = frame; break
        prior_held = bool(a['memory.request.valid'] and not i['memory.request.ready'])
    need(chosen is not None, 'MUTATION_ANCHOR_PRESENT', name)
    caught = None
    try: replay(records)
    except Violation as error: caught = str(error)
    need(caught is not None and caught.startswith(anchor + ':'), 'PRECISE_HOST_MUTATION_REJECTION', caught)
    return {'name': name, 'status': 'EXPECTED_HOST_REJECTION', 'source_case': source,
            'mutated_cycle': chosen['actual']['cycle'], 'anchor': anchor, 'diagnostic': caught,
            'mutation_scope': 'saved host observation only; no RTL/input mutation'}


def bindings(driver):
    paths = [Path(__file__).resolve(), HERE / 'ports.py', HERE / 'driver.cpp',
             TASK / 'source/CollectionReadStoreGsim.scala', TASK / 'store-on/CollectionReadStoreGsim.h',
             TASK / 'store-on/actual-core.json', ROOT / 'store-full-line-progress-stagec-r1/source/StoreBuffer.scala',
             ROOT / 'store-full-line-progress-stagec-r1/source/PostedCollectionRead.scala']
    if driver is not None: paths.append(Path(driver).resolve())
    return [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--driver', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    choose = parser.add_mutually_exclusive_group(required=True)
    choose.add_argument('--case', choices=list(POSITIVES) + list(NEGATIVES) + list(MUTATIONS))
    choose.add_argument('--all', action='store_true')
    args = parser.parse_args()
    names = list(POSITIVES) + list(NEGATIVES) + list(MUTATIONS) if args.all else [args.case]
    if any(n not in MUTATIONS for n in names) and args.driver is None:
        parser.error('--driver is required for DUT scenarios')
    args.out.mkdir(parents=True, exist_ok=True)
    source_bindings = bindings(args.driver)
    reports = []
    for name in names:
        if name in MUTATIONS:
            result = mutate(args.out, name)
        else:
            need(not (args.out / (name + '.jsonl.gz')).exists(), 'PRESERVE_EXISTING_TRACE', name)
            s = Scenario(args.driver, args.out, name)
            try:
                if name in NEGATIVES:
                    result = negative(s, name)
                else:
                    POSITIVES[name](s); result = s.finish()
            except (Violation, DriverFailure):
                s.stop()
                raise
        reports.append(result)
        (args.out / (name + '.result.json')).write_text(json.dumps(result, indent=2) + '\n')
        print('STORE_BOUNDARY_CASE ' + name + ' ' + result['status'], flush=True)
    need(bindings(args.driver) == source_bindings, 'RUNTIME_SOURCE_BINDING', 'bound sources changed while running')
    result = {'scope': SCOPE, 'status': 'PASS', 'cases': reports, 'source_bindings': source_bindings,
              'trace_format': 'lossless gzip JSONL, exact wire input/output plus parsed complete scalar samples',
              'trace_bytes': sum(p.stat().st_size for p in args.out.glob('*.jsonl.gz')),
              'not_exercised': ['default-OFF equivalence requires separately authorized/bound control',
                                'actual ROB authority, recovery input, adapter/PMP/cache/Home/backend progress']}
    (args.out / ('result.json' if args.all else args.case + '.invocation.json')).write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
