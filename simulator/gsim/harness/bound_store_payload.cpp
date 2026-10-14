#include "BoundStorePayloadGsim.h"
#include "pending_store_proof_reference.h"
#include <bit>
#include <cstring>
#include <deque>
#include <iostream>
#include <optional>
#include <type_traits>
#ifndef BOUND_STORE_SLOTS
#define BOUND_STORE_SLOTS 2
#endif
using namespace pending_store_reference;
struct Owner { bool valid = false; Proof proof{}; };
struct Input {
    std::array<Owner,3> owners{};
    unsigned head=0, eligible=0, clear=0, bind=0, pmp=0x1f;
    bool pause=false, flush=false, stable=true, hit=true;
    unsigned pbmt=0;
    uint32_t epoch=7, replyEpoch=7;
    Proof selected{{14,0xfeedfacecafebeefULL},7,va+128,ram+128,true,3,255};
    std::optional<Token> consume;
};
struct Snapshot {
    std::array<Proof,2> rows{};
    unsigned valid=0, bound=0, nonfree=0, reserved=0, proved=0, exact=0;
    bool query=false, queryWrite=false, permit=false, referencePermit=false, mutationChanged=false;
    uint64_t queryAddress=0;
    unsigned querySize=0;
    bool resultValid=false, resultFresh=false, storeResult=false, resultAllowed=false;
    unsigned resultRow=0;
    Proof result{}, selected{}, reference{}, single{};
};
struct Transaction { Proof proof; bool hit; unsigned pbmt; uint32_t replyEpoch; };
struct Certificate { Proof proof; bool bound=false; };
static std::string mode;
static unsigned mutation=0;
static bool witnessed=false;
static uint64_t cycles=0, queries=0, results=0, rejectedQueries=0, rejectedResults=0;
static uint64_t validSelections=0, row0Selections=0, row1Selections=0, singleSelections=0, noMatchData=0;
static uint64_t uniquePairs=0, boundInvalid=0;
struct Bench {
    SBoundStorePayloadGsim dut;
    Input in;
    Snapshot last;
    // These are host-submitted descriptors. A public query consumes one entry;
    // no DUT token, result payload, raw row or mutation output creates an expectation.
    std::deque<Proof> offered;
    std::optional<Transaction> pending;
    std::map<Token,Certificate> certified;
    uint64_t localCycles=0;
    Bench() {
        static_assert(std::is_trivially_copyable_v<SBoundStorePayloadGsim>);
        std::memset(&dut,0,sizeof(dut)); dut.LOG_START=1; dut.activateAll();
        tick(true); tick(true); tick(); tick();
    }
    const Owner *owner(Token t) const {
        const Owner *found=nullptr;
        for (const auto &o:in.owners) if (o.valid && o.proof.token.index==t.index) {
            require(!found,"host submitted duplicate current ROB indices"); found=&o;
        }
        return found;
    }
    bool ownerMatches(const Proof &p) const {
        const Owner *o=owner(p.token);
        return o && o->proof.token==p.token && o->proof.original==p.original &&
            o->proof.size==p.size && o->proof.mask==p.mask && p.write;
    }
    bool cleared(const Proof &p) const {
        return (in.clear&(1u<<p.token.index)) || (in.consume && *in.consume==p.token);
    }
    bool live(const Certificate &c) const {
        return ownerMatches(c.proof) && in.stable && c.proof.epoch==in.epoch;
    }
    bool selected(const Proof &p) const {
        return p.token==in.selected.token && p.original==in.selected.original && p.size==in.selected.size;
    }
    bool permitted(const Transaction &t) const {
        const auto &p=t.proof;
        if (!t.hit || t.pbmt || t.replyEpoch!=p.epoch || p.size>3) return false;
        const uint64_t bytes=1ULL<<p.size;
        if ((p.original&(bytes-1)) || (p.physical&(bytes-1)) ||
            (p.original&4095)!=(p.physical&4095) || p.mask!=lanes(p.physical,p.size)) return false;
        return p.physical>=ram && __uint128_t(p.physical)+bytes<=__uint128_t(ram)+ramBytes &&
            (in.pmp&2) && ((in.pmp>>3)&3)==3;
    }
    void add(unsigned port,unsigned index,uint64_t tag,uint64_t address=va,unsigned size=3) {
        require(port<3,"bad host owner port");
        Proof p{{index,tag},in.epoch,address,ram+(address&4095),true,size,lanes(address,size)};
        in.owners[port]={true,p}; in.eligible|=1u<<index; offered.push_back(p);
    }
    void choose(unsigned port) { in.selected=in.owners[port].proof; }
    unsigned rowOf(Token token) const {
        for(unsigned r=0;r<BOUND_STORE_SLOTS;++r) if((last.valid&(1u<<r)) && last.rows[r].token==token) return r;
        throw std::runtime_error("requested bind has no checked live certificate");
    }
    Snapshot bindOwner(unsigned port) {
        const unsigned row=rowOf(in.owners[port].proof.token);
        in.bind=1u<<row; tick(); in.bind=0; auto s=tick();
        require(s.bound&(1u<<row),"legal bind did not become visible"); return s;
    }
    Snapshot tick(bool reset=false) {
        dut.set_reset(reset);
#define OWNER(N) \
        dut.set_io$$owner##N##$$valid(in.owners[N].valid); \
        dut.set_io$$owner##N##$$bits$$token$$index(in.owners[N].proof.token.index); \
        dut.set_io$$owner##N##$$bits$$token$$tag(in.owners[N].proof.token.tag); \
        dut.set_io$$owner##N##$$bits$$address(in.owners[N].proof.original); \
        dut.set_io$$owner##N##$$bits$$size(in.owners[N].proof.size); \
        dut.set_io$$owner##N##$$bits$$mask(in.owners[N].proof.mask)
        OWNER(0); OWNER(1); OWNER(2);
#undef OWNER
        dut.set_io$$head(in.head); dut.set_io$$queryEligible(in.eligible); dut.set_io$$clearOwners(in.clear);
        dut.set_io$$pause(in.pause); dut.set_io$$flush(in.flush); dut.set_io$$stable(in.stable); dut.set_io$$epoch(in.epoch);
        dut.set_io$$bind(in.bind); dut.set_io$$pmpCfg(in.pmp); dut.set_io$$mutation(mutation);
        dut.set_io$$consume$$valid(in.consume.has_value());
        dut.set_io$$consume$$bits$$index(in.consume?in.consume->index:15);
        dut.set_io$$consume$$bits$$tag(in.consume?in.consume->tag:UINT64_MAX);
        dut.set_io$$selectToken$$index(in.selected.token.index); dut.set_io$$selectToken$$tag(in.selected.token.tag);
        dut.set_io$$selectAddress(in.selected.original); dut.set_io$$selectSize(in.selected.size);
        dut.set_io$$reply$$valid(in.hit);
        dut.set_io$$reply$$bits$$physicalAddress(offered.empty()?ram:offered.front().physical);
        dut.set_io$$reply$$bits$$epoch(in.replyEpoch); dut.set_io$$reply$$bits$$pbmt(in.pbmt);
        dut.step(); ++localCycles;
        Snapshot s;
#define READ(P) Proof{ \
        {unsigned(dut.get_io$$##P##$$token$$index()),uint64_t(dut.get_io$$##P##$$token$$tag())}, \
        uint32_t(dut.get_io$$##P##$$epoch()),uint64_t(dut.get_io$$##P##$$payload$$address()), \
        uint64_t(dut.get_io$$##P##$$payload$$physicalAddress()),bool(dut.get_io$$##P##$$payload$$write()), \
        unsigned(dut.get_io$$##P##$$payload$$size()),unsigned(dut.get_io$$##P##$$payload$$mask())}
        s.rows[0]=READ(proof0$$bits); s.rows[1]=READ(proof1$$bits);
        s.valid=unsigned(dut.get_io$$proof0$$valid())|(unsigned(dut.get_io$$proof1$$valid())<<1);
        s.result=READ(result); s.selected=READ(selected); s.reference=READ(reference); s.single=READ(singleSelected);
#undef READ
        s.bound=dut.get_io$$bound(); s.nonfree=dut.get_io$$nonfree();
        s.reserved=dut.get_io$$reservedCount(); s.proved=dut.get_io$$provedCount();
        s.exact=dut.get_io$$exactMask(); s.permit=dut.get_io$$candidatePermit();
        s.referencePermit=dut.get_io$$referencePermit(); s.mutationChanged=dut.get_io$$mutationChanged();
        s.query=dut.get_io$$query$$valid(); s.queryWrite=dut.get_io$$query$$bits$$write();
        s.queryAddress=dut.get_io$$query$$bits$$address(); s.querySize=dut.get_io$$query$$bits$$size();
        s.resultValid=dut.get_io$$resultValid(); s.resultFresh=dut.get_io$$resultFresh();
        s.storeResult=dut.get_io$$storeResult(); s.resultAllowed=dut.get_io$$resultAllowed(); s.resultRow=dut.get_io$$resultRow();
        if(reset) { dut.resetAll(); pending.reset(); offered.clear(); certified.clear(); last={}; return {}; }
        ++cycles;
        if(s.mutationChanged && !witnessed) {
            witnessed=true;
            std::cerr<<"ACTUAL_CORRUPTION count=1 mode="<<mode<<" cycle="<<cycles<<"\n"<<std::flush;
        }
        require(!(s.bound&~s.nonfree),"bound row is free");
        require(std::popcount(s.nonfree)==s.reserved+s.proved,"nonfree occupancy mismatch");
        require(s.reserved+s.proved<=BOUND_STORE_SLOTS,"bank capacity exceeded");
        if((s.nonfree&3)==3) {
            ++uniquePairs;
            require(s.rows[0].token.index!=s.rows[1].token.index,"actual nonfree indices are not unique");
        }
        if((s.bound&3)==3) require(s.rows[0].token.index!=s.rows[1].token.index,"actual bound indices are not unique");
        boundInvalid+=std::popcount(s.bound&~s.valid);
        unsigned expectedLive=0, expectedBound=0;
        std::optional<Proof> expectedSelection;
        for(const auto &[token,c]:certified) {
            expectedLive+=live(c); expectedBound+=c.bound;
            if(c.bound && live(c) && selected(c.proof)) {
                require(!expectedSelection,"independent selector has duplicate exact owners"); expectedSelection=c.proof;
            }
        }
        require(s.proved==certified.size(),"public-query certificate ledger lost or invented a proved row");
        require(std::popcount(s.valid)==expectedLive,"independent live certificate count mismatch");
        require(std::popcount(s.bound)==expectedBound,"independent bound certificate count mismatch");
        unsigned expectedExact=0;
        for(unsigned r=0;r<BOUND_STORE_SLOTS;++r) {
            const auto &p=s.rows[r];
            if((s.valid|s.bound)&(1u<<r)) {
                const auto it=certified.find(p.token);
                require(it!=certified.end() && p==it->second.proof,"independent full-tuple certificate mismatch");
                require(bool(s.bound&(1u<<r))==it->second.bound,"independent bound owner mismatch");
                require(bool(s.valid&(1u<<r))==live(it->second),"current full owner/epoch validity mismatch");
            }
            if((s.valid&s.bound&(1u<<r)) && selected(p)) expectedExact|=1u<<r;
        }
        require(s.exact==expectedExact,"unchanged full-match mask mismatch");
        require(s.referencePermit==expectedSelection.has_value(),"old scalar authorization disagrees with host ledger");
        require(s.permit==expectedSelection.has_value(),"BOUND_PAYLOAD_REJECT authorization mismatch");
        if(expectedSelection) {
            ++validSelections; row0Selections+=!!(expectedExact&1); row1Selections+=!!(expectedExact&2);
            // All fields compare, including the full 64-bit tag, VA, PA, epoch,
            // size, write and mask. No comparison constrains invalid payload data.
            require(s.reference==*expectedSelection,"old Mux1H full tuple disagrees with public-query ledger");
            require(s.selected==*expectedSelection,"BOUND_PAYLOAD_REJECT selected full tuple mismatch");
            if(expectedExact&1) {
                ++singleSelections;
                require(s.single==*expectedSelection,"single-row helper direct payload mismatch");
            }
        } else if(s.selected.token.tag || s.selected.original || s.selected.physical) ++noMatchData;
        require(s.resultValid==pending.has_value(),"registered query/result validity boundary mismatch");
        const bool fresh=pending && in.stable && !in.flush && pending->proof.epoch==in.epoch;
        require(s.resultFresh==fresh,"independent result freshness mismatch");
        if(pending) {
            ++results;
            require(s.result==pending->proof,"independent translated descriptor mismatch");
            require(s.resultAllowed==permitted(*pending),"independent response/PMP permission mismatch");
        }
        const bool accepted=fresh && ownerMatches(pending->proof) && !cleared(pending->proof);
        require(s.storeResult==accepted,"independent stale-result owner/clear/consume rejection mismatch");
        if(s.resultValid && !accepted) ++rejectedResults;
        // Advance expected state using only the accepted public query plus current
        // owner/bind/clear/consume/context inputs. Never copy a DUT result into it.
        for(unsigned r=0;r<BOUND_STORE_SLOTS;++r) if(in.bind&(1u<<r)) {
            require((s.valid&(1u<<r)) && !in.flush && !cleared(s.rows[r]),"host attempted an illegal bind");
            certified.at(s.rows[r].token).bound=true;
        }
        for(auto it=certified.begin();it!=certified.end();) {
            const auto &c=it->second;
            const bool gone=!ownerMatches(c.proof)||cleared(c.proof)||(!c.bound &&
                (c.proof.epoch!=in.epoch || !in.stable || in.flush));
            if(gone) it=certified.erase(it); else ++it;
        }
        if(accepted && permitted(*pending)) certified[pending->proof.token]={pending->proof,false};
        pending.reset();
        if(s.query) {
            ++queries;
            require(in.stable&&!in.flush,"query escaped context cancellation");
            require(!offered.empty(),"query without a host-submitted descriptor");
            Proof p=offered.front(); offered.pop_front();
            require(s.queryWrite && s.queryAddress==p.original && s.querySize==p.size,
                "public query differs from independently queued owner descriptor");
            const bool queryLive=ownerMatches(p)&&!cleared(p);
            if(!queryLive) ++rejectedQueries;
            p.physical=in.hit?p.physical:0;
            if(queryLive) pending=Transaction{p,in.hit,in.pbmt,in.replyEpoch};
        }
        last=s; return s;
    }
    Snapshot wait(unsigned n=3) { Snapshot s; while(n--)s=tick(); return s; }
    Snapshot grant() { for(unsigned n=0;n<12;++n) {auto s=tick(); if(s.query)return s;} throw std::runtime_error("query deadline"); }
    Snapshot proved(unsigned n) {
        for(unsigned k=0;k<16;++k) {auto s=tick(); if(std::popcount(s.valid)==n)return s;}
        throw std::runtime_error("proof deadline");
    }
};
static void proveBound(Bench &b,unsigned port,unsigned index,uint64_t tag,uint64_t address=va,unsigned size=3) {
    const unsigned count=b.certified.size()+1;
    b.add(port,index,tag,address,size); b.proved(count); b.choose(port); b.bindOwner(port);
}
int main(int argc,char **argv) { try {
    mode=argc>1?argv[1]:"";
    const std::map<std::string,unsigned> controls{{"",0},{"--mutate-payload",1},{"--mutate-row0",2},
        {"--mutate-token",3},{"--mutate-va",4},{"--mutate-size",5},{"--mutate-valid",6},
        {"--mutate-bound",7},{"--mutate-high-tag",8}};
    require(controls.contains(mode),"unknown negative control"); mutation=controls.at(mode);
    {
        Bench b; b.in.head=14;
        b.add(0,15,0xfedcba9876543210ULL); b.proved(1); b.choose(0);
        require(!b.tick().permit,"unbound certificate authorized payload");
        b.bindOwner(0); require(b.tick().permit,"row0 bound match missing");
        b.in.selected.token.tag^=1ULL<<63; require(!b.tick().permit,"high tag mismatch authorized"); b.choose(0);
        b.in.selected.original+=8; require(!b.tick().permit,"VA mismatch authorized"); b.choose(0);
        b.in.selected.size=2; require(!b.tick().permit,"size mismatch authorized"); b.choose(0);
        b.in.selected.token.index=6; require(!b.tick().permit,"absent index authorized"); b.choose(0);
        b.in.flush=true; require(b.tick().permit,"bound proof lost before flush edge"); b.in.flush=false;
        require(b.tick().permit,"bound proof did not survive query flush");
        b.in.stable=false; require(!b.tick().permit,"unstable context authorized bound data");
        b.in.stable=true; require(b.tick().permit,"bound proof lost across stable-only pause");
#if BOUND_STORE_SLOTS == 2
        proveBound(b,1,0,0x80000000000000a5ULL,va+4096+4,2);
        auto s=b.tick(); require(s.bound==3 && s.exact==2,"row1/both-bound selection missing");
        b.choose(0); require(b.tick().exact==1,"row0/both-bound selection missing");
        // Invalidate the CURRENT owner, leaving actual bound record identity alone.
        b.in.owners[0].proof.token.tag^=1ULL<<63; b.choose(1);
        s=b.tick(); require(s.bound==3 && s.valid==2 && s.exact==2,"late-invalid row0 shadowed valid row1");
        s=b.tick(); require(s.bound==2,"late-invalid row0 did not release on edge");
        proveBound(b,0,15,0x7edcba9876543210ULL,va+16,0);
        b.in.owners[1].proof.original+=8; b.choose(0);
        s=b.tick(); require(s.bound==3 && s.valid==1 && s.exact==1,"late-invalid row1 affected row0");
        b.tick();
        proveBound(b,1,0,0x90000000000000a5ULL,va+4096+4,2);
        // Clear plus same-index allocation cannot duplicate a pre-edge nonfree index.
        b.in.clear=1; b.add(1,0,0x10000000000000a5ULL,va+4096+4,2); b.choose(1);
        s=b.tick(); require(s.bound==3 && !(s.valid&2),"same-index new owner escaped old full-tag check");
        b.in.clear=0; b.proved(2); b.bindOwner(1); b.choose(1);
        require(b.tick().exact==2,"cleared row1 was not reused for new high tag");
        b.in.consume=Token{0,b.in.owners[1].proof.token.tag^(1ULL<<63)};
        b.tick(); b.in.consume.reset(); require(b.tick().bound==3,"wrong full-token consume cleared binding");
        b.in.consume=b.in.owners[1].proof.token;
        s=b.tick(); require(s.permit && s.bound==3,"consume incorrectly changed pre-edge scalar permission");
        b.in.consume.reset(); b.in.owners[1].valid=false; b.in.eligible&=~1u;
        require(b.tick().bound==1,"exact consume did not release row1");
#endif
        b.choose(0); b.in.consume=b.in.owners[0].proof.token; b.tick();
        b.in.consume.reset(); b.in.owners[0].valid=false; b.in.eligible=0;
        require(!b.tick().bound,"last bound owner survived exact consume");
        std::cout<<"BOUND_PAYLOAD_CASE bound_rows_exact_payload_late_invalid_high_tag_reuse\n";
    }
    {
        Bench b; b.add(0,3,0x8000000000000301ULL); b.tick(); b.tick();
        // Registered, side-effect-free query must drain despite pause and clear.
        b.in.pause=true; b.in.clear=1u<<3;
        b.add(0,3,0x0000000000000301ULL,va+24,3);
        auto s=b.tick(); require(s.query,"registered stale query did not drain under pause/clear");
        b.in.pause=false; b.in.clear=0; s=b.tick();
        require(!s.resultValid,"cleared query entered translated-valid stage");
        b.proved(1); b.choose(0); b.bindOwner(0); require(b.tick().permit,"reuse after stale query failed");
        std::cout<<"BOUND_PAYLOAD_CASE stale_registered_query_clear_and_reuse\n";
    }
    {
        Bench b; b.add(0,5,0x8000000000000501ULL); b.grant(); b.in.clear=1u<<5;
        b.add(0,5,0x0000000000000501ULL,va+32,3);
        auto s=b.tick(); require(s.resultValid&&!s.storeResult,"stale translated result accepted on clear/reuse");
        b.in.clear=0; b.proved(1); b.choose(0); b.bindOwner(0);
        require(b.tick().permit,"reuse after stale translated result failed");
        std::cout<<"BOUND_PAYLOAD_CASE stale_translated_result_and_reuse\n";
    }
#if BOUND_STORE_SLOTS == 2
    {
        Bench b; b.add(0,2,0x8000000000000201ULL); b.grant();
        b.add(1,7,0x8000000000000701ULL,va+40,3);
        auto s=b.tick(); require(s.storeResult,"result/admission overlap missing");
        b.proved(2); b.choose(0); b.bindOwner(0); b.choose(1); b.bindOwner(1);
        require(b.tick().exact==2,"overlapped admission/result row1 payload mismatch");
        std::cout<<"BOUND_PAYLOAD_CASE_distinct_result_and_admission\n";
    }
#endif
    {
        Bench b; b.add(0,4,0x8000000000000401ULL); b.proved(1); b.choose(0);
        b.in.eligible=0; ++b.in.epoch; require(!b.tick().permit,"unbound stale epoch authorized");
        require(!b.tick().proved,"unbound stale epoch was not cleared");
        std::cout<<"BOUND_PAYLOAD_CASE unbound_epoch_cleanup\n";
    }
    require(!mutation || witnessed,"negative control never reached a divergent observation");
    require(validSelections && row0Selections && singleSelections && noMatchData && boundInvalid,
        "missing bound-selection/invalid-data coverage");
#if BOUND_STORE_SLOTS == 2
    require(row1Selections && uniquePairs,"missing real two-row selection/uniqueness coverage");
#endif
    require(rejectedQueries && rejectedResults,"missing stale query/result rejection coverage");
    std::cout<<"BOUND_PAYLOAD_PASS slots="<<BOUND_STORE_SLOTS<<" cycles="<<cycles<<" queries="<<queries
        <<" results="<<results<<" selections="<<validSelections<<" row0="<<row0Selections<<" row1="<<row1Selections
        <<" single="<<singleSelections<<" unique_pairs="<<uniquePairs<<" bound_invalid="<<boundInvalid
        <<" ignored_data="<<noMatchData<<" stale_query="<<rejectedQueries<<" stale_result="<<rejectedResults<<"\n";
    return 0;
} catch(const std::exception &e) {
    std::cerr<<"BOUND_PAYLOAD_FAIL mode="<<mode<<" witness="<<witnessed<<" "<<e.what()<<"\n";
    return 1;
} }
