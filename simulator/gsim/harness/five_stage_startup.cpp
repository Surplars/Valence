#include "FiveStageStartup.h"
#include <iostream>
#include <random>
#include <stdexcept>
#ifndef I1_HAS_ROM
#define I1_HAS_ROM 1
#endif
int main() { try {
    SFiveStageStartup d;
    std::mt19937_64 rng{0x525354};
    unsigned checks = 0;
    for (unsigned trial = 0; trial < 32; ++trial) {
        d.set_reset(1); d.set_io$$clockLocked(0); d.set_io$$ddrReady(0); d.step(); d.step(); d.set_reset(0);
        bool l0 = false, l1 = false, r0 = false, r1 = false, released = false, seenReady = false, fault = false;
        unsigned count = 0;
        for (unsigned cycle = 0; cycle < 180; ++cycle) {
            bool lock = cycle >= 10 && (cycle < 100 || bool(rng() % 3));
            bool ready = cycle >= 45 && (cycle < 100 || bool(rng() % 3));
            d.set_io$$clockLocked(lock); d.set_io$$ddrReady(ready); d.step();
            if (d.get_io$$held() != !released || d.get_io$$memoryReady() != (r1 && !fault) ||
                d.get_io$$fault() != fault) throw std::runtime_error("startup/reset readiness oracle mismatch");
            ++checks;
            bool oldReleased = released, oldSeen = seenReady;
            if (!released) {
                if (!(l1 && (I1_HAS_ROM || r1))) count = 0;
                else if (count == 3) released = true;
                else ++count;
            }
            if (oldReleased && r1) seenReady = true;
            if (oldReleased && (!l1 || (oldSeen && !r1))) fault = true;
            l1 = l0; l0 = lock; r1 = r0; r0 = ready;
        }
        if (!released || !fault) throw std::runtime_error("lost readiness did not latch fault without hot reset");
    }
    std::cout << "FIVE_STAGE_STARTUP_PASS checks=" << checks << " bootrom=" << I1_HAS_ROM
              << " synchronized_startup_no_owner_discard=PASS\n"; return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
