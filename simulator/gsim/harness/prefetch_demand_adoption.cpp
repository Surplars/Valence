// Actual posted-enabled cache/home. External requests, response schedules and
// independent bytes/owner generations drive the proof; no internal state writes.
#ifndef READ_PF_DEMAND_ADOPTION
#error "explicit OFF/ON policy required"
#endif
#include "prefetch_demand_adoption_oracle.h"
namespace adoption {
using namespace dual_prefetch;
constexpr bool enabled = READ_PF_DEMAND_ADOPTION;
struct Seed {
    uint64_t a=base+128, source=a-64, dirty=a+2*stride, protectedStore=a+stride;
    uint64_t reuse=base+8192, reuseVictim=reuse+2*stride;
};
static Seed seed(Gate& g, bool dirty=true) {
    Seed s; g.permission(false);
    if (dirty) {
        for (unsigned w=0;w<8;++w) g.store(s.dirty+8*w,w&1?0xaa:0x55);
        g.prepare(s.a,false);
        g.permission(true); g.prepare(s.protectedStore,true);g.trigger(s.protectedStore,true);g.settle();
        check(g.present(g.token[1]) && g.token[1]->address==s.protectedStore,"seed lacks protected clean store token");
        const auto choice=g.choose(s.a,true,false);
        check(choice.allowed&&choice.victim.dirty&&choice.victim.address==s.dirty,"seed lacks authored dirty PF victim");
    } else g.prepare(s.a,false);
    g.permission(false);g.send({s.source});g.send({s.source+8});g.settle();
    return s;
}
struct Episode {
    Gate& g; Seed s; bool holdA=true,holdB=false;
    uint64_t aCount=0,bCount=0,aRefill=0,bRefill=0,attach=0,nextIssueBefore=0;
    uint64_t capture=0,ack=0,reused=0,bothWb=0,heldProbe=0;
    std::optional<Key> original; std::optional<unsigned> savedWb;
    Episode(Gate& gate,Seed initial):g(gate),s(initial) {
        const auto before=g.t.observer;
        g.t.observer=[&,before] {
            auto& d=g.t.d;
            // Memory latency scheduling is external and independent of DUT:
            // postpone whole AR owners, preserve any already-offered R payload.
            for(auto& r:g.t.ddr.pendingReads) {
                const auto pa=base+r.address;
                if((holdA&&pa==s.a)||(holdB&&pa==s.a+64)) r.due=g.t.cycles+1024;
            }
            if(d.get_io$$releaseAckFire()&&!ack&&savedWb&&d.get_io$$releaseAckSource()==2+*savedWb) {
                check(g.wb[*savedWb]&&original&&g.wb[*savedWb]->key==*original&&g.wb[*savedWb]->pf,
                    "late Ack changed saved PF generation/origin");++ack;
            }
            before();
#define O(x) d.get_io$$storePfObs$$##x()
            if(O(allocated)&&O(allocatedAddress)==s.a) original=g.active[O(allocatedSlot)];
            if(O(wbCapture)&&O(wbCaptureAddress)==s.dirty) {
                check(original&&g.wb[O(wbCaptureSlot)]&&g.wb[O(wbCaptureSlot)]->key==*original,
                    "initial dirty capture lost PF generation");savedWb=O(wbCaptureSlot);++capture;
            }
            if(d.get_io$$acquireFire()) {
                if(d.get_io$$acquireAddress()==s.a)++aCount;
                if(d.get_io$$acquireAddress()==s.a+64){++bCount;nextIssueBefore+=attach&&!aRefill;}
            }
            if(O(demandAttach)&&line(O(demandAttachAddress))==s.a)++attach;
            if(O(refill)&&line(O(refillAddress))==s.a)++aRefill;
            if(O(refill)&&line(O(refillAddress))==s.a+64)++bRefill;
            if(O(demandAlloc)&&original&&O(demandAllocSlot)==original->first&&savedWb&&g.wb[*savedWb]){
                check(g.active[original->first]&&g.active[original->first]->second>original->second,
                    "reused demand retained stale MSHR generation");++reused;
            }
            bothWb+=bool(g.wb[0]&&g.wb[1]);
            heldProbe+=d.get_io$$probeOffer()&&!d.get_io$$probeFire();
#undef O
        };
    }
    void release(bool a,bool b) {
        if(a)holdA=false;if(b)holdB=false;
        for(auto& r:g.t.ddr.pendingReads){const auto pa=base+r.address;
            if((a&&pa==s.a)||(b&&pa==s.a+64))r.due=g.t.cycles+1;}
    }
    void start(bool hint=true,bool holdAcquire=false) {
        g.hold(false,false,false,true);g.t.d.set_io$$adoption$$holdAcquire(holdAcquire);
        g.permission(hint);g.send({s.source+16,false,0,0});
        g.until([&]{return holdAcquire?bool(g.t.d.get_io$$acquireOffer()):aCount==1;},"read PF did not offer/issue A");
    }
    void result(const char* name) {
        check(aCount==1,"target issued duplicate acquire");
        std::cout<<"PREFETCH_DEMAND_ADOPTION_RESULT name="<<name<<" enabled="<<enabled
            <<" target_a="<<aCount<<" next_a="<<bCount<<" attach="<<attach
            <<" next_issue_before_first_refill="<<nextIssueBefore<<" target_refill="<<aRefill
            <<" next_refill="<<bRefill<<" dirty_capture="<<capture<<" saved_ack="<<ack
            <<" reused_mshr="<<reused<<" two_wb_samples="<<bothWb<<" held_probe_samples="<<heldProbe<<'\n';
    }
};
static void noAccept(Gate& g,Request q,unsigned cycles,const char* why) {
    const auto n=g.t.cpuAccepted;g.begin(q);g.ticks(cycles);
    check(g.offered&&g.t.cpuAccepted==n,why);
    // Posted-enabled integration strengthens the request contract: keep this
    // blocked offer stable until its real prerequisite drains and it accepts.
}
static void drainExceptAck(Gate& g) {
    g.until([&]{return !g.offered&&!g.t.cpuRequest&&g.t.cpuExpected.empty()&&
        !g.active[0]&&!g.active[1]&&g.sources.empty()&&!g.t.d.get_io$$storePfObs$$pendingCandidateValid();},
        "owner did not complete while saved Ack held");g.ticks(2);
}
static void two_owner(bool reverse) {
    Gate g;const auto s=seed(g);Episode e(g,s);e.holdB=!reverse;e.start();
    const auto reply=g.t.cpuReturned;const auto accepted=g.t.cpuAccepted;
    g.begin({s.a+24,false,0,0x33});
    if(enabled) {
        g.until([&]{return !g.offered;},"issued read PF did not adopt checked demand");
        check(e.attach==1&&g.t.cpuAccepted==accepted+1&&g.t.cpuReturned==reply,"attachment completed early");
        g.until([&]{return e.bCount==1;},"adopted read did not issue next PF before first completion");
        check(e.nextIssueBefore==1&&!e.aRefill&&e.capture==1&&!e.ack,"two-owner window lost saved WB duty");
        noAccept(g,{s.a+32},4,"duplicate reader attached to same PF");
        if(mutation=="cpu-byte"&&!mutationTriggered){mutationTriggered=true;injectMismatch=true;
            std::cerr<<"PREFETCH_DEMAND_ADOPTION_MUTATION_TRIGGER cpu-byte\n";}
        if(reverse){g.until([&]{return e.bRefill==1;},"younger PF did not refill first");check(!e.aRefill,"wrong reverse refill order");}
        else {e.release(true,false);g.until([&]{return e.aRefill==1;},"attached PF did not refill first");check(!e.bRefill,"wrong forward refill order");}
        e.release(true,true);drainExceptAck(g);
        check(g.t.cpuReturned==reply+2&&g.n("attached_response")==1&&g.present(g.token[0]),
            "adopted read response count or successor token differs");
        check(g.token[0]->address==s.a+64&&g.token[1]&&g.token[1]->address==s.protectedStore,
            "attached refill overwrote next read token or opposite store token");
        if(mutation=="duplicate-cpu"&&!mutationTriggered){
            mutationTriggered=true;g.t.injectDuplicateResponse=true;g.permission(false);g.send({s.a+40});
        }
    }else{
        g.ticks(5);check(g.offered&&g.t.cpuAccepted==accepted&&!e.bCount&&!e.attach,"OFF adopted pending PF");
        e.release(true,true);g.until([&]{return !g.offered&&g.t.cpuExpected.empty();},"OFF demand did not resume after PF refill");
        drainExceptAck(g);check(g.t.cpuReturned==reply+1,"OFF response count differs");
    }
    g.hold(false,false,false,false);g.settle();e.result(reverse?"two_owner_reverse":"two_owner_forward");
    g.permission(false);g.send({s.a+64});g.send({s.protectedStore});
    g.finish(reverse?"two_owner_reverse":"two_owner_forward");
}
static void exclusions_and_first_a() {
    Gate g;const auto s=seed(g,false);Episode e(g,s);e.start(true,true);
    check(!e.aCount,"held A accepted");noAccept(g,{s.a+16},3,"unissued read PF adopted demand");
    g.t.d.set_io$$adoption$$holdAcquire(0);
    g.until([&]{return e.aCount==1;},"held A did not issue");
    check(g.offered&&!e.attach,"demand attached on first A.fire edge");
    g.until([&]{return !g.offered;},"post-A read did not attach");
    g.permission(false);
    e.release(true,true);g.hold(false,false,false,false);g.settle();e.result("first_a_and_exclusions");
    g.finish("first_a_and_exclusions");
    Gate store;const uint64_t target=base+512;store.permission(false);store.prepare(target,true);
    store.permission(true);store.hold(false,true,false,false);store.trigger(target,true);
    store.until([&]{return store.n("pf_acquire")==1;},"store-origin PF not issued");
    store.permission(false);noAccept(store,{target+8},5,"read demand adopted store-origin PF");
    store.permission(false);store.hold(false,false,false,false);store.settle();
    store.finish("store_origin_exclusion");
    // In-aperture full-PA mismatch has both a free MSHR and response ticket.
    // It must create its own acquire, not inherit the existing PF transaction.
    Gate wrong;const auto w=seed(wrong,false);Episode f(wrong,w);f.start();wrong.permission(false);
    const uint64_t other=w.a+stride+24;const auto demandAlloc=wrong.n("demand_alloc");
    wrong.send({other},false);
    check(!f.attach&&!f.aRefill&&wrong.n("demand_alloc")==demandAlloc+1,
        "different valid full PA did not retain independent fresh demand ownership");
    // Actual home serializes same-set reservations. Release the original PF
    // after proving fresh cache ownership, then demand's own A/data may complete.
    f.release(true,true);wrong.hold(false,false,false,false);wrong.settle();
    unsigned ownAcquires=0;for(const auto&[key,owner]:wrong.owners)
        ownAcquires+=owner.address==line(other)&&!owner.pf&&owner.acquired&&owner.filled;
    check(ownAcquires==1&&f.aCount==1,"different full PA aliased existing PF acquire");
    check(wrong.find(other).has_value(),"different full PA did not install its own demand data");
    f.result("different_valid_full_pa");
    wrong.finish("different_valid_full_pa");
}
static void held_e_and_same_refill() {
    Gate g;const auto s=seed(g,false);Episode e(g,s);e.start();g.permission(false);
    g.hold(false,false,true,true);e.release(true,true);
    g.until([&]{return g.t.d.get_io$$grantAckOffer();},"PF did not hold E");
    const auto replies=g.t.cpuReturned;g.send({s.a+40,false,0,0},false);g.ticks(5);
    check(e.attach==1&&!e.aRefill&&!e.bCount&&g.t.cpuReturned==replies,"held E allowed early attached response/install");
    g.hold(false,false,false,false);g.settle();e.result("held_e_attach");g.finish("held_e_attach");
    Gate same;const auto t=seed(same,false);Episode f(same,t);f.start();same.permission(false);
    same.hold(false,false,true,true);f.release(true,true);
    same.until([&]{return same.t.d.get_io$$grantAckOffer();},"sameedge case lacks E offer");
    same.hold(false,false,false,true);same.until([&]{return same.t.d.get_io$$grantAckFire();},"sameedge E did not fire");
    same.begin({t.a+48});same.tick();
    check(same.t.d.get_io$$storePfObs$$refill()&&same.offered&&!f.attach,
        "demand attached on final engine response/install edge");
    same.until([&]{return !same.offered&&same.t.cpuExpected.empty();},"sameedge excluded read did not resume as hit");
    same.hold(false,false,false,false);same.settle();f.result("same_refill_exclusion");same.finish("same_refill_exclusion");
}
static void errors(unsigned mode) {
    Gate g;const auto s=seed(g);Episode e(g,s);g.t.ddr.denyReadAddress=uint32_t(s.a-base);
    g.t.d.set_io$$adoption$$faultMode(mode);g.t.d.set_io$$adoption$$faultBeat(mode==1?0:7);
    e.start();g.permission(false);const auto returned=g.t.cpuReturned;
    g.send({s.a+56,false,0,0},false);check(e.attach==1,"error PF did not adopt read");
    g.t.blockCpu=true;g.hold(false,false,true,true);e.release(true,true);
    g.until([&]{return g.t.d.get_io$$grantAckOffer();},"errored PF did not reach E");g.ticks(3);
    check(!e.aRefill&&g.t.cpuReturned==returned&&!g.find(s.a),"failed PF installed/responded before E");
    g.hold(false,false,false,true);g.until([&]{return e.aRefill==1;},"errored PF final result missing");g.ticks(4);
    check(!g.find(s.a)&&!g.present(g.token[0])&&g.t.cpuReturned==returned,"errored attached PF installed or escaped backpressure");
    g.t.blockCpu=false;drainExceptAck(g);check(g.t.cpuReturned==returned+1&&g.n("attached_response")==1,"error not returned exactly once");
    g.t.ddr.denyReadAddress.reset();g.t.d.set_io$$adoption$$faultMode(0);g.hold(false,false,false,false);g.settle();
    e.result(mode==1?"denied":"corrupt");g.send({s.a+56});g.finish(mode==1?"denied":"corrupt");
}
static void same_edge_first_error(unsigned mode) {
    Gate g;const auto s=seed(g,false);Episode e(g,s);
    g.t.ddr.denyReadAddress=uint32_t(s.a-base);
    g.t.d.set_io$$adoption$$faultMode(mode);g.t.d.set_io$$adoption$$faultBeat(0);
    e.start();g.permission(false);g.hold(false,true,true,true);e.release(true,true);
    g.until([&]{return g.t.d.get_io$$adoption$$grantOffer();},"sameedge error case lacks held real GrantData");
    check(g.t.d.get_io$$adoption$$grantError(),"sameedge Grant does not carry real home backing error");
    const auto returned=g.t.cpuReturned;
    g.begin({s.a+40,false,0,0x81});g.hold(false,false,true,true);g.tick();
    check(!g.offered&&e.attach==1&&g.t.d.get_io$$grantFire()&&
        (g.t.d.get_io$$storePfObs$$dDenied()||g.t.d.get_io$$storePfObs$$dCorrupt()),
        "first error D.fire and new demand attachment did not share preedge responsibility");
    g.until([&]{return g.t.d.get_io$$grantAckOffer();},"sameedge error failed to finish D");g.ticks(3);
    check(g.t.cpuReturned==returned&&!e.aRefill&&!g.find(s.a),"sameedge error completed before final E");
    g.hold(false,false,false,false);g.settle();
    check(g.t.cpuReturned==returned+1&&g.n("attached_response")==1&&!g.find(s.a),
        "sameedge first error did not fault attached current demand exactly once");
    e.result(mode==1?"sameedge_first_denied":"sameedge_first_corrupt");
    g.t.ddr.denyReadAddress.reset();g.t.d.set_io$$adoption$$faultMode(0);
    g.finish(mode==1?"sameedge_first_denied":"sameedge_first_corrupt");
}
static void known_error_before_demand(unsigned mode) {
    Gate g;const auto s=seed(g,false);Episode e(g,s);
    g.t.ddr.denyReadAddress=uint32_t(s.a-base);
    g.t.d.set_io$$adoption$$faultMode(mode);g.t.d.set_io$$adoption$$faultBeat(0);
    e.start();g.permission(false);g.hold(false,false,true,true);e.release(true,true);
    g.until([&]{return g.t.d.get_io$$grantAckOffer();},"known-error PF did not hold E");
    const auto returned=g.t.cpuReturned,accepted=g.t.cpuAccepted;
    g.begin({s.a+16,false,0,0});g.ticks(4);
    check(g.offered&&g.t.cpuAccepted==accepted&&!e.attach&&g.t.cpuReturned==returned,
        "known failed speculative PF attached later demand");
    g.t.ddr.denyReadAddress.reset();g.t.d.set_io$$adoption$$faultMode(0);
    g.hold(false,false,false,false);
    g.until([&]{return e.aRefill==1;},"known failed PF did not retire");
    check(!e.attach&&g.t.cpuReturned==returned&&!g.find(s.a),
        "unattached failed PF created response or successful install");
    g.until([&]{return !g.offered&&g.t.cpuExpected.empty();},"current read did not retry independently after known PF failure");
    g.settle();check(e.aCount==2&&g.t.cpuReturned==returned+1&&g.n("attached")==0,
        "known-error retry did not issue its separate current demand");
    std::cout<<"PREFETCH_DEMAND_ADOPTION_KNOWN_ERROR mode="<<mode<<" target_a="<<e.aCount
        <<" attach=0 current_response=1 speculative_response=0\n";
    g.finish(mode==1?"known_denied_before_demand":"known_corrupt_before_demand");
}
static void response_full_and_order() {
    {
        Gate g;const auto s=seed(g,false);Episode e(g,s);e.start();g.permission(false);
        g.t.blockCpu=true;g.send({s.source},false);g.send({s.source+8},false);
        check(g.t.cpuExpected.size()==2,"response-full case did not fill both tickets");
        noAccept(g,{s.a+8},4,"attachment overbooked full response tickets");
        g.t.blockCpu=false;g.until([&]{return !g.offered;},"held read did not attach after response space returned");
        check(e.attach==1,"response-full held read lost attachment after credit released");
        e.release(true,true);g.hold(false,false,false,false);g.settle();e.result("response_full");g.finish("response_full");
    }
    Gate g;const auto s=seed(g,false);Episode e(g,s);e.start();g.permission(false);
    // Older unrelated real demand completes after attached PF. Both hold tickets;
    // head order must prevent younger data escaping while the older is delayed.
    const uint64_t older=base+4096;bool holdOlder=true;
    const auto observer=g.t.observer;g.t.observer=[&,observer]{observer();for(auto&r:g.t.ddr.pendingReads)
        if(holdOlder&&base+r.address==older)r.due=g.t.cycles+1024;};
    g.send({older+8},false);g.send({s.a+32,false,0,0},false);check(e.attach==1,"ordered case did not adopt");
    const auto replies=g.t.cpuReturned;e.release(true,true);g.until([&]{return e.aRefill==1;},"younger adopted PF did not complete");
    g.ticks(4);check(g.t.cpuReturned==replies&&g.t.cpuExpected.size()==2,"younger response bypassed older ticket");
    holdOlder=false;for(auto&r:g.t.ddr.pendingReads)if(base+r.address==older)r.due=g.t.cycles+1;
    g.t.blockCpu=true;g.until([&]{return g.t.d.get_io$$cpu$$response$$valid();},"oldest response missing");g.ticks(5);
    g.t.blockCpu=false;g.hold(false,false,false,false);g.settle();
    for(unsigned i=0;i<8;++i)g.send({s.a+8*(i%8)});
    check(g.t.cpuAccepted>=12&&g.t.cpuAccepted==g.t.cpuReturned,"ticket wrap owner conservation failed");
    e.result("response_full_order_wrap");g.finish("response_full_order_wrap");
}
static void late_ack_reuse() {
    Gate g;Seed s;g.permission(false);
    for(unsigned w=0;w<8;++w)g.store(s.reuseVictim+8*w,0x55);
    for(unsigned w=0;w<8;++w)g.store(s.reuse+stride+8*w,0xaa);
    s=seed(g);Episode e(g,s);e.holdB=true;e.start();g.send({s.a+8},false);
    g.until([&]{return e.bCount==1;},"reuse case successor PF did not issue");e.release(true,false);
    g.until([&]{return e.aRefill==1&&g.t.cpuExpected.empty();},"attached A did not retire before old Ack");
    g.permission(false);g.hold(true,false,false,true);g.send({s.reuse+24},false);
    g.until([&]{return e.bothWb&&e.reused;},"old PF WB did not coexist with reused MSHR new capture");
    check(!e.ack&&e.savedWb&&g.wb[*e.savedWb],"old WB retired before intended late Ack");
    g.hold(false,false,false,false);e.release(true,true);g.settle();
    check(e.ack==1&&e.capture==1&&e.reused&&e.bothWb,"saved WB/reused owner conservation failed");
    e.result("late_ack_reuse_capture");g.finish("late_ack_reuse_capture");
}
static void probe_and_flush() {
    Gate g;const auto s=seed(g);Episode e(g,s);e.start();g.permission(false);g.send({s.a+16},false);
    g.t.dmaRequest=Request{s.a+24};g.ticks(8);check(!g.t.dmaReturned,"probe completed before reserved PF tail");
    g.startFlush();g.ticks(5);check(!g.t.d.get_io$$flushDone()&&!g.t.d.get_io$$cacheFlushDone(),"flush bypassed attached PF/WB");
    e.release(true,true);g.until([&]{return e.aRefill==1;},"flush prevented accepted attached owner completion");g.ticks(5);
    check(!e.ack&&!g.t.d.get_io$$flushDone()&&g.t.d.get_io$$prefetchBusy(),"flush lost held PF WB duty");
    g.hold(false,false,false,false);g.finishFlush();g.settle();e.result("probe_flush_tails");g.finish("probe_flush_tails");
}
static void posted_after_tails() {
    Gate g;const auto s=seed(g);Episode e(g,s);e.start();g.permission(false);g.send({s.a+8},false);
    Request posted{base+12288,true,0x123456789abcdef0ULL,255};posted.posted=true;
    noAccept(g,posted,5,"posted offer crossed attached PF owner");
    e.release(true,true);
    g.until([&]{return g.t.cpuExpected.empty()&&!g.active[0]&&!g.active[1]&&g.sources.empty();},
        "attached owner did not drain beneath held posted offer");
    g.ticks(5);check(g.offered&&!e.ack&&g.t.cpuRequest,"posted offer crossed saved PF WB tail");
    g.hold(false,false,false,false);
    g.until([&]{return !g.wb[0]&&!g.wb[1];},"saved PF WB did not drain beneath held posted offer");
    check(g.offered&&!g.t.d.get_io$$adoption$$postedAccepted(),"posted offer accepted before preedge WB drain");
    e.result("posted_blocked_by_tails");
    // Prior ordinary/PF/WB ledgers are now empty; retain the SAME stable offer.
    // Switch observation before its next eligible acceptance edge.
    check(g.sources.empty()&&!g.active[0]&&!g.active[1],"posted phase began before prior owners drained");
    unsigned postedAccepted=0,postedReleased=0;
    g.t.observer=[&]{postedAccepted+=g.t.d.get_io$$adoption$$postedAccepted();
        postedReleased+=g.t.d.get_io$$adoption$$postedReleased();check(!g.t.d.get_io$$adoption$$postedFailed(),"posted owner failed");};
    g.t.drainCpu();g.offered.reset();g.t.d.set_io$$adoption$$postedSeal(1);
    g.t.until([&]{return !g.t.d.get_io$$adoption$$postedBusy();},"post-drain posted owner failed to drain");
    check(postedAccepted==1&&postedReleased==1,"posted offer did not accept and retire after all tails");
    g.t.d.set_io$$flushRequest(1);g.t.until([&]{return g.t.d.get_io$$flushDone();},"post-adoption posted flush failed");
    for(const auto&[pa,word]:g.t.architectural)check(g.t.ddr.memory.at(uint32_t(pa-base))==word,"final posted byte oracle mismatch");
    check(g.t.cpuAccepted==g.t.cpuReturned&&g.t.grants.empty()&&!g.t.releasePending&&
        !g.t.ddr.writing&&!g.t.ddr.responding&&g.t.ddr.pendingReads.empty(),"final posted transport owner did not drain");
    if(!imageDirectory.empty()){
        std::filesystem::create_directories(imageDirectory);
        std::ofstream a(imageDirectory+"/posted_after_tails-actual.bin",std::ios::binary),x(imageDirectory+"/posted_after_tails-expected.bin",std::ios::binary);
        for(uint64_t o=0;o<BOARD_DDR_BYTES;o+=8)for(unsigned b=0;b<8;++b){a.put(char(g.t.ddr.memory.at(o)>>(8*b)));x.put(char(g.t.architectural.at(base+o)>>(8*b)));}
        check(bool(a)&&bool(x),"posted image write failed");
    }
    ++completedCases;std::cout<<"PREFETCH_DEMAND_ADOPTION_POSTED accepted="<<postedAccepted<<" released="<<postedReleased
        <<" cpu_accept="<<g.t.cpuAccepted<<" cpu_reply="<<g.t.cpuReturned<<" actual_generation_bits=64 fallback_dynamic=0\n";
}
}
int main(int argc,char**argv){
    try{
        using namespace dual_prefetch;using namespace adoption;
        for(int i=1;i<argc;++i){const std::string a=argv[i];
            if(a.rfind("--images=",0)==0)imageDirectory=a.substr(9);
            else if(a.rfind("--inject-",0)==0)mutation=a.substr(9);
            else throw std::runtime_error("unknown argument");}
        two_owner(false);two_owner(true);
        if(enabled){exclusions_and_first_a();held_e_and_same_refill();errors(1);errors(2);known_error_before_demand(1);known_error_before_demand(2);same_edge_first_error(1);same_edge_first_error(2);
            response_full_and_order();late_ack_reuse();probe_and_flush();posted_after_tails();}
        check(mutation.empty(),"requested poisoned oracle did not trigger");
        std::cout<<"PREFETCH_DEMAND_ADOPTION_PASS enabled="<<enabled<<" cases="<<completedCases
            <<" real_posted_cache_home=1 default_off=1 executing_cpu=0 performance_qualification=0\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<"PREFETCH_DEMAND_ADOPTION_FAIL "<<e.what()<<'\n';return 1;}
}
