// Actual cache/home lifecycle qualification. DUT internals are read-only.
// Independent byte, full-PA residency, response, and saved-WB ledgers are reused unchanged.
#ifndef DURABLE_READ_PREFETCH
#error "explicit matched durable/capture 0|1 required"
#endif
#define main original_adoption_main
#include "prefetch_demand_adoption.cpp"
#undef main
namespace durable {
using namespace dual_prefetch;
constexpr bool enabled = DURABLE_READ_PREFETCH;
constexpr uint64_t target=base+512, scratch=base+8192;
struct Watch {
    Gate& g; uint64_t address; std::function<void()> prior;
    unsigned captures=0,pending=0,held=0,writes=0,allocations=0,terminal=0,sendHolds=0;
    unsigned remaining=16; bool expect=false,have=false,armed=true;
    Watch(Gate& gate,uint64_t a):g(gate),address(a),prior(g.t.observer) {
        g.t.observer=[&] {
            auto& d=g.t.d;
            if(have) {
                check(bool(d.cache$candidateValid)==expect,"candidate next-edge validity mismatch");
                if(expect)check(unsigned(d.cache$candidateRemaining)==remaining,"candidate deadline refreshed");
            }
            expect=d.cache$candidateValid$NEXT;if(expect)remaining=d.cache$candidateRemaining$NEXT;have=true;
            if(armed&&d.get_io$$storePfObs$$candidate()&&!d.get_io$$storePfObs$$candidateStore()&&
                line(g.offered->address)+64==address) {
                bool permission=g.authorized;
                if(mutation=="permission"&&!mutationTriggered){mutationTriggered=true;permission=false;
                    std::cerr<<"DURABLE_READ_MUTATION_TRIGGER permission actual_candidate=1\n";}
                check(permission,"candidate lacks independent current READ permission");++captures;
            }
            if(armed&&d.cache$candidateValid&&d.cache$candidateAddress==address) {
                ++pending;check(!d.cache$candidateStore,"durable candidate changed READ origin");
                check(d.get_io$$prefetchBusy(),"valid candidate dropped architectural drain busy");
                const bool fire=g.t.cpuAccepted!=g.accepted;
                if(g.offered&&g.offered->write) {
                    ++writes;held+=!fire;sendHolds+=!fire&&d.cache$evictionState==2;
                    terminal+=!fire&&d.get_io$$storePfObs$$refill();
                    check(!d.get_io$$storePfObs$$allocated(),"offered WRITE allocated prefetch");
                }
                if(d.cache$candidateValid$NEXT) {
                    check(d.cache$candidateRemaining>0&&d.cache$candidateRemaining$NEXT+1==d.cache$candidateRemaining,
                        "retention did not spend exactly one original attempt");
                    bool observed=d.cache$candidateValid$NEXT;
                    if(mutation=="hold-next"&&!mutationTriggered&&enabled&&g.offered&&g.offered->write&&!fire){
                        mutationTriggered=true;observed=false;std::cerr<<"DURABLE_READ_MUTATION_TRIGGER hold-next actual_held=1\n";}
                    check(observed,"retained real held-store candidate NEXT was corrupted");
                }
            }
            if(armed&&d.get_io$$storePfObs$$allocated()&&d.get_io$$storePfObs$$allocatedAddress()==address) {
                bool tokenOccupied=g.present(g.token[0]);
                if(mutation=="token-capacity"&&!mutationTriggered&&enabled){mutationTriggered=true;tokenOccupied=true;
                    std::cerr<<"DURABLE_READ_MUTATION_TRIGGER token-capacity actual_allocation=1\n";}
                check(!tokenOccupied,"allocation overwrote a pre-edge full-PA READ token");
                check(!d.cache$candidateValid$NEXT,"allocation retained duplicate candidate");++allocations;
                check(allocations==1,"one captured hint allocated twice");
            }
            if(mutation=="refill-error"&&!mutationTriggered&&d.get_io$$storePfObs$$refill()&&d.get_io$$storePfObs$$refillError()){
                mutationTriggered=true;const bool observed=!bool(d.get_io$$storePfObs$$refillError());
                std::cerr<<"DURABLE_READ_MUTATION_TRIGGER refill-error actual_error=1\n";
                check(observed==true,"real late-error response ownership corrupted");
            }
            prior();
        };
    }
    void end(const char* name) {
        std::cout<<"DURABLE_READ_RESULT name="<<name<<" enabled="<<enabled<<" captures="<<captures<<" pending="<<pending
            <<" held="<<held<<" writes="<<writes<<" send_holds="<<sendHolds<<" terminal_holds="<<terminal<<" allocations="<<allocations<<'\n';
        armed=false;g.t.observer=prior;
    }
};
static void seed(Gate& g) {g.permission(false);g.store(scratch,0x55);g.prepare(target,false);g.permission(true);}
static void dirty_send() {
    Gate g;g.permission(false);g.store(scratch,0x55);g.store(target-128,0x55);
    g.store(target-64+stride,0x55);g.store(target-64+2*stride,0xaa);g.send({target-128});
    check(!g.find(target-64),"source dirty-demand fixture unexpectedly resident");
    g.permission(true);g.hold(true,false,false,true);Watch w(g,target);g.trigger(target,false,false);
    g.until([&]{return g.t.d.cache$evictionState==2&&g.t.d.get_io$$storePfObs$$cValid();},"source demand did not reach real dirty eSend");
    g.begin({scratch,true,0x9182736455463728ULL,0x55});g.tick();
    check(g.offered&&w.held==1&&w.sendHolds==1,"real eSend did not hold ordinary resident write");
    check(bool(g.t.d.cache$candidateValid$NEXT)==enabled,"old-cancel/new-retain witness disagrees");
    g.hold(false,false,false,true);g.until([&]{return !g.offered;},"held resident store failed to accept after C drained");
    g.until([&]{return !g.t.d.get_io$$storePfObs$$pendingCandidateValid();},"finite dirty-source candidate did not resolve");
    check(w.captures==1&&w.allocations==unsigned(enabled),"dirty held STORE lost later one-allocation opportunity");
    check(g.t.releasePending>0,"dirty-source witness failed to preserve real pending WB ACK");
    w.end("dirty_esend_held_store");g.hold(false,false,false,false);g.settle();g.permission(false);g.send({target});
    g.finish("dirty_esend_held_store");
}
static void deadline(bool expire) {
    Gate g;seed(g);Watch w(g,target);g.trigger(target,false,false);
    for(unsigned i=0;i<(expire?16U:15U);++i)g.store(scratch+8*(i%8),0x55,false);
    g.settle();check(w.captures==1&&w.pending==16&&w.allocations==unsigned(!expire),"original final-attempt/expiry boundary changed");
    w.end(expire?"deadline_expiry":"deadline_final_attempt");g.permission(false);g.send({target});
    g.finish(expire?"deadline_expiry":"deadline_final_attempt");
}
static void owner_blocker(bool store) {
    Gate g;g.permission(false);g.store(scratch,0x55);g.prepare(target,false);
    const uint64_t blocker=target+stride;g.prepare(blocker,store);g.permission(true);g.hold(false,false,true,false);
    g.trigger(blocker,store);g.until([&]{return g.t.d.get_io$$grantAckOffer();},"blocker never reached held real E");
    if(!store)g.send({target-128});
    Watch w(g,target);g.trigger(target,false,false);
    check(w.captures==unsigned(enabled&&store),"capture did not distinguish sole STORE PF from READ PF");
    if(enabled&&store){g.ticks(2);check(w.pending==2&&!w.allocations,"same-set STORE owner was not a bounded allocation wait");}
    g.hold(false,false,false,false);g.until([&]{return g.t.d.get_io$$grantAckFire();},"blocker held E failed to retire");
    g.begin({scratch,true,0x123498765abcdef0ULL,0x55});g.tick();
    check(g.offered&&g.t.d.get_io$$storePfObs$$refill(),"held terminal refill variant missed actual write-port hazard");
    g.settle();check(w.allocations==unsigned(enabled&&store),"same-set capture did not allocate once after owner drain");
    if(enabled&&store)check(w.terminal==1,"durable terminal-refill hold not observed");
    w.end(store?"store_owner_same_set_terminal":"read_owner_capture_rejected");g.permission(false);g.send({target});
    g.finish(store?"store_owner_same_set_terminal":"read_owner_capture_rejected");
}
static void cancel(const std::string& kind) {
    Gate g;seed(g);
    if(kind=="probe") {g.t.blockCpu=true;g.send({target-128+8},false);}
    Watch w(g,target);g.trigger(target,false,false);
    Request q{scratch,true,0xfedcba9876543210ULL,0x55};
    if(kind=="posted")q.posted=true;
    if(kind=="flush")g.startFlush();
    if(kind=="probe")g.t.dmaRequest=Request{scratch};
    g.begin(q);g.tick();
    if(kind=="probe") {
        g.until([&]{return g.t.d.get_io$$probeFire();},"legal DMA did not invalidate held store's resident line");
        check(g.offered&&!g.find(scratch)&&!g.t.d.cache$candidateValid$NEXT,
            "held write survived probe/cached-hit-to-miss class change");
        g.t.blockCpu=false;
    } else check(!g.t.d.cache$candidateValid$NEXT,"posted/flush failed terminal candidate cancellation");
    if(kind=="flush") {
        g.until([&]{return g.t.d.get_io$$flushDone();},"flush failed beside stable held STORE");
        for(const auto&[a,v]:g.t.architectural)check(g.t.ddr.memory.at(uint32_t(a-base))==v,"pre-store flush mismatch");
        g.t.d.set_io$$flushRequest(0);g.flushing=false;g.tick();
    }
    g.settle();check(!w.allocations,"terminally cancelled candidate resurrected");
    if(kind=="posted")check(!g.t.d.get_io$$adoption$$postedAccepted(),"proof-bearing resident store took conflicting posted route");
    const std::string name="cancel_"+kind;w.end(name.c_str());g.finish(name.c_str());
}
static void permission_token() {
    Gate g;seed(g);g.permission(false);Watch w(g,target);g.trigger(target,false);g.settle();
    check(!w.captures&&!w.allocations,"denied READ hint formed a candidate");
    g.permission(true);g.send({target-56});g.settle();check(w.allocations==1&&g.present(g.token[0]),"real READ token fixture failed");
    const auto c=g.n("read_candidate"),a=g.n("read_alloc");g.send({target-48});g.settle();
    check(g.n("read_candidate")==c&&g.n("read_alloc")==a,"occupied READ token admitted/overwrote new candidate");
    w.end("permission_and_occupied_read_token");g.permission(false);g.send({target});g.finish("permission_and_occupied_read_token");
}
static void error_case(unsigned mode) {
    // Unchanged actual dirty/adoption/error fixtures, rerun on each current model.
    if(mutation=="refill-error") {
        Gate g;const auto s=adoption::seed(g);adoption::Episode e(g,s);Watch w(g,s.a);
        g.t.ddr.denyReadAddress=uint32_t(s.a-base);g.t.d.set_io$$adoption$$faultMode(mode);g.t.d.set_io$$adoption$$faultBeat(7);
        e.start();g.permission(false);g.send({s.a+56},false);e.release(true,true);g.hold(false,false,false,false);g.settle();
        check(false,"late-error negative did not fail");
    }
    adoption::errors(mode);
}
}
int main(int argc,char**argv) {
    try {
        std::cout<<std::unitbuf;using namespace dual_prefetch;
        for(int i=1;i<argc;++i){std::string a=argv[i];if(a.rfind("--images=",0)==0)imageDirectory=a.substr(9);
            else if(a.rfind("--inject-",0)==0)mutation=a.substr(9);else throw std::runtime_error("unknown argument");}
        durable::dirty_send();durable::deadline(false);durable::deadline(true);
        durable::owner_blocker(true);durable::owner_blocker(false);
        durable::cancel("posted");durable::cancel("flush");durable::cancel("probe");
        durable::permission_token();durable::error_case(1);durable::error_case(2);adoption::two_owner(true);
        check(mutation.empty(),"requested negative failed to mutate and fail");
        check(completedCases==12,"focused directed case inventory differs");
        std::cout<<"DURABLE_READ_PREFETCH_PASS enabled="<<durable::enabled<<" cases="<<completedCases
            <<" real_cache_home=1 bytes_full_pa_wb_generation=1 cpu_qualification=0 physical_qualification=0\n";return 0;
    }catch(const std::exception&e){std::cerr<<"DURABLE_READ_PREFETCH_FAIL "<<e.what()<<'\n';return 1;}
}
