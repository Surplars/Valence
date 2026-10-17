#include "I1PmpTimingFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

struct Entry { uint64_t lower, upper; unsigned config; };
int main(int argc, char **argv) { try {
    SI1PmpTimingFixture d;
    const unsigned bits = DUT_XLEN == 32 ? 32 : 36;
    const uint64_t limit = 1ULL << bits;
    bool wrong = argc > 1 && std::string(argv[1]) == "--wrong-permission";
    std::mt19937_64 rng(0x504d5033324bULL);
#ifdef I1_PMP_REGISTERED
    d.set_io$$capture(1);
#endif
    d.set_reset(1); d.set_io$$writeEntry(0); d.step(); d.step(); d.set_reset(0);
    uint64_t checked = 0;
    uint64_t heldChecks = 0;
    for (unsigned configuration = 0; configuration < 128; ++configuration) {
        std::array<Entry, 8> entries;
        for (unsigned i = 0; i < 8; ++i) {
            uint64_t lower = (rng() % 32) * 4096 + (rng() % 1024) * 4;
            if (i == 0) lower = limit - 8192;
            uint64_t upper = lower + (1ULL << (rng() % 13));
            if (i == 0) upper = limit;
            unsigned cfg = (rng() & 0x87) | (configuration % 5 == 0 ? 0 : 8);
            entries[i] = {lower, upper, cfg};
            d.set_io$$writeEntry(1); d.set_io$$index(i);
            d.set_io$$lower(lower); d.set_io$$upper(upper); d.set_io$$config(cfg); d.step();
        }
        d.set_io$$writeEntry(0);
        for (unsigned n = 0; n < 512; ++n) {
            const auto &e = entries[n % 8];
            uint64_t a = n % 3 == 0 ? e.lower : n % 3 == 1 ? e.upper : rng() % 0x24000;
            a += int(rng() % 17) - 8;
            if (DUT_XLEN == 32) a &= 0xffffffffULL;
            if (DUT_XLEN == 64 && n % 31 == 0) a |= 1ULL << 48;
            unsigned size = n % 16, privilege = n % 3 == 0 ? 3 : n % 3 == 1 ? 1 : 0;
            bool execute = n & 1, write = n & 2;
            const uint64_t length = 1ULL << size;
            bool want = a < limit && size <= 12 && length <= limit - (a < limit ? a : 0);
            if (want) {
                bool found = false;
                for (const auto &entry : entries) {
                    if (!(entry.config & 0x18) || a >= entry.upper || a + length <= entry.lower) continue;
                    const unsigned permission = execute ? 4 : write ? 2 : 1;
                    want = a >= entry.lower && a + length <= entry.upper &&
                        ((privilege == 3 && !(entry.config & 128)) || (entry.config & permission));
                    found = true; break; // Independent lowest numbered overlapping region.
                }
                if (!found) want = privilege == 3;
            }
            d.set_io$$address(a); d.set_io$$size(size); d.set_io$$privilege(privilege);
            d.set_io$$execute(execute); d.set_io$$store(write); d.step();
#ifdef I1_PMP_REGISTERED
            // GSIM exposes values evaluated at the current edge. Observe
            // the new registered relation at the following edge while the
            // independent query remains unchanged.
            d.step();
#endif
            if (wrong && checked == 123) want = !want;
            if (bool(d.get_io$$allow()) != want) {
                std::cerr << "PMP query=" << checked << " address=0x" << std::hex << a
                          << std::dec << " size=" << size << " privilege=" << privilege
                          << " expected=" << want << " actual=" << bool(d.get_io$$allow()) << '\n';
                throw std::runtime_error("independent PMP full-interval/priority oracle");
            }
            ++checked;
#ifdef I1_PMP_REGISTERED
            if (checked % 257 == 1) {
                d.set_io$$capture(0); d.step();
                for (unsigned noise = 0; noise < 3; ++noise) {
                    d.set_io$$address(rng()); d.set_io$$size(rng() & 15);
                    d.set_io$$privilege(rng() & 3); d.set_io$$execute(rng() & 1);
                    d.set_io$$store(rng() & 1); d.step();
                    if (bool(d.get_io$$allow()) != want)
                        throw std::runtime_error("independent PMP captured-query hold/noise oracle");
                    ++heldChecks;
                }
                d.set_io$$address(a); d.set_io$$size(size); d.set_io$$privilege(privilege);
                d.set_io$$execute(execute); d.set_io$$store(write);
                d.set_io$$capture(1); d.step(); d.step();
                if (bool(d.get_io$$allow()) != want)
                    throw std::runtime_error("independent PMP captured-query restore oracle");
            }
#endif
        }
    }
    std::cout << "I1_PMP_TIMING_PASS xlen=" << DUT_XLEN << " independent_queries=" << checked
              << " held_input_noise_checks=" << heldChecks
              << " partial_overlap_unaligned_page_carry_limit_priority=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
