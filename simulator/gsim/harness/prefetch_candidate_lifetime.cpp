#define main originalPrefetchFixtureMain
#include "data_prefetch.cpp"
#undef main
#ifndef PREFETCH_CANDIDATE_CYCLES
#define PREFETCH_CANDIDATE_CYCLES 1
#endif

struct CandidateTest : PrefetchTest {
    static constexpr uint64_t stride = 64ULL * CACHE_LINES / 2;
#ifndef RETENTION_ORIGIN_OFFSET
#define RETENTION_ORIGIN_OFFSET (2 * stride)
#endif
    uint64_t origin = base + RETENTION_ORIGIN_OFFSET;
    uint64_t birth = 0, tokenSamples = 0, allocationAge = 0, tokenEvents = 0;
    bool watching = false, allocationPrevious = false, sawProbeCancel = false;
    CandidateTest() {
        auto parent = observer;
        observer = [&,parent] {
            parent();
            if (!watching) return;
            if (d.get_io$$prefetchEvents$$candidate()) {
                check(tokenEvents == 0, "retained candidate refreshed its original deadline");
                birth = cycles; ++tokenEvents;
            }
            if (allocationPrevious) check(d.get_io$$prefetchBusy() && d.get_io$$prefetchEvents$$missOwners() == 1,
                "candidate-to-prefetch handoff lost its continuous busy owner");
            allocationPrevious = d.get_io$$prefetchEvents$$allocated();
            if (d.cache$candidateValid) {
                check(birth && d.cache$candidateAddress == origin + 64,
                    "retained candidate changed its captured authorized physical address");
                ++tokenSamples;
                check(cycles - birth <= PREFETCH_CANDIDATE_CYCLES,
                    "retained candidate exceeded its original deadline");
                check(d.get_io$$prefetchBusy(), "retained authorization token escaped context busy");
                sawProbeCancel |= d.get_io$$probeOffer();
            }
            if (d.get_io$$prefetchEvents$$allocated()) {
                check(birth && d.cache$canAllocate && d.cache$evictionState == 0,
                    "retained candidate bypassed the unchanged idle-lane allocation guard");
                allocationAge = cycles - birth;
            }
        };
    }
    void warm(bool dirty, bool targetDirty = false, bool previousPending = false) {
        cpu({origin - 2 * stride, dirty, 0x1111222233334444ULL});
        cpu({origin - stride, dirty, 0x5555666677778888ULL});
        cpu({origin + 64 - 2 * stride, targetDirty, 0x0123456789abcdefULL});
        cpu({origin + 64 - stride, targetDirty, 0xfedcba9876543210ULL});
        check(candidates == 0 && !d.get_io$$prefetchBusy(), "warmup generated an unintended prediction");
        cpu({origin - 64}, !previousPending);
        watching = true;
    }
    void finish(const std::string &mode, uint64_t start) {
        watching = false;
        d.set_io$$holdCoherentC(0); d.set_io$$holdReleaseAck(0);
        if (mode == "flush") {
            until([&]{return d.get_io$$flushDone();}, "flush retained a cancelled prefetch token");
            d.set_io$$flushRequest(0); tick();
        }
        settle(); flush();
        std::cout << "PREFETCH_LIFETIME_CASE mode=" << mode << " attempts=" << PREFETCH_CANDIDATE_CYCLES
            << " cycles=" << cycles - start << " tokens=" << tokenEvents << " token_samples=" << tokenSamples
            << " allocation_age=" << allocationAge << " allocations=" << allocations
            << " probe_cancel=" << sawProbeCancel << " origin=" << origin
            << " cpu=" << cpuReturned << " dma=" << dmaReturned << " rbeats=" << ddr.rBeats
            << " wbeats=" << ddr.wBeats << '\n';
    }
};

int main(int argc,char **argv) {
    try {
        const std::string negative=argc>1?argv[1]:"";
        injectMismatch=negative=="--inject-mismatch";
        for (const std::string mode : {"clean","dirty","deadline","dirty-deadline","flush","demand",
                "duplicate","store","uncached","probe","dirty-target","no-mshr","reset","denied","page-end"}) {
            CandidateTest t;
            if (mode == "page-end") t.origin += 63 * 64;
            const bool dirty = mode == "dirty" || mode == "dirty-deadline";
            const bool deadline = mode == "deadline" || mode == "dirty-deadline";
            const bool positive = mode == "clean" || mode == "dirty";
            if (mode == "denied") {
                t.d.set_io$$prefetchPrivilege(1); t.d.set_io$$prefetchPmpCfg(0x09);
                t.d.set_io$$prefetchPmpAddress((t.origin + 64)/4);
                t.protectedEnd = t.origin + 64 - base;
            }
            t.warm(dirty,mode=="dirty-target",mode=="no-mshr");
            const auto start=t.cycles;
            t.d.set_io$$holdCoherentC(!positive);
            t.cpu({t.origin},false);
            if (mode == "denied" || mode == "page-end") {
                check(t.tokenEvents == 0, "original authorization exclusion generated a retained token");
                t.finish(mode,start); continue;
            }
            check(t.tokenEvents == 1, "test did not create exactly one authorized sequential token");
            if (positive) {
                t.settle();
                const bool expected = dirty ? PREFETCH_CANDIDATE_CYCLES >= 10 : PREFETCH_CANDIDATE_CYCLES >= 3;
                check(t.allocations == unsigned(expected), "clean/dirty retained-candidate allocation bound mismatch");
                check(!expected || (t.allocationAge >= (dirty?10U:3U) && t.allocationAge<=PREFETCH_CANDIDATE_CYCLES),
                    "retained-candidate allocation latency is outside its derived bound");
            } else if (mode == "reset") {
                t.watching=false; t.coordinatedReset(); t.tick();
                check(!t.d.get_io$$prefetchBusy() && !t.d.cache$candidateValid,
                    "coordinated reset preserved stale candidate authorization");
                for(unsigned n=0;n<20;++n)t.tick();
                check(t.allocations==0, "reset candidate later allocated from a reused owner");
            } else {
                if (mode == "flush") t.d.set_io$$flushRequest(1);
                if (mode == "demand") t.cpuRequest = Request{t.origin + 256};
                if (mode == "duplicate") t.cpuRequest = Request{t.origin + 64};
                if (mode == "store") t.cpuRequest = Request{t.origin + 64 - 2 * CandidateTest::stride,true,0x99aabbccddeeff00ULL};
                if (mode == "uncached") t.cpuRequest = Request{t.origin + 256,false,0,255,true};
                if (mode == "probe") t.dmaRequest = Request{t.origin + 64 - 2 * CandidateTest::stride};
                // A continuously offered same-line read cannot refresh a token.
                if (deadline) t.cpuRequest = Request{t.origin + 8};
                for(unsigned n=0;n<PREFETCH_CANDIDATE_CYCLES+20;++n) {
                    if (negative=="--freeze-deadline" && deadline && n>=PREFETCH_CANDIDATE_CYCLES) {
                        t.d.cache$candidateValid=1;t.d.cache$candidateValid$NEXT=1;t.d.activateAll();
                    }
                    t.tick();
                }
                check(t.allocations==0, "cancelled/deadline candidate acquired a speculative owner");
                check(!t.d.cache$candidateValid && !t.d.get_io$$prefetchBusy(),
                    "expired token added an unbounded context-barrier hold");
                if (deadline) check(t.tokenSamples==PREFETCH_CANDIDATE_CYCLES,
                    "sole-eviction token did not retain exactly its finite budget");
                if (mode=="probe" && PREFETCH_CANDIDATE_CYCLES==16)
                    check(t.sawProbeCancel, "probe did not reach the retained candidate window");
            }
            t.finish(mode,start);
        }
        std::cout << "PREFETCH_CANDIDATE_LIFETIME_PASS attempts=" << PREFETCH_CANDIDATE_CYCLES << '\n';
        return 0;
    } catch(const std::exception &error) {
        std::cerr << "PREFETCH_CANDIDATE_LIFETIME_FAIL " << error.what() << '\n';return 1;
    }
}
