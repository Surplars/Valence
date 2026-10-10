#pragma once
#include "unissued_observer.hpp"
namespace robwindow {
using canonical_overlap::Token;using canonical_overlap::need;
struct Rename {bool known=false,dispatchReady=false,recovering=false,tagExhausted=false;std::array<bool,2> offered{},writesRd{},fresh{},registerEnough{},accepted{};};
struct Sample {unsigned occupancy=0,freePhysical=0;Rename rename;};
template<class D> Sample read(D&d){
 Sample s;s.occupancy=d.board$platform$core$core$core$backend$ledger$count;
 for(unsigned i=0;i<capacity::physicalRegs;++i)s.freePhysical+=d.board$platform$core$core$core$backend$ledger$free[i];
 if constexpr(requires {d.get_capacityRobEntries();}){
  need(d.get_capacityRobEntries()==capacity::robEntries&&d.get_capacityRobBits()==capacity::robBits&&d.get_capacityPhysicalRegs()==capacity::physicalRegs&&d.get_capacityLsuEntries()==capacity::lsuEntries,"capacity actual wrapper/profile mismatch");
  need(s.occupancy==d.get_capacityRobOccupancy()&&s.freePhysical==d.get_capacityFreePhysical(),"capacity hierarchical/scalar crosscheck");
  auto&r=s.rename;r.known=true;r.offered={bool(d.get_capacityRenameOffer0()),bool(d.get_capacityRenameOffer1())};if(r.offered[0]){r.writesRd[0]=d.get_capacityRenameWritesRd0();r.fresh[0]=d.get_capacityRenameFresh0();r.registerEnough[0]=d.get_capacityRegisterEnough0();}if(r.offered[1]){r.writesRd[1]=d.get_capacityRenameWritesRd1();r.fresh[1]=d.get_capacityRenameFresh1();r.registerEnough[1]=d.get_capacityRegisterEnough1();}r.accepted={bool(d.get_capacityRenameAccepted0()),bool(d.get_capacityRenameAccepted1())};r.dispatchReady=d.get_capacityDispatchReady();r.recovering=d.get_capacityRecovering();r.tagExhausted=d.get_capacityTagExhausted();
 } else {
#ifdef ROB_CAPACITY_LEGACY_DONOR
  static_assert(capacity::robEntries==16&&capacity::physicalRegs==48);
#else
  static_assert(sizeof(D)==0,"fresh model lacks authoritative capacity scalar ABI");
#endif
 }
 return s;
}
class Observer {
 struct Life {bool live=false,emitted=false;Token token;uint64_t pc=0,first=0;};std::array<Life,capacity::robEntries> lives{};
 std::ofstream log;bool opened=false,seen=false,ended=false;uint64_t last=0,sequence=0,roiFirst=0,roiEnd=0,cycles=0,events=0;
 std::array<uint64_t,capacity::robEntries+1> occupancy{},liveLoads{};std::array<uint64_t,capacity::physicalRegs+1> freePhysical{};
 uint64_t preparedCycles=0,renameKnown=0,offered=0,accepted=0,stalled=0,robFull=0,prfEmpty=0,dispatchBlocked=0,recovering=0,tagExhausted=0,prfShortage=0,freshDemand=0,insufficientLanes=0;
 void emitLife(const char*event,const Life&l,uint64_t cycle,bool roi){log<<"{\"event\":\""<<event<<"\",\"sequence\":"<<sequence++<<",\"cycle\":"<<cycle<<",\"roi\":"<<roi<<",\"token\":["<<l.token.index<<','<<l.token.tag<<"],\"first_seen\":"<<l.first<<",\"pc\":"<<l.pc<<"}\n";++events;}
 template<size_t N> static void hist(std::ostream&o,const std::array<uint64_t,N>&a){o<<'[';for(unsigned i=0;i<a.size();++i){if(i)o<<',';o<<a[i];}o<<']';}
 public:
 void sample(const Sample&s,const unissued::Sample&u,const canonical_overlap::Sample&c,uint64_t cycle,bool roi){
  if(!opened){const auto*p=std::getenv("ROB_WINDOW_TRACE");need(p&&*p,"ROB window trace required");log.open(p);need(bool(log),"ROB window trace open");opened=true;}
  need(!seen||cycle==last+1,"ROB window omitted/duplicate sample");seen=true;last=cycle;
  if(c.reset){lives={};return;}
  need(s.occupancy==u.robCount&&s.occupancy<=capacity::robEntries&&s.freePhysical<=capacity::physicalRegs,"ROB window actual capacity bounds");
  unsigned ordinary=0;for(unsigned i=0;i<capacity::robEntries;++i){const auto&x=u.owners[i];auto&l=lives[i];bool active=x.live&&x.memory&&!x.store&&!x.atomic;
   if(l.live&&(!active||l.token!=x.token)){if(l.emitted)emitLife("left_rob",l,cycle,roi);l={};}
   if(active){need(x.token.index==i,"ROB window token index mismatch");if(!l.live){l={true,false,x.token,x.pc,cycle};}need(l.pc==x.pc,"ROB window immutable PC changed");if(roi&&!l.emitted){emitLife("load_live",l,cycle,roi);l.emitted=true;}ordinary++;}
  }
  if(roi){need(!ended,"ROB window disjoint ROI");if(!cycles)roiFirst=cycle;roiEnd=cycle+1;++cycles;++occupancy[s.occupancy];++freePhysical[s.freePhysical];++liveLoads[ordinary];
   if(c.preparedValid&&c.preparedAllowed&&c.preparedEpoch==c.epoch){need(c.prepared.index<capacity::robEntries,"ROB prepared token index range");const auto&x=u.owners[c.prepared.index];if(x.live&&x.pending&&x.memory&&!x.store&&!x.atomic&&x.token==c.prepared)++preparedCycles;}
   if(s.rename.known){const auto&r=s.rename;++renameKnown;unsigned n=0,a=0,fresh=0,insufficient=0;for(unsigned i=0;i<2;++i){need(!r.accepted[i]||r.offered[i],"rename accepted without offer");n+=r.offered[i];a+=r.accepted[i];if(r.offered[i]){need(!r.fresh[i]||r.writesRd[i],"fresh register without writer");fresh+=r.fresh[i];insufficient+=!r.registerEnough[i];if(!i||r.offered[0])need(r.registerEnough[i]==(fresh<=s.freePhysical),"actual rename fresh/capacity mismatch");need(!r.accepted[i]||r.registerEnough[i],"rename accepted without PRF capacity");}}freshDemand+=fresh;insufficientLanes+=insufficient;prfShortage+=n>a&&insufficient;need(!r.accepted[1]||r.accepted[0],"rename nonprefix acceptance");offered+=n;accepted+=a;stalled+=n>a;robFull+=n>a&&s.occupancy==capacity::robEntries;prfEmpty+=n>a&&s.freePhysical==0;dispatchBlocked+=n>a&&!r.dispatchReady;recovering+=n>a&&r.recovering;tagExhausted+=n>a&&r.tagExhausted;}
  }else if(cycles)ended=true;
 }
 void finish(std::ostream&o){need(cycles&&roiEnd-roiFirst==cycles,"ROB window ROI conservation");
  log<<"{\"event\":\"terminal\",\"sequence\":"<<sequence<<",\"roi_first\":"<<roiFirst<<",\"roi_end\":"<<roiEnd<<",\"roi_cycles\":"<<cycles<<",\"events\":"<<events<<"}\n";log.flush();need(bool(log),"ROB window trace write failed");
  o<<"ROB_WINDOW {\"schema\":1,\"rob_entries\":"<<capacity::robEntries<<",\"physical_regs\":"<<capacity::physicalRegs<<",\"lsu_entries\":"<<capacity::lsuEntries<<",\"roi_first\":"<<roiFirst<<",\"roi_end\":"<<roiEnd<<",\"cycles\":"<<cycles<<",\"rob_occupancy\":";hist(o,occupancy);o<<",\"free_physical\":";hist(o,freePhysical);o<<",\"ordinary_loads_live\":";hist(o,liveLoads);o<<",\"prepared_live_cycles\":"<<preparedCycles<<",\"rename_known_cycles\":"<<renameKnown<<",\"rename_offered_lanes\":"<<offered<<",\"rename_accepted_lanes\":"<<accepted<<",\"rename_stalled_cycles\":"<<stalled<<",\"stalled_with_rob_full\":"<<robFull<<",\"rename_fresh_demand_lanes\":"<<freshDemand<<",\"rename_prf_insufficient_offered_lanes\":"<<insufficientLanes<<",\"stalled_with_prf_shortage\":"<<prfShortage<<",\"stalled_with_prf_empty\":"<<prfEmpty<<",\"stalled_with_dispatch_block\":"<<dispatchBlocked<<",\"stalled_with_recovery\":"<<recovering<<",\"stalled_with_tag_exhausted\":"<<tagExhausted<<",\"causes_overlap\":true,\"missing_rename_cause_is_unknown\":true}\n";
 }
};
}
