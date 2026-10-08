#define CACHE_HOME_EMBED
#include "coherent_cache_home.cpp"
#ifndef PREFETCH_ENABLED
#define PREFETCH_ENABLED 0
#endif
struct PrefetchTest: Test {
    uint64_t candidates=0, allocations=0, useful=0, errors=0, busyCycles=0;
    unsigned peakPrefetch=0,peakDemand=0,peakPrefetchRelease=0;
    std::optional<uint64_t> protectedEnd;
    PrefetchTest() {
        readyAlways=true;
        observer=[&] {
            candidates+=d.get_io$$prefetchEvents$$candidate();
            allocations+=d.get_io$$prefetchEvents$$allocated();
            useful+=d.get_io$$prefetchEvents$$useful();
            errors+=d.get_io$$prefetchEvents$$error();
            busyCycles+=d.get_io$$prefetchBusy();
            const unsigned owners=d.get_io$$prefetchEvents$$missOwners();
            check(owners<=1&&owners<=occupancy(),"prefetch ownership budget exceeded");
            peakPrefetch=std::max(peakPrefetch,owners);peakDemand=std::max(peakDemand,occupancy()-owners);
            peakPrefetchRelease=std::max(peakPrefetchRelease,unsigned(d.get_io$$prefetchEvents$$releaseOwners()));
            if(protectedEnd && d.get_io$$ddrAxi$$ar$$valid() && ddr.arReady) {
                const uint64_t begin=d.get_io$$ddrAxi$$ar$$bits$$addr();
                const uint64_t bytes=(uint64_t(d.get_io$$ddrAxi$$ar$$bits$$len())+1)*8;
                check(begin+bytes<=*protectedEnd,"independent host protection range violation");
            }
        };
    }
    void settle() { drainCpu();drainDma();until([&]{return !d.get_io$$prefetchBusy()&&grants.empty()&&!releasePending;},"autonomous prefetch drain deadlock"); }
    void adjacent(unsigned count) {
        for(unsigned n=0;n<count;++n) {
            while(cpuExpected.size()>=2) tick();
            cpu({base+8ULL*n},false);
        }
        settle();
    }
    void report(const char*name,uint64_t start) {
        std::cout<<"PREFETCH_CASE name="<<name<<" cycles="<<cycles-start<<" accepted="<<cpuAccepted
            <<" returned="<<cpuReturned<<" candidates="<<candidates<<" allocations="<<allocations
            <<" useful="<<useful<<" errors="<<errors<<" busy="<<busyCycles<<" reads="<<ddr.reads
            <<" peak_read_ids="<<ddr.peakReadIds<<" peak_mshr="<<peakOccupied<<" peak_prefetch="<<peakPrefetch<<" peak_demand="<<peakDemand
            <<" peak_prefetch_release="<<peakPrefetchRelease<<" releases="<<releaseLines<<"\n";
    }
};
int main(int argc,char**argv) { try {
    const bool bypass=argc>1&&std::string(argv[1])=="--bypass-permission";
    const bool corrupt=argc>1&&std::string(argv[1])=="--inject-mismatch";
    injectMismatch=corrupt;
    {
        PrefetchTest t;
        t.d.set_io$$prefetchPrivilege(1);t.d.set_io$$prefetchPmpCfg(0x09);
        t.d.set_io$$prefetchPmpAddress((base+128)/4);t.protectedEnd=128;
        t.d.set_io$$bypassPrefetchAuthorization(bypass);
        t.cpu({base});t.cpu({base+64});t.settle();
        check(t.allocations==0,"denied next-line allocated prefetch");
        if(bypass)throw std::runtime_error("permission negative did not exercise forbidden read");
        t.report("pmp-denied",0);
    }
    {
        PrefetchTest t;const auto start=t.cycles;t.adjacent(8192);t.report("adjacent64k",start);
        check(t.cpuAccepted==8192&&t.cpuReturned==8192,"stream lost demand owners");
        check(t.allocations<=1024&&t.ddr.reads<=1024+32,"one-line traffic budget exceeded");
#if PREFETCH_ENABLED
        check(t.allocations>100&&t.useful>100&&t.ddr.peakReadIds>=2,"prefetch failed to expose real parallel reads");
#endif
        t.flush();
    }
    {
        PrefetchTest t;const auto start=t.cycles;
        for(unsigned n=0;n<256;++n)t.cpu({base+64ULL*((n*37)%1024)});
        t.settle();check(t.allocations==0,"nonsequential dependent chase generated prefetch");t.report("chase",start);
    }
    {
        PrefetchTest t;t.cpu({base+3968});t.cpu({base+4032});t.settle();
        check(t.allocations==0,"next-line crossed 4KiB boundary");t.report("page-end",0);
    }
#if PREFETCH_ENABLED
    {
        PrefetchTest t;t.ddr.denyReadAddress=128;t.cpu({base});t.cpu({base+64});t.settle();
        check(t.errors==1&&t.cpuReturned==2,"prefetch error leaked CPU response or retained owner");
        t.ddr.denyReadAddress.reset();t.cpu({base+128});t.settle();t.flush();t.report("prefetch-error",0);
    }
    {
        PrefetchTest t;
        for(unsigned n=0;n<512;++n)t.cpu({base+64ULL*((n*37)%512)});
        t.cpu({base+64ULL*512});
        t.cpu({base+64ULL*7}); // break prediction history before the second input fill
        t.cpu({base+64ULL*513});t.settle();
        // Install both predictor inputs without generating a speculative owner.
        // Then replay hits with the victim lane idle so the prediction alone
        // owns the clean Release being held, independent of hint lifetime.
        t.cpu({base+64ULL*512});
        const auto before=t.allocations;
        t.d.set_io$$holdReleaseAck(1);
        t.cpu({base+64ULL*513},false);
        // Existing clean victim is read while the background target reserves
        // this set. Its saved response must survive the following eviction.
        t.cpu({base+64ULL*2},false);
        t.drainCpu();
        t.until([&]{return t.allocations>before&&t.occupancy()==0&&t.grants.empty();},"prefetch did not finish ahead of delayed ReleaseAck",2000);
        check(t.peakPrefetchRelease==1&&t.releasePending>0&&t.d.get_io$$prefetchBusy(),"late prefetch ReleaseAck escaped busy ownership");
        for(unsigned n=0;n<32;++n){t.tick();check(t.d.get_io$$prefetchBusy(),"busy dropped before delayed prefetch Ack");}
        t.d.set_io$$holdReleaseAck(0);t.settle();t.flush();t.report("late-clean-ack",0);
    }
    {
        PrefetchTest t;t.cpu({base});t.d.set_io$$holdGrantAck(1);t.cpu({base+64},false);
        t.until([&]{return t.allocations>0&&t.d.get_io$$grantAckOffer()&&t.ddr.pendingReads.empty();},"no in-flight prefetch for E stall");
        check(t.d.get_io$$prefetchBusy(),"prefetch busy omitted held GrantAck");
        t.d.set_io$$flushRequest(1);for(unsigned n=0;n<20;++n){t.tick();check(!t.d.get_io$$flushDone(),"flush crossed held GrantAck");}
        t.d.set_io$$holdGrantAck(0);t.until([&]{return t.d.get_io$$flushDone();},"flush with in-flight prefetch deadlocked");
        t.d.set_io$$flushRequest(0);t.tick();t.settle();t.report("flush-held-e",0);
    }
    {
        PrefetchTest t;t.stream(0,512,true);const auto writes=t.ddr.writes;
        t.cpu({base+512ULL*64});t.cpu({base+513ULL*64});t.settle();
        check(t.allocations==0,"prefetch evicted a dirty-only victim set");
        check(t.ddr.writes-writes==2,"dirty demand replacement wrote unexpected extra victims");
        t.flush();t.report("dirty-victim-suppressed",0);
    }
    {
        PrefetchTest t;t.cpu({base});t.cpu({base+64},false);
        // Allocation alone is not external ownership: an earlier DMA write
        // may legitimately finish before Acquire and need no invalidation.
        // Wait for the actual accepted target Acquire, then race its fill.
        t.until([&]{return std::any_of(t.grants.begin(),t.grants.end(),[&](const auto&g){return g.second.address==base+128;});},"probe test lacked accepted prefetch Acquire",2000);
        t.dma({base+128,true,0x8877665544332211ULL});t.drainCpu();t.cpu({base+128});t.settle();
        check(t.probes>0,"DMA did not probe prefetched ownership");t.flush();t.report("probe-inflight",0);
    }
    {
        PrefetchTest t;t.cpu({base});t.d.set_io$$holdGrantAck(1);t.cpu({base+64},false);
        t.until([&]{return t.allocations>0&&t.d.get_io$$prefetchBusy();},"reset test lacked autonomous owner");
        t.coordinatedReset();t.tick();check(!t.d.get_io$$prefetchBusy(),"reset retained autonomous owner");
        t.cpu({base+128});t.settle();t.report("coordinated-reset",0);
    }
    {
        PrefetchTest t;t.blockCpu=true;t.cpu({base},false);t.cpu({base+64},false);
        t.until([&]{return t.candidates>0;},"no candidate for flush cancellation");
        t.d.set_io$$flushRequest(1);t.blockCpu=false;
        t.until([&]{return t.d.get_io$$flushDone();},"flush failed with pending candidate/demand");
        check(!t.d.get_io$$prefetchBusy(),"flush completed with autonomous owner");
        t.d.set_io$$flushRequest(0);t.tick();t.settle();t.report("flush-candidate",0);
    }
#endif
    std::cout<<"DATA_PREFETCH_PASS enabled="<<PREFETCH_ENABLED<<"\n";return 0;
 }catch(const std::exception&e){std::cerr<<"DATA_PREFETCH_FAIL "<<e.what()<<"\n";return 1;} }
