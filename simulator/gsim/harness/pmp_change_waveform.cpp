#include "PmpChangeWaveformGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <type_traits>
static void check(bool v, const char* message) { if (!v) throw std::runtime_error(message); }
int main(int argc, char** argv) {
    try {
        unsigned mutation = argc == 2 ? std::stoul(argv[1]) : 0;
        SPmpChangeWaveformGsim dut;
        static_assert(std::is_trivially_copyable_v<SPmpChangeWaveformGsim>);
        std::memset(&dut, 0, sizeof(dut)); dut.LOG_START = 1; dut.activateAll();
        uint64_t addr = 0, previousAddr = 0;
        unsigned cfg = 0, previousCfg = 0, previousPrivilege = 0;
        uint32_t epoch = 0;
        bool stable = false;
        uint64_t changedCycles = 0, consecutive = 0, separated = 0, resetChecks = 0;
        bool lastChanged = false;
        unsigned cycle = 0;
        auto tick = [&](bool update, unsigned nextCfg, uint64_t nextAddr, bool reset = false) {
            dut.set_reset(reset); dut.set_io$$update(update); dut.set_io$$cfg(nextCfg); dut.set_io$$addr(nextAddr);
            dut.set_io$$test$$physicalReady(cycle % 3 != 0); dut.set_io$$test$$responseReady(true);
            dut.set_io$$test$$aggregateDrained(true); dut.set_io$$test$$mutation(mutation);
            dut.set_io$$test$$poisonInvalid(true);
            dut.step();
            // The step has already applied an asserted reset to Q. Compare the
            // held-reset image, not the host image from before that reset edge.
            if (reset) { cfg = previousCfg = 0; addr = previousAddr = 0;
                previousPrivilege = 0; epoch = 0; stable = false; }
            const bool rawChanged = cfg != previousCfg || addr != previousAddr;
            const bool changed = rawChanged || previousPrivilege != 3;
            if (cycle) {
                check(!dut.get_io$$test$$mismatch(), "PMP waveform differential mismatch");
                check(bool(dut.get_io$$test$$rawChanged()) == rawChanged, "PMP waveform raw phase mismatch");
                check(bool(dut.get_io$$test$$changed()) == changed, "PMP waveform authorization phase mismatch");
                check(dut.get_io$$test$$epoch() == epoch && dut.get_io$$test$$postedEpoch() == epoch,
                    "PMP waveform epoch phase mismatch");
                check(bool(dut.get_io$$test$$stable()) == stable, "PMP waveform stability mismatch");
                changedCycles += rawChanged; consecutive += rawChanged && lastChanged;
                separated += rawChanged && !lastChanged; resetChecks += reset;
            }
            lastChanged = rawChanged;
            if (reset) { dut.resetAll(); cfg = previousCfg = 0; addr = previousAddr = 0; previousPrivilege = 0; epoch = 0; stable = false; }
            else {
                previousCfg = cfg; previousAddr = addr; previousPrivilege = 3;
                if (update) { cfg = nextCfg; addr = nextAddr; }
                epoch += changed; stable = !changed;
            }
            ++cycle;
        };
        tick(false, 0, 0, true); tick(false, 0, 0, true); tick(false, 0, 0);
        // OFF raw change, consecutive changes, an intervening no-op and return to
        // a previous value: the full-image comparator is the independent oracle.
        tick(true, 0, 1); tick(true, 0, 2); tick(true, 0, 3);
        tick(true, 0, 3); tick(true, 0, 2); tick(false, 0, 0); tick(false, 0, 0);
        std::mt19937_64 random(0x504d5045444745);
        for (unsigned n = 0; n < 2048; ++n) {
            const bool reset = n % 97 == 0;
            const bool same = n % 5 == 0;
            tick(n % 7 != 0, same ? cfg : (random() & 0x9f),
                same ? addr : (random() & ((1ULL << 54) - 1)), reset);
        }
        tick(false, 0, 0); tick(false, 0, 0);
        check(consecutive > 500 && separated > 100 && resetChecks > 10, "missing waveform coverage");
        std::cout << "PMP waveform PASS cycles=" << cycle << " changed=" << changedCycles
            << " consecutive=" << consecutive << " separated=" << separated << " resets=" << resetChecks << '\n';
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
