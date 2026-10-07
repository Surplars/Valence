// Independent AXI model; direct-load the exact downloadable binary, small smoke only.
#define main board_boot_regression_main
#include "board_boot.cpp"
#undef main
#include "data_cache_observer.h"

// Same-BIN cycle comparisons may deliberately retain the firmware's original
// reporting timebase while changing the model's UART/CPU configuration. Keep
// the independent arithmetic oracle tied to that compile-time firmware value,
// not to a value parsed from DUT output. Defaults preserve all existing tests.
#ifndef APP_TIMEBASE_HZ
#define APP_TIMEBASE_HZ BOARD_CPU_HZ
#endif

struct CacheCounters {
    uint64_t misses = 0, replacements = 0, dirtyEvictions = 0, missBlocked = 0;
    uint64_t storeBlocked = 0, unknownStoreBlocked = 0;
    static void sample(SBoardSocGsim &dut, void *context) {
        auto &c = *static_cast<CacheCounters *>(context);
        c.misses += dut.get_io$$cacheProfile$$readMiss() || dut.get_io$$cacheProfile$$writeMiss();
        c.replacements += dut.get_io$$cacheProfile$$replacementMiss();
        c.dirtyEvictions += dut.get_io$$cacheProfile$$dirtyEviction();
        c.missBlocked += dut.get_io$$cacheProfile$$missBlocked();
        c.storeBlocked += dut.get_io$$headProfile$$candidateLoadBlockedByStore();
        c.unknownStoreBlocked += dut.get_io$$headProfile$$candidateLoadBlockedByUnknownStore();
    }
    void report(const char *stage, const CacheCounters &before) const {
        std::cout << "PROFILE " << stage << " (includes preparation/verification/UART)"
                  << " misses=" << misses - before.misses
                  << " replacements=" << replacements - before.replacements
                  << " dirtyEvictions=" << dirtyEvictions - before.dirtyEvictions
                  << " missBlocked=" << missBlocked - before.missBlocked
                  << " storeBlocked=" << storeBlocked - before.storeBlocked
                  << " unknownStoreBlocked=" << unknownStoreBlocked - before.unknownStoreBlocked
                  << "\n" << std::flush;
    }
};

static std::string awaitLine(Test &test, const std::string &marker) {
    const size_t begin = test.expect(marker);
    test.expect("\r\n");
    return std::string(test.received.begin() + begin, test.received.begin() + test.consumed);
}
static uint64_t field(const std::string &line, const std::string &name) {
    const size_t begin = line.find(name + "=");
    check(begin != std::string::npos, "missing field " + name);
    return std::stoull(line.substr(begin + name.size() + 1));
}
static uint64_t milliField(const std::string &line, const std::string &name) {
    const size_t begin = line.find(name + "=");
    check(begin != std::string::npos, "missing fixed-point field " + name);
    const std::string value = line.substr(begin + name.size() + 1);
    const size_t dot = value.find('.');
    check(dot != std::string::npos && value.size() >= dot + 4, "fixed-point format");
    return std::stoull(value.substr(0, dot)) * 1000 + std::stoull(value.substr(dot + 1, 3));
}
static void rateCheck(const std::string &line, bool copy) {
    check(line.find(" PASS\r\n") != std::string::npos, "benchmark result failed");
    check(field(line, "bytes") == 4096, "wrong byte accounting");
    const uint64_t elapsed = field(line, "ticks");
    check(elapsed > 0, "zero elapsed counter");
    const uint64_t expected = 4096ULL * APP_TIMEBASE_HZ * 1000 / (elapsed * 1048576);
    check(milliField(line, "MiB/s") == expected, "MiB/s conversion");
    check(milliField(line, "ms") == elapsed * 1000000 / APP_TIMEBASE_HZ, "ms conversion");
    if (copy)
        check(milliField(line, "logical_R+W_MiB/s") ==
              8192ULL * APP_TIMEBASE_HZ * 1000 / (elapsed * 1048576), "copy traffic accounting");
}
int main(int argc, char **argv) {
    try {
        check(argc == 2, "usage: short-negative ddr_bench.bin");
        const auto image = readFile(argv[1]);
        check(!image.empty() && image.size() < 0x200000, "benchmark program bounds");
        // Independent RV64I ROM stub: enable FIFO as BootROM does, call entry,
        // then print a return marker. This intentionally skips serial uploading,
        // which is covered by the existing board-download tests.
        Bytes rom;
        word(rom, 0x00200297); // auipc t0,0x200 -> entry 0x80200000
        word(rom, 0x10000337); // lui t1,0x10000 -> UART
        word(rom, 0x00700393); // addi t2,zero,7
        word(rom, 0x00730123); // sb t2,2(t1) -> FCR=7
        word(rom, 0x000280e7); // jalr ra,0(t0); return address 0x80000014
        Bytes returned = instructionFixture('R');
        returned.resize(returned.size() - 4); // replace fixture's ret with a stop loop
        word(returned, 0x0000006f);
        rom.insert(rom.end(), returned.begin(), returned.end());
        Test test(rom); // No post-DDR-ready tick until after memory initialization.
        LocalityObserver perf; perf.startPc=LOCALITY_START_PC; perf.endPc=LOCALITY_STOP_PC;
        test.observer=LocalityObserver::sample; test.observerContext=&perf;
        for (size_t offset = 0; offset < image.size(); offset += 8) {
            uint64_t value = 0;
            for (unsigned lane = 0; lane < 8 && offset + lane < image.size(); ++lane)
                value |= uint64_t(image[offset + lane]) << (8 * lane);
            test.ddr.memory[uint32_t(offset)] = value;
        }
        // Deliberately corrupt the independent host expectation after the first
        // completed cold-read ROI. The unchanged positive run checks every phase,
        // flush and final backing word; this bounded run only proves rejection.
        while(perf.completed<1) {
            check(test.cycles<2000000 && test.received.size()<2048,"short negative guest budget");
            test.tick();
        }
        const auto found=test.ddr.memory.find(0x80400000U-ramBase);
        check(found!=test.ddr.memory.end() && found->second==(0x10203040ULL^1ULL),
              "short locality independent backing-memory mismatch");
        throw std::runtime_error("short locality negative unexpectedly accepted corruption");
    } catch (const std::exception &error) {
        std::cerr << "GSIM D-cache locality application: FAIL " << error.what() << "\n";
        return 1;
    }
}
