#include "FiveStageBranchPredictor.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
struct Entry { uint64_t pc = 0, target = 0; unsigned count = 0; bool valid = false, conditional = false; };
int main() { try {
    SFiveStageBranchPredictor d;
    d.set_reset(1); d.set_io$$train$$valid(0); d.set_io$$invalidate(0); d.set_io$$pc(0x80000000);
    d.step(); d.step(); d.set_reset(0);
    std::array<Entry, 64> table{};
    std::mt19937_64 rng(0xb1a2c3);
    unsigned takenCount = 0, aliasCount = 0;
    for (unsigned cycle = 0; cycle < 12000; ++cycle) {
        uint64_t pc = 0x80000000 + 4 * (rng() % 256), trainPc = 0x80000000 + 4 * (rng() % 256);
        bool train = rng() % 3, conditional = rng() % 2, taken = rng() % 2, branch = rng() % 5 != 0;
        bool invalidate = cycle % 137 == 0;
        uint64_t target = trainPc + (rng() % 128) * 4;
        d.set_io$$pc(pc); d.set_io$$train$$valid(train); d.set_io$$train$$bits$$pc(trainPc);
        d.set_io$$train$$bits$$target(target); d.set_io$$train$$bits$$conditional(conditional);
        d.set_io$$train$$bits$$controlFlow(branch); d.set_io$$train$$bits$$taken(taken);
        d.set_io$$invalidate(invalidate); d.step();
        auto &look = table[pc / 4 % 64]; bool hit = look.valid && look.pc == pc;
        uint64_t expected = hit && (!look.conditional || look.count >= 2) ? look.target : pc + 4;
        if (bool(d.get_io$$hit()) != hit || d.get_io$$nextPc() != expected)
            throw std::runtime_error("independent tagged BTB/counter oracle mismatch");
        takenCount += expected != pc + 4;
        if (train) {
            auto &entry = table[trainPc / 4 % 64]; bool oldHit = entry.valid && entry.pc == trainPc;
            aliasCount += entry.valid && !oldHit;
            if (branch) {
                unsigned c = !oldHit ? (taken ? 2 : 1) : taken ? (entry.count == 3 ? 3 : entry.count + 1)
                    : (entry.count == 0 ? 0 : entry.count - 1);
                entry = {trainPc, target, c, true, conditional};
            } else if (oldHit) entry.valid = false;
        }
        if (invalidate) for (auto &entry : table) entry.valid = false;
    }
    if (!takenCount || !aliasCount) throw std::runtime_error("predictor coverage incomplete");
    std::cout << "FIVE_STAGE_PREDICTOR_PASS vectors=12000 taken=" << takenCount << " aliases=" << aliasCount
        << " saturation_invalidation_false_branch=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
