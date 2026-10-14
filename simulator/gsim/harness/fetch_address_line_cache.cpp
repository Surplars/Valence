// Retain the existing independent cache data/capacity/II checks, then add
// accepted-owner A-lock/error/partial/invalidation cases. No DUT address/data
// chooses the expected request or the bytes returned by this host.
#define main original_cache_fixture_main
#include "instruction_line_cache.cpp"
#undef main
#include <array>
#include <vector>

namespace address_owner {
struct ExpectedGet { uint64_t address; unsigned size, source, mask; bool line, deny, corrupt; };
struct Response { unsigned source, size; uint64_t data; bool denied, corrupt; };
struct Case { uint64_t pc; unsigned mask = 3; bool line = false; unsigned lineFault = 0;
    bool invalidate = false, fallbackFault = false, pmpBoundary = false;
    unsigned errorBeat = 7, invalidatePhase = 0; bool pmpChurn = false; };
struct Counts {
    unsigned cases=0, gets=0, partial=0, zero=0, line=0, retry=0, denied=0, corrupt=0;
    unsigned heldA=0, lockedFill=0, lockedFallback=0, heldResponse=0, invalidated=0;
    unsigned stateMask=0, odd=0, wrap=0, resetAbandoned=0, earlyError=0, midError=0, lockedInvalidate=0, pmpChurn=0;
} count;
static std::vector<ExpectedGet> requests(const Case& c) {
    std::vector<ExpectedGet> result;
    if (c.line) result.push_back({c.pc & ~63ULL,6,0,255,true,bool(c.lineFault&1),bool(c.lineFault&2)});
    if (!c.line || c.lineFault) {
        if (c.mask == 3) {
            result.push_back({c.pc & ~7ULL,3,4,255,false,c.fallbackFault,false});
            if (c.pc & 4) result.push_back({(c.pc & ~7ULL)+8,3,5,255,false,c.fallbackFault,false});
        } else if (c.mask) {
            const uint64_t address = c.pc + (c.mask==2 ? 4 : 0);
            result.push_back({address,2,unsigned(4+(c.mask==2)),unsigned(address&4 ? 240:15),false,c.fallbackFault,false});
        }
    }
    return result;
}
static void runCase(Case c, bool negative=false, bool resetMidFill=false) {
    SInstructionLineCacheGsim dut;
    drive(dut,false,0,std::nullopt);dut.set_reset(1);dut.step();dut.step();dut.set_reset(0);
    auto expected=requests(c);std::deque<Response> replies;std::optional<ExpectedGet> held;
    bool accepted=false, invalidated=false, finished=false;unsigned sent=0, responseHold=0, beats=0;
    for(unsigned cycle=0;cycle<300&&!finished;++cycle) {
        const auto incoming = replies.empty()?std::optional<Response>{}:std::optional<Response>{replies.front()};
        const bool inv=c.invalidate&&!invalidated&&(c.invalidatePhase==0 ?
            bool(incoming&&incoming->size==6) : bool(held));
        const bool aReady=cycle%7>=5;
        const bool responseReady=responseHold>=3;
        const uint64_t poison=0xdead000000000003ULL ^ (cycle*0x100000009ULL);
        drive(dut,!accepted,accepted?poison:c.pc,std::nullopt,
            c.pmpBoundary?1:3,c.pmpBoundary?0x0c:(c.pmpChurn&&accepted ? 0x8b : 0),
            c.pmpBoundary?(c.pc+8)>>2:(c.pmpChurn&&accepted ? (cycle&1?0:UINT64_MAX>>10) : 0),inv,responseReady);
        dut.set_io$$fetch$$requestMask(c.mask);dut.set_io$$tl$$a$$ready(aReady);
        dut.set_io$$tl$$d$$valid(bool(incoming));
        dut.set_io$$tl$$d$$bits$$size(incoming?incoming->size:0);
        dut.set_io$$tl$$d$$bits$$source(incoming?incoming->source:7);
        dut.set_io$$tl$$d$$bits$$data(incoming?incoming->data:0x5555555555555555ULL);
        dut.set_io$$tl$$d$$bits$$denied(incoming&&incoming->denied);
        dut.set_io$$tl$$d$$bits$$corrupt(incoming&&incoming->corrupt);
        dut.step();
        count.stateMask|=1U<<dut.get_io$$observedState();
        if(inv){invalidated=true;++count.invalidated;if(held)++count.lockedInvalidate;}
        if(c.pmpChurn&&accepted&&held)++count.pmpChurn;
        if(incoming&&dut.get_io$$tl$$d$$ready()){replies.pop_front();++beats;}
        if(!accepted&&dut.get_io$$fetch$$request$$ready())accepted=true;
        const bool aValid=dut.get_io$$tl$$a$$valid();
        if(held)check(aValid,"held instruction A was withdrawn");
        if(aValid) {
            check(sent<expected.size(),"unowned or duplicated instruction A");const auto want=expected[sent];
            if(c.line&&c.lineFault&&!want.line)check(beats>=8,"retry A preceded all eight owned fill D beats");
            const uint64_t observed=dut.get_io$$tl$$a$$bits$$address() ^ uint64_t(negative?8:0);
            check(observed==want.address&&dut.get_io$$tl$$a$$bits$$size()==want.size&&
                dut.get_io$$tl$$a$$bits$$source()==want.source&&dut.get_io$$tl$$a$$bits$$mask()==want.mask&&
                dut.get_io$$tl$$a$$bits$$opcode()==4,
                "independent cache owner A address/size/source/mask mismatch");
            if(held)check(want.address==held->address&&want.size==held->size&&want.source==held->source&&want.mask==held->mask,
                "independent cache held A stability mismatch");
            if(!aReady) {held=want;++count.heldA;
                if(dut.get_io$$routeLocked()) {if(dut.get_io$$routeFallback())++count.lockedFallback;else ++count.lockedFill;}}
            else {
                held.reset();++sent;++count.gets;
                for(unsigned i=0;i<(want.line?8U:1U);++i) {
                    const bool terminal=want.line?i==c.errorBeat:true;
                    replies.push_back({want.source,want.size,beat((want.address&~7ULL)+8*i,0),
                        want.deny&&terminal,want.corrupt&&terminal});
                }
                count.denied+=want.deny;count.corrupt+=want.corrupt;
            }
        }
        if(resetMidFill&&beats==3) {
            check(accepted&&sent==1&&!dut.get_io$$fetch$$response$$valid(),"abandoned fill fixture missed active owner");
            drive(dut,false,0,std::nullopt);dut.set_reset(1);dut.step();dut.step();dut.set_reset(0);
            drive(dut,false,0,std::nullopt);dut.step();
            check(!dut.get_io$$tl$$a$$valid()&&!dut.get_io$$fetch$$response$$valid(),"reset exposed abandoned fill owner");
            ++count.resetAbandoned;return;
        }
        if(dut.get_io$$fetch$$response$$valid()) {
            check(accepted&&sent==expected.size()&&replies.empty(),"cache response escaped exact owned request ledger");
            uint64_t data=0;unsigned errors=(~c.mask)&3U;
            if(c.fallbackFault&&!c.line || c.fallbackFault&&c.lineFault)errors=3;
            else {
                if(c.mask&1)data|=instruction(c.pc,0);
                if(c.mask&2)data|=uint64_t(instruction(c.pc+4,0))<<32;
            }
            check(dut.get_io$$responseLow()==data&&dut.get_io$$responseHigh()==0&&
                dut.get_io$$fetch$$responseError()==errors&&!dut.get_io$$fetch$$responsePageFault(),
                "independent cache owner response/error mismatch");
            if(!responseReady){++responseHold;++count.heldResponse;}else finished=true;
        }
    }
    check(finished,"independent cache owner timed out");check(!c.invalidate||invalidated,"invalidate case not reached");
    count.earlyError+=c.lineFault&&c.errorBeat==0;count.midError+=c.lineFault&&c.errorBeat==3;
    ++count.cases;count.zero+=c.mask==0;count.partial+=c.mask==1||c.mask==2;count.line+=c.line;count.retry+=c.lineFault!=0;
    count.odd+=(c.pc&4)!=0;count.wrap+=c.pc>UINT64_MAX-8;
}
static void run(bool negative) {
    for(auto pc:{0ULL,0x80000000ULL,0x80000ff8ULL,0xfffffffffffffff8ULL})
        for(unsigned mask=0;mask<4;++mask)runCase({pc,mask},negative);
    for(auto pc:{0x80000004ULL,0x800000fcULL,0xfffffffffffffffcULL})
        for(unsigned mask=0;mask<4;++mask)runCase({pc,mask});
    runCase({ram,3,true});
    for(unsigned fault:{1U,2U,3U})for(unsigned errorBeat:{0U,3U,7U})
        runCase({ram+24,3,true,fault,false,false,false,errorBeat});
    runCase({ram+56,3,true,1,false,true});
    runCase({ram,3,true,0,true});
    runCase({ram+24,3,true,0,true,false,false,7,1,true});
    runCase({0x80000004ULL,3,false,0,true,false,false,7,1,true});
    runCase({ram,3,false,0,false,false,true});
    runCase({ram,3,true},false,true);
    std::cout<<"PASS_FETCH_ADDRESS_CACHE_OWNER cases="<<count.cases<<" gets="<<count.gets
        <<" partial="<<count.partial<<" zero="<<count.zero<<" line="<<count.line<<" retry="<<count.retry
        <<" denied="<<count.denied<<" corrupt="<<count.corrupt<<" heldA="<<count.heldA
        <<" lockedFill="<<count.lockedFill<<" lockedFallback="<<count.lockedFallback
        <<" heldResponse="<<count.heldResponse<<" invalidated="<<count.invalidated
        <<" stateMask="<<count.stateMask<<" odd="<<count.odd<<" wrap="<<count.wrap
        <<" resetAbandoned="<<count.resetAbandoned<<" earlyError="<<count.earlyError<<" midError="<<count.midError
        <<" lockedInvalidate="<<count.lockedInvalidate<<" pmpChurn="<<count.pmpChurn<<'\n';
    check(count.cases==43&&count.zero&&count.partial&&count.retry==10&&count.denied&&count.corrupt&&
        count.heldA&&count.lockedFill&&count.lockedFallback&&count.heldResponse&&count.invalidated&&
        count.odd&&count.wrap&&count.resetAbandoned&&count.earlyError==3&&count.midError==3&&
        count.lockedInvalidate==2&&count.pmpChurn,"cache address directed coverage missing");
    // hitReply/lineReply are covered by the retained independent cache test;
    // this cold-owner matrix must cover idle/fallback/sendFill/waitFill/retry.
    check((count.stateMask&0x8f)==0x8f,"cache owner reachable phase coverage missing");

}
}
int main(int argc,char** argv) {try {
    const bool negative=argc==2&&std::string_view(argv[1])=="--inject-address-mismatch";
    check(argc==1||negative,"unknown address owner argument");
    if(!negative)check(original_cache_fixture_main(1,argv)==0,"retained cache oracle failed");
    address_owner::run(negative);return 0;
} catch(const std::exception& e){std::cerr<<"FETCH_ADDRESS_CACHE_OWNER_FAIL "<<e.what()<<'\n';return 1;}}
