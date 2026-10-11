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
#ifndef READ_PF_DIRTY_RETRY
#define READ_PF_DIRTY_RETRY 0
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
#include "prefetch_demand_adoption_transport.h"
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
    bool readDirtyAuthorized = false, attached = false; unsigned ticket = 0;
    uint64_t issuedTagLo = 0, issuedTagHi = 0, attachCycle = 0, aCycle = 0, refillCycle = 0, cpuSequence = 0;
    unsigned beats = 0, sink = 0; Words expected{}, received{};
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
    std::optional<std::pair<unsigned,uint64_t>> heldA;
    uint64_t accepted = 0; unsigned ownedTickets = 0;
    std::optional<uint64_t> lastRead; bool sequentialRead = false;
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
            const bool protectedStoreOther = READ_PF_DIRTY_RETRY && CACHE_WAYS == 2 && pf && !store && split &&
                present(token[1]) && !(consumed & 2U) && set(token[1]->address) == set(address) &&
                token[1]->index != index && !resident[token[1]->index].dirty;
            allowed[way] = !protectedLine && (pf || !reserved) &&
                (!pf || store || !r.valid || !r.dirty || protectedStoreOther);
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
              !heldC && !heldE && !heldA && sources.empty() && !wb[0] && !wb[1], "final owner accounting differs");
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
    void allocate(unsigned slot, uint64_t address, bool pf, bool store, Choice selected, unsigned consumed = 0) {
        check(slot < 2 && !active[slot] && selected.allowed, "allocation lacks a free independently allowed slot");
        for (const auto& other : active) if (other) {
            check(owners.at(*other).choice.index != selected.index, "two MSHRs reserve one physical way");
            if (pf) check(set(owners.at(*other).address) != set(address), "PF crossed its whole-set reservation gate");
        }
        Owner o; o.key = {slot, ++generations[slot]}; o.address = line(address);
        o.pf = pf; o.store = store; o.choice = selected; o.expected = words(address);
        // Authorization belongs to this allocation generation. The alternate
        // token may later be consumed or probed before fixed-victim capture.
        o.readDirtyAuthorized = READ_PF_DIRTY_RETRY && pf && !store && selected.victim.valid &&
            selected.victim.dirty && present(token[1]) && !(consumed & 2U) &&
            token[1]->index != selected.index && set(token[1]->address) == set(address) &&
            !resident[token[1]->index].dirty;
        check(!pf || !selected.victim.valid || !selected.victim.dirty || store || o.readDirtyAuthorized,
            "dirty read allocation lacks independently captured store-token authorization");
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
        unsigned speculative = 0;
        for (const auto& entry : active) if (entry) {
            const auto& owner = owners.at(*entry); speculative += owner.pf && !owner.attached;
        }
        check(speculative <= 1, "more than one unattached speculative MSHR exists");
        for (unsigned i = 0; i < 2; ++i) {
            if (active[i] && !(live & (1U << i))) {
                check(owners.at(*active[i]).filled, "MSHR retired before refill"); active[i].reset();
            }
            check(bool(live & (1U << i)) == bool(active[i]), "actual MSHR lost allocation generation");
            if (active[i]) {
                const auto& o = owners.at(*active[i]);
                check(bool(O(mshrDemandAttachedMask) & (1U << i)) == o.attached,
                    "attached mask differs from accepted owner history");
                check(bool(pf & (1U << i)) == o.pf && (!o.pf ||
                    bool(O(mshrStoreMask) & (1U << i)) == o.store), "MSHR origin changed after allocation");
            }
            check(bool(O(wbLiveMask) & (1U << i)) == bool(wb[i]), "WB lifetime differs from capture/Ack history");
            if (wb[i]) check(bool(O(wbPrefetchMask) & (1U << i)) == wb[i]->pf &&
                bool(O(wbSentMask) & (1U << i)) == wb[i]->sent &&
                (i ? O(wbAddress1) : O(wbAddress0)) == wb[i]->address,
                "saved WB origin/address changed during MSHR reuse");
        }
        check(O(responseOwnedMask) == ownedTickets, "response credits differ from accepted/returned ticket ledger");
        check(O(responseHeadTicket) == (t.cpuReturned - unsigned(bool(t.retiredThisTick))) % RESPONSE_ENTRIES &&
            O(responseTailTicket) == accepted % RESPONSE_ENTRIES, "response head/tail lost ticket wrap order");
        for (const auto& [key, owner] : owners) if (owner.attached && !owner.filled)
            check(!(O(responseCompleteMask) & (1U << owner.ticket)), "attached response completed before final refill");
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
            const bool use = fire && !offered->atomic && !offered->uncached && !offered->virtualized &&
                effective && line(offered->address) == token[i]->address;
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
            if (!offered->write) {
                const auto current = line(offered->address);
                check(lastRead && (current == *lastRead + 64 || (current == *lastRead && sequentialRead)),
                    "read prediction lacks independent accepted sequential history");
            }
            candidate = std::pair{line(offered->address) + 64, offered->write};
            ++counts[offered->write ? "store_candidate" : "read_candidate"];
        }
        if (O(demandAttach)) {
            check(READ_PF_DEMAND_ADOPTION && fire && offered && !offered->write && !offered->atomic &&
                !offered->uncached && !offered->virtualized && !offered->posted,
                "attachment lacks accepted ordinary physical read");
            const unsigned m = O(demandAttachSlot);
            check(m < 2 && active[m], "attachment lacks original live owner");
            auto& o = owners.at(*active[m]);
            uint64_t address = O(demandAttachAddress);
            if (mutation == "wrong-pa" && !mutationTriggered) {
                mutationTriggered = true; address ^= 1ULL << 40;
                std::cerr << "PREFETCH_DEMAND_ADOPTION_MUTATION_TRIGGER wrong-pa\n";
            }
            check(o.pf && !o.store && o.acquired && !o.attached && !o.filled && !o.error &&
                o.aCycle < t.cycles && address == offered->address && line(address) == o.address &&
                !O(demandAlloc) && !O(refill), "attachment lost exact issued read-PF full PA/phase");
            o.attached = true; o.attachCycle = t.cycles; o.cpuSequence = t.cpuAccepted - 1; o.ticket = O(demandAttachTicket);
            check(o.ticket == (t.cpuAccepted - 1) % RESPONSE_ENTRIES,
                "attachment reserved a stale response ticket");
            ++counts["attached"];
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
            allocate(O(allocatedSlot), candidate->first, true, candidate->second, selected, consumed);
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
                    (!w.pf || !w.dirty || o.store || o.readDirtyAuthorized),
                    "captured victim changed allocation or read PF released unprotected dirty data");
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
                if (w.dirty) {
                    uint64_t observed = O(cData);
                    if (mutation == "dirty-byte" && !mutationTriggered && w.pf) {
                        mutationTriggered = true; observed ^= 1;
                        std::cerr << "PREFETCH_DEMAND_ADOPTION_MUTATION_TRIGGER dirty-byte\n";
                    }
                    check(w.beats < 8 && observed == w.expected[w.beats], "dirty release byte oracle mismatch");
                }
                if (O(cReady)) {
                    ++w.beats; ++counts["release_beats"]; counts["dirty_pf_beats"] += w.pf && w.dirty;
                    w.sent = w.beats == (w.dirty ? 8U : 1U);
                }
            }
        } else check(!heldC, "held C valid disappeared");
        if (d.get_io$$releaseAckFire()) {
            const unsigned source = d.get_io$$releaseAckSource();
            if (mutation == "lost-wb" && !mutationTriggered && source >= 2 && source < 4 &&
                wb[source - 2] && wb[source - 2]->pf) {
                mutationTriggered = true;
                std::cerr << "PREFETCH_DEMAND_ADOPTION_MUTATION_TRIGGER lost-wb\n";
                wb[source - 2].reset();
            }
            check(source >= 2 && source < 4 && wb[source - 2] && wb[source - 2]->sent,
                "ReleaseAck lost independently saved WB obligation");
            counts["dirty_pf_acks"] += wb[source - 2]->pf && wb[source - 2]->dirty;
            wb[source - 2].reset();
        }
        if (d.get_io$$acquireOffer()) {
            const auto payload = std::pair{unsigned(d.get_io$$acquireSource()), uint64_t(d.get_io$$acquireAddress())};
            if (heldA) check(payload == *heldA, "held A source/full PA changed");
            if (!d.get_io$$acquireFire()) { heldA = payload; ++counts["held_a_samples"]; } else heldA.reset();
        } else check(!heldA, "held A valid disappeared");
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
            auto& o = owners.at(*key); o.acquired = true; o.aCycle = t.cycles; sources[source] = *key;
            ++counts[o.pf ? "pf_acquire" : "demand_acquire"];
        }
        if (d.get_io$$grantFire()) {
            const unsigned source = d.get_io$$grantSource(); check(sources.count(source), "D lacks A owner");
            auto& o = owners.at(sources.at(source));
            if (!o.beats) o.sink = d.get_io$$grantSink();
            check(o.beats < 8 && o.sink == d.get_io$$grantSink(), "D changed owner sink/beat");
            o.error |= O(dDenied) || O(dCorrupt);
            // Error is a whole-transaction property and may first appear on
            // the last D beat. Failed home payload is unspecified, so validate
            // all successful bytes only after the complete error reduction.
            if (o.pf) o.received[o.beats] = O(dData);
            ++o.beats;
            if (o.pf && o.beats == 8 && !o.error)
                check(o.received == o.expected, "prefetch D byte oracle mismatch");
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
        if (O(acquireIssued)) {
            const unsigned m = O(acquireIssuedSlot);
            check(m < 2 && active[m], "issued tag lacks allocation owner");
            auto& o = owners.at(*active[m]);
            o.issuedTagLo = O(acquireIssuedTagLo); o.issuedTagHi = O(acquireIssuedTagHi);
            check(O(acquireTagBits) == 68 && o.issuedTagLo == m &&
                o.issuedTagHi == (o.pf ? 4U : 0U), "issued transaction tag changed immutable PF kind");
            ++counts["issued_tag"];
        }
        if (O(refill)) {
            const unsigned slot = O(refillSlot); check(slot < 2 && active[slot], "refill lacks allocated MSHR generation");
            auto& o = owners.at(*active[slot]);
            uint64_t tagHi = O(refillTagHi);
            if (mutation == "wrong-tag" && !mutationTriggered && o.attached) {
                mutationTriggered = true; tagHi ^= 4;
                std::cerr << "PREFETCH_DEMAND_ADOPTION_MUTATION_TRIGGER wrong-tag\n";
            }
            check(O(refillTagLo) == o.issuedTagLo && tagHi == o.issuedTagHi,
                "refill transaction tag differs from original issued PF kind");
            check(bool(O(refillDemandAttached)) == o.attached && (!o.attached || O(refillTicket) == o.ticket),
                "refill attachment/ticket differs from accepted demand");
            check(o.beats == 8 && o.acked && !o.filled && o.address == line(O(refillAddress)) &&
                o.choice.index == O(refillIndex) && o.pf == bool(O(refillPrefetch)) && o.error == bool(O(refillError)),
                "refill lost immutable origin/full PA/index/error");
            o.filled = true; o.refillCycle = t.cycles;
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
                    (o.pf && !o.store && !o.attached ? way : 1 - way)};
                if (o.pf && !o.attached) token[split && o.store ? 1 : 0] = Token{o.address, index, o.store};
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
            check(!(ownedTickets & (1U << (accepted % RESPONSE_ENTRIES))), "accepted request reused owned response ticket");
            ownedTickets |= 1U << (accepted % RESPONSE_ENTRIES);
            if (offered->uncached || offered->atomic || offered->virtualized) sequentialRead = false;
            else if (!offered->write) {
                const auto current = line(offered->address);
                sequentialRead = lastRead && (current == *lastRead + 64 || (current == *lastRead && sequentialRead));
                lastRead = current;
            }
            offered.reset(); accepted = t.cpuAccepted;
        }
        // A refill's replacement update is later than accepted-hit touch in
        // the real cache. This matters when independent demand admission lets
        // a hit in the other way share the refill's set on the same edge.
        if (refillReplacement) oldest[refillReplacement->first] = refillReplacement->second;
        if (t.retiredThisTick) {
            const auto& result = *t.retiredThisTick;
            check(ownedTickets & (1U << (result.sequence % RESPONSE_ENTRIES)), "CPU result has no independent ticket owner");
            ownedTickets &= ~(1U << (result.sequence % RESPONSE_ENTRIES));
            for (const auto& [key, owner] : owners) if (owner.attached && owner.cpuSequence == result.sequence) {
                check(owner.filled && owner.acked && owner.refillCycle < t.cycles &&
                    line(result.address) == owner.address && result.error == owner.error,
                    "attached CPU response preceded final E/refill or changed owner/error");
                ++counts["attached_response"];
            }
        }
        if (flushing) { token = {}; candidate.reset(); lastRead.reset(); sequentialRead = false; }
#undef O
    }
};


} // namespace dual_prefetch
