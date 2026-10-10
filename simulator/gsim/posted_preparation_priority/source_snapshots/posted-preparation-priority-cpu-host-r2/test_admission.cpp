#include "admission_model_adapter.hpp"
#include <functional>
#include <iostream>
#include <vector>
using namespace admission;
static unsigned rejected=0;
void reject(const std::function<void()>&f){bool ok=false;try{f();}catch(const std::runtime_error&){ok=true;}need(ok,"negative control escaped");++rejected;}
struct Fake {
 Sample s;bool trip=true;unsigned tagReads=0;
 void guard(bool v)const{if(trip)need(v,"invalid payload getter called");}
 uint64_t reset()const{return s.reset;}uint64_t cacheValid()const{return s.valid;}uint64_t cacheReady()const{return s.ready;}uint64_t cpuFire()const{return s.cpuFire;}
 uint64_t ordinary()const{guard(s.valid);return s.ordinary;}uint64_t address()const{guard(s.valid);return s.address;}uint64_t write()const{guard(s.valid);return s.write;}uint64_t hint()const{guard(s.valid);return s.hint;}
 uint64_t lastValid()const{return s.lastValid;}uint64_t lastLine()const{guard(s.lastValid);return s.lastLine;}
 uint64_t postedPrefetchAllowed()const{return s.postedAllowed;}uint64_t liveOwner()const{return s.live;}uint64_t releaseBusy()const{return s.release;}uint64_t flush()const{return s.flush;}uint64_t origin()const{return s.origin;}uint64_t events()const{return s.events;}
 uint64_t candidateValid()const{return s.cv;}uint64_t candidateAddress()const{guard(s.cv);return s.ca;}uint64_t candidateStore()const{guard(s.cv);return s.cs;}uint64_t pfIndex()const{guard(s.cv);return s.pi;}uint64_t canAllocate()const{guard(s.cv);return s.can;}uint64_t freeMshr()const{guard(s.allocated());return s.freeMshr;}
 uint64_t candidateRemaining()const{guard(s.cv);return s.remaining;}
 uint64_t trackedValid()const{return s.tracked;}uint64_t trackedAddress()const{guard(s.tracked);return s.trackedAddress;}uint64_t trackedIndex()const{guard(s.tracked);return s.trackedIndex;}uint64_t observedTrackedStore()const{guard(s.tracked);return s.trackedStore;}uint64_t consume()const{return s.consume;}
 uint64_t phase(unsigned i)const{return s.mshrs[i].phase;}uint64_t prefetchOwner(unsigned i)const{guard(s.mshrs[i].phase);return s.mshrs[i].pf;}uint64_t storePrefetchOwner(unsigned i)const{guard(s.mshrs[i].phase&&s.mshrs[i].pf);return s.mshrs[i].store;}uint64_t pendingAddress(unsigned i)const{guard(s.mshrs[i].phase);return s.mshrs[i].address;}uint64_t pendingIndex(unsigned i)const{guard(s.mshrs[i].phase);return s.mshrs[i].index;}
 uint64_t wbLive(unsigned)const{return 0;}uint64_t wbPrefetch(unsigned)const{guard(false);return 0;}uint64_t wbAddress(unsigned)const{guard(false);return 0;}
 uint64_t valid(unsigned i)const{guard((s.tracked&&i==s.trackedIndex)||s.cv);return s.cv?s.wayValid[i>>8]:(s.tracked&&i==s.trackedIndex&&s.trackedPresent);}
 uint64_t dirty(unsigned i)const{guard(s.cv&&s.wayValid[i>>8]);return s.wayDirty[i>>8];}uint64_t candidateTags(unsigned w)const{guard(s.cv&&s.wayValid[w]);return s.wayTag[w];}
 uint64_t needsMissSlot()const{guard(s.valid);return 0;}uint64_t reservedSet()const{guard(s.valid);return 0;}uint64_t barrierRequest()const{guard(s.valid);return 0;}
 uint64_t evictionState()const{guard(s.cv);return s.evictionState;}uint64_t queuedEvictWanted()const{guard(s.cv);return s.queuedEvict;}
 uint64_t barrier()const{guard(s.cv);return 0;}uint64_t flushActive()const{guard(s.cv);return 0;}uint64_t bypassState()const{guard(s.cv);return 0;}uint64_t probeState()const{guard(s.cv);return 0;}uint64_t tlBValid()const{guard(s.cv);return 0;}
};

Sample idle(){Sample s;s.postedAllowed=true;return s;}
void refresh(Sample&s){
 if(s.cv){s.gates=s.deriveGates();s.can=s.allocationBin()==N;s.origin=(s.origin&~12U)|(s.can?(s.cs?8:4):0);}
 s.events=(bool(s.origin&3)?1:0)|(bool(s.origin&12)?2:0)|(bool(s.origin&48)?4:0);
}
void block(Sample&s,unsigned gate){
 switch(gate){
 case 0:s.postedAllowed=false;break;
 case 1:s.live=true;s.mshrs[0]={2,17,true,false,0x80200440};break;
 case 2:s.release=true;s.wbs[0]={true,true,0x80200880};break;
 case 3:s.wayValid[0]=s.victimValid=true;s.wayTag[0]=s.ca>>14;s.victimAddress=s.ca;break;
 case 4:s.mshrs[0]={2,s.pi,false,false,s.ca+0x4000};break;
 case 5:s.wbs[0]={true,false,s.ca};break;
 case 6:s.wayValid[0]=s.wayDirty[0]=s.victimValid=s.victimDirty=true;s.wayTag[0]=(s.ca+0x4000)>>14;s.victimAddress=s.ca+0x4000;break;
 case 7:s.mshrs[0]={2,17,false,false,0x80200440};s.mshrs[1]={2,18,false,false,0x80200480};break;
 case 8:s.valid=s.ordinary=s.write=true;s.address=0x80203000;break;
 case 9:s.barrier=true;break;
 case 10:s.flushActive=true;break;
 case 11:s.flush=true;break;
 case 12:s.bypassState=1;break;
 case 13:s.probeState=1;break;
 case 14:s.tlB=true;break;
 case 15:s.evictionState=1;break;
 case 16:s.queuedEvict=true;break;
 }
 refresh(s);
}
// Expected times are chosen from absolute source/birth offsets, not a loop that
// calls the implementation's retain() predicate. The final attempt is #Lifetime.
std::vector<Sample> scenario(bool store,unsigned attempts,bool allocate,unsigned gate=15){
 need(attempts>=1&&attempts<=Lifetime,"fixture attempts");
 std::vector<Sample> v(attempts+4,idle());
 for(unsigned j=0;j<2;++j){auto&s=v[j];s.valid=s.ready=s.cpuFire=s.ordinary=s.hint=true;s.write=store;s.address=0x80200000+64*j;s.origin=j?(store?2:1):0;refresh(s);}
 for(unsigned j=0;j<attempts;++j){auto&s=v[j+2];s.cv=true;s.cs=store;s.ca=0x80200080;s.pi=2;s.remaining=Lifetime-1-j;
  if(j+1<attempts){s.evictionState=j%2?2:1;refresh(s);}else if(allocate)refresh(s);else block(s,gate);
 }
 auto&post=v[attempts+2];if(allocate){post.mshrs[0]={2,2,true,store,0x80200080};post.live=true;}
 // The observer must never infer an uninitialized history payload.
 bool valid=false;uint64_t line=0;
 for(auto&s:v){s.lastValid=valid;s.lastLine=valid?line:0;if(s.flush){valid=false;line=0;}else if(s.readFire()){valid=true;line=s.address>>6;}}
 return v;
}
void play(const std::vector<Sample>&v,bool output=false,unsigned enter=0,unsigned leave=10000){Observer o;for(unsigned i=0;i<v.size();++i)o.sample(v[i],10+i,i>=enter&&i<leave);std::ostringstream sink;o.finish(output?std::cout:sink);}
void guarded(){
 Fake f;readAccess(f);f.s.reset=true;readAccess(f);f.s=idle();f.s.valid=true;f.s.address=0x80200000;f.s.ordinary=true;readAccess(f);
 f.s=idle();f.s.tracked=true;f.s.trackedAddress=0x80200000;f.s.trackedIndex=0;f.s.trackedPresent=true;readAccess(f);
 f.s=idle();f.s.mshrs[0]={4,3,false,false,0x802000c0};readAccess(f);
 f.s=idle();f.s.cv=f.s.can=true;f.s.ca=0x80200000;f.s.pi=0;f.s.origin=4;f.s.events=2;readAccess(f);
 f.s=idle();f.s.cv=f.s.can=true;f.s.ca=0x80204000;f.s.pi=256;f.s.origin=4;f.s.events=2;
 f.s.tracked=true;f.s.trackedStore=true;f.s.trackedAddress=0x80208000;f.s.trackedIndex=256;f.s.trackedPresent=true;
 f.s.wayValid={true,true};f.s.wayDirty={true,false};f.s.wayTag={0x80200000ULL>>14,0x80208000ULL>>14};
 auto x=readAccess(f);need(x.victimAddress==0x80208000&&!x.victimDirty&&x.trackedStore,"clean tracked-store victim fixture");
}
int main(int argc,char**argv){try{
 if(argc>1){auto v=scenario(false,Lifetime,true);std::string mode=argv[1];
  if(mode=="fixture_store"){play(scenario(true,Lifetime,true),true);return 0;}
  if(mode=="fixture_expire"){play(scenario(false,Lifetime,false),true);return 0;}
  if(mode=="fixture_carry"){play(v,true,2,3);return 0;}
  if(mode=="fixture_flush"){auto q=scenario(false,1,false,11);play(q,true);return 0;}
  if(mode=="fixture_birth_flush"){auto q=scenario(false,1,true);q[1].flush=true;for(unsigned i=2;i<q.size();++i)q[i]=idle();play(q,true);return 0;}

  if(mode=="poison_refresh")v[2].remaining=Lifetime;
  else if(mode=="poison_overdue"){auto late=v[v.size()-3];late.remaining=0;v.insert(v.end()-2,late);}
  else if(mode=="poison_origin")v[2].cs=true;
  else if(mode=="poison_payload")v[0].trackedAddress=99;
  else throw std::runtime_error("unknown poison mode");
  play(v);return 0;
 }
 guarded();
 // All raw vetoes are independently reconstructed; every one kills retention.
 for(unsigned gate=0;gate<N;++gate){auto v=scenario(false,1,false,gate);if(gate==15&&Lifetime>1)v=scenario(false,Lifetime,false,gate);play(v);
  auto bad=v;bad[2].can=true;bad[2].origin=4;bad[2].events=2;reject([&]{play(bad);});}
 // A page-end accepted read with denied current hint creates no candidate.
 {auto q=scenario(false,1,true);q[0].address=0x80200f80;q[1].address=0x80200fc0;q[1].hint=false;q[1].origin=0;q[1].events=0;q[1].lastLine=q[0].address>>6;
  for(unsigned i=2;i<q.size();++i){q[i]=idle();q[i].lastValid=true;q[i].lastLine=0x80200fc0ULL>>6;}play(q);
  q[1].origin=1;q[1].events=1;reject([&]{play(q);});}
 // Store same-line prediction never latches authorization: a denied advance is
 // followed by a newly authorized same-line accepted store, which may emit.
 {auto q=scenario(true,Lifetime,true);auto retry=q[1];q[1].hint=false;q[1].origin=0;q[1].events=0;q.insert(q.begin()+2,retry);play(q);
  q[2].hint=false;reject([&]{play(q);});}
 // Exact last legal attempt can allocate even with remaining=0; capture then is terminal.
 play(scenario(false,Lifetime,true));play(scenario(false,Lifetime,false));play(scenario(true,Lifetime,true));
 auto base=scenario(false,Lifetime,true);
 for(const auto&mut:std::vector<std::function<void(std::vector<Sample>&)>>{
  [](auto&x){x[2].ca+=64;},[](auto&x){x[2].cs=true;},
  [](auto&x){x[2]=idle();x[2].lastValid=true;x[2].lastLine=0x80200040ULL>>6;},
  [](auto&x){x[2].remaining=Lifetime;},
  [](auto&x){x[1].origin=0;x[1].events=0;},
  [](auto&x){x[1].hint=false;},
  [](auto&x){x[0].lastLine=99;},[](auto&x){x[0].trackedAddress=99;},[](auto&x){x[0].ca=99;},
  [](auto&x){x[2].address=99;},[](auto&x){x[2].write=true;},
  [](auto&x){x[x.size()-3].origin=0;x[x.size()-3].events=0;},
  [](auto&x){x[x.size()-2].mshrs[0].address+=64;},
  [](auto&x){x[x.size()-2].mshrs[0].store=true;},
  [](auto&x){x[x.size()-2].mshrs[0].phase=0;},
  [](auto&x){x[2].lastLine++;},
  [](auto&x){auto late=x[x.size()-3];late.remaining=0;x.insert(x.end()-2,late);}
 }){auto v=base;mut(v);reject([&]{play(v);});}
 {Observer o;o.sample(base[0],10,true);reject([&]{o.sample(base[1],12,true);});}
 if(Lifetime>1){
  // No refresh even when a current same-line request has its own valid hint.
  auto v=base;v[3].valid=v[3].ready=v[3].cpuFire=v[3].ordinary=v[3].hint=true;v[3].address=0x80200040;refresh(v[3]);play(v);
  v[3].remaining++;reject([&]{play(v);});
  // Every non-eviction gate cancels after a legal retention, too.
  for(unsigned gate=0;gate<N;++gate)if(gate!=15){auto q=scenario(false,2,false,gate);play(q);q.insert(q.end()-2,q[3]);reject([&]{play(q);});}
  auto ack=scenario(false,1,false);ack[2].evictionState=3;refresh(ack[2]);play(ack);
 }
 // Explicit pending carry into and out of ROI; terminal accounting uses offer ROI.
 play(base,false,2,3);
 // Final trace includes a source-origin useful event after allocation.
 auto fixture=scenario(false,Lifetime,true);auto&u=fixture.back();u.valid=u.ready=u.cpuFire=u.ordinary=true;u.address=0x80200080;u.tracked=u.trackedPresent=u.consume=true;u.trackedAddress=u.address;u.trackedIndex=2;u.origin=16;refresh(u);
 auto final=idle();final.lastValid=true;final.lastLine=u.address>>6;fixture.push_back(final);
 play(fixture,true);std::cout<<"CONTROLS rejected="<<rejected<<" invalid_payload_getters_guarded=1 lifetime="<<Lifetime<<" deadline_attempts="<<Lifetime<<"\n";
 return 0;
 }catch(const std::exception&e){std::cerr<<"ADMISSION_REJECT "<<e.what()<<"\n";return 1;}}
