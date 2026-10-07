#include "UartConsole.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

static void check(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}

struct Test {
    SUartConsole dut;
    uint64_t cycles = 0;
    uint32_t hostFraction = 0;

    void tick() { dut.step(); ++cycles; }

    Test() {
        dut.set_io$$rx(1);
        dut.set_io$$mmio$$request$$valid(0);
        dut.set_io$$mmio$$response$$ready(0);
        dut.set_io$$mmio$$request$$bits$$address(0);
        dut.set_io$$mmio$$request$$bits$$write(0);
        dut.set_io$$mmio$$request$$bits$$data(0);
        dut.set_io$$mmio$$request$$bits$$size(0);
        dut.set_io$$mmio$$request$$bits$$byteEnable(1);
        dut.set_reset(1);
        tick(); tick();
        dut.set_reset(0);
    }

    uint32_t access(unsigned offset, bool write = false, unsigned value = 0) {
        dut.set_io$$mmio$$request$$valid(1);
        dut.set_io$$mmio$$request$$bits$$address(0x10000000ULL + offset);
        dut.set_io$$mmio$$request$$bits$$write(write);
        dut.set_io$$mmio$$request$$bits$$data(value);
        unsigned waited = 0;
        do {
            tick();
            check(++waited < 1000, "MMIO request stalled");
        } while (!dut.get_io$$mmio$$request$$ready());
        dut.set_io$$mmio$$request$$valid(0);
        tick();
        check(dut.get_io$$mmio$$response$$valid(), "MMIO response missing");
        uint32_t result = dut.get_io$$mmio$$response$$bits$$data();
        check(!dut.get_io$$mmio$$response$$bits$$error(), "MMIO error");
        dut.set_io$$mmio$$response$$ready(1);
        tick();
        dut.set_io$$mmio$$response$$ready(0);
        return result;
    }

    unsigned bitCycles() {
        unsigned result = 26;
        hostFraction += 1000000;
        if (hostFraction >= 1500000) {
            hostFraction -= 1500000;
            ++result;
        }
        return result;
    }

    void rxByte(unsigned value) {
        for (unsigned bit = 0; bit < 10; ++bit) {
            dut.set_io$$rx(bit == 0 ? 0 : bit == 9 ? 1 : (value >> (bit - 1)) & 1);
            for (unsigned cycle = bitCycles(); cycle != 0; --cycle) tick();
        }
        dut.set_io$$rx(1);
        for (unsigned cycle = bitCycles(); cycle != 0; --cycle) tick();
    }
};

int main() {
    try {
        Test test;
        test.access(3, true, 0x83);
        test.access(0, true, 1);
        test.access(1, true, 0);
        test.access(3, true, 3);
        check(test.access(0, true, 0x55) == 0, "TX write");
        std::vector<uint64_t> edges;
        bool previous = true;
        for (unsigned i = 0; i < 330; ++i) {
            test.tick();
            bool level = test.dut.get_io$$tx();
            if (level != previous) edges.push_back(test.cycles);
            previous = level;
        }
        check(edges.size() == 10, "expected ten edges for alternating 0x55 frame");
        for (unsigned i = 2; i < edges.size(); ++i) {
            unsigned interval = edges[i] - edges[i - 1];
            check(interval == 26 || interval == 27, "fractional TX bit period");
        }
        check(edges.back() - edges[1] >= 212 && edges.back() - edges[1] <= 214,
              "1.5 Mbaud average TX period");
        for (unsigned value : std::array<unsigned, 8>{0x00, 0xff, 0x55, 0xaa,
                                                       0xc3, 0x3c, 0x81, 0x7e}) {
            test.rxByte(value);
            check(test.access(5) & 1, "RX data-ready missing");
            check(test.access(0) == value, "fractional RX byte mismatch");
            check(!(test.access(5) & 0x0a), "RX framing or overrun");
        }
        std::cout << "GSIM board UART 1.5 Mbaud: PASS cycles=" << test.cycles << "\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM board UART 1.5 Mbaud: FAIL " << error.what() << "\n";
        return 1;
    }
}
