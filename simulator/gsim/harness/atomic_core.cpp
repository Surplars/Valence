#include "AtomicCoreGsim.h"
#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <deque>
#include <dlfcn.h>
#include <iostream>
#include <memory>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
static constexpr uint64_t base=0x80000000,dataBase=0x80010000;
using Memory=std::array<uint8_t,4096>;
static void check(bool ok,const std::string& s){if(!ok)throw std::runtime_error(s);}
#include "isa_model.h"
#include "reference.h"
static uint32_t addi(unsigned rd,unsigned rs,int v){return (uint32_t(v)&4095)<<20|rs<<15|rd<<7|0x13;}
static uint32_t load(unsigned rd,unsigned rs,int off=0,unsigned size=3){return (uint32_t(off)&4095)<<20|rs<<15|size<<12|rd<<7|3;}
static uint32_t store(unsigned rs,unsigned addr,int off=0,unsigned size=3){return ((uint32_t(off)&4095)>>5)<<25|rs<<20|addr<<15|size<<12|(uint32_t(off)&31)<<7|0x23;}
static uint32_t amo(unsigned op,unsigned rd=3,unsigned addr=1,unsigned rs=2,unsigned size=3,unsigned order=0){return op<<27|order<<25|rs<<20|addr<<15|size<<12|rd<<7|0x2f;}
static bool atomicLegal(uint32_t inst){unsigned f=(inst>>12)&7,op=inst>>27;return (inst&127)==0x2f&&(f==2||f==3)&&
 (op==0||op==1||op==2||op==3||op==4||op==8||op==12||op==16||op==20||op==24||op==28)&&(op!=2||((inst>>20)&31)==0);}
static uint64_t read(const Memory&m,uint64_t a,unsigned bytes){uint64_t v=0;for(unsigned i=0;i<bytes;++i)v|=uint64_t(m[a-dataBase+i])<<(8*i);return v;}
static void write(Memory&m,uint64_t a,uint64_t v,unsigned bytes){for(unsigned i=0;i<bytes;++i)m[a-dataBase+i]=v>>(8*i);}
static uint64_t calculate(unsigned op,uint64_t a,uint64_t b,unsigned bytes){
 if(bytes==4){a=uint32_t(a);b=uint32_t(b);}auto sa=std::bit_cast<int64_t>(bytes==4?extend(a,32):a),sb=std::bit_cast<int64_t>(bytes==4?extend(b,32):b);
 switch(op){case 0:return a+b;case 1:return b;case 4:return a^b;case 8:return a|b;case 12:return a&b;case 16:return sa<sb?a:b;case 20:return sa>sb?a:b;case 24:return std::min(a,b);case 28:return std::max(a,b);default:throw std::runtime_error("bad AMO oracle");}}
struct Reply {uint64_t data;bool error;unsigned due;};
struct Request {uint64_t address,data;unsigned size,mask;bool write;bool operator==(const Request&)const=default;};
struct AtomicResult {uint64_t value;bool error;};
#ifndef CACHED_CORE
#define CACHED_CORE 0
#endif
static unsigned programs=0,commits=0,atomics=0,scSuccess=0,scFailure=0,faults=0,dmaWrites=0,decoderCases=0;
static bool inject=false;
static void run(const char* reference,const std::vector<uint32_t>& code,unsigned seed,unsigned latency,
                bool diff=false,int dmaMode=0,unsigned errorStage=0,int faultIndex=-1,unsigned faultCause=0,uint64_t faultValue=0,const char* benchmark="atomic_mix"){
 auto ptr=std::make_unique<SAtomicCoreGsim>();auto& d=*ptr;std::mt19937_64 rng(seed);Memory actual{},expected{};
 for(unsigned i=0;i<4096;++i)actual[i]=expected[i]=uint8_t(i*31+17);
 std::array<uint64_t,32> regs{};uint64_t pc=base,fetch=base;std::deque<Reply> responses;std::deque<AtomicResult> results;
 std::optional<Request> held;bool active=false,reserved=false,dmaOffer=false,dmaDone=false,clearDone=false;
 uint64_t reservation=0;unsigned reservationBytes=0,activeOp=0,activeTransactions=0,cycle=0,retired=0,atomicCount=0;
 bool finished=false;unsigned firstAtomic=0,lastAtomic=0,lowerReads=0,lowerWrites=0;
 std::unique_ptr<Reference> ref;if(diff){ref=std::make_unique<Reference>(reference);ref->load(code);ref->initializeMemory(expected);}
 d.set_reset(1);d.set_io$$instruction0$$valid(0);d.set_io$$instruction1$$valid(0);d.set_io$$commitEnable(0);
 d.set_io$$dma$$request$$valid(0);d.set_io$$dma$$request$$bits$$atomic(0);d.set_io$$dma$$request$$bits$$atomicOp(0);d.set_io$$dma$$response$$ready(1);
 d.set_io$$memory$$request$$ready(0);d.set_io$$memory$$response$$valid(0);d.set_io$$memory$$response$$bits$$data(0);d.set_io$$memory$$response$$bits$$error(0);
 d.set_io$$clearReservation(0);d.set_io$$decodeInstruction(0);d.step();d.step();d.set_reset(0);
 for(;cycle<100000;++cycle){

#define SUPPLY(N) {uint64_t a=fetch+4*N;bool valid=!finished&&a>=base&&(a-base)/4<code.size();d.set_io$$instruction##N##$$valid(valid);d.set_io$$instruction##N##$$bits(valid?code[(a-base)/4]:0);}
  SUPPLY(0);SUPPLY(1);
#undef SUPPLY
  bool ready=!seed||rng()%4!=0,rv=!responses.empty()&&responses.front().due<=cycle;
  bool commitReady=!seed||rng()%4!=0;
  // Present DMA while the first atomic is locked; for LR it invalidates the reservation before SC.
  if(dmaMode==1&&active&&!dmaDone)dmaOffer=true;
  bool clear=dmaMode==2&&active&&activeOp==2&&!clearDone;if(clear){clearDone=true;reserved=false;}
  d.set_io$$clearReservation(clear);d.set_io$$commitEnable(commitReady);
  d.set_io$$dma$$request$$valid(dmaOffer);d.set_io$$dma$$request$$bits$$address(dataBase);d.set_io$$dma$$request$$bits$$data(0x12345678);
  d.set_io$$dma$$request$$bits$$write(1);d.set_io$$dma$$request$$bits$$size(3);d.set_io$$dma$$request$$bits$$mask(255);
  d.set_io$$memory$$request$$ready(ready);d.set_io$$memory$$response$$valid(rv);
  d.set_io$$memory$$response$$bits$$data(rv?responses.front().data:0);d.set_io$$memory$$response$$bits$$error(rv&&responses.front().error);d.step();
  check(d.get_io$$fetchPc()==fetch,"fetch model");
  fetch=d.get_io$$redirect$$valid()?d.get_io$$redirect$$bits$$target():fetch+4*(d.get_io$$accepted0()+d.get_io$$accepted1());
  bool cpu=d.get_io$$cpuRequest$$valid(),dma=dmaOffer&&d.get_io$$dma$$request$$ready();
  if(active)check(!dma&&!cpu,"interleaved request inside atomic");
  if(dma){write(expected,dataBase,0x12345678,8);reserved=false;dmaOffer=false;dmaDone=true;++dmaWrites;}
  if(cpu&&d.get_io$$cpuRequest$$bits$$atomic()){
   check(pc>=base&&(pc-base)/4<code.size(),"atomic after program end");uint32_t inst=code[(pc-base)/4];
   check(atomicLegal(inst),"atomic started before ROB head");
   check(responses.empty()&&actual==expected,"atomic did not drain previous writes");
   auto addr=regs[(inst>>15)&31],value=regs[(inst>>20)&31];unsigned bytes=1U<<((inst>>12)&3),op=inst>>27;
   check(addr==d.get_io$$cpuRequest$$bits$$address()&&value==d.get_io$$cpuRequest$$bits$$data()&&op==d.get_io$$cpuRequest$$bits$$atomicOp(),"atomic dependency/address/op mapping");
   check(!d.get_io$$cpuRequest$$bits$$write(),"atomic marked ordinary store");
   check(addr>=dataBase&&addr+bytes<=dataBase+4096&&!(addr&(bytes-1)),"bad atomic escaped LSU");
   uint64_t result=read(expected,addr,bytes);bool error=false;
   if(op==3){bool success=reserved&&reservation==addr&&reservationBytes==bytes;result=success?0:1;
    if(success){++scSuccess;error=errorStage==2;if(!error)write(expected,addr,value,bytes);}else ++scFailure;
   }else {result=bytes==4?extend(result,32):result;error=errorStage==1||(op!=2&&errorStage==2);
    if(op!=2&&!error)write(expected,addr,calculate(op,result,value,bytes),bytes);}
   if(op==2||op==3||(addr>>6)==(reservation>>6))reserved=false;
   if(op==2&&!error&&!clear){reserved=true;reservation=addr;reservationBytes=bytes;}
   results.push_back({result,error});active=true;activeOp=op;activeTransactions=0;++atomics;++atomicCount;
   if(atomicCount==1)firstAtomic=cycle;lastAtomic=cycle;
  }else if(cpu&&d.get_io$$cpuRequest$$bits$$write()&&(d.get_io$$cpuRequest$$bits$$address()>>6)==(reservation>>6))reserved=false;
  bool bv=d.get_io$$memory$$request$$valid();Request bus{d.get_io$$memory$$request$$bits$$address(),d.get_io$$memory$$request$$bits$$data(),d.get_io$$memory$$request$$bits$$size(),d.get_io$$memory$$request$$bits$$mask(),bool(d.get_io$$memory$$request$$bits$$write())};
  if(held)check(bv&&bus==*held,"held lower request changed");held=bv&&!ready?std::optional<Request>(bus):std::nullopt;
  if(bv&&ready){
   if(bus.write)++lowerWrites;else ++lowerReads;
   check(!d.get_io$$memory$$request$$bits$$atomic(),"atomic leaked below execution boundary");
   check(bus.address>=dataBase&&bus.address+(1U<<bus.size)<=dataBase+4096,"unexpected non-RAM request");
   bool error=false;if(active){++activeTransactions;error=(errorStage==1&&!bus.write)||(errorStage==2&&bus.write);}
   uint64_t beatAddr=bus.address&~UINT64_C(7);Reply reply{bus.write||error?0:read(actual,beatAddr,8),error,cycle+latency};
   if(bus.write&&!error)for(unsigned b=0;b<8;++b)if(bus.mask&(1U<<b))actual[beatAddr-dataBase+b]=bus.data>>(8*b);
   responses.push_back(reply);
  }
  if(rv&&d.get_io$$memory$$response$$ready())responses.pop_front();
  if(active&&d.get_io$$cpuResponse()){active=false;check(responses.empty(),"early atomic response");}
  auto commit=[&](bool valid,uint64_t at,uint32_t inst,unsigned rd,bool writes,uint64_t data,uint64_t next){if(!valid)return;
   check(commitReady,"retirement while disabled");check(at==pc&&inst==code[(pc-base)/4],"commit PC/instruction expected="+std::to_string(pc)+" actual="+std::to_string(at));
   Expected out;out.nextPc=pc+4;out.rd=(inst>>7)&31;
   if((inst&127)==0x2f){check(!results.empty()&&!results.front().error,"atomic committed before completion/on error");out.result=results.front().value;results.pop_front();}
   else {auto e=decode(inst);check(e,"unexpected illegal retirement");out=interpret(*e,inst,pc,regs,expected);check(!out.fault,"fault retired");
    if(e->memory==2)write(expected,out.target,regs[(inst>>20)&31],1U<<((inst>>12)&3));}
   if(inject&&(inst&127)==0x2f){data^=1;inject=false;}
   check(next==out.nextPc&&rd==out.rd&&writes==(out.rd!=0)&&(!writes||data==out.result),"atomic core commit mismatch PC="+std::to_string(pc));
   if(writes)regs[rd]=out.result;pc=out.nextPc;++retired;++commits;if(ref)ref->compare(regs,pc);
  };
#define COMMIT(N) commit(d.get_io$$commit##N##$$valid(),d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc());
  COMMIT(0);COMMIT(1);
#undef COMMIT
  if(d.get_io$$exception$$valid()){
   check(faultIndex>=0&&pc==base+4*faultIndex,"unexpected precise exception");
   check(d.get_io$$exception$$bits$$pc()==pc&&d.get_io$$exception$$bits$$cause()==faultCause&&d.get_io$$exception$$bits$$tval()==faultValue,"exception metadata");
   ++faults;finished=true;
  }else if(pc==base+code.size()*4) {check(faultIndex<0,"missing exception");finished=true;}
  if(finished&&!d.get_io$$memoryBusy()&&responses.empty()&&!dmaOffer){check(actual==expected,"final RAM mismatch");if(ref)ref->compareMemory(expected);break;}
 }
 check(cycle<100000,"atomic core timeout");if(dmaMode==1)check(dmaDone,"missing DMA witness");if(dmaMode==2)check(clearDone,"missing clear witness");
 ++programs;
 if(std::string(benchmark)=="read_reuse")check(lowerReads==(CACHED_CORE?1U:256U),"reused reads must hit enabled cache");
 if(code.size()>100)std::cout<<"ATOMIC_CORE name="<<benchmark<<" cached="<<CACHED_CORE<<" lowerReads="<<lowerReads<<" lowerWrites="<<lowerWrites<<" latency="<<latency<<" seed="<<seed<<" retired="<<retired<<" cycles="<<cycle+1<<" atomics="<<atomicCount<<" atomicStartSpan="<<lastAtomic-firstAtomic<<"\n";
}
static void decodeTest(){auto d=std::make_unique<SAtomicCoreGsim>();d->set_reset(1);d->step();
 for(unsigned op=0;op<32;++op)for(unsigned f=0;f<8;++f)for(unsigned order=0;order<4;++order)for(unsigned rs:{0U,2U,31U}){
  uint32_t inst=amo(op,7,5,rs,f,order);d->set_io$$decodeInstruction(inst);d->step();bool legal=atomicLegal(inst);
  check(bool(d->get_io$$decodeLegal())==legal,"atomic decoder legality");
  if(legal){check(d->get_io$$decoded$$atomic()&&d->get_io$$decoded$$memory()&&!d->get_io$$decoded$$store()&&d->get_io$$decoded$$rename$$writesRd(),"atomic decoder class");
   check(d->get_io$$decoded$$rename$$rs1()==5&&d->get_io$$decoded$$rename$$rs2()==rs&&d->get_io$$decoded$$rename$$rd()==7&&d->get_io$$decoded$$immediate()==0&&d->get_io$$decoded$$memorySize()==f,"atomic decoder dependencies");}
  ++decoderCases;
 }}
int main(int argc,char**argv){try{check(argc>=2,"usage: atomic-core NEMU.so [--inject-mismatch]");inject=argc>2;decodeTest();
 for(unsigned latency:{1U,12U})for(unsigned seed:{0U,8191U}){
  std::vector<uint32_t> code{0x00010097,addi(2,0,-1)};
  for(unsigned op:{0U,1U,4U,8U,12U,16U,20U,24U,28U})for(unsigned size:{2U,3U})for(unsigned order=0;order<4;++order){
   code.push_back(addi(5,2,-1));code.push_back(store(5,1));code.push_back(amo(op,3,1,2,size,order));code.push_back(addi(2,3,17));code.push_back(load(4,1));
  }
  run(argv[1],code,seed,latency,true);
  for(bool reuse:{true,false}){
   std::vector<uint32_t> reads{0x00010097};
   for(unsigned n=0;n<256;++n)reads.push_back(load(2+n%16,1,reuse?0:(n%256)*8));
   run(argv[1],reads,seed,latency,true,0,0,-1,0,0,reuse?"read_reuse":"read_stream");
  }
  run(argv[1],{0x00010097,addi(2,0,19),amo(2,3,1,0),amo(3),amo(3),load(4,1)},seed,latency,true);
  run(argv[1],{0x00010097,addi(1,1,4),addi(2,0,-1),amo(1,0,1,2,2,3),amo(2,3,1,0,2),amo(3,4,1,2,2),load(5,1,0,2)},seed,latency,true);
  run(argv[1],{0x00010097,amo(2,3,1,0),addi(2,0,19),store(2,1),amo(3),load(4,1)},seed,latency);
  run(argv[1],{0x00010097,amo(2,3,1,0),addi(2,0,19),amo(3),load(4,1)},seed,latency,false,1);
  run(argv[1],{0x00010097,amo(2,3,1,0),addi(2,0,19),amo(3),load(4,1)},seed,latency,false,2);
  // A taken branch must squash younger AMO/SC and their side effects.
  run(argv[1],{0x00010097,addi(2,0,19),0x00000663,amo(0),amo(3),load(4,1)},seed,latency,true);
  for(unsigned op:{0U,2U,3U}){
   auto first=op==2?4U:6U;
   run(argv[1],{0x00010097,addi(1,1,1),amo(op,3,1,op==2?0:2),store(2,1,7)},seed,latency,false,0,0,2,first,dataBase+1);
   run(argv[1],{0x100000b7,amo(op,3,1,op==2?0:2),0x00010117,store(0,2)},seed,latency,false,0,0,1,first+1,0x10000000);
  }
  run(argv[1],{0x00010097,amo(2,3,1,0),amo(3),store(2,1,8)},seed,latency,false,0,2,2,7,dataBase);
  for(unsigned stage:{1U,2U})run(argv[1],{0x00010097,addi(2,0,9),amo(0),store(2,1,8)},seed,latency,false,0,stage,2,7,dataBase);
  run(argv[1],{0x00010097,amo(2,3,1,0),store(2,1,8)},seed,latency,false,0,1,1,5,dataBase);
  for(auto inst:{amo(31),amo(2,3,1,2),amo(0,3,1,2,1)})run(argv[1],{0x00010097,inst,store(2,1)},seed,latency,false,0,0,1,2,inst);
 }
 std::cout<<"GSIM atomic core + NEMU subset: PASS programs="<<programs<<" commits="<<commits<<" atomics="<<atomics<<" SC="<<scSuccess<<"/"<<scFailure<<" faults="<<faults<<" DMA="<<dmaWrites<<" decoder="<<decoderCases<<"\n";
}catch(const std::exception&e){std::cerr<<"GSIM atomic core: FAIL "<<e.what()<<"\n";return 1;}}
