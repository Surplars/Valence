#include "TileLinkLineAcquireGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0x6a09e667f3bcc909ULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(STileLinkLineAcquireGsim &dut, bool request, uint64_t address,
                  unsigned tag, unsigned grow, bool permissionOnly, bool aReady,
                  bool eReady, bool resultReady, bool dValid = false,
                  unsigned source = 0, unsigned sink = 0, unsigned opcode = 5,
                  unsigned cap = 0, unsigned beat = 0, bool denied = false,
                  bool corrupt = false) {
    dut.set_io$$request$$valid(request);
    dut.set_io$$request$$bits$$address(address);
    dut.set_io$$request$$bits$$tag(tag);
    dut.set_io$$request$$bits$$grow(grow);
    dut.set_io$$request$$bits$$permissionOnly(permissionOnly);
    dut.set_io$$a$$ready(aReady);
    dut.set_io$$e$$ready(eReady);
    dut.set_io$$response$$ready(resultReady);
    dut.set_io$$d$$valid(dValid);
    dut.set_io$$d$$bits$$opcode(opcode);
    dut.set_io$$d$$bits$$param(cap);
    dut.set_io$$d$$bits$$size(6);
    dut.set_io$$d$$bits$$source(source);
    dut.set_io$$d$$bits$$sink(sink);
    dut.set_io$$d$$bits$$denied(denied);
    dut.set_io$$d$$bits$$data(lineWord(address, beat));
    dut.set_io$$d$$bits$$corrupt(corrupt);
}

static std::array<uint64_t, 8> responseWords(STileLinkLineAcquireGsim &dut) {
    return {dut.get_io$$word0(), dut.get_io$$word1(), dut.get_io$$word2(),
            dut.get_io$$word3(), dut.get_io$$word4(), dut.get_io$$word5(),
            dut.get_io$$word6(), dut.get_io$$word7()};
}

static void checkResponse(STileLinkLineAcquireGsim &dut, uint64_t address, unsigned tag,
                          bool hasData, unsigned cap, bool error) {
    check(dut.get_io$$response$$valid() && dut.get_io$$response$$bits$$tag() == tag &&
          bool(dut.get_io$$response$$bits$$hasData()) == hasData &&
          dut.get_io$$response$$bits$$cap() == cap &&
          bool(dut.get_io$$response$$bits$$error()) == error,
          "line acquire result tag, cap, data presence or error mismatch");
    const auto words = responseWords(dut);
    for (unsigned beat = 0; beat < 8; ++beat)
        check(words[beat] == (hasData ? lineWord(address, beat) : 0),
              "line acquire returned an incorrect GrantData beat");
}

int main(int argc, char **argv) {
    STileLinkLineAcquireGsim dut;
    constexpr uint64_t base = 0x80010000ULL;
    drive(dut, false, 0, 0, 0, false, false, false, false);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);

    std::array<unsigned, 4> sourceForRequest{};
    std::array<bool, 4> seenSource{};
    unsigned requested = 0, acquired = 0, heldA = 0;
    for (unsigned cycle = 0; cycle < 30 && (requested < 4 || acquired < 4); ++cycle) {
        const bool ready = cycle % 3 != 1;
        const bool permissionOnly = requested == 1 || requested == 3;
        drive(dut, requested < 4, base + 64 * requested, 0x40 + requested,
              requested % 3, permissionOnly, ready, false, false);
        dut.step();
        if (requested < 4 && dut.get_io$$request$$ready()) ++requested;
        if (dut.get_io$$a$$valid()) {
            const unsigned source = dut.get_io$$a$$bits$$source();
            const bool issuedPerm = acquired == 1 || acquired == 3;
            check(acquired < 4 && source < 4 && !seenSource[source] &&
                  dut.get_io$$a$$bits$$opcode() == (issuedPerm ? 7U : 6U) &&
                  dut.get_io$$a$$bits$$param() == acquired % 3 &&
                  dut.get_io$$a$$bits$$size() == 6 &&
                  dut.get_io$$a$$bits$$mask() == 255 &&
                  dut.get_io$$a$$bits$$address() == base + 64 * acquired,
                  "line acquire A metadata, ordering or source mismatch");
            if (ready) {
                seenSource[source] = true;
                sourceForRequest[acquired] = source;
                ++acquired;
            } else ++heldA;
        }
    }
    check(requested == 4 && acquired == 4 && heldA > 0,
          "four line acquires did not issue under A backpressure");
    drive(dut, true, base + 256, 0x44, 1, false, true, false, false);
    dut.step();
    check(!dut.get_io$$request$$ready(), "fifth line acquire overcommitted slots");

    if (argc == 2 && std::string(argv[1]) == "--inject-interleave") {
        drive(dut, false, 0, 0, 0, false, true, false, false, true,
              sourceForRequest[2], 2, 5, 0, 0);
        dut.step();
        drive(dut, false, 0, 0, 0, false, true, false, false, true,
              sourceForRequest[1], 1, 4, 1);
        dut.step();
        throw std::runtime_error("interleaved D burst was accepted");
    }

    // Complete grants out of A order. Each data-bearing D message occupies all
    // eight beats; E is held back until every independent D transaction finishes.
    for (unsigned index : {2U, 0U, 3U, 1U}) {
        const bool permissionOnly = index == 1 || index == 3;
        for (unsigned beat = 0; beat < (permissionOnly ? 1U : 8U); ++beat) {
            drive(dut, false, base + 64 * index, 0, 0, false, true, false, false,
                  true, sourceForRequest[index], index, permissionOnly ? 4 : 5,
                  index % 2, beat, false, index == 2 && beat == 5);
            dut.step();
            check(dut.get_io$$d$$ready(), "line acquire stalled a valid Grant beat");
        }
    }
    for (unsigned cycle = 0; cycle < 3; ++cycle) {
        drive(dut, false, 0, 0, 0, false, true, false, true);
        dut.step();
        check(dut.get_io$$e$$valid() && dut.get_io$$e$$bits$$sink() == 2 &&
              !dut.get_io$$response$$valid(),
              "line acquire exposed data before the E-channel GrantAck");
    }
    for (unsigned index : {2U, 0U, 3U, 1U}) {
        drive(dut, false, 0, 0, 0, false, true, true, false);
        dut.step();
        check(dut.get_io$$e$$valid() && dut.get_io$$e$$bits$$sink() == index,
              "line acquire E ack sink or ordering mismatch");
        if (index != 2) checkResponse(dut, base + 128, 0x42, true, 0, true);
    }
    // Result2 was offered while stalled before lower source0 completed E.
    for (unsigned index : {2U, 0U, 1U, 3U}) {
        drive(dut, false, 0, 0, 0, false, true, true, true);
        dut.step();
        checkResponse(dut, base + 64 * index, 0x40 + index,
                      index == 0 || index == 2, index % 2, index == 2);
    }

    // Reuse the released source. A zero-latency manager may return a Grant in
    // the very cycle its AcquirePerm handshakes on A.
    drive(dut, true, base + 256, 0x44, 2, true, true, false, false);
    dut.step();
    check(dut.get_io$$request$$ready(), "line acquire slot was not reusable");
    drive(dut, false, base + 256, 0, 0, false, true, false, false,
          true, 0, 3, 4, 2);
    dut.step();
    check(dut.get_io$$a$$valid() && dut.get_io$$a$$bits$$source() == 0 &&
          dut.get_io$$a$$bits$$address() == base + 256 &&
          dut.get_io$$d$$ready(), "same-cycle A/D Grant was not accepted");
    drive(dut, false, 0, 0, 0, false, true, false, false);
    dut.step();
    check(dut.get_io$$e$$valid() && dut.get_io$$e$$bits$$sink() == 3 &&
          !dut.get_io$$response$$valid(), "reused Grant completed before E ack");
    drive(dut, false, 0, 0, 0, false, true, true, false);
    dut.step();
    check(dut.get_io$$e$$valid() && dut.get_io$$e$$bits$$sink() == 3,
          "reused GrantAck sink mismatch");
    drive(dut, false, 0, 0, 0, false, true, true, true);
    dut.step();
    checkResponse(dut, base + 256, 0x44, false, 2, false);
    std::cout << "GSIM TileLink line acquire: PASS fourInflight outOfOrderD "
                 "GrantData Grant Ebackpressure corrupt reuse immediateGrant" << '\n';
}
