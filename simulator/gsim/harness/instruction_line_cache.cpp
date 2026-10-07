#include "InstructionLineCacheGsim.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#ifndef PACKET_WORDS
#define PACKET_WORDS 2
#endif

static constexpr uint64_t ram = 0x80010000;
static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static uint32_t instruction(uint64_t address, unsigned generation) {
    return 0x00000013U | (uint32_t(((address >> 2) + generation * 37) & 0xfff) << 20);
}
static uint64_t beat(uint64_t address, unsigned generation) {
    return uint64_t(instruction(address, generation)) |
        (uint64_t(instruction(address + 4, generation)) << 32);
}
static bool packetMatches(SInstructionLineCacheGsim &dut, uint64_t pc, unsigned generation) {
    return dut.get_io$$responseLow() == beat(pc, generation) &&
        (PACKET_WORDS == 2 || dut.get_io$$responseHigh() == beat(pc + 8, generation));
}
struct Reply {
    unsigned source;
    unsigned size;
    uint64_t data;
    bool denied;
};
static void drive(SInstructionLineCacheGsim &dut, bool request, uint64_t pc,
                  const std::optional<Reply> &reply, unsigned privilege = 3,
                  unsigned pmpCfg = 0, uint64_t pmpAddr = 0, bool invalidate = false,
                  bool responseReady = true) {
    dut.set_io$$fetch$$request$$valid(request);
    dut.set_io$$fetch$$request$$bits(pc);
    dut.set_io$$fetch$$requestMask((1U << PACKET_WORDS) - 1);
    dut.set_io$$fetch$$response$$ready(responseReady);
    dut.set_io$$invalidate(invalidate);
    dut.set_io$$privilege(privilege);
    dut.set_io$$pmpCfg0(pmpCfg);
    dut.set_io$$pmpAddr0(pmpAddr);
    dut.set_io$$tl$$a$$ready(1);
    dut.set_io$$tl$$d$$valid(bool(reply));
    dut.set_io$$tl$$d$$bits$$opcode(1);
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(reply ? reply->size : 3);
    dut.set_io$$tl$$d$$bits$$source(reply ? reply->source : 0);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(reply && reply->denied);
    dut.set_io$$tl$$d$$bits$$data(reply ? reply->data : 0);
    dut.set_io$$tl$$d$$bits$$corrupt(0);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$c$$ready(0);
    dut.set_io$$tl$$e$$ready(0);
}
static unsigned fetch(SInstructionLineCacheGsim &dut, uint64_t pc, unsigned generation,
                      unsigned expectedSize, unsigned privilege = 3,
                      unsigned pmpCfg = 0, uint64_t pmpAddr = 0,
                      bool injectLineError = false) {
    std::deque<Reply> replies;
    bool accepted = false;
    unsigned gets = 0;
    for (unsigned cycle = 0; cycle < 120; ++cycle) {
        std::optional<Reply> offered;
        if (!replies.empty()) offered = replies.front();
        drive(dut, !accepted, pc, offered, privilege, pmpCfg, pmpAddr);
        dut.step();
        if (offered && dut.get_io$$tl$$d$$ready()) replies.pop_front();
        if (!accepted && dut.get_io$$fetch$$request$$ready()) accepted = true;
        if (dut.get_io$$tl$$a$$valid()) {
            const unsigned size = dut.get_io$$tl$$a$$bits$$size();
            const uint64_t address = dut.get_io$$tl$$a$$bits$$address();
            const unsigned source = dut.get_io$$tl$$a$$bits$$source();
            const unsigned expectedGetSize = injectLineError && gets >= 1 ? 3 : expectedSize;
            const unsigned fallbackIndex = gets - (injectLineError && gets > 0 ? 1 : 0);
            const uint64_t expectedAddress = expectedGetSize == 6 ? pc & ~63ULL :
                (pc + 8ULL * fallbackIndex) & ~7ULL;
            check(size == expectedGetSize && address == expectedAddress,
                  "instruction Get used the wrong size or address");
            const unsigned count = (1U << size) / 8;
            for (unsigned i = 0; i < count; ++i)
                replies.push_back({source, size, beat(address + 8 * i, generation),
                    injectLineError && gets == 0 && i == count - 1});
            ++gets;
        }
        if (dut.get_io$$fetch$$response$$valid()) {
            check(accepted && replies.empty(), "instruction reply preceded complete TileLink data");
            check(!dut.get_io$$fetch$$responseError() &&
                  packetMatches(dut, pc, generation),
                  "instruction cache returned incorrect code");
            return gets;
        }
    }
    throw std::runtime_error("instruction cache request timed out");
}
static void streamHits(SInstructionLineCacheGsim &dut) {
    constexpr unsigned packets = PACKET_WORDS == 4 ? 7 : 8;
    unsigned issued = 0, returned = 0, overlaps = 0, cycles = 0;
    for (; cycles < 16 && returned < packets; ++cycles) {
        const bool request = issued < packets;
        drive(dut, request, ram + 64 + 8 * issued, std::nullopt);
        dut.step();
        const bool requestFire = request && dut.get_io$$fetch$$request$$ready();
        const bool responseFire = dut.get_io$$fetch$$response$$valid();
        check(!dut.get_io$$tl$$a$$valid(), "resident line unexpectedly accessed TileLink");
        if (responseFire) {
            check(returned < issued &&
                  packetMatches(dut, ram + 64 + 8 * returned, 0),
                  "streamed instruction packet was stale or reordered");
            ++returned;
        }
        if (requestFire) ++issued;
        if (requestFire && responseFire) ++overlaps;
    }
    check(issued == packets && returned == packets && cycles == packets + 1 && overlaps == packets - 1,
          "instruction cache hit path did not sustain one packet per cycle");

    drive(dut, true, ram + 64, std::nullopt);
    dut.step();
    check(dut.get_io$$fetch$$request$$ready(), "backpressure setup request was not accepted");
    drive(dut, true, ram + 72, std::nullopt, 3, 0, 0, false, false);
    dut.step();
    check(dut.get_io$$fetch$$response$$valid() &&
          packetMatches(dut, ram + 64, 0) &&
          !dut.get_io$$fetch$$request$$ready(), "stalled hit reply changed or accepted a request");
    drive(dut, true, ram + 72, std::nullopt);
    dut.step();
    check(dut.get_io$$fetch$$response$$valid() &&
          packetMatches(dut, ram + 64, 0) &&
          dut.get_io$$fetch$$request$$ready(), "hit reply could not hand off after backpressure");
    drive(dut, false, 0, std::nullopt);
    dut.step();
    check(dut.get_io$$fetch$$response$$valid() &&
          packetMatches(dut, ram + 72, 0),
          "next hit was lost after response backpressure");
}
int main() {
    try {
        SInstructionLineCacheGsim dut;
        drive(dut, false, 0, std::nullopt);
        dut.set_reset(1);
        dut.step(); dut.step(); dut.set_reset(0);
        check(fetch(dut, ram, 0, 6) == 1, "first line did not burst-fill");
        check(fetch(dut, ram + 64, 0, 6) == 1, "second line did not burst-fill");
        check(fetch(dut, ram + 128, 0, 6) == 1, "third line did not burst-fill");
        streamHits(dut);
        check(fetch(dut, ram + 8, 0, 6) == 0, "same line did not hit");
        if (PACKET_WORDS == 4)
            check(fetch(dut, ram + 56, 0, 3) == 2, "cross-line wide packet did not use precise fallback");
        check(fetch(dut, ram, 0, 6) == 0, "resident line was evicted unexpectedly");
        check(fetch(dut, ram + 512, 0, 6) == 1, "second way did not fill");
        check(fetch(dut, ram, 0, 6) == 0 && fetch(dut, ram + 512, 0, 6) == 0,
              "two lines in the same set did not coexist");
        check(fetch(dut, ram + 1024, 0, 6) == 1, "third same-set line did not replace a way");
        check(fetch(dut, ram + 512, 0, 6) == 0, "replacement evicted the recently used way");
        check(fetch(dut, ram + 1536, 0, 6, 3, 0, 0, true) == 1 + PACKET_WORDS / 2,
              "failed line fill did not retry the precise requested packet");
        drive(dut, false, 0, std::nullopt, 3, 0, 0, true);
        dut.step();
        check(fetch(dut, ram, 1, 6) == 1, "invalidate retained old RAM code");
        // A TOR region ending after the requested packet must not authorize a 64-byte fill.
        check(fetch(dut, ram, 1, 3, 1, 0x0c, (ram + PACKET_WORDS * 4) >> 2) == PACKET_WORDS / 2,
              "PMP boundary did not fall back to a precise packet Get");
        std::cout << "GSIM instruction line cache: PASS packetWords=" << PACKET_WORDS
                  << " hits=1packet/cycle lines=6 twoWay=1 "
                     "burstBeats=8 invalidate=1 pmpFallback=1\n";
    } catch (const std::exception &error) {
        std::cerr << "GSIM instruction line cache: FAIL " << error.what() << '\n';
        return 1;
    }
}
