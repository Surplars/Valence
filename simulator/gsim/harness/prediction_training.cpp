#include "PredictionTrainingGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef TRAIN_WIDTH
#define TRAIN_WIDTH 2
#endif
#ifndef COMPRESSED
#define COMPRESSED 1
#endif
#ifndef DELAYED_TRAINING
#define DELAYED_TRAINING 1
#endif
static void check(bool value, const char* message) { if (!value) throw std::runtime_error(message); }
struct Commit {
    bool valid = false, branch = false, indirect = false, taken = false;
    uint64_t pc = 0, next = 0;
    uint32_t instruction = 0x13;
};
using Packet = std::array<Commit, TRAIN_WIDTH>;
static void drive(SPredictionTrainingGsim& d, unsigned lane, const Commit& c, uint64_t pc) {
#define LANE(i) case i: \
    d.set_io$$retired$$lane##i##$$valid(c.valid); \
    d.set_io$$retired$$lane##i##$$bits$$pc(c.pc); \
    d.set_io$$retired$$lane##i##$$bits$$nextPc(c.next); \
    d.set_io$$retired$$lane##i##$$bits$$instruction(c.instruction); \
    d.set_io$$pc$$r##i(pc); break
    switch (lane) {
        LANE(0); LANE(1);
#if TRAIN_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("bad training lane");
    }
#undef LANE
}
struct Answer { bool taken, hit; uint64_t target; };
static Answer read(SPredictionTrainingGsim& d, unsigned lane) {
#define LANE(i) case i: return {bool(d.get_io$$taken$$r##i()), bool(d.get_io$$hit$$r##i()), d.get_io$$target$$r##i()}
    switch (lane) {
        LANE(0); LANE(1);
#if TRAIN_WIDTH == 4
        LANE(2); LANE(3);
#endif
        default: throw std::runtime_error("bad query lane");
    }
#undef LANE
}
int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SPredictionTrainingGsim d;
    std::mt19937_64 rng(0x93156be1);
    std::array<unsigned, 32> counters;
    std::array<bool, 16> hit{};
    std::array<uint64_t, 16> tags{}, targets{};
    Packet pending{};
    const unsigned alignment = COMPRESSED ? 2 : 4;
    unsigned trained = 0, indirect = 0, collisions = 0, cancelled = 0, compressed = 0, wrap = 0;
    auto reset = [&] {
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) drive(d, lane, {}, 0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        counters.fill(1); hit.fill(false); pending = {};
    };
    reset();
    for (unsigned cycle = 0; cycle < 40004; ++cycle) {
        if (cycle == 20000) {
            for (const auto& c : pending) cancelled += c.valid;
            reset();
        }
        Packet offered{};
        std::array<uint64_t, TRAIN_WIDTH> query{};
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) {
            auto& c = offered[lane];
            c.pc = cycle < 300 ? 0x80000000ULL : (rng() & ~uint64_t(alignment - 1));
            if (lane && cycle % 3 == 0) c.pc = offered[0].pc;
            if (cycle % 191 == 0) c.pc = UINT64_MAX - (alignment - 1);
            c.valid = cycle < 40000 && (cycle < 300 || cycle == 19999 || rng() % 5 != 0);
            unsigned kind = cycle < 300 ? 0 : rng() % (COMPRESSED ? 7 : 3);
            unsigned length = 4;
            switch (kind) {
                case 0: c.instruction = 0x63; c.branch = true; break; // BEQ
                case 1: c.instruction = 0x00008067; c.indirect = true; break; // JALR
                case 2: c.instruction = 0x13; break; // ADDI
                case 3: c.instruction = 0xc001; c.branch = true; length = 2; break; // C.BEQZ
                case 4: c.instruction = 0xe001; c.branch = true; length = 2; break; // C.BNEZ
                case 5: c.instruction = 0x8082; c.indirect = true; length = 2; break; // C.JR
                case 6: c.instruction = 0x9082; c.indirect = true; length = 2; break; // C.JALR
            }
            c.taken = (cycle < 150 || (rng() & 1)) && c.branch;
            c.next = c.branch && c.taken ? c.pc - 16 : c.pc + length;
            if (c.indirect) c.next = rng() & ~uint64_t(alignment - 1);
            compressed += c.valid && length == 2;
            wrap += c.valid && !c.taken && !c.indirect && c.next < c.pc;
            query[lane] = cycle % 5 == 0 && pending[lane].valid ? pending[lane].pc : c.pc;
            if (cycle % 7 == 0) query[lane] = tags[(c.pc / alignment) % 16];
            drive(d, lane, c, query[lane]);
        }
        d.step();
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) {
            const auto actual = read(d, lane);
            const unsigned index = (query[lane] / alignment) % 32;
            const unsigned targetIndex = (query[lane] / alignment) % 16;
            const bool expectedTaken = counters[index] >= 2;
            const bool expectedHit = hit[targetIndex] && tags[targetIndex] == query[lane];
            const bool observed = actual.taken ^ (inject && cycle == 300 && lane == 0);
            if (observed != expectedTaken || actual.hit != expectedHit ||
                (expectedHit && actual.target != targets[targetIndex])) {
                std::cerr << "cycle=" << cycle << " lane=" << lane << " pc=" << std::hex << query[lane]
                    << std::dec << " expected_taken=" << expectedTaken << " actual_taken=" << observed << '\n';
                throw std::runtime_error("prediction training oracle mismatch");
            }
        }
        // Independent ordered event model: staged packets train exactly one cycle later.
        const Packet applying = DELAYED_TRAINING ? pending : offered;
        for (unsigned lane = 0; lane < TRAIN_WIDTH; ++lane) {
            const auto& c = applying[lane];
            if (!c.valid) continue;
            const unsigned index = (c.pc / alignment) % 32;
            if (c.branch) {
                if (c.taken && counters[index] < 3) ++counters[index];
                if (!c.taken && counters[index] > 0) --counters[index];
                ++trained;
                for (unsigned older = 0; older < lane; ++older)
                    collisions += applying[older].valid && applying[older].branch &&
                        (applying[older].pc / alignment) % 32 == index;
            }
            if (c.indirect) {
                const unsigned ti = (c.pc / alignment) % 16;
                hit[ti] = true; tags[ti] = c.pc; targets[ti] = c.next; ++indirect;
            }
        }
        pending = offered;
    }
    check(trained > 10000 && indirect > 10000 && collisions > 1000 && wrap > 20,
        "prediction training coverage too small");
    if (COMPRESSED) check(compressed > 10000, "compressed predictor training untested");
    if (DELAYED_TRAINING) check(cancelled > 0, "pending training reset not tested");
    std::cout << "GSIM prediction training: PASS width=" << TRAIN_WIDTH << " delayed=" << DELAYED_TRAINING
        << " branches=" << trained << " indirect=" << indirect << " collisions=" << collisions
        << " compressed=" << compressed << " wrapped=" << wrap << " resetCancelled=" << cancelled << '\n';
    return 0;
} catch (const std::exception& error) { std::cerr << "GSIM prediction training: " << error.what() << '\n'; return 1; } }
