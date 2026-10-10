#include "MemoryProofFrontierExactGsim.h"
#include "memory_proof_frontier_exact_reference.h"
#include <algorithm>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
#include <vector>
#ifndef MEMORY_PROOF_ENABLED
#define MEMORY_PROOF_ENABLED 0
#endif
using namespace memory_proof_exact_reference;
constexpr uint64_t farOffset = 128;
using Key = std::pair<unsigned, uint64_t>;
static Key key(Token t) { return {t.index, t.tag}; }
struct Request {
    bool valid = false, memory = false, store = false, system = false, divide = false, writes = true;
    unsigned rd = 1, rs1 = 0, rs2 = 0;
    uint32_t instruction = 0x13;
    uint64_t immediate = 0, address = 0, pc = 0, expected = 0, expectedStore = 0;
};
static Request add(unsigned rd, uint64_t value) {
    Request r; r.valid = true; r.rd = rd; r.immediate = r.expected = value; return r;
}
static Request load(unsigned rd, uint64_t address) {
    Request r = add(rd, address); r.memory = true; r.address = address; r.instruction = 0x3003; return r;
}
static Request store(uint64_t address, unsigned rs2) {
    Request r = load(0, address); r.store = true; r.rs2 = rs2; r.writes = false; r.instruction = 0x3023; return r;
}
static Request system(uint32_t instruction, unsigned rs1 = 0) {
    Request r = add(0, 0); r.writes = false; r.system = true; r.rs1 = rs1; r.instruction = instruction; return r;
}
static Request divide() {
    Request r = add(24, 123456789ULL / 7); r.divide = true; r.rs1 = 25; r.rs2 = 26;
    r.instruction = (1U << 25) | (26U << 20) | (25U << 15) | (4U << 12) | (24U << 7) | 0x33; return r;
}
struct Entry { Token token; Request request; bool started = false, canonical = false, requested = false; };
struct Grant { uint64_t address, due; unsigned source, sink, beat = 0; bool done = false, error = false, prefetch = false; };
struct PteReply { uint64_t due, data; };
struct CacheOwner { Token token; uint64_t data; bool write; };
class Bench {
    SMemoryProofFrontierExactGsim d;
    std::deque<Entry> live;
    std::vector<Entry> cancelled;
    std::deque<PteReply> ptes;
    std::map<unsigned, Grant> grants;
    std::deque<std::pair<unsigned, uint64_t>> releaseAcks;
    std::optional<unsigned> grant;
    std::deque<CacheOwner> cacheOwners;
    std::array<uint64_t, 32> architectural{}, predicted{};
    std::map<Key, Proof> proofs;
    std::map<Key, uint64_t> queryCycles, startCycles, cacheCycles, externalCycles, responseCycles, completionCycles;
    std::set<Key> retiredTokens, checkedTokens;
    std::set<uint64_t> acceptedExternalLines, acceptedPrefetchLines;
    std::map<Key, std::pair<uint64_t, uint64_t>> usefulPrefetches;
    std::map<uint64_t, Token> outstandingMisses;
    struct Prefetch { Token origin; uint64_t candidateCycle; unsigned slot; };
    std::map<uint64_t, Prefetch> outstandingPrefetches;
    std::map<uint64_t, std::pair<Token, uint64_t>> nextLineAuthorities;
    std::optional<std::tuple<uint64_t, uint64_t, bool, unsigned>> heldCache;
    uint64_t nextPc = 0x1000;
    unsigned cBeat = 0, cSource = 0, cOpcode = 0;
    uint64_t cAddress = 0;
public:
    Tables tables;
    Bytes backing, expectedBytes, beforeClosure;
    uint64_t cycle = 0, delay = 16;
    unsigned allocated = 0, retired = 0, requests = 0, responses = 0, acquires = 0, peakGrants = 0;
    unsigned proofReads = 0, proofWrites = 0, frontierOverlap = 0, firstResponseVisible = 0;
    bool flush = false, injectData = false, injectProof = false, injectMissingAcquire = false, bareMode = false, lateStoreFault = false, injectStoreDecode = false;
    unsigned traps = 0, prefetchAcquires = 0, peakOrdinaryGrants = 0, postedRequests = 0;
    uint64_t trapCycle = 0;
    std::optional<Token> faultStore;
    std::optional<Token> old, far;
    std::vector<Token> closureStores, closureLoads;
    Bench() {
        drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        for (unsigned i = 0; i < 6; ++i) tick();
    }
    uint64_t physicalOf(uint64_t address) const { return bareMode ? address : tables.physical(address); }
    Entry &owner(Token token) {
        auto it = std::find_if(live.begin(), live.end(), [&](const Entry &e) { return e.token == token; });
        require(it != live.end(), "event has no exact live full-token owner"); return *it;
    }
    void drive(const std::array<Request, 2> &in) {
        auto immediateOperand = [&](const Request &r) {
            const bool value = (!r.divide && !r.store) || (injectStoreDecode && r.store);
            // Independent instruction-class property: an ordinary S-format store
            // has a register rs2 dependency even though its address contains an immediate.
            require(!r.valid || (r.instruction & 0x7f) != 0x23 || !value,
                    "ordinary store decode requires register rs2 dependency (useImmediate=false)");
            return value;
        };
#define DRIVE(N) \
        d.set_io$$allocate##N##$$valid(in[N].valid); \
        d.set_io$$allocate##N##$$bits$$rename$$writesRd(in[N].writes); \
        d.set_io$$allocate##N##$$bits$$rename$$rs1(in[N].rs1); \
        d.set_io$$allocate##N##$$bits$$rename$$rs2(in[N].rs2); \
        d.set_io$$allocate##N##$$bits$$rename$$rd(in[N].rd); \
        d.set_io$$allocate##N##$$bits$$rename$$pc(in[N].pc); \
        d.set_io$$allocate##N##$$bits$$rename$$instruction(in[N].instruction); \
        d.set_io$$allocate##N##$$bits$$expandedInstruction(in[N].instruction); \
        d.set_io$$allocate##N##$$bits$$system(in[N].system); \
        d.set_io$$allocate##N##$$bits$$memory(in[N].memory); \
        d.set_io$$allocate##N##$$bits$$store(in[N].store); \
        d.set_io$$allocate##N##$$bits$$memorySize(3); \
        d.set_io$$allocate##N##$$bits$$memoryUnsigned(0); \
        d.set_io$$allocate##N##$$bits$$immediate(in[N].immediate); \
        d.set_io$$allocate##N##$$bits$$operation(0); \
        d.set_io$$allocate##N##$$bits$$word(0); \
        d.set_io$$allocate##N##$$bits$$usePc(0); \
        d.set_io$$allocate##N##$$bits$$useImmediate(immediateOperand(in[N])); \
        d.set_io$$allocate##N##$$bits$$controlFlow(0); \
        d.set_io$$allocate##N##$$bits$$mulDiv(in[N].divide); \
        d.set_io$$allocate##N##$$bits$$mulDivOp(in[N].divide ? 4 : 0); \
        d.set_io$$allocate##N##$$bits$$atomic(0); \
        d.set_io$$allocate##N##$$bits$$atomicOp(0); \
        d.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
        d.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
        d.set_io$$allocate##N##$$bits$$fetchFault(0); \
        d.set_io$$allocate##N##$$bits$$fetchPageFault(0); \
        d.set_io$$allocate##N##$$bits$$fetchTval(0);
        DRIVE(0) DRIVE(1)
#undef DRIVE
        d.set_io$$commitEnable(1); d.set_io$$inspectRegister(cycle % 32);
        d.set_io$$recover$$valid(0); d.set_io$$recover$$bits$$inclusive(1);
        d.set_io$$recover$$bits$$token$$index(0); d.set_io$$recover$$bits$$token$$tag(0);
        d.set_io$$physical$$request$$ready(1); d.set_io$$physical$$response$$valid(0);
        d.set_io$$physical$$response$$bits$$data(0); d.set_io$$physical$$response$$bits$$error(0);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        const bool pv = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$request$$ready(1); d.set_io$$pte$$response$$valid(pv);
        d.set_io$$pte$$response$$bits$$data(pv ? ptes.front().data : 0); d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$cacheFlush(flush);
        d.set_io$$tl$$a$$ready(cycle % 7 != 2); d.set_io$$tl$$c$$ready(cycle % 5 != 3); d.set_io$$tl$$e$$ready(1);
        d.set_io$$tl$$b$$valid(0); d.set_io$$tl$$b$$bits$$opcode(6); d.set_io$$tl$$b$$bits$$param(2);
        d.set_io$$tl$$b$$bits$$size(6); d.set_io$$tl$$b$$bits$$source(0); d.set_io$$tl$$b$$bits$$address(ram);
        d.set_io$$tl$$b$$bits$$mask(255); d.set_io$$tl$$b$$bits$$data(0); d.set_io$$tl$$b$$bits$$corrupt(0);
        if (!grant && (releaseAcks.empty() || releaseAcks.front().second > cycle)) {
            for (auto &[source, g] : grants) if (!g.done && g.due <= cycle &&
                (!g.error || (far && completionCycles.count(key(*far))))) { grant = source; break; }
        }
        const bool ack = !grant && !releaseAcks.empty() && releaseAcks.front().second <= cycle;
        d.set_io$$tl$$d$$valid(grant.has_value() || ack);
        d.set_io$$tl$$d$$bits$$size(6); d.set_io$$tl$$d$$bits$$corrupt(0); d.set_io$$tl$$d$$bits$$denied(0);
        if (grant) {
            const auto &g = grants.at(*grant);
            d.set_io$$tl$$d$$bits$$opcode(5); d.set_io$$tl$$d$$bits$$param(0);
            d.set_io$$tl$$d$$bits$$source(g.source); d.set_io$$tl$$d$$bits$$sink(g.sink);
            d.set_io$$tl$$d$$bits$$data(backing.read(g.address + g.beat * 8, 3) ^ uint64_t(injectData));
            d.set_io$$tl$$d$$bits$$denied(g.error); // Transaction-level field remains constant across all eight beats.
            d.set_io$$tl$$d$$bits$$corrupt(g.error); // Match the verified home backing-error contract on every beat.
        } else {
            d.set_io$$tl$$d$$bits$$opcode(6); d.set_io$$tl$$d$$bits$$param(0);
            d.set_io$$tl$$d$$bits$$source(ack ? releaseAcks.front().first : 0);
            d.set_io$$tl$$d$$bits$$sink(0); d.set_io$$tl$$d$$bits$$data(0);
        }
    }
    std::vector<Token> tick(std::array<Request, 2> in = {}) {
        const bool pv = !ptes.empty() && ptes.front().due <= cycle;
        drive(in); d.step();
        std::vector<Token> accepted;
        require(d.get_io$$committedValue() == architectural[cycle % 32], "independent committed register mismatch");
#define ACCEPT(N) \
        if (d.get_io$$renamed##N##$$valid()) { \
            require(in[N].valid, "unoffered allocation"); \
            const Token t{unsigned(d.get_io$$renamed##N##$$bits$$token$$index()), uint64_t(d.get_io$$renamed##N##$$bits$$token$$tag())}; \
            Request r = in[N]; \
            if (r.memory) { \
                const auto pa = physicalOf(r.address); \
                if (r.store) { r.expectedStore = predicted[r.rs2]; expectedBytes.write(pa, r.expectedStore, 3); } \
                else r.expected = expectedBytes.read(pa, 3); \
            } \
            if (r.writes && r.rd) predicted[r.rd] = r.expected; \
            live.push_back({t, r}); accepted.push_back(t); ++allocated; \
        }
        ACCEPT(0) ACCEPT(1)
#undef ACCEPT
        if (pv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid()) ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())});
        require(!d.get_io$$physical$$request$$valid(), "unexpected uncached/bypass transaction in ordinary-RAM fixture");
        if (!lateStoreFault) require(!d.get_io$$trap$$valid(), "unexpected precise trap in positive controlled witness");
        if (d.get_io$$queryValid() && d.get_io$$queryHit()) {
            const uint64_t address = d.get_io$$queryAddress();
            const bool write = d.get_io$$queryWrite();
            require(tables.normalAllowed(address, write, 3), "query lacks raw independent PTE/PMP normality");
            require(d.get_io$$queryPhysical() == physicalOf(address), "query PA differs from raw table");
            if (d.get_io$$queryToken$$valid()) {
                const Token t{unsigned(d.get_io$$queryToken$$bits$$index()), uint64_t(d.get_io$$queryToken$$bits$$tag())};
                auto &e = owner(t);
                require(e.request.address == address && e.request.store == write, "query owner VA/access mismatch");
                queryCycles[key(t)] = cycle;
            }
        }
        if (d.get_io$$insertedProof$$valid()) {
            const Token t{unsigned(d.get_io$$insertedProof$$bits$$token$$index()), uint64_t(d.get_io$$insertedProof$$bits$$token$$tag())};
            auto &e = owner(t);
            const Proof observed{t, uint32_t(d.get_io$$insertedProof$$bits$$epoch()),
                uint64_t(d.get_io$$insertedProof$$bits$$payload$$address()), uint64_t(d.get_io$$insertedProof$$bits$$payload$$physicalAddress()),
                bool(d.get_io$$insertedProof$$bits$$payload$$write()), unsigned(d.get_io$$insertedProof$$bits$$payload$$size()),
                unsigned(d.get_io$$insertedProof$$bits$$payload$$mask())};
            Proof expected{t, uint32_t(d.get_io$$epoch()), e.request.address, physicalOf(e.request.address), e.request.store, 3, 255};
            if (injectProof) expected.token.tag ^= 1ULL << 63;
            require(observed == expected && queryCycles.count(key(t)) && cycle > queryCycles[key(t)],
                    "actual inserted proof differs from independent full-token query/permission expectation");
            proofs[key(t)] = observed;
            e.request.store ? ++proofWrites : ++proofReads;
        }
        if (d.get_io$$lsuStart()) {
            const Token t{unsigned(d.get_io$$lsuToken$$index()), uint64_t(d.get_io$$lsuToken$$tag())};
            auto &e = owner(t);
            require(!e.started && d.get_io$$lsuVa() == e.request.address, "duplicate start or lost original VA");
            e.started = true; e.canonical = d.get_io$$lsuPrechecked(); startCycles[key(t)] = cycle;
            if (e.canonical) {
                require(!e.request.store && d.get_io$$lsuParallel() && d.get_io$$lsuPa() == physicalOf(e.request.address),
                        "prechecked actual mode/PA mismatch");
                const Proof candidate{t, uint32_t(d.get_io$$epoch()), e.request.address, physicalOf(e.request.address), false, 3, 255};
                for (const auto &older : live) {
                    if (older.token == t) break;
                    if (!older.request.memory) continue;
                    if (!older.started) {
                        require(MEMORY_PROOF_ENABLED && proofs.count(key(older.token)), "crossed pending owner lacks its actual proof");
                        const auto &proof = proofs.at(key(older.token));
                        require(!older.request.store || disjoint(proof, candidate), "crossed physical store alias");
                    } else if (!older.request.store) require(older.canonical, "crossed serial old load");
                    else require(checkedTokens.count(key(older.token)), "crossed started store before real checked certificate");
                }
            }
        }
        if (d.get_io$$upstreamFire() && d.get_io$$frozenRequest$$valid()) {
            require(d.get_io$$canonicalOrigin$$valid(), "frozen request lacks original full owner");
            const Token t{unsigned(d.get_io$$canonicalOrigin$$bits$$token$$index()), uint64_t(d.get_io$$canonicalOrigin$$bits$$token$$tag())};
            const auto &e = owner(t);
            require(e.request.store && e.started && proofs.count(key(t)), "frozen request lacks prepared actual store");
            const auto &p = proofs.at(key(t));
            require(d.get_io$$frozenRequest$$bits$$physicalAddress() == p.physical &&
                    d.get_io$$frozenRequest$$bits$$address() == p.original &&
                    d.get_io$$frozenRequest$$bits$$mask() == p.mask && d.get_io$$frozenRequest$$bits$$size() == p.size,
                    "actual frozen request changed its independent retained tuple");
        }
        if (d.get_io$$canonicalChecked$$valid()) {
            const Token t{unsigned(d.get_io$$canonicalChecked$$bits$$origin$$token$$index()), uint64_t(d.get_io$$canonicalChecked$$bits$$origin$$token$$tag())};
            auto &e = owner(t);
            require(e.request.store && e.started && live.front().token == t, "checked certificate lacks real head owner");
            require(d.get_io$$canonicalChecked$$bits$$physicalAddress() == physicalOf(e.request.address) &&
                    d.get_io$$canonicalChecked$$bits$$virtualAddress() == e.request.address, "checked frozen VA/PA mismatch");
            require(checkedTokens.insert(key(t)).second, "duplicate checked certificate");
        }
        const bool cv = d.get_io$$cacheRequest$$valid();
        if (heldCache) require(cv, "held cache request VALID withdrawn");
        if (cv) {
            const auto payload = std::make_tuple(uint64_t(d.get_io$$cacheRequest$$bits$$address()),
                uint64_t(d.get_io$$cacheRequest$$bits$$data()), bool(d.get_io$$cacheRequest$$bits$$write()),
                unsigned(d.get_io$$cacheRequest$$bits$$mask()));
            if (heldCache) require(payload == *heldCache, "held cache payload changed");
            heldCache = !d.get_io$$cacheRequestFire() ? std::optional{payload} : std::nullopt;
            if (d.get_io$$cacheRequestFire()) {
                const uint64_t pa = std::get<0>(payload); const bool write = std::get<2>(payload);
                Entry *entry = nullptr;
                auto matches = [&](const Entry &e) {
                    return e.request.memory && e.started && !e.requested && e.request.store == write && physicalOf(e.request.address) == pa;
                };
                for (auto &e : live) if (matches(e)) { entry = &e; break; }
                if (!entry) for (auto &e : cancelled) if (matches(e)) { entry = &e; break; }
                require(entry && std::get<3>(payload) == 255, "cache accepted unowned/malformed ordinary request");
                if (write) require(std::get<1>(payload) == entry->request.expectedStore, "store bytes differ from independent dependency value");
                entry->requested = true; cacheCycles[key(entry->token)] = cycle;
                // These pinned generated fields expose the actual cache useful event.
                // The independent accepted PF lineage and real ordinary owner supply
                // the expected address/token; an inactive tracked payload is never read.
                if (d.cache$consume) {
                    require(d.cache$trackedValid && (pa & ~63ULL) == d.cache$trackedAddress &&
                            acceptedPrefetchLines.count(pa & ~63ULL),
                            "useful event lacks the exact independently accepted prefetch line");
                    require(usefulPrefetches.emplace(key(entry->token), std::pair{pa & ~63ULL, cycle}).second,
                            "duplicate useful event for one ordinary full-token owner");
                }
                if (d.get_io$$cachePostedProof()) {
                    require(write && bareMode && !proofs.count(key(entry->token)), "virtual/frozen owner incorrectly became posted authority");
                    ++postedRequests;
                }
                const uint64_t next = (pa & ~63ULL) + 64;
                // Independent normal-RAM and same-page authority from the real accepted owner.
                // This does not trust the cache's candidate/eligibility expression.
                if ((next >> 12) == (pa >> 12) && __uint128_t(next) + 64 <= __uint128_t(ram) + ramBytes &&
                    (bareMode || tables.normalAllowed(entry->request.address, write, 3)))
                    nextLineAuthorities[next] = {entry->token, cycle};
                cacheOwners.push_back({entry->token, entry->request.expected, write}); ++requests;
                if (d.get_io$$demandMiss()) {
                    require(d.get_io$$demandMissAddress() == pa, "cache miss address attribution mismatch");
                    require(!outstandingMisses.count(pa & ~63ULL) && !outstandingPrefetches.count(pa & ~63ULL),
                            "ordinary cache allocation reused an outstanding line owner");
                    outstandingMisses[pa & ~63ULL] = entry->token;
                }
            }
        }
        if (d.get_io$$prefetchAllocated()) {
            const uint64_t line = d.get_io$$prefetchAddress();
            require(!(line & 63) && line >= ram && __uint128_t(line) + 64 <= __uint128_t(ram) + ramBytes,
                    "prefetch escaped independent normal RAM interval");
            require(nextLineAuthorities.count(line), "prefetch has no independent accepted next-line authority");
            const auto authority = nextLineAuthorities.at(line);
            require(cycle > authority.second && cycle - authority.second <= 2 &&
                    !outstandingMisses.count(line) && !outstandingPrefetches.count(line),
                    "prefetch has stale or duplicate raw owner authority");
            require(d.get_io$$prefetchSlot() < 2, "prefetch exceeded the two real MSHRs");
            outstandingPrefetches.emplace(line, Prefetch{authority.first, cycle, unsigned(d.get_io$$prefetchSlot())});
        }
        if (d.get_io$$cacheResponse$$valid()) {
            require(!cacheOwners.empty(), "cache response has no real accepted owner");
            const auto &r = cacheOwners.front();
            if (!responseCycles.count(key(r.token))) responseCycles[key(r.token)] = cycle; // first visible, not handshake
            const bool expectedError = lateStoreFault && faultStore && r.token == *faultStore;
            require(bool(d.get_io$$cacheResponse$$bits$$error()) == expectedError && !d.get_io$$cacheResponse$$bits$$pageFault(), "cache response fault/full-token mismatch");
            if (!r.write) require(d.get_io$$cacheResponse$$bits$$data() == r.data, "actual loaded data differs from independent golden bytes");
            if (d.get_io$$cacheResponseFire()) { cacheOwners.pop_front(); ++responses; }
        }
        if (d.get_io$$tl$$a$$valid() && cycle % 7 != 2) {
            const unsigned source = d.get_io$$tl$$a$$bits$$source();
            const uint64_t address = d.get_io$$tl$$a$$bits$$address();
            require(d.get_io$$tl$$a$$bits$$opcode() == 6 && d.get_io$$tl$$a$$bits$$size() == 6,
                    "external transaction is not an ordinary full-line acquisition");
            require(!grants.count(source), "external acquisition reused a live source");
            const bool ordinary = outstandingMisses.count(address), pf = outstandingPrefetches.count(address);
            require(ordinary != pf, "external acquisition lacks one distinct demand-or-prefetch lineage");
            bool deny = false;
            if (ordinary) {
                const Token token = outstandingMisses.at(address);
                require(!externalCycles.count(key(token)), "duplicate external ordinary demand acceptance");
                if (!(injectMissingAcquire && address == ram)) externalCycles[key(token)] = cycle;
                deny = lateStoreFault && faultStore && token == *faultStore;
            } else { ++prefetchAcquires; acceptedPrefetchLines.insert(address); }
            const uint64_t due = cycle + (pf ? 16 : ((lateStoreFault && address == ram + farOffset) ? 32 : delay));
            // PF always keeps separate identity; a later demand to its line never becomes this owner.
            grants.emplace(source, Grant{address, due, source, source % 2, 0, false, deny, pf});
            acceptedExternalLines.insert(address);
            ++acquires; peakGrants = std::max(peakGrants, unsigned(grants.size()));
            unsigned ordinaryLive = 0;
            for (const auto &[unused, g] : grants) ordinaryLive += !g.prefetch;
            peakOrdinaryGrants = std::max(peakOrdinaryGrants, ordinaryLive);
        }
        if ((grant || (!releaseAcks.empty() && releaseAcks.front().second <= cycle)) && d.get_io$$tl$$d$$ready()) {
            if (grant) { auto &g = grants.at(*grant); if (++g.beat == 8) { g.done = true; grant.reset(); } }
            else releaseAcks.pop_front();
        }
        if (d.get_io$$tl$$e$$valid()) {
            const unsigned sink = d.get_io$$tl$$e$$bits$$sink();
            auto it = std::find_if(grants.begin(), grants.end(), [&](const auto &g) { return g.second.sink == sink; });
            require(it != grants.end() && it->second.done, "GrantAck lost full external source/sink owner");
            if (it->second.prefetch) require(outstandingPrefetches.erase(it->second.address) == 1, "lost prefetch drain owner");
            else require(outstandingMisses.erase(it->second.address) == 1, "lost ordinary drain owner");
            grants.erase(it);
        }
        if (d.get_io$$tl$$c$$valid() && cycle % 5 != 3) {
            const unsigned opcode = d.get_io$$tl$$c$$bits$$opcode(), source = d.get_io$$tl$$c$$bits$$source();
            const uint64_t address = d.get_io$$tl$$c$$bits$$address();
            if (!cBeat) { cOpcode = opcode; cSource = source; cAddress = address; }
            require(opcode == cOpcode && source == cSource && address == cAddress && (opcode == 6 || opcode == 7), "release burst lineage changed");
            if (opcode == 7) backing.write(address + 8 * cBeat, d.get_io$$tl$$c$$bits$$data(), 3);
            if (++cBeat == (opcode == 7 ? 8U : 1U)) { releaseAcks.push_back({source, cycle + 2}); cBeat = 0; }
        }
#define COMPLETE(N) \
        if (d.get_io$$issued##N##$$valid()) { \
            const Token t{unsigned(d.get_io$$issued##N##$$bits$$token$$index()), uint64_t(d.get_io$$issued##N##$$bits$$token$$tag())}; \
            const auto &e = owner(t); \
            if (e.request.memory && !e.request.store) { \
                require(!d.get_io$$issued##N##$$bits$$exception() && d.get_io$$issued##N##$$bits$$data() == e.request.expected, "load completion lost independent data/full token"); \
                completionCycles[key(t)] = cycle; \
            } \
        }
        COMPLETE(0) COMPLETE(1)
#undef COMPLETE
#define RETIRE(N) \
        if (d.get_io$$commit##N##$$valid()) { \
            require(!live.empty(), "retirement has no live owner"); const Entry e = live.front(); live.pop_front(); \
            const Token t{unsigned(d.get_io$$commit##N##$$bits$$token$$index()), uint64_t(d.get_io$$commit##N##$$bits$$token$$tag())}; \
            require(t == e.token && retiredTokens.insert(key(t)).second, "retirement full-token order/duplicate mismatch"); \
            require(d.get_io$$commit##N##$$bits$$pc() == e.request.pc && d.get_io$$commit##N##$$bits$$instruction() == e.request.instruction, "retirement original provenance mismatch"); \
            if (e.request.writes && e.request.rd) { \
                require(d.get_io$$commit##N##$$bits$$data() == e.request.expected, "independent architectural result mismatch"); \
                architectural[e.request.rd] = e.request.expected; \
            } \
            if (e.request.memory) require(responseCycles.count(key(t)), "memory retired without real response"); \
            ++retired; \
        }
        RETIRE(0) RETIRE(1)
#undef RETIRE
        if (d.get_io$$trap$$valid()) {
            require(lateStoreFault && faultStore && !live.empty(), "trap lacks independently expected fault owner");
            const Token t{unsigned(d.get_io$$trap$$bits$$token$$index()), uint64_t(d.get_io$$trap$$bits$$token$$tag())};
            require(t == *faultStore && live.front().token == t && d.get_io$$trap$$bits$$cause() == 7 &&
                    d.get_io$$trap$$bits$$pc() == live.front().request.pc &&
                    d.get_io$$trap$$bits$$tval() == live.front().request.address,
                    "late store fault lost precise cause/original VA/PC/full token");
            require(completionCycles.count(key(*far)) && completionCycles.at(key(*far)) < cycle,
                    "late-fault control did not first complete its younger far load");
            require(!retiredTokens.count(key(t)) && !retiredTokens.count(key(*far)), "faulting store/younger completed load retired");
            for (auto &e : live) { require(!retiredTokens.count(key(e.token)), "younger owner retired across older fault"); cancelled.push_back(e); }
            live.clear(); predicted = architectural; expectedBytes = beforeClosure;
            ++traps; trapCycle = cycle;
        }
        ++cycle; return accepted;
    }
    std::vector<Token> submit(std::vector<Request> program) {
        for (auto &r : program) { r.pc = nextPc; nextPc += 4; }
        std::vector<Token> result;
        unsigned cursor = 0;
        for (unsigned i = 0; i < 2000 && cursor < program.size(); ++i) {
            std::array<Request, 2> in{}; in[0] = program[cursor]; if (cursor + 1 < program.size()) in[1] = program[cursor + 1];
            auto tokens = tick(in); cursor += tokens.size(); result.insert(result.end(), tokens.begin(), tokens.end());
        }
        require(cursor == program.size(), "allocation failed to make progress"); return result;
    }
    void drain() {
        for (unsigned i = 0; i < 5000 && (!live.empty() || !cacheOwners.empty() || !ptes.empty() || !grants.empty() || !outstandingPrefetches.empty() || !d.get_io$$idle()); ++i) tick();
        require(live.empty() && cacheOwners.empty() && ptes.empty() && grants.empty(), "accepted owners failed to drain");
        for (unsigned i = 0; i < 12; ++i) tick();
        require(d.get_io$$idle() && requests == responses && outstandingMisses.empty() && outstandingPrefetches.empty() &&
                !d.get_io$$prefetchBusy() && !d.get_io$$cpuPostedBusy() && !d.get_io$$cachePostedBusy(),
                "backend/adapter/PF/posted owner drain mismatch");
    }
    void one(Request r) { submit({r}); drain(); }
    void csr(unsigned address, uint64_t value) { one(add(31, value)); one(system((address << 20) | (31 << 15) | (1 << 12) | 0x73, 31)); }
    void flushCache() {
        flush = true; bool done = false;
        for (unsigned i = 0; i < 3000 && !done; ++i) { tick(); done = d.get_io$$cacheFlushDone(); }
        require(done, "real cache flush failed to finish"); flush = false;
        for (unsigned i = 0; i < 8; ++i) tick();
        require(grants.empty() && releaseAcks.empty(), "flush release ownership not drained");
    }
    void warmControl(const std::string &mode) {
        const uint64_t base = bareMode ? ram : va;
        // Exercise the actual selected PF policy away from the primary cold-miss window.
        // Separate physical regions keep the Sv39 and Bare controls independently cold.
        const uint64_t pfOffset = bareMode ? 1536 : 1024;
        const unsigned pfBefore = prefetchAcquires;
        one(load(1, base + pfOffset)); one(load(2, base + pfOffset + 64));
        require(prefetchAcquires > pfBefore && outstandingPrefetches.empty() && !d.get_io$$prefetchBusy(),
                "sequential warm setup did not exercise and drain a distinct real prefetch owner");
        one(load(1, base)); one(load(2, base + 64));
        std::vector<Request> program{divide()};
        for (unsigned i = 0; i < 16; ++i) program.push_back(load(3 + i, base + 8 * i));
        const auto tokens = submit(program);
        drain();
        uint64_t bubbles = 0, first = startCycles.at(key(tokens[1])), last = first;
        for (unsigned i = 2; i < tokens.size(); ++i) {
            const uint64_t next = startCycles.at(key(tokens[i]));
            require(next > last, "one memory issue budget violated by warm control");
            bubbles += next - last - 1; last = next;
        }
        std::cout << "MEMORY_PROOF_WARM mode=" << mode << " enabled=" << MEMORY_PROOF_ENABLED
                  << " loads=16 first_start=" << first << " last_start=" << last
                  << " start_span=" << last - first << " intervening_bubbles=" << bubbles << "\n";
        // Measured II is a result. It is deliberately not a functional PASS predicate.
        // Retired demand owners and idle PF transport do not consume the installed
        // predictive token. Use its exact line through a real ordinary load after
        // measurement, so the next warm mode starts with no retained token.
        // The measured stream ends on base+64; this far line is non-sequential,
        // which prevents this consumption from predicting another fresh line.
        const uint64_t pfLine = ram + pfOffset + 128;
        require(d.cache$trackedValid && d.cache$trackedAddress == pfLine &&
                acceptedPrefetchLines.count(pfLine),
                "warm isolation lacks the expected installed tracked prefetch line");
        const unsigned acquiredBeforeConsume = prefetchAcquires;
        const Token consumer = submit({load(2, base + pfOffset + 128)}).at(0);
        drain();
        require(usefulPrefetches.count(key(consumer)) && usefulPrefetches.at(key(consumer)).first == pfLine,
                "warm isolation demand did not consume the exact prefetch line usefully");
        require(cacheCycles.count(key(consumer)) && completionCycles.count(key(consumer)) &&
                retiredTokens.count(key(consumer)) && !externalCycles.count(key(consumer)),
                "warm isolation ordinary owner did not hit, complete and retire");
        require(!d.cache$trackedValid && prefetchAcquires == acquiredBeforeConsume &&
                outstandingPrefetches.empty() && !d.get_io$$prefetchBusy(),
                "warm isolation did not clear the consumed token and drain all PF owners");
        std::cout << "MEMORY_PROOF_WARM_PF_CONSUMED mode=" << mode
                  << " token=" << consumer.index << ":" << consumer.tag << " pa=" << pfLine
                  << " useful_cycle=" << usefulPrefetches.at(key(consumer)).second
                  << " completion_cycle=" << completionCycles.at(key(consumer))
                  << " tracked_valid=" << unsigned(d.cache$trackedValid)
                  << " pf_acquires=" << prefetchAcquires << " status=PASS\n";
    }
    void run() {
        csr(0x3b0, allPmp); csr(0x3a0, 0x1f); csr(0x180, satp); csr(0x300, (1ULL << 17) | (1ULL << 11));
        require(d.get_io$$vm$$satp() == satp && d.get_io$$vm$$dataPrivilege() == 1, "real CSR setup did not establish Sv39 S access");
        one(add(25, 123456789)); one(add(26, 7)); one(add(30, 0x1133557799BBDDFFULL));
        one(load(1, va + 512)); one(store(va + 4096 + 512, 30)); // same real read/write translation keys, distinct cache lines
        flushCache(); // write back the dirty warm line; clean lines remain valid, so A/C/S0 were never touched
        for (uint64_t target : {ram, ram + farOffset, ram + 4096}) {
            require(!acceptedExternalLines.count(target), "warm setup accidentally fetched a target cold line");
            for (uint64_t warm : {ram + 512, ram + 576, ram + 4096 + 512, ram + 4096 + 576})
                require(((target >> 6) & 255) != ((warm >> 6) & 255), "warm/PF line aliases a target cache set");
        }
        require(d.get_io$$idle() && grants.empty() && outstandingMisses.empty() && outstandingPrefetches.empty(),
                "warm setup left a real accepted owner before the cold-miss window");
        delay = 300;
        beforeClosure = expectedBytes;
        require(((ram >> 6) & 255) != (((ram + farOffset) >> 6) & 255), "far witness shares the actual 256-set index");
        std::vector<Request> program{divide(), load(10, va)};
        for (unsigned i = 0; i < 8; ++i) program.push_back(store(va + 4096 + 8 * i, 10));
        for (unsigned i = 0; i < 7; ++i) program.push_back(load(11 + i, va + 8 + 8 * i));
        program.push_back(load(18, va + farOffset));
        const auto tokens = submit(program);
        old = tokens[1]; far = tokens.back();
        if (lateStoreFault) faultStore = tokens[2];
        closureStores.assign(tokens.begin() + 2, tokens.begin() + 10);
        closureLoads.assign(tokens.begin() + 10, tokens.begin() + 17);
        drain();
        require(cacheCycles.count(key(*old)) && externalCycles.count(key(*old)) && responseCycles.count(key(*old)),
                "old demand window is incomplete: cache=" + std::to_string(cacheCycles.count(key(*old))) +
                " external=" + std::to_string(externalCycles.count(key(*old))) +
                " response=" + std::to_string(responseCycles.count(key(*old))) +
                " old_index=" + std::to_string(old->index) + " old_tag=" + std::to_string(old->tag));
        std::cout << "MP_CLOSURE_TIMING old=" << old->index << ":" << old->tag << " far=" << far->index << ":" << far->tag
            << " old_query=" << queryCycles.at(key(*old)) << " old_start=" << startCycles.at(key(*old))
            << " old_cache=" << cacheCycles.at(key(*old)) << " old_tl=" << externalCycles.at(key(*old))
            << " old_first_response=" << responseCycles.at(key(*old))
            << " far_query=" << queryCycles.at(key(*far)) << " far_start=" << startCycles.at(key(*far))
            << " far_cache=" << cacheCycles.at(key(*far)) << " far_tl=" << externalCycles.at(key(*far))
            << " far_first_response=" << responseCycles.at(key(*far))
            << " proof_reads=" << proofReads << " proof_writes=" << proofWrites
            << " peak_ordinary=" << peakOrdinaryGrants << " pf_acquires=" << prefetchAcquires << "\n" << std::flush;
        const bool overlap = cacheCycles.at(key(*far)) < responseCycles.at(key(*old)) &&
                             externalCycles.at(key(*far)) < responseCycles.at(key(*old));
        require(overlap == bool(MEMORY_PROOF_ENABLED), "actual second cache/external demand overlap disagrees with OFF/ON contract");
        if (MEMORY_PROOF_ENABLED) {
            require(proofs.count(key(*far)), "far actual proof missing");
            for (Token t : closureStores) {
                require(proofs.count(key(t)) && proofs.at(key(t)).write, "older store independent actual write proof missing");
                if (startCycles.count(key(t)))
                    require(startCycles.at(key(t)) >= responseCycles.at(key(*old)), "dependent store started before A supplied rs2");
                else require(lateStoreFault, "positive store never started");
            }
            for (Token t : closureLoads) require(proofs.count(key(t)) && !proofs.at(key(t)).write, "older pending read proof missing");
            require(peakOrdinaryGrants >= 2, "two real ordinary demand owners never coexisted");
        }
        delay = 16; flushCache();
        for (unsigned i = 0; i < touchedBytes; ++i)
            require(backing.read(ram + i, 0) == expectedBytes.read(ram + i, 0), "final independently expected RAM byte mismatch");
        if (lateStoreFault) {
            require(MEMORY_PROOF_ENABLED && traps == 1 && !cancelled.empty(), "late fault control failed to recover exact younger context");
            const unsigned allocatedBefore = allocated;
            one(add(29, 0xC001D00D));
            require(allocated == allocatedBefore + 1 && architectural[29] == 0xC001D00D,
                    "post-fault ROB/PRF allocation failed to resume");
        } else {
            warmControl("sv39");
            csr(0x180, 0); bareMode = true;
            warmControl("bare");
        }
        require(allocated == retired + cancelled.size() && requests == responses, "final full-token/request drain mismatch");
        std::cout << "MEMORY_PROOF_FRONTIER_EXACT_PASS enabled=" << MEMORY_PROOF_ENABLED
                  << " old=" << old->index << ":" << old->tag << " far=" << far->index << ":" << far->tag
                  << " old_cache=" << cacheCycles.at(key(*old)) << " old_first_visible=" << responseCycles.at(key(*old))
                  << " far_cache=" << cacheCycles.at(key(*far)) << " far_external_tl=" << externalCycles.at(key(*far))
                  << " far_offset=" << farOffset << " old_set=" << ((ram >> 6) & 255)
                  << " far_set=" << (((ram + farOffset) >> 6) & 255)
                  << " pf_acquires=" << prefetchAcquires << " peak_ordinary=" << peakOrdinaryGrants
                  << " posted_requests=" << postedRequests << " envelope55=unqualified_component_schedule"
                  << " proof_reads=" << proofReads << " proof_writes=" << proofWrites << " retired=" << retired
                  << " traps=" << traps << " cancelled=" << cancelled.size() << " trap_cycle=" << trapCycle << "\n";
    }
};
int main(int argc, char **argv) {
    try {
        Bench b;
        const std::string mode = argc > 1 ? argv[1] : "";
        b.injectData = mode == "--inject-data"; b.injectProof = mode == "--inject-proof-token";
        b.lateStoreFault = mode == "--late-store-fault";
        b.injectMissingAcquire = mode == "--inject-missing-acquire";
        b.injectStoreDecode = mode == "--inject-store-decode";
        require(!b.lateStoreFault || MEMORY_PROOF_ENABLED, "late-store-fault requires actual frontier ON closure");
        b.run(); return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << "\n"; return 1; }
}
