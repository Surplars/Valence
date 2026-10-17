#include "FiveStageMulDiv.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>

#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
static void require(bool yes, const char *message) { if (!yes) throw std::runtime_error(message); }
static uint64_t narrow(uint64_t x) { return DUT_XLEN == 32 ? uint32_t(x) : x; }
static __int128 signedValue(uint64_t x, unsigned bits) {
    return (x >> (bits - 1) & 1) ? __int128(x) - (__int128(1) << bits) : __int128(x);
}
static uint64_t expected(uint64_t a, uint64_t b, unsigned op, bool word) {
    unsigned n = word ? 32 : DUT_XLEN;
    uint64_t mask = n == 64 ? UINT64_MAX : UINT32_MAX;
    a &= mask; b &= mask;
    __int128 sa = signedValue(a, n), sb = signedValue(b, n);
    uint64_t value;
    if (op < 4) {
        // Full-width procedural arithmetic is independent of the DUT's limb/carry/sign network.
        __int128 aa = (op == 1 || op == 2) ? sa : __int128(a);
        __int128 bb = op == 1 ? sb : __int128(b);
        unsigned __int128 product = (op == 0 || op == 3) ?
            static_cast<unsigned __int128>(a) * b : static_cast<unsigned __int128>(aa * bb);
        value = uint64_t(op ? product >> n : product);
    } else if (!(op & 1)) {
        if (!b) value = (op == 4) ? mask : a;
        else value = uint64_t(op == 4 ? sa / sb : sa % sb);
    } else value = !b ? (op == 5 ? mask : a) : (op == 5 ? a / b : a % b);
    value &= mask;
    if (word && (value >> 31 & 1)) value |= UINT64_MAX << 32;
    return narrow(value);
}

int main(int argc, char **) { try {
    SFiveStageMulDiv d;
    std::mt19937_64 random(0x4931d5f17ULL);
    const std::array<uint64_t, 10> edges{0, 1, 2, UINT64_MAX, UINT64_MAX - 1,
        0x8000000000000000ULL, 0x7fffffffffffffffULL, 0x80000000, 0x7fffffff, 0x100000001ULL};
    d.set_reset(1); d.set_io$$kill(0); d.set_io$$request$$valid(0); d.set_io$$response$$ready(0);
    d.step(); d.step(); d.set_reset(0);
    uint64_t transactions = 0, holdCycles = 0, killed = 0, cycles = 0;
    auto transact = [&](uint64_t a, uint64_t b, unsigned op, bool word, bool cancel, bool lateCancel = false) {
        uint64_t answer = expected(a, b, op, word);
        if (argc > 1 && transactions == 3) answer ^= 1;
        bool sent = false, done = false;
        unsigned killAt = 1 + random() % 2;
        std::optional<uint64_t> held;
        for (unsigned cycle = 0; cycle < 180 && !done; ++cycle) {
            bool kill = lateCancel ? held.has_value() : cancel && sent && cycle == killAt;
            bool ready = !lateCancel && cycle > 8 && (random() & 3) == 0;
            d.set_io$$kill(kill); d.set_io$$request$$valid(!sent);
            d.set_io$$request$$bits$$left(narrow(a)); d.set_io$$request$$bits$$right(narrow(b));
            d.set_io$$request$$bits$$funct3(op); d.set_io$$request$$bits$$word(word);
            d.set_io$$response$$ready(ready); d.step(); ++cycles;
            if (kill) {
                require(!d.get_io$$response$$valid(), "killed MDU exposed a result");
                if (lateCancel) require(d.get_io$$completed(),
                    "late kill fed back into registered MDU completion status");
                ++killed; done = true;
            } else {
                require(bool(d.get_io$$completed()) == bool(d.get_io$$response$$valid()),
                    "MDU local completion differs from live response");
                if (!sent && d.get_io$$request$$ready()) sent = true;
                if (d.get_io$$response$$valid()) {
                    require(sent, "MDU produced an unowned response");
                    auto value = d.get_io$$response$$bits();
                    require(value == answer, "independent MDU oracle mismatch");
                    if (held) require(*held == value, "MDU response changed under backpressure");
                    if (ready) done = true; else { held = value; ++holdCycles; }
                }
            }
        }
        require(sent && done, "MDU did not complete within its bounded latency");
        // Drain the edge that accepted/cancelled the result, then start with no offered request.
        d.set_io$$kill(0); d.set_io$$request$$valid(0); d.set_io$$response$$ready(0); d.step(); ++cycles;
        require(!d.get_io$$completed() && !d.get_io$$response$$valid(),
            "MDU duplicate response after completion/cancel");
        ++transactions;
    };
    for (auto a : edges) for (auto b : edges) for (unsigned op = 0; op < 8; ++op)
        transact(a, b, op, false, false);
    if (DUT_XLEN == 64) for (auto a : edges) for (auto b : edges) for (unsigned op : {0U, 4U, 5U, 6U, 7U})
        transact(a, b, op, true, false);
    for (unsigned n = 0; n < 1000; ++n) {
        unsigned op = random() % 8;
        bool word = DUT_XLEN == 64 && (op == 0 || op >= 4) && (random() & 1);
        transact(random(), random(), op, word, n % 19 == 0);
    }
    for (unsigned op : {0U, 1U, 2U, 3U, 4U, 5U, 6U, 7U})
        transact(UINT64_MAX, 7, op, false, false, true);
    d.set_reset(1); d.step(); d.set_reset(0); d.step();
    require(!d.get_io$$response$$valid(), "warm reset left an MDU owner");
    require(holdCycles && killed, "missing MDU hold/kill coverage");
    std::cout << "FIVE_STAGE_MDU_PASS xlen=" << DUT_XLEN << " transactions=" << transactions
        << " hold_cycles=" << holdCycles << " kills=" << killed << " cycles=" << cycles
        << " signed_unsigned_high_word_divzero_overflow_backpressure_kill_warm_reset=PASS late_completion_kills=8\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
