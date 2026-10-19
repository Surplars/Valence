// Independent full-PC ledger; no DUT tag/decode/control helpers.
#include "FiveStageBranchPredictor.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
struct Entry {
    uint64_t pc=0,target=0;
    unsigned counter=0;
    bool valid=false,conditional=false,control=false,compressed=false;
};
static void need(bool p,const char* message) { if(!p) throw std::runtime_error(message); }
static unsigned index(uint64_t pc) {
    // Architecture-independent documented storage policy for this 128-entry
    // profile. Full PCs, NOT a duplicated hardware tag comparison, own slots.
    return unsigned((pc/4)%128) ^ ((pc&2)?64:0);
}
int main(int argc,char** argv) { try {
    SFiveStageBranchPredictor d;
    bool mutate=argc>1&&std::string(argv[1])=="--wrong-target";
    std::array<Entry,128> ledger{};
    d.set_reset(1); d.set_io$$train$$valid(0); d.set_io$$invalidate(0); d.set_io$$pc(0x80000000);
    d.step(); d.step(); d.set_reset(0);
    unsigned checks=0,alias=0,length2=0,full32Hits=0,full16Hits=0;
    auto cycle=[&](uint64_t pc,uint64_t trainPc,bool train,bool cf,bool conditional,bool taken,
                   bool compressed,uint64_t target,bool invalidate=false) {
        d.set_io$$pc(pc); d.set_io$$train$$valid(train); d.set_io$$train$$bits$$pc(trainPc);
        d.set_io$$train$$bits$$target(target); d.set_io$$train$$bits$$controlFlow(cf);
        d.set_io$$train$$bits$$conditional(conditional); d.set_io$$train$$bits$$taken(taken);
        d.set_io$$train$$bits$$compressed(compressed); d.set_io$$invalidate(invalidate);
        d.step();
        auto look=ledger[index(pc)]; bool hit=look.valid&&look.pc==pc;
        uint64_t expected=hit&&look.control&&(!look.conditional||look.counter>=2)?look.target:
            pc+(hit&&look.compressed?2:4);
        if(mutate&&hit) expected^=2;
        need(bool(d.get_io$$hit())==hit&&d.get_io$$nextPc()==expected,
             "independent C folded BTB full-PC/length/target oracle");
        ++checks; length2+=hit&&look.compressed;
        if(train) {
            auto &entry=ledger[index(trainPc)]; bool old=entry.valid&&entry.pc==trainPc;
            alias+=entry.valid&&!old;
            unsigned count=!old?(taken?2:1):taken?(entry.counter==3?3:entry.counter+1):
                (entry.counter==0?0:entry.counter-1);
            entry={trainPc,target,count,true,conditional,cf,compressed};
        }
        if(invalidate) for(auto &entry:ledger) entry.valid=false;
    };
    // Both wholly32-bit and dense16-bit footprints use ALL128 entries,
    // without conflating the two halfwords or increasing memory capacity.
    for(unsigned stride:{4U,2U}) {
        cycle(0x80000000,0,false,false,false,false,false,0,true);
        for(unsigned i=0;i<128;++i) {
            uint64_t pc=0x80000000+stride*i;
            cycle(pc,pc,true,true,false,true,stride==2,0x80010000+4*i);
        }
        for(unsigned i=0;i<128;++i) {
            uint64_t pc=0x80000000+stride*i;
            cycle(pc,0,false,false,false,false,false,0);
            need(d.get_io$$hit(),"C BTB did not use all128 slots");
            if(stride==4)++full32Hits;else ++full16Hits;
            cycle(pc+512,0,false,false,false,false,false,0); // exact full tag must reject alias
            need(!d.get_io$$hit(),"C BTB false hit at upper-address alias");
        }
    }
    // Hit/miss and compressed-length selection across every carry boundary,
    // including XLEN wrap. All expected increments use host uint64 arithmetic.
    for(unsigned bit=2;bit<64;++bit) for(unsigned back=0;back<4;++back) {
        uint64_t pc=((uint64_t{1}<<bit)-2*back)&~uint64_t{1};
        cycle(pc,0,false,false,false,false,false,0,true);
        cycle(pc,0,false,false,false,false,false,0);
        cycle(pc,pc,true,false,false,false,true,0);
        cycle(pc,0,false,false,false,false,false,0);
        cycle(pc,pc,true,false,false,false,false,0);
        cycle(pc,0,false,false,false,false,false,0);
    }
    std::mt19937_64 rng(0x48414c46574f5244ULL);
    for(unsigned n=0;n<16000;++n) {
        uint64_t pc=0x80000000+2*(rng()%512), trainPc=0x80000000+2*(rng()%512);
        cycle(pc,trainPc,rng()%3,rng()%3,rng()%2,rng()%2,rng()%2,
              0x80010000+2*(rng()%512),n%173==0);
    }
    need(full32Hits==128&&full16Hits==128&&alias>1000&&length2>500,"C predictor coverage");
    std::cout<<"I1_C_PREDICTOR_PASS checks="<<checks<<" full32_hits="<<full32Hits
        <<" full16_hits="<<full16Hits<<" aliases="<<alias<<" length2="<<length2
        <<" full_pc_saturation_invalidate_false_control=PASS\n";
    return 0;
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;} }
