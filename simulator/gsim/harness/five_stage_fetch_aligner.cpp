#ifdef I1_SCALAR_PARCEL_FIXTURE
#include "I1FetchParcelTimingFixture.h"
using SFiveStageFetchAligner = SI1FetchParcelTimingFixture;
#else
#include "FiveStageFetchAligner.h"
#endif
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
#ifndef I1_TIMING_CUTS
#define I1_TIMING_CUTS 0
#endif
static constexpr unsigned WORD=DUT_XLEN/8;
static void need(bool b,const char *s) { if(!b) throw std::runtime_error(s); }
struct Test {
    SFiveStageFetchAligner d; std::map<uint64_t,uint8_t> bytes;
    struct Pending { uint64_t pc,data,due; bool error,page,span; };
    std::optional<Pending> pending; std::optional<std::array<uint64_t,3>> held;
    std::optional<std::array<uint64_t,5>> heldResponse;
    std::mt19937_64 random{0x50415243454c};
    uint64_t cycle=0,cases=0,requests=0,errorPc=~0ULL;
    bool faultPage=false,fullSpan=true;
    bool killPending=false;
    Test() {
        d.set_reset(1); d.set_io$$request$$valid(0); d.set_io$$response$$ready(0);
        d.set_io$$memoryRequest$$ready(0); d.set_io$$memoryResponse$$valid(0);
#if I1_TIMING_CUTS
        d.set_io$$invalidate(0);
#endif
        d.step(); d.step(); d.set_reset(0);
    }
    uint64_t load(uint64_t pc) {
        uint64_t value=0; pc &= ~(WORD-1ULL);
        for(unsigned j=0;j<WORD;++j) value|=uint64_t(bytes[pc+j])<<(8*j);
        return value;
    }
    void step(bool ready) {
        bool mr=!pending && cycle%4!=1, mv=pending && cycle>=pending->due;
        d.set_io$$response$$ready(ready); d.set_io$$memoryRequest$$ready(mr);
        d.set_io$$memoryResponse$$valid(mv);
        d.set_io$$memoryResponse$$bits$$data(pending?pending->data:0);
        d.set_io$$memoryResponse$$bits$$error(pending&&pending->error);
        d.set_io$$memoryResponse$$bits$$pageFault(pending&&pending->page);
        d.set_io$$memoryResponse$$bits$$fetchSpan(pending&&pending->span);
#ifdef I1_CACHED_PARCEL_PREDECODE
        // Wire encoding only; the independent byte/fault oracle below is unchanged.
        uint64_t classes=0, bits=pending?pending->data:0;
        for(unsigned lane=0;lane<WORD/2;++lane) {
            unsigned prefix=(bits>>(lane*16))&31;
            classes|=uint64_t((prefix&3)==3 && prefix!=31)<<lane;
            classes|=uint64_t((prefix&3)!=3)<<(4+lane);
        }
        d.set_io$$memoryResponse$$bits$$parcelClasses(classes);
#endif
#if I1_TIMING_CUTS
        d.set_io$$invalidate(killPending && pending && !mv);
        if(killPending && pending && !mv) killPending=false;
#endif
        d.step(); ++cycle;
        std::array<uint64_t,3> req{d.get_io$$memoryRequest$$bits$$address(),
            d.get_io$$memoryRequest$$bits$$size(),d.get_io$$memoryRequest$$bits$$write()};
        if(held) need(d.get_io$$memoryRequest$$valid() && req==*held,"C parcel offer changed under stalls");
        held.reset(); if(d.get_io$$memoryRequest$$valid()&&!mr) held=req;
        std::array<uint64_t,5> rsp{d.get_io$$response$$bits$$instruction(),d.get_io$$response$$bits$$error(),
            d.get_io$$response$$bits$$pageFault(),d.get_io$$response$$bits$$compressed(),
            d.get_io$$response$$bits$$secondHalfFault()};
        if(heldResponse) need(d.get_io$$response$$valid()&&rsp==*heldResponse,"C assembly reply changed under stalls");
        heldResponse.reset(); if(d.get_io$$response$$valid()&&!ready) heldResponse=rsp;
        if(mv&&d.get_io$$memoryResponse$$ready()) pending.reset();
        if(mr&&d.get_io$$memoryRequest$$valid()) {
            need(!pending && req[1]==1 && !req[2] && !(req[0]&1),"C parcel geometry/owner oracle");
            pending=Pending{req[0],load(req[0]),cycle+1+random()%9,req[0]==errorPc,
                req[0]==errorPc&&faultPage,fullSpan}; ++requests;
        }
    }
    void transact(uint64_t pc,uint32_t ins,bool span,bool firstError=false,bool secondError=false,
                  bool page=false,bool mutate=false,bool invalidate=true,int expectedParcels=-1) {
#if I1_TIMING_CUTS
        // Tests rewrite code/permission between unrelated cases. Invalidate
        // that change explicitly; directed SAME-word cases below retain it.
        if(invalidate) {
            d.set_io$$request$$valid(0); d.set_io$$invalidate(1);
            d.set_io$$response$$ready(0); d.set_io$$memoryResponse$$valid(0);
            d.step(); ++cycle; d.set_io$$invalidate(0);
        }
#endif
        for(unsigned j=0;j<4;++j) bytes[pc+j]=ins>>(8*j);
        fullSpan=span; errorPc=firstError?pc:secondError?pc+2:~0ULL; faultPage=page;
        bool comp=(ins&3)!=3, longIns=(ins&31)==31;
        bool split=!firstError&&!comp&&!longIns && (!span || pc%WORD>WORD-4);
        bool error=firstError || split&&secondError;
        uint32_t expected=comp||longIns?ins&65535:ins;
        if(mutate) expected^=1;
        uint64_t before=requests; bool accepted=false; unsigned stalls=0;
        d.set_io$$request$$bits(pc);
        for(unsigned n=0;n<300;++n) {
            d.set_io$$request$$valid(!accepted);
            bool ready=stalls>=5&&cycle%3==0; step(ready);
            if(!accepted&&d.get_io$$request$$ready()) accepted=true;
            if(d.get_io$$response$$valid()) {
                ++stalls; if(!ready) continue;
                need(bool(d.get_io$$response$$bits$$error())==error &&
                    bool(d.get_io$$response$$bits$$pageFault())==(error&&page) &&
                    bool(d.get_io$$response$$bits$$compressed())==(!error&&comp) &&
                    bool(d.get_io$$response$$bits$$secondHalfFault())==split,
                    "independent C first/second parcel fault oracle");
                if(!error) need(d.get_io$$response$$bits$$instruction()==expected,"independent C parcel byte oracle");
                need(requests-before==uint64_t(expectedParcels<0?(split?2:1):expectedParcels),
                    "C speculative second parcel/owner count oracle");
                d.set_io$$request$$valid(0); ++cases; return;
            }
        }
        throw std::runtime_error("C parcel bounded completion failed");
    }
};
int main(int argc,char **argv) { try {
    Test t; bool mutate=argc>1&&std::string(argv[1])=="--wrong-parcel";
    t.transact(0x80000ffe,1,true,false,true,true,mutate); // C at page end MUST NOT touch page two
    t.transact(0x80000ffe,0x00100013,true,false,true,true);
    t.transact(0x80000ffe,0x00100013,false,false,true,false);
    t.transact(0x80000000,0x00500013,false);
    t.transact(0x80000ffe,0xffff001f,false,false,true,true); // Unsupported >32-bit prefix traps without overfetch
    for(unsigned n=0;n<1500;++n) {
        uint64_t pc=0x80000000+(t.random()%4096)*2;
        uint32_t ins=(t.random()&0xffffffe0U)|0x13;
        if(n%3==0) ins=(t.random()&0xfffcU)|1;
        t.transact(pc,ins,n%2,n%29==0,n%37==0,n%5==0);
    }
#if I1_TIMING_CUTS
    if(WORD==8) {
        uint64_t base=0x80004000, value=0x0050001300010001ULL;
        for(unsigned j=0;j<WORD;++j) t.bytes[base+j]=value>>(8*j);
        t.transact(base,0x00010001,true);
        t.transact(base+2,0x00130001,true,false,false,false,false,false,0);
        t.transact(base+4,0x00500013,true,false,false,false,false,false,0);
        // A context transition must require new authorization and observe
        // replacement code, even at the exact same virtual word.
        t.transact(base+4,0x00600013,true,false,false,false,false,true,1);
        // A partial PMP/parcel grant cannot create whole-word reuse.
        t.transact(base,0x00010001,false);
        t.transact(base+2,0x00130001,true,false,false,false,false,false,1);
        // Invalidation while an accepted fill waits must poison publication.
        t.killPending=true;
        t.transact(base+0x100,0x00010001,true);
        t.transact(base+0x102,0x00010001,true,false,false,false,false,false,1);
    }
    // RV32 as well as RV64: valid full-word grant, then a faulting
    // reauthorization. No old buffered success may mask the new fault.
    t.transact(0x80008000,1,true);
    t.transact(0x80008000,1,true,true,false,true,false,true,1);
#endif
    std::cout<<"FIVE_STAGE_FETCH_ALIGNER_PASS xlen="<<DUT_XLEN<<" cases="<<t.cases<<" parcels="<<t.requests
        <<" aligned_halfword_word_page_boundary_precise_partial_fault_stalls=PASS\n"; return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
