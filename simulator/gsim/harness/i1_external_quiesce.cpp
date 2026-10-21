#include "I1ExternalQuiesceHarness.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>

// Independent raw ISA words and explicit architectural ledger. No DUT control/decode constants.
static bool trace = false;
constexpr uint64_t BASE = 0x80000000ULL, DATA = BASE + 0x2000, HANDLER = BASE + 0x100;
static void check(bool value, const std::string &why) { if (!value) throw std::runtime_error(why); }
static uint32_t ri(unsigned op, unsigned rd, unsigned f, unsigned rs, int imm) {
    return (uint32_t(imm) & 4095) << 20 | rs << 15 | f << 12 | rd << 7 | op;
}
static uint32_t store(unsigned rs, unsigned base, unsigned offset) {
    return (offset >> 5) << 25 | rs << 20 | base << 15 | 3 << 12 | (offset & 31) << 7 | 0x23;
}
struct Entry {
    uint64_t pc, next, value = 0, cause = 0, tval = 0;
    uint32_t ins;
    unsigned rd = 0;
    bool trap = false;
};
struct Program {
    std::map<uint64_t, uint32_t> code;
    std::deque<Entry> expected;
    uint64_t here = BASE, tail = 0;
    bool irq = false;
    void emit(uint32_t ins, unsigned rd = 0, uint64_t value = 0) {
        code[here] = ins;
        expected.push_back({here, here + 4, value, 0, 0, ins, rd, false});
        here += 4;
    }
    void finish() {
        emit(ri(0x13, 8, 0, 0, 0x55), 8, 0x55);
        tail = here; code[tail] = 0x0000006f; // Independently checked terminal self-loop.
    }
};
static Program arithmetic() {
    Program p;
    p.emit(0x00002217, 4, DATA);                    // auipc x4,2
    p.emit(ri(0x13, 1, 0, 0, 63), 1, 63);
    p.emit(ri(0x13, 2, 0, 0, 7), 2, 7);
    p.emit(0x0220c1b3, 3, 9);                     // div x3,x1,x2
    p.emit(store(1, 4, 0));
    p.emit(0x002232af, 5, 63);                    // amoadd.d x5,x2,(x4)
    p.emit(ri(0x03, 6, 3, 4, 0), 6, 70);
    p.emit(0x00630463); p.expected.back().next += 4; // beq x6,x6,+8
    p.code[p.here] = store(2, 4, 8); p.here += 4; // Poison side effect, never architectural.
    p.emit(0x0000100f);                            // fence.i
    const uint64_t ecall = p.here;
    p.emit(0x00000073); p.expected.back().trap = true; p.expected.back().cause = 11;
    const uint64_t resume = p.here;
    p.here = HANDLER;
    p.emit(ri(0x73, 10, 2, 0, 0x341), 10, ecall); // csrrs x10,mepc,x0
    p.emit(ri(0x13, 10, 0, 10, 4), 10, resume);
    p.emit(ri(0x73, 0, 1, 10, 0x341));
    p.emit(0x30200073); p.expected.back().next = resume;
    p.here = resume; p.finish();
    return p;
}
static Program interruptProgram() {
    Program p; p.irq = true;
    p.emit(ri(0x13, 7, 0, 0, 8), 7, 8);
    p.emit(ri(0x73, 0, 1, 7, 0x304));            // mie.MSIE
    p.emit(ri(0x73, 0, 6, 8, 0x300));            // mstatus.MIE
    p.emit(ri(0x13, 1, 0, 0, 63), 1, 63);
    p.emit(ri(0x13, 2, 0, 0, 7), 2, 7);
    p.emit(0x0220c1b3, 3, 9);
    p.finish(); p.code[HANDLER] = 0x30200073;
    return p;
}
struct Pending { unsigned due; uint64_t data; };
struct MemoryOffer {
    uint64_t address, data;
    unsigned size, mask, operation;
    bool write, atomic;
    bool operator==(const MemoryOffer &) const = default;
};
struct Coverage {
    unsigned cases = 0, stopped = 0, restarts = 0, heldOffer = 0, pendingFetch = 0, pendingData = 0;
    unsigned mulDiv = 0, fence = 0, branch = 0, trap = 0, mret = 0, irq = 0, cycles = 0;
    void add(const Coverage &b) {
        cases += b.cases; stopped += b.stopped; restarts += b.restarts; heldOffer += b.heldOffer; pendingFetch += b.pendingFetch;
        pendingData += b.pendingData; mulDiv += b.mulDiv; fence += b.fence; branch += b.branch;
        trap += b.trap; mret += b.mret; irq += b.irq; cycles += b.cycles;
    }
};
static Coverage run(Program p, int stopAt, bool negative = false, unsigned stopCount = 1) {
    std::cout << "CASE " << (p.irq ? "pending-irq" : "arithmetic") << " stop=" << stopAt << " repeats=" << stopCount << '\n';
    SI1ExternalQuiesceHarness d;
    d.set_reset(1); d.set_io$$quiesceRequest(0); d.set_io$$softwareIrq(0);
    d.set_io$$instructionRequest$$ready(0); d.set_io$$instructionResponse$$valid(0);
    d.set_io$$dataRequest$$ready(0); d.set_io$$dataResponse$$valid(0); d.set_io$$fenceReady(0);
    d.step(); d.step(); d.set_reset(0);
    std::optional<Pending> fetch, data;
    std::optional<uint64_t> heldFetch;
    std::optional<MemoryOffer> heldData;
    Coverage cov; cov.cases = 1;
    unsigned accepted = 0, replied = 0, successful = 0, retired = 0, fenceWait = 0, stoppedCycles = 0;
    unsigned fenceRetired = 0, irqCount = 0, requestNumber = 0;
    uint64_t memory = 0;
    bool requested = false, released = false, afterResume = false, irqAsserted = false, irqServiced = false;
    bool finished = false;
    auto require = [&](bool value, const std::string &why) {
        check(value, std::string(p.irq ? "irq" : "arithmetic") + " stop=" + std::to_string(stopAt) +
            " cycle=" + std::to_string(cov.cycles) + " retire=" + std::to_string(retired) + ": " + why);
    };
    for (unsigned cycle = 0; cycle < 3000; ++cycle) {
        cov.cycles = cycle;
        if (stopAt >= 0 && cycle == unsigned(stopAt)) { requested = true; ++requestNumber; }
        if (requested && released && afterResume && requestNumber < stopCount) {
            // A new stop starts only after a verified retirement following the prior release.
            // Keep the SAME CPU, register/memory state, and architectural ledger throughout.
            released = false; afterResume = false; stoppedCycles = 0; ++requestNumber;
        }
        // IRQ case deliberately requests stop while a real long-latency backend owner exists.
        if (p.irq && !requested && d.get_io$$stallMulDiv()) { requested = true; ++requestNumber; }
        if (stoppedCycles >= 6 && !released) { released = true; ++cov.restarts; }
        const bool halt = requested && !released;
        const bool fv = fetch && fetch->due <= cycle, dv = data && data->due <= cycle;
        const bool ir = cycle % 9 >= 3;
        const bool dr = cycle % 11 >= 4;
        d.set_io$$quiesceRequest(halt);
        d.set_io$$softwareIrq(irqAsserted && !irqServiced);
        d.set_io$$instructionRequest$$ready(ir);
        d.set_io$$instructionResponse$$valid(fv);
        d.set_io$$instructionResponse$$bits$$instruction(fetch ? fetch->data : 0x13);
        d.set_io$$instructionResponse$$bits$$error(0); d.set_io$$instructionResponse$$bits$$pageFault(0);
        d.set_io$$instructionResponse$$bits$$compressed(0); d.set_io$$instructionResponse$$bits$$secondHalfFault(0);
        d.set_io$$dataRequest$$ready(dr);
        d.set_io$$dataResponse$$valid(dv); d.set_io$$dataResponse$$bits$$data(data ? data->data : 0);
        d.set_io$$dataResponse$$bits$$error(0); d.set_io$$dataResponse$$bits$$pageFault(0);
        d.set_io$$dataResponse$$bits$$fetchSpan(0);
        d.set_io$$fenceReady(fenceWait >= 13);
        d.step();
        if (trace) std::cout << "TRACE cycle=" << cycle << " halt=" << halt
            << " stopped=" << unsigned(d.get_io$$architecturalStopped()) << " stages=" << unsigned(d.get_io$$stageValid())
            << " fetch=" << unsigned(d.get_io$$instructionRequest$$valid()) << ":" << std::hex
            << d.get_io$$instructionRequest$$bits() << " retire=" << unsigned(d.get_io$$retire$$valid()) << ":"
            << d.get_io$$retire$$bits$$pc() << ":" << d.get_io$$retire$$bits$$nextPc()
            << " trap=" << unsigned(d.get_io$$trapTaken()) << ":" << d.get_io$$trapPc() << ":" << d.get_io$$trapCause() << std::dec << '\n';
        require(d.get_io$$instructions() == successful, "independent successful-retirement count");
        if (halt) {
            cov.pendingFetch += bool(fetch); cov.pendingData += bool(data);
            cov.mulDiv += bool(d.get_io$$stallMulDiv()); cov.fence += bool(d.get_io$$fenceValid());
            cov.branch += bool(d.get_io$$branchMispredict());
        }
        if (d.get_io$$architecturalStopped()) {
            require(halt, "stopped asserted without held request");
            require(!d.get_io$$stageValid() && !d.get_io$$retire$$valid() && !d.get_io$$trapTaken() &&
                !d.get_io$$instructionRequest$$valid() && !d.get_io$$dataRequest$$valid(),
                "architecturalStopped acknowledged a live execution/request owner");
            require(!fetch && !data && !heldFetch && !heldData,
                "architecturalStopped acknowledged an unconsumed test transport owner");
            ++stoppedCycles; ++cov.stopped;
            if (p.irq) irqAsserted = true;
        }
        if (d.get_io$$fenceValid()) {
            ++fenceWait;
            if (fenceWait <= 13 || !d.get_io$$fenceDrained())
                require(!d.get_io$$retire$$valid(), "FENCE.I retired before real delayed completion/drain");
        }
        if (d.get_io$$trapTaken()) {
            if (d.get_io$$trapCause() >> 63) {
                require(p.irq && irqAsserted && !halt && released && !irqServiced,
                    "IRQ committed during stop or without pending interrupt");
                require(!p.expected.empty(), "interrupt arrived after terminal program");
                require(d.get_io$$trapCause() == (uint64_t(1) << 63 | 3) &&
                    d.get_io$$trapPc() == p.expected.front().pc, "IRQ precise architectural resume PC/cause");
                const uint64_t resume = p.expected.front().pc;
                p.expected.push_front({HANDLER, resume, 0, 0, 0, 0x30200073, 0, false});
                irqServiced = true; ++irqCount; ++cov.irq;
            } else {
                require(!p.expected.empty() && p.expected.front().trap && d.get_io$$retire$$valid(),
                    "unexpected or unowned synchronous trap");
                require(d.get_io$$trapPc() == p.expected.front().pc && d.get_io$$trapCause() == 11,
                    "independent synchronous trap PC/cause");
                if (halt) ++cov.trap;
            }
        }
        if (d.get_io$$retire$$valid()) {
            Entry e = p.expected.empty() ? Entry{p.tail, p.tail, 0, 0, 0, 0x0000006f, 0, false} : p.expected.front();
            require(d.get_io$$retire$$bits$$pc() == e.pc && d.get_io$$retire$$bits$$instruction() == e.ins,
                "independent retirement PC/instruction oracle expected_pc=" + std::to_string(e.pc) +
                " actual_pc=" + std::to_string(d.get_io$$retire$$bits$$pc()) +
                " expected_ins=" + std::to_string(e.ins) +
                " actual_ins=" + std::to_string(d.get_io$$retire$$bits$$instruction()));
            require(bool(d.get_io$$retire$$bits$$trap()) == e.trap &&
                bool(d.get_io$$retire$$bits$$writesRd()) == (e.rd != 0 && !e.trap), "retirement trap/write authority");
            if (e.trap) require(d.get_io$$retire$$bits$$cause() == e.cause &&
                d.get_io$$retire$$bits$$tval() == e.tval, "independent synchronous exception oracle");
            else {
                uint64_t want = e.value;
                if (negative && e.rd == 3) want ^= 1;
                if (e.rd) require(d.get_io$$retire$$bits$$rd() == e.rd &&
                    d.get_io$$retire$$bits$$data() == want, "independent register-result oracle");
                require(d.get_io$$retire$$bits$$nextPc() == e.next, "independent retirement next-PC oracle");
                ++successful;
            }
            if (e.ins == 0x0000100f) { require(fenceWait >= 13, "missing delayed FENCE.I hold"); ++fenceRetired; }
            if (halt && e.ins == 0x30200073) ++cov.mret;
            if (!p.expected.empty()) p.expected.pop_front();
            ++retired;
            if (released) afterResume = true;
        }
        if (fv && d.get_io$$instructionResponse$$ready()) fetch.reset();
        if (dv && d.get_io$$dataResponse$$ready()) { data.reset(); ++replied; }
        if (heldFetch) require(d.get_io$$instructionRequest$$valid() &&
            d.get_io$$instructionRequest$$bits() == *heldFetch, "stalled fetch offer withdrawn/changed by quiesce");
        heldFetch.reset();
        if (d.get_io$$instructionRequest$$valid() && !ir) {
            heldFetch = d.get_io$$instructionRequest$$bits();
            if (halt) ++cov.heldOffer;
        }
        if (d.get_io$$instructionRequest$$valid() && ir) {
            require(!fetch, "duplicate accepted fetch owner");
            const uint64_t pc = d.get_io$$instructionRequest$$bits();
            auto found = p.code.find(pc);
            const uint32_t ins = found == p.code.end() ? 0x00000013 : found->second;
            fetch = Pending{cycle + 2 + unsigned((pc >> 2) % 5), ins};
        }
        MemoryOffer offer{d.get_io$$dataRequest$$bits$$address(), d.get_io$$dataRequest$$bits$$data(),
            unsigned(d.get_io$$dataRequest$$bits$$size()), unsigned(d.get_io$$dataRequest$$bits$$mask()),
            unsigned(d.get_io$$dataRequest$$bits$$atomicOperation()), bool(d.get_io$$dataRequest$$bits$$write()),
            bool(d.get_io$$dataRequest$$bits$$atomic())};
        if (heldData) require(d.get_io$$dataRequest$$valid() && offer == *heldData,
            "stalled data request changed/withdrawn during quiesce");
        heldData.reset();
        if (d.get_io$$dataRequest$$valid() && !dr) heldData = offer;
        if (d.get_io$$dataRequest$$valid() && dr) {
            require(!p.irq && accepted < 3 && !data, "duplicate, wrong-path, or unowned memory side effect");
            require(offer.address == DATA && offer.size == 3 && offer.mask == 255,
                "independent memory address/width/mask oracle");
            const uint64_t old = memory;
            if (accepted == 0) {
                require(offer.write && !offer.atomic && offer.data == 63, "independent exactly-once store oracle");
                memory = 63;
            } else if (accepted == 1) {
                require(offer.write && offer.atomic && offer.operation == 0 && offer.data == 7,
                    "independent exactly-once AMOADD oracle");
                memory += 7;
            } else require(!offer.write && !offer.atomic && memory == 70, "independent load-after-AMO oracle");
            data = Pending{cycle + 17, old}; ++accepted;
        }
        const bool programDone = p.expected.empty();
        if (programDone && (stopAt < 0 && !p.irq || requested && released && afterResume && requestNumber == stopCount)) {
            require(p.irq ? irqCount == 1 : accepted == 3 && replied == 3 && memory == 70 && fenceRetired == 1,
                "final memory/IRQ/FENCE exactly-once totals");
            finished = true; break;
        }
    }
    require(finished, "finite retirement/drain/resume sequence timed out");
    if (stopAt >= 0 || p.irq) require(cov.stopped >= 6 * stopCount && cov.restarts == stopCount && released && afterResume,
        "four-phase request/stop/hold/release/resumed-retirement was not exercised");
    return cov;
}
int main(int argc, char **argv) try {
    std::cout << std::unitbuf;
    for (int i = 1; i < argc; ++i) if (std::string(argv[i]) == "--trace") trace = true;
    if (argc >= 2 && std::string(argv[1]).starts_with("--stop=")) {
        run(arithmetic(), std::stoi(std::string(argv[1]).substr(7))); return 0;
    }
    if (argc >= 2 && std::string(argv[1]) == "--repeated") {
        auto repeated = run(arithmetic(), 0, false, 4);
        std::cout << "I1_REPEATED_QUIESCE_PASS restarts=" << repeated.restarts << '\n'; return 0;
    }
    const bool negative = argc == 2 && std::string(argv[1]) == "--wrong-retire";
    const auto baseline = run(arithmetic(), -1, negative);
    Coverage total; total.add(baseline);
    // Every pre-completion edge of the unhalted trace is a separate deterministic stop experiment.
    // Later timing may change freely; only ISA outcomes and real ownership are the oracle.
    for (unsigned offset = 0; offset < baseline.cycles; ++offset) total.add(run(arithmetic(), offset));
    total.add(run(interruptProgram(), -1));
    total.add(run(arithmetic(), 0, false, 4));
    check(total.stopped && total.heldOffer && total.pendingFetch && total.pendingData && total.mulDiv &&
        total.fence && total.branch && total.trap && total.mret && total.irq,
        "directed stop coverage missing fetch/data/MDU/FENCE/branch/trap/MRET/IRQ intersection");
    std::cout << "I1_EXTERNAL_QUIESCE_PASS cases=" << total.cases << " baseline_cycles=" << baseline.cycles
        << " stopped=" << total.stopped << " restarts=" << total.restarts << " fetch_offer=" << total.heldOffer << " fetch_pending=" << total.pendingFetch
        << " data_pending=" << total.pendingData << " muldiv=" << total.mulDiv << " fence=" << total.fence
        << " branch=" << total.branch << " trap=" << total.trap << " mret=" << total.mret << " irq=" << total.irq << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << "FAIL: " << e.what() << '\n'; return 1; }
