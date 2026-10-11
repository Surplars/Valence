#include "PostedPreparationPriorityGsim.h"
#include "memory_proof_frontier_exact_reference.h"
#include "memory_state_oracle.h"
// Baseline control: shared-state raw observer intentionally absent.
#include <bit>
#include <algorithm>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
#include <vector>
#define MEMORY_PROOF_ENABLED 1
#ifndef PREPARATION_PRIORITY_ON
#define PREPARATION_PRIORITY_ON 0
#endif
#include <fstream>
using namespace memory_proof_exact_reference;
constexpr uint64_t farOffset = 128;
using Key = std::pair<unsigned, uint64_t>;
static Key key(Token t) { return {t.index, t.tag}; }
struct Request {
    bool valid = false, memory = false, store = false, system = false, divide = false, writes = false;
    bool atomic = false, fault = false, branch = false;
    unsigned rd = 0, rs1 = 0, rs2 = 0, size = 3;
    uint32_t instruction = 0x13;
    uint64_t branchTarget = 0, address = 0, pc = 0, expected = 0, expectedBeat = 0, expectedStore = 0, cause = 0;
};
static uint64_t sext(uint64_t value, unsigned width) {
    const uint64_t sign = 1ULL << (width - 1); return (value ^ sign) - sign;
}
static Request raw(uint32_t instruction) { Request r; r.valid = true; r.instruction = instruction; return r; }
static Request addi(unsigned rd, unsigned rs, int value) { return raw((unsigned(value & 4095) << 20) | (rs << 15) | (rd << 7) | 0x13); }
static Request shift(unsigned rd, unsigned rs, unsigned amount) { return raw((amount << 20) | (rs << 15) | (1 << 12) | (rd << 7) | 0x13); }
static Request load(unsigned rd, unsigned rs, int offset = 0, unsigned size = 3) {
    return raw((unsigned(offset & 4095) << 20) | (rs << 15) | (size << 12) | (rd << 7) | 3);
}
static Request store(unsigned rs, int offset, unsigned data, unsigned size = 3) {
    const unsigned imm = unsigned(offset) & 4095;
    return raw(((imm >> 5) << 25) | (data << 20) | (rs << 15) | (size << 12) | ((imm & 31) << 7) | 0x23);
}
static Request divide(unsigned rd = 24, unsigned rs1 = 25, unsigned rs2 = 26) {
    return raw((1U << 25) | (rs2 << 20) | (rs1 << 15) | (4U << 12) | (rd << 7) | 0x33);
}
static Request takenBranch(unsigned rs, unsigned offset = 8) {
    return raw((((offset >> 12) & 1) << 31) | (((offset >> 5) & 63) << 25) | (rs << 20) | (rs << 15) | (((offset >> 1) & 15) << 8) | (((offset >> 11) & 1) << 7) | 0x63);
}
static Request csrw(unsigned csr, unsigned rs = 31) { return raw((csr << 20) | (rs << 15) | (1 << 12) | 0x73); }
static std::vector<Request> constant(unsigned rd, uint64_t value) {
    std::vector<Request> code{addi(rd, 0, int((value >> 60) & 15))};
    for (int shiftBy = 56; shiftBy >= 0; shiftBy -= 4) {
        code.push_back(shift(rd, rd, 4)); code.push_back(addi(rd, rd, int((value >> shiftBy) & 15)));
    }
    return code;
}
struct Entry { Token token; Request request; bool started = false, canonical = false, requested = false; };
struct Grant { uint64_t address, due; unsigned source, sink, beat = 0; bool done = false, error = false, prefetch = false; };
struct PteReply { uint64_t due, data; };
struct CacheOwner { Token token; uint64_t data; bool write; };
// Full cache ownership is checked independently against accepted raw store intent.
struct OwnerContext { Key owner{}, cohort{}; uint64_t epoch = 0, line = 0; bool operator==(const OwnerContext &) const = default; };
struct OwnerReservation { unsigned mshr = 0, set = 0, way = 0; bool victimValid = false, victimDirty = false; uint64_t victim = 0; bool operator==(const OwnerReservation &) const = default; };
struct OwnerEvent { OwnerContext context; OwnerReservation reservation; bool operator==(const OwnerEvent &) const = default; };
struct RetainedOwner { OwnerEvent event; Bytes initial, merged; std::set<Key> members; bool acquired = false, grantAcked = false, refilled = false, installed = false, attached = false, sent = false, completed = false, released = false; unsigned grantBeats = 0, source = 0, wbSlot = 0; };
struct RetainedMember { OwnerContext context; unsigned ticket = 0; bool acknowledged = false, drained = false; };
class Bench {
    SPostedPreparationPriorityGsim d;
    memory_state_oracle::Oracle stateOracle;
    uint64_t stateChecks=0, stateStores=0, stateLoads=0, stateDualStores=0, stateThreeWrites=0;
    uint64_t stateKilledCapture=0, stateStaleCapture=0, stateStoreStarts=0, stateAtomicStarts=0;
    uint64_t stateFrontierDifferent=0, stateVirtualStoreDistinct=0, stateRetireAllocate=0, stateClearAllocate=0;
    uint64_t stateLoadWidths=0, stateStoreWidths=0, stateAllocationRows=0, stateRetireAllocateDistinct=0;
    std::array<std::optional<memory_state_oracle::Token>,64> lastStateOwner{};
    std::array<unsigned,64> lastStateClass{};
    uint64_t stateStoreLoadReuse=0, stateLoadStoreReuse=0;
    std::deque<Entry> live;
    std::vector<Entry> cancelled;
    std::deque<Entry> retainedRetiredStores;
    std::set<Key> localStoreAcks;
    std::deque<PteReply> ptes, physicalReplies;
    std::map<unsigned, Grant> grants;
    std::deque<std::pair<unsigned, uint64_t>> releaseAcks;
    std::optional<unsigned> grant;
    std::deque<CacheOwner> cacheOwners;
    std::array<uint64_t, 32> architectural{}, predicted{};
    std::map<Key, Proof> proofs;
    std::map<Key, uint64_t> queryCycles, startCycles, cacheCycles, externalCycles, responseCycles, completionCycles;
    std::set<Key> retiredTokens, checkedTokens, cacheReturned;
    std::map<Key, Request> acceptedIntents, allInstructions;
    std::map<Key, uint64_t> virtualIngress, virtualTranslatedReplies;
    unsigned contextRedirects = 0;
    std::map<Key, RetainedOwner> retainedOwners;
    std::map<Key, RetainedMember> retainedMembers;
    std::map<unsigned, Key> postedGrantSources, postedWbSlots;
    uint64_t lastReleaseCycle = 0, lastAckCycle = 0;
    unsigned lastReleaseSource = 0, lastAckSource = 0;
    uint64_t lastReleaseAddress = 0;
    std::set<uint64_t> acceptedExternalLines, acceptedPrefetchLines;
    std::map<Key, std::pair<uint64_t, uint64_t>> usefulPrefetches;
    std::map<uint64_t, Token> outstandingMisses;
    struct Prefetch { Token origin; uint64_t candidateCycle; unsigned slot; };
    std::map<uint64_t, Prefetch> outstandingPrefetches;
    std::map<uint64_t, std::pair<Token, uint64_t>> nextLineAuthorities;
    std::optional<std::array<uint64_t, 26>> heldFullCache;
    std::optional<std::tuple<uint64_t, uint64_t, bool, unsigned>> heldCache;
    std::map<Key, uint64_t> issuedEpoch;
    uint64_t nextPc = 0x1000;
    unsigned cBeat = 0, cSource = 0, cOpcode = 0;
    uint64_t cAddress = 0;
public:
    Tables tables;
    Bytes backing, expectedBytes, beforeClosure, committedBytes;
    uint64_t cycle = 0, delay = 16, releaseDelay = 2, maxReleaseDelay = 0;
    std::map<unsigned, uint64_t> releaseSentCycles;
    unsigned allocated = 0, retired = 0, requests = 0, responses = 0, acquires = 0, peakGrants = 0;
    unsigned proofReads = 0, proofWrites = 0, frontierOverlap = 0, firstResponseVisible = 0;
    bool flush = false, injectData = false, injectProof = false, injectMissingAcquire = false, bareMode = true, lateStoreFault = false;
    bool commitEnable = true, timerInterrupt = false, injectTiming = false, injectToken = false;
    bool injectState = false, injectStateOwner = false, injectLineOwner = false;
    std::optional<Token> probe, targetStore, targetLoad, olderLoad, blockingAtomic, recoveryTarget, staleStageToken;
    unsigned stagedAbaWitness = 0;
    std::optional<Token> systemBoundary;
    unsigned rawStageS = 0, rawStageA = 0, rawCompetition = 0, busyBeforeStore = 0, systemBoundaryWaits = 0, systemBoundaryRetired = 0, finalDrainSelectionWitness = 0;
    uint64_t firstRawCompetition = 0, targetDrainEdge = 0;
    std::optional<Token> olderDependency;
    uint64_t firstOlderReady = 0, firstOlderStage = 0;
    bool previousOlderReady = false, storeBeforeOlderReady = false;
    bool recoveringRequest = false, allowIrq = false;
    bool witnessActive = false;
    uint64_t firstHead = 0, firstLegalHead = 0, firstStart = 0, firstLoadStart = 0;
    unsigned nonheadPrepared = 0, contested = 0, stageStore = 0, stageLoad = 0, busyLoadBlocks = 0;
    unsigned atomicBlockStages = 0, releaseAckCount = 0, aliasStalls = 0, actualAtomicBypasses = 0;
    unsigned observedCycles = 0, originalReadyCycles = 0, olderPreemptions = 0, recoveryEvents = 0, interruptDrainCycles = 0, contextEpochCycles = 0;
    unsigned decoderChecks = 0, reusedIndices = 0, physicalTransactions = 0, deniedStoreCycles = 0, finalDrainEdges = 0, residualStoreStages = 0, preparedBeforeDrain = 0, ownerWritebacks = 0, ownerWritebackCompletions = 0;
    bool previousBusy = false, previousStageS = false, verifiedTargetPmp = false, targetPhysicalStoreContract = false;
    uint64_t retireDigest = 1469598103934665603ULL;
    unsigned selectedSeals = 0, heldCacheCycles = 0, postedAccepted = 0, postedDrained = 0, postedReleased = 0;
    std::set<Key> postedMembers, drainedMembers;
    std::map<unsigned, uint64_t> tokenSlots;
    std::ofstream trace;
    std::string caseName = "main";
    uint64_t mstatus = 0, pmpCfg = 0, pmpAddress = 0, softwareSatp = 0, beforeContextEpoch = 0;
    unsigned retirementHoldWitness = 0;
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
#define DRIVE(N) \
        d.set_io$$instruction##N##$$valid(in[N].valid); \
        d.set_io$$instruction##N##$$bits(in[N].instruction); \
        d.set_io$$pc##N(in[N].pc);
        DRIVE(0) DRIVE(1)
#undef DRIVE
        d.set_io$$commitEnable(commitEnable); d.set_io$$timerInterrupt(timerInterrupt); d.set_io$$probeIndex(probe ? probe->index : 0); d.set_io$$inspectRegister(cycle % 32);
        d.set_io$$recover$$valid(recoveringRequest); d.set_io$$recover$$bits$$inclusive(1);
        d.set_io$$recover$$bits$$token$$index(recoveryTarget ? recoveryTarget->index : 0); d.set_io$$recover$$bits$$token$$tag(recoveryTarget ? recoveryTarget->tag : 0);
        const bool physicalValid = !physicalReplies.empty() && physicalReplies.front().due <= cycle;
        d.set_io$$physical$$request$$ready(1); d.set_io$$physical$$response$$valid(physicalValid);
        d.set_io$$physical$$response$$bits$$data(physicalValid ? physicalReplies.front().data : 0); d.set_io$$physical$$response$$bits$$error(0);
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
    void observeMemoryState() { /* Baseline control: no reuse-specific observer. */ }
    void rememberMemoryOwner(Token t,const Request&r) { /* Baseline control: no reuse-specific observer. */ }
    void memoryStateSummary() { /* Baseline control: no reuse-specific observer. */ }
    std::vector<Token> tick(std::array<Request, 2> in = {}) {
        const bool pv = !ptes.empty() && ptes.front().due <= cycle;
        drive(in); d.step(); observeMemoryState();
        std::vector<Token> accepted;
        require(d.get_io$$committedValue() == architectural[cycle % 32], "independent committed register mismatch");
#define ACCEPT(N) \
        if (d.get_io$$renamed##N##$$valid()) { \
            require(in[N].valid, "unoffered allocation"); \
            const Token t{unsigned(d.get_io$$renamed##N##$$bits$$token$$index()), uint64_t(d.get_io$$renamed##N##$$bits$$token$$tag())}; \
            Request r = interpret(in[N]); ++decoderChecks; if (tokenSlots.count(t.index)) { require(tokenSlots.at(t.index) != t.tag, "ROB index reused without changing full tag"); ++reusedIndices; } tokenSlots[t.index] = t.tag; \
            require(bool(d.get_io$$decoded##N##$$memory()) == r.memory && bool(d.get_io$$decoded##N##$$store()) == r.store && bool(d.get_io$$decoded##N##$$atomic()) == r.atomic && bool(d.get_io$$decoded##N##$$system()) == r.system && bool(d.get_io$$decoded##N##$$mulDiv()) == r.divide, "actual raw decoder instruction class differs from independent interpreter"); \
            require(bool(d.get_io$$decoded##N##$$useImmediate()) == !(r.store || r.divide || r.atomic || r.branch), "actual raw decoder register/immediate ownership mismatch"); \
            if (r.memory) require(d.get_io$$decoded##N##$$memorySize() == r.size, "actual raw decoder memory width mismatch"); \
            if (r.writes && r.rd) predicted[r.rd] = r.expected; \
            require(allInstructions.emplace(key(t), r).second, "original full-token instruction reused"); rememberMemoryOwner(t,r); live.push_back({t, r}); accepted.push_back(t); ++allocated; \
        }
        ACCEPT(0) ACCEPT(1)
#undef ACCEPT
        if (pv && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid()) ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())});
        if (!physicalReplies.empty() && physicalReplies.front().due <= cycle && d.get_io$$physical$$response$$ready()) physicalReplies.pop_front();
        if (d.get_io$$physical$$request$$valid()) {
            const uint64_t address = d.get_io$$physical$$request$$bits$$address();
            const bool atomic = d.get_io$$physical$$request$$bits$$atomic();
            require(atomic || address < ram || address >= ram + ramBytes, "ordinary RAM escaped real cache path");
            const bool write = d.get_io$$physical$$request$$bits$$write();
            uint64_t atomicResult = 0;
            if (atomic) {
                require(d.get_io$$physical$$request$$bits$$atomicOp() == 0 && d.get_io$$physical$$request$$bits$$size() == 3 && !(address & 7), "independent AMOADD.D bypass shape/op mismatch");
                atomicResult = backing.read(address, 3);
                backing.write(address, atomicResult + d.get_io$$physical$$request$$bits$$data(), 3); ++actualAtomicBypasses;
            } else if (write) {
                const uint64_t data = d.get_io$$physical$$request$$bits$$data();
                const unsigned mask = d.get_io$$physical$$request$$bits$$mask();
                for (unsigned lane = 0; lane < 8; ++lane) if (mask & (1u << lane)) backing.write((address & ~7ULL) + lane, data >> (lane * 8), 0);
            }
            physicalReplies.push_back({cycle + 3, atomic ? atomicResult : write ? 0 : backing.read(address & ~7ULL, 3)}); ++physicalTransactions;
        }

        if (caseName == "virtual_store" && d.get_io$$upstreamFire() && d.get_io$$canonicalOrigin$$valid()) {
            const Token t{unsigned(d.get_io$$canonicalOrigin$$bits$$token$$index()), uint64_t(d.get_io$$canonicalOrigin$$bits$$token$$tag())};
            const auto &e = owner(t);
            require(!bareMode && e.started && e.request.store && d.get_io$$upstreamAddress() == e.request.address && !d.get_io$$upstreamPrechecked(), "virtual ingress lost original raw store/full token");
            require(virtualIngress.emplace(key(t), cycle).second, "virtual store ingress repeated");
        }
        if (caseName == "virtual_store" && d.adapter$translatedReply && d.adapter$translated$_do_enq_T) {
            const bool waiting = d.adapter$waiting;
            const bool originValid = waiting ? d.adapter$savedCanonicalStoreOrigin$$valid : d.adapter$virtualRequests$head$$canonicalStoreOrigin$$valid;
            if (originValid) {
                const Token t{unsigned(waiting ? d.adapter$savedCanonicalStoreOrigin$$bits$$token$$index : d.adapter$virtualRequests$head$$canonicalStoreOrigin$$bits$$token$$index), uint64_t(waiting ? d.adapter$savedCanonicalStoreOrigin$$bits$$token$$tag : d.adapter$virtualRequests$head$$canonicalStoreOrigin$$bits$$token$$tag)};
                const auto &e = owner(t);
                const uint64_t originalVa = waiting ? d.adapter$savedRequest$$address : d.adapter$virtualRequests$head$$request$$address;
                require(e.request.store && virtualIngress.count(key(t)) && originalVa == e.request.address, "real translation response lost original virtual store owner");
                require(virtualTranslatedReplies.emplace(key(t), cycle).second, "virtual store translation response repeated");
            }
        }
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
            Proof expected{t, uint32_t(d.get_io$$epoch()), e.request.address, physicalOf(e.request.address), e.request.store, e.request.size, unsigned(((1u << (1u << e.request.size)) - 1) << (e.request.address & 7))};
            if (injectProof) expected.token.tag ^= 1ULL << 63;
            require(observed == expected && queryCycles.count(key(t)) && cycle > queryCycles[key(t)],
                    "actual inserted proof differs from independent full-token query/permission expectation");
            proofs[key(t)] = observed;
            e.request.store ? ++proofWrites : ++proofReads;
        }
        if (d.get_io$$lsuStart()) {
            const Token t{unsigned(d.get_io$$lsuToken$$index()), uint64_t(d.get_io$$lsuToken$$tag())};
            Token expectedToken = t; if (injectToken && witnessActive && targetStore && t == *targetStore) expectedToken.tag ^= 1ULL << 63;
            auto &e = owner(expectedToken);
            require(!e.started && d.get_io$$lsuVa() == e.request.address, "duplicate start or lost original VA");
            issuedEpoch[key(t)] = d.adapter$postedEpoch;
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
            if (caseName == "virtual_store") require(virtualTranslatedReplies.count(key(t)) && virtualTranslatedReplies.at(key(t)) < cycle && !d.get_io$$frozenRequest$$valid(), "virtual checked PA did not follow original actual translation response");
            require(checkedTokens.insert(key(t)).second, "duplicate checked certificate");
        }
        const bool cv = d.get_io$$cacheRequest$$valid();
        if (heldCache) require(cv, "held cache request VALID withdrawn");
        if (cv) {
            std::array<uint64_t, 26> fullPayload{d.get_io$$cacheRequest$$bits$$atomic(), d.get_io$$cacheRequest$$bits$$atomicOp(),
                d.get_io$$cacheRequest$$bits$$address(), d.get_io$$cacheRequest$$bits$$write(), d.get_io$$cacheRequest$$bits$$size(),
                d.get_io$$cacheRequest$$bits$$data(), d.get_io$$cacheRequest$$bits$$mask(), d.get_io$$cacheRequest$$bits$$virtualized(),
                d.get_io$$cacheRequest$$bits$$precheckedLoad(), d.get_io$$cacheRequest$$bits$$translationEpoch(),
                d.get_io$$cacheRequest$$bits$$prefetchNextAllowed(), d.get_io$$cacheRequest$$bits$$uncached(), d.get_io$$cachePostedProof()};
            if (d.get_io$$cachePostedProof()) {
                // Source-bound passive ABI: physical requestProof is checked.deq.postedProof.
                const std::array<uint64_t, 13> proof{d.adapter$checked_checked$head$$postedProof$$bits$$token$$index,
                    d.adapter$checked_checked$head$$postedProof$$bits$$token$$tag, d.adapter$checked_checked$head$$postedProof$$bits$$epoch,
                    d.adapter$checked_checked$head$$postedProof$$bits$$address, d.adapter$checked_checked$head$$postedProof$$bits$$data,
                    d.adapter$checked_checked$head$$postedProof$$bits$$mask, d.adapter$checked_checked$head$$postedProof$$bits$$size,
                    d.adapter$checked_checked$head$$postedProof$$bits$$headAuthorized, d.adapter$checked_checked$head$$postedProof$$bits$$physicalPmpAllowed,
                    d.adapter$checked_checked$head$$postedProof$$bits$$originalPhysical, d.adapter$checked_checked$head$$postedProof$$bits$$integerOrigin,
                    d.adapter$checked_checked$head$$postedProof$$bits$$legacyPostedAccepted, d.adapter$checked_checked$head$$postedProof$$bits$$finalChecked};
                std::copy(proof.begin(), proof.end(), fullPayload.begin() + 13);
            }
            if (heldFullCache) require(fullPayload == *heldFullCache, "held complete cache request/proof payload changed");
            heldFullCache = !d.get_io$$cacheRequestFire() ? std::optional{fullPayload} : std::nullopt;
            const auto payload = std::make_tuple(uint64_t(d.get_io$$cacheRequest$$bits$$address()),
                uint64_t(d.get_io$$cacheRequest$$bits$$data()), bool(d.get_io$$cacheRequest$$bits$$write()),
                unsigned(d.get_io$$cacheRequest$$bits$$mask()));
            if (heldCache) { require(payload == *heldCache, "held cache payload changed"); ++heldCacheCycles; }
            heldCache = !d.get_io$$cacheRequestFire() ? std::optional{payload} : std::nullopt;
            if (d.get_io$$cacheRequestFire()) {
                const uint64_t pa = std::get<0>(payload); const bool write = std::get<2>(payload);
                Entry *entry = nullptr;
                auto matches = [&](const Entry &e) {
                    return e.request.memory && e.started && (e.request.atomic || !e.requested) && (e.request.atomic || e.request.store == write) && physicalOf(e.request.address) == pa;
                };
                for (auto &e : live) if (matches(e)) { entry = &e; break; }
                if (!entry) for (auto &e : cancelled) if (matches(e)) { entry = &e; break; }
                if (!entry) for (auto &e : retainedRetiredStores) if (matches(e)) { entry = &e; break; }
                require(entry && std::get<3>(payload) == unsigned(((1u << (1u << entry->request.size)) - 1) << (entry->request.address & 7)), "cache accepted unowned/malformed ordinary request");
                require(d.get_io$$cacheRequest$$bits$$size() == entry->request.size && bool(d.get_io$$cacheRequest$$bits$$atomic()) == entry->request.atomic &&
                    !d.get_io$$cacheRequest$$bits$$virtualized() && !d.get_io$$cacheRequest$$bits$$precheckedLoad() && d.get_io$$cacheRequest$$bits$$translationEpoch() == 0, "cache request shape/authorization metadata differs from independent original");
                if (entry->request.atomic) require(d.get_io$$cacheRequest$$bits$$atomicOp() == 0 && d.get_io$$cacheRequest$$bits$$data() + entry->request.expected == entry->request.expectedStore, "atomic cache request lost original rs2/op");
                if (d.get_io$$cachePostedProof()) {
                    require(fullPayload[13] == entry->token.index && fullPayload[14] == entry->token.tag && fullPayload[15] == issuedEpoch.at(key(entry->token)) &&
                        fullPayload[16] == pa && fullPayload[17] == std::get<1>(payload) && fullPayload[18] == std::get<3>(payload) && fullPayload[19] == entry->request.size,
                        "checked posted proof lost original CPU token/epoch/payload");
                    for (unsigned i = 20; i < 26; ++i) require(fullPayload[i] == 1, "checked posted proof lost original head/PMP/integer authority");
                }
                if (write) require(std::get<1>(payload) == (entry->request.expectedStore << (8 * (entry->request.address & 7))), "store bytes differ from independent dependency value");
                entry->requested = true; cacheCycles[key(entry->token)] = cycle; acceptedIntents[key(entry->token)] = entry->request;
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
                cacheOwners.push_back({entry->token, entry->request.expectedBeat, write}); ++requests;
                // demandAlloc is cpuFire && needsMissSlot, so posted joins also
                // assert it. Only the actual posted newLine event allocates an MSHR.
                // observeOwners independently checks every join's retained context.
                const bool postedAccept = d.get_io$$owner$$accepted$$valid();
                const bool postedNew = postedAccept && d.get_io$$owner$$accepted$$bits$$newLine();
                if (d.get_io$$demandMiss()) require(d.get_io$$demandMissAddress() == pa, "cache miss address attribution mismatch");
                if ((d.get_io$$demandMiss() && !postedAccept) || postedNew || (injectLineOwner && postedAccept && !postedNew)) {
                    if(outstandingMisses.count(pa&~63ULL)||outstandingPrefetches.count(pa&~63ULL)) {
                        std::cerr<<"LINE_OWNER_DIAGNOSTIC cycle="<<cycle<<" pa="<<pa<<" tag="<<entry->token.tag<<" slot="<<entry->token.index
                          <<" misses="<<outstandingMisses.count(pa&~63ULL)<<" prefetch="<<outstandingPrefetches.count(pa&~63ULL)
                          <<" E="<<unsigned(d.get_io$$tl$$e$$valid())<<" sink="<<unsigned(d.get_io$$tl$$e$$bits$$sink())<<" grants="<<grants.size()<<"\n";
                        std::cerr<<"LINE_EVENT demandMiss="<<unsigned(d.get_io$$demandMiss())<<" postedAccepted="<<unsigned(d.get_io$$owner$$accepted$$valid())<<" newLine="<<unsigned(d.get_io$$owner$$accepted$$bits$$newLine())<<"\n";
                        if(outstandingMisses.count(pa&~63ULL)) {const auto old=outstandingMisses.at(pa&~63ULL);std::cerr<<"LINE_OLD_OWNER tag="<<old.tag<<" slot="<<old.index<<" request_cycle="<<cacheCycles.at(key(old))<<"\n";}
                        for(const auto &[src,g]:grants)std::cerr<<"LINE_GRANT source="<<src<<" line="<<g.address<<" sink="<<g.sink<<" done="<<g.done<<" beat="<<g.beat<<"\n";
                    }
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
            if (d.get_io$$cacheResponseFire()) { cacheReturned.insert(key(r.token)); cacheOwners.pop_front(); ++responses; }
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
            if (grant) { auto &g = grants.at(*grant);
                if (postedGrantSources.count(*grant)) { auto &o = retainedOwners.at(postedGrantSources.at(*grant)); require(o.grantBeats < 8 && g.address == o.event.context.line && !g.error, "posted GrantData changed full retained owner"); ++o.grantBeats; }
                if (++g.beat == 8) { g.done = true; grant.reset(); } }
            else {
                const auto source = releaseAcks.front().first;
                require(releaseSentCycles.count(source), "ReleaseAck lost actual released source");
                lastAckCycle = cycle; lastAckSource = source;
                maxReleaseDelay = std::max(maxReleaseDelay, cycle - releaseSentCycles.at(source));
                releaseSentCycles.erase(source); ++releaseAckCount; releaseAcks.pop_front();
            }
        }
        if (d.get_io$$tl$$e$$valid()) {
            const unsigned sink = d.get_io$$tl$$e$$bits$$sink();
            auto it = std::find_if(grants.begin(), grants.end(), [&](const auto &g) { return g.second.sink == sink; });
            require(it != grants.end() && it->second.done, "GrantAck lost full external source/sink owner");
            if (it->second.prefetch) require(outstandingPrefetches.erase(it->second.address) == 1, "lost prefetch drain owner");
            else require(outstandingMisses.erase(it->second.address) == 1, "lost ordinary drain owner");
            if (postedGrantSources.count(it->first)) {
                auto &o = retainedOwners.at(postedGrantSources.at(it->first));
                require(o.grantBeats == 8 && !o.grantAcked, "posted E acknowledgement lost/duplicated full retained owner");
                o.grantAcked = true; postedGrantSources.erase(it->first);
            }
            grants.erase(it);
        }
        if (d.get_io$$tl$$c$$valid() && cycle % 5 != 3) {
            const unsigned opcode = d.get_io$$tl$$c$$bits$$opcode(), source = d.get_io$$tl$$c$$bits$$source();
            const uint64_t address = d.get_io$$tl$$c$$bits$$address();
            if (!cBeat) { cOpcode = opcode; cSource = source; cAddress = address; }
            require(opcode == cOpcode && source == cSource && address == cAddress && (opcode == 6 || opcode == 7), "release burst lineage changed");
            if (opcode == 7) backing.write(address + 8 * cBeat, d.get_io$$tl$$c$$bits$$data(), 3);
            if (++cBeat == (opcode == 7 ? 8U : 1U)) { require(!releaseSentCycles.count(source), "Release reused source before late ACK"); lastReleaseCycle = cycle; lastReleaseSource = source; lastReleaseAddress = address; releaseSentCycles[source] = cycle; releaseAcks.push_back({source, cycle + releaseDelay}); cBeat = 0; }
        }
#define COMPLETE(N) \
        if (d.get_io$$issued##N##$$valid()) { \
            const Token t{unsigned(d.get_io$$issued##N##$$bits$$token$$index()), uint64_t(d.get_io$$issued##N##$$bits$$token$$tag())}; \
            const auto &e = owner(t); \
            if (e.request.writes && e.request.rd && !e.request.fault) require(d.get_io$$issued##N##$$bits$$data() == e.request.expected, "independent completion value/full-token mismatch"); \
            completionCycles[key(t)] = cycle; \
            if (e.request.memory) require(bool(d.get_io$$issued##N##$$bits$$exception()) == e.request.fault && e.started, "memory completion/exception lost its independent started owner"); \
            if (e.request.store && !e.request.fault) require(localStoreAcks.insert(key(t)).second, "local store acknowledgement duplicated"); \
            if (e.request.memory && !e.request.store) { \
                require(bool(d.get_io$$issued##N##$$bits$$exception()) == e.request.fault, "load fault completion differs from independent exception"); \
                if (!e.request.fault) require(d.get_io$$issued##N##$$bits$$data() == e.request.expected, "load completion lost independent data/full token"); \
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
            if (e.request.memory && !e.request.store) require(responseCycles.count(key(t)), "load/atomic retired without real response"); \
            if (e.request.store) { require(localStoreAcks.count(key(t)) && completionCycles.at(key(t)) <= cycle, "store retired without original local LSU completion"); retainedRetiredStores.push_back(e); } \
            if (e.request.system && (((e.request.instruction & 127) == 0x0f) || (e.request.instruction >> 20) == 0x180)) require(!d.get_io$$cpuPostedBusy() && !d.get_io$$cachePostedBusy(), "raw system boundary retired before original posted drain"); \
            if (systemBoundary && t == *systemBoundary) ++systemBoundaryRetired; \
            if (e.request.store || e.request.atomic) committedBytes.write(physicalOf(e.request.address), e.request.expectedStore, e.request.size); \
            for (uint64_t value : std::array<uint64_t, 3>{e.request.pc, uint64_t(e.request.instruction), e.request.writes && e.request.rd ? uint64_t(d.get_io$$commit##N##$$bits$$data()) : 0ULL}) { retireDigest ^= value; retireDigest *= 1099511628211ULL; } \
            ++retired; \
        }
        RETIRE(0) RETIRE(1)
#undef RETIRE
        if (d.get_io$$trap$$valid()) {
            require(!d.get_io$$cpuPostedBusy() && !d.get_io$$cachePostedBusy(), "precise fault/interrupt crossed retained posted consumer ownership");
            require(!live.empty() && (live.front().request.fault || allowIrq), "trap lacks independently expected fault owner");
            const auto &e = live.front();
            const Token t{unsigned(d.get_io$$trap$$bits$$token$$index()), uint64_t(d.get_io$$trap$$bits$$token$$tag())};
            require(t == e.token && d.get_io$$trap$$bits$$cause() == (allowIrq ? (1ULL << 63) | 7 : e.request.cause) &&
                    d.get_io$$trap$$bits$$pc() == e.request.pc && d.get_io$$trap$$bits$$tval() == (allowIrq ? 0 : e.request.address),
                    "precise trap cause/original VA/PC/full-token mismatch");
            for (auto &e : live) { require(!retiredTokens.count(key(e.token)), "younger owner retired across older fault"); cancelled.push_back(e); }
            live.clear(); predicted = architectural; expectedBytes = committedBytes; timerInterrupt = false;
            ++traps; trapCycle = cycle;
        }
        if (d.get_io$$redirect$$valid() && !d.get_io$$trap$$valid()) {
            const Token t{unsigned(d.get_io$$redirect$$bits$$token$$index()), uint64_t(d.get_io$$redirect$$bits$$token$$tag())};
            require(allInstructions.count(key(t)), "real redirect lost original decoded full-token owner");
            const auto &r = allInstructions.at(key(t));
            require((r.branch || r.system) && d.get_io$$redirect$$bits$$pc() == r.pc && d.get_io$$redirect$$bits$$target() == (r.branch ? r.branchTarget : r.pc + 4), "real redirect differs from independent raw branch/system target");
            bool younger = retiredTokens.count(key(t));
            for (auto it = live.begin(); it != live.end();) {
                if (younger) { require(!it->started, "directed redirect cancelled already-started memory owner"); cancelled.push_back(*it); it = live.erase(it); }
                else { if(it->token == t) younger = true; ++it; }
            }
            require(younger, "redirect origin absent from live/retired original order");
            predicted = architectural; expectedBytes = committedBytes;
            for(const auto &e:live) { if(e.request.writes && e.request.rd) predicted[e.request.rd]=e.request.expected; if(e.request.store && !e.request.fault) expectedBytes.write(physicalOf(e.request.address),e.request.expectedStore,e.request.size); }
            nextPc = d.get_io$$redirect$$bits$$target();
            if(r.branch) ++recoveryEvents;
            if(systemBoundary && t == *systemBoundary) ++contextRedirects;
        }
        observe();
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
        for (unsigned i = 0; i < 5000 && (!live.empty() || !cacheOwners.empty() || !ptes.empty() || !physicalReplies.empty() || !grants.empty() || !outstandingPrefetches.empty() || !d.get_io$$idle()); ++i) tick();
        if (!live.empty() || !cacheOwners.empty() || !grants.empty()) {
            std::cerr << "DRAIN_DIAGNOSTIC cycle=" << cycle << " live=" << live.size() << " cache=" << cacheOwners.size() << " grants=" << grants.size() << " posted=" << bool(d.get_io$$cpuPostedBusy() || d.get_io$$cachePostedBusy()) << " headvalid=" << bool(d.get_io$$headValid()) << " head=" << (d.get_io$$headValid() ? unsigned(d.get_io$$headToken$$index()) : 0) << " recovering=" << bool(d.get_io$$recovering()) << " context=" << bool(d.get_io$$contextMemoryEpoch()) << " epoch=" << uint64_t(d.adapter$postedEpoch) << " satp=" << d.get_io$$vm$$satp() << "\n";
            for(const auto &e:live) std::cerr << "DRAIN_LIVE index=" << e.token.index << " tag=" << e.token.tag << " raw=" << e.request.instruction << " started=" << e.started << " requested=" << e.requested << "\n";
        }
        require(live.empty() && cacheOwners.empty() && ptes.empty() && physicalReplies.empty() && grants.empty(), "accepted owners failed to drain");
        for (unsigned i = 0; i < 12; ++i) tick();
        require(d.get_io$$idle() && requests == responses && outstandingMisses.empty() && outstandingPrefetches.empty() &&
                !d.get_io$$prefetchBusy() && !d.get_io$$cpuPostedBusy() && !d.get_io$$cachePostedBusy(),
                "backend/adapter/PF/posted owner drain mismatch");
    }
    void one(Request r) { submit({r}); drain(); }
    void setreg(unsigned reg, uint64_t value) { submit(constant(reg, value)); drain(); require(architectural[reg] == value, "constant sequence did not retire exact value"); }
    void csr(unsigned address, uint64_t value) { setreg(31, value); one(csrw(address)); }
    void flushCache() {
        flush = true; bool done = false;
        for (unsigned i = 0; i < 3000 && !done; ++i) { tick(); done = d.get_io$$cacheFlushDone(); }
        require(done, "real cache flush failed to finish"); flush = false;
        for (unsigned i = 0; i < 8; ++i) tick();
        require(grants.empty() && releaseAcks.empty(), "flush release ownership not drained");
    }
    Request interpret(Request r) {
        const uint32_t x = r.instruction;
        const unsigned op = x & 127, f = (x >> 12) & 7;
        r.rd = (x >> 7) & 31; r.rs1 = (x >> 15) & 31; r.rs2 = (x >> 20) & 31;
        const uint64_t imm = sext(x >> 20, 12);
        if (op == 0x13) {
            require(f == 0 || (f == 1 && (x >> 26) == 0), "unsupported independent immediate encoding");
            r.writes = true; r.expected = f == 0 ? predicted[r.rs1] + imm : predicted[r.rs1] << ((x >> 20) & 63);
        } else if (op == 0x33 && (x >> 25) == 1 && f == 4) {
            r.writes = true; r.divide = true;
            const int64_t a = int64_t(predicted[r.rs1]), b = int64_t(predicted[r.rs2]);
            r.expected = !b ? ~0ULL : (a == INT64_MIN && b == -1 ? uint64_t(a) : uint64_t(a / b));
        } else if (op == 0x63) {
            require(f == 0 && predicted[r.rs1] == predicted[r.rs2], "only independently taken BEQ is authored");
            r.branch = true;
            const uint64_t offset = sext(((uint64_t(x) >> 31) << 12) | (((x >> 7) & 1) << 11) | (((x >> 25) & 63) << 5) | (((x >> 8) & 15) << 1), 13);
            r.branchTarget = r.pc + offset;
        } else if (op == 3 || op == 0x23 || op == 0x2f) {
            r.memory = true; r.store = op == 0x23; r.atomic = op == 0x2f; r.writes = !r.store; r.size = f & 3;
            require(r.store ? f <= 3 : f != 7, "unsupported independent memory encoding");
            const uint64_t offset = r.atomic ? 0 : r.store ? sext(((x >> 25) << 5) | ((x >> 7) & 31), 12) : imm;
            r.address = predicted[r.rs1] + offset;
            r.expectedStore = predicted[r.rs2];
            r.fault = (r.address & ((1ULL << r.size) - 1)) != 0;
            r.cause = r.store ? 6 : 4;
            const bool writeAccess = r.store || r.atomic;
            const unsigned mode = (pmpCfg >> 3) & 3;
            uint64_t low = 0, high = 0;
            if (mode == 1) high = pmpAddress << 2;
            else if (mode == 2) { low = pmpAddress << 2; high = low + 4; }
            else if (mode == 3) {
                unsigned ones = 0; while (ones < 54 && ((pmpAddress >> ones) & 1)) ++ones;
                const uint64_t length = 1ULL << (ones + 3); low = (pmpAddress << 2) & ~(length - 1); high = low + length;
            }
            const bool applies = mode && (pmpCfg & 128) && r.address < high && r.address + (1ULL << r.size) > low;
            if (!r.fault && applies && (r.address < low || r.address + (1ULL << r.size) > high || !(pmpCfg & (writeAccess ? 2 : 1)))) {
                r.fault = true; r.cause = writeAccess ? 7 : 5;
            }
            if (!r.fault) {
                const uint64_t pa = physicalOf(r.address);
                if (r.store) expectedBytes.write(pa, r.expectedStore, r.size);
                else {
                    r.expectedBeat = expectedBytes.read(pa & ~7ULL, 3); r.expected = expectedBytes.read(pa, r.size);
                    if (r.atomic) { require((x >> 27) == 0 && r.size == 3, "only independent AMOADD.D supported"); r.expectedStore += r.expected; expectedBytes.write(pa, r.expectedStore, 3); }
                    if (f < 4 && r.size < 3) r.expected = sext(r.expected, 8U << r.size);
                }
            }
        } else if (op == 0x73 && f == 1 && r.rd == 0) {
            r.system = true;
            const unsigned csr = x >> 20;
            if (csr == 0x300) mstatus = predicted[r.rs1];
            if (csr == 0x3a0) pmpCfg = predicted[r.rs1];
            if (csr == 0x3b0) pmpAddress = predicted[r.rs1];
            if (csr == 0x180) softwareSatp = predicted[r.rs1];
            bareMode = !((softwareSatp >> 60) != 0 && (mstatus & (1ULL << 17)) && ((mstatus >> 11) & 3) != 3);
        } else if (op == 0x0f) { r.system = true; }
        else throw std::runtime_error("unsupported raw instruction in independent interpreter");
        return r;
    }
    void observeOwners() {
#define OWNER_KEY(F) Key{unsigned(d.get_io$$##F##$$slot()), uint64_t(d.get_io$$##F##$$generation())}
#define CONTEXT(F) OwnerContext{OWNER_KEY(F##$$owner), OWNER_KEY(F##$$cohortRoot), uint64_t(d.get_io$$##F##$$epoch()), uint64_t(d.get_io$$##F##$$lineAddress())}
#define RESERVATION(F) OwnerReservation{unsigned(d.get_io$$##F##$$mshr()), unsigned(d.get_io$$##F##$$set()), unsigned(d.get_io$$##F##$$way()), bool(d.get_io$$##F##$$victimValid()), bool(d.get_io$$##F##$$victimDirty()), (d.get_io$$##F##$$victimValid() ? uint64_t(d.get_io$$##F##$$victimAddress()) : 0ULL)}
#define EVENT(F) OwnerEvent{CONTEXT(F##$$context), RESERVATION(F##$$reservation)}
        auto checkedOwner = [&](const OwnerEvent &event) -> RetainedOwner & {
            require(retainedOwners.count(event.context.owner), "owner event lost full slot/generation");
            auto &o = retainedOwners.at(event.context.owner);
            require(o.event == event && !o.released, "owner event changed original context/reservation or followed release"); return o;
        };
        if (d.get_io$$owner$$accepted$$valid()) {
            const Token t{unsigned(d.get_io$$owner$$accepted$$bits$$member$$token$$index()), uint64_t(d.get_io$$owner$$accepted$$bits$$member$$token$$tag())};
            const Key tk = key(t); const auto context = CONTEXT(owner$$accepted$$bits$$member$$context);
            const OwnerEvent event{context, RESERVATION(owner$$accepted$$bits$$reservation)};
            require(acceptedIntents.count(tk) && cacheCycles.at(tk) == cycle, "posted acceptance lacks same-edge independently decoded store");
            const auto &r = acceptedIntents.at(tk);
            require(r.store && !r.fault && context.epoch == issuedEpoch.at(tk) && context.line == (r.address & ~63ULL) && event.reservation.set == ((context.line >> 6) & 255) && event.reservation.way < 2 && event.reservation.mshr < 2, "posted acceptance changed original address/physical resource");
            if (d.get_io$$owner$$accepted$$bits$$newLine()) {
                for (const auto &[unused, prior] : retainedOwners) require(prior.released || (prior.event.context.owner.first != context.owner.first && prior.event.reservation.mshr != event.reservation.mshr), "new posted owner reused live slot/MSHR");
                RetainedOwner fresh; fresh.event = event; fresh.initial = backing; fresh.merged = backing;
                require(retainedOwners.emplace(context.owner, fresh).second, "posted cache full generation reused");
            } else {
                auto &prior = checkedOwner(event);
                require(outstandingMisses.count(context.line) && !outstandingPrefetches.count(context.line) &&
                    prior.members.count(key(outstandingMisses.at(context.line))),
                    "posted join lost its original independently accepted line/full-token owner");
            }
            auto &o = checkedOwner(event); require(!o.refilled && !o.installed, "store merged after actual refill/install");
            const unsigned ticket = d.get_io$$owner$$accepted$$bits$$member$$responseTicket();
            require(ticket < 2 && retainedMembers.emplace(tk, RetainedMember{context, ticket}).second, "member response ticket/full-token reused");
            for (const auto &[old, member] : retainedMembers) if (old != tk && member.ticket == ticket) require(member.acknowledged || cacheReturned.count(old), "response ticket reused before old member return");
            o.members.insert(tk); o.merged.write(r.address, r.expectedStore, r.size);
            require(postedMembers.insert(tk).second, "duplicate full-token posted acceptance"); ++postedAccepted;
        }
        auto memberEvent = [&](Token t, const OwnerContext &context, unsigned ticket, bool drain) {
            const Key tk = key(t); require(retainedMembers.count(tk), "member event lost original full token");
            auto &m = retainedMembers.at(tk); require(m.context == context && m.ticket == ticket && cacheReturned.count(tk), "member event changed owner/ticket or preceded real response");
            const auto &o = retainedOwners.at(context.owner); require(!o.released, "member event after owner released");
            if (drain) { require(m.acknowledged && !m.drained && o.installed, "member drain preceded acknowledgement/install or repeated"); m.drained = true; require(drainedMembers.insert(tk).second, "duplicate posted member drain"); ++postedDrained; }
            else { require(!m.acknowledged, "duplicate posted member acknowledgement"); m.acknowledged = true; }
        };
#define MEMBER(F, DRAIN) if (d.get_io$$owner$$##F##$$valid()) memberEvent(Token{unsigned(d.get_io$$owner$$##F##$$bits$$token$$index()), uint64_t(d.get_io$$owner$$##F##$$bits$$token$$tag())}, CONTEXT(owner$$##F##$$bits$$context), unsigned(d.get_io$$owner$$##F##$$bits$$responseTicket()), DRAIN)
        MEMBER(acknowledged, false);
        if (d.get_io$$owner$$acquired$$valid()) {
            const auto event = EVENT(owner$$acquired$$bits); auto &o = checkedOwner(event);
            require(!o.acquired && d.get_io$$tl$$a$$valid() && cycle % 7 != 2 && d.get_io$$tl$$a$$bits$$address() == event.context.line, "posted acquire lacks actual original A handshake");
            o.acquired = true; o.source = d.get_io$$tl$$a$$bits$$source(); require(postedGrantSources.emplace(o.source, event.context.owner).second, "posted acquire reused live TL source");
        }
#define WORDS(F) std::array<uint64_t, 8>{d.get_io$$##F##$$word0(),d.get_io$$##F##$$word1(),d.get_io$$##F##$$word2(),d.get_io$$##F##$$word3(),d.get_io$$##F##$$word4(),d.get_io$$##F##$$word5(),d.get_io$$##F##$$word6(),d.get_io$$##F##$$word7()}
        if (d.get_io$$owner$$refillValid()) {
            const auto event = EVENT(owner$$refillEvent); auto &o = checkedOwner(event);
            require(o.acquired && o.grantAcked && !o.refilled && !d.get_io$$owner$$refillError(), "posted refill lost original A/Grant/E responsibility");
            const auto words = WORDS(owner$$refill);
            for (unsigned i = 0; i < 8; ++i) require(words[i] == o.initial.read(event.context.line + 8 * i, 3), "posted refill differs from independent original backing bytes"); o.refilled = true;
        }
        if (d.get_io$$owner$$installedValid()) {
            const auto event = EVENT(owner$$installedEvent); auto &o = checkedOwner(event);
            require(o.refilled && !o.installed, "posted install preceded refill or repeated"); const auto words = WORDS(owner$$installed);
            for (unsigned i = 0; i < 8; ++i) require(words[i] == o.merged.read(event.context.line + 8 * i, 3), "posted actual install differs from independently ordered raw store bytes"); o.installed = true;
        }
        MEMBER(drained, true);
        auto writeback = [&](const OwnerEvent &event, unsigned slot, Key ticketOwner, unsigned phase) {
            auto &o = checkedOwner(event);
            require(event.reservation.victimValid && event.reservation.victimDirty && ticketOwner == event.context.owner && slot < 2, "writeback lost original dirty victim/full generation ticket");
            if (phase == 0) { require(!o.attached && postedWbSlots.emplace(slot, ticketOwner).second, "writeback reused live slot"); o.attached = true; o.wbSlot = slot; ++ownerWritebacks; }
            else {
                require(o.attached && o.wbSlot == slot && postedWbSlots.at(slot) == ticketOwner, "held writeback changed original slot/address/generation");
                if (phase == 1) { require(!o.sent && lastReleaseCycle == cycle && lastReleaseSource == slot + 2 && lastReleaseAddress == event.reservation.victim, "writeback sent lacks matching actual C-last"); o.sent = true; }
                else { require(o.sent && !o.completed && lastAckCycle == cycle && lastAckSource == slot + 2, "writeback completed before its exact real ReleaseAck"); o.completed = true; postedWbSlots.erase(slot); ++ownerWritebackCompletions; }
            }
        };
#define WB(F, PHASE) if (d.get_io$$owner$$##F##$$valid()) writeback(EVENT(owner$$##F##$$bits), unsigned(d.get_io$$owner$$##F##$$bits$$ticket$$slot()), OWNER_KEY(owner$$##F##$$bits$$ticket$$owner), PHASE)
        WB(attached, 0); WB(sent, 1); WB(completed, 2);
        if (d.get_io$$owner$$released$$valid()) {
            const auto event = EVENT(owner$$released$$bits); auto &o = checkedOwner(event);
            require(o.installed && (!event.reservation.victimDirty || o.completed), "posted owner released before install/final dirty ReleaseAck");
            for (const auto &tk : o.members) require(retainedMembers.at(tk).acknowledged && retainedMembers.at(tk).drained, "posted owner released undrained original member"); o.released = true; ++postedReleased;
        }
        for (const auto &[unused, o] : retainedOwners) if (o.attached && !o.completed) require(!o.released && d.get_io$$cachePostedBusy(), "held dirty tail lost cache busy/full owner responsibility");
        require(!d.get_io$$owner$$failed(), "real posted consumer entered failure state");
#undef WB
#undef WORDS
#undef MEMBER
#undef EVENT
#undef RESERVATION
#undef CONTEXT
#undef OWNER_KEY
    }
    void observe() {
        observeOwners();
        if (!witnessActive || !targetStore || !targetLoad) return;
        const bool headValid = d.get_io$$headValid(), stageValid = d.get_io$$stageValid();
        const bool start = d.get_io$$lsuStart(), choiceValid = d.get_io$$choiceValid();
        // Never inspect inactive full-token payloads. Only valid observations can become owners.
        const std::optional<Token> head = headValid ? std::optional<Token>{{unsigned(d.get_io$$headToken$$index()), uint64_t(d.get_io$$headToken$$tag())}} : std::nullopt;
        const std::optional<Token> stage = stageValid ? std::optional<Token>{{unsigned(d.get_io$$stageToken$$index()), uint64_t(d.get_io$$stageToken$$tag())}} : std::nullopt;
        const std::optional<Token> started = start ? std::optional<Token>{{unsigned(d.get_io$$lsuToken$$index()), uint64_t(d.get_io$$lsuToken$$tag())}} : std::nullopt;
        ++observedCycles; interruptDrainCycles += d.get_io$$interruptDrain(); contextEpochCycles += d.get_io$$contextMemoryEpoch();
        if (blockingAtomic && d.get_io$$stageValid() && stage == blockingAtomic) ++atomicBlockStages;
        const bool olderReady = olderLoad && (d.get_io$$originalMask() & (1ULL << olderLoad->index));
        if (olderLoad && stage == olderLoad && olderReady) { ++olderPreemptions; if (!firstOlderStage) firstOlderStage = cycle; }
        if (caseName == "newly_ready" && olderReady && !previousOlderReady && !firstOlderReady) {
            require(olderDependency && completionCycles.count(key(*olderDependency)) && completionCycles.at(key(*olderDependency)) <= cycle, "older load became ready before its independently owned producer completion");
            firstOlderReady = cycle; storeBeforeOlderReady = previousStageS;
        }
        previousOlderReady = olderReady;
        const bool atHead = d.get_io$$headValid() && head == targetStore;
        const bool stagedS = d.get_io$$stageValid() && stage == targetStore;
        const bool stagedA = d.get_io$$stageValid() && stage == targetLoad;
        aliasStalls += d.get_io$$memoryStall() == 5;
        const bool busy = d.get_io$$cpuPostedBusy() || d.get_io$$cachePostedBusy();
        const bool prepared = d.get_io$$probePending() && d.get_io$$probePrepared() && d.get_io$$probeKnown() && d.get_io$$probeSafe();
        if (stagedS && choiceValid && d.get_io$$pmpDenied()) ++deniedStoreCycles;
        const bool busyFell = previousBusy && !busy;
        if (busyFell) { ++finalDrainEdges; if (stagedS) ++residualStoreStages; }
        if (busy && stagedS) ++preparedBeforeDrain;
        previousBusy = busy; previousStageS = stagedS;
        const bool originalA = (d.get_io$$originalMask() & (1ULL << targetLoad->index)) != 0;
        originalReadyCycles += originalA;
        const bool unstartedTarget = !startCycles.count(key(*targetStore));
        if (!atHead && unstartedTarget && originalA) {
            if (!firstRawCompetition) firstRawCompetition = cycle;
            ++rawCompetition; rawStageS += stagedS; rawStageA += stagedA; busyBeforeStore += busy;
            if (caseName == "busy_false" && cycle > firstRawCompetition) require(stagedA && !stagedS, "busy-false interval did not restore original ready load selection");
            if (caseName == "unaligned_store" || caseName == "outside_store") require(!stagedS, "independently unsafe nonhead store entered preparation stage");
            if (caseName == "final_drain" && busyFell && !targetDrainEdge) targetDrainEdge = cycle;
        }
        if (caseName == "final_drain" && targetDrainEdge && cycle == targetDrainEdge + 1) {
            require(stagedA || (startCycles.count(key(*targetLoad)) && startCycles.at(key(*targetLoad)) >= targetDrainEdge), "original load did not regain the next legal stage after final posted drain"); ++finalDrainSelectionWitness;
        }
        if (systemBoundary && head == systemBoundary && busy) {
            ++systemBoundaryWaits;
            require(d.get_io$$seal() && (!start || (started != targetStore && started != targetLoad)), "head system boundary failed to force seal and block younger memory before drain");
        }
        if (!atHead && busy && prepared && originalA) {
            ++contested; stageStore += stagedS; stageLoad += stagedA; selectedSeals += d.get_io$$seal();
        }
        if (!atHead && stagedS) { ++nonheadPrepared; require(!start || !(started == targetStore), "nonhead prepared store started"); }
        if (busy) {
            require(!start || !(started == targetLoad), "ordinary load started across posted ownership");
            if (originalA) ++busyLoadBlocks;
        }
        if (atHead && !commitEnable && d.get_io$$headDone() && localStoreAcks.count(key(*targetStore))) { require(!retiredTokens.count(key(*targetStore)), "completed store retired through commit backpressure"); ++retirementHoldWitness; }
        if (atHead && !firstHead) firstHead = cycle;
        // This edge is defined only for the independently decoded, aligned physical
        // normal-RAM store whose actual selected PMP check was already observed.
        // It is deliberately undefined for faulting, virtual, atomic and IO targets.
        if (atHead && targetPhysicalStoreContract && verifiedTargetPmp && d.get_io$$probePending() &&
            d.get_io$$serialAvailable() && !d.get_io$$serialStoreOwner$$valid() && !d.get_io$$blockPostedStart() &&
            !d.get_io$$interruptDrain() && !d.get_io$$contextMemoryEpoch() && !d.get_io$$fpMemoryEpoch() &&
            commitEnable && !d.get_io$$recovering() && !d.get_io$$recoveryAccepted() &&
            !d.get_io$$headException$$valid() && !firstLegalHead) firstLegalHead = cycle;
        if (start && started == targetStore && !firstStart) firstStart = cycle;
        if (start && started == targetLoad && !firstLoadStart) firstLoadStart = cycle;
        if (trace.is_open()) trace << "{\"case\":\"" << caseName << "\",\"cycle\":" << cycle
            << ",\"busy\":" << busy << ",\"cpu_posted_count_busy\":" << unsigned(d.get_io$$cpuPostedBusy()) << ",\"cache_posted_busy\":" << unsigned(d.get_io$$cachePostedBusy()) << ",\"head_s\":" << atHead << ",\"stage_s\":" << stagedS
            << ",\"stage_a\":" << stagedA << ",\"prepared_s\":" << prepared << ",\"original_a\":" << originalA
            << ",\"start_s\":" << (start && started == targetStore) << ",\"start_a\":" << (start && started == targetLoad)
            << ",\"pmp_denied\":" << (choiceValid ? int(d.get_io$$pmpDenied()) : -1) << ",\"serial_available\":" << unsigned(d.get_io$$serialAvailable())
            << ",\"seal\":" << unsigned(d.get_io$$seal()) << "}\n";
    }
    void closeMemoryStateCase() {
        drain(); delay=16; flushCache();
        for(unsigned i=0;i<touchedBytes;++i) require(backing.read(ram+i,0)==expectedBytes.read(ram+i,0),"memory-reuse final independent byte mismatch");
        require(allocated==retired+cancelled.size()&&requests==responses,"memory-reuse owner/commit/response drain mismatch");
        std::cout<<"MEMORY_REUSE_DIRECTED_PASS case="<<caseName<<" retired="<<retired<<" allocated="<<allocated<<"\n";
    }
    void runMemoryStateWidths() {
        setreg(25,123456789);setreg(26,7);setreg(27,ram);setreg(30,0x1133557799BBDDFFULL);
        for(unsigned round=0;round<8;++round) {
            std::cerr<<"WIDTH_ROUND "<<round<<" cycle="<<cycle<<"\n";
            std::vector<Request> program{divide(24)};
            for(unsigned n=0;n<round;++n)program.push_back(addi(0,0,0));
            for(unsigned size=0;size<4;++size) {
                program.push_back(store(27,256+64*size,30,size));
                program.push_back(store(27,264+64*size,30,size));
                program.push_back(load(17+size,27,1024+64*size,size));
            }
            submit(program);drain();
        }
        // Exactly 64 owners per phase returns each allocation row to its prior
        // class position: STORE -> LOAD -> STORE, with fresh independent tags.
        for(unsigned phase=0;phase<3;++phase) {
            std::cerr<<"REUSE_PHASE "<<phase<<" cycle="<<cycle<<"\n";
            std::vector<Request> program;
            for(unsigned i=0;i<64;++i) program.push_back(phase==1?load(17,27,1536+8*(i%16)):store(27,1536+8*(i%16),30));
            submit(program);drain();
        }
        closeMemoryStateCase();
    }
    void runMemoryStateFrontier() {
        csr(0x3b0,allPmp);csr(0x3a0,0x1f);csr(0x180,satp);csr(0x300,(1ULL<<17)|(1ULL<<11));
        setreg(25,123456789);setreg(26,7);setreg(27,va);setreg(28,va+4096);setreg(30,0x1133557799BBDDFFULL);
        one(load(1,27,512));one(store(28,512,30));flushCache();delay=300;
        beforeClosure=expectedBytes;
        std::vector<Request> program{divide(),load(10,27)};
        for(unsigned i=0;i<8;++i)program.push_back(store(28,8*i,10));
        for(unsigned i=0;i<7;++i)program.push_back(load(11+i,27,8+8*i));
        program.push_back(load(18,27,128));
        const auto tokens=submit(program);old=tokens[1];far=tokens.back();
        closureStores.assign(tokens.begin()+2,tokens.begin()+10);closureLoads.assign(tokens.begin()+10,tokens.begin()+17);
        drain();
        require(cacheCycles.at(key(*far))<responseCycles.at(key(*old)),"far frontier owner did not start before old response");
        require(proofs.count(key(*far)),"far independent proof witness absent");
        closeMemoryStateCase();
    }
    void run() {
        const std::set<std::string> cases{"main","older_ready","newly_ready","busy_false","final_drain","long_nonhead","alias_full","alias_partial","pmp_store","unaligned_store","outside_store","atomic_store","virtual_store","strong_mmio","strong_misaligned","strong_pmp_load","irq","fence","context","recovery","token_reuse","backpressure","late_ack","dirty_release","full_owner","wrap"};
        require(cases.count(caseName), "unknown directed case");
        const bool noPosted = caseName == "busy_false" || caseName == "virtual_store";
        const bool badStore = caseName == "pmp_store" || caseName == "unaligned_store";
        const bool badLoad = caseName == "strong_misaligned" || caseName == "strong_pmp_load";
        const bool recoveryCase = caseName == "recovery", irqCase = caseName == "irq";
        const bool boundary = caseName == "fence" || caseName == "context";
        const bool priorityCase = std::set<std::string>{"main","long_nonhead","token_reuse","backpressure","late_ack","dirty_release","full_owner","wrap","strong_mmio","strong_misaligned","strong_pmp_load"}.count(caseName);
        setreg(25, caseName == "newly_ready" ? ram * 7 : 123456789); setreg(26, 7);
        setreg(27, ram); setreg(30, 0x1133557799BBDDFFULL);
        if (caseName == "token_reuse") setreg(29, 0x8877665544332211ULL);
        if (caseName == "strong_mmio" || caseName == "outside_store") setreg(28, 0x10000000);
        if (caseName == "pmp_store") { csr(0x3b0, (ram + 8) >> 2); csr(0x3a0, 0x90); }
        if (caseName == "strong_pmp_load") { csr(0x3b0, (ram + 128) >> 2); csr(0x3a0, 0x92); }
        if (irqCase) { csr(0x305, 0x1000); csr(0x304, 128); csr(0x300, 8); allowIrq = true; }
        if (caseName == "context") { setreg(31, satp); beforeContextEpoch = d.adapter$postedEpoch; }
        if (caseName == "virtual_store") {
            csr(0x3b0, allPmp); csr(0x3a0, 0x1f); csr(0x180, satp); csr(0x300, (1ULL << 17) | (1ULL << 11));
            setreg(27, va); require(d.get_io$$virtualized(), "virtual exclusion never entered actual translated context");
        }
        if (caseName == "dirty_release" || caseName == "late_ack") {
            releaseDelay = 200;
            setreg(28, ram + 16384); one(store(28, 0, 30));
            setreg(28, ram + 32768); one(store(28, 0, 30));
        }
        if (caseName == "wrap") { while (allocated % 64 != 61) one(addi(29, 0, 1)); }
        delay = (caseName == "final_drain" || caseName == "alias_full" || caseName == "alias_partial") ? 32 : 600;
        const unsigned beforePosted = postedAccepted;
        if (!noPosted) {
            const Token first = submit({store(27, 0, 30)}).at(0);
            for (unsigned i = 0; i < 100 && (!retiredTokens.count(key(first)) || postedAccepted == beforePosted); ++i) tick();
            require(retiredTokens.count(key(first)) && postedAccepted == beforePosted + 1 && (d.get_io$$cpuPostedBusy() || d.get_io$$cachePostedBusy()), "primary witness lacks real live posted owner after head store retirement");
        }
        unsigned storeOffset = caseName == "unaligned_store" ? 9 : 8;
        if (caseName == "full_owner") {
            const Token second = submit({store(27, 128, 30)}).at(0);
            for (unsigned i = 0; i < 100 && (!retiredTokens.count(key(second)) || !retainedMembers.count(key(second)) || d.get_io$$owner$$postedMask() != 3); ++i) tick();
            require(retiredTokens.count(key(second)) && retainedMembers.count(key(second)) && !retainedOwners.at(retainedMembers.at(key(second)).context.owner).released && d.get_io$$owner$$postedMask() == 3, "two real posted line owners never simultaneously live");
            storeOffset = 264;
        }
        Request target = store(caseName == "outside_store" ? 28 : 27, storeOffset, 30);
        std::vector<Request> initial{divide(caseName == "newly_ready" ? 28 : 24)};
        if (caseName == "long_nonhead") { initial.push_back(divide(23, 24)); initial.push_back(divide(22, 23)); initial.push_back(divide(21, 22)); }
        if (caseName == "token_reuse") initial.push_back(divide(23, 24));
        if (recoveryCase || caseName == "token_reuse") initial.push_back(takenBranch(24));
        if (caseName == "older_ready") initial.push_back(load(17, 27, 128));
        if (caseName == "newly_ready") initial.push_back(load(17, 28, 192));
        if (caseName == "fence") initial.push_back(raw(0x0ff0000f));
        if (caseName == "context") initial.push_back(csrw(0x180));
        initial.push_back(target);
        auto tokens = submit(initial); targetStore = tokens.back(); probe = targetStore;
        if (caseName == "newly_ready" || caseName == "older_ready") olderLoad = tokens.at(1);
        if (caseName == "newly_ready") olderDependency = tokens.at(0);
        if (boundary) systemBoundary = tokens.at(1);
        {
            for (unsigned i = 0; i < 10 && !d.get_io$$probePrepared(); ++i) tick();
            require(d.get_io$$probePrepared() && d.get_io$$probeKnown(), "original nonhead store never prepared");
            if (caseName != "unaligned_store" && caseName != "outside_store" && caseName != "virtual_store") require(d.get_io$$probeSafe(), "ordinary physical store lacks actual safe range");
        }
        const Request immutableTarget = owner(*targetStore).request;
        targetPhysicalStoreContract = immutableTarget.store && !immutableTarget.atomic && !immutableTarget.fault && bareMode &&
            immutableTarget.address >= ram && __uint128_t(immutableTarget.address) + (1ULL << immutableTarget.size) <= __uint128_t(ram) + ramBytes &&
            !(immutableTarget.address & ((1ULL << immutableTarget.size) - 1));
        if (priorityCase) {
            for (unsigned i = 0; i < 8; ++i) {
                if (d.get_io$$choiceValid()) {
                    const Token choice{unsigned(d.get_io$$choiceToken$$index()), uint64_t(d.get_io$$choiceToken$$tag())};
                    if (choice == *targetStore) { require(!d.get_io$$pmpDenied(), "ordinary target failed actual physical PMP check"); verifiedTargetPmp = true; break; }
                }
                tick();
            }
            require(targetPhysicalStoreContract && verifiedTargetPmp, "first legal edge lacks independent physical shape and actual PMP witness");
        }
        if (caseName == "token_reuse") {
            require(d.get_io$$stageValid(), "ABA old store did not enter actual payload stage");
            const Token staged{unsigned(d.get_io$$stageToken$$index()), uint64_t(d.get_io$$stageToken$$tag())};
            require(staged == *targetStore && d.get_io$$stageAddress() == ram + 8 && d.get_io$$stageData() == predicted[30], "ABA old staged full-token/address/data mismatch");
            staleStageToken = targetStore;
            for (unsigned i = 0; i < 80 && (!recoveryEvents || d.get_io$$recovering()); ++i) tick();
            require(recoveryEvents == 1 && !d.get_io$$recovering() && !startCycles.count(key(*staleStageToken)), "ABA cancellation did not remove unstarted old stage owner");
            targetStore = submit({store(27, 8, 29)}).at(0); probe = targetStore;
            require(targetStore->index == staleStageToken->index && targetStore->tag != staleStageToken->tag, "ABA replacement did not reuse exact ROB index with fresh full tag");
            verifiedTargetPmp = false;
            for (unsigned i = 0; i < 12; ++i) {
                if (d.get_io$$choiceValid() && d.get_io$$stageValid()) {
                    const Token choice{unsigned(d.get_io$$choiceToken$$index()), uint64_t(d.get_io$$choiceToken$$tag())};
                    if (choice == *targetStore) {
                        require(!d.get_io$$pmpDenied() && d.get_io$$stageAddress() == ram + 8 && d.get_io$$stageData() == architectural[29] && architectural[29] != architectural[30], "ABA replacement inherited stale address/data/permission");
                        verifiedTargetPmp = true; ++stagedAbaWitness; break;
                    }
                }
                tick();
            }
            require(verifiedTargetPmp && stagedAbaWitness == 1, "ABA replacement never formed its own verified physical stage");
        }
        unsigned loadOffset = caseName == "alias_full" ? 8 : caseName == "alias_partial" ? 12 : caseName == "strong_misaligned" ? 129 : caseName == "full_owner" ? 384 : 128;
        std::vector<Request> finalInput;
        if (caseName == "atomic_store") finalInput.push_back(raw((30U << 20) | (27U << 15) | (3U << 12) | (19U << 7) | 0x2f));
        finalInput.push_back(load(18, caseName == "strong_mmio" ? 28 : 27, loadOffset, caseName == "alias_partial" ? 2 : 3));
        const auto finalTokens = submit(finalInput); targetLoad = finalTokens.back();
        if (caseName == "atomic_store") blockingAtomic = finalTokens.front();
        witnessActive = true;
        if (irqCase) timerInterrupt = true;

        if (caseName == "backpressure") {
            for (unsigned i = 0; i < 160 && !startCycles.count(key(*targetStore)); ++i) tick();
            require(startCycles.count(key(*targetStore)) && !retiredTokens.count(key(*targetStore)), "retirement backpressure missed live started store owner");
            commitEnable = false;
            for (unsigned i = 0; i < 80 && !retirementHoldWitness; ++i) tick();
            require(retirementHoldWitness > 0, "commit backpressure never held completed actual head store");
            for (unsigned i = 0; i < 12; ++i) tick(); commitEnable = true;
        }
        if (caseName == "busy_false") { commitEnable = false; for (unsigned i = 0; i < 12; ++i) tick(); commitEnable = true; }
        if (caseName == "context") {
            for(unsigned i=0;i<2000 && (!contextRedirects || d.get_io$$recovering());++i) tick();
            require(contextRedirects == 1 && !d.get_io$$recovering() && cancelled.size() == 2 && !startCycles.count(key(*targetStore)) && !startCycles.count(key(*targetLoad)), "SATP redirect did not cancel original unstarted younger memory");
            const auto replay = submit({target, finalInput.back()}); targetStore=replay.at(0);targetLoad=replay.at(1);probe=targetStore;
        }
        drain(); witnessActive = false;
        require(observedCycles > 0 && originalReadyCycles > 0, "directed case has no actual ready-load observation");
        if (priorityCase) {
            require(contested >= 2 && busyLoadBlocks >= 2, "no nonzero posted store/load competition witness");
            require(firstLegalHead && firstStart && firstStart >= firstLegalHead, "primary legal-head/start timeline missing");
            if (PREPARATION_PRIORITY_ON) {
                require(nonheadPrepared >= 2 && stageStore >= 2, "ON never retained safe prepared nonhead store against ready load");
                require((firstStart == firstLegalHead) != injectTiming, "ON missed first legal head start edge");
            } else {
                require(stageLoad >= 2, "OFF did not keep ready original load");
                require((firstStart > firstLegalHead) != injectTiming, "OFF did not miss first legal head stage");
            }
        }
        if (caseName == "older_ready") require(olderPreemptions > 0 && stageStore == 0, "older ready original load did not retain age priority");
        if (caseName == "newly_ready") require(firstOlderReady > 0 && firstOlderStage >= firstOlderReady && firstOlderStage <= firstOlderReady + 1 && (!PREPARATION_PRIORITY_ON || (stageStore > 0 && storeBeforeOlderReady)), "newly ready older load missed its first legal preparation selection");
        if (caseName == "busy_false") require(rawCompetition >= 3 && rawStageA >= 2 && rawStageS <= 1 && busyBeforeStore == 0, "busy-false pre-head interval changed original selection");
        if (caseName == "final_drain") require(targetDrainEdge > 0 && finalDrainSelectionWitness == 1 && (!PREPARATION_PRIORITY_ON || preparedBeforeDrain > 0), "final drain lacked actual next-stage restoration witness");
        if (caseName == "long_nonhead" && PREPARATION_PRIORITY_ON) require(nonheadPrepared > 40, "long nonhead stage lifetime not exercised");
        if (caseName == "alias_full" || caseName == "alias_partial") require(aliasStalls > 0 && firstLoadStart > firstStart && firstStart > 0, "full/partial physical alias bypassed the older store or lacked actual conflict witness");
        if (badStore) require(traps == 1 && !cacheCycles.count(key(*targetStore)), "faulting store gained a cache side effect or lost precise fault");
        if (caseName == "pmp_store") require(deniedStoreCycles > 0, "PMP denial was never actually observed on selected store");
        if (caseName == "unaligned_store" || caseName == "outside_store") require(stageStore == 0, "excluded store joined posted preparation competition");
        if (caseName == "outside_store" || caseName == "strong_mmio") require(physicalTransactions > 0, "actual uncached strong-boundary path not exercised");
        if (caseName == "atomic_store") require(stageStore <= 1 && atomicBlockStages > 0 && firstStart > 0 && actualAtomicBypasses == 1, "original atomic candidate did not suppress posted preparation union");
        if (caseName == "virtual_store") require(postedAccepted == 0 && virtualIngress.count(key(*targetStore)) && virtualTranslatedReplies.count(key(*targetStore)) && checkedTokens.count(key(*targetStore)) && cacheCycles.count(key(*targetStore)) && cacheReturned.count(key(*targetStore)) && retiredTokens.count(key(*targetStore)), "virtual store lost actual ingress/translation/final-PA/cache-response/full-token chain or acquired posted authority");
        if (badLoad) require(traps == 1 && !cacheCycles.count(key(*targetLoad)), "strong faulting load reached cache or lost precise fault");
        if (irqCase) require(traps == 1 && interruptDrainCycles > 0, "real interrupt failed to force posted drain and precise trap");
        if (boundary) require(systemBoundaryWaits > 0 && systemBoundaryRetired == 1, "raw system boundary lacked actual busy-head seal and drain-before-retirement witness");
        if (caseName == "context") require(contextEpochCycles > 0 && d.get_io$$vm$$satp() == satp && d.get_io$$vm$$dataPrivilege() == 3 && !d.get_io$$virtualized() && d.adapter$postedEpoch == beforeContextEpoch + 1, "actual SATP snapshot/posted epoch transition did not drain and preserve physical M-mode access");
        if (recoveryCase) require(recoveryEvents == 1 && cancelled.size() >= 2 && !startCycles.count(key(*targetStore)), "recovery failed to cancel staged full-token owners");
        if (caseName == "token_reuse") require(stagedAbaWitness == 1 && staleStageToken && !startCycles.count(key(*staleStageToken)) && startCycles.count(key(*targetStore)) && cacheCycles.count(key(*targetStore)) && retiredTokens.count(key(*targetStore)), "staged ABA cancellation/reallocation did not preserve full-token start/response/retirement");
        if (caseName == "full_owner") require(heldCacheCycles > 0, "full real owner bank never backpressured a held cache payload");
        if (caseName == "dirty_release" || caseName == "late_ack") require(ownerWritebacks > 0 && ownerWritebackCompletions == ownerWritebacks, "posted dirty victim did not complete real Release/ReleaseAck responsibility");
        if (caseName == "wrap") require(targetStore->index == 63 && targetLoad->index == 0, "circular oldest witness did not cross ROB wrap");
        delay = 16; flushCache();
        if (caseName == "late_ack") require(releaseAckCount > 0 && maxReleaseDelay >= 200, "late real ReleaseAck retention was not exercised");
        for (unsigned i = 0; i < touchedBytes; ++i) require(backing.read(ram + i, 0) == expectedBytes.read(ram + i, 0), "final independently expected RAM byte mismatch");
        for (const auto &[address, unused] : expectedBytes.changed) require(backing.read(address, 0) == expectedBytes.read(address, 0), "final independently expected external byte mismatch");
        for (const auto &[address, unused] : backing.changed) require(backing.read(address, 0) == expectedBytes.read(address, 0), "actual write escaped independently authored byte set");
        std::set<Key> retiredStoreDrainKeys;
        for (const auto &e : retainedRetiredStores) {
            const Key tk = key(e.token);
            require(retiredStoreDrainKeys.insert(tk).second && e.requested && cacheCycles.count(tk) && cacheReturned.count(tk) &&
                localStoreAcks.count(tk) && retiredTokens.count(tk), "locally acknowledged retired store lost its exact late cache request/response responsibility");
        }
        for (const auto &[unused, o] : retainedOwners) require(o.released, "terminal drain retained full owner generation");
        require(postedWbSlots.empty() && postedGrantSources.empty(), "terminal drain retained real cache transport resources");
        require(postedAccepted == postedDrained && requests == responses && allocated == retired + cancelled.size(), "terminal actual owner/commit/response drain mismatch");
        uint64_t byteDigest = 1469598103934665603ULL;
        for (unsigned i = 0; i < touchedBytes; ++i) { byteDigest ^= backing.read(ram + i, 0); byteDigest *= 1099511628211ULL; }
        for (const auto &[address, unused] : expectedBytes.changed) if (address < ram || address >= ram + touchedBytes) { byteDigest ^= address; byteDigest *= 1099511628211ULL; byteDigest ^= backing.read(address, 0); byteDigest *= 1099511628211ULL; }
        std::cout << "POSTED_PREPARATION_CASE name=" << caseName << " enabled=" << PREPARATION_PRIORITY_ON
            << " first_head=" << firstHead << " first_legal=" << firstLegalHead << " first_start=" << firstStart
            << " first_load=" << firstLoadStart << " contested=" << contested << " stage_s=" << stageStore
            << " stage_a=" << stageLoad << " seals=" << selectedSeals << " posted_members=" << postedAccepted
            << " posted_drained=" << postedDrained << " posted_released=" << postedReleased << " retired=" << retired
            << " witness=" << observedCycles << " decoder_checks=" << decoderChecks << " busy_load_blocks=" << busyLoadBlocks
            << " traps=" << traps << " cancelled=" << cancelled.size() << " retire_digest=" << retireDigest << " byte_digest=" << byteDigest
            << " verified_target_pmp=" << verifiedTargetPmp << " physical_store_contract=" << targetPhysicalStoreContract
            << " virtual_translation_witness=" << virtualTranslatedReplies.size() << " local_redirects=" << recoveryEvents << " context_redirects=" << contextRedirects
            << " staged_aba_witness=" << stagedAbaWitness
            << " first_older_ready=" << firstOlderReady << " first_older_stage=" << firstOlderStage << " atomic_bypasses=" << actualAtomicBypasses
            << " raw_competition=" << rawCompetition << " raw_stage_s=" << rawStageS << " raw_stage_a=" << rawStageA
            << " boundary_waits=" << systemBoundaryWaits << " boundary_retired=" << systemBoundaryRetired << " drain_selection_witness=" << finalDrainSelectionWitness
            << " retirement_hold_witness=" << retirementHoldWitness
            << " owner_writebacks=" << ownerWritebacks << " owner_writeback_completions=" << ownerWritebackCompletions << " max_release_delay=" << maxReleaseDelay
            << " busy_before_store=" << busyBeforeStore
            << " residual_store_stages=" << residualStoreStages << " final_drain_edges=" << finalDrainEdges
            << " requests=" << requests << " responses=" << responses << " bytes=" << touchedBytes << "\n";
        std::cout << "POSTED_PREPARATION_FOCUSED_PASS\n";
    }
};
int main(int argc, char **argv) {
    try {
        Bench b;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--inject-data") b.injectData = true;
            else if(arg=="--inject-state")b.injectState=true;
            else if(arg=="--inject-state-owner")b.injectStateOwner=true;
            else if(arg=="--inject-line-owner")b.injectLineOwner=true;
            else if (arg == "--case" && i + 1 < argc) b.caseName = argv[++i];
            else if (arg == "--inject-token") b.injectToken = true;
            else if (arg == "--inject-timing") b.injectTiming = true;
            else if (arg == "--trace" && i + 1 < argc) { b.trace.open(argv[++i]); require(b.trace.good(), "cannot open trace"); }
            else throw std::runtime_error("unknown argument " + arg);
        }
        if(b.caseName=="reuse_widths")b.runMemoryStateWidths();
        else if(b.caseName=="reuse_frontier")b.runMemoryStateFrontier();
        else b.run();
        b.memoryStateSummary(); return 0;
    } catch (const std::exception &e) { std::cerr << "POSTED_PREPARATION_FAIL " << e.what() << "\n"; return 1; }
}
