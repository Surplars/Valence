// Narrow raw-manager gate for the optional registered B lookup. Compile the
// SAME CoherentReadMshrGsim top twice, changing only its lookup flag and
// PROBE_LOOKUP_ON. Required geometry: 2 MSHRs, 2 replies, 1 WB, 16 lines,
// 2 ways, compact/banked tags, independent-demand admission.
#ifndef PROBE_LOOKUP_ON
#error "Define PROBE_LOOKUP_ON=0 or 1 to match the generated model"
#endif
#if PROBE_LOOKUP_ON != 0 && PROBE_LOOKUP_ON != 1
#error "PROBE_LOOKUP_ON must be 0 or 1"
#endif
#ifndef READ_MSHRS
#define READ_MSHRS 2
#endif
#ifndef CACHE_LINES
#define CACHE_LINES 16
#endif
#ifndef CACHE_WAYS
#define CACHE_WAYS 2
#endif
#ifndef INDEPENDENT_DEMAND_ADMISSION
#define INDEPENDENT_DEMAND_ADMISSION
#endif
#define COHERENT_READ_MSHR_EMBED
#include "coherent_read_mshr.cpp"
#include <array>

static_assert(READ_MSHRS == 2 && CACHE_LINES == 16 && CACHE_WAYS == 2,
    "probe lookup gate requires the pinned small raw geometry");
static constexpr uint64_t stride = 64ULL * CACHE_LINES / CACHE_WAYS;

struct ProbeExpectation {
    uint64_t address = 0, bCycle = 0, firstCycle = 0;
    bool present = false, dirty = false, done = false;
    unsigned beats = 0;
    std::array<uint64_t, 8> words{};
};

struct ProbeTest : Test {
    std::optional<ProbeExpectation> probeExpected;
    std::vector<uint64_t> cpuAcceptCycles;
    uint64_t rawBNoiseCycles = 0, lastEAckCycle = 0, lastReleaseAckCycle = 0;
    std::optional<uint64_t> forbiddenRelease;
    using CControl = std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t, bool>;
    std::optional<CControl> heldCControl;

    ProbeTest() {
        forceReady = true;
        beforeStep = [&](Test &) {
            // B is no longer valid after acceptance. Deliberately change BOTH
            // payload fields every cycle; expected C ownership stays fixed.
            d.set_io$$tl$$b$$bits$$source(7);
            if (probeAccepted && probeExpected && !probeExpected->done) {
                d.set_io$$tl$$b$$bits$$address((cycles & 1) ?
                    ((base + 128) | (1ULL << 40)) : base + 2 * stride + 192);
                d.set_io$$tl$$b$$bits$$source(cycles % 6);
                ++rawBNoiseCycles;
            }
        };
        afterStep = [&](Test &, const Edge &edge) { observe(edge); };
    }

    void observe(const Edge &edge) {
        if (request && d.get_io$$upstream$$request$$ready()) cpuAcceptCycles.push_back(cycles);
        if (edge.eReady && d.get_io$$tl$$e$$valid()) lastEAckCycle = cycles;
        if (edge.releaseAck && d.get_io$$tl$$d$$ready()) lastReleaseAckCycle = cycles;
        if (edge.bValid && d.get_io$$tl$$b$$ready()) {
            check(probeExpected && !probeExpected->bCycle && !probeExpected->done,
                "unowned or duplicate B acceptance");
            probeExpected->bCycle = cycles;
        }
        const bool valid = d.get_io$$tl$$c$$valid();
        const unsigned opcode = d.get_io$$tl$$c$$bits$$opcode();
        const unsigned param = d.get_io$$tl$$c$$bits$$param();
        const unsigned size = d.get_io$$tl$$c$$bits$$size();
        const unsigned source = d.get_io$$tl$$c$$bits$$source();
        const uint64_t address = d.get_io$$tl$$c$$bits$$address();
        const uint64_t data = d.get_io$$tl$$c$$bits$$data();
        const bool corrupt = d.get_io$$tl$$c$$bits$$corrupt();
        const CControl control{opcode, param, size, source, address, data, corrupt};
        if (heldCControl) check(valid && control == *heldCControl,
            "stalled C changed opcode/param/size/source/address/data/corrupt");
        heldCControl = valid && !edge.cReady ? std::optional{control} : std::nullopt;
        if (!valid) return;
        if (opcode >= 6) {
            check(!forbiddenRelease || address != *forbiddenRelease,
                "queued victim emitted a voluntary release after its probe won");
            return;
        }
        check(probeExpected && probeExpected->bCycle && !probeExpected->done,
            "ProbeAck offered before B ownership or after completion");
        auto &p = *probeExpected;
        if (!p.firstCycle) {
            p.firstCycle = cycles;
            // Protocol schedule, independent of internal state/taps: old
            // capture path is two edges; only dirty ON replies add one edge.
            const uint64_t latency = 2 + (p.dirty ? PROBE_LOOKUP_ON : 0);
            check(p.firstCycle - p.bCycle == latency,
                "B-to-first-C-valid latency differs from 2 + (dirty && ON)");
        }
        check(opcode == (p.dirty ? 5U : 4U) && param == (p.present ? 1U : 5U) &&
            size == 6 && source == 7 && address == p.address && !corrupt,
            "ProbeAck identity/permission/control mismatch");
        check(p.beats < (p.dirty ? 8U : 1U), "ProbeAck beat overflow");
        check(data == (p.dirty ? p.words[p.beats] : 0),
            "ProbeAck data differs from independently saved architectural bytes");
        if (edge.cReady && ++p.beats == (p.dirty ? 8U : 1U)) p.done = true;
    }

    void expectProbe(uint64_t address, bool present, bool dirty) {
        check(!probeExpected || probeExpected->done, "probe expectation overwritten");
        ProbeExpectation p;
        p.address = address; p.present = present; p.dirty = dirty;
        for (unsigned beat = 0; beat < 8; ++beat) {
            memory(address + 8 * beat);
            p.words[beat] = architectural.at(address + 8 * beat);
        }
        probeExpected = p;
    }

    void startProbe(uint64_t address, bool present, bool dirty) {
        check(!probing, "probe stimulus overwritten");
        expectProbe(address, present, dirty);
        probing = true; probeAccepted = probeDone = false; probeAddress = address;
    }

    void finishProbe() {
        until([&] { return probeDone; }, "raw probe completion deadlock", 2000);
        check(probeExpected && probeExpected->done, "manager/oracle probe completion mismatch");
    }

    void checkedProbe(uint64_t address, bool present, bool dirty) {
        startProbe(address, present, dirty); finishProbe();
    }

    void dirtyLine(uint64_t address, uint64_t salt) {
        for (unsigned beat = 0; beat < 8; ++beat)
            offer({address + 8 * beat, true,
                salt ^ (0x01030507090b0d0fULL * (beat + 1)), (beat & 1) ? 0xaaU : 0x55U});
    }
};

static void cleanAbsentAndAliases() {
    ProbeTest t;
    t.checkedProbe(base + 3 * stride, false, false);
    t.offer({base});
    t.checkedProbe(base, true, false);
    const auto invalidated = t.aCount;
    t.offer({base});
    check(t.aCount == invalidated + 1, "clean probe failed to invalidate its line");
    t.dirtyLine(base, 0x3141592653589793ULL);
    t.offer({base + stride});
    const auto residentAcquires = t.aCount;
    t.checkedProbe(base | (1ULL << 40), false, false);
    t.checkedProbe(base + 2 * stride, false, false);
    t.offer({base}); t.offer({base + stride});
    check(t.aCount == residentAcquires, "absent/high-PA probe invalidated a same-set resident");
    t.checkedProbe(base, true, true);
    t.offer({base + stride});
    check(t.aCount == residentAcquires, "dirty probe invalidated the opposite way");
    t.checkedProbe(base + stride, true, false);
    t.offer({base});
    check(t.aCount == residentAcquires + 1, "dirty probe failed to invalidate its line");
    check(t.rawBNoiseCycles, "saved B identity stimulus was not exercised");
}

static void heldReadAndCBackpressure() {
    ProbeTest t;
    t.dirtyLine(base, 0x8877665544332211ULL);
    t.offer({base + 64});
    const auto returned = t.returned, accepted = t.accepted;
    t.cReadyOverride = false;
    t.startProbe(base, true, true);
    t.request = Request{base + 64};
    t.tick();
    check(t.probeAccepted && t.accepted == accepted,
        "B acceptance failed or CPU read crossed asserted BVALID");
    const auto bCycle = t.probeExpected->bCycle;
    if (PROBE_LOOKUP_ON) {
        t.tick();
        check(t.request && t.accepted == accepted,
            "CPU read accepted during registered probe lookup");
    }
    t.tick();
    check(!t.request && t.accepted == accepted + 1 &&
        t.cpuAcceptCycles.back() == bCycle + 1 + PROBE_LOOKUP_ON,
        "held CPU read did not accept on dirty pCapture cycle");
    t.request = Request{base + 72};
    t.tick();
    check(!t.request && t.accepted == accepted + 2 &&
        t.cpuAcceptCycles.back() == bCycle + 2 + PROBE_LOOKUP_ON &&
        t.probeExpected->firstCycle == t.cycles && t.probeExpected->beats == 0,
        "second CPU read did not accept beside stalled first C in pSend");
    // First, middle (beat 4), and last (beat 7) each remain offered for
    // several cycles. The monitor checks every field even before C.fire.
    for (unsigned n = 0; n < 3; ++n) t.tick();
    check(t.returned == returned + 2, "CPU read replies stalled behind held C");
    t.cReadyOverride = true;
    t.until([&] { return t.probeExpected->beats == 4; }, "first four C beats stalled", 20);
    t.cReadyOverride = false;
    for (unsigned n = 0; n < 3; ++n) t.tick();
    check(t.probeExpected->beats == 4, "middle C beat consumed under backpressure");
    t.cReadyOverride = true;
    t.until([&] { return t.probeExpected->beats == 7; }, "middle C beats stalled", 20);
    t.cReadyOverride = false;
    for (unsigned n = 0; n < 3; ++n) t.tick();
    check(t.probeExpected->beats == 7 && !t.probeDone,
        "last C beat retired under backpressure");
    t.cReadyOverride = true; t.finishProbe();
    t.drain();
    const auto before = t.aCount;
    for (unsigned beat = 0; beat < 8; ++beat) t.offer({base + 8 * beat});
    check(t.aCount == before + 1, "dirty probe/refill lost line ownership");
}

static void postEAckBeforeInstall() {
    ProbeTest t;
    t.blockCpu = true;
    t.probeAfterAck = true;
    t.offer({base, true, 0xfedcba9876543210ULL, 0x5a}, false);
    t.expectProbe(base, true, true);
    t.finishProbe();
    check(t.lastEAckCycle && t.probeExpected->bCycle > t.lastEAckCycle && t.probeStalls,
        "post-E pending probe did not wait through pre-install ownership");
    check(t.returned == 0 && t.expected.size() == 1,
        "post-E probe depended on CPU response retirement");
    t.blockCpu = false; t.drain();
    t.offer({base});
    check(t.aCount == 2, "post-E probe failed to invalidate the newly installed store line");
}

static void queuedVictimAcrossLookup() {
    ProbeTest t;
    const uint64_t firstVictim = base, queuedVictim = base + 64;
    // Each pair fills both ways. Touching the second line leaves the first
    // line as the independently chosen least-recently-used dirty victim.
    t.dirtyLine(firstVictim, 0x1111222233334444ULL);
    t.dirtyLine(firstVictim + stride, 0x5555666677778888ULL);
    t.dirtyLine(queuedVictim, 0x9999aaaabbbbccccULL);
    t.dirtyLine(queuedVictim + stride, 0xddddeeeeffff0000ULL);
    t.releaseAckDelay = 100000;
    t.offer({firstVictim + 2 * stride}, false);
    t.until([&] { return t.releaseCount == 1; }, "first dirty victim did not release", 2000);
    check(t.releaseAcks.size() == 1 && t.cAddress == firstVictim,
        "first dirty release did not establish the intended occupied WB lane");
    t.offer({queuedVictim + 2 * stride}, false);
    t.tick(); t.tick();
    check(t.expected.size() == 2 && t.releaseCount == 1,
        "second dirty replacement did not queue behind the old ReleaseAck");
    t.forbiddenRelease = queuedVictim;
    t.startProbe(queuedVictim, true, true);
    // Retiring the previous WB makes the queued victim eligible on B.fire,
    // and then throughout the added lookup cycle. B must win both races.
    t.releaseAcks.front().due = t.cycles;
    t.tick();
    check(t.probeAccepted && t.lastReleaseAckCycle == t.probeExpected->bCycle,
        "queued victim B did not collide with old ReleaseAck turnover");
    t.finishProbe(); t.drain();
    check(t.releaseCount == 1 && t.aCount == 6 && t.releaseAcks.empty(),
        "probed queued victim was released redundantly or either replacement failed to refill");
    const auto before = t.aCount;
    t.offer({queuedVictim + stride}); t.offer({queuedVictim + 2 * stride});
    check(t.aCount == before, "queued-victim probe damaged surviving or replacement way");
    for (unsigned beat = 0; beat < 8; ++beat)
        check(t.backing.at(queuedVictim + 8 * beat) == t.architectural.at(queuedVictim + 8 * beat),
            "queued-victim probe lost dirty bytes");
}

static void releasedVictimWaitsForAck() {
    ProbeTest t;
    t.dirtyLine(base, 0x0123456789abcdefULL);
    t.dirtyLine(base + stride, 0x76543210fedcba98ULL);
    t.releaseAckDelay = 100000;
    t.offer({base + 2 * stride}, false);
    t.until([&] { return t.releaseCount == 1; }, "dirty ReleaseData did not finish", 2000);
    t.startProbe(base, false, false);
    for (unsigned n = 0; n < 3; ++n) t.tick();
    check(!t.probeAccepted && t.probeStalls >= 3,
        "old dirty victim probe bypassed its pending ReleaseAck");
    t.releaseAcks.front().due = t.cycles;
    t.finishProbe(); t.drain();
    check(t.probeExpected->bCycle == t.lastReleaseAckCycle + 1,
        "old dirty victim BREADY did not retain its ReleaseAck boundary");
}

int main(int argc, char **argv) {
    injectMismatch = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    try {
        cleanAbsentAndAliases();
        heldReadAndCBackpressure();
        postEAckBeforeInstall();
        queuedVictimAcrossLookup();
        releasedVictimWaitsForAck();
        std::cout << "PROBE_LOOKUP_RAW_PASS enabled=" << PROBE_LOOKUP_ON
            << " clean_absent_latency=2 dirty_latency=" << 2 + PROBE_LOOKUP_ON
            << " saved_b_identity=1 held_read_lookup=1 capture_send_read_overlap=1"
            << " c_first_middle_last_stall=1 post_e_pending_probe=1"
            << " same_set_high_pa=1 queued_victim_lookup_collision=1 release_ack_boundary=1\n";
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "PROBE_LOOKUP_RAW_FAIL enabled=" << PROBE_LOOKUP_ON << " " << e.what() << "\n";
        return 1;
    }
}
