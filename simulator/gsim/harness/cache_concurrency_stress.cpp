// Runtime-seeded traffic and independent memory oracle, reusing the exact emitted RTL.
#define CACHE_HOME_EMBED
#include "coherent_cache_home.cpp"
#include <set>

static uint64_t scramble(uint64_t x) {
    x += 0x9e3779b97f4a7c15ULL;
    x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ULL;
    x = (x ^ (x >> 27)) * 0x94d049bb133111ebULL;
    return x ^ (x >> 31);
}
struct Stress : Test {
    uint64_t seed, issuedCpu = 0, issuedDma = 0, observedLoads = 0;
    uint64_t mergedOpportunity = 0, missStoreOverlap = 0, delayedHeadCycles = 0;
    std::set<uint64_t> scheduledReads, scheduledWrites;
    std::deque<std::pair<uint64_t, bool>> latencyOwners;
    std::vector<uint64_t> hitLatencies, missLatencies;
    bool stochastic = true;
    explicit Stress(uint64_t s) : seed(s) {
        readyAlways = true;
        observer = [&] {
            // Every transaction receives its latency once, by transaction identity.
            // Fixed seed and logical transaction order are common to A/B runs.
            for (auto &read : ddr.pendingReads) if (scheduledReads.insert(read.sequence).second)
                read.due = cycles + 12 + scramble(seed ^ read.sequence ^ 0x1234) % 97;
            for (auto &write : ddr.pendingB) if (scheduledWrites.insert(write.sequence).second)
                write.due = cycles + 8 + scramble(seed ^ write.sequence ^ 0x5678) % 151;
            if (d.io$$cpu$$request$$valid && d.get_io$$cpu$$request$$ready()) {
                latencyOwners.push_back({cycles, bool(d.get_io$$hit())});
                observedLoads += !d.io$$cpu$$request$$bits$$write;
                missStoreOverlap += d.io$$cpu$$request$$bits$$write && d.get_io$$hit() && occupancy() != 0;
            }
            if (d.get_io$$cpu$$response$$valid() && !blockCpu) {
                check(!latencyOwners.empty(), "stress latency response lacked owner");
                const auto [accepted, hit] = latencyOwners.front(); latencyOwners.pop_front();
                (hit ? hitLatencies : missLatencies).push_back(cycles - accepted);
            }
            delayedHeadCycles += !cpuExpected.empty() && blockCpu;
        };
    }
    void pump() {
        const uint64_t epoch = cycles / 37;
        const auto bits = scramble(seed ^ epoch);
        blockCpu = stochastic && ((cycles % 37) < (bits % 17));
        blockDma = stochastic && ((cycles % 29) < ((bits >> 8) % 13));
        d.set_io$$holdCoherentC(stochastic && cycles % 23 < ((bits >> 16) % 5));
        d.set_io$$holdCoherentD(stochastic && cycles % 31 < ((bits >> 24) % 7));
        d.set_io$$holdReleaseAck(stochastic && cycles % 101 < ((bits >> 32) % 41));
        d.set_io$$holdGrantAck(stochastic && cycles % 19 < ((bits >> 40) % 5));
        tick();
    }
    template<class P> void await(P done, const char *why, unsigned limit = 200000) {
        for (unsigned n = 0; !done(); ++n) { check(n < limit, why); pump(); }
    }
    void issueCpu(Request request) {
        await([&] { return !cpuRequest; }, "stress CPU admission deadlock");
        cpuRequest = request; ++issuedCpu;
        await([&] { return !cpuRequest; }, "stress CPU request deadlock");
    }
    void issueDma(Request request) {
        await([&] { return !dmaRequest; }, "stress DMA admission deadlock");
        dmaRequest = request; ++issuedDma;
        await([&] { return !dmaRequest; }, "stress DMA request deadlock");
    }
    void settle() {
        await([&] { return !cpuRequest && !dmaRequest && cpuExpected.empty() && dmaExpected.empty() &&
            grants.empty() && !d.get_io$$prefetchBusy() && !releasePending; }, "stress owners failed to drain");
    }
    static uint64_t quantile(std::vector<uint64_t> samples, unsigned percent) {
        if (samples.empty()) return 0;
        std::sort(samples.begin(), samples.end());
        return samples[std::min(samples.size()-1, samples.size()*percent/100)];
    }
    void finish() {
        settle();
        d.set_io$$flushRequest(1);
        await([&] { return d.get_io$$flushDone(); }, "stress flush deadlock");
        d.set_io$$flushRequest(0); pump();
        for (const auto &[address, expected] : architectural)
            check(ddr.memory.at(uint32_t(address-base)) == expected, "stress full backing oracle mismatch");
        check(cpuAccepted == cpuReturned && dmaAccepted == dmaReturned && latencyOwners.empty(),
            "stress request/response ownership failed to close");
        std::cout << "CACHE_STRESS_PASS seed=" << seed << " cycles=" << cycles
            << " cpu=" << cpuReturned << " dma=" << dmaReturned
            << " load_bytes=" << observedLoads*8 << " rbeats=" << ddr.rBeats << " wbeats=" << ddr.wBeats
            << " hit_p50=" << quantile(hitLatencies, 50) << " hit_p99=" << quantile(hitLatencies, 99)
            << " miss_p50=" << quantile(missLatencies, 50) << " miss_p99=" << quantile(missLatencies, 99)
            << " reply_max=" << std::max(quantile(hitLatencies,100),quantile(missLatencies,100))
            << " held_head_cycles=" << delayedHeadCycles << " store_miss_overlap=" << missStoreOverlap
            << " dirty_probe_beats=" << dirtyProbeBeats << " release_overlap=" << releaseOverlap
            << " read_ids=" << ddr.peakReadIds << " write_ids=" << ddr.peakWriteIds << '\n';
    }
};
int main(int argc, char **argv) {
    try {
        uint64_t seed = 1;
        unsigned iterations = 1024;
        for (int i=1;i<argc;++i) {
            const std::string arg=argv[i];
            if (arg=="--seed" && i+1<argc) seed=std::stoull(argv[++i]);
            else if (arg=="--iterations" && i+1<argc) iterations=std::stoul(argv[++i]);
            else if (arg=="--inject-mismatch") injectMismatch=true;
            else throw std::runtime_error("unknown stress option");
        }
        check(iterations >= 64 && iterations <= 4096, "stress iteration limit out of bounds");
        Stress t(seed);
        // CPU and DMA random streams use disjoint halves. Shared-line probes
        // are inserted only after writes have retired, so the independent
        // acceptance-time oracle never invents a total order for racing writes.
        for (unsigned line=0;line<16;++line)
            t.issueCpu({base + 64ULL*line, true, scramble(seed+line), 255});
        t.settle();
        for (unsigned n=0;n<iterations;++n) {
            const uint64_t r=scramble(seed+n*0x10001ULL);
            const bool write=(r%10)<3;
            const uint64_t line=write && (r&16) ? (r>>8)%16 : (r>>8)%1024;
            const auto address=base+64*line+8*((r>>24)%8);
            t.issueCpu({address,write,scramble(r),write ? unsigned(1+((r>>32)%255)) : 255U});
            if (n%7==0) {
                const uint64_t dmaLine=1024+scramble(r^0xd00d)%1024;
                t.issueDma({base+64*dmaLine,bool(r&128),scramble(r^0xa55a), (r&128) ? unsigned(1+((r>>40)%255)) : 255U});
            }
            if (n%31==30) {
                t.settle();
                const unsigned hot=(n/31)%16;
                t.issueCpu({base+64ULL*hot,true,scramble(seed^n),255}); t.settle();
                // Probe dirty ownership while an independent miss is active.
                t.issueCpu({base+64ULL*(512+hot)});
                t.issueDma({base+64ULL*hot});
                t.settle();
                t.issueCpu({base+64ULL*hot});
            }
        }
        t.finish();
        return 0;
    } catch(const std::exception &error) {
        std::cerr << "CACHE_STRESS_FAIL " << error.what() << '\n'; return 1;
    }
}
