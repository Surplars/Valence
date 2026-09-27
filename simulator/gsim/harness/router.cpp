#include "CoreRegisterRouter.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
static void check(bool v,const char*m){if(!v)throw std::runtime_error(m);}
struct Request {uint64_t address,data;unsigned size,mask;bool write;};
struct Reply {uint64_t data;bool error;unsigned due;};
int main(int argc,char**){try{
    SCoreRegisterRouter d;std::mt19937_64 random(519);
    d.set_io$$upstream$$request$$valid(0);d.set_io$$upstream$$request$$bits$$address(0);d.set_io$$upstream$$request$$bits$$atomic(0);d.set_io$$upstream$$request$$bits$$atomicOp(0);d.set_io$$upstream$$request$$bits$$data(0);
    d.set_io$$upstream$$request$$bits$$size(0);d.set_io$$upstream$$request$$bits$$mask(0);d.set_io$$upstream$$request$$bits$$write(0);
    d.set_io$$upstream$$response$$ready(0);
    d.set_io$$memory$$request$$ready(0);d.set_io$$registers$$request$$ready(0);
    d.set_io$$memory$$response$$valid(0);d.set_io$$memory$$response$$bits$$data(0);d.set_io$$memory$$response$$bits$$error(0);
    d.set_io$$registers$$response$$valid(0);d.set_io$$registers$$response$$bits$$data(0);d.set_io$$registers$$response$$bits$$error(0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    std::deque<Reply> memory,registers,expected;
    Request request{};bool offer=false,inject=argc>1,held=false;Reply heldReply{};
    unsigned accepted=0,completed=0,maxOutstanding=0,orderedStalls=0,creditStalls=0,stream=0,maxStream=0;
    for(unsigned cycle=0;cycle<40000 || !expected.empty() || offer;++cycle){
        check(cycle<45000,"router drain timeout");
        if(!offer && cycle<40000){
            uint64_t address=(random()&1)?0x0c000000+random()%0x4000:0x80010000+random()%4096;
            if(cycle<300)address=cycle&1?0x0c000004:0x80010000;
            if(cycle%127==0)address=0x0bfffffc;if(cycle%127==1)address=0x0c004000;
            request={address,random(),unsigned(random()%4),unsigned(random()%256),bool(random()&1)};offer=true;
        }
        bool local=request.address>=0x0c000000&&request.address<0x0c004000;
        bool mr=cycle<300||random()%3,rr=cycle<300||random()%4,ready=cycle>=20&&(cycle<300||random()%3);
        bool mv=!memory.empty()&&memory.front().due<=cycle,rv=!registers.empty()&&registers.front().due<=cycle;
        d.set_io$$upstream$$request$$valid(offer);d.set_io$$upstream$$request$$bits$$address(request.address);d.set_io$$upstream$$request$$bits$$data(request.data);
        d.set_io$$upstream$$request$$bits$$size(request.size);d.set_io$$upstream$$request$$bits$$mask(request.mask);d.set_io$$upstream$$request$$bits$$write(request.write);
        d.set_io$$upstream$$response$$ready(ready);
        d.set_io$$memory$$request$$ready(mr);d.set_io$$registers$$request$$ready(rr);
        d.set_io$$memory$$response$$valid(mv);d.set_io$$memory$$response$$bits$$data(mv?memory.front().data:0);d.set_io$$memory$$response$$bits$$error(mv&&memory.front().error);
        d.set_io$$registers$$response$$valid(rv);d.set_io$$registers$$response$$bits$$data(rv?registers.front().data:0);d.set_io$$registers$$response$$bits$$error(rv&&registers.front().error);
        d.step();
        bool response=d.get_io$$upstream$$response$$valid();
        if(held)check(response&&heldReply.data==d.get_io$$upstream$$response$$bits$$data()&&heldReply.error==bool(d.get_io$$upstream$$response$$bits$$error()),"held response changed");
        held=response&&!ready;heldReply={d.get_io$$upstream$$response$$bits$$data(),bool(d.get_io$$upstream$$response$$bits$$error()),0};
        if(response){check(!expected.empty(),"unsolicited response");auto value=d.get_io$$upstream$$response$$bits$$data();if(inject){value^=1;inject=false;}
            check(value==expected.front().data&&bool(d.get_io$$upstream$$response$$bits$$error())==expected.front().error,"ordered response mismatch");
            if(ready){expected.pop_front();++completed;}}
        if(mv&&d.get_io$$memory$$response$$ready())memory.pop_front();
        if(rv&&d.get_io$$registers$$response$$ready())registers.pop_front();
        if(rv&&!d.get_io$$registers$$response$$ready()&&!response)++orderedStalls;
        bool mf=d.get_io$$memory$$request$$valid()&&mr,rf=d.get_io$$registers$$request$$valid()&&rr;
        bool take=offer&&d.get_io$$upstream$$request$$ready();
        check(!(mf&&rf)&&take==(mf||rf),"request handshake routing");
        if(take){check(local==rf,"address decode");unsigned offset=request.address%8;uint64_t factor=UINT64_C(1)<<(offset*8);
            if(local){check(d.get_io$$registers$$request$$bits$$address()==request.address&&d.get_io$$registers$$request$$bits$$data()==request.data/factor&&d.get_io$$registers$$request$$bits$$byteEnable()==request.mask/(1U<<offset)&&d.get_io$$registers$$request$$bits$$size()==request.size&&bool(d.get_io$$registers$$request$$bits$$write())==request.write,"register lane conversion");}
            else check(d.get_io$$memory$$request$$bits$$address()==request.address&&d.get_io$$memory$$request$$bits$$data()==request.data&&d.get_io$$memory$$request$$bits$$mask()==request.mask&&d.get_io$$memory$$request$$bits$$size()==request.size&&bool(d.get_io$$memory$$request$$bits$$write())==request.write,"memory passthrough");
            uint64_t value=random();bool error=random()%7==0;
            unsigned delay=cycle<300?1:local?1+random()%3:5+random()%21;
            (local?registers:memory).push_back({value,error,cycle+delay});
            expected.push_back({local?value*factor:value,error,0});
            ++accepted;offer=false;++stream;if(stream>maxStream)maxStream=stream;
            if(expected.size()>maxOutstanding)maxOutstanding=expected.size();
        }else {stream=0;if(offer&&expected.size()==8)++creditStalls;}
        check(expected.size()<=8,"credit overflow");
    }
    check(accepted==completed&&maxOutstanding==8&&orderedStalls>100&&creditStalls>100&&maxStream>200,"router coverage");
    std::cout<<"GSIM CoreRegisterRouter: PASS requests="<<accepted<<" capacity="<<maxOutstanding<<" stream="<<maxStream<<" orderingStalls="<<orderedStalls<<" creditStalls="<<creditStalls<<"\n";
}catch(const std::exception&e){std::cerr<<"GSIM CoreRegisterRouter: FAIL "<<e.what()<<'\n';return 1;}}
