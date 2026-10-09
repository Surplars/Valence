// Reconstructed on checkpoint 72d44d90 after loss of the earlier workspace.
// Source preparation only: no inherited runtime PASS or old artifact identity.
#ifndef CHECKED_STORE_PREFETCH
#error "explicit CHECKED_STORE_PREFETCH=0|1 required"
#endif
#if CHECKED_STORE_PREFETCH != 0 && CHECKED_STORE_PREFETCH != 1
#error "CHECKED_STORE_PREFETCH must be 0 or 1"
#endif
#ifndef MIXED_MODEL
#define MIXED_MODEL 1
#endif
#ifndef MIXED_RTL
#define MIXED_RTL 1
#endif
#define CACHE_HOME_EMBED
#include "../harness/coherent_cache_home.cpp"
#include <array>
#include <set>

namespace checked_store_cache {
static_assert(CACHE_LINES == 512 && READ_MSHRS == 2 && RESPONSE_ENTRIES == 2,
              "selected 32 KiB/two-MSHR/two-response geometry required");
constexpr bool enabled = CHECKED_STORE_PREFETCH != 0;
constexpr uint64_t stride = 64ULL * CACHE_LINES / 2;
static uint64_t line(uint64_t a) { return a & ~63ULL; }
static unsigned set(uint64_t a) { return unsigned((a / 64) % (CACHE_LINES / 2)); }
using Words = std::array<uint64_t, 8>;
using Key = std::pair<unsigned, uint64_t>;
struct Owner {
    Key key{}; uint64_t address = 0;
    bool pf = false, store = false, acquired = false, filled = false, retired = false, acked = false;
    bool error = false, expectedError = false;
    unsigned beats = 0, sink = 0; Words expected{};
};
struct Wb {
    Key origin{}; uint64_t serial = 0, address = 0;
    bool pf = false, dirty = false, fromMiss = false, sent = false;
    unsigned beat = 0; Words expected{};
};
using COffer = std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t>;
struct Intent { Request q; bool error = false; };

// Preserve the entire original Test, including all byte, held response,
// DMA/probe, A/D/E, C/Ack and full backing-image flush oracles. This observer
// adds immutable allocation/capture history; it never derives a saved WB's
// expected lineage from a later prefetchOwner(wbMshr) value.
struct Gate {
    Test t;
    std::map<std::string, uint64_t> counts;
    std::array<std::optional<Key>, 2> active{};
    std::array<std::optional<Wb>, 2> wb{};
    std::array<uint64_t, 2> generation{}, wbSerial{};
    std::map<Key, Owner> owners;
    std::map<unsigned, Key> sources;
    std::set<uint64_t> resident;
    std::map<uint64_t, bool> installedOrigin;
    std::optional<COffer> heldC;
    std::optional<unsigned> heldE;
    std::optional<Intent> offer;
    std::deque<Intent> replies;
    uint64_t accepted = 0, returned = 0;
    bool coldCandidate = false, holdCInput = false, holdEInput = false;
    bool injectAba = false, triggered = false;

    explicit Gate(bool inject = false) : injectAba(inject) {
        t.readyAlways = true; t.observer = [&] { observe(); }; tick();
    }
    Words words(uint64_t a) const {
        Words result{};
        for (unsigned i = 0; i < 8; ++i) result[i] = t.architectural.at(line(a) + i * 8);
        return result;
    }
    uint64_t n(const std::string& key) const {
        auto i = counts.find(key); return i == counts.end() ? 0 : i->second;
    }
    void need(const std::string& key) const {
        if (!n(key)) throw std::runtime_error("nonvacuous coverage missing: " + key);
    }
    void tick() { t.tick(); }
    void ticks(unsigned cycles) { while (cycles--) tick(); }
    template<class P> void until(P p, const char* why, unsigned budget = 8192) { t.until(p, why, budget); }
    void hold(bool c, bool d, bool e, bool ack) {
        holdCInput = c; holdEInput = e;
        t.d.set_io$$holdCoherentC(c); t.d.set_io$$holdCoherentD(d);
        t.d.set_io$$holdGrantAck(e); t.d.set_io$$holdReleaseAck(ack);
    }
    void begin(Request q, bool error = false) {
        check(!offer && !t.cpuRequest, "overwriting unaccepted authored request");
        offer = Intent{q, error}; t.cpuRequest = q;
    }
    void send(Request q, bool wait = true, bool error = false) {
        begin(q, error); until([&] { return !offer; }, "CPU offer did not accept");
        if (wait) t.drainCpu();
    }
    void store(uint64_t a, uint64_t value, unsigned mask = 255, bool wait = true) {
        send({a, true, value, mask}, wait);
    }
    void withdraw() {
        check(offer && t.cpuRequest, "withdrawal requires an unaccepted offer");
        offer.reset(); t.cpuRequest.reset();
    }
    bool idle() const { return !active[0] && !active[1] && !wb[0] && !wb[1] && sources.empty(); }
    void settle() {
        t.drainCpu(); t.drainDma();
        until([&] { return idle() && !t.d.get_io$$prefetchBusy(); }, "accepted owner drain timed out");
        ticks(2);
    }
    void finish(const char* name) {
        check(!offer, "finishing with an unaccepted request");
        hold(false, false, false, false); t.blockCpu = false;
        settle(); t.flush(); ticks(2);
        check(idle() && replies.empty() && !heldC && !heldE, "finish retained an accepted owner");
        std::cout << "CHECKED_STORE_CACHE_CASE name=" << name << " store_pf=" << enabled
            << " cycles=" << t.cycles << " cpu_accept=" << t.cpuAccepted << " cpu_reply=" << t.cpuReturned
            << " dma_reply=" << t.dmaReturned << " axi_read=" << t.ddr.reads << " axi_write=" << t.ddr.writes;
        for (const auto& p : counts) std::cout << ' ' << p.first << '=' << p.second;
        std::cout << " reconstructed=1 actual_cache_home=1 executing_cpu=0 performance_qualification=0\n";
    }
    void allocate(unsigned slot, uint64_t address, bool pf, bool store) {
        check(slot < 2 && !active[slot], "allocation overwrote a live MSHR generation");
        Key key{slot, ++generation[slot]};
        for (const auto& a : active) if (a)
            check(set(owners.at(*a).address) != set(address), "two MSHRs reserved one set");
        for (const auto& w : wb) if (w && w->fromMiss && w->origin.first == slot)
            ++counts["mshr_reuse_before_ack"];
        Owner o; o.key = key; o.address = line(address); o.pf = pf; o.store = store;
        owners.emplace(key, o); active[slot] = key;
        ++counts[pf ? "pf_alloc" : "demand_alloc"];
        if (pf) {
            ++counts[store ? "pf_alloc_store_origin" : "pf_alloc_read_origin"];
            check(enabled && store, "store-only stimulus allocated unexpected read/OFF PF");
        }
    }
    void observe() {
        auto& d = t.d;
#define O(field) d.get_io$$storePfObs$$##field()
        const unsigned live = O(mshrLiveMask), pf = O(mshrPrefetchMask);
        const unsigned wlive = O(wbLiveMask), wsent = O(wbSentMask), wpf = O(wbPrefetchMask);
        check((live | pf | wlive | wsent | wpf) < 4, "observation exceeds selected two slots");
        // Pre-edge snapshots must agree with preceding sampled events. Only a
        // later actual FREE snapshot retires an MSHR, not a guessed fill cycle.
        for (unsigned i = 0; i < 2; ++i) {
            if (active[i] && !(live & (1U << i))) {
                auto& o = owners.at(*active[i]); check(o.filled, "MSHR freed before refill");
                o.retired = true; active[i].reset();
                for (const auto& w : wb) if (w && w->fromMiss && w->origin == o.key)
                    ++counts["mshr_free_before_ack"];
            }
            check(bool(live & (1U << i)) == bool(active[i]), "live MSHR lacks allocation history");
            if (active[i]) {
                const auto& o = owners.at(*active[i]);
                check(bool(pf & (1U << i)) == o.pf, "MSHR PF classification changed");
                if (o.pf) check(bool(O(mshrStoreMask) & (1U << i)) == o.store, "MSHR PF source kind changed");
            }
            check(bool(wlive & (1U << i)) == bool(wb[i]), "WB lifetime differs from capture/Ack history");
            if (wb[i]) {
                const auto& w = *wb[i];
                check(w.address == (i ? O(wbAddress1) : O(wbAddress0)) &&
                    w.sent == bool(wsent & (1U << i)) && w.pf == bool(wpf & (1U << i)),
                    "saved WB identity/sent/classification changed before Ack");
                if (w.fromMiss) check(w.origin.first == (i ? O(wbMshr1) : O(wbMshr0)), "saved WB MSHR changed");
                ++counts["wb_history_samples"];
            }
        }
        const bool fire = t.cpuAccepted != accepted;
        check(t.cpuAccepted == accepted + unsigned(fire), "unexpected CPU acceptance count");
        if (offer && offer->q.write && resident.count(line(offer->q.address))) {
            bool safe = true, same = false, foreign = false, livePf = false, livePfWb = false;
            for (const auto& a : active) if (a) {
                const auto& o = owners.at(*a); const bool eq = set(offer->q.address) == set(o.address);
                same |= eq; foreign |= !o.pf; livePf |= o.pf; safe &= enabled && o.pf && !eq;
            }
            for (const auto& w : wb) if (w) {
                const bool eq = set(offer->q.address) == set(w->address);
                same |= eq; foreign |= !w->pf; livePfWb |= w->pf; safe &= enabled && w->pf && w->sent && !eq;
            }
            ++counts["store_hit_offer"];
            counts["hit_offer_pf_mshr"] += livePf; counts["hit_offer_pf_wb"] += livePfWb;
            if (fire) {
                check(d.get_io$$hit() && safe && !O(acquireResponsePending) && !O(queuedEvictWanted) && !O(responseFull),
                      "store hit crossed foreign/same-set/refill/capture/response ownership");
                ++counts["store_hit_accept"];
                const std::string mask = offer->q.mask == 255 ? "full" : "partial";
                if (livePf) ++counts["hit_accept_pf_mshr_" + mask];
                if (livePfWb) ++counts["hit_accept_pf_wb_" + mask];
            } else {
                counts["reject_same_set"] += same; counts["reject_foreign"] += foreign;
                counts["reject_refill"] += bool(O(acquireResponsePending));
                counts["reject_response_full"] += bool(O(responseFull));
                counts["reject_held_c"] += holdCInput && bool(O(cValid));
                counts["reject_held_e_same_set"] += holdEInput && d.get_io$$grantAckOffer() && same;
            }
        }
        if (coldCandidate) {
            check(!O(allocated), "cold candidate crossed real demand barrier");
            ++counts["cold_barrier_drop"]; coldCandidate = false;
        }
        check(bool(O(candidate)) == bool(d.get_io$$prefetchEvents$$candidate()), "candidate observation mismatch");
        if (O(candidate)) {
            check(enabled && fire && offer && offer->q.write && offer->q.mask == 255 &&
                (offer->q.address & 4095) < 4032 && O(candidateStore), "candidate lacks valid authored store");
            ++counts["candidate_store_origin"];
            if (d.get_io$$miss()) coldCandidate = true; else ++counts["same_line_retry_candidate"];
        }
        check(bool(O(useful)) == bool(d.get_io$$prefetchEvents$$useful()), "useful observation mismatch");
        if (O(useful)) {
            check(fire && offer && installedOrigin.count(line(offer->q.address)), "useful PF lost install history");
            const bool source = installedOrigin.at(line(offer->q.address));
            check(source == bool(O(usefulStore)), "useful PF changed source kind");
            ++counts["pf_useful"];
            ++counts[std::string("pf_useful_") + (source ? "store_origin_" : "read_origin_") +
                     (offer->q.write ? "store_demand" : "read_demand")];
        }
        // New demand allocation PRECEDES its same-edge direct victim capture.
        if (O(demandAlloc)) {
            check(fire && offer && line(offer->q.address) == line(O(demandAllocAddress)), "demand allocation lacks intent");
            allocate(O(demandAllocSlot), O(demandAllocAddress), false, offer->q.write);
        }
        if (O(allocated)) {
            check(d.get_io$$prefetchEvents$$allocated(), "allocation boundary disagrees");
            allocate(O(allocatedSlot), O(allocatedAddress), true, O(allocatedStore));
        }
        if (O(wbCapture)) {
            const unsigned slot = O(wbCaptureSlot), m = O(wbCaptureMshr);
            check(slot < 2 && m < 2 && !wb[slot], "capture stole a live WB slot");
            Wb w; w.serial = ++wbSerial[slot]; w.address = O(wbCaptureAddress);
            w.dirty = O(wbCaptureDirty); w.fromMiss = O(wbCaptureFromMiss); w.expected = words(w.address);
            if (w.fromMiss) {
                check(bool(active[m]), "capture lacks originating allocation"); w.origin = *active[m];
                const auto& o = owners.at(w.origin); w.pf = o.pf;
                check(set(w.address) == set(o.address), "victim belongs to another owner set");
                if (w.pf && w.dirty) check(o.store, "read PF captured dirty victim");
            }
            bool got = O(wbCapturePrefetch);
            if (injectAba && !triggered && O(wbCaptureDirect) && (pf & (1U << m))) {
                got = true; triggered = true;
                std::cerr << "CHECKED_STORE_CACHE_MUTATION_TRIGGER wb-prefetch-aba\n";
            }
            if (enabled) check(got == w.pf, "WB capture stale-PF ABA origin mismatch");
            else w.pf = got; // OFF preserves its existing conservative busy classification.
            if (O(wbCaptureDirect) && (pf & (1U << m))) {
                check(w.fromMiss && !owners.at(w.origin).pf && (!enabled || !got), "direct demand inherited PF origin");
                ++counts["direct_demand_stale_pf_aba"];
            }
            resident.erase(w.address); wb[slot] = w;
            ++counts[w.dirty ? "dirty_capture" : "clean_capture"];
            if (w.pf && w.dirty) ++counts["dirty_pf_capture"];
        }
        if (O(cValid)) {
            const unsigned op = O(cOpcode), source = d.get_io$$releaseSource();
            COffer c{op, unsigned(O(cParam)), unsigned(O(cSize)), source, d.get_io$$releaseAddress(), O(cData)};
            if (heldC) check(c == *heldC, "held C payload/control changed");
            if (!O(cReady)) { heldC = c; ++counts["held_c_cycles"]; } else heldC.reset();
            if (op == 6 || op == 7) {
                check(source >= 2 && source < 4 && wb[source - 2], "C lost saved WB source");
                auto& w = *wb[source - 2];
                check(w.address == d.get_io$$releaseAddress() && O(cSize) == 6 && O(cParam) == 1 &&
                    (op == 7) == w.dirty && !w.sent, "C release identity mismatch");
                if (w.dirty) check(w.beat < 8 && O(cData) == w.expected[w.beat], "C victim bytes mismatch");
                if (O(cReady)) {
                    ++w.beat; ++counts["c_release_beats"];
                    if (w.beat == (w.dirty ? 8U : 1U)) {
                        w.sent = true; ++counts["complete_release"];
                        if (w.pf && w.dirty) ++counts["complete_dirty_pf_release"];
                    }
                }
            }
        } else check(!heldC, "held C valid dropped");
        if (d.get_io$$releaseAckFire()) {
            const unsigned source = d.get_io$$releaseAckSource();
            check(source >= 2 && source < 4 && wb[source - 2], "Ack lost saved WB source");
            const auto& w = *wb[source - 2]; check(w.sent, "Ack preceded complete C release");
            if (w.fromMiss) {
                const auto& o = owners.at(w.origin);
                if (o.retired) ++counts["late_ack_after_mshr_free"];
                if (generation[w.origin.first] > w.origin.second) ++counts["ack_after_mshr_reuse"];
                if (w.pf && o.retired) ++counts["late_pf_ack"];
            }
            ++counts["release_ack"]; wb[source - 2].reset();
        }
        if (d.get_io$$acquireFire()) {
            const unsigned source = d.get_io$$acquireSource(); check(!sources.count(source), "A reused live source");
            auto found = owners.end();
            for (auto i = owners.begin(); i != owners.end(); ++i)
                if (!i->second.retired && !i->second.acquired && i->second.address == d.get_io$$acquireAddress()) {
                    check(found == owners.end(), "A matched ambiguous owners"); found = i;
                }
            check(found != owners.end(), "A lacks allocation history");
            auto& o = found->second; o.acquired = true;
            o.expectedError = t.ddr.denyReadAddress && *t.ddr.denyReadAddress == o.address - base;
            if (o.pf) o.expected = words(o.address);
            sources[source] = o.key; ++counts[o.pf ? "pf_a_fire" : "demand_a_fire"];
        }
        if (d.get_io$$grantFire()) {
            const unsigned source = d.get_io$$grantSource(); check(sources.count(source), "D lost A source");
            auto& o = owners.at(sources.at(source));
            check(o.beats < 8 && bool(O(dDenied)) == bool(O(dCorrupt)), "outside Mixed-home error contract");
            if (!o.beats) o.sink = d.get_io$$grantSink();
            check(o.sink == d.get_io$$grantSink(), "D changed sink"); o.error |= O(dDenied) || O(dCorrupt);
            if (o.pf && !o.expectedError) check(O(dData) == o.expected[o.beats], "PF D bytes changed target");
            if (++o.beats == 8) check(o.error == o.expectedError, "D differs from scripted backing fault");
        }
        if (d.get_io$$grantAckOffer()) {
            const unsigned sink = d.get_io$$grantAckSink(); if (heldE) check(*heldE == sink, "held E changed sink");
            if (!d.get_io$$grantAckFire()) { heldE = sink; ++counts["held_e_cycles"]; } else heldE.reset();
        } else check(!heldE, "held E valid dropped");
        if (d.get_io$$grantAckFire()) {
            auto found = sources.end();
            for (auto i = sources.begin(); i != sources.end(); ++i) {
                const auto& o = owners.at(i->second);
                if (o.beats == 8 && o.sink == d.get_io$$grantAckSink()) {
                    check(found == sources.end(), "E matched ambiguous owners"); found = i;
                }
            }
            check(found != sources.end(), "E lacks complete D owner");
            auto& o = owners.at(found->second); o.acked = true;
            if (o.pf && o.error) ++counts["pf_error_e"];
            sources.erase(found);
        }
        if (O(refill)) {
            const unsigned slot = O(refillSlot); check(slot < 2 && active[slot], "refill lacks MSHR");
            auto& o = owners.at(*active[slot]);
            check(o.beats == 8 && o.acked && !o.filled && o.pf == bool(O(refillPrefetch)) &&
                o.error == bool(O(refillError)) && o.address == line(O(refillAddress)), "refill lost D/E identity");
            o.filled = true;
            if (!o.error) resident.insert(o.address);
            if (o.pf) {
                if (!o.error) installedOrigin[o.address] = o.store;
                ++counts[o.error ? "pf_error_drop" : "pf_clean_install"];
            }
        }
        if (d.get_io$$probeFire()) resident.erase(line(d.get_io$$probeAddress()));
        if (fire) {
            check(bool(offer), "CPU acceptance lacks authored token"); replies.push_back(*offer);
            offer.reset(); accepted = t.cpuAccepted;
        }
        if (t.cpuReturned != returned) {
            check(t.cpuReturned == returned + 1 && !replies.empty(), "CPU reply lacks authored FIFO token");
            check(bool(d.get_io$$cpu$$response$$bits$$error()) == replies.front().error &&
                !d.get_io$$cpu$$response$$bits$$pageFault(), "CPU fault differs from authored outcome");
            if (replies.front().error) ++counts["actual_demand_fault"];
            replies.pop_front(); returned = t.cpuReturned;
        }
#undef O
    }
};

static void cold_retry_pressure() {
    Gate g;
    const uint64_t current = base + 64, target = base + 128, alias = target + stride;
    g.store(alias, 0x1234567812345678ULL); g.store(base, 0x1122334455667788ULL);
    g.store(current, 0x8877665544332211ULL);
    if (enabled) { g.need("cold_barrier_drop"); check(g.n("pf_alloc") == 0, "cold PF already allocated"); }
    g.hold(false, enabled, false, false); g.store(current + 8, 0x1020304050607080ULL);
    if (enabled) {
        g.until([&] { return g.n("pf_a_fire"); }, "same-line retry never issued PF");
        g.store(current + 16, 0xfedcba9876543210ULL); g.store(current + 24, 0x0123456789abcdefULL, 0x55);
        g.need("same_line_retry_candidate"); g.need("hit_accept_pf_mshr_full"); g.need("hit_accept_pf_mshr_partial");
        g.begin({alias, true, 0xaaaa5555ffff0000ULL}); g.ticks(12);
        check(bool(g.offer), "same-set hit crossed live PF reservation");
        g.hold(false, false, true, false);
        g.until([&] { return g.t.d.get_io$$grantAckOffer(); }, "PF never reached held E");
        g.ticks(12); g.need("reject_held_e_same_set"); g.withdraw();
        g.t.blockCpu = true;
        g.store(current + 32, 0x9999888877776666ULL, 255, false);
        g.store(current + 40, 0xabcdefabcdefabcdULL, 0xaa, false);
        g.begin({current + 48, true, 0x5566778899aabbccULL}); g.ticks(12);
        check(bool(g.offer), "third store lacked response credit"); g.need("reject_response_full");
        g.t.blockCpu = false; g.until([&] { return !g.offer; }, "response pressure did not recover"); g.t.drainCpu();
        g.hold(false, false, false, false);
        for (unsigned n = 0; n < 12; ++n) {
            if (!g.offer) g.begin({current + 56, true, 0x13579bdf02468aceULL ^ n});
            g.tick();
        }
        g.until([&] { return !g.offer; }, "refill-blocked hit did not resume"); g.t.drainCpu();
        g.need("reject_refill"); g.need("reject_same_set");
    } else {
        g.store(current + 16, 0xfedcba9876543210ULL); g.store(current + 24, 0x0123456789abcdefULL, 0x55);
        check(!g.n("pf_alloc"), "OFF stores allocated PF");
    }
    g.settle();
    for (uint64_t a : {target, current}) for (unsigned w = 0; w < 8; ++w) g.t.dma({a + w * 8});
    check(g.t.dirtyProbeBeats >= 8, "DMA did not observe dirty store bytes");
    g.finish("cold_retry_hit_pressure_dma");
}

static void dirty_pf_aba(bool mutation = false) {
    Gate g(mutation);
    const uint64_t target = base + 514ULL * 64, current = target - 64, demand = base + 517ULL * 64;
    for (unsigned s : {2U, 5U}) {
        g.store(base + s * 64ULL, 0x1111222233334444ULL ^ s);
        g.store(base + stride + s * 64ULL, 0xaaaabbbbccccddddULL ^ s);
    }
    g.store(target - 128, 0x7654321076543210ULL); g.store(current, 0x0123456701234567ULL);
    g.hold(enabled, false, false, enabled); g.store(current + 8, 0xffeeddccbbaa0099ULL);
    if (enabled) {
        g.until([&] { return g.n("dirty_pf_capture"); }, "PF never captured dirty victim");
        g.begin({current + 16, true, 0x1122334455667788ULL}); g.ticks(16);
        check(bool(g.offer), "hit crossed held dirty C"); g.need("reject_held_c"); g.need("held_c_cycles");
        g.hold(false, false, false, true);
        g.until([&] { return !g.offer; }, "hit did not resume with sent PF WB"); g.t.drainCpu();
        g.store(current + 24, 0xfeedfacecafebeefULL, 0x55);
        g.until([&] { return g.n("mshr_free_before_ack"); }, "PF MSHR did not free before Ack");
        g.store(current + 32, 0x9988776655443322ULL); g.store(current + 40, 0x012389ab4567cdefULL, 0xaa);
        g.need("hit_accept_pf_wb_full"); g.need("hit_accept_pf_wb_partial");
        // A read miss may coexist with the old PF WB. Its direct eviction must
        // bind to the NEW demand generation despite the stale old PF slot bit.
        g.send({demand}, false);
        g.until([&] { return g.n("direct_demand_stale_pf_aba"); }, "real same-slot stale-PF ABA absent");
        g.t.drainCpu(); g.ticks(2);
        g.begin({current + 48, true, 0xcafebabe01234567ULL}); g.ticks(16);
        check(bool(g.offer), "hit crossed foreign demand WB after MSHR release"); g.need("reject_foreign");
        g.hold(false, false, false, false);
        g.until([&] { return !g.offer; }, "foreign-WB hit did not resume"); g.t.drainCpu(); g.settle();
        g.need("complete_dirty_pf_release"); g.need("late_pf_ack"); g.need("ack_after_mshr_reuse");
    } else {
        g.store(current + 16, 0x1122334455667788ULL); g.send({target}); g.send({demand});
    }
    for (uint64_t a : {target, current, demand, base + 128, base + 320}) g.t.dma({a});
    g.store(target, 0x0f1e2d3c4b5a6978ULL); g.t.dma({target});
    g.t.dma({target, true, 0xa1b2c3d4e5f60718ULL, 0x81}); g.send({target});
    if (mutation) {
        check(g.triggered, "ABA mutation never reached actual trigger");
        throw std::runtime_error("ABA mutation escaped independent history oracle");
    }
    g.finish("dirty_pf_complete_c_late_ack_direct_demand_aba");
}

static void steady_store_stream() {
    Gate g; std::map<std::string, uint64_t> before; uint64_t begin = 0;
    for (unsigned l = 0; l < 1024; ++l) {
        if (l == 512) { before = g.counts; begin = g.t.cycles; }
        for (unsigned w = 0; w < 8; ++w)
            g.store(base + l * 64ULL + w * 8, 0x6a09e667f3bcc909ULL ^ (uint64_t(l) << 17) ^
                    (uint64_t(w) * 0x1111111111111111ULL));
    }
    g.settle(); auto delta = [&](const std::string& k) { return g.n(k) - before[k]; };
    if (enabled) check(delta("pf_alloc") && delta("dirty_pf_capture") && delta("complete_dirty_pf_release") &&
        delta("hit_accept_pf_mshr_full") && delta("pf_useful"), "dirty steady optimization coverage was vacuous");
    else check(!g.n("pf_alloc"), "OFF steady store stream allocated PF");
    std::cout << "CHECKED_STORE_CACHE_STEADY first_line=512 lines=512 words_per_line=8 bytes=32768"
        << " cycles=" << g.t.cycles - begin << " pf_alloc=" << delta("pf_alloc")
        << " dirty_pf_capture=" << delta("dirty_pf_capture") << " actual_store_hits_live_pf="
        << delta("hit_accept_pf_mshr_full") << " useful=" << delta("pf_useful")
        << " reconstructed=1 performance_qualification=0\n";
    for (unsigned l : {0U, 255U, 511U, 512U, 767U, 1023U})
        for (unsigned w = 0; w < 8; ++w) g.t.dma({base + l * 64ULL + w * 8});
    g.finish("over_cache_1024_lines_eight_words_dirty_steady");
}

static void actual_axi_error() {
    Gate g; const uint64_t target = base + 128; const Words unchanged = g.words(target);
    g.store(base, 0x1111111122222222ULL); g.store(target - 64, 0x3333333344444444ULL);
    // Author the backing error before issue. CPU error intent is independent
    // of DUT hit/miss/error; the existing DDR model generates actual AXI SLVERR.
    g.t.ddr.denyReadAddress = uint32_t(target - base); const auto replies = g.t.cpuReturned;
    g.store(target - 56, 0x5555555566666666ULL); g.settle();
    if (enabled) {
        g.need("pf_error_drop"); g.need("pf_error_e");
        check(g.t.cpuReturned == replies + 1 && !g.resident.count(target), "PF fault replied or installed line");
    }
    check(g.words(target) == unchanged, "PF fault changed architectural bytes");
    g.send({target, true, 0xdeadbeefcafef00dULL}, true, true); g.need("actual_demand_fault");
    check(g.words(target) == unchanged, "faulting demand store changed bytes"); g.settle();
    g.t.ddr.denyReadAddress.reset(); const auto probes = g.t.probes, reads = g.t.ddr.reads;
    for (unsigned w = 0; w < 8; ++w) g.t.dma({target + w * 8});
    check(g.t.probes == probes && g.t.ddr.reads > reads, "error E installed directory or DMA avoided backing");
    ++g.counts["error_no_directory_real_dma"];
    const auto a = g.n("demand_a_fire"); g.store(target, 0x0123456789abcdefULL);
    check(g.n("demand_a_fire") == a + 1, "cleared error did not require actual reacquire");
    g.t.dma({target}); g.finish("actual_axi_error_pf_drop_demand_fault_clear_retry");
}
} // namespace checked_store_cache

int main(int argc, char** argv) {
    try {
        bool aba = false;
        for (int i = 1; i < argc; ++i) {
            const std::string a = argv[i];
            if (a == "--inject-mismatch") injectMismatch = true;
            else if (a == "--inject-wb-prefetch-aba") aba = true;
            else throw std::runtime_error("unknown checked-store cache argument: " + a);
        }
        if (aba) {
            check(checked_store_cache::enabled, "ABA mutation requires ON model"); checked_store_cache::dirty_pf_aba(true);
        } else {
            checked_store_cache::cold_retry_pressure(); checked_store_cache::dirty_pf_aba();
            checked_store_cache::steady_store_stream(); checked_store_cache::actual_axi_error();
        }
        std::cout << "CHECKED_STORE_CACHE_PASS store_pf=" << CHECKED_STORE_PREFETCH
            << " reconstructed=1 actual_cache_home=1 independent_bytes=1 immutable_wb_history=1"
            << " original_guest_modified=0 executing_cpu=0 performance_qualification=0\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "CHECKED_STORE_CACHE_FAIL " << e.what() << '\n'; return 1;
    }
}
