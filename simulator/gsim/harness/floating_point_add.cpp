#include "FloatingPointAddGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
struct Request {uint64_t a=0,b=0,value=0,tag=0;unsigned sub=0,rm=0,flags=0,instruction=0x53;bool fault=false;};
class Driver {
public:
    SFloatingPointAddGsim dut;bool occupied=false,inject=false;Request expected{};unsigned latency=0;
    unsigned cycles=0,accepted=0,retired=0,flushed=0,stalls=0,verified=0;uint64_t lastChecked=0;
    void check(bool good,const char* why) {
        if(!good) throw std::runtime_error(std::string("FP add mismatch: ")+why+" cycle="+std::to_string(cycles));
    }
    void tick(const Request& r={},bool valid=false,bool ready=true,bool flush=false) {
        dut.set_io$$flush(flush);dut.set_io$$request$$valid(valid);dut.set_io$$result$$ready(ready);
        dut.set_io$$request$$bits$$a(r.a);dut.set_io$$request$$bits$$b(r.b);
        dut.set_io$$request$$bits$$instruction(r.instruction);dut.set_io$$request$$bits$$rounding(r.rm);
        dut.set_io$$request$$bits$$token$$index(r.tag%16);dut.set_io$$request$$bits$$token$$tag(r.tag);
        dut.step();
        check(bool(dut.get_io$$request$$ready())==(!occupied&&!flush),"request credit");
        const bool resultValid=occupied&&latency==0&&!flush;
        check(bool(dut.get_io$$result$$valid())==resultValid,"two-cycle result valid/flush");
        if(resultValid) {
            check(dut.get_io$$result$$bits$$token$$index()==expected.tag%16&&
                  dut.get_io$$result$$bits$$token$$tag()==expected.tag,"full token");
            const uint64_t actual=dut.get_io$$result$$bits$$value()^uint64_t(inject&&retired==20);
            if(actual!=expected.value) std::cerr<<std::hex<<"a="<<expected.a<<" b="<<expected.b
                <<" instruction="<<expected.instruction<<" rm="<<expected.rm<<" expected="<<expected.value
                <<" actual="<<actual<<" flags="<<dut.get_io$$result$$bits$$flags()<<std::dec<<'\n';
            check(actual==expected.value,"SoftFloat value");
            check(dut.get_io$$result$$bits$$flags()==expected.flags,"SoftFloat flags");
            check(bool(dut.get_io$$result$$bits$$exception())==expected.fault&&
                  dut.get_io$$result$$bits$$cause()==(expected.fault?2U:0U)&&
                  dut.get_io$$result$$bits$$tval()==(expected.fault?expected.instruction:0U),"illegal metadata");
            if(expected.tag!=lastChecked) {lastChecked=expected.tag;++verified;}
            if(!ready) ++stalls;
        }
        const bool take=valid&&!occupied&&!flush;
        if(resultValid&&ready) {occupied=false;++retired;}
        if(occupied&&latency) --latency;
        if(take) {occupied=true;latency=1;expected=r;++accepted;}
        if(flush) {if(occupied) ++flushed;occupied=false;latency=0;}
        ++cycles;
    }
    void reset() {
        dut.set_io$$request$$valid(false);dut.set_io$$result$$ready(false);dut.set_io$$flush(false);
        dut.set_reset(1);dut.step();dut.step();dut.set_reset(0);occupied=false;latency=0;tick();
    }
    void transaction(Request r,unsigned i) {
        tick(r,true); // capture request
        Request noise=r;noise.a^=0xabcdef;noise.b=~r.b;noise.tag^=0x100000000ULL;noise.rm=7;
        tick(noise,true,false); // raw stage: blocked refill, no premature result
        if(i%7==0) {tick(noise,true,false);tick(noise,true,false);} // held result and blocked refill
        // Check every vector numerically before cancelling its buffered result.
        if(i%97==0) {tick(noise,true,false);tick(noise,true,true,true);tick();return;}
        tick(noise,true); // occupied cannot refill on the retirement edge
        tick();
    }
};
int main(int argc,char** argv) {try {
    if(argc<2) throw std::runtime_error("vector file required");
    Driver d;d.inject=argc>2;d.reset();std::ifstream f(argv[1]);Request r;unsigned n=0;
    while(f>>std::hex>>r.a>>r.b>>r.sub>>r.rm>>r.value>>r.flags) {
        r.tag=0x100000000ULL+n;r.instruction=(r.sub?0x08000000:0)|0x53;
        d.transaction(r,n++);
    }
    d.check(f.eof()&&n==34840&&d.verified==34840,"all vectors numerically checked");
    for(unsigned rm=5;rm<8;++rm) {r={};r.rm=rm;r.tag=++n;r.fault=true;d.transaction(r,n);}
    for(unsigned instruction: {0x02000053U,0x10000053U,0x7bU}) {
        r={};r.instruction=instruction;r.tag=++n;r.fault=true;d.transaction(r,n);
    }
    // Reset drops a held result, then a new generation can make progress.
    r={};r.tag=++n;r.a=r.b=0xffffffff00000000ULL;r.value=r.a;
    d.tick(r,true);d.tick({},false,false);d.tick({},false,false);d.reset();d.transaction(r,1);
    // Kill/reset during the raw stage, then require progress with a fresh owner.
    d.tick(r,true);d.tick({},false,true,true);d.tick();d.transaction(r,2);
    d.tick(r,true);d.reset();d.transaction(r,3);
    d.check(d.accepted>34000&&d.retired>33000&&d.flushed>300&&d.stalls>9000,"coverage");
    std::cout<<"FP_ADD_PASS vectors=34840 cycles="<<d.cycles<<" accepted="<<d.accepted
             <<" retired="<<d.retired<<" flushed="<<d.flushed<<" stalled="<<d.stalls
             <<" illegal=6 latency=2 min_ii=3 reset_held=1 flush_raw=1 reset_raw=1\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
