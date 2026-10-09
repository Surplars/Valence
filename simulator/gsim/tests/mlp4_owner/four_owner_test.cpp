#include "backend_ownership_ledger.h"
#include "data_path_ownership_ledger.h"
#include "cpu_flow_bandwidth.h"
#include <functional>
#include <iostream>
#include <vector>
#include <type_traits>

static_assert(BackendSample::ownerCount==4);
static_assert(BackendSample::requestCapacity==4);
static unsigned negatives=0;
static void must(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
static void bit(BackendSample &s,unsigned n){s.events|=1ULL<<n;}
static void bit(DataPathSample &p,DataPathSample::Event n){p.events|=1ULL<<n;}
static void reject(const char *name,const std::function<void()> &fn,const char *message) {
    try{fn();}catch(const std::runtime_error &e){
        if(std::string(e.what()).find(message)==std::string::npos)
            throw std::runtime_error(std::string(name)+": unexpected rejection: "+e.what());
        ++negatives;std::cout<<"REJECT "<<name<<"\n";return;
    }
    throw std::runtime_error(std::string(name)+": corruption silently accepted");
}
static BackendToken token(unsigned n) {return {0x1234567800000001ULL+(uint64_t(n)<<32),7};}
// Explicit stimulus, independent from ledger state. Slot placement, queue count,
// cancellation and expected post-edge phase are chosen by the trace, never read
// from any shadow queue to construct the next observation.
struct Trace {
    BackendOwnershipLedger ledger;
    BackendSample s;
    std::array<bool,4> killed{};
    std::function<void()> observe;
    void tick() {
        if(s.fifoCount)bit(s,22);
        if(observe)observe();
        ledger.advance(s);
        for(unsigned i=0;i<4;++i) {
            killed[i]=killed[i]||s.cancelled[i];
            if(s.phase[i]==3&&killed[i]){s.phase[i]=0;s.live[i]=false;}
        }
        s.events=0;s.cancelled={};
    }
    void start(unsigned slot,BackendToken t,bool accept=true) {
        s.start=s.request=t;for(auto n:{3,8,20,41})bit(s,n);if(accept)bit(s,21);
        tick();s.slots[slot]=t;s.phase[slot]=accept?2:1;s.live[slot]=s.parallel[slot]=true;
        killed[slot]=false;s.fifoCount+=accept;
    }
    void accept(unsigned slot) {
        s.request=s.slots[slot];for(auto n:{20,21,41})bit(s,n);
        tick();s.phase[slot]=2;++s.fifoCount;
    }
    void dequeue() {bit(s,23);tick();--s.fifoCount;}
    void reply(unsigned slot,bool fast=false) {
        s.returnSlot=slot;for(auto n:{24,25,28})bit(s,n);if(fast)bit(s,35);
        tick();s.phase[slot]=fast?0:3;s.live[slot]=!fast;
    }
    void complete(unsigned slot,std::optional<BackendToken> replacement={}) {
        s.complete=s.slots[slot];bit(s,26);bit(s,27);
        if(replacement){s.start=s.request=*replacement;for(auto n:{3,8,20,21,41})bit(s,n);}
        tick();s.phase[slot]=replacement?2:0;s.live[slot]=bool(replacement);
        if(replacement){s.slots[slot]=*replacement;s.parallel[slot]=true;killed[slot]=false;++s.fifoCount;}
    }
    void cancel(unsigned slot) {s.cancelled[slot]=true;tick();}
    void validate() {auto x=ledger;auto v=s;if(v.fifoCount)bit(v,22);x.validate(v);}
    void corrupt(const char *name,const std::function<void(BackendSample &)> &change,const char *why) {
        auto x=ledger;auto v=s;if(v.fifoCount)bit(v,22);change(v);
        reject(name,[&]{x.advance(v);},why);
    }
};
static void allFourAndNegatives() {
    Trace t;
    for(unsigned i=0;i<4;++i)t.start(i,token(i));
    t.validate();must(t.s.liveCount()==4&&t.ledger.responses.size()==4&&t.s.fifoCount==4,"all four full owners missing");
    for(unsigned i:{2,3}) {
        t.corrupt(i==2?"drop_slot2":"drop_slot3",[&](auto &s){s.live[i]=false;s.phase[i]=0;},"slot live owner");
        t.corrupt(i==2?"stale_slot2_generation":"stale_slot3_generation",[&](auto &s){s.slots[i].tag^=1ULL<<60;},"full-token generation");
    }
    t.corrupt("swap_slot2_slot3_tokens",[](auto &s){std::swap(s.slots[2],s.slots[3]);},"full-token generation");
    t.corrupt("duplicate_full_token",[](auto &s){s.slots[3]=s.slots[2];},"duplicate live full token");
    t.corrupt("hidden_fifth_start",[](auto &s){s.start=token(9);bit(s,3);},"no independently available slot");
    t.corrupt("premature_completion",[](auto &s){s.complete=s.slots[2];bit(s,26);bit(s,27);},"completion lacks");
    for(unsigned i=0;i<4;++i)t.dequeue();
    t.cancel(2); // after downstream acceptance; still an outstanding read
    t.corrupt("wrong_return_slot3",[](auto &s){s.returnSlot=3;for(auto n:{24,25,28})bit(s,n);},"response full-token owner corruption");
    t.reply(0);t.complete(0,token(4)); // same-cycle old completion/new generation
    t.corrupt("replacement_keeps_stale_generation",[](auto &s){s.slots[0]=token(0);},"full-token generation");
    t.dequeue();
    t.reply(1,true); // fast load consumes response and physical LSU slot at once
    t.reply(2);t.tick(); // cancelled read returns, then discard frees done slot
    t.reply(3);
    t.corrupt("double_slot3_return",[](auto &s){s.returnSlot=3;for(auto n:{24,25,28})bit(s,n);},"response lacks response-phase");
    t.corrupt("release_before_completion",[](auto &s){s.live[3]=false;s.phase[3]=0;},"slot live owner");
    t.complete(3);t.reply(0);t.complete(0);t.tick();
    must(t.ledger.enqueues==5&&t.ledger.returns==5&&t.ledger.responses.empty()&&t.s.liveCount()==0,"four-owner drain conservation");
    t.corrupt("hidden_request_owner",[](auto &s){s.live[3]=true;s.phase[3]=1;s.slots[3]=token(10);},"slot live owner");
    t.corrupt("hidden_result_owner",[](auto &s){s.live[2]=true;s.phase[2]=3;s.slots[2]=token(10);},"slot live owner");
}
static void simultaneousQueueTransfer() {
    Trace t;t.start(0,token(50));
    t.s.start=t.s.request=token(51);for(auto n:{3,8,20,21,23,41})bit(t.s,n);t.tick();
    t.s.slots[1]=token(51);t.s.live[1]=t.s.parallel[1]=true;t.s.phase[1]=2;
    // Non-flow FIFO popped the OLD request; count stays one.
    t.validate();t.dequeue();t.reply(0);t.complete(0);t.reply(1);t.complete(1);t.tick();
    must(t.ledger.simultaneous==1&&t.ledger.returns==2,"same-cycle queue replacement lost ownership");
}
static void stalledAndCancelBeforeIssue() {
    Trace t;t.start(0,token(20),false);
    t.corrupt("stalled_owner_generation",[](auto &s){s.request=token(21);for(auto n:{20,41})bit(s,n);},"stalled request full-token");
    t.corrupt("stalled_request_vanished",[](auto &s){s.request=token(20);},"stalled request full-token");
    // A cancelled, unaccepted request remains stable until accepted and returned.
    t.s.request=token(20);bit(t.s,20);bit(t.s,41);t.s.cancelled[0]=true;t.tick();
    t.s.request=token(20);bit(t.s,20);bit(t.s,41);t.tick();
    t.accept(0);t.dequeue();t.reply(0);t.tick();t.validate();
    must(t.ledger.returns==1&&t.s.liveCount()==0,"preissue cancellation lost drain");
    Trace fault;fault.s.start=token(30);bit(fault.s,3);fault.tick();
    fault.s.slots[0]=token(30);fault.s.live[0]=true;fault.s.phase[0]=3;
    fault.complete(0);fault.tick();must(fault.ledger.enqueues==0,"immediate fault generated request");
    Trace forwarded;forwarded.s.start=token(31);bit(forwarded.s,3);bit(forwarded.s,36);forwarded.tick();
    forwarded.s.slots[0]=token(31);forwarded.s.live[0]=true;forwarded.s.phase[0]=3;
    forwarded.cancel(0);forwarded.tick();must(forwarded.s.liveCount()==0,"forwarded cancellation retained result");
    Trace reset;reset.start(0,token(40));reset.s.reset=true;reset.tick();reset.s={};reset.killed={};reset.tick();
    must(reset.ledger.resetRequestDrops==1&&reset.ledger.resetResponseDrops==1,"reset drops not exact");
}

using P=DataPathSample;
// Model stimulus has its own named states and request/reply fixtures. It never
// reads either ledger to synthesize signals. Two-entry ingress/checked/return
// limits are asserted separately from the four-entry backend owner/FIFO limit.
template<class Ledger> struct PathTrace {
    enum Stage { absent,fifo,ingress,translated,checked,physical,returned,done };
    struct Item {Stage stage=absent;DataPathRequest request;DataPathReply reply;};
    Trace backend;Ledger ledger;P p;
    std::array<Item,4> items;
    static constexpr bool flow=std::is_same_v<Ledger,FlowDataPathOwnershipLedger>;
    PathTrace() {
        for(unsigned i=0;i<4;++i)items[i]={absent,{0x80200000ULL+8*i,0,(3ULL<<7)|(255ULL<<9)},{0xfeed000000000000ULL+i,0}};
        backend.observe=[&]{configure();ledger.advance(backend.s,p,backend.ledger);};
    }
    unsigned count(Stage stage) const {unsigned n=0;for(auto &x:items)n+=x.stage==stage;return n;}
    int first(Stage stage) const {for(unsigned i=0;i<4;++i)if(items[i].stage==stage)return int(i);return -1;}
    void begin() {
        p={};
        unsigned downstream=0;for(auto &x:items)downstream+=x.stage>=ingress&&x.stage<=returned;
        p.count={0,0,downstream,downstream,count(ingress),count(translated),count(checked),count(physical),count(returned)};
        must(p.count[4]<=2&&p.count[6]<=2&&p.count[8]<=2,"two-entry adapter boundary overflow in stimulus");
        if(downstream)bit(p,P::ownerValid);
        for(auto [stage,port]:{std::pair{fifo,P::fifoDeq},{ingress,P::incoming},{translated,P::translatedDeq},{checked,P::checkedDeq}}) {
            int i=first(stage);if(i>=0)p.request[port]=items[i].request;
        }
    }
    void configure() {
        if constexpr(flow) {
            // PHYSICAL_INGRESS_FLOW remains disabled; selected identity shortcut enabled.
            ledger.flowEvents=(uint64_t(p.bit(P::virtualRequest))<<0)|(uint64_t(count(checked)<2)<<6);
            bool identity=p.bit(P::incomingRequest)&&count(translated)==0&&count(checked)<2;
            ledger.flowEvents|=(uint64_t(identity)<<4)|(uint64_t(p.bit(P::incomingRequest))<<5)|
                (uint64_t(identity||p.bit(P::translatedPop))<<3);
            ledger.ingressAuth=p.request[P::virtualIn].meta;
            int held=first(checked);if(held>=0)ledger.checkedHeadAuth=ledger.physicalAuth=items[held].request.meta|(1ULL<<52);
            int added=identity?first(ingress):p.bit(P::translatedPop)?first(translated):-1;
            if(added>=0){auto r=items[added].request;ledger.checkedAuth=r.meta|(1ULL<<52);ledger.checkedAddress=r.address;ledger.checkedData=r.data;}
        }
    }
    void start(unsigned i) {begin();p.request[P::fifoEnq]=items[i].request;backend.start(i,token(i));items[i].stage=fifo;}
    void send(unsigned i) {begin();bit(p,P::storeRequest);bit(p,P::virtualRequest);p.request[P::storePhysical]=p.request[P::virtualIn]=items[i].request;backend.dequeue();items[i].stage=ingress;}
    void translate(unsigned i) {
        begin();bit(p,P::incomingRequest);
        if constexpr(!flow){bit(p,P::translatedPush);p.request[P::translatedEnq]=items[i].request;}
        backend.tick();items[i].stage=flow?checked:translated;
    }
    void check(unsigned i) {begin();bit(p,P::translatedPop);backend.tick();items[i].stage=checked;}
    void launch(unsigned i) {begin();bit(p,P::checkedPop);bit(p,P::physicalRequest);p.request[P::physical]=items[i].request;backend.tick();items[i].stage=physical;}
    void returnPhysical(unsigned i) {begin();for(auto n:{P::virtualReply,P::physicalReply,P::returnPush})bit(p,n);p.reply[0]=p.reply[1]=items[i].reply;backend.tick();items[i].stage=returned;}
    void returnBackend(unsigned i) {begin();bit(p,P::storeResponse);bit(p,P::returnPop);p.reply[2]=p.reply[3]=p.reply[4]=items[i].reply;backend.reply(i);items[i].stage=done;}
    void complete(unsigned i) {begin();backend.complete(i);}
    void cancel(unsigned i) {begin();backend.cancel(i);}
    void idle() {begin();backend.tick();}
    void corrupt(const char *name,const std::function<void(P &)> &change,const char *why) {
        begin();configure();auto altered=p;change(altered);
        reject(name,[&]{ledger.validate(backend.s,altered,backend.ledger);},why);
    }
};
template<class Ledger> static void fourPhysicalPaths() {
    PathTrace<Ledger> f;
    for(unsigned i=0;i<4;++i)f.start(i);
    f.corrupt("stalled_fifo_payload",[](auto &p){p.request[P::fifoDeq].data^=1;},"FIFO dequeue fingerprint");
    f.cancel(2); // cancellation before physical issue retains the token
    for(unsigned i=0;i<4;++i) {
        f.send(i);
        f.corrupt("stalled_ingress_payload",[](auto &p){p.request[P::incoming].address^=8;},"translation incoming fingerprint");
        f.translate(i);if constexpr(!PathTrace<Ledger>::flow)f.check(i);
        f.corrupt("stalled_checked_payload",[](auto &p){p.request[P::checkedDeq].meta^=1ULL<<9;},"checked dequeue fingerprint");
        f.launch(i);
    }
    f.cancel(3); // cancellation after physical issue also drains
    must(f.ledger.physicalPending.size()==4,"physical shadow dropped upper owners");
    f.begin();f.configure();
    auto swapped=f.ledger;std::swap(swapped.physicalPending[2],swapped.physicalPending[3]);
    reject("swapped_physical_upper_tokens",[&]{swapped.validate(f.backend.s,f.p,f.backend.ledger);},"ordered physical full-token lineage");
    auto stale=f.ledger;stale.physicalPending[3].token.tag^=1ULL<<60;
    reject("stale_physical_upper_generation",[&]{stale.validate(f.backend.s,f.p,f.backend.ledger);},"ordered physical full-token lineage");
    auto hidden=f.ledger;hidden.physicalPending.push_back(hidden.physicalPending.back());
    reject("hidden_extra_physical_owner",[&]{hidden.validate(f.backend.s,f.p,f.backend.ledger);},"physical owner conservation");
    for(unsigned i=0;i<4;++i) {
        f.returnPhysical(i);
        f.begin();bit(f.p,P::storeResponse);bit(f.p,P::returnPop);
        f.p.reply[2]=f.p.reply[3]=f.p.reply[4]=f.items[i].reply;
        auto s=f.backend.s;s.returnSlot=i;for(auto n:{24,25,28})bit(s,n);f.configure();
        if(i>=2) {
            auto wrong=s;wrong.slots[i].tag-=1ULL<<32;
            reject("upper_return_stale_generation",[&]{f.ledger.validate(wrong,f.p,f.backend.ledger);},"backend return full-token lineage");
            auto wrongPayload=f.p;wrongPayload.reply[4].data^=1;
            reject("upper_return_payload",[&]{f.ledger.validate(s,wrongPayload,f.backend.ledger);},"backend/local reply payload");
        }
        f.returnBackend(i);
        if(i<2)f.complete(i);else f.idle();
    }
    f.idle();f.ledger.conservation();
    must(f.ledger.physicalPending.empty()&&f.ledger.storeOwners.empty()&&f.backend.s.liveCount()==0,"four-path drain incomplete");
    must(f.ledger.value("physical_request")==4&&f.ledger.value("physical_reply")==4,"four-path physical conservation");
    must(f.ledger.value("cancelled_owner_cycles")==2,"upper cancellation observations dropped");
}
template<class Ledger> static void stalledEnqueueFingerprint() {
    PathTrace<Ledger> f;f.begin();f.p.request[P::fifoEnq]=f.items[0].request;
    f.backend.start(0,token(0),false);
    f.begin();f.p.request[P::fifoEnq]=f.items[0].request;bit(f.backend.s,20);bit(f.backend.s,41);f.configure();
    auto changed=f.p;changed.request[P::fifoEnq].data^=1;
    reject("stalled_enqueue_data",[&]{f.ledger.validate(f.backend.s,changed,f.backend.ledger);},"stalled request fingerprint");
    changed=f.p;changed.request[P::fifoEnq].meta^=1ULL<<9;
    reject("stalled_enqueue_mask",[&]{f.ledger.validate(f.backend.s,changed,f.backend.ledger);},"stalled request fingerprint");
    auto owner=f.backend.s;owner.request.tag^=1ULL<<60;
    reject("stalled_enqueue_generation",[&]{f.ledger.validate(owner,f.p,f.backend.ledger);},"stalled request full-token");
    f.backend.tick(); // unchanged held payload remains accepted by the observer
    f.begin();f.p.request[P::fifoEnq]=f.items[0].request;f.backend.accept(0);f.items[0].stage=PathTrace<Ledger>::fifo;
    f.send(0);f.translate(0);if constexpr(!PathTrace<Ledger>::flow)f.check(0);
    f.launch(0);f.returnPhysical(0);f.returnBackend(0);f.complete(0);f.idle();
    must(f.ledger.value("physical_request")==1&&f.ledger.value("physical_reply")==1,"stalled enqueue drain lost token");
}
int main(){try{
    allFourAndNegatives();simultaneousQueueTransfer();stalledAndCancelBeforeIssue();
    fourPhysicalPaths<DataPathOwnershipLedger>();fourPhysicalPaths<FlowDataPathOwnershipLedger>();
    stalledEnqueueFingerprint<DataPathOwnershipLedger>();stalledEnqueueFingerprint<FlowDataPathOwnershipLedger>();
    std::cout<<"PASS four-owner lifecycle and independent physical path traces; corruption_rejections="<<negatives<<"\n";
}catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}}
