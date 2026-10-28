// Static-prepared actual-backend host. No DUT state writes or forced owner input.
// Expectations originate in raw instruction interpretation, accepted rename
// ownership, independent byte memory, and host-ledger lifetimes. Observation
// mutants modify local copies only; they are NOT RTL gate mutants.
#include "MulLoadOperandCaptureBackendGsim.h"
#include "pending_store_proof_reference.h"
#include <algorithm>
#include <array>
#include <deque>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <tuple>
#include <vector>
using pending_store_reference::Token;
using pending_store_reference::Bytes;
using pending_store_reference::Tables;
using pending_store_reference::require;
using Dut=SMulLoadOperandCaptureBackendGsim;
static uint64_t sext(uint64_t a,unsigned n){const uint64_t m=1ULL<<(n-1);return (a^m)-m;}
static uint32_t addi(unsigned d,unsigned s,int n){return (uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t slli(unsigned d,unsigned n){return n<<20|d<<15|1<<12|d<<7|0x13;}
static uint32_t load(unsigned d,unsigned s,int off=0){return (uint32_t(off)&4095)<<20|s<<15|3<<12|d<<7|3;}
static uint32_t mInst(unsigned d,unsigned a,unsigned b,unsigned op=0,bool word=false){return 1u<<25|b<<20|a<<15|op<<12|d<<7|(word?0x3b:0x33);}
static uint32_t branch(unsigned a){const unsigned off=32;return ((off>>12)&1)<<31|((off>>5)&63)<<25|a<<20|a<<15|((off>>1)&15)<<8|((off>>11)&1)<<7|0x63;}
static uint64_t product(uint64_t a,uint64_t b,unsigned op,bool word){
 using U=unsigned __int128;
 // Two's-complement sign extension in unsigned128 arithmetic, independent of
 // DUT partial-product/correction topology; multiplication is modulo 2^128.
 U x=a,y=b;
 if((op==1||op==2)&&(a>>63))x|=U(UINT64_MAX)<<64;
 if(op==1&&(b>>63))y|=U(UINT64_MAX)<<64;
 U p=x*y;uint64_t v=op?uint64_t(p>>64):uint64_t(p);
 return word?sext(uint32_t(v),32):v;
}
struct Instruction{uint32_t word;uint64_t pc;};
struct Entry{
 Token token;Instruction inst;unsigned rd=0,rs1=0,rs2=0,s1=0,s2=0,dest=0,op=0;
 bool writes=false,mul=false,div=false,mem=false,branch=false,system=false,word=false,alias=false;
 bool physicalSeen=false,errorServiced=false;
 bool error=false,page=false,killed=false,started=false,requested=false,returned=false,completed=false,retired=false;
 uint64_t left=0,right=0,value=0,address=0,pa=0,ordinal=0;
};
struct Reply{Token owner;uint64_t data;unsigned due;bool error;};
struct PteReply{uint64_t address,data;unsigned due;};
struct Row{Token token;unsigned s1,s2,dest;bool pending,memoryLive,killed,r1,r2,memory,store,atomic,m;unsigned op;bool word;};
struct Start{Token token;uint64_t pc,left,right;unsigned operation;bool word;};
class Bench{
 public:
 std::unique_ptr<Dut> storage=std::make_unique<Dut>();Dut&d=*storage;
 Tables tables;Bytes memory;
 std::array<uint64_t,32> architectural{},predicted{};
 std::array<unsigned,32> mapping{},committedMapping{};
 std::map<Token,Entry> entries;std::deque<Token> live,physicalOwners,upstreamOwners,lsuRequestOwners;
 std::deque<Reply> replies;std::deque<PteReply> ptes;std::set<uint64_t> faultLeaves;std::set<Token> trappedTokens;
 std::set<Token> completedTokens,retiredTokens,mulStarts,divStarts;
 std::vector<std::pair<unsigned,uint64_t>> expectedWrites;
 std::optional<Start> previousMul;
 using Held=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool,bool,bool,unsigned,bool,bool,uint32_t,bool>;
 std::optional<Held> heldPhysical;
 unsigned cycle=0,accepted=0,retired=0,latency=24,physicalHold=0,responseHold=0,physicalCount=0,responseCount=0;
 unsigned forwarded=0,forwardedLeft=0,forwardedRight=0,forwardedBoth=0,oldMulBlocked=0,oldDivBlocked=0,unavailableDiv=0;
 unsigned killedCount=0,traps=0,wraps=0,reuses=0,mulHigh=0,mulW=0,mulLow=0,lsuHeld=0,lateRejected=0,fullPop=0,peakMul=0;
 uint64_t softwareReady=0xffffffffULL,writeWake=0,currentReserve=0;unsigned expectedMulCount=0;bool originalAvailable=false;
 uint64_t nextPc=0x1000;bool enabled,commitEnable=true,faultNext=false,pageNext=false,mutated=false;
 std::string mutation;std::map<unsigned,uint64_t> oldTags;
 Bench(bool on,std::string mut={}):enabled(on),mutation(std::move(mut)){
  tables.pages[0].physical=0x80200000ULL;tables.pages[1].physical=0x80201000ULL;
  for(unsigned i=0;i<32;++i)mapping[i]=committedMapping[i]=i;
  tick({},true);tick({},true);tick();tick();
 }
 void check(bool ok,const std::string&why)const{require(ok,"cycle="+std::to_string(cycle)+" "+why);}
 Entry interpret(Instruction ins,Token t,unsigned s1,unsigned s2,unsigned dest,bool writes,bool alias){
  Entry e;e.token=t;e.inst=ins;e.s1=s1;e.s2=s2;e.dest=dest;e.alias=alias;e.ordinal=accepted;
  auto w=ins.word;unsigned opcode=w&127,f=(w>>12)&7;e.rd=(w>>7)&31;e.rs1=(w>>15)&31;e.rs2=(w>>20)&31;
  e.left=predicted[e.rs1];e.right=predicted[e.rs2];e.writes=false;
  if(opcode==0x13){e.writes=true;e.rs2=0;e.right=0;
   if(f==0)e.value=e.left+sext(w>>20,12);else if(f==1)e.value=e.left<<((w>>20)&63);else throw std::runtime_error("unsupported immediate");
  }else if((opcode==0x33||opcode==0x3b)&&(w>>25)==1){
   e.writes=true;e.op=f;e.word=opcode==0x3b;e.mul=f<4;e.div=!e.mul;
   if(e.mul){check(!e.word||f==0,"reserved MULW operation");e.value=product(e.left,e.right,f,e.word);}
   else{check(f==5&&!e.word,"host supports DIVU only");e.value=e.right?e.left/e.right:UINT64_MAX;}
  }else if(opcode==3){e.mem=true;e.writes=true;e.rs2=0;e.right=0;check(f==3,"host supports aligned LD only");
   e.address=e.left+sext(w>>20,12);check(!(e.address&7),"host LD alignment");e.pa=tables.physical(e.address);
   e.error=faultNext;e.page=pageNext;e.value=memory.read(e.pa,3);
  }else if(opcode==0x63){e.branch=true;check(f==0&&e.left==e.right,"host supports taken equal-register BEQ only");e.value=ins.pc+sext(((w>>31)<<12)|(((w>>7)&1)<<11)|(((w>>25)&63)<<5)|(((w>>8)&15)<<1),13);
  }else if(opcode==0x73){e.system=true;e.rs2=0;e.right=0;e.writes=e.rd!=0;check(!e.writes,"host CSRs only rd=x0");}
  else throw std::runtime_error("unknown host raw opcode");
  check(s1==mapping[e.rs1]&&s2==mapping[e.rs2],"rename source differs from architectural mapping");
  check(writes==(e.writes&&e.rd!=0),"rename writes flag differs from raw instruction");
  if(writes){check(dest<48&&(alias?dest==s1:dest>0),"rename destination/alias mapping out of range");mapping[e.rd]=dest;predicted[e.rd]=e.value;}
  if(alias)check(opcode==0x13&&f==0&&(w>>20)==0,"unexpected move alias");
  return e;
 }
 void restore(){predicted=architectural;mapping=committedMapping;for(auto t:live){auto&e=entries.at(t);if(e.writes&&e.rd){predicted[e.rd]=e.value;mapping[e.rd]=e.dest;}}}
 std::array<Row,16> rows(){std::array<Row,16>a{};
#define ROW(N) a[N]=Row{{unsigned(d.get_io$$row##N##$$token$$index()),uint64_t(d.get_io$$row##N##$$token$$tag())},unsigned(d.get_io$$row##N##$$source1()),unsigned(d.get_io$$row##N##$$source2()),unsigned(d.get_io$$row##N##$$destination()),bool(d.get_io$$row##N##$$pending()),bool(d.get_io$$row##N##$$memoryLive()),bool(d.get_io$$row##N##$$killed()),bool(d.get_io$$row##N##$$ownerReady1()),bool(d.get_io$$row##N##$$ownerReady2()),bool(d.get_io$$row##N##$$memory()),bool(d.get_io$$row##N##$$store()),bool(d.get_io$$row##N##$$atomic()),bool(d.get_io$$row##N##$$mulDiv()),unsigned(d.get_io$$row##N##$$operation()),bool(d.get_io$$row##N##$$word())}
 ROW(0);ROW(1);ROW(2);ROW(3);ROW(4);ROW(5);ROW(6);ROW(7);ROW(8);ROW(9);ROW(10);ROW(11);ROW(12);ROW(13);ROW(14);ROW(15);
#undef ROW
 return a;}
 void checkStart(Start actual,bool mul,const std::array<Row,16>&rs){
  if(!mutation.empty()&&!mutated&&mul){mutated=true;std::cerr<<"MUL_OBSERVER_MUTANT_REACHED mode="<<mutation<<'\n';if(mutation=="high-tag")actual.token.tag^=1ULL<<63;else if(mutation=="value")actual.left^=1;else throw std::runtime_error("unknown observer mode");}
  check(entries.count(actual.token),"MUL_FULL_OWNER_UNKNOWN");auto&e=entries.at(actual.token);
  check(!e.killed&&!e.retired&&e.mul==mul&&e.div!=mul,"M start nonexistent/dead/wrong-class owner");
  check(actual.pc==e.inst.pc&&actual.operation==e.op&&actual.word==e.word,"M start raw operation/PC mismatch");
  check(actual.left==e.left&&actual.right==e.right,"MUL_OPERAND_VALUE_MISMATCH");
  check((mul?mulStarts:divStarts).insert(actual.token).second,"duplicate M start");e.started=true;
  const auto&r=rs.at(actual.token.index);check(r.token==actual.token&&r.pending&&r.s1==e.s1&&r.s2==e.s2,"M start local-row ownership mismatch");
  if(mul){mulW+=e.word;mulHigh+=!e.word&&e.op!=0;mulLow+=!e.word&&e.op==0;}
  const uint64_t ready=softwareReady;bool f1=!((ready>>e.s1)&1),f2=!((ready>>e.s2)&1);
  if(f1||f2){check(enabled&&mul,"OFF or DIV consumed unready source");check(d.get_io$$lsuComplete$$valid()&&!d.get_io$$lsuComplete$$bits$$exception(),"forward has no successful registered LSU result");
   Token producer{unsigned(d.get_io$$lsuComplete$$bits$$token$$index()),uint64_t(d.get_io$$lsuComplete$$bits$$token$$tag())};
   check(entries.count(producer),"forward producer full owner unknown");const auto&p=entries.at(producer);
   check(p.mem&&!p.error&&!p.page&&!p.killed&&p.returned&&p.ordinal<e.ordinal&&p.dest!=0,"forward producer not older successful load");
   check((!f1||e.s1==p.dest)&&(!f2||e.s2==p.dest),"one load cannot satisfy two unrelated sources");
   check(!(currentReserve&((f1?(1ULL<<e.s1):0)|(f2?(1ULL<<e.s2):0))),"forwarded source reserved on capture edge");
   check(d.get_io$$lsuComplete$$bits$$data()==p.value,"stable LSU numerical oracle mismatch");
   check((!f1||actual.left==p.value)&&(!f2||actual.right==p.value),"forward payload not independent producer value");
   check(std::find(live.begin(),live.end(),producer)!=live.end()&&std::find(live.begin(),live.end(),actual.token)!=live.end(),"forward owner not globally live");
   check(!originalAvailable,"expanded capture displaced original available M winner");
   ++forwarded;forwardedLeft+=f1;forwardedRight+=f2;forwardedBoth+=f1&&f2;
  }
 }
 void complete(Token t,uint64_t value,bool exception,uint64_t cause,uint64_t tval){
  check(entries.count(t),"completion has unknown full owner");auto&e=entries.at(t);check(!e.killed,"killed owner CDB completion");
  check(completedTokens.insert(t).second,"duplicate CDB completion");
  if(e.mul||e.div)check((e.mul?mulStarts:divStarts).count(t),"M completion has no original start");e.completed=true;
  if(e.mem){check(exception==(e.error||e.page),"load fault status mismatch");if(exception)check(cause==(e.page?13:5)&&tval==e.address,"load precise fault cause/tval mismatch");}
  else check(!exception,"unexpected nonmemory exception");
  if(e.writes&&!exception){check(value==e.value,"independent completion value mismatch");if(e.rd){writeWake|=1ULL<<e.dest;expectedWrites.emplace_back(e.dest,e.value);}}
 }
 void retire(Token t,uint64_t pc,uint32_t ins,uint64_t value){
  check(entries.count(t),"retirement unknown full owner");auto&e=entries.at(t);
  check(!e.killed&&!e.error&&!e.page&&!e.retired&&retiredTokens.insert(t).second,"killed/fault/duplicate retirement");
  check(!live.empty()&&live.front()==t,"out of order retirement");live.pop_front();
  check(e.inst.pc==pc&&e.inst.word==ins,"retirement instruction provenance");
  check(e.alias||e.completed,"retirement without accepted completion");if(e.mul||e.div)check((e.mul?mulStarts:divStarts).count(t),"M retirement without actual start");
  if(e.writes&&e.rd){check(value==e.value,"independent retirement value mismatch");architectural[e.rd]=value;committedMapping[e.rd]=e.dest;}
  if(e.mem)check(e.returned&&e.completed,"load retired before response/completion");
  e.retired=true;++retired;
 }
 std::vector<Token> tick(std::array<std::optional<Instruction>,2> in={},bool reset=false){
  d.set_reset(reset);
#define IN(N) d.set_io$$instruction##N##$$valid(bool(in[N]));d.set_io$$instruction##N##$$bits(in[N]?in[N]->word:0xffffffffU);d.set_io$$pc##N(in[N]?in[N]->pc:nextPc)
 IN(0);IN(1);
#undef IN
  d.set_io$$commitEnable(commitEnable);d.set_io$$inspectRegister(0);
  bool ar=cycle>=physicalHold&&cycle%7!=3;
  bool dv=!replies.empty()&&cycle>=replies.front().due&&cycle>=responseHold;
  d.set_io$$physical$$request$$ready(ar);d.set_io$$physical$$response$$valid(dv);d.set_io$$physical$$response$$bits$$data(dv?replies.front().data:0);d.set_io$$physical$$response$$bits$$error(dv&&replies.front().error);d.set_io$$physical$$response$$bits$$pageFault(false);
  bool pv=!ptes.empty()&&cycle>=ptes.front().due;
  d.set_io$$pte$$request$$ready(cycle%5!=2);d.set_io$$pte$$response$$valid(pv);d.set_io$$pte$$response$$bits$$data(pv?ptes.front().data:0);d.set_io$$pte$$response$$bits$$error(false);
  d.step();if(reset){++cycle;return {};}
  auto rs=rows();const auto oldLive=live;std::vector<Token> got;writeWake=0;currentReserve=0;expectedWrites.clear();
  check(d.get_io$$readyMask()==softwareReady,"registered PRF-ready differs from accepted completion/allocation ledger");
  // Validate the pre-edge live snapshot before recording this edge's rename.
  for(auto&r:rs)if(r.pending||r.memoryLive){check(entries.count(r.token),"live row lacks independently allocated full token");auto&e=entries.at(r.token);check(!e.retired&&r.s1==e.s1&&r.s2==e.s2&&r.dest==e.dest,"live row changed immutable rename payload");}
  for(auto t:oldLive){const auto&e=entries.at(t);if(e.mul||e.div){const auto&r=rs[t.index];bool pending=!e.started&&!e.completed&&!e.killed;
   check(r.token==t&&r.pending==pending&&r.m&&r.op==e.op&&r.word==e.word,"M row pending/class differs from independent instruction lifetime");
   if(pending)check(r.r1==bool((softwareReady>>e.s1)&1)&&r.r2==bool((softwareReady>>e.s2)&1),"M owner-ready differs from independent PRF ready ledger");
  }}
  std::optional<unsigned> independentWake;
  if(d.get_io$$loadWake$$valid()){
   check(d.get_io$$lsuComplete$$valid()&&!d.get_io$$lsuComplete$$bits$$exception(),"load promise without successful registered completion");
   Token producer{unsigned(d.get_io$$lsuComplete$$bits$$token$$index()),uint64_t(d.get_io$$lsuComplete$$bits$$token$$tag())};check(entries.count(producer),"load promise unknown full owner");const auto&e=entries.at(producer);
   check(e.mem&&!e.error&&!e.page&&e.dest!=0&&e.returned&&d.get_io$$loadWake$$bits()==e.dest&&d.get_io$$lsuComplete$$bits$$data()==e.value,"load promise differs from independent registered producer owner/value");independentWake=e.dest;
  }
  bool potential=false;std::optional<Token> oldestOriginal;
  for(auto t:oldLive){const auto&e=entries.at(t);if(!(e.mul||e.div)||e.started||e.completed||e.killed)continue;
   const bool a=(softwareReady>>e.s1)&1,b=(softwareReady>>e.s2)&1;
   if(e.mul&&!(a&&b)&&independentWake){
    unsigned dest=*independentWake;potential|=(a||e.s1==dest)&&(b||e.s2==dest);
   }
   if(a&&b){bool available=e.mul?bool(d.get_io$$mulReady()):bool(d.get_io$$divReady());
    if(available){if(!oldestOriginal)oldestOriginal=t;}
    else if(e.div)++unavailableDiv;
   }
  }
  originalAvailable=oldestOriginal.has_value();
  if(potential&&oldestOriginal){
   check(d.get_io$$selectedValid()&&d.get_io$$selectedIndex()==oldestOriginal->index,"stable-load expansion displaced oldest original available M winner");
   const auto&winner=entries.at(*oldestOriginal);oldMulBlocked+=winner.mul;oldDivBlocked+=winner.div;
  }

#define ACCEPT(N) if(d.get_io$$renamed##N##$$valid()){check(in[N].has_value(),"rename without public instruction");Token t{unsigned(d.get_io$$renamed##N##$$bits$$token$$index()),uint64_t(d.get_io$$renamed##N##$$bits$$token$$tag())};check(!entries.count(t),"full token reused");auto old=oldTags.find(t.index);if(old!=oldTags.end()){check(old->second!=t.tag,"ROB index generation not advanced");++reuses;}oldTags[t.index]=t.tag;wraps+=accepted&&t.index==0;Entry e=interpret(*in[N],t,unsigned(d.get_io$$renamed##N##$$bits$$source1()),unsigned(d.get_io$$renamed##N##$$bits$$source2()),unsigned(d.get_io$$renamed##N##$$bits$$destination()),bool(d.get_io$$renamed##N##$$bits$$writesRd()),bool(d.get_io$$renamed##N##$$bits$$moveAlias()));entries.emplace(t,e);live.push_back(t);got.push_back(t);++accepted;}
 ACCEPT(0);ACCEPT(1);
#undef ACCEPT
  for(auto t:got){const auto&e=entries.at(t);if(e.writes&&e.rd&&!e.alias)currentReserve|=1ULL<<e.dest;}
  uint64_t actualReserve=0;
#define RESERVE(N) if(d.get_io$$reserve##N##$$valid()){unsigned dst=d.get_io$$reserve##N##$$bits();check(dst<48,"reserve index range");actualReserve|=1ULL<<dst;}
 RESERVE(0);RESERVE(1);
#undef RESERVE
  check(actualReserve==currentReserve,"PRF reserve differs from independent accepted rename owner");
  if(pv&&d.get_io$$pte$$response$$ready()){if(!(ptes.front().data&1ULL))faultLeaves.insert(ptes.front().address);ptes.pop_front();}
  if(d.get_io$$pte$$request$$valid()&&cycle%5!=2){auto address=d.get_io$$pte$$request$$bits();ptes.push_back({address,tables.pte(address),cycle+2});}
  if(previousMul){check(d.get_io$$mulArithmeticFire(),"registered MUL capture lost following arithmetic event");Token t{unsigned(d.get_io$$mulCaptured$$token$$index()),uint64_t(d.get_io$$mulCaptured$$token$$tag())};const auto&w=*previousMul;check(t==w.token&&d.get_io$$mulCaptured$$left()==w.left&&d.get_io$$mulCaptured$$right()==w.right&&d.get_io$$mulCaptured$$operation()==w.operation&&bool(d.get_io$$mulCaptured$$word())==w.word,"registered MUL capture changed old accepted payload");}
  else check(!d.get_io$$mulArithmeticFire(),"unowned MUL arithmetic event");
  previousMul.reset();
#define START(PREFIX) Start{{unsigned(d.get_io$$##PREFIX##$$bits$$token$$index()),uint64_t(d.get_io$$##PREFIX##$$bits$$token$$tag())},uint64_t(d.get_io$$##PREFIX##$$bits$$pc()),uint64_t(d.get_io$$##PREFIX##$$bits$$left()),uint64_t(d.get_io$$##PREFIX##$$bits$$right()),unsigned(d.get_io$$##PREFIX##$$bits$$operation()),bool(d.get_io$$##PREFIX##$$bits$$word())}
  bool mf=d.get_io$$mulStart$$valid()&&d.get_io$$mulReady();
  if(mf){auto s=START(mulStart);checkStart(s,true,rs);previousMul=s;}
  if(d.get_io$$divStart$$valid()&&d.get_io$$divReady())checkStart(START(divStart),false,rs);
#undef START
  auto count=unsigned(d.get_io$$mulCount());check(count==expectedMulCount,"MUL reservation conservation mismatch");check(!d.get_io$$mulPop()||count>0,"empty MUL pop");expectedMulCount=count+unsigned(mf)-unsigned(bool(d.get_io$$mulPop()));peakMul=std::max(peakMul,count);check(count<=8&&bool(d.get_io$$mulReady())==(count<8),"MUL old-count credit differs from capacity8");if(count==8&&d.get_io$$mulPop()){++fullPop;check(!mf,"MUL borrowed same-edge pop credit");}
  if(d.get_io$$lsuComplete$$valid()&&!d.get_io$$lsuCompleteReady())++lsuHeld;
  if(d.get_io$$selectedValid()&&d.get_io$$mulGrant()&&!d.get_io$$lateAllowed()){++lateRejected;check(!mf,"late rejected candidate started");}
  if(d.get_io$$mulComplete$$valid()){Token t{unsigned(d.get_io$$mulComplete$$bits$$token$$index()),uint64_t(d.get_io$$mulComplete$$bits$$token$$tag())};check(entries.count(t)&&mulStarts.count(t),"MUL completion without original start");check(d.get_io$$mulComplete$$bits$$data()==entries.at(t).value,"independent MUL complete product mismatch");}
  if(d.get_io$$lsuStart$$valid()&&d.get_io$$lsuReady()){
   Token t{unsigned(d.get_io$$lsuStart$$bits$$token$$index()),uint64_t(d.get_io$$lsuStart$$bits$$token$$tag())};check(entries.count(t),"LSU start unknown owner");auto&e=entries.at(t);check(e.mem&&!e.started&&!e.killed,"duplicate/dead/nonload LSU start");check(d.get_io$$lsuStart$$bits$$address()==e.address,"LSU raw effective address mismatch");e.started=true;
  }
  if(d.get_io$$lsuRequestFire()){
   check(d.get_io$$lsuRequestOwner$$valid(),"LSU request lacks exact owner observation");
   Token t{unsigned(d.get_io$$lsuRequestOwner$$bits$$index()),uint64_t(d.get_io$$lsuRequestOwner$$bits$$tag())};
   check(entries.count(t)&&entries.at(t).mem&&entries.at(t).started,"LSU request unknown/unstarted full owner");lsuRequestOwners.push_back(t);
  }
  if(d.get_io$$upstreamRequest$$valid()&&d.get_io$$upstreamRequestReady()){
   check(!lsuRequestOwners.empty(),"native request lacks accepted LSU owner");Token t=lsuRequestOwners.front();lsuRequestOwners.pop_front();auto&e=entries.at(t);
   check(!e.requested&&d.get_io$$upstreamRequest$$bits$$address()==e.address,"native request owner/address mismatch");
   e.requested=true;upstreamOwners.push_back(t);if(!e.page)physicalOwners.push_back(t);
  }
  if(dv&&d.get_io$$physical$$response$$ready()){auto r=replies.front();check(entries.count(r.owner),"physical response full owner lost");entries.at(r.owner).errorServiced|=r.error;replies.pop_front();++responseCount;}
  if(d.get_io$$physical$$request$$valid()){
   Held now{d.get_io$$physical$$request$$bits$$address(),d.get_io$$physical$$request$$bits$$data(),unsigned(d.get_io$$physical$$request$$bits$$size()),unsigned(d.get_io$$physical$$request$$bits$$mask()),bool(d.get_io$$physical$$request$$bits$$write()),bool(d.get_io$$physical$$request$$bits$$uncached()),bool(d.get_io$$physical$$request$$bits$$atomic()),unsigned(d.get_io$$physical$$request$$bits$$atomicOp()),bool(d.get_io$$physical$$request$$bits$$virtualized()),bool(d.get_io$$physical$$request$$bits$$precheckedLoad()),uint32_t(d.get_io$$physical$$request$$bits$$translationEpoch()),bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())};
   if(heldPhysical)check(now==*heldPhysical,"held physical request payload changed");heldPhysical=ar?std::nullopt:std::optional<Held>(now);
   if(ar){check(!physicalOwners.empty(),"physical request lacks prior native owner");Token t=physicalOwners.front();physicalOwners.pop_front();auto&e=entries.at(t);check(std::get<0>(now)==e.pa&&std::get<2>(now)==3&&std::get<3>(now)==255&&!std::get<4>(now)&&!std::get<5>(now)&&!std::get<6>(now)&&!std::get<8>(now)&&!std::get<9>(now)&&e.pa>=0x80200000ULL&&e.pa<=0x80220000ULL-8,"physical load differs from independent owner/address/full RAM contract");e.physicalSeen=true;replies.push_back({t,memory.read(e.pa,3),cycle+latency,e.error});++physicalCount;}
  }else check(!heldPhysical,"held physical VALID withdrawn");
  if(d.get_io$$upstreamResponse$$valid()&&d.get_io$$upstreamResponseReady()){
   check(!upstreamOwners.empty(),"upstream result without accepted native owner");auto t=upstreamOwners.front();upstreamOwners.pop_front();auto&e=entries.at(t);e.returned=true;
   check(bool(d.get_io$$upstreamResponse$$bits$$error())==(e.error||e.page)&&bool(d.get_io$$upstreamResponse$$bits$$pageFault())==e.page,"native precise fault mismatch");if(!e.error&&!e.page)check(d.get_io$$upstreamResponse$$bits$$data()==e.value,"native load bytes mismatch");
  }
#define COMPLETE(N) if(d.get_io$$issued##N##$$valid())complete({unsigned(d.get_io$$issued##N##$$bits$$token$$index()),uint64_t(d.get_io$$issued##N##$$bits$$token$$tag())},d.get_io$$issued##N##$$bits$$data(),d.get_io$$issued##N##$$bits$$exception(),d.get_io$$issued##N##$$bits$$cause(),d.get_io$$issued##N##$$bits$$tval())
 COMPLETE(0);COMPLETE(1);
#undef COMPLETE
  std::vector<std::pair<unsigned,uint64_t>> actualWrites;
#define WRITE(N) if(d.get_io$$write##N##$$valid())actualWrites.emplace_back(unsigned(d.get_io$$write##N##$$bits$$address()),uint64_t(d.get_io$$write##N##$$bits$$data()))
 WRITE(0);WRITE(1);
#undef WRITE
  std::sort(actualWrites.begin(),actualWrites.end());std::sort(expectedWrites.begin(),expectedWrites.end());check(actualWrites==expectedWrites,"PRF numerical writes differ from accepted full-owner completion oracle");
  if(d.get_io$$redirect$$valid()&&!d.get_io$$trap$$valid()){
   Token t{unsigned(d.get_io$$redirect$$bits$$token$$index()),uint64_t(d.get_io$$redirect$$bits$$token$$tag())};check(entries.count(t),"redirect unknown full owner");const auto&e=entries.at(t);if(e.branch)check(d.get_io$$redirect$$bits$$target()==e.value,"decoded branch target differs from raw oracle");
  }
#define RETIRE(N) if(d.get_io$$commit##N##$$valid())retire({unsigned(d.get_io$$commit##N##$$bits$$token$$index()),uint64_t(d.get_io$$commit##N##$$bits$$token$$tag())},d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$data())
 RETIRE(0);RETIRE(1);
#undef RETIRE
  if(d.get_io$$trap$$valid()){
   Token t{unsigned(d.get_io$$trap$$bits$$token$$index()),uint64_t(d.get_io$$trap$$bits$$token$$tag())};check(!live.empty()&&live.front()==t&&entries.count(t),"trap is not exact current head owner");auto&e=entries.at(t);
   check(!e.retired&&!e.killed&&trappedTokens.insert(t).second,"repeated/dead trap owner");check(e.mem&&(e.error||e.page)&&d.get_io$$trap$$bits$$pc()==e.inst.pc&&d.get_io$$trap$$bits$$cause()==(e.page?13:5)&&d.get_io$$trap$$bits$$tval()==e.address,"trap precise fault mismatch");
   for(auto k:live){entries.at(k).killed=true;++killedCount;}live.clear();restore();++traps;
  }else if(d.get_io$$recovery$$valid()&&d.get_io$$ledgerRecoveryAccepted()){
   Token t{unsigned(d.get_io$$recovery$$bits$$token$$index()),uint64_t(d.get_io$$recovery$$bits$$token$$tag())};auto it=std::find(live.begin(),live.end(),t);
   check(it!=live.end(),"recovery boundary not in host live ledger");const auto&e=entries.at(t);
   check((e.branch||e.system)&&!d.get_io$$recovery$$bits$$inclusive(),"unexpected nonbranch/nonCSR or inclusive recovery");
   check(d.get_io$$redirect$$valid()&&d.get_io$$redirect$$bits$$token$$index()==t.index&&d.get_io$$redirect$$bits$$token$$tag()==t.tag&&d.get_io$$redirect$$bits$$pc()==e.inst.pc&&d.get_io$$redirect$$bits$$target()==(e.branch?e.value:e.inst.pc+4),"recovery redirect differs from independent instruction target");
   ++it;for(auto x=it;x!=live.end();++x){entries.at(*x).killed=true;++killedCount;}live.erase(it,live.end());restore();
  }
  softwareReady|=writeWake;
  for(auto t:got){const auto&e=entries.at(t);if(e.writes&&e.rd&&!e.alias)softwareReady&=~(1ULL<<e.dest);}
  ++cycle;return got;
 }
 std::vector<Token> submit(const std::vector<uint32_t>&words){
  std::vector<Instruction> code;for(auto w:words){code.push_back({w,nextPc});nextPc+=4;}
  std::vector<Token> out;unsigned n=0;
  for(unsigned bound=0;bound<2048&&n<code.size();++bound){std::array<std::optional<Instruction>,2> in{};in[0]=code[n];if(n+1<code.size())in[1]=code[n+1];auto got=tick(in);n+=got.size();out.insert(out.end(),got.begin(),got.end());}
  check(n==code.size(),"bounded public allocation timeout");return out;
 }
 void wait(unsigned n){while(n--)tick();}
 void drain(){for(unsigned n=0;n<4096&&(!live.empty()||!lsuRequestOwners.empty()||!physicalOwners.empty()||!upstreamOwners.empty()||!replies.empty()||!ptes.empty()||previousMul);++n)tick();check(live.empty()&&lsuRequestOwners.empty()&&physicalOwners.empty()&&upstreamOwners.empty()&&replies.empty()&&ptes.empty(),"bounded owner drain timeout");wait(12);check(d.get_io$$idle()&&physicalCount==responseCount,"backend idle/physical conservation mismatch");}
 void one(uint32_t w){submit({w});drain();}
 void constant(unsigned rd,uint64_t v){std::vector<uint32_t>x{addi(rd,0,int(v>>55))};for(int i=44;i>=0;i-=11){x.push_back(slli(rd,11));x.push_back(addi(rd,rd,int((v>>i)&2047)));}submit(x);drain();}
 void csr(unsigned n,uint64_t v){constant(31,v);one(n<<20|31<<15|1<<12|0x73);}
 void configure(){using namespace pending_store_reference;csr(0x3b0,allPmp);csr(0x3a0,0x1f);csr(0x180,satp);csr(0x300,(1ULL<<17)|(1ULL<<11));constant(10,va);constant(11,va+4096);constant(25,0xfedcba9876543210ULL);constant(26,0x8000000000000003ULL);constant(27,7);check(d.get_io$$vm$$satp()==satp&&d.get_io$$vm$$dataPrivilege()==1,"real CSR VM configuration mismatch");}
 void requireCoverage(bool yes,const std::string&why){if(!yes)throw std::runtime_error("COVERAGE_NOT_REACHED "+why);}
 void report(const std::string&name){std::cout<<"MUL_LOAD_BACKEND_PASS case="<<name<<" profile="<<(enabled?"on":"off")<<" accepted="<<accepted<<" retired="<<retired<<" starts="<<mulStarts.size()<<" forwarded="<<forwarded<<" left="<<forwardedLeft<<" right="<<forwardedRight<<" both="<<forwardedBoth<<" wraps="<<wraps<<" reuse="<<reuses<<" peak_mul="<<peakMul<<" full_pop="<<fullPop<<" lsu_held="<<lsuHeld<<" late_rejected="<<lateRejected<<" kills="<<killedCount<<" traps="<<traps<<'\n';}
};
int main(int argc,char**argv){try{
 bool on=false;std::string name="ready-variants",mutation;
 for(int i=1;i<argc;++i){std::string s=argv[i];if(s=="--profile=on")on=true;else if(s=="--profile=off")on=false;else if(s=="--observer-high-tag")mutation="high-tag";else if(s=="--observer-value")mutation="value";else if(s.rfind("--",0)==0)throw std::runtime_error("unknown option");else name=s;}
 Bench b(on,mutation);b.configure();unsigned before=b.forwarded;
 if(name=="ready-variants"){
  for(unsigned op=0;op<4;++op)b.one(mInst(20,25,26,op));b.one(mInst(20,25,26,0,true));b.one(mInst(20,0,25));b.one(mInst(0,25,26));
  b.requireCoverage(b.mulHigh>=3&&b.mulW&&b.mulLow,"all MUL product variants");
 }else if(name=="source1"||name=="source2"||name=="same-producer"){
  b.latency=32;b.submit({load(5,10),mInst(20,name=="source2"?25:5,name=="source1"?26:5)});b.drain();
  if(on)b.requireCoverage(b.forwarded>before&&(name!="source1"||b.forwardedLeft)&&(name!="source2"||b.forwardedRight)&&(name!="same-producer"||b.forwardedBoth),"requested stable-load operand capture");
 }else if(name=="two-producers"){
  b.latency=36;b.submit({load(5,10),load(6,11),mInst(20,5,6)});b.drain();b.requireCoverage(b.mulStarts.size()==1,"two-producer dependent MUL start");
 }else if(name=="waw"){
  b.submit({load(5,10),mInst(20,5,25),addi(5,0,17),mInst(21,5,26)});b.drain();b.requireCoverage(b.mulStarts.size()==2,"WAW distinct-source owners");
 }else if(name=="head-wrap"){
  for(unsigned i=0;i<40;++i){b.submit({load(5,10,int((i%8)*8)),mInst(20,5,25)});b.drain();}b.requireCoverage(b.wraps&&b.reuses,"actual ROB index wrap and generation reuse");if(on)b.requireCoverage(b.forwarded>before,"forward after wrapped allocation");
 }else if(name=="kill-consumer"||name=="kill-both"){
  b.latency=120;std::vector<uint32_t>x{mInst(30,25,27,5)};
  if(name=="kill-consumer"){x.push_back(load(5,10));x.push_back(branch(30));}else{x.push_back(branch(30));x.push_back(load(5,10));}x.push_back(mInst(20,5,26));auto t=b.submit(x);b.drain();
  b.requireCoverage(b.entries.at(t.back()).killed&&!b.entries.at(t.back()).retired,"decoded branch killed dependent consumer");if(name=="kill-consumer")b.requireCoverage(b.entries.at(t[1]).retired,"older producer survives consumer kill");else b.requireCoverage(b.entries.at(t[2]).killed,"producer and consumer killed");
 }else if(name=="load-error"||name=="page-fault"){
  b.faultNext=name=="load-error";b.pageNext=name=="page-fault";if(b.pageNext)b.tables.pages[0].flags=0;
  auto t=b.submit({load(5,10),mInst(20,5,26)});b.drain();b.requireCoverage(b.traps==1&&!b.entries.at(t[1]).retired&&!b.mulStarts.count(t[1]),"faulting load never numerically feeds dependent MUL");
  const auto&producer=b.entries.at(t[0]);b.requireCoverage(producer.started&&producer.requested&&producer.returned,"faulting producer accepted native transaction and result");
  if(name=="load-error")b.requireCoverage(producer.physicalSeen&&producer.errorServiced,"actual owner-bound physical error response handshake");
  else b.requireCoverage(!producer.physicalSeen&&b.faultLeaves.count(pending_store_reference::root+8192),"actual invalid leaf PTE response without physical data request");
 }else if(name=="old-mul-contention"||name=="old-div-contention"){
  // Sweep fixed service/arrival phases, not DUT eligibility. Wait for the
  // owner-bound byte-memory reply to be queued AND due before choosing the
  // anchor, so neither cold translation nor memory latency consumes the burst.
  // The release is anchor+4; ready-M burst offsets 0..8 span release-4..+4.
  // Each attempt drains fully; only the unchanged independent winner checker
  // can establish the same-frame potential/original-available witness.
  b.latency=24;
  for(unsigned offset=0;offset<=8;++offset){
   b.responseHold=b.cycle+8192;
   auto owners=b.submit({load(5,10),mInst(20,5,26)});
   for(unsigned bound=0;bound<2048&&(b.replies.empty()||b.cycle<b.replies.front().due);++bound)b.tick();
   b.requireCoverage(!b.replies.empty()&&b.cycle>=b.replies.front().due,"priority phase owner reply queued and due");
   b.check(b.replies.size()==1&&b.replies.front().owner==owners[0]&&!b.entries.at(owners[0]).returned,"priority phase reply owner/hold mismatch");
   unsigned anchor=b.cycle+1;b.responseHold=anchor+4;
   b.wait(anchor+offset-b.cycle);
   std::vector<uint32_t>x;for(unsigned i=0;i<10;++i)x.push_back(mInst(21+i%4,25,27,name=="old-mul-contention"?0:5));
   b.submit(x);b.drain();b.responseHold=0;
   if(name=="old-mul-contention"?b.oldMulBlocked>0:b.oldDivBlocked>0)break;
  }
  b.requireCoverage(name=="old-mul-contention"?b.oldMulBlocked>0:b.oldDivBlocked>0,"actual same-frame load-expansion potential plus original available M winner");
 }else throw std::runtime_error("unknown case");
 b.requireCoverage(mutation.empty(),"observer mutation did not reach an actual MUL start");b.report(name);return 0;
 }catch(const std::exception&e){std::string s=e.what();std::cerr<<"MUL_LOAD_BACKEND_FAIL "<<s<<'\n';return s.find("COVERAGE_NOT_REACHED")!=std::string::npos?2:1;}}
