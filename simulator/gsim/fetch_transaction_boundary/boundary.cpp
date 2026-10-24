#include "FetchTransactionBoundaryGsim.h"
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>

#ifndef BOUNDARY_TOKEN_BITS
#define BOUNDARY_TOKEN_BITS 64
#endif
static_assert(BOUNDARY_TOKEN_BITS > 0 && BOUNDARY_TOKEN_BITS <= 64);
static constexpr uint64_t tokenMask = UINT64_MAX >> (64 - BOUNDARY_TOKEN_BITS);
using Dut = SFetchTransactionBoundaryGsim;
static void check(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error("FETCH_BOUNDARY_ORACLE " + message);
}
struct Context {
    uint64_t address, satp;
    unsigned mask, privilege;
    bool sum, mxr;
};
static Context context(unsigned n) {
    return {UINT64_C(0x40000000) + 8 * n, (uint64_t(n & 3 ? 8 : 0) << 60) |
        (uint64_t(17 + n) << 44) | (0x1234 + n), n & 3, n % 4, bool(n & 1), bool(n & 2)};
}
struct Owner {
    Context context;
    uint64_t token, due, data;
    unsigned errors, pages;
};
static uint64_t payload(const Context &c) { return (c.address * 173) ^ c.satp ^ (uint64_t(c.mask) << 37); }

int main(int argc, char **argv) {
    try {
        const std::string mode = argc == 2 ? argv[1] : "";
        check(argc <= 2 && (mode.empty() || mode == "--wrong-generation" || mode == "--duplicate-result" ||
            mode == "--inject-held-data" || mode == "--inject-turnover-context"), "unknown argument");
        Dut d;
        d.set_io$$requestValid(0); d.set_io$$address(0); d.set_io$$mask(0); d.set_io$$satp(0);
        d.set_io$$sum(0); d.set_io$$mxr(0); d.set_io$$privilege(3); d.set_io$$responseReady(0);
        d.set_io$$commandReady(0); d.set_io$$resultValid(0); d.set_io$$resultToken(0);
        d.set_io$$resultData(0); d.set_io$$resultErrors(0); d.set_io$$resultPages(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        std::optional<Owner> owner;
        using Offered = std::tuple<uint64_t, uint64_t, uint64_t, unsigned, unsigned, bool, bool>;
        std::optional<Offered> heldCommand;
        uint64_t nextToken = 0, lastToken = 0;
        unsigned accepted = 0, completed = 0, simultaneous = 0, resultHeld = 0, commandHeld = 0;
        unsigned noCredit = 0, idleCycles = 0, masks[4] = {}, contexts[4] = {}, latencies[4] = {};
        const unsigned delays[] = {1, 2, 7, 17};
        unsigned wraps = 0, releaseBlocked = 0;
        const unsigned limit = mode == "--duplicate-result" ? 1 : 256;
        bool injected = false, finished = false;
        for (uint64_t cycle = 0; cycle < 10000; ++cycle) {
            const auto request = context(accepted);
            const bool valid = accepted < limit;
            const bool ready = cycle % 5 != 2;
            const bool responseReady = cycle % 13 >= 5;
            const bool duplicate = mode == "--duplicate-result" && completed == 1 && !owner;
            const bool resultValid = duplicate || (owner && cycle >= owner->due);
            uint64_t resultToken = owner ? owner->token : lastToken;
            uint64_t resultData = owner ? owner->data : 0;
            unsigned errors = owner ? owner->errors : 0, pages = owner ? owner->pages : 0;
            if (resultValid && mode == "--wrong-generation") {
                std::cerr << "INJECT wrong-generation\n"; resultToken ^= 1;
            }
            if (duplicate) std::cerr << "INJECT duplicate-result\n";
            const bool matches = owner && resultToken == owner->token;
            const bool releasing = resultValid && matches && responseReady;
            const bool credit = !owner || releasing;
            const bool take = valid && ready && credit;
            if (resultValid && !responseReady && mode == "--inject-held-data") {
                std::cerr << "INJECT held-data\n"; resultData ^= 4; injected = true;
            }
            d.set_io$$requestValid(valid); d.set_io$$address(request.address); d.set_io$$mask(request.mask);
            d.set_io$$satp(request.satp); d.set_io$$sum(request.sum); d.set_io$$mxr(request.mxr);
            d.set_io$$privilege(request.privilege); d.set_io$$responseReady(responseReady);
            d.set_io$$commandReady(ready); d.set_io$$resultValid(resultValid); d.set_io$$resultToken(resultToken);
            d.set_io$$resultData(resultData); d.set_io$$resultErrors(errors); d.set_io$$resultPages(pages);
            d.step();
            // These two are intentional bad engine inputs. The production route
            // must assert before this independent model can accept the event.
            check(!duplicate, "duplicate result input was not rejected by hardware");
            check(!(resultValid && mode == "--wrong-generation"), "wrong generation input was not rejected by hardware");
            check(bool(d.get_io$$idle()) == !owner, "idle differs from outstanding owner history");
            check(bool(d.get_io$$requestReady()) == (ready && credit) &&
                bool(d.get_io$$commandValid()) == (valid && credit), "request/command credit handshake");
            check(bool(d.get_io$$responseValid()) == (resultValid && matches) &&
                bool(d.get_io$$resultReady()) == (matches && responseReady), "result/public response handshake");
            auto commandSatp = d.get_io$$commandSatp();
            if (take && releasing && mode == "--inject-turnover-context") {
                std::cerr << "INJECT turnover-context\n"; commandSatp ^= 1; injected = true;
            }
            const Offered observed{d.get_io$$commandToken(), d.get_io$$commandAddress(), commandSatp,
                unsigned(d.get_io$$commandMask()), unsigned(d.get_io$$commandPrivilege()),
                bool(d.get_io$$commandSum()), bool(d.get_io$$commandMxr())};
            if (d.get_io$$commandValid()) {
                const Offered expected{nextToken, request.address, request.satp, request.mask,
                    request.privilege, request.sum, request.mxr};
                check(observed == expected, "accepted/offered token or atomic context mismatch");
                check(!heldCommand || *heldCommand == observed, "held command changed token/context");
                if (!ready) { heldCommand = observed; ++commandHeld; } else heldCommand.reset();
            } else check(!heldCommand, "held command valid withdrawn");
            if (resultValid) {
                check(owner.has_value(), "unowned result");
                check(d.get_io$$responseData() == owner->data && d.get_io$$responseErrors() == owner->errors &&
                    d.get_io$$responsePages() == owner->pages, "held/returned payload or fault metadata changed");
                resultHeld += !responseReady;
            }
            releaseBlocked += releasing && valid && !ready;
            noCredit += valid && !credit;
            idleCycles += !owner;
            if (releasing) { lastToken = owner->token; owner.reset(); ++completed; }
            if (take) {
                check(!owner, "second transaction overwrote live context");
                owner = Owner{request, nextToken, cycle + delays[accepted % 4], payload(request),
                    unsigned((accepted / 4) & 3), unsigned((accepted / 16) & 3)};
                nextToken = (nextToken + 1) & tokenMask; wraps += nextToken == 0;
                ++latencies[accepted % 4]; ++masks[request.mask]; ++contexts[request.privilege]; ++accepted;
                simultaneous += releasing;
            }
            if (completed == limit && mode != "--duplicate-result" && !owner && cycle % 13 == 12) {
                finished = true; break;
            }
        }
        check(finished && accepted == limit && completed == limit && !owner && !heldCommand,
            "bounded run did not drain exactly once");
        check(simultaneous > 100 && resultHeld > 100 && commandHeld > 20 && noCredit > 100 && idleCycles > 10 && releaseBlocked > 10,
            "turnover/backpressure/credit coverage missing");
        for (unsigned i = 0; i < 4; ++i)
            check(masks[i] > 20 && contexts[i] > 20 && latencies[i] > 20, "mask/context/latency coverage missing");
        if (BOUNDARY_TOKEN_BITS == 2) check(wraps == 64, "small-tag generation wrap coverage missing");
        check(mode.empty() && !injected, "requested negative did not reach witness");
        std::cout << "PASS FETCH_TRANSACTION_BOUNDARY accepted=" << accepted << " completed=" << completed
                  << " simultaneous=" << simultaneous << " result_held=" << resultHeld
                  << " command_held=" << commandHeld << " no_credit=" << noCredit
                  << " release_blocked=" << releaseBlocked << " token_bits=" << BOUNDARY_TOKEN_BITS << " wraps=" << wraps
                  << " latency1=" << latencies[0] << " latency2=" << latencies[1]
                  << " latency7=" << latencies[2] << " latency17=" << latencies[3] << '\n';
        return 0;
    } catch (const std::exception &error) { std::cerr << error.what() << '\n'; return 1; }
}
