#include "CanonicalStoreTrackerGsim.h"
#include "canonical_store_oracle.h"
#include <array>
#include <iostream>
#include <optional>
#include <random>
#include <vector>
using namespace canonical_store_test;

// GSIM samples outputs on the driven tick; the expected record advances only
// after checking that tick. This catches a combinational same-edge certificate bypass.
class Bench {
    SCanonicalStoreTrackerGsim d;
    std::optional<Descriptor> record;
    bool certified = false;
public:
    uint32_t epoch = 11;
    bool live = true, stable = true, invalidate = false;
    unsigned ticks = 0, certificates = 0, intervals = 0, overlapCases = 0, disjointCases = 0;
    bool inject = false;
    Bench() {
        drive({}, {});
        d.set_io$$loadAddress(0); d.set_io$$loadSize(0);
        d.set_io$$storeAddress(0); d.set_io$$storeSize(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0); tick();
    }
    void drive(std::optional<Descriptor> start, std::optional<Descriptor> checked) {
        const auto s = start.value_or(Descriptor{}), c = checked.value_or(Descriptor{});
        d.set_io$$start$$valid(start.has_value());
        d.set_io$$start$$bits$$origin$$token$$index(s.token.index);
        d.set_io$$start$$bits$$origin$$token$$tag(s.token.tag);
        d.set_io$$start$$bits$$origin$$epoch(s.epoch);
        d.set_io$$start$$bits$$virtualAddress(s.virtualAddress);
        d.set_io$$start$$bits$$size(s.size); d.set_io$$start$$bits$$mask(s.mask);
        d.set_io$$checked$$valid(checked.has_value());
        d.set_io$$checked$$bits$$origin$$token$$index(c.token.index);
        d.set_io$$checked$$bits$$origin$$token$$tag(c.token.tag);
        d.set_io$$checked$$bits$$origin$$epoch(c.epoch);
        d.set_io$$checked$$bits$$virtualAddress(c.virtualAddress);
        d.set_io$$checked$$bits$$physicalAddress(c.physicalAddress);
        d.set_io$$checked$$bits$$size(c.size); d.set_io$$checked$$bits$$mask(c.mask);
        d.set_io$$ownerLive(live); d.set_io$$invalidate(invalidate);
        d.set_io$$stable(stable); d.set_io$$epoch(epoch);
    }
    void tick(std::optional<Descriptor> start = {}, std::optional<Descriptor> checked = {}) {
        drive(start, checked); d.step();
        const bool expected = record && certified && live && stable && record->epoch == epoch;
        require(bool(d.get_io$$tracked()) == record.has_value(), "tracker lifetime mismatch");
        const bool actual = bool(d.get_io$$certificate$$valid()) ^ (inject && ticks == 12);
        require(actual == expected, "registered certificate validity/lifetime mismatch");
        if (record) {
            require(d.get_io$$owner$$index() == record->token.index && d.get_io$$owner$$tag() == record->token.tag,
                "tracker changed exact owner");
        }
        if (expected) {
            require(d.get_io$$certificate$$bits$$origin$$token$$index() == record->token.index &&
                d.get_io$$certificate$$bits$$origin$$token$$tag() == record->token.tag &&
                d.get_io$$certificate$$bits$$origin$$epoch() == record->epoch &&
                d.get_io$$certificate$$bits$$virtualAddress() == record->virtualAddress &&
                d.get_io$$certificate$$bits$$physicalAddress() == record->physicalAddress &&
                d.get_io$$certificate$$bits$$size() == record->size &&
                d.get_io$$certificate$$bits$$mask() == record->mask, "certificate descriptor corruption");
        }
        const auto previous = record;
        if (record && !live) { record.reset(); certified = false; }
        if (start) { record = start; certified = false; }
        if (checked && previous && live && stable && checked->epoch == epoch &&
            sameDescriptor(*checked, *previous) && shape(*checked)) {
            require(!certified, "driver attempted a second certificate for one store");
            record = *checked; certified = true; ++certificates;
        }
        if (invalidate || !stable || (previous && previous->epoch != epoch)) {
            record.reset(); certified = false;
        }
        ++ticks;
    }
    void clear() { invalidate = true; tick(); invalidate = false; tick(); }
    void interval(uint64_t load, unsigned ls, uint64_t store, unsigned ss) {
        d.set_io$$loadAddress(load); d.set_io$$loadSize(ls);
        d.set_io$$storeAddress(store); d.set_io$$storeSize(ss); tick();
        const bool expected = disjoint(load, ls, store, ss);
        require(bool(d.get_io$$disjoint()) == expected, "independent 65-bit physical byte interval mismatch");
        ++intervals; if (expected) ++disjointCases; else ++overlapCases;
    }
};

int main(int argc, char **argv) { try {
    Bench b; b.inject = argc > 1 && std::string(argv[1]) == "--inject-valid";
    Descriptor owner;
    b.tick({}, owner); b.tick(); // Unsolicited/late event cannot create tracking.
    b.tick(owner, owner); b.tick(); // Start and event on one edge must not bypass the start register.
    std::vector<Descriptor> malformed;
    auto add = [&](auto change) { auto c = owner; change(c); malformed.push_back(c); };
    add([](auto &c) { ++c.token.index; }); add([](auto &c) { ++c.token.tag; });
    add([](auto &c) { ++c.epoch; }); add([](auto &c) { c.virtualAddress += 4096; });
    add([](auto &c) { c.size = 2; }); add([](auto &c) { c.mask = 15; });
    add([](auto &c) { c.size = 4; }); add([](auto &c) { c.physicalAddress += 1; });
    add([](auto &c) { c.physicalAddress += 8; }); // Wrong preserved page offset.
    add([](auto &c) { c.physicalAddress = ram + ramBytes; });
    add([](auto &c) { c.physicalAddress = ram - 4096; });
    add([](auto &c) { c.physicalAddress |= 1ULL << 48; });
    add([](auto &c) { c.physicalAddress = UINT64_MAX - 3; });
    for (const auto &bad : malformed) { b.tick({}, bad); b.tick(); }
    b.tick({}, owner); b.tick(); b.tick();
    // Success plus retirement backpressure leaves the registered proof reusable.
    for (unsigned n = 0; n < 5; ++n) b.tick();
    b.clear(); // Matching late physical error / retirement / accepted recovery invalidate identically here.
    b.tick({}, owner); b.tick();
    // Invalidating edge dominates a valid capture.
    b.tick(owner); b.invalidate = true; b.tick({}, owner); b.invalidate = false; b.tick();
    // It also dominates a fresh start.
    b.invalidate = true; b.tick(owner); b.invalidate = false; b.tick();
    b.tick(owner); b.live = false; b.tick({}, owner); b.tick(); b.live = true;
    // Reused ROB index cannot accept the old tag, including the final 8-bit generation.
    for (uint64_t tag : {8ULL, 127ULL, 254ULL, 255ULL}) {
        auto next = owner; next.token.tag = tag;
        b.tick(next); b.tick({}, owner); b.tick(); b.tick({}, next); b.tick(); b.clear();
    }
    b.tick(owner); b.stable = false; b.tick({}, owner); b.stable = true; b.tick();
    b.tick(owner); ++b.epoch; b.tick({}, owner); b.tick();
    owner.epoch = b.epoch; b.tick(owner); b.tick({}, owner); b.tick();
    ++b.epoch; b.tick(); b.tick(); // Already certified proof expires with epoch change.
    b.epoch = UINT32_MAX; owner.epoch = b.epoch;
    b.tick(owner); b.tick({}, owner); b.tick(); b.clear();
    b.epoch = 0; owner.epoch = 0; b.tick(owner);
    auto staleWrap = owner; staleWrap.epoch = UINT32_MAX; b.tick({}, staleWrap); b.tick();
    b.tick({}, owner); b.tick(); b.clear();

    // Exercise shape rejection with a matching descriptor, so mismatch cannot mask the shape check.
    for (unsigned kind = 0; kind < 6; ++kind) {
        auto bad = owner;
        if (kind == 0) bad.size = 4;
        if (kind == 1) bad.mask = 15;
        if (kind == 2) { ++bad.virtualAddress; ++bad.physicalAddress; }
        if (kind == 3) { bad.virtualAddress += 4092; bad.physicalAddress = ram + ramBytes - 4; }
        if (kind == 4) {
            bad.virtualAddress = va + 4092; bad.physicalAddress = UINT64_MAX - 3;
        }
        if (kind == 5) bad.physicalAddress = ram | (1ULL << 48);
        b.tick(bad); b.tick({}, bad); b.tick(); b.clear();
    }
    for (unsigned size = 0; size < 4; ++size) {
        for (unsigned offset = 0; offset < 8; offset += 1u << size) {
            auto subword = owner; subword.virtualAddress += offset; subword.physicalAddress += offset;
            subword.size = size; subword.mask = lanes(subword.physicalAddress, size);
            b.tick(subword); b.tick({}, subword); b.tick(); b.clear();
        }
    }

    // Distinct virtual aliases map to identical software-selected PA bytes. VAs never enter comparison.
    for (unsigned ls = 0; ls < 4; ++ls) for (unsigned ss = 0; ss < 4; ++ss) {
        for (unsigned lo = 0; lo < 16; ++lo) for (unsigned so = 0; so < 16; ++so)
            b.interval(ram + lo, ls, ram + so, ss);
    }
    for (uint64_t base : std::array<uint64_t, 4>{0ULL, ram, 0x1000080010000ULL, UINT64_MAX - 15}) {
        for (unsigned size = 0; size < 4; ++size) {
            b.interval(base, size, base ^ (1ULL << 63), size);
            b.interval(base, size, base, size);
        }
    }
    // Endpoints above UINT64_MAX remain 65-bit intervals; they never wrap to address zero.
    b.interval(UINT64_MAX - 7, 3, 0, 3);
    b.interval(UINT64_MAX, 0, 0, 0);
    b.interval(UINT64_MAX - 3, 3, 0, 3); // Malformed unaligned transfer fails closed.
    std::mt19937_64 random(0x43414e4f4e494341ULL);
    for (unsigned n = 0; n < 10000; ++n) {
        uint64_t a = random(), c = n % 2 ? random() : a + (random() % 25) - 12;
        const unsigned as = random() % 4, cs = random() % 4;
        if (n % 3) { a -= a % (1u << as); c -= c % (1u << cs); }
        b.interval(a, as, c, cs);
    }
    require(b.certificates >= 8 && b.overlapCases && b.disjointCases, "tracker/interval coverage missing");
    std::cout << "CANONICAL_STORE_TRACKER_PASS ticks=" << b.ticks << " certificates=" << b.certificates
        << " intervals=" << b.intervals << "\n";
    return 0;
} catch (const std::exception &e) { std::cerr << "CANONICAL_STORE_TRACKER_FAIL " << e.what() << '\n'; return 1; } }
