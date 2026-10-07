#include "DataTimingGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef REGISTERED_PAYLOAD
#define REGISTERED_PAYLOAD 0
#endif

static void check(bool v, const char *m) { if (!v) throw std::runtime_error(m); }
struct Request {
    uint64_t address, data;
    unsigned size, mask, op;
    bool write, atomic, virtualized, uncached;
    bool operator==(const Request &) const = default;
};
struct Reply {
    uint64_t data;
    bool error, page;
    unsigned due;
};
static Request downstream(SDataTimingGsim &d) {
    return {d.get_io$$downstream$$request$$bits$$address(), d.get_io$$downstream$$request$$bits$$data(),
        unsigned(d.get_io$$downstream$$request$$bits$$size()), unsigned(d.get_io$$downstream$$request$$bits$$mask()),
        unsigned(d.get_io$$downstream$$request$$bits$$atomicOp()), bool(d.get_io$$downstream$$request$$bits$$write()),
        bool(d.get_io$$downstream$$request$$bits$$atomic()), bool(d.get_io$$downstream$$request$$bits$$virtualized()),
        bool(d.get_io$$downstream$$request$$bits$$uncached())};
}
int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SDataTimingGsim d;
    std::mt19937_64 rng(0x100dd20261001ULL);
    unsigned accepted = 0, delivered = 0, completed = 0, bypass = 0, faults = 0, registeredCuts = 0;
    unsigned requestPeak = 0, responsePeak = 0, stream = 0, maxStream = 0, readyIsolation = 0;
    unsigned directedRegisteredCuts = 0;
    auto reset = [&] {
        d.set_io$$upstream$$request$$valid(0); d.set_io$$upstream$$response$$ready(0);
        d.set_io$$downstream$$request$$ready(0); d.set_io$$downstream$$response$$valid(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    };
    reset();
    // Three independent reset/drain epochs. Sustained streams and long stalls are
    // deliberate, rather than relying on random tests to hit queue saturation.
    for (unsigned epoch = 0; epoch < 3; ++epoch) {
        std::deque<Request> pending;
        std::deque<Reply> manager, expected;
        std::optional<Request> heldRequest;
        std::optional<Reply> heldReply;
        Request request{};
        bool offer = false;
        unsigned occupancy = 0;
        const unsigned duration = epoch == 2 ? 1000 : 20000;
        for (unsigned cycle = 0; cycle < duration || offer || !pending.empty() || !expected.empty(); ++cycle) {
            check(cycle < 24000, "data timing drain timeout");
            if (!offer && cycle < duration) {
                request = {rng(), rng(), unsigned(rng() % 4), unsigned(rng() % 256), unsigned(rng() % 32),
                    bool(rng() & 1), bool(rng() & 1), bool(rng() & 1), bool(rng() & 1)};
                offer = true;
            }
            const bool requestReady = manager.size() < 16 &&
                (epoch == 2 || (cycle < 150 ? cycle >= 20 : rng() % 4 != 0));
            const bool cpuReady = epoch == 2 ||
                (cycle < 150 ? cycle >= 40 : (cycle % 200 >= 30 && rng() % 3 != 0));
            std::optional<Reply> returning;
            if (!manager.empty() && manager.front().due <= cycle) returning = manager.front();
            d.set_io$$upstream$$request$$valid(offer);
            d.set_io$$upstream$$request$$bits$$address(request.address);
            d.set_io$$upstream$$request$$bits$$data(request.data);
            d.set_io$$upstream$$request$$bits$$size(request.size);
            d.set_io$$upstream$$request$$bits$$mask(request.mask);
            d.set_io$$upstream$$request$$bits$$atomicOp(request.op);
            d.set_io$$upstream$$request$$bits$$write(request.write);
            d.set_io$$upstream$$request$$bits$$atomic(request.atomic);
            d.set_io$$upstream$$request$$bits$$virtualized(request.virtualized);
            d.set_io$$upstream$$request$$bits$$uncached(request.uncached);
            d.set_io$$upstream$$response$$ready(cpuReady);
            d.set_io$$downstream$$request$$ready(requestReady);
            d.set_io$$downstream$$response$$valid(bool(returning));
            d.set_io$$downstream$$response$$bits$$data(returning ? returning->data : 0);
            d.set_io$$downstream$$response$$bits$$error(returning && returning->error);
            d.set_io$$downstream$$response$$bits$$pageFault(returning && returning->page);
            d.step();
            // These readiness checks are an independent capacity model. In
            // particular a full queue cannot borrow same-cycle dequeue credit.
            check(bool(d.get_io$$upstream$$request$$ready()) == (pending.size() < 2), "request ready credit mismatch");
            check(bool(d.get_io$$downstream$$response$$ready()) == (occupancy < 2), "response ready credit mismatch");
            if (!cpuReady && occupancy < 2) ++readyIsolation;
            const bool requestValid = d.get_io$$downstream$$request$$valid();
            const Request actualRequest = downstream(d);
            if (heldRequest) check(requestValid && actualRequest == *heldRequest, "held data request changed");
            heldRequest = requestValid && !requestReady ? std::optional<Request>(actualRequest) : std::nullopt;
            const bool responseValid = d.get_io$$upstream$$response$$valid();
            if (REGISTERED_PAYLOAD)
                check(responseValid == (occupancy != 0), "registered response leaked an empty-queue payload");
            Reply actual{d.get_io$$upstream$$response$$bits$$data(), bool(d.get_io$$upstream$$response$$bits$$error()),
                bool(d.get_io$$upstream$$response$$bits$$pageFault()), 0};
            if (heldReply) check(responseValid && actual.data == heldReply->data && actual.error == heldReply->error &&
                actual.page == heldReply->page, "held data response changed");
            heldReply = responseValid && !cpuReady ? std::optional<Reply>(actual) : std::nullopt;
            if (responseValid) {
                check(!expected.empty(), "unsolicited data response");
                if (inject) { actual.data ^= 1; inject = false; }
                const Reply &want = expected.front();
                check(actual.data == want.data && actual.error == want.error && actual.page == want.page,
                    "data response oracle mismatch");
                if (cpuReady) { expected.pop_front(); ++completed; }
            }
            const bool responseIn = returning && d.get_io$$downstream$$response$$ready();
            const bool responseOut = responseValid && cpuReady;
            if (returning && occupancy == 0 && cpuReady) {
                if (REGISTERED_PAYLOAD) {
                    check(responseIn && !responseOut, "registered response did not hold its mandatory cycle");
                    ++registeredCuts;
                } else {
                    check(responseIn && responseOut, "empty response queue added a mandatory cycle"); ++bypass;
                }
            }
            occupancy += unsigned(responseIn); occupancy -= unsigned(responseOut);
            responsePeak = std::max(responsePeak, occupancy);
            if (responseIn) manager.pop_front();
            if (requestValid && requestReady) {
                check(!pending.empty() && actualRequest == pending.front(), "data request oracle mismatch");
                pending.pop_front(); ++delivered;
                Reply reply{rng(), rng() % 7 == 0, rng() % 11 == 0,
                    cycle + unsigned(cycle < 150 ? 1 : 1 + rng() % 9)};
                // Include both access and page faults; no normalization of one flag into the other.
                faults += reply.error || reply.page;
                manager.push_back(reply); expected.push_back(reply);
            }
            if (offer && d.get_io$$upstream$$request$$ready()) {
                pending.push_back(request); offer = false; ++accepted;
                maxStream = std::max(maxStream, ++stream);
            } else stream = 0;
            requestPeak = std::max(requestPeak, unsigned(pending.size()));
            check(pending.size() <= 2 && occupancy <= 2, "data timing capacity exceeded");
        }
        check(manager.empty() && occupancy == 0, "response drain incomplete");
        reset(); d.step();
        check(!d.get_io$$downstream$$request$$valid() && !d.get_io$$upstream$$response$$valid(), "stale reset transaction");
    }
    if (REGISTERED_PAYLOAD) {
        // Saturated traffic naturally leaves one queued reply, so random streams
        // rarely expose the empty boundary. Add isolated LEGAL request/reply
        // pairs instead of weakening the minimum register-cut coverage gate.
        for (unsigned n = 0; n < 200; ++n) {
            const uint64_t address = 0x80010000ULL + n * 8;
            const uint64_t data = (uint64_t(n) + 1) * 0x910100000100001ULL;
            const bool error = n % 7 == 0, page = n % 11 == 0;
            d.set_io$$upstream$$request$$valid(1);
            d.set_io$$upstream$$request$$bits$$address(address);
            d.set_io$$upstream$$request$$bits$$data(0);
            d.set_io$$upstream$$request$$bits$$size(3);
            d.set_io$$upstream$$request$$bits$$mask(255);
            d.set_io$$upstream$$request$$bits$$atomicOp(0);
            d.set_io$$upstream$$request$$bits$$write(0);
            d.set_io$$upstream$$request$$bits$$atomic(0);
            d.set_io$$upstream$$request$$bits$$virtualized(0);
            d.set_io$$upstream$$request$$bits$$uncached(0);
            d.set_io$$upstream$$response$$ready(1);
            d.set_io$$downstream$$request$$ready(1);
            d.set_io$$downstream$$response$$valid(0); d.step();
            check(d.get_io$$upstream$$request$$ready() && !d.get_io$$downstream$$request$$valid(),
                "isolated request did not enter its register"); ++accepted;
            d.set_io$$upstream$$request$$valid(0); d.step();
            check(d.get_io$$downstream$$request$$valid() &&
                d.get_io$$downstream$$request$$bits$$address() == address, "isolated request owner mismatch");
            ++delivered;
            d.set_io$$downstream$$response$$valid(1);
            d.set_io$$downstream$$response$$bits$$data(data);
            d.set_io$$downstream$$response$$bits$$error(error);
            d.set_io$$downstream$$response$$bits$$pageFault(page); d.step();
            check(d.get_io$$downstream$$response$$ready() && !d.get_io$$upstream$$response$$valid(),
                "isolated registered response flowed through");
            ++registeredCuts; ++directedRegisteredCuts; faults += error || page;
            d.set_io$$downstream$$response$$valid(0);
            d.set_io$$downstream$$response$$bits$$data(data ^ 0xdeadbeef12345678ULL);
            d.set_io$$downstream$$response$$bits$$error(!error);
            d.set_io$$downstream$$response$$bits$$pageFault(!page);
            auto held = [&] {
                check(d.get_io$$upstream$$response$$valid() &&
                    d.get_io$$upstream$$response$$bits$$data() == data &&
                    bool(d.get_io$$upstream$$response$$bits$$error()) == error &&
                    bool(d.get_io$$upstream$$response$$bits$$pageFault()) == page,
                    "isolated registered payload changed with its invalid input");
            };
            d.set_io$$upstream$$response$$ready(0); d.step(); held();
            check(d.get_io$$downstream$$response$$ready(), "isolated response ready followed CPU backpressure");
            ++readyIsolation;
            d.set_io$$upstream$$response$$ready(1); d.step(); held(); ++completed;
            d.step();
            check(!d.get_io$$upstream$$response$$valid(), "isolated response duplicated after dequeue");
        }
    }
    std::cout << "GSIM data timing coverage: requests=" << accepted << " delivered=" << delivered
        << " completed=" << completed << " requestCredits=" << requestPeak
        << " responseCredits=" << responsePeak << " stream=" << maxStream << " flowReturns=" << bypass
        << " registeredCuts=" << registeredCuts
        << " directedRegisteredCuts=" << directedRegisteredCuts
        << " faultReturns=" << faults << " readyIsolation=" << readyIsolation << " resetEpochs=3\n";
    check(accepted == delivered && delivered == completed && requestPeak == 2 && responsePeak == 2 &&
        maxStream > 80 && (REGISTERED_PAYLOAD ? registeredCuts > 100 && bypass == 0 : bypass > 100) &&
        faults > 100 && readyIsolation > 100, "data timing coverage");
    std::cout << "GSIM data timing: PASS\n";
} catch (const std::exception &e) { std::cerr << "GSIM data timing: FAIL " << e.what() << '\n'; return 1; } }
