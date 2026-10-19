#include "FiveStageBackendControlFixture.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static void require(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
int main(int argc, char **argv) { try {
    SFiveStageBackendControlFixture d;
    const bool wrongCapacity = argc > 1 && std::string_view(argv[1]) == "--wrong-capacity";
    const bool wrongOwner = argc > 1 && std::string_view(argv[1]) == "--wrong-owner";
    d.set_reset(0);
    d.set_io$$offers(0); d.set_io$$ready(0); d.set_io$$enabled(0); d.set_io$$payload(0);
    unsigned capacityCases = 0, ownerCases = 0, blocked = 0, shadowed = 0;
    for (unsigned occupancy = 0; occupancy < 16; ++occupancy) {
        for (unsigned done = 0; done < 8; ++done) {
            d.set_io$$occupied(occupancy); d.set_io$$done(done); d.step();
            const bool rr = occupancy & 1, ex = occupancy & 2;
            const bool address = occupancy & 4, memory = occupancy & 8;
            const bool progress = done & 4;
            // Independently propagate exact downstream handshakes, opposite
            // to the DUT sum-of-vacancies formulation.
            const bool memoryFires = memory && (done & 1) && progress;
            const bool addressFires = address && (!memory || memoryFires) && progress;
            const bool executeFires = ex && (!address || addressFires) && (done & 2) && progress;
            const bool expected = !rr || (progress && (!ex || executeFires));
            require(bool(d.get_io$$capacity()) == (expected ^ wrongCapacity),
                    "independent backend capacity handshake oracle");
            ++capacityCases;
        }
    }
    std::mt19937_64 random{0x4921434150414349ULL};
    for (unsigned enabled = 0; enabled < 2; ++enabled)
        for (unsigned offers = 0; offers < 32; ++offers)
            for (unsigned ready = 0; ready < 8; ++ready) {
                const uint64_t payload = random();
                d.set_io$$offers(offers); d.set_io$$ready(ready);
                d.set_io$$enabled(enabled); d.set_io$$payload(payload); d.step();
                unsigned owner = 5;
                for (unsigned i = 0; i < 5; ++i) if (offers >> i & 1) { owner = i; break; }
                const bool stall = enabled && owner < 3 && !(ready >> owner & 1);
                const uint64_t expected = enabled
                    ? payload ^ (0x102030405060708ULL * (owner + 1)) : 0;
                require(d.get_io$$value() == (expected ^ uint64_t(wrongOwner)),
                        "independent nearest producer payload oracle");
                require(bool(d.get_io$$dependency()) == stall,
                        "independent unavailable producer stall oracle");
                if (!stall) require(d.get_io$$admitted() == expected,
                                    "unavailable producer escaped admission");
                blocked += stall;
                shadowed += stall && (offers >> (owner + 1));
                ++ownerCases;
            }
    require(blocked && shadowed, "missing blocked nearest same-rd coverage");
    std::cout << "I1_BACKEND_CONTROL_PASS capacity_cases=" << capacityCases
              << " owner_cases=" << ownerCases << " blocked=" << blocked
              << " shadowed=" << shadowed << " slots_unchanged=1\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
