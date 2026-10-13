#pragma once
#include "policy_oracle.h"
#include <cstdlib>
#include <fstream>
#include <string>

#ifndef LOCKED_STORE_PREFETCH_LRU
#error "The actual emitted profile must explicitly bind the host victim policy"
#endif
static_assert(LOCKED_STORE_PREFETCH_LRU == 0 || LOCKED_STORE_PREFETCH_LRU == 1);

// All history comes from accepted events. DUT replacement/victim decisions are
// comparison targets only, never initial state or updates of either model.
struct AcceptedVictimPolicy {
    using Policy = lru_victim_oracle::Policy;
    Policy model{256, bool(LOCKED_STORE_PREFETCH_LRU)};
    Policy flipped{256, !bool(LOCKED_STORE_PREFETCH_LRU)};
    struct Owner { bool live=false,pf=false,store=false,attached=false,completed=false;
        uint64_t pa=0; unsigned index=0; };
    std::array<Owner,2> owners{};
    uint64_t samples=0,bootSamples=0,resetSamples=0,historyChecks=0,hits=0,installs=0,errors=0,choices=0;
    bool mutated=false,seenReset=false;
    const std::string mutation = std::getenv("CPU_LRU_ORACLE_MUTATION") ? std::getenv("CPU_LRU_ORACLE_MUTATION") : "";
    static void require(bool ok,const char *why) { lru_victim_oracle::require(ok,why); }
    AcceptedVictimPolicy() { require(mutation.empty()||mutation=="policy"||mutation=="history","unknown host policy mutation"); }
    template<class F> void both(F f) { f(model); f(flipped); }
    template<class D> void begin(D &d) {
        ++samples;
        if(d.reset) {
            seenReset=true;++resetSamples;model=Policy(256,bool(LOCKED_STORE_PREFETCH_LRU));
            flipped=Policy(256,!bool(LOCKED_STORE_PREFETCH_LRU));owners={};return;
        }
        require(seenReset,"policy observer did not see the real reset");
        for(unsigned set=0;set<256;++set) {
            const auto &s=model.state(uint64_t(set)*64);
            require(s.oldest==d.board$platform$privateCache$replacement[set],"independent accepted-event LRU history mismatch");
            require(s.oldest==flipped.state(uint64_t(set)*64).oldest,"host paired history drift");
            for(unsigned way=0;way<2;++way) {
                const unsigned index=set+256*way;const bool valid=d.board$platform$privateCache$valid[index];
                require(s.ways[way].valid==valid,"independent accepted-event residency mismatch");
                if(valid) {
                    const uint64_t pa=(uint64_t(way?d.board$platform$privateCache$tagBanks_1[set]:d.board$platform$privateCache$tagBanks_0[set])<<14)|(uint64_t(set)<<6);
                    require(s.ways[way].address==pa,"independent accepted-event full PA mismatch");
                    require(s.ways[way].dirty==bool(d.board$platform$privateCache$dirty[index]),"independent accepted-event dirty history mismatch");
                }
            }
            ++historyChecks;
        }
    }
    unsigned replacement(uint64_t pa) const { return model.state(pa).oldest; }
    unsigned choose(uint64_t pa,bool store) {
        ++choices;
        return (mutation=="policy"?flipped:model).choose(pa,true,store).way;
    }
    template<class D> void end(D &d) {
        if(d.reset)return;
        // Capture accepted identities before applying same-edge writes.
        bool hit=false,write=false;uint64_t hitPa=0;
        if(d.get_cpuTagged$$cache$$valid()&&d.get_cpuTagged$$cache$$ready()&&d.get_cpuTagged$$cache$$ordinary()) {
            hitPa=d.get_cpuTagged$$cache$$address();write=d.get_cpuTagged$$cache$$write();
            hit=bool(model.find(hitPa));
            require(hit==bool(d.board$platform$privateCache$found),"accepted hit full-PA identity mismatch");
            require(!hit||!d.board$platform$privateCache$posted$accepted,"posted merge crossed resident hit");
        }
        const bool refill=d.get_cpuSupplyPrefetch$$refill();
        const bool posted=d.board$platform$privateCache$postedInstall;
        bool install=false,prefetch=false,storeOrigin=false,dirty=false;uint64_t pa=0;unsigned index=0,owner=0;
        if(refill) {
            owner=d.get_cpuSupplyPrefetch$$refillSlot();require(owner<2,"policy refill owner range");
            auto &o=owners[owner];pa=d.get_cpuSupplyPrefetch$$refillAddress()&~63ULL;index=d.get_cpuSupplyPrefetch$$refillIndex();
            require(o.live&&!o.completed&&o.pa==pa&&o.index==index,"policy refill lost accepted allocation identity");
            require(o.pf==bool(d.get_cpuSupplyPrefetch$$refillPrefetch())&&o.attached==bool(d.get_cpuSupplyPrefetch$$refillDemandAttached()),"policy refill origin/attachment drift");
            install=!d.get_cpuSupplyPrefetch$$refillError();prefetch=o.pf&&!o.attached;storeOrigin=o.store;dirty=!o.pf&&o.store;
            o.completed=true;if(!install)++errors;
        }
        if(posted) {
            require(!refill,"policy posted and legacy install overlap");
            owner=d.board$platform$privateCache$posted$io$$install$$bits$$reservation$$mshr;
            require(owner<2,"policy posted install owner range");auto &o=owners[owner];
            pa=d.board$platform$privateCache$posted$io$$install$$bits$$context$$lineAddress&~63ULL;
            index=d.board$platform$privateCache$posted$io$$install$$bits$$reservation$$set+256*d.board$platform$privateCache$posted$io$$install$$bits$$reservation$$way;
            require(o.live&&!o.pf&&!o.completed&&o.pa==pa&&o.index==index,"policy posted install lost accepted allocation identity");
            install=true;dirty=true;prefetch=false;storeOrigin=true;o.completed=true;
        }
        require(install==bool(d.get_cpuSupplyPrefetch$$installValid()),"policy accepted install handshake mismatch");
        if(install)require(pa==(d.get_cpuSupplyPrefetch$$installAddress()&~63ULL)&&index==d.get_cpuSupplyPrefetch$$installIndex()&&dirty==bool(d.get_cpuSupplyPrefetch$$installDirty()),"policy installed identity mismatch");
        // RTL priority: probe and WB invalidation, accepted hit, then install.
        if(d.board$platform$privateCache$probeFire) {
            const uint64_t address=d.board$platform$coherentHome$probe$io$$probe$$bits$$address;
            both([&](Policy &p){p.invalidate(address);});
        }
        if(d.get_cpuSupplyPrefetch$$wbCapture()) {
            const uint64_t address=d.get_cpuSupplyPrefetch$$wbCaptureAddress();
            const bool wasDirty=d.get_cpuSupplyPrefetch$$wbCaptureDirty();
            both([&](Policy &p){p.capture(address,wasDirty);});
        }
        if(hit) {
            const unsigned way=*model.find(hitPa);
            const bool skip=mutation=="history"&&!mutated&&model.state(hitPa).oldest!=1-way&&
                !(install&&((pa>>6)&255)==((hitPa>>6)&255));
            if(skip)mutated=true;
            else both([&](Policy &p){p.hit(hitPa,write);});
            ++hits;
        }
        if(install) {
            require(index<512&&(index&255)==((pa>>6)&255),"policy install index/set mismatch");
            both([&](Policy &p){p.install(pa,index/256,dirty,prefetch,storeOrigin,false);});++installs;
        }
        if(d.get_cpuSupplyPrefetch$$demandAttach()) {
            const unsigned i=d.get_cpuSupplyPrefetch$$demandAttachSlot();require(i<2,"policy attach owner range");auto &o=owners[i];
            require(o.live&&o.pf&&!o.store&&!o.attached&&!o.completed&&o.pa==(d.get_cpuSupplyPrefetch$$demandAttachAddress()&~63ULL),"policy attach lost immutable read-prefetch owner");o.attached=true;
        }
        if(d.get_cpuSupplyPrefetch$$allocated()||d.get_cpuSupplyPrefetch$$demandAlloc()) {
            const bool pf=d.get_cpuSupplyPrefetch$$allocated();
            require(!(pf&&d.get_cpuSupplyPrefetch$$demandAlloc()),"policy double allocation");
            const unsigned i=pf?d.get_cpuSupplyPrefetch$$allocatedSlot():d.get_cpuSupplyPrefetch$$demandAllocSlot();require(i<2,"policy allocation owner range");
            require(!owners[i].live||owners[i].completed,"policy live allocation reuse");
            if(!pf)require(d.get_cpuTagged$$cache$$valid()&&d.get_cpuTagged$$cache$$ready(),"policy demand allocation lacks accepted request");
            const uint64_t address=(pf?d.get_cpuSupplyPrefetch$$allocatedAddress():d.get_cpuSupplyPrefetch$$demandAllocAddress())&~63ULL;
            const unsigned idx=pf?d.get_cpuSupplyPrefetch$$allocatedIndex():d.board$platform$privateCache$index;
            owners[i]={true,pf,pf?bool(d.get_cpuSupplyPrefetch$$allocatedStore()):bool(d.get_cpuTagged$$cache$$write()),false,false,address,idx};
        }
    }
    template<class D> void boot(D &d) { ++bootSamples;begin(d);end(d); }
    void finish() const {
        std::ofstream out("policy-audit.json");
        out<<"{\"status\":\"PASS_ACCEPTED_EVENT_POLICY_HISTORY\",\"samples\":"<<samples
           <<",\"boot_samples\":"<<bootSamples<<",\"reset_samples\":"<<resetSamples
           <<",\"history_checks\":"<<historyChecks<<",\"hits\":"<<hits<<",\"installs\":"<<installs
           <<",\"error_refills\":"<<errors<<",\"candidate_queries\":"<<choices
           <<",\"store_prefetch_lru\":"<<LOCKED_STORE_PREFETCH_LRU<<"}\n";
    }
};
