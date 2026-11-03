// Actual I1 prediction observations, checked against the existing independent ISA/bus oracle.
#define I1_PERFORMANCE_OBSERVER 1
#define main i1_independent_integer_main
#include "five_stage.cpp"
#undef main
#include <map>
#include <iomanip>

#include "i1_prediction_metrics.h"
struct PerformanceObserver : FiveStageObserver, I1PredictionMetrics<SFiveStageCore> {
    void cycle(SFiveStageCore &dut, uint64_t cycle) override {
        I1PredictionMetrics<SFiveStageCore>::cycle(dut, cycle);
    }
    void retire(SFiveStageCore &dut, uint64_t cycle, uint64_t pc, uint32_t instruction,
                uint64_t next, bool trap) override {
        I1PredictionMetrics<SFiveStageCore>::retire(dut, cycle, pc, instruction, next, trap);
    }
};

static void backward(std::vector<uint32_t>& code,unsigned loop,unsigned reg) {
    const int offset=4*(int(loop)-int(code.size())); code.push_back(br(1,reg,0,unsigned(offset)));
}
static std::map<std::string,std::vector<uint32_t>> programs() {
    std::map<std::string,std::vector<uint32_t>> cases;
    auto &alu=cases["alu_independent"];
    for(unsigned i=0;i<256;++i) alu.push_back(ri(0x13,1+i%15,0,0,i));
    alu.push_back(0x00100073);
    auto &dependent=cases["alu_dependent"];
    for(unsigned i=0;i<256;++i) dependent.push_back(ri(0x13,1,0,1,1));
    dependent.push_back(0x00100073);
    auto &loop=cases["predictable_loop"];
    loop={ri(0x13,10,0,0,256),ri(0x13,2,0,0,0)};
    unsigned start=loop.size();
    loop.push_back(ri(0x13,2,0,2,1));loop.push_back(ri(0x13,10,0,10,-1));backward(loop,start,10);loop.push_back(0x00100073);
    auto &alternating=cases["alternating_direction"];
    alternating={ri(0x13,10,0,0,256),ri(0x13,2,0,0,0),ri(0x13,5,0,0,0)};
    start=alternating.size();
    alternating.push_back(ri(0x13,2,4,2,1));alternating.push_back(br(0,2,0,8));alternating.push_back(ri(0x13,5,0,5,1));
    alternating.push_back(ri(0x13,10,0,10,-1));backward(alternating,start,10);alternating.push_back(0x00100073);
    auto &random=cases["lfsr_direction"];
    random={ri(0x13,10,0,0,256),ri(0x13,2,0,0,1),ri(0x13,5,0,0,0)};start=random.size();
    random.push_back(ri(0x13,3,5,2,1));random.push_back(ri(0x13,4,7,2,1));random.push_back(rr(0x33,4,0,0,4,32));
    random.push_back(ri(0x13,4,7,4,0xb8));random.push_back(rr(0x33,2,4,3,4));random.push_back(ri(0x13,3,7,2,1));
    random.push_back(br(0,3,0,8));random.push_back(ri(0x13,5,0,5,1));
    random.push_back(ri(0x13,10,0,10,-1));backward(random,start,10);random.push_back(0x00100073);
    for(unsigned calls : {1U,2U}) {
        auto &code=cases[calls==1?"fixed_return":"alternating_return"];
        code={ri(0x13,10,0,0,128),ri(0x13,5,0,0,0)};start=code.size();
        std::vector<unsigned> sites;
        for(unsigned i=0;i<calls;++i){sites.push_back(code.size());code.push_back(0);}
        code.push_back(ri(0x13,10,0,10,-1));backward(code,start,10);code.push_back(0x00100073);
        const unsigned function=code.size();
        code.push_back(ri(0x13,5,0,5,1));code.push_back(ri(0x67,0,0,1,0));
        for(auto site:sites)code[site]=jal(1,4*(function-site));
    }
    auto &indirect=cases["alternating_indirect"];
    indirect={ri(0x13,10,0,0,128),6<<7|0x17U,ri(0x13,6,0,6,0x400-4),ri(0x13,5,0,0,0)};
    start=indirect.size();indirect.push_back(ri(0x67,1,0,6,0));indirect.push_back(ri(0x13,6,4,6,0x100));
    indirect.push_back(ri(0x13,10,0,10,-1));backward(indirect,start,10);indirect.push_back(0x00100073);
    indirect.resize(0x400/4,ri(0x13,0,0,0,0));indirect.push_back(ri(0x13,5,0,5,1));indirect.push_back(ri(0x67,0,0,1,0));
    indirect.resize(0x500/4,ri(0x13,0,0,0,0));indirect.push_back(ri(0x13,5,0,5,2));indirect.push_back(ri(0x67,0,0,1,0));
    auto &loads=cases["dependent_load_store"];
    loads={0x00002a17,ri(0x13,10,0,0,128),ri(0x13,1,0,0,7),st(3,20,1,0)};start=loads.size();
    loads.push_back(ri(0x03,2,3,20,0));loads.push_back(ri(0x13,2,0,2,1));loads.push_back(st(3,20,2,0));
    loads.push_back(ri(0x13,10,0,10,-1));backward(loads,start,10);loads.push_back(0x00100073);
    return cases;
}

int main(int argc,char **argv) {try {
    if(argc>1&&std::string(argv[1])=="--isa-smoke")return i1_independent_integer_main(argc-1,argv+1);
    const bool corrupt=argc==2 && std::string(argv[1])=="--inject-observation";
    const bool corruptOracle=argc==2 && std::string(argv[1])=="--inject-register-mismatch";
    for(const auto &[name,code]:programs())for(unsigned latency:{1U,7U}) {
        PerformanceObserver observer;
        observer.injectObservation=corrupt && name=="predictable_loop";
        const auto stats=execute("performance-"+name,code,latency,{}, {},false,
            corruptOracle,false,false,0,&observer,true);
        observer.report(name,latency,stats.cycles);
    }
    std::cout<<"I1_PERFORMANCE_PASS actual_retired_predictions independent_isa_bus_oracle fixed_service warm_after_8_per_pc=PASS\n";
    return 0;
}catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}}
