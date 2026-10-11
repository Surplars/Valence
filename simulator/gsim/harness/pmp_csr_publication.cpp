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
#ifndef PMP_BOUNDARY
#define PMP_BOUNDARY 0
#endif
using namespace pmp_csr_oracle;
static_assert(PMP_ENTRIES == 0 || PMP_ENTRIES == 8 || PMP_ENTRIES == 16);
static void check(bool okay, const std::string& message) {
    if (!okay) throw std::runtime_error(message);
}
struct Input {
    bool start = false, completeReady = true, vmReady = true, fenceReady = true, trap = false;
    Command command{};
#if PMP_BOUNDARY
    bool memory = false, memoryWrite = false, prechecked = false, physicalReady = true, responseReady = true;
    bool response = false, drained = true, flush = false, query = false, queryReply = false;
    uint64_t memoryAddress = 0x80000000, memoryData = 0, responseData = 0;
    uint32_t requestEpoch = 0;
#endif
    uint64_t address = 0x1000, trapPc = 0x80000004;
    unsigned size = 2, access = 0;
};
struct Suite {
    SPmpCsrPublicationGsim dut;
    Model model{PMP_ENTRIES};
    uint64_t cycles = 0, commands = 0, snapshots = 0, queries = 0, flushHolds = 0, completeHolds = 0;
    uint64_t nextToken = 1;
    bool inject = false;
#if PMP_BOUNDARY
    unsigned mutation = 0;
    Entries previousPmp{};
    uint64_t previousSatp = 0, previousFlags = 0, rawEvents = 0, contextEvents = 0, boundaryChecks = 0;
    unsigned previousPrivilege = 0;
    uint32_t epoch = 0, postedEpoch = 0;
    bool stable = false;
    uint64_t accepted = 0, physicalAccepted = 0, responses = 0;
#endif
    explicit Suite(bool negative, unsigned mutant = 0) : inject(negative) {
#if PMP_BOUNDARY
        mutation = mutant;
#endif
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
#if PMP_BOUNDARY
        dut.set_io$$boundary$$request$$valid(in.memory);
        dut.set_io$$boundary$$request$$bits$$atomic(false);
        dut.set_io$$boundary$$request$$bits$$atomicOp(0);
        dut.set_io$$boundary$$request$$bits$$address(in.memoryAddress);
        dut.set_io$$boundary$$request$$bits$$write(in.memoryWrite);
        dut.set_io$$boundary$$request$$bits$$size(3);
        dut.set_io$$boundary$$request$$bits$$data(in.memoryData);
        dut.set_io$$boundary$$request$$bits$$mask(255);
        dut.set_io$$boundary$$request$$bits$$virtualized(false);
        dut.set_io$$boundary$$request$$bits$$precheckedLoad(in.prechecked);
        dut.set_io$$boundary$$request$$bits$$translationEpoch(in.requestEpoch);
        dut.set_io$$boundary$$request$$bits$$prefetchNextAllowed(false);
        dut.set_io$$boundary$$request$$bits$$uncached(false);
        dut.set_io$$boundary$$physicalReady(in.physicalReady);
        dut.set_io$$boundary$$response$$valid(in.response);
        dut.set_io$$boundary$$response$$bits$$data(in.responseData);
        dut.set_io$$boundary$$response$$bits$$error(false);
        dut.set_io$$boundary$$response$$bits$$pageFault(false);
        dut.set_io$$boundary$$responseReady(in.responseReady);
        dut.set_io$$boundary$$aggregateDrained(in.drained);
        dut.set_io$$boundary$$flush(in.flush);
        dut.set_io$$boundary$$query$$valid(in.query);
        dut.set_io$$boundary$$query$$bits$$address(0x80000000);
        dut.set_io$$boundary$$query$$bits$$size(3);
        dut.set_io$$boundary$$query$$bits$$write(false);
        dut.set_io$$boundary$$queryReply$$valid(in.queryReply);
        dut.set_io$$boundary$$queryReply$$bits$$physicalAddress(0x80000000);
        dut.set_io$$boundary$$queryReply$$bits$$pbmt(0);
        dut.set_io$$boundary$$queryReply$$bits$$pageFault(false);
        dut.set_io$$boundary$$queryReply$$bits$$accessFault(false);
        dut.set_io$$boundary$$mutation(mutation);
        dut.set_io$$boundary$$poisonInvalid(true);
#endif
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
#if PMP_BOUNDARY
        bool rawChanged = false;
        for (unsigned i = 0; i < PMP_ENTRIES; ++i)
            rawChanged |= previousPmp[i].cfg != model.entries[i].cfg || previousPmp[i].addr != model.entries[i].addr;
        const bool changed = rawChanged || previousSatp != model.satp ||
            previousPrivilege != model.dataPrivilege() || previousFlags != (model.status & (3U << 18));
        if (compare) {
            check(!dut.get_io$$boundary$$mismatch(), "PMP boundary differential mismatch mutant=" + std::to_string(mutation));
            check(bool(dut.get_io$$boundary$$rawChanged()) == rawChanged,
                "PMP raw change phase oracle mismatch cycle=" + std::to_string(cycles));
            check(bool(dut.get_io$$boundary$$changed()) == changed &&
                bool(dut.get_io$$boundary$$oldChanged()) == changed, "PMP authorization change oracle mismatch cycle=" + std::to_string(cycles) +
                " expected=" + std::to_string(changed) + " actual=" + std::to_string(dut.get_io$$boundary$$changed()) +
                " reference=" + std::to_string(dut.get_io$$boundary$$oldChanged()) + " raw=" + std::to_string(rawChanged) +
                " prevpriv=" + std::to_string(previousPrivilege) + " priv=" + std::to_string(model.dataPrivilege()) +
                " prevsatp=" + std::to_string(previousSatp) + " satp=" + std::to_string(model.satp) +
                " prevflags=" + std::to_string(previousFlags) + " flags=" + std::to_string(model.status & (3U << 18)));
            check(dut.get_io$$boundary$$epoch() == ((PMP_BOUNDARY & 1) ? epoch : 0) &&
                dut.get_io$$boundary$$postedEpoch() == ((PMP_BOUNDARY & 2) ? postedEpoch : 0),
                "PMP epoch phase oracle mismatch");
            check(bool(dut.get_io$$boundary$$stable()) == (bool(PMP_BOUNDARY & 1) && stable && !in.flush),
                "PMP stable phase oracle mismatch");
            ++boundaryChecks; rawEvents += rawChanged; contextEvents += changed;
            accepted += in.memory && dut.get_io$$boundary$$requestReady();
            physicalAccepted += dut.get_io$$boundary$$physical$$valid() && in.physicalReady;
            responses += dut.get_io$$boundary$$upstreamResponse$$valid() && in.responseReady;
        }
        if (reset) {
            previousPmp = {}; previousSatp = previousFlags = 0; previousPrivilege = 0;
            epoch = postedEpoch = 0; stable = false;
        } else {
            previousPmp = model.entries; previousSatp = model.satp;
            previousFlags = model.status & (3U << 18); previousPrivilege = model.dataPrivilege();
            if (changed || in.flush) ++epoch;
            if (changed && in.drained && dut.get_io$$boundary$$idle()) ++postedEpoch;
            stable = !changed && !in.flush;
        }
#endif
        if (reset) {
            // GSIM evaluates NEXT during step even while reset is asserted.
            // Keep the public reset active through that settle before release,
            // so its speculative NEXT cannot consume the reset VM mismatch.
            dut.resetAll();
            model.reset();
            return;
        }
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
#if PMP_BOUNDARY
        in.physicalReady = false; // producer context publication cannot depend on downstream READY
#endif
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
#if PMP_BOUNDARY
    void memory(bool store, bool certified = false, bool stale = false, bool resetBusy = false) {
        check(model.phase == Phase::Idle, "memory test overlaps CSR");
        for (unsigned n = 0; n < 3; ++n) tick();
        Input in; in.memory = true; in.memoryWrite = store; in.prechecked = certified;
        in.requestEpoch = stale ? epoch - 1 : epoch;
        in.memoryData = 0x12345678; in.physicalReady = false; in.responseReady = false;
        unsigned watchdog = 0;
        do { check(++watchdog < 20, "memory acceptance timeout"); tick(in); }
        while (!dut.get_io$$boundary$$requestReady());
        in.memory = false;
        for (unsigned n = 0; n < 4; ++n) tick(in);
        if (resetBusy) { reset(); for (unsigned n = 0; n < 3; ++n) tick(); return; }
        if (stale) {
            check(!dut.get_io$$boundary$$physical$$valid(), "stale precheck issued physical request");
        } else {
            check(dut.get_io$$boundary$$physical$$valid(), "authorized request missing at held physical boundary");
            in.physicalReady = true; tick(in);
            in.response = true; in.responseData = 0xabcdef123456ULL;
            // The adapter retains response ownership but has no return-data buffer.
            // Hold downstream VALID/data until the upstream sink accepts it.
        }
        watchdog = 0;
        do { check(++watchdog < 20, "owner response timeout"); tick(in); }
        while (!dut.get_io$$boundary$$upstreamResponse$$valid());
        for (unsigned n = 0; n < 3; ++n) {
            tick(in);
            check(dut.get_io$$boundary$$upstreamResponse$$valid(), "held owner response disappeared");
            check(bool(dut.get_io$$boundary$$upstreamResponse$$bits$$error()) == stale,
                "authorization/fault response mismatch");
            if (!stale) check(dut.get_io$$boundary$$upstreamResponse$$bits$$data() == in.responseData,
                "owner response payload mismatch");
        }
        in.responseReady = true; tick(in); in.response = false; tick(); tick();
        check(dut.get_io$$boundary$$idle(), "owner did not drain");
    }
#endif
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
        const bool mutant = argc == 2 && std::string(argv[1]).find("--mutant=") == 0;
        check(argc == 1 || inject || (PMP_BOUNDARY && mutant), "usage: pmp_csr_publication [--inject-mismatch|--mutant=N]");
        Suite s(inject, mutant ? std::stoul(std::string(argv[1]).substr(9)) : 0);
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
#if PMP_BOUNDARY
        std::cout << "PMP CSR+phase stream PASS checks=" << s.boundaryChecks << " raw=" << s.rawEvents << " contexts=" << s.contextEvents << std::endl;
        s.reset();
        for (unsigned n = 0; n < 16; ++n) s.memory(n % 2);
        s.memory(false, false, false, true); // reset with a held physical owner
        if (PMP_BOUNDARY & 1) {
            s.addr(0, (0x80000000ULL >> 2) | 0x3fff); s.cfg(0, 0x1f);
            s.csr(0x180, 0x8000000000000001ULL); s.enter(1);
            s.memory(false, true, false); s.memory(false, true, true);
            s.returnMachine(); s.reset();
        }
#endif
        s.tick();
#if PMP_BOUNDARY
        check(s.boundaryChecks > 100 && s.rawEvents > 0 && s.contextEvents > s.rawEvents,
            "missing complete boundary/reset/VM coverage");
        std::cout << "PMP boundary PASS mode=" << PMP_BOUNDARY << " checks=" << s.boundaryChecks
                  << " raw_changes=" << s.rawEvents << " context_changes=" << s.contextEvents
                  << " requests=" << s.accepted << " physical=" << s.physicalAccepted << " responses=" << s.responses << '\n';
#endif
        check(s.snapshots >= 16 * s.queries / 2 && s.completeHolds > 0, "missing per-edge or backpressure checks");
        if (PMP_ENTRIES) check(s.flushHolds > 0, "missing held VM-flush checks");
        std::cout << "PMP CSR publication PASS entries=" << PMP_ENTRIES << " cycles=" << s.cycles
                  << " commands=" << s.commands << " entry_snapshots=" << s.snapshots
                  << " access_checks=" << s.queries << " flush_holds=" << s.flushHolds
                  << " completion_holds=" << s.completeHolds << '\n';
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
