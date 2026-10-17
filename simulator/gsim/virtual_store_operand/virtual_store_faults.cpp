#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main()try {
 unsigned cases=0,totalPrefills=0;
 for(unsigned kind=0;kind<5;kind++){
  Bench b;b.expectedQuery=true;b.configure();
  if(kind==0)b.tables.pages[0].flags=0;       // absent/invalid PTE
  if(kind==1)b.tables.pages[0].flags=0xc3;    // present read-only leaf
  if(kind==2)b.tables.pages[0].flags=0x87;    // A=0
  if(kind==3)b.tables.pages[0].flags=0x47;    // D=0
  b.expectedStoreFaultCause=kind==4?6:15;b.faultStore=true;b.denyStore=true;
  b.commitEnable=false;const auto before=b.physicalCount;
  auto owners=b.submit({divu(29,25,26),st(10,30,kind==4?1:0)});b.oldStore=owners[1];
  unsigned prefills=0;
  for(unsigned n=0;n<80;n++){
   b.tick();
   if(b.dut.get_io$$poolStageValid()&&b.dut.get_io$$poolStageToken$$index()==owners[1].index&&
    b.dut.get_io$$poolStageToken$$tag()==owners[1].tag)prefills++;
   b.check(!b.traps&&!b.entries.at(owners[1]).started&&b.physicalCount==before,
    "inert invalid store prefill raised speculative exception or write");
  }
  b.check(prefills>50,"invalid virtual operand prefill NOT_REACHED");
  b.commitEnable=true;b.drain();
  b.check(b.traps==1&&b.entries.at(owners[1]).completed&&!b.entries.at(owners[1]).requested&&
   !b.entries.at(owners[1]).retired&&b.physicalCount==before,"precise invalid store escaped head fault boundary");
  std::cout<<"VIRTUAL_STORE_FAULT_CASE kind="<<kind<<" prefills="<<prefills<<" cause="<<b.expectedStoreFaultCause<<'\n';
  cases++;totalPrefills+=prefills;
 }
 std::cout<<"VIRTUAL_STORE_FAULTS_PASS cases="<<cases<<" prefills="<<totalPrefills<<" speculative_faults=0 physical_writes=0\n";
}catch(const std::exception&e){std::cerr<<"VIRTUAL_STORE_FAULTS_FAIL "<<e.what()<<'\n';return 1;}
