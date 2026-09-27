#include "TileLinkLineProbeGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0x3c6ef372fe94f82bULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(STileLinkLineProbeGsim &dut, bool request, uint64_t requestAddress,
                  unsigned tag, bool bReady, bool resultReady, bool cValid = false,
                  uint64_t cAddress = 0, unsigned source = 0, unsigned opcode = 4,
                  unsigned param = 1, unsigned beat = 0, bool corrupt = false) {
    dut.set_io$$request$$valid(request);
    dut.set_io$$request$$bits$$address(requestAddress);
    dut.set_io$$request$$bits$$tag(tag);
    dut.set_io$$probe$$ready(bReady);
    dut.set_io$$response$$ready(resultReady);
    dut.set_io$$ack$$valid(cValid);
    dut.set_io$$ack$$bits$$opcode(opcode);
    dut.set_io$$ack$$bits$$param(param);
    dut.set_io$$ack$$bits$$size(6);
    dut.set_io$$ack$$bits$$source(source);
    dut.set_io$$ack$$bits$$address(cAddress);
    dut.set_io$$ack$$bits$$data(lineWord(cAddress, beat));
    dut.set_io$$ack$$bits$$corrupt(corrupt);
}

static std::array<uint64_t, 8> responseWords(STileLinkLineProbeGsim &dut) {
    return {dut.get_io$$word0(), dut.get_io$$word1(), dut.get_io$$word2(),
            dut.get_io$$word3(), dut.get_io$$word4(), dut.get_io$$word5(),
            dut.get_io$$word6(), dut.get_io$$word7()};
}

static void checkResponse(STileLinkLineProbeGsim &dut, uint64_t address, unsigned tag,
                          bool hasData, bool corrupt) {
    check(dut.get_io$$response$$valid() && dut.get_io$$response$$bits$$tag() == tag &&
          bool(dut.get_io$$response$$bits$$hasData()) == hasData &&
          bool(dut.get_io$$response$$bits$$corrupt()) == corrupt,
          "line probe result tag, data presence or corruption mismatch");
    const auto words = responseWords(dut);
    for (unsigned beat = 0; beat < 8; ++beat)
        check(words[beat] == (hasData ? lineWord(address, beat) : 0),
              "line probe returned a wrong dirty data beat");
}

int main(int argc, char **argv) {
    STileLinkLineProbeGsim dut;
    constexpr uint64_t base = 0x80010000ULL;
    drive(dut, false, 0, 0, false, false);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);

    std::array<unsigned, 4> sources{};
    std::array<bool, 4> seenSource{};
    unsigned requested = 0, probes = 0, heldB = 0;
    for (unsigned cycle = 0; cycle < 30 && (requested < 4 || probes < 4); ++cycle) {
        const bool ready = cycle % 3 != 1;
        drive(dut, requested < 4, base + 64 * requested, 0x50 + requested, ready, false);
        dut.step();
        if (requested < 4 && dut.get_io$$request$$ready()) ++requested;
        if (dut.get_io$$probe$$valid()) {
            const unsigned source = dut.get_io$$probe$$bits$$source();
            check(probes < 4 && source < 4 &&
                  dut.get_io$$probe$$bits$$opcode() == 6 &&
                  dut.get_io$$probe$$bits$$param() == 2 &&
                  dut.get_io$$probe$$bits$$size() == 6 &&
                  dut.get_io$$probe$$bits$$mask() == 255 &&
                  dut.get_io$$probe$$bits$$address() == base + 64 * probes,
                  "line probe B source, order or block metadata mismatch");
            if (ready) {
                check(!seenSource[source], "line probe reused a live source");
                seenSource[source] = true;
                sources[probes] = source;
                ++probes;
            } else ++heldB;
        }
    }
    check(requested == 4 && probes == 4 && heldB > 0,
          "four line probes did not issue under B backpressure");
    drive(dut, true, base + 256, 0x54, true, false);
    dut.step();
    check(!dut.get_io$$request$$ready(), "fifth line probe overcommitted slots");
    if (argc == 2 && std::string(argv[1]) == "--inject-interleave") {
        drive(dut, false, 0, 0, true, false, true,
              base + 128, sources[2], 5, 1, 0);
        dut.step();
        drive(dut, false, 0, 0, true, false, true,
              base + 64, sources[1], 4, 2);
        dut.step();
        throw std::runtime_error("interleaved C burst was accepted");
    }

    // Return independent C transactions out of B order. Dirty C messages hold
    // the channel for all eight beats, including a corrupted middle beat.
    for (unsigned index : {2U, 0U, 3U, 1U}) {
        const bool dirty = index == 2 || index == 3;
        for (unsigned beat = 0; beat < (dirty ? 8U : 1U); ++beat) {
            drive(dut, false, 0, 0, true, false, true,
                  base + 64 * index, sources[index], dirty ? 5 : 4,
                  index == 1 ? 2 : 1, beat, index == 2 && beat == 5);
            dut.step();
            check(dut.get_io$$ack$$ready(), "line probe stalled a valid C response beat");
        }
    }
    for (unsigned cycle = 0; cycle < 3; ++cycle) {
        drive(dut, false, 0, 0, true, false);
        dut.step();
        checkResponse(dut, base, 0x50, false, false);
    }
    drive(dut, false, 0, 0, true, true);
    dut.step();
    checkResponse(dut, base, 0x50, false, false);

    // A free slot exists, but a second probe of a still-occupied line must wait.
    drive(dut, true, base + 64, 0x60, true, false);
    dut.step();
    check(!dut.get_io$$request$$ready(), "same-line probe bypassed an outstanding result");
    drive(dut, true, base + 256, 0x54, true, false);
    dut.step();
    check(dut.get_io$$request$$ready(), "released probe slot was not reusable");

    // A zero-latency clean ProbeAck may coincide with the B handshake.
    drive(dut, false, 0, 0, true, false, true, base + 256, sources[0], 4, 5);
    dut.step();
    check(dut.get_io$$probe$$valid() && dut.get_io$$probe$$bits$$source() == sources[0] &&
          dut.get_io$$probe$$bits$$address() == base + 256 && dut.get_io$$ack$$ready(),
          "same-cycle B/C line probe failed");
    for (unsigned index : {4U, 1U, 2U, 3U}) {
        drive(dut, false, 0, 0, true, true);
        dut.step();
        checkResponse(dut, base + 64 * index, 0x50 + index,
                      index == 2 || index == 3, index == 2);
    }
    std::cout << "GSIM TileLink line probe: PASS fourInflight outOfOrderC dirtyData corrupt sameLine reuse" << '\n';
}
