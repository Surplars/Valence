#pragma once
#include "worksets_symbols.h"
#include "capacity.hpp"
#include <array>
#include <cstdint>
#include <stdexcept>
#include <ostream>
namespace pfroi {
inline void require(bool ok,const char* message){if(!ok)throw std::runtime_error(message);}
constexpr uint64_t beginPc[2]={MMU_WRITE_BEGIN_PC,MMU_COPY_BEGIN_PC};
constexpr uint64_t readBeginPc=0xfff78c24ULL,readEndPc=0xfff79068ULL;
constexpr uint64_t endPc=MMU_WRITE_COPY_END_PC,tailPc=MMU_WRITE_COPY_TAIL_PC;
constexpr uint64_t casePc=MMU_WORKSETS_CASE_PC,donePc=MMU_SMOKE_DONE_PC;
constexpr uint64_t sv39=(8ULL<<60)|(0xfffd8000ULL>>12);
struct Sample {
    uint64_t cycle=0,pc[2]={},satp=0;unsigned commits=0,head=0,privilege=0;
    unsigned origin=0,events=0;bool reset=false;
    std::array<uint64_t,7> axi{}; // AR, AR-declared beats, R, AW, AW-declared beats, W, B
};
struct Counts {
    std::array<uint64_t,7> axi{};
    uint64_t cycles=0,origin[6]={},candidate=0,allocated=0,useful=0,error=0,busy=0;
    uint64_t missOwnerCycles=0,releaseOwnerCycles=0,missPeak=0,releasePeak=0;
    void add(const Sample& s){
        require(s.origin<64&&s.events<2048,"prefetch scalar width mismatch");
        for(unsigned pair=0;pair<3;pair++){
            const unsigned bits=(s.origin>>(pair*2))&3;
            require(bits!=3&&bool(bits)==bool((s.events>>pair)&1),"prefetch origin/event mismatch");
        }
        ++cycles;for(unsigned b=0;b<6;b++)origin[b]+=(s.origin>>b)&1;
        for(unsigned i=0;i<axi.size();i++)axi[i]+=s.axi[i];
        candidate+=s.events&1;allocated+=(s.events>>1)&1;useful+=(s.events>>2)&1;
        error+=(s.events>>3)&1;busy+=(s.events>>4)&1;
        const unsigned m=(s.events>>5)&7,r=(s.events>>8)&7;
        missOwnerCycles+=m;releaseOwnerCycles+=r;if(m>missPeak)missPeak=m;if(r>releasePeak)releasePeak=r;
    }
    void print(std::ostream& o)const{
        o<<" cycles="<<cycles;const char* names[]={"candidate_read","candidate_store","allocated_read","allocated_store","useful_read","useful_store"};
        for(unsigned i=0;i<6;i++)o<<" "<<names[i]<<"="<<origin[i];
        o<<" candidate="<<candidate<<" allocated="<<allocated<<" useful="<<useful<<" error="<<error<<" busy_cycles="<<busy
         <<" miss_owner_cycles="<<missOwnerCycles<<" release_owner_cycles="<<releaseOwnerCycles
         <<" miss_peak="<<missPeak<<" release_peak="<<releasePeak;
        const char* an[]={"axi_read_requests","axi_read_declared_beats","axi_read_beats","axi_write_requests","axi_write_declared_beats","axi_write_beats","axi_write_responses"};
        for(unsigned i=0;i<axi.size();i++)o<<" "<<an[i]<<"="<<axi[i];
    }
};
struct Region {
    Counts timed,tail;uint64_t beginOffer=0,beginAccepted=0,endOffer=0,endAccepted=0,tailOffer=0,tailAccepted=0;
};
// Board Test calls the observer after step(). Public commit valid is the current
// offer. Its effect is checked at the following step by exact ROB head advance.
// Events are captured with the offer and accounted only after that same edge.
struct Observer {
    bool on=false,pendingValid=false,terminal=false;Sample pending;Counts whole;std::array<Region,24> regions;
    unsigned firstIndex=0,lastIndex=0,index=0,phase=0; // 0 before timed, 1 timed, 2 flush tail, 3 verified-case wait
    explicit Observer(bool enabled,unsigned selected):on(enabled){require(selected==0||selected==6||selected==18||selected==19||selected==21,"exact selected formal case required");firstIndex=index=selected;lastIndex=index+1;}
    bool accept(const Sample& s,uint64_t accepted,unsigned actualHead){
        require(!s.reset&&accepted==s.cycle+1,"ROI acceptance is not next nonreset edge");
        whole.add(s);if(!on)require(!(s.origin&0x2a),"OFF store-origin prefetch event");
        bool caseAccepted=false,marker=false;
        for(unsigned lane=0;lane<2;lane++)if((s.commits>>lane)&1){
            const auto pc=s.pc[lane];
            if(index<lastIndex&&pc==(index<18?readBeginPc:beginPc[index%2])){
                require(phase==0,"ROI begin order/uniqueness");require(s.satp==((index<18?index/6:(index-18)/2)==0?0:sv39)&&s.privilege==1,"ROI not expected actual S-mode Bare/Sv39");
                auto& r=regions[index];r.beginOffer=s.cycle;r.beginAccepted=accepted;phase=1;marker=true;
            }else if(pc==beginPc[0]||pc==beginPc[1])require(false,"unexpected ROI begin marker");
            if(pc==(firstIndex<18?readEndPc:endPc)){require(index<lastIndex&&phase==1,"ROI end without begin");auto& r=regions[index];r.endOffer=s.cycle;r.endAccepted=accepted;phase=2;if(firstIndex<18){r.tailOffer=s.cycle;r.tailAccepted=accepted;phase=3;}marker=true;}
            if(firstIndex>=18&&pc==tailPc){require(index<lastIndex&&phase==2,"ROI flush tail order");auto& r=regions[index];r.tailOffer=s.cycle;r.tailAccepted=accepted;phase=3;marker=true;}
            if(pc==casePc){require(index<lastIndex&&phase==3,"case marker before ROI/tail completion");++index;phase=0;marker=true;caseAccepted=true;}
            if(pc==donePc){require(index==lastIndex&&phase==0&&!terminal,"terminal before all ROI cases");terminal=true;marker=true;}
        }
        if(marker){const unsigned n=(s.commits&1)+((s.commits>>1)&1);require(actualHead==capacity::advance(s.head,n),"offered marker did not advance accepted ROB head");}
        // Half-open time intervals: begin included, end excluded. End is the
        // beginning of the independently reported flush-tail window.
        if(index<lastIndex&&phase==1)regions[index].timed.add(s);
        if(index<lastIndex&&phase==2)regions[index].tail.add(s);
        return caseAccepted;
    }
    bool sample(const Sample& now){
        bool c=false;
        if(pendingValid){require(!now.reset,"reset after pending sample");c=accept(pending,now.cycle,now.head);}
        pending=now;pendingValid=!now.reset;return c;
    }
    void finish(std::ostream& o)const{
        require(terminal&&index==lastIndex&&phase==0,"ROI incomplete terminal");
        for(unsigned i=firstIndex;i<lastIndex;i++){
            const auto& r=regions[i];require(r.timed.cycles==r.endOffer-r.beginOffer&&r.tail.cycles==r.tailOffer-r.endOffer,"ROI cycle/marker interval mismatch");
            o<<"STORE_PF_ROI index="<<i<<" mode="<<(i<18?i/6:(i-18)/2)<<" op="<<(i<18?"READ":i%2?"COPY":"WRITE")<<" begin_offer="<<r.beginOffer<<" begin_accepted="<<r.beginAccepted
             <<" end_offer="<<r.endOffer<<" end_accepted="<<r.endAccepted<<" tail_offer="<<r.tailOffer<<" tail_accepted="<<r.tailAccepted;
            r.timed.print(o);o<<"\nSTORE_PF_TAIL index="<<i;r.tail.print(o);o<<"\n";
        }
        require(whole.axi[1]==whole.axi[2]&&whole.axi[4]==whole.axi[5]&&whole.axi[3]==whole.axi[6],"terminal AXI request/beat/response conservation");
        o<<"STORE_PF_WHOLE_BOOT diagnostic_only=1";whole.print(o);o<<"\n";
    }
};
}
