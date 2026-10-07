#include "BoardSocGsim.h"
#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#ifdef DDR_MODEL
#include <unordered_map>
#endif
#ifndef BOARD_CPU_HZ
#define BOARD_CPU_HZ 40000000U
#endif

#ifndef BOARD_UART_BAUD
#define BOARD_UART_BAUD 1500000U
#endif

#ifndef UART_EXTRA_STOP_BITS
#define UART_EXTRA_STOP_BITS 1
#endif

#ifndef UART_DIVISOR
#define UART_DIVISOR 4
#endif

using Bytes = std::vector<uint8_t>;
static constexpr uint32_t ramBase = 0x80200000;
#ifdef DDR_MODEL
static constexpr uint32_t imageLimit = 0x1fffc000;
#else
static constexpr uint32_t imageLimit = 0xfc000;
#endif
static void check(bool good, const std::string &message) {
    if (!good) throw std::runtime_error(message);
}
static Bytes readFile(const char *path) {
    std::ifstream input(path, std::ios::binary);
    check(bool(input), std::string("cannot read ") + path);
    return Bytes(std::istreambuf_iterator<char>(input), {});
}
static uint32_t crc32(const Bytes &bytes) {
    uint32_t crc = 0xffffffff;
    for (uint8_t byte : bytes) {
        crc ^= byte;
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    return ~crc;
}
static void word(Bytes &bytes, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) bytes.push_back(value >> (8 * i));
}
static uint32_t wordAt(const Bytes &bytes, size_t offset) {
    uint32_t result = 0;
    for (unsigned i = 0; i < 4; ++i) result |= uint32_t(bytes.at(offset + i)) << (8 * i);
    return result;
}
static Bytes header(const Bytes &image, uint32_t address = ramBase, uint32_t length = 0) {
    Bytes result{'V', 'L', 'D', '1'};
    for (uint32_t value : {1U, address, address, length ? length : uint32_t(image.size()),
                          crc32(image), 256U, 0U}) word(result, value);
    word(result, crc32(result));
    return result;
}
static Bytes chunk(const Bytes &data, uint32_t sequence, bool corrupt = false) {
    Bytes result{'D', 'A', 'T', 'A'};
    word(result, sequence);
    word(result, data.size());
    word(result, crc32(data) ^ uint32_t(corrupt));
    result.insert(result.end(), data.begin(), data.end());
    return result;
}

// Independent RV64I fixture: UART polling and character immediates, then return.
// Changing A -> B rewrites an executed instruction at the same physical address.
static Bytes instructionFixture(char marker) {
    Bytes result;
    word(result, 0x100002b7); // lui t0, 0x10000 -- UART base
    const std::string message = std::string("FENCE ") + marker + "\r\n";
    for (uint8_t c : message) {
        word(result, 0x0052c303); // lbu t1, 5(t0)
        word(result, 0x02037313); // andi t1, t1, 32
        word(result, 0xfe030ce3); // beq t1, zero, -8
        word(result, (uint32_t(c) << 20) | 0x00000313); // addi t1, zero, character
        word(result, 0x00628023); // sb t1, 0(t0)
    }
    word(result, 0x00008067); // ret
    return result;
}

#ifdef DDR_MODEL
// Independent sparse AXI memory; protocol model, not a DDR PHY/CDC model.
struct DdrModel {
    std::unordered_map<uint32_t, uint64_t> memory;
    bool reading = false, writing = false, responding = false;
    unsigned readWait = 0, writeWait = 0, rBeat = 0, wBeat = 0;
    unsigned rCount = 0, wCount = 0, rSize = 0, wSize = 0, rId = 0, wId = 0;
    uint32_t rAddr = 0, wAddr = 0;
    bool arReady = false, awReady = false, wReady = false, rValid = false, bValid = false;
    uint64_t reads = 0, writes = 0, readBursts = 0, writeBursts = 0, stalls = 0;
    void drive(SBoardSocGsim &d, uint64_t cycle) {
        arReady = !reading && !writing && !responding && cycle % 7 != 2;
        awReady = !reading && !writing && !responding && cycle % 11 != 3;
        wReady = writing && cycle % 5 != 1;
        rValid = reading && readWait == 0;
        bValid = responding && writeWait == 0;
        d.set_io$$ddrAxi$$ar$$ready(arReady);
        d.set_io$$ddrAxi$$aw$$ready(awReady);
        d.set_io$$ddrAxi$$w$$ready(wReady);
        d.set_io$$ddrAxi$$r$$valid(rValid);
        d.set_io$$ddrAxi$$r$$bits$$data(rValid ? memory[(rAddr + (rBeat << rSize)) & ~7U] : 0);
        d.set_io$$ddrAxi$$r$$bits$$id(rId);
        d.set_io$$ddrAxi$$r$$bits$$resp(0);
        d.set_io$$ddrAxi$$r$$bits$$last(rValid && rBeat + 1 == rCount);
        d.set_io$$ddrAxi$$b$$valid(bValid);
        d.set_io$$ddrAxi$$b$$bits$$id(wId);
        d.set_io$$ddrAxi$$b$$bits$$resp(0);
    }
    static void address(uint32_t addr, unsigned count, unsigned size, unsigned burst) {
        check(size <= 3 && count <= 16 && burst == 1, "DDR AXI burst format");
        check(addr < 0x20000000U && uint64_t(addr) + (uint64_t(count) << size) <= 0x20000000ULL,
              "DDR address was not rebased into the 512 MiB aperture");
        check((addr & ((1U << size) - 1)) == 0 &&
              (addr & 4095U) + (count << size) <= 4096, "DDR alignment / 4 KiB boundary");
    }
    void sample(SBoardSocGsim &d) {
        if (readWait) --readWait;
        if (writeWait) --writeWait;
        if (d.get_io$$ddrAxi$$ar$$valid()) {
            if (arReady) {
                rAddr = d.get_io$$ddrAxi$$ar$$bits$$addr();
                rCount = d.get_io$$ddrAxi$$ar$$bits$$len() + 1;
                rSize = d.get_io$$ddrAxi$$ar$$bits$$size();
                rId = d.get_io$$ddrAxi$$ar$$bits$$id();
                address(rAddr, rCount, rSize, d.get_io$$ddrAxi$$ar$$bits$$burst());
                reading = true; rBeat = 0; readWait = 4; ++reads; readBursts += rCount > 1;
            } else ++stalls;
        }
        if (d.get_io$$ddrAxi$$aw$$valid()) {
            if (awReady) {
                wAddr = d.get_io$$ddrAxi$$aw$$bits$$addr();
                wCount = d.get_io$$ddrAxi$$aw$$bits$$len() + 1;
                wSize = d.get_io$$ddrAxi$$aw$$bits$$size();
                wId = d.get_io$$ddrAxi$$aw$$bits$$id();
                address(wAddr, wCount, wSize, d.get_io$$ddrAxi$$aw$$bits$$burst());
                writing = true; wBeat = 0; ++writes; writeBursts += wCount > 1;
            } else ++stalls;
        }
        if (d.get_io$$ddrAxi$$w$$valid()) {
            if (wReady) {
                check(bool(d.get_io$$ddrAxi$$w$$bits$$last()) == (wBeat + 1 == wCount), "DDR WLAST");
                auto &value = memory[(wAddr + (wBeat << wSize)) & ~7U];
                const uint64_t data = d.get_io$$ddrAxi$$w$$bits$$data();
                const unsigned mask = d.get_io$$ddrAxi$$w$$bits$$strb();
                for (unsigned lane = 0; lane < 8; ++lane)
                    if (mask & (1U << lane))
                        value = (value & ~(0xffULL << (8 * lane))) | (data & (0xffULL << (8 * lane)));
                if (++wBeat == wCount) { writing = false; responding = true; writeWait = 3; }
            } else ++stalls;
        }
        if (rValid && d.get_io$$ddrAxi$$r$$ready()) {
            if (++rBeat == rCount) reading = false;
            else readWait = 2;
        }
        if (bValid && d.get_io$$ddrAxi$$b$$ready()) responding = false;
    }
};
#endif

struct Test {
    std::unique_ptr<SBoardSocGsim> dut = std::make_unique<SBoardSocGsim>();
    uint64_t cycles = 0;
#ifdef DDR_MODEL
    DdrModel ddr;
#endif
    static constexpr unsigned period = (uint64_t(BOARD_CPU_HZ) * UART_DIVISOR + BOARD_UART_BAUD / 2) / BOARD_UART_BAUD;
    unsigned phase = 0, timer = 0, byte = 0;
    Bytes received;
    size_t consumed = 0;
    bool running = false;
    // Optional read-only observation after combinational evaluation. The memory
    // model and independent protocol/retirement expectations remain unchanged.
    void (*observer)(SBoardSocGsim &, void *) = nullptr;
    void *observerContext = nullptr;

    void tick() {
#ifdef DDR_MODEL
        ddr.drive(*dut, cycles);
#endif
        dut->step();
        if (observer) observer(*dut, observerContext);
#ifdef DDR_MODEL
        ddr.sample(*dut);
#endif
        ++cycles;
        if (running && dut->get_io$$trap$$valid()) {
            std::cerr << "trap pc=0x" << std::hex << dut->get_io$$trap$$bits$$pc()
                      << " cause=" << dut->get_io$$trap$$bits$$cause()
                      << " tval=0x" << dut->get_io$$trap$$bits$$tval() << std::dec << "\n";
            throw std::runtime_error("unexpected CPU trap");
        }
        const bool tx = dut->get_io$$uartTx();
        if (!phase) {
            if (!tx) { phase = 1; timer = period + period / 2 - 1; byte = 0; }
        } else if (timer) {
            --timer;
        } else if (phase <= 8) {
            byte |= unsigned(tx) << (phase - 1);
            ++phase;
            timer = period - 1;
        } else {
            check(tx, "UART TX stop bit");
            received.push_back(byte);
            phase = 0;
        }
    }
    void idle(unsigned count) { while (count--) tick(); }
    explicit Test(const Bytes &rom) {
        check(!rom.empty() && rom.size() <= 128 * 1024, "boot ROM image size");
        dut->set_io$$uartRx(1);
        dut->set_io$$program$$hold(1);
        dut->set_io$$program$$write(0);
        dut->set_io$$program$$index(0);
        dut->set_io$$program$$data(0);
        dut->set_io$$ramProgram$$write(0);
        dut->set_io$$ramProgram$$index(0);
        dut->set_io$$ramProgram$$data(0);
#ifdef DDR_MODEL
        dut->set_io$$ddrReady(0);
#endif
        dut->set_reset(1);
        idle(4);
        dut->set_reset(0);
        for (size_t offset = 0; offset < rom.size(); offset += 4) {
            uint32_t value = 0;
            for (unsigned lane = 0; lane < 4 && offset + lane < rom.size(); ++lane)
                value |= uint32_t(rom[offset + lane]) << (8 * lane);
            dut->set_io$$program$$write(1);
            dut->set_io$$program$$index(offset / 4);
            dut->set_io$$program$$data(value);
            tick();
        }
        dut->set_io$$program$$write(0);
        idle(4);
#ifdef DDR_MODEL
        dut->set_io$$program$$hold(0);
        idle(100);
        check(ddr.reads == 0 && ddr.writes == 0, "CPU accessed DDR before calibration");
        dut->set_io$$ddrReady(1);
#endif
        dut->set_io$$program$$hold(0);
        running = true;
    }
    uint64_t hostFraction = 0;
    unsigned hostBitCycles() {
        const uint64_t scaled = uint64_t(BOARD_CPU_HZ) * UART_DIVISOR;
        unsigned count = scaled / BOARD_UART_BAUD;
        hostFraction += scaled % BOARD_UART_BAUD;
        if (hostFraction >= BOARD_UART_BAUD) {
            hostFraction -= BOARD_UART_BAUD;
            ++count;
        }
        return count;
    }
    void send(uint8_t value) {
        for (unsigned bit = 0; bit < 10; ++bit) {
            dut->set_io$$uartRx(bit == 0 ? 0 : bit == 9 ? 1 : (value >> (bit - 1)) & 1);
            idle(hostBitCycles());
        }
        dut->set_io$$uartRx(1);
        for (unsigned gap = 0; gap < UART_EXTRA_STOP_BITS; ++gap) idle(hostBitCycles());
    }
    void send(const Bytes &bytes) { for (uint8_t byte : bytes) send(byte); }
    size_t expect(const std::string &marker, size_t suffix = 0) {
        // Header rejection deliberately drains RX for 50 ms before replying.
        // A fixed three-million-cycle budget expires before that at 100 MHz.
        // Preserve the legacy minimum and allow the firmware gap plus wire time.
        const uint64_t waitBudget = std::max<uint64_t>(3000000,
            uint64_t(BOARD_CPU_HZ) / 20 + uint64_t(period) * (32 + suffix) * 10 + 100000);
        const uint64_t deadline = cycles + waitBudget;
        while (cycles < deadline) {
            auto found = std::search(received.begin() + consumed, received.end(),
                                     marker.begin(), marker.end());
            if (found != received.end()) {
                const size_t position = size_t(found - received.begin());
                if (received.size() >= position + marker.size() + suffix) {
                    consumed = position + marker.size() + suffix;
                    return position;
                }
            }
            tick();
        }
        std::cerr << "timeout marker=" << marker << " cycle=" << cycles
                  << " fetchPc=0x" << std::hex << dut->get_io$$fetchPc() << std::dec << "\n";
        std::cerr << "UART bytes=" << received.size() << " unconsumed=";
        for (size_t i = consumed; i < received.size(); ++i) {
            const unsigned c = received[i];
            if (c >= 32 && c < 127) std::cerr << char(c);
            else std::cerr << "<" << std::hex << c << std::dec << ">";
        }
        std::cerr << "\n";
        throw std::runtime_error("UART response timeout");
    }
    void downloadMode() { expect("download mode (UART)\r\n"); }
    void ready() { expect("ready to boot\r\n"); }
    void startDownload() { send('d'); expect("VLOAD1\r\n"); }
    void ack(uint32_t sequence, uint32_t status) {
        const auto offset = expect("VACK", 8);
        check(wordAt(received, offset + 4) == sequence, "ACK sequence");
        const auto actual = wordAt(received, offset + 8);
        check(actual == status, "ACK status: expected " + std::to_string(status) +
                                ", received " + std::to_string(actual));
    }
    void download(const Bytes &image, bool checkRetry = false) {
        startDownload();
        send(header(image));
        ack(0xffffffff, 0);
        uint32_t sequence = 0;
        for (size_t offset = 0; offset < image.size(); offset += 256, ++sequence) {
            Bytes data(image.begin() + offset, image.begin() + std::min(offset + 256, image.size()));
            if (checkRetry && sequence == 0) {
                send(chunk(data, sequence, true));
                ack(sequence, 3);
            }
            send(chunk(data, sequence));
            ack(sequence, 0);
            // Only retry a nonfinal chunk: after final VDON the monitor accepts commands.
            if (checkRetry && sequence == 0 && image.size() > 256) {
                send(chunk(data, sequence));
                ack(sequence, 0);
            }
        }
        const auto offset = expect("VDON", 8);
        check(wordAt(received, offset + 4) == image.size(), "VDON length");
        check(wordAt(received, offset + 8) == crc32(image), "VDON image CRC");
        expect("DOWNLOAD OK\r\n");
        ready();
    }
};

int main(int argc, char **argv) {
    try {
        check(argc == 3, "usage: run bootrom.bin sample_app.bin");
        const auto rom = readFile(argv[1]);
        const auto sample = readFile(argv[2]);
        Test test(rom);
        test.expect("Valence Bootrom V0.1\r\n");
        test.downloadMode();
        const auto idleBytes = test.received.size();
        for (uint8_t c : Bytes{'r', 'a', 't', 'e', '\r', '\n'}) test.send(c);
        test.idle(10000);
        check(test.received.size() == idleBytes, "prompt or retired test commands produced output");
        std::cout << "boot banner / download mode / retired commands ignored: PASS\n";
        test.send('g');
        test.expect("NO IMAGE\r\n");
        test.downloadMode();
        std::cout << "no unverified jump: PASS\n";
        const auto fixtureA = instructionFixture('A');
        test.startDownload();
        auto invalidHeader = header(fixtureA);
        invalidHeader.back() ^= 1;
        test.send(invalidHeader);
        test.ack(0xffffffff, 1);
        test.downloadMode();
        std::cout << "header CRC rejection: PASS\n";
        test.startDownload();
        test.send(header(fixtureA, ramBase, imageLimit + 1));
        test.ack(0xffffffff, 2);
        test.downloadMode();
        std::cout << "reserved RAM bounds rejection: PASS\n";
#ifdef DDR_MODEL
        // Exercise the device's large-image range checks without serializing 1 MiB
        // of padding. Complete >1 MiB framing is covered by the host protocol test.
        for (uint32_t length : {0x100004U, imageLimit}) {
            test.startDownload();
            test.send(header(fixtureA, ramBase, length));
            test.ack(0xffffffff, 0);
            test.send(chunk(Bytes{}, 0)); // deliberate zero-length frame abort
            test.ack(0, 1);
            test.expect("DOWNLOAD ABORT\r\n");
            test.downloadMode();
        }
        std::cout << "DDR >1 MiB / maximum image headers accepted: PASS\n";
#endif
        test.download(sample, true);
        test.send('g');
#ifdef DDR_MODEL
        test.expect("boot from UART (DDR) @ 0x0000000080200000\r\n");
#else
        test.expect("boot from UART (RAM) @ 0x0000000080200000\r\n");
#endif
        test.expect("RAM APP OK");
        test.expect("APP RETURN\r\n");
        test.ready();
        std::cout << "sample RAM execution / chunk CRC retry: PASS\n";
        test.download(fixtureA);
        test.send('g');
        test.expect("FENCE A\r\n");
        test.ready();
        test.download(instructionFixture('B'));
        test.send('g');
        test.expect("FENCE B\r\n");
        test.ready();
        std::cout << "same-address rewritten instruction / fence.i: PASS\n";
        test.startDownload();
        auto badImage = header(fixtureA);
        badImage[20] ^= 1;
        badImage.resize(32);
        word(badImage, crc32(badImage));
        test.send(badImage);
        test.ack(0xffffffff, 0);
        test.send(chunk(fixtureA, 0));
        test.ack(0, 0);
        test.ack(0xffffffff, 3);
        test.expect("IMAGE CRC FAIL\r\n");
        test.downloadMode();
        test.send('g');
        test.expect("NO IMAGE\r\n");
        test.downloadMode();
        std::cout << "whole-image CRC / stale-image invalidation: PASS\n";
        std::cout << "GSIM board boot: PASS cycles=" << test.cycles
                  << " uartBytes=" << test.received.size()
                  << " romBytes=" << rom.size() << " sampleBytes=" << sample.size()
                  << " uartDivisor=" << UART_DIVISOR
#ifdef DDR_MODEL
                  << " ramBytes=536870912 romCapacity=131072\n";
        check(test.ddr.readBursts && test.ddr.writeBursts && test.ddr.stalls,
              "DDR regression did not exercise bursts and backpressure");
        std::cout << "AXI DDR reads=" << test.ddr.reads << " writes=" << test.ddr.writes
                  << " burstReads=" << test.ddr.readBursts << " burstWrites=" << test.ddr.writeBursts
                  << " stalls=" << test.ddr.stalls << "\n";
#else
                  << " ramBytes=1048576 romCapacity=131072\n";
#endif
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "GSIM board boot: FAIL " << error.what() << "\n";
        return 1;
    }
}
