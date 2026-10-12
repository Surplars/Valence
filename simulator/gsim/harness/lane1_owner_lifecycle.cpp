#include "Lane1OwnerLifecycleGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token&) const = default;
};
struct Completion {
    bool valid = false;
    Token token;
    uint64_t data = 0;
    bool fault = false;
    uint64_t cause = 0, tval = 0;
};
struct Input {
    unsigned allocate = 0, sameCycle = 3;
    bool dispatch = true, commit = false;
    Completion first;
    bool secondEnable = true, secondFault = false;
    uint64_t secondData = 0, secondCause = 0, secondTval = 0;
    bool capture = false, fromRename = false, renameLane = false;
    Token captureToken;
    bool ready = false, kill = false;
    bool recover = false, inclusive = false;
    Token recoveryToken;
};
struct Row {
    bool known = false, done = false, fault = false;
    Token token;
    uint64_t data = 0, cause = 0, tval = 0;
};
struct Observation {
    bool match, known, occupied, valid, ready, cancel;
    Token slot;
    unsigned renamed;
    std::array<Token, 2> rename;
    unsigned accepted, committed;
    std::array<Token, 2> commit;
    std::array<uint64_t, 2> data;
    unsigned occupancy;
    bool recovering, recoveryAccepted, exception;
    uint64_t exceptionTag, cause, tval;
    bool mutationApplied;
};

static void drive(SLane1OwnerLifecycleGsim& d, const Input& s, unsigned mutation) {
    d.set_io$$allocate(s.allocate); d.set_io$$dispatchReady(s.dispatch);
    d.set_io$$commitEnable(s.commit); d.set_io$$sameCycleRetire(s.sameCycle);
    d.set_io$$complete0$$valid(s.first.valid);
    d.set_io$$complete0$$bits$$token$$index(s.first.token.index);
    d.set_io$$complete0$$bits$$token$$tag(s.first.token.tag);
    d.set_io$$complete0$$bits$$data(s.first.data);
    d.set_io$$complete0$$bits$$nextPc(s.first.data + 4);
    d.set_io$$complete0$$bits$$exception(s.first.fault);
    d.set_io$$complete0$$bits$$cause(s.first.cause);
    d.set_io$$complete0$$bits$$tval(s.first.tval);
    d.set_io$$complete1Enable(s.secondEnable); d.set_io$$complete1Data(s.secondData);
    d.set_io$$complete1Fault(s.secondFault); d.set_io$$complete1Cause(s.secondCause);
    d.set_io$$complete1Tval(s.secondTval);
    d.set_io$$captureValid(s.capture); d.set_io$$captureFromRename(s.fromRename);
    d.set_io$$captureRenameLane(s.renameLane);
    d.set_io$$captureIndex(s.captureToken.index); d.set_io$$captureTag(s.captureToken.tag);
    d.set_io$$dequeueReady(s.ready); d.set_io$$kill(s.kill);
    d.set_io$$recover$$valid(s.recover);
    d.set_io$$recover$$bits$$token$$index(s.recoveryToken.index);
    d.set_io$$recover$$bits$$token$$tag(s.recoveryToken.tag);
    d.set_io$$recover$$bits$$inclusive(s.inclusive); d.set_io$$mutation(mutation);
}

static Observation read(SLane1OwnerLifecycleGsim& d, bool shared) {
#define OBS(p) return {bool(d.get_io$$##p##$$ownerMatch()), bool(d.get_io$$##p##$$rowKnown()), \
    bool(d.get_io$$##p##$$occupied()), bool(d.get_io$$##p##$$dequeueValid()), \
    bool(d.get_io$$##p##$$enqueueReady()), bool(d.get_io$$##p##$$cancel()), \
    {unsigned(d.get_io$$##p##$$slotIndex()), d.get_io$$##p##$$slotTag()}, \
    unsigned(d.get_io$$##p##$$renamed()), \
    {{{unsigned(d.get_io$$##p##$$renameIndex0()), d.get_io$$##p##$$renameTag0()}, \
      {unsigned(d.get_io$$##p##$$renameIndex1()), d.get_io$$##p##$$renameTag1()}}}, \
    unsigned(d.get_io$$##p##$$accepted()), unsigned(d.get_io$$##p##$$committed()), \
    {{{unsigned(d.get_io$$##p##$$commitIndex0()), d.get_io$$##p##$$commitTag0()}, \
      {unsigned(d.get_io$$##p##$$commitIndex1()), d.get_io$$##p##$$commitTag1()}}}, \
    {{d.get_io$$##p##$$commitData0(), d.get_io$$##p##$$commitData1()}}, \
    unsigned(d.get_io$$##p##$$occupancy()), bool(d.get_io$$##p##$$recovering()), \
    bool(d.get_io$$##p##$$recoveryAccepted()), bool(d.get_io$$##p##$$headException()), \
    d.get_io$$##p##$$exceptionTag(), d.get_io$$##p##$$exceptionCause(), d.get_io$$##p##$$exceptionTval(), \
    bool(d.get_io$$##p##$$mutationApplied())}
    if (shared) { OBS(shared); }
    OBS(legacy);
#undef OBS
}

// The oracle is an ordered list of allocated owners, plus retained row history
// and a one-element FIFO. It never derives expected tokens from DUT outputs.
struct Oracle {
    std::array<Row, 16> rows{};
    std::deque<Token> live;
    unsigned tail = 0, keep = 0;
    uint64_t nextTag = 0;
    bool recovering = false, occupied = false;
    Token slot;
    std::vector<Token> history;
    unsigned position(Token token) const {
        auto it = std::find(live.begin(), live.end(), token);
        return unsigned(it - live.begin());
    }
    bool isLive(Token token) const { return position(token) < live.size(); }
};
struct Coverage {
    unsigned cycles = 0, allocations = 0, retirements = 0, dual = 0, duplicate = 0;
    unsigned fault = 0, rejected = 0, stalls = 0, retained = 0, emptyStale = 0;
    unsigned cancelBlocked = 0, cancelReplacement = 0, reuse = 0, recoveries = 0;
    unsigned activeRecovery = 0, sameEdge = 0, doneMatch = 0, reset = 0;
    uint64_t highBits = 0;
};

class Test {
public:
    SLane1OwnerLifecycleGsim dut;
    Oracle model;
    Coverage cover;
    unsigned mutation = 0;
    unsigned corruptions = 0;
    std::string phase;

    explicit Test(unsigned fault) : mutation(fault) {}
    void require(bool good, const std::string& message) const {
        if (!good) throw std::runtime_error("cycle=" + std::to_string(cover.cycles) +
            " phase=" + phase + " " + message);
    }
    void reset() {
        drive(dut, {}, mutation);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        model = {}; ++cover.reset;
        tick({}, "reset-empty-mask");
    }
    std::vector<Token> tick(const Input& s, const std::string& label) {
        phase = label;
        const Row& owner = model.rows[model.slot.index];
        const bool match = owner.known && owner.token == model.slot;
        // Unknown power-up rows are intentionally not inspected. Cancellation
        // must still be masked by the reset occupied bit.
        require(!model.occupied || owner.known, "test captured an uninitialized owner row");
        const bool cancel = model.occupied && (!match || s.kill);
        const bool valid = model.occupied && !cancel;
        const bool ready = !model.occupied || s.ready;
        const unsigned recoveryPosition = model.position(s.recoveryToken);
        const unsigned requestedKeep = recoveryPosition + !s.inclusive;
        const bool recoveryAccepted = s.recover && recoveryPosition < model.live.size() &&
            (!model.recovering || requestedKeep < model.keep);
        const bool recoveryCycle = model.recovering || recoveryAccepted;
        const unsigned activeKeep = recoveryAccepted ? requestedKeep : model.keep;
        const std::array<Completion, 2> completions{{s.first,
            {s.secondEnable && valid && s.ready, model.slot, s.secondData,
                s.secondFault, s.secondCause, s.secondTval}}};
        unsigned accepted = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto& c = completions[lane];
            const unsigned age = model.position(c.token);
            const bool duplicate = lane && completions[0].valid && completions[0].token == c.token;
            if (c.valid && age < model.live.size() && !model.rows[c.token.index].done && !duplicate &&
                (!recoveryCycle || age < activeKeep)) accepted |= 1U << lane;
            cover.rejected += c.valid && !(accepted >> lane & 1);
            cover.duplicate += c.valid && duplicate;
        }
        std::vector<Token> committed;
        std::array<uint64_t, 2> commitData{};
        if (s.commit && !recoveryCycle) {
            for (unsigned lane = 0; lane < 2 && lane < model.live.size(); ++lane) {
                const Token token = model.live[lane];
                const Row& row = model.rows[token.index];
                bool mayCommit = row.done && !row.fault;
                uint64_t data = row.data;
                if (!row.done) for (unsigned c = 0; c < 2; ++c) {
                    if ((accepted >> c & 1) && (s.sameCycle >> c & 1) &&
                        completions[c].token == token && !completions[c].fault) {
                        mayCommit = true; data = completions[c].data;
                    }
                }
                if (!mayCommit) break;
                committed.push_back(token); commitData[lane] = data;
            }
        }
        const bool exception = !model.live.empty() && model.rows[model.live.front().index].done &&
            model.rows[model.live.front().index].fault && !model.recovering && !recoveryAccepted;
        std::vector<Token> renamed;
        if (s.dispatch && !recoveryCycle) for (unsigned lane = 0; lane < 2; ++lane) {
            if (!(s.allocate >> lane & 1) || model.live.size() + lane >= 16) break;
            renamed.push_back({(model.tail + lane) % 16, model.nextTag + lane});
        }
        const bool captureValid = s.capture && (!s.fromRename || unsigned(s.renameLane) < renamed.size());
        const Token captureToken = s.fromRename && captureValid ? renamed[s.renameLane] : s.captureToken;
        drive(dut, s, mutation); dut.step();
        for (bool shared : {false, true}) {
            const Observation a = read(dut, shared);
            const std::string who = shared ? "shared " : "legacy ";
            if (a.mutationApplied) {
                ++corruptions;
                std::cout << "ACTUAL_CORRUPTION count=" << corruptions << " mode=" << mutation
                    << " cycle=" << cover.cycles << " phase=" << phase << std::endl;
            }
            require(a.known == owner.known, who + "accepted-token row initialization mismatch");
            if (owner.known && (shared || model.occupied))
                require(a.match == match, who + "pure 64-bit owner equality mismatch");
            require(a.slot == model.slot, who + "registered token payload mismatch");
            require(a.occupied == model.occupied, who + "slot occupancy mismatch");
            require(a.cancel == cancel, who + "occupied-masked cancel mismatch");
            require(a.valid == valid, who + "dequeue authorization mismatch");
            require(a.ready == ready, who + "cancel-independent enqueue credit mismatch");
            require(a.occupancy == model.live.size(), who + "ROB occupancy mismatch");
            require(a.recovering == model.recovering && a.recoveryAccepted == recoveryAccepted,
                who + "recovery state/admission mismatch");
            require(a.accepted == accepted, who + "final completion acceptance mismatch");
            require(a.renamed == (1U << renamed.size()) - 1, who + "rename prefix mismatch");
            for (unsigned lane = 0; lane < renamed.size(); ++lane)
                require(a.rename[lane] == renamed[lane], who + "independently predicted allocated token mismatch");
            require(a.committed == (1U << committed.size()) - 1, who + "ordered retirement mismatch");
            for (unsigned lane = 0; lane < committed.size(); ++lane)
                require(a.commit[lane] == committed[lane] && a.data[lane] == commitData[lane],
                    who + "retired owner/data mismatch");
            require(a.exception == exception, who + "precise fault visibility mismatch");
            if (exception) {
                const Row& head = model.rows[model.live.front().index];
                require(a.exceptionTag == head.token.tag && a.cause == head.cause && a.tval == head.tval,
                    who + "precise fault payload mismatch");
            }
        }
        ++cover.cycles; cover.allocations += renamed.size(); cover.retirements += committed.size();
        cover.dual += accepted == 3; cover.recoveries += recoveryAccepted;
        cover.activeRecovery += model.recovering;
        cover.stalls += valid && !s.ready;
        cover.retained += owner.known && match && !model.isLive(model.slot);
        cover.emptyStale += owner.known && !match && !model.occupied;
        cover.doneMatch += match && owner.done && model.occupied;
        cover.cancelBlocked += cancel && !ready && captureValid;
        cover.cancelReplacement += cancel && ready && captureValid;
        cover.sameEdge += cancel && ready && captureValid && !renamed.empty();
        for (unsigned lane = 0; lane < 2; ++lane) if (accepted >> lane & 1) {
            const auto& c = completions[lane]; Row& row = model.rows[c.token.index];
            row.done = true; row.data = c.data; row.fault = c.fault;
            row.cause = c.cause; row.tval = c.tval; cover.fault += c.fault;
        }
        if (recoveryCycle) {
            const unsigned removed = std::min(unsigned(model.live.size()) - activeKeep, 4U);
            for (unsigned n = 0; n < removed; ++n) model.live.pop_back();
            model.tail = (model.tail + 16 - removed) % 16;
            model.keep = activeKeep;
            model.recovering = model.live.size() > activeKeep;
        } else {
            for (unsigned n = 0; n < committed.size(); ++n) model.live.pop_front();
            for (Token token : renamed) {
                cover.reuse += model.rows[token.index].known;
                model.rows[token.index] = {true, false, false, token, 0, 0, 0};
                model.live.push_back(token); model.history.push_back(token);
            }
            model.nextTag += renamed.size(); model.tail = (model.tail + renamed.size()) % 16;
        }
        if (cancel || (valid && s.ready)) model.occupied = false;
        if (captureValid && ready) { model.occupied = true; model.slot = captureToken; }
        return renamed;
    }
    std::vector<Token> allocate(unsigned n, bool capture = false, bool lane = false) {
        Input s; s.allocate = (1U << n) - 1; s.capture = capture;
        s.fromRename = true; s.renameLane = lane;
        return tick(s, "allocate");
    }
    void capture(Token token, const std::string& label = "raw-capture") {
        Input s; s.capture = true; s.captureToken = token; tick(s, label);
    }
    void flush() {
        if (!model.live.empty()) {
            Input s; s.recover = true; s.recoveryToken = model.live.front();
            s.inclusive = true; s.kill = true; tick(s, "flush-start");
            while (model.recovering) { Input rest; rest.kill = true; tick(rest, "flush-walk"); }
        }
        Input clear; clear.kill = true; tick(clear, "flush-slot");
    }
};

int main(int argc, char** argv) { try {
    unsigned mutation = 0;
    if (argc == 2) {
        const std::string mode(argv[1]);
        if (mode == "--negative-high-tag") mutation = 1;
        else if (mode == "--negative-valid-qualified") mutation = 2;
        else if (mode == "--negative-unmasked-cancel") mutation = 3;
        else throw std::runtime_error("unknown negative-control option");
    } else if (argc != 1) throw std::runtime_error("expected at most one negative-control option");
    Test t(mutation); t.reset();
    const Token first = t.allocate(1, true).front();
    Input disabled; disabled.secondEnable = false;
    t.tick(disabled, "pure-match-while-completion-disabled-and-stalled");
    Input finish; finish.ready = true; finish.commit = true; finish.secondData = UINT64_C(0x80000000deadbeef);
    t.tick(finish, "normal-lane1-same-cycle-retirement");
    t.tick({}, "retired-row-retains-equality-with-empty-slot");
    t.capture(first, "recapture-just-retired-token");
    t.tick({}, "recaptured-retired-owner-still-matches");
    t.tick(finish, "recaptured-retired-owner-rejects-final-acceptance");
    // Every tag bit is changed through a public stage input. No internal state
    // seeding is needed to challenge the complete 64-bit comparison. Keep the
    // real row live and unfinished, so raw lane-0 rejection cannot pass merely
    // because the owner's liveness or done qualification would already fail.
    const Token probeOwner = t.allocate(1).front();
    for (unsigned bit = 0; bit < 64; ++bit) {
        Token stale = probeOwner; stale.tag ^= UINT64_C(1) << bit;
        t.capture(stale, "capture-single-bit-stale-tag-" + std::to_string(bit));
        Input probe; probe.ready = bit & 1; probe.first = {true, stale, bit, false, 0, 0};
        t.tick(probe, "reject-single-bit-stale-tag-" + std::to_string(bit));
        t.tick({}, "empty-retained-stale-payload-mask");
        t.cover.highBits |= UINT64_C(1) << bit;
    }
    t.flush();
    // Done, liveness and completion-valid qualification must remain separate
    // from the pure retained-row equality.
    auto done = t.allocate(1, true).front();
    Input external; external.first = {true, done, 0x102, false, 0, 0};
    t.tick(external, "complete-owner-externally-while-slot-stalls");
    t.tick({}, "done-owner-still-matches");
    Input duplicateDone; duplicateDone.ready = true; duplicateDone.commit = true;
    t.tick(duplicateDone, "done-owner-rejects-second-completion");
    auto retiredWhileHeld = t.allocate(1, true).front();
    Input retireExternal; retireExternal.first = {true, retiredWhileHeld, 0x103, false, 0, 0};
    retireExternal.commit = true;
    t.tick(retireExternal, "external-retirement-while-execution-payload-stalls");
    t.tick(disabled, "occupied-retired-owner-retains-pure-equality");
    t.tick(duplicateDone, "nonlive-retained-owner-cannot-complete-again");
    auto pair = t.allocate(2, true, true);
    Input dual; dual.first = {true, pair[0], 0x201, false, 0, 0};
    dual.ready = true; dual.secondData = 0x202; dual.commit = true;
    t.tick(dual, "dual-completion-and-retirement");
    pair = t.allocate(2, true, true);
    Input duplicate; duplicate.first = {true, pair[1], 0x301, false, 0, 0};
    duplicate.ready = true; duplicate.secondData = 0x302; duplicate.commit = true;
    t.tick(duplicate, "duplicate-lane0-wins");
    Input head; head.first = {true, pair[0], 0x300, false, 0, 0}; head.commit = true;
    t.tick(head, "duplicate-result-retains-lane0-data");
    auto fault = t.allocate(1, true).front();
    Input faulting; faulting.ready = true; faulting.commit = true;
    faulting.secondFault = true; faulting.secondCause = 13; faulting.secondTval = UINT64_C(0xfedcba9876543210);
    t.tick(faulting, "fault-completes-without-retirement");
    t.tick({}, "precise-head-fault-and-retained-owner-match");
    Input trap; trap.recover = true; trap.recoveryToken = fault; trap.inclusive = true;
    t.tick(trap, "inclusive-fault-recovery");
    auto old = t.allocate(1, true).front();
    Input replace; replace.allocate = 1; replace.capture = true; replace.fromRename = true;
    replace.ready = true; replace.kill = true;
    t.tick(replace, "same-edge-allocate-kill-replacement");
    t.tick({}, "replacement-owned-on-following-cycle");
    Input blocked = replace; blocked.ready = false;
    t.tick(blocked, "stalled-kill-cannot-lend-replacement-credit");
    t.tick({}, "stalled-kill-leaves-empty-slot");
    t.flush();
    // Repeated accepted-token circulation initializes every row and wraps the
    // ring many times, while the generation number continues monotonically.
    for (unsigned lap = 0; lap < 32; ++lap) {
        pair = t.allocate(2, true, true);
        Input both; both.first = {true, pair[0], 0x1000 + lap * 2, false, 0, 0};
        both.ready = true; both.secondData = 0x1001 + lap * 2; both.commit = true;
        t.tick(both, "ring-wrap-dual-retirement");
    }
    t.capture(old, "capture-old-generation-after-row-reuse");
    Input stale; stale.ready = true; stale.first = {true, old, 0, false, 0, 0};
    t.tick(stale, "reject-old-generation-after-row-reuse");
    for (unsigned n = 0; n < 8; ++n) t.allocate(2, n == 7, true);
    Input full; full.allocate = 3; full.capture = true; full.fromRename = true;
    t.tick(full, "full-rob-has-no-allocation-credit");
    Input recover; recover.recover = true; recover.recoveryToken = t.model.live[7];
    recover.kill = true; recover.allocate = 3; recover.first = {true, t.model.live.back(), 99, false, 0, 0};
    t.tick(recover, "recovery-rejects-younger-completion-and-allocation");
    Input shrink; shrink.recover = true; shrink.recoveryToken = t.model.live[1];
    shrink.inclusive = true; shrink.kill = true;
    shrink.first = {true, t.model.live.front(), 0x5151, false, 0, 0};
    t.tick(shrink, "strict-recovery-shrink-with-surviving-completion");
    while (t.model.recovering) t.tick({}, "multi-cycle-rollback");
    Input commit; commit.commit = true; t.tick(commit, "retire-surviving-recovery-prefix");
    t.flush();
    // Random traffic uses only host-owned historical or newly accepted tokens.
    // Liveness is searched in the ordered list, independently of ring arithmetic.
    std::mt19937_64 rng(UINT64_C(0x12a1e164b17));
    for (unsigned n = 0; n < 2400; ++n) {
        Input s; s.allocate = rng() % 4; s.dispatch = rng() % 7 != 0;
        s.commit = rng() % 3 != 0; s.sameCycle = rng() % 4;
        s.ready = rng() % 3 != 0; s.kill = rng() % 23 == 0;
        s.capture = rng() % 3 == 0; s.fromRename = rng() % 2; s.renameLane = rng() % 2;
        s.captureToken = t.model.history[rng() % t.model.history.size()];
        if (n % 17 == 0) s.captureToken.tag ^= UINT64_C(1) << (rng() % 64);
        s.secondEnable = rng() % 5 != 0; s.secondData = rng();
        s.secondFault = rng() % 29 == 0; s.secondCause = 7; s.secondTval = rng();
        if (!t.model.live.empty()) {
            s.first.valid = rng() % 3 != 0;
            s.first.token = t.model.live[rng() % t.model.live.size()];
            if (n % 7 == 0) s.first.token = t.model.slot;
            s.first.data = rng(); s.first.fault = rng() % 31 == 0;
            s.first.cause = 5; s.first.tval = rng();
            s.recover = rng() % 13 == 0;
            s.recoveryToken = t.model.live[rng() % t.model.live.size()];
            s.inclusive = rng() % 2;
            if (n % 19 == 0) s.recoveryToken.tag ^= UINT64_C(1) << 63;
            if (s.recover) s.kill = true;
        }
        t.tick(s, "seeded-owner-lifecycle-traffic");
    }
    // Reset cancels occupied state even though neither ROB nor queue rows have
    // reset payloads. A fresh generation-zero allocation reestablishes equality.
    t.flush(); t.allocate(1, true); t.reset(); t.allocate(1, true);
    t.tick(disabled, "post-reset-reallocated-owner-stalls");
    t.tick(finish, "post-reset-normal-retirement"); t.tick({}, "post-reset-retained-row");
    const auto& c = t.cover;
    t.require(c.highBits == UINT64_MAX && c.reset == 2 && c.retained && c.emptyStale &&
        c.doneMatch && c.dual && c.duplicate && c.fault && c.rejected && c.stalls &&
        c.cancelBlocked && c.cancelReplacement && c.sameEdge && c.reuse > 32 &&
        c.recoveries && c.activeRecovery, "required lifecycle coverage missing");
    t.require(mutation == 0, "negative control escaped the lifecycle oracle");
    std::cout << "LANE1_OWNER_LIFECYCLE_PASS cycles=" << c.cycles << " paired_robs=2 tag_bits=64"
        << " swept_bits=64 allocations=" << c.allocations << " retirements=" << c.retirements
        << " reuse=" << c.reuse << " dual=" << c.dual << " duplicates=" << c.duplicate
        << " faults=" << c.fault << " rejected=" << c.rejected << " stalls=" << c.stalls
        << " retained_nonlive=" << c.retained << " empty_stale=" << c.emptyStale
        << " done_match=" << c.doneMatch << " cancel_blocked=" << c.cancelBlocked
        << " cancel_replacement=" << c.cancelReplacement << " same_edge_allocate_kill_replace=" << c.sameEdge
        << " recoveries=" << c.recoveries << " active_recovery=" << c.activeRecovery
        << " resets=" << c.reset << '\n';
    return 0;
} catch (const std::exception& e) {
    std::cerr << "LANE1_OWNER_LIFECYCLE_FAIL " << e.what() << '\n'; return 1;
} }
