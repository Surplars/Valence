// Standalone test of the exact benchmark host law; no generated DUT is used.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
static void check(bool p,const char *s){if(!p)throw std::runtime_error(s);}
#include "board_ddr_benchmark.h"
struct AxiStub {
    bool arValid=false,awValid=false,wValid=false,rReady=true,bReady=true,wLast=false;
    bool arReady=false,awReady=false,wReady=false,rValid=false,rLast=false,bValid=false;
    unsigned arId=0,awId=0,rId=0,bId=0,rResp=0,bResp=0;
    uint32_t arAddress=0,awAddress=0;uint64_t wData=0,rData=0;
#define GET(n,e) auto get_io$$ddrAxi$$##n(){return e;}
    GET(ar$$valid,arValid) GET(ar$$bits$$addr,arAddress) GET(ar$$bits$$id,arId)
    GET(ar$$bits$$len,15U) GET(ar$$bits$$size,3U) GET(ar$$bits$$burst,1U)
    GET(aw$$valid,awValid) GET(aw$$bits$$addr,awAddress) GET(aw$$bits$$id,awId)
    GET(aw$$bits$$len,15U) GET(aw$$bits$$size,3U) GET(aw$$bits$$burst,1U)
    GET(w$$valid,wValid) GET(w$$bits$$last,wLast) GET(w$$bits$$data,wData) GET(w$$bits$$strb,0x5aU)
    GET(r$$ready,rReady) GET(b$$ready,bReady)
#undef GET
#define SET(n,f) template<class T> void set_io$$ddrAxi$$##n(T v){f=v;}
    SET(ar$$ready,arReady) SET(aw$$ready,awReady) SET(w$$ready,wReady)
    SET(r$$valid,rValid) SET(r$$bits$$data,rData) SET(r$$bits$$id,rId)
    SET(r$$bits$$resp,rResp) SET(r$$bits$$last,rLast)
    SET(b$$valid,bValid) SET(b$$bits$$id,bId) SET(b$$bits$$resp,bResp)
#undef SET
};
static uint64_t readWord(unsigned id,unsigned beat){return 0xabcdef0000000000ULL+(id<<16)+beat;}
static uint64_t writeWord(unsigned id,unsigned beat){return 0x1234567800000000ULL+(id<<16)+beat;}
int main(int argc,char **argv){try{
    const std::string negative=argc>1?argv[1]:"";
    DdrModel memory;AxiStub d;
    for(unsigned i=0;i<2;++i)for(unsigned b=0;b<16;++b){
        memory.memory[0x1000+i*128+b*8]=readWord(i,b);memory.memory[0x8000+i*128+b*8]=~0ULL;
    }
    unsigned issuedRead=0,issuedWrite=0,writeId=0,writeBeat=0,duplex=0;
    std::array<unsigned,2> readBeats{},writeReplies{};
    bool heldR=false,heldB=false;uint64_t heldData=0;unsigned heldRid=0,heldRresp=0,heldBid=0,heldBresp=0;bool heldLast=false;
    unsigned rHeldCycles=0,bHeldCycles=0;
    for(unsigned cycle=0;cycle<500;++cycle){
        memory.drive(d,cycle);
        d.rReady=cycle%9!=4&&cycle%9!=5;d.bReady=cycle%13!=6&&cycle%13!=7;
        if(heldR){++rHeldCycles;check(d.rValid&&d.rData==heldData&&d.rId==heldRid&&d.rResp==heldRresp&&d.rLast==heldLast,"DDR held R payload changed");}
        if(heldB){++bHeldCycles;check(d.bValid&&d.bId==heldBid&&d.bResp==heldBresp,"DDR held B payload changed");}
        d.arValid=issuedRead<2;d.arId=issuedRead;d.arAddress=0x1000+issuedRead*128;
        d.awValid=issuedWrite<2;d.awId=negative=="--duplicate-write-id"?0:issuedWrite;d.awAddress=0x8000+issuedWrite*128;
        d.wValid=writeId<issuedWrite;d.wData=writeWord(writeId,writeBeat);d.wLast=writeBeat==15;
        if(negative=="--wlast"&&d.wValid)d.wLast=!d.wLast;
        const bool ar=d.arValid&&d.arReady,aw=d.awValid&&d.awReady,w=d.wValid&&d.wReady,r=d.rValid&&d.rReady,b=d.bValid&&d.bReady;
        if(r){
            check(d.rId<2&&readBeats[d.rId]<16,"DDR independent read ID/beat owner");
            check(d.rData==(readWord(d.rId,readBeats[d.rId])^(negative=="--read-byte"?1:0)),"DDR independent read bytes");
            check(d.rResp==0&&d.rLast==(readBeats[d.rId]==15),"DDR independent read response/last");
            ++readBeats[d.rId];
        }
        if(b){check(d.bId<2&&d.bResp==0&&writeReplies[d.bId]++==0,"DDR independent B owner/error");}
        duplex+=r&&w;
        heldR=d.rValid&&!d.rReady;heldData=d.rData;heldRid=d.rId;heldRresp=d.rResp;heldLast=d.rLast;
        heldB=d.bValid&&!d.bReady;heldBid=d.bId;heldBresp=d.bResp;
        memory.sample(d);
        issuedRead+=ar;issuedWrite+=aw;
        if(w&&++writeBeat==16){writeBeat=0;++writeId;}
        if(readBeats[0]==16&&readBeats[1]==16&&writeReplies[0]==1&&writeReplies[1]==1)break;
    }
    check(issuedRead==2&&issuedWrite==2&&writeId==2&&readBeats[0]==16&&readBeats[1]==16&&writeReplies[0]==1&&writeReplies[1]==1,"DDR all independent owners drain");
    check(memory.pendingReads.empty()&&memory.pendingWrites.empty()&&memory.pendingB.empty(),"DDR residual owner");
    for(unsigned i=0;i<2;++i)for(unsigned b=0;b<16;++b){
        uint64_t expected=~0ULL;const auto value=writeWord(i,b);
        for(unsigned lane=0;lane<8;++lane)if((0x5aU>>lane)&1)expected=(expected&~(0xffULL<<(lane*8)))|(value&(0xffULL<<(lane*8)));
        check(memory.memory.at(0x8000+i*128+b*8)==expected,"DDR write byte-lane mask");
    }
    check(duplex>0&&memory.mixedCycles>0&&rHeldCycles>0&&bHeldCycles>0,"DDR independent concurrent R/W was not exercised");
    std::cout<<"DDR_INDEPENDENT_HOST_PASS simultaneous_rw_fire="<<duplex<<" mixed_owner_cycles="<<memory.mixedCycles
        <<" held_r_cycles="<<rHeldCycles<<" held_b_cycles="<<bHeldCycles<<" reads=2 writes=2 r_beats=32 w_beats=32 b_responses=2\n";
    return 0;
}catch(const std::exception &e){std::cerr<<"DDR_INDEPENDENT_HOST_FAIL "<<e.what()<<"\n";return 1;}}
