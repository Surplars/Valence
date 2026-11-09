#!/usr/bin/env python3
"""Stage A: independent authored-byte and full-owner contract, scalar GSIM I/O.

This is an environmental component test. Proof/response completion, A and E
inputs are authored premises, not observations of a CPU, cache SRAM or Home.
No production reachability, old-data read count, DMA, timing or speedup claim
follows. The baseline owner oracle is imported from its immutable exact source;
coverage is independently enumerated from scalar byte intents, never RTL masks.

Running this file launches only an already-built supplied component executable.
--mutations-only replays saved positive observations without running the DUT.
"""
from dataclasses import asdict, dataclass, field
import argparse
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'Valence-ethernet-cpu-line275-r1/simulator/gsim/posted_merge_rebuild'
# Load the immutable baseline helpers rather than a generated build-tree copy.
sys.path.insert(0, str(BASE))
from contract_oracle import Contract, Context, HeldOffer, Intent, Owner, Reservation, Token, Violation, require
from fixture import (Scenario as BaselineScenario, DriverFailure, context_fields,
                     event_fields, member_fields, observe, reservation_fields)
from ports import INPUTS as BASE_INPUTS, PULSES as BASE_PULSES, EVENT
sys.path.pop(0)

INPUTS = BASE_INPUTS + ['decision0Ready', 'decision1Ready']
PULSES = BASE_PULSES + ['decision0Ready', 'decision1Ready']
TIMEOUT = 256
SCOPE = ('standalone posted owner plus acquisition policy; environmental authorization, '
         'response and coherence-completion premises; no production CPU/cache/Home qualification')
TRACE_BUDGET = 2 * 1024 * 1024  # Compressed, shared by this invocation's cases.


def source_bindings():
    paths = [Path(__file__).resolve()] + [BASE / name for name in ['fixture.py', 'contract_oracle.py', 'ports.py']]
    return [{'path': str(p.relative_to(ROOT)), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
             'bytes': p.stat().st_size} for p in paths]


def check(condition, anchor, detail):
    require(condition, anchor + ': ' + detail)


def packed_item(item):
    if item is None:
        return None
    intent, context, reservation, ticket, new = item
    return {'intent': asdict(intent), 'context': asdict(context),
            'reservation': asdict(reservation), 'ticket': ticket, 'new': new}


def unpacked_item(value):
    if value is None:
        return None
    i, c, r = copy.deepcopy(value['intent']), copy.deepcopy(value['context']), value['reservation']
    i['token'] = Token(**i['token'])
    c['owner'], c['root'] = Owner(**c['owner']), Owner(**c['root'])
    return Intent(**i), Context(**c), Reservation(**r), value['ticket'], value['new']


@dataclass
class Collection:
    context: Context
    reservation: Reservation
    byte_values: dict = field(default_factory=dict)
    stores: int = 0
    elapsed: int = 0
    decided: bool = False
    permission: bool = False
    accepted_cycle: int | None = None
    held: tuple | None = None

    def full(self):
        # A set of 64 independently authored absolute addresses is the proof.
        return set(self.byte_values) == set(range(self.context.line, self.context.line + 64))


class DecisionLedger:
    def __init__(self, timeout=TIMEOUT):
        self.timeout = timeout
        self.entries = {}
        self.count = 0
        self.permission_count = 0
        self.recovery_seen = False

    def observe(self, model, pending, s, actual, cycle):
        self.recovery_seen |= bool(s['seal'])
        if self.recovery_seen and model.tokens:
            check(actual['stores'] == len(model.tokens) and actual['busy'],
                  'RECOVERY_PRESERVES_ACCEPTED_STORES', 'seal/recovery lost accepted token responsibility')
        for slot in range(2):
            prefix = 'decision' + str(slot)
            candidates = [v for k, v in self.entries.items() if k.slot == slot]
            check(len(candidates) <= 1, 'FULL_OWNER_LIFETIME', 'physical policy slot reused')
            entry = candidates[0] if candidates else None
            valid = bool(actual[prefix + 'Valid'])
            check(entry is not None or not valid, 'FULL_OWNER_LIFETIME', 'decision without live full owner')
            if entry is None:
                continue
            bits = tuple(actual[prefix + 'Event.' + n] for n in EVENT) + (actual[prefix + 'PermissionOnly'],)
            if entry.held is not None:
                check(valid and bits == entry.held, 'HELD_DECISION_IDENTITY', 'kind/context/reservation changed or withdrew')
            if valid and actual[prefix + 'PermissionOnly']:
                check(entry.full(), 'FULL_MASK_PROOF',
                      f'permission-only needs 64 distinct bytes, got {len(entry.byte_values)} from {entry.stores} stores')
            check(actual[prefix + 'Age'] == entry.elapsed, 'MONOTONIC_COLLECTION_AGE',
                  f'owner {entry.context.owner}: age {actual[prefix + "Age"]}, expected {entry.elapsed}; joins cannot restart age')
            check(valid == (entry.decided and entry.accepted_cycle is None), 'REGISTERED_DECISION_TIMING',
                  'decision offered before registered coverage/seal/timeout, disappeared, or was reoffered')
            if valid:
                observe(actual, event_fields(prefix + 'Event', entry.context, entry.reservation))
                check(bool(actual[prefix + 'PermissionOnly']) == entry.permission,
                      'FROZEN_DECISION_KIND', 'offered kind differs from frozen authored-byte proof')
                entry.held = None if s[prefix + 'Ready'] else bits
                if s[prefix + 'Ready']:
                    entry.accepted_cycle = cycle
                    self.count += 1
                    self.permission_count += int(entry.permission)
            # Evaluate the old registered collection state before adding this
            # edge's accepted scalar bytes. A final-byte join cannot feed valid.
            if not entry.decided:
                sealed = model.runs[entry.context.owner].sealed or bool(s['seal'])
                if entry.full() or sealed or entry.elapsed == self.timeout - 1:
                    entry.decided = True
                    entry.permission = entry.full()
                else:
                    entry.elapsed += 1
        if actual['accepted.valid']:
            check(pending is not None, 'AUTHORED_STORE_ACCEPTANCE', 'acceptance has no independently authored intent')
            intent, context, reservation, _, new = pending
            if new:
                check(context.owner not in self.entries, 'FULL_OWNER_LIFETIME', 'owner generation reused')
                self.entries[context.owner] = Collection(context, reservation)
            entry = self.entries[context.owner]
            check(not entry.decided and not entry.full() and (new or not s['seal']),
                  'FROZEN_COLLECTION_NO_JOIN', 'store entered a closed/frozen owner')
            entry.byte_values.update(intent.bytes())
            entry.stores += 1
            if new and s['seal']:
                # An atomic allocation+ordered-boundary owns its first bytes
                # and publishes a registered partial decision at age zero.
                entry.decided = True
                entry.permission = False
        if actual['released.valid'] and s['releaseReady']:
            owner = Owner(actual['released.bits.context.owner.slot'], actual['released.bits.context.owner.generation'])
            check(self.entries[owner].accepted_cycle is not None, 'DECISION_BEFORE_RELEASE', 'unaccepted decision released')
            del self.entries[owner]


class FullLineContract(Contract):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = DecisionLedger()
        self.cycle = 0
        self.refill_controls = None

    def acquire(self, context, reservation, source):
        entry = self.policy.entries[context.owner]
        check(entry.accepted_cycle is not None and entry.accepted_cycle < self.cycle,
              'DECISION_BEFORE_ACQUIRE', 'A did not follow an earlier accepted full-identity decision')
        super().acquire(context, reservation, source)

    def note_refill_premise(self, s):
        """Author abstract engine Grant/E completion, not a fake production TL trace."""
        self.refill_controls = s
        if not s['refillValid']:
            return
        owner = Owner(s['event.context.owner.slot'], s['event.context.owner.generation'])
        if owner not in self.runs or self.runs[owner].source not in self.grants:
            return  # The normal owner contract (or RTL assertion test) rejects it.
        grant = self.grants[self.runs[owner].source]
        if 'completion' not in grant:
            grant['completion'] = True
            grant['has_data'] = bool(s['refillHasData'])
            grant['data'] = b''.join(s['refillWord' + str(i)].to_bytes(8, 'little') for i in range(8))
            grant['expected'] = self.line(self.runs[owner].context.line) if grant['has_data'] else None
            grant['error'], grant['to_t'] = bool(s['refillError']), bool(s['refillToT'])
            grant['e'] = bool(s['refillGrantAcked'])

    def refill(self, context, reservation, data):
        run = self.event(context, reservation)
        check(run.source in self.grants and not run.refilled, 'REFILL_FULL_OWNER', 'lost original source or duplicate completion')
        grant = self.grants[run.source]
        controls = self.refill_controls
        check(grant['e'] and controls['refillGrantAcked'], 'REAL_E_BEFORE_COMPLETION', 'engine completion preceded actual E premise')
        check(data == grant['data'], 'REFILL_ENGINE_BYTES', 'held engine completion changed bytes')
        entry = self.policy.entries[context.owner]
        bad = bool(controls['refillError']) or not controls['refillToT'] or \
            (bool(controls['refillHasData']) == entry.permission) or (entry.permission and not entry.full())
        run.sealed = True
        if bad:
            self.failed = True
            for owner in self.runs.values():
                owner.sealed = True
        else:
            if controls['refillHasData']:
                check(data == grant['expected'], 'PARTIAL_COHERENT_OLD_BYTES', 'partial refill is not coherent old data')
                run.base = data
            else:
                check(entry.full() and entry.permission, 'FULL_MASK_PROOF', 'data-less completion without full frozen owner')
                # No old memory is read to create the expected full-line payload.
                run.base = bytes(64)
            run.refilled = True
        del self.grants[run.source]

    def expected_install(self, owner):
        run = self.runs[owner]
        entry = self.policy.entries[owner]
        if entry.permission:
            check(run.refilled and entry.full(), 'PERMISSION_INSTALL_PREREQUISITES', 'install before successful ownership completion')
            expected = bytes(entry.byte_values[run.context.line + i] for i in range(64))
            # Independent baseline last-writer-wins evaluation must agree too.
            check(expected == super().expected_install(owner), 'INDEPENDENT_BYTE_ORACLES', 'scalar intent enumerations disagree')
            return expected
        return super().expected_install(owner)


class Scenario(BaselineScenario):
    def __init__(self, executable, directory, name, generation_bits=64):
        self.name, self.directory = name, Path(directory)
        self.stderr_path = self.directory / (name + '.stderr')
        self.stderr = self.stderr_path.open('w')
        self.trace = gzip.open(self.directory / (name + '.jsonl.gz'), 'wt', encoding='utf-8', compresslevel=6)
        self.child = subprocess.Popen([str(Path(executable).resolve())], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1,
                                     env={**os.environ, 'ASAN_OPTIONS': 'detect_leaks=0'})
        self.initialize(generation_bits)
        self.raw_clock(reset=1)
        self.raw_clock(reset=1)
        self.raw_clock(reset=0)

    def initialize(self, generation_bits):
        self.state = dict.fromkeys(INPUTS, 0)
        self.model = FullLineContract({a: (a * 29 + 11) & 255 for a in range(4096, 8192)},
                                     generation_bits=generation_bits)
        self.pending = None
        self.holds = {name: HeldOffer() for name in ['ingress', 'install', 'drain', 'release', 'fallback']}
        self.cycles = 0
        self.checking = False
        self.events = dict.fromkeys(['accepted', 'ack', 'install', 'drain', 'release', 'fallback'], 0)

    def precheck(self, actual):
        if self.checking:
            self.model.cycle = self.cycles
            self.model.policy.observe(self.model, self.pending, self.state, actual, self.cycles)
            self.model.note_refill_premise(self.state)

    def raw_clock(self, **updates):
        self.state.update(dict.fromkeys(PULSES, 0))
        self.state.update(updates)
        require(set(updates) <= set(INPUTS), 'unknown fixture input')
        try:
            self.child.stdin.write(' '.join(k + '=' + str(int(v)) for k, v in self.state.items()) + '\n')
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
        self.trace.write(json.dumps({'input': self.state, 'actual': actual, 'authored': packed_item(self.pending),
                                     'checked': self.checking}) + '\n')
        self.trace.flush()
        check(sum(p.stat().st_size for p in self.directory.glob('*.jsonl.gz')) <= TRACE_BUDGET,
              'COMPRESSED_TRACE_BUDGET', 'lossless trace allocation exceeded 2 MiB; no uncompressed duplicate exists')
        self.precheck(actual)
        return actual

    def clock(self, **updates):
        self.checking = True
        try:
            actual = super().clock(**updates)
            if self.state['seal']:
                for run in self.model.runs.values():
                    run.sealed = True
            return actual
        finally:
            self.checking = False

    def fill_payload(self, item, *, error=False, to_t=True, has_data=None, grant_acked=True):
        _, context, reservation, _ = item
        permission = self.model.policy.entries[context.owner].permission
        has_data = not permission if has_data is None else has_data
        # Poison is deliberately unrelated to old data/full payload for Grant.
        data = self.model.line(context.line) if has_data else bytes((i * 71 + 0xD3) & 255 for i in range(64))
        return {'refillValid': 1, 'refillError': int(error), 'refillToT': int(to_t),
                'refillHasData': int(has_data), 'refillGrantAcked': int(grant_acked),
                **event_fields('event', context, reservation),
                **{'refillWord' + str(i): int.from_bytes(data[8*i:8*i+8], 'little') for i in range(8)}}

    def decide(self, item, permission, *, seal=False, hold=0):
        owner = item[1].owner
        prefix = 'decision' + str(owner.slot)
        if seal:
            self.clock(seal=1)
        # Full-mask detection is registered; a bounded loop accommodates only
        # that documented one-cycle decision-register boundary.
        for _ in range(3):
            actual = self.clock()
            if actual[prefix + 'Valid']:
                break
        else:
            raise Violation('REGISTERED_DECISION_TIMING: expected decision absent')
        check(bool(actual[prefix + 'PermissionOnly']) == permission, 'CASE_DECISION_KIND', self.name)
        for _ in range(hold):
            check(self.clock(seal=1)[prefix + 'Valid'], 'HELD_DECISION_IDENTITY', 'held decision disappeared under recovery seal')
        check(self.clock(**{prefix + 'Ready': 1})[prefix + 'Valid'], 'DECISION_HANDSHAKE', 'missing offered decision')

    def retire(self, members, *, hold=0):
        self.consume('installValid', 'installReady', hold=hold)
        for _ in members:
            self.consume('drained.valid', 'drainReady')
        self.consume('released.valid', 'releaseReady', hold=hold)

    def finish_members(self, members, permission, *, seal=False, hold=0):
        self.decide(members[0], permission, seal=seal, hold=hold)
        self.acquire(members[0])
        self.fill(members[0])
        self.retire(members, hold=hold)

    def close(self, *, require_empty=True):
        result = super().close(require_empty=require_empty)
        result.update(decisions=self.model.policy.count, permission_decisions=self.model.policy.permission_count)
        return result


def sd_members(s, *, line=4160, slot=0, generation=0, first_tag=1, root=None, repeat=None):
    members = []
    for n in range(8):
        offset = n * 8 if repeat is None else repeat
        value = int.from_bytes(bytes(((n * 53 + b * 17 + 0x91) & 255) for b in range(8)), 'little')
        item = s.authored(first_tag + n, address=line + offset, value=value, slot=slot,
                          generation=generation, ticket=n % 2, root=root)
        s.accept(item, new=(n == 0)); s.ack(item); members.append(item)
    return members


def positives(executable, out):
    reports = []
    s = Scenario(executable, out, 'full-eight-sd-held-recovery')
    members = sd_members(s)
    expected = bytes(((n * 53 + b * 17 + 0x91) & 255) for n in range(8) for b in range(8))
    s.finish_members(members, True, hold=3)
    check(s.model.line(4160) == expected, 'AUTHORED_64_BYTE_RESULT', 'eight SD result differs from separately authored 64 bytes')
    reports.append(s.close())

    s = Scenario(executable, out, 'allocation-and-seal-same-edge')
    first = s.authored(1, size=1, value=0xC5D6)
    actual = s.clock(**{**s.payload(first), 'seal': 1})
    check(actual['accepted.valid'], 'ALLOCATION_SEAL_FIRST_STORE', 'same-edge seal lost initial accepted store')
    s.ack(first)
    s.finish_members([first], False, hold=2)
    reports.append(s.close())

    s = Scenario(executable, out, 'eight-repeated-sd-not-full')
    members = sd_members(s, repeat=0)
    s.finish_members(members, False, seal=True, hold=2)
    reports.append(s.close())

    for size, beats in [(0, [0, 7]), (1, [0, 2, 5, 7]), (2, [1, 3, 5, 7])]:
        s = Scenario(executable, out, 'natural-lane-mask-size' + str(size))
        members = []
        for beat in beats:
            for lane in range(0, 8, 1 << size):
                tag = len(members) + 1
                item = s.authored(tag, address=4160 + beat*8 + lane, size=size,
                                  value=(0xFEDCBA9876543210 >> (lane*3)) & ((1 << (8 << size))-1),
                                  ticket=tag % 2)
                s.accept(item, new=not members); s.ack(item); members.append(item)
        s.finish_members(members, False, seal=True)
        reports.append(s.close())

    s = Scenario(executable, out, 'sixty-three-bytes-missing-final-byte')
    members = []
    for n in range(7):
        item = s.authored(n + 1, address=4160 + 8*n, value=0x1020304050607080 + n, ticket=n % 2)
        s.accept(item, new=(n == 0)); s.ack(item); members.append(item)
    for n in range(7):
        item = s.authored(8+n, address=4216+n, size=0, value=0xD0+n, ticket=n % 2)
        s.accept(item, new=False); s.ack(item); members.append(item)
    s.finish_members(members, False, seal=True)
    check(s.model.line(4160)[63] == ((4223 * 29 + 11) & 255), 'MISSING_BYTE_OLD_DATA', 'unwritten last byte changed')
    reports.append(s.close())

    s = Scenario(executable, out, 'last-byte-completes-last-writer-wins')
    members = []
    # 7 SD + one SW + one SH + one SB = 63 unique bytes, then overlapping
    # byte/halfword updates, then the final byte. Capacity remains <=16.
    for n in range(7):
        item = s.authored(n+1, address=4160+8*n, value=0x5544332211009988+n, ticket=n % 2)
        s.accept(item, new=(n == 0)); s.ack(item); members.append(item)
    for n, (address, size, value) in enumerate([(4216, 2, 0xFFEEDDCC), (4220, 1, 0xBBAA),
                                               (4222, 0, 0x99), (4162, 0, 0x81),
                                               (4180, 1, 0x1234), (4223, 0, 0x77)], 8):
        item = s.authored(n, address=address, size=size, value=value, ticket=n % 2)
        s.accept(item, new=False); s.ack(item); members.append(item)
    s.finish_members(members, True, seal=True)
    check(s.model.line(4160)[2] == 0x81 and s.model.line(4160)[20:22] == b'\x34\x12',
          'LAST_WRITER_WINS', 'overlapping accepted stores lost order')
    reports.append(s.close())

    s = Scenario(executable, out, 'timeout-monotonic-continuing-joins')
    first = s.authored(1, size=0, value=0x41)
    s.accept(first); s.ack(first); members = [first]
    for n in range(2, 15):
        while s.model.policy.entries[first[1].owner].elapsed < (n-1)*18:
            s.clock()
        item = s.authored(n, address=4160 + (n % 8), size=0, value=n*7, ticket=n % 2)
        s.accept(item, new=False); s.ack(item); members.append(item)
    while not s.model.policy.entries[first[1].owner].decided:
        s.clock()
    check(s.model.policy.entries[first[1].owner].elapsed == 255, 'TIMEOUT_BOUND', 'partial owner did not stop at bounded age')
    s.finish_members(members, False, hold=3)
    reports.append(s.close())

    s = Scenario(executable, out, 'partial-sparse-random-byte-overlays')
    rng = random.Random(0x50CB0C5)
    members = []
    for n in range(16):
        size = rng.randrange(4)
        offset = rng.randrange(64 >> size) << size
        item = s.authored(n+1, address=4160+offset, size=size, value=rng.getrandbits(8 << size), ticket=n % 2)
        s.accept(item, new=(n == 0)); s.ack(item); members.append(item)
    check(len(s.model.policy.entries[members[0][1].owner].byte_values) < 64, 'SCENARIO_PARTIAL_PREMISE', 'random case accidentally full')
    s.finish_members(members, False, seal=True)
    reports.append(s.close())

    s = Scenario(executable, out, 'two-owners-reordered-full-partial-grants')
    first = s.authored(1, size=0, value=0xA7)
    s.accept(first); s.ack(first)
    second = sd_members(s, line=4224, slot=1, generation=1, first_tag=2, root=first[1].owner)
    s.decide(first, False, hold=2); s.decide(second[0], True, hold=2)
    s.acquire(first); s.acquire(second[0]); s.fill(second[0])
    check(not s.clock()['installValid'], 'INSTALL_GENERATION_ORDER', 'younger owner installed before older')
    s.fill(first); s.retire([first], hold=2); s.retire(second, hold=2)
    reports.append(s.close())

    s = Scenario(executable, out, 'reused-slot-full-partial-full')
    first = sd_members(s)
    s.finish_members(first, True)
    second = s.authored(17, address=4224, generation=1, size=0, value=0x71)
    s.accept(second); s.ack(second)
    s.finish_members([second], False, seal=True)
    third = sd_members(s, line=4288, generation=2, first_tag=33)
    s.finish_members(third, True)
    reports.append(s.close())

    s = Scenario(executable, out, 'dirty-victim-full-retains-releaseack')
    first = s.authored(1, victim=(4672, True))
    s.accept(first); s.ack(first); members = [first]
    for n in range(1, 8):
        item = s.authored(n+1, address=4160+n*8, value=0xABCDEF0123456789+n, ticket=n % 2, victim=(4672, True))
        s.accept(item, new=False); s.ack(item); members.append(item)
    s.decide(first, True); s.wb(first, 'writebackAttach', 1); s.wb(first, 'writebackSent', 1)
    s.acquire(first); s.fill(first); s.consume('installValid', 'installReady')
    for _ in members: s.consume('drained.valid', 'drainReady')
    check(not s.clock(releaseReady=1)['released.valid'], 'DIRTY_VICTIM_LIFETIME', 'full target overwrite lost victim WB responsibility')
    s.wb(first, 'writebackComplete', 1); s.consume('released.valid', 'releaseReady')
    reports.append(s.close())

    s = Scenario(executable, out, 'held-full-decision-late-store-blocked')
    members = sd_members(s)
    # A held late original request must remain offered until it can transfer;
    # retiring this owner ends this scenario, with the blocked ingress retained.
    for _ in range(2): s.clock()
    late = s.authored(99, address=4160, value=0xFEEDFACE, ticket=0)
    payload = s.payload(late, new=False)
    for _ in range(4):
        actual = s.clock(**{**payload, 'seal': 1})
        check(not actual['accepted.valid'] and not actual['enq.ready'], 'FROZEN_COLLECTION_NO_JOIN', 'late store entered frozen owner')
    # Whole-fixture reset may clear an unaccepted held offer. Recovery may not.
    reports.append(s.close(require_empty=False))

    for name, full, options in [('partial-grant-failclosed', False, {'has_data': False}),
                               ('permission-grantdata-failclosed', True, {'has_data': True}),
                               ('permission-denied-failclosed', True, {'error': True}),
                               ('permission-not-toT-failclosed', True, {'to_t': False})]:
        s = Scenario(executable, out, name)
        if full:
            members = sd_members(s)
        else:
            item = s.authored(1, size=1, value=0x8152)
            s.accept(item); s.ack(item); members = [item]
        s.decide(members[0], full, seal=not full); s.acquire(members[0])
        check(s.clock(**s.fill_payload(members[0], **options))['refillReady'], 'ERROR_COMPLETION_READY', 'error was not captured')
        for _ in range(3):
            actual = s.clock(drainReady=1, releaseReady=1, installReady=1)
            check(actual['failed'] and actual['busy'] and actual['stores'] == len(members) and
                  not any(actual[k] for k in ['installValid', 'drained.valid', 'released.valid']),
                  'ERROR_RETAINS_COMMITTED_STORES', 'invalid ownership result installed or erased accepted work')
        reports.append(s.close(require_empty=False))

    s = Scenario(executable, out, 'two-owner-error-retains-held-decision')
    first = s.authored(1, size=0, value=0xA5)
    second = s.authored(2, address=4224, slot=1, generation=1, ticket=1, size=1, value=0xB6C7,
                        root=first[1].owner)
    s.accept(first); s.ack(first); s.accept(second); s.ack(second)
    s.decide(first, False)
    s.clock(seal=1); s.clock()
    s.acquire(first)
    check(s.clock(**s.fill_payload(first, error=True))['refillReady'], 'ERROR_COMPLETION_READY', 'fatal result not captured')
    for _ in range(4):
        actual = s.clock(installReady=1, drainReady=1, releaseReady=1)
        check(actual['failed'] and actual['busy'] and actual['stores'] == 2 and actual['lines'] == 2 and
              actual['decision1Valid'] and not actual['eligible'] and
              not any(actual[k] for k in ['installValid', 'drained.valid', 'released.valid']),
              'ERROR_RETAINS_OTHER_OWNER', 'fatal completion withdrew other decision or dropped accepted obligations')
    report = s.close(require_empty=False)
    report['other_decision'] = 'offered partial metadata remains held after fatal refill; no success or cancellation inferred'
    reports.append(report)

    s = Scenario(executable, out, 'error-preserves-already-held-success')
    first = sd_members(s)
    second = s.authored(17, address=4224, slot=1, generation=1, ticket=0, root=first[0][1].owner)
    s.accept(second); s.ack(second)
    s.decide(first[0], True); s.decide(second, False, seal=True)
    s.acquire(first[0]); s.acquire(second); s.fill(first[0])
    check(s.clock()['installValid'], 'HELD_SUCCESS_ERROR_ORDER', 'successful installation was not offered')
    bad = s.fill_payload(second, error=True)
    check(not s.clock(**bad)['refillReady'], 'HELD_SUCCESS_ERROR_ORDER', 'error revoked a held installation')
    check(not s.clock(**{**bad, 'installReady': 1})['refillReady'],
          'HELD_SUCCESS_ERROR_ORDER', 'error overlapped held success completion')
    check(s.clock(**bad)['refillReady'], 'HELD_SUCCESS_ERROR_ORDER', 'error was not captured after held success')
    actual = s.clock(drainReady=1, releaseReady=1)
    check(actual['failed'] and actual['busy'] and actual['stores'] == 9 and actual['lines'] == 2 and
          not actual['drained.valid'] and not actual['released.valid'],
          'ERROR_RETAINS_COMMITTED_STORES', 'fatal refill dropped accepted installed or younger obligations')
    reports.append(s.close(require_empty=False))

    s = Scenario(executable, out, 'whole-subsystem-reset-contract')
    first = s.authored(1)
    s.accept(first); s.ack(first); s.clock(seal=1); s.clock()
    check(s.model.tokens and s.model.busy(), 'RECOVERY_PRESERVES_ACCEPTED_STORES', 'seal cancelled stores')
    # Explicit coordinated reset premise: the entire standalone fixture and
    # external synthetic ledger reset together. This is never a recovery path.
    s.raw_clock(reset=1); s.raw_clock(reset=1)
    old_cycles = s.cycles
    s.initialize(64); s.cycles = old_cycles
    s.raw_clock(reset=0)
    second = s.authored(2, address=4224)
    s.accept(second); s.ack(second); s.finish_members([second], False, seal=True)
    report = s.close(); report['reset_contract'] = 'coordinated whole-fixture reset only; accepted stores are not preserved across reset'
    reports.append(report)
    return reports


def tiny_generation(executable, out):
    s = Scenario(executable, out, 'generation2-exhaustion-fallback', generation_bits=2)
    for generation in range(4):
        item = s.authored(generation+1, generation=generation)
        s.accept(item); s.ack(item); s.finish_members([item], False, seal=True)
        s.model.probe(4160); s.clock(endEpisode=1)
    item = s.authored(9, generation=3, ticket=1)
    payload = s.payload(item)
    for _ in range(3):
        actual = s.clock(**payload)
        check(actual['exhausted'] and actual['fallback.valid'] and not actual['accepted.valid'],
              'GENERATION_NO_WRAP', 'exhausted full owner generation was reused')
    s.clock(**{**payload, 'fallbackReady': 1})
    s.clock(**{'fallbackAcknowledged.valid': 1, 'fallbackAcknowledged.bits.token.tag': item[0].token.tag,
               'fallbackAcknowledged.bits.token.index': item[0].token.index,
               'fallbackAcknowledged.bits.responseTicket': 1})
    return s.close()


RTL_NEGATIVES = {
    'acquire-before-decision': 'actual A.fire preceded frozen full-line decision acceptance',
    'permission-completion-before-E': 'engine completion must follow actual Grant E',
    'stale-owner-refill': 'refill kind/full generation must select its original live posted owner',
    'changed-reservation-acquire': 'actual A.fire lost its reservation',
    'duplicate-acquire': 'actual A.fire lost its reservation',
    'duplicate-ack': 'posted ACK must be the one real ordered',
}


def rtl_negative(executable, out, name):
    s = Scenario(executable, out, name)
    if name == 'permission-completion-before-E':
        members = sd_members(s); item = members[0]
        s.decide(item, True); s.acquire(item)
        bad = s.fill_payload(item, grant_acked=False)
    else:
        item = s.authored(1)
        s.accept(item); s.ack(item)
        if name != 'acquire-before-decision': s.decide(item, False, seal=True)
        bad = {'acquireValid': 1, **event_fields('event', item[1], item[2])}
        if name == 'stale-owner-refill':
            s.acquire(item)
            bad = {**s.fill_payload(item), 'event.context.owner.generation': 1}
        elif name == 'changed-reservation-acquire': bad['event.reservation.way'] = 1
        elif name == 'duplicate-acquire': s.acquire(item)
        elif name == 'duplicate-ack': bad = {'acknowledged.valid': 1, **member_fields('acknowledged.bits', item[0], item[1], item[3])}
    caught = None
    try:
        s.raw_clock(**bad); s.raw_clock()
    except DriverFailure as error:
        caught = str(error)
    if s.child.poll() is None:
        try: s.child.stdin.write('quit\n'); s.child.stdin.flush()
        except BrokenPipeError: pass
        s.child.wait(timeout=5)
    s.stderr.close(); s.trace.close()
    log = (caught or '') + s.stderr_path.read_text()
    check(caught is not None and RTL_NEGATIVES[name] in log and s.child.returncode != 0,
          'EXPECTED_RTL_ASSERTION', name + '\n' + log)
    check('AddressSanitizer' not in log and 'runtime error:' not in log, 'SANITIZER_NOT_EXPECTED_NEGATIVE', name)
    return {'name': name, 'status': 'EXPECTED_RTL_ASSERTION', 'anchor': RTL_NEGATIVES[name]}


class Replay(Scenario):
    """Re-executes the same independent checks against saved observations."""
    def __init__(self, records):
        self.initialize(64)
        self.records = iter(records)

    def raw_clock(self, **updates):
        frame = next(self.records)
        self.state = dict(frame['input'])
        self.pending = unpacked_item(frame['authored'])
        self.cycles = frame['actual']['cycle']
        actual = frame['actual']
        self.precheck(actual)
        return actual


def replay(records):
    checked = [r for r in records if r['checked']]
    s = Replay(checked)
    for _ in checked: s.clock()


def mutations(out):
    specs = [
        ('missing-byte-permission', 'sixty-three-bytes-missing-final-byte', 'FULL_MASK_PROOF'),
        ('store-count-shortcut', 'eight-repeated-sd-not-full', 'FULL_MASK_PROOF'),
        ('age-reset-on-join', 'timeout-monotonic-continuing-joins', 'MONOTONIC_COLLECTION_AGE'),
        ('held-kind-rewrite', 'full-eight-sd-held-recovery', 'HELD_DECISION_IDENTITY'),
        ('recovery-drop', 'eight-repeated-sd-not-full', 'RECOVERY_PRESERVES_ACCEPTED_STORES'),
    ]
    reports = []
    for name, source, anchor in specs:
        with gzip.open(Path(out)/(source+'.jsonl.gz'), 'rt', encoding='utf-8') as trace:
            records = [json.loads(line) for line in trace]
        replay(copy.deepcopy(records))  # Reject a broken baseline before mutation.
        changed = False
        prior_held = False
        accepted_count = 0
        for frame in records:
            s, actual = frame['input'], frame['actual']
            if not frame['checked']: continue
            if name == 'missing-byte-permission' and actual['decision0Valid']:
                actual['decision0PermissionOnly'] = 1; changed = True
            elif name == 'store-count-shortcut' and accepted_count >= 8 and not s['seal']:
                actual['decision0Valid'], actual['decision0PermissionOnly'] = 1, 1; changed = True
            elif name == 'age-reset-on-join' and actual['accepted.valid'] and not actual['accepted.bits.newLine'] and actual['decision0Age'] > 1:
                actual['decision0Age'] = 0; changed = True
            elif name == 'held-kind-rewrite' and prior_held and actual['decision0Valid']:
                actual['decision0PermissionOnly'] ^= 1; changed = True
            elif name == 'recovery-drop' and s['seal'] and actual['stores']:
                actual['stores'], actual['lines'], actual['busy'] = 0, 0, 0; changed = True
            prior_held = bool(actual['decision0Valid'] and not s['decision0Ready'])
            accepted_count += int(actual['accepted.valid'])
            if changed:
                mutated_cycle = actual['cycle']; break
        check(changed, 'MUTATION_ANCHOR_PRESENT', name)
        caught = None
        try: replay(records)
        except Violation as error: caught = str(error)
        check(caught is not None and anchor in caught, 'PRECISE_MUTATION_REJECTION', f'{name}: {caught}')
        reports.append({'name': name, 'status': 'EXPECTED_HOST_REJECTION', 'source_case': source,
                        'mutated_cycle': mutated_cycle, 'anchor': anchor, 'diagnostic': caught})
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executable', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--generation-bits', type=int, choices=[2, 64], default=64,
                        help='must match the supplied model; 2 runs only the optional separately-built exhaustion arm')
    parser.add_argument('--mutations-only', action='store_true')
    args = parser.parse_args()
    if args.mutations_only:
        reports = mutations(args.output)
        (args.output/'mutation-result.json').write_text(json.dumps({'scope': SCOPE, 'cases': reports,
                                                                  'source_bindings': source_bindings()}, indent=2)+'\n')
        print('FULL_LINE_HOST_MUTATIONS_PASS cases=' + str(len(reports)))
        return
    parser.error('--executable is required unless --mutations-only') if args.executable is None else None
    args.output.mkdir(parents=True, exist_ok=False)
    if args.generation_bits == 2:
        reports = [tiny_generation(args.executable, args.output)]
    else:
        reports = positives(args.executable, args.output)
        reports += [rtl_negative(args.executable, args.output, name) for name in RTL_NEGATIVES]
        reports += mutations(args.output)
    result = {'scope': SCOPE, 'generation_bits': args.generation_bits, 'collection_cycles': TIMEOUT,
              'status': 'PASS', 'cases': reports, 'source_bindings': source_bindings(),
              'trace_format': 'lossless streaming gzip JSONL; every input/output sample retained',
              'trace_compressed_bytes': sum(p.stat().st_size for p in args.output.glob('*.jsonl.gz')),
              'not_exercised': ['2-bit generation exhaustion requires a separately built 2-bit model']
              if args.generation_bits == 64 else ['64-bit full-line scenario arm']}
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print('FULL_LINE_STAGE_A_PASS generation_bits=' + str(args.generation_bits) + ' cases=' + str(len(reports)))


if __name__ == '__main__':
    main()
