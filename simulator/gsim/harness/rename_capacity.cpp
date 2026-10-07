#include "RenameCapacityGsim.h"
#include <bit>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>

static unsigned expected(unsigned available, unsigned fresh, unsigned width) {
    unsigned result = 0;
    for (unsigned lane = 0; lane < width; ++lane)
        if (available >= unsigned(std::popcount(fresh & ((1U << (lane + 1)) - 1))))
            result |= 1U << lane;
    return result;
}

int main(int argc, char **) {
    try {
        SRenameCapacityGsim dut;
        std::mt19937_64 random(7813);
        unsigned checked = 0, empty = 0, partial = 0;
        for (unsigned trial = 0; trial < 2048; ++trial) {
            uint64_t low = 0;
            uint32_t high = 0;
            if (trial % 4) {
                for (unsigned n = 0; n < trial % 9; ++n) {
                    const unsigned bit = random() % 96;
                    if (bit < 64) low |= UINT64_C(1) << bit;
                    else high |= uint32_t(1) << (bit - 64);
                }
            }
            for (unsigned fresh = 0; fresh < 64; ++fresh) {
                dut.set_io$$freeLow(low); dut.set_io$$freeHigh(high); dut.set_io$$fresh(fresh);
                dut.set_reset(0); dut.step();
                unsigned two = dut.get_io$$enough2();
                if (argc > 1) two ^= 1;
                const unsigned a2 = std::popcount(low & UINT64_C(0xffffffffffff));
                const unsigned a4 = std::popcount(low);
                const unsigned a6 = a4 + std::popcount(high);
                if (two != expected(a2, fresh, 2) ||
                    dut.get_io$$enough4() != expected(a4, fresh, 4) ||
                    dut.get_io$$enough6() != expected(a6, fresh, 6))
                    throw std::runtime_error("rename capacity mismatch");
                ++checked; empty += !a2; partial += two == 1;
            }
        }
        if (!empty || !partial) throw std::runtime_error("rename capacity coverage");
        std::cout << "GSIM rename capacity: PASS vectors=" << checked
                  << " widths=2/4/6 registers=48/64/96 empty=" << empty << " partial=" << partial << '\n';
    } catch (const std::exception &error) {
        std::cerr << "GSIM rename capacity: FAIL " << error.what() << '\n'; return 1;
    }
}
