#include "PipelinedMultiplyGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>
#include "muldiv_model.h"
static void check(bool ok,const char* message) { if(!ok) throw std::runtime_error(message); }
int main() {
    try {
        SPipelinedMultiplyGsim d;
        d.set_io$$start$$valid(0); d.set_io$$start$$bits$$token$$index(0); d.set_io$$start$$bits$$token$$tag(0);
        d.set_io$$start$$bits$$pc(0); d.set_io$$start$$bits$$operation(0); d.set_io$$start$$bits$$word(0);
        d.set_io$$start$$bits$$left(0); d.set_io$$start$$bits$$right(0);
        d.set_io$$cancelMask(0); d.set_io$$complete$$ready(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        struct Input { unsigned op; bool word; uint64_t a,b; };
        struct Expected { uint64_t tag, result; unsigned slot,due; bool cancelled; };
        const std::array<uint64_t,10> values{0,1,2,UINT64_MAX,UINT64_C(0x8000000000000000),UINT64_C(0x7fffffffffffffff),
            UINT64_C(0x80000000),UINT64_C(0xffffffff),UINT64_C(0xffffffff00000000),UINT64_C(0x123456789abcdef0)};
        std::mt19937_64 rng(64016);
        std::vector<Input> inputs;
        for(unsigned kind=0;kind<5;++kind) for(auto a:values) for(auto b:values)
            inputs.push_back({kind%4,kind==4,a,b});
        for(unsigned i=0;i<2500;++i) { unsigned kind=rng()%5; inputs.push_back({kind%4,kind==4,rng(),rng()}); }
        std::deque<Expected> pending;
        unsigned accepted=0,completed=0,cancelled=0,held=0,full=0,tail=0,steady=0,multiCancel=0,drain=0;
        for(unsigned cycle=0;cycle<30000;++cycle) {
            const bool valid=accepted<inputs.size();
            const bool ready=cycle<300 || (cycle>=350 && rng()%3==0);
            unsigned live=0;
            for(auto e:pending) if(!e.cancelled) live|=1U<<e.slot;
            const unsigned cancel=(cycle>=350 && accepted>=600 && cycle%17==0) ? unsigned(rng())&live : 0;
            if(__builtin_popcount(cancel)>1) ++multiCancel;
            Input input=valid?inputs[accepted]:Input{0,false,0,0};
            d.set_io$$start$$valid(valid); d.set_io$$start$$bits$$operation(input.op); d.set_io$$start$$bits$$word(input.word);
            d.set_io$$start$$bits$$left(input.a); d.set_io$$start$$bits$$right(input.b);
            d.set_io$$start$$bits$$token$$index((accepted+1)%32); d.set_io$$start$$bits$$token$$tag(accepted+1);
            d.set_io$$start$$bits$$pc(UINT64_C(0x80000000)+4*(accepted+1));
            d.set_io$$cancelMask(cancel); d.set_io$$complete$$ready(ready); d.step();
            check(d.get_io$$liveMask()==live,"live slot ownership mismatch");
            check(bool(d.get_io$$busy())==!pending.empty(),"occupancy/busy mismatch");
            check(bool(d.get_io$$start$$ready())==(pending.size()<8),"reserved capacity ready mismatch");
            const bool response=!pending.empty()&&!pending.front().cancelled&&cycle>=pending.front().due;
            check(bool(d.get_io$$complete$$valid())==response,"pipeline response validity/latency");
            const bool pop=!pending.empty()&&(pending.front().cancelled||(response&&ready));
            if(response) {
                auto e=pending.front();
                check(d.get_io$$complete$$bits$$data()==e.result,"pipelined arithmetic mismatch");
                check(d.get_io$$complete$$bits$$token$$tag()==e.tag && d.get_io$$complete$$bits$$token$$index()==e.tag%32,
                      "stale or changed response token");
                check(d.get_io$$complete$$bits$$nextPc()==UINT64_C(0x80000000)+4*(e.tag+1)&&!d.get_io$$complete$$bits$$exception(),"completion metadata");
                if(ready && !(cancel&(1U<<e.slot))) ++completed;
                if(!ready) ++held;
            }
            if(cycle<256) check(valid&&d.get_io$$start$$ready(),"one-start-per-cycle throughput bubble");
            if(cycle>=6&&cycle<262) {check(response&&ready,"one-result-per-cycle throughput bubble");++steady;}
            const bool fire=valid&&d.get_io$$start$$ready();
            if(valid&&!d.get_io$$start$$ready()) ++full;
            for(auto &e:pending) if(!e.cancelled&&(cancel&(1U<<e.slot))) {e.cancelled=true;++cancelled;}
            if(pop) pending.pop_front();
            if(fire) {
                pending.push_back({accepted+1,multiplyDivide(input.op,input.word,input.a,input.b),tail,
                    cycle+(input.word?2U:6U),false});
                tail=(tail+1)%8;++accepted;
            }
            if(accepted==inputs.size()&&pending.empty()) {if(++drain==10)break;} else drain=0;
        }
        check(accepted==inputs.size()&&pending.empty()&&completed+cancelled==accepted,"drain or response accounting");
        check(steady==256&&multiCancel>20&&cancelled>100&&full>100&&held>1000,"pipeline coverage");
        std::cout<<"GSIM PipelinedMultiply: PASS accepted="<<accepted<<" completed="<<completed<<" cancelled="<<cancelled
                 <<" held="<<held<<" full="<<full<<" multiCancel="<<multiCancel<<" steady="<<steady
                 <<" latency_word=2 latency_full=6 II=1\n";
    } catch(const std::exception &e) {std::cerr<<"GSIM PipelinedMultiply: FAIL "<<e.what()<<'\n';return 1;}
}
