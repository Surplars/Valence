#include "InstructionLineCacheGsim.h"
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string_view>

#ifndef PACKET_WORDS
#define PACKET_WORDS 2
#endif

static constexpr uint64_t ram = 0x80010000;
static constexpr uint64_t rom = 0x80000000;
static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static uint64_t beat(uint64_t address, unsigned generation) {
    const auto word = [generation](uint64_t pc) {
        return uint32_t(0x00000013U | (((pc >> 2) + generation * 37) & 0xfff) << 20);
    };
    return uint64_t(word(address)) | uint64_t(word(address + 4)) << 32;
}
struct Reply {
    unsigned source;
    unsigned index;
    uint64_t line;
    unsigned generation;
    unsigned size = 6;
};
struct Result {
    bool requestReady;
    bool responseValid;
    uint64_t responseLow;
    uint64_t responseHigh;
    bool aValid;
    uint64_t aAddress;
    unsigned aSource;
    bool dReady;
};
static Result step(SInstructionLineCacheGsim &dut, bool request = false, uint64_t pc = 0,
                   const std::optional<Reply> &reply = std::nullopt, bool invalidate = false,
                   bool aReady = true) {
    dut.set_io$$fetch$$request$$valid(request);
    dut.set_io$$fetch$$request$$bits(pc);
    dut.set_io$$fetch$$requestMask((1U << PACKET_WORDS) - 1);
    dut.set_io$$fetch$$response$$ready(1);
    dut.set_io$$invalidate(invalidate);
    dut.set_io$$privilege(3);
    dut.set_io$$pmpCfg0(0);
    dut.set_io$$pmpAddr0(0);
    dut.set_io$$tl$$a$$ready(aReady);
    dut.set_io$$tl$$d$$valid(bool(reply));
    dut.set_io$$tl$$d$$bits$$opcode(1);
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(reply ? reply->size : 6);
    dut.set_io$$tl$$d$$bits$$source(reply ? reply->source : 0);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(0);
    dut.set_io$$tl$$d$$bits$$data(reply ? beat(reply->line + reply->index * 8,
        reply->generation) : 0);
    dut.set_io$$tl$$d$$bits$$corrupt(0);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$c$$ready(0);
    dut.set_io$$tl$$e$$ready(0);
    dut.step();
    return {bool(dut.get_io$$fetch$$request$$ready()), bool(dut.get_io$$fetch$$response$$valid()),
        uint64_t(dut.get_io$$responseLow()), uint64_t(dut.get_io$$responseHigh()), bool(dut.get_io$$tl$$a$$valid()),
        dut.get_io$$tl$$a$$bits$$address(), unsigned(dut.get_io$$tl$$a$$bits$$source()),
        bool(dut.get_io$$tl$$d$$ready())};
}
static bool packetMatches(const Result &result, uint64_t pc, unsigned generation, bool inject = false) {
    uint64_t low = beat(pc, generation);
    uint64_t high = PACKET_WORDS == 4 ? beat(pc + 8, generation) : 0;
    if (inject) {
        if (PACKET_WORDS == 4) high ^= 1;
        else low ^= 1;
    }
    return result.responseLow == low && result.responseHigh == high;
}
static void sendLine(SInstructionLineCacheGsim &dut, uint64_t line, unsigned source,
                     unsigned generation = 0, bool aReady = true) {
    for (unsigned index = 0; index < 8; ++index) {
        const auto result = step(dut, false, 0, Reply{source, index, line, generation}, false, aReady);
        check(result.dReady, "line response was not accepted");
    }
}
int main(int argc, char **argv) {
    try {
        const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
        SInstructionLineCacheGsim dut;
        step(dut);
        dut.set_reset(1);
        step(dut); step(dut);
        dut.set_reset(0);

        bool accepted = false;
        unsigned demandSource = 0, prefetchSource = 0, secondPrefetchSource = 0;
        unsigned gets = 0;
        for (unsigned cycle = 0; cycle < 16 && gets < 3; ++cycle) {
            const auto result = step(dut, !accepted, ram);
            if (!accepted && result.requestReady) accepted = true;
            if (result.aValid) {
                check(result.aAddress == ram + 64 * gets,
                      "demand and two prefetch Gets were not sequential");
                if (gets == 0) demandSource = result.aSource;
                if (gets == 1) prefetchSource = result.aSource;
                if (gets == 2) secondPrefetchSource = result.aSource;
                ++gets;
            }
        }
        check(accepted && gets == 3 && demandSource != prefetchSource &&
              prefetchSource != secondPrefetchSource,
              "demand and two prefetch Gets did not overlap before the first response");
        sendLine(dut, ram, demandSource);
        for (unsigned cycle = 0; cycle < 4; ++cycle) step(dut);
        sendLine(dut, ram + 64, prefetchSource);
        bool lineHit = false, lineAccepted = false;
        for (unsigned cycle = 0; cycle < 12 && !lineHit; ++cycle) {
            const auto result = step(dut, !lineAccepted, ram + 64);
            if (!lineAccepted && result.requestReady) lineAccepted = true;
            if (result.responseValid) {
                check(lineAccepted && packetMatches(result, ram + 64, 0, inject),
                      "prefetched instruction line returned wrong code");
                lineHit = true;
            }
        }
        check(lineHit, "prefetched line did not hit");
        step(dut, false, 0, std::nullopt, true);
        sendLine(dut, ram + 128, secondPrefetchSource);
        for (unsigned cycle = 0; cycle < 3; ++cycle) step(dut);
        bool refetchAccepted = false, refetchIssued = false, refetchDone = false;
        unsigned refetchSource = 0;
        for (unsigned cycle = 0; cycle < 12 && !refetchIssued; ++cycle) {
            const auto result = step(dut, !refetchAccepted, ram + 128);
            if (!refetchAccepted && result.requestReady) refetchAccepted = true;
            if (result.aValid) {
                check(result.aAddress == ram + 128,
                      "invalidated prefetched line did not refetch");
                refetchSource = result.aSource;
                refetchIssued = true;
            }
        }
        check(refetchAccepted && refetchIssued, "invalidated prefetched line was reused");
        sendLine(dut, ram + 128, refetchSource, 1);
        for (unsigned cycle = 0; cycle < 6 && !refetchDone; ++cycle) {
            const auto result = step(dut);
            if (result.responseValid) {
                check(packetMatches(result, ram + 128, 1),
                      "stale prefetched code survived invalidation");
                refetchDone = true;
            }
        }
        check(refetchDone, "refetched instruction line did not reply");

        SInstructionLineCacheGsim stalled;
        step(stalled);
        stalled.set_reset(1);
        step(stalled); step(stalled);
        stalled.set_reset(0);
        bool initialAccepted = false, demandIssued = false, prefetchStalled = false;
        unsigned initialSource = 0, stalledSource = 0;
        for (unsigned cycle = 0; cycle < 12 && !demandIssued; ++cycle) {
            const auto result = step(stalled, !initialAccepted, ram);
            if (!initialAccepted && result.requestReady) initialAccepted = true;
            if (result.aValid && result.aAddress == ram) {
                initialSource = result.aSource;
                demandIssued = true;
            }
        }
        check(initialAccepted && demandIssued, "initial line Get was not issued");
        for (unsigned cycle = 0; cycle < 8 && !prefetchStalled; ++cycle) {
            const auto result = step(stalled, false, 0, std::nullopt, false, false);
            if (result.aValid && result.aAddress == ram + 64) {
                stalledSource = result.aSource;
                prefetchStalled = true;
            }
        }
        check(prefetchStalled, "prefetch A was not presented under backpressure");
        for (unsigned index = 0; index < 8; ++index) {
            const auto result = step(stalled, false, 0, Reply{initialSource, index, ram, 0},
                                     false, false);
            check(result.dReady && result.aValid && result.aAddress == ram + 64 &&
                  result.aSource == stalledSource, "stalled prefetch A changed during demand reply");
        }
#ifdef COMPACT_TAG_TEST
        const uint64_t fallbackAddress = ram | (1ULL << 40);
#else
        const uint64_t fallbackAddress = rom;
#endif
        bool romAccepted = false, romIssued = false;
        for (unsigned cycle = 0; cycle < 8; ++cycle) {
            // A wide adapter can accept the ROM packet while its first narrow
            // Get waits behind the locked prefetch A. Never reissue that packet.
            const auto result = step(stalled, !romAccepted, fallbackAddress, std::nullopt, false, false);
            if (!romAccepted && result.requestReady) romAccepted = true;
            check(result.aValid && result.aAddress == ram + 64 &&
                  result.aSource == stalledSource, "stalled prefetch A changed at ROM transition");
        }
        for (unsigned cycle = 0; cycle < 8 && (!romAccepted || !romIssued); ++cycle) {
            const auto result = step(stalled, !romAccepted, fallbackAddress);
            if (result.aValid && result.aAddress == fallbackAddress) romIssued = true;
            if (!romAccepted && result.requestReady) romAccepted = true;
        }
        check(romAccepted, "ROM fetch was not accepted after line reply");
        check(romIssued, "ROM Get was not issued after stalled prefetch A");
        std::cout << "GSIM instruction prefetch: PASS packetWords=" << PACKET_WORDS
                  << " three concurrent fills, full packet line hit, "
                     "invalidate, refetch and stalled ROM transition\n";
    } catch (const std::exception &error) {
        std::cerr << "GSIM instruction prefetch: FAIL " << error.what() << '\n';
        return 1;
    }
}
