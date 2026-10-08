#include "TileLinkAxi4Bridge.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#ifndef MAX_BURST_BEATS
#define MAX_BURST_BEATS 16
#endif
#ifndef TL_SIZE_BITS
#define TL_SIZE_BITS 3
#endif
static void check(bool p,const char* msg) { if(!p) throw std::runtime_error(msg); }
static constexpr uint64_t base=0x80200000ULL, window=0x80000000ULL;
static uint64_t initial(uint64_t a) { return 0xabcdef1357902468ULL ^ (a*0x100100101ULL); }
struct Tx { unsigned n,beats,source; uint64_t addr; bool write,error,reject; std::vector<uint64_t> expected; };
struct Read { unsigned tx,id,beat,ready; };
static uint64_t payload(unsigned n,unsigned b) { return 0x1248124812481248ULL ^ (uint64_t(n)<<32) ^ b; }
static unsigned mask(unsigned n,unsigned b) { return n%8==6 ? 0xff : (n+b)%3==0 ? 0x55 : 0xff; }
static unsigned size(unsigned b) { unsigned s=3; while(b>1) {++s;b/=2;} return s; }
static void reset(STileLinkAxi4Bridge& d) {
    d.set_io$$tl$$a$$valid(0); d.set_io$$tl$$c$$valid(0); d.set_io$$tl$$e$$valid(0);
    d.set_io$$tl$$d$$ready(0); d.set_io$$axi$$ar$$ready(0); d.set_io$$axi$$aw$$ready(0);
    d.set_io$$axi$$w$$ready(0); d.set_io$$axi$$r$$valid(0); d.set_io$$axi$$b$$valid(0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
}
static void run(STileLinkAxi4Bridge& d,bool mixed,bool stress,const std::string& negative,
                unsigned abortCycle=0) {
    constexpr unsigned total=96;
    std::vector<Tx> tx;
    std::map<uint64_t,uint64_t> oracle,device;
    auto read=[](auto& memory,uint64_t a) { auto it=memory.find(a);return it==memory.end()?initial(a):it->second; };
    auto write=[&](auto& memory,uint64_t a,unsigned n,unsigned b) {
        uint64_t v=read(memory,a),p=payload(n,b); for(unsigned k=0;k<8;++k)
            if(mask(n,b)&(1U<<k)) v=(v&~(0xffULL<<(8*k)))|(p&(0xffULL<<(8*k)));
        memory[a]=v;
    };
    for(unsigned i=0;i<total;++i) {
        const unsigned beats=stress?(1U<<(i%((1U<<TL_SIZE_BITS)-3))):8;
        const bool wr=mixed&&(i+i/16)%2==1, err=stress&&i%17==9, outside=stress&&(i%23==13||i==31);
        const bool rej=outside||beats>MAX_BURST_BEATS;
        // Repeated overlapping locations deliberately exercise read-after-write hazards.
        const unsigned location=i>=16&&i%7==0 ? (i-1)%16 : i>=16&&i%13==0 ? (i-2)%16 : i%16;
        const uint64_t offset=stress&&i==47 ? window-uint64_t(beats)*8 : location*(1ULL<<((1U<<TL_SIZE_BITS)-1));
        Tx t{i,beats,stress&&i%5==1?(i-1)%8:i%8,(stress&&i==31 ? 0xffffffffffffff80ULL : base+(outside?window:offset)),wr,err,rej,{}};
        for(unsigned b=0;b<beats;++b) {
            if(wr&&!rej) write(oracle,offset+8*b,i,b);
            t.expected.push_back(err||rej?0:read(oracle,offset+8*b));
        }
        tx.push_back(t);
    }
    unsigned next=0,abeat=0,completed=0,dbeat=0,cycle=0,peak=0,reordered=0;
    std::optional<unsigned> dOwner; unsigned outOfOrderD=0;
    unsigned arCount=0,awCount=0,rCount=0,bCount=0,dCount=0,sourceStalls=0;
    std::deque<unsigned> accepted;
    std::vector<Read> reads;
    std::optional<Read> heldR;
    std::optional<unsigned> writeTx,writeId;
    struct WriteOwner { unsigned tx,id,beat,due; };
    std::deque<WriteOwner> pendingWrites, pendingB;
    std::optional<unsigned> heldB;
    unsigned mixedPeak=0, writePeak=0, bReordered=0, rawStalls=0,warStalls=0,wawStalls=0;
    unsigned wbeat=0,bReadyAt=0;
    bool bPending=false,aHeld=false;
    std::array<bool,8> sourceLive{};
    std::array<bool,total> issued{};
    std::optional<std::tuple<uint64_t,unsigned,unsigned,unsigned>> stalledAr,stalledAw;
    std::optional<std::tuple<uint64_t,unsigned,bool>> stalledW;
    std::optional<std::tuple<uint64_t,unsigned,unsigned,unsigned,bool,bool>> stalledD;
    for(;cycle<500000&&completed<total;++cycle) {
        const bool arReady=!stress||cycle%7<4,awReady=!stress||cycle%9<4;
        const bool wReady=!pendingWrites.empty()&&(!stress||cycle%5<3),dReady=!stress||(cycle%19<9&&cycle%131<110);
        if(!heldR) {
            // Newest eligible ID first, but fixed per-beat hold once RVALID is asserted.
            for(auto it=reads.rbegin();it!=reads.rend();++it) if(cycle>=it->ready) {heldR=*it;break;}
        }
        const bool aValid=next<total&&(!stress||abeat==0||cycle%7!=3||aHeld);
        d.set_io$$tl$$a$$valid(aValid);
        const auto& a=tx.at(std::min(next,total-1));
        d.set_io$$tl$$a$$bits$$opcode(a.write?(a.n%8==6?0:1):4); d.set_io$$tl$$a$$bits$$param(0);
        d.set_io$$tl$$a$$bits$$size(size(a.beats));d.set_io$$tl$$a$$bits$$source(negative=="--bad-write-control"&&a.write&&a.beats>MAX_BURST_BEATS&&abeat==2 ? (a.source^1) : a.source);
        d.set_io$$tl$$a$$bits$$address(negative=="--bad-boundary" ? base+4096-4 : a.addr);d.set_io$$tl$$a$$bits$$mask(a.write?mask(a.n,abeat):255);
        d.set_io$$tl$$a$$bits$$data(payload(a.n,abeat));d.set_io$$tl$$a$$bits$$corrupt(0);
        d.set_io$$tl$$d$$ready(dReady);d.set_io$$axi$$ar$$ready(arReady);
        d.set_io$$axi$$aw$$ready(awReady);d.set_io$$axi$$w$$ready(wReady);
        d.set_io$$axi$$r$$valid(bool(heldR));
        d.set_io$$axi$$r$$bits$$id(negative=="--bad-id"?15:heldR?heldR->id:0);
        d.set_io$$axi$$r$$bits$$data(heldR?read(device,tx[heldR->tx].addr-base+8*heldR->beat):0);
        d.set_io$$axi$$r$$bits$$resp(heldR&&tx[heldR->tx].error&&heldR->beat==tx[heldR->tx].beats-1?2:0);
        d.set_io$$axi$$r$$bits$$last(heldR&&(negative=="--bad-last-late"?false:negative=="--bad-last"?heldR->beat==0:heldR->beat+1==tx[heldR->tx].beats));
        if (!heldB) for(auto it=pendingB.rbegin();it!=pendingB.rend();++it)
            if(cycle>=it->due) {heldB=it->id;break;}
        auto selectedB=std::find_if(pendingB.begin(),pendingB.end(),[&](auto& b){return heldB&&b.id==*heldB;});
        const bool bv=selectedB!=pendingB.end();
        d.set_io$$axi$$b$$valid(bv);d.set_io$$axi$$b$$bits$$id(negative=="--bad-bid"?15:bv?selectedB->id:0);
        d.set_io$$axi$$b$$bits$$resp(bv&&tx[selectedB->tx].error?2:0);
        d.step();
        auto ar=std::make_tuple(uint64_t(d.get_io$$axi$$ar$$bits$$addr()),unsigned(d.get_io$$axi$$ar$$bits$$id()),
            unsigned(d.get_io$$axi$$ar$$bits$$len()),unsigned(d.get_io$$axi$$ar$$bits$$size()));
        auto aw=std::make_tuple(uint64_t(d.get_io$$axi$$aw$$bits$$addr()),unsigned(d.get_io$$axi$$aw$$bits$$id()),
            unsigned(d.get_io$$axi$$aw$$bits$$len()),unsigned(d.get_io$$axi$$aw$$bits$$size()));
        auto w=std::make_tuple(uint64_t(d.get_io$$axi$$w$$bits$$data()),unsigned(d.get_io$$axi$$w$$bits$$strb()),bool(d.get_io$$axi$$w$$bits$$last()));
        auto out=std::make_tuple(uint64_t(d.get_io$$tl$$d$$bits$$data()),unsigned(d.get_io$$tl$$d$$bits$$source()),
            unsigned(d.get_io$$tl$$d$$bits$$size()),unsigned(d.get_io$$tl$$d$$bits$$opcode()),
            bool(d.get_io$$tl$$d$$bits$$denied()),bool(d.get_io$$tl$$d$$bits$$corrupt()));
        const bool arv=d.get_io$$axi$$ar$$valid(),awv=d.get_io$$axi$$aw$$valid(),wv=d.get_io$$axi$$w$$valid(),dv=d.get_io$$tl$$d$$valid();
        if(stalledAr)check(arv&&ar==*stalledAr,"AR unstable");if(stalledAw)check(awv&&aw==*stalledAw,"AW unstable");
        if(stalledW)check(wv&&w==*stalledW,"W unstable");if(stalledD)check(dv&&out==*stalledD,"D unstable");
        stalledAr=arv&&!arReady?std::optional{ar}:std::nullopt;stalledAw=awv&&!awReady?std::optional{aw}:std::nullopt;
        stalledW=wv&&!wReady?std::optional{w}:std::nullopt;stalledD=dv&&!dReady?std::optional{out}:std::nullopt;
        aHeld=aValid&&!d.get_io$$tl$$a$$ready();
        if(aValid&&d.get_io$$tl$$a$$ready()) {
            if(abeat==0) {
                check(!sourceLive[a.source],"TL source reused before final D");
                for(unsigned old:accepted) if(a.write||tx[old].write)
                    check(a.addr+uint64_t(a.beats)*8<=tx[old].addr || tx[old].addr+uint64_t(tx[old].beats)*8<=a.addr,
                        "overlapping RAW/WAR/WAW crossed live owner");
                accepted.push_back(next);sourceLive[a.source]=true;peak=std::max(peak,unsigned(accepted.size()));
            }
            ++abeat;if(!a.write||abeat==a.beats){++next;abeat=0;}
        } else if(next<total&&sourceLive[a.source])++sourceStalls;
        if(aValid&&!d.get_io$$tl$$a$$ready()&&abeat==0)for(unsigned old:accepted) {
            if(a.addr<tx[old].addr+uint64_t(tx[old].beats)*8 && tx[old].addr<a.addr+uint64_t(a.beats)*8) {
                rawStalls+=!a.write&&tx[old].write;warStalls+=a.write&&!tx[old].write;wawStalls+=a.write&&tx[old].write;
            }
        }
        auto owner=[&](uint64_t addr,bool wr) -> unsigned {
            for(unsigned n:accepted) if(!issued[n]&&tx[n].addr-base==addr&&tx[n].write==wr&&!tx[n].reject) return n;
            throw std::runtime_error("AXI address without unissued TL owner");
        };
        if(arv&&arReady) {
            unsigned n=owner(std::get<0>(ar),false),id=std::get<1>(ar);
            check(std::get<2>(ar)+1==tx[n].beats&&std::get<3>(ar)==3,"AR attributes mismatch");
            for(const auto& q:reads)check(q.id!=id,"live AXI ID reused");
            issued[n]=true;reads.push_back({n,id,0,cycle+32+(stress&&n%4==0?35:0)});++arCount;
        }
        if(awv&&awReady) {

            unsigned n=owner(std::get<0>(aw),true);
            check(std::get<2>(aw)+1==tx[n].beats&&std::get<3>(aw)==3,"AW attributes mismatch");

            issued[n]=true;pendingWrites.push_back({n,std::get<1>(aw),0,0});++awCount;
        }
        if(wv&&wReady) {
            // AXI permits W before AW; this harness deliberately withholds WREADY until AW.
            check(!pendingWrites.empty(),"write data lacks AW owner");auto& owner=pendingWrites.front();unsigned n=owner.tx;wbeat=owner.beat;
            check(std::get<0>(w)==payload(n,wbeat)&&std::get<1>(w)==mask(n,wbeat)&&
                std::get<2>(w)==(wbeat+1==tx[n].beats),"W payload mismatch");
            write(device,tx[n].addr-base+8*wbeat,n,wbeat);++owner.beat;
            if(owner.beat==tx[n].beats){owner.due=cycle+32+(owner.id%2?0:37);pendingB.push_back(owner);pendingWrites.pop_front();}
        }
        if(heldR&&d.get_io$$axi$$r$$ready()) {
            auto it=std::find_if(reads.begin(),reads.end(),[&](const Read& r){return r.id==heldR->id;});
            check(it!=reads.end(),"R lost owner");
            if(!accepted.empty()&&it->tx!=accepted.front())++reordered;
            ++it->beat;++rCount;
            if(it->beat==tx[it->tx].beats)reads.erase(it);
            heldR.reset();
        }
        if(bv&&d.get_io$$axi$$b$$ready()){
            // W may append to the deque this cycle; reacquire the iterator.
            auto b=std::find_if(pendingB.begin(),pendingB.end(),[&](auto& q){return heldB&&q.id==*heldB;});
            bReordered += b!=pendingB.begin();pendingB.erase(b);heldB.reset();++bCount;
        }
        writePeak=std::max(writePeak,unsigned(pendingWrites.size()+pendingB.size()));
        mixedPeak=std::max(mixedPeak,std::min(unsigned(reads.size()),unsigned(pendingWrites.size()+pendingB.size())));
        if(dv&&dReady) {
            check(!accepted.empty(),"duplicate TL D");
#ifdef UNORDERED_TL
            if(!dOwner){auto owner=std::find_if(accepted.begin(),accepted.end(),[&](unsigned n){return tx[n].source==std::get<1>(out);});check(owner!=accepted.end(),"D source has no pending owner");dOwner=*owner;outOfOrderD+=*owner!=accepted.front();}
            auto& t=tx[*dOwner];
#else
            auto& t=tx[accepted.front()];
#endif
            const bool err=t.error||t.reject;
            if(t.write)check(next>t.n,"write D returned before every A beat drained");
            check(std::get<1>(out)==t.source&&std::get<2>(out)==size(t.beats)&&
                std::get<3>(out)==(t.write?0:1)&&std::get<4>(out)==err&&
                std::get<5>(out)==(!t.write&&err),"TL D metadata/order/error mismatch");
            check(std::get<0>(out)==((t.write?0:t.expected[dbeat])^(negative=="--inject-data"?1ULL:0ULL)),"independent TL data oracle mismatch");
            if(!t.write)for(const auto& q:reads)check(q.tx!=t.n,"partial read burst escaped before error known");
            ++dbeat;++dCount;
            if(t.write||dbeat==t.beats){sourceLive[t.source]=false;
#ifdef UNORDERED_TL
                auto owner=std::find(accepted.begin(),accepted.end(),*dOwner);check(owner!=accepted.end(),"D owner vanished");accepted.erase(owner);dOwner.reset();
#else
                accepted.pop_front();
#endif
                ++completed;dbeat=0;}
        }
        if(abortCycle && (abortCycle==90 ? (a.write&&a.beats>MAX_BURST_BEATS&&abeat>0&&abeat<a.beats) : abortCycle==80 ? (cycle>=abortCycle&&!pendingWrites.empty()&&pendingWrites.front().beat>0&&pendingWrites.front().beat<tx[pendingWrites.front().tx].beats) : cycle==abortCycle)) {
            check(!accepted.empty(),"reset case has no live transaction");
            reset(d);std::cout<<"RESET_FLUSH_PASS cycle="<<cycle<<" live="<<accepted.size()<<"\n";return;
        }
    }
    check(completed==total&&accepted.empty()&&reads.empty()&&!heldR&&pendingWrites.empty()&&pendingB.empty()&&!heldB,"lost transaction or deadlock");
    unsigned expectedAr=0,expectedAw=0,expectedR=0,expectedD=0,oversizeReads=0,oversizeWrites=0;
    for(const auto& t:tx)if(t.beats>MAX_BURST_BEATS){if(t.write)++oversizeWrites;else ++oversizeReads;}
    for(const auto& t:tx){expectedD+=t.write?1:t.beats;if(!t.reject){if(t.write)++expectedAw;else{++expectedAr;expectedR+=t.beats;}}}
    check(arCount==expectedAr&&awCount==expectedAw&&rCount==expectedR&&bCount==expectedAw&&dCount==expectedD,"lost or duplicated AXI/TL beats");
    if(stress&&MAX_BURST_BEATS<16){check(oversizeReads>0,"oversize Get coverage missing");if(mixed)check(oversizeWrites>0,"oversize Put coverage missing");}
    if(stress)check(sourceStalls>0,"same-source backpressure not exercised");
#if defined(REQUIRE_MIXED)
    if(mixed&&!stress)check(mixedPeak>=2&&writePeak>=2,"two reads and two writes never overlapped");
#endif
#ifdef REQUIRE_MIXED
    if(mixed&&!stress)check(rawStalls&&warStalls&&wawStalls,"RAW/WAR/WAW stall coverage missing");
#endif
    std::cout << "MIXED_HAZARDS raw="<<rawStalls<<" war="<<warStalls<<" waw="<<wawStalls<<std::endl;
    std::cout << "MIXED_IDS write_peak=" << writePeak << " paired_read_write_peak=" << mixedPeak << " b_reordered=" << bReordered << std::endl;
    std::cout<<"TL_D_COMPLETION out_of_order="<<outOfOrderD<<std::endl;
    std::cout<<"OUTSTANDING_PASS mode="<<(mixed?"mixed":"reads")<<" stress="<<stress
        <<" cycles="<<cycle<<" transactions="<<total<<" dbeats="<<dCount<<" peak="<<peak<<" reordered="<<reordered<<" oversize_reads="<<oversizeReads<<" oversize_writes="<<oversizeWrites<<"\n";
}
int main(int argc,char**argv) {
    try {
        STileLinkAxi4Bridge d;reset(d);std::string arg=argc>1?argv[1]:"";
        if(!arg.empty()){run(d,arg=="--bad-write-control"||arg=="--bad-bid",true,arg);throw std::runtime_error("negative test not rejected");}
        run(d,false,false,"");reset(d);run(d,true,false,"");reset(d);
        run(d,false,true,"");reset(d);run(d,true,true,"");reset(d);
        run(d,false,true,"",20);run(d,true,true,"");reset(d);
        run(d,true,true,"",80);run(d,false,true,"");
        if(MAX_BURST_BEATS<16){reset(d);run(d,true,true,"",90);run(d,false,true,"");}
        std::cout<<"OUTSTANDING_ALL_PASS\n";return 0;
    } catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
}
