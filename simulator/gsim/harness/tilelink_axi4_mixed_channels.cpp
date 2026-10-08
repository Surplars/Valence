#include "TileLinkAxi4Bridge.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#ifndef AXI_SLOTS
#define AXI_SLOTS 1
#endif
static void check(bool p,const char *s){if(!p)throw std::runtime_error(s);}
static bool injectMismatch=false;
static constexpr uint64_t base=0x80200000ULL;
static uint64_t data(unsigned n,unsigned b){return 0x987654321abcdef0ULL^(uint64_t(n)<<40)^(uint64_t(b)*0x100100101ULL);}
static unsigned strobe(unsigned b){return b%3==0?0x55:b%3==1?0xaa:0xff;}
static unsigned size(unsigned beats){unsigned n=3;while(beats>1){++n;beats>>=1;}return n;}
static void reset(STileLinkAxi4Bridge &d){
 d.set_io$$tl$$a$$valid(0);d.set_io$$tl$$c$$valid(0);d.set_io$$tl$$e$$valid(0);d.set_io$$tl$$d$$ready(0);
 d.set_io$$axi$$ar$$ready(0);d.set_io$$axi$$r$$valid(0);d.set_io$$axi$$aw$$ready(0);d.set_io$$axi$$w$$ready(0);d.set_io$$axi$$b$$valid(0);
 d.set_reset(1);d.step();d.step();d.set_reset(0);
}
//0 AW first;1 all W before AW;2 slave waits for WVALID;3 simultaneous;4 stalls.
static void transaction(STileLinkAxi4Bridge &d,unsigned n,unsigned beats,unsigned mode,bool error=false,unsigned resetAfter=0){
 unsigned a=0,w=0,aws=0,bs=0,ds=0,awId=0,awCycle=0,lastWCycle=0,firstWCycle=0;
 bool priorWValid=false,priorAwValid=false;
 std::optional<std::tuple<uint64_t,unsigned,unsigned,unsigned>> heldAw;
 std::optional<std::tuple<uint64_t,unsigned,bool>> heldW;
 std::optional<std::tuple<unsigned,unsigned,unsigned,bool,bool,uint64_t>> heldD;
 for(unsigned cycle=0;cycle<1000;++cycle){
  const bool jointReady=priorWValid&&priorAwValid;
  bool awReady=mode==0||(mode==3?jointReady:false)||(mode==1?w==beats:mode==2?priorWValid:mode==4?cycle%7==5:false);
  bool wReady=mode==1||mode==2||(mode==3?(aws||jointReady):false)||(mode==0?aws&&cycle>awCycle+3:mode==4?cycle%5<2:false);
  if(resetAfter==1)wReady=false;
  if(resetAfter==2)awReady=false;
  const bool bv=aws&&w==beats&&cycle>std::max(awCycle,lastWCycle)+2&&!bs;
  const bool dr=cycle%9<4;
  d.set_io$$tl$$a$$valid(a<beats);d.set_io$$tl$$a$$bits$$opcode(1);d.set_io$$tl$$a$$bits$$param(0);
  d.set_io$$tl$$a$$bits$$size(size(beats));d.set_io$$tl$$a$$bits$$source(n%8);d.set_io$$tl$$a$$bits$$address(base+0x80+n*4096ULL);
  d.set_io$$tl$$a$$bits$$data(data(n,a));d.set_io$$tl$$a$$bits$$mask(strobe(a));d.set_io$$tl$$a$$bits$$corrupt(0);
  d.set_io$$tl$$d$$ready(dr);d.set_io$$axi$$aw$$ready(awReady);d.set_io$$axi$$w$$ready(wReady);
  d.set_io$$axi$$b$$valid(bv);d.set_io$$axi$$b$$bits$$id(awId);d.set_io$$axi$$b$$bits$$resp(error?2:0);
  d.set_io$$axi$$ar$$ready(0);d.set_io$$axi$$r$$valid(0);d.step();
  const bool av=d.get_io$$axi$$aw$$valid(),wv=d.get_io$$axi$$w$$valid(),dv=d.get_io$$tl$$d$$valid();
  auto aw=std::make_tuple(uint64_t(d.get_io$$axi$$aw$$bits$$addr()),unsigned(d.get_io$$axi$$aw$$bits$$id()),unsigned(d.get_io$$axi$$aw$$bits$$len()),unsigned(d.get_io$$axi$$aw$$bits$$size()));
  auto wb=std::make_tuple(uint64_t(d.get_io$$axi$$w$$bits$$data()),unsigned(d.get_io$$axi$$w$$bits$$strb()),bool(d.get_io$$axi$$w$$bits$$last()));
  auto db=std::make_tuple(unsigned(d.get_io$$tl$$d$$bits$$source()),unsigned(d.get_io$$tl$$d$$bits$$size()),unsigned(d.get_io$$tl$$d$$bits$$opcode()),bool(d.get_io$$tl$$d$$bits$$denied()),bool(d.get_io$$tl$$d$$bits$$corrupt()),uint64_t(d.get_io$$tl$$d$$bits$$data()));
  if(heldAw)check(av&&aw==*heldAw,"held AW payload changed");if(heldW)check(wv&&wb==*heldW,"held W payload changed");if(heldD)check(dv&&db==*heldD,"held TL D changed");
  heldAw=av&&!awReady?std::optional{aw}:std::nullopt;heldW=wv&&!wReady?std::optional{wb}:std::nullopt;heldD=dv&&!dr?std::optional{db}:std::nullopt;
  if(a<beats&&d.get_io$$tl$$a$$ready())++a;
  check(!d.get_io$$axi$$ar$$valid(),"write emitted AXI read");
  if(av||wv)check(a==beats,"AXI write began before complete TL burst capture");
  if(av&&awReady){check(!aws&&std::get<0>(aw)==0x80+n*4096ULL&&std::get<1>(aw)<AXI_SLOTS&&std::get<2>(aw)==beats-1&&std::get<3>(aw)==3,"AW owner/attributes mismatch");++aws;awId=std::get<1>(aw);awCycle=cycle;}
  if(wv&&wReady){check(w<beats&&std::get<0>(wb)==(data(n,w)^(injectMismatch?1ULL:0ULL))&&std::get<1>(wb)==strobe(w)&&std::get<2>(wb)==(w+1==beats),"W independent payload/strobe/last mismatch");if(!w)firstWCycle=cycle;++w;lastWCycle=cycle;}
  if(bv&&d.get_io$$axi$$b$$ready()){check(aws&&w==beats&&!bs,"B accepted before both channels completed");++bs;}
  if(dv&&dr){check(bs&&a==beats&&!ds&&std::get<0>(db)==n%8&&std::get<1>(db)==size(beats)&&std::get<2>(db)==0&&std::get<3>(db)==error&&!std::get<4>(db)&&!std::get<5>(db),"TL write completion owner/error mismatch");++ds;}
  if((resetAfter==1&&aws)||(resetAfter==2&&w)){check(!bs&&!ds,"partial-channel reset setup already completed");check(resetAfter==1?w==0:aws==0,"reset setup accepted both channels");reset(d);return;}
  if(ds){
   check(aws==1&&w==beats&&bs==1,"lost/duplicate channel transfer");
   if(mode==0)check(awCycle<firstWCycle,"AW-first mode not exercised");
   if(mode==1)check(lastWCycle<awCycle,"W-before-AW mode not exercised");
   if(mode==3)check(awCycle==firstWCycle,"simultaneous mode not exercised");
   std::cout<<"WRITE_CHANNEL_PASS slots="<<AXI_SLOTS<<" mode="<<mode<<" beats="<<beats<<" error="<<error<<"\n";return;
  }
  priorWValid=wv;priorAwValid=av;
 }
 throw std::runtime_error("AW/W channel progress deadline");
}

#ifndef WRITE_CREDITS
#define WRITE_CREDITS 2
#endif
static void queuedWrites(STileLinkAxi4Bridge& d) {
 reset(d);
 constexpr unsigned count=WRITE_CREDITS;
 unsigned a=0, aw=0, w=0, b=0, replies=0, cycle=0;
 std::array<unsigned,count> ids{};
 std::array<bool,count> completed{}, replied{};
 std::optional<std::tuple<uint64_t,unsigned,unsigned>> stalledAw;
 std::optional<std::tuple<uint64_t,unsigned,bool>> stalledW;
 for(;cycle<2000&&replies<count;++cycle) {
  const bool awReady=cycle>=80&&cycle%3!=1, wReady=cycle%5!=2, dr=cycle>=160;
  int chosen=-1;
  if(aw==count&&w==count*2)for(int n=count-1;n>=0;--n)if(!completed[n]){chosen=n;break;}
  d.set_io$$tl$$a$$valid(a<count*2);d.set_io$$tl$$a$$bits$$opcode(1);d.set_io$$tl$$a$$bits$$param(0);
  d.set_io$$tl$$a$$bits$$size(4);d.set_io$$tl$$a$$bits$$source(a/2);
  d.set_io$$tl$$a$$bits$$address(base+(a/2)*128);d.set_io$$tl$$a$$bits$$mask(strobe(a%2));
  d.set_io$$tl$$a$$bits$$data(data(a/2,a%2));d.set_io$$tl$$a$$bits$$corrupt(0);
  d.set_io$$tl$$d$$ready(dr);d.set_io$$axi$$aw$$ready(awReady);d.set_io$$axi$$w$$ready(wReady);
  d.set_io$$axi$$b$$valid(chosen>=0);d.set_io$$axi$$b$$bits$$id(chosen>=0?ids[chosen]:0);
  d.set_io$$axi$$b$$bits$$resp(chosen==1?2:0);d.set_io$$axi$$ar$$ready(0);d.set_io$$axi$$r$$valid(0);
  d.step();
  auto ad=std::make_tuple(uint64_t(d.get_io$$axi$$aw$$bits$$addr()),unsigned(d.get_io$$axi$$aw$$bits$$id()),unsigned(d.get_io$$axi$$aw$$bits$$len()));
  auto wd=std::make_tuple(uint64_t(d.get_io$$axi$$w$$bits$$data()),unsigned(d.get_io$$axi$$w$$bits$$strb()),bool(d.get_io$$axi$$w$$bits$$last()));
  bool av=d.get_io$$axi$$aw$$valid(),wv=d.get_io$$axi$$w$$valid();
  if(stalledAw)check(av&&ad==*stalledAw,"queued stalled AW changed");
  if(stalledW)check(wv&&wd==*stalledW,"queued stalled W changed");
  stalledAw=av&&!awReady?std::optional{ad}:std::nullopt;stalledW=wv&&!wReady?std::optional{wd}:std::nullopt;
  if(a<count*2&&d.get_io$$tl$$a$$ready())++a;
  if(av&&awReady){check(aw<count&&std::get<0>(ad)==aw*128&&std::get<2>(ad)==1,"AW FIFO order mismatch");ids[aw++]=std::get<1>(ad);}
  if(wv&&wReady){check(w<count*2&&std::get<0>(wd)==data(w/2,w%2)&&std::get<1>(wd)==strobe(w%2)&&std::get<2>(wd)==bool(w%2),"ID-less W order mismatch");++w;}
  if(chosen>=0&&d.get_io$$axi$$b$$ready()){completed[chosen]=true;++b;}
  if(d.get_io$$tl$$d$$valid()&&dr){
   unsigned source=d.get_io$$tl$$d$$bits$$source();
#ifndef UNORDERED_TL
   check(source==replies,"FIFO TL completion after inverse B mismatch");
#endif
   check(source<count&&!replied[source]&&completed[source]&&d.get_io$$tl$$d$$bits$$denied()==(source==1),"TL completion owner after inverse B mismatch");replied[source]=true;++replies;
  }
  if(cycle==70)check(a==count*2&&w>=2,"queued write / W-before-AW setup missing");
 }
 check(a==count*2&&aw==count&&w==count*2&&b==count&&replies==count,"queued write lost/duplicate/deadlock");
 std::cout<<"QUEUED_WRITE_PASS credits="<<count<<" inverse_b="<<b<<" held_d_cycles=160\n";
}

static void deniedHead(STileLinkAxi4Bridge& d) {
 reset(d);unsigned accepted=0,replies=0;
 for(unsigned c=0;c<80&&!replies;++c) {
  d.set_io$$tl$$a$$valid(accepted<2);d.set_io$$tl$$a$$bits$$opcode(0);d.set_io$$tl$$a$$bits$$param(0);
  d.set_io$$tl$$a$$bits$$size(4);d.set_io$$tl$$a$$bits$$source(3);
  d.set_io$$tl$$a$$bits$$address(base+0x80000000ULL);d.set_io$$tl$$a$$bits$$mask(255);
  d.set_io$$tl$$a$$bits$$data(0x55);d.set_io$$tl$$a$$bits$$corrupt(0);d.set_io$$tl$$d$$ready(1);
  d.set_io$$axi$$aw$$ready(1);d.set_io$$axi$$w$$ready(1);d.set_io$$axi$$ar$$ready(1);
  d.set_io$$axi$$r$$valid(0);d.set_io$$axi$$b$$valid(0);d.step();
  if(accepted<2&&d.get_io$$tl$$a$$ready())++accepted;
  check(!d.get_io$$axi$$aw$$valid()&&!d.get_io$$axi$$w$$valid()&&!d.get_io$$axi$$ar$$valid(),"denied head emitted AXI");
  if(d.get_io$$tl$$d$$valid()){check(accepted==2&&d.get_io$$tl$$d$$bits$$denied()&&d.get_io$$tl$$d$$bits$$source()==3,"denied head owner/drain");++replies;}
 }
 check(replies==1,"denied head failed to retire while D ready");
 transaction(d,7,2,2);
 std::cout<<"DENIED_WRITE_HEAD_RECOVERY_PASS\n";
}
int main(int argc,char **argv){try{
 injectMismatch=argc>1&&std::string(argv[1])=="--inject-data";
 STileLinkAxi4Bridge d;reset(d);unsigned n=0;
 if(argc>1&&std::string(argv[1])=="--wait-w-only"){transaction(d,n,8,2);return 0;}
 for(unsigned mode=0;mode<5;++mode)for(unsigned beats:{1U,2U,4U,8U,16U})transaction(d,n++,beats,mode,mode==4&&beats==4);
 transaction(d,n++,8,0,false,1);transaction(d,n++,16,3);
 transaction(d,n++,8,1,false,2);transaction(d,n++,16,3);
 queuedWrites(d); deniedHead(d);
 std::cout<<"WRITE_CHANNELS_ALL_PASS reset_after_aw=1 reset_after_w=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"WRITE_CHANNEL_FAIL "<<e.what()<<"\n";return 1;}}
