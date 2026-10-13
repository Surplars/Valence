// Authored CPU/DMA requests and an independent byte/owner oracle drive the
// real cache + mixed home + posted owner + AXI fixture. No internal state writes.
#ifndef PROBE_LOOKUP_ON
#error "explicit PROBE_LOOKUP_ON=0|1 is required"
#endif
#define PROBE_LOOKUP_FIXTURE
#define CACHE_HOME_EMBED
#define MIXED_MODEL 1
#define MIXED_RTL 1
#include "coherent_cache_home.cpp"
#include <array>

namespace {
constexpr uint64_t stride = CACHE_LINES / 2 * 64ULL;
struct Probe {
    uint64_t address, cycle;
    unsigned source, beats = 0;
    std::array<uint64_t, 8> words{};
    bool first = true;
};
struct Gate {
    Test t;
    std::optional<Probe> pending;
    std::optional<std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t>> heldC;
    uint64_t firstLatency = 0, replies = 0, acceptedInProbe = 0, lookupBlocked = 0;
    bool exactLatency = false, expectedDirty = false, poison = false, offeredCpu = false;
    unsigned postedAccepted = 0, postedAcked = 0, postedAcquired = 0, postedInstalled = 0;
    unsigned postedDrained = 0, postedReleased = 0, postedAttached = 0, postedSent = 0, postedCompleted = 0;
    unsigned postedCancelled = 0, postedSlot = 0, postedMshr = 0, postedWay = 0, postedSet = 0, postedWbSlot = 0;
    uint64_t postedGeneration = 0, postedAddress = 0, postedToken = 0, postedVictim = 0;
    bool postedVictimValid = false, postedVictimDirty = false;
    Gate() {
        t.readyAlways = true;
        // Keep speculation inactive while retaining the actual posted/PF RTL.
        t.d.set_io$$prefetchPrivilege(1); t.d.set_io$$prefetchPmpCfg(0x18);
        t.beforeStep = [&] { offeredCpu = bool(t.cpuRequest); };
        t.observer = [&] { observe(); };
        t.tick();
    }
    void observe() {
        auto& d = t.d;
        if (d.get_io$$probeFire()) {
            check(!pending, "second B accepted while original probe owns C");
            Probe p{uint64_t(d.get_io$$probeAddress()), t.cycles, unsigned(d.get_io$$probeTest$$source())};
            for (unsigned w = 0; w < 8; ++w) p.words[w] = t.architectural.at(p.address + 8*w);
            pending = p;
        }
        if (pending && offeredCpu) {
            const auto age = t.cycles - pending->cycle;
            if (age == 0 || (PROBE_LOOKUP_ON && age == 1))
                check(!d.get_io$$cpu$$request$$ready(), "CPU accepted during exclusive probe acceptance/lookup");
            if (PROBE_LOOKUP_ON && age == 1) ++lookupBlocked;
            if (age > 0 && d.get_io$$cpu$$request$$ready()) ++acceptedInProbe;
        }
#define C(x) d.get_io$$probeTest$$c##x()
        const auto c = std::make_tuple(unsigned(C(Opcode)), unsigned(C(Param)), unsigned(C(Size)),
            unsigned(C(Source)), uint64_t(C(Address)), uint64_t(C(Data)));
        if (heldC) check(C(Valid) && c == *heldC, "held C payload/identity changed");
        heldC = C(Valid) && !C(Ready) ? std::optional{c} : std::nullopt;
        if (C(Valid) && C(Opcode) < 6) {
            check(pending.has_value(), "ProbeAck offered without accepted B");
            auto& p = *pending;
            check(C(Address) == p.address && C(Source) == p.source && C(Size) == 6,
                "ProbeAck lost full address/source owner");
            if (p.first) {
                firstLatency = t.cycles - p.cycle; p.first = false;
                if (exactLatency) check(firstLatency == 2 + unsigned(PROBE_LOOKUP_ON && expectedDirty),
                    "real home probe B-to-first-C latency differs");
            }
            if (exactLatency) check(C(Opcode) == (expectedDirty ? 5 : 4) && C(Param) == 1,
                "clean/dirty resident probe reply control differs");
            if (C(Opcode) == 5) check(C(Data) == (p.words.at(p.beats) ^ uint64_t(poison)),
                "probe independent byte snapshot mismatch");
            if (C(Ready)) {
                if (C(Opcode) == 4 || ++p.beats == 8) { pending.reset(); ++replies; }
            }
        }
#undef C
#define P(x) d.get_io$$probeTest$$posted$$##x()
        if (P(accepted$$valid)) {
            check(P(accepted$$bits$$newLine) && postedAccepted == 0, "unexpected second posted owner");
            check(P(accepted$$bits$$member$$token$$tag) == postedToken &&
                P(accepted$$bits$$member$$token$$index) == (postedToken & 15), "posted accepted wrong token");
            check(P(accepted$$bits$$member$$context$$owner$$generation) == 0 &&
                P(accepted$$bits$$member$$context$$lineAddress) == postedAddress,
                "posted generation/full address differs from authored store");
            postedSlot = P(accepted$$bits$$member$$context$$owner$$slot);
            postedGeneration = P(accepted$$bits$$member$$context$$owner$$generation);
            postedMshr = P(accepted$$bits$$reservation$$mshr);
            postedWay = P(accepted$$bits$$reservation$$way); postedSet = P(accepted$$bits$$reservation$$set);
            postedVictim = P(accepted$$bits$$reservation$$victimAddress);
            postedVictimValid = P(accepted$$bits$$reservation$$victimValid);
            postedVictimDirty = P(accepted$$bits$$reservation$$victimDirty);
            ++postedAccepted;
        }
#define PE_INNER(event, field) d.get_io$$probeTest$$posted$$##event##$$##field()
#define PE(event, field) PE_INNER(event, field)
#define CHECK_CONTEXT(event) \
        check(postedAccepted && PE(event, bits$$context$$owner$$slot) == postedSlot && \
            PE(event, bits$$context$$owner$$generation) == postedGeneration && \
            PE(event, bits$$context$$epoch) == 1 && PE(event, bits$$context$$lineAddress) == postedAddress, \
            "posted event changed retained context");
#define CHECK_LINE(event, count) \
        if (PE(event, valid)) { CHECK_CONTEXT(event); \
            check(PE(event, bits$$reservation$$mshr) == postedMshr && \
                PE(event, bits$$reservation$$way) == postedWay && PE(event, bits$$reservation$$set) == postedSet && \
                PE(event, bits$$reservation$$victimValid) == postedVictimValid && \
                PE(event, bits$$reservation$$victimDirty) == postedVictimDirty && \
                (!postedVictimValid || PE(event, bits$$reservation$$victimAddress) == postedVictim), \
                "posted event changed retained reservation"); check(++count == 1, "duplicate posted line event"); }
        CHECK_LINE(acquired, postedAcquired)
        CHECK_LINE(installed, postedInstalled)
        CHECK_LINE(released, postedReleased)
        CHECK_LINE(attached, postedAttached)
        CHECK_LINE(sent, postedSent)
        CHECK_LINE(completed, postedCompleted)
        CHECK_LINE(cancelled, postedCancelled)
        if (P(attached$$valid)) postedWbSlot = P(attached$$bits$$ticket$$slot);
#define CHECK_WB(event) \
        if (PE(event, valid)) check(PE(event, bits$$ticket$$slot) == postedWbSlot && \
            PE(event, bits$$ticket$$owner$$slot) == postedSlot && \
            PE(event, bits$$ticket$$owner$$generation) == postedGeneration, "posted WB changed ticket lineage");
        CHECK_WB(attached)
        CHECK_WB(sent)
        CHECK_WB(completed)
#undef CHECK_WB
#define CHECK_MEMBER(event, count) \
        if (PE(event, valid)) { CHECK_CONTEXT(event); \
            check(PE(event, bits$$token$$tag) == postedToken, "posted member changed token"); \
            check(++count == 1, "duplicate posted member event"); }
        CHECK_MEMBER(acknowledged, postedAcked)
        CHECK_MEMBER(drained, postedDrained)
        check(!P(failed) && !P(fallback$$valid), "unexpected posted failure/fallback");
#undef CHECK_MEMBER
#undef CHECK_LINE
#undef CHECK_CONTEXT
#undef PE
#undef PE_INNER
#undef P
        check(postedCompleted <= postedSent && postedSent <= postedAttached,
            "posted writeback completed/sent before its retained predecessor");
        check(!(postedAttached && postedCancelled), "posted victim both attached and cancelled");
    }
    void ticks(unsigned n) { while (n--) t.tick(); }
    void finish(const char* name) {
        t.d.set_io$$holdCoherentC(0); t.d.set_io$$holdCoherentD(0); t.d.set_io$$holdReleaseAck(0);
        t.blockCpu = false; t.drainCpu(); t.drainDma(); t.flush();
        check(!pending && !heldC && t.cpuAccepted == t.cpuReturned && t.dmaAccepted == t.dmaReturned,
            "final CPU/DMA/probe ownership failed to drain");
        std::cout << "PROBE_LOOKUP_HOME_CASE name=" << name << " on=" << PROBE_LOOKUP_ON
            << " cycles=" << t.cycles << " cpu=" << t.cpuAccepted << " probes=" << t.probes
            << " first_c_latency=" << firstLatency << " dirty_beats=" << t.dirtyProbeBeats
            << " cpu_during_probe=" << acceptedInProbe << " lookup_blocked=" << lookupBlocked
            << " posted=" << postedAccepted << " posted_installed=" << postedInstalled
            << " posted_wb_attached=" << postedAttached << " posted_wb_sent=" << postedSent
            << " posted_wb_completed=" << postedCompleted
            << " full_backing_oracle=1\n";
    }
};

void latencyAndDemand(bool dirty) {
    Gate g; g.expectedDirty = dirty; g.exactLatency = true;
    g.t.cpu({base, dirty, 0x76543210abcdef01ULL}); g.t.cpu({base + 64});
    const auto idleStart = g.t.cycles;
    for (unsigned n = 0; n < 16; ++n) g.t.cpu({base + 64 + 8*(n%8)}, false);
    g.t.drainCpu(); check(g.t.cycles - idleStart == 17, "idle hit II/latency changed");
    g.t.dma({base}, false);
    const auto busyStart = g.t.cycles;
    for (unsigned n = 0; n < 16; ++n) g.t.cpu({base + 64 + 8*(n%8)}, false);
    g.t.drainCpu();
    std::cout << "PROBE_LOOKUP_DEMAND dirty=" << dirty << " on=" << PROBE_LOOKUP_ON
        << " idle_hits_cycles=17 probe_hits_cycles=" << g.t.cycles - busyStart << '\n';
    g.t.drainDma(); check(g.replies == 1 && g.acceptedInProbe > 0, "probe serialized disjoint resident reads");
    if (PROBE_LOOKUP_ON) check(g.lookupBlocked == 1, "continuous demand did not witness lookup exclusion");
    g.finish(dirty ? "dirty_latency_demand" : "clean_latency_demand");
}
void heldReplyAndC(bool poison) {
    Gate g; g.poison = poison;
    for (unsigned w = 0; w < 8; ++w) g.t.cpu({base + w*8, true, 0x718293a4b5c6d7e8ULL ^ w});
    g.t.blockCpu = true; g.t.cpu({base}, false);
    g.t.until([&] { return g.t.d.get_io$$cpu$$response$$valid(); }, "held CPU setup");
    g.t.d.set_io$$holdCoherentC(1); g.t.dma({base}, false);
    g.t.until([&] { return g.pending && g.t.d.get_io$$probeTest$$cValid(); }, "first probe C offer");
    g.ticks(3); g.t.d.set_io$$holdCoherentC(0);
    for (unsigned beat : {3U, 7U}) {
        g.t.until([&] { return g.pending && g.pending->beats == beat; }, "middle/last C stall setup");
        g.t.d.set_io$$holdCoherentC(1); g.ticks(3); g.t.d.set_io$$holdCoherentC(0);
    }
    g.t.drainDma(); check(g.t.cpuReturned + 1 == g.t.cpuAccepted && g.t.dirtyProbeBeats == 8,
        "dirty probe waited for CPU reply or lost data");
    g.finish("held_cpu_first_middle_last_c");
}
void releaseRace() {
    Gate g; g.t.cpu({base, true, 0xfedcba9876543210ULL});
    g.t.cpu({base + stride, true, 0x0123456789abcdefULL});
    g.t.dma({base}, false); g.t.cpu({base + 2*stride}, false);
    g.t.drainDma(); g.t.drainCpu();
    check(g.t.blockedProbeRelease > 0 && g.t.resolvedVictimProbes == 1,
        "same-victim B/ReleaseAck race witness missing");
    g.finish("same_victim_release_ack");
}
void flushCompetition() {
    Gate g;
    for (unsigned line = 0; line < CACHE_LINES; ++line)
        g.t.cpu({base + line*64ULL, true, 0x1234000000000000ULL ^ line});
    g.t.d.set_io$$holdCoherentC(1); g.t.d.set_io$$flushRequest(1);
    g.t.dma({base + (CACHE_LINES/4)*64ULL}, false);
    g.t.until([&] { return g.t.probes > 0; }, "probe competing with flush never accepted");
    check(!g.t.d.get_io$$flushDone(), "flush finished before held C");
    g.ticks(3); g.t.d.set_io$$holdCoherentC(0);
    g.t.until([&] { return g.t.d.get_io$$flushDone(); }, "probe/flush failed to drain");
    g.t.drainDma(); check(g.t.dirtyProbeBeats == 8, "flush competition lacked dirty probe");
    g.finish("flush_probe_collision");
}
void postedHeldDuringLookup() {
    Gate g; g.t.cpu({base, true, 0x1122334455667788ULL});
    // A dirty authored victim exercises the same posted owner across its
    // attach/sent/completed WB duties after the held lookup admission.
    g.t.cpu({base + 128, true, 0x0123456789abcdefULL});
    g.t.cpu({base + 128 + stride, true, 0xfedcba9876543210ULL});
    g.t.d.set_io$$holdCoherentC(1); g.t.dma({base}, false);
    g.t.until([&] { return bool(g.pending); }, "posted/lookup B acceptance setup");
    g.postedAddress = base + 128 + 2*stride; g.postedToken = 0x21;
    g.t.d.set_io$$adoption$$postedProofValid(1); g.t.d.set_io$$adoption$$postedToken(g.postedToken);
    g.t.cpuRequest = Request{g.postedAddress, true, 0x88aabbccddeeff11ULL};
    g.ticks(4);
    check(g.t.cpuRequest && !g.postedAccepted, "held probe admitted posted proof early");
    g.t.d.set_io$$holdCoherentC(0);
    g.t.until([&] { return !g.t.cpuRequest; }, "posted proof did not resume after probe");
    g.t.d.set_io$$adoption$$postedProofValid(0); g.t.d.set_io$$adoption$$postedSeal(1);
    g.t.drainCpu(); g.t.drainDma();
    g.t.until([&] { return !g.t.d.get_io$$adoption$$postedBusy(); }, "posted owner failed to drain");
    check(g.postedAccepted == 1 && g.postedAcked == 1 && g.postedAcquired == 1 && g.postedInstalled == 1 &&
        g.postedDrained == 1 && g.postedReleased == 1 && g.postedAttached == 1 &&
        g.postedSent == 1 && g.postedCompleted == 1 && !g.postedCancelled &&
        g.postedVictimValid && g.postedVictimDirty && g.postedVictim == base + 128,
        "posted owner/victim/WB event count mismatch");
    g.t.d.set_io$$adoption$$postedEndEpisode(1); g.t.tick(); g.t.d.set_io$$adoption$$postedEndEpisode(0);
    g.t.d.set_io$$adoption$$postedSeal(0);
    g.t.dma({g.postedAddress}); check(g.t.dirtyProbeBeats == 16, "posted installed bytes were not probed");
    g.finish("posted_held_lookup_and_install");
}
}
int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--inject-probe-byte") {
            heldReplyAndC(true); throw std::runtime_error("probe byte negative failed to trigger");
        }
        latencyAndDemand(false); latencyAndDemand(true); heldReplyAndC(false);
        releaseRace(); flushCompetition(); postedHeldDuringLookup();
        std::cout << "PROBE_LOOKUP_HOME_PASS on=" << PROBE_LOOKUP_ON << " cases=6 executing_cpu=0 timing_unmeasured=1\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << "PROBE_LOOKUP_HOME_FAIL " << e.what() << '\n'; return 1; }
}
