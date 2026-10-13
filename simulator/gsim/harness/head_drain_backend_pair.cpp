#include "HeadDrainBackendPairGsim.h"
#include "head_drain_oracle.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void require(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
struct Offer {
    bool valid = false;
    uint32_t original = 0x13, expanded = 0x13;
    bool system = false, fault = false, pageFault = false;
    unsigned rs1 = 0, rd = 0;
    bool writesRd = false, memory = false;
    uint64_t immediate = 0;
};
struct Token { unsigned index = 0; uint64_t tag = 0; bool valid = false; };

// No generated RTL predicates or DUT definitions are included by this host.
static bool classification(const Offer& o) {
    return head_drain_oracle::catalogs()[3].drain(o.original, o.expanded);
}
static Offer system(uint32_t instruction) {
    Offer o; o.valid = true; o.original = instruction; o.expanded = instruction; o.system = true; return o;
}
static Offer nop() { Offer o; o.valid = true; return o; }

class Test {
public:
    SHeadDrainBackendPairGsim d;
    std::array<bool, 16> known{}, expected{};
    std::array<uint64_t, 16> tags{};
    bool commit = false, quiet = false, fence = true;
    unsigned cycles = 0, accepted = 0, dual = 0, killed = 0, commits = 0, checked = 0;
    unsigned staleMasked = 0, reuse = 0, wraps = 0, faults = 0, starts = 0;
    unsigned retireAllocateEdges = 0;
    unsigned preparations = 0, lsuStarts = 0, fenceFlushes = 0;
    unsigned previousHead = 0;
    std::string mutation;
    bool mutated = false;

    explicit Test(std::string m): mutation(std::move(m)) {}
    void drive(unsigned lane, const Offer& o) {
#define LANE(n) case n: \
        d.set_io$$offer##n##$$valid(o.valid); \
        d.set_io$$offer##n##$$original(o.original); d.set_io$$offer##n##$$expanded(o.expanded); \
        d.set_io$$offer##n##$$system(o.system); d.set_io$$offer##n##$$fault(o.fault); \
        d.set_io$$offer##n##$$pageFault(o.pageFault); d.set_io$$offer##n##$$rs1(o.rs1); \
        d.set_io$$offer##n##$$rd(o.rd); d.set_io$$offer##n##$$writesRd(o.writesRd); \
        d.set_io$$offer##n##$$memory(o.memory); d.set_io$$offer##n##$$immediate(o.immediate); \
        d.set_io$$offer##n##$$expectedClass(classification(o)); break
        switch (lane) { LANE(0); LANE(1); default: throw std::runtime_error("bad lane"); }
#undef LANE
    }
    Token renamed(unsigned lane) {
#define LANE(n) case n: return {unsigned(d.get_io$$renamed##n##$$bits$$index()), \
        d.get_io$$renamed##n##$$bits$$tag(), bool(d.get_io$$renamed##n##$$valid())}
        switch (lane) { LANE(0); LANE(1); default: throw std::runtime_error("bad lane"); }
#undef LANE
    }
    std::array<Token, 2> tick(Offer a = {}, Offer b = {}) {
        drive(0, a); drive(1, b);
        d.set_io$$pc(0x80000000ULL + 8ULL * cycles);
        d.set_io$$commitEnable(commit); d.set_io$$fetchQuiescent(quiet); d.set_io$$fenceReady(fence);
        // This exact registered-redirect profile has no external recovery producer.
        d.set_io$$recover$$valid(false); d.set_io$$recover$$bits$$token$$index(0);
        d.set_io$$recover$$bits$$token$$tag(0); d.set_io$$recover$$bits$$inclusive(false);
        d.step(); ++cycles;
        const unsigned owned = unsigned(d.get_io$$liveMask()) & unsigned(d.get_io$$pendingMask());
        unsigned saved = unsigned(d.get_io$$savedMask());
        if (owned && mutation == "--mutate-observed-class" && !mutated) {
            saved ^= owned & (~owned + 1U); mutated = true;
            std::cerr << "ACTUAL_CORRUPTION count=1 observed=savedMask\n";
        }
        for (unsigned row = 0; row < 16; ++row) if (owned & (1U << row)) {
            require(known[row], "HEAD_DRAIN_OWNER_ORACLE: live pending row was never accepted");
            require(bool(saved & (1U << row)) == expected[row], "HEAD_DRAIN_ROW_ORACLE: saved immutable class");
            ++checked;
        }
        const unsigned head = unsigned(d.get_io$$head());
        if (head < previousHead && d.get_io$$committed()) ++wraps;
        previousHead = head;
        commits += unsigned(d.get_io$$committed());
        starts += unsigned(d.get_io$$systemStart());
        preparations += unsigned(d.get_io$$memoryPrepared());
        lsuStarts += unsigned(d.get_io$$lsuStart());
        fenceFlushes += unsigned(d.get_io$$fenceFlush());
        const std::array<Token, 2> tokens{renamed(0), renamed(1)};
        if (tokens[0].valid && tokens[1].valid) ++dual;
        if (d.get_io$$committed() && (tokens[0].valid || tokens[1].valid)) ++retireAllocateEdges;
        const std::array<Offer, 2> offers{a, b};
        for (unsigned lane = 0; lane < 2; ++lane) if (tokens[lane].valid) {
            const auto& t = tokens[lane];
            if (known[t.index] && tags[t.index] != t.tag) ++reuse;
            known[t.index] = true; tags[t.index] = t.tag; expected[t.index] = classification(offers[lane]);
            ++accepted;
        }
        return tokens;
    }
    void reset() {
        commit = false; quiet = false; fence = true;
        known.fill(false); expected.fill(false); tags.fill(0); previousHead = 0;
        drive(0, {}); drive(1, {}); d.set_io$$recover$$valid(false);
        d.set_io$$commitEnable(false); d.set_io$$fetchQuiescent(false); d.set_io$$fenceReady(true);
        d.set_io$$pc(0x80000000); d.set_io$$recover$$bits$$token$$index(0);
        d.set_io$$recover$$bits$$token$$tag(0); d.set_io$$recover$$bits$$inclusive(false);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0); tick();
    }
    std::array<Token, 2> allocate(Offer a, Offer b = {}) {
        for (unsigned cycle = 0; cycle < 20; ++cycle) {
            const auto t = tick(a, b);
            if (t[0].valid) {
                require(!b.valid || t[1].valid, "HEAD_DRAIN_DUAL_ACCEPT: directed dual offer was split");
                tick(); return t;
            }
        }
        throw std::runtime_error("HEAD_DRAIN_ALLOCATE: no accepted rename");
    }
    void drained() {
        for (unsigned cycle = 0; cycle < 80; ++cycle) {
            tick(); if (!d.get_io$$occupancy() && !d.get_io$$recovering()) return;
        }
        throw std::runtime_error("HEAD_DRAIN_RETIRE: no bounded drain");
    }
};

int main(int argc, char** argv) { try {
    Test t(argc > 1 ? argv[1] : "");
    // The exhaustive catalog is in the small decoder test. These cases exercise
    // real accepted allocation, gate timing, system execution and row lifecycle.
    const std::vector<uint32_t> instructions{
        0x3a001073, 0x3a201073, 0x3af01073, 0x3b001073, 0x3bf01073, 0x3c001073,
        0x3b004073, 0x18001073, 0x18002073, 0x1800a073, 0x18005073, 0x18006073,
        0x1800e073, 0x18004073, 0x1800c073, 0x12000073, 0x13f08073, 0x120000f3,
        0x30200073, 0x10200073, 0x302000f3, 0x0000100f, 0xfff0108f, 0x0000000f,
        0x00000053, 0x00100073, 0x00000013
    };
    for (uint32_t word : instructions) {
        t.reset(); auto offer = system(word); t.allocate(offer);
        const bool wanted = classification(offer);
        bool observed = bool(t.d.get_io$$pauseFetch());
        if (wanted && t.mutation == "--mutate-pause-gate" && !t.mutated) {
            observed = !observed; t.mutated = true;
            std::cerr << "ACTUAL_CORRUPTION count=1 observed=pauseFetch\n";
        }
        require(observed == wanted, "HEAD_DRAIN_PAUSE_ORACLE: pending head class");
        require(!t.d.get_io$$systemStart(), "HEAD_DRAIN_COMMIT_GATE: disabled commit launched system");
        t.commit = true; t.tick();
        if (wanted) require(!t.d.get_io$$systemStart(), "HEAD_DRAIN_QUIESCENT_GATE: undrained fetch launched system");
        // Reset separates raw classification probes; internal fault recovery is exercised below.
    }
    // Original/expanded selection, then system=false suppresses a saved true bit.
    for (bool systemFlag : {false, true}) {
        t.reset(); Offer compressed = system(0x0001); compressed.expanded = 0x30200073;
        compressed.system = systemFlag; t.allocate(compressed);
        require(bool(t.d.get_io$$pauseFetch()) == systemFlag, "HEAD_DRAIN_COMPRESSED: original/expanded or system gate");
    }
    // Both accepted rename ports store their own immutable bit and token.
    t.reset(); auto first = system(0x30200073); auto second = system(0x00000053);
    auto pair = t.allocate(first, second);
    require(pair[0].index != pair[1].index, "HEAD_DRAIN_DUAL_ACCEPT: two rows required");
    require((t.d.get_io$$savedMask() & (1U << pair[0].index)) &&
        !(t.d.get_io$$savedMask() & (1U << pair[1].index)), "HEAD_DRAIN_DUAL_CLASS: lane association");
    // A held ready system plus younger load activates the staged-address cone.
    t.reset(); Offer load = nop(); load.memory = true; load.immediate = 0x80200000; load.rd = 1; load.writesRd = true;
    const unsigned beforePreparation = t.preparations;
    pair = t.allocate(system(0x0000100f), load); for (unsigned i = 0; i < 6; ++i) t.tick();
    require(t.preparations > beforePreparation, "HEAD_DRAIN_MEMORY: staged-address witness missing");
    t.reset(); t.commit = true; const unsigned beforeLsu = t.lsuStarts;
    t.allocate(load); for (unsigned i = 0; i < 8; ++i) t.tick();
    require(t.lsuStarts > beforeLsu, "HEAD_DRAIN_MEMORY: actual LSU start witness missing");
    // Non-system fault payload can contain a drain-class encoding; precise trap
    // remains the old execution/retirement path and must never start a system op.
    for (bool page : {false, true}) {
        t.reset(); Offer fault = nop(); fault.original = 0x30200073; fault.expanded = 0x30200073;
        fault.fault = !page; fault.pageFault = page;
        const auto killedPair = t.allocate(fault, system(0x30200073)); t.commit = true;
        bool sawTrap = false;
        for (unsigned i = 0; i < 40; ++i) { t.tick(); sawTrap |= bool(t.d.get_io$$trap());
            require(!t.d.get_io$$systemStart(), "HEAD_DRAIN_FAULT: fault became a system launch"); }
        require(sawTrap && !t.d.get_io$$occupancy() && !t.d.get_io$$recovering(),
            "HEAD_DRAIN_FAULT: precise internal trap did not remove head and younger owner");
        require(!t.d.get_io$$headPending() && !t.d.get_io$$pauseFetch(),
            "HEAD_DRAIN_STALE_GATE: killed stale class paused fetch");
        require((t.d.get_io$$savedMask() & (1U << killedPair[0].index)) &&
            (t.d.get_io$$savedMask() & (1U << killedPair[1].index)),
            "HEAD_DRAIN_STALE_GATE: stale-positive witness was not retained");
        ++t.staleMasked; ++t.killed; ++t.faults;
        t.commit = false;
        const auto replacement = t.allocate(nop(), nop());
        for (unsigned lane = 0; lane < 2; ++lane) {
            require(replacement[lane].index == killedPair[lane].index &&
                replacement[lane].tag != killedPair[lane].tag,
                "HEAD_DRAIN_REUSE: slot did not acquire a new full token");
            require(!(t.d.get_io$$savedMask() & (1U << replacement[lane].index)),
                "HEAD_DRAIN_REUSE: accepted class was not overwritten");
        }
    }
    // Fill and retire enough real dual-lane requests to wrap/reuse every row.
    t.reset(); t.commit = true; t.quiet = true;
    for (unsigned cycle = 0; cycle < 80; ++cycle) t.tick(nop(), nop());
    t.drained();
    require(t.reuse >= 16 && t.commits >= 48 && t.retireAllocateEdges > 0,
        "HEAD_DRAIN_WRAP: insufficient full-token reuse or simultaneous retire/allocation");
    // Actual fence launch/completion, including the fetch-quiescence transition.
    t.reset(); const auto fenceToken = t.allocate(system(0x0000100f))[0]; (void)fenceToken;
    const unsigned beforeFenceStart = t.starts, beforeFenceFlush = t.fenceFlushes;
    t.commit = true; t.tick(); require(!t.d.get_io$$systemStart(), "HEAD_DRAIN_FENCE: started before fetch drain");
    t.quiet = true; t.drained();
    require(t.starts > beforeFenceStart && t.fenceFlushes > beforeFenceFlush,
        "HEAD_DRAIN_FENCE: no actual accepted start/flush in this case");
    require(t.dual > 0 && t.staleMasked > 0 && t.killed > 0 && t.checked > 0 && t.faults == 2,
        "HEAD_DRAIN_COVERAGE: required lifecycle case missing");
    if (!t.mutation.empty()) require(t.mutated, "HEAD_DRAIN_MUTATION: requested corruption was not reached");
    std::cout << "HEAD_DRAIN_BACKEND_PAIR_PASS cycles=" << t.cycles << " accepted=" << t.accepted
        << " dual=" << t.dual << " checked=" << t.checked << " staleMasked=" << t.staleMasked
        << " killed=" << t.killed << " reused=" << t.reuse << " commits=" << t.commits
        << " retireAllocateEdges=" << t.retireAllocateEdges << " faults=" << t.faults
        << " preparations=" << t.preparations << " lsuStarts=" << t.lsuStarts
        << " fenceFlushes=" << t.fenceFlushes << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; } }
