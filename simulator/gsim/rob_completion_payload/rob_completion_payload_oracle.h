#pragma once

#include "retirement_slot_rob_oracle.h"

namespace rob_completion_payload {
using namespace retirement_intent_rob;

// The inherited deque oracle assigns every token and all program-order state.
// These checks add defined raw-payload observations; they never substitute the
// paired reference for an architectural expectation or alter oracle output.
template<class Model> class Fixture {
    Model &m;
    retirement_intent_rob::Fixture<Model> common;
    uint64_t serial = 0;
public:
    std::string phase = "initialization";
    std::map<std::string, uint64_t> cover;
    explicit Fixture(Model &model) : m(model), common(model, "") {}
    const std::deque<Entry> &program() const { return common.oracle.program; }
    Token token(unsigned rank) const { return common.token(rank); }
    bool recovering() const { return common.oracle.recovering; }
    void reset() { common.reset(); }
    Observation tick(const Input &in = {}) {
        const auto before = common.oracle.program;
        try {
            const auto out = common.tick(in);
            const auto paired = sample(m);
            for (unsigned side = 0; side < 2; ++side) {
                const auto &actual = paired[side];
                if (!before.empty()) {
                    const auto &head = before.front();
                    // Allocation clears all RobEntry fields. Even an invalid
                    // headException must expose zero tval for an allocated but
                    // unfinished owner; a recycled RAM value cannot leak here.
                    const uint64_t cause = head.done ? head.result.cause : 0;
                    const uint64_t tval = head.done ? head.result.tval : 0;
                    require(actual.cause == cause && actual.tval == tval,
                        std::string(side ? "candidate" : "reference") +
                        " raw head cause/tval mismatch (done=" + std::to_string(head.done) +
                        ", expected tval=" + std::to_string(tval) +
                        ", actual tval=" + std::to_string(actual.tval) + ")");
                    require(actual.exception_token == head.token && actual.exception_pc == head.request.pc,
                        "allocated head raw exception owner/PC mismatch");
                    if (!head.done) ++cover["allocation-zero-observations"];
                }
                for (unsigned lane = 0; lane < 2 && lane < before.size(); ++lane) {
                    const auto &entry = before[lane];
                    if (entry.done) {
                        require(actual.retired[lane].next_pc == entry.result.next_pc,
                            std::string(side ? "candidate" : "reference") +
                            " saved nextPc mismatch slot=" + std::to_string(entry.token.index));
                        require(actual.retired[lane].data == entry.result.data,
                            "unchanged saved data mismatch");
                        ++cover["stored-nextpc-observations"];
                    } else if (in.intent_mask() == 0) {
                        require(actual.retired[lane].next_pc == 0,
                            "unfinished owner without retirement offers exposed nonzero nextPc");
                    }
                    require(actual.retired[lane].next_pc == paired[1 - side].retired[lane].next_pc,
                        "paired live-slot raw nextPc mismatch");
                    require(actual.retired[lane].data == paired[1 - side].retired[lane].data,
                        "paired live-slot raw data mismatch");
                }
            }
            ++cover["cycles"];
            cover["stored-dual-retirement"] += before.size() >= 2 && before[0].done && before[1].done &&
                out.retired[0].valid && out.retired[1].valid;
            return out;
        } catch (const std::runtime_error &error) {
            throw std::runtime_error("ROB_COMPLETION_PAYLOAD phase=" + phase + " cycle=" +
                std::to_string(cover["cycles"]) + " " + error.what());
        }
    }
    void fill(unsigned count, uint32_t opcode = 0x13) {
        for (unsigned n = 0; n < count; n += 2) {
            Input in; in.allocate[0] = request(UINT64_C(0x400000) + serial++, opcode);
            if (n + 1 < count) in.allocate[1] = request(UINT64_C(0x400000) + serial++);
            const auto out = tick(in);
            require(out.allocated[0] && (n + 1 == count || out.allocated[1]), "payload fixture allocation failed");
            tick(); // Observe allocation clearing before any completion offer.
        }
    }
    void settle() {
        unsigned budget = capacity;
        while (recovering()) { require(budget-- != 0, "rollback failed bounded progress"); tick(); }
        tick();
    }
    void flush() {
        if (!program().empty()) { Input in; in.head_trap = true; tick(in); }
        settle();
        require(program().empty(), "payload fixture flush failed");
    }
    void drain() {
        unsigned budget = 8 * capacity;
        while (!program().empty() || recovering()) {
            require(budget-- != 0, "payload fixture drain failed bounded progress");
            if (recovering()) { tick(); continue; }
            if (program().front().done && program().front().result.fault) { flush(); continue; }
            Input in; in.commit = true;
            unsigned port = 0;
            for (const auto &entry : program()) if (!entry.done && port < 2)
                in.complete[port++] = completion(entry.token, false, UINT64_C(0x3876aabbccdd0011));
            tick(in);
        }
        tick();
    }
};

template<class Model> void run(Model &m) {
    Fixture<Model> f(m);
    Input in;
    Observation out;

    // Deterministic witnesses for BOTH real-source negative controls. Writer 1
    // first owns a nonzero saved payload; trap then recycles precisely that row.
    // No uninitialized memory value is needed to observe the allocation-zero bug.
    f.phase = "writer-map-and-allocation-zero";
    f.fill(1); const Token old = f.token(0);
    in = {}; in.complete[1] = completion(old, true, UINT64_C(0x6a35d1e02bf947c8));
    out = f.tick(in); require(out.completed[1], "writer-1 priming completion rejected");
    out = f.tick(); require(out.head_exception, "writer-1 precise exception missing");
    f.flush(); f.fill(1); const Token replacement = f.token(0);
    require(old.index == replacement.index && old.tag != replacement.tag, "zero witness did not reuse owner row");
    in = {}; in.complete[0] = completion(old, true, UINT64_C(0xffff0000ffff0000));
    out = f.tick(in); require(!out.completed[0] && !out.head_done, "late retired generation altered new owner");
    ++f.cover["allocation-zero-reused-row"];
    f.drain();

    // Two distinct writes to equal-parity rows must never share a write port.
    // Both writer assignments and every physical head index are visited. All
    // results retire from saved storage, including the 15 -> 0 two-wide case.
    for (unsigned start = 0; start < capacity; ++start) for (unsigned reversed = 0; reversed < 2; ++reversed) {
        f.phase = "same-parity-start-" + std::to_string(start) + "-reversed-" + std::to_string(reversed);
        f.reset();
        for (unsigned n = 0; n < start; ++n) {
            f.fill(1); in = {}; in.commit = true; in.complete[n & 1] = completion(f.token(0)); f.tick(in);
        }
        f.fill(4);
        require(f.token(0).index == start && ((f.token(0).index ^ f.token(2).index) & 1) == 0,
            "same-parity test addressed wrong rows");
        for (unsigned offset = 0; offset < 2; ++offset) {
            in = {};
            for (unsigned rank = 0; rank < 2; ++rank) {
                const unsigned port = rank ^ reversed;
                const auto owner = f.token(offset + 2 * rank);
                in.complete[port] = completion(owner, false,
                    UINT64_C(0x8b731d2f6590a4c6) ^ (uint64_t(start) << 40) ^ (uint64_t(port) << 28) ^ offset);
                f.cover["writer-parity-mask"] |= 1u << (2 * port + (owner.index & 1));
            }
            out = f.tick(in); require(out.completed[0] && out.completed[1], "same-parity dual completion lost a port");
            f.tick();
        }
        in = {}; in.commit = true;
        out = f.tick(in); require(out.retired[0].valid && out.retired[1].valid, "saved first dual retirement failed");
        out = f.tick(in); require(out.retired[0].valid && out.retired[1].valid, "saved second dual retirement failed");
        f.cover["same-parity-head-mask"] |= 1u << start;
        ++f.cover["same-parity-pairs"];
        f.tick();
    }

    // Full-width payload walks on both writers. Cause remains the original
    // architectural register payload, while nextPc/tval are candidate RAMs.
    // A precise saved fault, exclusive retention, inclusive kill and row reuse
    // are checked for every bit without obtaining state from the paired DUT.
    for (unsigned port = 0; port < 2; ++port) for (unsigned bit = 0; bit < 64; ++bit) {
        f.phase = "all-bits-writer-" + std::to_string(port) + "-bit-" + std::to_string(bit);
        f.flush(); f.fill(1); const Token owner = f.token(0);
        auto c = completion(owner, true, bit + 0x100 * port);
        c.cause = UINT64_C(1) << bit;
        c.tval = ~(UINT64_C(1) << bit);
        c.next_pc = UINT64_C(1) << ((bit + 29) % 64);
        in = {}; in.commit = true; in.complete[port] = c; f.tick(in);
        out = f.tick(); require(out.head_exception && out.cause == c.cause && out.tval == c.tval,
            "full-width precise exception was truncated");
        in = {}; in.complete[1 - port] = completion(owner, false, UINT64_MAX);
        out = f.tick(in); require(!out.completed[1 - port], "already-done payload overwritten by other writer");
        in = {}; in.external = {true, owner, false}; f.tick(in); f.settle();
        out = f.tick(); require(out.head_exception && out.tval == c.tval, "exclusive recovery lost saved tval");
        in = {}; in.external = {true, owner, true}; f.tick(in); f.settle();
        f.fill(1); const Token fresh = f.token(0);
        require(fresh.index == owner.index && fresh.tag != owner.tag, "bit sweep failed physical-row reuse");
        in = {}; in.complete[port] = c; out = f.tick(in);
        require(!out.completed[port] && !out.head_done, "killed old tag wrote replacement payload");
        f.cover["payload-bits-writer-" + std::to_string(port)] |= UINT64_C(1) << bit;
        f.drain();
    }

    // Invalid payloads deliberately alias live rows and carry nonzero high-bit
    // data on BOTH writer inputs; no state update or same-cycle bypass is legal.
    f.phase = "invalid-poison";
    f.fill(4);
    for (unsigned bit = 0; bit < 64; ++bit) {
        in = {};
        for (unsigned port = 0; port < 2; ++port) {
            in.complete[port] = completion(f.token(port + (bit & 2)), true, ~(UINT64_C(1) << bit));
            in.complete[port].valid = false;
            in.allocate[port] = request(UINT64_MAX - bit - port); in.allocate[port].valid = false;
        }
        in.external = {false, f.token(0), true}; in.local = {false, f.token(3), false};
        out = f.tick(in); require(!out.completed[0] && !out.completed[1] && !out.head_done,
            "invalid poison changed payload state");
        ++f.cover["invalid-poison-cycles"];
    }
    f.drain();

    // An actual duplicate must store only writer zero's payload even when the
    // other payload disagrees in every field and the first is a precise fault.
    for (bool fault : {false, true}) {
        f.phase = fault ? "duplicate-fault-stored" : "duplicate-normal-stored";
        f.fill(2); in = {}; in.same_cycle = 0; in.commit = true;
        in.complete[0] = completion(f.token(0), fault, UINT64_C(0x8000000000007001));
        in.complete[1] = completion(f.token(0), !fault, UINT64_C(0x7fffffffffff8ffe));
        out = f.tick(in); require(out.completed[0] && !out.completed[1] && !out.retired[0].valid,
            "duplicate selected wrong authoritative writer");
        f.tick(); f.drain(); ++f.cover["stored-duplicate-cases"];
    }

    // Recovery only writes surviving owners. An accepted surviving head result
    // remains visible during and after the multi-beat rollback walk.
    for (bool inclusive : {false, true}) for (bool external : {false, true}) {
        f.phase = std::string("recovery-") + (inclusive ? "inclusive" : "exclusive") +
            (external ? "-external" : "-local");
        f.fill(12); const auto head = f.token(0), doomed = f.token(9);
        in = {}; in.commit = true;
        (external ? in.external : in.local) = {true, f.token(4), inclusive};
        in.complete[0] = completion(doomed, true, UINT64_C(0x5555aaaa3333cccc));
        in.complete[1] = completion(head, false, UINT64_C(0xaaaa5555cccc3333));
        out = f.tick(in); require(out.recovery_accepted && !out.completed[0] && out.completed[1] &&
            !out.retired[0].valid, "recovery write-survival/retirement veto changed");
        f.settle(); require(f.program().size() == (inclusive ? 4u : 5u), "wrong retained recovery prefix");
        f.drain(); ++f.cover["saved-recovery-cases"];
    }

    // Trusted system retains only the head. A precise trap overrides both the
    // system and arbitrary flush; external-at-head otherwise has tie priority.
    for (unsigned mode = 0; mode < 4; ++mode) {
        f.phase = "flush-system-trap-priority-" + std::to_string(mode);
        f.fill(12); in = {}; in.commit = true; in.head_system = true;
        in.head_trap = mode == 0;
        in.external = {true, f.token(mode < 3 ? 0 : 5), mode == 1};
        in.complete[0] = completion(f.token(0), false, UINT64_C(0x123456789abcdef0));
        in.complete[1] = completion(f.token(1), true, UINT64_C(0xfedcba9876543210));
        out = f.tick(in);
        if (mode == 0) require(out.trap_accepted && !out.system_accepted && !out.completed[0],
            "trap failed to override system/external and cancel writes");
        else if (mode < 3) require(out.external_wins && !out.system_accepted &&
            out.completed[0] == (mode == 2), "external head flush lost inclusive/exclusive tie");
        else require(out.system_accepted && out.completed[0] && !out.completed[1],
            "system failed to retain exactly its head payload");
        f.settle(); f.drain(); ++f.cover["priority-cases"];
    }

    require(f.cover["allocation-zero-reused-row"] == 1 && f.cover["allocation-zero-observations"] > 0,
        "allocation-zero witness missing");
    require(f.cover["writer-parity-mask"] == 15 && f.cover["same-parity-head-mask"] == 0xffff &&
        f.cover["same-parity-pairs"] == 32 && f.cover["stored-dual-retirement"] >= 64,
        "writer/parity/wrap/stored-dual coverage incomplete");
    require(f.cover["payload-bits-writer-0"] == UINT64_MAX && f.cover["payload-bits-writer-1"] == UINT64_MAX,
        "64-bit payload walk incomplete");
    require(f.cover["invalid-poison-cycles"] == 64 && f.cover["stored-duplicate-cases"] == 2 &&
        f.cover["saved-recovery-cases"] == 4 && f.cover["priority-cases"] == 4,
        "poison/duplicate/recovery/priority coverage incomplete");
    std::cout << "ROB_COMPLETION_PAYLOAD_ORACLE_PASS cycles=" << f.cover["cycles"]
        << " allocationZero=" << f.cover["allocation-zero-observations"]
        << " storedNextPc=" << f.cover["stored-nextpc-observations"]
        << " sameParityPairs=" << f.cover["same-parity-pairs"]
        << " storedDualRetirement=" << f.cover["stored-dual-retirement"]
        << " payloadBitsPerWriter=64 invalidPoison=64 recoveryCases=4 priorityCases=4\n";
}
} // namespace rob_completion_payload
