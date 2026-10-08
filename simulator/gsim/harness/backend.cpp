#include "RenameRobGsim.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <numeric>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#ifndef RECOVERY_WIDTH
#define RECOVERY_WIDTH 1
#endif
#ifndef FAST_HEAD_TRAP
#define FAST_HEAD_TRAP 0
#endif
#ifndef FAST_HEAD_SYSTEM
#define FAST_HEAD_SYSTEM 0
#endif

struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Request {
    bool valid = false, writes = false;
    unsigned rs1 = 0, rs2 = 0, rd = 0;
    uint64_t pc = 0;
    uint32_t instruction = 0;
};
struct Completion {
    bool valid = false, exception = false;
    Token token;
    uint64_t data = 0, cause = 0, tval = 0;
};
struct Input {
    std::array<Request, 2> allocate{};
    std::array<Completion, 2> complete{};
    bool dispatch = true, commit = false, recover = false, inclusive = false;
    bool headTrap = false, headSystem = false;
    Token boundary;
    unsigned inspect = 0;
};
struct Allocation {
    bool valid = false, writes = false, moveAlias = false;
    Token token;
    unsigned source1 = 0, source2 = 0, destination = 0, oldDestination = 0;
};
struct Retirement {
    bool valid = false, writes = false;
    Token token;
    unsigned rd = 0, destination = 0;
    uint64_t data = 0, pc = 0;
    uint32_t instruction = 0;
};
struct Output {
    std::array<Allocation, 2> allocated{};
    std::array<Retirement, 2> retired{};
    std::array<bool, 2> completed{};
};

// Only these adapters depend on GSIM accessor spelling. The scoreboard uses architectural events.
static void drive(SRenameRobGsim &dut, const Input &in) {
#define DRIVE(N) \
    dut.set_io$$complete##N##$$bits$$nextPc(0); \
    dut.set_io$$allocate##N##$$valid(in.allocate[N].valid); \
    dut.set_io$$allocate##N##$$bits$$writesRd(in.allocate[N].writes); \
    dut.set_io$$allocate##N##$$bits$$rs1(in.allocate[N].rs1); \
    dut.set_io$$allocate##N##$$bits$$rs2(in.allocate[N].rs2); \
    dut.set_io$$allocate##N##$$bits$$rd(in.allocate[N].rd); \
    dut.set_io$$allocate##N##$$bits$$pc(in.allocate[N].pc); \
    dut.set_io$$allocate##N##$$bits$$instruction(in.allocate[N].instruction); \
    dut.set_io$$complete##N##$$valid(in.complete[N].valid); \
    dut.set_io$$complete##N##$$bits$$token$$index(in.complete[N].token.index); \
    dut.set_io$$complete##N##$$bits$$token$$tag(in.complete[N].token.tag); \
    dut.set_io$$complete##N##$$bits$$data(in.complete[N].data); \
    dut.set_io$$complete##N##$$bits$$exception(in.complete[N].exception); \
    dut.set_io$$complete##N##$$bits$$cause(in.complete[N].cause); \
    dut.set_io$$complete##N##$$bits$$tval(in.complete[N].tval);
    DRIVE(0)
    DRIVE(1)
#undef DRIVE
    dut.set_io$$dispatchReady(in.dispatch);
    dut.set_io$$commitEnable(in.commit);
    dut.set_io$$recover$$valid(in.recover);
    dut.set_io$$recover$$bits$$inclusive(in.inclusive);
    dut.set_io$$recover$$bits$$token$$index(in.boundary.index);
    dut.set_io$$recover$$bits$$token$$tag(in.boundary.tag);
    dut.set_io$$inspectRegister(in.inspect);
#if FAST_HEAD_TRAP
    dut.set_io$$headTrap(in.headTrap);
#endif
#if FAST_HEAD_SYSTEM
    dut.set_io$$headSystem(in.headSystem);
#endif
}

static Output sample(SRenameRobGsim &dut) {
    Output out;
#define SAMPLE(N) \
    out.allocated[N] = {bool(dut.get_io$$renamed##N##$$valid()), \
        bool(dut.get_io$$renamed##N##$$bits$$writesRd()), \
        bool(dut.get_io$$renamed##N##$$bits$$moveAlias()), \
        {dut.get_io$$renamed##N##$$bits$$token$$index(), dut.get_io$$renamed##N##$$bits$$token$$tag()}, \
        dut.get_io$$renamed##N##$$bits$$source1(), dut.get_io$$renamed##N##$$bits$$source2(), \
        dut.get_io$$renamed##N##$$bits$$destination(), dut.get_io$$renamed##N##$$bits$$oldDestination()}; \
    out.retired[N] = {bool(dut.get_io$$commit##N##$$valid()), \
        bool(dut.get_io$$commit##N##$$bits$$writesRd()), \
        {dut.get_io$$commit##N##$$bits$$token$$index(), dut.get_io$$commit##N##$$bits$$token$$tag()}, \
        dut.get_io$$commit##N##$$bits$$rd(), dut.get_io$$commit##N##$$bits$$destination(), \
        dut.get_io$$commit##N##$$bits$$data(), dut.get_io$$commit##N##$$bits$$pc(), \
        dut.get_io$$commit##N##$$bits$$instruction()}; \
    out.completed[N] = dut.get_io$$completionAccepted##N();
    SAMPLE(0)
    SAMPLE(1)
#undef SAMPLE
    return out;
}

struct Entry {
    Token token;
    Request request;
    unsigned destination = 0, oldDestination = 0;
    bool writes = false, done = false, exception = false;
    uint64_t data = 0, cause = 0, tval = 0;
};

// Transactions in a deque and a set of available identities, not a translation of RTL arrays.
// Allocation may choose ANY available register; we do not assume the DUT's priority encoder policy.
class Scoreboard {
    SRenameRobGsim dut;
    std::array<unsigned, 32> committed{};
    std::set<unsigned> free;
    std::array<unsigned, PHYSICAL_REGS> references{};
    uint64_t nextTag = 0;
    unsigned head = 0, tail = 0;
    bool exhausted = false, recovering = false;
    size_t keep = 0;
    unsigned cycle = 0;
    bool injectHeadTrapMismatch = false, injectHeadSystemMismatch = false, injectSourceMismatch = false;
    bool injectPayloadMismatch = false;

    std::array<unsigned, 32> speculative() const {
        auto result = committed;
        for (const auto &entry : queue)
            if (entry.writes) result[entry.request.rd] = entry.destination;
        return result;
    }
    void check(bool ok, const std::string &message) const {
        if (!ok) throw std::runtime_error("cycle " + std::to_string(cycle) + ": " + message);
    }
    int position(Token token) const {
        for (size_t i = 0; i < queue.size(); ++i)
            if (queue[i].token == token) return int(i);
        return -1;
    }
    static int aliasSource(const Request &r) {
#ifdef MOVE_ALIAS
        if (!r.writes || r.rd == 0) return -1;
        const uint32_t insn = r.instruction;
        if ((insn >> 16) == 0 && ((insn >> 13) & 7) == 4 && !(insn & (1u << 12)) &&
            (insn & 3) == 2 && ((insn >> 7) & 31) == r.rd && ((insn >> 2) & 31) == r.rs2 &&
            r.rs1 == 0 && r.rs2 != 0) return int(r.rs2);
        if ((insn & 127) == 0x13 && ((insn >> 12) & 7) == 0 && (insn >> 20) == 0 &&
            ((insn >> 15) & 31) == r.rs1 && ((insn >> 7) & 31) == r.rd && r.rs1 != 0)
            return int(r.rs1);
        if ((insn & 127) == 0x33 && ((insn >> 25) & 127) == 0 && ((insn >> 12) & 7) == 0 &&
            ((insn >> 7) & 31) == r.rd && ((insn >> 15) & 31) == r.rs1 &&
            ((insn >> 20) & 31) == r.rs2) {
            if (r.rs1 == 0 && r.rs2 != 0) return int(r.rs2);
            if (r.rs2 == 0 && r.rs1 != 0) return int(r.rs1);
        }
#endif
        return -1;
    }
    void acquire(unsigned reg, bool alias) {
        check(reg < PHYSICAL_REGS, "physical register index");
        if (alias) check(references[reg] != 0 && !free.contains(reg), "alias source not owned");
        else check(references[reg] == 0 && free.erase(reg) == 1, "allocate unavailable register");
        ++references[reg];
    }
    void release(unsigned reg) {
        check(reg < PHYSICAL_REGS && references[reg] != 0, "physical owner underflow");
        if (--references[reg] == 0) check(free.insert(reg).second, "physical double free");
    }
public:
    std::deque<Entry> queue;
    std::vector<Token> history;
    unsigned allocations = 0, aliasedAllocations = 0, commits = 0, recoveries = 0, rejected = 0, dualCommits = 0;
    unsigned headTraps = 0, headTrapShrinks = 0, emptyHeadTrapRequests = 0, duplicateHeadTrapRequests = 0;
    unsigned headSystems = 0, headSystemShrinks = 0, duplicateHeadSystemRequests = 0;
    unsigned headSystemExternalTies = 0, headSystemTrapPriority = 0, headOwnerChecks = 0;

    explicit Scoreboard(bool inject = false, bool injectSystem = false, bool injectSource = false, bool injectPayload = false)
        : injectHeadTrapMismatch(inject), injectHeadSystemMismatch(injectSystem), injectSourceMismatch(injectSource),
          injectPayloadMismatch(injectPayload) {
        reset();
    }
    void reset() {
        drive(dut, Input{});
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
        queue.clear(); history.clear(); free.clear(); references.fill(0);
        for (unsigned r = 0; r < 32; ++r) committed[r] = r;
        for (unsigned r = 0; r < 32; ++r) references[r] = 1;
        for (unsigned r = 32; r < PHYSICAL_REGS; ++r) free.insert(r);
        nextTag = 0; head = tail = 0; exhausted = recovering = false; keep = 0;
    }
    bool busy() const { return recovering; }
    bool fullTag() const { return exhausted; }
    unsigned availableRegisters() const { return unsigned(free.size()); }

    Output tick(Input in = {}) {
        in.inspect %= 32;
        drive(dut, in);
        dut.step();
        Output out = sample(dut);
        // Software-oracle sensitivity only: corrupt one actually valid retirement.
        if (injectPayloadMismatch && out.retired[0].valid) {
            out.retired[0].pc ^= 4;
            injectPayloadMismatch = false;
        }
        if (injectSourceMismatch && out.allocated[1].valid) {
            out.allocated[1].source1 ^= 1;
            injectSourceMismatch = false;
        }
        check(dut.get_io$$occupancy() == queue.size(), "ROB occupancy");
        check(dut.get_io$$freeCount() == free.size(), "physical register conservation");
        check(bool(dut.get_io$$recovering()) == recovering, "recovery state");
        check(bool(dut.get_io$$tagExhausted()) == exhausted, "tag exhaustion");
        auto mapping = speculative();
        check(dut.get_io$$speculativeMapping() == mapping[in.inspect], "speculative map");
        check(dut.get_io$$committedMapping() == committed[in.inspect], "committed map");

        const int boundary = position(in.boundary);
        const size_t requestedKeep = boundary < 0 ? 0 : size_t(boundary) + !in.inclusive;
        const bool ordinaryRecovery = in.recover && boundary >= 0 && (!recovering || requestedKeep < keep);
        // Independent transaction-deque rule: a trusted head trap discards the
        // entire speculative suffix. It beats any ordinary token boundary;
        // repeating an already-all-discarding rollback does not accept twice.
        const bool headRecovery = FAST_HEAD_TRAP && in.headTrap && !queue.empty() && (!recovering || keep > 0);
        if (FAST_HEAD_TRAP && in.headTrap && queue.empty()) ++emptyHeadTrapRequests;
        if (headRecovery && recovering) ++headTrapShrinks;
        if (FAST_HEAD_TRAP && in.headTrap && recovering && keep == 0) ++duplicateHeadTrapRequests;
#if FAST_HEAD_TRAP
        bool expectedHead = headRecovery;
        if (injectHeadTrapMismatch && in.headTrap) { expectedHead = !expectedHead; injectHeadTrapMismatch = false; }
        check(bool(dut.get_io$$headTrapAccepted()) == expectedHead, "head trap acceptance oracle mismatch");
#endif
        // The software deque owns the current head identity. Neither the DUT's
        // head index nor its new headToken output determines the expected owner,
        // boundary or acknowledgement. External same-head ties retain priority.
        const bool externalHeadTie = ordinaryRecovery && boundary == 0;
        const bool systemRecovery = FAST_HEAD_SYSTEM && in.headSystem && !queue.empty() &&
            !headRecovery && !externalHeadTie && (!recovering || keep > 1);
#if FAST_HEAD_SYSTEM
        if (in.headSystem) {
            check(!queue.empty(), "test sent trusted system request without an owner");
            check(dut.get_io$$headSystemToken$$index() == queue.front().token.index &&
                dut.get_io$$headSystemToken$$tag() == queue.front().token.tag,
                "trusted head system owner oracle mismatch");
            ++headOwnerChecks;
            headSystemExternalTies += externalHeadTie && !headRecovery;
            headSystemTrapPriority += headRecovery;
            duplicateHeadSystemRequests += recovering && keep == 1 && !headRecovery && !externalHeadTie;
        }
        headSystemShrinks += systemRecovery && recovering;
        bool expectedSystem = systemRecovery;
        if (injectHeadSystemMismatch && in.headSystem) {
            expectedSystem = !expectedSystem; injectHeadSystemMismatch = false;
        }
        check(bool(dut.get_io$$headSystemAccepted()) == expectedSystem,
            "head system acceptance oracle mismatch");
#endif
        headSystems += systemRecovery;
        const bool acceptRecovery = headRecovery || systemRecovery || ordinaryRecovery;
        const bool recoveryCycle = recovering || acceptRecovery;
        if (acceptRecovery) { keep = headRecovery ? 0 : systemRecovery ? 1 : requestedKeep; ++recoveries; }
        headTraps += headRecovery;
        check(bool(dut.get_io$$recoveryAccepted()) == acceptRecovery, "recovery acceptance/age");
        const bool headFault = !queue.empty() && queue.front().done && queue.front().exception && !recoveryCycle;
        check(bool(dut.get_io$$headException$$valid()) == headFault, "precise head exception");
        if (headFault) {
            const auto &e = queue.front();
            check(dut.get_io$$headException$$bits$$token$$tag() == e.token.tag &&
                  dut.get_io$$headException$$bits$$token$$index() == e.token.index &&
                  dut.get_io$$headException$$bits$$pc() == e.request.pc &&
                  dut.get_io$$headException$$bits$$cause() == e.cause &&
                  dut.get_io$$headException$$bits$$tval() == e.tval, "exception identity/payload");
        }

        // Model accepted completions before checking retirement: a non-faulting head
        // completion can retire in this cycle, while a fault becomes visible at the
        // precise head exception boundary on the following cycle.
        std::set<std::pair<unsigned, uint64_t>> seen;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto &c = in.complete[lane];
            const int pos = position(c.token);
            const auto identity = std::make_pair(c.token.index, c.token.tag);
            const bool valid = c.valid && pos >= 0 && !queue[pos].done && !seen.contains(identity) &&
                               (!recoveryCycle || size_t(pos) < keep);
            check(out.completed[lane] == valid, "stale/duplicate/wrong-path completion filter");
            if (c.valid) seen.insert(identity);
            if (valid) {
                auto &e = queue[pos];
                e.done = true; e.data = c.data; e.exception = c.exception; e.cause = c.cause; e.tval = c.tval;
            } else if (c.valid) ++rejected;
        }

        unsigned retireCount = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = in.commit && !recoveryCycle && retireCount == lane && lane < queue.size() &&
                               queue[lane].done && !queue[lane].exception;
            const auto &actual = out.retired[lane];
            check(actual.valid == valid, "ordered commit prefix");
            if (valid) {
                const auto &e = queue[lane];
                check(actual.token == e.token && actual.rd == e.request.rd && actual.writes == e.writes &&
                      actual.destination == e.destination && actual.data == e.data &&
                      actual.pc == e.request.pc && actual.instruction == e.request.instruction, "commit record");
                ++retireCount;
            }
        }
        if (retireCount == 2) ++dualCommits;

        std::vector<Entry> newEntries;
        auto available = free;
        bool prefix = in.dispatch && !recoveryCycle && !exhausted;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto &r = in.allocate[lane];
            const auto &a = out.allocated[lane];
            const bool writes = r.writes && r.rd != 0;
            const int alias = aliasSource(r);
            const bool valid = prefix && r.valid && queue.size() + lane < ROB_ENTRIES &&
                               (!writes || alias >= 0 || !available.empty()) && !exhausted;
            check(a.valid == valid, "allocation prefix/resource backpressure");
            prefix = valid;
            if (!valid) continue;
            check(a.source1 == mapping[r.rs1] && a.source2 == mapping[r.rs2], "same-packet source mapping");
            check(a.token.index == (tail + lane) % ROB_ENTRIES && a.token.tag == nextTag, "allocation token");
            check(a.writes == writes, "x0 destination suppression");
            check(a.moveAlias == (alias >= 0), "move alias recognition");
            if (writes) {
                if (alias >= 0) check(a.destination == mapping[unsigned(alias)], "move alias mapping");
                else check(a.destination != 0 && available.erase(a.destination) == 1,
                           "unique free destination");
                check(a.oldDestination == mapping[r.rd], "same-packet WAW old mapping");
                mapping[r.rd] = a.destination;
            } else check(a.destination == 0 && a.oldDestination == 0, "no-destination metadata");
            newEntries.push_back({a.token, r, a.destination, a.oldDestination, writes});
            history.push_back(a.token);
            const uint64_t limit = UINT64_MAX >> (64 - TAG_BITS);
            if (nextTag == limit) exhausted = true;
            else ++nextTag;
        }

        if (recoveryCycle) {
            for (unsigned lane = 0; lane < RECOVERY_WIDTH && queue.size() > keep; ++lane) {
                const auto e = queue.back();
                if (e.writes) release(e.destination);
                queue.pop_back();
                tail = (tail + ROB_ENTRIES - 1) % ROB_ENTRIES;
            }
            recovering = queue.size() > keep;
        } else {
            for (unsigned i = 0; i < retireCount; ++i) {
                const auto e = queue.front(); queue.pop_front();
                if (e.writes) {
                    committed[e.request.rd] = e.destination;
                    release(e.oldDestination);
                }
                head = (head + 1) % ROB_ENTRIES;
                ++commits;
            }
            for (const auto &e : newEntries) {
                if (e.writes) acquire(e.destination, aliasSource(e.request) >= 0);
                if (aliasSource(e.request) >= 0) ++aliasedAllocations;
                queue.push_back(e);
                tail = (tail + 1) % ROB_ENTRIES;
                ++allocations;
            }
        }
        check(free.size() == size_t(std::count(references.begin(), references.end(), 0u)),
              "scoreboard free/reference agreement");
        check(std::accumulate(references.begin(), references.end(), 0u) ==
              32u + unsigned(std::count_if(queue.begin(), queue.end(), [](const Entry &e) { return e.writes; })),
              "scoreboard register ownership");
        ++cycle;
        return out;
    }
    void drain() {
        for (unsigned n = 0; n < 4 * ROB_ENTRIES + 20 && (!queue.empty() || busy()); ++n) {
            Input in; in.commit = true;
            if (!queue.empty() && queue.front().done && queue.front().exception) {
                in.recover = true; in.inclusive = true; in.boundary = queue.front().token;
            } else {
                unsigned lane = 0;
                for (const auto &e : queue) if (!e.done && lane < 2)
                    in.complete[lane++] = {true, false, e.token, e.token.tag ^ 0x12345678};
            }
            tick(in);
        }
        check(queue.empty() && !busy(), "drain progress");
        for (unsigned r = 0; r < 32; ++r) { Input in; in.inspect = r; tick(in); }
    }
};

static Request request(unsigned rd, unsigned rs1 = 0, unsigned rs2 = 0, bool writes = true) {
    return {true, writes, rs1, rs2, rd, 0x80000000ull + rd * 4, 0x13u + (rd << 7)};
}

static Request moveRequest(unsigned rd, unsigned source) {
    return {true, true, 0, source, rd, 0x80000000ull + rd * 4,
            uint32_t((4u << 13) | (rd << 7) | (source << 2) | 2u)};
}

static void headTrapTests(bool inject) {
#if FAST_HEAD_TRAP
    Scoreboard model(inject);
    Input in;
    // Empty ROB: no invented owner or recovery event; ordinary allocation is
    // still allowed in this ledger-only fixture. The CPU's empty trap itself
    // independently blocks dispatch and uses its architectural emptyPc.
    in.headTrap = true;
    in.allocate = {request(1), request(2)};
    auto first = model.tick(in);
    in = {}; in.headTrap = true; in.commit = true;
    in.allocate = {request(3), request(4)};
    in.complete = {Completion{true, false, first.allocated[0].token, 11},
                   Completion{true, false, first.allocated[1].token, 22}};
    model.tick(in);
    model.drain();

    // Simultaneous live/stale general requests cannot outrank a current-head
    // trap. Force the circular head through every index, including wraparound.
    for (unsigned round = 0; round < ROB_ENTRIES + 3; ++round) {
        in = {}; in.allocate[0] = request(5); auto advance = model.tick(in);
        in = {}; in.commit = true;
        in.complete[0] = {true, false, advance.allocated[0].token, round};
        model.tick(in);
        in = {}; in.allocate = {request(6, 5), request(7, 6)}; auto pair = model.tick(in);
        in = {}; in.headTrap = true; in.recover = true; in.commit = true;
        in.boundary = pair.allocated[1].token; in.inclusive = round & 1;
        if (round & 2) ++in.boundary.tag;
        in.complete = {Completion{true, false, pair.allocated[0].token, 33},
                       Completion{true, true, pair.allocated[1].token, 44, 2, 0xbad}};
        model.tick(in); model.drain();
        in = {}; in.allocate = {request(8), request(9)}; model.tick(in);
        in = {}; in.complete[0] = {true, false, pair.allocated[0].token, 99};
        model.tick(in); model.drain();
    }

    // Start a nonzero rollback and shrink it to the head before it finishes.
    // This is a ledger contract test; the CPU retains safeTrap's no-rollback
    // guard and never takes an unsafe automatic interrupt during restoration.
    for (unsigned i = 0; i < ROB_ENTRIES / 2; ++i) {
        in = {}; in.allocate = {request(0), request(0)}; model.tick(in);
    }
    in = {}; in.recover = true; in.boundary = model.queue[1].token;
    model.tick(in);
    in = {}; in.headTrap = true; in.commit = true;
    in.complete[0] = {true, false, model.queue.front().token, 0x55};
    model.tick(in);
    // Repeated requests while keep==0 are idempotent, even with completions.
    while (model.busy()) {
        in = {}; in.headTrap = true; in.commit = true;
        if (!model.queue.empty()) in.complete[0] = {true, false, model.queue.front().token, 0x66};
        model.tick(in);
    }
    model.drain();

    // Precise synchronous fault metadata remains unchanged until the trap
    // consumes that head. No younger architectural update is permitted.
    in = {}; in.allocate = {request(10), request(11)}; auto fault = model.tick(in);
    in = {}; in.complete[0] = {true, true, fault.allocated[0].token, 0, 2, 0xf00d};
    in.complete[1] = {true, false, fault.allocated[1].token, 77}; model.tick(in);
    in = {}; in.commit = true; model.tick(in);
    in.headTrap = true; model.tick(in); model.drain();

    // Bounded concurrent traffic: preserve the original independent mapping,
    // ownership, stale-token, same-packet and ordered-retirement checks.
    for (uint64_t seed : {UINT64_C(0x64103), UINT64_C(0x81003)}) {
        model.reset();
        std::mt19937_64 random(seed);
        for (unsigned cycle = 0; cycle < 1500; ++cycle) {
            in = {}; in.inspect = cycle % 32; in.commit = random() % 4 != 0;
            for (unsigned lane = 0; lane < 2; ++lane) {
                if (random() % 4) in.allocate[lane] = request(random() % 32, random() % 32, random() % 32);
                if (!model.queue.empty() && random() % 4) {
                    const auto &entry = model.queue[random() % model.queue.size()];
                    in.complete[lane] = {true, random() % 31 == 0, entry.token, random(), 2, random()};
                } else if (!model.history.empty()) {
                    in.complete[lane] = {true, false, model.history[random() % model.history.size()], random()};
                }
            }
            if (!model.queue.empty() && random() % 11 == 0) {
                in.recover = true; in.inclusive = random() & 1;
                in.boundary = model.queue[random() % model.queue.size()].token;
            }
            in.headTrap = random() % 17 == 0 ||
                (!model.queue.empty() && model.queue.front().done && model.queue.front().exception);
            model.tick(in);
        }
        model.drain();
    }
    if (!model.headTraps || !model.headTrapShrinks || !model.emptyHeadTrapRequests ||
        !model.duplicateHeadTrapRequests || !model.dualCommits || !model.rejected)
        throw std::runtime_error("head trap directed/random coverage incomplete");
    std::cout << "GSIM trusted head-trap ledger: PASS headTraps=" << model.headTraps
              << " activeRollbackShrinks=" << model.headTrapShrinks
              << " emptyRequests=" << model.emptyHeadTrapRequests
              << " duplicateZeroBoundary=" << model.duplicateHeadTrapRequests
              << " dualCommits=" << model.dualCommits << " rejectedCompletions=" << model.rejected
              << " seeds=2 randomCycles=3000\n";
#else
    throw std::runtime_error("head-trap short mode requires FAST_HEAD_TRAP=1");
#endif
}

static void authorizationTests(bool injectSystem, bool injectSource) {
#if FAST_HEAD_SYSTEM && FAST_HEAD_TRAP
    static_assert(TAG_BITS == 64 && ROB_ENTRIES >= 12 && RECOVERY_WIDTH >= 1 && RECOVERY_WIDTH <= 4,
        "authorization short uses a multi-cycle rollback fixture");
    Scoreboard model(false, injectSystem, injectSource);
    Input in;
    unsigned rawWaw = 0, x0 = 0, holes = 0, capacity = 0, aliasCases = 0;

    in.allocate = {request(5, 5), request(5, 5, 5)};
    model.tick(in); ++rawWaw; model.drain();
    in = {}; in.allocate = {request(0, 5, 5), request(6, 0, 0)};
    model.tick(in); ++x0; model.drain();
    in = {}; in.allocate = {request(7, 6), request(8, 7)};
    in.allocate[0].valid = false; model.tick(in); ++holes;
    in.allocate[0].valid = true; in.allocate[1].valid = false;
    model.tick(in); ++holes; model.drain();
#ifdef MOVE_ALIAS
    in = {}; in.allocate = {moveRequest(8, 9), moveRequest(10, 8)};
    model.tick(in); ++aliasCases;
    in = {}; in.allocate = {request(9, 8), moveRequest(8, 9)};
    model.tick(in); ++aliasCases; model.drain();
#endif

    model.reset();
    while (model.availableRegisters() && model.queue.size() < ROB_ENTRIES) {
        in = {}; in.allocate[0] = request(11, 11);
        if (model.availableRegisters() > 1 && model.queue.size() + 1 < ROB_ENTRIES)
            in.allocate[1] = request(12, 11);
        model.tick(in);
    }
    in = {}; in.allocate = {request(13), request(14)}; model.tick(in); ++capacity;
#ifdef MOVE_ALIAS
    if (model.queue.size() + 1 < ROB_ENTRIES) {
        in = {}; in.allocate = {moveRequest(13, 11), moveRequest(14, 13)};
        model.tick(in); ++aliasCases;
    }
#endif
    while (model.queue.size() < ROB_ENTRIES) {
        in = {}; in.allocate[0] = request(0);
        if (model.queue.size() + 1 < ROB_ENTRIES) in.allocate[1] = request(0);
        model.tick(in);
    }
    in = {}; in.commit = true; in.allocate = {request(15), request(16)};
    in.complete = {Completion{true, false, model.queue[0].token, 1},
        Completion{true, false, model.queue[1].token, 2}};
    model.tick(in); ++capacity; model.drain();

    auto fill = [&]() {
        while (model.queue.size() < ROB_ENTRIES) {
            Input next; next.allocate[0] = request(0);
            if (model.queue.size() + 1 < ROB_ENTRIES) next.allocate[1] = request(0);
            model.tick(next);
        }
    };
    // Walk every circular head using independently recorded allocation events.
    for (unsigned round = 0; round < ROB_ENTRIES + 1; ++round) {
        model.reset(); // Advance by round entries without trusting a hardware head.
        for (unsigned i = 0; i < round; ++i) {
            in = {}; in.allocate[0] = request(0); auto one = model.tick(in);
            in = {}; in.commit = true;
            in.complete[0] = {true, false, one.allocated[0].token, i}; model.tick(in);
        }
        fill();
        const Token current = model.queue.front().token;
        Token stale = current; ++stale.tag;
        in = {}; in.headSystem = true; in.commit = true;
        in.allocate = {request(17), request(18)};
        in.complete = {Completion{true, false, current, 0x1234},
            Completion{true, false, model.queue.back().token, 0xbad}};
        model.tick(in);
        while (model.busy()) {
            in = {}; in.headSystem = true; in.commit = true;
            in.complete[0] = {true, false, stale, 0xbad};
            model.tick(in);
        }
        in = {}; in.commit = true; model.tick(in); model.drain();
    }
    // A nonzero generic boundary is strictly shrunk to one retained owner.
    model.reset(); fill();
    in = {}; in.recover = true; in.boundary = model.queue[6].token; model.tick(in);
    in = {}; in.headSystem = true; model.tick(in);
    while (model.busy()) { in = {}; in.headSystem = true; model.tick(in); }
    model.drain();

    // Both exclusive and inclusive external same-head ties remain external.
    // A stale full-tag tie does not win; a younger valid token loses to head.
    for (unsigned kind = 0; kind < 4; ++kind) {
        model.reset(); fill();
        in = {}; in.headSystem = true; in.recover = true;
        in.boundary = model.queue[kind == 3 ? 2 : 0].token;
        in.inclusive = kind == 1;
        if (kind == 2) ++in.boundary.tag;
        in.complete[0] = {true, false, model.queue.front().token, 0x77};
        model.tick(in); model.drain();
    }
    // Automatic inclusive trap wins over both a system retain-one request and
    // a valid external head tie; it rejects every same-edge completion.
    model.reset(); fill();
    in = {}; in.headSystem = true; in.headTrap = true; in.recover = true;
    in.boundary = model.queue.front().token;
    in.complete[0] = {true, false, model.queue.front().token, 0x99};
    model.tick(in); model.drain();

    if (!model.headSystems || !model.headSystemShrinks || !model.duplicateHeadSystemRequests ||
        model.headSystemExternalTies != 2 || model.headSystemTrapPriority != 1 || !model.headOwnerChecks ||
        !rawWaw || !x0 || holes != 2 || capacity != 2 || !model.rejected)
        throw std::runtime_error("authorization short coverage incomplete");
#ifdef MOVE_ALIAS
    if (aliasCases < 2) throw std::runtime_error("authorization alias coverage incomplete");
#endif
    std::cout << "GSIM authorization ledger: PASS headSystems=" << model.headSystems
        << " activeShrinks=" << model.headSystemShrinks << " duplicateRetainOne=" << model.duplicateHeadSystemRequests
        << " externalHeadTies=" << model.headSystemExternalTies << " trapPriority=" << model.headSystemTrapPriority
        << " ownerChecks=" << model.headOwnerChecks << " rawWaw=" << rawWaw << " x0=" << x0
        << " validHoles=" << holes << " capacity=" << capacity << " aliases=" << aliasCases << "\n";
#else
    throw std::runtime_error("authorization short requires FAST_HEAD_SYSTEM=1 and FAST_HEAD_TRAP=1");
#endif
}

int main(int argc, char **argv) {
    if (argc == 2 && (std::string(argv[1]) == "--authorization-short" ||
            std::string(argv[1]) == "--inject-head-system-mismatch" ||
            std::string(argv[1]) == "--inject-tentative-source-mismatch")) {
        try {
            authorizationTests(std::string(argv[1]) == "--inject-head-system-mismatch",
                std::string(argv[1]) == "--inject-tentative-source-mismatch");
            return 0;
        } catch (const std::exception &error) {
            std::cerr << "GSIM authorization ledger: FAIL " << error.what() << '\n';
            return 1;
        }
    }
    if (argc == 2 && (std::string(argv[1]) == "--head-trap-short" ||
                     std::string(argv[1]) == "--inject-head-trap-mismatch")) {
        try { headTrapTests(std::string(argv[1]) == "--inject-head-trap-mismatch"); return 0; }
        catch (const std::exception &error) {
            std::cerr << "GSIM trusted head-trap ledger: FAIL " << error.what() << '\n';
            return 1;
        }
    }
    Scoreboard model(false, false, false, argc == 2 && std::string(argv[1]) == "--inject-rob-payload-mismatch");
    Input in;
    // Same-packet RAW/WAW; a younger completion cannot retire past an unfinished head.
    in.allocate = {request(5, 5), request(5, 5, 5)};
    auto pair = model.tick(in);
    in = {}; in.commit = true;
    in.complete[0] = {true, false, pair.allocated[1].token, 22};
    model.tick(in);
    in = {}; in.commit = true; model.tick(in);
    in.complete = {Completion{true, false, pair.allocated[0].token, 11},
                   Completion{true, false, pair.allocated[0].token, 999}};
    auto bypass = model.tick(in);
    if (!(bypass.retired[0].valid && bypass.retired[1].valid &&
          bypass.retired[0].data == 11 && bypass.retired[1].data == 22))
        throw std::runtime_error("head completion did not retire with the ready younger entry");
    model.drain();

#ifdef MOVE_ALIAS
    // Same-packet aliases, overwrite while shared, and a redirect through an alias.
    in = {}; in.allocate = {moveRequest(8, 9), moveRequest(10, 8)};
    auto aliases = model.tick(in);
    if (aliases.allocated[0].destination != aliases.allocated[1].destination)
        throw std::runtime_error("same-packet move alias did not share its source");
    in = {}; in.allocate = {request(9), request(8)}; model.tick(in);
    in = {}; in.recover = true; in.boundary = aliases.allocated[0].token;
    model.tick(in); model.drain();
#endif

    // Holes and downstream backpressure must not consume registers or slots.
    in = {}; in.allocate[1] = request(7); model.tick(in);
    in.allocate[0] = request(6); in.dispatch = false; model.tick(in);
    in = {}; in.allocate = {request(0), request(3, 0)}; model.tick(in);
    model.drain();

    // Branch rollback, older recovery during rollback, killed completion on the redirect cycle.
    in = {}; in.allocate = {request(0, 0, 0, false), request(8)};
    auto older = model.tick(in);
    in.allocate = {request(9), request(10)};
    auto younger = model.tick(in);
    in = {}; in.recover = true; in.boundary = older.allocated[1].token;
    in.complete[0] = {true, false, younger.allocated[1].token, 77}; model.tick(in);
    in = {}; in.recover = true; in.inclusive = true; in.boundary = older.allocated[0].token;
    model.tick(in); model.drain();
    in = {}; in.allocate[0] = request(12); model.tick(in);
    in = {}; in.complete[0] = {true, false, younger.allocated[1].token, 88}; model.tick(in);
    in.recover = true; in.boundary = younger.allocated[1].token; model.tick(in);
    model.drain();

    // Exceptions suppress their own retirement and all younger retirement.
    in = {}; in.allocate = {request(13), request(14)}; pair = model.tick(in);
    in = {}; in.commit = true;
    in.complete = {Completion{true, false, pair.allocated[0].token, 13},
                   Completion{true, true, pair.allocated[1].token, 14, 2, 0xbad}};
    bypass = model.tick(in);
    if (!(bypass.retired[0].valid && !bypass.retired[1].valid))
        throw std::runtime_error("same-cycle exception crossed the retirement boundary");
    model.tick(Input{.commit = true}); model.drain();

    // Exhaust the ROB without destinations, then exercise physical-register pressure.
    for (unsigned i = 0; i < ROB_ENTRIES / 2 + 2; ++i) {
        in = {}; in.allocate = {request(0), request(0)}; model.tick(in);
    }
    model.drain();
    for (unsigned i = 0; i < PHYSICAL_REGS; ++i) {
        in = {}; in.allocate = {request(1), request(2)}; model.tick(in);
    }
    model.drain();

    // Replayable concurrent allocate/complete/commit/redirect traffic and adversarial late tokens.
    for (uint64_t seed : {0x1234ull, 0x8badf00dull, 0xdecafbadull}) {
        model.reset();
        std::mt19937_64 random(seed);
        for (unsigned cycle = 0; cycle < 6000; ++cycle) {
            in = {}; in.inspect = cycle % 32; in.commit = random() % 4 != 0; in.dispatch = random() % 5 != 0;
            for (unsigned lane = 0; lane < 2; ++lane) {
                if (random() % 4 != 0) {
#ifdef MOVE_ALIAS
                    if (random() % 5 == 0) in.allocate[lane] = moveRequest(1 + random() % 31, 1 + random() % 31);
                    else
#endif
                        in.allocate[lane] = request(random() % 32, random() % 32, random() % 32);
                }
                if (!model.queue.empty() && random() % 4 != 0) {
                    const auto &e = model.queue[random() % model.queue.size()];
                    in.complete[lane] = {true, random() % 41 == 0, e.token, random(), 2, random()};
                } else if (!model.history.empty() && random() % 2 == 0) {
                    in.complete[lane] = {true, false, model.history[random() % model.history.size()], random()};
                }
            }
            if (!model.queue.empty() && (random() % 17 == 0 ||
                (model.queue.front().done && model.queue.front().exception))) {
                const auto &e = model.queue[random() % model.queue.size()];
                in.recover = true; in.boundary = e.token; in.inclusive = random() % 2;
                if (model.queue.front().exception) { in.boundary = model.queue.front().token; in.inclusive = true; }
            }
            model.tick(in);
            if (model.fullTag()) model.drain();
        }
        model.drain();
    }

    if constexpr (TAG_BITS == 8) {
        model.reset();
        for (unsigned i = 0; i < 140; ++i) {
            in = {}; in.allocate = {request(1), request(2)}; model.tick(in); model.drain();
        }
        if (!model.fullTag()) throw std::runtime_error("tag wraparound was not blocked");
        in = {}; in.allocate = {request(1), request(2)};
        if (model.tick(in).allocated[0].valid) throw std::runtime_error("allocation after tag exhaustion");
    }
    if (!model.dualCommits || !model.recoveries || !model.rejected)
        throw std::runtime_error("required coverage not reached");
#ifdef MOVE_ALIAS
    if (model.aliasedAllocations < 100) throw std::runtime_error("move alias coverage not reached");
#endif
    std::cout << "GSIM RenameRob: PASS rob=" << ROB_ENTRIES << " physical=" << PHYSICAL_REGS
              << " tagBits=" << TAG_BITS << " recoveryWidth=" << RECOVERY_WIDTH
              << " allocations=" << model.allocations << " commits=" << model.commits
              << " aliases=" << model.aliasedAllocations
              << " dualCommits=" << model.dualCommits << " recoveries=" << model.recoveries
              << " rejectedCompletions=" << model.rejected << " seeds=3 randomCycles=18000\n";
}
