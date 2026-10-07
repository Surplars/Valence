#include "SharedDataGsim.h"
#include <array>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
#ifndef REGISTERED_PHYSICAL_OWNERS
#define REGISTERED_PHYSICAL_OWNERS 0
#endif
#define SET(i,field,v) do {if(i)d.set_io$$client1$$##field(v);else d.set_io$$client0$$##field(v);}while(0)
#define GET(i,field) (i?d.get_io$$client1$$##field():d.get_io$$client0$$##field())
struct Request {uint64_t address,data; unsigned size,mask;bool write,atomic;unsigned atomicOp;
 bool virtualized,uncached;bool operator==(const Request&)const=default;};
struct Reply {unsigned owner,due;uint64_t data;bool error,pageFault;};
int main(int argc,char**){try{
 SSharedDataGsim d;std::mt19937_64 rng(519);std::array<Request,2> req{};std::array<bool,2> offer{},ready{};
 std::deque<Reply> q;unsigned accepted=0,completed=0,peak=0,fair=0,stalls=0,stream=0,maxStream=0,turn=0;
 bool held=false;Request previous{};
 for(unsigned i=0;i<2;++i){SET(i,request$$valid,0);SET(i,request$$bits$$address,0);SET(i,request$$bits$$data,0);SET(i,request$$bits$$write,0);SET(i,request$$bits$$size,0);SET(i,request$$bits$$mask,0);SET(i,request$$bits$$atomic,0);SET(i,request$$bits$$atomicOp,0);SET(i,request$$bits$$virtualized,0);SET(i,request$$bits$$uncached,0);SET(i,response$$ready,0);}
 d.set_io$$memory$$request$$ready(0);d.set_io$$memory$$response$$valid(0);d.set_io$$memory$$response$$bits$$data(0);d.set_io$$memory$$response$$bits$$error(0);
 d.set_io$$memory$$response$$bits$$pageFault(0);
 d.set_reset(1);d.step();d.step();d.set_reset(0);
 // Independent zero-latency manager: retain valid/data until accepted. A
 // registered owner may delay this reply by one cycle, never lose/misroute it.
 for(unsigned owner=0;owner<2;++owner){
  const uint64_t data=0x9182736455aa00ffULL+owner;
  SET(owner,request$$valid,1);SET(owner,request$$bits$$address,0x80010040+owner*8);
  SET(owner,response$$ready,owner==0);
  d.set_io$$memory$$request$$ready(1);d.set_io$$memory$$response$$valid(1);
  d.set_io$$memory$$response$$bits$$data(data);d.set_io$$memory$$response$$bits$$error(1);
  d.set_io$$memory$$response$$bits$$pageFault(1);d.step();
  check(GET(owner,request$$ready)&&d.get_io$$memory$$request$$valid(),"immediate request not accepted");
  check(bool(GET(owner,response$$valid))==!REGISTERED_PHYSICAL_OWNERS,"empty-owner latency contract");
  check(!GET(!owner,response$$valid),"immediate response owner mismatch");
  bool consumed=d.get_io$$memory$$response$$ready();
  SET(owner,request$$valid,0);d.set_io$$memory$$request$$ready(0);
  if(!consumed){
   for(unsigned stall=0;stall<3;++stall){
    d.step();check(GET(owner,response$$valid)&&!GET(!owner,response$$valid),"held response owner mismatch");
    auto value=GET(owner,response$$bits$$data);if(argc>1)value^=1;
    check(value==data&&GET(owner,response$$bits$$error)&&GET(owner,response$$bits$$pageFault),"response data mismatch");
    if(d.get_io$$memory$$response$$ready()){consumed=true;break;}
   }
   if(!consumed){SET(owner,response$$ready,1);d.step();check(d.get_io$$memory$$response$$ready(),"held reply not drained");}
  }else{
   auto value=GET(owner,response$$bits$$data);if(argc>1)value^=1;
   check(value==data&&GET(owner,response$$bits$$error)&&GET(owner,response$$bits$$pageFault),"response data mismatch");
  }
  d.set_io$$memory$$response$$valid(0);d.step();
  check(!GET(0,response$$valid)&&!GET(1,response$$valid),"duplicate immediate reply");
 }
 SET(0,response$$ready,0);SET(1,response$$ready,0);
 d.set_reset(1);d.step();d.step();d.set_reset(0);
 for(unsigned cycle=0;cycle<40000||!q.empty()||offer[0]||offer[1];++cycle){
  check(cycle<45000,"drain timeout");
  for(unsigned i=0;i<2;++i){
   if(!offer[i]&&cycle<40000&&(cycle<500||rng()%3)){req[i]={0x80010000+8*(rng()%512),rng(),unsigned(rng()%4),unsigned(rng()%256),bool(rng()%2),bool(rng()%2),unsigned(rng()%32),bool(rng()%2),bool(rng()%2)};offer[i]=true;}
   ready[i]=cycle>=20&&(cycle<500||rng()%3);
   SET(i,request$$bits$$atomic,req[i].atomic);SET(i,request$$bits$$atomicOp,req[i].atomicOp);SET(i,request$$bits$$virtualized,req[i].virtualized);SET(i,request$$bits$$uncached,req[i].uncached);SET(i,request$$valid,offer[i]);SET(i,request$$bits$$address,req[i].address);SET(i,request$$bits$$data,req[i].data);
   SET(i,request$$bits$$write,req[i].write);SET(i,request$$bits$$size,req[i].size);SET(i,request$$bits$$mask,req[i].mask);SET(i,response$$ready,ready[i]);
  }
  bool mr=cycle<500||rng()%4,mv=!q.empty()&&q.front().due<=cycle;
  d.set_io$$memory$$request$$ready(mr);d.set_io$$memory$$response$$valid(mv);
  d.set_io$$memory$$response$$bits$$data(mv?q.front().data:0);d.set_io$$memory$$response$$bits$$error(mv&&q.front().error);d.set_io$$memory$$response$$bits$$pageFault(mv&&q.front().pageFault);d.step();
  for(unsigned i=0;i<2;++i)if(GET(i,response$$valid)){
   check(mv&&i==q.front().owner,"response owner mismatch");auto value=GET(i,response$$bits$$data);if(argc>1)value^=1;
   check(value==q.front().data&&bool(GET(i,response$$bits$$error))==q.front().error&&bool(GET(i,response$$bits$$pageFault))==q.front().pageFault,"response data mismatch");
  }
  if(mv&&d.get_io$$memory$$response$$ready()){check(ready[q.front().owner]&&GET(q.front().owner,response$$valid),"response handshake");q.pop_front();++completed;}
  bool a=offer[0]&&GET(0,request$$ready),b=offer[1]&&GET(1,request$$ready),fire=d.get_io$$memory$$request$$valid()&&mr;
  check(!(a&&b)&&fire==(a||b),"request handshake");
  Request current{d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),d.get_io$$memory$$request$$bits$$size(),d.get_io$$memory$$request$$bits$$mask(),bool(d.get_io$$memory$$request$$bits$$write()),bool(d.get_io$$memory$$request$$bits$$atomic()),d.get_io$$memory$$request$$bits$$atomicOp(),bool(d.get_io$$memory$$request$$bits$$virtualized()),bool(d.get_io$$memory$$request$$bits$$uncached())};
  if(held)check(d.get_io$$memory$$request$$valid()&&current==previous,"stalled request changed");
  bool wasHeld=held;held=d.get_io$$memory$$request$$valid()&&!mr;previous=current;stalls+=held;
  if(fire){unsigned owner=b;check(current==req[owner],"request data mismatch");
   if(offer[0]&&offer[1]&&!wasHeld){check(owner==turn,"round robin fairness");++fair;}
   turn=!owner;offer[owner]=false;++accepted;
   q.push_back({owner,cycle+(cycle<500?1:unsigned(1+rng()%30)),rng(),bool(rng()%7==0),bool(rng()%11==0)});
   peak=std::max(peak,unsigned(q.size()));maxStream=std::max(maxStream,++stream);
  }else stream=0;
  check(q.size()<=8,"credit overflow");
 }
 check(accepted==completed&&peak==8&&fair>1000&&stalls>100&&maxStream>400,"coverage");
 std::cout<<"GSIM SharedDataArbiter: PASS registeredOwners="<<REGISTERED_PHYSICAL_OWNERS<<" immediateReplies=2 requests="<<accepted<<" maxOutstanding="<<peak<<" fairGrants="<<fair<<" backpressure="<<stalls<<" stream="<<maxStream<<"\n";
}catch(const std::exception&e){std::cerr<<"GSIM SharedDataArbiter: FAIL "<<e.what()<<"\n";return 1;}}
