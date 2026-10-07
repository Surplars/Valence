#include "HomeQualificationGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#ifndef HOME_BASE
#define HOME_BASE 0x80200000ULL
#endif
#ifndef HOME_BYTES
#define HOME_BYTES 536870912ULL
#endif
int main(int argc, char **argv) { try {
    SHomeQualificationGsim d;
    std::mt19937_64 rng(0x711220261002ULL);
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    unsigned hits = 0, inside = 0, both = 0;
    constexpr uint64_t base = HOME_BASE, bytes = HOME_BYTES, tagMask = (1ULL << 58) - 1;
    for (unsigned i = 0; i < 120000; ++i) {
        uint64_t address = rng();
        switch (i % 8) {
            case 0: address = base - 1; break;
            case 1: address = base; break;
            case 2: address = base + bytes - 1; break;
            case 3: address = base + bytes; break;
            case 4: address = base + rng() % bytes; break;
            case 5: address = (base + rng() % bytes) ^ (1ULL << 63); break;
            case 6: address = (base + rng() % bytes) ^ (1ULL << 32); break;
        }
        const uint64_t tag = address >> 6;
        const uint64_t first = i % 3 == 0 ? tag : rng() & tagMask;
        const uint64_t second = i % 4 == 0 ? tag : rng() & tagMask;
        const bool firstOwned = rng() & 1, secondOwned = rng() & 1;
        const bool expectedOwned = (firstOwned && first == tag) || (secondOwned && second == tag);
        const bool expectedRange = address >= base && address - base < bytes;
        d.set_io$$address(address); d.set_io$$firstTag(first); d.set_io$$secondTag(second);
        d.set_io$$firstOwned(firstOwned); d.set_io$$secondOwned(secondOwned);
        d.set_reset(0); d.step();
        bool actualOwned = d.get_io$$owned();
        if (inject && i == 7) actualOwned = !actualOwned;
        if (actualOwned != expectedOwned || bool(d.get_io$$inRam()) != expectedRange)
            throw std::runtime_error("home qualification oracle mismatch");
        hits += expectedOwned; inside += expectedRange;
        both += firstOwned && secondOwned && first == tag && second == tag;
    }
    if (!hits || !inside || !both) throw std::runtime_error("home qualification coverage incomplete");
    std::cout << "GSIM home qualification: PASS vectors=120000 base=" << std::hex << base
              << std::dec << " hits=" << hits << " in_range=" << inside << " both=" << both << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
