#pragma once
#include "muldiv_model.h"
// Independent software ISA oracle, shared by ideal and synchronous platforms.
// Independent mask/match ISA table, not the hardware's opcode/funct switch structure.
struct Encoding {
    const char *name;
    uint32_t mask, match;
    unsigned alu;
    bool word, immediate, upper, pc;
    unsigned control = 0;
    unsigned memory = 0; // 1 load, 2 store
    bool mulDiv = false;
};
static const std::vector<Encoding> encodings = {
    {"lui",   0x0000007f, 0x00000037, 0, false, true, true, false},
    {"auipc", 0x0000007f, 0x00000017, 0, false, true, true, true},
    {"addi",  0x0000707f, 0x00000013, 0, false, true, false, false},
    {"slti",  0x0000707f, 0x00002013, 8, false, true, false, false},
    {"sltiu", 0x0000707f, 0x00003013, 9, false, true, false, false},
    {"xori",  0x0000707f, 0x00004013, 2, false, true, false, false},
    {"ori",   0x0000707f, 0x00006013, 3, false, true, false, false},
    {"andi",  0x0000707f, 0x00007013, 4, false, true, false, false},
    {"slli",  0xfc00707f, 0x00001013, 5, false, true, false, false},
    {"srli",  0xfc00707f, 0x00005013, 6, false, true, false, false},
    {"srai",  0xfc00707f, 0x40005013, 7, false, true, false, false},
    {"add",   0xfe00707f, 0x00000033, 0, false, false, false, false},
    {"sub",   0xfe00707f, 0x40000033, 1, false, false, false, false},
    {"sll",   0xfe00707f, 0x00001033, 5, false, false, false, false},
    {"slt",   0xfe00707f, 0x00002033, 8, false, false, false, false},
    {"sltu",  0xfe00707f, 0x00003033, 9, false, false, false, false},
    {"xor",   0xfe00707f, 0x00004033, 2, false, false, false, false},
    {"srl",   0xfe00707f, 0x00005033, 6, false, false, false, false},
    {"sra",   0xfe00707f, 0x40005033, 7, false, false, false, false},
    {"or",    0xfe00707f, 0x00006033, 3, false, false, false, false},
    {"and",   0xfe00707f, 0x00007033, 4, false, false, false, false},
    {"addiw", 0x0000707f, 0x0000001b, 0, true, true, false, false},
    {"slliw", 0xfe00707f, 0x0000101b, 5, true, true, false, false},
    {"srliw", 0xfe00707f, 0x0000501b, 6, true, true, false, false},
    {"sraiw", 0xfe00707f, 0x4000501b, 7, true, true, false, false},
    {"addw",  0xfe00707f, 0x0000003b, 0, true, false, false, false},
    {"subw",  0xfe00707f, 0x4000003b, 1, true, false, false, false},
    {"sllw",  0xfe00707f, 0x0000103b, 5, true, false, false, false},
    {"srlw",  0xfe00707f, 0x0000503b, 6, true, false, false, false},
    {"sraw",  0xfe00707f, 0x4000503b, 7, true, false, false, false},
    {"beq",  0x0000707f, 0x00000063, 0, false, false, false, false, 1},
    {"bne",  0x0000707f, 0x00001063, 0, false, false, false, false, 2},
    {"blt",  0x0000707f, 0x00004063, 0, false, false, false, false, 3},
    {"bge",  0x0000707f, 0x00005063, 0, false, false, false, false, 4},
    {"bltu", 0x0000707f, 0x00006063, 0, false, false, false, false, 5},
    {"bgeu", 0x0000707f, 0x00007063, 0, false, false, false, false, 6},
    {"jal",  0x0000007f, 0x0000006f, 0, false, true, false, true, 7},
    {"jalr", 0x0000707f, 0x00000067, 0, false, true, false, false, 8},
    {"lb", 0x0000707f, 0x00000003, 0, false, true, false, false, 0, 1},
    {"lh", 0x0000707f, 0x00001003, 0, false, true, false, false, 0, 1},
    {"lw", 0x0000707f, 0x00002003, 0, false, true, false, false, 0, 1},
    {"ld", 0x0000707f, 0x00003003, 0, false, true, false, false, 0, 1},
    {"lbu", 0x0000707f, 0x00004003, 0, false, true, false, false, 0, 1},
    {"lhu", 0x0000707f, 0x00005003, 0, false, true, false, false, 0, 1},
    {"lwu", 0x0000707f, 0x00006003, 0, false, true, false, false, 0, 1},
    {"sb", 0x0000707f, 0x00000023, 0, false, false, false, false, 0, 2},
    {"sh", 0x0000707f, 0x00001023, 0, false, false, false, false, 0, 2},
    {"sw", 0x0000707f, 0x00002023, 0, false, false, false, false, 0, 2},
    {"sd", 0x0000707f, 0x00003023, 0, false, false, false, false, 0, 2},
    {"czero.eqz", 0xfe00707f, 0x0e005033, 10, false, false, false, false},
    {"czero.nez", 0xfe00707f, 0x0e007033, 11, false, false, false, false},
    {"mul", 0xfe00707f, 0x02000033, 0, false, false, false, false, 0, 0, true},
    {"mulh", 0xfe00707f, 0x02001033, 0, false, false, false, false, 0, 0, true},
    {"mulhsu", 0xfe00707f, 0x02002033, 0, false, false, false, false, 0, 0, true},
    {"mulhu", 0xfe00707f, 0x02003033, 0, false, false, false, false, 0, 0, true},
    {"div", 0xfe00707f, 0x02004033, 0, false, false, false, false, 0, 0, true},
    {"divu", 0xfe00707f, 0x02005033, 0, false, false, false, false, 0, 0, true},
    {"rem", 0xfe00707f, 0x02006033, 0, false, false, false, false, 0, 0, true},
    {"remu", 0xfe00707f, 0x02007033, 0, false, false, false, false, 0, 0, true},
    {"mulw", 0xfe00707f, 0x0200003b, 0, true, false, false, false, 0, 0, true},
    {"divw", 0xfe00707f, 0x0200403b, 0, true, false, false, false, 0, 0, true},
    {"divuw", 0xfe00707f, 0x0200503b, 0, true, false, false, false, 0, 0, true},
    {"remw", 0xfe00707f, 0x0200603b, 0, true, false, false, false, 0, 0, true},
    {"remuw", 0xfe00707f, 0x0200703b, 0, true, false, false, false, 0, 0, true},
    {"sh1add", 0xfe00707f, 0x20002033, 16, false, false, false, false},
    {"sh2add", 0xfe00707f, 0x20004033, 17, false, false, false, false},
    {"sh3add", 0xfe00707f, 0x20006033, 18, false, false, false, false},
    {"add.uw", 0xfe00707f, 0x0800003b, 19, false, false, false, false},
    {"sh1add.uw", 0xfe00707f, 0x2000203b, 20, false, false, false, false},
    {"sh2add.uw", 0xfe00707f, 0x2000403b, 21, false, false, false, false},
    {"sh3add.uw", 0xfe00707f, 0x2000603b, 22, false, false, false, false},
    {"slli.uw", 0xfc00707f, 0x0800101b, 23, false, true, false, false},
    {"andn", 0xfe00707f, 0x40007033, 24, false, false, false, false},
    {"orn", 0xfe00707f, 0x40006033, 25, false, false, false, false},
    {"xnor", 0xfe00707f, 0x40004033, 26, false, false, false, false},
    {"clz", 0xfff0707f, 0x60001013, 27, false, true, false, false},
    {"clzw", 0xfff0707f, 0x6000101b, 27, true, true, false, false},
    {"ctz", 0xfff0707f, 0x60101013, 28, false, true, false, false},
    {"ctzw", 0xfff0707f, 0x6010101b, 28, true, true, false, false},
    {"cpop", 0xfff0707f, 0x60201013, 29, false, true, false, false},
    {"cpopw", 0xfff0707f, 0x6020101b, 29, true, true, false, false},
    {"min", 0xfe00707f, 0x0a004033, 30, false, false, false, false},
    {"minu", 0xfe00707f, 0x0a005033, 31, false, false, false, false},
    {"max", 0xfe00707f, 0x0a006033, 32, false, false, false, false},
    {"maxu", 0xfe00707f, 0x0a007033, 33, false, false, false, false},
    {"sext.b", 0xfff0707f, 0x60401013, 34, false, true, false, false},
    {"sext.h", 0xfff0707f, 0x60501013, 35, false, true, false, false},
    {"zext.h", 0xfff0707f, 0x0800403b, 36, false, true, false, false},
    {"rol", 0xfe00707f, 0x60001033, 37, false, false, false, false},
    {"rolw", 0xfe00707f, 0x6000103b, 37, true, false, false, false},
    {"ror", 0xfe00707f, 0x60005033, 38, false, false, false, false},
    {"rorw", 0xfe00707f, 0x6000503b, 38, true, false, false, false},
    {"rori", 0xfc00707f, 0x60005013, 38, false, true, false, false},
    {"roriw", 0xfe00707f, 0x6000501b, 38, true, true, false, false},
    {"orc.b", 0xfff0707f, 0x28705013, 39, false, true, false, false},
    {"rev8", 0xfff0707f, 0x6b805013, 40, false, true, false, false},
    {"bclr", 0xfe00707f, 0x48001033, 41, false, false, false, false},
    {"bclri", 0xfc00707f, 0x48001013, 41, false, true, false, false},
    {"bset", 0xfe00707f, 0x28001033, 42, false, false, false, false},
    {"bseti", 0xfc00707f, 0x28001013, 42, false, true, false, false},
    {"binv", 0xfe00707f, 0x68001033, 43, false, false, false, false},
    {"binvi", 0xfc00707f, 0x68001013, 43, false, true, false, false},
    {"bext", 0xfe00707f, 0x48005033, 44, false, false, false, false},
    {"bexti", 0xfc00707f, 0x48005013, 44, false, true, false, false},
};
static const Encoding *decode(uint32_t inst) {
    for (const auto &e : encodings) if ((inst & e.mask) == e.match) return &e;
    return nullptr;
}
static uint64_t extend(uint64_t value, unsigned bits) {
    const uint64_t sign = UINT64_C(1) << (bits - 1);
    return (value ^ sign) - sign;
}
static uint64_t immediate(const Encoding &e, uint32_t inst) {
    if (e.memory == 2) return extend(((inst >> 25) << 5) | ((inst >> 7) & 31), 12);
    if (e.control >= 1 && e.control <= 6)
        return extend(((inst >> 31) << 12) | (((inst >> 7) & 1) << 11) |
                      (((inst >> 25) & 63) << 5) | (((inst >> 8) & 15) << 1), 13);
    if (e.control == 7)
        return extend(((inst >> 31) << 20) | (((inst >> 12) & 255) << 12) |
                      (((inst >> 20) & 1) << 11) | (((inst >> 21) & 1023) << 1), 21);
    return e.upper ? extend(inst & 0xfffff000U, 32) : extend(inst >> 20, 12);
}
static uint64_t execute(const Encoding &e, uint64_t a, uint64_t b) {
    const unsigned width = e.word ? 32 : 64;
    const unsigned shift = b % width;
    const uint64_t mask = e.word ? 0xffffffffU : UINT64_MAX;
    uint64_t value = 0;
    switch (e.alu) {
    case 0: value = a + b; break;
    case 1: value = a - b; break;
    case 2: value = a ^ b; break;
    case 3: value = a | b; break;
    case 4: value = a & b; break;
    case 5: value = a << shift; break;
    case 6: value = (a & mask) >> shift; break;
    case 7:
        value = (a & mask) >> shift;
        if (shift && ((a >> (width - 1)) & 1)) value |= mask ^ (mask >> shift);
        break;
    case 8: value = (a ^ (UINT64_C(1) << 63)) < (b ^ (UINT64_C(1) << 63)); break;
    case 9: value = a < b; break;
    case 10: value = b == 0 ? 0 : a; break;
    case 11: value = b != 0 ? 0 : a; break;
    case 16: value = (a << 1) + b; break;
    case 17: value = (a << 2) + b; break;
    case 18: value = (a << 3) + b; break;
    case 19: value = uint64_t(uint32_t(a)) + b; break;
    case 20: value = (uint64_t(uint32_t(a)) << 1) + b; break;
    case 21: value = (uint64_t(uint32_t(a)) << 2) + b; break;
    case 22: value = (uint64_t(uint32_t(a)) << 3) + b; break;
    case 23: value = uint64_t(uint32_t(a)) << (b % 64); break;
    case 24: value = a & ~b; break;
    case 25: value = a | ~b; break;
    case 26: value = ~(a ^ b); break;
    case 27:
        for (unsigned i = width; i && !(a & (UINT64_C(1) << (i - 1))); --i) ++value;
        break;
    case 28:
        for (unsigned i = 0; i < width && !(a & (UINT64_C(1) << i)); ++i) ++value;
        break;
    case 29:
        for (unsigned i = 0; i < width; ++i) value += (a >> i) & 1;
        break;
    case 30: case 32: {
        const bool less = (a ^ (UINT64_C(1) << 63)) < (b ^ (UINT64_C(1) << 63));
        value = (less == (e.alu == 30)) ? a : b; break;
    }
    case 31: value = a < b ? a : b; break;
    case 33: value = a < b ? b : a; break;
    case 34: value = extend(a & 255, 8); break;
    case 35: value = extend(a & 65535, 16); break;
    case 36: value = a & 65535; break;
    case 37: case 38:
        // Per-bit permutation, independent of the DUT's staged rotation mux network.
        for (unsigned i = 0; i < width; ++i) {
            const unsigned destination = (i + (e.alu == 37 ? shift : width - shift)) % width;
            value |= ((a >> i) & 1) << destination;
        }
        break;
    case 39:
        for (unsigned i = 0; i < 8; ++i) if ((a >> (8 * i)) & 255) value |= UINT64_C(255) << (8 * i);
        break;
    case 40:
        for (unsigned i = 0; i < 8; ++i) value |= ((a >> (8 * i)) & 255) << (8 * (7 - i));
        break;
    case 41: value = a & ~(UINT64_C(1) << (b % 64)); break;
    case 42: value = a | (UINT64_C(1) << (b % 64)); break;
    case 43: value = a ^ (UINT64_C(1) << (b % 64)); break;
    case 44: value = (a >> (b % 64)) & 1; break;
    }
    return e.word ? extend(value & 0xffffffffU, 32) : value;
}
struct Expected {
    uint64_t result = 0, nextPc = 0, target = 0, cause = 0;
    unsigned rd = 0;
    bool fault = false, taken = false;
};
static Expected interpret(const Encoding &e, uint32_t inst, uint64_t pc,
                          const std::array<uint64_t, 32> &registers, const Memory &memory) {
    Expected out;
    out.rd = (inst >> 7) & 31;
    const uint64_t a = registers[(inst >> 15) & 31], b = registers[(inst >> 20) & 31];
    const uint64_t offset = immediate(e, inst);
    out.nextPc = pc + 4;
    if (e.mulDiv) {
        out.result = multiplyDivide((inst >> 12) & 7, e.word, a, b);
        return out;
    }
    if (e.memory) {
        if (e.memory == 2) out.rd = 0;
        out.target = a + offset;
        const unsigned bytes = 1U << ((inst >> 12) & 3);
        const bool misaligned = (out.target & (bytes - 1)) != 0;
        const bool accessible = out.target >= dataBase && out.target - dataBase <= memory.size() - bytes;
        out.fault = misaligned || !accessible;
        out.cause = (e.memory == 2 ? 6 : 4) + !misaligned;
        if (!out.fault && e.memory == 1) {
            for (unsigned i = 0; i < bytes; ++i) out.result |= uint64_t(memory[out.target - dataBase + i]) << (8 * i);
            if (!(inst & 0x4000) && bytes < 8) out.result = extend(out.result, bytes * 8);
        }
        return out;
    }
    if (!e.control) {
        out.result = execute(e, e.pc ? pc : (e.upper ? 0 : a), e.immediate ? offset : b);
        return out;
    }
    if (e.control < 7) {
        out.rd = 0;
        const bool signedLess = (a ^ (UINT64_C(1) << 63)) < (b ^ (UINT64_C(1) << 63));
        switch (e.control) {
        case 1: out.taken = a == b; break;
        case 2: out.taken = a != b; break;
        case 3: out.taken = signedLess; break;
        case 4: out.taken = !signedLess; break;
        case 5: out.taken = a < b; break;
        case 6: out.taken = a >= b; break;
        }
        out.target = pc + offset;
    } else {
        out.taken = true;
        out.result = pc + 4;
        out.target = e.control == 7 ? pc + offset : ((a + offset) & ~UINT64_C(1));
    }
    if (out.taken) out.nextPc = out.target;
    out.fault = out.taken && (out.target & 3);
    return out;
}
