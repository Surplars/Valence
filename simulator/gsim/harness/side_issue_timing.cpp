#include "SideIssueTimingGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
static void source(SSideIssueTimingGsim& d, unsigned slot, unsigned a, unsigned b) {
#define SRC(i) case i: d.set_io$$source1$$r##i(a); d.set_io$$source2$$r##i(b); return
    switch (slot) {
        SRC(0); SRC(1); SRC(2); SRC(3); SRC(4); SRC(5); SRC(6); SRC(7);
        SRC(8); SRC(9); SRC(10); SRC(11); SRC(12); SRC(13); SRC(14); SRC(15);
    }
#undef SRC
    throw std::runtime_error("invalid source slot");
}
struct Allocation { bool valid = false; unsigned index = 0, a = 0, b = 0; };
struct Event { bool valid = false; unsigned index = 0; };
static void allocate(SSideIssueTimingGsim& d, unsigned lane, const Allocation& a) {
#define ALLOC(i) case i: d.set_io$$allocate##i##$$valid(a.valid); \
    d.set_io$$allocate##i##$$bits$$index(a.index); d.set_io$$allocate##i##$$bits$$source1(a.a); \
    d.set_io$$allocate##i##$$bits$$source2(a.b); return
    switch (lane) { ALLOC(0); ALLOC(1); }
#undef ALLOC
    throw std::runtime_error("invalid allocation lane");
}
static void wake(SSideIssueTimingGsim& d, unsigned port, Event e) {
#define WAKE(i) case i: d.set_io$$wake##i##$$valid(e.valid); d.set_io$$wake##i##$$bits(e.index); return
    switch (port) { WAKE(0); WAKE(1); WAKE(2); }
#undef WAKE
    throw std::runtime_error("invalid wake port");
}
static void reserve(SSideIssueTimingGsim& d, unsigned port, Event e) {
#define RESERVE(i) case i: d.set_io$$reserve##i##$$valid(e.valid); d.set_io$$reserve##i##$$bits(e.index); return
    switch (port) { RESERVE(0); RESERVE(1); }
#undef RESERVE
    throw std::runtime_error("invalid reserve port");
}
static std::array<unsigned, 2> oldest(uint16_t eligible, unsigned head) {
    std::array<unsigned, 2> result{};
    unsigned found = 0;
    // Independent procedural age walk, not a copied parallel prefix circuit.
    for (unsigned age = 0; age < 16 && found < 2; ++age) {
        const unsigned index = (head + age) % 16;
        if (eligible & (1U << index)) result[found++] = 1U << index;
    }
    return result;
}
enum CandidateFlag : uint16_t {
    CPending = 1U << 0, CSystem = 1U << 1, CMulDiv = 1U << 2,
    CMemory = 1U << 3, CStore = 1U << 4, CPrepared = 1U << 5,
    CKnown = 1U << 6, CUsePc = 1U << 7, CUseImmediate = 1U << 8,
    CControlFlow = 1U << 9
};
static void candidateFlags(SSideIssueTimingGsim& d, unsigned slot, unsigned flags) {
#define FLAGS(i) case i: d.set_io$$candidateFlags$$r##i(flags); return
    switch (slot) {
        FLAGS(0); FLAGS(1); FLAGS(2); FLAGS(3); FLAGS(4); FLAGS(5); FLAGS(6); FLAGS(7);
        FLAGS(8); FLAGS(9); FLAGS(10); FLAGS(11); FLAGS(12); FLAGS(13); FLAGS(14); FLAGS(15);
    }
#undef FLAGS
    throw std::runtime_error("invalid candidate slot");
}
struct CandidateInputs {
    std::array<uint16_t, 16> flags{};
    uint16_t ready1 = 0, ready2 = 0, promise1 = 0, promise2 = 0;
    unsigned head = 0;
    bool branchRedirect = false;
};
static CandidateInputs candidateGroup(std::mt19937_64& rng, unsigned group) {
    CandidateInputs in;
    in.head = group % 16;
    in.branchRedirect = group & 1;
    for (auto& flags : in.flags) flags = rng() & 1023;
    in.ready1 = rng(); in.ready2 = rng(); in.promise1 = rng(); in.promise2 = rng();
    auto fixed = [&](unsigned age, uint16_t flags, bool ready1, bool ready2) {
        const unsigned slot = (in.head + age) % 16, bit = 1U << slot;
        in.flags[slot] = flags;
        in.ready1 = (in.ready1 & ~bit) | (ready1 ? bit : 0);
        in.ready2 = (in.ready2 & ~bit) | (ready2 ? bit : 0);
    };
    const uint16_t store = CPending | CMemory | CStore;
    if ((group & 1) == 0) {
        fixed(0, store, true, true);                     // never prepare the head
    } else {
        fixed(0, CPending, false, true);                 // late ALU credit changes actual top-two grants
        in.promise1 |= 1U << in.head;
    }
    fixed(1, store, true, false);                        // address-only preparation
    fixed(2, store | CKnown, true, false);               // cannot repeatedly select address-only
    fixed(3, store | CKnown | CUsePc | CUseImmediate, false, false);
    fixed(7, CPending, false, true);                     // actual late-ALU sensitivity
    fixed(8, CPending, true, false);
    in.promise1 |= 1U << ((in.head + 7) % 16);
    in.promise2 |= 1U << ((in.head + 8) % 16);
    fixed(9, store | CControlFlow, true, true);
    // Keep half of the remaining slots randomized; the other half explicitly
    // exercises every class exclusion and each individually unused source.
    if ((group & 1) == 0) {
        fixed(4, store | CPrepared, true, true);
        fixed(5, store | CSystem, true, true);
        fixed(6, store | CMulDiv, true, true);
        fixed(10, CMemory | CStore, true, true);
        fixed(11, CPending | CMemory, true, true);
        fixed(12, store | CKnown | CUsePc, false, true);
        fixed(13, store | CKnown | CUseImmediate, true, false);
        fixed(14, CPending | CStore, true, true);          // memory flag is still mandatory
    }
    return in;
}
struct CandidateOracle { uint16_t stores = 0, alu = 0, all = 0; };
static CandidateOracle candidateOracle(const CandidateInputs& in, unsigned phase) {
    CandidateOracle out;
    // Interpret each reservation as a scheduling operation, then age-walk in
    // oldest(). No DUT eligibility bits or parallel-prefix ranks are an oracle.
    for (unsigned slot = 0; slot < 16; ++slot) {
        const unsigned flags = in.flags[slot], bit = 1U << slot;
        if (!(flags & CPending) || (flags & (CSystem | CMulDiv))) continue;
        if (in.branchRedirect && (flags & CControlFlow)) continue;
        const bool first = in.ready1 & bit, second = in.ready2 & bit;
        if (flags & CMemory) {
            if (!(flags & CStore) || (flags & CPrepared) || slot == in.head) continue;
            if (!(flags & CUsePc) && !first) continue;
            // Preparing the address is useful once even if store data is late.
            if ((flags & CKnown) && !(flags & CUseImmediate) && !second) continue;
            out.stores |= bit;
        } else {
            const bool promisedFirst = phase == 0 && (in.promise1 & bit);
            const bool promisedSecond = phase == 0 && (in.promise2 & bit);
            if (!(flags & CUsePc) && !first && !promisedFirst) continue;
            if (!(flags & CUseImmediate) && !second && !promisedSecond) continue;
            out.alu |= bit;
        }
    }
    out.all = out.stores | out.alu;
    return out;
}
static void candidateDrive(SSideIssueTimingGsim& d, const CandidateInputs& in, unsigned phase) {
    for (unsigned slot = 0; slot < 16; ++slot) candidateFlags(d, slot, in.flags[slot]);
    d.set_io$$candidateReady1(in.ready1); d.set_io$$candidateReady2(in.ready2);
    d.set_io$$candidateHead(in.head); d.set_io$$candidateBranchRedirect(in.branchRedirect);
    d.set_io$$aluPromise1(in.promise1); d.set_io$$aluPromise2(in.promise2);
    d.set_io$$executionOccupied(1);
    d.set_io$$executionForwardable(phase != 3);
    d.set_io$$executionDeqReady(phase != 2);
    d.set_io$$multiplyFinish(phase == 1);
}
int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    const bool injectStore = argc > 1 && std::string_view(argv[1]) == "--inject-store-candidate";
    SSideIssueTimingGsim d;
    std::mt19937_64 rng(0x20261003d15ULL);
    std::mt19937_64 candidateRng(0x20261004e16ULL);
    CandidateInputs candidateInputs;
    uint16_t invariantCandidates = 0, invariantAlu = 0, invariantGrants = 0;
    std::array<unsigned, 2> invariantOwners{};
    unsigned candidateChecks = 0, storeInvariantPairs = 0, aluPromiseChanges = 0, storeGrantChanges = 0;
    unsigned headExcluded = 0, partialAddress = 0, knownDataWait = 0, unusedSources = 0;
    unsigned preparedExcluded = 0, classExcluded = 0, controlHeld = 0, candidateWrap = 0;
    std::array<unsigned, 16> a{}, b{};
    uint64_t physical = 0xffffffffULL;
    uint16_t active = 0;
    unsigned cycles = 0, compared = 0, collisions = 0, replaced = 0, samePacketRaw = 0;
    unsigned aliasInit = 0, lateBlocked = 0, dualClasses = 0, storeGrants = 0, wrapped = 0;
    auto reset = [&] {
        physical = 0xffffffffULL; active = 0; a.fill(63); b.fill(63);
        d.set_io$$physical(physical); d.set_io$$active(0);
        for (unsigned i = 0; i < 16; ++i) source(d, i, a[i], b[i]);
        for (unsigned i = 0; i < 2; ++i) { allocate(d, i, {}); reserve(d, i, {}); }
        for (unsigned i = 0; i < 3; ++i) wake(d, i, {});
        d.set_io$$head(0); d.set_io$$stores(0); d.set_io$$others(0);
        d.set_io$$multiply(0); d.set_io$$divide(0);
        d.set_io$$multiplyReady(0); d.set_io$$divideReady(0);
        candidateDrive(d, CandidateInputs{}, 0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    };
    reset();
    for (unsigned cycle = 0; cycle < 6000; ++cycle) {
        if (cycle == 3000) reset();
        std::array<Allocation, 2> allocation{};
        std::array<Event, 3> wakes{};
        std::array<Event, 2> reserves{};
        for (auto& e : wakes) e = {rng() % 3 != 0, unsigned(rng() % 48)};
        for (auto& e : reserves) e = {rng() % 3 == 0, 32 + unsigned(rng() % 16)};
        for (unsigned i = 0; i < 2; ++i)
            allocation[i] = {rng() % 3 != 0, (cycle + i) % 16, unsigned(rng() % 48), unsigned(rng() % 48)};
        // Same-packet producer/consumer, simultaneous wake+reserve, aliased
        // sources, x0, and replace-after-recovery are deterministic each block.
        if (cycle % 8 == 0) {
            const unsigned destination = 32 + cycle % 16;
            allocation[0] = {true, cycle % 16, 0, 0};
            allocation[1] = {true, (cycle + 1) % 16, destination, destination};
            reserves[0] = {true, destination}; wakes[0] = {true, destination};
            ++samePacketRaw;
        }
        if (cycle % 8 == 1) {
            const unsigned alias = (cycle * 7) % 48;
            allocation[0] = {true, cycle % 16, alias, alias};
            // A move alias reserves no new destination. Wake may still arrive
            // on this edge and must be visible to the newly allocated owner.
            wakes[0] = {true, alias}; reserves = {}; ++aliasInit;
        }
        for (auto w : wakes) for (auto r : reserves)
            collisions += w.valid && r.valid && w.index == r.index;
        const uint16_t clearing = cycle % 11 == 0 ? uint16_t(rng()) : 0;
        const unsigned head = cycle % 16;
        const uint16_t stores = rng(), others = uint16_t(rng()) & ~stores;
        const uint16_t multiply = rng(), divide = uint16_t(rng()) & ~multiply;
        const bool mReady = cycle & 1, dReady = cycle & 2;
        d.set_io$$physical(physical); d.set_io$$active(active);
        for (unsigned i = 0; i < 16; ++i) source(d, i, a[i], b[i]);
        for (unsigned i = 0; i < 2; ++i) { allocate(d, i, allocation[i]); reserve(d, i, reserves[i]); }
        for (unsigned i = 0; i < 3; ++i) wake(d, i, wakes[i]);
        d.set_io$$head(head); d.set_io$$stores(stores); d.set_io$$others(others);
        d.set_io$$multiply(multiply); d.set_io$$divide(divide);
        d.set_io$$multiplyReady(mReady); d.set_io$$divideReady(dReady);
        const unsigned candidatePhase = cycle % 4;
        if (candidatePhase == 0) candidateInputs = candidateGroup(candidateRng, cycle / 4);
        candidateDrive(d, candidateInputs, candidatePhase);
        d.step();
        // Full physical scoreboard is the oracle: no owner-local wake equations.
        // Inputs apply at the following edge, so inspect current owners first.
        for (unsigned i = 0; i < 16; ++i) if (active & (1U << i)) {
            check(a[i] < 48 && b[i] < 48, "invalid active fixture source");
            const bool expectedA = (physical >> a[i]) & 1;
            const bool expectedB = (physical >> b[i]) & 1;
            const bool actualA = bool((d.get_io$$ready1() >> i) & 1) ^ (inject && cycle == 100);
            check(actualA == expectedA && bool((d.get_io$$ready2() >> i) & 1) == expectedB,
                "owner readiness differs from independent physical scoreboard");
            ++compared;
        }
        const auto store = oldest(stores, head), shared = oldest(stores | others, head);
        check(d.get_io$$store0() == store[0] && d.get_io$$store1() == store[1], "store-only age selection");
        check(d.get_io$$shared0() == shared[0] && d.get_io$$shared1() == shared[1], "shared age selection");
        const unsigned grantedStores = (shared[0] | shared[1]) & stores;
        check((grantedStores & ~(store[0] | store[1])) == 0, "early store payload misses shared grant");
        storeGrants += __builtin_popcount(grantedStores);
        const auto m = oldest(multiply, head), div = oldest(divide, head);
        check(d.get_io$$multiplyOwner() == m[0] && d.get_io$$divideOwner() == div[0],
            "unit availability changed early M operand owner");
        // Old behavior's literal combined candidate list is the oracle.
        const uint16_t available = (mReady ? multiply : 0) | (dReady ? divide : 0);
        const unsigned grant = oldest(available, head)[0];
        check(bool(d.get_io$$selectedValid()) == bool(grant) &&
              bool(d.get_io$$multiplyGrant()) == bool(grant & multiply) &&
              bool(d.get_io$$divideGrant()) == bool(grant & divide), "late M class grant priority");
        if (grant) check((1U << d.get_io$$selectedIndex()) == grant, "late M selected owner");
        lateBlocked += (!mReady && m[0]) || (!dReady && div[0]);
        dualClasses += m[0] && div[0];
        wrapped += grant && (__builtin_ctz(grant) < head);
        const auto expectedCandidates = candidateOracle(candidateInputs, candidatePhase);
        const uint16_t actualCandidates = d.get_io$$candidateEligible() ^
            (injectStore && cycle == 104 ? (1U << candidateInputs.head) : 0);
        check(actualCandidates == expectedCandidates.stores, "store candidate semantics");
        check(d.get_io$$legacyStoreEligible() == expectedCandidates.stores,
            "generic issue filtered store semantics");
        check(d.get_io$$legacyAluEligible() == expectedCandidates.alu, "late ALU promise semantics");
        const auto candidateOwners = oldest(expectedCandidates.stores, candidateInputs.head);
        const auto candidateShared = oldest(expectedCandidates.all, candidateInputs.head);
        check(d.get_io$$candidate0() == candidateOwners[0] &&
              d.get_io$$candidate1() == candidateOwners[1], "exact early store payload owners");
        check(d.get_io$$candidateShared0() == candidateShared[0] &&
              d.get_io$$candidateShared1() == candidateShared[1], "semantic common issue owners");
        const uint16_t candidateGrants =
            (d.get_io$$candidateShared0() | d.get_io$$candidateShared1()) & actualCandidates;
        check((candidateGrants & ~(candidateOwners[0] | candidateOwners[1])) == 0,
            "semantic store payload misses authorized common top-two grant");
        if (candidatePhase == 0) {
            invariantCandidates = actualCandidates;
            invariantAlu = d.get_io$$legacyAluEligible();
            invariantOwners = candidateOwners;
            invariantGrants = candidateGrants;
            for (unsigned slot = 0; slot < 16; ++slot) {
                const unsigned flags = candidateInputs.flags[slot], bit = 1U << slot;
                const bool selected = actualCandidates & bit;
                const bool first = candidateInputs.ready1 & bit, second = candidateInputs.ready2 & bit;
                const bool storeClass = (flags & (CPending | CMemory | CStore)) ==
                    (CPending | CMemory | CStore);
                headExcluded += storeClass && slot == candidateInputs.head && !selected;
                partialAddress += selected && !(flags & (CKnown | CUseImmediate)) && !second;
                knownDataWait += storeClass && (flags & CKnown) && !(flags & CUseImmediate) &&
                    first && !second && !selected;
                unusedSources += selected &&
                    ((!first && (flags & CUsePc)) || (!second && (flags & CUseImmediate)));
                preparedExcluded += storeClass && (flags & CPrepared) && first && second && !selected;
                classExcluded += storeClass && (flags & (CSystem | CMulDiv)) && first && second && !selected;
                controlHeld += storeClass && candidateInputs.branchRedirect &&
                    (flags & CControlFlow) && first && second && !selected;
            }
            candidateWrap += candidateOwners[0] &&
                unsigned(__builtin_ctz(candidateOwners[0])) < candidateInputs.head;
        } else {
            check(actualCandidates == invariantCandidates && candidateOwners == invariantOwners,
                "late completion/dequeue/ALU promise changed early store payload ownership");
            ++storeInvariantPairs;
            aluPromiseChanges += d.get_io$$legacyAluEligible() != invariantAlu;
            storeGrantChanges += candidateGrants != invariantGrants;
        }
        ++candidateChecks;
        // Apply physical register events once, then ask the next iteration's
        // independently indexed source values. Allocation clearing wins wake.
        for (auto w : wakes) if (w.valid) physical |= uint64_t(1) << w.index;
        for (auto r : reserves) if (r.valid) physical &= ~(uint64_t(1) << r.index);
        active &= ~clearing;
        for (auto n : allocation) if (n.valid) {
            replaced += (active >> n.index) & 1;
            a[n.index] = n.a; b[n.index] = n.b; active |= 1U << n.index;
        }
        ++cycles;
    }
    check(compared > 30000 && collisions > 500 && replaced > 1000 && samePacketRaw == 750 &&
          aliasInit == 750 && lateBlocked > 2000 && dualClasses > 4000 && storeGrants > 3000 && wrapped > 50,
          "insufficient owner/side-issue boundary coverage");
    check(candidateChecks == 6000 && storeInvariantPairs == 4500 && aluPromiseChanges == 4500 &&
          storeGrantChanges >= 2250 && headExcluded >= 750 && partialAddress >= 1500 &&
          knownDataWait >= 1500 && unusedSources >= 1500 && preparedExcluded >= 750 &&
          classExcluded >= 1500 && controlHeld >= 750 && candidateWrap > 50,
          "insufficient store eligibility/late-credit boundary coverage");
    std::cout << "SIDE_ISSUE_TIMING_PASS cycles=" << cycles << " ready_checks=" << compared
              << " wake_reserve_collisions=" << collisions << " owner_replacements=" << replaced
              << " same_packet_raw=" << samePacketRaw << " alias_init=" << aliasInit
              << " blocked_units=" << lateBlocked << " dual_classes=" << dualClasses
              << " store_grants=" << storeGrants << " age_wrap=" << wrapped << " resets=2"
              << " store_candidates=" << candidateChecks << " store_invariant_pairs=" << storeInvariantPairs
              << " alu_promise_changes=" << aluPromiseChanges << " late_store_grant_changes=" << storeGrantChanges
              << " head_excluded=" << headExcluded << " partial_address=" << partialAddress
              << " known_data_wait=" << knownDataWait << " unused_sources=" << unusedSources
              << " prepared_excluded=" << preparedExcluded << " class_excluded=" << classExcluded
              << " control_held=" << controlHeld << " candidate_age_wrap=" << candidateWrap << '\n';
    return 0;
} catch (const std::exception& e) {
    std::cerr << "side issue timing oracle mismatch: " << e.what() << '\n'; return 1;
} }
