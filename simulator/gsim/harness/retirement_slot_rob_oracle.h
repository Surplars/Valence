#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

namespace retirement_intent_rob {
constexpr unsigned capacity = 16, recovery_width = 4, initial_free = 16;
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &other) const { return index == other.index && tag == other.tag; }
};
struct Request { bool valid = false; uint64_t pc = 0; uint32_t instruction = 0; };
struct Completion {
    bool valid = false;
    Token token;
    uint64_t data = 0, next_pc = 0;
    bool fault = false;
    uint64_t cause = 0, tval = 0;
};
struct Recovery { bool valid = false; Token token; bool inclusive = false; };
struct OwnerLimit { bool valid = false; Token token; };
struct Input {
    std::array<Request, 2> allocate{};
    std::array<Completion, 2> complete{};
    // Negative means use the actual completion-valid mask. A raw offer can
    // outlive actual completion valid only in an accepted/ongoing recovery.
    int intent = -1;
    unsigned same_cycle = 3;
    bool dispatch = true, commit = false, head_trap = false, head_system = false;
    Recovery external, local;
    OwnerLimit load_limit;
    unsigned intent_mask() const {
        return intent < 0 ? unsigned(complete[0].valid) | (unsigned(complete[1].valid) << 1) : unsigned(intent);
    }
};
struct Entry { Token token; Request request; bool done = false; Completion result; };
struct Commit {
    bool valid = false;
    Token token;
    uint64_t pc = 0, data = 0, next_pc = 0;
    uint32_t instruction = 0;
    unsigned rd = 0, destination = 0;
    bool writes = false;
};
struct Observation {
    std::array<bool, 2> allocated{}, completed{};
    std::array<Token, 2> allocated_token{};
    std::array<unsigned, 2> source1{}, source2{}, destination{}, old_destination{};
    std::array<bool, 2> writes{}, alias{};
    std::array<Commit, 2> retired{};
    bool external_accepted = false, external_wins = false, recovery_accepted = false;
    bool trap_accepted = false, system_accepted = false, recovering = false;
    Recovery selected;
    unsigned killed = 0, occupancy = 0, free_count = initial_free;
    bool head_valid = false, head_done = false, head_exception = false, exhausted = false;
    Token system_token, exception_token;
    uint64_t head_pc = 0, exception_pc = 0, cause = 0, tval = 0;
};
inline void require(bool value, const std::string &why) {
    if (!value) throw std::runtime_error("RETIREMENT_ROB_ORACLE: " + why);
}
inline int locate(const std::deque<Entry> &program, Token owner) {
    for (unsigned n = 0; n < program.size(); ++n) if (program[n].token == owner) return int(n);
    return -1;
}
inline void compare(const Observation &a, const Observation &e) {
    require(a.occupancy == e.occupancy && a.recovering == e.recovering, "occupancy/recovery state mismatch");
    require(a.external_accepted == e.external_accepted && a.external_wins == e.external_wins &&
        a.recovery_accepted == e.recovery_accepted && a.trap_accepted == e.trap_accepted &&
        a.system_accepted == e.system_accepted, "recovery candidate admission/priority mismatch");
    require(a.selected.valid == e.selected.valid && a.killed == e.killed, "recovery selection/mask mismatch");
    if (e.selected.valid) require(a.selected.token == e.selected.token &&
        a.selected.inclusive == e.selected.inclusive, "selected recovery identity mismatch");
    require(a.free_count == initial_free && !a.exhausted, "nonwriter allocation consumed registers or tags exhausted");
    require(a.head_valid == e.head_valid && a.head_done == e.head_done && a.head_pc == e.head_pc,
        "head registered state mismatch");
    if (e.head_valid) require(a.system_token == e.system_token, "trusted head owner mismatch");
    require(a.head_exception == e.head_exception, "precise head exception mismatch");
    if (e.head_exception) require(a.exception_token == e.exception_token && a.exception_pc == e.exception_pc &&
        a.cause == e.cause && a.tval == e.tval, "head exception identity/payload mismatch");
    for (unsigned lane = 0; lane < 2; ++lane) {
        require(a.completed[lane] == e.completed[lane], "completion owner/duplicate/done mismatch lane=" + std::to_string(lane));
        require(a.allocated[lane] == e.allocated[lane], "allocation prefix mismatch lane=" + std::to_string(lane));
        if (e.allocated[lane]) require(a.allocated_token[lane] == e.allocated_token[lane] &&
            a.source1[lane] == 0 && a.source2[lane] == 0 && a.destination[lane] == 0 &&
            a.old_destination[lane] == 0 && !a.writes[lane] && !a.alias[lane], "allocation owner/nonwriter mismatch");
        const auto &ac = a.retired[lane]; const auto &ec = e.retired[lane];
        require(ac.valid == ec.valid, "ordered retirement valid mismatch lane=" + std::to_string(lane));
        if (ec.valid) require(ac.token == ec.token && ac.pc == ec.pc && ac.instruction == ec.instruction &&
            ac.data == ec.data && ac.next_pc == ec.next_pc && !ac.writes && ac.rd == 0 && ac.destination == 0,
            "retirement owner/priority/payload mismatch lane=" + std::to_string(lane));
    }
}

// Independent program-order ledger. A deque determines owner liveness, ordering,
// readiness and rollback. Slot numbers are generated at allocation, never copied
// from the DUT. The small circular walk below is only for the documented raw
// recovery-candidate age priority, which applies even to a stale local offer.
class Oracle {
    unsigned head = 0, tail = 0, keep = 0;
    uint64_t serial = 0;
    unsigned slot_rank(unsigned index) const {
        unsigned cursor = head;
        for (unsigned rank = 0; rank < capacity; ++rank) {
            if (cursor == index) return rank;
            cursor = cursor + 1 == capacity ? 0 : cursor + 1;
        }
        throw std::runtime_error("fixture supplied out-of-range slot");
    }
public:
    std::deque<Entry> program;
    bool recovering = false;
    void reset() { *this = Oracle{}; }
    Observation advance(const Input &in) {
        Observation e;
        const auto before = program;
        e.occupancy = unsigned(before.size()); e.recovering = recovering;
        e.head_valid = !before.empty();
        if (e.head_valid) {
            e.head_done = before.front().done;
            e.head_pc = before.front().request.pc;
            e.system_token = before.front().token;
        }
        const int ext = locate(before, in.external.token), loc = locate(before, in.local.token);
        const unsigned ext_keep = ext < 0 ? 0 : unsigned(ext) + !in.external.inclusive;
        const unsigned loc_keep = loc < 0 ? 0 : unsigned(loc) + !in.local.inclusive;
        e.external_accepted = in.external.valid && ext >= 0 && (!recovering || ext_keep < keep);
        const bool local_accepted = in.local.valid && loc >= 0 && (!recovering || loc_keep < keep);
        const bool ordinary_external = e.external_accepted && (!in.local.valid ||
            slot_rank(in.external.token.index) <= slot_rank(in.local.token.index));
        const bool ordinary = ordinary_external || local_accepted;
        e.trap_accepted = in.head_trap && !before.empty() && (!recovering || keep != 0);
        const bool external_head = e.external_accepted && ext == 0;
        e.system_accepted = in.head_system && !before.empty() && !e.trap_accepted && !external_head &&
            (!recovering || keep > 1);
        require(!in.head_system || (!before.empty() && (!recovering || keep != 0) && !in.local.valid),
            "fixture violated trusted head-system producer contract");
        e.recovery_accepted = e.trap_accepted || e.system_accepted || ordinary;
        e.external_wins = e.trap_accepted || (!e.system_accepted && ordinary_external);
        e.selected = ordinary_external ? in.external : in.local;
        e.selected.valid = ordinary_external || in.local.valid;
        if (e.trap_accepted || e.system_accepted)
            e.selected = {true, before.front().token, e.trap_accepted};
        if (e.recovery_accepted) {
            keep = e.trap_accepted ? 0 : e.system_accepted ? 1 : ordinary_external ? ext_keep : loc_keep;
            for (unsigned slot = 0; slot < capacity; ++slot)
                if (slot_rank(slot) >= keep) e.killed |= 1u << slot;
        }
        const bool rollback = recovering || e.recovery_accepted;
        const unsigned actual_mask = unsigned(in.complete[0].valid) | (unsigned(in.complete[1].valid) << 1);
        require((in.intent_mask() & actual_mask) == actual_mask, "raw intent cannot omit an actual completion");
        require(rollback || in.intent_mask() == actual_mask,
            "raw-only retirement intent requires accepted or ongoing recovery");
        e.head_exception = !before.empty() && before.front().done && before.front().result.fault && !rollback;
        if (e.head_exception) {
            const auto &first = before.front();
            e.exception_token = first.token; e.exception_pc = first.request.pc;
            e.cause = first.result.cause; e.tval = first.result.tval;
        }
        std::array<int, 2> completed_rank{-1, -1};
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto &c = in.complete[lane];
            const int rank = locate(before, c.token);
            const bool duplicate = lane && in.complete[0].valid && in.complete[0].token == c.token;
            e.completed[lane] = c.valid && rank >= 0 && !before[rank].done && !duplicate &&
                (!rollback || unsigned(rank) < keep);
            if (e.completed[lane]) {
                completed_rank[lane] = rank;
                program[rank].done = true; program[rank].result = c;
            }
        }
        unsigned retired = 0;
        // A live outstanding-load owner limits retirement to its strictly older program prefix.
        // A stale generation fails closed without affecting completion acceptance.
        const int limit_rank = locate(before, in.load_limit.token);
        bool commit_prefix = in.commit && !rollback && (!in.load_limit.valid || limit_rank >= 0);
        for (unsigned lane = 0; lane < 2 && lane < before.size(); ++lane) {
            const auto &entry = before[lane];
            bool ready = entry.done && !entry.result.fault;
            Completion result = entry.result;
            if (!entry.done) for (unsigned port = 0; port < 2; ++port)
                if (completed_rank[port] == int(lane) && ((in.same_cycle >> port) & 1) && !in.complete[port].fault) {
                    ready = true; result = in.complete[port];
                }
            const bool valid = commit_prefix && ready && (!in.load_limit.valid || int(lane) < limit_rank);
            if (valid) {
                e.retired[lane] = {true, entry.token, entry.request.pc, result.data, result.next_pc,
                    entry.request.instruction, 0, 0, false};
                ++retired;
            }
            commit_prefix = valid && (entry.request.instruction & 0x7f) != 0x73;
        }
        std::vector<Entry> allocated;
        bool allocation_prefix = in.dispatch && !rollback;
        for (unsigned lane = 0; lane < 2; ++lane) {
            e.allocated[lane] = allocation_prefix && in.allocate[lane].valid && before.size() + lane < capacity;
            allocation_prefix = e.allocated[lane];
            if (e.allocated[lane]) {
                const Token token{tail, serial++};
                tail = (tail + 1) % capacity;
                e.allocated_token[lane] = token;
                allocated.push_back({token, in.allocate[lane], false, {}});
            }
        }
        if (rollback) {
            for (unsigned n = 0; n < recovery_width && program.size() > keep; ++n) {
                program.pop_back(); tail = (tail + capacity - 1) % capacity;
            }
            recovering = program.size() > keep;
        } else {
            for (unsigned n = 0; n < retired; ++n) { program.pop_front(); head = (head + 1) % capacity; }
            for (const auto &entry : allocated) program.push_back(entry);
        }
        return e;
    }
};

inline Request request(uint64_t serial, uint32_t opcode = 0x13) {
    return {true, UINT64_C(0xa81357bd80000000) ^ (serial << 2),
        uint32_t((serial * UINT64_C(0x137ad41)) & ~UINT32_C(127)) | opcode};
}
inline Completion completion(Token owner, bool fault = false, uint64_t salt = 0) {
    return {true, owner, UINT64_C(0x81ed23456789abcd) ^ (owner.tag * 67) ^ salt,
        UINT64_C(0xc321987680000004) ^ (owner.tag << 2) ^ (salt << 2), fault,
        UINT64_C(0x800000000000000d) ^ salt, UINT64_C(0xfedcba9876543210) ^ (salt << 1)};
}

template<class Model> void drive(Model &m, const Input &in) {
#define RI_DRIVE_LANE(N) \
    m.set_io$$rob$$in$$allocate##N##$$valid(in.allocate[N].valid); \
    m.set_io$$rob$$in$$allocate##N##$$bits$$pc(in.allocate[N].pc); \
    m.set_io$$rob$$in$$allocate##N##$$bits$$instruction(in.allocate[N].instruction); \
    m.set_io$$rob$$in$$allocate##N##$$bits$$rs1(0); \
    m.set_io$$rob$$in$$allocate##N##$$bits$$rs2(0); \
    m.set_io$$rob$$in$$allocate##N##$$bits$$rd(0); \
    m.set_io$$rob$$in$$allocate##N##$$bits$$writesRd(0); \
    m.set_io$$rob$$in$$complete##N##$$valid(in.complete[N].valid); \
    m.set_io$$rob$$in$$complete##N##$$bits$$token$$index(in.complete[N].token.index); \
    m.set_io$$rob$$in$$complete##N##$$bits$$token$$tag(in.complete[N].token.tag); \
    m.set_io$$rob$$in$$complete##N##$$bits$$data(in.complete[N].data); \
    m.set_io$$rob$$in$$complete##N##$$bits$$nextPc(in.complete[N].next_pc); \
    m.set_io$$rob$$in$$complete##N##$$bits$$exception(in.complete[N].fault); \
    m.set_io$$rob$$in$$complete##N##$$bits$$cause(in.complete[N].cause); \
    m.set_io$$rob$$in$$complete##N##$$bits$$tval(in.complete[N].tval)
    RI_DRIVE_LANE(0); RI_DRIVE_LANE(1);
#undef RI_DRIVE_LANE
#define RI_DRIVE_RECOVERY(N) \
    m.set_io$$rob$$in$$##N##$$valid(in.N.valid); \
    m.set_io$$rob$$in$$##N##$$bits$$token$$index(in.N.token.index); \
    m.set_io$$rob$$in$$##N##$$bits$$token$$tag(in.N.token.tag); \
    m.set_io$$rob$$in$$##N##$$bits$$inclusive(in.N.inclusive)
    RI_DRIVE_RECOVERY(external); RI_DRIVE_RECOVERY(local);
#undef RI_DRIVE_RECOVERY
    m.set_io$$rob$$in$$intent(in.intent_mask()); m.set_io$$rob$$in$$sameCycleRetire(in.same_cycle);
    m.set_io$$rob$$in$$dispatchReady(in.dispatch); m.set_io$$rob$$in$$commitEnable(in.commit);
    m.set_io$$rob$$in$$headTrap(in.head_trap); m.set_io$$rob$$in$$headSystem(in.head_system);
    m.set_io$$rob$$in$$loadOrderLimit$$valid(in.load_limit.valid);
    m.set_io$$rob$$in$$loadOrderLimit$$bits$$index(in.load_limit.token.index);
    m.set_io$$rob$$in$$loadOrderLimit$$bits$$tag(in.load_limit.token.tag);
}

template<class Model> std::array<Observation, 2> sample(Model &m) {
    std::array<Observation, 2> result{};
#define RI_GET(P, F) m.get_io$$rob$$##P##$$##F()
#define RI_SAMPLE_LANE(O, P, N) \
    O.allocated[N] = RI_GET(P, renamed##N##$$valid); \
    O.allocated_token[N] = {unsigned(RI_GET(P, renamed##N##$$bits$$token$$index)), \
        uint64_t(RI_GET(P, renamed##N##$$bits$$token$$tag))}; \
    O.source1[N] = RI_GET(P, renamed##N##$$bits$$source1); \
    O.source2[N] = RI_GET(P, renamed##N##$$bits$$source2); \
    O.destination[N] = RI_GET(P, renamed##N##$$bits$$destination); \
    O.old_destination[N] = RI_GET(P, renamed##N##$$bits$$oldDestination); \
    O.writes[N] = RI_GET(P, renamed##N##$$bits$$writesRd); O.alias[N] = RI_GET(P, renamed##N##$$bits$$moveAlias); \
    O.completed[N] = RI_GET(P, completionAccepted##N); \
    O.retired[N] = {bool(RI_GET(P, commit##N##$$valid)), \
        {unsigned(RI_GET(P, commit##N##$$bits$$token$$index)), uint64_t(RI_GET(P, commit##N##$$bits$$token$$tag))}, \
        uint64_t(RI_GET(P, commit##N##$$bits$$pc)), uint64_t(RI_GET(P, commit##N##$$bits$$data)), \
        uint64_t(RI_GET(P, commit##N##$$bits$$nextPc)), uint32_t(RI_GET(P, commit##N##$$bits$$instruction)), \
        unsigned(RI_GET(P, commit##N##$$bits$$rd)), unsigned(RI_GET(P, commit##N##$$bits$$destination)), \
        bool(RI_GET(P, commit##N##$$bits$$writesRd))}
#define RI_SAMPLE(O, P) \
    RI_SAMPLE_LANE(O, P, 0); RI_SAMPLE_LANE(O, P, 1); \
    O.external_accepted = RI_GET(P, externalAccepted); O.external_wins = RI_GET(P, externalWins); \
    O.recovery_accepted = RI_GET(P, recoveryAccepted); O.trap_accepted = RI_GET(P, headTrapAccepted); \
    O.system_accepted = RI_GET(P, headSystemAccepted); O.recovering = RI_GET(P, recovering); \
    O.selected = {bool(RI_GET(P, selected$$valid)), \
        {unsigned(RI_GET(P, selected$$bits$$token$$index)), uint64_t(RI_GET(P, selected$$bits$$token$$tag))}, \
        bool(RI_GET(P, selected$$bits$$inclusive))}; \
    O.killed = RI_GET(P, killed); O.occupancy = RI_GET(P, occupancy); \
    O.head_valid = RI_GET(P, headValid); O.head_done = RI_GET(P, headDone); O.head_pc = RI_GET(P, headPc); \
    O.head_exception = RI_GET(P, headException$$valid); \
    O.exception_token = {unsigned(RI_GET(P, headException$$bits$$token$$index)), \
        uint64_t(RI_GET(P, headException$$bits$$token$$tag))}; \
    O.exception_pc = RI_GET(P, headException$$bits$$pc); O.cause = RI_GET(P, headException$$bits$$cause); \
    O.tval = RI_GET(P, headException$$bits$$tval); O.free_count = RI_GET(P, freeCount); \
    O.exhausted = RI_GET(P, tagExhausted); \
    O.system_token = {unsigned(RI_GET(P, headSystemToken$$index)), uint64_t(RI_GET(P, headSystemToken$$tag))}
    RI_SAMPLE(result[0], reference); RI_SAMPLE(result[1], candidate);
#undef RI_SAMPLE
#undef RI_SAMPLE_LANE
#undef RI_GET
    return result;
}

// These mutate sampled candidate OUTPUTS, never the owner model or RTL state.
// They are oracle-sensitivity controls, not functional-equivalence evidence.
inline bool mutate(Observation &out, const Input &in, const std::deque<Entry> &before,
        const std::string &kind) {
    if (kind == "final-veto" && in.commit && (out.recovering || out.recovery_accepted) && !before.empty()) {
        for (unsigned lane = 0; lane < 2; ++lane) if ((in.intent_mask() & (1u << lane)) &&
                in.complete[lane].token == before.front().token && !in.complete[lane].fault) {
            out.retired[0].valid = true;
            return true;
        }
    }
    if (kind == "high-tag") for (unsigned lane = 0; lane < 2; ++lane) {
        const auto &c = in.complete[lane];
        if (!c.valid || out.completed[lane]) continue;
        for (const auto &entry : before) if (entry.token.index == c.token.index &&
                (entry.token.tag ^ c.token.tag) == (UINT64_C(1) << 63)) {
            out.completed[lane] = true;
            return true;
        }
    }
    if (kind == "duplicate" && in.complete[0].valid && in.complete[1].valid &&
            in.complete[0].token == in.complete[1].token && out.completed[0] && !out.completed[1]) {
        out.completed[1] = true;
        return true;
    }
    if (kind == "lane-priority" && in.complete[0].valid && in.complete[1].valid &&
            in.complete[0].token == in.complete[1].token && out.retired[0].valid &&
            out.retired[0].token == in.complete[0].token && in.complete[0].data != in.complete[1].data) {
        out.retired[0].data = in.complete[1].data;
        return true;
    }
    return false;
}

template<class Model> class Fixture {
    Model &m;
    std::string mutation;
    bool mutation_fired = false;
    uint64_t request_serial = 0;
public:
    Oracle oracle;
    std::map<std::string, uint64_t> cover;
    explicit Fixture(Model &model, const std::string &mode) : m(model), mutation(mode) { reset(); }
    void reset() {
        drive(m, {}); m.set_reset(1); m.step(); m.step(); m.set_reset(0); oracle.reset(); ++cover["resets"];
        tick();
    }
    Observation tick(const Input &in = {}) {
        const auto before = oracle.program;
        const auto expected = oracle.advance(in);
        drive(m, in); m.step(); auto observations = sample(m);
        if (!mutation.empty() && !mutation_fired)
            mutation_fired = mutate(observations[1], in, before, mutation);
        for (unsigned side = 0; side < 2; ++side) {
            try { compare(observations[side], expected); }
            catch (const std::runtime_error &error) {
                throw std::runtime_error("ROB cycle=" + std::to_string(cover["cycles"]) +
                    (side ? " ON " : " OFF ") + error.what() +
                    (mutation_fired ? " [candidate output mutation " + mutation + "]" : ""));
            }
        }
        for (const std::string kind : {"final-veto", "high-tag", "lane-priority", "duplicate"}) {
            if (cover["sensitivity-" + kind]) continue;
            auto corrupt = observations[1];
            if (!mutate(corrupt, in, before, kind)) continue;
            bool rejected = false;
            try { compare(corrupt, expected); } catch (const std::runtime_error &) { rejected = true; }
            require(rejected, "candidate output mutation escaped independent oracle: " + kind);
            ++cover["sensitivity-" + kind];
        }
        if (in.load_limit.valid) {
            const int rank = locate(before, in.load_limit.token);
            ++cover[rank < 0 ? "limit-stale" : rank == 0 ? "limit-head" : "limit-prefix"];
        }
        cover["count-" + std::to_string(before.size())]++;
        ++cover["cycles"];
        cover["commits"] += expected.retired[0].valid + expected.retired[1].valid;
        cover["completions"] += expected.completed[0] + expected.completed[1];
        cover["recovery-accepted"] += expected.recovery_accepted;
        cover["recovery-rejected"] += (in.external.valid || in.local.valid) && !expected.recovery_accepted;
        cover["recovery-active"] += expected.recovering;
        cover["raw-intent-recovery"] += in.intent >= 0 && (expected.recovery_accepted || expected.recovering);
        if (expected.retired[0].valid && expected.retired[1].valid) {
            ++cover["commit2"];
            cover["commit2-start-slots"] |= 1u << expected.retired[0].token.index;
            cover["commit2-wrap"] += expected.retired[0].token.index == capacity - 1;
        }
        return observations[1];
    }
    void fill(unsigned count, uint32_t opcode = 0x13) {
        for (unsigned n = 0; n < count; n += 2) {
            Input in; in.allocate[0] = request(request_serial++, opcode);
            if (n + 1 < count) in.allocate[1] = request(request_serial++);
            const auto out = tick(in);
            require(out.allocated[0] && (n + 1 == count || out.allocated[1]), "directed allocation failed");
        }
    }
    Token token(unsigned rank) const {
        require(rank < oracle.program.size(), "test requested a missing program owner");
        return oracle.program[rank].token;
    }
    void settle() {
        while (oracle.recovering) tick();
        tick(); // Observe the completed rollback state before the next action.
    }
    void flush() {
        if (!oracle.program.empty() || oracle.recovering) { Input in; in.head_trap = true; tick(in); settle(); }
        require(oracle.program.empty(), "trap failed to empty the program");
    }
    void drain() {
        unsigned budget = 8 * capacity;
        while (!oracle.program.empty() || oracle.recovering) {
            require(budget-- != 0, "drain failed to make bounded progress");
            if (oracle.recovering) { tick(); continue; }
            if (oracle.program.front().done && oracle.program.front().result.fault) { flush(); continue; }
            Input in; in.commit = true;
            unsigned port = 0;
            for (const auto &entry : oracle.program) if (!entry.done && port < 2)
                in.complete[port++] = completion(entry.token);
            tick(in);
        }
        tick();
    }
    void finish() const {
        require(mutation.empty(), "requested output mutation did not encounter its witness: " + mutation);
        for (const std::string kind : {"final-veto", "high-tag", "lane-priority", "duplicate"})
            require(cover.at("sensitivity-" + kind) == 1, "missing output sensitivity witness " + kind);
        require(cover.at("high-completion-bits") == UINT64_MAX && cover.at("high-recovery-bits") == UINT64_MAX,
            "full 64-bit supplied-owner sweep incomplete");
        require(cover.at("commit2-start-slots") == 0xffff && cover.at("commit2-wrap") &&
            cover.at("raw-intent-recovery") && cover.at("recovery-active") && cover.at("recovery-rejected"),
            "required wrap/rollback/rejected-owner coverage incomplete");
        require(cover.at("limit-stale") && cover.at("limit-head") && cover.at("limit-prefix") &&
            cover.at("duplicate-slot1-branch") && cover.at("duplicate-slot1-fault") &&
            cover.at("count-0") && cover.at("count-1") && cover.at("count-2") && cover.at("count-16") &&
            cover.at("duplicate-high-bits") == UINT64_MAX && cover.at("younger-global-accept"),
            "retirement-slot-specific coverage incomplete");
        std::cout << "RETIREMENT_ROB_ORACLE PASS cycles=" << cover.at("cycles") << " commits=" << cover.at("commits")
            << " commit2=" << cover.at("commit2") << " wrapCommit2=" << cover.at("commit2-wrap")
            << " completionTagBits=64 recoveryTagBits=64 recoveryAccepted=" << cover.at("recovery-accepted")
            << " recoveryRejected=" << cover.at("recovery-rejected")
            << " rawIntentRecovery=" << cover.at("raw-intent-recovery")
            << " slot1BranchDuplicates=" << cover.at("duplicate-slot1-branch")
            << " slot1FaultDuplicates=" << cover.at("duplicate-slot1-fault")
            << " limitHead=" << cover.at("limit-head") << " limitPrefix=" << cover.at("limit-prefix")
            << " limitStale=" << cover.at("limit-stale") << " youngerGlobalAccept=" << cover.at("younger-global-accept")
            << " outputSensitivity=final-veto,high-tag,lane-priority,duplicate\n";
    }
};

template<class Model> void run(Model &m, const std::string &mutation) {
    require(mutation.empty() || mutation == "final-veto" || mutation == "high-tag" || mutation == "lane-priority" || mutation == "duplicate",
        "unknown candidate output mutation: " + mutation);
    Fixture<Model> f(m, mutation);
    Input in;

    // A legal completion with any one wrong supplied tag bit must fail on BOTH
    // ports; neither recovery candidate may authorize the same mismatched owner.
    f.fill(2);
    for (unsigned bit = 0; bit < 64; ++bit) {
        in = {}; in.commit = true;
        for (unsigned lane = 0; lane < 2; ++lane) {
            auto stale = f.token(lane); stale.tag ^= UINT64_C(1) << bit;
            in.complete[lane] = completion(stale);
        }
        const auto out = f.tick(in);
        require(!out.completed[0] && !out.completed[1] && !out.retired[0].valid, "wrong full tag became live");
        f.cover["high-completion-bits"] |= UINT64_C(1) << bit;
        in.external = {true, in.complete[0].token, bool(bit & 1)};
        in.local = {true, in.complete[1].token, !bool(bit & 1)};
        const auto rejected = f.tick(in);
        require(!rejected.recovery_accepted && !rejected.external_accepted, "wrong recovery tag became live");
        f.cover["high-recovery-bits"] |= UINT64_C(1) << bit;
    }
    f.drain();

    // Lane zero wins an actual duplicate, including data/next-PC selection.
    f.fill(2); in = {}; in.commit = true;
    in.complete[0] = completion(f.token(0), false, 0x1234);
    in.complete[1] = completion(f.token(0), false, 0xfabc);
    f.tick(in); f.drain();

    // Every same-cycle enable mask, reversed result ports, and saved done state.
    for (unsigned mask = 0; mask < 4; ++mask) for (unsigned reversed = 0; reversed < 2; ++reversed) {
        f.fill(2); in = {}; in.commit = true; in.same_cycle = mask;
        in.complete[0] = completion(f.token(reversed)); in.complete[1] = completion(f.token(1 - reversed));
        f.tick(in); in = {}; in.commit = true; f.tick(in); f.drain();
    }
    // An earlier branch offer still suppresses a later duplicate even though
    // the branch cannot retire until the registered done handoff.
    f.fill(2); const auto branch_owner = f.token(0);
    in = {}; in.commit = true; in.same_cycle = 2;
    in.complete[0] = completion(branch_owner, false, 0x1100);
    in.complete[1] = completion(branch_owner, false, 0xff00);
    auto out = f.tick(in);
    require(out.completed[0] && !out.completed[1] && !out.retired[0].valid, "branch duplicate stole retirement");
    in = {}; in.commit = true; in.complete[0] = completion(branch_owner, true, 0x4567);
    in.complete[1] = completion(f.token(1));
    out = f.tick(in);
    require(!out.completed[0] && out.retired[0].data == completion(branch_owner, false, 0x1100).data,
        "done owner accepted overwrite or lost original result");
    f.drain();

    // Earlier fault must suppress later nonfault duplicate, preserve precise
    // fault payload, and remain at the head until authorized inclusive rollback.
    f.fill(2); const auto fault_owner = f.token(0);
    in = {}; in.commit = true;
    in.complete[0] = completion(fault_owner, true, 0xa5);
    in.complete[1] = completion(fault_owner, false, 0x5a);
    out = f.tick(in);
    require(out.completed[0] && !out.completed[1] && !out.retired[0].valid, "fault duplicate retired");
    in = {}; in.commit = true; out = f.tick(in); require(out.head_exception, "precise fault missing");
    in.external = {true, fault_owner, false}; f.tick(in); f.settle();
    require(f.oracle.program.size() == 1, "exclusive fault recovery did not retain boundary");
    in = {}; in.external = {true, fault_owner, true}; f.tick(in); f.settle();

    // The same duplicate rules must hold at head+1 even when head can retire.
    for (bool fault : {false, true}) {
        f.fill(2); in = {}; in.complete[0] = completion(f.token(0)); f.tick(in);
        const auto second = f.token(1);
        in = {}; in.commit = true; in.same_cycle = fault ? 3 : 2;
        in.complete[0] = completion(second, fault, 0x12345);
        in.complete[1] = completion(second, false, 0x98765);
        out = f.tick(in);
        require(out.completed[0] && !out.completed[1] && out.retired[0].valid && !out.retired[1].valid,
            "head+1 raw duplicate stole second retirement slot");
        ++f.cover[fault ? "duplicate-slot1-fault" : "duplicate-slot1-branch"];
        f.drain();
    }
    // A stale earlier generation never suppresses an exact later full-token owner.
    for (unsigned bit = 0; bit < 64; ++bit) {
        f.fill(2); const auto exact = f.token(0); auto stale = exact; stale.tag ^= UINT64_C(1) << bit;
        in = {}; in.commit = true; in.complete[0] = completion(stale); in.complete[1] = completion(exact);
        out = f.tick(in);
        require(!out.completed[0] && out.completed[1] && out.retired[0].valid,
            "stale earlier tag blocked exact later raw offer");
        f.cover["duplicate-high-bits"] |= UINT64_C(1) << bit; f.drain();
    }
    // Global acceptance remains meaningful for a younger owner outside both retirement slots.
    f.fill(4); in = {}; in.commit = true; in.complete[0] = completion(f.token(3));
    out = f.tick(in);
    require(out.completed[0] && !out.retired[0].valid && !out.retired[1].valid,
        "head-local predicate replaced global completion authority");
    ++f.cover["younger-global-accept"]; f.drain();
    // Test the existing full-owner load-order limit, including same-index stale generation.
    for (unsigned limit = 0; limit < 3; ++limit) {
        f.fill(4); in = {}; in.commit = true; in.load_limit = {true, f.token(limit)};
        in.complete[0] = completion(f.token(0)); in.complete[1] = completion(f.token(1));
        out = f.tick(in);
        require(out.completed[0] && out.completed[1] && out.retired[0].valid == (limit > 0) &&
            out.retired[1].valid == (limit > 1), "strict older prefix escaped live load-order limit");
        f.drain();
    }
    f.fill(2); in = {}; in.commit = true; in.load_limit = {true, f.token(1)};
    in.load_limit.token.tag ^= UINT64_C(1) << 63;
    in.complete[0] = completion(f.token(0)); in.complete[1] = completion(f.token(1)); out = f.tick(in);
    require(out.completed[0] && out.completed[1] && !out.retired[0].valid && !out.retired[1].valid,
        "stale load-order limit did not fail closed"); f.drain();

    // Two commits can straddle slot 15 -> 0. Starting at every physical slot
    // also ensures comparisons do not accidentally rely on a nonwrapped head.
    for (unsigned slot = 0; slot < capacity; ++slot) {
        f.reset();
        for (unsigned n = 0; n < slot; ++n) { f.fill(1); in = {}; in.commit = true; in.complete[0] = completion(f.token(0)); f.tick(in); }
        f.fill(2); in = {}; in.commit = true;
        in.complete[0] = completion(f.token(1)); in.complete[1] = completion(f.token(0));
        out = f.tick(in); require(out.retired[0].valid && out.retired[1].valid, "two-wide wrap retirement failed");
    }

    // Full capacity does not borrow same-edge retire credits. Allocation holes
    // and dispatch stalls are tested independently of completion/commit readiness.
    f.reset(); f.fill(capacity);
    in = {}; in.commit = true; in.allocate = {request(991), request(992)};
    in.complete[0] = completion(f.token(0)); in.complete[1] = completion(f.token(1));
    out = f.tick(in); require(!out.allocated[0] && out.retired[1].valid, "full ROB borrowed retirement credits");
    in = {}; in.allocate[1] = request(993); f.tick(in);
    in.allocate[0] = request(994); in.dispatch = false; f.tick(in);
    f.drain();

    // A system instruction ends the commit prefix even when the younger entry
    // is simultaneously completing. Its result is still saved and later retires.
    f.fill(2, 0x73); in = {}; in.commit = true;
    in.complete[0] = completion(f.token(0)); in.complete[1] = completion(f.token(1));
    out = f.tick(in); require(out.retired[0].valid && !out.retired[1].valid, "system crossed retirement boundary");
    f.drain();

    // Both arbitrary recovery candidates: inclusive/exclusive boundaries, same
    // token ties, different token ordering, and stale candidates with live slots.
    for (unsigned shape = 0; shape < 6; ++shape) for (unsigned flags = 0; flags < 4; ++flags) {
        f.flush(); f.fill(12); in = {}; in.commit = true;
        const unsigned erank = shape == 1 ? 7 : shape == 5 ? 0 : 3;
        const unsigned lrank = shape == 0 ? 3 : shape == 1 ? 2 : shape == 4 ? 8 : 6;
        in.external = {true, f.token(erank), bool(flags & 1)};
        in.local = {true, f.token(lrank), bool(flags & 2)};
        if (shape == 2) in.external.token.tag ^= UINT64_C(1) << 63;
        if (shape == 3 || shape == 4) in.local.token.tag ^= UINT64_C(1) << 62;
        // Both raw execution offers are present, while recovery prekill removed
        // actual complete.valid. This must never expose speculative retirement.
        in.complete[0] = completion(f.token(0)); in.complete[0].valid = false;
        in.complete[1] = completion(f.token(1)); in.complete[1].valid = false;
        // Shape 3 has a valid older external; shape 4 likewise. All matrix
        // choices accept at least one boundary and are legal raw-only witnesses.
        in.intent = 3;
        out = f.tick(in);
        require(out.recovery_accepted && !out.retired[0].valid && !out.retired[1].valid,
            "recovery failed final retirement veto");
        if (f.oracle.recovering) {
            // The current head can complete and persist during rollback, but
            // must not commit until the entire rollback walk has finished.
            in = {}; in.commit = true;
            if (!f.oracle.program.empty()) in.complete[0] = completion(f.token(0));
            f.tick(in);
        }
        f.settle(); f.drain();
    }

    // A raw-only older port must not steal authoritative completion from a
    // surviving actual later port. Duplicate suppression for state writes uses
    // complete.valid; raw-intent duplicate suppression affects retirement only.
    f.fill(12); in = {}; in.external = {true, f.token(5), false}; in.commit = true;
    in.complete[0] = completion(f.token(0), false, 0xaaaa); in.complete[0].valid = false;
    in.complete[1] = completion(f.token(0), false, 0xbbbb); in.intent = 3;
    out = f.tick(in);
    require(!out.completed[0] && out.completed[1] && !out.retired[0].valid,
        "raw duplicate intent altered authoritative completion admission");
    f.settle(); f.drain();

    // A valid external request can lose to an older stale local raw candidate.
    // Preserve the established arbitration contract: the stale local cannot be
    // accepted, and the younger external does not silently replace it.
    f.fill(10); in = {};
    in.external = {true, f.token(7), true}; in.local = {true, f.token(2), false};
    in.local.token.tag ^= UINT64_C(1) << 63;
    out = f.tick(in);
    require(out.external_accepted && !out.external_wins && !out.recovery_accepted,
        "stale local raw priority contract changed");
    f.flush();

    // Active rollback rejects equal or wider boundaries, accepts a strict
    // shrink, and again applies the final retirement veto on the last walk beat.
    f.fill(16); in = {}; in.external = {true, f.token(6), false}; f.tick(in);
    require(f.oracle.recovering, "directed rollback should require multiple beats");
    in = {}; in.external = {true, f.token(6), false}; in.local = {true, f.token(7), true};
    out = f.tick(in); require(!out.recovery_accepted && out.recovering, "equal rollback boundary was readmitted");
    in = {}; in.external = {true, f.token(4), true}; in.local = {true, f.token(4), false};
    in.commit = true; in.complete[0] = completion(f.token(0)); in.complete[0].valid = false; in.intent = 1;
    out = f.tick(in); require(out.recovery_accepted && out.external_wins, "strict shrink or external tie failed");
    f.settle(); f.drain();

    // Kill then immediately reuse exactly the killed physical slot. The old full
    // owner cannot complete the replacement; the fresh tag is generated by our
    // allocation counter, never taken from a DUT output or injected into state.
    f.fill(4); const auto killed_owner = f.token(2);
    in = {}; in.external = {true, killed_owner, true}; f.tick(in); f.settle();
    f.fill(2); const auto reused_owner = f.token(2);
    require(killed_owner.index == reused_owner.index && killed_owner.tag != reused_owner.tag,
        "directed recovery did not exercise slot reuse");
    in = {}; in.complete[0] = completion(killed_owner); in.complete[1] = completion(reused_owner);
    out = f.tick(in); require(!out.completed[0] && out.completed[1], "killed owner defeated fresh owner");
    f.drain();

    // Trusted trap/system recovery uses the real public ports. A system retains
    // only its head and may save that result; a trap cancels every completion.
    f.fill(12); in = {}; in.head_system = true; in.commit = true;
    in.complete[0] = completion(f.token(0)); in.complete[1] = completion(f.token(1));
    out = f.tick(in); require(out.system_accepted && out.completed[0] && !out.completed[1], "system head survival failed");
    in = {}; in.head_trap = true; in.commit = true;
    in.complete[0] = completion(f.token(0)); f.tick(in); f.settle();
    f.fill(4); in = {}; in.head_system = true; in.external = {true, f.token(0), false};
    out = f.tick(in); require(out.external_wins && !out.system_accepted, "external head tie lost priority");
    f.settle(); f.drain();

    // Reproducible mixed traffic exercises legal state transitions beyond the
    // directed witnesses. History owners include committed and discarded tags.
    std::mt19937_64 rng(UINT64_C(0x7265746972657231));
    std::vector<Token> history;
    for (unsigned cycle = 0; cycle < 1200; ++cycle) {
        in = {}; in.commit = (rng() % 4) != 0; in.dispatch = (rng() % 5) != 0;
        in.same_cycle = unsigned(rng() & 3);
        for (unsigned lane = 0; lane < 2; ++lane) {
            if (rng() % 3) in.allocate[lane] = request(2000 + cycle * 2 + lane, rng() % 29 ? 0x13 : 0x73);
            if (!f.oracle.program.empty() && rng() % 4) {
                Token owner = f.token(unsigned(rng() % f.oracle.program.size()));
                if (!history.empty() && rng() % 7 == 0) owner = history[rng() % history.size()];
                if (rng() % 11 == 0) owner.tag ^= UINT64_C(1) << (rng() % 64);
                in.complete[lane] = completion(owner, rng() % 37 == 0, rng());
            }
        }
        if (in.complete[0].valid && rng() % 6 == 0) {
            in.complete[1] = in.complete[0]; in.complete[1].data ^= UINT64_C(0xdeafbeef98765432);
        }
        if (!f.oracle.program.empty()) {
            for (auto *candidate : {&in.external, &in.local}) if (rng() % 13 == 0) {
                *candidate = {true, f.token(unsigned(rng() % f.oracle.program.size())), bool(rng() & 1)};
                if (rng() % 4 == 0) candidate->token.tag ^= UINT64_C(1) << (rng() % 64);
            }
            in.head_trap = rng() % 79 == 0;
        }
        out = f.tick(in);
        for (unsigned lane = 0; lane < 2; ++lane) if (out.allocated[lane]) {
            // These values have just been checked against independently assigned
            // serial tags; history is stimulus only, never oracle state.
            history.push_back(out.allocated_token[lane]);
        }
    }
    f.drain(); f.finish();
}
} // namespace retirement_intent_rob

// Parent idles the backend separately. This touches public ROB inputs only and
// does not step or reset the shared model, so backend witnesses remain intact.
template<class Model> void idle_retirement_rob(Model &m) {
    retirement_intent_rob::Input in; in.dispatch = false; in.intent = 0;
    retirement_intent_rob::drive(m, in);
}
template<class Model> void run_retirement_rob(Model &m, const std::string &mutation = "") {
    const std::string prefix = "--mutate-";
    const std::string kind = mutation.compare(0, prefix.size(), prefix) == 0 ? mutation.substr(prefix.size()) : mutation;
    retirement_intent_rob::run(m, kind);
}
