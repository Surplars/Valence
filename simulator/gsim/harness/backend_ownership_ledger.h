#pragma once
#include <array>
#include <cstdint>
#include <deque>
#include <stdexcept>
#include <string>
#include <algorithm>

// Independent host transaction ownership. Tokens are never truncated to ROB indices.
// Recovery/cancellation intentionally does not clear either queue: accepted reads drain.
struct BackendToken {
    uint64_t tag=0; unsigned index=0;
    bool operator==(const BackendToken &) const = default;
};
struct BackendSample {
    uint64_t events=0; BackendToken head, queueHead, request, start, complete;
    std::array<BackendToken,2> slots{};
    std::array<unsigned,2> phase{};
    std::array<bool,2> live{}, cancelled{}, parallel{};
    unsigned returnSlot=0, fifoCount=0, storeCause=0, commits=0;
    bool reset=false, headValid=false, headDone=false, headQueued=false, headMemory=false, recovery=false;
    bool bit(unsigned n) const { return (events>>n)&1; }
    bool enq() const { return bit(20)&&bit(21); }
    bool deq() const { return bit(22)&&bit(23); }
    bool reply() const { return bit(24)&&bit(25); }
};
struct BackendOwnershipLedger {
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
        for(unsigned i=0;i<2;++i)if(s.live[i]&&s.slots[i]==token)return true;
        return false;
    }
    void validate(const BackendSample &s) {
        require(requests.size()==s.fifoCount,"hardware FIFO count differs from shadow");
        require(s.bit(22)==!requests.empty(),"hardware FIFO validity differs from shadow");
        require(responses.size()<=2 && requests.size()<=2,"two-slot capacity exceeded");
        require(!(s.live[0]&&s.live[1]&&s.slots[0]==s.slots[1]),"duplicate live full token");
        if(s.headValid)require(s.head==s.queueHead,"ROB and reservation head full tokens disagree");
        for(const auto &e:responses)require(resident(s,e.token),"accepted request lost physical LSU owner");
        for(unsigned i=0;i<2;++i)if(s.live[i]&&s.phase[i]==2)
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
        int slot=-1; for(unsigned i=0;i<2;++i)if(s.live[i]&&s.slots[i]==s.head)slot=int(i);
        if(slot<0)return "issued_memory_unknown_owner";
        if(s.phase[slot]==3)return s.bit(26)&&s.bit(27)&&s.complete==s.head?
            "issued_memory_completion_accept":"issued_memory_result_ready";
        if(s.reply()&&s.returnSlot<2&&s.slots[s.returnSlot]==s.head)return "issued_memory_response_accept";
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
        if(s.reset){resetRequestDrops+=requests.size();resetResponseDrops+=responses.size();requests.clear();responses.clear();++resets;return;}
        validate(s);
        for(unsigned i=0;i<2;++i)if(s.cancelled[i]&&find(s.slots[i]))++cancellationWhileOutstanding;
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
            require(s.bit(28)&&s.returnSlot<2,"response lacks hardware owner slot");
            require(!responses.empty(),"response shadow underflow");
            require(responses.front().stage!=fifo,"response precedes StoreBuffer acceptance");
            require(responses.front().token==s.slots[s.returnSlot],"response full-token owner corruption");
            responses.pop_front();++returns;
        }
        simultaneous+=s.enq()&&s.deq();
        require(enqueues-returns-resetResponseDrops==responses.size(),"response conservation failed");
        require(enqueues-dequeues-resetRequestDrops==requests.size(),"FIFO conservation failed");
    }
};
