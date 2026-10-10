#!/usr/bin/env python3
"""Authored component schedules against real GSIM scalar observations.

Proof fields are explicit environmental premises. This fixture does not prove
CPU lineage, cache SRAM writes, real TileLink/home reachability or performance.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

from contract_oracle import Context, Contract, HeldOffer, Intent, Owner, Reservation, Token, require
from ports import INPUTS, PULSES, OFFER, MEMBER, EVENT


def token_fields(prefix, token):
    return {prefix + '.index': token.index, prefix + '.tag': token.tag}


def context_fields(prefix, context):
    return {prefix + '.owner.slot': context.owner.slot, prefix + '.owner.generation': context.owner.generation,
            prefix + '.cohortRoot.slot': context.root.slot, prefix + '.cohortRoot.generation': context.root.generation,
            prefix + '.epoch': context.epoch, prefix + '.lineAddress': context.line}


def reservation_fields(prefix, reservation):
    return {prefix + '.mshr': reservation.mshr, prefix + '.set': reservation.set, prefix + '.way': reservation.way,
            prefix + '.victimValid': int(reservation.victim_valid), prefix + '.victimDirty': int(reservation.victim_dirty),
            prefix + '.victimAddress': reservation.victim_address}


def event_fields(prefix, context, reservation):
    return {**context_fields(prefix + '.context', context), **reservation_fields(prefix + '.reservation', reservation)}


def member_fields(prefix, intent, context, ticket):
    return {**token_fields(prefix + '.token', intent.token), **context_fields(prefix + '.context', context),
            prefix + '.responseTicket': ticket}


def observe(actual, expected):
    for name, value in expected.items():
        require(actual[name] == value, f'actual scalar mismatch {name}: {actual[name]} != {value}')


class DriverFailure(RuntimeError):
    pass


class Scenario:
    def __init__(self, executable, directory, name, generation_bits=64):
        self.name = name
        self.directory = Path(directory)
        self.stderr_path = self.directory / (name + '.stderr')
        self.stderr = self.stderr_path.open('w')
        self.trace = (self.directory / (name + '.jsonl')).open('w')
        self.child = subprocess.Popen([str(executable)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.stderr, text=True, bufsize=1,
                                      env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        self.state = dict.fromkeys(INPUTS, 0)
        self.model = Contract({a: (a * 29 + 11) & 255 for a in range(4096, 8192)}, generation_bits=generation_bits)
        self.pending = None
        self.holds = {name: HeldOffer() for name in ['ingress', 'install', 'drain', 'release', 'fallback']}
        self.cycles = 0
        self.events = {'accepted': 0, 'ack': 0, 'install': 0, 'drain': 0, 'release': 0, 'fallback': 0}
        self.raw_clock(reset=1)
        self.raw_clock(reset=1)
        self.raw_clock(reset=0)

    def raw_clock(self, **updates):
        self.state.update(dict.fromkeys(PULSES, 0))
        self.state.update(updates)
        require(set(updates) <= set(INPUTS), 'unknown fixture input')
        line = ' '.join(name + '=' + str(int(value)) for name, value in self.state.items()) + '\n'
        try:
            self.child.stdin.write(line)
            self.child.stdin.flush()
            result = self.child.stdout.readline()
        except BrokenPipeError:
            result = ''
        if not result:
            code = self.child.wait(timeout=5)
            self.stderr.flush()
            raise DriverFailure(f'GSIM driver exited {code}: ' + self.stderr_path.read_text())
        try:
            actual = json.loads(result)
        except json.JSONDecodeError:
            raise DriverFailure('GSIM non-JSON diagnostic: ' + result + self.stderr_path.read_text())
        self.cycles += 1
        self.trace.write(json.dumps({'input': self.state, 'actual': actual}) + '\n')
        self.trace.flush()
        return actual

    def clock(self, **updates):
        before = {'busy': int(self.model.busy()), 'stores': len(self.model.tokens), 'lines': len(self.model.runs),
                  'failed': int(self.model.failed), 'exhausted': int(self.model.exhausted),
                  'episodeActive': int(self.model.episode_root is not None)}
        actual = self.raw_clock(**updates)
        observe(actual, before)
        s = self.state
        incoming = tuple(s['enq.bits.' + n] for n in OFFER) if s['enq.valid'] else None
        self.holds['ingress'].sample(incoming, actual['enq.ready'], s['contextEpoch'])
        for label, valid, ready, names in [
            ('install', 'installValid', 'installReady', ['installEvent.' + n for n in EVENT] +
             ['installWord' + str(i) for i in range(8)]),
            ('drain', 'drained.valid', 'drainReady', ['drained.bits.' + n for n in MEMBER]),
            ('release', 'released.valid', 'releaseReady', ['released.bits.' + n for n in EVENT]),
            ('fallback', 'fallback.valid', 'fallbackReady', ['fallback.bits.' + n for n in OFFER])]:
            payload = tuple(actual[n] for n in names) if actual[valid] else None
            self.holds[label].sample(payload, s[ready], 0)
        if actual['accepted.valid']:
            require(s['enq.valid'] and actual['enq.ready'] and self.pending is not None, 'unoffered actual acceptance')
            intent, context, reservation, ticket, new = self.pending
            observe(actual, {**member_fields('accepted.bits.member', intent, context, ticket),
                             **reservation_fields('accepted.bits.reservation', reservation), 'accepted.bits.newLine': int(new)})
            self.model.accept(intent, context, reservation, ticket, new)
            # The external component premise is real cache response completion
            # at ownership transfer; actual cache integration is a later gate.
            self.model.response_complete(ticket, intent.token)
            self.events['accepted'] += 1
            self.pending = None
        if s['acknowledged.valid']:
            token = Token(s['acknowledged.bits.token.tag'], s['acknowledged.bits.token.index'])
            context, ticket = self.model.tokens[token]
            expected = {**context_fields('acknowledged.bits.context', context), 'acknowledged.bits.responseTicket': ticket}
            observe(s, expected)
            self.model.ack(token, ticket)
            self.events['ack'] += 1
        event_valid = any(s[name] for name in ['acquireValid', 'refillValid', 'writebackAttach',
                                             'writebackSent', 'writebackComplete', 'victimCancel'])
        if event_valid:
            owner = Owner(s['event.context.owner.slot'], s['event.context.owner.generation'])
            run = self.model.runs[owner]
            context, reservation = run.context, run.reservation
            observe(s, event_fields('event', context, reservation))
            ticket = (s['writebackTicket.slot'], Owner(s['writebackTicket.owner.slot'], s['writebackTicket.owner.generation']))
            if s['writebackAttach']:
                require(ticket[1] == owner, 'fixture WB capture owner mismatch')
                self.model.attach_wb(context, reservation, ticket[0])
            if s['writebackSent']:
                self.model.sent_wb(context, reservation, ticket)
            if s['writebackComplete']:
                self.model.complete_wb(context, reservation, ticket)
            if s['victimCancel']:
                self.model.cancel_victim(context, reservation)
            if s['acquireValid']:
                self.model.acquire(context, reservation, reservation.mshr)
            if s['refillValid'] and actual['refillReady']:
                data = b''.join(s['refillWord' + str(i)].to_bytes(8, 'little') for i in range(8))
                self.model.refill(context, reservation, data)
        if actual['installValid']:
            owner = Owner(actual['installEvent.context.owner.slot'], actual['installEvent.context.owner.generation'])
            run = self.model.runs[owner]
            observe(actual, event_fields('installEvent', run.context, run.reservation))
            data = b''.join(actual['installWord' + str(i)].to_bytes(8, 'little') for i in range(8))
            require(data == self.model.expected_install(owner), 'actual merged line differs from raw authored bytes')
            if s['installReady']:
                self.model.install(run.context, run.reservation, data)
                self.events['install'] += 1
        if actual['drained.valid']:
            require(self.model.drains, 'unowned actual token drain')
            token = self.model.drains[0]
            context, ticket = self.model.tokens[token]
            run = self.model.runs[context.owner]
            intent = next(i for i in run.members if i.token == token)
            observe(actual, member_fields('drained.bits', intent, context, ticket))
            require(token in self.model.acknowledged and run.installed, 'drain valid before true ACK/install')
            if s['drainReady']:
                self.model.drain(token, context)
                self.events['drain'] += 1
        if actual['released.valid']:
            require(self.model.order, 'unowned actual release')
            run = self.model.runs[self.model.order[0]]
            observe(actual, event_fields('released.bits', run.context, run.reservation))
            require(run.installed and run.victim_done and all(i.token not in self.model.tokens for i in run.members),
                    'release valid before real token/WB drain')
            if s['releaseReady']:
                self.model.release(run.context, run.reservation)
                self.events['release'] += 1
        if actual['fallback.valid']:
            require(s['enq.valid'], 'fallback without original offer')
            observe(actual, {'fallback.bits.' + n: s['enq.bits.' + n] for n in OFFER})
            if s['fallbackReady']:
                require(self.pending is not None and actual['enq.ready'], 'fallback lost held original request')
                intent, _, _, _, _ = self.pending
                self.model.fallback_accept(intent, s['cacheAdmission.responseTicket'])
                self.pending = None
                self.events['fallback'] += 1
        if s['fallbackAcknowledged.valid']:
            self.model.fallback_ack(Token(s['fallbackAcknowledged.bits.token.tag'], s['fallbackAcknowledged.bits.token.index']),
                                    s['fallbackAcknowledged.bits.responseTicket'])
        if s['endEpisode']:
            self.model.end_episode(context_epoch=s['contextEpoch'])
        return actual

    def authored(self, tag, *, address=4160, value=0x1122334455667788, size=3, slot=0,
                 generation=0, ticket=0, root=None, victim=None, epoch=None):
        epoch = self.model.context_epoch if epoch is None else epoch
        intent = Intent(Token(tag, tag % 16), address, value, size, epoch)
        owner = Owner(slot, generation)
        root = root or self.model.episode_root or owner
        context = Context(owner, root, epoch, address & ~63)
        reservation = Reservation(slot, (address // 64) % 8, victim_valid=victim is not None,
                                  victim_dirty=bool(victim and victim[1]), victim_address=victim[0] if victim else 0)
        return intent, context, reservation, ticket

    def payload(self, item, *, new=True):
        intent, context, reservation, ticket = item
        offset = intent.address & 7
        data = (intent.value << (8 * offset)) & ((1 << 64) - 1)
        mask = ((1 << (1 << intent.size)) - 1) << offset
        result = {**{'enq.bits.' + name: 0 for name in OFFER},
                  'enq.valid': 1, 'enq.bits.request.address': intent.address, 'enq.bits.request.write': 1,
                  'enq.bits.request.size': intent.size, 'enq.bits.request.data': data, 'enq.bits.request.mask': mask,
                  **token_fields('enq.bits.proof.token', intent.token), 'enq.bits.proof.epoch': intent.epoch,
                  'enq.bits.proof.address': intent.address, 'enq.bits.proof.data': data,
                  'enq.bits.proof.mask': mask, 'enq.bits.proof.size': intent.size,
                  **{'enq.bits.proof.' + n: 1 for n in ['headAuthorized', 'physicalPmpAllowed', 'originalPhysical',
                                                      'integerOrigin', 'legacyPostedAccepted', 'finalChecked']},
                  'cacheAdmission.responseAvailable': 1, 'cacheAdmission.targetAbsent': 1,
                  'cacheAdmission.reservationValid': int(new),
                  'cacheAdmission.responseTicket': ticket, **reservation_fields('cacheAdmission.reservation', reservation)}
        self.pending = (intent, context, reservation, ticket, new)
        return result

    def accept(self, item, *, new=True, held=0):
        payload = self.payload(item, new=new)
        for n in range(held):
            actual = self.clock(**{**payload, 'cacheAdmission.responseAvailable': 0,
                                  'cacheAdmission.reservation.mshr': n % 2,
                                  'cacheAdmission.reservation.way': n % 2,
                                  'cacheAdmission.reservation.victimAddress': 4608 + n * 64})
            require(not actual['enq.ready'], 'held admission unexpectedly transferred')
        if held and new:
            actual = self.clock(**{**payload, 'cacheAdmission.targetAbsent': 0})
            require(not actual['enq.ready'], 'resident hit/upgrade admitted as absent-line full-data miss')
        actual = self.clock(**payload)
        require(actual['accepted.valid'], 'authored admissible store stalled')

    def ack(self, item):
        intent, context, _, ticket = item
        self.clock(**{'acknowledged.valid': 1, **member_fields('acknowledged.bits', intent, context, ticket)})

    def acquire(self, item):
        _, context, reservation, _ = item
        self.clock(**{'acquireValid': 1, **event_fields('event', context, reservation)})

    def fill_payload(self, item, *, error=False, to_t=True):
        _, context, reservation, _ = item
        data = self.model.line(context.line)
        for i in range(8):
            self.model.grant_beat(reservation.mshr, int.from_bytes(data[8 * i:8 * i + 8], 'little'), reservation.mshr,
                                  error=error, to_t=to_t)
        self.model.e(reservation.mshr)
        return {'refillValid': 1, 'refillError': int(error), 'refillToT': int(to_t), 'refillHasData': 1,
                'refillGrantAcked': 1, **event_fields('event', context, reservation),
                **{'refillWord' + str(i): int.from_bytes(data[8 * i:8 * i + 8], 'little') for i in range(8)}}

    def fill(self, item):
        require(self.clock(**self.fill_payload(item))['refillReady'], 'reserved owner failed to accept real refill')

    def consume(self, valid, ready, hold=0):
        for _ in range(hold):
            require(self.clock()[valid], 'expected held lifecycle offer absent')
        require(self.clock(**{ready: 1})[valid], 'expected lifecycle handshake absent')

    def wb(self, item, signal, slot=0):
        _, context, reservation, _ = item
        self.clock(**{signal: 1, **event_fields('event', context, reservation), 'writebackTicket.slot': slot,
                      'writebackTicket.owner.slot': context.owner.slot,
                      'writebackTicket.owner.generation': context.owner.generation})

    def finish(self, item):
        self.ack(item)
        self.acquire(item)
        self.fill(item)
        self.consume('installValid', 'installReady')
        self.consume('drained.valid', 'drainReady')
        self.consume('released.valid', 'releaseReady')

    def close(self, *, require_empty=True):
        if require_empty:
            self.clock()
            require(not self.model.busy(), 'case ended with accepted responsibility')
            self.model.flush()
        if self.child.poll() is None:
            self.child.stdin.write('quit\n')
            self.child.stdin.flush()
        code = self.child.wait(timeout=5)
        self.stderr.close()
        self.trace.close()
        require(code == 0, f'component child exit {code}')
        return {'name': self.name, 'cycles': self.cycles, 'events': self.events, 'status': 'PASS'}


def positive(executable, out):
    reports = []
    s = Scenario(executable, out, 'merge-held-ticket-reuse')
    first = s.authored((1 << 63) + 1, size=0, value=0xEA)
    s.accept(first, held=3)
    s.ack(first)
    members = [first]
    for n, address, size, value in [(2, 4162, 1, 0xA1B2), (3, 4167, 0, 0xC3),
                                     (4, 4176, 3, 0xFFEEDDCCBBAA9988), (5, 4184, 2, 0xDDEEFF00)]:
        item = s.authored((1 << 63) + n, address=address, size=size, value=value, ticket=n % 2)
        s.accept(item, new=False)
        s.ack(item)
        members.append(item)
    s.model.probe(4160)  # Synthetic pre-A N probe premise, not a real home observation.
    s.model.dma_write({4212: 0x97, 4213: 0x52})
    s.acquire(first)
    s.fill(first)
    s.consume('installValid', 'installReady', hold=3)
    for n, _ in enumerate(members):
        s.consume('drained.valid', 'drainReady', hold=2 if n == 0 else 0)
    s.consume('released.valid', 'releaseReady', hold=2)
    reports.append(s.close())

    s = Scenario(executable, out, 'two-owner-reordered-refill')
    first = s.authored(1)
    second = s.authored(2, address=4224, slot=1, generation=1, ticket=1, root=first[1].owner)
    s.accept(first); s.accept(second); s.ack(first); s.ack(second)
    s.acquire(first); s.acquire(second); s.fill(second)
    require(not s.clock()['installValid'], 'younger fill installed before older owner')
    s.fill(first)
    s.consume('installValid', 'installReady', hold=2)
    s.consume('drained.valid', 'drainReady', hold=2)
    s.consume('released.valid', 'releaseReady', hold=2)
    s.consume('installValid', 'installReady', hold=2)
    s.consume('drained.valid', 'drainReady')
    s.consume('released.valid', 'releaseReady')
    reports.append(s.close())

    for dirty in [False, True]:
        s = Scenario(executable, out, 'victim-' + ('dirty' if dirty else 'clean'))
        item = s.authored(1, victim=(4672, dirty))
        s.accept(item); s.wb(item, 'writebackAttach', 1); s.wb(item, 'writebackSent', 1)
        s.ack(item); s.acquire(item); s.fill(item)
        s.consume('installValid', 'installReady'); s.consume('drained.valid', 'drainReady')
        require(not s.clock(releaseReady=1)['released.valid'], 'owner released before exact WB ACK')
        s.wb(item, 'writebackComplete', 1)
        s.consume('released.valid', 'releaseReady', hold=2)
        reports.append(s.close())

    s = Scenario(executable, out, 'probe-cancelled-victim')
    item = s.authored(1, victim=(4672, True))
    s.accept(item)
    s.model.resident[4672] = s.model.line(4672)
    s.model.probe(4672)
    s.wb(item, 'victimCancel')
    s.finish(item)
    reports.append(s.close())

    s = Scenario(executable, out, 'probe-after-install-held-ack')
    item = s.authored(1)
    s.accept(item); s.acquire(item); s.fill(item)
    s.consume('installValid', 'installReady')
    require(not s.clock()['drained.valid'], 'token drained before real ACK')
    s.model.probe(4160); s.model.dma_write({4160: 0x19})
    s.ack(item); s.consume('drained.valid', 'drainReady'); s.consume('released.valid', 'releaseReady')
    reports.append(s.close())
    require(s.model.backing[4160] == 0x19, 'late lifecycle resurrected pre-DMA bytes')

    s = Scenario(executable, out, 'episode-context-boundary')
    first = s.authored(1)
    s.accept(first); s.finish(first)
    second = s.authored(2, address=4224, generation=1, root=first[1].owner)
    s.accept(second); s.finish(second)
    s.clock(endEpisode=1, contextEpoch=1)
    third = s.authored(3, address=4288, generation=2, epoch=1)
    s.accept(third); s.finish(third)
    reports.append(s.close())

    s = Scenario(executable, out, 'error-preserves-held-install')
    first = s.authored(1)
    second = s.authored(2, address=4224, slot=1, generation=1, ticket=1, root=first[1].owner)
    s.accept(first); s.accept(second); s.ack(first); s.ack(second)
    s.acquire(first); s.acquire(second); s.fill(first)
    require(s.clock()['installValid'], 'first install not held')
    bad = s.fill_payload(second, error=True)
    require(not s.clock(**bad)['refillReady'], 'error revoked a held success offer')
    require(not s.clock(**{**bad, 'installReady': 1})['refillReady'], 'error overlapped held offer completion')
    require(s.clock(**bad)['refillReady'], 'error did not retire after held offer completed')
    result = s.clock(drainReady=1, releaseReady=1)
    require(result['failed'] and result['busy'] and not result['drained.valid'] and not result['released.valid'],
            'post-ACK contract error erased responsibility')
    reports.append(s.close(require_empty=False))
    return reports


def tiny_generation(executable, out):
    s = Scenario(executable, out, 'generation2-exhausted-fallback', generation_bits=2)
    for generation in range(4):
        item = s.authored(generation + 1, generation=generation)
        s.accept(item); s.finish(item)
        s.model.probe(4160)
        s.clock(endEpisode=1)
    item = s.authored(5, generation=3, ticket=1)
    payload = s.payload(item)
    for n in range(4):
        result = s.clock(**{**payload, 'cacheAdmission.reservationValid': n % 2,
                            'cacheAdmission.responseTicket': n % 2, 'cacheAdmission.reservation.way': n % 2,
                            'cacheAdmission.reservation.victimAddress': 4672 + n * 64})
        require(result['exhausted'] and result['fallback.valid'] and not result['accepted.valid'],
                'exhaustion did not hold exact legacy fallback')
    s.clock(**{**payload, 'fallbackReady': 1})
    require(s.clock()['busy'], 'fallback lost its accepted responsibility')
    s.clock(**{'fallbackAcknowledged.valid': 1, **token_fields('fallbackAcknowledged.bits.token', item[0].token),
               'fallbackAcknowledged.bits.responseTicket': 1})
    return s.close()


NEGATIVES = {
    'stale-acquire': 'actual A.fire lost its reservation',
    'bad-ack': 'posted ACK must be the one real ordered',
    'duplicate-ack': 'posted ACK must be the one real ordered',
    'cancel-without-victim': 'only a genuinely removed',
    'cancel-after-capture': 'only a genuinely removed',
    'held-epoch': 'context changed while an original posted proof',
    'end-with-held': 'cohort may end only',
    'stale-refill': 'refill kind/full generation',
    'wrong-wb-ticket': 'ReleaseAck detached from captured WB generation',
    'changed-held-offer': 'held posted ingress changed',
    'reissue-cancelled-victim': 'real eviction capture must attach',
}


def negative(executable, out, name):
    s = Scenario(executable, out, name)
    item = s.authored(1, victim=(4672, True) if name in ['cancel-after-capture', 'wrong-wb-ticket',
                                                      'reissue-cancelled-victim'] else None)
    payload = s.payload(item)
    if name in ['held-epoch', 'end-with-held', 'changed-held-offer']:
        held = {**payload, 'cacheAdmission.responseAvailable': 0}
        s.clock(**held)
        bad = {**held, **({'contextEpoch': 1} if name == 'held-epoch' else
                          {'endEpisode': 1} if name == 'end-with-held' else
                          {'enq.bits.request.data': 1, 'enq.bits.proof.data': 1})}
    else:
        s.accept(item)
        if name in ['bad-ack', 'duplicate-ack']:
            if name == 'duplicate-ack': s.ack(item)
            bad = {'acknowledged.valid': 1, **member_fields('acknowledged.bits', item[0], item[1], item[3])}
            if name == 'bad-ack': bad['acknowledged.bits.token.index'] = 0
        else:
            bad = event_fields('event', item[1], item[2])
            if name == 'stale-acquire':
                bad.update({'acquireValid': 1, 'event.context.owner.generation': 1})
            elif name in ['cancel-without-victim', 'cancel-after-capture']:
                if name == 'cancel-after-capture': s.wb(item, 'writebackAttach')
                bad['victimCancel'] = 1
            elif name == 'stale-refill':
                s.acquire(item)
                bad.update({'refillValid': 1, 'event.context.owner.generation': 1})
            elif name == 'wrong-wb-ticket':
                s.wb(item, 'writebackAttach'); s.wb(item, 'writebackSent')
                bad.update({'writebackComplete': 1, 'writebackTicket.slot': 0,
                            'writebackTicket.owner.slot': 0, 'writebackTicket.owner.generation': 1})
            elif name == 'reissue-cancelled-victim':
                s.model.resident[4672] = s.model.line(4672); s.model.probe(4672)
                s.wb(item, 'victimCancel')
                bad.update({'writebackAttach': 1, 'writebackTicket.slot': 0,
                            'writebackTicket.owner.slot': 0, 'writebackTicket.owner.generation': 0})
    caught = None
    try:
        s.raw_clock(**bad)
        s.raw_clock()  # Some assertion backends report the consumed edge one call later.
    except DriverFailure as error:
        caught = str(error)
    if s.child.poll() is None:
        try:
            s.child.stdin.write('quit\n'); s.child.stdin.flush()
        except BrokenPipeError:
            pass
        s.child.wait(timeout=5)
    s.stderr.close(); s.trace.close()
    log = (caught or '') + s.stderr_path.read_text()
    require(caught is not None and NEGATIVES[name] in log, 'expected actual RTL assertion not observed: ' + name + '\n' + log)
    require(s.child.returncode != 0, 'assertion negative did not terminate the actual model')
    require('AddressSanitizer' not in log and 'runtime error:' not in log, 'sanitizer failure is not an expected negative')
    return {'name': name, 'status': 'EXPECTED_RTL_ASSERTION', 'diagnostic': NEGATIVES[name]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--generation-bits', type=int, choices=[2, 64], required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if args.generation_bits == 2:
        reports = [tiny_generation(args.executable, args.output)]
    else:
        reports = positive(args.executable, args.output)
        reports += [negative(args.executable, args.output, name) for name in NEGATIVES]
    result = {'scope': 'standalone owner environmental component; no real CPU/cache/home qualification',
              'generation_bits': args.generation_bits, 'status': 'PASS', 'cases': reports}
    (args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print('POSTED_OWNER_COMPONENT_PASS generation_bits=' + str(args.generation_bits) + ' cases=' + str(len(reports)))


if __name__ == '__main__':
    main()
