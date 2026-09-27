#include "MachineCoreGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

int main(int argc, char **argv) {
    try {
        check(argc == 5, "usage: machine_aia_s_uart image.bin wait-pc done-pc fail-pc");
        std::ifstream input(argv[1], std::ios::binary);
        check(bool(input), "firmware image open failed");
        const std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(input)), {});
        check(bytes.size() <= 8192 && bytes.size() % 4 == 0, "firmware image does not fit ROM");
        const uint64_t waitPc = std::stoull(argv[2], nullptr, 16);
        const uint64_t donePc = std::stoull(argv[3], nullptr, 16);
        const uint64_t failPc = std::stoull(argv[4], nullptr, 16);
        SMachineCoreGsim dut;
        dut.set_io$$programHold(0);
        dut.set_io$$programWrite(0);
        dut.set_io$$programIndex(0);
        dut.set_io$$programData(0);
        dut.set_io$$timerInterrupt(0);
        dut.set_io$$timerTick(0);
        dut.set_io$$timeValue(0);
        dut.set_io$$sources(0);
        dut.set_io$$uartRx(1);
        dut.set_io$$commitEnable(1);
        dut.set_io$$inspectRegister(0);
        dut.set_io$$instruction0$$valid(0);
        dut.set_io$$instruction0$$bits(0);
        dut.set_io$$instruction1$$valid(0);
        dut.set_io$$instruction1$$bits(0);
        dut.set_io$$memory$$request$$ready(0);
        dut.set_io$$memory$$response$$valid(0);
        dut.set_io$$memory$$response$$bits$$data(0);
        dut.set_io$$memory$$response$$bits$$error(0);
        dut.set_io$$msi$$request$$valid(0);
        dut.set_io$$msi$$request$$bits$$address(0);
        dut.set_io$$msi$$request$$bits$$data(0);
        dut.set_io$$msi$$request$$bits$$size(0);
        dut.set_io$$msi$$request$$bits$$byteEnable(0);
        dut.set_io$$msi$$request$$bits$$write(0);
        dut.set_io$$msi$$response$$ready(1);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
        dut.set_io$$programHold(1);
        dut.step();
        dut.step();
        for (unsigned word = 0; word < 2048; ++word) {
            const size_t byte = size_t(word) * 4;
            uint32_t value = 0;
            for (unsigned lane = 0; lane < 4 && byte + lane < bytes.size(); ++lane)
                value |= uint32_t(bytes[byte + lane]) << (8 * lane);
            dut.set_io$$programWrite(1);
            dut.set_io$$programIndex(word);
            dut.set_io$$programData(value);
            dut.step();
        }
        dut.set_io$$programWrite(0);
        dut.step();
        dut.set_io$$programHold(0);

        bool enteredSupervisor = false, sawSupervisorPending = false, sawTrap = false, done = false;
        uint64_t lastPc = 0;
        unsigned cycle = 0;
        auto advance = [&](bool receive = true) {
            dut.set_io$$uartRx(receive);
            dut.step();
            ++cycle;
            check(!dut.get_io$$msiError(), "APLIC MSI failed");
            sawSupervisorPending |= (dut.get_io$$externalPending() & 2) != 0;
            if (dut.get_io$$trap$$valid()) {
                check(dut.get_io$$trap$$bits$$cause() == 0x8000000000000009ULL,
                      "unexpected CPU trap instead of S external interrupt");
                sawTrap = true;
            }
            auto commit = [&](bool valid, uint64_t pc) {
                if (!valid) return;
                lastPc = pc;
                check(pc != failPc, "firmware entered failure loop");
                if (pc == waitPc) enteredSupervisor = true;
                if (pc == donePc) done = true;
            };
            commit(dut.get_io$$commit0$$valid(), dut.get_io$$commit0$$bits$$pc());
            commit(dut.get_io$$commit1$$valid(), dut.get_io$$commit1$$bits$$pc());
        };
        while (!enteredSupervisor && cycle < 8000) advance();
        check(enteredSupervisor, "firmware did not enter S mode");
        for (unsigned idle = 0; idle < 64; ++idle) advance();
        for (unsigned bit = 0; bit < 10; ++bit) {
            const bool level = bit == 0 ? false : bit == 9 ? true : (('Z' >> (bit - 1)) & 1) != 0;
            for (unsigned tick = 0; tick < 16; ++tick) advance(level);
        }
        while (!done && cycle < 16000) advance();
        check(sawSupervisorPending && sawTrap && done, "S UART interrupt was not handled");
        std::cout << "GSIM machine AIA S UART: PASS cycles=" << cycle
                  << " pending=" << sawSupervisorPending << " trap=" << sawTrap
                  << " done=0x" << std::hex << lastPc << std::dec << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM machine AIA S UART: FAIL " << error.what() << '\n';
        return 1;
    }
}
