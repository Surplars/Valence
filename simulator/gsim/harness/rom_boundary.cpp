#include "RomBoundaryGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>

static void check(bool v, const char* m) { if (!v) throw std::runtime_error(m); }
struct A {
    uint64_t address, data;
    unsigned opcode, param, size, source, mask;
    bool corrupt;
    bool operator==(const A&) const = default;
};
struct D {
    uint64_t data;
    unsigned opcode, param, size, source, sink;
    bool denied, corrupt;
    bool operator==(const D&) const = default;
};
static void driveA(SRomBoundaryGsim& d, const A& a) {
#define F(n) d.set_io$$upstream$$a$$bits$$##n(a.n)
    F(address); F(data); F(opcode); F(param); F(size); F(source); F(mask); F(corrupt);
#undef F
}
static void driveD(SRomBoundaryGsim& d, const D& a) {
#define F(n) d.set_io$$downstream$$d$$bits$$##n(a.n)
    F(data); F(opcode); F(param); F(size); F(source); F(sink); F(denied); F(corrupt);
#undef F
}
static A readA(SRomBoundaryGsim& d) {
    A a;
#define F(n) a.n = d.get_io$$downstream$$a$$bits$$##n()
    F(address); F(data); F(opcode); F(param); F(size); F(source); F(mask); F(corrupt);
#undef F
    return a;
}
static D readD(SRomBoundaryGsim& d) {
    D a;
#define F(n) a.n = d.get_io$$upstream$$d$$bits$$##n()
    F(data); F(opcode); F(param); F(size); F(source); F(sink); F(denied); F(corrupt);
#undef F
    return a;
}
int main(int argc, char** argv) { try {
    bool inject = argc > 1 && std::string(argv[1]) == "--inject-mismatch";
    SRomBoundaryGsim d;
    std::mt19937_64 random(0xaac412);
    std::deque<A> expectedA;
    std::deque<D> expectedD;
    std::optional<A> offeredA;
    std::optional<D> offeredD;
    unsigned sequenceA = 0, sequenceD = 0, poppedA = 0, poppedD = 0;
    unsigned peakA = 0, peakD = 0, fullPop = 0, overlap = 0, resetDropped = 0;
    unsigned runA = 0, runD = 0, bestA = 0, bestD = 0;
    d.set_io$$upstream$$b$$ready(0);
    d.set_io$$upstream$$c$$valid(0);
    d.set_io$$upstream$$e$$valid(0);
    d.set_io$$downstream$$b$$valid(0);
    d.set_io$$downstream$$c$$ready(0);
    d.set_io$$downstream$$e$$ready(0);
    d.set_io$$upstream$$a$$valid(0);
    d.set_io$$downstream$$d$$valid(0);
    d.set_io$$downstream$$a$$ready(0);
    d.set_io$$upstream$$d$$ready(0);
    driveA(d, {}); driveD(d, {});
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    for (unsigned cycle = 0; cycle < 50000 || offeredA || offeredD ||
         !expectedA.empty() || !expectedD.empty(); ++cycle) {
        check(cycle < 50500, "registered TL queue drain timeout");
        if (cycle == 25000) {
            resetDropped += expectedA.size() + expectedD.size();
            // No handshakes are authorized during reset. Quiesce the drivers
            // before cancelling the in-flight beat slots, then resume offers.
            d.set_io$$upstream$$a$$valid(0); d.set_io$$downstream$$d$$valid(0);
            d.set_reset(1); d.step(); d.step(); d.set_reset(0);
            expectedA.clear(); expectedD.clear();
        }
        if (cycle < 50000 && !offeredA && (cycle < 300 || random() % 4 != 0)) {
            unsigned n = sequenceA++;
            offeredA = n < 128 ? A{0x80200000ULL + (n / 8) * 64, random(), 1, 0, 6,
                (n / 8) & 15, unsigned(random() & 255), bool(random() & 1)} :
                A{random(), random(), unsigned(random() % 6), unsigned(random() & 7),
                  unsigned(random() % 7), unsigned(random() & 15), unsigned(random() & 255), bool(random() & 1)};
        }
        if (cycle < 50000 && !offeredD && (cycle < 300 || random() % 3 != 0)) {
            unsigned n = sequenceD++;
            offeredD = D{random(), n < 128 ? 1U : unsigned(random() & 1),
                unsigned(random() & 7), n < 128 ? 6U : unsigned(random() % 7),
                n < 128 ? (n / 8) & 15 : unsigned(random() & 15), unsigned(random() & 1),
                bool(random() & 1), bool(random() & 1)};
        }
        bool readyA = cycle < 300 ? !(cycle >= 32 && cycle < 80) : random() % 4 != 0;
        bool readyD = cycle < 300 ? !(cycle >= 64 && cycle < 100) : random() % 3 != 0;
        if (cycle >= 24980 && cycle < 25000) { readyA = false; readyD = false; }
        d.set_io$$upstream$$a$$valid(bool(offeredA));
        d.set_io$$downstream$$d$$valid(bool(offeredD));
        driveA(d, offeredA.value_or(A{})); driveD(d, offeredD.value_or(D{}));
        d.set_io$$downstream$$a$$ready(readyA); d.set_io$$upstream$$d$$ready(readyD);
        d.step();
        if (bool(d.get_io$$downstream$$a$$valid()) != !expectedA.empty() ||
            bool(d.get_io$$upstream$$d$$valid()) != !expectedD.empty()) {
            std::cerr << "cycle=" << cycle << " expected_A=" << expectedA.size()
                << " actual_A_valid=" << unsigned(d.get_io$$downstream$$a$$valid())
                << " expected_D=" << expectedD.size()
                << " actual_D_valid=" << unsigned(d.get_io$$upstream$$d$$valid()) << "\n";
        }
        check(bool(d.get_io$$upstream$$a$$ready()) == (expectedA.size() < 2),
            "registered TL A ready is not occupancy-only");
        check(bool(d.get_io$$downstream$$d$$ready()) == (expectedD.size() < 2),
            "registered TL D ready is not occupancy-only");
        check(bool(d.get_io$$downstream$$a$$valid()) == !expectedA.empty(),
            "registered TL A bypass or validity mismatch");
        check(bool(d.get_io$$upstream$$d$$valid()) == !expectedD.empty(),
            "registered TL D bypass or validity mismatch");
        bool takeA = offeredA && expectedA.size() < 2;
        bool takeD = offeredD && expectedD.size() < 2;
        bool popA = !expectedA.empty() && readyA, popD = !expectedD.empty() && readyD;
        if (!expectedA.empty()) {
            A actual = readA(d);
            if (inject) { actual.data ^= 1; inject = false; }
            check(actual == expectedA.front(), "registered TL A independent FIFO oracle mismatch");
        }
        if (!expectedD.empty()) check(readD(d) == expectedD.front(),
            "registered TL D independent FIFO oracle mismatch");
        if (popA && expectedA.size() == 2) ++fullPop;
        if (popD && expectedD.size() == 2) ++fullPop;
        if (popA) { expectedA.pop_front(); ++poppedA; } if (popD) { expectedD.pop_front(); ++poppedD; }
        if (takeA) { expectedA.push_back(*offeredA); offeredA.reset(); }
        if (takeD) { expectedD.push_back(*offeredD); offeredD.reset(); }
        if ((takeA && popA) || (takeD && popD)) ++overlap;
        bestA = std::max(bestA, runA = popA ? runA + 1 : 0);
        bestD = std::max(bestD, runD = popD ? runD + 1 : 0);
        peakA = std::max(peakA, unsigned(expectedA.size())); peakD = std::max(peakD, unsigned(expectedD.size()));
    }
    check(peakA == 2 && peakD == 2 && fullPop > 100 && overlap > 1000 &&
        bestA > 100 && bestD > 100 && poppedA > 10000 && poppedD > 10000 && resetDropped > 0,
        "registered TL FIFO coverage incomplete");
    std::cout << "GSIM registered TL boundary: PASS A=" << poppedA << " D=" << poppedD
        << " fullPop=" << fullPop << " overlap=" << overlap << " II1=" << bestA << "/" << bestD
        << " resetDropped=" << resetDropped << "\n";
} catch (const std::exception& e) { std::cerr << "GSIM registered TL: FAIL " << e.what() << "\n"; return 1; } }
