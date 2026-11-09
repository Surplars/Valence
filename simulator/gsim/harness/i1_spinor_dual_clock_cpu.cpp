// Real CPU/VPU clocks, full transactions and the SAME independent program oracle.
#define I1_SPINOR_CPU_DUAL
#define I1_SPINOR_PROGRAM_ONLY
#include "i1_spinor_cpu.cpp"

int main(int argc,char**argv){try{
    const bool inject=argc>1&&std::string(argv[1])=="--inject-value";
    const bool injectFlags=argc>1&&std::string(argv[1])=="--inject-flags";
    for(auto periods:{std::array<unsigned,2>{10,6},{6,10}})for(unsigned latency:{1u,12u}){
        Program p;Model d;Memory memory(d,p.image,latency);
        d.set_cpuClock(0);d.set_vpuClock(0);d.set_commonColdReset(1);
        d.set_io$$time(0);d.set_io$$externalIrq(0);d.set_io$$timerIrq(0);d.set_io$$softwareIrq(0);
        memory.inputs(0);d.step();bool oldCpu=false,oldVpu=false;
        unsigned checked=0,offered=0,done=0;uint64_t cycle=0,tick=0;
        for(;tick<300000 && checked<p.expected.size();++tick){
            const bool cold=tick<80;
            bool cpu=(tick%periods[0])>=periods[0]/2;
            bool vpu=((tick+1)%periods[1])>=periods[1]/2;
            if(tick>=1800&&tick<2000)vpu=oldVpu;
            if(tick>=2400&&tick<2500)cpu=oldCpu;
            const bool cpuEdge=cpu&&!oldCpu;
            d.set_commonColdReset(cold);d.set_cpuClock(oldCpu);d.set_vpuClock(oldVpu);
            if(cpuEdge)memory.inputs(cycle);
            d.set_io$$time(cycle);d.step(); // settle inputs without a clock edge
            if(cpuEdge&&!cold){
                memory.outputs(cycle);
            need(!d.get_io$$protocolError(),"Spinor native protocol error");
            if(d.get_observation$$vectorOffer$$valid()) {
                need(offered<p.offers.size(),"unexpected CPU vector command");
                auto o=p.offers.at(offered++);
                auto token=d.get_observation$$vectorOffer$$bits$$token();
                need(uint64_t(token>>64)==0xbeef && uint64_t(token)==o.sequence,"CPU 80-bit vector token oracle");
                need(d.get_observation$$vectorOffer$$bits$$instruction()==o.instruction,"CPU vector command order oracle");
                if(o.scalar) need(d.get_observation$$vectorOffer$$bits$$scalar()==*o.scalar,"CPU native scalar/f0 operand oracle");
            }
            done+=d.get_observation$$vectorDone();
            if(d.get_io$$retire$$valid()) {
            auto e=p.expected.at(checked);
            if(inject && e.instruction==0x0103f357 && !e.trap)e.value^=1;
            if(injectFlags && e.flags)e.flags^=1;
            const std::string at=" index="+std::to_string(checked)+" pc="+std::to_string(e.pc);
            need(d.get_io$$retire$$bits$$pc()==e.pc && d.get_io$$retire$$bits$$instruction()==e.instruction,
                 "CPU vector independent PC/instruction oracle"+at);
            need(bool(d.get_io$$retire$$bits$$trap())==e.trap,"CPU vector independent trap oracle"+at);
            if(e.trap) need(d.get_io$$retire$$bits$$cause()==e.cause && d.get_io$$retire$$bits$$tval()==e.tval,
                           "CPU vector precise cause/tval oracle"+at);
            need(bool(d.get_io$$retire$$bits$$writesRd())==e.integer,"CPU vector integer enable oracle"+at);
            if(e.integer) {
                const uint64_t got=d.get_io$$retire$$bits$$data();
                need(d.get_io$$retire$$bits$$rd()==e.rd && (got&e.mask)==(e.value&e.mask),
                     "CPU vector independent value oracle"+at+" got="+std::to_string(got)+" expected="+std::to_string(e.value));
            }
            need(bool(d.get_io$$retire$$bits$$floating$$write())==e.floating,"CPU vector FPR enable oracle"+at);
            if(e.floating) need(d.get_io$$retire$$bits$$rd()==e.rd && d.get_io$$retire$$bits$$floating$$data()==e.value,
                                "CPU vector independent f0/IEEE oracle"+at);
            need(d.get_io$$retire$$bits$$floating$$flags()==e.flags,"CPU vector independent flags oracle"+at);
            if(!e.trap)need(d.get_io$$retire$$bits$$nextPc()==e.next,"CPU vector precise next-PC oracle"+at);
            ++checked;
            }
            }
            d.set_cpuClock(cpu);d.set_vpuClock(vpu);d.step();oldCpu=cpu;oldVpu=vpu;
            if(cpuEdge&&!cold)++cycle;
        }
        need(checked==p.expected.size(),"CPU vector bounded completion index="+std::to_string(checked));
        need(offered==p.offers.size()&&done==offered,"CPU vector native offer/done ledger");
        need(memory.load(BASE+0x2020)==0x3f8000013f800001ULL && memory.load(BASE+0x2028)==0x3f8000013f800001ULL,
             "CPU vector final independent RAM oracle");
        need(memory.load(BASE+0x2180)==1,"CPU scalar completion sentinel oracle");
        std::cout<<"I1_SPINOR_DUAL_CLOCK_CPU_PASS latency="<<latency<<" cpu_cycles="<<cycle<<" periods="<<periods[0]<<":"<<periods[1]<<" retire="<<checked
                 <<" vector_commands="<<offered<<" traps=2 token80_VS_FCSR_f0_cache_LRSC=PASS\n";
    }
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
