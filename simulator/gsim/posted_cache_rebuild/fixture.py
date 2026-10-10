#!/usr/bin/env python3
"""Real cache/SRAM/engine with an independently authored synthetic TL manager.

The fixture supplies authority premises. CPU lineage and real-home reachable
schedules are separate gates. Raw scalar traces preserve every actual event.
"""
import argparse
from collections import deque, Counter
import json
import os
from pathlib import Path
import subprocess
import sys
from ports import INPUTS, OUTPUTS, REQUEST, PROOF, AB, C, D
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'posted_merge_rebuild'))
from contract_oracle import Contract, Context, Owner, Reservation, Token, Intent, require


def word(memory, address):
    return int.from_bytes(bytes(memory[address + i] for i in range(8)), 'little')


def line_bytes(memory, address):
    return bytes(memory[address + i] for i in range(64))


def observed_context(a, prefix):
    return Context(Owner(a[prefix + '.owner.slot'], a[prefix + '.owner.generation']),
                   Owner(a[prefix + '.cohortRoot.slot'], a[prefix + '.cohortRoot.generation']),
                   a[prefix + '.epoch'], a[prefix + '.lineAddress'])


def observed_reservation(a, prefix):
    return Reservation(a[prefix + '.mshr'], a[prefix + '.set'], a[prefix + '.way'],
                       bool(a[prefix + '.victimValid']), bool(a[prefix + '.victimDirty']), a[prefix + '.victimAddress'])


def observed_token(a, prefix):
    return Token(a[prefix + '.tag'], a[prefix + '.index'])


def observed_event(a, prefix):
    return observed_context(a, prefix + '.context'), observed_reservation(a, prefix + '.reservation')


class DriverFailure(RuntimeError):
    pass


class Cache:
    def __init__(self, executable, directory, name, enabled=True, generation_bits=64, wb_entries=2):
        self.name = name
        self.enabled = enabled
        self.wb_entries = wb_entries
        self.directory = Path(directory)
        self.stderr_path = self.directory / (name + '.stderr')
        self.stderr = self.stderr_path.open('w')
        self.trace = (self.directory / (name + '.jsonl')).open('w')
        self.child = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.stderr, text=True, bufsize=1,
                                      env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        memory = {a: (a * 29 + 11) & 255 for a in range(4096, 8192)}
        self.model = Contract(memory, generation_bits=generation_bits, wb_entries=wb_entries)
        self.backing = dict(memory)  # Updated only by actual C data or explicit completed DMA.
        self.dirty = set()
        self.state = dict.fromkeys(INPUTS, 0)
        self.request = None
        self.responses = deque()
        self.bypass = deque()
        self.acquires = {}
        self.release_acks = deque()
        self.d_offer = None
        self.grant_source = None
        self.probe = None
        self.c_burst = None
        self.held = {}
        self.cycle = 0
        self.count = Counter()
        self.events = []
        self.last = None
        self.tag = 0
        self.grant_delay = 24
        self.delay_by_line = {}
        self.hold_a = self.hold_c = self.hold_e = self.hold_cpu = self.hold_ack = False
        self.deny_line = None
        self.bad_cap_line = None
        self.bypass_error = False
        self.pending_negative = False
        self.fallback_active = False
        self.poison = None
        self.raw(reset=1)
        self.raw(reset=1)
        self.raw(reset=0)

    def raw(self, **updates):
        require(set(updates) <= set(INPUTS), 'unknown scalar fixture input')
        self.state.update(updates)
        data = ' '.join(k + '=' + str(int(v)) for k, v in self.state.items()) + '\n'
        try:
            self.child.stdin.write(data)
            self.child.stdin.flush()
            result = self.child.stdout.readline()
        except BrokenPipeError:
            result = ''
        if not result:
            code = self.child.wait(timeout=5)
            self.stderr.flush()
            raise DriverFailure(f'actual cache model exited {code}: ' + self.stderr_path.read_text())
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            raise DriverFailure('actual cache non-JSON output: ' + result + self.stderr_path.read_text())
        self.cycle += 1
        self.trace.write(json.dumps({'input': self.state, 'actual': result}) + '\n')
        self.trace.flush()
        self.last = result
        return result

    def begin(self, address, *, write=False, value=0, size=3, proof=False, virtual=False, uncached=False):
        require(self.request is None, 'authored held request overwritten')
        self.tag += 1
        intent = Intent(Token(self.tag, self.tag % 16), address, value, size, self.model.context_epoch)
        bits = dict.fromkeys(REQUEST, 0)
        bits.update(address=address, write=int(write), data=(value << (8 * (address & 7))) & ((1 << 64) - 1),
                    size=size, mask=((1 << (1 << size)) - 1) << (address & 7),
                    virtualized=int(virtual), uncached=int(uncached))
        self.request = {'intent': intent, 'bits': bits, 'proof': proof, 'error': self.bypass_error and (virtual or uncached)}
        return intent.token

    def send(self, address, **kwargs):
        token = self.begin(address, **kwargs)
        self.until(lambda: self.request is None, 'original request acceptance')
        return token

    def tick(self, **updates):
        values = {'reset': 0, 'posted.seal': 0, 'posted.endEpisode': 0,
                  'posted.contextEpoch': self.model.context_epoch,
                  'tl.a.ready': not self.hold_a, 'tl.c.ready': not self.hold_c,
                  'tl.e.ready': not self.hold_e, 'upstream.response.ready': not self.hold_cpu,
                  'downstream.request.ready': True,
                  'upstream.request.valid': self.request is not None,
                  'posted.requestProof.valid': bool(self.request and self.request['proof']),
                  'tl.b.valid': bool(self.probe and not self.probe['accepted'])}
        if self.request:
            q = self.request; intent = q['intent']
            values.update({'upstream.request.bits.' + k: v for k, v in q['bits'].items()})
            proof = dict.fromkeys(PROOF, 0)
            proof.update({'token.tag': intent.token.tag, 'token.index': intent.token.index, 'epoch': intent.epoch,
                          'address': intent.address, 'data': q['bits']['data'], 'mask': q['bits']['mask'], 'size': intent.size})
            if q['proof']:
                proof.update({k: 1 for k in ['headAuthorized', 'physicalPmpAllowed', 'originalPhysical',
                                             'integerOrigin', 'legacyPostedAccepted', 'finalChecked']})
            values.update({'posted.requestProof.bits.' + k: v for k, v in proof.items()})
        elif not self.enabled:
            # Invalid sidecar bits have no semantics, including under ordinary offers.
            values['posted.requestProof.bits.token.tag'] = self.cycle
        if self.probe:
            values.update({'tl.b.bits.opcode': 6, 'tl.b.bits.param': 2, 'tl.b.bits.size': 6,
                           'tl.b.bits.source': 3, 'tl.b.bits.address': self.probe['address'], 'tl.b.bits.mask': 255})
        if self.d_offer is None:
            if self.grant_source is None and self.release_acks and not self.hold_ack and self.release_acks[0]['due'] <= self.cycle:
                ack = self.release_acks[0]
                self.d_offer = {'opcode': 6, 'param': 0, 'size': 6, 'source': ack['source'], 'sink': 0,
                                'data': 0, 'denied': 0, 'corrupt': 0}
            else:
                choices = [s for s, g in self.acquires.items() if g['beat'] < 8 and g['due'] <= self.cycle]
                if choices:
                    source = self.grant_source if self.grant_source is not None else max(choices)
                    self.grant_source = source
                    g = self.acquires[source]
                    if g['base'] is None:
                        g['base'] = line_bytes(self.backing, g['address'])
                    data = int.from_bytes(g['base'][g['beat'] * 8:(g['beat'] + 1) * 8], 'little')
                    self.d_offer = {'opcode': 5, 'param': int(g['address'] == self.bad_cap_line), 'size': 6,
                                    'source': source, 'sink': g['sink'], 'data': data,
                                    'denied': int(g['address'] == self.deny_line and g['beat'] == 7), 'corrupt': 0}
        values['tl.d.valid'] = self.d_offer is not None
        if self.d_offer:
            values.update({'tl.d.bits.' + k: v for k, v in self.d_offer.items()})
        values['downstream.response.valid'] = bool(self.bypass)
        if self.bypass:
            values.update({'downstream.response.bits.' + k: v for k, v in self.bypass[0].items()})
        values.update(updates)
        a = self.raw(**values)
        s = self.state
        if self.enabled:
            if self.model.busy():
                require(a['posted.busy'], 'accepted cache responsibility disappeared')
            elif self.fallback_active:
                accepted_tail = bool(self.responses or self.acquires or self.release_acks or self.c_burst or self.bypass or
                                     (self.probe and self.probe['accepted'] and not self.probe['done']))
                if accepted_tail:
                    require(a['posted.busy'], 'fallback ACK lost actual accepted coherence/WB tail')
                if not a['posted.busy']:
                    require(not accepted_tail, 'fallback drain cleared before actual resource release')
                    self.fallback_active = False
            else:
                require(not a['posted.busy'], 'unowned accepted cache responsibility')
            require(a['posted.episodeActive'] == int(self.model.episode_root is not None), 'cohort lifetime mismatch')
        for name, valid, ready, fields in [
            ('A', a['tl.a.valid'], s['tl.a.ready'], ['tl.a.bits.' + n for n in AB]),
            ('C', a['tl.c.valid'], s['tl.c.ready'], ['tl.c.bits.' + n for n in C]),
            ('E', a['tl.e.valid'], s['tl.e.ready'], ['tl.e.bits.sink']),
            ('response', a['upstream.response.valid'], s['upstream.response.ready'],
             ['upstream.response.bits.data', 'upstream.response.bits.error', 'upstream.response.bits.pageFault'])]:
            payload = tuple(a[n] for n in fields)
            if name in self.held:
                require(valid and payload == self.held[name], name + ' held offer changed')
            if valid and not ready: self.held[name] = payload
            else: self.held.pop(name, None)
        current = self.request
        accepted = bool(current and a['upstream.request.ready'])
        if accepted:
            q = current; intent = q['intent']; bits = q['bits']; address = bits['address']
            expected = 0 if bits['write'] or q['error'] else word(self.model.memory, address & ~7)
            self.responses.append({'data': expected, 'error': int(q['error']), 'pageFault': 0, 'token': intent.token})
            self.count['cpu_accept'] += 1
            if a['accepted.valid']:
                require(q['proof'] and bits['write'] and self.enabled, 'cache fabricated posted authority')
                context = observed_context(a, 'accepted.bits.member.context')
                reservation = observed_reservation(a, 'accepted.bits.reservation')
                require(observed_token(a, 'accepted.bits.member.token') == intent.token, 'full CPU token changed')
                ticket = a['accepted.bits.member.responseTicket']
                self.model.accept(intent, context, reservation, ticket, bool(a['accepted.bits.newLine']))
                self.model.response_complete(ticket, intent.token)
                self.count['posted_accept'] += 1
                self.count['posted_new' if a['accepted.bits.newLine'] else 'posted_join'] += 1
            elif bits['write'] and not q['error']:
                self.model.memory.update(intent.bytes())
                self.dirty.add(address & ~63)
                if address & ~63 in self.model.resident:
                    self.model.resident[address & ~63] = self.model.line(address & ~63)
                self.count['legacy_write'] += 1
            if a['hit']: self.count['cpu_hit'] += 1
            self.request = None
        else:
            require(not a['accepted.valid'], 'owner accepted without actual cache upstream fire')
        if a['fallback.valid']:
            require(accepted and current['proof'], 'fallback detached from actual acceptance')
            require(observed_token(a, 'fallback.bits.token') == current['intent'].token, 'fallback token changed')
            self.model.fallback_accept(current['intent'], a['fallback.bits.responseTicket'])
            self.fallback_active = True
            self.count['fallback'] += 1
        responded = None
        if a['upstream.response.valid'] and s['upstream.response.ready']:
            require(self.responses, 'unowned actual CPU response')
            responded = self.responses.popleft()
            for field in ['data', 'error', 'pageFault']:
                require(a['upstream.response.bits.' + field] == responded[field], 'actual CPU byte/error response differs from authored intent')
            self.count['cpu_response'] += 1
        if a['acknowledged.valid']:
            token = observed_token(a, 'acknowledged.bits.token')
            require(responded and responded['token'] == token, 'ACK was not actual upstream response.fire')
            context = observed_context(a, 'acknowledged.bits.context')
            require(self.model.tokens[token][0] == context, 'ACK full owner changed')
            self.model.ack(token, a['acknowledged.bits.responseTicket'])
            self.count['posted_ack'] += 1
        if a['fallbackAck.valid']:
            token = observed_token(a, 'fallbackAck.bits.token')
            require(responded and responded['token'] == token, 'fallback ACK not actual response.fire')
            self.model.fallback_ack(token, a['fallbackAck.bits.responseTicket'])
        if a['tl.b.ready'] and s['tl.b.valid']:
            p = self.probe
            require(p and not p['accepted'], 'unexpected actual B handshake')
            p['accepted'] = True
            p['hit'] = p['address'] in self.model.resident
            p['dirty'] = p['hit'] and p['address'] in self.dirty
            p['bytes'] = self.model.line(p['address'])
            self.model.probe(p['address'])
            self.dirty.discard(p['address'])
            self.count['probe'] += 1
        elif s['tl.b.valid']:
            self.count['probe_stall'] += 1
        for label, method in [('attached', self.model.attach_wb), ('sent', self.model.sent_wb), ('completed', self.model.complete_wb)]:
            if a[label + '.valid']:
                context, reservation = observed_event(a, label + '.bits')
                ticket_owner = Owner(a[label + '.bits.ticket.owner.slot'], a[label + '.bits.ticket.owner.generation'])
                require(ticket_owner == context.owner, 'WB detached full owner')
                slot = a[label + '.bits.ticket.slot']
                if label == 'attached': method(context, reservation, slot)
                else:
                    if label == 'sent':
                        require(a['tl.c.valid'] and s['tl.c.ready'] and a['tl.c.bits.source'] == 2 + slot,
                                'WB sent was not real C-last')
                    else:
                        require(s['tl.d.valid'] and a['tl.d.ready'] and s['tl.d.bits.opcode'] == 6 and s['tl.d.bits.source'] == 2 + slot,
                                'WB completion was not real exact ReleaseAck')
                    method(context, reservation, (slot, ticket_owner))
                self.count['wb_' + label] += 1
        if a['cancelled.valid']:
            self.model.cancel_victim(*observed_event(a, 'cancelled.bits'))
            self.count['victim_cancel'] += 1
        if a['tl.a.valid'] and s['tl.a.ready']:
            source = a['tl.a.bits.source']; address = a['tl.a.bits.address']
            require(source in (0, 1) and source not in self.acquires, 'actual physical Acquire source reused or invented')
            require(a['tl.a.bits.opcode'] == 6 and a['tl.a.bits.param'] == 1 and a['tl.a.bits.size'] == 6,
                    'posted cache uses actual N-to-T full data acquisition')
            self.acquires[source] = {'address': address, 'sink': source, 'beat': 0, 'base': None,
                                     'due': self.cycle + self.delay_by_line.get(address, self.grant_delay),
                                     'posted': bool(a['acquired.valid'])}
            if a['acquired.valid']:
                context, reservation = observed_event(a, 'acquired.bits')
                require(context.line == address, 'actual A address differs from full owner')
                self.model.acquire(context, reservation, source)
                self.count['posted_a'] += 1
            self.count['a'] += 1
        else:
            require(not a['acquired.valid'], 'engine enqueue counted as actual A')
        if s['tl.d.valid'] and a['tl.d.ready']:
            d = self.d_offer
            require(d is not None, 'D fire without authored transport offer')
            if d['opcode'] == 6:
                require(self.release_acks and self.release_acks[0]['source'] == d['source'], 'unowned ReleaseAck')
                self.release_acks.popleft(); self.count['release_ack'] += 1
            else:
                g = self.acquires[d['source']]
                if g['beat'] == 0:
                    require(g['base'] == line_bytes(self.backing, g['address']), 'Grant ownership base changed beneath held offer')
                if g['posted']:
                    self.model.grant_beat(d['source'], d['data'], d['sink'], error=bool(d['denied']), to_t=d['param'] == 0)
                g['beat'] += 1
                if g['beat'] == 8: self.grant_source = None
                self.count['grant_beat'] += 1
            self.d_offer = None
        if a['tl.e.valid'] and s['tl.e.ready']:
            sink = a['tl.e.bits.sink']
            sources = [source for source, g in self.acquires.items() if g['sink'] == sink]
            require(len(sources) == 1 and self.acquires[sources[0]]['beat'] == 8, 'actual E without complete granted source')
            source = sources[0]
            if self.acquires[source]['posted']: self.model.e(source)
            del self.acquires[source]
            self.count['e'] += 1
        if a['tl.c.valid'] and s['tl.c.ready']:
            opcode, source, address = a['tl.c.bits.opcode'], a['tl.c.bits.source'], a['tl.c.bits.address']
            require(opcode in (4, 5, 6, 7) and a['tl.c.bits.size'] == 6 and not a['tl.c.bits.corrupt'], 'malformed actual C')
            if self.c_burst is None:
                expected = self.model.line(address)
                if opcode in (4, 5):
                    require(self.probe and self.probe['accepted'] and self.probe['address'] == address,
                            'ProbeAck not associated with actual B')
                    require(opcode == (5 if self.probe['dirty'] else 4), 'probe dirty-data obligation lost')
                    require(a['tl.c.bits.param'] == (1 if self.probe['hit'] else 5), 'probe hit/absent permission changed')
                    expected = self.probe['bytes']
                else:
                    require(source in range(2, 2 + self.wb_entries), 'invented Release source')
                self.c_burst = {'opcode': opcode, 'source': source, 'address': address, 'beat': 0, 'expected': expected}
            burst = self.c_burst
            require((opcode, source, address) == (burst['opcode'], burst['source'], burst['address']), 'C burst changed owner')
            data = a['tl.c.bits.data'].to_bytes(8, 'little')
            if opcode in (5, 7):
                require(data == burst['expected'][burst['beat'] * 8:(burst['beat'] + 1) * 8], 'actual SRAM C bytes differ from authored coherent image')
                self.backing.update({address + burst['beat'] * 8 + i: b for i, b in enumerate(data)})
            burst['beat'] += 1
            if burst['beat'] == (8 if opcode in (5, 7) else 1):
                if opcode in (6, 7):
                    self.model.resident.pop(address, None); self.dirty.discard(address)
                    self.release_acks.append({'source': source, 'due': self.cycle + 9})
                    self.count['release_dirty' if opcode == 7 else 'release_clean'] += 1
                else:
                    self.probe['done'] = True; self.count['probe_complete'] += 1
                self.c_burst = None
        if a['refillValid']:
            data = b''.join(a['refillWord' + str(i)].to_bytes(8, 'little') for i in range(8))
            self.model.refill(*observed_event(a, 'refillEvent'), data)
            self.events.append(('refill', self.cycle, a['refillEvent.context.lineAddress']))
            self.count['posted_refill'] += 1
        if a['lineWrite']:
            address = a['lineWriteAddress']
            data = b''.join(a['installWord' + str(i)].to_bytes(8, 'little') for i in range(8))
            if a['lineWritePosted']:
                require(a['installedValid'], 'posted SRAM write without owner install.fire')
                self.model.install(*observed_event(a, 'installedEvent'), data)
                self.dirty.add(address)
                self.count['posted_install'] += 1
            else:
                require(data == self.model.line(address), 'ordinary SRAM line installation byte mismatch')
                self.model.resident[address] = data
            self.events.append(('install', self.cycle, address))
        else:
            require(not a['installedValid'], 'owner install.fire without true SRAM line write')
        if a['drained.valid']:
            self.model.drain(observed_token(a, 'drained.bits.token'), observed_context(a, 'drained.bits.context'))
            self.count['token_drain'] += 1
        if a['released.valid']:
            self.model.release(*observed_event(a, 'released.bits'))
            self.count['owner_release'] += 1
        if a['downstream.request.valid'] and s['downstream.request.ready']:
            require(not self.bypass, 'unexpected parallel synthetic bypass')
            self.bypass.append({'data': 0, 'error': int(self.bypass_error), 'pageFault': 0})
            self.count['bypass'] += 1
        if s['downstream.response.valid'] and a['downstream.response.ready']:
            self.bypass.popleft()
        if s['posted.endEpisode']:
            self.model.end_episode(held_ingress=bool(current and current['proof']), accepted_same_edge=bool(a['accepted.valid']))
        return a

    def until(self, predicate, label, limit=2048):
        for _ in range(limit):
            if predicate(): return
            self.tick()
        raise AssertionError('bounded progress failure: ' + label)

    def idle(self):
        self.until(lambda: not self.request and not self.responses and not self.model.busy() and not self.acquires and
                   not self.release_acks and self.c_burst is None and self.d_offer is None and not self.bypass and
                   (not self.enabled or not self.last['posted.busy']),
                   'actual owner/response/coherence drain')
        self.tick()

    def end_episode(self):
        self.idle()
        self.tick(**{'posted.endEpisode': 1})
        self.tick()

    def read_line(self, address):
        for offset in range(0, 64, 8): self.send(address + offset)
        self.idle()

    def start_probe(self, address):
        require(self.probe is None or self.probe['done'], 'overwriting held probe')
        self.probe = {'address': address & ~63, 'accepted': False, 'done': False}

    def finish_probe(self):
        self.until(lambda: self.probe['done'], 'real B/C probe completion')

    def dma(self, changes):
        self.model.dma_write(changes)
        self.backing.update(changes)

    def flush(self):
        self.state['flushRequest'] = 1
        self.until(lambda: bool(self.last['flushDone']), 'actual dirty cache flush', 8192)
        self.state['flushRequest'] = 0
        self.tick()
        require(self.backing == self.model.memory, 'full actual backing image differs after real flush')
        self.count['full_backing_check'] += 1

    def close(self, success=True):
        if self.child.poll() is None:
            try: self.child.stdin.write('quit\n'); self.child.stdin.flush()
            except BrokenPipeError: pass
            self.child.stdin.close()
        code = self.child.wait(timeout=5)
        self.stderr.close(); self.trace.close()
        diagnostic = self.stderr_path.read_text()
        require(not any(x in diagnostic for x in ['AddressSanitizer', 'UndefinedBehaviorSanitizer', 'runtime error:']),
                'sanitizer failure is never a passing semantic negative')
        if success: require(code == 0, 'model failed during positive scenario')
        return {'name': self.name, 'cycles': self.cycle, 'events': dict(self.count), 'status': 'PASS'}


def merge_reuse(t):
    t.grant_delay = 120
    for i, (offset, value, size) in enumerate([(0, 0x1122334455667788, 3), (2, 0x9999, 1),
                                             (7, 0xA5, 0), (8, 0xDEADBEEF, 2), (32, 0x12345678, 2)]):
        t.send(4160 + offset, write=True, value=value, size=size, proof=True)
        t.until(lambda: not t.responses, 'actual early response credit reuse')
    t.idle()
    require(t.count['posted_accept'] == 5 and t.count['posted_new'] == 1 and t.count['posted_a'] == 1,
            'five store/two-ticket merge coverage absent')
    t.read_line(4160); t.flush()


def reordered(t):
    t.delay_by_line = {4160: 120, 4224: 12}
    t.send(4160, write=True, value=0xABC, proof=True)
    t.send(4224, write=True, value=0xDEF, proof=True)
    t.idle()
    refills = [address for kind, _, address in t.events if kind == 'refill']
    installs = [address for kind, _, address in t.events if kind == 'install']
    require(refills == [4224, 4160] and installs == [4160, 4224], 'out-of-order refill/oldest install not exercised')
    t.read_line(4160); t.read_line(4224); t.flush()


def credit_late_hit(t):
    t.hold_cpu = True
    t.send(4160, write=True, value=0x11, proof=True)
    t.send(4168, write=True, value=0x22, proof=True)
    token = t.begin(4176, write=True, value=0x33, proof=True)
    t.until(lambda: t.count['posted_install'] == 1, 'real installation while original request held for credit')
    for _ in range(8): t.tick()
    require(t.request and t.request['intent'].token == token and t.count['posted_accept'] == 2,
            'credit-held request was withdrawn or falsely admitted')
    t.hold_cpu = False
    t.idle()
    require(t.count['posted_accept'] == 2 and t.count['legacy_write'] == 1 and t.count['cpu_hit'] >= 1,
            'unchanged held request did not become a legacy resident hit')
    t.read_line(4160); t.flush()


def pre_a_mutation(t):
    t.hold_a = True
    t.send(4160, write=True, value=0xBEEF, size=1, proof=True)
    t.start_probe(4160); t.finish_probe()
    require(t.count['a'] == 0 and not t.probe['hit'], 'probe did not precede actual A')
    t.dma({4163: 0x42, 4179: 0x79, 4210: 0xAB})
    t.hold_a = False
    t.idle(); t.read_line(4160); t.flush()


def post_install_probe(t):
    t.hold_cpu = True
    t.send(4160, write=True, value=0x7777, size=1, proof=True)
    t.until(lambda: t.count['posted_install'] == 1, 'install before held ACK')
    t.start_probe(4160); t.finish_probe()
    require(t.model.busy() and t.count['posted_ack'] == 0 and t.probe['dirty'], 'held ACK/probe dirty coverage absent')
    t.dma({4160: 0xD1, 4161: 0xD2, 4185: 0xCA})
    t.hold_cpu = False
    t.idle(); t.read_line(4160); t.flush()
    require(t.count['posted_install'] == 1, 'late drain resurrected probed line')


def probe_after_e(t):
    t.send(4160, write=True, value=0x8989, proof=True)
    t.until(lambda: t.count['e'] == 1, 'actual E handshake')
    t.start_probe(4160); t.finish_probe()
    require(t.count['probe_stall'] > 0, 'real post-E pre-install probe did not stall')
    t.idle(); t.read_line(4160); t.flush()


def victim(t, dirty):
    t.send(4160, write=dirty, value=0x1122)
    t.idle()
    t.send(4672); t.idle()
    t.hold_ack = True
    t.send(5184, write=True, value=0x9988, proof=True)
    t.until(lambda: t.count['posted_install'] == 1 and t.count['token_drain'] == 1, 'C-last/acquire/refill overlap')
    require(t.count['wb_attached'] == 1 and t.count['wb_sent'] == 1 and t.count['wb_completed'] == 0 and
            t.model.busy() and t.last['mshrMask'], 'owner did not retain its real pending WB')
    require(t.count['release_dirty' if dirty else 'release_clean'] == 1, 'actual victim kind not exercised')
    t.hold_ack = False
    t.idle(); t.read_line(5184); t.flush()


def cancel_victim(t):
    t.send(4160, write=True, value=0x1122); t.idle()
    t.send(4672); t.idle()
    t.send(5184, write=True, value=0x3344, proof=True)
    t.start_probe(4160); t.finish_probe()
    t.idle()
    require(t.count['victim_cancel'] == 1 and t.count['wb_attached'] == 0 and t.count['release_dirty'] == 0,
            'real probe did not cancel exactly the uncaptured victim')
    t.read_line(5184); t.flush()


def flush_busy(t):
    t.send(4160, write=True, value=0xCAFEBABE, proof=True)
    t.until(lambda: not t.responses, 'early ACK before real flush request')
    require(t.model.busy(), 'flush was not requested across a live posted obligation')
    t.flush(); t.idle()
    require(t.count['owner_release'] == 1 and t.count['release_dirty'] == 1, 'flush omitted posted install/victim drain')


def episode_boundary(t):
    t.send(4160, write=True, value=0x11, proof=True); t.idle()
    root = t.model.episode_root
    t.send(4224, write=True, value=0x22, proof=True); t.idle()
    require(t.model.episode_root == root, 'local empty owner ended cohort')
    t.end_episode(); t.model.context_boundary(1)
    t.send(4288, write=True, value=0x33, proof=True); t.idle()
    require(t.model.episode_root != root, 'new same-path episode reused stale root')
    t.flush()


def tiny_generation(t):
    for i in range(4):
        t.send(4160 + i * 64, write=True, value=100 + i, proof=True)
        t.end_episode()
    require(t.model.exhausted, 'tiny generation did not exhaust')
    t.hold_cpu = True
    t.send(4480, write=True, value=0x1234, proof=True)
    for _ in range(80): t.tick()
    require(t.count['fallback'] == 1 and t.model.busy(), 'fallback lacked real legacy response ownership')
    t.hold_cpu = False
    t.idle(); t.read_line(4480); t.flush()
    require(t.count['posted_accept'] == 4, 'exhausted owner wrapped or invented generation')


def dirty_fallback_tail(t, context_negative=False):
    for i in range(4):
        t.send(4160 + i * 64, write=True, value=100 + i, proof=True)
        t.end_episode()
    # Set 1 now has dirty line 4160. Fill its second way and make 4160 the victim.
    t.send(4672); t.idle()
    t.hold_ack = True
    t.send(5184, write=True, value=0xABCDEF, proof=True)
    t.until(lambda: t.count['fallback'] == 1 and not t.responses and bool(t.release_acks),
            'fallback CPU ACK before held real dirty ReleaseAck')
    require(not t.model.busy() and t.last['posted.busy'] and t.count['release_dirty'] == 1,
            'fallback WB tail did not outlive the real CPU ACK')
    t.count['fallback_wb_tail'] += 1
    if context_negative:
        t.poison = {'field': 'posted.contextEpoch', 'original': t.model.context_epoch,
                    'poisoned': t.model.context_epoch + 1, 'boundary': 'CPU ACK complete; exact old WB ReleaseAck held'}
        t.tick(**{'posted.contextEpoch': t.model.context_epoch + 1})
        raise AssertionError('fallback context crossed a live WB tail')
    # Probes still drain while the conservative fallback responsibility is live.
    t.start_probe(5184); t.finish_probe()
    t.begin(5248, write=True, value=0xDEAD, proof=True)
    for _ in range(5): t.tick()
    require(t.request is not None and t.count['fallback'] == 1, 'new fallback crossed the old held WB')
    t.state['flushRequest'] = 1
    for _ in range(4): t.tick()
    require(not t.last['flushDone'], 'flush completed before old ReleaseAck')
    t.hold_ack = False
    t.until(lambda: t.count['release_ack'] == 1, 'exact old fallback ReleaseAck')
    # A newly accepted probe on the otherwise-empty clear edge remains responsibility.
    t.start_probe(4672); t.tick()
    require(t.probe['accepted'], 'probe did not meet the old fallback drain edge')
    t.finish_probe(); t.count['fallback_probe_tail'] += 1
    t.until(lambda: t.last['flushDone'], 'old fallback drain with a younger held proof and flush')
    require(t.request is not None, 'held new proof bypassed active flush')
    t.state['flushRequest'] = 0
    t.idle(); t.end_episode(); t.read_line(5248); t.flush()
    require(t.count['fallback'] == 2, 'new fallback did not progress after actual old drain')


def off_legacy(t):
    for i in range(3): t.send(4160 + i * 8, write=True, value=0xAA + i, proof=True)
    t.idle(); t.read_line(4160); t.flush()
    require(t.count['posted_accept'] == 0 and t.count['legacy_write'] == 3, 'OFF instantiated posted behavior')


def negative(t, kind):
    if kind in ('fatal-error', 'fatal-cap'):
        if kind == 'fatal-error':
            t.deny_line = 4160
            t.poison = {'field': 'tl.d.bits.denied', 'original': 0, 'poisoned': 1, 'boundary': 'last GrantData beat after posted ACK'}
        else:
            t.bad_cap_line = 4160
            t.poison = {'field': 'tl.d.bits.param', 'original': 0, 'poisoned': 1, 'boundary': 'T replaced by B permission'}
        t.send(4160, write=True, value=0x1234, proof=True)
        for _ in range(128): t.tick()
    else:
        t.hold_cpu = True
        t.send(4160, write=True, value=0x11, proof=True)
        t.send(4168, write=True, value=0x22, proof=True)
        t.begin(4176, write=True, value=0x33, proof=True)
        t.tick()
        if kind == 'held-proof':
            t.poison = {'field': 'posted.requestProof.bits.token.tag', 'original': t.request['intent'].token.tag, 'poisoned': 999}
            t.tick(**{'posted.requestProof.bits.token.tag': 999})
        elif kind == 'held-context':
            t.poison = {'field': 'posted.contextEpoch', 'original': 0, 'poisoned': 1, 'unchanged_proof_epoch': 0}
            t.tick(**{'posted.contextEpoch': 1})
        else:
            t.poison = {'field': 'posted.endEpisode', 'original': 0, 'poisoned': 1, 'boundary': 'two accepted stores plus held third proof'}
            t.tick(**{'posted.endEpisode': 1})
    raise AssertionError('negative failed to terminate the real model')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--executable', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--enabled', type=int, choices=[0, 1], required=True)
    ap.add_argument('--generation-bits', type=int, default=64)
    ap.add_argument('--wb-entries', type=int, default=2)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if not args.enabled:
        cases = [('off-legacy-sram-flush', off_legacy)]
    elif args.generation_bits == 2:
        cases = [('generation2-real-fallback', tiny_generation), ('dirty-fallback-WB-tail', dirty_fallback_tail)]
    elif args.wb_entries == 1:
        # No C-last overlap exists in this original WB1 configuration.
        cases = [('wb1-basic-merge', merge_reuse)]
    else:
        cases = [('merge-response-reuse', merge_reuse), ('two-line-reordered', reordered),
                 ('credit-held-to-legacy-hit', credit_late_hit), ('before-A-probe-DMA', pre_a_mutation),
                 ('after-install-held-ACK-probe-DMA', post_install_probe), ('after-E-probe', probe_after_e),
                 ('clean-victim-overlap', lambda t: victim(t, False)), ('dirty-victim-overlap', lambda t: victim(t, True)),
                 ('probe-cancels-victim', cancel_victim), ('flush-live-owner', flush_busy),
                 ('explicit-episode-boundary', episode_boundary)]
    results = []
    def progress():
        (args.output / 'progress.json').write_text(json.dumps({'status': 'RUNNING', 'cases': results}, indent=2) + '\n')
    progress()
    for name, case in cases:
        t = Cache(args.executable, args.output, name, bool(args.enabled), args.generation_bits, args.wb_entries)
        try:
            case(t); results.append(t.close()); progress()
        except BaseException:
            t.close(False)
            raise
    if args.enabled and args.generation_bits == 64 and args.wb_entries == 2:
        diagnostics = {'fatal-error': ['platform violated guaranteed posted RAM refill success'],
                       'fatal-cap': ['platform violated guaranteed posted RAM refill success'],
                       'held-proof': ['cache held original request/proof changed'],
                       # Both exact guards reject the same changed current/captured epoch.
                       # Generated scheduling may evaluate either source assertion first.
                       'held-context': ['cache held posted context changed',
                                        'cache original posted proof detached from request'],
                       'end-with-held': ['episode ended beside held or accepted original proof',
                                         'cohort may end only at an empty registered aggregate boundary']}
        for name, diagnostic in diagnostics.items():
            t = Cache(args.executable, args.output, name)
            try:
                negative(t, name)
            except DriverFailure as error:
                t.close(False)
                observed = [guard for guard in diagnostic if guard in str(error)]
                require(observed, 'negative did not hit the expected exact real RTL guard')
                require(t.child.returncode != 0, 'semantic negative model exited successfully')
                results.append({'name': name, 'status': 'EXPECTED_RTL_ASSERTION',
                                'diagnostic': observed[0], 'exit': t.child.returncode, 'stimulus': t.poison})
                progress()
            else:
                t.close(False); raise AssertionError('negative was not detected')
    if args.enabled and args.generation_bits == 2:
        t = Cache(args.executable, args.output, 'fallback-context-before-WB-drain', True, 2, args.wb_entries)
        try:
            dirty_fallback_tail(t, context_negative=True)
        except DriverFailure as error:
            t.close(False)
            diagnostic = 'cache fallback context changed before real coherence drain'
            require(diagnostic in str(error) and t.child.returncode != 0, 'wrong fallback context negative guard')
            results.append({'name': t.name, 'status': 'EXPECTED_RTL_ASSERTION', 'diagnostic': diagnostic,
                            'stimulus': t.poison, 'exit': t.child.returncode})
            progress()
        else:
            t.close(False); raise AssertionError('fallback context mutation was not detected')
    report = {'status': 'PASS', 'scope': 'real private cache/engine/SRAM; synthetic manager and authority premises; no real CPU/home claim',
              'enabled': bool(args.enabled), 'generation_bits': args.generation_bits, 'wb_entries': args.wb_entries, 'cases': results}
    (args.output / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print('POSTED_CACHE_COMPONENT_PASS enabled=' + str(args.enabled) + ' generation_bits=' + str(args.generation_bits) +
          ' wb_entries=' + str(args.wb_entries) + ' cases=' + str(len(results)))


if __name__ == '__main__':
    main()
