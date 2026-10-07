#include "BoardRomGsim.h"
#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>

static constexpr uint64_t base = 0x80000000ULL, bytes = 128 * 1024;
static void check(bool v, const char *m) { if (!v) throw std::runtime_error(m); }
static uint32_t word(unsigned index) { return 0x76543210U ^ (index * 0x1020304U); }
struct Reply {
    uint64_t data, mask;
    unsigned source, size, acceptedAt;
    bool denied;
};
struct Held {
    uint64_t data;
    unsigned source, size;
    bool denied;
    bool operator==(const Held &) const = default;
};

int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SBoardRomGsim d;
    auto reset = [&] {
        d.set_io$$write(0); d.set_io$$index(0); d.set_io$$data(0);
        d.set_io$$requestValid(0); d.set_io$$address(base); d.set_io$$size(0); d.set_io$$mask(1);
        d.set_io$$source(0); d.set_io$$responseReady(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    };
    reset();
    for (unsigned index = 0; index < 32768; ++index) {
        if (index >= 64 && index < 32764) continue;
        d.set_io$$write(1); d.set_io$$index(index); d.set_io$$data(word(index)); d.step();
    }
    d.set_io$$write(0); d.step();
    std::mt19937_64 rng(0x2c0ed20261002ULL);
    unsigned accepted = 0, completed = 0, discarded = 0, faults = 0, stalledA = 0, stalledD = 0;
    unsigned peak = 0, fullNoBorrow = 0, emptyBypass = 0, stream = 0, longestStream = 0;
    for (unsigned epoch = 0; epoch < 3; ++epoch) {
        // Independent physical capacity model: two reply slots plus one native
        // synchronous ROM reply. A full reply queue cannot borrow D.ready credit.
        std::deque<Reply> replies, ledger;
        std::optional<Reply> native;
        std::optional<Held> held;
        unsigned issued = 0;
        const unsigned limit = epoch == 0 ? 3 : 1200;
        const unsigned duration = epoch == 0 ? 80 : 6000;
        bool resetPending = false;
        for (unsigned cycle = 0; cycle < duration; ++cycle) {
            const bool offer = issued < limit || epoch == 0;
            const bool ready = epoch == 2 || (epoch == 1 && cycle >= 80 && cycle % 113 >= 15 && rng() % 4 != 0);
            const unsigned size = issued % 4, count = 1U << size, region = (issued / 4) % 4;
            const uint64_t begin = region == 0 ? base : region == 1 ? base + bytes - 16 :
                                   region == 2 ? base - 16 : base + bytes;
            const uint64_t address = begin + ((issued * 8) % 16);
            const unsigned lane = address % 8;
            uint64_t dataMask = 0;
            for (unsigned i = 0; i < count; ++i) dataMask |= 255ULL << ((lane + i) * 8);
            const bool denied = address < base || address + count > base + bytes;
            const unsigned index = ((address - base) & ~7ULL) / 4;
            const uint64_t data = denied ? 0 : uint64_t(word(index + 1)) << 32 | word(index);
            Reply request{data, denied ? UINT64_MAX : dataMask, issued % 8, size, cycle, denied};
            d.set_io$$requestValid(offer); d.set_io$$address(offer ? address : UINT64_MAX);
            d.set_io$$size(offer ? size : 7); d.set_io$$mask(offer ? ((1U << count) - 1) << lane : 0);
            d.set_io$$source(request.source); d.set_io$$responseReady(ready); d.step();
            const unsigned occupancy = replies.size();
            const bool requestReady = !native || occupancy < 2;
            const bool responseValid = !replies.empty() || bool(native);
            check(bool(d.get_io$$requestReady()) == requestReady, "ROM request credit oracle mismatch");
            check(bool(d.get_io$$responseValid()) == responseValid, "ROM response latency/valid oracle mismatch");
            Held actual{d.get_io$$responseData(), unsigned(d.get_io$$responseSource()),
                        unsigned(d.get_io$$responseSize()), bool(d.get_io$$responseError())};
            if (held) check(responseValid && actual == *held, "stalled ROM reply changed");
            held = responseValid && !ready ? std::optional<Held>(actual) : std::nullopt;
            const bool aFire = offer && requestReady, dFire = responseValid && ready;
            if (responseValid) {
                check(!ledger.empty(), "unsolicited ROM reply");
                const Reply &want = ledger.front();
                if (inject) { actual.data ^= uint64_t(1) << (address % 8); inject = false; }
                check((actual.data & want.mask) == (want.data & want.mask) && actual.source == want.source &&
                      actual.size == want.size && actual.denied == want.denied, "ROM reply credit oracle mismatch");
                if (replies.empty() && ready) {
                    check(cycle == want.acceptedAt + 1, "empty ROM reply buffer added latency"); ++emptyBypass;
                }
                if (dFire) { ledger.pop_front(); ++completed; }
                else ++stalledD;
            }
            if (occupancy == 2 && native && ready) {
                check(!requestReady, "full ROM queue borrowed same-cycle D dequeue credit"); ++fullNoBorrow;
            }
            if (offer && !requestReady) ++stalledA;
            // Model all changes using pre-edge capacity, not post-pop queue size.
            if (dFire && occupancy) replies.pop_front();
            const bool consumedNative = native && occupancy < 2;
            if (consumedNative) {
                if (!(occupancy == 0 && ready)) replies.push_back(*native);
                native.reset();
            }
            if (aFire) { native = request; ledger.push_back(request); ++issued; ++accepted; faults += denied; }
            peak = std::max(peak, unsigned(ledger.size()));
            check(ledger.size() <= 3, "ROM exceeded independent physical capacity");
            stream = aFire && dFire ? stream + 1 : 0;
            longestStream = std::max(longestStream, stream);
            if (epoch == 0 && cycle == duration - 1) {
                check(ledger.size() == 3 && replies.size() == 2 && native, "pending-reset saturation not reached");
                discarded += ledger.size(); resetPending = true; break;
            }
            if (issued == limit && ledger.empty()) break;
            check(cycle + 1 < duration, "ROM reply drain timeout");
        }
        if (resetPending) reset();
        else check(ledger.empty(), "ROM ledger did not drain");
    }
    check(accepted == completed + discarded && discarded == 3 && peak == 3 && faults && stalledA && stalledD &&
          fullNoBorrow && emptyBypass && longestStream > 100, "ROM reply credit coverage missing");
    std::cout << "GSIM ROM reply credits: PASS accepted=" << accepted << " completed=" << completed
              << " resetDiscarded=" << discarded << " faults=" << faults << " peak=" << peak
              << " stalledA=" << stalledA << " stalledD=" << stalledD << " fullNoBorrow=" << fullNoBorrow
              << " emptyBypass=" << emptyBypass << " sustainedII1=" << longestStream
              << " sizes=1/2/4/8 sourceOrder=checked\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
