// Focused A1 backend acceptance. The RV64 retirement oracle executes the raw
// instruction stream BEFORE starting the DUT. It does not consume DUT values,
// issue decisions, completion tokens, redirect targets, or an older RTL model.
#include "A1DualBackendGsim.h"
#include "gsim_model_storage.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

#ifndef A1_DUAL_OWNER
#define A1_DUAL_OWNER 0
#endif
#ifndef A1_DUAL_INSPECT_VALUE
#define A1_DUAL_INSPECT_VALUE 1
#endif

namespace {
constexpr uint64_t codeBase = UINT64_C(0x80200000);
constexpr uint64_t dataBase = codeBase + 0x1000;
constexpr size_t dataBytes = 4096;
constexpr uint32_t ebreak = 0x00100073;
constexpr uint32_t fenceI = 0x0000100f;

void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
std::string hex(uint64_t value) {
    std::ostringstream out;
    out << "0x" << std::hex << value;
    return out.str();
}
uint64_t signExtend(uint64_t value, unsigned width) {
    const uint64_t sign = UINT64_C(1) << (width - 1);
    const uint64_t mask = (UINT64_C(1) << width) - 1;
    return ((value & mask) ^ sign) - sign;
}
bool signedLess(uint64_t a, uint64_t b) {
    return (a ^ (UINT64_C(1) << 63)) < (b ^ (UINT64_C(1) << 63));
}
uint64_t signedDivide(uint64_t a, uint64_t b, bool remainder) {
    // Unsigned magnitudes avoid C++ overflow/implementation-defined signed casts.
    if (!b) return remainder ? a : UINT64_MAX;
    const bool aNegative = a >> 63, bNegative = b >> 63;
    const uint64_t aa = aNegative ? -a : a;
    const uint64_t bb = bNegative ? -b : b;
    const uint64_t magnitude = remainder ? aa % bb : aa / bb;
    return (remainder ? aNegative : aNegative != bNegative) ? -magnitude : magnitude;
}
uint32_t addi(unsigned rd, unsigned rs, int immediate) {
    return (uint32_t(immediate) & 0xfff) << 20 | rs << 15 | rd << 7 | 0x13;
}
uint32_t slli(unsigned rd, unsigned rs, unsigned amount) {
    return amount << 20 | rs << 15 | 1 << 12 | rd << 7 | 0x13;
}
uint32_t regOp(unsigned rd, unsigned a, unsigned b, unsigned function = 0, bool m = false) {
    return unsigned(m) << 25 | b << 20 | a << 15 | function << 12 | rd << 7 | 0x33;
}
uint32_t auipc(unsigned rd, uint32_t immediate) { return (immediate & 0xfffff000) | rd << 7 | 0x17; }
uint32_t load(unsigned rd, unsigned rs, int offset = 0, unsigned function = 3) {
    return (uint32_t(offset) & 0xfff) << 20 | rs << 15 | function << 12 | rd << 7 | 3;
}
uint32_t store(unsigned rs, unsigned value, int offset = 0, unsigned size = 3) {
    const uint32_t imm = uint32_t(offset) & 0xfff;
    return (imm >> 5) << 25 | value << 20 | rs << 15 | size << 12 | (imm & 31) << 7 | 0x23;
}
uint32_t branch(unsigned a, unsigned b, int offset, unsigned function = 0) {
    const uint32_t imm = uint32_t(offset) & 0x1fff;
    return ((imm >> 12) & 1) << 31 | ((imm >> 5) & 63) << 25 | b << 20 | a << 15 |
        function << 12 | ((imm >> 1) & 15) << 8 | ((imm >> 11) & 1) << 7 | 0x63;
}
uint32_t csr(unsigned rd, unsigned source, unsigned operation) {
    return 0x340u << 20 | source << 15 | operation << 12 | rd << 7 | 0x73;
}

struct Bytes {
    std::array<uint8_t, dataBytes> data{};
    Bytes() {
        for (size_t i = 0; i < data.size(); ++i)
            data[i] = uint8_t((i * 73 + (i >> 3) * 19 + 0x81) ^ (i >> 5));
        // Exact binary64 1.5 fixture. The bounded FP case performs 1.5 + 1.5.
        write(dataBase + 768, UINT64_C(0x3ff8000000000000), 8);
    }
    size_t index(uint64_t address, unsigned bytes) const {
        require(address >= dataBase && address - dataBase <= dataBytes - bytes,
            "memory access outside fixture: " + hex(address));
        return size_t(address - dataBase);
    }
    uint64_t read(uint64_t address, unsigned bytes) const {
        const size_t at = index(address, bytes);
        uint64_t result = 0;
        for (unsigned i = 0; i < bytes; ++i) result |= uint64_t(data[at + i]) << (8 * i);
        return result;
    }
    void write(uint64_t address, uint64_t value, unsigned bytes) {
        const size_t at = index(address, bytes);
        for (unsigned i = 0; i < bytes; ++i) data[at + i] = uint8_t(value >> (8 * i));
    }
    void busWrite(uint64_t alignedAddress, uint64_t value, unsigned mask) {
        const size_t at = index(alignedAddress, 8);
        for (unsigned i = 0; i < 8; ++i)
            if ((mask >> i) & 1) data[at + i] = uint8_t(value >> (8 * i));
    }
};

struct Program {
    std::string name;
    std::vector<uint32_t> words;
    unsigned delay = 3;
    bool recovery = false;
    bool commitPressure = true;
    // Zero preserves the original ten fixtures and their exact service law.
    // Contention fixtures use a fixed public-cycle rendezvous, not DUT probes.
    unsigned contention = 0, responsePhase = 8;
    void put(uint32_t word) { words.push_back(word); }
    uint32_t at(uint64_t pc) const {
        require(pc >= codeBase && !(pc & 3) && (pc - codeBase) / 4 < words.size(),
            "instruction PC outside program: " + hex(pc));
        return words.at(size_t((pc - codeBase) / 4));
    }
    bool contains(uint64_t pc) const {
        return pc >= codeBase && !(pc & 3) && (pc - codeBase) / 4 < words.size();
    }
};
struct Retire {
    uint64_t pc = 0, data = 0, nextPc = 0;
    uint32_t word = 0;
    unsigned rd = 0;
    bool writes = false;
};
struct StoreEvent { uint64_t address = 0, data = 0; unsigned size = 0; };
struct Oracle {
    std::array<uint64_t, 32> registers{};
    Bytes memory;
    std::vector<Retire> retirements;
    std::vector<StoreEvent> stores;
    std::map<uint64_t, std::set<uint64_t>> legalRedirects;
    uint64_t trapPc = 0, trapCause = 0, trapTval = 0, scratch = 0;
    std::array<uint64_t, 32> floating{};
    bool fpEnabled = false;
    unsigned loads = 0, muls = 0, divs = 0, branches = 0, systems = 0, fps = 0;

    explicit Oracle(const Program &program) {
        uint64_t pc = codeBase;
        for (unsigned steps = 0; steps < 8192; ++steps) {
            const uint32_t word = program.at(pc);
            if (word == ebreak) {
                trapPc = pc; trapCause = 3; trapTval = pc; return;
            }
            if ((word & 127) == 0x53 && !fpEnabled) {
                trapPc = pc; trapCause = 2; trapTval = word; return;
            }
            const unsigned opcode = word & 127, function = (word >> 12) & 7;
            const unsigned rd = (word >> 7) & 31, rs1 = (word >> 15) & 31, rs2 = (word >> 20) & 31;
            const uint64_t a = registers[rs1], b = registers[rs2];
            // Decoded-instruction boundary contract: rd is zero for stores,
            // branches and FP-destination-only operations. An FP encoding's
            // rd names an FPR, never an integer retirement destination.
            Retire out{pc, 0, pc + 4, word, rd, false};
            if (opcode == 0x13) {
                out.writes = rd != 0;
                if (function == 0) out.data = a + signExtend(word >> 20, 12);
                else if (function == 1 && (word >> 26) == 0) out.data = a << ((word >> 20) & 63);
                else throw std::runtime_error("unsupported independent OP-IMM");
            } else if (opcode == 0x17 || opcode == 0x37) {
                out.writes = rd != 0;
                out.data = (opcode == 0x17 ? pc : 0) + signExtend(word & 0xfffff000u, 32);
            } else if (opcode == 0x33) {
                out.writes = rd != 0;
                if ((word >> 25) == 0 && function == 0) out.data = a + b;
                else if ((word >> 25) == 1) {
                    if (function == 0) { out.data = a * b; ++muls; }
                    else if (function == 4) { out.data = signedDivide(a, b, false); ++divs; }
                    else if (function == 5) { out.data = b ? a / b : UINT64_MAX; ++divs; }
                    else if (function == 6) { out.data = signedDivide(a, b, true); ++divs; }
                    else if (function == 7) { out.data = b ? a % b : a; ++divs; }
                    else throw std::runtime_error("unsupported independent multiply-high opcode");
                } else throw std::runtime_error("unsupported independent OP");
            } else if (opcode == 3 || opcode == 0x23) {
                const bool writing = opcode == 0x23;
                const unsigned size = function & 3, bytes = 1u << size;
                require(function <= (writing ? 3u : 6u), "invalid oracle memory opcode");
                const uint64_t immediate = signExtend(writing ? ((word >> 25) << 5 | rd) : word >> 20, 12);
                const uint64_t address = a + immediate;
                require(!(address & (bytes - 1)), "oracle fixture has misaligned memory access");
                if (writing) {
                    out.rd = 0;
                    memory.write(address, b, bytes);
                    stores.push_back({address, b, size});
                } else {
                    out.writes = rd != 0;
                    out.data = memory.read(address, bytes);
                    if (!(function & 4) && size < 3) out.data = signExtend(out.data, bytes * 8);
                    ++loads;
                }
            } else if (opcode == 0x63) {
                const uint64_t offset = signExtend(((word >> 31) << 12) | (((word >> 7) & 1) << 11) |
                    (((word >> 25) & 63) << 5) | (((word >> 8) & 15) << 1), 13);
                bool taken;
                switch (function) {
                case 0: taken = a == b; break;
                case 1: taken = a != b; break;
                case 4: taken = signedLess(a, b); break;
                case 5: taken = !signedLess(a, b); break;
                case 6: taken = a < b; break;
                case 7: taken = a >= b; break;
                default: throw std::runtime_error("invalid independent branch opcode");
                }
                out.rd = 0;
                if (taken) out.nextPc = pc + offset;
                legalRedirects[pc].insert(out.nextPc);
                ++branches;
            } else if (word == fenceI) {
                out.rd = 0;
                legalRedirects[pc].insert(out.nextPc);
                ++systems;
            } else if (word == (0x300u << 20 | 5u << 15 | 2u << 12 | 0x73)) {
                require(!fpEnabled && a == 0x2000, "bounded FP fixture requires FS Initial enable");
                // x0 discards the CSR read value; only the FS write has an
                // architectural consequence in this bounded fixture.
                out.rd = 0; fpEnabled = true; ++systems;
            } else if (word == (0xf2000053u | 6u << 15 | 1u << 7)) {
                require(fpEnabled && registers[6] == UINT64_C(0x3ff8000000000000),
                    "bounded FMV.D.X fixture operand differs from exact binary64 1.5");
                floating[1] = registers[6]; out.data = floating[1]; out.rd = 0; ++fps;
            } else if (word == (0x02000053u | 1u << 20 | 1u << 15 | 2u << 7)) {
                require(fpEnabled && floating[1] == UINT64_C(0x3ff8000000000000),
                    "bounded FADD.D fixture operand differs from exact binary64 1.5");
                // 1.5 + 1.5 = 3 exactly, independent of host floating-point mode.
                // This explicitly does not qualify general F/D arithmetic.
                floating[2] = UINT64_C(0x4008000000000000);
                out.data = floating[2]; out.rd = 0; ++fps;
            } else if (word == (0xe2000053u | 2u << 15 | 7u << 7)) {
                require(fpEnabled, "bounded FMV.X.D before FS enable");
                out.data = floating[2]; out.writes = true; ++fps;
            } else if (opcode == 0x73 && (word >> 20) == 0x340 && function && function != 4) {
                const uint64_t source = function & 4 ? rs1 : a;
                out.writes = rd != 0;
                // CSRRW with rd=x0 suppresses the read. Other forms still read.
                out.data = (function & 3) == 1 && rd == 0 ? 0 : scratch;
                switch (function & 3) {
                case 1: scratch = source; break;
                case 2: if (rs1) scratch |= source; break;
                case 3: if (rs1) scratch &= ~source; break;
                default: throw std::runtime_error("invalid independent CSR opcode");
                }
                ++systems;
            } else throw std::runtime_error("unsupported independent instruction " + hex(word));
            if (out.writes) registers[out.rd] = out.data;
            registers[0] = 0;
            retirements.push_back(out);
            pc = out.nextPc;
        }
        throw std::runtime_error("independent program did not reach a terminal trap in 8192 instructions");
    }
};

std::vector<Program> programs() {
    std::vector<Program> all;
    {
        Program p{"independent_alu"};
        for (unsigned i = 0; i < 96; ++i) p.put(addi(1 + i % 30, 0, int(i * 13) - 500));
        for (unsigned i = 1; i <= 20; ++i) p.put(regOp(i, i + 1, (i + 7) % 31));
        p.put(addi(0, 17, 29)); // x0 must not become an architectural write.
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"dependent_alu"};
        p.put(addi(1, 0, 3)); p.put(addi(2, 0, -7));
        for (unsigned i = 0; i < 48; ++i) {
            p.put(regOp(3, 1, 2)); p.put(addi(1, 3, int(i % 17) - 8));
            p.put(regOp(4, 3, 1)); p.put(addi(2, 4, 1));
        }
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"mul_load_alu"}; p.delay = 7;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 17)); p.put(addi(3, 0, -9));
        for (unsigned i = 0; i < 32; ++i) {
            p.put(regOp(8, 2, 3, 0, true)); p.put(load(9, 1, int(i * 8)));
            p.put(addi(10, 2, int(i))); p.put(regOp(11, 8, 9));
            p.put(regOp(12, 10, 11)); p.put(addi(2, 0, int(19 + i)));
        }
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"divide_load_alu"}; p.delay = 5;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 1999)); p.put(addi(3, 0, 7));
        for (unsigned i = 0; i < 12; ++i) {
            p.put(regOp(8, 2, 3, 5, true)); p.put(load(9, 1, int(i * 8)));
            p.put(addi(10, 0, int(i + 5))); p.put(regOp(11, 8, 9));
            p.put(regOp(12, 10, 11)); p.put(addi(2, 2, -13));
        }
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"subword_store_load"}; p.delay = 9;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, -91)); p.put(addi(3, 0, 0x123));
        for (unsigned size = 0; size < 4; ++size) {
            const int offset = int(size * 16 + (size == 0 ? 7 : size == 1 ? 6 : size == 2 ? 4 : 0));
            p.put(store(1, 2, offset, size)); p.put(load(8 + size, 1, offset, size));
            if (size < 3) p.put(load(12 + size, 1, offset, size + 4));
            p.put(store(1, 3, 64 + int(size * 8), size)); p.put(load(16 + size, 1, 64 + int(size * 8), size));
        }
        p.put(load(20, 1, 0)); p.put(load(21, 1, 16));
        p.put(load(22, 1, 32)); p.put(load(23, 1, 48));
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"branch_recovery"}; p.delay = 37; p.recovery = true;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 997)); p.put(addi(3, 0, 7));
        p.put(regOp(5, 2, 3, 5, true));
        // DIV holds the branch source. Younger memory and multiply instructions
        // may execute, but none of this wrong-path suffix may retire or store.
        const size_t firstBranch = p.words.size(); p.put(0);
        p.put(load(10, 1, 256)); p.put(regOp(11, 2, 3, 0, true));
        p.put(store(1, 11, 512)); p.put(addi(12, 0, 999));
        p.put(load(13, 1, 264)); p.put(regOp(14, 2, 3, 0, true));
        const size_t firstTarget = p.words.size();
        p.words[firstBranch] = branch(5, 5, int((firstTarget - firstBranch) * 4));
        p.put(load(6, 1, 272));
        const size_t secondBranch = p.words.size(); p.put(0);
        p.put(regOp(15, 6, 3, 0, true)); p.put(load(16, 1, 280));
        p.put(store(1, 2, 520)); p.put(addi(17, 0, 888));
        const size_t secondTarget = p.words.size();
        p.words[secondBranch] = branch(6, 6, int((secondTarget - secondBranch) * 4));
        p.put(regOp(18, 5, 6)); p.put(load(19, 1, 512)); p.put(load(20, 1, 520));
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"csr_fence_recovery"}; p.delay = 11; p.recovery = true;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 123));
        p.put(csr(3, 2, 1)); p.put(csr(4, 0, 2)); p.put(csr(5, 2, 3));
        p.put(csr(6, 17, 5)); p.put(csr(7, 4, 6)); p.put(csr(8, 1, 7));
        p.put(csr(9, 0, 2)); p.put(store(1, 9, 0)); p.put(fenceI);
        p.put(load(10, 1, 0)); p.put(regOp(11, 10, 4));
        p.put(csr(0, 2, 1)); p.put(csr(12, 0, 2));
        p.put(fenceI); p.put(addi(13, 12, 2));
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"bounded_branch_loop"}; p.delay = 6; p.recovery = true;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 12)); p.put(addi(3, 0, 0));
        const size_t loop = p.words.size();
        p.put(addi(3, 3, 1)); p.put(regOp(4, 3, 3, 0, true));
        p.put(load(5, 1, 320)); p.put(regOp(6, 5, 4)); p.put(addi(2, 2, -1));
        p.put(branch(2, 0, -int((p.words.size() - loop) * 4), 1));
        p.put(store(1, 6, 328)); p.put(load(7, 1, 328));
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"signed_divide_fs_off"};
        p.put(addi(1, 0, -101)); p.put(addi(2, 0, 7));
        p.put(regOp(3, 1, 2, 4, true)); p.put(regOp(4, 1, 2, 6, true));
        p.put(regOp(5, 1, 0, 4, true)); p.put(regOp(6, 1, 0, 6, true));
        p.put(addi(7, 0, 1)); p.put(slli(7, 7, 63)); p.put(addi(8, 0, -1));
        p.put(regOp(9, 7, 8, 4, true)); p.put(regOp(10, 7, 8, 6, true));
        p.put(regOp(11, 1, 2, 0, true)); p.put(regOp(12, 7, 8, 5, true));
        p.put(regOp(13, 7, 8, 7, true)); p.put(regOp(14, 11, 3));
        // FS remains Off after reset: this otherwise supported FMV must trap
        // precisely as illegal, without committing itself or its suffix.
        p.put(0xf2000053u | 6u << 15 | 1u << 7);
        p.put(addi(14, 0, 999)); p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"bounded_fp_system"}; p.delay = 8;
        p.put(auipc(1, 0x1000)); p.put(0x000022b7); // LUI x5,2.
        p.put(0x300u << 20 | 5u << 15 | 2u << 12 | 0x73); // CSRRS x0,mstatus,x5.
        p.put(load(6, 1, 768)); p.put(addi(2, 0, 17)); p.put(addi(3, 0, 19));
        p.put(0xf2000053u | 6u << 15 | 1u << 7); // FMV.D.X f1,x6.
        p.put(regOp(8, 2, 3, 0, true)); p.put(load(9, 1, 400));
        p.put(0x02000053u | 1u << 20 | 1u << 15 | 2u << 7); // FADD.D f2,f1,f1,RNE.
        p.put(addi(10, 8, 1)); p.put(regOp(11, 9, 10));
        p.put(0xe2000053u | 2u << 15 | 7u << 7); // FMV.X.D x7,f2.
        p.put(regOp(12, 7, 2)); p.put(store(1, 7, 776)); p.put(load(13, 1, 776));
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"held_load_contention"}; p.contention = 1;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 7));
        p.put(load(4, 1, 0));
        p.put(addi(8, 4, 1)); p.put(addi(9, 4, 2));
        p.put(load(5, 1, 8));
        p.put(addi(10, 5, 3)); p.put(regOp(11, 8, 9));
        p.put(regOp(12, 10, 11)); p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"held_alu_exchange"}; p.contention = 2;
        p.put(auipc(1, 0x1000)); p.put(addi(2, 0, 7));
        p.put(load(4, 1, 16)); p.put(regOp(5, 4, 2, 0, true));
        p.put(load(6, 1, 24)); p.put(addi(7, 4, 1));
        for (unsigned i = 0; i < 18; ++i) p.put(addi(7, 7, int(i + 1)));
        p.put(regOp(8, 7, 5)); p.put(regOp(9, 8, 6));
        p.put(ebreak); all.push_back(p);
    }
    {
        Program p{"system_alu_collision"}; p.contention = 3; p.commitPressure = false;
        p.put(addi(1, 0, 17)); p.put(addi(3, 0, 1));
        for (unsigned group = 0; group < 6; ++group) {
            p.put(csr(4, 1, 1));
            for (unsigned i = 0; i < 12; ++i) p.put(addi(3, 3, int(i + 1)));
        }
        p.put(csr(5, 0, 2)); p.put(regOp(6, 3, 5)); p.put(ebreak); all.push_back(p);
    }
    return all;
}

struct Reply { uint64_t due = 0, data = 0, sequence = 0; };
struct BusRequest {
    uint64_t address = 0, data = 0;
    unsigned size = 0, mask = 0;
    bool write = false, atomic = false, virtualized = false;
    bool operator==(const BusRequest &other) const {
        return std::tie(address, data, size, mask, write, atomic, virtualized) ==
            std::tie(other.address, other.data, other.size, other.mask, other.write, other.atomic, other.virtualized);
    }
};
struct Counters {
    uint64_t cycles = 0, inspectionCycles = 0, renamed = 0, retired = 0, issue = 0, issue2 = 0, commit2 = 0;
    uint64_t dualStart = 0, dualComplete = 0, exchange = 0, aluForward = 0, loadForward = 0;
    uint64_t requests = 0, responses = 0, stores = 0, requestHeld = 0, responseHeld = 0;
    uint64_t redirects = 0, redirectWithReply = 0, maxOccupancy = 0, maxReplies = 0;
    uint64_t ticketReuse = 0, commitBlocked = 0, wrongPathRenamed = 0;
    uint64_t systemOtherComplete = 0, mulDivCancelled = 0, mulDivMultiCancel = 0;
};

class Test {
    std::unique_ptr<GsimModelStorage<SA1DualBackendGsim>> storage;
    SA1DualBackendGsim &dut;
    const Program &program;
    Oracle oracle;
    Bytes deviceMemory;
    std::deque<Reply> replies;
    std::set<std::pair<unsigned, uint64_t>> committedTokens;
    std::map<unsigned, uint64_t> previousTag;
    std::optional<BusRequest> heldRequest;
    uint64_t feedPc = codeBase, cycle = 0;
    size_t retired = 0, storeIndex = 0;
    bool terminal = false, previousRedirect = false;
    bool inject = false, injected = false;
    std::set<uint64_t> architecturalPcs;
    Counters counts;

    void check(bool ok, const std::string &why) const {
        require(ok, program.name + " cycle=" + std::to_string(cycle) + " " + why);
    }
    void driveIdle() {
        dut.set_io$$valid0(false); dut.set_io$$valid1(false);
        dut.set_io$$instruction0(0x13); dut.set_io$$instruction1(0x13);
        dut.set_io$$pc0(codeBase); dut.set_io$$pc1(codeBase + 4);
        dut.set_io$$commitEnable(true); dut.set_io$$inspectRegister(0);
        dut.set_io$$memory$$request$$ready(false);
        dut.set_io$$memory$$response$$valid(false);
        dut.set_io$$memory$$response$$bits$$data(0);
        dut.set_io$$memory$$response$$bits$$error(false);
        dut.set_io$$memory$$response$$bits$$pageFault(false);
    }
    void commit(Retire actual, unsigned index, uint64_t tag) {
        check(!terminal, "retirement after terminal trap");
        check(retired < oracle.retirements.size(), "unexpected extra retirement");
        check(index < 16, "commit token exceeds A1 ROB16");
        check(committedTokens.insert({index, tag}).second, "duplicate full-token retirement");
        if (previousTag.count(index)) {
            check(previousTag.at(index) != tag, "ROB slot reuse retained old ticket");
            ++counts.ticketReuse;
        }
        previousTag[index] = tag;
        const auto &expected = oracle.retirements.at(retired);
        if (inject && !injected && retired >= 5 && expected.writes) {
            actual.data ^= 1;
            injected = true;
            std::cerr << "A1_NEGATIVE_REACHED program=" << program.name << " retired=" << retired
                << " pc=" << hex(actual.pc) << " mutation=sampled_retirement_data\n";
        }
        check(actual.pc == expected.pc, "retirement PC expected=" + hex(expected.pc) + " actual=" + hex(actual.pc));
        check(actual.word == expected.word, "retirement instruction expected=" + hex(expected.word) + " actual=" + hex(actual.word));
        check(actual.rd == expected.rd, "retirement rd expected=" + std::to_string(expected.rd) + " actual=" + std::to_string(actual.rd));
        check(actual.writes == expected.writes, "retirement writesRd/x0 mismatch at " + hex(actual.pc));
        // CommitRecord.data is architectural only when it writes a GPR.
        // Stores/branches/x0/FP-destination completions may carry arbitrary
        // payload values. FP semantics are checked through FMV.X.D and memory.
        if (expected.writes)
            check(actual.data == expected.data, "retirement data expected=" + hex(expected.data) + " actual=" + hex(actual.data) + " pc=" + hex(actual.pc));
        check(actual.nextPc == expected.nextPc, "retirement nextPc expected=" + hex(expected.nextPc) + " actual=" + hex(actual.nextPc));
        ++retired; ++counts.retired;
    }
    bool tick(bool offer = true, unsigned inspect = 0) {
        const bool valid0 = offer && !terminal && program.contains(feedPc);
        const bool valid1 = valid0 && program.contains(feedPc + 4);
        const bool commitEnable = program.contention == 1 || program.contention == 2
            ? !(cycle >= 24 && cycle < 30)
            : !program.commitPressure || cycle % 23 >= 5;
        const bool ready = program.contention == 1 || program.contention == 2
            ? cycle % 13 != 4
            : cycle % 11 != 2 && cycle % 11 != 3 && cycle % 17 != 8;
        const bool response = !replies.empty() && replies.front().due <= cycle;
        dut.set_io$$valid0(valid0); dut.set_io$$valid1(valid1);
        dut.set_io$$instruction0(valid0 ? program.at(feedPc) : 0x13);
        dut.set_io$$instruction1(valid1 ? program.at(feedPc + 4) : 0x13);
        dut.set_io$$pc0(feedPc); dut.set_io$$pc1(feedPc + 4);
        dut.set_io$$commitEnable(commitEnable); dut.set_io$$inspectRegister(inspect);
        dut.set_io$$memory$$request$$ready(ready);
        dut.set_io$$memory$$response$$valid(response);
        dut.set_io$$memory$$response$$bits$$data(response ? replies.front().data : 0);
        dut.set_io$$memory$$response$$bits$$error(false);
        dut.set_io$$memory$$response$$bits$$pageFault(false);
        dut.step();

        const bool redirect = dut.get_io$$redirect$$valid();
        const bool trap = dut.get_io$$trap$$valid();
        const bool renamed0 = dut.get_io$$renamed0(), renamed1 = dut.get_io$$renamed1();
        check(!renamed0 || valid0, "renamed absent lane 0");
        check(!renamed1 || (valid1 && renamed0), "rename broke offered prefix");
        for (unsigned lane = 0; lane < unsigned(renamed0) + unsigned(renamed1); ++lane) {
            ++counts.renamed;
            if (!architecturalPcs.count(feedPc + lane * 4) && feedPc + lane * 4 != oracle.trapPc)
                ++counts.wrongPathRenamed;
        }
        feedPc += 4 * (unsigned(renamed0) + unsigned(renamed1));
        const unsigned issue = dut.get_io$$issueCount();
        check(issue <= 2, "global two-issue budget exceeded");
        counts.issue += issue; counts.issue2 += issue == 2;
        counts.dualStart += dut.get_io$$dualSideStart();
        counts.dualComplete += dut.get_io$$dualSideComplete();
        counts.exchange += dut.get_io$$exchangedOperands();
        counts.aluForward += dut.get_io$$aluHeldForward();
        counts.loadForward += dut.get_io$$loadHeldForward();
        counts.systemOtherComplete += dut.get_io$$systemAndOtherComplete();
        counts.mulDivCancelled += dut.get_io$$mulDivCancelled();
        counts.mulDivMultiCancel += dut.get_io$$mulDivMultiCancel();
        counts.maxOccupancy = std::max(counts.maxOccupancy, uint64_t(dut.get_io$$occupancy()));
        check(dut.get_io$$occupancy() <= 16, "ROB occupancy exceeded preserved A1 capacity");
        counts.commitBlocked += !commitEnable;
        const bool commit0 = dut.get_io$$commit0$$valid(), commit1 = dut.get_io$$commit1$$valid();
        check(!commit1 || commit0, "retirement broke two-lane prefix");
        check(commitEnable || (!commit0 && !commit1), "retirement ignored commit backpressure");
        counts.commit2 += commit0 && commit1;
#define COMMIT(N) \
        if (dut.get_io$$commit##N##$$valid()) commit( \
            {dut.get_io$$commit##N##$$bits$$pc(), dut.get_io$$commit##N##$$bits$$data(), \
             dut.get_io$$commit##N##$$bits$$nextPc(), uint32_t(dut.get_io$$commit##N##$$bits$$instruction()), \
             unsigned(dut.get_io$$commit##N##$$bits$$rd()), bool(dut.get_io$$commit##N##$$bits$$writesRd())}, \
            dut.get_io$$commit##N##$$bits$$token$$index(), dut.get_io$$commit##N##$$bits$$token$$tag())
        COMMIT(0); COMMIT(1);
#undef COMMIT
        if (trap) {
            check(!terminal, "duplicate terminal trap");
            check(retired == oracle.retirements.size(), "trap before independent architectural prefix completed");
            check(dut.get_io$$trap$$bits$$pc() == oracle.trapPc, "imprecise terminal trap PC");
            check(dut.get_io$$trap$$bits$$cause() == oracle.trapCause,
                "terminal trap cause expected=" + std::to_string(oracle.trapCause));
            check(dut.get_io$$trap$$bits$$tval() == oracle.trapTval, "terminal trap tval mismatch");
            terminal = true;
        }
        if (redirect) {
            const uint64_t pc = dut.get_io$$redirect$$bits$$pc(), target = dut.get_io$$redirect$$bits$$target();
            if (trap) check(pc == oracle.trapPc && target == 0, "reset-M-mode terminal trap redirect mismatch");
            else {
                check(oracle.legalRedirects.count(pc) && oracle.legalRedirects.at(pc).count(target),
                    "redirect not justified by independent control flow pc=" + hex(pc) + " target=" + hex(target));
                check(program.contains(target), "redirect leaves bounded program");
                ++counts.redirects;
                counts.redirectWithReply += !replies.empty();
            }
            // Only the host offer cursor follows the DUT redirect. The oracle
            // PC, register state, memory and expected retirements never do.
            feedPc = target;
        }
        if (response && dut.get_io$$memory$$response$$ready()) {
            check(replies.front().sequence == counts.responses, "ordered response obligation mismatch");
            replies.pop_front(); ++counts.responses;
        } else if (response) ++counts.responseHeld;

        const bool request = dut.get_io$$memory$$request$$valid();
        if (request) {
            BusRequest bus{dut.get_io$$memory$$request$$bits$$address(), dut.get_io$$memory$$request$$bits$$data(),
                unsigned(dut.get_io$$memory$$request$$bits$$size()), unsigned(dut.get_io$$memory$$request$$bits$$mask()),
                bool(dut.get_io$$memory$$request$$bits$$write()), bool(dut.get_io$$memory$$request$$bits$$atomic()),
                bool(dut.get_io$$memory$$request$$bits$$virtualized())};
            if (heldRequest && !redirect && !previousRedirect)
                check(bus == *heldRequest, "memory request payload changed during backpressure");
            check(!bus.atomic && !bus.virtualized, "unexpected atomic/translated request in Bare fixture");
            check(bus.size <= 3, "memory size exceeds 64-bit port");
            const unsigned bytes = 1u << bus.size;
            check(!(bus.address & (bytes - 1)), "misaligned external request");
            const unsigned mask = ((1u << bytes) - 1u) << (bus.address & 7);
            check(bus.mask == mask, "external byte-mask mismatch");
            deviceMemory.index(bus.address, bytes);
            if (ready) {
                if (bus.write) {
                    check(storeIndex < oracle.stores.size(), "wrong-path or duplicate external store");
                    const auto &expected = oracle.stores.at(storeIndex++);
                    check(bus.address == expected.address && bus.size == expected.size,
                        "external store address/size differs from independent architectural order");
                    const uint64_t shifted = expected.data << ((bus.address & 7) * 8);
                    check(bus.data == shifted, "external store data mismatch");
                    deviceMemory.busWrite(bus.address & ~UINT64_C(7), bus.data, bus.mask);
                    ++counts.stores;
                }
                const uint64_t data = deviceMemory.read(bus.address & ~UINT64_C(7), 8);
                // Every accepted request owns exactly one delayed ordered reply.
                // The delay depends only on public cycle/request ordinals.
                const uint64_t delay = program.delay + (counts.requests % 4) * 3 + (cycle % 3);
                const uint64_t scheduled = program.contention == 1 ? 40 :
                    program.contention == 2 ? 40 + counts.requests * program.responsePhase : cycle + delay;
                replies.push_back({std::max(cycle + 1, scheduled), data, counts.requests});
                ++counts.requests;
                counts.maxReplies = std::max(counts.maxReplies, uint64_t(replies.size()));
                heldRequest.reset();
            } else { heldRequest = bus; ++counts.requestHeld; }
        } else {
            // Speculative canceled memory offers may disappear during recovery.
            heldRequest.reset();
        }
        previousRedirect = redirect;
        ++cycle; ++counts.cycles;
        return terminal && replies.empty() && dut.get_io$$ownersIdle() &&
            !dut.get_io$$memoryBusy() && dut.get_io$$occupancy() == 0;
    }

public:
    explicit Test(const Program &p, bool negative)
        : storage(std::make_unique<GsimModelStorage<SA1DualBackendGsim>>()), dut(storage->get()),
          program(p), oracle(p), inject(negative) {
        for (const auto &expected : oracle.retirements) architecturalPcs.insert(expected.pc);
        dut.LOG_START = 1;
        dut.activateAll();
        driveIdle(); dut.set_reset(true); dut.step(); dut.step();
        dut.set_reset(false);
    }
    Counters run() {
        unsigned quiet = 0;
        while (cycle < 20000 && quiet < 4) {
            if (tick()) ++quiet; else quiet = 0;
        }
        check(quiet == 4, "timeout waiting for precise trap and all response/owner obligations to drain");
        check(counts.requests == counts.responses && replies.empty(), "request/response conservation failed");
        check(storeIndex == oracle.stores.size(), "architectural store never reached memory");
        check(deviceMemory.data == oracle.memory.data, "final independent byte-memory mismatch");
        check(!inject || injected, "negative mutation never reached a sampled retirement");
        check(counts.issue2 > 0 || program.name == "signed_divide_fs_off", "no two-issue witness in directed program");
        if (program.recovery) check(counts.redirects > 0, "directed recovery program never redirected");
#if A1_DUAL_OWNER
        // Fixed schedules above have demonstrated these accepted-capture
        // witnesses. Legacy is intentionally not required to expose new paths.
        if (program.contention == 1)
            check(counts.loadForward > 0, "held-load dependent capture witness absent");
        if (program.contention == 2 && program.responsePhase == 8)
            check(counts.exchange > 0 && counts.aluForward > 0,
                "exchanged held-ALU dependent capture witness absent");
#endif
        if (program.contention == 3)
            check(counts.systemOtherComplete > 0, "system and ordinary completion collision absent");
        // Timing ends once the terminal trap and all service/owner obligations
        // are drained. Register inspection is correctness-only, not execution.
        const Counters execution = counts;
#if A1_DUAL_INSPECT_VALUE
        for (unsigned reg = 0; reg < 32; ++reg) {
            tick(false, reg);
            check(dut.get_io$$committedValue() == oracle.registers[reg], "final committed register mismatch x" + std::to_string(reg));
        }
#endif
        const uint64_t inspectionCycles = counts.cycles - execution.cycles;
        counts = execution;
        counts.inspectionCycles = inspectionCycles;
        std::cout << "A1_DUAL_PROGRAM_PASS topology=" << (A1_DUAL_OWNER ? "dual-owner" : "legacy")
            << " program=" << program.name << " contention=" << program.contention
            << " response_phase=" << program.responsePhase << " cycles=" << counts.cycles
            << " inspection_cycles=" << counts.inspectionCycles << " retired=" << counts.retired
            << " renamed=" << counts.renamed << " issue=" << counts.issue << " issue2=" << counts.issue2
            << " commit2=" << counts.commit2 << " ticket_reuse=" << counts.ticketReuse
            << " side_dual_start=" << counts.dualStart << " side_dual_complete=" << counts.dualComplete
            << " exchanged_operands=" << counts.exchange << " alu_held_forward=" << counts.aluForward
            << " load_held_forward=" << counts.loadForward << " system_other_complete=" << counts.systemOtherComplete
            << " muldiv_cancelled=" << counts.mulDivCancelled << " muldiv_multi_cancel=" << counts.mulDivMultiCancel
            << " requests=" << counts.requests
            << " responses=" << counts.responses << " stores=" << counts.stores
            << " request_stall=" << counts.requestHeld << " response_stall=" << counts.responseHeld
            << " max_reply_debt=" << counts.maxReplies << " max_rob=" << counts.maxOccupancy
            << " commit_blocked=" << counts.commitBlocked << " redirects=" << counts.redirects
            << " redirect_pending_reply=" << counts.redirectWithReply << " wrong_path_renamed=" << counts.wrongPathRenamed
            << " oracle_load=" << oracle.loads << " oracle_mul=" << oracle.muls << " oracle_div=" << oracle.divs
            << " oracle_branch=" << oracle.branches << " oracle_system=" << oracle.systems << " oracle_fp=" << oracle.fps
            << " trap_pc=" << hex(oracle.trapPc) << " trap_cause=" << oracle.trapCause
            << " trap_tval=" << hex(oracle.trapTval) << " trap_count=1\n";
        std::cout << "A1_BACKEND_METRIC {\"name\":\"" << program.name << "\",\"topology\":\""
            << (A1_DUAL_OWNER ? "dual-owner" : "legacy") << "\",\"cycles\":" << counts.cycles
            << ",\"contention\":" << program.contention << ",\"response_phase\":" << program.responsePhase
            << ",\"inspection_cycles\":" << counts.inspectionCycles
            << ",\"retired\":" << counts.retired << ",\"issue2\":" << counts.issue2
            << ",\"side_dual_start\":" << counts.dualStart << ",\"side_dual_complete\":" << counts.dualComplete
            << ",\"system_other_complete\":" << counts.systemOtherComplete
            << ",\"exchanged_operands\":" << counts.exchange << ",\"alu_held_forward\":" << counts.aluForward
            << ",\"load_held_forward\":" << counts.loadForward << ",\"muldiv_cancelled\":" << counts.mulDivCancelled
            << ",\"redirect_pending_reply\":" << counts.redirectWithReply
            << ",\"trap_cause\":" << oracle.trapCause << "}\n";
        return counts;
    }
};
} // namespace

int main(int argc, char **argv) {
    try {
        bool inject = false;
        std::string selected;
        std::optional<unsigned> contentionPhase;
        for (int i = 1; i < argc; ++i) {
            const std::string option = argv[i];
            if (option == "--inject-mismatch") inject = true;
            else if (option == "--program" && i + 1 < argc) selected = argv[++i];
            else if (option == "--contention-phase" && i + 1 < argc) {
                contentionPhase = unsigned(std::stoul(argv[++i]));
                require(*contentionPhase <= 32, "contention phase must be <=32");
            } else throw std::runtime_error("usage: a1_dual_backend [--inject-mismatch] [--program NAME] [--contention-phase 0..32]");
        }
        unsigned completed = 0;
        Counters total;
        for (auto program : programs()) {
            if (!selected.empty() && program.name != selected) continue;
            if (contentionPhase && program.contention == 2) program.responsePhase = *contentionPhase;
            Test test(program, inject);
            const auto result = test.run();
            total.cycles += result.cycles; total.retired += result.retired;
            total.inspectionCycles += result.inspectionCycles;
            total.dualStart += result.dualStart; total.dualComplete += result.dualComplete;
            total.exchange += result.exchange; total.aluForward += result.aluForward; total.loadForward += result.loadForward;
            total.systemOtherComplete += result.systemOtherComplete;
            total.mulDivCancelled += result.mulDivCancelled; total.mulDivMultiCancel += result.mulDivMultiCancel;
            total.redirectWithReply += result.redirectWithReply; total.wrongPathRenamed += result.wrongPathRenamed;
            ++completed;
        }
        require(completed != 0, "unknown or empty program selection");
        require(!inject, "negative mode unexpectedly passed");
        std::cout << "A1_DUAL_BACKEND_PASS topology=" << (A1_DUAL_OWNER ? "dual-owner" : "legacy")
            << " programs=" << completed << " cycles=" << total.cycles
            << " inspection_cycles=" << total.inspectionCycles << " retired=" << total.retired
            << " side_dual_start=" << total.dualStart << " side_dual_complete=" << total.dualComplete
            << " exchanged_operands=" << total.exchange << " alu_held_forward=" << total.aluForward
            << " load_held_forward=" << total.loadForward << " system_other_complete=" << total.systemOtherComplete
            << " muldiv_cancelled=" << total.mulDivCancelled << " muldiv_multi_cancel=" << total.mulDivMultiCancel
            << " redirect_pending_reply=" << total.redirectWithReply
            << " wrong_path_renamed=" << total.wrongPathRenamed
            << " independent_oracle=1 deterministic_service=1 precise_terminal_trap=1\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "A1_DUAL_BACKEND_FAIL " << error.what() << '\n';
        return 1;
    }
}
