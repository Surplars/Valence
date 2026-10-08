// The build runner derives this header from the existing independent deque oracle.
// Its only edits observe/mutate sampled DUT outputs for negative controls.
#define main inherited_ledger_main
#include "backend_qualification_adapter.h"
#undef main

static std::string mutation;
static bool mutationFired = false;
static void mutateObservation(Output &out, const Input &in) {
    if (mutationFired || mutation.empty()) return;
    if (mutation == "completion-owner" && in.complete[0].valid && !out.completed[0]) {
        out.completed[0] = true; mutationFired = true;
    } else if (mutation == "high-tag-completion" && in.complete[0].valid &&
            (in.complete[0].token.tag >> 32) && !out.completed[0]) {
        out.completed[0] = true; mutationFired = true;
    } else if (mutation == "source" && out.allocated[1].valid) {
        out.allocated[1].source1 ^= 1; mutationFired = true;
    } else if (mutation == "retire-prefix" && !out.retired[0].valid && !out.retired[1].valid && in.commit) {
        out.retired[1].valid = true; mutationFired = true;
    } else if (out.retired[0].valid) {
        if (mutation == "pc") out.retired[0].pc ^= UINT64_C(1) << 63;
        else if (mutation == "instruction") out.retired[0].instruction ^= UINT32_C(1) << 31;
        else if (mutation == "data") out.retired[0].data ^= UINT64_C(1) << 63;
        else if (mutation == "token") out.retired[0].token.tag ^= UINT64_C(1) << 63;
        else return;
        mutationFired = true;
    }
}
static bool observeRecovery(bool value, const Input &in) {
    if (mutation == "recovery-owner" && !mutationFired && in.recover && (in.boundary.tag >> 32) && !value) {
        mutationFired = true; return true;
    }
    return value;
}
static bool observeHeadException(bool value) {
    if (mutation == "exception" && !mutationFired && value) {
        mutationFired = true; return false;
    }
    return value;
}
static void demand(bool value, const char *message) {
    if (!value) throw std::runtime_error(message);
}
static Request payloadRequest(uint64_t serial, unsigned rd = 0) {
    auto r = request(rd, (serial >> 2) & 31, (serial >> 7) & 31, rd != 0);
    r.pc = (UINT64_C(0x9b137acf4e205600) ^ (serial * UINT64_C(0x100000004))) & ~UINT64_C(1);
    // Opaque independent allocation payload with non-system opcode; ledger does not decode ISA here.
    r.instruction = (uint32_t(serial * UINT64_C(0x459ad31)) & ~UINT32_C(127)) | 0x13;
    return r;
}
struct Witness {
    unsigned tagBitRejects = 0, recoveryBitRejects = 0, simultaneous = 0;
    unsigned indexWraps = 0, reuseRejects = 0, flushes = 0, partialRetires = 0;
    unsigned heldPayloadCycles = 0, fullBackpressure = 0, exceptionHolds = 0;
    unsigned recoveryPriority = 0, resetWithOwners = 0, partialAllocation = 0;
    unsigned pairAtEveryHead = 0, boundaryStraddles = 0;
};
static void directedQualification() {
    Witness w;
    Scoreboard model;
    Input in;
    in.allocate = {payloadRequest(1, 5), payloadRequest(2, 5)};
    auto pair = model.tick(in);
    // Every generation bit is independently significant for both producer ports and recovery.
    for (unsigned bit = 0; bit < 64; ++bit) {
        Token wrong0 = pair.allocated[0].token, wrong1 = pair.allocated[1].token;
        wrong0.tag ^= UINT64_C(1) << bit; wrong1.tag ^= UINT64_C(1) << bit;
        in = {}; in.commit = true; in.recover = true; in.inclusive = bit & 1; in.boundary = wrong0;
        in.complete = {Completion{true, true, wrong0, UINT64_MAX, 2, UINT64_MAX},
                       Completion{true, false, wrong1, UINT64_MAX}};
        auto out = model.tick(in);
        demand(!out.completed[0] && !out.completed[1] && !out.retired[0].valid && !out.retired[1].valid,
            "full-width stale generation accepted");
        w.tagBitRejects += 2; ++w.recoveryBitRejects;
    }
    in = {}; in.commit = true;
    in.complete = {Completion{true, false, pair.allocated[0].token, UINT64_C(0x80000000deadbeef)},
                   Completion{true, false, pair.allocated[1].token, UINT64_C(0x7ff0011223344556)}};
    in.allocate = {payloadRequest(3, 6), payloadRequest(4, 7)};
    auto out = model.tick(in);
    demand(out.completed[0] && out.completed[1] && out.retired[0].valid && out.retired[1].valid &&
        out.allocated[0].valid && out.allocated[1].valid, "simultaneous two-lane turnover missing");
    ++w.simultaneous; model.drain();

    // Reuse every physical ROB index after both retirement and inclusive flush.
    // A stale token for the very same index may never overwrite the new payload.
    for (unsigned flush = 0; flush < 2; ++flush) {
        model.reset();
        std::array<Token, ROB_ENTRIES> previous{};
        for (unsigned round = 0; round < 12; ++round) {
            for (unsigned lanePair = 0; lanePair < ROB_ENTRIES / 2; ++lanePair) {
                in = {}; in.allocate = {payloadRequest(1000 + flush * 10000 + round * ROB_ENTRIES + lanePair * 2),
                    payloadRequest(1001 + flush * 10000 + round * ROB_ENTRIES + lanePair * 2)};
                auto allocated = model.tick(in);
                demand(allocated.allocated[0].valid && allocated.allocated[1].valid, "wrap allocation missing");
                for (unsigned lane = 0; lane < 2; ++lane) {
                    auto token = allocated.allocated[lane].token;
                    if (round) {
                        in = {}; in.complete[0] = {true, false, previous[token.index], UINT64_MAX};
                        in.recover = true; in.boundary = previous[token.index]; in.inclusive = true;
                        demand(!model.tick(in).completed[0], "reused index accepted its old owner");
                        ++w.reuseRejects;
                    }
                    previous[token.index] = token;
                }
            }
            ++w.indexWraps;
            if (flush) {
                in = {}; in.recover = true; in.inclusive = true; in.boundary = model.queue.front().token;
                in.commit = true; in.allocate = {payloadRequest(9), payloadRequest(10)};
                in.complete = {Completion{true, false, model.queue.front().token, 1},
                    Completion{true, false, model.queue.back().token, 2}};
                out = model.tick(in);
                demand(!out.retired[0].valid && !out.allocated[0].valid && !out.completed[0] && !out.completed[1],
                    "flush priority failed");
                ++w.recoveryPriority; ++w.flushes;
            }
            model.drain();
        }
    }

    // Two-wide payload reads at every head parity and across the final/first bank address boundary.
    for (unsigned position = 0; position < ROB_ENTRIES; ++position) {
        model.reset();
        for (unsigned advance = 0; advance < position; ++advance) {
            in = {}; in.allocate[0] = payloadRequest(15000 + advance);
            auto one = model.tick(in);
            in = {}; in.commit = true;
            in.complete[0] = {true, false, one.allocated[0].token, advance}; model.tick(in);
        }
        in = {}; in.allocate = {payloadRequest(16000 + 2*position), payloadRequest(16001 + 2*position)};
        pair = model.tick(in);
        demand(pair.allocated[0].token.index == position &&
            pair.allocated[1].token.index == (position + 1) % ROB_ENTRIES, "straddling pair owner order");
        in = {}; in.commit = true;
        in.complete = {Completion{true, false, pair.allocated[0].token, UINT64_C(0xa5a5a5a555555555)},
            Completion{true, false, pair.allocated[1].token, UINT64_C(0x5a5a5a5aaaaaaaaa)}};
        out = model.tick(in);
        demand(out.retired[0].valid && out.retired[1].valid, "two-wide payload parity retirement");
        ++w.pairAtEveryHead; w.boundaryStraddles += position == ROB_ENTRIES - 1;
        model.drain();
    }

    // Full capacity cannot take same-cycle freed slots; subsequent partial capacity accepts one lane.
    model.reset();
    for (unsigned n = 0; n < ROB_ENTRIES / 2; ++n) {
        in = {}; in.allocate = {payloadRequest(20000 + 2*n), payloadRequest(20001 + 2*n)};
        model.tick(in);
    }
    in = {}; in.commit = true; in.allocate = {payloadRequest(21000), payloadRequest(21001)};
    in.complete[0] = {true, false, model.queue.front().token, 0xabc};
    out = model.tick(in);
    demand(out.retired[0].valid && !out.retired[1].valid && !out.allocated[0].valid,
        "full-capacity partial retire/backpressure missing");
    ++w.partialRetires; ++w.fullBackpressure;
    in = {}; in.allocate = {payloadRequest(21002), payloadRequest(21003)};
    out = model.tick(in);
    demand(out.allocated[0].valid && !out.allocated[1].valid, "one-slot allocation prefix missing");
    ++w.partialAllocation; model.drain();

    // Completed payload remains unchanged under independent dispatch/retirement stalls and poisoned invalid inputs.
    model.reset();
    in = {}; in.allocate = {payloadRequest(30000, 3), payloadRequest(30001, 4)}; pair = model.tick(in);
    in = {}; in.complete = {Completion{true, false, pair.allocated[0].token, 0x1234},
        Completion{true, false, pair.allocated[1].token, 0x5678}}; model.tick(in);
    for (unsigned n = 0; n < 97; ++n) {
        in = {}; in.dispatch = false; in.allocate = {payloadRequest(UINT64_MAX - n), payloadRequest(0xdead + n)};
        in.complete = {Completion{false, true, pair.allocated[0].token, UINT64_MAX, UINT64_MAX, UINT64_MAX},
            Completion{true, false, pair.allocated[1].token, UINT64_MAX}};
        out = model.tick(in);
        demand(!out.allocated[0].valid && !out.retired[0].valid && !out.completed[0] && !out.completed[1],
            "held payload ownership changed");
        ++w.heldPayloadCycles;
    }
    in = {}; in.commit = true; model.tick(in); model.drain();

    // Partial retirement before a synchronous fault; the exception holds precise high-bit metadata.
    model.reset();
    in = {}; in.allocate = {payloadRequest(40000, 8), payloadRequest(40001, 9)}; pair = model.tick(in);
    in = {}; in.commit = true;
    in.complete = {Completion{true, false, pair.allocated[0].token, 10},
        Completion{true, true, pair.allocated[1].token, 11, UINT64_C(0x8000000000000002), UINT64_C(0xfedcba9876543210)}};
    out = model.tick(in);
    demand(out.retired[0].valid && !out.retired[1].valid, "exception did not stop retirement prefix");
    ++w.partialRetires;
    for (unsigned n = 0; n < 33; ++n) {
        in = {}; in.commit = true; in.dispatch = false;
        in.complete[0] = {true, false, pair.allocated[1].token, UINT64_MAX};
        out = model.tick(in);
        demand(!out.retired[0].valid && !out.retired[1].valid && !out.completed[0], "precise exception lost ownership");
        ++w.exceptionHolds;
    }
    in = {}; in.headTrap = true; in.commit = true;
    in.allocate = {payloadRequest(41000), payloadRequest(41001)};
    out = model.tick(in); demand(!out.allocated[0].valid && !out.retired[0].valid, "trap recovery priority");
    ++w.flushes; ++w.recoveryPriority; model.drain();
    in = {}; in.allocate = {payloadRequest(42000), payloadRequest(42001)}; model.tick(in);
    model.reset(); ++w.resetWithOwners; model.drain();

    demand(w.tagBitRejects == 128 && w.recoveryBitRejects == 64 && w.reuseRejects == 352 &&
        w.indexWraps == 24 && w.partialAllocation == 1 && w.exceptionHolds == 33 &&
        w.pairAtEveryHead == ROB_ENTRIES && w.boundaryStraddles == 1, "directed coverage incomplete");
    std::cout << "GSIM FPGA-next ROB directed: PASS tagBitRejects=" << w.tagBitRejects
        << " recoveryBitRejects=" << w.recoveryBitRejects << " simultaneousAllocateCompleteRetire=" << w.simultaneous
        << " indexWraps=" << w.indexWraps << " reusedIndexStaleRejects=" << w.reuseRejects
        << " flushes=" << w.flushes << " partialRetires=" << w.partialRetires
        << " heldPayloadCycles=" << w.heldPayloadCycles << " fullBackpressure=" << w.fullBackpressure
        << " partialAllocation=" << w.partialAllocation << " exceptionHolds=" << w.exceptionHolds
        << " recoveryPriority=" << w.recoveryPriority << " resetWithOwners=" << w.resetWithOwners
        << " pairAtEveryHead=" << w.pairAtEveryHead << " boundaryStraddles=" << w.boundaryStraddles << '\n';
}
int main(int argc, char **argv) {
    try {
        if (argc == 2 && std::string(argv[1]).starts_with("--mutate=")) mutation = std::string(argv[1]).substr(9);
        else if (argc > 1) return inherited_ledger_main(argc, argv);
        inherited_ledger_main(1, argv);
        directedQualification();
        if (!mutation.empty()) throw std::runtime_error("negative control did not reject: " + mutation);
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "GSIM FPGA-next ROB qualification: FAIL " << e.what()
            << " mutation=" << mutation << " fired=" << mutationFired << '\n';
        return 1;
    }
}
