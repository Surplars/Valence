#include "PipelinedMultiplyLifetimeGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#include <vector>
#include "muldiv_model.h"
static void check(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); }
#ifndef REGISTERED_MULTIPLY_OPERANDS
#define REGISTERED_MULTIPLY_OPERANDS 0
#endif
static constexpr unsigned inputLatency=REGISTERED_MULTIPLY_OPERANDS;
static uint64_t ownerTag(SPipelinedMultiplyLifetimeGsim &d,unsigned slot) { switch(slot) {
#define OWNER_CASE(n) case n: return d.get_io$$owner##n##$$tag();
OWNER_CASE(0) OWNER_CASE(1) OWNER_CASE(2) OWNER_CASE(3) OWNER_CASE(4) OWNER_CASE(5) OWNER_CASE(6) OWNER_CASE(7)
#undef OWNER_CASE
} throw std::runtime_error("owner slot range"); }

int runCase(int argc,char** argv, unsigned resetAge) {
    try {
        SPipelinedMultiplyLifetimeGsim d;
        const bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
        d.set_io$$start$$valid(0); d.set_io$$start$$bits$$token$$index(0); d.set_io$$start$$bits$$token$$tag(0);
        d.set_io$$start$$bits$$pc(0); d.set_io$$start$$bits$$operation(0); d.set_io$$start$$bits$$word(0);
        d.set_io$$start$$bits$$left(0); d.set_io$$start$$bits$$right(0);
        d.set_io$$cancelMask(0); d.set_io$$complete$$ready(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        // Reset while arithmetic owns live reservations, then immediately reuse
        // slot zero. These old high-tag requests must never produce new results.
        for (unsigned c=0;c<resetAge;++c) {
            d.set_io$$start$$valid(1); d.set_io$$start$$bits$$operation(c%4);
            d.set_io$$start$$bits$$word(c%5==4); d.set_io$$start$$bits$$left(UINT64_MAX-c);
            d.set_io$$start$$bits$$right(0x1234567+c); d.set_io$$start$$bits$$token$$tag(UINT64_C(0xf000000000000000)+c);
            d.set_io$$start$$bits$$token$$index(c%16); d.set_io$$complete$$ready(0); d.step();
        }
        d.set_io$$start$$valid(0); d.set_reset(1); d.step(); d.set_reset(0);
        struct Input { unsigned op; bool word; uint64_t a,b; };
        struct Expected { uint64_t tag, result; unsigned slot,due,previewAt; bool word,cancelled; };
        const std::array<uint64_t,10> values{0,1,2,UINT64_MAX,UINT64_C(0x8000000000000000),UINT64_C(0x7fffffffffffffff),
            UINT64_C(0x80000000),UINT64_C(0xffffffff),UINT64_C(0xffffffff00000000),UINT64_C(0x123456789abcdef0)};
        std::mt19937_64 rng(64016);
        std::vector<Input> inputs;
        for(unsigned kind=0;kind<5;++kind) for(auto a:values) for(auto b:values)
            inputs.push_back({kind%4,kind==4,a,b});
        for(unsigned i=0;i<2500;++i) { unsigned kind=rng()%5; inputs.push_back({kind%4,kind==4,rng(),rng()}); }
        std::deque<Expected> pending;
        unsigned accepted=0,completed=0,cancelled=0,held=0,full=0,tail=0,steady=0,multiCancel=0,drain=0,reusedCancelled=0;
        std::array<bool,8> wasCancelled{};
        std::array<unsigned,8> lastAllocation{};
        unsigned denseReuse=0,cancelBeforeWrite=0,cancelAtWrite=0,cancelAfterWrite=0;
        for(unsigned cycle=0;cycle<30000;++cycle) {
            const bool valid=accepted<inputs.size();
            const bool ready=cycle<300 || (cycle>=350 && rng()%3==0);
            unsigned live=0;
            for(auto e:pending) if(!e.cancelled) live|=1U<<e.slot;
            const unsigned cancel=(cycle>=800 && cycle<1000) ? live : (cycle>=350 && accepted>=600 && cycle%17==0) ? unsigned(rng())&live : 0;
            if(__builtin_popcount(cancel)>1) ++multiCancel;
            Input input=valid?inputs[accepted]:Input{0,false,0,0};
            d.set_io$$start$$valid(valid); d.set_io$$start$$bits$$operation(input.op); d.set_io$$start$$bits$$word(input.word);
            d.set_io$$start$$bits$$left(input.a); d.set_io$$start$$bits$$right(input.b);
            d.set_io$$start$$bits$$token$$index((accepted+1)%16); d.set_io$$start$$bits$$token$$tag(UINT64_C(0x8000000000000000) | (accepted+1));
            d.set_io$$start$$bits$$pc(UINT64_C(0x80000000)+4*(accepted+1));
            d.set_io$$cancelMask(cancel); d.set_io$$complete$$ready(ready); d.step();
            check(d.get_io$$liveMask()==live,"live slot ownership mismatch");
            for (const auto &e:pending) if(!e.cancelled)
                check(ownerTag(d,e.slot)==(UINT64_C(0x8000000000000000)|e.tag),"retained full owner mismatch");
            check(bool(d.get_io$$busy())==!pending.empty(),"occupancy/busy mismatch");
            check(bool(d.get_io$$start$$ready())==(pending.size()<8),"reserved capacity ready mismatch");
            const bool response=!pending.empty()&&!pending.front().cancelled&&cycle>=pending.front().due;
            check(bool(d.get_io$$complete$$valid())==response,"pipeline response validity/latency");
            const Expected *preview=nullptr;
            for (const auto &e:pending) if(e.word&&!e.cancelled&&e.previewAt==cycle) preview=&e;
            check(bool(d.get_io$$preview$$valid())==bool(preview),"word preview validity");
            if(preview) {
                check(d.get_io$$preview$$bits$$data()==preview->result,"word preview arithmetic mismatch");
                check(d.get_io$$preview$$bits$$token$$tag()==(UINT64_C(0x8000000000000000)|preview->tag) &&
                      d.get_io$$preview$$bits$$token$$index()==preview->tag%16,"word preview owner mismatch");
            }
            const bool pop=!pending.empty()&&(pending.front().cancelled||(response&&ready));
            if(response) {
                auto e=pending.front();
                check((d.get_io$$complete$$bits$$data() ^ uint64_t(inject))==e.result,"pipelined arithmetic mismatch");
                check(d.get_io$$complete$$bits$$token$$tag()==(UINT64_C(0x8000000000000000)|e.tag) && d.get_io$$complete$$bits$$token$$index()==e.tag%16,
                      "stale or changed response token");
                check(d.get_io$$complete$$bits$$nextPc()==UINT64_C(0x80000000)+4*(e.tag+1)&&!d.get_io$$complete$$bits$$exception(),"completion metadata");
                if(ready && !(cancel&(1U<<e.slot))) ++completed;
                if(!ready) ++held;
            }
            if(cycle<256) check(valid&&d.get_io$$start$$ready(),"one-start-per-cycle throughput bubble");
            if(cycle>=6+inputLatency&&cycle<262+inputLatency) {check(response&&ready,"one-result-per-cycle throughput bubble");++steady;}
            const bool fire=valid&&d.get_io$$start$$ready();
            if(valid&&!d.get_io$$start$$ready()) ++full;
            for(auto &e:pending) if(!e.cancelled&&(cancel&(1U<<e.slot))) {e.cancelled=true;wasCancelled[e.slot]=true;++cancelled;
                if(cycle+1<e.due)++cancelBeforeWrite;else if(cycle+1==e.due)++cancelAtWrite;else ++cancelAfterWrite;}
            if(pop) pending.pop_front();
            if(fire) {
                if(wasCancelled[tail]) {++reusedCancelled;if(cycle-lastAllocation[tail]==8)++denseReuse;wasCancelled[tail]=false;}
                lastAllocation[tail]=cycle;
                pending.push_back({accepted+1,multiplyDivide(input.op,input.word,input.a,input.b),tail,
                    cycle+(input.word?2U:6U)+inputLatency,cycle+1+inputLatency,input.word,false});
                tail=(tail+1)%8;++accepted;
            }
            if(accepted==inputs.size()&&pending.empty()) {if(++drain==10)break;} else drain=0;
        }
        check(accepted==inputs.size()&&pending.empty()&&completed+cancelled==accepted,"drain or response accounting");
        check(denseReuse>100&&cancelBeforeWrite>0&&cancelAtWrite>0&&cancelAfterWrite>0&&reusedCancelled>100&&steady==256&&multiCancel>20&&cancelled>100&&full>100&&held>1000,"pipeline coverage");
        std::cout<<"GSIM PipelinedMultiply: PASS accepted="<<accepted<<" completed="<<completed<<" cancelled="<<cancelled
                 <<" held="<<held<<" full="<<full<<" multiCancel="<<multiCancel<<" steady="<<steady
                 <<" dense_E8_reuse="<<denseReuse<<" cancel_before_at_after="<<cancelBeforeWrite<<","<<cancelAtWrite<<","<<cancelAfterWrite<<" canceled_reuse="<<reusedCancelled<<" active_reset_age="<<resetAge<<" latency_word="<<2+inputLatency<<" latency_full="<<6+inputLatency<<" II=1\n";
        return 0;
    } catch(const std::exception &e) {std::cerr<<"GSIM PipelinedMultiply: FAIL "<<e.what()<<'\n';return 1;}
}

int main(int argc,char** argv) { for(unsigned resetAge: {1U,2U,4U,6U,8U}) if(runCase(argc,argv,resetAge)) return 1; return 0; }
