"""Independent event contract for a new posted-store reconstruction.

This is a host oracle, not a cycle model or CPU authorization producer. Tests
author scalar byte intent. They may assume component proof fields explicitly;
only a future executing-CPU fixture can establish production head provenance.
Synthetic schedules are not a claim of reachability through the real home.
"""

from dataclasses import dataclass, field
from collections import deque


class Violation(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise Violation(message)


@dataclass(frozen=True)
class Token:
    tag: int
    index: int


@dataclass(frozen=True)
class Owner:
    slot: int
    generation: int


@dataclass(frozen=True)
class Context:
    owner: Owner
    root: Owner
    epoch: int
    line: int


@dataclass(frozen=True)
class Reservation:
    mshr: int
    set: int
    way: int = 0
    victim_valid: bool = False
    victim_dirty: bool = False
    victim_address: int = 0


@dataclass(frozen=True)
class Intent:
    token: Token
    address: int
    value: int
    size: int = 3
    epoch: int = 0
    # Explicit environmental premises of a standalone component fixture.
    head: bool = True
    pmp: bool = True
    physical: bool = True
    integer: bool = True
    posted: bool = True
    checked: bool = True

    def bytes(self):
        require(0 <= self.size <= 3 and self.address % (1 << self.size) == 0, "scalar alignment/size")
        return {self.address + n: (self.value >> (8 * n)) & 255 for n in range(1 << self.size)}

    def proof(self):
        return self.head and self.pmp and self.physical and self.integer and self.posted and self.checked


@dataclass
class Run:
    context: Context
    reservation: Reservation
    members: list = field(default_factory=list)
    sealed: bool = False
    acquired: bool = False
    refilled: bool = False
    installed: bool = False
    base: bytes | None = None
    source: int | None = None
    wb_ticket: tuple | None = None
    wb_sent: bool = False
    victim_done: bool = False


class Contract:
    def __init__(self, memory, generation_bits=64, response_entries=2, cache_sets=8, wb_entries=2):
        require(2 <= generation_bits <= 64, "generation width")
        self.memory = dict(memory)  # Coherent visibility, independent of backing visibility.
        self.backing = dict(memory)
        self.resident = {}
        self.generation_bits = generation_bits
        self.response_entries = response_entries
        self.cache_sets = cache_sets
        self.wb_entries = wb_entries
        self.next_generation = 0
        self.exhausted = False
        self.failed = False
        self.runs = {}
        self.order = []
        self.tokens = {}
        self.responses = deque()
        self.tickets = {}
        self.acknowledged = set()
        self.drains = deque()
        self.grants = {}
        self.fallback = None
        self.removed_victims = set()
        self.episode_root = None
        self.context_epoch = 0

    def line(self, address):
        return bytes(self.memory[address + i] for i in range(64))

    def event(self, context, reservation):
        require(context.owner in self.runs, "unknown or released full owner")
        run = self.runs[context.owner]
        require(run.context == context and run.reservation == reservation, "full saved lineage changed")
        return run

    def accept(self, intent, context, reservation, ticket, new):
        require(not self.failed and self.fallback is None, "admission after failure/fallback")
        require(intent.proof(), "component lacks explicit successful physical posted premise")
        require(intent.epoch == self.context_epoch, "stale authorization at acceptance")
        require(context.line == intent.address & ~63 and context.epoch == intent.epoch, "line/epoch changed")
        require(all(a in self.memory for a in intent.bytes()), "store outside aperture")
        require(intent.token not in self.tokens and len(self.tokens) < 16, "live token reused/capacity")
        require(0 <= ticket < self.response_entries and ticket not in self.tickets, "response credit reused")
        if new:
            require(not self.exhausted, "generation exhausted")
            require(context.line not in self.resident, "new posted owner requires an actual absent-line miss")
            require(context.owner.slot in (0, 1) and len(self.runs) < 2, "line capacity")
            require(context.owner.generation == self.next_generation, "generation reused/skipped")
            require(reservation.mshr in (0, 1) and reservation.set == (context.line // 64) % self.cache_sets,
                    "physical reservation geometry")
            require(not reservation.victim_dirty or reservation.victim_valid, "dirty invalid victim")
            require(not reservation.victim_valid or (reservation.victim_address % 64 == 0 and
                    reservation.victim_address != context.line and
                    (reservation.victim_address // 64) % self.cache_sets == reservation.set), "victim geometry")
            for prior in self.runs.values():
                require(prior.context.owner.slot != context.owner.slot and prior.context.line != context.line and
                        prior.reservation.mshr != reservation.mshr and prior.reservation.set != reservation.set,
                        "live physical reservation reused")
            root = self.episode_root if self.episode_root is not None else context.owner
            require(context.root == root, "new episode did not capture its full root owner")
            for prior in self.runs.values():
                prior.sealed = True
            run = Run(context, reservation, victim_done=not reservation.victim_valid)
            self.runs[context.owner] = run
            self.order.append(context.owner)
            self.episode_root = root
            if self.next_generation == (1 << self.generation_bits) - 1:
                self.exhausted = True
            else:
                self.next_generation += 1
        else:
            run = self.event(context, reservation)
            require(self.order[-1] == context.owner and not run.sealed and not run.refilled and not run.installed,
                    "join crossed sealed/installed run")
        run.members.append(intent)
        self.tokens[intent.token] = (context, ticket)
        self.drains.append(intent.token)
        self.responses.append(intent.token)
        self.tickets[ticket] = [intent.token, False]

    def response_complete(self, ticket, token):
        require(ticket in self.tickets and self.tickets[ticket] == [token, False],
                "duplicate completion or late fill wrote a reused response ticket")
        self.tickets[ticket][1] = True

    def ack(self, token, ticket):
        require(self.responses and self.responses[0] == token and self.tickets.get(ticket) == [token, True],
                "ACK is not the actual oldest complete response handshake")
        self.responses.popleft()
        del self.tickets[ticket]
        self.acknowledged.add(token)

    def acquire(self, context, reservation, source):
        run = self.event(context, reservation)
        require(not run.acquired and source in (0, 1) and source not in self.grants, "actual A/source ownership")
        require(run.victim_done or run.wb_sent, "A preceded original victim C-last")
        run.acquired = True
        run.source = source
        self.grants[source] = dict(owner=context.owner, beats=[], sink=None, expected=None, e=False,
                                   error=False, to_t=True)

    def grant_beat(self, source, word, sink, *, error=False, to_t=True):
        require(source in self.grants, "Grant without actual A")
        grant = self.grants[source]
        require(len(grant['beats']) < 8 and (grant['sink'] is None or grant['sink'] == sink), "Grant beat/sink")
        if not grant['beats']:
            grant['expected'] = self.line(self.runs[grant['owner']].context.line)
        grant['sink'] = sink
        grant['beats'].append(word.to_bytes(8, 'little'))
        grant['error'] |= error
        grant['to_t'] &= to_t

    def e(self, source):
        grant = self.grants[source]
        require(len(grant['beats']) == 8 and not grant['e'], "E before all eight real grant beats/duplicate")
        grant['e'] = True

    def refill(self, context, reservation, data):
        run = self.event(context, reservation)
        require(run.source in self.grants and not run.refilled, "refill lost original source owner")
        grant = self.grants[run.source]
        require(grant['e'], "refill before true E")
        require(data == b''.join(grant['beats']), "engine result changed grant bytes")
        run.sealed = True
        if grant['error'] or not grant['to_t']:
            self.failed = True
            for owner in self.runs.values():
                owner.sealed = True
        else:
            require(data == grant['expected'], "refill base is not memory at coherence grant ownership")
            run.base = data
            run.refilled = True
        del self.grants[run.source]

    def expected_install(self, owner):
        run = self.runs[owner]
        require(run.base is not None, "no coherent base before fill")
        data = bytearray(run.base)
        for intent in run.members:
            for address, value in intent.bytes().items():
                data[address - run.context.line] = value
        return bytes(data)

    def install(self, context, reservation, data):
        run = self.event(context, reservation)
        require(not self.failed and run.refilled and not run.installed, "failed, premature or duplicate install")
        require(all(self.runs[o].installed for o in self.order[:self.order.index(context.owner)]), "install order")
        require(data == self.expected_install(context.owner), "merged bytes differ from authored scalar intent")
        run.installed = True
        self.memory.update({context.line + i: b for i, b in enumerate(data)})
        self.resident[context.line] = data

    def drain(self, token, context):
        require(not self.failed and self.drains and self.drains[0] == token and token in self.acknowledged,
                "drain before real ACK or out of order")
        require(self.tokens[token][0] == context and self.runs[context.owner].installed, "drain before real installation")
        self.drains.popleft()
        del self.tokens[token]

    def attach_wb(self, context, reservation, slot):
        run = self.event(context, reservation)
        require(reservation.victim_valid and not run.victim_done and run.wb_ticket is None and
                0 <= slot < self.wb_entries, "WB must attach actual valid victim once")
        require(all(r.wb_ticket is None or r.victim_done or r.wb_ticket[0] != slot for r in self.runs.values()),
                "physical WB slot reused")
        run.wb_ticket = (slot, context.owner)

    def complete_wb(self, context, reservation, ticket):
        run = self.event(context, reservation)
        require(run.wb_ticket == ticket and run.wb_sent and not run.victim_done, "ReleaseAck changed full captured ticket")
        run.victim_done = True

    def sent_wb(self, context, reservation, ticket):
        run = self.event(context, reservation)
        require(run.wb_ticket == ticket and not run.wb_sent and not run.victim_done, "C-last changed full captured ticket")
        run.wb_sent = True

    def cancel_victim(self, context, reservation):
        run = self.event(context, reservation)
        require(reservation.victim_valid and run.wb_ticket is None and not run.victim_done and
                reservation.victim_address in self.removed_victims, "invalid victim cancellation")
        run.victim_done = True
        self.removed_victims.remove(reservation.victim_address)

    def release(self, context, reservation):
        run = self.event(context, reservation)
        require(not self.failed and run.installed and run.victim_done and self.order[0] == context.owner and
                all(i.token not in self.tokens for i in run.members), "resource release preceded token/WB drain")
        del self.runs[context.owner]
        self.order.pop(0)

    def probe(self, address):
        line = address & ~63
        require(all(r.context.line != line or not r.acquired or r.installed for r in self.runs.values()),
                "probe crossed A through installation")
        if line in self.resident:
            self.backing.update({line + i: b for i, b in enumerate(self.resident.pop(line))})
            self.removed_victims.add(line)

    def dma_write(self, changes):
        for address in changes:
            line = address & ~63
            require(line not in self.resident and all(r.context.line != line or not r.acquired or r.installed
                    for r in self.runs.values()), "DMA needs completed probe and no acquired transient")
        self.memory.update(changes)
        self.backing.update(changes)

    def context_boundary(self, epoch):
        require(not self.runs and not self.tokens and self.fallback is None and self.episode_root is None,
                "context changed across responsibility or an unclosed old cohort")
        self.context_epoch = epoch

    def end_episode(self, *, accepted_upstream_busy=False, held_ingress=False, coherence_busy=False,
                    accepted_same_edge=False, context_epoch=None):
        require(not self.busy() and not accepted_upstream_busy and not held_ingress and not coherence_busy,
                "episode end omitted accepted upstream/held/coherence responsibility")
        require(not accepted_same_edge, "episode end overlapped a newly accepted posted transfer")
        self.episode_root = None
        if context_epoch is not None:
            self.context_epoch = context_epoch

    def fallback_accept(self, intent, ticket):
        require(self.exhausted and not self.runs and not self.tokens and not self.responses and self.fallback is None,
                "fallback must follow drain")
        self.fallback = (intent, ticket)

    def fallback_ack(self, token, ticket):
        require(self.fallback is not None and self.fallback[0].token == token and self.fallback[1] == ticket,
                "fallback token/response identity changed")
        self.fallback = None

    def busy(self):
        return bool(self.runs or self.tokens or self.fallback or self.failed)

    def flush(self):
        require(not self.busy(), "flush crossed posted responsibility")
        for line, data in self.resident.items():
            self.backing.update({line + i: b for i, b in enumerate(data)})
        self.resident.clear()
        require(self.backing == self.memory, "final backing bytes differ from independent coherent visibility")


class Responsibility:
    """Handshake ledger, not a producer of CPU proof. All ages are independently authored."""

    def __init__(self):
        self.owners = {}
        self.accepted_loads = set()

    def accept_posted(self, token, age, payload):
        require(token not in self.owners, "accepted physical store token reused")
        self.owners[token] = (age, 'sb', payload)

    def move(self, token, before, after, payload, reported_before_busy, reported_after_busy):
        require(token in self.owners and self.owners[token][1] == before and self.owners[token][2] == payload,
                "handoff changed complete payload or source responsibility")
        require(reported_before_busy and reported_after_busy, "responsibility handoff gap")
        age, _, _ = self.owners[token]
        self.owners[token] = (age, after, payload)

    def release(self, token):
        require(token in self.owners and self.owners[token][1] == 'cache', "release before final owner")
        del self.owners[token]

    def older_busy(self, age):
        return any(prior < age for prior, _, _ in self.owners.values())

    def may_launch_independent(self):
        return not self.owners

    def accept_load(self, token):
        require(self.may_launch_independent(), "new independent load crossed posted responsibility")
        self.accepted_loads.add(token)

    def drain_load(self, token):
        # Once accepted, no later posted-busy flag can block the load's response.
        require(token in self.accepted_loads, "unknown accepted load")
        self.accepted_loads.remove(token)


class HeldOffer:
    """Only immutable request/proof belongs here; cache admission decisions do not."""

    def __init__(self):
        self.prior = None
        self.epoch = None

    def sample(self, payload, ready, epoch):
        if self.prior is not None:
            require(payload == self.prior and epoch == self.epoch, "held full offer or authorization context changed")
        self.prior = payload if payload is not None and not ready else None
        self.epoch = epoch if self.prior is not None else None
