#pragma once
#include <array>
#include <cstdint>
#include <stdexcept>

// Independent architectural model: native CSR instructions, filtered raw state,
// and half-open byte intervals. No DUT decoder, generated constants, or bounds
// are used to decide the expected state or access result.
namespace pmp_csr_oracle {
using Wide = unsigned __int128;
constexpr uint64_t addressMask = (uint64_t(1) << 54) - 1;
struct Entry { unsigned cfg = 0; uint64_t addr = 0; };
using Entries = std::array<Entry, 16>;
struct Range { Wide low = 0, end = 7; bool active = false; };
inline Range range(const Entries& entries, unsigned i) {
    const auto [cfg, addr] = entries.at(i);
    const unsigned mode = (cfg / 8) % 4;
    const Wide top = Wide(addr) * 4;
    if (mode == 1) {
        const Wide low = i ? Wide(entries[i - 1].addr) * 4 : 0;
        return {low, top ? top - 1 : (Wide(1) << 65) - 1, top > low};
    }
    if (mode == 2) return {top, top + 3, true};
    unsigned trailing = 0;
    while (trailing < 54 && ((addr >> trailing) & 1)) ++trailing;
    const Wide bytes = trailing >= 53 ? Wide(1) << 56 : Wide(8) << trailing;
    const Wide low = (top / bytes) * bytes;
    return {low, low + bytes - 1, mode == 3};
}
inline bool denied(const Entries& entries, unsigned count, uint64_t address,
                   unsigned size, unsigned access, unsigned privilege) {
    if (!count) return false;
    const Wide begin = address, limit = begin + (Wide(1) << size);
    for (unsigned i = 0; i < count; ++i) {
        const Range r = range(entries, i);
        if (!r.active || begin > r.end || limit <= r.low) continue;
        const unsigned cfg = entries[i].cfg;
        const bool permission = access == 0 ? cfg & 1 : access == 1 ? cfg & 2 :
            access == 2 ? cfg & 4 : (cfg & 3) == 3;
        return begin < r.low || limit > r.end + 1 ||
            ((privilege != 3 || (cfg & 128)) && !permission);
    }
    return privilege != 3;
}
struct Command { uint32_t instruction = 0; uint64_t operand = 0, pc = 0, token = 0; };
struct Result {
    uint64_t data = 0, nextPc = 0, token = 0, cause = 2, tval = 0;
    bool redirect = false, invalidate = false, exception = false;
};
enum class Phase { Idle, Execute, VmFlush, FenceI, Finish };
class Model {
public:
    unsigned count;
    Entries entries{};
    unsigned privilege = 3;
    uint64_t status = 0, epc = 0, satp = 0;
    Phase phase = Phase::Idle;
    Command pending{};
    Result result{};
    uint64_t rawChanges = 0, permissionChanges = 0;
    explicit Model(unsigned implemented) : count(implemented) {}
    void reset() { const auto n = count; *this = Model(n); }
    unsigned dataPrivilege() const { return privilege == 3 && (status & (1U << 17)) ? (status >> 11) & 3 : privilege; }
    unsigned mode(unsigned i) const { return (entries[i].cfg >> 3) & 3; }
    bool exists(unsigned csr) const {
        return csr == 0x300 || csr == 0x341 || csr == 0x301 || csr == 0xf11 || csr == 0xc01 ||
            (count && (csr == 0x180 || csr == 0x3a0 || csr == 0x3a2 ||
                       (csr >= 0x3b0 && csr < 0x3b0 + count)));
    }
    uint64_t read(unsigned csr) const {
        if (csr == 0x300) return 0xa00000000ULL | status;
        if (csr == 0x341) return epc;
        if (csr == 0x180) return satp;
        if (csr == 0x301) return (uint64_t(2) << 62) | (1U << 8) | (1U << 12) | (1U << 18) | (1U << 20);
        if (csr == 0x3a0 || csr == 0x3a2) {
            uint64_t value = 0;
            for (unsigned j = 0; j < 8; ++j) value |= uint64_t(entries[(csr == 0x3a0 ? 0 : 8) + j].cfg) << (8 * j);
            return value;
        }
        if (csr >= 0x3b0 && csr < 0x3c0) return entries[csr - 0x3b0].addr;
        return 0;
    }
    void execute() {
        const auto [inst, operand, pc, token] = pending;
        result = {}; result.nextPc = pc + 4; result.token = token; result.tval = inst;
        phase = Phase::Finish;
        const unsigned funct3 = (inst >> 12) & 7;
        if ((inst & 127) == 15 && funct3 <= 1) {
            result.redirect = result.invalidate = funct3 == 1;
            if (funct3 == 1) phase = Phase::FenceI;
            return;
        }
        if (inst == 0x10500073) return;
        if ((inst & 0xfe007fffU) == 0x12000073U && count && privilege >= 1) {
            result.redirect = result.invalidate = true; phase = Phase::VmFlush; return;
        }
        if ((inst & 127) == 0x73 && funct3) {
            const unsigned csr = inst >> 20, operation = funct3 & 3;
            const unsigned rs1 = (inst >> 15) & 31, rd = (inst >> 7) & 31;
            const uint64_t source = funct3 & 4 ? rs1 : operand;
            const bool write = operation == 1 || rs1 != 0;
            const bool doRead = operation != 1 || rd != 0;
            const uint64_t old = read(csr);
            result.data = doRead ? old : 0;
            const bool legal = exists(csr) && privilege >= ((csr >> 8) & 3) &&
                !(write && (csr >> 10) == 3) && (csr != 0xc01 || privilege == 3);
            result.exception = !legal;
            if (!legal || !write) return;
            const uint64_t value = operation == 2 ? old | source : operation == 3 ? old & ~source : source;
            bool changed = false, permissions = false;
            if (count && (csr == 0x3a0 || csr == 0x3a2)) {
                const unsigned first = csr == 0x3a0 ? 0 : 8;
                for (unsigned i = first; i < first + 8 && i < count; ++i) {
                    auto& e = entries[i];
                    if (e.cfg & 128) continue;
                    const unsigned raw = (value >> (8 * (i - first))) & 255;
                    const unsigned clean = (raw & 0x9d) | ((raw & 1) ? raw & 2 : 0);
                    changed |= clean != e.cfg; permissions |= clean != e.cfg; e.cfg = clean;
                }
            } else if (count && csr >= 0x3b0 && csr < 0x3b0 + count) {
                const unsigned i = csr - 0x3b0;
                const bool nextTor = i + 1 < count && mode(i + 1) == 1;
                if (!(entries[i].cfg & 128) && !(nextTor && (entries[i + 1].cfg & 128))) {
                    changed = entries[i].addr != (value & addressMask);
                    permissions = changed && (mode(i) != 0 || nextTor);
                    entries[i].addr = value & addressMask;
                }
            } else if (csr == 0x300) {
                constexpr uint64_t writable = (1U << 1) | (1U << 3) | (1U << 5) | (1U << 7) |
                    (1U << 8) | (3U << 11) | (1U << 17);
                status = value & (writable | (count ? (3U << 18) : 0));
                if (((status >> 11) & 3) == 2) status |= 3U << 11;
            } else if (csr == 0x341) epc = value & ~uint64_t(3);
            else if (csr == 0x180 && ((value >> 60) == 0 || (value >> 60) == 8)) {
                satp = value >> 60 ? value : 0; result.redirect = result.invalidate = true;
            }
            rawChanges += changed;
            permissionChanges += permissions;
            if (permissions) { result.redirect = result.invalidate = true; phase = Phase::VmFlush; }
            return;
        }
        if (inst == 0x30200073 && privilege == 3) {
            result.redirect = true; result.invalidate = count != 0; result.nextPc = epc;
            privilege = (status >> 11) & 3;
            const bool previousIe = status & (1U << 7);
            status &= ~uint64_t((3U << 11) | (1U << 3));
            status |= (1U << 7) | (previousIe ? 1U << 3 : 0);
            if (privilege != 3) status &= ~uint64_t(1U << 17);
            return;
        }
        result.exception = true;
    }
    void trap(uint64_t pc) {
        epc = pc & ~uint64_t(3);
        const bool ie = status & (1U << 3);
        status &= ~uint64_t((3U << 11) | (1U << 7) | (1U << 3));
        status |= (privilege << 11) | (ie ? 1U << 7 : 0);
        privilege = 3;
    }
};
} // namespace pmp_csr_oracle
