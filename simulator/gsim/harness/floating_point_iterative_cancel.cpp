// Reuse the scalar driver only. This executable has its own targeted workload.
#define main floating_point_full_matrix_main
#include "floating_point_full.cpp"
#undef main
#include <map>
#include <set>

int main(int argc,char** argv) {try {
    if(argc<2 || argc>3) throw std::runtime_error("SoftFloat vectors and optional --omit-cancel required");
    const bool omitCancel=argc==3 && std::string(argv[2])=="--omit-cancel";
    if(argc==3 && !omitCancel) throw std::runtime_error("unknown cancellation option");
    std::ifstream input(argv[1]);Request r;std::map<unsigned,Request> cases;
    while(input>>std::hex>>r.inst>>r.rm>>r.a>>r.b>>r.c>>r.integer>>r.value>>r.flags) {
        const unsigned function=(r.inst>>25)&0x7e;
        if((r.inst&127)!=0x53 || (function!=0x0c && function!=0x2c)) continue;
        if(Driver::iterativeLatency(r,function==0x2c)==4) continue;
        const unsigned key=unsigned(bool(r.inst&(1U<<25)))*10+unsigned(function==0x2c)*5+r.rm;
        cases.try_emplace(key,r);
    }
    if(!input.eof() || cases.size()!=20) throw std::runtime_error("20 format/opcode/rounding iterative cases required");
    Driver d;d.reset();unsigned kills=0,midpoint=0,late=0,held=0;uint64_t tag=1ULL<<55;
    for(auto [key,request]:cases) {
        const unsigned latency=Driver::iterativeLatency(request,((request.inst>>25)&0x7e)==0x2c);
        const std::set<unsigned> delays={0,1,latency/2,latency-4,latency-3,latency-2,latency-1,latency};
        for(unsigned delay:delays) for(bool byReset:{false,true}) {
            request.tag=tag++;
            d.inputs(request,true,false);d.step();
            d.check(d.dut.get_io$$request$$ready(),"iterative kill begins with one free credit");
            for(unsigned i=0;i<delay;++i) {
                d.inputs({},false,false);d.step();
                d.check(!d.dut.get_io$$request$$ready(),"iterative kill retains owner until cancellation");
                d.check(bool(d.dut.get_io$$result$$valid())==(i+1>=latency),"exact pre-cancellation latency");
            }
            if(omitCancel && kills==1) {d.inputs({},false,false);d.step();}
            else if(byReset) d.reset();
            else {
                d.inputs({},false,true,true);d.step();
                d.check(!d.dut.get_io$$result$$valid(),"flush suppresses raw/rounded output at cancellation");
            }
            // The very next available cycle carries a new generation to the
            // same iterative engine; no post-flush cooldown may be hidden.
            auto successor=request;successor.tag=tag++;
            d.transaction(successor,1);
            for(unsigned quiet=0;quiet<latency+8;++quiet) {
                d.inputs({},false,true);d.step();
                d.check(!d.dut.get_io$$result$$valid() && d.dut.get_io$$request$$ready(),
                    "no zombie completion or lost credit after immediate iterative successor");
            }
            d.throughput(successor,latency);
            ++kills;if(delay==latency/2)++midpoint;
            if(delay>=latency-4 && delay<latency)++late;
            if(delay==latency)++held;
        }
    }
    d.check(kills==320 && midpoint==40 && late==160 && held==40,"targeted cancellation coverage");
    std::cout<<"FP_ITERATIVE_CANCEL_PASS cases=20 cancel_points=8 flush=160 reset=160 midpoint="<<midpoint
        <<" late_or_raw_boundary="<<late<<" held="<<held<<" immediate_refire="<<kills
        <<" successor_ii_checks="<<d.iiChecks<<" cycles="<<d.cycles<<" no_zombie=1\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
