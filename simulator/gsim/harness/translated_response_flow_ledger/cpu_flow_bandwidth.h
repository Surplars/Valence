#pragma once
#include "data_path_sample.h"
#include <iostream>
#include <map>
#include <optional>
#ifndef PHYSICAL_INGRESS_FLOW
#define PHYSICAL_INGRESS_FLOW 0
#endif

// Passive, full-generation lineage. Every queue below is a PRE-EDGE shadow of a
// registered hardware boundary. A locally acknowledged store keeps its original
// token and complete fingerprint until its ordered physical response, even after
// retirement and reuse of the same ROB index. Never infer ownership from address.
// This fixture-local fork adds the selected board's existing identity shortcut
// and its opt-in physical-load ingress shortcut. The local continuation also
// distinguishes actual translated-return port fires from internal queue fires.
// It preserves full-generation lineage and raw-probe conservation. The shortcut
// is predicted from pre-edge queue capacity, not inferred from a missing event.
struct FlowDataPathOwnershipLedger {
    using P=DataPathSample;
    struct Transaction {
        BackendToken token;
        DataPathRequest original, request;
        bool buffered=false, fault=false, pageFault=false;
        uint64_t authorization=0;
    };
    struct Buffered { Transaction transaction; bool issued=false; };
    struct Returned { Transaction transaction; DataPathReply reply; };
    std::deque<Transaction> fifo, storeOwners, ingress, translated, checked, owners, physicalPending;
    std::deque<Buffered> stores;
    std::deque<Returned> returns;
    std::optional<Transaction> waiting;
    std::optional<Returned> localReply;
    std::optional<std::pair<BackendToken,DataPathRequest>> stalledRequest;
    std::optional<DataPathReply> stalledReply;
    std::map<std::string,uint64_t> counters;
    uint64_t flowEvents=0, ingressAuth=0, checkedAuth=0, checkedAddress=0, checkedData=0;
    uint64_t checkedHeadAuth=0, physicalAuth=0;
    bool flow(unsigned bit) const { return (flowEvents>>bit)&1; }
    static uint64_t expectedAuthorization(const Transaction &t) {
        const auto &r=t.request;
        const uint64_t bytes=1ULL<<((r.meta>>7)&3), next=(r.address&~63ULL)+64;
        // The frozen guest executes only integer M-mode code and never writes
        // PMP/privilege CSRs. Current and next-line PMP therefore use unlocked
        // M-mode access; directed S/PMP/epoch cases live in the adapter proof.
        // Explicit new profile only. This fixed M-bare guest never writes PMP;
        // the observer independently asserts M, MPRV=0, satp=0 and all PMP cfg OFF.
        // Do not derive permission from the observed DUT hint.
        static_assert(STORE_PREFETCH_PROFILE==0 || STORE_PREFETCH_PROFILE==1);
        unsigned naturalMask=0;
        for(unsigned byte=0;byte<bytes;++byte) naturalMask |= 1U<<((r.address&7)+byte);
        const bool storeShape=STORE_PREFETCH_PROFILE && !(r.address&(bytes-1)) &&
            ((r.meta>>9)&255)==(naturalMask&255);
        const bool hint=!t.fault&&(!r.write()||storeShape)&&!r.atomic()&&!r.virtualized()&&!(r.meta&(1ULL<<18))&&
            r.address>=0x80200000ULL&&r.address<=0x100200000ULL-bytes&&
            next>=0x80200000ULL&&next<=0x100200000ULL-64&&
            (r.address>>12)==(next>>12);
        return r.meta|(uint64_t(hint)<<52);
    }

    FlowDataPathOwnershipLedger() {
        // Stable receipt columns also report untouched paths as explicit zeroes.
        for(const char *key:{"checks","resets","foreign_request","foreign_response","foreign_epoch",
            "identity_pass","physical_ingress_pass","fifo_enqueue","fifo_dequeue","buffered_accept","fast_accept","forwarded_accept",
            "local_accept","local_reply","buffered_response","direct_response","store_request","store_response",
            "virtual_request","incoming_request","translation_request","translation_reply","translated_push",
            "translated_pop","checked_pop","physical_request","virtual_reply","physical_reply","return_push","return_pop",
            "route_drain","route_flow_buffered","route_flow_fast","route_direct","fault_placeholder",
            "return_empty_pass","return_empty_capture","return_old_head_transfer",
            "same_cycle_translation_reply","simultaneous_fifo_transfer","simultaneous_return_transfer","cancelled_owner_cycles",
            "reset_fifo_drops","reset_buffered_drops","reset_store_owner_drops","reset_ingress_drops","reset_waiting_drops",
            "reset_translated_drops","reset_checked_drops","reset_translation_owner_drops","reset_physical_drops",
            "reset_return_drops","reset_local_reply_drops"})counters.emplace(key,0);
    }

    static void require(bool ok,const char *why) {
        if(!ok)throw std::runtime_error(std::string("data path ownership: ")+why);
    }
    static bool same(const Transaction &a,const Transaction &b) {
        return a.token==b.token && a.original==b.original;
    }
    static void payload(const DataPathRequest &a,const DataPathRequest &b,const char *why) {
        require(a==b,why);
    }
    static void response(const DataPathReply &a,const DataPathReply &b,const char *why) {
        require(a==b,why);
    }
    static bool tokenIn(const std::deque<Transaction> &q,BackendToken token) {
        return std::any_of(q.begin(),q.end(),[&](const Transaction &t){return t.token==token;});
    }
    unsigned issued() const {
        return unsigned(std::count_if(stores.begin(),stores.end(),[](const Buffered &s){return s.issued;}));
    }
    unsigned directOutstanding() const {
        return unsigned(std::count_if(storeOwners.begin(),storeOwners.end(),[](const Transaction &t){return !t.buffered;}));
    }
    bool contains(BackendToken token) const {
        if(tokenIn(fifo,token)||tokenIn(storeOwners,token)||tokenIn(ingress,token)||tokenIn(translated,token)||
            tokenIn(checked,token)||tokenIn(owners,token)||tokenIn(physicalPending,token))return true;
        if(waiting&&waiting->token==token)return true;
        if(localReply&&localReply->transaction.token==token)return true;
        for(const auto &s:stores)if(s.transaction.token==token)return true;
        for(const auto &r:returns)if(r.transaction.token==token)return true;
        return false;
    }
    Transaction fifoHead() const { require(!fifo.empty(),"FIFO transfer underflow");return fifo.front(); }
    Transaction fastStore(const BackendSample &s,const P &p) const {
        require(s.headValid,"fast store lacks valid full-token ROB head");
        auto r=p.request[P::fast];
        require(r.write()&&!r.atomic()&&!r.virtualized()&&!(r.meta&(1ULL<<18)),"invalid fast store request class");
        return {s.head,r,r,true,false,false};
    }
    Transaction selected(const BackendSample &s,const P &p) const {
        const unsigned routes=p.bit(P::drain)+p.bit(P::flowBuffered)+p.bit(P::flowFast);
        require(routes<=1,"multiple StoreBuffer physical arbitration routes");
        if(p.bit(P::drain)) {
            auto it=std::find_if(stores.begin(),stores.end(),[](const Buffered &b){return !b.issued;});
            require(it!=stores.end(),"drain lacks persistent buffered store owner");
            return it->transaction;
        }
        if(p.bit(P::flowFast)) {
            require(p.bit(P::fastAccept),"flow-fast route lacks fast acceptance");
            return fastStore(s,p);
        }
        auto t=fifoHead();
        require(s.deq(),"physical direct/flow request lacks FIFO acceptance");
        t.buffered=p.bit(P::flowBuffered);
        require(t.buffered==p.bit(P::bufferedAccept),"physical request buffered/direct route corruption");
        require(!p.bit(P::forwardedAccept),"forwarded local read issued physically");
        return t;
    }
    Returned localAccepted(const P &p) const {
        auto t=fifoHead();
        if(p.bit(P::bufferedAccept))return {t,{0,0}};
        require(p.bit(P::forwardedAccept),"local response has no acceptance class");
        const auto &r=t.request;
        require(!r.write()&&!r.atomic()&&!r.virtualized(),"invalid forwarded request class");
        uint64_t data=0; unsigned covered=0;
        // Oldest to youngest: the youngest buffered matching byte wins. Issued
        // stores remain forwardable until the edge accepting their response.
        for(const auto &entry:stores) {
            const auto &w=entry.transaction.request;
            if((w.address>>3)!=(r.address>>3))continue;
            const unsigned mask=(w.meta>>9)&255;
            for(unsigned byte=0;byte<8;++byte)if(mask&(1U<<byte)) {
                const uint64_t bits=uint64_t(255)<<(8*byte);
                data=(data&~bits)|(w.data&bits);covered|=1U<<byte;
            }
        }
        const unsigned mask=(r.meta>>9)&255;
        require((covered&mask)==mask,"forwarded read lacks complete buffered byte coverage");
        return {t,{data,0}};
    }
    bool physicalIngressPass(const P &p) const {
        if (!PHYSICAL_INGRESS_FLOW || (ingressAuth & (1ULL<<19)) || !p.bit(P::virtualRequest) || !ingress.empty() ||
            !translated.empty() || waiting || checked.size() >= 2) return false;
        const auto &r = p.request[P::virtualIn];
        const uint64_t bytes = 1ULL << ((r.meta >> 7) & 3);
        // This full-core fixture is M-mode only and explicitly disables virtual
        // precheck. Predict the permitted route from the independent pre-edge
        // shadow and complete ordinary-request fingerprint, never a DUT bypass bit.
        return !r.write() && !r.atomic() && !r.virtualized() && !(r.meta & (1ULL << 18)) &&
            !(r.address & (bytes - 1)) && r.address >= 0x80200000ULL &&
            r.address <= 0x100200000ULL - bytes;
    }
    bool identityPass(const P &p) const {
        return p.bit(P::incomingRequest) && !ingress.front().request.virtualized() &&
            translated.empty() && checked.size() < 2;
    }
    // P::virtualReply is adapter virtual response valid && ready: the actual
    // return-buffer input. P::storeResponse is StoreBuffer physical response
    // valid && ready: its actual integer output. The fixture rejects foreign
    // FP/system epochs before using this equivalence. returnPush/returnPop are
    // separate INTERNAL queue fires, not the port fires under empty flow.
    bool returnEmptyPass(const P &p) const {
        return returns.empty() && p.bit(P::virtualReply) && p.bit(P::storeResponse);
    }
    void validateReturnBoundary(const P &p) const {
        const bool pass=returnEmptyPass(p);
        require(returns.size()<=2,"return two-credit capacity exceeded");
        require(!p.bit(P::virtualReply)||returns.size()<2,"return input fired without pre-edge queue credit");
        require(p.bit(P::returnPush)==(p.bit(P::virtualReply)&&!pass),"relocated return enqueue route corruption");
        require(p.bit(P::returnPop)==(p.bit(P::storeResponse)&&!pass),"relocated return/StoreBuffer response route corruption");
        require(!p.bit(P::returnPop)||!returns.empty(),"registered return dequeue underflow");
        if(pass)require(!owners.empty(),"empty return pass lacks accepted input owner");
    }
    Returned selectedReturn(const P &p) const {
        if(!returns.empty())return returns.front(); // Older queue head always wins.
        require(returnEmptyPass(p)&&!owners.empty(),"StoreBuffer response has no accepted return owner");
        return {owners.front(),p.reply[1]};
    }
    // Read-only checks, including all transfer payloads. This does not increment
    // counters. advance() invokes it, and must precede BackendOwnershipLedger::advance().
    void validate(const BackendSample &s,const P &p,const BackendOwnershipLedger &b) const {
        if(s.reset)return;
        if(stalledRequest) {
            require(s.bit(20)&&s.request==stalledRequest->first,"stalled request full-token lineage changed or vanished");
            payload(p.request[P::fifoEnq],stalledRequest->second,"stalled request fingerprint corruption");
        }
        if(stalledReply) {
            require(s.bit(24),"stalled backend response vanished");
            response(p.reply[4],*stalledReply,"stalled backend response payload corruption");
        }
        const bool predictedIngress=physicalIngressPass(p);
        require(flow(1)==predictedIngress,"physical ingress route prediction mismatch");
        require(flow(0)==(p.bit(P::virtualRequest)&&!predictedIngress),"raw virtual enqueue route mismatch");
        require(!flow(2),"prechecked flow unexpectedly enabled in physical-only workload");
        require(flow(4)==identityPass(p),"raw identity route mismatch");
        require(flow(5)==p.bit(P::incomingRequest),"raw virtual dequeue mismatch");
        require(flow(3)==(predictedIngress||identityPass(p)||p.bit(P::translatedPop)),"raw checked enqueue route mismatch");
        require(flow(6)==(checked.size()<2),"checked enqueue readiness is not occupancy-only");
        if(p.bit(P::virtualRequest))require(ingressAuth==p.request[P::virtualIn].meta,
            "physical fixture emitted unexpected authorization metadata");
        if(!checked.empty())require(checked.front().authorization==checkedHeadAuth,
            "checked held authorization metadata mismatch");
        if(p.bit(P::physicalRequest))require(checked.front().authorization==physicalAuth,
            "physical authorization metadata mismatch");
        require(!p.bit(P::foreignRequest)&&!p.bit(P::foreignResponse)&&!p.bit(P::foreignEpoch),
            "foreign FP/system traffic in integer-only ownership workload");
        const std::array<size_t,9> expected{stores.size(),issued(),storeOwners.size(),directOutstanding(),
            ingress.size(),translated.size(),checked.size(),owners.size(),returns.size()};
        for(unsigned i=0;i<expected.size();++i)
            if(expected[i]!=p.count[i])throw std::runtime_error("data path ownership: pre-edge count corruption at index "+std::to_string(i));
        require(fifo.size()==b.requests.size()&&fifo.size()==s.fifoCount,"FIFO lineage count differs from backend");
        for(unsigned i=0;i<fifo.size();++i)require(fifo[i].token==b.requests[i],"FIFO full-token lineage differs from backend");
        require(p.bit(P::ownerValid)==!storeOwners.empty(),"StoreBuffer owner validity corruption");
        if(!storeOwners.empty())require(p.bit(P::ownerBuffered)==storeOwners.front().buffered,"StoreBuffer response class corruption");
        require(p.bit(P::waiting)==bool(waiting),"translation waiting state corruption");
        require(p.bit(P::storeAckValid)==bool(localReply),"local acknowledgement state corruption");
        require(p.bit(P::storeAckValid)==s.bit(40),"backend/local acknowledgement probes disagree");
        require(p.bit(P::bufferedAccept)==(s.deq()&&s.bit(37)),"buffered acceptance route corruption");
        require(p.bit(P::forwardedAccept)==(s.deq()&&s.bit(38)),"forwarded acceptance route corruption");
        require(!(p.bit(P::bufferedAccept)&&p.bit(P::forwardedAccept)),"duplicate local acceptance classes");
        require(p.bit(P::fastAccept)==s.bit(43),"fast store acceptance probes disagree");
        require(!(p.bit(P::bufferedAccept)&&p.bit(P::fastAccept)),"two buffered writes accepted on one edge");
        if(!fifo.empty())payload(fifo.front().request,p.request[P::fifoDeq],"FIFO dequeue fingerprint corruption");
        if(s.enq()) {
            require(!contains(s.request),"duplicate accepted full-token lineage");
            require(!p.bit(P::fastAccept)||!(s.head==s.request),"same token accepted on FIFO and fast path");
        }
        if(p.bit(P::fastAccept)) {
            require(!contains(s.head),"fast store reuses outstanding full-token lineage");
            (void)fastStore(s,p);
        }
        if(s.deq()) {
            auto t=fifoHead();
            if(p.bit(P::bufferedAccept))require(t.request.write()&&!t.request.atomic()&&!t.request.virtualized(),"invalid buffered store class");
            if(p.bit(P::bufferedAccept)||p.bit(P::forwardedAccept)) {
                require(!localReply,"local acceptance overwrites held acknowledgement");
                require(!directOutstanding(),"local acceptance bypasses older direct responses");
                (void)localAccepted(p);
            } else require(p.bit(P::storeRequest)&&!p.bit(P::drain)&&!p.bit(P::flowFast),"direct FIFO acceptance lacks physical request");
        }
        require(p.bit(P::storeRequest)==p.bit(P::virtualRequest),"StoreBuffer/translation ingress handshake route corruption");
        if(p.bit(P::storeRequest)) {
            auto t=selected(s,p);
            payload(t.request,p.request[P::storePhysical],"selected StoreBuffer request fingerprint corruption");
            payload(t.request,p.request[P::virtualIn],"translation ingress request fingerprint corruption");
        }
        if(!ingress.empty())payload(ingress.front().request,p.request[P::incoming],"translation incoming fingerprint corruption");
        if(p.bit(P::incomingRequest)) {
            require(!ingress.empty()&&!waiting,"incoming transfer lacks registered owner or overwrites waiting owner");
            require(p.bit(P::incomingVirtualized)==ingress.front().request.virtualized(),"incoming virtualized route corruption");
            require(p.bit(P::translationRequest)==ingress.front().request.virtualized(),"translation request route corruption");
        } else require(!p.bit(P::translationRequest),"translation request lacks incoming owner");
        require(!p.bit(P::translationReply)||waiting||p.bit(P::translationRequest),"translation reply lacks accepted owner");
        const bool bypass=p.bit(P::incomingRequest)&&!ingress.front().request.virtualized();
        require(p.bit(P::translatedPush)==((bypass&&!identityPass(p))||p.bit(P::translationReply)),"translated enqueue route corruption");
        if(p.bit(P::translatedPush)) {
            const auto &t=waiting?*waiting:ingress.front();
            const auto &out=p.request[P::translatedEnq];
            // Translation may change ONLY address, virtualized and uncached. An
            // existing uncached property is sticky, including a non-VM bypass.
            constexpr uint64_t translatedFields=(1ULL<<17)|(1ULL<<18);
            require(out.data==t.request.data&&(out.meta&~translatedFields)==(t.request.meta&~translatedFields),
                "translation changed preserved request fingerprint fields");
            require(!out.virtualized(),"translated request remains virtualized");
            require(!(t.request.meta&(1ULL<<18))||(out.meta&(1ULL<<18)),"translation cleared uncached property");
            if(!t.request.virtualized()) {
                payload(out,t.request,"nonvirtual identity translation fingerprint corruption");
                require(!p.bit(P::translationEnqueuePageFault)&&!p.bit(P::translationEnqueueAccessFault),"identity translation fabricated fault");
            }
        }
        if(!translated.empty())payload(translated.front().request,p.request[P::translatedDeq],"translated dequeue fingerprint corruption");
        if(p.bit(P::translatedPop)) {
            require(!translated.empty(),"translated dequeue underflow");
            require(p.bit(P::translatedPageFault)==translated.front().pageFault,"translated page fault lineage corruption");
            require(!translated.front().fault||p.bit(P::translatedFault),"physical check lost translation fault");
        }
        if(!checked.empty()) {
            payload(checked.front().request,p.request[P::checkedDeq],"checked dequeue fingerprint corruption");
            require(p.bit(P::checkedFault)==checked.front().fault&&p.bit(P::checkedPageFault)==checked.front().pageFault,
                "checked fault lineage corruption");
        }
        require(p.bit(P::physicalRequest)==(p.bit(P::checkedPop)&&!p.bit(P::checkedFault)),"physical/fault placeholder route corruption");
        if(p.bit(P::checkedPop)) {
            require(!checked.empty(),"checked dequeue underflow");
            if(p.bit(P::physicalRequest))payload(checked.front().request,p.request[P::physical],"physical request fingerprint corruption");
        }
        // All stages are ordered; concatenate oldest to youngest independently
        // of the request-port observations and compare with StoreBuffer owners.
        size_t ordinal=0;
        auto lineage=[&](const Transaction &t) {
            require(ordinal<storeOwners.size()&&same(storeOwners[ordinal],t),"ordered pipeline full-token lineage corruption");
            ++ordinal;
        };
        for(const auto &r:returns)lineage(r.transaction);
        for(const auto &t:owners)lineage(t);
        for(const auto &t:checked)lineage(t);
        for(const auto &t:translated)lineage(t);
        if(waiting)lineage(*waiting);
        for(const auto &t:ingress)lineage(t);
        require(ordinal==storeOwners.size(),"ordered pipeline owner conservation failure");
        size_t physicalOrdinal=0;
        for(const auto &t:owners)if(!t.fault) {
            require(physicalOrdinal<physicalPending.size()&&same(physicalPending[physicalOrdinal],t),
                "ordered physical full-token lineage corruption");
            payload(physicalPending[physicalOrdinal].request,t.request,"ordered physical request fingerprint corruption");
            ++physicalOrdinal;
        }
        require(physicalOrdinal==physicalPending.size(),"physical owner conservation failure");
        for(const auto &t:storeOwners)if(!t.buffered) {
            auto e=b.find(t.token);
            require(e&&e->stage==BackendOwnershipLedger::downstream,"direct owner lost backend full-token lineage");
        }
        if(localReply) {
            auto e=b.find(localReply->transaction.token);
            require(e&&e->stage==BackendOwnershipLedger::localReply,"local acknowledgement lost backend full-token lineage");
        }
        if(!owners.empty())require(p.bit(P::ownerFault)==owners.front().fault,"translation response owner fault corruption");
        require(p.bit(P::physicalReply)==(p.bit(P::virtualReply)&&!p.bit(P::ownerFault)),"physical/virtual response route corruption");
        validateReturnBoundary(p);
        if(p.bit(P::virtualReply)) {
            require(!owners.empty(),"virtual response registered-owner underflow");
            const auto &t=owners.front();
            if(t.fault)response(p.reply[1],{0,uint64_t(1|(t.pageFault?2:0))},"fault response payload corruption");
            else {
                require(!physicalPending.empty()&&same(physicalPending.front(),t),"physical response full-token lineage corruption");
                payload(physicalPending.front().request,t.request,"physical response request fingerprint corruption");
                response(p.reply[0],p.reply[1],"physical/virtual reply fingerprint corruption");
            }
        }
        if(p.bit(P::storeResponse)) {
            require(!storeOwners.empty(),"StoreBuffer response registered-owner underflow");
            const auto returned=selectedReturn(p);
            require(same(returned.transaction,storeOwners.front()),"StoreBuffer return full-token lineage corruption");
            response(returned.reply,p.reply[2],"relocated return payload corruption");
            response(p.reply[2],p.reply[3],"StoreBuffer response payload corruption");
            if(storeOwners.front().buffered) {
                require(!stores.empty()&&stores.front().issued&&same(stores.front().transaction,storeOwners.front()),
                    "buffered response lost persistent full-token lineage");
                require(!p.reply[3].flags,"guaranteed buffered store received fault");
            }
        }
        const bool acceptedLocal=p.bit(P::bufferedAccept)||p.bit(P::forwardedAccept);
        const bool directReply=p.bit(P::storeResponse)&&!storeOwners.front().buffered;
        if(directReply)require(!localReply&&!acceptedLocal&&s.reply(),"direct return lost ordered backend response route");
        if(s.reply()) {
            require(s.returnSlot<BackendSample::ownerCount&&s.live[s.returnSlot],"backend response has no live full-token slot");
            std::optional<BackendToken> token;
            DataPathReply expectedReply;
            if(localReply){token=localReply->transaction.token;expectedReply=localReply->reply;}
            else if(acceptedLocal){token=fifo.front().token;expectedReply=localAccepted(p).reply;}
            else if(directReply){token=storeOwners.front().token;expectedReply=p.reply[3];}
            require(bool(token),"backend response lacks data-path owner");
            response(expectedReply,p.reply[4],"backend/local reply payload corruption");
            require(*token==s.slots[s.returnSlot],"backend return full-token lineage corruption");
            require(!b.responses.empty()&&b.responses.front().token==*token,"backend ordered response lineage corruption");
        }
    }
    uint64_t value(const std::string &name) const {
        auto it=counters.find(name);return it==counters.end()?0:it->second;
    }
    void conservation() const {
        auto check=[&](const char *push,const char *pop,const char *drop,size_t pending) {
            require(value(push)==value(pop)+value(drop)+pending,"boundary conservation failure");
        };
        check("fifo_enqueue","fifo_dequeue","reset_fifo_drops",fifo.size());
        require(value("buffered_accept")+value("fast_accept")==value("buffered_response")+value("reset_buffered_drops")+stores.size(),"buffered store conservation failure");
        check("store_request","store_response","reset_store_owner_drops",storeOwners.size());
        require(value("virtual_request")==value("incoming_request")+value("physical_ingress_pass")+
            value("reset_ingress_drops")+ingress.size(),"physical ingress boundary conservation failure");
        check("translation_request","translation_reply","reset_waiting_drops",bool(waiting));
        check("translated_push","translated_pop","reset_translated_drops",translated.size());
        require(value("translated_pop")+value("identity_pass")+value("physical_ingress_pass")==value("checked_pop")+value("reset_checked_drops")+checked.size(),"checked identity boundary conservation failure");
        check("checked_pop","virtual_reply","reset_translation_owner_drops",owners.size());
        check("physical_request","physical_reply","reset_physical_drops",physicalPending.size());
        check("return_push","return_pop","reset_return_drops",returns.size());
        require(value("virtual_reply")==value("return_push")+value("return_empty_pass"),"return input/queue/pass conservation failure");
        require(value("store_response")==value("return_pop")+value("return_empty_pass"),"return output/queue/pass conservation failure");
        check("local_accept","local_reply","reset_local_reply_drops",bool(localReply));
    }
    void advance(const BackendSample &s,const P &p,const BackendOwnershipLedger &b) {
        if(s.reset) {
            auto discard=[&](auto &q,const char *key){counters[key]+=q.size();q.clear();};
            discard(fifo,"reset_fifo_drops");discard(stores,"reset_buffered_drops");
            discard(storeOwners,"reset_store_owner_drops");discard(ingress,"reset_ingress_drops");
            discard(translated,"reset_translated_drops");discard(checked,"reset_checked_drops");
            discard(owners,"reset_translation_owner_drops");discard(physicalPending,"reset_physical_drops");
            discard(returns,"reset_return_drops");
            counters["reset_waiting_drops"]+=bool(waiting);waiting.reset();
            counters["reset_local_reply_drops"]+=bool(localReply);localReply.reset();
            stalledRequest.reset();stalledReply.reset();
            ++counters["resets"];conservation();return;
        }
        counters["foreign_request"]+=p.bit(P::foreignRequest);
        counters["foreign_response"]+=p.bit(P::foreignResponse);
        counters["foreign_epoch"]+=p.bit(P::foreignEpoch);
        validate(s,p,b);++counters["checks"];
        // Capture every source BEFORE mutation, then pop old registered heads
        // before pushing successors. Empty return flow consumes its actual port
        // input/output once; internal queue push/pop remain separately observed.
        const bool emptyPass=returnEmptyPass(p);
        counters["return_empty_pass"]+=emptyPass;
        counters["return_empty_capture"]+=returns.empty()&&p.bit(P::virtualReply)&&!p.bit(P::storeResponse);
        counters["return_old_head_transfer"]+=!returns.empty()&&p.bit(P::storeResponse);
        std::optional<Transaction> bus, incomingTransfer, translatedTransfer, checkedTransfer;
        std::optional<Returned> virtualReturn, newLocal;
        if(p.bit(P::storeRequest))bus=selected(s,p);
        if(p.bit(P::incomingRequest))incomingTransfer=ingress.front();
        if(p.bit(P::translatedPush)) {
            translatedTransfer=waiting?*waiting:ingress.front();
            translatedTransfer->request=p.request[P::translatedEnq];
            translatedTransfer->fault=p.bit(P::translationEnqueuePageFault)||p.bit(P::translationEnqueueAccessFault);
            translatedTransfer->pageFault=p.bit(P::translationEnqueuePageFault);
        }
        const bool fastIngress=physicalIngressPass(p);
        if(fastIngress) {
            require(bool(bus),"physical ingress lacks accepted full-token bus owner");
            checkedTransfer=*bus;
            ++counters["physical_ingress_pass"];
        }
        if(identityPass(p)) {
            require(!checkedTransfer,"two checked shortcut owners");
            checkedTransfer=ingress.front();
            require(!checkedTransfer->fault&&!checkedTransfer->pageFault,"physical identity fabricated fault");
            ++counters["identity_pass"];
        }
        if(p.bit(P::translatedPop)) {
            require(!checkedTransfer,"two checked enqueue owners");
            checkedTransfer=translated.front();checkedTransfer->fault=p.bit(P::translatedFault);
            checkedTransfer->pageFault=p.bit(P::translatedPageFault);
        }
        if(checkedTransfer) {
            checkedTransfer->authorization=expectedAuthorization(*checkedTransfer);
            require(checkedAddress==checkedTransfer->request.address&&checkedData==checkedTransfer->request.data&&
                checkedAuth==checkedTransfer->authorization,"independent checked payload/permission mismatch");
        }
        std::optional<Transaction> newOwner;
        if(p.bit(P::checkedPop))newOwner=checked.front();
        if(p.bit(P::virtualReply))virtualReturn=Returned{owners.front(),p.reply[1]};
        if(p.bit(P::bufferedAccept)||p.bit(P::forwardedAccept))newLocal=localAccepted(p);
        for(unsigned i=0;i<BackendSample::ownerCount;++i)if(s.cancelled[i]&&contains(s.slots[i]))++counters["cancelled_owner_cycles"];
        if(p.bit(P::storeResponse)) {
            if(storeOwners.front().buffered){stores.pop_front();++counters["buffered_response"];}
            else ++counters["direct_response"];
            storeOwners.pop_front();
            if(p.bit(P::returnPop))returns.pop_front();
        }
        if(p.bit(P::virtualReply))owners.pop_front();
        if(p.bit(P::physicalReply))physicalPending.pop_front();
        if(p.bit(P::checkedPop))checked.pop_front();
        if(p.bit(P::translatedPop))translated.pop_front();
        if(p.bit(P::incomingRequest))ingress.pop_front();
        if(p.bit(P::translationReply))waiting.reset();
        else if(p.bit(P::translationRequest))waiting=incomingTransfer;
        if(newLocal){localReply=*newLocal;++counters["local_accept"];}
        if(s.reply()&&localReply){localReply.reset();++counters["local_reply"];}
        if(p.bit(P::bufferedAccept)){auto t=fifo.front();t.buffered=true;stores.push_back({t,false});}
        if(p.bit(P::fastAccept))stores.push_back({fastStore(s,p),false});
        if(bus) {
            if(bus->buffered) {
                auto it=std::find_if(stores.begin(),stores.end(),[&](const Buffered &x){return same(x.transaction,*bus);});
                require(it!=stores.end()&&!it->issued,"selected buffered owner vanished or issued twice");it->issued=true;
            }
            storeOwners.push_back(*bus);if(!fastIngress)ingress.push_back(*bus);
            ++counters[p.bit(P::drain)?"route_drain":p.bit(P::flowBuffered)?"route_flow_buffered":p.bit(P::flowFast)?"route_flow_fast":"route_direct"];
        }
        if(translatedTransfer)translated.push_back(*translatedTransfer);
        if(checkedTransfer)checked.push_back(*checkedTransfer);
        if(newOwner){owners.push_back(*newOwner);if(!newOwner->fault)physicalPending.push_back(*newOwner);else ++counters["fault_placeholder"];}
        if(p.bit(P::returnPush)){require(bool(virtualReturn),"queue capture lacks accepted return input");returns.push_back(*virtualReturn);}
        if(s.deq())fifo.pop_front();
        if(s.enq()){auto r=p.request[P::fifoEnq];fifo.push_back({s.request,r,r,false,false,false});}
        counters["fifo_enqueue"]+=s.enq();counters["fifo_dequeue"]+=s.deq();
        counters["buffered_accept"]+=p.bit(P::bufferedAccept);counters["fast_accept"]+=p.bit(P::fastAccept);
        counters["forwarded_accept"]+=p.bit(P::forwardedAccept);
        for(auto pair:{std::pair{P::storeRequest,"store_request"},{P::storeResponse,"store_response"},
            {P::virtualRequest,"virtual_request"},{P::incomingRequest,"incoming_request"},
            {P::translationRequest,"translation_request"},{P::translationReply,"translation_reply"},
            {P::translatedPush,"translated_push"},{P::translatedPop,"translated_pop"},{P::checkedPop,"checked_pop"},
            {P::physicalRequest,"physical_request"},{P::virtualReply,"virtual_reply"},{P::physicalReply,"physical_reply"},
            {P::returnPush,"return_push"},{P::returnPop,"return_pop"}})counters[pair.second]+=p.bit(pair.first);
        counters["same_cycle_translation_reply"]+=p.bit(P::translationRequest)&&p.bit(P::translationReply);
        counters["simultaneous_fifo_transfer"]+=s.enq()&&s.deq();
        counters["simultaneous_return_transfer"]+=p.bit(P::returnPush)&&p.bit(P::returnPop);
        if(s.bit(20)&&!s.bit(21))stalledRequest=std::pair{s.request,p.request[P::fifoEnq]};else stalledRequest.reset();
        if(s.bit(24)&&!s.bit(25))stalledReply=p.reply[4];else stalledReply.reset();
        conservation();
    }
    // Full category string; empty means no proven stage. Caller must refine ONLY
    // legacy issued_memory_downstream_unknown, preserving retire/launch priorities.
    std::string category(BackendToken token,const BackendSample &,const P &p) const {
        const std::string prefix="issued_memory_downstream_";
        for(unsigned i=0;i<returns.size();++i)if(returns[i].transaction.token==token)
            return prefix+(i?"return_buffer_behind_owner":p.bit(P::returnPop)?"return_buffer_accept":"return_buffer_wait");
        for(unsigned i=0;i<owners.size();++i)if(owners[i].token==token)
            return prefix+(i?"response_behind_owner":p.bit(P::virtualReply)?"response_accept":owners[i].fault?"fault_response_wait":"physical_response_wait");
        for(unsigned i=0;i<checked.size();++i)if(checked[i].token==token)
            return prefix+(i?"checked_behind_owner":p.bit(P::checkedPop)?"checked_transfer":checked[i].fault?"checked_fault_wait":"checked_physical_wait");
        for(unsigned i=0;i<translated.size();++i)if(translated[i].token==token)
            return prefix+(i?"translated_behind_owner":p.bit(P::translatedPop)?"translated_transfer":"translated_wait");
        if(waiting&&waiting->token==token)return prefix+(p.bit(P::translationReply)?"translation_response_accept":"translation_wait");
        for(unsigned i=0;i<ingress.size();++i)if(ingress[i].token==token)
            return prefix+(i?"ingress_behind_owner":p.bit(P::incomingRequest)?"ingress_transfer":"ingress_wait");
        return {};
    }
    void report() const {
        conservation();std::cout<<"DATA_PATH_LEDGER";
        for(const auto &[key,n]:counters)std::cout<<" "<<key<<"="<<n;
        std::cout<<" pending_fifo="<<fifo.size()<<" pending_buffered="<<stores.size()
            <<" pending_store_owners="<<storeOwners.size()<<" pending_ingress="<<ingress.size()
            <<" pending_waiting="<<bool(waiting)<<" pending_translated="<<translated.size()
            <<" pending_checked="<<checked.size()<<" pending_response_owners="<<owners.size()
            <<" pending_physical="<<physicalPending.size()<<" pending_returns="<<returns.size()
            <<" pending_local_reply="<<bool(localReply)<<"\n";
    }
};
