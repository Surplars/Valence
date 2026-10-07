#include "InstructionRequestGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef PACKET_WORDS
#define PACKET_WORDS 2
#endif
#ifndef FLOW_THROUGH
#define FLOW_THROUGH 0
#endif
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
struct Request {
    uint64_t address;
    unsigned mask;
    bool operator==(const Request &) const = default;
};
struct Reply {
    uint64_t low, high;
    unsigned error, page, due;
};
static Reply reply(const Request &r, unsigned due) {
    constexpr unsigned mask = (1U << PACKET_WORDS) - 1;
    return {r.address ^ 0x8142246881422468ULL, ~r.address ^ (uint64_t(r.mask) << 47),
        unsigned((r.address >> 4) & mask), unsigned((r.address >> 10) & mask), due};
}
int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SInstructionRequestGsim d;
    std::mt19937_64 rng(0x71220261002ULL);
    unsigned accepted = 0, delivered = 0, completed = 0, isolated = 0, zeroMask = 0;
    unsigned faults = 0, stalls = 0, immediate = 0, peak = 0, longest = 0;
    auto reset = [&] {
        d.set_io$$requestValid(0); d.set_io$$downstreamReady(0);
        d.set_io$$responseValid(0); d.set_io$$responseReady(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    };
    reset();
    for (unsigned epoch = 0; epoch < 3; ++epoch) {
        std::deque<Request> pending;
        std::deque<Reply> manager;
        std::optional<Request> held;
        Request offered{};
        bool offering = false;
        unsigned stream = 0;
        const unsigned duration = epoch == 2 ? 1000 : 10000;
        for (unsigned cycle = 0; cycle < duration || offering || !pending.empty() || !manager.empty(); ++cycle) {
            check(cycle < 16000, "instruction request drain timeout");
            if (!offering && cycle < duration) {
                offered = {rng(), unsigned(rng() & ((1U << PACKET_WORDS) - 1))};
                offering = true;
            }
            const bool downstreamReady = manager.size() < 16 &&
                (epoch == 2 || (cycle < 80 ? cycle >= 20 : rng() % 4 != 0));
            const bool cpuReady = epoch == 2 || (cycle < 80 ? cycle >= 40 : rng() % 3 != 0);
            const bool outputValid = !pending.empty() || (FLOW_THROUGH && offering);
            const Request output = !pending.empty() ? pending.front() : offered;
            const bool flowed = FLOW_THROUGH && pending.empty() && offering && downstreamReady;
            const bool instant = epoch == 2 && manager.empty() && outputValid && downstreamReady;
            std::optional<Reply> returning;
            if (!manager.empty() && manager.front().due <= cycle) returning = manager.front();
            else if (instant) returning = reply(output, cycle);
            d.set_io$$requestValid(offering); d.set_io$$requestAddress(offered.address);
            d.set_io$$requestMask(offered.mask); d.set_io$$downstreamReady(downstreamReady);
            d.set_io$$responseReady(cpuReady); d.set_io$$responseValid(bool(returning));
            d.set_io$$responseLow(returning ? returning->low : 0);
            d.set_io$$responseHigh(returning ? returning->high : 0);
            d.set_io$$responseError(returning ? returning->error : 0);
            d.set_io$$responsePageFault(returning ? returning->page : 0);
            d.step();
            // Independent FIFO oracle: empty bypass is optional, but full enqueue
            // never borrows a dequeue credit. A blocked empty offer is captured.
            check(bool(d.get_io$$requestReady()) == (pending.size() < 2), "instruction request credit mismatch");
            check(bool(d.get_io$$downstreamValid()) == outputValid, "instruction request flow/register mismatch");
            check(bool(d.get_io$$downstreamResponseReady()) == cpuReady, "instruction response backpressure mismatch");
            if (!downstreamReady && pending.size() < 2) ++isolated;
            Request actual{d.get_io$$downstreamAddress(), unsigned(d.get_io$$downstreamMask())};
            if (inject && outputValid) { actual.mask ^= 1; inject = false; }
            if (outputValid) check(actual == output, "instruction request oracle mismatch");
            if (held) check(d.get_io$$downstreamValid() && actual == *held, "stalled instruction request changed");
            held = outputValid && !downstreamReady ? std::optional<Request>(actual) : std::nullopt;
            if (outputValid && downstreamReady) {
                const Request sent = output;
                if (!pending.empty()) pending.pop_front();
                manager.push_back(reply(sent, cycle + (instant ? 0 : 1 + unsigned(rng() % 6))));
                ++delivered;
            }
            check(bool(d.get_io$$upstreamResponseValid()) == bool(returning), "instruction response latency changed");
            if (returning) {
                check(!manager.empty(), "instruction unsolicited response");
                const Reply &want = manager.front();
                check(d.get_io$$upstreamResponseLow() == want.low &&
                    d.get_io$$upstreamResponseHigh() == (PACKET_WORDS == 4 ? want.high : 0) &&
                    d.get_io$$upstreamResponseError() == want.error &&
                    d.get_io$$upstreamResponsePageFault() == want.page, "instruction response/fault oracle mismatch");
                if (cpuReady) { faults += want.error || want.page; manager.pop_front(); ++completed; }
                immediate += instant;
            }
            if (offering && d.get_io$$requestReady()) {
                if (!flowed) pending.push_back(offered);
                zeroMask += !offered.mask; offering = false; ++accepted;
                longest = std::max(longest, ++stream);
            } else { stream = 0; stalls += offering; }
            peak = std::max(peak, unsigned(pending.size()));
            check(pending.size() <= 2, "instruction queue capacity exceeded");
        }
        reset(); d.step();
        check(!d.get_io$$downstreamValid() && !d.get_io$$upstreamResponseValid(), "stale reset instruction transaction");
    }
    check(accepted == delivered && delivered == completed && peak == 2 && longest > 20 &&
        isolated && faults && stalls && immediate && zeroMask, "instruction request coverage incomplete");
    // Destructive reset drops queued requests only with the producer and manager
    // reset together. Verify a full queue cannot replay stale address/mask later.
    d.set_io$$requestValid(1); d.set_io$$requestAddress(0x80000ffcULL); d.set_io$$requestMask(1);
    d.set_io$$downstreamReady(0); d.step(); d.step();
    reset(); d.set_io$$downstreamReady(1); d.step();
    check(!d.get_io$$downstreamValid() && d.get_io$$requestReady(), "reset retained queued instruction request");
    std::cout << "GSIM instruction requests: PASS words=" << PACKET_WORDS << " accepted=" << accepted
              << " flow=" << FLOW_THROUGH << " completed=" << completed << " peak=" << peak << " stream=" << longest
              << " ready_isolation=" << isolated << " zero_mask=" << zeroMask
              << " faults=" << faults << " immediate=" << immediate << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
