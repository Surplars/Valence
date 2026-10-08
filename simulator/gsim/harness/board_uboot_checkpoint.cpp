// Exact combined OpenSBI/U-Boot bytes; independent serial-pin and AXI fixture.
// Identity classification is enforced and recorded by run_uboot_gsim.py.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include <array>
#include <chrono>
#include <csignal>
#include <unistd.h>
#include <regex>

// Read-only crash diagnostics: preserve the DUT assertion and normal SIGABRT.
// The handler uses a fixed buffer and write(2), not iostream/heap allocation.
static SBoardSocGsim *abortDut = nullptr;
static volatile uint64_t abortCycle = 0, abortLastPc = 0;
static void onAbort(int signum) {
    char buffer[512]; unsigned used = 0;
    auto text = [&](const char *s) { while (*s && used < sizeof(buffer)) buffer[used++] = *s++; };
    auto number = [&](uint64_t n) {
        char digits[16]; unsigned count = 0;
        do { digits[count++] = "0123456789abcdef"[n & 15]; n >>= 4; } while (n && count < 16);
        while (count && used < sizeof(buffer)) buffer[used++] = digits[--count];
    };
    text("\nUBOOT_ABORT_SNAPSHOT cycle_hex=0x"); number(abortCycle);
    text(" last_retired_pc=0x"); number(abortLastPc);
    if (abortDut) {
        const auto index = unsigned(abortDut->board$platform$privateCache$evictIndex);
        const auto slot = unsigned(abortDut->board$platform$privateCache$evictMshr);
        text(" evict_index=0x"); number(index);
        text(" evict_mshr=0x"); number(slot);
        text(" start_eviction=0x"); number(abortDut->board$platform$privateCache$startEviction);
        text(" evict_from_miss=0x"); number(abortDut->board$platform$privateCache$evictFromMiss);
        text(" direct_eviction=0x"); number(abortDut->board$platform$privateCache$evictFromMiss &&
                 !abortDut->board$platform$privateCache$queuedMissEviction);
        text(" cpu_fire=0x"); number(abortDut->board$platform$privateCache$cpuFire);
        text(" needs_miss_slot=0x"); number(abortDut->board$platform$privateCache$needsMissSlot);
        if (index < 512) { text(" victim_dirty=0x"); number(abortDut->board$platform$privateCache$dirty[index]); }
        if (slot < 2) {
            text(" prefetch_owner=0x"); number(abortDut->board$platform$privateCache$prefetchOwner[slot]);
            text(" owner_phase=0x"); number(abortDut->board$platform$privateCache$phase[slot]);
        }
    }
    text("\n");
    const auto ignored = ::write(STDERR_FILENO, buffer, used); (void)ignored;
    std::signal(signum, SIG_DFL);
}

static constexpr uint64_t protectedBase = 0xfff78000ULL;
static constexpr uint64_t protectedEnd = 0xffffc000ULL;
static constexpr uint64_t ubootBase = 0x80400000ULL;
static constexpr uint32_t protectedOffset = protectedBase - ramBase;
static constexpr uint32_t protectedEndOffset = protectedEnd - ramBase;
static uint64_t sentinel(uint32_t offset) {
    return 0x76a1e0ce5a17beefULL ^ (uint64_t(offset) * 0x9e3779b97f4a7c15ULL);
}

struct Observation {
    uint64_t commits = 0, ubootCommits = 0, relocatedCommits = 0;
    uint64_t traps = 0, supervisorEcalls = 0, lastPc = 0;
    uint64_t maxCycles = 8000000, semihostProbe = 0;
    unsigned maxSeconds = 300;
    Test *test = nullptr;
    std::chrono::steady_clock::time_point began = std::chrono::steady_clock::now();
    static void observe(SBoardSocGsim &dut, void *context) {
        auto &s = *static_cast<Observation *>(context);
        check(s.test->cycles < s.maxCycles, "bounded U-Boot cycle budget exhausted");
        if ((s.test->cycles & 4095) == 0) {
            const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::steady_clock::now() - s.began).count();
            check(elapsed < s.maxSeconds, "bounded U-Boot wall-clock budget exhausted");
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = lane ? dut.get_io$$commit1() : dut.get_io$$commit0();
            const uint64_t pc = lane ? dut.get_io$$commit1Pc() : dut.get_io$$commit0Pc();
            if (!valid) continue;
            ++s.commits; s.lastPc = pc;
            if (pc >= ubootBase && pc < protectedBase) ++s.ubootCommits;
            if (pc >= 0xf0000000ULL && pc < protectedBase) ++s.relocatedCommits;
        }
        // Observe accepted host-memory writes before the DDR model samples them.
        // A dirty cache line never evicted is outside this sentinel's coverage.
        if (dut.get_io$$ddrAxi$$aw$$valid() && s.test->ddr.awReady) {
            const uint64_t start = dut.get_io$$ddrAxi$$aw$$bits$$addr();
            const uint64_t end = start + ((uint64_t(dut.get_io$$ddrAxi$$aw$$bits$$len()) + 1)
                                              << dut.get_io$$ddrAxi$$aw$$bits$$size());
            check(end <= protectedOffset || start >= protectedEndOffset,
                  "AXI write overlaps monitor/diagnostic reservation");
        }
        abortCycle = s.test->cycles + 1;
        abortLastPc = s.lastPc;
        if (!dut.get_io$$trap$$valid()) return;
        ++s.traps;
        const uint64_t pc = dut.get_io$$trap$$bits$$pc();
        const uint64_t cause = dut.get_io$$trap$$bits$$cause();
        const uint64_t code = cause & ~(1ULL << 63);
        const bool irq = cause >> 63;
        const bool firmware = pc >= ramBase && pc < 0x80300000ULL;
        const bool uboot = pc >= ubootBase && pc < protectedBase;
        const bool csrProbe = !irq && code == 2 && firmware;
        const bool semihost = !irq && code == 3 && pc == s.semihostProbe && s.semihostProbe;
        const bool sbiCall = !irq && code == 9 && uboot;
        if (sbiCall) ++s.supervisorEcalls;
        const bool timerIrq = irq && (code == 5 || code == 7 || code == 9);
        if (!(csrProbe || semihost || sbiCall || timerIrq)) {
            std::cerr << "\ntrap pc=0x" << std::hex << pc << " cause=0x" << cause
                      << " tval=0x" << dut.get_io$$trap$$bits$$tval() << std::dec << '\n';
            throw std::runtime_error("unexpected U-Boot/OpenSBI architectural trap");
        }
    }
};

static std::string normalized(std::string text) {
    text.erase(std::remove(text.begin(), text.end(), '\r'), text.end());
    return text;
}
static uint64_t bdNumber(const std::string &text, const std::string &field) {
    const std::regex pattern(field + R"(\s*=\s*(?:0x)?([0-9a-fA-F]+))");
    std::smatch found;
    check(std::regex_search(text, found, pattern), "bdinfo missing " + field);
    return std::stoull(found[1], nullptr, 16);
}
static void verifyCommand(size_t index, const std::string &raw) {
    const std::string output = normalized(raw);
    check(output.find("Unknown command") == std::string::npos, "unknown U-Boot command");
    if (index == 0) {
        check(output.find("DRAM bank") != std::string::npos, "bdinfo DRAM output missing");
        check(bdNumber(output, "-> start") == ramBase, "bdinfo DRAM base mismatch");
        const uint64_t usable = bdNumber(output, "-> size");
        check(usable == 0x80000000ULL, "bdinfo physical DDR size mismatch");
        const uint64_t reloc = bdNumber(output, "relocaddr");
        check(reloc >= ubootBase && reloc < protectedBase, "U-Boot relocation overlaps monitor");
    } else if (index == 1) {
        check(output.find("\nUBOOT_TIMER_OK\n") != std::string::npos,
              "time echo did not execute independently of command echo");
        check(output.find("\ntime:") != std::string::npos &&
              output.find(" seconds") != std::string::npos, "timer report missing");
    } else if (index == 2) {
        check(output.find("print Board Info structure") != std::string::npos,
              "help bdinfo did not execute");
    } else {
        check(output.find("\nVALENCE_UBOOT_OK\n") != std::string::npos,
              "completion marker only echoed, not executed");
    }
}

int main(int argc, char **argv) {
    std::unique_ptr<Test> test;
    Observation observed;
    std::string console;
    size_t printed = 0, completed = 0;
    try {
        check(argc >= 2 && argc <= 6,
              "usage: run fw_payload.bin [cycles=8000000] [seconds=300] [semihost-pc=0] [prompt]");
        const auto image = readFile(argv[1]);
        check(image.size() > 0x200000 && uint64_t(ramBase) + image.size() <= protectedBase,
              "combined OpenSBI/U-Boot image bounds");
        if (argc > 2) observed.maxCycles = std::stoull(argv[2]);
        if (argc > 3) observed.maxSeconds = std::stoul(argv[3]);
        if (argc > 4) observed.semihostProbe = std::stoull(argv[4], nullptr, 0);
        check(observed.maxCycles > 0 && observed.maxSeconds > 0, "nonpositive bounded budget");
        const std::string prompt = argc > 5 ? argv[5] : "valence-uboot> ";
        Bytes rom;
        word(rom, 0x00200297); // auipc t0,0x200 -> 0x80200000 from ROM 0x80000000
        word(rom, 0x10000337); // UART base
        word(rom, 0x00700393);
        word(rom, 0x00730123); // FCR=7, clear FIFOs as ROM handoff
        word(rom, 0x00000513); // a0=0
        word(rom, 0x00000593); // a1=0: require payload's embedded DTB
        word(rom, 0x00028067); // jump to OpenSBI
        test = std::make_unique<Test>(rom);
        test->running = false;
        abortDut = test->dut.get(); abortCycle = test->cycles;
        std::signal(SIGABRT, onAbort);
        observed.test = test.get();
        test->observer = Observation::observe;
        test->observerContext = &observed;
        for (size_t off = 0; off < image.size(); off += 8) {
            uint64_t value = 0;
            for (unsigned lane = 0; lane < 8 && off + lane < image.size(); ++lane)
                value |= uint64_t(image[off + lane]) << (lane * 8);
            if (value) test->ddr.memory[uint32_t(off)] = value;
        }
        for (uint32_t off = protectedOffset; off < protectedEndOffset; off += 8)
            test->ddr.memory[off] = sentinel(off);
        const std::array<std::string, 4> commands = {
            "bdinfo\r", "time echo UBOOT_TIMER_OK\r", "help bdinfo\r", "echo VALENCE_UBOOT_OK\r"};
        bool booted = false, pending = false;
        size_t responseStart = 0;
        while (completed < commands.size()) {
            test->tick();
            if (test->cycles % 250000 == 0)
                std::cerr << "\nUBOOT_PROGRESS cycles=" << test->cycles << " last_pc=0x"
                          << std::hex << observed.lastPc << std::dec << " uart_bytes=" << printed << "\n";
            if (printed == test->received.size()) continue;
            while (printed < test->received.size()) {
                const char c = char(test->received[printed++]);
                console += c;
                std::cout << c << std::flush;
            }
            check(console.find("sbi_trap_error") == std::string::npos &&
                  console.find("### ERROR") == std::string::npos &&
                  console.find("** Cannot") == std::string::npos,
                  "firmware reported failure");
            if (!console.ends_with(prompt)) continue;
            if (!booted) {
                check(console.find("OpenSBI") != std::string::npos, "missing OpenSBI banner");
                check(console.find("S-mode") != std::string::npos, "missing S-mode handoff banner");
                check(console.find("U-Boot ") != std::string::npos && observed.ubootCommits,
                      "missing actual U-Boot execution");
                booted = true;
            } else if (pending && console.size() > responseStart + prompt.size()) {
                verifyCommand(completed, console.substr(responseStart));
                ++completed;
                pending = false;
            }
            if (pending || completed == commands.size()) continue;
            responseStart = console.size();
            pending = true;
            for (const uint8_t c : commands[completed]) {
                test->send(c);
                test->idle(5000); // paced pin-level serial; do not overflow RX FIFO
            }
        }
        test->idle(20000); // bounded time for already-issued DDR traffic
        for (uint32_t off = protectedOffset; off < protectedEndOffset; off += 8)
            check(test->ddr.memory.at(off) == sentinel(off), "monitor/diagnostic sentinel changed");
        check(observed.relocatedCommits, "no high-address relocated U-Boot retirement");
        check(test->ddr.readBursts && test->ddr.writeBursts && test->ddr.stalls,
              "DDR burst/backpressure path not exercised");
        std::cout << "\nUBOOT_GSIM_PASS cycles=" << test->cycles << " commits=" << observed.commits
                  << " uboot_commits=" << observed.ubootCommits
                  << " relocated_commits=" << observed.relocatedCommits
                  << " supervisor_ecalls=" << observed.supervisorEcalls
                  << " traps=" << observed.traps << " commands=" << completed
                  << " sentinel_bytes=" << (protectedEnd - protectedBase) << '\n';
        std::cout << "Preloaded exact payload; UART pins and independent AXI memory. "
                     "Not UART/TFTP transfer, physical board, MIG, CDC or exact-bit qualification.\n";
        return 0;
    } catch (const std::exception &error) {
        // Print any characters received inside paced input before the failure.
        if (test) while (printed < test->received.size())
            std::cout << char(test->received[printed++]);
        std::cerr << "\nUBOOT_GSIM_FAIL reason=" << error.what()
                  << " cycles=" << (test ? test->cycles : 0)
                  << " commits=" << observed.commits << " last_pc=0x" << std::hex
                  << observed.lastPc << std::dec << " uart_bytes=" << printed
                  << " completed_commands=" << completed << '\n';
        return 1;
    }
}
