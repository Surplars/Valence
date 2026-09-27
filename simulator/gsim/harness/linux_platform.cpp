#include "LinuxPlatformGsim.h"
#include "uart_console.h"
#include <algorithm>
#include <array>
#include <cstdlib>
#include <csignal>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#ifndef LINUX_ISSUE_WIDTH
#define LINUX_ISSUE_WIDTH 2
#endif
#ifndef LINUX_COHERENT_L1
#define LINUX_COHERENT_L1 0
#endif
#ifndef LINUX_CACHE_LINES
#define LINUX_CACHE_LINES 128
#endif
static_assert(LINUX_ISSUE_WIDTH == 2 || LINUX_ISSUE_WIDTH == 4);

static volatile std::sig_atomic_t stopRequested = 0;
static void stopConsole(int) { stopRequested = 1; }

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static std::vector<uint8_t> image(const char *path) {
    std::ifstream input(path, std::ios::binary);
    check(input.good(), "cannot open boot image");
    return std::vector<uint8_t>((std::istreambuf_iterator<char>(input)), {});
}

static void drive(SLinuxPlatformGsim &dut) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$ramWrite(0);
    dut.set_io$$ramIndex(0);
    dut.set_io$$ramData(0);
    dut.set_io$$inspectRegister(17);
    dut.set_io$$uartRx(1);
}

static void loadRom(SLinuxPlatformGsim &dut, const std::vector<uint8_t> &code) {
    check(!code.empty() && code.size() <= 8192, "reset ROM image exceeds the platform ROM");
    for (size_t index = 0; index < (code.size() + 3) / 4; ++index) {
        uint32_t word = 0;
        for (size_t byte = 0; byte < 4; ++byte) {
            const size_t offset = index * 4 + byte;
            if (offset < code.size()) word |= uint32_t(code[offset]) << (byte * 8);
        }
        drive(dut);
        dut.set_io$$hold(1);
        dut.set_io$$romWrite(1);
        dut.set_io$$romIndex(index);
        dut.set_io$$romData(word);
        dut.step();
    }
}

static void loadRam(SLinuxPlatformGsim &dut, const std::vector<uint8_t> &code, uint64_t address) {
    constexpr uint64_t base = 0x80010000;
    constexpr uint64_t bytes = 1 << 26;
    check(address >= base && address + code.size() <= base + bytes && !(address & 7),
          "RAM image exceeds the Linux platform window");
    const uint64_t start = (address - base) / 8;
    for (size_t index = 0; index < (code.size() + 7) / 8; ++index) {
        uint64_t word = 0;
        for (size_t byte = 0; byte < 8; ++byte) {
            const size_t offset = index * 8 + byte;
            if (offset < code.size()) word |= uint64_t(code[offset]) << (byte * 8);
        }
        drive(dut);
        dut.set_io$$hold(1);
        dut.set_io$$ramWrite(1);
        dut.set_io$$ramIndex(start + index);
        dut.set_io$$ramData(word);
        dut.step();
    }
}

int main(int argc, char **argv) {
    try {
        const bool consoleMode = argc == 5 && std::string(argv[4]) == "--console";
        const bool profileMode = argc == 5 && std::string(argv[4]).starts_with("--profile=");
        check(argc == 4 || argc == 5,
              "expected reset ROM, OpenSBI fw_jump, Linux Image [max cycles|--console]");
        const auto resetImage = image(argv[1]);
        const auto firmware = image(argv[2]);
        const auto kernel = image(argv[3]);
        check(kernel.size() >= 64 && kernel[0x30] == 'R' && kernel[0x31] == 'I' &&
              kernel[0x32] == 'S' && kernel[0x33] == 'C' && kernel[0x34] == 'V',
              "kernel is not a RISC-V boot Image");
        const uint64_t maxCycles = profileMode ? std::stoull(std::string(argv[4]).substr(10)) :
            argc == 5 && !consoleMode ? std::stoull(argv[4]) :
            consoleMode ? UINT64_MAX - 1 : 250000000;
        check(maxCycles > 0, "profile cycle count must be positive");
        static SLinuxPlatformGsim dut;
        drive(dut);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
        loadRom(dut, resetImage);
        loadRam(dut, firmware, 0x80040000);
        loadRam(dut, kernel, 0x80200000);
        drive(dut);
        dut.set_io$$hold(1);
        dut.step();

        unsigned txPhase = 0, txTimer = 0;
        uint8_t txByte = 0;
        std::string console;
        bool initReached = false, panicReached = false, exitReached = false;
        UartConsoleInput input;
        UartSerialRx serialRx;
        uint64_t initCycle = 0;
        if (consoleMode) {
            std::signal(SIGINT, stopConsole);
            std::signal(SIGTERM, stopConsole);
        }
        uint64_t commits = 0, traps = 0, cycles = 0;
        uint64_t cacheHits = 0, cacheMisses = 0, emptySlotMisses = 0, replacementMisses = 0;
        uint64_t readMisses = 0, writeMisses = 0;
        uint64_t dirtyEvictions = 0, missBlockedCycles = 0, bypassBlockedCycles = 0;
        uint64_t probeBlockedCycles = 0, evictionCycles = 0, refillCycles = 0;
        uint64_t userCommits = 0;
        uint64_t lastPc = 0, lastTrapPc = 0, lastCause = 0, lastTval = 0;
        std::array<uint64_t, 12> recentPcs{};
        size_t recentCount = 0, recentNext = 0;
        auto recordPc = [&](uint64_t pc) {
            recentPcs[recentNext] = pc;
            recentNext = (recentNext + 1) % recentPcs.size();
            recentCount = std::min(recentCount + 1, recentPcs.size());
        };
        std::vector<std::string> trapEvents;
        std::unordered_map<uint64_t, uint64_t> sampledPcs, sbiExtensions;
        std::unordered_map<uint64_t, uint64_t> trapCauses;
        std::unordered_map<uint64_t, uint64_t> watchedPcs;
        if (const char *watch = std::getenv("VALENCE_LINUX_WATCH_PC")) {
            std::stringstream stream(watch);
            std::string token;
            while (std::getline(stream, token, ',')) watchedPcs.emplace(std::stoull(token, nullptr, 16), 0);
        }
        for (cycles = 1; cycles <= maxCycles && !stopRequested; ++cycles) {
            drive(dut);
            if (consoleMode && initCycle) {
                if ((cycles & 63) == 0) input.poll();
                dut.set_io$$uartRx(serialRx.next(input.bytes));
            }
            dut.step();
            cacheHits += dut.get_io$$cacheHit();
            cacheMisses += dut.get_io$$cacheMiss();
            emptySlotMisses += dut.get_io$$coherentCacheProfile$$emptySlotMiss();
            replacementMisses += dut.get_io$$coherentCacheProfile$$replacementMiss();
            readMisses += dut.get_io$$coherentCacheProfile$$readMiss();
            writeMisses += dut.get_io$$coherentCacheProfile$$writeMiss();
            dirtyEvictions += dut.get_io$$coherentCacheProfile$$dirtyEviction();
            missBlockedCycles += dut.get_io$$coherentCacheProfile$$missBlocked();
            bypassBlockedCycles += dut.get_io$$coherentCacheProfile$$bypassBlocked();
            probeBlockedCycles += dut.get_io$$coherentCacheProfile$$probeBlocked();
            evictionCycles += dut.get_io$$coherentCacheProfile$$evictionCycle();
            refillCycles += dut.get_io$$coherentCacheProfile$$refillCycle();
            auto recordCommit = [&](bool valid, uint64_t pc) {
                if (!valid) return;
                ++commits;
                lastPc = pc;
                if (lastPc < 0x80000000) ++userCommits;
                if (auto entry = watchedPcs.find(lastPc); entry != watchedPcs.end() && !entry->second) {
                    entry->second = cycles;
                    std::cerr << "\nGSIM Linux watch: pc=0x" << std::hex << lastPc << std::dec
                              << " cycle=" << cycles << '\n';
                }
                recordPc(lastPc);
            };
            recordCommit(dut.get_io$$commit0(), dut.get_io$$commit0Pc());
            recordCommit(dut.get_io$$commit1(), dut.get_io$$commit1Pc());
            recordCommit(dut.get_io$$commit2(), dut.get_io$$commit2Pc());
            recordCommit(dut.get_io$$commit3(), dut.get_io$$commit3Pc());
            if (dut.get_io$$trap()) {
                ++traps;
                lastTrapPc = dut.get_io$$trapPc();
                lastCause = dut.get_io$$trapCause();
                lastTval = dut.get_io$$trapTval();
                ++trapCauses[lastCause];
                if (lastCause == 9) ++sbiExtensions[dut.get_io$$committedValue()];
                if (trapEvents.size() < 48) {
                    std::ostringstream event;
                    event << std::hex << lastTrapPc << ':' << lastCause << ':' << lastTval;
                    trapEvents.push_back(event.str());
                }
            }
            const bool tx = dut.get_io$$uartTx();
            if (!txPhase) {
                if (!tx) { txPhase = 1; txTimer = 23; txByte = 0; }
            } else if (txTimer) {
                --txTimer;
            } else if (txPhase <= 8) {
                txByte |= unsigned(tx) << (txPhase - 1);
                ++txPhase;
                txTimer = 15;
            } else {
                if (tx) {
                    if (console.size() < 262144) console += char(txByte);
                    if (consoleMode) serialRx.ack(txByte);
                    std::cout.put(char(txByte));
                    std::cout.flush();
                    if (!initReached && console.find("VALENCE_LINUX_INIT_OK") != std::string::npos) {
                        initReached = true;
                    }
                    if (consoleMode && initReached && !initCycle &&
                        console.find("valence# ") != std::string::npos) {
                        initCycle = cycles;
                        input.activate();
                        std::cerr << "\n[GSIM Linux UART ready; type help, coremark 1, or Ctrl+D to exit]\n";
                    }
                    if (!panicReached) panicReached = console.find("Kernel panic") != std::string::npos;
                    if (!exitReached) exitReached = console.find("VALENCE_LINUX_EXIT") != std::string::npos;
                }
                txPhase = 0;
            }
            if ((!consoleMode && initReached) || panicReached || exitReached || input.stop) break;
            if (cycles > 40000000 && cycles % 1024 == 0) ++sampledPcs[lastPc];
            if (cycles % 5000000 == 0 && !consoleMode)
                std::cerr << "\nGSIM Linux progress: cycles=" << cycles << " commits=" << commits
                          << " traps=" << traps << " pc=0x" << std::hex << lastPc
                          << std::dec << " uartBytes=" << console.size()
                          << " userCommits=" << userCommits << '\n';
        }
        if (profileMode && !panicReached) {
            std::cout << "\nGSIM Linux profile: {\"issue_width\":" << LINUX_ISSUE_WIDTH
                      << ",\"cache\":\"" << (LINUX_COHERENT_L1 ? "coherent" : "direct")
                      << "\",\"cache_lines\":" << LINUX_CACHE_LINES
                      << ",\"cycles\":" << std::min(cycles, maxCycles)
                      << ",\"commits\":" << commits << ",\"cache_hits\":" << cacheHits
                      << ",\"cache_misses\":" << cacheMisses
                      << ",\"empty_slot_misses\":" << emptySlotMisses
                      << ",\"replacement_misses\":" << replacementMisses
                      << ",\"read_misses\":" << readMisses
                      << ",\"write_misses\":" << writeMisses
                      << ",\"dirty_evictions\":" << dirtyEvictions
                      << ",\"miss_blocked_cycles\":" << missBlockedCycles
                      << ",\"bypass_blocked_cycles\":" << bypassBlockedCycles
                      << ",\"probe_blocked_cycles\":" << probeBlockedCycles
                      << ",\"eviction_cycles\":" << evictionCycles
                      << ",\"refill_cycles\":" << refillCycles << "}\n";
            return 0;
        }
        if (!initReached || panicReached || !userCommits || console.find("Linux version ") == std::string::npos) {
            auto inspect = [&](unsigned reg) {
                drive(dut);
                dut.set_io$$inspectRegister(reg);
                dut.step();
                return dut.get_io$$committedValue();
            };
            const uint64_t a0 = inspect(10), t1 = inspect(6), ra = inspect(1), sp = inspect(2);
            std::cerr << "\nLinux boot diagnostic: cycles=" << cycles << " commits=" << commits
                      << " traps=" << traps << " lastPc=0x" << std::hex << lastPc
                      << " fetchPc=0x" << dut.get_io$$fetchPc() << " lastTrapPc=0x"
                      << lastTrapPc << " cause=0x" << lastCause << " tval=0x" << lastTval
                      << " a0=0x" << a0 << " t1=0x" << t1 << " ra=0x" << ra << " sp=0x" << sp
                      << std::dec << " userCommits=" << userCommits << "\nrecent PCs:";
            for (size_t index = 0; index < recentCount; ++index) {
                const size_t slot = (recentNext + recentPcs.size() - recentCount + index) % recentPcs.size();
                std::cerr << " 0x" << std::hex << recentPcs[slot];
            }
            std::cerr << std::dec << "\nTraps:";
            for (const auto &event : trapEvents) std::cerr << ' ' << event;
            auto top = [](const auto &counts) {
                std::vector<std::pair<uint64_t, uint64_t>> entries(counts.begin(), counts.end());
                std::sort(entries.begin(), entries.end(), [](const auto &a, const auto &b) {
                    return a.second > b.second;
                });
                if (entries.size() > 12) entries.resize(12);
                return entries;
            };
            std::cerr << "\nSampled PCs:";
            for (const auto &[pc, count] : top(sampledPcs))
                std::cerr << " 0x" << std::hex << pc << std::dec << ':' << count;
            std::cerr << "\nSBI extensions:";
            for (const auto &[extension, count] : top(sbiExtensions))
                std::cerr << " 0x" << std::hex << extension << std::dec << ':' << count;
            std::cerr << "\nTrap causes:";
            for (const auto &[cause, count] : top(trapCauses))
                std::cerr << " 0x" << std::hex << cause << std::dec << ':' << count;
            std::cerr << '\n';
            throw std::runtime_error(panicReached ? "Linux kernel panic" : "Linux did not start init");
        }
        std::cout << "\nGSIM Linux: PASS issueWidth=" << LINUX_ISSUE_WIDTH
                  << " cache=" << (LINUX_COHERENT_L1 ? "coherent" : "direct")
                  << " cycles=" << cycles << " commits=" << commits
                  << " traps=" << traps << " userCommits=" << userCommits << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM Linux: FAIL " << error.what() << '\n';
        return 1;
    }
}
