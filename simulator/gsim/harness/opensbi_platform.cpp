#include "OpenSbiPlatformGsim.h"
#include <algorithm>
#include <cerrno>
#include <csignal>
#include <cstdint>
#include <deque>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <sstream>
#include <string>
#include <termios.h>
#include <unistd.h>
#include <vector>

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

static void drive(SOpenSbiPlatformGsim &dut) {
    dut.set_io$$hold(0);
    dut.set_io$$romWrite(0);
    dut.set_io$$romIndex(0);
    dut.set_io$$romData(0);
    dut.set_io$$ramWrite(0);
    dut.set_io$$ramIndex(0);
    dut.set_io$$ramData(0);
    dut.set_io$$inspectRegister(12);
    dut.set_io$$uartRx(1);
}

class ConsoleInput {
public:
    bool tty = false;
    bool eof = false;
    bool stop = false;
    std::deque<uint8_t> bytes;
    std::string expectedEcho;

    void activate() {
        tty = isatty(STDIN_FILENO);
        if (tty) {
            check(tcgetattr(STDIN_FILENO, &originalTerm) == 0, "cannot read terminal settings");
            termios active = originalTerm;
            active.c_lflag &= ~(ICANON | ECHO);
            active.c_cc[VMIN] = 0;
            active.c_cc[VTIME] = 0;
            check(tcsetattr(STDIN_FILENO, TCSANOW, &active) == 0, "cannot set terminal input mode");
            changedTerm = true;
        }
        originalFlags = fcntl(STDIN_FILENO, F_GETFL);
        check(originalFlags >= 0 && fcntl(STDIN_FILENO, F_SETFL, originalFlags | O_NONBLOCK) == 0,
              "cannot make terminal input nonblocking");
    }

    ~ConsoleInput() {
        if (originalFlags >= 0) fcntl(STDIN_FILENO, F_SETFL, originalFlags);
        if (changedTerm) tcsetattr(STDIN_FILENO, TCSANOW, &originalTerm);
    }

    void poll() {
        if (eof || stop || bytes.size() >= 4096) return;
        uint8_t buffer[256];
        const size_t space = std::min(sizeof(buffer), size_t(4096 - bytes.size()));
        const ssize_t count = read(STDIN_FILENO, buffer, space);
        if (count < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) return;
            throw std::runtime_error("terminal input read failed");
        }
        if (count == 0) {
            if (!tty) eof = true;
            return;
        }
        for (ssize_t index = 0; index < count; ++index) {
            if (tty && buffer[index] == 4) { stop = true; break; }
            bytes.push_back(buffer[index]);
            if (!tty) expectedEcho += char(buffer[index]);
        }
    }

private:
    int originalFlags = -1;
    bool changedTerm = false;
    termios originalTerm{};
};

class SerialRx {
public:
    bool active = false;

    bool next(std::deque<uint8_t> &bytes) {
        if (!active && !bytes.empty()) {
            value = bytes.front();
            bytes.pop_front();
            frameCycle = 0;
            active = true;
        }
        if (!active) return true;
        const unsigned bit = frameCycle / 16;
        const bool level = bit == 0 ? false : bit == 9 ? true : (value >> (bit - 1)) & 1;
        if (++frameCycle == 160) active = false;
        return level;
    }

private:
    uint8_t value = 0;
    unsigned frameCycle = 0;
};

static void loadRom(SOpenSbiPlatformGsim &dut, const std::vector<uint8_t> &code) {
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

static void loadRam(SOpenSbiPlatformGsim &dut, const std::vector<uint8_t> &code,
                    uint64_t address) {
    constexpr uint64_t base = 0x80010000;
    constexpr uint64_t bytes = 1 << 20;
    check(address >= base && address + code.size() <= base + bytes && !(address & 7),
          "RAM image exceeds the platform window");
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
        check(argc == 4 || consoleMode,
              "expected reset ROM, OpenSBI fw_jump, and S-mode probe images [--console]");
        const auto resetImage = image(argv[1]);
        const auto firmware = image(argv[2]);
        const auto nextStage = image(argv[3]);
        SOpenSbiPlatformGsim dut;
        drive(dut);
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
        loadRom(dut, resetImage);
        loadRam(dut, firmware, 0x80040000);
        loadRam(dut, nextStage, 0x80100000);
        drive(dut);
        dut.set_io$$hold(1);
        dut.step();

        unsigned txPhase = 0, txTimer = 0;
        uint8_t txByte = 0;
        std::string console;
        unsigned commits = 0, traps = 0, unexpectedTraps = 0, handoffCycle = 0;
        uint64_t lastPc = 0, lastTrapPc = 0, lastCause = 0, lastTval = 0;
        uint64_t firstTrapPc = 0, firstCause = 0, firstTval = 0;
        std::deque<uint64_t> recentPcs;
        std::deque<uint64_t> firstTrapRecentPcs;
        std::vector<std::string> trapEvents;
        ConsoleInput input;
        SerialRx serialRx;
        std::string echoed;
        uint64_t lastTxCycle = 0;
        for (uint64_t cycle = 1; !stopRequested; ++cycle) {
            if (!handoffCycle && cycle > 10000000) break;
            drive(dut);
            if (consoleMode && handoffCycle && cycle > handoffCycle + 1024) {
                if ((cycle & 63) == 0) input.poll();
                dut.set_io$$uartRx(serialRx.next(input.bytes));
            }
            dut.step();
            if (dut.get_io$$commit0()) {
                ++commits;
                lastPc = dut.get_io$$commit0Pc();
                recentPcs.push_back(lastPc);
                if (recentPcs.size() > 12) recentPcs.pop_front();
            }
            if (dut.get_io$$commit1()) {
                ++commits;
                lastPc = dut.get_io$$commit1Pc();
                recentPcs.push_back(lastPc);
                if (recentPcs.size() > 12) recentPcs.pop_front();
            }
            if (dut.get_io$$trap()) {
                const uint64_t cause = dut.get_io$$trapCause();
                if (cause != 2 && cause != 3 && cause != 9) ++unexpectedTraps;
                if (trapEvents.size() < 48) {
                    std::ostringstream event;
                    event << std::hex << dut.get_io$$trapPc() << ':'
                          << dut.get_io$$trapCause() << ':' << dut.get_io$$trapTval();
                    trapEvents.push_back(event.str());
                }
                if (!traps) {
                    firstTrapPc = dut.get_io$$trapPc();
                    firstCause = dut.get_io$$trapCause();
                    firstTval = dut.get_io$$trapTval();
                    firstTrapRecentPcs = recentPcs;
                }
                ++traps;
                lastTrapPc = dut.get_io$$trapPc();
                lastCause = dut.get_io$$trapCause();
                lastTval = dut.get_io$$trapTval();
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
                    if (console.size() < 65536) console += char(txByte);
                    if (consoleMode) {
                        std::cout.put(char(txByte));
                        std::cout.flush();
                        if (cycle > handoffCycle + 1024 && handoffCycle) echoed += char(txByte);
                    }
                    lastTxCycle = cycle;
                }
                txPhase = 0;
            }
            if (!handoffCycle && dut.get_io$$committedValue() == 0x53424921ULL) {
                handoffCycle = cycle;
                if (!consoleMode) break;
                check(console.find("OpenSBI v1.9") != std::string::npos &&
                      console.find("Domain0 Next Mode           : S-mode") != std::string::npos &&
                      !unexpectedTraps, "OpenSBI console boot failed");
                input.activate();
                std::signal(SIGINT, stopConsole);
                std::signal(SIGTERM, stopConsole);
                std::cerr << "\n[GSIM UART ready; type to echo, Ctrl+D or Ctrl+C to exit]\n";
            }
            if (consoleMode && handoffCycle && input.stop) break;
            if (consoleMode && handoffCycle && !input.tty && input.eof && input.bytes.empty() &&
                !serialRx.active && echoed.size() >= input.expectedEcho.size() &&
                cycle > handoffCycle + 1024 && cycle > lastTxCycle + 160) {
                check(echoed == input.expectedEcho, "UART RX/TX echo mismatch");
                break;
            }
            if (consoleMode && handoffCycle && !input.tty && input.eof &&
                cycle > handoffCycle + 2000000)
                throw std::runtime_error("UART input echo timeout");
        }
        drive(dut);
        dut.set_io$$inspectRegister(10);
        dut.step();
        const uint64_t sbiError = dut.get_io$$committedValue();
        dut.set_io$$inspectRegister(11);
        dut.step();
        const uint64_t sbiVersion = dut.get_io$$committedValue();
        if (!handoffCycle || console.find("OpenSBI v1.9") == std::string::npos ||
            console.find("Domain0 Next Mode           : S-mode") == std::string::npos ||
            unexpectedTraps || sbiError || sbiVersion != 0x03000000) {
            std::cerr << "OpenSBI boot diagnostic: handoffCycle=" << handoffCycle
                      << " commits=" << commits << " traps=" << traps
                      << " unexpectedTraps=" << unexpectedTraps
                      << " lastPc=0x" << std::hex << lastPc
                      << " firstTrapPc=0x" << firstTrapPc << " firstCause=0x" << firstCause
                      << " firstTval=0x" << firstTval
                      << " lastTrapPc=0x" << lastTrapPc << " cause=0x" << lastCause
                      << " tval=0x" << lastTval << " fetchPc=0x" << dut.get_io$$fetchPc()
                      << " sbiError=0x" << sbiError << " sbiVersion=0x" << sbiVersion << std::dec
                      << "\nrecent PCs:";
            for (auto pc : recentPcs) std::cerr << " 0x" << std::hex << pc;
            std::cerr << std::dec << "\nUART:\n" << console << '\n';
            std::cerr << "Before first trap:";
            for (auto pc : firstTrapRecentPcs) std::cerr << " 0x" << std::hex << pc;
            std::cerr << std::dec << '\n';
            std::cerr << "Traps:";
            for (const auto &event : trapEvents) std::cerr << ' ' << event;
            std::cerr << '\n';
            throw std::runtime_error("OpenSBI banner or S-mode SBI handoff missing");
        }
        if (consoleMode) {
            std::cerr << "\nGSIM OpenSBI console: PASS commits=" << commits << " traps=" << traps
                      << " handoffCycle=" << handoffCycle << " sbiVersion=0x" << std::hex
                      << sbiVersion << std::dec << '\n';
        } else {
            std::cout << "GSIM OpenSBI v1.9: PASS commits=" << commits << " traps=" << traps
                      << " handoffCycle=" << handoffCycle << " sbiVersion=0x" << std::hex
                      << sbiVersion << std::dec << "\nUART:\n" << console;
        }
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM OpenSBI v1.9: FAIL " << error.what() << '\n';
        return 1;
    }
}
