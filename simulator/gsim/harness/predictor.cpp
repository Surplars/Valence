#include "BranchPredictorGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>

int main() {
    try {
        SBranchPredictorGsim dut;
        dut.set_io$$pc0(0); dut.set_io$$pc1(0);
        dut.set_io$$train0$$valid(0); dut.set_io$$train1$$valid(0);
        dut.set_io$$train0$$bits$$pc(0); dut.set_io$$train1$$bits$$pc(0);
        dut.set_io$$train0$$bits$$taken(0); dut.set_io$$train1$$bits$$taken(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        std::array<unsigned, 64> counters; counters.fill(1);
        std::mt19937_64 rng(0x825192);
        unsigned collisions = 0;
        for (unsigned cycle = 0; cycle < 10000; ++cycle) {
            std::array<uint64_t, 2> pc{(rng() % 4096) * 4, (rng() % 4096) * 4};
            std::array<bool, 2> valid{rng() % 4 != 0, rng() % 4 != 0};
            std::array<bool, 2> taken{bool(rng() & 1), bool(rng() & 1)};
            if (cycle < 32) {
                pc = {0, 256}; valid = {true, true};
                taken = {cycle < 8 || cycle >= 16, cycle < 8 || cycle >= 24};
            } else if (cycle % 2 == 0) pc[1] = pc[0] + 256;
            dut.set_io$$pc0(pc[0]); dut.set_io$$pc1(pc[1]);
            dut.set_io$$train0$$valid(valid[0]); dut.set_io$$train1$$valid(valid[1]);
            dut.set_io$$train0$$bits$$pc(pc[0]); dut.set_io$$train1$$bits$$pc(pc[1]);
            dut.set_io$$train0$$bits$$taken(taken[0]); dut.set_io$$train1$$bits$$taken(taken[1]);
            dut.step();
            if (bool(dut.get_io$$taken0()) != (counters[(pc[0] >> 2) % 64] >= 2) ||
                bool(dut.get_io$$taken1()) != (counters[(pc[1] >> 2) % 64] >= 2))
                throw std::runtime_error("direction table saturation/collision mismatch");
            collisions += valid[0] && valid[1] && ((pc[0] >> 2) % 64 == (pc[1] >> 2) % 64);
            for (unsigned lane = 0; lane < 2; ++lane) if (valid[lane]) {
                auto &value = counters[(pc[lane] >> 2) % 64];
                if (taken[lane]) value = std::min(3U, value + 1);
                else if (value) --value;
            }
        }
        if (collisions < 2000) throw std::runtime_error("collision coverage");
        std::cout << "GSIM BranchPredictor: PASS cycles=10000 sameIndexDualUpdates=" << collisions << '\n';
    } catch (const std::exception &e) {
        std::cerr << "GSIM BranchPredictor: FAIL " << e.what() << '\n';
        return 1;
    }
}
