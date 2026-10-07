#include "StagedFabricGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
static void check(bool v,const char* m){if(!v)throw std::runtime_error(m);}
struct Request {
 uint64_t address=0,data=0;unsigned size=0,mask=0,op=0;
 bool write=false,atomic=false,virtualized=false,uncached=false,cpu=false;
 bool operator==(const Request&)const=default;
};
struct Reply {uint64_t data=0;bool error=false,page=false;unsigned due=0;};
struct Pending {Request request;Reply reply;};
static unsigned decode(const Request&r){
 if(r.atomic)return 0;
 if(r.address>=0x02000000&&r.address<0x02010000)return 1;
 if(r.address>=0x10000000&&r.address<0x10000008)return 2;
 if(r.address>=0x10001000&&r.address<0x10001028)return 3;
 return 0;
}
static void manager(SStagedFabricGsim& d,unsigned p,bool ready,const std::optional<Reply>& r){
 if(p==0){
  d.set_io$$memory$$request$$ready(ready);d.set_io$$memory$$response$$valid(bool(r));
  d.set_io$$memory$$response$$bits$$data(r?r->data:0);
  d.set_io$$memory$$response$$bits$$error(r&&r->error);d.set_io$$memory$$response$$bits$$pageFault(r&&r->page);
  return;
 }
#define PORT(N) case N+1: d.set_io$$reg##N##$$request$$ready(ready); \
 d.set_io$$reg##N##$$response$$valid(bool(r));d.set_io$$reg##N##$$response$$bits$$data(r?r->data:0); \
 d.set_io$$reg##N##$$response$$bits$$error(r&&r->error);break;
 switch(p){PORT(0);PORT(1);PORT(2);default:throw std::runtime_error("port");}
#undef PORT
}
static bool requestValid(SStagedFabricGsim& d,unsigned p){
 if(p==0)return d.get_io$$memory$$request$$valid();
 switch(p){case 1:return d.get_io$$reg0$$request$$valid();case 2:return d.get_io$$reg1$$request$$valid();default:return d.get_io$$reg2$$request$$valid();}
}
static bool responseReady(SStagedFabricGsim& d,unsigned p){
 if(p==0)return d.get_io$$memory$$response$$ready();
 switch(p){case 1:return d.get_io$$reg0$$response$$ready();case 2:return d.get_io$$reg1$$response$$ready();default:return d.get_io$$reg2$$response$$ready();}
}
static Request bus(SStagedFabricGsim& d,unsigned p){
 Request r;
 if(p==0){
  r.address=d.get_io$$memory$$request$$bits$$address();r.data=d.get_io$$memory$$request$$bits$$data();
  r.size=d.get_io$$memory$$request$$bits$$size();r.mask=d.get_io$$memory$$request$$bits$$mask();
  r.write=d.get_io$$memory$$request$$bits$$write();r.atomic=d.get_io$$memory$$request$$bits$$atomic();
  r.op=d.get_io$$memory$$request$$bits$$atomicOp();r.virtualized=d.get_io$$memory$$request$$bits$$virtualized();
  r.uncached=d.get_io$$memory$$request$$bits$$uncached();r.cpu=d.get_io$$memoryCpu();return r;
 }
#define PORT(N) case N+1:r.address=d.get_io$$reg##N##$$request$$bits$$address(); \
 r.data=d.get_io$$reg##N##$$request$$bits$$data();r.size=d.get_io$$reg##N##$$request$$bits$$size(); \
 r.mask=d.get_io$$reg##N##$$request$$bits$$byteEnable();r.write=d.get_io$$reg##N##$$request$$bits$$write();break;
 switch(p){PORT(0);PORT(1);PORT(2);}
#undef PORT
 return r;
}
int main(int argc,char**){try{
 SStagedFabricGsim d;std::mt19937_64 random(731);
 std::array<std::deque<Reply>,4> replies;std::deque<Reply> expected;std::deque<Pending> pending;
 std::array<unsigned,4> counts{};std::optional<Request> heldMemory;std::optional<Reply> heldReply;
 Request r;bool offer=false,inject=argc>1;unsigned accepted=0,completed=0,peak=0,bufferPeak=0,stream=0,maxStream=0,atomics=0;
 d.set_io$$upstream$$request$$valid(0);d.set_io$$upstream$$response$$ready(0);
 for(unsigned p=0;p<4;++p)manager(d,p,false,std::nullopt);
 d.set_reset(1);d.step();d.step();d.set_reset(0);
 for(unsigned cycle=0;cycle<30000||offer||!expected.empty();++cycle){
  check(cycle<35000,"fabric drain timeout");
  if(!offer&&cycle<30000){
   r={};unsigned choice=random()%9;
   if(cycle<300)r.address=0x80200000+(cycle%32)*8;
   else if(choice==0)r.address=0x02000000+random()%65536;
   else if(choice==1)r.address=0x10000000+random()%8;
   else if(choice==2)r.address=0x10001000+random()%40;
   else if(choice==3)r.address=0x02010000;
   else if(choice==4)r.address=0x10000008;
   else if(choice==5)r.address=0x10001028;
   else if(choice==6)r.address=0x01fffff8;
   else r.address=UINT64_C(0xff00000080200000)+random()%4096;
   r.data=random();r.size=random()%4;r.mask=random()%256;r.op=random()%32;
   r.write=random()&1;r.atomic=cycle>=300&&random()%11==0;
   r.virtualized=random()&1;r.uncached=random()&1;r.cpu=random()&1;offer=true;
  }
  std::array<bool,4> ready{};std::array<std::optional<Reply>,4> returns{};
  for(unsigned p=0;p<4;++p){
   ready[p]=cycle<300?!(p==0&&cycle>=260&&cycle<280):random()%4!=0;
   if(!replies[p].empty()&&replies[p].front().due<=cycle)returns[p]=replies[p].front();
   manager(d,p,ready[p],returns[p]);
  }
  bool sinkReady=cycle>=30&&(cycle<300||random()%3!=0);
  d.set_io$$upstream$$request$$valid(offer);d.set_io$$upstream$$request$$bits$$address(r.address);
  d.set_io$$upstream$$request$$bits$$data(r.data);d.set_io$$upstream$$request$$bits$$size(r.size);
  d.set_io$$upstream$$request$$bits$$mask(r.mask);d.set_io$$upstream$$request$$bits$$write(r.write);
  d.set_io$$upstream$$request$$bits$$atomic(r.atomic);d.set_io$$upstream$$request$$bits$$atomicOp(r.op);
  d.set_io$$upstream$$request$$bits$$virtualized(r.virtualized);d.set_io$$upstream$$request$$bits$$uncached(r.uncached);
  d.set_io$$requestCpu(r.cpu);d.set_io$$upstream$$response$$ready(sinkReady);d.step();
  bool rv=d.get_io$$upstream$$response$$valid();
  Reply out{d.get_io$$upstream$$response$$bits$$data(),bool(d.get_io$$upstream$$response$$bits$$error()),bool(d.get_io$$upstream$$response$$bits$$pageFault())};
  if(heldReply)check(rv&&out.data==heldReply->data&&out.error==heldReply->error&&out.page==heldReply->page,"held fabric response changed");
  heldReply=rv&&!sinkReady?std::optional<Reply>(out):std::nullopt;
  if(rv){
   check(!expected.empty(),"unsolicited fabric reply");auto actual=out.data;if(inject){actual^=1;inject=false;}
   check(actual==expected.front().data&&out.error==expected.front().error&&out.page==expected.front().page,"fabric response mismatch");
   if(sinkReady){expected.pop_front();++completed;}
  }
  for(unsigned p=0;p<4;++p)if(returns[p]&&responseReady(d,p))replies[p].pop_front();
  unsigned selected=decode(r);bool take=offer&&d.get_io$$upstream$$request$$ready();
  if(take){
   Reply reply{random(),random()%7==0,selected==0&&random()%13==0};Reply wanted=reply;
   if(selected)wanted.data<<=(r.address&7)*8;
   expected.push_back(wanted);++accepted;++counts[selected];if(r.atomic)++atomics;
   if(selected){reply.due=cycle+(cycle<300?1:1+random()%12);replies[selected].push_back(reply);}
   else pending.push_back({r,reply});
   offer=false;maxStream=std::max(maxStream,++stream);
  }else stream=0;
  for(unsigned p=1;p<4;++p){
   bool fire=requestValid(d,p)&&ready[p];check(fire==(take&&selected==p),"local request duplicated/lost");
   if(fire){Request want;want.address=r.address;want.data=r.data>>((r.address&7)*8);want.size=r.size;
    want.mask=r.mask>>(r.address&7);want.write=r.write;check(bus(d,p)==want,"register byte lanes");}
  }
  bool memoryValid=requestValid(d,0);Request memory=bus(d,0);
  if(heldMemory)check(memoryValid&&memory==*heldMemory,"buffered request/CPU classification changed");
  heldMemory=memoryValid&&!ready[0]?std::optional<Request>(memory):std::nullopt;
  if(memoryValid&&ready[0]){
   check(!pending.empty()&&memory==pending.front().request,"buffered memory request mismatch");
   auto reply=pending.front().reply;reply.due=cycle+(cycle<300?1:1+random()%25);
   replies[0].push_back(reply);pending.pop_front();
  }
  peak=std::max(peak,unsigned(expected.size()));bufferPeak=std::max(bufferPeak,unsigned(pending.size()));
  check(expected.size()<=8&&pending.size()<=2,"fabric capacity exceeded");
 }
 check(accepted==completed&&peak==8&&bufferPeak==2&&maxStream>150&&atomics>100,"fabric coverage");
 for(unsigned n:counts)check(n>100,"destination coverage");
 check(pending.empty(),"pending memory request lost");for(auto&q:replies)check(q.empty(),"unconsumed manager reply");
 std::cout<<"GSIM staged fabric: PASS requests="<<accepted<<" owners="<<peak<<" requestBuffer="<<bufferPeak<<" stream="<<maxStream<<" atomicBypass="<<atomics<<" ports="<<counts[0]<<","<<counts[1]<<","<<counts[2]<<","<<counts[3]<<"\n";
}catch(const std::exception&e){std::cerr<<"GSIM staged fabric: FAIL "<<e.what()<<"\n";return 1;}}
