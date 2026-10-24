#include "FetchRequestContextGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string_view>

static void check(bool ok, const char *why) {
    if (!ok) throw std::runtime_error(why);
}

struct Request {
    uint64_t address;
    unsigned mask, privilege, serial;
};

struct Reply {
    uint64_t data;
    unsigned error, page, due;
};

// Architectural privilege encodings and traffic are host-owned, not read from
// DUT definitions. Each three-request group deliberately reuses PA/mask for U/S/M.
static Request request(unsigned serial) {
    constexpr std::array<unsigned, 3> privileges{0, 1, 3};
    constexpr std::array<uint64_t, 4> bases{
        UINT64_C(0x80000000), UINT64_C(0x100000000),
        UINT64_C(0x0080000000000000), UINT64_C(0x0000ffff00000000)};
    const unsigned group = serial / 3;
    return {bases[(group / 4) % bases.size()] + UINT64_C(0xff8) + 8 * (group % 13),
        group % 4, privileges[serial % privileges.size()], serial};
}

static Reply reply(const Request &r, unsigned due) {
    return {r.address ^ UINT64_C(0x8142246881422468) ^ (uint64_t(r.privilege) << 59) ^
        (uint64_t(r.serial) << 32) ^ (uint64_t(r.mask) << 17), r.serial % 4, (r.serial / 4) % 4, due};
}

static void checkRequest(const Request &actual, const Request &expected, unsigned cycle, const char *where) {
    if (actual.address != expected.address || actual.mask != expected.mask || actual.privilege != expected.privilege) {
        std::ostringstream why;
        why << "independent accepted request-context oracle mismatch: " << where << " cycle=" << cycle
            << " accepted_id=" << expected.serial << " expected_privilege=" << expected.privilege
            << " observed_privilege=" << actual.privilege << " expected_mask=" << expected.mask
            << " observed_mask=" << actual.mask << std::hex << " expected_pa=0x" << expected.address
            << " observed_pa=0x" << actual.address;
        throw std::runtime_error(why.str());
    }
}

int main(int argc, char **argv) {
    try {
        check(argc == 1 || (argc == 2 && std::string_view(argv[1]) == "--inject-context"),
            "usage: fetch-context-buffer [--inject-context]");
        const bool inject = argc == 2;
        SFetchRequestContextGsim d;
        d.set_io$$requestValid(0);
        d.set_io$$requestAddress(0);
        d.set_io$$requestMask(0);
        d.set_io$$requestPrivilege(0);
        d.set_io$$downstreamReady(0);
        d.set_io$$responseReady(0);
        d.set_io$$responseValid(0);
        d.set_io$$responseData(0);
        d.set_io$$responseError(0);
        d.set_io$$responsePageFault(0);
        d.set_reset(1);
        d.step();
        d.step();
        d.set_reset(0);
        const bool flow = d.get_io$$configuredFlowThrough();
        const bool independent = d.get_io$$configuredIndependentCapture();
        check(!independent || flow, "invalid fixture configuration");
        const char *mode = independent ? "independent" : flow ? "flow" : "registered";

        // This ledger contains exactly the host offers accepted by the upstream
        // handshake, never payload learned from downstream DUT observations.
        std::deque<Request> acceptedRequests;
        std::deque<Reply> replies;
        std::optional<Request> offered, held;
        std::array<unsigned, 4> acceptedPrivilege{}, forwardedPrivilege{};
        unsigned accepted = 0, forwarded = 0, completed = 0, peak = 0;
        unsigned heldCycles = 0, crossContextHeld = 0, inputStalls = 0, fullCycles = 0;
        unsigned turnover = 0, contextTurnover = 0, fullPopNoBorrow = 0;
        unsigned emptyBypass = 0, emptyCapture = 0, registeredDelay = 0, zeroMask = 0;
        unsigned responseStalls = 0, responseFaults = 0, immediate = 0, drain = 0;
        unsigned stream = 0, longestStream = 0;
        bool injected = false;
        for (unsigned cycle = 0; cycle < 10000; ++cycle) {
            // Directed fill/hold, full pop, continuous traffic, empty gap, and
            // continuous empty flow precede a deterministic congestion tail.
            const bool supply = cycle < 80 || (cycle >= 96 && (cycle < 160 || cycle % 19 < 13));
            if (!offered && accepted < 256 && supply) offered = request(accepted);
            const bool downstreamReady = replies.size() < 8 && cycle >= 16 &&
                (cycle < 160 || (cycle % 17 >= 5 && cycle % 31 >= 3));
            const bool cpuReady = cycle >= 40 && (cycle < 160 || cycle % 11 >= 3);
            const unsigned occupancy = unsigned(acceptedRequests.size());
            const bool inputReady = occupancy < 2;
            const bool outputValid = occupancy != 0 || (flow && offered.has_value());
            const std::optional<Request> expected = occupancy != 0
                ? std::optional<Request>(acceptedRequests.front()) : offered;
            const bool inputFire = offered.has_value() && inputReady;
            const bool outputFire = outputValid && downstreamReady;
            const bool instant = replies.empty() && outputFire && cycle >= 96 && cycle < 160;
            std::optional<Reply> returning;
            if (!replies.empty() && replies.front().due <= cycle) returning = replies.front();
            else if (instant) returning = reply(*expected, cycle);
            // Invalid inputs still change, so saved context cannot accidentally
            // pass by following an idle producer's live sideband.
            const Request driven = offered.value_or(request(256 + cycle));
            d.set_io$$requestValid(offered.has_value());
            d.set_io$$requestAddress(driven.address);
            d.set_io$$requestMask(driven.mask);
            d.set_io$$requestPrivilege(driven.privilege);
            d.set_io$$downstreamReady(downstreamReady);
            d.set_io$$responseReady(cpuReady);
            d.set_io$$responseValid(returning.has_value());
            d.set_io$$responseData(returning ? returning->data : 0);
            d.set_io$$responseError(returning ? returning->error : 0);
            d.set_io$$responsePageFault(returning ? returning->page : 0);
            // GSIM exposes this cycle's pre-edge handshake outputs after step.
            // Update the host's accepted ledger only after checking those outputs.
            d.step();
            check(bool(d.get_io$$requestReady()) == inputReady, "occupancy-only request credit mismatch");
            check(bool(d.get_io$$downstreamValid()) == outputValid, "request flow/registered valid mismatch");
            check(bool(d.get_io$$configuredFlowThrough()) == flow &&
                bool(d.get_io$$configuredIndependentCapture()) == independent, "fixture mode changed");
            Request actual{d.get_io$$downstreamAddress(), unsigned(d.get_io$$downstreamMask()),
                unsigned(d.get_io$$downstreamPrivilege()), 0};
            if (outputValid) {
                check(expected.has_value(), "independent output expectation missing");
                checkRequest(actual, *expected, cycle, "offer");
                if (inject && !injected && held && occupancy != 0) {
                    // Mutate the observation only, not the independent ledger or
                    // driven request. A nonzero exit without both messages below
                    // is not an accepted negative-control result.
                    actual.privilege = expected->privilege == 3 ? 0 : 3;
                    injected = true;
                    std::cerr << "INJECT context cycle=" << cycle << " accepted_id=" << expected->serial
                        << " expected_privilege=" << expected->privilege
                        << " observed_privilege=" << actual.privilege << '\n';
                    checkRequest(actual, *expected, cycle, "injected context observation");
                }
            }
            if (held) {
                check(outputValid, "held request valid was dropped");
                checkRequest(actual, *held, cycle, "held stability");
                ++heldCycles;
                crossContextHeld += offered && offered->privilege != held->privilege && !downstreamReady;
            }
            held = outputValid && !downstreamReady ? expected : std::nullopt;
            fullCycles += occupancy == 2;
            fullPopNoBorrow += occupancy == 2 && outputFire && offered.has_value();
            inputStalls += offered.has_value() && !inputReady;
            turnover += inputFire && outputFire && occupancy != 0;
            contextTurnover += inputFire && outputFire && occupancy != 0 &&
                offered->privilege != expected->privilege;
            emptyBypass += occupancy == 0 && inputFire && outputFire;
            emptyCapture += occupancy == 0 && inputFire && !outputFire;
            registeredDelay += occupancy == 0 && inputFire && !outputValid;
            if (inputFire) {
                acceptedRequests.push_back(*offered);
                ++acceptedPrivilege[offered->privilege];
                zeroMask += offered->mask == 0;
                ++accepted;
                longestStream = std::max(longestStream, ++stream);
            } else {
                stream = 0;
            }
            if (outputFire) {
                check(!acceptedRequests.empty(), "downstream forwarded an unaccepted request");
                const Request sent = acceptedRequests.front();
                checkRequest(actual, sent, cycle, "accepted dequeue");
                acceptedRequests.pop_front();
                replies.push_back(reply(sent, cycle + (instant ? 0 : 1 + sent.serial % 7)));
                ++forwardedPrivilege[sent.privilege];
                ++forwarded;
            }
            if (inputFire) offered.reset();
            check(bool(d.get_io$$downstreamResponseReady()) == cpuReady, "response backpressure changed");
            check(bool(d.get_io$$upstreamResponseValid()) == returning.has_value(), "response latency changed");
            if (returning) {
                check(!replies.empty(), "response has no independently forwarded request");
                const Reply &want = replies.front();
                check(d.get_io$$upstreamResponseData() == want.data &&
                    d.get_io$$upstreamResponseError() == want.error &&
                    d.get_io$$upstreamResponsePageFault() == want.page, "independent response payload/fault mismatch");
                responseStalls += !cpuReady;
                immediate += instant;
                if (cpuReady) {
                    responseFaults += want.error != 0 || want.page != 0;
                    replies.pop_front();
                    ++completed;
                }
            }
            peak = std::max(peak, unsigned(acceptedRequests.size()));
            check(acceptedRequests.size() <= 2, "accepted request capacity exceeded");
            check(accepted - forwarded == acceptedRequests.size(), "accepted request accounting mismatch");
            check(forwarded - completed == replies.size(), "forwarded response accounting mismatch");
            if (completed == 256 && ++drain == 8) break;
        }
        check(!inject, "context injection did not reach the independent mismatch check");
        check(accepted == 256 && forwarded == 256 && completed == 256 && drain == 8 &&
            acceptedRequests.empty() && replies.empty() && !offered && !held, "request-context drain incomplete");
        check(acceptedPrivilege == forwardedPrivilege && acceptedPrivilege[0] && acceptedPrivilege[1] &&
            acceptedPrivilege[3] && !acceptedPrivilege[2], "mixed U/S/M privilege coverage incomplete");
        check(peak == 2 && fullCycles && heldCycles && crossContextHeld && inputStalls && turnover &&
            contextTurnover && fullPopNoBorrow && emptyCapture && zeroMask && responseStalls &&
            responseFaults && immediate && longestStream > 20, "request-context transport coverage incomplete");
        check(flow ? emptyBypass != 0 && registeredDelay == 0 : emptyBypass == 0 && registeredDelay != 0,
            "empty bypass/registered latency coverage incomplete");
        std::cout << "PASS FETCH_REQUEST_CONTEXT_BUFFER mode=" << mode << " accepted=" << accepted
            << " forwarded=" << forwarded << " completed=" << completed << " U=" << acceptedPrivilege[0]
            << " S=" << acceptedPrivilege[1] << " M=" << acceptedPrivilege[3] << " max_queued=" << peak
            << " held=" << heldCycles << " cross_context_held=" << crossContextHeld << " full=" << fullCycles
            << " input_stalls=" << inputStalls << " turnover=" << turnover << " context_turnover=" << contextTurnover
            << " full_pop_no_borrow=" << fullPopNoBorrow << " empty_bypass=" << emptyBypass
            << " empty_capture=" << emptyCapture << " registered_delay=" << registeredDelay
            << " zero_mask=" << zeroMask << " response_stalls=" << responseStalls
            << " response_faults=" << responseFaults << " immediate=" << immediate
            << " longest_stream=" << longestStream << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << e.what() << '\n';
        return 1;
    }
}
