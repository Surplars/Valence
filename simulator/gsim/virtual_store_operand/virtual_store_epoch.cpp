#define main retained_ready_main
#include "observed_backend.cpp"
#undef main
int main(int argc,char**argv)try {
 const bool mutate=argc>1&&std::string(argv[1])=="--stale-epoch";
 Bench b;b.expectedQuery=true;b.configure();b.warm();
 b.constant(31,satp^(1ULL<<44));
 const auto epochBefore=b.dut.get_io$$epoch();const Bytes before=b.expected;
 const auto beforePhysical=b.physicalCount; const auto beforeRedirects=b.c1SystemRedirects;
 const uint32_t satpWrite=0x180u<<20|31u<<15|1u<<12|0x73;
 auto owners=b.submit({divu(29,25,26),satpWrite,st(10,30)});
 const auto store=owners[2];unsigned prepared=0,epochCycles=0,clear=0;
 for(unsigned n=0;n<600&&!b.entries.at(store).killed;n++){
  const bool q=b.dut.get_io$$descriptorValid()&&b.dut.get_io$$descriptorToken$$index()==store.index&&
   b.dut.get_io$$descriptorToken$$tag()==store.tag;
  const bool s=b.dut.get_io$$poolStageValid()&&b.dut.get_io$$poolStageToken$$index()==store.index&&
   b.dut.get_io$$poolStageToken$$tag()==store.tag;
  prepared+=q||s;
  if((q||s)&&b.dut.backend$clear)clear++;
  if(b.dut.backend$contextMemoryEpoch){epochCycles++;
   b.check(!q&&!s&&!b.dut.backend$capture&&!b.dut.backend$transfer&&!b.dut.get_io$$lsuStart(),
    "context barrier retained speculative virtual-store operands");}
  b.tick();
 }
 b.check(prepared>4&&clear>0&&epochCycles>0,"virtual store SATP prefill/cancel NOT_REACHED");
 b.check(b.entries.at(store).killed&&!b.entries.at(store).started&&!b.entries.at(store).retired&&
  b.physicalCount==beforePhysical,"SATP-cancelled prefill produced side effects");
 b.expected=before;b.drain();
 b.check(b.c1SystemRedirects==beforeRedirects+1&&b.dut.get_io$$epoch()>epochBefore,
  "SATP context publication missing");
 // New ASID is cold; the identical VA now maps elsewhere in the independent PTE responder.
 b.tables.pages[0].physical=ram+16384;
 const auto currentEpoch=uint64_t(b.dut.get_io$$epoch());
 const auto replay=b.submit({st(10,30)})[0];unsigned originChecks=0;
 for(unsigned n=0;n<600&&!b.entries.at(replay).retired;n++){
  b.tick();
  if(b.dut.get_io$$canonicalOrigin$$valid()&&b.dut.get_io$$upstreamFire()){
   const auto observedEpoch=mutate?epochBefore:uint64_t(b.dut.get_io$$canonicalOrigin$$bits$$epoch());
   b.check(b.dut.get_io$$canonicalOrigin$$bits$$token$$index()==replay.index&&
    b.dut.get_io$$canonicalOrigin$$bits$$token$$tag()==replay.tag&&observedEpoch==currentEpoch&&observedEpoch>epochBefore,
    "stale epoch used after SATP publication");originChecks++;
  }
 }
 b.drain();b.check(originChecks==1,"exact replay origin/epoch NOT_REACHED");
 b.check(b.entries.at(replay).pa==ram+16384&&b.entries.at(replay).requested&&b.entries.at(replay).retired&&
  b.physicalCount==beforePhysical+1,"replayed store used stale mapping or missing real response");
 std::cout<<"VIRTUAL_STORE_EPOCH_PASS prepared="<<prepared<<" clear="<<clear<<" context_cycles="<<epochCycles
  <<" origin_checks="<<originChecks<<" old_epoch="<<epochBefore<<" new_epoch="<<currentEpoch<<" replay_pa="<<b.entries.at(replay).pa<<'\n';
}catch(const std::exception&e){std::cerr<<"VIRTUAL_STORE_EPOCH_FAIL "<<e.what()<<'\n';return 1;}
