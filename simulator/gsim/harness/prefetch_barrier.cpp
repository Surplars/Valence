#include "PrefetchBarrierGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <deque>
#ifndef PREFETCH_BARRIER_ENABLED
#define PREFETCH_BARRIER_ENABLED 1
#endif
static void check(bool p,const char*m){if(!p)throw std::runtime_error(m);}
static uint32_t csr(unsigned a){return (a<<20)|(1<<15)|(1<<12)|0x73;}
static bool retired(SPrefetchBarrierGsim&d,uint64_t pc){return
 (d.get_io$$commit0$$valid()&&d.get_io$$commit0$$bits$$pc()==pc)||
 (d.get_io$$commit1$$valid()&&d.get_io$$commit1$$bits$$pc()==pc);}
static void reset(SPrefetchBarrierGsim&d,bool bypass){
 d.set_io$$instruction$$valid(0);d.set_io$$instruction$$bits(0x13);
 d.set_io$$instruction1$$valid(0);d.set_io$$instruction1$$bits(0x13);
 d.set_io$$memory$$request$$ready(1);d.set_io$$memory$$response$$valid(0);
 d.set_io$$memory$$response$$bits$$data(0x123456789abcdef0ULL);d.set_io$$memory$$response$$bits$$error(0);d.set_io$$memory$$response$$bits$$pageFault(0);d.set_io$$busy(1);d.set_io$$bypassBusy(bypass);d.set_io$$timerInterrupt(0);d.set_io$$commitEnable(1);d.set_io$$fenceReady(1);
 d.set_reset(1);d.step();d.step();d.set_reset(0);
}
int main(int argc,char**argv){try{
 const std::string mode=argc>1?argv[1]:"";
 const bool bypass=mode=="--bypass-busy";unsigned completed=0;
 for(uint32_t instruction:{csr(0x3a0),csr(0x180),csr(0x300),0x12000073U,0x30200073U,0x10200073U,0x0000100fU,0x00000073U,0xffffffffU}){
  if(mode=="--only-mprv"&&instruction!=csr(0x300))continue;
  SPrefetchBarrierGsim d;reset(d,bypass);
  std::vector<uint32_t> program={0x80010137U,0x02011113U,0x02015113U,0x01f00093U,instruction,0x00013183U}; // x2=RAM, x1=31, target + younger load
  if(instruction==csr(0x180))program={0x80010137U,0x02011113U,0x02015113U,0x00100093U,0x03f09093U,0x01f0e093U,instruction,0x00013183U}; // Sv39 PPN31
  if(instruction==csr(0x300))program={0x80010137U,0x02011113U,0x02015113U,0x000200b7U,instruction,0x00013183U}; // MPRV with MPP=U
  const uint64_t targetPc=0x80000000ULL+4*(program.size()-2);
  unsigned offered=0;bool targetDone=false,trapped=false,sawVm=false,sawFence=false,sawRedirect=false;
  std::deque<unsigned> memoryDue;
  const bool fault=instruction==0x00000073U||instruction==0xffffffffU;
  for(unsigned cycle=0;cycle<500&&!targetDone&&!trapped;++cycle){
   bool busy=cycle<100;d.set_io$$busy(busy);
   const bool commitEnabled=!(PREFETCH_BARRIER_ENABLED&&cycle>=101&&cycle<130);
   d.set_io$$commitEnable(commitEnabled);d.set_io$$fenceReady(instruction!=0x0000100fU||cycle>=150);d.set_io$$instruction$$valid(offered<program.size());
   d.set_io$$instruction$$bits(offered<program.size()?program[offered]:0x13);
   d.set_io$$instruction1$$valid(offered+1<program.size());
   d.set_io$$instruction1$$bits(offered+1<program.size()?program[offered+1]:0x13);
   const bool reply=!memoryDue.empty()&&memoryDue.front()<=cycle;d.set_io$$memory$$response$$valid(reply);
   d.step();
   if(offered<program.size())offered+=unsigned(d.get_io$$accepted())+unsigned(d.get_io$$accepted1());
   if(d.get_io$$memory$$request$$valid()) {
    check(commitEnabled,"young memory crossed unretired context owner");
    check(instruction!=0x0000100fU||cycle>=150,"young memory crossed held FENCE.I drain");
    std::cerr<<"CONTEXT_MEMORY instruction=0x"<<std::hex<<instruction<<" address=0x"<<uint64_t(d.get_io$$memory$$request$$bits$$address())
      <<" satp=0x"<<uint64_t(d.get_io$$satp())<<std::dec<<" cycle="<<cycle<<" cfg="<<unsigned(d.get_io$$pmpCfg0())
      <<" fetch_priv="<<unsigned(d.get_io$$privilege())<<" data_priv="<<unsigned(d.get_io$$dataPrivilege())
      <<" virtualized="<<unsigned(d.get_io$$memory$$request$$bits$$virtualized())<<"\n";
    check(d.get_io$$memory$$request$$bits$$address()==0x80010000ULL,"young load address mismatch");
    if(instruction==csr(0x3a0))check(d.get_io$$pmpCfg0()==31,"young load crossed active context update");
    if(instruction==csr(0x300))check(d.get_io$$dataPrivilege()==0,"young load crossed active context update");
    if(instruction==csr(0x180))check(d.get_io$$satp()==0x800000000000001fULL,"young load crossed active context update");
    if(instruction==0x30200073||instruction==0x10200073)check(d.get_io$$privilege()==0,"young load crossed active context update");
    memoryDue.push_back(cycle+4);
   }
   if(reply&&d.get_io$$memory$$response$$ready())memoryDue.pop_front();
   check(!retired(d,targetPc+4),"younger load retired across context redirect");
   const bool commit=retired(d,targetPc);
   if(busy&&PREFETCH_BARRIER_ENABLED){
    check(!commit&&!d.get_io$$trap()&&!d.get_io$$vmFlush()&&!d.get_io$$fenceFlush(),"system or trap crossed autonomous prefetch busy");
    check(d.get_io$$pmpCfg0()==0&&d.get_io$$satp()==0&&d.get_io$$privilege()==3,"context changed before prefetch drain");
    check(d.get_io$$memoryBusy(),"external prefetch owner missing from memoryBusy");
   }
   sawRedirect|=d.get_io$$redirect();sawVm|=d.get_io$$vmFlush();sawFence|=d.get_io$$fenceFlush();targetDone=commit;trapped=d.get_io$$trap();
  }
  check(offered==program.size(),"barrier case never reached real system instruction");
  check(fault?trapped:targetDone,"system/trap failed to progress after prefetch drain");
  if(instruction==csr(0x3a0))check(d.get_io$$pmpCfg0()==31,"PMP committed value mismatch");
  if(instruction==csr(0x180))check(d.get_io$$satp()==0x800000000000001fULL&&sawRedirect,"SATP committed value/redirect mismatch");
  if(instruction==csr(0x300))check(d.get_io$$dataPrivilege()==0,"MPRV committed privilege mismatch");
  if(instruction==0x12000073)check(sawVm,"SFENCE missing translation flush");
  if(instruction==0x0000100f)check(sawFence,"FENCE.I missing cache flush");
  if(instruction==0x30200073||instruction==0x10200073)check(d.get_io$$privilege()==0,"return privilege mismatch");
  if(fault)check(d.get_io$$trapPc()==targetPc&&d.get_io$$trapCause()==(instruction==0x00000073?11:2),"precise exception PC/cause mismatch");
  ++completed;
 }
 if(PREFETCH_BARRIER_ENABLED) {
  SPrefetchBarrierGsim d;reset(d,false);d.set_io$$busy(0);
  const std::vector<uint32_t> setup={0x08000093U,csr(0x304),0x00800093U,csr(0x300)};
  unsigned offered=0;bool done=false;
  for(unsigned n=0;n<400&&!done;++n){d.set_io$$instruction$$valid(offered<setup.size());d.set_io$$instruction$$bits(offered<setup.size()?setup[offered]:0x13);d.step();if(offered<setup.size()&&d.get_io$$accepted())++offered;done=retired(d,0x8000000c);}
  check(done,"interrupt setup failed");d.set_io$$instruction$$valid(0);d.set_io$$instruction$$bits(0x13);
 d.set_io$$instruction1$$valid(0);d.set_io$$instruction1$$bits(0x13);
 d.set_io$$memory$$request$$ready(1);d.set_io$$memory$$response$$valid(0);
 d.set_io$$memory$$response$$bits$$data(0x123456789abcdef0ULL);d.set_io$$memory$$response$$bits$$error(0);d.set_io$$memory$$response$$bits$$pageFault(0);d.set_io$$busy(1);d.set_io$$timerInterrupt(1);
  for(unsigned n=0;n<80;++n){d.step();check(!d.get_io$$trap(),"interrupt crossed autonomous prefetch busy");}
  d.set_io$$busy(0);bool trapped=false;for(unsigned n=0;n<200&&!trapped;++n){d.step();trapped=d.get_io$$trap();}
  check(trapped&&d.get_io$$trapCause()==0x8000000000000007ULL,"interrupt failed after drain");++completed;
 }
 std::cout<<"PREFETCH_BARRIER_PASS cases="<<completed<<"\n";return 0;
 }catch(const std::exception&e){std::cerr<<"PREFETCH_BARRIER_FAIL "<<e.what()<<"\n";return 1;}}
