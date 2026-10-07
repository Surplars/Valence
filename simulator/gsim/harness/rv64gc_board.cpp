// Production BoardSocTop, coherent cache, TL/AXI and independent sparse backing.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main

struct GcObservation {
    bool fetchPermission = false;
    bool trace = false;
    unsigned traced = 0;
    unsigned traps = 0;
    unsigned compressedCommits = 0;
    static void sample(SBoardSocGsim &dut, void *context) {
        auto &state = *static_cast<GcObservation *>(context);
        if (dut.get_io$$trap$$valid()) {
            if (state.trace) std::cerr << "TRACE trap cause=" << dut.get_io$$trap$$bits$$cause()
                << " pc=0x" << std::hex << dut.get_io$$trap$$bits$$pc()
                << " tval=0x" << dut.get_io$$trap$$bits$$tval() << std::dec << "\n";
            const unsigned causes[] = {9, 1, 9};
            check(state.fetchPermission ? (state.traps < 3 &&
                      dut.get_io$$trap$$bits$$cause() == causes[state.traps]) :
                      (dut.get_io$$trap$$bits$$cause() == 9 && state.traps == 0),
                  "unexpected precise trap cause/order");
            ++state.traps;
        }
        // Board scalar commit ports expose PCs; consecutive 2-byte retirement
        // advances demonstrate real compressed frontend use, independently of
        // the numeric decoder fixture.
        static uint64_t previousPc = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            bool valid = lane ? dut.get_io$$commit1() : dut.get_io$$commit0();
            uint64_t pc = lane ? dut.get_io$$commit1Pc() : dut.get_io$$commit0Pc();
            if (valid) {
                if (state.trace && state.traced++ < 256 && pc >= 0x80200000ULL)
                    std::cerr << "TRACE commit pc=0x" << std::hex << pc << std::dec << "\n";
                if (previousPc && pc == previousPc + 2) ++state.compressedCommits;
                previousPc = pc;
            }
        }
    }
};

int main(int argc, char **argv) {
    try {
        check(argc >= 2 && argc <= 4,
              "usage: run smoke.bin [--fetch-permission] [--inject-mismatch]");
        bool fetchPermission = false, inject = false, trace = false;
        for (int i = 2; i < argc; ++i) {
            const std::string flag(argv[i]);
            if (flag == "--fetch-permission") fetchPermission = true;
            else if (flag == "--inject-mismatch") inject = true;
            else if (flag == "--trace") trace = true;
            else check(false, "unknown option");
        }
        auto image = readFile(argv[1]);
        check(!image.empty() && image.size() < 16384, "short GC image bounds");
        if (inject) {
            bool changed = false;
            for (size_t offset = 0; offset + 4 <= image.size(); offset += 4) {
                if (wordAt(image, offset) == 0x301022f3) { // csrr t0,misa
                    const uint32_t wrong = 0x00000293; // addi t0,zero,0
                    for (unsigned byte = 0; byte < 4; ++byte) image[offset + byte] = wrong >> (8 * byte);
                    changed = true;
                    break;
                }
            }
            check(changed, "negative-control ISA anchor located");
        }
        Bytes rom;
        word(rom, 0x00200297); // auipc t0,0x200 -> 0x80200000
        word(rom, 0x000280e7); // jalr ra,0(t0)
        word(rom, 0x0000006f);
        Test test(rom);
        for (size_t offset = 0; offset < image.size(); offset += 8) {
            uint64_t value = 0;
            for (unsigned lane = 0; lane < 8 && offset + lane < image.size(); ++lane)
                value |= uint64_t(image[offset + lane]) << (8 * lane);
            test.ddr.memory[uint32_t(offset)] = value;
        }
        test.running = false; // observer explicitly validates the deliberate ECALL
        GcObservation observed;
        observed.fetchPermission = fetchPermission;
        observed.trace = trace;
        test.observer = GcObservation::sample;
        test.observerContext = &observed;
        bool passed = false;
        const uint64_t deadline = test.cycles + 150000;
        while (test.cycles < deadline) {
            test.tick();
            std::string uart(test.received.begin(), test.received.end());
            check(uart.find("FAIL") == std::string::npos, "firmware independent anchor/context failure");
            if (uart.find(fetchPermission ? "FETCH PERMISSION PASS\r\n" : "RV64GC PASS\r\n") !=
                std::string::npos) { passed = true; break; }
        }
        check(passed && observed.traps == (fetchPermission ? 3U : 1U) && observed.compressedCommits > 0,
              "bounded completion / S-mode trap / compressed retirement");
        check(test.ddr.readBursts && test.ddr.stalls, "production DDR bursts/backpressure not exercised");
        std::cout << (fetchPermission ? "FETCH_PERMISSION_BOARD_PASS cycles=" : "RV64GC_BOARD_PASS cycles=")
                  << test.cycles
                  << " context_fprs=32 s_ecall=" << observed.traps
                  << " compressed_advances=" << observed.compressedCommits
                  << " ddr_reads=" << test.ddr.readBursts << "\n";
        std::cout << "Short hardware context-mechanism check; NOT Linux context scheduling or FPGA timing.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "RV64GC board mismatch: " << error.what() << "\n";
        return 1;
    }
}
