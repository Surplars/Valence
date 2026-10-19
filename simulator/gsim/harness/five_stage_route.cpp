#include "FiveStageTileLinkRoute.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef ALLOW_REGISTERS
#define ALLOW_REGISTERS 0
#endif
#ifndef I1_TIMING_CUTS
#define I1_TIMING_CUTS 0
#endif
static void need(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Request { uint64_t address, data; unsigned opcode, size, source, mask; };
int main(int argc, char **argv) { try {
    const bool mutate = argc > 1 && std::string(argv[1]) == "--wrong-route";
    constexpr uint64_t base = 0x80200000ULL, end = 0x100200000ULL;
    std::vector<Request> cases;
    std::mt19937_64 rng(0x726f757465ULL);
    const std::array<uint64_t, 13> points{0, 0x10000000, base - 1, base, base + 1,
        0xffffffffULL, 0x100000000ULL, end - 128, end - 8, end - 1, end, end + 1, UINT64_MAX};
    for (unsigned size = 0; size <= 7; ++size)
        for (auto address : points)
            for (unsigned op : {4U, 1U, 0U, 5U})
                cases.push_back({address, rng(), op, size, unsigned(rng() & 1), unsigned(rng() & 255)});
    for (unsigned n = 0; n < 1000; ++n) {
        unsigned size = rng() % 8;
        uint64_t address = (n & 1) ? base + rng() % (end - base) : 0x10000000 + rng() % 4096;
        if (n % 3) address &= ~((1ULL << size) - 1);
        cases.push_back({address, rng(), unsigned(n % 4 ? 4 : 1), size,
            unsigned(rng() & 1), unsigned(rng() & 255)});
    }
    SFiveStageTileLinkRoute d;
    d.set_reset(1); d.set_io$$host$$a$$valid(0); d.set_io$$host$$d$$ready(0);
    d.set_io$$memory$$a$$ready(0); d.set_io$$memory$$d$$valid(0);
    d.set_io$$registers$$request$$ready(0); d.set_io$$registers$$response$$valid(0);
    d.step(); d.step(); d.set_reset(0);
    unsigned memories = 0, registers = 0, denies = 0, totalBeats = 0;
    for (const auto &r : cases) {
        // Independent end arithmetic uses 128 bits, NOT the DUT's optimized range expression.
        unsigned __int128 high = static_cast<unsigned __int128>(r.address) + (1ULL << r.size);
        bool aligned = r.address % (1ULL << r.size) == 0;
        bool inMemory = aligned && r.address >= base && high <= end;
        bool inRegisters = !inMemory && ALLOW_REGISTERS && aligned && r.size <= 3 &&
            (r.opcode == 4 || r.opcode == 0 || r.opcode == 1);
        unsigned expectedOwner = inMemory ? 1 : inRegisters ? 2 : 3;
        if (mutate && r.address == base && r.size == 0) expectedOwner = 3;
        unsigned owner = 0, beat = 0, count = r.opcode == 4 ? unsigned(((1ULL << r.size) + 7) / 8) : 1;
        bool accepted = false, forwarded = false, finished = false;
        for (unsigned cycle = 0; cycle < 400 && !finished; ++cycle) {
            bool mr = rng() % 3 != 0, rr = rng() % 4 != 0, ready = rng() % 4 == 0;
            bool response = forwarded && cycle > 7;
            uint64_t value = 0x0123456789abcdefULL ^ r.address ^ (uint64_t(beat) << 32);
            d.set_io$$host$$a$$valid(!accepted);
            // After upstream acceptance the live host is deliberately changed.
            // Only the held owner's packet may reach a stalled downstream.
            d.set_io$$host$$a$$bits$$address(accepted && I1_TIMING_CUTS ? ~r.address : r.address);
            d.set_io$$host$$a$$bits$$data(accepted && I1_TIMING_CUTS ? ~r.data : r.data);
            d.set_io$$host$$a$$bits$$opcode(r.opcode); d.set_io$$host$$a$$bits$$size(r.size);
            d.set_io$$host$$a$$bits$$source(r.source); d.set_io$$host$$a$$bits$$mask(r.mask);
            d.set_io$$host$$d$$ready(ready);
            d.set_io$$memory$$a$$ready(mr); d.set_io$$memory$$d$$valid(response && owner == 1);
            d.set_io$$memory$$d$$bits$$data(value); d.set_io$$memory$$d$$bits$$size(r.size);
            d.set_io$$memory$$d$$bits$$source(r.source);
            d.set_io$$memory$$d$$bits$$opcode(r.opcode == 4 ? 1 : 0);
            d.set_io$$memory$$d$$bits$$denied(0); d.set_io$$memory$$d$$bits$$corrupt(0);
            d.set_io$$registers$$request$$ready(rr); d.set_io$$registers$$response$$valid(response && owner == 2);
            d.set_io$$registers$$response$$bits$$data(value); d.set_io$$registers$$response$$bits$$error(0);
            d.step();
            bool offer = I1_TIMING_CUTS ? accepted && !forwarded : !accepted;
            need(bool(d.get_io$$memory$$a$$valid()) == (offer && inMemory),
                "independent route memory offer oracle");
            need(bool(d.get_io$$registers$$request$$valid()) == (offer && inRegisters),
                "independent route register offer oracle");
            if (offer && inMemory) {
                need(d.get_io$$memory$$a$$bits$$address() == r.address &&
                    d.get_io$$memory$$a$$bits$$data() == r.data &&
                    d.get_io$$memory$$a$$bits$$size() == r.size &&
                    d.get_io$$memory$$a$$bits$$source() == r.source, "route held memory metadata oracle");
            }
            if (offer && inRegisters) {
                need(d.get_io$$registers$$request$$bits$$address() == r.address &&
                    d.get_io$$registers$$request$$bits$$data() == (r.data >> (8 * (r.address & 7))) &&
                    d.get_io$$registers$$request$$bits$$byteEnable() == (r.mask >> (r.address & 7)) &&
                    bool(d.get_io$$registers$$request$$bits$$write()) == (r.opcode != 4),
                    "route subword register lane oracle");
            }
            bool expectedValid = accepted && (!I1_TIMING_CUTS || forwarded) && (owner == 3 || response);
            need(bool(d.get_io$$host$$d$$valid()) == expectedValid, "route response owner oracle");
            if (expectedValid) {
                need(d.get_io$$host$$d$$bits$$source() == r.source &&
                    d.get_io$$host$$d$$bits$$size() == r.size &&
                    d.get_io$$host$$d$$bits$$opcode() == (r.opcode == 4 ? 1 : 0) &&
                    bool(d.get_io$$host$$d$$bits$$denied()) == (owner == 3), "route held D metadata oracle");
                if (owner != 3) need(d.get_io$$host$$d$$bits$$data() ==
                    (owner == 1 ? value : value << (8 * (r.address & 7))), "route held response data oracle");
                if (ready) { ++beat; ++totalBeats; finished = beat == count; }
            }
            if (offer && (inMemory ? mr : inRegisters ? rr : true)) {
                unsigned actualOwner = d.get_io$$memory$$a$$valid() ? 1 :
                    d.get_io$$registers$$request$$valid() ? 2 : 3;
                need(actualOwner == expectedOwner, "independent route destination oracle");
                forwarded = true;
            }
            if (!accepted && d.get_io$$host$$a$$ready()) {
                owner = inMemory ? 1 : inRegisters ? 2 : 3; accepted = true;
                memories += owner == 1; registers += owner == 2; denies += owner == 3;
            }
        }
        need(finished, "route bounded completion oracle");
    }
    need(memories > 10 && denies > 10 && (!ALLOW_REGISTERS || registers > 10), "route coverage");
    std::cout << "FIVE_STAGE_ROUTE_PASS transactions=" << cases.size() << " beats=" << totalBeats
        << " memory=" << memories << " registers=" << registers << " denied=" << denies
        << " bounds_above4G_alignment_lane_backpressure=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
