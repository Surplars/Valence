#include "SpeculativeRamRangeGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

using Wide = unsigned __int128;
struct Window { Wide base, bytes; };
static constexpr Wide top = Wide(1) << 64;
// Independent mathematical oracle: inclusive start, exclusive 128-bit end, no wrap.
static constexpr std::array<Window, 12> windows = {{
    {0x80200000, Wide(512) << 20}, {0x80200000, Wide(1) << 20},
    {0x1000, 0x100}, {0x1008, 24}, {0x1000, 8}, {0, 0},
    {3, 19}, {0x1000, 3}, {top - 4096, 4096}, {0, top}, {0, 8},
    {0x100000000, Wide(3) << 20}
}};
int main(int argc, char **argv) {
    try {
        SSpeculativeRamRangeGsim dut;
        dut.set_reset(0);
        const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
        uint64_t checks = 0;
        auto check = [&](uint64_t address, unsigned size) {
            dut.set_io$$address(address);
            dut.set_io$$size(size);
            dut.step();
            unsigned expected = 0;
            for (unsigned i = 0; i < windows.size(); ++i) {
                const auto &w = windows[i];
                const Wide end = Wide(address) + (Wide(1) << size);
                if (w.bytes && Wide(address) >= w.base && end <= w.base + w.bytes)
                    expected |= 1U << i;
            }
            unsigned actual = dut.get_io$$contained();
            if (inject && checks == 0) actual ^= 1;
            if (actual != expected) {
                std::cerr << "range oracle mismatch address=0x" << std::hex << address
                          << " size=" << size << " expected=" << expected << " actual=" << actual << "\n";
                throw std::runtime_error("range oracle mismatch");
            }
            ++checks;
        };
        for (const auto &w : windows) {
            const std::array<Wide, 6> centers = {
                w.base, w.base + w.bytes, w.base + w.bytes / 2,
                w.base + 8, w.base + (Wide(1) << 21), top
            };
            for (Wide center : centers)
                for (int delta = -128; delta <= 128; ++delta)
                    for (unsigned size = 0; size < 4; ++size)
                        check(uint64_t(center) + uint64_t(delta), size);
        }
        std::mt19937_64 rng(0x50dd20260930ULL);
        for (unsigned i = 0; i < 100000; ++i) {
            check(rng(), i & 3);
            for (const auto &w : windows)
                if (w.bytes) check(uint64_t(w.base + Wide(rng()) % w.bytes), i & 3);
        }
        std::cout << "GSIM range oracle: PASS " << checks
                  << " vectors x 12 windows; DDR/URAM/boundary/unaligned/overflow\n";
    } catch (const std::exception &e) {
        std::cerr << e.what() << "\n";
        return 1;
    }
}
