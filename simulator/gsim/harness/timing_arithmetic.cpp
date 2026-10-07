#include "TimingArithmeticGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    STimingArithmeticGsim dut;
    dut.set_reset(0);
    uint64_t count = 0;
    auto one = [&](uint64_t a, uint64_t b) {
        dut.set_io$$a(a); dut.set_io$$b(b); dut.step();
        uint64_t expected = a + b;
        if (inject && count == 7) expected ^= 1;
        constexpr uint64_t mask = UINT64_MAX >> 1;
        if (dut.get_io$$sum() != expected || bool(dut.get_io$$le()) != (a <= b) ||
            bool(dut.get_io$$le63()) != ((a & mask) <= (b & mask)))
            throw std::runtime_error("timing arithmetic independent oracle mismatch");
        const uint64_t word = a & ((uint64_t{1} << 62) - 1);
        if (dut.get_io$$word0() != word || dut.get_io$$word1() != word + 1 ||
            dut.get_io$$word2() != word + 2 || dut.get_io$$word4() != word + 4 ||
            dut.get_io$$word255() != word + 255 || dut.get_io$$byte255() != (a & 255) + 255)
            throw std::runtime_error("timing arithmetic independent oracle mismatch: extended constant carry");
        ++count;
    };
    const std::array<uint64_t, 12> edges{0, 1, 2, 3, 0xff, 0x100, 0xffff, 0x10000,
        UINT64_MAX >> 1, uint64_t{1} << 63, UINT64_MAX - 1, UINT64_MAX};
    for (auto a : edges) for (auto b : edges) one(a, b);
    for (unsigned bit = 1; bit < 64; ++bit) {
        uint64_t boundary = uint64_t{1} << bit;
        for (uint64_t delta = 0; delta < 3; ++delta) {
            one(boundary - delta, 1); one(UINT64_MAX - boundary + delta, boundary);
            one(boundary, boundary - delta); one(boundary - delta, boundary);
        }
    }
    std::mt19937_64 random(0x20261004abULL);
    for (unsigned i = 0; i < 10000; ++i) one(random(), random());
    std::cout << "TIMING_ARITHMETIC_PASS vectors=" << count << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
