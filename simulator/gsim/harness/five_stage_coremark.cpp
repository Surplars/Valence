#ifdef I1_SPINOR_CPU_DUAL
#include "I1SpinorDualClockFixture.h"
using Model = SI1SpinorDualClockFixture;
#elif defined(I1_SPINOR_CPU)
#include "I1SpinorCoreFixture.h"
using Model = SI1SpinorCoreFixture;
#elif defined(DUT_OOO)
#include "InorderMatchedOooCoremark.h"
using Model = SInorderMatchedOooCoremark;
#else
#ifdef I1_COREMARK_PREDICTION
#include "I1PerformanceCachedCore.h"
using Model = SI1PerformanceCachedCore;
#else
#include "FiveStageCachedCore.h"
using Model = SFiveStageCachedCore;
#endif
#endif
#define FIVE_STAGE_ORACLE_ONLY
#include "five_stage.cpp"
#ifdef I1_COREMARK_COMPRESSED
#include "i1_compressed_reference.h"
#endif
#ifdef I1_COREMARK_PREDICTION
#include "i1_prediction_metrics.h"
#endif
#include <deque>
#include <fstream>
#include <iomanip>
#include <iterator>
#define SIGNAL(PREFIX, PORT, SUFFIX) PREFIX ## PORT ## SUFFIX

struct Burst { uint64_t address, data, due; unsigned mask, beats, beat = 0; bool write, prepared = false;
    uint64_t value = 0; bool error = false; };
struct Memory {
    Model &d;
    std::vector<uint8_t> bytes;
    std::array<std::optional<Burst>, 2> owners;
    std::array<bool, 2> requestReady{};
    std::array<std::optional<std::array<uint64_t, 5>>, 2> held;
    std::optional<unsigned> active;
    std::deque<uint64_t> timerValues;
    unsigned latency, last = 1;
    uint64_t requests = 0, beats = 0, writes = 0, activeCycles = 0, arbitrationWaitCycles = 0;
    Memory(Model &model, std::vector<uint8_t> image, unsigned delay) : d(model), bytes(std::move(image)), latency(delay) {}
    uint64_t load(uint64_t a, unsigned n = 8) const {
        need(a >= BASE && a + n <= BASE + bytes.size(), "benchmark memory out of bounds");
        uint64_t value = 0; for (unsigned j = 0; j < n; ++j) value |= uint64_t(bytes[a - BASE + j]) << (8 * j);
        return value;
    }
    void inputs(uint64_t cycle) {
        if (!active) for (unsigned n = 0; n < 2; ++n) {
            unsigned port = (last + 1 + n) % 2;
            if (owners[port]) { active = port; owners[port]->due = cycle + latency; last = port; break; }
        }
        if (active) {
            ++activeCycles;
            auto &b = *owners[*active];
            if (b.due <= cycle && !b.prepared) {
                uint64_t a = b.address + b.beat * 8;
                b.error = a != 0x0200bff8 && (a < BASE || a + 8 > BASE + bytes.size());
                b.value = a == 0x0200bff8 ? cycle : b.error ? 0 : load(a);
                b.prepared = true;
            }
        }
        for (unsigned port = 0; port < 2; ++port)
            arbitrationWaitCycles += owners[port] && (!active || *active != port);
#define INPUT(PORT, INDEX) \
        requestReady[INDEX] = !owners[INDEX]; d.SIGNAL(set_io$$, PORT, $$request$$ready)(requestReady[INDEX]); \
        d.SIGNAL(set_io$$, PORT, $$response$$valid)(active && *active == INDEX && owners[INDEX]->prepared); \
        d.SIGNAL(set_io$$, PORT, $$response$$bits$$data)(owners[INDEX] ? owners[INDEX]->value : 0); \
        d.SIGNAL(set_io$$, PORT, $$response$$bits$$error)(owners[INDEX] && owners[INDEX]->error); \
        d.SIGNAL(set_io$$, PORT, $$response$$bits$$last)(owners[INDEX] && owners[INDEX]->beat + 1 == owners[INDEX]->beats);
        INPUT(instructionMemory, 0) INPUT(dataMemory, 1)
#undef INPUT
    }
    void outputs(uint64_t cycle) {
        if (active) {
            unsigned port = *active; auto &b = *owners[port];
            bool ready = port ? d.get_io$$dataMemory$$response$$ready() : d.get_io$$instructionMemory$$response$$ready();
            if (b.prepared && ready) {
                uint64_t a = b.address + b.beat * 8;
                if (!b.error && b.write) for (unsigned j = 0; j < 8; ++j)
                    if (b.mask >> j & 1) bytes[a - BASE + j] = b.data >> (8 * j);
                if (a == 0x0200bff8) timerValues.push_back(b.value);
                ++beats; b.prepared = false; b.due = cycle + 1;
                if (++b.beat == b.beats) { owners[port].reset(); active.reset(); }
            }
        }
#define OUTPUT(PORT, INDEX) \
        { bool valid = d.SIGNAL(get_io$$, PORT, $$request$$valid)(), ready = requestReady[INDEX]; \
        std::array<uint64_t, 5> req{d.SIGNAL(get_io$$, PORT, $$request$$bits$$address)(), \
            d.SIGNAL(get_io$$, PORT, $$request$$bits$$write)(), d.SIGNAL(get_io$$, PORT, $$request$$bits$$data)(), \
            d.SIGNAL(get_io$$, PORT, $$request$$bits$$mask)(), d.SIGNAL(get_io$$, PORT, $$request$$bits$$beats)()}; \
        if (held[INDEX]) need(valid && req == *held[INDEX], "benchmark burst offer changed under backpressure"); \
        held[INDEX].reset(); if (valid && !ready) held[INDEX] = req; \
        if (valid && ready) { need(!owners[INDEX], "benchmark duplicated burst owner"); \
            need(req[4] >= 1 && req[4] <= 8 && !(req[0] & 7), "benchmark illegal burst"); \
            owners[INDEX] = Burst{req[0], req[2], cycle + latency, unsigned(req[3]), unsigned(req[4]), 0, bool(req[1])}; \
            ++requests; writes += req[1]; } }
        OUTPUT(instructionMemory, 0) OUTPUT(dataMemory, 1)
#undef OUTPUT
    }
};

#ifndef I1_COREMARK_MEMORY_ONLY
int main(int argc, char **argv) { try {
    need(argc == 6 || argc == 7, "image, errors/ticks/CRCs addresses and latency required; optional --inject");
    std::ifstream file(argv[1], std::ios::binary); need(bool(file), "missing benchmark binary");
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(file)), {});
    need(image.size() <= 65536, "benchmark ROM overflow"); image.resize(0x12000);
    uint64_t errorsAddress = std::stoull(argv[2], nullptr, 0), ticksAddress = std::stoull(argv[3], nullptr, 0);
    uint64_t crcsAddress = std::stoull(argv[4], nullptr, 0); unsigned latency = std::stoul(argv[5]);
    bool smoke = crcsAddress == 0;
    const bool injectRegister = argc == 7 && std::string(argv[6]) != "--inject-prediction-observer" &&
        std::string(argv[6]) != "--inject-length-observer";
    Model d; Memory memory(d, image, latency); Oracle oracle(image);
    d.set_reset(1);
#ifndef DUT_OOO
    d.set_io$$time(0); d.set_io$$externalIrq(0); d.set_io$$timerIrq(0); d.set_io$$softwareIrq(0);
#ifdef I1_WITH_A
    d.set_io$$invalidateReservation(0);
#endif
#else
    d.set_io$$inspectRegister(0);
#endif
    memory.inputs(0); d.step(); d.step(); d.set_reset(0);
    uint64_t retired = 0, trace = 1469598103934665603ULL, roiStart = 0, roiInstructions = 0;
    uint64_t instructionHits = 0, instructionMisses = 0, dataHits = 0, dataMisses = 0, mispredicts = 0;
    uint64_t loadUseStalls = 0, memoryStalls = 0, mulDivStalls = 0, fetchStalls = 0, storeAckStalls = 0;
    uint64_t dataOffers = 0, dataAccepts = 0;
    unsigned timers = 0; bool finished = false;
    uint64_t currentCycle = 0;
#ifdef I1_COREMARK_PREDICTION
    I1PredictionMetrics<Model> prediction;
    prediction.injectObservation = argc == 7 && std::string(argv[6]) == "--inject-prediction-observer";
    prediction.injectLengthObservation = argc == 7 && std::string(argv[6]) == "--inject-length-observer";
    PredictionCounts roiPredictionStart, roiPrediction, roiWarmStart, roiWarm;
    std::array<PredictionCounts, 4> roiKindsStart{}, roiKinds{};
    std::map<uint64_t, PredictionCounts> roiPcStart, roiPc;
    const auto difference = [](const PredictionCounts &a, const PredictionCounts &b) {
        return PredictionCounts{a.count-b.count, a.correct-b.correct,
            a.directionCount-b.directionCount, a.directionCorrect-b.directionCorrect};
    };
#endif
    auto retire = [&](uint64_t pc, uint32_t instruction, unsigned rd, bool writesRd, uint64_t value,
                      uint64_t nextPc, bool trap, uint64_t cause) {
        unsigned instructionBytes = 4;
        uint32_t expanded = instruction;
#ifdef I1_COREMARK_COMPRESSED
        instructionBytes = (instruction & 3) == 3 ? 4 : 2;
        if (instructionBytes == 2) {
            auto decoded = I1CompressedReference::decode(instruction);
            need(decoded.legal, "CoreMark independent compressed expansion legality");
            expanded = decoded.value;
        }
#endif
        need(pc == oracle.pc && instruction == oracle.load(pc, instructionBytes), "CoreMark independent retired PC/instruction mismatch");
        unsigned op = expanded & 127, a = expanded >> 15 & 31;
        if (op == 3 && oracle.r[a] + signExtend(expanded >> 20, 12) == 0x0200bff8) {
            need(!memory.timerValues.empty(), "unowned CoreMark timer sample");
            oracle.timerValue = memory.timerValues.front(); memory.timerValues.pop_front();
            if (++timers == 1) {
                roiStart = retired;
#ifdef I1_COREMARK_PREDICTION
                roiPredictionStart=prediction.total; roiWarmStart=prediction.warm;
                roiKindsStart=prediction.kinds; roiPcStart=prediction.perPc;
#endif
            } else {
                roiInstructions = retired - roiStart;
#ifdef I1_COREMARK_PREDICTION
                roiPrediction=difference(prediction.total,roiPredictionStart);
                roiWarm=difference(prediction.warm,roiWarmStart);
                for (unsigned kind=0;kind<4;++kind) roiKinds[kind]=difference(prediction.kinds[kind],roiKindsStart[kind]);
                for (const auto &[pc,counts]:prediction.perPc) roiPc[pc]=difference(counts,roiPcStart[pc]);
#endif
            }
        }
        auto expected = oracle.evaluate(expanded, false, false, instructionBytes);
        if (injectRegister && retired == 2) expected.value ^= 1;
        need(trap == expected.trap && (!trap || cause == expected.cause), "CoreMark independent exception mismatch");
#ifdef I1_COREMARK_PREDICTION
        prediction.retire(d,currentCycle,pc,expanded,expected.next,trap,instructionBytes);
#endif
        if (trap) {
            need(expanded == 0x00100073 && cause == 3, "CoreMark terminated at an unexpected exception");
            need(oracle.r[10] == 0, "workload CRC/errors/smoke failed"); finished = true; return;
        }
        need((writesRd && rd != 0) == expected.write, "CoreMark independent register write-enable mismatch");
        if (expected.write && (rd != expected.rd || value != expected.value))
            throw std::runtime_error("CoreMark independent register oracle mismatch pc=" + std::to_string(pc)
                + " expected=" + std::to_string(expected.value) + " got=" + std::to_string(value));
        need(nextPc == expected.next, "CoreMark independent next-PC mismatch");
        trace ^= pc; trace *= 1099511628211ULL; trace ^= instruction; trace *= 1099511628211ULL;
        oracle.commit(expected); ++retired;
    };
    uint64_t cycle;
    for (cycle = 0; cycle < (smoke ? 30000U : 12000000U) && !finished; ++cycle) {
        memory.inputs(cycle);
#ifndef DUT_OOO
        d.set_io$$time(cycle);
#endif
        d.step(); memory.outputs(cycle);
        currentCycle=cycle;
#ifdef I1_COREMARK_PREDICTION
        prediction.cycle(d,cycle);
#endif
        instructionHits += d.get_io$$instructionHit(); instructionMisses += d.get_io$$instructionMiss();
        dataHits += d.get_io$$dataHit(); dataMisses += d.get_io$$dataMiss();
#ifdef DUT_OOO
#define RETIRE(LANE) \
        if (d.SIGNAL(get_io$$commit, LANE, $$valid)()) retire(d.SIGNAL(get_io$$commit, LANE, $$bits$$pc)(), \
            d.SIGNAL(get_io$$commit, LANE, $$bits$$instruction)(), d.SIGNAL(get_io$$commit, LANE, $$bits$$rd)(), \
            d.SIGNAL(get_io$$commit, LANE, $$bits$$writesRd)(), d.SIGNAL(get_io$$commit, LANE, $$bits$$data)(), \
            d.SIGNAL(get_io$$commit, LANE, $$bits$$nextPc)(), false, 0);
        RETIRE(0) RETIRE(1)
#undef RETIRE
        if (d.get_io$$exception$$valid()) retire(d.get_io$$exception$$bits$$pc(), oracle.load(oracle.pc, 4),
            0, false, 0, 0, true, d.get_io$$exception$$bits$$cause());
#else
        mispredicts += d.get_io$$branchMispredict();
        loadUseStalls += d.get_io$$stallLoadUse(); memoryStalls += d.get_io$$stallMemory();
        mulDivStalls += d.get_io$$stallMulDiv(); fetchStalls += d.get_io$$stallFetch();
        storeAckStalls += d.get_io$$stallStoreAck();
        dataOffers += d.get_io$$dataRequestOffered(); dataAccepts += d.get_io$$dataRequestAccepted();
        if (d.get_io$$retire$$valid()) retire(d.get_io$$retire$$bits$$pc(), d.get_io$$retire$$bits$$instruction(),
            d.get_io$$retire$$bits$$rd(), d.get_io$$retire$$bits$$writesRd(), d.get_io$$retire$$bits$$data(),
            d.get_io$$retire$$bits$$nextPc(), d.get_io$$retire$$bits$$trap(), d.get_io$$retire$$bits$$cause());
#endif
    }
    if (!finished) {
        std::cerr << "WORKLOAD_STALL cycles=" << cycle << " retired=" << retired << " next_pc=" << std::hex
            << oracle.pc << std::dec << " memory_requests=" << memory.requests << " memory_beats=" << memory.beats;
#ifdef DUT_OOO
        std::cerr << " fetch_pc=" << std::hex << d.get_io$$debugFetchPc() << std::dec
            << " recovering=" << unsigned(d.get_io$$debugRecovering())
            << " fence_flush=" << unsigned(d.get_io$$debugFenceFlush())
            << " occupancy=" << unsigned(d.get_io$$debugOccupancy())
            << " memory_busy=" << unsigned(d.get_io$$debugMemoryBusy());
#endif
        std::cerr << '\n';
    }
    need(finished, "workload bounded completion failed");
    if (smoke) {
        need(std::equal(memory.bytes.begin(), memory.bytes.end(), oracle.memory.begin()),
            "self-modifying instruction/data bytes differ from independent ISA oracle");
        std::cout << "FIVE_STAGE_CACHED_CPU_SMOKE_PASS cycles=" << cycle << " retired=" << retired
            << " self_modifying_fence_i_jalr_alias_wrong_path=PASS\n";
        return 0;
    }
    need(timers == 2 && roiInstructions > 10000, "CoreMark timer/ROI coverage failed");
    need(memory.load(errorsAddress, 4) == 0, "CoreMark captured official CRC failure");
    const std::array<uint64_t, 4> known{0xe9f5, 0xe714, 0x1fd7, 0x8e3a};
    for (unsigned j = 0; j < 4; ++j) need(memory.load(crcsAddress + j * 4, 4) == known[j], "CoreMark independent known CRC mismatch");
    need(std::equal(memory.bytes.begin() + 65536, memory.bytes.end(), oracle.memory.begin() + 65536),
        "CoreMark final RAM differs from independent ISA oracle");
    uint64_t ticks = memory.load(ticksAddress);
    need(ticks == oracle.r[11] && ticks > 0, "CoreMark timer return mismatch");
#ifdef I1_COREMARK_PREDICTION
    prediction.report("coremark",latency,cycle);
    uint64_t pcBranches=0;
    for (const auto &[pc,counts]:roiPc) if (counts.count) {
        pcBranches+=counts.count;
        std::cout << "I1_COREMARK_PC pc=" << pc << " count=" << counts.count << " correct=" << counts.correct << '\n';
    }
    need(pcBranches==roiPrediction.count,"CoreMark per-PC ROI branch denominator mismatch");
    std::cout << "I1_COREMARK_PREDICTION {\"roi_branches\":" << roiPrediction.count
        << ",\"roi_correct\":" << roiPrediction.correct
        << ",\"roi_direction_queries\":" << roiPrediction.directionCount
        << ",\"roi_direction_correct\":" << roiPrediction.directionCorrect
        << ",\"roi_returns\":" << roiKinds[2].count << ",\"roi_returns_correct\":" << roiKinds[2].correct
        << ",\"roi_indirect\":" << roiKinds[3].count << ",\"roi_indirect_correct\":" << roiKinds[3].correct
        << ",\"roi_warm_branches\":" << roiWarm.count << ",\"roi_warm_correct\":" << roiWarm.correct << "}\n";
#endif
    std::cout << "MATCHED_COREMARK_PASS {\"cycles\":" << cycle << ",\"roi_ticks\":" << ticks
        << ",\"roi_instructions\":" << roiInstructions << ",\"retired\":" << retired
        << ",\"trace_fnv64\":\"" << std::hex << trace << std::dec << "\",\"burst_requests\":" << memory.requests
        << ",\"bus_beats\":" << memory.beats << ",\"stores\":" << memory.writes
        << ",\"ic_hits\":" << instructionHits << ",\"ic_misses\":" << instructionMisses
        << ",\"dc_hits\":" << dataHits << ",\"dc_misses\":" << dataMisses
        << ",\"mispredicts\":" << mispredicts << ",\"crcfinal\":" << memory.load(crcsAddress + 16, 4)
        << ",\"stall_load_use_cycles\":" << loadUseStalls << ",\"stall_memory_cycles\":" << memoryStalls
        << ",\"stall_mul_div_cycles\":" << mulDivStalls << ",\"stall_fetch_cycles\":" << fetchStalls
        << ",\"stall_store_ack_cycles\":" << storeAckStalls << ",\"data_offered_cycles\":" << dataOffers
        << ",\"data_accepted_requests\":" << dataAccepts << ",\"bus_active_cycles\":" << memory.activeCycles
        << ",\"arbitration_wait_owner_cycles\":" << memory.arbitrationWaitCycles
        << ",\"formal_score\":false}\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }

#endif // I1_COREMARK_MEMORY_ONLY
