// Passive, overlapping event matrix. Not an additive causal CPI breakdown.
#include "performance_observer.h"
#include <map>
#include <algorithm>
#include <stdexcept>
#include <vector>
#include <fstream>
#include <cstdlib>
static const char *frontendNames[]={"pause","correction","flush","recovery","rollback","allocate_dispatch_block","allocate_recovery_block","allocate_tag_exhausted","allocate_rob_full","allocate_prf0_block","allocate_prf1_block","full_consume_supply","three_consume_two_supply","supply0_not_capture","supply_lane1_short","virtual_request","virtual_blocked","virtual_reply","physical_request","physical_blocked","physical_reply","translation_request","translation_reply","bare_translation_request","frontend_pause","frontend_invalidate","frontend_no_lane0","redirect_trap","redirect_system","redirect_replay","redirect_branch_or_other_local","redirect_external","fetch_tl_get","allocate0","renamed0","prf_empty","frontend_enabled","translation_wait_no_reply","physical_wait_no_reply","empty_no_supply_unpaused","reply_next_request_blocked","identity_virtual_capture"};
// Exact cache transaction classes and overlapping state/event cross-tabs.
struct CacheCounts {
 static constexpr const char *names[16]={"accepted_hit","accepted_miss","accepted_fallback","demand_refill_request","demand_refill_complete","demand_refill_error","demand_refill_install","waiting_refill","fallback_active","retry_fallback","waiting_prefetch","response","request","tl_a_fire","tl_d_fire","tl_a_blocked"};
 uint64_t events[16][3]={},states[8][5]={},sources[256]={},latencyCount[3]={},latencySum[3]={},latencyMax[3]={},latencyHist[3][65]={};
 uint64_t cycle=0,start=0,orphanReplies=0; unsigned kind=0; bool pending=false;
 void sample(SBoardSocGsim &d) {
  const auto bits=d.get_perfCacheEvents(); const bool empty=!d.get_io$$headProfile$$valid();
  const bool zero=!(d.get_io$$commit0()||d.get_io$$commit1());
  const bool physicalWait=(d.get_perfEvents()>>38)&1;
  for(unsigned i=0;i<16;++i)if((bits>>i)&1){++events[i][0];events[i][1]+=empty;events[i][2]+=zero;}
  const auto state=d.get_perfCacheState();++states[state][0];states[state][1]+=empty;states[state][2]+=zero;states[state][3]+=physicalWait;states[state][4]+=physicalWait&&empty;
  if((bits>>13)&1)++sources[d.get_perfCacheGetSource()];
  if((bits>>11)&1){if(pending){auto n=cycle-start;++latencyCount[kind];latencySum[kind]+=n;latencyMax[kind]=std::max(latencyMax[kind],n);++latencyHist[kind][std::min(uint64_t(64),n)];pending=false;}else ++orphanReplies;}
  unsigned accepted=(bits&1)+((bits>>1)&1)+((bits>>2)&1);
  if(accepted!=unsigned((bits>>12)&1))throw std::runtime_error("instruction-cache accepted class partition mismatch");
  if(accepted){if(pending)throw std::runtime_error("instruction-cache unowned second request");pending=true;start=cycle;kind=(bits&1)?0:((bits&2)?1:2);}
  ++cycle;
 }
 void report(const char *name){
  for(unsigned i=0;i<16;++i)std::cout<<"ICACHE_EVENT name="<<name<<" event="<<names[i]<<" cycles="<<events[i][0]<<" head_empty="<<events[i][1]<<" zero_commit="<<events[i][2]<<"\n";
  for(unsigned i=0;i<8;++i)std::cout<<"ICACHE_STATE name="<<name<<" state="<<i<<" cycles="<<states[i][0]<<" head_empty="<<states[i][1]<<" zero_commit="<<states[i][2]<<" physical_wait_no_reply="<<states[i][3]<<" physical_wait_no_reply_head_empty="<<states[i][4]<<"\n";
  for(unsigned i=0;i<256;++i)if(sources[i])std::cout<<"ICACHE_TL_SOURCE name="<<name<<" source="<<i<<" count="<<sources[i]<<"\n";
  for(unsigned i=0;i<3;++i){std::cout<<"ICACHE_LATENCY name="<<name<<" class="<<i<<" transactions="<<latencyCount[i]<<" cycles="<<latencySum[i]<<" maximum="<<latencyMax[i]<<"\n";for(unsigned n=0;n<=64;++n)if(latencyHist[i][n])std::cout<<"ICACHE_LATENCY_BIN name="<<name<<" class="<<i<<" cycles="<<n<<" count="<<latencyHist[i][n]<<"\n";}
  std::cout<<"ICACHE_BOUNDARY name="<<name<<" orphan_replies="<<orphanReplies<<" request_pending="<<pending<<"\n";
 }
};

struct FrontendCounts {
 uint64_t events[42][3]={}, occupancy[5]={}, supply[3]={}, capture[3]={}, rename[3]={}, phase[6][3]={};
 uint64_t getSize[8]={}; std::map<uint64_t,uint64_t> getLines;
 uint64_t discarded=0,cycles=0, correctionCaptureSum=0,correctionRenameSum=0,correctionRetireSum=0,correctionCaptureN=0,correctionRenameN=0,correctionRetireN=0,correctionSuperseded=0;
 int64_t correctionAt=-1; bool capturePending=false,renamePending=false,retirePending=false;
 void sample(SBoardSocGsim &d) {
  bool empty=!d.get_io$$headProfile$$valid(), zero=!(d.get_io$$commit0()||d.get_io$$commit1());
  auto bits=d.get_perfEvents();
  if((bits>>32)&1){++getSize[d.get_perfFetchGetSize()];++getLines[d.get_perfFetchGetAddress() & ~uint64_t(63)];}
  for(unsigned i=0;i<42;++i)if((bits>>i)&1){++events[i][0];events[i][1]+=empty;events[i][2]+=zero;}
  ++occupancy[d.get_perfOccupancy()];++supply[d.get_perfSupply()];++capture[d.get_perfCapture()];++rename[d.get_perfRename()];discarded+=d.get_perfDiscard();
  auto p=d.get_perfTranslationPhase();++phase[p][0];phase[p][1]+=empty;phase[p][2]+=zero;
  if((bits>>1)&1){correctionSuperseded+=capturePending||renamePending||retirePending;correctionAt=cycles;capturePending=renamePending=retirePending=true;}
  if(capturePending&&d.get_perfCapture()){correctionCaptureSum+=cycles-correctionAt;++correctionCaptureN;capturePending=false;}
  if(renamePending&&d.get_perfRename()&&cycles>uint64_t(correctionAt)){correctionRenameSum+=cycles-correctionAt;++correctionRenameN;renamePending=false;}
  if(retirePending&&!zero&&cycles>uint64_t(correctionAt)){correctionRetireSum+=cycles-correctionAt;++correctionRetireN;retirePending=false;}
  ++cycles;
 }
 void report(const char *name){
  std::cout<<"FRONTEND_HIST name="<<name<<" cycles="<<cycles<<" discarded="<<discarded;
  for(unsigned i=0;i<5;++i)std::cout<<" occupancy_"<<i<<"="<<occupancy[i];
  for(unsigned i=0;i<3;++i)std::cout<<" supply_"<<i<<"="<<supply[i]<<" capture_"<<i<<"="<<capture[i]<<" rename_"<<i<<"="<<rename[i];
  std::cout<<"\n";
  for(unsigned i=0;i<42;++i)std::cout<<"FRONTEND_EVENT name="<<name<<" event="<<frontendNames[i]<<" cycles="<<events[i][0]<<" head_empty="<<events[i][1]<<" zero_commit="<<events[i][2]<<"\n";
  for(unsigned i=0;i<6;++i)std::cout<<"FRONTEND_PHASE name="<<name<<" phase="<<i<<" cycles="<<phase[i][0]<<" head_empty="<<phase[i][1]<<" zero_commit="<<phase[i][2]<<"\n";
  for(unsigned i=0;i<8;++i)std::cout<<"FRONTEND_GET_SIZE name="<<name<<" size="<<i<<" count="<<getSize[i]<<"\n";
  for(auto [line,n]:getLines)std::cout<<"FRONTEND_GET_LINE name="<<name<<" address="<<line<<" count="<<n<<"\n";
  std::cout<<"FRONTEND_CORRECTION name="<<name<<" capture_latency_sum="<<correctionCaptureSum<<" capture_n="<<correctionCaptureN<<" rename_latency_sum="<<correctionRenameSum<<" rename_n="<<correctionRenameN<<" next_retire_latency_sum="<<correctionRetireSum<<" next_retire_n="<<correctionRetireN<<" superseded="<<correctionSuperseded<<"\n";
 }
};
// Exclusive observed zero-commit states, not an additive causal CPI model.
struct BackendCounts {
 uint64_t zero[6]={},executing[5]={},requestNotSelected=0,selectedRequestCause[8]={},structuralMemory[3]={};
 void sample(SBoardSocGsim &d){
  if(d.get_io$$commit0()||d.get_io$$commit1())return;
  if((d.get_perfEvents()>>3)&1){++zero[0];return;}
  if(!d.get_io$$headProfile$$valid()){++zero[1];return;}
  if(d.get_io$$headProfile$$done()){++zero[2];return;}
  if(d.get_io$$headProfile$$queued()){
   if(!d.get_io$$headProfile$$operandsReady()){++zero[3];return;}
   ++zero[4];
   if(d.get_io$$headProfile$$memory())++structuralMemory[d.get_io$$headProfile$$memoryStarting()?0:(!d.get_io$$headProfile$$memorySlotAvailable()?1:2)];
   return;
  }
  ++zero[5];
  if(!d.get_io$$headProfile$$memory()){++executing[0];return;}
  unsigned phase=d.get_io$$headProfile$$memoryPhase();
  if(phase>3)throw std::runtime_error("head memory phase out of range");
  ++executing[phase+1];
  if(phase==1){if(!d.get_io$$headProfile$$memoryRequestSelected())++requestNotSelected;else ++selectedRequestCause[d.get_io$$headProfile$$memoryRequestStallCause()];}
 }
 void report(const char *name){
  static const char *labels[6]={"recovery","empty","done","dependency","structural","executing"};
  for(unsigned i=0;i<6;++i)std::cout<<"BACKEND_ZERO_COMMIT name="<<name<<" state="<<labels[i]<<" cycles="<<zero[i]<<"\n";
  for(unsigned i=0;i<5;++i)std::cout<<"BACKEND_EXECUTING name="<<name<<" class="<<i<<" cycles="<<executing[i]<<"\n";
  std::cout<<"BACKEND_REQUEST name="<<name<<" not_selected="<<requestNotSelected;
  for(unsigned i=0;i<8;++i)std::cout<<" raw_dequeue_cause_when_lsu_selected_"<<i<<"="<<selectedRequestCause[i];
  for(unsigned i=0;i<3;++i)std::cout<<" structural_memory_"<<i<<"="<<structuralMemory[i];std::cout<<"\n";
 }
};

struct FrontendObserver: PerfObserver {
 FrontendCounts allFrontend,roiFrontend;
 CacheCounts allCache,roiCache;
 BackendCounts allBackend,roiBackend;
 std::vector<uint64_t> retiredPcs; bool pcActive=false,pcFinished=false;
 void sampleRetiredPc(SBoardSocGsim &d){
  if(!startPc||!endPc)return;
  for(unsigned lane=0;lane<2;++lane){
   bool valid=lane?d.get_io$$commit1():d.get_io$$commit0();
   uint64_t pc=lane?d.get_io$$commit1Pc():d.get_io$$commit0Pc();
   if(!valid)continue;
   if(pc==startPc&&!pcFinished)pcActive=true;
   if(pcActive)retiredPcs.push_back(pc);
   if(pc==endPc&&pcActive){pcActive=false;pcFinished=true;}
  }
 }
 void reportRetiredPc(){
  if(!pcFinished)return;
  if(const char *path=std::getenv("FRONTEND_RETIRE_TRACE")){
   std::ofstream file(path,std::ios::binary);if(!file)throw std::runtime_error("cannot create retired PC trace");
   for(auto pc:retiredPcs)for(unsigned shift=0;shift<64;shift+=8)file.put(char((pc>>shift)&255));
   file.close();if(!file)throw std::runtime_error("cannot finish retired PC trace");
  }
  std::cout<<"RETIRE_PC_STREAM count="<<retiredPcs.size()<<" completed="<<pcFinished<<"\n";
 }
 static void sample(SBoardSocGsim &d,void *p){auto &o=*static_cast<FrontendObserver*>(p);o.allFrontend.sample(d);o.allCache.sample(d);o.allBackend.sample(d);o.sampleRetiredPc(d);bool previouslyActive=o.active;PerfObserver::sample(d,static_cast<PerfObserver*>(&o));if(previouslyActive||o.active){o.roiFrontend.sample(d);o.roiCache.sample(d);o.roiBackend.sample(d);}}
 void report(){reportRetiredPc();PerfObserver::report();allFrontend.report("whole_run");allCache.report("whole_run");allBackend.report("whole_run");if(finished){roiFrontend.report("coremark_roi");roiCache.report("coremark_roi");roiBackend.report("coremark_roi");}}
};
