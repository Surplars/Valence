#pragma once
// Uncompiled passive audit draft. Fixed M/Bare benchmark family ONLY.
#include "prefetch_audit_frame.h"
#include "prefetch_transport_audit.h"
#include "../contract_oracle.h"
#include <map>
#include <deque>
#include <optional>
#include <iostream>
#include <string>
namespace cpu_prefetch_audit {
struct Owner {uint64_t seq=0,pc=0,mask=0; bool operator==(const Owner&)const=default;};
struct Demand {Owner owner;bool upstream=false,cache=false,physicalDone=false;std::optional<uint64_t> data;unsigned kind=0;std::optional<unsigned> source;};
struct OptionalOwner {Owner owner;uint64_t line=0;bool stale=false,used=false;std::optional<unsigned> source;};
struct CachedLine {bool valid=false,speculative=false,used=false;uint64_t line=0,origin=0;std::array<uint64_t,8> words{};};
struct Wire {bool av=false,ar=false,dv=false,dr=false;APayload a{};DPayload d{};};
template<class D> Wire captureWire(D&d){
 Wire w;w.av=d.io$$instructionA$$valid;w.ar=d.io$$instructionA$$ready;w.dv=d.io$$instructionD$$valid;w.dr=d.io$$instructionD$$ready;
 w.a={d.io$$instructionA$$bits$$address,d.get_io$$instructionA$$bits$$data(),unsigned(d.get_io$$instructionA$$bits$$opcode()),unsigned(d.get_io$$instructionA$$bits$$param()),unsigned(d.io$$instructionA$$bits$$size),unsigned(d.io$$instructionA$$bits$$source),unsigned(d.io$$instructionA$$bits$$mask),bool(d.get_io$$instructionA$$bits$$corrupt())};
 w.d={d.io$$instructionD$$bits$$data,unsigned(d.io$$instructionD$$bits$$source),unsigned(d.io$$instructionD$$bits$$size),unsigned(d.io$$instructionD$$bits$$opcode),unsigned(d.io$$instructionD$$bits$$param),unsigned(d.io$$instructionD$$bits$$sink),bool(d.io$$instructionD$$bits$$denied),bool(d.io$$instructionD$$bits$$corrupt)};return w;
}
class Audit {
 static constexpr uint64_t ram=0x80200000ULL,end=0x80220000ULL;
 TransportLedger transport;
 std::map<uint64_t,Demand> owners;
 std::deque<uint64_t> virtualOrder,bufferOrder,returnOrder;
 std::optional<Owner> heldVirtual,heldCache;
 std::optional<uint64_t> activeCache;
 std::optional<OptionalOwner> candidate,spec;
 std::array<std::array<CachedLine,2>,256> cache{};
 std::array<uint64_t,4> expectedPhase{};
 std::optional<unsigned> heldCompletion;
 uint64_t n=0,result=0,cutoff=0,cycles=0,physicalAccepted=0,physicalCompleted=0;
 bool ambiguous=false,havePrevious=false;unsigned fallbackNextGroup=0;
 Frame previous{};
 uint64_t seeds=0,seedCancels=0,joins=0,specInstalls=0,staleDrops=0,specErrors=0,specHits=0,unusedEvictions=0,unusedInvalidations=0;
 static void check(bool b,const std::string&m){if(!b)throw std::runtime_error("CPU_PREFETCH_AUDIT "+m);}
 static Owner owner(uint64_t seq,uint64_t pc,uint64_t mask){return {seq,pc,mask};}
 static uint64_t line(uint64_t pc){return pc&~uint64_t(63);}
 static bool inRam(uint64_t a,uint64_t len){return len&&len<=end-ram&&a>=ram&&a-ram<=end-ram-len;}
 bool contextAgeEligible(const Owner&o,bool kill)const{return !kill&&!ambiguous&&n!=UINT64_MAX&&o.seq>=cutoff;}
 bool eligible(const Owner&o,bool kill)const{
  if(!contextAgeEligible(o,kill)||o.mask!=3||(o.pc&7)||line(o.pc)>UINT64_MAX-127)return false;
  const uint64_t next=line(o.pc)+64; const independent::Pmp fixedPmp{};
  return inRam(line(o.pc),64)&&inRam(next,64)&&(line(o.pc)>>12)==(next>>12)&&independent::execute(fixedPmp,line(o.pc),64,3)&&independent::execute(fixedPmp,next,64,3);
 }
 Demand& demand(uint64_t seq){auto it=owners.find(seq);check(it!=owners.end(),"unknown full64 demand owner");return it->second;}
 bool ownEmpty()const{return owners.empty()&&virtualOrder.empty()&&bufferOrder.empty()&&returnOrder.empty()&&!heldVirtual&&!heldCache&&!activeCache&&!candidate&&!spec;}
 void setReturnedData(uint64_t seq,uint64_t data){auto&d=demand(seq);check(!d.data,"duplicate expected demand payload");d.data=data;}
 void completion(const Frame&f,const TransferResult&t){
  check(t.words==f.completionWords,"actual 512-bit engine result differs from independently checked D words");
  if(t.tag==0){check(activeCache&&*activeCache==t.ownerSeq,"demand fill completion lost cache owner");auto&d=demand(t.ownerSeq);check(d.source&&*d.source==t.source&&d.kind==2,"demand fill source/class mismatch");setReturnedData(t.ownerSeq,t.words[(d.owner.pc>>3)&7]);}
  else{check(spec&&spec->source&&*spec->source==t.source&&spec->owner.seq==t.ownerSeq,"spec completion owner mismatch");if(t.error)++specErrors;
   if(activeCache){auto&d=demand(*activeCache);if(d.kind==3&&d.source&&*d.source==t.source){check(line(d.owner.pc)==t.address,"joined response line mismatch");setReturnedData(d.owner.seq,t.words[(d.owner.pc>>3)&7]);}}
   if(spec->stale)++staleDrops;
  }
 }
public:
 explicit Audit(TransportLedger::ReadBeat read):transport(std::move(read)){}
 void retired(uint32_t inst)const{if((inst&0x7f)==0x73)check(inst==0x30401073,"fixed performance guest retired unapproved SYSTEM/CSR");}
 template<class D>void observe(D&dut,uint64_t cycle){
  Frame f=capture(dut);Wire w=captureWire(dut);check(cycle==cycles++,"nonconsecutive host frame");
  if(f.fetch_idle)check(ownEmpty(),"current DUT fetchIdle precedes old independent owner drain");
  check(f.context_privilege==3&&f.context_satp==0,"independent fixed M/Bare context changed");for(unsigned i=0;i<16;++i)check(f.pmpCfg[i]==0&&f.pmpAddr[i]==0,"independent fixed PMP policy changed");
  check(n!=UINT64_MAX&&!ambiguous,"fixed CPU suite reached unqualified sequence-wrap scope");
  bool kill=false;for(auto x:f.killProducers)kill|=bool(x);check(kill==bool(f.kill),"K union mismatch");
  check(f.virtual_current_sequence==n&&f.virtual_expected_result==result&&f.cutoff==cutoff&&bool(f.age_ambiguous)==ambiguous,"host full64 sequence/cutoff state mismatch");
  check(bool(f.age_usable)==(!kill&&!ambiguous&&n!=UINT64_MAX),"age usability mismatch");
  if(havePrevious){check(f.virtual_current_sequence==previous.virtual_next_sequence&&f.virtual_expected_result==previous.virtual_expected_result_next&&f.held==previous.held_next&&f.cutoff==previous.cutoff_next,"adjacent current/NEXT phase mismatch");}
  check(f.phase==expectedPhase,"fill current phase disagrees with independent transport lifecycle");
  for(unsigned s=0;s<4;++s)if(expectedPhase[s]){auto t=transport.sourceSnapshot(s);check(t.source==s&&t.address==f.slotAddress[s]&&t.tag==f.slotTag[s],"fill current source metadata changed");}
  check(bool(f.candidate_valid)==bool(candidate)&&bool(f.spec_engine_outstanding)==bool(spec),"optional current credit mismatch");
  if(candidate)check(f.certificate_seq==candidate->owner.seq&&f.certificate_priv==3&&f.certificate_identity&&f.candidate_line==candidate->line,"candidate full certificate changed");
  if(spec)check(f.certificate_seq==spec->owner.seq&&f.certificate_priv==3&&f.certificate_identity&&f.spec_engine_line==spec->line&&bool(f.spec_engine_stale)==spec->stale,"engine full certificate/stale mismatch");
  check(bool(f.virtual_fire)==bool(f.virtual_valid&&f.virtual_ready)&&bool(f.physical_upstream_fire)==bool(f.physical_upstream_valid&&f.physical_upstream_ready)&&bool(f.cache_fire)==bool(f.cache_valid&&f.cache_ready),"public handshake reconstruction mismatch");
  check(bool(f.physical_response_fire)==bool(f.physical_response_valid&&f.physical_response_ready),"physical reply handshake mismatch");
  if(f.result_raw_valid)check(f.result_matches&&f.virtual_response_sequence==result,"raw result wrong full64 token hidden by qualified valid");
  check(bool(f.virtual_response_valid)==bool(f.result_raw_valid&&f.result_matches),"qualified result valid mismatch");
  const unsigned fallbackGroupAtEntry=fallbackNextGroup;check(dut.tile$fetchCache$fallback$nextGroup==fallbackNextGroup,"fallback group differs from independent accepted-demand alternation");
  const bool specAtEntry=bool(spec);const bool candidateAtEntry=bool(candidate);
  if(kill||f.invalidate){if(spec)spec->stale=true;}
  transport.beginCycle();
  // A final D may produce an ordinary fallback response on this same frame.
  if(w.dv&&w.dr){check(!w.d.denied&&!w.d.corrupt,"fixed original I service unexpectedly asserted error flags");auto t=transport.acceptD(w.d);if(w.d.source<4&&t)expectedPhase[w.d.source]=3;
   if(t&&t->fallback){auto&d=demand(t->ownerSeq);check(d.kind==4,"fallback response without independently classified demand");setReturnedData(t->ownerSeq,t->words[0]);}}
  unsigned firstComplete=4;for(unsigned i=0;i<4;++i)if(f.phase[i]==3){firstComplete=i;break;}
  if(firstComplete<4){unsigned expected=heldCompletion?*heldCompletion:firstComplete;check(f.engine_completion_source==expected,"engine complete selection changed or lost held owner");if(!f.engine_completion_fire)heldCompletion=expected;}
  if(f.engine_completion_fire){check(!f.cache_fire,"profile forbids simultaneous refill completion and cache acceptance");check(firstComplete<4,"engine completion without old-current complete slot");auto t=transport.complete(unsigned(f.engine_completion_source),unsigned(f.engine_completion_tag),bool(f.engine_completion_error));expectedPhase[t.source]=0;heldCompletion.reset();completion(f,t);
   if(t.tag==1){check(spec.has_value(),"missing optional owner on terminal");if(f.observed_spec_write_classification){check(!t.error&&!spec->stale&&eligible(spec->owner,kill),"unauthorized/stale/error speculative installation");++specInstalls;}}
   if(f.actual_cache_data_write_enable){check(!t.error&&!f.invalidate,"cache writes error/invalidated refill");check(f.writtenWords==t.words,"actual cache data bank write differs from checked line");check(f.writeSet==((t.address>>6)&255)&&f.writeWay<2&&f.writeTag==((t.address>>14)&0x7ffff)&&f.writeValidNext,"actual cache tag/valid install mismatch");
    check(bool(f.observed_spec_write_classification)==bool(t.tag==1),"write classified against wrong engine tag");auto &entry=cache[f.writeSet][f.writeWay];if(entry.valid&&entry.speculative&&!entry.used)++unusedEvictions;entry={true,t.tag==1,false,t.address,t.ownerSeq,t.words};}
   if(t.tag==1)spec.reset();
  }else check(!f.actual_cache_data_write_enable&&!f.observed_spec_write_classification&&!f.observed_demand_write_classification,"cache write without actual engine completion");
  if(f.invalidate)for(auto&set:cache)for(auto&e:set){if(e.valid&&e.speculative&&!e.used)++unusedInvalidations;e.valid=false;}
  if(f.physical_response_fire){check(!returnOrder.empty()&&activeCache&&returnOrder.front()==*activeCache&&f.physical_response_sequence==*activeCache,"physical response lost full ordered owner");auto&d=demand(*activeCache);check(d.data.has_value(),"physical reply precedes independently established payload");check(f.physical_response_mask==d.owner.mask,"physical response mask mismatch");d.physicalDone=true;returnOrder.pop_front();activeCache.reset();++physicalCompleted;}
  if(f.virtual_response_valid){check(!virtualOrder.empty()&&virtualOrder.front()==f.virtual_response_sequence,"virtual result order/full64 mismatch");auto&d=demand(virtualOrder.front());check(d.physicalDone||d.owner.mask==0,"virtual reply before physical obligation");check(!(f.virtual_response_errors&d.owner.mask)&&!(f.virtual_response_pages&d.owner.mask),"fixed M/Bare demand fault");if(d.owner.mask){check(d.data.has_value(),"virtual reply missing golden response payload");for(unsigned i=0;i<2;++i)if((d.owner.mask>>i)&1)check(uint32_t(f.virtual_response_data>>(32*i))==uint32_t(*d.data>>(32*i)),"virtual reply byte/owner mismatch");}owners.erase(d.owner.seq);virtualOrder.pop_front();++result;}
  if(f.virtual_valid){Owner o=owner(n,f.virtual_pc,f.virtual_mask);check(!(o.pc&7)&&o.mask<=3,"original virtual packet shape");if(heldVirtual)check(*heldVirtual==o,"first public held offer changed");check(f.command_pc==o.pc&&f.command_mask==o.mask&&f.command_privilege==3&&f.command_satp==0&&f.command_identity,"first-offer command context changed");if(f.held){check(heldVirtual&&f.held_token==o.seq&&f.held_virtualAddress==o.pc&&f.held_requestMask==o.mask&&f.held_privilege==3&&f.held_satp==0,"held first-offer captured context mismatch");}
   if(f.virtual_fire){check(owners.emplace(n,Demand{o}).second,"reused virtual full sequence");virtualOrder.push_back(n);++n;heldVirtual.reset();}else heldVirtual=o;
  }else check(!heldVirtual,"public held offer withdrawn");
  if(f.physical_upstream_valid){auto&d=demand(f.physical_upstream_sequence);check(f.physical_upstream_pc==d.owner.pc&&f.physical_upstream_mask==d.owner.mask&&f.physical_upstream_privilege==3&&f.physical_upstream_identity,"physical command lost frozen full owner/context");if(f.physical_upstream_fire){check(!d.upstream,"duplicate physical command owner");check(bufferOrder.size()<2,"buffer borrowed a same-frame pop instead of old capacity");d.upstream=true;bufferOrder.push_back(d.owner.seq);returnOrder.push_back(d.owner.seq);++physicalAccepted;}}
  std::optional<Owner> acceptedCache;
  if(f.cache_valid){Owner o=owner(f.cache_sequence,f.cache_pc,f.cache_mask);check(!bufferOrder.empty()&&bufferOrder.front()==o.seq,"cache offered owner not accepted buffer head");auto&d=demand(o.seq);check(o==d.owner&&f.cache_privilege==3&&f.cache_identity,"cache frozen context differs from originating demand");if(heldCache)check(*heldCache==o,"cache held offer/context changed");
   if(f.cache_fire){check(!activeCache&&!d.cache,"cache demand ownership overlap");bufferOrder.pop_front();activeCache=o.seq;d.cache=true;acceptedCache=o;heldCache.reset();
    const bool allowed=inRam(line(o.pc),64)&&o.mask==3&&!(o.pc&7);check(bool(f.cache_line_allowed)==allowed,"independent whole-line policy mismatch");
    CachedLine*hit=nullptr;if(!f.invalidate)for(auto&e:cache[(o.pc>>6)&255])if(e.valid&&e.line==line(o.pc))hit=&e;
    check(bool(f.cache_hit)==bool(hit),"cache hit lacks independently installed line generation");
    if(allowed&&hit){d.kind=1;d.data=hit->words[(o.pc>>3)&7];if(hit->speculative){hit->used=true;++specHits;}}
    else if(allowed&&spec&&spec->line==line(o.pc)&&!spec->stale&&!f.invalidate&&contextAgeEligible(spec->owner,kill)&&contextAgeEligible(o,kill)){d.kind=3;d.source=spec->source;spec->used=true;++joins;check(f.cache_state_next==4,"authorized join did not preserve waitPrefetch owner");}
    else d.kind=allowed?2:4;
   }else heldCache=o;
  }else check(!heldCache,"held cache demand withdrawn");
  if(f.engine_request_fire){unsigned slot=unsigned(f.engine_allocated_source),tag=unsigned(f.engine_request_tag_next_array);check(tag<=1,"unexpected engine tag");uint64_t seq=0;
   if(tag==1){check(candidate&&!specAtEntry&&!spec&&eligible(candidate->owner,kill)&&f.engine_request_address==candidate->line,"optional engine reservation lacks prior independent authorized candidate");seq=candidate->owner.seq;spec=*candidate;spec->source=slot;candidate.reset();}
   else{check(bool(activeCache),"demand fill lacks active cache owner");auto&d=demand(*activeCache);check(d.kind==2&&!d.source&&f.engine_request_address==line(d.owner.pc),"demand fill owner/address mismatch");seq=d.owner.seq;d.source=slot;}
   transport.reserve(slot,seq,f.engine_request_address,tag);expectedPhase[slot]=1;
  }
  // Fallback A may be offered before cache acceptance: authorize its immutable
  // current buffer owner and word mask, never merely a mapped address.
  if(w.av&&w.a.source>=4&&!transport.hasSource(w.a.source)){
   check(f.cache_valid&&!f.cache_line_allowed,"fallback offer lacks lawful current demand");auto&d=demand(f.cache_sequence);check(d.upstream&&d.owner.pc==f.cache_pc&&d.owner.mask==f.cache_mask&&d.owner.mask,"fallback origin mismatch");
   const unsigned group=fallbackGroupAtEntry;const unsigned low=d.owner.mask==3?0:unsigned((d.owner.mask>>1)&1);const unsigned size=d.owner.mask==3?3:2;const uint64_t address=d.owner.pc+(d.owner.mask==2?4:0);
   check(w.a.source==(4u|(group<<1)|low)&&w.a.address==address&&w.a.size==size,"fallback source/word selection differs from known demand");
   transport.permitExplicitFallback(d.owner.seq,w.a.source,address,size);
  }
  if(acceptedCache&&demand(acceptedCache->seq).kind==4&&acceptedCache->mask)fallbackNextGroup^=1;
  check(dut.tile$fetchCache$fallback$nextGroup$NEXT==fallbackNextGroup,"fallback projected group mismatch");
  transport.offerA(w.av,w.ar,w.a);if(w.av&&w.ar&&w.a.source<4)expectedPhase[w.a.source]=2;
  if(specAtEntry&&spec&&acceptedCache){bool ahead=false;for(unsigned i=0;i<=4;++i)ahead|=line(acceptedCache->pc)<=UINT64_MAX-i*64&&line(acceptedCache->pc)+i*64==spec->line;if(!ahead)spec->stale=true;}
  // Observe candidate selection, then prove it came from this accepted demand.
  if(f.candidate_valid_next){
   if(candidate){check(f.candidate_seq_next==candidate->owner.seq&&f.candidate_line_next==candidate->line,"live candidate overwritten");check(!kill&&!f.invalidate,"cancelled candidate retained");}
   else{check(!candidateAtEntry&&!specAtEntry&&acceptedCache&&eligible(*acceptedCache,kill)&&!spec,"new candidate lacks free old credit/independent demand");check(f.candidate_seq_next==acceptedCache->seq&&f.candidate_line_next==line(acceptedCache->pc)+64,"new candidate provenance/next-line mismatch");candidate=OptionalOwner{*acceptedCache,f.candidate_line_next};++seeds;}
  }else if(candidate){check(kill||f.invalidate||!eligible(candidate->owner,false)||(acceptedCache&&line(acceptedCache->pc)==candidate->line),"candidate disappeared without known cancellation or engine acceptance");candidate.reset();++seedCancels;}
  if(kill){check(n-(f.virtual_fire?1:0)<=UINT64_MAX-f.virtual_valid,"uncovered cutoff overflow");cutoff=n-(f.virtual_fire?1:0)+f.virtual_valid;}
  check(n!=UINT64_MAX,"fixed CPU suite approached unqualified sequence-wrap scope");
  check(f.virtual_next_sequence==n&&f.virtual_expected_result_next==result&&f.cutoff_next==cutoff,"projected full64 counter/cutoff mismatch");check(f.phaseNext==expectedPhase,"projected fill phase mismatch");
  transport.endCycle();previous=f;havePrevious=true;
  check(owners.size()<=2&&bufferOrder.size()<=2&&returnOrder.size()<=2,"accepted owner capacity exceeded");
 }
 void finish(){transport.assertDrained();check(ownEmpty()&&n==result&&physicalAccepted==physicalCompleted,"unfinished CPU fetch provenance obligation");uint64_t unusedResident=0;for(const auto&set:cache)for(const auto&e:set)unusedResident+=e.valid&&e.speculative&&!e.used;auto c=transport.counters();std::cout<<"CPU_PREFETCH_AUDIT_PASS virtual="<<n<<" physical="<<physicalAccepted<<" seeds="<<seeds<<" candidate_cancels="<<seedCancels<<" demand_line_A="<<c.lineA-c.specReservations<<" spec_reservations="<<c.specReservations<<" total_I_A="<<c.acceptedA<<" requested_payload_bytes="<<c.requestedBytes<<" returned_wire_bytes="<<c.returnedWireBytes<<" total_I_D="<<c.acceptedD<<" installs="<<specInstalls<<" joins="<<joins<<" speculative_hits="<<specHits<<" stale_drops="<<staleDrops<<" errors="<<specErrors<<" unused_evictions="<<unusedEvictions<<" unused_invalidations="<<unusedInvalidations<<" unused_resident="<<unusedResident<<" wrap_observed=0 scope=fixed_M_Bare_guest_provenance\n";}
};
}
