// Reuse the established independent protocol/data oracle unchanged.
#define main existingHomeMshrMain
#include "home_mshr.cpp"
#undef main
#ifndef HOME_LINES
#define HOME_LINES 16
#endif
#ifndef HOME_MIXED
#define HOME_MIXED 0
#endif

struct TagTest : Test {
    uint64_t trace = 1469598103934665603ULL;
    unsigned simultaneousEC = 0, stalledUpper = 0, stalledA = 0;
    unsigned canceledAcquires = 0, canceledGrants = 0;
    void mix(uint64_t value) { trace ^= value; trace *= 1099511628211ULL; }
    void tick() {
        const bool cv = !c.empty(), ev = !e.empty() && allowE;
        const bool uv = upper && !upperAccepted, av = !requests.empty();
        const auto finishedBefore = finished;
        Test::tick();
        simultaneousEC += cv && ev && d.get_io$$client$$c$$ready() && finished != finishedBefore;
        stalledUpper += uv && !d.get_io$$upstream$$request$$ready();
        stalledA += av && !d.get_io$$client$$a$$ready();
        // Only public protocol observations enter this deterministic cycle trace.
        // It is compared byte-for-byte between baseline and candidate receipts.
        mix(cycle); mix(accepted); mix(finished); mix(cBeats); mix(readGets); mix(probes); mix(upperDone);
        mix(d.get_io$$client$$a$$ready()); mix(d.get_io$$client$$c$$ready()); mix(d.get_io$$client$$e$$ready());
        mix(d.get_io$$upstream$$request$$ready());
        mix(d.get_io$$client$$d$$valid());
        if (d.get_io$$client$$d$$valid()) {
            mix(d.get_io$$client$$d$$bits$$opcode()); mix(d.get_io$$client$$d$$bits$$source());
            mix(d.get_io$$client$$d$$bits$$sink()); mix(d.get_io$$client$$d$$bits$$data());
            mix(d.get_io$$client$$d$$bits$$denied()); mix(d.get_io$$client$$d$$bits$$corrupt());
        }
        mix(d.get_io$$client$$b$$valid());
        if (d.get_io$$client$$b$$valid()) { mix(d.get_io$$client$$b$$bits$$address()); mix(d.get_io$$client$$b$$bits$$source()); }
        mix(d.get_io$$line$$a$$valid());
        if (d.get_io$$line$$a$$valid()) {
            mix(d.get_io$$line$$a$$bits$$address()); mix(d.get_io$$line$$a$$bits$$opcode());
            mix(d.get_io$$line$$a$$bits$$source()); mix(d.get_io$$line$$a$$bits$$data());
        }
        mix(d.get_io$$upstream$$response$$valid());
        if (d.get_io$$upstream$$response$$valid()) mix(d.get_io$$upstream$$response$$bits$$data());
    }
    template<class F> void until(F f, const char* message) {
        unsigned n = 0; while (!f()) { check(++n < 2500, message); tick(); }
    }
    void fill(uint64_t address, unsigned source = 0) {
        const auto goal = finished + 1; acquire(address, source);
        until([&] { return finished == goal; }, "tag test Acquire did not complete");
    }
    void upstreamRead(uint64_t address) {
        const auto goal = upperDone + 1; upper = address;
        until([&] { return upperDone == goal; }, "tag test upstream read did not complete");
    }
    void resetEpoch() {
        canceledAcquires += live.size();
        for (const auto& [source, entry] : live) canceledGrants += entry.beat == 8;
        Test::resetEpoch();
    }
    void drain() {
        until([&] { return requests.empty() && live.empty() && c.empty() && e.empty() && !releasing &&
            pending.empty() && !held && !write && !dataResponse && !upper; }, "tag test failed to drain");
        check(accepted == finished + canceledAcquires && grants == finished + canceledGrants,
            "tag test lost Acquire ownership");
    }
    void report(const char* scenario) {
        std::cout << "HOME_TAG_CASE " << scenario << " cycles=" << cycle << " trace=" << trace
            << " acquires=" << accepted << " grants=" << grants << " releases=" << releases
            << " probes=" << probes << " writes=" << writes << " simultaneous_ec=" << simultaneousEC
            << " held_upper=" << stalledUpper << " held_a=" << stalledA
            << " reset_canceled=" << canceledAcquires << "\n";
    }
};

int main(int argc, char** argv) { try {
    const std::string arg = argc > 1 ? argv[1] : "";
    constexpr uint64_t stride = (HOME_LINES / 2) * 64ULL;
    const uint64_t a = base, b = base + stride, replacement = base + 2 * stride;
    TagTest aliases; aliases.inject = arg == "--inject-data";
    aliases.fill(a); aliases.fill(b, 1); aliases.modify(a); aliases.modify(b);
    if (arg == "--bad-owned-acquire") {
        // One free slot is needed for A to reach its independent admission assertion.
        TagTest duplicate; duplicate.fill(a + 64); duplicate.acquire(a + 64, 1);
        for (unsigned n = 0; n < 100; ++n) duplicate.tick();
        throw std::runtime_error("owned Acquire was not rejected");
    }
    const uint64_t highAlias = a | (1ULL << 40);
    aliases.upstreamRead(highAlias);
    check(aliases.probes == 0 && aliases.cache.count(a) && aliases.cache.count(b), "high address aliased directory owner");
    if (arg == "--bad-aperture") {
        aliases.acquire(highAlias + 64, 0);
        for (unsigned n = 0; n < 100; ++n) aliases.tick();
        throw std::runtime_error("invalid aperture Acquire was not rejected");
    }
    if (arg == "--bad-release-aperture") {
        aliases.c.push_back({highAlias, 4, 6, 1, 0, {}});
        for (unsigned n = 0; n < 100; ++n) aliases.tick();
        throw std::runtime_error("invalid aperture Release was not rejected");
    }
    aliases.upstreamRead(a);
    check(aliases.probes == 1 && !aliases.cache.count(a) && aliases.cache.count(b), "same-set tags selected wrong owner");
    aliases.fill(replacement); aliases.release(b);
    aliases.until([&] { return aliases.releases == 1; }, "same-set second-way Release failed");
    aliases.upstreamRead(replacement);
    check(aliases.probes == 2 && aliases.cache.empty(), "replacement tag selected wrong owner");
    // This address crosses the 4-GiB boundary of the same aperture.
    aliases.fill(base + 0x10000); aliases.modify(base + 0x10000); aliases.upstreamRead(base + 0x10000);
    aliases.drain(); aliases.report("aliases");

    TagTest overlap;
    const uint64_t probeLine = base, releaseLine = base + 64, installLine = base + 128;
    overlap.fill(probeLine); overlap.fill(releaseLine); overlap.modify(probeLine); overlap.modify(releaseLine);
    overlap.allowE = false; overlap.acquire(installLine, 0);
    overlap.until([&] { return !overlap.e.empty(); }, "no pending E installation");
    overlap.release(releaseLine); overlap.upper = probeLine; overlap.allowE = true;
    overlap.tick();
    check(overlap.simultaneousEC == 1 && overlap.stalledUpper, "different-set E/C/upstream overlap absent");
    overlap.drain();
    check(overlap.cache.count(installLine) && !overlap.cache.count(probeLine) && overlap.releases == 1,
        "E installation was lost to another reader");
    overlap.upstreamRead(installLine);
    check(overlap.probes == 2, "different-set installed owner not found");
    overlap.drain(); overlap.report("concurrent_e_c_upstream");

    TagTest saved;
    saved.fill(base); saved.modify(base);
    saved.upper = base;
    saved.until([&] { return saved.upperAccepted; }, "saved probe request was not accepted");
    // The acceptance saved the request; the next registered mProbeSend cycle
    // simultaneously sees first ReleaseC. No DUT-internal observation is used.
    saved.release(base); saved.tick();
    check(saved.cBeats == 1 && saved.probes == 0, "ReleaseC did not race saved probe recheck");
    saved.drain();
    check(saved.probes == 0 && saved.releases == 1 && saved.upperDone == 1,
        "released saved probe was not canceled before issue");
    saved.report("release_c_saved_recheck");

    TagTest disjoint;
    disjoint.fill(base); disjoint.fill(base + 64); disjoint.modify(base); disjoint.modify(base + 64);
    disjoint.upper = base;
    disjoint.until([&] { return disjoint.upperAccepted; }, "disjoint saved probe was not accepted");
    disjoint.release(base + 64); disjoint.tick();
    check(disjoint.cBeats == 1 && disjoint.probes == 0, "disjoint ReleaseC/recheck overlap absent");
    disjoint.drain();
    check(disjoint.probes == 1 && disjoint.releases == 1 && disjoint.upperDone == 1 && disjoint.cache.empty(),
        "ReleaseC redirected or canceled the disjoint saved probe");
    disjoint.report("disjoint_release_c_saved_recheck");

    TagTest held;
    held.fill(base); held.fill(base + 64); held.modify(base);
    held.allowD = false; held.allowE = false;
    for (unsigned i = 0; i < HOME_ENTRIES; ++i) held.acquire(base + 128 + 64 * i, i);
    held.until([&] { return held.d.get_io$$client$$d$$valid(); }, "no held Grant");
    held.release(base); const auto oldWrites = held.writes;
    held.until([&] { return held.writes > oldWrites; }, "release blocked by held Grant");
    for (unsigned n = 0; n < 9; ++n) held.tick();
    held.allowD = true;
    held.until([&] { return held.releases == 1 && held.grants == 2 + HOME_ENTRIES; }, "held Grants failed to finish");
    held.allowE = true; held.drain();
    check(held.peak >= HOME_ENTRIES, "configured Acquire capacity missing");
    // Hold a Probe across a racing release; existing Test checks stable B bits.
    held.modify(base + 64); held.holdB = true; held.upper = base + 64;
    held.until([&] { return held.d.get_io$$client$$b$$valid(); }, "no held Probe");
    for (unsigned n = 0; n < 7; ++n) held.tick();
    held.release(base + 64); held.holdB = false; held.drain();
    held.denyAddress = base + 0x4000; held.fill(*held.denyAddress);
    check(!held.cache.count(*held.denyAddress), "denied Grant installed tag");
    held.denyAddress.reset(); held.fill(base + 0x4000);
    held.allowD = false; held.allowE = false; held.acquire(base + 0x5040, 0);
    held.until([&] { return held.d.get_io$$client$$d$$valid(); }, "reset lacked held Grant");
    held.resetEpoch(); held.mix(0xfeed);
    held.fill(base + 0x5040); held.upstreamRead(base + 0x5040); held.drain();
    held.report("held_reset");
    std::cout << "HOME_TAG_RAM_PASS mixed=" << HOME_MIXED << " lines=" << HOME_LINES
              << " entries=" << HOME_ENTRIES << "\n";
    return 0;
} catch (const std::exception& error) { std::cerr << error.what() << "\n"; return 1; } }
