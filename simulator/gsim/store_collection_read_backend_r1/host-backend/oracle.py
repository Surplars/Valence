"""Independent authored-instruction, full-token and external-obligation ledger.

The only owner-creating ingress is same-cycle renamed.valid + authored allocate
payload. Passive head/start/request taps verify identities; they never invent
program order. Bare translationEpoch is inactive opaque transport state captured
at actual start.fire, never a qualification or precheck authority.
"""
from collections import Counter, deque
from dataclasses import dataclass
from decoded import MASK64, RAM, LIMIT, READ_BEAT
from ports import REQUEST_WIDTHS, PROOF_WIDTHS


class Violation(RuntimeError):
    pass


def check(ok, why):
    if not ok:
        raise Violation(why)


def schema(frame, widths, extra=()):
    check(set(frame) == set(widths) | set(extra), 'EXACT_SCALAR_SCHEMA')
    for n, w in widths.items():
        check(type(frame[n]) is int and 0 <= frame[n] < 1 << w, 'SCALAR_WIDTH: ' + n)


def token(f, p):
    return f[p + '.index'], f[p + '.tag']


def fields(f, p, names):
    return {n: f[p + '.' + n] for n in names}


@dataclass
class Owner:
    instruction: object
    token: tuple
    destination: int
    writes: bool
    expected: dict
    accepted: int
    completed: int = 0
    retired: int = 0
    started: int = 0
    lsu_accepted: int = 0
    requested: int = 0
    responded: int = 0
    epoch: int = 0

    @property
    def store(self):
        return bool(self.instruction.decoded()['store'])

    @property
    def memory(self):
        return bool(self.instruction.decoded()['memory'])

    def request(self, external=False):
        return dict(returnHandle=4 if self.store and external else 0, atomic=0, atomicOp=0,
                    address=self.expected['address'], write=int(self.store), size=3,
                    data=self.expected['store_data'], mask=255, virtualized=0,
                    precheckedLoad=0, translationEpoch=self.epoch, prefetchNextAllowed=0, uncached=0)

    def proof(self, external=False):
        return {'token.index': self.token[0], 'token.tag': self.token[1], 'epoch': 1,
                'address': self.expected['address'], 'data': self.expected['store_data'],
                'mask': 255, 'size': 3, 'headAuthorized': 1, 'physicalPmpAllowed': 1,
                'originalPhysical': 1, 'integerOrigin': 1,
                'legacyPostedAccepted': int(external), 'finalChecked': 0}

    def reply(self):
        return dict(returnHandle=4 if self.store else 0, data=0 if self.store else READ_BEAT,
                    error=0, pageFault=0)


class Ledger:
    def __init__(self):
        self.owners = {}
        self.roles = {}
        self.order = deque()
        self.registers = [0] * 32
        self.predicted = [0] * 32
        self.generations = {}
        self.pending = {}
        self.external = set()
        self.external_completed = set()
        self.holds = {}
        self.counts = Counter()
        self.events = []
        self.published = False
        self.cycle = 0

    def note(self, name, **details):
        self.events.append(dict(name=name, cycle=self.cycle, **details))

    def find(self, value):
        check(value in self.owners, 'UNKNOWN_FULL_TOKEN: ' + repr(value))
        return self.owners[value]

    def context_ready(self, f):
        check(not self.order and not self.pending and not self.external and not f['io.memoryBusy'] and
              not f['io.recovering'] and not f['io.pauseFetch'] and not f['io.pmpRawChanged'],
              'CONTEXT_PUBLICATION_REQUIRES_DRAIN')
        check(all(self.roles[r].retired for r in ('pmp-lower', 'pmp-upper', 'pmp-permissions', 'data-privilege')),
              'CONTEXT_CSR_RETIREMENT')
        check(f['io.vmState.satp'] == 0 and f['io.vmState.dataPrivilege'] == 1 and
              f['io.vmState.sum'] == f['io.vmState.mxr'] == 0 and f['io.fetchPrivilege'] == 3,
              'ACTUAL_VM_PRIVILEGE_SETUP')
        cfg = [0, 15] + [0] * 14
        addr = [RAM >> 2, LIMIT >> 2] + [0] * 14
        for n in range(16):
            check(f['io.pmpState.cfg.' + str(n)] == cfg[n] and f['io.pmpState.addr.' + str(n)] == addr[n],
                  'ACTUAL_RAW_PMP_SETUP: ' + str(n))
            # Independent TOR interval plus inactive NAPOT decoding exposed by
            # production PmpState. Preserve every public 65-bit value exactly.
            if n == 1:
                low, end, active = RAM, LIMIT - 1, 1
            else:
                mask = (((addr[n] ^ (addr[n] + 1)) << 2) | 3) & ((1 << 56) - 1)
                low = (addr[n] << 2) & ~mask
                end, active = low | mask, 0
            check((f['io.pmpState.regionLow.' + str(n)], f['io.pmpState.regionEnd.' + str(n)],
                   f['io.pmpState.regionActive.' + str(n)]) == (low, end, active),
                  'ACTUAL_DECODED_PMP_SETUP: ' + str(n))
        check(self.counts['pmp_raw_changes'] == 3, 'ACTUAL_PMP_CHANGE_PULSES')

    def publish(self, f):
        check(not self.published, 'CONTEXT_ALREADY_PUBLISHED')
        self.context_ready(f)
        self.published = True
        self.note('authored_stable_external_epoch_published', epoch=1)

    def external_complete(self, owner):
        check(owner.store and owner.token in self.external and owner.responded and owner.retired and
              not self.pending and not self.order and self.roles['head-read'].retired,
              'AUTHORED_EXTERNAL_COMPLETION_PREMISE')
        self.external.remove(owner.token)
        self.external_completed.add(owner.token)
        self.counts['external_completions'] += 1
        self.note('authored_external_posted_completion', token=list(owner.token))

    def hold(self, name, valid, ready, payload):
        if name in self.holds:
            check(valid and payload == self.holds[name], 'HELD_PAYLOAD_CHANGED: ' + name)
        if valid and not ready:
            self.holds[name] = payload
            self.counts[name + '_holds'] += 1
        else:
            self.holds.pop(name, None)

    def observe(self, inp, f, offers):
        self.cycle = f['cycle']
        before = list(self.order)
        check(inp['io.posted.externalBusy'] == int(bool(self.external)), 'EXTERNAL_BUSY_INDEPENDENT_LEDGER')
        check((inp['io.posted.contextEpoch'], inp['io.loadPrecheck.epoch'], inp['io.loadPrecheck.stable'],
               inp['io.posted.blockNew']) == ((1, 1, 1, 0) if self.published else (0, 0, 0, 1)),
              'AUTHORED_STABLE_CONTEXT')
        check(f['io.committedValue'] == self.registers[inp['io.inspectRegister']], 'ARCHITECTURAL_INSPECT')
        check(f['io.occupancy'] == len(before), 'INDEPENDENT_ROB_OCCUPANCY')
        check(bool(f['observation.headValid']) == bool(before), 'INDEPENDENT_HEAD_VALID')
        if before:
            check(token(f, 'observation.headToken') == before[0], 'INDEPENDENT_HEAD_FULL_TOKEN')
        for bad in ('io.trap.valid', 'io.headException.valid', 'io.memoryDiscarded', 'io.memoryForwarded',
                    'io.mulDivCancelled', 'io.imsic.request.valid', 'io.loadPrecheck.request.valid',
                    'io.canonicalStore.requestOrigin.valid', 'io.canonicalStore.requestFrozenProof.valid'):
            check(not f[bad], 'UNEXPECTED_PATH: ' + bad)
        if self.published:
            check(not f['io.pmpRawChanged'] and not f['io.redirect.valid'] and not f['io.recovering'] and
                  not f['io.recoveryAccepted'] and not f['io.invalidateFetch'] and not f['io.vmFlush'],
                  'LIVE_CONTEXT_OR_RECOVERY_CHANGED')
            check(f['io.vmState.satp'] == 0 and f['io.vmState.dataPrivilege'] == 1,
                  'LIVE_CONTEXT_CHANGED')
        self.counts['pmp_raw_changes'] += f['io.pmpRawChanged']
        if self.external:
            check(f['observation.postedBusy'] and f['io.memoryBusy'], 'RETAINED_EXTERNAL_BUSY')
            self.counts['external_busy_cycles'] += 1

        accepted = []
        for lane in range(2):
            p = 'io.renamed.' + str(lane)
            if not f[p + '.valid']:
                continue
            op = offers[lane]
            check(op is not None and inp['io.allocate.' + str(lane) + '.valid'], 'RENAMED_WITHOUT_AUTHORED_OFFER')
            d = op.decoded()
            check(all(inp['io.allocate.' + str(lane) + '.bits.' + k] == v for k, v in d.items()),
                  'SAME_CYCLE_AUTHORED_DECODED_BINDING')
            check(all(inp['io.rawRequests.' + str(lane) + '.' + k[7:]] == v for k, v in d.items() if k.startswith('rename.')),
                  'RAW_RENAME_REQUEST_BINDING')
            check(inp['io.rawDestinations.' + str(lane)] == d['rename.rd'], 'RAW_DESTINATION_BINDING')
            t = token(f, p + '.bits.token')
            check(t not in self.owners and op.role not in self.roles and all(x[0] != t[0] for x in self.order),
                  'FULL_TOKEN_OWNER_REUSE')
            if t[0] in self.generations:
                check(t[1] != self.generations[t[0]], 'ROB_INDEX_REUSE_REQUIRES_NEW_FULL_TAG')
                self.counts['token_reuse'] += 1
            self.generations[t[0]] = t[1]
            writes = bool(d['rename.writesRd'] and d['rename.rd'])
            check(f[p + '.bits.writesRd'] == writes and not f[p + '.bits.moveAlias'], 'EFFECTIVE_RENAME_WRITE')
            expected = op.semantics(self.predicted)
            owner = Owner(op, t, f[p + '.bits.destination'], writes, expected, self.cycle)
            self.owners[t] = self.roles[op.role] = owner
            self.order.append(t)
            if writes:
                self.predicted[d['rename.rd']] = expected['result']
            self.counts['accepted'] += 1
            self.note('accepted_authored_decoded_owner', role=op.role, token=list(t), lane=lane, word=op.word)
            accepted.append(lane)

        if f['io.redirect.valid']:
            owner = self.find(token(f, 'io.redirect.bits.token'))
            check(owner.instruction.decoded()['system'] and before == [owner.token] and not accepted and
                  f['io.redirect.bits.pc'] == owner.instruction.pc and
                  f['io.redirect.bits.target'] == owner.instruction.pc + 4,
                  'SERIALIZED_REAL_CSR_REDIRECT')
            self.counts['csr_redirects'] += 1
            self.note('actual_csr_redirect', role=owner.instruction.role, token=list(owner.token))
        if f['io.recovering'] or f['io.recoveryAccepted']:
            check(not self.published and (not before or all(self.find(t).instruction.decoded()['system'] for t in before)),
                  'UNEXPECTED_RECOVERY')

        divide = self.roles.get('older-divide')
        read = self.roles.get('head-read')
        if divide and read and before and before[0] == divide.token:
            check(read.token != divide.token and read.token in self.order and not read.started and
                  self.registers[10] == RAM and self.registers[0] == 0 and self.external,
                  'PREHEAD_ACCEPTED_READY_OWNER_PREMISE')
            check(not f['observation.eligible'] and not f['observation.start.valid'] and
                  not f['io.collectionHeadRead'] and not f['observation.lsuQualification'],
                  'YOUNGER_READ_MINTED_BEFORE_ACTUAL_HEAD')
            self.counts['prehead_suppressed_cycles'] += 1
            # Payload-only diagnostic. There is deliberately no valid scheduler
            # selection tap in this frozen model, so no selection-valid claim.
            if f['io.headProfile.candidateLoadPc'] == read.instruction.pc:
                self.counts['prehead_candidate_payload_cycles'] += 1

        start = f['observation.start.valid']
        if start:
            owner = self.find(token(f, 'observation.start.bits.token'))
            check(owner.memory and not owner.started and before and before[0] == owner.token and
                  f['observation.headPending'] and not f['observation.headDone'], 'REAL_HEAD_MEMORY_START')
            d, p = owner.instruction.decoded(), 'observation.start.bits.'
            expected = {'pc': owner.instruction.pc, 'address': owner.expected['address'],
                        'data': owner.expected['store_data'], 'atomic': 0, 'atomicOp': 0,
                        'store': int(owner.store), 'size': 3, 'unsigned': 0, 'accessDenied': 0,
                        'virtualized': 0, 'precheckedLoad': 0, 'collectionHeadRead': int(not owner.store),
                        'forward.valid': 0, 'frozenStoreProof.valid': 0, 'canonicalStoreEpoch.valid': 0,
                        'postedProof.valid': int(owner.store)}
            check(all(f[p + k] == v for k, v in expected.items()), 'PREDICTED_ACTIVE_START_FIELDS')
            if owner.store:
                check(fields(f, p + 'postedProof.bits', PROOF_WIDTHS) == owner.proof(), 'REAL_HEAD_POSTED_PROOF')
            else:
                check(self.external and inp['io.posted.externalBusy'] and f['observation.eligible'] and
                      divide.retired and self.counts['prehead_suppressed_cycles'] > 0,
                      'QUALIFIED_ACTUAL_HEAD_AUTHORITY')
            if f['observation.startReady']:
                owner.started = self.cycle
                owner.epoch = f[p + 'translationEpoch']
                self.counts['starts'] += 1
                self.counts['qualified_starts'] += int(not owner.store)
                self.note('actual_head_start', role=owner.instruction.role, token=list(owner.token),
                          opaque_inactive_translation_epoch=owner.epoch, collectionRead=int(not owner.store))
        check(f['io.posted.starting'] == int(bool(start and f['observation.startReady'] and
              f['observation.start.bits.store'])), 'POSTED_START_EVENT')

        # At each actual request boundary, every semantically active request bit
        # is independently predicted; the captured inactive epoch is transported.
        for external, valid_key, ready, prefix, qkey in (
            (False, 'observation.lsuRequest.valid', f['observation.lsuRequestReady'],
             'observation.lsuRequest.bits', 'observation.lsuQualification'),
            (True, 'io.memory.request.valid', inp['io.memory.request.ready'],
             'io.memory.request.bits', 'io.collectionHeadRead')):
            valid = f[valid_key]
            check(not f[qkey] or valid, 'QUALIFICATION_WITHOUT_REQUEST')
            payload = None
            if valid:
                request = fields(f, prefix, REQUEST_WIDTHS)
                candidates = [o for o in self.owners.values() if o.memory and o.started and
                              not (o.requested if external else o.lsu_accepted)]
                check(len(candidates) == 1, 'REQUEST_HAS_EXACT_INDEPENDENT_OWNER')
                owner = candidates[0]
                check(request == owner.request(external), 'COMPLETE_184_BIT_REQUEST: ' + ('external' if external else 'lsu'))
                check(f[qkey] == int(not owner.store), 'REQUEST_QUALIFICATION_OWNERSHIP')
                payload = (request, f[qkey])
                if external:
                    check(f['io.posted.requestProof.valid'] == int(owner.store), 'REQUEST_PROOF_CLASS')
                    if owner.store:
                        proof = fields(f, 'io.posted.requestProof.bits', PROOF_WIDTHS)
                        check(proof == owner.proof(True), 'EXTERNAL_FULL_POSTED_PROOF')
                        payload += (proof,)
                    else:
                        check(self.external and inp['io.posted.externalBusy'], 'READ_RETAINS_OLDER_EXTERNAL_OWNER')
                if ready:
                    if external:
                        handle = request['returnHandle']
                        check(handle not in self.pending, 'RETURN_HANDLE_REUSE_WITHOUT_ACCEPTED_RESPONSE')
                        self.pending[handle] = owner.token
                        owner.requested = self.cycle
                        self.counts['service_requests'] += 1
                        self.counts['qualified_requests'] += int(not owner.store)
                        if owner.store:
                            check(owner.token not in self.external_completed, 'EXTERNAL_OWNER_RECREATED')
                            self.external.add(owner.token)
                            self.counts['external_owners'] += 1
                            self.counts['posted_proofs'] += 1
                        self.note('external_request_accepted', role=owner.instruction.role, token=list(owner.token), handle=handle)
                    else:
                        owner.lsu_accepted = self.cycle
                        self.counts['lsu_requests'] += 1
            self.hold('external_request' if external else 'lsu_request', valid, ready, payload)

        if inp['io.memory.response.valid']:
            reply = fields(inp, 'io.memory.response.bits', ('returnHandle', 'data', 'error', 'pageFault'))
            handle = reply['returnHandle']
            check(handle in self.pending, 'RESPONSE_WITHOUT_ACCEPTED_SERVICE_OWNER')
            owner = self.find(self.pending[handle])
            check(reply == owner.reply() and not owner.responded, 'INDEPENDENT_RESPONSE_PAYLOAD')
            if f['io.memory.response.ready']:
                owner.responded = self.cycle
                del self.pending[handle]
                self.counts['service_responses'] += 1
                self.note('service_response_accepted', role=owner.instruction.role, token=list(owner.token))
        self.hold('service_response', inp['io.memory.response.valid'], f['io.memory.response.ready'],
                  fields(inp, 'io.memory.response.bits', ('returnHandle', 'data', 'error', 'pageFault')))

        for lane in range(2):
            p = 'io.issued.' + str(lane)
            if not f[p + '.valid']:
                continue
            owner = self.find(token(f, p + '.bits.token'))
            check(not owner.completed and not owner.retired and not f[p + '.bits.exception'] and
                  f[p + '.bits.nextPc'] == owner.instruction.pc + 4, 'ONCE_ONLY_ACCEPTED_COMPLETION')
            if not owner.instruction.decoded()['system']:
                check(f[p + '.bits.data'] == owner.expected['result'], 'INDEPENDENT_COMPLETION_VALUE')
                self.counts['ordinary_completions'] += 1
            else:
                self.counts['csr_completions'] += 1
            if owner.memory:
                check(owner.lsu_accepted and (owner.store or owner.responded), 'COMPLETION_REQUIRES_REAL_MEMORY_ACCEPTANCE')
            owner.completed = self.cycle
            self.note('accepted_completion', role=owner.instruction.role, token=list(owner.token))
        for lane in range(2):
            p = 'io.commit.' + str(lane)
            if not f[p + '.valid']:
                continue
            t = token(f, p + '.bits.token')
            check(self.order and self.order[0] == t, 'RETIREMENT_FULL_TOKEN_PROGRAM_ORDER')
            owner = self.find(t)
            d = owner.instruction.decoded()
            check(not owner.retired and (owner.completed or d['system']), 'RETIREMENT_REQUIRES_COMPLETION')
            check(f[p + '.bits.pc'] == owner.instruction.pc and f[p + '.bits.instruction'] == owner.instruction.word and
                  f[p + '.bits.rd'] == d['rename.rd'] and f[p + '.bits.writesRd'] == owner.writes and
                  f[p + '.bits.destination'] == owner.destination and f[p + '.bits.nextPc'] == owner.instruction.pc + 4,
                  'ORIGINAL_RETIRED_INSTRUCTION_AND_DESTINATION')
            if owner.writes:
                check(f[p + '.bits.data'] == owner.expected['result'], 'ARCHITECTURAL_RESULT')
                self.registers[d['rename.rd']] = owner.expected['result']
            owner.retired = self.cycle
            self.order.popleft()
            self.counts['retired'] += 1
            self.note('architectural_retirement', role=owner.instruction.role, token=list(t))
        return accepted

    def final(self, f):
        check(not self.order and not self.pending and not self.external and not self.holds and
              not f['io.memoryBusy'] and not f['io.posted.busy'] and not f['io.occupancy'], 'FINAL_INDEPENDENT_DRAIN')
        expected = dict(accepted=21, retired=21, ordinary_completions=17, starts=2, qualified_starts=1,
                        lsu_requests=2, service_requests=2, service_responses=2, qualified_requests=1,
                        external_owners=1, external_completions=1, posted_proofs=1, pmp_raw_changes=3)
        check(all(self.counts[k] == v for k, v in expected.items()), 'FINAL_EXACT_CARDINALITIES: ' + repr(dict(self.counts)))
        check(self.counts['prehead_suppressed_cycles'] >= 2 and self.counts['prehead_candidate_payload_cycles'] >= 1 and
              self.counts['external_request_holds'] >= 4, 'NONVACUOUS_HEAD_AND_HELD_TRANSPORT_WITNESSES')
        read, store = self.roles['head-read'], self.roles['posted-store']
        check(store.retired < read.accepted and store.responded < read.accepted and
              read.responded <= read.completed <= read.retired and store.token in self.external_completed,
              'FINAL_OWNER_LIFETIMES')
        check(self.registers[20] == READ_BEAT and self.registers[24] == MASK64 // 7,
              'FINAL_INDEPENDENT_ARCHITECTURAL_VALUES')
        return expected
