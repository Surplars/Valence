// Real cache + Mixed coherent home + AXI. No DUT token/selector is used as an
// oracle: residency, origin and replacement order come from authored requests
// and completed protocol events. Build each explicit OFF/ON model separately.
#ifndef SPLIT_PREFETCH_TRACKING
#error "explicit SPLIT_PREFETCH_TRACKING=0|1 must match the generated model"
#endif
#if SPLIT_PREFETCH_TRACKING != 0 && SPLIT_PREFETCH_TRACKING != 1
#error "SPLIT_PREFETCH_TRACKING must be 0 or 1"
#endif
#ifndef STORE_PF_LRU_ON
#error "explicit STORE_PF_LRU_ON=0|1 must match the generated model"
#endif
#if STORE_PF_LRU_ON != 0 && STORE_PF_LRU_ON != 1
#error "STORE_PF_LRU_ON must be 0 or 1"
#endif
#ifndef CACHE_WAYS
#define CACHE_WAYS 2
#endif
#ifndef PF_CANDIDATE_CYCLES
#define PF_CANDIDATE_CYCLES 1
#endif
#ifndef CACHE_BASE
#define CACHE_BASE 0x1000080010000ULL
#endif
#define MIXED_MODEL 1
#define MIXED_RTL 1
#define CACHE_HOME_EMBED
#include "coherent_cache_home.cpp"
#include <array>
#include <filesystem>
#include <fstream>

namespace dual_prefetch {
static_assert(CACHE_LINES == 512 && READ_MSHRS == 2 && RESPONSE_ENTRIES == 2);
static_assert(CACHE_WAYS == 1 || CACHE_WAYS == 2);
static_assert(PF_CANDIDATE_CYCLES == 1 || PF_CANDIDATE_CYCLES == 16);
constexpr bool split = SPLIT_PREFETCH_TRACKING != 0, lru = STORE_PF_LRU_ON != 0;
constexpr unsigned sets = CACHE_LINES / CACHE_WAYS;
constexpr uint64_t stride = uint64_t(sets) * 64;
static uint64_t line(uint64_t a) { return a & ~63ULL; }
static unsigned set(uint64_t a) { return unsigned((a / 64) % sets); }
using Key = std::pair<unsigned, uint64_t>;
using Words = std::array<uint64_t, 8>;
struct Resident { bool valid = false, dirty = false; uint64_t address = 0; };
struct Token { uint64_t address; unsigned index; bool store; };
struct Choice { unsigned index = 0; Resident victim{}; bool allowed = false; };
struct Owner {
    Key key{}; uint64_t address = 0; Choice choice{};
    bool pf = false, store = false, acquired = false, acked = false, filled = false, error = false;
    unsigned beats = 0, sink = 0; Words expected{};
};
struct Wb {
    Key key{}; uint64_t address = 0; bool pf = false, dirty = false, sent = false;
    unsigned beats = 0; Words expected{};
};
std::string imageDirectory, mutation;
bool mutationTriggered = false;
unsigned completedCases = 0;

struct Gate {
    Test t;
    std::array<Resident, CACHE_LINES> resident{};
    std::array<unsigned, sets> oldest{};
    // OFF has one shared token in slot zero. ON slot zero is read-origin and
    // slot one store-origin. The immutable origin survives MSHR and way reuse.
    std::array<std::optional<Token>, 2> token{};
    std::array<std::optional<Key>, 2> active{};
    std::array<uint64_t, 2> generations{};
    std::map<Key, Owner> owners;
    std::array<std::optional<Wb>, 2> wb{};
    std::map<unsigned, Key> sources;
    std::map<std::string, uint64_t> counts;
    std::optional<Request> offered;
    std::optional<std::pair<uint64_t, bool>> candidate;
    std::optional<std::tuple<unsigned, unsigned, unsigned, unsigned, uint64_t, uint64_t>> heldC;
    std::optional<unsigned> heldE;
    uint64_t accepted = 0;
    bool flushing = false, authorized = true;
    bool lastHit = false, lastMiss = false;

    Gate() { t.readyAlways = true; t.observer = [&] { observe(); }; tick(); }
    uint64_t n(const std::string& key) const {
        const auto i = counts.find(key); return i == counts.end() ? 0 : i->second;
    }
    Words words(uint64_t address) const {
        Words result{};
        for (unsigned i = 0; i < 8; ++i) result[i] = t.architectural.at(line(address) + i * 8);
        return result;
    }
    bool present(const std::optional<Token>& value) const {
        return value && resident.at(value->index).valid &&
            resident.at(value->index).address == value->address;
    }
    std::optional<unsigned> find(uint64_t address) const {
        for (unsigned way = 0; way < CACHE_WAYS; ++way) {
            const unsigned index = way * sets + set(address);
            if (resident[index].valid && resident[index].address == line(address)) return index;
        }
        return std::nullopt;
    }
    Choice choose(uint64_t address, bool pf, bool store, unsigned consumed = 0) const {
        std::array<bool, CACHE_WAYS> allowed{};
        for (unsigned way = 0; way < CACHE_WAYS; ++way) {
            const unsigned index = way * sets + set(address);
            const auto& r = resident[index];
            const unsigned other = store ? 0 : 1;
            const bool protectedLine = pf && split && present(token[other]) && !(consumed & (1U << other)) &&
                token[other]->index == index && token[other]->address == r.address;
            bool reserved = false;
            for (const auto& owner : active) if (owner)
                reserved |= owners.at(*owner).choice.index == index;
            // Independent demand admission reserves physical ways. PF retains
            // its separate whole-set admission gate, checked at allocation.
            allowed[way] = !protectedLine && (pf || !reserved) && (!pf || store || !r.valid || !r.dirty);
        }
        const auto result = [&](unsigned way) {
            const unsigned index = way * sets + set(address);
            return Choice{index, resident[index], allowed[way]};
        };
        for (unsigned way = 0; way < CACHE_WAYS; ++way)
            if (allowed[way] && !resident[way * sets + set(address)].valid) return result(way);
        if (pf && !(store && lru)) {
            for (unsigned way = 0; way < CACHE_WAYS; ++way)
                if (allowed[way] && !resident[way * sets + set(address)].dirty) return result(way);
        }
        if (allowed[oldest[set(address)]]) return result(oldest[set(address)]);
        for (unsigned way = 0; way < CACHE_WAYS; ++way) if (allowed[way]) return result(way);
        return {};
    }
    void tick() { t.tick(); }
    void ticks(unsigned count) { while (count--) tick(); }
    template<class P> void until(P p, const char* why, unsigned budget = 8192) { t.until(p, why, budget); }
    void begin(Request q) {
        check(!offered && !t.cpuRequest, "overwriting authored CPU offer");
        offered = q; t.cpuRequest = q;
    }
    void send(Request q, bool wait = true) {
        begin(q); until([&] { return !offered; }, "CPU request did not accept");
        if (wait) until([&] { return t.cpuExpected.empty(); }, "CPU reply did not retire");
    }
    void store(uint64_t address, unsigned mask = 255, bool wait = true) {
        send({address, true, 0x7192a3b4c5d6e7f8ULL ^ (address * 17), mask}, wait);
    }
    void dma(Request q) {
        check(!t.dmaRequest, "overwriting authored DMA offer"); t.dmaRequest = q;
        until([&] { return !t.dmaRequest && t.dmaExpected.empty(); }, "real DMA/probe did not complete");
    }
    void permission(bool allow) {
        authorized = allow;
        t.d.set_io$$prefetchPmpCfg(allow ? 0x1f : 0x18);
        t.d.set_io$$prefetchPrivilege(allow ? 3 : 1);
    }
    void prepare(uint64_t target, bool storeOrigin) {
        check(target >= base + 128 && target + 64 <= base + BOARD_DDR_BYTES &&
              ((target - 64) & 4095) < 4032, "invalid authored prediction target");
        // Partial stores establish residency without authorizing a prediction.
        store(target - 128, 0x55); store(target - 64, 0xaa);
        if (storeOrigin) store(target - 128); else send({target - 128});
        settle();
    }
    void trigger(uint64_t target, bool storeOrigin, bool wait = true) {
        if (storeOrigin) store(target - 64, 255, wait); else send({target - 64}, wait);
    }
    void hold(bool c, bool d, bool e, bool ack) {
        t.d.set_io$$holdCoherentC(c); t.d.set_io$$holdCoherentD(d);
        t.d.set_io$$holdGrantAck(e); t.d.set_io$$holdReleaseAck(ack);
    }
    void settle() {
        until([&] { return !offered && !t.cpuRequest && t.cpuExpected.empty() &&
            !t.dmaRequest && t.dmaExpected.empty() && !active[0] && !active[1] &&
            !wb[0] && !wb[1] && sources.empty() && !t.d.get_io$$prefetchBusy(); },
            "accepted CPU/PF/WB/DMA ownership did not drain");
        ticks(2);
    }
    void startFlush() { flushing = true; t.d.set_io$$flushRequest(1); }
    void finishFlush() {
        until([&] { return t.d.get_io$$flushDone(); }, "cache/home flush did not drain");
        // This cache flush writes dirty lines back and preserves clean lines
        // and replacement order. Only actual capture/probe events invalidate.
        t.d.set_io$$flushRequest(0); flushing = false; tick();
        check(!present(token[0]) && !present(token[1]), "flush retained a resident token");
        for (const auto& [a, value] : t.architectural)
            check(t.ddr.memory.at(uint32_t(a - base)) == value, "full flush independent backing mismatch");
        check(t.grants.empty() && !t.releasePending && t.ddr.pendingReads.empty() &&
              !t.ddr.writing && !t.ddr.responding, "flush completed before real traffic drained");
    }
    void finish(const char* name) {
        hold(false, false, false, false); settle(); startFlush(); finishFlush(); ticks(2);
        check(t.cpuAccepted == t.cpuReturned && t.dmaAccepted == t.dmaReturned &&
              !heldC && !heldE && sources.empty() && !wb[0] && !wb[1], "final owner accounting differs");
        if (!imageDirectory.empty()) {
            std::filesystem::create_directories(imageDirectory);
            const auto stem = imageDirectory + "/" + name;
            std::ofstream expected(stem + "-expected.bin", std::ios::binary);
            std::ofstream actual(stem + "-actual.bin", std::ios::binary);
            for (uint64_t offset = 0; offset < BOARD_DDR_BYTES; offset += 8) {
                const auto e = t.architectural.at(base + offset), a = t.ddr.memory.at(uint32_t(offset));
                for (unsigned byte = 0; byte < 8; ++byte) {
                    expected.put(char(e >> (8 * byte))); actual.put(char(a >> (8 * byte)));
                }
            }
            check(bool(expected) && bool(actual), "full-image evidence write failed");
        }
        ++completedCases;
        std::cout << "DUAL_PREFETCH_TRACKING_CASE name=" << name << " split=" << split
            << " store_lru=" << lru << " ways=" << CACHE_WAYS << " lifetime=" << PF_CANDIDATE_CYCLES
            << " cycles=" << t.cycles << " cpu_accept=" << t.cpuAccepted << " cpu_reply=" << t.cpuReturned
            << " axi_ar=" << t.ddr.reads << " axi_r=" << t.ddr.rBeats << " axi_aw=" << t.ddr.writes
            << " axi_w=" << t.ddr.wBeats << " axi_b=" << t.ddr.bResponses;
        for (const auto& [key, value] : counts) std::cout << ' ' << key << '=' << value;
        std::cout << " actual_cache_home=1 full_pa=1 full_flush=1 executing_cpu=0 performance_qualification=0\n";
    }
    void allocate(unsigned slot, uint64_t address, bool pf, bool store, Choice selected) {
        check(slot < 2 && !active[slot] && selected.allowed, "allocation lacks a free independently allowed slot");
        for (const auto& other : active) if (other) {
            check(owners.at(*other).choice.index != selected.index, "two MSHRs reserve one physical way");
            if (pf) check(set(owners.at(*other).address) != set(address), "PF crossed its whole-set reservation gate");
        }
        Owner o; o.key = {slot, ++generations[slot]}; o.address = line(address);
        o.pf = pf; o.store = store; o.choice = selected; o.expected = words(address);
        owners.emplace(o.key, o); active[slot] = o.key;
        ++counts[pf ? (store ? "store_alloc" : "read_alloc") : "demand_alloc"];
    }
    void observe() {
        auto& d = t.d;
        std::optional<std::pair<unsigned, unsigned>> refillReplacement;
#define O(field) d.get_io$$storePfObs$$##field()
        check(bool(O(trackingSplitEnabled)) == split, "generated tracking mode differs from explicit host mode");
        const unsigned live = O(mshrLiveMask), pf = O(mshrPrefetchMask);
        check((live | pf | unsigned(O(wbLiveMask))) < 4, "actual owner resources exceed two entries");
        check((live & pf) != 3, "more than one global speculative MSHR exists");
        for (unsigned i = 0; i < 2; ++i) {
            if (active[i] && !(live & (1U << i))) {
                check(owners.at(*active[i]).filled, "MSHR retired before refill"); active[i].reset();
            }
            check(bool(live & (1U << i)) == bool(active[i]), "actual MSHR lost allocation generation");
            if (active[i]) {
                const auto& o = owners.at(*active[i]);
                check(bool(pf & (1U << i)) == o.pf && (!o.pf ||
                    bool(O(mshrStoreMask) & (1U << i)) == o.store), "MSHR origin changed after allocation");
            }
            check(bool(O(wbLiveMask) & (1U << i)) == bool(wb[i]), "WB lifetime differs from capture/Ack history");
            if (wb[i]) check(bool(O(wbPrefetchMask) & (1U << i)) == wb[i]->pf &&
                bool(O(wbSentMask) & (1U << i)) == wb[i]->sent &&
                (i ? O(wbAddress1) : O(wbAddress0)) == wb[i]->address,
                "saved WB origin/address changed during MSHR reuse");
        }
        const bool fire = t.cpuAccepted != accepted;
        check(t.cpuAccepted == accepted + unsigned(fire) && (!fire || offered), "CPU acceptance lacks authored request");
        unsigned consumed = 0;
        for (unsigned i = 0; i < 2; ++i) {
            const bool effective = present(token[i]);
            const bool observed = i ? O(storeTokenValid) : O(readTokenValid);
            uint64_t observedAddress = i ? O(storeTokenAddress) : O(readTokenAddress);
            const unsigned observedIndex = i ? O(storeTokenIndex) : O(readTokenIndex);
            if (!mutationTriggered && mutation == "token-address" && effective) {
                observedAddress ^= 1ULL << 40; mutationTriggered = true;
                std::cerr << "DUAL_PREFETCH_TRACKING_MUTATION_TRIGGER token-address\n";
            }
            check(observed == effective, "resident token validity differs from completed full-PA residency");
            if (effective) check(observedAddress == token[i]->address && observedIndex == token[i]->index,
                "resident token full PA/index differs from immutable refill origin");
            const bool use = fire && effective && line(offered->address) == token[i]->address;
            check(bool(i ? O(storeTokenConsume) : O(readTokenConsume)) == use,
                "token consumed without accepted matching full-PA demand");
            if (use) consumed |= 1U << i;
            if (token[i] && !effective) token[i].reset();
        }
        counts["dual_resident_samples"] += present(token[0]) && present(token[1]);
        check(bool(O(useful)) == bool(consumed) && bool(d.get_io$$prefetchEvents$$useful()) == bool(consumed),
            "useful event differs from independent resident-token consumption");
        if (consumed) {
            const unsigned i = consumed & 1 ? 0 : 1;
            bool origin = O(usefulStore);
            if (!mutationTriggered && mutation == "token-origin") {
                origin = !origin; mutationTriggered = true;
                std::cerr << "DUAL_PREFETCH_TRACKING_MUTATION_TRIGGER token-origin\n";
            }
            check(origin == token[i]->store, "useful event changed immutable refill origin");
            ++counts[token[i]->store ? "store_useful" : "read_useful"];
        }
        if (O(pendingCandidateValid)) {
            check(candidate && candidate->first == O(pendingCandidateAddress) &&
                candidate->second == bool(O(pendingCandidateStore)), "pending candidate changed authored full PA/origin");
            const auto address = candidate->first; const auto selected = choose(address, true, candidate->second, consumed);
            check(O(pendingCandidateSet) == set(address) && O(candidateReplacementWay) == oldest[set(address)],
                "candidate set/LRU differs from independent completed access order");
            for (unsigned way = 0; way < CACHE_WAYS; ++way) {
                const auto& r = resident[way * sets + set(address)];
                check(bool(way ? O(candidateWay1Valid) : O(candidateWay0Valid)) == r.valid &&
                    bool(way ? O(candidateWay1Dirty) : O(candidateWay0Dirty)) == (r.valid && r.dirty) &&
                    (!r.valid || (way ? O(candidateWay1Address) : O(candidateWay0Address)) == r.address),
                    "candidate full-PA way snapshot differs from authored residency");
            }
            check(bool(O(candidateVictimAllowed)) == selected.allowed,
                "candidate admissibility differs from independent cross-origin protection");
            ++counts[selected.allowed ? "candidate_allowed" : "candidate_no_victim"];
            if (selected.allowed) {
                unsigned index = O(candidateVictimIndex);
                if (!mutationTriggered && mutation == "victim" && split && present(token[0]) && candidate->second &&
                    set(token[0]->address) == set(candidate->first)) {
                    index = token[0]->index; mutationTriggered = true;
                    std::cerr << "DUAL_PREFETCH_TRACKING_MUTATION_TRIGGER victim\n";
                }
                check(index == selected.index && bool(O(candidateVictimValid)) == selected.victim.valid &&
                    bool(O(candidateVictimDirty)) == (selected.victim.valid && selected.victim.dirty) &&
                    (!selected.victim.valid || O(candidateVictimAddress) == selected.victim.address),
                    "candidate selected protected or wrong full-PA victim");
            }
        } else candidate.reset();
        if (O(candidate)) {
            check(fire && offered && authorized && (offered->address & 4095) < 4032 &&
                bool(O(candidateStore)) == offered->write && (!offered->write || offered->mask == 255),
                "candidate lacks authored authorized source request");
            const unsigned own = split && offered->write ? 1 : 0;
            check(!present(token[own]) || (consumed & (1U << own)), "prediction overwrote its live origin token");
            candidate = std::pair{line(offered->address) + 64, offered->write};
            ++counts[offered->write ? "store_candidate" : "read_candidate"];
        }
        if (O(demandAlloc)) {
            check(fire && line(offered->address) == line(O(demandAllocAddress)), "demand owner lacks original request");
            allocate(O(demandAllocSlot), offered->address, false, offered->write, choose(offered->address, false, offered->write));
        }
        if (O(allocated)) {
            check(candidate && candidate->first == O(allocatedAddress) && candidate->second == bool(O(allocatedStore)),
                "prefetch allocation changed captured candidate");
            const auto selected = choose(candidate->first, true, candidate->second, consumed);
            check(selected.allowed && O(allocatedIndex) == selected.index &&
                bool(O(allocatedVictimValid)) == selected.victim.valid &&
                bool(O(allocatedVictimDirty)) == (selected.victim.valid && selected.victim.dirty) &&
                (!selected.victim.valid || O(allocatedVictimAddress) == selected.victim.address),
                "prefetch allocation selected disallowed/wrong full-PA victim");
            allocate(O(allocatedSlot), candidate->first, true, candidate->second, selected);
        }
        for (unsigned i = 0; i < 2; ++i) if (consumed & (1U << i)) token[i].reset();
        if (O(wbCapture)) {
            const unsigned slot = O(wbCaptureSlot), index = O(wbCaptureIndex), m = O(wbCaptureMshr);
            check(slot < 2 && !wb[slot] && resident[index].valid &&
                resident[index].address == O(wbCaptureAddress) && resident[index].dirty == bool(O(wbCaptureDirty)),
                "WB capture changed independent victim bytes/identity");
            Wb w; w.address = O(wbCaptureAddress); w.dirty = O(wbCaptureDirty); w.expected = words(w.address);
            if (O(wbCaptureFromMiss)) {
                check(m < 2 && active[m], "WB capture lacks originating MSHR generation");
                w.key = *active[m]; const auto& o = owners.at(w.key); w.pf = o.pf;
                check(o.choice.index == index && o.choice.victim.address == w.address &&
                    (!w.pf || !w.dirty || o.store), "captured victim changed allocation or read PF released dirty data");
            }
            check(bool(O(wbCapturePrefetch)) == w.pf, "WB capture inherited stale MSHR prefetch origin");
            resident[index] = {}; wb[slot] = w;
            ++counts[w.pf && w.dirty ? "dirty_pf_capture" : "other_capture"];
        }
        if (O(cValid)) {
            const unsigned op = O(cOpcode), source = d.get_io$$releaseSource();
            const auto payload = std::tuple{op, unsigned(O(cParam)), unsigned(O(cSize)), source,
                uint64_t(d.get_io$$releaseAddress()), uint64_t(O(cData))};
            if (heldC) check(payload == *heldC, "held C payload changed");
            if (!O(cReady)) { heldC = payload; ++counts["held_c_samples"]; } else heldC.reset();
            if (op == 6 || op == 7) {
                check(source >= 2 && source < 4 && wb[source - 2], "C lacks saved WB owner");
                auto& w = *wb[source - 2];
                check(w.address == d.get_io$$releaseAddress() && !w.sent && (op == 7) == w.dirty &&
                    O(cSize) == 6 && O(cParam) == 1, "C changed saved release identity");
                if (w.dirty) check(w.beats < 8 && O(cData) == w.expected[w.beats], "dirty release byte oracle mismatch");
                if (O(cReady)) {
                    ++w.beats; ++counts["release_beats"]; counts["dirty_pf_beats"] += w.pf && w.dirty;
                    w.sent = w.beats == (w.dirty ? 8U : 1U);
                }
            }
        } else check(!heldC, "held C valid disappeared");
        if (d.get_io$$releaseAckFire()) {
            const unsigned source = d.get_io$$releaseAckSource();
            check(source >= 2 && source < 4 && wb[source - 2] && wb[source - 2]->sent,
                "ReleaseAck preceded its full saved C release");
            counts["dirty_pf_acks"] += wb[source - 2]->pf && wb[source - 2]->dirty;
            wb[source - 2].reset();
        }
        if (d.get_io$$acquireFire()) {
            const unsigned source = d.get_io$$acquireSource();
            check(!sources.count(source), "A source reused before E");
            std::optional<Key> key;
            for (const auto& a : active) if (a) {
                const auto& o = owners.at(*a);
                if (!o.acquired && o.address == d.get_io$$acquireAddress()) {
                    check(!key, "A matches ambiguous allocation generations"); key = a;
                }
            }
            check(bool(key), "A lacks captured allocation identity");
            auto& o = owners.at(*key); o.acquired = true; sources[source] = *key;
            ++counts[o.pf ? "pf_acquire" : "demand_acquire"];
        }
        if (d.get_io$$grantFire()) {
            const unsigned source = d.get_io$$grantSource(); check(sources.count(source), "D lacks A owner");
            auto& o = owners.at(sources.at(source));
            if (!o.beats) o.sink = d.get_io$$grantSink();
            check(o.beats < 8 && o.sink == d.get_io$$grantSink(), "D changed owner sink/beat");
            o.error |= O(dDenied) || O(dCorrupt);
            if (o.pf && !o.error) check(O(dData) == o.expected[o.beats], "prefetch D byte oracle mismatch");
            ++o.beats;
        }
        if (d.get_io$$grantAckOffer()) {
            const unsigned sink = d.get_io$$grantAckSink();
            if (heldE) check(*heldE == sink, "held E sink changed");
            if (!d.get_io$$grantAckFire()) { heldE = sink; ++counts["held_e_samples"]; } else heldE.reset();
        } else check(!heldE, "held E valid disappeared");
        if (d.get_io$$grantAckFire()) {
            auto found = sources.end();
            for (auto i = sources.begin(); i != sources.end(); ++i) {
                const auto& o = owners.at(i->second);
                if (o.beats == 8 && o.sink == d.get_io$$grantAckSink()) {
                    check(found == sources.end(), "E matches ambiguous D owners"); found = i;
                }
            }
            check(found != sources.end(), "E lacks completed D owner");
            owners.at(found->second).acked = true; sources.erase(found);
        }
        if (O(refill)) {
            const unsigned slot = O(refillSlot); check(slot < 2 && active[slot], "refill lacks allocated MSHR generation");
            auto& o = owners.at(*active[slot]);
            check(o.beats == 8 && o.acked && !o.filled && o.address == line(O(refillAddress)) &&
                o.choice.index == O(refillIndex) && o.pf == bool(O(refillPrefetch)) && o.error == bool(O(refillError)),
                "refill lost immutable origin/full PA/index/error");
            o.filled = true;
            counts["opposite_consume_refill"] += split && o.pf &&
                bool(consumed & (o.store ? 1U : 2U));
            counts["pf_refill_under_flush"] += o.pf && flushing;
            check(bool(O(installValid)) == !o.error, "failed refill installed a line");
            if (!o.error) {
                const unsigned index = o.choice.index, way = index / sets;
                check(!resident[index].valid && O(installIndex) == index && line(O(installAddress)) == o.address &&
                    bool(O(installDirty)) == (!o.pf && o.store), "installation changed independently selected way");
                resident[index] = {true, !o.pf && o.store, o.address};
                refillReplacement = std::pair{set(o.address), CACHE_WAYS == 1 ? 0U :
                    (o.pf && !o.store ? way : 1 - way)};
                if (o.pf) token[split && o.store ? 1 : 0] = Token{o.address, index, o.store};
            }
            if (o.pf) ++counts[o.error ? "pf_error" : "pf_install"];
        }
        if (d.get_io$$probeFire()) {
            if (const auto index = find(d.get_io$$probeAddress())) resident[*index] = {};
            ++counts["real_probe"];
        }
        if (fire) {
            lastHit = d.get_io$$hit(); lastMiss = d.get_io$$miss();
            if (lastHit) {
                const auto index = find(offered->address); check(bool(index), "accepted hit lacks full-PA independent residency");
                resident[*index].dirty |= offered->write;
                oldest[set(offered->address)] = CACHE_WAYS == 1 ? 0 : 1 - *index / sets;
            }
            offered.reset(); accepted = t.cpuAccepted;
        }
        // A refill's replacement update is later than accepted-hit touch in
        // the real cache. This matters when independent demand admission lets
        // a hit in the other way share the refill's set on the same edge.
        if (refillReplacement) oldest[refillReplacement->first] = refillReplacement->second;
        if (flushing) { token = {}; candidate.reset(); }
#undef O
    }
};

static void requireTokens(const Gate& g, uint64_t read, uint64_t store = 0) {
    check(g.present(g.token[0]) && g.token[0]->address == read && !g.token[0]->store,
        "read-origin resident token is missing");
    check(g.present(g.token[1]) == bool(split && store), "opposite-origin resident token availability differs");
    if (split && store) check(g.token[1]->address == store && g.token[1]->store,
        "store-origin token changed full physical address");
}

static void dual_residency(bool sameSet) {
    Gate g; const uint64_t r = base + 128, s = r + (sameSet ? stride : 1024);
    g.prepare(r, false); g.prepare(s, true);
    g.trigger(r, false); g.settle(); requireTokens(g, r);
    const auto stores = g.n("store_candidate");
    g.trigger(s, true); g.settle(); requireTokens(g, r, s);
    check(g.n("read_alloc") == 1 && g.n("store_alloc") == unsigned(split) &&
        g.n("store_candidate") == stores + unsigned(split), "OFF/ON cross-origin candidate gate differs");
    if (split && sameSet) check(g.token[0]->index != g.token[1]->index &&
        set(g.token[0]->address) == set(g.token[1]->address), "dual same-set tokens did not occupy different ways");
    // Repeating either source cannot overwrite that origin's unconsumed token.
    const auto allocated = g.n("pf_acquire"); g.trigger(s, true); g.settle();
    check(g.n("pf_acquire") == allocated, "same-origin source overwrote a resident token");
    g.permission(false); g.send({r}); check(g.lastHit, "read token did not produce useful hit");
    g.send({s}); check(g.lastHit == split && g.lastMiss == !split, "store token OFF/ON hit behavior differs");
    g.settle(); check(g.n("read_useful") == 1 && g.n("store_useful") == unsigned(split),
        "each installed origin token was not consumed exactly once");
    g.finish(sameSet ? "dual_same_set_different_way" : "dual_distinct_sets");
}

static void protected_dirty_release() {
    Gate g; const uint64_t r = base + 128, dirty = r + stride, s = r + 2 * stride;
    for (unsigned word = 0; word < 8; ++word) g.store(dirty + 8 * word, word & 1 ? 0xaa : 0x55);
    g.prepare(r, false); g.prepare(s, true); g.trigger(r, false); g.settle(); requireTokens(g, r);
    const auto c = g.n("release_beats"), replies = g.t.cpuReturned;
    g.hold(true, false, false, true); g.trigger(s, true);
    if (split) {
        g.until([&] { return g.n("dirty_pf_capture") == 1; }, "protected read token prevented eligible dirty victim capture");
        g.until([&] { return g.t.d.get_io$$storePfObs$$cValid(); }, "dirty PF victim did not offer C");
        g.ticks(5); check(g.n("release_beats") == c, "held dirty release advanced");
        g.hold(false, false, false, true);
        g.until([&] { return g.n("release_beats") == c + 3; }, "dirty PF did not reach middle C beat");
        g.hold(true, false, false, true); g.ticks(3);
        check(g.n("release_beats") == c + 3, "held middle dirty C beat advanced");
        g.hold(false, false, false, true);
        g.until([&] { return g.n("pf_install") == 2 && !g.active[0] && !g.active[1]; },
            "PF refill did not retire while its ReleaseAck was held");
        requireTokens(g, r, s); g.ticks(4);
        check(g.n("dirty_pf_beats") == 8 && !g.n("dirty_pf_acks") && g.t.d.get_io$$prefetchBusy(),
            "dirty PF lost eight-beat Release/held-Ack cost after MSHR retirement");
    } else { g.ticks(20); requireTokens(g, r); check(!g.n("store_alloc"), "OFF acquired a second token"); }
    check(g.t.cpuReturned == replies + 1, "prefetch invented or lost CPU responses");
    g.hold(false, false, false, false); g.settle();
    check(g.n("dirty_pf_acks") == unsigned(split), "dirty prefetch ReleaseAck accounting differs");
    g.finish("cross_protection_dirty_release_ack");
}

static void no_allowed_victim() {
    Gate g; const uint64_t s = base + 128, dirty = s + stride, r = s + 2 * stride;
    g.store(dirty, 0x55); g.prepare(r, false); g.prepare(s, true);
    g.trigger(s, true); g.settle();
    check(g.n("store_alloc") == 1, "store token setup failed");
    g.trigger(r, false); g.settle();
    check(!g.n("read_alloc") && !g.t.d.get_io$$prefetchBusy() &&
        g.n("candidate_no_victim") == unsigned(split), "read PF evicted dirty/protected way or failed to cancel");
    g.permission(false); g.send({r}); g.settle(); check(g.lastMiss, "normal demand was blocked by token protection");
    g.finish("read_no_allowed_victim_demand_progress");
}

static void probe_and_way_reuse() {
    Gate g; const uint64_t r = base + 128, s = r + stride, replacement = r + 2 * stride;
    g.prepare(r, false); g.prepare(s, true); g.trigger(r, false); g.settle();
    g.trigger(s, true); g.settle(); requireTokens(g, r, s);
    const auto probes = g.n("real_probe"); g.dma({r}); g.settle();
    check(g.n("real_probe") == probes + 1 && !g.present(g.token[0]) &&
        g.present(g.token[1]) == split, "real probe cleared wrong same-set origin token");
    g.permission(false); g.send({replacement}); g.settle();
    check(!g.n("read_useful") && !g.n("store_useful") && g.present(g.token[1]) == split,
        "full-PA way reuse consumed or cleared other-way token");
    g.send({r}); g.settle();
    check(!g.n("read_useful") && !g.n("store_useful"), "reloaded old full PA falsely consumed a reused token");
    // Demand LRU is intentionally unrestricted: by this point it has evicted
    // the remaining token or the replacement in ordinary access order.
    g.send({s}); g.settle();
    check(!g.n("store_useful"), "demand eviction left stale useful token after same-index remap");
    g.finish("probe_full_pa_way_reuse");
}

static void refill_error_preserves_other() {
    Gate g; const uint64_t r = base + 128, s = r + 1024;
    g.prepare(r, false); g.prepare(s, true); g.trigger(r, false); g.settle();
    g.t.ddr.denyReadAddress = uint32_t(s - base); g.trigger(s, true); g.settle();
    requireTokens(g, r); check(g.n("pf_error") == unsigned(split), "real AXI failed PF error path missing");
    g.permission(false); g.send({s}); g.settle(); requireTokens(g, r);
    check(g.lastMiss && !g.n("store_useful"), "failed prefetch installed a useful resident token");
    g.t.ddr.denyReadAddress.reset(); g.send({r}); g.settle();
    check(g.n("read_useful") == 1, "failed other-origin refill cleared surviving read token");
    g.finish("failed_refill_preserves_other_origin");
}

static void flush_during_refill() {
    Gate g; const uint64_t r = base + 128, s = r + 1024;
    g.prepare(r, false); g.prepare(s, true); g.trigger(r, false); g.settle();
    g.hold(false, false, true, false); g.trigger(s, true);
    if (split) {
        g.until([&] { return g.t.d.get_io$$grantAckOffer(); }, "second-origin PF did not reach held E");
        g.startFlush(); g.ticks(3);
        check(!g.t.d.get_io$$flushDone() && g.n("held_e_samples"), "flush passed accepted held PF GrantAck");
    } else g.startFlush();
    g.hold(false, false, false, false); g.finishFlush(); g.settle();
    check(!g.present(g.token[0]) && !g.present(g.token[1]), "refill resurrected a token under flush");
    check(g.n("pf_refill_under_flush") == unsigned(split), "flush/refill priority coverage was vacuous");
    g.permission(false); g.send({r}); g.send({s}); g.settle();
    check(!g.n("read_useful") && !g.n("store_useful"), "flush retained stale useful origins");
    g.finish("flush_overrides_accepted_prefetch_refill");
}

static void consume_during_other_refill() {
    Gate g; const uint64_t r = base + 128, s = r + 1024;
    g.prepare(r, false); g.prepare(s, true); g.trigger(r, false); g.settle();
    g.hold(false, false, true, false); g.trigger(s, true);
    if (split) {
        g.until([&] { return g.t.d.get_io$$grantAckOffer(); }, "other-origin PF did not reach held E");
        g.hold(false, false, false, false);
        g.until([&] { return g.t.d.get_io$$grantAckFire(); }, "other-origin PF E did not retire");
    } else g.hold(false, false, false, false);
    // The real acquire engine becomes complete on E, making its response
    // available on the following edge. A disjoint read hit may accept then.
    g.permission(false); g.send({r}); g.settle();
    check(g.n("read_useful") == 1 && !g.present(g.token[0]) && g.present(g.token[1]) == split &&
        g.n("opposite_consume_refill") == unsigned(split), "same-edge old-token consume lost fresh opposite refill");
    g.send({s}); g.settle();
    check(g.n("store_useful") == unsigned(split), "same-edge fresh token did not remain useful");
    g.finish("consume_read_token_during_store_refill");
}

static void cancel_candidate(bool flush) {
    Gate g; const uint64_t target = base + 128;
    g.prepare(target, true); g.trigger(target, true, false);
    check(g.n("store_candidate") == 1, "cancellation lacked actual accepted candidate");
    if (flush) g.startFlush(); else g.begin({target});
    g.tick(); check(!g.n("store_alloc"), "candidate crossed actual demand/flush barrier");
    if (flush) g.finishFlush();
    g.settle(); check(!g.n("store_alloc"), "canceled candidate appeared later");
    g.finish(flush ? "cancel_pending_candidate_flush" : "cancel_pending_candidate_demand");
}

static void one_way_veto() {
    Gate g; const uint64_t r = base + 128, s = r + stride;
    g.prepare(r, false); g.trigger(r, false); g.settle(); requireTokens(g, r);
    g.prepare(s, true);
    g.trigger(s, true); g.settle(); requireTokens(g, r);
    check(!g.n("store_alloc") && g.n("candidate_no_victim") == unsigned(split),
        "one-way opposite-origin veto allocated or failed bounded cancellation");
    g.permission(false); g.send({s}); g.settle();
    check(g.lastMiss && !g.present(g.token[0]), "one-way normal demand could not evict protected token");
    g.finish("one_way_opposite_token_veto");
}
} // namespace dual_prefetch

int main(int argc, char** argv) {
    using namespace dual_prefetch;
    try {
        bool oneWay = false;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--one-way") oneWay = true;
            else if (arg == "--inject-mismatch") injectMismatch = true;
            else if (arg.rfind("--inject-", 0) == 0) mutation = arg.substr(9);
            else if (arg.rfind("--images=", 0) == 0) imageDirectory = arg.substr(9);
            else throw std::runtime_error("unknown dual tracking gate option: " + arg);
        }
        check(oneWay == (CACHE_WAYS == 1), "one-way host selection must match actual model");
        check(mutation.empty() || mutation == "token-address" || mutation == "token-origin" || mutation == "victim",
            "unknown observation mutation");
        check(!(injectMismatch && !mutation.empty()), "run independent negative controls separately");
        if (oneWay) one_way_veto();
        else {
            dual_residency(false); dual_residency(true); protected_dirty_release(); no_allowed_victim();
            probe_and_way_reuse(); refill_error_preserves_other(); flush_during_refill(); consume_during_other_refill();
            cancel_candidate(false); cancel_candidate(true);
        }
        check(mutation.empty(), "requested negative control did not fail its oracle");
        std::cout << "DUAL_PREFETCH_TRACKING_PASS split=" << split << " store_lru=" << lru
            << " ways=" << CACHE_WAYS << " lifetime=" << PF_CANDIDATE_CYCLES << " cases=" << completedCases
            << " full_pa=1 independent_tokens=1 independent_policy=1 actual_cache_home=1 full_flush=1"
            << " executing_cpu=0 performance_qualification=0\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "DUAL_PREFETCH_TRACKING_FAIL " << error.what() << '\n'; return 1;
    }
}
