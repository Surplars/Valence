#include "MemoryCopyDma.h"
#include <array>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <tuple>
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
struct Test {
 SMemoryCopyDma d; std::array<uint64_t,512> mem{};
 struct Reply {unsigned due; bool write,error; unsigned index; uint64_t data;};
 std::deque<Reply> q; std::mt19937 rng; unsigned cycle=0,requests=0,peak=0,reads=0,writes=0,latency=1;
 uint64_t source=0,destination=0,length=0;unsigned transferReads=0,transferWrites=0;
 int failAt=-1; bool random=false,held=false; std::tuple<uint64_t,uint64_t,bool> offer;
 Test(unsigned seed):rng(seed){
  for(auto&v:mem)v=(uint64_t(rng())<<32)|rng();
  d.set_io$$control$$request$$valid(0);d.set_io$$control$$response$$ready(0);
  d.set_io$$control$$request$$bits$$address(0);d.set_io$$control$$request$$bits$$data(0);
  d.set_io$$control$$request$$bits$$write(0);d.set_io$$control$$request$$bits$$size(3);d.set_io$$control$$request$$bits$$byteEnable(255);
  d.set_reset(1);tick();tick();d.set_reset(0);
 }
 void tick(){
  bool ready=!random||rng()%4!=0,valid=!q.empty()&&q.front().due<=cycle;
  d.set_io$$memory$$request$$ready(ready);d.set_io$$memory$$response$$valid(valid);
  d.set_io$$memory$$response$$bits$$data(valid?q.front().data:0);
  d.set_io$$memory$$response$$bits$$error(valid?q.front().error:false);
  d.step();++cycle;
  if(valid&&d.get_io$$memory$$response$$ready()){
   auto r=q.front();q.pop_front();if(r.write&&!r.error)mem[r.index]=r.data;
  }
  auto next=std::make_tuple(d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),bool(d.get_io$$memory$$request$$bits$$write()));
  if(held)check(d.get_io$$memory$$request$$valid()&&offer==next,"stalled request changed");
  held=d.get_io$$memory$$request$$valid()&&!ready;offer=next;
  if(d.get_io$$memory$$request$$valid()&&ready){
   auto [address,data,write]=next;
   check(address>=0x80010000&&address<0x80011000&&address%8==0,"RAM address");
   check(d.get_io$$memory$$request$$bits$$size()==3&&d.get_io$$memory$$request$$bits$$byteEnable()==255,"memory width");
   check(address==(write?destination+8*transferWrites:source+8*transferReads),"transfer address sequence");
   check(8*(write?transferWrites:transferReads)<length,"transfer exceeded length");
   write?++transferWrites:++transferReads;
   unsigned index=(address-0x80010000)/8;
   bool error=int(requests)==failAt;++requests;write?++writes:++reads;
   q.push_back({cycle+latency+(random?unsigned(rng()%7):0),write,error,index,write?data:mem[index]});
   peak=std::max(peak,unsigned(q.size()));check(q.size()<=4,"credit overflow");
  }
  if(d.get_io$$irq())check(q.empty()&&!held,"interrupt before drain");
 }
 uint64_t access(unsigned offset,bool write=false,uint64_t data=0,bool error=false,unsigned size=3,unsigned mask=255){
  d.set_io$$control$$request$$bits$$address(0x10001000+offset);d.set_io$$control$$request$$bits$$write(write);
  d.set_io$$control$$request$$bits$$data(data);d.set_io$$control$$request$$bits$$size(size);d.set_io$$control$$request$$bits$$byteEnable(mask);
  d.set_io$$control$$request$$valid(1);unsigned wait=0;
  do{tick();check(++wait<1000,"control request timeout");}while(!d.get_io$$control$$request$$ready());
  d.set_io$$control$$request$$valid(0);do{tick();check(++wait<1000,"control response timeout");}while(!d.get_io$$control$$response$$valid());
  auto value=d.get_io$$control$$response$$bits$$data();
  check(bool(d.get_io$$control$$response$$bits$$error())==error,"control error mismatch");
  for(unsigned i=0;i<3;++i){tick();check(d.get_io$$control$$response$$valid()&&value==d.get_io$$control$$response$$bits$$data(),"control response unstable");}
  d.set_io$$control$$response$$ready(1);tick();d.set_io$$control$$response$$ready(0);return value;
 }
 void start(uint64_t s,uint64_t dst,uint64_t n,bool irq=true){access(0,true,s);access(8,true,dst);access(16,true,n);source=s;destination=dst;length=n;transferReads=transferWrites=0;access(24,true,irq?7:3);}
 void finish(bool error=false){unsigned limit=cycle+100000;while(!d.get_io$$irq()){tick();check(cycle<limit,"DMA timeout");}
  check(access(32)==(error?6:2),"completion status");access(24,true,6);tick();check(!d.get_io$$irq()&&access(32)==0,"interrupt clear");}
};
int main(int argc,char**){try{
 unsigned cases=0,total=0,peak=0;
 for(unsigned seed:{0U,17U,8191U})for(unsigned latency:{1U,4U,12U}){
  Test t(seed);t.random=seed!=0;t.latency=latency;
  for(unsigned bytes:{8U,64U,512U,2048U}){
   auto expected=t.mem;for(unsigned i=0;i<bytes/8;++i)expected[256+i]=expected[i];
   if(argc>1)expected[256]^=1;
   auto before=t.requests,begin=t.cycle;t.start(0x80010000,0x80010800,bytes);t.finish();
   check(t.mem==expected,"copy data mismatch");check(t.requests-before==bytes/4,"copy request count");
   if(bytes==2048)std::cout<<"DMA bytes="<<bytes<<" latency="<<latency<<" seed="<<seed<<" cycles="<<t.cycle-begin<<" maxOutstanding="<<t.peak<<"\n";
   ++cases;
  }
  peak=std::max(peak,t.peak);total+=t.requests;
 }
 check(peak==4,"missing multi-outstanding coverage");
 Test t(42);t.random=true;t.latency=100;
 t.start(0x80010000,0x80010800,512);t.access(0,true,0,true);t.access(24,true,0,true);t.finish();
 for(auto desc:{std::array<uint64_t,3>{0x80010000,0x80010800,0}, {0x80010001,0x80010800,8}, {0x80010000,0x80010800,9}, {0x80010000,0x80010008,64}, {0x80010000,0x80010ff8,16}, {0xfffffffffffffff8ULL,0x80010000,16}, {0x80010000,0x80010801,8}}){
  auto before=t.requests;t.start(desc[0],desc[1],desc[2]);t.finish(true);check(t.requests==before,"invalid descriptor side effect");++cases;
 }
 t.start(0x80010000,0x80010800,64,false);
 unsigned limit=t.cycle+10000;while(t.access(32)==1){check(t.cycle<limit,"poll completion timeout");check(!t.d.get_io$$irq(),"disabled IRQ");}
 check(t.access(32)==2&&!t.d.get_io$$irq(),"poll completion status");t.access(24,true,4);t.finish();++cases;
 t.access(32,true,0,true);t.access(40,false,0,true);t.access(0,true,0,true,2);t.access(0,true,0,true,3,15);
 for(unsigned fail:{0U,3U,6U,9U}){
  t.failAt=t.requests+fail;t.start(0x80010000,0x80010800,512);t.finish(true);check(t.q.empty(),"error did not drain");
  t.failAt=-1;auto expected=t.mem;for(unsigned i=0;i<64;++i)expected[256+i]=expected[i];
  t.start(0x80010000,0x80010800,512);t.finish();check(t.mem==expected,"restart after error");++cases;
 }
 std::cout<<"GSIM MemoryCopyDma: PASS cases="<<cases<<" requests="<<total+t.requests<<" maxOutstanding="<<peak<<"\n";
}catch(const std::exception&e){std::cerr<<"GSIM DMA: FAIL "<<e.what()<<"\n";return 1;}}
