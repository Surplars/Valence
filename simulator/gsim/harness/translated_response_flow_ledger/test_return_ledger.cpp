#include "cpu_flow_bandwidth.h"
#include <functional>
#include <sstream>
using L=FlowDataPathOwnershipLedger;using P=DataPathSample;
static unsigned positive=0,negative=0;
static void must(bool b,const char*why){if(!b)throw std::runtime_error(why);}
static void bit(P&p,P::Event n,bool b=true){if(b)p.events|=1ULL<<n;else p.events&=~(1ULL<<n);}
static void bit(BackendSample&s,unsigned n,bool b=true){if(b)s.events|=1ULL<<n;else s.events&=~(1ULL<<n);}
static L::Transaction transaction(unsigned n,bool write=false,bool buffered=false,bool fault=false,bool pageFault=false){
 DataPathRequest r{0x80220000ULL+n*8,0x8bcde10000000000ULL+n,uint64_t(write)|(3ULL<<7)|(255ULL<<9)};
 return {{0x100000000ULL+n,n&15},r,r,buffered,fault,pageFault,0};
}
struct Fixture{
 L l;P p;BackendSample s;BackendOwnershipLedger b;
 Fixture(unsigned queued,unsigned pending,bool write=false,bool buffered=false,unsigned flags=0,bool fault=false,bool pageFault=false){
  must(queued+pending<=4,"fixture owner capacity");
  for(unsigned i=0;i<queued+pending;++i){
   auto t=transaction(i+1,write,buffered,fault,pageFault);l.storeOwners.push_back(t);
   if(buffered)l.stores.push_back({t,true});
   if(i<queued)l.returns.push_back({t,{0xdecaf00000000000ULL+i,flags}});
   else {l.owners.push_back(t);if(!fault)l.physicalPending.push_back(t);}
  }
  unsigned total=queued+pending;
  for(auto key:{"store_request","virtual_request","physical_ingress_pass","checked_pop"})l.counters[key]=total;
  l.counters["physical_request"]=fault?0:total;l.counters["physical_reply"]=fault?0:queued;
  l.counters["virtual_reply"]=l.counters["return_push"]=queued;
  l.counters["buffered_accept"]=buffered?total:0;
  l.conservation();begin();
 }
 void begin(){
  p={};s={};b={};l.flowEvents=1ULL<<6;
  p.count={unsigned(l.stores.size()),l.issued(),unsigned(l.storeOwners.size()),l.directOutstanding(),0,0,0,unsigned(l.owners.size()),unsigned(l.returns.size())};
  bit(p,P::ownerValid,!l.storeOwners.empty());if(!l.storeOwners.empty())bit(p,P::ownerBuffered,l.storeOwners.front().buffered);
  if(!l.owners.empty())bit(p,P::ownerFault,l.owners.front().fault);
  unsigned slot=0;for(const auto&t:l.storeOwners)if(!t.buffered){b.responses.push_back({t.token,BackendOwnershipLedger::downstream});s.live[slot]=true;s.slots[slot]=t.token;s.phase[slot]=2;++slot;}
 }
 void input(uint64_t data=0x123456789abcdef0ULL,unsigned flags=0){
  bit(p,P::virtualReply);if(!l.owners.front().fault){bit(p,P::physicalReply);p.reply[0]=p.reply[1]={data,flags};}
  else p.reply[1]={0,uint64_t(1|(l.owners.front().pageFault?2:0))};
 }
 void output(bool empty){
  bit(p,P::storeResponse);p.reply[2]=p.reply[3]=empty?p.reply[1]:l.returns.front().reply;
  if(!l.storeOwners.front().buffered){bit(s,24);bit(s,25);p.reply[4]=p.reply[3];}
 }
 void valid(){l.validate(s,p,b);++positive;}
 void advance(){l.advance(s,p,b);}
};
static void reject(const char*name,const Fixture&base,const std::function<void(Fixture&)>&mutate,const char*reason){
 Fixture f=base;f.valid();const auto oldEvents=f.p.events;const auto oldReply=f.p.reply;const auto oldCount=f.p.count;
 mutate(f);
 must(oldEvents!=f.p.events||oldReply!=f.p.reply||oldCount!=f.p.count||f.s.events!=base.s.events||f.s.slots!=base.s.slots||f.l.returns.size()!=base.l.returns.size(),"poison did not change a signal/state");
 try{f.l.validate(f.s,f.p,f.b);}catch(const std::runtime_error&e){must(std::string(e.what()).find(reason)!=std::string::npos,e.what());++negative;std::cout<<"REJECT "<<name<<" reason="<<e.what()<<"\n";return;}
 throw std::runtime_error(std::string("poison escaped: ")+name);
}
int main(){try{
 // Every data/error/pageFault tuple is preserved for direct load and direct store.
 for(bool write:{false,true})for(unsigned flags=0;flags<4;++flags){Fixture f(0,1,write,false);f.input(0x9900000000000000ULL+flags,flags);f.output(true);f.valid();f.advance();must(f.l.returns.empty()&&f.l.owners.empty()&&f.l.storeOwners.empty()&&f.l.value("return_empty_pass")==1,"empty pass not exactly once");f.l.conservation();}
 for(bool pf:{false,true}){Fixture f(0,1,false,false,0,true,pf);f.input();f.output(true);f.valid();f.advance();must(f.l.returns.empty()&&f.l.storeOwners.empty(),"fault owner leak");}
 // Accepted held input must capture once; later dequeue retains full payload.
 for(unsigned flags=0;flags<4;++flags){Fixture f(0,1);f.input(0xabc0000000000000ULL+flags,flags);bit(f.p,P::returnPush);f.valid();f.advance();must(f.l.returns.size()==1&&f.l.value("return_empty_capture")==1&&f.l.value("return_empty_pass")==0,"held misclassified");f.begin();f.output(false);bit(f.p,P::returnPop);f.valid();f.advance();must(f.l.returns.empty()&&f.l.storeOwners.empty(),"held response leak");}
 // Older registered head wins over simultaneous new input; new data remains queued.
 Fixture old(1,1);old.input(0xbeef0001,3);old.output(false);bit(old.p,P::returnPush);bit(old.p,P::returnPop);old.valid();
 reject("old-head-new-input-reorder",old,[](auto&f){f.p.reply[2]=f.p.reply[3]=f.p.reply[4]=f.p.reply[1];},"relocated return payload corruption");
 old.advance();must(old.l.returns.size()==1&&old.l.returns.front().reply==DataPathReply{0xbeef0001,3}&&old.l.value("return_empty_pass")==0&&old.l.value("return_old_head_transfer")==1,"old-pop/new-push order");old.begin();old.output(false);bit(old.p,P::returnPop);old.valid();old.advance();must(old.l.returns.empty()&&old.l.storeOwners.empty(),"old/new drain leak");
 // Full pre-edge queue cannot accept input even when an old response drains.
 Fixture full(2,1);full.output(false);bit(full.p,P::returnPop);full.valid();reject("full-pop-illegal-admission",full,[](auto&f){f.input();bit(f.p,P::returnPush);},"pre-edge queue credit");full.advance();must(full.l.returns.size()==1,"full pop incorrect");
 Fixture pass(0,1);pass.input();pass.output(true);pass.valid();
 reject("phantom-empty-pass",pass,[](auto&f){bit(f.p,P::virtualReply,false);bit(f.p,P::physicalReply,false);},"relocated return/StoreBuffer response route");
 reject("pass-double-dequeue",pass,[](auto&f){bit(f.p,P::returnPop);},"relocated return/StoreBuffer response route");
 reject("pass-duplicate-capture",pass,[](auto&f){bit(f.p,P::returnPush);},"relocated return enqueue route");
 reject("pass-wrong-data",pass,[](auto&f){f.p.reply[2].data^=1;},"relocated return payload");
 reject("pass-wrong-error",pass,[](auto&f){f.p.reply[2].flags^=1;},"relocated return payload");
 reject("pass-wrong-pagefault",pass,[](auto&f){f.p.reply[2].flags^=2;},"relocated return payload");
 reject("pass-backend-token",pass,[](auto&f){f.s.slots[0].tag^=1ULL<<48;},"backend return full-token lineage");
 reject("pass-backend-omitted",pass,[](auto&f){bit(f.s,25,false);},"direct return lost ordered backend");
 reject("unqualified-foreign-fp",pass,[](auto&f){bit(f.p,P::foreignResponse);},"foreign FP/system traffic");
 reject("wrong-preedge-count",pass,[](auto&f){f.p.count[8]=1;},"pre-edge count corruption");
 Fixture held(0,1);held.input(0x314159,3);bit(held.p,P::returnPush);held.valid();
 reject("held-input-false-pass",held,[](auto&f){bit(f.p,P::returnPush,false);},"relocated return enqueue route");
 reject("held-input-phantom-pop",held,[](auto&f){bit(f.p,P::returnPop);},"relocated return/StoreBuffer response route");
 Fixture queued(1,0);queued.output(false);bit(queued.p,P::returnPop);queued.valid();
 reject("queued-dropped-pop",queued,[](auto&f){bit(f.p,P::returnPop,false);},"relocated return/StoreBuffer response route");
 reject("queued-dropped-output",queued,[](auto&f){bit(f.p,P::storeResponse,false);},"relocated return/StoreBuffer response route");
 // Accepted posted store has two distinct obligations: the early local ACK
 // releases the backend token, and the later physical response releases store
 // ownership. Exercise both actual advance() edges independently.
 Fixture posted(0,1,true,true);const auto postedOwner=posted.l.storeOwners.front();
 posted.l.localReply=L::Returned{postedOwner,{0,0}};posted.l.counters["local_accept"]=1;
 posted.b.responses.push_back({postedOwner.token,BackendOwnershipLedger::localReply});
 posted.s.live[0]=true;posted.s.slots[0]=postedOwner.token;posted.s.phase[0]=2;
 bit(posted.p,P::storeAckValid);bit(posted.s,40);bit(posted.s,24);bit(posted.s,25);
 posted.p.reply[4]={0,0};posted.valid();posted.advance();
 must(!posted.l.localReply&&posted.l.value("local_reply")==1&&posted.l.stores.size()==1&&posted.l.owners.size()==1,"local ACK lost later physical obligation");
 posted.begin();posted.input(0);posted.output(true);posted.valid();
 reject("posted-ack-repeated-at-return",posted,[](auto&f){bit(f.s,24);bit(f.s,25);},"backend response has no live full-token slot");
 reject("guaranteed-posted-store-fault",posted,[](auto&f){f.p.reply[0].flags=f.p.reply[1].flags=f.p.reply[2].flags=f.p.reply[3].flags=1;},"guaranteed buffered store received fault");
 posted.advance();must(posted.l.stores.empty()&&posted.l.storeOwners.empty()&&posted.l.value("buffered_response")==1&&posted.l.value("local_accept")==1&&posted.l.value("local_reply")==1,"posted owner/ACK not drained exactly once");
 // Duplicate after actual drain has no queue or physical owner and must fail.
 pass.advance();pass.begin();bit(pass.p,P::storeResponse);bit(pass.p,P::returnPop);
 try{pass.l.validate(pass.s,pass.p,pass.b);throw std::runtime_error("duplicate passed");}catch(const std::runtime_error&e){must(std::string(e.what()).find("registered return dequeue underflow")!=std::string::npos,e.what());++negative;}
 std::cout<<"PASS_RETURN_FLOW_LEDGER_CONTROLS positive="<<positive<<" negative="<<negative<<" error_tuples=4 direct_load_store=1 local_faults=2 held_capture_then_pop=4 old_pop_new_push=1 full_pop=1 posted_ack=1\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL_RETURN_FLOW_LEDGER_CONTROLS "<<e.what()<<"\n";return 1;}}
