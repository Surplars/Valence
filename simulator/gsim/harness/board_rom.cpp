#include "BoardRomGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>

static constexpr uint64_t base = 0x80000000ULL, bytes = 128 * 1024;
static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static uint32_t word(unsigned index) { return 0x76543210U ^ (index * 0x1020304U); }

int main() {
    SBoardRomGsim dut;
    dut.set_io$$write(0);
    dut.set_io$$requestValid(0);
    dut.set_io$$responseReady(0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    for (unsigned i = 0; i < 4; ++i) {
        for (unsigned index : {i, 32764U + i}) {
            dut.set_io$$write(1);
            dut.set_io$$index(index);
            dut.set_io$$data(word(index));
            dut.step();
        }
    }
    dut.set_io$$write(0);
    dut.step();
    unsigned transactions = 0, faults = 0, stalls = 0;
    for (unsigned size = 0; size < 4; ++size) {
        const unsigned count = 1U << size;
        for (unsigned region = 0; region < 4; ++region) {
            const uint64_t begin = region == 0 ? base : region == 1 ? base + bytes - 16 :
                                   region == 2 ? base - 16 : base + bytes;
            for (unsigned offset = 0; offset < 16; offset += count) {
                const uint64_t address = begin + offset;
                const bool error = address < base || address + count > base + bytes;
                const unsigned lane = address & 7;
                const unsigned laneMask = ((1U << count) - 1) << lane;
                bool accepted = false, returned = false;
                for (unsigned cycle = 0; cycle < 80 && !returned; ++cycle) {
                    const bool ready = cycle >= 7;
                    dut.set_io$$requestValid(!accepted);
                    dut.set_io$$address(address);
                    dut.set_io$$size(size);
                    dut.set_io$$mask(laneMask);
                    dut.set_io$$responseReady(ready);
                    dut.step();
                    if (dut.get_io$$responseValid()) {
                        check(bool(dut.get_io$$responseError()) == error, "ROM boundary error mismatch");
                        if (!error) {
                            const unsigned index = ((address - base) & ~7ULL) / 4;
                            const uint64_t expected = uint64_t(word(index + 1)) << 32 | word(index);
                            uint64_t mask = 0;
                            for (unsigned i = 0; i < count; ++i) mask |= 255ULL << ((lane + i) * 8);
                            check((dut.get_io$$responseData() & mask) == (expected & mask),
                                  "ROM byte/halfword/word/beat data mismatch");
                        }
                        if (ready) returned = true;
                        else ++stalls;
                    }
                    if (!accepted && dut.get_io$$requestReady()) accepted = true;
                }
                check(accepted && returned, "ROM transfer failed to complete");
                dut.set_io$$requestValid(0);
                dut.step();
                ++transactions;
                faults += error;
            }
        }
    }
    check(stalls > 0 && faults > 0, "ROM coverage missing");
    std::cout << "GSIM board ROM: PASS transactions=" << transactions << " faults=" << faults
              << " stalledResponses=" << stalls
              << " sizes=1/2/4/8 finalBytes=checked capacity=128KiB\n";
}
