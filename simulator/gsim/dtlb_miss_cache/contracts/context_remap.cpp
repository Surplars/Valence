#define main unused_board_boot_main
#include "board_boot.cpp"
#undef main
#include "context_symbols.h"
#include <map>
#include <array>

// Independent PA/value and physical transaction scoreboard. No DUT writes.
static constexpr uint64_t A=0x80400000, B=0x80480000, C=0x80500000;
static constexpr uint64_t AV=0x1111222233334444ULL, BV=0x5555666677778888ULL,
    CV=0x123456789abcdef0ULL, SIG=0x56414c454e43454fULL;
struct ContextObserver {
    Test *test=nullptr;
    struct Reply { uint64_t value; bool write; };
    std::map<uint64_t,uint64_t> expected;
    std::map<unsigned,Reply> replies;
    std::array<unsigned,3> targetHits{};
    unsigned priorState=0, probeRetired=0, writes=0, walked=0;
    uint64_t done=0, checkedReplies=0;
    bool sfenced=false, switched=false;
    std::string injection;
    static void sample(SBoardSocGsim &d,void *p) { static_cast<ContextObserver*>(p)->sample(d); }
    void sample(SBoardSocGsim &d) {
        check(!d.get_io$$trap$$valid(),"unexpected native CPU trap in context fixture");
        const unsigned state=d.board$platform$physicalData_walkers_1$state;
        if(state==1 && priorState!=1)++walked;
        if(priorState==3 && state==2 &&
           d.board$platform$physicalData_walkers_1$saved$$virtualAddress==0x40000000) {
            check(!d.board$platform$physicalData_walkers_1$savedResponse$$pageFault &&
                  !d.board$platform$physicalData_walkers_1$savedResponse$$accessFault,"L2 success carries fault");
            const auto pa=d.board$platform$physicalData_walkers_1$savedResponse$$physicalAddress;
            const auto root=d.board$platform$physicalData_walkers_1$saved$$rootPpn;
            const auto asid=d.board$platform$physicalData_walkers_1$saved$$asid;
            if(root==0x80300 && asid==0 && pa==A)++targetHits[0];
            else if(root==0x80300 && asid==0 && pa==B)++targetHits[1];
            else if(root==0x80310 && asid==1 && pa==C)++targetHits[2];
            else check(false,"L2 target response root/ASID/PA mismatch");
        }
        priorState=state;
        const auto raw=d.get_dataPathEvents();
        if(raw&(1ULL<<19)) {
            const uint64_t pa=d.get_dataPathRequest9Address(), meta=d.get_dataPathRequest9Meta();
            const bool write=meta&1;
            check(!(meta&2) && !(pa&7) && ((meta>>7)&3)==3 && ((meta>>9)&255)==255,
                "unexpected physical access geometry");
            check(expected.contains(pa),"unseeded CPU data access");
            if(write) {
                const auto value=d.get_dataPathRequest9Data();
                check((pa==0x80303000 && value==0x201200cf && !sfenced) ||
                      (pa==0x80600000 && value==SIG && switched),"unexpected CPU data side effect");
                expected[pa]=value;++writes;
            } else {
                check(!(sfenced && pa==A),"stale A data request after SFENCE");
                check(!(switched && pa==B),"stale B data request after SATP context switch");
            }
            const unsigned handle=d.get_cpuTagged$$physical$$handle();
            check(replies.emplace(handle,Reply{expected.at(pa),write}).second,"duplicate physical handle");
        }
        if(raw&(1ULL<<21)) {
            const unsigned handle=d.get_cpuTagged$$physicalReply$$handle();
            check(replies.contains(handle),"physical reply has no accepted owner");
            const auto reply=replies.at(handle);replies.erase(handle);
            check(d.get_dataPathReply0Flags()==0,"physical response fault");
            if(!reply.write)check(d.get_dataPathReply0Data()==(reply.value^(injection=="--inject-data"?1ULL:0ULL)),
                "physical response does not match independent PA data");
            ++checkedReplies;
        }
        for(unsigned lane=0;lane<2;++lane) {
            const bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
            if(!valid)continue;
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            check(pc!=CTX_FAIL,"guest rejected context remap data or trapped");
            if(pc==CTX_PROBE_A||pc==CTX_PROBE_B||pc==CTX_PROBE_C) {
                const uint64_t order[]={CTX_PROBE_A,CTX_PROBE_B,CTX_PROBE_C};
                check(probeRetired<3 && order[probeRetired]==pc,"context target probes retired out of sequence");
                ++probeRetired;
            }
            if(pc==CTX_SFENCE){check(!sfenced&&!switched,"duplicate SFENCE");sfenced=true;}
            if(pc==CTX_SATP){check(sfenced&&!switched,"invalid SATP test sequence");switched=true;}
            if(pc==CTX_DONE && !done)done=test->cycles;
        }
    }
};
int main(int argc,char **argv) { try {
    check(argc==2||argc==3,"context_remap.bin [--inject-data|--inject-coverage|--inject-stale]");
    ContextObserver o;if(argc==3)o.injection=argv[2];
    const auto code=readFile(argv[1]);
    Bytes rom;word(rom,0x00200297);word(rom,0x00028067);
    Test t(rom);t.running=false;o.test=&t;
    auto seed=[&](uint64_t pa,uint64_t v){t.ddr.memory[uint32_t(pa-ramBase)]=v;o.expected[pa]=v;};
    for(size_t off=0;off<code.size();off+=8){uint64_t v=0;for(unsigned b=0;b<8&&off+b<code.size();++b)v|=uint64_t(code[off+b])<<(8*b);seed(ramBase+off,v);}
    auto branch=[](uint64_t pa){return ((pa>>12)<<10)|1ULL;};
    auto leaf=[](uint64_t pa){return ((pa>>12)<<10)|0xcfULL;};
    for(auto root:{0x80300000ULL,0x80310000ULL}) {
        for(unsigned page=0;page<4;++page)for(unsigned word=0;word<512;++word)seed(root+page*4096+word*8,0);
        seed(root+8,branch(root+0x2000));seed(root+0x2000,branch(root+0x3000));
        for(unsigned page=0;page<32;++page)seed(root+0x3000+page*8,leaf(root==0x80310000&&page==0?C:A+page*4096));
    }
    for(unsigned page=0;page<32;++page)for(unsigned w=0;w<8;++w)seed(A+page*4096+w*8,w?0:page?0x90000000ULL+page:AV);
    for(unsigned w=0;w<8;++w){seed(B+w*8,w?0:BV);seed(C+w*8,w?0:CV);}
    seed(0x80600000,0);
    t.observer=ContextObserver::sample;t.observerContext=&o;
    while(!o.done && t.cycles<1000000)t.tick();
    check(o.done&&o.probeRetired==3&&o.sfenced&&o.switched,"native context fixture timed out or incomplete");
    t.idle(128);
    check(o.replies.empty()&&t.ddr.pendingReads.empty()&&t.ddr.pendingWrites.empty()&&t.ddr.pendingB.empty(),"owners not drained");
    check(o.writes==2&&t.ddr.memory.at(0x80600000-ramBase)==SIG,"final signature/write count");
    check(t.ddr.memory.at(0x80303000-ramBase)==0x201200cf,"guest PTE mutation missing");
    check(t.ddr.memory.at(B-ramBase)==(o.injection=="--inject-stale"?AV:BV),"independent new-PA sentinel oracle");
    std::cout<<"NATIVE_CONTEXT_DATA_PASS cycles="<<t.cycles<<" probes="<<o.probeRetired<<" writes="<<o.writes<<" walks="<<o.walked<<" checked_replies="<<o.checkedReplies<<" sfence=1 satp_root_asid=1\n";
    if(o.injection=="--inject-coverage")o.targetHits[1]=0;
    for(auto n:o.targetHits)check(n>0,"missing actual target L2 hit coverage");
    check(o.walked>0&&o.checkedReplies>0,"missing actual translation/data traffic");
    t.fabric.finish();
    std::cout<<"NATIVE_L2_CONTEXT_PASS cycles="<<t.cycles<<" target_l2_hits="<<o.targetHits[0]<<","<<o.targetHits[1]<<","<<o.targetHits[2]<<" walks="<<o.walked<<" checked_replies="<<o.checkedReplies<<" sfence=1 satp_root_asid=1 permission_atomic=NOT_COVERED\n";
    return 0;
} catch(const std::exception &e){std::cerr<<"FAIL: "<<e.what()<<"\n";return 1;} }
