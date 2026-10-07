#include "IntegerCoreGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <dlfcn.h>
#include <fstream>
#include <iostream>
#include <iterator>
#include <iomanip>
#include <optional>
#include <random>
#include <stdexcept>

#include <string>
#include <vector>

#ifndef MEMORY_ENTRIES
#define MEMORY_ENTRIES 4
#endif
#ifndef FAST_HEAD_LOAD
#define FAST_HEAD_LOAD 0
#endif
#ifndef INDIRECT_ENTRIES
#define INDIRECT_ENTRIES 0
#endif
#ifndef REGISTERED_BRANCH_REDIRECT
#define REGISTERED_BRANCH_REDIRECT 0
#endif
#ifndef BRANCH_ENTRIES
#define BRANCH_ENTRIES 64
#endif
#ifndef DELAYED_PREDICTION_TRAINING
#define DELAYED_PREDICTION_TRAINING 0
#endif
#ifndef REGISTERED_FETCH_PACKET
#define REGISTERED_FETCH_PACKET 0
#endif
#ifndef STORE_BUFFER_ENTRIES
#define STORE_BUFFER_ENTRIES 4
#endif

constexpr uint64_t base = 0x80000000;
constexpr uint64_t dataBase = base + 0x10000;
using Memory = std::array<uint8_t, 4096>;
static void check(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
#include "isa_model.h"
#include "reference.h"
struct Commit {
    bool valid, writes;
    unsigned rd;
    uint64_t pc, value, nextPc, tag;
    uint32_t instruction;
};
static std::array<Commit, 2> commits(SIntegerCoreGsim &dut) {
    std::array<Commit, 2> out{};
#define COMMIT(N) \
    out[N] = {bool(dut.get_io$$commit##N##$$valid()), bool(dut.get_io$$commit##N##$$bits$$writesRd()), \
              dut.get_io$$commit##N##$$bits$$rd(), dut.get_io$$commit##N##$$bits$$pc(), \
              dut.get_io$$commit##N##$$bits$$data(), dut.get_io$$commit##N##$$bits$$nextPc(), \
              dut.get_io$$commit##N##$$bits$$token$$tag(), dut.get_io$$commit##N##$$bits$$instruction()};
    COMMIT(0)
    COMMIT(1)
#undef COMMIT
    return out;
}
static void idle(SIntegerCoreGsim &dut) {
    dut.set_io$$instruction0$$valid(0); dut.set_io$$instruction0$$bits(0);
    dut.set_io$$instruction1$$valid(0); dut.set_io$$instruction1$$bits(0);
    dut.set_io$$commitEnable(1); dut.set_io$$inspectRegister(0);
    dut.set_io$$decodeInstruction(0); dut.set_io$$decodePc(0);
    dut.set_io$$memory$$request$$ready(0);
    dut.set_io$$memory$$response$$valid(0);
    dut.set_io$$memory$$response$$bits$$data(0);
    dut.set_io$$memory$$response$$bits$$error(0);
}
static void reset(SIntegerCoreGsim &dut) {
    idle(dut);
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
}
static uint64_t decoderTests() {
    SIntegerCoreGsim dut;
    reset(dut);
    uint64_t count = 0;
    auto test = [&](uint32_t inst, uint64_t pc) {
        dut.set_io$$decodeInstruction(inst); dut.set_io$$decodePc(pc); dut.step();
        const auto *e = decode(inst);
        check(bool(dut.get_io$$decodeLegal()) == bool(e), "decoder legality: " + std::to_string(inst));
        check(dut.get_io$$decoded$$rename$$instruction() == inst && dut.get_io$$decoded$$rename$$pc() == pc,
              "decoder instruction/PC metadata");
        const bool conditional = e && e->control >= 1 && e->control <= 6;
        const bool noDestination = conditional || (e && e->memory == 2);
        check(dut.get_io$$decoded$$rename$$rd() == (noDestination ? 0 : ((inst >> 7) & 31)), "decoder destination");
        check(bool(dut.get_io$$decoded$$rename$$writesRd()) == (bool(e) && !noDestination), "decoder destination enable");
        check(bool(dut.get_io$$decoded$$mulDiv()) == bool(e && e->mulDiv), "decoder M kind");
        check(dut.get_io$$decoded$$mulDivOp() == ((e && e->mulDiv) ? ((inst >> 12) & 7) : 0), "decoder M operation");
        if (e) {
            check(dut.get_io$$decoded$$operation() == e->alu && bool(dut.get_io$$decoded$$word()) == e->word,
                  std::string("decoder operation: ") + e->name);
            check(dut.get_io$$decoded$$rename$$rs1() == ((e->upper || e->control == 7) ? 0 : ((inst >> 15) & 31)), "decoder source 1");
            check(dut.get_io$$decoded$$rename$$rs2() == (e->immediate ? 0 : ((inst >> 20) & 31)), "decoder source 2");
            check(bool(dut.get_io$$decoded$$usePc()) == e->pc &&
                  bool(dut.get_io$$decoded$$useImmediate()) == e->immediate, "decoder operand mux");
            check(dut.get_io$$decoded$$controlFlow() == e->control, "decoder control-flow kind");
            check(bool(dut.get_io$$decoded$$memory()) == bool(e->memory) &&
                  bool(dut.get_io$$decoded$$store()) == (e->memory == 2) &&
                  dut.get_io$$decoded$$memorySize() == (e->memory ? ((inst >> 12) & 3) : 0) &&
                  bool(dut.get_io$$decoded$$memoryUnsigned()) == (e->memory == 1 && (inst & 0x4000)),
                  "decoder memory fields");
            if (e->immediate || conditional || e->memory) check(dut.get_io$$decoded$$immediate() == immediate(*e, inst), "decoder immediate extension");
        } else {
            check(dut.get_io$$decoded$$operation() == 15 && !dut.get_io$$decoded$$word() &&
                  !dut.get_io$$decoded$$rename$$rs1() && !dut.get_io$$decoded$$rename$$rs2() &&
                  !dut.get_io$$decoded$$controlFlow() && !dut.get_io$$decoded$$memory() && !dut.get_io$$decoded$$store(),
                  "illegal operation must have no dependencies");
        }
        ++count;
    };
    for (unsigned opcode = 0; opcode < 128; ++opcode)
        for (unsigned funct3 = 0; funct3 < 8; ++funct3)
            for (unsigned funct7 = 0; funct7 < 128; ++funct7)
                test(opcode | (funct3 << 12) | (funct7 << 25) | (17U << 20) | (13U << 15) | (7U << 7), base);
    std::mt19937_64 rng(0x19abcdef);
    for (unsigned i = 0; i < 5000; ++i) test(rng(), rng());
    // Exhaust fixed unary selectors and all six immediate index bits, including reserved neighbours.
    for (unsigned opcode : {0x13U, 0x1bU, 0x33U, 0x3bU})
        for (unsigned f3 : {1U, 4U, 5U})
            for (unsigned upper = 0; upper < 4096; ++upper)
                test(opcode | (f3 << 12) | (upper << 20) | (13U << 15) | (7U << 7), base);
    return count;
}
struct Stats {
    uint64_t mulDivCancelled = 0, mulDivOverlap = 0, mulDivBlocked = 0, mulDivConcurrent = 0, mulDivMultiCancel = 0;
    uint64_t earlyDisjointLoads = 0;
    uint64_t forwarded = 0, loads = 0, stores = 0, memoryErrors = 0, memoryBackpressure = 0;
    uint64_t commits = 0, dualCommits = 0, partialAccepts = 0, supplyStalls = 0, backendStalls = 0;
    uint64_t programs = 0, traps = 0, performanceCycles = 0, redirects = 0, recoveryCycles = 0;
    uint64_t branches = 0, takenBranches = 0, jumps = 0, olderRedirects = 0, misaligned = 0, olderDuringRollback = 0;
    uint64_t slot0HoldAndLane1Progress = 0, olderLane0BranchResolution = 0, aluForwardingHits = 0;
};
// Independent byte RAM. Serial requests must match the architectural head;
// buffered RAM writes are matched in order against the retired architectural store stream.
// speculative RAM read values are checked by the independent ISA model and NEMU at retirement.
struct BusRequest {
    uint64_t address, data;
    unsigned size, mask;
    bool write;
    bool operator==(const BusRequest &) const = default;
};
class DataMemory {
    struct Response { uint64_t data, due; bool error, write; };
    unsigned latency;
    std::optional<BusRequest> held;
    bool requestReady = false, responseValid = false;
    Response response{};
    Response read(const BusRequest &r, uint64_t due) const {
        Response out{0, due, r.address < dataBase || r.address - dataBase >= memory.size(), r.write};
        if (!out.error) {
            const auto index = (r.address - dataBase) & ~UINT64_C(7);
            for (unsigned i = 0; i < 8; ++i) out.data |= uint64_t(memory[index + i]) << (i * 8);
        }
        return out;
    }
public:
    Memory memory;
    uint64_t watchAddress = 0, beforeStorePc = 0, earlyReads = 0;
    std::deque<BusRequest> busWrites, retiredWrites;
    std::vector<uint64_t> readAddresses;
    void compareWrites() {
        while (!busWrites.empty() && !retiredWrites.empty()) {
            const auto &a = busWrites.front(), &b = retiredWrites.front();
            check(a.address == b.address && a.size == b.size && a.mask == b.mask, "buffered store order/address mismatch");
            for (unsigned lane = 0; lane < 8; ++lane) if (a.mask & (1U << lane))
                check(uint8_t(a.data >> (8 * lane)) == uint8_t(b.data >> (8 * lane)), "buffered store data mismatch");
            busWrites.pop_front(); retiredWrites.pop_front();
        }
    }
    void retiredStore(uint64_t address, unsigned size, uint64_t data) {
        const unsigned lane = address & 7;
        retiredWrites.push_back({address, data << (8 * lane), size, ((1U << (1U << size)) - 1) << lane, true});
        compareWrites();
    }
    std::deque<Response> pending;
    size_t maxOutstanding = 0;
    uint64_t loads = 0, stores = 0, errors = 0, backpressure = 0, readWriteOverlap = 0;
    DataMemory(const Memory &initial, unsigned delay) : latency(delay), memory(initial) {}
    void drive(SIntegerCoreGsim &dut, uint64_t cycle, bool stalled, std::mt19937_64 &rng) {
        requestReady = latency == 0 ? bool(held) && pending.empty() : (!stalled || rng() % 4 != 0);
        responseValid = false;
        if (!pending.empty() && cycle >= pending.front().due) { responseValid = true; response = pending.front(); }
        if (latency == 0 && held && requestReady) { responseValid = true; response = read(*held, cycle); }
        dut.set_io$$memory$$request$$ready(requestReady);
        dut.set_io$$memory$$response$$valid(responseValid);
        dut.set_io$$memory$$response$$bits$$data(response.data);
        dut.set_io$$memory$$response$$bits$$error(response.error);
    }
    void observe(SIntegerCoreGsim &dut, uint64_t cycle, uint64_t architecturalPc,
                 const std::vector<uint32_t> &program, const std::array<uint64_t, 32> &registers) {
        if (responseValid) {
            const bool accepted = dut.get_io$$memory$$response$$ready();
#if !REGISTERED_RESPONSE_OWNERS
            check(accepted, "LSU dropped outstanding response");
#endif
            if (accepted && !pending.empty()) pending.pop_front();
        }
        const bool valid = dut.get_io$$memory$$request$$valid();
        check(!held || valid, "LSU withdrew a stalled request");
        if (!valid) return;
        const BusRequest r{dut.get_io$$memory$$request$$bits$$address(), dut.get_io$$memory$$request$$bits$$data(),
                           dut.get_io$$memory$$request$$bits$$size(), dut.get_io$$memory$$request$$bits$$mask(),
                           bool(dut.get_io$$memory$$request$$bits$$write())};
        check(!held || *held == r, "memory request changed under backpressure");
        const unsigned bytes = 1U << r.size, lane = r.address & 7;
        check(r.size <= 3 && !(r.address & (bytes - 1)) && r.mask == ((1U << bytes) - 1) << lane,
              "invalid data request alignment or lanes");
        const bool ordinaryRam = r.address >= dataBase && r.address - dataBase <= memory.size() - bytes;
        if (!ordinaryRam) {
            check(architecturalPc >= base && (architecturalPc - base) / 4 < program.size(), "unexpected memory request PC");
            const uint32_t inst = program[(architecturalPc - base) / 4];
            const auto *e = decode(inst);
            check(e && e->memory, "premature irrevocable memory request");
            const uint64_t address = registers[(inst >> 15) & 31] + immediate(*e, inst);
            check(r.address == address && r.size == ((inst >> 12) & 3) && r.write == (e->memory == 2),
                  "irrevocable request does not match architectural head");
            if (r.write) {
                const uint64_t value = registers[(inst >> 20) & 31];
                for (unsigned i = 0; i < bytes; ++i)
                    check(uint8_t(r.data >> ((lane + i) * 8)) == uint8_t(value >> (i * 8)), "store byte lane mismatch");
            }
        }
        if (!requestReady) { held = r; ++backpressure; return; }
        if (!r.write && r.address == watchAddress && architecturalPc < beforeStorePc) ++earlyReads;
        // Load slots and four buffered stores share MEMORY_ENTRIES+1 ordered owner credits.
        const auto writes = std::count_if(pending.begin(), pending.end(), [](const auto &p){return p.write;});
        const auto reads = pending.size() - writes;
        if(!r.write && writes)++readWriteOverlap;
        check(pending.size() < MEMORY_ENTRIES + 1, "exceeded response-owner credits");
        check(r.write ? writes < STORE_BUFFER_ENTRIES : reads < MEMORY_ENTRIES, "exceeded read/write capacity");
        const auto reply = read(r, cycle + latency);
        errors += reply.error;
        if (r.write) {
            ++stores;
            if (!reply.error) {
                busWrites.push_back(r); compareWrites();
                const auto index = (r.address - dataBase) & ~UINT64_C(7);
                for (unsigned i = 0; i < 8; ++i) if (r.mask & (1U << i)) memory[index + i] = r.data >> (8 * i);
            }
        } else {
            ++loads;
            readAddresses.push_back(r.address);
        }
        if (latency == 0) {
            check(responseValid, "same-cycle memory response missing");
            if (!dut.get_io$$memory$$response$$ready()) pending.push_back(reply);
        } else pending.push_back(reply);
        maxOutstanding = std::max(maxOutstanding, pending.size());
        held.reset();
    }
};

static void programTest(Reference &ref, const std::vector<uint32_t> &program, uint64_t seed,
                        bool stalled, bool performance, bool injectMismatch, Stats &stats,
                        unsigned memoryLatency = 1, const std::string &benchmark = "", bool expectDiscard = false, int expectedForwarded = -1,
                        int watchStoreIndex = -1, unsigned watchLoadOffset = 0, bool expectEarlyRead = false) {
    SIntegerCoreGsim dut;
    reset(dut);
    check(program.size() * 4 <= dataBase - base, "code image overlaps reference data RAM");
    ref.load(program);
    Memory architecturalMemory{};
    for (size_t i = 0; i < architecturalMemory.size(); ++i) architecturalMemory[i] = uint8_t(i * 37 + 0x80);
    // Independent linked-ring fixture: every load yields next-address minus 8.
    // The following ADDI must execute before the next load can form its address.
    if (benchmark == "throughput_serial_load_alu_address") {
        for (unsigned node = 0; node < 64; ++node) {
            const uint64_t value = dataBase + ((node + 1) % 64) * 8 - 8;
            for (unsigned byte = 0; byte < 8; ++byte)
                architecturalMemory[node * 8 + byte] = uint8_t(value >> (byte * 8));
        }
    }
    ref.initializeMemory(architecturalMemory);
    std::array<uint64_t, 32> architectural{};
    std::mt19937_64 rng(seed);
    uint64_t fetchPc = base, architecturalPc = base;
    const uint64_t end = base + program.size() * 4;
    uint64_t retired = 0, fetched = 0, lastCommitTag = 0, lastRedirectTag = 0;
    bool hadRedirect = false;
    unsigned drained = 0;
    DataMemory ram(architecturalMemory, memoryLatency);
    if (watchStoreIndex >= 0) {
        ram.watchAddress = dataBase + watchLoadOffset;
        ram.beforeStorePc = base + unsigned(watchStoreIndex) * 4;
    }
    uint64_t cycles = 0, zero = 0, single = 0, dual = 0, recovery = 0, blocked = 0, memBusy = 0;
    std::array<uint64_t, 3> issueCycles{}, renameCycles{};
    uint64_t occupancySum = 0, robFull = 0;
    std::array<unsigned, BRANCH_ENTRIES> direction{};
    direction.fill(1);
#if INDIRECT_ENTRIES > 0
    std::array<bool, INDIRECT_ENTRIES> indirectValid{};
    std::array<uint64_t, INDIRECT_ENTRIES> indirectTag{}, indirectTarget{};
#endif
    struct Training { uint64_t pc, nextPc; unsigned kind; };
    std::vector<Training> pendingTraining;
    auto train = [&](const Training& event) {
        if (event.kind >= 1 && event.kind <= 6) {
            auto& counter = direction[(event.pc >> 2) % direction.size()];
            if (event.nextPc != event.pc + 4) counter = std::min(3U, counter + 1);
            else if (counter) --counter;
        }
#if INDIRECT_ENTRIES > 0
        if (event.kind == 8) {
            const auto index = (event.pc >> 2) % INDIRECT_ENTRIES;
            indirectValid[index] = true;
            indirectTag[index] = event.pc;
            indirectTarget[index] = event.nextPc;
        }
#endif
    };
    uint64_t predictedTaken = 0, branchMisses = 0, directMisses = 0, knownJalrPredictions = 0;
    bool previousAuipc = false;
    uint64_t previousAuipcNext = 0, previousAuipcValue = 0;
    unsigned previousAuipcRd = 0;
    bool finished = false;
    uint64_t drainCycles = 0;
    unsigned discarded = 0, forwarded = 0;
    constexpr uint64_t dmaValue = UINT64_C(0x1122334455667788);
    const bool dmaReplay = benchmark == "same_address_dma_replay" ||
        benchmark == "same_address_dma_replay_zero" || benchmark == "overlap_dma_replay";
    bool dmaInjected = false;
    auto finish = [&]() {
        if (watchStoreIndex >= 0) check(bool(ram.earlyReads) == expectEarlyRead, "load/store disambiguation timing witness");
        stats.earlyDisjointLoads += ram.earlyReads;
        check(expectedForwarded < 0 || forwarded == unsigned(expectedForwarded), "store forwarding coverage: " + std::to_string(forwarded));
        stats.forwarded += forwarded;
        check(!expectDiscard || discarded > 0, "wrong-path RAM load cancellation coverage");
        check(ram.memory == architecturalMemory && ram.pending.empty(), "RAM state at program end");
        check(ram.busWrites.empty() && ram.retiredWrites.empty(), "missing or extra buffered store");
        ref.compareMemory(architecturalMemory);
        stats.loads += ram.loads; stats.stores += ram.stores;
        stats.memoryErrors += ram.errors; stats.memoryBackpressure += ram.backpressure;
        if (!benchmark.empty()) {
            if (benchmark.starts_with("rv64b_dependent_"))
                check(cycles <= retired + 4, "B dependent stream lost one-per-cycle throughput");
            if (benchmark.starts_with("rv64b_independent_"))
                check(double(retired) / cycles > (PHYSICAL_REGS >= 40 ? 1.9 : 1.3), "B independent throughput");
            // No retirement-to-query bypass: the second iteration is fetched in the first training cycle.
            if (benchmark == "direct_jump_chain") check(directMisses == 0, "direct JAL must avoid execution redirects");
            if (benchmark == "taken_branch_loop") check(branchMisses == 3, "loop predictor warmup and exit coverage: " + std::to_string(branchMisses));
            if (benchmark == "independent_loads" && memoryLatency == 12)
                check(ram.maxOutstanding == MEMORY_ENTRIES, "independent load concurrency coverage");
            if (benchmark == "ready_load_bypass")
                check(ram.readAddresses.size() == 5 && ram.readAddresses.front() == dataBase + 8 &&
                      std::count(ram.readAddresses.begin(), ram.readAddresses.end(), dataBase) == 1 &&
                      ram.maxOutstanding >= 2,
                      "ready younger loads must issue while the older address waits for division");
            if (dmaReplay)
                check(dmaInjected && recovery > 0 && ram.readAddresses.size() == 3 &&
                      ram.readAddresses.front() == dataBase &&
                      ram.readAddresses[1] == dataBase + (benchmark == "overlap_dma_replay" ? 4 : 0) &&
                      ram.readAddresses.back() == dataBase &&
                      architectural[4] == (benchmark == "overlap_dma_replay" ? dmaValue >> 32 : dmaValue) &&
                      architectural[6] == dmaValue,
                      "overlapping load replay must discard the value read before an external write");
            if(benchmark=="compiled_c_array_sum" && memoryLatency==12 && ROB_ENTRIES==32) {
                check(ram.readWriteOverlap>0,"core load/write response overlap coverage");
                std::cout<<"GSIM RAM read/write overlap: PASS requests="<<ram.readWriteOverlap<<"\n";
            }
            check(architecturalPc == end, "benchmark must finish normally, not stop on an exception");
            check(!stalled && retired > 0 && cycles == zero + single + dual, "IPC accounting");
            check(retired == single + 2 * dual, "IPC retirement accounting");
            std::cout << "IPC {\"name\":\"" << benchmark << "\",\"rob\":" << ROB_ENTRIES
                      << ",\"physical\":" << PHYSICAL_REGS << ",\"memory_latency\":" << memoryLatency
#if REGISTERED_FETCH_PACKET
                      << ",\"predicted_taken\":null"
#else
                      << ",\"predicted_taken\":" << predictedTaken << ",\"branch_mispredictions\":" << branchMisses
#endif
#if REGISTERED_FETCH_PACKET
                      << ",\"branch_mispredictions\":" << branchMisses
                      << ",\"known_jalr_predictions\":null"
#else
                      << ",\"known_jalr_predictions\":" << knownJalrPredictions
#endif
                      << ",\"direct_mispredictions\":" << directMisses
                      << ",\"cycles\":" << cycles << ",\"retired\":" << retired
                      << ",\"post_retirement_memory_drain_cycles\":" << drainCycles
                      << ",\"ipc\":" << std::setprecision(9) << double(retired) / cycles
                      << ",\"zero_commit_cycles\":" << zero << ",\"single_commit_cycles\":" << single
                      << ",\"dual_commit_cycles\":" << dual << ",\"recovery_cycles\":" << recovery
#if REGISTERED_FETCH_PACKET
                      << ",\"allocation_blocked_cycles\":null"
#else
                      << ",\"allocation_blocked_cycles\":" << blocked
#endif
                      << ",\"raw_input_present_no_rename_cycles\":" << blocked
                      << ",\"memory_busy_cycles\":" << memBusy
                      << ",\"zero_issue_cycles\":" << issueCycles[0] << ",\"single_issue_cycles\":" << issueCycles[1]
                      << ",\"dual_issue_cycles\":" << issueCycles[2]
                      << ",\"issued\":" << issueCycles[1] + 2 * issueCycles[2]
                      << ",\"zero_rename_cycles\":" << renameCycles[0] << ",\"single_rename_cycles\":" << renameCycles[1]
                      << ",\"dual_rename_cycles\":" << renameCycles[2]
                      << ",\"rob_occupancy_sum\":" << occupancySum << ",\"rob_full_cycles\":" << robFull
                      << ",\"memory_entries\":" << MEMORY_ENTRIES << ",\"max_outstanding\":" << ram.maxOutstanding << ",\"forwarded_loads\":" << forwarded << ",\"loads\":" << ram.loads << ",\"stores\":" << ram.stores << "}\n";
        }
    };
    auto inImage = [&](uint64_t pc) { return pc >= base && pc < end && (pc & 3) == 0; };
    for (uint64_t cycle = 0; cycle < std::max<size_t>(200000, program.size() * 200 + 2000); ++cycle) {
        if (dmaReplay && cycle == 30) {
            check(ram.readAddresses.size() == 1 && ram.pending.empty(),
                  "external write must follow the younger read and precede the older one");
            for (unsigned i = 0; i < 8; ++i)
                ram.memory[i] = architecturalMemory[i] = dmaValue >> (8 * i);
            ref.externalWrite64(dataBase, dmaValue);
            dmaInjected = true;
        }
        const unsigned inspect = cycle % 32;
        const bool enable = !stalled || (cycle >= 64 && rng() % 5 != 0);
        const bool supply = !stalled || rng() % 5 != 0;
        const bool valid0 = supply && inImage(fetchPc);
        const bool valid1 = valid0 && inImage(fetchPc + 4) && (!stalled || rng() % 4 != 0);
        std::array<uint64_t, 2> prediction{fetchPc + 4, fetchPc + 8};
        std::array<bool, 2> predictTaken{}, knownIndirect{};
#if !REGISTERED_FETCH_PACKET
        for (unsigned lane = 0; lane < 2; ++lane) {
            const uint64_t pc = fetchPc + lane * 4;
            if (!(lane == 0 ? valid0 : valid1)) continue;
            const uint32_t inst = program[(pc - base) / 4];
            const auto *e = decode(inst);
            if (e && e->control >= 1 && e->control <= 7) {
                const uint64_t target = pc + immediate(*e, inst);
                predictTaken[lane] = (e->control == 7 || direction[(pc >> 2) % direction.size()] >= 2) &&
                    !(target & 3) && target != pc + 4;
                if (predictTaken[lane]) prediction[lane] = target;
            } else if (e && e->control == 8) {
                bool valid = previousAuipc && previousAuipcNext == pc;
                uint64_t value = previousAuipcValue;
                unsigned rd = previousAuipcRd;
                if (lane == 1) {
                    const auto prior = program[(fetchPc - base) / 4];
                    rd = (prior >> 7) & 31;
                    valid = valid0 && (prior & 127) == 0x17 && rd;
                    if (valid) value = fetchPc + immediate(*decode(prior), prior);
                }
                const uint64_t target = (value + immediate(*e, inst)) & ~UINT64_C(1);
                knownIndirect[lane] = valid && rd == ((inst >> 15) & 31);
                predictTaken[lane] = knownIndirect[lane] && !(target & 3) && target != pc + 4;
                if (predictTaken[lane]) prediction[lane] = target;
#if INDIRECT_ENTRIES > 0
                if (!knownIndirect[lane]) {
                    const auto index = (pc >> 2) % INDIRECT_ENTRIES;
                    if (indirectValid[index] && indirectTag[index] == pc) {
                        const uint64_t saved = indirectTarget[index];
                        predictTaken[lane] = !(saved & 3) && saved != pc + 4;
                        if (predictTaken[lane]) prediction[lane] = saved;
                    }
                }
#endif
            }
        }
#endif
        dut.set_io$$instruction0$$valid(valid0);
        dut.set_io$$instruction1$$valid(valid1);
        dut.set_io$$instruction0$$bits(valid0 ? program[(fetchPc - base) / 4] : 0);
        dut.set_io$$instruction1$$bits(valid1 ? program[(fetchPc + 4 - base) / 4] : 0);
        dut.set_io$$commitEnable(enable);
        dut.set_io$$inspectRegister(inspect);
        ram.drive(dut, cycle, stalled, rng);
        dut.step();
#if REGISTERED_FETCH_PACKET
        stats.slot0HoldAndLane1Progress += bool(dut.get_slot0HoldAndLane1Progress());
        stats.olderLane0BranchResolution += bool(dut.get_olderLane0BranchResolution());
        stats.aluForwardingHits += bool(dut.get_aluForwardingHit());
#endif
        if (finished && dut.get_io$$memoryBusy()) ++drainCycles;
        check(dut.get_io$$issueCount() <= 2, "global two-issue budget exceeded");
        discarded += dut.get_io$$memoryDiscarded();
        forwarded += dut.get_io$$memoryForwarded();
        check(dut.get_io$$fetchPc() == fetchPc, "instruction device supplied the wrong fetch cursor");
        check(dut.get_io$$occupancy() <= ROB_ENTRIES, "program ROB capacity");
        if (!hadRedirect) check(dut.get_io$$occupancy() == fetched - retired, "program ROB occupancy before recovery");
        check(dut.get_io$$committedValue() == architectural[inspect], "program committed PRF value");
        const bool accept0 = dut.get_io$$accepted0(), accept1 = dut.get_io$$accepted1();
        const bool redirect = dut.get_io$$redirect$$valid();
        const bool recovering = dut.get_io$$recovering();
        check(!accept1 || accept0, "accepted non-prefix instruction");
#if !REGISTERED_FETCH_PACKET
        check(!accept0 || valid0, "accepted absent first instruction");
        check(!accept1 || valid1, "accepted absent second instruction");
        check(!accept1 || !predictTaken[0], "accepted instruction after predicted-taken lane zero");
#endif
        uint64_t predictedFetchPc = fetchPc;
        if (accept0) predictedFetchPc = prediction[0];
        if (accept1) predictedFetchPc = prediction[1];
        if (!finished) predictedTaken += (accept0 && predictTaken[0]) + (accept1 && predictTaken[1]);
#if !REGISTERED_FETCH_PACKET
        for (unsigned lane = 0; lane < 2; ++lane) if (lane == 0 ? accept0 : accept1) {
            const uint64_t pc = fetchPc + lane * 4;
            const uint32_t inst = program[(pc - base) / 4];
            previousAuipcRd = (inst >> 7) & 31;
            previousAuipc = (inst & 127) == 0x17 && previousAuipcRd;
            previousAuipcNext = pc + 4;
            if (previousAuipc) previousAuipcValue = pc + immediate(*decode(inst), inst);
            if (!finished && knownIndirect[lane] && predictTaken[lane]) ++knownJalrPredictions;
        }
#endif
        if (!supply) ++stats.supplyStalls;
        if (valid0 && !accept0) ++stats.backendStalls;
        if (valid1 && accept0 && !accept1) ++stats.partialAccepts;
        stats.mulDivConcurrent += bool(dut.get_io$$mulDivConcurrent());
        stats.mulDivMultiCancel += bool(dut.get_io$$mulDivMultiCancel());
        stats.mulDivCancelled += bool(dut.get_io$$mulDivCancelled());
        stats.mulDivOverlap += bool(dut.get_io$$mulDivOverlap());
        stats.mulDivBlocked += bool(dut.get_io$$mulDivBlocked());
        const auto output = commits(dut);
        ram.observe(dut, cycle, architecturalPc, program, architectural);
        if (!finished) {
            ++cycles;
            const unsigned n = unsigned(output[0].valid) + unsigned(output[1].valid);
            zero += n == 0; single += n == 1; dual += n == 2;
            recovery += redirect || recovering;
            blocked += valid0 && !accept0;
            memBusy += bool(dut.get_io$$memoryBusy());
            ++issueCycles[dut.get_io$$issueCount()];
            ++renameCycles[unsigned(accept0) + unsigned(accept1)];
            occupancySum += dut.get_io$$occupancy();
            robFull += dut.get_io$$occupancy() == ROB_ENTRIES;
        }
        check(!output[1].valid || output[0].valid, "commit lane hole");
        check(enable || (!output[0].valid && !output[1].valid), "commit backpressure ignored");
        if (redirect || recovering) {
            check(!accept0 && !accept1 && !output[0].valid, "recovery must block allocation and retirement");
            ++stats.recoveryCycles;
        }
        // Keep the exact steady-state two-wide assertion, allowing only bounded
        // fill time for the explicit fetch and issue/execute register boundaries.
        constexpr unsigned throughputFill = REGISTERED_FETCH_PACKET ? 8 : 4;
        if (performance && PHYSICAL_REGS >= 40 && cycle >= throughputFill && fetchPc + 8 < end) {
            check(accept1 && output[1].valid && !redirect,
                  "machine-code stream lost two-wide throughput cycle=" + std::to_string(cycle) +
                  " pc=" + std::to_string(fetchPc) + " accept1=" + std::to_string(accept1) +
                  " commit1=" + std::to_string(output[1].valid) + " redirect=" + std::to_string(redirect));
            ++stats.performanceCycles;
        }
        if (output[1].valid) ++stats.dualCommits;
        // Queries above see pre-edge training state. Apply the prior retirement
        // packet now; derive events from the independent architectural model.
        if (DELAYED_PREDICTION_TRAINING) {
            for (const auto& event : pendingTraining) train(event);
            pendingTraining.clear();
        }
        for (const auto &c : output) {
            if (!c.valid) continue;
            check(inImage(architecturalPc), "committed outside expected program path");
            const auto inst = program[(architecturalPc - base) / 4];
            const auto *encoding = decode(inst);
            check(encoding != nullptr, "illegal instruction committed");
            const auto &e = *encoding;
            const auto expected = interpret(e, inst, architecturalPc, architectural, architecturalMemory);
            check(!expected.fault, "misaligned control flow committed");
            check(c.pc == architecturalPc && c.instruction == inst && c.rd == expected.rd &&
                  c.writes == (expected.rd != 0) && c.value == expected.result && c.nextPc == expected.nextPc,
                  "ISA software model mismatch at PC " + std::to_string(architecturalPc));
            check(retired == 0 || c.tag > lastCommitTag, "commit token order");
            lastCommitTag = c.tag;
            if (expected.rd) architectural[expected.rd] = c.value;
            if (injectMismatch && retired == 0) architectural[1] ^= 1;
            if (e.memory == 2) {
                const unsigned bytes = 1U << ((inst >> 12) & 3);
                const uint64_t value = architectural[(inst >> 20) & 31];
                ram.retiredStore(expected.target, (inst >> 12) & 3, value);
                for (unsigned b = 0; b < bytes; ++b) architecturalMemory[expected.target - dataBase + b] = value >> (8 * b);
            }
            ref.compare(architectural, expected.nextPc);
            if (e.memory) ref.compareMemory(architecturalMemory);
            const Training event{architecturalPc, expected.nextPc, e.control};
            if (DELAYED_PREDICTION_TRAINING) pendingTraining.push_back(event);
            else train(event);
            architecturalPc = expected.nextPc;
            if (e.control >= 1 && e.control <= 6) { ++stats.branches; stats.takenBranches += expected.taken; }
            if (e.control >= 7) ++stats.jumps;
            ++retired; ++stats.commits;
        }
        fetched += accept0 + accept1;
        if (redirect) {
            previousAuipc = false;
            const auto pc = dut.get_io$$redirect$$bits$$pc();
            check(inImage(pc), "redirect instruction outside image");
            const auto *e = decode(program[(pc - base) / 4]);
            check(e && (e->control || e->memory == 1), "redirect from a non-control/non-load instruction");
            if (!finished && e->control >= 1 && e->control <= 6) ++branchMisses;
            if (!finished && e->control == 7) ++directMisses;
            const auto tag = dut.get_io$$redirect$$bits$$token$$tag();
            if (hadRedirect && tag < lastRedirectTag) {
                ++stats.olderRedirects;
                if (recovering) ++stats.olderDuringRollback;
            }
            lastRedirectTag = tag;
            hadRedirect = true;
            fetchPc = dut.get_io$$redirect$$bits$$target();
            check((fetchPc & 3) == 0, "redirect to misaligned address");
            ++stats.redirects;
        } else fetchPc = predictedFetchPc;
#if REGISTERED_FETCH_PACKET
        // The raw supply cursor is no longer the rename PC. Model the instruction
        // device at the requested address; do not use this DUT signal as an ISA
        // oracle. The independent packet FIFO test verifies capture/flush cursor
        // arithmetic, and every committed instruction/PC/value remains checked
        // against the software ISA model and NEMU above.
        fetchPc = dut.get_nextFetchPc();
        check((fetchPc & 3) == 0, "unaligned raw instruction fetch cursor");
#endif
        const bool exception = dut.get_io$$exception$$valid();
        if (exception) {
            check(inImage(architecturalPc), "unexpected exception outside image");
            const uint32_t inst = program[(architecturalPc - base) / 4];
            const auto *e = decode(inst);
            const auto expected = e ? interpret(*e, inst, architecturalPc, architectural, architecturalMemory) : Expected{};
            check(!e || expected.fault, "exception on a legal aligned instruction");
            check(dut.get_io$$exception$$bits$$pc() == architecturalPc &&
                  dut.get_io$$exception$$bits$$cause() == (e ? expected.cause : 2) &&
                  dut.get_io$$exception$$bits$$tval() == (e ? expected.target : inst), "precise exception event");
            check(!accept0 && !accept1 && !output[0].valid, "exception must stop fetch and retirement");
            if (!dut.get_io$$memoryBusy() && ++drained == 32) {
                ++stats.traps; ++stats.programs; stats.misaligned += bool(e && !e->memory); finish(); return;
            }
        } else if (architecturalPc == end && dut.get_io$$occupancy() == 0 && !dut.get_io$$memoryBusy()) {
            if (++drained == 33) { ++stats.programs; finish(); return; }
        } else drained = 0;
        if (architecturalPc == end) finished = true;
    }
    throw std::runtime_error("program timeout at architectural PC " + std::to_string(architecturalPc));
}
static std::vector<uint32_t> loadBinary(const char *path) {
    std::ifstream file(path, std::ios::binary);
    check(bool(file), "cannot read assembly payload");
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)), {});
    check(!bytes.empty() && bytes.size() % 4 == 0 && bytes.size() <= (1U << 20), "invalid payload size");
    std::vector<uint32_t> words;
    for (size_t i = 0; i < bytes.size(); i += 4)
        words.push_back(uint32_t(bytes[i]) | (uint32_t(bytes[i + 1]) << 8) |
                        (uint32_t(bytes[i + 2]) << 16) | (uint32_t(bytes[i + 3]) << 24));
    return words;
}
static uint32_t branchCode(unsigned funct3, unsigned rs1, unsigned rs2, int offset) {
    check(offset >= -4096 && offset <= 4094 && offset % 2 == 0, "branch generator offset");
    const uint32_t imm = uint32_t(offset) & 8191;
    return ((imm >> 12) << 31) | (((imm >> 5) & 63) << 25) | (rs2 << 20) | (rs1 << 15) |
           (funct3 << 12) | (((imm >> 1) & 15) << 8) | (((imm >> 11) & 1) << 7) | 0x63;
}
static uint32_t jumpCode(unsigned rd, int offset) {
    const uint32_t imm = uint32_t(offset) & 0x1fffff;
    return ((imm >> 20) << 31) | (((imm >> 1) & 1023) << 21) | (((imm >> 11) & 1) << 20) |
           (((imm >> 12) & 255) << 12) | (rd << 7) | 0x6f;
}
static void controlTests(Reference &ref, Stats &stats) {
    // Correct sequential prediction for not-taken branches must preserve full issue/commit throughput.
    programTest(ref, std::vector<uint32_t>(512, branchCode(1, 0, 0, 2)), 0, false, true, false, stats);
    // The first predicted direct jump must truncate the packet before the second jump.
    programTest(ref, {jumpCode(1, 12), jumpCode(2, 16), 0, 0x00700193U, 0x00900213U}, 1, false, false, false, stats);
    // An unpredicted JALR resolves before an older dependent branch; the older redirect must supersede it.
    std::vector<uint32_t> reverse{0x00000317U, 0x05430313U, 0x00000513U}; // x6 = base + 84
    for (unsigned i = 0; i < 12; ++i) reverse.push_back(0x00150513U);
    reverse.push_back(branchCode(0, 10, 10, 60)); // index 15 -> index 30
    reverse.push_back(0x00030067U); // JALR x0,x6: not adjacent to AUIPC
    for (unsigned i = 0; i < 4; ++i) reverse.push_back(0);
    for (unsigned i = 0; i < 8; ++i) reverse.push_back(0x00158593U);
    reverse.push_back(0x00000067U); // speculative jump outside image, killed by older branch
    reverse.push_back(0x02a00613U);
    const auto before = stats.olderRedirects;
    programTest(ref, reverse, 0, false, false, false, stats);
    check(stats.olderRedirects > before, "older branch superseding JALR coverage");
    // A next-PC equal to fall-through needs no recovery, but must write the link register.
    programTest(ref, {jumpCode(1, 4), 0x00108113U}, 1, false, false, false, stats);
    // Exact AUIPC/JALR targets in the same packet and across packets, including stalls,
    // odd-address bit-zero clearing, and rs1 == rd link-register replacement.
    for (unsigned prefix = 0; prefix < 2; ++prefix) {
        for (bool stalled : {false, true}) {
            std::vector<uint32_t> pair(prefix, 0x00000013U);
            pair.insert(pair.end(), {0x00000097U, 0x00d080e7U, 0, 0x00108113U});
            programTest(ref, pair, 0x194 + prefix, stalled, false, false, stats);
        }
    }
    programTest(ref, {0x00000097U, 0x008080e7U, 0x00108113U}, 7, true, false, false, stats);
    // A matching pair with bit one set must still raise a precise alignment fault.
    programTest(ref, {0x00000097U, 0x003080e7U, 0x00100113U}, 8, true, false, false, stats);
    // Adjacent AUIPC writes a different register (or x0): use the real JALR source.
    programTest(ref, {0x00000317U, 0x01430313U, 0x00000097U, 0x000300e7U, 0, 0x00108113U},
                9, true, false, false, stats);
    programTest(ref, {0x00000097U, 0x01408093U, 0x00000017U, 0x000080e7U, 0, 0x00108113U},
                10, true, false, false, stats);
    // IALIGN=32: taken branch/JAL/JALR fault; a not-taken branch ignores the unaligned target.
    programTest(ref, {branchCode(0, 0, 0, 2), 0x00100093U}, 2, true, false, false, stats);
    programTest(ref, {jumpCode(1, 2), 0x00100093U}, 3, true, false, false, stats);
    programTest(ref, {0x00000097U, 0x00308093U, 0x000080e7U, 0x00100113U}, 4, true, false, false, stats);
    programTest(ref, {branchCode(1, 0, 0, 2), 0x00100093U}, 5, true, false, false, stats);
    for (uint64_t seed : {UINT64_C(0x1234), UINT64_C(0x735abc), UINT64_C(0x918eff)}) {
        std::mt19937_64 rng(seed);
        std::vector<uint32_t> code{0x01100093U, 0x00000113U, 0xfff00193U, 0x00100213U};
        const unsigned body = code.size();
        for (unsigned block = 0; block < 24; ++block) {
            for (unsigned i = 0; i < 4; ++i) {
                const auto &e = encodings[rng() % 30];
                uint32_t instruction = (uint32_t(rng()) & ~e.mask) | e.match;
                instruction = (instruction & ~(31U << 7)) | ((8 + rng() % 24) << 7);
                code.push_back(instruction);
            }
            const std::array<unsigned, 6> conditions{0, 1, 4, 5, 6, 7};
            code.push_back(branchCode(conditions[block % 6], 3, 4, 12));
            code.push_back(0x00140413U); // addi x8,x8,1
            code.push_back(0x00148493U); // addi x9,x9,1
            code.push_back(jumpCode(5, 8));
            code.push_back(0); // wrong-path illegal instruction must never become an architectural exception
        }
        code.push_back(0x00110113U); // increment bounded loop counter x2
        code.push_back(branchCode(4, 2, 1, int(body * 4) - int(code.size() * 4)));
        code.push_back(0x02a00513U);
        programTest(ref, code, seed, true, false, false, stats);
    }
}
static uint32_t loadCode(unsigned rd, unsigned rs1, unsigned kind, int offset) {
    return ((uint32_t(offset) & 4095) << 20) | (rs1 << 15) | (kind << 12) | (rd << 7) | 3;
}
static uint32_t storeCode(unsigned rs2, unsigned rs1, unsigned size, int offset) {
    const auto imm = uint32_t(offset) & 4095;
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (size << 12) | ((imm & 31) << 7) | 0x23;
}
static uint32_t addiCode(unsigned rd, unsigned rs, int value) {
    return ((uint32_t(value) & 4095) << 20) | (rs << 15) | (rd << 7) | 0x13;
}
static void memoryTests(Reference &ref, Stats &stats) {
    const uint32_t address = 0x00010097U; // auipc x1,0x10, exactly dataBase at the first PC
    // A long older load keeps the store away from the ROB head. Observe the external
    // load handshake before the store can obtain head permission, independently of SQ state.
    for (bool sameBeat : {false, true}) {
        programTest(ref, {address, loadCode(3, 1, 3, 128), storeCode(0, 1, 0, 0),
                         loadCode(4, 1, 0, sameBeat ? 1 : 16)},
                    0, false, false, false, stats, 40, "", false, -1, 2, sameBeat ? 1 : 16, true);
    }
    // Full and partial byte overlap must wait; a load seeing old RAM would fail the ISA oracle.
    for (unsigned size : {0U, 3U}) {
        programTest(ref, {address, loadCode(3, 1, 3, 128), storeCode(0, 1, size, size == 0 ? 17 : 16),
                         loadCode(4, 1, 3, 16)},
                    0, false, false, false, stats, 40, "", false, -1, 2, 16, false);
    }
    // Store address remains unknown until the long load returns: AND x5,x3,x0; ADD x5,x5,x1.
    programTest(ref, {address, loadCode(3, 1, 3, 128), 0x0001f2b3U, 0x001282b3U,
                     storeCode(0, 5, 3, 16), loadCode(4, 1, 3, 16)},
                0, false, false, false, stats, 40, "", false, -1, 4, 16, false);
    // Irrevocable buffered writes survive younger branch recovery and a precise illegal stop.
    std::vector<uint32_t> buffered{address, addiCode(2, 0, 17)};
    for (unsigned i = 0; i < 12; ++i) {
        buffered.push_back(storeCode(2, 1, i % 4, (i % 8) * 8));
        buffered.push_back(addiCode(2, 2, 1));
    }
    auto redirectBuffer = buffered;
    redirectBuffer.insert(redirectBuffer.end(), {branchCode(0, 0, 0, 8), storeCode(2, 1, 3, 120), loadCode(3, 1, 3, 0)});
    programTest(ref, redirectBuffer, 0x8391, true, false, false, stats, 40);
    buffered.insert(buffered.end(), {0, storeCode(2, 1, 3, 120)});
    programTest(ref, buffered, 0x8392, true, false, false, stats, 40);
    // All byte lanes, load signedness, store widths, store/load dependencies, x0, and negative offsets.
    for (unsigned latency : {0U, 1U, 7U}) {
        std::vector<uint32_t> code{address, addiCode(2, 0, -129)};
        for (unsigned size = 0; size < 4; ++size) {
            for (unsigned lane = 0; lane < 8; lane += 1U << size) {
                code.push_back(storeCode(2, 1, size, 16 + lane));
                code.push_back(loadCode(3, 1, size, 16 + lane));
                if (size < 3) code.push_back(loadCode(4, 1, size + 4, 16 + lane));
                code.push_back(addiCode(2, 3, 1));
            }
        }
        code.push_back(addiCode(5, 1, 32));
        code.push_back(storeCode(2, 5, 3, -8));
        code.push_back(loadCode(0, 5, 3, -8)); // x0 still causes a real memory transaction
        programTest(ref, code, 0x91 + latency, true, false, false, stats, latency);
    }
    for (uint64_t seed : {0x451U, 0x789U, 0xa129U}) {
        std::mt19937_64 rng(seed);
        std::vector<uint32_t> code{address};
        for (unsigned i = 0; i < 1500; ++i) {
            const unsigned size = rng() % 4, offset = (rng() % 256) & ~((1U << size) - 1);
            const unsigned rd = 2 + rng() % 29;
            if (rng() & 1) code.push_back(loadCode(rd, 1, size + ((size < 3 && (rng() & 1)) ? 4 : 0), offset));
            else code.push_back(storeCode(rd, 1, size, offset));
            code.push_back(addiCode(rd, rd, int(rng() % 4096) - 2048));
        }
        programTest(ref, code, seed, true, false, false, stats, 3);
    }
    // Every contained byte footprint and signedness; each pair has its own successful store.
    std::vector<uint32_t> forwarding{address, addiCode(2, 0, -129)};
    unsigned pairs = 0;
    for (unsigned ss = 0; ss < 4; ++ss)
        for (unsigned sl = 0; sl < 8; sl += 1U << ss)
            for (unsigned ls = 0; ls <= ss; ++ls)
                for (unsigned ll = sl; ll < sl + (1U << ss); ll += 1U << ls)
                    for (unsigned sign = 0; sign < (ls == 3 ? 1U : 2U); ++sign) {
                        forwarding.push_back(storeCode(2, 1, ss, 32 + sl));
                        forwarding.push_back(loadCode(3, 1, ls + sign * 4, 32 + ll));
                        ++pairs;
                    }
    programTest(ref, forwarding, 0, false, false, false, stats, 4, "", false, pairs);
    // Partial coverage, disjoint bytes and another beat must fall back to a real RAM read.
    programTest(ref, {address, addiCode(2, 0, -129), storeCode(2, 1, 0, 0), loadCode(3, 1, 1, 0),
                     storeCode(2, 1, 1, 2), loadCode(3, 1, 0, 0),
                     storeCode(2, 1, 3, 0), loadCode(3, 1, 3, 8)},
                0, false, false, false, stats, 4, "", false, 0);
    // Wrong-path store behind a delayed older branch must never reach the memory bus.
    std::vector<uint32_t> wrong{address, addiCode(2, 0, 0)};
    for (unsigned i = 0; i < 12; ++i) wrong.push_back(addiCode(2, 2, 1));
    wrong.push_back(branchCode(0, 2, 2, 8));
    wrong.push_back(storeCode(2, 1, 3, 0));
    wrong.push_back(loadCode(3, 1, 3, 0));
    programTest(ref, wrong, 0x73, true, false, false, stats, 5);
    // A younger redirect while the head memory transaction waits cannot cancel that transaction.
    programTest(ref, {address, loadCode(2, 1, 3, 0), branchCode(0, 0, 0, 8), storeCode(2, 1, 3, 0), addiCode(3, 2, 1)},
                0x51, false, false, false, stats, 12);
    // A late response from a load younger than a delayed taken branch must be drained without writeback.
    for (unsigned latency : {12U, 40U}) {
        std::vector<uint32_t> cancelled{address};
        for (unsigned i = 0; i < 12; ++i) cancelled.push_back(addiCode(2, 2, 1));
        cancelled.push_back(branchCode(0, 2, 2, 8));
        cancelled.push_back(loadCode(3, 1, 3, 0));
        cancelled.push_back(addiCode(3, 0, 42));
        cancelled.push_back(storeCode(3, 1, 3, 8));
        programTest(ref, cancelled, 0, false, false, false, stats, latency, "", true);
    }
    // Misalignment is rejected before a request; access errors return through the memory response.
    for (bool store : {false, true}) {
        for (unsigned size : {1U, 2U, 3U})
            programTest(ref, {address, addiCode(2, 0, 99), store ? storeCode(2, 1, size, 1) : loadCode(0, 1, size, 1),
                             storeCode(2, 1, 0, 32)}, 0x79, true, false, false, stats, 2);
        programTest(ref, {addiCode(1, 0, 0), addiCode(2, 0, 99), store ? storeCode(2, 1, 3, 0) : loadCode(0, 1, 3, 0),
                         addiCode(3, 0, 42)}, 0x81, true, false, false, stats, 5);
    }
}
static uint32_t mulDivCode(unsigned op, bool word, unsigned rd, unsigned rs1, unsigned rs2);
// Bounded machine-code microbenchmarks, using exactly the same independent ISA,
// memory and per-retirement NEMU checks as the functional suite. These are not a
// claim about FPGA frequency, cache bandwidth or a formal CoreMark score.
#ifndef FETCH_HINT_ALIAS_BENCH
#define FETCH_HINT_ALIAS_BENCH 0
#endif
static void throughputBenchmarks(Reference &ref, Stats &stats, const std::vector<uint32_t> &compiled) {
    std::vector<uint32_t> independent, chain, dualChain, notTaken, directJumps;
    for (unsigned i = 0; i < 1024; ++i) {
        independent.push_back(addiCode(1 + i % 16, 0, i));
        chain.push_back(addiCode(1, 1, 1));
        dualChain.push_back(addiCode(1 + i % 2, 1 + i % 2, 1));
    }
    for (unsigned i = 0; i < 128; ++i) {
        notTaken.push_back(branchCode(1, 0, 0, 8));
        notTaken.push_back(addiCode(1 + i % 16, 0, i));
        directJumps.push_back(jumpCode(1, 8));
        directJumps.push_back(0);
    }
    programTest(ref, independent, 0, false, false, false, stats, 1, "throughput_independent_alu");
    programTest(ref, chain, 0, false, false, false, stats, 1, "throughput_dependent_alu");
    programTest(ref, dualChain, 0, false, false, false, stats, 1, "throughput_dual_dependency");
    programTest(ref, notTaken, 0, false, false, false, stats, 1, "throughput_not_taken_mixed");
    programTest(ref, directJumps, 0, false, false, false, stats, 1, "throughput_direct_jumps");
    programTest(ref, {addiCode(1, 0, 0), addiCode(2, 0, 128), addiCode(1, 1, 1),
                     branchCode(4, 1, 2, -4)},
                0, false, false, false, stats, 1, "throughput_taken_loop");
#if FETCH_HINT_ALIAS_BENCH
    // 17 taken conditional sites, 64 bytes apart: an explicit capacity/conflict
    // workload, not a general CoreMark speed claim. Same binary in both profiles.
    std::vector<uint32_t> aliasLoop{addiCode(1, 0, 1), addiCode(2, 0, 32)};
    for (unsigned site = 0; site < 17; ++site) {
        aliasLoop.push_back(addiCode(3 + site % 8, 3 + site % 8, 1));
        aliasLoop.push_back(addiCode(12 + site % 8, 12 + site % 8, 1));
        aliasLoop.push_back(branchCode(1, 1, 0, 56));
        for (unsigned padding = 0; padding < 13; ++padding) aliasLoop.push_back(0);
    }
    aliasLoop.push_back(addiCode(2, 2, -1));
    aliasLoop.push_back(branchCode(1, 2, 0, -int(17 * 64 + 4)));
    programTest(ref, aliasLoop, 0, false, false, false, stats, 1, "throughput_hint_alias_loop");
#endif
    for (unsigned latency : {1U, 12U}) {
        std::vector<uint32_t> loadUse{0x00010097U}, mixed{0x00010097U};
        for (unsigned i = 0; i < 64; ++i) {
            loadUse.push_back(loadCode(2, 1, 3, i * 8));
            loadUse.push_back(addiCode(3, 2, 1));
            mixed.push_back(loadCode(2, 1, 3, i * 8));
            mixed.push_back(addiCode(4 + i % 8, 0, i));
            mixed.push_back(addiCode(3, 2, 1));
            mixed.push_back(storeCode(3, 1, 3, 1024 + i * 8));
        }
#if SERIAL_LOAD_ALU_BENCH
        std::vector<uint32_t> serialLoadAlu{0x00010097U};
        for (unsigned i = 0; i < 128; ++i) {
            serialLoadAlu.push_back(loadCode(2, 1, 3, 0));
            serialLoadAlu.push_back(addiCode(1, 2, 8));
        }
        programTest(ref, serialLoadAlu, 0, false, false, false, stats, latency,
                    "throughput_serial_load_alu_address");
#endif
        programTest(ref, loadUse, 0, false, false, false, stats, latency, "throughput_load_use");
        programTest(ref, mixed, 0, false, false, false, stats, latency, "throughput_memory_alu_mix");
        programTest(ref, compiled, 0, false, false, false, stats, latency, "throughput_compiled_sum");
    }
    constexpr unsigned expectedPrograms = 12 + (FETCH_HINT_ALIAS_BENCH ? 1 : 0)
#if SERIAL_LOAD_ALU_BENCH
        + 2
#endif
        ;
    check(stats.programs == expectedPrograms && stats.commits > 4000 && stats.dualCommits > 0,
          "short throughput coverage incomplete");
    std::cout << "GSIM short two-issue throughput + NEMU: PASS programs=" << stats.programs
              << " commits=" << stats.commits << " dualCommitCycles=" << stats.dualCommits << '\n';
}

// Exercise the ownership corner introduced by independent elastic slots:
// completion arbitration can retain an older lane-0 branch while lane 1 drains
// and admits a younger branch. Every instruction, data value, precise exception
// and RAM effect still uses programTest's independent ISA + NEMU oracles.
static void pipelineRecoveryTests(Reference &ref, Stats &stats) {
#if REGISTERED_FETCH_PACKET
    std::vector<uint32_t> forwarding;
    for (unsigned i = 0; i < 128; ++i) {
        forwarding.push_back(addiCode(3, 3, 1));
        forwarding.push_back(addiCode(4, 4, 1));
    }
    programTest(ref, forwarding, 0x681, false, true, false, stats);
    check(stats.aluForwardingHits > 0, "ordinary ALU promise never entered a dependent execution slot");

    unsigned contentionPrograms = 0;
    // Sweep the returning-load phase, not internal DUT state, so both owners
    // must arise from ordinary decoded machine instructions and actual grants.
    // Stop only after the hard coverage witnesses have all occurred.
    for (unsigned latency = 1; latency <= 24; ++latency) {
        for (unsigned padding = 0; padding < 16; ++padding) {
            std::vector<uint32_t> code{0x00010097U, loadCode(2, 1, 3, 128)};
            for (unsigned i = 0; i < padding; ++i) code.push_back(addiCode(8 + i % 8, 0, i));
            code.push_back(addiCode(6, 0, 1));
            code.push_back(branchCode(0, 0, 0, 16));
            code.push_back(branchCode(0, 0, 0, 8));
            code.push_back(addiCode(6, 0, 99));
            code.push_back(addiCode(7, 0, 77));
            code.push_back(addiCode(5, 0, 42));
            programTest(ref, code, 0x682 + padding, false, false, false, stats, latency);
            ++contentionPrograms;
            if (stats.slot0HoldAndLane1Progress && stats.olderLane0BranchResolution) break;
        }
        if (stats.slot0HoldAndLane1Progress && stats.olderLane0BranchResolution) break;
    }
    check(stats.slot0HoldAndLane1Progress > 0,
          "LSU writeback never held slot 0 while independent lane 1 made progress");
    check(stats.olderLane0BranchResolution > 0,
          "simultaneous branch resolutions never selected an actual older lane-0 owner");

    // Preserve load/branch cancellation, completion contention and retirement
    // backpressure in a bounded program that can revisit fresh ROB owners.
    for (uint64_t seed : {UINT64_C(0x683), UINT64_C(0x684)}) {
        programTest(ref, {0x00010097U, loadCode(2, 1, 3, 128), branchCode(0, 2, 2, 16),
                         addiCode(3, 2, 1), loadCode(4, 1, 3, 256), addiCode(5, 4, 1),
                         addiCode(6, 2, 42), storeCode(6, 1, 3, 512), loadCode(7, 1, 3, 512)},
                    seed, true, false, false, stats, 12);
    }
    check(stats.programs >= 4 && stats.commits > 256 && stats.redirects > 0 &&
          stats.loads > 0 && stats.stores > 0 && stats.supplyStalls > 0,
          "pipeline recovery architectural coverage incomplete");
    std::cout << "GSIM pipeline recovery + NEMU: PASS programs=" << stats.programs
              << " contentionPrograms=" << contentionPrograms << " commits=" << stats.commits
              << " slot0HeldLane1Progress=" << stats.slot0HoldAndLane1Progress
              << " olderLane0BranchResolution=" << stats.olderLane0BranchResolution
              << " aluForwardingHits=" << stats.aluForwardingHits
              << " redirects=" << stats.redirects << '\n';
#else
    throw std::runtime_error("pipeline recovery mode requires the registered execution/fetch candidate");
#endif
}

static void ipcBenchmarks(Reference &ref, Stats &stats, const std::vector<uint32_t> &compiled) {
    for (unsigned kind=0;kind<4;++kind) {
        std::vector<uint32_t> code{addiCode(1,0,127),addiCode(2,0,1)};
        for (unsigned i=0;i<128;++i)
            code.push_back(mulDivCode(kind<2 ? 0 : 4, kind==3, kind==1 ? 1 : 3+i%16, 1, 2));
        const std::array<const char*,4> names{"rv64m_independent_mul","rv64m_dependent_mul","rv64m_div64","rv64m_div32"};
        programTest(ref,code,0,false,false,false,stats,1,names[kind]);
    }
    for (unsigned kind = 0; kind < 4; ++kind) {
        std::vector<uint32_t> code{addiCode(1,0,-127)};
        for (unsigned i = 0; i < 2048; ++i) {
            const unsigned rd = kind % 2 ? 1 : 3 + i % 16;
            code.push_back((kind < 2 ? 0x60705013U : 0x60001013U) | (1U << 15) | (rd << 7));
        }
        const std::array<const char*,4> names{"rv64b_independent_rori", "rv64b_dependent_rori",
            "rv64b_independent_clz", "rv64b_dependent_clz"};
        programTest(ref,code,0,false,false,false,stats,1,names[kind]);
    }
    std::vector<uint32_t> independent, chain;
    for (unsigned i = 0; i < 4096; ++i) {
        independent.push_back(addiCode(1 + i % 16, 0, i % 2048));
        chain.push_back(addiCode(1, 1, 1));
    }
    std::vector<uint32_t> directJumps;
    for (unsigned i = 0; i < 512; ++i) { directJumps.push_back(jumpCode(1, 8)); directJumps.push_back(0); }
    programTest(ref, directJumps, 0, false, false, false, stats, 1, "direct_jump_chain");
    programTest(ref, independent, 0, false, false, false, stats, 1, "independent_alu");
    programTest(ref, chain, 0, false, false, false, stats, 1, "dependent_alu");
    programTest(ref, std::vector<uint32_t>(4096, branchCode(1, 0, 0, 2)), 0, false, false, false, stats, 1, "not_taken_branch");
    programTest(ref, {addiCode(1, 0, 0), addiCode(2, 0, 512), addiCode(1, 1, 1), branchCode(4, 1, 2, -4)},
                0, false, false, false, stats, 1, "taken_branch_loop");
    for (unsigned latency : {1U, 4U, 12U}) {
        std::vector<uint32_t> loads{0x00010097U};
        for (unsigned i = 0; i < 256; ++i) loads.push_back(loadCode(2 + i % 16, 1, 3, (i % 128) * 8));
        programTest(ref, loads, 0, false, false, false, stats, latency, "independent_loads");
        // Same-address store/load chain with a dependent integer update.
        std::vector<uint32_t> memory{0x00010097U};
        for (unsigned i = 0; i < 256; ++i) {
            memory.push_back(storeCode(2, 1, 3, 0));
            memory.push_back(loadCode(2, 1, 3, 0));
            memory.push_back(addiCode(2, 2, 1));
        }
        programTest(ref, memory, 0, false, false, false, stats, latency, "store_load_chain");
        programTest(ref, compiled, 0, false, false, false, stats, latency, "compiled_c_array_sum");
    }
    // DIVU delays the older load address; independent younger loads can hide RAM latency.
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 3, 0), loadCode(6, 1, 3, 8), loadCode(7, 1, 3, 16),
                     loadCode(8, 1, 3, 24), loadCode(9, 1, 3, 32)},
                0, false, false, false, stats, 40, "ready_load_bypass");
    // The younger same-address load sees the old value, then DMA writes a new value before DIVU
    // resolves the older load address. In-order retirement must return the new value twice.
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 3, 0), loadCode(6, 1, 3, 0)},
                0, false, false, false, stats, 12, "same_address_dma_replay");
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 3, 0), loadCode(6, 1, 3, 0)},
                0, false, false, false, stats, 0, "same_address_dma_replay_zero");
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 2, 4), loadCode(6, 1, 3, 0)},
                0, false, false, false, stats, 12, "overlap_dma_replay");
}

// Bounded capacity proof: reuse the independent architectural/request oracles and
// the exact existing IPC memory stimuli, without the unrelated ALU/M/B suite.
static void memoryCapacityTests(Reference &ref, Stats &stats) {
    for (unsigned latency : {1U, 12U}) {
        std::vector<uint32_t> loads{0x00010097U};
        for (unsigned i = 0; i < 256; ++i) loads.push_back(loadCode(2 + i % 16, 1, 3, (i % 128) * 8));
        programTest(ref, loads, 0, false, false, false, stats, latency, "independent_loads");
    }
    // DIVU delays the older load address; independent younger loads can hide RAM latency.
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 3, 0), loadCode(6, 1, 3, 8), loadCode(7, 1, 3, 16),
                     loadCode(8, 1, 3, 24), loadCode(9, 1, 3, 32)},
                0, false, false, false, stats, 40, "ready_load_bypass");
    // The younger same-address load sees the old value, then DMA writes a new value before DIVU
    // resolves the older load address. In-order retirement must return the new value twice.
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 3, 0), loadCode(6, 1, 3, 0)},
                0, false, false, false, stats, 12, "same_address_dma_replay");
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 3, 0), loadCode(6, 1, 3, 0)},
                0, false, false, false, stats, 0, "same_address_dma_replay_zero");
    programTest(ref, {0x00010097U, addiCode(2, 0, 1), mulDivCode(5, false, 5, 1, 2),
                     loadCode(4, 5, 2, 4), loadCode(6, 1, 3, 0)},
                0, false, false, false, stats, 12, "overlap_dma_replay");
    std::cout << "GSIM memory capacity + NEMU: PASS slots=" << MEMORY_ENTRIES
              << " programs=" << stats.programs << " commits=" << stats.commits << '\n';
}

static uint32_t czeroCode(bool nez, unsigned rd, unsigned rs1, unsigned rs2) {
    return (nez ? 0x0e007033U : 0x0e005033U) | (rd << 7) | (rs1 << 15) | (rs2 << 20);
}
static void zicondTests(Reference &ref, Stats &stats) {
    // Reinitialize before each alias combination, covering zero and upper-bit-only conditions.
    std::vector<uint32_t> aliases;
    for (bool nez : {false, true})
        for (unsigned rd : {0U, 1U, 2U, 3U})
            for (unsigned rs1 : {0U, 1U, 2U, 3U})
                for (unsigned rs2 : {0U, 1U, 2U, 3U}) {
                    aliases.push_back(addiCode(1, 0, -1));
                    aliases.push_back(addiCode(2, 0, 1));
                    aliases.push_back(0x03f11113U); // slli x2,x2,63
                    aliases.push_back(addiCode(3, 0, 0));
                    aliases.push_back(czeroCode(nez, rd, rs1, rs2));
                }
    programTest(ref, aliases, 0x231, false, false, false, stats);
    programTest(ref, aliases, 0x232, true, false, false, stats);
    std::vector<uint32_t> independent;
    for (unsigned i = 0; i < 512; ++i) independent.push_back(czeroCode(i & 1, 1 + i % 2, 0, 0));
    programTest(ref, independent, 0, false, true, false, stats);
    for (uint64_t seed : {UINT64_C(17), UINT64_C(8191)}) {
        std::mt19937_64 rng(seed);
        std::vector<uint32_t> code;
        for (unsigned i = 0; i < 2048; ++i) {
            if (i % 4 == 0) code.push_back(addiCode(1 + rng() % 31, 0, int(rng() % 4096) - 2048));
            else code.push_back(czeroCode(rng() & 1, rng() % 32, rng() % 32, rng() % 32));
        }
        programTest(ref, code, seed, true, false, false, stats);
    }
    std::cout << "GSIM Zicond + NEMU: PASS programs=5 aliasCases=128 randomInstructions=4096 dualIssue=checked\n";
}
static uint32_t mulDivCode(unsigned op, bool word, unsigned rd, unsigned rs1, unsigned rs2) {
    return 0x02000033U | (word ? 8U : 0U) | (op << 12) | (rd << 7) | (rs1 << 15) | (rs2 << 20);
}
static void constant(std::vector<uint32_t> &code, unsigned rd, uint64_t value) {
    code.push_back(addiCode(rd, 0, value >> 56));
    for (int bit = 48; bit >= 0; bit -= 8) {
        code.push_back((8U << 20) | (rd << 15) | (1U << 12) | (rd << 7) | 0x13);
        code.push_back(addiCode(rd, rd, (value >> bit) & 255));
    }
}
static uint32_t bitCode(const Encoding &e, unsigned rd, unsigned rs1, unsigned rs2, unsigned index) {
    const uint32_t variable = (rd << 7) | (rs1 << 15) | ((e.immediate ? index : rs2) << 20);
    return e.match | (variable & ~e.mask);
}
static void bitTests(Reference &ref, Stats &stats) {
    const std::array<uint64_t, 16> edges{0, 1, UINT64_MAX, UINT64_C(0x8000000000000000),
        UINT64_C(0x7fffffffffffffff), UINT64_C(0x80000000), UINT64_C(0xffffffff),
        UINT64_C(0xdeadbeef80000000), 0x80, 0x8000, 0xff, 0xffff,
        UINT64_C(0x010080000001ff00), UINT64_C(0xaaaaaaaaaaaaaaaa),
        UINT64_C(0x5555555555555555), UINT64_C(0xffffffff00000000)};
    std::mt19937_64 rng(0xb0100);
    unsigned operations = 0;
    for (const auto &e : encodings) {
        if (e.alu < 16) continue;
        ++operations;
        // Three bounded images per encoding, below the data-RAM address range.
        for (unsigned group = 0; group < 3; ++group) {
            std::vector<uint32_t> code;
            for (unsigned i = 0; i < 64; ++i) {
                const uint64_t a = group == 0 ? edges[i / 4] : group == 1 ? UINT64_C(1) << i : rng();
                const uint64_t b = group == 0 ? edges[(i % 4) * 4 + (i / 16)] : group == 1 ? 64 + i : rng();
                constant(code, 1, a); constant(code, 2, b);
                code.push_back(bitCode(e, 3, 1, 2, i));
                code.push_back(bitCode(e, 0, 1, 2, i));
                code.push_back(bitCode(e, 1, 1, 2, i));
                code.push_back(bitCode(e, 2, 1, 2, i));
                code.push_back(addiCode(4, 3, 1));
            }
            programTest(ref, code, 0xb100 + group, true, false, false, stats);
        }
        // Older load/divide contend with B completion; taken branch discards dependent B writes.
        std::vector<uint32_t> recovery{0x00010097U, loadCode(2,1,3,0),
            mulDivCode(4,false,6,2,0), bitCode(e,3,2,2,63), branchCode(0,6,6,12),
            bitCode(e,3,3,2,31), bitCode(e,2,3,2,32), addiCode(4,3,1)};
        programTest(ref, recovery, 0, false, false, false, stats, 5);
    }
    check(operations == 40, "B encoding coverage");
    // Mixed dependency chains and source/destination register zero across all B encodings.
    std::vector<uint32_t> mixed;
    for (unsigned i = 0; i < 3000; ++i) {
        const auto &e = encodings[64 + rng() % 40];
        mixed.push_back(addiCode(1 + rng() % 31, 0, int(rng() % 4096) - 2048));
        mixed.push_back(bitCode(e, rng() % 32, rng() % 32, rng() % 32, rng() % 64));
    }
    programTest(ref, mixed, 0xb201, true, false, false, stats);
    std::cout << "GSIM RV64B + NEMU: PASS encodings=40 operandPairs=7680 randomB=3000 recoveryPrograms=40\n";
}
static void mulDivTests(Reference &ref, Stats &stats) {
    const std::array<uint64_t, 8> values{0,1,UINT64_MAX,UINT64_C(0x8000000000000000),UINT64_C(0x7fffffffffffffff),
        UINT64_C(0x80000000),UINT64_C(0xffffffff),UINT64_C(0xdeadbeef80000000)};
    for (bool word : {false,true}) for (unsigned op=0; op<8; ++op) {
        if (word && op>0 && op<4) continue;
        std::vector<uint32_t> boundaries;
        for (auto a : values) for (auto b : values) {
            constant(boundaries, 1, a); constant(boundaries, 2, b);
            boundaries.push_back(mulDivCode(op,word,3,1,2));
            boundaries.push_back(mulDivCode(op,word,1,1,2)); // destination aliases source
            boundaries.push_back(mulDivCode(op,word,2,1,2));
            boundaries.push_back(mulDivCode(op,word,0,1,2));
        }
        programTest(ref,boundaries,0x640,true,false,false,stats);
    }
    std::mt19937_64 rng(0x640);
    std::vector<uint32_t> random;
    for (unsigned i=0; i<1000; ++i) {
        unsigned op=rng()%8; bool word=rng()&1;
        if (word && op>0 && op<4) op=0;
        random.push_back(addiCode(1+rng()%31,0,int(rng()%4096)-2048));
        random.push_back(mulDivCode(op,word,rng()%32,rng()%32,rng()%32));
    }
    programTest(ref,random,0x641,true,false,false,stats);
    // A long older dependency delays branch resolution while a younger divide starts.
    auto cancelled=stats.mulDivCancelled;
    std::vector<uint32_t> wrong;
    for (unsigned i=0;i<12;++i) wrong.push_back(addiCode(10,10,1));
    wrong.push_back(branchCode(0,10,10,12));
    wrong.push_back(mulDivCode(4,false,5,0,0));
    wrong.push_back(addiCode(5,5,1));
    wrong.push_back(mulDivCode(0,false,5,10,10));
    wrong.push_back(addiCode(6,5,1));
    programTest(ref,wrong,0,false,false,false,stats);
    check(stats.mulDivCancelled>cancelled,"branch did not cancel an active M operation");
    // An older M result must survive a younger taken branch and rollback.
    programTest(ref,{addiCode(1,0,-7),addiCode(2,0,3),mulDivCode(4,false,3,1,2),
        branchCode(0,0,0,8),addiCode(3,0,99),addiCode(4,3,1)},0,false,false,false,stats);
    // Sweep response timing so LSU and arithmetic contend for their shared completion port.
    for (unsigned latency=1;latency<=12;++latency) {
        programTest(ref,{0x00010097U,loadCode(2,1,3,0),mulDivCode(0,false,3,0,0),
            addiCode(4,3,1),storeCode(4,1,3,8),loadCode(5,1,3,8)},0,false,false,false,stats,latency);
    }
    // A slow load delays a branch while several independent wrong-path multiplies enter the pipeline.
    auto multiCancel = stats.mulDivMultiCancel;
    std::vector<uint32_t> pipelineKill{0x00010097U,loadCode(2,1,3,0),branchCode(0,2,2,28)};
    for(unsigned i=0;i<6;++i) pipelineKill.push_back(mulDivCode(i%4,false,0,0,0));
    for(unsigned i=0;i<24;++i) pipelineKill.push_back(mulDivCode(i%4,false,3+i%8,2,2));
    programTest(ref,pipelineKill,0,false,false,false,stats,4);
    // The registered redirect gives wrong-path multiplies an extra cycle to complete.
    // NEMU still checks the architectural stream; simultaneous live cancellations are
    // a microarchitectural coverage requirement only for the unregistered schedule.
    if (!REGISTERED_BRANCH_REDIRECT)
        check(stats.mulDivMultiCancel>multiCancel,"redirect did not cancel multiple active multiplies");
    // Older multiply must survive a younger branch; no global flush of the result queue.
    programTest(ref,{addiCode(1,0,-7),addiCode(2,0,3),mulDivCode(0,false,3,1,2),
        branchCode(0,0,0,8),addiCode(3,0,99),addiCode(4,3,1)},0,false,false,false,stats);
    check(stats.mulDivConcurrent>0,"independent multiplication never overlapped division");
    check(stats.mulDivOverlap>0 && (FAST_HEAD_LOAD || stats.mulDivBlocked>0),
          "M overlap/completion arbitration coverage");
    std::cout << "GSIM RV64M + NEMU: PASS cancelled=" << stats.mulDivCancelled << " aluOverlap=" << stats.mulDivOverlap
              << " completionBlocked=" << stats.mulDivBlocked << " multiplyDivideOverlap=" << stats.mulDivConcurrent
              << " multiCancel=" << stats.mulDivMultiCancel << " boundaryPairs=832 randomM=1000\n";
}
int main(int argc, char **argv) {
    try {
        check(argc == 5 || argc == 6, "usage: run NEMU.so integer.bin branch.bin bare.bin [--inject-mismatch|--ipc|--timing-smoke|--throughput-short|--pipeline-recovery|--memory-capacity]");
        const bool inject = argc == 6 && std::string(argv[5]) == "--inject-mismatch";
        const bool ipcOnly = argc == 6 && std::string(argv[5]) == "--ipc";
        const bool timingSmoke = argc == 6 && std::string(argv[5]) == "--timing-smoke";
        const bool throughputOnly = argc == 6 && std::string(argv[5]) == "--throughput-short";
        const bool memoryCapacity = argc == 6 && std::string(argv[5]) == "--memory-capacity";
        const bool pipelineRecovery = argc == 6 && std::string(argv[5]) == "--pipeline-recovery";
        check(argc == 5 || inject || ipcOnly || timingSmoke || throughputOnly || pipelineRecovery || memoryCapacity, "unknown mode");
        const auto decodeCount = (inject || ipcOnly || timingSmoke || throughputOnly || pipelineRecovery || memoryCapacity) ? 0 : decoderTests();
        Reference ref(argv[1]);
        Stats stats;
        const auto compiled = loadBinary(argv[4]);
        if (memoryCapacity) { memoryCapacityTests(ref, stats); return 0; }
        if (ipcOnly) { ipcBenchmarks(ref, stats, compiled); return 0; }
        if (throughputOnly) { throughputBenchmarks(ref, stats, compiled); return 0; }
        if (pipelineRecovery) { pipelineRecoveryTests(ref, stats); return 0; }
        programTest(ref, loadBinary(argv[2]), 0x459, true, false, inject, stats);
        check(!inject, "injected mismatch was not detected");
        programTest(ref, loadBinary(argv[3]), 0x987, false, false, false, stats);
        programTest(ref, loadBinary(argv[3]), 0x988, true, false, false, stats);
        controlTests(ref, stats);
        memoryTests(ref, stats);
        if (timingSmoke) {
            programTest(ref, compiled, 0x419, true, false, false, stats, 5);
            check(stats.loads > 2000 && stats.stores > 2000 && stats.memoryErrors == 2 &&
                stats.memoryBackpressure > 100 && stats.branches > 100 && stats.redirects > 100 &&
                stats.dualCommits > 100, "timing smoke coverage incomplete");
            std::cout << "GSIM control/memory timing + NEMU: PASS rob=" << ROB_ENTRIES
                << " physical=" << PHYSICAL_REGS << " slots=" << MEMORY_ENTRIES
                << " predictor=" << BRANCH_ENTRIES << " trainingDelay=" << DELAYED_PREDICTION_TRAINING
                << " programs=" << stats.programs << " commits=" << stats.commits
                << " loads=" << stats.loads << " stores=" << stats.stores
                << " redirects=" << stats.redirects << " branches=" << stats.branches << '\n';
            return 0;
        }
        zicondTests(ref, stats);
        mulDivTests(ref, stats);
        bitTests(ref, stats);
        programTest(ref, compiled, 0x419, true, false, false, stats, 5);
        ipcBenchmarks(ref, stats, compiled);
        for (uint64_t seed : {UINT64_C(0x5321), UINT64_C(0xabcdef), UINT64_C(0x918af)}) {
            std::mt19937_64 rng(seed);
            std::vector<uint32_t> program;
            // Original thirty integer encodings; M and Zicond have separate randomized suites.
            for (unsigned i = 0; i < 6000; ++i) {
                const auto &e = encodings[i < 30 ? i : rng() % 30];
                program.push_back((uint32_t(rng()) & ~e.mask) | e.match);
            }
            programTest(ref, program, seed, true, false, false, stats);
        }
        std::vector<uint32_t> independent;
        for (unsigned i = 0; i < 512; ++i) independent.push_back(((i & 2047U) << 20) | (((i % 2) + 1) << 7) | 0x13);
        programTest(ref, independent, 1, false, true, false, stats);
        for (uint32_t illegal : {0U, 0xffffffffU, 0x0200101bU, 0x0200103bU, 0x00007003U, 0x00001067U}) {
            // Reserved M word/reserved load/reserved JALR instructions are rejected by this subset; these are not claimed illegal RV64I.
            std::vector<uint32_t> program{0xfff00093U, 0x00108113U, 0x00110193U, illegal, 0x12300113U, 0x12300193U};
            programTest(ref, program, illegal, true, false, false, stats);
        }
        check(stats.loads > 2000 && stats.stores > 2000 && stats.memoryErrors == 2 && stats.memoryBackpressure > 100, "memory coverage thresholds");
        check(stats.dualCommits > 100 && stats.supplyStalls && stats.backendStalls && stats.traps == 19 && stats.misaligned == 4 && stats.redirects > 100 && stats.branches > 100 && stats.olderRedirects > 0,
              "program coverage thresholds: dual=" + std::to_string(stats.dualCommits) +
              " supply=" + std::to_string(stats.supplyStalls) + " backend=" + std::to_string(stats.backendStalls) +
              " traps=" + std::to_string(stats.traps) + " misaligned=" + std::to_string(stats.misaligned) +
              " redirects=" + std::to_string(stats.redirects) + " branches=" + std::to_string(stats.branches) +
              " olderRedirects=" + std::to_string(stats.olderRedirects));
        if (PHYSICAL_REGS == 36) check(stats.partialAccepts > 100, "partial fetch acceptance coverage");
        if (PHYSICAL_REGS >= 40) check(stats.performanceCycles >= 200, "two-wide program performance coverage");
        std::cout << "GSIM IntegerCore + NEMU: PASS rob=" << ROB_ENTRIES << " physical=" << PHYSICAL_REGS
                  << " decoderCases=" << decodeCount << " programs=" << stats.programs
                  << " earlyDisjointLoads=" << stats.earlyDisjointLoads
                  << " commits=" << stats.commits << " dualCommits=" << stats.dualCommits
                  << " partialAccepts=" << stats.partialAccepts << " supplyStalls=" << stats.supplyStalls
                  << " backendStalls=" << stats.backendStalls << " traps=" << stats.traps
                  << " redirects=" << stats.redirects << " recoveryCycles=" << stats.recoveryCycles
                  << " branches=" << stats.branches << " takenBranches=" << stats.takenBranches
                  << " jumps=" << stats.jumps << " olderRedirects=" << stats.olderRedirects
                  << " forwarded=" << stats.forwarded << " loads=" << stats.loads << " stores=" << stats.stores << " memoryErrors=" << stats.memoryErrors
                  << " memoryBackpressure=" << stats.memoryBackpressure
                  << " olderDuringRollback=" << stats.olderDuringRollback << " misaligned=" << stats.misaligned << " twoWideCycles=" << stats.performanceCycles << " randomInstructions=18000 seeds=3\n";
    } catch (const std::exception &error) {
        std::cerr << "GSIM IntegerCore: FAIL " << error.what() << '\n';
        return 1;
    }
}
