#include "CanonicalStoreOwnerMapGsim.h"
#include "canonical_store_oracle.h"
#include <array>
#include "gsim_model_storage.h"
#include <iostream>
#include <optional>
#include <vector>
using namespace canonical_store_test;
#ifndef OWNER_MAP_ROWS
#define OWNER_MAP_ROWS 16
#endif

// The expected permission is an independent full-identity/lifecycle model. No
// candidate map bit, DUT ownerLive, or accepted completion feeds model state.
struct Row { Token token{}; unsigned kind = 0; bool live = false, pending = false; };
struct Edge {
    std::optional<Token> allocate, retire, complete;
    std::optional<Descriptor> start, checked;
    unsigned kind = 3;
    uint64_t clear = 0;
    bool exception = false, invalidate = false;
};
class Bench {
    GsimModelStorage<SCanonicalStoreOwnerMapGsim> storage;
    SCanonicalStoreOwnerMapGsim& d;
    std::array<Row, OWNER_MAP_ROWS> rows{};
    std::optional<Descriptor> record;
    bool certified = false;
public:
    uint32_t epoch = 11;
    Token memoryOwner{}, headOwner{};
    bool memoryProtected = true, headValid = true, headDone = false, stable = true;
    unsigned ticks = 0, certificates = 0, staleRejected = 0, preedgeInvalidations = 0;
    bool inject = false;
    const bool staged, reconstruct;
    uint64_t indexedTagXor = 0;
    Bench(bool stage, bool rebuild) : d(storage.get()), staged(stage), reconstruct(rebuild) {
        d.LOG_START = 1; d.activateAll();
        drive({}); d.set_reset(1); d.step(); d.resetAll(); d.step(); d.resetAll(); d.set_reset(0); tick();
    }
    void drive(const Edge &e) {
        d.set_io$$staged(staged); d.set_io$$reconstruct(reconstruct); d.set_io$$indexedTagXor(indexedTagXor);
        const auto a = e.allocate.value_or(Token{}), r = e.retire.value_or(Token{}), c = e.complete.value_or(Token{});
        const auto s = e.start.value_or(Descriptor{}), k = e.checked.value_or(Descriptor{});
        d.set_io$$allocate$$valid(e.allocate.has_value());
        d.set_io$$allocate$$bits$$index(a.index); d.set_io$$allocate$$bits$$tag(a.tag);
        d.set_io$$allocateClass(e.kind); d.set_io$$clear(e.clear);
        d.set_io$$start$$valid(e.start.has_value());
        d.set_io$$start$$bits$$origin$$token$$index(s.token.index);
        d.set_io$$start$$bits$$origin$$token$$tag(s.token.tag);
        d.set_io$$start$$bits$$origin$$epoch(s.epoch);
        d.set_io$$start$$bits$$virtualAddress(s.virtualAddress);
        d.set_io$$start$$bits$$size(s.size); d.set_io$$start$$bits$$mask(s.mask);
        d.set_io$$checked$$valid(e.checked.has_value());
        d.set_io$$checked$$bits$$origin$$token$$index(k.token.index);
        d.set_io$$checked$$bits$$origin$$token$$tag(k.token.tag);
        d.set_io$$checked$$bits$$origin$$epoch(k.epoch);
        d.set_io$$checked$$bits$$virtualAddress(k.virtualAddress);
        d.set_io$$checked$$bits$$physicalAddress(k.physicalAddress);
        d.set_io$$checked$$bits$$size(k.size); d.set_io$$checked$$bits$$mask(k.mask);
        d.set_io$$memoryProtected(memoryProtected); d.set_io$$headValid(headValid); d.set_io$$headDone(headDone);
        d.set_io$$memoryOwner$$index(memoryOwner.index); d.set_io$$memoryOwner$$tag(memoryOwner.tag);
        d.set_io$$headOwner$$index(headOwner.index); d.set_io$$headOwner$$tag(headOwner.tag);
        d.set_io$$retire$$valid(e.retire.has_value());
        d.set_io$$retire$$bits$$index(r.index); d.set_io$$retire$$bits$$tag(r.tag);
        d.set_io$$complete$$valid(e.complete.has_value());
        d.set_io$$complete$$bits$$index(c.index); d.set_io$$complete$$bits$$tag(c.tag);
        d.set_io$$exception(e.exception); d.set_io$$invalidate(e.invalidate);
        d.set_io$$stable(stable); d.set_io$$epoch(epoch);
    }
    void tick(const Edge &e = {}) {
        drive(e); d.step();
        const Row *ownerRow = record ? &rows.at(record->token.index) : nullptr;
        const bool live = record && memoryProtected && headValid && (!staged || !headDone) &&
            memoryOwner == record->token && headOwner == record->token && ownerRow->live && !ownerRow->pending &&
            ownerRow->token.index == record->token.index && (ownerRow->token.tag ^ indexedTagXor) == record->token.tag && ownerRow->kind == 3;
        const bool valid = live && certified && stable && record->epoch == epoch;
        const uint64_t expected = valid ? uint64_t(1) << record->token.index : 0;
        const std::string where = "cycle=" + std::to_string(ticks) + " ";
        require(bool(d.get_io$$ownerLive()) == live, where + "full owner relation mismatch");
        require(bool(d.get_io$$tracked()) == record.has_value(), where + "tracker lifetime mismatch");
        require(bool(d.get_io$$certificate$$valid()) == valid, where + "certificate authorization mismatch");
        require(uint64_t(d.get_io$$reference()) == expected, where + "old consumer map mismatch");
        const uint64_t candidate = d.get_io$$candidate() ^ (inject && valid ? uint64_t(1) << record->token.index : 0);
        if (inject && valid) std::cerr << "ACTUAL_CORRUPTION count=1 mode=sampled-candidate-map\n";
        require(candidate == expected, where + "candidate consumer map mismatch");
        if (valid) {
            require(d.get_io$$certificate$$bits$$origin$$token$$tag() == record->token.tag &&
                d.get_io$$certificate$$bits$$origin$$token$$index() == record->token.index &&
                d.get_io$$certificate$$bits$$physicalAddress() == record->physicalAddress,
                where + "certificate full identity or physical payload changed");
        }
        uint64_t expectedLive = 0, expectedPending = 0;
        for (unsigned i = 0; i < OWNER_MAP_ROWS; ++i) {
            if (rows[i].live) { expectedLive |= uint64_t(1) << i; require(rows[i].token.index == i, "model live invariant"); }
            if (rows[i].pending) expectedPending |= uint64_t(1) << i;
        }
        require(d.get_io$$live() == expectedLive && d.get_io$$pending() == expectedPending, where + "row priority mismatch");
        const auto previous = record;
        const bool invalidating = e.invalidate || (previous &&
            (((e.clear >> previous->token.index) & 1) ||
             (e.retire && *e.retire == previous->token) ||
             (e.complete && *e.complete == previous->token && (staged || e.exception))));
        if (valid && invalidating) ++preedgeInvalidations;
        if (previous && !live) { record.reset(); certified = false; }
        if (e.start) { require(!previous || !live, "illegal live-owner replacement in test"); record = e.start; certified = false; }
        if (e.checked && previous && live && sameDescriptor(*e.checked, *previous) && shape(*e.checked) &&
            stable && e.checked->epoch == epoch) {
            require(!certified, "test tried duplicate certification"); record = e.checked; certified = true; ++certificates;
        } else if (e.checked) ++staleRejected;
        if (invalidating || !stable || (previous && previous->epoch != epoch)) { record.reset(); certified = false; }
        for (unsigned i = 0; i < OWNER_MAP_ROWS; ++i) {
            if ((e.clear >> i) & 1) { rows[i].live = false; rows[i].pending = false; }
            if (e.retire && e.retire->index == i) rows[i].live = false;
        }
        if (e.start) rows.at(e.start->token.index).pending = false;
        if (e.allocate) rows.at(e.allocate->index) = {*e.allocate, e.kind, bool(e.kind & 1), true};
        ++ticks;
    }
    void start(Descriptor owner, unsigned kind = 3) {
        memoryOwner = headOwner = owner.token;
        Edge e; e.allocate = owner.token; e.kind = kind; tick(e);
        e = {}; e.start = owner; tick(e); tick();
    }
    void checked(Descriptor owner) { Edge e; e.checked = owner; tick(e); tick(); }
    void clear() { Edge e; e.invalidate = true; e.clear = ~uint64_t(0); tick(e); tick(); }
};

void runCase(bool staged, bool reconstruct, bool inject) {
    Bench b(staged, reconstruct); b.inject = inject;
    // High tag values are explicit boundary stimuli, not a claimed natural counter wrap.
    for (unsigned index = 0; index < OWNER_MAP_ROWS; ++index) {
        Descriptor owner; owner.token = {index, (uint64_t(1) << 63) + index};
        b.start(owner);
        auto old = owner; old.token.tag ^= uint64_t(1) << 63;
        b.checked(old); b.checked(owner);
        Edge e; e.retire = owner.token; e.allocate = Token{index, owner.token.tag + 73};
        b.tick(e); b.tick(); b.checked(owner); b.clear();
    }
    Descriptor owner; owner.token = {OWNER_MAP_ROWS - 1, UINT64_MAX};
    // All three indexed producer identity relations reject a bit-63-only mismatch.
    for (unsigned mismatch = 0; mismatch < 3; ++mismatch) {
        b.start(owner); b.checked(owner);
        if (mismatch == 0) b.memoryOwner.tag ^= uint64_t(1) << 63;
        if (mismatch == 1) b.headOwner.tag ^= uint64_t(1) << 63;
        if (mismatch == 2) b.indexedTagXor = uint64_t(1) << 63;
        b.tick(); b.tick(); b.indexedTagXor = 0; b.clear();
    }
    // Invalidating edges preserve old pre-edge permission and dominate capture/start.
    for (unsigned kind = 0; kind < 4; ++kind) {
        b.start(owner);
        Edge e; e.checked = owner;
        e.allocate = Token{0, 100 + kind}; // Concurrent rename with owner retirement/kill/event.
        if (kind == 0) e.invalidate = true;
        if (kind == 1) e.clear = uint64_t(1) << owner.token.index;
        if (kind == 2) e.retire = owner.token;
        if (kind == 3) { e.complete = owner.token; e.exception = true; }
        b.tick(e); b.tick(); b.checked(owner); b.clear();
    }
    b.start(owner); b.checked(owner);
    { Edge e; e.complete = owner.token; b.tick(e); b.tick(); }
    b.clear(); // Successful completion disposes only in staged mode.
    b.start(owner); b.checked(owner); b.headDone = true; b.tick(); b.tick(); b.headDone = false; b.clear();
    for (unsigned kind : {0U, 1U, 7U, 11U}) { b.start(owner, kind); b.checked(owner); b.clear(); }
    b.start(owner); b.checked(owner); b.stable = false; b.tick(); b.stable = true; b.tick(); b.clear();
    b.start(owner); b.checked(owner); ++b.epoch; b.tick(); b.tick(); b.clear();
    owner.epoch = b.epoch;
    // Match malformed start descriptors so the real shape check must reject them.
    for (unsigned kind = 0; kind < 6; ++kind) {
        auto bad = owner;
        if (kind == 0) bad.size = 4;
        if (kind == 1) bad.mask = 15;
        if (kind == 2) { ++bad.virtualAddress; ++bad.physicalAddress; }
        if (kind == 3) bad.physicalAddress += 8;
        if (kind == 4) bad.physicalAddress = ram + ramBytes;
        if (kind == 5) bad.physicalAddress |= uint64_t(1) << 48;
        b.start(bad); b.checked(bad); b.clear();
    }
    // A fresh start and checked callback on the same edge cannot certify the new record.
    { Edge e; e.allocate = owner.token; b.tick(e); }
    { Edge e; e.start = owner; e.checked = owner; b.tick(e); b.tick(); }
    b.checked(owner); b.clear();
    b.start(owner);
    { auto bad = owner; ++bad.epoch; b.checked(bad); }
    b.checked(owner); b.clear();
    { Edge e; e.allocate = owner.token; e.clear = uint64_t(1) << owner.token.index; e.invalidate = true; b.tick(e); b.tick(); }
    { Edge e; e.start = owner; e.checked = owner; e.invalidate = true; b.tick(e); b.tick(); }
    b.checked(owner); b.clear();
    require(b.certificates >= OWNER_MAP_ROWS + 5 && b.staleRejected >= OWNER_MAP_ROWS + 12 && b.preedgeInvalidations,
        "owner-map coverage incomplete");
    std::cout << "CANONICAL_OWNER_MAP_PASS rows=" << OWNER_MAP_ROWS << " staged=" << staged
        << " reconstruct=" << reconstruct << " ticks=" << b.ticks << " certificates=" << b.certificates << " rejected=" << b.staleRejected
        << " preedge_invalidations=" << b.preedgeInvalidations << '\n';
}
int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--mutate-map";
    for (bool staged : {false, true}) for (bool reconstruct : {false, true}) runCase(staged, reconstruct, inject);
    return 0;
} catch (const std::exception &e) { std::cerr << "CANONICAL_OWNER_MAP_FAIL " << e.what() << '\n'; return 1; } }
