#define FIVE_STAGE_SOC_MEMORY_ONLY
#include "five_stage_soc.cpp"
#include "five_stage_rom_host.h"
#include "five_stage_coherent_readback.h"

int main(int argc,char **argv) { try {
    need(argc>=2,"C/A SoC binary required");
    std::ifstream f(argv[1],std::ios::binary); need(bool(f),"missing C/A SoC binary");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(f)),{});
    bool compressed=argc>2&&std::string(argv[2])=="--compressed-boundary";
    bool mutate=argc>2&&std::string(argv[2])=="--wrong-result";
    SFiveStageSoc d; AxiMemory m(d,image,false);
    m.bytes[0xf000]=compressed;
    uint16_t prefix=compressed?1:0x0013;
    m.bytes[0x4ffe]=prefix; m.bytes[0x4fff]=prefix>>8;
    d.set_reset(1); d.set_io$$uartRx(1); d.set_io$$externalIrq(0);
    d.set_io$$clockLocked(1); d.set_io$$ddrReady(1); d.set_io$$jtagLinkUp(0);
    d.set_io$$jtagDmi$$request$$valid(0); d.set_io$$jtagDmi$$response$$ready(0);
    i1CoherentHostIdle(d);
    i1InitializeRom(d,m,"src/main/resources/inorder/bootrom.hex");
    m.inputs(0); d.step(); d.step(); d.set_reset(0);
    uint64_t lastA0=0,retired=0,cRetired=0,traps=0,lastPc=0,atBoundary=0;
    for(uint64_t cycle=0;cycle<1500000;++cycle) {
        m.inputs(cycle); d.step(); m.outputs(cycle);
        if(d.get_io$$trapTaken()) {
            ++traps;
            if(traps<16) std::cerr<<"CA_TRAP cause=0x"<<std::hex<<d.get_io$$trapCause()
                <<" previous_pc=0x"<<lastPc<<std::dec<<'\n';
        }
        if(!d.get_io$$retire$$valid()) continue;
        ++retired; auto pc=d.get_io$$retire$$bits$$pc(); lastPc=pc;
        auto ins=d.get_io$$retire$$bits$$instruction(); unsigned length=(ins&3)==3?4:2;
        if(pc>=0x10000 && pc<0x11000) {
            need(!d.get_io$$retire$$bits$$trap(),"C/A BootROM fault"); continue;
        }
        if(d.get_io$$retire$$bits$$writesRd()&&d.get_io$$retire$$bits$$rd()==10)
            lastA0=d.get_io$$retire$$bits$$data();
        if(d.get_io$$retire$$bits$$trap()&&d.get_io$$retire$$bits$$cause()==3) {
            need(lastA0==0,"C/A actual CPU guest failed");
#ifdef I1_COHERENT_READBACK
            uint64_t drainCycle = cycle + 1;
            for (unsigned i = 0; i < 320; i += 64) coherentRead(d, m, drainCycle, 0x30000 + i);
#endif
            for(unsigned c:{2U,4U,5U,6U,7U}) need(m.load(0x30000+c*8)==(c==2?2:1),
                "independent C/A precise fault ledger oracle");
            need(m.load(0x30100)==42 && m.load(0x30108)==0x40001000 &&
                m.load(0x30110)==(mutate?0ULL:0x434150415353ULL),"independent C/A completion/alias/boundary oracle");
            need(atBoundary==(compressed?1U:0U),"page-end compressed instruction did not retire precisely");
            need(cRetired>50,"compressed instruction coverage missing");
            std::cout<<"FIVE_STAGE_CA_SOC_PASS cycles="<<cycle<<" retired="<<retired
                <<" compressed="<<cRetired<<" traps="<<traps<<" boundary16="<<compressed
                <<" C_mixed_halfword_page_partial_fault_A_W_D_amo_alias_aq_rl_fence=PASS\n";
            return 0;
        }
        if(d.get_io$$retire$$bits$$trap()) continue;
        if(pc==0x40000ffe) { need(compressed && ins==1,"wrong page-end C opcode"); ++atBoundary; }
        else {
            need(pc>=0x80200000 && pc+length<=0x80200000+image.size(),"C/A CPU retired outside text");
            uint32_t expected=0;
            for(unsigned j=0;j<length;++j) expected|=uint32_t(m.bytes[pc-0x80200000+j])<<(8*j);
            need(ins==expected,"independent compressed retired byte oracle");
        }
        cRetired+=length==2;
    }
    std::cerr<<"CA_SOC_STALL last_pc="<<std::hex<<lastPc<<std::dec<<" retired="<<retired<<" traps="<<traps<<"\n";
    throw std::runtime_error("C/A SoC bounded completion failed");
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
