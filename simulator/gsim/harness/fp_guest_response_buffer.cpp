#include "FpGuestResponseBufferGsim.h"
#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

// Component packets only. Fault bits below are transport data, not actual traps
// or evidence that a guest floating-point instruction executed.
namespace {
constexpr unsigned LANES = 16, CAPACITY = 2, CYCLE_LIMIT = 1024;
constexpr uint64_t TRACE_LIMIT = 10 * 1024 * 1024;
constexpr std::array<const char *, 4> MODES{
    "queue_flow", "queue_registered", "registered_head", "empty_head_flow"};

struct Packet {
    uint64_t data = 0, gpa = 0;
    unsigned handle = 0;
    bool error = false, page = false, gpf = false, gva = false, implicit = false;
    bool operator==(const Packet &) const = default;
};
struct Request {
    uint64_t address = 0, data = 0;
    uint32_t epoch = 0;
    unsigned handle = 0, size = 0, mask = 0, op = 0;
    bool write = false, atomic = false, virt = false, prechecked = false, hint = false, uncached = false;
    bool operator==(const Request &) const = default;
};
struct Offer { uint64_t sequence; Packet packet; };
struct RequestOffer { uint64_t sequence; Request packet; };
struct Observed {
    bool inputReady = false, outputValid = false, idle = false;
    bool requestReady = false, forwardValid = false;
    Packet output;
    Request forward;
};
struct Counts {
    uint64_t accepted = 0, consumed = 0, heldInput = 0, heldOutput = 0, full = 0, fullPop = 0;
    uint64_t emptyBypass = 0, emptyCapture = 0, replacement = 0, tailPromotion = 0;
    uint64_t requests = 0, heldRequests = 0, requestsWhileFull = 0;
    uint64_t metadataChanges = 0, metadataClears = 0, highGpa = 0, highHandle = 0;
    uint64_t continuousAccepted = 0, continuousConsumed = 0, handleMask = 0;
    unsigned maximum = 0, statusMask = 0, metadataMask = 0;
};
struct Lane {
    // This deque represents accepted but not consumed response transactions.
    // It does not model head/tail registers, pointers, muxes, or DUT internals.
    std::deque<Packet> pending;
    std::optional<Offer> offer;
    std::optional<RequestOffer> request;
    std::optional<Packet> heldOutput, lastConsumed;
    std::optional<Offer> heldInput;
    std::optional<Request> heldRequest;
    uint64_t nextSequence = 0, nextRequest = 0;
    bool outputReady = false, forwardReady = true;
    Counts counts;
};

bool metadata(unsigned lane) { return (lane / 2) % 2; }
bool tagged(unsigned lane) { return lane % 2; }
bool flow(unsigned lane) { return lane / 4 == 0 || lane / 4 == 3; }
bool clearMetadata(const Packet &p) { return !p.gpf && !p.gva && !p.implicit && p.gpa == 0; }
bool sameMetadata(const Packet &a, const Packet &b) {
    return a.gpa == b.gpa && a.gpf == b.gpf && a.gva == b.gva && a.implicit == b.implicit;
}
Packet normalized(Packet p, unsigned lane) {
    if (!tagged(lane)) p.handle = 0;
    if (!metadata(lane)) { p.gpa = 0; p.gpf = p.gva = p.implicit = false; }
    return p;
}
Packet makePacket(unsigned lane, uint64_t sequence) {
    Packet p;
    const uint64_t identity = (uint64_t(lane) << 32) | sequence;
    p.data = UINT64_C(0xd37ac019fedcba98) ^ (identity * UINT64_C(0x0101010101010121));
    p.handle = unsigned((sequence * 17 + lane * 5) & 63);
    p.error = sequence & 1; p.page = sequence & 2;
    p.gpf = sequence & 1; p.gva = sequence & 2; p.implicit = sequence & 4;
    p.gpa = UINT64_C(0x8f01e2d3c4b5a697) ^ (uint64_t(1) << ((sequence + lane) % 64)) ^
        (sequence * UINT64_C(0x9e3779b97f4a7c15));
    if (sequence % 16 == 0) { p.gpa = ~uint64_t(0); p.gpf = p.gva = p.implicit = true; }
    if (sequence % 16 == 1) { p.gpa = 0; p.gpf = p.gva = p.implicit = false; }
    return p;
}
Request makeRequest(unsigned lane, uint64_t sequence) {
    Request r;
    r.address = UINT64_C(0xfedc000080000000) ^ (uint64_t(lane) << 20) ^ (sequence * 8);
    r.data = UINT64_C(0x89abcdef01234567) ^ (sequence * UINT64_C(0x0907050301070305));
    r.epoch = uint32_t(UINT32_C(0xa5c30000) ^ (lane << 12) ^ sequence);
    r.handle = unsigned((sequence * 29 + lane * 7) & 63);
    r.size = sequence & 3; r.mask = (sequence * 37 + 1) & 255; r.op = sequence & 31;
    r.write = sequence & 1; r.atomic = sequence & 2; r.virt = sequence & 4;
    r.prechecked = sequence & 8; r.hint = sequence & 16; r.uncached = sequence & 32;
    return r;
}

class Bench {
    alignas(SFpGuestResponseBufferGsim) std::byte storage[sizeof(SFpGuestResponseBufferGsim)]{};
    SFpGuestResponseBufferGsim &d;
    std::array<Lane, LANES> lanes;
    std::ofstream trace;
    std::string negative;
    bool mutated = false, resetting = false;
    uint64_t cycle = 0, traceBytes = 0;
    unsigned idleResets = 0, resetCycles = 0;

    void check(bool yes, const std::string &message, unsigned lane) const {
        if (!yes) throw std::runtime_error(message + " lane=" + std::to_string(lane) +
            " cycle=" + std::to_string(cycle));
    }
    void drive(unsigned index) {
        const auto &s = lanes[index];
        const Packet p = s.offer ? s.offer->packet : Packet{};
        const Request r = s.request ? s.request->packet : Request{};
        switch (index) {
#define DRIVE(N) case N: \
        d.set_io$$lane##N##$$response$$valid(bool(s.offer)); \
        d.set_io$$lane##N##$$response$$bits$$data(p.data); \
        d.set_io$$lane##N##$$response$$bits$$error(p.error); \
        d.set_io$$lane##N##$$response$$bits$$pageFault(p.page); \
        d.set_io$$lane##N##$$response$$bits$$returnHandle(p.handle); \
        d.set_io$$lane##N##$$response$$bits$$guestFault$$guestPageFault(p.gpf); \
        d.set_io$$lane##N##$$response$$bits$$guestFault$$guestAddress(p.gva); \
        d.set_io$$lane##N##$$response$$bits$$guestFault$$guestPhysicalAddress(p.gpa); \
        d.set_io$$lane##N##$$response$$bits$$guestFault$$implicitPte(p.implicit); \
        d.set_io$$lane##N##$$result$$ready(s.outputReady); \
        d.set_io$$lane##N##$$request$$valid(bool(s.request)); \
        d.set_io$$lane##N##$$request$$bits$$address(r.address); \
        d.set_io$$lane##N##$$request$$bits$$data(r.data); \
        d.set_io$$lane##N##$$request$$bits$$returnHandle(r.handle); \
        d.set_io$$lane##N##$$request$$bits$$atomic(r.atomic); \
        d.set_io$$lane##N##$$request$$bits$$atomicOp(r.op); \
        d.set_io$$lane##N##$$request$$bits$$write(r.write); \
        d.set_io$$lane##N##$$request$$bits$$size(r.size); \
        d.set_io$$lane##N##$$request$$bits$$mask(r.mask); \
        d.set_io$$lane##N##$$request$$bits$$virtualized(r.virt); \
        d.set_io$$lane##N##$$request$$bits$$precheckedLoad(r.prechecked); \
        d.set_io$$lane##N##$$request$$bits$$translationEpoch(r.epoch); \
        d.set_io$$lane##N##$$request$$bits$$prefetchNextAllowed(r.hint); \
        d.set_io$$lane##N##$$request$$bits$$uncached(r.uncached); \
        d.set_io$$lane##N##$$forwardRequest$$ready(s.forwardReady); break;
            DRIVE(0) DRIVE(1) DRIVE(2) DRIVE(3) DRIVE(4) DRIVE(5) DRIVE(6) DRIVE(7)
            DRIVE(8) DRIVE(9) DRIVE(10) DRIVE(11) DRIVE(12) DRIVE(13) DRIVE(14) DRIVE(15)
#undef DRIVE
        }
    }
    Observed observe(unsigned index) const {
        Observed o;
        switch (index) {
#define READ(N) case N: \
        o.inputReady = d.get_io$$lane##N##$$response$$ready(); \
        o.outputValid = d.get_io$$lane##N##$$result$$valid(); \
        o.idle = d.get_io$$lane##N##$$idle(); \
        o.output.data = d.get_io$$lane##N##$$result$$bits$$data(); \
        o.output.error = d.get_io$$lane##N##$$result$$bits$$error(); \
        o.output.page = d.get_io$$lane##N##$$result$$bits$$pageFault(); \
        o.output.handle = d.get_io$$lane##N##$$result$$bits$$returnHandle(); \
        o.output.gpf = d.get_io$$lane##N##$$result$$bits$$guestFault$$guestPageFault(); \
        o.output.gva = d.get_io$$lane##N##$$result$$bits$$guestFault$$guestAddress(); \
        o.output.gpa = d.get_io$$lane##N##$$result$$bits$$guestFault$$guestPhysicalAddress(); \
        o.output.implicit = d.get_io$$lane##N##$$result$$bits$$guestFault$$implicitPte(); \
        o.requestReady = d.get_io$$lane##N##$$request$$ready(); \
        o.forwardValid = d.get_io$$lane##N##$$forwardRequest$$valid(); \
        o.forward.address = d.get_io$$lane##N##$$forwardRequest$$bits$$address(); \
        o.forward.data = d.get_io$$lane##N##$$forwardRequest$$bits$$data(); \
        o.forward.handle = d.get_io$$lane##N##$$forwardRequest$$bits$$returnHandle(); \
        o.forward.atomic = d.get_io$$lane##N##$$forwardRequest$$bits$$atomic(); \
        o.forward.op = d.get_io$$lane##N##$$forwardRequest$$bits$$atomicOp(); \
        o.forward.write = d.get_io$$lane##N##$$forwardRequest$$bits$$write(); \
        o.forward.size = d.get_io$$lane##N##$$forwardRequest$$bits$$size(); \
        o.forward.mask = d.get_io$$lane##N##$$forwardRequest$$bits$$mask(); \
        o.forward.virt = d.get_io$$lane##N##$$forwardRequest$$bits$$virtualized(); \
        o.forward.prechecked = d.get_io$$lane##N##$$forwardRequest$$bits$$precheckedLoad(); \
        o.forward.epoch = d.get_io$$lane##N##$$forwardRequest$$bits$$translationEpoch(); \
        o.forward.hint = d.get_io$$lane##N##$$forwardRequest$$bits$$prefetchNextAllowed(); \
        o.forward.uncached = d.get_io$$lane##N##$$forwardRequest$$bits$$uncached(); break;
            READ(0) READ(1) READ(2) READ(3) READ(4) READ(5) READ(6) READ(7)
            READ(8) READ(9) READ(10) READ(11) READ(12) READ(13) READ(14) READ(15)
#undef READ
        }
        return o;
    }
    static void packetFields(std::ostream &out, const Packet &p) {
        out << ',' << p.data << ',' << p.error << ',' << p.page << ',' << p.handle
            << ',' << p.gpf << ',' << p.gva << ',' << p.gpa << ',' << p.implicit;
    }
    static void requestFields(std::ostream &out, const Request &r) {
        out << ',' << r.address << ',' << r.data << ',' << r.handle << ',' << r.atomic << ',' << r.op
            << ',' << r.write << ',' << r.size << ',' << r.mask << ',' << r.virt << ',' << r.prechecked
            << ',' << r.epoch << ',' << r.hint << ',' << r.uncached;
    }
    void record(unsigned phase, unsigned index, const Observed &o) {
        if (!trace.is_open()) return;
        const auto &s = lanes[index];
        trace << cycle << ',' << phase << ',' << resetting << ',' << index << ','
            << (s.offer ? int64_t(s.offer->sequence) : -1) << ',' << bool(s.offer) << ',' << o.inputReady
            << ',' << o.outputValid << ',' << s.outputReady << ',' << o.idle;
        packetFields(trace, s.offer ? s.offer->packet : Packet{});
        packetFields(trace, o.output);
        trace << ',' << (s.request ? int64_t(s.request->sequence) : -1) << ',' << bool(s.request)
            << ',' << o.requestReady << ',' << o.forwardValid << ',' << s.forwardReady;
        requestFields(trace, s.request ? s.request->packet : Request{});
        requestFields(trace, o.forward);
        trace << '\n';
    }
    void mutate(unsigned index, Observed &o) {
        if (mutated || negative.empty()) return;
        const auto &s = lanes[index];
        if (negative == "metadata-mismatch" && metadata(index) && o.outputValid) o.output.gpa ^= uint64_t(1) << 61;
        else if (negative == "return-handle-mismatch" && tagged(index) && o.outputValid) o.output.handle ^= 32;
        else if (negative == "occupancy-mismatch" && s.pending.size() == CAPACITY && s.outputReady)
            o.inputReady = !o.inputReady;
        else if (negative == "ordering-mismatch" && s.pending.size() == CAPACITY && o.outputValid)
            o.output.data = s.pending[1].data;
        else return;
        mutated = true;
        std::cerr << "FP_GUEST_RESPONSE_BUFFER_NEGATIVE " << negative << " lane=" << index << " cycle=" << cycle << '\n';
    }
    void verify(unsigned index, const Observed &o, unsigned phase) {
        auto &s = lanes[index]; auto &c = s.counts;
        const auto occupancy = s.pending.size();
        const bool expectedValid = occupancy != 0 || (flow(index) && bool(s.offer));
        check(o.inputReady == (occupancy < CAPACITY), "BUFFER_OCCUPANCY_MISMATCH", index);
        check(o.idle == (occupancy == 0), "BUFFER_IDLE_MISMATCH", index);
        check(o.outputValid == expectedValid, "BUFFER_VALID_MISMATCH", index);
        if (expectedValid) {
            const Packet wanted = occupancy ? s.pending.front() : normalized(s.offer->packet, index);
            check(o.output.data == wanted.data, "BUFFER_ORDERING_MISMATCH", index);
            check(o.output.error == wanted.error && o.output.page == wanted.page, "BUFFER_STATUS_MISMATCH", index);
            check(o.output.handle == wanted.handle, "BUFFER_RETURN_HANDLE_MISMATCH", index);
            check(sameMetadata(o.output, wanted), "BUFFER_METADATA_MISMATCH", index);
        }
        if (s.heldOutput) check(o.outputValid && o.output == *s.heldOutput, "BUFFER_HELD_OUTPUT_MISMATCH", index);
        if (s.heldInput) check(s.offer && s.offer->sequence == s.heldInput->sequence &&
            s.offer->packet == s.heldInput->packet, "DRIVER_HELD_INPUT_MISMATCH", index);
        s.heldOutput = o.outputValid && !s.outputReady ? std::optional<Packet>(o.output) : std::nullopt;
        s.heldInput = s.offer && !o.inputReady ? s.offer : std::nullopt;
        c.heldInput += bool(s.heldInput); c.heldOutput += bool(s.heldOutput);

        // Public request passthrough must not acquire response-storage credits.
        check(o.requestReady == s.forwardReady && o.forwardValid == bool(s.request),
            "BUFFER_REQUEST_HANDSHAKE_MISMATCH", index);
        if (s.request) {
            Request wanted = s.request->packet;
            if (!tagged(index)) wanted.handle = 0;
            check(o.forward == wanted, "BUFFER_REQUEST_PAYLOAD_MISMATCH", index);
        }
        if (s.heldRequest) check(o.forwardValid && o.forward == *s.heldRequest,
            "BUFFER_HELD_REQUEST_MISMATCH", index);
        s.heldRequest = o.forwardValid && !s.forwardReady ? std::optional<Request>(o.forward) : std::nullopt;
        c.heldRequests += bool(s.heldRequest);
        if (s.request && o.requestReady) {
            ++c.requests; c.requestsWhileFull += occupancy == CAPACITY; s.request.reset();
        }

        const bool accepted = s.offer && o.inputReady;
        const bool consumed = o.outputValid && s.outputReady;
        c.full += occupancy == CAPACITY;
        c.fullPop += occupancy == CAPACITY && consumed;
        c.emptyBypass += occupancy == 0 && accepted && consumed;
        c.emptyCapture += occupancy == 0 && accepted && !consumed;
        c.replacement += occupancy == 1 && accepted && consumed;
        c.tailPromotion += occupancy == CAPACITY && consumed;
        c.accepted += accepted; c.consumed += consumed;
        c.continuousAccepted += phase == 7 && accepted;
        c.continuousConsumed += phase == 7 && consumed;
        if (consumed) {
            c.statusMask |= 1U << (unsigned(o.output.error) | (unsigned(o.output.page) << 1));
            c.metadataMask |= 1U << (unsigned(o.output.gpf) | (unsigned(o.output.gva) << 1) |
                (unsigned(o.output.implicit) << 2));
            c.handleMask |= uint64_t(1) << o.output.handle;
            c.highHandle += (o.output.handle & 32) != 0;
            c.highGpa += (o.output.gpa >> 63) != 0;
            if (s.lastConsumed && !sameMetadata(*s.lastConsumed, o.output)) {
                ++c.metadataChanges; c.metadataClears += clearMetadata(o.output);
            }
            s.lastConsumed = o.output;
        }
        // Abstract transaction conservation. An accepted empty bypass is both
        // appended and consumed here; it never leaves a stored owner behind.
        if (accepted) s.pending.push_back(normalized(s.offer->packet, index));
        if (consumed) {
            check(!s.pending.empty(), "BUFFER_CONSUMED_WITHOUT_OWNER", index);
            s.pending.pop_front();
        }
        if (accepted) s.offer.reset();
        check(s.pending.size() <= CAPACITY && c.accepted - c.consumed == s.pending.size(),
            "BUFFER_CONSERVATION_MISMATCH", index);
        c.maximum = std::max(c.maximum, unsigned(s.pending.size()));
    }
    void tick(unsigned phase, bool supplyRequests = true, bool forceRequestReady = false) {
        check(cycle < CYCLE_LIMIT, "BUFFER_CYCLE_BOUND", 0);
        for (unsigned i = 0; i < LANES; ++i) {
            auto &s = lanes[i];
            if (supplyRequests && !s.request) {
                const auto sequence = s.nextRequest++;
                s.request = RequestOffer{sequence, makeRequest(i, sequence)};
            }
            s.forwardReady = forceRequestReady || (cycle + i) % 5 != 0;
            drive(i);
        }
        d.step();
        std::array<Observed, LANES> observed;
        for (unsigned i = 0; i < LANES; ++i) {
            observed[i] = observe(i);
            // Raw DUT observations are recorded before any negative-control mutation.
            record(phase, i, observed[i]);
        }
        for (unsigned i = 0; i < LANES; ++i) {
            mutate(i, observed[i]); verify(i, observed[i], phase);
        }
        ++cycle; resetCycles += resetting;
    }
    void ready(bool value) { for (auto &s : lanes) s.outputReady = value; }
    void offerAll() {
        for (unsigned i = 0; i < LANES; ++i) {
            auto &s = lanes[i];
            if (!s.offer) {
                const auto sequence = s.nextSequence++;
                s.offer = Offer{sequence, makePacket(i, sequence)};
            }
        }
    }
    void drain(unsigned phase, unsigned ticks = 4) {
        ready(true);
        for (unsigned t = 0; t < ticks; ++t) tick(phase, false, true);
        for (unsigned i = 0; i < LANES; ++i)
            check(lanes[i].pending.empty() && !lanes[i].offer && !lanes[i].request,
                "BUFFER_DRAIN_BOUND", i);
    }
    void idleReset(unsigned phase) {
        for (unsigned i = 0; i < LANES; ++i)
            check(lanes[i].pending.empty() && !lanes[i].offer && !lanes[i].request &&
                !lanes[i].heldInput && !lanes[i].heldOutput && !lanes[i].heldRequest,
                "DRIVER_RESET_WITH_OWNER", i);
        ready(true); resetting = true; d.set_reset(1);
        tick(phase, false, true); d.resetAll();
        tick(phase, false, true); d.resetAll();
        d.activateAll(); d.set_reset(0); resetting = false;
        ++idleResets; tick(phase, false, true);
    }
    void summarize() {
        for (unsigned i = 0; i < LANES; ++i) {
            const auto &c = lanes[i].counts;
            check(c.accepted == c.consumed && c.accepted > 300 && c.maximum == CAPACITY,
                "BUFFER_COVERAGE_CONSERVATION", i);
            check(c.heldInput && c.heldOutput && c.fullPop && c.emptyCapture && c.replacement && c.tailPromotion,
                "BUFFER_COVERAGE_OWNERSHIP", i);
            check(c.requests && c.heldRequests && c.requestsWhileFull, "BUFFER_COVERAGE_PASSTHROUGH", i);
            check(c.continuousAccepted == 128 && c.continuousConsumed == (flow(i) ? 128 : 127),
                "BUFFER_CONTINUOUS_II_MISMATCH", i);
            check((flow(i) ? c.emptyBypass > 0 : c.emptyBypass == 0) && c.statusMask == 15,
                "BUFFER_COVERAGE_MODE", i);
            if (metadata(i)) check(c.metadataChanges && c.metadataClears && c.highGpa && c.metadataMask == 255,
                "BUFFER_COVERAGE_METADATA", i);
            else check(!c.metadataChanges && !c.metadataClears && !c.highGpa && c.metadataMask == 1,
                "BUFFER_DISABLED_METADATA_MISMATCH", i);
            if (tagged(i)) check(c.highHandle && c.handleMask == ~uint64_t(0), "BUFFER_COVERAGE_FULL_HANDLE", i);
            else check(!c.highHandle && c.handleMask == 1, "BUFFER_UNTAGGED_HANDLE_MISMATCH", i);
        }
        check(negative.empty(), "BUFFER_NEGATIVE_DID_NOT_FAIL", 0);
        if (trace.is_open()) {
            trace.flush(); check(bool(trace), "BUFFER_TRACE_WRITE_FAILED", 0);
            traceBytes = uint64_t(trace.tellp());
            check(traceBytes < TRACE_LIMIT, "BUFFER_TRACE_SIZE_BOUND", 0);
            trace.close();
        }
        check(cycle == 732 && idleResets == 2 && resetCycles == 4, "BUFFER_SCHEDULE_COUNT", 0);
        std::cout << "FP_GUEST_RESPONSE_BUFFER_PASS {\"component_only\":true,\"guest_fd_execution\":false,"
            << "\"configs\":16,\"capacity\":2,\"cycles\":" << cycle << ",\"cycle_limit\":" << CYCLE_LIMIT
            << ",\"idle_resets\":" << idleResets << ",\"reset_cycles\":" << resetCycles
            << ",\"trace_rows\":" << (traceBytes ? cycle * LANES : 0) << ",\"trace_bytes\":" << traceBytes
            << ",\"lanes\":[";
        for (unsigned i = 0; i < LANES; ++i) {
            const auto &c = lanes[i].counts;
            if (i) std::cout << ',';
            std::cout << "{\"lane\":" << i << ",\"mode\":\"" << MODES[i / 4] << "\",\"metadata\":"
                << (metadata(i) ? "true" : "false") << ",\"tagged\":" << (tagged(i) ? "true" : "false");
#define COUNT(NAME, FIELD) std::cout << ",\"" NAME "\":" << c.FIELD
            COUNT("accepted", accepted); COUNT("consumed", consumed); COUNT("max_occupancy", maximum);
            COUNT("held_inputs", heldInput); COUNT("held_outputs", heldOutput); COUNT("full_cycles", full);
            COUNT("full_pop_no_credit", fullPop); COUNT("empty_bypass", emptyBypass); COUNT("empty_capture", emptyCapture);
            COUNT("head_replacement", replacement); COUNT("tail_promotion", tailPromotion);
            COUNT("request_transfers", requests); COUNT("request_holds", heldRequests); COUNT("requests_while_full", requestsWhileFull);
            COUNT("metadata_changes", metadataChanges); COUNT("metadata_clears", metadataClears);
            COUNT("high_gpa", highGpa); COUNT("high_handle", highHandle); COUNT("handle_mask", handleMask);
            COUNT("status_mask", statusMask); COUNT("metadata_mask", metadataMask);
            COUNT("continuous_accepted", continuousAccepted); COUNT("continuous_consumed", continuousConsumed);
#undef COUNT
            std::cout << '}';
        }
        std::cout << "]}\n";
    }

public:
    Bench(const std::string &tracePath, std::string negativeMode)
        : d(*::new (static_cast<void *>(storage)) SFpGuestResponseBufferGsim), negative(std::move(negativeMode)) {
        static_assert(std::is_trivially_copyable_v<SFpGuestResponseBufferGsim>);
        d.LOG_START = 1; d.activateAll();
        if (!tracePath.empty()) {
            trace.open(tracePath);
            check(bool(trace), "BUFFER_TRACE_OPEN_FAILED", 0);
            trace << "cycle,phase,reset,lane,input_seq,input_valid,input_ready,output_valid,output_ready,idle"
                << ",input_data,input_error,input_page,input_handle,input_gpf,input_gva,input_gpa,input_implicit"
                << ",output_data,output_error,output_page,output_handle,output_gpf,output_gva,output_gpa,output_implicit"
                << ",request_seq,request_valid,request_ready,forward_valid,forward_ready"
                << ",request_address,request_data,request_handle,request_atomic,request_op,request_write,request_size"
                << ",request_mask,request_virtualized,request_prechecked,request_epoch,request_hint,request_uncached"
                << ",forward_address,forward_data,forward_handle,forward_atomic,forward_op,forward_write,forward_size"
                << ",forward_mask,forward_virtualized,forward_prechecked,forward_epoch,forward_hint,forward_uncached\n";
        }
    }
    void run() {
        idleReset(0);
        // Empty readiness and unrelated request passthrough.
        for (unsigned t = 0; t < 6; ++t) { ready(t % 2); tick(1); }
        ready(true); offerAll(); tick(2); drain(2);
        // Capture an empty held offer, preserve it, fill the tail, and hold a
        // third input. The first full-queue pop cannot borrow enqueue credit.
        ready(false); offerAll(); tick(3);
        for (unsigned t = 0; t < 3; ++t) tick(3);
        offerAll(); tick(4);
        offerAll(); tick(4); tick(4);
        ready(true);
        for (unsigned t = 0; t < 4; ++t) tick(4);
        // Occupancy-one simultaneous replacement must preserve whole packets.
        ready(false); offerAll(); tick(5); ready(true);
        for (unsigned t = 0; t < 24; ++t) { offerAll(); tick(5); }
        drain(5);
        // Adjacent all-ones, zero, and distinct metadata, including high GPA bits.
        for (unsigned t = 0; t < 16; ++t) { offerAll(); tick(6); }
        drain(6);
        for (unsigned t = 0; t < 128; ++t) { offerAll(); tick(7); }
        // Separate the ROI from its drain so the one-cycle registered latency
        // remains visible instead of being hidden in an aggregate count.
        drain(10);
        // Bounded deterministic, lane-skewed congestion. Offers remain stable
        // until accepted; no reset, cancellation, or artificial flush is used.
        for (unsigned t = 0; t < 512; ++t) {
            for (unsigned i = 0; i < LANES; ++i) {
                auto &s = lanes[i];
                s.outputReady = (t + 3 * i) % 17 >= 5;
                if (!s.offer && (t + i) % 7 != 0) {
                    const auto sequence = s.nextSequence++;
                    s.offer = Offer{sequence, makePacket(i, sequence)};
                }
            }
            tick(8);
        }
        drain(8, 8);
        idleReset(9);
        for (unsigned t = 0; t < 3; ++t) tick(9, false, true);
        summarize();
    }
};
} // namespace

int main(int argc, char **argv) {
    try {
        std::string trace, negative;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--trace" && i + 1 < argc) trace = argv[++i];
            else if (arg == "--negative" && i + 1 < argc) negative = argv[++i];
            else throw std::runtime_error("BUFFER_ARGUMENT_ERROR");
        }
        if (!negative.empty() && negative != "metadata-mismatch" && negative != "return-handle-mismatch" &&
            negative != "occupancy-mismatch" && negative != "ordering-mismatch")
            throw std::runtime_error("BUFFER_UNKNOWN_NEGATIVE");
        Bench bench(trace, negative); bench.run();
    } catch (const std::exception &error) {
        std::cerr << "FP_GUEST_RESPONSE_BUFFER_FAIL " << error.what() << '\n';
        return 1;
    }
    return 0;
}
