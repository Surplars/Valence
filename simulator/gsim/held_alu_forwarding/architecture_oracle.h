#pragma once
// Independent, bounded architectural reference for the immutable directed guest.
// No generated-model, DUT decode, PRF, ready, allocation, or response-data input.
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <map>
#include <optional>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace b1 {

enum class ArchKind {
    Addi, Slli, Auipc, Add, Mul, Divu, Load, Store, Branch, Jal, Jalr, Csr,
    Fence, FenceI, SfenceVma, Mret, Ecall
};

struct ArchInstruction {
    uint64_t pc = 0;
    uint32_t word = 0;
    uint8_t rs1 = 0, rs2 = 0, rd = 0;
    bool writes = false;
    ArchKind kind = ArchKind::Addi;
    uint64_t immediate = 0;
    uint16_t csr = 0;
    uint8_t csr_operation = 0;
};

struct ArchFault {
    uint64_t cause = 0, tval = 0;
    bool operator==(const ArchFault&) const = default;
};

struct ArchWalkStep {
    uint64_t pte_address = 0, pte = 0;
    unsigned level = 0;
};

struct ArchTranslation {
    uint64_t pa = 0;
    std::optional<ArchFault> fault;
    std::vector<ArchWalkStep> walk;
    unsigned privilege = 3;
};

struct ArchEvaluation {
    ArchInstruction instruction{};
    uint64_t result = 0, nextpc = 0, address = 0, physical_address = 0, store_value = 0;
    uint8_t size = 0;
    bool load = false, store = false;
    std::optional<ArchFault> trap;
    bool csr_write = false;
    uint64_t csr_value = 0;
    ArchTranslation translation{};
};

struct ArchStore {
    uint64_t pc = 0, virtual_address = 0, physical_address = 0, value = 0;
    unsigned size = 0;
    bool operator==(const ArchStore&) const = default;
};

class Architecture {
public:
    static constexpr uint64_t entry_pc = UINT64_C(0x80200000);
    static constexpr unsigned pmp_entries = 16;
    // Explicit RV64 platform profile: 56-bit physical addresses, four-byte PMP
    // granule, S/U implemented, no floating-point state in this guest.
    static constexpr uint64_t pmp_address_mask = (UINT64_C(1) << 54) - 1;
    static constexpr uint64_t physical_limit = UINT64_C(1) << 56;

    // Boot ROM is a separately fixed two-instruction prefix; guest.bin is
    // unchanged. Default construction retains the original guest-entry API.
    explicit Architecture(uint64_t start_pc = entry_pc) : pc_(start_pc) {
        if (start_pc != entry_pc && start_pc != UINT64_C(0x80000000))
            fail("start PC outside fixed boot/guest entries", start_pc);
        if (start_pc == UINT64_C(0x80000000)) {
            constexpr std::array<uint8_t, 8> boot{0x97, 0x02, 0x20, 0x00, 0x67, 0x80, 0x02, 0x00};
            seed_bytes(start_pc, boot);
        }
    }

    static ArchInstruction decode(uint32_t word) {
        ArchInstruction d;
        d.word = word;
        d.rd = static_cast<uint8_t>((word >> 7) & 31);
        const auto rs1 = static_cast<uint8_t>((word >> 15) & 31);
        const auto rs2 = static_cast<uint8_t>((word >> 20) & 31);
        const unsigned opcode = word & 127, f3 = (word >> 12) & 7, f7 = word >> 25;
        const auto writer = [&] { d.writes = d.rd != 0; };
        if (opcode == 0x13 && f3 == 0) {
            d.kind = ArchKind::Addi; d.rs1 = rs1;
            d.immediate = sign_extend(word >> 20, 12); writer();
        } else if (opcode == 0x13 && f3 == 1 && (word >> 26) == 0) {
            d.kind = ArchKind::Slli; d.rs1 = rs1;
            d.immediate = (word >> 20) & 63; writer();
        } else if (opcode == 0x17) {
            d.kind = ArchKind::Auipc;
            d.immediate = sign_extend(word & UINT32_C(0xfffff000), 32); writer();
        } else if (opcode == 0x33 && ((f7 == 0 && f3 == 0) ||
                                     (f7 == 1 && (f3 == 0 || f3 == 5)))) {
            d.kind = f7 == 0 ? ArchKind::Add : (f3 == 0 ? ArchKind::Mul : ArchKind::Divu);
            d.rs1 = rs1; d.rs2 = rs2; writer();
        } else if (opcode == 0x03 && f3 == 3) {
            d.kind = ArchKind::Load; d.rs1 = rs1;
            d.immediate = sign_extend(word >> 20, 12); writer();
        } else if (opcode == 0x23 && f3 == 3) {
            d.kind = ArchKind::Store; d.rs1 = rs1; d.rs2 = rs2;
            d.immediate = sign_extend(((word >> 25) << 5) | ((word >> 7) & 31), 12);
        } else if (opcode == 0x63 && f3 == 1) {
            d.kind = ArchKind::Branch; d.rs1 = rs1; d.rs2 = rs2;
            d.immediate = sign_extend(((uint64_t(word) >> 31) << 12) |
                (((word >> 7) & 1) << 11) | (((word >> 25) & 63) << 5) |
                (((word >> 8) & 15) << 1), 13);
        } else if (opcode == 0x6f) {
            d.kind = ArchKind::Jal;
            d.immediate = sign_extend(((uint64_t(word) >> 31) << 20) |
                (((word >> 12) & 255) << 12) | (((word >> 20) & 1) << 11) |
                (((word >> 21) & 1023) << 1), 21); writer();
        } else if (word == UINT32_C(0x00028067)) {
            d.kind = ArchKind::Jalr; d.rs1 = rs1;
            d.immediate = 0; writer(); // Exact fixed ROM JALR x0,x5,0 only.
        } else if (opcode == 0x73 && (f3 == 1 || f3 == 2)) {
            d.kind = ArchKind::Csr; d.rs1 = rs1; d.csr = static_cast<uint16_t>(word >> 20);
            d.csr_operation = static_cast<uint8_t>(f3); writer();
        } else if (word == UINT32_C(0x0330000f)) {
            d.kind = ArchKind::Fence;
        } else if (word == UINT32_C(0x0000100f)) {
            d.kind = ArchKind::FenceI;
        } else if (word == UINT32_C(0x12000073)) {
            d.kind = ArchKind::SfenceVma;
        } else if (word == UINT32_C(0x30200073)) {
            d.kind = ArchKind::Mret;
        } else if (word == UINT32_C(0x00000073)) {
            d.kind = ArchKind::Ecall;
        } else {
            fail("instruction outside frozen guest subset", word);
        }
        return d;
    }

    // Seeds are caller-supplied frozen input bytes, never observed DUT values.
    // Load guest.bin at entry_pc, then seed-file qwords, then case controls.
    void seed_bytes(uint64_t address, std::span<const uint8_t> bytes) {
        require_seed_phase();
        if (bytes.size() > physical_limit || address > physical_limit - bytes.size())
            fail("seed outside physical profile", address);
        for (size_t i = 0; i < bytes.size(); ++i) memory_[address + i] = bytes[i];
    }

    void seed_qword(uint64_t address, uint64_t value) {
        require_seed_phase();
        if ((address & 7) != 0) fail("unaligned seed qword", address);
        std::array<uint8_t, 8> bytes{};
        for (unsigned i = 0; i < 8; ++i) bytes[i] = static_cast<uint8_t>(value >> (i * 8));
        seed_bytes(address, bytes);
    }

    // Only D3's predeclared external load error is injected. D4/D5 must fault
    // through their actual seeded page tables / programmed PMP configuration.
    // Evaluation is pure; only architectural trap delivery consumes this rule.
    void inject_load_fault(uint64_t fault_pc, uint64_t cause, uint64_t tval) {
        require_seed_phase();
        if (cause != 5) fail("only predeclared D3 load access error may be injected", cause);
        if (!injected_.emplace(fault_pc, ArchFault{cause, tval}).second)
            fail("duplicate injected load fault", fault_pc);
    }

    uint64_t read_memory(uint64_t address, unsigned bytes = 8) const {
        if (bytes == 0 || bytes > 8 || address > std::numeric_limits<uint64_t>::max() - (bytes - 1))
            fail("invalid reference memory read", address);
        uint64_t value = 0;
        for (unsigned i = 0; i < bytes; ++i) {
            const auto found = memory_.find(address + i);
            if (found == memory_.end()) fail("unseeded reference memory byte", address + i);
            value |= uint64_t(found->second) << (8 * i);
        }
        return value;
    }

    uint64_t reg(unsigned index) const {
        if (index >= registers_.size()) fail("invalid architectural register", index);
        return registers_[index];
    }
    uint64_t pc() const { return pc_; }
    unsigned privilege() const { return privilege_; }
    unsigned data_privilege() const {
        return privilege_ == 3 && (mstatus_ & mprv_bit) ? unsigned((mstatus_ >> 11) & 3) : privilege_;
    }
    uint64_t context_epoch() const { return context_epoch_; }
    uint64_t retired_count() const { return retired_count_; }
    uint64_t trap_count() const { return trap_count_; }
    const std::vector<ArchStore>& store_history() const { return stores_; }
    const std::map<uint64_t, uint8_t>& memory() const { return memory_; }
    uint64_t pmp_address(unsigned index) const {
        if (index >= pmp_entries) fail("invalid PMP address index", index);
        return pmp_address_[index];
    }
    uint8_t pmp_config(unsigned index) const {
        if (index >= pmp_entries) fail("invalid PMP config index", index);
        return pmp_config_[index];
    }

    uint64_t csr(uint16_t address) const {
        if (address == 0x3b0 || address == 0x3b1)
            return pmp_address_[address - 0x3b0];
        switch (address) {
        case 0x140: return sscratch_;
        case 0x180: return satp_;
        case 0x300: return mstatus_;
        case 0x305: return mtvec_;
        case 0x341: return mepc_;
        case 0x342: return mcause_;
        case 0x343: return mtval_;
        case 0x3a0: {
            uint64_t result = 0;
            for (unsigned i = 0; i < 8; ++i) result |= uint64_t(pmp_config_[i]) << (8 * i);
            return result;
        }
        default: fail("CSR outside bounded architectural profile", address);
        }
    }

    bool physical_allowed(uint64_t pa, unsigned bytes, bool write, bool fetch = false) const {
        return pmp_allows(pa, bytes, write, fetch, fetch ? privilege_ : data_privilege());
    }

    ArchTranslation translate(uint64_t va, unsigned bytes, bool write, bool fetch = false) const {
        ArchTranslation t;
        t.privilege = fetch ? privilege_ : data_privilege();
        if (bytes == 0 || bytes > 64 || va > std::numeric_limits<uint64_t>::max() - (bytes - 1))
            fail("invalid bounded translation span", va);
        const uint64_t access_cause = fetch ? 1 : (write ? 7 : 5);
        const uint64_t page_cause = fetch ? 12 : (write ? 15 : 13);
        const auto access_fault = [&] { t.fault = ArchFault{access_cause, va}; return t; };
        const auto page_fault = [&] { t.fault = ArchFault{page_cause, va}; return t; };
        if (t.privilege == 3 || (satp_ >> 60) == 0) {
            t.pa = va;
            if (!pmp_allows(t.pa, bytes, write, fetch, t.privilege)) return access_fault();
            return t;
        }
        if ((satp_ >> 60) != 8) fail("unsupported non-Bare/non-Sv39 address mode", satp_);
        const uint64_t high = va >> 39;
        const uint64_t canonical_high = ((va >> 38) & 1) ? ((UINT64_C(1) << 25) - 1) : 0;
        if (high != canonical_high) return page_fault();
        // All frozen guest accesses are aligned and remain within one page.
        // A crossing line must be split by its caller; never bless only its start.
        if ((va & 4095) + bytes > 4096) fail("cross-page span outside bounded guest", va);
        uint64_t table = (satp_ & ((UINT64_C(1) << 44) - 1)) << 12;
        for (int level = 2; level >= 0; --level) {
            const uint64_t index = (va >> (12 + unsigned(level) * 9)) & 511;
            const uint64_t pte_address = table + index * 8;
            // Implicit supervisor page-table reads are PMP checked too.
            if (!pmp_allows(pte_address, 8, false, false, 1)) return access_fault();
            const uint64_t pte = read_memory(pte_address, 8);
            t.walk.push_back({pte_address, pte, unsigned(level)});
            const bool valid = (pte & 1) != 0, readable = (pte & 2) != 0;
            const bool writable = (pte & 4) != 0, executable = (pte & 8) != 0;
            const bool user = (pte & 16) != 0, accessed = (pte & 64) != 0, dirty = (pte & 128) != 0;
            if (!valid || (!readable && writable) || (pte >> 54) != 0) return page_fault();
            const uint64_t ppn = (pte >> 10) & ((UINT64_C(1) << 44) - 1);
            if (!readable && !executable) {
                // U/A/D are reserved in a non-leaf PTE in this Sv39 profile.
                if (user || accessed || dirty || level == 0) return page_fault();
                table = ppn << 12;
                continue;
            }
            if ((t.privilege == 0 && !user) ||
                (t.privilege == 1 && user && (fetch || !(mstatus_ & sum_bit)))) return page_fault();
            if ((fetch && !executable) || (write && !writable) ||
                (!fetch && !write && !(readable || ((mstatus_ & mxr_bit) && executable)))) return page_fault();
            const uint64_t low_ppn_mask = (UINT64_C(1) << (unsigned(level) * 9)) - 1;
            if (ppn & low_ppn_mask) return page_fault();
            // Frozen mappings deliberately set both A and D. Neither assume
            // Svade nor synthesize unobserved hardware PTE writes outside scope.
            if (!accessed || (write && !dirty)) fail("A/D update outside frozen mapping profile", pte_address);
            const uint64_t offset_mask = (UINT64_C(1) << (12 + unsigned(level) * 9)) - 1;
            t.pa = (ppn << 12) | (va & offset_mask);
            if (!pmp_allows(t.pa, bytes, write, fetch, t.privilege)) return access_fault();
            return t;
        }
        return page_fault();
    }

    ArchEvaluation evaluate(uint64_t instruction_pc, uint32_t word, uint64_t left, uint64_t right) const {
        ArchEvaluation e;
        e.instruction = decode(word);
        e.instruction.pc = instruction_pc;
        e.nextpc = instruction_pc + 4;
        const auto& d = e.instruction;
        // Never let an observed nonzero x0 become a reference source value.
        if (d.rs1 == 0) left = 0;
        if (d.rs2 == 0) right = 0;
        switch (d.kind) {
        case ArchKind::Addi: e.result = left + d.immediate; break;
        case ArchKind::Slli: e.result = left << d.immediate; break;
        case ArchKind::Auipc: e.result = instruction_pc + d.immediate; break;
        case ArchKind::Add: e.result = left + right; break;
        case ArchKind::Mul: e.result = left * right; break;
        case ArchKind::Divu: e.result = right == 0 ? UINT64_MAX : left / right; break;
        case ArchKind::Branch: if (left != right) e.nextpc = instruction_pc + d.immediate; break;
        case ArchKind::Jal: e.result = instruction_pc + 4; e.nextpc = instruction_pc + d.immediate; break;
        case ArchKind::Jalr: e.result = instruction_pc + 4; e.nextpc = (left + d.immediate) & ~UINT64_C(1); break;
        case ArchKind::Load: case ArchKind::Store: {
            e.load = d.kind == ArchKind::Load;
            e.store = d.kind == ArchKind::Store;
            e.size = 8; e.address = left + d.immediate; e.store_value = right;
            if (e.address & 7) { e.trap = ArchFault{e.store ? 6u : 4u, e.address}; break; }
            e.translation = translate(e.address, 8, e.store);
            e.physical_address = e.translation.pa;
            e.trap = e.translation.fault;
            if (e.trap) break;
            const auto injected = injected_.find(instruction_pc);
            if (e.load && injected != injected_.end()) {
                if (injected->second.tval != e.address) fail("D3 injection address mismatch", instruction_pc);
                e.trap = injected->second;
                break;
            }
            if (e.load) e.result = read_memory(e.physical_address, 8);
            else (void)read_memory(e.physical_address, 8); // Store range must be declared too.
            break;
        }
        case ArchKind::Csr: {
            const bool write = d.csr_operation == 1 || d.rs1 != 0;
            if (!csr_known(d.csr) || privilege_ < ((d.csr >> 8) & 3) ||
                (write && ((d.csr >> 10) & 3) == 3)) {
                e.trap = ArchFault{2, word}; break;
            }
            e.result = csr(d.csr);
            e.csr_write = write;
            e.csr_value = d.csr_operation == 1 ? left : e.result | left;
            break;
        }
        case ArchKind::SfenceVma:
            if (privilege_ < 1) e.trap = ArchFault{2, word};
            break;
        case ArchKind::Mret:
            if (privilege_ != 3) e.trap = ArchFault{2, word};
            else e.nextpc = mepc_;
            break;
        case ArchKind::Ecall: e.trap = ArchFault{privilege_ == 3 ? 11u : (privilege_ == 1 ? 9u : 8u), 0}; break;
        case ArchKind::Fence: case ArchKind::FenceI: break;
        }
        // This image contains no compressed words; its valid control targets
        // are four-byte aligned. IALIGN=16 remains the declared CPU profile.
        if (!e.trap && (e.nextpc & 1)) e.trap = ArchFault{0, e.nextpc};
        return e;
    }

    ArchEvaluation next() const {
        const auto fetch = translate(pc_, 4, false, true);
        if (fetch.fault) {
            ArchEvaluation e;
            e.instruction.pc = pc_; e.nextpc = pc_;
            e.trap = fetch.fault; e.translation = fetch;
            return e;
        }
        const uint32_t word = static_cast<uint32_t>(read_memory(fetch.pa, 4));
        const auto d = decode(word);
        return evaluate(pc_, word, reg(d.rs1), reg(d.rs2));
    }

    // Architectural result data is defined only for an effective GPR write.
    // Non-writers' raw destination/result wires are not architectural outputs.
    ArchEvaluation retire(uint64_t instruction_pc, uint32_t word, uint8_t rd, uint64_t result) {
        const ArchEvaluation e = next();
        require_equal("retirement PC", instruction_pc, pc_);
        require_equal("retirement instruction", word, e.instruction.word);
        if (e.trap) fail("faulting instruction retired", instruction_pc);
        if (e.instruction.writes) {
            require_equal("retirement destination", rd, e.instruction.rd);
            require_equal("retirement result", result, e.result);
        }
        commit(e);
        return e;
    }

    ArchEvaluation retire(uint64_t instruction_pc, uint32_t word, uint8_t rd, uint64_t result, uint64_t next_pc) {
        const auto e = next();
        require_equal("retirement next PC", next_pc, e.nextpc);
        return retire(instruction_pc, word, rd, result);
    }

    // A precise synchronous trap is independently derived from the next
    // unretired instruction. No faulting destination or store is committed.
    void trap(uint64_t instruction_pc, uint64_t cause, uint64_t tval) {
        require_equal("trap PC", instruction_pc, pc_);
        const auto e = next();
        if (!e.trap) fail("unexpected architectural trap", instruction_pc);
        require_equal("trap cause", cause, e.trap->cause);
        require_equal("trap tval", tval, e.trap->tval);
        if (cause >> 63) fail("interrupt outside frozen guest profile", cause);
        const uint64_t old_status = mstatus_;
        mstatus_ &= ~(mie_bit | mpie_bit | mpp_mask);
        if (old_status & mie_bit) mstatus_ |= mpie_bit;
        mstatus_ |= uint64_t(privilege_) << 11;
        mepc_ = instruction_pc & ~UINT64_C(1);
        mcause_ = cause; mtval_ = tval;
        privilege_ = 3;
        pc_ = mtvec_ & ~UINT64_C(3); // Synchronous exceptions always use BASE.
        injected_.erase(instruction_pc);
        ++trap_count_;
        ++context_epoch_;
        started_ = true;
    }

private:
    static constexpr uint64_t sie_bit = UINT64_C(1) << 1;
    static constexpr uint64_t mie_bit = UINT64_C(1) << 3;
    static constexpr uint64_t spie_bit = UINT64_C(1) << 5;
    static constexpr uint64_t mpie_bit = UINT64_C(1) << 7;
    static constexpr uint64_t spp_bit = UINT64_C(1) << 8;
    static constexpr uint64_t mpp_mask = UINT64_C(3) << 11;
    static constexpr uint64_t mprv_bit = UINT64_C(1) << 17;
    static constexpr uint64_t sum_bit = UINT64_C(1) << 18;
    static constexpr uint64_t mxr_bit = UINT64_C(1) << 19;
    static constexpr uint64_t status_writable = sie_bit | mie_bit | spie_bit | mpie_bit |
        spp_bit | mpp_mask | mprv_bit | sum_bit | mxr_bit;
    static constexpr uint64_t fixed_status = UINT64_C(0x0000000a00000000);

    uint64_t pc_ = entry_pc;
    unsigned privilege_ = 3;
    std::array<uint64_t, 32> registers_{};
    std::map<uint64_t, uint8_t> memory_;
    std::map<uint64_t, ArchFault> injected_;
    std::array<uint8_t, pmp_entries> pmp_config_{};
    std::array<uint64_t, pmp_entries> pmp_address_{};
    uint64_t mstatus_ = fixed_status;
    uint64_t satp_ = 0, mtvec_ = 0, mepc_ = 0, mcause_ = 0, mtval_ = 0;
    uint64_t sscratch_ = 0;
    uint64_t context_epoch_ = 0, retired_count_ = 0, trap_count_ = 0;
    bool started_ = false;
    std::vector<ArchStore> stores_;

    static uint64_t sign_extend(uint64_t value, unsigned bits) {
        const uint64_t sign = UINT64_C(1) << (bits - 1);
        return (value ^ sign) - sign;
    }
    [[noreturn]] static void fail(const char* what, uint64_t value) {
        std::ostringstream text;
        text << "architecture: " << what << " (0x" << std::hex << value << ')';
        throw std::runtime_error(text.str());
    }
    static void require_equal(const char* what, uint64_t got, uint64_t expected) {
        if (got == expected) return;
        std::ostringstream text;
        text << "architecture: " << what << " mismatch: observed=0x" << std::hex << got
             << " expected=0x" << expected;
        throw std::runtime_error(text.str());
    }
    void require_seed_phase() const {
        if (started_) fail("reference reseeding after execution is forbidden", pc_);
    }
    static bool csr_known(uint16_t address) {
        if (address == 0x3b0 || address == 0x3b1) return true;
        switch (address) {
        case 0x140: case 0x180: case 0x300: case 0x305:
        case 0x341: case 0x342: case 0x343: case 0x3a0: return true;
        default: return false;
        }
    }

    bool pmp_allows(uint64_t pa, unsigned bytes, bool write, bool fetch, unsigned effective_privilege) const {
        if (bytes == 0 || bytes > 64 || pa >= physical_limit || bytes > physical_limit - pa) return false;
        const uint64_t last = pa + bytes - 1;
        for (unsigned index = 0; index < pmp_entries; ++index) {
            const uint8_t cfg = pmp_config_[index];
            const unsigned mode = (cfg >> 3) & 3;
            if (mode == 0) continue;
            uint64_t low = 0, end = 0; // Half-open range; maximum end is 2^57.
            if (mode != 3) fail("PMP range outside frozen OFF/NAPOT profile", cfg);
            {
                unsigned ones = 0;
                while (ones < 54 && ((pmp_address_[index] >> ones) & 1)) ++ones;
                const uint64_t encoded_mask = (UINT64_C(1) << (ones + 1)) - 1;
                low = (pmp_address_[index] & ~encoded_mask) << 2;
                end = low + (UINT64_C(1) << (ones + 3));
            }
            if (last < low || pa >= end) continue;
            // The FIRST entry covering ANY byte owns the entire decision.
            if (pa < low || last >= end) return false;
            if (effective_privilege == 3 && !(cfg & 128)) return true;
            return (cfg & (fetch ? 4 : (write ? 2 : 1))) != 0;
        }
        return effective_privilege == 3;
    }

    void write_csr(uint16_t address, uint64_t value) {
        if (address == 0x3b0 || address == 0x3b1) {
            const unsigned index = address - 0x3b0;
            if (!(pmp_config_[index] & 128)) {
                const uint64_t next_address = value & pmp_address_mask;
                if (pmp_address_[index] != next_address) ++context_epoch_;
                pmp_address_[index] = next_address;
            }
            return;
        }
        switch (address) {
        case 0x140: sscratch_ = value; break;
        case 0x180:
            // Unsupported MODE is WARL: preserve the previous value.
            if ((value >> 60) == 0 || (value >> 60) == 8) {
                satp_ = (value >> 60) == 0 ? 0 : value;
                ++context_epoch_;
            }
            break;
        case 0x300: {
            if (((value >> 11) & 3) == 2) fail("reserved MPP outside bounded profile", value);
            const uint64_t next_status = fixed_status | (value & status_writable);
            if ((next_status ^ mstatus_) & (mpp_mask | mprv_bit | sum_bit | mxr_bit)) ++context_epoch_;
            mstatus_ = next_status;
            break;
        }
        case 0x305: mtvec_ = (value & ~UINT64_C(3)) | ((value & 3) == 1 ? 1 : 0); break;
        case 0x341: mepc_ = value & ~UINT64_C(1); break;
        case 0x342: mcause_ = value; break;
        case 0x343: mtval_ = value; break;
        case 0x3a0: {
            bool changed = false;
            for (unsigned i = 0; i < 8; ++i) {
                if (pmp_config_[i] & 128) continue;
                uint8_t cfg = static_cast<uint8_t>((value >> (8 * i)) & 0x9f);
                if (!(cfg & 1)) cfg = static_cast<uint8_t>(cfg & ~2u); // Reserved W=1/R=0 is WARL.
                const unsigned mode = (cfg >> 3) & 3;
                if (mode != 0 && mode != 3) fail("PMP range outside frozen OFF/NAPOT profile", cfg);
                changed |= cfg != pmp_config_[i];
                pmp_config_[i] = cfg;
            }
            if (changed) ++context_epoch_;
            break;
        }
        default: fail("unsupported committed CSR write", address);
        }
    }

    void commit(const ArchEvaluation& e) {
        if (e.trap) fail("internal attempt to commit fault", e.instruction.pc);
        if (e.store) {
            for (unsigned i = 0; i < e.size; ++i)
                memory_.at(e.physical_address + i) = static_cast<uint8_t>(e.store_value >> (8 * i));
            stores_.push_back({e.instruction.pc, e.address, e.physical_address, e.store_value, e.size});
        }
        if (e.csr_write) write_csr(e.instruction.csr, e.csr_value);
        if (e.instruction.kind == ArchKind::SfenceVma) ++context_epoch_;
        if (e.instruction.kind == ArchKind::Mret) {
            const unsigned returning_privilege = unsigned((mstatus_ >> 11) & 3);
            if (returning_privilege == 2) fail("reserved return privilege", returning_privilege);
            const bool old_mpie = (mstatus_ & mpie_bit) != 0;
            mstatus_ &= ~(mie_bit | mpp_mask);
            if (old_mpie) mstatus_ |= mie_bit;
            mstatus_ |= mpie_bit;
            if (returning_privilege != 3) mstatus_ &= ~mprv_bit;
            privilege_ = returning_privilege;
            ++context_epoch_;
        }
        if (e.instruction.writes) registers_[e.instruction.rd] = e.result;
        registers_[0] = 0;
        pc_ = e.nextpc;
        ++retired_count_;
        started_ = true;
    }
};

} // namespace b1
