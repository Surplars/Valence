#define CACHE_HOME_EMBED
#include "coherent_cache_home.cpp"
struct Focus : Test {
    struct Write { uint64_t address; unsigned count, beat; };
    std::deque<Write> writes;
    unsigned allocations=0, staleDirtyDemands=0, memoryBeats=0, injectedLive=0;
    bool injectLive=false, corruptWrite=false;
    void settle() { drainCpu(); until([&]{return !d.get_io$$prefetchBusy()&&grants.empty()&&!releasePending;},"prefetch did not drain"); tick(); }
    Focus(bool live=false,bool corrupt=false):injectLive(live),corruptWrite(corrupt) {
        readyAlways=true;
        observer=[&]{
            allocations+=d.get_io$$prefetchEvents$$allocated();
            if(d.get_io$$ddrAxi$$aw$$valid()&&ddr.awReady) writes.push_back({base+d.get_io$$ddrAxi$$aw$$bits$$addr(),unsigned(d.get_io$$ddrAxi$$aw$$bits$$len())+1,0});
            if(d.get_io$$ddrAxi$$w$$valid()&&ddr.wReady) {
                check(!writes.empty(),"independent writeback had no AW owner"); auto &w=writes.front();
                const auto address=w.address+8*w.beat; auto actual=uint64_t(d.get_io$$ddrAxi$$w$$bits$$data());
                if(corruptWrite)actual^=1;
                check(d.get_io$$ddrAxi$$w$$bits$$strb()==255,"independent writeback byte mask mismatch");
                check(actual==architectural.at(address),"independent writeback byte oracle mismatch");
                ++memoryBeats; ++w.beat; if(w.beat==w.count)writes.pop_front();
            }
            if(d.get_io$$miss() && d.cache$phase[d.cache$evictMshr]==0 && d.cache$startEviction && d.cache$dirty[d.cache$evictIndex] && d.cache$prefetchOwner[d.cache$evictMshr]) {
                check(d.cache$phase[d.cache$evictMshr]==0,"direct demand did not use FREE MSHR"); ++staleDirtyDemands;
                std::cout<<"STALE_DIRTY_DEMAND cycle="<<cycles<<" mshr="<<unsigned(d.cache$evictMshr)<<" phase=FREE index="<<unsigned(d.cache$evictIndex)<<std::endl;
            }
            if(injectLive && !injectedLive && d.get_io$$prefetchEvents$$allocated()) {
                for(unsigned m=0;m<2;++m)if(d.cache$phase$NEXT[m]==1&&d.cache$prefetchOwner$NEXT[m]) {
                    const auto index=d.cache$pendingIndex$NEXT[m];
                    check(!d.cache$dirty$NEXT[index],"negative fixture victim was already dirty");
                    d.cache$dirty$NEXT[index]=1; d.activateAll(); ++injectedLive;
                    std::cout<<"INJECT_LIVE_PREFETCH_DIRTY cycle="<<cycles<<" mshr="<<m<<" phase=evictWait index="<<unsigned(index)<<std::endl;
                }
            }
        };
    }
};
int main(int argc,char**argv) {try {
    const std::string arg=argc>1?argv[1]:"";
    if(arg=="--live-prefetch-dirty") {
        Focus t(true);
        t.cpu({base+64});t.cpu({base+5*64});t.settle();
        t.cpu({base+7*64});t.cpu({base+8*64});t.settle();
        check(false,"live prefetch dirty negative was not detected");
    }
    Focus t(false,arg=="--corrupt-writeback");
    t.cpu({base,true,0x1122334455667788ULL});t.cpu({base+4*64,true,0xaabbccddeeff0042ULL});
    t.cpu({base+2*64});t.cpu({base+3*64});t.settle();
    const auto before=t.allocations;
    t.cpu({base+3*64});t.cpu({base+4*64});t.settle();
    check(t.allocations==before+1,"setup did not complete one prefetch");
    check(t.d.cache$phase[0]==0&&t.d.cache$prefetchOwner[0],"setup did not leave stale prefetch bit in FREE MSHR0");
    std::cout<<"FREE_OWNER_REUSE_READY cycle="<<t.cycles<<" mshr=0 old_prefetch=1 dirty_set=0"<<std::endl;
    t.cpu({base+8*64});t.settle();
    check(t.staleDirtyDemands==1,"focused test missed direct dirty demand on freed prefetch owner");
    t.cpu({base});t.cpu({base+4*64});t.settle();
    t.flush();
    check(t.memoryBeats>=16&&t.writes.empty(),"independent writeback oracle missed dirty data");
    check(t.cpuAccepted==t.cpuReturned,"demand reply ledger did not close");
    std::cout<<"PREFETCH_OWNER_PASS cycles="<<t.cycles<<" prefetch_allocations="<<t.allocations<<" stale_dirty_demand="<<t.staleDirtyDemands<<" memory_beats="<<t.memoryBeats<<" replies="<<t.cpuReturned<<" full_backing_words="<<t.architectural.size()<<std::endl;
    return 0;
}catch(const std::exception&e){std::cerr<<"PREFETCH_OWNER_FAIL "<<e.what()<<std::endl;return 1;}}
