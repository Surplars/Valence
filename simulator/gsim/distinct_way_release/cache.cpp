// New source must be compiled only against its own OFF/ON generated model.
#ifndef DISTINCT_WAY_RELEASE_ON
#error "explicit DISTINCT_WAY_RELEASE_ON=0|1 is required"
#endif
#if DISTINCT_WAY_RELEASE_ON != 0 && DISTINCT_WAY_RELEASE_ON != 1
#error "invalid distinct-way mode"
#endif
#ifdef MIXED_MODEL
#error "this gate retains the Board AW/pending-R fence host"
#endif
#define DISTINCT_WAY_FIXTURE 1
#define CACHE_HOME_EMBED
#include "../harness/coherent_cache_home.cpp"
#include <array>
#include <set>

namespace distinct_way {
constexpr bool enabled = DISTINCT_WAY_RELEASE_ON;
constexpr unsigned sets = CACHE_LINES / 2;
constexpr uint64_t stride = 64ULL * sets;
static_assert(CACHE_LINES == 512 && READ_MSHRS == 2 && RESPONSE_ENTRIES == 2);
static uint64_t line(uint64_t a) { return a & ~63ULL; }
static unsigned set(uint64_t a) { return unsigned((a >> 6) % sets); }
using Words = std::array<uint64_t, 8>;
using Key = std::pair<unsigned, uint64_t>;
struct Resident { uint64_t address = 0; bool dirty = false; };
struct Owner {
    Key key{}; uint64_t address = 0; unsigned index = 0, source = 0, sink = 0, beats = 0;
    bool pf = false, store = false, acquired = false, acked = false, error = false, expectedError = false, retired = false;
    Words grant{};
};
struct Acquire { Key key{}; uint64_t address = 0; unsigned directory = 0, source = 0; };
struct Release {
    Key key{}; uint64_t address = 0; Words words{}; unsigned beats = 0, directory = 0;
    bool fromMiss = false, dirty = false, first = true, sent = false;
};
using CBeat = std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t>;
using DBeat = std::tuple<unsigned, unsigned, uint64_t, bool, bool>;

struct Gate {
    Test t;
    std::array<std::optional<Resident>, CACHE_LINES> cache{};
    std::array<std::optional<uint64_t>, CACHE_LINES> directory{};
    std::array<unsigned, sets> lru{};
    std::array<std::optional<Key>, 2> live{};
    std::array<uint64_t, 2> generation{};
    std::map<Key, Owner> owners;
    std::array<std::optional<Acquire>, 2> home{};
    std::array<std::optional<Release>, 2> wb{};
    std::map<unsigned, Key> source;
    std::optional<Request> offered;
    std::optional<CBeat> heldC;
    std::optional<DBeat> heldD;
    std::optional<std::pair<unsigned, uint64_t>> heldA;
    std::optional<unsigned> heldE;
    std::map<std::string, unsigned> coverage;
    std::map<uint64_t, unsigned> cBeats, aFires, eFires;
    std::optional<uint64_t> probeAddress;
    std::optional<uint32_t> poisonAddress;
    unsigned poisonBeat = 7;
    uint64_t backingReadBeats = 0;
    bool mutateDirectory = false, mutationDone = false;

    Gate() {
        t.readyAlways = true;
        t.beforeStep = [&] {
            offered = t.cpuRequest;
            if (poisonAddress) {
                const auto r = t.ddr.selected();
                t.d.set_io$$ddrAxi$$r$$bits$$resp(r != t.ddr.pendingReads.end() &&
                    r->address == *poisonAddress && r->beat == poisonBeat ? 2 : 0);
            }
        };
        t.observer = [&] { observe(); };
        tick();
        check(bool(t.d.get_io$$distinctWay$$enabled()) == enabled, "actual fixture flag differs from host");
    }
    void tick() { t.tick(); }
    void ticks(unsigned n) { while (n--) tick(); }
    template<class P> void until(P p, const char* why) { t.until(p, why, 8192); }
    Words words(uint64_t a) const {
        Words w{}; for (unsigned b = 0; b < 8; ++b) w[b] = t.architectural.at(line(a) + b * 8); return w;
    }
    std::optional<unsigned> resident(uint64_t a) const {
        for (unsigned w = 0; w < 2; ++w) {
            const unsigned i = set(a) + w * sets;
            if (cache[i] && cache[i]->address == line(a)) return i;
        }
        return {};
    }
    unsigned committed(uint64_t a) const {
        std::optional<unsigned> found;
        for (unsigned i = 0; i < CACHE_LINES; ++i) if (directory[i] && *directory[i] == line(a)) {
            check(!found, "independent directory duplicate line"); found = i;
        }
        check(bool(found), "C/probe lacks independently committed owner"); return *found;
    }
    unsigned choose(uint64_t a, bool filter) const {
        bool eligible[2] = {true, true};
        if (filter) for (const auto& key : live) if (key) {
            const auto i = owners.at(*key).index;
            if (i % sets == set(a)) eligible[i / sets] = false;
        }
        for (unsigned w = 0; w < 2; ++w) if (eligible[w] && !cache[set(a) + w * sets]) return set(a) + w * sets;
        const unsigned w = eligible[lru[set(a)]] ? lru[set(a)] : 1 - lru[set(a)];
        check(eligible[w], "allocation has no unreserved way"); return set(a) + w * sets;
    }
    void allocate(unsigned m, uint64_t address, unsigned index, bool pf, bool store) {
        check(m < 2 && !live[m], "allocation reused a live MSHR generation");
        bool same = false;
        for (const auto& key : live) if (key && set(owners.at(*key).address) == set(address)) {
            const auto& old = owners.at(*key); same = true;
            check(enabled && !pf && !store && old.pf && old.store && old.acquired &&
                old.address != line(address), "new same-set owner exceeded narrow issued-store-PF/read scope");
        }
        check(index == choose(address, same), "fixed victim differs from eligibility-first invalid/LRU oracle");
        const Key key{m, ++generation[m]};
        Owner owner; owner.key = key; owner.address = line(address); owner.index = index;
        owner.pf = pf; owner.store = store; owners.emplace(key, owner); live[m] = key;
    }
    void observe() {
        auto& d = t.d;
        if (t.ddr.rValid && d.get_io$$ddrAxi$$r$$ready()) ++backingReadBeats;
#define O(name) d.get_io$$storePfObs$$##name()
        // Compare committed pre-edge ownership with an event-derived ledger.
        // E's tag write may already have changed its *unowned* bank in GSIM.
        for (unsigned i = 0; i < CACHE_LINES; ++i) {
            check(bool(d.home$owned[i]) == bool(directory[i]), "home owned bit changed outside C/E/probe responsibility");
            if (directory[i]) {
                uint64_t address = ((i < sets ? d.home$tagBanks_0[i] : d.home$tagBanks_1[i-sets]) << 14) |
                    (uint64_t(i % sets) << 6);
                if (mutateDirectory && !mutationDone && !home[0] && !home[1]) {
                    address ^= uint64_t(1) << 40; mutationDone = true;
                }
                check(address == *directory[i], "home directory full-line identity mismatch");
            }
            check(bool(d.cache$valid[i]) == bool(cache[i]), "cache validity changed outside captured owner/probe/refill");
            if (cache[i]) check(bool(d.cache$dirty[i]) == cache[i]->dirty, "cache dirty byte responsibility mismatch");
        }
        for (unsigned m = 0; m < 2; ++m) {
            check(bool(d.cache$phase[m]) == bool(live[m]), "cache lifetime/phase mismatch");
            if (live[m]) check(d.cache$pendingIndex[m] == owners.at(*live[m]).index &&
                line(d.cache$pending$$address[m]) == owners.at(*live[m]).address, "fixed MSHR index/address changed");
            if (home[m]) {
                check(!directory[home[m]->directory] && d.home$directory[m] == home[m]->directory &&
                    d.home$addresses[m] == home[m]->address && d.home$sources[m] == home[m]->source,
                    "home reservation changed or became committed before E");
            }
        }
        if (O(demandAlloc)) {
            check(offered && line(offered->address) == line(O(demandAllocAddress)), "demand lost authored request");
            const unsigned m = O(demandAllocSlot);
            allocate(m, offered->address, d.cache$pendingIndex$NEXT[m], false, offered->write);
        }
        if (O(allocated)) {
            check(O(allocatedStore), "fixture unexpectedly allocated read-origin PF");
            allocate(O(allocatedSlot), O(allocatedAddress), O(allocatedIndex), true, true);
        }
        if (d.get_io$$hit()) {
            check(bool(offered), "hit lost authored request"); const auto index = resident(offered->address);
            check(bool(index), "hit not found in independent resident model"); lru[set(offered->address)] = 1 - *index / sets;
            if (offered->write) cache[*index]->dirty = true;
        }
        if (O(wbCapture)) {
            const unsigned j = O(wbCaptureSlot), index = O(wbCaptureIndex), m = O(wbCaptureMshr);
            check(j < 2 && !wb[j] && cache[index] && cache[index]->address == O(wbCaptureAddress) &&
                cache[index]->dirty == bool(O(wbCaptureDirty)), "WB capture lost selected resident victim");
            Release r; r.address = O(wbCaptureAddress); r.words = words(r.address); r.dirty = O(wbCaptureDirty);
            r.fromMiss = O(wbCaptureFromMiss);
            if (r.fromMiss) { check(bool(live[m]), "WB has no allocated origin"); r.key = *live[m];
                check(bool(O(wbCapturePrefetch)) == owners.at(r.key).pf, "WB inherited stale PF lineage"); }
            wb[j] = r; cache[index].reset();
        }
        if (O(cValid)) {
            const CBeat c{O(cOpcode), O(cParam), O(cSize), d.get_io$$releaseSource(),
                d.get_io$$releaseAddress(), O(cData)};
            if (heldC) check(c == *heldC, "held C full address/source/size/permission/data changed");
            heldC = !O(cReady) ? std::optional{c} : std::nullopt;
        } else check(!heldC, "held C offer disappeared");
        if (d.get_io$$releaseFire()) {
            const unsigned sourceId = d.get_io$$releaseSource();
            check(sourceId >= 2 && sourceId < 4 && wb[sourceId-2], "C source has no immutable WB owner");
            auto& r = *wb[sourceId-2];
            check(r.address == d.get_io$$releaseAddress() && r.dirty == bool(d.get_io$$releaseData()) &&
                O(cSize) == 6 && O(cParam) == 1 && !r.sent, "C changed original release identity");
            if (r.first) {
                r.directory = committed(r.address); r.first = false;
                for (const auto& a : home) if (a) check(a->address != r.address && a->directory != r.directory,
                    "first C aliases a full transient line/directory");
                if (d.get_io$$grantAckFire()) ++coverage["first_c_e"];
            }
            if (r.dirty) check(r.beats < 8 && O(cData) == r.words[r.beats], "C dirty victim full-byte mismatch");
            ++r.beats; ++cBeats[r.address];
            if (r.beats == (r.dirty ? 8U : 1U)) {
                check(directory[r.directory] == r.address, "last C lost committed slot");
                directory[r.directory].reset(); r.sent = true;
                if (d.get_io$$grantAckFire()) ++coverage["last_c_e"];
            }
        }
        if (d.get_io$$acquireOffer()) {
            const auto a = std::pair{unsigned(d.get_io$$acquireSource()), uint64_t(d.get_io$$acquireAddress())};
            if (heldA) check(*heldA == a, "held A address/source changed");
            heldA = !d.get_io$$acquireFire() ? std::optional{a} : std::nullopt;
        } else check(!heldA, "held A offer disappeared");
        if (d.get_io$$acquireFire()) {
            const unsigned src = d.get_io$$acquireSource(); const uint64_t address = d.get_io$$acquireAddress();
            check(!source.count(src), "engine source reused before E");
            std::optional<Key> key;
            for (const auto& k : live) if (k && owners.at(*k).address == address) { check(!key, "ambiguous A owner"); key = k; }
            check(bool(key), "A lacks full-line allocated owner"); auto& owner = owners.at(*key);
            check(!owner.acquired && d.cache$engine$tag[src] == key->first, "A tag differs from MSHR allocation identity");
            const unsigned sink = !home[0] ? 0 : 1;
            check(!home[sink], "home Acquire capacity exceeded");
            for (const auto& a : home) if (a) check(set(a->address) != set(address), "second same-set A escaped E gate");
            const unsigned dir = !directory[set(address)] ? set(address) : set(address) + sets;
            check(!directory[dir] && d.home$directory$NEXT[sink] == dir && d.home$sources$NEXT[sink] == (src ^ 1U),
                "home allocator/source permutation differs from independent ledger");
            home[sink] = Acquire{*key, address, dir, src ^ 1U}; owner.source = src; owner.acquired = true;
            owner.expectedError = t.ddr.denyReadAddress && *t.ddr.denyReadAddress == uint32_t(address-base);
            // The actual mixed-home contract sends zero for every beat of an
            // errored line, including beats whose delivered error bit is clear.
            for (unsigned b = 0; b < 8; ++b) owner.grant[b] = owner.expectedError ? 0 :
                t.ddr.memory.at(uint32_t(address-base+b*8));
            source[src] = *key; ++aFires[address];
            if (dir != owner.index) ++coverage["cache_directory_permutation"];
            if ((src ^ 1U) != sink) ++coverage["source_sink_permutation"];
        }
        if (d.get_io$$distinctWay$$grantOffer()) {
            const DBeat payload{d.get_io$$grantSource(), d.get_io$$grantSink(), O(dData), bool(O(dDenied)), bool(O(dCorrupt))};
            if (heldD) check(*heldD == payload, "held D source/sink/data/error changed");
            heldD = !d.get_io$$distinctWay$$grantReady() ? std::optional{payload} : std::nullopt;
        } else check(!heldD, "held D offer disappeared");
        if (d.get_io$$grantFire()) {
            const unsigned src = d.get_io$$grantSource(); check(source.count(src), "D lacks A lifetime");
            auto& owner = owners.at(source.at(src));
            const unsigned sink = d.get_io$$grantSink();
            check(home[sink] && home[sink]->key == owner.key && owner.beats < 8 &&
                O(dData) == owner.grant[owner.beats], "D whole-line bytes or home reservation mismatch");
            if (owner.beats) check(owner.sink == sink, "D sink changed during burst");
            const unsigned mode = d.io$$distinctWay$$faultMode, errorBeat = d.io$$distinctWay$$faultBeat;
            const bool chosen = owner.expectedError && (mode == 0 || owner.beats == errorBeat);
            check(bool(O(dDenied)) == (chosen && mode != 2) && bool(O(dCorrupt)) == (chosen && mode != 1),
                "D denied/corrupt field or beat differs from scripted full-line fault");
            owner.sink = sink; ++owner.beats; owner.error |= O(dDenied) || O(dCorrupt);
            if (owner.beats == 8) check(owner.error == owner.expectedError, "whole-line D error aggregation mismatch");
        }
        if (d.get_io$$grantAckOffer()) {
            const unsigned sink = d.get_io$$grantAckSink(); if (heldE) check(*heldE == sink, "held E sink changed");
            heldE = !d.get_io$$grantAckFire() ? std::optional{sink} : std::nullopt;
        } else check(!heldE, "held E offer disappeared");
        if (d.get_io$$grantAckFire()) {
            const unsigned sink = d.get_io$$grantAckSink(); check(bool(home[sink]), "E lacks reserved home sink");
            const Acquire a = *home[sink]; auto& owner = owners.at(a.key);
            check(owner.beats == 8 && owner.sink == sink && !owner.acked && !directory[a.directory],
                "E preceded whole line or overwrote committed C slot");
            check(owner.error == bool(d.home$errors[sink]), "delivered full-line error differs from home result");
            if (!owner.error) directory[a.directory] = a.address;
            owner.acked = true; source.erase(owner.source); home[sink].reset(); ++eFires[a.address];
        }
        if (O(refill)) {
            const unsigned m = O(refillSlot); check(bool(live[m]), "refill has no full MSHR lifetime");
            const auto& owner = owners.at(*live[m]);
            check(owner.acked && owner.beats == 8 && owner.address == line(O(refillAddress)) &&
                owner.index == O(refillIndex) && owner.error == bool(O(refillError)) &&
                bool(O(installValid)) == !owner.error, "refill installation escaped fixed index/full error/E");
            if (!owner.error) {
                check(!cache[owner.index], "refill overwrote a still-valid way");
                cache[owner.index] = Resident{owner.address, !owner.pf && owner.store};
                lru[set(owner.address)] = 1 - owner.index / sets;
            }
        }
        if (d.get_io$$probeFire()) {
            const uint64_t a = d.get_io$$probeAddress(); check(!probeAddress, "overlapping maintenance probes");
            probeAddress = a; const auto index = resident(a); if (index) cache[*index].reset();
        }
        for (unsigned p = 0; p < 2; ++p) if (d.home$probe$phase[p] == 3 && d.home$probe$phase$NEXT[p] == 0) {
            check(probeAddress && d.home$probe$address[p] == *probeAddress, "probe completion lost full address");
            directory[committed(*probeAddress)].reset(); probeAddress.reset(); ++coverage["probe_complete"];
        }
        if (d.get_io$$releaseAckFire()) {
            const unsigned src = d.get_io$$releaseAckSource(); check(src >= 2 && src < 4 && wb[src-2], "late Ack lost saved WB owner");
            const auto& r = *wb[src-2]; check(r.sent, "Ack preceded last C");
            if (r.fromMiss && generation[r.key.first] > r.key.second && directory[r.directory] &&
                *directory[r.directory] != r.address) ++coverage["ack_after_both_reuses"];
            wb[src-2].reset();
        }
        for (unsigned m = 0; m < 2; ++m) if (live[m] && d.cache$phase$NEXT[m] == 0) {
            owners.at(*live[m]).retired = true; live[m].reset();
        }
#undef O
    }
    void settle() {
        t.drainCpu(); t.drainDma();
        until([&] { return !t.d.get_io$$prefetchBusy() && !live[0] && !live[1] && !wb[0] && !wb[1]; }, "owner drain timed out");
        ticks(2);
    }
    void fillDirty(uint64_t a) {
        for (unsigned b = 0; b < 8; ++b) t.cpu({a+b*8, true, 0x91e10da5c79e7b1dULL ^ (a << 3) ^
            (uint64_t(b)*0x1112131415161718ULL), b & 1U ? 0xa5U : 0x5aU});
    }
    void hold(bool c, bool d, bool e, bool ack) {
        t.d.set_io$$holdCoherentC(c); t.d.set_io$$holdCoherentD(d);
        t.d.set_io$$holdGrantAck(e); t.d.set_io$$holdReleaseAck(ack);
    }
    void finish(const char* name) {
        hold(false, false, false, false); t.d.set_io$$distinctWay$$holdAcquire(0); t.blockCpu = false;
        poisonAddress.reset(); t.ddr.denyReadAddress.reset(); t.d.set_io$$distinctWay$$faultMode(0);
        settle(); t.flush(); ticks(2);
        check(!home[0] && !home[1] && !source.size() && !heldA && !heldC && !heldD && !heldE,
            "gate finished with an accepted or held owner");
        std::cout << "DISTINCT_WAY_CASE name=" << name << " on=" << enabled << " cycles=" << t.cycles
            << " byte_oracle=1 directory_oracle=1 actual_cache_home=1 executing_cpu=0";
        for (const auto& [key, value] : coverage) std::cout << ' ' << key << '=' << value;
        std::cout << '\n';
    }
};

constexpr uint64_t x = base + 128, y = x + stride, pf = x + 2*stride, demand = x + 3*stride;
static void permuteWays(Gate& g) {
    // Preserve legality while separating physical cache way from home slot:
    // capture a way-1 victim, hold its A, then probe away old way 0. The saved
    // way-1 refill now acquires free directory way 0. Refill way 0 into dir 1.
    const uint64_t temporary = x + 4*stride;
    g.fillDirty(x); g.fillDirty(y); g.t.cpu({x});
    g.t.d.set_io$$distinctWay$$holdAcquire(1); g.t.cpu({temporary}, false);
    g.until([&] { return g.t.d.get_io$$acquireOffer(); }, "permutation A not held");
    g.t.dma({x}); g.t.d.set_io$$distinctWay$$holdAcquire(0); g.t.drainCpu();
    g.fillDirty(x); g.fillDirty(y); g.settle();
    check(g.resident(x) && *g.resident(x) != g.committed(x) &&
        g.resident(y) && *g.resident(y) != g.committed(y), "legal setup did not permute both ways");
}
static void train(Gate& g, bool dirty, bool unissued = false) {
    if (dirty) { g.fillDirty(x); g.fillDirty(y); }
    // Cold full stores create history but the real miss barrier cancels PF.
    g.t.cpu({pf-128, true, 0x123456789abcdef0ULL});
    g.t.cpu({pf-64, true, 0xfedcba9876543210ULL}); g.settle();
    check(!g.aFires[pf], "training unexpectedly prefetched target");
    g.hold(false, false, true, true); g.t.d.set_io$$distinctWay$$holdAcquire(unissued);
    const auto rBefore = g.backingReadBeats;
    g.t.cpu({pf-56, true, 0x3141592653589793ULL});
    if (unissued) {
        g.until([&] { return g.t.d.get_io$$acquireOffer() && g.t.d.get_io$$acquireAddress() == pf; }, "PF A not offered");
        g.t.cpuRequest = Request{demand}; const auto accepted = g.t.cpuAccepted, beforeC = uint64_t(g.cBeats[y]); g.ticks(8);
        check(g.t.cpuAccepted == accepted && g.cBeats[y] == beforeC, "unissued PF enabled other-way demand/C");
        g.t.cpuRequest.reset(); g.t.d.set_io$$distinctWay$$holdAcquire(0);
    }
    if (unissued) {
        // Stop after real backing last R, before the home's registered Grant.
        g.until([&] { return g.backingReadBeats == rBefore + 8; }, "PF backing read did not complete");
        g.hold(false, true, true, true);
        g.until([&] { return g.t.d.get_io$$distinctWay$$grantOffer(); }, "held first D not offered");
        g.ticks(4); ++g.coverage["held_first_d"];
        auto beats = [&] { unsigned n = 0; for (const auto& [key, owner] : g.owners)
            if (owner.address == pf) n = owner.beats; return n; };
        g.hold(false, false, true, true); g.until([&] { return beats() == 3; }, "three D beats missing");
        g.hold(false, true, true, true); g.ticks(4); ++g.coverage["held_middle_d"];
        g.hold(false, false, true, true); g.until([&] { return beats() == 7; }, "seven D beats missing");
        g.hold(false, true, true, true); g.ticks(4); ++g.coverage["held_last_d"];
        g.hold(false, false, true, true);
    }
    g.until([&] { return g.t.d.get_io$$grantAckOffer(); }, "PF did not reach held E");
    check(g.aFires[pf] == 1 && !g.eFires[pf], "gate lacks actual PF A and held E");
}

// modes: 0 eight C before E plus holds/reuse; 1 first C/E; 2 last C/E;
// 3 invalid alternate; 4 flush; 5 PF error; 6 demand error.
static void scenario(unsigned mode, unsigned faultMode = 0, unsigned faultBeat = 7) {
    Gate g; const bool dirty = mode != 3;
    if (mode == 5 || mode == 6) {
        const uint64_t address = mode == 5 ? pf : demand;
        g.poisonAddress = uint32_t(address-base); g.poisonBeat = faultBeat;
        g.t.ddr.denyReadAddress = *g.poisonAddress;
        g.t.d.set_io$$distinctWay$$faultMode(faultMode); g.t.d.set_io$$distinctWay$$faultBeat(faultBeat);
    }
    if (mode == 0 || mode == 1 || mode == 2) permuteWays(g);
    train(g, dirty, mode == 0);
    g.cBeats.clear(); g.aFires[demand] = 0;
    // Same-line, resident hit, store miss, uncached, virtual and high-PA alias
    // offers cannot use this exception. They are withdrawn before acceptance.
    auto reject = [&](Request q, bool virt = false) {
        g.t.cpuRequest = q; g.t.d.set_io$$cpu$$request$$bits$$virtualized(virt);
        const auto old = g.t.cpuAccepted; g.ticks(4);
        check(g.t.cpuAccepted == old, "out-of-scope request used distinct-way admission");
        g.t.cpuRequest.reset(); g.t.d.set_io$$cpu$$request$$bits$$virtualized(0);
    };
    reject({pf}); if (dirty) { reject({y}); reject({x}); } reject({demand, true, 0x1234});
    reject({demand, false, 0, 255, true}); reject({demand}, true);
    g.t.d.set_io$$cpu$$request$$bits$$atomic(1); reject({demand}); g.t.d.set_io$$cpu$$request$$bits$$atomic(0);
    reject({demand ^ (1ULL << 55)});
    g.t.d.set_io$$flushRequest(1); reject({demand}); g.t.d.set_io$$flushRequest(0);
    g.t.blockCpu = true; g.t.cpu({pf-128}, false); g.t.cpu({pf-64}, false); g.tick();
    check(g.t.d.get_io$$storePfObs$$responseFull(), "response-full setup lacked both tickets");
    reject({demand}); g.t.blockCpu = false; g.t.drainCpu();
    g.hold(dirty, false, true, true);
    g.t.cpuRequest = Request{demand};
    if (enabled) {
        g.until([&] { return !g.t.cpuRequest; }, "ON demand did not accept beside issued PF");
        if (dirty) {
            g.until([&] { return g.t.d.get_io$$storePfObs$$cValid(); }, "dirty other-way C not offered");
            g.ticks(4); ++g.coverage["held_first_c"]; // held first beat
            if (mode == 1) {
                g.hold(false, false, false, true); g.tick();
                check(g.coverage["first_c_e"] == 1, "first-C/E collision not reached");
            } else {
                g.hold(false, false, true, true);
                g.until([&] { return g.cBeats[y] == 3; }, "first three C beats did not transfer");
                g.hold(true, false, true, true); g.ticks(4); ++g.coverage["held_middle_c"]; // held middle
                g.hold(false, false, true, true);
                g.until([&] { return g.cBeats[y] == 7; }, "first seven C beats did not transfer");
                g.hold(true, false, true, true); g.ticks(4); ++g.coverage["held_last_c"]; // held last
                g.hold(false, false, mode != 2, true); g.tick();
                if (mode == 2) check(g.coverage["last_c_e"] == 1, "last-C/E collision not reached");
            }
            g.until([&] { return g.cBeats[y] == 8; }, "other-way release did not transfer exactly eight beats");
        }
        if (mode != 1 && mode != 2) {
            reject({demand+stride}); // both MSHRs live, despite another response ticket
            g.until([&] { return g.t.d.get_io$$acquireOffer() && g.t.d.get_io$$acquireAddress() == demand; }, "demand A not parked");
            g.ticks(8); check(!g.aFires[demand] && !g.eFires[pf], "same-set demand A crossed held PF E");
            check(g.cBeats[y] == (dirty ? 8U : 0U), "C-before-E dirty/invalid discriminator failed");
        }
    } else {
        g.ticks(24); check(g.t.cpuRequest && !g.cBeats[y] && !g.aFires[demand], "OFF lost original same-set block");
    }
    if (mode == 4) g.t.d.set_io$$flushRequest(1);
    g.hold(false, false, false, true);
    if (mode == 4 && !enabled) g.t.cpuRequest.reset();
    g.t.drainCpu();
    if (mode == 0) {
        // Directory already holds the new demand in the old victim slot. Keep
        // both old cache WB Acks held while two cold reads reuse both MSHRs.
        g.t.blockCpu = true; g.t.cpu({base+9*64}, false); g.t.cpu({base+11*64}, false);
        g.ticks(8); g.hold(false, false, false, false); g.t.blockCpu = false; g.settle();
        check(g.coverage["ack_after_both_reuses"], "late Ack did not cross directory AND MSHR reuse");
    }
    g.hold(false, false, false, false);
    if (mode == 4) {
        g.until([&] { return g.t.d.get_io$$flushDone(); }, "flush could not drain accepted overlap");
        g.t.d.set_io$$flushRequest(0); g.tick();
    }
    g.settle();
    if (mode == 5 || mode == 6) {
        const uint64_t bad = mode == 5 ? pf : demand;
        check(!g.resident(bad), "errored full line installed");
        if (mode == 5 && enabled) check(g.coverage["cache_directory_permutation"], "error/reuse did not permute cache/home way");
        g.poisonAddress.reset(); g.t.ddr.denyReadAddress.reset(); g.t.d.set_io$$distinctWay$$faultMode(0);
        const auto misses = g.t.missCount; g.t.cpu({bad}); check(g.t.missCount > misses, "error retry unexpectedly hit");
    }
    // Verify all eight words, then invoke the real home maintenance/probe path.
    for (unsigned b = 0; b < 8; ++b) { g.t.cpu({pf+b*8}); g.t.cpu({demand+b*8}); }
    g.t.dma({demand}); g.settle(); check(g.coverage["probe_complete"], "real maintenance probe was not exercised");
    const std::string name = "mode" + std::to_string(mode) + "-fault" + std::to_string(faultMode) + "-beat" + std::to_string(faultBeat);
    g.finish(name.c_str());
}
static void cleanOtherWay() {
    Gate g; g.fillDirty(x); g.t.cpu({y}); g.settle(); train(g, false);
    g.cBeats.clear(); g.t.cpuRequest = Request{demand};
    if (enabled) {
        g.until([&] { return !g.t.cpuRequest; }, "clean-alternate demand not admitted");
        g.until([&] { return g.t.d.get_io$$storePfObs$$cValid(); }, "clean Release not offered");
        check(g.t.d.get_io$$storePfObs$$cOpcode() == 6, "clean alternate offered ReleaseData");
    }
    g.ticks(12); check(!g.cBeats[y] && !g.eFires[pf] && !g.aFires[demand], "clean C bypassed PF E");
    g.hold(false, false, false, false); g.t.drainCpu(); g.settle();
    check(g.cBeats[y] == 1, "clean alternate did not issue exactly one Release after E");
    g.finish("clean-other-way-keeps-E-gate");
}
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--mutate-directory") {
            distinct_way::Gate g; g.mutateDirectory = true; g.t.cpu({base+128}); g.ticks(2);
            check(false, "directory identity mutation was not rejected");
        }
        for (unsigned mode = 0; mode <= 4; ++mode) distinct_way::scenario(mode);
        distinct_way::cleanOtherWay();
        for (unsigned mode : {5U, 6U}) for (unsigned kind : {1U, 2U}) for (unsigned beat : {0U, 3U, 7U})
            distinct_way::scenario(mode, kind, beat);
        std::cout << "DISTINCT_WAY_RELEASE_PASS on=" << distinct_way::enabled << " cases=18 performance_qualification=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "DISTINCT_WAY_RELEASE_FAIL " << error.what() << '\n'; return 1;
    }
}
