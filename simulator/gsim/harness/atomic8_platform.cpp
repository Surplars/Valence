#include "Atomic8PlatformGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

static void check(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}
static void drive(SAtomic8PlatformGsim &dut) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$inspectRegister(0);
}
int main(int argc, char **argv) {
    try {
        check(argc == 3, "expected ROM image and fault PC");
        std::ifstream firmware(argv[1], std::ios::binary);
        check(firmware.good(), "cannot open atomic ROM image");
        std::vector<uint8_t> code((std::istreambuf_iterator<char>(firmware)), {});
        check(!code.empty() && code.size() % 4 == 0 && code.size() <= 1024, "invalid atomic ROM size");
        const auto faultPc = std::stoull(argv[2], nullptr, 0);
        SAtomic8PlatformGsim dut;
        drive(dut);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        for (unsigned i = 0; i < code.size() / 4; ++i) {
            const uint32_t word = uint32_t(code[4 * i]) | (uint32_t(code[4 * i + 1]) << 8) |
                (uint32_t(code[4 * i + 2]) << 16) | (uint32_t(code[4 * i + 3]) << 24);
            drive(dut);
            dut.set_io$$hold(1);
            dut.set_io$$romWrite(1);
            dut.set_io$$romIndex(i);
            dut.set_io$$romData(word);
            dut.step();
        }
        drive(dut); dut.set_io$$hold(1); dut.step();
        unsigned requests = 0, commits = 0;
        for (unsigned cycle = 1; cycle <= 5000; ++cycle) {
            drive(dut);
            dut.step();
            requests += dut.get_io$$cpuMemoryFire();
            commits += dut.get_io$$commit0() + dut.get_io$$commit1();
            if (!dut.get_io$$trap()) continue;
            check(dut.get_io$$trapCause() == 7, "out-of-range AMO must raise store access fault");
            check(dut.get_io$$trapPc() == faultPc, "faulting AMO PC mismatch");
            check(dut.get_io$$trapTval() == UINT64_C(0x80012000), "faulting AMO address mismatch");
            auto reg = [&](unsigned index) {
                drive(dut); dut.set_io$$inspectRegister(index); dut.step();
                return uint64_t(dut.get_io$$committedValue());
            };
            check(reg(6) == 41 && reg(7) == 82 && reg(28) == 0 && reg(29) == 41 &&
                  reg(30) == 41 && reg(31) == 82 && reg(10) == 0,
                  "upper-RAM AMO/LR/SC/W result mismatch");
            check(requests == 8, "invalid AMO issued a memory request or an expected operation was lost");
            std::cout << "GSIM atomic 8KiB platform: PASS cycles=" << cycle << " commits=" << commits
                      << " cpuRequests=" << requests << " faultPc=0x" << std::hex << faultPc << std::dec << '\n';
            return 0;
        }
        throw std::runtime_error("upper-RAM atomic program timed out");
    } catch (const std::exception &error) {
        std::cerr << "GSIM atomic 8KiB platform: FAIL " << error.what() << '\n';
        return 1;
    }
}
