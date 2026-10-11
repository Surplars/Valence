// Additive host gate. Keep all qualified transport/oracle/source files unchanged.
// The renamed original entry point is deliberately not executed: its prior PASS
// remains separately bound, while this binary qualifies only the new cases.
#define main qualified_adoption_main
#include "prefetch_demand_adoption.cpp"
#undef main

namespace adoption_exclusions {
using namespace adoption;
static std::string negative;
static bool same(const Request& a,const Request& b) {
    return std::tie(a.address,a.write,a.data,a.mask,a.uncached,a.atomic,a.virtualized,a.posted,a.atomicOp)==
        std::tie(b.address,b.write,b.data,b.mask,b.uncached,b.atomic,b.virtualized,b.posted,b.atomicOp);
}
static void excluded(unsigned kind) {
    const char* names[]={"ordinary_store","atomic_add","uncached_read"};
    const std::string name=names[kind];
    Gate g;const auto s=seed(g,false);Episode e(g,s);e.start();g.permission(false);
    check(e.original&&e.aCount==1&&!e.aRefill&&!e.attach,"exclusion lacks issued pending read PF");
    const Key original=*e.original;
    const auto accepted=g.t.cpuAccepted,returned=g.t.cpuReturned,alloc=g.n("demand_alloc");
    const auto captures=g.n("other_capture");
    Request q{s.a+24};
    if(kind==0){q.write=true;q.data=0x76543210fedcba98ULL;q.mask=0x5a;}
    if(kind==1){q.atomic=true;q.atomicOp=0;q.data=0x1020304050607081ULL;}
    if(kind==2)q.uncached=true;
    const bool poison=negative==name;
    // The negative changes a real external request, removing its sole excluded
    // class so the actual DUT must attach. This is not a poisoned zero counter.
    if(poison){q.write=false;q.atomic=false;q.uncached=false;q.data=0;q.mask=255;}
    const uint64_t oldWord=g.t.architectural.at(q.address);
    const uint64_t newWord=kind==0?Test::merge(oldWord,q.data,q.mask):kind==1?oldWord+q.data:oldWord;
    if(!poison&&kind!=2)check(newWord!=oldWord,"excluded update has vacuous unchanged bytes");
    unsigned stableSamples=0,acceptedOnce=0,returnedOnce=0;
    uint64_t acceptCycle=0,replyCycle=0;
    const auto beforeStep=g.t.beforeStep;
    g.t.beforeStep=[&,beforeStep]{
        if(beforeStep)beforeStep();
        if(g.t.cpuRequest){check(same(*g.t.cpuRequest,q)&&g.offered&&same(*g.offered,q),
            "held excluded request payload changed or was cancelled");++stableSamples;}
    };
    const auto observer=g.t.observer;
    g.t.observer=[&,observer]{
        const bool fire=g.t.cpuAccepted!=g.accepted;
        if(fire&&!poison&&kind==1){
            // Independent AMOADD.D semantics at accepted external boundary.
            // Test already reserved the exact old-value response expectation.
            check(q.atomic&&q.atomicOp==0&&!q.write&&q.mask==255,"AMO oracle called for other operation");
            check(g.t.architectural.at(q.address)==oldWord,"AMO old bytes changed before acceptance");
            g.t.architectural.at(q.address)=newWord;
        }
        observer();
        if(fire){
            ++acceptedOnce;acceptCycle=g.t.cycles;
            if(!poison){
                const auto& o=g.owners.at(original);
                check(o.pf&&!o.store&&o.filled&&o.acked&&!o.attached&&!o.error&&o.refillCycle<acceptCycle,
                    "excluded request accepted before original PF responsibility drained");
                check(!g.t.d.get_io$$storePfObs$$demandAttach()&&!g.t.d.get_io$$storePfObs$$demandAlloc(),
                    "excluded request attached or allocated a duplicate demand owner");
                check(bool(g.t.d.get_io$$hit())==(kind==0),"excluded request used wrong ordinary/bypass route");
            }
        }
        if(g.t.retiredThisTick){
            ++returnedOnce;replyCycle=g.t.cycles;
            check(g.t.retiredThisTick->sequence==accepted&&g.t.retiredThisTick->address==q.address&&
                !g.t.retiredThisTick->error&&!g.t.retiredThisTick->cancelled,
                "excluded response lost exact accepted sequence/address/error");
        }
    };
    g.begin(q);g.ticks(6);
    if(poison){
        std::cerr<<"PREFETCH_ADOPTION_EXCLUSION_NEGATIVE name="<<name
            <<" changed_external_class=1 actual_attach="<<e.attach
            <<" actual_accept_delta="<<g.t.cpuAccepted-accepted<<'\n';
        check(e.attach==1&&g.t.cpuAccepted==accepted+1,"negative did not change actual DUT attachment");
        throw std::runtime_error("excluded-demand class mutation caused actual pending-PF attachment");
    }
    check(g.offered&&g.t.cpuRequest&&g.t.cpuAccepted==accepted&&g.t.cpuReturned==returned&&!e.attach,
        "excluded request attached or replied while original PF data was pending");
    g.hold(false,false,true,true);e.release(true,true);
    g.until([&]{return g.t.d.get_io$$grantAckOffer();},"excluded PF did not reach held E");g.ticks(3);
    check(g.offered&&g.t.cpuRequest&&g.t.cpuAccepted==accepted&&!e.attach&&!e.aRefill,
        "excluded request crossed original PF held-E responsibility");
    g.hold(false,false,false,false);g.settle();
    check(acceptedOnce==1&&returnedOnce==1&&g.t.cpuAccepted==accepted+1&&g.t.cpuReturned==returned+1&&
        replyCycle>acceptCycle&&stableSamples>=9&&!e.attach&&e.aCount==1&&e.aRefill==1&&!e.bCount&&
        g.n("demand_alloc")==alloc&&!g.n("attached_response"),"excluded eventual owner/response conservation failed");
    check(g.n("other_capture")==captures+unsigned(kind!=0),"bypass did not release exact prefetched resident line");
    check(g.t.architectural.at(q.address)==newWord,"excluded update differs from independent byte semantics");
    if(kind==0)check(g.find(q.address)&&g.resident[*g.find(q.address)].dirty,"ordinary store did not dirty installed PF line");
    else check(!g.find(q.address),"bypass retained prefetched cache line");
    // Existing full-memory flush, C/D/E/tag/error/ticket/owner checks stay active.
    g.t.beforeStep=beforeStep;g.t.observer=observer;
    e.result(names[kind]);g.finish(names[kind]);
    unsigned changedBytes=0;for(unsigned b=0;b<8;++b)changedBytes+=uint8_t(oldWord>>(8*b))!=uint8_t(newWord>>(8*b));
    std::cout<<"PREFETCH_ADOPTION_EXCLUSION_RESULT name="<<name
        <<" stable_offer_samples="<<stableSamples<<" accepted="<<acceptedOnce<<" responses="<<returnedOnce
        <<" attach=0 target_acquires=1 target_refills=1 ordinary_hit="<<(kind==0)
        <<" bypass="<<(kind!=0)<<" changed_bytes="<<changedBytes<<" exact_error=0 owner_generation="<<original.second
        <<" refill_cycle="<<g.owners.at(original).refillCycle<<" accept_cycle="<<acceptCycle
        <<" response_cycle="<<replyCycle<<" full_image_bytes="<<BOARD_DDR_BYTES<<'\n';
}
}
int main(int argc,char** argv){
    try{
        using namespace adoption_exclusions;
        check(enabled,"new exclusions require the explicitly enabled qualified model");
        for(int i=1;i<argc;++i){const std::string a=argv[i];
            if(a.rfind("--images=",0)==0)imageDirectory=a.substr(9);
            else if(a.rfind("--inject-class=",0)==0)negative=a.substr(15);
            else throw std::runtime_error("unknown extension argument");}
        const char* names[]={"ordinary_store","atomic_add","uncached_read"};
        for(unsigned i=0;i<3;++i)if(negative.empty()||negative==names[i])excluded(i);
        check(negative.empty(),"requested exclusion negative did not trigger");
        check(completedCases==3,"extension directed case inventory differs");
        std::cout<<"PREFETCH_ADOPTION_EXCLUSIONS_PASS cases=3 original_cases_rerun=0 real_posted_cache_home=1"
            <<" exact_models_reused=1 executing_cpu=0 performance_qualification=0\n";
        return 0;
    }catch(const std::exception& e){std::cerr<<"PREFETCH_ADOPTION_EXCLUSIONS_FAIL "<<e.what()<<'\n';return 1;}
}
