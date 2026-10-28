// DRAFT: GSIM header binding and behavior NOT executed/qualified.
#include "ContextOwnedInstructionPrefetchGsim.h"
#include "contract_oracle.h"
#include <iostream>
#include <vector>
#include <algorithm>
using namespace independent;
struct Expected { uint64_t address; unsigned size; bool speculative; uint64_t owner; };
struct WireReply {unsigned source, index, size;uint64_t address;bool bad;};
class Run {
 SContextOwnedInstructionPrefetchGsim d;
 std::deque<Expected> expected;
 std::map<uint64_t,Owner> acceptedOwners;
 std::optional<Owner> offered;
 std::optional<WireReply> heldReply;
 bool seedUsed=false,seedAdvertised=false,independentlyDrained=false;
 unsigned clocks=0;
 public:
 Ledger ledger;Pmp pmp{};
 uint64_t cutoff=0;bool age=true,kill=false,aReady=true,serveSpec=true;
 bool corruptFinalSpec=false,injectAddress=false,responseReady=true,invalidate=false;
 std::optional<std::array<uint64_t,3>> heldResponse;
 bool lastIdle=false,lastA=false,lastSpecA=false,lastInstall=false,lastRequestReady=false;
 bool engineReserved=false,engineDone=false,publicSpecSeen=false;
 unsigned engineReservations=0,engineBeforeAPulses=0,specDBeats=0,currentSpecDBeats=0,installs=0,invalidationPulses=0;
 unsigned specHolds=0,killHolds=0,fallbackHolds=0,reverseOverlap=0,responseHolds=0,installBlockedOffers=0;
 Run(){drive({});d.set_reset(1);d.step();d.step();d.set_reset(0);}
 void expect(uint64_t a,unsigned size,bool spec=false,uint64_t owner=UINT64_MAX){independentlyDrained=false;expected.push_back({a,size,spec,owner==UINT64_MAX?ledger.accepted:owner});}
 void request(Owner o){independentlyDrained=false;require(!offered,"host attempted to replace held demand");offered=o;}
 void drive(std::optional<WireReply> r){
  Owner o=offered.value_or(Owner{});
  d.set_io$$fetch$$request$$valid(bool(offered));d.set_io$$fetch$$request$$bits(o.pc);
  d.set_io$$fetch$$requestMask(o.mask);d.set_io$$fetch$$requestContext$$privilege(o.privilege);
  d.set_io$$fetch$$requestContext$$sourceSequence(o.sequence);d.set_io$$fetch$$requestContext$$identityTranslation(o.identity);
  d.set_io$$fetch$$response$$ready(responseReady);d.set_io$$livePrivilege(3);
  d.set_io$$invalidate(invalidate);d.set_io$$kill(kill);d.set_io$$minimumSequence(cutoff);d.set_io$$ageUsable(age);
#define PMP(N) d.set_io$$pmpCfg_##N(pmp[N].cfg);d.set_io$$pmpAddr_##N(pmp[N].addr)
  PMP(0);PMP(1);PMP(2);PMP(3);PMP(4);PMP(5);PMP(6);PMP(7);PMP(8);PMP(9);PMP(10);PMP(11);PMP(12);PMP(13);PMP(14);PMP(15);
#undef PMP
  d.set_io$$tl$$a$$ready(aReady);d.set_io$$tl$$d$$valid(bool(r));
  d.set_io$$tl$$d$$bits$$opcode(1);d.set_io$$tl$$d$$bits$$param(0);d.set_io$$tl$$d$$bits$$sink(0);
  d.set_io$$tl$$d$$bits$$size(r?r->size:0);d.set_io$$tl$$d$$bits$$source(r?r->source:0);
  d.set_io$$tl$$d$$bits$$data(r?bytes((r->address&~7ULL)+r->index*8,8):0);
  d.set_io$$tl$$d$$bits$$denied(0);d.set_io$$tl$$d$$bits$$corrupt(r&&r->bad);
  d.set_io$$tl$$b$$valid(0);d.set_io$$tl$$c$$ready(1);d.set_io$$tl$$e$$ready(1);
 }
 void tick(){
  require(++clocks<2000,"bounded cache script timed out");
  const bool hadObligation=!ledger.demands.empty()||!ledger.inflight.empty()||bool(ledger.held)||(engineReserved&&!engineDone);
  const auto seedBefore=ledger.credit;
  std::optional<WireReply> reply=heldReply;
  // Independent fixed FIFO-by-source service. Directed suppression only withholds
  // a whole speculative reply; once begun there is no payload change while held.
  if(!reply)for(const auto&[source,t]:ledger.inflight)if(!t.speculative||serveSpec){
   reply=WireReply{source,t.beats,t.a.size,t.a.address,t.speculative&&corruptFinalSpec&&t.beats==7};break;
  }
  drive(reply);d.step();
  if(d.get_io$$speculativeRequest()){
   // Observer confirms transport acceptance, never creates optional authority.
   // The complete seed must predate this edge and independently still qualify.
   require(seedBefore&&!seedBefore->stale&&!engineReserved&&!seedUsed,
    "engine reservation without unique prior independent seed");
   const auto&o=seedBefore->owner;
   require(!kill&&!invalidate&&age&&o.identity&&o.sequence>=cutoff&&o.mask==3&&!(o.pc&7)&&
    seedBefore->line==(o.pc&~63ULL)+64&&seedBefore->line>=ram&&seedBefore->line+64<=ram_end&&
    (seedBefore->line>>12)==(o.pc>>12)&&execute(pmp,seedBefore->line,64,o.privilege),
    "engine reservation violates independent live authorization");
   engineReserved=true;++engineReservations;
  }
  if(kill||invalidate)ledger.cancel();
  if(invalidate)++invalidationPulses;
  lastRequestReady=d.get_io$$fetch$$request$$ready();
  lastInstall=d.get_io$$speculativeInstall();
  if(lastInstall){require(engineReserved&&ledger.credit&&!ledger.credit->stale&&!kill&&!invalidate&&age&&ledger.credit->owner.sequence>=cutoff,"stale/unauthorized speculative install");++installs;}
  if(lastInstall&&offered){require(!lastRequestReady,"prefetch install admitted SRAM hit read");++installBlockedOffers;}
  if(offered&&lastRequestReady){
   Owner owner=*offered;owner.ordinal=ledger.accepted;require(acceptedOwners.emplace(owner.ordinal,owner).second,"duplicate accepted ordinal");ledger.demand(owner);
   // Whole-line eligibility additionally requires the physical packet alignment.
   if(!(owner.pc&7))ledger.authorizeSeed(owner,pmp,cutoff,age,kill);
   offered.reset();
  }
  Payload a{d.get_io$$tl$$a$$bits$$address(),d.get_io$$tl$$a$$bits$$data(),
   unsigned(d.get_io$$tl$$a$$bits$$opcode()),unsigned(d.get_io$$tl$$a$$bits$$param()),
   unsigned(d.get_io$$tl$$a$$bits$$size()),unsigned(d.get_io$$tl$$a$$bits$$source()),
   unsigned(d.get_io$$tl$$a$$bits$$mask()),bool(d.get_io$$tl$$a$$bits$$corrupt())};
  lastA=d.get_io$$tl$$a$$valid();lastSpecA=false;
  ledger.offer(lastA,aReady,a);
  if(lastA){
   auto found=std::find_if(expected.begin(),expected.end(),[&](const Expected&e){return e.address==a.address&&e.size==a.size;});
   require(found!=expected.end(),"A not authorized by scripted independent demand/seed expectations");
   lastSpecA=found->speculative;
   if(!lastSpecA){
    const auto accepted=acceptedOwners.find(found->owner);
    const bool sameHeldOffer=offered&&found->owner==ledger.accepted;
    require(accepted!=acceptedOwners.end()||(!aReady&&sameHeldOffer),"demand A lacks accepted ordinal or current held offer");
    const Owner&o=accepted!=acceptedOwners.end()?accepted->second:*offered;
    require((a.size==6&&a.address==(o.pc&~63ULL)&&o.mask==3)||
     (a.size==3&&a.address==o.pc&&o.mask==3)||
     (a.size==2&&a.address==o.pc&&o.mask==1),"A payload mismatches independent ordinal PC/mask");
    if(aReady){require(accepted!=acceptedOwners.end(),"demand A fired without public accepted demand");
     require(std::any_of(ledger.demands.begin(),ledger.demands.end(),[&](const Owner&o){return o.ordinal==found->owner;}),"demand A reused already completed owner");
    }
   }
   if(!lastSpecA&&!aReady&&a.size!=6){++fallbackHolds;if(d.get_io$$speculativeRequest())++reverseOverlap;}
   if(lastSpecA){
    require(ledger.credit&&ledger.credit->owner.ordinal==found->owner&&ledger.credit->line==a.address&&!seedUsed,"extra/chained/repeated speculative A");
    require(engineReserved,"spec A preceded authorized engine reservation");
    // Reservation is irrevocable even if K preceded the first public A.
    
    publicSpecSeen=true;
    seedAdvertised=true;if(!aReady){++specHolds;if(kill)++killHolds;}
   }
   if(aReady){
    if(injectAddress){std::cerr<<"CACHE_OBSERVER_MUTATION_REACHED\n";a.address^=64;}
    ledger.accept(a,found->speculative,found->address,found->size,found->owner);
    if(found->speculative)seedUsed=true;expected.erase(found);
   }
  }
  if(engineReserved&&!publicSpecSeen)++engineBeforeAPulses;
  if(reply&&d.get_io$$tl$$d$$ready()){
   if(ledger.inflight.at(reply->source).speculative){++specDBeats;++currentSpecDBeats;}
   ledger.beat(reply->source);heldReply.reset();
  }
  else heldReply=reply;
  if(d.get_io$$speculativeComplete()){
   require(engineReserved&&!engineDone&&currentSpecDBeats==8,"spec engine completion without exact 8D owner");engineDone=true;
  }
  const bool responseValid=d.get_io$$fetch$$response$$valid();
  const std::array<uint64_t,3> response{uint64_t(d.get_io$$fetch$$response$$bits()),uint64_t(d.get_io$$fetch$$responseError()),uint64_t(d.get_io$$fetch$$responsePageFault())};
  if(responseValid){
   require(!ledger.demands.empty(),"response valid without accepted demand");
   const auto&o=ledger.demands.front();
   require(std::none_of(expected.begin(),expected.end(),[&](const Expected&e){return !e.speculative&&e.owner==o.ordinal;}),
    "response preceded required demand/fallback A");
   require(std::none_of(ledger.inflight.begin(),ledger.inflight.end(),[&](const auto&entry){const auto&t=entry.second;
    return (!t.speculative&&t.ordinal==o.ordinal)||(t.speculative&&t.a.address==(o.pc&~63ULL));}),
    "response preceded owned transport final D");
  }
  if(heldResponse)require(responseValid&&response==*heldResponse,"held demand response data/error changed");
  heldResponse=responseValid&&!responseReady?std::optional<std::array<uint64_t,3>>(response):std::nullopt;
  if(heldResponse){++responseHolds;require(!d.get_io$$idle(),"idle while demand response held");}
  if(responseValid&&responseReady){
   require(!ledger.demands.empty(),"response lacks original demand owner");
   // Partial requests take the ordinary bridge: its contract marks disabled
   // words as errors, not successful instructions. Never waive requested bits.
   const unsigned expectedErrors=(~ledger.demands.front().mask)&3U;
   ledger.response(d.get_io$$fetch$$response$$bits(),d.get_io$$fetch$$responseError(),
    d.get_io$$fetch$$responsePageFault(),expectedErrors,0);
  }
  lastIdle=d.get_io$$idle();
  // A pre-edge pending owner may finish during this step; using the remaining
  // ledger at the cycle entrance is necessary: an idle cache may accept a
  // new demand on this very edge. Do not require busy combinationally on fire.
  if(hadObligation)require(!lastIdle,"cache idle with outstanding independent obligation");
 }
 void accepted(){for(unsigned i=0;i<100&&offered;++i)tick();require(!offered,"demand not accepted");}
 void completed(unsigned n){for(unsigned i=0;i<150&&ledger.completed<n;++i)tick();require(ledger.completed==n,"demand response missing/duplicate");}
 void drain(){for(unsigned i=0;i<150&&(!lastIdle||!ledger.inflight.empty()||!expected.empty()||offered);++i)tick();for(unsigned i=0;i<8;++i)tick();
  require(!offered&&expected.empty()&&lastIdle&&(!engineReserved||engineDone),"cache did not drain/expected transport missing");ledger.drained();independentlyDrained=true;}
 void releaseCompletedSeed(){
  // Independent terminal obligations plus completed quiet drain, never DUT idle alone.
  require(independentlyDrained&&engineReserved&&engineDone&&currentSpecDBeats==8&&
   !offered&&expected.empty()&&!heldReply&&!heldResponse,"host attempted premature credit reuse");
  ledger.drained();ledger.credit.reset();seedUsed=false;seedAdvertised=false;
  engineReserved=false;engineDone=false;publicSpecSeen=false;currentSpecDBeats=0;independentlyDrained=false;
 }
 void releaseUnissuedSeed(){
  // Optional authority may remain unused. Release host bookkeeping only after
  // completed independent demand/TL obligations and an eight-cycle quiet drain.
  require(independentlyDrained&&ledger.credit&&!engineReserved&&!seedUsed&&!seedAdvertised&&
   !publicSpecSeen&&!offered&&expected.empty()&&!heldReply&&!heldResponse,
   "host attempted to release a live or unproved unissued seed");
  ledger.drained();ledger.credit.reset();independentlyDrained=false;
 }
 void stats(const char*name){std::cout<<"CONTEXT_CACHE_PASS case="<<name<<" cycles="<<clocks<<" demands="<<ledger.accepted<<" completed="<<ledger.completed<<" demand_A="<<ledger.demand_gets<<" spec_A="<<ledger.spec_gets<<" D="<<ledger.dbeats<<" engine_reservations="<<engineReservations<<" engine_before_a="<<engineBeforeAPulses<<" spec_D="<<specDBeats<<" installs="<<installs<<" invalidate_pulses="<<invalidationPulses<<" held_spec="<<specHolds<<" killed_held="<<killHolds<<" fallback_held="<<fallbackHolds<<" reverse_overlap="<<reverseOverlap<<" response_held="<<responseHolds<<" install_blocked_offer="<<installBlockedOffers<<'\n';}
};
static void simple(const std::string& name){
 Run r;Owner o{ram,10,3,3,true,0};bool spec=true;
 if(name=="identity-off"){o.identity=false;spec=false;}
 else if(name=="old-sequence"){r.cutoff=11;spec=false;}
 else if(name=="old-sequence-high64"){o.sequence=0x10000000aULL;r.cutoff=0x200000000ULL;spec=false;}
 else if(name=="fresh-sequence-high64"){o.sequence=0x200000000ULL;r.cutoff=0x10000000aULL;}
 else if(name=="age-off"){r.age=false;spec=false;}
 else if(name=="page-end"){o.pc=ram+0xfc0;spec=false;}
 else if(name=="ram-end"){o.pc=ram+0x1fc0;spec=false;}
 else if(name=="s-full-allow"||name=="u-full-allow"||name=="m-locked-napot-allow"){
  o.privilege=name=="s-full-allow"?1:name=="u-full-allow"?0:3;
  r.pmp[0]={unsigned(name=="m-locked-napot-allow"?0x9c:0x1c),(ram/4)|1023};
 }else if(name=="s-tor-next-partial-deny"||name=="u-tor-next-partial-deny"){
  o.privilege=name=="s-tor-next-partial-deny"?1:0;
  r.pmp[0]={0,ram/4};r.pmp[1]={0x0c,(ram+96)/4};spec=false;
 }else if(name=="m-unlocked-napot-deny-bypass"){
  r.pmp[0]={0x18,(ram/4)|1023};
 }else if(name=="m-locked-napot-next-deny"){
  r.pmp[0]={0x98,((ram+64)/4)|7};spec=false;
 }else if(name=="locked-next-deny"){
  // Locked NA4 first match intersects only 4 B of the following line: the
  // entire speculative line must be denied, even though current demand passes.
  r.pmp[0]={0x90,(ram+64)/4};spec=false;
 }else require(name=="basic","unknown simple cache case");
 r.expect(o.pc&~63ULL,6);if(spec)r.expect((o.pc&~63ULL)+64,6,true);
 r.request(o);r.accepted();r.completed(1);r.drain();
 require(r.ledger.spec_gets==(spec?1:0),"spec suppression/one-credit coverage");
 if(name=="basic"){
  require(r.installs==1,"basic optional line was not successfully installed");
  // No A authority is added: a real prefetch hit must deliver original byte
  // contents at a nonzero line offset without demand or optional traffic.
  r.request({ram+72,11,3,3,false,0});r.accepted();r.completed(2);r.drain();
  require(r.ledger.demand_gets==1&&r.ledger.spec_gets==1,"installed prefetched line was not a no-refill hit");
 }
 // With no more demand, drain's eight quiet cycles reject chained prefetches;
 // installed line must not keep idle false forever.
 r.stats(name.c_str());
}
static void heldKill(bool fallback){
 Run r;r.serveSpec=false;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,20,3,3,true,0});r.accepted();
 for(unsigned i=0;i<100&&r.ledger.demand_gets==0;++i)r.tick();
 require(r.ledger.demand_gets==1,"initial demand A missing");r.aReady=false;
 for(unsigned i=0;i<100&&!r.lastSpecA;++i)r.tick();require(r.lastSpecA,"spec A not presented for hold");
 r.completed(1);
 if(fallback){r.expect(0x90000000ULL,2);r.request({0x90000000ULL,21,1,3,false,0});}
 r.kill=true;r.cutoff=22;for(unsigned i=0;i<4;++i)r.tick();
 require(r.killHolds>=4,"kill while spec A held not covered");
 r.aReady=true;r.serveSpec=true;if(fallback)r.accepted();r.drain();require(r.ledger.spec_gets==1,"held spec was retracted");
 // Prove stale line was not installed by demanding it with speculation disabled.
 r.kill=false;r.expect(ram+64,6);r.request({ram+64,23,3,3,false,0});r.accepted();r.completed(fallback?3:2);r.drain();
 r.stats(fallback?"b1-fill-lock-kill":"held-a-kill-stale");
}
static void joinedAfterKill(bool lateError){
 Run r;r.serveSpec=false;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,30,3,3,true,0});r.accepted();r.completed(1);
 for(unsigned i=0;i<100&&r.ledger.spec_gets==0;++i)r.tick();require(r.ledger.spec_gets==1,"spec not inflight for join");
 // No line Get is authorized for the joined packet. The demand must retain its
 // original PC/mask after cancellation and late final-beat corruption.
 r.request({ram+72,31,3,3,true,0});r.accepted();r.kill=true;r.cutoff=32;r.tick();
 if(lateError)r.expect(ram+72,3,false,1);
 r.corruptFinalSpec=lateError;r.serveSpec=true;r.completed(2);r.drain();
 require(r.ledger.completed==2&&r.ledger.demand_gets==(lateError?2:1)&&r.ledger.spec_gets==1,
  "joined after K exact transport/response obligations");r.stats(lateError?"joined-late-error":"joined-success-after-k");
}
static void engineBeforeAKill(){
 Run r;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,35,3,3,true,0});r.accepted();
 for(unsigned i=0;i<100&&!r.engineReserved;++i)r.tick();
 require(r.engineReservations==1&&!r.publicSpecSeen&&r.engineBeforeAPulses>0,
  "hidden engine acceptance before public spec A not reached");
 r.kill=true;r.cutoff=36;r.drain();
 require(r.ledger.spec_gets==1&&r.specDBeats==8&&r.engineDone,"pre-A K lost accepted engine obligation");
 // Stale installation would suppress this required new demand line transport.
 r.kill=false;r.expect(ram+64,6);r.request({ram+64,37,3,3,false,0});r.accepted();r.completed(2);r.drain();r.stats("engine-owned-before-a-kill");
}
static void reverseB1(){
 Run r;r.expect(ram,6);r.request({ram,40,3,3,false,0});r.accepted();r.completed(1);r.drain();
 // Cached hit seeds a new optional line. Next cycle fallback can acquire the
 // external A lock while that seed is only being accepted by the fill engine.
 r.expect(ram+64,6,true);r.request({ram,41,3,3,true,0});r.accepted();
 r.aReady=false;r.expect(0x90000000ULL,2);r.request({0x90000000ULL,42,1,3,false,0});
 for(unsigned i=0;i<6;++i)r.tick();
 require(r.fallbackHolds>=4&&r.reverseOverlap>0,"reverse B1 fallback-lock/fill-overlap not reached");
 r.aReady=true;r.accepted();r.drain();require(r.ledger.completed==3&&r.ledger.spec_gets==1,"reverse B1 conservation");r.stats("b1-fallback-lock");
}
static void responseHold(){
 Run r;r.responseReady=false;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,50,3,3,true,0});r.accepted();
 for(unsigned i=0;i<100&&r.responseHolds<12;++i)r.tick();require(r.responseHolds>=12,"held response not reached");
 r.responseReady=true;r.completed(1);r.drain();r.stats("response-hold");
}
static void installCollision(){
 Run r;r.serveSpec=false;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,60,3,3,true,0});r.accepted();r.completed(1);
 for(unsigned i=0;i<100&&r.ledger.spec_gets==0;++i)r.tick();require(r.ledger.spec_gets==1,"spec not pending for install collision");
 r.serveSpec=true;
 // Continually present known resident demand packets while final prefetch D
 // advances into installation. No additional demand or speculative Get allowed.
 for(unsigned i=0;i<40;++i){r.request({ram,61+i,3,3,false,0});r.accepted();if(r.installBlockedOffers)break;}
 r.drain();require(r.installBlockedOffers>0,"install versus offered cached hit collision not reached");r.stats("install-hit-collision");
}
static void reuseInstalledSeed(){
 Run r;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,110,3,3,true,0});r.accepted();r.completed(1);r.drain();
 require(r.installs==1&&r.ledger.spec_gets==1,"initial unused prefetch install not reached");r.releaseCompletedSeed();
 // +128 is neither the first demanded line nor its unused installed next line.
 r.expect(ram+128,6);r.expect(ram+192,6,true);r.request({ram+128,111,3,3,true,0});r.accepted();r.completed(2);r.drain();
 require(r.engineReservations==2&&r.ledger.spec_gets==2&&r.ledger.demand_gets==2&&r.specDBeats==16&&r.installs==2,
  "single speculative credit failed reuse after unused installed line");r.stats("new-seed-after-unused-install");
}
static void invalidateInstalled(){
 Run r;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,120,3,3,true,0});r.accepted();r.completed(1);r.drain();
 require(r.installs==1,"prefetch install missing before maintenance");
 r.invalidate=true;r.tick();r.invalidate=false;
 r.expect(ram+64,6);r.request({ram+64,121,3,3,false,0});r.accepted();r.completed(2);r.drain();
 require(r.invalidationPulses==1&&r.ledger.demand_gets==2&&r.ledger.spec_gets==1,
  "invalidate failed to remove installed prefetched line");r.stats("invalidate-idle-installed");
}
static void standaloneLateError(){
 Run r;r.corruptFinalSpec=true;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,130,3,3,true,0});r.accepted();r.completed(1);r.drain();
 require(r.installs==0&&r.ledger.completed==1&&r.specDBeats==8&&r.engineDone,
  "standalone speculative error installed or created architectural response");
 r.expect(ram+64,6);r.request({ram+64,131,3,3,false,0});r.accepted();r.completed(2);r.drain();
 require(r.ledger.spec_gets==1&&r.ledger.demand_gets==2,"failed speculative line suppressed later demand refill");r.stats("standalone-spec-late-error");
}
// Establish retained failure from real accepted transport, not from a DUT bit.
// The source line and one different line are independently known resident.
static void prepareRetainedStale(Run&r){
 r.expect(ram+128,6);r.request({ram+128,190,3,3,false,0});r.accepted();r.completed(1);r.drain();
 r.serveSpec=false;r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,200,3,3,true,0});r.accepted();r.completed(2);
 for(unsigned i=0;i<100&&r.ledger.spec_gets==0;++i)r.tick();require(r.ledger.spec_gets==1,"last-stale setup did not accept optional A");
 r.kill=true;r.cutoff=201;r.tick();r.serveSpec=true;r.drain();
 require(r.engineDone&&r.engineReservations==1&&r.specDBeats==8&&r.installs==0&&r.ledger.demand_gets==2,
  "last-stale setup did not establish one drained uninstalled transport");
 r.kill=false;r.releaseCompletedSeed();
}
static void lastStaleHitSuppressed(){
 Run r;prepareRetainedStale(r);
 for(unsigned i=0;i<3;++i){
  // No new A is authorized: this known source hit repeats the failed target.
  r.request({ram+i*8,202+i*2,3,3,true,0});r.accepted();r.completed(3+i*2);r.drain();r.releaseUnissuedSeed();
  // A different known resident source separates the visits. Suppression must
  // survive this source-line change; a per-contiguous-line bit would fail here.
  r.request({ram+128,203+i*2,3,3,false,0});r.accepted();r.completed(4+i*2);r.drain();
 }
 require(r.engineReservations==1&&r.ledger.spec_gets==1&&r.ledger.demand_gets==2,
  "same failed target source hit issued a new optional request");
 // Suppression cannot remove ordinary demand authority for the uncached target.
 r.expect(ram+64,6);r.request({ram+72,209,3,3,false,0});r.accepted();r.completed(9);r.drain();
 require(r.ledger.spec_gets==1&&r.ledger.demand_gets==3&&r.ledger.completed==9,
  "suppressed target lost its independent ordinary demand response");r.stats("last-stale-hit-retry-suppressed");
}
static void lastStaleColdBypass(){
 Run r;prepareRetainedStale(r);r.invalidate=true;r.tick();r.invalidate=false;
 // Same retained failed target, but invalidate removed the source line as well.
 r.expect(ram,6);r.expect(ram+64,6,true);r.request({ram,202,3,3,true,0});r.accepted();r.completed(3);r.drain();
 require(r.invalidationPulses==1&&r.ledger.demand_gets==3&&r.ledger.spec_gets==2&&
  r.engineReservations==2&&r.specDBeats==16&&r.installs==1,
  "cold source miss did not bypass retained-failure suppression");r.stats("last-stale-cold-miss-bypass");
}
static void lastStaleNewTarget(){
 Run r;prepareRetainedStale(r);
 // The different source is already resident: only target inequality permits it.
 r.expect(ram+192,6,true);r.request({ram+128,202,3,3,true,0});r.accepted();r.completed(3);r.drain();
 require(r.ledger.demand_gets==2&&r.ledger.spec_gets==2&&r.installs==1,
  "different optional target was suppressed despite a free credit");r.releaseCompletedSeed();
 // That successful new reservation replaced the one-entry retained failure.
 r.expect(ram+64,6,true);r.request({ram,203,3,3,true,0});r.accepted();r.completed(4);r.drain();
 require(r.ledger.demand_gets==2&&r.ledger.spec_gets==3&&r.engineReservations==3&&
  r.specDBeats==24&&r.installs==2,"new target did not restore old target admission");r.stats("last-stale-new-target-allowed");
}
static void lastStaleResetFirst(){
 Run r;r.expect(ram,6);r.request({ram,299,3,3,false,0});r.accepted();r.completed(1);r.drain();
 // First actual speculation follows a known hit, so the cold-miss bypass cannot
 // disguise a broken reset history state.
 r.expect(ram+64,6,true);r.request({ram,300,3,3,true,0});r.accepted();r.completed(2);r.drain();
 require(r.ledger.completed==2&&r.engineReservations==1&&r.ledger.demand_gets==1&&r.ledger.spec_gets==1&&r.specDBeats==8&&r.installs==1,
  "reset retained failure state suppressed the first lawful seed");r.stats("last-stale-reset-first-seed");
}
int main(int argc,char**argv){try{require(argc==2,"usage: context_cache CASE");std::string n=argv[1];
 if(n=="last-stale-hit-retry-suppressed")lastStaleHitSuppressed();else if(n=="last-stale-cold-miss-bypass")lastStaleColdBypass();else if(n=="last-stale-new-target-allowed")lastStaleNewTarget();else if(n=="last-stale-reset-first-seed")lastStaleResetFirst();else if(n=="standalone-spec-late-error")standaloneLateError();else if(n=="new-seed-after-unused-install")reuseInstalledSeed();else if(n=="invalidate-idle-installed")invalidateInstalled();else if(n=="engine-owned-before-a-kill")engineBeforeAKill();else if(n=="b1-fallback-lock")reverseB1();else if(n=="response-hold")responseHold();else if(n=="install-hit-collision")installCollision();else if(n=="held-a-kill-stale")heldKill(false);else if(n=="b1-fill-lock-kill")heldKill(true);else if(n=="joined-late-error")joinedAfterKill(true);else if(n=="joined-success-after-k")joinedAfterKill(false);else simple(n);
 return 0;}catch(const std::exception&e){std::cerr<<"CONTEXT_CACHE_FAIL "<<e.what()<<'\n';return 1;}}
