#include "CursorNeighborGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SCursorNeighborGsim d;
    d.set_reset(0);
    uint64_t count = 0;
    constexpr uint64_t mask = (uint64_t{1} << 43) - 1;
    auto one = [&](uint64_t value) {
        d.set_io$$value(value); d.step();
        uint64_t plus = value + 1;
        if (inject && count == 3) plus ^= 1;
        if (d.get_io$$plus64() != plus || d.get_io$$minus64() != value - 1 ||
            d.get_io$$plus43() != (plus & mask) || d.get_io$$minus43() != ((value - 1) & mask))
            throw std::runtime_error("cursor neighbor independent oracle mismatch");
        ++count;
    };
    one(0); one(1); one(UINT64_MAX); one(UINT64_MAX - 1);
    for (unsigned bit = 1; bit < 64; ++bit)
        for (int delta = -3; delta <= 3; ++delta) one((uint64_t{1} << bit) + uint64_t(delta));
    std::mt19937_64 random(0x20261005ccULL);
    for (unsigned i = 0; i < 10000; ++i) one(random());
    std::cout << "CURSOR_NEIGHBOR_PASS vectors=" << count << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
