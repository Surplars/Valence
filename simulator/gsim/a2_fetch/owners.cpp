#include "FetchDemandOwnersGsim.h"
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Offer { uint64_t base; unsigned context, mask; bool stale; };
struct Owner { Offer offer; uint64_t due; };
int main(int argc, char **argv) { try {
    const std::string mode = argc == 2 ? argv[1] : "";
    check(argc <= 2 && (mode.empty() || mode == "--unowned" || mode == "--inject-held"), "bad owners argument");
    SFetchDemandOwnersGsim d;
    d.set_io$$candidate(0); d.set_io$$base(0); d.set_io$$context(0); d.set_io$$mask(0);
    d.set_io$$requestReady(0); d.set_io$$response(0); d.set_io$$invalidate(0);
    d.set_io$$query0(0); d.set_io$$query1(0); d.set_io$$queryContext(0);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    std::deque<Owner> live;
    std::optional<Offer> held;
    unsigned accepted = 0, retired = 0, maximum = 0, heldCycles = 0, staleReplies = 0, cancelledHeld = 0;
    unsigned turnover = 0, drain = 0;
    for (uint64_t cycle = 0; cycle < 10000; ++cycle) {
        const Offer candidate{accepted % 23 == 0 ? UINT64_MAX - 7 : UINT64_C(0x40000000) + 8 * (accepted % 11),
            unsigned(cycle % 8), accepted % 4, false};
        const bool valid = accepted < 256;
        const bool ready = cycle % 7 >= 3;
        const bool response = (!live.empty() && cycle >= live.front().due) || (mode == "--unowned" && cycle == 0);
        const bool invalidate = cycle % 19 == 7;
        const bool credit = live.size() < 2 || response;
        const bool request = held.has_value() || (valid && credit);
        const Offer offered = held.value_or(candidate);
        const bool take = request && ready;
        const uint64_t q0 = live.empty() ? candidate.base : live.front().offer.base;
        const uint64_t q1 = candidate.base;
        const unsigned qc = live.empty() ? candidate.context : live.front().offer.context;
        unsigned owned = 0;
        for (const auto &o : live) if (!o.offer.stale && o.offer.context == qc) {
            owned |= (o.offer.base == q0 ? 1 : 0) | (o.offer.base == q1 ? 2 : 0);
        }
        if (mode == "--unowned" && cycle == 0) std::cerr << "INJECT unowned\n";
        d.set_io$$candidate(valid); d.set_io$$base(candidate.base); d.set_io$$context(candidate.context);
        d.set_io$$mask(candidate.mask); d.set_io$$requestReady(ready); d.set_io$$response(response);
        d.set_io$$invalidate(invalidate); d.set_io$$query0(q0); d.set_io$$query1(q1); d.set_io$$queryContext(qc);
        d.step();
        check(mode != "--unowned", "unowned response was not rejected by hardware");
        check(bool(d.get_io$$headValid()) == !live.empty() && bool(d.get_io$$credit()) == credit &&
            bool(d.get_io$$held()) == held.has_value() && bool(d.get_io$$idle()) == (live.empty() && !held),
            "independent demand owner credit/idle mismatch");
        check(d.get_io$$owned() == owned, "pending owner was lost, aliased, or mistaken for stale data");
        if (!live.empty()) {
            const auto &h = live.front().offer;
            check(d.get_io$$headBase() == h.base && d.get_io$$headPlus() == h.base + 8 &&
                d.get_io$$headMinus() == h.base - 24 && d.get_io$$headContext() == h.context &&
                bool(d.get_io$$headStale()) == h.stale, "return was routed to the wrong accepted demand");
        }
        check(bool(d.get_io$$requestValid()) == request, "demand request valid/credit mismatch");
        if (request) {
            auto address = d.get_io$$requestBase();
            if (mode == "--inject-held" && held) { std::cerr << "INJECT held\n"; address ^= 8; }
            check(address == offered.base && d.get_io$$requestContext() == offered.context &&
                d.get_io$$requestMask() == offered.mask, "independent held demand payload mismatch");
        }
        heldCycles += held.has_value();
        if (response) { staleReplies += live.front().offer.stale; live.pop_front(); ++retired; }
        if (invalidate) for (auto &o : live) o.offer.stale = true;
        if (take) {
            auto saved = offered; saved.stale |= invalidate;
            live.push_back({saved, cycle + (accepted % 2 ? 2 : 17)});
            ++accepted; turnover += response; held.reset();
        } else if (request && !held) { held = offered; held->stale = invalidate; }
        if (invalidate && held) { held->stale = true; ++cancelledHeld; }
        maximum = std::max(maximum, unsigned(live.size()));
        check(live.size() + unsigned(held.has_value()) <= 2, "accepted plus held exceeds demand credit");
        if (retired == 256 && ++drain == 5) break;
    }
    check(mode.empty() && accepted == 256 && retired == 256 && live.empty() && !held && maximum == 2 &&
        heldCycles && staleReplies && cancelledHeld && turnover, "demand owner coverage/drain incomplete");
    std::cout << "PASS A2_FETCH_OWNERS accepted=" << accepted << " retired=" << retired
        << " max_owners=" << maximum << " held=" << heldCycles << " stale_replies=" << staleReplies
        << " cancelled_held=" << cancelledHeld << " turnover=" << turnover << '\n'; return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
