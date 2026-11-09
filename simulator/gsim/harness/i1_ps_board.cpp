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
        need(argc >= 3, "usage: board-probe.bin cpu-hz [--inject-frequency]");
        const unsigned cpuHz = std::stoul(argv[2]);
        need(cpuHz == 250000000 || cpuHz == 300000000, "board CPU profile must be 250 or 300 MHz");
        std::ifstream file(argv[1], std::ios::binary);
        need(bool(file), "board payload missing");
        const std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
        constexpr uint64_t base = 0x40000000, mailbox = 0x4fff0000;
        const bool inject = argc > 3;
        for (unsigned order = 0; order < 2; ++order) {
            for (unsigned latency : {1U, 12U}) {
                Model d;
                AxiMemory memory(d, {}, false, false);
                memory.readLatency = latency; memory.writeLatency = latency;
                for (unsigned i = 0; i < image.size(); ++i) memory.bytes[base + i] = image[i];
                const std::array<unsigned, 3> period = latency == 1 ?
                    std::array<unsigned, 3>{cpuHz == 250000000 ? 12U : 10U, 10, 10} : std::array<unsigned, 3>{10, 6, 8};
                d.set_cpuClock(0); d.set_vpuClock(0); d.set_systemClock(0);
                d.set_boardColdReset(1); d.set_io$$start(0); d.set_io$$ddrReady(0);
                memory.inputs(0); d.step();
                bool oldCpu = false, oldVpu = false, oldSystem = false;
                bool gateCpu = true, gateVpu = true, launched = false, done = false, dropped = false;
                uint64_t systemCycles = 0, launchCycle = 0, terminalCycle = 0, retired = 0;
                for (uint64_t tick = 0; tick < 200000 && !done; ++tick) {
                    const bool cold = tick < 160;
                    const bool rawCpu = tick % period[0] >= period[0] / 2;
                    const bool rawVpu = (tick + 1) % period[1] >= period[1] / 2;
                    const bool system = (tick + 2) % period[2] >= period[2] / 2;
                    // Model the physical BUFGCE contract: only update the held enable while low.
                    if (!rawCpu) gateCpu = d.get_io$$cpuClockEnable();
                    if (!rawVpu) gateVpu = d.get_io$$vpuClockEnable();
                    const bool cpu = rawCpu && gateCpu, vpu = rawVpu && gateVpu;
                    const bool ce = cpu && !oldCpu, se = system && !oldSystem;
                    d.set_cpuClock(oldCpu); d.set_vpuClock(oldVpu); d.set_systemClock(oldSystem);
                    d.set_boardColdReset(cold);
                    dropped = launched && systemCycles > launchCycle + 20;
                    d.set_io$$start(tick >= (order ? 800 : 400) && !dropped);
                    d.set_io$$ddrReady(tick >= (order ? 400 : 800) && !dropped);
                    if (se) memory.inputs(systemCycles);
                    d.step();
                    if (!cold) {
                        if (d.get_io$$started() && !launched) {
                            need(tick >= 800, "CPU released before both RPU levels");
                            launched = true; launchCycle = systemCycles;
                        }
                        need(!launched || d.get_io$$started(), "GPIO drop reset an active transaction epoch");
                        if (!launched) {
                            need(!d.get_io$$memory$$ar$$valid() && !d.get_io$$memory$$aw$$valid() &&
                                !d.get_io$$memory$$w$$valid(), "PS HP traffic escaped cold hold");
                        }
                        need(!d.get_io$$protocolError(), "board native protocol error");
                        if (se) {
                            if (d.get_io$$memory$$ar$$valid()) {
                                auto a = d.get_io$$memory$$ar$$bits$$addr();
                                need(a >= base && a < base + 0x10000000, "PS read relocation escaped reserved window");
                            }
                            if (d.get_io$$memory$$aw$$valid()) {
                                auto a = d.get_io$$memory$$aw$$bits$$addr();
                                need(a >= base && a < base + 0x10000000, "PS write relocation escaped reserved window");
                            }
                            memory.outputs(systemCycles);
                        }
                        if (ce && d.get_io$$retire$$valid()) {
                            need(!d.get_io$$retire$$bits$$trap(), "unexpected board boot architectural trap");
                            ++retired;
                        }
                        if (memory.load(mailbox + 56) == 1) {
                            if (!terminalCycle) terminalCycle = systemCycles;
                            done = systemCycles > terminalCycle + 100 && memory.reads.empty() && !memory.sending &&
                                memory.addresses.empty() && memory.writeBeats.empty() && memory.replies.empty();
                        }
                    }
                    d.set_cpuClock(cpu); d.set_vpuClock(vpu); d.set_systemClock(system); d.step();
                    oldCpu = cpu; oldVpu = vpu; oldSystem = system;
                    if (se && !cold) ++systemCycles;
                }
                need(done && dropped && retired > 20, "board boot bounded completion failed");
                need(memory.load(mailbox) == 0xbeef && memory.load(mailbox + 8) == 0x80000000003411adULL,
                    "independent board H/hart profile oracle");
                need(memory.load(mailbox + 16) == 300000000 && memory.load(mailbox + 24) == (cpuHz ^ unsigned(inject)) &&
                    memory.load(mailbox + 32) == 300000000, "independent board CMU frequency oracle");
                need(memory.load(mailbox + 40) == 0x0123456789abcdefULL && memory.load(mailbox + 48) == 0,
                    "independent board physical DDR load/store oracle");
                std::cout << "I1_PS_BOARD_PASS order=" << order << " latency=" << latency
                    << " retired=" << retired << " system_cycles=" << systemCycles << std::endl;
            }
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
