#include "SharedTwoWordFetchPmpGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
using Wide = unsigned __int128;
struct Entry { Wide low=0, end=0; uint64_t addr=0; unsigned cfg=0; bool active=false; };
using Entries = std::array<Entry,16>;
constexpr uint64_t rawMask = (uint64_t(1)<<54)-1;
// Independent trailing-ones byte interval decoder, bounded to the baseline's
// 56-bit physical address contract. In particular all-ones NAPOT ends at 2^56-1,
// whereas an unbounded byte decoder ends at 2^57-1. Test that difference explicitly.
static void decode(Entries &e) {
 for(unsigned i=0;i<16;++i) {
  auto &x=e[i]; unsigned mode=(x.cfg>>3)&3; Wide top=Wide(x.addr)*4;
  x.active=mode!=0;
  if(mode==1) {x.low=i?Wide(e[i-1].addr)*4:0;x.end=top?top-1:0;x.active=top>x.low;}
  else if(mode==2) {x.low=top;x.end=top+3;}
  else {unsigned ones=0;while(ones<54 && ((x.addr>>ones)&1))++ones;
   unsigned bits=ones+3; if(bits>56)bits=56;
   Wide mask=(Wide(1)<<bits)-1;x.low=top&~mask;x.end=x.low|mask;}
 }
}
static bool denied(const Entries &e,uint64_t a,unsigned priv) {
 Wide start=a,last=start+3;
 for(const auto &x:e)if(x.active && start<=x.end && last>=x.low)
  return start<x.low || last>x.end || !((priv==3 && !(x.cfg&128)) || (x.cfg&4));
 return priv!=3;
}
static uint64_t trials=0,differing=0,allows=0,denies=0;
static void one(SSharedTwoWordFetchPmpGsim &d,Entries e,uint64_t base,unsigned priv,bool raw=false) {
 d.set_io$$cfg0(e[0].cfg);d.set_io$$addr0(e[0].addr);d.set_io$$low0(uint64_t(e[0].low));d.set_io$$end0(uint64_t(e[0].end));d.set_io$$lowHigh0(unsigned(e[0].low>>64));d.set_io$$endHigh0(unsigned(e[0].end>>64));d.set_io$$active0(e[0].active);
 d.set_io$$cfg1(e[1].cfg);d.set_io$$addr1(e[1].addr);d.set_io$$low1(uint64_t(e[1].low));d.set_io$$end1(uint64_t(e[1].end));d.set_io$$lowHigh1(unsigned(e[1].low>>64));d.set_io$$endHigh1(unsigned(e[1].end>>64));d.set_io$$active1(e[1].active);
 d.set_io$$cfg2(e[2].cfg);d.set_io$$addr2(e[2].addr);d.set_io$$low2(uint64_t(e[2].low));d.set_io$$end2(uint64_t(e[2].end));d.set_io$$lowHigh2(unsigned(e[2].low>>64));d.set_io$$endHigh2(unsigned(e[2].end>>64));d.set_io$$active2(e[2].active);
 d.set_io$$cfg3(e[3].cfg);d.set_io$$addr3(e[3].addr);d.set_io$$low3(uint64_t(e[3].low));d.set_io$$end3(uint64_t(e[3].end));d.set_io$$lowHigh3(unsigned(e[3].low>>64));d.set_io$$endHigh3(unsigned(e[3].end>>64));d.set_io$$active3(e[3].active);
 d.set_io$$cfg4(e[4].cfg);d.set_io$$addr4(e[4].addr);d.set_io$$low4(uint64_t(e[4].low));d.set_io$$end4(uint64_t(e[4].end));d.set_io$$lowHigh4(unsigned(e[4].low>>64));d.set_io$$endHigh4(unsigned(e[4].end>>64));d.set_io$$active4(e[4].active);
 d.set_io$$cfg5(e[5].cfg);d.set_io$$addr5(e[5].addr);d.set_io$$low5(uint64_t(e[5].low));d.set_io$$end5(uint64_t(e[5].end));d.set_io$$lowHigh5(unsigned(e[5].low>>64));d.set_io$$endHigh5(unsigned(e[5].end>>64));d.set_io$$active5(e[5].active);
 d.set_io$$cfg6(e[6].cfg);d.set_io$$addr6(e[6].addr);d.set_io$$low6(uint64_t(e[6].low));d.set_io$$end6(uint64_t(e[6].end));d.set_io$$lowHigh6(unsigned(e[6].low>>64));d.set_io$$endHigh6(unsigned(e[6].end>>64));d.set_io$$active6(e[6].active);
 d.set_io$$cfg7(e[7].cfg);d.set_io$$addr7(e[7].addr);d.set_io$$low7(uint64_t(e[7].low));d.set_io$$end7(uint64_t(e[7].end));d.set_io$$lowHigh7(unsigned(e[7].low>>64));d.set_io$$endHigh7(unsigned(e[7].end>>64));d.set_io$$active7(e[7].active);
 d.set_io$$cfg8(e[8].cfg);d.set_io$$addr8(e[8].addr);d.set_io$$low8(uint64_t(e[8].low));d.set_io$$end8(uint64_t(e[8].end));d.set_io$$lowHigh8(unsigned(e[8].low>>64));d.set_io$$endHigh8(unsigned(e[8].end>>64));d.set_io$$active8(e[8].active);
 d.set_io$$cfg9(e[9].cfg);d.set_io$$addr9(e[9].addr);d.set_io$$low9(uint64_t(e[9].low));d.set_io$$end9(uint64_t(e[9].end));d.set_io$$lowHigh9(unsigned(e[9].low>>64));d.set_io$$endHigh9(unsigned(e[9].end>>64));d.set_io$$active9(e[9].active);
 d.set_io$$cfg10(e[10].cfg);d.set_io$$addr10(e[10].addr);d.set_io$$low10(uint64_t(e[10].low));d.set_io$$end10(uint64_t(e[10].end));d.set_io$$lowHigh10(unsigned(e[10].low>>64));d.set_io$$endHigh10(unsigned(e[10].end>>64));d.set_io$$active10(e[10].active);
 d.set_io$$cfg11(e[11].cfg);d.set_io$$addr11(e[11].addr);d.set_io$$low11(uint64_t(e[11].low));d.set_io$$end11(uint64_t(e[11].end));d.set_io$$lowHigh11(unsigned(e[11].low>>64));d.set_io$$endHigh11(unsigned(e[11].end>>64));d.set_io$$active11(e[11].active);
 d.set_io$$cfg12(e[12].cfg);d.set_io$$addr12(e[12].addr);d.set_io$$low12(uint64_t(e[12].low));d.set_io$$end12(uint64_t(e[12].end));d.set_io$$lowHigh12(unsigned(e[12].low>>64));d.set_io$$endHigh12(unsigned(e[12].end>>64));d.set_io$$active12(e[12].active);
 d.set_io$$cfg13(e[13].cfg);d.set_io$$addr13(e[13].addr);d.set_io$$low13(uint64_t(e[13].low));d.set_io$$end13(uint64_t(e[13].end));d.set_io$$lowHigh13(unsigned(e[13].low>>64));d.set_io$$endHigh13(unsigned(e[13].end>>64));d.set_io$$active13(e[13].active);
 d.set_io$$cfg14(e[14].cfg);d.set_io$$addr14(e[14].addr);d.set_io$$low14(uint64_t(e[14].low));d.set_io$$end14(uint64_t(e[14].end));d.set_io$$lowHigh14(unsigned(e[14].low>>64));d.set_io$$endHigh14(unsigned(e[14].end>>64));d.set_io$$active14(e[14].active);
 d.set_io$$cfg15(e[15].cfg);d.set_io$$addr15(e[15].addr);d.set_io$$low15(uint64_t(e[15].low));d.set_io$$end15(uint64_t(e[15].end));d.set_io$$lowHigh15(unsigned(e[15].low>>64));d.set_io$$endHigh15(unsigned(e[15].end>>64));d.set_io$$active15(e[15].active);
 d.set_io$$base(base);d.set_io$$privilege(priv);d.set_io$$raw(raw);d.step();
 if(raw)decode(e);
 unsigned expected=denied(e,base,priv)|(unsigned(denied(e,base+4,priv))<<1);
 if(d.get_io$$denied()!=expected)throw std::runtime_error("INDEPENDENT_BYTE_ORACLE");
 differing+=expected==1 || expected==2;allows+=2-((expected&1)+((expected>>1)&1));denies+=(expected&1)+((expected>>1)&1);++trials;
}
int main(int argc,char **argv) {try {
 SSharedTwoWordFetchPmpGsim d;std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();d.set_reset(1);d.step();d.step();d.set_reset(0);
 Entries e{};
 if(argc>1) {
  if(std::string(argv[1])=="--contract-alignment")one(d,e,4,1);
  else {e[0]={1,7,0,4,true};one(d,e,0,1);}
  throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 }
 // Explicit last packet, high address and page-edge cases do not depend on RNG luck.
 for(uint64_t base: {uint64_t(0),uint64_t(4088),uint64_t(4096),uint64_t(1)<<63,~uint64_t(7)}) {
  for(unsigned priv=0;priv<4;++priv) {
   e={};e[0]={base,Wide(base)+3,0,0,true};e[1]={Wide(base)+4,Wide(base)+7,0,4,true};one(d,e,base,priv);
   e[0].low|=Wide(1)<<64;e[0].end|=Wide(1)<<64;one(d,e,base,priv);
  }
 }
 // Every cfg byte and privilege, opposing adjacent NA4 permissions, all positions.
 for(unsigned i=0;i<16;++i)for(unsigned cfg=0;cfg<256;++cfg)for(unsigned priv=0;priv<4;++priv) {
  e={};e[i]={0x1000,0x1003,0,cfg,true};if(i<15)e[i+1]={0x1004,0x1007,0,cfg^4,true};one(d,e,0x1000,priv);
 }
 // Exhaust nearby lower/upper word boundaries, including reversed and bit64 bounds.
 for(unsigned lo=0;lo<16;++lo)for(unsigned hi=0;hi<16;++hi)for(unsigned high=0;high<4;++high) {
  e={};e[0]={Wide(lo*4)|(Wide(high&1)<<64),Wide(hi*4+3)|(Wide(high>>1)<<64),0,0,true};e[1]={0,127,0,4,true};one(d,e,24,1);
 }
 std::mt19937_64 rng(0x32776f7264706d70ULL);
 for(unsigned n=0;n<12000;++n) {
  uint64_t base=rng()&~7ULL;
  for(auto &x:e){x.low=(Wide(rng()&1)<<64)|(rng()&~3ULL);x.end=(Wide(rng()&1)<<64)|(rng()|3);x.cfg=rng()&255;x.active=rng()&1;x.addr=rng()&rawMask;}
  e[n%16].low=base;e[n%16].end=Wide(base)+3;e[n%16].active=true;
  one(d,e,base,rng()%4);
  // Raw54 states, boundaries and addresses above the physical domain.
  e[n%16].addr=(n%3)?e[n%16].addr:rawMask;
  Entries decoded=e;decode(decoded);base=uint64_t(decoded[n%16].end)&~7ULL;
  one(d,e,base,rng()%4,true);one(d,e,(uint64_t(1)<<56)+(n%32)*8,rng()%4,true);
 }
 e={};e[0].cfg=0x1c;e[0].addr=rawMask;
 one(d,e,(uint64_t(1)<<56)-8,1,true);one(d,e,uint64_t(1)<<56,1,true);
 decode(e);if(e[0].end!=(Wide(1)<<56)-1 || !denied(e,uint64_t(1)<<56,1))throw std::runtime_error("PHYSICAL_DOMAIN_CONTRACT");
 if(trials<50000 || differing<1000 || allows<1000 || denies<1000)throw std::runtime_error("COVERAGE_LOW");
 std::cout<<"SHARED_TWO_WORD_PMP_PASS trials="<<trials<<" differing="<<differing<<" raw54_max_napot_domain=56-bit unbounded_oracle_difference=explicit\n";
 return 0;
 }catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}}
