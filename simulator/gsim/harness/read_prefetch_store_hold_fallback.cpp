// Test-only 2-bit posted generations are exhausted using four real transactions.
// No private DUT state is written. Standard transport retains the independent
// accepted CPU/AXI/coherence byte and source/response owner oracle.
#define CACHE_BASE 0x1000080010000ULL
#define MIXED_MODEL 1
#define MIXED_RTL 1
#define CACHE_HOME_EMBED
#include "prefetch_demand_adoption_transport.h"
#include <filesystem>
#include <fstream>
int main(int argc,char**argv) {
    try {
        std::cout<<std::unitbuf;bool injectNonposted=false;
        std::string images;for(int i=1;i<argc;++i){std::string a=argv[i];if(a.rfind("--images=",0)==0)images=a.substr(9);else if(a=="--inject-nonposted")injectNonposted=true;else throw std::runtime_error("unknown argument");}
        Test t;t.readyAlways=true;
        t.d.set_io$$prefetchPmpCfg(0x18);t.d.set_io$$prefetchPrivilege(1);
        unsigned accepted=0,released=0,fallback=0,pfAllocated=0,overlap=0;
        t.observer=[&]{accepted+=t.d.get_io$$adoption$$postedAccepted();released+=t.d.get_io$$adoption$$postedReleased();
            fallback+=t.d.get_io$$adoption$$postedFallback();pfAllocated+=t.d.get_io$$storePfObs$$allocated();
            check(!t.d.get_io$$adoption$$postedFailed(),"posted generation prefill failed");};
        for(unsigned i=0;i<4;++i){
            Request q{base+8192+64*i,true,0x912345678abcdef0ULL+i,255};q.posted=true;
            t.cpu(q);t.d.set_io$$adoption$$postedSeal(1);
            t.until([&]{return !t.d.get_io$$adoption$$postedBusy();},"posted generation did not drain");
            t.d.set_io$$adoption$$postedSeal(0);t.tick();
            check(accepted==i+1&&released==i+1&&!fallback,"four real generations did not allocate exactly once each");
        }
        constexpr uint64_t target=base+512,scratch=base+8192;
        t.cpu({target-128,true,0x1111222233334444ULL,0x55});
        t.cpu({target-64,true,0xaaaabbbbccccddddULL,0xaa});
        t.cpu({target-128});t.d.set_io$$prefetchPmpCfg(0x1f);t.d.set_io$$prefetchPrivilege(3);
        t.cpu({target-64},false);
        check(t.d.get_io$$storePfObs$$candidate()&&t.d.cache$candidateValid$NEXT,
            "exhausted fallback schedule lacks original read candidate");
        Request q{scratch,true,0xfedcba9876543210ULL,255};q.posted=!injectNonposted;
        if(injectNonposted)std::cerr<<"READ_PREFETCH_STORE_HOLD_FALLBACK_MUTATION_TRIGGER real_external_proof_removed=1\n";
        check(!t.cpuRequest,"pending source was not accepted");t.cpuRequest=q;
        const auto before=t.cpuAccepted;
        const auto prior=t.observer;t.observer=[&]{prior();
            if(t.d.cache$candidateValid&&t.d.cache$candidateAddress==target){
                ++overlap;check(bool(t.cpuRequest)&&!t.d.get_io$$cpu$$request$$ready()&&
                    t.d.cache$postedIntent&&!t.d.cache$candidateValid$NEXT&&!t.d.get_io$$storePfObs$$allocated(),
                    "real exhausted fallback offer did not cancel candidate before admission");
            }};
        t.tick();check(overlap==1&&t.cpuAccepted==before&&!fallback,"fallback crossed pre-edge candidateBusy");
        t.drainCpu();t.d.set_io$$prefetchPmpCfg(0x18);t.d.set_io$$prefetchPrivilege(1);
        t.until([&]{return !t.d.get_io$$adoption$$postedBusy();},"candidate/fallback drain deadlock");
        check(overlap==1&&fallback==1&&accepted==4&&released==4&&!pfAllocated&&t.cpuAccepted==before+1,
            "fallback did not accept once after candidate cancelled");
        t.flush();check(t.cpuAccepted==t.cpuReturned&&t.grants.empty()&&!t.releasePending,
            "fallback final responses or coherence owners did not drain");
        if(!images.empty()){
            std::filesystem::create_directories(images);std::ofstream a(images+"/exhausted_fallback-actual.bin",std::ios::binary),x(images+"/exhausted_fallback-expected.bin",std::ios::binary);
            for(uint64_t o=0;o<BOARD_DDR_BYTES;o+=8)for(unsigned b=0;b<8;++b){a.put(char(t.ddr.memory.at(o)>>(8*b)));x.put(char(t.architectural.at(base+o)>>(8*b)));}
            check(bool(a)&&bool(x),"fallback image write failed");}
        std::cout<<"READ_PREFETCH_STORE_HOLD_FALLBACK_PASS generation_bits=2 authored_posted_allocations="<<accepted
            <<" authored_posted_releases="<<released<<" candidate_overlap="<<overlap<<" fallback="<<fallback
            <<" pf_allocations="<<pfAllocated<<" cpu_accepted="<<t.cpuAccepted<<" cpu_returned="<<t.cpuReturned
            <<" final_image_bytes="<<BOARD_DDR_BYTES<<" internal_state_pokes=0 executing_cpu=0\n";return 0;
    }catch(const std::exception&e){std::cerr<<"READ_PREFETCH_STORE_HOLD_FALLBACK_FAIL "<<e.what()<<'\n';return 1;}
}
