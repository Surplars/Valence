#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

// Authored raw RV64I program and a separate, deliberately small ISA interpreter.
// Neither the encoders nor the interpreter import DUT decode/cache definitions.
namespace posted_board_guest {
constexpr uint64_t romBase = 0x80000000ULL;
constexpr uint64_t ddrBase = 0x80200000ULL;
constexpr uint64_t scratchA = 0x80210000ULL;
constexpr uint64_t scratchB = scratchA + 0x4000;
constexpr uint64_t scratchC = scratchA + 0x8000;
constexpr uint64_t memoryBegin = scratchA - 64, memoryEnd = scratchC + 128;
constexpr unsigned lineBytes = 64, cacheLines = 512, cacheWays = 2;
constexpr unsigned directedLineCount = 4, directedStoresPerLine = 8;
constexpr unsigned minimumDirectedMembers = 2;
constexpr std::array<uint64_t, directedLineCount> directedLines{
    scratchA + 0x400, scratchA + 0x800, scratchA + 0xc00, scratchA + 0x1000};
using ByteMemory = std::map<uint64_t, uint8_t>;
inline void require(bool good, const std::string &why) {
    if (!good) throw std::runtime_error(why);
}
inline uint64_t signExtend(uint64_t value, unsigned bits) {
    const uint64_t sign = UINT64_C(1) << (bits - 1);
    return (value ^ sign) - sign;
}
inline uint32_t immediate(unsigned rd, unsigned rs, int value) {
    return (uint32_t(value & 4095) << 20) | (rs << 15) | (rd << 7) | 0x13;
}
inline uint32_t add(unsigned rd, unsigned left, unsigned right) {
    return (right << 20) | (left << 15) | (rd << 7) | 0x33;
}
inline uint32_t store(unsigned value, unsigned address, int offset, unsigned size) {
    const unsigned imm = unsigned(offset) & 4095;
    return ((imm >> 5) << 25) | (value << 20) | (address << 15) | (size << 12) |
        ((imm & 31) << 7) | 0x23;
}
inline uint32_t load(unsigned rd, unsigned address, int offset, unsigned size) {
    return ((unsigned(offset) & 4095) << 20) | (address << 15) | (size << 12) | (rd << 7) | 3;
}
inline uint32_t branchNotEqual(unsigned left, unsigned right, int offset) {
    const uint32_t imm = uint32_t(offset) & 8191;
    return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 63) << 25) | (right << 20) |
        (left << 15) | (1U << 12) | (((imm >> 1) & 15) << 8) | (((imm >> 11) & 1) << 7) | 0x63;
}
inline std::vector<uint32_t> instructions() {
    std::vector<uint32_t> code{
        0x00210097,                    // auipc x1,0x210: PC + 0x210000 = A
        0x000041b7, add(3, 1, 3),      // B = A + 0x4000
        0x00008237, add(4, 1, 4),      // C = A + 0x8000
        immediate(2, 0, 0x321), store(2, 1, 0, 3), 0x0ff0000f,
        immediate(2, 0, 0x654), store(2, 3, 0, 3), 0x0ff0000f,
        // The ordinary fences drain earlier store owners, preserving dirty A/B.
        // C shares their 256-set index and must displace a dirty way.
        immediate(2, 0, 0x765), store(2, 4, 0, 3),
        immediate(6, 0, 0x5a3),
        store(6, 4, 9, 0),
        immediate(7, 0, 0)
    };
    // Enough genuine allocations to reuse a 16-entry ROB index while the
    // downstream accepted write remains pending. No timing/control forcing.
    for (unsigned n = 0; n < 40; ++n) code.push_back(immediate(7, 7, 1));
    // An early load reaches the head during the actual victim write. Avoid
    // filling the legacy StoreBuffer with the remaining masks before this
    // observation point. Read the beat containing the first masked store.
    code.push_back(load(11, 4, 8, 3));
    code.insert(code.end(), {store(6, 4, 10, 1), store(6, 4, 12, 2),
        store(6, 4, 1, 0), store(6, 4, 2, 1), store(6, 4, 4, 2)});
    code.push_back(load(10, 4, 0, 3));
    // Four distinct cold sets, deliberately nonadjacent to avoid next-line
    // prefetch warming a later case. Ordinary fences between cases preserve
    // dirty bytes but finish each earlier owner; no DUT control is forced.
    code.push_back(immediate(8, 1, 0x400));
    for (unsigned line = 0; line < directedLineCount; ++line) {
        code.push_back(immediate(2, 0, 0x510 + int(line)));
        code.push_back(store(2, 8, 0, 3));
        for (unsigned word = 1; word < directedStoresPerLine; ++word) {
            // The younger SD's base/data are already available while normal
            // ADDI/branch instructions occupy the head. This exercises the
            // prepared-younger-store seal bug without a taken-branch recovery.
            code.push_back(immediate(7, 7, 1));
            code.push_back(branchNotEqual(0, 0, 8)); // Always false, fall through.
            code.push_back(store(2, 8, int(word * 8), 3));
        }
        // Keep future load/system instructions beyond the 16-entry ROB until
        // the last stores have become real head-authorized requests.
        for (unsigned n = 0; n < 20; ++n) code.push_back(immediate(7, 7, 1));
        code.push_back(load(12, 8, 56, 3));
        code.push_back(0x0ff0000f);
        if (line + 1 < directedLineCount) code.push_back(immediate(8, 8, 0x400));
    }
    code.push_back(0x0000100f);         // fence.i: Board's real final cache flush
    code.push_back(0x0000006f);         // jal x0,0: bounded host observes this spin
    return code;
}
inline ByteMemory initialMemory() {
    ByteMemory memory;
    for (uint64_t address = memoryBegin; address < memoryEnd; ++address) {
        const uint64_t index = address - memoryBegin;
        memory.emplace(address, uint8_t((index * 37 + 19) ^ (index >> 3)));
    }
    return memory;
}
inline uint8_t byteAt(const ByteMemory &memory, uint64_t address) {
    const auto found = memory.find(address);
    return found == memory.end() ? 0 : found->second;
}
inline uint64_t wordAt(const ByteMemory &memory, uint64_t address) {
    uint64_t result = 0;
    for (unsigned b = 0; b < 8; ++b) result |= uint64_t(byteAt(memory, address + b)) << (8 * b);
    return result;
}
struct Intent {
    uint64_t pc = 0, address = 0, rawData = 0, laneData = 0, responseData = 0;
    unsigned size = 0, mask = 0;
    bool store = false;
};
struct Expected {
    uint64_t pc = 0, next = 0, value = 0;
    uint32_t instruction = 0;
    unsigned rd = 0;
    bool memory = false, fence = false, fenceI = false, done = false;
    Intent intent;
};
struct Program {
    std::vector<uint32_t> code = instructions();
    std::vector<Expected> trace;
    std::map<uint64_t, Intent> intents;
    ByteMemory initial = initialMemory(), finalBytes = initial;
    uint64_t donePc = 0, fenceIPc = 0, loadPc = 0, conflictPc = 0;
    unsigned stores = 0, loads = 0;
    bool isDirectedLine(uint64_t line) const {
        for (const auto expected : directedLines) if (line == expected) return true;
        return false;
    }
    std::vector<uint8_t> bytes() const {
        std::vector<uint8_t> result;
        for (uint32_t instruction : code)
            for (unsigned b = 0; b < 4; ++b) result.push_back(instruction >> (8 * b));
        // Fetch can rename speculative fall-through behind JAL before redirect.
        // Valid raw padding is present in ROM but may never retire.
        for (unsigned n = 0; n < 32; ++n)
            for (unsigned b = 0; b < 4; ++b) result.push_back(uint32_t(0x0000006f) >> (8 * b));
        return result;
    }
    bool rawInstruction(uint64_t pc, uint32_t instruction) const {
        if (pc < romBase || (pc & 3)) return false;
        const uint64_t index = (pc - romBase) / 4;
        return index < code.size() ? code[index] == instruction :
            index < code.size() + 32 && instruction == 0x0000006f;
    }
};
inline Program interpret() {
    Program p;
    std::array<uint64_t, 32> registers{};
    for (size_t ordinal = 0; ordinal < p.code.size(); ++ordinal) {
        Expected e;
        e.pc = romBase + ordinal * 4; e.next = e.pc + 4; e.instruction = p.code[ordinal];
        const uint32_t x = e.instruction;
        const unsigned op = x & 127, rd = (x >> 7) & 31, rs1 = (x >> 15) & 31;
        const unsigned rs2 = (x >> 20) & 31, f = (x >> 12) & 7;
        if (op == 0x17) { e.rd = rd; e.value = e.pc + signExtend(x & 0xfffff000U, 32); }
        else if (op == 0x37) { e.rd = rd; e.value = signExtend(x & 0xfffff000U, 32); }
        else if (op == 0x13 && f == 0) { e.rd = rd; e.value = registers[rs1] + signExtend(x >> 20, 12); }
        else if (op == 0x33 && f == 0 && !(x >> 25)) { e.rd = rd; e.value = registers[rs1] + registers[rs2]; }
        else if (op == 0x63 && f == 1) {
            const uint32_t encoded = ((x >> 31) << 12) | (((x >> 7) & 1) << 11) |
                (((x >> 25) & 63) << 5) | (((x >> 8) & 15) << 1);
            const bool taken = registers[rs1] != registers[rs2];
            require(!taken && signExtend(encoded, 13) == 8,
                "directed branch must be architecturally not taken with independent +8 target");
        }
        else if (op == 0x23 || op == 3) {
            require(f <= 3, "guest interpreter rejects unsupported memory funct3");
            e.memory = true;
            Intent &i = e.intent;
            i.pc = e.pc; i.store = op == 0x23; i.size = f;
            const uint32_t encoded = i.store ? (((x >> 25) << 5) | ((x >> 7) & 31)) : x >> 20;
            i.address = registers[rs1] + signExtend(encoded, 12);
            const unsigned bytes = 1U << i.size;
            require(!(i.address & (bytes - 1)) && i.address >= memoryBegin && i.address + bytes <= memoryEnd,
                "guest memory operand is misaligned/outside independent byte memory");
            i.rawData = i.store ? registers[rs2] : 0;
            i.laneData = i.rawData << ((i.address & 7) * 8);
            i.mask = ((1U << bytes) - 1) << (i.address & 7);
            if (i.store) {
                for (unsigned b = 0; b < bytes; ++b) p.finalBytes.at(i.address + b) = i.rawData >> (b * 8);
                ++p.stores;
                if (i.address == scratchC) p.conflictPc = e.pc;
            } else {
                ++p.loads;
                e.rd = rd; i.responseData = wordAt(p.finalBytes, i.address & ~UINT64_C(7));
                e.value = i.responseData >> ((i.address & 7) * 8);
                if (bytes < 8) e.value = signExtend(e.value & ((UINT64_C(1) << (bytes * 8)) - 1), bytes * 8);
                p.loadPc = e.pc;
            }
            require(p.intents.emplace(e.pc, i).second, "guest repeats a memory PC");
        } else if (x == 0x0ff0000f) e.fence = true;
        else if (x == 0x0000100f) { e.fenceI = true; p.fenceIPc = e.pc; }
        else if (x == 0x0000006f) { e.done = true; e.next = e.pc; p.donePc = e.pc; }
        else throw std::runtime_error("guest interpreter rejects raw instruction " + std::to_string(x));
        if (e.rd) registers[e.rd] = e.value;
        registers[0] = 0;
        p.trace.push_back(e);
        if (e.done) break;
    }
    require(registers[1] == scratchA && registers[3] == scratchB && registers[4] == scratchC,
        "raw AUIPC/add address construction mismatch");
    require(p.stores == 9 + directedLineCount * directedStoresPerLine && p.loads == 2 + directedLineCount &&
        p.intents.size() == p.stores + p.loads && p.donePc && p.fenceIPc && p.loadPc,
        "guest instruction coverage changed");
    for (const uint64_t line : directedLines) {
        unsigned stores = 0, loads = 0, words = 0;
        for (const auto &entry : p.intents) {
            const auto &i = entry.second;
            if ((i.address & ~UINT64_C(63)) != line) continue;
            if (i.store) { ++stores; words |= 1U << unsigned((i.address - line) / 8); }
            else ++loads;
            require(i.size == 3, "directed line must use independently decoded aligned SD/LD");
        }
        require(stores == directedStoresPerLine && loads == 1 && words == 255,
            "each directed line must contain exactly eight distinct authored SD beats and one LD");
    }
    require(((scratchA / lineBytes) % (cacheLines / cacheWays)) ==
        ((scratchB / lineBytes) % (cacheLines / cacheWays)) &&
        ((scratchA / lineBytes) % (cacheLines / cacheWays)) ==
        ((scratchC / lineBytes) % (cacheLines / cacheWays)), "guest addresses do not share a set");
    return p;
}
} // namespace posted_board_guest
