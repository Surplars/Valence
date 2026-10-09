#pragma once
#include <array>
#include <cstdint>
#include <deque>
#include <stdexcept>
#include <string>
#include <algorithm>
#include <optional>

#ifndef BACKEND_OWNER_COUNT
#define BACKEND_OWNER_COUNT 2
#endif
#ifndef BACKEND_REQUEST_CAPACITY
#define BACKEND_REQUEST_CAPACITY BACKEND_OWNER_COUNT
#endif
static_assert(BACKEND_REQUEST_CAPACITY==BACKEND_OWNER_COUNT, "observed IntegerBackend FIFO is sized by memoryEntries");
static_assert(BACKEND_OWNER_COUNT==2 || BACKEND_OWNER_COUNT==4, "backend owner probes support exactly two or four owners");

// Independent host transaction ownership. Tokens are never truncated to ROB indices.
// Recovery/cancellation intentionally does not clear either queue: accepted reads drain.
struct BackendToken {
    uint64_t tag=0; unsigned index=0;
    bool operator==(const BackendToken &) const = default;
};
struct BackendSample {
    static constexpr unsigned ownerCount=BACKEND_OWNER_COUNT;
    // IntegerBackend requests and ParallelLoadStoreUnit owners both use memoryEntries.
    // Later adapter ingress/checked/response buffers retain their separate depth two.
    static constexpr unsigned requestCapacity=BACKEND_REQUEST_CAPACITY;
    uint64_t events=0; BackendToken head, queueHead, request, start, complete;
    std::array<BackendToken,ownerCount> slots{};
    std::array<unsigned,ownerCount> phase{};
    std::array<bool,ownerCount> live{}, cancelled{}, parallel{};
    unsigned returnSlot=0, fifoCount=0, storeCause=0, commits=0;
    bool reset=false, headValid=false, headDone=false, headQueued=false, headMemory=false, recovery=false;
    unsigned liveCount() const { return unsigned(std::count(live.begin(),live.end(),true)); }
    bool bit(unsigned n) const { return (events>>n)&1; }
    bool enq() const { return bit(20)&&bit(21); }
    bool deq() const { return bit(22)&&bit(23); }
    bool reply() const { return bit(24)&&bit(25); }
};
struct BackendOwnershipLedger {
    static constexpr unsigned ownerCount=BackendSample::ownerCount;
    static constexpr unsigned requestCapacity=BackendSample::requestCapacity;
    // Legacy two-owner traces preserve their existing checks. Four-owner traces
    // additionally track EVERY slot from reset/start through final release.
    // This shadow is never initialized from observed live owners.
    static constexpr bool trackSlotLifetimes=ownerCount==4;
    struct Slot { BackendToken token; bool live=false,cancelled=false,parallel=false; unsigned phases=1; };
    std::array<Slot,ownerCount> slotOwners{};
    std::optional<BackendToken> stalledRequest;
    enum Stage { fifo, localReply, downstream };
    struct Entry { BackendToken token; Stage stage; };
    std::deque<BackendToken> requests;
    std::deque<Entry> responses;
    uint64_t enqueues=0, dequeues=0, returns=0, localAccepts=0, directAccepts=0;
    uint64_t simultaneous=0, cancellationWhileOutstanding=0, checks=0, resets=0, fastStores=0, forwardedStarts=0;
    uint64_t resetRequestDrops=0,resetResponseDrops=0;
    static void require(bool ok,const char *message) { if(!ok)throw std::runtime_error(std::string("backend ownership: ")+message); }
    const Entry *find(BackendToken token) const {
        for(const auto &e:responses)if(e.token==token)return &e;
        return nullptr;
    }
    bool resident(const BackendSample &s,BackendToken token) const {
        for(unsigned i=0;i<ownerCount;++i)if(s.live[i]&&s.slots[i]==token)return true;
        return false;
    }
    void validate(const BackendSample &s) {
        require(requests.size()==s.fifoCount,"hardware FIFO count differs from shadow");
        require(s.bit(22)==!requests.empty(),"hardware FIFO validity differs from shadow");
        require(responses.size()<=ownerCount,"LSU response-owner capacity exceeded");
        require(requests.size()<=requestCapacity,"backend request FIFO capacity exceeded");
        for(unsigned i=0;i<ownerCount;++i)for(unsigned j=0;j<i;++j)
            require(!(s.live[i]&&s.live[j]&&s.slots[i]==s.slots[j]),"duplicate live full token");
        if constexpr(trackSlotLifetimes)validateSlots(s);
        if(stalledRequest)require(s.bit(20)&&s.bit(41)&&s.request==*stalledRequest,
            "stalled request full-token owner changed or vanished");
        if(s.headValid)require(s.head==s.queueHead,"ROB and reservation head full tokens disagree");
        for(const auto &e:responses)require(resident(s,e.token),"accepted request lost physical LSU owner");
        for(unsigned i=0;i<ownerCount;++i)if(s.live[i]&&s.phase[i]==2)
            require(find(s.slots[i]),"response-phase LSU lacks accepted request owner");
        size_t queued=0;
        for(const auto &e:responses)if(e.stage==fifo){
            require(queued<requests.size()&&requests[queued]==e.token,"request/response shadow order diverged");++queued;
        }
        require(queued==requests.size(),"FIFO shadow contains absent response owner");
        if(s.bit(26))require(resident(s,s.complete),"completion does not match live full token");
        if(s.enq())require(s.bit(41)&&(resident(s,s.request)||(s.bit(3)&&s.request==s.start)),
            "request acceptance does not match live or same-cycle start full token");
        ++checks;
    }
    void validateSlots(const BackendSample &s) const {
        for(unsigned i=0;i<ownerCount;++i) {
            const auto &old=slotOwners[i];
            require(s.live[i]==old.live,"slot live owner appeared or was prematurely released");
            require(s.phase[i]<4&&s.live[i]==(s.phase[i]!=0),"slot live/phase mismatch");
            if(old.live) {
                require(s.slots[i]==old.token,"slot full-token generation or position changed");
                require(old.phases&(1U<<s.phase[i]),"slot phase changed without authorized handshake");
                require(s.parallel[i]==old.parallel,"slot parallel class changed during ownership");
            }
        }
        if(s.bit(26)) {
            const auto i=slotOf(s,s.complete);
            require(i<ownerCount&&s.phase[i]==3&&!slotOwners[i].cancelled,
                "completion lacks noncancelled result owner");
        }
        if(s.reply())require(s.returnSlot<ownerCount&&s.live[s.returnSlot]&&s.phase[s.returnSlot]==2,
            "response lacks response-phase full-token owner");
        if(s.enq()&&!(s.bit(3)&&s.request==s.start)) {
            const auto i=slotOf(s,s.request);
            require(i<ownerCount&&s.phase[i]==1,"request lacks request-phase full-token owner");
        }
    }
    static unsigned slotOf(const BackendSample &s,BackendToken token) {
        for(unsigned i=0;i<ownerCount;++i)if(s.live[i]&&s.slots[i]==token)return i;
        return ownerCount;
    }
    void advanceSlots(const BackendSample &s) {
        unsigned startSlot=ownerCount;
        if(s.bit(3)) {
            // Select the completing old owner, otherwise the first idle slot.
            // This derives selection from full-token completion, not a DUT slot-ID tap.
            if(s.bit(26)) {
                startSlot=slotOf(s,s.complete);
                require(s.bit(27),"replacement start precedes completion acceptance");
            } else for(unsigned i=0;i<ownerCount;++i)if(!s.live[i]){startSlot=i;break;}
            require(startSlot<ownerCount,"start has no independently available slot");
            require(!resident(s,s.start),"start reuses a live full-token generation");
        }
        for(unsigned i=0;i<ownerCount;++i) {
            auto &next=slotOwners[i];
            next.phases=1U<<s.phase[i];
            if(!s.live[i])continue;
            next.cancelled=next.cancelled||s.cancelled[i];
            if(s.phase[i]==1&&s.enq()&&s.request==s.slots[i])next.phases=1U<<2;
            if(s.reply()&&s.returnSlot==i) {
                require(!s.bit(35)||!next.cancelled,"cancelled response retired through fast-load path");
                next.phases=1U<<(s.bit(35)?0:3);
            }
            if(s.phase[i]==3&&((s.bit(26)&&s.bit(27)&&s.complete==s.slots[i])||next.cancelled))next.phases=1;
            if(next.phases==1)next.live=false;
        }
        if(startSlot<ownerCount) {
            auto &next=slotOwners[startSlot];
            // A start which neither requests nor forwards can be request-arbitration
            // stalled or an immediate alignment/access fault. Both retain the token.
            next={s.start,true,false,s.bit(8),(1U<<1)|(1U<<3)};
            if(s.bit(36))next.phases=1U<<3;
            else if(s.enq()&&s.request==s.start)next.phases=1U<<2;
            else if(s.bit(41)&&s.request==s.start)next.phases=1U<<1;
        }
    }
    // Classify from the pre-edge state. Handshake cycles get their own launch/return bins.
    std::string category(const BackendSample &s) const {
        if(s.commits)return s.commits==2?"progress_two":"progress_one";
        if(s.recovery)return "recovery";
        if(!s.headValid)return "empty";
        if(s.headDone)return "done_awaiting_retire";
        if(s.headQueued){
            if(s.bit(4)||(s.bit(3)&&s.start==s.head))return "queued_memory_launch";
            if(!s.headMemory){
                if(s.bit(30)||s.bit(31))return "queued_special_unknown";
                return s.bit(29)?"queued_nonmemory_eligible":"queued_nonmemory_not_eligible";
            }
            if(!s.bit(0))return "queued_memory_operands";
            if(!s.bit(2))return "queued_memory_preparation_or_selection";
            if(!s.bit(5))return "queued_memory_no_available_slot";
            if(!s.bit(6)||(!s.bit(8)&&!s.bit(7)))return "queued_memory_serial_exclusion";
            if(!s.bit(10))return "queued_memory_slot_acceptance";
            return "queued_memory_other_gating";
        }
        if(!s.headMemory)return "issued_nonmemory";
        int slot=-1; for(unsigned i=0;i<ownerCount;++i)if(s.live[i]&&s.slots[i]==s.head)slot=int(i);
        if(slot<0)return "issued_memory_unknown_owner";
        if(s.phase[slot]==3)return s.bit(26)&&s.bit(27)&&s.complete==s.head?
            "issued_memory_completion_accept":"issued_memory_result_ready";
        if(s.reply()&&s.returnSlot<ownerCount&&s.slots[s.returnSlot]==s.head)return "issued_memory_response_accept";
        if(s.phase[slot]==1){
            if(s.enq()&&s.request==s.head)return "issued_memory_request_launch";
            return s.bit(41)&&s.request==s.head?"issued_memory_request_fifo_backpressure":"issued_memory_request_not_selected";
        }
        const Entry *e=find(s.head);
        if(!e)return "issued_memory_unknown_stage";
        if(e->stage==fifo){
            if(requests.empty()||!(requests.front()==s.head))return "issued_memory_fifo_behind_owner";
            if(s.deq())return "issued_memory_fifo_launch";
            return "issued_memory_fifo_store_cause_"+std::to_string(s.storeCause);
        }
        return e->stage==localReply?"issued_memory_local_reply_wait":"issued_memory_downstream_unknown";
    }
    void advance(const BackendSample &s) {
        if(s.reset){resetRequestDrops+=requests.size();resetResponseDrops+=responses.size();requests.clear();responses.clear();slotOwners={};stalledRequest.reset();++resets;return;}
        validate(s);
        for(unsigned i=0;i<ownerCount;++i)if(s.cancelled[i]&&find(s.slots[i]))++cancellationWhileOutstanding;
        fastStores+=s.bit(43);forwardedStarts+=s.bit(36);
        // Non-flow request FIFO consumes the OLD head before this cycle's enqueue.
        if(s.deq()){
            require(!requests.empty(),"FIFO dequeue underflow");auto token=requests.front();requests.pop_front();
            auto it=std::find_if(responses.begin(),responses.end(),[&](const Entry &e){return e.token==token;});
            require(it!=responses.end()&&it->stage==fifo,"dequeue lost full-token owner");
            bool local=s.bit(37)||s.bit(38);it->stage=local?localReply:downstream;
            localAccepts+=local;directAccepts+=!local;++dequeues;
        }
        if(s.enq()){
            require(!find(s.request),"duplicate accepted token");
            requests.push_back(s.request);responses.push_back({s.request,fifo});++enqueues;
        }
        // A local acknowledgement can coincide with dequeue. It still owns the ordered response.
        if(s.reply()){
            require(s.bit(28)&&s.returnSlot<ownerCount,"response lacks hardware owner slot");
            require(!responses.empty(),"response shadow underflow");
            require(responses.front().stage!=fifo,"response precedes StoreBuffer acceptance");
            require(responses.front().token==s.slots[s.returnSlot],"response full-token owner corruption");
            responses.pop_front();++returns;
        }
        if constexpr(trackSlotLifetimes)advanceSlots(s);
        if(s.bit(20)&&!s.bit(21))stalledRequest=s.request;else stalledRequest.reset();
        require(responses.size()<=ownerCount,"LSU response-owner capacity exceeded after edge");
        require(requests.size()<=requestCapacity,"backend request FIFO capacity exceeded after edge");
        simultaneous+=s.enq()&&s.deq();
        require(enqueues-returns-resetResponseDrops==responses.size(),"response conservation failed");
        require(enqueues-dequeues-resetRequestDrops==requests.size(),"FIFO conservation failed");
    }
};
