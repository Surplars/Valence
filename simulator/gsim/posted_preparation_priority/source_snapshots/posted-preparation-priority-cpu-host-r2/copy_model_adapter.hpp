#pragma once
#include "copy_eviction.hpp"
#include "copy_adapter_logic.hpp"
namespace pfcopy {
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
  const bool responseValid=d.board$platform$privateCache$engine$_io_response_valid_T_1;
  unsigned m=0;bool normalRefill=false,postedInstall=false;unsigned postedIndex=0;
  if(responseValid){
#if POSTED_STORE_ON
   const auto tag=d.board$platform$privateCache$engine$io$$response$$bits$$tag;
   m=d.board$platform$privateCache$fillMshr;require(m<2,"copy actual fill MSHR range");
   const bool posted=d.board$platform$privateCache$postedMshr[m];
   const unsigned kind=posted?2:d.board$platform$privateCache$prefetchOwner[m]?1:0;
   verifyAcquireTag(tag,m,kind,posted?d.board$platform$privateCache$postedContext$$owner$$slot[m]:0,posted?d.board$platform$privateCache$postedContext$$owner$$generation[m]:0);
#else
   m=unsigned(d.board$platform$privateCache$engine$io$$response$$bits$$tag);require(m<2,"copy refill tag range");
#endif
  }
#if POSTED_STORE_ON
  normalRefill=d.board$platform$privateCache$refill;
  postedInstall=d.board$platform$privateCache$postedInstall;
  if(postedInstall)postedIndex=d.board$platform$privateCache$postedInstallIndex;
  require(!normalRefill||(responseValid&&!d.board$platform$privateCache$postedMshr[m]),"ordinary refill must actually fire outside posted class");
#else
  normalRefill=responseValid; // OFF source pins engine.response.ready=true.
#endif
  const bool responseError=normalRefill&&d.board$platform$privateCache$engine$io$$response$$bits$$error;
  const bool pf=normalRefill&&d.board$platform$privateCache$prefetchOwner[m];
  const bool storePf=pf&&d.board$platform$privateCache$storePrefetchOwner[m];
  const auto classified=classifyInstall(responseValid,normalRefill,postedInstall,responseError,pf,storePf);
  require(classified.residentInstall==bool(d.get_lineage$$lineWriteValid()),"COPY resident generation must follow actual SRAM installLine");
  e.successfulRefill=classified.residentInstall;e.install=classified.storePfInstall;e.error=classified.storePfError;
  if(normalRefill){e.fillMshr=m;e.installAddress=d.board$platform$privateCache$pending$$address[m]&~63ULL;e.installIndex=d.board$platform$privateCache$pendingIndex[m];}
  if(postedInstall){e.installIndex=postedIndex;e.installAddress=d.get_lineage$$owner$$installedEvent$$context$$lineAddress();}
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
}
