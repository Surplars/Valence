#define main mixed_regression_main
#include "tilelink_axi4_mixed.cpp"
#undef main
#ifndef FAST_TL_SOURCE
#define FAST_TL_SOURCE 21
#endif
static void headOfLine(STileLinkAxi4Bridge& d) {
 reset(d);
 struct Pending {uint64_t address;unsigned id,beat,due;};
 std::deque<Pending> pending;
 std::optional<unsigned> held;
 std::array<bool,2> live{};std::array<uint64_t,2> address{};std::array<unsigned,2> beats{};
 std::optional<unsigned> dBurst;
 std::optional<std::tuple<uint64_t,unsigned,unsigned>> stalled;
 unsigned sent=0,fastDone=0,slowDone=0,fastBeforeSlow=0,reuseBeforeSlow=0,ar=0,rb=0,db=0,cycle=0;
 bool slowSent=false;
 auto value=[](uint64_t a){return 0xbadc0ffee1234000ULL^(a*0x1010101ULL);};
 for(;cycle<5000&&(fastDone<16||!slowDone);++cycle){
  bool valid=!slowSent||(!live[1]&&sent<16);unsigned source=slowSent?1:0;
  uint64_t a=base+(source?0x2000+sent*64:0x1000);
  if(!held)for(auto it=pending.rbegin();it!=pending.rend();++it)if(cycle>=it->due){held=it->id;break;}
  auto r=std::find_if(pending.begin(),pending.end(),[&](auto& p){return held&&p.id==*held;});
  bool rv=r!=pending.end(),ready=cycle%23<18;
  d.set_io$$tl$$a$$valid(valid);d.set_io$$tl$$a$$bits$$opcode(4);d.set_io$$tl$$a$$bits$$param(0);
  d.set_io$$tl$$a$$bits$$size(6);d.set_io$$tl$$a$$bits$$source(source?FAST_TL_SOURCE:0);d.set_io$$tl$$a$$bits$$address(a);
  d.set_io$$tl$$a$$bits$$mask(255);d.set_io$$tl$$a$$bits$$data(0);d.set_io$$tl$$a$$bits$$corrupt(0);
  d.set_io$$tl$$d$$ready(ready);d.set_io$$axi$$ar$$ready(1);d.set_io$$axi$$aw$$ready(1);d.set_io$$axi$$w$$ready(1);
  d.set_io$$axi$$b$$valid(0);d.set_io$$axi$$r$$valid(rv);d.set_io$$axi$$r$$bits$$id(rv?r->id:0);
  d.set_io$$axi$$r$$bits$$data(rv?value(r->address+8*r->beat):0);d.set_io$$axi$$r$$bits$$last(rv&&r->beat==7);d.set_io$$axi$$r$$bits$$resp(0);
  d.step();
  if(valid&&d.get_io$$tl$$a$$ready()){
   check(!live[source],"HOL source reuse before final D");live[source]=true;address[source]=a-base;beats[source]=0;
   if(source){reuseBeforeSlow+=!slowDone&&sent>0;++sent;}else slowSent=true;
  }
  if(d.get_io$$axi$$ar$$valid()){
   uint64_t addr=d.get_io$$axi$$ar$$bits$$addr();unsigned id=d.get_io$$axi$$ar$$bits$$id();
   check(d.get_io$$axi$$ar$$bits$$len()==7&&d.get_io$$axi$$ar$$bits$$size()==3,"HOL burst attributes");
   check((live[0]&&address[0]==addr)||(live[1]&&address[1]==addr),"HOL AR owner");
   for(auto& old:pending)check(old.id!=id,"HOL live AXI ID reused");
   pending.push_back({addr,id,0,addr==0x1000?400:cycle+1});++ar;
  }
  if(rv&&d.get_io$$axi$$r$$ready()){
   auto owner=std::find_if(pending.begin(),pending.end(),[&](auto&p){return held&&p.id==*held;});check(owner!=pending.end(),"HOL R owner");
   if(++owner->beat==8)pending.erase(owner);held.reset();++rb;
  }
  bool dv=d.get_io$$tl$$d$$valid();auto bits=std::make_tuple(uint64_t(d.get_io$$tl$$d$$bits$$data()),unsigned(d.get_io$$tl$$d$$bits$$source()),unsigned(d.get_io$$tl$$d$$bits$$size()));
  if(stalled)check(dv&&bits==*stalled,"HOL stalled D changed source/data");stalled=dv&&!ready?std::optional{bits}:std::nullopt;
  if(dv&&ready){
   unsigned wireSource=std::get<1>(bits);check(wireSource==0||wireSource==FAST_TL_SOURCE,"HOL full source width lost");unsigned src=wireSource?1:0;check(live[src],"HOL D owner missing");
   if(dBurst)check(*dBurst==src,"TL D burst interleaved");else dBurst=src;
   check(std::get<2>(bits)==6&&std::get<0>(bits)==value(address[src]+8*beats[src])&&!d.get_io$$tl$$d$$bits$$denied(),"HOL independent data oracle");
   ++db;if(++beats[src]==8){live[src]=false;dBurst.reset();if(src){++fastDone;fastBeforeSlow+=!slowDone;}else ++slowDone;}
  }
 }
 check(fastDone==16&&slowDone==1&&ar==17&&rb==136&&db==136&&pending.empty(),"HOL lost transaction/deadlock");
#ifdef UNORDERED_TL
 check(fastBeforeSlow>=8&&reuseBeforeSlow>=8,"completed younger slots did not bypass slow source and reuse holes");
#else
 check(fastBeforeSlow==0&&reuseBeforeSlow==0,"ordered control unexpectedly bypassed oldest request");
#endif
 std::cout<<"HOL_PASS cycles="<<cycle<<" fast_before_slow="<<fastBeforeSlow<<" reused_before_slow="<<reuseBeforeSlow<<std::endl;
}
int main(int argc,char**argv){try{STileLinkAxi4Bridge d;headOfLine(d);return mixed_regression_main(argc,argv);}catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}}
