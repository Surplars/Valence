#pragma once
#include <array>
#include <deque>
#include <map>
#include <optional>
#include <fstream>
#include <cstdlib>
#include <cstdint>
#include <compare>
#include <ostream>
#include <stdexcept>
#include <string>
namespace canonical_overlap {
inline void need(bool good,const char* why){if(!good)throw std::runtime_error(why);}
struct Token { uint64_t index=0,tag=0; auto operator<=>(const Token&)const=default; };
struct Request { bool valid=false,ready=false,write=false,atomic=false,virtualized=false,prechecked=false,uncached=false; uint64_t address=0,data=0,size=0,mask=0,epoch=0; bool fire()const{return valid&&ready;} };
struct Response { bool valid=false,ready=false,error=false,pageFault=false; bool fire()const{return valid&&ready;} };
struct Certificate { bool valid=false;Token token;uint64_t epoch=0,va=0,pa=0,size=0,mask=0; };
struct Slot { bool live=false,serial=false,acceptedKnown=false,accepted=false,storeClass=false,exempt=false,cancel=false; Token token;uint64_t phase=0;Response response; };
struct Sample {
 bool reset=false,enabled=false,stable=false,headValid=false,protectedValid=false,tracked=false,ownerLive=false,invalidate=false;
 uint64_t epoch=0;Token head,protectedToken;
 bool preparedValid=false,preparedAllowed=false,preparedMatches=false;Token prepared;uint64_t preparedEpoch=0,preparedVa=0,preparedPa=0,preparedSize=0;Certificate capture,record;std::array<Slot,4> slots{};
 bool startValid=false,startReady=false,startStore=false,startAtomic=false,startVirtual=false,startPrechecked=false,startForwarded=false;
 Token start;uint64_t startEpoch=0,startVa=0,startPa=0,startSize=0;
 bool requestOwnerValid=false;Token requestOwner;Request request,dequeue,upstream,checked,checkedDequeue,physical;
 bool direct=false,checkedFault=false,checkedPageFault=false,ownerPush=false,ownerFault=false;Response physicalResponse,upstreamResponse;
 bool cacheObserved=false,cacheBarrier=false,cacheFound=false,cacheReadHit=false,cacheWriteHit=false,cacheBarrierRequest=false,cachePosted=false;Request cache;Response cacheResponse;
 bool choiceValid=false,choiceStore=false,choiceAtomic=false,choicePrechecked=false,choiceIsHead=false;
 Token choice;bool blockedStore=false,physicalConflict=false,olderUncanonical=false,issueAvailable=false,noOtherSerial=false,olderSystem=false;
};
struct Op { bool known=false,store=false,prechecked=false,virtualized=false;Token token;uint64_t epoch=0,va=0,pa=0,size=0,mask=0;bool fault=false; };
inline uint64_t lanes(uint64_t pa,uint64_t size){need(size<=3,"canonical observer size");return (((uint64_t(1)<<(uint64_t(1)<<size))-1)<<(pa&7))&255;}
inline bool disjoint(uint64_t a,uint64_t am,uint64_t b,uint64_t bm){return (a>>3)!=(b>>3)||!(am&bm);}
inline bool same(const Request&a,const Request&b){return a.address==b.address&&a.data==b.data&&a.size==b.size&&a.mask==b.mask&&a.write==b.write&&a.atomic==b.atomic&&a.virtualized==b.virtualized&&a.prechecked==b.prechecked&&a.epoch==b.epoch;}
struct PreparedSnapshot { bool valid=false;Token token;uint64_t epoch=0,va=0,pa=0,size=0;bool allowed=false,matches=false;auto operator<=>(const PreparedSnapshot&)const=default; };
class Observer {
 std::deque<Op> requests,upstream,checked,responses;std::map<Token,Op> starts;
 struct Store { Certificate cert;uint64_t captureCycle=0;bool upstreamPending=false,physicalIssued=false,physicalResponded=false;unsigned hitClass=0;uint64_t cacheAccepted=0,barrierCycles=0;std::optional<uint64_t> barrierBegin,barrierEnd; };
 struct CacheOwner {Op op;uint64_t id=0;};std::deque<CacheOwner> cacheOwners;std::optional<CacheOwner> barrierOwner;uint64_t cacheSequence=0;std::map<Token,Token> parents;
 std::map<Token,Store> stores;std::optional<Token> responseVisible,usableRecord,previousChoice;std::optional<PreparedSnapshot> previousPrepared;std::ofstream log;bool opened=false,seen=false;uint64_t previous=0;
 static Op pop(std::deque<Op>&q,const char*m){need(!q.empty(),m);auto x=q.front();q.pop_front();return x;}
 void event(const char* kind,uint64_t cycle,const Op& op,const Sample&s,bool eligible=false){
  if(!log.is_open())return;
  log<<"{\"event\":\""<<kind<<"\",\"cycle\":"<<cycle<<",\"known\":"<<op.known;
  if(op.known)log<<",\"token_index\":"<<op.token.index<<",\"token_tag\":"<<op.token.tag<<",\"epoch\":"<<op.epoch;
  log<<",\"prepared_valid\":"<<s.preparedValid<<",\"prepared_matches_choice\":"<<s.preparedMatches<<",\"choice_valid\":"<<s.choiceValid;
  if(s.choiceValid)log<<",\"choice_index\":"<<s.choice.index<<",\"choice_tag\":"<<s.choice.tag;
  log<<",\"va\":"<<op.va<<",\"size\":"<<op.size<<",\"pa\":"<<op.pa<<",\"mask\":"<<op.mask<<",\"store\":"<<op.store<<",\"prechecked\":"<<op.prechecked<<",\"eligible_overlap\":"<<eligible;
  if(eligible) { auto t=stores.find(s.record.token);need(t!=stores.end(),"overlap certificate missing");log<<",\"store_index\":"<<t->first.index<<",\"store_tag\":"<<t->first.tag<<",\"store_epoch\":"<<t->second.cert.epoch<<",\"store_pa\":"<<t->second.cert.pa<<",\"store_mask\":"<<t->second.cert.mask<<",\"store_physical_issued\":"<<t->second.physicalIssued<<",\"store_real_response_pending\":"<<!t->second.physicalResponded;
   for(unsigned i=0;i<s.slots.size();++i)if(s.slots[i].live&&s.slots[i].token==t->first){const auto&z=s.slots[i];log<<",\"store_slot\":"<<i<<",\"store_live\":"<<z.live<<",\"store_serial\":"<<z.serial<<",\"store_request_accepted_known\":"<<z.acceptedKnown<<",\"store_request_accepted\":"<<z.accepted<<",\"store_class\":"<<z.storeClass;}
   log<<",\"head_index\":"<<s.head.index<<",\"head_tag\":"<<s.head.tag<<",\"protected_index\":"<<s.protectedToken.index<<",\"protected_tag\":"<<s.protectedToken.tag<<",\"current_epoch\":"<<s.epoch<<",\"context_stable\":"<<s.stable;
  }
  auto parent=parents.find(op.token);
  if(op.known&&!op.store&&parent!=parents.end()){auto it=stores.find(parent->second);need(it!=stores.end(),"parent store missing");const auto&t=it->second;unsigned relation=!t.physicalIssued?0:t.hitClass==1?1:t.hitClass==2?(t.barrierEnd?3:2):4;
   log<<",\"parent_store_index\":"<<it->first.index<<",\"parent_store_tag\":"<<it->first.tag<<",\"parent_store_hit_class\":"<<t.hitClass<<",\"barrier_relation\":"<<relation;
   if(t.physicalIssued)log<<",\"parent_cache_accept_cycle\":"<<t.cacheAccepted;
   if(t.barrierBegin)log<<",\"parent_barrier_begin\":"<<*t.barrierBegin;
   if(t.barrierEnd)log<<",\"parent_barrier_end\":"<<*t.barrierEnd;
  }
  log<<",\"cache_barrier\":"<<s.cacheBarrier;
  if(s.cache.valid)log<<",\"cache_request_found\":"<<s.cacheFound<<",\"cache_read_hit\":"<<s.cacheReadHit<<",\"cache_write_hit\":"<<s.cacheWriteHit<<",\"cache_barrier_request\":"<<s.cacheBarrierRequest;
  log<<"}\n";
 }
 bool overlap(const Op&o,const Sample&s,uint64_t cycle) {
  if(!o.known||o.store||!o.prechecked||!s.record.valid)return false;
  const auto &c=s.record;auto it=stores.find(c.token);need(it!=stores.end(),"usable certificate without observed checked capture");const auto&t=it->second;
  need(t.captureCycle<cycle&&t.cert.epoch==c.epoch&&t.cert.pa==c.pa&&t.cert.mask==c.mask&&t.cert.va==c.va&&t.cert.size==c.size,"record differs from registered capture");
  bool exact=false;for(const auto&slot:s.slots)if(slot.live&&slot.token==c.token){need(!exact,"duplicate canonical slot owner");exact=slot.serial&&slot.acceptedKnown&&slot.accepted&&slot.storeClass;}
  return exact&&s.headValid&&s.protectedValid&&s.head==c.token&&s.protectedToken==c.token&&s.stable&&o.epoch==c.epoch&&c.epoch==s.epoch&&o.token!=c.token&&t.upstreamPending&&!t.physicalResponded&&(!responseVisible||*responseVisible!=c.token)&&disjoint(o.pa,o.mask,c.pa,c.mask);
 }
 public:
 std::map<std::pair<unsigned,unsigned>,uint64_t> upstreamOccupancy,physicalOccupancy;
 uint64_t storeCacheHits=0,storeCacheMisses=0,unknownCacheOwners=0,cacheOverlap=0;std::array<uint64_t,4> barrierBins{};std::array<uint64_t,5> loadCacheRelation{};
 uint64_t samples=0,captures=0,startsOverlap=0,upstreamOverlap=0,physicalOverlap=0,unknownUpstream=0;
 // Exclusive ROI partitions. Each sample belongs to exactly one occupancy and one selected-load stall bin.
 std::array<uint64_t,5> occupancy{};std::array<uint64_t,9> stalls{};uint64_t roiSamples=0;
 void sample(const Sample&s,uint64_t cycle,bool roi){
  if(!opened){const char*p=std::getenv("CANONICAL_OVERLAP_TRACE");need(p&&*p,"canonical trace path required");log.open(p);need(bool(log),"cannot create canonical trace");opened=true;}
  need(!seen||cycle==previous+1,"canonical observer omitted/duplicate edge");seen=true;previous=cycle;++samples;
  if(s.reset){requests.clear();upstream.clear();checked.clear();responses.clear();starts.clear();stores.clear();cacheOwners.clear();barrierOwner.reset();parents.clear();return;}
  if(roi){unsigned uk=0,uu=0,pk=0,pu=0;auto up=[&](const auto&q){for(const auto&o:q)(o.known?uk:uu)++;};up(upstream);up(checked);up(responses);for(const auto&o:responses)if(!o.fault)(o.known?pk:pu)++;++upstreamOccupancy[{uk,uu}];++physicalOccupancy[{pk,pu}];}
  if(s.cacheObserved){need(s.cacheBarrier==barrierOwner.has_value(),"cache barrier owner/state mismatch");if(s.cacheBarrier&&barrierOwner->op.known&&barrierOwner->op.store&&barrierOwner->op.virtualized)++stores[barrierOwner->op.token].barrierCycles;
   if(roi){unsigned k=!s.cacheBarrier?0:!barrierOwner->op.known?3:barrierOwner->op.store&&barrierOwner->op.virtualized?1:2;++barrierBins[k];}
  }
  responseVisible.reset();if(!responses.empty()&&responses.front().known&&(s.physicalResponse.valid||s.upstreamResponse.valid))responseVisible=responses.front().token;
  if(s.record.valid){if(!usableRecord||*usableRecord!=s.record.token){Op o;o.known=true;o.store=true;o.token=s.record.token;o.epoch=s.record.epoch;o.va=s.record.va;o.pa=s.record.pa;o.size=s.record.size;o.mask=s.record.mask;event("record_usable",cycle,o,s);usableRecord=o.token;}}else usableRecord.reset();
  PreparedSnapshot prep{s.preparedValid,s.prepared,s.preparedEpoch,s.preparedVa,s.preparedPa,s.preparedSize,s.preparedAllowed,s.preparedMatches};
  if(!previousPrepared||*previousPrepared!=prep){Op o;o.known=s.preparedValid;if(o.known){o.token=s.prepared;o.epoch=s.preparedEpoch;o.va=s.preparedVa;o.pa=s.preparedPa;o.size=s.preparedSize;o.mask=lanes(o.pa,o.size);o.prechecked=s.preparedAllowed;}event("load_prepared",cycle,o,s);previousPrepared=prep;}
  if(s.choiceValid){if(!previousChoice||*previousChoice!=s.choice){Op o;o.known=true;o.token=s.choice;o.store=s.choiceStore;o.prechecked=s.choicePrechecked;o.epoch=s.epoch;event("choice_selected",cycle,o,s);previousChoice=o.token;}}else previousChoice.reset();
  if(roi){++roiSamples;unsigned n=0;for(auto&x:s.slots)n+=x.live;need(n<occupancy.size(),"canonical occupancy");++occupancy[n];
   unsigned k=0;if(s.choiceValid&&!s.choiceStore&&!s.choiceAtomic&&!s.choiceIsHead){
    if(s.startValid&&s.startReady)k=1;else if(!s.choicePrechecked)k=2;else if(s.physicalConflict)k=3;else if(s.olderUncanonical)k=4;else if(!s.noOtherSerial)k=5;else if(!s.issueAvailable)k=6;else if(s.olderSystem)k=7;else k=8;
   }++stalls[k];
  }
  if(s.startValid&&s.startReady){Op o;o.known=true;o.token=s.start;o.store=s.startStore;o.prechecked=s.startPrechecked;o.virtualized=s.startVirtual;o.epoch=s.startEpoch;o.va=s.startVa;o.pa=s.startPrechecked?s.startPa:s.startVa;o.size=s.startSize;o.mask=lanes(o.pa,o.size);starts[o.token]=o;
   const bool yes=overlap(o,s,cycle);if(yes)parents[o.token]=s.record.token;startsOverlap+=yes;event("lsu_start",cycle,o,s,yes);}
  // Non-flow backend FIFO: old dequeue precedes new enqueue, even on replacement.
  std::optional<Op> dequeued;if(s.dequeue.fire())dequeued=pop(requests,"backend request FIFO owner underflow");
  if(s.request.fire()){need(s.requestOwnerValid,"LSU request fire lacks owner");auto it=starts.find(s.requestOwner);need(it!=starts.end(),"request lacks accepted start");auto o=it->second;o.pa=s.request.address;o.mask=s.request.mask;o.epoch=s.request.epoch;requests.push_back(o);}
  if(s.upstream.fire()){Op o;if(s.direct){need(dequeued.has_value()&&same(s.dequeue,s.upstream),"direct upstream lacks exact FIFO request");o=*dequeued;}else ++unknownUpstream;
   o.pa=s.upstream.address;o.mask=s.upstream.mask;o.epoch=s.upstream.epoch;o.size=s.upstream.size;o.store=s.upstream.write;o.prechecked=s.upstream.prechecked;
   if(!o.known){o.va=s.upstream.address;o.virtualized=s.upstream.virtualized;}
   if(o.known){const bool yes=overlap(o,s,cycle);upstreamOverlap+=yes;event("upstream_accept",cycle,o,s,yes);}
   else event("upstream_accept",cycle,o,s);upstream.push_back(o);
   if(o.known&&o.store&&o.virtualized)stores[o.token].upstreamPending=true;
  }
  // Original adapter is ordered. Its registered checked FIFO never bypasses this sample edge.
  if(s.upstreamResponse.fire()){auto o=pop(responses,"adapter response owner underflow");need(s.physicalResponse.fire()==!o.fault,"real response/fault owner conservation");
   if(o.known&&o.store&&o.virtualized){auto it=stores.find(o.token);need(it!=stores.end(),"real store response owner absent");it->second.upstreamPending=false;it->second.physicalResponded=!o.fault;}event("real_response",cycle,o,s);}
  if(s.cacheObserved&&s.cacheResponse.fire()){need(!cacheOwners.empty(),"cache response owner underflow");auto old=cacheOwners.front();cacheOwners.pop_front();if(barrierOwner&&barrierOwner->id==old.id){if(old.op.known&&old.op.store&&old.op.virtualized)stores[old.op.token].barrierEnd=cycle;event("cache_barrier_end",cycle,old.op,s);barrierOwner.reset();}event("cache_response",cycle,old.op,s);}
  need(!s.cacheObserved||!s.cache.fire()||s.physical.fire(),"cache request lacks same-edge adapter physical acceptance");
  need(s.ownerPush==s.checkedDequeue.fire(),"checked dequeue and owner enqueue differ");
  if(s.ownerPush){auto o=pop(checked,"checked request owner underflow");o.fault=s.ownerFault;need(s.physical.fire()==!o.fault,"physical acceptance/fault owner conservation");
   if(!o.fault){need(o.pa==s.physical.address&&o.mask==s.physical.mask&&o.store==s.physical.write,"physical request differs from checked owner");if(s.cacheObserved&&s.cache.fire()){
     need(same(s.cache,s.physical),"cache request differs from exact physical owner");need(!s.cacheBarrier,"cache accepted across live miss barrier");
     if(o.known&&o.store&&o.virtualized){auto&t=stores[o.token];t.physicalIssued=true;t.cacheAccepted=cycle;t.hitClass=s.cacheWriteHit?1:(!s.cacheFound&&s.cacheBarrierRequest?2:0);if(roi){storeCacheHits+=t.hitClass==1;storeCacheMisses+=t.hitClass==2;}}
     CacheOwner co{o,++cacheSequence};cacheOwners.push_back(co);unknownCacheOwners+=!o.known;
     if(s.cacheBarrierRequest&&!s.cachePosted){need(!barrierOwner,"overlapping cache barriers");barrierOwner=co;if(o.known&&o.store&&o.virtualized)stores[o.token].barrierBegin=cycle;event("cache_barrier_begin",cycle,o,s);}
     const bool cacheYes=overlap(o,s,cycle);cacheOverlap+=cacheYes;event("cache_accept",cycle,o,s,cacheYes);
     auto parent=parents.find(o.token);if(o.known&&!o.store&&parent!=parents.end()){const auto&t=stores.at(parent->second);unsigned rel=!t.physicalIssued?0:t.hitClass==1?1:t.hitClass==2?(t.barrierEnd?3:2):4;++loadCacheRelation[rel];}
    }else if(s.cacheObserved&&o.known&&((o.store&&o.virtualized)||o.prechecked)&&o.pa>=0x80200000ULL&&o.pa+ (1ULL<<o.size)<=0x100200000ULL)need(false,"known RAM physical owner lacks cache acceptance");
    const bool yes=overlap(o,s,cycle);physicalOverlap+=yes;event("physical_accept",cycle,o,s,yes);if(o.known&&o.store&&o.virtualized)stores[o.token].physicalIssued=true;}responses.push_back(o);}
  if(s.checked.fire()){auto o=pop(upstream,"checked acceptance lacks upstream owner");o.pa=s.checked.address;o.mask=s.checked.mask;o.size=s.checked.size;o.fault=s.checkedFault;checked.push_back(o);}
  if(s.capture.valid){need(s.enabled&&s.checked.fire()&&!s.checkedFault&&s.checked.write&&!s.checked.atomic,"certificate lacks actual checked store acceptance");need(!checked.empty(),"certificate owner missing");auto&o=checked.back();const auto&c=s.capture;need(o.known&&o.token==c.token&&o.va==c.va&&o.pa==c.pa&&o.mask==c.mask&&o.size==c.size,"certificate owner/address mismatch");auto&t=stores[c.token];need(t.upstreamPending,"certificate store response already consumed");t.cert=c;t.captureCycle=cycle;o.epoch=c.epoch;++captures;event("checked_certificate",cycle,o,s);}
  if(!s.enabled)need(!s.capture.valid&&!s.record.valid&&!s.tracked,"OFF exposes live canonical proof");
 }
 void finish(std::ostream&out){need(requests.empty()&&upstream.empty()&&checked.empty()&&responses.empty()&&cacheOwners.empty()&&!barrierOwner,"canonical observer owner queues did not drain");uint64_t a=0,b=0;for(auto x:occupancy)a+=x;for(auto x:stalls)b+=x;need(a==roiSamples&&b==roiSamples,"exclusive canonical bins do not conserve ROI");log.flush();need(bool(log),"canonical sidecar write failed");
  out<<"CANONICAL_OVERLAP {\"samples\":"<<samples<<",\"roi_samples\":"<<roiSamples<<",\"certificate_captures\":"<<captures<<",\"lsu_start_overlap\":"<<startsOverlap<<",\"upstream_overlap\":"<<upstreamOverlap<<",\"physical_overlap\":"<<physicalOverlap<<",\"unknown_upstream\":"<<unknownUpstream<<",\"final_owner_queues\":0,\"occupancy\":[";
  for(unsigned i=0;i<occupancy.size();++i){if(i)out<<',';out<<occupancy[i];}out<<"],\"stalls\":[";for(unsigned i=0;i<stalls.size();++i){if(i)out<<',';out<<stalls[i];}out<<"],\"store_cache_hit_samples\":"<<storeCacheHits<<",\"store_cache_miss_samples\":"<<storeCacheMisses<<",\"cache_overlap\":"<<cacheOverlap<<",\"unknown_cache_owners\":"<<unknownCacheOwners<<",\"barrier_bins\":[";for(unsigned i=0;i<barrierBins.size();++i){if(i)out<<',';out<<barrierBins[i];}out<<"],\"load_cache_barrier_relation\":[";for(unsigned i=0;i<loadCacheRelation.size();++i){if(i)out<<',';out<<loadCacheRelation[i];}out<<"],\"accepted_upstream_occupancy\":[";bool first=true;for(const auto&[key,n]:upstreamOccupancy){if(!first)out<<',';first=false;out<<"{\"known\":"<<key.first<<",\"unknown\":"<<key.second<<",\"cycles\":"<<n<<'}';}out<<"],\"accepted_physical_occupancy\":[";first=true;for(const auto&[key,n]:physicalOccupancy){if(!first)out<<',';first=false;out<<"{\"known\":"<<key.first<<",\"unknown\":"<<key.second<<",\"cycles\":"<<n<<'}';}out<<"]}\n";
 }
};
}
