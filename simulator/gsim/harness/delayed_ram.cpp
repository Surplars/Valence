#include "SynchronousDataRam.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>

static constexpr uint64_t base = 0x80010000;
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }

struct Request { uint64_t address, data; bool write; };
struct Reply { uint64_t data; bool error; };

static Request request(unsigned index) {
    if (index < 8) return {base + 8 * index, 0x1234000000000000ULL + index, true};
    if (index % 13 == 0) return {base + 4096, 0, false};
    if (index % 11 == 0) return {base + 8 * (index % 8), 0x5678000000000000ULL + index, true};
    return {base + 8 * (index % 8), 0, false};
}

static Reply access(std::array<uint64_t, 8> &memory, const Request &r) {
    if (r.address == base + 4096) return {0, true};
    auto &word = memory[(r.address - base) / 8];
    if (r.write) { word = r.data; return {0, false}; }
    return {word, false};
}

static void drive(SSynchronousDataRam &dut, const Request &r, bool valid, bool ready) {
    dut.set_io$$port$$request$$valid(valid);
    dut.set_io$$port$$request$$bits$$address(r.address);
    dut.set_io$$port$$request$$bits$$data(r.data);
    dut.set_io$$port$$request$$bits$$write(r.write);
    dut.set_io$$port$$request$$bits$$size(3);
    dut.set_io$$port$$request$$bits$$mask(255);
    dut.set_io$$port$$request$$bits$$atomic(0);
    dut.set_io$$port$$request$$bits$$atomicOp(0);
    dut.set_io$$port$$response$$ready(ready);
}

int main() {
    SSynchronousDataRam dut;
    drive(dut, {}, false, false);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    std::array<uint64_t, 8> memory{};
    std::deque<Reply> expected;
    unsigned issued = 0, received = 0, requestStalls = 0, responseStalls = 0, errors = 0, peak = 0;
    for (unsigned cycle = 0; cycle < 4000; ++cycle) {
        bool valid = issued < 96;
        bool ready = cycle >= 24 && cycle % 3 != 0;
        Request r = valid ? request(issued) : Request{};
        drive(dut, r, valid, ready);
        dut.step();
        if (dut.get_io$$port$$response$$valid()) {
            check(!expected.empty(), "response without an accepted request");
            check(dut.get_io$$port$$response$$bits$$data() == expected.front().data &&
                  bool(dut.get_io$$port$$response$$bits$$error()) == expected.front().error,
                  "delayed response data, error or order mismatch");
            if (ready) { expected.pop_front(); ++received; }
            else ++responseStalls;
        }
        if (valid && dut.get_io$$port$$request$$ready()) {
            auto reply = access(memory, r);
            errors += reply.error;
            expected.push_back(reply);
            ++issued;
            if (expected.size() > peak) peak = expected.size();
        } else if (valid) ++requestStalls;
        if (issued == 96 && received == 96 && !dut.get_io$$busy()) break;
    }
    check(issued == 96 && received == 96 && expected.empty(), "delayed RAM failed to drain");
    check(errors > 0 && requestStalls > 0 && responseStalls > 0 && peak >= 3,
          "delayed RAM backpressure coverage missing");
    std::cout << "GSIM delayed RAM: PASS requests=" << issued << " errors=" << errors
              << " requestStalls=" << requestStalls << " responseStalls=" << responseStalls
              << " peakOutstanding=" << peak << '\n';
}
