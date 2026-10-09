#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "drain.hpp"
#include <array>

constexpr uint64_t codeBase=0x80200000ULL, dataBase=0x80220000ULL;
constexpr uint64_t signature=0x80240000ULL, seed=0x6ac135ef892047bdULL;
constexpr uint64_t streamBegin=0x8020009cULL, streamEnd=0x802000b0ULL;
constexpr uint64_t donePc=0x8020017cULL, failPc=0x80200184ULL, mretPc=0x80200244ULL;
struct Observed {
    Test* test=nullptr;
    bool terminal=false, poisonTrap=false;
    unsigned traps=0, returns=0;
    std::array<uint64_t,2> trapPcs{};
    uint64_t storesPf=0, usefulPf=0, irqWhilePfLive=0, pendingCycles=0;
    static void sample(SBoardSocGsim& d,void* raw){
        auto& s=*static_cast<Observed*>(raw);
        check(!d.board$platform$dma$busy,"unexpected DMA in timer-only fixture");
        const auto origins=d.get_dataPrefetchOriginEvents();
        s.storesPf+=(origins>>3)&1;s.usefulPf+=(origins>>5)&1;
        const bool pending=d.board$platform$timer$io_irq_REG &&
            d.board$platform$core$core$core$backend$systemUnit$machineTimerReady;
        s.pendingCycles+=pending;
        s.irqWhilePfLive+=pending&&bool(d.get_dataPrefetchEvents()&0x7f0);
        if(d.get_io$$trap$$valid()){
            const uint64_t want=0x8000000000000007ULL^(s.poisonTrap?1:0);
            check(s.traps<2&&d.get_io$$trap$$bits$$cause()==want,"independent timer cause/order mismatch");
            const auto pc=d.get_io$$trap$$bits$$pc();
            check(pc>=streamBegin&&pc<=streamEnd&&!(pc&3),"timer interrupted PC outside streaming loop");
            check(d.get_io$$trap$$bits$$tval()==0,"timer interrupt tval must be zero");
            s.trapPcs[s.traps++]=pc;
        }
        for(unsigned lane=0;lane<2;lane++){
            const bool v=lane?d.get_io$$commit1():d.get_io$$commit0();
            const uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
            if(!v)continue;
            check(pc!=failPc,"timer guest independent check failed");
            s.returns+=pc==mretPc;
            s.terminal|=pc==donePc;
        }
    }
};
static uint64_t wordAtPa(const DdrModel& m,uint64_t pa){
    const auto it=m.memory.find(uint32_t(pa-0x80200000ULL));
    check(it!=m.memory.end(),"missing final timer backing word");return it->second;
}
static void oracle(const DdrModel& m,const Observed& o,bool poison){
    for(uint64_t n=0;n<8192;n++){
        auto actual=wordAtPa(m,dataBase+8*n);
        if(poison&&n==713)actual^=1;
        check(actual==(seed^n),"independent timer full64KiB data mismatch");
    }
    check(wordAtPa(m,signature)==0x54494d455250464fULL&&wordAtPa(m,signature+8)==2,"timer final signature/count mismatch");
    for(unsigned i=0;i<2;i++)check(wordAtPa(m,signature+16+8*i)==o.trapPcs[i],"independent timer mepc restore mismatch");
    check(wordAtPa(m,signature+32)==0&&!(wordAtPa(m,signature+40)&8),"timer IRQ enable restoration mismatch");
}
int main(int argc,char** argv){try{
    check(argc==2||argc==3,"usage: timer image.bin [--inject-trap|--inject-data|--inject-drain]");
    const std::string flag=argc==3?argv[2]:"";
    check(flag.empty()||flag=="--inject-trap"||flag=="--inject-data"||flag=="--inject-drain","unknown timer flag");
    auto image=readFile(argv[1]);check(!image.empty()&&image.size()<65536,"timer guest image bounds");
    Bytes rom;word(rom,0x00200297);word(rom,0x000280e7);word(rom,0x0000006f);
    Test t(rom);
    for(size_t i=0;i<image.size();i+=8){uint64_t v=0;for(unsigned b=0;b<8&&i+b<image.size();b++)v|=uint64_t(image[i+b])<<(8*b);t.ddr.memory[uint32_t(i)]=v;}
    t.running=false;Observed o;o.test=&t;o.poisonTrap=flag=="--inject-trap";t.observer=Observed::sample;t.observerContext=&o;
    bool drained=false;unsigned quiet=0;pfdrain::Snapshot drain;const uint64_t deadline=t.cycles+400000;
    while(t.cycles<deadline){t.tick();if(o.terminal){drain=pfdrain::read(*t.dut,t.ddr);if(flag=="--inject-drain")drain.value[5]|=1;quiet=drain.empty()?quiet+1:0;if(quiet>=2){drained=true;break;}}}
    if(o.terminal){std::cout<<"TIMER_TERMINAL_DRAIN quiet="<<quiet;drain.print(std::cout);std::cout<<"\n";}
    check(drained,"timer bounded terminal CPU/cache/fabric drain");
    check(o.traps==2&&o.returns==2&&o.pendingCycles>0,"timer actual trap/return coverage");
    check(t.dut->board$platform$core$core$core$backend$systemUnit$privilege==3,"timer final privilege mismatch");
    if(STORE_PF_ON)check(o.storesPf>0&&o.usefulPf>0&&o.irqWhilePfLive>0,"timer/PF live overlap coverage");
    else check(o.storesPf==0&&o.usefulPf==0,"disabled store PF admitted traffic");
    oracle(t.ddr,o,flag=="--inject-data");
    bool caught=false;try{oracle(t.ddr,o,true);}catch(const std::runtime_error&){caught=true;}
    check(caught,"timer offline data poison escaped");
    std::cout<<"PASS_TIMER_STREAM_IRQ cycles="<<t.cycles<<" traps="<<o.traps<<" mret="<<o.returns
      <<" irq_pending_cycles="<<o.pendingCycles<<" irq_pending_pf_live="<<o.irqWhilePfLive
      <<" store_pf_alloc="<<o.storesPf<<" store_pf_useful="<<o.usefulPf<<" words=8192 terminal_drain=18\n";
    return 0;
}catch(const std::exception& e){std::cerr<<"Timer CPU mismatch: "<<e.what()<<"\n";return 1;}}
