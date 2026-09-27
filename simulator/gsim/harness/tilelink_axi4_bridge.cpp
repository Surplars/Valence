#include "TileLinkAxi4Bridge.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>

static constexpr uint64_t base = 0x80010000;
#ifndef MAX_WRITES
#define MAX_WRITES 4
#endif
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }

struct Request { uint64_t address, data; unsigned size, mask; bool write; };
struct Expected { uint64_t data; unsigned source, size; bool write, error; };
struct ReadReply { uint64_t data; unsigned response, due; };
struct WriteAddress { uint64_t address; unsigned size; };
struct WriteData { uint64_t data; unsigned mask; };

static Request request(unsigned n, bool writeStream) {
    if (writeStream) return {base + 8 * (n % 8), 0x1234000000000000ULL + n, 3, 255, true};
    if (n < 8) return {base + 8 * n, 0x1234000000000000ULL + n, 3, 255, true};
    if (n == 88) return {base + 16, 0x0000000011223344ULL, 2, 15, true};
    if (n % 19 == 0) return {base + 4096, 0, 3, 255, false};
    return {base + 8 * (n % 8), 0, 3, 255, false};
}

static uint64_t readBeat(const std::array<uint8_t, 64> &memory, uint64_t address) {
    unsigned offset = (address - base) & ~7U;
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= uint64_t(memory[offset + i]) << (8 * i);
    return value;
}

static void writeBeat(std::array<uint8_t, 64> &memory, uint64_t address, uint64_t data, unsigned mask) {
    unsigned offset = (address - base) & ~7U;
    for (unsigned i = 0; i < 8; ++i) if (mask & (1U << i)) memory[offset + i] = data >> (8 * i);
}

static void drive(STileLinkAxi4Bridge &dut, const Request &request, bool valid, unsigned source,
                  bool dReady, bool arReady, bool awReady, bool wReady,
                  const std::deque<ReadReply> &reads, const std::deque<ReadReply> &writes,
                  unsigned cycle) {
    dut.set_io$$tl$$a$$valid(valid);
    dut.set_io$$tl$$a$$bits$$opcode(request.write ? 1 : 4);
    dut.set_io$$tl$$a$$bits$$param(0);
    dut.set_io$$tl$$a$$bits$$size(request.size);
    dut.set_io$$tl$$a$$bits$$source(source);
    dut.set_io$$tl$$a$$bits$$address(request.address);
    dut.set_io$$tl$$a$$bits$$mask(request.mask);
    dut.set_io$$tl$$a$$bits$$data(request.data);
    dut.set_io$$tl$$a$$bits$$corrupt(0);
    dut.set_io$$tl$$d$$ready(dReady);
    dut.set_io$$tl$$c$$valid(0);
    dut.set_io$$tl$$e$$valid(0);
    dut.set_io$$axi$$ar$$ready(arReady);
    dut.set_io$$axi$$aw$$ready(awReady);
    dut.set_io$$axi$$w$$ready(wReady);
    bool rValid = !reads.empty() && reads.front().due <= cycle;
    dut.set_io$$axi$$r$$valid(rValid);
    dut.set_io$$axi$$r$$bits$$id(0);
    dut.set_io$$axi$$r$$bits$$data(rValid ? reads.front().data : 0);
    dut.set_io$$axi$$r$$bits$$resp(rValid ? reads.front().response : 0);
    dut.set_io$$axi$$r$$bits$$last(1);
    bool bValid = !writes.empty() && writes.front().due <= cycle;
    dut.set_io$$axi$$b$$valid(bValid);
    dut.set_io$$axi$$b$$bits$$id(0);
    dut.set_io$$axi$$b$$bits$$resp(0);
}

int main(int argc, char **argv) {
    const bool injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    const bool writeStream = argc == 2 && std::string(argv[1]) == "--write-stream";
    const unsigned requestCount = writeStream ? 256 : 105;
    if (argc == 2 && std::string(argv[1]) == "--high-address") {
        STileLinkAxi4Bridge dut;
        std::deque<ReadReply> reads;
        std::deque<ReadReply> writes;
        drive(dut, {}, false, 0, false, false, false, false, reads, writes, 0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        drive(dut, {base + 0x100000000ULL, 0, 3, 255, false},
              true, 0, true, true, true, true, reads, writes, 0);
        dut.step();
        throw std::runtime_error("32-bit AXI accepted a truncated TileLink address");
    }
    STileLinkAxi4Bridge dut;
    std::array<uint8_t, 64> memory{};
    std::array<bool, 8> sourceBusy{};
    std::deque<Expected> expected;
    std::deque<ReadReply> reads;
    std::deque<ReadReply> b;
    std::deque<WriteAddress> aw;
    std::deque<WriteData> w;
    std::optional<WriteAddress> heldAr, heldAw;
    std::optional<WriteData> heldW;
    std::deque<Request> acceptedWrites;
    drive(dut, {}, false, 0, false, false, false, false, reads, b, 0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned issued = 0, retired = 0, arCount = 0, writeCount = 0, denied = 0, peakReads = 0;
    unsigned aStalls = 0, dStalls = 0, arStalls = 0, writeSplit = 0, pendingWrites = 0, peakWrites = 0;
    unsigned cycles = 0;
    for (unsigned cycle = 0; cycle < 15000; ++cycle) {
        cycles = cycle + 1;
        const unsigned source = issued % 8;
        bool valid = issued < requestCount && !sourceBusy[source];
        bool dReady = cycle % 5 != 0, arReady = cycle % 7 != 1;
        bool awReady = cycle % 7 != 2, wReady = cycle % 7 != 4;
        Request req = valid ? request(issued, writeStream) : Request{};
        drive(dut, req, valid, source, dReady, arReady, awReady, wReady, reads, b, cycle);
        dut.step();
        bool aFire = valid && dut.get_io$$tl$$a$$ready();
        bool dFire = dut.get_io$$tl$$d$$valid() && dReady;
        bool arFire = dut.get_io$$axi$$ar$$valid() && arReady;
        bool awFire = dut.get_io$$axi$$aw$$valid() && awReady;
        bool wFire = dut.get_io$$axi$$w$$valid() && wReady;
        bool rFire = !reads.empty() && reads.front().due <= cycle && dut.get_io$$axi$$r$$ready();
        bool bFire = !b.empty() && b.front().due <= cycle && dut.get_io$$axi$$b$$ready();
        if (heldAr) {
            check(dut.get_io$$axi$$ar$$valid() && dut.get_io$$axi$$ar$$bits$$addr() == heldAr->address &&
                  dut.get_io$$axi$$ar$$bits$$size() == heldAr->size, "AXI AR changed under backpressure");
        }
        if (heldAw) {
            check(dut.get_io$$axi$$aw$$valid() && dut.get_io$$axi$$aw$$bits$$addr() == heldAw->address &&
                  dut.get_io$$axi$$aw$$bits$$size() == heldAw->size, "AXI AW changed under backpressure");
        }
        if (heldW) {
            check(dut.get_io$$axi$$w$$valid() && dut.get_io$$axi$$w$$bits$$data() == heldW->data &&
                  dut.get_io$$axi$$w$$bits$$strb() == heldW->mask, "AXI W changed under backpressure");
        }
        heldAr = dut.get_io$$axi$$ar$$valid() && !arReady ?
            std::optional<WriteAddress>{{dut.get_io$$axi$$ar$$bits$$addr(),
                                         unsigned(dut.get_io$$axi$$ar$$bits$$size())}} : std::nullopt;
        heldAw = dut.get_io$$axi$$aw$$valid() && !awReady ?
            std::optional<WriteAddress>{{dut.get_io$$axi$$aw$$bits$$addr(),
                                         unsigned(dut.get_io$$axi$$aw$$bits$$size())}} : std::nullopt;
        heldW = dut.get_io$$axi$$w$$valid() && !wReady ?
            std::optional<WriteData>{{dut.get_io$$axi$$w$$bits$$data(),
                                      unsigned(dut.get_io$$axi$$w$$bits$$strb())}} : std::nullopt;
        if (dut.get_io$$tl$$d$$valid()) {
            check(!expected.empty(), "TileLink D without an accepted A");
            const auto &front = expected.front();
            check(dut.get_io$$tl$$d$$bits$$source() == front.source &&
                  dut.get_io$$tl$$d$$bits$$size() == front.size &&
                  dut.get_io$$tl$$d$$bits$$opcode() == (front.write ? 0 : 1) &&
                  bool(dut.get_io$$tl$$d$$bits$$denied()) == front.error &&
                  dut.get_io$$tl$$d$$bits$$data() == front.data,
                  "TileLink-to-AXI response data, source or order mismatch");
            if (dFire) {
                if (front.write) --pendingWrites;
                sourceBusy[front.source] = false;
                expected.pop_front(); ++retired;
            } else ++dStalls;
        }
        if (rFire) reads.pop_front();
        if (bFire) b.pop_front();
        if (arFire) {
            check(dut.get_io$$axi$$ar$$bits$$id() == 0 && dut.get_io$$axi$$ar$$bits$$len() == 0 &&
                  dut.get_io$$axi$$ar$$bits$$burst() == 1, "AXI read attributes");
            uint64_t address = dut.get_io$$axi$$ar$$bits$$addr();
            unsigned response = address >= base + 4096 ? 2 : 0;
            uint64_t data = response ? 0 : readBeat(memory, address);
            if (injectMismatch && arCount == 0) data ^= 1;
            reads.push_back({data, response, cycle + 20});
            ++arCount; denied += response != 0;
            peakReads = std::max(peakReads, unsigned(reads.size()));
        } else if (dut.get_io$$axi$$ar$$valid()) ++arStalls;
        if (awFire) {
            check(!acceptedWrites.empty() && dut.get_io$$axi$$aw$$bits$$id() == 0 &&
                  dut.get_io$$axi$$aw$$bits$$len() == 0 &&
                  dut.get_io$$axi$$aw$$bits$$burst() == 1, "AXI write attributes");
            aw.push_back({dut.get_io$$axi$$aw$$bits$$addr(), unsigned(dut.get_io$$axi$$aw$$bits$$size())});
        }
        if (wFire) {
            check(!acceptedWrites.empty() && dut.get_io$$axi$$w$$bits$$last(), "AXI write data attributes");
            w.push_back({dut.get_io$$axi$$w$$bits$$data(), unsigned(dut.get_io$$axi$$w$$bits$$strb())});
        }
        if (awFire != wFire) ++writeSplit;
        while (!aw.empty() && !w.empty()) {
            check(!acceptedWrites.empty() && aw.front().address == acceptedWrites.front().address &&
                  aw.front().size == acceptedWrites.front().size &&
                  w.front().data == acceptedWrites.front().data &&
                  w.front().mask == acceptedWrites.front().mask,
                  "AXI AW/W payload mismatch");
            writeBeat(memory, aw.front().address, w.front().data, w.front().mask);
            b.push_back({0, 0, cycle + 3});
            aw.pop_front(); w.pop_front(); acceptedWrites.pop_front(); ++writeCount;
        }
        if (aFire) {
            check(!sourceBusy[source], "TileLink source reused before D response");
            sourceBusy[source] = true;
            expected.push_back({req.write || req.address >= base + 4096 ? 0 : readBeat(memory, req.address),
                                source, req.size, req.write, !req.write && req.address >= base + 4096});
            if (req.write) {
                acceptedWrites.push_back(req);
                peakWrites = std::max(peakWrites, ++pendingWrites);
            }
            ++issued;
        } else if (valid) ++aStalls;
        if (issued == requestCount && retired == requestCount && expected.empty() && reads.empty() && b.empty() &&
            acceptedWrites.empty() && aw.empty() && w.empty()) break;
    }
    if (writeStream) {
        check(issued == requestCount && retired == requestCount && writeCount == requestCount &&
              arCount == 0 && peakWrites == MAX_WRITES,
              "TileLink-to-AXI write stream did not drain");
        for (unsigned i = 0; i < 8; ++i) {
            check(readBeat(memory, base + 8 * i) == 0x1234000000000000ULL + 248 + i,
                  "TileLink-to-AXI write stream memory mismatch");
        }
        std::cout << "GSIM TileLink-to-AXI4 write stream: PASS writes=" << writeCount
                  << " cycles=" << cycles << " peakWrites=" << peakWrites << '\n';
        return 0;
    }
    check(issued == 105 && retired == 105 && arCount == 96 && writeCount == 9 &&
          denied > 0 && peakReads == 8 && aStalls > 0 && dStalls > 0 &&
          arStalls > 0 && writeSplit > 0 && peakWrites == MAX_WRITES,
          "TileLink-to-AXI coverage or drain missing");
    std::cout << "GSIM TileLink-to-AXI4: PASS requests=" << issued << " reads=" << arCount
              << " writes=" << writeCount << " deniedReads=" << denied
              << " peakAxiReads=" << peakReads << " peakWrites=" << peakWrites << " aStalls=" << aStalls
              << " dStalls=" << dStalls << '\n';
}
