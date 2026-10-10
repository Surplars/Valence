#include "TranslatedResponseFlowGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifndef RESPONSE_FLOW_ENABLED
#define RESPONSE_FLOW_ENABLED 0
#endif
static_assert(RESPONSE_FLOW_ENABLED == 0 || RESPONSE_FLOW_ENABLED == 1);

// Component-only stimulus. Labels describe synthetic request/response pairs;
// this is not a CPU, MMIO-device, translation, cancellation, or side-effect test.
// The oracle uses independent deques and the public decoupled interface only.
static void check(bool condition, const char *reason) {
    if (!condition) throw std::runtime_error(reason);
}
static constexpr uint64_t digestSeed = 1469598103934665603ULL;
static void hash(uint64_t &digest, uint64_t value) {
    digest ^= value;
    digest *= 1099511628211ULL;
}
enum class Kind : unsigned { Load, Store, MmioLoad, MmioStore, Metadata, Count };
struct Request {
    uint64_t address = 0, data = 0;
    uint32_t translationEpoch = 0;
    unsigned atomicOp = 0, size = 0, mask = 0;
    bool atomic = false, write = false, virtualized = false;
    bool precheckedLoad = false, prefetchNextAllowed = false, uncached = false;
    bool operator==(const Request &other) const {
        return address == other.address && data == other.data && translationEpoch == other.translationEpoch &&
               atomicOp == other.atomicOp && size == other.size && mask == other.mask && atomic == other.atomic &&
               write == other.write && virtualized == other.virtualized && precheckedLoad == other.precheckedLoad &&
               prefetchNextAllowed == other.prefetchNextAllowed && uncached == other.uncached;
    }
};
struct Response {
    uint64_t data = 0;
    bool error = false, pageFault = false;
    bool operator==(const Response &other) const {
        return data == other.data && error == other.error && pageFault == other.pageFault;
    }
};
struct Transaction {
    Request request;
    Response response;
    Kind kind;
};
static Transaction transaction(unsigned id, Kind kind, uint64_t data, unsigned faults) {
    Request request;
    const bool mmio = kind == Kind::MmioLoad || kind == Kind::MmioStore;
    request.address = (mmio ? 0x10000000ULL : 0x80200000ULL) + 8ULL * id;
    request.data = 0x9876543210abcdefULL ^ (0x102030405060708ULL * id);
    request.write = kind == Kind::Store || kind == Kind::MmioStore;
    request.size = id % 4;
    request.mask = (1U << (1U << request.size)) - 1;
    request.uncached = mmio;
    if (kind == Kind::Metadata) {
        // Deliberately opaque metadata, including hostile-looking combinations:
        // this buffer must copy every field without authorizing or rewriting it.
        request.address = 0xfedcba9876543210ULL ^ (0x102030405060708ULL * id);
        request.atomic = (id & 1) != 0;
        request.atomicOp = id % 32;
        request.write = (id & 2) != 0;
        request.virtualized = (id & 4) != 0;
        request.precheckedLoad = (id & 8) != 0;
        request.prefetchNextAllowed = (id & 16) != 0;
        request.uncached = (id & 32) != 0;
        request.translationEpoch = 0x89abcdefU ^ (id * 0x1020304U);
        request.mask = (id * 53U) & 255;
    }
    return {request, {data, bool(faults & 1), bool(faults & 2)}, kind};
}
static void hashResponse(uint64_t &digest, unsigned id, const Transaction &transaction, const Response &response) {
    hash(digest, id);
    hash(digest, unsigned(transaction.kind));
    hash(digest, response.data);
    hash(digest, response.error);
    hash(digest, response.pageFault);
}
static std::vector<Transaction> faultMatrix() {
    const std::array<uint64_t, 8> patterns = {
        0, UINT64_MAX, 1, 1ULL << 63, 0xaaaaaaaaaaaaaaaaULL, 0x5555555555555555ULL,
        0x0123456789abcdefULL, 0xfedcba9876543210ULL
    };
    std::vector<Transaction> result;
    for (unsigned kind = 0; kind < 4; ++kind)
        for (unsigned faults = 0; faults < 4; ++faults)
            for (uint64_t data : patterns)
                result.push_back(transaction(unsigned(result.size()), Kind(kind), data, faults));
    return result;
}
static std::vector<Transaction> uniqueStream(unsigned count, bool metadata = false) {
    std::vector<Transaction> result;
    for (unsigned id = 0; id < count; ++id)
        result.push_back(transaction(id, metadata ? Kind::Metadata : Kind(id % 4),
            0xc3a5000000000000ULL | (uint64_t(id) << 16) | uint64_t(id ^ 0x5a5a), (id / 4) % 4));
    return result;
}
struct Options {
    bool dependent = false, patternedStalls = false;
    unsigned holdEveryResponse = 0, blockConsumer = 0, memoryDelay = 1;
};
struct Stats {
    uint64_t cycles = 0, acceptedAtSum = 0, returnedAtSum = 0;
    uint64_t semanticDigest = digestSeed, requestDigest = digestSeed;
    uint64_t firstAccepted = UINT64_MAX, lastAccepted = 0, firstReturned = UINT64_MAX, lastReturned = 0;
    uint64_t minLatency = UINT64_MAX, maxLatency = 0;
    unsigned issued = 0, accepted = 0, returned = 0, peak = 0;
    unsigned inputStalls = 0, outputStalls = 0, requestStalls = 0, requestWhileFull = 0;
    unsigned emptyAccepts = 0, emptyPasses = 0, emptyCaptures = 0, oldPopNewCapture = 0;
    unsigned fullPops = 0, captureAfterFullPop = 0, inputHoldChecks = 0, outputHoldChecks = 0;
    unsigned idleWithOutstanding = 0, idleWithVisibleResponse = 0, drainChecks = 0;
    unsigned heldFaultMask = 0, faultMask = 0, maxReturnStreak = 0;
    std::array<unsigned, unsigned(Kind::Count)> kindCounts{};
};
struct Observation {
    bool inputReady, outputValid, idle;
    Response response;
};
struct Test {
    STranslatedResponseFlowGsim dut;
    std::string injection;
    bool injected = false;

    explicit Test(std::string injection = "") : injection(std::move(injection)) {
        driveRequest(Request{}, false, false);
        dut.set_io$$downstream$$response$$valid(0);
        dut.set_io$$downstream$$response$$bits$$data(0);
        dut.set_io$$downstream$$response$$bits$$error(0);
        dut.set_io$$downstream$$response$$bits$$pageFault(0);
        dut.set_io$$upstream$$response$$ready(0);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
    }
    void driveRequest(const Request &request, bool valid, bool ready) {
        dut.set_io$$upstream$$request$$valid(valid);
        dut.set_io$$downstream$$request$$ready(ready);
        dut.set_io$$upstream$$request$$bits$$atomic(request.atomic);
        dut.set_io$$upstream$$request$$bits$$atomicOp(request.atomicOp);
        dut.set_io$$upstream$$request$$bits$$address(request.address);
        dut.set_io$$upstream$$request$$bits$$write(request.write);
        dut.set_io$$upstream$$request$$bits$$size(request.size);
        dut.set_io$$upstream$$request$$bits$$data(request.data);
        dut.set_io$$upstream$$request$$bits$$mask(request.mask);
        dut.set_io$$upstream$$request$$bits$$virtualized(request.virtualized);
        dut.set_io$$upstream$$request$$bits$$precheckedLoad(request.precheckedLoad);
        dut.set_io$$upstream$$request$$bits$$translationEpoch(request.translationEpoch);
        dut.set_io$$upstream$$request$$bits$$prefetchNextAllowed(request.prefetchNextAllowed);
        dut.set_io$$upstream$$request$$bits$$uncached(request.uncached);
    }
    Request observeRequest() {
        Request request;
        request.atomic = dut.get_io$$downstream$$request$$bits$$atomic();
        request.atomicOp = dut.get_io$$downstream$$request$$bits$$atomicOp();
        request.address = dut.get_io$$downstream$$request$$bits$$address();
        request.write = dut.get_io$$downstream$$request$$bits$$write();
        request.size = dut.get_io$$downstream$$request$$bits$$size();
        request.data = dut.get_io$$downstream$$request$$bits$$data();
        request.mask = dut.get_io$$downstream$$request$$bits$$mask();
        request.virtualized = dut.get_io$$downstream$$request$$bits$$virtualized();
        request.precheckedLoad = dut.get_io$$downstream$$request$$bits$$precheckedLoad();
        request.translationEpoch = dut.get_io$$downstream$$request$$bits$$translationEpoch();
        request.prefetchNextAllowed = dut.get_io$$downstream$$request$$bits$$prefetchNextAllowed();
        request.uncached = dut.get_io$$downstream$$request$$bits$$uncached();
        return request;
    }
    Stats run(const std::vector<Transaction> &transactions, Options options = {}) {
        check(!transactions.empty(), "empty_test_fixture");
        Stats stats;
        struct Pending { unsigned id; uint64_t due; };
        // pending models an ordered synthetic downstream producer, queued owns
        // only accepted buffer inputs, ledger owns accepted requests until return.
        std::deque<Pending> pending;
        std::deque<unsigned> queued, ledger;
        std::vector<uint64_t> acceptedAt(transactions.size());
        std::optional<Request> heldRequest;
        std::optional<Response> heldInput, heldOutput;
        bool requestHeld = false, inputHeld = false, previousFullPop = false;
        unsigned visibleHold = 0, returnStreak = 0, quiet = 0;
        uint64_t expectedDigest = digestSeed;
        for (unsigned id = 0; id < transactions.size(); ++id)
            hashResponse(expectedDigest, id, transactions[id], transactions[id].response);

        for (; stats.cycles < 20000; ++stats.cycles) {
            const uint64_t cycle = stats.cycles;
            const unsigned occupancy = unsigned(queued.size());
            const bool requestValid = stats.issued < transactions.size() &&
                (requestHeld || ((!options.dependent || ledger.empty()) &&
                 (!options.patternedStalls || cycle % 9 != 4)));
            const bool requestReady = !options.patternedStalls || cycle % 5 < 3;
            const Request poison = transaction(unsigned(cycle + 123), Kind::Metadata,
                0xdeadbeefULL, 0).request;
            const Request &request = stats.issued < transactions.size() ? transactions[stats.issued].request : poison;
            const bool inputValid = !pending.empty() && pending.front().due <= cycle &&
                (inputHeld || !options.patternedStalls || cycle % 7 < 5);
            const unsigned sourceId = inputValid ? pending.front().id : 0;
            const Response input = inputValid ? transactions[sourceId].response :
                Response{0xbadc0ffe00000000ULL ^ cycle, bool(cycle & 1), bool(cycle & 2)};
            const bool outputReady = cycle >= options.blockConsumer &&
                (!options.holdEveryResponse || visibleHold >= options.holdEveryResponse) &&
                (!options.patternedStalls || cycle % 11 < 5);
            const bool expectedReady = occupancy < 2;
            const bool expectedValid = occupancy != 0 || (RESPONSE_FLOW_ENABLED && inputValid);
            const unsigned owner = occupancy ? queued.front() : sourceId;
            const bool inputFire = inputValid && expectedReady;
            const bool outputFire = expectedValid && outputReady;
            const bool requestFire = requestValid && requestReady;
            driveRequest(request, requestValid, requestReady);
            dut.set_io$$downstream$$response$$valid(inputValid);
            dut.set_io$$downstream$$response$$bits$$data(input.data);
            dut.set_io$$downstream$$response$$bits$$error(input.error);
            dut.set_io$$downstream$$response$$bits$$pageFault(input.pageFault);
            dut.set_io$$upstream$$response$$ready(outputReady);
            // GSIM step exposes the just-evaluated, pre-edge handshake outputs.
            dut.step();
            Observation actual{bool(dut.get_io$$downstream$$response$$ready()),
                bool(dut.get_io$$upstream$$response$$valid()), bool(dut.get_io$$idle()),
                {uint64_t(dut.get_io$$upstream$$response$$bits$$data()),
                 bool(dut.get_io$$upstream$$response$$bits$$error()),
                 bool(dut.get_io$$upstream$$response$$bits$$pageFault())}};
            const Request actualRequest = observeRequest();
            check(bool(dut.get_io$$upstream$$request$$ready()) == requestReady, "request_ready_passthrough_mismatch");
            check(bool(dut.get_io$$downstream$$request$$valid()) == requestValid, "request_valid_passthrough_mismatch");
            check(actualRequest == request, "request_payload_passthrough_mismatch");
            if (heldRequest) check(requestValid && actualRequest == *heldRequest, "request_stalled_payload_changed");
            heldRequest = requestValid && !requestReady ? std::optional<Request>(actualRequest) : std::nullopt;

            // Negative controls damage observations, never stimulus or expected
            // owners. Each corruption must reach its specific checking branch.
            if (!injected && !injection.empty()) {
                if (injection == "data" && expectedValid) { actual.response.data ^= 1ULL << 37; injected = true; }
                if (injection == "error" && expectedValid) { actual.response.error = !actual.response.error; injected = true; }
                if (injection == "pagefault" && expectedValid) { actual.response.pageFault = !actual.response.pageFault; injected = true; }
                if (injection == "order" && occupancy == 2) { actual.response = transactions[queued[1]].response; injected = true; }
                if (injection == "credit" && occupancy == 2 && outputReady) { actual.inputReady = true; injected = true; }
                if (injection == "drop" && expectedValid) { actual.outputValid = false; injected = true; }
                if (injection == "duplicate" && stats.returned == transactions.size() && !expectedValid) {
                    actual.outputValid = true;
                    actual.response = transactions.back().response;
                    injected = true;
                }
            }
            check(actual.inputReady == expectedReady, "response_credit_mismatch");
            check(actual.idle == (occupancy == 0), "response_idle_occupancy_mismatch");
            if (expectedValid && !actual.outputValid) check(false, "response_valid_missing");
            if (!expectedValid && actual.outputValid) check(false, "response_unowned_duplicate");
            if (expectedValid) {
                check(!ledger.empty() && ledger.front() == owner, "response_owner_ledger_mismatch");
                const Response &expected = transactions[owner].response;
                if (!(actual.response == expected)) {
                    // Recognizable later payloads identify reordering separately
                    // from data-bit damage. Unique negative-control data ensures
                    // these diagnoses cannot alias each other.
                    for (unsigned index = 1; index < ledger.size(); ++index)
                        if (actual.response == transactions[ledger[index]].response)
                            check(false, "response_order_mismatch");
                    check(actual.response.data == expected.data, "response_data_mismatch");
                    check(actual.response.error == expected.error, "response_error_mismatch");
                    check(actual.response.pageFault == expected.pageFault, "response_pagefault_mismatch");
                }
            }
            if (heldOutput) {
                check(actual.outputValid && actual.response == *heldOutput, "response_stalled_payload_changed");
                ++stats.outputHoldChecks;
            }
            if (heldInput) {
                check(inputValid && input == *heldInput, "producer_stalled_payload_changed");
                ++stats.inputHoldChecks;
            }
            heldOutput = expectedValid && !outputReady ? std::optional<Response>(actual.response) : std::nullopt;
            heldInput = inputValid && !expectedReady ? std::optional<Response>(input) : std::nullopt;
            requestHeld = requestValid && !requestReady;
            inputHeld = inputValid && !expectedReady;
            stats.inputStalls += inputHeld;
            stats.outputStalls += expectedValid && !outputReady;
            stats.requestStalls += requestHeld;
            stats.requestWhileFull += occupancy == 2 && requestFire;
            stats.idleWithOutstanding += occupancy == 0 && !ledger.empty();
            stats.idleWithVisibleResponse += occupancy == 0 && expectedValid;
            stats.fullPops += occupancy == 2 && outputFire;
            stats.captureAfterFullPop += previousFullPop && inputFire;
            previousFullPop = occupancy == 2 && outputFire;
            stats.oldPopNewCapture += occupancy != 0 && outputFire && inputFire;
            if (expectedValid && !outputReady) {
                stats.heldFaultMask |= 1U << (unsigned(actual.response.error) | (unsigned(actual.response.pageFault) << 1));
                ++visibleHold;
            }
            if (outputFire) visibleHold = 0;
            if (inputFire) {
                acceptedAt[sourceId] = cycle;
                stats.acceptedAtSum += cycle;
                if (!stats.accepted) stats.firstAccepted = cycle;
                stats.lastAccepted = cycle;
                ++stats.accepted;
                stats.emptyAccepts += occupancy == 0;
                stats.emptyPasses += occupancy == 0 && outputFire;
                stats.emptyCaptures += occupancy == 0 && !outputFire;
            }
            if (outputFire) {
                const uint64_t latency = cycle - acceptedAt[owner];
                stats.minLatency = std::min(stats.minLatency, latency);
                stats.maxLatency = std::max(stats.maxLatency, latency);
                stats.returnedAtSum += cycle;
                if (!stats.returned) stats.firstReturned = cycle;
                stats.lastReturned = cycle;
                ++stats.returned;
                ++stats.kindCounts[unsigned(transactions[owner].kind)];
                stats.faultMask |= 1U << (unsigned(actual.response.error) | (unsigned(actual.response.pageFault) << 1));
                hashResponse(stats.semanticDigest, owner, transactions[owner], actual.response);
            }
            returnStreak = outputFire ? returnStreak + 1 : 0;
            stats.maxReturnStreak = std::max(stats.maxReturnStreak, returnStreak);

            // All decisions above use PRE-EDGE occupancy. An old owner always
            // wins; popping a full queue cannot authorize this edge's enqueue.
            if (outputFire) {
                ledger.pop_front();
                if (occupancy) queued.pop_front();
            }
            if (inputFire) {
                if (!(RESPONSE_FLOW_ENABLED && occupancy == 0 && outputFire)) queued.push_back(sourceId);
                pending.pop_front();
            }
            if (requestFire) {
                pending.push_back({stats.issued, cycle + options.memoryDelay});
                ledger.push_back(stats.issued);
                for (uint64_t value : {request.address, request.data, uint64_t(request.translationEpoch),
                     uint64_t(request.atomicOp), uint64_t(request.size), uint64_t(request.mask),
                     uint64_t(request.atomic), uint64_t(request.write), uint64_t(request.virtualized),
                     uint64_t(request.precheckedLoad), uint64_t(request.prefetchNextAllowed), uint64_t(request.uncached)})
                    hash(stats.requestDigest, value);
                ++stats.issued;
            }
            stats.peak = std::max(stats.peak, unsigned(queued.size()));
            check(queued.size() <= 2, "model_capacity_exceeded");
            check(stats.accepted == stats.returned + queued.size(), "response_conservation_mismatch");
            check(stats.issued == ledger.size() + stats.returned, "request_conservation_mismatch");
            check(ledger.size() == pending.size() + queued.size(), "producer_conservation_mismatch");
            if (stats.returned == transactions.size() && !expectedValid && !inputValid) {
                check(queued.empty() && pending.empty() && ledger.empty() && actual.idle, "response_drain_mismatch");
                ++stats.drainChecks;
                if (++quiet == 4) { ++stats.cycles; break; }
            } else quiet = 0;
        }
        check(stats.drainChecks == 4 && stats.issued == transactions.size() &&
              stats.accepted == transactions.size() && stats.returned == transactions.size(), "response_drain_timeout");
        check(stats.semanticDigest == expectedDigest, "response_semantic_digest_mismatch");
        check(injection.empty(), injected ? "negative_control_not_detected" : "negative_control_not_exercised");
        return stats;
    }
};
static void report(const char *name, const Stats &stats) {
    std::cout << "TRANSLATED_RESPONSE_CASE name=" << name << " flag=" << RESPONSE_FLOW_ENABLED
        << " cycles=" << stats.cycles << " issued=" << stats.issued << " accepted=" << stats.accepted
        << " returned=" << stats.returned << " semantic_digest=" << stats.semanticDigest
        << " request_digest=" << stats.requestDigest << " peak=" << stats.peak
        << " input_stalls=" << stats.inputStalls << " output_stalls=" << stats.outputStalls
        << " request_stalls=" << stats.requestStalls << " request_while_full=" << stats.requestWhileFull
        << " empty_accepts=" << stats.emptyAccepts << " empty_passes=" << stats.emptyPasses
        << " empty_captures=" << stats.emptyCaptures << " old_pop_new_capture=" << stats.oldPopNewCapture
        << " full_pops=" << stats.fullPops << " capture_after_full_pop=" << stats.captureAfterFullPop
        << " input_hold_checks=" << stats.inputHoldChecks << " output_hold_checks=" << stats.outputHoldChecks
        << " idle_outstanding=" << stats.idleWithOutstanding << " idle_visible=" << stats.idleWithVisibleResponse
        << " fault_mask=" << stats.faultMask << " held_fault_mask=" << stats.heldFaultMask
        << " min_latency=" << stats.minLatency << " max_latency=" << stats.maxLatency
        << " latency_sum=" << stats.returnedAtSum - stats.acceptedAtSum
        << " accepted_span=" << stats.lastAccepted - stats.firstAccepted
        << " returned_span=" << stats.lastReturned - stats.firstReturned
        << " longest_ii1=" << stats.maxReturnStreak << " drain_checks=" << stats.drainChecks
        << " loads=" << stats.kindCounts[unsigned(Kind::Load)] << " stores=" << stats.kindCounts[unsigned(Kind::Store)]
        << " mmio_loads=" << stats.kindCounts[unsigned(Kind::MmioLoad)]
        << " mmio_stores=" << stats.kindCounts[unsigned(Kind::MmioStore)]
        << " metadata=" << stats.kindCounts[unsigned(Kind::Metadata)] << '\n';
}
int main(int argc, char **argv) {
    try {
        check(argc <= 2, "invalid_arguments");
        if (argc == 2) {
            const std::string argument = argv[1];
            const std::vector<std::string> controls = {"data", "error", "pagefault", "order", "credit", "drop", "duplicate"};
            std::string mode;
            for (const auto &control : controls) if (argument == "--inject-" + control) mode = control;
            check(!mode.empty(), "invalid_arguments");
            Test test(mode);
            Options options;
            options.blockConsumer = 12;
            test.run(uniqueStream(16), options);
            check(false, "negative_control_not_detected");
        }
        unsigned cases = 0;
        uint64_t accepted = 0, suiteDigest = digestSeed;
        auto emit = [&](const char *name, const Stats &stats) {
            report(name, stats);
            ++cases;
            accepted += stats.accepted;
            hash(suiteDigest, stats.semanticDigest);
        };
        {
            Test test;
            Options options;
            options.dependent = true;
            const auto stats = test.run(faultMatrix(), options);
            check(stats.emptyAccepts == 128 && stats.faultMask == 15, "empty_fault_matrix_coverage_missing");
            check(stats.emptyPasses == (RESPONSE_FLOW_ENABLED ? 128U : 0U), "empty_flow_latency_mismatch");
            check(stats.minLatency == (RESPONSE_FLOW_ENABLED ? 0U : 1U) &&
                  stats.maxLatency == stats.minLatency, "isolated_response_latency_mismatch");
            emit("empty_fault_matrix", stats);
        }
        {
            Test test;
            Options options;
            options.dependent = true;
            options.holdEveryResponse = 3;
            const auto stats = test.run(faultMatrix(), options);
            check(stats.emptyCaptures == 128 && stats.emptyPasses == 0 && stats.heldFaultMask == 15 &&
                  stats.outputHoldChecks >= 128 * 3, "held_fault_matrix_coverage_missing");
            emit("held_fault_matrix", stats);
        }
        {
            Test test;
            const auto stats = test.run(uniqueStream(96));
            check(stats.lastAccepted - stats.firstAccepted == 95 && stats.lastReturned - stats.firstReturned == 95 &&
                  stats.maxReturnStreak == 96, "response_ii1_coverage_missing");
            check(stats.peak == (RESPONSE_FLOW_ENABLED ? 0U : 1U), "stream_occupancy_mismatch");
            emit("stream_ii1", stats);
        }
        {
            Test test;
            Options options;
            options.blockConsumer = 12;
            const auto stats = test.run(uniqueStream(48), options);
            check(stats.peak == 2 && stats.fullPops && stats.captureAfterFullPop && stats.oldPopNewCapture &&
                  stats.inputHoldChecks && stats.requestWhileFull, "capacity_full_pop_turnover_coverage_missing");
            emit("capacity_full_pop_turnover", stats);
        }
        {
            Test test;
            Options options;
            options.patternedStalls = true;
            options.blockConsumer = 24;
            const auto stats = test.run(uniqueStream(192), options);
            check(stats.peak == 2 && stats.fullPops && stats.oldPopNewCapture && stats.inputStalls &&
                  stats.outputStalls && stats.requestStalls && stats.faultMask == 15 && stats.heldFaultMask == 15,
                  "mixed_stall_coverage_missing");
            emit("mixed_load_store_mmio_stalls", stats);
        }
        {
            Test test;
            Options options;
            options.patternedStalls = true;
            options.blockConsumer = 16;
            options.memoryDelay = 7;
            const auto stats = test.run(uniqueStream(64, true), options);
            check(stats.idleWithOutstanding >= 6 && stats.requestStalls && stats.requestWhileFull &&
                  stats.kindCounts[unsigned(Kind::Metadata)] == 64, "request_metadata_coverage_missing");
            emit("request_metadata_transparent", stats);
        }
        std::cout << "TRANSLATED_RESPONSE_FLOW_PASS flag=" << RESPONSE_FLOW_ENABLED << " cases=" << cases
            << " accepted=" << accepted << " returned=" << accepted << " semantic_digest=" << suiteDigest
            << " capacity=2 request_fields=12 fault_combinations=4 data_patterns=8 component_only=1\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "TRANSLATED_RESPONSE_FLOW_FAIL reason=" << error.what() << '\n';
        return 1;
    }
}
