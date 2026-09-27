#include "TileLinkLineWriteGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0x243f6a8885a308d3ULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(STileLinkLineWriteGsim &dut, bool request, uint64_t address, unsigned tag,
                  bool aReady, bool responseReady, bool dValid = false, unsigned source = 0,
                  bool denied = false) {
    dut.set_io$$request$$valid(request);
    dut.set_io$$request$$bits$$address(address);
    dut.set_io$$request$$bits$$tag(tag);
    dut.set_io$$word0(lineWord(address, 0));
    dut.set_io$$word1(lineWord(address, 1));
    dut.set_io$$word2(lineWord(address, 2));
    dut.set_io$$word3(lineWord(address, 3));
    dut.set_io$$word4(lineWord(address, 4));
    dut.set_io$$word5(lineWord(address, 5));
    dut.set_io$$word6(lineWord(address, 6));
    dut.set_io$$word7(lineWord(address, 7));
    dut.set_io$$response$$ready(responseReady);
    dut.set_io$$tl$$a$$ready(aReady);
    dut.set_io$$tl$$d$$valid(dValid);
    dut.set_io$$tl$$d$$bits$$opcode(0); // AccessAck
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(6);
    dut.set_io$$tl$$d$$bits$$source(source);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(denied);
    dut.set_io$$tl$$d$$bits$$data(0);
    dut.set_io$$tl$$d$$bits$$corrupt(0);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$c$$ready(1);
    dut.set_io$$tl$$e$$ready(1);
}

int main() {
    STileLinkLineWriteGsim dut;
    constexpr uint64_t base = 0x80010000ULL;
    drive(dut, false, 0, 0, false, false);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);

    std::array<unsigned, 4> sourceForRequest{};
    std::array<bool, 4> seenSource{};
    unsigned requests = 0, aBeats = 0, heldA = 0;
    for (unsigned cycle = 0; cycle < 120 && (requests < 4 || aBeats < 32); ++cycle) {
        const bool ready = cycle % 3 != 1;
        drive(dut, requests < 4, base + 64 * requests, 0x30 + requests, ready, false);
        dut.step();
        check(!dut.get_io$$tl$$c$$valid() && !dut.get_io$$tl$$e$$valid(),
              "line write unexpectedly emitted a coherence message");
        if (requests < 4 && dut.get_io$$request$$ready()) ++requests;
        if (dut.get_io$$tl$$a$$valid()) {
            const unsigned index = aBeats / 8, beat = aBeats % 8;
            const unsigned source = dut.get_io$$tl$$a$$bits$$source();
            check(index < 4 && source < 4 &&
                  dut.get_io$$tl$$a$$bits$$opcode() == 0 &&
                  dut.get_io$$tl$$a$$bits$$size() == 6 &&
                  dut.get_io$$tl$$a$$bits$$mask() == 255 &&
                  dut.get_io$$tl$$a$$bits$$address() == base + 64 * index &&
                  dut.get_io$$tl$$a$$bits$$data() == lineWord(base + 64 * index, beat),
                  "line write A burst changed source, address, beat order or data");
            if (beat == 0 && ready) {
                check(!seenSource[source], "line write reused a live source");
                seenSource[source] = true;
                sourceForRequest[index] = source;
            } else if (beat != 0) {
                check(sourceForRequest[index] == source, "line write A source changed within burst");
            }
            if (ready) ++aBeats;
            else ++heldA;
        }
    }
    check(requests == 4 && aBeats == 32 && heldA > 0,
          "four line writes did not issue under A backpressure");
    drive(dut, true, base + 256, 0x34, true, false);
    dut.step();
    check(!dut.get_io$$request$$ready(), "fifth line write overcommitted slots");

    for (unsigned index : {3U, 1U, 2U, 0U}) {
        drive(dut, false, 0, 0, true, false, true, sourceForRequest[index], index == 2);
        dut.step();
        check(dut.get_io$$tl$$d$$ready(), "line write stalled a pending D acknowledgement");
    }
    for (unsigned cycle = 0; cycle < 3; ++cycle) {
        drive(dut, false, 0, 0, true, false);
        dut.step();
        check(dut.get_io$$response$$valid() && dut.get_io$$response$$bits$$tag() == 0x30 &&
              !dut.get_io$$response$$bits$$error(), "backpressured line write result changed");
    }
    for (unsigned index = 0; index < 4; ++index) {
        drive(dut, false, 0, 0, true, true);
        dut.step();
        check(dut.get_io$$response$$valid() && dut.get_io$$response$$bits$$tag() == 0x30 + index &&
              bool(dut.get_io$$response$$bits$$error()) == (index == 2),
              "line write response tag or denied mismatch");
    }

    bool accepted = false;
    unsigned reusedBeats = 0;
    for (unsigned cycle = 0; cycle < 20 && (!accepted || reusedBeats < 8); ++cycle) {
        const bool immediateAck = accepted && reusedBeats == 7;
        drive(dut, !accepted, base + 256, 0x34, true, false,
              immediateAck, sourceForRequest[0]);
        dut.step();
        if (!accepted && dut.get_io$$request$$ready()) accepted = true;
        if (dut.get_io$$tl$$a$$valid()) {
            check(dut.get_io$$tl$$a$$bits$$source() == sourceForRequest[0] &&
                  dut.get_io$$tl$$a$$bits$$data() == lineWord(base + 256, reusedBeats),
                  "reused line write slot issued wrong beat");
            ++reusedBeats;
        }
        if (immediateAck)
            check(dut.get_io$$tl$$d$$ready(), "same-cycle final A/D acknowledgement stalled");
    }
    check(accepted && reusedBeats == 8, "line write slot was not reused");
    drive(dut, false, 0, 0, true, true);
    dut.step();
    check(dut.get_io$$response$$valid() && dut.get_io$$response$$bits$$tag() == 0x34 &&
          !dut.get_io$$response$$bits$$error(), "reused line write result mismatch");
    std::cout << "GSIM TileLink line write: PASS fourInflight burstLock outOfOrderAck denied reuse" << '\n';
}
