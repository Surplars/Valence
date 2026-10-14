#include "LoadReadyDirectGsim.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <map>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

namespace {
constexpr uint64_t ram = 0x80010000ULL, ramBytes = 4096;
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token&) const = default;
};
struct Operation {
    Token token;
    uint64_t pc = 0, address = ram, data = 0x9abcdeff87654321ULL;
    uint64_t forwardData = 0x80ff7f01800081feULL;
    unsigned size = 3, atomicOp = 0;
    bool unsignedLoad = false, store = false, atomic = false, denied = false;
    bool virtualized = false, forwarded = false;
};
struct Input {
    std::optional<Operation> start;
    bool requestReady = false, responseValid = false, error = false, pageFault = false;
    bool completeReady = false, cancel = false;
    uint64_t responseData = 0x80ff7f01800081feULL;
};
struct Result {
    Token token;
    uint64_t data = 0, nextPc = 0, cause = 0, tval = 0;
    bool exception = false;
    bool operator==(const Result&) const = default;
};
struct Observation {
    unsigned phase = 0;
    bool busy = false, issueAvailable = false, cancelled = false, startReady = false;
    bool capture = false, discarded = false, forwarded = false, completeValid = false;
    bool requestValid = false, responseReady = false, previewValid = false, storeForwardValid = false;
    Token owner, storeForwardToken;
    Result result, preview;
    uint64_t requestAddress = 0, requestData = 0, requestEpoch = 0, storeForwardAddress = 0;
    uint64_t storeForwardData = 0;
    unsigned requestSize = 0, requestMask = 0, requestAtomicOp = 0, storeForwardSize = 0;
    bool requestWrite = false, requestAtomic = false, requestVirtual = false;
    bool requestPrechecked = false, requestUncached = false, requestPrefetch = false;
};
struct Record {
    Operation op;
    bool requested = false, responded = false, completed = false, cancelled = false, discarded = false;
};
struct State {
    unsigned phase = 0; // Independent protocol ledger: free, waiting request, waiting response, stored result.
    bool cancelled = false, initialized = false, freshSuccessfulResult = false;
    Operation op;
    Result result;
    size_t owner = 0;
};
struct Event {
    bool start = false, request = false, response = false, completion = false, discard = false;
    bool bypass = false, capture = false;
    Operation sending;
};

uint64_t value(uint64_t beat, const Operation& op) {
    const unsigned width = 8U << op.size;
    const uint64_t shifted = beat >> (8 * (op.address & 7));
    if (width == 64) return shifted;
    const uint64_t mask = (uint64_t(1) << width) - 1;
    const uint64_t low = shifted & mask;
    return !op.unsignedLoad && (low & (uint64_t(1) << (width - 1))) ? low | ~mask : low;
}
bool misaligned(const Operation& op) { return (op.address & ((uint64_t(1) << op.size) - 1)) != 0; }
bool atomicFault(const Operation& op) {
    return op.atomic && !op.virtualized &&
        (op.address < ram || op.address >= ram + ramBytes ||
         (uint64_t(1) << op.size) > ram + ramBytes - op.address);
}
bool staticFault(const Operation& op) { return misaligned(op) || op.denied || atomicFault(op); }
bool ordinary(const Operation& op) { return !op.store && !op.atomic; }
bool writeAccess(const Operation& op) { return op.store || (op.atomic && op.atomicOp != 2); }
Result initialResult(const Operation& op) {
    Result r;
    r.token = op.token; r.nextPc = op.pc + 4; r.tval = op.address;
    r.exception = staticFault(op);
    // Initial capture and later memory reply are separate writers. The original
    // start writer chooses the final nonfault cause by atomic-write class only;
    // an allowed ordinary store therefore retains cause5 until its real reply.
    r.cause = misaligned(op) ? (writeAccess(op) ? 6 : 4) :
        (op.denied ? (writeAccess(op) ? 7 : 5) : (op.atomic && op.atomicOp != 2 ? 7 : 5));
    r.data = op.forwarded ? value(op.forwardData, op) : 0;
    return r;
}
void applyReply(Result& r, const Operation& op, const Input& in) {
    r.data = op.atomic ? in.responseData : (op.store ? 0 : value(in.responseData, op));
    r.exception = in.error || in.pageFault;
    r.cause = in.pageFault ? (writeAccess(op) ? 15 : 13) : (writeAccess(op) ? 7 : 5);
}

Observation read(SLoadReadyDirectGsim& d, unsigned lane, bool initialized) {
    Observation o;
#define RESULT(P,R) \
    R.token = {unsigned(d.get_io$$lane##P##$$complete$$bits$$token$$index()), \
        uint64_t(d.get_io$$lane##P##$$complete$$bits$$token$$tag())}; \
    R.data = d.get_io$$lane##P##$$complete$$bits$$data(); \
    R.nextPc = d.get_io$$lane##P##$$complete$$bits$$nextPc(); \
    R.exception = d.get_io$$lane##P##$$complete$$bits$$exception(); \
    R.cause = d.get_io$$lane##P##$$complete$$bits$$cause(); \
    R.tval = d.get_io$$lane##P##$$complete$$bits$$tval()
#define SIDE(P) \
    o.phase = d.get_io$$lane##P##$$phase(); \
    o.busy = d.get_io$$lane##P##$$busy(); \
    o.issueAvailable = d.get_io$$lane##P##$$issueAvailable(); \
    o.cancelled = d.get_io$$lane##P##$$registeredCancelled(); \
    o.startReady = d.get_io$$lane##P##$$startReady(); \
    o.capture = d.get_io$$lane##P##$$capture(); \
    o.discarded = d.get_io$$lane##P##$$discarded(); \
    o.forwarded = d.get_io$$lane##P##$$forwarded(); \
    o.completeValid = d.get_io$$lane##P##$$complete$$valid(); \
    if (initialized) { \
        o.owner = {unsigned(d.get_io$$lane##P##$$owner$$index()), uint64_t(d.get_io$$lane##P##$$owner$$tag())}; \
        RESULT(P,o.result); \
    } \
    o.requestValid = d.get_io$$lane##P##$$memory$$request$$valid(); \
    o.responseReady = d.get_io$$lane##P##$$memory$$response$$ready(); \
    o.previewValid = d.get_io$$lane##P##$$fastLoadPreview$$valid(); \
    if (o.previewValid) { \
    o.preview.token = {unsigned(d.get_io$$lane##P##$$fastLoadPreview$$bits$$token$$index()), \
        uint64_t(d.get_io$$lane##P##$$fastLoadPreview$$bits$$token$$tag())}; \
    o.preview.data = d.get_io$$lane##P##$$fastLoadPreview$$bits$$data(); \
    o.preview.nextPc = d.get_io$$lane##P##$$fastLoadPreview$$bits$$nextPc(); \
    o.preview.exception = d.get_io$$lane##P##$$fastLoadPreview$$bits$$exception(); \
    o.preview.cause = d.get_io$$lane##P##$$fastLoadPreview$$bits$$cause(); \
    o.preview.tval = d.get_io$$lane##P##$$fastLoadPreview$$bits$$tval(); \
    } \
    if (o.requestValid) { \
    o.requestAddress = d.get_io$$lane##P##$$memory$$request$$bits$$address(); \
    o.requestData = d.get_io$$lane##P##$$memory$$request$$bits$$data(); \
    o.requestSize = d.get_io$$lane##P##$$memory$$request$$bits$$size(); \
    o.requestMask = d.get_io$$lane##P##$$memory$$request$$bits$$mask(); \
    o.requestAtomicOp = d.get_io$$lane##P##$$memory$$request$$bits$$atomicOp(); \
    o.requestWrite = d.get_io$$lane##P##$$memory$$request$$bits$$write(); \
    o.requestAtomic = d.get_io$$lane##P##$$memory$$request$$bits$$atomic(); \
    o.requestVirtual = d.get_io$$lane##P##$$memory$$request$$bits$$virtualized(); \
    o.requestEpoch = d.get_io$$lane##P##$$memory$$request$$bits$$translationEpoch(); \
    o.requestPrechecked = d.get_io$$lane##P##$$memory$$request$$bits$$precheckedLoad(); \
    o.requestUncached = d.get_io$$lane##P##$$memory$$request$$bits$$uncached(); \
    o.requestPrefetch = d.get_io$$lane##P##$$memory$$request$$bits$$prefetchNextAllowed(); \
    } \
    o.storeForwardValid = d.get_io$$lane##P##$$forwardStore$$valid(); \
    if (o.storeForwardValid) { \
    o.storeForwardToken = {unsigned(d.get_io$$lane##P##$$forwardStore$$bits$$token$$index()), \
        uint64_t(d.get_io$$lane##P##$$forwardStore$$bits$$token$$tag())}; \
    o.storeForwardAddress = d.get_io$$lane##P##$$forwardStore$$bits$$address(); \
    o.storeForwardData = d.get_io$$lane##P##$$forwardStore$$bits$$data(); \
    o.storeForwardSize = d.get_io$$lane##P##$$forwardStore$$bits$$size(); \
    }
    if (lane == 0) { SIDE(0); } else { SIDE(1); }
#undef SIDE
#undef RESULT
    return o;
}

class Bench {
    alignas(SLoadReadyDirectGsim) std::byte storage[sizeof(SLoadReadyDirectGsim)]{};
    SLoadReadyDirectGsim& dut;
    bool enabled;
    std::string mutation, label;
    std::array<State, 2> state{};
    std::array<std::vector<Record>, 2> ledger;
    std::array<uint64_t, 2> serial{};
    std::array<std::map<std::string, uint64_t>, 2> cover;
    uint64_t cycle = 0, mutations = 0, postChecks = 0;
    void require(bool okay, const std::string& why, unsigned lane) const {
        if (!okay) throw std::runtime_error("lane=" + std::to_string(lane) + " cycle=" +
            std::to_string(cycle) + " case=" + label + " " + why);
    }
    void drive(unsigned lane, const Input& in) {
        const auto op = in.start.value_or(Operation{});
#define SIDE(P) \
        dut.set_io$$lane##P##$$startValid(in.start.has_value()); \
        dut.set_io$$lane##P##$$token$$index(op.token.index); dut.set_io$$lane##P##$$token$$tag(op.token.tag); \
        dut.set_io$$lane##P##$$pc(op.pc); dut.set_io$$lane##P##$$address(op.address); \
        dut.set_io$$lane##P##$$data(op.data); dut.set_io$$lane##P##$$size(op.size); \
        dut.set_io$$lane##P##$$unsignedLoad(op.unsignedLoad); dut.set_io$$lane##P##$$store(op.store); \
        dut.set_io$$lane##P##$$atomic(op.atomic); dut.set_io$$lane##P##$$atomicOp(op.atomicOp); \
        dut.set_io$$lane##P##$$accessDenied(op.denied); dut.set_io$$lane##P##$$virtualized(op.virtualized); \
        dut.set_io$$lane##P##$$forwardValid(op.forwarded); dut.set_io$$lane##P##$$forwardData(op.forwardData); \
        dut.set_io$$lane##P##$$cancel(in.cancel); dut.set_io$$lane##P##$$complete$$ready(in.completeReady); \
        dut.set_io$$lane##P##$$memory$$request$$ready(in.requestReady); \
        dut.set_io$$lane##P##$$memory$$response$$valid(in.responseValid); \
        dut.set_io$$lane##P##$$memory$$response$$bits$$data(in.responseData); \
        dut.set_io$$lane##P##$$memory$$response$$bits$$error(in.error); \
        dut.set_io$$lane##P##$$memory$$response$$bits$$pageFault(in.pageFault)
        if (lane == 0) { SIDE(0); } else { SIDE(1); }
#undef SIDE
    }
    Event expected(unsigned lane, const Input& in) const {
        const auto& s = state[lane];
        Event e;
        e.start = in.start && (s.phase == 0 || (s.phase == 3 && in.completeReady && !s.cancelled));
        e.bypass = lane == 0 && e.start && !staticFault(*in.start) && !in.start->forwarded;
        e.sending = e.bypass ? *in.start : s.op;
        e.request = (s.phase == 1 || e.bypass) && in.requestReady;
        e.response = in.responseValid && (s.phase == 2 || (s.phase == 1 && in.requestReady) || e.bypass);
        e.completion = s.phase == 3 && !s.cancelled && in.completeReady;
        e.discard = s.phase == 3 && (s.cancelled || in.cancel);
        // The oracle asks whether THIS accepted operation or reply creates a new
        // successful ordinary-load result. It does not read the candidate event.
        if (e.start) {
            const auto& op = *in.start;
            e.capture = ordinary(op) &&
                ((op.forwarded && !staticFault(op)) || (e.response && !in.error && !in.pageFault));
        } else {
            e.capture = e.response && ordinary(s.op) && !s.cancelled && !in.cancel && !in.error && !in.pageFault;
        }
        return e;
    }
    bool initialStoreBeforeReply(unsigned lane, const Input& in, const Observation& o) const {
        const auto& s = state[lane];
        if (!s.initialized || s.phase != 2 || !s.op.store || s.op.atomic || s.cancelled ||
            staticFault(s.op) || in.responseValid || s.result.exception || o.result.exception ||
            s.result.cause != 5 || o.result.cause != 5 || o.phase != 2 ||
            !(o.owner == s.op.token) || !(o.result.token == s.op.token)) return false;
        const auto& record = ledger[lane].at(s.owner);
        return record.requested && !record.responded;
    }
    void mutate(Observation& o, unsigned lane, const Input& in, const Event& e) {
        if (mutation.empty() || mutations) return;
        const auto& s = state[lane];
        bool reached = false;
        if (mutation == "--mutate-capture-drop" && enabled && e.capture && o.capture) {
            o.capture = false; reached = true;
        } else if (mutation == "--mutate-capture-add" && !e.capture && e.response && in.cancel && !o.capture) {
            o.capture = true; reached = true;
        } else if (mutation == "--mutate-store-initial-cause" && initialStoreBeforeReply(lane, in, o)) {
            o.result.cause = 7; reached = true;
        } else if (s.freshSuccessfulResult && s.phase == 3 && s.initialized) {
            if (mutation == "--mutate-result-data" && o.result.data == s.result.data) {
                o.result.data ^= 1; reached = true;
            } else if (mutation == "--mutate-token-high" && o.result.token == s.result.token) {
                o.result.token.tag ^= uint64_t(1) << 63; reached = true;
            } else if (mutation == "--mutate-post-phase" && o.phase == 3) {
                o.phase = 2; reached = true;
            }
        }
        if (reached) {
            ++mutations;
            std::cerr << "ACTUAL_CORRUPTION kind=host-sampled-observation mode=" << mutation
                      << " count=" << mutations << " lane=" << lane << " cycle=" << cycle
                      << " owner_index=" << s.op.token.index << " owner_tag=" << s.op.token.tag
                      << " phase=" << s.phase << " sampled_phase=" << o.phase
                      << (mutation == "--mutate-store-initial-cause" ? " cause_before=5 cause_after=7" : "") << '\n';
        }
    }
    void check(unsigned lane, const Input& in, Observation o, const Event& e) {
        const auto& s = state[lane];
        cover[lane]["ordinaryStoreInitialCause"] += initialStoreBeforeReply(lane, in, o);
        mutate(o, lane, in, e);
        // GSIM step exposes the pre-edge combinational observation. At each
        // next call these are the actual state/result produced by the prior
        // edge. The ledger was already advanced independently on that edge.
        require(o.phase == s.phase, "POST_EDGE_PHASE disagrees with accepted operation/response ledger", lane);
        require(o.cancelled == s.cancelled, "POST_EDGE_CANCELLED lost registered cancellation", lane);
        require(o.busy == (s.phase != 0), "busy differs from independent occupancy", lane);
        require(o.issueAvailable == (s.phase == 0 || (s.phase == 3 && !s.cancelled)),
            "reservation availability differs from state-only contract", lane);
        if (s.initialized) {
            ++postChecks;
            require(o.owner == s.op.token, "POST_EDGE_OWNER lost full accepted token", lane);
            require(o.result.token == s.result.token, "POST_EDGE_RESULT_TOKEN full-tag mismatch", lane);
            require(o.result.data == s.result.data, "POST_EDGE_RESULT_DATA independent lane/sign/reply mismatch", lane);
            require(o.result.nextPc == s.result.nextPc && o.result.tval == s.result.tval &&
                o.result.exception == s.result.exception && o.result.cause == s.result.cause,
                "POST_EDGE_RESULT precise metadata mismatch", lane);
        }
        require(o.startReady == (s.phase == 0 || (s.phase == 3 && in.completeReady && !s.cancelled)),
            "start replacement authorization differs from old result drain", lane);
        require(o.requestValid == (s.phase == 1 || e.bypass), "request valid phase/bypass mismatch", lane);
        require(o.responseReady == (s.phase == 2 || (s.phase == 1 && in.requestReady) || e.bypass),
            "response ready escaped direct/registered request boundary", lane);
        require(o.completeValid == (s.phase == 3 && !s.cancelled), "completion escaped result/cancellation state", lane);
        require(o.discarded == e.discard, "discard priority mismatch", lane);
        require(o.capture == (enabled && e.capture), "CAPTURE_EVENT differs from independent result-write event", lane);
        require(o.forwarded == (e.start && in.start->forwarded && !misaligned(*in.start) && !in.start->denied),
            "forwarded start classification mismatch", lane);
        const bool preview = s.phase == 2 && in.responseValid && ordinary(s.op) &&
            !s.cancelled && !in.cancel && !in.error && !in.pageFault;
        require(o.previewValid == preview, "fast preview class/cancel/error mismatch", lane);
        if (preview) {
            auto want = s.result; want.data = value(in.responseData, s.op); want.exception = false;
            require(o.preview == want, "preview original token/data/metadata mismatch", lane);
        }
        const bool storeForward = s.phase == 3 && s.op.store && !s.result.exception;
        require(o.storeForwardValid == storeForward, "store result classification mismatch", lane);
        if (storeForward) require(o.storeForwardToken == s.op.token && o.storeForwardAddress == s.op.address &&
            o.storeForwardSize == s.op.size && o.storeForwardData == (s.op.data << (8 * (s.op.address & 7))),
            "stored forwarding payload lost original operation", lane);
        if (o.requestValid) {
            const auto& op = e.sending;
            const unsigned mask = unsigned((((uint64_t(1) << (1U << op.size)) - 1) << (op.address & 7)) & 255);
            require(o.requestAddress == op.address && o.requestData == (op.atomic ? op.data : op.data << (8 * (op.address & 7))) &&
                o.requestSize == op.size && o.requestMask == mask && o.requestAtomicOp == op.atomicOp &&
                o.requestWrite == op.store && o.requestAtomic == op.atomic && o.requestVirtual == op.virtualized &&
                !o.requestEpoch && !o.requestPrechecked && !o.requestUncached && !o.requestPrefetch,
                "REQUEST_PAYLOAD differs from accepted owner during ready/hold/cancel", lane);
        }
    }
    void advance(unsigned lane, const Input& in, const Event& e) {
        auto& s = state[lane]; auto& c = cover[lane];
        const auto prior = s;
        if (in.cancel && prior.phase != 0) {
            require(ordinary(prior.op), "driver attempted irrevocable cancellation", lane);
            ledger[lane].at(prior.owner).cancelled = true; s.cancelled = true; ++c["cancelEdges"];
        }
        if (e.completion) {
            auto& old = ledger[lane].at(prior.owner);
            require(!old.completed, "duplicate completion in operation ledger", lane);
            require(old.responded || old.op.forwarded || staticFault(old.op), "completion before result source", lane);
            old.completed = true; ++c["completions"];
        }
        if (e.discard) { ledger[lane].at(prior.owner).discarded = true; ++c["discards"]; }
        if (e.start) {
            for (const auto& old : ledger[lane]) require(!(old.op.token == in.start->token), "driver reused a full token", lane);
            s.owner = ledger[lane].size(); ledger[lane].push_back({*in.start});
            s.op = *in.start; s.cancelled = false; s.initialized = true; s.result = initialResult(s.op);
            ++c["starts"]; c["highTags"] += (s.op.token.tag >> 32) != 0; c["index15"] += s.op.token.index == 15;
            c["replacements"] += prior.phase == 3;
        }
        if (e.request) {
            auto& record = ledger[lane].at(s.owner);
            require(!record.requested && !record.responded && !record.op.forwarded && !staticFault(record.op),
                "request escaped accepted operation or duplicated", lane);
            record.requested = true; ++c["requests"];
        }
        if (e.response) {
            auto& record = ledger[lane].at(s.owner);
            require(record.requested && !record.responded, "response without exactly one original accepted request", lane);
            record.responded = true; applyReply(s.result, record.op, in); ++c["responses"];
        }
        // State movement follows protocol milestones recorded above, not the event.
        if (e.start) {
            s.phase = staticFault(s.op) || s.op.forwarded || e.response ? 3 : (e.request ? 2 : 1);
        } else if (e.discard || e.completion) s.phase = 0;
        else if (e.response) s.phase = 3;
        else if (e.request) s.phase = 2;
        s.freshSuccessfulResult = e.capture;
        c["semanticCaptures"] += e.capture; c["observedCaptures"] += enabled && e.capture;
        c["doneHoldEdges"] += prior.phase == 3 && !e.completion && !e.discard && !e.start;
        c["heldRequestEdges"] += prior.phase == 1 && !in.requestReady;
        c["postCaptureEdges"] += prior.freshSuccessfulResult;
    }
public:
    Bench(bool flag, std::string mode)
        : dut(*::new(static_cast<void*>(storage)) SLoadReadyDirectGsim),
          enabled(flag), mutation(std::move(mode)) {
        static_assert(std::is_trivially_copyable_v<SLoadReadyDirectGsim>);
        dut.LOG_START = 1; dut.activateAll();
        drive(0, {}); drive(1, {}); dut.set_reset(1);
        dut.step(); dut.resetAll(); dut.step(); dut.resetAll();
        dut.activateAll(); dut.set_reset(0); tick(0, {}, "after-reset");
    }
    ~Bench() { dut.~SLoadReadyDirectGsim(); }
    Operation op(unsigned lane) {
        const uint64_t n = ++serial[lane];
        Operation o; o.token = {unsigned(n % 16), (uint64_t(1) << 63) | (n << 40) | (n << 4) | lane};
        o.pc = 0x1000 + 4 * n; o.address = ram + (n % 32) * 8; return o;
    }
    void tick(unsigned lane, Input in, const std::string& name) {
        label = name;
        std::array<Input, 2> inputs{}; inputs[lane] = in;
        drive(0, inputs[0]); drive(1, inputs[1]); dut.step();
        require(bool(dut.get_io$$enabled()) == enabled, "host feature flag does not match emitted model", lane);
        for (unsigned i = 0; i < 2; ++i) {
            const auto e = expected(i, inputs[i]);
            check(i, inputs[i], read(dut, i, state[i].initialized), e); advance(i, inputs[i], e);
        }
        ++cycle; dut.resetAll();
    }
    void count(unsigned lane, const std::string& name) { ++cover[lane][name]; }
    void start(unsigned lane, const Operation& o, bool ready = false, const std::string& name = "start") {
        require(state[lane].phase == 0, "test start requires drained slot", lane);
        Input in; in.start = o; in.requestReady = ready; tick(lane, in, name);
    }
    void request(unsigned lane) {
        if (state[lane].phase == 1) { Input in; in.requestReady = true; tick(lane, in, "accept-request"); }
        require(state[lane].phase == 2, "test expected response owner", lane);
    }
    void reply(unsigned lane, bool error = false, bool page = false, bool cancel = false) {
        require(state[lane].phase == 2, "test reply requires original request", lane);
        Input in; in.responseValid = true; in.error = error; in.pageFault = page; in.cancel = cancel;
        tick(lane, in, "deliver-owned-response");
    }
    void drain(unsigned lane) {
        require(state[lane].phase == 3, "test drain requires result", lane);
        Input in; in.completeReady = true; tick(lane, in, "drain-actual-post-edge-result");
        tick(lane, {}, "verify-idle-after-drain");
        require(state[lane].phase == 0, "result failed to drain", lane);
    }
    void delayed(unsigned lane, Operation o, bool error = false, bool page = false) {
        start(lane, o, true); request(lane);
        tick(lane, {}, "response-delay-0"); tick(lane, {}, "response-delay-1");
        reply(lane, error, page); tick(lane, {}, "post-response-result-held"); drain(lane);
    }
    void suite(unsigned lane) {
        delayed(lane, op(lane)); count(lane, "normalDelayed");
        {
            start(lane, op(lane)); tick(lane, {}, "held-request-0"); tick(lane, {}, "held-request-1");
            Input in; in.requestReady = true; in.responseValid = true;
            tick(lane, in, "request-and-response-same-edge"); drain(lane); count(lane, "requestResponse");
        }
        {
            Input in; in.start = op(lane); in.requestReady = true; in.responseValid = true;
            tick(lane, in, "new-start-response-boundary");
            if (lane) { in.start.reset(); tick(lane, in, "registered-start-later-request-response"); }
            drain(lane); count(lane, lane ? "registeredStartBoundary" : "immediateStartResponse");
        }
        for (unsigned size = 0; size < 4; ++size) for (unsigned unsign = 0; unsign < 2; ++unsign)
            for (unsigned offset = 0; offset < 8; offset += 1U << size) {
                auto o = op(lane); o.address = ram + offset; o.size = size; o.unsignedLoad = unsign;
                o.forwarded = true; start(lane, o, true, "forwarded-lane-and-sign"); drain(lane);
                count(lane, "forwardedStarts");
                o = op(lane); o.address = ram + offset; o.size = size; o.unsignedLoad = unsign;
                delayed(lane, o); count(lane, "responseLaneAndSign");
            }
        for (unsigned kind = 0; kind < 6; ++kind) {
            auto o = op(lane);
            if (kind == 0 || kind == 2) o.address += 1;
            if (kind == 1 || kind == 3) o.denied = true;
            if (kind == 2 || kind == 3) o.forwarded = true;
            if (kind >= 4) { o.atomic = true; o.address = 0; o.atomicOp = kind == 4 ? 0 : 2; }
            start(lane, o, true, "static-fault-excludes-capture"); drain(lane);
            count(lane, kind < 2 ? (kind ? "accessFault" : "alignmentFault") :
                (kind < 4 ? "forwardedFault" : "atomicRangeFault"));
        }
        for (unsigned kind = 0; kind < 3; ++kind) {
            auto o = op(lane); o.virtualized = true;
            delayed(lane, o, kind != 1, kind != 0);
            count(lane, kind == 0 ? "responseFault" : "pageFault");
        }
        for (unsigned kind = 0; kind < 3; ++kind) for (unsigned fault = 0; fault < 3; ++fault) {
            auto o = op(lane); o.store = kind == 0; o.atomic = kind != 0; o.atomicOp = kind == 2 ? 2 : 0;
            o.virtualized = true; delayed(lane, o, fault == 1, fault == 2);
            count(lane, kind ? "atomicExcluded" : "storeExcluded");
        }
        for (unsigned cause = 0; cause < 2; ++cause) {
            auto o = op(lane); o.store = true; o.denied = cause; o.address += !cause;
            start(lane, o, true, "store-static-fault-excluded"); drain(lane); count(lane, "storeStaticFault");
        }
        {
            auto old = op(lane); old.forwarded = true; start(lane, old);
            auto fresh = op(lane); fresh.forwarded = true;
            fresh.token = {old.token.index, old.token.tag ^ (uint64_t(1) << 63)};
            Input in; in.start = fresh; in.completeReady = true;
            tick(lane, in, "old-done-drain-new-forwarded-full-tag-owner"); drain(lane); count(lane, "doneReplace");
        }
        {
            auto old = op(lane); old.forwarded = true; start(lane, old);
            Input in; in.start = op(lane); in.completeReady = true; in.requestReady = true; in.responseValid = true;
            tick(lane, in, "old-done-drain-new-memory-start");
            if (lane) { in.start.reset(); in.completeReady = false; tick(lane, in, "replacement-registered-response"); }
            drain(lane); count(lane, "doneReplaceMemory");
        }
        {
            start(lane, op(lane), true); request(lane); reply(lane, false, false, true);
            drain(lane); count(lane, "sameEdgeCancelResponse");
        }
        {
            start(lane, op(lane), true); request(lane); Input kill; kill.cancel = true;
            tick(lane, kill, "register-cancellation-before-reply");
            tick(lane, {}, "cancelled-response-delay-0"); tick(lane, {}, "cancelled-response-delay-1");
            reply(lane); drain(lane); count(lane, "registeredCancelDelayedResponse");
        }
        {
            start(lane, op(lane)); Input kill; kill.cancel = true;
            tick(lane, kill, "cancel-held-request"); tick(lane, {}, "cancelled-held-request-stable");
            request(lane); reply(lane); drain(lane); count(lane, "cancelHeldRequest");
        }
        {
            auto o = op(lane); o.forwarded = true; start(lane, o);
            Input kill; kill.cancel = true; tick(lane, kill, "same-edge-cancel-clears-done-without-ready");
            tick(lane, {}, "verify-cancelled-done-cleared"); count(lane, "cancelDoneClear");
        }
        {
            auto o = op(lane); o.forwarded = true; start(lane, o);
            auto fresh = op(lane); fresh.forwarded = true;
            Input in; in.start = fresh; in.completeReady = true; in.cancel = true;
            tick(lane, in, "new-owner-wins-old-done-cancel-and-drain"); drain(lane); count(lane, "cancelDoneReplacement");
        }
        {
            start(lane, op(lane), true); request(lane); reply(lane, false, false, true);
            auto fresh = op(lane); fresh.forwarded = true;
            Input in; in.start = fresh; in.completeReady = true;
            tick(lane, in, "registered-cancelled-done-blocks-replacement");
            require(state[lane].phase == 0, "registered cancellation did not clear before replacement", lane);
            tick(lane, in, "held-start-accepted-only-after-cancelled-clear"); drain(lane);
            count(lane, "registeredCancelClearPriority");
        }
        {
            auto fresh = op(lane); fresh.forwarded = true;
            Input in; in.start = fresh; in.cancel = true;
            tick(lane, in, "idle-new-owner-cancel-does-not-kill-new-start"); drain(lane);
            count(lane, "idleCancelNewStart");
        }
    }
    void finish() {
        tick(0, {}, "final-post-edge-check");
        if (!mutation.empty()) throw std::runtime_error("UNREACHED_CONTROL " + mutation + " mutations=" + std::to_string(mutations));
        const std::vector<std::string> required{"normalDelayed", "requestResponse", "forwardedStarts",
            "responseLaneAndSign", "alignmentFault", "accessFault", "forwardedFault", "atomicRangeFault",
            "responseFault", "pageFault", "storeExcluded", "atomicExcluded", "storeStaticFault", "doneReplace",
            "doneReplaceMemory", "sameEdgeCancelResponse", "registeredCancelDelayedResponse", "cancelHeldRequest",
            "cancelDoneClear", "cancelDoneReplacement", "registeredCancelClearPriority", "idleCancelNewStart",
            "highTags", "index15", "doneHoldEdges", "heldRequestEdges", "postCaptureEdges", "ordinaryStoreInitialCause"};
        for (unsigned lane = 0; lane < 2; ++lane) {
            require(state[lane].phase == 0, "final LSU not idle", lane);
            for (const auto& name : required) require(cover[lane][name] != 0, "missing required witness " + name, lane);
            require(cover[lane][lane ? "registeredStartBoundary" : "immediateStartResponse"] != 0,
                "missing direct/registered new-start response witness", lane);
            require(cover[lane]["requests"] == cover[lane]["responses"], "request/response conservation", lane);
            for (const auto& r : ledger[lane]) {
                const bool noMemory = r.op.forwarded || staticFault(r.op);
                require(noMemory ? (!r.requested && !r.responded) : (r.requested && r.responded),
                    "owner's independent response conservation failed", lane);
                require(r.completed || r.discarded, "accepted owner never drained", lane);
                require(!r.discarded || r.cancelled, "uncancelled owner discarded", lane);
            }
            std::cout << "DIRECT_LSU_COVERAGE registerStart=" << lane;
            for (const auto& [name, count] : cover[lane]) std::cout << ' ' << name << '=' << count;
            std::cout << '\n';
        }
        std::cout << "LOAD_READY_DIRECT_PASS enabled=" << enabled << " cycles=" << cycle
                  << " actual_post_edge_checks=" << postChecks << " mutations=" << mutations << '\n';
    }
};
} // namespace

int main(int argc, char** argv) {
    try {
        std::optional<bool> enabled;
        std::string mode;
        const std::vector<std::string> controls{"--mutate-capture-drop", "--mutate-capture-add",
            "--mutate-result-data", "--mutate-token-high", "--mutate-post-phase", "--mutate-store-initial-cause"};
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--enabled=0" || arg == "--enabled=1") {
                if (enabled) throw std::runtime_error("duplicate --enabled");
                enabled = arg.back() == '1';
            } else {
                bool known = false; for (const auto& control : controls) known |= arg == control;
                if (!known || !mode.empty()) throw std::runtime_error("unknown or duplicate direct control: " + arg);
                mode = arg;
            }
        }
        if (!enabled) throw std::runtime_error("usage: run --enabled=0|1 [one --mutate-* control]");
        if (!*enabled && mode == "--mutate-capture-drop")
            throw std::runtime_error("capture-drop requires the enabled event model");
        Bench b(*enabled, mode); b.suite(0); b.suite(1); b.finish(); return 0;
    } catch (const std::exception& e) {
        std::cerr << "LOAD_READY_DIRECT_FAIL " << e.what() << '\n'; return 1;
    }
}
