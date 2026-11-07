#include "MemoryDomainSelectorGsim.h"
#include <array>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <new>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

// Independent accepted-event ledger, not an MSU/ROB/LSU or guest-trap model.
// H encodings below are assembled from H 1.0 instruction fields, never imported
// from DUT definitions. Synthetic native packets exercise transport fields.
// Successful lifetimes only: exceptional release, simultaneous capture/release
// priority and inactive-token retirement matches are source-equivalence scope,
// not dynamic coverage. Reset is exercised only before any accepted owner.
namespace {
constexpr unsigned LANES = 2, DOMAINS = 3, CASES = 64, CYCLE_LIMIT = 4096;
constexpr uint64_t TRACE_LIMIT = 12 * 1024 * 1024;
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
struct Request {
    uint64_t address = 0, data = 0;
    uint32_t epoch = 0;
    unsigned handle = 0, size = 0, mask = 0, op = 0;
    bool write = false, atomic = false, virt = false, prechecked = false, hint = false, uncached = false;
    bool operator==(const Request &) const = default;
};
struct Reply {
    uint64_t data = 0, gpa = 0;
    unsigned handle = 0;
    bool error = false, page = false, gpf = false, gva = false, implicit = false;
    bool operator==(const Reply &) const = default;
};
struct Instruction { uint32_t word; bool hLoad, hStore, fpMemory, arithmetic; };
uint32_t hlv(unsigned size, unsigned variant) {
    return 0x60004073U | (size << 26) | (variant << 20) | (9U << 15) | (7U << 7);
}
uint32_t hsv(unsigned size) { return 0x62004073U | (size << 26) | (11U << 20) | (9U << 15); }
std::vector<Instruction> instructions() {
    std::vector<Instruction> v;
    for (unsigned size = 0; size != 4; ++size) {
        v.push_back({hlv(size, 0), true, false, false, false});
        if (size != 3) v.push_back({hlv(size, 1), true, false, false, false});
    }
    v.push_back({hlv(1, 3), true, false, false, false});
    v.push_back({hlv(2, 3), true, false, false, false});
    for (unsigned size = 0; size != 4; ++size) v.push_back({hsv(size), false, true, false, false});
    // Reserved near misses and HFENCE are classifier probes only, not executed traps.
    for (auto word : {hlv(3, 1), hlv(3, 3), hlv(0, 3), hlv(2, 2), hsv(2) | (1U << 7),
                      0x22000073U, 0x62000073U, 0x00000013U})
        v.push_back({word, false, false, false, false});
    v.push_back({0x0004a387U, false, false, true, false}); // FLW f7,0(x9)
    v.push_back({0x0004b387U, false, false, true, false}); // FLD f7,0(x9)
    v.push_back({0x00b4a027U, false, false, true, false}); // FSW f11,0(x9)
    v.push_back({0x00b4b027U, false, false, true, false}); // FSD f11,0(x9)
    v.push_back({0x02b483d3U, false, false, false, true}); // FADD.D f7,f9,f11,RNE
    return v;
}
struct Case { unsigned domain; bool protectedOwner; Instruction instruction; Token token; Request request; Reply reply; };
Case makeCase(unsigned lane, unsigned sequence, const std::vector<Instruction> &ops) {
    constexpr std::array<unsigned, 8> guestOrder{0, 1, 2, 0, 2, 1, 0, 0};
    Case c{};
    c.domain = lane ? sequence % 2 * 2 : guestOrder[sequence % 8];
    c.protectedOwner = c.domain != 0 || (!lane && sequence % 8 == 7);
    if (c.domain == 1) c.instruction = ops[((sequence / 8) * 2 + (sequence % 8 == 5)) % 13];
    else if (c.domain == 2) {
        const unsigned ordinal = lane ? sequence / 2 : (sequence / 8) * 2 + (sequence % 8 == 4);
        c.instruction = ops[21 + ordinal % 4];
    } else c.instruction = c.protectedOwner ? ops[25] : ops[20];
    c.token = {sequence % 16, UINT64_C(0xfedc012300000001) ^ (uint64_t(lane) << 40) ^ (uint64_t(sequence) << 32)};
    auto &r = c.request;
    r.address = UINT64_C(0xfe01234580000000) ^ (uint64_t(lane) << 24) ^ (sequence * 8);
    r.data = UINT64_C(0x8011223344556677) ^ (sequence * UINT64_C(0x0102040810204081));
    r.epoch = UINT32_C(0xfedcba00) ^ sequence;
    r.handle = lane && c.domain == 0 ? (sequence / 2) % 16 : 0;
    r.size = sequence & 3; r.mask = (sequence * 37 + 1) & 255; r.op = sequence & 31;
    r.write = sequence & 1; r.atomic = sequence & 2; r.virt = sequence & 4;
    r.prechecked = sequence & 8; r.hint = sequence & 16; r.uncached = sequence & 32;
    auto &p = c.reply;
    p.data = UINT64_C(0xa587654321fedc09) ^ r.data;
    p.handle = lane ? (c.domain == 2 ? 16 : r.handle) : 0;
    p.error = sequence & 1; p.page = sequence & 2;
    // All 8 metadata combinations, high GPA, and explicit clear transitions.
    p.gpf = sequence & 1; p.gva = sequence & 2; p.implicit = sequence & 4;
    p.gpa = sequence % 8 ? (UINT64_C(0x8000000012345678) ^ (uint64_t(sequence) << 53)) : 0;
    return c;
}
struct Input {
    bool start = false, complete = false;
    Instruction instruction{0x13, false, false, false, false};
    Token startToken, completeToken;
    std::array<bool, 2> commit{};
    std::array<Token, 2> commitToken{};
    std::array<bool, DOMAINS> requestValid{}, responseReady{true, true, true};
    std::array<Request, DOMAINS> request{};
    bool nativeRequestReady = true, nativeResponseValid = false;
    Reply nativeResponse;
    std::array<bool, 5> busy{}; // integer, H, FP-memory, posted, prefetch
    bool architecturalFpBusy = false;
};
struct Output {
    bool active = false, contextEpoch = false, hEpoch = false, fpEpoch = false, retired = false;
    Token token;
    unsigned domain = 0, matches = 0;
    bool busy = false, cpuBusy = false, architectureOnly = false;
    bool hLoad = false, hStore = false, hMemory = false, fpMemory = false;
    std::array<bool, DOMAINS> requestReady{}, responseValid{};
    std::array<Reply, DOMAINS> response{};
    bool nativeRequestValid = false, nativeResponseReady = false;
    Request nativeRequest;
};
struct Counts {
    std::array<unsigned, DOMAINS> requests{}, responses{};
    unsigned starts = 0, completions = 0, retirements = 0;
    unsigned requestStalls = 0, responseStalls = 0, responseDelay = 0;
    unsigned postResponseHolds = 0, wrongTag = 0, wrongIndex = 0, arithmeticOverlap = 0;
    unsigned busyMasks = 0, metadataMask = 0, statusMask = 0, hForms = 0;
    unsigned sustainedRequests = 0, sustainedTurnovers = 0;
    uint64_t handles = 0;
};
struct Ledger {
    bool active = false, completed = false, responded = false;
    Token token;
    unsigned domain = 0;
    bool context = false;
    std::optional<unsigned> pending;
    unsigned pendingHandle = 0;
    std::optional<Request> heldRequest;
    std::optional<Reply> heldResponse;
    Counts counts;
};
bool sameMetadata(const Reply &a, const Reply &b) {
    return a.gpa == b.gpa && a.gpf == b.gpf && a.gva == b.gva && a.implicit == b.implicit;
}

class Bench {
    alignas(SMemoryDomainSelectorGsim) std::byte storage[sizeof(SMemoryDomainSelectorGsim)]{};
    SMemoryDomainSelectorGsim &d;
    const std::vector<Instruction> ops = instructions();
    std::array<Ledger, LANES> ledger;
    std::ofstream trace;
    std::string schedule, negative;
    bool mutated = false, resetting = false, streaming = false, matrix = false;
    unsigned cycle = 0, idleResets = 0;
    void check(bool yes, const std::string &name, unsigned lane) const {
        if (!yes) throw std::runtime_error("MEMORY_DOMAIN_SELECTOR_CHECK[" + name + "]: lane=" +
            std::to_string(lane) + " cycle=" + std::to_string(cycle));
    }
    void drive(unsigned lane, const Input &i) {
        switch (lane) {
#define CLIENT_DRIVE(L, P, N) \
        d.set_io$$##L##$$##P##$$request$$valid(i.requestValid[N]); \
        d.set_io$$##L##$$##P##$$request$$bits$$address(i.request[N].address); \
        d.set_io$$##L##$$##P##$$request$$bits$$data(i.request[N].data); \
        d.set_io$$##L##$$##P##$$request$$bits$$translationEpoch(i.request[N].epoch); \
        d.set_io$$##L##$$##P##$$request$$bits$$returnHandle(i.request[N].handle); \
        d.set_io$$##L##$$##P##$$request$$bits$$size(i.request[N].size); \
        d.set_io$$##L##$$##P##$$request$$bits$$mask(i.request[N].mask); \
        d.set_io$$##L##$$##P##$$request$$bits$$atomicOp(i.request[N].op); \
        d.set_io$$##L##$$##P##$$request$$bits$$write(i.request[N].write); \
        d.set_io$$##L##$$##P##$$request$$bits$$atomic(i.request[N].atomic); \
        d.set_io$$##L##$$##P##$$request$$bits$$virtualized(i.request[N].virt); \
        d.set_io$$##L##$$##P##$$request$$bits$$precheckedLoad(i.request[N].prechecked); \
        d.set_io$$##L##$$##P##$$request$$bits$$prefetchNextAllowed(i.request[N].hint); \
        d.set_io$$##L##$$##P##$$request$$bits$$uncached(i.request[N].uncached); \
        d.set_io$$##L##$$##P##$$response$$ready(i.responseReady[N]);
#define DRIVE(L, N) case N: \
        d.set_io$$##L##$$acceptedStart$$valid(i.start); \
        d.set_io$$##L##$$acceptedStart$$bits$$instruction(i.instruction.word); \
        d.set_io$$##L##$$acceptedStart$$bits$$token$$index(i.startToken.index); \
        d.set_io$$##L##$$acceptedStart$$bits$$token$$tag(i.startToken.tag); \
        d.set_io$$##L##$$acceptedComplete$$valid(i.complete); \
        d.set_io$$##L##$$acceptedComplete$$bits$$index(i.completeToken.index); \
        d.set_io$$##L##$$acceptedComplete$$bits$$tag(i.completeToken.tag); \
        d.set_io$$##L##$$commit0$$valid(i.commit[0]); \
        d.set_io$$##L##$$commit0$$bits$$index(i.commitToken[0].index); \
        d.set_io$$##L##$$commit0$$bits$$tag(i.commitToken[0].tag); \
        d.set_io$$##L##$$commit1$$valid(i.commit[1]); \
        d.set_io$$##L##$$commit1$$bits$$index(i.commitToken[1].index); \
        d.set_io$$##L##$$commit1$$bits$$tag(i.commitToken[1].tag); \
        CLIENT_DRIVE(L, integer, 0) CLIENT_DRIVE(L, h, 1) CLIENT_DRIVE(L, fp, 2) \
        d.set_io$$##L##$$memory$$request$$ready(i.nativeRequestReady); \
        d.set_io$$##L##$$memory$$response$$valid(i.nativeResponseValid); \
        d.set_io$$##L##$$memory$$response$$bits$$data(i.nativeResponse.data); \
        d.set_io$$##L##$$memory$$response$$bits$$returnHandle(i.nativeResponse.handle); \
        d.set_io$$##L##$$memory$$response$$bits$$error(i.nativeResponse.error); \
        d.set_io$$##L##$$memory$$response$$bits$$pageFault(i.nativeResponse.page); \
        d.set_io$$##L##$$guestFault$$guestPageFault(i.nativeResponse.gpf); \
        d.set_io$$##L##$$guestFault$$guestAddress(i.nativeResponse.gva); \
        d.set_io$$##L##$$guestFault$$guestPhysicalAddress(i.nativeResponse.gpa); \
        d.set_io$$##L##$$guestFault$$implicitPte(i.nativeResponse.implicit); \
        d.set_io$$##L##$$integerBusy(i.busy[0]); d.set_io$$##L##$$hBusy(i.busy[1]); \
        d.set_io$$##L##$$fpMemoryBusy(i.busy[2]); d.set_io$$##L##$$postedBusy(i.busy[3]); \
        d.set_io$$##L##$$prefetchBusy(i.busy[4]); \
        d.set_io$$##L##$$architecturalFpBusy(i.architecturalFpBusy); break;
            DRIVE(guest, 0) DRIVE(host, 1)
#undef DRIVE
#undef CLIENT_DRIVE
        }
    }
    Output observe(unsigned lane) const {
        Output o;
        switch (lane) {
#define CLIENT_READ(L, P, F, N) \
        o.requestReady[N] = d.get_io$$##L##$$##P##$$request$$ready(); \
        o.responseValid[N] = d.get_io$$##L##$$##P##$$response$$valid(); \
        o.response[N].data = d.get_io$$##L##$$##P##$$response$$bits$$data(); \
        o.response[N].handle = d.get_io$$##L##$$##P##$$response$$bits$$returnHandle(); \
        o.response[N].error = d.get_io$$##L##$$##P##$$response$$bits$$error(); \
        o.response[N].page = d.get_io$$##L##$$##P##$$response$$bits$$pageFault(); \
        o.response[N].gpf = d.get_io$$##L##$$##F##$$guestPageFault(); \
        o.response[N].gva = d.get_io$$##L##$$##F##$$guestAddress(); \
        o.response[N].gpa = d.get_io$$##L##$$##F##$$guestPhysicalAddress(); \
        o.response[N].implicit = d.get_io$$##L##$$##F##$$implicitPte();
#define READ(L, N) case N: \
        o.active = d.get_io$$##L##$$ownerActive(); \
        o.token.index = d.get_io$$##L##$$ownerToken$$index(); o.token.tag = d.get_io$$##L##$$ownerToken$$tag(); \
        o.contextEpoch = d.get_io$$##L##$$contextMemoryEpoch(); \
        o.hEpoch = d.get_io$$##L##$$hMemoryEpoch(); o.fpEpoch = d.get_io$$##L##$$fpMemoryEpoch(); \
        o.domain = d.get_io$$##L##$$domain(); o.retired = d.get_io$$##L##$$retired(); \
        o.matches = d.get_io$$##L##$$retireMatches(); \
        o.busy = d.get_io$$##L##$$busy(); o.cpuBusy = d.get_io$$##L##$$cpuBusy(); \
        o.architectureOnly = d.get_io$$##L##$$architectureOnly(); \
        o.hLoad = d.get_io$$##L##$$decodedHLoad(); o.hStore = d.get_io$$##L##$$decodedHStore(); \
        o.hMemory = d.get_io$$##L##$$decodedHMemory(); o.fpMemory = d.get_io$$##L##$$decodedFpMemory(); \
        CLIENT_READ(L, integer, integerFault, 0) CLIENT_READ(L, h, hFault, 1) CLIENT_READ(L, fp, fpFault, 2) \
        o.nativeRequestValid = d.get_io$$##L##$$memory$$request$$valid(); \
        o.nativeResponseReady = d.get_io$$##L##$$memory$$response$$ready(); \
        o.nativeRequest.address = d.get_io$$##L##$$memory$$request$$bits$$address(); \
        o.nativeRequest.data = d.get_io$$##L##$$memory$$request$$bits$$data(); \
        o.nativeRequest.epoch = d.get_io$$##L##$$memory$$request$$bits$$translationEpoch(); \
        o.nativeRequest.handle = d.get_io$$##L##$$memory$$request$$bits$$returnHandle(); \
        o.nativeRequest.size = d.get_io$$##L##$$memory$$request$$bits$$size(); \
        o.nativeRequest.mask = d.get_io$$##L##$$memory$$request$$bits$$mask(); \
        o.nativeRequest.op = d.get_io$$##L##$$memory$$request$$bits$$atomicOp(); \
        o.nativeRequest.write = d.get_io$$##L##$$memory$$request$$bits$$write(); \
        o.nativeRequest.atomic = d.get_io$$##L##$$memory$$request$$bits$$atomic(); \
        o.nativeRequest.virt = d.get_io$$##L##$$memory$$request$$bits$$virtualized(); \
        o.nativeRequest.prechecked = d.get_io$$##L##$$memory$$request$$bits$$precheckedLoad(); \
        o.nativeRequest.hint = d.get_io$$##L##$$memory$$request$$bits$$prefetchNextAllowed(); \
        o.nativeRequest.uncached = d.get_io$$##L##$$memory$$request$$bits$$uncached(); break;
            READ(guest, 0) READ(host, 1)
#undef READ
#undef CLIENT_READ
        }
        return o;
    }
    static void tokenJson(std::ostream &s, const Token &t) { s << t.index << ',' << t.tag; }
    static void requestJson(std::ostream &s, const Request &r) {
        s << '[' << r.address << ',' << r.data << ',' << r.epoch << ',' << r.handle << ',' << r.size << ','
          << r.mask << ',' << r.op << ',' << r.write << ',' << r.atomic << ',' << r.virt << ','
          << r.prechecked << ',' << r.hint << ',' << r.uncached << ']';
    }
    static void replyJson(std::ostream &s, const Reply &r) {
        s << '[' << r.data << ',' << r.gpa << ',' << r.handle << ',' << r.error << ',' << r.page << ','
          << r.gpf << ',' << r.gva << ',' << r.implicit << ']';
    }
    template <class T, size_t N> static void arrayJson(std::ostream &s, const std::array<T, N> &a) {
        s << '[';
        for (size_t n = 0; n < N; ++n) s << (n ? "," : "") << a[n];
        s << ']';
    }
    static void inputJson(std::ostream &s, const Input &i) {
        s << "{\"start\":[" << i.start << ','; tokenJson(s, i.startToken);
        s << ',' << i.instruction.word << "],\"complete\":[" << i.complete << ',';
        tokenJson(s, i.completeToken); s << "],\"commits\":[";
        for (unsigned n = 0; n < 2; ++n) {
            s << (n ? ",[" : "[") << i.commit[n] << ','; tokenJson(s, i.commitToken[n]); s << ']';
        }
        s << "],\"request_valid\":"; arrayJson(s, i.requestValid);
        s << ",\"request\":[";
        for (unsigned n = 0; n < DOMAINS; ++n) { if (n) s << ','; requestJson(s, i.request[n]); }
        s << "],\"response_ready\":"; arrayJson(s, i.responseReady);
        s << ",\"native_request_ready\":" << i.nativeRequestReady
          << ",\"native_response_valid\":" << i.nativeResponseValid << ",\"native_response\":";
        replyJson(s, i.nativeResponse); s << ",\"busy\":"; arrayJson(s, i.busy);
        s << ",\"architectural_fp_busy\":" << i.architecturalFpBusy << '}';
    }
    static void outputJson(std::ostream &s, const Output &o) {
        s << "{\"owner\":[" << o.active << ','; tokenJson(s, o.token);
        s << ',' << o.contextEpoch << ',' << o.hEpoch << ',' << o.fpEpoch
          << "],\"domain\":" << o.domain << ",\"retired\":" << o.retired
          << ",\"retire_matches\":" << o.matches << ",\"busy\":" << o.busy
          << ",\"cpu_busy\":" << o.cpuBusy << ",\"architecture_only\":" << o.architectureOnly
          << ",\"decode\":[" << o.hLoad << ',' << o.hStore << ',' << o.hMemory << ',' << o.fpMemory
          << "],\"request_ready\":"; arrayJson(s, o.requestReady);
        s << ",\"response_valid\":"; arrayJson(s, o.responseValid);
        s << ",\"response\":[";
        for (unsigned n = 0; n < DOMAINS; ++n) { if (n) s << ','; replyJson(s, o.response[n]); }
        s << "],\"native_request_valid\":" << o.nativeRequestValid
          << ",\"native_response_ready\":" << o.nativeResponseReady << ",\"native_request\":";
        requestJson(s, o.nativeRequest); s << '}';
    }
    void traceRow(const std::array<Input, LANES> &in, const std::array<Output, LANES> &out) {
        if (!trace.is_open()) return;
        trace << "{\"event\":\"cycle\",\"cycle\":" << cycle << ",\"reset\":" << resetting << ",\"lanes\":[";
        for (unsigned lane = 0; lane < LANES; ++lane) {
            trace << (lane ? ",{\"input\":" : "{\"input\":"); inputJson(trace, in[lane]);
            trace << ",\"output\":"; outputJson(trace, out[lane]); trace << '}';
        }
        trace << "]}\n";
        check(bool(trace) && trace.tellp() >= 0 && uint64_t(trace.tellp()) <= TRACE_LIMIT, "trace_bound", 0);
    }
    void corrupt(unsigned lane, const Input &i, Output &o) {
        if (mutated || negative.empty()) return;
        const unsigned selected = ledger[lane].domain;
        bool ready = false;
        if (negative == "classification" && lane == 0 && cycle == 3) { o.hLoad = !o.hLoad; ready = true; }
        if (negative == "busy" && lane == 0 && cycle == 3) { o.busy = !o.busy; ready = true; }
        if (matrix && lane == 0 && negative == "owner" && ledger[lane].active) {
            o.active = !o.active; ready = true;
        }
        if (matrix && i.requestValid[selected]) {
            if (lane == 0 && negative == "request_payload") { o.nativeRequest.address ^= 8; ready = true; }
            if (lane == 0 && negative == "request_exclusion") {
                o.requestReady[(selected + 1) % DOMAINS] = true; ready = true;
            }
            if (lane == 1 && negative == "handle") { o.nativeRequest.handle ^= 1; ready = true; }
            if (lane == 0 && negative == "stall" && ledger[lane].heldRequest) {
                o.nativeRequest.data ^= 1; ready = true;
            }
        }
        if (matrix && lane == 0 && i.nativeResponseValid) {
            if (negative == "response_payload") { o.response[selected].data ^= 1; ready = true; }
            if (negative == "response_exclusion") {
                o.responseValid[(selected + 1) % DOMAINS] = true; ready = true;
            }
            if (negative == "metadata") { o.response[selected].gpa ^= 1; ready = true; }
        }
        if (matrix && lane == 0 && negative == "retirement" && ledger[lane].active &&
            i.commit[0] && !(i.commitToken[0] == ledger[lane].token)) {
            o.retired = true; ready = true;
        }
        mutated = ready;
    }
    void inspect(unsigned lane, const Input &i, const Output &o) {
        auto &l = ledger[lane];
        auto &c = l.counts;
        const unsigned selected = l.active ? l.domain : 0;
        check(o.active == l.active && o.token == l.token && o.domain == selected &&
            o.contextEpoch == (l.active && l.context) && o.hEpoch == (l.active && selected == 1) &&
            o.fpEpoch == (l.active && selected == 2), "owner", lane);
        check(o.hLoad == i.instruction.hLoad && o.hStore == i.instruction.hStore &&
            o.hMemory == (i.instruction.hLoad || i.instruction.hStore) &&
            o.fpMemory == i.instruction.fpMemory, "classification", lane);
        unsigned matches = 0;
        for (unsigned n = 0; n < 2; ++n)
            if (i.commit[n] && i.commitToken[n] == l.token) matches |= 1U << n;
        check(o.matches == matches && o.retired == bool(matches), "retirement", lane);
        const bool cpuBusy = i.busy[0] || i.busy[1] || i.busy[2] || i.busy[3];
        const bool busy = cpuBusy || i.busy[4];
        check(o.cpuBusy == cpuBusy && o.busy == busy &&
            o.architectureOnly == (i.architecturalFpBusy && !busy), "busy", lane);
        unsigned busyMask = 0;
        for (unsigned n = 0; n < 5; ++n) busyMask |= unsigned(i.busy[n]) << n;
        c.busyMasks |= uint32_t{1} << busyMask;
        check(!(selected != 0 && i.busy[0]), "stimulus", lane);

        // Continuity is checked before field equality so the stall corruption
        // has its own precise diagnostic, without changing any driven value.
        if (l.heldRequest)
            check(o.nativeRequestValid && o.nativeRequest == *l.heldRequest, "stall", lane);
        if (l.heldResponse)
            check(o.responseValid[selected] && o.response[selected] == *l.heldResponse, "stall", lane);
        for (unsigned n = 0; n < DOMAINS; ++n) {
            check(o.requestReady[n] == (n == selected && i.nativeRequestReady), "request_exclusion", lane);
            check(o.responseValid[n] == (n == selected && i.nativeResponseValid), "response_exclusion", lane);
        }
        check(o.nativeRequestValid == i.requestValid[selected], "request_payload", lane);
        check(o.nativeResponseReady == i.responseReady[selected], "response_exclusion", lane);
        Request expected = i.request[selected];
        expected.handle = lane ? (selected == 2 ? 16 : expected.handle) : 0;
        Request payload = o.nativeRequest;
        const unsigned handle = payload.handle;
        payload.handle = expected.handle;
        check(payload == expected, "request_payload", lane);
        check(handle == expected.handle, "handle", lane);
        const Reply &response = o.response[selected];
        check(response.data == i.nativeResponse.data && response.error == i.nativeResponse.error &&
            response.page == i.nativeResponse.page, "response_payload", lane);
        check(response.handle == (lane && selected == 0 ? i.nativeResponse.handle : 0), "handle", lane);
        Reply metadata = lane ? Reply{} : i.nativeResponse;
        check(sameMetadata(response, metadata), "metadata", lane);

        const bool requestFire = o.nativeRequestValid && i.nativeRequestReady;
        const bool responseFire = i.nativeResponseValid && o.nativeResponseReady;
        if (i.nativeResponseValid) {
            check(l.pending && *l.pending == selected, "credits", lane);
            check(i.nativeResponse.handle == l.pendingHandle, "handle", lane);
        }
        if (requestFire) check(!l.pending || responseFire, "credits", lane);
        if (l.pending && !i.nativeResponseValid) ++c.responseDelay;
        if (o.nativeRequestValid && !i.nativeRequestReady) ++c.requestStalls;
        if (i.nativeResponseValid && !o.nativeResponseReady) ++c.responseStalls;
        l.heldRequest = o.nativeRequestValid && !i.nativeRequestReady ?
            std::optional<Request>(o.nativeRequest) : std::nullopt;
        l.heldResponse = i.nativeResponseValid && !o.nativeResponseReady ?
            std::optional<Reply>(response) : std::nullopt;
        if (l.active && l.responded && !matches) ++c.postResponseHolds;
        if (responseFire) {
            ++c.responses[selected];
            c.metadataMask |= 1U << (unsigned(response.gpf) | (unsigned(response.gva) << 1) |
                (unsigned(response.implicit) << 2));
            c.statusMask |= 1U << (unsigned(response.error) | (unsigned(response.page) << 1));
            l.pending.reset();
            if (l.active) l.responded = true;
        }
        // Native-slot consume/reaccept on one edge is used only by the idle
        // integer stream. It does not grant protected-owner replacement.
        if (requestFire) {
            ++c.requests[selected];
            c.handles |= UINT64_C(1) << o.nativeRequest.handle;
            if (streaming) { ++c.sustainedRequests; c.sustainedTurnovers += responseFire; }
            if (l.active && !l.context && selected == 0) ++c.arithmeticOverlap;
            l.pending = selected;
            l.pendingHandle = o.nativeRequest.handle;
        }
        if (i.complete) {
            check(l.active && i.completeToken == l.token && l.responded && !l.pending && !l.completed,
                "completion", lane);
            l.completed = true;
            ++c.completions;
        }
        for (unsigned n = 0; n < 2; ++n) if (i.commit[n] && l.active && !(i.commitToken[n] == l.token)) {
            if (i.commitToken[n].index == l.token.index) ++c.wrongTag;
            else if (i.commitToken[n].tag == l.token.tag) ++c.wrongIndex;
        }
        if (matches) {
            check(l.active && l.completed && l.responded && !l.pending && !l.heldRequest && !l.heldResponse,
                "retirement", lane);
            l.active = false; l.domain = 0;
            ++c.retirements;
        }
        if (i.start) {
            check(!l.active && !l.pending && !requestFire && !responseFire && !busy && !matches,
                "start", lane);
            l.active = true; l.completed = false; l.responded = false; l.token = i.startToken;
            l.domain = !lane && (i.instruction.hLoad || i.instruction.hStore) ? 1 :
                i.instruction.fpMemory ? 2 : 0;
            l.context = !i.instruction.arithmetic;
            ++c.starts;
            if (l.domain == 1) for (unsigned n = 0; n < 13; ++n)
                if (i.instruction.word == ops[n].word) c.hForms |= 1U << n;
        }
    }
    void tick(const std::array<Input, LANES> &in) {
        check(++cycle <= CYCLE_LIMIT, "cycle_bound", 0);
        for (unsigned lane = 0; lane < LANES; ++lane) drive(lane, in[lane]);
        d.set_reset(resetting);
        d.step();
        // GSIM exposes this edge's combinational outputs, before its sequential
        // update. Persist unmodified observations, then check and advance ledger.
        std::array<Output, LANES> out{observe(0), observe(1)};
        traceRow(in, out);
        if (resetting) return;
        for (unsigned lane = 0; lane < LANES; ++lane) {
            corrupt(lane, in[lane], out[lane]);
            inspect(lane, in[lane], out[lane]);
        }
    }
    std::array<Input, LANES> caseInputs(unsigned sequence) const {
        std::array<Input, LANES> in;
        for (unsigned lane = 0; lane < LANES; ++lane) {
            const Case c = makeCase(lane, sequence, ops);
            auto &i = in[lane];
            // Nonaccepted instruction bits are unrelated probes. Ownership
            // must follow the captured start, never the live decode input.
            i.instruction = ops[(sequence + 13) % ops.size()];
            i.startToken = c.token; i.completeToken = c.token;
            i.nativeResponse = c.reply;
            for (unsigned n = 0; n < DOMAINS; ++n) {
                i.request[n] = c.request;
                if (n != c.domain) {
                    i.request[n].address ^= uint64_t(n + 1) << 40;
                    i.request[n].data ^= UINT64_C(0xdeadbeef) * (n + 1);
                    i.request[n].handle = (n + sequence) & 15;
                }
            }
            i.architecturalFpBusy = c.protectedOwner;
        }
        return in;
    }
    void runStream() {
        streaming = true;
        // Independent one-slot native source: one edge latency, eight integer
        // acceptances on consecutive edges, seven consume/reaccept edges.
        for (unsigned beat = 0; beat <= 8; ++beat) {
            std::array<Input, LANES> in;
            for (unsigned lane = 0; lane < LANES; ++lane) {
                auto &i = in[lane];
                if (beat < 8) {
                    i.requestValid[0] = true;
                    i.request[0] = makeCase(lane, beat, ops).request;
                    i.request[0].handle = lane ? beat : 0;
                }
                if (beat) {
                    i.nativeResponseValid = true;
                    i.nativeResponse = makeCase(lane, beat - 1, ops).reply;
                    i.nativeResponse.handle = lane ? beat - 1 : 0;
                    i.busy[0] = true;
                }
            }
            tick(in);
        }
        streaming = false;
    }
    void runCase(unsigned sequence) {
        const unsigned r = schedule == "baseline" ? 2 : 3;
        const unsigned delay = schedule == "baseline" ? 1 : 3;
        const unsigned s = schedule == "baseline" ? 2 : 3;
        const unsigned hold = schedule == "baseline" ? 2 : 4;
        auto in = caseInputs(sequence);
        for (unsigned lane = 0; lane < LANES; ++lane) {
            const Case c = makeCase(lane, sequence, ops);
            in[lane].start = c.protectedOwner;
            in[lane].instruction = c.instruction;
        }
        tick(in);
        in = caseInputs(sequence);
        for (auto &i : in) { i.requestValid.fill(true); i.nativeRequestReady = false; }
        for (unsigned n = 0; n < r; ++n) tick(in);
        for (auto &i : in) i.nativeRequestReady = true;
        tick(in);
        in = caseInputs(sequence);
        for (unsigned lane = 0; lane < LANES; ++lane)
            in[lane].busy[makeCase(lane, sequence, ops).domain] = true;
        for (unsigned n = 0; n < delay; ++n) tick(in);
        for (unsigned lane = 0; lane < LANES; ++lane) {
            in[lane].nativeResponseValid = true;
            in[lane].responseReady[makeCase(lane, sequence, ops).domain] = false;
        }
        for (unsigned n = 0; n < s; ++n) tick(in);
        for (auto &i : in) i.responseReady.fill(true);
        tick(in);
        in = caseInputs(sequence);
        for (unsigned lane = 0; lane < LANES; ++lane) in[lane].complete = makeCase(lane, sequence, ops).protectedOwner;
        tick(in);
        for (unsigned n = 0; n < hold; ++n) {
            in = caseInputs(sequence);
            for (unsigned lane = 0; lane < LANES; ++lane) if (makeCase(lane, sequence, ops).protectedOwner && n < 2) {
                in[lane].commit.fill(true);
                in[lane].commitToken.fill(in[lane].startToken);
                in[lane].commitToken[0].tag ^= UINT64_C(1) << (n == 0 ? 63 : 33);
                in[lane].commitToken[1].index ^= 1;
            }
            tick(in);
        }
        in = caseInputs(sequence);
        for (unsigned lane = 0; lane < LANES; ++lane) if (makeCase(lane, sequence, ops).protectedOwner) {
            const unsigned slot = sequence % 2;
            in[lane].commit[slot] = true;
            in[lane].commitToken[slot] = in[lane].startToken;
        }
        tick(in);
        tick(caseInputs(sequence));
    }
    void verifyCoverage() const {
        const bool baseline = schedule == "baseline";
        check(cycle == (baseline ? 877U : 1261U) && idleResets == 1, "coverage", 0);
        for (unsigned lane = 0; lane < LANES; ++lane) {
            const auto &l = ledger[lane]; const auto &c = l.counts;
            const std::array<unsigned, DOMAINS> expected = lane ?
                std::array<unsigned, DOMAINS>{40, 0, 32} : std::array<unsigned, DOMAINS>{40, 16, 16};
            const unsigned owners = lane ? 32 : 40;
            check(c.requests == expected && c.responses == expected && c.starts == owners &&
                c.completions == owners && c.retirements == owners && c.wrongTag == 2 * owners &&
                c.wrongIndex == 2 * owners && c.requestStalls == (baseline ? 128U : 192U) &&
                c.responseStalls == (baseline ? 128U : 192U) && c.responseDelay == (baseline ? 64U : 192U) &&
                c.postResponseHolds == owners * (baseline ? 3 : 5) && c.arithmeticOverlap == (lane ? 0U : 8U) &&
                c.busyMasks == UINT32_MAX && c.metadataMask == (lane ? 1U : 255U) && c.statusMask == 15 &&
                c.hForms == (lane ? 0U : 8191U) && c.handles == (lane ? UINT64_C(131071) : 1) &&
                c.sustainedRequests == 8 && c.sustainedTurnovers == 7, "coverage", lane);
            check(!l.active && !l.pending && !l.heldRequest && !l.heldResponse, "drain", lane);
        }
    }
public:
    Bench(std::string s, std::string n, const std::string &path) :
        d(*new (storage) SMemoryDomainSelectorGsim), schedule(std::move(s)), negative(std::move(n)) {
        d.LOG_START = 1;
        d.activateAll();
        if (!path.empty()) {
            trace.open(path);
            check(bool(trace), "trace_open", 0);
            trace << "{\"event\":\"header\",\"schema\":1,\"schedule\":\"" << schedule
                  << "\",\"component_only\":true,\"guest_fd_execution\":false,\"cycle_limit\":4096,"
                     "\"cases_per_lane\":64,\"stream_requests\":8,\"request_fields\":[\"address\",\"data\",\"epoch\","
                     "\"handle\",\"size\",\"mask\",\"op\",\"write\",\"atomic\",\"virtualized\",\"prechecked\",\"hint\","
                     "\"uncached\"],\"reply_fields\":[\"data\",\"gpa\",\"handle\",\"error\",\"page\","
                     "\"guest_page_fault\",\"guest_address\",\"implicit_pte\"]}\n";
        }
    }
    ~Bench() { d.~SMemoryDomainSelectorGsim(); }
    void run() {
        resetting = true; ++idleResets;
        tick({}); tick({}); resetting = false;
        for (unsigned mask = 0; mask < 32; ++mask) {
            std::array<Input, LANES> in;
            for (auto &i : in) {
                i.instruction = ops[mask % ops.size()];
                i.architecturalFpBusy = true;
                for (unsigned n = 0; n < 5; ++n) i.busy[n] = (mask >> n) & 1;
            }
            tick(in);
        }
        runStream();
        matrix = true;
        for (unsigned sequence = 0; sequence < CASES; ++sequence) runCase(sequence);
        matrix = false;
        tick({}); tick({});
        verifyCoverage();
        check(negative.empty(), "negative_not_triggered", 0);
        if (trace.is_open()) {
            trace << "{\"event\":\"summary\",\"summary\":"; summary(trace); trace << "}\n";
            trace.flush();
            check(bool(trace) && trace.tellp() >= 0 && uint64_t(trace.tellp()) <= TRACE_LIMIT, "trace_bound", 0);
        }
    }
    void summary(std::ostream &s) const {
        s << "{\"schema\":1,\"component_only\":true,\"guest_fd_execution\":false,\"schedule\":\"" << schedule
          << "\",\"cycles\":" << cycle << ",\"idle_resets\":" << idleResets << ",\"lanes\":[";
        for (unsigned lane = 0; lane < LANES; ++lane) {
            const auto &c = ledger[lane].counts;
            s << (lane ? ",{\"name\":\"host\",\"requests\":" : "{\"name\":\"guest\",\"requests\":");
            arrayJson(s, c.requests); s << ",\"responses\":"; arrayJson(s, c.responses);
            s << ",\"starts\":" << c.starts << ",\"completions\":" << c.completions
              << ",\"retirements\":" << c.retirements << ",\"request_stalls\":" << c.requestStalls
              << ",\"response_stalls\":" << c.responseStalls << ",\"response_delay\":" << c.responseDelay
              << ",\"post_response_holds\":" << c.postResponseHolds << ",\"wrong_tag\":" << c.wrongTag
              << ",\"wrong_index\":" << c.wrongIndex << ",\"arithmetic_overlap\":" << c.arithmeticOverlap
              << ",\"busy_masks\":" << c.busyMasks << ",\"metadata_mask\":" << c.metadataMask
              << ",\"status_mask\":" << c.statusMask << ",\"h_forms\":" << c.hForms << ",\"handles\":" << c.handles
              << ",\"sustained_requests\":" << c.sustainedRequests
              << ",\"sustained_turnovers\":" << c.sustainedTurnovers << ",\"drained\":true}";
        }
        s << "]}";
    }
};
} // namespace

int main(int argc, char **argv) {
    try {
        std::string schedule = "baseline", negative, path;
        for (int n = 1; n < argc; ++n) {
            const std::string arg = argv[n];
            if (arg == "--schedule" && n + 1 < argc) schedule = argv[++n];
            else if (arg == "--negative" && n + 1 < argc) negative = argv[++n];
            else if (arg == "--trace" && n + 1 < argc) path = argv[++n];
            else throw std::runtime_error("MEMORY_DOMAIN_SELECTOR_CHECK[cli]: invalid argument");
        }
        const std::array<std::string, 12> negatives{"", "owner", "classification", "request_payload",
            "request_exclusion", "response_payload", "response_exclusion", "metadata", "handle", "stall", "busy", "retirement"};
        bool known = false;
        for (const auto &name : negatives) known |= negative == name;
        if (!known || (schedule != "baseline" && schedule != "staggered") ||
            (!negative.empty() && schedule != "baseline"))
            throw std::runtime_error("MEMORY_DOMAIN_SELECTOR_CHECK[cli]: unknown schedule or negative");
        Bench bench(schedule, negative, path);
        bench.run();
        std::cout << "MEMORY_DOMAIN_SELECTOR_SUMMARY "; bench.summary(std::cout); std::cout << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
