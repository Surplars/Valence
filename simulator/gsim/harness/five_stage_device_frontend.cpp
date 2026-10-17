#include "I1CoherentDeviceFrontEnd.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>

static void need(bool ok, const char *text) { if (!ok) throw std::runtime_error(text); }
struct Operation { uint64_t address, data, expected = 0; unsigned size, lane; bool write, error; };
struct Reply { uint64_t data, due; bool error; };
static uint64_t word(std::map<uint64_t, uint8_t> &bytes, uint64_t a) {
    uint64_t value = 0;
    for (unsigned i = 0; i < 8; ++i) value |= uint64_t(bytes[(a & ~7ULL) + i]) << (i * 8);
    return value;
}

int main(int argc, char **argv) { try {
    const bool wrong = argc == 2 && std::string(argv[1]) == "--wrong-data";
    SI1CoherentDeviceFrontEnd d;
    std::mt19937_64 rng(0x444556494345ULL);
    std::map<uint64_t, uint8_t> expected, actual;
    std::array<std::optional<Operation>, 2> offers;
    std::array<std::deque<Operation>, 2> owners;
    std::array<unsigned, 2> sent{}, completed{}, peak{};
    std::deque<Reply> replies;
    std::optional<std::array<uint64_t, 5>> heldMemory;
    unsigned errors = 0, stalled = 0, accepted = 0, maxRun = 0, run = 0;
    d.set_reset(1);
    d.set_io$$network$$request$$valid(0); d.set_io$$loader$$request$$valid(0);
    d.set_io$$network$$response$$ready(0); d.set_io$$loader$$response$$ready(0);
    d.set_io$$memory$$request$$ready(0); d.set_io$$memory$$response$$valid(0);
    d.set_io$$memory$$response$$bits$$data(0); d.set_io$$memory$$response$$bits$$error(0);
    d.set_io$$memory$$response$$bits$$pageFault(0); d.step(); d.step(); d.set_reset(0);
    for (uint64_t cycle = 0; cycle < 150000; ++cycle) {
        for (unsigned side = 0; side < 2; ++side) if (!offers[side] && sent[side] < 600 && owners[side].size() < 4) {
            const unsigned n = sent[side], size = n % 4, lane = (n * 3) & (8 - (1U << size));
            const uint64_t address = 0x80210000ULL + side * 0x2000 + (n % 32) * 8 + lane;
            offers[side] = Operation{address, rng(), 0, size, lane, n % 3 != 0, n % 32 == 31};
        }
        std::array<bool, 2> responseReady{cycle > 100 && rng() % 4 != 0, cycle > 140 && rng() % 3 != 0};
#define SEND(PORT, SIDE) \
        { const auto op = offers[SIDE].value_or(Operation{}); \
          d.set_io$$##PORT##$$request$$valid(bool(offers[SIDE])); \
          d.set_io$$##PORT##$$request$$bits$$address(op.address); \
          d.set_io$$##PORT##$$request$$bits$$data(op.data); \
          d.set_io$$##PORT##$$request$$bits$$write(op.write); \
          d.set_io$$##PORT##$$request$$bits$$size(op.size); \
          d.set_io$$##PORT##$$request$$bits$$byteEnable((1U << (1U << op.size)) - 1); \
          d.set_io$$##PORT##$$response$$ready(responseReady[SIDE]); }
        SEND(network, 0) SEND(loader, 1)
#undef SEND
        const bool memoryReady = replies.size() < 8 && rng() % 5 != 0;
        const bool responseValid = !replies.empty() && replies.front().due <= cycle;
        d.set_io$$memory$$request$$ready(memoryReady);
        d.set_io$$memory$$response$$valid(responseValid);
        d.set_io$$memory$$response$$bits$$data(responseValid ? replies.front().data : 0);
        d.set_io$$memory$$response$$bits$$error(responseValid && replies.front().error);
        d.step();
        if (responseValid && d.get_io$$memory$$response$$ready()) replies.pop_front();
#define RECEIVE(PORT, SIDE) \
        if (d.get_io$$##PORT##$$response$$valid() && responseReady[SIDE]) { \
            need(!owners[SIDE].empty(), "device response without an independent owner"); \
            const auto op = owners[SIDE].front(); owners[SIDE].pop_front(); \
            need(bool(d.get_io$$##PORT##$$response$$bits$$error()) == op.error && \
                 d.get_io$$##PORT##$$response$$bits$$data() == op.expected, \
                 "independent device lane/error/order oracle mismatch"); \
            errors += op.error; ++completed[SIDE]; \
        } \
        if (offers[SIDE] && d.get_io$$##PORT##$$request$$ready()) { \
            auto op = *offers[SIDE]; offers[SIDE].reset(); \
            op.expected = op.write || op.error ? 0 : word(expected, op.address) >> (op.lane * 8); \
            if (op.write && !op.error) for (unsigned n = 0; n < (1U << op.size); ++n) \
                expected[op.address + n] = op.data >> (8 * n); \
            if (wrong && SIDE == 0 && sent[SIDE] == 0) op.expected ^= 1; \
            owners[SIDE].push_back(op); ++sent[SIDE]; \
            need(owners[SIDE].size() <= 4, "originating device exceeds its four configured credits"); \
            peak[SIDE] = std::max(peak[SIDE], unsigned(owners[SIDE].size())); \
        }
        RECEIVE(network, 0) RECEIVE(loader, 1)
#undef RECEIVE
        const bool valid = d.get_io$$memory$$request$$valid();
        const std::array<uint64_t, 5> request{d.get_io$$memory$$request$$bits$$address(),
            d.get_io$$memory$$request$$bits$$data(), d.get_io$$memory$$request$$bits$$mask(),
            d.get_io$$memory$$request$$bits$$size(), d.get_io$$memory$$request$$bits$$write()};
        if (heldMemory) need(valid && request == *heldMemory, "native device offer changed under backpressure");
        heldMemory.reset();
        if (valid && !memoryReady) { heldMemory = request; ++stalled; }
        if (valid && memoryReady) {
            const uint64_t a = request[0]; const unsigned size = request[3], lane = a & 7;
            const bool error = ((a >> 3) & 31) == 31;
            need(size <= 3 && !(lane & ((1U << size) - 1)) &&
                 request[2] == (((1U << (1U << size)) - 1) << lane) &&
                 !d.get_io$$memory$$request$$bits$$atomic() &&
                 !d.get_io$$memory$$request$$bits$$virtualized(), "independent device native geometry mismatch");
            const uint64_t value = error || request[4] ? 0 : word(actual, a);
            if (request[4] && !error) for (unsigned n = 0; n < 8; ++n)
                if (request[2] >> n & 1) actual[(a & ~7ULL) + n] = request[1] >> (8 * n);
            replies.push_back({value, cycle + 3 + rng() % 17, error});
            ++accepted; maxRun = std::max(maxRun, ++run);
        } else run = 0;
        if (completed[0] == 600 && completed[1] == 600) {
            need(sent[0] == 600 && sent[1] == 600 && accepted == 1200 && replies.empty() &&
                 owners[0].empty() && owners[1].empty() && peak[0] == 4 && peak[1] == 4 &&
                 errors > 10 && stalled > 20, "device adversarial credit/error/stall coverage missing");
            need(expected == actual, "independent device final byte oracle mismatch");
            std::cout << "I1_DEVICE_FRONTEND_PASS requests=" << accepted << " cycles=" << cycle
                << " errors=" << errors << " stalled=" << stalled << " peak_credits=4,4 max_native_run=" << maxRun
                << " subword_lane_ownership_backpressure_real_ack=PASS\n";
            return 0;
        }
    }
    throw std::runtime_error("device frontend bounded completion failed");
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
