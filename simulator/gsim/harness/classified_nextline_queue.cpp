#include "ClassifiedNextLineQueueGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>
using U128=unsigned __int128;
#ifndef RAM_BASE
#define RAM_BASE 0x80200000ULL
#endif
#ifndef RAM_BYTES
#define RAM_BYTES 0x80000000ULL
#endif
static bool grant(uint64_t a,uint64_t boundary,unsigned mode,unsigned priv,bool fault){
 U128 next=(U128(a)/64+1)*64;
 if(fault||U128(a)<RAM_BASE||U128(a)+8>U128(RAM_BASE)+RAM_BYTES||next+64>U128(RAM_BASE)+RAM_BYTES||next/4096!=U128(a)/4096)return false;
 std::array<unsigned,2> cfg{};std::array<uint64_t,2> pa{};
 if(mode==1)cfg[0]=0x1f;if(mode==2)cfg[0]=0x18;if(mode==3)cfg[0]=0x98;
 if(mode<=3)pa[0]=(1ULL<<54)-1;else pa[0]=(boundary>>2)&((1ULL<<54)-1);
 if(mode==4){cfg[0]=0x11;cfg[1]=0x1f;pa[1]=(1ULL<<54)-1;}
 if(mode==5)cfg[0]=0x09;if(mode==6){cfg[1]=0x09;pa[1]=0;}
 for(unsigned i=0;i<2;i++){
  unsigned type=(cfg[i]>>3)&3;if(!type)continue;U128 lo,hi;
  if(type==1){lo=i?U128(pa[i-1])*4:0;hi=U128(pa[i])*4;if(hi<=lo)continue;--hi;}
  else if(type==2){lo=U128(pa[i])*4;hi=lo+3;}
  else {unsigned ones=0;while(ones<54&&(pa[i]&(1ULL<<ones)))++ones;U128 n=U128(1)<<(ones+3);lo=(U128(pa[i])*4)&~(n-1);hi=lo+n-1;}
  unsigned covered=0;for(unsigned byte=0;byte<64;byte++)covered+=(next+byte>=lo&&next+byte<=hi);
  if(covered)return covered==64&&((priv==3&&!(cfg[i]&128))||(cfg[i]&1));
 }
 return priv==3;
}
int main(int argc,char**argv){try{
 SClassifiedNextLineQueueGsim d;std::deque<std::pair<uint64_t,bool>> q;uint64_t serial=1,rng=0x8422f17bULL;
 bool corrupt=argc>1&&std::string(argv[1])=="--corrupt-summary";
 auto step=[&](bool push,bool pop,bool reset,unsigned mode,unsigned priv,uint64_t address,uint64_t boundary,bool fault){
  d.set_reset(reset);d.set_io$$push(push&&!reset);d.set_io$$pop(pop&&!reset);d.set_io$$seed(serial);
  d.set_io$$address(address);d.set_io$$boundary(boundary);d.set_io$$mode(mode);d.set_io$$privilege(priv);d.set_io$$fault(fault);d.set_io$$corrupt(corrupt);d.step();
  if(reset)q.clear();else{
   if(bool(d.get_io$$ready())!=(q.size()<2)||bool(d.get_io$$valid())!=!q.empty()||d.get_io$$count()!=q.size())throw std::runtime_error("independent checked credit mismatch");
   if(!q.empty()&&(d.get_io$$owner()!=q.front().first||bool(d.get_io$$hint())!=q.front().second))throw std::runtime_error("independent captured PMP authority mismatch");
   bool accept=push&&q.size()<2,retire=pop&&!q.empty();if(retire)q.pop_front();if(accept)q.emplace_back(serial,grant(address,boundary,mode,priv,fault));
  }++serial;
 };
 auto cycle=[&](bool push,bool pop,bool reset,unsigned mode=1,unsigned priv=1,uint64_t addr=RAM_BASE+128,uint64_t bound=RAM_BASE+220,bool fault=false){step(push,pop,reset,mode,priv,addr,bound,fault);};
 cycle(false,false,true);cycle(false,false,true);
 cycle(true,false,false);cycle(true,false,false);
 // Change permission/context repeatedly while both accepted grants are held.
 for(unsigned k=0;k<28;k++)cycle(true,false,false,k%7,k%4);
 cycle(true,true,false);cycle(true,true,false);cycle(true,true,false);cycle(false,true,false);cycle(false,true,false);
 for(unsigned k=0;k<20000;k++){
  rng^=rng<<13;rng^=rng>>7;rng^=rng<<17;
  uint64_t address=RAM_BASE+(rng%2048)*8;uint64_t next=(address/64+1)*64;
  cycle(rng&1,(rng>>1)&1,k%997==0,(rng>>2)%7,(rng>>5)%4,address,next+((rng>>8)%17)*4,(rng>>13)%13==0);
 }
 cycle(false,true,false);cycle(false,true,false);cycle(false,true,false);
 if(corrupt)throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 std::cout<<"CLASSIFIED_NEXTLINE_QUEUE_PASS random=20000 context_changes_while_stalled=28\n";return 0;
}catch(const std::exception&e){std::cerr<<"CLASSIFIED_NEXTLINE_QUEUE_FAIL "<<e.what()<<"\n";return 1;}}
