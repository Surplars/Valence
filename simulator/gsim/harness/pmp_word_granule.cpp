#include "PmpWordGranuleGsim.h"
#include "pmp_csr_oracle.h"
#include <iostream>
#include <random>
#include <string>
#include <cstring>
#include <type_traits>
using namespace pmp_csr_oracle;
static void check(bool v,const char* s){if(!v)throw std::runtime_error(s);}
static uint64_t trials=0, differingWords=0, allows=0, denies=0;
static void drive(SPmpWordGranuleGsim& d,const Entries& e) {
 d.set_io$$cfg0(e[0].cfg);d.set_io$$addr0(e[0].addr);
 d.set_io$$cfg1(e[1].cfg);d.set_io$$addr1(e[1].addr);
 d.set_io$$cfg2(e[2].cfg);d.set_io$$addr2(e[2].addr);
 d.set_io$$cfg3(e[3].cfg);d.set_io$$addr3(e[3].addr);
 d.set_io$$cfg4(e[4].cfg);d.set_io$$addr4(e[4].addr);
 d.set_io$$cfg5(e[5].cfg);d.set_io$$addr5(e[5].addr);
 d.set_io$$cfg6(e[6].cfg);d.set_io$$addr6(e[6].addr);
 d.set_io$$cfg7(e[7].cfg);d.set_io$$addr7(e[7].addr);
 d.set_io$$cfg8(e[8].cfg);d.set_io$$addr8(e[8].addr);
 d.set_io$$cfg9(e[9].cfg);d.set_io$$addr9(e[9].addr);
 d.set_io$$cfg10(e[10].cfg);d.set_io$$addr10(e[10].addr);
 d.set_io$$cfg11(e[11].cfg);d.set_io$$addr11(e[11].addr);
 d.set_io$$cfg12(e[12].cfg);d.set_io$$addr12(e[12].addr);
 d.set_io$$cfg13(e[13].cfg);d.set_io$$addr13(e[13].addr);
 d.set_io$$cfg14(e[14].cfg);d.set_io$$addr14(e[14].addr);
 d.set_io$$cfg15(e[15].cfg);d.set_io$$addr15(e[15].addr);
}
static void one(SPmpWordGranuleGsim& d,const Entries& e,uint64_t a,uint64_t b,unsigned access,unsigned privilege,unsigned mutation=0,unsigned size=2,bool corrupt=false) {
 drive(d,e);d.set_io$$address0(a);d.set_io$$address1(b);d.set_io$$privilege(privilege);d.set_io$$access(access);d.set_io$$size(size);d.set_io$$mutation(mutation);d.set_io$$corruptGranule(corrupt);d.step();
 {bool want=denied(e,0,a,size,access,privilege);check(bool(d.get_io$$denied0_0())==want,"ORACLE_BYTE_RANGE_FIRST_PERMISSION");allows+=!want;denies+=want;}
 {bool want=denied(e,0,b,size,access,privilege);check(bool(d.get_io$$denied0_1())==want,"ORACLE_BYTE_RANGE_FIRST_PERMISSION");allows+=!want;denies+=want;}
 {bool want=denied(e,8,a,size,access,privilege);check(bool(d.get_io$$denied8_0())==want,"ORACLE_BYTE_RANGE_FIRST_PERMISSION");allows+=!want;denies+=want;}
 {bool want=denied(e,8,b,size,access,privilege);check(bool(d.get_io$$denied8_1())==want,"ORACLE_BYTE_RANGE_FIRST_PERMISSION");allows+=!want;denies+=want;}
 {bool want=denied(e,16,a,size,access,privilege);check(bool(d.get_io$$denied16_0())==want,"ORACLE_BYTE_RANGE_FIRST_PERMISSION");allows+=!want;denies+=want;}
 {bool want=denied(e,16,b,size,access,privilege);check(bool(d.get_io$$denied16_1())==want,"ORACLE_BYTE_RANGE_FIRST_PERMISSION");allows+=!want;denies+=want;}
 differingWords+=denied(e,16,a,size,access,privilege)!=denied(e,16,b,size,access,privilege);++trials;
}
int main(int argc,char**argv){try {
 const std::string flag=argc>1?argv[1]:""; SPmpWordGranuleGsim d;
 static_assert(std::is_trivially_copyable_v<SPmpWordGranuleGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
 d.set_reset(1);d.set_io$$size(2);d.step();d.step();d.set_reset(0);
 Entries e{};
 if(!flag.empty()) {
  unsigned mutation=0,size=2;bool corrupt=false;uint64_t a=0x1000,b=0x1004;unsigned access=0,privilege=1;
  if(flag=="--mutant-high-address") {mutation=1;e[0]={0x11,0x400};a|=1ULL<<40;}
  else if(flag=="--mutant-priority") {mutation=2;e[0]={0x10,0x400};e[1]={0x11,0x400};}
  else if(flag=="--mutant-lock") {mutation=3;e[0]={0x90,0x400};privilege=3;}
  else if(flag=="--mutant-write-permission") {mutation=4;e[0]={0x11,0x400};access=1;}
  else if(flag=="--mutant-inactive") {mutation=5;e[0]={0,0x400};e[1]={0x11,0x400};}
  else if(flag=="--mutant-high-region") {mutation=6;e[0]={0x11,((1ULL<<40)|0x1000)>>2};}
  else if(flag=="--contract-granule") {corrupt=true;e[0]={0x11,0x400};}
  else if(flag=="--contract-size") {size=3;e[0]={0x1f,0x7ff};}
  else if(flag=="--contract-alignment") {a|=2;e[0]={0x1f,0x7ff};}
  else throw std::runtime_error("unknown flag");
  std::cout<<"REACHED "<<flag<<std::endl;one(d,e,a,b,access,privilege,mutation,size,corrupt);throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 }
 const uint64_t extremes[]={0,4,0xfffffffcULL,0x100000000ULL,0x1001ffffcULL,0x100200000ULL,(1ULL<<56)-4,1ULL<<56,(1ULL<<63),~uint64_t(3)};
 for(unsigned mode=0;mode<4;mode++)for(unsigned permission=0;permission<8;permission++)for(unsigned lock=0;lock<2;lock++) {
  e={};e[0]={mode*8+permission+lock*128,mode==1?0x800ULL:mode==2?0x400ULL:0x7ffULL};
  e[1]={0x15,0x401}; // Adjacent NA4 word with independent execute permission.
  for(unsigned priv=0;priv<4;priv++)for(unsigned access=0;access<4;access++){
   one(d,e,0x1000,0x1004,access,priv);for(auto a:extremes)one(d,e,a,a+4,access,priv);
  }
 }
 // Empty/decreasing TOR and a later permissive overlap must retain priority.
 for(unsigned top=0;top<16;top++)for(unsigned low=0;low<16;low++) {
  e={};e[0]={0,low};e[1]={0x08,top};e[2]={0x1f,0x1f};
  for(unsigned i=0;i<32;i++)one(d,e,4*i,4*i+4,0,1);
 }
 // NAPOT extreme and arbitrary dynamic raw-state updates. Oracle uses trailing
 // ones and byte intervals; it never reads the DUT's decoded region fields.
 std::mt19937_64 rng(0x4b6772616e756c65);
 for(unsigned cycle=0;cycle<12000;cycle++) {
  for(auto& x:e){x.cfg=rng()&255;x.addr=rng()&addressMask;}
  if(cycle%4==0)e[cycle%16].addr=addressMask;
  uint64_t a=rng()&~uint64_t(3);
  if(cycle%3) {const auto r=range(e,cycle%16);a=uint64_t((cycle%2?r.low:r.end))&~uint64_t(3);a+=(int(cycle%5)-2)*4;}
  const uint64_t b=a+4;one(d,e,a,b,rng()%4,rng()%4);
 }
 check(trials>30000 && differingWords>1000 && allows>1000 && denies>1000,"COVERAGE_LOW");
 std::cout<<"PMP_WORD_GRANULE_PASS entries=0,8,16 trials="<<trials<<" byte_oracle_checks="<<trials*6<<" differing_word_permissions="<<differingWords<<" allows="<<allows<<" denies="<<denies<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<"PMP word oracle rejection: "<<e.what()<<'\n';return 1;}}
