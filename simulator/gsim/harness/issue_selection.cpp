#include "IssueSelectionGsim.h"
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
    SIssueSelectionGsim d;
    d.set_reset(0);
    uint64_t checked = 0, wrapped = 0, dual = 0;
    auto check = [&](uint64_t slots, unsigned head) {
        slots &= mask;
        int first = -1, second = -1;
        // Independent procedural scan, not the RTL's head-partition priority encoder.
        for (unsigned age = 0; age < n; ++age) {
            unsigned i = (head + age) % n;
            if (!(slots & (uint64_t(1) << i))) continue;
            if (first < 0) first = int(i);
            else { second = int(i); break; }
        }
        auto oneHot = [](int i) { return i < 0 ? uint64_t(0) : uint64_t(1) << i; };
        auto payload = [](int i) { return i < 0 ? uint64_t(0) :
            0xd63af091c472b805ULL ^ (uint64_t(i + 1) * 0x100010001ULL); };
        d.set_io$$eligible(slots); d.set_io$$head(head); d.step();
        uint64_t firstPayload = payload(first);
        if (inject && checked == 100) firstPayload ^= 1;
        if (d.get_io$$first() != oneHot(first) || d.get_io$$second() != oneHot(second) ||
            bool(d.get_io$$firstValid()) != (first >= 0) || bool(d.get_io$$secondValid()) != (second >= 0) ||
            (first >= 0 && d.get_io$$firstIndex() != unsigned(first)) ||
            (second >= 0 && d.get_io$$secondIndex() != unsigned(second)) ||
            d.get_io$$firstPayload() != firstPayload || d.get_io$$secondPayload() != payload(second))
            throw std::runtime_error("issue selection payload oracle mismatch");
        ++checked; wrapped += first >= 0 && unsigned(first) < head; dual += second >= 0;
    };
    for (unsigned head = 0; head < n; ++head) {
        check(0, head); check(mask, head);
        for (unsigned a = 0; a < n; ++a) {
            check(uint64_t(1) << a, head);
            check(mask ^ (uint64_t(1) << a), head);
            for (unsigned b = 0; b < n; ++b) {
                check((uint64_t(1) << a) | (uint64_t(1) << b), head);
                check(mask & ~(uint64_t(1) << a) & ~(uint64_t(1) << b), head);
            }
        }
    }
    std::mt19937_64 rng(0x20261002c15ULL);
    for (unsigned i = 0; i < 20000; ++i) {
        uint64_t slots = rng(); unsigned head = rng() % n;
        check(slots, head);
    }
    if (!wrapped || !dual) throw std::runtime_error("issue selection coverage incomplete");
    std::cout << "GSIM issue selection payload: PASS rob=" << n << " vectors=" << checked
              << " wrapped=" << wrapped << " dual=" << dual << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
