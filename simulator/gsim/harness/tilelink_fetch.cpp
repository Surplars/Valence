#include "InstructionTileLinkBridge.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr uint64_t base = 0x80000000ULL;
static void check(bool good, const char *message) { if (!good) throw std::runtime_error(message); }
static uint32_t word(uint64_t address) { return 0x10203040U ^ uint32_t(address >> 2); }
static bool denied(uint64_t address) { return address >= base + 0x100 && address < base + 0x10000; }
static bool corrupt(uint64_t address) { return address == base + 24; }
static bool error(uint64_t address) { return denied(address) || corrupt(address); }
static uint64_t beat(uint64_t address) {
    return error(address) ? 0 : (uint64_t(word(address + 4)) << 32) | word(address);
}
static uint64_t packet(uint64_t pc) { return (uint64_t(uint32_t(beat((pc + 4) & ~7ULL) >> (8 * ((pc + 4) & 7)))) << 32) |
                                           uint32_t(beat(pc & ~7ULL) >> (8 * (pc & 7)));
}
struct Reply { unsigned source, due; uint64_t data; bool denied, corrupt = false; unsigned size = 3; };

static void drive(SInstructionTileLinkBridge &dut, bool request, uint64_t pc, bool responseReady,
                  bool aReady, const std::optional<Reply> &reply, unsigned requestMask = 3) {
    dut.set_io$$fetch$$request$$valid(request);
    dut.set_io$$fetch$$request$$bits(pc);
    dut.set_io$$fetch$$requestMask(requestMask);
    dut.set_io$$fetch$$response$$ready(responseReady);
    dut.set_io$$tl$$a$$ready(aReady);
    dut.set_io$$tl$$d$$valid(bool(reply));
    dut.set_io$$tl$$d$$bits$$opcode(1);
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(reply ? reply->size : 3);
    dut.set_io$$tl$$d$$bits$$source(reply ? reply->source : 0);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(reply && reply->denied);
    dut.set_io$$tl$$d$$bits$$data(reply ? reply->data : 0);
    dut.set_io$$tl$$d$$bits$$corrupt(reply && reply->corrupt);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$c$$ready(0);
    dut.set_io$$tl$$e$$ready(0);
}

int main(int argc, char **argv) {
    const bool mismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    const bool wrongSource = argc == 2 && std::string(argv[1]) == "--inject-wrong-source";
    const std::array<uint64_t, 13> pcs{base, base + 4, base + 8, base + 12, base + 20,
                                        base + 24, base + 0xf8, base + 0xfc, base + 0x100,
                                        base + 0x104, base + 0x10000, base + 0x10004, base};
    SInstructionTileLinkBridge dut;
    std::optional<Reply> offered;
    std::vector<Reply> pending;
    drive(dut, false, 0, false, false, offered);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned issued = 0, retired = 0, aCount = 0, aStalls = 0, responseStalls = 0, outOfOrder = 0;
    unsigned responseRequestOverlap = 0, requestAOverlap = 0, simultaneousAD = 0, cacheHits = 0;
    uint64_t currentPc = 0;
    unsigned currentGroup = 0, nextGroup = 0;
    bool firstReturned = false, injected = false, currentHit = false, cachedGood = false;
    uint64_t cachedAddress = 0;
    std::optional<std::pair<unsigned, uint64_t>> stalledA;
    for (unsigned cycle = 0; cycle < 1000 && retired < pcs.size(); ++cycle) {
        if (!offered) {
            int chosen = -1;
            for (unsigned i = 0; i < pending.size(); ++i) {
                if (pending[i].due <= cycle && (chosen < 0 || pending[i].source > pending[chosen].source))
                    chosen = int(i);
            }
            if (chosen >= 0) { offered = pending[chosen]; pending.erase(pending.begin() + chosen); }
        }
        const bool request = issued < pcs.size();
        const bool responseReady = retired > 0 || cycle % 5 != 0;
        const bool aReady = cycle % 4 != 0 || (offered && responseReady);
        drive(dut, request, request ? pcs[issued] : 0, responseReady, aReady, offered);
        dut.step();
        if (request && dut.get_io$$fetch$$request$$ready() &&
            dut.get_io$$tl$$a$$valid() && aReady) {
            ++requestAOverlap;
            if (offered && dut.get_io$$tl$$d$$ready()) ++simultaneousAD;
        }
        if (request && dut.get_io$$fetch$$request$$ready() && responseReady &&
            dut.get_io$$fetch$$response$$valid()) ++responseRequestOverlap;
        if (dut.get_io$$fetch$$response$$valid()) {
            check(retired < issued, "TileLink fetch returned an unsolicited packet");
            uint64_t expected = packet(pcs[retired]);
            if (mismatch && !injected) { expected ^= 1; injected = true; }
            check(dut.get_io$$fetch$$response$$bits() == expected,
                  "TileLink fetch packet data or alignment mismatch");
            const uint64_t pc = pcs[retired];
            const unsigned expectedErrors = unsigned(error(pc & ~7ULL)) |
                (unsigned(error((pc + 4) & ~7ULL)) << 1);
            check(dut.get_io$$fetch$$responseError() == expectedErrors,
                  "TileLink fetch lost per-word access errors");
            if (responseReady) {
                check(aCount == 1 + unsigned((currentPc & 4) != 0) - unsigned(currentHit),
                      "TileLink fetch response arrived before all Gets");
                ++retired;
            } else ++responseStalls;
            cachedAddress = (currentPc & ~7ULL) + ((currentPc & 4) ? 8 : 0);
            cachedGood = cachedAddress >= base && cachedAddress < base + 8192 && !error(cachedAddress);
        }
        if (offered && dut.get_io$$tl$$d$$ready()) {
            if ((offered->source & 1) == 1 && !currentHit && !firstReturned) ++outOfOrder;
            if ((offered->source & 1) == 0) firstReturned = true;
            offered.reset();
        }
        if (request && dut.get_io$$fetch$$request$$ready()) {
            currentPc = pcs[issued];
            currentHit = (currentPc & 4) && cachedGood && cachedAddress == (currentPc & ~7ULL);
            if (currentHit) ++cacheHits;
            currentGroup = nextGroup;
            nextGroup ^= 1;
            aCount = 0;
            firstReturned = false;
            ++issued;
        }
        if (dut.get_io$$tl$$a$$valid()) {
            const unsigned source = dut.get_io$$tl$$a$$bits$$source();
            const uint64_t address = dut.get_io$$tl$$a$$bits$$address();
            if (stalledA) check(source == stalledA->first && address == stalledA->second,
                                "TileLink fetch A changed under backpressure");
            stalledA = !aReady ? std::make_optional(std::make_pair(source, address)) : std::nullopt;
            if (aReady) {
                const unsigned beatIndex = aCount + unsigned(currentHit);
                check(source == 2 * currentGroup + beatIndex &&
                      address == (currentPc & ~7ULL) + 8 * beatIndex &&
                      dut.get_io$$tl$$a$$bits$$opcode() == 4 &&
                      dut.get_io$$tl$$a$$bits$$size() == 3 &&
                      dut.get_io$$tl$$a$$bits$$mask() == 255,
                      "TileLink fetch Get address, source or size mismatch");
                pending.push_back({source, cycle + ((source & 1) == 0 ? 9U : 1U), beat(address),
                                   denied(address), corrupt(address)});
                ++aCount;
            } else ++aStalls;
        } else stalledA.reset();
    }
    if (issued != pcs.size() || retired != pcs.size() || !aStalls || !responseStalls ||
        !outOfOrder || !responseRequestOverlap || requestAOverlap != pcs.size() || !simultaneousAD ||
        cacheHits < 3) {
        std::cerr << "TileLink fetch coverage issued=" << issued << " retired=" << retired
                  << " aStalls=" << aStalls << " responseStalls=" << responseStalls
                  << " outOfOrderD=" << outOfOrder << " responseRequestOverlap=" << responseRequestOverlap
                  << " requestAOverlap=" << requestAOverlap << " simultaneousAD=" << simultaneousAD
                  << " cacheHits=" << cacheHits << '\n';
        throw std::runtime_error("TileLink fetch alignment, backpressure or out-of-order coverage missing");
    }
    offered.reset();
    drive(dut, false, 0, true, false, offered);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    std::vector<Reply> resetPending;
    bool resetAccepted = false, resetReturned = false;
    unsigned resetGets = 0;
    for (unsigned cycle = 0; cycle < 40 && !resetReturned; ++cycle) {
        if (!offered && !resetPending.empty() && resetPending.front().due <= cycle) {
            offered = resetPending.front();
            resetPending.erase(resetPending.begin());
        }
        drive(dut, !resetAccepted, base + 4, true, true, offered);
        dut.step();
        if (!resetAccepted && dut.get_io$$fetch$$request$$ready()) resetAccepted = true;
        if (dut.get_io$$tl$$a$$valid()) {
            const unsigned source = dut.get_io$$tl$$a$$bits$$source();
            const uint64_t address = dut.get_io$$tl$$a$$bits$$address();
            check(source == resetGets && address == base + 8 * resetGets,
                  "TileLink fetch retained a ROM beat across reset");
            resetPending.push_back({source, cycle + 2, beat(address), false});
            ++resetGets;
        }
        if (offered && dut.get_io$$tl$$d$$ready()) offered.reset();
        if (dut.get_io$$fetch$$response$$valid()) {
            check(dut.get_io$$fetch$$response$$bits() == packet(base + 4),
                  "TileLink fetch reset packet mismatch");
            resetReturned = true;
        }
    }
    check(resetAccepted && resetReturned && resetGets == 2,
          "TileLink fetch reset did not discard the ROM beat cache");
    SInstructionTileLinkBridge locked;
    std::optional<Reply> empty;
    drive(locked, false, 0, true, false, empty);
    locked.set_reset(1); locked.step(); locked.step(); locked.set_reset(0);
    auto tick = [&](bool request, uint64_t pc, bool aReady, std::optional<Reply> reply) {
        drive(locked, request, pc, true, aReady, reply);
        locked.step();
    };
    tick(true, base, true, empty);
    check(locked.get_io$$fetch$$request$$ready() && locked.get_io$$tl$$a$$bits$$source() == 0,
          "TileLink fetch cache warm-up request failed");
    tick(false, 0, true, Reply{0, 0, beat(base), false});
    check(locked.get_io$$fetch$$response$$valid(), "TileLink fetch cache warm-up response missing");
    tick(true, base + 0x20, true, empty);
    check(locked.get_io$$fetch$$request$$ready() && locked.get_io$$tl$$a$$bits$$source() == 2,
          "TileLink fetch second packet request failed");
    tick(true, base + 4, false, Reply{2, 0, beat(base + 0x20), false});
    check(locked.get_io$$tl$$a$$valid() && !locked.get_io$$fetch$$request$$ready() &&
          locked.get_io$$tl$$a$$bits$$source() == 1 &&
          locked.get_io$$tl$$a$$bits$$address() == base + 8,
          "TileLink fetch did not hold the cached beat decision under A backpressure");
    tick(true, base + 4, true, empty);
    check(locked.get_io$$fetch$$request$$ready() && locked.get_io$$tl$$a$$bits$$source() == 1 &&
          locked.get_io$$tl$$a$$bits$$address() == base + 8,
          "TileLink fetch changed its stalled A after a different beat completed");
    tick(false, 0, true, Reply{1, 0, beat(base + 8), false});
    check(locked.get_io$$fetch$$response$$valid() &&
          locked.get_io$$fetch$$response$$bits() == packet(base + 4),
          "TileLink fetch lost the held cached beat after backpressure");
    for (unsigned mask : {0U, 1U, 2U}) {
        SInstructionTileLinkBridge guarded;
        drive(guarded, false, 0, true, false, empty, mask);
        guarded.set_reset(1); guarded.step(); guarded.step(); guarded.set_reset(0);
        constexpr uint64_t boundary = base + 0xfc;
        if (mask == 1) {
            drive(guarded, true, boundary, true, false, empty, mask);
            guarded.step();
            check(!guarded.get_io$$fetch$$request$$ready() && guarded.get_io$$tl$$a$$valid() &&
                  guarded.get_io$$tl$$a$$bits$$address() == boundary &&
                  guarded.get_io$$tl$$a$$bits$$size() == 2 &&
                  guarded.get_io$$tl$$a$$bits$$mask() == 0xf0,
                  "protected word Get changed under A backpressure");
        }
        drive(guarded, true, boundary, true, true, empty, mask);
        guarded.step();
        check(guarded.get_io$$fetch$$request$$ready(), "protected fetch was not accepted");
        if (mask == 0) {
            check(!guarded.get_io$$tl$$a$$valid(), "denied packet issued a TileLink Get");
            drive(guarded, false, 0, false, false, empty, mask);
            guarded.step();
            check(guarded.get_io$$fetch$$response$$valid() &&
                  guarded.get_io$$fetch$$response$$bits() == 0 &&
                  guarded.get_io$$fetch$$responseError() == 3,
                  "denied packet did not hold its fault-only response");
        } else {
            const uint64_t address = boundary + (mask == 2 ? 4 : 0);
            check(guarded.get_io$$tl$$a$$valid() &&
                  guarded.get_io$$tl$$a$$bits$$address() == address &&
                  guarded.get_io$$tl$$a$$bits$$size() == 2 &&
                  guarded.get_io$$tl$$a$$bits$$mask() == (mask == 2 ? 0x0f : 0xf0) &&
                  guarded.get_io$$tl$$a$$bits$$source() == (mask == 2 ? 1 : 0),
                  "protected fetch issued a forbidden or oversized Get");
            const uint64_t data = uint64_t(word(address)) << ((address & 4) ? 32 : 0);
            drive(guarded, false, 0, true, true,
                  Reply{unsigned(mask == 2), 0, data, false, false, 2}, mask);
            guarded.step();
            check(guarded.get_io$$fetch$$response$$valid() &&
                  guarded.get_io$$fetch$$response$$bits() ==
                      (uint64_t(word(address)) << (mask == 2 ? 32 : 0)) &&
                  guarded.get_io$$fetch$$responseError() == (mask == 2 ? 1 : 2),
                  "protected fetch lost the allowed word or wrong fault lane");
        }
    }
    if (wrongSource) {
        offered = Reply{4, 0, 0, false};
        drive(dut, false, 0, true, true, offered);
        dut.step();
        throw std::runtime_error("TileLink fetch accepted an unsolicited D");
    }
    std::cout << "GSIM TileLink fetch: PASS packets=" << retired << " aStalls=" << aStalls
              << " responseStalls=" << responseStalls << " outOfOrderD=" << outOfOrder
              << " responseRequestOverlap=" << responseRequestOverlap
              << " simultaneousAD=" << simultaneousAD << " cacheHits=" << cacheHits
              << " resetGets=" << resetGets << '\n';
}
