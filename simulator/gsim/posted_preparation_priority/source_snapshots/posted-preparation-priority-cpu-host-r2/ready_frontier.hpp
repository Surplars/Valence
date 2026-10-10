#pragma once
#include "unissued_model_adapter.hpp"
#include <sstream>
namespace frontier {
using canonical_overlap::need;using canonical_overlap::Token;
inline void token(std::ostream&o,Token t){o<<'['<<t.index<<','<<t.tag<<']';}
struct Operand {bool known=false,ready=false,initialized=false;unsigned source=0,bank=0;uint64_t value=0;};
template<class D> Operand operand(D&d,unsigned source,bool registeredReady,bool ownerReady,bool live){
 Operand x;need(source<64,"frontier operand range");x.source=source;x.ready=registeredReady;
 need(!live||registeredReady==ownerReady,"frontier registered readiness mismatch");
 if(!live||!registeredReady||!ownerReady)return x;
 if(!source){x.known=true;return x;}
 x.initialized=d.board$platform$core$core$core$backend$physicalFile$initialized[source];
 // The actual PRF defines zero for unwritten locations; never touch a bank.
 if(!x.initialized){x.known=true;return x;}
 x.bank=d.board$platform$core$core$core$backend$physicalFile$owner[source];need(x.bank<2,"frontier bank range");
 x.value=x.bank?d.board$platform$core$core$core$backend$physicalFile$banks_1[source]:d.board$platform$core$core$core$backend$physicalFile$banks_0[source];x.known=true;return x;
}
inline bool proof(Token owner,uint64_t epoch,uint64_t va,unsigned size,bool addressKnown,const canonical_overlap::Sample&c){
 return addressKnown&&c.preparedValid&&c.prepared==owner&&c.preparedEpoch==epoch&&c.preparedVa==va&&c.preparedSize==size&&c.preparedAllowed;
}
#if MEMORY_PROOF_FRONTIER_ON
struct StagingOwner { bool valid=false; Token token{}; };
template<class D> StagingOwner stagingOwner(D&d,const unissued::Sample&u){
 StagingOwner result;
 if(!d.board$platform$core$core$core$backend$stagedMemoryValid)return result;
 Token saved{d.board$platform$core$core$core$backend$stagedMemoryMetadata$$renamed$$token$$index,d.board$platform$core$core$core$backend$stagedMemoryMetadata$$renamed$$token$$tag};
 need(saved.index<64,"frontier staged index range");
 const auto&owner=u.owners[saved.index];
 if(!owner.live||!owner.pending||!owner.memoryLive||!owner.memory||owner.killed||owner.token!=saved)return result;
 result.valid=true;result.token=saved;return result;
}
#endif
class Observer {
 std::ofstream log;bool opened=false,seen=false,ended=false;uint64_t previous=0,sequence=0,begin=0,end=0,cycles=0;
 std::array<std::string,64> old{};std::array<Token,64> owners{};std::string oldContext;
 void row(const char*event,uint64_t cycle,const std::string&tail){log<<"{\"event\":\""<<event<<"\",\"sequence\":"<<sequence++<<",\"cycle\":"<<cycle<<tail<<"}\n";}
 public:
 template<class D> void sample(D&d,const unissued::Sample&u,const canonical_overlap::Sample&c,uint64_t cycle,bool roi){
  if(!opened){const char*p=std::getenv("READY_LOAD_FRONTIER_TRACE");need(p&&*p,"frontier trace required");log.open(p);need(bool(log),"frontier trace open");opened=true;}
  need(!seen||cycle==previous+1,"frontier duplicate/missing sample");seen=true;previous=cycle;
  if(!roi){if(cycles)ended=true;return;}need(!ended&&!c.reset,"frontier disjoint/reset ROI");if(!cycles)begin=cycle;end=cycle+1;++cycles;
  for(unsigned i=0;i<64;++i){const auto&x=u.owners[i];bool live=x.live&&x.memory;
   if(!old[i].empty()&&(!live||owners[i]!=x.token)){std::ostringstream o;o<<",\"token\":";token(o,owners[i]);row("leave",cycle,o.str());old[i].clear();}
   if(!live)continue;need(x.token.index==i&&x.age< u.robCount,"frontier live token");owners[i]=x.token;
   std::ostringstream o;o<<",\"token\":";token(o,x.token);o<<",\"state\":{\"epoch\":"<<c.epoch<<",\"pc\":"<<x.pc<<",\"pending\":"<<x.pending<<",\"memory_live\":"<<x.memoryLive<<",\"store\":"<<x.store<<",\"atomic\":"<<x.atomic<<",\"killed\":"<<x.killed<<",\"memory_canonical\":"<<x.memoryCanonical<<",\"destination\":"<<x.destination<<",\"writes_rd\":"<<x.writesRd;
   if(x.sourcesKnown){
    need(x.pending,"frontier invalid pending payload");auto p=operand(d,x.source1,x.prfReady1,x.ready1,!x.killed&&x.memoryLive);
    const auto imm=(i&1)?d.board$platform$core$core$core$backend$payload_1$immediateBank1[i>>1]:d.board$platform$core$core$core$backend$payload_1$immediateBank0[i>>1];
    const unsigned size=d.board$platform$core$core$core$backend$queue$$request$$memorySize[i];need(size<=3,"frontier payload size");
    o<<",\"source1\":"<<x.source1<<",\"source2\":"<<x.source2<<",\"ready1\":"<<x.ready1<<",\"ready2\":"<<x.ready2<<",\"prf_ready1\":"<<x.prfReady1<<",\"prf_ready2\":"<<x.prfReady2<<",\"initialized\":"<<p.initialized<<",\"bank\":";if(p.known&&p.source&&p.initialized)o<<p.bank;else o<<"null";
    o<<",\"operand\":";if(p.known)o<<p.value;else o<<"null";o<<",\"immediate\":"<<imm<<",\"size\":"<<size<<",\"va\":";if(p.known)o<<uint64_t(p.value+imm);else o<<"null";
    o<<",\"actual_positive_proof\":"<<proof(x.token,c.epoch,p.value+imm,size,p.known,c);
    if(!x.store&&!x.atomic&&c.choiceValid&&c.choice==x.token&&p.known){need(d.board$platform$core$core$core$backend$stagedMemoryAddress==uint64_t(p.value+imm),"frontier selected VA/payload mismatch");need(d.board$platform$core$core$core$backend$stagedMemorySize==size,"frontier selected size mismatch");}
   }else{o<<",\"source1\":null,\"source2\":null,\"ready1\":null,\"ready2\":null,\"prf_ready1\":null,\"prf_ready2\":null,\"initialized\":null,\"bank\":null,\"operand\":null,\"immediate\":null,\"size\":null,\"va\":null,\"actual_positive_proof\":0";}
   o<<",\"store_address_known\":"<<x.addressKnown<<",\"store_prepared\":"<<x.prepared<<",\"store_va\":";if(x.addressKnown)o<<x.va;else o<<"null";o<<'}';
   auto state=o.str();if(state!=old[i]){row("owner",cycle,state);old[i]=state;}
  }
  std::ostringstream o;o<<",\"state\":{\"head\":"<<u.head<<",\"count\":"<<u.robCount<<",\"epoch\":"<<c.epoch<<",\"stable\":"<<c.stable<<",\"choice\":";if(c.choiceValid){token(o,c.choice);}else o<<"null";
  o<<",\"choice_prechecked\":"<<c.choicePrechecked<<",\"start_fire\":"<<(c.startValid&&c.startReady)<<",\"physical_conflict\":"<<c.physicalConflict<<",\"older_uncanonical\":"<<c.olderUncanonical<<",\"issue_available\":"<<c.issueAvailable<<",\"no_other_serial\":"<<c.noOtherSerial<<",\"older_system\":"<<c.olderSystem;
#if MEMORY_PROOF_FRONTIER_ON
  const auto staged=stagingOwner(d,u);o<<",\"staging\":";if(staged.valid){o<<"{\"token\":";token(o,staged.token);o<<",\"va\":"<<d.board$platform$core$core$core$backend$stagedMemoryAddress<<",\"size\":"<<unsigned(d.board$platform$core$core$core$backend$stagedMemorySize)<<'}';}else o<<"null";
#else
  const bool stage=d.board$platform$core$core$core$backend$stagedMemoryValid;o<<",\"staging\":";if(stage){o<<"{\"token\":";token(o,{d.board$platform$core$core$core$backend$stagedMemoryToken$$index,d.board$platform$core$core$core$backend$stagedMemoryToken$$tag});o<<",\"va\":"<<d.board$platform$core$core$core$backend$stagedMemoryAddress<<",\"size\":"<<unsigned(d.board$platform$core$core$core$backend$stagedMemorySize)<<'}';}else o<<"null";
#endif
  const bool query=d.get_mpQueryValid();o<<",\"query\":";if(query){o<<"{\"token\":["<<unsigned(d.get_mpQueryIndex())<<','<<d.get_mpQueryTag()<<"],\"epoch\":"<<d.get_mpQueryEpoch()<<",\"va\":"<<d.get_mpQueryVa()<<",\"size\":"<<unsigned(d.get_mpQuerySize())<<",\"response_valid\":"<<unsigned(d.get_mpQueryHit())<<'}';}else o<<"null";
  o<<",\"translated\":null,\"prepared\":null";
  o<<",\"store_certificate\":";if(c.record.valid){o<<"{\"token\":";token(o,c.record.token);o<<",\"epoch\":"<<c.record.epoch<<",\"va\":"<<c.record.va<<",\"pa\":"<<c.record.pa<<",\"size\":"<<c.record.size<<'}';}else o<<"null";o<<'}';
  auto state=o.str();if(state!=oldContext){row("context",cycle,state);oldContext=state;}
 }
 void finish(std::ostream&o){need(cycles&&end-begin==cycles,"frontier ROI conservation");log<<"{\"event\":\"terminal\",\"sequence\":"<<sequence<<",\"roi_first\":"<<begin<<",\"roi_end\":"<<end<<",\"roi_cycles\":"<<cycles<<"}\n";log.flush();need(bool(log),"frontier trace write");o<<"READY_LOAD_FRONTIER cycles="<<cycles<<" events="<<sequence<<" passive=1\n";}
};
}
