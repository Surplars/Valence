#include "VmInstructionPlatformGsim.h"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}
static void drive(SVmInstructionPlatformGsim &dut) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$ramWrite(0);
    dut.set_io$$ramIndex(0);
    dut.set_io$$ramData(0);
    dut.set_io$$inspectRegister(0);
}
static void programRam(SVmInstructionPlatformGsim &dut, unsigned index, uint64_t value) {
    drive(dut);
    dut.set_io$$hold(1);
    dut.set_io$$ramWrite(1);
    dut.set_io$$ramIndex(index);
    dut.set_io$$ramData(value);
    dut.step();
}
static void runCase(const char *path, bool crossPage) {
        std::ifstream firmware(path, std::ios::binary);
        check(firmware.good(), "cannot open firmware binary");
        std::vector<unsigned char> code((std::istreambuf_iterator<char>(firmware)), {});
        check(!code.empty() && code.size() % 4 == 0 && code.size() <= 8192, "invalid firmware image");
        SVmInstructionPlatformGsim dut;
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
        const uint64_t va = 0x40000000ULL;
        const uint64_t dataVa = 0x40002000ULL;
        programRam(dut, 1, (0x80011ULL << 10) | 1ULL);
        programRam(dut, 512, (0x80012ULL << 10) | 1ULL);
        programRam(dut, 1024 + ((va >> 12) & 511), (0x80000ULL << 10) | 0x4bULL);
        programRam(dut, 1024 + ((dataVa >> 12) & 511), (0x80014ULL << 10) | 0xc7ULL);
        programRam(dut, 4 * 512, 42);
        drive(dut); dut.set_io$$hold(1); dut.step();
        unsigned traps = 0, walks = 0, pteReads = 0, hits = 0, dataWalks = 0;
        uint64_t cause = 0, tval = 0;
        for (unsigned cycle = 0; cycle < 900; ++cycle) {
            drive(dut);
            dut.step();
            walks += dut.get_io$$iWalk();
            pteReads += dut.get_io$$iPteRead();
            hits += dut.get_io$$iTlbHit();
            dataWalks += dut.get_io$$dWalk();
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
        check(traps == 1 && cause == 12 && tval == 0x40001000ULL,
              "virtual instruction page fault was not precise");
        check(reg(10) == (crossPage ? 42 : 43), "supervisor instruction at the page boundary did not execute");
        check(reg(11) == 12 && reg(12) == 0x40001000ULL, "trap CSRs disagree with the trap event");
        const uint64_t epc = reg(13);
        if (epc != (crossPage ? 0x40000ffeULL : 0x40001000ULL)) {
            std::cerr << "crossPage=" << crossPage << " mepc=0x" << std::hex << epc
                      << " mtval=0x" << tval << std::dec << '\n';
            throw std::runtime_error("faulting instruction mepc disagrees with the instruction start");
        }
        check(walks >= 2 && pteReads >= 4 && hits > 0, "I-TLB or PTE walk was not exercised");
        check(dataWalks > 0, "S-mode data translation was not exercised");
        std::cout << "GSIM CPU virtual fetch" << (crossPage ? " cross-page" : " baseline")
                  << ": PASS walks=" << walks << " pteRamReads=" << pteReads
                  << " tlbHits=" << hits << " dataWalks=" << dataWalks << '\n';
}
int main(int argc, char **argv) {
    try {
        check(argc == 3, "expected baseline and cross-page firmware binaries");
        runCase(argv[1], false);
        runCase(argv[2], true);
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM CPU virtual fetch: FAIL " << e.what() << '\n';
        return 1;
    }
}
