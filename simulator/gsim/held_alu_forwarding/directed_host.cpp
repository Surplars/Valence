// Uses the unchanged qualified Test, DDR model, fabric service and amended
// SupplyLedger. Only this new directed executable selects new predeclared laws.
#define main preserved_board_boot_main
#include "host/harness/board_boot.cpp"
#undef main
#include "host/supply_ledger.h"
#include "held_observer.h"
#include "directed_tagged_probe.h"
#ifndef B1_ENABLED
#define B1_ENABLED 0
#endif
#if B1_ENABLED
#include "binding_memory_on.h"
#include "binding_memory_core_on.h"
#else
#include "binding_memory_retained_a.h"
#include "binding_memory_core_retained_a.h"
#endif
static_assert(binding_memory::required_bindings_complete);
static_assert(binding_core::required_bindings_complete);
#include <filesystem>
#ifndef B1_ENABLED
#define B1_ENABLED 0
#endif
static_assert(B1_ENABLED==0||B1_ENABLED==1);

struct Directed {
    b1::HeldObserver oracle;
    b1_transport::Probe tagged;
    SupplyLedger supply;
    Test* test=nullptr;
    uint64_t callbackCycles=0,roiCycles=0,tailCycles=0;
    uint64_t lastSequence=0;
    std::map<uint64_t,unsigned> lineOccurrences;
    bool armed=false;
    Directed(b1::Scenario scenario,const Bytes& image,std::string mutation)
        :oracle(std::move(scenario),B1_ENABLED,std::move(mutation)) {
        oracle.seed_image(image);
        tagged.expectedPhysical=[&](tagged_board::Token t){return oracle.expected_pa({t.index,t.tag});};
        tagged.expectedLocalFault=[&](tagged_board::Token t,unsigned flags){return oracle.expected_local_fault({t.index,t.tag},flags);};
    }
    static void sample(SBoardSocGsim& d,void* context){static_cast<Directed*>(context)->sample(d);}
    void sample(SBoardSocGsim& d){
        const uint64_t cycle=callbackCycles++;
        if(cycle<4)return; // Original Test holds reset for precisely four ticks.
        b1::Snapshot s;s.cycle=cycle;
        binding_memory::sample(d,s);
        binding_core::sample(d,s);
        oracle.sample(s);
        // Original constructor has no accepted DDR transfers before calibration.
        // The tagged owner ledger can safely start here, including fixed boot.
        tagged.sample(d,cycle);
        if(test){
            const bool roi=!oracle.terminalSeen;
            if(roi)++roiCycles;else ++tailCycles;
            supply.sample(d,test->ddr,roi,oracle.terminalSeen,false,cycle);
        }
    }
    void configure_new_reads(){
        // Called immediately after the original model accepts requests. Only
        // first eligibility/error metadata for each newly accepted sequence is
        // changed, by fixed address/occurrence/phase inputs known before boot.
        for(auto& r:test->ddr.pendingReads)if(r.sequence>=lastSequence){
            const uint64_t physical=ramBase+uint64_t(r.address),line=physical&~UINT64_C(63);
            const unsigned occurrence=lineOccurrences[line]++;
            r.due+=oracle.scenario.phase;
            if(oracle.scenario.delayedLine==line)
                r.due=std::max<uint64_t>(r.due,test->cycles-1+oracle.scenario.delay);
            r.error=oracle.scenario.errorLine==line&&occurrence==0;
            lastSequence=std::max(lastSequence,r.sequence+1);
        }
    }
    void tick(){test->tick();configure_new_reads();}
    bool drained() const {
        return oracle.requests.empty()&&test->ddr.pendingReads.empty()&&test->ddr.pendingWrites.empty()&&test->ddr.pendingB.empty()&&
            tagged.ledger.handles.empty()&&tagged.ledger.transport.empty()&&tagged.ledger.storeOwners.empty()&&
            std::all_of(tagged.ledger.slots.begin(),tagged.ledger.slots.end(),[](const auto& x){return !x;})&&
            std::all_of(supply.owners.begin(),supply.owners.end(),[](const auto& x){return !x.live;})&&
            std::all_of(supply.wb.begin(),supply.wb.end(),[](const auto& x){return !x.live;});
    }
};
int main(int argc,char** argv){
    std::unique_ptr<Directed> observer;
    try {
        check(argc==3||argc==4,"usage: directed-run guest.bin frozen-case.txt [mutation]");
        const auto image=readFile(argv[1]);const auto scenario=b1::Scenario::read(argv[2]);
        observer=std::make_unique<Directed>(scenario,image,argc==4?argv[3]:"");
        Bytes rom;word(rom,0x00200297);word(rom,0x00028067);rom.resize(64,0);
        Test test(rom,Directed::sample,observer.get());test.running=false;observer->test=&test;
        auto seed=[&](uint64_t pa,uint64_t value){check(pa>=ramBase&&pa-ramBase<BOARD_DDR_BYTES,"seed outside original DDR aperture");test.ddr.memory[uint32_t(pa-ramBase)]=value;};
        for(auto [address,value]:scenario.seed)seed(address,value);
        for(size_t off=0;off<image.size();off+=8){uint64_t value=0;for(unsigned b=0;b<8&&off+b<image.size();++b)value|=uint64_t(image[off+b])<<(8*b);seed(ramBase+off,value);}
        while(test.cycles<30000&&!observer->oracle.terminalSeen)observer->tick();
        check(observer->oracle.terminalSeen,"B1 terminal marker not reached in fixed cycle bound");
        for(const auto& [address,record]:observer->oracle.terminalStores){
            // Check the guest's FENCE.I-protected terminal bytes before a
            // terminal ECALL handler can overwrite the fault mailbox.
            check(record.first==8,"frozen guest terminal store size changed");
            check(test.ddr.memory[uint32_t(address-ramBase)]==record.second,"independent terminal committed store bytes mismatch");
        }
        // Let already accepted work/dirty writeback retire naturally. No control
        // force, response drop or model reset is used to manufacture drain.
        while(test.cycles<30000&&!observer->drained())observer->tick();
        check(observer->drained(),"B1 accepted obligations failed bounded terminal drain");
        observer->oracle.verify_terminal();observer->tagged.finish();test.fabric.finish();
        observer->supply.finish(observer->roiCycles,observer->tailCycles);
        check(test.ddr.memory[uint32_t(scenario.signatureAddress-ramBase)]==scenario.signature,"independent final backing signature mismatch");
        check(test.ddr.memory[uint32_t(scenario.sentinelAddress-ramBase)]==scenario.sentinel,"independent final backing sentinel mismatch");
        observer->tagged.report();observer->oracle.report();
        std::cout<<"B1_DIRECTED_FUNCTIONAL_PASS bound=30000 timeout_contract_seconds=120 coverage=REQUIRES_FAMILY_AGGREGATION\n";
        return 0;
    }catch(const std::exception& error){
        const bool applied=observer&&observer->oracle.applied;
        std::cerr<<"B1_DIRECTED_FAIL mutation="<<(observer?observer->oracle.mutation:"")<<" applied="<<applied<<" "<<error.what()<<"\n";
        if(observer&&!observer->oracle.mutation.empty()&&!applied)return 3;
        return 1;
    }
}
