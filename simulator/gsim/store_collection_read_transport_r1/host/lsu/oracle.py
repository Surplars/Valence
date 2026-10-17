"""Direct-IO adaptation of the sealed response_state_only_flow.cpp owner oracle.

No model import, internal state access, generated accessor assumption or run on
import. observe() consumes one accepted-public-boundary observation frame. Its
state is derived only from authored offers and actual public handshakes. Public
slot observations check that state; they never create a transaction owner.
"""
import copy
from dataclasses import dataclass
from ports import INPUT_WIDTHS, OUTPUT_WIDTHS, REQUEST, RESPONSE, COMPLETE

RAM, RAM_BYTES, MASK64 = 0x80200000, 0x80000000, (1 << 64) - 1


class Violation(RuntimeError):
    pass


def check(ok, message):
    if not ok:
        raise Violation(message)


def group(frame, prefix, names):
    return {n: frame[prefix + '.' + n] for n in names}


def full_token(frame, prefix):
    return frame[prefix + '.index'], frame[prefix + '.tag']


def schema(frame, widths, extra=()):
    check(set(frame) == set(widths) | set(extra), 'SCALAR_SCHEMA: missing or unexpected field')
    for name, bits in widths.items():
        check(type(frame[name]) is int and 0 <= frame[name] < (1 << bits),
              'SCALAR_WIDTH: ' + name)


@dataclass(frozen=True)
class Op:
    name: str
    index: int
    tag: int
    address: int
    pc: int
    data: int
    beat: int
    destination: int
    size: int = 3
    atomicOp: int = 21
    epoch: int = 0x31415926
    unsigned: bool = False
    store: bool = False
    atomic: bool = False
    virtualized: bool = False
    prechecked: bool = False
    physical: int = 0
    forward: bool = False
    denied: bool = False
    parallel: bool = True
    destinationValid: bool = True
    qualified: bool = False  # Legacy BOUND-STORE qualifier, never collection authority.
    collectionRead: bool = False
    error: bool = False
    page: bool = False

    @property
    def token(self):
        return self.index, self.tag

    def mask(self):
        return ((1 << (1 << self.size)) - 1) << (self.address & 7)

    def value(self):
        bits = 8 << self.size
        shifted = self.beat >> ((self.address & 7) * 8)
        low = shifted & ((1 << bits) - 1)
        if not self.unsigned and low & (1 << (bits - 1)):
            low |= MASK64 ^ ((1 << bits) - 1)
        return low

    def destination_eligible(self):
        return self.destinationValid and self.destination != 0 and not self.store and not self.atomic

    def request(self, slot):
        return dict(returnHandle=slot, atomic=int(self.atomic), atomicOp=self.atomicOp,
            address=self.physical if self.prechecked else self.address, write=int(self.store),
            size=self.size, data=self.data if self.atomic else
                (self.data << (8 * (self.address & 7))) & MASK64,
            mask=self.mask(), virtualized=int(self.virtualized and not self.prechecked),
            precheckedLoad=int(self.prechecked), translationEpoch=self.epoch,
            prefetchNextAllowed=0, uncached=0)

    def reply(self, slot):
        return dict(returnHandle=slot, data=self.beat, error=int(self.error), pageFault=int(self.page))

    def completion(self):
        write = self.store or (self.atomic and self.atomicOp != 2)
        return {'token.index': self.index, 'token.tag': self.tag,
            'data': self.beat if self.atomic else 0 if self.store else self.value(),
            'nextPc': (self.pc + 4) & MASK64, 'exception': int(self.error or self.page),
            'cause': (15 if write else 13) if self.page else (7 if write else 5),
            'tval': self.address}

    def drive(self):
        # This first suite intentionally narrows transport to legal nonlocal
        # bare operations; unsupported classes are not silently approximated.
        check(not (self.atomic or self.virtualized or self.prechecked or self.forward or
                   self.denied or self.qualified), 'NARROW_START_PREMISE: bare nonlocal owner required')
        check(self.address % (1 << self.size) == 0 and
              RAM <= self.address < self.address + (1 << self.size) <= RAM + RAM_BYTES,
              'NARROW_START_PREMISE: aligned complete RAM interval required')
        check(not self.collectionRead or not self.store,
              'NARROW_COLLECTION_PREMISE: qualified read cannot be a store')
        d = dict.fromkeys(INPUT_WIDTHS, 0)
        d.update({'start.valid': 1, 'parallel': int(self.parallel),
            'candidateAdmission.precheckedLoad': int(self.prechecked),
            'candidateAdmission.parallel': int(self.parallel),
            'issueDestination.valid': int(self.destinationValid),
            'issueDestination.bits': self.destination,
            'boundHeadStoreOverlapQualified': int(self.qualified)})
        payload = {'token.index': self.index, 'token.tag': self.tag, 'pc': self.pc,
            'address': self.address, 'data': self.data, 'size': self.size,
            'store': int(self.store), 'atomic': int(self.atomic), 'atomicOp': self.atomicOp,
            'unsigned': int(self.unsigned), 'virtualized': int(self.virtualized),
            'precheckedLoad': int(self.prechecked), 'physicalAddress': self.physical,
            'translationEpoch': self.epoch, 'collectionHeadRead': int(self.collectionRead),
            'forward.valid': int(self.forward), 'forward.bits': self.beat,
            'accessDenied': int(self.denied)}
        d.update({'start.bits.' + k: v for k, v in payload.items()})
        return d


@dataclass
class Owner:
    op: Op
    slot: int
    phase: int = 1
    issued: bool = False
    responded: bool = False
    cancelled: bool = False
    completed: bool = False
    drained: bool = False
    publications: int = 0
    startCycle: int = 0
    issueCycle: int = 0
    responseCycle: int = 0


class Ledger:
    def __init__(self):
        self.slots = [None] * 4
        self.owners = {}
        self.pending = {}
        self.holds = {}
        self.cycle = 0
        self.lastPublished = None
        self.mutation = None
        self.anchors = []
        self.counts = dict.fromkeys(['starts', 'issues', 'responses', 'completions',
            'discards', 'publications', 'request_holds', 'qualified_holds',
            'response_holds', 'completion_stalls', 'held_cycles', 'replacements',
            'simultaneous_request_response', 'request_hold_other_start'], 0)

    def anchor(self, name):
        self.anchors.append(name)

    def hold(self, name, valid, ready, payload, message):
        if name in self.holds:
            check(valid and payload == self.holds[name], message)
        if valid and not ready:
            self.holds[name] = copy.deepcopy(payload)
        else:
            self.holds.pop(name, None)

    def find(self, token):
        check(token in self.owners, 'independent full-token owner missing')
        return self.owners[token]

    def observe(self, inputs, actual, offer=None):
        schema(inputs, INPUT_WIDTHS)
        schema(actual, OUTPUT_WIDTHS, ('cycle',))
        check(actual['cycle'] > self.cycle, 'CYCLE_MONOTONIC: observation repeated')
        self.cycle = actual['cycle']
        check(not inputs['reset'], 'RESET_ONLY_WHILE_DRAINED: reset is outside accepted-owner trace')
        check(bool(inputs['start.valid']) == (offer is not None), 'AUTHORED_START: offer validity mismatch')
        if offer:
            authored = offer.drive()
            for name in INPUT_WIDTHS:
                if name.startswith(('start.', 'issueDestination.', 'candidateAdmission.')) or name in (
                        'parallel', 'boundHeadStoreOverlapQualified'):
                    check(inputs[name] == authored[name], 'AUTHORED_START: ' + name)
        check(not any(inputs[n] for n in ['fastStoreRetire', 'fastLoadRetire', 'relaxStoreOwner.valid']),
              'NARROW_CONTROL_PREMISE: no fast retire or relaxed owner')
        cancel = [bool(inputs['cancel.' + str(s)]) for s in range(4)]
        old_slots = list(self.slots)
        old_pending = dict(self.pending)
        expectedDiscard = False
        expectedHeld = set()
        for s, owner in enumerate(old_slots):
            check(bool(actual['live.' + str(s)]) == (owner is not None), 'independent slot lifetime mismatch')
            check(actual['phase.' + str(s)] == (owner.phase if owner else 0), 'independent slot phase mismatch')
            if owner:
                check(full_token(actual, 'owner.' + str(s)) == owner.op.token, 'saved slot full-token mismatch')
                expectedDiscard |= owner.phase == 3 and (owner.cancelled or cancel[s])
                if owner.phase == 3 and not owner.cancelled and not (owner.op.error or owner.op.page) and owner.op.destination_eligible():
                    expectedHeld.add(s)
                    check(owner.publications == 1, 'HELD_WITHOUT_PUBLICATION: saved successful owner was not published exactly once')
                    check(actual[f'heldLoadValue.{s}.bits.destination'] == owner.op.destination and
                          actual[f'heldLoadValue.{s}.bits.data'] == owner.op.value(),
                          'HELD_OWNER_DATA: held destination/value differs from original accepted owner')
                    self.counts['held_cycles'] += 1
            check(bool(actual[f'heldLoadValue.{s}.valid']) == (s in expectedHeld),
                  'HELD_MASK: independent saved-owner mask mismatch')
        check(bool(actual['busy']) == any(x is not None for x in old_slots), 'independent busy lifetime mismatch')
        check(bool(actual['discarded']) == expectedDiscard, 'cancelled completion drain witness mismatch')
        completed = None
        completion = None
        destinationValid = False
        if actual['complete.valid']:
            completion = group(actual, 'complete.bits', COMPLETE)
            owner = self.find((completion['token.index'], completion['token.tag']))
            check(owner.phase == 3 and not owner.cancelled and not owner.drained and owner.responded,
                  'cancelled/non-done completion offered')
            expected = owner.op.completion()
            observedToken = (completion['token.index'], completion['token.tag'])
            if self.mutation == 'oracle-token':
                self.anchor('oracle_full_token'); observedToken = (observedToken[0], observedToken[1] ^ (1 << 63))
            check(observedToken == owner.op.token, 'ORACLE_FULL_TOKEN: original 64-bit completion token mismatch')
            expectedData = expected['data']
            if self.mutation == 'oracle-data':
                self.anchor('oracle_completion_data'); expectedData ^= 1
            check(completion['data'] == expectedData, 'ORACLE_COMPLETION_DATA: independently extracted data mismatch')
            check(all(completion[n] == expected[n] for n in ('exception', 'cause', 'tval', 'nextPc')),
                  'exact completion exception/cause/original tval/nextPc mismatch')
            destinationValid = owner.op.destination_eligible() and not (owner.op.error or owner.op.page)
            if destinationValid:
                check(actual['completedIssueDestination.bits'] == owner.op.destination,
                      'COMPLETION_DESTINATION: completed sideband lost accepted-owner destination')
            self.counts['completion_stalls'] += not inputs['complete.ready']
            if inputs['complete.ready']:
                check(not cancel[owner.slot], 'caller accepted same-edge cancelled completion')
                completed = owner
                owner.completed = owner.drained = True
                self.counts['completions'] += 1
        check(bool(actual['completedIssueDestination.valid']) == destinationValid,
              'COMPLETION_DESTINATION_VALID: independent completed-owner sideband mismatch')
        self.hold('completion', actual['complete.valid'], inputs['complete.ready'], completion,
                  'HELD_COMPLETION: held original owner changed')
        # Cancellation retains every accepted external responsibility.
        for s, owner in enumerate(old_slots):
            if owner:
                if cancel[s]:
                    check(not owner.op.store and not owner.op.atomic, 'driver cancelled irrevocable operation')
                    owner.cancelled = True
                if owner.phase == 3 and owner.cancelled:
                    check(owner.responded and s not in self.pending, 'CANCEL_DRAIN_RESPONSE: real response must precede release')
                    owner.drained = True
                    self.slots[s] = None
                    self.counts['discards'] += 1
                elif owner is completed:
                    self.slots[s] = None
            else:
                check(not cancel[s], 'driver cancelled absent slot')
        take = bool(offer and actual['start.ready'])
        self.hold('start', inputs['start.valid'], actual['start.ready'],
                  {n: inputs[n] for n in INPUT_WIDTHS if n.startswith(('start.', 'issueDestination.'))},
                  'HELD_START: producer changed held operation')
        if take:
            check(offer.token not in self.owners, 'driver reused full ROB generation')
            s = actual['ordinaryLoadCapacity.actualSlot']
            check(0 <= s < 4 and self.slots[s] is None, 'start reused undrained physical slot')
            # No canonical/relaxed-owner exceptions are used. Completion is
            # preferred; otherwise the independently empty lowest slot wins.
            expectedSlot = completed.slot if completed else next((n for n, x in enumerate(old_slots) if x is None), None)
            check(s == expectedSlot, 'START_SLOT: accepted operation differs from independent legal slot')
            owner = Owner(offer, s, startCycle=self.cycle)
            self.slots[s] = owner
            self.owners[offer.token] = owner
            self.counts['starts'] += 1
            self.counts['replacements'] += completed is not None and completed.slot == s
        check(not actual['forwarded'] and not actual['boundHeadStoreOverlapAccepted'],
              'unaccepted start produced semantic witness')
        request = None
        reqfire = bool(actual['memory.request.valid'] and inputs['memory.request.ready'])
        check(bool(actual['requestOwner.valid']) == bool(actual['memory.request.valid']),
              'LSU request missing full-token owner')
        if actual['memory.request.valid']:
            t = full_token(actual, 'requestOwner.bits')
            owner = self.find(t)
            now = group(actual, 'memory.request.bits', REQUEST)
            check(not owner.issued and not owner.drained and now == owner.op.request(owner.slot),
                  'LSU ingress fields/handle/original owner mismatch')
            check(actual['collectionHeadRead'] == int(owner.op.collectionRead),
                  'COLLECTION_READ_OWNER: sidecar differs from accepted operation')
            check(not any(actual[n + '.valid'] for n in ('postedProof', 'canonicalStoreOrigin', 'frozenStoreProof')),
                  'frozen/origin validity mismatch')
            request = (now, t, actual['collectionHeadRead'])
            self.counts['request_holds'] += not inputs['memory.request.ready']
            self.counts['qualified_holds'] += not inputs['memory.request.ready'] and owner.op.collectionRead
            self.counts['request_hold_other_start'] += bool(take and offer.token != t and not inputs['memory.request.ready'])
            if reqfire:
                check(owner.slot not in self.pending, 'RETURN_HANDLE_REUSE: original reservation still live')
                owner.issued = True; owner.issueCycle = self.cycle; owner.phase = 2
                self.pending[owner.slot] = owner
                self.counts['issues'] += 1
        else:
            check(not actual['collectionHeadRead'] and not any(actual[n + '.valid'] for n in
                ('postedProof', 'canonicalStoreOrigin', 'frozenStoreProof')), 'SIDECAR_WITHOUT_REQUEST')
        self.hold('request', actual['memory.request.valid'], inputs['memory.request.ready'], request,
                  'held LSU request or full-token owner changed')
        publication = {}
        response = group(inputs, 'memory.response.bits', RESPONSE) if inputs['memory.response.valid'] else None
        rfire = bool(inputs['memory.response.valid'] and actual['memory.response.ready'])
        if response:
            handle = response['returnHandle']
            check(bool(actual['memory.response.ready']) == (handle in old_pending),
                  'REGISTERED_RESERVATION: readiness differs from pre-edge accepted owner')
            self.counts['response_holds'] += not actual['memory.response.ready']
            if rfire:
                owner = old_pending[handle]
                check(owner.issued and not owner.responded and not owner.drained,
                      'RETURN_OWNER: unsolicited/domain/duplicate response lacks original issued owner')
                check(response == owner.op.reply(owner.slot), 'RETURN_DATA: supplied response differs from independent original reply')
                check(owner.phase == 2, 'LSU_RESPONSE_PENDING: response lacks exact pending reservation')
                owner.responded = True; owner.responseCycle = self.cycle; owner.phase = 3
                del self.pending[handle]
                self.counts['responses'] += 1
                if not owner.cancelled and not (owner.op.error or owner.op.page) and owner.op.destination_eligible():
                    publication[handle] = owner
        self.hold('response', inputs['memory.response.valid'], actual['memory.response.ready'], response,
                  'HELD_RESPONSE_PAYLOAD: external producer changed held tuple')
        self.counts['simultaneous_request_response'] += reqfire and rfire
        expectedMask = sum(1 << n for n in publication)
        actualMask = sum(actual[f'loadResultPublish.{n}.valid'] << n for n in range(4))
        if self.mutation == 'oracle-publish-valid' and expectedMask:
            self.anchor('oracle_publish_valid'); actualMask ^= expectedMask & -expectedMask
        if self.mutation == 'oracle-publish-duplicate' and not expectedMask and self.lastPublished:
            self.anchor('oracle_publish_duplicate'); actualMask |= 1 << self.lastPublished.slot
        check(actualMask == expectedMask, 'ORACLE_PUBLISH_VALID: successful accepted-owner publication mask mismatch')
        for s, owner in publication.items():
            destination = actual[f'loadResultPublish.{s}.bits']
            if self.mutation == 'oracle-publish-destination':
                self.anchor('oracle_publish_destination'); destination ^= 1
            check(destination == owner.op.destination, 'ORACLE_PUBLISH_DESTINATION: publication lost original accepted-owner destination')
            check(owner.publications == 0, 'ORACLE_PUBLISH_DUPLICATE: owner published more than once')
            owner.publications += 1
            self.counts['publications'] += 1
            self.lastPublished = owner
        return take

    def drained(self):
        check(not any(self.slots) and not self.pending and not self.holds,
              'fixture did not return to fully drained idle')
        for owner in self.owners.values():
            check(owner.drained and int(owner.completed) + int(owner.cancelled) == 1,
                  'owner not completed/cancelled/fast-retired exactly once')
            check(owner.issued and owner.responded, 'accepted owner lost transport conservation')
            expected = int(not owner.cancelled and not (owner.op.error or owner.op.page) and owner.op.destination_eligible())
            check(owner.publications == expected, 'drained owner lost successful publication or published a suppressed class')
        c = self.counts
        check(c['starts'] == c['issues'] == c['responses'] == c['completions'] + c['discards'],
              'global request/response/completion/cancel conservation mismatch')
