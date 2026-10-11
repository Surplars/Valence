#include <array>
struct PerfCounts {
 uint64_t cycles=0,retired=0, commits[3]={}, headEmpty=0,headNotDone=0,headOperandsWait=0,headMemory=0, memoryCompletionBlocked=0,storeBlocked=0,unknownStoreBlocked=0;
 uint64_t readMiss=0,writeMiss=0,missBlocked=0,refill=0,eviction=0,requestCause[8]={};
 void sample(SBoardSocGsim &d) {
  ++cycles; unsigned n=d.get_io$$commit0()+d.get_io$$commit1(); retired+=n; ++commits[n];
  headEmpty+=!d.get_io$$headProfile$$valid(); headNotDone+=d.get_io$$headProfile$$valid()&&!d.get_io$$headProfile$$done();
  headOperandsWait+=d.get_io$$headProfile$$valid()&&d.get_io$$headProfile$$queued()&&!d.get_io$$headProfile$$operandsReady();
  headMemory+=d.get_io$$headProfile$$valid()&&d.get_io$$headProfile$$memory();
  memoryCompletionBlocked+=d.get_io$$headProfile$$memoryCompletionBlocked();
  storeBlocked+=d.get_io$$headProfile$$candidateLoadBlockedByStore(); unknownStoreBlocked+=d.get_io$$headProfile$$candidateLoadBlockedByUnknownStore();
  readMiss+=d.get_io$$cacheProfile$$readMiss();writeMiss+=d.get_io$$cacheProfile$$writeMiss();missBlocked+=d.get_io$$cacheProfile$$missBlocked();refill+=d.get_io$$cacheProfile$$refillCycle();eviction+=d.get_io$$cacheProfile$$evictionCycle();
  ++requestCause[d.get_io$$headProfile$$memoryRequestStallCause()];
 }
 void report(const char *name) {
  std::cout<<"BOARD_IPC name="<<name<<" cycles="<<cycles<<" retired="<<retired<<" ipc="<<double(retired)/cycles<<" zero_commit="<<commits[0]<<" single_commit="<<commits[1]<<" dual_commit="<<commits[2]<<" head_empty="<<headEmpty<<" head_not_done="<<headNotDone<<" head_operands_wait="<<headOperandsWait<<" head_memory="<<headMemory<<" memory_completion_blocked="<<memoryCompletionBlocked<<" store_blocked="<<storeBlocked<<" unknown_store_blocked="<<unknownStoreBlocked<<" read_miss="<<readMiss<<" write_miss="<<writeMiss<<" miss_blocked="<<missBlocked<<" refill="<<refill<<" eviction="<<eviction;
  for(unsigned i=0;i<8;++i)std::cout<<" request_cause_"<<i<<"="<<requestCause[i]; std::cout<<"\n";
 }
};
struct PerfObserver {
 PerfCounts all, roi; uint64_t startPc=0,endPc=0; bool active=false,finished=false;
 static void sample(SBoardSocGsim &d,void *p){auto &o=*static_cast<PerfObserver*>(p);o.all.sample(d);
  bool begin=(d.get_io$$commit0()&&d.get_io$$commit0Pc()==o.startPc)||(d.get_io$$commit1()&&d.get_io$$commit1Pc()==o.startPc);
  bool end=(d.get_io$$commit0()&&d.get_io$$commit0Pc()==o.endPc)||(d.get_io$$commit1()&&d.get_io$$commit1Pc()==o.endPc);
  if(begin&&!o.finished)o.active=true;
  if(o.active)o.roi.sample(d);
  if(end&&o.active){o.active=false;o.finished=true;}
 }
 void report(){all.report("whole_run_after_reset_includes_UART");if(finished)roi.report("first_start_time_rdtime_retire_through_stop_time_rdtime_retire_inclusive");}
};
