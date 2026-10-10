#include "PostedStoreCpuLineageGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iomanip>
#include <initializer_list>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

// Independent raw RV64 encodings and byte memory. No DUT decode/proof helper,
// generated instruction table, cache component oracle, or internal forcing.
using Dut = SPostedStoreCpuLineageGsim;
static constexpr uint64_t base = 0x80000000ULL, ram = 0x80200000ULL;
// Host-driven input: GSIM exposes only its setter. Both drive and handshake
// observation use this same value on the sampled tick; stimulus remains ready=1.
static constexpr bool pteRequestReady = true;
using Bytes = std::array<uint8_t, 4096>;
static void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
// Optional JSONL evidence. Every complete record is flushed immediately, so a
// failed assertion keeps its expected trace and the actual failing prefix.
class Trace {
    std::ofstream output;
    uint64_t lastCycle = 0;
    static std::string quoted(const std::string &text) {
        std::ostringstream out;
        out << '"';
        for (const unsigned char c : text) {
            if (c == '"' || c == '\\') out << '\\' << char(c);
            else if (c < 32) out << "\\u" << std::hex << std::setw(4) << std::setfill('0') << unsigned(c);
            else out << char(c);
        }
        return out.str() + '"';
    }
public:
    void open(const std::string &path) {
        if (path.empty()) return;
        output.open(path, std::ios::out | std::ios::trunc);
        require(output.good(), "cannot open lineage trace " + path);
    }
    void event(const std::string &name, uint64_t cycle, const char *kind,
        std::initializer_list<std::pair<const char *, uint64_t>> fields = {}, const std::string &stage = "") {
        lastCycle = cycle;
        if (!output.is_open()) return;
        output << "{\"case\":" << quoted(name) << ",\"cycle\":" << cycle << ",\"kind\":" << quoted(kind);
        if (!stage.empty()) output << ",\"stage\":" << quoted(stage);
        for (const auto &field : fields) output << ',' << quoted(field.first) << ':' << field.second;
        output << "}\n";
        output.flush();
        require(output.good(), "cannot append lineage trace");
    }
    void failure(const std::string &name, const std::string &message) noexcept {
        try {
            if (!output.is_open()) return;
            output << "{\"case\":" << quoted(name) << ",\"cycle\":" << lastCycle
                << ",\"kind\":\"failure\",\"message\":" << quoted(message) << "}\n";
            output.flush();
        } catch (...) { /* Preserve the original failure if tracing also fails. */ }
    }
};
static uint64_t sext(uint64_t x, unsigned bits) {
    const uint64_t sign = UINT64_C(1) << (bits - 1);
    return (x ^ sign) - sign;
}
static uint32_t addi(unsigned rd, unsigned rs, int imm) {
    return (uint32_t(imm & 4095) << 20) | (rs << 15) | (rd << 7) | 0x13;
}
static uint32_t shift(unsigned rd, unsigned rs, unsigned amount, bool right) {
    return (amount << 20) | (rs << 15) | ((right ? 5 : 1) << 12) | (rd << 7) | 0x13;
}
static uint32_t ori(unsigned rd, unsigned rs, unsigned imm) {
    return (imm << 20) | (rs << 15) | (6 << 12) | (rd << 7) | 0x13;
}
static uint32_t csrw(unsigned csr, unsigned rs) { return (csr << 20) | (rs << 15) | 0x1073; }
static uint32_t store(unsigned rs, unsigned addr, int offset, unsigned size) {
    const unsigned imm = offset & 4095;
    return ((imm >> 5) << 25) | (rs << 20) | (addr << 15) | (size << 12) | ((imm & 31) << 7) | 0x23;
}
static uint32_t load(unsigned rd, unsigned addr, int offset, unsigned funct3) {
    return (unsigned(offset & 4095) << 20) | (addr << 15) | (funct3 << 12) | (rd << 7) | 3;
}
static uint32_t beq(unsigned left, unsigned right, unsigned offset) {
    return (((offset >> 12) & 1) << 31) | (((offset >> 5) & 63) << 25) | (right << 20) |
        (left << 15) | (((offset >> 1) & 15) << 8) | (((offset >> 11) & 1) << 7) | 0x63;
}
static Bytes initialBytes() {
    Bytes result{};
    for (unsigned i = 0; i < result.size(); ++i) result[i] = uint8_t((i * 37 + 19) ^ (i >> 3));
    return result;
}
static uint64_t readBeat(const Bytes &memory, uint64_t address) {
    require((address & ~UINT64_C(7)) >= ram && (address & ~UINT64_C(7)) + 8 <= ram + memory.size(),
        "external memory request outside authored RAM aperture");
    uint64_t result = 0;
    for (unsigned i = 0; i < 8; ++i) result |= uint64_t(memory[(address & ~UINT64_C(7)) - ram + i]) << (i * 8);
    return result;
}
struct Token {
    uint64_t tag = 0; unsigned index = 0;
    bool operator==(const Token &o) const { return tag == o.tag && index == o.index; }
    bool operator<(const Token &o) const { return std::tie(tag, index) < std::tie(o.tag, o.index); }
};
static void requireEpochDrain(bool externalOwner, const std::set<Token> &priorOwners) {
    require(!externalOwner && priorOwners.empty(), "authorization context changed with retained ownership");
}
static void epochOracleControls() {
    const std::set<Token> oldOwner{{17, 1}};
    auto rejects = [](bool externalOwner, const std::set<Token> &priorOwners) {
        try { requireEpochDrain(externalOwner, priorOwners); }
        catch (const std::runtime_error &e) {
            return std::string(e.what()) == "authorization context changed with retained ownership";
        }
        return false;
    };
    require(rejects(false, oldOwner), "epoch oracle accepted delayed old-owner response");
    require(rejects(true, {}), "epoch oracle accepted external retained ownership");
    // Even a reply in the observed tick cannot erase a pre-edge responsibility
    // from this check. Hardware increments only from aggregateDrained && idle.
    auto afterReply = oldOwner;
    afterReply.clear();
    require(afterReply.empty() && rejects(false, oldOwner), "epoch oracle used post-reply responsibility");
    // A newly started owner belongs to the new epoch and is checked separately
    // at every proof boundary against its immutable captured witness epoch.
    requireEpochDrain(false, {});
    std::cout << "CPU_POSTED_EPOCH_ORACLE delayed_old_rejected=1 external_old_rejected=1"
        << " same_tick_old_reply_rejected=1 empty_old_new_start_allowed=1\n";
}
struct Intent {
    uint64_t pc = 0, address = 0, physicalAddress = 0, rawData = 0, data = 0, responseData = 0;
    uint64_t cause = 0;
    unsigned size = 0, mask = 0, privilege = 3;
    bool store = false, virtualized = false, denied = false, localFault = false, pageFault = false, fault = false;
    bool eligible() const { return store && !virtualized && !fault && address >= ram && address + (1U << size) <= ram + 4096; }
};
struct Expected {
    uint64_t pc = 0, next = 0, value = 0, cause = 0, tval = 0;
    uint32_t instruction = 0;
    unsigned rd = 0;
    bool fault = false, memory = false;
    Intent intent;
};
struct Program {
    std::string name;
    std::vector<uint32_t> code;
    std::vector<Expected> trace;
    std::map<uint64_t, Intent> intents;
    std::map<uint64_t, uint64_t> ptes;
    std::vector<uint64_t> expectedPteAddresses;
    Bytes initial = initialBytes(), result = initialBytes();
    unsigned expectedStores = 0;
    bool needReuse = false, needBranch = false, needVirtualFault = false, needPmpFault = false, needVirtualSuccess = false;
};

// This interpreter is deliberately small and rejects encodings outside this
// fixture. Architectural intent is built before simulation, including faults.
static void interpret(Program &program) {
    for (const auto &pte : program.ptes) if (pte.first >= ram && pte.first + 8 <= ram + program.initial.size())
        for (unsigned byte = 0; byte < 8; ++byte) program.initial[pte.first - ram + byte] = pte.second >> (8 * byte);
    program.result = program.initial;
    std::array<uint64_t, 32> r{};
    uint64_t pc = base, mstatus = 0, satp = 0, pmpAddress = 0;
    uint8_t pmpConfig = 0;
    auto denied = [&](uint64_t address, unsigned bytes, unsigned privilege, bool writing) {
        const unsigned mode = (pmpConfig >> 3) & 3;
        uint64_t low = 0, high = 0;
        if (mode == 1) high = pmpAddress << 2;
        else if (mode == 2) { low = pmpAddress << 2; high = low + 4; }
        else if (mode == 3) {
            unsigned ones = 0;
            while (ones < 54 && ((pmpAddress >> ones) & 1)) ++ones;
            uint64_t bytesInRegion = UINT64_C(1) << (ones + 3);
            low = (pmpAddress << 2) & ~(bytesInRegion - 1);
            high = low + bytesInRegion;
        }
        if (!mode || address >= high || address + bytes <= low) return privilege != 3;
        if (address < low || address + bytes > high) return true;
        return (privilege != 3 || (pmpConfig & 128)) && !(pmpConfig & (writing ? 2 : 1));
    };
    auto translate = [&](uint64_t va, bool writing) -> std::pair<bool, uint64_t> {
        require((satp >> 60) == 8 && sext(va & ((UINT64_C(1) << 39) - 1), 39) == va,
            "authored virtual case must use canonical Sv39");
        uint64_t table = (satp & ((UINT64_C(1) << 44) - 1)) << 12;
        for (int level = 2; level >= 0; --level) {
            const uint64_t address = table + ((va >> (12 + 9 * level)) & 511) * 8;
            require(!denied(address, 8, 1, false), "authored page-table access denied by independent PMP");
            program.expectedPteAddresses.push_back(address);
            const auto pteAt = program.ptes.find(address);
            const uint64_t pte = pteAt == program.ptes.end() ? 0 : pteAt->second;
            if (!(pte & 1) || ((pte & 4) && !(pte & 2))) return {true, 0};
            if (pte & 10) {
                const unsigned pageBits = 12 + 9 * level;
                const uint64_t physicalPage = ((pte >> 10) & ((UINT64_C(1) << 44) - 1)) << 12;
                if ((pte & 16) || !(pte & 64) || (writing && (!(pte & 4) || !(pte & 128))) ||
                    (!writing && !(pte & 2)) || (physicalPage & ((UINT64_C(1) << pageBits) - 1))) return {true, 0};
                return {false, physicalPage | (va & ((UINT64_C(1) << pageBits) - 1))};
            }
            table = ((pte >> 10) & ((UINT64_C(1) << 44) - 1)) << 12;
        }
        return {true, 0};
    };
    for (unsigned budget = 0; pc >= base && (pc - base) / 4 < program.code.size(); ++budget) {
        require(budget < 1024 && !(pc & 3), "unbounded independent program");
        Expected e;
        e.pc = pc; e.next = pc + 4; e.instruction = program.code[(pc - base) / 4];
        const uint32_t x = e.instruction;
        const unsigned op = x & 127, rd = (x >> 7) & 31, rs1 = (x >> 15) & 31, rs2 = (x >> 20) & 31;
        const unsigned f = (x >> 12) & 7;
        if (op == 0x17) { e.rd = rd; e.value = pc + sext(x & 0xfffff000U, 32); }
        else if (op == 0x37) { e.rd = rd; e.value = sext(x & 0xfffff000U, 32); }
        else if (op == 0x13) {
            e.rd = rd;
            if (f == 0) e.value = r[rs1] + sext(x >> 20, 12);
            else if (f == 1) e.value = r[rs1] << ((x >> 20) & 63);
            else if (f == 5 && !(x >> 26)) e.value = r[rs1] >> ((x >> 20) & 63);
            else if (f == 6) e.value = r[rs1] | sext(x >> 20, 12);
            else throw std::runtime_error("unsupported independent immediate encoding");
        } else if (op == 0x33 && f == 6 && !(x >> 25)) { e.rd = rd; e.value = r[rs1] | r[rs2]; }
        else if (op == 0x63 && f == 0) {
            const uint64_t offset = sext(((x >> 31) << 12) | (((x >> 7) & 1) << 11) |
                (((x >> 25) & 63) << 5) | (((x >> 8) & 15) << 1), 13);
            if (r[rs1] == r[rs2]) e.next = pc + offset;
        } else if (op == 3 || op == 0x23) {
            e.memory = true;
            Intent &i = e.intent;
            i.pc = pc; i.store = op == 0x23; i.size = f & 3;
            const uint64_t offset = sext(i.store ? (((x >> 25) << 5) | ((x >> 7) & 31)) : x >> 20, 12);
            i.address = r[rs1] + offset; i.rawData = i.store ? r[rs2] : 0;
            i.data = i.rawData << ((i.address & 7) * 8);
            const unsigned bytes = 1U << i.size;
            i.mask = ((1U << bytes) - 1) << (i.address & 7);
            i.privilege = (mstatus & (UINT64_C(1) << 17)) ? ((mstatus >> 11) & 3) : 3;
            i.virtualized = i.privilege != 3 && (satp >> 60) != 0;
            i.denied = !i.virtualized && denied(i.address, bytes, i.privilege, i.store);
            const bool misaligned = i.address & (bytes - 1);
            i.localFault = misaligned || i.denied;
            i.physicalAddress = i.address;
            if (i.virtualized && !i.localFault) {
                const auto translated = translate(i.address, i.store);
                i.pageFault = translated.first; i.physicalAddress = translated.second;
                require(i.pageFault || !denied(i.physicalAddress, bytes, i.privilege, i.store),
                    "authored successful translation denied by independent physical PMP");
            }
            i.fault = i.localFault || i.pageFault;
            e.fault = i.fault; e.tval = i.address;
            e.cause = misaligned ? (i.store ? 6 : 4) : i.denied ? (i.store ? 7 : 5) : (i.store ? 15 : 13);
            i.cause = e.cause;
            if (!e.fault) {
                if (i.store) {
                    require(i.physicalAddress >= ram && i.physicalAddress + bytes <= ram + program.result.size(), "store outside independent RAM");
                    for (unsigned b = 0; b < bytes; ++b) program.result[i.physicalAddress - ram + b] = i.rawData >> (8 * b);
                    ++program.expectedStores;
                } else {
                    e.rd = rd;
                    if (i.physicalAddress == 0x0c000000) { require(bytes == 4, "APLIC width"); i.responseData = 0x80000004; }
                    else i.responseData = readBeat(program.result, i.physicalAddress);
                    e.value = i.responseData >> ((i.address & 7) * 8);
                    if (bytes < 8) e.value = (f & 4) ? e.value & ((UINT64_C(1) << (bytes * 8)) - 1) : sext(e.value & ((UINT64_C(1) << (bytes * 8)) - 1), bytes * 8);
                }
            }
            program.intents.emplace(pc, i);
        } else if (op == 0x73 && f == 1 && rd == 0) {
            switch (x >> 20) {
            case 0x300: mstatus = r[rs1]; break;
            case 0x180: satp = r[rs1]; break;
            case 0x3b0: pmpAddress = r[rs1] & ((UINT64_C(1) << 54) - 1); break;
            case 0x3a0: pmpConfig = r[rs1]; break;
            default: throw std::runtime_error("unsupported independent CSR encoding");
            }
        } else require(op == 0x0f && (f == 0 || f == 1), "unsupported independent instruction");
        program.trace.push_back(e);
        if (e.fault) break;
        if (e.rd) r[e.rd] = e.value;
        pc = e.next;
    }
}
static std::vector<Program> programs() {
    auto fresh = [](const std::string &name) {
        Program p; p.name = name;
        p.code = {0x00200097, addi(2, 0, 0x321)}; // AUIPC x1, 0x200 gives RAM, independent of DUT constants.
        return p;
    };
    std::vector<Program> result;
    Program p = fresh("physical-lineage-reuse-load-aplic-fence-context-recovery");
    p.needReuse = true; p.needBranch = true;
    p.code.push_back(store(2, 1, 0, 3));
    for (unsigned i = 0; i < 64; ++i) p.code.push_back(addi(3, 3, 1));
    p.code.insert(p.code.end(), {store(2, 1, 9, 0), store(2, 1, 10, 1), store(2, 1, 12, 2),
        load(10, 1, 64, 3), store(2, 1, 24, 3), 0x0c000237, load(11, 4, 0, 6),
        store(2, 1, 32, 3), 0x0ff0000f, store(2, 1, 40, 3), 0x000402b7, csrw(0x300, 5),
        store(2, 1, 48, 3)});
    // A dependency chain lets the store reach checked memory before the branch
    // resolves, without forcing any internal recovery/ready signal.
    for (unsigned i = 0; i < 32; ++i) p.code.push_back(addi(7, 7, 1));
    p.code.insert(p.code.end(), {beq(7, 7, 12), store(2, 1, 80, 3), addi(15, 0, 7),
        load(12, 1, 72, 3), store(2, 1, 56, 3), 0x0000100f, load(13, 1, 0, 3)});
    result.push_back(p);
    p = fresh("precise-misaligned-store");
    p.code.push_back(store(2, 1, 1, 3)); result.push_back(p);
    p = fresh("precise-locked-pmp-store"); p.needPmpFault = true;
    p.code.insert(p.code.end(), {store(2, 1, 0, 3), shift(5, 1, 2, true), ori(5, 5, 511),
        csrw(0x3b0, 5), addi(5, 0, 0x99), csrw(0x3a0, 5), store(2, 1, 16, 3)});
    result.push_back(p);
    p = fresh("precise-virtual-store-page-fault"); p.needVirtualFault = true;
    p.ptes[ram + 8] = 0;
    p.code.insert(p.code.end(), {store(2, 1, 0, 3), addi(5, 0, -1), csrw(0x3b0, 5),
        addi(5, 0, 15), csrw(0x3a0, 5), shift(5, 1, 12, true), addi(6, 0, 8),
        shift(6, 6, 60, false), (6U << 20) | (5U << 15) | (6U << 12) | (5U << 7) | 0x33,
        csrw(0x180, 5), 0x000212b7, addi(5, 5, -2048), csrw(0x300, 5),
        0x40002337, store(2, 6, 0, 3)});
    result.push_back(p);
    p = fresh("successful-virtual-store-no-proof"); p.needVirtualSuccess = true;
    p.ptes[ram + 0x2008] = (((ram + 0x3000) >> 12) << 10) | 1; // Root pointer, V only.
    p.ptes[ram + 0x3000] = ((ram >> 12) << 10) | 0xc7; // Aligned 2 MiB R/W/A/D leaf, U=0.
    p.code.insert(p.code.end(), {store(2, 1, 0, 3), addi(5, 0, -1), csrw(0x3b0, 5),
        addi(5, 0, 15), csrw(0x3a0, 5), shift(5, 1, 12, true), addi(5, 5, 2), addi(6, 0, 8),
        shift(6, 6, 60, false), (6U << 20) | (5U << 15) | (6U << 12) | (5U << 7) | 0x33,
        csrw(0x180, 5), 0x000212b7, addi(5, 5, -2048), csrw(0x300, 5),
        0x40000337, addi(6, 6, 128), addi(2, 0, 0x5a5), store(2, 6, 0, 3),
        csrw(0x300, 0), load(14, 1, 128, 3)});
    result.push_back(p);
    return result;
}

struct Request {
    uint64_t address = 0, data = 0, epoch = 0;
    unsigned mask = 0, size = 0, atomicOp = 0;
    bool write = false, atomic = false, virtualized = false, prechecked = false, uncached = false, prefetch = false;
    bool operator==(const Request &o) const {
        return std::tie(address, data, epoch, mask, size, atomicOp, write, atomic, virtualized, prechecked, uncached, prefetch) ==
            std::tie(o.address, o.data, o.epoch, o.mask, o.size, o.atomicOp, o.write, o.atomic, o.virtualized, o.prechecked, o.uncached, o.prefetch);
    }
};
struct Proof {
    Token token;
    uint64_t epoch = 0, address = 0, data = 0;
    unsigned mask = 0, size = 0;
    bool valid = false, head = false, pmp = false, physical = false, integer = false, legacy = false, checked = false;
    bool operator==(const Proof &o) const {
        return valid == o.valid && (!valid || (token == o.token &&
            std::tie(epoch, address, data, mask, size, head, pmp, physical, integer, legacy, checked) ==
            std::tie(o.epoch, o.address, o.data, o.mask, o.size, o.head, o.pmp, o.physical, o.integer, o.legacy, o.checked)));
    }
};
struct Boundary {
    Request request; Proof proof;
    bool valid = false, ready = false, responseValid = false, responseReady = false, error = false, pageFault = false;
    uint64_t responseData = 0;
};
#define GET(N, F) d.get_io$$##N##$$##F()
#define BOUNDARY_READER(N) static Boundary read_##N(Dut &d) { \
    Boundary b; b.valid = GET(N, valid); b.ready = GET(N, ready); \
    b.request = {GET(N, request$$address), GET(N, request$$data), GET(N, request$$translationEpoch), \
        unsigned(GET(N, request$$mask)), unsigned(GET(N, request$$size)), unsigned(GET(N, request$$atomicOp)), \
        bool(GET(N, request$$write)), bool(GET(N, request$$atomic)), bool(GET(N, request$$virtualized)), \
        bool(GET(N, request$$precheckedLoad)), bool(GET(N, request$$uncached)), bool(GET(N, request$$prefetchNextAllowed))}; \
    b.proof = {{GET(N, proof$$bits$$token$$tag), unsigned(GET(N, proof$$bits$$token$$index))}, \
        GET(N, proof$$bits$$epoch), GET(N, proof$$bits$$address), GET(N, proof$$bits$$data), \
        unsigned(GET(N, proof$$bits$$mask)), unsigned(GET(N, proof$$bits$$size)), bool(GET(N, proof$$valid)), \
        bool(GET(N, proof$$bits$$headAuthorized)), bool(GET(N, proof$$bits$$physicalPmpAllowed)), \
        bool(GET(N, proof$$bits$$originalPhysical)), bool(GET(N, proof$$bits$$integerOrigin)), \
        bool(GET(N, proof$$bits$$legacyPostedAccepted)), bool(GET(N, proof$$bits$$finalChecked))}; \
    b.responseValid = GET(N, responseValid); b.responseReady = GET(N, responseReady); \
    b.responseData = GET(N, response$$data); b.error = GET(N, response$$error); b.pageFault = GET(N, response$$pageFault); \
    return b; }
BOUNDARY_READER(lsu)
BOUNDARY_READER(storeIn)
BOUNDARY_READER(storeOut)
BOUNDARY_READER(backend)
BOUNDARY_READER(translated)
BOUNDARY_READER(checked)
BOUNDARY_READER(physical)
#undef BOUNDARY_READER
#undef GET

struct Witness { Intent intent; Token token; uint64_t epoch; };
static void validateCancelledRead(const Token &owner, const Token &redirect,
    const std::map<Token, Witness> &owners,
    const std::map<Token, std::pair<uint64_t, uint32_t>> &allocated,
    const std::map<Token, uint64_t> &order, uint64_t epoch) {
    require(owners.count(owner) && allocated.count(owner) && allocated.count(redirect) &&
        order.count(owner) && order.count(redirect), "cancel lacks original full-token lineage");
    const auto &w = owners.at(owner);
    require(w.token == owner && allocated.at(owner).first == w.intent.pc && w.epoch == epoch,
        "cancel changed original full-token/epoch");
    require(order.at(owner) > order.at(redirect), "cancel targeted older memory owner");
    require((allocated.at(owner).second & 127) == 3 && !w.intent.store && !w.intent.virtualized &&
        !w.intent.fault && !w.intent.denied, "cancel is not the authored physical readonly load");
}
static void requireCancelledReadDrained(bool transportPending) {
    require(!transportPending, "cancel dropped a late transport response");
}
static void requireMemoryCompletion(bool cancelled, bool active, bool respondedOrLocalFault) {
    require(!cancelled && active && respondedOrLocalFault, "memory completion has no live replied original owner");
}
static void requireMemoryRetirement(bool cancelled, bool completed) {
    require(!cancelled && completed, "memory retirement has no original noncancelled completion");
}
static void cancellationOracleControls() {
    const Token owner{17, 1}, redirect{16, 0};
    Intent intent; intent.pc = base; intent.address = ram; intent.physicalAddress = ram;
    const std::map<Token, Witness> original{{owner, {intent, owner, 1}}};
    const std::map<Token, std::pair<uint64_t, uint32_t>> instructions{
        {owner, {base, load(1, 2, 0, 3)}}, {redirect, {base - 4, beq(1, 1, 8)}}};
    const std::map<Token, uint64_t> order{{owner, 1}, {redirect, 0}};
    auto rejects = [](const auto &test) {
        bool rejected = false;
        try { test(); } catch (const std::runtime_error &) { rejected = true; }
        require(rejected, "cancel oracle failed to reject a broken owner");
    };
    validateCancelledRead(owner, redirect, original, instructions, order, 1);
    auto storeOwner = original; storeOwner.at(owner).intent.store = true;
    rejects([&] { validateCancelledRead(owner, redirect, storeOwner, instructions, order, 1); });
    auto older = order; older.at(owner) = 0; older.at(redirect) = 1;
    rejects([&] { validateCancelledRead(owner, redirect, original, instructions, older, 1); });
    rejects([&] { validateCancelledRead({18, 1}, redirect, original, instructions, order, 1); });
    rejects([&] { validateCancelledRead(owner, redirect, original, instructions, order, 2); });
    rejects([&] { requireCancelledReadDrained(true); });
    rejects([&] { requireMemoryCompletion(true, true, true); });
    rejects([&] { requireMemoryCompletion(false, true, false); });
    rejects([&] { requireMemoryRetirement(true, true); });
    rejects([&] { requireMemoryRetirement(false, false); });
    requireCancelledReadDrained(false);
    requireMemoryCompletion(false, true, true);
    requireMemoryRetirement(false, true);
    std::cout << "CPU_POSTED_CANCEL_ORACLE store_rejected=1 older_load_rejected=1 wrong_tag_rejected=1"
        << " wrong_epoch_rejected=1 late_response_rejected=1 fake_completion_rejected=1 fake_retirement_rejected=1\n";
}
struct Stats {
    uint64_t cycles = 0, commits = 0, launches = 0, proofs = 0, requestHolds = 0, responseHolds = 0;
    uint64_t reusedWhileBusy = 0, blockedLoad = 0, blockedAplic = 0, blockedSystem = 0;
    uint64_t blockedFence = 0, blockedFenceI = 0, blockedContext = 0;
    uint64_t retiredWhileBusy = 0, acknowledgedStoreIndexReuse = 0;
    uint64_t recoveryBusy = 0, traps = 0, pteReads = 0, epochChanges = 0, ownerAcks = 0;
    std::array<unsigned, 7> virtualRequests{}, virtualResponses{};
    unsigned virtualCompletions = 0;
};
static void driveDefaults(Dut &d) {
    d.set_io$$instruction0$$valid(0); d.set_io$$instruction1$$valid(0);
    d.set_io$$instruction0$$bits(0); d.set_io$$instruction1$$bits(0);
    d.set_io$$commitEnable(1); d.set_io$$externalBusy(0); d.set_io$$episodeActive(0);
    d.set_io$$memory$$request$$ready(0); d.set_io$$memory$$response$$valid(0);
    d.set_io$$memory$$response$$bits$$data(0); d.set_io$$memory$$response$$bits$$error(0);
    d.set_io$$memory$$response$$bits$$pageFault(0);
    d.set_io$$pte$$request$$ready(pteRequestReady); d.set_io$$pte$$response$$valid(0);
    d.set_io$$pte$$response$$bits$$data(0); d.set_io$$pte$$response$$bits$$error(0);
}

static Stats run(Program &program, bool enabled, bool injectToken, bool injectByte, Trace &trace) {
    trace.event(program.name, 0, "case_begin", {{"enabled", enabled}, {"owner_hold_cycles", 512},
        {"inject_token", injectToken}, {"inject_byte", injectByte}, {"expected_instructions", program.trace.size()}});
    for (unsigned index = 0; index < program.trace.size(); ++index) {
        const auto &e = program.trace[index];
        trace.event(program.name, 0, "expected", {{"ordinal", index}, {"pc", e.pc}, {"instruction", e.instruction},
            {"next_pc", e.next}, {"rd", e.rd}, {"value", e.value}, {"fault", e.fault},
            {"cause", e.cause}, {"tval", e.tval}, {"memory", e.memory}, {"store", e.intent.store},
            {"virtualized", e.intent.virtualized}, {"address", e.intent.address}, {"physical_address", e.intent.physicalAddress},
            {"raw_data", e.intent.rawData}, {"lane_data", e.intent.data}, {"mask", e.intent.mask},
            {"size", e.intent.size}, {"privilege", e.intent.privilege}, {"pmp_denied", e.intent.denied},
            {"page_fault", e.intent.pageFault}, {"response_data", e.intent.responseData}, {"proof_eligible", e.intent.eligible()}});
    }
    for (const auto &pte : program.ptes)
        trace.event(program.name, 0, "expected_pte", {{"address", pte.first}, {"data", pte.second}});
    Dut d;
    driveDefaults(d); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    Stats stats;
    Bytes memory = program.initial;
    std::map<Token, std::pair<uint64_t, uint32_t>> allocated;
    std::map<Token, uint64_t> allocationOrder;
    std::map<unsigned, Token> lastRetired;
    std::array<std::deque<Witness>, 7> expected;
    std::array<std::deque<Witness>, 7> returnOwners;
    std::array<Boundary, 7> previous{};
    const std::array<std::string, 7> names = {"lsu", "request-fifo/store-in", "store-out", "backend", "adapter-in", "checked/router-in", "external-memory"};
    std::set<Token> launched, committedStores, completedStores;
    std::set<Token> activeLsuOwners;
    std::set<Token> cancelledLoadOwners;
    std::set<Token> lsuReturnedOwners, completedMemoryOwners;
    std::set<Token> externalOwnerTokens, acknowledgedExternalStores;
    std::map<Token, Witness> authorized;
    std::map<Token, Witness> memoryOwners;
    std::map<Token, uint64_t> localAck;
    unsigned retired = 0, physicalStores = 0, settled = 0, heldRequestCycles = 0;
    uint64_t fetch = base, ownerSince = 0, oldEpoch = 0, previousOwnership = UINT64_MAX;
    bool externalBusy = false, episode = false, trapSeen = false, ptePending = false;
    bool responsePending = false, responseForUnaccepted = false;
    std::pair<bool, Token> responseStoreOwner{};
    uint64_t responseData = 0, pteData = 0;
    Request heldExternal;
    bool haveHeldExternal = false;
    for (unsigned cycle = 0; cycle < 12000; ++cycle) {
        stats.cycles = cycle + 1;
        if (externalBusy && cycle - ownerSince >= 512) {
            trace.event(program.name, cycle, "environment_owner_release", {{"owner_since", ownerSince},
                {"retained_tokens", externalOwnerTokens.size()}});
            for (const auto &owner : externalOwnerTokens) require(acknowledgedExternalStores.count(owner),
                "environment released a retained store before its real response");
            externalBusy = false; externalOwnerTokens.clear();
        }
        const bool ownerAtEdge = externalBusy;
        // Snapshot responsibility accepted on earlier ticks before observing any
        // new request in this tick. A request born in the new epoch must not be
        // mistaken for an old owner merely because it precedes the context check
        // in this host loop. Include every transport stage and full LSU token.
        std::set<Token> olderOwners = activeLsuOwners;
        for (const auto &stage : expected) for (const auto &w : stage) olderOwners.insert(w.token);
        for (const auto &stage : returnOwners) for (const auto &w : stage) olderOwners.insert(w.token);
        const bool enable = cycle < 30 || cycle % 11 >= 3;
        d.set_io$$commitEnable(enable);
        d.set_io$$externalBusy(enabled && externalBusy); d.set_io$$episodeActive(enabled && episode);
        auto word = [&](uint64_t pc) { return pc >= base && !(pc & 3) && (pc - base) / 4 < program.code.size(); };
        d.set_io$$instruction0$$valid(!trapSeen && word(fetch));
        d.set_io$$instruction1$$valid(!trapSeen && word(fetch) && word(fetch + 4));
        d.set_io$$instruction0$$bits(word(fetch) ? program.code[(fetch - base) / 4] : 0);
        d.set_io$$instruction1$$bits(word(fetch + 4) ? program.code[(fetch + 4 - base) / 4] : 0);
        // A known, held offer receives a legal zero-latency response when ready
        // finally rises. The real registered router owner holds this response.
        const bool accepting = haveHeldExternal && heldRequestCycles >= 4 && !responsePending;
        if (accepting) {
            responsePending = true; responseForUnaccepted = true;
            responseData = heldExternal.write ? 0 : readBeat(memory, heldExternal.address);
        }
        d.set_io$$memory$$request$$ready(accepting);
        d.set_io$$memory$$response$$valid(responsePending);
        d.set_io$$memory$$response$$bits$$data(responseData);
        d.set_io$$pte$$response$$valid(ptePending);
        d.set_io$$pte$$response$$bits$$data(pteData);
        trace.event(program.name, cycle, "drive", {{"fetch_pc", fetch}, {"commit_enable", enable},
            {"instruction0_valid", !trapSeen && word(fetch)},
            {"instruction0", word(fetch) ? program.code[(fetch - base) / 4] : 0},
            {"instruction1_valid", !trapSeen && word(fetch) && word(fetch + 4)},
            {"instruction1", word(fetch + 4) ? program.code[(fetch + 4 - base) / 4] : 0},
            {"external_busy", enabled && externalBusy}, {"episode_active", enabled && episode},
            {"memory_ready", accepting}, {"memory_response_valid", responsePending},
            {"memory_response_data", responseData}, {"pte_response_valid", ptePending}, {"pte_response_data", pteData}});
        d.step();
        const std::array<Boundary, 7> boundaries = {read_lsu(d), read_storeIn(d), read_storeOut(d),
            read_backend(d), read_translated(d), read_checked(d), read_physical(d)};
        const uint64_t ownership = uint64_t(ownerAtEdge) | (uint64_t(episode) << 1) |
            (uint64_t(d.get_io$$busy()) << 2) | (uint64_t(d.get_io$$seal()) << 3) | (uint64_t(d.get_io$$endEpisode()) << 4);
        if (ownership != previousOwnership) {
            trace.event(program.name, cycle, "ownership_state", {{"external_busy", ownerAtEdge}, {"episode_input", episode},
                {"cpu_busy", d.get_io$$busy()}, {"seal", d.get_io$$seal()}, {"end_episode", d.get_io$$endEpisode()}});
            previousOwnership = ownership;
        }
        auto rememberRename = [&](bool valid, uint64_t pc, uint32_t instruction, Token token) {
            if (!valid) return;
            trace.event(program.name, cycle, "rename", {{"pc", pc}, {"instruction", instruction},
                {"token_tag", token.tag}, {"token_index", token.index}, {"external_busy", ownerAtEdge}});
            require(word(pc) && program.code[(pc - base) / 4] == instruction, "rename must own an authored raw instruction");
            require(allocated.emplace(token, std::make_pair(pc, instruction)).second, "full token reused");
            const uint64_t ordinal = allocationOrder.size();
            allocationOrder.emplace(token, ordinal);
            auto prior = lastRetired.find(token.index);
            if (ownerAtEdge && prior != lastRetired.end() && prior->second.tag != token.tag) ++stats.reusedWhileBusy;
            if (ownerAtEdge) for (const auto &owner : externalOwnerTokens)
                if (owner.index == token.index && owner.tag != token.tag && committedStores.count(owner) &&
                    acknowledgedExternalStores.count(owner)) ++stats.acknowledgedStoreIndexReuse;
        };
#define RENAME(N) rememberRename(d.get_io$$rename##N##$$valid(), d.get_io$$renamePc##N(), \
    d.get_io$$renameInstruction##N(), {d.get_io$$rename##N##$$bits$$tag(), unsigned(d.get_io$$rename##N##$$bits$$index())})
        RENAME(0); RENAME(1);
#undef RENAME
        const Token head{d.get_io$$headToken$$tag(), unsigned(d.get_io$$headToken$$index())};
        if (d.get_io$$startValid()) trace.event(program.name, cycle, "head_launch", {
            {"ready", d.get_io$$startReady()}, {"token_tag", d.get_io$$start$$token$$tag()},
            {"token_index", d.get_io$$start$$token$$index()}, {"pc", d.get_io$$start$$pc()},
            {"head_valid", d.get_io$$headValid()}, {"head_tag", head.tag}, {"head_index", head.index},
            {"head_pc", d.get_io$$headPc()}, {"head_instruction", d.get_io$$headInstruction()},
            {"address", d.get_io$$start$$address()}, {"raw_data", d.get_io$$start$$data()},
            {"size", d.get_io$$start$$size()}, {"store", d.get_io$$start$$store()},
            {"virtualized", d.get_io$$start$$virtualized()}, {"atomic", d.get_io$$start$$atomic()},
            {"access_denied", d.get_io$$start$$accessDenied()}, {"pmp_denied", d.get_io$$pmpDenied()},
            {"privilege", d.get_io$$dataPrivilege()}, {"epoch", d.get_io$$contextEpoch()}});
        if (d.get_io$$startValid() && d.get_io$$startReady()) {
            ++stats.launches;
            const Token token{d.get_io$$start$$token$$tag(), unsigned(d.get_io$$start$$token$$index())};
            auto allocation = allocated.find(token);
            require(allocation != allocated.end(), "LSU start has no raw-instruction rename token");
            const uint64_t pc = allocation->second.first;
            auto raw = program.intents.find(pc);
            require(raw != program.intents.end(), "wrong-path memory instruction launched");
            const Intent &intent = raw->second;
            require(launched.insert(token).second, "memory token launched twice");
            require(activeLsuOwners.insert(token).second, "memory token already owns an LSU");
            require(d.get_io$$start$$pc() == pc && d.get_io$$start$$address() == intent.address &&
                d.get_io$$start$$size() == intent.size && bool(d.get_io$$start$$store()) == intent.store &&
                bool(d.get_io$$start$$virtualized()) == intent.virtualized && !d.get_io$$start$$atomic(),
                "raw ISA memory intent differs at LSU launch");
            require(!intent.store || d.get_io$$start$$data() == intent.rawData, "raw store operand differs at launch");
            require(bool(d.get_io$$start$$accessDenied()) == intent.denied &&
                d.get_io$$dataPrivilege() == intent.privilege, "raw CSR/PMP model disagrees with launch authorization");
            if (!intent.virtualized) require(bool(d.get_io$$pmpDenied()) == intent.denied, "PMP verdict belongs to another physical request");
            if (intent.store) require(d.get_io$$headValid() && token == head && d.get_io$$headPc() == pc,
                "store launch not associated with actual full-token ROB head");
            Witness witness{intent, token, d.get_io$$contextEpoch()};
            memoryOwners.emplace(token, witness);
            if (!intent.localFault) expected[0].push_back(witness);
            if (intent.eligible()) authorized.emplace(token, witness);
            if (enabled && ownerAtEdge && !intent.eligible()) require(false, "ordinary load/MMIO/fault launched across posted ownership");
        }
        std::optional<Witness> acceptedExternalStore;
        std::array<std::optional<Witness>, 7> offered;
        for (unsigned stage = 0; stage < boundaries.size(); ++stage) {
            const auto &b = boundaries[stage]; const auto &old = previous[stage];
            const std::string where = program.name + " " + names[stage] + " cycle=" + std::to_string(cycle);
            if (b.valid || (old.valid && !old.ready)) trace.event(program.name, cycle, "request", {{"valid", b.valid}, {"ready", b.ready},
                {"address", b.request.address}, {"data", b.request.data}, {"mask", b.request.mask}, {"size", b.request.size},
                {"write", b.request.write}, {"atomic", b.request.atomic}, {"atomic_op", b.request.atomicOp},
                {"virtualized", b.request.virtualized}, {"prechecked", b.request.prechecked},
                {"translation_epoch", b.request.epoch}, {"uncached", b.request.uncached}, {"prefetch", b.request.prefetch},
                {"proof_valid", b.proof.valid}, {"proof_tag", b.proof.token.tag}, {"proof_index", b.proof.token.index},
                {"proof_epoch", b.proof.epoch}, {"proof_address", b.proof.address}, {"proof_data", b.proof.data},
                {"proof_mask", b.proof.mask}, {"proof_size", b.proof.size}, {"head_authorized", b.proof.head},
                {"pmp_allowed", b.proof.pmp}, {"original_physical", b.proof.physical}, {"integer_origin", b.proof.integer},
                {"legacy_accepted", b.proof.legacy}, {"final_checked", b.proof.checked}}, names[stage]);
            if (b.responseValid || (old.responseValid && !old.responseReady)) {
                const bool hasOwner = !returnOwners[stage].empty();
                const Token owner = hasOwner ? returnOwners[stage].front().token : Token{};
                trace.event(program.name, cycle, "response", {{"valid", b.responseValid}, {"ready", b.responseReady}, {"data", b.responseData},
                    {"error", b.error}, {"page_fault", b.pageFault}, {"prior_owner_valid", hasOwner},
                    {"prior_owner_tag", owner.tag}, {"prior_owner_index", owner.index}}, names[stage]);
            }
            if (old.valid && !old.ready) {
                require(b.valid && b.request == old.request && b.proof == old.proof, where + " held request/proof changed");
                ++stats.requestHolds;
            }
            if (old.responseValid && !old.responseReady) {
                require(b.responseValid && b.responseData == old.responseData && b.error == old.error && b.pageFault == old.pageFault,
                    where + " held real response changed");
                ++stats.responseHolds;
            }
            require(!b.proof.valid || (enabled && b.valid), where + " proof without a real request");
            if (b.valid) {
                auto queued = expected[stage].begin();
                if (stage == 0) {
                    require(d.get_io$$requestOwner$$valid(), where + " LSU request lacks original owner");
                    const Token owner{d.get_io$$requestOwner$$bits$$tag(), unsigned(d.get_io$$requestOwner$$bits$$index())};
                    queued = std::find_if(expected[0].begin(), expected[0].end(),
                        [&](const Witness &w) { return w.token == owner; });
                    require(queued != expected[0].end(), where + " LSU arbitration owner has no original launch");
                }
                if (queued != expected[stage].end()) offered[stage] = *queued;
                else {
                    // Direct SB traffic, the backend mux, response-buffer request
                    // passthrough and router can expose an unaccepted offer. Carry
                    // that original upstream owner; never synthesize one from PA.
                    require((stage == 2 || stage == 3 || stage == 4 || stage == 6) && offered[stage - 1].has_value(),
                        where + " request has no original accepted or passthrough owner");
                    offered[stage] = offered[stage - 1];
                }
                const Witness w = *offered[stage];
                const bool wantsProof = enabled && w.intent.eligible();
                trace.event(program.name, cycle, "request_owner", {{"token_tag", w.token.tag}, {"token_index", w.token.index},
                    {"pc", w.intent.pc}, {"original_address", w.intent.address}, {"physical_address", w.intent.physicalAddress},
                    {"original_virtual", w.intent.virtualized}, {"expected_proof", wantsProof},
                    {"epoch", w.epoch}, {"ready", b.ready}}, names[stage]);
                require(b.proof.valid == wantsProof, where + " missing or unauthorized original-origin proof");
                require(b.request.address == (stage >= 5 ? w.intent.physicalAddress : w.intent.address) &&
                    (!w.intent.store || b.request.data == w.intent.data) && b.request.mask == w.intent.mask &&
                    b.request.size == w.intent.size && b.request.write == w.intent.store && !b.request.atomic &&
                    b.request.virtualized == (stage < 5 && w.intent.virtualized) &&
                    !b.request.prechecked && !b.request.uncached,
                    where + " original memory intent/address/lane/order mismatch");
                if (wantsProof) {
                    Token wanted = w.token; if (injectToken) wanted.tag ^= 1;
                    const uint64_t wantedData = w.intent.data ^ (injectByte ? 1 : 0);
                    trace.event(program.name, cycle, "proof_compare", {{"original_tag", w.token.tag},
                        {"original_index", w.token.index}, {"wanted_tag", wanted.tag}, {"wanted_index", wanted.index},
                        {"actual_tag", b.proof.token.tag}, {"actual_index", b.proof.token.index},
                        {"wanted_data", wantedData}, {"actual_data", b.proof.data},
                        {"wanted_epoch", w.epoch}, {"actual_epoch", b.proof.epoch}}, names[stage]);
                    require(b.proof.token == wanted && b.proof.address == w.intent.address && b.proof.data == wantedData &&
                        b.proof.mask == w.intent.mask && b.proof.size == w.intent.size && b.proof.epoch == w.epoch,
                        where + " immutable full-token/epoch/payload lineage mismatch");
                    require(b.proof.head && b.proof.pmp && b.proof.physical && b.proof.integer &&
                        b.proof.legacy == (stage >= 2) && b.proof.checked == (stage >= 5),
                        where + " authority appeared at the wrong production boundary");
                    ++stats.proofs;
                }
                if (b.ready) {
                    require(queued != expected[stage].end(), where + " output accepted before its original input owner");
                    expected[stage].erase(queued);
                    returnOwners[stage].push_back(w);
                    if (w.intent.virtualized && w.intent.store) ++stats.virtualRequests[stage];
                    const bool faultTerminated = stage == 4 && w.intent.pageFault;
                    const bool localAplic = stage == 5 && w.intent.physicalAddress == 0x0c000000;
                    if (stage + 1 < boundaries.size() && !faultTerminated && !localAplic)
                        expected[stage + 1].push_back(w);
                    if (stage == 6 && w.intent.store) acceptedExternalStore = w;
                }
                if (enabled && ownerAtEdge && stage >= 1 && !w.intent.eligible())
                    require(!b.ready, where + " ordinary request crossed retained external owner");
            }
            if (b.responseValid) {
                require(!returnOwners[stage].empty(), where + " response without original full-token owner");
                const auto &w = returnOwners[stage].front();
                trace.event(program.name, cycle, "response_owner", {{"token_tag", w.token.tag}, {"token_index", w.token.index},
                    {"pc", w.intent.pc}, {"expected_data", w.intent.responseData}, {"expected_page_fault", w.intent.pageFault},
                    {"ready", b.responseReady}}, names[stage]);
                require(b.error == w.intent.pageFault && b.pageFault == w.intent.pageFault &&
                    b.responseData == w.intent.responseData, where + " response differs from original raw memory intent");
                if (b.responseReady) {
                    if (stage == 0) require(lsuReturnedOwners.insert(w.token).second,
                        "duplicate original LSU response");
                    if (stage == 0 && w.intent.store && !w.intent.fault) {
                        require(!localAck.count(w.token), where + " duplicate store acknowledgement");
                        localAck[w.token] = cycle;
                    }
                    if (w.intent.virtualized && w.intent.store) ++stats.virtualResponses[stage];
                    returnOwners[stage].pop_front();
                }
            }
            previous[stage] = b;
        }
        if (d.get_io$$completionValid()) trace.event(program.name, cycle, "completion", {
            {"ready", d.get_io$$completionReady()}, {"token_tag", d.get_io$$completion$$token$$tag()},
            {"token_index", d.get_io$$completion$$token$$index()}, {"data", d.get_io$$completion$$data()},
            {"next_pc", d.get_io$$completion$$nextPc()}, {"exception", d.get_io$$completion$$exception()},
            {"cause", d.get_io$$completion$$cause()}, {"tval", d.get_io$$completion$$tval()}});
        if (d.get_io$$completionValid() && d.get_io$$completionReady()) {
            const Token token{d.get_io$$completion$$token$$tag(), unsigned(d.get_io$$completion$$token$$index())};
            require(memoryOwners.count(token), "completion lost original raw memory owner");
            const auto &w = memoryOwners.at(token);
            requireMemoryCompletion(cancelledLoadOwners.count(token), activeLsuOwners.count(token),
                lsuReturnedOwners.count(token) || w.intent.localFault);
            require(activeLsuOwners.erase(token) == 1 && completedMemoryOwners.insert(token).second,
                "completion lost or duplicated its active full-token LSU owner");
            if (w.intent.store) {
                require(completedStores.insert(token).second && bool(d.get_io$$completion$$exception()) == w.intent.fault,
                    "store completion duplicated or changed original fault status");
                if (w.intent.fault) require(d.get_io$$completion$$cause() == w.intent.cause &&
                    d.get_io$$completion$$tval() == w.intent.address, "store completion lost precise original fault address");
                else require(localAck.count(token) && d.get_io$$completion$$data() == 0,
                    "store completed without its original ordered response");
                if (w.intent.virtualized) ++stats.virtualCompletions;
            }
        }
        if (enabled && ownerAtEdge && d.get_io$$headValid()) {
            const unsigned opcode = d.get_io$$headInstruction() & 127;
            auto i = program.intents.find(d.get_io$$headPc());
            if (i != program.intents.end() && !i->second.store) {
                if (i->second.address == 0x0c000000) ++stats.blockedAplic;
                else ++stats.blockedLoad;
            }
            if (opcode == 0x0f || opcode == 0x73) {
                ++stats.blockedSystem;
                if (opcode == 0x73) ++stats.blockedContext;
                else if ((d.get_io$$headInstruction() >> 12) & 7) ++stats.blockedFenceI;
                else ++stats.blockedFence;
                require(!d.get_io$$systemStart(), "system boundary launched before posted drain");
            }
            if (d.get_io$$recovering() || d.get_io$$redirect$$valid()) ++stats.recoveryBusy;
        }
        const uint64_t epoch = d.get_io$$contextEpoch();
        if (epoch != oldEpoch || cycle == 0) trace.event(program.name, cycle, "context", {
            {"old_epoch", oldEpoch}, {"epoch", epoch}, {"satp", d.get_io$$vm$$satp()},
            {"sum", d.get_io$$vm$$sum()}, {"mxr", d.get_io$$vm$$mxr()},
            {"data_privilege", d.get_io$$vm$$dataPrivilege()}, {"external_busy", ownerAtEdge},
            {"older_accepted_owners", olderOwners.size()}});
        if (cycle > 3 && epoch != oldEpoch) {
            for (const auto &owner : olderOwners) trace.event(program.name, cycle, "context_old_owner", {
                {"token_tag", owner.tag}, {"token_index", owner.index}});
            requireEpochDrain(ownerAtEdge, olderOwners);
            ++stats.epochChanges;
        }
        oldEpoch = epoch;
        auto commit = [&](bool valid, Token token, uint64_t pc, uint32_t instruction, unsigned rd,
            bool writes, uint64_t value, uint64_t next) {
            if (!valid) return;
            trace.event(program.name, cycle, "commit", {{"token_tag", token.tag}, {"token_index", token.index},
                {"pc", pc}, {"instruction", instruction}, {"rd", rd}, {"writes_rd", writes},
                {"data", value}, {"next_pc", next}, {"commit_enabled", enable}, {"expected_ordinal", retired}});
            require(enable && retired < program.trace.size(), "unexpected/disabled retirement");
            const Expected &e = program.trace[retired];
            require(!e.fault && pc == e.pc && instruction == e.instruction && next == e.next && rd == e.rd &&
                writes == (rd != 0) && (!rd || value == e.value), "independent commit mismatch pc=" + std::to_string(pc));
            auto allocation = allocated.find(token);
            require(allocation != allocated.end() && allocation->second == std::make_pair(pc, instruction), "commit changed original rename full token");
            if (e.memory) requireMemoryRetirement(cancelledLoadOwners.count(token), completedMemoryOwners.count(token));
            if (e.memory && e.intent.store) {
                require(localAck.count(token) && completedStores.count(token), "store retired before its original acknowledgement/completion");
                require(committedStores.insert(token).second, "store retired twice");
            }
            lastRetired[token.index] = token; ++retired; ++stats.commits;
            if (ownerAtEdge) ++stats.retiredWhileBusy;
        };
#define COMMIT(N) commit(d.get_io$$commit##N##$$valid(), \
    {d.get_io$$commit##N##$$bits$$token$$tag(), unsigned(d.get_io$$commit##N##$$bits$$token$$index())}, \
    d.get_io$$commit##N##$$bits$$pc(), d.get_io$$commit##N##$$bits$$instruction(), \
    d.get_io$$commit##N##$$bits$$rd(), d.get_io$$commit##N##$$bits$$writesRd(), \
    d.get_io$$commit##N##$$bits$$data(), d.get_io$$commit##N##$$bits$$nextPc())
        COMMIT(0); COMMIT(1);
#undef COMMIT
        if (d.get_io$$trap$$valid()) {
            trace.event(program.name, cycle, "trap", {{"token_tag", d.get_io$$trap$$bits$$token$$tag()},
                {"token_index", d.get_io$$trap$$bits$$token$$index()}, {"pc", d.get_io$$trap$$bits$$pc()},
                {"cause", d.get_io$$trap$$bits$$cause()}, {"tval", d.get_io$$trap$$bits$$tval()}});
            require(!trapSeen && retired < program.trace.size(), "unexpected/repeated trap");
            const auto &e = program.trace[retired];
            require(e.fault && d.get_io$$trap$$bits$$pc() == e.pc && d.get_io$$trap$$bits$$cause() == e.cause &&
                d.get_io$$trap$$bits$$tval() == e.tval, "imprecise raw-ISA store fault");
            const Token token{d.get_io$$trap$$bits$$token$$tag(), unsigned(d.get_io$$trap$$bits$$token$$index())};
            require(allocated.count(token) && allocated.at(token).first == e.pc && !authorized.count(token) &&
                completedStores.count(token), "fault acquired posted authority or lost original completion token");
            trapSeen = true; ++retired; ++stats.traps;
        }
        if (d.get_io$$recovering() || d.get_io$$redirect$$valid()) trace.event(program.name, cycle, "recovery", {
            {"recovering", d.get_io$$recovering()}, {"redirect_valid", d.get_io$$redirect$$valid()},
            {"token_tag", d.get_io$$redirect$$bits$$token$$tag()}, {"token_index", d.get_io$$redirect$$bits$$token$$index()},
            {"pc", d.get_io$$redirect$$bits$$pc()}, {"target", d.get_io$$redirect$$bits$$target()},
            {"external_busy", ownerAtEdge}});
        if (d.get_io$$redirect$$valid()) {
            const Token redirect{d.get_io$$redirect$$bits$$token$$tag(), unsigned(d.get_io$$redirect$$bits$$token$$index())};
            require(allocationOrder.count(redirect), "redirect lost original rename full token");
            for (const auto &owner : activeLsuOwners) if (allocationOrder.at(owner) > allocationOrder.at(redirect)) {
                validateCancelledRead(owner, redirect, memoryOwners, allocated, allocationOrder, epoch);
                require(!authorized.count(owner), "recovery attempted to cancel an authorized store owner");
                cancelledLoadOwners.insert(owner);
                trace.event(program.name, cycle, "cancel_readonly_owner", {{"token_tag", owner.tag},
                    {"token_index", owner.index}, {"redirect_tag", redirect.tag}, {"redirect_index", redirect.index}});
            }
        }
        for (const auto &owner : cancelledLoadOwners) if (activeLsuOwners.count(owner)) {
            auto containsOwner = [&](const auto &stages) {
                return std::any_of(stages.begin(), stages.end(), [&](const auto &stage) {
                    return std::any_of(stage.begin(), stage.end(), [&](const Witness &w) { return w.token == owner; });
                });
            };
            // A cancelled read drains the real transport, then LSU discards its
            // result without a completion. Never erase accepted transport work.
            const bool transportPending = containsOwner(expected) || containsOwner(returnOwners);
            if (!transportPending) {
                requireCancelledReadDrained(transportPending);
                require(lsuReturnedOwners.count(owner), "cancel lost its actual late LSU response");
                activeLsuOwners.erase(owner);
                trace.event(program.name, cycle, "cancel_readonly_drained", {{"token_tag", owner.tag}, {"token_index", owner.index}});
            }
        }
        const auto &physical = boundaries[6];
        if (physical.valid && physical.ready) {
            require(accepting && responseForUnaccepted && physical.request == heldExternal, "external request changed before checked acceptance");
            responseForUnaccepted = false;
            if (physical.request.write) {
                require(acceptedExternalStore.has_value(), "external store lost original independent memory token");
                responseStoreOwner = {true, acceptedExternalStore->token};
                ++physicalStores;
                for (unsigned byte = 0; byte < 8; ++byte) if (physical.request.mask & (1U << byte))
                    memory[(physical.request.address & ~UINT64_C(7)) - ram + byte] = physical.request.data >> (8 * byte);
                if (enabled && acceptedExternalStore->intent.eligible()) {
                    if (!externalBusy) { externalBusy = true; episode = true; ownerSince = cycle; }
                    externalOwnerTokens.insert(acceptedExternalStore->token);
                    trace.event(program.name, cycle, "environment_owner_accept", {
                        {"token_tag", acceptedExternalStore->token.tag}, {"token_index", acceptedExternalStore->token.index},
                        {"pc", acceptedExternalStore->intent.pc}, {"address", physical.request.address},
                        {"owner_since", ownerSince}});
                }
            } else responseStoreOwner = {};
            haveHeldExternal = false; heldRequestCycles = 0;
        } else if (physical.valid && !physical.ready) {
            if (!haveHeldExternal) { heldExternal = physical.request; haveHeldExternal = true; heldRequestCycles = 0; }
            require(physical.request == heldExternal, "external held raw request changed"); ++heldRequestCycles;
        }
        if (responsePending && physical.responseReady) {
            trace.event(program.name, cycle, "environment_response_ack", {{"store_owner", responseStoreOwner.first},
                {"token_tag", responseStoreOwner.second.tag}, {"token_index", responseStoreOwner.second.index},
                {"data", responseData}, {"request_accepted", !responseForUnaccepted}, {"external_busy", externalBusy}});
            require(!responseForUnaccepted, "response consumed before original request acceptance");
            if (responseStoreOwner.first) acknowledgedExternalStores.insert(responseStoreOwner.second);
            responsePending = false; ++stats.ownerAcks;
        }
        if (ptePending) trace.event(program.name, cycle, "pte_response", {
            {"data", pteData}, {"ready", d.get_io$$pte$$response$$ready()}});
        if (d.get_io$$pte$$request$$valid()) trace.event(program.name, cycle, "pte_request", {
            {"address", d.get_io$$pte$$request$$bits()}, {"ready", pteRequestReady}});
        if (d.get_io$$pte$$request$$valid() && pteRequestReady) {
            const uint64_t address = d.get_io$$pte$$request$$bits();
            require(!ptePending && stats.pteReads < program.expectedPteAddresses.size() &&
                address == program.expectedPteAddresses[stats.pteReads] && program.ptes.count(address),
                "walker request does not match independently walked raw SATP/VA/PTE bytes");
            pteData = program.ptes.at(address);
            ptePending = true; ++stats.pteReads;
        } else if (ptePending && d.get_io$$pte$$response$$ready()) ptePending = false;
        if (enabled && d.get_io$$endEpisode()) {
            trace.event(program.name, cycle, "environment_episode_end", {{"external_busy", ownerAtEdge}});
            require(!ownerAtEdge, "episode ended while external owner retained"); episode = false;
        }
        fetch = d.get_io$$nextFetchPc();
        if (retired == program.trace.size() && !externalBusy && !responsePending && !ptePending && d.get_io$$idle()) {
            if (++settled >= 12) break;
        } else settled = 0;
    }
    require(settled >= 12, program.name + " timeout retired=" + std::to_string(retired));
    require(activeLsuOwners.empty(), "final drain lost an accepted full-token LSU owner");
    require(physicalStores == program.expectedStores && committedStores.size() == program.expectedStores,
        program.name + " dropped/duplicated/wrong-path store");
    require(memory == program.result, program.name + " independent final byte image mismatch");
    for (unsigned stage = 0; stage < expected.size(); ++stage) {
        require(expected[stage].empty(), names[stage] + " lost an original memory token");
        require(returnOwners[stage].empty(), names[stage] + " lost an original response owner");
    }
    require(stats.pteReads == program.expectedPteAddresses.size(), "missing independently expected page-table read");
    if (enabled && program.expectedStores) require(stats.proofs && stats.requestHolds && stats.responseHolds,
        program.name + " missing actual held request/proof/return coverage");
    if (enabled && program.needReuse) require(stats.reusedWhileBusy && stats.acknowledgedStoreIndexReuse &&
        stats.retiredWhileBusy > 16 && stats.blockedLoad && stats.blockedAplic &&
        stats.blockedFence && stats.blockedFenceI && stats.blockedContext,
        "missing ROB reuse or ordinary load/APLIC/fence/context waiting coverage");
    if (enabled && program.needBranch) require(stats.recoveryBusy, "branch recovery did not overlap retained external ownership");
    if (program.needVirtualFault) require(stats.pteReads == 1 && stats.traps == 1, "virtual store fault did not use real walker");
    if (program.needVirtualFault || program.needVirtualSuccess) {
        for (unsigned stage = 0; stage < 7; ++stage) {
            const unsigned transfers = program.needVirtualSuccess || stage < 5 ? 1 : 0;
            require(stats.virtualRequests[stage] == transfers && stats.virtualResponses[stage] == transfers,
                names[stage] + " missing exact original virtual-store request/response lineage");
        }
        require(stats.virtualCompletions == 1, "virtual store lost its original full-token completion");
    }
    if (program.needVirtualSuccess) require(stats.pteReads == 2 && stats.traps == 0,
        "successful virtual-store no-proof case did not walk and retire normally");
    if (program.needPmpFault) require(stats.traps == 1, "PMP store fault missing");
    trace.event(program.name, stats.cycles, "case_pass", {{"commits", stats.commits}, {"stores", physicalStores},
        {"proofs", stats.proofs}, {"traps", stats.traps}, {"pte_reads", stats.pteReads},
        {"request_holds", stats.requestHolds}, {"response_holds", stats.responseHolds},
        {"acknowledged_store_index_reuse", stats.acknowledgedStoreIndexReuse}});
    std::cout << "CPU_POSTED_LINEAGE case=" << program.name << " mode=" << (enabled ? "on" : "off")
        << " commits=" << stats.commits << " stores=" << physicalStores << " proofs=" << stats.proofs
        << " requestHolds=" << stats.requestHolds << " realResponseHolds=" << stats.responseHolds
        << " robReuseWhileBusy=" << stats.reusedWhileBusy << " loadWait=" << stats.blockedLoad
        << " ackedStoreIndexReuse=" << stats.acknowledgedStoreIndexReuse << " retiredWhileBusy=" << stats.retiredWhileBusy
        << " aplicWait=" << stats.blockedAplic << " systemWait=" << stats.blockedSystem
        << " fenceWait=" << stats.blockedFence << " fenceIWait=" << stats.blockedFenceI
        << " contextWait=" << stats.blockedContext
        << " recoveryBusy=" << stats.recoveryBusy << " traps=" << stats.traps
        << " pteReads=" << stats.pteReads << " contextChanges=" << stats.epochChanges
        << " virtualPhysicalRequests=" << stats.virtualRequests[6]
        << " virtualPhysicalResponses=" << stats.virtualResponses[6]
        << " virtualCompletions=" << stats.virtualCompletions << '\n';
    return stats;
}
int main(int argc, char **argv) {
    std::string activeCase = "argument-validation";
    Trace trace;
    try {
        require(argc >= 2 && (std::string(argv[1]) == "--on" || std::string(argv[1]) == "--off"), "explicit --on or --off required");
        const bool enabled = std::string(argv[1]) == "--on";
        bool injectToken = false, injectByte = false;
        std::string selectedCase, tracePath;
        for (int i = 2; i < argc; ++i) {
            const std::string option = argv[i];
            if (option == "--inject-oracle-token-mismatch") injectToken = true;
            else if (option == "--inject-oracle-byte-mismatch") injectByte = true;
            else if (option == "--case") {
                require(selectedCase.empty() && i + 1 < argc, "--case requires one nonduplicated case name");
                selectedCase = argv[++i]; activeCase = selectedCase;
                require(!selectedCase.empty(), "--case requires a nonempty case name");
            } else if (option == "--trace") {
                require(tracePath.empty() && i + 1 < argc, "--trace requires one nonduplicated JSONL path");
                tracePath = argv[++i];
                require(!tracePath.empty(), "--trace requires a nonempty JSONL path");
            }
            else throw std::runtime_error("unknown argument " + option);
        }
        require(enabled || (!injectToken && !injectByte), "oracle mismatch controls require --on");
        require(!injectToken || !injectByte, "choose one oracle mismatch control");
        epochOracleControls();
        cancellationOracleControls();
        trace.open(tracePath);
        auto cases = programs();
        require(selectedCase.empty() || std::any_of(cases.begin(), cases.end(),
            [&](const Program &p) { return p.name == selectedCase; }), "unknown case " + selectedCase);
        for (auto &program : cases) {
            if (!selectedCase.empty() && program.name != selectedCase) continue;
            activeCase = program.name;
            // Isolation includes independent interpretation, not just DUT reset.
            interpret(program);
            require((!injectToken && !injectByte) || std::any_of(program.intents.begin(), program.intents.end(),
                [](const auto &entry) { return entry.second.eligible(); }),
                "oracle mismatch case has no original physical store");
            run(program, enabled, injectToken, injectByte, trace);
        }
        std::cout << "GSIM CPU posted-store lineage: PASS; real CPU/LSU/FIFO/StoreBuffer/translation, external cache-retention contract only\n";
        return 0;
    } catch (const std::exception &e) {
        trace.failure(activeCase, e.what());
        std::cerr << "GSIM CPU posted-store lineage: FAIL case=" << activeCase << ' ' << e.what() << '\n';
        return 1;
    }
}
