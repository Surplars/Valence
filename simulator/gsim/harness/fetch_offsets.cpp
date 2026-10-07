#include "FetchOffsetsGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#ifndef FETCH_WIDTH
#define FETCH_WIDTH 2
#endif
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
static uint16_t half(uint64_t address) {
    // Both 32-bit words crossing byte 6 and compressed runs, unrelated to DUT decode.
    if (((address >> 1) & 3) == 3) return 0x0093;
    return uint16_t(0x0001 | ((address >> 4) & 0x7ff0));
}
static uint32_t instruction(uint64_t address) {
    const auto first = half(address);
    return first | ((first & 3) == 3 ? uint32_t(half(address + 2)) << 16 : 0);
}
static bool errorAt(uint64_t address) { return ((address >> 2) & 15) == 3; }
static bool pageAt(uint64_t address) { return ((address >> 2) & 15) == 11; }
static uint64_t packet(uint64_t address) {
    uint64_t data = 0;
    for (unsigned h = 0; h < 4; ++h) data |= uint64_t(half(address + 2*h)) << (16*h);
    return data;
}
#ifndef STABLE_FAULT_METADATA
#define STABLE_FAULT_METADATA 0
#endif
static void metadataKillTest() {
    for (uint64_t pc : {UINT64_C(0x8000000c), UINT64_C(0x8000002c)}) {
        SFetchOffsetsGsim dut;
        dut.set_io$$pc(pc); dut.set_io$$enable(0); dut.set_io$$invalidate(0);
        dut.set_io$$pause(0); dut.set_io$$virtualized(0); dut.set_io$$requestReady(1);
        dut.set_io$$responseValid(0); dut.set_io$$responseLow(0); dut.set_io$$responseHigh(0);
        dut.set_io$$responseErrors(0); dut.set_io$$responsePages(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        dut.set_io$$enable(1); dut.step();
        check(dut.get_io$$requestValid(), "metadata fixture request");
        const uint64_t address = dut.get_io$$requestAddress();
        unsigned errors = 0, pages = 0;
        for (unsigned word = 0; word < FETCH_WIDTH; ++word) {
            errors |= unsigned(errorAt(address + 4*word)) << word;
            pages |= unsigned(pageAt(address + 4*word)) << word;
        }
        dut.set_io$$requestReady(0); dut.set_io$$responseValid(1);
        dut.set_io$$responseLow(packet(address)); dut.set_io$$responseHigh(packet(address + 8));
        dut.set_io$$responseErrors(errors); dut.set_io$$responsePages(pages); dut.step();
        check(dut.get_io$$lane0$$valid(), "metadata fixture response");
        dut.set_io$$responseValid(0); dut.set_io$$pause(1); dut.set_io$$enable(0); dut.step();
        check(!dut.get_io$$lane0$$valid() && dut.get_io$$lane0$$bits() == instruction(pc) &&
              bool(dut.get_io$$errors() & 1) == errorAt(pc) &&
              bool(dut.get_io$$pages() & 1) == pageAt(pc), "disable changed fetch metadata payload");
        dut.set_io$$enable(1); dut.set_io$$invalidate(1); dut.step();
        check(!dut.get_io$$lane0$$valid() && !dut.get_io$$lane1$$valid() &&
              dut.get_io$$lane0$$bits() == instruction(pc) &&
              bool(dut.get_io$$errors() & 1) == errorAt(pc) &&
              bool(dut.get_io$$pages() & 1) == pageAt(pc), "invalidate changed fetch metadata payload");
    }
    std::cout << "GSIM fetch metadata kill isolation: PASS access/page disable/invalidate\n";
}
int main(int argc, char **) {
    try {
        SFetchOffsetsGsim dut;
        uint64_t pc = 0x80000000ULL, pendingAddress = 0, heldAddress = 0;
        unsigned delay = 0, heldMask = 0, checked = 0, checkedLast = 0, faultChecks = 0, requests = 0;
        bool pending = false, held = false;
        dut.set_io$$pc(pc); dut.set_io$$enable(0); dut.set_io$$invalidate(0);
        dut.set_io$$pause(1); dut.set_io$$virtualized(0); dut.set_io$$requestReady(0);
        dut.set_io$$responseValid(0); dut.set_io$$responseLow(0); dut.set_io$$responseHigh(0);
        dut.set_io$$responseErrors(0); dut.set_io$$responsePages(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        for (unsigned cycle = 0; cycle < 10000; ++cycle) {
            const bool enable = cycle % 13 != 0, invalidate = cycle % 89 == 17;
            const bool ready = cycle % 5 != 0, reply = pending && !delay;
            unsigned errorMask = 0, pageMask = 0;
            for (unsigned w = 0; w < FETCH_WIDTH; ++w) {
                errorMask |= unsigned(errorAt(pendingAddress + 4*w)) << w;
                pageMask |= unsigned(pageAt(pendingAddress + 4*w)) << w;
            }
            dut.set_io$$pc(pc); dut.set_io$$enable(enable); dut.set_io$$invalidate(invalidate);
            dut.set_io$$pause(cycle % 23 == 0);
            dut.set_io$$virtualized((cycle / 131) & 1);
            dut.set_io$$requestReady(ready); dut.set_io$$responseValid(reply);
            dut.set_io$$responseLow(packet(pendingAddress));
            dut.set_io$$responseHigh(packet(pendingAddress + 8));
            dut.set_io$$responseErrors(errorMask); dut.set_io$$responsePages(pageMask);
            dut.step();
            if (held) check(dut.get_io$$requestValid() && dut.get_io$$requestAddress() == heldAddress &&
                            dut.get_io$$requestMask() == heldMask, "held request changed");
            held = dut.get_io$$requestValid() && !ready;
            if (held) { heldAddress = dut.get_io$$requestAddress(); heldMask = dut.get_io$$requestMask(); }
            if (reply && dut.get_io$$responseReady()) pending = false;
            if (dut.get_io$$requestValid() && ready) {
                check(!pending, "multiple outstanding fetches");
                check(dut.get_io$$requestMask() == (FETCH_WIDTH == 4 ? 15 : 3), "unexpected mask");
                pending = true; pendingAddress = dut.get_io$$requestAddress();
                delay = 1 + cycle % 7; ++requests;
            } else if (delay) --delay;
            const bool valid[4] = {bool(dut.get_io$$lane0$$valid()), bool(dut.get_io$$lane1$$valid()),
                                  bool(dut.get_io$$lane2$$valid()), bool(dut.get_io$$lane3$$valid())};
            const uint32_t bits[4] = {dut.get_io$$lane0$$bits(), dut.get_io$$lane1$$bits(),
                                     dut.get_io$$lane2$$bits(), dut.get_io$$lane3$$bits()};
            const uint64_t faults[4] = {dut.get_io$$fault0(), dut.get_io$$fault1(),
                                       dut.get_io$$fault2(), dut.get_io$$fault3()};
            uint64_t address = pc;
            unsigned prefix = 0;
            for (unsigned lane = 0; lane < 4; ++lane) {
                if (lane >= FETCH_WIDTH) check(!valid[lane], "extra instruction lane");
                if (valid[lane]) {
                    check(enable && !invalidate, "disabled/stale instruction exposed");
                    check(lane == 0 || valid[lane - 1], "non-contiguous prefix");
                    const uint32_t want = instruction(address);
                    check((bits[lane] ^ (argc > 1 ? 1U : 0U)) == want, "mixed-length instruction mismatch");
                    const bool longWord = (want & 3) == 3;
                    const bool e = errorAt(address) || (longWord && errorAt(address + 2));
                    const bool p = pageAt(address) || (longWord && pageAt(address + 2));
                    check(bool((dut.get_io$$errors() >> lane) & 1) == e, "access fault metadata");
                    check(bool((dut.get_io$$pages() >> lane) & 1) == p, "page fault metadata");
                    if (e || p) {
                        const uint64_t wantFault = errorAt(address) || pageAt(address) ? address : address + 2;
                        check(faults[lane] == wantFault, "fault tval address");
                        ++faultChecks;
                    }
                    address += longWord ? 4 : 2; ++prefix; ++checked;
                    if (lane + 1 == FETCH_WIDTH) ++checkedLast;
                }
            }
            // A supply stall is not an acceptance. Advance from the independent
            // fixture only when the chosen contiguous prefix actually exists.
            if (prefix && cycle % 4 != 0) {
                const unsigned take = 1 + cycle % prefix;
                for (unsigned lane = 0; lane < take; ++lane) pc += (instruction(pc) & 3) == 3 ? 4 : 2;
            }
            if (cycle % 173 == 0) pc = 0x80000000ULL + ((cycle * 14) & 1022);
            if (cycle % 997 == 0) pc = UINT64_MAX - 29; // 64-bit wrap and packet boundary.
        }
        check(checked > 1000 && checkedLast > 100 && faultChecks > 100 && requests > 100,
              "insufficient boundary/fault/width coverage");
        std::cout << "GSIM fetch offsets: PASS width=" << FETCH_WIDTH << " instructions=" << checked
                  << " fullWidth=" << checkedLast << " faults=" << faultChecks << " requests=" << requests << "\n";
        if (STABLE_FAULT_METADATA) metadataKillTest();
    } catch (const std::exception &error) {
        std::cerr << "GSIM fetch offsets: FAIL " << error.what() << "\n"; return 1;
    }
}
