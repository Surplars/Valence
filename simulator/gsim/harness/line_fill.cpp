#include "TileLinkLineFillGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0x9e3779b97f4a7c15ULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(STileLinkLineFillGsim &dut, bool request, uint64_t address, unsigned tag,
                  bool responseReady, bool dValid = false, unsigned source = 0,
                  unsigned beat = 0, bool denied = false, bool corrupt = false) {
    dut.set_io$$request$$valid(request);
    dut.set_io$$request$$bits$$address(address);
    dut.set_io$$request$$bits$$tag(tag);
    dut.set_io$$response$$ready(responseReady);
    dut.set_io$$tl$$a$$ready(1);
    dut.set_io$$tl$$d$$valid(dValid);
    dut.set_io$$tl$$d$$bits$$opcode(1); // AccessAckData
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(6);
    dut.set_io$$tl$$d$$bits$$source(source);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(denied);
    dut.set_io$$tl$$d$$bits$$data(lineWord(address, beat));
    dut.set_io$$tl$$d$$bits$$corrupt(corrupt);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$c$$ready(1);
    dut.set_io$$tl$$e$$ready(1);
}

static std::array<uint64_t, 8> responseWords(STileLinkLineFillGsim &dut) {
    return {dut.get_io$$word0(), dut.get_io$$word1(), dut.get_io$$word2(),
            dut.get_io$$word3(), dut.get_io$$word4(), dut.get_io$$word5(),
            dut.get_io$$word6(), dut.get_io$$word7()};
}

static void checkResponse(STileLinkLineFillGsim &dut, uint64_t address, unsigned tag,
                          bool error) {
    check(dut.get_io$$response$$valid() && dut.get_io$$response$$bits$$tag() == tag &&
          bool(dut.get_io$$response$$bits$$error()) == error,
          "line fill response tag or error mismatch");
    const auto words = responseWords(dut);
    for (unsigned beat = 0; beat < 8; ++beat)
        check(words[beat] == lineWord(address, beat), "line fill data beat mismatch");
}

int main() {
    STileLinkLineFillGsim dut;
    const uint64_t base = 0x80010000ULL;
    drive(dut, false, 0, 0, false);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);

    // Fill all four slots before returning any D beat. Each A Get is a single beat.
    std::array<unsigned, 4> sourceForRequest{};
    unsigned requests = 0, gets = 0;
    std::array<bool, 4> seenSource{};
    for (unsigned cycle = 0; cycle < 20 && (requests < 4 || gets < 4); ++cycle) {
        drive(dut, requests < 4, base + 64 * requests, 0x40 + requests, false);
        dut.step();
        check(!dut.get_io$$tl$$c$$valid() && !dut.get_io$$tl$$e$$valid(),
              "line fill unexpectedly emitted a coherence message");
        if (requests < 4 && dut.get_io$$request$$ready()) ++requests;
        if (dut.get_io$$tl$$a$$valid()) {
            const auto source = dut.get_io$$tl$$a$$bits$$source();
            check(source < 4 && !seenSource[source] &&
                  dut.get_io$$tl$$a$$bits$$opcode() == 4 &&
                  dut.get_io$$tl$$a$$bits$$size() == 6 &&
                  dut.get_io$$tl$$a$$bits$$mask() == 255 &&
                  dut.get_io$$tl$$a$$bits$$address() == base + 64 * gets,
                  "line fill issued incorrect or duplicate Get");
            sourceForRequest[gets] = source;
            seenSource[source] = true;
            ++gets;
        }
    }
    check(requests == 4 && gets == 4, "four line fills did not issue concurrently");
    check(sourceForRequest == std::array<unsigned, 4>{0, 1, 2, 3},
          "line fill source allocation changed unexpectedly");
    drive(dut, true, base + 256, 0x44, false);
    dut.step();
    check(!dut.get_io$$request$$ready(), "fifth line fill overcommitted slots");

    // TL D messages may return out of source order; their beats remain contiguous.
    // Keep the result port stalled so all four complete lines must remain buffered.
    for (unsigned index : {2U, 0U, 3U, 1U}) {
        for (unsigned beat = 0; beat < 8; ++beat) {
            const bool denied = index == 2 && beat == 0;
            const bool corrupt = index == 3 && beat == 5;
            drive(dut, false, base + 64 * index, 0x40 + index, false,
                  true, sourceForRequest[index], beat, denied, corrupt);
            dut.step();
            check(dut.get_io$$tl$$d$$ready(), "line fill stalled an outstanding D beat");
        }
    }
    for (unsigned cycle = 0; cycle < 3; ++cycle) {
        drive(dut, false, 0, 0, false);
        dut.step();
        checkResponse(dut, base, 0x40, false);
    }
    for (unsigned index = 0; index < 4; ++index) {
        drive(dut, false, 0, 0, true);
        dut.step();
        checkResponse(dut, base + 64 * index, 0x40 + index, index >= 2);
    }

    // The released slot must be reusable without changing the tags or data of
    // any earlier transaction.
    bool accepted = false, issued = false;
    for (unsigned cycle = 0; cycle < 8 && (!accepted || !issued); ++cycle) {
        drive(dut, !accepted, base + 256, 0x44, false);
        dut.step();
        if (!accepted && dut.get_io$$request$$ready()) accepted = true;
        if (dut.get_io$$tl$$a$$valid()) {
            check(dut.get_io$$tl$$a$$bits$$source() == 0 &&
                  dut.get_io$$tl$$a$$bits$$address() == base + 256,
                  "reused line fill slot issued wrong Get");
            issued = true;
        }
    }
    check(accepted && issued, "line fill slot was not reused");
    for (unsigned beat = 0; beat < 8; ++beat) {
        drive(dut, false, base + 256, 0x44, false, true, 0, beat);
        dut.step();
        check(dut.get_io$$tl$$d$$ready(), "reused line fill failed to accept D beat");
    }
    drive(dut, false, 0, 0, true);
    dut.step();
    checkResponse(dut, base + 256, 0x44, false);
    std::cout << "GSIM TileLink line fill: PASS fourInflight outOfOrderD backpressure errors reuse" << '\n';
}
