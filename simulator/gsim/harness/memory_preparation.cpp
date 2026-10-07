#include "MemoryPreparationSelectorGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef ROB_ENTRIES
#define ROB_ENTRIES 16
#endif

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    constexpr unsigned n = ROB_ENTRIES;
    constexpr uint64_t mask = (uint64_t(1) << n) - 1;
    SMemoryPreparationSelectorGsim d;
    d.set_reset(0);
    uint64_t checked = 0, excludedFirst = 0, excludedOnly = 0, wrapped = 0;
    auto check = [&](uint64_t eligible, unsigned head, bool issued, unsigned owner) {
        eligible &= mask;
        // Independent procedural circular-age scan, not the DUT's priority-mask
        // construction. Recompute the final winner AFTER removing the owner.
        auto oldest = [&](uint64_t slots) {
            for (unsigned age = 0; age < n; ++age) {
                unsigned i = (head + age) % n;
                if (slots & (uint64_t(1) << i)) return int(i);
            }
            return -1;
        };
        int first = oldest(eligible);
        int second = oldest(first < 0 ? 0 : eligible & ~(uint64_t(1) << first));
        int selected = oldest(eligible & ~(issued ? uint64_t(1) << owner : 0));
        bool useSecond = issued && first == int(owner);
        d.set_io$$eligible(eligible); d.set_io$$head(head);
        d.set_io$$issued(issued); d.set_io$$issuedIndex(owner); d.step();
        bool valid = selected >= 0;
        if (inject && checked == 100) valid = !valid;
        if (bool(d.get_io$$firstValid()) != (first >= 0) ||
            (first >= 0 && d.get_io$$firstIndex() != unsigned(first)) ||
            bool(d.get_io$$secondValid()) != (second >= 0) ||
            (second >= 0 && d.get_io$$secondIndex() != unsigned(second)) ||
            bool(d.get_io$$useSecond()) != useSecond ||
            bool(d.get_io$$selectedValid()) != valid ||
            (selected >= 0 && d.get_io$$selectedIndex() != unsigned(selected)))
            throw std::runtime_error("memory preparation oracle mismatch");
        ++checked; excludedFirst += useSecond; excludedOnly += useSecond && second < 0;
        wrapped += selected >= 0 && unsigned(selected) < head;
    };
    for (unsigned head = 0; head < n; ++head) {
        check(0, head, false, 0); check(mask, head, true, head);
        for (unsigned a = 0; a < n; ++a) {
            check(uint64_t(1) << a, head, false, a);
            check(uint64_t(1) << a, head, true, a);
            for (unsigned b = 0; b < n; ++b) {
                uint64_t slots = (uint64_t(1) << a) | (uint64_t(1) << b);
                check(slots, head, false, b);
                for (unsigned owner : std::array<unsigned, 4>{a, b, head, (a + 1) % n})
                    check(slots, head, true, owner);
            }
        }
    }
    std::mt19937_64 rng(0x20261002eaULL);
    for (unsigned i = 0; i < 20000; ++i) {
        uint64_t slots = rng(); unsigned head = rng() % n, owner = rng() % n;
        bool issued = rng() & 1;
        check(slots, head, issued, owner);
    }
    if (!excludedFirst || !excludedOnly || !wrapped)
        throw std::runtime_error("memory preparation coverage incomplete");
    std::cout << "GSIM memory preparation: PASS rob=" << n << " vectors=" << checked
              << " excluded_first=" << excludedFirst << " excluded_only=" << excludedOnly
              << " wrapped=" << wrapped << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
