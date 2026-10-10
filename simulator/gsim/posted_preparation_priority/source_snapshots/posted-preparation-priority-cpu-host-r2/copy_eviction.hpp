#pragma once
#include <array>
#include <cstdint>
#include <ostream>
#include <stdexcept>
#include <unordered_map>
#include <vector>
namespace pfcopy {
inline void require(bool b,const char* s){if(!b)throw std::runtime_error(s);}
struct Event {
 uint64_t cycle=0,installAddress=0,victimAddress=0,demandAddress=0,cpuAddress=0;
 unsigned installIndex=0,victimIndex=0;bool active=false,install=false,evict=false,evictForDemand=false,demandWrite=false;
 bool cpu=false,cpuWrite=false,cpuHit=false;
 bool allocate=false,error=false,probe=false,probeHit=false,successfulRefill=false;unsigned probeIndex=0;uint64_t probeAddress=0;unsigned allocMshr=0,fillMshr=0,allocIndex=0;uint64_t allocAddress=0;
};
struct Record {uint64_t line=0,installed=0,evicted=0,demand=0,allocated=0,storeCycle=0;unsigned slot=0;bool active=false,live=true,used=false,paired=false,followed=false;};
struct Ledger {
 struct Owner {bool live=false;uint64_t address=0,cycle=0;unsigned index=0;};
 std::array<Owner,2> owners{};uint64_t allocations=0,errors=0,probes=0;
 uint64_t a,b,bytes;std::vector<Record> records;std::array<size_t,512> slots{};
 std::unordered_map<uint64_t,size_t> lastEvicted,liveLines;uint64_t installs=0,evictions=0,paired=0,followingMiss=0,followingHit=0,usedBeforeEviction=0;
 std::vector<Record> witnesses;
 Ledger(uint64_t ap,uint64_t bp,uint64_t n):a(ap),b(bp),bytes(n){slots.fill(SIZE_MAX);}
 bool inB(uint64_t p)const{return p>=b&&p<b+bytes;}
 void accept(const Event& e){
  require(e.installIndex<512&&e.victimIndex<512&&e.allocIndex<512,"copy ledger cache slot range");
  require(e.allocMshr<2&&e.fillMshr<2,"copy ledger MSHR range");
  if(e.active){errors+=e.error;probes+=e.probe;}
  require(e.probeIndex<512,"copy probe slot range");
  auto clearSlot=[&](unsigned slot){const auto n=slots[slot];if(n!=SIZE_MAX){auto& r=records.at(n);r.live=false;auto it=liveLines.find(r.line);if(it!=liveLines.end()&&it->second==n)liveLines.erase(it);slots[slot]=SIZE_MAX;}};
  // Probes invalidate only the matching resident generation, never count as
  // voluntary evictions. Any successful refill starts a new slot generation.
  if(e.probe&&e.probeHit){const auto n=slots[e.probeIndex];if(n!=SIZE_MAX){require(records.at(n).line==(e.probeAddress&~63ULL),"probe PA differs from tracked slot owner");clearSlot(e.probeIndex);}}
  if(e.successfulRefill||e.install)clearSlot(e.installIndex);
  uint64_t allocationCycle=0;
  if(e.install||e.error){auto& q=owners[e.fillMshr];require(q.live&&q.address==e.installAddress&&q.index==e.installIndex,"copy fill lost exact PF allocation");allocationCycle=q.cycle;q.live=false;}
  if(e.allocate){auto& q=owners[e.allocMshr];require(!q.live&&!(e.allocAddress&63),"copy PF allocation reuse/alignment");q={true,e.allocAddress,e.cycle,e.allocIndex};if(e.active)++allocations;}
  if(e.cpu&&inB(e.cpuAddress)){
   const auto line=e.cpuAddress&~63ULL;
   if(e.cpuHit){auto live=liveLines.find(line);if(live!=liveLines.end())records.at(live->second).used=true;}
   auto it=lastEvicted.find(line);
   if(e.active&&e.cpuWrite&&it!=lastEvicted.end()){
    auto& r=records[it->second];
    if(r.active&&r.paired&&!r.followed){require(e.cycle>r.evicted,"copy store precedes victim eviction");r.followed=true;r.storeCycle=e.cycle;
     if(e.cpuHit)++followingHit;else ++followingMiss;if(witnesses.size()<8)witnesses.push_back(r);
    }
   }
  }
  if(e.evict){
   const auto n=slots[e.victimIndex];
   if(n!=SIZE_MAX){auto& r=records.at(n);
    if(r.live&&r.line==(e.victimAddress&~63ULL)){
     require(e.cycle>r.installed,"copy eviction precedes PF install");r.live=false;r.evicted=e.cycle;r.demand=e.demandAddress&~63ULL;
     r.paired=e.active&&r.active&&e.evictForDemand&&!e.demandWrite&&inB(r.line)&&r.demand==a+(r.line-b);
     if(e.active&&r.active){++evictions;usedBeforeEviction+=r.used;if(r.paired)++paired;}
     lastEvicted[r.line]=n;liveLines.erase(r.line);
    } else {r.live=false;liveLines.erase(r.line);}
    slots[e.victimIndex]=SIZE_MAX;
   }
  }
  if(e.install){
   require(!(e.installAddress&63),"copy PF install unaligned line");
   if(slots[e.installIndex]!=SIZE_MAX){auto& old=records.at(slots[e.installIndex]);old.live=false;liveLines.erase(old.line);}
   const auto n=records.size();Record r;r.line=e.installAddress;r.installed=e.cycle;r.allocated=allocationCycle;r.slot=e.installIndex;r.active=e.active;records.push_back(r);slots[e.installIndex]=n;liveLines[e.installAddress]=n;
   if(e.active)++installs;
  }
 }
 void print(std::ostream& o,unsigned index)const{
  o<<"COPY_PF_VICTIM index="<<index<<" store_pf_allocations="<<allocations<<" store_pf_errors="<<errors<<" actual_probes="<<probes<<" store_pf_installs="<<installs<<" observed_evictions="<<evictions<<" matching_A_demand="<<paired
   <<" subsequent_B_store_miss="<<followingMiss<<" subsequent_B_store_hit="<<followingHit<<" used_before_eviction="<<usedBeforeEviction<<"\n";
  for(const auto& r:witnesses)o<<"COPY_PF_WITNESS index="<<index<<" slot="<<r.slot<<" line="<<r.line<<" allocation_cycle="<<r.allocated<<" install_cycle="<<r.installed
   <<" victim_cycle="<<r.evicted<<" demand_line="<<r.demand<<" subsequent_store_cycle="<<r.storeCycle<<" used_before_eviction="<<r.used<<"\n";
 }
};
// Model-specific extraction is read-only. A pre-edge event is processed at the
// next call, only after the corresponding installed/invalidation registers match.
#ifdef PF_COPY_ACTUAL_MODEL
struct Observer {
 Ledger ledger;Event pending{};bool held=false;
 Observer(uint64_t a,uint64_t b,uint64_t n):ledger(a,b,n){}
 void sample(SBoardSocGsim& d,uint64_t cycle,bool activeOffer){
#if STORE_PF_ON
  if(held){require(cycle==pending.cycle+1,"copy observer skipped edge");
   if(pending.allocate)require(d.board$platform$privateCache$phase[pending.allocMshr]!=0&&d.board$platform$privateCache$prefetchOwner[pending.allocMshr]&&d.board$platform$privateCache$storePrefetchOwner[pending.allocMshr]&&d.board$platform$privateCache$pending$$address[pending.allocMshr]==pending.allocAddress&&d.board$platform$privateCache$pendingIndex[pending.allocMshr]==pending.allocIndex,"copy allocation lacks exact post-edge MSHR");
   if(pending.install)require(d.board$platform$privateCache$trackedValid&&d.board$platform$privateCache$trackedAddress==pending.installAddress&&d.board$platform$privateCache$trackedIndex==pending.installIndex&&d.board$platform$privateCache$valid[pending.installIndex]&&!d.board$platform$privateCache$dirty[pending.installIndex],"copy PF install lacks real post-edge state");
   if(pending.evict)require(d.board$platform$privateCache$evictionState==1&&d.board$platform$privateCache$evictionAddress==pending.victimAddress&&!d.board$platform$privateCache$valid[pending.victimIndex],"copy victim lacks real post-edge invalidation");
   ledger.accept(pending);
  }
  Event e;e.cycle=cycle;e.active=activeOffer;
  e.allocate=(d.get_dataPrefetchOriginEvents()>>3)&1;e.allocMshr=d.board$platform$privateCache$freeMshr;e.allocIndex=d.board$platform$privateCache$pfIndex;e.allocAddress=d.board$platform$privateCache$candidateAddress;
  e.probe=d.board$platform$privateCache$probeFire;e.probeHit=d.board$platform$privateCache$actualProbeHit;e.probeIndex=d.board$platform$privateCache$probeIndex;e.probeAddress=d.board$platform$privateCache$probeAddress$NEXT;
  const auto m=unsigned(d.board$platform$privateCache$engine$io$$response$$bits$$tag);require(m<2,"copy refill tag range");
  e.successfulRefill=d.board$platform$privateCache$engine$_io_response_valid_T_1&&!d.board$platform$privateCache$engine$io$$response$$bits$$error;
  e.fillMshr=m;e.error=d.board$platform$privateCache$engine$_io_response_valid_T_1&&d.board$platform$privateCache$engine$io$$response$$bits$$error&&d.board$platform$privateCache$prefetchOwner[m]&&d.board$platform$privateCache$storePrefetchOwner[m];
  e.install=d.board$platform$privateCache$engine$_io_response_valid_T_1&&!d.board$platform$privateCache$engine$io$$response$$bits$$error&&d.board$platform$privateCache$prefetchOwner[m]&&d.board$platform$privateCache$storePrefetchOwner[m];
  e.installAddress=d.board$platform$privateCache$pending$$address[m]&~63ULL;e.installIndex=d.board$platform$privateCache$pendingIndex[m];
  e.evict=d.board$platform$privateCache$startEviction;e.victimIndex=d.board$platform$privateCache$evictIndex;
  e.victimAddress=d.board$platform$privateCache$evictionAddress$NEXT;
  const auto v=unsigned(d.board$platform$privateCache$evictMshr);require(v<2,"copy eviction MSHR range");
  e.evictForDemand=d.board$platform$privateCache$evictFromMiss&&!d.board$platform$privateCache$prefetchOwner$NEXT[v];
  e.demandAddress=d.board$platform$privateCache$pending$$address$NEXT[v];e.demandWrite=d.board$platform$privateCache$pending$$write$NEXT[v];
  e.cpu=d.board$platform$privateCache$cpuFire&&d.board$platform$privateCache$ordinary;
  e.cpuAddress=d.get_dataPathRequest9Address();e.cpuWrite=d.get_dataPathRequest9Meta()&1;e.cpuHit=d.board$platform$privateCache$found;
  if(e.cpu)require((d.get_dataPathEvents()>>19)&1,"copy cache accept lacks same physical request fire");
  pending=e;held=!d.get_backendReset();
#else
  (void)d;(void)cycle;(void)activeOffer;
#endif
 }
 void finish(std::ostream& o,unsigned index)const{ledger.print(o,index);}
};
#endif
}
