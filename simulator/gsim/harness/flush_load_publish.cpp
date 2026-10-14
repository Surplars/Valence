#include "FlushLoadPublishGsim.h"
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <memory>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

// The oracle is driven only by accepted public transactions. No DUT register is
// read or written. Slot observations below check the model, never initialize it.
namespace {
constexpr uint64_t RAM = 0x80010000ULL, VA = 0x40000000ULL;
void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
struct Op {
    Token token;
    uint64_t address = 0, physical = 0, data = 0, pc = 0, beat = 0;
    unsigned size = 3, atomicOp = 0, epoch = 7, slot = 99, destination = 0, publications = 0;
    bool destinationValid = true, fastRetired = false;
    bool store = false, atomic = false, virt = true, prechecked = true, unsign = false;
    bool forward = false, denied = false, parallel = true, frozen = false, qualified = false;
    bool error = false, page = false, accepted = false, queued = false, issued = false;
    bool returned = false, responded = false, completed = false, cancelled = false, drained = false;
    uint64_t startCycle = 0, queueCycle = 0, issueCycle = 0, returnCycle = 0, responseCycle = 0;
    bool misaligned() const { return address & ((1U << size) - 1); }
    bool local() const { return misaligned() || denied || forward; }
    bool exception() const { return local() ? misaligned() || denied : error || page; }
    bool destinationEligible() const { return destinationValid && destination && !store && !atomic; }
};
using Ptr = std::shared_ptr<Op>;
unsigned mask(const Op &o) { return ((1U << (1U << o.size)) - 1) << (o.address & 7); }
uint64_t value(uint64_t beat, const Op &o) {
    const unsigned bits = 8U << o.size;
    const uint64_t shifted = beat >> ((o.address & 7) * 8);
    if (bits == 64) return shifted;
    const uint64_t low = shifted & ((1ULL << bits) - 1);
    return !o.unsign && (low & (1ULL << (bits - 1))) ? low | (~0ULL << bits) : low;
}
struct Request {
    uint64_t address, data;
    unsigned size, mask, atomicOp, handle, epoch;
    bool store, atomic, virt, prechecked, uncached, hint;
    bool operator==(const Request &) const = default;
};
Request request(const Op &o) {
    return {o.prechecked ? o.physical : o.address,
        o.atomic ? o.data : o.data << ((o.address & 7) * 8), o.size, mask(o), o.atomicOp,
        o.slot, o.epoch, o.store, o.atomic, o.virt && !o.prechecked, o.prechecked, false, false};
}
struct Reply {
    Ptr owner; unsigned handle; uint64_t data; bool error, page;
    bool operator==(const Reply &r) const { return handle == r.handle && data == r.data && error == r.error && page == r.page; }
};
struct Slot { Ptr owner; unsigned phase = 0; };

class Bench {
    // Zero storage before object lifetime; use the normal GSIM reset/activation
    // path, without writing generated internals or treating zero payload as valid.
    alignas(SFlushLoadPublishGsim) std::byte storage[sizeof(SFlushLoadPublishGsim)]{};
    SFlushLoadPublishGsim &d;
    std::array<Slot, 4> slots{};
    std::vector<Ptr> owners;
    std::deque<Ptr> queue;
    std::deque<Reply> buffered;
    std::optional<Request> heldRequest, heldExternal;
    std::optional<Token> heldRequestOwner;
    std::optional<Reply> heldInput;
    unsigned nextId = 1;
    bool lastInputFire = false;
public:
    uint64_t cycle = 0;
    bool memoryReady = true, completeReady = true, holdEnqueue = false, holdQueue = false;
    bool holdResponse = false, direct = false, automaticReplies = false, fastRetire = false;
    unsigned cancel = 0, flushCauses = 0;
    bool exceptionBlock = false, inconsistentAdmission = false, mirrorReserve = false;
    unsigned mirrorExpected = 0, flushBlocked = 0, candidateOnlyCapacity = 0;
    std::optional<Reply> offeredReply;
    std::optional<Token> relax;
    std::string mutation;
    unsigned starts = 0, enqueues = 0, issues = 0, returns = 0, responses = 0, completions = 0, discards = 0;
    unsigned maxLive = 0, maxPending = 0, requestHolds = 0, externalHolds = 0, responseHolds = 0;
    unsigned completeStalls = 0, overlap = 0, concurrentEnqueueReply = 0, replacement = 0, localResults = 0;
    unsigned directHolds = 0, directFires = 0, negativeAnchors = 0;
    unsigned publications = 0, heldCycles = 0, fastRetires = 0;
    unsigned responseOtherStart = 0, responseOtherRequestStall = 0, forwardReplacements = 0;
    unsigned suppressedFault = 0, suppressedCancel = 0, suppressedDestination = 0;
    Ptr lastPublished;
    bool lastResponseReady = false;
    Bench() : d(*::new (static_cast<void *>(storage)) SFlushLoadPublishGsim) {
        static_assert(std::is_trivially_copyable_v<SFlushLoadPublishGsim>);
        d.LOG_START = 1; d.activateAll(); drive({}); d.set_reset(1);
        d.step(); d.resetAll(); d.step(); d.resetAll(); d.activateAll(); d.set_reset(0);
        for (unsigned i = 0; i < 8; ++i) tick();
    }
    Ptr op(unsigned size = 3) {
        const unsigned id = nextId++;
        auto x = std::make_shared<Op>();
        x->token = {id % 16, 0x8000000100000000ULL + id};
        // Accepted operation identity owns the destination, never DUT publication.
        x->destination = 1 + (id * 7) % 47;
        const unsigned offset = (id * 32 + (size == 0 ? 3 : size == 1 ? 2 : size == 2 ? 4 : 0)) & 4095;
        x->address = VA + offset; x->physical = RAM + offset; x->size = size;
        x->pc = 0x80002000ULL + 4 * id; x->data = 0x87654321fedcba98ULL ^ (id * 257);
        x->beat = 0x80fedcba98765480ULL ^ (0x0101010101010101ULL * id);
        return x;
    }
    void anchor(const std::string &name) {
        ++negativeAnchors; std::cout << "TAGGED_LOAD_PUBLISH_ANCHOR " << name << " cycle=" << cycle << std::endl;
    }
    Token observedOwner(unsigned slot) const {
        switch (slot) {
#define OWNER(N) case N: return {unsigned(d.get_io$$owner##N##$$index()), uint64_t(d.get_io$$owner##N##$$tag())};
            OWNER(0) OWNER(1) OWNER(2) OWNER(3)
#undef OWNER
        }
        throw std::runtime_error("invalid observed slot");
    }
    Ptr find(Token token) const {
        for (const auto &x : owners) if (x->token == token) return x;
        throw std::runtime_error("independent full-token owner missing");
    }
    unsigned publishDestination(unsigned slot) const {
        switch (slot) {
#define PUB(N) case N: return unsigned(d.get_io$$publishDestination##N());
            PUB(0) PUB(1) PUB(2) PUB(3)
#undef PUB
        }
        throw std::runtime_error("invalid publication slot");
    }
    unsigned heldDestination(unsigned slot) const {
        switch (slot) {
#define HELD(N) case N: return unsigned(d.get_io$$heldDestination##N());
            HELD(0) HELD(1) HELD(2) HELD(3)
#undef HELD
        }
        throw std::runtime_error("invalid held slot");
    }
    uint64_t heldData(unsigned slot) const {
        switch (slot) {
#define DATA(N) case N: return uint64_t(d.get_io$$heldData##N());
            DATA(0) DATA(1) DATA(2) DATA(3)
#undef DATA
        }
        throw std::runtime_error("invalid held slot");
    }
    void verifyHeld() {
        unsigned expected = 0;
        for (unsigned i = 0; i < 4; ++i) {
            const auto &s = slots[i];
            if (s.owner && s.phase == 3 && !s.owner->cancelled && !s.owner->exception() &&
                s.owner->destinationEligible()) {
                const auto &o = *s.owner; expected |= 1U << i;
                check(o.publications == 1, "HELD_WITHOUT_PUBLICATION: saved successful owner was not published exactly once");
                check(heldDestination(i) == o.destination && heldData(i) == value(o.beat,o),
                    "HELD_OWNER_DATA: held destination/value differs from original accepted owner");
                ++heldCycles;
            }
        }
        check(unsigned(d.get_io$$held()) == expected, "HELD_MASK: independent saved-owner mask mismatch");
    }
    void verifyPublication(const std::array<Ptr,4> &expected) {
        unsigned expectedMask = 0;
        for (unsigned i = 0; i < 4; ++i) if (expected[i]) expectedMask |= 1U << i;
        unsigned observedMask = d.get_io$$publish();
        if (mutation == "oracle-publish-valid" && expectedMask) {
            anchor("oracle_publish_valid"); observedMask ^= expectedMask & (~expectedMask + 1U);
        }
        if (mutation == "oracle-publish-duplicate" && !expectedMask && lastPublished) {
            anchor("oracle_publish_duplicate"); observedMask |= 1U << lastPublished->slot;
        }
        check(observedMask == expectedMask, "ORACLE_PUBLISH_VALID: successful accepted-owner publication mask mismatch");
        for (unsigned i = 0; i < 4; ++i) if (expected[i]) {
            const auto &x = expected[i];
            unsigned observedDestination = publishDestination(i);
            if (mutation == "oracle-publish-destination") {
                anchor("oracle_publish_destination"); observedDestination ^= 1U;
            }
            check(observedDestination == x->destination,
                "ORACLE_PUBLISH_DESTINATION: publication lost original accepted-owner destination");
            check(x->publications == 0, "ORACLE_PUBLISH_DUPLICATE: owner published more than once");
            ++x->publications; ++publications; lastPublished = x;
        }
    }
    void drive(const Ptr &x) {
        Op empty; const Op &o = x ? *x : empty;
        d.set_io$$flushCauses(flushCauses); d.set_io$$exceptionBlock(exceptionBlock);
        d.set_io$$inconsistentAdmission(inconsistentAdmission);
        d.set_io$$mirrorAllocate(true); d.set_io$$mirrorReserve(mirrorReserve);
        d.set_io$$start$$valid(bool(x));
        d.set_io$$destination$$valid(bool(x) && o.destinationValid);
        d.set_io$$destination$$bits(o.destination);
        d.set_io$$fastLoadRetire(fastRetire);
#define START(F,V) d.set_io$$start$$bits$$##F(V)
        START(token$$index,o.token.index); START(token$$tag,o.token.tag); START(pc,o.pc);
        START(address,o.address); START(physicalAddress,o.physical); START(data,o.data);
        START(size,o.size); START(store,o.store); START(atomic,o.atomic); START(atomicOp,o.atomicOp);
        START(unsigned,o.unsign); START(accessDenied,o.denied); START(virtualized,o.virt);
        START(precheckedLoad,o.prechecked); START(translationEpoch,o.epoch);
        START(forward$$valid,o.forward); START(forward$$bits,o.beat);
        START(canonicalStoreEpoch$$valid,o.frozen); START(canonicalStoreEpoch$$bits,o.epoch);
        START(frozenStoreProof$$valid,o.frozen); START(frozenStoreProof$$bits$$address,o.address);
        START(frozenStoreProof$$bits$$physicalAddress,o.physical);
        START(frozenStoreProof$$bits$$size,o.size); START(frozenStoreProof$$bits$$mask,mask(o));
#undef START
        d.set_io$$parallel(o.parallel); d.set_io$$qualified(o.qualified);
        d.set_io$$relax$$valid(bool(relax)); d.set_io$$relax$$bits$$index(relax?relax->index:15);
        d.set_io$$relax$$bits$$tag(relax?relax->tag:UINT64_MAX);
        d.set_io$$cancel(cancel); d.set_io$$holdEnqueue(holdEnqueue); d.set_io$$holdQueue(holdQueue);
        d.set_io$$holdResponse(holdResponse); d.set_io$$directResponse(direct);
        d.set_io$$complete$$ready(completeReady); d.set_io$$memory$$request$$ready(memoryReady);
        const auto &r = offeredReply;
        d.set_io$$memory$$response$$valid(bool(r));
        d.set_io$$memory$$response$$bits$$returnHandle(r ? r->handle : cycle % 8);
        d.set_io$$memory$$response$$bits$$data(r ? r->data : UINT64_MAX);
        d.set_io$$memory$$response$$bits$$error(r && r->error);
        d.set_io$$memory$$response$$bits$$pageFault(r && r->page);
    }
    Request sampleRequest(bool external) const {
#define READ(P,F) d.get_io$$##P##$$bits$$##F()
#define PAYLOAD(P) Request{READ(P,address),READ(P,data),unsigned(READ(P,size)),unsigned(READ(P,mask)), \
        unsigned(READ(P,atomicOp)),unsigned(READ(P,returnHandle)),unsigned(READ(P,translationEpoch)), \
        bool(READ(P,write)),bool(READ(P,atomic)),bool(READ(P,virtualized)),bool(READ(P,precheckedLoad)), \
        bool(READ(P,uncached)),bool(READ(P,prefetchNextAllowed))}
        if (external) return PAYLOAD(memory$$request);
        return PAYLOAD(request);
#undef PAYLOAD
#undef READ
    }
    void verifyCompletion(const Ptr &x) {
        const Op &o = *x;
        check(!o.drained && !o.completed && (o.local() || o.responded), "premature or duplicate completion");
        const bool write = o.store || (o.atomic && o.atomicOp != 2);
        const bool exception = o.local() ? o.misaligned() || o.denied : o.error || o.page;
        const uint64_t cause = o.misaligned() ? (write ? 6 : 4) : (!o.local() && o.page) ? (write ? 15 : 13) : (write ? 7 : 5);
        const uint64_t data = o.local() ? (o.forward ? value(o.beat,o) : 0) : o.atomic ? o.beat : o.store ? 0 : value(o.beat,o);
        Token observed{unsigned(d.get_io$$complete$$bits$$token$$index()),uint64_t(d.get_io$$complete$$bits$$token$$tag())};
        if (mutation == "oracle-token") { anchor("oracle_full_token"); observed.tag ^= 1ULL << 63; }
        check(observed == o.token, "ORACLE_FULL_TOKEN: original 64-bit completion token mismatch");
        uint64_t expectedData = data;
        if (mutation == "oracle-data") { anchor("oracle_completion_data"); expectedData ^= 1; }
        check(d.get_io$$complete$$bits$$data() == expectedData, "ORACLE_COMPLETION_DATA: independently extracted data mismatch");
        check(bool(d.get_io$$complete$$bits$$exception()) == exception && d.get_io$$complete$$bits$$cause() == cause &&
            d.get_io$$complete$$bits$$tval() == o.address && d.get_io$$complete$$bits$$nextPc() == o.pc + 4,
            "exact completion exception/cause/original tval/nextPc mismatch");
    }
    bool tick(const Ptr &offer = {}) {
        if (automaticReplies && !offeredReply) {
            auto it = std::find_if(owners.begin(),owners.end(),[](const Ptr &x){ return x->issued && !x->returned; });
            if (it != owners.end()) offeredReply = Reply{*it,(*it)->slot,(*it)->beat,(*it)->error,(*it)->page};
        }
        drive(offer); d.step(); lastInputFire = false;
        if (std::getenv("TAGGED_LOAD_PUBLISH_TRACE")) std::cerr << "cycle=" << cycle << " live=" << unsigned(d.get_io$$live())
            << " phase=" << unsigned(d.get_io$$phase()) << " starts=" << starts << " enqueues=" << enqueues
            << " issues=" << issues << " responses=" << responses << " complete=" << completions << '\n';
        unsigned mirrorObserved = d.get_io$$mirrorReady1();
        if (mutation == "oracle-mirror" && mirrorExpected) {
            anchor("mirror_incoming_publication"); mirrorObserved ^= 1;
        }
        check(mirrorObserved == mirrorExpected && d.get_io$$mirrorReady2() == mirrorExpected,
            "ORACLE_INCOMING_READY: publication allocation/class/reserve priority mismatch");
        verifyHeld();
        std::array<Ptr,4> expectedPublication{};
        const unsigned actualSlotStarts = d.get_io$$slotStart();
        const unsigned actualSlotResponses = d.get_io$$slotResponse();
        const unsigned stalledSlotRequests = unsigned(d.get_io$$slotRequestValid()) & ~unsigned(d.get_io$$slotRequestReady());
        unsigned expectedSlotResponses = 0;
        unsigned live = 0, pending = 0;
        bool discarded = false;
        for (unsigned i = 0; i < 4; ++i) {
            const auto &s = slots[i]; live += bool(s.owner); pending += s.owner && s.owner->queued && !s.owner->responded;
            check(bool(d.get_io$$live() & (1U << i)) == bool(s.owner), "independent slot lifetime mismatch");
            check(((unsigned(d.get_io$$phase()) >> (2*i)) & 3) == s.phase, "independent slot phase mismatch");
            if (s.owner) {
                check(observedOwner(i) == s.owner->token, "saved slot full-token mismatch");
                discarded |= s.phase == 3 && (s.owner->cancelled || (cancel & (1U << i)));
            }
        }
        check(bool(d.get_io$$discarded()) == discarded, "cancelled completion drain witness mismatch");
        maxLive = std::max(maxLive,live); maxPending = std::max(maxPending,pending);
        Ptr completed;
        bool expectedCompletedDestination = false;
        if (d.get_io$$complete$$valid()) {
            const Token t{unsigned(d.get_io$$complete$$bits$$token$$index()),uint64_t(d.get_io$$complete$$bits$$token$$tag())};
            auto x = find(t); check(slots[x->slot].phase == 3 && !x->cancelled, "cancelled/non-done completion offered");
            verifyCompletion(x); completeStalls += !completeReady;
            expectedCompletedDestination = x->destinationEligible() && !x->exception();
            if (expectedCompletedDestination) check(d.get_io$$completedDestination$$bits() == x->destination,
                "COMPLETION_DESTINATION: completed sideband lost accepted-owner destination");
            if (completeReady) {
                check(!(cancel & (1U << x->slot)), "caller accepted same-edge cancelled completion");
                x->completed = x->drained = true; completed = x; ++completions;
            }
        }
        check(bool(d.get_io$$completedDestination$$valid()) == expectedCompletedDestination,
            "COMPLETION_DESTINATION_VALID: independent completed-owner sideband mismatch");
        // Cancel affects retirement authority, but never deletes a request/reply obligation.
        for (unsigned i = 0; i < 4; ++i) if (slots[i].owner) {
            auto x = slots[i].owner;
            if (cancel & (1U << i)) { check(!x->store && !x->atomic, "driver cancelled irrevocable operation"); x->cancelled = true; }
            if (slots[i].phase == 3 && x->cancelled) { x->drained = true; ++discards; slots[i] = {}; }
            else if (x == completed) slots[i] = {};
        }
        const bool take = offer && d.get_io$$start$$ready();
        if (offer && (flushCauses || exceptionBlock)) {
            check(!take && !actualSlotStarts, "FINAL_PERMISSION: blocked owner captured"); ++flushBlocked;
            candidateOnlyCapacity += d.get_io$$candidateAvailable() && !d.get_io$$available();
        }
        if (take) {
            check(!offer->accepted, "driver reused accepted operation");
            for (const auto &x : owners) check(x->token != offer->token, "driver reused full ROB generation");
            const unsigned slot = d.get_io$$chosen(); check(slot < 4 && !slots[slot].owner, "start reused undrained physical slot");
            offer->slot = slot; offer->accepted = true; offer->startCycle = cycle;
            owners.push_back(offer); slots[slot] = {offer,offer->local() ? 3U : 1U};
            ++starts; localResults += offer->local(); replacement += completed && completed->slot == slot;
            if (offer->forward && !offer->exception() && offer->destinationEligible()) {
                expectedPublication[slot] = offer;
                forwardReplacements += completed && completed->slot == slot;
            }
            if (offer->local() && !offer->exception() && !offer->destinationEligible()) ++suppressedDestination;
            if (offer->local() && offer->exception()) ++suppressedFault;
            check(bool(d.get_io$$forwarded()) == (offer->forward && !offer->misaligned() && !offer->denied), "forwarded start witness mismatch");
            if (d.get_io$$overlapAccepted()) {
                check(offer->qualified && offer->frozen && offer->store && !offer->parallel, "bound-store acceptance lacks real frozen store");
                unsigned coowners = 0;
                for (const auto &s : slots) if (s.owner && s.owner != offer) {
                    const auto &x = *s.owner; ++coowners;
                    check(x.prechecked && x.virt && !x.store && !x.atomic && !x.cancelled && x.token.index != offer->token.index &&
                        x.epoch == offer->epoch && ((x.physical >> 3) != (offer->physical >> 3) || !(mask(x) & mask(*offer))),
                        "bound-store accepted without independent live disjoint co-owner");
                }
                check(coowners, "bound-store witness had no live co-owner"); ++overlap;
            }
        } else check(!d.get_io$$forwarded() && !d.get_io$$overlapAccepted(), "unaccepted start produced semantic witness");
        check(actualSlotStarts == (take ? 1U << offer->slot : 0U),
            "START_SLOT: accepted operation differs from observed real slot start");
        // Registered external request queue cannot bypass an ingress on this edge.
        bool externalIssued = false;
        if (d.get_io$$memory$$request$$valid()) {
            check(!queue.empty(), "external request without prior accepted queue owner");
            const auto now = sampleRequest(true); const auto x = queue.front();
            check(now == request(*x), "external request fields lost original accepted owner");
            if (heldExternal) check(now == *heldExternal, "held external request changed");
            heldExternal = memoryReady ? std::nullopt : std::optional{now}; externalHolds += !memoryReady;
            if (memoryReady) {
                check(x->queued && !x->issued && cycle > x->queueCycle, "duplicate/nonregistered external issue");
                x->issued = true; x->issueCycle = cycle; queue.pop_front(); ++issues; externalIssued = true;
            }
        } else check(!heldExternal || holdQueue, "held external request withdrew valid");
        bool enqueued = false;
        if (d.get_io$$request$$valid()) {
            check(d.get_io$$requestOwner$$valid(), "LSU request missing full-token owner");
            const Token t{unsigned(d.get_io$$requestOwner$$bits$$index()),uint64_t(d.get_io$$requestOwner$$bits$$tag())};
            const auto x = find(t); const auto now = sampleRequest(false);
            check(!x->local() && !x->queued && !x->drained && now == request(*x), "LSU ingress fields/handle/original owner mismatch");
            if (heldRequest) check(now == *heldRequest && t == *heldRequestOwner, "held LSU request or full-token owner changed");
            const bool ready = d.get_io$$requestReady(); requestHolds += !ready;
            heldRequest = ready ? std::nullopt : std::optional{now}; heldRequestOwner = ready ? std::nullopt : std::optional{t};
            check(bool(d.get_io$$origin$$valid()) == x->frozen && bool(d.get_io$$frozen$$valid()) == x->frozen, "frozen/origin validity mismatch");
            if (x->frozen) check(d.get_io$$origin$$bits$$token$$index() == x->token.index &&
                d.get_io$$origin$$bits$$token$$tag() == x->token.tag && d.get_io$$origin$$bits$$epoch() == x->epoch &&
                d.get_io$$frozen$$bits$$address() == x->address && d.get_io$$frozen$$bits$$physicalAddress() == x->physical &&
                d.get_io$$frozen$$bits$$size() == x->size && d.get_io$$frozen$$bits$$mask() == mask(*x),
                "frozen store lost complete binding/token/epoch");
            if (ready) { x->queued = true; x->queueCycle = cycle; queue.push_back(x); slots[x->slot].phase = 2; ++enqueues; enqueued = true; }
        } else check(!heldRequest, "held LSU request withdrew valid");
        const auto input = offeredReply;
        if (input) {
            if (heldInput) check(*input == *heldInput, "HELD_RESPONSE_PAYLOAD: external producer changed held tuple");
            const bool ready = d.get_io$$memory$$response$$ready();
            heldInput = ready ? std::nullopt : input; responseHolds += !ready; directHolds += direct && !ready;
            if (ready) {
                auto x = input->owner;
                check(x && input->handle == x->slot && x->issued && !x->returned,
                    "RETURN_OWNER: unsolicited/domain/duplicate response lacks original issued owner");
                check(input->data == x->beat && input->error == x->error && input->page == x->page,
                    "RETURN_DATA: supplied response differs from independent original reply");
                x->returned = true; x->returnCycle = cycle; ++returns; lastInputFire = true;
                if (!direct) buffered.push_back(*input); offeredReply.reset();
            }
        } else check(!heldInput, "held external response withdrew valid");
        bool responseFired = false;
        lastResponseReady = d.get_io$$responseReady();
        if (d.get_io$$response$$valid()) {
            const Reply now{{},unsigned(d.get_io$$response$$bits$$returnHandle()),d.get_io$$response$$bits$$data(),
                bool(d.get_io$$response$$bits$$error()),bool(d.get_io$$response$$bits$$pageFault())};
            check(now.handle < 4 && slots[now.handle].owner, "LSU_RESPONSE_OWNER: response names absent/ineligible slot");
            auto x = slots[now.handle].owner;
            check(x->queued && !x->responded && !x->local() && slots[now.handle].phase == 2,
                "LSU_RESPONSE_PENDING: response lacks exact pending reservation");
            check(now == Reply{x,x->slot,x->beat,x->error,x->page}, "LSU_RESPONSE_DATA: response buffer changed original tuple");
            if (!direct) {
                check(!buffered.empty() && now == buffered.front() && buffered.front().owner == x,
                    "registered response buffer lost independent arrival order");
                check(x->returned && cycle > x->returnCycle, "registered response bypassed its capture edge");
            }
            if (d.get_io$$responseReady()) {
                check(x->returned && x->issued, "actual LSU reply preceded external request/response acceptance");
                x->responded = true; x->responseCycle = cycle; expectedSlotResponses |= 1U << x->slot;
                if (!x->exception() && !x->cancelled && x->destinationEligible() && !fastRetire) {
                    check(!expectedPublication[x->slot], "response and start claimed same physical publication slot");
                    expectedPublication[x->slot] = x;
                    responseOtherStart += take && offer->slot != x->slot;
                    responseOtherRequestStall += bool(stalledSlotRequests & ~(1U << x->slot));
                }
                suppressedFault += x->exception(); suppressedCancel += x->cancelled;
                suppressedDestination += !x->exception() && !x->cancelled && !x->destinationEligible();
                if (fastRetire) {
                    check(!x->exception() && !x->cancelled && !x->store && !x->atomic,
                        "driver fast-retired without a legal successful ordinary response");
                    x->fastRetired = x->drained = true; ++fastRetires; slots[x->slot] = {};
                } else slots[x->slot].phase = 3;
                if (!direct) buffered.pop_front(); else ++directFires;
                ++responses; concurrentEnqueueReply += enqueued; responseFired = true;
            }
        }
        check(!fastRetire || responseFired, "driver asserted fast retirement without actual response acceptance");
        check(actualSlotResponses == expectedSlotResponses,
            "RESPONSE_SLOT: accepted tagged response differs from observed real slot fire");
        verifyPublication(expectedPublication);
        if (d.get_io$$publish()) mirrorExpected = mirrorReserve ? 0 : 1;
        if (direct && input) std::cout << "TAGGED_LOAD_PUBLISH_DIRECT_EDGE cycle=" << cycle << " start_fire=" << take
            << " ingress_fire=" << enqueued << " external_request_fire=" << externalIssued
            << " external_response_fire=" << lastInputFire << " lsu_response_ready=" << lastResponseReady
            << " lsu_response_fire=" << responseFired << " queue_after=" << queue.size()
            << " buffer_after=" << buffered.size() << '\n';
        ++cycle; return take;
    }
    template <class Predicate> void until(Predicate pred, const char *why) {
        for (unsigned i = 0; i < 1000 && !pred(); ++i) tick(); check(pred(),why);
    }
    void accept(const Ptr &x) { for (unsigned i=0;i<1000;++i) if (tick(x)) return; throw std::runtime_error("start timed out"); }
    void issue(const Ptr &x) { until([&]{return x->issued;},"external issue timed out"); }
    void reply(const Ptr &x) {
        check(!offeredReply && x->issued && !x->returned,"driver offered unissued or duplicate reply");
        offeredReply = Reply{x,x->slot,x->beat,x->error,x->page};
        until([&]{return x->returned;},"response input timed out");
    }
    void settle(const Ptr &x) { until([&]{return x->responded;},"buffered LSU response timed out"); }
    void drain() {
        holdEnqueue = holdQueue = holdResponse = false; memoryReady = completeReady = true; cancel = 0; automaticReplies = true;
        until([&]{return std::all_of(owners.begin(),owners.end(),[](const Ptr &x){return x->drained;});},"completion/cancel drain timed out");
        automaticReplies = false; for (unsigned i=0;i<4;++i) tick();
        check(d.get_io$$idle() && queue.empty() && buffered.empty() && !offeredReply && !heldRequest && !heldExternal && !heldInput,
            "fixture did not return to fully drained idle");
        for (const auto &x : owners) {
            check(x->drained && unsigned(x->completed) + unsigned(x->cancelled) + unsigned(x->fastRetired) == 1,
                "owner not completed/cancelled/fast-retired exactly once");
            // A later cancel may kill an already-published done result; earlier cancellation suppresses publication.
            check(x->publications <= 1, "owner duplicated its publication");
            if (!x->cancelled) check(x->publications == unsigned(x->destinationEligible() && !x->exception() && !x->fastRetired),
                "drained owner lost successful publication or published a suppressed class");
            check(x->local() ? !x->queued && !x->issued && !x->returned && !x->responded :
                x->queued && x->issued && x->returned && x->responded,"accepted owner lost transport conservation");
        }
        check(enqueues == issues && issues == returns && returns == responses && starts == completions + discards + fastRetires,
            "global request/response/completion/cancel conservation mismatch");
    }
    void note(const char *name) { std::cout << "TAGGED_LOAD_PUBLISH_CASE " << name << " cycle=" << cycle << '\n'; }
    void positive();
    void flushPositive();
    void negative(const std::string &mode);
};

void Bench::flushPositive() {
    // Legal service continues to drain old owners while F blocks only new starts.
    auto pending = op(); accept(pending); issue(pending); completeReady=false;
    holdResponse=true; reply(pending);
    auto blocked = op();
    for (unsigned f=1; f<16; ++f) {
        flushCauses=f; check(!tick(blocked),"FLUSH_BLOCKED_OFFER_ACCEPTED");
    }
    check(candidateOnlyCapacity==15,"CANDIDATE_STRICT_CAPACITY_DIFFERENCE_NOT_REACHED");
    holdResponse=false; check(!tick(blocked)&&pending->responded&&pending->publications==1,
        "FLUSH_BLOCKED_OLD_SUCCESSFUL_RESPONSE");
    completeReady=true; check(!tick(blocked)&&pending->completed,"FLUSH_BLOCKED_OLD_COMPLETION");
    flushCauses=0; exceptionBlock=true; check(!tick(blocked),"EXCEPTION_BLOCKED_OFFER_ACCEPTED");
    exceptionBlock=false; check(tick(blocked),"FIRST_LEGAL_START_DELAYED");
    drain(); note("all_flush_causes_keep_strict_capacity_and_release_without_bubble");
    for (unsigned reserve=0; reserve<2; ++reserve) {
        auto f=op(); f->virt=false; f->prechecked=false; f->forward=true; f->address=RAM+0x80;
        flushCauses=4; mirrorReserve=bool(reserve); check(!tick(f),"FLUSH_FORWARDED_CAPTURE");
        flushCauses=0; check(tick(f)&&f->publications==1,"FIRST_LEGAL_FORWARDED_PUBLICATION_MISSING");
        tick(); check(mirrorExpected==(reserve?0U:1U),"SAME_EDGE_RESERVE_PRIORITY_NOT_REACHED");
        mirrorReserve=false; drain();
    }
    note("forwarded_publication_incoming_both_sources_reserve_class_priority");

    for(unsigned kind=0;kind<3;++kind) {
        auto x=op(); x->error=kind==0; x->page=kind==1;
        accept(x); issue(x); completeReady=false; holdResponse=true; reply(x);
        auto waiting=op(); flushCauses=8; holdResponse=false;
        if(kind==2) cancel=1u<<x->slot;
        check(!tick(waiting)&&x->responded&&!x->publications,"FLUSH_FAULT_CANCEL_RESPONSE_MISMATCH");
        cancel=0; completeReady=true; check(!tick(waiting)&&x->drained,"FLUSH_FAULT_CANCEL_DRAIN_BLOCKED");
        flushCauses=0; drain();
    }
    note("old_error_pagefault_cancel_response_and_completion_continue_under_flush");
    auto serial=op();serial->store=true;serial->prechecked=false;serial->parallel=false;serial->frozen=true;
    accept(serial);issue(serial);completeReady=false;
    relax=serial->token;auto handoff=op();flushCauses=2;
    unsigned differences=candidateOnlyCapacity;
    check(!tick(handoff)&&candidateOnlyCapacity==differences+1,"CANONICAL_CANDIDATE_HANDOFF_NOT_REACHED");
    flushCauses=0;relax->tag^=1ULL<<63;
    check(!tick(handoff),"STALE_CANONICAL_OWNER_GRANTED_HANDOFF");
    relax=serial->token;check(tick(handoff)&&handoff->slot!=serial->slot,"FIRST_LEGAL_CANONICAL_HANDOFF_DELAYED");
    relax.reset();drain();note("canonical_handoff_exact_owner_and_stale_generation_under_flush");
    std::cout << "FLUSH_ADMISSION_PRIORITY_PASS blocked=" << flushBlocked
        << " candidate_strict_difference=" << candidateOnlyCapacity << '\n';
}

void Bench::positive() {
    // Four real pending reservations; queue backpressure and response arrival are
    // controlled independently of completion readiness.
    holdQueue = true; completeReady = false;
    std::array<Ptr,4> four;
    for (unsigned i=0;i<4;++i) { four[i]=op(i); four[i]->unsign=i&1; four[i]->error=i==1; four[i]->page=i==2; accept(four[i]); }
    for (unsigned i=0;i<4;++i) tick();
    check(enqueues == 4 && !issues,"all-four queued ownership witness missing");
    auto blocked=op(); for (unsigned i=0;i<4;++i) check(!tick(blocked),"fifth outstanding start escaped capacity");
    holdQueue=false; for (auto &x:four) issue(x);
    holdResponse=true; reply(four[3]); reply(four[2]);
    offeredReply=Reply{four[1],four[1]->slot,four[1]->beat,four[1]->error,four[1]->page};
    for (unsigned i=0;i<5;++i) { tick(); check(!four[1]->returned,"full response buffer failed to hold input"); }
    holdResponse=false; until([&]{return four[1]->returned;},"held response failed release"); reply(four[0]);
    for (unsigned i=0;i<8;++i) tick(); check(!completions,"completion stall consumed result");
    drain(); note("four_pending_ooo_registered_buffer_completion_stall");

    holdEnqueue=true; holdQueue=true; const unsigned oldHolds=requestHolds;
    for (unsigned i=0;i<4;++i) accept(op(i));
    for (unsigned i=0;i<6;++i) tick(); check(requestHolds>oldHolds,"locked request hold absent");
    holdEnqueue=false; for (unsigned i=0;i<6;++i) tick();
    holdQueue=false; memoryReady=false; for (unsigned i=0;i<6;++i) tick();
    drain(); note("held_arbiter_requests_all_slots_and_external_ready_stall");

    auto before=op(); holdQueue=true; accept(before);
    check(before->queued && !before->issued,"cancel-before-issue anchor missing queue owner");
    cancel=1U<<before->slot; tick(); cancel=0; drain(); check(before->cancelled,"queued cancel missing");
    auto waiting=op(); accept(waiting); issue(waiting); cancel=1U<<waiting->slot; tick(); cancel=0; drain();
    auto edge=op(); edge->page=true; accept(edge); issue(edge); completeReady=false; holdResponse=true; reply(edge);
    cancel=1U<<edge->slot; holdResponse=false; tick(); check(edge->responded,"cancel/response same-edge witness absent"); cancel=0; drain();
    auto done=op(); done->error=true; accept(done); issue(done); completeReady=false; reply(done); settle(done);
    tick(); cancel=1U<<done->slot; tick(); cancel=0; drain(); note("cancel_queued_waiting_response_edge_blocked_done");

    auto old=op(0); accept(old); issue(old); completeReady=false; reply(old); settle(old);
    auto fresh=op(0); fresh->token.index=old->token.index; fresh->token.tag=old->token.tag^(1ULL<<63);
    completeReady=true; check(tick(fresh),"same-edge completed-slot replacement rejected");
    check(old->completed && fresh->slot==old->slot,"same-index high-generation slot reuse absent"); drain();
    auto a=op(); accept(a); issue(a); completeReady=false; holdResponse=true; reply(a);
    auto b=op(); const unsigned simultaneous=concurrentEnqueueReply; holdResponse=false; accept(b);
    check(concurrentEnqueueReply>simultaneous,"different-slot enqueue plus response witness absent"); drain();
    note("same_slot_high_tag_reuse_and_other_slot_enqueue_reply");

    // Slot A's legal buffered response must publish even while slot B starts and
    // immediately loses request arbitration to external enqueue backpressure.
    auto responding=op(2); accept(responding); issue(responding);
    completeReady=false; holdResponse=true; reply(responding);
    auto contending=op(1); holdEnqueue=true; holdResponse=false;
    const unsigned oldOtherStart=responseOtherStart, oldOtherStall=responseOtherRequestStall;
    check(tick(contending), "other-slot start under enqueue backpressure was not accepted");
    check(responding->responded && responding->publications==1 && contending->slot!=responding->slot &&
        !contending->queued && responseOtherStart==oldOtherStart+1 && responseOtherRequestStall==oldOtherStall+1,
        "RESPONSE_OTHER_SLOT_STALL: old response publication lacked real different-slot start/request stall");
    for (unsigned i=0;i<3;++i) tick(); drain();
    note("old_response_publication_with_other_slot_start_and_request_backpressure");

    auto replaced=op(1); accept(replaced); issue(replaced); completeReady=false;
    reply(replaced); settle(replaced);
    auto forwarded=op(0); forwarded->prechecked=false; forwarded->forward=true;
    forwarded->token.index=replaced->token.index; forwarded->token.tag=replaced->token.tag^(1ULL<<63);
    forwarded->destination=replaced->destination==47?1:replaced->destination+1;
    completeReady=true; const unsigned oldForwardReplacements=forwardReplacements;
    check(tick(forwarded), "successful forwarded replacement was not accepted");
    check(replaced->completed && replaced->publications==1 && forwarded->slot==replaced->slot &&
        forwarded->publications==1 && forwardReplacements==oldForwardReplacements+1,
        "FORWARDED_REPLACEMENT: old held completion and new forwarded publication did not retain their own destinations");
    drain(); note("successful_forward_replacement_same_index_different_generation_and_destination");

    for (unsigned size=0;size<4;++size) for (unsigned unsign=0;unsign<2;++unsign) {
        auto x=op(size); x->prechecked=false; x->forward=true; x->unsign=unsign; x->beat=0xfedcba9876543280ULL; accept(x); drain();
    }
    for (unsigned size=1;size<4;++size) {
        auto x=op(size); x->prechecked=false; x->virt=false; x->address=RAM+0x101; x->denied=size==2;
        x->store=size==3; x->parallel=!x->store; accept(x); drain();
    }
    for (unsigned store=0;store<2;++store) {
        auto x=op(); x->prechecked=false; x->virt=false; x->address=x->physical; x->denied=true; x->store=store; x->parallel=!store; accept(x); drain();
    }
    note("local_forward_all_sizes_signed_unsigned_misaligned_access_denied");

    for (unsigned local=0;local<2;++local) for (unsigned noDestination=0;noDestination<2;++noDestination) {
        auto x=op(); x->forward=local; x->prechecked=!local;
        if (noDestination) x->destinationValid=false; else x->destination=0;
        accept(x); drain(); check(!x->publications,"zero/invalid destination published a result");
    }
    // A successful result may be killed after its one publication; kill must not
    // repeat publication or let the held result escape as an accepted completion.
    auto killedDone=op(); accept(killedDone); issue(killedDone); completeReady=false;
    reply(killedDone); settle(killedDone); tick();
    check(killedDone->publications==1,"successful done kill had no earlier real publication");
    cancel=1U<<killedDone->slot; tick(); cancel=0; drain();
    note("zero_invalid_destination_suppression_and_successful_done_kill");

    // Ordinary store and atomic return classes independently exercise all request
    // fields, store data lanes, page-fault priority and complete XLEN atomic data.
    for (unsigned kind=0;kind<4;++kind) {
        auto x=op(kind==0?1:3); x->prechecked=false; x->virt=false; x->address=x->physical; x->parallel=false;
        x->store=kind<2; x->atomic=kind>=2; x->atomicOp=kind==2?2:kind==3?3:0;
        x->page=kind==1||kind==3; x->error=kind==1||kind==2; accept(x); drain();
    }
    note("store_atomic_and_exact_fault_classes");

    auto load=op(); load->token.index=4; load->address=VA+0x40; load->physical=RAM+0x40;
    accept(load); issue(load); completeReady=false; holdResponse=true; reply(load);
    auto store=op(); store->token.index=0; store->address=VA+0x100; store->physical=RAM+0x100;
    store->prechecked=false; store->store=true; store->parallel=false; store->frozen=true; store->qualified=true;
    holdResponse=false; const unsigned previousOverlap=overlap; accept(store);
    check(overlap==previousOverlap+1 && load->responded,"real disjoint frozen bound store plus reply absent"); drain();
    note("real_frozen_bound_store_disjoint_live_load_response");

    direct=true; completeReady=false; auto immediate=op(); immediate->slot=0;
    offeredReply=Reply{immediate,0,immediate->beat,false,false};
    check(tick(immediate) && immediate->queued && !immediate->returned,"earliest offered reply did not hold at enqueue");
    check(!lastResponseReady,"earliest enqueue edge exposed unregistered response readiness");
    tick(); check(immediate->issued && immediate->returned && immediate->responded,"earliest held reply failed following-edge acceptance");
    drain(); direct=false; note("earliest_offer_at_enqueue_held_until_registered_reservation");
    // Public LSU interface contract only: OooParams.fastHeadLoadRetire stays
    // false and the constructor guard rejects enabling it in this profile.
    auto fast=op(); accept(fast); issue(fast); completeReady=false; holdResponse=true; reply(fast);
    fastRetire=true; holdResponse=false; tick(); fastRetire=false;
    check(fast->responded && fast->fastRetired && fast->drained && !fast->publications,
        "FAST_RETIRE_SUPPRESSION: successful consumed response published or retained a result");
    drain(); note("public_lsu_fast_retire_contract_not_board_reachability");
    check(maxLive==4 && maxPending==4 && requestHolds && externalHolds && responseHolds && completeStalls && overlap &&
        concurrentEnqueueReply && replacement && localResults && directHolds && directFires &&
        publications && heldCycles && responseOtherStart && responseOtherRequestStall && forwardReplacements &&
        suppressedFault && suppressedCancel && suppressedDestination && fastRetires==1,
        "required coverage witness missing");
    std::cout << "FLUSH_LOAD_PUBLISH_MATRIX_PASS flush_blocked=" << flushBlocked
        << " candidate_strict_difference=" << candidateOnlyCapacity << " cycles=" << cycle << " starts=" << starts << " enqueues=" << enqueues
        << " issues=" << issues << " returns=" << returns << " responses=" << responses << " completions=" << completions
        << " discards=" << discards << " max_live=" << maxLive << " max_pending=" << maxPending
        << " request_holds=" << requestHolds << " external_holds=" << externalHolds << " response_holds=" << responseHolds
        << " completion_stalls=" << completeStalls << " bound_store=" << overlap << " simultaneous_enqueue_reply=" << concurrentEnqueueReply
        << " replacements=" << replacement << " local_results=" << localResults << " direct_holds=" << directHolds
        << " publications=" << publications << " held_cycles=" << heldCycles
        << " response_other_start=" << responseOtherStart << " response_other_request_stall=" << responseOtherRequestStall
        << " forward_replacements=" << forwardReplacements << " suppressed_fault=" << suppressedFault
        << " suppressed_cancel=" << suppressedCancel << " suppressed_destination=" << suppressedDestination
        << " interface_fast_retires=" << fastRetires << '\n';
}

void Bench::negative(const std::string &mode) {
    if (mode=="inconsistent-admission") {
        auto x=op(); flushCauses=1; inconsistentAdmission=true;
        anchor("inconsistent_candidate_permission"); tick(x);
    } else if (mode=="oracle-mirror") {
        auto x=op(); x->virt=false; x->prechecked=false; x->forward=true; x->address=RAM+0x80;
        accept(x); mutation=mode; tick();
    } else if (mode=="oracle-publish-valid" || mode=="oracle-publish-destination") {
        auto x=op(); accept(x); issue(x); completeReady=false; holdResponse=true; reply(x);
        mutation=mode; holdResponse=false; tick();
    } else if (mode=="oracle-publish-duplicate") {
        auto x=op(); accept(x); issue(x); completeReady=false; reply(x); settle(x);
        check(x->publications==1,"duplicate publication control lacks earlier publication"); mutation=mode; tick();
    } else if (mode=="oracle-token" || mode=="oracle-data") {
        auto x=op(); accept(x); issue(x); completeReady=false; reply(x); settle(x); mutation=mode; tick();
    } else if (mode=="held-response-payload") {
        direct=true; completeReady=false; auto x=op(); x->slot=0;
        offeredReply=Reply{x,0,x->beat,false,false}; check(tick(x) && !x->returned,"held-control setup lacks actual hold");
        anchor("held_response_payload"); offeredReply->data^=1; tick();
    } else if (mode=="duplicate") {
        auto x=op(); accept(x); drain(); direct=true; anchor("duplicate_drained_handle");
        offeredReply=Reply{x,x->slot,x->beat,false,false}; tick();
    } else {
        check(mode=="invalid-handle" || mode=="wrong-domain" || mode=="unsolicited","unknown negative control");
        direct=true; anchor(mode=="invalid-handle"?"invalid_handle_7":mode=="wrong-domain"?"store_domain_handle_4":"unsolicited_integer_handle_0");
        offeredReply=Reply{{},mode=="invalid-handle"?7U:mode=="wrong-domain"?4U:0U,0xabcdef0123456789ULL,false,false}; tick();
    }
    throw std::runtime_error("NEGATIVE_CONTROL_ESCAPED: designated assertion/oracle did not reject");
}
} // namespace

int main(int argc,char **argv) {
    try {
        if(argc==1) { { Bench b; b.flushPositive(); } { Bench b; b.positive(); } }
        else { Bench b; check(argc==2,"usage: tagged_load_publish [--invalid-handle|--wrong-domain|--unsolicited|--duplicate|--held-response-payload|--oracle-token|--oracle-data|--oracle-publish-valid|--oracle-publish-destination|--oracle-publish-duplicate]");
            std::string mode=argv[1]; if(mode.starts_with("--"))mode.erase(0,2); b.negative(mode); }
        return 0;
    } catch(const std::exception &e) {
        std::cerr << "TAGGED_LOAD_PUBLISH_REJECT " << e.what() << '\n'; return 1;
    }
}
