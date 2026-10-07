#include "RedirectCaptureGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SRedirectCaptureGsim d;
    d.set_reset(0);
    uint64_t checked = 0, killedOldest = 0, simultaneous = 0, blockedCases = 0;
    auto check = [&](unsigned flags, unsigned a, unsigned b, unsigned killed, bool blocked) {
        d.set_io$$flags(flags); d.set_io$$index0(a); d.set_io$$index1(b);
        d.set_io$$killed(killed); d.set_io$$blocked(blocked); d.step();
        for (bool high : {false, true}) {
            // Independent procedural oracle: choose the ORIGINAL oldest flag,
            // then reject it if killed. Never retry another lane after rejection.
            int chosen = -1;
            for (unsigned position = 0; position < 2; ++position) {
                unsigned lane = high ? 1 - position : position;
                if (flags & (1U << lane)) { chosen = int(lane); break; }
            }
            unsigned selected = chosen < 0 ? 0 : 1U << chosen;
            unsigned index = chosen == 0 ? a : b;
            bool accept = chosen >= 0 && !blocked && !(killed & (1U << index));
            unsigned clear = accept ? 1U << index : 0;
            if (inject && checked == 100 && high) clear ^= 1;
            unsigned gotSelected = high ? d.get_io$$selectedHigh() : d.get_io$$selectedLow();
            bool gotAccept = high ? d.get_io$$acceptHigh() : d.get_io$$acceptLow();
            unsigned gotClear = high ? d.get_io$$clearHigh() : d.get_io$$clearLow();
            if (gotSelected != selected || gotAccept != accept || gotClear != clear)
                throw std::runtime_error("redirect capture oracle mismatch");
            if (flags == 3 && !blocked && a != b && (killed & (1U << index)) &&
                !(killed & (1U << (chosen == 0 ? b : a)))) ++killedOldest;
        }
        ++checked; simultaneous += flags == 3; blockedCases += blocked;
    };
    for (unsigned a = 0; a < 16; ++a)
        for (unsigned b = 0; b < 16; ++b)
            for (unsigned flags = 0; flags < 4; ++flags)
                for (unsigned kills = 0; kills < 8; ++kills)
                    for (bool blocked : {false, true}) {
                        unsigned killed = (kills & 1 ? 1U << a : 0) |
                            (kills & 2 ? 1U << b : 0) | (kills & 4 ? 0xaaaaU : 0);
                        check(flags, a, b, killed, blocked);
                    }
    std::mt19937_64 rng(0x20261002c9ULL);
    for (unsigned n = 0; n < 50000; ++n) {
        // Draw each argument explicitly: no unspecified argument-evaluation order.
        unsigned flags = rng() & 3, a = rng() & 15, b = rng() & 15, killed = rng() & 65535;
        bool blocked = rng() & 1;
        check(flags, a, b, killed, blocked);
    }
    if (!killedOldest || !simultaneous || !blockedCases)
        throw std::runtime_error("redirect capture coverage incomplete");
    std::cout << "GSIM redirect capture: PASS vectors=" << checked
              << " priorities=2 killed_oldest_live_younger=" << killedOldest
              << " simultaneous=" << simultaneous << " blocked=" << blockedCases << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
