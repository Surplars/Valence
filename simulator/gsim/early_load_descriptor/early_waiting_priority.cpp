#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try{
 Bench b;b.expectedQuery=true;b.configure();b.warm();b.constant(25,(va+4096)*7);b.constant(26,7);
 const auto owners=b.submit({divu(29,25,26),ld(20,29)});
 bool waiting=false;
 for(unsigned n=0;n<30&&!waiting;n++){
  waiting=b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==owners[1].index&&
   b.dut.get_io$$descriptorToken$$tag()==owners[1].tag&&!b.entries.at(owners[0]).completed;
  if(!waiting)b.tick();
 }
 b.check(waiting,"priority fixture did not reserve unready Q");
 auto ready=b.submit({ld(21,11)})[0];
 bool selected=false,readyQSeen=false;uint64_t selectedCycle=0;
 for(unsigned n=0;n<100&&!selected;++n){
  readyQSeen |= b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==ready.index&&
   b.dut.get_io$$descriptorToken$$tag()==ready.tag;
  selected=b.dut.get_io$$poolStageValid()&&b.dut.get_io$$poolStageToken$$index()==ready.index&&
   b.dut.get_io$$poolStageToken$$tag()==ready.tag;
  if(selected)selectedCycle=b.cycle;else b.tick();
 }
 // The virtual-memory launch guard may still block behind the older uncanonical
 // load. This test checks metadata/preparation priority, not a new ordering bypass.
  b.check(readyQSeen&&selected&&!b.entries.at(owners[0]).completed,"waiting Q was not replaced by exact younger ready preparation");
 b.check(!b.entries.at(ready).started,"younger virtual load bypassed older uncanonical owner");
 b.drain();b.check(b.entries.at(owners[1]).retired&&b.entries.at(ready).retired,"preempted waiting owner lost");
 std::cout<<"EARLY_WAITING_PRIORITY_PASS exact_ready_q=1 ready_start="<<b.entries.at(ready).start<<" producer_complete="<<b.entries.at(owners[0]).complete<<"\n";
}catch(const std::exception&e){std::cerr<<"EARLY_WAITING_PRIORITY_FAIL "<<e.what()<<'\n';return 1;}
