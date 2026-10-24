// Actual CommonA1 tile, raw instruction TileLink service, independent retirement
// oracle. No generated-model header is needed for the software-only self-test.
#ifndef A1_VM_ORACLE_ONLY
#include "CommonA1VmPipelineGsim.h"
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
    unsigned setupInstructions = 0;
    bool vm() const { return name.rfind("vm_", 0) == 0; }
    unsigned bootstrapInstructions() const { return unsigned(boot.size()) + setupInstructions; }
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
std::vector<Program> originalPrograms() {
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

constexpr uint64_t vmVa = UINT64_C(0x40000000), vmPa = UINT64_C(0x80210000);
constexpr uint64_t rootPa = UINT64_C(0x80300000), l1Pa = rootPa + 4096, l0Pa = rootPa + 8192;
constexpr uint64_t satpValue = (UINT64_C(8) << 60) | (rootPa >> 12);
constexpr uint64_t mstatusValue = UINT64_C(0x20800); // MPRV=1, MPP=S; execution remains M.
uint64_t pteWord(uint64_t address) {
    if (address == rootPa + 8) return (l1Pa >> 12) << 10 | 1;
    if (address == l1Pa) return (l0Pa >> 12) << 10 | 1;
    if (address == l0Pa) return (vmPa >> 12) << 10 | 0xc7; // V,R,W,A,D; supervisor leaf.
    throw std::runtime_error("PTE manager address outside independent three-level image " + hex(address));
}
uint64_t initialData(uint64_t address) {
    require(address >= vmPa && address < vmPa + 64 && !(address & 7), "data manager outside single line");
    return UINT64_C(0x1234000000000000) + (address - vmPa) / 8;
}
uint64_t walkIndependent(uint64_t va, uint64_t satp, uint64_t status, uint64_t pmpcfg, uint64_t pmpaddr, bool write) {
    require(satp == satpValue && status == mstatusValue, "oracle requires Sv39 MPRV/MPP=S");
    require(pmpcfg == 0x0f && pmpaddr == UINT64_C(0x40000000), "oracle PMP first TOR RWX aperture");
    require(va >= vmVa && va < vmVa + 64 && !(va & 7), "oracle virtual access outside aligned data line");
    uint64_t table = (satp & ((UINT64_C(1) << 44) - 1)) << 12;
    for (int level = 2; level >= 0; --level) {
        const uint64_t pteAddress = table + 8 * ((va >> (12 + 9 * level)) & 511);
        require(pteAddress + 8 <= (pmpaddr << 2), "oracle denied PTE PMP interval");
        const uint64_t pte = pteWord(pteAddress);
        require((pte & 1) && !((pte & 4) && !(pte & 2)), "oracle invalid PTE");
        if (pte & 0xe) {
            require(level == 0 && !(pte & 0x10) && (pte & 2) && (pte & 0x40) && (!write || (pte & 0x84) == 0x84),
                "oracle supervisor leaf/accessed/dirty/write permission");
            const uint64_t pa = ((pte >> 10) << 12) | (va & 4095);
            require(pa + 8 <= (pmpaddr << 2), "oracle denied data PMP whole interval");
            return pa;
        }
        table = (pte >> 10) << 12;
    }
    throw std::runtime_error("oracle absent leaf");
}
void constant(std::vector<uint32_t> &code, unsigned rd, uint64_t value) {
    int shift = 56; while (shift && ((value >> shift) & 255) == 0) shift -= 8;
    code.push_back(imm(rd, 0, int((value >> shift) & 255)));
    for (shift -= 8; shift >= 0; shift -= 8) {
        code.push_back(imm(rd, rd, 8, 1));
        if ((value >> shift) & 255) code.push_back(imm(rd, rd, int((value >> shift) & 255)));
    }
}
uint32_t csrWrite(unsigned csr, unsigned rs) { return csr << 20 | rs << 15 | 1 << 12 | 0x73; }
uint32_t store64(unsigned rs, unsigned base, unsigned offset) {
    return ((offset >> 5) & 127) << 25 | rs << 20 | base << 15 | 3 << 12 | (offset & 31) << 7 | 0x23;
}
uint32_t load64(unsigned rd, unsigned base, unsigned offset) { return offset << 20 | base << 15 | 3 << 12 | rd << 7 | 3; }
std::vector<Program> programs() {
    std::vector<Program> result;
    for (const auto &p : originalPrograms())
        if (p.placement == "ram" && (p.name == "independent_alu" || p.name == "branches")) result.push_back(p);
    for (bool dependent : {false, true}) {
        Program p{dependent ? "vm_dependency" : "vm_store_stream", "rom", {}, {}};
        auto &c = p.code;
        constant(c, 10, UINT64_C(0x40000000)); c.push_back(csrWrite(0x3b0, 10));
        constant(c, 10, 0x0f); c.push_back(csrWrite(0x3a0, 10));
        constant(c, 10, satpValue); c.push_back(csrWrite(0x180, 10));
        c.push_back(0x12000073); // SFENCE.VMA x0,x0 before demand translations.
        constant(c, 10, mstatusValue); c.push_back(csrWrite(0x300, 10));
        constant(c, 11, vmVa); constant(c, 12, 7);
        c.push_back(store64(12, 11, 0));
        c.push_back(0x0330000f); // Cold ordinary SD completes before younger dependent load demand.
        c.push_back(load64(13, 11, 0));
        p.setupInstructions = c.size();
        for (unsigned i = 0; i < 48; ++i) {
            const unsigned offset = (i % 8) * 8;
            if (dependent) { c.push_back(load64(12, 11, offset)); c.push_back(imm(12, 12, 3)); }
            else { c.push_back(imm(12, 0, int(i) + 31)); c.push_back(reg(14 + i % 8, 12, 13)); }
            c.push_back(store64(12, 11, offset));
            c.push_back(load64(13, 11, offset));
        }
        c.push_back(0x0330000f);
        for (unsigned i = 0; i < 8; ++i) c.push_back(load64(20 + i, 11, 8 * i));
        c.push_back(ebreak); result.push_back(p);
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

    struct Access { uint64_t pc, va, pa, data; bool write; };
    std::vector<Access> accesses;
    unsigned stores = 0, loads = 0;
    explicit Oracle(const Program &program) {
        uint64_t pc = romBase, satp = 0, status = 0, cfg = 0, address = 0;
        std::map<uint64_t, uint64_t> memory;
        for (unsigned i = 0; i < 8; ++i) memory[vmPa + 8*i] = initialData(vmPa + 8*i);
        const Memory unused{};
        for (unsigned steps = 0; steps < 1200; ++steps) {
            require(program.architectural(pc), "independent oracle escaped architectural image: " + hex(pc));
            const uint32_t instruction = program.word(pc);
            if (instruction == ebreak) { trapPc = pc; return; }
            Retire out{pc, 0, pc+4, instruction, 0, false};
            const unsigned opcode = instruction & 127, rs = (instruction >> 15) & 31;
            if (instruction == 0x12000073 || opcode == 0x0f) {
                require(program.vm() && (instruction == 0x12000073 || instruction == 0x0330000f), "unexpected fence");
            } else if (opcode == 0x73) {
                require(program.vm() && ((instruction >> 12) & 7) == 1 && ((instruction >> 7) & 31) == 0,
                    "oracle CSR instruction outside explicit CSRRW rd0 subset");
                const unsigned csr = instruction >> 20;
                if (csr == 0x3b0) address = registers[rs];
                else if (csr == 0x3a0) cfg = registers[rs];
                else if (csr == 0x180) satp = registers[rs];
                else if (csr == 0x300) status = registers[rs];
                else throw std::runtime_error("unknown oracle CSR");
            } else if (opcode == 3 || opcode == 0x23) {
                require(program.vm() && ((instruction >> 12) & 7) == 3, "oracle only aligned LD/SD");
                const bool write = opcode == 0x23;
                const unsigned raw = write ? ((instruction >> 25) << 5) | ((instruction >> 7) & 31) : instruction >> 20;
                const int offset = int(raw ^ 0x800) - 0x800;
                const uint64_t va = registers[rs] + offset;
                const uint64_t pa = walkIndependent(va, satp, status, cfg, address, write);
                const uint64_t data = write ? registers[(instruction >> 20) & 31] : memory.at(pa);
                accesses.push_back({pc,va,pa,data,write});
                if (write) { memory[pa] = data; ++stores; }
                else { out.rd = (instruction >> 7) & 31; out.writes = out.rd != 0; out.data = data; ++loads; }
            } else {
                const Encoding *encoding = decode(instruction);
                require(encoding && !encoding->memory && !encoding->mulDiv, "oracle unknown integer instruction");
                const Expected expected = interpret(*encoding, instruction, pc, registers, unused);
                require(!expected.fault, "unexpected independent architectural fault");
                out.data = expected.result; out.nextPc = expected.nextPc;
                out.rd = expected.rd; out.writes = expected.rd != 0;
                if (encoding->control && encoding->control < 7) {
                    if (expected.taken) ++taken; else ++notTaken;
                }
            }
            if (out.writes) registers[out.rd] = out.data;
            registers[0] = 0; events.push_back(out); pc = out.nextPc;
        }
        throw std::runtime_error("independent guest exceeded 1200 instructions");
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
struct ClearReply { unsigned owner; uint64_t due; bool clear = true; uint64_t data = 0; };
struct CacheOwner { Request request; uint64_t due; unsigned sink; };
struct StoreWitness {
    Oracle::Access expected; uint64_t epoch = 0, upstream = 0;
    std::optional<uint64_t> translated, checked, certificate, physical;
};

void oracleSelfTest(bool injectRetirement, bool injectManager) {
    for (const auto &program : programs()) {
        const Oracle oracle(program);
        require(oracle.events.size() >= 200 && oracle.events.size() < 1200, "guest retirement bound");
        require(oracle.registers[0] == 0 && oracle.registers[30] == 0, "oracle wrong-path/x0 invariant");
        if (program.name == "branches")
            require(oracle.taken == 127 && oracle.notTaken == 65 && oracle.registers[1] == 0 &&
                oracle.registers[2] == 192 && oracle.registers[4] == 64, "branch golden self-test");
        if (program.vm()) require(oracle.stores == 49 && oracle.loads >= 57, "VM independent load/store program bounds");
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
        std::cout << "A1_VM_CPU_ORACLE_CASE name=" << program.name << " placement=" << program.placement
            << " retired=" << oracle.events.size() << " trap_pc=" << hex(oracle.trapPc) << '\n';
    }
    require(!injectRetirement && !injectManager, "requested negative mutation was never sampled");
    std::cout << "A1_VM_CPU_ORACLE_PASS\n";
}

#ifndef A1_VM_ORACLE_ONLY
struct Counters {
    uint64_t work = 0, bootstrap = 0, roi = 0, retired = 0, accepted = 0, virtualFetch = 0, physicalFetch = 0;
    uint64_t tlRequests = 0, tlBeats = 0, drain = 0, inspection = 0, dualCommit = 0;
    uint64_t roiAccepted = 0, roiVirtualFetch = 0, roiPhysicalFetch = 0, clearRequests = 0, clearReplies = 0;
};
class Run {
    const Program &program;
    const Oracle oracle; // Complete raw-byte execution precedes constructing DUT.
    std::unique_ptr<GsimModelStorage<SCommonA1VmPipelineGsim>> storage;
    SCommonA1VmPipelineGsim &dut;
    InstructionManager manager;
    ManagerOracle managerOracle;
    std::array<std::deque<ClearReply>, 2> clears;
    std::array<std::set<unsigned>, 2> clearOwners;
    std::set<std::pair<unsigned, uint64_t>> retiredTokens;
    Counters counts;
    std::map<unsigned, CacheOwner> cacheOwners;
    std::set<unsigned> cacheSinks;
    std::deque<unsigned> grants;
    std::optional<Request> heldCacheA;
    std::map<std::pair<unsigned,uint64_t>, StoreWitness> stores;
    std::vector<Oracle::Access> expectedStores;
    size_t storeCursor = 0, physicalStoreCursor = 0;
    uint64_t nativeRequests = 0, nativeReplies = 0, pteReads = 0, dataAcquires = 0, dataGrants = 0, dataAcks = 0;
    uint64_t demandRequests = 0, demandReplies = 0, demandHits = 0, demandMisses = 0;
    int firstDemandMissAccess = -1;
    uint64_t translatedStores = 0, checkedStores = 0, certificates = 0, physicalStores = 0, hitPasses = 0;
    uint64_t precheckedLoads = 0, dtlbHits = 0, packetPartial = 0, packetFlush = 0, packetExpected = 0;
    uint64_t hitStageLatency = 0, allStoreStageLatency = 0;
    bool stageNegative = false;
    using Token = std::pair<unsigned,uint64_t>;
    struct DemandOwner { uint64_t va; bool write; std::optional<Token> store; };
    std::deque<DemandOwner> demandOwners;
    std::map<Token, uint64_t> hitAt;
    uint64_t hitStoreSamples = 0;
    std::optional<unsigned> offeredGrant() const {
        if (!grants.empty() && cacheOwners.at(grants.front()).due <= cycle) return grants.front();
        return {};
    }
    void stageObserve() {
        const bool registered = dut.get_io$$registeredTranslation();
        require(!dut.get_io$$acceptedPrefixEnabled(), "preserve actual Selected acceptedPrefixValidation=false");
        packetPartial += dut.get_io$$packetPresent() == 2 && dut.get_io$$packetConsume() == 1;
        packetFlush += dut.get_io$$packetFlush(); packetExpected += dut.get_io$$packetExpectedNext();
        dtlbHits += dut.get_io$$dtlbHit();
        if (dut.get_io$$upstream$$valid()) {
            if (dut.get_io$$upstream$$bits$$precheckedLoad()) ++precheckedLoads;
            if (dut.get_io$$upstream$$bits$$virtualized() && !dut.get_io$$upstream$$bits$$precheckedLoad()) {
                std::optional<Token> token;
                if (dut.get_io$$upstream$$bits$$write()) token = Token{
                    unsigned(dut.get_io$$upstreamOrigin$$bits$$token$$index()),
                    uint64_t(dut.get_io$$upstreamOrigin$$bits$$token$$tag())};
                demandOwners.push_back({dut.get_io$$upstream$$bits$$address(),
                    bool(dut.get_io$$upstream$$bits$$write()), token});
            }
            if (dut.get_io$$upstream$$bits$$write()) {
                require(program.vm() && storeCursor < expectedStores.size(), "unexpected accepted data store");
                const auto expected = expectedStores.at(storeCursor++);
                require(dut.get_io$$upstream$$bits$$virtualized() && !dut.get_io$$upstream$$bits$$precheckedLoad() &&
                    !dut.get_io$$upstream$$bits$$atomic() && !dut.get_io$$upstream$$bits$$uncached(),
                    "store must exercise ordinary demand virtual path");
                require(dut.get_io$$upstream$$bits$$address() == expected.va && dut.get_io$$upstream$$bits$$data() == expected.data &&
                    dut.get_io$$upstream$$bits$$size() == 3 && dut.get_io$$upstream$$bits$$mask() == 255,
                    "accepted virtual store differs from pre-executed architectural oracle");
                require(dut.get_io$$upstreamOrigin$$valid(), "ordinary store missing canonical full-token origin");
                const auto token = std::make_pair(unsigned(dut.get_io$$upstreamOrigin$$bits$$token$$index()),
                    uint64_t(dut.get_io$$upstreamOrigin$$bits$$token$$tag()));
                require(stores.emplace(token, StoreWitness{expected, dut.get_io$$upstreamOrigin$$bits$$epoch(), cycle,
                    {},{},{},{}}).second, "duplicate accepted store full token");
            }
        }
        if (dut.get_io$$translationRequest$$valid()) {
            ++demandRequests;
            require(!demandOwners.empty(), "translation request has no accepted ingress owner");
            const DemandOwner demand = demandOwners.front(); demandOwners.pop_front();
            require(dut.get_io$$translationRequest$$bits$$virtualAddress() == demand.va &&
                dut.get_io$$translationRequest$$bits$$access() == (demand.write ? 1 : 0),
                "translation request crossed ordered ingress ownership");
            require(program.vm() && dut.get_io$$vm$$satp() == satpValue && dut.get_io$$vm$$dataPrivilege() == 1 &&
                !dut.get_io$$vm$$sum() && !dut.get_io$$vm$$mxr() && dut.get_io$$fetchPrivilege() == 3 &&
                dut.get_io$$pmpConfig0() == 0x0f && dut.get_io$$pmpAddress0() == UINT64_C(0x40000000),
                "actual CSR MPRV/MPP=S, M fetch, Sv39 and PMP context not established");
            require(dut.get_io$$translationRequest$$bits$$rootPpn() == (rootPa >> 12) &&
                dut.get_io$$translationRequest$$bits$$mode() == 8 && dut.get_io$$translationRequest$$bits$$privilege() == 1 &&
                dut.get_io$$translationRequest$$bits$$asid() == 0 && !dut.get_io$$translationRequest$$bits$$sum() &&
                !dut.get_io$$translationRequest$$bits$$mxr(), "translation request owner context mismatch");
            if (dut.get_io$$translationResponse$$valid() && !dut.get_io$$translationWaiting()) {
                ++demandHits;
                const uint64_t va = dut.get_io$$translationRequest$$bits$$virtualAddress();
                require(dut.get_io$$translationResponse$$bits$$physicalAddress() ==
                    walkIndependent(va,satpValue,mstatusValue,0x0f,UINT64_C(0x40000000),
                        dut.get_io$$translationRequest$$bits$$access() == 1), "TLB-hit PA independent page oracle");
                if (demand.store) require(hitAt.emplace(*demand.store, cycle).second, "duplicate hit full-token owner");
            } else { ++demandMisses; if (firstDemandMissAccess < 0) firstDemandMissAccess = dut.get_io$$translationRequest$$bits$$access(); }
        }
        if (dut.get_io$$translationResponse$$valid()) {
            ++demandReplies;
            require(!dut.get_io$$translationResponse$$bits$$pageFault() && !dut.get_io$$translationResponse$$bits$$accessFault() &&
                dut.get_io$$translationResponse$$bits$$pbmt() == 0, "unexpected translation fault/PBMT");
        }
        if (dut.get_io$$translationHitPass()) { ++hitPasses; require(!registered, "registered M2 leaked old same-cycle hit pass"); }
#define OBSERVE_STORE_STAGE(NAME, ORIGIN, MEMBER, COUNT) \
        if (dut.get_io$$##NAME##$$valid() && dut.get_io$$##NAME##$$bits$$write()) { \
            require(dut.get_io$$##ORIGIN##$$valid(), "store stage lost origin"); \
            const auto key = std::make_pair(unsigned(dut.get_io$$##ORIGIN##$$bits$$token$$index()), \
                uint64_t(dut.get_io$$##ORIGIN##$$bits$$token$$tag())); \
            auto found = stores.find(key); require(found != stores.end(), "store stage substituted full token"); \
            auto &owner = found->second; \
            require(!owner.MEMBER && dut.get_io$$##ORIGIN##$$bits$$epoch() == owner.epoch, "duplicate/stale store stage"); \
            uint64_t pa = dut.get_io$$##NAME##$$bits$$address(); \
            if (stageNegative && !injected && std::string(#NAME) == "checked") { \
                pa ^= 8; injected = true; std::cerr << "A1_VM_STAGE_NEGATIVE_REACHED\n"; } \
            require(pa == owner.expected.pa && dut.get_io$$##NAME##$$bits$$data() == owner.expected.data && \
                !dut.get_io$$##NAME##$$bits$$virtualized() && dut.get_io$$##NAME##$$bits$$size() == 3 && \
                dut.get_io$$##NAME##$$bits$$mask() == 255, "independent store stage PA/data oracle mismatch"); \
            owner.MEMBER = cycle; ++COUNT; \
        }
        OBSERVE_STORE_STAGE(translated, translatedOrigin, translated, translatedStores);
        OBSERVE_STORE_STAGE(checked, checkedOrigin, checked, checkedStores);
#undef OBSERVE_STORE_STAGE
        if (dut.get_io$$checked$$valid() && dut.get_io$$checked$$bits$$write()) {
            const auto key = std::make_pair(unsigned(dut.get_io$$checkedOrigin$$bits$$token$$index()),
                uint64_t(dut.get_io$$checkedOrigin$$bits$$token$$tag()));
            const auto &o = stores.at(key);
            require(!dut.get_io$$checkedFault() && !dut.get_io$$checkedPageFault(), "legal store denied at checked permission");
            if (registered) require(o.translated && *o.translated < cycle,
                "M2 store must cross registered translated boundary before checked acceptance");
            allStoreStageLatency += cycle - o.upstream;
            if (hitAt.count(key)) { hitStageLatency += cycle - hitAt.at(key); ++hitStoreSamples; }
        }
        if (dut.get_io$$certificate$$valid()) {
            const auto key = std::make_pair(unsigned(dut.get_io$$certificate$$bits$$origin$$token$$index()),
                uint64_t(dut.get_io$$certificate$$bits$$origin$$token$$tag()));
            auto found = stores.find(key); require(found != stores.end(), "certificate unowned full token");
            auto &o = found->second;
            require(o.checked && !o.certificate && dut.get_io$$certificate$$bits$$origin$$epoch() == o.epoch &&
                dut.get_io$$certificate$$bits$$virtualAddress() == o.expected.va &&
                dut.get_io$$certificate$$bits$$physicalAddress() == o.expected.pa &&
                dut.get_io$$certificate$$bits$$size() == 3 && dut.get_io$$certificate$$bits$$mask() == 255,
                "independent canonical certificate owner/VA/PA/permission mismatch");
            o.certificate = cycle; ++certificates;
        }
        if (dut.get_io$$physical$$valid() && dut.get_io$$physical$$bits$$write()) {
            require(physicalStoreCursor < expectedStores.size(), "extra physical store");
            const auto &e = expectedStores.at(physicalStoreCursor++);
            require(dut.get_io$$physical$$bits$$address() == e.pa && dut.get_io$$physical$$bits$$data() == e.data &&
                dut.get_io$$physical$$bits$$mask() == 255 && !dut.get_io$$physical$$bits$$virtualized(),
                "physical store diverged from independent architectural sequence");
            ++physicalStores;
        }
    }

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
#define DRIVE_NATIVE(N) \
        dut.set_io$$scalar##N##$$response$$bits$$clearReservation(clears[N].empty() ? false : clears[N].front().clear); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$data(clears[N].empty() ? 0 : clears[N].front().data)
        DRIVE_NATIVE(0); DRIVE_NATIVE(1);
#undef DRIVE_NATIVE
        dut.set_io$$dataA$$ready(cacheOwners.size() < 2 && cacheSinks.size() < 2);
        dut.set_io$$dataC$$ready(true); dut.set_io$$dataE$$ready(true);
        const auto source = offeredGrant();
        dut.set_io$$dataGrant$$valid(bool(source));
        const CacheOwner entry = source ? cacheOwners.at(*source) : CacheOwner{};
        dut.set_io$$dataGrant$$bits$$source(source.value_or(0)); dut.set_io$$dataGrant$$bits$$sink(entry.sink);
        dut.set_io$$dataGrant$$bits$$cap(entry.request.param == 0 ? 1 : 0);
        dut.set_io$$dataGrant$$bits$$denied(false); dut.set_io$$dataGrant$$bits$$corrupt(false);
#define GRANT_WORD(N) dut.set_io$$dataGrant$$bits$$data##N(source ? initialData(entry.request.address + 8*N) : 0)
        GRANT_WORD(0); GRANT_WORD(1); GRANT_WORD(2); GRANT_WORD(3);
        GRANT_WORD(4); GRANT_WORD(5); GRANT_WORD(6); GRANT_WORD(7);
#undef GRANT_WORD

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
        const bool cacheReady = cacheOwners.size() < 2 && cacheSinks.size() < 2;
        drive(stopped, registerIndex);
        dut.step();
        if (!program.vm()) require(!dut.get_io$$unexpectedCoherent(), "non-memory guest emitted coherent traffic");
        stageObserve();
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

#define OBSERVE_NATIVE(N) \
        if (!clears[N].empty() && clears[N].front().due <= cycle && dut.get_io$$scalar##N##$$response$$ready()) { \
            require(clearOwners[N].erase(clears[N].front().owner) == 1, "native response lost accepted owner"); \
            if (clears[N].front().clear) ++counts.clearReplies; else ++nativeReplies; \
            clears[N].pop_front(); \
        } \
        if (dut.get_io$$scalar##N##$$request$$valid()) { \
            require(N == 1, "bounded guest unexpectedly used scalar0 data bypass"); \
            const unsigned owner = dut.get_io$$scalar##N##$$request$$bits$$owner(); \
            require(clearOwners[N].insert(owner).second, "duplicate native full owner"); \
            const bool clear = dut.get_io$$scalar##N##$$request$$bits$$clearReservation(); \
            uint64_t data = 0; \
            if (clear) { require(terminal, "reservation clear before terminal trap"); ++counts.clearRequests; } \
            else { \
                require(program.vm() && !dut.get_io$$scalar##N##$$request$$bits$$memory$$write() && \
                    !dut.get_io$$scalar##N##$$request$$bits$$memory$$atomic() && \
                    !dut.get_io$$scalar##N##$$request$$bits$$memory$$virtualized() && \
                    !dut.get_io$$scalar##N##$$request$$bits$$memory$$precheckedLoad() && \
                    dut.get_io$$scalar##N##$$request$$bits$$memory$$size() == 3 && \
                    dut.get_io$$scalar##N##$$request$$bits$$memory$$mask() == 255, "illegal physical PTE read"); \
                data = pteWord(dut.get_io$$scalar##N##$$request$$bits$$memory$$address()); ++nativeRequests; ++pteReads; \
            } \
            clears[N].push_back({owner, cycle + serviceLatency, clear, data}); \
        }
        OBSERVE_NATIVE(0); OBSERVE_NATIVE(1);
#undef OBSERVE_NATIVE
        // Legal whole-line Home: sources survive through Grant acceptance and
        // sinks survive independently through mandatory E. No probe/eviction is
        // needed by the fixed one-line working set; any C is rejected, not acked.
        require(!dut.get_io$$dataC$$valid(), "single-line guest unexpectedly released/evicted cache data");
        if (dut.get_io$$dataE$$valid()) {
            require(cacheSinks.erase(dut.get_io$$dataE$$bits$$sink()) == 1, "unowned/duplicate cache GrantAck"); ++dataAcks;
        }
        const auto grantSource = offeredGrant();
        if (grantSource && dut.get_io$$dataGrant$$ready()) {
            require(cacheOwners.erase(*grantSource) == 1, "cache Grant lost owner"); grants.pop_front(); ++dataGrants;
        }
        const Request cacheA{dut.get_io$$dataA$$bits$$address(), dut.get_io$$dataA$$bits$$data(),
            unsigned(dut.get_io$$dataA$$bits$$opcode()), unsigned(dut.get_io$$dataA$$bits$$param()),
            unsigned(dut.get_io$$dataA$$bits$$size()), unsigned(dut.get_io$$dataA$$bits$$source()),
            unsigned(dut.get_io$$dataA$$bits$$mask()), bool(dut.get_io$$dataA$$bits$$corrupt())};
        const bool cacheValid = dut.get_io$$dataA$$valid();
        if (heldCacheA) require(cacheValid && cacheA == *heldCacheA, "cache held Acquire changed");
        if (cacheValid) {
            require(program.vm() && cacheA.opcode == 6 && cacheA.size == 6 && cacheA.address == vmPa &&
                cacheA.mask == 255 && !cacheA.corrupt && cacheA.param <= 1, "illegal bounded cache AcquireBlock");
            if (cacheReady) {
                unsigned sink = 0; while (cacheSinks.count(sink)) ++sink;
                require(sink < 2 && !cacheOwners.count(cacheA.source), "cache source/sink reuse");
                cacheSinks.insert(sink); cacheOwners.emplace(cacheA.source, CacheOwner{cacheA,cycle+serviceLatency,sink});
                grants.push_back(cacheA.source); ++dataAcquires; heldCacheA.reset();
            } else heldCacheA = cacheA;
        } else heldCacheA.reset();

        ++cycle;
        return terminal && manager.idle() && managerOracle.idle() && clears[0].empty() && clears[1].empty() &&
            cacheOwners.empty() && cacheSinks.empty() && grants.empty() && !heldCacheA &&
            dut.get_io$$fetchIdle() && dut.get_io$$privateIdle() && dut.get_io$$ownersIdle() &&
            !dut.get_io$$memoryBusy() && dut.get_io$$robOccupancy() == 0;
    }
public:
    Run(const Program &p, bool retirementNegative, bool managerNegative, bool stageMutation = false)
        : program(p), oracle(p), storage(std::make_unique<GsimModelStorage<SCommonA1VmPipelineGsim>>()),
          dut(storage->get()), manager(p), managerOracle(p),
          injectRetirement(retirementNegative), injectManager(managerNegative) {
        stageNegative = stageMutation;
        for (const auto &a : oracle.accesses) if (a.write) expectedStores.push_back(a);
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
        require(!injectRetirement && !injectManager && !stageNegative, "requested negative mutation was not rejected");
        if (program.vm()) {
            require(storeCursor == oracle.stores && physicalStores == oracle.stores && checkedStores == oracle.stores &&
                certificates == oracle.stores, "store accepted/checked/certificate/physical conservation");
            require(nativeRequests == nativeReplies && pteReads == 3 && dataAcquires == 1 && dataGrants == 1 && dataAcks == 1,
                "fixed three-level first miss and one-line ownership conservation");
            require(demandRequests == demandReplies && demandOwners.empty() && hitStoreSamples == hitAt.size() &&
                hitStoreSamples >= 48 && demandHits >= 48 && demandMisses >= 1 && precheckedLoads > 0,
                "actual MPRV demand TLB hits/miss and prechecked bypass coverage missing");
            if (dut.get_io$$registeredTranslation()) require(translatedStores == oracle.stores && hitPasses == 0,
                "M2 registered stage coverage missing");
            else require(hitPasses >= 48, "baseline same-cycle demand-hit pass coverage missing");
        } else require(!nativeRequests && !dataAcquires && !demandRequests, "bare reference guest changed memory scope");
        const auto before = counts;
        for (unsigned index = 0; index < 32; ++index) {
            require(tick(true, index), "register inspection reopened a drained owner");
            require(dut.get_io$$committedValue() == oracle.registers[index], "final GPR mismatch x" + std::to_string(index));
        }
        require(counts.retired == before.retired && counts.clearRequests == before.clearRequests &&
            managerOracle.idle(), "inspection changed architectural/service state");
        std::cout << "A1_VM_STAGE_METRIC {\"name\":\"" << program.name << "\",\"placement\":\"" << program.placement
            << "\",\"native_requests\":" << nativeRequests << ",\"native_replies\":" << nativeReplies
            << ",\"pte_reads\":" << pteReads << ",\"data_acquires\":" << dataAcquires << ",\"data_grants\":" << dataGrants
            << ",\"data_acks\":" << dataAcks << ",\"demand_requests\":" << demandRequests << ",\"demand_replies\":" << demandReplies
            << ",\"first_demand_miss_access\":" << firstDemandMissAccess << ",\"demand_hits\":" << demandHits << ",\"demand_misses\":" << demandMisses << ",\"translated_stores\":" << translatedStores
            << ",\"checked_stores\":" << checkedStores << ",\"certificates\":" << certificates << ",\"physical_stores\":" << physicalStores
            << ",\"hit_passes\":" << hitPasses << ",\"prechecked_loads\":" << precheckedLoads << ",\"dtlb_hits\":" << dtlbHits
            << ",\"hit_store_samples\":" << hitStoreSamples << ",\"hit_stage_latency_sum\":" << hitStageLatency << ",\"all_store_stage_latency_sum\":" << allStoreStageLatency
            << ",\"packet_partial_consume\":" << packetPartial << ",\"packet_flush\":" << packetFlush << ",\"packet_expected_next\":" << packetExpected
            << ",\"accepted_prefix_validation\":false,\"registered_translation\":" << unsigned(dut.get_io$$registeredTranslation())
            << ",\"circular_payload\":" << unsigned(dut.get_io$$circularPayload()) << "}\n";
        std::cout << "A1_VM_CPU_METRIC {\"name\":\"" << program.name << "\",\"placement\":\"" << program.placement
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
        bool injectRetirement = false, injectManager = false, oracleOnly = false, stageMutation = false;
        for (int i = 1; i < argc; ++i) {
            const std::string argument = argv[i];
            if (argument == "--inject-stage-pa") stageMutation = true;
            else if (argument == "--inject-retirement-data") injectRetirement = true;
            else if (argument == "--inject-manager-source") injectManager = true;
            else if (argument == "--oracle-only") oracleOnly = true;
            else throw std::runtime_error("unknown bounded host argument: " + argument);
        }
        require(!(injectRetirement && injectManager), "select exactly one negative mutation");
#ifdef A1_VM_ORACLE_ONLY
        oracleOnly = true;
#endif
        if (oracleOnly) { require(!stageMutation, "stage observation negative requires actual DUT"); oracleSelfTest(injectRetirement, injectManager); return 0; }
#ifndef A1_VM_ORACLE_ONLY
        for (const auto &program : programs()) {
            if (stageMutation && !program.vm()) continue;
            Run(program, injectRetirement, injectManager, stageMutation).run();
        }
        std::cout << "A1_VM_CPU_SERVICE latency=3 A_always_ready_until_16_owners D_II=1 max_cycles=30000\n";
        std::cout << "A1_VM_CPU_RETIREMENT_PASS\n";
#endif
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "A1_VM_CPU_RETIREMENT_FAIL " << error.what() << '\n'; return 1;
    }
}
