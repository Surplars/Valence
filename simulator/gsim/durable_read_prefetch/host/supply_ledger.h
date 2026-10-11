#pragma once
#include "passive_supply.h"
#include "production_probe.h"
#include "adoption_ledger.h"
#include <fstream>
#include <algorithm>
#include <vector>
#include <set>
#define PC(x) d.board$platform$privateCache$##x
#define PF(x) d.get_cpuSupplyPrefetch$$##x()
struct SupplyLedger {
    PassiveSupply base;
    AdoptionLedger adoption;
    std::ofstream raw{"supply-events.tsv"}, axi{"axi-events.tsv"};
    struct Owner { bool live=false,pf=false,store=false; uint64_t seq=0,pa=0,born=0; bool completed=false,postedBound=false,installed=false; unsigned postedSlot=0,rootSlot=0; uint64_t generation=0,rootGeneration=0,epoch=0; };
    struct Wb { bool live=false,pf=false,store=false; uint64_t seq=0,pa=0,target=0,born=0,ownerSeq=0; unsigned mshr=0; };
    std::array<Owner,2> owners{}; std::array<Wb,2> wb{};
    uint64_t serial=0,wbSerial=0,axiHash=1469598103934665603ULL,axiEvents=0;
    std::array<uint64_t,3> cycles{}, ar{},aw{},r{},w{},b{},rExpected{},wExpected{},captures{},acks{},allocs{},fills{},postedFills{},postedInstalls{};
    std::array<std::map<unsigned,uint64_t>,3> cross;
    std::array<std::array<uint64_t,9>,3> reasons{};
    struct Retry {uint64_t id,cycle,target;unsigned remaining=15;};std::vector<Retry> retry;
    struct Block {uint64_t id=0,line=0,target=0,start=0;bool busyClear=false,offered=false;};
    Block block; uint64_t blockSerial=0,retrySerial=0,guardChecks=0;
    static void require(bool x,const char *s){PassiveSupply::require(x,s);}
    template<class... T> void event(const char *name,uint64_t cycle,T... values){raw<<name<<'\t'<<cycle;((raw<<'\t'<<uint64_t(values)),...);raw<<'\n';}
    void axiEvent(uint64_t cycle,unsigned channel,std::initializer_list<uint64_t> fields) {
        auto word=[&](uint64_t v){axi<<'\t'<<v;for(unsigned i=0;i<8;++i){axiHash^=(v>>(8*i))&255;axiHash*=1099511628211ULL;}};
        axi<<"AXI";word(cycle);word(channel);for(auto v:fields)word(v);axi<<'\n';++axiEvents;
    }
    void bindPosted(unsigned i,uint64_t pa,unsigned slot,uint64_t gen,unsigned root,uint64_t rootGen,uint64_t epoch) {
        require(i<2&&owners[i].live&&!owners[i].pf&&owners[i].pa==pa,"ledger posted binding lacks allocation");
        auto &x=owners[i];
        if(x.postedBound)require(x.postedSlot==slot&&x.generation==gen&&x.rootSlot==root&&x.rootGeneration==rootGen&&x.epoch==epoch,"ledger posted full generation changed");
        else{x.postedBound=true;x.postedSlot=slot;x.generation=gen;x.rootSlot=root;x.rootGeneration=rootGen;x.epoch=epoch;}
    }
    void installed(unsigned i,uint64_t pa,unsigned slot,uint64_t gen,unsigned root,uint64_t rootGen,uint64_t epoch) {
        bindPosted(i,pa,slot,gen,root,rootGen,epoch);auto &x=owners[i];
        require(x.completed&&!x.installed,"ledger posted install lacks unique refill");x.installed=true;
    }
    void retired(unsigned i) {
        require(owners[i].completed&&(!owners[i].postedBound||owners[i].installed),"ledger retired owner lacks refill/install completion");
    }
    void complete(unsigned i,uint64_t pa,bool posted) {
        require(i<2&&owners[i].live&&!owners[i].completed&&owners[i].pa==pa&&(!posted||(!owners[i].pf&&owners[i].postedBound)),
            "ledger completion lacks unique full-PA owner");
        owners[i].completed=true;
    }
    static void requireAccepted(const PassiveSupply::Sample &s){require(s.cacheFire&&s.reqFire&&s.pa.has_value()&&s.meta.has_value(),"ledger event lacks accepted payload");}
    struct Guard {unsigned mask=0,index=0,dup=0,validMask=0,dirtyMask=0,allowedMask=0,preferred=0,replacement=0,otherIndex=0;bool otherValid=false;uint64_t address[2]={},otherPa=0;};
    // Independent full-PA guard; ON permits the dirty alternate only when the
    // other way holds the protected clean store token. No DUT decision is driven.
    // Exact B-profile source formula, for an explicit full PA. It is checked
    // against the DUT on every real pending candidate before being used as a
    // read-only one-step feasibility query for a missed read opportunity.
    template<class D> Guard guard(D &d,uint64_t pa,bool store) {
        require(!(pa&63)&&pa>=0x80200000ULL&&pa<0x100200000ULL,"ledger target full PA/range");
        const unsigned set=(pa>>6)&255;
        bool valid[2],dirty[2],allowed[2];uint64_t resident[2]={};
        const bool otherValid=store?bool(PF(readTokenValid))&&!PF(readTokenConsume):bool(PF(storeTokenValid))&&!PF(storeTokenConsume);
        uint64_t otherPa=0;unsigned otherIndex=0;
        if(otherValid){otherPa=store?PF(readTokenAddress):PF(storeTokenAddress);otherIndex=store?PF(readTokenIndex):PF(storeTokenIndex);}
        Guard g;bool present=false,reserved=false,victimPending=false,free=false,targetPending=false;
        for(unsigned way=0;way<2;++way){unsigned idx=set+256*way;valid[way]=PC(valid)[idx];dirty[way]=valid[way]&&PC(dirty)[idx];
            if(valid[way])resident[way]=(uint64_t(way?PC(tagBanks_1)[set]:PC(tagBanks_0)[set])<<14)|(uint64_t(set)<<6);
            present|=valid[way]&&resident[way]==pa;
            allowed[way]=!(otherValid&&valid[way]&&otherIndex==idx&&resident[way]==otherPa);
        }
        for(unsigned i=0;i<2;++i){g.validMask|=unsigned(valid[i])<<i;g.dirtyMask|=unsigned(dirty[i])<<i;g.allowedMask|=unsigned(allowed[i])<<i;g.address[i]=resident[i];}
        g.replacement=PC(replacement)[set];g.otherValid=otherValid;g.otherPa=otherPa;g.otherIndex=otherIndex;
        unsigned preferred=!valid[0]?0:!valid[1]?1:!dirty[0]?0:!dirty[1]?1:PC(replacement)[set];
        g.preferred=set+256*preferred;unsigned way=allowed[preferred]?preferred:!preferred;g.index=set+256*way;
        for(unsigned i=0;i<2;++i){free|=PC(phase)[i]==0;if(PC(phase)[i]){reserved|=(PC(pendingIndex)[i]&255)==set;targetPending|=(PC(pending$$address)[i]&~63ULL)==pa;}
            if(PC(wbLive)[i])victimPending|=PC(wbAddress)[i]==pa;}
        bool demandMiss=false;
        if(d.board$platform$platformRouter$_io_memory_request_valid_T_2)
            demandMiss=(PC(needsMissSlot)&&!PC(reservedSet))||PC(bypass)||(d.get_dataPathRequest9Meta()&1);
        bool ownerBlocked=PC(liveOwner),releaseBlocked=PC(releaseBusy),victimCreditBlocked=false;
#if READ_PREFETCH_DEMAND_ADOPTION
        if(!store){
            ownerBlocked=(PF(mshrLiveMask)&PF(mshrPrefetchMask)&~unsigned(PF(mshrDemandAttachedMask)))!=0;
            releaseBlocked=(PF(wbLiveMask)&PF(wbPrefetchMask)&~unsigned(PF(wbSentMask)))!=0;
        }
        victimCreditBlocked=valid[way]&&PC(wbLive)[0]&&PC(wbLive)[1];
#endif
        const bool bad[]={!bool(PC(postedPrefetchAllowed)),ownerBlocked,releaseBlocked,present,reserved,victimPending,
            !allowed[way],valid[way]&&dirty[way]&&!store&&!(READ_PREFETCH_DIRTY_RETRY&&!allowed[!way]&&!dirty[!way]),!free,demandMiss,bool(PC(barrier)),bool(PC(flushActive)),
            bool(d.board$platform$core$core$core$backend$systemUnit$_io_fenceIFlush_T),PC(bypassState)!=0,PC(probeState)!=0,
            bool(d.board$platform$coherentHome$probe$sendQueue$_io_deq_valid_T),bool(PC(queuedEvictWanted)),PC(evictionState)!=0,victimCreditBlocked};
        for(unsigned i=0;i<19;++i)g.mask|=unsigned(bad[i])<<i;
#if DURABLE_READ_PREFETCH_CANDIDATE
        // New allocation veto is pre-edge capacity. A same-edge consume does
        // not supply this token; otherwiseEligible intentionally omits this bit.
        g.mask|=unsigned(!store && bool(PF(readTokenValid)))<<19;
#endif
        g.dup=present|(targetPending<<1)|(victimPending<<2);
        if(PF(pendingCandidateValid)&&PF(pendingCandidateAddress)==pa)g.dup|=8;
        return g;
    }
    template<class D> void snapshot(D &d,const Guard &g,uint64_t cycle,unsigned type,uint64_t id,uint64_t pa){
        unsigned wmask=0,freeM=0,sent=0;for(unsigned i=0;i<2;++i){wmask|=unsigned(PC(wbLive)[i])<<i;freeM|=unsigned(PC(phase)[i]==0)<<i;if(PC(wbLive)[i]&&PC(wbSent)[i])sent|=1U<<i;}
        event("TARGET_STATE",cycle,type,id,pa,g.mask,g.dup,g.validMask,g.dirtyMask,g.address[0],g.address[1],g.preferred,g.index,g.replacement,g.allowedMask,g.otherValid,g.otherPa,g.otherIndex,wmask,(~wmask)&3,sent,PC(evictionState),PC(evictionLaneAvailable),freeM);
    }
    template<class D,class Mem> void sample(D &d,Mem &mem,bool roi,bool ended,bool done,uint64_t cycle) {
        ProductionSupplyProbe probe{d};auto s=base.capture(probe);s.cycle=cycle;if(roi)base.count(s);
        unsigned region=roi?1:ended&&!done?2:0;
        if(roi||region==2){
            ++cycles[region];unsigned commits=unsigned(d.get_io$$commit0())+unsigned(d.get_io$$commit1());
            bool translation=(d.get_cpuBandwidthEvents()>>7)&1,blocked=s.reqValid&&!s.reqFire,refill=d.get_io$$cacheProfile$$refillCycle(),eviction=d.get_io$$cacheProfile$$evictionCycle();
            bool storeBlocked=d.get_io$$headProfile$$candidateLoadBlockedByStore(),headMemory=d.get_io$$headProfile$$valid()&&d.get_io$$headProfile$$memory();
            unsigned phase0=PC(phase)[0],phase1=PC(phase)[1];
            unsigned mask=(commits!=0)|(blocked<<1)|(translation<<2)|(refill<<3)|(eviction<<4)|(storeBlocked<<5)|(headMemory<<6)|(s.live<<7)|(s.release<<8)|(s.reqFire<<9)|((d.get_io$$headProfile$$valid()&&!d.get_io$$headProfile$$done()&&d.get_io$$headProfile$$memory())<<10)|(phase0<<11)|(phase1<<14);
            ++cross[region][mask];unsigned reason=commits?0:blocked?1:translation?2:refill?3:eviction?4:storeBlocked?5:headMemory?6:7;++reasons[region][reason];
        }
        // A payload is read only when that channel is valid and accepted.
        if(d.get_io$$ddrAxi$$ar$$valid()&&mem.arReady){++ar[region];rExpected[region]+=d.get_io$$ddrAxi$$ar$$bits$$len()+1;axiEvent(cycle,0,{d.get_io$$ddrAxi$$ar$$bits$$addr(),d.get_io$$ddrAxi$$ar$$bits$$id(),d.get_io$$ddrAxi$$ar$$bits$$len(),d.get_io$$ddrAxi$$ar$$bits$$size(),d.get_io$$ddrAxi$$ar$$bits$$burst()});}
        if(d.get_io$$ddrAxi$$aw$$valid()&&mem.awReady){++aw[region];wExpected[region]+=d.get_io$$ddrAxi$$aw$$bits$$len()+1;axiEvent(cycle,1,{d.get_io$$ddrAxi$$aw$$bits$$addr(),d.get_io$$ddrAxi$$aw$$bits$$id(),d.get_io$$ddrAxi$$aw$$bits$$len(),d.get_io$$ddrAxi$$aw$$bits$$size(),d.get_io$$ddrAxi$$aw$$bits$$burst()});}
        if(mem.rValid&&d.get_io$$ddrAxi$$r$$ready()){auto it=mem.selected();require(it!=mem.pendingReads.end(),"ledger R owner");++r[region];axiEvent(cycle,2,{it->id,mem.heldReadData,uint64_t(it->beat+1==it->count),uint64_t(it->error&&it->beat+1==it->count),it->address+(it->beat<<it->size)});}
        if(mem.wReady&&d.get_io$$ddrAxi$$w$$valid()){require(!mem.pendingWrites.empty(),"ledger W owner");const auto &it=mem.pendingWrites.front();++w[region];axiEvent(cycle,3,{it.id,d.get_io$$ddrAxi$$w$$bits$$data(),d.get_io$$ddrAxi$$w$$bits$$strb(),d.get_io$$ddrAxi$$w$$bits$$last(),it.address+(it.beat<<it.size)});}
        if(mem.bValid&&d.get_io$$ddrAxi$$b$$ready()){auto it=std::find_if(mem.pendingB.begin(),mem.pendingB.end(),[&](const auto &x){return mem.heldB&&x.sequence==*mem.heldB;});require(it!=mem.pendingB.end(),"ledger B owner");++b[region];axiEvent(cycle,4,{it->id,uint64_t(it->error),it->address});}
        if(PF(pendingCandidateValid)){
            auto g=guard(d,PF(pendingCandidateAddress),PF(pendingCandidateStore));
            require((g.mask==0)==bool(PC(canAllocate)),"ledger exact candidate canAllocate disagreement");
#if DURABLE_READ_PREFETCH_CANDIDATE
            constexpr unsigned otherwiseIgnored=(1U<<17)|(1U<<19);
#else
            constexpr unsigned otherwiseIgnored=(1U<<17);
#endif
            require((g.mask&~otherwiseIgnored)==0?bool(PC(otherwiseEligible)):!bool(PC(otherwiseEligible)),"ledger exact candidate otherwiseEligible disagreement");
            require(g.index==PF(candidateVictimIndex),"ledger candidate victim identity disagreement");++guardChecks;
        }
        const auto oldWb=wb;const auto oldOwners=owners;
        // Retiring captured WB identity is consumed before possible same-edge reuse.
        for(unsigned i=0;i<2;++i){
            require(bool(PC(wbLive)[i])==wb[i].live,"ledger WB lifetime disagreement");
            if(wb[i].live){require(PC(wbAddress)[i]==wb[i].pa&&PC(wbMshr)[i]==wb[i].mshr&&bool(PC(wbPrefetch)[i])==wb[i].pf,"ledger WB full identity disagreement");}
            if(PC(phase)[i]){require(owners[i].live&&owners[i].pa==(PC(pending$$address)[i]&~63ULL)&&owners[i].pf==bool(PC(prefetchOwner)[i]),"ledger MSHR identity disagreement");}
            else {if(owners[i].live)retired(i);owners[i].live=false;}
            if(PC(phase)[i]&&PC(postedMshr)[i])bindPosted(i,PC(postedContext$$lineAddress)[i],PC(postedContext$$owner$$slot)[i],PC(postedContext$$owner$$generation)[i],PC(postedContext$$cohortRoot$$slot)[i],PC(postedContext$$cohortRoot$$generation)[i],PC(postedContext$$epoch)[i]);
        }
        if(PC(evictionRetiring)){unsigned i=PC(_ackIndex_T);require(wb[i].live&&PC(wbSent)[i],"ledger ACK lacks sent WB owner");auto x=wb[i];event("WB_ACK",cycle,region,i,x.seq,x.pa,x.pf,x.store,x.target,x.ownerSeq,cycle-x.born);wb[i].live=false;++acks[region];}
        if(PF(wbCapture)){unsigned i=PF(wbCaptureSlot),m=PF(wbCaptureMshr);bool pf=PF(wbCapturePrefetch);require(i<2&&m<2&&!wb[i].live,"ledger WB capture live reuse");
            Wb x;x.live=true;x.pf=pf;x.pa=PF(wbCaptureAddress);x.born=cycle;x.seq=++wbSerial;x.mshr=m;
            if(pf){require(!PF(wbCaptureDirect)&&PF(wbCaptureFromMiss)&&owners[m].live&&owners[m].pf,"ledger PF WB captured stale owner");x.store=owners[m].store;x.target=owners[m].pa;x.ownerSeq=owners[m].seq;}
            wb[i]=x;++captures[region];event("WB_DETAIL",cycle,region,i,x.seq,PF(wbCaptureIndex),x.pa);event("WB_CAPTURE",cycle,region,i,x.seq,x.pa,x.pf,x.store,x.target,x.ownerSeq,PF(wbCaptureDirty),PF(wbCaptureDirect),PF(wbCaptureFromMiss));
        }
        if(PF(refill)){unsigned i=PF(refillSlot);require(i<2&&owners[i].live&&owners[i].pa==(PF(refillAddress)&~63ULL)&&owners[i].pf==bool(PF(refillPrefetch)),"ledger refill identity disagreement");auto x=owners[i];complete(i,x.pa,false);++fills[region];event("REFILL_DETAIL",cycle,region,x.seq,x.pa,PF(refillIndex));event("REFILL",cycle,region,x.seq,x.pa,x.pf,x.store,cycle-x.born,PF(refillError));}
        // Posted store refills are a separate accepted response path, excluded
        // from the existing legacy refill pulse. Read payload only on fire.
        if(PC(_posted_io_refill_valid_T)&&PC(posted$_io_refill_ready_T_22)) {
            require(!PF(refill),"legacy and posted refill overlap");
            unsigned i=PC(posted$io$$refill$$bits$$reservation$$mshr);
            require(i<2&&i==PC(fillMshr)&&PC(postedMshr)[i]&&PC(phase)[i]==3,
                "ledger posted refill lacks reserved fill MSHR");
            uint64_t pa=PC(pending$$address)[i]&~63ULL;complete(i,pa,true);++postedFills[region];
            event("POSTED_REFILL",cycle,region,owners[i].seq,pa,i);
        }
        if(PC(postedInstall)) {
            require(!PF(refill),"legacy refill overlaps posted install");
            unsigned i=PC(posted$io$$install$$bits$$reservation$$mshr),slot=PC(posted$installSlot);
            require(i<2&&slot<2&&PC(postedMshr)[i],"posted install lacks live reserved owner");
            uint64_t pa=PC(posted$io$$install$$bits$$context$$lineAddress);
            installed(i,pa,PC(posted$contexts$$owner$$slot)[slot],PC(posted$contexts$$owner$$generation)[slot],PC(posted$contexts$$cohortRoot$$slot)[slot],PC(posted$contexts$$cohortRoot$$generation)[slot],PC(posted$contexts$$epoch)[slot]);
            ++postedInstalls[region];event("POSTED_INSTALL",cycle,region,owners[i].seq,pa,i,owners[i].postedSlot,owners[i].generation,owners[i].rootSlot,owners[i].rootGeneration,owners[i].epoch);
        }
        for(unsigned store=0;store<2;++store)if(store?PF(storeTokenConsume):PF(readTokenConsume)){
            requireAccepted(s);require(store?PF(storeTokenValid):PF(readTokenValid),"ledger consume invalid token");event("CONSUME",cycle,region,store,store?PF(storeTokenAddress):PF(readTokenAddress),*s.pa,*s.meta);
        }
        if(PF(allocated)||PF(demandAlloc)){
            bool pf=PF(allocated);if(!pf)requireAccepted(s);require(!(pf&&PF(demandAlloc)),"ledger double allocation");unsigned i=pf?PF(allocatedSlot):PF(demandAllocSlot);require(i<2&&!owners[i].live,"ledger allocation live MSHR reuse");
            Owner x;x.live=true;x.pf=pf;x.store=pf?bool(PF(allocatedStore)):bool(*s.meta&1);x.pa=(pf?PF(allocatedAddress):PF(demandAllocAddress))&~63ULL;x.born=cycle;x.seq=++serial;owners[i]=x;++allocs[region];event("ALLOC_DETAIL",cycle,region,x.seq,x.pa,pf?PF(allocatedIndex):PC(index));event("ALLOC",cycle,region,i,x.seq,x.pa,x.pf,x.store);
        }
        // Resolve the previous accepted-read retry against the next cycle's
        // unmodified state. This is feasibility, not an alternative execution.
        for(auto it=retry.begin();it!=retry.end();){auto g=guard(d,it->target,false);bool otherwise=(g.mask&~(1U<<17))==0;
            snapshot(d,g,cycle,1,it->id,it->target);event("RETRY_GUARD",cycle,it->id,it->cycle,it->target,g.mask,g.dup,PC(evictionState),PF(candidate)&&PF(candidateStore));
            if(g.mask==0||!otherwise||!(PC(evictionState)==1||PC(evictionState)==2)||!it->remaining)it=retry.erase(it);else{--it->remaining;++it;}}
        if(block.id&&roi){
            if(!block.busyClear&&!s.live&&!s.release){block.busyClear=true;event("BUSY_CLEAR",cycle,block.id,block.line,block.target,cycle-block.start);}
            if(!block.offered&&s.reqValid&&!(*s.meta&1)&&(*s.pa&~63ULL)==block.target){block.offered=true;event("NEXT_OFFER",cycle,block.id,block.target,cycle-block.start);}
        }
        if(s.cacheFire&&s.ordinary.value_or(false)&&!(*s.meta&1)&&roi){
            uint64_t line=*s.pa&~63ULL;unsigned mask=s.pending|(s.readOwnerBlocked.value_or(s.live)<<1)|(s.readReleaseBlocked.value_or(s.release)<<2)|(s.ownResident<<3)|(!s.posted<<4);
            if(block.id&&line==block.target){event("NEXT_ACCEPT",cycle,block.id,line,cycle-block.start);block={};}
            if(s.sequential.value_or(false)&&s.hint.value_or(false)&&mask){
                if(block.id)event("BLOCK_SUPERSEDED",cycle,block.id,line);
                block={++blockSerial,line,line+64,cycle,false,false};snapshot(d,guard(d,block.target,false),cycle,2,block.id,block.target);event("BLOCK",cycle,block.id,line,line+64,mask);
                for(unsigned i=0;i<2;++i){if(PC(phase)[i]&&PC(prefetchOwner)[i])event("BLOCK_PF",cycle,block.id,i,oldOwners[i].seq,PC(phase)[i],oldOwners[i].pa,oldOwners[i].store,cycle-oldOwners[i].born);
                    if(oldWb[i].live&&oldWb[i].pf)event("BLOCK_WB",cycle,block.id,i,oldWb[i].seq,oldWb[i].pa,oldWb[i].target,oldWb[i].store,oldWb[i].ownerSeq,cycle-oldWb[i].born);}
            } else if(block.id&&line==block.line&&cycle>block.start){
                auto g=guard(d,block.target,false);uint64_t id=++retrySerial;snapshot(d,g,cycle,0,id,block.target);event("SAME_READ",cycle,block.id,id,*s.pa,s.hint.value_or(false),mask,g.dup);
                if(s.hint.value_or(false)&&mask==0)retry.push_back({id,cycle,block.target,15});
            }
            event("READ",cycle,region,*s.pa,s.hint.value_or(false),mask,s.sequential.value_or(false));
        }
        if(s.candidate){require(s.reqFire&&s.pa.has_value(),"ledger candidate lacks accepted address");uint64_t target=(*s.pa&~63ULL)+64;event("CANDIDATE",cycle,region,target,PF(candidateStore),*s.pa);}
        if(s.aValid)event("HOME_A",cycle,region,*s.aPa,probe.aSource(),*s.aFire);
        adoption.sample(d,mem,s,*this,region,cycle);
    }
    void finish(uint64_t expectedCycles,uint64_t tail) {
        require(cycles[1]==expectedCycles&&cycles[2]==tail,"ledger ROI/tail cycle boundaries");
        for(auto x:wb)require(!x.live,"ledger leftover WB");for(auto x:owners)require(!x.live,"ledger leftover MSHR");
        uint64_t aa=0,ff=0,pp=0,pi=0,cc=0,kk=0,rr=0,re=0,ww=0,we=0,wa=0,bb=0;
        for(unsigned q=0;q<3;++q){aa+=allocs[q];ff+=fills[q];pp+=postedFills[q];pi+=postedInstalls[q];cc+=captures[q];kk+=acks[q];rr+=r[q];re+=rExpected[q];ww+=w[q];we+=wExpected[q];wa+=aw[q];bb+=b[q];
            if(q){uint64_t sum=0;for(auto x:reasons[q])sum+=x;require(sum==cycles[q],"ledger exclusive cycles mismatch");}
            std::cout<<"LEDGER_TOTAL region="<<q<<" cycles="<<cycles[q]<<" ar="<<ar[q]<<" aw="<<aw[q]<<" r="<<r[q]<<" w="<<w[q]<<" b="<<b[q]<<" alloc="<<allocs[q]<<" refill="<<fills[q]<<" wb_capture="<<captures[q]<<" wb_ack="<<acks[q]<<" posted_refill="<<postedFills[q]<<" posted_install="<<postedInstalls[q]<<"\n";
            for(unsigned i=0;i<8;++i)std::cout<<"LEDGER_REASON region="<<q<<" reason="<<i<<" count="<<reasons[q][i]<<"\n";
            for(auto [mask,n]:cross[q])std::cout<<"LEDGER_CROSS region="<<q<<" mask="<<mask<<" count="<<n<<"\n";
        }
        require(aa==ff+pp&&pp==pi&&cc==kk&&rr==re&&ww==we&&wa==bb,"ledger transaction conservation");
        std::cout<<"LEDGER_PASS guard_checks="<<guardChecks<<" blocks="<<blockSerial<<" same_reads="<<retrySerial<<" axi_events="<<axiEvents<<" axi_fnv64="<<axiHash<<"\n";
        adoption.finish();
        raw.close();axi.close();
    }
};
#undef PC
#undef PF
