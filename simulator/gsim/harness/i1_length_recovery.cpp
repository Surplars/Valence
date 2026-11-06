// The independent ISA/store ledgers stay in the established bare-core driver.
// Only the external response schedule aligns a live C parcel with a real branch.
#define main i1_integer_core_main
#include "five_stage.cpp"
#undef main

static_assert(DUT_HAS_C && DUT_XLEN == 64, "requires the RV64 C no-predictor bare core");
struct LengthRecoveryObserver : FiveStageObserver {
    const uint64_t special, target;
    const bool full;
    bool specialAccepted=false, waitingTarget=false, targetOffered=false;
    unsigned overlaps=0;
    LengthRecoveryObserver(uint64_t pc, uint64_t destination, bool blocked)
        : special(pc),target(destination),full(blocked) {}
    void cycle(SFiveStageCore &d, uint64_t) override {
        const bool redirect=d.get_io$$branchMispredict();
        const bool offered=d.get_io$$instructionRequest$$valid();
        const uint64_t pc=d.get_io$$instructionRequest$$bits();
        if(redirect) {
            need(specialAccepted, "length recovery flush preceded the scheduled live C owner");
            need(bool(d.get_io$$instructionResponse$$ready())==!full,
                "length recovery did not reach the intended queue capacity");
            need(!offered, "length recovery leaked an unoffered fetch at same-cycle flush");
            ++overlaps; waitingTarget=true;
        } else if(waitingTarget&&offered) {
            need(pc==target, "length recovery emitted a killed sequential fetch before redirect target");
            waitingTarget=false; targetOffered=true;
        }
        // This test uses fixed READY=1. Every visible request is accepted.
        if(offered&&pc==special) specialAccepted=true;
    }
};
int main(int argc,char **argv) { try {
    const std::string option=argc>1?argv[1]:"";
    for(bool full : {false,true}) {
        if((option=="--empty"&&full) || (option=="--full"&&!full)) continue;
        constexpr uint64_t target=BASE+0x80;
        const uint64_t special=BASE+(full?32:12);
        std::vector<uint32_t> code(0x8c/4,ri(0x13,0,0,0,0));
        code[0]=0x00002a17; // AUIPC x20,2
        code[1]=ri(0x03,4,3,20,512); // old real load holds branch in ADDR
        code[2]=br(0,0,0,0x78); // taken BEQ to independent target
        for(unsigned offset=12;offset<special-BASE;offset+=4)
            code[offset/4]=ri(0x13,1,0,0,33); // fill EX/RF/ID and the two IF slots
        code[(special-BASE)/4]=0x00010001; // live wrong-path C.NOP reply, predictor defaults +4
        code[0x80/4]=ri(0x13,31,0,0,77);
        code[0x84/4]=st(3,20,31,0);
        code[0x88/4]=0x00100073;
        LengthRecoveryObserver observer(special,option=="--inject-target"?target^4:target,full);
        auto result=execute(full?"mixed-c-length-flush-full":"mixed-c-length-flush-empty",code,1,
            {},{},false,false,false,false,64,&observer,true,special);
        need(observer.overlaps==1&&observer.targetOffered,"length recovery redirect coverage missing");
        need(result.synchronizedReplyFlushReady==uint64_t(!full) &&
             result.synchronizedReplyFlushBlocked==uint64_t(full),
             "length recovery external C response/flush overlap was not exercised");
        std::cout<<"I1_LENGTH_RECOVERY_PASS queue_full="<<full<<" cycles="<<result.cycles
            <<" retired="<<result.retires<<" response_ready_overlap="<<result.synchronizedReplyFlushReady
            <<" response_blocked_overlap="<<result.synchronizedReplyFlushBlocked
            <<" no_unoffered_fetch_precise_PC_ISA_store=PASS\n";
    }
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
