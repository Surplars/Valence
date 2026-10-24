// Actual CommonA1 tile, raw instruction TileLink service, independent retirement
// oracle. No generated-model header is needed for the software-only self-test.
#ifndef A1_COMMON_ORACLE_ONLY
#include "CommonA1CpuRetirementGsim.h"
#include "gsim_model_storage.h"
#endif
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

namespace {
constexpr uint64_t romBase = UINT64_C(0x80000000), ramBase = UINT64_C(0x80200000);
constexpr uint64_t romBytes = 128 * 1024, ramWindowBytes = 128 * 1024;
constexpr uint32_t nop = 0x00000013, ebreak = 0x00100073;
[[maybe_unused]] constexpr unsigned maxCycles = 30000;
constexpr unsigned serviceLatency = 3, maxTransactions = 16;
// isa_model.h is reused unchanged. Data-memory instructions are forbidden below.
constexpr uint64_t dataBase = ramBase + 0x100000;
using Memory = std::array<uint8_t, 4096>;
#include "isa_model.h"

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
std::string hex(uint64_t value) {
    std::ostringstream out; out << "0x" << std::hex << value; return out.str();
}
uint32_t imm(unsigned rd, unsigned rs, int value, unsigned function = 0) {
    return (uint32_t(value) & 0xfff) << 20 | rs << 15 | function << 12 | rd << 7 | 0x13;
}
uint32_t reg(unsigned rd, unsigned a, unsigned b, unsigned function = 0) {
    return b << 20 | a << 15 | function << 12 | rd << 7 | 0x33;
}
uint32_t branch(unsigned a, unsigned b, int offset, unsigned function) {
    const uint32_t value = uint32_t(offset) & 0x1fff;
    return ((value >> 12) & 1) << 31 | ((value >> 5) & 63) << 25 | b << 20 | a << 15 |
        function << 12 | ((value >> 1) & 15) << 8 | ((value >> 11) & 1) << 7 | 0x63;
}
struct Program {
    std::string name, placement;
    std::vector<uint32_t> code, boot;
    uint64_t base() const { return placement == "rom" ? romBase : ramBase; }
    unsigned bootstrapInstructions() const { return unsigned(boot.size()); }
    bool architectural(uint64_t pc) const {
        return !(pc & 3) && ((pc >= base() && (pc - base()) / 4 < code.size()) ||
            (pc >= romBase && (pc - romBase) / 4 < boot.size()));
    }
    bool mapped(uint64_t address, uint64_t bytes) const {
        return bytes && ((address >= romBase && address - romBase <= romBytes - bytes) ||
            (address >= ramBase && address - ramBase <= ramWindowBytes - bytes));
    }
    uint32_t word(uint64_t pc) const {
        require(!(pc & 3) && mapped(pc, 4), "program read outside declared instruction windows: " + hex(pc));
        if (pc >= base() && (pc - base()) / 4 < code.size()) return code.at((pc - base()) / 4);
        if (pc >= romBase && (pc - romBase) / 4 < boot.size()) return boot.at((pc - romBase) / 4);
        // Defined NOPs cover speculative post-terminal/branch-path reads. They
        // are fixture bytes, never synthesized from DUT PCs or decoded values.
        return nop;
    }
    uint64_t beat(uint64_t address) const {
        require(!(address & 7), "unaligned physical beat read");
        return uint64_t(word(address)) | uint64_t(word(address + 4)) << 32;
    }
};
std::vector<Program> programs() {
    std::vector<Program> result;
    for (const std::string placement : {"rom", "ram"}) {
        auto make = [&](const std::string &name) {
            Program out{name, placement, {}, {}};
            // AUIPC uses a positive PC-relative offset, avoiding RV64 LUI's
            // sign-extended 0xffffffff80200000 address. Both bootstrap retires
            // are checked, and are excluded only from separately named ROI IPC.
            if (placement == "ram") out.boot = {0x00200f97, 0x000f8067};
            return out;
        };
        Program independent = make("independent_alu");
        independent.code = {imm(25, 0, 17), imm(26, 0, 29)};
        for (unsigned i = 0; i < 480; ++i) {
            const unsigned rd = 1 + i % 24;
            independent.code.push_back(i % 3 == 0 ? reg(rd, 25, 26) :
                i % 3 == 1 ? imm(rd, 0, int(i) - 240) : reg(rd, 25, 26, 4));
        }
        independent.code.push_back(ebreak); result.push_back(independent);
        Program dependent = make("dependent_chain");
        dependent.code.push_back(imm(1, 0, 1));
        for (unsigned i = 0; i < 480; ++i)
            dependent.code.push_back(i % 2 ? imm(1, 1, int(i & 127), 4) : imm(1, 1, 7));
        dependent.code.push_back(ebreak); result.push_back(dependent);
        Program branches = make("branches");
        branches.code = {imm(1, 0, 64), imm(2, 0, 0), imm(3, 0, 0), imm(4, 0, 0),
            imm(2, 2, 3), reg(3, 3, 2, 4), branch(2, 0, 8, 1),
            imm(30, 30, 1), // Always skipped: catches wrong-path retirement.
            branch(2, 0, 8, 0), imm(4, 4, 1), imm(1, 1, -1),
            branch(1, 0, -28, 1), ebreak};
        result.push_back(branches);
    }
    return result;
}
struct Retire {
    uint64_t pc = 0, data = 0, nextPc = 0;
    uint32_t instruction = 0;
    unsigned rd = 0;
    bool writes = false;
};
struct Oracle {
    std::array<uint64_t, 32> registers{};
    std::vector<Retire> events;
    uint64_t trapPc = 0;
    unsigned taken = 0, notTaken = 0;
    explicit Oracle(const Program &program) {
        uint64_t pc = romBase;
        const Memory unused{};
        for (unsigned steps = 0; steps < 1000; ++steps) {
            require(program.architectural(pc), "independent oracle escaped architectural image: " + hex(pc));
            const uint32_t instruction = program.word(pc);
            if (instruction == ebreak) { trapPc = pc; return; }
            const Encoding *encoding = decode(instruction);
            require(encoding && !encoding->memory && !encoding->mulDiv,
                "bounded integer oracle rejected unknown/data-memory instruction");
            const Expected expected = interpret(*encoding, instruction, pc, registers, unused);
            require(!expected.fault, "unexpected independent architectural fault");
            Retire out{pc, expected.result, expected.nextPc, instruction, expected.rd, expected.rd != 0};
            if (encoding->control && encoding->control < 7) {
                if (expected.taken) ++taken; else ++notTaken;
            }
            if (out.writes) registers[out.rd] = out.data;
            registers[0] = 0;
            events.push_back(out);
            pc = out.nextPc;
        }
        throw std::runtime_error("independent guest exceeded 1000 instructions");
    }
};
void checkRetirement(const Retire &actual, const Retire &expected, bool negative = false) {
    const std::string prefix = negative ? "A1_RETIREMENT_NEGATIVE_REACHED " : "retirement mismatch ";
    require(actual.pc == expected.pc, prefix + "PC expected=" + hex(expected.pc) + " got=" + hex(actual.pc));
    require(actual.instruction == expected.instruction, prefix + "raw instruction");
    require(actual.rd == expected.rd && actual.writes == expected.writes, prefix + "rd/writesRd");
    if (expected.writes) require(actual.data == expected.data, prefix + "data pc=" + hex(actual.pc));
    // Non-writing branch/x0 completion payload is architecturally unspecified.
    require(actual.nextPc == expected.nextPc, prefix + "nextPc pc=" + hex(actual.pc));
}

struct Request {
    uint64_t address = 0, data = 0;
    unsigned opcode = 0, param = 0, size = 0, source = 0, mask = 0;
    bool corrupt = false;
    auto tuple() const { return std::tie(address, data, opcode, param, size, source, mask, corrupt); }
    bool operator==(const Request &other) const { return tuple() == other.tuple(); }
};
struct Reply {
    uint64_t data = 0;
    unsigned source = 0, size = 0, opcode = 1, param = 0, sink = 0;
    bool denied = false, corrupt = false;
    auto tuple() const { return std::tie(data, source, size, opcode, param, sink, denied, corrupt); }
    bool operator==(const Reply &other) const { return tuple() == other.tuple(); }
};
struct Transaction { Request request; uint64_t due; unsigned beat = 0; };
unsigned beats(unsigned size) { return size <= 3 ? 1 : 1u << (size - 3); }

// Service production and checking have separate ownership state. The checker
// learns only accepted A requests, independently recomputes byte/beat contents,
// and rejects source reuse, unowned/wrong D, early replies and held changes.
class ManagerOracle {
    const Program &program;
    struct Owner { Request request; uint64_t due; unsigned beat = 0; };
    std::map<unsigned, Owner> owners;
    std::optional<Request> heldA;
    std::optional<Reply> heldD;
public:
    uint64_t accepted = 0, returned = 0, completed = 0;
    explicit ManagerOracle(const Program &p) : program(p) {}
    void a(bool valid, bool ready, const Request &request, uint64_t cycle) {
        if (heldA) require(valid && request == *heldA, "manager oracle A changed while stalled");
        if (!valid) { heldA.reset(); return; }
        require(request.opcode == 4 && request.param == 0 && !request.corrupt,
            "manager oracle requires legal uncorrupted Get");
        require((request.size == 2 || request.size == 3 || request.size == 6) &&
            request.source < maxTransactions, "manager oracle illegal size/source");
        const uint64_t bytes = UINT64_C(1) << request.size;
        require(!(request.address & (bytes - 1)) && program.mapped(request.address, bytes),
            "manager oracle request outside aligned ROM/RAM windows");
        const unsigned mask = request.size >= 3 ? 255 : 15u << (request.address & 7);
        require(request.mask == mask, "manager oracle incorrect byte mask");
        if (ready) {
            require(owners.count(request.source) == 0, "manager oracle source reused before last D beat");
            owners.emplace(request.source, Owner{request, cycle + serviceLatency, 0});
            ++accepted; heldA.reset();
        } else heldA = request;
    }
    void d(bool valid, bool ready, const Reply &reply, uint64_t cycle, bool negative = false) {
        const std::string prefix = negative ? "A1_MANAGER_NEGATIVE_REACHED " : "manager oracle ";
        if (heldD) require(valid && reply == *heldD, prefix + "D changed while stalled");
        if (!valid) { heldD.reset(); return; }
        const auto found = owners.find(reply.source);
        require(found != owners.end(), prefix + "D source has no accepted Get");
        Owner &owner = found->second;
        require(cycle >= owner.due, prefix + "reply earlier than fixed service latency");
        require(reply.opcode == 1 && reply.param == 0 && reply.sink == 0 &&
            !reply.denied && !reply.corrupt && reply.size == owner.request.size,
            prefix + "AccessAckData metadata");
        const uint64_t address = (owner.request.address & ~UINT64_C(7)) + 8 * owner.beat;
        require(reply.data == program.beat(address), prefix + "byte/beat mismatch");
        if (ready) {
            ++returned;
            if (++owner.beat == beats(owner.request.size)) { owners.erase(found); ++completed; }
            heldD.reset();
        } else heldD = reply;
    }
    bool idle() const { return owners.empty() && !heldA && !heldD; }
};
class InstructionManager {
    const Program &program;
    std::deque<Transaction> pending;
    std::set<unsigned> sources;
public:
    explicit InstructionManager(const Program &p) : program(p) {}
    bool ready() const { return pending.size() < maxTransactions; }
    std::optional<Reply> offer(uint64_t cycle) const {
        if (pending.empty() || cycle < pending.front().due) return {};
        const auto &entry = pending.front();
        return Reply{program.beat((entry.request.address & ~UINT64_C(7)) + 8 * entry.beat),
            entry.request.source, entry.request.size};
    }
    void accept(const Request &request, uint64_t cycle) {
        require(sources.insert(request.source).second, "service duplicated a live source");
        pending.push_back({request, cycle + serviceLatency, 0});
    }
    void consume() {
        require(!pending.empty(), "service consumed empty D queue");
        auto &entry = pending.front();
        if (++entry.beat == beats(entry.request.size)) {
            sources.erase(entry.request.source); pending.pop_front();
        }
    }
    bool idle() const { return pending.empty() && sources.empty(); }
};
struct ClearReply { unsigned owner; uint64_t due; };

void oracleSelfTest(bool injectRetirement, bool injectManager) {
    for (const auto &program : programs()) {
        const Oracle oracle(program);
        require(oracle.events.size() >= 400 && oracle.events.size() < 1000, "guest retirement bound");
        require(oracle.registers[0] == 0 && oracle.registers[30] == 0, "oracle wrong-path/x0 invariant");
        if (program.name == "branches")
            require(oracle.taken == 127 && oracle.notTaken == 65 && oracle.registers[1] == 0 &&
                oracle.registers[2] == 192 && oracle.registers[4] == 64, "branch golden self-test");
        if (program.placement == "ram") require(oracle.registers[31] == ramBase, "RAM bootstrap golden self-test");
        for (const auto &expected : oracle.events) checkRetirement(expected, expected);
        if (injectRetirement) {
            Retire bad = oracle.events.at(8); require(bad.writes, "negative write sample missing");
            bad.data ^= 1; checkRetirement(bad, oracle.events.at(8), true);
        }
        ManagerOracle audit(program);
        const Request request{program.base(), 0, 4, 0, 6, 0, 255, false};
        audit.a(true, false, request, 0); audit.a(true, true, request, 1);
        for (unsigned beat = 0; beat < 8; ++beat) {
            Reply response{program.beat(program.base() + 8 * beat), 0, 6};
            if (injectManager) { response.source = 15; audit.d(true, true, response, 4, true); }
            audit.d(true, false, response, 4 + 2 * beat);
            audit.d(true, true, response, 5 + 2 * beat);
        }
        require(audit.idle() && audit.accepted == 1 && audit.completed == 1 && audit.returned == 8,
            "manager oracle self-test conservation");
        std::cout << "A1_COMMON_CPU_ORACLE_CASE name=" << program.name << " placement=" << program.placement
            << " retired=" << oracle.events.size() << " trap_pc=" << hex(oracle.trapPc) << '\n';
    }
    require(!injectRetirement && !injectManager, "requested negative mutation was never sampled");
    std::cout << "A1_COMMON_CPU_ORACLE_PASS\n";
}

#ifndef A1_COMMON_ORACLE_ONLY
struct Counters {
    uint64_t work = 0, bootstrap = 0, roi = 0, retired = 0, accepted = 0, virtualFetch = 0, physicalFetch = 0;
    uint64_t tlRequests = 0, tlBeats = 0, drain = 0, inspection = 0, dualCommit = 0;
    uint64_t roiAccepted = 0, roiVirtualFetch = 0, roiPhysicalFetch = 0, clearRequests = 0, clearReplies = 0;
};
class Run {
    const Program &program;
    const Oracle oracle; // Complete raw-byte execution precedes constructing DUT.
    std::unique_ptr<GsimModelStorage<SCommonA1CpuRetirementGsim>> storage;
    SCommonA1CpuRetirementGsim &dut;
    InstructionManager manager;
    ManagerOracle managerOracle;
    std::array<std::deque<ClearReply>, 2> clears;
    std::array<std::set<unsigned>, 2> clearOwners;
    std::set<std::pair<unsigned, uint64_t>> retiredTokens;
    Counters counts;
    uint64_t cycle = 0;
    size_t retired = 0;
    bool terminal = false, injectRetirement = false, injectManager = false, injected = false;
    bool roiStarted = false;
    void retire(Retire actual, unsigned index, uint64_t tag) {
        require(!terminal && retired < oracle.events.size(), "extra/post-trap retirement");
        require(retiredTokens.emplace(index, tag).second, "duplicate full ROB token retirement");
        bool mutation = false;
        if (injectRetirement && !injected && retired >= 8 && actual.writes) {
            actual.data ^= 1; injected = true; mutation = true;
        }
        checkRetirement(actual, oracle.events.at(retired), mutation);
        ++retired; ++counts.retired;
    }
    void drive(bool stopped, unsigned inspect = 0) {
        dut.set_io$$hold(stopped); dut.set_io$$inspectRegister(inspect);
        dut.set_io$$instructionA$$ready(manager.ready());
        const auto response = manager.offer(cycle);
        dut.set_io$$instructionD$$valid(bool(response));
        const Reply bits = response.value_or(Reply{});
        dut.set_io$$instructionD$$bits$$opcode(bits.opcode);
        dut.set_io$$instructionD$$bits$$param(bits.param);
        dut.set_io$$instructionD$$bits$$size(bits.size);
        dut.set_io$$instructionD$$bits$$source(bits.source);
        dut.set_io$$instructionD$$bits$$sink(bits.sink);
        dut.set_io$$instructionD$$bits$$denied(bits.denied);
        dut.set_io$$instructionD$$bits$$data(bits.data);
        dut.set_io$$instructionD$$bits$$corrupt(bits.corrupt);
#define DRIVE_CLEAR(N) \
        dut.set_io$$scalar##N##$$request$$ready(true); \
        dut.set_io$$scalar##N##$$response$$valid(!clears[N].empty() && clears[N].front().due <= cycle); \
        dut.set_io$$scalar##N##$$response$$bits$$owner(clears[N].empty() ? 0 : clears[N].front().owner); \
        dut.set_io$$scalar##N##$$response$$bits$$clearReservation(true); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$data(0); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$error(false); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$pageFault(false)
        DRIVE_CLEAR(0); DRIVE_CLEAR(1);
#undef DRIVE_CLEAR
    }
    bool tick(bool inspect = false, unsigned registerIndex = 0) {
        const bool stopped = terminal;
        // ROI begins on the cycle after the last bootstrap retirement. Work
        // always starts at reset release and includes all bootstrap latency.
        // ROM/RAM are separate placements, not mutually matched warm starts.
        const bool inRoi = roiStarted || program.bootstrapInstructions() == 0;
        const auto response = manager.offer(cycle);
        const bool aReady = manager.ready();
        drive(stopped, registerIndex);
        dut.step();
        require(!dut.get_io$$unexpectedCoherent(), "unexpected coherent traffic");
        require(dut.get_io$$robOccupancy() <= 16, "preserved ROB bound exceeded");
        if (!stopped) {
            ++counts.work;
            if (inRoi) ++counts.roi; else ++counts.bootstrap;
            counts.accepted += dut.get_io$$acceptedInstructions();
            counts.virtualFetch += dut.get_io$$virtualFetchFire();
            counts.physicalFetch += dut.get_io$$physicalFetchFire();
            if (inRoi) {
                counts.roiAccepted += dut.get_io$$acceptedInstructions();
                counts.roiVirtualFetch += dut.get_io$$virtualFetchFire();
                counts.roiPhysicalFetch += dut.get_io$$physicalFetchFire();
            }
        } else if (inspect) ++counts.inspection; else ++counts.drain;
        const bool commit0 = dut.get_io$$commit0$$valid(), commit1 = dut.get_io$$commit1$$valid();
        require(!commit1 || commit0, "non-prefix retirement lanes");
        counts.dualCommit += commit0 && commit1;
#define RETIRE(N) \
        if (dut.get_io$$commit##N##$$valid()) retire( \
            {dut.get_io$$commit##N##$$bits$$pc(), dut.get_io$$commit##N##$$bits$$data(), \
            dut.get_io$$commit##N##$$bits$$nextPc(), uint32_t(dut.get_io$$commit##N##$$bits$$instruction()), \
            unsigned(dut.get_io$$commit##N##$$bits$$rd()), bool(dut.get_io$$commit##N##$$bits$$writesRd())}, \
            dut.get_io$$commit##N##$$bits$$token$$index(), dut.get_io$$commit##N##$$bits$$token$$tag())
        RETIRE(0); RETIRE(1);
#undef RETIRE
        if (retired >= program.bootstrapInstructions()) roiStarted = true;
        if (dut.get_io$$trap$$valid()) {
            require(!terminal && retired == oracle.events.size(), "early/repeated terminal trap");
            require(dut.get_io$$trap$$bits$$pc() == oracle.trapPc && dut.get_io$$trap$$bits$$cause() == 3 &&
                dut.get_io$$trap$$bits$$tval() == oracle.trapPc, "imprecise EBREAK cause3/PC/tval");
            terminal = true;
        }
        // Consume the pre-cycle D before learning newly accepted A. A source
        // may be reused only after its final beat really transfers this cycle.
        Reply observed = response.value_or(Reply{});
        bool managerMutation = false;
        if (response && injectManager && !injected) {
            observed.source ^= 8; injected = true; managerMutation = true;
        }
        managerOracle.d(bool(response), dut.get_io$$instructionD$$ready(), observed, cycle, managerMutation);
        if (response && dut.get_io$$instructionD$$ready()) {
            manager.consume(); if (!stopped) ++counts.tlBeats;
        }
        const Request request{dut.get_io$$instructionA$$bits$$address(), dut.get_io$$instructionA$$bits$$data(),
            unsigned(dut.get_io$$instructionA$$bits$$opcode()), unsigned(dut.get_io$$instructionA$$bits$$param()),
            unsigned(dut.get_io$$instructionA$$bits$$size()), unsigned(dut.get_io$$instructionA$$bits$$source()),
            unsigned(dut.get_io$$instructionA$$bits$$mask()), bool(dut.get_io$$instructionA$$bits$$corrupt())};
        const bool aValid = dut.get_io$$instructionA$$valid();
        managerOracle.a(aValid, aReady, request, cycle);
        if (aValid && aReady) { manager.accept(request, cycle); if (!stopped) ++counts.tlRequests; }
#define OBSERVE_CLEAR(N) \
        if (!clears[N].empty() && clears[N].front().due <= cycle && dut.get_io$$scalar##N##$$response$$ready()) { \
            require(clearOwners[N].erase(clears[N].front().owner) == 1, "clear response lost accepted owner"); \
            clears[N].pop_front(); ++counts.clearReplies; \
        } \
        if (dut.get_io$$scalar##N##$$request$$valid()) { \
            require(N == 1 && dut.get_io$$scalar##N##$$request$$bits$$clearReservation(), "unexpected scalar memory traffic"); \
            require(terminal, "reservation clear without observed architectural trap"); \
            const unsigned owner = dut.get_io$$scalar##N##$$request$$bits$$owner(); \
            require(clearOwners[N].insert(owner).second, "duplicate clear owner"); \
            clears[N].push_back({owner, cycle + serviceLatency}); ++counts.clearRequests; \
        }
        OBSERVE_CLEAR(0); OBSERVE_CLEAR(1);
#undef OBSERVE_CLEAR
        ++cycle;
        return terminal && manager.idle() && managerOracle.idle() && clears[0].empty() && clears[1].empty() &&
            dut.get_io$$fetchIdle() && dut.get_io$$privateIdle() && dut.get_io$$ownersIdle() &&
            !dut.get_io$$memoryBusy() && dut.get_io$$robOccupancy() == 0;
    }
public:
    Run(const Program &p, bool retirementNegative, bool managerNegative)
        : program(p), oracle(p), storage(std::make_unique<GsimModelStorage<SCommonA1CpuRetirementGsim>>()),
          dut(storage->get()), manager(p), managerOracle(p),
          injectRetirement(retirementNegative), injectManager(managerNegative) {
        drive(true); dut.set_reset(true); dut.step(); dut.step(); dut.set_reset(false);
    }
    void run() {
        unsigned quiet = 0;
        while (cycle < maxCycles && quiet < 4) { if (tick()) ++quiet; else quiet = 0; }
        require(quiet == 4, "30000-cycle bound reached before precise trap and owner drain");
        require(managerOracle.accepted == managerOracle.completed && manager.idle(), "instruction owner conservation");
        require(counts.clearRequests == 1 && counts.clearReplies == 1, "trap clear owner must complete exactly once");
        require(retired == oracle.events.size() && counts.work == counts.bootstrap + counts.roi,
            "retirement/cycle accounting mismatch");
        require(!injectRetirement && !injectManager, "requested negative mutation was not rejected");
        const auto before = counts;
        for (unsigned index = 0; index < 32; ++index) {
            require(tick(true, index), "register inspection reopened a drained owner");
            require(dut.get_io$$committedValue() == oracle.registers[index], "final GPR mismatch x" + std::to_string(index));
        }
        require(counts.retired == before.retired && counts.clearRequests == before.clearRequests &&
            managerOracle.idle(), "inspection changed architectural/service state");
        std::cout << "A1_COMMON_CPU_METRIC {\"name\":\"" << program.name << "\",\"placement\":\"" << program.placement
            << "\",\"work_cycles\":" << counts.work << ",\"bootstrap_cycles\":" << counts.bootstrap
            << ",\"roi_cycles\":" << counts.roi << ",\"retired\":" << counts.retired
            << ",\"bootstrap_retired\":" << program.bootstrapInstructions()
            << ",\"roi_retired\":" << counts.retired - program.bootstrapInstructions()
            << ",\"accepted_instructions\":" << counts.accepted << ",\"virtual_fetch_requests\":" << counts.virtualFetch
            << ",\"physical_fetch_requests\":" << counts.physicalFetch << ",\"tl_requests\":" << counts.tlRequests
            << ",\"tl_beats\":" << counts.tlBeats << ",\"drain_cycles\":" << counts.drain
            << ",\"inspection_cycles\":" << counts.inspection << ",\"dual_commit_cycles\":" << counts.dualCommit
            << ",\"roi_accepted_instructions\":" << counts.roiAccepted
            << ",\"roi_virtual_fetch_requests\":" << counts.roiVirtualFetch
            << ",\"roi_physical_fetch_requests\":" << counts.roiPhysicalFetch
            << ",\"all_tl_requests\":" << managerOracle.accepted << ",\"all_tl_beats\":" << managerOracle.returned
            << ",\"clear_requests\":" << counts.clearRequests << ",\"clear_replies\":" << counts.clearReplies
            << ",\"work_ipc\":" << double(counts.retired) / counts.work
            << ",\"roi_ipc\":" << double(counts.retired - program.bootstrapInstructions()) / counts.roi << "}\n";
    }
};
#endif
} // namespace

int main(int argc, char **argv) {
    try {
        bool injectRetirement = false, injectManager = false, oracleOnly = false;
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            if (argument == "--inject-retirement-data") injectRetirement = true;
            else if (argument == "--inject-manager-source") injectManager = true;
            else if (argument == "--oracle-only") oracleOnly = true;
            else throw std::runtime_error("unknown bounded host argument: " + argument);
        }
        require(!(injectRetirement && injectManager), "select exactly one negative mutation");
#ifdef A1_COMMON_ORACLE_ONLY
        oracleOnly = true;
#endif
        if (oracleOnly) { oracleSelfTest(injectRetirement, injectManager); return 0; }
#ifndef A1_COMMON_ORACLE_ONLY
        for (const auto &program : programs()) Run(program, injectRetirement, injectManager).run();
        std::cout << "A1_COMMON_CPU_SERVICE latency=3 A_always_ready_until_16_owners D_II=1 max_cycles=30000\n";
        std::cout << "A1_COMMON_CPU_RETIREMENT_PASS\n";
#endif
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "A1_COMMON_CPU_RETIREMENT_FAIL " << error.what() << '\n'; return 1;
    }
}
