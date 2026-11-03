#include "I1DivideStepFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>

#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif

int main(int argc, char **) { try {
    SI1DivideStepFixture dut;
    std::mt19937_64 random(0x1d17e20261103ULL);
    constexpr unsigned n = DUT_XLEN;
    const uint64_t mask = n == 64 ? UINT64_MAX : UINT32_MAX;
    const std::array<uint64_t, 6> edges{0, 1, 2, mask, mask - 1, uint64_t(1) << (n - 1)};
    unsigned cases = 0;
    auto check = [&](bool high, uint64_t low, uint64_t divisor) {
        low &= mask; divisor &= mask;
        const __uint128_t window = (__uint128_t(high) << n) | low;
        const bool take = window >= divisor;
        __uint128_t expected = take ? window - divisor : window;
        if (argc > 1 && cases == 3) expected ^= 1;
        dut.set_io$$high(high); dut.set_io$$low(low); dut.set_io$$divisor(divisor);
        dut.step();
        const __uint128_t actual = (__uint128_t(dut.get_io$$remainderHigh()) << n) |
            dut.get_io$$remainderLow();
        if (bool(dut.get_io$$quotientBit()) != take || actual != expected)
            throw std::runtime_error("independent wide divide-step oracle mismatch");
        ++cases;
    };
    for (auto high : {false, true}) for (auto low : edges) for (auto divisor : edges)
        check(high, low, divisor);
    for (unsigned i = 0; i < 12000; ++i) check(random() & 1, random(), random());
    std::cout << "I1_DIVIDE_STEP_PASS xlen=" << n << " cases=" << cases
              << " complete_width_borrow_zero_divisor=PASS\n";
    return 0;
} catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; } }
