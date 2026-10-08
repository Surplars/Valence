#include "PrefetchBarrierGsim.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <string>
#include <vector>
int main(int argc,char**argv){
 const bool corrupt=argc>1&&std::string(argv[1])=="--inject-mismatch";
 SPrefetchBarrierGsim d;
 d.set_io$$instruction$$valid(0);d.set_io$$instruction$$bits(0x13);
 d.set_io$$instruction1$$valid(0);d.set_io$$instruction1$$bits(0x13);
 d.set_io$$memory$$request$$ready(1);d.set_io$$memory$$response$$valid(0);
 d.set_io$$memory$$response$$bits$$data(0x123456789abcdef0ULL);
 d.set_io$$memory$$response$$bits$$error(0);d.set_io$$memory$$response$$bits$$pageFault(0);
 d.set_io$$commitEnable(1);d.set_io$$fenceReady(1);
 d.set_io$$busy(1);d.set_io$$bypassBusy(0);d.set_io$$timerInterrupt(0);
 d.set_reset(1);d.step();d.step();d.set_reset(0);
 const std::vector<uint32_t> program={0x80010137U,0x02011113U,0x02015113U,0x000200b7U,0x30009073U,0x00013183U};
 unsigned offered=0,requests=0;bool csr=false,load=false,trap=false;uint64_t value=0,cause=0,trapPc=0;
 std::deque<unsigned> due;
 for(unsigned cycle=0;cycle<400;++cycle){
  // Hold retirement immediately after the head CSR captures its command.
  // The effective privilege can update before ROB retirement; neither stage
  // authorizes a younger load to escape with the prior machine permissions.
#if PREFETCH_BARRIER_ENABLED
  const bool commitEnabled=!(cycle>=101&&cycle<130);
#else
  const bool commitEnabled=!(cycle>=6&&cycle<35);
#endif
  d.set_io$$commitEnable(commitEnabled);
  d.set_io$$busy(cycle<100);d.set_io$$instruction$$valid(offered<program.size());d.set_io$$instruction$$bits(offered<program.size()?program[offered]:0x13);
  d.set_io$$instruction1$$valid(offered+1<program.size());d.set_io$$instruction1$$bits(offered+1<program.size()?program[offered+1]:0x13);
  bool reply=!due.empty()&&due.front()<=cycle;d.set_io$$memory$$response$$valid(reply);d.step();
  if(offered<program.size())offered+=unsigned(d.get_io$$accepted())+unsigned(d.get_io$$accepted1());
  if(d.get_io$$memory$$request$$valid()){
   ++requests;due.push_back(cycle+4);
   std::cout<<"REQUEST cycle="<<cycle<<" address="<<std::hex<<uint64_t(d.get_io$$memory$$request$$bits$$address())<<std::dec<<" data_priv="<<unsigned(d.get_io$$dataPrivilege())<<" virtualized="<<unsigned(d.get_io$$memory$$request$$bits$$virtualized())<<"\n";
  }
  if(reply&&d.get_io$$memory$$response$$ready())due.pop_front();
  auto retire=[&](bool valid,uint64_t pc,uint64_t data){if(!valid)return;
   std::cout<<"COMMIT cycle="<<cycle<<" pc="<<std::hex<<pc<<" data="<<data<<std::dec<<" data_priv="<<unsigned(d.get_io$$dataPrivilege())<<"\n";
   if(pc==0x80000010ULL)csr=true;if(pc==0x80000014ULL){load=true;value=data;}
  };
  retire(d.get_io$$commit0$$valid(),d.get_io$$commit0$$bits$$pc(),d.get_io$$commit0$$bits$$data());
  retire(d.get_io$$commit1$$valid(),d.get_io$$commit1$$bits$$pc(),d.get_io$$commit1$$bits$$data());
  if(d.get_io$$trap()){trap=true;cause=d.get_io$$trapCause()^uint64_t(corrupt);trapPc=d.get_io$$trapPc();std::cout<<"TRAP cycle="<<cycle<<" cause="<<cause<<" pc="<<std::hex<<trapPc<<std::dec<<"\n";}
 }
 std::cout<<"OBSERVATION csr="<<csr<<" load="<<load<<" value=0x"<<std::hex<<value<<std::dec<<" trap="<<trap<<" cause="<<cause<<" requests="<<requests<<" final_data_priv="<<unsigned(d.get_io$$dataPrivilege())<<"\n";
 const bool passed=csr&&!load&&trap&&cause==5&&trapPc==0x80000014ULL&&requests==0;
 std::cout<<(passed?"CONTEXT_WINDOW_PASS":"CONTEXT_WINDOW_FAIL old privilege escaped CSR retirement")<<"\n";
 return !passed;
}
