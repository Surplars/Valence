#include "PmpCsrPublicationGsim.h"
#include "pmp_csr_oracle.h"
#include <array>
#include <cstring>
#include <type_traits>
#include <iostream>
#include <random>
#include <string>
#include <vector>

#ifndef PMP_ENTRIES
#define PMP_ENTRIES 16
#endif
using namespace pmp_csr_oracle;
static_assert(PMP_ENTRIES == 0 || PMP_ENTRIES == 8 || PMP_ENTRIES == 16);
static void check(bool okay, const std::string& message) {
    if (!okay) throw std::runtime_error(message);
}
struct Input {
    bool start = false, completeReady = true, vmReady = true, fenceReady = true, trap = false;
    Command command{};
    uint64_t address = 0x1000, trapPc = 0x80000004;
    unsigned size = 2, access = 0;
};
struct Suite {
    SPmpCsrPublicationGsim dut;
    Model model{PMP_ENTRIES};
    uint64_t cycles = 0, commands = 0, snapshots = 0, queries = 0, flushHolds = 0, completeHolds = 0;
    uint64_t nextToken = 1;
    bool inject = false;
    explicit Suite(bool negative) : inject(negative) {
        // Same pinned-GSIM host initialization contract as coherent_read_mshr.cpp:
        // init() uses a uint32_t pointer distance as a byte count. Fully initialize
        // its trivially-copyable host storage, then exercise real DUT reset edges.
        static_assert(std::is_trivially_copyable_v<SPmpCsrPublicationGsim>);
        std::memset(&dut, 0, sizeof(dut));
        dut.LOG_START = 1;
        dut.activateAll();
        reset();
    }
    void snapshot() {
        for (unsigned i = 0; i < 16; ++i) {
            uint64_t cfg = 0, addr = 0, low = 0, end = 0;
            bool lowHigh = false, endHigh = false, active = false;
#define ENTRY(n) case n: \
            cfg = dut.get_io$$snapshot$$entry##n##$$cfg(); \
            addr = dut.get_io$$snapshot$$entry##n##$$addr(); \
            low = dut.get_io$$snapshot$$entry##n##$$low(); \
            lowHigh = dut.get_io$$snapshot$$entry##n##$$lowHigh(); \
            end = dut.get_io$$snapshot$$entry##n##$$end(); \
            endHigh = dut.get_io$$snapshot$$entry##n##$$endHigh(); \
            active = dut.get_io$$snapshot$$entry##n##$$active(); break
            switch (i) {
                ENTRY(0); ENTRY(1); ENTRY(2); ENTRY(3); ENTRY(4); ENTRY(5); ENTRY(6); ENTRY(7);
                ENTRY(8); ENTRY(9); ENTRY(10); ENTRY(11); ENTRY(12); ENTRY(13); ENTRY(14); ENTRY(15);
            }
#undef ENTRY
            auto expected = range(model.entries, i);
            if (inject && i == 0) expected.end ^= 1;
            check(cfg == model.entries[i].cfg && addr == model.entries[i].addr,
                "PMP raw CSR oracle mismatch entry=" + std::to_string(i));
            check(low == uint64_t(expected.low) && lowHigh == bool(expected.low >> 64) &&
                  end == uint64_t(expected.end) && endHigh == bool(expected.end >> 64) && active == expected.active,
                "PMP publication oracle mismatch entry=" + std::to_string(i) + " cycle=" + std::to_string(cycles));
            ++snapshots;
        }
    }
    void result() {
        const auto& r = model.result;
        check(dut.get_io$$result$$completion$$data() == r.data &&
              dut.get_io$$result$$completion$$nextPc() == r.nextPc &&
              dut.get_io$$result$$completion$$token$$index() == 0 &&
              dut.get_io$$result$$completion$$token$$tag() == r.token &&
              bool(dut.get_io$$result$$completion$$exception()) == r.exception &&
              dut.get_io$$result$$completion$$cause() == r.cause &&
              dut.get_io$$result$$completion$$tval() == r.tval &&
              bool(dut.get_io$$result$$redirect()) == r.redirect &&
              bool(dut.get_io$$result$$invalidateFetch()) == r.invalidate,
            "PMP CSR completion/refetch oracle mismatch command=" + std::to_string(commands));
    }
    void tick(const Input& in = {}, bool reset = false, bool compare = true) {
        dut.set_reset(reset);
        dut.set_io$$start(in.start);
        dut.set_io$$instruction(in.command.instruction);
        dut.set_io$$operand(in.command.operand);
        dut.set_io$$pc(in.command.pc);
        dut.set_io$$token(in.command.token);
        dut.set_io$$completeReady(in.completeReady);
        dut.set_io$$vmFlushReady(in.vmReady);
        dut.set_io$$fenceIReady(in.fenceReady);
        dut.set_io$$trap(in.trap);
        dut.set_io$$trapPc(in.trapPc);
        dut.set_io$$trapCause(11);
        dut.set_io$$address(in.address);
        dut.set_io$$size(in.size);
        dut.set_io$$access(in.access);
        dut.step(); ++cycles;
        // GSIM reports combinational values before this call's edge. They are
        // the post-edge state from the preceding call. Observe EVERY cycle,
        // before advancing the independent model, including CSR publication,
        // reset release, held completions and unacknowledged VM/I-cache flushes.
        if (compare) {
            snapshot();
            check(bool(dut.get_io$$ready()) == (model.phase == Phase::Idle) &&
                  bool(dut.get_io$$trapReady()) == (model.phase == Phase::Idle), "PMP CSR capacity mismatch");
            check(bool(dut.get_io$$complete()) == (model.phase == Phase::Finish) &&
                  bool(dut.get_io$$vmFlush()) == (model.phase == Phase::VmFlush) &&
                  bool(dut.get_io$$fenceI()) == (model.phase == Phase::FenceI), "PMP CSR sequencing/flush mismatch");
            check(dut.get_io$$fetchPrivilege() == model.privilege &&
                  dut.get_io$$dataPrivilege() == model.dataPrivilege() && dut.get_io$$satp() == model.satp,
                  "PMP privilege/context oracle mismatch");
            check(bool(dut.get_io$$denied()) == denied(model.entries, PMP_ENTRIES, in.address, in.size,
                      in.access, model.dataPrivilege()) &&
                  bool(dut.get_io$$fetchDenied()) == denied(model.entries, PMP_ENTRIES, in.address, in.size, 2,
                      model.privilege), "PMP raw-state access oracle mismatch");
            queries += 2;
            if (model.phase == Phase::Finish || model.phase == Phase::VmFlush || model.phase == Phase::FenceI)
                result();
            flushHolds += model.phase == Phase::VmFlush && !in.vmReady;
            completeHolds += model.phase == Phase::Finish && !in.completeReady;
        }
        if (reset) { model.reset(); return; }
        if (model.phase == Phase::Execute) model.execute();
        else if (model.phase == Phase::VmFlush && in.vmReady) model.phase = Phase::Finish;
        else if (model.phase == Phase::FenceI && in.fenceReady) model.phase = Phase::Finish;
        else if (model.phase == Phase::Finish && in.completeReady) model.phase = Phase::Idle;
        else if (model.phase == Phase::Idle && in.start) { model.pending = in.command; model.phase = Phase::Execute; }
        if (in.trap) {
            check(model.phase == Phase::Idle, "invalid driver trap overlap"); model.trap(in.trapPc);
        }
    }
    void reset() {
        tick({}, true, false); tick({}, true); tick();
    }
    void command(uint32_t inst, uint64_t operand = 0, unsigned holds = 3) {
        check(model.phase == Phase::Idle, "driver issued overlapping command");
        Input in; in.start = true; in.command = {inst, operand, 0x80000000 + commands * 4, nextToken++};
        tick(in); ++commands;
        // Deassert VALID after acceptance, then poison invalid request payload.
        in.start = false;
        in.command = {0xffffffffU, UINT64_MAX, UINT64_MAX, UINT64_MAX};
        in.completeReady = in.vmReady = in.fenceReady = false;
        tick(in);
        for (unsigned n = 0; n < holds; ++n) { in.address = 0xfff + n; tick(in); }
        unsigned watchdog = 0;
        while (model.phase != Phase::Idle) {
            check(++watchdog < 5, "CSR transaction did not drain");
            in.completeReady = in.vmReady = in.fenceReady = true;
            tick(in);
        }
        tick();
    }
    void csr(unsigned address, uint64_t value, unsigned funct3 = 1, unsigned rs1 = 1, unsigned rd = 1) {
        command((address << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | 0x73, value);
    }
    void cfg(unsigned bank, uint64_t value) { csr(bank ? 0x3a2 : 0x3a0, value); }
    void addr(unsigned i, uint64_t value) { csr(0x3b0 + i, value); }
    void returnMachine() {
        Input in; in.trap = true; tick(in); tick();
    }
    void enter(unsigned privilege) {
        check(model.privilege == 3, "enter requires M mode");
        csr(0x341, 0x80004003); csr(0x300, uint64_t(privilege) << 11); command(0x30200073); tick();
    }
    void probe(uint64_t address) {
        for (unsigned size = 0; size < 8; ++size) for (unsigned access = 0; access < 4; ++access) {
            Input in; in.address = address; in.size = size; in.access = access; tick(in);
        }
    }
    void boundaries() {
        std::vector<uint64_t> addresses{0, 1, 3, 0xfff, 0x1000, 0x1003, 0x1004,
            (uint64_t(1) << 56) - 1, uint64_t(1) << 56, UINT64_MAX - 3, UINT64_MAX};
        for (unsigned i = 0; i < PMP_ENTRIES; ++i) {
            const auto r = range(model.entries, i);
            if (r.active) for (uint64_t edge : {uint64_t(r.low), uint64_t(r.end)})
                for (int delta : {-1, 0, 1}) addresses.push_back(edge + delta);
        }
        for (const auto address : addresses) probe(address);
    }
};

int main(int argc, char** argv) {
    try {
        const bool inject = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
        check(argc == 1 || inject, "usage: pmp_csr_publication [--inject-mismatch]");
        Suite s(inject);
        s.boundaries();
        // No-entry implementations reject PMP CSRs, with their original raw reset ports.
        s.csr(0x3a0, 0xffffffffffffffffULL); s.csr(0x3b0, UINT64_MAX); s.reset();
        if (PMP_ENTRIES) {
            // OFF raw writes, later TOR publication, equal/reversed bounds and
            // changing an OFF predecessor immediately change TOR low/active.
            s.addr(0, 0x400); s.addr(1, 0x800); s.cfg(0, 0x0b00); s.enter(1); s.boundaries(); s.returnMachine();
            for (auto lower : {0x800ULL, 0x801ULL, 0x7ffULL, 0ULL}) { s.addr(0, lower); s.boundaries(); }
            s.addr(1, 0); s.boundaries(); s.reset();
            // NA4 partial overlap and first-entry priority over a wider NAPOT grant.
            s.addr(0, 0x400); s.addr(1, 0x403); s.cfg(0, 0x1f11); s.enter(0); s.boundaries(); s.returnMachine();
            // RW, RS, RC, immediate forms, zero-source read-only/no-op operations,
            // x0 write suppression and W-without-R/reserved-bit sanitization.
            s.cfg(0, 0x627e1f1b17131109ULL); s.csr(0x3a0, 0x0000000000000400ULL, 2);
            s.csr(0x3a0, 0x0000000000000200ULL, 3); s.csr(0x3a0, 31, 5, 31);
            s.csr(0x3a0, 0, 6, 0); s.csr(0x3a0, 0, 7, 0);
            s.csr(0x3a0, UINT64_MAX, 2, 0); s.csr(0x3a0, UINT64_MAX, 3, 0);
            s.csr(0x3b0, 0, 2, 1); s.csr(0x3b0, 0, 3, 1);
            s.csr(0x3b0, 0, 1, 0, 0); s.csr(0x3b0, 0x400, 1, 1, 0);
            s.csr(0x3b0, UINT64_MAX, 1); s.csr(0x3b0, UINT64_MAX, 3); s.boundaries();
            s.csr(0x3a1, UINT64_MAX); s.csr(0xf11, 1); s.csr(0xf11, UINT64_MAX, 2, 0);
            s.reset();
            // Every NAPOT carry length, highest implemented bit and 56/64-bit edges.
            s.cfg(0, 0x1f); s.csr(0x300, (1U << 17) | (1U << 11));
            for (unsigned n = 0; n <= 54; ++n) {
                s.addr(0, n == 54 ? addressMask : (uint64_t(1) << n) - 1);
                s.probe((uint64_t(1) << 56) - 1); s.probe(0); s.probe(UINT64_MAX);
            }
            s.reset();
            // Mixed locked/unlocked cfg-bank writes; next TOR locks its predecessor.
            s.addr(0, 0x400); s.addr(1, 0x800); s.addr(2, 0xc00);
            s.cfg(0, 0x1f8980); s.addr(0, 0); s.addr(1, 0); s.addr(2, 0x1000);
            s.cfg(0, 0x1b1b1b); s.boundaries();
            if (PMP_ENTRIES == 16) {
                s.addr(7, 0x500); s.addr(8, 0x900); s.cfg(1, 0x1f1b0989);
                s.addr(7, 0); s.cfg(1, 0x17171717); s.addr(15, addressMask); s.boundaries();
            }
            s.reset();
            s.addr(0, 0x403); s.cfg(0, 0x99); // Locked R-only NAPOT also constrains M.
            s.boundaries(); s.csr(0x300, (1U << 17) | (1U << 11)); s.boundaries();
            s.csr(0x300, 1U << 17); s.boundaries(); s.csr(0x300, (1U << 17) | (2U << 11)); s.boundaries();
            s.enter(1); s.csr(0x3a0, 0); s.csr(0x3b0, 0); s.boundaries(); s.returnMachine();
            s.enter(0); s.csr(0x3a0, 0); s.boundaries(); s.returnMachine();
            s.csr(0x180, 0x8000000000000001ULL); s.csr(0x180, 0xf000000000000001ULL);
            s.command(0x12000073); s.command(0x0000100f); s.csr(0x180, 0); s.reset();
            // Bounded deterministic CSR stream. Periodic reset prevents locks from
            // turning all random writes into ignored operations.
            std::mt19937_64 random(0x72616e676573);
            for (unsigned n = 0; n < 512; ++n) {
                if (n % 31 == 0) s.reset();
                const unsigned csr = n % 4 == 0 ? 0x3a0 : n % 4 == 1 ? 0x3a2 : 0x3b0 + random() % 16;
                const unsigned operations[] = {1, 2, 3, 5, 6, 7};
                s.csr(csr, random(), operations[random() % 6], random() % 32, random() % 32);
                Input in; in.address = random(); in.size = random() % 8; in.access = random() % 4; s.tick(in);
            }
            // Reset while a real permission-changing CSR is awaiting VM drain.
            s.reset(); Input in; in.start = true; in.command = {0x3a0090f3, 0x1f, 0x80000000, 0xffff};
            s.tick(in); in.start = false; in.vmReady = false; s.tick(in); s.tick(in); s.reset();
        } else {
            s.enter(1); s.boundaries(); s.csr(0x3a0, 0); s.returnMachine();
            s.command(0x0000100f); s.reset();
        }
        s.tick();
        check(s.snapshots >= 16 * s.queries / 2 && s.completeHolds > 0, "missing per-edge or backpressure checks");
        if (PMP_ENTRIES) check(s.flushHolds > 0, "missing held VM-flush checks");
        std::cout << "PMP CSR publication PASS entries=" << PMP_ENTRIES << " cycles=" << s.cycles
                  << " commands=" << s.commands << " entry_snapshots=" << s.snapshots
                  << " access_checks=" << s.queries << " flush_holds=" << s.flushHolds
                  << " completion_holds=" << s.completeHolds << '\n';
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
