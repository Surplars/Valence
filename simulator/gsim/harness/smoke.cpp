#include "GsimSmoke.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

int main() {
    SGsimSmoke dut;
    dut.set_reset(1);
    dut.set_io$$enable(0);
    dut.set_io$$write(0);
    dut.set_io$$read(0);
    dut.step();
    dut.step();
    check(dut.get_io$$count() == 0, "reset failed");
    dut.set_reset(0);
    dut.set_io$$lhs(UINT64_MAX);
    dut.set_io$$rhs(2);
    dut.set_io$$enable(1);
    for (unsigned i = 0; i < 16; ++i) {
        dut.step();
        // GSIM evaluates cycle outputs from the state preceding this step's register update.
        check(dut.get_io$$count() == i, "counter sampling/clock enable failed");
        check(dut.get_io$$sum() == 1, "64-bit wraparound failed");
    }
    dut.set_io$$enable(0);
    dut.step();
    check(dut.get_io$$count() == 16, "counter hold failed");
    dut.set_reset(1);
    dut.step();
    check(dut.get_io$$count() == 0, "warm reset failed");
    dut.set_reset(0);

    std::array<uint32_t, 8> expected{};
    dut.set_io$$write(1);
    dut.set_io$$mask(15);
    for (unsigned address = 0; address < expected.size(); ++address) {
        expected[address] = 0x10203040u + address;
        dut.set_io$$address(address);
        dut.set_io$$writeData(expected[address]);
        dut.step();
    }
    // All mask combinations, including preserving every byte and replacing every byte.
    for (unsigned mask = 0; mask < 16; ++mask) {
        const unsigned address = mask % 8;
        const uint32_t data = 0xa0b0c000u + mask;
        dut.set_io$$address(address);
        dut.set_io$$mask(mask);
        dut.set_io$$writeData(data);
        dut.step();
        for (unsigned byte = 0; byte < 4; ++byte) {
            if (mask & (1u << byte)) {
                const uint32_t byteMask = 0xffu << (8 * byte);
                expected[address] = (expected[address] & ~byteMask) | (data & byteMask);
            }
        }
    }
    dut.set_io$$write(0);
    dut.set_io$$read(1);
    for (unsigned address = 0; address < expected.size(); ++address) {
        dut.set_io$$address(address);
        dut.step();
        dut.set_io$$read(0);
        dut.step();
        check(dut.get_io$$readData() == expected[address], "synchronous memory/mask failed");
        dut.set_io$$read(1);
    }
    std::cout << "GSIM smoke: PASS (reset, cycle sampling, uint64 add, synchronous byte-mask memory)\n";
}
