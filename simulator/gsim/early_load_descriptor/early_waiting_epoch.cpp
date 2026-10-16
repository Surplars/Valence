#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main() try {
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 b.constant(25,(va+4096)*7);b.constant(26,7);b.constant(31,satp ^ (1ULL<<44)); // Change ASID while preserving the same page-table root.
 const auto epochBefore=b.dut.get_io$$epoch();
 const auto redirectsBefore=b.c1SystemRedirects;
 // Older DIVU delays head eligibility. The younger DIVU remains unresolved
 // when SATP starts, so its consumer has a real waiting Q to cancel.
 const uint32_t satpWrite=0x180u<<20|31u<<15|1u<<12|0x73;
 auto owners=b.submit({divu(30,25,26),satpWrite,divu(29,25,26),ld(20,29)});
 const auto producer=owners[2],load=owners[3];
 unsigned waiting=0,waitingClear=0,epochCycles=0;bool sawClear=false;
 for(unsigned n=0;n<600&&!b.entries.at(load).killed;++n){
  bool q=b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==load.index&&b.dut.get_io$$descriptorToken$$tag()==load.tag;
  bool s=b.dut.get_io$$poolStageValid()&&b.dut.get_io$$poolStageToken$$index()==load.index&&b.dut.get_io$$poolStageToken$$tag()==load.tag;
  const bool unready=!b.entries.at(producer).completed;
  if(q&&unready){++waiting;b.check(!s&&!b.entries.at(load).started,"waiting SATP load acquired operands or launched");}
  if(q&&unready&&b.dut.backend$clear&&b.dut.get_io$$shadow$$reserveSystem()){
   ++waitingClear;sawClear=true;
   b.check(!b.dut.backend$capture&&!b.dut.backend$transfer,"system reservation failed to cancel waiting Q");
  }
  if(b.dut.backend$contextMemoryEpoch){
   ++epochCycles;
   b.check(sawClear&&!q&&!s&&!b.dut.backend$capture&&!b.dut.backend$transfer&&!b.dut.get_io$$lsuStart(),"SATP epoch retained or recaptured speculative memory");
  }
  b.tick();
 }
 b.drain();
 std::cout<<"EARLY_EPOCH_WITNESS waiting="<<waiting<<" clear="<<waitingClear<<" context="<<epochCycles<<" redirects_before="<<redirectsBefore<<" redirects_after="<<b.c1SystemRedirects<<" epoch_before="<<epochBefore<<" epoch_after="<<b.dut.get_io$$epoch()<<" satp="<<b.dut.get_io$$vm$$satp()<<" killed="<<b.entries.at(load).killed<<"\n";
 b.check(waiting>=4&&waitingClear==1&&epochCycles>0,"missing waiting Q/system clear/context epoch witness");
 b.check(b.c1SystemRedirects==redirectsBefore+1&&b.dut.get_io$$epoch()>epochBefore,"missing actual SATP epoch/redirect");
 b.check(b.entries.at(load).killed&&!b.entries.at(load).started&&!b.entries.at(load).retired,"SATP-cancelled waiting load affected memory or retirement");
 b.check(b.entries.at(owners[0]).retired&&b.entries.at(owners[1]).retired,"valid pre-epoch work failed to retire");
 std::cout<<"EARLY_WAITING_EPOCH_PASS waiting_cycles="<<waiting<<" waiting_system_clear="<<waitingClear<<" context_epoch_cycles="<<epochCycles<<" epoch_before="<<epochBefore<<" epoch_after="<<b.dut.get_io$$epoch()<<"\n";
} catch(const std::exception&e){std::cerr<<"EARLY_WAITING_EPOCH_FAIL "<<e.what()<<'\n';return 1;}
