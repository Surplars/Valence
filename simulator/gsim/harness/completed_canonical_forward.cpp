#include "CompletedCanonicalForwardGsim.h"
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
#include <utility>
#include <vector>

// Independent boundary oracle: only accepted starts and actual request/reply
// handshakes create ownership. Certificates are inputs to be checked, never the
// source of expected result data. There is no backend or translation model here.
namespace {
constexpr uint64_t VA = 0x40000000ULL, ALIAS = 0x50000000ULL, RAM = 0x80200000ULL;
constexpr uint64_t RAM_BYTES = 0x80000000ULL;
void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Certificate {
    Token token;
    uint32_t epoch = 0;
    uint64_t va = 0, pa = 0;
    unsigned size = 0, mask = 0;
    bool valid = false;
};
struct Operation {
    Token token;
    uint64_t address = 0, physical = 0, data = 0, pc = 0, expected = 0;
    uint32_t epoch = 19;
    unsigned size = 3;
    bool store = false, virt = true, prechecked = true, unsign = false, forward = false;
    bool origin = false, parallel = true, error = false, page = false;
    Certificate certificate;
    uint64_t forwardXor = 0;
    bool accepted = false, requested = false, responded = false, completed = false, cancelled = false, drained = false;
    uint64_t startCycle = 0, requestCycle = 0, responseCycle = 0, completeCycle = 0;
};
using Ptr = std::shared_ptr<Operation>;
unsigned bytes(unsigned size) { check(size < 4, "ORACLE_SIZE: invalid operation width"); return 1U << size; }
unsigned lanes(uint64_t address, unsigned size) {
    unsigned result = 0;
    for (unsigned i = 0; i < bytes(size); ++i) result |= 1U << ((address + i) % 8);
    return result;
}
uint64_t storeBeat(const Operation &s) {
    uint64_t result = 0;
    // Includes the original unmasked data, matching the StoreForward payload's
    // full aligned beat. Only the separately checked covered lanes may be used.
    for (unsigned i = 0; i + s.address % 8 < 8; ++i)
        result |= ((s.data >> (8 * i)) & 255ULL) << (8 * (i + s.address % 8));
    return result;
}
uint64_t extend(uint64_t value, unsigned size, bool unsign) {
    const unsigned bits = 8 * bytes(size);
    if (bits < 64 && !unsign && (value & (1ULL << (bits - 1)))) value |= ~0ULL << bits;
    return value;
}
uint64_t loadFromStore(const Operation &s, const Operation &l) {
    check(l.physical >= s.physical && l.physical - s.physical + bytes(l.size) <= bytes(s.size),
        "ORACLE_RANGE: source does not own every requested byte");
    uint64_t value = 0;
    for (unsigned i = 0; i < bytes(l.size); ++i) {
        const unsigned sourceByte = unsigned(l.physical - s.physical) + i;
        value |= ((s.data >> (sourceByte * 8)) & 255ULL) << (i * 8);
    }
    return extend(value, l.size, l.unsign);
}
uint64_t memoryBeat(uint64_t address) {
    uint64_t result = 0;
    for (unsigned i = 0; i < 8; ++i) {
        const uint64_t byteAddress = (address & ~7ULL) + i;
        result |= uint64_t(uint8_t((byteAddress * 29) ^ (byteAddress >> 11) ^ 0x93)) << (8 * i);
    }
    return result;
}
uint64_t memoryValue(const Operation &o) {
    uint64_t value = 0;
    const uint64_t beat = memoryBeat(o.physical);
    for (unsigned i = 0; i < bytes(o.size); ++i)
        value |= ((beat >> (8 * ((o.address + i) % 8))) & 255ULL) << (8 * i);
    return extend(value, o.size, o.unsign);
}
Certificate certificate(const Operation &s) {
    return {s.token, s.epoch, s.address, s.physical, s.size, lanes(s.address, s.size), true};
}
bool certificateMatches(const Operation &s, const Operation &l) {
    const auto &c = l.certificate;
    if (!c.valid || c.size > 3 || c.token != s.token || c.epoch != s.epoch || c.epoch != l.epoch ||
        c.va != s.address || c.size != s.size || c.mask != lanes(s.address,s.size)) return false;
    const uint64_t width = 1ULL << c.size;
    if (c.va % width || c.pa % width || c.va % 4096 != c.pa % 4096 ||
        c.mask != lanes(c.pa,c.size) || c.pa < RAM || c.pa - RAM > RAM_BYTES - width) return false;
    if (l.address % bytes(l.size) || l.physical % bytes(l.size) ||
        l.address % 4096 != l.physical % 4096 || l.physical < RAM ||
        l.physical - RAM > RAM_BYTES - bytes(l.size)) return false;
    return (c.pa / 8 == l.physical / 8) && (c.mask & lanes(l.physical,l.size)) == lanes(l.physical,l.size);
}
struct Reply { Ptr owner; uint64_t due = 0; };

class Bench {
    // Normal generated activation/reset API only. Never alter DUT registers.
    alignas(SCompletedCanonicalForwardGsim) std::byte storage[sizeof(SCompletedCanonicalForwardGsim)]{};
    SCompletedCanonicalForwardGsim &d;
    Ptr active;
    unsigned phase = 0;
    std::deque<Reply> pending;
    std::vector<Ptr> history;
    unsigned nextId = 0;
public:
    uint64_t cycle = 0;
    bool memoryReady = true, completeReady = false, allowReplies = false;
    std::optional<Token> cancel;
    unsigned starts = 0, requests = 0, responses = 0, completions = 0, discards = 0;
    unsigned turnover = 0, heldBlocked = 0, preReplyBlocked = 0, nextCycleLoads = 0, slots = 0;
    bool lastReady = false, lastComplete = false, lastSource = false;
    std::string mutation;
    explicit Bench(std::string mutation = {}) : d(*::new (static_cast<void *>(storage)) SCompletedCanonicalForwardGsim),
        mutation(std::move(mutation)) {
        static_assert(std::is_trivially_copyable_v<SCompletedCanonicalForwardGsim>);
        d.LOG_START = 1; d.activateAll(); drive({}); d.set_reset(1);
        d.step(); d.resetAll(); d.step(); d.resetAll(); d.activateAll(); d.set_reset(0);
        for (unsigned i = 0; i < 3; ++i) tick();
        slots = unsigned(d.get_io$$configuredSlots());
        check(slots == 2 || slots == 4, "CONFIGURATION: expected real two/four-owner M3 LSU");
    }
    ~Bench() { d.~SCompletedCanonicalForwardGsim(); }
    void anchor(const std::string &name) const {
        const std::string label = name == "source-tag" ? "owner" : name == "forward-data" ? "data" :
            name == "oracle-data" ? "observation" : name;
        std::cout << "A1_M3_INJECT " << label << " cycle=" << cycle << std::endl;
    }
    Ptr source(unsigned offset, unsigned size, uint64_t data, bool error = false, bool page = false) {
        auto x = std::make_shared<Operation>();
        // Reuse the ROB index and low 32 tag bits, changing high generation bits.
        x->token = {3, (uint64_t(++nextId) << 40) | 0x91ULL};
        x->address = VA + 0x100 + offset; x->physical = RAM + 0x100 + offset;
        x->pc = 0x80001000ULL + 4 * nextId; x->data = data; x->size = size;
        x->store = true; x->prechecked = false; x->parallel = false; x->origin = true;
        x->error = error; x->page = page; return x;
    }
    Ptr forwarded(const Ptr &source, unsigned offset, unsigned size, bool unsign) {
        auto x = std::make_shared<Operation>();
        x->token = {7, 0x8000000000000000ULL | (uint64_t(++nextId) << 40) | 0x92ULL};
        x->address = ALIAS + 0x100 + offset; x->physical = RAM + 0x100 + offset;
        x->pc = 0x80002000ULL + 4 * nextId; x->size = size; x->unsign = unsign;
        x->epoch = source->epoch; x->forward = true; x->certificate = certificate(*source);
        x->expected = loadFromStore(*source,*x); return x;
    }
    Ptr ordinary() {
        auto x = std::make_shared<Operation>();
        x->token = {7, 0xc000000000000000ULL | (uint64_t(++nextId) << 40) | 0x92ULL};
        x->address = ALIAS + 0x208; x->physical = RAM + 0x208;
        x->pc = 0x80003000ULL + 4 * nextId; x->expected = memoryValue(*x); return x;
    }
    void drive(const Ptr &offer) {
        Operation empty; const auto &o = offer ? *offer : empty; const auto &c = o.certificate;
        d.set_io$$startValid(bool(offer)); d.set_io$$tokenIndex(o.token.index); d.set_io$$tokenTag(o.token.tag);
        d.set_io$$pc(o.pc); d.set_io$$address(o.address); d.set_io$$physicalAddress(o.physical);
        d.set_io$$data(o.data); d.set_io$$size(o.size); d.set_io$$unsignedLoad(o.unsign);
        d.set_io$$store(o.store); d.set_io$$virtualized(o.virt); d.set_io$$prechecked(o.prechecked);
        d.set_io$$forwarded(o.forward); d.set_io$$parallel(o.parallel); d.set_io$$epoch(o.epoch);
        d.set_io$$originValid(o.origin); d.set_io$$certificateValid(c.valid);
        d.set_io$$sourceIndex(c.token.index); d.set_io$$sourceTag(c.token.tag); d.set_io$$sourceEpoch(c.epoch);
        d.set_io$$sourceVirtualAddress(c.va); d.set_io$$sourcePhysicalAddress(c.pa);
        d.set_io$$sourceSize(c.size); d.set_io$$sourceMask(c.mask); d.set_io$$forwardDataXor(o.forwardXor);
        // This exact ordinary-load relaxation must NOT permit a forwarded load
        // to escape to an empty slot while its source completion is stalled.
        d.set_io$$relaxValid(bool(offer) && o.forward);
        d.set_io$$cancelValid(bool(cancel)); d.set_io$$cancelIndex(cancel ? cancel->index : 0);
        d.set_io$$cancelTag(cancel ? cancel->tag : 0);
        d.set_io$$memory$$request$$ready(memoryReady); d.set_io$$complete$$ready(completeReady);
        const bool reply = allowReplies && !pending.empty() && pending.front().due <= cycle;
        d.set_io$$memory$$response$$valid(reply);
        d.set_io$$memory$$response$$bits$$data(reply ? memoryBeat(pending.front().owner->physical) : 0);
        d.set_io$$memory$$response$$bits$$error(reply && pending.front().owner->error);
        d.set_io$$memory$$response$$bits$$pageFault(reply && pending.front().owner->page);
    }
    void verifyCompletion(const Ptr &o) {
        check(o && phase == 3 && !o->drained && !o->completed && (o->forward || o->responded),
            "M3_COMPLETION_LIFETIME: premature/duplicate completion");
        Token observed{unsigned(d.get_io$$complete$$bits$$token$$index()),d.get_io$$complete$$bits$$token$$tag()};
        if (mutation == "oracle-token" && o->forward) { anchor(mutation); observed.tag ^= 1ULL << 63; }
        check(observed == o->token, "M3_ORACLE_TOKEN: full 64-bit generation lost or stale token completed");
        uint64_t observedData = d.get_io$$complete$$bits$$data();
        if (mutation == "oracle-data" && o->forward) { anchor(mutation); observedData ^= 1; }
        check(observedData == (o->store ? 0 : o->expected),
            "M3_ORACLE_DATA: independently extracted source bytes/sign extension differ");
        check(bool(d.get_io$$complete$$bits$$exception()) == (o->error || o->page) &&
            d.get_io$$complete$$bits$$tval() == o->address && d.get_io$$complete$$bits$$nextPc() == o->pc + 4,
            "M3_COMPLETION_METADATA: exception/original VA/next PC mismatch");
        if (o->error || o->page) check(d.get_io$$complete$$bits$$cause() ==
            (o->page ? (o->store ? 15U : 13U) : (o->store ? 7U : 5U)),
            "M3_PRECISE_FAULT: store error/page-fault cause changed");
    }
    bool tick(const Ptr &offer = {}) {
        const bool reply = allowReplies && !pending.empty() && pending.front().due <= cycle;
        drive(offer); d.step();
        if (std::getenv("A1_M3_TRACE")) std::cerr << "cycle=" << cycle << " phase=" << phase
            << " actual=" << unsigned(d.get_io$$phase()) << " starts=" << starts << " requests=" << requests
            << " replies=" << responses << " complete=" << completions << '\n';
        check(unsigned(d.get_io$$live()) == (active ? 1U : 0U) && unsigned(d.get_io$$phase()) == phase &&
            bool(d.get_io$$busy()) == bool(active), "M3_OWNER_STATE: independent single-owner lifetime differs");
        const bool sourceEligible = active && phase == 3 && active->store && active->virt && active->origin &&
            active->requested && active->responded && !active->error && !active->page;
        lastSource = d.get_io$$source$$valid();
        check(lastSource == sourceEligible, "M3_SOURCE_ELIGIBILITY: unsuccessful/unreturned store offered forwarding");
        if (lastSource) check(d.get_io$$source$$bits$$token$$index() == active->token.index &&
            d.get_io$$source$$bits$$token$$tag() == active->token.tag &&
            d.get_io$$source$$bits$$address() == active->address && d.get_io$$source$$bits$$size() == active->size &&
            d.get_io$$source$$bits$$data() == storeBeat(*active),
            "M3_SOURCE_PAYLOAD: real completed StoreForward lost original source ownership/bytes");
        const bool cancelledNow = active && cancel && *cancel == active->token;
        const bool discard = active && phase == 3 && (active->cancelled || cancelledNow);
        check(bool(d.get_io$$discarded()) == discard, "M3_CANCEL_DRAIN: exact cancelled owner was not discarded");
        const bool completeValid = d.get_io$$complete$$valid();
        check(completeValid == bool(active && phase == 3 && !active->cancelled),
            "M3_COMPLETE_VALID: missing result or cancelled owner completed");
        if (completeValid) verifyCompletion(active);
        lastComplete = completeValid && completeReady;
        check(!lastComplete || !cancelledNow, "DRIVER_ERROR: completion must be held during same-edge cancellation");
        check(unsigned(d.get_io$$slotComplete()) == (lastComplete ? 1U : 0U),
            "M3_COMPLETION_SLOT: completion arbitration changed actual owner");
        lastReady = d.get_io$$startReady();
        if (mutation == "oracle-turnover" && offer && offer->forward && sourceEligible && !completeReady) {
            anchor(mutation); lastReady = true;
        }
        const bool take = offer && lastReady;
        if (take) {
            check(!offer->accepted, "DRIVER_ERROR: accepted operation offered twice");
            check(!active || lastComplete, "M3_TURNOVER_ONLY: start escaped to empty slot without consuming source");
            if (offer->forward) {
                check(sourceEligible && lastComplete && active && active->token == offer->certificate.token,
                    "M3_SOURCE_OWNER: forwarding requires same-edge completion of exact successful source");
                check(certificateMatches(*active,*offer),
                    "M3_CERTIFICATE_ORACLE: accepted source certificate/epoch/coverage is invalid");
                check(offer->expected == loadFromStore(*active,*offer),
                    "M3_EXPECTED_SOURCE: independent source bytes changed across turnover");
                ++turnover;
            }
            for (const auto &old : history) check(old->drained || old->token != offer->token || old == active,
                "M3_TOKEN_REUSE: full token reused while original owner remains live");
        }
        check(unsigned(d.get_io$$slotStart()) == (take ? 1U : 0U),
            "M3_START_SLOT: forwarded replacement did not use consumed source slot");
        check(bool(d.get_io$$acceptedForward()) == bool(take && offer->forward),
            "M3_FORWARD_EVENT: unaccepted load generated forwarding event");
        bool requestValid = d.get_io$$memory$$request$$valid();
        if (mutation == "oracle-request" && take && offer->forward) { anchor(mutation); requestValid = true; }
        if (take && offer->forward) check(!requestValid,
            "M3_NO_EXTRA_REQUEST: forwarded load generated an additional memory request");
        const Ptr requestOwner = take ? offer : active;
        const bool expectedRequest = requestOwner && !requestOwner->forward &&
            (take || phase == 1);
        check(requestValid == expectedRequest, "M3_REQUEST_VALID: physical transaction was duplicated/lost");
        if (requestValid) {
            const auto &o = *requestOwner;
            check(!o.requested && d.get_io$$requestOwner$$valid() &&
                d.get_io$$requestOwner$$bits$$index() == o.token.index && d.get_io$$requestOwner$$bits$$tag() == o.token.tag,
                "M3_REQUEST_OWNER: actual request lost accepted full-token ownership");
            check(d.get_io$$memory$$request$$bits$$address() == (o.prechecked ? o.physical : o.address) &&
                d.get_io$$memory$$request$$bits$$data() == storeBeat(o) &&
                d.get_io$$memory$$request$$bits$$size() == o.size &&
                d.get_io$$memory$$request$$bits$$mask() == lanes(o.address,o.size) &&
                bool(d.get_io$$memory$$request$$bits$$write()) == o.store &&
                !d.get_io$$memory$$request$$bits$$atomic() && !d.get_io$$memory$$request$$bits$$atomicOp() &&
                bool(d.get_io$$memory$$request$$bits$$virtualized()) == (o.virt && !o.prechecked) &&
                bool(d.get_io$$memory$$request$$bits$$precheckedLoad()) == o.prechecked &&
                d.get_io$$memory$$request$$bits$$translationEpoch() == o.epoch &&
                !d.get_io$$memory$$request$$bits$$uncached() && !d.get_io$$memory$$request$$bits$$prefetchNextAllowed(),
                "M3_REQUEST_PAYLOAD: actual request differs from independently accepted operation");
            check(bool(d.get_io$$origin$$valid()) == o.origin, "M3_ORIGIN_VALID: store origin validity mismatch");
            if (o.origin) check(d.get_io$$origin$$bits$$token$$index() == o.token.index &&
                d.get_io$$origin$$bits$$token$$tag() == o.token.tag && d.get_io$$origin$$bits$$epoch() == o.epoch,
                "M3_ORIGIN_OWNER: actual store request lost canonical token/epoch");
        }
        const bool responseFire = reply && d.get_io$$memory$$response$$ready();
        check(unsigned(d.get_io$$slotResponse()) == (responseFire ? 1U : 0U),
            "M3_RESPONSE_SLOT: real reply did not reach original request owner");
        if (responseFire) check(active && pending.front().owner == active && active->requested && !active->responded &&
            phase == 2 && cycle > active->requestCycle, "M3_RESPONSE_OWNER: reply lacks prior actual request");
        if (lastComplete) {
            active->completed = active->drained = true; active->completeCycle = cycle; ++completions;
            if (active->forward && cycle == active->startCycle + 1) ++nextCycleLoads;
        }
        if (cancelledNow) { check(!active->store, "DRIVER_ERROR: cancelled irrevocable store"); active->cancelled = true; }
        if (discard) { active->drained = true; ++discards; }
        if (lastComplete || discard) { active.reset(); phase = 0; }
        if (take) {
            active = offer; active->accepted = true; active->startCycle = cycle;
            phase = active->forward ? 3 : 1; history.push_back(active); ++starts;
        }
        if (requestValid && memoryReady) {
            requestOwner->requested = true; requestOwner->requestCycle = cycle;
            pending.push_back({requestOwner,cycle + 3}); phase = 2; ++requests;
        }
        if (responseFire) {
            active->responded = true; active->responseCycle = cycle; pending.pop_front(); phase = 3; ++responses;
        }
        ++cycle; return take;
    }
    template <class Predicate> void until(Predicate done, const char *why) {
        for (unsigned i = 0; i < 100 && !done(); ++i) tick();
        check(done(),why);
    }
    void accept(const Ptr &o) {
        for (unsigned i = 0; i < 100; ++i) if (tick(o)) return;
        throw std::runtime_error("M3_ACCEPT_TIMEOUT: requested owner never accepted");
    }
    void reject(const Ptr &o, unsigned count, bool beforeReply) {
        for (unsigned i = 0; i < count; ++i) {
            check(!tick(o), "M3_HELD_SOURCE: forwarded load admitted without actual successful source turnover");
            if (beforeReply) ++preReplyBlocked; else ++heldBlocked;
        }
    }
    void returned(const Ptr &o) {
        allowReplies = true;
        until([&] { return o->responded; }, "M3_REPLY_TIMEOUT: actual store reply did not complete");
        tick();
    }
    void drain() {
        allowReplies = memoryReady = completeReady = true; cancel.reset();
        until([&] { return !active && pending.empty(); }, "M3_DRAIN_TIMEOUT: LSU failed to drain");
        tick(); tick();
        check(requests == responses, "M3_CONSERVATION: actual memory request/reply imbalance");
        for (const auto &o : history) {
            check(o->drained && (o->completed != o->cancelled), "M3_CONSERVATION: owner lost or completed after cancellation");
            check(o->forward ? (!o->requested && !o->responded) : (o->requested && o->responded),
                "M3_CONSERVATION: forwarded/physical response obligation changed");
        }
    }
};

void mutate(const std::string &kind, const Ptr &load) {
    auto &c = load->certificate;
    if (kind == "source-tag") c.token.tag ^= 1ULL << 40;
    else if (kind == "source-index") c.token.index ^= 1;
    else if (kind == "source-epoch") ++c.epoch;
    else if (kind == "load-epoch") ++load->epoch;
    else if (kind == "source-va") c.va += 8;
    else if (kind == "source-size") c.size = 2;
    else if (kind == "source-mask") c.mask ^= 1;
    else if (kind == "source-pa") c.pa = 0x10000100ULL;
    else if (kind == "load-offset") load->physical ^= 1;
    else if (kind == "coverage") { load->address += 8; load->physical += 8; }
    else if (kind == "missing-certificate") c.valid = false;
    else if (kind == "forward-data") load->forwardXor = 1ULL << 56;
}

void widthCases(const std::string &mutation) {
    struct Case { const char *name; unsigned storeOffset, storeSize, loadOffset, loadSize; bool unsign; uint64_t data; };
    const std::array cases{
        Case{"lb-negative",0,3,7,0,false,0x80fedcba98765481ULL},
        Case{"lbu",0,3,7,0,true,0x80fedcba98765481ULL},
        Case{"lh-negative",0,3,6,1,false,0x80fedcba98765481ULL},
        Case{"lhu",0,3,2,1,true,0x80fedcba98765481ULL},
        Case{"lw-negative",0,3,4,2,false,0x80fedcba98765481ULL},
        Case{"lwu",0,3,4,2,true,0x80fedcba98765481ULL},
        Case{"ld",0,3,0,3,false,0x80fedcba98765481ULL},
        Case{"lb-positive",0,3,1,0,false,0x80fedcba98765481ULL},
        Case{"lh-positive",0,3,0,1,false,0x80fedcba98765481ULL},
        Case{"lw-positive",0,3,0,2,false,0x80fedcba18765481ULL},
        Case{"sb-nonzero",7,0,7,0,true,0x81ULL},
        Case{"sh-nonzero",6,1,7,0,false,0x8172ULL},
        Case{"sw-nonzero",4,2,6,1,false,0x81725436ULL}};
    Bench b(mutation);
    for (const auto &test : cases) {
        b.completeReady = false; b.allowReplies = false; b.memoryReady = false;
        auto source = b.source(test.storeOffset,test.storeSize,test.data);
        auto load = b.forwarded(source,test.loadOffset,test.loadSize,test.unsign);
        b.accept(source);
        check(!source->requested, "SETUP: request backpressure failed");
        b.reject(load,2,true);
        b.memoryReady = true;
        b.until([&] { return source->requested; }, "SETUP: actual store request missing");
        b.reject(load,2,true);
        b.returned(source);
        check(b.lastSource && !source->completed, "SETUP: successful source not held at completion");
        b.reject(load,3,false);
        const auto requestCount = b.requests, responseCount = b.responses, completionCount = b.completions;
        if (!mutation.empty() && mutation.rfind("oracle-",0) != 0) { mutate(mutation,load); b.anchor(mutation); }
        b.completeReady = true;
        check(b.tick(load), "M3_NO_TURNOVER: certified load was not accepted on source completion edge");
        check(source->completed && source->completeCycle == load->startCycle && b.lastComplete &&
            b.completions == completionCount + 1 && b.requests == requestCount && b.responses == responseCount,
            "M3_EXACT_TURNOVER: old completion/new load did not share one exact-owner edge");
        b.tick();
        check(load->completed && load->completeCycle == load->startCycle + 1,
            "M3_NEXT_COMPLETION: forwarded load missed next-cycle completion");
        b.drain();
        std::cout << "A1_M3_TURNOVER_CASE name=" << test.name << " slots=" << b.slots
            << " source_requests=1 load_requests=0 same_edge_turnover=1 next_cycle_complete=1\n";
    }
    check(b.turnover == cases.size() && b.nextCycleLoads == cases.size() && b.requests == cases.size() &&
        b.responses == cases.size() && b.completions == 2 * cases.size(), "M3_WIDTH_COVERAGE: incomplete width scenario ledger");
    std::cout << "A1_M3_WIDTHS_PASS slots=" << b.slots << " cases=" << cases.size()
        << " held_blocked=" << b.heldBlocked << " prereply_blocked=" << b.preReplyBlocked
        << " full_tag_reuse=1 alias_va=1\n";
}

void faultCases(const std::string &mutation) {
    Bench b;
    for (bool page : {false,true}) {
        b.completeReady = false; b.allowReplies = false;
        auto source = b.source(0,3,0x80fedcba98765481ULL,!page,page);
        auto forbidden = b.forwarded(source,7,0,false);
        b.accept(source); b.returned(source);
        check(!b.lastSource && !source->completed, "M3_FAULT_SOURCE: failed actual store remains eligible");
        b.reject(forbidden,3,false);
        b.completeReady = true;
        if (mutation == (page ? "page-source" : "error-source")) { b.anchor(mutation); b.tick(forbidden); }
        b.tick();
        check(source->completed && !forbidden->accepted, "M3_FAULT_RETIRE: fault did not remain precise/source-only");
        auto ordinary = b.ordinary(); b.accept(ordinary); b.returned(ordinary); b.drain();
        check(ordinary->requested && ordinary->responded && ordinary->completed,
            "M3_FAULT_FALLBACK: fault suppressed a later ordinary real memory request");
        std::cout << "A1_M3_FAULT_SOURCE_PASS kind=" << (page ? "page-fault" : "access-error")
            << " no_forward_source=1 ordinary_request=1\n";
    }
}

void cancelCase() {
    Bench b;
    auto source = b.source(0,3,0x80fedcba98765481ULL);
    auto load = b.forwarded(source,6,1,false);
    b.accept(source); b.returned(source); b.completeReady = true;
    check(b.tick(load) && source->completed, "SETUP: cancellation case lacks real turnover");
    b.completeReady = false;
    // A stale same-index cancellation must not kill this generation.
    b.cancel = Token{load->token.index, load->token.tag ^ (1ULL << 40)};
    b.tick(); check(!load->cancelled && !load->completed, "M3_CANCEL_TOKEN: stale-generation cancellation hit live owner");
    b.cancel = load->token; b.tick(); b.cancel.reset(); b.drain();
    check(load->cancelled && load->drained && !load->completed && b.requests == 1 && b.responses == 1 &&
        b.completions == 1 && b.discards == 1, "M3_CANCELLED_COMPLETION: accepted cancelled load falsely completed");
    std::cout << "A1_M3_CANCEL_PASS actual_source_reply=1 exact_cancel=1 stale_cancel_rejected=1 load_completed=0\n";
}
} // namespace

int main(int argc, char **argv) {
    try {
        std::string mutation;
        if (argc == 2 && std::string(argv[1]).rfind("--inject-",0) == 0) mutation = std::string(argv[1]).substr(9);
        else check(argc == 1, "usage: completed_canonical_forward [--inject-MUTATION]");
        if (mutation == "owner") mutation = "source-tag";
        else if (mutation == "data") mutation = "forward-data";
        else if (mutation == "observation") mutation = "oracle-data";
        const std::vector<std::string> allowed{"source-tag","source-index","source-epoch","load-epoch","source-va",
            "source-size","source-mask","source-pa","load-offset","coverage","missing-certificate","forward-data",
            "oracle-data","oracle-token","oracle-request","oracle-turnover","error-source","page-source"};
        bool known = mutation.empty(); for (const auto &name : allowed) known |= mutation == name;
        check(known, "unknown completed-canonical-forward mutation");
        if (mutation == "error-source" || mutation == "page-source") faultCases(mutation);
        else { widthCases(mutation); faultCases({}); cancelCase(); }
        check(mutation.empty(), "M3_MUTATION_SURVIVED: negative control failed to detect the injected defect");
        std::cout << "A1_M3_COMPLETED_FORWARD_PASS real_parallel_lsu=1 actual_store_replies=1"
            << " widths=7 nonzero_offsets=1 precise_faults=1 cancellation=1 full_token_reuse=1\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "A1_M3_COMPLETED_FORWARD_FAIL " << error.what() << '\n'; return 1;
    }
}
