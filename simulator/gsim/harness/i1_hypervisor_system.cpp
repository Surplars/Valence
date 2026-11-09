#include "I1SpinorManagedSystem.h"
#define FIVE_STAGE_ORACLE_ONLY
#include "five_stage.cpp"
#include <deque>
#include <map>
#include <optional>
#include "i1_spinor_program_reference.h"
using Model=SI1SpinorManagedSystem;
#include "i1_axi_memory_reference.h"
struct HypervisorProgram {
    static constexpr uint64_t GVA=0x40000000ULL, GPA=0x10080000000ULL;
    static constexpr uint64_t VSATP=(8ULL<<60)|((GPA+0x10000)>>12);
    static constexpr uint64_t HGATP=(8ULL<<60)|((BASE+0x4000)>>12);
    static constexpr uint64_t BAD_ROOT=GPA+0x40010000;
    std::vector<uint8_t> image=std::vector<uint8_t>(0x30000);
    std::vector<Expected> expected;
    std::map<uint64_t,unsigned> literals;
    std::map<unsigned,uint32_t> instructions;
    unsigned cursor=0;uint64_t pc=BASE;
    void bytes(unsigned at,uint64_t v,unsigned size){for(unsigned j=0;j<size;++j)image.at(at+j)=v>>(8*j);}
    void location(unsigned at,uint64_t address){cursor=at;pc=address;}
    void emit(uint32_t i,unsigned rd=0,uint64_t value=0,bool fp=false,unsigned flags=0,uint64_t mask=~0ULL){
        auto [it,inserted]=instructions.emplace(cursor,i);
        need(inserted||it->second==i,"independent handler image changed between traps");
        bytes(cursor,i,4);expected.push_back({pc,pc+4,value,mask,0,0,i,rd,flags,rd!=0&&!fp,fp,false});
        cursor+=4;pc+=4;
    }
    void load(unsigned rd,uint64_t value){
        auto [it,inserted]=literals.emplace(value,0x700+8*literals.size());
        if(inserted)bytes(it->second,value,8);
        need(it->second<0x800,"literal pool exceeds independent instruction immediate");
        emit(ri(0x03,rd,3,31,it->second),rd,value);
    }
    void csr(unsigned address,unsigned source){emit(ri(0x73,0,1,source,address));}
    void read(unsigned address,unsigned rd,uint64_t value,uint64_t mask=~0ULL){emit(ri(0x73,rd,2,0,address),rd,value,false,0,mask);}
    void upper(unsigned rd,uint64_t value){emit(uint32_t(value&0xfffff000ULL)|(rd<<7)|0x37,rd,value);}
    void handler(uint64_t cause,uint64_t faultPc,uint64_t tval,uint64_t htval,uint64_t htinst,
                 uint64_t resume,uint64_t extensionStatus){
        unsigned save=cursor;uint64_t savePc=pc;location(0x800,BASE+0x800);
        read(0x142,21,cause);read(0x143,22,tval);read(0x643,23,htval);read(0x64a,24,htinst);
        read(0x600,26,0x180|(cause==10?0:0x40),0x1c0);
        read(0x141,27,faultPc);emit(ri(0x13,27,0,27,4),27,resume);csr(0x141,27);
        read(0x140,28,0x1122334455667788ULL);
        read(0x200,28,extensionStatus,0x6600);
        load(28,VSATP);csr(0x280,28);emit(0x10200073);expected.back().next=resume;
        location(save,savePc);
    }
    void trap(uint32_t i,uint64_t cause,uint64_t tval,uint64_t htval=0,uint64_t htinst=0,
              bool fetch=false,uint64_t extensionStatus=0x6600){
        uint64_t at=pc;
        if(!fetch)bytes(cursor,i,4);
        expected.push_back({pc,BASE+0x800,0,~0ULL,cause,tval,fetch?0u:i,0,0,false,false,true});
        cursor+=4;pc+=4;handler(cause,at,tval,htval,htinst,pc,extensionStatus);
    }
    explicit HypervisorProgram(unsigned variant){
        // Sv39x4 root index 1026 exercises both extra GPA bits. PTEs and
        // expectations come from software constants, never from DUT decode.
        bytes(0x4000+1026*8,((BASE>>12)<<10)|0xdf,8);
        bytes(0x4000,0xd7,8); // GPA low GiB -> physical low GiB for CMU MMIO.
        bytes(0x10000+8,(((GPA+0x11000)>>12)<<10)|1,8);
        bytes(0x11000,(((GPA+0x12000)>>12)<<10)|1,8);
        bytes(0x12000,(((GPA+0x20000)>>12)<<10)|0xcf,8);
        bytes(0x12000+3*8,(((GPA+0x23000)>>12)<<10)|0xc7,8);
        const uint64_t badGpa=variant==6?(1ULL<<45)+0x23000:GPA+0x40023000;
        bytes(0x12000+5*8,((badGpa>>12)<<10)|0xc7,8);
        bytes(0x12000+6*8,((0x10080000ULL>>12)<<10)|0xc7,8);
        bytes(0x23000,0x0000000200000001ULL,8);bytes(0x23008,0x0000000400000003ULL,8);
        bytes(0x23040,0x3f800000,4);
        bytes(0x23050,0x3380000033800000ULL,8);bytes(0x23058,0x3380000033800000ULL,8);
        emit(0x00000f97,31,BASE);
        load(1,BASE+0x400);csr(0x305,1);load(1,BASE+0x800);csr(0x105,1);
        load(1,HGATP);csr(0x680,1);load(1,VSATP);csr(0x280,1);
        load(1,0xf0b7ff);csr(0x302,1);load(1,7);csr(0x306,1);csr(0x606,1);csr(0x106,1);
        load(1,0x2200);csr(0x200,1);load(1,0x1122334455667788ULL);csr(0x140,1);
        load(1,0xaabbccddeeff0011ULL);csr(0x240,1);
        load(1,0x2a00);csr(0x300,1); // MPP=S, host FS/VS Initial.
        load(1,BASE+0x1000);csr(0x341,1);emit(0x30200073);expected.back().next=BASE+0x1000;
        location(0x1000,BASE+0x1000);load(1,0x100);csr(0x600,1);
        upper(7,GVA+0x3000);
        emit(0x60004073u|(2u<<26)|(1u<<20)|(7u<<15)|(10u<<7),10,1); // HLV.WU
        emit(ri(0x13,11,0,0,42),11,42);
        emit(0x62004073u|(2u<<26)|(11u<<20)|(7u<<15)); // HSV.W
        emit(0x60004073u|(2u<<26)|(1u<<20)|(7u<<15)|(10u<<7),10,42);
        upper(6,GVA);
        emit(0x60004073u|(2u<<26)|(3u<<20)|(6u<<15)|(10u<<7),10,0x01100a13); // HLVX.WU
        emit(0x22000073);emit(0x62000073); // HFENCE.VVMA/GVMA globally order the two small TLBs.
        if(variant==4){load(1,(8ULL<<60)|(BAD_ROOT>>12));csr(0x280,1);}
        load(1,0x180);csr(0x600,1);load(1,0x2300);csr(0x100,1);csr(0x141,6);
        emit(0x10200073);expected.back().next=GVA;
        location(0x20000,GVA);
        if(variant==4){bytes(cursor,0x01100a13,4);trap(0,20,GVA,(BAD_ROOT+8)>>2,0x3000,true,0x2200);}
        else emit(0x01100a13,20,17);
        // First instruction was skipped by the directed fetch fault only.
        if(variant==4)emit(ri(0x13,20,0,0,17),20,17);
        read(0x140,19,0xaabbccddeeff0011ULL);csr(0x140,20);
        emit(ri(0x13,7,0,0,4),7,4);emit(0x0103f357,6,4);
        upper(7,GVA+0x3000);emit(0x0203e107);emit(0x0221b0d7);
        emit(ri(0x13,8,0,7,0x20),8,GVA+0x3020);emit(0x020460a7);
        emit(ri(0x03,10,3,8,0),10,0x000000050000002dULL);
        emit((2u<<27)|(8<<15)|(2<<12)|(22<<7)|0x2f,22,45);emit(0x020460a7);
        emit((3u<<27)|(8<<15)|(2<<12)|(23<<7)|0x2f,23,1);
        emit(ri(0x07,0,2,7,0x40),0,0xffffffff3f800000ULL,true);
        emit(ri(0x73,0,5,3,0x002));emit(ri(0x73,0,5,0,0x001));
        emit(ri(0x13,14,0,7,0x50),14,GVA+0x3050);emit(0x02076107);
        emit(0x022050d7,0,0,false,1);emit(0x020460a7);
        emit(ri(0x03,10,3,8,0),10,0x3f8000013f800001ULL);
        emit(0x42101057,0,0xffffffff3f800001ULL,true);emit(0xe2000953,18,0xffffffff3f800001ULL);
        read(0x001,19,1);
        if(variant==1||variant==2||variant==3||variant==6){
            upper(9,GVA+0x5000);
            uint32_t bad=(variant==1||variant==6)?ri(0x03,10,3,9,0):(variant==2?0x0204e107:0x0204e0a7);
            trap(bad,variant==3?23:21,GVA+0x5000,variant==6?0:badGpa>>2);
            read(0x008,19,0); // faulting element zero retains the restart boundary.
        }
        if(variant==5){upper(9,GVA+0x7000);trap(ri(0x03,10,3,9,0),13,GVA+0x7000);}
        trap(0x00000073,10,0); // VS ECALL must reach HS with the separate cause code.
        read(0x140,19,17);
        upper(30,GVA+0x6000);
        if(variant==7){
            emit(ri(0x13,29,0,0,6),29,6);emit(st(3,30,29,0x50));
            emit(st(3,30,29,0x20)); // Both managed domains stop; system clock stays alive.
        }else{emit(ri(0x13,29,0,0,2),29,2);emit(st(3,30,29,0x20));}
        for(unsigned n=0;n<32;++n)emit(ri(0x13,0,0,0,0));
        emit(ri(0x03,29,3,30,0x158),29,0x51);read(0x140,19,17);
        emit(ri(0x13,29,0,0,6),29,6);emit(st(3,30,29,0x50));
        emit(ri(0x13,29,0,0,4),29,4);emit(st(3,30,29,0x20));
        for(unsigned n=0;n<32;++n)emit(ri(0x13,0,0,0,0));
        read(0xc20,29,4);emit(ri(0x03,29,3,30,0x198),29,0x51);
        emit(ri(0x13,29,0,0,4),29,4);emit(st(3,30,29,0x50));
        emit(0x020460a7);emit(ri(0x13,20,0,0,1),20,1);emit(st(3,7,20,0x180));
        bytes(cursor,0x0000006f,4);
    }
};
int main(int argc,char **argv){try {
    const std::string option=argc>1?argv[1]:"";
    const bool inject=option=="--inject-value",injectFlags=option=="--inject-flags",injectGate=option=="--inject-gate";
    const bool injectHtval=option=="--inject-htval",injectCause=option=="--inject-cause";
    for(unsigned variant=0;variant<8;++variant)for(auto periods:{std::array<unsigned,3>{10,6,8},{6,10,12}})
    for(unsigned latency:{1u,12u}) {
        if((injectHtval||injectCause)&&variant!=1)continue;
        if(variant>0 && (latency!=12 || ((variant%2==0)!=(periods[0]==10))))continue;
        const bool managed=true;
        HypervisorProgram p(variant);Model d;AxiMemory memory(d,p.image,false,false);
        memory.readLatency=latency;memory.writeLatency=latency;
        d.set_cpuClock(0);d.set_vpuClock(0);d.set_systemClock(0);d.set_commonColdReset(1);
        d.set_io$$memoryReady(1);d.set_io$$uartRx(1);d.set_io$$externalIrq(0);
        d.set_io$$wakeCpu(0);d.set_io$$wakeVpu(0);memory.inputs(0);d.step();
        bool oldCpu=false,oldVpu=false,oldSystem=false,gateCpu=true,gateVpu=true;
        bool sawCpuStop=false,sawVpuStop=false,wakeStarted=false,wakeEnded=false,sawBothStop=false;
        uint64_t cpuCycles=0,systemCycles=0,cpuOff=0,vpuOff=0;unsigned checked=0;
        for(uint64_t tick=0;tick<2000000&&checked<p.expected.size();++tick) {
            const bool cold=tick<160;
            const bool rawCpu=(tick%periods[0])>=periods[0]/2;
            const bool rawVpu=((tick+1)%periods[1])>=periods[1]/2;
            const bool system=((tick+2)%periods[2])>=periods[2]/2;
            if(!rawCpu)gateCpu=d.get_io$$cpuClockEnable();
            if(!rawVpu)gateVpu=d.get_io$$vpuClockEnable();
            const bool cpu=rawCpu&&gateCpu,vpu=rawVpu&&gateVpu;
            const bool cpuEdge=cpu&&!oldCpu,systemEdge=system&&!oldSystem;
            d.set_cpuClock(oldCpu);d.set_vpuClock(oldVpu);d.set_systemClock(oldSystem);
            d.set_commonColdReset(cold);
            if(systemEdge)memory.inputs(systemCycles);
            d.set_io$$wakeCpu(wakeStarted&&!wakeEnded);d.step();
            if(!cold) {
                need(!d.get_io$$protocolError(),"managed system native protocol error");
                sawBothStop |= !d.get_io$$cpuClockEnable()&&!d.get_io$$vpuClockEnable();
                if(!d.get_io$$cpuClockEnable()) {
                    sawCpuStop=true;if(systemEdge)++cpuOff;
                    need(d.get_io$$cpuStopAck()&&d.get_io$$fabricIdle()&&!injectGate,
                        "independent managed clock drain oracle");
                    need(memory.reads.empty()&&!memory.sending&&memory.addresses.empty()&&
                        memory.writeBeats.empty()&&memory.replies.empty(),"CPU gated with outstanding AXI owner");
                    need(!d.get_io$$retire$$valid(),"CPU retirement valid while clock stopped");
                }
                if(!d.get_io$$vpuClockEnable()) {
                    sawVpuStop=true;if(systemEdge)++vpuOff;
                    need(d.get_io$$vpuStopAck(),"VPU gated before complete drain acknowledgement");
                }
                if(sawCpuStop&&cpuOff>=40)wakeStarted=true;
                if(wakeStarted&&d.get_io$$cpuClockEnable()&&!d.get_io$$cpuStopAck())wakeEnded=true;
                if(systemEdge)memory.outputs(systemCycles);
                if(cpuEdge&&d.get_io$$retire$$valid()) {
                    auto e=p.expected.at(checked);
                    if(inject&&e.instruction==0x0103f357&&!e.trap)e.value^=1;
                    if(injectFlags&&e.flags)e.flags^=1;
                    if(injectHtval&&(e.instruction>>20)==0x643&&e.value)e.value^=1;
                    if(injectCause&&e.trap&&e.cause==21)e.cause^=1;
                    const auto at=" index="+std::to_string(checked)+" pc="+std::to_string(e.pc);
                    need(d.get_io$$retire$$bits$$pc()==e.pc&&d.get_io$$retire$$bits$$instruction()==e.instruction,
                        "managed independent PC/instruction oracle"+at);
                    need(bool(d.get_io$$retire$$bits$$trap())==e.trap,"managed independent trap oracle"+at);
                    if(e.trap)need(d.get_io$$retire$$bits$$cause()==e.cause&&d.get_io$$retire$$bits$$tval()==e.tval,
                        "managed precise cause/tval oracle"+at);
                    need(bool(d.get_io$$retire$$bits$$writesRd())==e.integer,"managed integer enable oracle"+at);
                    if(e.integer)need(d.get_io$$retire$$bits$$rd()==e.rd&&
                        (d.get_io$$retire$$bits$$data()&e.mask)==(e.value&e.mask),"managed independent value oracle"+at+
                        " got="+std::to_string(d.get_io$$retire$$bits$$data())+" expected="+std::to_string(e.value));
                    need(bool(d.get_io$$retire$$bits$$floating$$write())==e.floating,"managed FPR enable oracle"+at);
                    if(e.floating)need(d.get_io$$retire$$bits$$rd()==e.rd&&d.get_io$$retire$$bits$$floating$$data()==e.value,
                        "managed independent IEEE/f0 oracle"+at);
                    need(d.get_io$$retire$$bits$$floating$$flags()==e.flags,"managed independent flags oracle"+at);
                    if(!e.trap)need(d.get_io$$retire$$bits$$nextPc()==e.next,"managed next-PC oracle"+at);
                    ++checked;
                }
            }
            d.set_cpuClock(cpu);d.set_vpuClock(vpu);d.set_systemClock(system);d.step();
            oldCpu=cpu;oldVpu=vpu;oldSystem=system;
            if(cpuEdge&&!cold)++cpuCycles;if(systemEdge&&!cold)++systemCycles;
        }
        need(checked==p.expected.size(),"managed bounded completion index="+std::to_string(checked));
        need(memory.load(0x23020)==0x3f8000013f800001ULL&&memory.load(0x23028)==0x3f8000013f800001ULL,
            "managed independent final vector RAM oracle");
        need(memory.load(0x23180)==1,"guest completion sentinel");
        if(variant==7)need(sawBothStop,"simultaneous CPU/VPU stop coverage incomplete");
        if(managed) {
            need(sawCpuStop&&sawVpuStop&&cpuOff>=40&&vpuOff>0&&wakeEnded,"managed CPU/VPU stop/wake coverage incomplete");

        }
        std::cout<<"I1_HYPERVISOR_SYSTEM_PASS variant="<<variant<<" periods="<<periods[0]<<":"<<periods[1]<<":"<<periods[2]
            <<" latency="<<latency<<" retired="<<checked<<" cpu_cycles="<<cpuCycles<<" system_cycles="<<systemCycles
            <<" cpu_off="<<cpuOff<<" vpu_off="<<vpuOff<<" Sv39x4_HLV_HSV_HLVX_guest_fault_CMU_V_FCSR_LRSC=PASS\n";
    }
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
