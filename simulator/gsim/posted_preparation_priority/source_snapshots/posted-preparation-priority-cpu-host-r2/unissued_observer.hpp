#pragma once
#include "canonical_observer.hpp"
#include "capacity.hpp"
#include <sstream>
#include <set>
#include <vector>
namespace unissued {
using canonical_overlap::Token;using canonical_overlap::need;
struct Owner {
 bool live=false,pending=false,memoryLive=false,memory=false,store=false,atomic=false,system=false,writesRd=false,moveAlias=false;
 Token token;uint64_t age=0,pc=0,destination=0;
 bool sourcesKnown=false,ready1=false,ready2=false,prfReady1=false,prfReady2=false,usePc=false,useImmediate=false,killed=false;
 uint64_t source1=0,source2=0,size=0,va=0;bool addressKnown=false,prepared=false,busy=false,safeRaw=false,memoryCanonical=false;
};
struct Capture {bool valid=false;Token token;uint64_t va=0;bool dataReady=false;};
struct Sample {uint64_t head=0,robCount=0,satp=0,privilege=0;std::array<Owner,capacity::robEntries> owners{};std::array<Capture,2> captures{};};
inline void token(std::ostream&o,Token t){o<<'['<<t.index<<','<<t.tag<<']';}
inline void optional(std::ostream&o,const std::optional<uint64_t>&v){if(v)o<<*v;else o<<"null";}
inline unsigned originalBin(const canonical_overlap::Sample&c){
 if(!c.choiceValid||c.choiceStore||c.choiceAtomic||c.choiceIsHead)return 0;
 if(c.startValid&&c.startReady)return 1;if(!c.choicePrechecked)return 2;if(c.physicalConflict)return 3;
 if(c.olderUncanonical)return 4;if(!c.noOtherSerial)return 5;if(!c.issueAvailable)return 6;if(c.olderSystem)return 7;return 8;
}
class Observer {
 struct History {bool valid=false,sourcesKnown=false,emitted=false;Owner owner;uint64_t first=0;std::optional<uint64_t> address,prepared,capture,start;};
 std::array<History,capacity::robEntries> history{};std::ofstream log;bool opened=false,seen=false,ended=false;uint64_t previous=0,sequence=0,spanBegin=0,spanEnd=0,roiFirst=0,roiEnd=0;std::string previousSnapshot;
 uint64_t samples=0,roiCycles=0,spans=0,ownerEvents=0;std::array<uint64_t,10> bins{};std::array<uint64_t,9> canonicalBins{};
 std::map<std::string,uint64_t> dimensions;
 void flush(){if(previousSnapshot.empty())return;log<<"{\"event\":\"span\",\"sequence\":"<<sequence++<<",\"begin\":"<<spanBegin<<",\"end\":"<<spanEnd<<",\"state\":"<<previousSnapshot<<"}\n";++spans;previousSnapshot.clear();}
 void emitOwner(const Owner&x){auto&h=history[x.token.index];need(h.valid&&h.owner.token==x.token,"unissued owner history full token");if(h.emitted)return;flush();
  log<<"{\"event\":\"owner\",\"sequence\":"<<sequence++<<",\"token\":";token(log,x.token);log<<",\"first_seen\":"<<h.first<<",\"pc\":"<<x.pc<<",\"memory\":"<<x.memory<<",\"store\":"<<x.store<<",\"atomic\":"<<x.atomic<<",\"system\":"<<x.system<<",\"writes_rd\":"<<x.writesRd<<",\"destination\":"<<x.destination<<",\"move_alias\":"<<x.moveAlias<<",\"sources_known\":"<<h.sourcesKnown<<",\"source1\":";if(h.sourcesKnown)log<<h.owner.source1;else log<<"null";log<<",\"source2\":";if(h.sourcesKnown)log<<h.owner.source2;else log<<"null";log<<"}\n";h.emitted=true;++ownerEvents;
 }
 void timing(std::ostream&o,const History&h){o<<",\"first_seen\":"<<h.first<<",\"first_address_known\":";optional(o,h.address);o<<",\"first_prepared\":";optional(o,h.prepared);o<<",\"first_capture\":";optional(o,h.capture);o<<",\"accepted_start\":";optional(o,h.start);}
 public:
 void sample(const Sample&s,const canonical_overlap::Sample&c,uint64_t cycle,bool roi){
  if(!opened){const auto*p=std::getenv("UNISSUED_STORE_TRACE");need(p&&*p,"unissued sidecar required");log.open(p);need(bool(log),"unissued sidecar open");opened=true;}
  need(!seen||cycle==previous+1,"unissued omitted/duplicate sample");seen=true;previous=cycle;++samples;
  if(c.reset){history={};return;}
  for(unsigned i=0;i<capacity::robEntries;++i){const auto&x=s.owners[i];auto&h=history[i];if(!x.live){h.valid=false;continue;}
   need(x.token.index==i&&x.age==capacity::age(i,s.head)&&x.age<s.robCount,"unissued live age/identity");
   if(!h.valid||h.owner.token!=x.token){h={};h.valid=true;h.owner=x;h.first=cycle;h.sourcesKnown=x.sourcesKnown;}
   need(h.owner.pc==x.pc&&h.owner.memory==x.memory&&h.owner.store==x.store&&h.owner.destination==x.destination,"unissued live immutable owner changed");
   if(x.sourcesKnown){need(!h.sourcesKnown||(h.owner.source1==x.source1&&h.owner.source2==x.source2),"unissued source identity changed");h.sourcesKnown=true;h.owner.source1=x.source1;h.owner.source2=x.source2;need(x.ready1==x.prfReady1&&x.ready2==x.prfReady2,"unissued readiness crosscheck");}
   if(x.addressKnown&&!h.address)h.address=cycle;if(x.prepared&&!h.prepared)h.prepared=cycle;
   for(const auto&z:s.captures)if(z.valid&&z.token==x.token&&!h.capture)h.capture=cycle;
  }
  if(roi){need(!ended,"unissued disjoint ROI");if(!roiCycles)roiFirst=cycle;roiEnd=cycle+1;++roiCycles;
   const bool selected=c.choiceValid&&!c.choiceStore&&!c.choiceAtomic&&!c.choiceIsHead;const Owner*load=nullptr;
   if(c.choiceValid){need(c.choice.index<capacity::robEntries,"unissued load index");load=&s.owners[c.choice.index];need(load->live&&load->pending&&load->token==c.choice&&load->memoryLive&&load->memory,"unissued choice lacks live full owner");emitOwner(*load);}
   if(selected&&c.choicePrechecked)need(c.preparedValid&&c.preparedMatches&&c.preparedAllowed&&c.prepared==c.choice&&c.preparedEpoch==c.epoch,"unissued prepared load certificate mismatch");
   std::vector<const Owner*> stores;unsigned olderOtherUnknown=0;bool missing1=false,missing2=false,missingAddress=false,missingPrepared=false,unknown=false;
   bool anyAddress=false,anyPrepared=false,waitingLoad=false,anyCapture=false;unsigned pendingStores=0;
   if(selected)for(const auto&x:s.owners)if(x.live&&x.memoryLive&&x.age<load->age){
    if(!x.store){olderOtherUnknown+=!x.memoryCanonical;continue;}stores.push_back(&x);emitOwner(x);if(!x.pending&&!history[x.token.index].start)unknown=true;
    if(x.pending){++pendingStores;if(!x.sourcesKnown)unknown=true;else {missing1|=!x.ready1;missing2|=!x.ready2;}missingAddress|=!x.addressKnown;missingPrepared|=!x.prepared;anyAddress|=x.addressKnown;anyPrepared|=x.prepared;}
   }
   const unsigned bin=!selected?0:!c.choicePrechecked?1:stores.empty()?2:unknown?9:!pendingStores?3:missing1?4:missing2?5:missingAddress?6:missingPrepared?7:8;
   ++bins[bin];const auto original=originalBin(c);++canonicalBins[original];
   std::ostringstream o;o<<"{\"bin\":"<<bin<<",\"canonical_bin\":"<<original<<",\"satp\":"<<s.satp<<",\"privilege\":"<<s.privilege<<",\"head\":"<<s.head<<",\"rob_count\":"<<s.robCount<<",\"epoch\":"<<c.epoch<<",\"stable\":"<<c.stable<<",\"selected\":"<<selected<<",\"choice\":";
   if(load){o<<"{\"token\":";token(o,load->token);o<<",\"age\":"<<load->age<<",\"store\":"<<c.choiceStore<<",\"atomic\":"<<c.choiceAtomic<<",\"head\":"<<c.choiceIsHead<<",\"prechecked\":"<<c.choicePrechecked<<",\"prepared_match\":"<<c.preparedMatches<<",\"va\":";if(c.choicePrechecked)o<<c.preparedVa;else o<<"null";o<<",\"pa\":";if(c.choicePrechecked)o<<c.preparedPa;else o<<"null";o<<",\"size\":";if(c.choicePrechecked)o<<c.preparedSize;else o<<"null";o<<'}';}else o<<"null";
   o<<",\"older_live_loads\":[";bool fol=true;if(selected)for(const auto&y:s.owners)if(y.live&&y.memoryLive&&y.memory&&!y.store&&!y.atomic&&y.age<load->age){emitOwner(y);if(!fol)o<<',';fol=false;token(o,y.token);}o<<"]";
   o<<",\"start_fire\":"<<(c.startValid&&c.startReady)<<",\"physical_conflict\":"<<c.physicalConflict<<",\"older_uncanonical\":"<<c.olderUncanonical<<",\"issue_available\":"<<c.issueAvailable<<",\"no_other_serial\":"<<c.noOtherSerial<<",\"older_system\":"<<c.olderSystem<<",\"older_other_uncanonical\":"<<olderOtherUnknown<<",\"certificate\":";
   if(c.record.valid){const auto&z=c.record;o<<"{\"token\":";token(o,z.token);o<<",\"epoch\":"<<z.epoch<<",\"va\":"<<z.va<<",\"pa\":"<<z.pa<<",\"size\":"<<z.size<<",\"mask\":"<<z.mask<<'}';}else o<<"null";
   o<<",\"stores\":[";bool first=true;for(const auto*p:stores){const auto&x=*p;const auto&h=history[x.token.index];if(!first)o<<',';first=false;
    o<<"{\"token\":";token(o,x.token);o<<",\"age\":"<<x.age<<",\"pending\":"<<x.pending<<",\"killed\":"<<x.killed<<",\"sources_known\":"<<x.sourcesKnown<<",\"address_known\":"<<x.addressKnown<<",\"prepared\":"<<x.prepared<<",\"busy\":"<<x.busy<<",\"size\":"<<x.size<<",\"va\":";if(x.addressKnown)o<<x.va;else o<<"null";
    o<<",\"safe_raw_range\":";if(x.addressKnown)o<<x.safeRaw;else o<<"null";o<<",\"certificate_match\":"<<(c.record.valid&&c.record.token==x.token)<<",\"registered_ready1\":";if(x.sourcesKnown)o<<x.ready1;else o<<"null";o<<",\"registered_ready2\":";if(x.sourcesKnown)o<<x.ready2;else o<<"null";o<<",\"prf_ready1\":";if(x.sourcesKnown)o<<x.prfReady1;else o<<"null";o<<",\"prf_ready2\":";if(x.sourcesKnown)o<<x.prfReady2;else o<<"null";
    o<<",\"source1\":";if(x.sourcesKnown)o<<x.source1;else o<<"null";o<<",\"source2\":";if(x.sourcesKnown)o<<x.source2;else o<<"null";timing(o,h);
    o<<",\"capture\":";const Capture*cap=nullptr;for(const auto&z:s.captures)if(z.valid&&z.token==x.token)cap=&z;
    if(cap){anyCapture=true;o<<"{\"va\":"<<cap->va<<",\"data_ready\":"<<cap->dataReady<<'}';}else o<<"null";
    o<<",\"is_head\":"<<(x.age==0)<<",\"lsu_slot\":";const canonical_overlap::Slot* slot=nullptr;for(const auto&z:c.slots)if(z.live&&z.token==x.token)slot=&z;if(slot){o<<"{\"serial\":"<<slot->serial<<",\"request_accepted_known\":"<<slot->acceptedKnown<<",\"request_accepted\":"<<slot->accepted<<",\"phase\":"<<slot->phase<<'}';}else o<<"null";
    o<<",\"preceding_live_loads\":[";bool fl=true;for(const auto&y:s.owners)if(y.live&&y.memoryLive&&y.memory&&!y.store&&!y.atomic&&y.age<x.age){emitOwner(y);if(!fl)o<<',';fl=false;token(o,y.token);}o<<"]";
    o<<",\"data_producers\":[";bool fp=true;
    if(x.sourcesKnown&&!x.ready2)for(const auto&y:s.owners)if(y.live&&y.age<x.age&&y.writesRd&&y.destination==x.source2){
     emitOwner(y);if(!fp)o<<',';fp=false;o<<"{\"token\":";token(o,y.token);o<<",\"age\":"<<y.age<<",\"destination\":"<<y.destination<<",\"memory_live\":"<<y.memoryLive<<",\"pending\":"<<y.pending<<",\"accepted_start\":";optional(o,history[y.token.index].start);o<<'}';
     waitingLoad|=y.memory&&y.memoryLive&&!y.store&&!y.atomic&&!y.moveAlias;
    }o<<"]}";
   }o<<"]}";
   if(selected&&c.choicePrechecked){dimensions["selected_prechecked"]++;if(stores.size()>1)dimensions["multiple_older_stores"]++;if(pendingStores)dimensions["unissued_older_store"]++;if(missing1)dimensions["some_rs1_not_ready"]++;if(missing2)dimensions["some_rs2_not_ready"]++;if(missingAddress)dimensions["some_address_not_captured"]++;if(missingPrepared)dimensions["some_store_not_prepared"]++;if(anyAddress)dimensions["some_unissued_address_known"]++;if(anyPrepared)dimensions["some_unissued_prepared"]++;if(waitingLoad)dimensions["rs2_matches_older_live_load_destination"]++;if(anyCapture)dimensions["capture_inflight"]++;if(olderOtherUnknown)dimensions["other_older_uncanonical_memory"]++;}
   auto snapshot=o.str();if(snapshot!=previousSnapshot){flush();previousSnapshot=std::move(snapshot);spanBegin=cycle;}spanEnd=cycle+1;
  }else if(roiCycles){ended=true;flush();}
  // These handshakes change pending at the next edge. A same-cycle selection
  // never gets to borrow future accepted-owner evidence.
  if(c.startValid&&c.startReady){need(c.start.index<capacity::robEntries,"unissued accepted start index");auto&h=history[c.start.index];need(h.valid&&h.owner.token==c.start,"unissued start lacks exact live owner");need(!h.start,"unissued duplicate accepted start");h.start=cycle;}
 }
 void finish(std::ostream&o){flush();uint64_t total=0;for(auto n:bins)total+=n;need(total==roiCycles&&roiEnd-roiFirst==roiCycles,"unissued exclusive ROI conservation");
  log<<"{\"event\":\"terminal\",\"sequence\":"<<sequence<<",\"roi_first\":"<<roiFirst<<",\"roi_end\":"<<roiEnd<<",\"roi_cycles\":"<<roiCycles<<",\"spans\":"<<spans<<",\"owners\":"<<ownerEvents<<"}\n";log.flush();need(bool(log),"unissued trace write failure");
  o<<"UNISSUED_STORES {\"schema\":1,\"samples\":"<<samples<<",\"roi_first\":"<<roiFirst<<",\"roi_end\":"<<roiEnd<<",\"roi_cycles\":"<<roiCycles<<",\"spans\":"<<spans<<",\"owners\":"<<ownerEvents<<",\"exclusive_bins\":[";for(unsigned i=0;i<bins.size();++i){if(i)o<<',';o<<bins[i];}o<<"],\"canonical_bins\":[";for(unsigned i=0;i<canonicalBins.size();++i){if(i)o<<',';o<<canonicalBins[i];}o<<"],\"overlapping_dimensions\":{";bool f=true;for(const auto&[k,n]:dimensions){if(!f)o<<',';f=false;o<<'"'<<k<<"\":"<<n;}o<<"},\"predicted_savings\":null}\n";
 }
};
}
