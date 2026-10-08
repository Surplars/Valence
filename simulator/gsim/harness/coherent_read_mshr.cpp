#include "CoherentReadMshrGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#ifndef READ_MSHRS
#define READ_MSHRS 2
#endif
#ifndef CACHE_LINES
#define CACHE_LINES 512
#endif
#ifndef CACHE_WAYS
#define CACHE_WAYS 2
#endif
#ifndef CACHE_BASE
#define CACHE_BASE 0x80010000ULL
#endif
static constexpr uint64_t base = CACHE_BASE;
static constexpr unsigned releaseSource = READ_MSHRS == 1 ? 0 : READ_MSHRS;
static bool injectMismatch = false;
static void check(bool good, const char *message) { if (!good) throw std::runtime_error(message); }
struct Request { uint64_t address; bool write = false; uint64_t data = 0; unsigned mask = 255; bool uncached = false; };
struct Expected { uint64_t data; bool error; };
struct Acquire { uint64_t address, due; unsigned source, sink, beat = 0; bool error, grantDone = false; };
struct Ack { uint64_t due; unsigned source; };
struct Test {
    SCoherentReadMshrGsim d;
    std::map<uint64_t, uint64_t> backing, architectural;
    std::map<unsigned, Acquire> acquires;
    std::deque<Ack> releaseAcks;
    std::deque<Expected> expected;
    std::deque<Expected> bypassReplies;
    std::optional<unsigned> grant;
    std::optional<Request> request;
    std::optional<std::tuple<uint64_t, bool, bool>> stalledCpu;
    std::optional<std::tuple<unsigned, unsigned, uint64_t, uint64_t>> stalledC;
    uint64_t cycles = 0, accepted = 0, returned = 0, aCount = 0, releaseCount = 0, probeCount = 0;
    uint64_t peakAcquires = 0, overlapReleases = 0, probeStalls = 0, baseline = 0;
    uint64_t denyLine = ~0ULL, probeAddress = 0;
    bool blockCpu = false, forceReady = false, probing = false, probeAccepted = false, probeDone = false;
    bool probeAfterAck = false;
    uint64_t autoProbeOffset = 0;
    unsigned cBeat = 0, cOpcode = 0, cSource = 0, lastProbeOpcode = 0, lastProbeParam = 0;
    uint64_t bypassCount = 0;
    uint64_t cAddress = 0;
    static uint64_t initial(uint64_t address) { return 0x912345678abcdef0ULL ^ address * 0x100100101ULL; }
    uint64_t memory(uint64_t address) {
        backing.try_emplace(address, initial(address));
        architectural.try_emplace(address, backing.at(address));
        return backing.at(address);
    }
    static uint64_t merge(uint64_t old, uint64_t value, unsigned mask) {
        for (unsigned b = 0; b < 8; ++b) if (mask & (1U << b))
            old = (old & ~(0xffULL << (8*b))) | (value & (0xffULL << (8*b)));
        return old;
    }
    void tick() {
        const bool ar = forceReady || cycles % 7 != 2;
        const bool cr = forceReady || cycles % 11 < 7;
        const bool er = forceReady || cycles % 5 != 1;
        const bool cpuReady = !blockCpu && (forceReady || cycles % 9 < 6);
        if (!grant && (releaseAcks.empty() || releaseAcks.front().due > cycles)) {
            for (auto it = acquires.rbegin(); it != acquires.rend(); ++it)
                if (!it->second.grantDone && it->second.due <= cycles) { grant = it->first; break; }
        }
        const bool ack = !grant && !releaseAcks.empty() && releaseAcks.front().due <= cycles;
        const bool dv = grant || ack;
        d.set_io$$tl$$a$$ready(ar); d.set_io$$tl$$c$$ready(cr); d.set_io$$tl$$e$$ready(er);
        const bool bValid = probing && !probeAccepted;
        const bool downstreamReady = cycles % 3 != 0;
        const bool downstreamValid = !bypassReplies.empty();
        d.set_io$$tl$$b$$valid(bValid);
        d.set_io$$tl$$b$$bits$$address(probeAddress);
        d.set_io$$tl$$d$$valid(dv);
        if (grant) {
            const auto &g = acquires.at(*grant);
            d.set_io$$tl$$d$$bits$$opcode(5); d.set_io$$tl$$d$$bits$$source(g.source);
            d.set_io$$tl$$d$$bits$$sink(g.sink); d.set_io$$tl$$d$$bits$$param(0);
            d.set_io$$tl$$d$$bits$$data(memory(g.address + 8*g.beat) ^ uint64_t(injectMismatch));
            d.set_io$$tl$$d$$bits$$denied(g.error && g.beat == 7);
        } else if (ack) {
            d.set_io$$tl$$d$$bits$$opcode(6); d.set_io$$tl$$d$$bits$$source(releaseAcks.front().source);
            d.set_io$$tl$$d$$bits$$sink(0); d.set_io$$tl$$d$$bits$$param(0);
            d.set_io$$tl$$d$$bits$$data(0); d.set_io$$tl$$d$$bits$$denied(0);
        }
        d.set_io$$upstream$$response$$ready(cpuReady);
        d.set_io$$upstream$$request$$valid(bool(request));
        if (request) {
            d.set_io$$upstream$$request$$bits$$address(request->address);
            d.set_io$$upstream$$request$$bits$$write(request->write);
            d.set_io$$upstream$$request$$bits$$data(request->data);
            d.set_io$$upstream$$request$$bits$$mask(request->mask);
            d.set_io$$upstream$$request$$bits$$uncached(request->uncached);
        }
        d.set_io$$downstream$$request$$ready(downstreamReady);
        d.set_io$$downstream$$response$$valid(downstreamValid);
        d.set_io$$downstream$$response$$bits$$data(bypassReplies.empty() ? 0 : bypassReplies.front().data);
        d.set_io$$downstream$$response$$bits$$error(0);
        d.step(); ++cycles;
        const auto cpu = std::make_tuple(uint64_t(d.get_io$$upstream$$response$$bits$$data()),
            bool(d.get_io$$upstream$$response$$bits$$error()), bool(d.get_io$$upstream$$response$$bits$$pageFault()));
        if (stalledCpu) check(d.get_io$$upstream$$response$$valid() && cpu == *stalledCpu, "stalled CPU response changed");
        stalledCpu = d.get_io$$upstream$$response$$valid() && !cpuReady ? std::optional{cpu} : std::nullopt;
        const auto c = std::make_tuple(unsigned(d.get_io$$tl$$c$$bits$$opcode()),
            unsigned(d.get_io$$tl$$c$$bits$$source()), uint64_t(d.get_io$$tl$$c$$bits$$address()),
            uint64_t(d.get_io$$tl$$c$$bits$$data()));
        if (stalledC) check(d.get_io$$tl$$c$$valid() && c == *stalledC, "stalled C owner/payload changed");
        stalledC = d.get_io$$tl$$c$$valid() && !cr ? std::optional{c} : std::nullopt;
        if (request && d.get_io$$upstream$$request$$ready()) {
            const auto q = *request;
            if ((q.write && !d.get_io$$hit()) || q.uncached)
                check(expected.empty(), "barrier accepted before earlier CPU replies");
            memory(q.address);
            const bool error = !q.uncached && (q.address & ~63ULL) == denyLine && d.get_io$$miss();
            expected.push_back({q.write ? 0 : architectural.at(q.address), error});
            if (q.write && !error) architectural[q.address] = merge(architectural.at(q.address), q.data, q.mask);
            ++accepted; request.reset();
        }
        if (d.get_io$$upstream$$response$$valid() && cpuReady) {
            check(!expected.empty(), "unowned CPU response");
            check(std::get<1>(cpu) == expected.front().error && !std::get<2>(cpu), "CPU response error owner mismatch");
            if (!expected.front().error) check(std::get<0>(cpu) == expected.front().data, "CPU independent data mismatch");
            expected.pop_front(); ++returned;
        }
        if (downstreamValid && d.get_io$$downstream$$response$$ready()) bypassReplies.pop_front();
        if (d.get_io$$downstream$$request$$valid() && downstreamReady) {
            ++bypassCount;
            const uint64_t a = d.get_io$$downstream$$request$$bits$$address();
            const bool write = d.get_io$$downstream$$request$$bits$$write();
            uint64_t value = memory(a);
            if (write) backing[a] = merge(value, d.get_io$$downstream$$request$$bits$$data(), d.get_io$$downstream$$request$$bits$$mask());
            bypassReplies.push_back({write ? 0 : value, false});
        }
        if (d.get_io$$tl$$a$$valid() && ar) {
            const unsigned source = d.get_io$$tl$$a$$bits$$source();
            check(d.get_io$$tl$$a$$bits$$opcode() == 6 && d.get_io$$tl$$a$$bits$$size() == 6 &&
                d.get_io$$tl$$a$$bits$$param() == 1, "Acquire control mismatch");
            check(!acquires.count(source), "live acquire source reused");
            const uint64_t a = d.get_io$$tl$$a$$bits$$address();
            const unsigned sinks = READ_MSHRS == 1 ? 2 : READ_MSHRS;
            const unsigned sink = (source + 1) % sinks;
            for (const auto &[id, g] : acquires) check(g.sink != sink, "manager sink collision");
            acquires.emplace(source, Acquire{a, cycles + 32 + (aCount % 4 == 0 ? 15U : 0U), source, sink, 0, a == denyLine});
            ++aCount; peakAcquires = std::max(peakAcquires, uint64_t(acquires.size()));
        }
        if (dv && d.get_io$$tl$$d$$ready()) {
            if (grant) {
                auto &g = acquires.at(*grant);
                if (++g.beat == 8) { g.grantDone = true; grant.reset(); }
            } else releaseAcks.pop_front();
        }
        if (d.get_io$$tl$$e$$valid() && er) {
            const unsigned sink = d.get_io$$tl$$e$$bits$$sink();
            auto it = std::find_if(acquires.begin(), acquires.end(), [&](const auto &g) { return g.second.sink == sink; });
            check(it != acquires.end() && it->second.grantDone, "GrantAck lost sink owner");
            if (probeAfterAck) {
                check(!probing, "test probe owner occupied");
                probing = true; probeAccepted = probeDone = false; probeAddress = it->second.address + autoProbeOffset; probeAfterAck = false;
            }
            acquires.erase(it);
        }
        if (probing && !probeAccepted) {
            if (bValid && d.get_io$$tl$$b$$ready()) probeAccepted = true;
            else if (bValid) ++probeStalls;
        }
        if (d.get_io$$tl$$c$$valid() && cr) {
            const unsigned op = std::get<0>(c), source = std::get<1>(c);
            const uint64_t address = std::get<2>(c);
            if (!cBeat) { cOpcode = op; cSource = source; cAddress = address; }
            check(op == cOpcode && source == cSource && address == cAddress && d.get_io$$tl$$c$$bits$$size() == 6,
                "C burst interleaved or changed control");
            check(op == 4 || op == 5 || op == 6 || op == 7, "unexpected C opcode");
            if (op == 5 || op == 7) {
                const uint64_t a = address + 8*cBeat; memory(a);
                check(std::get<3>(c) == architectural.at(a), "dirty snapshot mismatch");
                backing[a] = std::get<3>(c);
            }
            if (op == 4 || op == 6 || cBeat == 7) {
                if (op >= 6) {
                    check(source == releaseSource, "release source overlapped acquire owner");
                    releaseAcks.push_back({cycles + 5, source}); ++releaseCount;
                    overlapReleases += !acquires.empty();
                } else {
                    check(probing && probeAccepted && address == probeAddress && source == 7, "ProbeAck owner mismatch");
                    lastProbeOpcode = op; lastProbeParam = d.get_io$$tl$$c$$bits$$param();
                    probeDone = true; probing = false; ++probeCount;
                }
                cBeat = 0;
            } else ++cBeat;
        }
    }
    Test() {
        d.set_io$$upstream$$request$$valid(0); d.set_io$$upstream$$request$$bits$$atomic(0);
        d.set_io$$upstream$$request$$bits$$atomicOp(0); d.set_io$$upstream$$request$$bits$$virtualized(0);
        d.set_io$$upstream$$request$$bits$$uncached(0); d.set_io$$upstream$$request$$bits$$size(3);
        d.set_io$$upstream$$request$$bits$$address(base); d.set_io$$upstream$$request$$bits$$mask(255);
        d.set_io$$upstream$$request$$bits$$write(0); d.set_io$$upstream$$request$$bits$$data(0);
        d.set_io$$tl$$b$$bits$$opcode(6); d.set_io$$tl$$b$$bits$$param(2); d.set_io$$tl$$b$$bits$$size(6);
        d.set_io$$tl$$b$$bits$$source(7); d.set_io$$tl$$b$$bits$$mask(255); d.set_io$$tl$$b$$bits$$data(0);
        d.set_io$$tl$$d$$bits$$opcode(5); d.set_io$$tl$$d$$bits$$source(0); d.set_io$$tl$$d$$bits$$sink(0);
        d.set_io$$tl$$d$$bits$$size(6); d.set_io$$tl$$d$$bits$$param(0); d.set_io$$tl$$d$$bits$$data(0);
        d.set_io$$tl$$d$$bits$$denied(0); d.set_io$$tl$$d$$bits$$corrupt(0);
        d.set_io$$downstream$$response$$bits$$pageFault(0); d.set_io$$flushRequest(0);
        d.set_reset(1); tick(); tick(); d.set_reset(0);
    }
    template<class Predicate> void until(Predicate done, const char *message, unsigned limit = 200000) {
        for (unsigned n = 0; !done(); ++n) { check(n < limit, message); tick(); }
    }
    void offer(Request q, bool wait = true) {
        check(!request, "test request overwrite"); request = q;
        until([&] { return !request; }, "CPU request deadlock");
        if (wait) drain();
    }
    void drain() { until([&] { return expected.empty() && !request; }, "CPU response deadlock"); }
    void stream(unsigned first, unsigned count, bool write = false) {
        for (unsigned n = 0; n < count; ++n) offer({base + 64ULL*(first+n), write, 0xdead000000000000ULL ^ (first+n)}, false);
        drain();
    }
    void flush() {
        d.set_io$$flushRequest(1);
        until([&] { return d.get_io$$flushDone(); }, "dirty flush deadlock");
        d.set_io$$flushRequest(0); tick();
        for (auto [a, value] : architectural) check(backing.at(a) == value, "flush lost dirty backing data");
    }
    void coordinatedReset() {
        // Accepted pre-reset traffic is discarded by BOTH endpoints. Backing
        // memory survives; dirty cache-only data has no reset-persistence promise.
        d.set_io$$upstream$$request$$valid(0); d.set_io$$upstream$$response$$ready(0);
        d.set_io$$tl$$a$$ready(0); d.set_io$$tl$$b$$valid(0); d.set_io$$tl$$c$$ready(0);
        d.set_io$$tl$$d$$valid(0); d.set_io$$tl$$e$$ready(0);
        d.set_io$$downstream$$request$$ready(0); d.set_io$$downstream$$response$$valid(0);
        d.set_io$$flushRequest(0); d.set_reset(1); d.step(); d.step(); d.set_reset(0); cycles += 2;
        acquires.clear(); releaseAcks.clear(); expected.clear(); bypassReplies.clear();
        grant.reset(); request.reset(); stalledCpu.reset(); stalledC.reset();
        probing = probeAccepted = probeDone = probeAfterAck = blockCpu = false;
        cBeat = 0; architectural = backing;
    }
    void probe(uint64_t address) {
        check(!probing, "test probe overwrite"); probing = true; probeAccepted = probeDone = false; probeAddress = address;
        until([&] { return probeDone; }, "probe deadlock");
    }
};
int main(int argc, char **argv) {
    injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    try {
#ifdef COMPACT_TAG_TEST
        // Addresses intentionally share every retained tag/index bit. The
        // independent backing model distinguishes all64 address bits.
        Test aliases;
        aliases.offer({base, true, 0x0102030405060708ULL});
        const uint64_t highAlias = base | (1ULL << 40);
        const auto acquireBefore = aliases.aCount;
        aliases.probe(highAlias);
        check(aliases.lastProbeOpcode == 4 && aliases.lastProbeParam == 5,
            "out-of-aperture B aliased dirty resident permission/data");
        aliases.offer({base});
        check(aliases.aCount == acquireBefore, "high-alias probe invalidated low resident");
        const auto bypassBefore = aliases.bypassCount;
        aliases.offer({highAlias});
        aliases.offer({highAlias, true, 0xffeeddccbbaa9988ULL});
        aliases.offer({base});
        check(aliases.bypassCount == bypassBefore + 2 && aliases.aCount == acquireBefore,
            "high-alias CPU access failed full-width bypass qualification");
        const uint64_t bytes = std::max<uint64_t>(16384, CACHE_LINES*256ULL);
        aliases.offer({base + bytes - 8});
        const auto edgeBypass = aliases.bypassCount;
        aliases.offer({base - 8}); aliases.offer({base + bytes});
        check(aliases.bypassCount == edgeBypass + 2, "aperture edge bypass mismatch");
        // Dirty releases from both sides of4GiB must retain exact addresses.
        Test crossing;
        crossing.offer({base, true, 0xaabbccddeeff0099ULL});
        crossing.offer({base + 65536, true, 0x1122334455667788ULL});
        crossing.flush();
        check(crossing.backing.at(base) == 0xaabbccddeeff0099ULL &&
            crossing.backing.at(base+65536) == 0x1122334455667788ULL,
            "compact victim reconstruction lost high address bit");
#endif
        Test hits; hits.offer({base}); hits.forceReady = true;
        const auto hitStart = hits.cycles;
        for (unsigned n = 0; n < 16; ++n) hits.offer({base + 8ULL*(n % 8)}, false);
        hits.drain();
        check(hits.cycles - hitStart == 17, "read-hit one-cycle latency / II1 regression");
        const auto storeStart = hits.cycles;
        for (unsigned n = 0; n < 16; ++n)
            hits.offer({base, true, 0x9876543210abcdefULL ^ n, 1U << (n % 8)}, false);
        hits.drain();
        check(hits.cycles - storeStart == 17, "store-hit one-cycle latency / II1 regression");
        // All seven responses remain owned while byte-strobed writes change
        // the resident word. Each earlier read must retain its own version.
        hits.blockCpu = true;
        hits.offer({base}, false);
        hits.offer({base, true, 0x00000000000000e1ULL, 1}, false);
        hits.offer({base}, false);
        hits.offer({base, true, 0xab00000000000000ULL, 128}, false);
        hits.offer({base}, false);
        hits.offer({base, true, 0x13579bdf02468aceULL, 0x55}, false);
        hits.offer({base}, false);
        for (unsigned n = 0; n < 8; ++n) hits.tick();
        hits.blockCpu = false; hits.drain(); hits.probe(base);
        Test clean; clean.stream(0, CACHE_LINES); clean.peakAcquires = 0;
        const auto start = clean.cycles;
        clean.stream(CACHE_LINES, CACHE_LINES*2);
        const auto cleanCycles = clean.cycles - start;
        check(clean.peakAcquires >= READ_MSHRS, "steady-state clean replacement did not overlap all miss slots");
        if (READ_MSHRS > 1) check(clean.overlapReleases, "release did not overlap unrelated acquires");
        Test dirty; dirty.stream(0, CACHE_LINES, true); dirty.peakAcquires = 0;
        dirty.stream(CACHE_LINES, CACHE_LINES);
        if (READ_MSHRS > 1) check(dirty.peakAcquires >= 2 && dirty.overlapReleases, "dirty-victim read stream remained fully blocking");
        dirty.flush();
        Test conflicts;
        conflicts.offer({base}, false); conflicts.offer({base + 8}, false); conflicts.drain();
        check(conflicts.aCount == 1, "same-line request bypassed reservation or failed residency");
        const uint64_t stride = 64ULL*CACHE_LINES/CACHE_WAYS;
        conflicts.offer({base + stride}, false); conflicts.offer({base + 2*stride}, false); conflicts.drain();
        conflicts.denyLine = base + 64ULL*CACHE_LINES*3;
        conflicts.offer({conflicts.denyLine}); const auto misses = conflicts.aCount;
        conflicts.denyLine = ~0ULL; conflicts.offer({base + 64ULL*CACHE_LINES*3});
        check(conflicts.aCount == misses + 1, "denied refill installed a valid line");
        conflicts.offer({base + 64, true, 0x1122334455667788ULL, 0x55});
        conflicts.blockCpu = true; conflicts.offer({base + 64}, false);
        conflicts.until([&] { return conflicts.d.get_io$$upstream$$response$$valid(); }, "held response setup");
        conflicts.probe(base + 64); // C must progress independently of CPU response retirement.
        conflicts.blockCpu = false; conflicts.drain();
        conflicts.offer({base + 64, false, 0, 255, true}); // ordered bypass sees dirty probe backing.
        Test afterAck; afterAck.blockCpu = true; afterAck.probeAfterAck = true;
        afterAck.offer({base}, false);
        afterAck.until([&] { return afterAck.probeDone; }, "post-E pre-install probe deadlock");
        check(afterAck.probeStalls, "post-E transient probe did not exercise installation ordering");
        afterAck.blockCpu = false; afterAck.drain(); afterAck.offer({base});
        check(afterAck.aCount == 2, "probe failed to invalidate installed line");
        Test absentProbe; absentProbe.offer({base});
        absentProbe.blockCpu = true; absentProbe.probeAfterAck = true; absentProbe.autoProbeOffset = stride;
        absentProbe.offer({base + stride}, false);
        absentProbe.until([&] { return absentProbe.probeDone; }, "nonresident same-set probe/refill deadlock");
        absentProbe.blockCpu = false; absentProbe.drain(); absentProbe.offer({base + stride});
        check(absentProbe.aCount == 2, "absent probe corrupted the concurrent refill");
        Test resetRead; resetRead.offer({base}, false);
        resetRead.until([&] { return !resetRead.acquires.empty(); }, "reset acquire setup");
        resetRead.coordinatedReset(); resetRead.offer({base + 128});
        Test resetRelease; resetRelease.offer({base, true, 0x123456789abcdef0ULL});
        if (CACHE_WAYS == 2) resetRelease.offer({base + stride, true, 0xfedcba9876543210ULL});
        resetRelease.offer({base + stride*CACHE_WAYS}, false);
        resetRelease.until([&] { return resetRelease.cOpcode == 7 && resetRelease.cBeat > 0; }, "reset release setup");
        resetRelease.coordinatedReset(); resetRelease.offer({base});
        std::cout << "COHERENT_READ_MSHR_PASS mshrs=" << READ_MSHRS << " lines=" << CACHE_LINES
            << " steady_clean_cycles=" << cleanCycles << " steady_peak=" << clean.peakAcquires
            << " dirty_peak=" << dirty.peakAcquires << " overlapping_releases=" << dirty.overlapReleases
            << " read_hit_ii1=1 store_hit_ii1=1 held_strobe_raw=1 held_reply_probe=1 post_e_probe=1 absent_probe_refill=1 denied_retry=1 same_line_reservation=1 reset_read=1 reset_release=1\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << "COHERENT_READ_MSHR_FAIL " << e.what() << "\n"; return 1; }
}
