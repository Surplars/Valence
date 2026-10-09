#include "VirtualLoadPrecheckGsim.h"
#include "virtual_load_test_memory.h"
#include <deque>
#include <iostream>
#include <optional>
#include <tuple>
#include <vector>
#ifndef PRECHECK_ENABLED
#define PRECHECK_ENABLED 0
#endif
using namespace virtual_load_test;
struct Request {
    uint64_t address = va, epoch = 0;
    bool prechecked = false, virt = true, uncached = false;
    unsigned size = 3;
};
struct Expected { bool fault = false, page = false; uint64_t physical = 0; bool uncached = false; };
struct Reply { uint64_t due, data; bool error = false; };
struct Observation { bool hit = false, stable = false; uint64_t physical = 0, epoch = 0, queryEpoch = 0; unsigned pbmt = 0; };
class Bench {
    SVirtualLoadPrecheckGsim d;
    std::deque<Reply> ptes, physical;
    std::deque<Expected> expected;
    std::optional<std::tuple<uint64_t, unsigned, bool>> held;
public:
    PageTables tables;
    uint64_t cycle = 0, contextSatp = satp, pmpAddress = allPmp, queryAddress = va;
    unsigned privilege = 1, cfg = 0x1f, querySize = 3;
    unsigned requests = 0, responses = 0, pteReads = 0, walks = 0, physicalHolds = 0, hits = 0;
    unsigned blockPhysical = 0, blockResponse = 0, latency = 3;
    bool sum = false, mxr = false, query = false, flush = false, inject = false;
    Observation observed;
    Bench() {
        drive(std::nullopt); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        for (unsigned n = 0; n < 4; ++n) tick();
    }
    void drive(std::optional<Request> request) {
        Request r = request.value_or(Request{});
        d.set_io$$upstream$$request$$valid(request.has_value());
        d.set_io$$upstream$$request$$bits$$address(r.address);
        d.set_io$$upstream$$request$$bits$$data(0);
        d.set_io$$upstream$$request$$bits$$size(r.size);
        d.set_io$$upstream$$request$$bits$$mask((1u << (1u << r.size)) - 1);
        d.set_io$$upstream$$request$$bits$$write(0); d.set_io$$upstream$$request$$bits$$atomic(0);
        d.set_io$$upstream$$request$$bits$$atomicOp(0);
        d.set_io$$upstream$$request$$bits$$virtualized(r.virt);
        d.set_io$$upstream$$request$$bits$$uncached(r.uncached);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(1);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(r.prechecked);
        d.set_io$$upstream$$request$$bits$$translationEpoch(r.epoch);
        d.set_io$$upstream$$response$$ready(cycle >= blockResponse);
        d.set_io$$physical$$request$$ready(cycle >= blockPhysical && cycle % 7 != 5);
        const bool pv = !physical.empty() && physical.front().due <= cycle;
        d.set_io$$physical$$response$$valid(pv);
        d.set_io$$physical$$response$$bits$$data(pv ? physical.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(pv && physical.front().error);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(cycle % 5 != 3);
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$response$$valid(tv);
        d.set_io$$pte$$response$$bits$$data(tv ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(contextSatp); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(pmpAddress);
        d.set_io$$queryValid(query); d.set_io$$queryAddress(queryAddress); d.set_io$$querySize(querySize);
        d.set_io$$flush(flush);
    }
    bool tick(std::optional<Request> request = {}, std::optional<Expected> accepted = {}) {
        const bool pv = !physical.empty() && physical.front().due <= cycle;
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        drive(request); d.step();
        const bool take = request && d.get_io$$upstream$$request$$ready();
        if (take) { require(accepted.has_value(), "accepted request lacks independent expectation"); expected.push_back(*accepted); ++requests; }
        if (pv && d.get_io$$physical$$response$$ready()) physical.pop_front();
        if (tv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && cycle % 5 != 3) {
            ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())}); ++pteReads;
        }
        const bool valid = d.get_io$$physical$$request$$valid();
        auto payload = std::make_tuple(uint64_t(d.get_io$$physical$$request$$bits$$address()),
            unsigned(d.get_io$$physical$$request$$bits$$size()), bool(d.get_io$$physical$$request$$bits$$uncached()));
        if (held) require(valid && payload == *held, "physical payload changed under backpressure");
        const bool ready = cycle >= blockPhysical && cycle % 7 != 5;
        held = valid && !ready ? std::optional{payload} : std::nullopt;
        physicalHolds += valid && !ready;
        if (valid && ready) {
            auto next = expected.begin();
            unsigned pending = physical.size();
            // Only one request is normally issued by this fixture driver; pending
            // faults have no physical owner. This cursor is independent of DUT FIFOs.
            while (next != expected.end() && (next->fault || pending--)) ++next;
            require(next != expected.end(), "unauthorized or duplicate physical request");
            require(std::get<0>(payload) == (next->physical ^ (inject ? 8ULL : 0ULL)) &&
                std::get<1>(payload) == 3 && std::get<2>(payload) == next->uncached,
                "independent physical translation/attribute mismatch");
            require(!d.get_io$$physical$$request$$bits$$virtualized() &&
                !d.get_io$$physical$$request$$bits$$precheckedLoad(), "private authorization metadata escaped physically");
            physical.push_back({cycle + latency, readValue(next->physical)});
        }
        if (d.get_io$$upstream$$response$$valid() && cycle >= blockResponse) {
            require(!expected.empty(), "unowned response"); const auto e = expected.front(); expected.pop_front();
            require(bool(d.get_io$$upstream$$response$$bits$$error()) == e.fault &&
                bool(d.get_io$$upstream$$response$$bits$$pageFault()) == e.page &&
                d.get_io$$upstream$$response$$bits$$data() == (e.fault ? 0 : readValue(e.physical)),
                "independent ordered response/fault mismatch"); ++responses;
        }
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit();
        observed = {bool(d.get_io$$queryHit()), bool(d.get_io$$stable()), uint64_t(d.get_io$$queryPhysical()),
            uint64_t(d.get_io$$epoch()), uint64_t(d.get_io$$queryEpoch()), unsigned(d.get_io$$queryPbmt())};
        ++cycle; return take;
    }
    void run(Request r, Expected e) {
        const unsigned target = responses + 1;
        bool sent = false;
        for (unsigned n = 0; n < 1000 && responses < target; ++n) {
            if (!sent) sent = tick(r, e); else tick();
        }
        require(responses == target, "adapter transaction timed out");
        for (unsigned n = 0; n < 5; ++n) tick();
        require(d.get_io$$idle(), "adapter/service did not drain");
    }
    void settle() { for (unsigned n = 0; n < 4; ++n) tick(); }
    void peek(uint64_t address, bool expectedHit, uint64_t expectedPa = 0, unsigned pbmt = 0) {
        const auto beforeReads = pteReads, beforeWalks = walks, beforeRequests = requests;
        query = true; queryAddress = address; settle();
        require(observed.hit == (PRECHECK_ENABLED && expectedHit), "hit-only DTLB peek oracle mismatch");
        if (observed.hit) require(observed.physical == expectedPa && observed.pbmt == pbmt &&
            observed.queryEpoch == observed.epoch, "peek address/attribute/epoch mismatch");
        require(pteReads == beforeReads && walks == beforeWalks && requests == beforeRequests && physical.empty(),
            "peek generated a walk or data side effect");
        query = false; tick();
    }
};
#ifdef DTLB_ENTRIES
// External request/response and page-table checks only. No private TLB index is observed.
static void capacityReplacement() {
    static_assert(DTLB_ENTRIES == 4 || DTLB_ENTRIES == 8 || DTLB_ENTRIES == 16 || DTLB_ENTRIES == 32);
    Bench c;
    c.tables.pages.clear();
    for (unsigned i = 0; i <= DTLB_ENTRIES; ++i) c.tables.pages[i] = {ram, 0x43};
    for (unsigned i = 0; i < DTLB_ENTRIES; ++i) c.run({va + i * 4096}, {false, false, ram});
    require(c.walks == DTLB_ENTRIES && c.hits == 0, "capacity compulsory miss count mismatch");
    for (unsigned i = 0; i < DTLB_ENTRIES; ++i) {
        c.peek(va + i * 4096 + 24, true, ram + 24);
        c.run({va + i * 4096}, {false, false, ram});
    }
    require(c.walks == DTLB_ENTRIES && c.hits == DTLB_ENTRIES, "full-capacity warm hit count mismatch");
    // A failed walk neither fills nor advances round-robin replacement.
    c.run({va + (DTLB_ENTRIES + 1) * 4096}, {true, true});
    c.peek(va + (DTLB_ENTRIES + 1) * 4096, false);
    for (unsigned i = 0; i < DTLB_ENTRIES; ++i) c.peek(va + i * 4096, true, ram);
    c.run({va + DTLB_ENTRIES * 4096}, {false, false, ram});
    c.peek(va, false);
    for (unsigned i = 1; i <= DTLB_ENTRIES; ++i) c.peek(va + i * 4096, true, ram);
    c.run({va}, {false, false, ram});
    c.peek(va, true, ram); c.peek(va + 4096, false);
    // Wrapping through the remaining slots must leave exactly the new full set.
    for (unsigned i = 1; i < DTLB_ENTRIES; ++i) c.run({va + i * 4096}, {false, false, ram});
    for (unsigned i = 0; i < DTLB_ENTRIES; ++i) c.peek(va + i * 4096, true, ram);
    c.peek(va + DTLB_ENTRIES * 4096, false);
    require(c.walks == 2 * DTLB_ENTRIES + 2, "replacement/fault walk count mismatch");
    c.flush = true; c.tick(); c.flush = false; c.settle();
    for (unsigned i = 0; i < DTLB_ENTRIES; ++i) c.peek(va + i * 4096, false);
    std::cout << "DATA_TRANSLATION_CAPACITY_PASS entries=" << DTLB_ENTRIES
        << " walks=" << c.walks << " hits=" << c.hits << "\n";
}
#endif
int main(int argc, char **argv) { try {
#ifdef DTLB_ENTRIES
    capacityReplacement();
#endif
    Bench b; b.inject = argc > 1 && std::string(argv[1]) == "--inject-address";
    b.run({va}, {false, false, ram});
    b.run({va + 8}, {false, false, ram + 8});
    b.peek(va + 24, true, ram + 24);
    b.peek(va + 9 * 4096, false);
    b.peek(0x0000008040000000ULL, false);
    auto saved = b.contextSatp;
    b.contextSatp ^= 1ULL << 44; b.peek(va, false); b.contextSatp = saved; b.peek(va, true, ram);
    b.contextSatp ^= 1; b.peek(va, false); b.contextSatp = saved;
    b.contextSatp = (9ULL << 60) | (saved & ((1ULL << 60) - 1)); b.peek(va, false); b.contextSatp = saved;
    b.privilege = 0; b.peek(va, false); b.privilege = 1;
    b.sum = true; b.peek(va, false); b.sum = false;
    b.mxr = true; b.peek(va, false); b.mxr = false; b.peek(va, true, ram);
    b.run({va + 3 * 4096}, {false, false, 0x10000000ULL});
    b.peek(va + 3 * 4096, true, 0x10000000ULL);
    b.run({va + 4 * 4096}, {false, false, ram + 8192, true});
    b.peek(va + 4 * 4096, true, ram + 8192, 1);
    b.run({va + 5 * 4096}, {true, true}); b.peek(va + 5 * 4096, false);
    b.mxr = true; b.run({va + 5 * 4096}, {false, false, ram + 12288});
    b.peek(va + 5 * 4096, true, ram + 12288); b.mxr = false; b.peek(va + 5 * 4096, false);
    b.run({va + 6 * 4096}, {true, true});
    b.sum = true; b.run({va + 6 * 4096}, {false, false, ram + 16384}); b.sum = false;
    b.run({va + 9 * 4096}, {true, true});
    if (PRECHECK_ENABLED) {
        b.settle(); const auto epoch = b.observed.epoch;
        b.run({ram, epoch, true, false}, {false, false, ram});
        b.flush = true; b.tick(); b.flush = false; b.settle();
        require(b.observed.epoch != epoch, "flush did not revoke certificate epoch");
        b.run({ram, epoch, true, false}, {true, false});
        b.peek(va, false);
        b.tables.pages[0].physical = ram + 24576;
        b.run({va}, {false, false, ram + 24576}); b.peek(va, true, ram + 24576);
        b.cfg = 0x18; b.settle();
        b.run({ram, b.observed.epoch, true, false}, {true, false});
        b.cfg = 0x1f; b.settle();
        b.run({0x10000000ULL, b.observed.epoch, true, false}, {true, false});
        b.run({ram + ramBytes, b.observed.epoch, true, false}, {true, false});
        b.run({ram, b.observed.epoch, true, false, true}, {true, false});
    }
    b.blockPhysical = b.cycle + 100; b.blockResponse = b.cycle + 150;
    b.run({va + 1 * 4096}, {false, false, ram + 4096});
    require(b.physicalHolds > 0 && b.walks > 0 && b.hits > 0, "required pressure/warm translation coverage missing");
    std::cout << "VIRTUAL_LOAD_PRECHECK_PASS enabled=" << PRECHECK_ENABLED << " accepted=" << b.requests
        << " responses=" << b.responses << " pte_reads=" << b.pteReads << " walks=" << b.walks
        << " physical_holds=" << b.physicalHolds << "\n";
    return 0;
} catch (const std::exception &e) { std::cerr << "VIRTUAL_LOAD_PRECHECK_FAIL " << e.what() << "\n"; return 1; } }
