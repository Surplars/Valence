#include "CpuResetReleaseHarness.h"
#include <iostream>
#include <stdexcept>
#include <string>

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string(argv[1]) == "--inject";
    unsigned cases = 0;
    for (unsigned period : {4U, 6U, 10U, 14U}) for (unsigned phase = 0; phase < period; ++phase) {
        SCpuResetReleaseHarness d;
        bool old = false;
        unsigned edges = 0;
        for (unsigned tick = 0; tick < 1000; ++tick) {
            const bool cold = tick < 50 || (tick >= 200 + phase && tick < 213 + phase) ||
                (tick >= 330 + phase && tick < 340 + phase) || (tick >= 700 + phase && tick < 710 + phase);
            const bool clock = !(tick >= 240 && tick < 380) && (tick + phase) % period >= period / 2;
            d.set_rawClock(old); d.set_coldReset(cold); d.step();
            if (cold) edges = 0;
            auto check = [&] {
                const bool expected = (cold || edges < 3) ^ inject;
                if (d.get_conventional() != expected || d.get_distributed() != expected)
                    throw std::runtime_error("independent three-edge cold-reset release oracle");
            };
            check();
            if (!old && clock && !cold) ++edges;
            d.set_rawClock(clock); d.step(); check();
            old = clock;
        }
        ++cases;
    }
    std::cout << "CPU_RESET_RELEASE_PASS cases=" << cases
              << " async_assert_three_edges_clock_halt_reassert=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
