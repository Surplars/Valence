#include "FloatingPointFullGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
struct Request {
    uint64_t a=0,b=0,c=0,integer=0,value=0,tag=0;
    unsigned inst=0,rm=0,flags=0;bool fault=false;
};
class Driver {
public:
    SFloatingPointFullGsim dut;bool inject=false;
    unsigned cycles=0,verified=0,flushed=0,stalled=0;
    void check(bool good,const std::string& why) {
        if(!good) throw std::runtime_error("FP full mismatch: "+why+" cycle="+std::to_string(cycles));
    }
    void inputs(const Request& r,bool valid,bool ready,bool flush=false) {
        dut.set_io$$flush(flush);dut.set_io$$request$$valid(valid);dut.set_io$$result$$ready(ready);
        dut.set_io$$request$$bits$$a(r.a);dut.set_io$$request$$bits$$b(r.b);dut.set_io$$request$$bits$$c(r.c);
        dut.set_io$$request$$bits$$integer(r.integer);
        dut.set_io$$request$$bits$$instruction(r.inst);dut.set_io$$request$$bits$$rounding(r.rm);
        dut.set_io$$request$$bits$$token$$index(r.tag%16);dut.set_io$$request$$bits$$token$$tag(r.tag);
    }
    void step() {dut.step();++cycles;}
    void reset() {
        inputs({},false,false);dut.set_reset(1);step();step();dut.set_reset(0);step();
    }
    void transaction(const Request& r,unsigned n) {
        inputs(r,true,false);step();check(dut.get_io$$request$$ready(),"idle request credit");
        Request noise=r;noise.a=~r.a;noise.c^=0xabcdef;noise.tag^=1ULL<<40;noise.inst=0x7b;
        bool result=false;
        for(unsigned wait=0;wait<160;++wait) {
            inputs(noise,true,false);step();
            check(!dut.get_io$$request$$ready(),"no premature refill");
            if(dut.get_io$$result$$valid()) {result=true;break;}
        }
        check(result,"bounded response progress");
        auto observe=[&] {
            check(dut.get_io$$result$$valid(),"held response valid");
            check(dut.get_io$$result$$bits$$token$$index()==r.tag%16 &&
                dut.get_io$$result$$bits$$token$$tag()==r.tag,"complete token");
            const uint64_t actual=dut.get_io$$result$$bits$$value() ^ uint64_t(inject&&verified==20);
            if(actual!=r.value || dut.get_io$$result$$bits$$flags()!=r.flags)
                std::cerr<<std::hex<<"inst="<<r.inst<<" rm="<<r.rm<<" a="<<r.a<<" b="<<r.b<<" c="<<r.c
                    <<" int="<<r.integer<<" want="<<r.value<<" got="<<actual<<" flags_want="<<r.flags
                    <<" flags_got="<<dut.get_io$$result$$bits$$flags()<<std::dec<<'\n';
            check(actual==r.value,"SoftFloat value");
            check(dut.get_io$$result$$bits$$flags()==r.flags,"SoftFloat flags");
            check(bool(dut.get_io$$result$$bits$$exception())==r.fault &&
                dut.get_io$$result$$bits$$cause()==(r.fault?2U:0U) &&
                dut.get_io$$result$$bits$$tval()==(r.fault?r.inst:0U),"precise illegal metadata");
        };
        observe();++verified;
        if(n%7==0) for(unsigned stall=0;stall<3;++stall) {inputs(noise,true,false);step();observe();++stalled;}
        if(n%97==0) {inputs(noise,true,true,true);step();check(!dut.get_io$$result$$valid(),"flush suppresses result");++flushed;}
        else {inputs(noise,true,true);step();observe();}
        inputs({},false,true);step();
        check(!dut.get_io$$result$$valid() && dut.get_io$$request$$ready(),"response frees exactly one credit");
    }
    void killIteration(Request r,bool byReset,unsigned delay=1) {
        inputs(r,true,false);step();
        check(dut.get_io$$request$$ready(),"kill request accepted from idle");
        for(unsigned i=0;i<delay;++i){inputs({},false,false);step();}
        if(delay) check(!dut.get_io$$request$$ready(),"iteration occupied");
        if(byReset) reset();
        else {inputs({},false,false,true);step();inputs({},false,true);step();}
        for(unsigned i=0;i<140;++i) {
            inputs({},false,true);step();
            check(!dut.get_io$$result$$valid() && dut.get_io$$request$$ready(),"no stale divider output after kill");
        }
        ++flushed;
    }
};
int main(int argc,char** argv) {try {
    if(argc<2) throw std::runtime_error("vector file required");
    std::string profile=argc>2?argv[2]:"fd";
    Driver d;d.inject=argc>3;d.reset();std::ifstream f(argv[1]);Request r;unsigned n=0;
    while(f>>std::hex>>r.inst>>r.rm>>r.a>>r.b>>r.c>>r.integer>>r.value>>r.flags) {
        r.tag=(1ULL<<40)+n;
        if(profile=="f" && ((r.inst & (1U<<25)) || ((r.inst>>25)==0x20))) {
            r.fault=true;r.value=0;r.flags=0;
        }
        if(profile=="small") {
            const unsigned function=r.inst>>25;
            const bool supported=!(r.inst&(1U<<25)) && (function==0 || function==4 || function==0x10 ||
                function==0x14 || function==0x50 || function==0x70 || function==0x78) &&
                (r.inst&0x7f)==0x53;
            r.fault=!supported;if(r.fault){r.value=0;r.flags=0;}
        }
        d.transaction(r,n++);r.fault=false;
    }
    d.check(f.eof() && n==27840,"all independent vectors checked");
    for(unsigned inst : {0x06000053U,0x04000053U,0x7bU,0x58100053U,0x20003053U,
        0xa0003053U,0xc0400053U,0x40300053U,0x04000043U}) {
        r={};r.inst=inst;r.tag=(1ULL<<42)+n++;r.fault=true;d.transaction(r,n);
    }
    for(unsigned instruction:{0x53U,0x02000053U,0x10000053U,0x18000053U,0x58000053U,
        0x43U,0xc0000053U,0xd0000053U,0x40100053U,0x42000053U}) {
        for(unsigned rm:{5U,6U,7U}) {
            r={};r.inst=instruction;r.rm=rm;r.tag=(1ULL<<43)+n++;r.fault=true;d.transaction(r,n);
        }
    }
    if(profile!="small") {
        r={};r.inst=0x18000053;r.a=r.b=0xffffffff3f800000ULL;r.tag=1ULL<<50;
        d.killIteration(r,false);d.killIteration(r,true);r.value=r.a;d.transaction(r,1);
    }
    // Kill every arithmetic producer before/at each early stage and with a
    // held response. Values are not used as an oracle: no response may survive.
    for(unsigned inst:{0x53U,0x10000053U,0x43U,0xd0200053U,
                       0x02000053U,0x12000053U,0x02000043U,0xd2200053U}) {
        if(profile=="f" && (inst&(1U<<25))) continue;
        if(profile=="small" && inst!=0x53U) continue;
        for(unsigned delay=0;delay<7;++delay) {
            r={};r.inst=inst;r.a=r.b=r.c=(inst&(1U<<25))?
                0x3ff0000000000000ULL:0xffffffff3f800000ULL;
            r.integer=7;r.tag=(1ULL<<51)+delay;
            d.killIteration(r,false,delay);
        }
    }
    d.check(d.verified>=27879 && d.stalled>9000 && d.flushed>280,"coverage");
    std::cout<<"FP_FULL_PASS profile="<<profile<<" vectors=27840 illegal=39 cycles="<<d.cycles
        <<" stalled="<<d.stalled<<" flush="<<d.flushed<<" flags=31 full_token=1 stage_kill=1\n";return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
