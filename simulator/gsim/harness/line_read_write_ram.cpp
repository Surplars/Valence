#include "TileLinkLineReadWriteRamGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool condition, const char *message) {
    if (!condition) throw std::runtime_error(message);
}

static uint64_t lineWord(uint64_t address, unsigned beat) {
    return 0xbb67ae8584caa73bULL ^ (address * 0x100000001b3ULL) ^
           (uint64_t(beat + 1) * 0x0102040810204081ULL);
}

static void drive(STileLinkLineReadWriteRamGsim &dut, bool write, uint64_t writeAddress,
                  unsigned writeTag, bool writeReady, bool read, uint64_t readAddress,
                  unsigned readTag, bool readReady) {
    dut.set_io$$writeRequest$$valid(write);
    dut.set_io$$writeRequest$$bits$$address(writeAddress);
    dut.set_io$$writeRequest$$bits$$tag(writeTag);
    dut.set_io$$writeWord0(lineWord(writeAddress, 0));
    dut.set_io$$writeWord1(lineWord(writeAddress, 1));
    dut.set_io$$writeWord2(lineWord(writeAddress, 2));
    dut.set_io$$writeWord3(lineWord(writeAddress, 3));
    dut.set_io$$writeWord4(lineWord(writeAddress, 4));
    dut.set_io$$writeWord5(lineWord(writeAddress, 5));
    dut.set_io$$writeWord6(lineWord(writeAddress, 6));
    dut.set_io$$writeWord7(lineWord(writeAddress, 7));
    dut.set_io$$writeResponse$$ready(writeReady);
    dut.set_io$$readRequest$$valid(read);
    dut.set_io$$readRequest$$bits$$address(readAddress);
    dut.set_io$$readRequest$$bits$$tag(readTag);
    dut.set_io$$readResponse$$ready(readReady);
}

static std::array<uint64_t, 8> readWords(STileLinkLineReadWriteRamGsim &dut) {
    return {dut.get_io$$readWord0(), dut.get_io$$readWord1(), dut.get_io$$readWord2(),
            dut.get_io$$readWord3(), dut.get_io$$readWord4(), dut.get_io$$readWord5(),
            dut.get_io$$readWord6(), dut.get_io$$readWord7()};
}

int main() {
    STileLinkLineReadWriteRamGsim dut;
    constexpr uint64_t base = 0x80010000ULL;
    drive(dut, false, 0, 0, false, false, 0, 0, false);
    dut.set_reset(1);
    dut.step();
    dut.step();
    dut.set_reset(0);

    unsigned writesIssued = 0, writesDone = 0, maxWrites = 0, heldWrites = 0;
    std::array<bool, 5> seenWrites{};
    for (unsigned cycle = 0; cycle < 5000 && writesDone < 5; ++cycle) {
        const bool ready = cycle % 7 >= 3;
        const uint64_t address = writesIssued == 4 ? base + 4096 : base + 64 * writesIssued;
        drive(dut, writesIssued < 5, address, 0x20 + writesIssued, ready,
              false, 0, 0, false);
        dut.step();
        if (writesIssued < 5 && dut.get_io$$writeRequest$$ready()) ++writesIssued;
        if (dut.get_io$$writeResponse$$valid()) {
            const unsigned tag = dut.get_io$$writeResponse$$bits$$tag();
            check(tag >= 0x20 && tag <= 0x24, "RAM writeback returned unknown tag");
            const unsigned index = tag - 0x20;
            check(index < writesIssued && !seenWrites[index] &&
                  bool(dut.get_io$$writeResponse$$bits$$error()) == (index == 4),
                  "RAM writeback acknowledgement or denied mismatch");
            if (ready) {
                seenWrites[index] = true;
                ++writesDone;
            } else ++heldWrites;
        }
        maxWrites = std::max(maxWrites, writesIssued - writesDone);
    }
    check(writesIssued == 5 && writesDone == 5 && maxWrites == 4 && heldWrites > 0,
          "RAM writeback did not exercise four outstanding requests and response stalls");

    // Exercise the production read/write arbiter with both request directions
    // live. Writes target disjoint lines, so reads must observe the initialized
    // version without relying on cross-direction ordering.
    unsigned parallelWritesIssued = 0, parallelWritesDone = 0;
    unsigned parallelReadsIssued = 0, parallelReadsDone = 0;
    unsigned maxParallelWrites = 0, maxParallelReads = 0;
    std::array<bool, 4> seenParallelWrites{}, seenParallelReads{};
    for (unsigned cycle = 0; cycle < 5000 && (parallelWritesDone < 4 || parallelReadsDone < 4); ++cycle) {
        const bool writeReady = cycle % 6 >= 2;
        const bool readReady = cycle % 5 >= 2;
        drive(dut, parallelWritesIssued < 4, base + 64 * (4 + parallelWritesIssued),
              0x80 + parallelWritesIssued, writeReady,
              parallelReadsIssued < 4, base + 64 * parallelReadsIssued,
              0x90 + parallelReadsIssued, readReady);
        dut.step();
        if (parallelWritesIssued < 4 && dut.get_io$$writeRequest$$ready()) ++parallelWritesIssued;
        if (parallelReadsIssued < 4 && dut.get_io$$readRequest$$ready()) ++parallelReadsIssued;
        if (dut.get_io$$writeResponse$$valid()) {
            const unsigned tag = dut.get_io$$writeResponse$$bits$$tag();
            check(tag >= 0x80 && tag < 0x84, "concurrent line write returned unknown tag");
            const unsigned index = tag - 0x80;
            check(index < parallelWritesIssued && !seenParallelWrites[index] &&
                  !dut.get_io$$writeResponse$$bits$$error(),
                  "concurrent line write acknowledgement mismatch");
            if (writeReady) {
                seenParallelWrites[index] = true;
                ++parallelWritesDone;
            }
        }
        if (dut.get_io$$readResponse$$valid()) {
            const unsigned tag = dut.get_io$$readResponse$$bits$$tag();
            check(tag >= 0x90 && tag < 0x94, "concurrent line read returned unknown tag");
            const unsigned index = tag - 0x90;
            check(index < parallelReadsIssued && !seenParallelReads[index] &&
                  !dut.get_io$$readResponse$$bits$$error(),
                  "concurrent line read acknowledgement mismatch");
            const auto words = readWords(dut);
            for (unsigned beat = 0; beat < 8; ++beat)
                check(words[beat] == lineWord(base + 64 * index, beat),
                      "concurrent line read saw a wrong memory version");
            if (readReady) {
                seenParallelReads[index] = true;
                ++parallelReadsDone;
            }
        }
        maxParallelWrites = std::max(maxParallelWrites, parallelWritesIssued - parallelWritesDone);
        maxParallelReads = std::max(maxParallelReads, parallelReadsIssued - parallelReadsDone);
    }
    check(parallelWritesIssued == 4 && parallelWritesDone == 4 &&
          parallelReadsIssued == 4 && parallelReadsDone == 4 &&
          maxParallelWrites == 4 && maxParallelReads == 4,
          "concurrent line read/write queues did not both make progress");

    unsigned readsIssued = 0, readsDone = 0, maxReads = 0, heldReads = 0;
    std::array<bool, 9> seenReads{};
    for (unsigned cycle = 0; cycle < 5000 && readsDone < 9; ++cycle) {
        const bool ready = cycle % 5 >= 2;
        const uint64_t address = readsIssued == 8 ? base + 4096 : base + 64 * readsIssued;
        drive(dut, false, 0, 0, false,
              readsIssued < 9, address, 0x40 + readsIssued, ready);
        dut.step();
        if (readsIssued < 9 && dut.get_io$$readRequest$$ready()) ++readsIssued;
        if (dut.get_io$$readResponse$$valid()) {
            const unsigned tag = dut.get_io$$readResponse$$bits$$tag();
            check(tag >= 0x40 && tag <= 0x48, "RAM line fill returned unknown tag");
            const unsigned index = tag - 0x40;
            const bool denied = index == 8;
            check(index < readsIssued && !seenReads[index] &&
                  bool(dut.get_io$$readResponse$$bits$$error()) == denied,
                  "RAM line fill response tag or denied mismatch");
            const auto words = readWords(dut);
            for (unsigned beat = 0; beat < 8; ++beat)
                check(words[beat] == (denied ? 0 : lineWord(base + 64 * index, beat)),
                      "RAM line fill readback differs from 64-byte write");
            if (ready) {
                seenReads[index] = true;
                ++readsDone;
            } else ++heldReads;
        }
        maxReads = std::max(maxReads, readsIssued - readsDone);
    }
    check(readsIssued == 9 && readsDone == 9 && maxReads == 4 && heldReads > 0,
          "RAM readback did not exercise four outstanding requests and response stalls");
    std::cout << "GSIM TileLink line read/write RAM: PASS burstWrite readback concurrent denied backpressure" << '\n';
}
