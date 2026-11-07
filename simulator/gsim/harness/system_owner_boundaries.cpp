#include "SystemOwnerBoundariesGsim.h"
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

// Accepted-event helper verification only. No ROB/MSU reachability, real
// FP/counter retirement consumer, guest trap, cancellation or live reset model.
namespace {
constexpr unsigned DOMAINS = 3, OWNERS = 8, CYCLE_LIMIT = 256;
constexpr uint64_t TRACE_LIMIT = 1024 * 1024;
constexpr uint32_t H_LOAD = 0x6004c3f3U; // HLV.B x7,(x9), H 1.0 encoding.
constexpr uint32_t FP_LOAD = 0x0004b387U; // FLD f7,0(x9).
constexpr std::array<unsigned, OWNERS> DOMAIN{1, 2, 1, 2, 1, 1, 2, 1};
constexpr std::array<bool, OWNERS> EXCEPTION{true, true, false, false, false, true, true, false};
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
Token token(unsigned n) { return {n + 1, UINT64_C(0x8000000100000055) + (uint64_t(n) << 32)}; }
struct Request {
    uint64_t address = 0, data = 0;
    uint32_t epoch = 0;
    unsigned size = 0, mask = 0, op = 0;
    bool write = false, atomic = false, virt = false, prechecked = false, hint = false, uncached = false;
    bool operator==(const Request &) const = default;
};
struct Reply {
    uint64_t data = 0;
    bool error = false, page = false;
    bool operator==(const Reply &) const = default;
};
struct Input {
    bool start = false, complete = false, exception = true;
    Token startToken{15, UINT64_C(0xdeadbeef00000055)}, completeToken{15, UINT64_C(0xdeadbeef00000055)};
    uint32_t instruction = FP_LOAD;
    std::array<bool, 2> commit{};
    std::array<Token, 2> commitToken{};
    std::array<bool, DOMAINS> requestValid{}, responseReady{true, true, true};
    std::array<Request, DOMAINS> request{};
    bool nativeRequestReady = true, nativeResponseValid = false;
    Reply nativeResponse;
    std::array<bool, 5> busy{}; // integer, H, FP memory, posted, prefetch.
};
struct Output {
    bool active = false, context = false, h = false, fp = false, retired = false;
    Token token;
    unsigned domain = 0, matches = 0;
    bool busy = false, cpuBusy = false;
    std::array<bool, DOMAINS> requestReady{}, responseValid{};
    std::array<Reply, DOMAINS> response{};
    bool nativeRequestValid = false, nativeResponseReady = false;
    Request nativeRequest;
};
struct Counts {
    std::array<unsigned, DOMAINS> requests{}, responses{};
    unsigned starts = 0, successful = 0, exceptional = 0, retirements = 0;
    unsigned retireCapture = 0, exceptionCapture = 0, inactiveMatches = 0, retiredPulses = 0;
    unsigned requestStalls = 0, responseStalls = 0, responseDelay = 0;
    unsigned drains = 0, holds = 0, wrongTag = 0, wrongIndex = 0, invalidMatches = 0;
};
struct Ledger {
    bool active = false, responded = false, requested = false;
    Token token;
    unsigned domain = 0, completion = 0, quiet = 0;
    std::optional<unsigned> pending;
    std::optional<Request> heldRequest;
    std::optional<Reply> heldResponse;
    std::vector<Token> exceptionalTokens;
    std::array<unsigned, OWNERS> completions{}, retirements{};
    Counts counts;
};
struct Row { unsigned cycle; bool reset; std::string phase; Input input; Output output; };

class Bench {
    alignas(SSystemOwnerBoundariesGsim) std::byte storage[sizeof(SSystemOwnerBoundariesGsim)]{};
    SSystemOwnerBoundariesGsim &d;
    Ledger l;
    std::ofstream trace;
    std::optional<Row> previous;
    std::string schedule, negative, stateCheck = "owner";
    bool mutated = false;
    unsigned cycle = 0;
    void check(bool yes, const std::string &name) const {
        if (!yes) throw std::runtime_error("SYSTEM_OWNER_BOUNDARIES_CHECK[" + name +
            "]: cycle=" + std::to_string(cycle));
    }
    void drive(const Input &i) {
        d.set_io$$acceptedStart$$valid(i.start);
        d.set_io$$acceptedStart$$bits$$instruction(i.instruction);
        d.set_io$$acceptedStart$$bits$$token$$index(i.startToken.index);
        d.set_io$$acceptedStart$$bits$$token$$tag(i.startToken.tag);
        d.set_io$$acceptedComplete$$valid(i.complete);
        d.set_io$$acceptedComplete$$bits$$token$$index(i.completeToken.index);
        d.set_io$$acceptedComplete$$bits$$token$$tag(i.completeToken.tag);
        d.set_io$$acceptedComplete$$bits$$exception(i.exception);
        d.set_io$$commit0$$valid(i.commit[0]);
        d.set_io$$commit0$$bits$$index(i.commitToken[0].index);
        d.set_io$$commit0$$bits$$tag(i.commitToken[0].tag);
        d.set_io$$commit1$$valid(i.commit[1]);
        d.set_io$$commit1$$bits$$index(i.commitToken[1].index);
        d.set_io$$commit1$$bits$$tag(i.commitToken[1].tag);
#define CLIENT_DRIVE(P, N) \
        d.set_io$$##P##$$request$$valid(i.requestValid[N]); \
        d.set_io$$##P##$$request$$bits$$address(i.request[N].address); \
        d.set_io$$##P##$$request$$bits$$data(i.request[N].data); \
        d.set_io$$##P##$$request$$bits$$translationEpoch(i.request[N].epoch); \
        d.set_io$$##P##$$request$$bits$$size(i.request[N].size); \
        d.set_io$$##P##$$request$$bits$$mask(i.request[N].mask); \
        d.set_io$$##P##$$request$$bits$$atomicOp(i.request[N].op); \
        d.set_io$$##P##$$request$$bits$$write(i.request[N].write); \
        d.set_io$$##P##$$request$$bits$$atomic(i.request[N].atomic); \
        d.set_io$$##P##$$request$$bits$$virtualized(i.request[N].virt); \
        d.set_io$$##P##$$request$$bits$$precheckedLoad(i.request[N].prechecked); \
        d.set_io$$##P##$$request$$bits$$prefetchNextAllowed(i.request[N].hint); \
        d.set_io$$##P##$$request$$bits$$uncached(i.request[N].uncached); \
        d.set_io$$##P##$$response$$ready(i.responseReady[N]);
        CLIENT_DRIVE(integer, 0) CLIENT_DRIVE(h, 1) CLIENT_DRIVE(fp, 2)
#undef CLIENT_DRIVE
        d.set_io$$memory$$request$$ready(i.nativeRequestReady);
        d.set_io$$memory$$response$$valid(i.nativeResponseValid);
        d.set_io$$memory$$response$$bits$$data(i.nativeResponse.data);
        d.set_io$$memory$$response$$bits$$error(i.nativeResponse.error);
        d.set_io$$memory$$response$$bits$$pageFault(i.nativeResponse.page);
        d.set_io$$integerBusy(i.busy[0]); d.set_io$$hBusy(i.busy[1]);
        d.set_io$$fpMemoryBusy(i.busy[2]); d.set_io$$postedBusy(i.busy[3]);
        d.set_io$$prefetchBusy(i.busy[4]);
    }
    Output observe() const {
        Output o;
        o.active = d.get_io$$ownerActive();
        o.token = {d.get_io$$ownerToken$$index(), d.get_io$$ownerToken$$tag()};
        o.context = d.get_io$$contextMemoryEpoch(); o.h = d.get_io$$hMemoryEpoch();
        o.fp = d.get_io$$fpMemoryEpoch(); o.domain = d.get_io$$domain();
        o.retired = d.get_io$$retired(); o.matches = d.get_io$$retireMatches();
        o.busy = d.get_io$$busy(); o.cpuBusy = d.get_io$$cpuBusy();
#define CLIENT_READ(P, N) \
        o.requestReady[N] = d.get_io$$##P##$$request$$ready(); \
        o.responseValid[N] = d.get_io$$##P##$$response$$valid(); \
        o.response[N].data = d.get_io$$##P##$$response$$bits$$data(); \
        o.response[N].error = d.get_io$$##P##$$response$$bits$$error(); \
        o.response[N].page = d.get_io$$##P##$$response$$bits$$pageFault();
        CLIENT_READ(integer, 0) CLIENT_READ(h, 1) CLIENT_READ(fp, 2)
#undef CLIENT_READ
        o.nativeRequestValid = d.get_io$$memory$$request$$valid();
        o.nativeResponseReady = d.get_io$$memory$$response$$ready();
        o.nativeRequest.address = d.get_io$$memory$$request$$bits$$address();
        o.nativeRequest.data = d.get_io$$memory$$request$$bits$$data();
        o.nativeRequest.epoch = d.get_io$$memory$$request$$bits$$translationEpoch();
        o.nativeRequest.size = d.get_io$$memory$$request$$bits$$size();
        o.nativeRequest.mask = d.get_io$$memory$$request$$bits$$mask();
        o.nativeRequest.op = d.get_io$$memory$$request$$bits$$atomicOp();
        o.nativeRequest.write = d.get_io$$memory$$request$$bits$$write();
        o.nativeRequest.atomic = d.get_io$$memory$$request$$bits$$atomic();
        o.nativeRequest.virt = d.get_io$$memory$$request$$bits$$virtualized();
        o.nativeRequest.prechecked = d.get_io$$memory$$request$$bits$$precheckedLoad();
        o.nativeRequest.hint = d.get_io$$memory$$request$$bits$$prefetchNextAllowed();
        o.nativeRequest.uncached = d.get_io$$memory$$request$$bits$$uncached();
        return o;
    }
    static void tokenJson(std::ostream &s, const Token &t) { s << t.index << ',' << t.tag; }
    static void requestJson(std::ostream &s, const Request &r) {
        s << '[' << r.address << ',' << r.data << ',' << r.epoch << ',' << r.size << ',' << r.mask << ','
          << r.op << ',' << r.write << ',' << r.atomic << ',' << r.virt << ',' << r.prechecked << ','
          << r.hint << ',' << r.uncached << ']';
    }
    static void replyJson(std::ostream &s, const Reply &r) { s << '[' << r.data << ',' << r.error << ',' << r.page << ']'; }
    template <class T, size_t N> static void arrayJson(std::ostream &s, const std::array<T, N> &a) {
        s << '[';
        for (size_t n = 0; n < N; ++n) s << (n ? "," : "") << a[n];
        s << ']';
    }
    static void inputJson(std::ostream &s, const Input &i) {
        s << "{\"start\":[" << i.start << ','; tokenJson(s, i.startToken);
        s << ',' << i.instruction << "],\"complete\":[" << i.complete << ',';
        tokenJson(s, i.completeToken); s << ',' << i.exception << "],\"commits\":[";
        for (unsigned n = 0; n < 2; ++n) {
            s << (n ? ",[" : "[") << i.commit[n] << ','; tokenJson(s, i.commitToken[n]); s << ']';
        }
        s << "],\"request_valid\":"; arrayJson(s, i.requestValid); s << ",\"request\":[";
        for (unsigned n = 0; n < DOMAINS; ++n) { if (n) s << ','; requestJson(s, i.request[n]); }
        s << "],\"response_ready\":"; arrayJson(s, i.responseReady);
        s << ",\"native_request_ready\":" << i.nativeRequestReady
          << ",\"native_response_valid\":" << i.nativeResponseValid << ",\"native_response\":";
        replyJson(s, i.nativeResponse); s << ",\"busy\":"; arrayJson(s, i.busy); s << '}';
    }
    static void ownerJson(std::ostream &s, const Output &o) {
        s << '[' << o.active << ','; tokenJson(s, o.token);
        s << ',' << o.context << ',' << o.h << ',' << o.fp << ']';
    }
    static void outputJson(std::ostream &s, const Output &o) {
        s << "{\"owner\":"; ownerJson(s, o);
        s << ",\"domain\":" << o.domain << ",\"retired\":" << o.retired
          << ",\"retire_matches\":" << o.matches << ",\"busy\":" << o.busy << ",\"cpu_busy\":" << o.cpuBusy
          << ",\"request_ready\":"; arrayJson(s, o.requestReady);
        s << ",\"response_valid\":"; arrayJson(s, o.responseValid); s << ",\"response\":[";
        for (unsigned n = 0; n < DOMAINS; ++n) { if (n) s << ','; replyJson(s, o.response[n]); }
        s << "],\"native_request_valid\":" << o.nativeRequestValid
          << ",\"native_response_ready\":" << o.nativeResponseReady << ",\"native_request\":";
        requestJson(s, o.nativeRequest); s << '}';
    }
    void flushRow(const Output *post) {
        if (!trace.is_open() || !previous) return;
        const Row &r = *previous;
        trace << "{\"event\":\"cycle\",\"cycle\":" << r.cycle << ",\"reset\":" << r.reset
              << ",\"phase\":\"" << r.phase << "\",\"input\":";
        inputJson(trace, r.input); trace << ",\"output\":"; outputJson(trace, r.output);
        trace << ",\"post\":";
        if (post) {
            trace << "{\"owner\":"; ownerJson(trace, *post); trace << ",\"domain\":" << post->domain << '}';
        } else trace << "null";
        trace << "}\n";
        check(bool(trace) && trace.tellp() >= 0 && uint64_t(trace.tellp()) <= TRACE_LIMIT, "trace_bound");
    }
    void corrupt(Output &o) {
        if (mutated || negative.empty()) return;
        if (negative == "exception_release" && cycle == 18) { o.active = true; mutated = true; }
        if (negative == "retire_capture" && cycle == 37) { o.token.tag ^= 1; mutated = true; }
        if (negative == "exception_capture" && cycle == 70) { o.token.tag ^= 1; mutated = true; }
        if (negative == "inactive_match" && cycle == 3) { o.matches = 0; o.retired = false; mutated = true; }
        if (negative == "high_tag" && cycle == 6) { o.matches = 1; o.retired = true; mutated = true; }
        if (negative == "index_match" && cycle == 7) { o.matches = 2; o.retired = true; mutated = true; }
        if (negative == "valid_qualification" && cycle == 5) { o.matches = 1; o.retired = true; mutated = true; }
        if (negative == "epoch_clear" && cycle == 18) { o.context = true; mutated = true; }
        if (negative == "domain_switch" && cycle == 37) { o.domain = 1; mutated = true; }
    }
    void inspect(const Input &i, const Output &o, const std::string &phase, bool reset) {
        auto &c = l.counts;
        const unsigned selected = l.active ? l.domain : 0;
        check(o.active == l.active && o.token == l.token, stateCheck);
        check(o.context == l.active && o.h == (l.active && selected == 1) &&
            o.fp == (l.active && selected == 2), l.active ? "epochs" : "epoch_clear");
        check(o.domain == selected, "domain_switch");
        stateCheck = "owner";
        unsigned matches = 0;
        for (unsigned n = 0; n < 2; ++n) {
            if (i.commit[n] && i.commitToken[n] == l.token) matches |= 1U << n;
            if (i.commit[n]) for (const auto &exceptionToken : l.exceptionalTokens)
                check(!(i.commitToken[n] == exceptionToken), "exception_commit");
        }
        check(matches != 3, "duplicate_commit");
        std::string matchCheck = !l.active && matches ? "inactive_match" : "retirement_match";
        if (phase.ends_with("_2") && phase.starts_with("probe_")) matchCheck = "valid_qualification";
        if (phase.ends_with("_3") && phase.starts_with("probe_")) matchCheck = "high_tag";
        if (phase.ends_with("_4") && phase.starts_with("probe_")) matchCheck = "index_match";
        check(o.matches == matches && o.retired == bool(matches), matchCheck);
        const bool busy = i.busy[0] || i.busy[1] || i.busy[2] || i.busy[3] || i.busy[4];
        check(o.cpuBusy == (i.busy[0] || i.busy[1] || i.busy[2] || i.busy[3]) && o.busy == busy, "busy");
        check(!i.busy[0] && !i.busy[3] && !i.busy[4], "stimulus_busy");
        if (l.heldRequest) check(o.nativeRequestValid && o.nativeRequest == *l.heldRequest, "request_stall");
        if (l.heldResponse) check(o.responseValid[selected] && o.response[selected] == *l.heldResponse, "response_stall");
        for (unsigned n = 0; n < DOMAINS; ++n) {
            check(o.requestReady[n] == (n == selected && i.nativeRequestReady), "request_exclusion");
            check(o.responseValid[n] == (n == selected && i.nativeResponseValid), "response_exclusion");
            check(o.response[n] == i.nativeResponse, "response_payload");
        }
        check(o.nativeRequestValid == i.requestValid[selected] && o.nativeRequest == i.request[selected], "request_payload");
        check(o.nativeResponseReady == i.responseReady[selected], "response_exclusion");
        const bool requestFire = o.nativeRequestValid && i.nativeRequestReady;
        const bool responseFire = i.nativeResponseValid && o.nativeResponseReady;
        const bool offers = i.requestValid[0] || i.requestValid[1] || i.requestValid[2] || i.nativeResponseValid;
        const bool drained = !l.pending && !l.heldRequest && !l.heldResponse && !offers && !busy;
        if (reset) {
            check(!l.active && drained && !i.start && !i.complete && !matches, "idle_reset");
            return;
        }
        if (i.nativeResponseValid) check(l.active && l.pending && *l.pending == selected, "response_credit");
        if (requestFire) check(l.active && !l.pending && !l.requested && !l.completion, "request_credit");
        if (l.pending && !i.nativeResponseValid) ++c.responseDelay;
        if (o.nativeRequestValid && !i.nativeRequestReady) ++c.requestStalls;
        if (i.nativeResponseValid && !o.nativeResponseReady) ++c.responseStalls;
        for (unsigned n = 0; n < 2; ++n) if (i.commit[n] && !(i.commitToken[n] == l.token)) {
            if (i.commitToken[n].index == l.token.index) ++c.wrongTag;
            if (i.commitToken[n].tag == l.token.tag) ++c.wrongIndex;
        }
        if (phase.starts_with("probe_") && phase.ends_with("_2")) {
            check(!i.commit[0] && !i.commit[1] && i.commitToken[0] == l.token && i.commitToken[1] == l.token,
                "invalid_probe");
            ++c.invalidMatches;
        }
        if (phase.starts_with("drain_")) { check(l.active && l.responded && drained, "drain"); ++c.drains; }
        if (phase.starts_with("hold_")) { check(l.active && l.responded && drained && l.quiet, "hold"); ++c.holds; }
        const bool oldActive = l.active;
        if (i.complete) {
            check(oldActive && i.completeToken == l.token && l.responded && drained && l.quiet && !l.completion,
                "completion_drain");
            const unsigned owner = l.token.index - 1;
            check(owner < OWNERS && token(owner) == l.token && i.exception == EXCEPTION[owner], "completion_token");
            ++l.completions[owner];
            l.completion = i.exception ? 2 : 1;
            if (i.exception) {
                check(!matches, "exception_commit");
                l.exceptionalTokens.push_back(l.token); ++c.exceptional;
                l.active = false;
                stateCheck = i.start ? "exception_capture" : "exception_release";
                c.exceptionCapture += i.start;
            } else ++c.successful;
        }
        if (matches) {
            ++c.retiredPulses;
            if (oldActive) {
                check(!i.complete && l.completion == 1 && l.responded && drained && l.quiet, "retirement_drain");
                ++l.retirements[l.token.index - 1]; ++c.retirements;
                l.active = false;
                stateCheck = i.start ? "retire_capture" : "retirement_release";
                c.retireCapture += i.start;
            } else {
                check(drained && !i.start && !i.complete && phase.starts_with("probe_"), "inactive_probe");
                ++c.inactiveMatches;
            }
        }
        if (i.start) {
            check(!l.active && drained && !requestFire && !responseFire && c.starts < OWNERS, "start_drain");
            const unsigned n = c.starts;
            check(i.startToken == token(n) && i.instruction == (DOMAIN[n] == 1 ? H_LOAD : FP_LOAD), "start_token");
            l.active = true; l.token = i.startToken; l.domain = DOMAIN[n]; l.completion = 0;
            l.requested = false; l.responded = false; l.quiet = 0;
            ++c.starts;
        }
        if (responseFire) { ++c.responses[selected]; l.pending.reset(); l.responded = true; }
        if (requestFire) { ++c.requests[selected]; l.pending = selected; l.requested = true; }
        l.heldRequest = o.nativeRequestValid && !i.nativeRequestReady ?
            std::optional<Request>(o.nativeRequest) : std::nullopt;
        l.heldResponse = i.nativeResponseValid && !o.nativeResponseReady ?
            std::optional<Reply>(o.response[selected]) : std::nullopt;
        if (l.active && l.responded && drained) ++l.quiet;
    }
    void tick(const Input &i, const std::string &phase, bool reset = false) {
        check(++cycle <= CYCLE_LIMIT, "cycle_bound");
        drive(i); d.set_reset(reset); d.step();
        Output o = observe();
        // step exposes this edge's pre-update outputs. The next observation is
        // the actual post-edge owner, never a prediction copied from the ledger.
        flushRow(&o);
        previous = Row{cycle, reset, phase, i, o};
        corrupt(o);
        inspect(i, o, phase, reset);
    }
    static Input inputs(unsigned n) {
        Input i;
        i.instruction = DOMAIN[n] == 1 ? FP_LOAD : H_LOAD; // Invalid start garbage must not reclassify.
        i.startToken = token(n); i.startToken.tag ^= UINT64_C(1) << 63;
        i.completeToken = i.startToken;
        i.nativeResponse = {UINT64_C(0xfedcba9876543210) ^ (uint64_t(n) << 36), EXCEPTION[n], false};
        for (unsigned domain = 0; domain < DOMAINS; ++domain) {
            auto &r = i.request[domain];
            r.address = UINT64_C(0x8000000080001000) ^ (uint64_t(domain) << 48) ^ (uint64_t(n) << 3);
            r.data = UINT64_C(0x9abcdef012345678) ^ (uint64_t(n) << 40) ^ domain;
            r.epoch = 0x80000000U + n;
            r.size = 3; r.mask = 255; // Read requests; irrelevant control bits remain zero.
        }
        return i;
    }
    void start(unsigned n, Input &i) const {
        i.start = true; i.startToken = token(n); i.instruction = DOMAIN[n] == 1 ? H_LOAD : FP_LOAD;
    }
    void probes(const std::string &kind, Token retained) {
        for (unsigned n = 0; n < 6; ++n) {
            Input i;
            if (n < 2) { i.commit[n] = true; i.commitToken[n] = retained; }
            if (n == 2) i.commitToken.fill(retained);
            if (n == 3) { i.commit[0] = true; i.commitToken[0] = retained; i.commitToken[0].tag ^= UINT64_C(1) << 63; }
            if (n == 4) { i.commit[1] = true; i.commitToken[1] = retained; i.commitToken[1].index ^= 1; }
            tick(i, "probe_" + kind + "_" + std::to_string(n));
        }
    }
    void owner(unsigned n, bool standalone) {
        const bool baseline = schedule == "baseline";
        const unsigned s = baseline ? 1 : 2, delay = baseline ? 1 : 3;
        const unsigned r = baseline ? 1 : 2, hold = baseline ? 1 : 3;
        const std::string name(1, char('A' + n));
        Input i = inputs(n);
        if (standalone) { start(n, i); tick(i, "start_" + name); }
        i = inputs(n); i.requestValid[DOMAIN[n]] = true; i.nativeRequestReady = false;
        for (unsigned k = 0; k < s; ++k) tick(i, "request_stall_" + name);
        i.nativeRequestReady = true; tick(i, "request_" + name);
        i = inputs(n); i.busy[DOMAIN[n]] = true;
        for (unsigned k = 0; k < delay; ++k) tick(i, "delay_" + name);
        i.nativeResponseValid = true; i.responseReady[DOMAIN[n]] = false;
        for (unsigned k = 0; k < r; ++k) tick(i, "response_stall_" + name);
        i.responseReady[DOMAIN[n]] = true; tick(i, "response_" + name);
        tick(inputs(n), "drain_" + name);
        if (!EXCEPTION[n]) {
            i = inputs(n); i.complete = true; i.completeToken = token(n); i.exception = false;
            tick(i, "complete_" + name);
        }
        i = inputs(n); i.commit.fill(true); i.commitToken.fill(token(n));
        i.commitToken[0].tag ^= UINT64_C(1) << 63; i.commitToken[1].index ^= 1;
        for (unsigned k = 0; k < hold; ++k) tick(i, "hold_" + name);
        i = inputs(n);
        if (EXCEPTION[n]) {
            i.complete = true; i.completeToken = token(n);
            if (n == 5 || n == 6) { start(n + 1, i); tick(i, "exception_capture_" + name); }
            else tick(i, "release_" + name);
        } else {
            const unsigned lane = n == 3 || n == 7 ? 1 : 0;
            i.commit[lane] = true; i.commitToken[lane] = token(n);
            if (n == 2 || n == 3) { start(n + 1, i); tick(i, "retire_capture_" + name); }
            else tick(i, "retire_" + name);
        }
    }
    void verifyCoverage() const {
        const auto &c = l.counts;
        const bool baseline = schedule == "baseline";
        const std::array<unsigned, DOMAINS> transfers{0, 5, 3};
        check(cycle == (baseline ? 88U : 136U) && c.requests == transfers && c.responses == transfers &&
            c.starts == 8 && c.successful == 4 && c.exceptional == 4 && c.retirements == 4 &&
            c.retireCapture == 2 && c.exceptionCapture == 2 && c.inactiveMatches == 4 && c.retiredPulses == 8 &&
            c.requestStalls == (baseline ? 8U : 16U) && c.responseStalls == (baseline ? 8U : 16U) &&
            c.responseDelay == (baseline ? 8U : 24U) && c.drains == 8 && c.holds == (baseline ? 8U : 24U) &&
            c.wrongTag == (baseline ? 10U : 26U) && c.wrongIndex == (baseline ? 10U : 26U) &&
            c.invalidMatches == 2, "coverage");
        for (unsigned n = 0; n < OWNERS; ++n)
            check(l.completions[n] == 1 && l.retirements[n] == unsigned(!EXCEPTION[n]), "owner_coverage");
        check(!l.active && !l.pending && !l.heldRequest && !l.heldResponse, "final_drain");
    }
public:
    Bench(std::string s, std::string n, const std::string &path) :
        d(*new (storage) SSystemOwnerBoundariesGsim), schedule(std::move(s)), negative(std::move(n)) {
        d.LOG_START = 1; d.activateAll();
        if (!path.empty()) {
            trace.open(path); check(bool(trace), "trace_open");
            trace << "{\"event\":\"header\",\"schema\":1,\"schedule\":\"" << schedule
                  << "\",\"component_only\":true,\"guest_fd_execution\":false,\"cycle_limit\":256,\"owners\":8,"
                     "\"request_fields\":[\"address\",\"data\",\"epoch\",\"size\",\"mask\",\"op\",\"write\",\"atomic\","
                     "\"virtualized\",\"prechecked\",\"hint\",\"uncached\"],\"reply_fields\":[\"data\",\"error\",\"page\"]}\n";
        }
    }
    ~Bench() { d.~SSystemOwnerBoundariesGsim(); }
    void run() {
        tick({}, "reset", true); tick({}, "reset", true);
        probes("reset", {});
        owner(0, true); owner(1, true); owner(2, true); owner(3, false); owner(4, false);
        probes("retained", token(4));
        owner(5, true); owner(6, false); owner(7, false);
        tick({}, "final"); tick({}, "final");
        verifyCoverage(); check(negative.empty(), "negative_not_triggered");
        // The final quiet row has no sampled successor; do not fabricate one.
        flushRow(nullptr);
        if (trace.is_open()) {
            trace << "{\"event\":\"summary\",\"summary\":"; summary(trace); trace << "}\n";
            trace.flush();
            check(bool(trace) && trace.tellp() >= 0 && uint64_t(trace.tellp()) <= TRACE_LIMIT, "trace_bound");
        }
    }
    void summary(std::ostream &s) const {
        const auto &c = l.counts;
        s << "{\"schema\":1,\"component_only\":true,\"guest_fd_execution\":false,\"schedule\":\"" << schedule
          << "\",\"cycles\":" << cycle << ",\"idle_resets\":1,\"requests\":";
        arrayJson(s, c.requests); s << ",\"responses\":"; arrayJson(s, c.responses);
        s << ",\"starts\":" << c.starts << ",\"successful_completions\":" << c.successful
          << ",\"exceptional_completions\":" << c.exceptional << ",\"active_retirements\":" << c.retirements
          << ",\"retire_capture\":" << c.retireCapture << ",\"exception_capture\":" << c.exceptionCapture
          << ",\"inactive_matches\":" << c.inactiveMatches << ",\"retired_pulses\":" << c.retiredPulses
          << ",\"request_stalls\":" << c.requestStalls << ",\"response_stalls\":" << c.responseStalls
          << ",\"response_delay\":" << c.responseDelay << ",\"drain_cycles\":" << c.drains
          << ",\"hold_cycles\":" << c.holds << ",\"wrong_tag\":" << c.wrongTag
          << ",\"wrong_index\":" << c.wrongIndex << ",\"invalid_matches\":" << c.invalidMatches
          << ",\"drained\":true}";
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
            else throw std::runtime_error("SYSTEM_OWNER_BOUNDARIES_CHECK[cli]: invalid argument");
        }
        const std::array<std::string, 10> negatives{"", "exception_release", "retire_capture", "exception_capture",
            "inactive_match", "high_tag", "index_match", "valid_qualification", "epoch_clear", "domain_switch"};
        bool known = false;
        for (const auto &name : negatives) known |= negative == name;
        if (!known || (schedule != "baseline" && schedule != "staggered") ||
            (!negative.empty() && schedule != "baseline"))
            throw std::runtime_error("SYSTEM_OWNER_BOUNDARIES_CHECK[cli]: unknown schedule or negative");
        Bench bench(schedule, negative, path); bench.run();
        std::cout << "SYSTEM_OWNER_BOUNDARIES_SUMMARY "; bench.summary(std::cout); std::cout << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n'; return 1;
    }
}
