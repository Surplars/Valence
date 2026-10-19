#include "FiveStagePreparedQueueFixture.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static void require(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
int main(int argc, char **argv) { try {
    SFiveStagePreparedQueueFixture d;
    const bool wrongReady = argc > 1 && std::string_view(argv[1]) == "--wrong-ready";
    const bool wrongData = argc > 1 && !wrongReady;
    std::deque<uint64_t> queue;
    std::mt19937_64 random{0x51554555454e4154ULL};
    unsigned accepted = 0, consumed = 0, stalled = 0, full = 0, simultaneous = 0, resets = 0;
    auto reset = [&] {
        d.set_reset(1); d.set_io$$enq$$valid(0); d.set_io$$enq$$bits(0); d.set_io$$deq$$ready(0);
        d.step(); d.step(); d.set_reset(0); queue.clear(); ++resets;
    };
    auto tick = [&](bool valid, uint64_t bits, bool ready) {
        const bool credit = queue.size() < 2;
        d.set_io$$enq$$valid(valid); d.set_io$$enq$$bits(bits); d.set_io$$deq$$ready(ready); d.step();
        require(bool(d.get_io$$enq$$ready()) == (credit ^ wrongReady),
                "independent registered queue credit oracle");
        require(bool(d.get_io$$deq$$valid()) == !queue.empty() && d.get_io$$count() == queue.size(),
                "independent registered queue occupancy oracle");
        if (!queue.empty())
            require(d.get_io$$deq$$bits() == (queue.front() ^ uint64_t(wrongData)),
                    "independent registered queue payload oracle");
        const bool pop = !queue.empty() && ready, push = valid && credit;
        stalled += !queue.empty() && !ready; full += queue.size() == 2; simultaneous += pop && push;
        if (pop) { queue.pop_front(); ++consumed; }
        if (push) { queue.push_back(bits); ++accepted; }
    };
    reset();
    for (unsigned cycle = 0; cycle < 20000; ++cycle) {
        if (cycle && cycle % 1997 == 0) { reset(); continue; }
        const unsigned phase = cycle % 113;
        const bool valid = phase < 48 || (phase > 80 && (random() & 1));
        const bool ready = phase >= 32 && (phase > 70 || (random() & 3) != 0);
        // Invalid input payload changes too; it never owns a slot.
        tick(valid, random(), ready);
    }
    for (unsigned cycle = 0; cycle < 5; ++cycle) tick(false, random(), true);
    require(queue.empty() && accepted && consumed && stalled && full && simultaneous && resets == 11,
            "missing two-slot reset/full/turnover coverage");
    std::cout << "I1_PREPARED_QUEUE_PASS stimulus_cycles=20000 resets=" << resets
              << " accepted=" << accepted << " consumed=" << consumed
              << " slots=2 held_payload_credit_latency_II_unchanged=1\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
