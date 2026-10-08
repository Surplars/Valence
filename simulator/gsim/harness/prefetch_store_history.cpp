#define main originalPrefetchFixtureMain
#include "data_prefetch.cpp"
#undef main
#ifndef PREFETCH_BREAK_ON_STORE
#define PREFETCH_BREAK_ON_STORE 0
#endif
#ifndef HISTORY_ORIGIN_OFFSET
#define HISTORY_ORIGIN_OFFSET 0
#endif

struct HistoryTest : PrefetchTest {
    const uint64_t origin=base+HISTORY_ORIGIN_OFFSET;
    bool expectedValid=false;
    uint64_t expectedLine=0, historyChecks=0, acceptedStores=0, heldStoreOffers=0;
    HistoryTest() {
        auto previous=observer;
        observer=[&,previous] {
            previous();
            check(bool(d.cache$lastValid)==expectedValid,"independent accepted-request history validity mismatch");
            if(expectedValid) check(d.cache$lastLine==expectedLine,"independent accepted-request history address mismatch");
            ++historyChecks;
            const bool fire=d.io$$cpu$$request$$valid&&d.get_io$$cpu$$request$$ready();
            const bool write=d.io$$cpu$$request$$bits$$write;
            const uint64_t address=d.io$$cpu$$request$$bits$$address;
            const bool ordinary=address>=base && address+8<=base+BOARD_DDR_BYTES &&
                !d.io$$cpu$$request$$bits$$atomic && !d.io$$cpu$$request$$bits$$virtualized &&
                !d.io$$cpu$$request$$bits$$uncached;
            heldStoreOffers+=d.io$$cpu$$request$$valid&&write&&!fire;
            if(fire && ordinary && !write){expectedValid=true;expectedLine=address>>6;}
            if(fire && ordinary && write){++acceptedStores;if(PREFETCH_BREAK_ON_STORE)expectedValid=false;}
            if(d.io$$flushRequest)expectedValid=false;
        };
    }
    void resetTogether(){coordinatedReset();expectedValid=false;tick();}
    void finish(const char *name){settle();flush();std::cout<<"PREFETCH_STORE_HISTORY_CASE name="<<name
        <<" break="<<PREFETCH_BREAK_ON_STORE<<" history_checks="<<historyChecks<<" accepted_stores="<<acceptedStores
        <<" held_store_offers="<<heldStoreOffers<<" candidates="<<candidates<<" allocations="<<allocations
        <<" cpu="<<cpuReturned<<" dma="<<dmaReturned<<" rbeats="<<ddr.rBeats<<" wbeats="<<ddr.wBeats<<"\n";}
};

int main(int argc,char **argv){try{
    const std::string negative=argc>1?argv[1]:"";
    injectMismatch=negative=="--inject-mismatch";
    {
        HistoryTest t;t.cpu({t.origin});const auto before=t.candidates;
        t.cpu({t.origin+64});t.settle();check(t.candidates==before+1,"pure read stream lost prediction");
        t.finish("reads-preserved");
    }
    for(const char *mode:{"store-hit","store-miss","failed-store","uncached-store","held-store-reply"}){
        HistoryTest t;t.cpu({t.origin});
        const bool same=std::string(mode)=="store-hit"||std::string(mode)=="held-store-reply";
        const bool uncached=std::string(mode)=="uncached-store";
        const bool held=std::string(mode)=="held-store-reply";
        if(std::string(mode)=="failed-store")t.ddr.denyReadAddress=(t.origin+1024-base)&~63ULL;
        t.blockCpu=held;
        t.cpu({same?t.origin:t.origin+1024,true,0x8877665544332211ULL,255,uncached},!held);
        if(negative=="--ignore-store-break" && PREFETCH_BREAK_ON_STORE && !uncached){
            t.d.cache$lastValid=1;t.d.cache$lastValid$NEXT=1;t.d.activateAll();
        }
        t.tick();
        check(bool(t.d.cache$lastValid)==(!PREFETCH_BREAK_ON_STORE||uncached),"accepted store history break mismatch");
        if(held){for(unsigned n=0;n<20;++n)t.tick();check(!t.cpuExpected.empty(),"store response was not held");t.blockCpu=false;}
        t.settle();t.ddr.denyReadAddress.reset();
        const auto before=t.candidates;t.cpu({t.origin+64});t.settle();
        check(t.candidates==before+unsigned(!PREFETCH_BREAK_ON_STORE||uncached),"store/read candidate boundary mismatch");
        const auto resume=t.candidates;t.cpu({t.origin+128});t.settle();
        check(t.candidates==resume+1,"prediction did not resume on consecutive reads");
        t.finish(mode);
    }
    {
        HistoryTest t;t.cpu({t.origin});t.d.set_io$$holdCoherentD(1);t.cpu({t.origin+4096},false);
        t.cpuRequest=Request{t.origin,true,0x123456789abcdef0ULL};
        for(unsigned n=0;n<24;++n){
            if(negative=="--clear-on-offer") {t.d.cache$lastValid=0;t.d.cache$lastValid$NEXT=0;t.d.activateAll();}
            t.tick();check(t.cpuRequest.has_value(),"held store unexpectedly fired through blocked fill");
            check(t.d.cache$lastValid && t.d.cache$lastLine==(t.origin+4096)/64,"unaccepted store erased live history");
        }
        check(t.heldStoreOffers>=24,"store-offer backpressure witness missing");
        t.d.set_io$$holdCoherentD(0);t.drainCpu();t.tick();
        check(bool(t.d.cache$lastValid)==!PREFETCH_BREAK_ON_STORE,"accepted held store did not end history at fire");
        const auto before=t.candidates;t.cpu({t.origin+4160});t.settle();
        check(t.candidates==before+unsigned(!PREFETCH_BREAK_ON_STORE),"held-store follow-on prediction mismatch");
        t.finish("offered-versus-accepted");
    }
    {
        HistoryTest t;t.cpu({t.origin});t.dma({t.origin,true,0x13579bdf2468ace0ULL});t.settle();
        check(t.probes>0,"probe history fixture missed coherence probe");
        const auto before=t.candidates;t.cpu({t.origin+64});t.settle();
        check(t.candidates==before+1,"DMA probe incorrectly classified as accepted CPU store");
        t.finish("probe-preserves-history");
    }
    for(const char *mode:{"flush","reset","denied","page-end"}){
        HistoryTest t;
        const uint64_t a=std::string(mode)=="page-end"?t.origin+3968:t.origin;
        t.cpu({a});
        if(std::string(mode)=="flush")t.flush();
        if(std::string(mode)=="reset")t.resetTogether();
        if(std::string(mode)=="denied"){
            t.d.set_io$$prefetchPrivilege(1);t.d.set_io$$prefetchPmpCfg(0x09);
            t.d.set_io$$prefetchPmpAddress((a+128)/4);t.protectedEnd=a+128-base;
        }
        const auto before=t.candidates;t.cpu({a+64});t.settle();
        check(t.candidates==before,"history reset/protection boundary generated a candidate");
        t.finish(mode);
    }
    std::cout<<"PREFETCH_STORE_HISTORY_PASS break="<<PREFETCH_BREAK_ON_STORE<<"\n";return 0;
}catch(const std::exception &error){std::cerr<<"PREFETCH_STORE_HISTORY_FAIL "<<error.what()<<"\n";return 1;}}
