#pragma once
#include "admission_observer.hpp"
#include <map>
#include <sstream>
#include <vector>
namespace lru_victim {
using admission::need;
struct Candidate {
 bool valid=false,store=false,allocate=false;unsigned set=0,lru=0,index=0,slot=0;
 uint64_t address=0;std::array<bool,2> wayValid{},wayDirty{};std::array<uint64_t,2> wayPa{};
};
inline unsigned expectedWay(const Candidate& c,bool enabled){
 if(!c.wayValid[0])return 0;if(!c.wayValid[1])return 1;
 if(enabled&&c.store)return c.lru;
 if(!c.wayDirty[0])return 0;if(!c.wayDirty[1])return 1;return c.lru;
}
inline void validate(const Candidate&c,bool enabled){
 if(!c.valid){need(!c.store&&!c.allocate&&!c.address&&!c.set&&!c.lru&&!c.index&&!c.slot,"LRU invalid candidate payload");return;}
 need(c.address%64==0&&c.set==((c.address>>6)&255)&&c.lru<2&&c.index<512&&(c.index&255)==c.set,"LRU candidate geometry");
 for(unsigned w=0;w<2;++w){need(c.wayValid[w]||(!c.wayDirty[w]&&!c.wayPa[w]),"LRU invalid way payload");if(c.wayValid[w])need(c.wayPa[w]%64==0&&((c.wayPa[w]>>6)&255)==c.set,"LRU full PA/set mismatch");}
 need((c.index>>8)==expectedWay(c,enabled),"LRU independently derived victim selection mismatch");
 need(!c.allocate||c.slot<2,"LRU allocation slot range");
}
template<class Access> Candidate candidate(const admission::Sample&s,const Access&a){
 Candidate c;if(s.reset||!s.cv)return c;
 c.valid=true;c.store=s.cs;c.allocate=s.allocated();c.address=s.ca;c.set=(s.ca>>6)&255;c.lru=a.replacement(c.set);c.index=s.pi;if(c.allocate)c.slot=s.freeMshr;
 for(unsigned w=0;w<2;++w){c.wayValid[w]=s.wayValid[w];if(c.wayValid[w]){c.wayDirty[w]=s.wayDirty[w];c.wayPa[w]=(s.wayTag[w]<<14)|(uint64_t(c.set)<<6);}}
 return c;
}
struct Payload {uint64_t data=0,corrupt=0;};
template<class Access> Payload guardedPayload(const Access&a,unsigned opcode,bool channelC){
 const bool carriesData=channelC?(opcode==5||opcode==7):(opcode==1||opcode==5);
 if(!carriesData)return {};return {a.data(),a.corrupt()};
}
struct Event {std::string kind;std::map<std::string,uint64_t> fields;};
struct Touch {unsigned index=0;bool pf=false,storePf=false,posted=false;uint64_t address=0;std::string kind;};
struct Raw {uint64_t cycle=0;bool roi=false;Candidate candidate;std::vector<Touch> touches;std::vector<Event> events;};
class Observer {
 std::ofstream log;bool opened=false,held=false;uint64_t seq=0,last=0,first=0,end=0,roiCycles=0;Raw prior{};
 std::array<unsigned,256> predicted{};std::map<std::string,uint64_t> counts;
 void begin(const std::string&kind,uint64_t cycle){log<<"{\"event\":\""<<kind<<"\",\"sequence\":"<<seq++<<",\"cycle\":"<<cycle;counts[kind]++;}
 void close(){log<<"}\n";}
 void edge(const std::string&kind,const Raw&r){begin(kind,r.cycle+1);log<<",\"offer_cycle\":"<<r.cycle<<",\"accepted_cycle\":"<<r.cycle+1<<",\"roi\":"<<r.roi;}
 void candidateJson(const Candidate&c){
  log<<",\"address\":"<<c.address<<",\"store\":"<<c.store<<",\"set\":"<<c.set<<",\"replacement\":"<<c.lru<<",\"victim_index\":"<<c.index<<",\"victim_way\":"<<(c.index>>8)<<",\"allocate\":"<<c.allocate<<",\"slot\":";
  if(c.allocate)log<<c.slot;else log<<"null";
  log<<",\"ways\":[";for(unsigned w=0;w<2;++w){if(w)log<<',';log<<"{\"valid\":"<<c.wayValid[w]<<",\"dirty\":"<<c.wayDirty[w]<<",\"pa\":";if(c.wayValid[w])log<<c.wayPa[w];else log<<"null";log<<'}';}log<<']';
 }
 public:
 template<class D,class M>void sample(D&d,M&m,const admission::Sample&s,uint64_t cycle,bool roi){
  if(!opened){auto p=std::getenv("STORE_PF_LRU_TRACE");need(p&&*p,"LRU trace required");log.open(p);need(bool(log),"LRU trace open");opened=true;}
  if(s.reset){need(!held,"LRU reset after observed execution");return;}
  if(!held){begin("initial",cycle);log<<",\"policy\":"<<STORE_PF_LRU_VICTIM_ON<<",\"replacement\":[";for(unsigned set=0;set<256;++set){predicted[set]=unsigned(d.board$platform$privateCache$replacement[set]);need(predicted[set]<2,"LRU initial bit width");if(set)log<<',';log<<predicted[set];}log<<']';close();}
  else{
   need(cycle==last+1,"LRU omitted callback edge");
   for(const auto&t:prior.touches){const unsigned set=t.index&255,way=t.index>>8;need(t.index<512,"LRU touch index range");predicted[set]=(t.pf&&!t.storePf&&!t.posted)?way:1-way;edge("touch",prior);log<<",\"kind\":\""<<t.kind<<"\",\"index\":"<<t.index<<",\"pa\":"<<t.address<<",\"prefetch\":"<<t.pf<<",\"store_prefetch\":"<<t.storePf<<",\"posted\":"<<t.posted<<",\"after\":"<<predicted[set];close();}
   for(const auto&t:prior.touches)need(unsigned(d.board$platform$privateCache$replacement[t.index&255])==predicted[t.index&255],"LRU registered bit differs from accepted access/install order");
   if(prior.candidate.valid){edge("candidate",prior);candidateJson(prior.candidate);close();
    if(prior.candidate.allocate){const auto&c=prior.candidate;const auto&owner=s.mshrs[c.slot];need(owner.phase&&owner.pf&&owner.store==c.store&&owner.address==c.address&&owner.index==c.index,"LRU allocation missing exact next-edge MSHR owner");edge("allocation",prior);candidateJson(c);log<<",\"phase\":"<<owner.phase;close();}}
   for(const auto&e:prior.events){edge(e.kind,prior);for(const auto&kv:e.fields)log<<",\""<<kv.first<<"\":"<<kv.second;close();}
  }
  struct Access {D&d;unsigned replacement(unsigned set)const{return unsigned(d.board$platform$privateCache$replacement[set]);}};
  Raw now;now.cycle=cycle;now.roi=roi;now.candidate=candidate(s,Access{d});validate(now.candidate,STORE_PF_LRU_VICTIM_ON);
  if(now.candidate.valid)need(now.candidate.lru==predicted[now.candidate.set],"LRU candidate set bit differs from independently tracked history");
  // Only accepted CPU hits touch replacement; posted hits use their later install.
  if(s.cpuFire&&!d.get_lineage$$owner$$accepted$$valid()&&!d.board$platform$privateCache$bypass&&d.board$platform$privateCache$found){
   Touch t;t.kind="cpu_hit";t.index=unsigned(d.board$platform$privateCache$index);t.address=s.address;now.touches.push_back(t);
  }
  const bool installed=d.get_lineage$$lineWriteValid();
  if(installed){Touch t;t.kind="install";t.posted=d.board$platform$privateCache$postedInstall;t.address=d.get_lineage$$lineWriteAddress();
   if(t.posted)t.index=unsigned(d.board$platform$privateCache$postedInstallIndex);
   else{need(d.board$platform$privateCache$refill,"LRU ordinary install missing accepted refill");unsigned slot=unsigned(d.board$platform$privateCache$fillMshr);need(slot<2&&s.mshrs[slot].phase,"LRU install without live MSHR");t.index=s.mshrs[slot].index;t.pf=s.mshrs[slot].pf;t.storePf=t.pf&&s.mshrs[slot].store;}
   now.touches.push_back(t);
  }
  if(d.board$platform$privateCache$refill){unsigned slot=unsigned(d.board$platform$privateCache$fillMshr);need(slot<2&&s.mshrs[slot].phase,"LRU refill missing owner");now.events.push_back({"refill",{{"slot",slot},{"pa",s.mshrs[slot].address},{"index",s.mshrs[slot].index},{"prefetch",s.mshrs[slot].pf},{"store_prefetch",s.mshrs[slot].store},{"error",d.board$platform$privateCache$engine$io$$response$$bits$$error},{"installed",installed}}});}
  if(d.get_lineage$$tlC$$valid()&&d.get_lineage$$tlC$$ready()){
   const unsigned op=d.get_lineage$$tlC$$bits$$opcode();
   struct CAccess {D&d;uint64_t data()const{return d.get_lineage$$tlC$$bits$$data();}uint64_t corrupt()const{return d.get_lineage$$tlC$$bits$$corrupt();}};
   const auto payload=guardedPayload(CAccess{d},op,true);
   now.events.push_back({"tl_c",{{"opcode",op},{"param",d.get_lineage$$tlC$$bits$$param()},{"source",d.get_lineage$$tlC$$bits$$source()},{"size",d.get_lineage$$tlC$$bits$$size()},{"pa",d.get_lineage$$tlC$$bits$$address()},{"data",payload.data},{"corrupt",payload.corrupt}}});
  }
  if(d.get_lineage$$tlD$$valid()&&d.get_lineage$$tlD$$ready()){
   const unsigned op=d.get_lineage$$tlD$$bits$$opcode();
   struct DAccess {D&d;uint64_t data()const{return d.get_lineage$$tlD$$bits$$data();}uint64_t corrupt()const{return d.get_lineage$$tlD$$bits$$corrupt();}};
   const auto payload=guardedPayload(DAccess{d},op,false);
   now.events.push_back({"tl_d",{{"opcode",op},{"param",d.get_lineage$$tlD$$bits$$param()},{"source",d.get_lineage$$tlD$$bits$$source()},{"size",d.get_lineage$$tlD$$bits$$size()},{"data",payload.data},{"denied",d.get_lineage$$tlD$$bits$$denied()},{"corrupt",payload.corrupt}}});
  }
  if(d.get_io$$ddrAxi$$aw$$valid()&&m.awReady)now.events.push_back({"axi_aw",{{"id",d.get_io$$ddrAxi$$aw$$bits$$id()},{"pa",uint64_t(ramBase)+d.get_io$$ddrAxi$$aw$$bits$$addr()},{"len",d.get_io$$ddrAxi$$aw$$bits$$len()},{"size",d.get_io$$ddrAxi$$aw$$bits$$size()},{"burst",d.get_io$$ddrAxi$$aw$$bits$$burst()}}});
  if(d.get_io$$ddrAxi$$w$$valid()&&m.wReady)now.events.push_back({"axi_w",{{"data",d.get_io$$ddrAxi$$w$$bits$$data()},{"strobe",d.get_io$$ddrAxi$$w$$bits$$strb()},{"last",d.get_io$$ddrAxi$$w$$bits$$last()}}});
  if(m.bValid&&d.get_io$$ddrAxi$$b$$ready())now.events.push_back({"axi_b",{{"id",m.wId},{"error",m.writeError}}});
  if(roi){if(!roiCycles)first=cycle;end=cycle+1;++roiCycles;}
  prior=std::move(now);held=true;last=cycle;
 }
 void finish(std::ostream&o){need(held&&roiCycles&&end-first==roiCycles,"LRU ROI coverage");need(!prior.candidate.allocate&&prior.touches.empty()&&prior.events.empty(),"LRU unaccepted terminal event");begin("terminal",last);log<<",\"roi_first\":"<<first<<",\"roi_end\":"<<end<<",\"roi_cycles\":"<<roiCycles<<",\"policy\":"<<STORE_PF_LRU_VICTIM_ON;close();log.flush();need(bool(log),"LRU trace write");o<<"STORE_PF_LRU_OBSERVER cycles="<<roiCycles<<" events="<<seq<<" policy="<<STORE_PF_LRU_VICTIM_ON<<" passive=1 actual_registered_replacement=1 accepted_next_edge=1\n";}
};
}
