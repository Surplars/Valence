#include "older_prefix_oracle.h"
#include <algorithm>
#include <iostream>
#include <map>
#include <random>
#include <string_view>
#ifndef OLDER_PREFIX_ORACLE_ONLY
#include "OlderPrefixRetirementGsim.h"
#endif

using namespace older_prefix;
static Request request(uint64_t serial, uint32_t opcode = 0x13) {
    return {true, (UINT64_C(0x9b13000080000000) ^ (serial * UINT64_C(0x100000004))) & ~UINT64_C(1),
        uint32_t((serial * UINT64_C(0x459ad31)) & ~UINT32_C(127)) | opcode};
}
static Completion completion(Token token, bool exception = false) {
    return {true, token, UINT64_C(0x8123456789abcdef) ^ token.tag,
        UINT64_C(0xa765432180000004) ^ (token.tag << 2), exception,
        UINT64_C(0x800000000000000d), UINT64_C(0xfedcba9876543210)};
}
static std::string mutation;
static bool mutation_fired = false;
[[maybe_unused]] static void mutate(Observation &out, const Input &in, const std::deque<Entry> &program) {
    if (mutation.empty() || mutation_fired) return;
    const int limit = locate(program, in.limit);
    bool fired = false;
    if (mutation == "checked-load" && in.limit_valid && limit == 0 && !out.retired[0].valid) {
        out.retired[0].valid = true; fired = true;
    } else if (mutation == "younger-lane" && in.limit_valid && limit == 1 && out.retired[0].valid &&
            !out.retired[1].valid) {
        out.retired[1].valid = true; fired = true;
    } else if (mutation == "stale-limit" && in.limit_valid && limit < 0 && !program.empty() &&
            in.commit && !out.recovering && !out.recovery_accepted) {
        out.retired[0].valid = true; fired = true;
    } else if (mutation == "lost-older" && in.limit_valid && limit > 0 && out.retired[0].valid) {
        out.retired[0].valid = false; fired = true;
    } else if (mutation == "global-hold" && !in.commit && in.limit_valid && !program.empty() &&
            program.front().done && !program.front().result.exception) {
        out.retired[0].valid = true; fired = true;
    } else if (mutation == "branch-hold" && in.commit && in.complete[0].valid && !(in.same_cycle & 1) &&
            !program.empty() && in.complete[0].token == program.front().token && !program.front().done) {
        out.retired[0].valid = true; fired = true;
    } else if (mutation == "recovery-owner" && in.recover && locate(program, in.boundary) < 0 &&
            !out.recovery_accepted) {
        out.recovery_accepted = true; fired = true;
    } else if (mutation == "exception" && out.head_exception) {
        out.head_exception = false; fired = true;
    } else if (mutation == "completion-owner" && in.complete[0].valid && !out.completed[0]) {
        out.completed[0] = true; fired = true;
    } else if (out.retired[0].valid) {
        if (mutation == "retire-token") { out.retired[0].token.tag ^= UINT64_C(1) << 63; fired = true; }
        if (mutation == "retire-payload") { out.retired[0].data ^= UINT64_C(1) << 63; fired = true; }
    }
    mutation_fired = fired;
}

// Pure host checks validate the oracle's written contract. No mock hardware is
// used, and these checks are never labelled GSIM or production RTL evidence.
[[maybe_unused]] static void host_contract() {
    uint64_t cases = 0, high_tags = 0;
    for (unsigned head = 0; head < capacity; ++head) {
        for (unsigned count = 0; count <= capacity; ++count) {
            std::deque<Entry> program;
            for (unsigned rank = 0; rank < count; ++rank) {
                Token token{(head + rank) % capacity, UINT64_C(0xa234567800000000) + rank};
                program.push_back({token, request(rank), true, completion(token)});
            }
            for (unsigned rank = 0; rank <= count; ++rank) {
                Input in; in.commit = true; in.limit_valid = rank != count;
                if (in.limit_valid) in.limit = program[rank].token;
                for (unsigned ready = 0; ready < 4; ++ready) {
                    for (unsigned fault = 0; fault < 4; ++fault) {
                        Oracle oracle; oracle.program = program;
                        for (unsigned n = 0; n < std::min(count, 2u); ++n) {
                            oracle.program[n].done = (ready >> n) & 1;
                            oracle.program[n].result.exception = (fault >> n) & 1;
                        }
                        const auto out = oracle.advance(in);
                        unsigned allowed = std::min(2u, rank);
                        unsigned expected = 0;
                        while (expected < allowed && ((ready >> expected) & 1) && !((fault >> expected) & 1))
                            ++expected;
                        require(out.retired[0].valid == (expected > 0) && out.retired[1].valid == (expected > 1),
                            "host contract rank/readiness/exception mismatch");
                        require(oracle.program.size() == count - expected, "host contract remaining FIFO mismatch");
                        ++cases;
                    }
                }
            }
            if (!program.empty()) for (unsigned bit = 0; bit < 64; ++bit) {
                Oracle oracle; oracle.program = program;
                Input in; in.commit = true; in.limit_valid = true; in.limit = program.back().token;
                in.limit.tag ^= UINT64_C(1) << bit;
                // Choose independent per-entry generation separation, even when the bit flip matches another tag.
                const auto out = oracle.advance(in);
                require(!out.retired[0].valid && !out.retired[1].valid, "host contract stale owner did not fail closed");
                ++high_tags;
            }
        }
    }
    // Head completion is present, but its producer forbids same-cycle retirement.
    Oracle branch;
    Input in; in.allocate = {request(1), request(2)};
    auto out = branch.advance(in);
    in = {}; in.commit = true; in.limit_valid = true; in.limit = out.allocated_token[1];
    in.complete[0] = completion(out.allocated_token[0]); in.same_cycle = 0;
    out = branch.advance(in); require(!out.retired[0].valid, "host branch handoff bypassed");
    in.complete = {}; out = branch.advance(in); require(out.retired[0].valid, "host branch handoff lost completion");
    // Observation comparison must reject an extra retirement independent of valid payload.
    Observation expected, corrupt; corrupt.retired[1].valid = true;
    bool rejected = false;
    try { compare(corrupt, expected); } catch (const std::runtime_error &) { rejected = true; }
    require(rejected, "host comparison negative control escaped");
    std::cout << "HOST_ORACLE_ONLY: PASS rankReadinessFaultCases=" << cases << " staleGenerationBits=" << high_tags
        << " comparisonNegative=1; no production RTL executed\n";
}

#ifndef OLDER_PREFIX_ORACLE_ONLY
static void drive(SOlderPrefixRetirementGsim &dut, const Input &in) {
#define DRIVE(N) \
    dut.set_io$$allocate##N##$$valid(in.allocate[N].valid); \
    dut.set_io$$allocate##N##$$bits$$writesRd(0); \
    dut.set_io$$allocate##N##$$bits$$rs1(0); \
    dut.set_io$$allocate##N##$$bits$$rs2(0); \
    dut.set_io$$allocate##N##$$bits$$rd(0); \
    dut.set_io$$allocate##N##$$bits$$pc(in.allocate[N].pc); \
    dut.set_io$$allocate##N##$$bits$$instruction(in.allocate[N].instruction); \
    dut.set_io$$complete##N##$$valid(in.complete[N].valid); \
    dut.set_io$$complete##N##$$bits$$token$$index(in.complete[N].token.index); \
    dut.set_io$$complete##N##$$bits$$token$$tag(in.complete[N].token.tag); \
    dut.set_io$$complete##N##$$bits$$data(in.complete[N].data); \
    dut.set_io$$complete##N##$$bits$$nextPc(in.complete[N].next_pc); \
    dut.set_io$$complete##N##$$bits$$exception(in.complete[N].exception); \
    dut.set_io$$complete##N##$$bits$$cause(in.complete[N].cause); \
    dut.set_io$$complete##N##$$bits$$tval(in.complete[N].tval);
    DRIVE(0) DRIVE(1)
#undef DRIVE
    dut.set_io$$sameCycleRetire(in.same_cycle);
    dut.set_io$$fastHeadRetire$$valid(in.fast.valid);
    dut.set_io$$fastHeadRetire$$bits$$token$$index(in.fast.token.index);
    dut.set_io$$fastHeadRetire$$bits$$token$$tag(in.fast.token.tag);
    dut.set_io$$fastHeadRetire$$bits$$data(in.fast.data);
    dut.set_io$$fastHeadRetire$$bits$$nextPc(in.fast.next_pc);
    dut.set_io$$fastHeadRetire$$bits$$exception(in.fast.exception);
    dut.set_io$$fastHeadRetire$$bits$$cause(in.fast.cause);
    dut.set_io$$fastHeadRetire$$bits$$tval(in.fast.tval);
    dut.set_io$$loadOrderRetireLimit$$valid(in.limit_valid);
    dut.set_io$$loadOrderRetireLimit$$bits$$index(in.limit.index);
    dut.set_io$$loadOrderRetireLimit$$bits$$tag(in.limit.tag);
    dut.set_io$$dispatchReady(in.dispatch);
    dut.set_io$$commitEnable(in.commit);
    dut.set_io$$recover$$valid(in.recover);
    dut.set_io$$recover$$bits$$token$$index(in.boundary.index);
    dut.set_io$$recover$$bits$$token$$tag(in.boundary.tag);
    dut.set_io$$recover$$bits$$inclusive(in.inclusive);
    dut.set_io$$headTrap(in.head_trap);
    dut.set_io$$headSystem(in.head_system);
}
static Observation sample(SOlderPrefixRetirementGsim &dut) {
    Observation out;
#define SAMPLE(N) \
    out.allocated[N] = dut.get_io$$renamed##N##$$valid(); \
    out.allocated_token[N] = {dut.get_io$$renamed##N##$$bits$$token$$index(), \
        dut.get_io$$renamed##N##$$bits$$token$$tag()}; \
    out.completed[N] = dut.get_io$$completionAccepted##N(); \
    out.retired[N] = {bool(dut.get_io$$commit##N##$$valid()), \
        {dut.get_io$$commit##N##$$bits$$token$$index(), dut.get_io$$commit##N##$$bits$$token$$tag()}, \
        dut.get_io$$commit##N##$$bits$$pc(), dut.get_io$$commit##N##$$bits$$data(), \
        dut.get_io$$commit##N##$$bits$$nextPc(), dut.get_io$$commit##N##$$bits$$instruction()};
    SAMPLE(0) SAMPLE(1)
#undef SAMPLE
    out.recovery_accepted = dut.get_io$$recoveryAccepted();
    out.trap_accepted = dut.get_io$$headTrapAccepted();
    out.system_accepted = dut.get_io$$headSystemAccepted();
    out.system_token = {dut.get_io$$headSystemToken$$index(), dut.get_io$$headSystemToken$$tag()};
    out.recovering = dut.get_io$$recovering();
    out.occupancy = dut.get_io$$occupancy();
    out.head_exception = dut.get_io$$headException$$valid();
    out.exception_token = {dut.get_io$$headException$$bits$$token$$index(), dut.get_io$$headException$$bits$$token$$tag()};
    out.exception_pc = dut.get_io$$headException$$bits$$pc();
    out.cause = dut.get_io$$headException$$bits$$cause();
    out.tval = dut.get_io$$headException$$bits$$tval();
    return out;
}
class Fixture {
    SOlderPrefixRetirementGsim dut;
    uint64_t cycle = 0;
public:
    Oracle oracle;
    std::map<std::string, uint64_t> witness;
    Fixture() { reset(); }
    void reset() {
        drive(dut, {}); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0); oracle.reset();
    }
    Observation tick(const Input &in = {}) {
        const auto before = oracle.program;
        auto expected = oracle.advance(in);
        drive(dut, in); dut.step(); auto actual = sample(dut);
        mutate(actual, in, before);
        try {
            compare(actual, expected);
            if (in.head_system) require(actual.system_token == expected.system_token,
                "trusted system owner oracle mismatch");
        } catch (const std::runtime_error &e) {
            throw std::runtime_error("cycle=" + std::to_string(cycle) + " " + e.what());
        }
        ++cycle;
        ++witness["cycles"];
        witness["commits"] += expected.retired[0].valid + expected.retired[1].valid;
        return actual;
    }
    void fill(unsigned count) {
        for (unsigned n = 0; n < count; n += 2) {
            Input in; in.allocate[0] = request(100 + n);
            if (n + 1 < count) in.allocate[1] = request(101 + n);
            auto out = tick(in);
            require(out.allocated[0] && (n + 1 == count || out.allocated[1]), "fixture fill did not allocate");
        }
    }
    void finish_all() {
        const auto entries = oracle.program;
        for (unsigned n = 0; n < entries.size(); n += 2) {
            Input in; in.complete[0] = completion(entries[n].token);
            if (n + 1 < entries.size()) in.complete[1] = completion(entries[n + 1].token);
            tick(in);
        }
    }
    void drain() {
        for (unsigned n = 0; n < 4 * capacity && (!oracle.program.empty() || oracle.recovering); ++n) {
            Input in; in.commit = true;
            if (!oracle.program.empty() && oracle.program.front().done && oracle.program.front().result.exception) {
                in.recover = true; in.inclusive = true; in.boundary = oracle.program.front().token;
            } else {
                unsigned lane = 0;
                for (const auto &entry : oracle.program) if (!entry.done && lane < 2)
                    in.complete[lane++] = completion(entry.token);
            }
            tick(in);
        }
        require(oracle.program.empty() && !oracle.recovering, "fixture failed to drain");
        tick();
    }
    void position(unsigned head) {
        reset();
        for (unsigned n = 0; n < head; ++n) {
            Input in; in.allocate[0] = request(n); auto out = tick(in);
            in = {}; in.commit = true; in.complete[0] = completion(out.allocated_token[0]); tick(in);
        }
    }
    void report() const {
        std::cout << "GSIM_OLDER_PREFIX_COMPONENT: PASS";
        for (const auto &[name, value] : witness) std::cout << ' ' << name << '=' << value;
        std::cout << "; component scope only, no executing-CPU replay proof\n";
    }
};

static void exhaustive_boundaries(Fixture &f) {
    for (unsigned head = 0; head < capacity; ++head) {
        for (unsigned count = 1; count <= capacity; ++count) {
            for (unsigned rank = 0; rank < count; ++rank) {
                f.position(head); f.fill(count); f.finish_all();
                const auto stop = f.oracle.program[rank].token;
                Input in; in.commit = true; in.limit_valid = true; in.limit = stop;
                unsigned retired = 0;
                for (unsigned n = 0; n <= (rank + 1) / 2; ++n) {
                    auto out = f.tick(in); retired += out.retired[0].valid + out.retired[1].valid;
                }
                require(retired == rank && f.oracle.program.front().token == stop,
                    "directed limit did not preserve exact checked-load suffix");
                ++f.witness["headCountRankCases"];
                if (count == capacity) ++f.witness["fullRobCases"];
                if (head + count > capacity) ++f.witness["wrappedCases"];
                if (rank == 1) ++f.witness["laneOneBoundaries"];
                // An invalid payload cannot restrict the ordinary no-limit behavior.
                in.limit_valid = false; in.limit.tag ^= UINT64_C(1) << 63;
                f.tick(in); f.drain();
            }
        }
    }
}
static void token_authority(Fixture &f) {
    for (unsigned head = 0; head < capacity; ++head) {
        f.position(head); f.fill(capacity); f.finish_all();
        const auto old = f.oracle.program;
        for (unsigned bit = 0; bit < 64; ++bit) {
            Input in; in.commit = true; in.limit_valid = true; in.limit = old.back().token;
            in.limit.tag ^= UINT64_C(1) << bit;
            in.recover = true; in.boundary = in.limit; in.inclusive = true;
            in.complete[0] = completion(in.limit);
            f.tick(in); ++f.witness["wrongGenerationBits"];
        }
        f.drain(); f.fill(capacity); f.finish_all();
        for (const auto &entry : old) {
            Input in; in.commit = true; in.limit_valid = true; in.limit = entry.token;
            f.tick(in); ++f.witness["reusedIndexStaleLimits"];
        }
        f.drain();
        f.fill(3); const auto outside = f.oracle.program.back().token;
        f.finish_all(); f.drain(); f.fill(1); f.finish_all();
        Input in; in.commit = true; in.limit_valid = true; in.limit = outside;
        f.tick(in); ++f.witness["outOfWindowLimits"];
        f.drain();
        in = {}; in.commit = true; in.limit_valid = true; in.limit = outside;
        f.tick(in); ++f.witness["emptyLimits"];
    }
}
static void retirement_interactions(Fixture &f) {
    for (unsigned head = 0; head < capacity; ++head) {
        f.position(head); f.fill(4);
        auto entries = f.oracle.program;
        Input in; in.commit = true; in.limit_valid = true; in.limit = entries[1].token;
        in.complete = {completion(entries[0].token), completion(entries[1].token)};
        in.allocate = {request(301), request(302)};
        auto out = f.tick(in);
        require(out.retired[0].valid && !out.retired[1].valid && out.allocated[0] && out.allocated[1],
            "simultaneous completion/allocate/one-lane retire fixture missing");
        ++f.witness["simultaneousTurnover"];
        f.drain();

        f.position(head); f.fill(capacity); entries = f.oracle.program;
        in = {}; in.commit = true; in.limit_valid = true; in.limit = entries[1].token;
        in.complete = {completion(entries[0].token), completion(entries[1].token)};
        in.allocate = {request(303), request(304)};
        out = f.tick(in); require(out.retired[0].valid && !out.allocated[0], "full ROB borrowed same-cycle credit");
        ++f.witness["fullTurnoverBackpressure"];
        in = {}; in.allocate = {request(305), request(306)};
        out = f.tick(in); require(out.allocated[0] && !out.allocated[1], "partial allocation was not a prefix");
        f.drain();

        f.position(head); f.fill(3); entries = f.oracle.program;
        in = {}; in.commit = true; in.limit_valid = true; in.limit = entries[2].token;
        in.complete = {completion(entries[0].token), completion(entries[1].token)}; in.same_cycle = 0;
        out = f.tick(in); require(!out.retired[0].valid, "registered branch hold escaped");
        ++f.witness["branchCompletionHolds"];
        in.complete = {}; in.commit = false; f.tick(in); ++f.witness["globalHolds"];
        in.commit = true; out = f.tick(in); require(out.retired[0].valid && out.retired[1].valid,
            "registered completion failed next-cycle retirement"); f.drain();

        f.position(head); f.fill(3); entries = f.oracle.program;
        in = {}; in.commit = true; in.limit_valid = true; in.limit = entries[1].token;
        in.fast = completion(entries[0].token);
        out = f.tick(in); require(out.retired[0].valid && !out.retired[1].valid, "legal older fast-head missing");
        ++f.witness["legalFastHeadOlder"];
        // The checked owner is now at head. Caller withholds its pending fast completion,
        // as required by RenameRob's trusted fastHeadRetire contract.
        in.fast = {}; f.tick(in); ++f.witness["callerGatedFastHead"];
        in.limit.tag ^= UINT64_C(1) << 63; f.tick(in); ++f.witness["callerGatedStaleFastHead"];
        in.limit_valid = false; in.fast = completion(entries[1].token); f.tick(in); f.drain();

        f.position(head);
        in = {}; in.allocate = {request(401, 0x73), request(402)}; out = f.tick(in);
        auto first = out.allocated_token;
        in = {}; in.allocate[0] = request(403); auto stop = f.tick(in).allocated_token[0];
        in = {}; in.commit = true; in.limit_valid = true; in.limit = stop;
        in.complete = {completion(first[0]), completion(first[1])};
        out = f.tick(in); require(out.retired[0].valid && !out.retired[1].valid, "system single-step lost");
        ++f.witness["systemSingleStep"];
        f.drain();
    }
}
static void exception_recovery(Fixture &f) {
    for (unsigned head = 0; head < capacity; ++head) {
        f.position(head); f.fill(4); auto entries = f.oracle.program;
        Input in; in.commit = true; in.limit_valid = true; in.limit = entries[2].token;
        in.complete = {completion(entries[0].token), completion(entries[1].token, true)};
        auto out = f.tick(in); require(out.retired[0].valid && !out.retired[1].valid, "younger fault prefix escaped");
        in.complete = {}; out = f.tick(in); require(out.head_exception && !out.retired[0].valid,
            "head exception failed to remain precise"); ++f.witness["preciseExceptions"];
        in.head_trap = true; in.allocate = {request(500), request(501)};
        f.tick(in); ++f.witness["headTrapPriority"];
        f.drain();
        for (unsigned fault_rank : {1u, 2u}) {
            f.position(head); f.fill(4); entries = f.oracle.program;
            in = {}; in.commit = true; in.limit_valid = true; in.limit = entries[1].token;
            in.complete = {completion(entries[0].token), completion(entries[fault_rank].token, true)};
            out = f.tick(in); require(out.retired[0].valid && !out.retired[1].valid,
                "fault at/after limit admitted forbidden retirement");
            in.complete = {}; out = f.tick(in);
            require(out.head_exception == (fault_rank == 1) && !out.retired[0].valid,
                "fault became visible before precise head ownership");
            if (fault_rank == 2) {
                in.complete[0] = completion(entries[1].token); f.tick(in);
                in.complete = {}; in.limit_valid = false; out = f.tick(in);
                require(out.retired[0].valid && !out.retired[1].valid, "younger fault did not stop released prefix");
                out = f.tick(in); require(out.head_exception, "released younger fault never reached precise head");
            }
            ++f.witness[fault_rank == 1 ? "checkedLoadExceptions" : "youngerThanLimitExceptions"];
            f.drain();
        }
        for (unsigned inclusive = 0; inclusive < 2; ++inclusive) {
            for (unsigned kept = 0; kept < 2; ++kept) {
                f.position(head); f.fill(capacity); entries = f.oracle.program; f.finish_all();
                const auto limit = entries[kept ? 2 : 11].token;
                in = {}; in.commit = true; in.limit_valid = true; in.limit = limit;
                in.recover = true; in.inclusive = inclusive; in.boundary = entries[6].token;
                in.allocate = {request(510), request(511)};
                f.tick(in);
                in.recover = false; in.allocate = {};
                while (f.oracle.recovering) f.tick(in);
                out = f.tick(in);
                require(out.retired[0].valid == bool(kept), "kept/discarded limit recovery behavior");
                ++f.witness[kept ? "keptLimits" : "discardedLimitsFailClosed"];
                f.drain();
                if (!kept) {
                    f.fill(capacity); f.finish_all();
                    in = {}; in.commit = true; in.limit_valid = true; in.limit = limit;
                    f.tick(in); ++f.witness["rollbackReusedStaleLimits"];
                    f.drain();
                }
            }
        }
        f.position(head); f.fill(capacity); entries = f.oracle.program;
        in = {}; in.commit = true; in.limit_valid = true; in.limit = entries[12].token;
        in.recover = true; in.boundary = entries[8].token; f.tick(in);
        in.boundary = entries[3].token; in.inclusive = true; f.tick(in);
        ++f.witness["recoveryShrinks"];
        in.recover = false; while (f.oracle.recovering) f.tick(in);
        f.drain();
        f.position(head); f.fill(capacity); entries = f.oracle.program;
        in = {}; in.commit = true; in.limit_valid = true; in.limit = entries[8].token;
        in.head_system = true; in.complete[0] = completion(entries[0].token);
        out = f.tick(in); require(out.system_accepted && !out.retired[0].valid, "head system recovery priority");
        ++f.witness["headSystemPriority"];
        in.head_system = false; in.complete = {};
        while (f.oracle.recovering) f.tick(in);
        out = f.tick(in); require(!out.retired[0].valid, "discarded system limit must fail closed");
        f.drain();
    }
}
static void seeded_stress(Fixture &f) {
    for (uint64_t seed : {UINT64_C(0x1735), UINT64_C(0x912fed), UINT64_C(0xabcdef123)}) {
        f.reset(); std::mt19937_64 rng(seed); std::vector<Token> history;
        for (unsigned n = 0; n < 3000; ++n) {
            Input in; in.commit = (rng() % 5) != 0; in.dispatch = (rng() % 6) != 0;
            for (unsigned lane = 0; lane < 2; ++lane) if (rng() % 3 != 0)
                in.allocate[lane] = request(seed + 2 * n + lane, rng() % 31 == 0 ? 0x73 : 0x13);
            const auto entries = f.oracle.program;
            for (unsigned lane = 0; lane < 2; ++lane) if (!entries.empty() && rng() % 4 != 0) {
                Token token = entries[rng() % entries.size()].token;
                if (rng() % 7 == 0) token.tag ^= UINT64_C(1) << (rng() % 64);
                in.complete[lane] = completion(token, rng() % 53 == 0);
            }
            in.same_cycle = rng() & 3;
            in.limit_valid = rng() % 3 != 0;
            if (!entries.empty()) in.limit = entries[rng() % entries.size()].token;
            if (rng() % 5 == 0) in.limit.tag ^= UINT64_C(1) << (rng() % 64);
            if (!history.empty() && rng() % 9 == 0) in.limit = history[rng() % history.size()];
            if (!entries.empty() && rng() % 17 == 0) {
                in.recover = true; in.inclusive = rng() & 1; in.boundary = entries[rng() % entries.size()].token;
                if (rng() % 4 == 0) in.boundary.tag ^= UINT64_C(1) << (rng() % 64);
            }
            auto out = f.tick(in);
            for (unsigned lane = 0; lane < 2; ++lane) if (out.allocated[lane]) history.push_back(out.allocated_token[lane]);
            ++f.witness["seededCycles"];
        }
        f.drain();
    }
}
#endif

int main(int argc, char **argv) {
    try {
#ifdef OLDER_PREFIX_ORACLE_ONLY
        require(argc == 1, "host-oracle-only mode does not execute hardware mutations");
        (void)argv; host_contract();
#else
        if (argc == 2 && std::string_view(argv[1]).starts_with("--mutate=")) mutation = argv[1] + 9;
        else require(argc == 1, "usage: run [--mutate=NAME]");
        Fixture f;
        exhaustive_boundaries(f);
        token_authority(f);
        retirement_interactions(f);
        exception_recovery(f);
        seeded_stress(f);
        require(mutation.empty(), "negative control did not fire: " + mutation);
        require(f.witness["headCountRankCases"] == 2176 && f.witness["wrongGenerationBits"] == 1024 &&
            f.witness["seededCycles"] == 9000 && f.witness["legalFastHeadOlder"] == 16 &&
            f.witness["keptLimits"] == 32 && f.witness["discardedLimitsFailClosed"] == 32 &&
            f.witness["checkedLoadExceptions"] == 16 && f.witness["youngerThanLimitExceptions"] == 16 &&
            f.witness["rollbackReusedStaleLimits"] == 32 && f.witness["callerGatedStaleFastHead"] == 16,
            "coverage witness incomplete");
        f.report();
#endif
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "OLDER_PREFIX: FAIL " << e.what() << " mutation=" << mutation
            << " fired=" << mutation_fired << '\n';
        return 1;
    }
}
