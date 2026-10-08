// Independent held-response oracle. Reuse only the external port drive and memory
// byte function from the instruction-cache fixture, never the DUT's bank/way data.
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wreturn-type"
#define main instructionCacheOriginalMain
#include "instruction_line_cache.cpp"
#undef main
#pragma GCC diagnostic pop
#include <algorithm>
#include <functional>
#include <vector>

struct HeldHitTest {
    struct Transaction { unsigned source, size, index; uint64_t address; unsigned generation; };
    struct Expected { uint64_t address; unsigned generation; uint64_t accepted; };
    struct Request { uint64_t address; unsigned generation; };
    SInstructionLineCacheGsim d;
    std::vector<Transaction> memory;
    std::deque<Expected> expected;
    std::optional<Request> request;
    unsigned generation = 17;
    uint64_t cycles = 0, replies = 0, requests = 0, gets = 0, held = 0, prefetchDuringHold = 0;
    bool ready = true, invalidate = false, allMemory = false, brokenHold = false, mutated = false;
    bool firstStallPrefetch = false;
    uint64_t memoryLimit = ram;
    std::optional<unsigned> selected;

    void tick() {
        std::optional<Reply> response;
        selected.reset();
        for (unsigned i = 0; i < memory.size(); ++i) {
            const auto &m = memory[i];
            if (allMemory || m.address <= memoryLimit) {
                selected = i;
                response = Reply{m.source, m.size, beat(m.address + m.index * 8, m.generation), false};
                break;
            }
        }
        drive(d, bool(request), request ? request->address : ram + 192, response,
            3, 0, 0, invalidate, ready);
        if (brokenHold && held == 2 && !mutated) {
            // Restore the unsafe hitReply state after the snapshot. This is the
            // precise old dependency on the now-disabled/live-address SRAM read.
            d.cache$state = 5; d.cache$state$NEXT = 5; d.activateAll(); mutated = true;
        }
        d.step(); ++cycles;
        if (d.get_io$$fetch$$response$$valid()) {
            check(!expected.empty(), "held-hit response has no accepted owner");
            const auto &e = expected.front();
            check(packetMatches(d, e.address, e.generation) && !d.get_io$$fetch$$responseError() &&
                !d.get_io$$fetch$$responsePageFault(), "held-hit immutable byte oracle mismatch");
            check(cycles > e.accepted, "held-hit response lost synchronous read latency");
            if (ready) { ++replies; expected.pop_front(); } else ++held;
        }
#ifdef PREFETCH_ENABLED
        if (!ready && d.get_io$$fetch$$response$$valid() && d.cache$prefetchReply) {
            ++prefetchDuringHold; firstStallPrefetch |= held == 1;
        }
#endif
        if (request && d.get_io$$fetch$$request$$ready()) {
            expected.push_back({request->address, request->generation, cycles});
            request.reset(); ++requests;
        }
        if (response && d.get_io$$tl$$d$$ready()) {
            auto &m = memory[*selected];
            if (++m.index == (1U << m.size) / 8) memory.erase(memory.begin() + *selected);
        }
        if (d.get_io$$tl$$a$$valid()) {
            const auto size = unsigned(d.get_io$$tl$$a$$bits$$size());
            const auto address = uint64_t(d.get_io$$tl$$a$$bits$$address());
            check(size == 6 && address >= ram && address < ram + 4096,
                "held-hit unexpected or unauthorized memory request");
            memory.push_back({unsigned(d.get_io$$tl$$a$$bits$$source()), size, 0, address, generation}); ++gets;
        }
    }
    template<class P> void until(P done, const char *message) {
        for (unsigned i = 0; !done(); ++i) { check(i < 200, message); tick(); }
    }
    void reset() {
        drive(d, false, 0, std::nullopt);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        request.reset(); expected.clear(); memory.clear(); ready = true; invalidate = false;
    }
    void warm() {
        reset();
        request = Request{ram, generation};
        until([&]{return requests == 1 && expected.empty();}, "held-hit demand warmup stalled");
        memoryLimit = ram + 64;
        for (unsigned i = 0; i < 20; ++i) tick();
#ifdef PREFETCH_ENABLED
        check(gets >= 3 && std::any_of(memory.begin(), memory.end(), [](const auto &m) {
            return m.address == ram + 128 && m.index == 0;
        }) && std::all_of(memory.begin(), memory.end(), [](const auto &m) { return m.address >= ram + 128; }),
            "held-hit fixture did not retain its pending prefetch");
#else
        request = Request{ram + 64, generation};
        until([&]{return requests == 2 && expected.empty();}, "held-hit second warmup stalled");
#endif
    }
    void run(bool invalidateFirst, bool invalidateRelease, bool resetHeld, bool alignPrefetch = false) {
        warm();
#ifdef PREFETCH_ENABLED
        if (alignPrefetch) {
            memoryLimit = ram + 128;
            for (unsigned i = 0; i < 7; ++i) tick();
            check(std::any_of(memory.begin(), memory.end(), [](const auto &m) {
                return m.address == ram + 128 && m.index == 7;
            }), "prefetch could not align its last beat with the hit request");
        }
#endif
        const auto beforeRequests = requests, beforeReplies = replies;
        request = Request{ram + 8, generation}; ready = false;
        tick();
        check(!request && requests == beforeRequests + 1 && expected.size() == 1,
            "held-hit request was not admitted immediately");
        const auto acceptedCycle = cycles;
        request = Request{ram + 72, generation + unsigned(invalidateFirst || invalidateRelease)};
        if (invalidateFirst || invalidateRelease) ++generation;
        memoryLimit = ram + 128; // deliver a pending prefetch while the CPU reply is held
        for (unsigned i = 0; i < 20; ++i) {
            invalidate = invalidateFirst && i == 0;
            tick();
            check(request && d.get_io$$fetch$$response$$valid() && expected.size() == 1,
                "held-hit offer or response changed during backpressure");
            if (i == 0) check(cycles == acceptedCycle + 1, "first hit latency changed");
        }
        invalidate = false;
#ifdef PREFETCH_ENABLED
        check(prefetchDuringHold == 1, "prefetch did not return during held instruction hit");
        check(!alignPrefetch || firstStallPrefetch, "prefetch return missed the first hit-stall edge");
#endif
        if (resetHeld) {
            // Coordinated reset cancels both CPU/TL owners; no old reply survives.
            reset(); generation = 21; allMemory = true;
            tick(); check(!d.get_io$$fetch$$response$$valid(), "reset exposed a cancelled hit response");
            const auto newReplies = replies;
            request = Request{ram + 8, generation};
            until([&]{return !request && expected.empty() && replies == newReplies + 1;},
                "post-reset instruction refetch stalled");
        } else {
            invalidate = invalidateRelease; ready = true; allMemory = true;
            tick();
            check(!request && replies == beforeReplies + 1 && expected.size() == 1,
                "held-hit release could not accept its waiting request");
            invalidate = false;
            if (!invalidateFirst && !invalidateRelease) {
                tick();
                check(expected.empty() && replies == beforeReplies + 2,
                    "post-hold resident hit lost initiation interval one");
            } else {
                until([&]{return expected.empty();}, "invalidated next request did not refetch");
                const auto oldGets = gets;
                request = Request{ram + 8, generation};
                until([&]{return !request && expected.empty();}, "invalidated old line did not refetch");
                check(gets > oldGets, "invalidation retained the old held-hit line");
                request = Request{ram + 128, generation};
                until([&]{return !request && expected.empty();}, "invalidated prefetch line did not refetch");
            }
        }
        check(held >= 20, "held-hit multiple-cycle pressure was not exercised");
        std::cout << "HELD_HIT_CASE invalidate_first=" << invalidateFirst << " invalidate_release=" << invalidateRelease
            << " reset_held=" << resetHeld << " align_prefetch=" << alignPrefetch << " cycles=" << cycles << " held=" << held
            << " prefetch_during_hold=" << prefetchDuringHold << " requests=" << requests
            << " replies=" << replies << " gets=" << gets << '\n';
    }
};

int main(int argc, char **argv) {
    try {
        const bool broken = argc == 2 && std::string_view(argv[1]) == "--bypass-hit-snapshot";
        for (unsigned mode = 0; mode < 4; ++mode) {
            HeldHitTest t; t.brokenHold = broken;
            t.run(mode == 1, mode == 2, mode == 3);
        }
#ifdef PREFETCH_ENABLED
        for (unsigned mode = 0; mode < 2; ++mode) {
            HeldHitTest t; t.brokenHold = broken; t.run(mode == 1, false, false, true);
        }
#endif
        std::cout << "INSTRUCTION_HIT_STABILITY_PASS packet_words=" << PACKET_WORDS << '\n';
    } catch (const std::exception &error) {
        std::cerr << "INSTRUCTION_HIT_STABILITY_FAIL " << error.what() << '\n'; return 1;
    }
}
