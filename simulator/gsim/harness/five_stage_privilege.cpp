#include "FiveStagePrivilegeHarness.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
static void need(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
struct Test {
    SFiveStagePrivilegeHarness d;
    uint64_t checks = 0;
    Test() { reset(); }
    void reset() {
        d.set_reset(1); d.set_io$$writeValid(0); d.set_io$$trapValid(0);
        d.set_io$$mret(0); d.set_io$$sret(0); d.set_io$$sfence(0);
        d.set_io$$externalIrq(0); d.set_io$$supervisorExternalIrq(0);
        d.set_io$$softwareIrq(0); d.set_io$$timerIrq(0);
        d.set_io$$readAddress(0x300); d.set_io$$address(0); d.set_io$$size(0);
        d.set_io$$accessPrivilege(3); d.set_io$$execute(0); d.set_io$$writeAccess(0);
        d.step(); d.step(); d.set_reset(0); d.step();
    }
    uint64_t read(unsigned a, bool legal = true) {
        d.set_io$$readAddress(a); d.step(); ++checks;
        need(bool(d.get_io$$readLegal()) == legal, "independent CSR privilege/existence oracle");
        return d.get_io$$readData();
    }
    void write(unsigned a, uint64_t v) {
        d.set_io$$readAddress(a); d.set_io$$writeAddress(a); d.set_io$$writeData(v);
        d.set_io$$writeValid(1); d.step(); d.set_io$$writeValid(0); d.step();
    }
    void mret() { d.set_io$$mret(1); d.step(); d.set_io$$mret(0); d.step(); }
    void sret() { d.set_io$$sret(1); d.step(); d.set_io$$sret(0); d.step(); }
    void mode(unsigned m) { write(0x300, uint64_t(m) << 11); mret(); }
    uint64_t trap(uint64_t c, uint64_t pc = 0x80400104, uint64_t tval = 0x40004000) {
        d.set_io$$trapCause(c); d.set_io$$trapPc(pc); d.set_io$$trapTval(tval);
        d.set_io$$trapValid(1); d.step(); auto v = d.get_io$$vector();
        d.set_io$$trapValid(0); d.step(); return v;
    }
};
// Independently decode TOR/NA4/NAPOT with a trailing-ones loop and byte range intervals.
static bool pmpOracle(uint64_t a, unsigned size, unsigned priv, bool exec, bool write,
                      const std::array<uint8_t, 4> &cfg, const std::array<uint64_t, 4> &addr) {
    uint64_t length = 1ULL << size, limit = 1ULL << 36;
    if (a >= limit || length > limit - a) return false;
    for (unsigned i = 0; i < 4; ++i) {
        unsigned mode = cfg[i] >> 3 & 3;
        uint64_t lo = 0, hi = 0;
        if (mode == 1) { lo = i ? addr[i - 1] * 4 : 0; hi = addr[i] * 4; }
        if (mode == 2) { lo = addr[i] * 4; hi = lo + 4; }
        if (mode == 3) {
            unsigned n = 0; while (n < 34 && (addr[i] >> n & 1)) ++n;
            uint64_t bytes = 1ULL << (n + 3);
            lo = addr[i] * 4 & ~(bytes - 1); hi = lo + bytes;
        }
        if (!mode || a >= hi || a + length <= lo) continue;
        bool permission = cfg[i] >> (exec ? 2 : write ? 1 : 0) & 1;
        return a >= lo && a + length <= hi && ((priv == 3 && !(cfg[i] & 128)) || permission);
    }
    return priv == 3;
}
int main(int argc, char **argv) { try {
    Test t;
    bool mutate = argc > 1 && std::string(argv[1]) == "--wrong-delegation";
    uint64_t misa = t.read(0x301);
    need((misa & ((1ULL << 18) | (1ULL << 20))) == ((1ULL << 18) | (1ULL << 20)),
        "S/U misa capability missing");
    need(!(misa & ((1ULL << 0) | (1ULL << 2) | (1ULL << 3) | (1ULL << 5))), "unsupported ISA advertised");
    t.write(0x302, ~0ULL); need(t.read(0x302) == 0xb3ff, "medeleg WARL mask");
    t.write(0x303, ~0ULL); need(t.read(0x303) == 0x222, "mideleg machine interrupt delegation");
    t.write(0x180, (8ULL << 60) | (0xffffULL << 44) | 0x80220);
    need(t.read(0x180) == ((8ULL << 60) | 0x80220), "satp ASIDLEN=0/mode/PPN");
    t.write(0x180, (9ULL << 60) | 0x1234);
    need(t.read(0x180) == ((8ULL << 60) | 0x80220), "unsupported satp mode must ignore entire write");
    t.write(0x305, 0x80000101); t.write(0x105, 0x80400001);
    // Even a delegatable synchronous exception in M never traps downwards.
    need(t.trap(13) == 0x80000100 && t.d.get_io$$privilege() == 3, "M trap delegated downward");
    t.mode(1);
    need(t.d.get_io$$privilege() == 1 && !t.d.get_io$$mretLegal() && t.d.get_io$$sretLegal(), "MRET to S");
    t.read(0x300, false); t.read(0x301, false); t.read(0x3a0, false); t.read(0x100);
    need(t.trap(13) == (mutate ? 0x80000100 : 0x80400000), "independent delegated vector oracle");
    need(t.read(0x141) == 0x80400104 && t.read(0x142) == 13 && t.read(0x143) == 0x40004000,
        "S trap EPC/cause/tval");
    need(t.read(0x100) & 0x100, "S trap SPP not saved");
    t.sret(); need(t.d.get_io$$privilege() == 1, "SRET to S");
    // Undelegated S ECALL reaches M; MPRV must affect data only and clear on return below M.
    t.write(0x100, 0);
    need(t.trap(11) == 0x80000100 && t.d.get_io$$privilege() == 3, "undelegated trap failed");
    t.write(0x300, (1ULL << 17) | (1ULL << 11));
    need(t.d.get_io$$privilege() == 3 && t.d.get_io$$dataPrivilege() == 1, "MPRV effective privilege");
    t.write(0x306, 7); t.write(0x106, 7);
    t.mret(); need(t.d.get_io$$privilege() == 1 && !(t.read(0x100) & (1ULL << 17)), "MRET MPRV clear");
    t.write(0x100, 0); t.sret();
    need(t.d.get_io$$privilege() == 0 && !t.d.get_io$$wfiLegal(), "SRET to U/WFI privilege");
    need(t.read(0xc01) == 123, "U time counter enable");
    t.read(0x100, false); t.read(0x180, false); t.read(0x306, false);
    t.trap(8); need(t.d.get_io$$privilege() == 1 && !(t.read(0x100) & 0x100), "U ECALL delegated to S");
    // SEIP must be masked in M, eligible with SIE in S and globally enabled when in U.
    t.trap(11); t.write(0x304, 0xaaa); t.d.set_io$$supervisorExternalIrq(1); t.d.step();
    need(!t.d.get_io$$irqPending(), "delegated IRQ escaped into M");
    t.mode(1); need(!t.d.get_io$$irqPending(), "SIE=0 did not mask S IRQ");
    t.write(0x100, 2); need(t.d.get_io$$irqPending() && t.d.get_io$$irqCause() == (1ULL << 63 | 9),
        "S external IRQ priority/enable");
    need(t.trap(1ULL << 63 | 9) == 0x80400024, "vectored S interrupt address");
    t.d.set_io$$supervisorExternalIrq(0); t.d.step();
    t.write(0x100, 0); t.sret(); t.d.set_io$$supervisorExternalIrq(1); t.d.step();
    need(t.d.get_io$$irqPending(), "S global IE incorrectly gated IRQ from U");
    t.d.set_io$$supervisorExternalIrq(0); t.trap(11);
    t.write(0x300, (1ULL << 20) | (1ULL << 21) | (1ULL << 22) | (1ULL << 11));
    t.mret(); t.read(0x180, false);
    need(!t.d.get_io$$sfenceLegal() && !t.d.get_io$$sretLegal() && !t.d.get_io$$wfiLegal(), "TVM/TSR/TW");
    t.trap(11);
    t.write(0x306, 0); t.mode(0); t.read(0xc01, false); t.trap(11);
    // Configuration locking, including a locked TOR's predecessor address.
    t.reset(); t.write(0x3b0, 0x1000); t.write(0x3b1, 0x2000);
    t.write(0x3a0, 0x8f00); t.write(0x3b0, 0x3000); t.write(0x3b1, 0x4000); t.write(0x3a0, 0);
    need(t.read(0x3b0) == 0x1000 && t.read(0x3b1) == 0x2000 && t.read(0x3a0) == 0x8f00,
        "locked TOR predecessor/config/address changed");
    t.read(0x3a1, false); need(t.read(0x3bf) == 0, "unused PMP bank must be hardwired OFF");
    t.reset(); t.d.set_io$$supervisorExternalIrq(1);
    need(t.read(0x344) & 512, "external SEIP read disappeared");
    need(!(t.d.get_io$$readDataForWrite() & 512), "external SEIP leaked into CSRRS software write base");
    t.write(0x344, t.d.get_io$$readDataForWrite() | 32);
    t.d.set_io$$supervisorExternalIrq(0);
    need(t.read(0x344) == 32, "CSRRS mip latched external SEIP as software pending");
    t.reset(); std::mt19937_64 random(0x5355504d50);
    uint64_t pmpChecks = 0;
    for (unsigned batch = 0; batch < 40; ++batch) {
        std::array<uint8_t, 4> cfg{}; std::array<uint64_t, 4> addr{};
        uint64_t packed = 0;
        for (unsigned i = 0; i < 4; ++i) {
            unsigned mode = random() % 4, perms = random() % 8;
            if (!(perms & 1)) perms &= ~2U;
            cfg[i] = mode * 8 + perms; packed |= uint64_t(cfg[i]) << (8 * i);
            addr[i] = ((0x80000000ULL + random() % 8192) >> 2);
            if (mode == 3) addr[i] |= (1ULL << (random() % 8)) - 1;
            t.write(0x3b0 + i, addr[i]);
        }
        t.write(0x3a0, packed);
        for (unsigned n = 0; n < 300; ++n) {
            uint64_t a = n % 43 == 0 ? (1ULL << 36) : 0x80000000ULL + random() % 9000;
            unsigned size = random() % 9, priv = n % 3 == 0 ? 3 : n % 3 == 1 ? 1 : 0;
            bool exec = n % 5 == 0, write = n % 2;
            t.d.set_io$$address(a); t.d.set_io$$size(size); t.d.set_io$$accessPrivilege(priv);
            t.d.set_io$$execute(exec); t.d.set_io$$writeAccess(write); t.d.step();
            need(bool(t.d.get_io$$allow()) == pmpOracle(a, size, priv, exec, write, cfg, addr),
                "independent PMP interval/priority/partial-access oracle"); ++pmpChecks;
        }
    }
    std::cout << "FIVE_STAGE_PRIVILEGE_PASS csr_checks=" << t.checks << " pmp_checks=" << pmpChecks
        << " M_S_U_delegation_xret_MPRV_counter_TVM_TSR_TW_PMP_lock_priority_bounds=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
