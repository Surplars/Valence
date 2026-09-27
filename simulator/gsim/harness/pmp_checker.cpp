#include "PmpCheckerGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

using Wide = unsigned __int128;
struct Entry { unsigned cfg = 0; uint64_t addr = 0; };
using Entries = std::array<Entry, 16>;
static void check(bool okay, const char *message) {
    if (!okay) throw std::runtime_error(message);
}

// Decode NAPOT by counting trailing ones, independently of the RTL mask formula.
static bool denied(const Entries &entries, uint64_t address, unsigned size, unsigned access, unsigned privilege) {
    const Wide start = address, end = start + (uint64_t(1) << size) - 1;
    for (unsigned i = 0; i < entries.size(); ++i) {
        const auto [cfg, encoded] = entries[i];
        const unsigned mode = (cfg >> 3) & 3;
        Wide low = 0, high = 0;
        if (mode == 0) continue;
        if (mode == 1) {
            low = i ? Wide(entries[i - 1].addr) << 2 : 0;
            const Wide top = Wide(encoded) << 2;
            if (top <= low) continue;
            high = top - 1;
        } else if (mode == 2) {
            low = Wide(encoded) << 2;
            high = low + 3;
        } else {
            unsigned trailing = 0;
            while (trailing < 54 && (encoded & (uint64_t(1) << trailing))) ++trailing;
            const Wide bytes = trailing >= 53 ? Wide(1) << 56 : Wide(8) << trailing;
            low = (Wide(encoded) << 2) & ~(bytes - 1);
            high = low + bytes - 1;
        }
        if (start > high || end < low) continue;
        const bool whole = start >= low && end <= high;
        const bool permission = access == 0 ? cfg & 1 : access == 1 ? cfg & 2 :
                                access == 2 ? cfg & 4 : (cfg & 3) == 3;
        return !whole || ((privilege != 3 || (cfg & 128)) && !permission);
    }
    return privilege != 3;
}

static void one(SPmpCheckerGsim &dut, const Entries &entries, uint64_t address,
                unsigned size, unsigned access, unsigned privilege, bool inject = false) {
    dut.set_io$$cfg0(entries[0].cfg); dut.set_io$$cfg1(entries[1].cfg);
    dut.set_io$$cfg2(entries[2].cfg); dut.set_io$$cfg3(entries[3].cfg);
    dut.set_io$$cfg4(entries[4].cfg); dut.set_io$$cfg5(entries[5].cfg);
    dut.set_io$$cfg6(entries[6].cfg); dut.set_io$$cfg7(entries[7].cfg);
    dut.set_io$$cfg8(entries[8].cfg); dut.set_io$$cfg9(entries[9].cfg);
    dut.set_io$$cfg10(entries[10].cfg); dut.set_io$$cfg11(entries[11].cfg);
    dut.set_io$$cfg12(entries[12].cfg); dut.set_io$$cfg13(entries[13].cfg);
    dut.set_io$$cfg14(entries[14].cfg); dut.set_io$$cfg15(entries[15].cfg);
    dut.set_io$$addr0(entries[0].addr); dut.set_io$$addr1(entries[1].addr);
    dut.set_io$$addr2(entries[2].addr); dut.set_io$$addr3(entries[3].addr);
    dut.set_io$$addr4(entries[4].addr); dut.set_io$$addr5(entries[5].addr);
    dut.set_io$$addr6(entries[6].addr); dut.set_io$$addr7(entries[7].addr);
    dut.set_io$$addr8(entries[8].addr); dut.set_io$$addr9(entries[9].addr);
    dut.set_io$$addr10(entries[10].addr); dut.set_io$$addr11(entries[11].addr);
    dut.set_io$$addr12(entries[12].addr); dut.set_io$$addr13(entries[13].addr);
    dut.set_io$$addr14(entries[14].addr); dut.set_io$$addr15(entries[15].addr);
    dut.set_io$$address(address); dut.set_io$$size(size);
    dut.set_io$$access(access); dut.set_io$$privilege(privilege);
    dut.step();
    bool expected = denied(entries, address, size, access, privilege);
    if (inject) expected = !expected;
    check(bool(dut.get_io$$denied()) == expected, "PMP oracle mismatch");
}

int main(int argc, char **argv) {
    try {
        const bool inject = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
        check(argc == 1 || inject, "usage: pmp_checker [--inject-mismatch]");
        SPmpCheckerGsim dut;
        dut.set_reset(1); dut.step(); dut.set_reset(0);
        Entries entries{};
        one(dut, entries, 0x80000000, 2, 2, 1, inject);
        entries[0] = {0x1d, 0x200003ff}; // 8 KiB ROM, R/X.
        entries[1] = {0x1b, 0x200041ff}; // 4 KiB RAM, R/W.
        one(dut, entries, 0x80000000, 2, 2, 0);
        one(dut, entries, 0x80000000, 2, 1, 0);
        one(dut, entries, 0x80010000, 3, 3, 1);
        one(dut, entries, 0x80010ffc, 3, 0, 1); // Partial RAM overlap wins.
        one(dut, entries, 0x80011000, 3, 0, 1); // No match.
        one(dut, entries, 0x80011000, 3, 0, 3); // M no-match allow.
        entries[0].cfg |= 128;
        one(dut, entries, 0x80000000, 2, 1, 3); // Locked M store denial.
        entries[0] = {0, 0x400};
        entries[1] = {0x0b, 0x800}; // TOR uses OFF predecessor as lower bound.
        one(dut, entries, 0x1000, 3, 0, 1);
        one(dut, entries, 0x1ffc, 3, 0, 1);
        entries[0] = {0x12, 0x400}; // NA4, W-only.
        entries[1] = {0x1d, 0x403}; // Overlapping NAPOT.
        one(dut, entries, 0x1000, 3, 1, 1);
        one(dut, entries, 0x1004, 2, 2, 1);
        entries = {};
        entries[0] = {0x1f, (uint64_t(1) << 54) - 1}; // Entire 56-bit physical range.
        one(dut, entries, (uint64_t(1) << 56) - 8, 3, 0, 1);
        one(dut, entries, uint64_t(1) << 56, 3, 0, 1);
        entries = {};
        entries[15] = {0x1d, 0x200003ff}; // Last entry still grants ROM execute.
        one(dut, entries, 0x80000000, 2, 2, 1);
        entries[14] = {0x1b, 0x200003ff}; // Earlier matching entry denies execute.
        one(dut, entries, 0x80000000, 2, 2, 1);
        std::mt19937_64 rng(0x504d50434845434bULL);
        const unsigned permissions[] = {0, 1, 3, 4, 5, 7};
        for (unsigned i = 0; i < 6000; ++i) {
            Entries random{};
            for (auto &entry : random) {
                unsigned kind = rng() % 4;
                entry.cfg = (kind << 3) | permissions[rng() % 6] | ((rng() & 7) == 0 ? 128 : 0);
                uint64_t base = (rng() & 0x3f) << 4;
                unsigned logBytes = 3 + (rng() % 10);
                entry.addr = kind == 3 ?
                    ((base & ~((uint64_t(1) << logBytes) - 1)) >> 2) |
                    ((uint64_t(1) << (logBytes - 3)) - 1) : base >> 2;
            }
            uint64_t address = (rng() & 3) ? ((rng() & 0x7ff) + (rng() & 7)) :
                               (uint64_t(1) << 56) - (rng() & 15);
            one(dut, random, address, rng() % 4, rng() % 4, (rng() % 3) == 0 ? 3 : rng() % 2);
        }
        std::cout << "GSIM PMP checker: PASS directed=16 randomized=6000 entries=16\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM PMP checker: FAIL " << e.what() << '\n';
        return 1;
    }
}
