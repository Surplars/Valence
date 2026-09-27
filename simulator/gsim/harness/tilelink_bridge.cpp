#include "OrderedTileLinkBridge.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr uint64_t base = 0x80010000;
#ifdef ALLOW_WRITE_ERRORS
static constexpr unsigned requestCount = 106;
#else
static constexpr unsigned requestCount = 105;
#endif
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }

struct Request { uint64_t address, data; unsigned size, mask; bool write; };
struct Expected { uint64_t data; bool error; unsigned source; bool write; };
struct Reply { uint64_t data; unsigned source, size, opcode, due, sequence; bool denied, corrupt; };

static Request request(unsigned n) {
#ifdef ALLOW_WRITE_ERRORS
    if (n == 105) return {base + 4096, 0xdeadbeef, 3, 255, true};
#endif
    if (n < 8) {
#ifdef BANKED_WRITES
        return {base + 8 * n + (n >= 4 ? 2048 : 0), 0x1234000000000000ULL + n, 3, 255, true};
#else
        return {base + 8 * n, 0x1234000000000000ULL + n, 3, 255, true};
#endif
    }
    if (n == 88) return {base + 16, 0x0000000011223344ULL, 2, 15, true};
    if (n % 19 == 0) return {base + 4096, 0, 3, 255, false};
    unsigned size = n % 4, bytes = 1U << size;
    unsigned lane = (n / 8) % (8 / bytes) * bytes;
    return {base + 8 * (n % 8) + lane, 0, size, ((1U << bytes) - 1) << lane, false};
}

static uint64_t readBeat(const std::array<uint8_t, 4096> &memory, uint64_t address) {
    unsigned offset = (address - base) & ~7U;
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= uint64_t(memory[offset + i]) << (8 * i);
    return value;
}

static void writeBeat(std::array<uint8_t, 4096> &memory, uint64_t address, uint64_t data, unsigned mask) {
    unsigned offset = (address - base) & ~7U;
    for (unsigned i = 0; i < 8; ++i) if (mask & (1U << i)) memory[offset + i] = data >> (8 * i);
}

static void drive(SOrderedTileLinkBridge &dut, const Request &r, bool valid, bool responseReady,
                  bool aReady, const std::optional<Reply> &offered) {
    dut.set_io$$data$$request$$valid(valid);
    dut.set_io$$data$$request$$bits$$atomic(0);
    dut.set_io$$data$$request$$bits$$atomicOp(0);
    dut.set_io$$data$$request$$bits$$address(r.address);
    dut.set_io$$data$$request$$bits$$write(r.write);
    dut.set_io$$data$$request$$bits$$size(r.size);
    dut.set_io$$data$$request$$bits$$data(r.data);
    dut.set_io$$data$$request$$bits$$mask(r.mask);
    dut.set_io$$data$$response$$ready(responseReady);
    dut.set_io$$tl$$a$$ready(aReady);
    dut.set_io$$tl$$d$$valid(bool(offered));
    dut.set_io$$tl$$d$$bits$$source(offered ? offered->source : 0);
    dut.set_io$$tl$$d$$bits$$opcode(offered ? offered->opcode : 0);
    dut.set_io$$tl$$d$$bits$$param(0);
    dut.set_io$$tl$$d$$bits$$size(offered ? offered->size : 0);
    dut.set_io$$tl$$d$$bits$$sink(0);
    dut.set_io$$tl$$d$$bits$$denied(offered && offered->denied);
    dut.set_io$$tl$$d$$bits$$data(offered ? offered->data : 0);
    dut.set_io$$tl$$d$$bits$$corrupt(offered && offered->corrupt);
    dut.set_io$$tl$$b$$valid(0);
    dut.set_io$$tl$$b$$bits$$opcode(0);
    dut.set_io$$tl$$b$$bits$$param(0);
    dut.set_io$$tl$$b$$bits$$size(0);
    dut.set_io$$tl$$b$$bits$$source(0);
    dut.set_io$$tl$$b$$bits$$address(0);
    dut.set_io$$tl$$b$$bits$$mask(0);
    dut.set_io$$tl$$b$$bits$$data(0);
    dut.set_io$$tl$$b$$bits$$corrupt(0);
    dut.set_io$$tl$$c$$ready(1);
    dut.set_io$$tl$$e$$ready(1);
}

static void sourceStabilityTest() {
    SOrderedTileLinkBridge dut;
    drive(dut, {}, false, false, false, {});
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    for (unsigned i = 0; i < 3; ++i) {
        drive(dut, {base + 8 * i, 0, 3, 255, false}, true, false, true, {});
        dut.step();
    }
    Reply first{100, 0, 3, 1, 0, 0, false, false};
    drive(dut, {}, false, false, true, first); dut.step();
    const Request stalled{base + 128, 0, 3, 255, false};
    drive(dut, stalled, true, false, false, {}); dut.step();
    check(dut.get_io$$tl$$a$$valid() && dut.get_io$$tl$$a$$bits$$source() == 3,
          "stalled request did not choose the available source");
    drive(dut, stalled, true, true, false, {}); dut.step();
    check(dut.get_io$$tl$$a$$valid() && dut.get_io$$tl$$a$$bits$$source() == 3,
          "TileLink A source changed while a lower source was released");
    drive(dut, stalled, true, false, true, {}); dut.step();
    check(dut.get_io$$tl$$a$$valid() && dut.get_io$$tl$$a$$bits$$source() == 3 &&
          dut.get_io$$data$$request$$ready(), "TileLink A source changed under backpressure");
    std::cout << "GSIM TileLink bridge source stability: PASS lowerSourceReleasedDuringAStall\n";
}

int main(int argc, char **argv) {
    bool injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    SOrderedTileLinkBridge dut;
    std::array<uint8_t, 4096> memory{};
    std::deque<Expected> expected;
    std::vector<Reply> pending;
    std::optional<Reply> offered;
    std::optional<Request> heldA;
    std::optional<unsigned> heldSource;
    drive(dut, {}, false, false, false, offered);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    unsigned issued = 0, retired = 0, reads = 0, writes = 0, errors = 0, peak = 0;
    unsigned writeInFlight = 0, peakWrites = 0, activeWriteBank = 0;
    unsigned aStalls = 0, responseStalls = 0, outOfOrder = 0, maxReturnedSequence = 0;
    unsigned flowedResponses = 0;
    bool mixedInFlight = false;
    unsigned completedCycles = 0;
    for (unsigned cycle = 0; cycle < 10000; ++cycle) {
        if (!offered) {
            int selected = -1;
            for (unsigned i = 0; i < pending.size(); ++i) {
                if (pending[i].due <= cycle &&
                    (selected < 0 || pending[i].source > pending[selected].source)) selected = i;
            }
            if (selected >= 0) {
                offered = pending[selected];
                pending.erase(pending.begin() + selected);
            }
        }
        bool valid = issued < requestCount, aReady = cycle % 7 != 1, responseReady = cycle % 5 != 0;
        Request r = valid ? request(issued) : Request{};
        drive(dut, r, valid, responseReady, aReady, offered);
        dut.step();
        bool aFire = dut.get_io$$tl$$a$$valid() && aReady;
        bool dFire = offered && dut.get_io$$tl$$d$$ready();
        if (dFire && !expected.empty() && offered->source == expected.front().source &&
            dut.get_io$$data$$response$$valid()) ++flowedResponses;
        if (heldA) {
            check(dut.get_io$$tl$$a$$valid() && dut.get_io$$tl$$a$$bits$$address() == heldA->address &&
                  dut.get_io$$tl$$a$$bits$$size() == heldA->size &&
                  dut.get_io$$tl$$a$$bits$$mask() == heldA->mask &&
                  dut.get_io$$tl$$a$$bits$$source() == *heldSource,
                  "TileLink A changed under backpressure");
        }
        heldA = dut.get_io$$tl$$a$$valid() && !aReady ? std::optional<Request>{r} : std::nullopt;
        heldSource = heldA ? std::optional<unsigned>{unsigned(dut.get_io$$tl$$a$$bits$$source())} : std::nullopt;
        if (dut.get_io$$data$$response$$valid()) {
            check(!expected.empty(), "TileLink bridge response without request");
            check(dut.get_io$$data$$response$$bits$$data() == expected.front().data &&
                  bool(dut.get_io$$data$$response$$bits$$error()) == expected.front().error,
                  "TileLink bridge response data, error or order mismatch");
            if (responseReady) {
                if (expected.front().write) --writeInFlight;
                expected.pop_front(); ++retired;
            }
            else ++responseStalls;
        }
        if (dFire) {
            if (offered->sequence < maxReturnedSequence) ++outOfOrder;
            if (offered->sequence > maxReturnedSequence) maxReturnedSequence = offered->sequence;
            offered.reset();
        }
        if (aFire) {
            unsigned source = dut.get_io$$tl$$a$$bits$$source();
            uint64_t address = dut.get_io$$tl$$a$$bits$$address();
            bool write = dut.get_io$$tl$$a$$bits$$opcode() == 1;
            check(source < 8 && address == r.address && dut.get_io$$tl$$a$$bits$$size() == r.size &&
                  dut.get_io$$tl$$a$$bits$$mask() == r.mask && write == r.write,
                  "TileLink A request encoding mismatch");
            bool denied = address >= base + 4096;
            bool corrupt = !write && !denied && issued % 23 == 0;
            uint64_t data = denied || write ? 0 : readBeat(memory, address);
            if (write) {
#ifdef BANKED_WRITES
                unsigned bank = address >= base + 2048 && address < base + 4096 ? 1U : 0U;
                if (writeInFlight) check(bank == activeWriteBank,
                                         "banked TileLink writes crossed domains before drain");
                else activeWriteBank = bank;
#endif
                if (!denied) writeBeat(memory, address, dut.get_io$$tl$$a$$bits$$data(), r.mask);
                ++writes;
                ++writeInFlight;
                if (writeInFlight > peakWrites) peakWrites = writeInFlight;
            } else { ++reads; errors += denied || corrupt; }
            if (injectMismatch && !write && reads == 1) data ^= 1;
            pending.push_back({data, source, r.size, write ? 0U : 1U,
                               cycle + (write ? 4U : source == 0 ? 28U : 3U + source % 3), issued,
                               denied, corrupt});
            expected.push_back({denied || write ? 0 : readBeat(memory, address), denied || corrupt, source, write});
            bool hasRead = false, hasWrite = false;
            for (const auto &entry : expected) {
                hasRead |= !entry.write;
                hasWrite |= entry.write;
            }
            mixedInFlight |= hasRead && hasWrite;
            ++issued;
            if (expected.size() > peak) peak = expected.size();
        } else if (dut.get_io$$tl$$a$$valid()) ++aStalls;
        if (valid && dut.get_io$$data$$request$$ready()) check(aFire, "DataPort request without TileLink A");
        if (issued == requestCount && retired == requestCount && pending.empty() && !offered) {
            completedCycles = cycle + 1;
            break;
        }
    }
    check(issued == requestCount && retired == requestCount && expected.empty(), "TileLink bridge failed to drain");
    check(reads == 96 && writes == requestCount - 96 && errors > 0 && peak == 8 && outOfOrder > 0 &&
          aStalls > 0 && responseStalls > 0, "TileLink bridge coverage missing");
#ifdef FLOW_HEAD_RESPONSE
    check(flowedResponses > 0, "head response bypass was not exercised");
#endif
#ifdef ORDERED_WRITES
    check(peakWrites > 1, "ordered-write bridge did not pipeline writes");
#ifdef MIXED_ACCESSES
    check(mixedInFlight, "ordered RAM bridge did not overlap read and write responses");
#endif
#elif defined(BANKED_WRITES)
    check(peakWrites > 1, "banked-write bridge did not pipeline same-bank writes");
#else
    check(peakWrites == 1, "generic TileLink bridge did not serialize writes");
#endif
    std::cout << "GSIM TileLink bridge: PASS requests=" << issued << " reads=" << reads
              << " writes=" << writes << " readErrors=" << errors << " peakOutstanding=" << peak
              << " peakWrites=" << peakWrites << " outOfOrderD=" << outOfOrder << " aStalls=" << aStalls
              << " responseStalls=" << responseStalls << " mixedInFlight=" << mixedInFlight
              << " flowedResponses=" << flowedResponses
              << " cycles=" << completedCycles << '\n';
    if (!injectMismatch) sourceStabilityTest();
}
