// Independent full-PC storage ledger; checks public outputs, not DUT tag or decode helpers.
#include "FiveStageBranchPredictor.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef DUT_ENTRIES
#define DUT_ENTRIES 128
#endif
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
#ifndef DUT_C
#define DUT_C 0
#endif
#ifndef DUT_TIMING
#define DUT_TIMING 1
#endif
#ifndef DUT_HASHED
#define DUT_HASHED 0
#endif
struct StoredBranch {
    uint64_t pc=0,target=0;
    unsigned counter=0;
    bool valid=false,conditional=false,control=false,compressed=false;
};
static void require(bool value,const char *message) {
    if(!value)throw std::runtime_error(message);
}
static uint64_t fit(uint64_t value) {return DUT_XLEN==64?value:uint32_t(value);}
static unsigned slot(uint64_t pc) {
    constexpr unsigned bits=std::countr_zero(unsigned(DUT_ENTRIES));
    constexpr unsigned shift=DUT_C&&!DUT_TIMING?1:2;
    unsigned index=unsigned((pc>>shift)%DUT_ENTRIES);
    if(DUT_C&&DUT_TIMING&&(pc&2))index^=DUT_ENTRIES/2;
    if(DUT_HASHED)index^=unsigned((pc>>(shift+bits))%DUT_ENTRIES);
    return index;
}
int main(int argc,char **argv) {try {
    const bool mutation=argc==2&&std::string(argv[1])=="--inject-target";
    SFiveStageBranchPredictor d;
    std::array<StoredBranch,DUT_ENTRIES> ledger{};
    // FPGA C lengths deliberately alias without owning a BTB slot. Keep this
    // software bit array independent of the full-PC branch ownership ledger.
    constexpr bool separateLength=DUT_C&&DUT_TIMING;
    std::array<bool,DUT_ENTRIES> lengths{};
    d.set_reset(1);d.set_io$$train$$valid(0);d.set_io$$invalidate(0);d.set_io$$pc(0x80000000);
    d.step();d.step();d.set_reset(0);
    unsigned checks=0,hits=0,aliases=0,invalidations=0,falseControls=0,shortHits=0,sameSlot=0,preservedBranches=0;
    auto cycle=[&](uint64_t pc,uint64_t trainPc,bool train,bool control,bool conditional,bool taken,
                   bool compressed,uint64_t target,bool invalidate=false) {
        pc=fit(pc);trainPc=fit(trainPc);target=fit(target);
        d.set_io$$pc(pc);d.set_io$$train$$valid(train);d.set_io$$train$$bits$$pc(trainPc);
        d.set_io$$train$$bits$$controlFlow(control);d.set_io$$train$$bits$$conditional(conditional);
        d.set_io$$train$$bits$$taken(taken);d.set_io$$train$$bits$$target(target);
        d.set_io$$train$$bits$$compressed(compressed);d.set_io$$invalidate(invalidate);d.step();
        const auto look=ledger[slot(pc)];const bool hit=look.valid&&look.pc==pc;
        const bool shortPrediction=separateLength?lengths[slot(pc)]:DUT_C&&hit&&look.compressed;
        const bool takenPrediction=hit&&look.control&&(!look.conditional||look.counter>=2);
        require(bool(d.get_io$$taken())==takenPrediction && bool(d.get_io$$compressed())==shortPrediction,
                "independent predictor taken/length class oracle");
        uint64_t expected=takenPrediction?look.target:
            fit(pc+(shortPrediction?2:4));
        if(mutation&&hit)expected^=4;
        if(bool(d.get_io$$hit())!=hit||d.get_io$$nextPc()!=expected) {
            std::cerr<<"predictor check="<<std::dec<<checks<<" pc="<<std::hex<<pc
                <<" expected="<<expected<<" actual="<<d.get_io$$nextPc()
                <<" stored_pc="<<look.pc<<" target="<<look.target<<std::dec
                <<" hit="<<hit<<" actual_hit="<<unsigned(d.get_io$$hit())
                <<" counter="<<look.counter<<" control="<<look.control
                <<" compressed="<<look.compressed<<" train="<<train
                <<" train_pc="<<std::hex<<trainPc<<std::dec<<" invalidate="<<invalidate<<'\n';
            throw std::runtime_error("independent banked predictor full-PC/next-PC oracle mismatch");
        }
#if DUT_TIMING
        std::vector<uint64_t> values{d.get_io$$candidateValues$$plusTwo(),d.get_io$$candidateValues$$plusFour(),
            d.get_io$$candidateValues$$target0()};
#if DUT_ENTRIES >= 4
        values.push_back(d.get_io$$candidateValues$$target1());
#endif
#if DUT_ENTRIES >= 8
        values.push_back(d.get_io$$candidateValues$$target2());
        values.push_back(d.get_io$$candidateValues$$target3());
#endif
        const unsigned mask=d.get_io$$candidateMask();uint64_t selected=0;
        for(unsigned i=0;i<values.size();++i)if((mask>>i)&1)selected|=values[i];
        require(std::popcount(mask)==1&&selected==expected,"independent bank-local candidate selection mismatch");
#endif
        ++checks;hits+=hit;shortHits+=shortPrediction;
        sameSlot+=train&&slot(pc)==slot(trainPc);
        if(train) {
            auto &entry=ledger[slot(trainPc)];const bool old=entry.valid&&entry.pc==trainPc;
            aliases+=entry.valid&&!old;
            if(separateLength)lengths[slot(trainPc)]=compressed;
            if(control||(DUT_C&&!DUT_TIMING)) {
                const unsigned counter=!old?(taken?2:1):taken?std::min(3U,entry.counter+1):
                    (entry.counter?entry.counter-1:0);
                entry={trainPc,target,counter,true,conditional,control,DUT_C&&compressed};
            }else if(old){entry.valid=false;++falseControls;}
        }
        if(invalidate){for(auto &entry:ledger)entry.valid=false;lengths.fill(false);++invalidations;}
    };
    // Every slot participates; exact full PCs reject aliases at arbitrary upper bits.
    const unsigned stride=DUT_C?2:4;
    for(unsigned i=0;i<DUT_ENTRIES;++i) {
        const uint64_t pc=0x80000000+stride*i;
        cycle(pc,pc,true,true,false,true,DUT_C,fit(0xfedcba9800000000ULL+4*i));
    }
    for(unsigned i=0;i<DUT_ENTRIES;++i) {
        const uint64_t pc=0x80000000+stride*i;
        cycle(pc,0,false,false,false,false,false,0);
        require(d.get_io$$hit(),"predictor did not use every configured slot");
    }
    if constexpr(separateLength) {
        // An ordinary instruction at a different full PC may change the
        // aliased length bit, but must not evict this not-taken branch.
        constexpr unsigned bits=std::countr_zero(unsigned(DUT_ENTRIES));
        const uint64_t pc=0x80000000, alias=pc+(uint64_t{1}<<(2+2*bits));
        require(slot(pc)==slot(alias),"directed length alias missed its slot");
        cycle(pc,0,false,false,false,false,false,0,true);
        cycle(pc,pc,true,true,true,false,false,pc+64);
        cycle(pc,alias,true,false,false,false,true,0);
        cycle(pc,0,false,false,false,false,false,0);
        require(d.get_io$$hit()&&d.get_io$$nextPc()==pc+2,
                "ordinary alias evicted branch or failed to train independent length");
        ++preservedBranches;
        cycle(pc,pc,true,false,false,false,false,0);
        cycle(pc,0,false,false,false,false,false,0);
        require(!d.get_io$$hit()&&d.get_io$$nextPc()==pc+4,
                "same-PC ordinary replacement failed to clear obsolete branch");
    }
    // Counter saturation, same-address lookup/train, false-code replacement and invalidate priority.
    for(unsigned i=0;i<40;++i)cycle(0x80000000,0x80000000,true,true,true,i<16||i>=32,DUT_C,0x80000100);
    cycle(0x80000000,0x80000000,true,false,false,false,DUT_C,0);
    cycle(0x80000000,0,false,false,false,false,false,0);
    cycle(0x80000000,0x80000000,true,true,false,true,false,0x80000100,true);
    cycle(0x80000000,0,false,false,false,false,false,0);
    // Consecutive invalidations, an overlapping allocation, and allocation in
    // the immediately following cycle must have the original visible epochs.
    for(unsigned round=0;round<32;++round) {
        const uint64_t pc=0x80000000+stride*(round%DUT_ENTRIES);
        cycle(pc,pc,true,true,true,true,DUT_C,pc+64);
        cycle(pc,pc,true,true,false,true,DUT_C,pc+96,true);
        cycle(pc,pc,true,true,false,true,DUT_C,pc+128,true);
        cycle(pc,pc,true,true,false,true,DUT_C,pc+160);
        cycle(pc,0,false,false,false,false,false,0);
        cycle(pc,pc,true,false,false,false,false,0);
        cycle(pc,0,false,false,false,false,false,0);
    }
    std::mt19937_64 random(0x42414e4b53504931ULL);
    for(unsigned i=0;i<18000;++i) {
        const uint64_t high=i%19==0?fit(random()&~uint64_t(DUT_ENTRIES*16-1)):0x80000000;
        const uint64_t trainPc=fit(high+stride*(random()%(4*DUT_ENTRIES)));
        const uint64_t pc=i%3==0?trainPc:fit(high+stride*(random()%(4*DUT_ENTRIES)));
        cycle(pc,trainPc,i%4!=0,random()%4!=0,random()%2,random()%2,DUT_C&&random()%2,
            fit(random()&~uint64_t(1)),i%173==0);
    }
    // Carry/wrap boundaries are independent of the table's physical tag encoding.
    for(unsigned bit=2;bit<DUT_XLEN;++bit) {
        const uint64_t pc=fit((uint64_t(1)<<bit)-stride);
        cycle(pc,pc,true,false,false,false,DUT_C,0,true);
        cycle(pc,pc,true,false,false,false,DUT_C,0);
        cycle(pc,0,false,false,false,false,false,0);
    }
    d.set_reset(1);d.set_io$$train$$valid(0);d.set_io$$invalidate(0);d.step();d.step();d.set_reset(0);
    for(auto &entry:ledger)entry.valid=false;
    lengths.fill(false);
    cycle(0x80000000,0,false,false,false,false,false,0);
    require(hits>30&&aliases>100&&invalidations>50&&sameSlot>100,"predictor coverage incomplete");
    if(DUT_C)require(shortHits>10,"compressed prediction coverage missing");
    if(separateLength)require(preservedBranches==1,"separate length/branch ownership coverage missing");
    if(!DUT_C||separateLength)require(falseControls>0,"false-control invalidation coverage missing");
    std::cout<<"I1_BANKED_PREDICTOR_PASS entries="<<DUT_ENTRIES<<" xlen="<<DUT_XLEN
        <<" C="<<DUT_C<<" hashed="<<DUT_HASHED<<" checks="<<checks<<" hits="<<hits
        <<" aliases="<<aliases<<" invalidations="<<invalidations<<" same_slot="<<sameSlot
        <<" preserved_branch_alias="<<preservedBranches
        <<" saturation_false_control_invalidate_warm_reset_candidates=PASS\n";
    return 0;
}catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 1;}}
