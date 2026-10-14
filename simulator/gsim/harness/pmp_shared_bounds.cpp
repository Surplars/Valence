#include "PmpSharedBoundsGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
using U128 = unsigned __int128;
struct Region { U128 low=0,end=0; unsigned cfg=0; bool active=false; };
using Regions=std::array<Region,16>;
static void check(bool v,const char *why){if(!v)throw std::runtime_error(why);}
static uint64_t trials=0,allows=0,denies=0,partialFirst=0,irregular=0;
static bool oracle(const Regions &r,unsigned entries,uint64_t a,unsigned size,unsigned privilege,unsigned access){
 const U128 start=a,last=start+((U128(1)<<size)-1);
 for(unsigned i=0;i<entries;i++)if(r[i].active && start<=r[i].end && last>=r[i].low){
  const bool cover=start>=r[i].low && last<=r[i].end;
  const bool permission=access==0?(r[i].cfg&1):access==1?(r[i].cfg&2):access==2?(r[i].cfg&4):((r[i].cfg&3)==3);
  const bool allow=(privilege==3 && !(r[i].cfg&128)) || permission;
  partialFirst+=!cover;
  return !cover||!allow;
 }
 return entries!=0 && privilege!=3;
}
static void drive(SPmpSharedBoundsGsim &d,const Regions &r){
 d.set_io$$low0(uint64_t(r[0].low));d.set_io$$lowHigh0(unsigned(r[0].low>>64));d.set_io$$end0(uint64_t(r[0].end));d.set_io$$endHigh0(unsigned(r[0].end>>64));d.set_io$$cfg0(r[0].cfg);d.set_io$$active0(r[0].active);
 d.set_io$$low1(uint64_t(r[1].low));d.set_io$$lowHigh1(unsigned(r[1].low>>64));d.set_io$$end1(uint64_t(r[1].end));d.set_io$$endHigh1(unsigned(r[1].end>>64));d.set_io$$cfg1(r[1].cfg);d.set_io$$active1(r[1].active);
 d.set_io$$low2(uint64_t(r[2].low));d.set_io$$lowHigh2(unsigned(r[2].low>>64));d.set_io$$end2(uint64_t(r[2].end));d.set_io$$endHigh2(unsigned(r[2].end>>64));d.set_io$$cfg2(r[2].cfg);d.set_io$$active2(r[2].active);
 d.set_io$$low3(uint64_t(r[3].low));d.set_io$$lowHigh3(unsigned(r[3].low>>64));d.set_io$$end3(uint64_t(r[3].end));d.set_io$$endHigh3(unsigned(r[3].end>>64));d.set_io$$cfg3(r[3].cfg);d.set_io$$active3(r[3].active);
 d.set_io$$low4(uint64_t(r[4].low));d.set_io$$lowHigh4(unsigned(r[4].low>>64));d.set_io$$end4(uint64_t(r[4].end));d.set_io$$endHigh4(unsigned(r[4].end>>64));d.set_io$$cfg4(r[4].cfg);d.set_io$$active4(r[4].active);
 d.set_io$$low5(uint64_t(r[5].low));d.set_io$$lowHigh5(unsigned(r[5].low>>64));d.set_io$$end5(uint64_t(r[5].end));d.set_io$$endHigh5(unsigned(r[5].end>>64));d.set_io$$cfg5(r[5].cfg);d.set_io$$active5(r[5].active);
 d.set_io$$low6(uint64_t(r[6].low));d.set_io$$lowHigh6(unsigned(r[6].low>>64));d.set_io$$end6(uint64_t(r[6].end));d.set_io$$endHigh6(unsigned(r[6].end>>64));d.set_io$$cfg6(r[6].cfg);d.set_io$$active6(r[6].active);
 d.set_io$$low7(uint64_t(r[7].low));d.set_io$$lowHigh7(unsigned(r[7].low>>64));d.set_io$$end7(uint64_t(r[7].end));d.set_io$$endHigh7(unsigned(r[7].end>>64));d.set_io$$cfg7(r[7].cfg);d.set_io$$active7(r[7].active);
 d.set_io$$low8(uint64_t(r[8].low));d.set_io$$lowHigh8(unsigned(r[8].low>>64));d.set_io$$end8(uint64_t(r[8].end));d.set_io$$endHigh8(unsigned(r[8].end>>64));d.set_io$$cfg8(r[8].cfg);d.set_io$$active8(r[8].active);
 d.set_io$$low9(uint64_t(r[9].low));d.set_io$$lowHigh9(unsigned(r[9].low>>64));d.set_io$$end9(uint64_t(r[9].end));d.set_io$$endHigh9(unsigned(r[9].end>>64));d.set_io$$cfg9(r[9].cfg);d.set_io$$active9(r[9].active);
 d.set_io$$low10(uint64_t(r[10].low));d.set_io$$lowHigh10(unsigned(r[10].low>>64));d.set_io$$end10(uint64_t(r[10].end));d.set_io$$endHigh10(unsigned(r[10].end>>64));d.set_io$$cfg10(r[10].cfg);d.set_io$$active10(r[10].active);
 d.set_io$$low11(uint64_t(r[11].low));d.set_io$$lowHigh11(unsigned(r[11].low>>64));d.set_io$$end11(uint64_t(r[11].end));d.set_io$$endHigh11(unsigned(r[11].end>>64));d.set_io$$cfg11(r[11].cfg);d.set_io$$active11(r[11].active);
 d.set_io$$low12(uint64_t(r[12].low));d.set_io$$lowHigh12(unsigned(r[12].low>>64));d.set_io$$end12(uint64_t(r[12].end));d.set_io$$endHigh12(unsigned(r[12].end>>64));d.set_io$$cfg12(r[12].cfg);d.set_io$$active12(r[12].active);
 d.set_io$$low13(uint64_t(r[13].low));d.set_io$$lowHigh13(unsigned(r[13].low>>64));d.set_io$$end13(uint64_t(r[13].end));d.set_io$$endHigh13(unsigned(r[13].end>>64));d.set_io$$cfg13(r[13].cfg);d.set_io$$active13(r[13].active);
 d.set_io$$low14(uint64_t(r[14].low));d.set_io$$lowHigh14(unsigned(r[14].low>>64));d.set_io$$end14(uint64_t(r[14].end));d.set_io$$endHigh14(unsigned(r[14].end>>64));d.set_io$$cfg14(r[14].cfg);d.set_io$$active14(r[14].active);
 d.set_io$$low15(uint64_t(r[15].low));d.set_io$$lowHigh15(unsigned(r[15].low>>64));d.set_io$$end15(uint64_t(r[15].end));d.set_io$$endHigh15(unsigned(r[15].end>>64));d.set_io$$cfg15(r[15].cfg);d.set_io$$active15(r[15].active);
}
static void one(SPmpSharedBoundsGsim &d,const Regions &r,uint64_t a,unsigned size,uint64_t line,unsigned priv,unsigned access,unsigned mutation=0,unsigned rawSize=7){
 drive(d,r);d.set_io$$address(a);d.set_io$$size(size);d.set_io$$lineAddress(line);d.set_io$$rawAddress(a^3);d.set_io$$rawSize(rawSize);d.set_io$$privilege(priv);d.set_io$$access(access);d.set_io$$mutation(mutation);d.step();
 {const bool want=oracle(r,0,a,size,priv,access);check(bool(d.get_io$$natural0())==want,"SHARED_BOUND_BYTE_ORACLE");allows+=!want;denies+=want;}
 {const bool want=oracle(r,0,line,6,priv,access);check(bool(d.get_io$$line0())==want,"SHARED_BOUND_BYTE_ORACLE");allows+=!want;denies+=want;}
 {const bool want=oracle(r,8,a,size,priv,access);check(bool(d.get_io$$natural8())==want,"SHARED_BOUND_BYTE_ORACLE");allows+=!want;denies+=want;}
 {const bool want=oracle(r,8,line,6,priv,access);check(bool(d.get_io$$line8())==want,"SHARED_BOUND_BYTE_ORACLE");allows+=!want;denies+=want;}
 {const bool want=oracle(r,16,a,size,priv,access);check(bool(d.get_io$$natural16())==want,"SHARED_BOUND_BYTE_ORACLE");allows+=!want;denies+=want;}
 {const bool want=oracle(r,16,line,6,priv,access);check(bool(d.get_io$$line16())==want,"SHARED_BOUND_BYTE_ORACLE");allows+=!want;denies+=want;}
 {const bool want=oracle(r,16,a^3,rawSize,priv,access);check(bool(d.get_io$$generic())==want,"GENERIC_BYTE_ORACLE");allows+=!want;denies+=want;}
 for(auto x:r)if(x.active && ((x.low&3)!=0 || (x.end&3)!=3)){++irregular;break;}
 ++trials;
}
int main(int argc,char **argv){try{
 SPmpSharedBoundsGsim d;static_assert(std::is_trivially_copyable_v<SPmpSharedBoundsGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();d.set_io$$size(3);d.set_reset(1);d.step();d.step();d.set_reset(0);
 Regions r{};const std::string flag=argc>1?argv[1]:"";
 if(!flag.empty()){
  const bool line=flag.rfind("--line-",0)==0;const std::string name=flag.substr(line?7:10);unsigned m=0,size=3;const uint64_t a=line?0x2000:0x1000;
  if(name=="drop-cover"){m=1;r[0]={a+4,a+7,7,true};r[1]={a,a+63,7,true};}
  else if(name=="drop-bound64"){m=2;r[0]={(U128(1)<<64)+a,(U128(1)<<64)+a+63,7,true};}
  else if(name=="lower-cover-end"){m=3;r[0]={a+4,a+63,7,true};r[1]={a,a+63,7,true};}
  else if(name=="upper-cover-start"){m=4;r[0]={a,a+3,7,true};r[1]={a,a+63,7,true};}
  else if(name=="reverse-priority"){m=5;r[0]={a,a+63,0,true};r[1]={a,a+63,7,true};}
  else if(name=="unconditional-low" && !line){m=6;size=2;r[0]={a-1,a+63,7,true};}
  else throw std::runtime_error("unknown mutation");
  std::cout<<"REACHED "<<flag<<std::endl;one(d,r,0x1000,size,0x2000,1,0,m);throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 }
 // Exhaust all low-byte boundaries, including unaligned/reversed test regions.
 for(unsigned size=0;size<=3;size++)for(unsigned lo=0;lo<24;lo++)for(unsigned end=0;end<24;end++)for(unsigned sub=0;sub<8;sub+=(1U<<size)){
  r={};r[0]={lo,end,(lo+end)&255,true};r[1]={0,127,7,true};one(d,r,8+sub,size,0,(lo+end)%4,(lo+end+sub)%4);
 }
 for(unsigned lo=0;lo<192;lo++)for(unsigned end=0;end<192;end++){
  r={};r[0]={lo,end,(lo^end)&255,true};r[1]={0,255,7,true};one(d,r,64,3,64,(lo+end)%4,(lo^end)%4);
 }
 // First partial match denies even M unlocked; a later covering region cannot rescue it.
 for(unsigned priv=0;priv<4;priv++)for(unsigned access=0;access<4;access++)for(unsigned lock=0;lock<2;lock++){
  r={};r[0]={0x1004,0x1007,7U+128U*lock,true};r[1]={0x1000,0x103f,7,true};one(d,r,0x1000,3,0x1000,priv,access);
 }
 const uint64_t edges[]={0,1,3,4,7,8,0xfffffffcULL,0x100000000ULL,(1ULL<<56)-1,1ULL<<56,(1ULL<<63)-1,1ULL<<63,~0ULL};
 std::mt19937_64 rng(0x736861726564626f);
 for(unsigned cycle=0;cycle<16000;cycle++){
  unsigned size=cycle%4;uint64_t a=(cycle%3?rng():edges[cycle%13])&~((1ULL<<size)-1),line=a&~63ULL;
  for(auto &x:r){x.low=(U128(rng()&1)<<64)|rng();x.end=(U128(rng()&1)<<64)|rng();x.cfg=rng()&255;x.active=rng()&1;}
  for(unsigned i=0;i<4;i++){U128 base=a;const unsigned before=rng()%65;r[i].low=base>=before?base-before:0;r[i].end=base+(rng()%129);r[i].active=true;}
  one(d,r,a,size,line,rng()%4,rng()%4,0,rng()%8);
 }
 check(trials>60000 && allows>1000 && denies>1000 && partialFirst>1000 && irregular>1000,"COVERAGE_LOW");
 std::cout<<"PMP_SHARED_BOUNDS_PASS entries=0,8,16 natural_sizes=0,1,2,3 line_size=6 trials="<<trials<<" oracle_checks="<<trials*7<<" partial_first="<<partialFirst<<" irregular_regions="<<irregular<<" allows="<<allows<<" denies="<<denies<<"\n";return 0;
 }catch(const std::exception &e){std::cerr<<"PMP shared-bound oracle rejection: "<<e.what()<<"\n";return 1;}}
