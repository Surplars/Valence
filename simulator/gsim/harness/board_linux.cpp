// Boot the EXACT UART-downloadable combined image on the compact DDR board CPU.
// Preload skips serial transfer only. Independent AXI latency/backpressure remains.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main

struct LinuxObservation {
    uint64_t commits = 0, userCommits = 0, traps = 0, lastPc = 0;
    uint64_t trapPc = 0, cause = 0, tval = 0;
    static void observe(SBoardSocGsim &dut, void *context) {
        auto &s = *static_cast<LinuxObservation *>(context);
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = lane ? dut.get_io$$commit1() : dut.get_io$$commit0();
            const uint64_t pc = lane ? dut.get_io$$commit1Pc() : dut.get_io$$commit0Pc();
            if (valid) {
                ++s.commits;
                s.lastPc = pc;
                if (pc < 0x80000000) ++s.userCommits;
            }
        }
        if (!dut.get_io$$trap$$valid()) return;
        ++s.traps;
        s.trapPc = dut.get_io$$trap$$bits$$pc();
        s.cause = dut.get_io$$trap$$bits$$cause();
        s.tval = dut.get_io$$trap$$bits$$tval();
        // OpenSBI probes absent CSRs/PMPs. Linux legitimately uses ECALL,
        // software-managed A/D page faults, software misalignment emulation,
        // the kernel's explicit unaligned-access probe, and timer interrupts.
        const uint64_t code = s.cause & ~(uint64_t(1) << 63);
        const bool interrupt = s.cause >> 63;
        const bool probe = code == 2 && s.trapPc >= 0x80200000 && s.trapPc < 0x80300000;
        const bool semihostProbe = code == 3 && s.trapPc == SEMHOST_PROBE_PC;
        if (!(interrupt ? (code == 5 || code == 7 || code == 9) :
              (probe || semihostProbe || code == 4 || code == 6 ||
               code == 8 || code == 9 || code == 12 || code == 13 || code == 15))) {
            std::cerr << "unexpected trap pc=0x" << std::hex << s.trapPc << " cause=" << s.cause
                      << " tval=0x" << s.tval << std::dec << '\n';
            throw std::runtime_error("unexpected Linux/OpenSBI architectural trap");
        }
    }
};

int main(int argc, char **argv) {
    try {
        check(argc == 2 || argc == 3, "usage: run opensbi_linux_ddr50.bin [max-cycles]");
        const auto image = readFile(argv[1]);
        check(image.size() > 0x200040 && image.size() < imageLimit, "combined image bounds");
        check(std::string(image.begin() + 0x200030, image.begin() + 0x200035) == "RISCV",
              "embedded Linux Image magic");
        const uint64_t maxCycles = argc == 3 ? std::stoull(argv[2]) : 500000000;
        Bytes rom;
        word(rom, 0x00200297); // auipc t0,0x200 -> OpenSBI 0x80200000
        word(rom, 0x10000337); // lui t1,0x10000 -> UART
        word(rom, 0x00700393); // addi t2,zero,7
        word(rom, 0x00730123); // sb t2,2(t1) -> FCR=7
        word(rom, 0x00000513); // a0=hart0
        word(rom, 0x00000593); // a1=0, exactly like ROM monitor (embedded FDT required)
        word(rom, 0x00028067); // jalr zero,0(t0)
        Test test(rom);
        // This fixture executes an OS; replace the bootloader's no-traps policy
        // with the explicit cause/PC policy above, not blanket trap suppression.
        test.running = false;
        LinuxObservation observed;
        test.observer = LinuxObservation::observe;
        test.observerContext = &observed;
        for (size_t offset = 0; offset < image.size(); offset += 8) {
            uint64_t value = 0;
            for (unsigned lane = 0; lane < 8 && offset + lane < image.size(); ++lane)
                value |= uint64_t(image[offset + lane]) << (8 * lane);
            if (value) test.ddr.memory[uint32_t(offset)] = value;
        }
        size_t printed = 0;
        std::string console;
        bool sentHelp = false;
        for (; test.cycles < maxCycles;) {
            test.tick();
            if (test.received.size() != printed) {
                const char c = char(test.received[printed++]);
                console += c;
                std::cout << c << std::flush;
                check(console.find("Kernel panic") == std::string::npos &&
                      console.find("Oops:") == std::string::npos &&
                      console.find("sbi_trap_error") == std::string::npos, "kernel/firmware reported failure");
            }
            if (!sentHelp && console.find("valence# ") != std::string::npos) {
                const std::string command = ROOTFS_BUSYBOX ?
                    "uname -m; printf 'VALENCE_%s_OK\\n' SHELL; fastfetch --version; "
                    "printf 'VALENCE_%s_OK\\n' FASTFETCH\r" : "help\r";
                for (uint8_t c : command) {
                    test.send(c);
                    // hvc0 is polled, not a qualified UART IRQ driver. Model
                    // interactive typing; do not overflow its 16-byte FIFO.
                    test.idle(100000); // 2 ms at 50 MHz
                }
                sentHelp = true;
            }
            const bool commandDone = ROOTFS_BUSYBOX ?
                console.find("VALENCE_SHELL_OK") != std::string::npos &&
                    console.find("VALENCE_FASTFETCH_OK") != std::string::npos :
                console.find("exit: park init (reset board to restart)") != std::string::npos;
            if (sentHelp && commandDone &&
                console.ends_with("valence# ")) break;
            if (test.cycles % 10000000 == 0) {
                std::cerr << "\nprogress cycles=" << test.cycles << " commits=" << observed.commits
                          << " lastPc=0x" << std::hex << observed.lastPc << std::dec
                          << " uartBytes=" << printed << '\n';
            }
        }
        check(console.find("OpenSBI v1.9") != std::string::npos, "missing pinned OpenSBI banner");
        check(console.find("S-mode") != std::string::npos, "no S-mode handoff");
        check(console.find("Linux version") != std::string::npos, "no Linux entry");
        check(console.find("VALENCE_LINUX_INIT_OK") != std::string::npos && observed.userCommits,
              "no real Linux user-mode init execution");
        check(sentHelp && console.ends_with("valence# "), "UART help input/output not completed");
        if (ROOTFS_BUSYBOX) {
            check(console.find("VALENCE_SHELL_OK") != std::string::npos &&
                  console.find("VALENCE_FASTFETCH_OK") != std::string::npos &&
                  console.find("riscv64") != std::string::npos &&
                  console.find("fastfetch 2.69.0") != std::string::npos,
                  "BusyBox shell/real fastfetch not executed");
        }
        check(test.ddr.readBursts && test.ddr.writeBursts && test.ddr.stalls, "DDR path not exercised");
        std::cout << "\nGSIM DDR50 Linux: PASS cycles=" << test.cycles << " commits=" << observed.commits
                  << " userCommits=" << observed.userCommits << " traps=" << observed.traps
                  << " readBursts=" << test.ddr.readBursts << " writeBursts=" << test.ddr.writeBursts << '\n';
        std::cout << "Exact combined image; serial preload shortcut. Not MIG/CDC/physical-board qualification.\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM DDR50 Linux: FAIL " << error.what() << '\n';
        return 1;
    }
}
