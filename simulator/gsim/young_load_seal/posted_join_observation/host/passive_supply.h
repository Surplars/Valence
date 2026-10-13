#pragma once
#ifndef MEMORY_SCHEDULE_OVERLAP
#define MEMORY_SCHEDULE_OVERLAP 0
#endif
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>

#ifndef READ_PREFETCH_DIRTY_RETRY
#define READ_PREFETCH_DIRTY_RETRY 0
#endif
struct PassiveSupply {
    struct Sample {
        uint64_t cycle=0;
        bool reqValid=false,reqFire=false,cacheFire=false,flush=false;
        std::optional<uint64_t> pa,meta;
        std::optional<bool> hint,ordinary,sequential;
        bool retry=false;
        bool candidate=false,allocate=false,candidateRead=false,allocateRead=false;
        bool pending=false,live=false,release=false,ownResident=false,posted=false;
        std::optional<bool> readOwnerBlocked,readReleaseBlocked;
        bool aValid=false;
        std::optional<bool> aFire,sameSet,sameLine,sourceBusy,directoryFull;
        std::optional<uint64_t> aPa;
    };
    bool historyValid=false,historySequential=false;uint64_t historyLine=0;
    uint64_t opportunities=0,readCandidates=0,readAllocations=0,candidates=0,allocations=0;
    uint64_t requestValid=0,requestFire=0,homeValid=0,homeFire=0;
    std::array<uint64_t,32> opportunityMasks{};
    std::array<uint64_t,8> homeBlockedMasks{};
    std::map<unsigned,Sample> opportunityWitnesses,homeWitnesses;
    static void require(bool p,const char *message){if(!p)throw std::runtime_error(message);}
    static unsigned setOf(uint64_t pa){require(!(pa&63),"passive home PA alignment");return unsigned((pa>>6)&255);}
    static bool active(unsigned phase){require(phase<=4,"passive home phase range");return phase!=0;}
    static unsigned source(unsigned value){require(value<2,"passive home source range");return value;}
    template<class P> Sample capture(P &p) {
        Sample s;s.reqValid=p.reqValid();s.reqFire=p.reqFire();s.cacheFire=p.cacheFire();s.flush=p.flush();
        require(!s.reqFire||s.reqValid,"passive request fire without valid");
        require(s.reqFire==p.independentReqFire(),"passive request event aliases differ");
        if(s.reqValid){s.pa=p.reqPa();s.meta=p.reqMeta();s.hint=p.hint();}
        if(s.cacheFire){
            require(s.reqFire,"passive cache fire lacks physical fire");s.ordinary=p.ordinary();
            if(*s.ordinary&&!(*s.meta&1)){
                const bool dutValid=p.historyValid();
                require(dutValid==historyValid,"passive independent read history validity");
                if(dutValid)require(p.historyLine()==historyLine,"passive independent read history line");
                const uint64_t line=*s.pa>>6;s.sequential=historyValid&&line&&line==historyLine+1;
                s.retry=READ_PREFETCH_DIRTY_RETRY&&historyValid&&line==historyLine&&historySequential;
                if(!historyValid||line!=historyLine)historySequential=*s.sequential;
                historyValid=true;historyLine=line;
            }
        }
        // This fixed profile does not break read history on stores. Only flush
        // clears it; the separate store-history nonordinary clear is unrelated.
        if(s.cacheFire&&!s.ordinary.value_or(false))historySequential=false;
        if(s.flush){historyValid=false;historySequential=false;}
        s.candidate=p.candidate();s.allocate=p.allocate();
        if(s.candidate)s.candidateRead=!p.candidateStore();
        if(s.allocate)s.allocateRead=!p.allocateStore();
        s.pending=p.pending();s.live=p.live();s.release=p.release();
        if constexpr(requires { p.readOwnerBlocked(); p.readReleaseBlocked(); }) {
            s.readOwnerBlocked=p.readOwnerBlocked();s.readReleaseBlocked=p.readReleaseBlocked();
        }
        s.ownResident=p.readResident()&&!p.readConsume();s.posted=p.posted();
        s.aValid=p.aValid();
        if(s.aValid){
            s.aFire=p.aFire();s.aPa=p.aPa();const unsigned set=setOf(*s.aPa),aSource=source(p.aSource());
            bool same=false,busy=false,sameLine=false;
            std::array<bool,512> reserved{};
            for(unsigned i=0;i<2;++i)if(active(p.homePhase(i))){
                same|=setOf(p.homePa(i))==set;busy|=source(p.homeSource(i))==aSource;
                sameLine|=(p.homePa(i)>>6)==(*s.aPa>>6);
#if MEMORY_SCHEDULE_OVERLAP
                const unsigned slot=p.homeDirectory(i);
                require(slot<512&&(slot&255)==setOf(p.homePa(i)),
                    "passive transient directory slot geometry");
                require(!reserved[slot]&&!p.owned(slot),
                    "passive transient directory reservation collision");
                reserved[slot]=true;
#endif
            }
            s.sameSet=same;s.sameLine=sameLine;s.sourceBusy=busy;
#if MEMORY_SCHEDULE_OVERLAP
            s.directoryFull=(p.owned(set)||reserved[set])&&(p.owned(set+256)||reserved[set+256]);
            require(!*s.aFire||(!sameLine&&!busy&&!*s.directoryFull),
                "passive home accepted a known blocker");
#else
            s.directoryFull=p.owned(set)&&p.owned(set+256);
            require(!*s.aFire||(!same&&!busy&&!*s.directoryFull),"passive home accepted a known blocker");
#endif
        }
        // A-ready without A-valid is intentionally not read or manufactured.
        return s;
    }
    void count(const Sample &s) {
        requestValid+=s.reqValid;requestFire+=s.reqFire;
        candidates+=s.candidate;allocations+=s.allocate;readCandidates+=s.candidateRead;readAllocations+=s.allocateRead;
        if((s.sequential.value_or(false)||s.retry)&&s.hint.value_or(false)){
            require(s.cacheFire&&s.reqFire&&s.ordinary.value_or(false)&&!(*s.meta&1),"passive opportunity eligibility");
            require(!s.flush,"passive opportunity coincides with flush");
            const unsigned mask=s.pending|(s.readOwnerBlocked.value_or(s.live)<<1)|(s.readReleaseBlocked.value_or(s.release)<<2)|(s.ownResident<<3)|(!s.posted<<4);
            ++opportunities;++opportunityMasks[mask];opportunityWitnesses.try_emplace(mask,s);
            require(s.candidateRead==(mask==0),"passive formation mask does not explain candidate");
        }
        if(s.aValid){
            ++homeValid;homeFire+=*s.aFire;
            if(!*s.aFire){
                const unsigned mask=(MEMORY_SCHEDULE_OVERLAP?*s.sameLine:*s.sameSet)|(*s.sourceBusy<<1)|(*s.directoryFull<<2);
                ++homeBlockedMasks[mask];homeWitnesses.try_emplace(mask,s);
            }
        }
    }
    template<class P> void sample(P &p,bool roi,uint64_t cycle){Sample s=capture(p);s.cycle=cycle;if(roi)count(s);}
    static void witness(const char *kind,unsigned mask,const Sample &s){
        std::cout<<"PASSIVE_SUPPLY_WITNESS kind="<<kind<<" cycle="<<s.cycle<<" mask="<<mask;
        auto optional=[](const char *name,const auto &x){std::cout<<" "<<name<<"=";if(x)std::cout<<*x;else std::cout<<"UNKNOWN";};
        std::cout<<" req_valid="<<s.reqValid<<" req_fire="<<s.reqFire;
        optional("read_owner_blocked",s.readOwnerBlocked);optional("read_release_blocked",s.readReleaseBlocked);
        optional("req_pa",s.pa);optional("req_meta",s.meta);optional("hint",s.hint);optional("ordinary",s.ordinary);optional("read_sequential",s.sequential);
        std::cout<<" read_candidate="<<s.candidateRead<<" read_allocate="<<s.allocateRead
            <<" pending="<<s.pending<<" live_pf="<<s.live<<" release="<<s.release<<" own_read_resident="<<s.ownResident<<" posted_allowed="<<s.posted<<" a_valid="<<s.aValid;
        optional("a_fire_ready_when_valid",s.aFire);optional("a_pa",s.aPa);optional("transient_same_set",s.sameSet);optional("source_busy",s.sourceBusy);optional("directory_full",s.directoryFull);std::cout<<"\n";
    }
    void report(uint64_t expectedCandidates,uint64_t expectedAllocations)const{
        require(candidates==expectedCandidates&&allocations==expectedAllocations,"passive original aggregate mismatch");
        uint64_t o=0,h=0;for(auto n:opportunityMasks)o+=n;for(auto n:homeBlockedMasks)h+=n;
        require(o==opportunities&&h+homeFire==homeValid,"passive exclusive bucket conservation");
        require(readCandidates==opportunityMasks[0],"passive formed candidates do not close all-clear opportunities");
        std::cout<<"PASSIVE_SUPPLY_COUNTS opportunities="<<opportunities<<" read_candidates="<<readCandidates<<" read_allocations="<<readAllocations
            <<" req_valid="<<requestValid<<" req_fire="<<requestFire<<" home_a_valid="<<homeValid<<" home_a_fire="<<homeFire<<" home_a_blocked="<<h<<" home_other_gates=UNKNOWN\n";
        for(unsigned i=0;i<32;++i)if(opportunityMasks[i])std::cout<<"PASSIVE_OPPORTUNITY_BUCKET mask="<<i<<" count="<<opportunityMasks[i]<<"\n";
        for(unsigned i=0;i<8;++i)if(homeBlockedMasks[i])std::cout<<"PASSIVE_HOME_BLOCK_BUCKET mask="<<i<<" count="<<homeBlockedMasks[i]<<"\n";
        for(const auto &[m,s]:opportunityWitnesses)witness("read_opportunity",m,s);
        for(const auto &[m,s]:homeWitnesses)witness("home_blocked",m,s);
    }
};
