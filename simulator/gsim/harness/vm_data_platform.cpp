#include "VmDataPlatformGsim.h"
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static void drive(SVmDataPlatformGsim &dut) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$ramWrite(0);
    dut.set_io$$ramIndex(0);
    dut.set_io$$ramData(0);
    dut.set_io$$inspectRegister(0);
}
static void programRam(SVmDataPlatformGsim &dut, unsigned index, uint64_t value) {
    drive(dut);
    dut.set_io$$hold(1);
    dut.set_io$$ramWrite(1);
    dut.set_io$$ramIndex(index);
    dut.set_io$$ramData(value);
    dut.step();
}
int main(int argc, char **argv) {
    try {
        check(argc == 2 || (argc == 3 && std::string(argv[2]) == "--coherent"),
              "expected firmware binary path and optional --coherent");
        const bool coherent = argc == 3;
        std::ifstream firmware(argv[1], std::ios::binary);
        check(firmware.good(), "cannot open firmware binary");
        std::vector<unsigned char> code((std::istreambuf_iterator<char>(firmware)), {});
        check(!code.empty() && code.size() % 4 == 0 && code.size() <= 8192, "invalid firmware image");
        SVmDataPlatformGsim dut;
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
        const uint64_t va = 0x40002000ULL;
        programRam(dut, 1, (0x80011ULL << 10) | 1ULL);
        programRam(dut, 512, (0x80012ULL << 10) | 1ULL);
        programRam(dut, 1024 + ((va >> 12) & 511), 0);
        programRam(dut, 1024 + ((0x40004000ULL >> 12) & 511),
                   (1ULL << 61) | (0x80014ULL << 10) | 0xc7ULL);
        programRam(dut, 4 * 512, 0x1122334455667788ULL);
        drive(dut); dut.set_io$$hold(1); dut.step();
        unsigned commits = 0, traps = 0, walks = 0, pteReads = 0, physicalRequests = 0;
        unsigned probeAckData = 0, releaseData = 0;
        unsigned measuredCycles = 0, measuredRetired = 0;
        uint64_t cause = 0, tval = 0;
        for (unsigned cycle = 0; cycle < 3000; ++cycle) {
            drive(dut);
            dut.step();
            if (!traps) {
                ++measuredCycles;
                measuredRetired += dut.get_io$$commitCount();
            }
            commits += dut.get_io$$committed();
            walks += dut.get_io$$dWalk();
            pteReads += dut.get_io$$dPteRead();
            physicalRequests += dut.get_io$$cpuPhysicalRequest();
            probeAckData += dut.get_io$$probeAckData();
            releaseData += dut.get_io$$releaseData();
            if (dut.get_io$$trap()) {
                ++traps;
                cause = dut.get_io$$trapCause();
                tval = dut.get_io$$trapTval();
            }
        }
        auto reg = [&](unsigned number) {
            drive(dut);
            dut.set_io$$inspectRegister(number);
            dut.step();
            return uint64_t(dut.get_io$$committedValue());
        };
        check(commits >= 20, "firmware did not retire");
        check(traps == 1 && cause == 13 && tval == 0x40003000ULL,
              "virtual load page fault was not precise");
        check(reg(10) == 0x1122334455667788ULL, "virtual load returned wrong physical RAM data");
        check(reg(14) == 0x1122334455667788ULL, "virtual store/load did not round-trip through physical RAM");
        check(reg(15) == 0x1122334455667788ULL, "PBMT non-cacheable alias missed the dirty physical line");
        check(reg(16) == 0x1122334455667788ULL, "virtual AMO missed the dirty physical line");
        check(reg(31) == 0x1122334455667808ULL, "virtual hot load/store loop returned the wrong value");
        check(reg(11) == 13 && reg(12) == 0x40003000ULL, "trap CSRs disagree with the trap event");
        check(walks == 5 && pteReads == 7, "DTLB miss or non-leaf PTE cache behavior changed");
        check(physicalRequests == 263, "faulting virtual load issued a physical data request");
        if (coherent) check(probeAckData >= 8 && releaseData >= 16,
                            "dirty PTE probe or PBMT alias writeback was not exercised");
        std::cout << "GSIM CPU virtual data: PASS commits=" << commits << " walks=" << walks
                  << " pteRamReads=" << pteReads << " physicalDataRequests=" << physicalRequests
                  << " probeAckData=" << probeAckData << " releaseData=" << releaseData
                  << " firstTrapCycles=" << measuredCycles << " firstTrapRetired=" << measuredRetired
                  << " firstTrapIpc=" << std::setprecision(6) << double(measuredRetired) / measuredCycles << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM CPU virtual data: FAIL " << e.what() << '\n';
        return 1;
    }
}
