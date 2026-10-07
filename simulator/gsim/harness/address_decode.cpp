#include "TwoBankAddressDecoder.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef ADDRESS_WIDTH
#define ADDRESS_WIDTH 64
#endif
#ifndef DECODER_BASE
#define DECODER_BASE 0x80010000ULL
#endif
#ifndef BANK_BYTES
#define BANK_BYTES 2048
#endif
#ifndef SECOND_BYTES
#define SECOND_BYTES 2048
#endif

int main(int argc, char **argv) {
    try {
        const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
        using Wide = unsigned __int128;
        constexpr uint64_t base = DECODER_BASE;
        constexpr uint64_t first = BANK_BYTES, second = SECOND_BYTES;
#if ADDRESS_WIDTH == 64
        constexpr uint64_t addressMask = UINT64_MAX;
#else
        constexpr uint64_t addressMask = (uint64_t{1} << ADDRESS_WIDTH) - 1;
#endif
        STwoBankAddressDecoder d;
        unsigned vectors = 0;
        std::array<unsigned, 4> counts{};
        auto check = [&](uint64_t raw) {
            const uint64_t address = raw & addressMask;
            // Ordinary 128-bit mathematical intervals, no prefix/mask algorithm.
            unsigned expected = (Wide(address) >= Wide(base) && Wide(address) < Wide(base) + first ? 1 : 0) |
                (Wide(address) >= Wide(base) + first && Wide(address) < Wide(base) + first + second ? 2 : 0);
            ++counts[expected];
            if (inject && vectors == 100) expected ^= 1;
            d.set_io$$address(address);
            d.step();
            if (unsigned(d.get_io$$hitMask()) != expected)
                throw std::runtime_error("static address decode oracle mismatch");
            ++vectors;
        };
        auto edge = [&](uint64_t center) {
            for (int delta = -32; delta <= 32; ++delta) check(center + uint64_t(delta));
        };
        edge(0); edge(base); edge(base + first); edge(base + first + second); edge(addressMask);
        for (unsigned bit = 0; bit < ADDRESS_WIDTH; ++bit) {
            const uint64_t power = uint64_t{1} << bit;
            edge(power); edge(base + power); edge(base + first + power);
        }
        std::mt19937_64 random(0x94fa6c1dULL);
        for (unsigned i = 0; i < 50000; ++i) {
            uint64_t value = random();
            switch (i % 5) {
                case 0: break;
                case 1: value = base + value % first; break;
                case 2: value = base + first + value % second; break;
                case 3: value = base - 128 + value % (first + second + 256); break;
                case 4: value = (value & 0xffffffffULL) | 0x100000000ULL; break;
            }
            check(value);
        }
        if (counts[0] < 1000 || counts[1] < 1000 || counts[2] < 1000 || counts[3])
            throw std::runtime_error("static address decode coverage insufficient");
        std::cout << "GSIM static address decode: PASS width=" << ADDRESS_WIDTH
                  << " base=" << std::hex << base << std::dec << " banks=" << first << ',' << second
                  << " vectors=" << vectors << " unmapped=" << counts[0]
                  << " hit0=" << counts[1] << " hit1=" << counts[2] << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
