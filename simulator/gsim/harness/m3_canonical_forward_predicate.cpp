#include "M3CanonicalForwardPredicateGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

using Wide = unsigned __int128;
constexpr uint64_t ram = 0x80200000ULL, endRam = ram + (1ULL << 31);
static void need(bool b, const std::string &s) { if (!b) throw std::runtime_error(s); }
struct Case {
    bool sourceValid = true, storeValid = true, loadValid = true, readAllowed = true;
    bool ordinary = true, older = true, pending = false, stable = true;
    unsigned sourceIndex = 15, storeIndex = 15, loadIndex = 0, sourceSize = 3, storeSize = 3, loadSize = 3;
    uint64_t sourceTag = 0x8000000100000042ULL, storeTag = sourceTag, loadTag = sourceTag + 1;
    uint64_t sourceVa = 0x40000100, storeVa = sourceVa, loadVa = 0x50000100;
    uint64_t storePa = ram + 0x100, loadPa = storePa;
    uint32_t epoch = 0x80000021, storeEpoch = epoch, loadEpoch = epoch;
    unsigned mask = 255;
};
static bool aligned(uint64_t a, unsigned size) { return a % (1u << size) == 0; }
static bool ramRange(uint64_t a, unsigned size) {
    return Wide(a) >= ram && Wide(a) + (1u << size) <= endRam;
}
static unsigned byteMask(uint64_t a, unsigned size) {
    unsigned m = 0;
    for (unsigned b = 0; b < (1u << size); ++b)
        if (a % 8 + b < 8) m |= 1u << (a % 8 + b);
    return m;
}
static bool oracle(const Case &c) {
    if (!c.sourceValid || !c.storeValid || !c.loadValid || !c.readAllowed || !c.ordinary ||
        !c.older || c.pending || !c.stable || c.storeSize > 3) return false;
    if (c.sourceIndex != c.storeIndex || c.sourceTag != c.storeTag ||
        c.sourceVa != c.storeVa || c.sourceSize != c.storeSize ||
        (c.sourceIndex == c.loadIndex && c.sourceTag == c.loadTag)) return false;
    if (c.storeEpoch != c.epoch || c.loadEpoch != c.epoch) return false;
    if (!aligned(c.storeVa, c.storeSize) || !aligned(c.storePa, c.storeSize) ||
        !aligned(c.loadVa, c.loadSize) || !aligned(c.loadPa, c.loadSize) ||
        c.storeVa % 4096 != c.storePa % 4096 || c.loadVa % 4096 != c.loadPa % 4096 ||
        !ramRange(c.storePa, c.storeSize) || !ramRange(c.loadPa, c.loadSize) ||
        c.mask != byteMask(c.storePa, c.storeSize)) return false;
    // Independently enumerate actual bytes, rather than reproduce the DUT beat/mask equation.
    for (unsigned b = 0; b < (1u << c.loadSize); ++b)
        if (Wide(c.loadPa) + b < c.storePa || Wide(c.loadPa) + b >= Wide(c.storePa) + (1u << c.storeSize))
            return false;
    return true;
}
static void drive(SM3CanonicalForwardPredicateGsim &d, const Case &c) {
    d.set_io$$source$$valid(c.sourceValid);
    d.set_io$$source$$bits$$token$$index(c.sourceIndex); d.set_io$$source$$bits$$token$$tag(c.sourceTag);
    d.set_io$$source$$bits$$address(c.sourceVa); d.set_io$$source$$bits$$size(c.sourceSize);
    d.set_io$$source$$bits$$data(0x80ff7f0181828384ULL);
    d.set_io$$store$$valid(c.storeValid);
    d.set_io$$store$$bits$$origin$$token$$index(c.storeIndex);
    d.set_io$$store$$bits$$origin$$token$$tag(c.storeTag);
    d.set_io$$store$$bits$$origin$$epoch(c.storeEpoch);
    d.set_io$$store$$bits$$virtualAddress(c.storeVa); d.set_io$$store$$bits$$size(c.storeSize);
    d.set_io$$store$$bits$$mask(c.mask); d.set_io$$store$$bits$$physicalAddress(c.storePa);
    d.set_io$$load$$valid(c.loadValid);
    d.set_io$$load$$bits$$token$$index(c.loadIndex); d.set_io$$load$$bits$$token$$tag(c.loadTag);
    d.set_io$$load$$bits$$address(c.loadVa); d.set_io$$load$$bits$$size(c.loadSize);
    d.set_io$$load$$bits$$physicalAddress(c.loadPa); d.set_io$$load$$bits$$epoch(c.loadEpoch);
    d.set_io$$load$$bits$$allowed(c.readAllowed);
    d.set_io$$ordinaryVirtualLoad(c.ordinary); d.set_io$$sourceOlder(c.older);
    d.set_io$$pendingOlderStore(c.pending); d.set_io$$stable(c.stable); d.set_io$$epoch(c.epoch);
}
int main(int argc, char **argv) {
    try {
        bool inject = argc == 2 && std::string(argv[1]) == "--inject-result";
        need(argc == 1 || inject, "unknown option");
        SM3CanonicalForwardPredicateGsim d;
        d.set_clock(0); d.set_reset(1); d.step(); d.set_clock(1); d.step();
        d.set_clock(0); d.set_reset(0); d.step();
        unsigned tested = 0, allowed = 0, denied = 0, alias = 0;
        auto check = [&](const Case &c) {
            drive(d, c); d.step(); const bool expected = oracle(c);
            bool actual = d.get_io$$qualified();
            if (inject && tested == 0) { std::cerr << "INJECT M3 predicate result\n"; actual = !actual; }
            need(actual == expected, "M3 predicate independent byte/owner/epoch oracle mismatch");
            ++tested; allowed += expected; denied += !expected;
            alias += expected && c.sourceVa != c.loadVa;
        };
        check(Case{});
        for (unsigned ss = 0; ss < 4; ++ss) for (unsigned ls = 0; ls < 4; ++ls)
            for (unsigned so = 0; so < 8; ++so) for (unsigned lo = 0; lo < 8; ++lo) {
                Case c; c.sourceSize = c.storeSize = ss; c.loadSize = ls;
                c.sourceVa += so; c.storeVa += so; c.storePa += so; c.loadVa += lo; c.loadPa += lo;
                c.mask = byteMask(c.storePa, c.storeSize); check(c);
            }
        for (unsigned variant = 0; variant < 32; ++variant) {
            Case c;
            switch (variant) {
            case 0: c.sourceValid = false; break;
            case 1: c.storeValid = false; break;
            case 2: c.loadValid = false; break;
            case 3: c.readAllowed = false; break;
            case 4: c.ordinary = false; break;
            case 5: c.older = false; break;
            case 6: c.pending = true; break;
            case 7: c.stable = false; break;
            case 8: c.storeTag ^= 1ULL << 48; break;
            case 9: c.storeIndex ^= 1; break;
            case 10: c.storeEpoch ^= 1; break;
            case 11: c.loadEpoch ^= 1; break;
            case 12: ++c.epoch; break;
            case 13: c.storeVa += 4096; break;
            case 14: c.sourceSize = 2; break;
            case 15: c.storeSize = 7; break;
            case 16: c.mask = 127; break;
            case 17: c.loadPa += 4096; break;
            case 18: c.loadVa = c.sourceVa; c.loadPa += 4096; break;
            case 19: c.loadPa ^= 1ULL << 63; break;
            case 20: c.loadVa += 4; break;
            case 21: c.storePa += 4; break;
            case 22: c.loadIndex = c.sourceIndex; c.loadTag = c.sourceTag; break;
            case 23: c.storePa = c.loadPa = ram - 8; c.sourceVa = c.storeVa = c.loadVa = 0xff8; break;
            case 24: c.storePa = c.loadPa = endRam; c.sourceVa = c.storeVa = c.loadVa = 0; break;
            case 25: c.storePa = c.loadPa = endRam - 8; c.sourceVa = c.storeVa = c.loadVa = 0xff8; break;
            case 26: c.sourceTag = c.storeTag = UINT64_MAX; break;
            case 27: c.epoch = c.storeEpoch = c.loadEpoch = UINT32_MAX; break;
            case 28: c.loadIndex = c.sourceIndex; ++c.loadTag; break;
            case 29: c.sourceIndex = c.storeIndex = 0; c.loadIndex = 15; break;
            case 30: c.sourceVa = c.storeVa = c.loadVa; break;
            case 31: c.sourceSize = c.storeSize = 2; c.mask = 15; break;
            }
            check(c);
        }
        need(allowed > 50 && denied > 900 && alias > 50, "M3 predicate nonvacuous coverage missing");
        std::cout << "M3_CANONICAL_PREDICATE_PASS cases=" << tested << " allowed=" << allowed
                  << " denied=" << denied << " alias=" << alias << '\n';
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
