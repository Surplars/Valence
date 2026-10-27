#include "BankedRobCompletionDataGsim.h"
#include "completion_payload_byte_oracle.h"
#include "retirement_slot_rob_oracle.h"
#include <iostream>
#include <map>
#include <random>
#include <string>
namespace ri = retirement_intent_rob;
namespace cb = completion_bytes;
// The retained independent program-order deque oracle covers ownership and
// control. This new, separate byte shadow observes storage lifetime including
// invalid output bytes, and deliberately contains no bank/writer-map formula.
struct StoredRow {
    bool initialized = false, done = false;
    cb::Row value;
    uint64_t cause = 0;
};
static void drive_fast(SBankedRobCompletionDataGsim &m, const ri::Completion &c) {
    m.set_io$$fastHeadRetire$$valid(c.valid);
    m.set_io$$fastHeadRetire$$bits$$token$$index(c.token.index);
    m.set_io$$fastHeadRetire$$bits$$token$$tag(c.token.tag);
    m.set_io$$fastHeadRetire$$bits$$data(c.data); m.set_io$$fastHeadRetire$$bits$$nextPc(c.next_pc);
    m.set_io$$fastHeadRetire$$bits$$exception(c.fault); m.set_io$$fastHeadRetire$$bits$$cause(c.cause);
    m.set_io$$fastHeadRetire$$bits$$tval(c.tval);
}
struct Pending { bool valid; ri::Token token; uint64_t pc, cause, tval; };
static std::array<Pending, 2> pending(SBankedRobCompletionDataGsim &m) {
#define P(N) {bool(m.get_io$$##N##PendingException$$valid()), \
    {unsigned(m.get_io$$##N##PendingException$$bits$$token$$index()), uint64_t(m.get_io$$##N##PendingException$$bits$$token$$tag())}, \
    uint64_t(m.get_io$$##N##PendingException$$bits$$pc()), uint64_t(m.get_io$$##N##PendingException$$bits$$cause()), \
    uint64_t(m.get_io$$##N##PendingException$$bits$$tval())}
    return {{P(reference), P(candidate)}};
#undef P
}
class Fixture {
    SBankedRobCompletionDataGsim m;
    std::array<StoredRow, 16> physical{};
    unsigned head = 0;
    uint64_t serial = 1;
    std::string mode;
    bool mutated = false;
public:
    ri::Oracle oracle;
    std::map<std::string, uint64_t> cover;
    explicit Fixture(std::string mode_) : mode(std::move(mode_)) { reset(); }
    void reset() {
        ri::drive(m, {}); drive_fast(m, {}); m.set_io$$inspectRegister(0);
        m.set_reset(1); m.step(); m.step(); m.set_reset(0);
        oracle.reset(); head = 0; ++cover["reset"];
        // Reset initializes logical head/count only. Previously known row bytes
        // and done state survive; virgin physical rows remain unobserved.
        tick();
    }
    ri::Completion result(ri::Token token, bool fault = false) {
        const auto p = cb::pattern(serial++);
        return {true, token, p.data, p.next_pc, fault, UINT64_C(0xfedc87658000000d) ^ serial, p.tval};
    }
    ri::Observation tick(const ri::Input &in = {}) {
        const auto before = oracle.program;
        const auto expected = oracle.advance(in);
        ri::drive(m, in); drive_fast(m, {}); m.set_io$$inspectRegister(0); m.step();
        auto actual = ri::sample(m); auto pend = pending(m);
        if (!mutated && mode == "--observe-high-tag") for (unsigned lane = 0; lane < 2; ++lane) {
            if (!in.complete[lane].valid || expected.completed[lane]) continue;
            for (const auto &e : before) if (e.token.index == in.complete[lane].token.index &&
                    (e.token.tag ^ in.complete[lane].token.tag) == (UINT64_C(1) << 63)) {
                actual[1].completed[lane] = true; mutated = true;
            }
        }
        if (!mutated && mode == "--observe-bypass" && expected.retired[0].valid && !before.front().done) {
            actual[1].retired[0].data ^= UINT64_C(1) << 63; mutated = true;
        }
        if (!mutated && mode == "--observe-retained-tval" && physical[head].initialized &&
                physical[head].done && (expected.recovery_accepted || expected.recovering)) {
            actual[1].tval ^= UINT64_C(1) << 63; mutated = true;
        }
        if (!mutated && mode == "--observe-allocate-zero" && physical[head].initialized &&
                !physical[head].done && !in.complete[0].valid && !in.complete[1].valid) {
            actual[1].retired[0].data = UINT64_C(0x8000000000000001); mutated = true;
        }
        if (mutated) std::cerr << "LEDGER_COMPLETION_OBSERVATION_MUTATION_REACHED " << mode << '\n';
        for (unsigned side = 0; side < 2; ++side) {
            ri::compare(actual[side], expected);
            const bool pending_valid = !before.empty() && before.front().done && before.front().result.fault && !expected.recovering;
            cb::require(pend[side].valid == pending_valid, "LEDGER_PENDING_EXCEPTION_VALID_ORACLE");
            if (pending_valid) {
                const auto &e = before.front();
                cb::require(pend[side].token == e.token && pend[side].pc == e.request.pc &&
                    pend[side].cause == e.result.cause && pend[side].tval == e.result.tval,
                    "LEDGER_PENDING_EXCEPTION_PAYLOAD_ORACLE");
            }
            for (unsigned lane = 0; lane < 2; ++lane) {
                const unsigned index = (head + lane) % 16;
                cb::require(actual[side].retired[lane].token.index == index, "LEDGER_HEAD_INDEX_ORACLE");
                const auto &old = physical[index];
                if (!old.initialized) { ++cover["uninitialized_output_skipped"]; continue; }
                cb::Row expected_bytes{true, {}};
                if (old.done) expected_bytes = old.value;
                else for (unsigned port = 0; port < 2; ++port) {
                    const auto &c = in.complete[port];
                    if (expected.completed[port] && c.token.index == index && !c.fault && ((in.same_cycle >> port) & 1))
                        expected_bytes = {true, cb::encode({c.data, c.next_pc, c.tval})};
                }
                cb::compare_field(actual[side].retired[lane].data, expected_bytes, 0, "LEDGER_RAW_DATA_BYTE_ORACLE");
                cb::compare_field(actual[side].retired[lane].next_pc, expected_bytes, 1, "LEDGER_RAW_NEXTPC_BYTE_ORACLE");
                ++cover[old.done ? "defined_done_projection" : "defined_not_done_projection"];
            }
            if (physical[head].initialized) {
                const cb::Row zero{true, {}};
                cb::compare_field(actual[side].tval, physical[head].done ? physical[head].value : zero,
                    2, "LEDGER_RAW_TVAL_BYTE_ORACLE");
                cb::require(actual[side].cause == physical[head].cause, "LEDGER_RAW_CAUSE_ORACLE");
                cb::require(pend[side].tval == actual[side].tval && pend[side].cause == actual[side].cause,
                    "LEDGER_PENDING_RAW_ALIAS_ORACLE");
            }
        }
        cb::require(m.get_io$$referenceSpeculativeMapping() == 0 && m.get_io$$candidateSpeculativeMapping() == 0 &&
            m.get_io$$referenceCommittedMapping() == 0 && m.get_io$$candidateCommittedMapping() == 0,
            "LEDGER_NONWRITER_RAT_ORACLE");
        for (unsigned lane = 0; lane < 2; ++lane) if (expected.completed[lane]) {
            const auto &c = in.complete[lane]; auto &row = physical[c.token.index];
            cb::require(row.initialized, "LEDGER_COMPLETION_PRECEDES_ALLOCATION");
            row.done = true; row.value = {true, cb::encode({c.data, c.next_pc, c.tval})}; row.cause = c.cause;
        }
        for (unsigned lane = 0; lane < 2; ++lane) if (expected.allocated[lane])
            physical[expected.allocated_token[lane].index] = {true, false, {true, {}}, 0};
        const unsigned committed = unsigned(expected.retired[0].valid) + unsigned(expected.retired[1].valid);
        if (committed == 2) { cover["dual_retire_start_mask"] |= UINT64_C(1) << head; cover["dual_retire_wrap"] += head == 15; }
        head = (head + committed) % 16;
        ++cover["cycles"]; cover["commits"] += committed;
        cover["dual_accept_same_parity"] += expected.completed[0] && expected.completed[1] &&
            in.complete[0].token.index % 2 == in.complete[1].token.index % 2;
        cover["reversed_writer_order"] += expected.completed[0] && expected.completed[1] &&
            in.complete[0].token.index > in.complete[1].token.index;
        cover["recovery_retained_done"] += (expected.recovery_accepted || expected.recovering) &&
            !before.empty() && before.front().done;
        cover["held_done"] += !in.commit && !before.empty() && before.front().done;
        cover["allocation_plus_completion"] += (expected.allocated[0] || expected.allocated[1]) &&
            (expected.completed[0] || expected.completed[1]);
        cover["head_system_keeps_head_completion"] += expected.system_accepted && expected.completed[0] &&
            in.complete[0].token == before.front().token;
        cover["head_system_rejects_younger"] += expected.system_accepted && in.complete[1].valid &&
            ri::locate(before, in.complete[1].token) > 0 && !expected.completed[1];
        cover["local_wins_competing_recovery"] += in.external.valid && in.local.valid &&
            expected.recovery_accepted && !expected.external_wins && expected.selected.token == in.local.token;
        cover["ongoing_recovery_shrinks"] += expected.recovering && expected.recovery_accepted;
        cover["stale_lane0_live_lane1_same_index"] += in.complete[0].valid && in.complete[1].valid &&
            in.complete[0].token.index == in.complete[1].token.index &&
            (in.complete[0].token.tag ^ in.complete[1].token.tag) == (UINT64_C(1) << 63) &&
            !expected.completed[0] && expected.completed[1];
        cover["bypass_retire"] += expected.retired[0].valid && !before.front().done;
        return actual[1];
    }
    void fill(unsigned n) {
        for (unsigned i = 0; i < n; i += 2) {
            ri::Input in; in.allocate[0] = ri::request(serial++);
            if (i + 1 < n) in.allocate[1] = ri::request(serial++);
            tick(in);
        }
    }
    ri::Token token(unsigned rank) const { return oracle.program.at(rank).token; }
    void settle() { unsigned budget = 8; while (oracle.recovering) { cb::require(budget--, "LEDGER_RECOVERY_TIMEOUT"); tick(); } tick(); }
    void flush() { if (!oracle.program.empty()) { ri::Input in; in.head_trap = true; tick(in); settle(); } }
    void drain() {
        unsigned budget = 128;
        while (!oracle.program.empty()) {
            cb::require(budget--, "LEDGER_DRAIN_TIMEOUT");
            if (oracle.recovering) { tick(); continue; }
            if (oracle.program.front().done && oracle.program.front().result.fault) { flush(); continue; }
            ri::Input in; in.commit = true; unsigned lane = 0;
            for (const auto &e : oracle.program) if (!e.done && lane < 2) in.complete[lane++] = result(e.token);
            tick(in);
        }
        tick();
    }
    void fast_bypass() {
        reset(); fill(1); const auto owner = token(0); const auto c = result(owner);
        ri::Input in; in.commit = true; ri::drive(m, in); drive_fast(m, c); m.step();
        const auto out = ri::sample(m);
        for (const auto &a : out) cb::require(a.retired[0].valid && !a.retired[1].valid &&
            a.retired[0].token == owner && a.retired[0].data == c.data && a.retired[0].next_pc == c.next_pc &&
            !a.completed[0] && !a.completed[1], "LEDGER_EXISTING_FAST_HEAD_BYPASS_ORACLE");
        ++cover["existing_fast_head_bypass"]; reset(); // Standalone trusted producer contract; no invented completion.
    }
    void finish() {
        cb::require(mode.empty(), "NEGATIVE_CONTROL_ESCAPED");
        for (const auto *name : {"dual_accept_same_parity", "reversed_writer_order", "dual_retire_wrap", "held_done",
                "recovery_retained_done", "bypass_retire", "existing_fast_head_bypass", "defined_not_done_projection",
                "defined_done_projection", "uninitialized_output_skipped", "allocation_plus_completion",
                "head_system_keeps_head_completion", "head_system_rejects_younger", "local_wins_competing_recovery",
                "ongoing_recovery_shrinks", "stale_lane0_live_lane1_same_index"})
            cb::require(cover[name] > 0, std::string("LEDGER_MISSING_COVERAGE ") + name);
        cb::require(cover["wrong_tag_bits"] == UINT64_MAX && cover["dual_retire_start_mask"] == 0xffff,
            "LEDGER_FULL_TAG_OR_HEAD_SWEEP_MISSING");
        std::cout << "LEDGER_COMPLETION_BYTE_ORACLE_PASS";
        for (const auto &[key, value] : cover) std::cout << ' ' << key << '=' << value;
        std::cout << " owner_oracle=retained_independent_deque storage_oracle=flat24bytes no_rtl_equivalence_as_oracle=1\n";
    }
};
int main(int argc, char **argv) { try {
    const std::string mode = argc == 2 ? argv[1] : "";
    cb::require(argc <= 2 && (mode.empty() || mode == "--observe-high-tag" || mode == "--observe-bypass" ||
        mode == "--observe-retained-tval" || mode == "--observe-allocate-zero"), "LEDGER_BAD_ARGUMENT");
    Fixture f(mode);
    f.fill(4); f.tick();
    for (unsigned bit = 0; bit < 64; ++bit) {
        ri::Input in; in.commit = true;
        for (unsigned lane = 0; lane < 2; ++lane) { auto stale = f.token(lane); stale.tag ^= UINT64_C(1) << bit; in.complete[lane] = f.result(stale); }
        f.tick(in); f.cover["wrong_tag_bits"] |= UINT64_C(1) << bit;
    }
    ri::Input in; in.complete[0] = f.result(f.token(2)); in.complete[1] = f.result(f.token(0)); f.tick(in);
    in = {}; in.complete[0] = f.result(f.token(3)); in.complete[1] = f.result(f.token(1)); f.tick(in);
    for (unsigned i = 0; i < 9; ++i) f.tick();
    f.drain();
    // A stale high-tag offer in the lower port is not a duplicate of the exact
    // live owner in the upper port. Both retain all64 owner bits.
    f.fill(4); in = {}; auto stale = f.token(0); stale.tag ^= UINT64_C(1) << 63;
    in.complete[0] = f.result(stale); in.complete[1] = f.result(f.token(0)); f.tick(in);
    // Allocation and accepted arbitrary completions coexist without touching
    // each other's rows; this exercises the real distinct-row contract.
    in = {}; in.allocate[0] = ri::request(0xa101); in.allocate[1] = ri::request(0xa102);
    in.complete[0] = f.result(f.token(3)); in.complete[1] = f.result(f.token(1)); f.tick(in); f.drain();
    // Every head index, including 15->0, accepts reversed completion-lane order
    // and retires a pair immediately with no new cycle or parity restriction.
    f.fill(1); f.drain();
    for (unsigned n = 0; n < 32; ++n) {
        f.fill(2); in = {}; in.commit = true;
        in.complete[0] = f.result(f.token(1)); in.complete[1] = f.result(f.token(0)); f.tick(in); f.tick();
        if (n == 15) { f.fill(1); f.drain(); }
    }
    f.fill(16);
    in = {}; in.complete[0] = f.result(f.token(0)); in.complete[1] = f.result(f.token(2)); f.tick(in);
    in = {}; in.external = {true, f.token(5), false}; f.tick(in); f.settle();
    f.drain();
    // Head fault tval remains byte-exact under precise exception suppression;
    // rollback does not clear stored completed payload bytes.
    f.fill(10); in = {}; in.complete[1] = f.result(f.token(0), true); f.tick(in); f.tick();
    in = {}; in.external = {true, f.token(4), false}; f.tick(in); f.settle(); f.flush();
    // Trusted head-system recovery accepts only the retained head's result.
    f.fill(12); in = {}; in.head_system = true;
    in.complete[0] = f.result(f.token(0)); in.complete[1] = f.result(f.token(1)); f.tick(in); f.settle(); f.drain();
    // The older local recovery wins competing candidates; an ongoing rollback
    // can subsequently shrink to an older exact external owner.
    f.fill(16); in = {}; in.complete[0] = f.result(f.token(0)); in.complete[1] = f.result(f.token(2)); f.tick(in);
    in = {}; in.external = {true, f.token(12), false}; in.local = {true, f.token(9), false}; f.tick(in);
    in = {}; in.external = {true, f.token(4), false}; f.tick(in); f.settle(); f.drain();
    f.reset(); f.fill(16); f.tick(); f.drain();
    // Duplicate completion arbitration: lower lane wins even with opposite field values.
    f.fill(2); in = {}; in.commit = true; in.complete[0] = f.result(f.token(0)); in.complete[1] = f.result(f.token(0));
    f.tick(in); f.drain();
    // Held/registered result when bypass is ineligible remains available next cycle.
    f.fill(2); in = {}; in.commit = true; in.same_cycle = 0;
    in.complete[0] = f.result(f.token(1)); in.complete[1] = f.result(f.token(0)); f.tick(in); f.tick(); f.drain();
    f.fast_bypass(); f.finish(); return 0;
} catch (const std::exception &e) { std::cerr << "LEDGER_COMPLETION_FAIL " << e.what() << '\n'; return 1; } }
