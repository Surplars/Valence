#include "data_path_ownership_ledger.h"
#include <functional>
#include <sstream>

using P=DataPathSample;
static const BackendToken A{0x100000001ULL,3},B{0x200000001ULL,3},C{0x300000001ULL,3};
static void bit(BackendSample &s,unsigned n){s.events|=uint64_t(1)<<n;}
static void bit(P &p,P::Event n,bool on=true){if(on)p.events|=uint64_t(1)<<n;else p.events&=~(uint64_t(1)<<n);}
static DataPathRequest request(uint64_t address=0x80000000,bool write=false,bool vm=false,uint64_t data=0) {
    return {address,data,uint64_t(write)|(3ULL<<7)|(255ULL<<9)|(uint64_t(vm)<<17)};
}
static void must(bool x,const char *why){if(!x)throw std::runtime_error(why);}
static unsigned negatives=0;
static void failure(const std::function<void()> &fn,const char *expected) {
    try{fn();}catch(const std::runtime_error &e){
        if(std::string(e.what()).find(expected)!=std::string::npos){++negatives;return;}
        throw std::runtime_error(std::string("expected rejection '")+expected+"', got: "+e.what());
    }
    throw std::runtime_error(std::string("negative data-path case silently passed: ")+expected);
}
// Directed traces use the public shadow only to supply idle signal defaults.
// Each test explicitly chooses its event sequence and transferred fingerprint;
// negative cases change one observation with all other observations unchanged.
struct Fixture {
    BackendOwnershipLedger backend;
    DataPathOwnershipLedger ledger;
    BackendSample s;P p;
    void begin() {
        s={};p={};
        s.fifoCount=unsigned(backend.requests.size());
        if(s.fifoCount)bit(s,22);
        must(backend.responses.size()<=2,"test exceeded backend capacity");
        for(unsigned i=0;i<backend.responses.size();++i) {
            s.slots[i]=backend.responses[i].token;s.live[i]=true;s.phase[i]=2;
        }
        p.count={unsigned(ledger.stores.size()),ledger.issued(),unsigned(ledger.storeOwners.size()),ledger.directOutstanding(),
            unsigned(ledger.ingress.size()),unsigned(ledger.translated.size()),unsigned(ledger.checked.size()),
            unsigned(ledger.owners.size()),unsigned(ledger.returns.size())};
        if(!ledger.fifo.empty())p.request[P::fifoDeq]=ledger.fifo.front().request;
        if(!ledger.ingress.empty()) {
            p.request[P::incoming]=ledger.ingress.front().request;
            bit(p,P::incomingVirtualized,ledger.ingress.front().request.virtualized());
        }
        if(!ledger.translated.empty()) {
            p.request[P::translatedDeq]=ledger.translated.front().request;
            bit(p,P::translatedFault,ledger.translated.front().fault);
            bit(p,P::translatedPageFault,ledger.translated.front().pageFault);
        }
        if(!ledger.checked.empty()) {
            p.request[P::checkedDeq]=ledger.checked.front().request;
            bit(p,P::checkedFault,ledger.checked.front().fault);
            bit(p,P::checkedPageFault,ledger.checked.front().pageFault);
        }
        bit(p,P::ownerValid,!ledger.storeOwners.empty());
        if(!ledger.storeOwners.empty())bit(p,P::ownerBuffered,ledger.storeOwners.front().buffered);
        if(!ledger.owners.empty())bit(p,P::ownerFault,ledger.owners.front().fault);
        bit(p,P::waiting,bool(ledger.waiting));
        if(ledger.localReply){bit(p,P::storeAckValid);bit(s,40);}
        bit(p,P::reserveGuardMatch);
    }
    void tick(){ledger.advance(s,p,backend);backend.advance(s);}
    void idle(){begin();tick();}
    void enq(BackendToken t,DataPathRequest r) {
        s.start=s.request=t;for(auto n:{3,20,21,41})bit(s,n);p.request[P::fifoEnq]=r;
    }
    void enqueue(BackendToken t,DataPathRequest r){begin();enq(t,r);tick();}
    void reply() {
        for(auto n:{24,25,28})bit(s,n);s.returnSlot=0;
        if(ledger.localReply)p.reply[4]=ledger.localReply->reply;
        else if(p.bit(P::bufferedAccept)||p.bit(P::forwardedAccept))p.reply[4]=ledger.localAccepted(p).reply;
        else p.reply[4]=p.reply[3];
    }
    void local(bool forward=false,bool immediate=true,bool flow=false) {
        bit(s,23);bit(s,forward?38:37);bit(p,forward?P::forwardedAccept:P::bufferedAccept);
        if(immediate)reply();
        if(flow){bit(p,P::flowBuffered);physical(ledger.fifo.front().request);}
    }
    void physical(DataPathRequest r) {
        bit(p,P::storeRequest);bit(p,P::virtualRequest);
        p.request[P::storePhysical]=p.request[P::virtualIn]=r;
    }
    void direct() {bit(s,23);physical(ledger.fifo.front().request);}
    void fast(BackendToken t,DataPathRequest r,bool flow) {
        s.head=s.queueHead=t;s.headValid=true;bit(s,43);bit(p,P::fastAccept);p.request[P::fast]=r;
        if(flow){bit(p,P::flowFast);physical(r);}
    }
    void drain() {
        bit(p,P::drain);
        auto it=std::find_if(ledger.stores.begin(),ledger.stores.end(),[](auto &x){return !x.issued;});
        must(it!=ledger.stores.end(),"test drain underflow");physical(it->transaction.request);
    }
    void incoming(bool immediate=true,uint64_t translatedAddress=0,bool pageFault=false,bool accessFault=false) {
        bit(p,P::incomingRequest);
        auto r=ledger.ingress.front().request;
        if(r.virtualized()) {
            bit(p,P::translationRequest);
            if(!immediate)return;
            bit(p,P::translationReply);r.address=translatedAddress;r.meta&=~(1ULL<<17);
        }
        bit(p,P::translatedPush);p.request[P::translatedEnq]=r;
        bit(p,P::translationEnqueuePageFault,pageFault);bit(p,P::translationEnqueueAccessFault,accessFault);
    }
    void translationReply(uint64_t address,bool pageFault=false,bool accessFault=false) {
        auto r=ledger.waiting->request;r.address=address;r.meta&=~(1ULL<<17);
        bit(p,P::translationReply);bit(p,P::translatedPush);p.request[P::translatedEnq]=r;
        bit(p,P::translationEnqueuePageFault,pageFault);bit(p,P::translationEnqueueAccessFault,accessFault);
    }
    void check(bool addedFault=false) {
        bit(p,P::translatedPop);if(addedFault)bit(p,P::translatedFault);
    }
    void launch() {
        bit(p,P::checkedPop);
        if(!ledger.checked.front().fault){bit(p,P::physicalRequest);p.request[P::physical]=ledger.checked.front().request;}
    }
    void returnPhysical(uint64_t data=0x123456789abcdef0ULL,uint64_t flags=0) {
        bit(p,P::virtualReply);bit(p,P::returnPush);
        if(ledger.owners.front().fault)p.reply[1]={0,uint64_t(1|(ledger.owners.front().pageFault?2:0))};
        else {bit(p,P::physicalReply);p.reply[0]=p.reply[1]={data,flags};}
    }
    void returnStore() {
        bit(p,P::storeResponse);bit(p,P::returnPop);
        p.reply[2]=p.reply[3]=ledger.returns.front().reply;
        if(!ledger.storeOwners.front().buffered)reply();
    }
    void identityToPhysical() {
        begin();incoming();tick();begin();check();tick();begin();launch();tick();
    }
    void finishPhysical(uint64_t data=0) {
        begin();returnPhysical(data);tick();begin();returnStore();tick();idle();
    }
    void empty() {
        must(ledger.fifo.empty()&&ledger.stores.empty()&&ledger.storeOwners.empty()&&ledger.ingress.empty()&&
            !ledger.waiting&&ledger.translated.empty()&&ledger.checked.empty()&&ledger.owners.empty()&&
            ledger.physicalPending.empty()&&ledger.returns.empty()&&!ledger.localReply&&backend.responses.empty(),"test leaked owner");
        ledger.conservation();
    }
};

static void directAndCancelled() {
    Fixture f;auto r=request();f.enqueue(A,r);f.begin();f.direct();f.tick();
    f.begin();f.s.cancelled[0]=true;f.tick();
    must(f.ledger.category(A,f.s,f.p)=="issued_memory_downstream_ingress_wait","ingress stage category");
    f.begin();f.incoming();must(f.ledger.category(A,f.s,f.p)=="issued_memory_downstream_ingress_transfer","ingress transfer category");f.tick();
    f.begin();f.check();f.tick();f.begin();f.launch();f.tick();
    f.begin();must(f.ledger.category(A,f.s,f.p)=="issued_memory_downstream_physical_response_wait","physical response stage category");
    f.returnPhysical(0xdeadbeef,1);f.tick();
    f.idle();f.idle();f.begin();
    must(f.ledger.category(A,f.s,f.p)=="issued_memory_downstream_return_buffer_wait","delayed return buffer category");
    f.returnStore();f.tick();f.empty();
    must(f.ledger.value("cancelled_owner_cycles")==1,"cancelled accepted read was not retained");
}
static void bufferedRetirementAndReuse() {
    Fixture f;auto old=request(0x80000000,true,false,0x1111222233334444ULL);
    auto newer=request(0x80000008,true,false,0x5555666677778888ULL);
    f.enqueue(A,old);f.begin();f.local();f.tick();
    must(f.backend.responses.empty()&&f.ledger.stores.size()==1,"local ack must outlive backend token");
    f.enqueue(B,newer);f.begin();f.local();f.drain();f.tick();
    must(f.ledger.storeOwners.front().token==A,"old retired store attributed to reused ROB token");
    f.identityToPhysical();f.begin();f.returnPhysical();f.drain();f.tick();
    f.begin();f.returnStore();f.incoming();f.tick();
    must(f.ledger.stores.size()==1&&f.ledger.stores.front().transaction.token==B,"simultaneous old store response lost new owner");
    f.begin();f.check();f.tick();f.begin();f.launch();f.tick();f.finishPhysical();f.empty();
    must(f.ledger.value("route_drain")==2&&f.ledger.value("buffered_response")==2,"drain conservation");
}
static void fastAndFlowBuffered() {
    Fixture f;auto w=request(0x80000000,true,false,0xffeeddccbbaa9988ULL);
    f.begin();f.fast(A,w,true);f.tick();f.identityToPhysical();f.finishPhysical();f.empty();
    f.enqueue(B,w);f.begin();f.local(false,false,true);f.tick();
    must(bool(f.ledger.localReply),"delayed local ack not captured");
    f.begin();f.reply();f.incoming();f.tick();f.begin();f.check();f.tick();f.begin();f.launch();f.tick();
    f.finishPhysical();f.empty();
    must(f.ledger.value("route_flow_fast")==1&&f.ledger.value("route_flow_buffered")==1,"flow arbitration not covered");
}
static void forwardedRead() {
    Fixture f;auto w=request(0x80000000,true,false,0x1122334455667788ULL);
    f.begin();f.fast(A,w,false);f.tick();
    auto young=w;young.data=0xaabbccdd00000000ULL;young.meta=(young.meta&~(255ULL<<9))|(240ULL<<9);
    f.begin();f.fast(B,young,false);f.tick();
    f.enqueue(C,request());f.begin();f.local(true,false);f.tick();
    must(f.ledger.localReply->reply.data==0xaabbccdd55667788ULL,"forwarding byte age/mask merge");
    f.begin();f.reply();f.drain();f.tick();f.identityToPhysical();f.finishPhysical();
    f.begin();f.drain();f.tick();f.identityToPhysical();f.finishPhysical();f.empty();
    must(f.ledger.value("forwarded_accept")==1&&f.ledger.value("physical_request")==2,"forwarded read must not issue physically");
}
static void translationsAndFaultOrdering() {
    Fixture f;auto v=request(0x10000000,false,true);
    f.enqueue(A,v);f.begin();f.direct();f.enq(B,request(0x80000008));f.tick();
    f.begin();f.incoming(false);f.direct();f.tick();
    must(f.ledger.waiting&&f.ledger.waiting->token==A&&f.ledger.ingress.front().token==B,"waiting and ingress ownership conflated");
    f.begin();f.translationReply(0x80001000,true);f.tick();
    f.begin();f.check();f.incoming();f.tick();
    f.begin();f.launch();f.check();f.tick();
    must(f.ledger.owners.front().fault&&f.ledger.physicalPending.empty(),"fault placeholder issued physical request");
    f.begin();f.launch();f.returnPhysical();f.tick();
    f.begin();f.returnStore();f.returnPhysical(0xbeef,0);f.tick();
    f.begin();f.returnStore();f.tick();f.empty();
    must(f.ledger.value("physical_request")==1&&f.ledger.value("fault_placeholder")==1&&f.ledger.value("simultaneous_return_transfer")==1,"fault/data ordered responses");
    // Same-cycle TLB hit; output address/PBMT change is legitimate, payload isn't.
    Fixture hit;hit.enqueue(A,v);hit.begin();hit.direct();hit.tick();hit.begin();hit.incoming(true,0x80008000);
    hit.p.request[P::translatedEnq].meta|=1ULL<<18;hit.tick();
    hit.begin();hit.check(true);hit.tick();hit.begin();hit.launch();hit.tick();hit.finishPhysical();hit.empty();
    must(hit.ledger.value("same_cycle_translation_reply")==1&&hit.ledger.value("physical_request")==0,"TLB hit/PMP fault coverage");
    Fixture access;access.enqueue(A,v);access.begin();access.direct();access.tick();access.begin();access.incoming(true,0x80004000,false,true);access.tick();
    access.begin();access.check();access.tick();access.begin();access.launch();access.tick();access.finishPhysical();access.empty();
}
static void simultaneousEveryBoundary() {
    Fixture f;f.enqueue(A,request());f.begin();f.direct();f.enq(B,request(0x80000008));f.tick();
    f.begin();f.direct();f.incoming();f.tick();
    f.begin();f.incoming();f.check();f.tick();
    f.begin();f.check();f.launch();f.tick();
    f.begin();f.launch();f.returnPhysical(10);f.tick();
    f.begin();f.returnStore();f.returnPhysical(20);f.tick();
    f.begin();f.returnStore();f.tick();f.empty();
    must(f.ledger.value("simultaneous_fifo_transfer")==1&&f.ledger.value("simultaneous_return_transfer")==1,"simultaneous transfers not counted");
}
static void resetAndReuse() {
    Fixture f;f.enqueue(A,request(0x1000,false,true));f.begin();f.direct();f.tick();f.begin();f.incoming(false);f.tick();
    f.enqueue(B,request(0x80000008));f.begin();f.s.reset=true;f.tick();f.empty();
    must(f.ledger.value("reset_waiting_drops")==1&&f.ledger.value("reset_fifo_drops")==1,"reset pending ownership discard");
    f.enqueue(A,request());f.begin();f.direct();f.tick();f.identityToPhysical();f.finishPhysical();f.empty();
    Fixture reply;reply.begin();reply.fast(A,request(0x80000000,true),true);reply.tick();reply.identityToPhysical();
    reply.begin();reply.returnPhysical();reply.tick();reply.begin();reply.s.reset=true;reply.tick();reply.empty();
    must(reply.ledger.value("reset_return_drops")==1&&reply.ledger.value("reset_buffered_drops")==1,"reset returned buffered store discard");
    Fixture local;local.enqueue(A,request(0x80000000,true));local.begin();local.local(false,false);local.tick();
    local.begin();local.s.reset=true;local.tick();local.empty();must(local.ledger.value("reset_local_reply_drops")==1,"reset held local acknowledgement discard");
}
static void resetEveryBoundary() {
    for(unsigned stage=0;stage<5;++stage) {
        Fixture f;f.enqueue(A,request());f.begin();f.direct();f.tick();
        if(stage>=1){f.begin();f.incoming();f.tick();}
        if(stage>=2){f.begin();f.check();f.tick();}
        if(stage>=3){f.begin();f.launch();f.tick();}
        if(stage>=4){f.begin();f.returnPhysical();f.tick();}
        f.begin();f.s.reset=true;f.tick();f.empty();
        const char *keys[]={"reset_ingress_drops","reset_translated_drops","reset_checked_drops","reset_translation_owner_drops","reset_return_drops"};
        must(f.ledger.value(keys[stage])==1,"reset stage-specific drop receipt");
        must(f.ledger.value("reset_physical_drops")==unsigned(stage==3),"reset physical outstanding drop receipt");
        f.begin();f.s.reset=true;f.tick();f.empty();
    }
    Fixture zero;std::ostringstream out;auto *previous=std::cout.rdbuf(out.rdbuf());zero.ledger.report();std::cout.rdbuf(previous);
    for(const char *field:{"DATA_PATH_LEDGER","foreign_request=0","resets=0","reset_return_drops=0","pending_waiting=0"})
        must(out.str().find(field)!=std::string::npos,"stable zero-valued receipt field missing");
}
static void corruptionRejections() {
    Fixture f;f.enqueue(A,request());f.begin();
    f.p.request[P::fifoDeq].data^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"FIFO dequeue fingerprint");
    f.begin();f.backend.requests.front()=B;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"FIFO full-token lineage");f.backend.requests.front()=A;
    f.begin();f.direct();f.p.request[P::storePhysical].address^=8;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"selected StoreBuffer request fingerprint");
    f.begin();f.direct();bit(f.p,P::flowFast);failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"direct FIFO acceptance lacks physical request");
    f.begin();f.direct();f.tick();f.begin();
    for(unsigned i=0;i<9;++i){++f.p.count[i];failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"pre-edge count corruption");--f.p.count[i];}
    bit(f.p,P::foreignRequest);failure([&]{f.ledger.advance(f.s,f.p,f.backend);},"foreign FP/system");must(f.ledger.value("foreign_request")==1,"foreign request rejection not counted");
    f.begin();f.p.request[P::incoming].address^=8;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"translation incoming fingerprint");
    f.begin();f.incoming();f.p.request[P::translatedEnq].address^=8;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"nonvirtual identity translation");
    f.begin();f.incoming();f.p.request[P::translatedEnq].meta^=1ULL<<9;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"translation changed preserved");
    f.begin();f.incoming();f.tick();f.begin();f.p.request[P::translatedDeq].data^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"translated dequeue fingerprint");
    f.begin();f.check();f.tick();f.begin();f.p.request[P::checkedDeq].data^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"checked dequeue fingerprint");
    f.begin();f.launch();f.p.request[P::physical].meta^=1ULL<<7;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"physical request fingerprint");
    f.begin();f.launch();f.tick();f.begin();f.returnPhysical();f.p.reply[1].data^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"physical/virtual reply fingerprint");
    f.begin();f.returnPhysical();f.tick();f.begin();f.returnStore();f.p.reply[2].data^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"relocated return payload");
    f.begin();f.returnStore();f.p.reply[3].flags^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"StoreBuffer response payload");
    f.begin();f.returnStore();f.p.reply[4].data^=1;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"backend/local reply payload");
    f.begin();f.returnStore();f.s.slots[0]=B;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"backend return full-token lineage");
    f.begin();f.ledger.returns.front().transaction.token=B;failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"ordered pipeline full-token lineage");f.ledger.returns.front().transaction.token=A;
    f.begin();f.returnStore();bit(f.p,P::returnPop,false);failure([&]{f.ledger.validate(f.s,f.p,f.backend);},"relocated return/StoreBuffer response route");
    f.begin();f.returnStore();f.tick();f.empty();
    Fixture fault;fault.enqueue(A,request(0x1000,false,true));fault.begin();fault.direct();fault.tick();
    fault.begin();fault.incoming(true,0,true);fault.tick();fault.begin();fault.check();fault.tick();
    fault.begin();fault.launch();bit(fault.p,P::physicalRequest);failure([&]{fault.ledger.validate(fault.s,fault.p,fault.backend);},"physical/fault placeholder route");
    fault.begin();fault.launch();fault.tick();fault.begin();fault.returnPhysical();fault.p.reply[1].flags=1;
    failure([&]{fault.ledger.validate(fault.s,fault.p,fault.backend);},"fault response payload");
    Fixture local;local.enqueue(A,request(0x80000000,true));local.begin();local.local();local.p.reply[4].flags=1;
    failure([&]{local.ledger.validate(local.s,local.p,local.backend);},"backend/local reply payload");
    local.begin();local.local(false,false);local.tick();local.begin();local.reply();local.p.reply[4].data=1;
    failure([&]{local.ledger.validate(local.s,local.p,local.backend);},"backend/local reply payload");
    Fixture forwarded;forwarded.begin();forwarded.fast(A,request(0x80000000,true,false,0x1234),false);forwarded.tick();
    forwarded.enqueue(B,request());forwarded.begin();forwarded.local(true,true);forwarded.p.reply[4].data^=1;
    failure([&]{forwarded.ledger.validate(forwarded.s,forwarded.p,forwarded.backend);},"backend/local reply payload");
    forwarded.begin();forwarded.local(true,true);forwarded.drain();forwarded.p.request[P::storePhysical]=request(0x80000008,true,false,0x1234);
    failure([&]{forwarded.ledger.validate(forwarded.s,forwarded.p,forwarded.backend);},"selected StoreBuffer request fingerprint");
    Fixture virtualPayload;virtualPayload.enqueue(A,request(0x1000,false,true));virtualPayload.begin();virtualPayload.direct();virtualPayload.tick();
    virtualPayload.begin();virtualPayload.incoming(true,0x80000000);virtualPayload.p.request[P::translatedEnq].data=1;
    failure([&]{virtualPayload.ledger.validate(virtualPayload.s,virtualPayload.p,virtualPayload.backend);},"translation changed preserved request");
    virtualPayload.begin();virtualPayload.incoming(true,0x80000000);virtualPayload.p.request[P::translatedEnq].meta|=1ULL<<17;
    failure([&]{virtualPayload.ledger.validate(virtualPayload.s,virtualPayload.p,virtualPayload.backend);},"translated request remains virtualized");
    Fixture guaranteed;guaranteed.begin();guaranteed.fast(A,request(0x80000000,true),true);guaranteed.tick();guaranteed.identityToPhysical();
    guaranteed.begin();guaranteed.returnPhysical(0,1);guaranteed.tick();guaranteed.begin();guaranteed.returnStore();
    failure([&]{guaranteed.ledger.validate(guaranteed.s,guaranteed.p,guaranteed.backend);},"guaranteed buffered store received fault");
    Fixture swapped;swapped.enqueue(A,request());swapped.begin();swapped.direct();swapped.enq(B,request(0x80000008));swapped.tick();
    swapped.begin();swapped.direct();swapped.incoming();swapped.tick();swapped.begin();swapped.incoming();swapped.check();swapped.tick();
    swapped.begin();swapped.check();swapped.launch();swapped.tick();swapped.begin();swapped.launch();swapped.returnPhysical();swapped.tick();
    swapped.begin();swapped.returnStore();std::swap(swapped.s.slots[0],swapped.s.slots[1]);
    failure([&]{swapped.ledger.validate(swapped.s,swapped.p,swapped.backend);},"backend return full-token lineage");
    Fixture registered;registered.begin();registered.fast(A,request(0x80000000,true),true);bit(registered.p,P::incomingRequest);
    failure([&]{registered.ledger.validate(registered.s,registered.p,registered.backend);},"incoming transfer lacks registered owner");
    Fixture duplicate;duplicate.begin();duplicate.fast(A,request(0x80000000,true),false);duplicate.tick();
    duplicate.begin();duplicate.fast(A,request(0x80000008,true),false);failure([&]{duplicate.ledger.validate(duplicate.s,duplicate.p,duplicate.backend);},"fast store reuses outstanding full-token");
}
int main(){try{
    directAndCancelled();bufferedRetirementAndReuse();fastAndFlowBuffered();forwardedRead();
    translationsAndFaultOrdering();simultaneousEveryBoundary();resetAndReuse();resetEveryBoundary();corruptionRejections();
    std::cout<<"PASS data-path full-token lineage, all arbitration classes, registered boundaries, translation/fault ordering, cancellation, reset, reuse, simultaneous transfers; corruption_rejections="<<negatives<<"\n";
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}}
