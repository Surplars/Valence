// Short upstream OpenSBI -> S-mode check using the frozen R8 board model.
#include "I1PsBoardGsim.h"
#include <array>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>
using Model = SI1PsBoardGsim;
static void need(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
#include "i1_axi_memory_reference.h"

int main(int argc, char **argv) {
    try {
        need(argc == 2, "usage: run gsim-quiet-probe.bin");
        std::ifstream file(argv[1], std::ios::binary);
        need(bool(file), "OpenSBI image missing");
        const std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
        Model d;
        AxiMemory memory(d, {}, false, false);
        memory.readLatency = 3; memory.writeLatency = 3;
        for (unsigned i = 0; i < image.size(); ++i)
            if (image[i]) memory.bytes[0x40000000ULL + i] = image[i];
        constexpr uint64_t report = 0x4fff0100, pass = 0x534d4f4445504153ULL;
        uint64_t retired = 0, pc = 0, trapPc = 0, cause = 0, tval = 0, terminal = 0;
        d.set_cpuClock(0); d.set_vpuClock(0); d.set_systemClock(0);
        d.set_boardColdReset(1); d.set_io$$start(0); d.set_io$$ddrReady(0);
        memory.inputs(0); d.step();
        for (uint64_t cycle = 0; cycle < 2000000; ++cycle) {
            // Independent 300 MHz domains share the same frequency in this short case.
            // Sample BUFGCE enables while the input clocks are low.
            d.set_cpuClock(0); d.set_vpuClock(0); d.set_systemClock(0); d.step();
            d.set_boardColdReset(cycle < 32);
            d.set_io$$start(cycle >= 64); d.set_io$$ddrReady(cycle >= 96);
            memory.inputs(cycle); d.step();
            const bool cpu = d.get_io$$cpuClockEnable(), vpu = d.get_io$$vpuClockEnable();
            if (cycle >= 32) {
                need(!d.get_io$$protocolError(), "board protocol error");
                memory.outputs(cycle);
                if (cpu && d.get_io$$retire$$valid()) {
                    pc = d.get_io$$retire$$bits$$pc();
                    ++retired;
                    if (d.get_io$$retire$$bits$$trap()) {
                        trapPc = pc; cause = d.get_io$$retire$$bits$$cause();
                        tval = d.get_io$$retire$$bits$$tval();
                    }
                }
                const auto result = memory.load(report + 48);
                if (result == pass && !terminal) terminal = cycle;
                if (result == 0xbad || (terminal && cycle > terminal + 100)) {
                    for (unsigned offset = 0; offset <= 80; offset += 8)
                        std::cout << "report+" << std::hex << offset << "=0x" << memory.load(report + offset) << ' ';
                    std::cout << std::dec << std::endl;
                    need(result == pass, "S-mode probe reported failure");
                    need(memory.load(report) == 0xbeef && memory.load(report + 8) == 0x8fe00000,
                         "S-mode hart/FDT ABI mismatch");
                    need(memory.load(report + 16) == 0x03000000 && memory.load(report + 24) == 1,
                         "SBI v3 BASE/TIME response mismatch");
                    need(memory.load(report + 32) == 12 && memory.load(report + 40) == 1 &&
                         memory.load(report + 56) == 0x8000000000080210ULL,
                         "S-mode atomic/timer/Sv39 oracle mismatch");
                    std::cout << "PASS_I1_PS_OPENSBI_S_MODE_SBI_TIMER_SV39 cycles=" << cycle
                              << " retired=" << retired << std::endl;
                    return 0;
                }
                if (cycle % 100000 == 0 || cycle == 1999999)
                    std::cout << "progress cycles=" << cycle << " retired=" << retired << std::hex
                              << " pc=0x" << pc << " trap_pc=0x" << trapPc << " cause=0x" << cause
                              << " tval=0x" << tval << " result=0x" << result << std::dec << std::endl;
            }
            d.set_cpuClock(cpu); d.set_vpuClock(vpu); d.set_systemClock(1); d.step();
        }
        throw std::runtime_error("bounded OpenSBI/S-mode completion timeout");
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
