#include "SynchronousRegisterFile.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>

int main() { try {
    SSynchronousRegisterFile d;
    d.set_reset(1); d.set_io$$writeEnable(0); d.set_io$$readEnable(0); d.step(); d.step();
    d.set_reset(0);
    std::array<uint64_t, 32> registers{};
    std::optional<std::array<uint64_t, 2>> expected;
    std::mt19937_64 rng(0x1f00113);
    unsigned collisions = 0, stalls = 0, zeroWrites = 0;
    for (unsigned step = 0; step < 12000; ++step) {
        bool read = rng() % 3 != 0, write = rng() % 3 != 0;
        unsigned a = rng() % 32, b = rng() % 32, rd = step % 5 ? rng() % 32 : a;
        uint64_t value = rng();
        d.set_io$$readEnable(read); d.set_io$$writeEnable(write);
        d.set_io$$rs1(a); d.set_io$$rs2(b); d.set_io$$rd(rd); d.set_io$$writeData(value);
        d.step();
        if (expected && (d.get_io$$data1() != (*expected)[0] || d.get_io$$data2() != (*expected)[1]))
            throw std::runtime_error("independent synchronous RF oracle mismatch");
        if (write && rd) registers[rd] = value;
        if (read) expected = std::array<uint64_t, 2>{registers[a], registers[b]};
        collisions += read && write && rd && (a == rd || b == rd);
        stalls += !read; zeroWrites += write && !rd;
        if (step == 6000) {
            d.set_reset(1); d.set_io$$readEnable(0); d.set_io$$writeEnable(0); d.step(); d.step();
            registers.fill(0); expected.reset(); d.set_reset(0);
        }
    }
    if (!collisions || !stalls || !zeroWrites) throw std::runtime_error("RF coverage incomplete");
    std::cout << "FIVE_STAGE_RF_PASS vectors=12000 collisions=" << collisions << " stalls=" << stalls
        << " x0_writes=" << zeroWrites << " warm_reset=1\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
