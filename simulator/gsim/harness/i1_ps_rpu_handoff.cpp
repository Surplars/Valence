#include "I1SpinorManagedSystem.h"
#include <array>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
using Model=SI1SpinorManagedSystem;
static void need(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
#include "i1_axi_memory_reference.h"
static constexpr uint64_t SHARED=0x0fff0000, BASE=0x80000000;
static constexpr uint32_t MAGIC=0x49314254, ABI=0x10000, SEED=0x6d5a56a9, ITERATIONS=64;
static uint32_t goldenKernel() {
    std::array<uint32_t,64> ram{};
    for(unsigned i=0;i<64;++i) {
        unsigned n=i%32;uint32_t rotated=n?(SEED<<n)|(SEED>>(32-n)):SEED;
        ram[i]=(SEED^(i*uint32_t(0x9e3779b9)))+rotated;
    }
    uint32_t hash=2166136261U;
    for(unsigned i=0;i<ITERATIONS;++i) {
        uint32_t value=ram[i%64];value^=value*8192U;value^=value/131072U;value^=value*32U;
        ram[i%64]=value+i+SEED;hash=uint32_t((hash^ram[i%64])*16777619U);
    }
    return hash;
}
static void put32(AxiMemory &m,uint64_t a,uint32_t value){for(unsigned i=0;i<4;++i)m.bytes[a+i]=value>>(i*8);}
int main(int argc,char **argv){try {
    need(argc>=4,"usage: image.bin expected_crc32 breakpoint_pc [--inject-result]");
    std::ifstream f(argv[1],std::ios::binary);need(bool(f),"RV image file unavailable");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(f)),{});
    uint32_t crc=std::stoul(argv[2],nullptr,0);uint64_t breakpoint=std::stoull(argv[3],nullptr,0);
    bool inject=argc>4;
    unsigned cases=0;
    for(unsigned scenario=0;scenario<4;++scenario)for(unsigned latency:{1U,12U}) {
        const std::array<unsigned,3> period=latency==1?std::array<unsigned,3>{12,10,10}:std::array<unsigned,3>{10,6,8};
        Model d;AxiMemory memory(d,image,false,false);memory.readLatency=latency;memory.writeLatency=latency;
        put32(memory,SHARED,MAGIC^(scenario==1));put32(memory,SHARED+4,ABI);
        put32(memory,SHARED+8,image.size());put32(memory,SHARED+12,crc^(scenario==2));
        put32(memory,SHARED+16,SEED);put32(memory,SHARED+20,ITERATIONS);
        put32(memory,SHARED+24,scenario==3);put32(memory,SHARED+64,1);
        d.set_cpuClock(0);d.set_vpuClock(0);d.set_systemClock(0);d.set_commonColdReset(1);
        d.set_io$$memoryReady(1);d.set_io$$uartRx(1);d.set_io$$externalIrq(0);
        d.set_io$$wakeCpu(0);d.set_io$$wakeVpu(0);memory.inputs(0);d.step();
        bool oldCpu=false,oldVpu=false,oldSystem=false,done=false,sawRunning=false;
        uint64_t cpuCycles=0,systemCycles=0,retired=0,terminalAt=0;unsigned traps=0;
        for(uint64_t tick=0;tick<12000000&&!done;++tick) {
            bool cold=tick<80;
            bool cpu=(tick%period[0])>=period[0]/2;
            bool vpu=((tick+2)%period[1])>=period[1]/2;
            bool system=((tick+1)%period[2])>=period[2]/2;
            if(!cold){cpu=cpu&&d.get_io$$cpuClockEnable();vpu=vpu&&d.get_io$$vpuClockEnable();}
            bool ce=cpu&&!oldCpu,ve=vpu&&!oldVpu,se=system&&!oldSystem;
            (void)ve;
            d.set_cpuClock(oldCpu);d.set_vpuClock(oldVpu);d.set_systemClock(oldSystem);
            d.set_commonColdReset(cold);memory.inputs(systemCycles);d.step();
            if(!cold) {
                need(!d.get_io$$protocolError(),"native CPU/VPU protocol error during PS boot payload");
                if(se)memory.outputs(systemCycles);
                if(ce&&d.get_io$$retire$$valid()) {
                    ++retired;
                    if(d.get_io$$retire$$bits$$trap()) {
                        ++traps;need(scenario==3&&d.get_io$$retire$$bits$$cause()==3&&
                            d.get_io$$retire$$bits$$pc()==breakpoint,"independent RV breakpoint trap oracle");
                    }
                }
                uint32_t state=memory.load(SHARED+64);
                sawRunning|=state==2;
                if(state==3||state==0x80000000U) {
                    if(!terminalAt)terminalAt=systemCycles;
                    done=systemCycles>terminalAt+100&&memory.reads.empty()&&!memory.sending&&
                        memory.addresses.empty()&&memory.writeBeats.empty()&&memory.replies.empty();
                }
            }
            d.set_cpuClock(cpu);d.set_vpuClock(vpu);d.set_systemClock(system);d.step();
            oldCpu=cpu;oldVpu=vpu;oldSystem=system;
            if(ce&&!cold)++cpuCycles;if(se&&!cold)++systemCycles;
        }
        need(done,"PS/RPU/RV cold-boot result timed out");
        uint32_t state=memory.load(SHARED+64),error=memory.load(SHARED+68);
        const uint32_t errors[]={0,3,1,4};
        need(state==(scenario?0x80000000U:3U)&&error==errors[scenario],"independent PS-visible boot status/error oracle");
        if(scenario!=1) {
            need(sawRunning&&uint32_t(memory.load(SHARED+72))==crc,"independent PS-visible image CRC oracle");
            need(memory.load(SHARED+80)==0xbeef&&memory.load(SHARED+88)==0x80000000003411adULL,
                "independent RV hart/misa report oracle");
        }
        if(scenario==0) {
            need(uint32_t(memory.load(SHARED+76))==(goldenKernel()^uint32_t(inject)),"independent RPU/RV DDR result oracle");
            need(memory.load(SHARED+96)>0&&memory.load(SHARED+104)>0,"RV performance counters absent from report");
        }
        if(scenario==3)need(traps==1&&memory.load(SHARED+112)==breakpoint&&memory.load(SHARED+120)==3,
            "independent PS-visible precise trap record oracle");
        else need(traps==0,"unexpected RV trap during cold boot");
        std::cout<<"I1_PS_RPU_HANDOFF_PASS scenario="<<scenario<<" latency="<<latency
            <<" cpu_cycles="<<cpuCycles<<" system_cycles="<<systemCycles<<" retired="<<retired
            <<" checksum="<<std::hex<<uint32_t(memory.load(SHARED+76))<<std::dec<<"\n";
        ++cases;
    }
    need(cases==8,"missing cold-boot scenarios");return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
