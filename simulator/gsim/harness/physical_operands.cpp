#include "PhysicalOperandsGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef ROB_ENTRIES
#define ROB_ENTRIES 16
#endif
#ifndef PHYSICAL_REGS
#define PHYSICAL_REGS 48
#endif
#ifndef SHARED_DECODE_CLIENTS
#define SHARED_DECODE_CLIENTS 1
#endif
#if SHARED_DECODE_CLIENTS != 1 && SHARED_DECODE_CLIENTS != 3
#error "SHARED_DECODE_CLIENTS must be 1 or 3"
#endif

static void sources(SPhysicalOperandsGsim &d, unsigned i, unsigned a, unsigned b) {
#define SRC(N) case N: d.set_io$$source1$$r##N(a); d.set_io$$source2$$r##N(b); return
    switch (i) {
        SRC(0); SRC(1); SRC(2); SRC(3); SRC(4); SRC(5); SRC(6); SRC(7);
        SRC(8); SRC(9); SRC(10); SRC(11); SRC(12); SRC(13); SRC(14); SRC(15);
#if ROB_ENTRIES > 16
        SRC(16); SRC(17); SRC(18); SRC(19); SRC(20); SRC(21); SRC(22); SRC(23);
        SRC(24); SRC(25); SRC(26); SRC(27); SRC(28); SRC(29); SRC(30); SRC(31);
#endif
    }
#undef SRC
    throw std::runtime_error("source port");
}
static void value(SPhysicalOperandsGsim &d, unsigned i, uint64_t v) {
#define VAL(N) case N: d.set_io$$values$$r##N(v); return
    switch (i) {
        VAL(0); VAL(1); VAL(2); VAL(3); VAL(4); VAL(5); VAL(6); VAL(7);
        VAL(8); VAL(9); VAL(10); VAL(11); VAL(12); VAL(13); VAL(14); VAL(15);
        VAL(16); VAL(17); VAL(18); VAL(19); VAL(20); VAL(21); VAL(22); VAL(23);
        VAL(24); VAL(25); VAL(26); VAL(27); VAL(28); VAL(29); VAL(30); VAL(31);
        VAL(32); VAL(33); VAL(34); VAL(35); VAL(36); VAL(37); VAL(38); VAL(39);
        VAL(40); VAL(41); VAL(42); VAL(43); VAL(44); VAL(45); VAL(46); VAL(47);
#if PHYSICAL_REGS > 48
        VAL(48); VAL(49); VAL(50); VAL(51); VAL(52); VAL(53); VAL(54); VAL(55);
        VAL(56); VAL(57); VAL(58); VAL(59); VAL(60); VAL(61); VAL(62); VAL(63);
#endif
    }
#undef VAL
    throw std::runtime_error("value port");
}
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    const bool injectShared = argc == 2 && std::string_view(argv[1]) == "--inject-shared-mismatch";
    if (injectShared && SHARED_DECODE_CLIENTS != 3)
        throw std::runtime_error("shared negative control requires three-client wrapper");
    SPhysicalOperandsGsim d;
    std::mt19937_64 rng(0x20261002a9ULL);
    std::array<unsigned, 32> a{}, b{};
    std::array<uint64_t, 64> words{};
    uint64_t checked = 0, empty = 0, dual = 0, invalidUnselected = 0;
#if SHARED_DECODE_CLIENTS == 3
    uint64_t sharedVectors = 0;
#endif
    for (unsigned i = 0; i < 32; ++i) { a[i] = i % PHYSICAL_REGS; b[i] = (i * 7 + 3) % PHYSICAL_REGS; }
    for (auto &word : words) word = rng();
    auto one = [&](uint32_t owner0, uint32_t owner1, std::array<uint32_t, 4> otherOwners = {}) {
        d.set_io$$owner0(owner0); d.set_io$$owner1(owner1); d.set_reset(0);
#if SHARED_DECODE_CLIENTS == 3
        d.set_io$$otherOwners$$r0(otherOwners[0]); d.set_io$$otherOwners$$r1(otherOwners[1]);
        d.set_io$$otherOwners$$r2(otherOwners[2]); d.set_io$$otherOwners$$r3(otherOwners[3]);
#else
        (void)otherOwners; // Archived/default models have no additional getters or setters.
#endif
        for (unsigned i = 0; i < ROB_ENTRIES; ++i) sources(d, i, a[i], b[i]);
        for (unsigned i = 0; i < PHYSICAL_REGS; ++i) value(d, i, words[i]);
        d.step();
        // Independent procedural owner lookup and ordinary software array read,
        // not the DUT's physical-mask construction or masked OR equations.
        auto expected = [&](uint32_t owner, const auto &ids) -> uint64_t {
            for (unsigned slot = 0; slot < ROB_ENTRIES; ++slot)
                if (owner & (uint32_t(1) << slot)) {
                    if (ids[slot] >= PHYSICAL_REGS) throw std::runtime_error("invalid selected fixture");
                    return words[ids[slot]];
                }
            return 0;
        };
        uint64_t left0 = d.get_io$$left0();
        if (inject && checked == 100) left0 ^= 1;
        if (left0 != expected(owner0, a) || d.get_io$$right0() != expected(owner0, b) ||
            d.get_io$$left1() != expected(owner1, a) || d.get_io$$right1() != expected(owner1, b))
            throw std::runtime_error("physical operand oracle mismatch");
#if SHARED_DECODE_CLIENTS == 3
        std::array<uint64_t, 8> more{
            d.get_io$$others$$r0(), d.get_io$$others$$r1(),
            d.get_io$$others$$r2(), d.get_io$$others$$r3(),
            d.get_io$$others$$r4(), d.get_io$$others$$r5(),
            d.get_io$$others$$r6(), d.get_io$$others$$r7()};
        if (injectShared && checked == 0) more[0] ^= 1;
        // Same independent procedural owner lookup/array oracle, applied to
        // every client. No DUT one-hot decode or masked-OR equations are reused.
        for (unsigned owner = 0; owner < 4; ++owner)
            if (more[2 * owner] != expected(otherOwners[owner], a) ||
                more[2 * owner + 1] != expected(otherOwners[owner], b))
                throw std::runtime_error("shared physical operand oracle mismatch");
#endif
        ++checked; empty += !owner0 || !owner1; dual += bool(owner0 && owner1);
    };
    one(0, 0);
    for (unsigned slot = 0; slot < ROB_ENTRIES; ++slot)
        for (unsigned left = 0; left < PHYSICAL_REGS; ++left)
            for (unsigned right = 0; right < PHYSICAL_REGS; ++right) {
                a[slot] = left; b[slot] = right;
                one(uint32_t(1) << slot, uint32_t(1) << ((slot + 1) % ROB_ENTRIES));
            }
    for (unsigned n = 0; n < 20000; ++n) {
        for (unsigned i = 0; i < 32; ++i) { a[i] = rng() % PHYSICAL_REGS; b[i] = rng() % PHYSICAL_REGS; }
        for (auto &word : words) word = rng();
        const uint32_t owner0 = n % 7 ? uint32_t(1) << (rng() % ROB_ENTRIES) : 0;
        const uint32_t owner1 = n % 11 ? uint32_t(1) << (rng() % ROB_ENTRIES) : 0;
        one(owner0, owner1);
    }
#if SHARED_DECODE_CLIENTS == 3
    // All 64 independent active/empty combinations of six different owners
    // prove that three early reads coexist, not a shared late-grant/value mux.
    for (unsigned offset = 0; offset < ROB_ENTRIES; ++offset)
        for (unsigned pattern = 0; pattern < 64; ++pattern) {
            for (unsigned slot = 0; slot < ROB_ENTRIES; ++slot) {
                a[slot] = (slot * 3 + offset) % PHYSICAL_REGS;
                b[slot] = (slot * 5 + offset + 1) % PHYSICAL_REGS;
            }
            for (auto &word : words) word = rng();
            std::array<uint32_t, 6> owners{};
            for (unsigned lane = 0; lane < 6; ++lane)
                if (pattern & (1u << lane))
                    owners[lane] = uint32_t(1) << ((offset + lane) % ROB_ENTRIES);
            one(owners[0], owners[1], {owners[2], owners[3], owners[4], owners[5]});
            ++sharedVectors;
        }
#endif
    // A non-power-of-two PRF must not dynamically index stale unselected IDs.
    // Empty owners and valid selected owners remain defined with all others 0xff.
    for (unsigned slot = 0; slot < ROB_ENTRIES; ++slot) {
        a.fill(255); b.fill(255); a[slot] = slot % PHYSICAL_REGS; b[slot] = PHYSICAL_REGS - 1;
        one(uint32_t(1) << slot, 0); one(0, 0); invalidUnselected += 2;
    }
    std::cout << "GSIM physical operand payload: PASS rob=" << ROB_ENTRIES << " physical=" << PHYSICAL_REGS
        << " vectors=" << checked << " empty=" << empty << " dual=" << dual
        << " invalidUnselected=" << invalidUnselected
#if SHARED_DECODE_CLIENTS == 3
        << " sharedClients=3 independentOwnerVectors=" << sharedVectors
#endif
        << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
