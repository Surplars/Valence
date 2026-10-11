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
struct Request { uint64_t address; bool write = false; uint64_t data = 0; unsigned mask = 255; bool uncached = false; bool atomic = false, virtualized = false, posted = false; unsigned atomicOp = 0; };
struct Expected { uint64_t data, acceptedCycle; bool error, hit, cancelled = false; uint64_t address = 0, sequence = 0; };
struct GrantOwner { uint64_t address; unsigned beats = 0, sink = 0; };
struct Test {
    SCoherentCacheHomeGsim d;
    std::function<void()> observer;
    std::function<void()> beforeStep;
    DdrModel ddr;
    std::map<uint64_t, uint64_t> architectural;
    std::optional<Request> cpuRequest, dmaRequest;
    std::deque<Expected> cpuExpected, dmaExpected;
    std::optional<Expected> retiredThisTick;
    bool injectDuplicateResponse = false;
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
        retiredThisTick.reset();
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
            d.set_io$$##port##$$request$$bits$$atomic(pending->atomic); \
            d.set_io$$##port##$$request$$bits$$atomicOp(pending->atomicOp); \
            d.set_io$$##port##$$request$$bits$$virtualized(pending->virtualized); \
        }
        DRIVE_REQUEST(cpu, cpuRequest) DRIVE_REQUEST(dma, dmaRequest)
        d.set_io$$adoption$$postedProofValid(cpuRequest && cpuRequest->posted);
        d.set_io$$adoption$$postedToken(cpuAccepted + 1);
#undef DRIVE_REQUEST
        ddr.drive(d, cycles);
        if(blockDdrWrites){ddr.awReady=false;ddr.wReady=false;d.set_io$$ddrAxi$$aw$$ready(0);d.set_io$$ddrAxi$$w$$ready(0);}
        if (beforeStep) beforeStep();
        d.step(); ddr.sample(d); ++cycles;
        const unsigned occupied=occupancy();check(occupied<=READ_MSHRS,"MSHR occupancy exceeds configuration");
        peakOccupied=std::max(peakOccupied,occupied);
        const auto cpu = d.get_io$$cpu$$response$$valid() ? std::make_tuple(uint64_t(d.get_io$$cpu$$response$$bits$$data()),
            bool(d.get_io$$cpu$$response$$bits$$error()), bool(d.get_io$$cpu$$response$$bits$$pageFault())) : std::tuple<uint64_t, bool, bool>{};
        const auto dma = d.get_io$$dma$$response$$valid() ? std::make_tuple(uint64_t(d.get_io$$dma$$response$$bits$$data()),
            bool(d.get_io$$dma$$response$$bits$$error()), bool(d.get_io$$dma$$response$$bits$$pageFault())) : std::tuple<uint64_t, bool, bool>{};
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
            cpuExpected.push_back({q.write ? 0 : architectural.at(q.address), cycles, error, hit, false, q.address, cpuAccepted});
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
            if (injectDuplicateResponse) std::cerr << "PREFETCH_DEMAND_ADOPTION_MUTATION_TRIGGER duplicate-cpu\n";
            const unsigned observedCount = injectDuplicateResponse ? 2 : 1;
            for (unsigned observed = 0; observed < observedCount; ++observed) {
            check(!cpuExpected.empty(), "duplicate CPU response violates accepted-ticket ownership");
            const auto e = cpuExpected.front();
            retiredThisTick = e;
            if (latencyTrace) { latencyReply = cycles; latencyTrace = false; }
            check(std::get<1>(cpu) == e.error && !std::get<2>(cpu), "CPU error/response owner mismatch");
            if (!e.error) check(std::get<0>(cpu) == (e.data ^ uint64_t(injectMismatch)), "CPU independent byte oracle mismatch");
            if (e.hit) { ++hitCount; hitLatency += cycles - e.acceptedCycle; }
            else { ++missCount; missLatency += cycles - e.acceptedCycle; }
            cancelledReplies += e.cancelled; cpuExpected.pop_front(); ++cpuReturned;
            }
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
        d.set_io$$##port##$$request$$bits$$precheckedLoad(0); \
        d.set_io$$##port##$$request$$bits$$translationEpoch(0); \
        d.set_io$$##port##$$request$$bits$$uncached(0)
        INIT_PORT(cpu); INIT_PORT(dma);
        d.set_io$$cpu$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$dma$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$prefetchPmpCfg(0x1f); d.set_io$$prefetchPmpAddress((1ULL<<54)-1);
        d.set_io$$prefetchPrivilege(3); d.set_io$$bypassPrefetchAuthorization(0);
#undef INIT_PORT
        d.set_io$$holdGrantAck(0); d.set_io$$holdCoherentD(0); d.set_io$$holdCoherentC(0); d.set_io$$holdReleaseAck(0);
#ifdef DISTINCT_WAY_FIXTURE
        d.set_io$$distinctWay$$holdAcquire(0);
        d.set_io$$distinctWay$$faultMode(0); d.set_io$$distinctWay$$faultBeat(0);
#endif
        d.set_io$$adoption$$holdAcquire(0); d.set_io$$adoption$$faultMode(0); d.set_io$$adoption$$faultBeat(0);
        d.set_io$$adoption$$postedProofValid(0); d.set_io$$adoption$$postedToken(0);
        d.set_io$$adoption$$postedSeal(0); d.set_io$$adoption$$postedEndEpisode(0);
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
