#include "RetireTimingGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SRetireTimingGsim d;
    d.set_reset(0);
    std::mt19937_64 rng(0x20261002b5ULL);
    uint64_t equalCases = 0, signCases = 0, faults16 = 0, faults32 = 0, notTaken = 0;
    unsigned takenKinds = 0, notTakenKinds = 0;
    constexpr uint64_t sign = UINT64_C(1) << 63;
    constexpr unsigned cases = 262144;
    for (unsigned n = 0; n < cases; ++n) {
        uint64_t a = rng(), b = rng();
        // Independently exercise equality and first differences at every byte,
        // signed boundaries and carry/wrap cases; do not import DUT definitions.
        const unsigned stimulus = (n / 16) % 8;
        if (stimulus == 0) b = a;
        if (stimulus == 1) b = a ^ (UINT64_C(1) << ((n / 128) % 64));
        if (stimulus == 2) { a = (UINT64_C(1) << ((n / 128) % 64)) - 1; b = a + 1; }
        if (stimulus == 3) { a = sign - 1; b = sign; }
        if (stimulus == 4) { a = sign; b = UINT64_MAX; }
        const uint64_t pc = rng(), imm = rng();
        const unsigned kind = n % 16;
        const bool shortInst = rng() & 1;
        const bool eq = a == b, ult = a < b, slt = (a ^ sign) < (b ^ sign);
        bool taken = false;
        switch (kind) {
        case 1: taken = eq; break;
        case 2: taken = !eq; break;
        case 3: taken = slt; break;
        case 4: taken = !slt; break;
        case 5: taken = ult; break;
        case 6: taken = !ult; break;
        case 7: case 8: taken = true; break;
        }
        const uint64_t sum = (kind == 8 ? a : pc) + imm;
        const uint64_t target = kind == 8 ? sum & ~UINT64_C(1) : sum;
        const uint64_t sequential = pc + (shortInst ? 2 : 4);
        uint64_t expectedPc = taken ? target : sequential;
        const uint64_t data = kind == 7 || kind == 8 ? sequential : 0;
        d.set_io$$left(a); d.set_io$$right(b); d.set_io$$pc(pc); d.set_io$$immediate(imm);
        d.set_io$$kind(kind); d.set_io$$short(shortInst); d.step();
        if (inject && n == 7) expectedPc ^= 1;
        if (bool(d.get_io$$equal()) != eq || bool(d.get_io$$unsignedLess()) != ult ||
            bool(d.get_io$$signedLess()) != slt || d.get_io$$target() != target ||
            d.get_io$$nextPc() != expectedPc || d.get_io$$data() != data ||
            bool(d.get_io$$legal()) != (kind >= 1 && kind <= 8) ||
            bool(d.get_io$$misaligned16()) != (taken && (target & 1)) ||
            bool(d.get_io$$misaligned32()) != (taken && (target & 3)))
            throw std::runtime_error("branch compare/result oracle mismatch");
        equalCases += eq; signCases += bool((a ^ b) & sign);
        faults16 += taken && (target & 1); faults32 += taken && (target & 3);
        notTaken += !taken;
        takenKinds |= taken ? 1U << kind : 0;
        notTakenKinds |= !taken ? 1U << kind : 0;
    }
    if (!equalCases || !signCases || !faults16 || !faults32 || !notTaken)
        throw std::runtime_error("branch compare coverage incomplete");
    if ((takenKinds & 0x7e) != 0x7e || (notTakenKinds & 0x7e) != 0x7e)
        throw std::runtime_error("conditional branch bidirectional coverage incomplete");
    std::cout << "GSIM branch compare/result: PASS vectors=" << cases << " kinds=16 equal=" << equalCases
              << " sign_differ=" << signCases << " misaligned16=" << faults16
              << " misaligned32=" << faults32 << " not_taken=" << notTaken
              << " conditional_bidirectional=6\n";
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
