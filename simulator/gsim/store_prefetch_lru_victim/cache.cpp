// Store-origin LRU victim qualification based on the qualified checked-store PF
// fixture. No runtime PASS, generated model or performance result is inherited.
#ifndef CHECKED_STORE_PREFETCH
#define CHECKED_STORE_PREFETCH 1
#endif
#if CHECKED_STORE_PREFETCH != 1
#error "store-prefetch LRU victim gate requires checked-store PF ON in both models"
#endif
#ifndef STORE_PF_LRU_ON
#error "explicit STORE_PF_LRU_ON=0|1 must match generated model"
#endif
#if STORE_PF_LRU_ON != 0 && STORE_PF_LRU_ON != 1
#error "STORE_PF_LRU_ON must be 0 or 1"
#endif
#ifndef STORE_PF_MRU_ON
#error "explicit STORE_PF_MRU_ON=0|1 must match the generated insertion model"
#endif
#if STORE_PF_MRU_ON != 1
#error "store PF MRU insertion is required in both victim modes"
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
#include <fstream>
#include <filesystem>
#include "policy_oracle.h"

namespace store_prefetch_lru_victim {
static_assert(CACHE_LINES == 512 && READ_MSHRS == 2 && RESPONSE_ENTRIES == 2,
              "selected 32 KiB/two-MSHR/two-response geometry required");
constexpr bool enabled = true;
constexpr bool lruVictim = STORE_PF_LRU_ON != 0;
std::string imageDirectory;
std::string mutation;
constexpr bool mruInsertion = STORE_PF_MRU_ON != 0;
constexpr uint64_t stride = 64ULL * CACHE_LINES / 2;
static uint64_t line(uint64_t a) { return a & ~63ULL; }
static unsigned set(uint64_t a) { return unsigned((a / 64) % (CACHE_LINES / 2)); }
using Words = std::array<uint64_t, 8>;
using Key = std::pair<unsigned, uint64_t>;
struct Owner {
    Key key{}; uint64_t address = 0, allocationCycle = 0, acquireCycle = 0, refillCycle = 0;
    bool pf = false, store = false, acquired = false, filled = false, retired = false, acked = false;
    bool error = false, expectedError = false;
    unsigned beats = 0, sink = 0; Words expected{};
    lru_victim_oracle::Choice choice{};
};
struct Wb {
    Key origin{}; uint64_t serial = 0, address = 0, captureCycle = 0;
    bool pf = false, dirty = false, fromMiss = false, sent = false;
    unsigned beat = 0; Words expected{};
};
using COffer = std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t>;
struct Intent { Request q; bool error = false; };
struct Admission {
    uint64_t address = 0, cycle = 0;
    bool write = false, hit = false, miss = false;
};
struct Traffic {
    uint64_t cycle, ar, r, aw, w, b, c, acquire, pfAcquire, dirtyCapture;
};

// Preserve the entire original Test, including all byte, held response,
// DMA/probe, A/D/E, C/Ack and full backing-image flush oracles. This observer
// adds immutable allocation/capture history; it never derives a saved WB's
// expected lineage from a later prefetchOwner(wbMshr) value.
struct Gate {
    Test t;
    lru_victim_oracle::Policy policy{CACHE_LINES / 2, lruVictim};
    std::optional<std::pair<uint64_t, bool>> candidateIntent;
    bool policyMutationTriggered = false;
    std::map<std::string, uint64_t> counts;
    std::array<std::optional<Key>, 2> active{};
    std::array<std::optional<Wb>, 2> wb{};
    std::array<uint64_t, 2> generation{}, wbSerial{};
    std::map<Key, Owner> owners;
    std::vector<Wb> captured;
    std::vector<Admission> admissions;
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
    bool allowReadOrigin = false, trace = false;

    explicit Gate(bool inject = false, bool readOrigin = false, bool traceEvents = false)
        : injectAba(inject), allowReadOrigin(readOrigin), trace(traceEvents) {
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
    Traffic traffic() const {
        return {t.cycles, t.ddr.reads, t.ddr.rBeats, t.ddr.writes, t.ddr.wBeats,
                t.ddr.bResponses, n("c_release_beats"), n("demand_a_fire"),
                n("pf_a_fire"), n("dirty_capture")};
    }
    void reportTraffic(const char* origin, const char* phase, const Traffic& before) const {
        const auto after = traffic();
        std::cout << "STORE_PREFETCH_LRU_VICTIM_PHASE origin=" << origin << " phase=" << phase
            << " store_pf=1 store_pf_mru=" << mruInsertion
            << " cycles=" << after.cycle - before.cycle << " axi_ar=" << after.ar - before.ar
            << " axi_r=" << after.r - before.r << " axi_aw=" << after.aw - before.aw
            << " axi_w=" << after.w - before.w << " axi_b=" << after.b - before.b
            << " c_release_beats=" << after.c - before.c
            << " demand_a=" << after.acquire - before.acquire
            << " pf_a=" << after.pfAcquire - before.pfAcquire
            << " dirty_capture=" << after.dirtyCapture - before.dirtyCapture << '\n';
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
        if (!imageDirectory.empty()) {
            std::filesystem::create_directories(imageDirectory);
            const std::string stem = imageDirectory + "/" + name;
            std::ofstream golden(stem + "-expected.bin", std::ios::binary);
            std::ofstream actual(stem + "-actual.bin", std::ios::binary);
            for (uint64_t offset = 0; offset < BOARD_DDR_BYTES; offset += 8) {
                const auto e = t.architectural.at(base + offset), a = t.ddr.memory.at(uint32_t(offset));
                for (unsigned byte = 0; byte < 8; ++byte) {
                    golden.put(char(e >> (byte * 8))); actual.put(char(a >> (byte * 8)));
                }
            }
            check(bool(golden) && bool(actual), "full-image evidence write failed");
        }
        std::cout << "STORE_PREFETCH_LRU_VICTIM_CASE name=" << name << " store_pf=" << enabled
            << " store_pf_mru=" << mruInsertion << " store_pf_lru=" << lruVictim
            << " cycles=" << t.cycles << " cpu_accept=" << t.cpuAccepted << " cpu_reply=" << t.cpuReturned
            << " dma_reply=" << t.dmaReturned << " axi_read=" << t.ddr.reads << " axi_write=" << t.ddr.writes
            << " axi_ar=" << t.ddr.reads << " axi_r=" << t.ddr.rBeats
            << " axi_aw=" << t.ddr.writes << " axi_w=" << t.ddr.wBeats
            << " axi_b=" << t.ddr.bResponses;
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
        o.allocationCycle = t.cycles;
        o.choice = policy.choose(address, pf, store);
        check(o.choice.admissible, "allocated read PF selected an independently dirty victim");
        owners.emplace(key, o); active[slot] = key;
        ++counts[pf ? "pf_alloc" : "demand_alloc"];
        if (pf) {
            ++counts[store ? "pf_alloc_store_origin" : "pf_alloc_read_origin"];
            check(enabled && (store || allowReadOrigin), "store-only stimulus allocated unexpected read/OFF PF");
        }
        if (trace) std::cout << "STORE_PREFETCH_LRU_VICTIM_EVENT kind=allocate cycle=" << t.cycles
            << " address=" << o.address << " mshr=" << slot << " generation=" << key.second
            << " pf=" << pf << " store_origin=" << (pf && store) << '\n';
    }
    void observe() {
        auto& d = t.d;
#define O(field) d.get_io$$storePfObs$$##field()
        if (O(pendingCandidateValid)) {
            check(bool(candidateIntent), "pending candidate lacks original authored request");
            const auto [address, store] = *candidateIntent;
            uint64_t way0 = O(candidateWay0Valid) ? O(candidateWay0Address) : 0;
            uint64_t way1 = O(candidateWay1Valid) ? O(candidateWay1Address) : 0;
            bool observedStore = O(pendingCandidateStore), observedLru = O(candidateReplacementWay);
            const auto& expected = policy.state(address);
            if (!policyMutationTriggered && !mutation.empty() && O(allocated) && store &&
                expected.ways[0].valid && expected.ways[1].valid &&
                expected.ways[0].dirty != expected.ways[1].dirty) {
                if (mutation == "lru-bit") observedLru = !observedLru;
                else if (mutation == "origin") observedStore = !observedStore;
                else if (mutation == "full-pa") way0 ^= 1ULL << 40;
                else throw std::runtime_error("unknown policy mutation");
                policyMutationTriggered = true;
                std::cerr << "STORE_PREFETCH_LRU_VICTIM_MUTATION_TRIGGER " << mutation
                    << " cycle=" << t.cycles << " target=" << address << '\n';
            }
            check(O(pendingCandidateAddress) == address && O(pendingCandidateSet) == policy.set(address),
                  "pending candidate full PA/set differs from original authored request");
            check(observedStore == store, "pending candidate origin differs from original authored request");
            check(observedLru == bool(expected.oldest), "candidate LRU bit differs from independent access order");
            check(bool(O(candidateWay0Valid)) == expected.ways[0].valid &&
                  bool(O(candidateWay1Valid)) == expected.ways[1].valid,
                  "candidate way validity differs from independent residency");
            check(way0 == (expected.ways[0].valid ? expected.ways[0].address : 0) &&
                  way1 == (expected.ways[1].valid ? expected.ways[1].address : 0),
                  "candidate full-PA ways differ from independent residency");
            check((bool(O(candidateWay0Valid)) && bool(O(candidateWay0Dirty))) == (expected.ways[0].valid && expected.ways[0].dirty) &&
                  (bool(O(candidateWay1Valid)) && bool(O(candidateWay1Dirty))) == (expected.ways[1].valid && expected.ways[1].dirty),
                  "candidate dirty ways differ from authored stores");
            const auto selected = policy.choose(address, true, store);
            const uint64_t observedVictim = O(candidateVictimValid) ? O(candidateVictimAddress) : 0;
            check(O(candidateVictimWay) == selected.way && O(candidateVictimIndex) == selected.slot &&
                  bool(O(candidateVictimValid)) == selected.victim.valid &&
                  (bool(O(candidateVictimValid)) && bool(O(candidateVictimDirty))) == (selected.victim.valid && selected.victim.dirty) &&
                  observedVictim == (selected.victim.valid ? selected.victim.address : 0),
                  "candidate selected victim differs from independent origin/LRU policy");
            ++counts["independent_policy_snapshots"];
            if (trace) std::cout << "STORE_PREFETCH_LRU_VICTIM_SNAPSHOT cycle=" << t.cycles
                << " target=" << address << " set=" << selected.set << " store_origin=" << observedStore
                << " lru_way=" << observedLru << " way0_valid=" << expected.ways[0].valid
                << " way0_dirty=" << expected.ways[0].dirty << " way0_pa=" << way0
                << " way1_valid=" << expected.ways[1].valid << " way1_dirty=" << expected.ways[1].dirty
                << " way1_pa=" << way1 << " victim_index=" << uint64_t(O(candidateVictimIndex))
                << " victim_pa=" << observedVictim << " allocated=" << uint64_t(O(allocated)) << '\n';
        } else candidateIntent.reset();
        const unsigned live = O(mshrLiveMask), pf = O(mshrPrefetchMask);
        const unsigned wlive = O(wbLiveMask), wsent = O(wbSentMask), wpf = O(wbPrefetchMask);
        check((live | pf | wlive | wsent | wpf) < 4, "observation exceeds selected two slots");
        counts["full_wb_samples"] += wlive == 3;
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
            check(enabled && fire && offer && (offer->q.address & 4095) < 4032,
                  "candidate lacks valid authored request");
            candidateIntent = std::pair{line(offer->q.address) + 64, bool(offer->q.write)};
            check(bool(O(candidateStore)) == offer->q.write, "candidate source differs from authored request");
            if (O(candidateStore)) {
                check(offer->q.mask == 255, "store candidate lacks full authored mask");
                ++counts["candidate_store_origin"];
                if (d.get_io$$miss()) coldCandidate = true; else ++counts["same_line_retry_candidate"];
            } else {
                check(allowReadOrigin, "store-only stimulus generated read-origin PF");
                ++counts["candidate_read_origin"];
            }
            if (trace) std::cout << "STORE_PREFETCH_LRU_VICTIM_EVENT kind=candidate cycle=" << t.cycles
                << " request_address=" << offer->q.address << " expected_target=" << line(offer->q.address) + 64
                << " store_origin=" << bool(O(candidateStore)) << '\n';
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
            check(bool(candidateIntent) && candidateIntent->first == O(allocatedAddress) &&
                  candidateIntent->second == bool(O(allocatedStore)), "allocation changed captured candidate origin/address");
            const auto chosen = policy.choose(O(allocatedAddress), true, O(allocatedStore));
            check(O(allocatedIndex) == chosen.slot && bool(O(allocatedVictimValid)) == chosen.victim.valid &&
                  (bool(O(allocatedVictimValid)) && bool(O(allocatedVictimDirty))) == (chosen.victim.valid && chosen.victim.dirty) &&
                  (O(allocatedVictimValid) ? O(allocatedVictimAddress) : 0) == (chosen.victim.valid ? chosen.victim.address : 0),
                  "allocation captured wrong independent victim slot/full PA");
            allocate(O(allocatedSlot), O(allocatedAddress), true, O(allocatedStore));
        }
        if (O(wbCapture)) {
            const unsigned slot = O(wbCaptureSlot), m = O(wbCaptureMshr);
            check(slot < 2 && m < 2 && !wb[slot], "capture stole a live WB slot");
            Wb w; w.serial = ++wbSerial[slot]; w.address = O(wbCaptureAddress); w.captureCycle = t.cycles;
            w.dirty = O(wbCaptureDirty); w.fromMiss = O(wbCaptureFromMiss); w.expected = words(w.address);
            if (w.fromMiss) {
                check(bool(active[m]), "capture lacks originating allocation"); w.origin = *active[m];
                const auto& o = owners.at(w.origin); w.pf = o.pf;
                check(set(w.address) == set(o.address), "victim belongs to another owner set");
                if (w.pf && w.dirty) check(o.store, "read PF captured dirty victim");
                check(o.choice.slot == O(wbCaptureIndex) && o.choice.victim.valid &&
                      o.choice.victim.address == w.address && o.choice.victim.dirty == w.dirty,
                      "WB capture changed allocated independent slot/full PA");
            }
            bool got = O(wbCapturePrefetch);
            if (injectAba && !triggered && O(wbCaptureDirect) && (pf & (1U << m))) {
                got = true; triggered = true;
                std::cerr << "STORE_PREFETCH_LRU_VICTIM_MUTATION_TRIGGER wb-prefetch-aba\n";
            }
            if (enabled) check(got == w.pf, "WB capture stale-PF ABA origin mismatch");
            else w.pf = got; // OFF preserves its existing conservative busy classification.
            if (O(wbCaptureDirect) && (pf & (1U << m))) {
                check(w.fromMiss && !owners.at(w.origin).pf && (!enabled || !got), "direct demand inherited PF origin");
                ++counts["direct_demand_stale_pf_aba"];
            }
            policy.capture(w.address, w.dirty);
            resident.erase(w.address); wb[slot] = w; captured.push_back(w);
            if (trace) std::cout << "STORE_PREFETCH_LRU_VICTIM_EVENT kind=victim cycle=" << t.cycles
                << " address=" << w.address << " wb=" << slot << " serial=" << w.serial
                << " from_miss=" << w.fromMiss << " mshr=" << w.origin.first
                << " generation=" << w.origin.second << " owner_pf=" << w.pf
                << " dirty=" << w.dirty << '\n';
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
            auto& o = found->second; o.acquired = true; o.acquireCycle = t.cycles;
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
            o.filled = true; o.refillCycle = t.cycles;
            if (trace) std::cout << "STORE_PREFETCH_LRU_VICTIM_EVENT kind=refill cycle=" << t.cycles
                << " address=" << o.address << " mshr=" << slot << " generation=" << o.key.second
                << " pf=" << o.pf << " store_origin=" << (o.pf && o.store)
                << " installed=" << !o.error << '\n';
            check(O(refillIndex) == o.choice.slot, "refill changed independently allocated slot");
            policy.install(o.address, o.choice.way, !o.pf && o.store, o.pf, o.store, o.error);
            check(bool(O(installValid)) == !o.error, "refill install event differs from actual error");
            if (!o.error) {
                check(O(installIndex) == o.choice.slot && line(O(installAddress)) == o.address &&
                      bool(O(installDirty)) == (!o.pf && o.store), "successful install identity/dirty mismatch");
                resident.insert(o.address);
            }
            if (o.pf) {
                if (!o.error) installedOrigin[o.address] = o.store;
                ++counts[o.error ? "pf_error_drop" : "pf_clean_install"];
            }
        }
        if (d.get_io$$probeFire()) {
            policy.invalidate(d.get_io$$probeAddress());
            resident.erase(line(d.get_io$$probeAddress()));
        }
        if (fire) {
            check(bool(offer), "CPU acceptance lacks authored token");
            if (d.get_io$$hit()) policy.hit(offer->q.address, offer->q.write);
            replies.push_back(*offer);
            admissions.push_back({offer->q.address, t.cycles, offer->q.write,
                                  bool(d.get_io$$hit()), bool(d.get_io$$miss())});
            if (trace) std::cout << "STORE_PREFETCH_LRU_VICTIM_EVENT kind=cpu_admission cycle=" << t.cycles
                << " address=" << offer->q.address << " write=" << offer->q.write
                << " hit=" << uint64_t(d.get_io$$hit()) << " miss=" << uint64_t(d.get_io$$miss()) << '\n';
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
        g.need("full_wb_samples");
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
    std::cout << "STORE_PREFETCH_LRU_VICTIM_STEADY first_line=512 lines=512 words_per_line=8 bytes=32768"
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

struct Conflict {
    const char* name;
    bool storeOrigin = true;
    unsigned validMask = 3, dirtyMask = 1, oldest = 0;
    bool error = false, probeDuringAck = false;
};
static const Owner& ownerAt(const Gate& g, uint64_t address, bool pf) {
    const Owner* result = nullptr;
    for (const auto& [key, owner] : g.owners) if (owner.address == address && owner.pf == pf) {
        check(!result, "full-PA owner lookup was ambiguous"); result = &owner;
    }
    check(result, "authored target lacks an actual owner"); return *result;
}
static const Wb& captureAt(const Gate& g, Key key) {
    const Wb* result = nullptr;
    for (const auto& captured : g.captured) if (captured.fromMiss && captured.origin == key) {
        check(!result, "owner captured more than one victim"); result = &captured;
    }
    check(result, "owner lacks its actual victim capture"); return *result;
}
static void conflict(const Conflict& spec) {
    Gate g(false, !spec.storeOrigin, true);
    const uint64_t x = base + 128, y = x + stride, target = x + 2 * stride;
    const uint64_t previous = target - 128, current = target - 64;
    check(x >> 32 && target + 64 <= base + BOARD_DDR_BYTES &&
          (current % 4096) + 128 <= 4096 && set(x) == set(y) && set(y) == set(target),
          "authored conflict lacks full-width same-set physical addresses");
    const Traffic whole = g.traffic();
    // Real demand fills establish physical way order; masked stores do not
    // authorize speculation. Invalid-way-0 is established by a real DMA probe.
    const unsigned seedMask = spec.validMask == 2 ? 3 : spec.validMask;
    for (unsigned way = 0; way < 2; ++way) if (seedMask & (1U << way)) {
        const uint64_t address = way ? y : x;
        if (spec.dirtyMask & (1U << way)) {
            for (unsigned word = 0; word < 8; ++word)
                g.store(address + word * 8, 0x91e10da5c79e7b1dULL ^ (address << 3) ^
                        (uint64_t(word) * 0x1112131415161718ULL), (word & 1) ? 0xa5 : 0x5a);
        } else g.send({address});
    }
    if (spec.validMask == 2) {
        const auto probes = g.t.probes; g.t.dma({x});
        check(g.t.probes > probes && !g.policy.find(x), "invalid-way-0 setup lacks actual probe");
    }
    if (spec.validMask == 3 && spec.oldest == 1) {
        // The mirror needs one real touch; the main case keeps Y MRU solely
        // from its completed ordinary demand refill.
        g.send({x});
        check(g.admissions.back().hit, "mirror MRU source touch did not hit real cache");
    }
    if (spec.storeOrigin) {
        g.store(previous, 0x123456789abcdef0ULL);
        g.store(current, 0xfedcba9876543210ULL);
        g.need("cold_barrier_drop");
    } else {
        g.store(previous, 0x123456789abcdef0ULL, 0x55);
        g.store(current, 0xfedcba9876543210ULL, 0xaa);
        g.send({previous});
    }
    g.settle();
    check(!g.n("pf_alloc"), "seed allocated an unrelated PF");
    const auto seeded = g.policy.state(target);
    check(seeded.oldest == spec.oldest || spec.validMask != 3, "authored LRU setup failed");
    for (unsigned way = 0; way < 2; ++way)
        check(seeded.ways[way].valid == bool(spec.validMask & (1U << way)) &&
              (!seeded.ways[way].valid || seeded.ways[way].dirty == bool(spec.dirtyMask & (1U << way))),
              "authored valid/dirty seed differs from independent completed requests");
    const auto chosen = g.policy.choose(target, true, spec.storeOrigin);
    const uint64_t source = spec.oldest ? x : y;
    const Words unchanged = g.words(target);
    if (spec.error) g.t.ddr.denyReadAddress = uint32_t(target - base);
    const auto replies = g.t.cpuReturned, cBefore = g.n("c_release_beats");
    const Traffic pfStart = g.traffic();
    g.hold(chosen.admissible && chosen.victim.valid, false, false, chosen.victim.valid);
    if (spec.storeOrigin) g.store(current + 8, 0x3141592653589793ULL);
    else g.send({current});
    if (!chosen.admissible) {
        g.ticks(32);
        check(!g.n("pf_alloc") && !g.n("pf_a_fire") && !g.t.d.get_io$$prefetchBusy(),
              "read-origin both-dirty candidate acquired or retained speculative ownership");
        g.need("candidate_read_origin"); g.need("independent_policy_snapshots");
        g.t.ddr.denyReadAddress.reset(); g.finish(spec.name);
        std::cout << "STORE_PREFETCH_LRU_VICTIM_CONFLICT name=" << spec.name
            << " store_pf_lru=" << lruVictim << " admitted=0 read_dirty_blocked=1\n";
        return;
    }
    g.until([&] { return g.n("pf_alloc") == 1; }, "authored PF never allocated");
    const Key key = ownerAt(g, target, true).key;
    check(g.owners.at(key).store == spec.storeOrigin, "actual PF has wrong authored origin");
    if (chosen.victim.valid) {
        g.until([&] { return g.n("clean_capture") + g.n("dirty_capture") > 0; }, "PF did not capture victim");
        const auto& victim = captureAt(g, key);
        check(victim.address == chosen.victim.address && victim.dirty == chosen.victim.dirty && victim.pf,
              "actual victim disagrees with independently authored policy");
        g.until([&] { return g.t.d.get_io$$storePfObs$$cValid(); }, "captured victim never offered C");
        g.ticks(7); g.need("held_c_cycles");
        if (spec.probeDuringAck) {
            // Request DMA while the actual home still owns the victim. Once
            // Release completes, the home can satisfy DMA from backing and
            // need not create a probe, so requesting it later is insufficient.
            g.t.dma({chosen.victim.address}, false);
            g.until([&] { return g.t.d.get_io$$probeOffer(); }, "real DMA never offered victim probe");
            g.ticks(7);
            check(!g.t.d.get_io$$probeFire(), "captured victim probe bypassed writeback ownership");
        }
        g.hold(false, false, false, true);
        if (chosen.victim.dirty) {
            g.until([&] { return g.n("c_release_beats") == cBefore + 3; }, "dirty release missed third beat");
            g.hold(true, false, false, true); g.ticks(5);
            check(g.n("c_release_beats") == cBefore + 3, "held middle dirty C beat advanced");
            g.hold(false, false, false, true);
        }
    }
    if (spec.probeDuringAck) {
        g.until([&] { return g.n("c_release_beats") == cBefore + (chosen.victim.dirty ? 8U : 1U); },
                "probed victim never completed real C release");
        g.ticks(7);
        check(g.t.blockedProbeRelease && !g.t.d.get_io$$probeFire(), "matching probe escaped held ReleaseAck");
        // A real-home DMA maintenance barrier may delay PF refill until this
        // probe completes. Release its exact Ack before requiring refill.
        g.hold(false, false, false, false);
    }
    g.until([&] { return g.owners.at(key).retired; }, "PF refill/MSHR retirement timed out");
    const auto& completed = g.owners.at(key);
    check(completed.acquired && completed.acked && completed.filled && completed.error == spec.error &&
          g.t.cpuReturned == replies + 1 && g.words(target) == unchanged,
          "PF lost real A/D/E/error ownership or invented CPU reply/bytes");
    check(bool(g.policy.find(target)) == !spec.error, "failed PF installed or successful PF disappeared");
    const uint64_t releaseBeats = g.n("c_release_beats") - cBefore;
    check(releaseBeats == (chosen.victim.valid ? (chosen.victim.dirty ? 8U : 1U) : 0U),
          "victim did not send exact complete C burst");
    if (chosen.victim.valid && !spec.probeDuringAck) {
        bool retained = false;
        for (const auto& wb : g.wb) retained |= wb && wb->origin == key && wb->sent;
        check(retained && g.t.d.get_io$$prefetchBusy(), "held Ack lost retired PF writeback ownership");
        g.ticks(7);
    }
    g.hold(false, false, false, false); g.settle();
    if (spec.probeDuringAck) check(g.t.resolvedVictimProbes, "blocked victim probe did not resume after Ack");
    g.t.ddr.denyReadAddress.reset();
    g.reportTraffic(spec.name, "prefetch_and_release_ack", pfStart);
    unsigned hits = 0, misses = 0;
    const Traffic later = g.traffic();
    if (spec.validMask == 3) {
        const bool retained = !chosen.victim.valid || chosen.victim.address != source;
        for (unsigned word = 1; word < 8; ++word) {
            g.send({source + word * 8});
            const auto& a = g.admissions.back(); hits += a.hit; misses += a.miss;
            check(a.address == source + word * 8 && !a.write && a.hit == (retained || word > 1) &&
                  a.miss == (!retained && word == 1), "seven source words disagree with actual retention");
        }
        check(g.n("demand_a_fire") - later.acquire == uint64_t(!retained),
              "source retention disagrees with actual demand acquire count");
    }
    g.settle(); g.reportTraffic(spec.name, "seven_source_words", later);
    std::cout << "STORE_PREFETCH_LRU_VICTIM_CONFLICT name=" << spec.name
        << " store_pf_lru=" << lruVictim << " admitted=1 store_origin=" << spec.storeOrigin
        << " target=" << target << " lru_way=" << seeded.oldest << " valid_mask=" << spec.validMask
        << " dirty_mask=" << spec.dirtyMask << " victim_index=" << chosen.slot
        << " victim_pa=" << (chosen.victim.valid ? chosen.victim.address : 0)
        << " victim_dirty=" << chosen.victim.dirty << " c_beats=" << releaseBeats
        << " source=" << source << " later_hits=" << hits << " later_misses=" << misses
        << " pf_error=" << spec.error << " actual_full_pa_snapshot=1 independent_access_order=1\n";
    // Exercise actual DMA coherence on every authored line, then compare all
    // 131072 backing bytes after actual cache and home drain.
    for (uint64_t address : {x, y, target, previous, current})
        for (unsigned word = 0; word < 8; ++word) g.t.dma({address + word * 8});
    g.finish(spec.name); g.reportTraffic(spec.name, "whole_case_including_flush", whole);
    if (!mutation.empty()) throw std::runtime_error("requested actual-snapshot mutation never triggered");
}
// Cancellation uses ordinary offers at the exact pending-candidate edge.
// No internal candidate/register assignment or synthetic permission is used.
static void cancel_candidate(unsigned kind) {
    Gate g(false, false, true);
    const uint64_t target = base + 128, current = target - 64;
    const uint64_t sameSet = target + stride;
    g.store(sameSet, 0x19a273b45c6d7e8fULL, 0x55);
    g.store(target - 128, 0x8796a5b4c3d2e1f0ULL);
    g.store(current, 0x0123456789abcdefULL); g.settle();
    check(!g.n("pf_alloc"), "cancellation seed allocated PF");
    const auto candidates = g.n("candidate_store_origin");
    g.store(current + 8, 0xfedcba9876543210ULL, 255, false);
    check(g.n("candidate_store_origin") == candidates + 1, "cancellation lacks real created candidate");
    if (kind == 0) g.begin({target});
    else if (kind == 1) g.begin({sameSet, true, 0xa1b2c3d4e5f60718ULL, 0x81});
    else if (kind == 2) g.begin({target + 5*64});
    else g.t.d.set_io$$flushRequest(1);
    g.tick();
    check(!g.n("pf_alloc"), "pending PF crossed authored demand/store/maintenance cancellation");
    if (kind == 3) {
        g.until([&] { return g.t.d.get_io$$flushDone(); }, "maintenance cancellation failed to drain");
        g.t.d.set_io$$flushRequest(0); g.tick();
    } else g.until([&] { return !g.offer; }, "canceling demand did not accept");
    g.settle(); check(!g.n("pf_alloc"), "canceled PF appeared later");
    const char* names[] = {"cancel_target_demand", "cancel_same_set_store", "cancel_foreign_demand", "cancel_flush"};
    g.finish(names[kind]);
    std::cout << "STORE_PREFETCH_LRU_VICTIM_CANCEL kind=" << names[kind]
        << " store_pf_lru=" << lruVictim << " actual_pending_candidate=1 allocated=0\n";
}
} // namespace store_prefetch_lru_victim

int main(int argc, char** argv) {
    using namespace store_prefetch_lru_victim;
    try {
        bool aba = false;
        for (int i = 1; i < argc; ++i) {
            const std::string a = argv[i];
            if (a == "--inject-mismatch") injectMismatch = true;
            else if (a == "--inject-wb-prefetch-aba") aba = true;
            else if (a.rfind("--inject-policy-", 0) == 0) mutation = a.substr(16);
            else if (a.rfind("--images=", 0) == 0) imageDirectory = a.substr(9);
            else throw std::runtime_error("unknown victim gate option: " + a);
        }
        check(unsigned(aba) + unsigned(injectMismatch) + unsigned(!mutation.empty()) <= 1,
              "negative controls must run separately");
        if (!mutation.empty()) conflict({"dirty_lru_clean_mru", true, 3, 1, 0});
        else if (aba) dirty_pf_aba(true);
        else {
            cold_retry_pressure(); dirty_pf_aba(); steady_store_stream(); actual_axi_error();
            const Conflict cases[] = {
                {"dirty_lru_clean_mru", true, 3, 1, 0},
                {"mirror_dirty_lru_clean_mru", true, 3, 2, 1},
                {"both_invalid", true, 0, 0, 0}, {"invalid_way1", true, 1, 1, 1},
                {"invalid_way0", true, 2, 2, 0},
                {"both_clean_lru0", true, 3, 0, 0}, {"both_clean_lru1", true, 3, 0, 1},
                {"both_dirty_lru0", true, 3, 3, 0, false, true}, {"both_dirty_lru1", true, 3, 3, 1},
                {"read_origin_clean_first", false, 3, 1, 0},
                {"read_origin_both_dirty_blocked", false, 3, 3, 0},
                {"dirty_victim_pf_error", true, 3, 1, 0, true}
            };
            for (const auto& c : cases) conflict(c);
            for (unsigned kind = 0; kind < 4; ++kind) cancel_candidate(kind);
        }
        std::cout << "STORE_PREFETCH_LRU_VICTIM_PASS store_pf=1 store_pf_mru=1 store_pf_lru=" << lruVictim
            << " cases=20 independent_policy=1 full_pa=1 actual_cache_home=1 full_flush=1"
            << " original_guest_modified=0 executing_cpu=0 performance_qualification=0\n";
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "STORE_PREFETCH_LRU_VICTIM_FAIL " << e.what() << '\n'; return 1;
    }
}
