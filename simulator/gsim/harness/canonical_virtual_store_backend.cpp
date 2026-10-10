#include "CanonicalVirtualStoreBackendGsim.h"
#include "virtual_load_test_memory.h"
#include <algorithm>
#include <array>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <tuple>
#include <vector>
#ifndef PRECHECK_ENABLED
#define PRECHECK_ENABLED 1
#endif
#ifndef CANONICAL_STORE_OVERLAP
#define CANONICAL_STORE_OVERLAP 0
#endif
using namespace virtual_load_test;
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
struct Request {
    bool valid = false, memory = false, store = false, system = false, writes = true, branch = false, mulDiv = false;
    unsigned rd = 1, rs1 = 0, rs2 = 0;
    uint64_t immediate = 0, pc = 0, expected = 0, expectedCause = 0, virtualAddress = 0;
    uint32_t instruction = 0x13;
    bool fault = false, physicalError = false;
};
struct Entry { Token token; Request request; bool requested = false, started = false, canonical = false, upstreamSeen = false; };
struct Pending { uint64_t due = 0, data = 0; Token token{}; bool error = false; };
struct Input { std::array<Request, 2> requests{}; bool recover = false, inclusive = true; Token boundary{}; };
struct Result { std::array<bool, 2> accepted{}; std::array<Token, 2> tokens{}; bool recovered = false; };
static Request add(unsigned rd, uint64_t value) { Request r; r.valid = true; r.rd = rd; r.immediate = value; r.expected = value; return r; }
static Request load(unsigned rd, uint64_t address) { Request r = add(rd, address); r.memory = true; r.virtualAddress = address; return r; }
static Request store(uint64_t address, unsigned rs2 = 30) { Request r = load(0, address); r.store = true; r.rs2 = rs2; r.writes = false; r.instruction = 0x3023; return r; }
// A real 64-iteration DIV keeps the retirement head busy while independent
// younger virtual loads obtain their registered certificates.
static Request divide() {
    Request r = add(24, 0); r.mulDiv = true; r.rs1 = 25; r.rs2 = 26;
    r.expected = 123456789ULL / 7; r.instruction = (1U << 25) | (26U << 20) | (25U << 15) | (4U << 12) | (24U << 7) | 0x33;
    return r;
}
static Request system(uint32_t instruction, unsigned rs1 = 0) { Request r = add(0, 0); r.writes = false; r.system = true; r.rs1 = rs1; r.instruction = instruction; return r; }
class Bench {
    using Key = std::pair<unsigned, uint64_t>;
    SCanonicalVirtualStoreBackendGsim d;
    std::deque<Entry> live;
    std::deque<Pending> replies, ptes;
    std::array<uint64_t, 32> architectural{};
    std::map<uint64_t, uint64_t> expectedMemory, physicalMemory;
    std::optional<std::tuple<uint64_t, uint64_t, bool, unsigned, bool>> held;
    std::map<uint64_t, uint64_t> firstPeek;
    uint64_t nextPc = 0x1000;
public:
    PageTables tables;
    uint64_t cycle = 0, caseStart = 0, coldCycles = 0, trace = 1469598103934665603ULL;
    unsigned latency = 35, holdPhysicalUntil = 0, holdReplyUntil = 0, secondLatency = 0;
    unsigned allocated = 0, retired = 0, physicalRequests = 0, physicalResponses = 0, peak = 0;
    unsigned certifiedStores = 0, overlappingStoreLoads = 0, originHolds = 0, upstreamAccepted = 0,
        upstreamCompleted = 0, acceptedPeak = 0;
    std::array<uint64_t, 10> stalls{};
    std::array<uint64_t, 9> liveDistribution{};
    std::map<Key, uint64_t> storeResponseCycles;
    uint64_t certificateToResponseCycles = 0, firstLoadLeadCycles = 0;
    std::map<Key, uint64_t> firstYoungerStart;
    struct OverlapPair { Key store, load; uint64_t start = 0, request = 0, physical = 0; };
    std::vector<OverlapPair> overlapPairs;
    unsigned overlapRequests = 0, overlapPhysical = 0;
    unsigned precheckedStarts = 0, serialStarts = 0, serialBeforeProof = 0, pteReads = 0, walks = 0, hits = 0, queryHits = 0;
    unsigned trapCount = 0, physicalHolds = 0, cancellations = 0, reuse = 0, redirects = 0, cancelledSlotReuse = 0;
    bool commitEnable = true, inject = false;
    std::set<std::pair<unsigned, uint64_t>> killed;
    std::map<unsigned, uint64_t> generations;
    std::map<Key, uint64_t> storeOrigins, storeCertificates, certificateEpochs;
    std::set<Key> responded, committedTokens;
    std::optional<Token> lastTrapToken;
    uint64_t lastTrapCause = 0, lastTrapVa = 0;
    bool wasRetired(Token token) const { return committedTokens.count({token.index, token.tag}); }
    std::optional<std::tuple<unsigned, uint64_t, uint64_t, uint64_t>> heldOrigin;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); for (unsigned n = 0; n < 5; ++n) tick(); }
    void check(bool ok, const std::string &why) const { require(ok, "cycle " + std::to_string(cycle) + ": " + why); }
    uint64_t expectedAt(uint64_t address) { auto p = tables.physical(address); return expectedMemory.count(p) ? expectedMemory[p] : readValue(p); }
    void drive(const Input &in) {
#define DRIVE(N) \
        d.set_io$$allocate##N##$$valid(in.requests[N].valid); \
        d.set_io$$allocate##N##$$bits$$rename$$writesRd(in.requests[N].writes); \
        d.set_io$$allocate##N##$$bits$$rename$$rs1(in.requests[N].rs1); \
        d.set_io$$allocate##N##$$bits$$rename$$rs2(in.requests[N].rs2); \
        d.set_io$$allocate##N##$$bits$$rename$$rd(in.requests[N].rd); \
        d.set_io$$allocate##N##$$bits$$rename$$pc(in.requests[N].pc); \
        d.set_io$$allocate##N##$$bits$$rename$$instruction(in.requests[N].instruction); \
        d.set_io$$allocate##N##$$bits$$expandedInstruction(in.requests[N].instruction); \
        d.set_io$$allocate##N##$$bits$$system(in.requests[N].system); \
        d.set_io$$allocate##N##$$bits$$memory(in.requests[N].memory); \
        d.set_io$$allocate##N##$$bits$$store(in.requests[N].store); \
        d.set_io$$allocate##N##$$bits$$memorySize(3); \
        d.set_io$$allocate##N##$$bits$$memoryUnsigned(0); \
        d.set_io$$allocate##N##$$bits$$immediate(in.requests[N].immediate); \
        d.set_io$$allocate##N##$$bits$$operation(0); \
        d.set_io$$allocate##N##$$bits$$word(0); \
        d.set_io$$allocate##N##$$bits$$usePc(0); \
        d.set_io$$allocate##N##$$bits$$useImmediate(!in.requests[N].branch && !in.requests[N].mulDiv); \
        d.set_io$$allocate##N##$$bits$$controlFlow(in.requests[N].branch ? 1 : 0); \
        d.set_io$$allocate##N##$$bits$$mulDiv(in.requests[N].mulDiv); \
        d.set_io$$allocate##N##$$bits$$mulDivOp(in.requests[N].mulDiv ? 4 : 0); \
        d.set_io$$allocate##N##$$bits$$atomic(0); \
        d.set_io$$allocate##N##$$bits$$atomicOp(0); \
        d.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
        d.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
        d.set_io$$allocate##N##$$bits$$fetchFault(0); \
        d.set_io$$allocate##N##$$bits$$fetchPageFault(0); \
        d.set_io$$allocate##N##$$bits$$fetchTval(0);
        DRIVE(0) DRIVE(1)
#undef DRIVE
        d.set_io$$commitEnable(commitEnable); d.set_io$$inspectRegister(cycle % 32);
        d.set_io$$recover$$valid(in.recover); d.set_io$$recover$$bits$$inclusive(in.inclusive);
        d.set_io$$recover$$bits$$token$$index(in.boundary.index); d.set_io$$recover$$bits$$token$$tag(in.boundary.tag);
        d.set_io$$physical$$request$$ready(cycle >= holdPhysicalUntil && cycle % 9 != 5);
        const bool reply = !replies.empty() && replies.front().due <= cycle && cycle >= holdReplyUntil;
        d.set_io$$physical$$response$$valid(reply);
        d.set_io$$physical$$response$$bits$$data(reply ? replies.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(reply && replies.front().error);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(cycle % 5 != 3);
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$response$$valid(pte); d.set_io$$pte$$response$$bits$$data(pte ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
    }
    Result tick(Input in = {}) {
        const bool reply = !replies.empty() && replies.front().due <= cycle && cycle >= holdReplyUntil;
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        drive(in); d.step(); Result out;
        check(d.get_io$$committedValue() == architectural[cycle % 32], "committed register architectural oracle mismatch");
#define ACCEPT(N) \
        out.accepted[N] = d.get_io$$renamed##N##$$valid(); \
        if (out.accepted[N]) out.tokens[N] = {unsigned(d.get_io$$renamed##N##$$bits$$token$$index()), uint64_t(d.get_io$$renamed##N##$$bits$$token$$tag())};
        ACCEPT(0) ACCEPT(1)
#undef ACCEPT
        for (unsigned n = 0; n < 2; ++n) if (out.accepted[n]) {
            check(in.requests[n].valid, "allocation without offered instruction");
            auto r = in.requests[n];
            if (r.memory && !r.fault) {
                const uint64_t address = r.virtualAddress;
                if (r.store) expectedMemory[tables.physical(address)] = architectural[r.rs2];
                else r.expected = expectedAt(address);
            }
            auto old = generations.find(out.tokens[n].index);
            if (old != generations.end() && old->second != out.tokens[n].tag) ++reuse;
            generations[out.tokens[n].index] = out.tokens[n].tag;
            for (const auto &[index, tag] : killed)
                if (index == out.tokens[n].index && tag != out.tokens[n].tag) ++cancelledSlotReuse;
            live.push_back({out.tokens[n], r}); ++allocated;
        }
        out.recovered = d.get_io$$recoveryAccepted();
        if (out.recovered && in.recover) {
            auto at = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == in.boundary; });
            check(at != live.end(), "recovery boundary lost full-token owner");
            auto first = at + !in.inclusive;
            for (auto it = first; it != live.end(); ++it) { killed.insert({it->token.index, it->token.tag}); ++cancellations; }
            live.erase(first, live.end());
        }
        if (d.get_io$$redirect$$valid() && !d.get_io$$trap$$valid()) {
            const Token token{unsigned(d.get_io$$redirect$$bits$$token$$index()), uint64_t(d.get_io$$redirect$$bits$$token$$tag())};
            auto at = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == token; });
            check(at != live.end() && (at->request.branch || at->request.system), "redirect lost branch/system full-token owner");
            if (at->request.branch) {
                check(d.get_io$$redirect$$bits$$target() == at->request.pc + at->request.immediate,
                    "taken branch target/provenance mismatch");
                ++redirects;
            }
            for (auto it = at + 1; it != live.end(); ++it) { killed.insert({it->token.index, it->token.tag}); ++cancellations; }
            live.erase(at + 1, live.end());
        }
        if (reply && d.get_io$$physical$$response$$ready()) {
            const Key key{replies.front().token.index, replies.front().token.tag};
            responded.insert(key);
            if (storeCertificates.count(key)) {
                storeResponseCycles[key] = cycle;
                certificateToResponseCycles += cycle - storeCertificates[key];
                if (firstYoungerStart.count(key)) firstLoadLeadCycles += cycle - firstYoungerStart[key];
            }
            replies.pop_front(); ++physicalResponses;
        }
        if (pte && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && cycle % 5 != 3) {
            ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())}); ++pteReads;
        }
        if (d.get_io$$queryHit()) {
            ++queryHits; const uint64_t address = d.get_io$$queryAddress();
            check(d.get_io$$queryPhysical() == tables.physical(address), "peek differed from independent page tables");
            if (!firstPeek.count(address)) firstPeek[address] = cycle;
        }
        if (d.get_io$$canonicalChecked$$valid()) {
            const Token token{unsigned(d.get_io$$canonicalChecked$$bits$$origin$$token$$index()),
                uint64_t(d.get_io$$canonicalChecked$$bits$$origin$$token$$tag())};
            const Key key{token.index, token.tag};
            const auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == token; });
            check(CANONICAL_STORE_OVERLAP && owner != live.end() && owner == live.begin() &&
                owner->request.store && owner->started && owner->upstreamSeen && storeOrigins.count(key) &&
                storeOrigins[key] < cycle, "checked certificate lacks a previously accepted exact head store");
            const auto address = owner->request.virtualAddress;
            const auto &mapping = tables.pages.at(unsigned((address - va) / 4096));
            const auto physical = tables.physical(address);
            // Independent whole-transfer/PTE/PBMT oracle. Output fields never establish permission.
            check((mapping.flags & 0xc7) == 0xc7 && !(mapping.flags & 0x10) && mapping.pbmt == 0 &&
                !(address & 7) && physical >= ram && physical <= ram + ramBytes - 8,
                "certificate lacks independent ordinary RAM/write permission");
            check(d.get_io$$canonicalChecked$$bits$$virtualAddress() == address &&
                d.get_io$$canonicalChecked$$bits$$physicalAddress() == physical &&
                d.get_io$$canonicalChecked$$bits$$size() == 3 && d.get_io$$canonicalChecked$$bits$$mask() == 255 &&
                d.get_io$$canonicalChecked$$bits$$origin$$epoch() == d.get_io$$epoch(),
                "checked certificate differs from independent exact owner/VA/PA/shape/epoch");
            check(!storeCertificates.count(key), "duplicate checked certificate for one accepted store");
            storeCertificates[key] = cycle;
            certificateEpochs[key] = d.get_io$$epoch(); ++certifiedStores;
        }
        if (d.get_io$$lsuStart()) {
            const Token token{unsigned(d.get_io$$lsuToken$$index()), uint64_t(d.get_io$$lsuToken$$tag())};
            auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == token; });
            check(owner != live.end(), "LSU start used cancelled/stale full ROB token"); owner->started = true;
            check(d.get_io$$lsuVa() == owner->request.virtualAddress, "LSU lost original virtual address");
            if (d.get_io$$lsuPrechecked()) {
                ++precheckedStarts; owner->canonical = true; const auto address = d.get_io$$lsuVa();
                check(PRECHECK_ENABLED && !owner->request.store && (!owner->request.fault || owner->request.physicalError) && d.get_io$$lsuParallel(), "invalid speculative certificate use");
                check(d.get_io$$lsuPa() == tables.physical(address), "canonical physical alias mismatch");
                check(firstPeek.count(address) && cycle >= firstPeek[address] + 2, "lookup/PMP/issue register cut collapsed");
                for (auto older = live.begin(); older != owner; ++older) {
                    if (!older->request.memory) continue;
                    if (!older->request.store) {
                        check(older->canonical, "younger certified load crossed uncanonical older read");
                        continue;
                    }
                    const Key key{older->token.index, older->token.tag};
                    const uint64_t storePa = tables.physical(older->request.virtualAddress);
                    const uint64_t loadPa = tables.physical(address);
                    const unsigned __int128 storeEnd = static_cast<unsigned __int128>(storePa) + 8;
                    const unsigned __int128 loadEnd = static_cast<unsigned __int128>(loadPa) + 8;
                    check(CANONICAL_STORE_OVERLAP && older->started && older->upstreamSeen &&
                        storeCertificates.count(key) && storeCertificates[key] < cycle &&
                        certificateEpochs[key] == d.get_io$$epoch() &&
                        (storeEnd <= loadPa || loadEnd <= storePa),
                        "younger load crossed unissued, uncertified, stale or physically aliasing older store");
                    if (!responded.count(key)) {
                        check(d.get_io$$serialStoreOwner$$valid() && d.get_io$$serialStoreSlotLive(),
                            "earlier load start did not overlap an actually live serial store slot");
                        check(d.get_io$$serialStoreOwner$$bits$$index() == older->token.index &&
                            d.get_io$$serialStoreOwner$$bits$$tag() == older->token.tag,
                            "overlap witness lost exact live serial store generation");
                        overlapPairs.push_back({key, {token.index, token.tag}, cycle, 0, 0});
                        ++overlappingStoreLoads;
                        if (!firstYoungerStart.count(key)) firstYoungerStart[key] = cycle;
                    }
                }
            } else {
                ++serialStarts;
                const auto found = firstPeek.find(owner->request.virtualAddress);
                if (found != firstPeek.end() && cycle < found->second + 2) ++serialBeforeProof;
            }
        }
        if (d.get_io$$upstreamFire()) {
            const uint64_t address = d.get_io$$upstreamAddress();
            auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) {
                return e.request.memory && !e.upstreamSeen && address ==
                    (e.canonical ? tables.physical(e.request.virtualAddress) : e.request.virtualAddress);
            });
            check(owner != live.end(), "upstream request lost captured VA/PA owner");
            check(bool(d.get_io$$upstreamPrechecked()) == owner->canonical,
                "accepted serial request changed authorization class after late certificate");
            owner->upstreamSeen = true;
            for (auto &pair : overlapPairs) if (pair.load == Key{owner->token.index, owner->token.tag}) {
                check(!pair.request, "duplicate overlapped load upstream acceptance");
                pair.request = cycle;
                if (!responded.count(pair.store)) ++overlapRequests;
            }
            if (d.get_io$$canonicalOrigin$$valid()) {
                const Token origin{unsigned(d.get_io$$canonicalOrigin$$bits$$token$$index()),
                    uint64_t(d.get_io$$canonicalOrigin$$bits$$token$$tag())};
                check(CANONICAL_STORE_OVERLAP && owner->request.store && owner->token == origin &&
                    owner == live.begin() && d.get_io$$canonicalOrigin$$bits$$epoch() == d.get_io$$epoch(),
                    "accepted canonical origin changed full-token head/store/epoch provenance");
                check(!storeOrigins.count({origin.index, origin.tag}), "duplicate accepted canonical origin");
                storeOrigins[{origin.index, origin.tag}] = cycle;
            }
        }
        const bool originValid = d.get_io$$canonicalOrigin$$valid();
        if (heldOrigin) check(originValid, "held canonical origin disappeared");
        if (originValid) {
            const auto originPayload = std::make_tuple(unsigned(d.get_io$$canonicalOrigin$$bits$$token$$index()),
                uint64_t(d.get_io$$canonicalOrigin$$bits$$token$$tag()),
                uint64_t(d.get_io$$canonicalOrigin$$bits$$epoch()), uint64_t(d.get_io$$upstreamAddress()));
            if (heldOrigin) check(originPayload == *heldOrigin,
                "held origin changed token, generation, epoch or original VA");
            heldOrigin = !d.get_io$$upstreamFire() ? std::optional{originPayload} : std::nullopt;
            originHolds += heldOrigin.has_value();
        } else heldOrigin.reset();
        const bool valid = d.get_io$$physical$$request$$valid();
        std::tuple<uint64_t, uint64_t, bool, unsigned, bool> payload{};
        if (valid) payload = std::make_tuple(uint64_t(d.get_io$$physical$$request$$bits$$address()),
            uint64_t(d.get_io$$physical$$request$$bits$$data()), bool(d.get_io$$physical$$request$$bits$$write()),
            unsigned(d.get_io$$physical$$request$$bits$$mask()), bool(d.get_io$$physical$$request$$bits$$uncached()));
        const bool ready = cycle >= holdPhysicalUntil && cycle % 9 != 5;
        if (held) check(valid && payload == *held, "held data request payload changed");
        held = valid && !ready ? std::optional{payload} : std::nullopt; physicalHolds += valid && !ready;
        if (valid && ready) {
            const auto address = std::get<0>(payload); const bool write = std::get<2>(payload);
            auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) {
                return e.request.memory && !e.requested && (!e.request.fault || e.request.physicalError) &&
                    e.request.store == write && tables.physical(e.request.virtualAddress) == address;
            });
            check(owner != live.end(), "speculative fault/MMIO traffic, duplicate, or unowned physical request");
            owner->requested = true;
            for (auto &pair : overlapPairs) if (pair.load == Key{owner->token.index, owner->token.tag}) {
                check(pair.request && !pair.physical, "overlapped physical fire lacks unique upstream owner");
                pair.physical = cycle;
                if (!responded.count(pair.store)) ++overlapPhysical;
            }
            const auto &mapping = tables.pages.at(unsigned((owner->request.virtualAddress - va) / 4096));
            check(std::get<4>(payload) == (mapping.pbmt != 0), "PBMT cacheability mismatch");
            if (address < ram || address >= ram + ramBytes || mapping.pbmt)
                check(owner == live.begin() && replies.empty(), "device/PBMT request speculated or overlapped");
            check(!d.get_io$$physical$$request$$bits$$virtualized() && !d.get_io$$physical$$request$$bits$$precheckedLoad(),
                "internal authorization metadata leaked downstream");
            if (write) { check(std::get<1>(payload) == architectural[owner->request.rs2] && std::get<3>(payload) == 255,
                "store physical payload mismatch");
                if (!owner->request.physicalError) physicalMemory[address] = std::get<1>(payload);
            }
            const uint64_t data = write ? 0 : (physicalMemory.count(address) ? physicalMemory[address] : readValue(address));
            replies.push_back({cycle + ((secondLatency && physicalRequests == 1) ? secondLatency : latency), data, owner->token, owner->request.physicalError});
            ++physicalRequests; peak = std::max(peak, unsigned(replies.size()));
        }
#define RETIRE(N) \
        if (d.get_io$$commit##N##$$valid()) { \
            check(!live.empty(), "retirement without live owner"); auto e = live.front(); live.pop_front(); \
            const Token token{unsigned(d.get_io$$commit##N##$$bits$$token$$index()), uint64_t(d.get_io$$commit##N##$$bits$$token$$tag())}; \
            check(e.token == token && !e.request.fault && !killed.count({token.index, token.tag}), "retirement full-token order/cancellation mismatch"); \
            check(committedTokens.insert({token.index, token.tag}).second, "duplicate full-token retirement"); \
            check(d.get_io$$commit##N##$$bits$$pc() == e.request.pc && d.get_io$$commit##N##$$bits$$instruction() == e.request.instruction, "retirement provenance mismatch"); \
            if (e.request.writes && e.request.rd) { \
                check(d.get_io$$commit##N##$$bits$$data() == (e.request.expected ^ (inject ? 1ULL : 0ULL)), "independent architectural result mismatch"); \
                architectural[e.request.rd] = e.request.expected; \
            } \
            trace ^= e.request.pc; trace *= 1099511628211ULL; trace ^= e.request.writes ? e.request.expected : 0; trace *= 1099511628211ULL; ++retired; \
        }
        RETIRE(0) RETIRE(1)
#undef RETIRE
        if (d.get_io$$trap$$valid()) {
            check(!live.empty(), "trap without live owner"); const auto e = live.front();
            const Token token{unsigned(d.get_io$$trap$$bits$$token$$index()), uint64_t(d.get_io$$trap$$bits$$token$$tag())};
            check(e.request.fault && token == e.token && d.get_io$$trap$$bits$$pc() == e.request.pc &&
                d.get_io$$trap$$bits$$cause() == e.request.expectedCause &&
                d.get_io$$trap$$bits$$tval() == e.request.virtualAddress, "precise fault must retain original VA, PC and full token");
            lastTrapToken = token;
            lastTrapCause = d.get_io$$trap$$bits$$cause();
            lastTrapVa = d.get_io$$trap$$bits$$tval();
            for (const auto &young : live) killed.insert({young.token.index, young.token.tag});
            live.clear(); ++trapCount;
        }
        upstreamAccepted += d.get_io$$upstreamFire();
        upstreamCompleted += d.get_io$$upstreamResponseFire();
        check(upstreamCompleted <= upstreamAccepted, "CPU response exceeded accepted ordered owners");
        acceptedPeak = std::max(acceptedPeak, upstreamAccepted - upstreamCompleted);
        const auto owners = __builtin_popcount(unsigned(d.get_io$$lsuLive()));
        check(owners < liveDistribution.size(), "LSU occupancy exceeded bounded owner capacity");
        ++liveDistribution[owners];
        const auto reason = unsigned(d.get_io$$memoryStall());
        check(reason < stalls.size(), "memory stall reason out of range"); ++stalls[reason];
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit();
        ++cycle; return out;
    }
    std::vector<Token> submit(std::vector<Request> requests) {
        for (auto &r : requests) { r.pc = nextPc; nextPc += 4; }
        std::vector<Token> tokens; unsigned cursor = 0;
        for (unsigned n = 0; n < 2000 && cursor < requests.size(); ++n) {
            Input in; in.requests[0] = requests[cursor]; if (cursor + 1 < requests.size()) in.requests[1] = requests[cursor + 1];
            const auto out = tick(in);
            for (unsigned lane = 0; lane < 2; ++lane) if (out.accepted[lane]) { tokens.push_back(out.tokens[lane]); ++cursor; }
        }
        check(cursor == requests.size(), "allocation timed out"); return tokens;
    }
    void drain() {
        for (unsigned n = 0; n < 4000 && (!live.empty() || !replies.empty() || !ptes.empty()); ++n) tick();
        check(live.empty() && replies.empty() && ptes.empty(), "pipeline failed to drain");
        for (unsigned n = 0; n < 12; ++n) tick();
        check(d.get_io$$idle() && upstreamAccepted == upstreamCompleted,
            "idle omitted accepted ownership or canceled-owner responses");
    }
    void one(Request r) { submit({r}); drain(); }
    void csr(unsigned address, uint64_t value) { one(add(31, value)); one(system((address << 20) | (31 << 15) | (1 << 12) | 0x73, 31)); }
    void divideOperands() { one(add(25, 123456789)); one(add(26, 7)); }
    void configure() {
        csr(0x3b0, allPmp); csr(0x3a0, 0x1f); csr(0x180, satp); csr(0x300, (1ULL << 17) | (1ULL << 11));
        check(d.get_io$$vm$$satp() == satp && d.get_io$$vm$$dataPrivilege() == 1, "real CSR setup did not establish virtual S data access");
    }
    void warm() { const auto begin = cycle; one(load(1, va)); one(load(2, va + 4096)); coldCycles = cycle - begin; }
    void clearCounters() {
        check(upstreamAccepted == upstreamCompleted, "cannot reset accounting with live accepted owners");
        stalls.fill(0); liveDistribution.fill(0); upstreamAccepted = upstreamCompleted = acceptedPeak = 0;
        certificateToResponseCycles = firstLoadLeadCycles = 0;
        overlapPairs.clear(); overlapRequests = overlapPhysical = 0;
        certifiedStores = overlappingStoreLoads = originHolds = 0; caseStart = cycle; peak = physicalRequests = physicalResponses = precheckedStarts = serialStarts = serialBeforeProof = physicalHolds = queryHits = 0; firstPeek.clear(); }
    void wait(unsigned count) { for (unsigned n = 0; n < count; ++n) tick(); }
    void recover(Token token) {
        Input in; in.recover = true; in.boundary = token;
        bool accepted = false; for (unsigned n = 0; n < 100 && !accepted; ++n) accepted = tick(in).recovered;
        check(accepted, "recovery not accepted");
    }
    void report(const std::string &name) const {
        std::cout << "CANONICAL_BACKEND_CASE name=" << name << " trace=" << trace << " retired=" << retired << " physical=" << physicalRequests
            << " cycles=" << cycle - caseStart << " cold_cycles=" << coldCycles << " serial_before_proof=" << serialBeforeProof << " peak=" << peak << " prechecked=" << precheckedStarts << " serial=" << serialStarts << " traps=" << trapCount
            << " certificates=" << certifiedStores << " overlap_store_loads=" << overlappingStoreLoads
            << " overlap_request_fires=" << overlapRequests << " overlap_physical_fires=" << overlapPhysical
            << " origin_holds=" << originHolds << " accepted_peak=" << acceptedPeak
            << " cert_to_response_cycles=" << certificateToResponseCycles << " younger_lead_cycles=" << firstLoadLeadCycles
            << " holds=" << physicalHolds << " cancellations=" << cancellations << " reuse=" << reuse << " cancelled_slot_reuse=" << cancelledSlotReuse;
        // The inherited prepared-address predicate cannot distinguish newly certified
        // physical aliases from uncanonical/unissued stores. Keep that bucket explicitly
        // unresolved; exact transaction-pair witnesses remain separately authoritative.
        for (unsigned n = 0; n < stalls.size(); ++n) {
            if (n == 3) std::cout << " unresolved_store_stall=" << stalls[n];
            else std::cout << " stall" << n << "=" << stalls[n];
        }
        for (unsigned n = 0; n < liveDistribution.size(); ++n) std::cout << " live" << n << "=" << liveDistribution[n];
        std::cout << std::endl;
        for (const auto &pair : overlapPairs) {
            std::cout << "CANONICAL_BACKEND_PAIR case=" << name << " store=" << pair.store.first << ":" << pair.store.second
                << " younger=" << pair.load.first << ":" << pair.load.second << " lsu_start=" << pair.start
                << " upstream_fire=" << pair.request << " physical_fire=" << pair.physical;
            const auto response = storeResponseCycles.find(pair.store);
            if (response != storeResponseCycles.end()) std::cout << " store_response=" << response->second;
            std::cout << '\n';
        }
    }
};
int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject-result";
    const bool injectCancelledRetirement = argc > 1 && std::string(argv[1]) == "--inject-cancel-retirement";
    { Bench b; b.inject = inject; b.configure(); b.warm(); b.divideOperands(); b.clearCounters();
      b.holdReplyUntil = b.cycle + 100; b.submit({divide(), load(3, va + 8), load(4, va + 4096 + 16)}); b.drain();
      b.check(b.physicalRequests == 2 && b.peak == (PRECHECK_ENABLED ? 2U : 1U), "two warm virtual RAM loads did not establish expected physical overlap");
      b.check(b.precheckedStarts == (PRECHECK_ENABLED ? 2U : 0U), "warm loads did not use the certified path"); b.report("warm_overlap"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters(); b.one(load(3, va + 8));
      b.check(b.physicalRequests == 1 && b.serialStarts == 1 && b.precheckedStarts == 0,
          "unprepared head load did not use original serial translation"); b.report("head_serial_single"); }
    { Bench b; b.configure(); b.clearCounters(); b.one(load(3, va + 8));
      b.check(b.physicalRequests == 1 && b.serialStarts == 1 && b.precheckedStarts == 0,
          "cold head load waited for or used an optional certificate"); b.report("cold_head_serial_single"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters();
      b.holdPhysicalUntil = b.cycle + 100; b.submit({load(3, va + 8)}); b.wait(20);
      b.check(b.serialStarts == 1 && b.precheckedStarts == 0 && b.physicalRequests == 0 &&
          (!PRECHECK_ENABLED || (b.queryHits > 0 && b.serialBeforeProof == 1)),
          "head serial owner was not held across late certificate arrival");
      b.drain(); std::vector<Request> reuseProgram;
      for (unsigned n = 0; n < 32; ++n) reuseProgram.push_back(add(3 + n % 20, 0x200 + n));
      b.submit(reuseProgram); b.drain(); b.one(load(3, va + 8));
      b.check(b.reuse > 0 && b.precheckedStarts == 0, "late head certificate escaped through owner reuse");
      b.report("head_serial_held_proof"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters(); b.holdPhysicalUntil = b.cycle + 65;
      b.submit({load(3, va + 8), load(4, va + 4096 + 16)}); b.wait(35); b.commitEnable = false; b.wait(70);
      b.commitEnable = true; b.drain(); b.check(b.physicalHolds > 0, "request backpressure not exercised"); b.report("backpressure"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters();
      auto dependentAddress = load(11, va + 4096 + 8); dependentAddress.rs1 = 10;
      dependentAddress.immediate = dependentAddress.virtualAddress - readValue(ram + 8);
      b.submit({load(10, va + 8), dependentAddress, load(12, va + 32)}); b.drain();
      b.check(b.physicalRequests == 3, "uncanonical older load lost demand ownership"); b.report("older_uncanonical_load"); }
    { Bench b; b.configure(); b.warm(); b.one(load(5, va + 2 * 4096)); b.one(add(30, 0x1122334455667788ULL)); b.clearCounters();
      b.submit({store(va), load(6, va + 2 * 4096)}); b.drain(); b.report("physical_alias_store_order"); }
    for (unsigned page : {3U, 4U, 7U}) {
      Bench b; b.configure(); b.one(load(1, va + page * 4096)); b.warm(); b.clearCounters();
      b.submit({load(3, va + 8), load(4, va + page * 4096), load(5, va + 4096 + 16)}); b.drain();
      b.report("serial_page_" + std::to_string(page));
    }
    { Bench b; b.configure(); b.warm(); b.divideOperands(); b.clearCounters();
      Request branch = add(0, 32); branch.branch = true; branch.writes = false; branch.rs1 = branch.rs2 = 3;
      branch.instruction = 0x02318063;
      b.holdReplyUntil = b.cycle + 150; b.secondLatency = 400;
      b.submit({divide(), load(3, va + 8), branch, load(4, va + 4096 + 16)});
      for (unsigned n = 0; n < 400 && !b.redirects; ++n) b.tick();
      b.check(b.redirects == 1, "real mispredicted branch did not cancel younger load");
      b.wait(12);
      std::vector<Request> reuseProgram;
      for (unsigned n = 0; n < 32; ++n) reuseProgram.push_back(add(3 + n % 20, 0x100 + n));
      b.submit(reuseProgram);
      if (PRECHECK_ENABLED) b.check(b.physicalResponses < b.physicalRequests && b.cancelledSlotReuse > 0,
          "ROB token was not reused while cancelled physical response remained in flight");
      b.drain(); b.secondLatency = 0;
      b.one(load(3, va + 24));
      b.check(b.cancellations == 1 && b.reuse > 0, "cancellation/token generation reuse not exercised"); b.report("cancel_token_reuse"); }
    { Bench b; b.configure(); b.warm(); const auto oldEpoch = b.cycle; (void)oldEpoch;
      b.one(system(0x12000073)); b.tables.pages[0].physical = ram + 24576;
      b.one(load(7, va)); b.one(load(8, va + 8)); b.report("sfence_remap"); }
    { Bench b; b.configure(); b.warm(); b.one(add(31, 0x18)); b.clearCounters();
      auto denied = load(5, va + 4096 + 8); denied.fault = true; denied.expectedCause = 5;
      const auto revoke = system((0x3a0 << 20) | (31 << 15) | (1 << 12) | 0x73, 31);
      b.submit({load(4, va + 8), revoke, denied}); b.drain();
      b.check(b.trapCount == 0 && b.cancellations == 1,
          "PMP permission change did not flush the younger pre-revocation instruction");
      b.one(denied);
      b.check(b.trapCount == 1 && b.physicalRequests == 1,
          "PMP CSR failed to drain older load or revoked younger proof escaped"); b.report("csr_epoch_drain"); }
    for (unsigned kind = 0; kind < 5; ++kind) {
      Bench b; b.configure(); b.warm(); auto r = load(3, kind == 0 ? va + 9 * 4096 : va + 8);
      r.fault = true; r.expectedCause = kind == 0 ? 13 : kind == 3 ? 4 : 5; r.physicalError = kind == 2 || kind == 4;
      if (kind == 1) b.csr(0x3a0, 0x18);
      if (kind == 2) b.divideOperands();
      if (kind == 3) r.immediate = r.virtualAddress = va + 3;
      b.clearCounters(); if (kind == 2) { b.submit({divide(), r}); b.drain(); } else b.one(r);
      if (kind == 2) b.check(b.precheckedStarts == (PRECHECK_ENABLED ? 1U : 0U),
          "speculative downstream-error certificate path was not exercised");
      if (kind == 4) b.check(b.serialStarts == 1 && b.precheckedStarts == 0,
          "head-serial physical-error path was not exercised");
      b.check(b.trapCount == 1 && b.physicalRequests == ((kind == 2 || kind == 4) ? 1U : 0U), "fault generated unauthorized data traffic");
      b.report("fault_" + std::to_string(kind));
    }
    // The real store ACK is deliberately delayed. OFF must remain serial; ON
    // must expose an actual earlier load start, not merely emit a certificate.
    { Bench b; b.configure(); b.warm(); b.one(add(30, 0x1122334455667788ULL)); b.clearCounters();
      b.holdReplyUntil = b.cycle + 160;
      b.submit({store(va), load(6, va + 4096 + 16)}); b.drain();
      b.check(b.physicalRequests == 2 && b.peak == (CANONICAL_STORE_OVERLAP ? 2U : 1U),
          "warm store-to-load overlap did not change actual physical occupancy");
      b.check(b.overlappingStoreLoads == (CANONICAL_STORE_OVERLAP ? 1U : 0U) &&
          b.overlapRequests == (CANONICAL_STORE_OVERLAP ? 1U : 0U) &&
          b.overlapPhysical == (CANONICAL_STORE_OVERLAP ? 1U : 0U),
          "missing separate LSU/request/physical overlap witnesses before the real store response"); b.report("checked_head_store_overlap"); }
    { Bench b; b.configure(); b.warm(); b.one(load(5, va + 8192));
      b.one(add(30, 0x7766554433221100ULL)); b.clearCounters(); b.holdReplyUntil = b.cycle + 120;
      b.submit({store(va), load(6, va + 8192)}); b.drain();
      b.check(b.overlappingStoreLoads == 0 && b.peak == 1, "distinct virtual aliases bypassed live store");
      b.report("certified_physical_alias_block"); }
    { Bench b; b.configure(); b.warm(); b.one(add(30, 0x1234)); b.clearCounters();
      b.holdReplyUntil = b.cycle + 120;
      b.submit({store(va), store(va + 8), load(6, va + 4096 + 16)}); b.drain();
      b.check(b.physicalRequests == 3 && b.overlappingStoreLoads == (CANONICAL_STORE_OVERLAP ? 1U : 0U),
          "unissued intervening store was skipped or final eligible overlap absent");
      b.report("second_unknown_store_barrier"); }
    { Bench b; b.configure(); b.warm(); b.one(add(30, 0xdeadbeef)); b.clearCounters();
      auto failing = store(va); failing.fault = failing.physicalError = true; failing.expectedCause = 7;
      const auto before = b.retired; b.holdReplyUntil = b.cycle + 180;
      auto dependent = add(7, 1); dependent.rs1 = 6;
      dependent.expected = readValue(ram + 4096 + 16) + 1;
      const auto packet = b.submit({failing, load(6, va + 4096 + 16), dependent}); b.drain();
      b.check(packet.size() == 3 && !b.wasRetired(packet[1]) && !b.wasRetired(packet[2]) &&
          !injectCancelledRetirement, "faulted store allowed the younger load or dependent full token to retire");
      b.check(b.lastTrapToken && *b.lastTrapToken == packet[0] && b.lastTrapCause == 7 && b.lastTrapVa == va,
          "late certified store error changed the faulting full token, original VA or access-fault cause");
      b.check(b.trapCount == 1 && b.retired == before &&
          b.overlappingStoreLoads == (CANONICAL_STORE_OVERLAP ? 1U : 0U) &&
          b.overlapRequests == (CANONICAL_STORE_OVERLAP ? 1U : 0U) &&
          b.overlapPhysical == (CANONICAL_STORE_OVERLAP ? 1U : 0U),
          "late certified store error lost precise trap or let younger load/dependency retire");
      b.check(b.physicalRequests == b.physicalResponses, "late store error did not drain every accepted owner");
      std::cout << "CANONICAL_BACKEND_LATE_STORE_FAULT store=" << packet[0].index << ":" << packet[0].tag
          << " young=" << packet[1].index << ":" << packet[1].tag
          << " dependent=" << packet[2].index << ":" << packet[2].tag
          << " young_retired=" << b.wasRetired(packet[1]) << " dependent_retired=" << b.wasRetired(packet[2])
          << " cause=" << b.lastTrapCause << " tval=0x" << std::hex << b.lastTrapVa << std::dec
          << " upstream_accepted=" << b.upstreamAccepted << " upstream_returned=" << b.upstreamCompleted
          << " physical_accepted=" << b.physicalRequests << " physical_returned=" << b.physicalResponses
          << " outstanding=" << b.upstreamAccepted - b.upstreamCompleted << '\n';
      b.report("late_certified_store_error"); }
    { Bench b; b.configure(); b.warm(); b.one(add(30, 0xfeedface)); b.clearCounters();
      auto failing = load(6, va + 4096 + 16); failing.fault = failing.physicalError = true; failing.expectedCause = 5;
      b.holdReplyUntil = b.cycle + 140; b.submit({store(va), failing}); b.drain();
      b.check(b.trapCount == 1 && b.physicalRequests == 2 && b.physicalResponses == 2 &&
          b.overlappingStoreLoads == (CANONICAL_STORE_OVERLAP ? 1U : 0U),
          "late overlapping load access error failed precise response ownership"); b.report("late_overlap_load_error"); }
    std::cout << "CANONICAL_BACKEND_PASS enabled=" << CANONICAL_STORE_OVERLAP << "\n"; return 0;
} catch (const std::exception &e) { std::cerr << "CANONICAL_BACKEND_FAIL " << e.what() << "\n"; return 1; } }
