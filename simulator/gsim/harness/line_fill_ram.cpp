#include "TileLinkLineFillRamGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0x6a09e667f3bcc909ULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(STileLinkLineFillRamGsim &dut, bool request, uint64_t address,
                  unsigned tag, bool responseReady, bool program = false,
                  unsigned index = 0, uint64_t data = 0) {
    dut.set_io$$request$$valid(request);
    dut.set_io$$request$$bits$$address(address);
    dut.set_io$$request$$bits$$tag(tag);
    dut.set_io$$response$$ready(responseReady);
    dut.set_io$$programValid(program);
    dut.set_io$$programIndex(index);
    dut.set_io$$programData(data);
}

static std::array<uint64_t, 8> responseWords(STileLinkLineFillRamGsim &dut) {
    return {dut.get_io$$word0(), dut.get_io$$word1(), dut.get_io$$word2(),
            dut.get_io$$word3(), dut.get_io$$word4(), dut.get_io$$word5(),
            dut.get_io$$word6(), dut.get_io$$word7()};
}

int main() {
    STileLinkLineFillRamGsim dut;
    constexpr uint64_t base = 0x80010000ULL;
    drive(dut, false, 0, 0, false);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);

    for (unsigned line = 0; line < 4; ++line) {
        for (unsigned beat = 0; beat < 8; ++beat) {
            drive(dut, false, 0, 0, false, true, 8 * line + beat,
                  lineWord(base + 64 * line, beat));
            dut.step();
        }
    }

    unsigned issued = 0, completed = 0, maxOutstanding = 0, held = 0;
    for (unsigned cycle = 0; cycle < 4000 && completed < 5; ++cycle) {
        const bool ready = cycle % 7 >= 3;
        const uint64_t address = issued == 4 ? base + 4096 : base + 64 * issued;
        drive(dut, issued < 5, address, 0x60 + issued, ready);
        dut.step();
        if (issued < 5 && dut.get_io$$request$$ready()) ++issued;
        if (dut.get_io$$response$$valid()) {
            const bool error = completed == 4;
            if (!(issued > completed && dut.get_io$$response$$bits$$tag() == 0x60 + completed &&
                  bool(dut.get_io$$response$$bits$$error()) == error))
                std::cerr << "cycle=" << cycle << " issued=" << issued << " completed=" << completed
                          << " tag=" << unsigned(dut.get_io$$response$$bits$$tag())
                          << " error=" << unsigned(dut.get_io$$response$$bits$$error()) << '\n';
            check(issued > completed && dut.get_io$$response$$bits$$tag() == 0x60 + completed &&
                  bool(dut.get_io$$response$$bits$$error()) == error,
                  "RAM line fill tag, ordering or denied mismatch");
            const auto words = responseWords(dut);
            for (unsigned beat = 0; beat < 8; ++beat)
                check(words[beat] == (error ? 0 : lineWord(base + 64 * completed, beat)),
                      "RAM line fill data mismatch");
            if (ready) ++completed;
            else ++held;
        }
        maxOutstanding = std::max(maxOutstanding, issued - completed);
    }
    check(issued == 5 && completed == 5 && maxOutstanding == 4 && held > 0,
          "RAM line fill did not exercise four outstanding lines and response stalls");
    std::cout << "GSIM TileLink line fill RAM: PASS fourOutstanding fullLine denied backpressure" << '\n';
}
