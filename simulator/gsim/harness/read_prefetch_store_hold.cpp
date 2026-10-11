// Real posted-enabled cache/home. The independent resident/owner/byte oracle is
// unchanged. Internal fields below are passive diagnostics only, never written.
#ifndef READ_PF_STORE_HOLD
#error "explicit OFF/ON policy required"
#endif
#include "prefetch_demand_adoption_oracle.h"
namespace store_hold {
using namespace dual_prefetch;
constexpr bool enabled = READ_PF_STORE_HOLD;
struct Watch {
    Gate& g; uint64_t target;
    std::function<void()> prior;
    unsigned candidates=0, pending=0, holds=0, acceptedWrites=0, heldWrites=0, allocations=0, expiries=0;
    bool nextValid=false, haveNext=false; unsigned nextRemaining=0;
    explicit Watch(Gate& gate,uint64_t address):g(gate),target(address),prior(g.t.observer) {
        g.t.observer=[&] {
            auto& d=g.t.d;
            if(haveNext) {
                check(bool(d.cache$candidateValid)==nextValid,"candidate NEXT failed real next-edge readback");
                if(nextValid) check(unsigned(d.cache$candidateRemaining)==nextRemaining,"candidate lifetime next-edge mismatch");
            }
            nextValid=d.cache$candidateValid$NEXT;nextRemaining=d.cache$candidateRemaining$NEXT;haveNext=true;
            const bool matching=d.cache$candidateValid&&d.cache$candidateAddress==target;
            if(d.get_io$$storePfObs$$candidate()&&!d.get_io$$storePfObs$$candidateStore())++candidates;
            if(matching) {
                ++pending;
                const bool fire=g.t.cpuAccepted!=g.accepted;
                const bool write=g.offered&&g.offered->write;
                if(write){acceptedWrites+=fire;heldWrites+=!fire;check(!d.cache$canAllocate,"write cycle allocated a PF");}
                if(d.cache$candidateValid$NEXT&&write) {
                    ++holds;
                    check(enabled&&fire&&g.offered&&!g.offered->posted&&!g.offered->uncached&&
                        !g.offered->atomic&&!g.offered->virtualized&&g.find(g.offered->address),
                        "hold lacks accepted authored ordinary resident store");
                    check(!d.cache$candidateStore&&!d.cache$postedIntent&&!d.get_io$$adoption$$postedBusy()&&
                        d.cache$evictionState==0&&d.cache$storeWrite&&d.cache$candidateRemaining>0&&
                        d.cache$candidateRemaining$NEXT+1==d.cache$candidateRemaining,
                        "hold changed origin, route, finite budget or idle requirement");
                    bool observedNext=d.cache$candidateValid$NEXT;
                    if(mutation=="hold-next"&&!mutationTriggered){mutationTriggered=true;observedNext=!observedNext;
                        std::cerr<<"READ_PREFETCH_STORE_HOLD_MUTATION_TRIGGER hold-next real_sample=1\n";}
                    check(observedNext,"mutated real hold NEXT rejected by independent store schedule");
                }
                if(write&&fire&&!d.cache$candidateRemaining&&!d.cache$candidateValid$NEXT)++expiries;
            }
            if(d.get_io$$storePfObs$$allocated()&&d.get_io$$storePfObs$$allocatedAddress()==target)++allocations;
            prior();
        };
    }
    void finish(const char* name) {
        std::cout<<"READ_PREFETCH_STORE_HOLD_RESULT name="<<name<<" enabled="<<enabled<<" candidates="<<candidates
            <<" pending="<<pending<<" holds="<<holds<<" accepted_writes="<<acceptedWrites<<" held_writes="<<heldWrites
            <<" allocations="<<allocations<<" expiries="<<expiries<<'\n';
        g.t.observer=prior;
    }
};
constexpr uint64_t target=base+512, scratch=base+8192;
static void seed(Gate& g,bool origin=false) {
    g.permission(false);g.store(scratch,0x55);g.prepare(target,origin);g.permission(true);
}
static void accepted_store(unsigned count,bool fault=false) {
    Gate g;seed(g);Watch w(g,target);
    if(fault){g.t.ddr.denyReadAddress=uint32_t(target-base);g.t.d.set_io$$adoption$$faultMode(2);g.t.d.set_io$$adoption$$faultBeat(3);}
    const auto before=g.n("read_candidate");g.trigger(target,false,false);
    check(g.n("read_candidate")==before+1,"source did not create one read candidate");
    for(unsigned i=0;i<count;++i)g.store(scratch+8*(i%8),0x55,false);
    g.permission(false);g.settle();
    const bool expires=count>=16;
    check(w.acceptedWrites==(enabled?std::min(count,16u):1u)&&w.heldWrites==0,"authored continuous writes did not all accept");
    check(w.holds==(enabled?std::min(count,15u):0u),"old cancel/new finite hold schedule mismatch");
    check(w.allocations==unsigned(enabled&&!expires),"later allocation/expiry differs from bounded hold contract");
    check(w.expiries==unsigned(enabled&&expires),"continuous writes did not expire at original bound");
    if(fault)check(g.n("pf_error")==unsigned(enabled),"retained PF error did not drain its original owner");
    g.t.ddr.denyReadAddress.reset();g.t.d.set_io$$adoption$$faultMode(0);
    const auto a=g.n("demand_alloc");g.send({target+24});g.settle();
    check(g.n("demand_alloc")==a+unsigned(!enabled||expires||fault),"target demand did not use correct resident/refill route");
    const char* name=fault?"hold_then_error":expires?"continuous_write_expiry":count==1?"hold_then_allocate":"repeated_hold_then_allocate";
    w.finish(name);g.finish(name);
}
static void held_write() {
    Gate g;seed(g);g.t.blockCpu=true;g.send({target-128+8},false);Watch w(g,target);
    g.trigger(target,false,false);g.begin({scratch,true,0x91abcdef12345678ULL,0x55});g.tick();
    check(w.heldWrites==1&&!w.holds&&!w.allocations,"response-full held store retained candidate");
    g.permission(false);g.t.blockCpu=false;g.settle();
    check(w.pending==1&&!w.allocations,"held store later revived cancelled candidate");
    w.finish("held_write_cancels");g.finish("held_write_cancels");
}
static void excluded(const std::string& which) {
    Gate g;seed(g,which=="store_origin");
    if(which=="present"){g.permission(false);g.send({target});g.prepare(target,false);g.permission(true);}
    if(which=="dirty_victim"){
        g.permission(false);g.send({target+stride});g.store(target+2*stride);g.prepare(target,false);g.permission(true);
    }
    Watch w(g,target);g.trigger(target,which=="store_origin",false);
    if(which=="flush")g.startFlush();
    Request q{scratch,true,0xfedcba9876543210ULL,0x55};
    if(which=="dirty_victim")q.address=target+stride;
    if(which=="posted_legacy_hit"){q.posted=true;q.mask=255;}
    if(which=="uncached"){q.write=false;q.uncached=true;q.mask=255;}
    g.begin(q);g.tick();
    const unsigned dirtyHold=unsigned(enabled&&which=="dirty_victim");
    check(w.pending==1&&w.holds==dirtyHold&&!w.allocations,"excluded candidate retention differs from authored victim change");
    if(which=="flush") {
        // The authored store remains held until flush completes. Verify the
        // pre-store backing image before releasing flush, then let the same
        // request accept and use the final flush to verify its new bytes.
        g.until([&]{return g.t.d.get_io$$flushDone();},"flush did not complete beside held store");
        for(const auto&[a,v]:g.t.architectural)check(g.t.ddr.memory.at(uint32_t(a-base))==v,
            "pre-store flush independent backing mismatch");
        g.t.d.set_io$$flushRequest(0);g.flushing=false;g.tick();
    }
    g.until([&]{return !g.offered;},"excluded held request did not accept");g.permission(false);
    g.settle();check(w.pending==1+dirtyHold&&!w.allocations,"excluded candidate failed to recheck current dirty victim");
    w.finish(which.c_str());g.finish(which.c_str());
}
// A new posted owner is blocked by pre-edge candidateBusy, then progresses once
// cancellation and the preceding read response drain. This directly tests that
// the new hold cannot create a candidateBusy/posted admission deadlock.
static void posted_offer() {
    Gate g;seed(g);Watch w(g,target);g.trigger(target,false,false);
    Request q{base+12288,true,0x123456789abcdef0ULL,255};q.posted=true;
    g.begin(q);g.tick();
    check(w.pending==1&&!w.holds&&!w.allocations&&g.offered&&!g.t.d.get_io$$adoption$$postedAccepted(),
        "posted new-owner offer crossed candidate edge");
    w.finish("posted_new_owner_cancels");
    unsigned accepted=0,released=0;
    g.t.observer=[&]{accepted+=g.t.d.get_io$$adoption$$postedAccepted();released+=g.t.d.get_io$$adoption$$postedReleased();
        check(!g.t.d.get_io$$storePfObs$$allocated(),"cancelled candidate allocated during posted work");
        check(!g.t.d.get_io$$adoption$$postedFailed(),"posted owner failed");};
    g.t.drainCpu();g.offered.reset();g.permission(false);g.t.d.set_io$$adoption$$postedSeal(1);
    g.t.until([&]{return !g.t.d.get_io$$adoption$$postedBusy();},"candidateBusy/posted deadlock");
    check(accepted==1&&released==1,"posted responsibility did not accept and drain exactly once");
    g.t.flush();check(g.t.cpuAccepted==g.t.cpuReturned,"posted response conservation failed");
    if(!imageDirectory.empty()) {
        std::filesystem::create_directories(imageDirectory);
        std::ofstream a(imageDirectory+"/posted_new_owner_cancels-actual.bin",std::ios::binary),x(imageDirectory+"/posted_new_owner_cancels-expected.bin",std::ios::binary);
        for(uint64_t o=0;o<BOARD_DDR_BYTES;o+=8)for(unsigned b=0;b<8;++b){a.put(char(g.t.ddr.memory.at(o)>>(8*b)));x.put(char(g.t.architectural.at(base+o)>>(8*b)));}
        check(bool(a)&&bool(x),"posted image write failed");
    }
    ++completedCases;
    std::cout<<"READ_PREFETCH_STORE_HOLD_POSTED accepted="<<accepted<<" released="<<released<<" final_image_bytes="<<BOARD_DDR_BYTES<<'\n';
}
}
int main(int argc,char**argv) {
    try {
        std::cout<<std::unitbuf;
        using namespace dual_prefetch;using namespace store_hold;
        for(int i=1;i<argc;++i){const std::string a=argv[i];if(a.rfind("--images=",0)==0)imageDirectory=a.substr(9);
            else if(a.rfind("--inject-",0)==0)mutation=a.substr(9);else throw std::runtime_error("unknown argument");}
        accepted_store(1);accepted_store(5);accepted_store(18);accepted_store(1,true);held_write();
        for(const char* s:{"store_origin","posted_legacy_hit","uncached","flush","present","dirty_victim"})excluded(s);
        posted_offer();
        check(mutation.empty(),"requested negative did not trigger");
        check(completedCases==12,"directed case inventory differs");
        std::cout<<"READ_PREFETCH_STORE_HOLD_PASS enabled="<<enabled<<" cases="<<completedCases
            <<" real_posted_cache_home=1 exact_bytes_and_owners=1 executing_cpu=0 performance_qualification=0\n";return 0;
    }catch(const std::exception&e){std::cerr<<"READ_PREFETCH_STORE_HOLD_FAIL "<<e.what()<<'\n';return 1;}
}
