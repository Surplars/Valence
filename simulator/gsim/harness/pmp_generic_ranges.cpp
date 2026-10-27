#include "PmpGenericRangesGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
using Wide=unsigned __int128;
struct Region {Wide low=0,end=0;unsigned cfg=0;bool active=false;uint64_t addr=0;};
using Regions=std::array<Region,16>;
static uint64_t trials=0,carryCases=0,highCases=0,decodedCases=0,partialCases=0,noMatchCases=0;
static std::array<uint64_t,8> sizes{};
static std::array<uint64_t,16> selectedCounts{};
static void need(bool v,const char* s){if(!v)throw std::runtime_error(s);}
// Independent producer oracle uses trailing-one counting, not RTL xor-mask decoding.
static Regions decode(Regions in){
 Regions out=in;
 for(unsigned i=0;i<16;i++){
  auto &r=out[i]; unsigned mode=(r.cfg>>3)&3;r.active=mode!=0;
  // Inactive OFF bounds still follow the producer's unused NAPOT decode.
  if(mode==1){r.low=i?Wide(in[i-1].addr)<<2:0;Wide top=Wide(r.addr)<<2;r.active=top>r.low;r.end=top?top-1:((Wide(1)<<65)-1);}
  else if(mode==2){r.low=Wide(r.addr)<<2;r.end=r.low+3;}
  else {unsigned n=0;while(n<54 && (r.addr&(uint64_t(1)<<n)))++n;Wide bytes=n>=53?Wide(1)<<56:Wide(8)<<n;r.low=(Wide(r.addr)<<2)&~(bytes-1);r.end=r.low+bytes-1;}
 }
 return out;
}
struct Expected{unsigned hit=0,deny=0;bool def=false,denied=false;};
static Expected oracle(const Regions&r,unsigned entries,uint64_t a,unsigned size,unsigned priv,unsigned access){
 Expected e;e.def=entries!=0 && priv!=3;const Wide first=a,last=first+(Wide(1)<<size)-1;int chosen=-1;
 for(unsigned i=0;i<entries;i++){
  const auto& x=r[i];bool hit=x.active && first<=x.end && last>=x.low;
  bool cover=first>=x.low && last<=x.end;
  bool perm=access==0?(x.cfg&1):access==1?(x.cfg&2):access==2?(x.cfg&4):((x.cfg&3)==3);
  bool allow=(priv==3 && !(x.cfg&128)) || perm;
  if(hit){e.hit|=1U<<i;if(!cover||!allow)e.deny|=1U<<i;if(chosen<0){chosen=i;e.denied=!cover||!allow;partialCases+=!cover;selectedCounts[i]++;}}
 }
 if(chosen<0){e.denied=e.def;noMatchCases++;}return e;
}
static void drive(SPmpGenericRangesGsim&d,const Regions&r){
 d.set_io$$cfg0(r[0].cfg);
 d.set_io$$addr0(r[0].addr);
 d.set_io$$low0(uint64_t(r[0].low));
 d.set_io$$lowHigh0(unsigned(r[0].low>>64));
 d.set_io$$end0(uint64_t(r[0].end));
 d.set_io$$endHigh0(unsigned(r[0].end>>64));
 d.set_io$$active0(r[0].active);
 d.set_io$$cfg1(r[1].cfg);
 d.set_io$$addr1(r[1].addr);
 d.set_io$$low1(uint64_t(r[1].low));
 d.set_io$$lowHigh1(unsigned(r[1].low>>64));
 d.set_io$$end1(uint64_t(r[1].end));
 d.set_io$$endHigh1(unsigned(r[1].end>>64));
 d.set_io$$active1(r[1].active);
 d.set_io$$cfg2(r[2].cfg);
 d.set_io$$addr2(r[2].addr);
 d.set_io$$low2(uint64_t(r[2].low));
 d.set_io$$lowHigh2(unsigned(r[2].low>>64));
 d.set_io$$end2(uint64_t(r[2].end));
 d.set_io$$endHigh2(unsigned(r[2].end>>64));
 d.set_io$$active2(r[2].active);
 d.set_io$$cfg3(r[3].cfg);
 d.set_io$$addr3(r[3].addr);
 d.set_io$$low3(uint64_t(r[3].low));
 d.set_io$$lowHigh3(unsigned(r[3].low>>64));
 d.set_io$$end3(uint64_t(r[3].end));
 d.set_io$$endHigh3(unsigned(r[3].end>>64));
 d.set_io$$active3(r[3].active);
 d.set_io$$cfg4(r[4].cfg);
 d.set_io$$addr4(r[4].addr);
 d.set_io$$low4(uint64_t(r[4].low));
 d.set_io$$lowHigh4(unsigned(r[4].low>>64));
 d.set_io$$end4(uint64_t(r[4].end));
 d.set_io$$endHigh4(unsigned(r[4].end>>64));
 d.set_io$$active4(r[4].active);
 d.set_io$$cfg5(r[5].cfg);
 d.set_io$$addr5(r[5].addr);
 d.set_io$$low5(uint64_t(r[5].low));
 d.set_io$$lowHigh5(unsigned(r[5].low>>64));
 d.set_io$$end5(uint64_t(r[5].end));
 d.set_io$$endHigh5(unsigned(r[5].end>>64));
 d.set_io$$active5(r[5].active);
 d.set_io$$cfg6(r[6].cfg);
 d.set_io$$addr6(r[6].addr);
 d.set_io$$low6(uint64_t(r[6].low));
 d.set_io$$lowHigh6(unsigned(r[6].low>>64));
 d.set_io$$end6(uint64_t(r[6].end));
 d.set_io$$endHigh6(unsigned(r[6].end>>64));
 d.set_io$$active6(r[6].active);
 d.set_io$$cfg7(r[7].cfg);
 d.set_io$$addr7(r[7].addr);
 d.set_io$$low7(uint64_t(r[7].low));
 d.set_io$$lowHigh7(unsigned(r[7].low>>64));
 d.set_io$$end7(uint64_t(r[7].end));
 d.set_io$$endHigh7(unsigned(r[7].end>>64));
 d.set_io$$active7(r[7].active);
 d.set_io$$cfg8(r[8].cfg);
 d.set_io$$addr8(r[8].addr);
 d.set_io$$low8(uint64_t(r[8].low));
 d.set_io$$lowHigh8(unsigned(r[8].low>>64));
 d.set_io$$end8(uint64_t(r[8].end));
 d.set_io$$endHigh8(unsigned(r[8].end>>64));
 d.set_io$$active8(r[8].active);
 d.set_io$$cfg9(r[9].cfg);
 d.set_io$$addr9(r[9].addr);
 d.set_io$$low9(uint64_t(r[9].low));
 d.set_io$$lowHigh9(unsigned(r[9].low>>64));
 d.set_io$$end9(uint64_t(r[9].end));
 d.set_io$$endHigh9(unsigned(r[9].end>>64));
 d.set_io$$active9(r[9].active);
 d.set_io$$cfg10(r[10].cfg);
 d.set_io$$addr10(r[10].addr);
 d.set_io$$low10(uint64_t(r[10].low));
 d.set_io$$lowHigh10(unsigned(r[10].low>>64));
 d.set_io$$end10(uint64_t(r[10].end));
 d.set_io$$endHigh10(unsigned(r[10].end>>64));
 d.set_io$$active10(r[10].active);
 d.set_io$$cfg11(r[11].cfg);
 d.set_io$$addr11(r[11].addr);
 d.set_io$$low11(uint64_t(r[11].low));
 d.set_io$$lowHigh11(unsigned(r[11].low>>64));
 d.set_io$$end11(uint64_t(r[11].end));
 d.set_io$$endHigh11(unsigned(r[11].end>>64));
 d.set_io$$active11(r[11].active);
 d.set_io$$cfg12(r[12].cfg);
 d.set_io$$addr12(r[12].addr);
 d.set_io$$low12(uint64_t(r[12].low));
 d.set_io$$lowHigh12(unsigned(r[12].low>>64));
 d.set_io$$end12(uint64_t(r[12].end));
 d.set_io$$endHigh12(unsigned(r[12].end>>64));
 d.set_io$$active12(r[12].active);
 d.set_io$$cfg13(r[13].cfg);
 d.set_io$$addr13(r[13].addr);
 d.set_io$$low13(uint64_t(r[13].low));
 d.set_io$$lowHigh13(unsigned(r[13].low>>64));
 d.set_io$$end13(uint64_t(r[13].end));
 d.set_io$$endHigh13(unsigned(r[13].end>>64));
 d.set_io$$active13(r[13].active);
 d.set_io$$cfg14(r[14].cfg);
 d.set_io$$addr14(r[14].addr);
 d.set_io$$low14(uint64_t(r[14].low));
 d.set_io$$lowHigh14(unsigned(r[14].low>>64));
 d.set_io$$end14(uint64_t(r[14].end));
 d.set_io$$endHigh14(unsigned(r[14].end>>64));
 d.set_io$$active14(r[14].active);
 d.set_io$$cfg15(r[15].cfg);
 d.set_io$$addr15(r[15].addr);
 d.set_io$$low15(uint64_t(r[15].low));
 d.set_io$$lowHigh15(unsigned(r[15].low>>64));
 d.set_io$$end15(uint64_t(r[15].end));
 d.set_io$$endHigh15(unsigned(r[15].end>>64));
 d.set_io$$active15(r[15].active);
}
static void one(SPmpGenericRangesGsim&d,const Regions&in,uint64_t a,unsigned size,unsigned priv,unsigned access,bool decoded=false,bool inject=false,int mutant=-1){
 drive(d,in);d.set_io$$decoded(decoded);d.set_io$$address(a);d.set_io$$size(size);d.set_io$$privilege(priv);d.set_io$$access(access);d.step();
 const auto r=decoded?decode(in):in;const Wide first=a,last=first+(Wide(1)<<size)-1;unsigned overlaps=0,covers=0;
 for(unsigned i=0;i<16;i++){overlaps|=unsigned(r[i].active&&first<=r[i].end&&last>=r[i].low)<<i;covers|=unsigned(first>=r[i].low&&last<=r[i].end)<<i;}
 need(d.get_io$$rangeOverlap()==overlaps,"GENERIC_RANGE_OVERLAP_ORACLE");need(d.get_io$$rangeCovers()==covers,"GENERIC_RANGE_COVERS_ORACLE");
 {const auto e=oracle(r,0,a,size,priv,access);
 need(bool(d.get_io$$oldDenied0())==(e.denied ^ (inject && false)),"GENERIC_PMP_DECISION_ORACLE");
 need(d.get_io$$oldHit0()==e.hit && d.get_io$$oldDeny0()==e.deny && bool(d.get_io$$oldDefault0())==e.def,"GENERIC_PMP_SUMMARY_ORACLE");
 need(bool(d.get_io$$candidateDenied0())==(e.denied ^ (inject && true)),"GENERIC_PMP_DECISION_ORACLE");
 need(d.get_io$$candidateHit0()==e.hit && d.get_io$$candidateDeny0()==e.deny && bool(d.get_io$$candidateDefault0())==e.def,"GENERIC_PMP_SUMMARY_ORACLE");
 }
 {const auto e=oracle(r,8,a,size,priv,access);
 need(bool(d.get_io$$oldDenied8())==(e.denied ^ (inject && false)),"GENERIC_PMP_DECISION_ORACLE");
 need(d.get_io$$oldHit8()==e.hit && d.get_io$$oldDeny8()==e.deny && bool(d.get_io$$oldDefault8())==e.def,"GENERIC_PMP_SUMMARY_ORACLE");
 need(bool(d.get_io$$candidateDenied8())==(e.denied ^ (inject && true)),"GENERIC_PMP_DECISION_ORACLE");
 need(d.get_io$$candidateHit8()==e.hit && d.get_io$$candidateDeny8()==e.deny && bool(d.get_io$$candidateDefault8())==e.def,"GENERIC_PMP_SUMMARY_ORACLE");
 }
 {const auto e=oracle(r,16,a,size,priv,access);
 need(bool(d.get_io$$oldDenied16())==(e.denied ^ (inject && false)),"GENERIC_PMP_DECISION_ORACLE");
 need(d.get_io$$oldHit16()==e.hit && d.get_io$$oldDeny16()==e.deny && bool(d.get_io$$oldDefault16())==e.def,"GENERIC_PMP_SUMMARY_ORACLE");
 need(bool(d.get_io$$candidateDenied16())==(e.denied ^ (inject && true)),"GENERIC_PMP_DECISION_ORACLE");
 need(d.get_io$$candidateHit16()==e.hit && d.get_io$$candidateDeny16()==e.deny && bool(d.get_io$$candidateDefault16())==e.def,"GENERIC_PMP_SUMMARY_ORACLE");
 }
 if(mutant>=0){need(bool((d.get_io$$mutantOverlap()>>mutant)&1)==bool(overlaps&1) && bool((d.get_io$$mutantCovers()>>mutant)&1)==bool(covers&1),"MUTANT_RANGE_ORACLE");}
 ++trials;++sizes[size];carryCases+=((a&127)+((1U<<size)-1))>=128;highCases+=last>UINT64_MAX;decodedCases+=decoded;
}
int main(int argc,char**argv){try{
 const std::string arg=argc==2?argv[1]:"";const bool inject=arg=="--inject-oracle";need(argc<=2,"one flag only");
 SPmpGenericRangesGsim d;std::memset(&d,0,sizeof(d));d.activateAll();d.set_reset(1);d.step();d.set_reset(0);
 Regions r{};if(inject){std::cout<<"REACHED_ORACLE_NEGATIVE\n";one(d,r,0,0,1,0,false,true);throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");}
 if(!arg.empty()){
  unsigned m=0,size=0;uint64_t a=0;
  if(arg=="--drop-carry"){m=0;a=127;size=1;r[0]={128,128,7,true,0};}
  else if(arg=="--drop-address63"){m=1;a=uint64_t(1)<<63;r[0]={0,127,7,true,0};}
  else if(arg=="--drop-bound64"){m=2;r[0]={Wide(1)<<64,(Wide(1)<<64)+127,7,true,0};}
  else if(arg=="--strict-upper"){m=3;r[0]={0,0,7,true,0};}
  else if(arg=="--drop-cover"){m=4;size=1;r[0]={1,1,7,true,0};}
  else throw std::runtime_error("unknown flag");
  std::cout<<"REACHED_MUTANT "<<arg<<std::endl;one(d,r,a,size,1,0,false,false,m);throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED");
 }
 // Exhaust all low address positions and sizes, crossing and exact-bound edges.
 for(uint64_t base:{uint64_t(0),uint64_t(128),(uint64_t(1)<<56)-128,(uint64_t(1)<<63)-128,UINT64_MAX-127})
 for(unsigned al=0;al<128;al++)for(unsigned size=0;size<8;size++){
  uint64_t a=base+al;Wide end=Wide(a)+(Wide(1)<<size)-1;
  std::array<Wide,7> b={0,Wide(a),end,end+1,Wide(a)?Wide(a)-1:0,(Wide(1)<<64),(Wide(1)<<65)-1};
  for(auto low:b)for(auto hi:b){r={};r[0]={low,hi,7,true,0};r[1]={0,(Wide(1)<<65)-1,7,true,0};one(d,r,a,size,(al+size)%4,(al^size)%4);}
 }
 // Complete cfg/privilege/access policies including reserved combinations.
 for(unsigned cfg=0;cfg<256;cfg++)for(unsigned priv=0;priv<4;priv++)for(unsigned acc=0;acc<4;acc++)for(unsigned size=0;size<8;size++){
  r={};r[7]={0x1000,0x10ff,cfg,true,0};r[8]={0,0x1fff,7,true,0};one(d,r,0x1001,size,priv,acc);
 }
 // Exact priority, partial cover, inactive and array-boundary ownership.
 for(unsigned i=0;i<16;i++)for(unsigned priv=0;priv<4;priv++)for(unsigned acc=0;acc<4;acc++){
  r={};r[i]={0x1004,0x1007,7,true,0};if(i+1<16)r[i+1]={0,0x1fff,7,true,0};one(d,r,0x1000,3,priv,acc);
  r[i]={0x1000,0x10ff,0,true,0};one(d,r,0x1000,2,priv,acc);r[i].active=false;one(d,r,0x1000,2,priv,acc);
 }
 // Actual TOR/NA4/NAPOT producer paths, zero/reversed TOR and saturated NAPOT.
 for(unsigned mode=0;mode<4;mode++)for(unsigned cfg=0;cfg<256;cfg++)for(unsigned size=0;size<8;size++){
  r={};r[0].addr=0x400;r[1].addr=(cfg&1)?0x3ff:0x800;r[1].cfg=(cfg&~24U)|(mode<<3);
  for(uint64_t a:{uint64_t(0),uint64_t(0xfff),uint64_t(0x1000),uint64_t(0x1ffc),UINT64_MAX})one(d,r,a,size,cfg%4,(cfg>>2)%4,true);
 }
 for(unsigned trailing=0;trailing<=54;trailing++)for(unsigned size=0;size<8;size++){
  r={};r[15].cfg=0x9f;r[15].addr=(uint64_t(1)<<trailing)-1;
  for(uint64_t a:{uint64_t(0),(uint64_t(1)<<56)-1,UINT64_MAX})one(d,r,a,size,3,0,true);
 }
 std::mt19937_64 rng(0x65a1faca);const Wide mask=(Wide(1)<<65)-1;
 for(unsigned t=0;t<20000;t++){
  for(auto&x:r){x.low=((Wide(rng()&1)<<64)|rng())&mask;x.end=((Wide(rng()&1)<<64)|rng())&mask;x.cfg=rng()&255;x.active=rng()&1;x.addr=rng()&((uint64_t(1)<<54)-1);}
  uint64_t a=(t%3==0)?uint64_t(r[t%16].low):rng();one(d,r,a,rng()%8,rng()%4,rng()%4,t&1);
 }
 need(trials==346696,"TRIAL_COUNT_MISMATCH");
 need(carryCases && highCases && decodedCases && partialCases && noMatchCases,"COVERAGE_EMPTY");for(auto c:sizes)need(c,"SIZE_UNCOVERED");for(auto c:selectedCounts)need(c,"ENTRY_UNCOVERED");
 std::cout<<"PMP_GENERIC_RANGES_PASS trials="<<trials<<" carry="<<carryCases<<" xlen_carry="<<highCases<<" decoded="<<decodedCases<<" partial="<<partialCases<<" no_match="<<noMatchCases<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
