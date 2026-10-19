// Frozen functional baseline for BootROM V0.2. This does not qualify timing, DDR or a physical board.
// Normal build: generated BaselineBoardGsim sources + this file; run bootrom.bin sample_app.bin.
// Protocol-only unit check: c++ -std=c++17 -DBASELINE_PROTOCOL_SELFTEST this-file.cpp -o selftest.
#ifndef BASELINE_PROTOCOL_SELFTEST
#include "BaselineBoardGsim.h"
#endif
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

#ifndef BOARD_CYCLE_LIMIT
#define BOARD_CYCLE_LIMIT 30000000ULL
#endif
using Bytes = std::vector<uint8_t>;
static constexpr uint32_t cpuHz = 40000000, uartBaud = 1500000;
static constexpr uint64_t romBase = 0x80000000ULL, ramBase = 0x80200000ULL;
static constexpr size_t ramBytes = 1048576, imageLimit = 0xfc000;
static constexpr uint64_t signatureAddress = ramBase + 0x10000;
static constexpr uint64_t signatureValue = 0x0000024600000055ULL;
static void check(bool good, const std::string &message) {
    if (!good) throw std::runtime_error(message);
}
[[maybe_unused]] static Bytes readFile(const char *path) {
    std::ifstream input(path, std::ios::binary);
    check(bool(input), std::string("cannot read ") + path);
    return Bytes(std::istreambuf_iterator<char>(input), {});
}
// Independent reflected IEEE CRC-32, not the firmware implementation/table.
static uint32_t crc32(const Bytes &bytes) {
    uint32_t crc = 0xffffffffU;
    for (uint8_t byte : bytes) {
        crc ^= byte;
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc >> 1) ^ ((crc & 1) ? 0xedb88320U : 0);
    }
    return ~crc;
}
static void word(Bytes &bytes, uint32_t value) {
    for (unsigned lane = 0; lane < 4; ++lane) bytes.push_back(uint8_t(value >> (8 * lane)));
}
static uint32_t wordAt(const Bytes &bytes, size_t offset) {
    uint32_t value = 0;
    for (unsigned lane = 0; lane < 4; ++lane) value |= uint32_t(bytes.at(offset + lane)) << (8 * lane);
    return value;
}
static Bytes header(const Bytes &image, bool corruptImageCrc = false) {
    Bytes result{'V', 'L', 'D', '1'};
    for (uint32_t value : {1U, uint32_t(ramBase), uint32_t(ramBase), uint32_t(image.size()),
                          crc32(image) ^ uint32_t(corruptImageCrc), 256U, 0U}) word(result, value);
    word(result, crc32(result));
    return result;
}
static Bytes chunk(const Bytes &bytes, uint32_t sequence, bool corrupt = false) {
    Bytes result{'D', 'A', 'T', 'A'};
    word(result, sequence);
    word(result, uint32_t(bytes.size()));
    word(result, crc32(bytes) ^ uint32_t(corrupt));
    result.insert(result.end(), bytes.begin(), bytes.end());
    return result;
}

struct Fixture {
    Bytes image;
    std::map<uint64_t, uint64_t> loads;
};
// Independent RV64I encodings. The host checks load retirement values and the actual RAM byte writes.
static Fixture signatureFixture() {
    Fixture fixture;
    auto emit = [&](uint32_t instruction) { word(fixture.image, instruction); };
    auto load = [&](uint32_t instruction, uint64_t expected) {
        fixture.loads.emplace(ramBase + fixture.image.size(), expected);
        emit(instruction);
    };
    emit(0x802102b7); // lui t0, 0x80210
    emit(0x02029293); // slli t0, t0, 32
    emit(0x0202d293); // srli t0, t0, 32: unsigned physical address 0x80210000
    emit(0x13500313); // addi t1, zero, 0x135
    emit(0x0062b023); // sd t1, 0(t0)
    emit(0x07a00313); // addi t1, zero, 0x7a
    emit(0x006280a3); // sb t1, 1(t0)
    emit(0x24600313); // addi t1, zero, 0x246
    emit(0x00629223); // sh t1, 4(t0)
    emit(0x05500313); // addi t1, zero, 0x55
    emit(0x0062a023); // sw t1, 0(t0)
    load(0x0002c383, 0x55); // lbu t2, 0(t0)
    load(0x0042d383, 0x246); // lhu t2, 4(t0)
    load(0x0002a383, 0x55); // lw t2, 0(t0)
    load(0x0002b383, signatureValue); // ld t2, 0(t0)
    emit(0x0330000f); // fence rw, rw
    emit(0x0000100f); // fence.i: this platform writes dirty private lines back
    emit(0x100002b7); // lui t0, 0x10000: UART base
    for (uint8_t c : std::string("BASELINE RAM OK\r\n")) {
        emit(0x0052c303); // lbu t1, 5(t0)
        emit(0x02037313); // andi t1, t1, 32
        emit(0xfe030ce3); // beq t1, zero, -8
        emit((uint32_t(c) << 20) | 0x00000313); // addi t1, zero, character
        emit(0x00628023); // sb t1, 0(t0)
    }
    emit(0x00008067); // ret, preserving the BootROM's ra and sp
    return fixture;
}

#ifndef BASELINE_PROTOCOL_SELFTEST
struct Test {
    std::unique_ptr<SBaselineBoardGsim> dut = std::make_unique<SBaselineBoardGsim>();
    Bytes rom, activeImage, received, shadow = Bytes(ramBytes), known = Bytes(ramBytes);
    Fixture fixture;
    struct Reply { uint64_t value, mask; };
    std::deque<Reply> replies;
    uint64_t cycles = 0, romCommits = 0, ramCommits = 0, reads = 0, writes = 0, checkedBytes = 0;
    uint64_t hostFraction = 0;
    unsigned phase = 0, timer = 0, byte = 0, checkedLoads = 0;
    size_t consumed = 0;
    bool running = false, executionAllowed = false, checkingFixture = false;
    static constexpr unsigned period = (cpuHz + uartBaud / 2) / uartBaud;

    void retirement(bool valid, uint64_t pc, uint32_t instruction, bool writesRd, unsigned rd, uint64_t data) {
        if (!valid) return;
        const Bytes *expected = nullptr;
        uint64_t base = 0;
        if (pc >= romBase && pc + 4 <= romBase + rom.size()) {
            ++romCommits;
            expected = &rom;
            base = romBase;
        } else if (pc >= ramBase && pc + 4 <= ramBase + activeImage.size()) {
            check(executionAllowed, "RAM instruction retired before verified AUTOBOOT authorization");
            ++ramCommits;
            expected = &activeImage;
            base = ramBase;
        } else {
            std::cerr << "unexpected retired pc=0x" << std::hex << pc << std::dec << '\n';
            throw std::runtime_error("retirement outside the ROM/downloaded image");
        }
        check((pc & 3) == 0 && instruction == wordAt(*expected, size_t(pc - base)),
              "retired instruction differs from independent binary-byte oracle");
        if (checkingFixture) {
            const auto found = fixture.loads.find(pc);
            if (found != fixture.loads.end()) {
                check(writesRd && rd == 7 && data == found->second, "RAM load retirement signature mismatch");
                ++checkedLoads;
            }
        }
    }
    void memory() {
        if (dut->get_io$$ramRequest()) {
            const uint64_t address = dut->get_io$$ramAddress();
            const unsigned size = dut->get_io$$ramSize(), mask = dut->get_io$$ramMask();
            const uint64_t data = dut->get_io$$ramWriteData();
            const unsigned count = 1U << size;
            check(size <= 3 && address >= ramBase && address + count <= ramBase + ramBytes,
                  "RAM request outside the frozen aperture");
            check((address & (count - 1)) == 0 && mask == (((1U << count) - 1) << (address & 7)),
                  "RAM request alignment/byte-lane mask mismatch");
            const size_t offset = size_t((address & ~7ULL) - ramBase);
            Reply reply{0, 0};
            if (dut->get_io$$ramWrite()) {
                ++writes;
                for (unsigned lane = 0; lane < 8; ++lane) if (mask & (1U << lane)) {
                    shadow.at(offset + lane) = uint8_t(data >> (lane * 8));
                    known.at(offset + lane) = 1;
                }
                reply.mask = ~0ULL; // Writes acknowledge with zero data.
            } else {
                ++reads;
                // Uninitialized RAM is deliberately unknown, not a fabricated all-zero oracle.
                for (unsigned lane = 0; lane < 8; ++lane) if (known.at(offset + lane)) {
                    reply.value |= uint64_t(shadow.at(offset + lane)) << (lane * 8);
                    reply.mask |= 0xffULL << (lane * 8);
                    ++checkedBytes;
                }
            }
            replies.push_back(reply);
        }
        if (dut->get_io$$ramResponse()) {
            check(!replies.empty(), "RAM response has no accepted request");
            check(!dut->get_io$$ramError(), "unexpected RAM error/page fault");
            const auto reply = replies.front();
            replies.pop_front();
            check(((dut->get_io$$ramReadData() ^ reply.value) & reply.mask) == 0,
                  "RAM response differs from ordered independent byte shadow");
        }
        check(replies.size() <= 4, "RAM outstanding response capacity exceeded");
    }
    void tick() {
        check(cycles < BOARD_CYCLE_LIMIT, "bounded functional boot exceeded BOARD_CYCLE_LIMIT");
        dut->step();
        ++cycles;
        if (running) {
            if (dut->get_io$$trap$$valid()) {
                std::cerr << "trap pc=0x" << std::hex << dut->get_io$$trap$$bits$$pc()
                          << " cause=" << dut->get_io$$trap$$bits$$cause()
                          << " tval=0x" << dut->get_io$$trap$$bits$$tval() << std::dec << '\n';
                throw std::runtime_error("unexpected architectural trap");
            }
            retirement(dut->get_io$$commit0$$valid(), dut->get_io$$commit0$$bits$$pc(),
                       dut->get_io$$commit0$$bits$$instruction(), dut->get_io$$commit0$$bits$$writesRd(),
                       dut->get_io$$commit0$$bits$$rd(), dut->get_io$$commit0$$bits$$data());
            retirement(dut->get_io$$commit1$$valid(), dut->get_io$$commit1$$bits$$pc(),
                       dut->get_io$$commit1$$bits$$instruction(), dut->get_io$$commit1$$bits$$writesRd(),
                       dut->get_io$$commit1$$bits$$rd(), dut->get_io$$commit1$$bits$$data());
            memory();
        }
        const bool tx = dut->get_io$$uartTx();
        if (!phase) {
            if (!tx) { phase = 1; timer = period + period / 2 - 1; byte = 0; }
        } else if (timer) --timer;
        else if (phase <= 8) {
            byte |= unsigned(tx) << (phase - 1);
            ++phase;
            timer = period - 1;
        } else {
            check(tx, "UART TX stop bit");
            received.push_back(uint8_t(byte));
            phase = 0;
        }
    }
    void idle(unsigned count) { while (count--) tick(); }
    explicit Test(Bytes image) : rom(std::move(image)), fixture(signatureFixture()) {
        // The pinned generator's constructor under-clears its array storage. Keep its established deterministic init.
        static_assert(std::is_trivially_copyable_v<SBaselineBoardGsim>);
        std::memset(dut.get(), 0, sizeof(*dut));
        dut->cycles = 0; dut->LOG_START = 1; dut->LOG_END = 0; dut->activateAll();
        check(!rom.empty() && rom.size() <= 131072, "boot ROM image size");
        dut->set_io$$uartRx(1);
        dut->set_io$$program$$hold(1);
        dut->set_io$$program$$write(0);
        dut->set_io$$program$$index(0);
        dut->set_io$$program$$data(0);
        dut->set_reset(1); idle(4); dut->set_reset(0);
        for (size_t offset = 0; offset < rom.size(); offset += 4) {
            uint32_t value = 0;
            for (unsigned lane = 0; lane < 4 && offset + lane < rom.size(); ++lane)
                value |= uint32_t(rom[offset + lane]) << (8 * lane);
            dut->set_io$$program$$write(1);
            dut->set_io$$program$$index(offset / 4);
            dut->set_io$$program$$data(value);
            tick();
        }
        dut->set_io$$program$$write(0); idle(4);
        dut->set_io$$program$$hold(0); running = true;
    }
    void resetBoard() {
        idle(1000);
        check(replies.empty(), "reset requested with an outstanding RAM transaction");
        running = false; executionAllowed = false; checkingFixture = false;
        dut->set_io$$uartRx(1); dut->set_io$$program$$hold(1); dut->set_reset(1);
        phase = timer = byte = 0; idle(8);
        dut->set_reset(0); idle(4);
        phase = timer = byte = 0; hostFraction = 0; consumed = received.size();
        dut->set_io$$program$$hold(0); running = true;
        // Neither program port nor simulator reinitialization rewrites ROM/RAM here.
    }
    unsigned hostBitCycles() {
        unsigned count = cpuHz / uartBaud;
        hostFraction += cpuHz % uartBaud;
        if (hostFraction >= uartBaud) { hostFraction -= uartBaud; ++count; }
        return count;
    }
    void send(uint8_t value) {
        for (unsigned bit = 0; bit < 10; ++bit) {
            dut->set_io$$uartRx(bit == 0 ? 0 : bit == 9 ? 1 : (value >> (bit - 1)) & 1);
            idle(hostBitCycles());
        }
        dut->set_io$$uartRx(1); idle(hostBitCycles());
    }
    void send(const Bytes &bytes) { for (uint8_t value : bytes) send(value); }
    size_t expect(const std::string &marker, size_t suffix = 0) {
        const uint64_t deadline = std::min<uint64_t>(BOARD_CYCLE_LIMIT, cycles + 5000000);
        while (cycles < deadline) {
            const auto found = std::search(received.begin() + consumed, received.end(), marker.begin(), marker.end());
            if (found != received.end()) {
                const size_t position = size_t(found - received.begin());
                if (received.size() >= position + marker.size() + suffix) {
                    consumed = position + marker.size() + suffix;
                    return position;
                }
            }
            tick();
        }
        std::cerr << "timeout marker=" << marker << " cycle=" << cycles << " fetchPc=0x"
                  << std::hex << dut->get_io$$fetchPc() << std::dec << " UART=";
        for (size_t i = consumed; i < received.size(); ++i)
            if (received[i] >= 32 && received[i] < 127) std::cerr << char(received[i]);
            else std::cerr << '<' << unsigned(received[i]) << '>';
        std::cerr << '\n';
        throw std::runtime_error("UART response timeout");
    }
    void banner() {
        expect("Valence Bootrom V0.2 | verified downloads auto-boot\r\n");
        downloadMode();
    }
    void downloadMode() { expect("download mode (UART); verified images auto-boot\r\n"); }
    void ack(uint32_t sequence, uint32_t status) {
        const size_t offset = expect("VACK", 8);
        check(wordAt(received, offset + 4) == sequence, "VACK sequence mismatch");
        check(wordAt(received, offset + 8) == status, "VACK status mismatch");
    }
    void upload(const Bytes &image, bool badImageCrc, bool retryChunk = false) {
        check(!image.empty() && image.size() <= imageLimit, "application size outside baseline RAM");
        activeImage = image; executionAllowed = false;
        send('d'); expect("VLOAD1\r\n"); send(header(image, badImageCrc)); ack(0xffffffffU, 0);
        uint32_t sequence = 0;
        for (size_t offset = 0; offset < image.size(); offset += 256, ++sequence) {
            const Bytes bytes(image.begin() + offset, image.begin() + std::min(offset + 256, image.size()));
            if (retryChunk && sequence == 0) { send(chunk(bytes, sequence, true)); ack(sequence, 3); }
            send(chunk(bytes, sequence)); ack(sequence, 0);
        }
        if (badImageCrc) {
            ack(0xffffffffU, 3); expect("IMAGE CRC FAIL\r\n"); downloadMode();
            check(ramCommits == 0, "bad CRC image executed");
            return;
        }
        const size_t offset = expect("VDON", 8);
        check(wordAt(received, offset + 4) == image.size() && wordAt(received, offset + 8) == crc32(image),
              "VDON length/CRC mismatch");
        // VDON is emitted only after actual RAM writeback/readback. This oracle does not trust that claim alone.
        for (size_t index = 0; index < image.size(); ++index)
            check(known[index] && shadow[index] == image[index], "downloaded RAM byte differs from the host image");
        expect("DOWNLOAD OK\r\n");
        executionAllowed = true;
        expect("AUTOBOOT\r\n");
        expect("boot from UART (RAM) @ 0x0000000080200000\r\n");
    }
    void returned() {
        expect("APP RETURN\r\n");
        expect("EXTERNAL STATE LOCKED; BOARD RESET REQUIRED; peripheral ownership unknown\r\n");
        expect("locked> ");
        executionAllowed = false;
    }
};
#endif

int main(int argc, char **argv) {
    try {
#ifdef BASELINE_PROTOCOL_SELFTEST
        (void)argc; (void)argv;
        const Bytes standard{'1','2','3','4','5','6','7','8','9'};
        check(crc32(standard) == 0xcbf43926U && crc32({}) == 0, "IEEE CRC known-answer check");
        const auto fixture = signatureFixture();
        check(fixture.image.size() == 416 && fixture.loads.size() == 4, "signature fixture layout");
        const auto good = header(fixture.image), bad = header(fixture.image, true);
        check(good.size() == 36 && wordAt(good, 0) == 0x31444c56U && wordAt(good, 16) == 416,
              "VLD1 independent header framing");
        check(wordAt(good, 32) == crc32(Bytes(good.begin(), good.begin() + 32)) &&
              wordAt(bad, 32) == crc32(Bytes(bad.begin(), bad.begin() + 32)) &&
              (wordAt(good, 20) ^ wordAt(bad, 20)) == 1, "valid header carrying a deliberately bad image CRC");
        const auto frame = chunk(standard, 7, true);
        check(frame.size() == 25 && wordAt(frame, 0) == 0x41544144U && wordAt(frame, 4) == 7 &&
              wordAt(frame, 8) == 9 && wordAt(frame, 12) == (0xcbf43926U ^ 1U), "DATA framing");
        std::cout << "baseline UART protocol/fixture host self-test: PASS (no hardware execution)\n";
#else
        check(argc == 3, "usage: run bootrom.bin sample_app.bin");
        Test test(readFile(argv[1]));
        const Bytes sample = readFile(argv[2]);
        test.banner();
        check(test.romCommits > 0 && test.ramCommits == 0, "reset did not execute only the ROM");
        std::cout << "reset ROM banner / ROM instruction-byte oracle: PASS\n";
        test.upload(test.fixture.image, true);
        test.send('g'); test.expect("MANUAL RUN REMOVED; download a fresh image\r\n");
        test.idle(1000);
        check(test.ramCommits == 0, "rejected image or removed manual launch executed RAM");
        std::cout << "whole-image bad CRC / no unverified execution / manual launch removed: PASS\n";
        test.upload(sample, false, true);
        test.expect("RAM APP OK\r\n"); test.returned();
        check(test.ramCommits > 0, "sample UART marker lacked RAM instruction retirement");
        std::cout << "chunk CRC retry / RAM image byte oracle / AUTOBOOT sample guest: PASS\n";
        const uint64_t before = test.ramCommits;
        const size_t lockStart = test.received.size();
        test.send('d');
        test.expect("EXTERNAL STATE LOCKED; BOARD RESET REQUIRED; peripheral ownership unknown\r\n");
        test.expect("locked> ");
        test.send('g'); test.expect("MANUAL RUN REMOVED; download a fresh image\r\n");
        test.idle(1000);
        const std::string locked(test.received.begin() + lockStart, test.received.end());
        check(test.ramCommits == before && locked.find("VLOAD1") == std::string::npos &&
              locked.find("AUTOBOOT") == std::string::npos, "returned application bypassed reset-only lock");
        std::cout << "APP RETURN / download and manual-launch lock: PASS\n";
        test.resetBoard(); test.banner();
        test.checkingFixture = true;
        test.upload(test.fixture.image, false);
        test.expect("BASELINE RAM OK\r\n"); test.returned();
        check(test.checkedLoads == 4, "signature load checks were not all retired exactly once");
        for (unsigned lane = 0; lane < 8; ++lane) {
            const size_t offset = size_t(signatureAddress - ramBase) + lane;
            check(test.known[offset] && test.shadow[offset] == uint8_t(signatureValue >> (lane * 8)),
                  "physical RAM byte signature mismatch after guest fence.i");
        }
        check(test.reads > 0 && test.writes > 0 && test.checkedBytes > 0, "RAM oracle coverage absent");
        std::cout << "hardware reset / fresh AUTOBOOT / byte-half-word-doubleword loads / RAM signature: PASS\n"
                  << "IRQ delivery chain: NOT COVERED\n"
                  << "DDR / Linux / frequency / physical board: NOT COVERED\n"
                  << "GSIM functional board baseline: PASS cycles=" << test.cycles
                  << " romCommits=" << test.romCommits << " ramCommits=" << test.ramCommits
                  << " ramReads=" << test.reads << " ramWrites=" << test.writes
                  << " checkedReadBytes=" << test.checkedBytes << " uartBytes=" << test.received.size()
                  << " romBytes=" << test.rom.size() << " sampleBytes=" << sample.size()
                  << " uartDivisor=1 ramBytes=1048576\n";
#endif
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "functional board baseline: FAIL " << error.what() << '\n';
        return 1;
    }
}
