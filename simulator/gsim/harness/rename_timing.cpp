#include "RenameTimingGsim.h"
#include <array>
#include <bit>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static std::pair<uint64_t, unsigned> candidates(uint64_t low, uint32_t high, unsigned fresh,
                                               unsigned width, unsigned registers) {
    std::array<bool, 96> free{};
    for (unsigned r = 0; r < registers; ++r) free[r] = r < 64 ? (low >> r & 1) : (high >> (r - 64) & 1);
    uint64_t result = 0; unsigned available = 0;
    for (unsigned lane = 0; lane < width; ++lane) {
        unsigned first = registers;
        for (unsigned r = 0; r < registers; ++r) if (free[r]) { first = r; break; }
        if (first != registers) {
            result |= uint64_t(first) << (lane * 8); available |= 1U << lane;
            if (fresh >> lane & 1) free[first] = false;
        }
    }
    return {result, available};
}
int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SRenameTimingGsim d; std::mt19937_64 rng(0x20261001a110cULL);
    const uint64_t mask = (UINT64_C(1) << 48) - 1;
    unsigned checked = 0, conflicts = 0, empty = 0, partial = 0;
    for (unsigned trial = 0; trial < 2048; ++trial) {
        uint64_t low = 0; uint32_t high = 0;
        if (trial % 4) for (unsigned n = 0; n < trial % 12; ++n) {
            unsigned r = rng() % 96;
            if (r < 64) low |= UINT64_C(1) << r; else high |= uint32_t(1) << (r - 64);
        }
        if (trial % 32 == 31) { low = ~UINT64_C(0); high = ~uint32_t(0); }
        for (unsigned fresh = 0; fresh < 64; ++fresh) {
            d.set_io$$freeLow(low); d.set_io$$freeHigh(high); d.set_io$$fresh(fresh);
            uint64_t current = rng() & mask, expected = current;
            unsigned wv = rng() % 8, rv = rng() % 4, wi = 0, ri = 0;
            for (unsigned lane = 0; lane < 3; ++lane) {
                unsigned r = rng() % 48; wi |= r << (lane * 8);
                if (wv >> lane & 1) expected |= UINT64_C(1) << r;
            }
            for (unsigned lane = 0; lane < 2; ++lane) {
                unsigned r = (trial % 8 == 0 && lane == 0) ? wi & 255 : rng() % 48;
                ri |= r << (lane * 8);
                if (rv >> lane & 1) {
                    conflicts += bool(expected >> r & 1) && !bool(current >> r & 1);
                    expected &= ~(UINT64_C(1) << r);
                }
            }
            d.set_io$$current(current); d.set_io$$wakeValid(wv); d.set_io$$wakeIds(wi);
            d.set_io$$reserveValid(rv); d.set_io$$reserveIds(ri); d.set_reset(0); d.step();
            auto a = candidates(low, high, fresh, 2, 48), b = candidates(low, high, fresh, 4, 64);
            auto c = candidates(low, high, fresh, 6, 96);
            uint64_t actual = d.get_io$$next(); if (inject) actual ^= 1;
            if (actual != expected || d.get_io$$candidates2() != a.first || d.get_io$$available2() != a.second ||
                d.get_io$$candidates4() != b.first || d.get_io$$available4() != b.second ||
                d.get_io$$candidates6() != c.first || d.get_io$$available6() != c.second)
                throw std::runtime_error("rename payload/ready oracle mismatch");
            empty += !a.second; partial += a.second == 1; ++checked;
        }
    }
    if (!conflicts || !empty || !partial) throw std::runtime_error("rename timing coverage incomplete");
    std::cout << "GSIM rename payload/ready: PASS vectors=" << checked << " widths=2/4/6 registers=48/64/96"
              << " reserve_wins=" << conflicts << " empty=" << empty << " partial=" << partial << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
