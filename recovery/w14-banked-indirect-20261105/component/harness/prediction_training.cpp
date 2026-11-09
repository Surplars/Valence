#include "PredictionTrainingGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef TRAIN_WIDTH
#define TRAIN_WIDTH 2
#endif
#ifndef COMPRESSED
#define COMPRESSED 1
#endif
#ifndef DELAYED_TRAINING
#define DELAYED_TRAINING 1
#endif
static void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Commit {
    bool valid = false, branch = false, indirect = false, taken = false;
    uint64_t pc = 0, next = 0;
    uint32_t instruction = 0x13;
};
using Packet = std::array<Commit, TRAIN_WIDTH>;
static void drive(SPredictionTrainingGsim& d, unsigned lane, const Commit& c, uint64_t pc) {
#define LANE(i) case i: \
    d.set_io$$retired$$lane##i##$$valid(c.valid); \
    d.set_io$$retired$$lane##i##$$bits$$pc(c.pc); \
    d.set_io$$retired$$lane##i##$$bits$$nextPc(c.next); \
    d.set_io$$retired$$lane##i##$$bits$$instruction(c.instruction); \
    d.set_io$$pc$$r##i(pc); break
    switch (lane) {
        LANE(0); LANE(1);
#if TRAIN_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("bad training lane");
    }
#undef LANE
}
struct Answer { bool taken, hit; uint64_t target; };
static Answer read(SPredictionTrainingGsim& d, unsigned lane) {
#define LANE(i) case i: return {bool(d.get_io$$taken$$r##i()), bool(d.get_io$$hit$$r##i()), d.get_io$$target$$r##i()}
    switch (lane) {
        LANE(0); LANE(1);
#if TRAIN_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("bad query lane");
    }
#undef LANE
}
// Source-only directed extension for the default 16-entry component.
// The old randomized oracle below is deliberately unchanged. This oracle uses
// explicit ISA test-vector classifications, not DUT decode helpers or outputs.
static void directedIndirect(SPredictionTrainingGsim& d, int argc, char** argv) {
    static_assert(TRAIN_WIDTH == 2 && COMPRESSED == 1 && DELAYED_TRAINING == 1,
        "directed component cases require the frozen default wrapper");
    bool injectHit = false, injectHigh = false;
    for (int i = 1; i < argc; ++i) {
        injectHit |= std::string_view(argv[i]) == "--inject-table-hit";
        injectHigh |= std::string_view(argv[i]) == "--inject-table-target-high";
    }
    struct Entry { bool valid = false; uint64_t pc = 0, target = 0; };
    std::array<Entry, 16> table{};
    Packet pending{};
    unsigned cycles = 0, queries = 0, hits = 0, misses = 0;
    unsigned highTag = 0, highTarget = 0, collision = 0, holes = 0;
    unsigned latency = 0, resetCancelled = 0, legalJalr = 0, legalCompressed = 0;
    unsigned badFunct3 = 0, ebreak = 0, mv = 0, add = 0;
    auto reset = [&] {
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) drive(d, lane, {}, 0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        table = {}; pending = {};
    };
    // Read/check old Q first. Applying last cycle's packet updates only the
    // software next state. A packet offered at c becomes query-visible at c+2.
    auto tick = [&](const Packet& offered, uint64_t q0, uint64_t q1,
                    unsigned expectedHitMask, const char* label) {
        const std::array<uint64_t, 2> query{q0, q1};
        for (unsigned lane = 0; lane < 2; ++lane) drive(d, lane, offered[lane], query[lane]);
        d.step();
        for (unsigned lane = 0; lane < 2; ++lane) {
            const Entry& e = table[(query[lane] >> 1) & 15];
            const bool expected = e.valid && e.pc == query[lane];
            check(expected == bool(expectedHitMask & (1u << lane)),
                "directed vector/model hit precondition mismatch");
            Answer actual = read(d, lane);
            // Negative controls alter observations only, never input or model.
            if (injectHit && expected) { actual.hit = !actual.hit; injectHit = false; }
            if (injectHigh && expected && (e.target >> 63)) {
                actual.target ^= uint64_t(1) << 63; injectHigh = false;
            }
            if (actual.hit != expected || (expected && actual.target != e.target)) {
                std::cerr << "directed=" << label << " cycle=" << cycles << " lane=" << lane
                    << " pc=" << std::hex << query[lane] << " expected_target=" << e.target
                    << " actual_target=" << actual.target << std::dec
                    << " expected_hit=" << expected << " actual_hit=" << actual.hit << '\n';
                throw std::runtime_error(actual.hit != expected ?
                    "directed indirect table hit mismatch" : "directed indirect table target mismatch");
            }
            ++queries; if (expected) ++hits; else ++misses;
        }
        for (const auto& c : pending) {
            if (c.valid && c.indirect) table[(c.pc >> 1) & 15] = {true, c.pc, c.next};
        }
        pending = offered;
        ++cycles;
    };
    auto event = [](uint64_t pc, uint64_t target, uint32_t instruction,
                    bool trains = true, bool valid = true) {
        Commit c; c.valid = valid; c.indirect = trains;
        c.pc = pc; c.next = target; c.instruction = instruction; return c;
    };
    const uint64_t a = 0x0000000012345602ULL;
    const uint64_t b = a ^ (uint64_t(1) << 63); // identical low 63 bits; full-PC tag differs
    const uint64_t lowTarget = 0x0000000087654320ULL;
    const uint64_t high = lowTarget ^ (uint64_t(1) << 63);
    reset();
    tick({event(a, lowTarget, 0x00008067), {}}, a, b, 0, "latency-c");
    tick({}, a, b, 0, "latency-c+1-no-bypass");
    tick({}, a, b, 1, "latency-c+2"); ++latency;
    tick({event(a, high, 0x00008067), {}}, a, b, 1, "target-high-c");
    tick({}, a, b, 1, "target-high-c+1-old-target");
    tick({}, a, b, 1, "target-high-c+2-new-target"); ++highTarget; ++highTag;
    // Both lanes target the same entry, but distinct full tags. Lane 1 wins.
    tick({event(a, lowTarget, 0x00008067), event(b, high, 0x000280e7)}, a, b, 1, "collision-c");
    tick({}, a, b, 1, "collision-c+1");
    tick({}, a, b, 2, "collision-lane1-wins"); ++collision; ++highTag;
    // Invalid lane 1 must not mask lane 0. Invalid lane 0 must not train.
    tick({event(a, lowTarget, 0x00008067), event(b, high, 0x000280e7, true, false)}, a, b, 2, "hole-lane1-c");
    tick({}, a, b, 2, "hole-lane1-c+1");
    tick({}, a, b, 1, "hole-lane1-result"); ++holes;
    tick({event(a, lowTarget, 0x00008067, true, false), event(b, high, 0x000280e7)}, a, b, 1, "hole-lane0-c");
    tick({}, a, b, 1, "hole-lane0-c+1");
    tick({}, a, b, 2, "hole-lane0-result"); ++holes;
    // Reset while a valid replacement is pending: clears table and cancels it.
    tick({event(a, high, 0x00008067), {}}, a, b, 2, "reset-pending-offer");
    check(pending[0].valid && pending[0].indirect, "reset pending precondition");
    reset();
    tick({}, a, b, 0, "reset-cleared"); tick({}, a, b, 0, "reset-no-resurrection");
    tick({}, a, b, 0, "reset-drained"); ++resetCancelled;
    // JALR rd/rs1 register choices are orthogonal to table training, including
    // x0 base, ordinary registers and link registers; immediate is nonzero.
    const std::array<unsigned, 4> rs1{0, 5, 17, 31}, rd{0, 1, 5, 27};
    for (unsigned i = 0; i < rs1.size(); ++i) {
        reset();
        const uint32_t instruction = (0x123u << 20) | (rs1[i] << 15) | (rd[i] << 7) | 0x67u;
        tick({event(b, high + 2 * i, instruction), {}}, b, a, 0, "legal-jalr-c");
        tick({}, b, a, 0, "legal-jalr-c+1");
        tick({}, b, a, 1, "legal-jalr-result"); ++legalJalr;
    }
    // Legal C.JR and C.JALR, with two distinct nonzero rs1 registers each.
    for (uint32_t instruction : {0x8282u, 0x8f82u, 0x9282u, 0x9f82u}) {
        reset();
        tick({Commit{}, event(b, high, instruction)}, b, a, 0, "legal-compressed-c");
        tick({}, b, a, 0, "legal-compressed-c+1");
        tick({}, b, a, 1, "legal-compressed-result"); ++legalCompressed;
    }
    // Illegal funct3 JALR and non-jump compressed neighbors must neither
    // allocate cold entries nor overwrite an existing matching entry's target.
    const std::array<uint32_t, 10> rejected{
        0x00009067, 0x0000a067, 0x0000b067, 0x0000c067, 0x0000d067, 0x0000e067, 0x0000f067,
        0x9002, 0x8286, 0x9286}; // C.EBREAK, C.MV x5,x1, C.ADD x5,x1
    for (unsigned i = 0; i < rejected.size(); ++i) {
        reset();
        tick({event(a, high, rejected[i], false), event(b, high, rejected[i], false)}, a, b, 0, "rejected-cold-c");
        tick({}, a, b, 0, "rejected-cold-c+1");
        tick({}, a, b, 0, "rejected-cold-result");
        tick({event(a, lowTarget, 0x00008067), {}}, a, b, 0, "rejected-seed-c");
        tick({}, a, b, 0, "rejected-seed-c+1");
        tick({event(a, high, rejected[i], false), event(b, high, rejected[i], false)}, a, b, 1, "rejected-warm-c");
        tick({}, a, b, 1, "rejected-warm-c+1");
        tick({}, a, b, 1, "rejected-warm-result");
        if (i < 7) ++badFunct3; else if (i == 7) ++ebreak; else if (i == 8) ++mv; else ++add;
    }
    check(highTag == 2 && highTarget == 1 && collision == 1 && holes == 2 && latency == 1 &&
        resetCancelled == 1 && legalJalr == 4 && legalCompressed == 4 && badFunct3 == 7 &&
        ebreak == 1 && mv == 1 && add == 1 && hits && misses,
        "directed indirect coverage incomplete");
    check(!injectHit && !injectHigh, "requested negative control did not fire");
    std::cout << "GSIM directed indirect: PASS cycles=" << cycles << " queries=" << queries
        << " hits=" << hits << " misses=" << misses << " full64Tag=" << highTag
        << " targetHigh=" << highTarget << " distinctTagCollision=" << collision
        << " validHoles=" << holes << " latencyTriplets=" << latency
        << " resetCancelled=" << resetCancelled << " legalJalr=" << legalJalr
        << " legalCompressed=" << legalCompressed << " illegalFunct3=" << badFunct3
        << " cEbreak=" << ebreak << " cMv=" << mv << " cAdd=" << add << '\n';
}

// W14-only extension. The original randomized and directed suites remain unchanged.
static void bankedIndirect(SPredictionTrainingGsim& d, int argc, char** argv) {
    static_assert(TRAIN_WIDTH == 2 && COMPRESSED == 1 && DELAYED_TRAINING == 1);
    bool injectStaleHit = false;
    for (int i = 1; i < argc; ++i)
        injectStaleHit |= std::string_view(argv[i]) == "--inject-bank-stale-hit";
    struct Entry { bool valid = false; uint64_t pc = 0, target = 0; };
    std::array<Entry, 16> table{};
    Packet pending{};
    unsigned cycles = 0, queries = 0, hits = 0, misses = 0;
    unsigned staleMiss = 0, ownerFlip = 0, samePc = 0, sameIndex = 0;
    unsigned parallelSameParity = 0, continuous = 0, resetCancelled = 0;
    unsigned rowCoverage = 0, owner0Coverage = 0, owner1Coverage = 0;
    auto event = [](uint64_t pc, uint64_t target) {
        Commit c; c.valid = true; c.indirect = true;
        c.pc = pc; c.next = target; c.instruction = 0x00008067; return c;
    };
    auto reset = [&](const Packet& offered = Packet{}) {
        for (unsigned lane = 0; lane < 2; ++lane) drive(d, lane, offered[lane], 0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        table = {}; pending = {};
    };
    // Independent logical row oracle: no physical bank, owner or DUT internal ABI.
    // Check cached old Q, then apply pending in lane order, then capture offered.
    auto tick = [&](const Packet& offered, uint64_t q0, uint64_t q1,
                    unsigned expectedHitMask, const char* label) {
        const std::array<uint64_t, 2> query{q0, q1};
        for (unsigned lane = 0; lane < 2; ++lane) drive(d, lane, offered[lane], query[lane]);
        d.step();
        for (unsigned lane = 0; lane < 2; ++lane) {
            const Entry& e = table[(query[lane] >> 1) & 15];
            const bool expected = e.valid && e.pc == query[lane];
            check(expected == bool(expectedHitMask & (1u << lane)),
                "banked vector/model hit precondition mismatch");
            Answer actual = read(d, lane);
            // This exact window has valid owner1/B and stale owner0/A, not an invalid row.
            if (injectStaleHit && lane == 0 && std::string_view(label) == "owner-0-to-1-stale-A") {
                check(e.valid && !expected, "stale-bank negative precondition");
                actual.hit = true; injectStaleHit = false;
            }
            if (actual.hit != expected || (expected && actual.target != e.target)) {
                std::cerr << "banked=" << label << " cycle=" << cycles << " lane=" << lane
                    << " pc=" << std::hex << query[lane] << " expected_target=" << e.target
                    << " actual_target=" << actual.target << std::dec
                    << " expected_hit=" << expected << " actual_hit=" << actual.hit << '\n';
                throw std::runtime_error(actual.hit != expected ?
                    "banked indirect table hit mismatch" : "banked indirect table target mismatch");
            }
            ++queries; if (expected) ++hits; else ++misses;
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto& c = pending[lane];
            if (c.valid && c.indirect) {
                const unsigned row = (c.pc >> 1) & 15;
                table[row] = {true, c.pc, c.next};
                rowCoverage |= 1u << row;
                (lane == 0 ? owner0Coverage : owner1Coverage) |= 1u << row;
            }
        }
        pending = offered;
        ++cycles;
    };
    const uint64_t a = 0x0000000012345602ULL;
    const uint64_t b = a ^ (uint64_t(1) << 63);
    const uint64_t c = a ^ (uint64_t(1) << 40);
    const uint64_t t0 = 0x0000000087654320ULL;
    const uint64_t t1 = t0 ^ (uint64_t(1) << 63);
    reset();
    tick({event(a, t0), Commit{}}, a, b, 0, "seed-owner0-c");
    tick({}, a, b, 0, "seed-owner0-c+1");
    tick({}, a, b, 1, "seed-owner0-c+2");
    tick({Commit{}, event(b, t1)}, a, b, 1, "owner-0-to-1-c");
    tick({}, a, b, 1, "owner-0-to-1-c+1");
    tick({}, a, b, 2, "owner-0-to-1-stale-A"); ++staleMiss; ++ownerFlip;
    tick({event(c, t0 + 2), Commit{}}, b, c, 1, "owner-1-to-0-c");
    tick({}, b, c, 1, "owner-1-to-0-c+1");
    tick({}, b, c, 2, "owner-1-to-0-stale-B"); ++staleMiss; ++ownerFlip;
    // Both queries remain fixed on one PC while the owner changes and target differs.
    tick({Commit{}, event(c, t1 + 4)}, c, c, 3, "same-PC-owner1-c");
    tick({}, c, c, 3, "same-PC-owner1-c+1-old-target");
    tick({}, c, c, 3, "same-PC-owner1-c+2-new-target"); ++samePc; ++ownerFlip;
    tick({event(c, t0 + 6), Commit{}}, c, c, 3, "same-PC-owner0-c");
    tick({}, c, c, 3, "same-PC-owner0-c+1-old-target");
    tick({}, c, c, 3, "same-PC-owner0-c+2-new-target"); ++samePc; ++ownerFlip;
    tick({event(a, t0 + 8), event(b, t1 + 10)}, a, b, 0, "dual-same-index-c");
    tick({}, a, b, 0, "dual-same-index-c+1");
    tick({}, a, b, 2, "dual-same-index-lane1-wins"); ++sameIndex; ++staleMiss;
    // Indices 3 and 5 have the same parity: no accidental parity-bank arbitration.
    tick({event(a + 4, t0 + 12), event(a + 8, t1 + 14)}, a + 4, a + 8, 0, "dual-same-parity-c");
    tick({}, a + 4, a + 8, 0, "dual-same-parity-c+1");
    tick({}, a + 4, a + 8, 3, "dual-same-parity-result"); ++parallelSameParity;
    for (unsigned i = 0; i < 6; ++i) {
        Packet offered{};
        offered[i & 1] = event(c, (i & 1 ? t1 : t0) + 32 + 2 * i);
        tick(offered, b, c, i < 2 ? 1 : 2, "continuous-owner-flip");
        ++continuous;
    }
    tick({}, b, c, 2, "continuous-drain-c+1");
    tick({}, c, c, 3, "continuous-drain-c+2");
    // Reset overlaps a valid pending packet and a different valid offered packet.
    tick({event(a, t0 + 64), event(b, t1 + 66)}, c, c, 3, "reset-pending-offer");
    check(pending[0].valid && pending[1].valid, "banked reset pending precondition");
    reset({event(c, t0 + 68), event(a, t1 + 70)});
    tick({}, a, b, 0, "reset-no-old-bank-hit");
    tick({}, c, a, 0, "reset-no-offered-resurrection");
    tick({}, a, b, 0, "reset-no-pending-resurrection"); ++resetCancelled;
    // Cover all 16 rows under both owners, without peeking at RAM or owner state.
    for (unsigned row = 0; row < 16; row += 2) {
        const uint64_t x = 0x60000000ULL + 2 * row, y = x + 2;
        tick({event(x, t0 + row), event(y, t1 + row)}, x, y, 0, "all-rows-seed-c");
        tick({}, x, y, 0, "all-rows-seed-c+1");
        tick({}, x, y, 3, "all-rows-seed-c+2");
        tick({event(y, t0 + row + 2), event(x, t1 + row + 2)}, x, y, 3, "all-rows-swap-c");
        tick({}, x, y, 3, "all-rows-swap-c+1");
        tick({}, x, y, 3, "all-rows-swap-c+2");
    }
    check(staleMiss == 3 && ownerFlip == 4 && samePc == 2 && sameIndex == 1 &&
        parallelSameParity == 1 && continuous == 6 && resetCancelled == 1 &&
        rowCoverage == 0xffff && owner0Coverage == 0xffff && owner1Coverage == 0xffff,
        "banked indirect coverage incomplete");
    check(!injectStaleHit, "requested stale-bank negative control did not fire");
    std::cout << "GSIM banked indirect: PASS cycles=" << cycles << " queries=" << queries
        << " hits=" << hits << " misses=" << misses << " staleMiss=" << staleMiss
        << " ownerFlip=" << ownerFlip << " samePc=" << samePc << " sameIndex=" << sameIndex
        << " parallelSameParity=" << parallelSameParity << " continuous=" << continuous
        << " resetCancelled=" << resetCancelled << " rows=" << rowCoverage
        << " owner0Rows=" << owner0Coverage << " owner1Rows=" << owner1Coverage << '\n';
}

int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SPredictionTrainingGsim d;
    std::mt19937_64 rng(0x93156be1);
    std::array<unsigned, 32> counters;
    std::array<bool, 16> hit{};
    std::array<uint64_t, 16> tags{}, targets{};
    Packet pending{};
    const unsigned alignment = COMPRESSED ? 2 : 4;
    unsigned trained = 0, indirect = 0, collisions = 0, cancelled = 0, compressed = 0, wrap = 0;
    auto reset = [&] {
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) drive(d, lane, {}, 0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        counters.fill(1); hit.fill(false); pending = {};
    };
    reset();
    for (unsigned cycle = 0; cycle < 40004; ++cycle) {
        if (cycle == 20000) {
            for (const auto& c : pending) cancelled += c.valid;
            reset();
        }
        Packet offered{};
        std::array<uint64_t, TRAIN_WIDTH> query{};
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) {
            auto& c = offered[lane];
            c.pc = cycle < 300 ? 0x80000000ULL : (rng() & ~uint64_t(alignment - 1));
            if (lane && cycle % 3 == 0) c.pc = offered[0].pc;
            if (cycle % 191 == 0) c.pc = UINT64_MAX - (alignment - 1);
            c.valid = cycle < 40000 && (cycle < 300 || cycle == 19999 || rng() % 5 != 0);
            unsigned kind = cycle < 300 ? 0 : rng() % (COMPRESSED ? 7 : 3);
            unsigned length = 4;
            switch (kind) {
                case 0: c.instruction = 0x63; c.branch = true; break; // BEQ
                case 1: c.instruction = 0x00008067; c.indirect = true; break; // JALR
                case 2: c.instruction = 0x13; break; // ADDI
                case 3: c.instruction = 0xc001; c.branch = true; length = 2; break; // C.BEQZ
                case 4: c.instruction = 0xe001; c.branch = true; length = 2; break; // C.BNEZ
                case 5: c.instruction = 0x8082; c.indirect = true; length = 2; break; // C.JR
                case 6: c.instruction = 0x9082; c.indirect = true; length = 2; break; // C.JALR
            }
            c.taken = (cycle < 150 || (rng() & 1)) && c.branch;
            c.next = c.branch && c.taken ? c.pc - 16 : c.pc + length;
            if (c.indirect) c.next = rng() & ~uint64_t(alignment - 1);
            compressed += c.valid && length == 2;
            wrap += c.valid && !c.taken && !c.indirect && c.next < c.pc;
            query[lane] = cycle % 5 == 0 && pending[lane].valid ? pending[lane].pc : c.pc;
            if (cycle % 7 == 0) query[lane] = tags[(c.pc / alignment) % 16];
            drive(d, lane, c, query[lane]);
        }
        d.step();
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) {
            const auto actual = read(d, lane);
            const unsigned index = (query[lane] / alignment) % 32;
            const unsigned targetIndex = (query[lane] / alignment) % 16;
            const bool expectedTaken = counters[index] >= 2;
            const bool expectedHit = hit[targetIndex] && tags[targetIndex] == query[lane];
            const bool observed = actual.taken ^ (inject && cycle == 300 && lane == 0);
            if (observed != expectedTaken || actual.hit != expectedHit ||
                (expectedHit && actual.target != targets[targetIndex])) {
                std::cerr << "cycle=" << cycle << " lane=" << lane << " pc=" << std::hex << query[lane]
                    << std::dec << " expected_taken=" << expectedTaken << " actual_taken=" << observed << '\n';
                throw std::runtime_error("prediction training oracle mismatch");
            }
        }
        // Independent ordered event model: staged packets train exactly one cycle later.
        const Packet applying = DELAYED_TRAINING ? pending : offered;
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) {
            const auto& c = applying[lane];
            if (!c.valid) continue;
            const unsigned index = (c.pc / alignment) % 32;
            if (c.branch) {
                if (c.taken && counters[index] < 3) ++counters[index];
                if (!c.taken && counters[index] > 0) --counters[index];
                ++trained;
                for (unsigned older = 0; older < lane; ++older)
                    collisions += applying[older].valid && applying[older].branch &&
                        (applying[older].pc / alignment) % 32 == index;
            }
            if (c.indirect) {
                const unsigned ti = (c.pc / alignment) % 16;
                hit[ti] = true; tags[ti] = c.pc; targets[ti] = c.next; ++indirect;
            }
        }
        pending = offered;
    }
    check(trained > 10000 && indirect > 10000 && collisions > 1000 && wrap > 20,
        "prediction training coverage too small");
    if (COMPRESSED) check(compressed > 10000, "compressed predictor training untested");
    if (DELAYED_TRAINING) check(cancelled > 0, "pending training reset not tested");
    std::cout << "GSIM prediction training: PASS width=" << TRAIN_WIDTH << " delayed=" << DELAYED_TRAINING
        << " branches=" << trained << " indirect=" << indirect << " collisions=" << collisions
        << " compressed=" << compressed << " wrapped=" << wrap << " resetCancelled=" << cancelled << '\n';
    directedIndirect(d, argc, argv);
    bankedIndirect(d, argc, argv);
    return 0;
} catch (const std::exception& error) { std::cerr << "GSIM prediction training: " << error.what() << '\n'; return 1; } }
