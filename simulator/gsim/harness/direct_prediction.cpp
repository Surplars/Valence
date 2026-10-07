#include "DirectPredictionGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SDirectPredictionGsim d;
    d.set_reset(0);
    unsigned vectors = 0, wraps = 0, sequential = 0, misaligned = 0;
    auto verify = [&](uint64_t pc, uint64_t immediate, bool shortInstruction) {
        // Literal architectural-width addition is deliberately independent of
        // the DUT's cancellation and low-bit qualification formulas.
        const uint64_t target = pc + immediate;
        const uint64_t successor = pc + (shortInstruction ? 2 : 4);
        d.set_io$$pc(pc); d.set_io$$immediate(immediate);
        d.set_io$$shortInstruction(shortInstruction); d.step();
        bool different = d.get_io$$differentSuccessor();
        if (inject && vectors == 100) { different = !different; inject = false; }
        if (bool(d.get_io$$aligned16()) != ((target % 2) == 0) ||
            bool(d.get_io$$aligned32()) != ((target % 4) == 0) ||
            different != (target != successor))
            throw std::runtime_error("direct prediction qualification oracle mismatch");
        ++vectors; wraps += target < pc; sequential += target == successor;
        misaligned += target % 4 != 0;
    };
    const uint64_t pcs[] = {0, 1, 2, 3, 4, 0x80000000ULL, 0x80200002ULL,
        0x7ffffffffffffffeULL, 0x8000000000000000ULL, UINT64_MAX - 4, UINT64_MAX - 2, UINT64_MAX};
    const uint64_t immediates[] = {0, 1, 2, 3, 4, 6, 8, uint64_t(-1), uint64_t(-2), uint64_t(-4),
        uint64_t(-4096), 4096, 0x7fffffffffffffffULL, 0x8000000000000000ULL, UINT64_MAX};
    for (uint64_t pc : pcs) for (uint64_t immediate : immediates)
        for (bool shortInstruction : {false, true}) verify(pc, immediate, shortInstruction);
    std::mt19937_64 rng(0x100f20261002ULL);
    for (unsigned i = 0; i < 50000; ++i) verify(rng(), rng(), bool(rng() & 1));
    if (!wraps || !sequential || !misaligned) throw std::runtime_error("prediction qualification coverage missing");
    std::cout << "GSIM direct prediction qualification: PASS vectors=" << vectors << " wrap=" << wraps
              << " sequential=" << sequential << " misaligned=" << misaligned << " full64LiteralOracle=1\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
