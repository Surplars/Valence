#pragma once
// STATIC DRAFT: not compiled or executed. Independent passive CPU I-transport ledger.
//
// API / phase README:
//   TransportLedger audit(optional independent ReadBeat callback);
//   beginCycle();
//   reserve(slot, full64Owner, lineAddress, tag);             // actual engine request.fire
//   permitExplicitFallback(full64Owner, source, addr, size); // caller has independently proved demand
//   offerA(valid, ready, APayload);                         // exactly once EVERY cycle, even invalid
//   acceptD(DPayload [, independentlyExpectedData]);         // only actual D.fire
//   auto result = complete(slot, tag, error);               // actual engine response.fire
//   endCycle();
// Caller orders simultaneously observed events from the reviewed current/NEXT frame.
// Old terminal D may precede a new fallback A if the caller proves that turnover legal.
// Engine slots/spec credit CANNOT borrow a same-edge complete: frame-entry occupancy is
// checked even if complete() is called first. Last D NEVER releases a fill-engine slot.
// Same-frame reserve+A is rejected by default (this CPU cache uses dispatchFlow=false);
// only an explicitly reviewed dispatch-flow variant may set allowImmediateLineA=true.
// Zero-latency A+D and final-D+complete
// are rejected for the actual registered line engine / fixed >=3-cycle CPU memory service.
// One engine request, public A observation, D acceptance and engine completion per frame.
//
// ReadBeat must read independent original service/backing bytes at an aligned 8-byte
// address. A.fire snapshots 8 beats (line) or 1 beat (fallback) BEFORE concurrent writes,
// matching the unchanged manager service. Without ReadBeat, every acceptD MUST supply
// expectedData from the independent service snapshot, NEVER from observed DUT D.data.
// Returned words are observed data already checked against that independent expectation.
// Data corruption/denial bits are accumulated; complete(error) must match their OR.
// Line A must follow reservation FIFO even while held. The caller additionally checks
// actual 512-bit completion data against complete() words, held completion/selection,
// and independently expected denied/corrupt service flags (not merely their sampled OR).
// The original memory manager owns its exact >=3-cycle service timing proof.
// The caller retains architectural demand/join/install/permission/cutoff/K obligations.
// No mapped-address authority, stale-install permission, or cancellation API exists here.
// A K cannot erase a registered engine/fallback owner or withdraw a held A.
// assertDrained checks TRANSPORT/ENGINE only, not the caller's architectural response queue.

#include <array>
#include <cstdint>
#include <deque>
#include <functional>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>

namespace cpu_prefetch_audit {

struct APayload {
    uint64_t address=0, data=0;
    unsigned opcode=4, param=0, size=6, source=0, mask=255;
    bool corrupt=false;
    bool operator==(const APayload&) const = default;
};
struct DPayload {
    uint64_t data=0;
    unsigned source=0, size=6, opcode=1, param=0, sink=0;
    bool denied=false, corrupt=false;
};
struct TransferResult {
    uint64_t ownerSeq=0, address=0;
    unsigned source=0, size=0, tag=0, beats=0;
    bool fallback=false, error=false;
    std::array<uint64_t,8> words{}, expectedWords{};
};
struct TransportCounters {
    uint64_t reservations=0, demandReservations=0, specReservations=0;
    uint64_t acceptedA=0, lineA=0, fallbackA=0, requestedBytes=0;
    uint64_t acceptedD=0, lineD=0, fallbackD=0, returnedWireBytes=0;
    uint64_t engineCompletions=0, fallbackCompletions=0, heldACycles=0;
};

class TransportLedger {
public:
    using ReadBeat = std::function<uint64_t(uint64_t)>;
    explicit TransportLedger(ReadBeat independentReadBeat={},bool allowImmediateLineA=false)
        : readBeat_(std::move(independentReadBeat)),allowImmediateLineA_(allowImmediateLineA) {}

    void beginCycle() {
        check(!inCycle_,"beginCycle while previous frame remains open");
        inCycle_=true; ++cycle_;
        for(unsigned i=0;i<4;++i) lineBusyAtEntry_[i]=bool(lines_[i]);
        specBusyAtEntry_=bool(specSlot_);
        reservedThisCycle_=aObservedThisCycle_=dAcceptedThisCycle_=completedThisCycle_=false;
    }
    void endCycle() {
        frame(); check(aObservedThisCycle_,"missing public A observation in frame");
        inCycle_=false;
    }

    void reserve(unsigned slot,uint64_t ownerSeq,uint64_t address,unsigned tag) {
        frame(); check(slot<4,"line reservation slot exceeds four entries");
        check(tag<=1,"unknown line caller tag (only demand0/spec1)");
        check((address&63)==0 && address<=UINT64_MAX-63,"unaligned/overflow line reservation");
        check(!reservedThisCycle_,"more than one line engine request in a frame");
        check(!lineBusyAtEntry_[slot]&&!lines_[slot],"line slot reused without old-current credit");
        // Actual engine uses current free-mask PriorityEncoder, not D/completion bypass.
        unsigned first=0;while(first<4&&lineBusyAtEntry_[first])++first;
        check(slot==first,"line engine reservation violates first-current-free policy");
        if(tag==1) check(!specBusyAtEntry_&&!specSlot_,"speculative engine credit reused before next frame");
        Entry e;e.result.ownerSeq=ownerSeq;e.result.address=address;e.result.source=slot;
        e.result.size=6;e.result.tag=tag;e.reservedFrame=cycle_;
        lines_[slot]=e;sendQueue_.push_back(slot);reservedThisCycle_=true;++counts_.reservations;
        if(tag==1){specSlot_=slot;++counts_.specReservations;}else ++counts_.demandReservations;
    }

    // This is an authorization ticket supplied by the demand-provenance owner.
    // It does not infer authority from a DUT address or a mapped-memory predicate.
    void permitExplicitFallback(uint64_t ownerSeq,unsigned source,uint64_t address,unsigned size) {
        frame(); check(source>=4&&source<8,"fallback source is not full source4..7");
        check(size==2||size==3,"fallback must be 4-byte or 8-byte Get");
        check(!(address&((uint64_t(1)<<size)-1))&&address<=UINT64_MAX-((uint64_t(1)<<size)-1),
            "unaligned/overflow explicit fallback");
        auto &entry=fallbacks_[source-4];check(!entry,"fallback source already permitted or outstanding");
        Entry e;e.result.ownerSeq=ownerSeq;e.result.address=address;e.result.source=source;
        e.result.size=size;e.result.fallback=true;entry=e;
    }

    void offerA(bool valid,bool ready,const APayload &a) {
        frame();check(!aObservedThisCycle_,"multiple A observations in one frame");aObservedThisCycle_=true;
        if(heldA_)check(valid&&a==*heldA_,"irrevocable held A was withdrawn or changed (including source)");
        if(!valid){heldA_.reset();return;}
        check(a.source<8,"I A full source outside0..7");
        check(a.opcode==4&&a.param==0&&!a.corrupt&&a.data==0,"unexpected I A opcode/param/data/corrupt");
        Entry &e=entry(a.source);
        check(!e.aAccepted,"duplicate A for an already accepted source");
        if(!e.result.fallback){
            check(!sendQueue_.empty()&&sendQueue_.front()==a.source,"line A violated reservation/send FIFO order");
            if(!allowImmediateLineA_)check(e.reservedFrame<cycle_,"line A borrowed same-frame reservation despite registered dispatch");
        }
        check(a.address==e.result.address&&a.size==e.result.size,"A address/size differs from authorized owner");
        const unsigned mask=a.size==2?(15u<<unsigned(a.address&7)):255u;
        check(a.mask==mask,"I Get byte mask differs from authorized owner");
        heldA_=ready?std::nullopt:std::optional<APayload>(a);
        if(!ready){++counts_.heldACycles;return;}
        e.aAccepted=true;e.acceptedAFrame=cycle_;
        if(readBeat_){
            const unsigned n=e.result.fallback?1:8;
            for(unsigned i=0;i<n;++i)e.result.expectedWords[i]=readBeat_((a.address&~uint64_t(7))+8*i);
            e.hasSnapshot=true;
        }
        if(!e.result.fallback)sendQueue_.pop_front();
        ++counts_.acceptedA;counts_.requestedBytes+=uint64_t(1)<<a.size;
        if(e.result.fallback)++counts_.fallbackA;else ++counts_.lineA;
    }

    // Return a checked terminal-beat snapshot. Line engine ownership remains live.
    std::optional<TransferResult> acceptD(const DPayload &d) {
        frame();const Entry &e=entry(d.source);
        check(e.hasSnapshot,"D requires independent A-time ReadBeat snapshot or explicit expectedData");
        check(e.result.beats<8,"D beyond checked word storage");
        return acceptDImpl(d,e.result.expectedWords[e.result.beats]);
    }
    std::optional<TransferResult> acceptD(const DPayload &d,uint64_t independentExpectedData) {
        frame();return acceptDImpl(d,independentExpectedData);
    }

    TransferResult complete(unsigned slot,unsigned tag,bool error) {
        frame();check(slot<4,"engine completion slot exceeds four entries");
        check(!completedThisCycle_,"more than one engine completion in a frame");
        Entry &e=entry(slot);
        check(e.aAccepted&&e.result.beats==8,"engine completion before exactly eight accepted D beats");
        check(e.lastDFrame<cycle_,"engine completion borrowed same-frame final D");
        check(tag==e.result.tag&&error==e.result.error,"engine completion tag/error differs from source owner");
        TransferResult result=e.result;
        if(tag==1){check(specSlot_&&*specSlot_==slot,"spec completion lost its sole engine credit");specSlot_.reset();}
        lines_[slot].reset();completedThisCycle_=true;++counts_.engineCompletions;
        return result;
    }

    bool hasSource(unsigned source) const {
        check(source<8,"source query outside0..7");return source<4?bool(lines_[source]):bool(fallbacks_[source-4]);
    }
    TransferResult sourceSnapshot(unsigned source) const { return entry(source).result; }
    std::optional<unsigned> speculativeSource() const { return specSlot_; }
    const TransportCounters &counters() const { return counts_; }
    void assertDrained() const {
        check(!inCycle_,"drain assertion requires closed observation frame");
        check(!heldA_&&!specSlot_&&sendQueue_.empty(),"held A/send FIFO/speculative credit remains at drain");
        for(unsigned i=0;i<4;++i)check(!lines_[i]&&!fallbacks_[i],"reserved/accepted source remains at drain");
        check(counts_.reservations==counts_.engineCompletions,"engine reservation/completion conservation");
        check(counts_.lineA==counts_.engineCompletions,"line A/completion conservation");
        check(counts_.fallbackA==counts_.fallbackCompletions,"fallback A/D conservation");
        check(counts_.lineD==8*counts_.engineCompletions&&counts_.fallbackD==counts_.fallbackCompletions,
            "terminal D beat conservation");
    }

private:
    struct Entry {
        TransferResult result;
        bool aAccepted=false,hasSnapshot=false;
        uint64_t reservedFrame=0,acceptedAFrame=0,lastDFrame=0;
    };
    std::array<std::optional<Entry>,4> lines_{},fallbacks_{};
    std::deque<unsigned> sendQueue_;
    std::optional<unsigned> specSlot_;
    std::optional<APayload> heldA_;
    std::array<bool,4> lineBusyAtEntry_{};
    bool inCycle_=false,specBusyAtEntry_=false,reservedThisCycle_=false;
    bool aObservedThisCycle_=false,dAcceptedThisCycle_=false,completedThisCycle_=false;
    uint64_t cycle_=0;
    ReadBeat readBeat_;
    bool allowImmediateLineA_=false;
    TransportCounters counts_;
    static void check(bool ok,const char *message) {
        if(!ok)throw std::runtime_error(std::string("PREFETCH_TRANSPORT_AUDIT: ")+message);
    }
    void frame() const { check(inCycle_,"event outside beginCycle/endCycle"); }
    Entry &entry(unsigned source) {
        check(source<8,"full source outside0..7");
        auto &e=source<4?lines_[source]:fallbacks_[source-4];
        check(bool(e),"source has no independently registered transport owner");return *e;
    }
    const Entry &entry(unsigned source) const {
        check(source<8,"full source outside0..7");
        const auto &e=source<4?lines_[source]:fallbacks_[source-4];
        check(bool(e),"source has no independently registered transport owner");return *e;
    }
    std::optional<TransferResult> acceptDImpl(const DPayload &d,uint64_t expectedData) {
        check(!dAcceptedThisCycle_,"multiple I D acceptances in a frame");
        Entry &e=entry(d.source);
        check(e.aAccepted&&e.acceptedAFrame<cycle_,"D has no older accepted A");
        const unsigned required=e.result.fallback?1:8;
        check(e.result.beats<required,"extra/duplicate D beat after terminal beat");
        check(d.opcode==1&&d.param==0&&d.sink==0&&d.size==e.result.size,
            "D opcode/param/sink/size differs from fixed instruction service contract");
        if(e.hasSnapshot)check(expectedData==e.result.expectedWords[e.result.beats],"explicit D golden differs from A-time snapshot");
        check(d.data==expectedData,"D data differs from independent byte-memory snapshot");
        e.result.words[e.result.beats]=d.data;e.result.expectedWords[e.result.beats]=expectedData;
        ++e.result.beats;e.result.error=e.result.error||d.denied||d.corrupt;e.lastDFrame=cycle_;
        dAcceptedThisCycle_=true;++counts_.acceptedD;counts_.returnedWireBytes+=8;
        if(e.result.fallback)++counts_.fallbackD;else ++counts_.lineD;
        if(e.result.beats!=required)return std::nullopt;
        TransferResult result=e.result;
        if(e.result.fallback){fallbacks_[d.source-4].reset();++counts_.fallbackCompletions;}
        return result;
    }
};
} // namespace cpu_prefetch_audit
