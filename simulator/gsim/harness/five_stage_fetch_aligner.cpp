#ifdef I1_SCALAR_PARCEL_FIXTURE
#include "I1FetchParcelTimingFixture.h"
using SFiveStageFetchAligner = SI1FetchParcelTimingFixture;
#else
#include "FiveStageFetchAligner.h"
#endif
#include <array>
#include <cstdint>
#include <deque>
#include <vector>
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
#ifdef I1_FETCH_GUEST_FAULT
    std::optional<std::array<uint64_t,3>> heldGuest;
    void checkGuest(bool fault,uint64_t faultPc) {
        need(bool(d.get_io$$response$$bits$$guest$$pageFault())==fault &&
            d.get_io$$response$$bits$$guest$$physical()==(fault?faultPc>>2:0) &&
            bool(d.get_io$$response$$bits$$guest$$implicitPte())==(fault&&bool(faultPc&4)),
            "independent C guest fault metadata oracle");
    }
#endif
    std::mt19937_64 random{0x50415243454c};
    uint64_t cycle=0,cases=0,requests=0,errorPc=~0ULL;
    bool faultPage=false,fullSpan=true;
    bool killPending=false;
    // Optional burst service exercises external ownership turnover; expectations
    // below remain byte/permission ledgers and do not inspect aligner phases.
    bool turnoverService=false, blockReturnRequest=false, offered=false;
    unsigned memoryLatency=1;
    uint64_t offeredPc=0, invalidateWaitPc=~0ULL, invalidateReturnPc=~0ULL;
    uint64_t firstTurnovers=0, secondTurnovers=0, freshReuseTurnovers=0;
    uint64_t blockedTurnovers=0, heldReplyChecks=0, invalidations=0;
    std::vector<uint64_t> requestAddresses;
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
        bool mv=pending && cycle>=pending->due;
        bool mr=turnoverService ? (!pending || mv) && !(blockReturnRequest && mv) : !pending && cycle%4!=1;
        d.set_io$$response$$ready(ready); d.set_io$$memoryRequest$$ready(mr);
        d.set_io$$memoryResponse$$valid(mv);
        d.set_io$$memoryResponse$$bits$$data(pending?pending->data:0);
        d.set_io$$memoryResponse$$bits$$error(pending&&pending->error);
        d.set_io$$memoryResponse$$bits$$pageFault(pending&&pending->page);
        d.set_io$$memoryResponse$$bits$$fetchSpan(pending&&pending->span);
#ifdef I1_FETCH_GUEST_FAULT
        bool guestFault=pending&&pending->error&&pending->page;
        d.set_io$$memoryResponse$$bits$$guest$$pageFault(guestFault);
        d.set_io$$memoryResponse$$bits$$guest$$physical(guestFault?pending->pc>>2:0);
        d.set_io$$memoryResponse$$bits$$guest$$implicitPte(guestFault&&bool(pending->pc&4));
#endif
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
        bool invalidate=pending && ((!mv && (killPending || pending->pc==invalidateWaitPc)) ||
            (mv && pending->pc==invalidateReturnPc));
        d.set_io$$invalidate(invalidate);
        if(invalidate) {
            ++invalidations; killPending=false;
            invalidateWaitPc=~0ULL; invalidateReturnPc=~0ULL;
        }
#endif
        d.step(); ++cycle;
        std::array<uint64_t,3> req{d.get_io$$memoryRequest$$bits$$address(),
            d.get_io$$memoryRequest$$bits$$size(),d.get_io$$memoryRequest$$bits$$write()};
        if(held) need(d.get_io$$memoryRequest$$valid() && req==*held,"C parcel offer changed under stalls");
        held.reset(); if(d.get_io$$memoryRequest$$valid()&&!mr) held=req;
        std::array<uint64_t,5> rsp{d.get_io$$response$$bits$$instruction(),d.get_io$$response$$bits$$error(),
            d.get_io$$response$$bits$$pageFault(),d.get_io$$response$$bits$$compressed(),
            d.get_io$$response$$bits$$secondHalfFault()};
        if(heldResponse) {
            need(d.get_io$$response$$valid()&&rsp==*heldResponse,"C assembly reply changed under stalls");
            ++heldReplyChecks;
        }
        heldResponse.reset(); if(d.get_io$$response$$valid()&&!ready) heldResponse=rsp;
#ifdef I1_FETCH_GUEST_FAULT
        std::array<uint64_t,3> guest{d.get_io$$response$$bits$$guest$$pageFault(),
            d.get_io$$response$$bits$$guest$$physical(),d.get_io$$response$$bits$$guest$$implicitPte()};
        if(heldGuest) need(d.get_io$$response$$valid()&&guest==*heldGuest,"C guest metadata changed under stalls");
        heldGuest.reset();if(d.get_io$$response$$valid()&&!ready)heldGuest=guest;
#endif
        if(mv&&d.get_io$$memoryResponse$$ready()) {
            if(offered && d.get_io$$request$$ready() && d.get_io$$response$$valid() && ready) {
                if(rsp[4]) ++secondTurnovers; else ++firstTurnovers;
                if((offeredPc & ~(WORD-1ULL))==(pending->pc & ~(WORD-1ULL)) &&
                    !d.get_io$$memoryRequest$$valid()) ++freshReuseTurnovers;
            }
            if(offered && d.get_io$$memoryRequest$$valid() && !mr) ++blockedTurnovers;
            pending.reset();
        }
        if(mr&&d.get_io$$memoryRequest$$valid()) {
            need(!pending && req[1]==1 && !req[2] && !(req[0]&1),"C parcel geometry/owner oracle");
            pending=Pending{req[0],load(req[0]),turnoverService ? cycle+memoryLatency-1 : cycle+1+random()%9,
                req[0]==errorPc,req[0]==errorPc&&faultPage,fullSpan};
            ++requests; requestAddresses.push_back(req[0]);
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
#ifdef I1_FETCH_GUEST_FAULT
                checkGuest(error&&page,errorPc);
#endif
                if(!error) need(d.get_io$$response$$bits$$instruction()==expected,"independent C parcel byte oracle");
                need(requests-before==uint64_t(expectedParcels<0?(split?2:1):expectedParcels),
                    "C speculative second parcel/owner count oracle");
                d.set_io$$request$$valid(0); ++cases; return;
            }
        }
        throw std::runtime_error("C parcel bounded completion failed");
    }
};
#if I1_TIMING_CUTS
// At most one accepted architectural parcel is live. Response-before-request
// ledger order admits a replacement on exactly the old completion edge.
struct StreamExpected {
    uint64_t pc; uint32_t instruction;
    bool compressed, error, page, second;
};
struct TurnoverCoverage {
    uint64_t cases=0, instructions=0, first=0, second=0, fresh=0, blocked=0, held=0, invalidations=0;
};
static void turnoverCase(unsigned which, TurnoverCoverage &coverage, bool mutate) {
    Test t; t.turnoverService=true;
    constexpr uint64_t base=0x80010000;
    std::vector<std::pair<uint64_t,uint32_t>> program;
    std::vector<uint64_t> expectedRequests;
    bool holdReply=false;
    switch(which) {
    case 0: // first return -> next parcel in the fresh word
        program={{base,0x00500013},{base+4,0x00600013}}; expectedRequests={base}; break;
    case 1: // first return -> a new cache word in the same cycle
        program={{base,0x00500013},{base+32,0x00600013}}; expectedRequests={base,base+32}; break;
    case 2: // next memory offer is held while the old response completes
        program={{base,0x00500013},{base+32,0x00600013}}; expectedRequests={base,base+32};
        t.blockReturnRequest=true; break;
    case 3: // second return -> a different instruction in that fresh word
        program={{base+6,0x00500013},{base+10,0x00600013}}; expectedRequests={base+6,base+8}; break;
    case 4: // partial authorization cannot authorize the next same-word parcel
        program={{base,0x00500013},{base+4,0x00000001}}; expectedRequests={base,base+2,base+4};
        t.fullSpan=false; break;
    case 5: // first error cannot publish an apparently reusable word
        program={{base,0x00500013},{base+4,0x00000001}}; expectedRequests={base,base+4};
        t.errorPc=base; break;
    case 6: // second-parcel page fault, then reauthorize another same-word parcel
        program={{base+6,0x00500013},{base+10,0x00000001}};
        expectedRequests={base+6,base+8,base+10}; t.errorPc=base+8; t.faultPage=true; break;
    case 7: // invalidate an in-flight first fill
        program={{base,0x00500013},{base+4,0x00000001}}; expectedRequests={base,base+4};
        t.memoryLatency=4; t.invalidateWaitPc=base; break;
    case 8: // invalidate exactly at first return/new request
        program={{base,0x00500013},{base+4,0x00000001}}; expectedRequests={base,base+4};
        t.invalidateReturnPc=base; break;
    case 9: // direct return held by consumer must become an identical registered reply
        program={{base,0x00500013},{base+4,0x00600013}}; expectedRequests={base};
        holdReply=true; break;
    case 10: // poison the second returned word before it arrives
        program={{base+6,0x00500013},{base+10,0x00000001}};
        expectedRequests={base+6,base+8,base+10}; t.memoryLatency=4; t.invalidateWaitPc=base+8; break;
    case 11: // steady aligned32 feed: independent one-instruction/cycle service budget
        for(unsigned n=0;n<32;++n) {
            program.push_back({base+4*n,0x00500013});
            if(n%2==0) expectedRequests.push_back(base+4*n);
        }
        break;
    }
    for(auto [pc,ins]:program) for(unsigned j=0;j<4;++j) t.bytes[pc+j]=ins>>(8*j);
    auto expected=[&](uint64_t pc) {
        uint32_t instruction=0;
        for(unsigned j=0;j<4;++j) instruction|=uint32_t(t.bytes[pc+j])<<(8*j);
        bool compressed=(instruction&3)!=3, unsupported=(instruction&31)==31;
        bool firstError=pc==t.errorPc;
        bool second=!firstError&&!compressed&&!unsupported && (!t.fullSpan || pc%WORD>WORD-4);
        bool error=firstError || second&&pc+2==t.errorPc;
        if(compressed||unsupported) instruction&=65535;
        if(mutate && which==0) instruction^=1;
        return StreamExpected{pc,instruction,compressed&&!error,error,error&&t.faultPage,second};
    };
    std::deque<StreamExpected> owners;
    unsigned offered=0,completed=0,stallLeft=0; bool stalled=false;
    uint64_t start=t.cycle;
    for(unsigned n=0;n<500 && completed<program.size();++n) {
        t.offered=offered<program.size();
        t.offeredPc=t.offered?program[offered].first:0;
        t.d.set_io$$request$$valid(t.offered); t.d.set_io$$request$$bits(t.offeredPc);
        if(holdReply&&!stalled&&t.pending&&t.cycle>=t.pending->due) { stallLeft=3; stalled=true; }
        bool ready=stallLeft==0; if(stallLeft) --stallLeft;
        t.step(ready);
        if(t.d.get_io$$response$$valid()&&ready) {
            need(!owners.empty(),"turnover response has no independently accepted owner");
            auto e=owners.front(); owners.pop_front();
            need(bool(t.d.get_io$$response$$bits$$error())==e.error &&
                bool(t.d.get_io$$response$$bits$$pageFault())==e.page &&
                bool(t.d.get_io$$response$$bits$$compressed())==e.compressed &&
                bool(t.d.get_io$$response$$bits$$secondHalfFault())==e.second,
                "turnover independent permission/fault oracle");
#ifdef I1_FETCH_GUEST_FAULT
            t.checkGuest(e.page,e.pc+(e.second?2:0));
#endif
            if(!e.error) need(t.d.get_io$$response$$bits$$instruction()==e.instruction,
                "turnover independent byte oracle");
            ++completed;
        }
        if(t.offered&&t.d.get_io$$request$$ready()) {
            need(owners.empty(),"turnover accepted a second live architectural owner");
            owners.push_back(expected(t.offeredPc)); ++offered;
        }
    }
    need(completed==program.size() && owners.empty() && !t.pending,"turnover bounded completion and drain");
    need(t.requestAddresses==expectedRequests,"turnover independent authorization request ledger");
    if(which==0) need(t.firstTurnovers>0 && t.freshReuseTurnovers>0,"first-return fresh-word reuse not exercised");
    if(which==1) need(t.firstTurnovers>0,"first-return new-word turnover not exercised");
    if(which==2) need(t.blockedTurnovers>0,"turnover next memory offer was never backpressured");
    if(which==3) need(t.secondTurnovers>0 && t.freshReuseTurnovers>0,"second-return fresh-word reuse not exercised");
    if(which==7 || which==8 || which==10) need(t.invalidations==1,"turnover invalidate stimulus missing");
    if(which==9) need(t.heldReplyChecks>=3,"direct-to-held reply stability was not exercised");
    if(which==11) need(t.cycle-start<=program.size()+2,"aligned32 hit stream missed one-instruction/cycle budget");
    ++coverage.cases; coverage.instructions+=completed; coverage.first+=t.firstTurnovers;
    coverage.second+=t.secondTurnovers; coverage.fresh+=t.freshReuseTurnovers;
    coverage.blocked+=t.blockedTurnovers; coverage.held+=t.heldReplyChecks; coverage.invalidations+=t.invalidations;
    std::cout<<"I1_PARCEL_TURNOVER_CASE_PASS case="<<which<<" instructions="<<completed<<" cycles="<<t.cycle-start
        <<" parcels="<<t.requests<<" first="<<t.firstTurnovers<<" second="<<t.secondTurnovers
        <<" fresh="<<t.freshReuseTurnovers<<" blocked="<<t.blockedTurnovers<<" held="<<t.heldReplyChecks
        <<" invalidations="<<t.invalidations<<'\n';
}
#endif

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
#if I1_TIMING_CUTS
    if(WORD==8) {
        TurnoverCoverage coverage;
        bool wrongTurnover=argc>1&&std::string(argv[1])=="--wrong-turnover";
        for(unsigned n=0;n<12;++n) turnoverCase(n,coverage,wrongTurnover);
        std::cout<<"I1_PARCEL_TURNOVER_PASS cases="<<coverage.cases<<" instructions="<<coverage.instructions
            <<" first="<<coverage.first<<" second="<<coverage.second<<" fresh="<<coverage.fresh
            <<" blocked="<<coverage.blocked<<" held="<<coverage.held<<" invalidations="<<coverage.invalidations
            <<" independent_bytes_permissions_owner_stability_bandwidth=PASS\n";
    }
#endif
    std::cout<<"FIVE_STAGE_FETCH_ALIGNER_PASS xlen="<<DUT_XLEN<<" cases="<<t.cases<<" parcels="<<t.requests
        <<" aligned_halfword_word_page_boundary_precise_partial_fault_stalls=PASS\n"; return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
