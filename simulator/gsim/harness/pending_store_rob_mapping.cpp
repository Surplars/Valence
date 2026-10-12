#include "PendingStoreRobMappingGsim.h"
#include "pending_store_proof_reference.h"
#include <cstring>
#include <iostream>
#include <optional>
#include <type_traits>
#ifndef PENDING_STORE_SLOTS
#define PENDING_STORE_SLOTS 1
#endif
using namespace pending_store_reference;
struct Owner { bool valid = false; unsigned slot = 0; Proof proof{}; };
struct Input {
    std::array<Owner,3> owners{};
    unsigned head=0, eligible=0, clear=0, bind=0, pmp=0x1f, ownerDeny=0;
    uint64_t loadAddress=ram+64;
    unsigned loadSize=3;
    bool poisonInvalid=true;
    bool pause=false, flush=false, stable=true, hit=true, load=false;
    unsigned pbmt=0;
    uint32_t epoch=7, replyEpoch=7;
    uint64_t replyPa=ram;
    Proof loadProof{{14,0x8000000000001401ULL},7,va,ram,false,3,255};
    std::optional<Token> consume;
};
struct Snapshot {
    std::array<std::optional<Proof>,2> proofs{};
    unsigned ownerMap=0,disjointMap=0;
    unsigned bound=0,reserved=0,proved=0;
    bool query=false,write=false;
    uint64_t queryAddress=0;
    unsigned querySize=0;
    std::optional<Proof> load;
    bool loadAllowed=false;
    bool storeResult=false, resultValid=false, resultFresh=false, resultStore=false, resultAllowed=false;
    unsigned resultRow=0;
    std::optional<Proof> result;
    bool operator==(const Snapshot &) const = default;
};
struct Transaction { Proof proof; bool hit; unsigned pbmt; uint32_t replyEpoch; };
static std::string mode;
static uint64_t totalCycles=0,totalResults=0,totalProofs=0,totalQueries=0,totalLoads=0,distinctOwnerEdges=0;
static bool corruptionApplied=false;
static uint64_t mappedEdges=0,disjointEdges=0,overlapEdges=0,poisonEdges=0;
struct Bench {
    SPendingStoreRobMappingGsim dut;
    Input in;
    Tables tables;
    std::optional<Transaction> pending;
    std::map<Token,Proof> certified;
    std::optional<std::pair<Proof,bool>> loadCertificate;
    uint64_t cycles=0;
    Bench() {
        static_assert(std::is_trivially_copyable_v<SPendingStoreRobMappingGsim>);
        std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();
        tick(true);tick(true);tick();tick();
    }
    const Owner *owner(Token t) const {
        const Owner *found=nullptr;
        for(const auto &o:in.owners) if(o.valid && o.slot==t.index) found=&o;
        return found;
    }
    bool matches(const Proof &p, const std::string &omit="") const {
        const Owner *o=owner(p.token);
        if(!o || (o==&in.owners[0] && in.ownerDeny)) return false;
        const bool tag = omit=="tag" ? (o->proof.token.tag & ~(1ULL<<63))==(p.token.tag & ~(1ULL<<63)) : o->proof.token.tag==p.token.tag;
        return o->proof.token.index==p.token.index && tag && (omit=="va" || o->proof.original==p.original) &&
            (omit=="size" || o->proof.size==p.size) && (omit=="mask" || o->proof.mask==p.mask) && p.write;
    }
    bool cleared(const Proof &p) const {
        return (in.clear & (1u<<p.token.index)) || (in.consume && *in.consume==p.token);
    }
    bool permitted(const Transaction &t) const {
        const auto &p=t.proof;
        if(!t.hit || t.pbmt || t.replyEpoch!=p.epoch || p.size>3) return false;
        const uint64_t bytes=1ULL<<p.size;
        if((p.original&(bytes-1)) || (p.physical&(bytes-1)) || (p.original&4095)!=(p.physical&4095)) return false;
        if(p.mask!=lanes(p.physical,p.size)) return false;
        const __uint128_t end=__uint128_t(p.physical)+bytes;
        return p.physical>=ram && end<=__uint128_t(ram)+ramBytes &&
            tables.normalAllowed(p.original,p.write,p.size,in.pmp);
    }
    void owner(unsigned port,unsigned index,uint64_t tag,uint64_t address=va,unsigned size=3,unsigned mask=255) {
        in.owners[port]={true,index,{{index,tag},in.epoch,address,ram+(address-va),true,size,mask}};
        in.eligible|=1u<<index;
    }
    Snapshot tick(bool reset=false) {
        dut.set_reset(reset);
        const unsigned mutation=mode=="--mutate-producer-valid"?1:mode=="--mutate-index"?2:mode=="--mutate-producer-full-token"?3:0;
        dut.set_io$$mutation(mutation);
        dut.set_io$$ownerDeny(in.ownerDeny);
        dut.set_io$$poisonInvalid(in.poisonInvalid);
        dut.set_io$$loadAddress(in.loadAddress);
        dut.set_io$$loadSize(in.loadSize);
#define OWNER(N) \
        dut.set_io$$owner##N##$$valid(in.owners[N].valid); \
        dut.set_io$$slot##N(in.owners[N].slot); \
        dut.set_io$$owner##N##$$bits$$token$$index(in.owners[N].proof.token.index); \
        dut.set_io$$owner##N##$$bits$$token$$tag(in.owners[N].proof.token.tag); \
        dut.set_io$$owner##N##$$bits$$address(in.owners[N].proof.original); \
        dut.set_io$$owner##N##$$bits$$size(in.owners[N].proof.size); \
        dut.set_io$$owner##N##$$bits$$mask(in.owners[N].proof.mask)
        OWNER(0);OWNER(1);OWNER(2);
#undef OWNER
        dut.set_io$$head(in.head);dut.set_io$$queryEligible(in.eligible);dut.set_io$$clearOwners(in.clear);
        dut.set_io$$pause(in.pause);dut.set_io$$flush(in.flush);dut.set_io$$stable(in.stable);dut.set_io$$epoch(in.epoch);
        dut.set_io$$bind(in.bind);dut.set_io$$pmpCfg(in.pmp);dut.set_io$$pmpAddress(allPmp);
        dut.set_io$$consume$$valid(in.consume.has_value());
        dut.set_io$$consume$$bits$$index(in.consume?in.consume->index:15);
        dut.set_io$$consume$$bits$$tag(in.consume?in.consume->tag:UINT64_MAX);
        dut.set_io$$load$$valid(in.load);dut.set_io$$load$$bits$$token$$index(in.loadProof.token.index);
        dut.set_io$$load$$bits$$token$$tag(in.loadProof.token.tag);dut.set_io$$load$$bits$$address(in.loadProof.original);
        dut.set_io$$load$$bits$$size(in.loadProof.size);
        dut.set_io$$reply$$valid(in.hit);dut.set_io$$reply$$bits$$physicalAddress(in.replyPa);
        dut.set_io$$reply$$bits$$epoch(in.replyEpoch);dut.set_io$$reply$$bits$$pbmt(in.pbmt);
        dut.step();++cycles;
        Snapshot c,r;
#define READ_PROOF(S,P,N) \
        if(dut.get_io$$##P##$$proof##N##$$valid()) (S).proofs[N]=Proof{ \
            {unsigned(dut.get_io$$##P##$$proof##N##$$bits$$token$$index()),uint64_t(dut.get_io$$##P##$$proof##N##$$bits$$token$$tag())}, \
            uint32_t(dut.get_io$$##P##$$proof##N##$$bits$$epoch()),uint64_t(dut.get_io$$##P##$$proof##N##$$bits$$payload$$address()), \
            uint64_t(dut.get_io$$##P##$$proof##N##$$bits$$payload$$physicalAddress()),bool(dut.get_io$$##P##$$proof##N##$$bits$$payload$$write()), \
            unsigned(dut.get_io$$##P##$$proof##N##$$bits$$payload$$size()),unsigned(dut.get_io$$##P##$$proof##N##$$bits$$payload$$mask())}
#define READ(S,P) \
        READ_PROOF(S,P,0);READ_PROOF(S,P,1); \
        (S).bound=dut.get_io$$##P##$$bound();(S).reserved=dut.get_io$$##P##$$reservedCount();(S).proved=dut.get_io$$##P##$$provedCount(); \
        (S).query=dut.get_io$$##P##$$query$$valid(); \
        if((S).query) { (S).write=dut.get_io$$##P##$$query$$bits$$write();(S).queryAddress=dut.get_io$$##P##$$query$$bits$$address();(S).querySize=dut.get_io$$##P##$$query$$bits$$size(); } \
        if(dut.get_io$$##P##$$loadPrepared$$valid()) { (S).load=Proof{ \
            {unsigned(dut.get_io$$##P##$$loadPrepared$$bits$$token$$index()),uint64_t(dut.get_io$$##P##$$loadPrepared$$bits$$token$$tag())}, \
            uint32_t(dut.get_io$$##P##$$loadPrepared$$bits$$epoch()),uint64_t(dut.get_io$$##P##$$loadPrepared$$bits$$address()), \
            uint64_t(dut.get_io$$##P##$$loadPrepared$$bits$$physicalAddress()),false,unsigned(dut.get_io$$##P##$$loadPrepared$$bits$$size()),0}; \
            (S).loadAllowed=dut.get_io$$##P##$$loadPrepared$$bits$$allowed(); } \
        (S).storeResult=dut.get_io$$##P##$$storeResult();(S).resultValid=dut.get_io$$##P##$$resultValid(); \
        (S).resultFresh=dut.get_io$$##P##$$resultFresh(); \
        if((S).resultValid) { (S).resultStore=dut.get_io$$##P##$$resultStore();(S).resultAllowed=dut.get_io$$##P##$$resultAllowed(); \
            (S).resultRow=(S).resultStore?unsigned(dut.get_io$$##P##$$resultRow()):0; \
            (S).result=Proof{{unsigned(dut.get_io$$##P##$$result$$token$$index()),uint64_t(dut.get_io$$##P##$$result$$token$$tag())}, \
            uint32_t(dut.get_io$$##P##$$result$$epoch()),uint64_t(dut.get_io$$##P##$$result$$payload$$address()), \
            uint64_t(dut.get_io$$##P##$$result$$payload$$physicalAddress()),bool(dut.get_io$$##P##$$result$$payload$$write()), \
            unsigned(dut.get_io$$##P##$$result$$payload$$size()),unsigned(dut.get_io$$##P##$$result$$payload$$mask())}; }
        READ(c,candidate);READ(r,reference);
        c.ownerMap=dut.get_io$$candidateMap();r.ownerMap=dut.get_io$$referenceMap();
        c.disjointMap=dut.get_io$$candidateDisjoint();r.disjointMap=dut.get_io$$referenceDisjoint();
#undef READ
#undef READ_PROOF
        if(reset) {dut.resetAll();pending.reset();certified.clear();loadCertificate.reset();return {};}
        ++totalCycles;
        // Corrupt only a real observation with the value of a specified weaker predicate.
        // The normal parity/oracle check below must detect it; no flag forces failure.
        if(pending && pending->proof.write && c.resultFresh) {
            const auto &p=pending->proof;
            for(const std::string part:{"tag","va","size","mask"}) if(mode=="--mutate-owner-"+part) {
                const bool weak=matches(p,part)&&!cleared(p);
                if(weak!=c.storeResult) {c.storeResult=weak;corruptionApplied=true;}
            }
            if(mode=="--mutate-clear" && (in.clear&(1u<<p.token.index)) && matches(p) && !in.consume) {
                c.storeResult=true;corruptionApplied=true;
            }
            if(mode=="--mutate-consume" && in.consume && *in.consume==p.token && matches(p) && !in.clear) {
                c.storeResult=true;corruptionApplied=true;
            }
            if(mode=="--mutate-wrong-row" && PENDING_STORE_SLOTS==2 && c.resultRow==1) {
                const bool weak=in.owners[0].valid && in.owners[0].proof.token!=p.token;
                if(weak!=c.storeResult) {c.storeResult=weak;corruptionApplied=true;}
            }
        }
        if(mode=="--mutate-live-clear") for(auto &p:c.proofs) if(p && cleared(*p)) {p.reset();corruptionApplied=true;}
        if(mode=="--mutate-proof-tag") for(auto &p:c.proofs) if(p) {p->token.tag^=1ULL<<63;corruptionApplied=true;}
        if(mutation && (c.ownerMap!=r.ownerMap || c.disjointMap!=r.disjointMap)) corruptionApplied=true;
        require(c==r,"cycle parity mismatch at cycle "+std::to_string(cycles)+" control="+mode);
        unsigned expectedMap=0,expectedDisjoint=0;
        for(const auto &proof:c.proofs) if(proof) {
            const auto &p=*proof;
            const auto *o=owner(p.token);
            require(o && matches(p),"ROB map proof lost current full owner");
            expectedMap|=1u<<p.token.index;
            const uint64_t bytes=1ULL<<in.loadSize;
            if(!(in.loadAddress&(bytes-1)) && ((in.loadAddress>>3)!=(p.physical>>3) || !(lanes(in.loadAddress,in.loadSize)&p.mask)))
                expectedDisjoint|=1u<<p.token.index;
        }
        require(c.ownerMap==expectedMap && c.disjointMap==expectedDisjoint,"independent ROB map/disjoint oracle mismatch");
        mappedEdges+=!!c.ownerMap;disjointEdges+=!!c.disjointMap;overlapEdges+=!!(c.ownerMap&~c.disjointMap);
        poisonEdges+=in.poisonInvalid && (!c.proofs[0] || (PENDING_STORE_SLOTS==2&&!c.proofs[1]));
        require(c.reserved+c.proved<=PENDING_STORE_SLOTS,"independent bank capacity exceeded");
        require(c.resultValid==pending.has_value(),"query-to-translated boundary mismatch");
        const bool fresh=pending && in.stable && !in.flush && pending->proof.epoch==in.epoch;
        require(c.resultFresh==fresh,"independent freshness oracle mismatch");
        if(pending) {
            ++totalResults;const auto &p=pending->proof;
            require(c.result && *c.result==p && c.resultStore==p.write,"independent translated full-tuple oracle mismatch");
            require(c.resultAllowed==permitted(*pending),"independent PMP/shape/response oracle mismatch");
        }
        const bool accepted=fresh && pending->proof.write && matches(pending->proof) && !cleared(pending->proof);
        require(c.storeResult==accepted,"independent actual storeResult owner oracle mismatch");
        for(const auto &p:c.proofs) if(p) {
            ++totalProofs;
            require(matches(*p)&&p->epoch==in.epoch&&in.stable,"independent current owner proof mismatch");
            const auto it=certified.find(p->token);
            require(it!=certified.end()&&it->second==*p,"independent full-tuple certificate oracle mismatch");
        }
        const bool loadLive=loadCertificate && in.stable && !in.flush && loadCertificate->first.epoch==in.epoch;
        require(c.load.has_value()==loadLive,"independent retained load validity mismatch");
        if(c.load) {++totalLoads;require(*c.load==loadCertificate->first&&c.loadAllowed==loadCertificate->second,"independent retained load tuple/permission mismatch");}
        const auto oldLoadCertificate=loadCertificate;
        if(accepted && permitted(*pending)) certified[pending->proof.token]=pending->proof;
        if(fresh && !pending->proof.write && !cleared(pending->proof)) {
            auto p=pending->proof;p.mask=0;loadCertificate=std::make_pair(p,permitted(*pending));
        }
        // Existing certificate invalidation uses its pre-edge identity, even if a new
        // result is also captured. Mirror only this externally observable lifecycle.
        if(!in.stable || in.flush || (oldLoadCertificate && (oldLoadCertificate->first.epoch!=in.epoch || cleared(oldLoadCertificate->first)))) loadCertificate.reset();
        pending.reset();
        if(c.query) {
            ++totalQueries;require(in.stable&&!in.flush&&!in.pause,"query escaped cancellation");
            Proof p;
            if(c.write) {
                // The query descriptor contains no token; select the oldest matching
                // queued transaction using the actual result token next cycle below.
                // Tests distinguish owners by their address, except deliberate same-VA
                // fairness cases where the fixed oldest-first grant order is recorded.
                const Owner *selected=nullptr;
                for(const auto &o:in.owners) if(o.valid&&o.slot==o.proof.token.index&&o.proof.original==c.queryAddress&&o.proof.size==c.querySize&&!cleared(o.proof)) {
                    bool present=false;for(const auto &proof:c.proofs) if(proof && proof->token==o.proof.token) present=true;
                    if(pending) present|=pending->proof.token==o.proof.token;
                    if(!present && (!selected || ((o.slot+16-in.head)%16)<((selected->slot+16-in.head)%16))) selected=&o;
                }
                require(selected,"store query has no independent full owner");p=selected->proof;
            } else {p=in.loadProof;p.write=false;p.mask=lanes(p.original,p.size);}
            p.epoch=in.epoch;p.physical=in.hit?in.replyPa:0;
            pending=Transaction{p,in.hit,in.pbmt,in.replyEpoch};
            if(c.storeResult && c.result && c.result->token!=p.token) ++distinctOwnerEdges;
        }
        return c;
    }
    Snapshot wait(unsigned n=5) {Snapshot s;while(n--)s=tick();return s;}
    Snapshot grant(bool write=true) {for(unsigned n=0;n<16;++n){auto s=tick();if(s.query&&s.write==write)return s;}throw std::runtime_error("bounded grant deadline");}
    Snapshot proved(unsigned count=1) {for(unsigned n=0;n<24;++n){auto s=tick();unsigned got=0;for(const auto &p:s.proofs)got+=p.has_value();if(got==count)return s;}throw std::runtime_error("bounded proof deadline");}
};
int main(int argc,char **argv) {try {
    mode=argc>1?argv[1]:"";
    for(const std::string change:{"va","size","mask","tag","index","invalid"}) {
        Bench b;b.owner(0,15,0xfedcba9876543210ULL);b.grant();b.in.eligible=0;
        if(change=="va")b.in.owners[0].proof.original+=8;
        if(change=="size")b.in.owners[0].proof.size=2;
        if(change=="mask")b.in.owners[0].proof.mask=15;
        if(change=="tag")b.in.owners[0].proof.token.tag^=1ULL<<63;
        if(change=="index")b.in.owners[0].proof.token.index=0;
        if(change=="invalid")b.in.owners[0].valid=false;
        auto s=b.tick();require(!s.storeResult,"changed current owner authorized result");
        s=b.wait(2);require(!s.reserved&&!s.proved,"changed owner did not release inflight");
        b.owner(0,15,0x7edcba9876543210ULL);b.proved();
        std::cout<<"ROB_MAP_CASE current_"<<change<<"_at_result_and_row_reuse\n";
    }
    {Bench b;b.owner(0,3,0x8000000000003001ULL);b.tick();b.in.owners[0].proof.original+=8;b.in.eligible=0;
      auto s=b.tick();require(!s.query,"changed queued owner was granted");s=b.wait();require(!s.reserved&&!s.proved,"queued owner cleanup failed");
      b.owner(0,3,0x9000000000003001ULL);b.in.owners[0].proof.token.index=4;s=b.wait();require(!s.query&&!s.reserved&&!s.proved,"malformed physical owner slot admitted");
      std::cout<<"ROB_MAP_CASE queued_owner_change_and_physical_slot_mismatch\n";}
    for(unsigned edge=0;edge<8;++edge) {
        Bench b;b.owner(0,2,0x8000000000000201ULL);b.grant();b.in.eligible=0;
        if(edge==0||edge==7)b.in.clear=1u<<2;
        if(edge==1||edge==7)b.in.consume=b.in.owners[0].proof.token;
        if(edge==2||edge==7)++b.in.epoch;
        if(edge==3||edge==7)b.in.stable=false;
        if(edge==4||edge==7)b.in.flush=true;
        if(edge==5||edge==7)b.in.pmp=0x19;
        if(edge==6)b.in.pause=true;
        auto s=b.tick();require(s.storeResult==(edge==5||edge==6),"same-edge result priority changed");
        s=b.tick();require((s.proved==1)==(edge==6),"same-edge PMP/cancel result capture changed");
        std::cout<<"ROB_MAP_CASE result_edge_"<<edge<<"\n";
    }
    for(unsigned denial=0;denial<8;++denial) {
        Bench b;b.owner(0,1,0x8000000000000101ULL);
        if(denial==0)b.in.hit=false;
        if(denial==1)b.in.pbmt=1;
        if(denial==2)--b.in.replyEpoch;
        if(denial==3)b.in.replyPa=0x10000000;
        if(denial==4)b.in.replyPa=ram+1;
        if(denial==5)b.in.owners[0].proof.mask=15;
        if(denial==6)b.in.pmp=0x19;
        if(denial==7)b.in.owners[0].proof.original=va+1;
        b.grant();b.in.eligible=0;auto s=b.tick();require(s.storeResult&&!s.resultAllowed,"denied result disposition mismatch");
        s=b.tick();require(!s.reserved&&!s.proved,"denied/no-hit result failed to release inflight");
        std::cout<<"ROB_MAP_CASE deny_release_"<<denial<<"\n";
    }
    {Bench b;b.owner(0,15,0x8000000000001501ULL);b.in.head=14;b.in.load=true;auto s=b.proved();
      b.in.bind=1;b.tick();b.in.bind=0;b.in.eligible=0;b.in.load=false;b.wait();
      b.in.flush=true;b.tick();b.in.flush=false;b.in.pause=true;s=b.wait();require(s.bound==1&&s.proofs[0],"bound proof lost across query cancel");
      b.in.clear=1u<<15;s=b.tick();require(s.proofs[0].has_value(),"live proof suppressed before clear edge");
      b.in.clear=0;b.in.owners[0].valid=false;s=b.tick();require(!s.bound&&!s.proved,"clear did not win after edge");
      b.in.pause=false;b.owner(0,15,0x0000000000001501ULL);s=b.proved();b.in.consume=b.in.owners[0].proof.token;
      s=b.tick();require(s.proofs[0].has_value(),"live proof suppressed before consume edge");
      b.in.consume.reset();b.in.owners[0].valid=false;s=b.tick();require(!s.proved,"consume did not release reused row");
      std::cout<<"ROB_MAP_CASE live_clear_consume_bound_cancel_high_tag_reuse\n";}
    {Bench b;b.in.load=true;b.grant(false);b.in.pmp=0x1a;b.in.load=false;b.tick();auto s=b.tick();
      require(s.load&&!s.loadAllowed,"read permission not evaluated at registered PMP boundary");
      b.owner(0,2,0x8000000000000202ULL);b.proved();s=b.wait();require(s.load&&!s.loadAllowed,"store result erased retained denied load");
      b.in.clear=1u<<14;b.tick();b.in.clear=0;s=b.tick();require(!s.load,"load clear owner did not release certificate");
      b.in.load=true;b.in.pmp=0x1f;b.grant(false);b.in.load=false;b.tick();s=b.tick();require(s.load&&s.loadAllowed,"allowed load tuple missing");
      ++b.in.epoch;b.tick();s=b.tick();require(!s.load,"epoch did not invalidate retained load");
      std::cout<<"ROB_MAP_CASE load_retention_read_write_pmp_epoch\n";}
#if PENDING_STORE_SLOTS == 2
    {Bench b;b.in.head=14;b.owner(0,15,0x8000000000001501ULL);b.owner(1,0,0xa000000000000001ULL,va+8);b.grant();
      b.in.replyPa=ram+8;auto s=b.tick();require(s.storeResult&&s.query&&s.queryAddress==va+8,"distinct result/grant owners did not overlap");
      b.in.eligible=0;b.in.owners[1].proof.original+=8;
      s=b.tick();require(!s.storeResult&&s.resultRow==1,"row1 current owner rejection missing");
      b.in.owners[1].valid=false;s=b.wait();require(s.proved==1&&!s.reserved,"row1 cleanup changed row0 certificate");
      b.in.owners[1].valid=true;b.in.owners[1].proof.original=va+8;b.in.eligible=1;b.proved(2);
      b.in.bind=3;b.tick();b.in.bind=0;b.owner(2,1,0xe000000000000101ULL,va+16);s=b.wait();require(s.bound==3&&s.proved==2,"bound rows evicted or overallocated");
      b.in.consume=b.in.owners[0].proof.token;b.tick();b.in.consume.reset();b.in.owners[0].valid=false;b.in.replyPa=ram+16;b.proved(2);
      std::cout<<"ROB_MAP_CASE distinct_grant_result_owners_wrong_row_bound_reuse\n";}
#endif
    {Bench b;b.owner(0,4,0x9000000000000401ULL);b.grant();b.tick(true);auto s=b.wait();require(!s.resultValid||s.resultFresh,"reset recovery stale freshness");b.proved();
      std::cout<<"ROB_MAP_CASE reset_inflight_recovery\n";}
    for(unsigned guard=0;guard<12;++guard) {
        Bench b;b.owner(0,7,0x8000000000000701ULL);b.proved();b.in.eligible=0;
        b.in.ownerDeny=1u<<guard;auto s=b.tick();
        require(!s.ownerMap && !s.disjointMap,"production ROB owner guard did not suppress stale proof");
        b.tick();b.in.ownerDeny=0;b.in.eligible=1u<<7;b.proved();
        std::cout<<"ROB_MAP_CASE owner_guard_"<<guard<<"_and_readmit\n";
    }
    {Bench b;b.owner(0,6,0xffffffffffffffffULL);b.proved();b.in.eligible=0;
      b.in.loadAddress=ram;auto s=b.tick();require(s.ownerMap&&!s.disjointMap,"physical overlap incorrectly disjoint");
      b.in.loadAddress=ram+1;s=b.tick();require(s.ownerMap&&!s.disjointMap,"unaligned load bypassed store");
      b.in.loadAddress=ram+8;s=b.tick();require(s.ownerMap==s.disjointMap,"disjoint load lost row mapping");
      b.in.owners[0].proof.token.tag^=1ULL<<63;s=b.tick();require(!s.ownerMap,"high-bit renamed owner reused stale proof");
      b.in.clear=1u<<6;b.tick();b.in.clear=0;b.in.eligible=1u<<6;b.proved();
      std::cout<<"ROB_MAP_CASE high64_retained_owner_reuse_overlap_unaligned_disjoint\n";}
    {Bench b;b.owner(0,9,0x8000000000000901ULL);b.grant();b.in.clear=1u<<9;
      b.in.owners[0].proof.token.tag^=1ULL<<63;b.in.owners[1]=b.in.owners[0];b.in.owners[0].valid=false;
      auto s=b.tick();require(!s.storeResult&&!s.ownerMap,"clear rename kill allowed old return");
      b.in.clear=0;b.in.eligible=1u<<9;b.proved();
      std::cout<<"ROB_MAP_CASE simultaneous_clear_rename_kill_return\n";}
    for(const std::string change:{"va","size","mask","epoch","stable"}) {
      Bench b;b.owner(0,8,0x8000000000000801ULL);b.proved();b.in.eligible=0;
      if(change=="va")b.in.owners[0].proof.original+=8;
      if(change=="size")b.in.owners[0].proof.size=2;
      if(change=="mask")b.in.owners[0].proof.mask=15;
      if(change=="epoch")++b.in.epoch;
      if(change=="stable")b.in.stable=false;
      auto s=b.tick();require(!s.ownerMap&&!s.disjointMap,"retained proof mismatch remained mapped");
      std::cout<<"ROB_MAP_CASE retained_"<<change<<"_invalidates_map\n";
    }
    require(mappedEdges&&disjointEdges&&overlapEdges&&poisonEdges,"ROB map coverage totals empty");
    if(!mode.empty()) require(corruptionApplied,"requested corruption control was not exercised");
    require(totalQueries&&totalResults&&totalProofs&&totalLoads,"coverage totals empty");
#if PENDING_STORE_SLOTS == 2
    require(distinctOwnerEdges,"distinct owner query/result boundary not witnessed");
#endif
    std::cout<<"ROB_MAP_PASS slots="<<PENDING_STORE_SLOTS<<" cycles="<<totalCycles<<" queries="<<totalQueries<<" results="<<totalResults<<" proofs="<<totalProofs<<" loads="<<totalLoads<<" mapped_edges="<<mappedEdges<<" disjoint_edges="<<disjointEdges<<" overlap_edges="<<overlapEdges<<" poison_edges="<<poisonEdges<<" distinct_owner_edges="<<distinctOwnerEdges<<'\n';
    return 0;
} catch(const std::exception &e) {std::cerr<<"ROB_MAP_FAIL "<<e.what()<<'\n';return 1;}}
