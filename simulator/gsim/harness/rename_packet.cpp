#include "IntegerCoreGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string_view>
#include <vector>

static constexpr uint64_t base = 0x80000000ULL;
struct Expected { uint64_t pc; unsigned rd; uint64_t data; };
static uint32_t jal(unsigned rd, unsigned offset) {
    return ((offset >> 20 & 1) << 31) | ((offset >> 1 & 1023) << 21) |
           ((offset >> 11 & 1) << 20) | ((offset >> 12 & 255) << 12) | rd << 7 | 0x6f;
}
static uint32_t cli(unsigned value) { return 0x4401 | value << 2; }
static uint32_t caddi(unsigned value) { return 0x0401 | value << 2; }
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    unsigned total = 0, stalled = 0, returns = 0, redirects = 0;
    for (unsigned variant = 0; variant < 4; ++variant) for (unsigned seed = 0; seed < 5; ++seed) {
        SIntegerCoreGsim d; std::mt19937_64 rng(1234 + seed);
        std::map<uint64_t, uint32_t> program;
        std::vector<Expected> trace;
        auto put = [&](unsigned offset, uint32_t instruction) { program[base + offset] = instruction; };
        const unsigned initial = variant == 0 ? 7 : variant == 1 ? 3 : variant == 2 ? 5 : 2;
        put(0, cli(initial)); trace.push_back({base, 8, initial});
        unsigned continuation = 6, target = 0x40;
        if (variant == 0 || variant == 2) {
            const unsigned link = variant == 0 ? 1 : 5;
            put(2, jal(link, target - 2)); trace.push_back({base + 2, link, base + continuation});
        } else {
            put(2, 0x00001497); trace.push_back({base + 2, 9, base + 0x1002}); // AUIPC x9,1
            if (variant == 1) {
                put(6, 0x9482); continuation = 8; target = 0x1002; // C.JALR x9
            } else {
                put(6, 0x040480e7); continuation = 10; target = 0x1042; // JALR x1,x9,64
            }
            trace.push_back({base + 6, 1, base + continuation});
        }
        put(target, caddi(1)); trace.push_back({base + target, 8, initial + 1});
        put(target + 2, variant == 2 ? 0x00028067 : 0x8082); // JALR x0,x5 / C.JR x1
        trace.push_back({base + target + 2, 0, 0});
        put(continuation, caddi(2)); trace.push_back({base + continuation, 8, initial + 3});
        const uint64_t terminal = base + continuation + 2;
        auto word = [&](uint64_t pc) { auto it = program.find(pc); return it == program.end() ? 0U : it->second; };
        d.set_io$$instruction0$$valid(0); d.set_io$$instruction1$$valid(0);
        d.set_io$$decodeInstruction(0); d.set_io$$decodePc(base); d.set_io$$inspectRegister(8);
        d.set_io$$memory$$request$$ready(1); d.set_io$$memory$$response$$valid(0);
        d.set_io$$memory$$response$$bits$$data(0); d.set_io$$memory$$response$$bits$$error(0);
        d.set_io$$memory$$response$$bits$$pageFault(0); d.set_io$$commitEnable(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        unsigned committed = 0; bool done = false;
        auto observe = [&] {
            auto check = [&](bool v, uint64_t at, unsigned instruction, bool writes, unsigned rd, uint64_t data) {
                if (!v) return;
                if (committed >= trace.size()) throw std::runtime_error("prediction committed past precise terminal");
                const auto &e = trace[committed++];
                unsigned expectedInstruction = word(e.pc);
                if (inject && writes) data ^= 1;
                bool sameInstruction = (expectedInstruction & 3) == 3 ? instruction == expectedInstruction :
                    (instruction & 65535) == expectedInstruction;
                if (at != e.pc || !sameInstruction || writes != bool(e.rd) ||
                    (e.rd && (rd != e.rd || data != e.data)))
                    throw std::runtime_error("prediction packet architectural oracle mismatch");
                returns += !e.rd; ++total;
            };
#define CHECK(N) check(d.get_io$$commit##N##$$valid(), d.get_io$$commit##N##$$bits$$pc(), \
                d.get_io$$commit##N##$$bits$$instruction(), d.get_io$$commit##N##$$bits$$writesRd(), \
                d.get_io$$commit##N##$$bits$$rd(), d.get_io$$commit##N##$$bits$$data())
            CHECK(0); CHECK(1);
#undef CHECK
            redirects += bool(d.get_io$$redirect$$valid());
            if (d.get_io$$exception$$valid()) {
                if (committed != trace.size() || d.get_io$$exception$$bits$$pc() != terminal ||
                    d.get_io$$exception$$bits$$cause() != 2 || d.get_io$$committedValue() != initial + 3)
                    throw std::runtime_error("prediction precise exception/final register mismatch");
                done = true;
            }
        };
        for (unsigned cycle = 0; cycle < 2000; ++cycle) {
            bool valid = seed == 0 || rng() % 3 != 0;
            bool second = valid && (seed == 0 || rng() % 4 != 0);
            bool enable = seed == 0 || rng() % 4 != 0;
            // An explicit empty-supply cycle observes current PC via public IO.
            // PC cannot advance from acceptance on this cycle; a backend redirect
            // supplies its new PC explicitly. Observe every commit on both steps.
            // These cycles are deliberately NOT an IPC or board performance test.
            d.set_io$$instruction0$$valid(0); d.set_io$$instruction1$$valid(0);
            d.set_io$$commitEnable(enable); d.step(); observe(); if (done) break;
            uint64_t pc = d.get_io$$redirect$$valid() ? d.get_io$$redirect$$bits$$target() : d.get_io$$fetchPc();
            unsigned a = word(pc), b = word(pc + ((a & 3) == 3 ? 4 : 2));
            d.set_io$$instruction0$$valid(valid); d.set_io$$instruction0$$bits(a);
            d.set_io$$instruction1$$valid(second); d.set_io$$instruction1$$bits(b);
            d.step(); observe(); stalled += !valid || !enable; if (done) break;
        }
        if (!done) throw std::runtime_error("prediction packet timeout");
    }
    if (!stalled || !returns || !redirects) throw std::runtime_error("prediction packet coverage incomplete");
    std::cout << "GSIM prediction packets: PASS programs=20 commits=" << total << " returns=" << returns
              << " stalled_cycles=" << stalled << " redirects=" << redirects
              << " compressed_calls=5 compressed_returns=15 auipc_jalr=10 precise_terminal=20\n";
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
