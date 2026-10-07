// Passive scalar observation of existing GSIM fields. The runner verifies each
// field's emitted FIR definition before reusing either model. No DUT mutation.
#include "frontend_observer.h"
struct DataCacheCounts {
    uint64_t cycles=0,hits=0,misses=0,empty=0,replacements=0,readMiss=0,writeMiss=0;
    uint64_t dirtyEvictions=0,writebackBeats=0,writebackLines=0,probeRequests=0,probeDataBeats=0;
    uint64_t missBlocked=0,bypassBlocked=0,probeBlocked=0,refillCycles=0,evictionCycles=0;
    uint64_t zeroCommitMissBlocked=0,states[12]={};
    void sample(SBoardSocGsim &d) {
        ++cycles;
        bool fire=d.board$platform$privateCache$cpuFire;
        bool ordinary=d.board$platform$privateCache$ordinary;
        bool found=d.board$platform$privateCache$found;
        bool miss=d.get_io$$cacheProfile$$readMiss()||d.get_io$$cacheProfile$$writeMiss();
        if(miss!=(fire&&ordinary&&!found))throw std::runtime_error("passive D-cache miss equivalence failed");
        hits+=fire&&ordinary&&found; misses+=miss;
        empty+=d.get_io$$cacheProfile$$emptySlotMiss(); replacements+=d.get_io$$cacheProfile$$replacementMiss();
        readMiss+=d.get_io$$cacheProfile$$readMiss(); writeMiss+=d.get_io$$cacheProfile$$writeMiss();
        dirtyEvictions+=d.get_io$$cacheProfile$$dirtyEviction();
        // _T_25 is C.fire && state==evictSend; _T_265 is C.fire && state==probeSend.
        bool writeback=d.board$platform$privateCache$_T_25&&d.board$platform$privateCache$victimDirty;
        writebackBeats+=writeback; writebackLines+=writeback&&d.board$platform$privateCache$releaseBeat==7;
        probeRequests+=d.board$platform$privateCache$probeRead;
        probeDataBeats+=d.board$platform$privateCache$_T_265&&d.board$platform$privateCache$probeDirty;
        missBlocked+=d.get_io$$cacheProfile$$missBlocked(); bypassBlocked+=d.get_io$$cacheProfile$$bypassBlocked();
        probeBlocked+=d.get_io$$cacheProfile$$probeBlocked(); refillCycles+=d.get_io$$cacheProfile$$refillCycle();
        evictionCycles+=d.get_io$$cacheProfile$$evictionCycle();
        zeroCommitMissBlocked+=d.get_io$$cacheProfile$$missBlocked()&&!d.get_io$$commit0()&&!d.get_io$$commit1();
        auto state=d.board$platform$privateCache$state;
        if(state>=12)throw std::runtime_error("invalid D-cache state");++states[state];
    }
    void report(const std::string &name) const {
        if(misses!=empty+replacements||misses!=readMiss+writeMiss)throw std::runtime_error("D-cache miss partition mismatch");
        std::cout<<"DCACHE name="<<name<<" cycles="<<cycles<<" hits="<<hits<<" misses="<<misses
          <<" empty="<<empty<<" replacements="<<replacements<<" read_miss="<<readMiss<<" write_miss="<<writeMiss
          <<" dirty_evictions="<<dirtyEvictions<<" writeback_beats="<<writebackBeats<<" writeback_lines="<<writebackLines
          <<" probes="<<probeRequests<<" probe_data_beats="<<probeDataBeats<<" miss_blocked="<<missBlocked
          <<" bypass_blocked="<<bypassBlocked<<" probe_blocked="<<probeBlocked<<" refill_cycles="<<refillCycles
          <<" eviction_cycles="<<evictionCycles<<" zero_commit_miss_blocked="<<zeroCommitMissBlocked;
        for(unsigned i=0;i<12;++i)std::cout<<" state_"<<i<<"="<<states[i];std::cout<<"\n";
    }
};
struct DataCacheObserver: FrontendObserver {
    DataCacheCounts allData,roiData;
    static void sample(SBoardSocGsim &d,void *p) {
        auto &o=*static_cast<DataCacheObserver*>(p);bool previouslyActive=o.active;
        FrontendObserver::sample(d,static_cast<FrontendObserver*>(&o));
        o.allData.sample(d);if(previouslyActive||o.active)o.roiData.sample(d);
    }
    void report(){FrontendObserver::report();allData.report("whole_run");if(finished)roiData.report("coremark_roi");}
};
struct LocalityObserver {
    uint64_t startPc=0,endPc=0;bool active=false;
    DataCacheCounts current;PerfCounts ipc;
    unsigned completed=0;
    static void sample(SBoardSocGsim &d,void *p) {
        auto &o=*static_cast<LocalityObserver*>(p);
        bool begin=(d.get_io$$commit0()&&d.get_io$$commit0Pc()==o.startPc)||(d.get_io$$commit1()&&d.get_io$$commit1Pc()==o.startPc);
        bool end=(d.get_io$$commit0()&&d.get_io$$commit0Pc()==o.endPc)||(d.get_io$$commit1()&&d.get_io$$commit1Pc()==o.endPc);
        if(begin){if(o.active)throw std::runtime_error("nested locality ROI");o.current={};o.ipc={};o.active=true;}
        if(o.active){o.current.sample(d);o.ipc.sample(d);}
        if(end){if(!o.active)throw std::runtime_error("unowned locality ROI end");
            const auto name="locality_"+std::to_string(o.completed++);o.current.report(name);o.ipc.report(name.c_str());o.active=false;}
    }
};
