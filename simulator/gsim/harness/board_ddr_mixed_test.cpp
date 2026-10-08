// Host-memory-model unit test only; this does not simulate or substitute for RTL.
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
static void check(bool p, const char* m) { if (!p) throw std::runtime_error(m); }
struct Port {
    struct Address { uint64_t addr=0,id=0,len=0,size=3,burst=1; } ar,aw;
    bool arv=false,awv=false,wv=false,rr=false,br=false;
    bool arReady=false,awReady=false,wReady=false,rv=false,bv=false,rl=false,wl=false;
    uint64_t rd=0,rid=0,rresp=0,bid=0,bresp=0,wd=0,wm=255;
    bool get_io$$ddrAxi$$ar$$valid(){return arv;} bool get_io$$ddrAxi$$aw$$valid(){return awv;}
    bool get_io$$ddrAxi$$w$$valid(){return wv;} bool get_io$$ddrAxi$$r$$ready(){return rr;}
    bool get_io$$ddrAxi$$b$$ready(){return br;}
#define ADDR_GET(chan,field) uint64_t get_io$$ddrAxi$$##chan##$$bits$$##field(){return chan.field;}
    ADDR_GET(ar,addr) ADDR_GET(ar,id) ADDR_GET(ar,len) ADDR_GET(ar,size) ADDR_GET(ar,burst)
    ADDR_GET(aw,addr) ADDR_GET(aw,id) ADDR_GET(aw,len) ADDR_GET(aw,size) ADDR_GET(aw,burst)
#undef ADDR_GET
    uint64_t get_io$$ddrAxi$$w$$bits$$data(){return wd;}
    uint64_t get_io$$ddrAxi$$w$$bits$$strb(){return wm;}
    bool get_io$$ddrAxi$$w$$bits$$last(){return wl;}
#define SET(name,field) void set_io$$ddrAxi$$##name(uint64_t v){field=v;}
    SET(ar$$ready,arReady) SET(aw$$ready,awReady) SET(w$$ready,wReady)
    SET(r$$valid,rv) SET(r$$bits$$data,rd) SET(r$$bits$$id,rid) SET(r$$bits$$resp,rresp) SET(r$$bits$$last,rl)
    SET(b$$valid,bv) SET(b$$bits$$id,bid) SET(b$$bits$$resp,bresp)
#undef SET
};
#define BOARD_DDR_BYTES 0x80000000ULL
#include "board_ddr_mixed.h"
int main(int argc,char**argv) {
 try {
  DdrModel m; Port p; uint64_t cycle=0;
  auto tick=[&]{check(cycle<2000,"model deadlock");m.drive(p,cycle++);m.sample(p);};
  if(argc>1&&std::string(argv[1])=="--bad-boundary") { DdrModel::address(4090,2,3,1); return 2; }
  const std::string arg=argc>1?argv[1]:"";
  if(arg=="--duplicate-write") { p.aw={1024,4,1,3,1};p.awv=true;do{tick();}while(!p.awReady);do{tick();}while(!p.awReady);return 2; }
  if(arg=="--bad-wlast") { p.aw={1024,4,1,3,1};p.awv=true;do{tick();}while(!p.awReady);p.awv=false;p.wv=true;p.wl=true;do{tick();}while(!p.wReady);return 2; }
  for(unsigned n=0;n<2;++n) { m.memory[n*64]=100+n;p.ar={n*64,n,0,3,1};p.arv=true;do{tick();}while(!p.arReady); }
  p.arv=false;
  for(unsigned n=0;n<4;++n) { p.aw={1024+n*64,4+n,1,3,1};p.awv=true;do{tick();}while(!p.awReady); }
  p.awv=false;
  check(m.pendingReads.size()==2&&m.pendingWrites.size()==4,"independent credit admission missing");
  for(unsigned n=0;n<4;++n)for(unsigned b=0;b<2;++b) {
   p.wv=true;p.wd=0x123456789abcdef0ULL+n*16+b;p.wm=b?0xaa:0x55;p.wl=b==1;
   do{tick();}while(!p.wReady);
  }
  p.wv=false;
  while(!p.rv||!p.bv)tick();
  auto held=std::make_tuple(p.rd,p.rid,p.rl,p.bid,p.bresp);
  for(unsigned i=0;i<6;++i){tick();check(std::make_tuple(p.rd,p.rid,p.rl,p.bid,p.bresp)==held,"held R/B changed");}
  std::array<bool,8> r{},b{};p.rr=true;p.br=true;
  while(!m.pendingReads.empty()||!m.pendingB.empty()) {
   m.drive(p,cycle++);
   if(p.rv){check(p.rid<2&&!r[p.rid]&&p.rd==100+p.rid&&p.rl,"read owner/data duplicate");r[p.rid]=true;}
   if(p.bv){check(p.bid>=4&&p.bid<8&&!b[p.bid],"B owner duplicate");b[p.bid]=true;}
   m.sample(p);
  }
  for(unsigned n=0;n<4;++n)for(unsigned beat=0;beat<2;++beat) {
   uint64_t expected=0,v=0x123456789abcdef0ULL+n*16+beat;
   for(unsigned k=0;k<8;++k)if((beat?0xaa:0x55)&(1U<<k))expected|=v&(0xffULL<<(8*k));
   check(m.memory.at(1024+n*64+beat*8)==expected,"independent write byte oracle");
  }
  check(m.twoReadTwoWriteCycles&&m.peakWriteIds==4&&m.rBeats==2&&m.wBeats==8&&m.bResponses==4,"mixed count coverage");
  std::cout<<"MIXED_HOST_MODEL_PASS reordered_b="<<m.reorderedB<<" mixed_cycles="<<m.twoReadTwoWriteCycles<<std::endl;
  return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<std::endl;return 1;}
}
