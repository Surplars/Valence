#include "CoherentCacheHomeGsim.h"
#include "mshr_occupancy.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <functional>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>
#ifndef AXI_SLOTS
#define AXI_SLOTS 4
#endif
#ifndef READ_MSHRS
#define READ_MSHRS 2
#endif
#ifndef CACHE_LINES
#define CACHE_LINES 512
#endif
#ifndef RESPONSE_ENTRIES
#define RESPONSE_ENTRIES 2
#endif
static void check(bool p, const char *m) { if (!p) throw std::runtime_error(m); }
#define BOARD_DDR_BYTES 131072ULL
#define DDR_READ_CREDITS 4
#define DDR_READ_LATENCY 32
#define DDR_READ_BEAT_GAP 1
#if defined(PREFETCH_BENCHMARK_MODEL)
#include "board_ddr_benchmark.h"
#elif defined(MIXED_MODEL)
#include "board_ddr_mixed.h"
#else
#include "board_ddr_multiid.h"
#endif
#ifndef CACHE_BASE
#define CACHE_BASE 0x80010000ULL
#endif
static constexpr uint64_t base = CACHE_BASE;
static bool injectMismatch = false;
static bool unsafeFenceNegative = false;
struct Request { uint64_t address; bool write = false; uint64_t data = 0; unsigned mask = 255; bool uncached = false; };
struct Expected { uint64_t data, acceptedCycle; bool error, hit, cancelled = false; };
struct GrantOwner { uint64_t address; unsigned beats = 0, sink = 0; };
struct Test {
    SCoherentCacheHomeGsim d;
    std::function<void()> observer;
    DdrModel ddr;
    std::map<uint64_t, uint64_t> architectural;
    std::optional<Request> cpuRequest, dmaRequest;
    std::deque<Expected> cpuExpected, dmaExpected;
    std::map<unsigned, GrantOwner> grants;
    std::map<unsigned, uint64_t> releases;
    std::optional<std::tuple<uint64_t, bool, bool>> stalledCpu, stalledDma;
    uint64_t cycles = 0, cpuAccepted = 0, cpuReturned = 0, dmaAccepted = 0, dmaReturned = 0;
    uint64_t peakCpu = 0, peakAcquires = 0, releaseLines = 0, releaseOverlap = 0, releasePending = 0;
    uint64_t probes = 0, dirtyProbeBeats = 0, blockedProbeRelease = 0, cancelledReplies = 0;
    uint64_t cpuBlocked = 0, hitCount = 0, missCount = 0, hitLatency = 0, missLatency = 0;
    unsigned peakOccupied = 0;
    unsigned occupancy() const {
#if READ_MSHRS > 1
        return MshrOccupancy::nonblocking(d.cache$phase);
#else
        return MshrOccupancy::legacy(d.cache$state,d.cache$probeResume,d.cache$flushActive,d.cache$pendingBypass);
#endif
    }
    uint64_t lastReleaseAckCycle = 0, turnoverReleases = 0;
    unsigned releaseBeat = 0;
    bool latencyTrace = false;
    uint64_t latencyAccepted = 0, latencyReply = 0, latencyRelease = 0, latencyAcquire = 0, latencyAr = 0;
    uint64_t releaseAddress = 0, stalledVictimAddress = 0, resolvedVictimProbes = 0;
    bool victimProbeWaiting = false, victimReleaseAcked = false;
    bool blockCpu = false, blockDma = false, readyAlways = false, blockDdrWrites = false;
    static uint64_t initial(uint64_t a) { return 0xabcde98765432100ULL ^ (a * 0x100100101ULL); }
    static uint64_t merge(uint64_t old, uint64_t data, unsigned mask) {
        for (unsigned b = 0; b < 8; ++b) if (mask & (1U << b))
            old = (old & ~(0xffULL << (8*b))) | (data & (0xffULL << (8*b)));
        return old;
    }
    void tick() {
        check(cycles < 1000000, "bounded integration cycle budget exceeded");
        const bool cpuReady = !blockCpu && (readyAlways || cycles % 13 < 8);
        const bool dmaReady = !blockDma && (readyAlways || cycles % 7 != 3);
        d.set_io$$cpu$$request$$valid(bool(cpuRequest));
        d.set_io$$dma$$request$$valid(bool(dmaRequest));
        d.set_io$$cpu$$response$$ready(cpuReady); d.set_io$$dma$$response$$ready(dmaReady);
#define DRIVE_REQUEST(port, pending) \
        if (pending) { \
            d.set_io$$##port##$$request$$bits$$address(pending->address); \
            d.set_io$$##port##$$request$$bits$$write(pending->write); \
            d.set_io$$##port##$$request$$bits$$data(pending->data); \
            d.set_io$$##port##$$request$$bits$$mask(pending->mask); \
            d.set_io$$##port##$$request$$bits$$uncached(pending->uncached); \
        }
        DRIVE_REQUEST(cpu, cpuRequest) DRIVE_REQUEST(dma, dmaRequest)
#undef DRIVE_REQUEST
        ddr.drive(d, cycles);
        if(blockDdrWrites){ddr.awReady=false;ddr.wReady=false;d.set_io$$ddrAxi$$aw$$ready(0);d.set_io$$ddrAxi$$w$$ready(0);}
        d.step(); ddr.sample(d); ++cycles;
        const unsigned occupied=occupancy();check(occupied<=READ_MSHRS,"MSHR occupancy exceeds configuration");
        peakOccupied=std::max(peakOccupied,occupied);
        const auto cpu = std::make_tuple(uint64_t(d.get_io$$cpu$$response$$bits$$data()),
            bool(d.get_io$$cpu$$response$$bits$$error()), bool(d.get_io$$cpu$$response$$bits$$pageFault()));
        const auto dma = std::make_tuple(uint64_t(d.get_io$$dma$$response$$bits$$data()),
            bool(d.get_io$$dma$$response$$bits$$error()), bool(d.get_io$$dma$$response$$bits$$pageFault()));
        if (stalledCpu) check(d.get_io$$cpu$$response$$valid() && cpu == *stalledCpu, "held CPU reply changed");
        if (stalledDma) check(d.get_io$$dma$$response$$valid() && dma == *stalledDma, "held DMA reply changed");
        stalledCpu = d.get_io$$cpu$$response$$valid() && !cpuReady ? std::optional{cpu} : std::nullopt;
        stalledDma = d.get_io$$dma$$response$$valid() && !dmaReady ? std::optional{dma} : std::nullopt;
        if (cpuRequest && d.get_io$$cpu$$request$$ready()) {
            const auto q = *cpuRequest;
            if (latencyTrace) latencyAccepted = cycles;
            const bool hit = d.get_io$$hit();
            if ((q.write && !hit) || q.uncached) check(cpuExpected.empty(), "CPU barrier crossed older replies");
            const bool error = d.get_io$$miss() && ddr.denyReadAddress &&
                *ddr.denyReadAddress == ((q.address - base) & ~63ULL);
            check(architectural.count(q.address), "CPU address outside independent initialized image");
            cpuExpected.push_back({q.write ? 0 : architectural.at(q.address), cycles, error, hit});
            if (q.write && !error) architectural[q.address] = merge(architectural.at(q.address), q.data, q.mask);
            cpuRequest.reset(); ++cpuAccepted; peakCpu = std::max(peakCpu, uint64_t(cpuExpected.size()));
        } else if (cpuRequest) ++cpuBlocked;
        if (dmaRequest && d.get_io$$dma$$request$$ready()) {
            const auto q = *dmaRequest;
            check(architectural.count(q.address), "DMA address outside independent initialized image");
            dmaExpected.push_back({q.write ? 0 : architectural.at(q.address), cycles, false, false});
            if (q.write) architectural[q.address] = merge(architectural.at(q.address), q.data, q.mask);
            dmaRequest.reset(); ++dmaAccepted;
        }
        if (d.get_io$$cpu$$response$$valid() && cpuReady) {
            check(!cpuExpected.empty(), "CPU response lacked accepted owner");
            const auto e = cpuExpected.front();
            if (latencyTrace) { latencyReply = cycles; latencyTrace = false; }
            check(std::get<1>(cpu) == e.error && !std::get<2>(cpu), "CPU error/response owner mismatch");
            if (!e.error) check(std::get<0>(cpu) == (e.data ^ uint64_t(injectMismatch)), "CPU independent byte oracle mismatch");
            if (e.hit) { ++hitCount; hitLatency += cycles - e.acceptedCycle; }
            else { ++missCount; missLatency += cycles - e.acceptedCycle; }
            cancelledReplies += e.cancelled; cpuExpected.pop_front(); ++cpuReturned;
        }
        if (d.get_io$$dma$$response$$valid() && dmaReady) {
            check(!dmaExpected.empty(), "DMA response lacked accepted owner");
            const auto e = dmaExpected.front();
            check(!std::get<1>(dma) && !std::get<2>(dma) && std::get<0>(dma) == e.data,
                "DMA independent byte/owner oracle mismatch");
            dmaExpected.pop_front(); ++dmaReturned;
        }
        if (latencyTrace && d.get_io$$ddrAxi$$ar$$valid() && !latencyAr) latencyAr = cycles;
        if (d.get_io$$acquireFire()) {
            if (latencyTrace && !latencyAcquire) latencyAcquire = cycles;
            const unsigned source = d.get_io$$acquireSource();
            check(!grants.count(source), "cache reused live Acquire source");
            grants.emplace(source, GrantOwner{d.get_io$$acquireAddress()});
            peakAcquires = std::max(peakAcquires, uint64_t(grants.size()));
        }
        if (d.get_io$$grantFire()) {
            const unsigned source = d.get_io$$grantSource(), sink = d.get_io$$grantSink();
            check(grants.count(source), "home Grant lost cache Acquire source");
            auto &g = grants.at(source);
            if (!g.beats) g.sink = sink;
            check(g.sink == sink && g.beats < 8, "home Grant sink/beat ownership changed");
            ++g.beats;
        }
        if (d.get_io$$grantAckFire()) {
            const unsigned sink = d.get_io$$grantAckSink();
            auto i = std::find_if(grants.begin(), grants.end(), [&](const auto &g) { return g.second.beats == 8 && g.second.sink == sink; });
            check(i != grants.end(), "cache GrantAck lost home sink owner"); grants.erase(i);
        }
        if (d.get_io$$releaseFire()) {
            if (latencyTrace && !latencyRelease) latencyRelease = cycles;
            if (!releaseBeat) {
                if (lastReleaseAckCycle && cycles == lastReleaseAckCycle + 2) ++turnoverReleases;
                ++releaseLines; ++releasePending; releaseOverlap += !grants.empty();
                releaseAddress = d.get_io$$releaseAddress();
                check(!releases.count(d.get_io$$releaseSource()), "release source reused before Ack");
                releases[d.get_io$$releaseSource()] = releaseAddress;
            }
            if (!d.get_io$$releaseData() || releaseBeat == 7) releaseBeat = 0; else ++releaseBeat;
        }
        if (d.get_io$$releaseAckFire()) {
            lastReleaseAckCycle = cycles;
            check(releasePending > 0 && releases.count(d.get_io$$releaseAckSource()), "ReleaseAck owner mismatch"); --releasePending;
            const auto ackAddress = releases.at(d.get_io$$releaseAckSource());
            releases.erase(d.get_io$$releaseAckSource());
            if (victimProbeWaiting && stalledVictimAddress == ackAddress) victimReleaseAcked = true;
        }
        probes += d.get_io$$probeFire();
        dirtyProbeBeats += d.get_io$$probeReplyFire() && d.get_io$$probeReplyData();
        if (d.get_io$$probeOffer() && !d.get_io$$probeFire() && releasePending &&
            d.get_io$$probeAddress() == releaseAddress) {
            if (!victimProbeWaiting || stalledVictimAddress != releaseAddress) victimReleaseAcked = false;
            ++blockedProbeRelease; victimProbeWaiting = true; stalledVictimAddress = releaseAddress;
        }
        if (d.get_io$$probeFire() && victimProbeWaiting && d.get_io$$probeAddress() == stalledVictimAddress) {
            check(victimReleaseAcked, "same-victim probe bypassed its ReleaseAck");
            ++resolvedVictimProbes; victimProbeWaiting = false;
        }
        if (observer) observer();
    }
    Test() {
        for (uint64_t offset = 0; offset < BOARD_DDR_BYTES; offset += 8) {
            ddr.memory[offset] = initial(base + offset); architectural[base + offset] = initial(base + offset);
        }
#define INIT_PORT(port) \
        d.set_io$$##port##$$request$$valid(0); d.set_io$$##port##$$response$$ready(0); \
        d.set_io$$##port##$$request$$bits$$address(base); d.set_io$$##port##$$request$$bits$$size(3); \
        d.set_io$$##port##$$request$$bits$$data(0); d.set_io$$##port##$$request$$bits$$mask(255); \
        d.set_io$$##port##$$request$$bits$$write(0); d.set_io$$##port##$$request$$bits$$atomic(0); \
        d.set_io$$##port##$$request$$bits$$atomicOp(0); d.set_io$$##port##$$request$$bits$$virtualized(0); \
        d.set_io$$##port##$$request$$bits$$uncached(0)
        INIT_PORT(cpu); INIT_PORT(dma);
        d.set_io$$cpu$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$dma$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$prefetchPmpCfg(0x1f); d.set_io$$prefetchPmpAddress((1ULL<<54)-1);
        d.set_io$$prefetchPrivilege(3); d.set_io$$bypassPrefetchAuthorization(0);
#undef INIT_PORT
        d.set_io$$holdGrantAck(0); d.set_io$$holdCoherentD(0); d.set_io$$holdCoherentC(0); d.set_io$$holdReleaseAck(0);
        d.set_io$$flushRequest(0); d.set_reset(1); tick(); tick(); d.set_reset(0);
        check(occupancy()==0,"reset retained cache miss owner");
        // The order FIFO is empty after reset. Its unused storage must never
        // become an eager array index; accepted enqueues overwrite live owners.
        for (auto &entry : d.ordered$order$ram) entry = 0xff;
    }
    template<class Predicate> void until(Predicate done, const char *message, unsigned budget = 500000) {
        const auto deadline = cycles + budget;
        while (!done() && cycles < deadline) tick();
        check(done(), message);
    }
    void drainCpu() { until([&] { return !cpuRequest && cpuExpected.empty(); }, "CPU completion deadlock"); }
    void drainDma() { until([&] { return !dmaRequest && dmaExpected.empty(); }, "DMA completion deadlock"); }
    void cpu(Request r, bool wait = true) {
        check(!cpuRequest, "CPU request overwritten"); cpuRequest = r;
        until([&] { return !cpuRequest; }, "CPU request deadlock"); if (wait) drainCpu();
    }
    void dma(Request r, bool wait = true) {
        check(!dmaRequest, "DMA request overwritten"); dmaRequest = r;
        until([&] { return !dmaRequest; }, "DMA request deadlock"); if (wait) drainDma();
    }
    void stream(unsigned first, unsigned count, bool write = false) {
        for (unsigned n = 0; n < count; ++n) cpu({base + 64ULL*(first+n), write, 0x1234000000000000ULL ^ (first+n)}, false);
        drainCpu();
    }
    void flush() {
        d.set_io$$flushRequest(1); until([&] { return d.get_io$$flushDone(); }, "cache/home flush deadlock");
        d.set_io$$flushRequest(0); tick();
        for (auto [a, value] : architectural) check(ddr.memory.at(uint32_t(a-base)) == value, "flush independent backing mismatch");
        check(grants.empty() && releasePending == 0 && ddr.pendingReads.empty() && !ddr.writing && !ddr.responding,
            "flush acknowledged before accepted traffic drained");
    }
    void coordinatedReset() {
        // Reset is shared with the downstream model; no stale pre-reset owner survives.
        d.set_io$$cpu$$request$$valid(0); d.set_io$$cpu$$response$$ready(0);
        d.set_io$$dma$$request$$valid(0); d.set_io$$dma$$response$$ready(0);
        d.set_io$$ddrAxi$$ar$$ready(0); d.set_io$$ddrAxi$$aw$$ready(0); d.set_io$$ddrAxi$$w$$ready(0);
        d.set_io$$ddrAxi$$r$$valid(0); d.set_io$$ddrAxi$$b$$valid(0); d.set_io$$flushRequest(0);
        d.set_io$$holdGrantAck(0); d.set_io$$holdCoherentD(0); d.set_io$$holdCoherentC(0); d.set_io$$holdReleaseAck(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0); cycles += 2;
        auto memory = std::move(ddr.memory); ddr = DdrModel{}; ddr.memory = std::move(memory);
        for (auto [offset, value] : ddr.memory) architectural[base+offset] = value;
        cpuRequest.reset(); dmaRequest.reset(); cpuExpected.clear(); dmaExpected.clear(); grants.clear(); releases.clear();
        stalledCpu.reset(); stalledDma.reset(); releasePending = releaseBeat = 0; blockCpu = blockDma = false;
        victimProbeWaiting = victimReleaseAcked = false;
    }
};
#ifndef CACHE_HOME_EMBED
int main(int argc, char **argv) {
    injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    unsafeFenceNegative = argc == 2 && std::string(argv[1]) == "--unsafe-cache-only-fence";
    try {
        MshrOccupancy::selfTest();
        // Identical modulo385 host timing phase (LCM of7/11/5 stalls) and
        // always-ready CPU isolate cold, clean-victim and dirty-victim latency.
        for (unsigned kind = 0; kind < 3; ++kind) {
            Test latency; latency.readyAlways = true;
            if (kind) {
                latency.cpu({base, kind == 2, 0x778899aabbccddeeULL});
                latency.cpu({base + 64ULL*(CACHE_LINES/2), kind == 2, 0x1122334455667788ULL});
            }
            while (latency.cycles % 385) latency.tick();
            check(latency.grants.empty() && latency.ddr.pendingReads.empty() && !latency.releasePending,
                  "idle-latency setup retained a protocol owner");
            latency.latencyTrace = true;
            latency.cpu({base + (kind ? 64ULL*CACHE_LINES : 0)});
            check(latency.latencyReply > latency.latencyAccepted && latency.latencyAr >= latency.latencyAcquire,
                  "missing idle-latency boundaries");
            if (kind) check(latency.latencyRelease > latency.latencyAccepted, "missing victim-release witness");
            std::cout << "IDLE_MISS_LATENCY kind=" << kind << " response=" << latency.latencyReply-latency.latencyAccepted
                << " release=" << (kind ? latency.latencyRelease-latency.latencyAccepted : 0)
                << " acquire=" << latency.latencyAcquire-latency.latencyAccepted
                << " ar_offer=" << latency.latencyAr-latency.latencyAccepted
                << " acquire_to_ar=" << latency.latencyAr-latency.latencyAcquire << std::endl;
        }
        Test steady; steady.stream(0, CACHE_LINES); steady.peakAcquires = 0; steady.peakOccupied = 0;
        const auto begin = steady.cycles, priorReads = steady.ddr.reads;
        steady.stream(CACHE_LINES, 1024);
        const auto steadyCycles = steady.cycles - begin;
        check(steady.ddr.reads-priorReads == 1024, "steady replacement lost/duplicated cache-line reads");
        check(steady.peakOccupied == READ_MSHRS, "configured occupancy not observed in independent-line fixture");
        check(steady.peakAcquires >= READ_MSHRS, "real home did not expose configured miss concurrency");
        Test dirty; dirty.stream(0, CACHE_LINES, true); dirty.peakAcquires = 0; dirty.ddr.peakReadIds = 0;
        const auto dirtyBegin = dirty.cycles;
        dirty.stream(CACHE_LINES, CACHE_LINES);
        const auto dirtyCycles = dirty.cycles - dirtyBegin;
        std::cout << "DIRTY_STREAM_DIAGNOSTIC mshrs=" << READ_MSHRS << " cycles=" << dirtyCycles
            << " acquire_peak=" << dirty.peakAcquires << " axi_read_peak=" << dirty.ddr.peakReadIds
            << " release_overlap=" << dirty.releaseOverlap << " ack_turnover_releases=" << dirty.turnoverReleases << std::endl;
        if (READ_MSHRS > 1) check(dirty.peakAcquires >= 2 && dirty.ddr.peakReadIds >= 2 && dirty.releaseOverlap,
            "real dirty writeback serialized every read miss");
#if defined(MIXED_MODEL) && defined(MIXED_RTL)
        check(dirty.ddr.peakWriteIds >= 2 && dirty.ddr.twoReadTwoWriteCycles > 0,
            "production dirty stream never had two live reads and two live writes together");
        std::cout << "MIXED_OVERLAP reads=" << dirty.ddr.reads << " writes=" << dirty.ddr.writes
            << " rbeats=" << dirty.ddr.rBeats << " wbeats=" << dirty.ddr.wBeats << " b=" << dirty.ddr.bResponses
            << " write_peak=" << dirty.ddr.peakWriteIds << " mixed_cycles=" << dirty.ddr.mixedCycles
            << " two_read_two_write_cycles=" << dirty.ddr.twoReadTwoWriteCycles << std::endl;
#else
        if (READ_MSHRS > 1) check(dirty.turnoverReleases, "queued victim never captured at prior ReleaseAck");
#endif
        const auto flushBegin = dirty.cycles; dirty.flush();
        std::cout << "DIRTY_TOTAL replacement_cycles=" << dirtyCycles << " flush_tail_cycles=" << dirty.cycles-flushBegin
            << " total_cycles=" << dirty.cycles-dirtyBegin << std::endl;
        Test hits; hits.cpu({base}); hits.readyAlways = true;
        auto start = hits.cycles;
        for (unsigned n = 0; n < 16; ++n) hits.cpu({base + 8ULL*(n%8)}, false);
        hits.drainCpu(); check(hits.cycles-start == 17, "integrated read-hit latency/II1 regression");
        start = hits.cycles;
        for (unsigned n = 0; n < 16; ++n) hits.cpu({base, true, 0xabcdef0000000000ULL ^ n, 1U << (n%8)}, false);
        hits.drainCpu(); check(hits.cycles-start == 17, "integrated store-hit latency/II1 regression");
        // Only two credits are assumed. Hold an older read while a partial hit
        // store changes the word, then independently verify the following read.
        for (unsigned mask : {1U, 128U, 0x55U, 0xaaU}) {
            hits.blockCpu = true; hits.cpu({base}, false);
            hits.cpu({base, true, 0x13579bdf02468aceULL ^ mask, mask}, false);
            for (unsigned n = 0; n < 12; ++n) hits.tick();
            hits.blockCpu = false; hits.drainCpu(); hits.cpu({base});
        }
        hits.blockCpu = true; hits.cpu({base}, false);
        hits.until([&] { return hits.d.get_io$$cpu$$response$$valid(); }, "held CPU probe setup");
        hits.dma({base}); // real DMA must probe dirty data without waiting for CPU DREADY.
        check(hits.dirtyProbeBeats >= 8, "real dirty DMA probe not exercised");
        hits.blockCpu = false; hits.drainCpu();
        hits.dma({base, true, 0xffeeddccbbaa0099ULL, 0x55}); hits.cpu({base}); hits.flush();
        const uint64_t stride = 64ULL*CACHE_LINES/2;
        Test race; race.cpu({base, true, 0xfedcba9876543210ULL});
        race.cpu({base + stride, true, 0x0123456789abcdefULL});
        race.dma({base}, false); race.cpu({base + 2*stride}, false);
        race.drainDma(); race.drainCpu();
        check(race.blockedProbeRelease > 0 && race.resolvedVictimProbes == 1,
            "same-victim B/ReleaseAck race witness missing"); race.flush();
        Test pressure; pressure.stream(0, CACHE_LINES, true);
        pressure.dma({base + (CACHE_LINES/4)*64}, false);
        for (unsigned n = 0; n < READ_MSHRS; ++n) pressure.cpu({base + 64ULL*(CACHE_LINES+n)}, false);
        pressure.drainCpu(); pressure.drainDma();
        check(pressure.dirtyProbeBeats >= 8, "unrelated dirty probe under miss pressure missing");
        const auto pressureFlushStart=pressure.cycles, pressureWrites=pressure.ddr.writes; pressure.flush();
        std::cout << "DIRTY_FLUSH_ONLY cycles=" << pressure.cycles-pressureFlushStart
            << " writebacks=" << pressure.ddr.writes-pressureWrites << std::endl;
        Test delayed; delayed.stream(0, CACHE_LINES, true);
        delayed.d.set_io$$holdCoherentD(1); delayed.d.set_io$$holdGrantAck(1);
        for (unsigned n = 0; n < READ_MSHRS; ++n) delayed.cpu({base + 64ULL*(CACHE_LINES+n)}, false);
        for (unsigned n = 0; n < 180; ++n) delayed.tick();
        delayed.d.set_io$$holdCoherentD(0);
        for (unsigned n = 0; n < 80; ++n) delayed.tick();
        delayed.d.set_io$$holdGrantAck(0); delayed.drainCpu(); delayed.flush();
        // An accepted flush survives withdrawal, and a held request does not
        // retrigger it. All-clean and dirty backing oracles remain independent.
        Test cleanFlush; cleanFlush.flush(); check(cleanFlush.ddr.writes==0,"clean flush emitted writes");
        Test withdraw; withdraw.stream(0, 4, true); withdraw.d.set_io$$flushRequest(1); withdraw.tick();
        withdraw.d.set_io$$flushRequest(0);
        withdraw.until([&]{return withdraw.d.get_io$$flushDone();},"withdrawn flush failed to finish");
        check(withdraw.releasePending==0&&!withdraw.ddr.writing&&!withdraw.ddr.responding,"withdrawn flush finished early");
        withdraw.flush();
        Test repeat; repeat.stream(0, 4, true); repeat.d.set_io$$flushRequest(1);
        repeat.until([&]{return repeat.d.get_io$$flushDone();},"held flush failed");
        const auto repeatedWrites=repeat.ddr.writes;
        for(unsigned n=0;n<90;++n){repeat.tick();check(repeat.d.get_io$$flushDone(),"held flushDone dropped");}
        check(repeat.ddr.writes==repeatedWrites,"held flush retriggered writes");repeat.d.set_io$$flushRequest(0);repeat.tick();repeat.flush();
#ifdef MIXED_RTL
        Test fullFlush; fullFlush.stream(0, CACHE_LINES, true);
        fullFlush.d.set_io$$holdCoherentD(1);fullFlush.d.set_io$$flushRequest(1);
        for(unsigned n=0;n<250;++n){fullFlush.tick();check(!fullFlush.d.get_io$$flushDone(),"WB-full flush retired early");}
        check(fullFlush.releasePending==READ_MSHRS,"flush failed to fill bounded writeback owners");
        fullFlush.d.set_io$$holdCoherentD(0);fullFlush.flush();
        // Hold the final C beat of the last dirty line until an older Ack is
        // available, then release C and D together. Ack must not move the scan.
        Test collision;collision.stream(0,2,true);collision.d.set_io$$holdCoherentD(1);collision.d.set_io$$flushRequest(1);
        collision.until([&]{return collision.releaseLines==2&&collision.releaseBeat==7;},"flush C/Ack collision setup");
        collision.d.set_io$$holdCoherentC(1);
        collision.until([&]{return collision.ddr.bResponses>=1;},"older flush B never arrived");
        for(unsigned n=0;n<6;++n)collision.tick();
        collision.d.set_io$$holdCoherentC(0);collision.d.set_io$$holdCoherentD(0);collision.tick();
        check(collision.d.get_io$$releaseFire()&&collision.d.get_io$$releaseAckFire(),"final dirty C and older Ack did not coincide");
        collision.flush();
        Test resetFlush;resetFlush.stream(0,4,true);resetFlush.d.set_io$$holdCoherentD(1);resetFlush.d.set_io$$flushRequest(1);
        resetFlush.until([&]{return resetFlush.releasePending>=2;},"reset flush owner setup");
        resetFlush.coordinatedReset();resetFlush.cpu({base});resetFlush.flush();
        std::cout<<"PARALLEL_FLUSH_PROTOCOL_PASS full_window=1 final_c_ack_collision=1 reset=1 clean=1 withdrawn=1 held_request=1\n";
#endif
#if READ_MSHRS > 1
        Test probeFlush; probeFlush.stream(0,CACHE_LINES,true);
        probeFlush.d.set_io$$holdCoherentC(1);probeFlush.d.set_io$$flushRequest(1);
        probeFlush.dma({base+(CACHE_LINES/4)*64ULL},false);
        probeFlush.until([&]{return probeFlush.probes>0;},"probe competing with active flush never fired");
        check(!probeFlush.d.get_io$$flushDone(),"flush completed while victim C was blocked");
        probeFlush.d.set_io$$holdCoherentC(0);
        probeFlush.until([&]{return probeFlush.d.get_io$$flushDone();},"probe/flush ownership deadlock");
        check(probeFlush.releasePending==0,"flush completed before its writeback Acks");
        // ProbeAck transfers data ownership to the home. Wait for that DMA's
        // completion before comparing the whole backing image, not just cache-owned writebacks.
        probeFlush.drainDma();probeFlush.flush();
        check(probeFlush.dirtyProbeBeats>=8,"flush competition did not return dirty probe data");
        std::cout<<"FLUSH_PROBE_COMPETITION_PASS dirty_probe_beats="<<probeFlush.dirtyProbeBeats<<"\n";
#endif
        // The CPU store has left the cache via ProbeAckData, but its home
        // write is deliberately not yet visible in backing memory.
        Test visibility;visibility.cpu({base,true,0x13572468abcdef01ULL});visibility.blockDdrWrites=true;
        visibility.dma({base},false);
        visibility.until([&]{return visibility.dirtyProbeBeats>=8;},"dirty probe ownership transfer setup");
        visibility.d.set_io$$flushRequest(1);
        visibility.until([&]{return visibility.d.get_io$$cacheFlushDone();},"cache-local flush did not quiesce");
        check(visibility.ddr.memory.at(0)!=visibility.architectural.at(base),"stale instruction visibility negative setup missing");
        for(unsigned n=0;n<24;++n){
            visibility.tick();
            const bool ready=unsafeFenceNegative?visibility.d.get_io$$cacheFlushDone():visibility.d.get_io$$flushDone();
            check(!ready,"cache-only fence exposes stale instruction bytes");
            check(!visibility.d.get_io$$homeDrainDone(),"home drain forgot dirty probe write owner");
        }
        visibility.blockDdrWrites=false;visibility.drainDma();
        visibility.until([&]{return visibility.d.get_io$$flushDone();},"home-drained fence failed to finish");
        check(visibility.ddr.memory.at(0)==visibility.architectural.at(base),"fence released before new instruction bytes visible");
        visibility.flush();
        // A miss allocated before FENCE may still be waiting for the home.
        // Phase one must let that A and the older DMA complete before closing admission.
        Test pendingFence;pendingFence.dma({base+1000*64ULL},false);
        pendingFence.until([&]{return !pendingFence.ddr.pendingReads.empty();},"older DMA setup");
        pendingFence.cpu({base},false);
        pendingFence.until([&]{return pendingFence.d.get_io$$acquireOffer()&&!pendingFence.d.get_io$$acquireFire();},"unaccepted cache Acquire setup");
        pendingFence.d.set_io$$flushRequest(1);pendingFence.drainDma();pendingFence.drainCpu();pendingFence.flush();
        // New upstream work may remain VALID behind a closed home. It is not
        // an accepted drain owner and cannot keep a completed FENCE busy forever.
        Test gated;gated.d.set_io$$flushRequest(1);gated.until([&]{return gated.d.get_io$$flushDone();},"empty drain setup");
        gated.dma({base},false);
        for(unsigned n=0;n<24;++n){gated.tick();check(gated.d.get_io$$flushDone(),"new queued DMA blocked completed drain");}
        check(!gated.dmaExpected.empty(),"new DMA crossed closed home admission");
        gated.d.set_io$$flushRequest(0);gated.tick();gated.drainDma();
        std::cout<<"FENCE_HOME_DRAIN_PASS stale_probe_write_blocked=1 pending_acquire=1 new_dma_gate=1\n";
        Test denied; denied.ddr.denyReadAddress = 3*CACHE_LINES*64;
        denied.cpu({base + 3ULL*CACHE_LINES*64}); const auto before = denied.ddr.reads;
        denied.ddr.denyReadAddress.reset(); denied.cpu({base + 3ULL*CACHE_LINES*64});
        check(denied.ddr.reads == before + 1, "denied line installed ownership/data");
        Test cancelled; cancelled.blockCpu = true;
        for (unsigned n = 0; n < READ_MSHRS; ++n) cancelled.cpu({base + n*64ULL}, false);
        for (auto &e : cancelled.cpuExpected) e.cancelled = true;
        cancelled.blockCpu = false; cancelled.drainCpu();
        check(cancelled.cancelledReplies == READ_MSHRS, "accepted cancelled requests lost FIFO ownership");
        cancelled.cpu({base + 4096});
        Test resetRead; resetRead.cpu({base}, false);
        resetRead.until([&] { return !resetRead.ddr.pendingReads.empty(); }, "live read reset setup");
        resetRead.coordinatedReset(); resetRead.cpu({base + 128});
        Test resetWrite; resetWrite.cpu({base, true, 0xaaaa555500001111ULL});
        resetWrite.cpu({base + stride, true, 0x1111222233334444ULL});
        resetWrite.cpu({base + 2*stride}, false);
        resetWrite.until([&] { return resetWrite.ddr.writing && resetWrite.ddr.wBeat > 0 && resetWrite.ddr.wBeat < resetWrite.ddr.wCount; },
            "live writeback reset setup");
        resetWrite.coordinatedReset(); resetWrite.cpu({base});
        std::cout << "CACHE_HOME_PASS mshrs=" << READ_MSHRS << " lines=" << CACHE_LINES
            << " response_entries=" << RESPONSE_ENTRIES << " steady_lines=1024 steady_cycles=" << steadyCycles
            << " occupied_peak=" << steady.peakOccupied << " acquire_peak=" << steady.peakAcquires << " axi_read_peak=" << steady.ddr.peakReadIds
            << " dirty_cycles=" << dirtyCycles << " dirty_acquire_peak=" << dirty.peakAcquires
            << " dirty_axi_read_peak=" << dirty.ddr.peakReadIds << " dirty_release_overlap=" << dirty.releaseOverlap
            << " same_victim_probe_stall=" << race.blockedProbeRelease << " read_hit_ii1=1 store_hit_ii1=1"
            << " held_raw_strobes=1 dirty_dma_probe=1 denied_retry=1 coordinated_reset=2"
            << " cancelled_reply_owners=" << cancelled.cancelledReplies
            << " hit_response_count=" << hits.hitCount << " hit_response_cycles=" << hits.hitLatency
            << " axi_slots=" << AXI_SLOTS << " max_burst_beats=8 model_read_latency=32 cpu_execution=0\n";
        return 0;
    } catch (const std::exception &e) { std::cerr << "CACHE_HOME_FAIL " << e.what() << "\n"; return 1; }
}

#endif // CACHE_HOME_EMBED
