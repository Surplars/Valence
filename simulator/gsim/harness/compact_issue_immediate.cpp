#include "BankedIssuePayloadGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

using Payload = std::array<uint64_t, 6>;
struct Write { bool valid = false; unsigned index = 0; Payload data{}; };
struct Read { bool enable = false; unsigned index = 0; };
static constexpr std::array<unsigned, 8> masks = {7, 16, 16, 1, 1, 59, 59, 1};
static void check(bool ok, const char* text) { if (!ok) throw std::runtime_error(text); }
static void write(SBankedIssuePayloadGsim& d, unsigned lane, const Write& w) {
#define LANE(N) case N: \
 d.set_io$$write$$lane##N##$$valid(w.valid); \
 d.set_io$$write$$lane##N##$$bits$$index(w.index); \
 d.set_io$$write$$lane##N##$$bits$$data$$pc(w.data[0]); \
 d.set_io$$write$$lane##N##$$bits$$data$$instruction(w.data[1]); \
 d.set_io$$write$$lane##N##$$bits$$data$$expandedInstruction(w.data[2]); \
 d.set_io$$write$$lane##N##$$bits$$data$$predictedNextPc(w.data[3]); \
 d.set_io$$write$$lane##N##$$bits$$data$$immediate(w.data[4]); \
 d.set_io$$write$$lane##N##$$bits$$data$$fetchTval(w.data[5]); break
    switch (lane) { LANE(0); LANE(1); default: throw std::runtime_error("bad write lane"); }
#undef LANE
}
static void address(SBankedIssuePayloadGsim& d, unsigned lane, const Read& r) {
#define LANE(N) case N: d.set_io$$address$$lane##N##$$index(r.index); \
 d.set_io$$address$$lane##N##$$enable(r.enable); break
    switch (lane) { LANE(0); LANE(1); LANE(2); LANE(3); LANE(4); LANE(5); LANE(6); LANE(7); }
#undef LANE
}
static Payload data(SBankedIssuePayloadGsim& d, unsigned lane) {
#define LANE(N) case N: return {d.get_io$$data$$lane##N##$$pc(), \
 d.get_io$$data$$lane##N##$$instruction(), d.get_io$$data$$lane##N##$$expandedInstruction(), \
 d.get_io$$data$$lane##N##$$predictedNextPc(), d.get_io$$data$$lane##N##$$immediate(), \
 d.get_io$$data$$lane##N##$$fetchTval()}
    switch (lane) { LANE(0); LANE(1); LANE(2); LANE(3); LANE(4); LANE(5); LANE(6); LANE(7); }
#undef LANE
    throw std::runtime_error("bad read lane");
}
int main(int argc, char** argv) { try {
    const bool arbitrary = argc > 1 && std::string_view(argv[1]) == "--arbitrary64";
    const bool invalid = argc > 1 && std::string_view(argv[1]) == "--inject-noncanonical-immediate";
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-payload-mismatch";
    const bool collision = argc > 1 && std::string_view(argv[1]) == "--inject-bank-collision";
    SBankedIssuePayloadGsim d;
    std::array<Payload, 16> memory{};
    std::array<bool, 16> initialized{};
    std::mt19937_64 random(0x954a2329837ULL);
    for (unsigned lane = 0; lane < 2; ++lane) write(d, lane, {});
    for (unsigned port = 0; port < 8; ++port) address(d, port, {});
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    unsigned reads = 0, writes = 0, dualWrites = 0, wrapPairs = 0, readWriteCollisions = 0, invalidReads = 0;
    // Independent software values: do not truncate/sign-extend observed DUT data.
    const std::array<uint64_t, 8> signedValues = {0, 1, UINT64_MAX, 0x7fffffffULL,
        0xffffffff80000000ULL, 0xffffffff80000001ULL, 0x7ffffffeULL, 0xfffffffffffff800ULL};
    std::array<unsigned, 2> extremeBanks{};
    std::array<unsigned, 2> observedExtremeMasks{};
    unsigned retainedReads = 0, resetReads = 0;
    for (unsigned cycle = 0; cycle < 16000; ++cycle) {
        std::array<Write, 2> w{};
        std::array<Read, 8> r{};
        const unsigned first = cycle < 16 ? cycle : random() % 16;
        w[0].valid = cycle < 16 || random() % 4 != 0;
        w[0].index = first;
        w[1].valid = cycle < 16 || random() % 3 != 0;
        w[1].index = (first + 1) % 16;
        if (collision && cycle == 40) { w[0].valid = w[1].valid = true; w[1].index = first ^ 2; }
        const bool retain = cycle >= 8000 && cycle < 8064;
        if (retain || (cycle >= 16 && cycle < 32)) w[0].valid = w[1].valid = false;
        d.set_reset(cycle == 8020 || cycle == 8021);
        unsigned laneIndex = 0;
        for (auto& port : w) {
            for (auto& value : port.data) value = random();
            port.data[1] &= UINT32_MAX; port.data[2] &= UINT32_MAX;
            if (!arbitrary) {
                const uint32_t raw = static_cast<uint32_t>(random());
                // Arithmetic oracle independent of the Chisel concatenation implementation.
                port.data[4] = raw < 0x80000000U ? uint64_t(raw) : uint64_t(raw) - (uint64_t(1) << 32);
                if (cycle < 16) port.data[4] = signedValues[(cycle / 2 + laneIndex) % signedValues.size()];
                if (port.valid && (port.data[4] == 0x7fffffffULL || port.data[4] == 0xffffffff80000000ULL))
                    ++extremeBanks[port.index & 1];
                // Invalid bits on inactive lanes must never trip the write assertion.
                if (!port.valid) port.data[4] = 0x0123456789abcdefULL;
            }
            ++laneIndex;
            writes += port.valid;
        }
        if (invalid && cycle == 40) {
            w[0].valid = true;
            w[0].data[4] = 0x0000000080000000ULL;
        }
        dualWrites += w[0].valid && w[1].valid;
        wrapPairs += w[0].valid && w[1].valid && first == 15;
        for (unsigned port = 0; port < 8; ++port) {
            r[port].index = port < 2 ? w[port].index : random() % 16;
            r[port].enable = initialized[r[port].index] && random() % 7 != 0;
            if (cycle >= 16 && cycle < 32) {
                r[port].index = cycle - 16;
                r[port].enable = true;
                if (cycle == 24 && port == 2) r[port].enable = false;
            }
            address(d, port, r[port]);
            readWriteCollisions += r[port].enable && ((w[0].valid && r[port].index == w[0].index) ||
                (w[1].valid && r[port].index == w[1].index));
        }
        for (unsigned lane = 0; lane < 2; ++lane) write(d, lane, w[lane]);
        d.step();
        for (unsigned port = 0; port < 8; ++port) {
            auto actual = data(d, port);
            if (inject && cycle == 100 && port == 5) actual[5] ^= 1;
            for (unsigned field = 0; field < 6; ++field) {
                const uint64_t expected = r[port].enable && (masks[port] & (1U << field)) ?
                    memory[r[port].index][field] : 0;
                check(actual[field] == expected, "immutable issue payload oracle mismatch");
                if (field == 4 && r[port].enable && (masks[port] & (1U << field))) {
                    if (expected == 0x7fffffffULL) observedExtremeMasks[r[port].index & 1] |= 1;
                    if (expected == 0xffffffff80000000ULL) observedExtremeMasks[r[port].index & 1] |= 2;
                }
            }
            retainedReads += retain && r[port].enable;
            resetReads += (cycle == 8020 || cycle == 8021) && r[port].enable;
            reads += r[port].enable; invalidReads += !r[port].enable;
        }
        for (const auto& port : w) if (port.valid) {
            memory[port.index] = port.data; initialized[port.index] = true;
        }
    }
    check(reads > 80000 && dualWrites > 6000 && wrapPairs > 300 && readWriteCollisions > 20000 &&
        invalidReads > 10000, "missing issue RAM read/write/invalid coverage");
    check(retainedReads > 300 && resetReads > 0, "missing retained rows across reset coverage");
    check(arbitrary || (extremeBanks[0] > 0 && extremeBanks[1] > 0), "missing signed extrema in both banks");
    check(arbitrary || (observedExtremeMasks[0] == 3 && observedExtremeMasks[1] == 3),
        "missing readback of signed extrema in both banks");
    std::cout << "GSIM compact issue immediate: PASS cycles=16000 reads=" << reads << " writes=" << writes
        << " dualWrites=" << dualWrites << " wrapPairs=" << wrapPairs
        << " retainedReads=" << retainedReads << " resetReads=" << resetReads
        << " readWriteCollisions=" << readWriteCollisions << " invalidReads=" << invalidReads << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << "GSIM immutable issue payload: " << e.what() << '\n'; return 1; } }
