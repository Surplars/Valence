#include "OrderedAxi4Bridge.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>

static constexpr uint64_t base = 0x80010000;
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }

struct Request { uint64_t address, data; unsigned size, mask; bool write; };
struct Reply { uint64_t data; unsigned resp, due; };
struct Expected { uint64_t data; bool error, write; };
struct WriteAddress { uint64_t address; unsigned size; };
struct WriteData { uint64_t data; unsigned mask; };

static Request request(unsigned n) {
    if (n < 8) return {base + 8 * n, 0x1234000000000000ULL + n, 3, 255, true};
    if (n == 88) return {base + 16, 0x0000000011223344ULL, 2, 15, true};
    if (n % 19 == 0) return {base + 4096, 0, 3, 255, false};
    unsigned size = n % 4, bytes = 1U << size;
    unsigned lane = (n / 8) % (8 / bytes) * bytes;
    return {base + 8 * (n % 8) + lane, 0, size, ((1U << bytes) - 1) << lane, false};
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

static void drive(SOrderedAxi4Bridge &dut, const Request &r, bool valid, bool ready,
                  bool arReady, bool awReady, bool wReady, const std::deque<Reply> &reads,
                  const std::deque<Reply> &writes, unsigned cycle, bool injectWriteError = false) {
    dut.set_io$$data$$request$$valid(valid);
    dut.set_io$$data$$request$$bits$$atomic(0);
    dut.set_io$$data$$request$$bits$$atomicOp(0);
    dut.set_io$$data$$request$$bits$$address(r.address);
    dut.set_io$$data$$request$$bits$$write(r.write);
    dut.set_io$$data$$request$$bits$$size(r.size);
    dut.set_io$$data$$request$$bits$$data(r.data);
    dut.set_io$$data$$request$$bits$$mask(r.mask);
    dut.set_io$$data$$response$$ready(ready);
    dut.set_io$$axi$$ar$$ready(arReady);
    dut.set_io$$axi$$aw$$ready(awReady);
    dut.set_io$$axi$$w$$ready(wReady);
    bool rValid = !reads.empty() && reads.front().due <= cycle;
    dut.set_io$$axi$$r$$valid(rValid);
    dut.set_io$$axi$$r$$bits$$id(0);
    dut.set_io$$axi$$r$$bits$$data(rValid ? reads.front().data : 0);
    dut.set_io$$axi$$r$$bits$$resp(rValid ? reads.front().resp : 0);
    dut.set_io$$axi$$r$$bits$$last(1);
    bool bValid = !writes.empty() && writes.front().due <= cycle;
    dut.set_io$$axi$$b$$valid(bValid);
    dut.set_io$$axi$$b$$bits$$id(0);
    dut.set_io$$axi$$b$$bits$$resp(injectWriteError && bValid ? 2 : 0);
}

int main(int argc, char **argv) {
    bool injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    bool injectWriteError = argc == 2 && std::string(argv[1]) == "--inject-write-error";
    SOrderedAxi4Bridge dut;
    std::array<uint8_t, 64> memory{};
    std::deque<Reply> reads;
    std::deque<Expected> expected;
    std::deque<WriteAddress> aw;
    std::deque<WriteData> w;
    std::optional<WriteAddress> heldAr, heldAw;
    std::optional<WriteData> heldW;
    std::deque<Reply> b;
    std::deque<Request> acceptedWrites;
    drive(dut, {}, false, false, false, false, false, reads, b, 0);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned issued = 0, retired = 0, arCount = 0, writeCount = 0, errors = 0, peakReads = 0;
    unsigned arStalls = 0, writeSplit = 0, responseStalls = 0, pendingWrites = 0, peakWrites = 0;
    for (unsigned cycle = 0; cycle < 10000; ++cycle) {
        bool valid = issued < 105, ready = cycle % 5 != 0;
        bool arReady = cycle % 7 != 1, awReady = cycle % 7 != 2, wReady = cycle % 7 != 4;
        Request r = valid ? request(issued) : Request{};
        drive(dut, r, valid, ready, arReady, awReady, wReady, reads, b, cycle, injectWriteError);
        dut.step();

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
        if (dut.get_io$$data$$response$$valid()) {
            check(!expected.empty(), "bridge response without accepted request");
            check(dut.get_io$$data$$response$$bits$$data() == expected.front().data &&
                  bool(dut.get_io$$data$$response$$bits$$error()) == expected.front().error,
                  "bridge response data, error or order mismatch");
            if (ready) {
                if (expected.front().write) --pendingWrites;
                expected.pop_front(); ++retired;
            }
            else ++responseStalls;
        }
        if (rFire) { check(!reads.empty(), "unexpected AXI R handshake"); reads.pop_front(); }
        if (bFire) b.pop_front();
        if (arFire) {
            check(dut.get_io$$axi$$ar$$bits$$id() == 0 && dut.get_io$$axi$$ar$$bits$$len() == 0 &&
                  dut.get_io$$axi$$ar$$bits$$burst() == 1, "AXI read address attributes");
            uint64_t address = dut.get_io$$axi$$ar$$bits$$addr();
            unsigned resp = address >= base + 4096 ? 2 : 0;
            uint64_t data = resp ? 0 : readBeat(memory, address);
            if (injectMismatch && arCount == 0) data ^= 1;
            reads.push_back({data, resp, cycle + 20});
            ++arCount; errors += resp != 0;
            if (reads.size() > peakReads) peakReads = reads.size();
        } else if (dut.get_io$$axi$$ar$$valid()) ++arStalls;
        if (awFire) {
            check(!acceptedWrites.empty() && dut.get_io$$axi$$aw$$bits$$id() == 0 &&
                  dut.get_io$$axi$$aw$$bits$$len() == 0 && dut.get_io$$axi$$aw$$bits$$burst() == 1,
                  "AXI write address attributes");
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
                  "AXI decoupled AW/W payload mismatch");
            writeBeat(memory, aw.front().address, w.front().data, w.front().mask);
            b.push_back({0, 0, cycle + 3});
            aw.pop_front(); w.pop_front(); acceptedWrites.pop_front(); ++writeCount;
        }
        if (valid && dut.get_io$$data$$request$$ready()) {
            if (r.write) {
                acceptedWrites.push_back(r);
                expected.push_back({0, false, true});
                peakWrites = std::max(peakWrites, ++pendingWrites);
            } else {
                bool error = r.address >= base + 4096;
                expected.push_back({error ? 0 : readBeat(memory, r.address), error, false});
            }
            ++issued;
        }
        if (issued == 105 && retired == 105 && reads.empty() && b.empty() &&
            acceptedWrites.empty() && aw.empty() && w.empty()) break;
    }
    check(issued == 105 && retired == 105 && expected.empty(), "AXI bridge failed to drain");
    check(arCount == 96 && writeCount == 9 && errors > 0 && peakReads == 8 && arStalls > 0 &&
          responseStalls > 0 && writeSplit > 0 && peakWrites == 4,
          "AXI bridge throughput/backpressure coverage missing");
    std::cout << "GSIM AXI bridge: PASS requests=" << issued << " reads=" << arCount
              << " writes=" << writeCount << " readErrors=" << errors << " peakReads=" << peakReads
              << " peakWrites=" << peakWrites
              << " arStalls=" << arStalls << " responseStalls=" << responseStalls << '\n';
}
