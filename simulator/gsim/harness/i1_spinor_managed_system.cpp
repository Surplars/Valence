#include "I1SpinorManagedSystem.h"
#define FIVE_STAGE_ORACLE_ONLY
#include "five_stage.cpp"
#include <deque>
#include <map>
#include <optional>
#include "i1_spinor_program_reference.h"
using Model=SI1SpinorManagedSystem;
#include "i1_axi_memory_reference.h"
struct ManagedProgram:Program {
    explicit ManagedProgram(bool managed) {
        if(!managed)return;
        cursor-=4; // Replace the unexecuted final stop loop, preserving the original oracle.
        emit(0x10080f37,30,0x10080000);
        emit(ri(0x13,29,0,0,2),29,2);
        emit(st(3,30,29,0x20)); // Request CPU retention through real CMU MMIO.
        // STOP crosses into the CPU domain; allow the in-flight instruction
        // window to drain before checking the status after external wake.
        for(unsigned n=0;n<32;++n)emit(ri(0x13,0,0,0,0));
        emit(ri(0x03,29,3,30,0x158),29,0x51); // enabled, admitted, wake pending
        emit(ri(0x13,29,0,0,6),29,6);
        emit(st(3,30,29,0x50)); // Clear CPU and old vector-command wake history.
        emit(ri(0x13,29,0,0,4),29,4);
        emit(st(3,30,29,0x20)); // Stop VPU while CPU continues executing.
        for(unsigned n=0;n<32;++n)emit(ri(0x13,0,0,0,0));
        vec(ri(0x73,29,2,0,0xc20),29,4); // Pending CSR command wakes the retained VPU.
        emit(ri(0x03,29,3,30,0x198),29,0x51);
        emit(ri(0x13,29,0,0,4),29,4);emit(st(3,30,29,0x50));
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020); // VRF contents survived clock stop.
        emit(ri(0x13,29,0,0,0x55),29,0x55);emit(st(3,8,29,0x188));
        bytes(cursor,0x0000006f,4);
    }
};
int main(int argc,char **argv){try {
    const std::string option=argc>1?argv[1]:"";
    const bool inject=option=="--inject-value",injectFlags=option=="--inject-flags",injectGate=option=="--inject-gate";
    for(bool managed:{false,true})for(auto periods:{std::array<unsigned,3>{10,6,8},{6,10,12}})
    for(unsigned latency:{1u,12u}) {
        ManagedProgram p(managed);Model d;AxiMemory memory(d,p.image,false,false);
        memory.readLatency=latency;memory.writeLatency=latency;
        d.set_cpuClock(0);d.set_vpuClock(0);d.set_systemClock(0);d.set_commonColdReset(1);
        d.set_io$$memoryReady(1);d.set_io$$uartRx(1);d.set_io$$externalIrq(0);
        d.set_io$$wakeCpu(0);d.set_io$$wakeVpu(0);memory.inputs(0);d.step();
        bool oldCpu=false,oldVpu=false,oldSystem=false,gateCpu=true,gateVpu=true;
        bool sawCpuStop=false,sawVpuStop=false,wakeStarted=false,wakeEnded=false;
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
        need(memory.load(0x2020)==0x3f8000013f800001ULL&&memory.load(0x2028)==0x3f8000013f800001ULL,
            "managed independent final vector RAM oracle");
        need(memory.load(0x2180)==1,"managed scalar completion sentinel");
        if(managed) {
            need(sawCpuStop&&sawVpuStop&&cpuOff>=40&&vpuOff>0&&wakeEnded,"managed CPU/VPU stop/wake coverage incomplete");
            need(memory.load(0x2188)==0x55,"managed retention completion sentinel");
        }
        std::cout<<"I1_MANAGED_SYSTEM_PASS managed="<<managed<<" periods="<<periods[0]<<":"<<periods[1]<<":"<<periods[2]
            <<" latency="<<latency<<" retired="<<checked<<" cpu_cycles="<<cpuCycles<<" system_cycles="<<systemCycles
            <<" cpu_off="<<cpuOff<<" vpu_off="<<vpuOff<<" AXI_CMU_retention_V_FCSR_LRSC=PASS\n";
    }
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
