// Same production board and fixed AXI backing; no altered DUT timing or memory responses.
#include "worksets_symbols.h"
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "abi.hpp"
#include "copy_model_adapter.hpp"
#include "roi.hpp"
#include "drain.hpp"
#include "passive.hpp"
#include "canonical_model_adapter.hpp"
#include "cache_window_adapter.hpp"
#include "admission_getters.hpp"
#include "admission_model_adapter.hpp"
#include "dmmu_observer.hpp"
#include "unissued_model_adapter.hpp"
#include "window_observer.hpp"
#include "proof_observer.hpp"
#include "ready_frontier.hpp"
#include "lru_victim_observer.hpp"
#include <type_traits>
static_assert(std::extent_v<decltype(SBoardSocGsim::board$platform$physicalData_walkers_0$tlb$$valid)> ==8);
static_assert(std::extent_v<decltype(SBoardSocGsim::board$platform$physicalData_walkers_1$tlb$$valid)> ==16);
static_assert(std::extent_v<decltype(SBoardSocGsim::board$platform$physicalData_adapters_0$cache$$valid)> ==4);
static_assert(std::extent_v<decltype(SBoardSocGsim::board$platform$physicalData_adapters_1$cache$$valid)> ==4);
static uint64_t expectedWord(uint64_t);
static void buffers(const DdrModel& d,unsigned op,unsigned poison=0){
    for(uint64_t n=0;n<16384;n++){
        const uint64_t a=d.memory.at(uint32_t(MMU_SMOKE_DATA_A+n*8-ramBase));
        uint64_t b=d.memory.at(uint32_t(MMU_SMOKE_DATA_B+n*8-ramBase));
        if(poison&&n==12031)b^=1;
        check(a==expectedWord(n)&&b==(op==2?expectedWord(n):~expectedWord(n)),"independent per-case full128KiB data oracle");
    }
}
struct Observed {
    Test* test=nullptr;
    bandwidth::Passive passive;
    canonical_overlap::Observer canonical;
    admission::Observer admission;
    dmmu::Observer dmmu;
    unissued::Observer unissued;
    robwindow::Observer window;
    memory_frontier::Observer proof;
    frontier::Observer readiness;
    lru_victim::Observer lru;
    unsigned traps=0,cases=0,first=18,last=24;bool terminal=false,poisonTrap=false;
    pfroi::Observer pf{bool(STORE_PF_ON),19};
    pfcopy::Observer copy{MMU_SMOKE_DATA_A,MMU_SMOKE_DATA_B,131072};
    static void sample(SBoardSocGsim& d,void* cookie){
        auto& s=*static_cast<Observed*>(cookie);
        check(!d.board$platform$dma$busy,"unexpected DMA during store-PF replay");
        if(d.get_io$$trap$$valid()){
            uint64_t want=s.traps<3?(s.traps==0?13:s.traps==1?15:1):9;
            if(s.poisonTrap&&!s.traps)want=15;
            check(s.traps<3+s.last-s.first&&d.get_io$$trap$$bits$$cause()==want,"independent worksets trap order mismatch");++s.traps;
        }
        pfroi::Sample sample;sample.cycle=s.test->cycles;sample.reset=d.get_backendReset();
        sample.commits=unsigned(d.get_io$$commit0())|(unsigned(d.get_io$$commit1())<<1);
        sample.pc[0]=d.get_io$$commit0Pc();sample.pc[1]=d.get_io$$commit1Pc();sample.head=d.get_backendHeadIndex();
        sample.satp=d.board$platform$core$core$core$backend$systemUnit$satp;
        sample.privilege=d.board$platform$core$core$core$backend$systemUnit$privilege;
        sample.origin=d.get_dataPrefetchOriginEvents();sample.events=d.get_dataPrefetchEvents();
        // Input handshakes use the unchanged DDR driver values just driven before step(); generated ABI exposes getters only for DUT outputs.
        const bool ar=d.get_io$$ddrAxi$$ar$$valid()&&s.test->ddr.arReady;
        const bool aw=d.get_io$$ddrAxi$$aw$$valid()&&s.test->ddr.awReady;
        sample.axi={uint64_t(ar),ar?uint64_t(d.get_io$$ddrAxi$$ar$$bits$$len())+1:0,
            uint64_t(s.test->ddr.rValid&&d.get_io$$ddrAxi$$r$$ready()),uint64_t(aw),
            aw?uint64_t(d.get_io$$ddrAxi$$aw$$bits$$len())+1:0,
            uint64_t(d.get_io$$ddrAxi$$w$$valid()&&s.test->ddr.wReady),
            uint64_t(s.test->ddr.bValid&&d.get_io$$ddrAxi$$b$$ready())};
        if(s.pf.sample(sample)){
            check(s.cases<1,"too many accepted cases");buffers(s.test->ddr,s.first<18?0:s.first==18?1:2);
            bool caught=false;try{buffers(s.test->ddr,s.first<18?0:s.first==18?1:2,1);}catch(const std::runtime_error&){caught=true;}
            check(caught,"per-case buffer poison escaped");++s.cases;
            std::cout<<"WORKSET_PROGRESS cases="<<s.cases<<" index="<<(s.first+s.cases-1)
                     <<" cycles="<<s.test->cycles<<" accepted_marker=1 independent_words=32768 per_case_poison_rejected=1"<<std::endl;
        }
        s.passive.sample(d,s.test->ddr,sample.cycle,s.pf.phase);
        auto canonicalSample=canonical_overlap::read(d);canonical_overlap::attachCache(canonicalSample,d);
        s.canonical.sample(canonicalSample,sample.cycle,s.pf.phase==1);
        bool activeOffer=s.pf.phase==1;
        for(unsigned lane=0;lane<2;lane++)if((sample.commits>>lane)&1){
            if(sample.pc[lane]==(s.first<18?pfroi::readBeginPc:pfroi::beginPc[s.first%2]))activeOffer=true;
            if(sample.pc[lane]==(s.first<18?pfroi::readEndPc:pfroi::endPc))activeOffer=false;
        }
        auto unissuedSample=unissued::read(d,canonicalSample);
        s.unissued.sample(unissuedSample,canonicalSample,sample.cycle,activeOffer);
        s.window.sample(robwindow::read(d),unissuedSample,canonicalSample,sample.cycle,activeOffer);
        s.proof.sample(d,s.test->ddr,sample.cycle,activeOffer);
        s.readiness.sample(d,unissuedSample,canonicalSample,sample.cycle,activeOffer);
        const auto admissionSample=admission::read(d);
        s.admission.sample(admissionSample,sample.cycle,activeOffer);
        s.lru.sample(d,s.test->ddr,admissionSample,sample.cycle,activeOffer);
        s.dmmu.sample(dmmu::read(d),sample.cycle,activeOffer);
        s.copy.sample(d,sample.cycle,activeOffer&&(s.first==19||s.first==21));
        s.terminal=s.pf.terminal;
    }
};
static uint64_t expectedWord(uint64_t n){return 0x729ad0513fe68bc4ULL^(0x0102040810204081ULL*n);}
static void oracle(const DdrModel& d,unsigned first,unsigned last,unsigned poison){
    auto at=[&](uint64_t pa){return d.memory.at(uint32_t(pa-ramBase));};
    check(at(MMU_SMOKE_SIGNATURE)==0x4d4d55574f524b53ULL&&at(MMU_SMOKE_SIGNATURE+8)==0&&
          at(MMU_SMOKE_SIGNATURE+16)==last-first&&at(MMU_SMOKE_SIGNATURE+48)==first&&at(MMU_SMOKE_SIGNATURE+56)==last,"worksets final complete signature");
    for(unsigned c=first;c<last;c++){
        unsigned mode=c<18?c/6:(c-18)/2,test=c<18?c%6:1,op=c<18?0:1+(c-18)%2;
        uint64_t pages=test<2?0:4ULL<<(test-2),count=pages?pages:test?16384:1024,passes=pages?128:test?1:8;
        uint64_t r[8];for(unsigned k=0;k<8;k++)r[k]=at(MMU_SMOKE_ENTRY+0x65000+c*64+k*8);
        if(poison==2&&c==first)r[3]^=1;
        check(r[0]==mode&&r[1]==test&&r[2]==op&&r[3]==count&&r[4]==passes&&r[5]>0,"independent workset coverage/count oracle");
        uint64_t sum=0;for(uint64_t n=0;n<count;n++)sum+=expectedWord(pages?n*520:n);
        if(poison==3&&c==first)r[7]^=1;
        check(r[7]==(op?0:sum*passes)&&(!op?r[6]==0:r[6]>0),"independent workset result/flush oracle");
    }
    const unsigned finalOp=last<=18?0:1+(last-19)%2;
    for(uint64_t n=0;n<16384;n++){
        uint64_t a=at(MMU_SMOKE_DATA_A+n*8),b=at(MMU_SMOKE_DATA_B+n*8);
        if(poison==1&&n==12031)b^=1;
        check(a==expectedWord(n)&&b==(finalOp==2?expectedWord(n):~expectedWord(n)),"independent full128KiB data oracle");
    }
}
int main(int argc,char** argv){try{
    check(argc==4||argc==5,"usage: worksets image.bin begin end [--inject-trap]");bool poison=argc==5&&std::string(argv[4])=="--inject-trap";
    size_t usedFirst=0,usedLast=0;
    auto rawFirst=std::stoull(argv[2],&usedFirst),rawLast=std::stoull(argv[3],&usedLast);
    check(usedFirst==std::string(argv[2]).size()&&usedLast==std::string(argv[3]).size()&&rawFirst<rawLast&&rawLast<=24,"worksets range input");
    unsigned first=unsigned(rawFirst),last=unsigned(rawLast);
    check((first==0||first==6||first==18||first==19||first==21)&&last==first+1,"canonical-overlap replay requires exact case0/6/18/19/21");
    check(argc==4||poison,"unknown option");auto payload=readFile(argv[1]);check(!payload.empty()&&payload.size()<32768,"worksets guest size");
    Bytes rom;word(rom,uint32_t(MMU_SMOKE_ENTRY&0xfffff000ULL)|0x2b7);word(rom,0x02029293);word(rom,0x0202d293);word(rom,0x000280e7);word(rom,0x0000006f);
    Test t(rom);t.running=false;Observed s;s.passive.openTrace();s.test=&t;s.poisonTrap=poison;s.first=first;s.last=last;s.pf=pfroi::Observer(bool(STORE_PF_ON),first);t.observer=Observed::sample;t.observerContext=&s;
    for(size_t off=0;off<payload.size();off+=8){uint64_t v=0;for(unsigned lane=0;lane<8&&off+lane<payload.size();lane++)v|=uint64_t(payload[off+lane])<<(lane*8);t.ddr.memory[uint32_t(MMU_SMOKE_ENTRY-ramBase+off)]=v;}
    t.ddr.memory[uint32_t(MMU_SMOKE_ENTRY+0x64000-ramBase)]=first;
    t.ddr.memory[uint32_t(MMU_SMOKE_ENTRY+0x64008-ramBase)]=last;
    bool done=false;unsigned quiet=0;pfdrain::Snapshot drain;
    while(t.cycles<24000000){t.tick();if(s.terminal){drain=pfdrain::read(*t.dut,t.ddr);quiet=(drain.empty()&&!bandwidth::ownerSample(*t.dut).live&&t.dut->get_mpReserved()==0&&t.dut->get_mpAllowed()==0&&!t.dut->get_mpQueryValid()&&!t.dut->get_mpResultValid()&&!t.dut->get_mpFrontierValid())?quiet+1:0;if(quiet>=2){done=true;break;}}}
    if(s.terminal){std::cout<<"STORE_PF_TERMINAL_DRAIN accepted_terminal=1 consecutive_quiet="<<quiet;drain.print(std::cout);std::cout<<"\n";}
    check(done,"worksets bounded completion");
    std::cout<<"WORKSETS_SIGNATURE error="<<t.ddr.memory.at(uint32_t(MMU_SMOKE_SIGNATURE+8-ramBase))
             <<" cases="<<t.ddr.memory.at(uint32_t(MMU_SMOKE_SIGNATURE+16-ramBase))
             <<" cause="<<t.ddr.memory.at(uint32_t(MMU_SMOKE_SIGNATURE+24-ramBase))<<std::endl;
    check(s.traps==3+last-first&&s.cases==last-first,"worksets retirement/trap coverage");oracle(t.ddr,first,last,0);
    for(unsigned p=1;p<=3;p++){bool caught=false;try{oracle(t.ddr,first,last,p);}catch(const std::runtime_error&){caught=true;}check(caught,"worksets oracle poison escaped");}
    for(const auto& owner:s.copy.ledger.owners)check(!owner.live,"copy PF allocation owner did not terminally drain");
    s.canonical.finish(std::cout);
    s.unissued.finish(std::cout);
    s.window.finish(std::cout);
    s.proof.finish(std::cout);
    s.readiness.finish(std::cout);
    s.lru.finish(std::cout);
    s.admission.finish(std::cout);
    s.dmmu.finish(std::cout);
    s.pf.finish(std::cout);s.copy.finish(std::cout,first);
    s.passive.finish(std::cout,first,s.pf.regions[first].timed.cycles,s.pf.regions[first].tail.cycles);
    std::cout<<"POSTED_BANDWIDTH_TERMINAL posted_owner_masks=0 passive=1 posted_store_merge="<<POSTED_STORE_ON<<"\n";
    for(unsigned c=first;c<last;c++){std::cout<<"WORKSET_ROW index="<<c;for(unsigned k=0;k<8;k++)std::cout<<" "<<t.ddr.memory.at(uint32_t(MMU_SMOKE_ENTRY+0x65000+c*64+k*8-ramBase));std::cout<<"\n";}
    std::cout<<"FORMAL_BC_REPLAY_PASS pf_and_prepared="<<STORE_PF_ON<<" real_cpu=1 real_S_Bare_Sv39_4K_2M=1 cases=1 guest_changed=0 speedup_required=0 independent_per_case_words=32768\n";
    std::cout<<"BOOTROM_MMU_WORKSETS_PASS cycles="<<t.cycles<<" begin="<<first<<" end="<<last<<" faults=3 S_ecalls="<<(last-first)<<" full_buffers_verified_per_case=1 independent_final_words=32768 independent_row_oracles_per_segment=1 offline_oracle_poison_rejected=3 full54=0 FPGA=0\n";
}catch(const std::exception& e){std::cerr<<"BOOTROM_MMU_WORKSETS_FAIL "<<e.what()<<"\n";return 1;}}
