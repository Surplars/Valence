#include <cstdint>
#include <unordered_map>
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <string>
static void check(bool p,const char *s){if(!p)throw std::runtime_error(s);}
#include "fake_axi.h"
#include "on-host/harness/board_ddr_benchmark.h"
struct Rig {
 DdrModel m; Fake d;
 Rig(){d.io$$ddrAxi$$r$$ready=1;for(unsigned i=0;i<4;++i){m.memory[0x100+8*i]=0xa0+i;m.memory[0x200+8*i]=0xb0+i;m.memory[0x300+8*i]=0xc0+i;}}
 void ar(uint64_t cycle,unsigned id,unsigned pa){d.io$$ddrAxi$$ar$$valid=1;d.io$$ddrAxi$$ar$$bits$$id=id;d.io$$ddrAxi$$ar$$bits$$addr=pa;d.io$$ddrAxi$$ar$$bits$$len=3;d.io$$ddrAxi$$ar$$bits$$size=3;d.io$$ddrAxi$$ar$$bits$$burst=1;m.drive(d,cycle);check(m.arReady,"test AR not accepted");m.sample(d);d.io$$ddrAxi$$ar$$valid=0;}
 void beat(uint64_t cycle,unsigned id,uint64_t value,bool last){m.drive(d,cycle);check(m.rValid,"missing scheduled beat");check(d.io$$ddrAxi$$r$$bits$$id==id,"interleaved or reordered burst ID");check(d.io$$ddrAxi$$r$$bits$$data==value,"held/data byte order changed");check(bool(d.io$$ddrAxi$$r$$bits$$last)==last,"LAST before expected beat count");m.sample(d);}
};
int main(int argc,char **argv){try{
 const std::string mutation=argc>1?argv[1]:"";
 {Rig r;r.ar(0,1,0x100);r.ar(1,2,0x200);r.m.drive(r.d,31);check(!r.m.rValid,"response before original 32-cycle eligibility");
  r.beat(32,1,0xa0,false);if(mutation=="--inject-unlock")r.m.lockedRead.reset();
  for(unsigned i=1;i<4;++i)r.beat(32+i,1,0xa0+i,i==3);
  for(unsigned i=0;i<4;++i)r.beat(36+i,2,0xb0+i,i==3);
  check(r.m.pendingReads.empty()&&!r.m.lockedRead&&r.m.rBeats==8,"burst release/accounting");}
 {Rig r;r.ar(0,1,0x100);r.ar(1,2,0x200);for(unsigned i=0;i<4;++i)r.beat(40+i,2,0xb0+i,i==3);for(unsigned i=0;i<4;++i)r.beat(44+i,1,0xa0+i,i==3);}
 {Rig r;r.m.denyReadAddress=0x100;r.ar(0,1,0x100);r.ar(1,2,0x200);r.d.io$$ddrAxi$$r$$ready=0;r.m.drive(r.d,32);r.m.sample(r.d);
  if(mutation=="--inject-held-data")r.m.heldReadData^=1;
  for(unsigned c=33;c<36;++c){r.m.drive(r.d,c);check(r.d.io$$ddrAxi$$r$$bits$$id==1&&r.d.io$$ddrAxi$$r$$bits$$data==0xa0&&!r.d.io$$ddrAxi$$r$$bits$$last&&r.d.io$$ddrAxi$$r$$bits$$resp==0,"held R payload changed");r.m.sample(r.d);}
  r.d.io$$ddrAxi$$r$$ready=1;for(unsigned i=0;i<3;++i)r.beat(36+i,1,0xa0+i,false);
  r.d.io$$ddrAxi$$r$$ready=0;
  for(unsigned c=39;c<43;++c){r.m.drive(r.d,c);check(r.d.io$$ddrAxi$$r$$bits$$id==1&&r.d.io$$ddrAxi$$r$$bits$$data==0xa3&&r.d.io$$ddrAxi$$r$$bits$$last&&r.d.io$$ddrAxi$$r$$bits$$resp==2,"held LAST payload/RESP changed or burst released early");r.m.sample(r.d);if(c==39&&mutation=="--inject-last-release"){r.m.lockedRead.reset();r.m.heldRead.reset();}}
  r.d.io$$ddrAxi$$r$$ready=1;r.beat(43,1,0xa3,true);for(unsigned i=0;i<4;++i)r.beat(44+i,2,0xb0+i,i==3);}
 {Rig r;r.ar(0,1,0x100);bool caught=false;try{r.ar(1,1,0x200);}catch(const std::runtime_error &e){caught=std::string(e.what())=="DDR live read ID reused";}check(caught,"duplicate live ID was not rejected");}
 {Rig r;r.ar(0,1,0x100);r.m.drive(r.d,32);r.m.sample(r.d);r.m.drive(r.d,32);check(!r.m.rValid,"beat gap eligibility bypassed");r.beat(33,1,0xa1,false);r.beat(34,1,0xa2,false);r.beat(35,1,0xa3,true);}
 std::cout<<"LAW_CONTROLS_PASS cases=5\n";return 0;
 }catch(const std::exception &e){std::cerr<<"LAW_CONTROLS_FAIL "<<e.what()<<"\n";return 1;}}
