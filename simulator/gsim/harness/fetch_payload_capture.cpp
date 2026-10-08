#include "FetchOffsetsGsim.h"
#include <algorithm>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#ifndef FETCH_WIDTH
#define FETCH_WIDTH 2
#endif
static void check(bool good,const char *why) { if(!good)throw std::runtime_error(why); }
static uint64_t mix(uint64_t v) { v^=v>>30;v*=0xbf58476d1ce4e5b9ULL;v^=v>>27;v*=0x94d049bb133111ebULL;return v^(v>>31); }
static uint16_t parcel(uint64_t address,unsigned generation,bool context) {
    if (((address>>1)&3)==3) return uint16_t(0x0093 | ((generation&15)<<8));
    return uint16_t(1 | ((mix(address ^ (uint64_t(generation)<<40) ^ (uint64_t(context)<<61)) & 0x3fff)<<2));
}
static uint64_t packet(uint64_t address,unsigned generation,bool context) {
    uint64_t value=0;for(unsigned n=0;n<4;++n)value|=uint64_t(parcel(address+2*n,generation,context))<<(16*n);return value;
}
static uint32_t instruction(uint64_t address,unsigned generation,bool context) {
    const auto first=parcel(address,generation,context);
    return uint32_t(first) | ((first&3)==3 ? uint32_t(parcel(address+2,generation,context))<<16 : 0);
}
static bool accessFault(uint64_t address,unsigned generation,bool context) { return ((address>>2)+generation+context)%19==3; }
static bool pageFault(uint64_t address,unsigned generation,bool context) { return ((address>>2)+generation+context)%23==7; }
struct Owner { uint64_t address;unsigned generation,delay;bool context,stale=false; };
int main(int argc,char **argv) {
    try {
        unsigned seed=1,iterations=12000;
        bool corrupt=false,bypassStale=false,bypassInvalidate=false;
        for(int n=1;n<argc;++n) {
            const std::string arg=argv[n];
            if(arg=="--seed"&&n+1<argc)seed=std::stoul(argv[++n]);
            else if(arg=="--iterations"&&n+1<argc)iterations=std::stoul(argv[++n]);
            else if(arg=="--inject-word")corrupt=true;
            else if(arg=="--bypass-stale")bypassStale=true;
            else if(arg=="--bypass-invalidate")bypassInvalidate=true;
            else throw std::runtime_error("unknown frontend capture option");
        }
        check(iterations>=1000&&iterations<=100000,"frontend iteration bound");
        SFetchOffsetsGsim d;
        uint64_t pc=0x80000000ULL,heldAddress=0;
        unsigned generation=0,heldGeneration=0,heldMask=0;
        bool context=false,heldContext=false,held=false,heldStale=false;
        std::optional<Owner> pending;
        uint64_t checked=0,replies=0,invalidatedReply=0,staleReply=0,wrongContextReply=0;
        uint64_t lockedInvalidate=0,turnovers=0,joins=0,resets=0,staleMutations=0;
        auto idle=[&] {
            d.set_io$$pc(pc);d.set_io$$enable(0);d.set_io$$pause(1);d.set_io$$invalidate(0);d.set_io$$virtualized(context);
            d.set_io$$requestReady(0);d.set_io$$responseValid(0);d.set_io$$responseLow(0);d.set_io$$responseHigh(0);
            d.set_io$$responseErrors(0);d.set_io$$responsePages(0);
        };
        idle();d.set_reset(1);d.step();d.step();d.set_reset(0);
        for(unsigned cycle=0;cycle<iterations;++cycle) {
            if(cycle>0&&cycle%3001==0) {
                idle();d.set_reset(1);d.step();d.step();d.set_reset(0);pending.reset();held=false;++generation;++resets;
            }
            const uint64_t random=mix(seed*0x10001ULL+cycle);
            const bool invalidate=cycle%47==11;
            const bool enable=cycle%13!=0;
            const bool ready=cycle%7<4;
            const bool reply=pending&&pending->delay==0;
            if(cycle%131==17)context=!context;
            if(invalidate)++generation;
            if(bypassStale&&reply&&pending->stale&&!invalidate&&enable&&pending->context==context) {
                pc=pending->address;
                d.fetch$pendingStale=0;d.fetch$pendingStale$NEXT=0;d.activateAll();++staleMutations;
            }
            d.set_io$$pc(pc);d.set_io$$enable(enable);d.set_io$$pause(cycle%29<3);
            d.set_io$$invalidate(invalidate&&!bypassInvalidate);d.set_io$$virtualized(context);
            d.set_io$$requestReady(ready);d.set_io$$responseValid(reply);
            unsigned errors=0,pages=0;
            if(pending)for(unsigned word=0;word<FETCH_WIDTH;++word) {
                errors|=unsigned(accessFault(pending->address+4*word,pending->generation,pending->context))<<word;
                pages|=unsigned(pageFault(pending->address+4*word,pending->generation,pending->context))<<word;
            }
            d.set_io$$responseLow(pending?packet(pending->address,pending->generation,pending->context):0);
            d.set_io$$responseHigh(pending?packet(pending->address+8,pending->generation,pending->context):0);
            d.set_io$$responseErrors(errors);d.set_io$$responsePages(pages);d.step();
            if(held)check(d.get_io$$requestValid()&&d.get_io$$requestAddress()==heldAddress&&d.get_io$$requestMask()==heldMask,
                          "frontend held request payload changed");
            const bool valid[4]={bool(d.get_io$$lane0$$valid()),bool(d.get_io$$lane1$$valid()),
                                bool(d.get_io$$lane2$$valid()),bool(d.get_io$$lane3$$valid())};
            const uint32_t bits[4]={d.get_io$$lane0$$bits(),d.get_io$$lane1$$bits(),d.get_io$$lane2$$bits(),d.get_io$$lane3$$bits()};
            const uint64_t fault[4]={d.get_io$$fault0(),d.get_io$$fault1(),d.get_io$$fault2(),d.get_io$$fault3()};
            if(reply&&pending->stale)check(!valid[0]&&!valid[1]&&!valid[2]&&!valid[3],
                                          "frontend stale owner became visible");
            uint64_t address=pc;unsigned prefix=0;
            for(unsigned lane=0;lane<4;++lane) {
                if(lane>=FETCH_WIDTH)check(!valid[lane],"frontend extra valid lane");
                if(!valid[lane])continue;
                check(enable&&!invalidate&&(lane==0||valid[lane-1]),"frontend invalidation/prefix validity oracle mismatch");
                const auto expected=instruction(address,generation,context);
                if ((bits[lane]^(corrupt?1U:0U))!=expected) {
                    std::cerr << "FETCH_CAPTURE_DIAGNOSTIC cycle="<<cycle<<" lane="<<lane<<" pc="<<std::hex<<pc
                        <<" address="<<address<<" got="<<bits[lane]<<" expected="<<expected<<std::dec
                        <<" generation="<<generation<<" context="<<context<<" invalidate="<<invalidate
                        <<" reply="<<reply<<" held="<<held<<" dut_pending_stale="<<unsigned(d.fetch$pendingStale)
                        <<" dut_pending_context="<<unsigned(d.fetch$pendingContext)<<" held_context="<<heldContext;
                    if(pending)std::cerr<<" owner_generation="<<pending->generation<<" owner_context="<<pending->context
                        <<" owner_stale="<<pending->stale<<" owner_address="<<std::hex<<pending->address<<std::dec;
                    std::cerr<<'\n';
                }
                check((bits[lane]^(corrupt?1U:0U))==expected,"frontend independent generation/context instruction mismatch");
                const bool wide=(expected&3)==3;
                const bool e=accessFault(address,generation,context)||(wide&&accessFault(address+2,generation,context));
                const bool p=pageFault(address,generation,context)||(wide&&pageFault(address+2,generation,context));
                check(bool(d.get_io$$errors()&(1U<<lane))==e&&bool(d.get_io$$pages()&(1U<<lane))==p,
                      "frontend independent exception metadata mismatch");
                if(e||p)check(fault[lane]==((accessFault(address,generation,context)||pageFault(address,generation,context))?address:address+2),
                              "frontend independent fault address mismatch");
                joins+=wide&&(address&7)==6;address+=wide?4:2;++checked;++prefix;
            }
            const bool request=d.get_io$$requestValid()&&ready;
            if(reply) {
                ++replies;invalidatedReply+=invalidate;staleReply+=pending->stale;
                wrongContextReply+=pending->context!=context;turnovers+=request;
                check(d.get_io$$responseReady(),"frontend unexpectedly backpressured reply");pending.reset();
            }
            if(request) {
                check(!pending,"frontend accepted overlapping response owners");
                lockedInvalidate+=held&&invalidate;
                // InstructionPort carries no first-offer context token. The
                // downstream translation service samples context on fire;
                // retain that accepted owner unchanged until its reply.
                pending=Owner{d.get_io$$requestAddress(),generation,
                    unsigned(1+(random%13)),context,invalidate||(held&&heldStale)};
                held=false;heldStale=false;
            } else if(d.get_io$$requestValid()&&!ready&&!held) {
                held=true;heldAddress=d.get_io$$requestAddress();heldMask=d.get_io$$requestMask();
                heldGeneration=generation;heldContext=context;
            }
            if(invalidate&&pending)pending->stale=true;
            if(invalidate&&held)heldStale=true;
            if(pending&&pending->delay)--pending->delay;
            if(prefix&&cycle%4!=0) {
                const unsigned take=1+random%prefix;
                for(unsigned n=0;n<take;++n)pc+=(instruction(pc,generation,context)&3)==3?4:2;
            }
            if(cycle%173==0)pc=0x80000000ULL+((random>>8)&1022);
            if(cycle%997==0)pc=UINT64_MAX-29;
        }
        check(checked>1000&&joins>100&&invalidatedReply>0&&staleReply>0&&wrongContextReply>0&&lockedInvalidate>0&&turnovers>0,
              "frontend capture concurrency witnesses missing");
        check(!bypassStale||staleMutations>0,"stale-owner negative was not exercised");
        std::cout<<"FETCH_CAPTURE_PASS width="<<FETCH_WIDTH<<" seed="<<seed<<" checked="<<checked<<" replies="<<replies
            <<" invalidate_reply="<<invalidatedReply<<" stale_reply="<<staleReply<<" wrong_context="<<wrongContextReply
            <<" locked_invalidate="<<lockedInvalidate<<" reply_request_turnover="<<turnovers
            <<" compressed_joins="<<joins<<" resets="<<resets<<'\n';return 0;
    } catch(const std::exception &error) {std::cerr<<"FETCH_CAPTURE_FAIL "<<error.what()<<'\n';return 1;}
}
