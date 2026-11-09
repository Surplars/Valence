#include "FiveStageWordCache.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef CACHE_BYTES
#define CACHE_BYTES 512
#endif
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
static constexpr unsigned WORD = DUT_XLEN / 8, LINE = 64;
#ifndef CACHE_BASE
#define CACHE_BASE 0x80000000ULL
#endif
#ifndef CACHE_WINDOW
#define CACHE_WINDOW 0x10000000ULL
#endif
static constexpr uint64_t BASE = CACHE_BASE, MASK = DUT_XLEN == 64 ? UINT64_MAX : UINT32_MAX;
static void need(bool v, const char *s) { if (!v) throw std::runtime_error(s); }
struct Backend {
    uint64_t address, data; unsigned mask, beats, beat = 0; bool write;
};
struct Test {
    SFiveStageWordCache d;
    std::vector<uint8_t> memory = std::vector<uint8_t>(65536);
    std::optional<Backend> backend;
    std::optional<std::array<uint64_t, 7>> heldRequest;
    std::optional<std::array<uint64_t, 2>> heldResponse;
    uint64_t cycle = 0, requests = 0, hits = 0, misses = 0, unownedChanges = 0;
    unsigned errorBeat = 999; bool invalidateFill = false;
    bool sideEffectOnError = false;
    bool responseReady = false;
    Test() {
        for (unsigned j = 0; j < memory.size(); ++j) memory[j] = (j * 73 + 19) ^ ((j >> 8) * 37) ^ ((j >> 13) * 11);
        d.set_reset(1); d.set_io$$request$$valid(0); d.set_io$$response$$ready(0);
        d.set_io$$memory$$request$$ready(0); d.set_io$$memory$$response$$valid(0);
        d.set_io$$invalidate(0); d.step(); d.step(); d.set_reset(0);
        d.set_io$$request$$bits$$noAllocate(0);
    }
    uint64_t load(uint64_t a) {
        uint64_t v = 0;
        for (unsigned j = 0; j < WORD; ++j) v |= uint64_t(memory[(a - BASE + j) % memory.size()]) << (8 * j);
        return v;
    }
    void step(bool inv = false) {
        bool ready = !backend && cycle % 4 != 1;
        bool valid = backend && cycle % 5 != 2;
        bool error = backend && backend->beat == errorBeat;
        uint64_t value = backend ? load(backend->address + backend->beat * WORD) : 0;
        d.set_io$$memory$$request$$ready(ready); d.set_io$$memory$$response$$valid(valid);
        d.set_io$$memory$$response$$bits$$data(value); d.set_io$$memory$$response$$bits$$error(error);
        d.set_io$$memory$$response$$bits$$last(backend && backend->beat + 1 == backend->beats);
        d.set_io$$invalidate(inv || (invalidateFill && backend && backend->beat == 1));
        d.step(); ++cycle;
        hits += d.get_io$$hit(); misses += d.get_io$$miss();
        std::array<uint64_t, 7> req{d.get_io$$memory$$request$$bits$$address(),
            d.get_io$$memory$$request$$bits$$write(), d.get_io$$memory$$request$$bits$$data(),
            d.get_io$$memory$$request$$bits$$mask(), d.get_io$$memory$$request$$bits$$beats(),
            d.get_io$$memory$$request$$bits$$size(), d.get_io$$memory$$request$$bits$$byteOffset()};
        if (heldRequest) need(d.get_io$$memory$$request$$valid() && req == *heldRequest,
            "cache backend offer changed under backpressure");
        heldRequest.reset();
        if (d.get_io$$memory$$request$$valid() && !ready) heldRequest = req;
        std::array<uint64_t, 2> rsp{d.get_io$$response$$bits$$data(), d.get_io$$response$$bits$$error()};
#ifdef CACHE_METADATA
        if (d.get_io$$response$$valid() && !d.get_io$$response$$bits$$error()) {
            // RISC-V parcel prefixes: independently enumerate the 32-bit
            // forms and compressed quadrants from the returned raw bytes.
            unsigned classes=0;
            for(unsigned lane=0;lane<4;++lane) {
                unsigned prefix=(rsp[0]>>(16*lane))&31;
                if((prefix&3)!=3) classes|=1U<<(lane+4);
                switch(prefix) {case 3:case 7:case 11:case 15:case 19:case 23:case 27:
                    classes|=1U<<lane;break;default:break;}
            }
            need(d.get_io$$response$$bits$$parcelClasses()==(classes^unsigned(classInject)),
                "independent cached parcel prefix oracle");
        }
#endif
        if (heldResponse) need(d.get_io$$response$$valid() && rsp == *heldResponse,
            "cache CPU response changed under backpressure");
        heldResponse.reset();
        if (d.get_io$$response$$valid() && !responseReady) heldResponse = rsp;
        if (valid && d.get_io$$memory$$response$$ready()) {
            if (backend->write && (!error || sideEffectOnError)) for (unsigned j = 0; j < WORD; ++j)
                if (backend->mask >> j & 1) memory[(backend->address - BASE + j) % memory.size()] = backend->data >> (8 * j);
            if (++backend->beat == backend->beats) backend.reset();
        }
        if (ready && d.get_io$$memory$$request$$valid()) {
            need(!backend, "cache duplicated backend owner");
            need(req[4] == 1 || req[4] == LINE / WORD, "cache emitted an illegal burst length");
            need(!(req[0] & (WORD - 1)), "cache emitted an unaligned beat");
            backend = Backend{req[0], req[2], unsigned(req[3]), unsigned(req[4]), 0, bool(req[1])}; ++requests;
        }
    }
    std::array<uint64_t, 2> transact(uint64_t address, bool write = false, uint64_t data = 0,
                                   unsigned mask = WORD == 8 ? 255 : 15, bool noAllocate = false,
                                   int invalidateCycle = -1) {
        d.set_io$$request$$valid(1); d.set_io$$request$$bits$$address(address);
        d.set_io$$request$$bits$$write(write); d.set_io$$request$$bits$$size(WORD == 8 ? 3 : 2);
        d.set_io$$request$$bits$$data(data); d.set_io$$request$$bits$$mask(mask);
        d.set_io$$request$$bits$$noAllocate(noAllocate);
        responseReady = false; d.set_io$$response$$ready(0);
        bool accepted = false;
        for (unsigned n = 0; n < 200; ++n) {
            if (accepted) {
                d.set_io$$request$$valid(0);
                // Unoffered inputs are unconstrained. Change banks, tags and
                // write payload while the real owner waits or holds its reply.
                d.set_io$$request$$bits$$address((BASE + ((cycle * 0x1040) ^ 0x8000)) & MASK);
                d.set_io$$request$$bits$$write(cycle & 1);
                d.set_io$$request$$bits$$data(~cycle & MASK);
                d.set_io$$request$$bits$$mask(cycle & ((1U << WORD) - 1));
                ++unownedChanges;
            }
            responseReady = accepted && cycle % 3 == 0; d.set_io$$response$$ready(responseReady);
            step(int(n) == invalidateCycle);
            bool response = d.get_io$$response$$valid() && responseReady;
            if (!accepted && d.get_io$$request$$ready()) accepted = true;
            if (response) {
                d.set_io$$request$$valid(0); d.set_io$$response$$ready(0); responseReady = false;
                return {d.get_io$$response$$bits$$data(), d.get_io$$response$$bits$$error()};
            }
        }
        throw std::runtime_error("cache transaction bounded timeout");
    }
    void invalidate() { d.set_io$$request$$valid(0); d.set_io$$response$$ready(0); responseReady = false; step(true); }
};
int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject";
    Test t;
    auto checkRead = [&](uint64_t a) { auto r = t.transact(a); need(!r[1] && r[0] == (t.load(a & ~(WORD - 1ULL)) ^ uint64_t(inject)),
        "cache independent byte-memory oracle mismatch"); };
    checkRead(BASE + 16); uint64_t reads = t.requests; checkRead(BASE + 16);
    need(t.requests == reads + (CACHE_BYTES ? 0 : 1), "cache hit/disabled mode did not match contract");
    // A presence bit captured at admission must not outlive invalidation at
    // that edge or the immediately following lookup edge. Change backing RAM
    // so an accidentally retained hit cannot pass a payload-only comparison.
    for (int edge : {0, 1}) {
        checkRead(BASE + 16); reads = t.requests;
        t.memory[16] ^= uint8_t(0x35 + edge);
        auto invalidated = t.transact(BASE + 16, false, 0, WORD == 8 ? 255 : 15, false, edge);
        need(!invalidated[1] && invalidated[0] == t.load(BASE + 16),
            "admission/lookup invalidation exposed stale cached bytes");
        need(t.requests == reads + 1, "admission/lookup invalidation retained old presence");
    }
    // M-mode may have filled this line before a narrower PMP context forced a scalar uncached write.
    auto bypassWrite = t.transact(BASE + 16, true, 0x1111222233334444ULL & MASK, WORD == 8 ? 255 : 15, true);
    need(!bypassWrite[1] && t.load(BASE + 16) == (0x1111222233334444ULL & MASK),
        "PMP boundary bypass write did not wait for real memory ack");
    reads = t.requests; checkRead(BASE + 16);
    need(t.requests == reads + 1, "PMP boundary bypass write left an old cached line valid");
    // Common high bits are omitted only AFTER the exact cacheable-window admission.
    // Addresses differing solely in those bits must bypass and preserve the live line.
    reads = t.requests;
    uint64_t outside = BASE ^ (1ULL << (DUT_XLEN - 1));
    checkRead(outside + 16); checkRead(outside + 16);
    need(t.requests == reads + 2, "fixed-prefix alias was incorrectly cached");
    reads = t.requests; checkRead(BASE + 16);
    need(t.requests == reads + (CACHE_BYTES ? 0 : 1), "outside-window bypass damaged live cached line");
    reads = t.requests;
    checkRead(BASE + CACHE_WINDOW); checkRead(BASE + CACHE_WINDOW);
    checkRead(BASE - WORD); checkRead(BASE - WORD);
    need(t.requests == reads + 4, "exclusive cache-window boundary was cached");
    checkRead(BASE + CACHE_WINDOW - WORD); reads = t.requests;
    checkRead(BASE + CACHE_WINDOW - WORD);
    need(t.requests == reads + (CACHE_BYTES ? 0 : 1), "last legal window line failed to cache");
    if (CACHE_BYTES && CACHE_WINDOW > CACHE_BYTES + 16ULL) {
        checkRead(BASE + 16); reads = t.requests;
        checkRead(BASE + CACHE_BYTES + 16); checkRead(BASE + 16);
        need(t.requests == reads + 2, "varying tag bits aliased two legal cache lines");
    }
    auto r = t.transact(BASE + 16, true, 0xfedcba9876543210ULL & MASK, 5);
    need(!r[1], "successful partial write failed"); checkRead(BASE + 16);
    auto before = t.load(BASE + 16); t.errorBeat = 0;
    r = t.transact(BASE + 16, true, 0, WORD == 8 ? 255 : 15);
    need(r[1] && t.load(BASE + 16) == before, "errored store changed memory");
    t.errorBeat = 999; checkRead(BASE + 16);
    // A subordinate can change RAM before returning a B error. A stale successful cache hit
    // afterwards would hide the real memory value. The fault still must reach the CPU.
    t.errorBeat = 0; t.sideEffectOnError = true;
    r = t.transact(BASE + 16, true, 0x123456789abcdef0ULL & MASK);
    need(r[1] && t.load(BASE + 16) == (0x123456789abcdef0ULL & MASK), "late write-error setup failed");
    t.errorBeat = 999; t.sideEffectOnError = false; reads = t.requests;
    checkRead(BASE + 16);
    need(t.requests == reads + 1, "late AXI write error left stale cached payload valid");
    t.invalidate(); t.errorBeat = CACHE_BYTES ? 3 : 0;
    r = t.transact(BASE + 16); need(r[1], "middle/last burst error was not propagated");
    t.errorBeat = 999; reads = t.requests; checkRead(BASE + 16);
    need(t.requests == reads + 1, "failed refill incorrectly installed a line");
    t.invalidate(); t.invalidateFill = true; checkRead(BASE + 16); t.invalidateFill = false;
    reads = t.requests; checkRead(BASE + 16);
    need(t.requests == reads + 1, "invalidation during refill resurrected a line");
    checkRead(BASE + (CACHE_BYTES ? CACHE_BYTES : 512) + 16); checkRead(BASE + 16);
    reads = t.requests; checkRead(0x10000000); checkRead(0x10000000);
    need(t.requests == reads + 2, "MMIO was cached");
    checkRead(BASE + 16);

    // Touch every real set/bank, then revisit in reverse. This checks the
    // entire bank-selection space, independently of the DUT's tag encoding.
    if (CACHE_BYTES && CACHE_WINDOW >= CACHE_BYTES) {
        for (unsigned offset = 0; offset < CACHE_BYTES; offset += LINE) checkRead(BASE + offset + 16);
        reads = t.requests;
        for (unsigned offset = CACHE_BYTES; offset; offset -= LINE) checkRead(BASE + offset - LINE + 16);
        need(t.requests == reads, "banked tag sweep lost or aliased an installed set");
    }
#ifdef CACHE_FLOW
    // A warmed IF bank must sustain one real accepted request/response per cycle, not a host hit oracle.
    unsigned admitted = 0, returned = 0, elapsed = 0;
    std::vector<uint64_t> acceptedAddresses;
    reads = t.requests;
    t.responseReady = true; t.d.set_io$$response$$ready(1);
    for (; elapsed < 40 && returned < 16; ++elapsed) {
        bool valid = admitted < 16;
        uint64_t address = BASE + ((uint64_t(admitted) * 0x1040) % CACHE_BYTES) + 16;
        t.d.set_io$$request$$valid(valid); t.d.set_io$$request$$bits$$address(address);
        t.d.set_io$$request$$bits$$write(0); t.step();
        if (valid && t.d.get_io$$request$$ready()) { acceptedAddresses.push_back(address); ++admitted; }
        if (t.d.get_io$$response$$valid()) {
            need(returned < acceptedAddresses.size(), "IF response has no independently accepted address");
            need(!t.d.get_io$$response$$bits$$error() &&
                t.d.get_io$$response$$bits$$data() == t.load(acceptedAddresses[returned]),
                "pipelined IF hit data mismatch"); ++returned;
        }
    }
    need(admitted == 16 && returned == 16 && elapsed == 17 && t.requests == reads,
        "IF cache inserted avoidable hit bubbles or duplicated an owner");
    t.d.set_io$$request$$valid(0); t.d.set_io$$response$$ready(0); t.responseReady = false;
#endif
    // Give adjacent sets different full-address tags, then require all hits.
    // Correct data alone cannot hide a wrong-bank tag miss and refill.
    if (CACHE_BYTES && CACHE_WINDOW >= 3ULL * CACHE_BYTES) {
        std::vector<uint64_t> installed;
        reads = t.requests; uint64_t expectedMisses = 0;
        for (unsigned offset = 0; offset < CACHE_BYTES; offset += LINE) {
            const uint64_t replacement = (offset / LINE) % 3ULL;
            uint64_t address = BASE + offset + replacement * CACHE_BYTES;
            expectedMisses += replacement != 0;
            checkRead(address); installed.push_back(address);
        }
        need(t.requests == reads + expectedMisses, "different full-address tags were incorrectly accepted as hits");
        reads = t.requests;
        for (auto address = installed.rbegin(); address != installed.rend(); ++address) checkRead(*address);
        need(t.requests == reads, "different full-address tags were lost across cache banks");
    }
    t.d.set_reset(1); t.d.set_io$$request$$valid(0); t.d.set_io$$response$$ready(0); t.responseReady = false;
    t.d.set_io$$memory$$request$$ready(0); t.d.set_io$$memory$$response$$valid(0);
    t.d.step(); t.d.step(); t.d.set_reset(0);
    reads = t.requests; checkRead(BASE + 16);
    need(t.requests == reads + 1, "warm reset exposed old valid cache metadata");
    std::mt19937_64 random(0xa110c);
    for (unsigned j = 0; j < 1000; ++j) {
        uint64_t a = BASE + (random() % (8192 / WORD)) * WORD;
        if (j % 7 == 0) { auto v = t.transact(a, true, random() & MASK, random() & ((1U << WORD) - 1));
            need(!v[1], "random write failed"); }
        else checkRead(a);
        if (j % 97 == 0) t.invalidate();
    }
    need(t.unownedChanges > 100, "cache unowned-input variation coverage missing");
    std::cout << "FIVE_STAGE_CACHE_PASS bytes=" << CACHE_BYTES << " xlen=" << DUT_XLEN
        << " requests=" << t.requests << " hits=" << t.hits << " misses=" << t.misses
        << " unowned_input_changes=" << t.unownedChanges
        << " partial_store_error_refill_error_stale_fill_mmio_backpressure_warm_reset_window_alias_admission_invalidate=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
