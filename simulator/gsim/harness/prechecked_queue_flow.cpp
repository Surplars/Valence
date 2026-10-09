#include "PrecheckedQueueFlowGsim.h"
#include "virtual_load_test_memory.h"
#include <algorithm>
#include <deque>
#include <iostream>
#include <optional>
#include <string>
#include <tuple>
#include <vector>
#ifndef QUEUE_FLOW_ENABLED
#define QUEUE_FLOW_ENABLED 0
#endif
#ifndef PREFETCH_ENABLED
#define PREFETCH_ENABLED 0
#endif
using namespace virtual_load_test;
// All expected addresses, permissions, order and response data are software inputs.
// No DUT-private bypass/fault/owner verdict participates in this oracle.
struct Request {
    uint64_t address = ram, epoch = 0, data = 0;
    bool prechecked = true, virt = false, uncached = false, write = false, atomic = false;
    unsigned size = 3, mask = 255, atomicOp = 0;
};
struct Expected { bool fault = false, page = false; uint64_t physical = ram; bool uncached = false, prefetch = true; };
struct Entry { Request request; Expected expected; uint64_t accepted; bool issued = false; };
struct Reply { uint64_t due, data; bool error = false; };
using Payload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, unsigned, bool, bool, bool, uint64_t, bool>;
using Response = std::tuple<uint64_t, bool, bool>;
class Bench {
    SPrecheckedQueueFlowGsim d;
    std::deque<Reply> ptes, physical;
    std::deque<Entry> expected;
    std::optional<Payload> held;
    std::optional<Response> heldResponse;
public:
    PageTables tables;
    uint64_t cycle = 0, contextSatp = satp, pmpAddress = allPmp, epoch = 0;
    uint64_t firstAccepted = 0, lastAccepted = 0, firstPhysical = 0, lastPhysical = 0;
    uint64_t latencySum = 0, latencyMin = ~0ULL, latencyMax = 0, trace = 1469598103934665603ULL;
    unsigned privilege = 1, cfg = 0x1f, accepted = 0, responded = 0, issued = 0, faults = 0;
    unsigned pteReads = 0, walks = 0, hits = 0, physicalHolds = 0, responseHolds = 0, upstreamStalls = 0;
    unsigned blockPhysical = 0, blockResponse = 0, latency = 2, pteLatency = 2;
    bool sum = false, mxr = false, flush = false, periodicStalls = false;
    std::string mutation;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); settle(); }
    Request certificate(uint64_t address = ram) const { Request r; r.address = address; r.epoch = epoch; return r; }
    void check(bool ok, const std::string &why) const { require(ok, "cycle " + std::to_string(cycle) + ": " + why); }
    bool physicalReady() const { return cycle >= blockPhysical && (!periodicStalls || cycle % 7 != 5); }
    bool pteReady() const { return !periodicStalls || cycle % 5 != 3; }
    void drive(std::optional<Request> request) {
        const Request r = request.value_or(Request{});
        d.set_io$$upstream$$request$$valid(request.has_value());
        d.set_io$$upstream$$request$$bits$$address(r.address); d.set_io$$upstream$$request$$bits$$data(r.data);
        d.set_io$$upstream$$request$$bits$$size(r.size); d.set_io$$upstream$$request$$bits$$mask(r.mask);
        d.set_io$$upstream$$request$$bits$$write(r.write); d.set_io$$upstream$$request$$bits$$atomic(r.atomic);
        d.set_io$$upstream$$request$$bits$$atomicOp(r.atomicOp); d.set_io$$upstream$$request$$bits$$virtualized(r.virt);
        d.set_io$$upstream$$request$$bits$$uncached(r.uncached); d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(1);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(r.prechecked);
        d.set_io$$upstream$$request$$bits$$translationEpoch(r.epoch);
        d.set_io$$upstream$$response$$ready(cycle >= blockResponse);
        d.set_io$$physical$$request$$ready(physicalReady());
        const bool pv = !physical.empty() && physical.front().due <= cycle;
        d.set_io$$physical$$response$$valid(pv); d.set_io$$physical$$response$$bits$$data(pv ? physical.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(pv && physical.front().error); d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(pteReady());
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$response$$valid(tv); d.set_io$$pte$$response$$bits$$data(tv ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(contextSatp); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(pmpAddress);
        d.set_io$$queryValid(0); d.set_io$$queryAddress(va); d.set_io$$querySize(3); d.set_io$$flush(flush);
    }
    bool tick(std::optional<Request> request = {}, std::optional<Expected> expectation = {}) {
        const bool pv = !physical.empty() && physical.front().due <= cycle;
        const bool tv = !ptes.empty() && ptes.front().due <= cycle;
        drive(request); d.step();
        const bool take = request && d.get_io$$upstream$$request$$ready();
        if (take) {
            check(expectation.has_value(), "accepted request lacks independent expectation");
            expected.push_back({*request, *expectation, cycle});
            if (!accepted) firstAccepted = cycle; lastAccepted = cycle; ++accepted;
        } else if (request) ++upstreamStalls;
        if (pv && d.get_io$$physical$$response$$ready()) physical.pop_front();
        if (tv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && pteReady()) {
            ptes.push_back({cycle + pteLatency, tables.pte(d.get_io$$pte$$request$$bits())}); ++pteReads;
        }
        const bool valid = d.get_io$$physical$$request$$valid();
        const Payload payload{d.get_io$$physical$$request$$bits$$address(), d.get_io$$physical$$request$$bits$$data(),
            d.get_io$$physical$$request$$bits$$size(), d.get_io$$physical$$request$$bits$$mask(),
            bool(d.get_io$$physical$$request$$bits$$write()), bool(d.get_io$$physical$$request$$bits$$atomic()),
            d.get_io$$physical$$request$$bits$$atomicOp(), bool(d.get_io$$physical$$request$$bits$$uncached()),
            bool(d.get_io$$physical$$request$$bits$$virtualized()), bool(d.get_io$$physical$$request$$bits$$precheckedLoad()),
            d.get_io$$physical$$request$$bits$$translationEpoch(), bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())};
        if (held) check(valid && payload == *held, "physical payload changed under backpressure");
        held = valid && !physicalReady() ? std::optional{payload} : std::nullopt;
        physicalHolds += valid && !physicalReady();
        if (valid && physicalReady()) {
            auto next = std::find_if(expected.begin(), expected.end(), [](const auto &e) { return !e.expected.fault && !e.issued; });
            check(next != expected.end(), "unauthorized or duplicate physical request");
            const auto &r = next->request; const auto &e = next->expected;
            check((std::get<0>(payload) ^ (mutation == "--inject-address" ? 8ULL : 0ULL)) == e.physical &&
                std::get<1>(payload) == r.data && std::get<2>(payload) == r.size && std::get<3>(payload) == r.mask &&
                std::get<4>(payload) == r.write && std::get<5>(payload) == r.atomic && std::get<6>(payload) == r.atomicOp &&
                std::get<7>(payload) == e.uncached, "independent physical order/address/shape mismatch");
            check(!std::get<8>(payload) && !std::get<9>(payload) && !std::get<10>(payload),
                "private authorization metadata escaped physically");
            check((std::get<11>(payload) ^ (mutation == "--inject-prefetch")) == (PREFETCH_ENABLED && e.prefetch),
                "independent next-line authorization mismatch");
            check(cycle >= next->accepted + 2, "registered ingress or checked boundary collapsed");
            const uint64_t delay = cycle - next->accepted;
            latencySum += delay; latencyMin = std::min(latencyMin, delay); latencyMax = std::max(latencyMax, delay);
            next->issued = true; physical.push_back({cycle + latency, readValue(e.physical)});
            if (!issued) firstPhysical = cycle; lastPhysical = cycle; ++issued;
        }
        const bool responseValid = d.get_io$$upstream$$response$$valid();
        const Response response{d.get_io$$upstream$$response$$bits$$data(), bool(d.get_io$$upstream$$response$$bits$$error()),
            bool(d.get_io$$upstream$$response$$bits$$pageFault())};
        if (heldResponse) check(responseValid && response == *heldResponse, "response payload changed under backpressure");
        heldResponse = responseValid && cycle < blockResponse ? std::optional{response} : std::nullopt;
        responseHolds += responseValid && cycle < blockResponse;
        if (responseValid && cycle >= blockResponse) {
            check(!expected.empty(), "unowned response"); const auto e = expected.front(); expected.pop_front();
            check(e.expected.fault || e.issued, "response preceded physical acceptance");
            check((std::get<1>(response) ^ (mutation == "--inject-fault" && e.expected.fault)) == e.expected.fault &&
                std::get<2>(response) == e.expected.page &&
                (std::get<0>(response) ^ (mutation == "--inject-response" ? 1ULL : 0ULL)) ==
                    (e.expected.fault ? 0 : readValue(e.expected.physical)), "independent ordered response/fault mismatch");
            trace ^= e.request.address; trace *= 1099511628211ULL;
            trace ^= std::get<0>(response); trace *= 1099511628211ULL;
            trace ^= std::get<1>(response); trace *= 1099511628211ULL;
            ++responded; faults += e.expected.fault;
        }
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit(); epoch = d.get_io$$epoch();
        ++cycle; return take;
    }
    void settle() { for (unsigned n = 0; n < 5; ++n) tick(); }
    void burst(const std::vector<std::pair<Request, Expected>> &requests) {
        unsigned cursor = 0;
        for (unsigned n = 0; n < 2000 && cursor < requests.size(); ++n)
            if (tick(requests[cursor].first, requests[cursor].second)) ++cursor;
        check(cursor == requests.size(), "ingress timed out"); drain();
    }
    void drain() {
        for (unsigned n = 0; n < 4000 && (!expected.empty() || !physical.empty() || !ptes.empty()); ++n) tick();
        check(expected.empty() && physical.empty() && ptes.empty(), "transaction drain timed out");
        settle(); check(d.get_io$$idle(), "idle omitted accepted ownership");
        check(accepted == responded, "accepted request lost its response");
    }
    void run(Request r, Expected e) { burst({{r, e}}); }
    void report(const std::string &name) const {
        std::cout << "PRECHECKED_QUEUE_FLOW_CASE name=" << name << " trace=" << trace << " accepted=" << accepted
            << " responses=" << responded << " physical=" << issued << " faults=" << faults << " cycles=" << cycle
            << " min_latency=" << (issued ? latencyMin : 0) << " max_latency=" << latencyMax << " latency_sum=" << latencySum
            << " accept_span=" << (accepted ? lastAccepted - firstAccepted : 0)
            << " physical_span=" << (issued ? lastPhysical - firstPhysical : 0)
            << " physical_holds=" << physicalHolds << " response_holds=" << responseHolds << " ingress_stalls=" << upstreamStalls
            << " walks=" << walks << " hits=" << hits << std::endl;
    }
};
int main(int argc, char **argv) { try {
    const std::string mutation = argc > 1 ? argv[1] : "";
    { Bench b; b.mutation = mutation; b.run(b.certificate(), {}); b.report("registered_latency"); }
    { Bench b; b.latency = 1; std::vector<std::pair<Request, Expected>> requests;
      for (unsigned n = 0; n < 48; ++n) requests.push_back({b.certificate(ram + n * 8), {false, false, ram + n * 8}});
      b.burst(requests); b.check(b.issued == 48, "stream lost physical owner"); b.report("unblocked_throughput"); }
    { Bench b; b.periodicStalls = true; b.pteLatency = 7; b.blockPhysical = b.cycle + 75; b.blockResponse = b.cycle + 130;
      std::vector<std::pair<Request, Expected>> requests;
      Request older; older.prechecked = false; older.virt = true; older.address = va;
      requests.push_back({older, {false, false, ram}});
      for (unsigned n = 1; n < 40; ++n) {
          auto r = b.certificate(ram + n * 8); const bool fault = n % 7 == 3; if (fault) --r.epoch;
          requests.push_back({r, {fault, false, r.address}});
      }
      b.mutation = mutation; b.burst(requests);
      b.check(b.physicalHolds > 0 && b.responseHolds > 0 && b.upstreamStalls > 0 && b.walks > 0,
          "hold/spill/older-translation pressure coverage missing"); b.report("hold_spill_older_priority"); }
    { Bench b; Request serial; serial.prechecked = false; serial.virt = true; serial.address = va;
      b.run(serial, {}); serial.address = va + 8;
      b.burst({{serial, {false, false, ram + 8}}, {b.certificate(ram + 24), {false, false, ram + 24}}});
      b.check(b.hits > 0, "warm older translated priority not exercised"); b.report("warm_translated_priority"); }
    { Bench b; b.mutation = mutation;
      for (unsigned kind = 0; kind < 8; ++kind) {
          auto r = b.certificate();
          if (kind == 0) --r.epoch; if (kind == 1) r.address = 0x10000000ULL;
          if (kind == 2) r.address = ram + ramBytes; if (kind == 3) r.write = true;
          if (kind == 4) { r.atomic = true; r.atomicOp = 2; }
          if (kind == 5) r.virt = true; if (kind == 6) r.uncached = true;
          if (kind == 7) r.address = ram + ramBytes - 4;
          b.run(r, {true, false});
      }
      b.check(b.issued == 0 && b.faults == 8, "invalid certificate escaped"); b.report("invalid_certificate"); }
    { Bench b;
      for (unsigned size = 0; size < 4; ++size) {
          auto r = b.certificate(ram + 16 + (size ? 0 : 3)); r.size = size;
          r.mask = ((1U << (1U << size)) - 1U) << (r.address & 7);
          b.run(r, {false, false, r.address});
      }
      auto r = b.certificate(ram + 1); b.run(r, {bool(QUEUE_FLOW_ENABLED), false, r.address});
      r = b.certificate(ram + 24); r.mask = 0x7f; b.run(r, {bool(QUEUE_FLOW_ENABLED), false, r.address});
      b.check(b.faults == (QUEUE_FLOW_ENABLED ? 2U : 0U), "documented poison-shape policy mismatch");
      b.report("shape_hardening"); }
    { Bench b;
      for (unsigned change = 0; change < 8; ++change) {
          auto stale = b.certificate();
          if (change == 0) { b.flush = true; b.tick(); b.flush = false; }
          if (change == 1) b.contextSatp ^= 1ULL << 44;
          if (change == 2) b.contextSatp ^= 1ULL;
          if (change == 3) b.sum = !b.sum;
          if (change == 4) b.mxr = !b.mxr;
          if (change == 5) b.privilege = 0;
          if (change == 6) b.cfg = 0x18;
          if (change == 7) b.pmpAddress ^= 8;
          b.settle(); b.check(b.epoch != stale.epoch, "context change did not revoke epoch");
          b.run(stale, {true, false});
          b.run(b.certificate(ram + 32), {change >= 6, false, ram + 32});
      }
      b.report("context_epoch_reauthorization"); }
    { Bench b; b.privilege = 3; b.settle(); b.run(b.certificate(), {true, false});
      b.privilege = 1; b.contextSatp = 0; b.settle(); b.run(b.certificate(), {true, false});
      b.report("machine_and_bare_rejection"); }
    if (PREFETCH_ENABLED) {
        Bench b; b.blockPhysical = b.cycle + 30;
        b.run(b.certificate(ram + 32), {false, false, ram + 32, false, true});
        b.run(b.certificate(ram + 4032), {false, false, ram + 4032, false, false});
        // NAPOT 8-byte current-word permission cannot authorize the next 64-byte line.
        b.pmpAddress = ram >> 2; b.settle();
        b.run(b.certificate(), {false, false, ram, false, false});
        b.pmpAddress = allPmp; b.settle();
        for (unsigned kind = 0; kind < 3; ++kind) {
            Request r; r.prechecked = false; r.virt = true; r.address = va + 64 + kind * 8;
            if (kind == 0) r.write = true;
            if (kind == 1) { r.atomic = true; r.atomicOp = 2; }
            if (kind == 2) r.uncached = true;
            b.run(r, {false, false, ram + 64 + kind * 8, r.uncached, false});
        }
        b.check(b.issued == 6 && b.physicalHolds > 0, "next-line permission/hold coverage missing");
        b.report("next_line_authorization");
    }
    // Legal, same-epoch PA is a trusted certificate payload, not a retranslation query.
    // The backend fixture separately verifies its producer's VA/PA/full-token match.
    { Bench b; b.run(b.certificate(ram + 24576), {false, false, ram + 24576}); b.report("trusted_same_epoch_pa"); }
    std::cout << "PRECHECKED_QUEUE_FLOW_PASS enabled=" << QUEUE_FLOW_ENABLED << "\n"; return 0;
} catch (const std::exception &e) { std::cerr << "PRECHECKED_QUEUE_FLOW_FAIL " << e.what() << "\n"; return 1; } }
