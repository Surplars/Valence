#include "OwnerLocalIssueReadyGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
static void source(SOwnerLocalIssueReadyGsim& d, unsigned slot, unsigned a, unsigned b) {
#define SRC(i) case i: d.set_io$$source1$$r##i(a); d.set_io$$source2$$r##i(b); return
    switch (slot) {
        SRC(0); SRC(1); SRC(2); SRC(3); SRC(4); SRC(5); SRC(6); SRC(7);
        SRC(8); SRC(9); SRC(10); SRC(11); SRC(12); SRC(13); SRC(14); SRC(15);
    }
#undef SRC
    throw std::runtime_error("invalid source slot");
}
struct Allocation { bool valid = false; unsigned index = 0, a = 0, b = 0; };
struct Event { bool valid = false; unsigned index = 0; };
static void allocate(SOwnerLocalIssueReadyGsim& d, unsigned lane, const Allocation& a) {
#define ALLOC(i) case i: d.set_io$$allocate##i##$$valid(a.valid); \
    d.set_io$$allocate##i##$$bits$$index(a.index); d.set_io$$allocate##i##$$bits$$source1(a.a); \
    d.set_io$$allocate##i##$$bits$$source2(a.b); return
    switch (lane) { ALLOC(0); ALLOC(1); }
#undef ALLOC
    throw std::runtime_error("invalid allocation lane");
}
static void wake(SOwnerLocalIssueReadyGsim& d, unsigned port, Event e) {
#define WAKE(i) case i: d.set_io$$wake##i##$$valid(e.valid); d.set_io$$wake##i##$$bits(e.index); return
    switch (port) { WAKE(0); WAKE(1); WAKE(2); }
#undef WAKE
    throw std::runtime_error("invalid wake port");
}
static void reserve(SOwnerLocalIssueReadyGsim& d, unsigned port, Event e) {
#define RESERVE(i) case i: d.set_io$$reserve##i##$$valid(e.valid); d.set_io$$reserve##i##$$bits(e.index); return
    switch (port) { RESERVE(0); RESERVE(1); }
#undef RESERVE
    throw std::runtime_error("invalid reserve port");
}

static void promise(SOwnerLocalIssueReadyGsim& d, unsigned port, Event e) {
#define P(NAME) d.set_io$$##NAME##$$valid(e.valid); d.set_io$$##NAME##$$bits(e.index)
    if (port == 0) { P(loadPromise); }
    else if (port == 1) { P(aluPromise0); }
    else { P(aluPromise1); }
#undef P
}
int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SOwnerLocalIssueReadyGsim d;
    std::mt19937_64 rng(0x398932b135ULL);
    std::array<unsigned, 16> a{}, b{};
    uint64_t physical = 0xffffffffULL;
    uint16_t active = 0;
    unsigned comparisons = 0, allocationWake = 0, reserveWake = 0, rowReuse = 0, killed = 0;
    unsigned promisedUnready = 0, loadHits = 0, aluHits = 0, bothSources = 0, samePacketRaw = 0;
    auto reset = [&] {
        physical = 0xffffffffULL; active = 0; a.fill(63); b.fill(63);
        d.set_io$$physical(physical); d.set_io$$active(0);
        for (unsigned slot = 0; slot < 16; ++slot) source(d, slot, a[slot], b[slot]);
        for (unsigned lane = 0; lane < 2; ++lane) { allocate(d, lane, {}); reserve(d, lane, {}); }
        for (unsigned port = 0; port < 3; ++port) { wake(d, port, {}); promise(d, port, {}); }
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    };
    reset();
    for (unsigned cycle = 0; cycle < 16000; ++cycle) {
        if (cycle == 6000 || cycle == 12000) reset();
        std::array<Allocation, 2> allocation{};
        std::array<Event, 3> wakes{}, promises{};
        std::array<Event, 2> reserves{};
        for (auto& e : wakes) e = {rng() % 3 != 0, unsigned(rng() % 48)};
        for (auto& e : promises) e = {rng() % 3 != 0, 1 + unsigned(rng() % 47)};
        for (auto& e : reserves) e = {rng() % 3 == 0, 32 + unsigned(rng() % 16)};
        for (unsigned lane = 0; lane < 2; ++lane)
            allocation[lane] = {rng() % 3 != 0, (cycle + lane) % 16, unsigned(rng() % 48), unsigned(rng() % 48)};
        if (cycle % 8 == 0) {
            const unsigned destination = 32 + cycle % 16;
            allocation[0] = {true, cycle % 16, 0, 0};
            allocation[1] = {true, (cycle + 1) % 16, destination, destination};
            reserves[0] = wakes[0] = {true, destination}; ++samePacketRaw;
        }
        if (cycle % 8 == 1) {
            const unsigned destination = 32 + (cycle - 1) % 16;
            promises[0] = {true, destination};
            const unsigned alias = (cycle * 7) % 48;
            allocation[0] = {true, cycle % 16, alias, alias};
            wakes[0] = {true, alias}; reserves = {};
        }
        const uint16_t clearing = cycle % 11 == 0 ? uint16_t(rng()) : 0;
        for (const auto& n : allocation) for (auto w : wakes)
            allocationWake += n.valid && w.valid && (n.a == w.index || n.b == w.index);
        for (auto w : wakes) for (auto r : reserves)
            reserveWake += w.valid && r.valid && w.index == r.index;
        d.set_io$$physical(physical); d.set_io$$active(active);
        for (unsigned slot = 0; slot < 16; ++slot) source(d, slot, a[slot], b[slot]);
        for (unsigned lane = 0; lane < 2; ++lane) { allocate(d, lane, allocation[lane]); reserve(d, lane, reserves[lane]); }
        for (unsigned port = 0; port < 3; ++port) { wake(d, port, wakes[port]); promise(d, port, promises[port]); }
        d.step();
        std::array<uint16_t, 2> expected{};
        for (unsigned slot = 0; slot < 16; ++slot) if (active & (1U << slot)) {
            unsigned sourceHits = 0;
            for (unsigned operand = 0; operand < 2; ++operand) {
                const unsigned index = operand == 0 ? a[slot] : b[slot];
                check(index < 48, "active source outside independent scoreboard");
                bool ready = (physical >> index) & 1;
                for (unsigned port = 0; port < 3; ++port) if (promises[port].valid && promises[port].index == index) {
                    promisedUnready += !ready;
                    if (!ready) { if (port == 0) ++loadHits; else ++aluHits; }
                    ++sourceHits; ready = true;
                }
                if (ready) expected[operand] |= 1U << slot;
                ++comparisons;
            }
            bothSources += sourceHits >= 2;
        }
        uint16_t local1 = d.get_io$$local1();
        if (inject && cycle >= 100 && active) local1 ^= active & -active;
        check(d.get_io$$global1() == expected[0] && d.get_io$$global2() == expected[1] &&
            local1 == expected[0] && d.get_io$$local2() == expected[1],
            "owner-local issue readiness differs from independent scoreboard and promises");
        for (auto w : wakes) if (w.valid) physical |= uint64_t(1) << w.index;
        for (auto r : reserves) if (r.valid) physical &= ~(uint64_t(1) << r.index);
        killed += __builtin_popcount(active & clearing); active &= ~clearing;
        for (auto n : allocation) if (n.valid) {
            rowReuse += (active >> n.index) & 1;
            a[n.index] = n.a; b[n.index] = n.b; active |= 1U << n.index;
        }
        for (unsigned slot = 0; slot < 16; ++slot) if (!(active & (1U << slot))) a[slot] = b[slot] = 63;
    }
    check(comparisons > 200000 && allocationWake > 1000 && reserveWake > 1000 && rowReuse > 5000 &&
        killed > 2000 && promisedUnready > 1000 && loadHits > 500 && aluHits > 500 && bothSources > 500 &&
        samePacketRaw == 2000, "missing readiness coincidence/promise/reuse coverage");
    std::cout << "GSIM owner-local issue readiness: PASS cycles=16000 comparisons=" << comparisons
        << " allocationWake=" << allocationWake << " reserveWake=" << reserveWake << " rowReuse=" << rowReuse
        << " killed=" << killed << " promisedUnready=" << promisedUnready << " loadHits=" << loadHits
        << " aluHits=" << aluHits << " bothSources=" << bothSources << " samePacketRaw=" << samePacketRaw << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << "GSIM owner-local issue readiness: " << e.what() << '\n'; return 1; } }
