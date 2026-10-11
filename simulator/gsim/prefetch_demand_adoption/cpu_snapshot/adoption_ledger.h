#pragma once
#include <array>
#include <deque>
#include <map>
#include <set>
#include <tuple>
#ifndef READ_PREFETCH_DEMAND_ADOPTION
#define READ_PREFETCH_DEMAND_ADOPTION 0
#endif
#define AD_PC(x) d.board$platform$privateCache$##x
#define AD_PF(x) d.get_cpuSupplyPrefetch$$##x()
// Independent, passive attachment ledger. A hardware PF tag intentionally has
// generation zero; serial provides a host generation across MSHR/source reuse.
// Tag Lo and Hi are both preserved. No observer drives or repairs DUT state.
struct AdoptionLedger {
    struct Tag { uint64_t lo=0,hi=0; bool operator==(const Tag &) const = default; };
    struct Flight {
        bool live=false,pf=false,store=false,issued=false,completed=false,knownError=false;
        uint64_t serial=0,pa=0,born=0,issuedCycle=0,firstR=0,attach=0,ar=0;
        unsigned source=0; Tag tag;
    };
    struct Attachment {
        uint64_t id=0,owner=0,pa=0,address=0,cycle=0,refillCycle=0,responseCycle=0;
        unsigned slot=0,ticket=0; Tag tag; bool refilled=false,error=false,responded=false;
    };
    struct Physical { uint64_t serial=0,address=0,attach=0; bool write=false; };
    std::array<Flight,2> flights{};
    std::map<uint64_t,Attachment> attachments;
    std::array<uint64_t,16> ticketBindings{};
    std::deque<Physical> physical;
    uint64_t serial=0,attachSerial=0,physicalSerial=0,attachResponses=0,knownErrors=0;
    std::array<uint64_t,3> attaches{},responses{},bothLive{},successorAlloc{},successorIssue{},blocked{},noOffer{};
    std::map<std::pair<unsigned,unsigned>,uint64_t> intersections;
    static void require(bool v,const char *message){PassiveSupply::require(v,message);}
    static uint64_t fullPa(uint64_t offset) {
        require(offset<2147483648ULL,"adoption DDR address offset outside pinned 2GiB RAM");
        return 0x80200000ULL+offset;
    }
    template<class L,class... T> static void event(L &l,const char *name,uint64_t cycle,T... fields){l.event(name,cycle,fields...);}
    void allocated(unsigned slot,uint64_t generation,uint64_t pa,bool pf,bool store,uint64_t cycle) {
        require(slot<2&&!flights[slot].live&&!(pa&63),"adoption allocation reused live full-PA generation");
        Flight x;x.live=true;x.serial=generation;x.pa=pa;x.pf=pf;x.store=store;x.born=cycle;flights[slot]=x;
    }
    void issued(unsigned slot,uint64_t pa,unsigned source,Tag tag,uint64_t cycle) {
        require(slot<2&&source<2,"adoption issued slot/source range");auto &f=flights[slot];
        require(f.live&&!f.issued&&f.pa==pa&&!f.completed,"adoption A lacks unique allocation identity");
        for(unsigned i=0;i<2;++i)if(i!=slot&&flights[i].live&&flights[i].issued&&!flights[i].completed)
            require(flights[i].source!=source,"adoption source reloaded before completion");
        require(!(tag.hi&~15ULL)&&((tag.hi>>2)&3)==(f.pf?1U:((tag.hi>>2)&3)),"adoption tag high bits/origin invalid");
        f.issued=true;f.source=source;f.tag=tag;f.issuedCycle=cycle;
    }
    uint64_t attach(unsigned slot,uint64_t generation,uint64_t address,unsigned ticket,Tag tag,uint64_t cycle) {
        require(slot<2&&ticket<2,"adoption attachment slot/ticket range");auto &f=flights[slot];
        require(f.live&&f.serial==generation&&f.pa==(address&~63ULL)&&f.pf&&!f.store&&f.issued&&!f.completed&&!f.knownError&&!f.attach&&f.tag==tag,
            "adoption attachment lacks unique issued read-PF full-PA generation");
        require(!ticketBindings[ticket],"adoption attachment reused bound ticket");
        Attachment a;a.id=++attachSerial;a.owner=generation;a.pa=f.pa;a.address=address;a.slot=slot;a.ticket=ticket;a.tag=tag;a.cycle=cycle;
        attachments.emplace(a.id,a);ticketBindings[ticket]=a.id;f.attach=a.id;return a.id;
    }
    void bound(unsigned slot,uint64_t address,unsigned ticket,bool owned) {
        require(slot<2&&ticket<2,"adoption live binding slot/ticket range");const auto &f=flights[slot];
        require(f.live&&f.attach&&attachments.contains(f.attach),"adoption lost attachment binding");const auto &a=attachments.at(f.attach);
        require(a.owner==f.serial&&a.address==address&&a.ticket==ticket&&ticketBindings[ticket]==a.id&&owned,
            "adoption live full-PA/ticket/word-offset binding changed");
    }
    void refill(unsigned slot,uint64_t address,Tag tag,bool attached,unsigned ticket,bool error,uint64_t cycle) {
        require(slot<2,"adoption refill slot range");auto &f=flights[slot];
        require(f.live&&f.issued&&!f.completed&&f.pa==(address&~63ULL)&&f.tag==tag&&attached==bool(f.attach),
            "adoption refill lost full tag/origin/generation");
        if(f.knownError)require(error,"adoption registered error lost before refill");
        f.completed=true;
        if(f.attach){auto &a=attachments.at(f.attach);require(a.address==address&&a.ticket==ticket&&!a.refilled,"adoption refill lost attached word/ticket");a.refilled=true;a.error=error;a.refillCycle=cycle;}
    }
    void response(uint64_t id,uint64_t address,bool write,bool error,uint64_t cycle) {
        require(attachments.contains(id),"adoption physical response has unknown attachment");auto &a=attachments.at(id);
        require(a.refilled&&!a.responded&&!write&&a.address==address&&a.error==error&&cycle>a.refillCycle,
            "adoption actual CPU response missing/duplicate/early/wrong payload binding");
        a.responded=true;a.responseCycle=cycle;++attachResponses;
    }
    template<class D,class Mem,class L> void sample(D &d,Mem &mem,const PassiveSupply::Sample &s,L &l,unsigned region,uint64_t cycle) {
        const unsigned live=AD_PF(mshrLiveMask),attached=AD_PF(mshrDemandAttachedMask),known=AD_PF(mshrKnownErrorMask);
        require(!(live&~3U)&&!(attached&~3U)&&!(known&~3U),"adoption B MSHR mask range");
        // Payload arrays are indexed only by a live owner. Stale prefetch bits
        // and unused ticket/word fields do not qualify an identity.
        for(unsigned i=0;i<2;++i){auto &f=flights[i];
            if(!(live&(1U<<i))){
                if(f.live){require(f.completed,"adoption MSHR vanished before refill");if(f.attach){const auto &a=attachments.at(f.attach);require(a.refilled&&ticketBindings[a.ticket]==a.id,"adoption retired owner lost ticket binding");ticketBindings[a.ticket]=0;}}
                f.live=false;require(!(attached&(1U<<i))&&!(known&(1U<<i)),"adoption stale attachment/error after free");continue;
            }
            require(f.live&&f.pa==(AD_PC(pending$$address)[i]&~63ULL)&&f.pf==bool((AD_PF(mshrPrefetchMask)>>i)&1),"adoption live MSHR generation/origin mismatch");
            if(f.pf)require(f.store==bool((AD_PF(mshrStoreMask)>>i)&1),"adoption immutable PF store/read origin changed");
            require(bool(attached&(1U<<i))==bool(f.attach),"adoption DUT/host attached lifetime mismatch");
            if(f.attach&&f.completed){require(!(AD_PF(readTokenValid)&&AD_PF(readTokenAddress)==f.pa)&&!(AD_PF(storeTokenValid)&&AD_PF(storeTokenAddress)==f.pa),"adoption attached refill fabricated resident token");}
            if(f.attach){unsigned ticket=AD_PC(pendingTicket)[i];bound(i,AD_PC(pending$$address)[i],ticket,(AD_PF(responseOwnedMask)>>ticket)&1);}
            if(known&(1U<<i)){
                require(f.issued&&!f.completed&&AD_PC(phase)[i]==3,"adoption known error has no issued fill owner");
                if(!f.knownError){f.knownError=true;++knownErrors;event(l,"ATTACH_KNOWN_ERROR",cycle,region,i,f.serial,f.pa,f.tag.lo,f.tag.hi);}
            } else if(f.knownError&&!f.completed)require(false,"adoption known error vanished before refill");
        }
        uint64_t currentAttachment=0;
        if(AD_PF(demandAttach)){
            require(READ_PREFETCH_DEMAND_ADOPTION&&s.cacheFire&&s.reqFire&&s.pa&&s.meta&&s.ordinary.value_or(false)&&!(*s.meta&1),"adoption event lacks accepted ordinary physical read");
            unsigned i=AD_PF(demandAttachSlot),ticket=AD_PF(demandAttachTicket);
            require(i<2&&AD_PF(demandAttachReady)&&!AD_PF(demandAlloc)&&!(AD_PF(responseOwnedMask)&(1U<<ticket))&&!AD_PF(acquireResponsePending),"adoption crossed request/ticket/refill exclusion");
            require(*s.pa==AD_PF(demandAttachAddress)&&AD_PC(phase)[i]==3&&(AD_PF(mshrAcquireIssuedMask)&(1U<<i))&&!(known&(1U<<i)),"adoption qualified payload/lifetime mismatch");
            currentAttachment=attach(i,flights[i].serial,*s.pa,ticket,flights[i].tag,cycle);++attaches[region];
            event(l,"DEMAND_ATTACH",cycle,region,currentAttachment,i,flights[i].serial,*s.pa,flights[i].pa,ticket,(*s.pa>>3)&7,flights[i].tag.lo,flights[i].tag.hi,live,known);
        }
        if(s.reqFire){require(s.pa&&s.meta,"adoption physical fire lacks payload");physical.push_back({++physicalSerial,*s.pa,currentAttachment,bool(*s.meta&1)});}
        if(AD_PF(acquireIssued)){
            require(s.aValid&&s.aFire.value_or(false)&&s.aPa&&AD_PF(acquireTagBits)==68,"adoption A-issued observation lacks accepted complete 68-bit tag");
            unsigned i=AD_PF(acquireIssuedSlot);Tag tag{AD_PF(acquireIssuedTagLo),AD_PF(acquireIssuedTagHi)};
            issued(i,*s.aPa,ProductionSupplyProbe<D>{d}.aSource(),tag,cycle);
            event(l,"ACQUIRE_ISSUED",cycle,region,i,flights[i].serial,flights[i].pa,flights[i].pf,flights[i].store,flights[i].source,tag.lo,tag.hi,live);
            if(flights[i].pf&&!flights[i].store)for(unsigned j=0;j<2;++j)if(j!=i&&flights[j].live&&flights[j].attach&&flights[j].pa!=flights[i].pa&&!flights[j].completed&&!(AD_PF(refill)&&AD_PF(refillSlot)==j)){++successorIssue[region];event(l,"ATTACH_SUCCESSOR_ISSUED",cycle,region,flights[j].attach,flights[j].serial,flights[j].pa,flights[i].serial,flights[i].pa,live,flights[j].firstR);}
        }
        // All acquire responses, including the posted path, retain one A tag.
        const bool postedRefill=AD_PC(_posted_io_refill_valid_T)&&AD_PC(posted$_io_refill_ready_T_22);
        if(AD_PF(refill)||postedRefill){
            unsigned i=AD_PF(refillSlot);require(i<2,"adoption refill index range");
            bool isAttached=AD_PF(refillDemandAttached);unsigned ticket=isAttached?AD_PF(refillTicket):0;
            uint64_t address=AD_PF(refillAddress);Tag tag{AD_PF(refillTagLo),AD_PF(refillTagHi)};
            refill(i,address,tag,isAttached,ticket,AD_PF(refillError),cycle);
            event(l,"ACQUIRE_REFILL",cycle,region,i,flights[i].serial,address,flights[i].pf,flights[i].store,flights[i].attach,tag.lo,tag.hi,AD_PF(refillError));
            if(isAttached)event(l,"ATTACH_REFILL",cycle,region,flights[i].attach,i,flights[i].serial,address,ticket,tag.lo,tag.hi,AD_PF(refillError));
        }
        if(AD_PF(allocated)||AD_PF(demandAlloc)){
            const bool pf=AD_PF(allocated);unsigned i=pf?AD_PF(allocatedSlot):AD_PF(demandAllocSlot);uint64_t pa=(pf?AD_PF(allocatedAddress):AD_PF(demandAllocAddress))&~63ULL;
            allocated(i,++serial,pa,pf,pf?bool(AD_PF(allocatedStore)):bool(s.meta.value_or(0)&1),cycle);
            require(i<2&&l.owners[i].seq==flights[i].serial,"adoption/supply allocation generation disagreement");
            if(pf&&!flights[i].store)for(unsigned j=0;j<2;++j)if(j!=i&&flights[j].live&&flights[j].attach&&flights[j].pa!=pa&&!flights[j].completed){++successorAlloc[region];event(l,"ATTACH_SUCCESSOR_ALLOC",cycle,region,flights[j].attach,flights[j].serial,flights[j].pa,flights[i].serial,pa,live,flights[j].firstR);}
        }
        if(d.get_io$$ddrAxi$$ar$$valid()&&mem.arReady){uint64_t pa=fullPa(d.get_io$$ddrAxi$$ar$$bits$$addr())&~63ULL;for(unsigned i=0;i<2;++i){auto &f=flights[i];if(f.live&&f.pa==pa){require(f.issued&&!f.completed&&++f.ar==1,"adoption duplicate DDR AR for one full-PA owner generation");event(l,"OWNER_AR",cycle,region,i,f.serial,f.pa,f.attach,d.get_io$$ddrAxi$$ar$$bits$$id());}}}
        if(mem.rValid&&d.get_io$$ddrAxi$$r$$ready()){auto it=mem.selected();require(it!=mem.pendingReads.end(),"adoption R has no accepted AR");uint64_t pa=fullPa(it->address)&~63ULL;for(auto &f:flights)if(f.live&&f.pa==pa&&!f.firstR){f.firstR=cycle;event(l,"OWNER_FIRST_R",cycle,region,f.serial,f.pa,f.attach,it->id);}}
        if(d.get_dataPathEvents()&(1ULL<<21)){
            require(!physical.empty(),"adoption physical response lacks accepted request");auto p=physical.front();physical.pop_front();
            if(p.attach){response(p.attach,p.address,p.write,d.get_dataPathReply0Flags()!=0,cycle);++responses[region];const auto &a=attachments.at(p.attach);event(l,"ATTACH_CPU_RESPONSE",cycle,region,a.id,a.owner,a.address,a.ticket,a.tag.lo,a.tag.hi,d.get_dataPathReply0Data(),d.get_dataPathReply0Flags());}
        }
        unsigned attachedLive=__builtin_popcount(attached&live),ownersLive=__builtin_popcount(live);
        if(attachedLive&&ownersLive==2)++bothLive[region];
        if(region){blocked[region]+=s.reqValid&&!s.reqFire;noOffer[region]+=!s.reqValid;unsigned mask=(s.reqValid?1:0)|(s.reqFire?2:0)|(attachedLive?4:0)|(ownersLive==2?8:0)|(s.live?16:0)|(s.release?32:0);++intersections[{region,mask}];}
    }
    void finish() const {
        require(physical.empty()&&attachSerial==attachResponses,"adoption accepted demand/CPU response conservation");
        for(const auto &f:flights)require(!f.live,"adoption MSHR not drained");for(auto id:ticketBindings)require(!id,"adoption response ticket not drained");
        for(const auto &[id,a]:attachments)require(a.refilled&&a.responded,"adoption attachment lost refill/CPU response");
        if(!READ_PREFETCH_DEMAND_ADOPTION)require(!attachSerial,"adoption OFF produced attachment");
        for(unsigned q=0;q<3;++q)std::cout<<"ADOPTION_TOTAL region="<<q<<" attach="<<attaches[q]<<" actual_cpu_response="<<responses[q]<<" both_owners_live_cycles="<<bothLive[q]<<" successor_alloc_before_refill="<<successorAlloc[q]<<" successor_a_before_refill="<<successorIssue[q]<<" blocked="<<blocked[q]<<" no_offer="<<noOffer[q]<<"\n";
        for(const auto &[key,n]:intersections)std::cout<<"ADOPTION_CROSS region="<<key.first<<" mask="<<key.second<<" count="<<n<<"\n";
        std::cout<<"ADOPTION_PASS attached="<<attachSerial<<" actual_cpu_response="<<attachResponses<<" known_error_owners="<<knownErrors<<" known_error_path="<<(knownErrors?"OBSERVED":"NOT_EXERCISED")<<" cache_e_cycle=UNKNOWN resident_useful_semantics=UNCHANGED\n";
    }
};
#undef AD_PC
#undef AD_PF
