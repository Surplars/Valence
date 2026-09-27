#include "MachineTimer.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
struct Request {uint64_t address=0,data=0;unsigned size=3,mask=255;bool write=false;};
struct Reply {uint64_t data;bool error;};
struct Test {
 SMachineTimer d;Request r;bool offer=false,irq=false,inject=false;uint64_t time=0,compare=~UINT64_C(0);
 std::deque<Reply> expected;unsigned cycles=0,accepted=0,completed=0,held=0,stream=0,maxStream=0,peak=0,edges=0;
 Test(bool corrupt):inject(corrupt){d.set_reset(1);tick(false,false);tick(false,false);d.set_reset(0);}
 bool tick(bool pulse,bool ready){
  d.set_io$$tick(pulse);d.set_io$$mmio$$response$$ready(ready);d.set_io$$mmio$$request$$valid(offer);
  d.set_io$$mmio$$request$$bits$$address(r.address);d.set_io$$mmio$$request$$bits$$data(r.data);
  d.set_io$$mmio$$request$$bits$$write(r.write);d.set_io$$mmio$$request$$bits$$size(r.size);d.set_io$$mmio$$request$$bits$$byteEnable(r.mask);
  d.step();++cycles;check(bool(d.get_io$$irq())==irq,"timer IRQ model mismatch");
  check(d.get_io$$timeValue()==time,"timer time export mismatch");
  if(d.get_io$$mmio$$response$$valid()){
   check(!expected.empty(),"unsolicited response");auto value=d.get_io$$mmio$$response$$bits$$data();if(inject){value^=1;inject=false;}
   check(value==expected.front().data&&bool(d.get_io$$mmio$$response$$bits$$error())==expected.front().error,"timer response mismatch");
   if(ready){expected.pop_front();++completed;}else ++held;
  }
  bool nextIrq=time>=compare;edges+=nextIrq!=irq;irq=nextIrq;
  uint64_t beforeTime=time;if(pulse)++time;
  bool fire=offer&&d.get_io$$mmio$$request$$ready();
  if(fire){
   bool isTime=r.address==0x0200bff8||r.address==0x0200bffc;
   bool isCompare=r.address==0x02004000||r.address==0x02004004;
   bool full=r.size==3&&r.mask==255&&!(r.address&4);
   bool legal=(isTime||isCompare)&&(full||(r.size==2&&r.mask==15));
   uint64_t before=isTime?beforeTime:compare, value=0;
   if(legal){
    if(r.write){uint64_t after=full?r.data:(r.address&4)?((r.data&0xffffffff)<<32)|(before&0xffffffff):(before&0xffffffff00000000ULL)|(r.data&0xffffffff);
     if(isTime)time=after;else compare=after;
    }else value=full?before:(r.address&4)?before>>32:before&0xffffffff;
   }
   expected.push_back({value,!legal});++accepted;maxStream=std::max(maxStream,++stream);peak=std::max(peak,unsigned(expected.size()));
  }else stream=0;
  check(expected.size()<=2,"response capacity");return fire;
 }
 void access(uint64_t address,bool write=false,uint64_t data=0,unsigned size=3,unsigned mask=255,bool pulse=false){
  r={address,data,size,mask,write};offer=true;while(!tick(pulse,false)){}offer=false;
  for(unsigned i=0;i<5;++i)tick(pulse,false);while(!expected.empty())tick(pulse,true);
 }
};
int main(int argc,char**){try{
 Test t(argc>1);std::mt19937_64 rng(7531);
 t.access(0x0200bff8);t.access(0x02004000);
 // Overflow, unsigned comparison, write priority over tick, and half-word preservation.
 t.access(0x0200bff8,true,~UINT64_C(0)-2);t.access(0x02004000,true,~UINT64_C(0));
 for(unsigned i=0;i<5;++i)t.tick(true,true);
 t.access(0x0200bff8,false);t.access(0x02004000,true,0);
 t.access(0x0200bff8,true,0x0123456789abcdef,3,255,true);
 t.access(0x0200bffc,true,0x80000000,2,15,true);t.access(0x0200bff8,true,42,2,15,true);
 t.access(0x0200bff8);t.access(0x0200bffc,false,0,2,15);
 t.access(0x02004004,true,~UINT64_C(0),2,15);t.access(0x02004000,true,~UINT64_C(0),2,15);
 for(unsigned cycle=0;cycle<20000;++cycle){
  if(!t.offer){
   uint64_t address=std::array<uint64_t,6>{0x0200bff8,0x0200bffc,0x02004000,0x02004004,0x02004008,0x0200bff9}[rng()%6];
   unsigned size=rng()%4;unsigned mask=size==3?255:size==2?15:rng()%256;
   t.r={address,rng()%3?rng():t.time+3,size,mask,bool(rng()%2)};t.offer=true;
   if(cycle<500)t.r={0x02004000,~UINT64_C(0),3,255,true};
  }
  if(t.tick(rng()%3,cycle>=20&&(cycle<500||rng()%3)))t.offer=false;
 }
 while(t.offer)if(t.tick(true,true))t.offer=false;
 while(!t.expected.empty())t.tick(true,true);
 check(t.accepted==t.completed&&t.peak==2&&t.maxStream>400&&t.held>100&&t.edges>30,"timer coverage");
 std::cout<<"GSIM MachineTimer: PASS requests="<<t.accepted<<" held="<<t.held<<" stream="<<t.maxStream<<" IRQedges="<<t.edges<<"\n";
}catch(const std::exception&e){std::cerr<<"GSIM timer: FAIL "<<e.what()<<"\n";return 1;}}
