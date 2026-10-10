#pragma once
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <ostream>
#include <sstream>
#include <stdexcept>
#include <string>
#ifndef PREFETCH_CANDIDATE_CYCLES
#define PREFETCH_CANDIDATE_CYCLES 1
#endif
namespace admission {
constexpr unsigned Lifetime=PREFETCH_CANDIDATE_CYCLES;
static_assert(Lifetime==1 || Lifetime==16,"only audited life1/life16 profiles");
inline void need(bool x,const char* m){if(!x)throw std::runtime_error(m);}
constexpr unsigned N=17;
inline const char* gateName(unsigned i){static const char* n[N]={"posted_not_allowed","pf_live","pf_release","present","set_reserved","victim_pending","dirty_read_victim","no_free_mshr","demand_offered","barrier","flush_active","flush_request","bypass_busy","probe_busy","tl_b_valid","eviction_busy","queued_eviction"};return n[i];}
struct Mshr{unsigned phase=0,index=0;bool pf=false,store=false;uint64_t address=0;};
struct Wb{bool live=false,pf=false;uint64_t address=0;};
struct Sample{
 bool reset=false,valid=false,ready=false,cpuFire=false,ordinary=false,write=false,hint=false;
 uint64_t address=0;bool lastValid=false;uint64_t lastLine=0;
 bool postedAllowed=false,live=false,release=false,tracked=false,trackedPresent=false,trackedStore=false,consume=false;
 uint64_t trackedAddress=0;unsigned trackedIndex=0;
 bool cv=false,cs=false;uint64_t ca=0;unsigned pi=0,freeMshr=0;
 bool flush=false,can=false,queuedEvict=false;unsigned evictionState=0,remaining=0;
 bool needsMiss=false,demandReserved=false,barrierRequest=false,barrier=false,flushActive=false,tlB=false;
 unsigned bypassState=0,probeState=0;std::array<Wb,2> wbs{};
 std::array<bool,2> wayValid{},wayDirty{};std::array<uint64_t,2> wayTag{};bool victimValid=false,victimDirty=false;uint64_t victimAddress=0;
 unsigned origin=0,events=0;std::array<bool,N> gates{};std::array<Mshr,2> mshrs{};
 bool readFire()const{return valid&&ready&&ordinary&&!write;}
 bool storeFire()const{return valid&&ready&&ordinary&&write;}
 bool sequential()const{return lastValid&&(address>>6)==lastLine+1&&(address>>6)!=0;}
 bool available()const{return postedAllowed&&!cv&&!live&&!release&&(!tracked||consume||!trackedPresent);}
 bool emitted()const{return origin&3;}bool allocated()const{return origin&12;}
 bool generated()const{return readFire()&&sequential()&&hint&&available();}
 unsigned generationBin()const{if(!lastValid)return 0;if(!sequential())return 1;if(!hint)return 2;if(!postedAllowed)return 3;if(cv)return 4;if(live)return 5;if(release)return 6;if(tracked&&trackedPresent&&!consume)return trackedStore?8:7;return 9;}
 bool otherwiseEligible()const{for(unsigned i=0;i<N;++i)if(i!=15&&gates[i])return false;return true;}
 bool retain()const{return cv&&otherwiseEligible()&&(evictionState==1||evictionState==2)&&remaining>0;}
 std::array<bool,N> deriveGates()const{
  auto set=(ca>>6)&255,tag=(ca>>14)&0x7ffff;
  bool present=false,reserved=false,pending=false,free=false;
  for(unsigned w=0;w<2;++w)present|=wayValid[w]&&wayTag[w]==tag;
  present=present&&ca>=0x80200000ULL&&ca<0x100200000ULL;
  for(auto&m:mshrs){free|=!m.phase;reserved|=m.phase&&(m.index&255)==set;}
  for(auto&w:wbs)pending|=w.live&&(w.address>>6)==(ca>>6);
  bool demand=valid&&((needsMiss&&!demandReserved)||barrierRequest||write);
  return {!postedAllowed,live,release,present,reserved,pending,victimValid&&victimDirty&&!cs,!free,demand,barrier,flushActive,flush,bypassState!=0,probeState!=0,tlB,evictionState!=0,queuedEvict};
 }
 unsigned allocationBin()const{for(unsigned i=0;i<N;++i)if(gates[i])return i;return N;}
};
inline void validate(const Sample& s){
 if(s.reset)return;
 need(s.cpuFire==(s.valid&&s.ready),"admission cache fire mismatch");
 need(s.valid||(!s.ordinary&&!s.write&&!s.hint&&!s.address),"admission invalid request payload");
 need(s.lastValid||!s.lastLine,"admission invalid history payload");
 need(s.tracked||(!s.trackedAddress&&!s.trackedIndex&&!s.trackedStore&&!s.trackedPresent),"admission invalid tracked payload");
 need(s.cv||(!s.ca&&!s.cs&&!s.pi&&!s.can&&!s.victimValid&&!s.victimDirty&&!s.victimAddress&&!s.wayValid[0]&&!s.wayValid[1]&&!s.wayDirty[0]&&!s.wayDirty[1]&&!s.wayTag[0]&&!s.wayTag[1]&&!s.remaining&&!s.needsMiss&&!s.demandReserved&&!s.barrierRequest&&!s.barrier&&!s.flushActive&&!s.bypassState&&!s.probeState&&!s.tlB&&!s.queuedEvict&&!s.evictionState),"admission invalid candidate payload");
 need(s.consume==(s.cpuFire&&s.ordinary&&s.tracked&&(s.address>>6)==(s.trackedAddress>>6)),"admission consume mismatch");
 need(s.origin<64&&s.events<2048,"admission events width");
 for(unsigned i=0;i<3;++i){auto z=(s.origin>>(2*i))&3;need(z!=3&&bool(z)==bool((s.events>>i)&1),"admission event/origin disagreement");}
 need(bool(s.origin&48)==s.consume&&(!s.consume||bool(s.origin&32)==s.trackedStore),"admission useful origin/consume mismatch");
 need(bool(s.origin&1)==s.generated(),"admission read candidate source/gates mismatch");
 need(!(s.origin&2)||(s.storeFire()&&s.hint&&s.available()&&!s.flush),"admission store candidate lacks accepted permitted store");
 need(!s.emitted()||!s.cv,"admission candidate overwrite");
 need(!s.allocated()||s.cv,"admission allocation lacks candidate");
 if(s.cv){need(s.evictionState<4,"admission eviction state range");need(s.remaining<Lifetime,"admission candidate remaining range");need(s.gates==s.deriveGates(),"admission independently derived gates mismatch");need(s.ca%64==0&&s.pi<512,"admission candidate address/index");need(s.can==(s.allocationBin()==N),"admission allocation gates mismatch");need(s.allocated()==s.can,"admission allocation event missing/extra");if(s.allocated())need(bool(s.origin&8)==s.cs,"admission allocation origin mismatch");}
 for(auto&w:s.wbs)need(w.live||(!w.pf&&!w.address),"admission invalid WB payload");
 for(unsigned w=0;w<2;++w)need(s.wayValid[w]||(!s.wayDirty[w]&&!s.wayTag[w]),"admission invalid way payload");
 for(auto&m:s.mshrs){need(m.phase<=4,"admission MSHR phase range");need(m.phase||(!m.pf&&!m.store&&!m.address&&!m.index),"admission invalid MSHR payload");if(m.phase)need(m.index<512&&(!m.store||m.pf),"admission live MSHR payload");}
}
inline void boolean(std::ostream&o,const char*n,bool v){o<<",\""<<n<<"\":"<<v;}
inline uint64_t nextAddress(uint64_t address){return(address&~4095ULL)|((((address>>6)+1)&63)<<6);}
inline void rawJson(std::ostream&o,const Sample&s){
 o<<",\"remaining\":"<<s.remaining<<",\"needs_miss\":"<<s.needsMiss<<",\"demand_reserved\":"<<s.demandReserved<<",\"barrier_request\":"<<s.barrierRequest<<",\"barrier\":"<<s.barrier<<",\"flush_active\":"<<s.flushActive<<",\"bypass_state\":"<<s.bypassState<<",\"probe_state\":"<<s.probeState<<",\"tl_b_valid\":"<<s.tlB<<",\"mshrs\":[";
 for(unsigned i=0;i<2;++i){if(i)o<<",";auto&m=s.mshrs[i];o<<"{\"phase\":"<<m.phase<<",\"pf\":"<<m.pf<<",\"store\":"<<m.store<<",\"address\":";if(m.phase)o<<m.address;else o<<"null";o<<",\"index\":";if(m.phase)o<<m.index;else o<<"null";o<<"}";}o<<"],\"wbs\":[";
 for(unsigned i=0;i<2;++i){if(i)o<<",";auto&w=s.wbs[i];o<<"{\"live\":"<<w.live<<",\"pf\":"<<w.pf<<",\"address\":";if(w.live)o<<w.address;else o<<"null";o<<"}";}o<<"]";
}
inline void stateJson(std::ostream&o,const Sample&s){
 o<<"\"cache_valid\":"<<s.valid<<",\"cache_ready\":"<<s.ready<<",\"ordinary\":"<<s.ordinary<<",\"write\":"<<s.write<<",\"address\":";if(s.valid)o<<s.address;else o<<"null";
 boolean(o,"hint",s.hint);boolean(o,"last_valid",s.lastValid);o<<",\"last_line\":";if(s.lastValid)o<<s.lastLine;else o<<"null";
 boolean(o,"sequential",s.readFire()&&s.sequential());boolean(o,"available",s.available());boolean(o,"posted_allowed",s.postedAllowed);boolean(o,"candidate_valid",s.cv);boolean(o,"pf_live",s.live);boolean(o,"pf_release",s.release);boolean(o,"tracked_valid",s.tracked);boolean(o,"tracked_present",s.trackedPresent);boolean(o,"consume",s.consume);
 o<<",\"tracked_address\":";if(s.tracked)o<<s.trackedAddress;else o<<"null";o<<",\"tracked_index\":";if(s.tracked)o<<s.trackedIndex;else o<<"null";o<<",\"tracked_store\":";if(s.tracked)o<<s.trackedStore;else o<<"null";
 boolean(o,"flush",s.flush);o<<",\"origin\":"<<s.origin<<",\"events\":"<<s.events;
}
struct Counts{uint64_t cycles=0,reads=0,candidate[2]={},allocate[2]={},useful[2]={},retained[2]={},cancelled[2]={},generation[10]={},blockers[N]={},exclusive[N+1]={};
 void add(const Sample&s){++cycles;if(s.readFire()){++reads;++generation[s.generationBin()];}for(unsigned i=0;i<2;++i){candidate[i]+=(s.origin>>i)&1;allocate[i]+=(s.origin>>(i+2))&1;useful[i]+=(s.origin>>(i+4))&1;}if(s.cv){++exclusive[s.allocationBin()];for(unsigned i=0;i<N;++i)blockers[i]+=s.gates[i];retained[s.cs]+=s.retain();cancelled[s.cs]+=!s.retain()&&!s.allocated();}if(s.emitted()&&s.flush)++cancelled[bool(s.origin&2)];}
 void json(std::ostream&o)const{o<<"{\"cycles\":"<<cycles<<",\"reads\":"<<reads<<",\"candidate\":["<<candidate[0]<<","<<candidate[1]<<"],\"allocate\":["<<allocate[0]<<","<<allocate[1]<<"],\"useful\":["<<useful[0]<<","<<useful[1]<<"],\"retained\":["<<retained[0]<<","<<retained[1]<<"],\"cancelled\":["<<cancelled[0]<<","<<cancelled[1]<<"],\"generation_bins\":[";for(unsigned i=0;i<10;++i)o<<(i?",":"")<<generation[i];o<<"],\"allocation_exclusive\":[";for(unsigned i=0;i<=N;++i)o<<(i?",":"")<<exclusive[i];o<<"],\"allocation_overlapping\":[";for(unsigned i=0;i<N;++i)o<<(i?",":"")<<blockers[i];o<<"]}";}
};
struct Observer{
 std::ofstream trace;bool held=false;Sample prev{};uint64_t priorCycle=0,seq=0,candidateId=0,prevSeq=0,prevCandidateId=0,liveCandidateId=0,liveCandidateCycle=0,liveSourceSeq=0,liveSourceAddress=0;bool prevActive=false,liveSourceStore=false,liveSourceHint=false,storeHistoryValid=false,storeSequential=false;uint64_t liveDeadline=0,storeLastLine=0;bool roiStarted=false,roiEnded=false;unsigned entryOrigin=0,exitOrigin=0;uint64_t entryId=0,exitId=0;Counts all,roi;
 Observer(){const char*p=std::getenv("READ_PREFETCH_TRACE");if(p){trace.open(p,std::ios::out|std::ios::trunc);need(bool(trace),"admission trace open");}}
 void row(const std::string&v){if(trace){trace<<v<<'\n';need(bool(trace),"admission trace write");}}
 void sample(const Sample&s,uint64_t cycle,bool active){validate(s);if(s.reset){need(!held,"admission reset after live sampling");return;}
 if(held){need(cycle==priorCycle+1,"admission skipped edge");
  bool lv=prev.flush?false:(prev.readFire()?true:prev.lastValid);need(s.lastValid==lv,"admission read history validity transition");if(lv)need(s.lastLine==(prev.readFire()?prev.address>>6:prev.lastLine),"admission read history address transition");
  bool retained=prev.cv&&prev.otherwiseEligible()&&(prev.evictionState==1||prev.evictionState==2)&&priorCycle<liveDeadline;
  need(s.cv==((prev.emitted()||retained)&&!prev.flush),"admission missing/extra retained candidate");
  if(s.cv){
   auto expectedAddress=prev.emitted()?nextAddress(prev.address):prev.ca;
   auto expectedStore=prev.emitted()?bool(prev.origin&2):prev.cs;
   auto deadline=prev.emitted()?priorCycle+Lifetime:liveDeadline;
   need(cycle<=deadline&&s.remaining==deadline-cycle,"admission deadline refresh/countdown mismatch");
   need(s.ca==expectedAddress&&s.cs==expectedStore,"admission candidate address/origin transition");
  }
  if(prev.allocated()){need(prev.freeMshr<2,"admission allocation slot range");const auto&m=s.mshrs[prev.freeMshr];need(m.phase&&m.pf&&m.store==prev.cs&&m.address==prev.ca&&m.index==prev.pi,"admission exact post-edge MSHR allocation missing");}
  all.add(prev);if(prevActive)roi.add(prev);
  if(prev.readFire()) {std::ostringstream o;o<<"{\"event\":\"read_accept\",\"edge\":"<<cycle<<",\"offer\":"<<priorCycle<<",\"roi\":"<<prevActive<<",\"source_seq\":"<<prevSeq<<",\"bin\":"<<prev.generationBin()<<",";stateJson(o,prev);o<<"}";row(o.str());}
  if(prev.storeFire()){std::ostringstream o;o<<"{\"event\":\"store_accept\",\"edge\":"<<cycle<<",\"offer\":"<<priorCycle<<",\"roi\":"<<prevActive<<",\"source_seq\":"<<prevSeq<<",";stateJson(o,prev);o<<"}";row(o.str());}
  if(prev.flush||(prev.cpuFire&&!prev.ordinary)){std::ostringstream o;o<<"{\"event\":\"history_clear\",\"edge\":"<<cycle<<",\"flush\":"<<prev.flush<<"}";row(o.str());}
  if(prev.emitted()){std::ostringstream o;o<<"{\"event\":\"candidate\",\"edge\":"<<cycle<<",\"offer\":"<<priorCycle<<",\"roi\":"<<prevActive<<",\"id\":"<<prevCandidateId<<",\"source_seq\":"<<prevSeq<<",\"source_address\":"<<prev.address<<",\"store\":"<<bool(prev.origin&2)<<",\"address\":"<<((prev.address&~4095ULL)|((((prev.address>>6)+1)&63)<<6))<<",\"hint\":"<<prev.hint<<",\"deadline\":"<<(priorCycle+Lifetime)<<",\"lifetime\":"<<Lifetime<<",\"cancelled_on_emit\":"<<prev.flush<<"}";row(o.str());}
  if(prev.cv){std::ostringstream o;o<<"{\"event\":\"decision\",\"edge\":"<<cycle<<",\"offer\":"<<priorCycle<<",\"roi\":"<<prevActive<<",\"id\":"<<liveCandidateId<<",\"source_seq\":"<<liveSourceSeq<<",\"source_address\":"<<liveSourceAddress<<",\"emitted_offer\":"<<liveCandidateCycle<<",\"deadline\":"<<liveDeadline<<",\"attempt\":"<<(priorCycle-liveCandidateCycle)<<",\"source_hint\":"<<liveSourceHint<<",\"retain\":"<<retained<<",\"cancel\":"<<(!retained&&!prev.allocated())<<",\"candidate_address\":"<<prev.ca<<",\"store\":"<<prev.cs<<",\"allocate\":"<<prev.allocated()<<",\"slot\":";if(prev.allocated())o<<prev.freeMshr;else o<<"null";o<<",\"index\":"<<prev.pi<<",\"exclusive\":"<<prev.allocationBin()<<",\"gates\":[";for(unsigned i=0;i<N;++i)o<<(i?",":"")<<prev.gates[i];o<<"],\"way_valid\":["<<prev.wayValid[0]<<","<<prev.wayValid[1]<<"],\"way_dirty\":["<<prev.wayDirty[0]<<","<<prev.wayDirty[1]<<"],\"way_tag\":[";for(unsigned w=0;w<2;++w){if(w)o<<",";if(prev.wayValid[w])o<<prev.wayTag[w];else o<<"null";}o<<"],\"victim_valid\":"<<prev.victimValid<<",\"victim_dirty\":"<<prev.victimDirty<<",\"victim_address\":";if(prev.victimValid)o<<prev.victimAddress;else o<<"null";o<<",\"victim_tracked_index_match\":"<<(prev.tracked&&prev.trackedIndex==prev.pi)<<",\"victim_tracked_address_match\":"<<(prev.tracked&&prev.victimValid&&prev.trackedAddress==prev.victimAddress)<<",\"queued_eviction\":"<<prev.queuedEvict<<",\"eviction_state\":"<<prev.evictionState<<",";stateJson(o,prev);rawJson(o,prev);o<<"}";row(o.str());
   if(prev.allocated()){std::ostringstream w;const auto&m=s.mshrs[prev.freeMshr];w<<"{\"event\":\"allocation_witness\",\"edge\":"<<cycle<<",\"id\":"<<liveCandidateId<<",\"slot\":"<<prev.freeMshr<<",\"phase\":"<<m.phase<<",\"address\":"<<m.address<<",\"index\":"<<m.index<<",\"store\":"<<m.store<<"}";row(w.str());}
  }
  if(prev.tracked&&(!prev.trackedPresent||prev.consume||prev.flush)){std::ostringstream o;o<<"{\"event\":\"tracked_release\",\"edge\":"<<cycle<<",\"roi\":"<<prevActive<<",\"address\":"<<prev.trackedAddress<<",\"store\":"<<prev.trackedStore<<",\"consume\":"<<prev.consume<<",\"invalidated\":"<<!prev.trackedPresent<<",\"flush\":"<<prev.flush<<"}";row(o.str());}
  if(prev.emitted()){liveCandidateId=prevCandidateId;liveCandidateCycle=priorCycle;liveSourceSeq=prevSeq;liveSourceAddress=prev.address;liveSourceStore=bool(prev.origin&2);liveSourceHint=prev.hint;liveDeadline=priorCycle+Lifetime;}
 }
 if(active&&!prevActive){need(!roiStarted,"admission ROI restarted");roiStarted=true;entryId=s.cv?liveCandidateId:0;entryOrigin=s.cs;}
 if(!active&&prevActive){roiEnded=true;exitId=s.cv?liveCandidateId:0;exitOrigin=s.cs;}
 if(active!=prevActive){std::ostringstream o;o<<"{\"event\":\"roi_boundary\",\"edge\":"<<cycle<<",\"enter\":"<<active<<",\"id\":";if(s.cv)o<<liveCandidateId;else o<<"null";o<<",\"store\":";if(s.cv)o<<s.cs;else o<<"null";o<<"}";row(o.str());}
 if(!held)need(!s.cv,"admission sampling began after candidate birth");
 // Store history is prediction-only; current permission is mandatory on each generation.
 bool same=storeHistoryValid&&(s.address>>6)==storeLastLine;
 bool sequential=storeHistoryValid&&(s.address>>6)!=0&&(s.address>>6)==storeLastLine+1;
 bool storeGenerated=s.storeFire()&&!s.flush&&s.hint&&s.available()&&(sequential||(same&&storeSequential));
 need(bool(s.origin&2)==storeGenerated,"admission independent store generation mismatch");
 if(s.flush||(s.cpuFire&&!s.ordinary)){storeHistoryValid=false;storeSequential=false;}
 else if(s.storeFire()){storeHistoryValid=true;storeLastLine=s.address>>6;if(!same)storeSequential=sequential;}
 prevSeq=s.cpuFire?++seq:0;prevCandidateId=s.emitted()?++candidateId:0;prev=s;priorCycle=cycle;prevActive=active;held=true;
 }
 void finish(std::ostream&o){need(!prev.cv&&!prev.emitted()&&!prev.allocated(),"admission undrained terminal event");std::ostringstream s;s<<"{\"event\":\"summary\",\"schema\":2,\"lifetime\":"<<Lifetime<<",\"all\":";all.json(s);s<<",\"roi\":";roi.json(s);s<<",\"roi_carry_in\":["<<(entryId&&!entryOrigin)<<","<<(entryId&&entryOrigin)<<"],\"roi_carry_out\":["<<(exitId&&!exitOrigin)<<","<<(exitId&&exitOrigin)<<"],\"predicted_savings\":null}";row(s.str());if(trace)trace.flush();o<<"READ_PREFETCH_ADMISSION "<<s.str()<<'\n';}
};
}
