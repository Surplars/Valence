#include "CombinedCheckedDataFlowGsim.h"
#define VIRTUAL_LOAD_TEST_RAM_BASE 0x80200000ULL
#define VIRTUAL_LOAD_TEST_RAM_BYTES (1ULL << 31)
#include "virtual_load_test_memory.h"
#include "../m2_data_translation/oracle.h"
#include <algorithm>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <string>
#include <tuple>
#include <vector>

#ifndef COMBINED_CHECKED_FLOW
#define COMBINED_CHECKED_FLOW 0
#endif
using namespace canonical_store_test;

// Independent architectural oracle: software PTEs, byte ranges, R/W/X/U/A/D,
// PMP and expected ordered memory replies. Passive DUT events establish where
// an owner moved, never whether its address, rights or canonical proof is valid.
struct Request {
    Descriptor descriptor;
    bool origin = false, write = true, atomic = false, virt = true;
    bool prechecked = false, uncached = false, lateError = false;
    unsigned atomicOp = 0;
    uint32_t translationEpoch = 0;
    uint64_t data = 0;
};
struct Entry {
    Request request;
    uint64_t id = 0, acceptedCycle = 0, physical = 0;
    bool pageFault = false, accessFault = false, uncached = false, certify = false, prefetch = false;
    bool routed = false, checked = false, physicalSeen = false, certificateSeen = false;
    bool fault() const { return pageFault || accessFault; }
};
struct Reply { uint64_t due, data; bool error = false; };
using Payload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, unsigned,
    bool, bool, bool, uint64_t, bool>;
using Response = std::tuple<uint64_t, bool, bool>;

class Bench {
    SCombinedCheckedDataFlowGsim d;
    std::deque<Reply> ptes, replies;
    std::map<uint64_t, Entry> records;
    std::deque<uint64_t> ordered, ingress, translated, checked, owners;
    std::optional<uint64_t> waiting, pendingFullRelease;
    std::optional<Payload> held;
    std::optional<Response> heldResponse;
    bool injected = false;
public:
    virtual_load_test::PageTables tables;
    uint64_t cycle = 0, blockPhysical = 0, blockResponse = 0, context = virtual_load_test::satp;
    uint64_t pmpAddress = virtual_load_test::allPmp;
    uint32_t epoch = 1;
    unsigned cfg = 0x1f, privilege = 1, latency = 1, pteLatency = 2;
    bool sum = false, mxr = false, flush = false, periodic = false;
    unsigned accepted = 0, returned = 0, physical = 0, certificates = 0, faults = 0;
    unsigned incomingFires = 0, translationFires = 0, translatedPushes = 0, translatedPops = 0, checkedPushes = 0;
    unsigned hitPasses = 0, precheckedPasses = 0, hitSpills = 0, precheckedSpills = 0;
    unsigned ownerPushes = 0, ownerPops = 0, walks = 0, hits = 0, pteReads = 0;
    unsigned heldPhysical = 0, heldResponses = 0, heldUpstream = 0;
    unsigned checkedFull = 0, translatedFull = 0, ownersFull = 0, fullReleaseEvents = 0;
    unsigned olderPopNewSpill = 0, acceptedMissWaiting = 0, lateErrors = 0;
    uint64_t trace = 1469598103934665603ULL;
    std::vector<uint64_t> acceptCycles, physicalCycles, returnCycles, physicalLatencies, releaseGaps;
    std::string mutation;

    Bench(const std::string &mode = "") : mutation(mode) {
        drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        settle(); check(d.get_io$$epoch() == epoch && d.get_io$$stable(), "initial authorization epoch did not settle");
    }
    void check(bool ok, const std::string &message) const {
        require(ok, "cycle=" + std::to_string(cycle) + " " + message);
    }
    bool mutate(const std::string &option, const std::string &marker, bool eligible = true) {
        if (mutation != option || injected || !eligible) return false;
        injected = true; std::cout << marker << '\n' << std::flush; return true;
    }
    bool pmpAllows(uint64_t address, uint64_t bytes, bool read, bool write) const {
        // One NAPOT entry followed by 15 OFF entries. Decode independently and
        // require every accessed byte, not just the starting byte, to match.
        if (privilege == 3 && !(cfg & 0x80)) return true;
        if (((cfg >> 3) & 3) != 3) return false;
        unsigned ones = 0;
        while (ones < 54 && ((pmpAddress >> ones) & 1)) ++ones;
        const unsigned __int128 mask = (static_cast<unsigned __int128>(1) << ones) - 1;
        const unsigned __int128 base = (static_cast<unsigned __int128>(pmpAddress) & ~mask) << 2;
        const unsigned __int128 limit = base + (static_cast<unsigned __int128>(1) << (ones + 3));
        const unsigned __int128 end = static_cast<unsigned __int128>(address) + bytes;
        return address >= base && end <= limit && (!read || (cfg & 1)) && (!write || (cfg & 2));
    }
    Entry truth(const Request &r) const {
        Entry e; e.request = r; const auto &a = r.descriptor;
        const bool needsRead = r.atomic ? r.atomicOp != 3 : !r.write;
        const bool needsWrite = r.atomic ? r.atomicOp != 2 : r.write;
        e.physical = a.virtualAddress; e.uncached = r.uncached;
        if (r.prechecked) {
            e.accessFault = r.virt || r.write || r.atomic || r.uncached || privilege == 3 || !(context >> 60) ||
                r.translationEpoch != epoch || !wholeRam(e.physical, a.size) ||
                (COMBINED_CHECKED_FLOW && (!aligned(e.physical, a.size) || a.mask != lanes(e.physical, a.size)));
        } else if (r.virt && privilege != 3 && (context >> 60)) {
            const bool canonical = (a.virtualAddress >> 39) == 0 && ((a.virtualAddress >> 38) & 1) == 0;
            const auto found = tables.pages.find(unsigned((a.virtualAddress - va) / 4096));
            if (!canonical || found == tables.pages.end()) e.pageFault = true;
            else {
                const auto &m = found->second; const unsigned flags = m.flags;
                const bool readable = flags & 2, writable = flags & 4, executable = flags & 8;
                const bool user = flags & 16, accessed = flags & 64, dirty = flags & 128;
                e.physical = m.physical + a.virtualAddress % 4096;
                e.uncached |= m.pbmt != 0;
                e.pageFault = !(flags & 1) || (!readable && writable) || !(readable || executable) || !accessed ||
                    (needsRead && !readable && !(mxr && executable)) || (needsWrite && (!writable || !dirty)) ||
                    (privilege == 1 && user && !sum) || (privilege == 0 && !user) || m.pbmt == 3;
            }
        }
        if (!e.pageFault && (r.virt || r.prechecked))
            e.accessFault |= !pmpAllows(e.physical, uint64_t(1) << a.size, needsRead, needsWrite) ||
                (r.atomic && !wholeRam(e.physical, a.size));
        auto actualShape = a; actualShape.physicalAddress = e.physical;
        e.certify = !e.fault() && r.origin && r.virt && r.write && !r.atomic && !r.prechecked &&
            !e.uncached && a.epoch == epoch && shape(actualShape);
        const uint64_t next = (e.physical & ~63ULL) + 64;
        e.prefetch = !e.fault() && !r.write && !r.atomic && !e.uncached && wholeRam(e.physical, a.size) &&
            (e.physical & 4095) < 4032 && next >= ram && next + 64 <= ram + ramBytes &&
            pmpAllows(next, 64, true, false);
        return e;
    }
    bool physicalReady() const { return cycle >= blockPhysical && (!periodic || cycle % 7 != 5); }
    bool pteReady() const { return !periodic || cycle % 5 != 3; }
    void drive(std::optional<Request> request) {
        const auto r = request.value_or(Request{}); const auto &a = r.descriptor;
        d.set_io$$upstream$$request$$valid(request.has_value());
        d.set_io$$upstream$$request$$bits$$address(a.virtualAddress);
        d.set_io$$upstream$$request$$bits$$data(r.data);
        d.set_io$$upstream$$request$$bits$$size(a.size); d.set_io$$upstream$$request$$bits$$mask(a.mask);
        d.set_io$$upstream$$request$$bits$$write(r.write); d.set_io$$upstream$$request$$bits$$atomic(r.atomic);
        d.set_io$$upstream$$request$$bits$$atomicOp(r.atomicOp);
        d.set_io$$upstream$$request$$bits$$virtualized(r.virt);
        d.set_io$$upstream$$request$$bits$$uncached(r.uncached);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(r.prechecked);
        d.set_io$$upstream$$request$$bits$$translationEpoch(r.translationEpoch);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(1); // Deliberately untrusted ingress hint.
        d.set_io$$origin$$valid(request && r.origin);
        d.set_io$$origin$$bits$$token$$index(a.token.index); d.set_io$$origin$$bits$$token$$tag(a.token.tag);
        d.set_io$$origin$$bits$$epoch(a.epoch);
        d.set_io$$upstream$$response$$ready(cycle >= blockResponse);
        d.set_io$$physical$$request$$ready(physicalReady());
        const bool response = !replies.empty() && replies.front().due <= cycle;
        d.set_io$$physical$$response$$valid(response);
        d.set_io$$physical$$response$$bits$$data(response ? replies.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(response && replies.front().error);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$request$$ready(pteReady()); d.set_io$$pte$$response$$valid(pte);
        d.set_io$$pte$$response$$bits$$data(pte ? ptes.front().data : 0); d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(context); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(pmpAddress); d.set_io$$flush(flush);
    }
    bool tick(std::optional<Request> request = {}) {
        const bool response = !replies.empty() && replies.front().due <= cycle;
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        drive(request); d.step();
        const bool take = request && d.get_io$$upstream$$request$$ready();
        if (take) {
            auto e = truth(*request); e.id = accepted; e.acceptedCycle = cycle;
            records.emplace(e.id, e); ordered.push_back(e.id); ingress.push_back(e.id);
            acceptCycles.push_back(cycle); ++accepted;
        }
        heldUpstream += request && !take;
        if (response && d.get_io$$physical$$response$$ready()) replies.pop_front();
        if (pte && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && pteReady()) {
            ptes.push_back({cycle + pteLatency, tables.pte(d.get_io$$pte$$request$$bits())}); ++pteReads;
        }
        // Queue counts are checked before applying this edge's independent events.
        check(d.get_io$$translatedCount() == translated.size() && d.get_io$$checkedCount() == checked.size() &&
            d.get_io$$ownerCount() == owners.size(), "passive queue counts disagree with exact owner ledger");
        const bool hp = d.get_io$$hitPass(), pp = d.get_io$$precheckedPass();
        const bool tp = d.get_io$$translatedPush(), tq = d.get_io$$translatedPop();
        const bool cp = d.get_io$$checkedPush(), cq = d.get_io$$checkedPop();
        const bool op = d.get_io$$ownerPush(), oq = d.get_io$$ownerPop();
        const bool tf = d.get_io$$translationFire(), tr = d.get_io$$translationReply();
        std::optional<uint64_t> incomingId, resultId, checkedId;
        if (d.get_io$$incomingFire()) {
            check(!ingress.empty(), "raw ingress consumed an unaccepted owner");
            incomingId = ingress.front(); ingress.pop_front(); ++incomingFires;
            const auto &r = records.at(*incomingId).request;
            check(d.get_io$$incomingAddress() == r.descriptor.virtualAddress && d.get_io$$incomingData() == r.data,
                "registered raw ingress payload/owner mismatch");
            check(tf == (r.virt && !r.prechecked), "raw ingress translation ownership mismatch");
            if (tf && !tr) {
                check(!waiting, "second miss overwrote saved raw request"); waiting = incomingId; ++acceptedMissWaiting;
            } else resultId = incomingId;
        } else check(!tf, "translation request has no raw ingress owner");
        if (tr && !tf) {
            check(waiting.has_value() && !resultId, "late translation reply lacks its saved owner");
            resultId = waiting; waiting.reset();
        }
        check(!(hp && pp), "raw hit and prechecked direct paths claimed one result twice");
        if (resultId) {
            auto &e = records.at(*resultId);
            check(!e.routed && (unsigned(tp) + unsigned(hp) + unsigned(pp) == 1),
                "exact raw result must enter translated XOR direct checked once");
            e.routed = true;
            check(!hp || (e.request.virt && !e.request.prechecked && !e.request.atomic && !e.uncached && !e.pageFault),
                "raw translation hit bypass accepted a forbidden request kind");
            check(!pp || (COMBINED_CHECKED_FLOW && e.request.prechecked), "prechecked direct owner mismatch");
            if (tp) {
                check(d.get_io$$translatedData() == e.request.data, "translated spill payload/owner mismatch");
                if (!e.pageFault) check(d.get_io$$translatedAddress() == e.physical, "translated spill PA mismatch");
            }
        } else check(!tp && !hp && !pp, "result appeared without current or saved raw owner");
        // Older FIFO -> checked and new raw -> FIFO are LEGAL on one edge.
        // Their identities must not be conflated into global push exclusivity.
        if (tq) {
            check(!translated.empty(), "translated FIFO popped without an older owner");
            checkedId = translated.front(); translated.pop_front();
        }
        if (hp || pp) {
            check(!checkedId && resultId, "direct source overtook an older translated owner"); checkedId = resultId;
        }
        check(cp == checkedId.has_value(), "checked admission lacked exactly one source owner");
        olderPopNewSpill += tq && tp;
        if (cp) {
            auto &e = records.at(*checkedId);
            check(!e.checked && d.get_io$$checkedData() == e.request.data, "checked payload/owner duplicated or changed");
            if (!e.pageFault) check(d.get_io$$checkedAddress() == e.physical, "checked physical address mismatch");
            check(bool(d.get_io$$checkedFault()) == e.fault() && bool(d.get_io$$checkedPageFault()) == e.pageFault,
                "checked authorization disagrees with independent permissions");
            e.checked = true;
        }
        if (d.get_io$$certificate$$valid()) {
            check(checkedId.has_value(), "canonical event without same-edge checked owner");
            auto &e = records.at(*checkedId); const auto &a = e.request.descriptor;
            const bool poison = mutate("--inject-canonical", "INJECT COMBINED_CHECKED_FLOW canonical attribution");
            check(e.certify && !e.certificateSeen && !e.request.prechecked && e.request.write && !e.request.atomic &&
                (d.get_io$$certificate$$bits$$origin$$token$$index() ^ (poison ? 1u : 0u)) == a.token.index &&
                d.get_io$$certificate$$bits$$origin$$token$$tag() == a.token.tag &&
                d.get_io$$certificate$$bits$$origin$$epoch() == a.epoch &&
                d.get_io$$certificate$$bits$$virtualAddress() == a.virtualAddress &&
                d.get_io$$certificate$$bits$$physicalAddress() == e.physical &&
                d.get_io$$certificate$$bits$$size() == a.size && d.get_io$$certificate$$bits$$mask() == a.mask,
                "independent canonical certificate attribution mismatch");
            e.certificateSeen = true; ++certificates;
        }
        if (checkedId) check(records.at(*checkedId).certificateSeen == records.at(*checkedId).certify,
            "checked raw store lacks exact required canonical certificate");

        const bool valid = d.get_io$$physical$$request$$valid();
        check(cq == op, "checked pop and response-owner push separated");
        if (held) check(valid, "held physical request withdrew valid");
        if (valid) {
            const Payload payload{d.get_io$$physical$$request$$bits$$address(), d.get_io$$physical$$request$$bits$$data(),
                unsigned(d.get_io$$physical$$request$$bits$$size()), unsigned(d.get_io$$physical$$request$$bits$$mask()),
                bool(d.get_io$$physical$$request$$bits$$write()), bool(d.get_io$$physical$$request$$bits$$atomic()),
                unsigned(d.get_io$$physical$$request$$bits$$atomicOp()), bool(d.get_io$$physical$$request$$bits$$uncached()),
                bool(d.get_io$$physical$$request$$bits$$virtualized()), bool(d.get_io$$physical$$request$$bits$$precheckedLoad()),
                d.get_io$$physical$$request$$bits$$translationEpoch(), bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())};
            if (held) check(payload == *held, "held physical payload or authorization hint changed");
            held = !physicalReady() ? std::optional<Payload>{payload} : std::nullopt;
            heldPhysical += !physicalReady();
            if (physicalReady()) {
                check(op && !checked.empty(), "physical request has no checked owner");
                auto &e = records.at(checked.front()); const auto &r = e.request;
                const bool poison = mutate("--inject-pa", "INJECT COMBINED_CHECKED_FLOW physical PA");
                check(!e.fault() && !e.physicalSeen && (std::get<0>(payload) ^ (poison ? 8ULL : 0ULL)) == e.physical,
                    "independent physical PA/order mismatch");
                check(std::get<1>(payload) == r.data && std::get<2>(payload) == r.descriptor.size &&
                    std::get<3>(payload) == r.descriptor.mask && std::get<4>(payload) == r.write &&
                    std::get<5>(payload) == r.atomic && std::get<6>(payload) == r.atomicOp &&
                    std::get<7>(payload) == e.uncached && !std::get<8>(payload) && !std::get<9>(payload) &&
                    std::get<10>(payload) == 0, "independent physical shape/private-metadata mismatch");
                check(std::get<11>(payload) == e.prefetch, "independent next-line READ PMP/page/range mismatch");
                check(e.certificateSeen == e.certify, "physical owner missing canonical attribution");
                e.physicalSeen = true; ++physical;
                physicalCycles.push_back(cycle); physicalLatencies.push_back(cycle - e.acceptedCycle);
                replies.push_back({cycle + latency, r.write ? 0 : beatData(e.physical), r.lateError});
            }
        }
        if (op) {
            check(!checked.empty(), "response owner appeared without checked descriptor");
            const auto &e = records.at(checked.front());
            check(bool(d.get_io$$ownerFault()) == e.fault() && bool(d.get_io$$ownerPageFault()) == e.pageFault &&
                e.physicalSeen == !e.fault(), "fault placeholder or real physical owner mismatch");
        }
        const bool responseValid = d.get_io$$upstream$$response$$valid();
        check(oq == (responseValid && cycle >= blockResponse), "response handshake lost its owner pop");
        if (heldResponse) check(responseValid, "held ordered response withdrew valid");
        if (responseValid) {
            const Response payload{d.get_io$$upstream$$response$$bits$$data(),
                bool(d.get_io$$upstream$$response$$bits$$error()), bool(d.get_io$$upstream$$response$$bits$$pageFault())};
            if (heldResponse) check(payload == *heldResponse, "held ordered response payload changed");
            heldResponse = cycle < blockResponse ? std::optional<Response>{payload} : std::nullopt;
            heldResponses += cycle < blockResponse;
            if (cycle >= blockResponse) {
                check(!owners.empty() && !ordered.empty() && owners.front() == ordered.front(),
                    "response reordered or lost exact accepted owner");
                const auto id = owners.front(); const auto &e = records.at(id);
                const bool fault = e.fault() || e.request.lateError;
                const bool poisonFault = mutate("--inject-fault", "INJECT COMBINED_CHECKED_FLOW response fault", fault);
                check((std::get<1>(payload) ^ poisonFault) == fault && std::get<2>(payload) == e.pageFault,
                    "independent ordered fault classification mismatch");
                const uint64_t data = e.fault() || e.request.write ? 0 : beatData(e.physical);
                const bool poisonData = mutate("--inject-data", "INJECT COMBINED_CHECKED_FLOW response data", !e.request.write);
                check((std::get<0>(payload) ^ (poisonData ? 1ULL : 0ULL)) == data,
                    "independent ordered response data mismatch");
                check(e.routed && e.checked && e.physicalSeen == !e.fault() && e.certificateSeen == e.certify,
                    "completed owner lacks exact raw/checked/physical/canonical conservation");
                trace ^= e.request.descriptor.virtualAddress; trace *= 1099511628211ULL;
                trace ^= data; trace *= 1099511628211ULL; trace ^= fault; trace *= 1099511628211ULL;
                faults += e.fault(); lateErrors += e.request.lateError; ++returned; returnCycles.push_back(cycle);
                owners.pop_front(); ordered.pop_front(); records.erase(id);
            }
        }
        if (op) { owners.push_back(checked.front()); checked.pop_front(); }
        if (cp) checked.push_back(*checkedId);
        if (tp) translated.push_back(*resultId);
        const auto checkedCount = d.get_io$$checkedCount();
        const auto translatedCount = d.get_io$$translatedCount();
        checkedFull += checkedCount == 2; translatedFull += translatedCount == 8; ownersFull += d.get_io$$ownerCount() == 8;
        hitSpills += d.get_io$$hitOffer() && !hp && checkedCount == 2;
        precheckedSpills += d.get_io$$precheckedOffer() && !pp && checkedCount == 2;
        if (pendingFullRelease && tp) { releaseGaps.push_back(cycle - *pendingFullRelease); pendingFullRelease.reset(); }
        if (translatedCount == 8 && tq) {
            check(!tp, "full translated FIFO borrowed same-cycle pop credit");
            pendingFullRelease = cycle; ++fullReleaseEvents;
        }
        translatedPushes += tp; translatedPops += tq; checkedPushes += cp;
        ownerPushes += op; ownerPops += oq; hitPasses += hp; precheckedPasses += pp; translationFires += tf;
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit();
        ++cycle; return take;
    }
    void settle() { for (unsigned n = 0; n < 5; ++n) tick(); }
    Request raw(uint64_t address = va, bool write = true, unsigned size = 3) const {
        Request r; r.descriptor.virtualAddress = address; r.descriptor.size = size;
        r.descriptor.mask = lanes(address, size); r.descriptor.epoch = epoch;
        r.descriptor.token = Token{unsigned(accepted % 16), 1 + accepted / 16};
        r.data = 0x8877665544332211ULL ^ (uint64_t(accepted) * 0x0102040810204081ULL);
        r.write = write; r.origin = write; return r;
    }
    Request certified(uint64_t address = ram, unsigned size = 3) const {
        auto r = raw(address, false, size); r.prechecked = true; r.virt = false; r.translationEpoch = epoch;
        // A certified load has no store-origin sideband; it must still never emit a store certificate.
        return r;
    }
    void send(const Request &r) {
        for (unsigned n = 0; n < 4000; ++n) if (tick(r)) return;
        throw std::runtime_error("upstream acceptance timed out");
    }
    void drain() {
        for (unsigned n = 0; n < 8000 && (!ordered.empty() || !replies.empty() || !ptes.empty()); ++n) tick();
        settle();
        check(ordered.empty() && records.empty() && ingress.empty() && translated.empty() && checked.empty() &&
            owners.empty() && !waiting && replies.empty() && ptes.empty() && !held && !heldResponse && d.get_io$$idle(),
            "accepted descriptors, fault placeholders or external replies failed to drain");
        check(accepted == returned && accepted == incomingFires && accepted == checkedPushes &&
            accepted == ownerPushes && accepted == ownerPops && translatedPushes == translatedPops &&
            accepted == translatedPushes + hitPasses + precheckedPasses,
            "exact raw request -> checked XOR translated -> owner conservation failed");
        pendingFullRelease.reset();
    }
    void run(const Request &r) { send(r); drain(); }
    void maintenance(bool translationFlush = true) {
        check(ordered.empty() && d.get_io$$idle(), "driver attempted illegal undrained maintenance");
        flush = translationFlush; tick(); flush = false; ++epoch; settle();
        check(d.get_io$$epoch() == epoch && d.get_io$$stable(), "drained authorization epoch mismatch");
    }
    void measure(const std::string &name, unsigned count, unsigned kind, bool congested = false) {
        drain(); periodic = false; latency = 1;
        const auto start = cycle;
        const auto a = accepted, r = returned, ph = physical, h = hits, w = walks;
        const auto hp = hitPasses, pp = precheckedPasses, tp = translatedPushes, tq = translatedPops;
        const auto tf = translationFires, fr = fullReleaseEvents;
        const auto gi = releaseGaps.size();
        if (congested) { blockPhysical = cycle + 96; blockResponse = cycle + 144; }
        unsigned rawCount = 0, preCount = 0;
        for (unsigned n = 0; n < count; ++n) {
            // Mixed starts with a certified owner: control's older FIFO makes
            // later raw hits staged, with II=1, rather than spuriously demanding
            // empty-path raw latency from a nonempty translated queue.
            const bool pre = kind == 1 || (kind == 2 && n % 2 == 0);
            if (pre) { send(certified(ram + (n % 64) * 8)); ++preCount; }
            else { send(raw(va + (n % 64) * 8, n % 3 != 1)); ++rawCount; }
        }
        drain();
        check(accepted - a == count && returned - r == count && physical - ph == count &&
            hits - h == rawCount && walks == w && translationFires - tf == rawCount,
            "matched stream did not exercise exact real DTLB hit/certified owner counts");
        const auto acceptanceSpan = acceptCycles.back() - acceptCycles.at(a) + 1;
        const auto physicalSpan = physicalCycles.back() - physicalCycles.at(ph) + 1;
        const unsigned expectedLatency = kind == 0 || COMBINED_CHECKED_FLOW ? 2 : 3;
        if (!congested) {
            check(acceptanceSpan == count && physicalSpan == count, "continuous stream lost II=1");
            for (unsigned i = ph; i < physical; ++i)
                check(physicalLatencies.at(i) == expectedLatency, "empty/unblocked registered path latency mismatch");
            check(precheckedPasses - pp == (COMBINED_CHECKED_FLOW ? preCount : 0), "certified stream direct-pass mismatch");
        } else {
            check(fullReleaseEvents > fr && releaseGaps.size() > gi && releaseGaps.at(gi) == 1,
                "full FIFO release must expose one no-borrow edge then resume next cycle");
        }
        std::cout << "COMBINED_CHECKED_FLOW_METRIC scenario=" << name << " count=" << count
            << " raw=" << rawCount << " prechecked=" << preCount << " cycles=" << cycle - start
            << " acceptance_span=" << acceptanceSpan << " physical_span=" << physicalSpan
            << " first_physical_latency=" << physicalLatencies.at(ph)
            << " first_return_latency=" << returnCycles.at(r) - acceptCycles.at(a)
            << " demand_hits=" << hits - h << " hit_pass=" << hitPasses - hp
            << " prechecked_pass=" << precheckedPasses - pp << " translated_push=" << translatedPushes - tp
            << " translated_pop=" << translatedPops - tq << " full_release_events=" << fullReleaseEvents - fr
            << " first_release_resume_gap=" << (releaseGaps.size() > gi ? releaseGaps.at(gi) : 0) << '\n';
    }
    void report(const std::string &name) const {
        std::cout << "COMBINED_CHECKED_FLOW_CASE name=" << name << " accepted=" << accepted << " returned=" << returned
            << " physical=" << physical << " certificates=" << certificates << " faults=" << faults
            << " incoming=" << incomingFires << " checked_push=" << checkedPushes
            << " translated_push=" << translatedPushes << " translated_pop=" << translatedPops
            << " owner_push=" << ownerPushes << " owner_pop=" << ownerPops
            << " trace=" << trace << " walks=" << walks << " hits=" << hits
            << " hit_pass=" << hitPasses << " prechecked_pass=" << precheckedPasses
            << " hit_spills=" << hitSpills << " prechecked_spills=" << precheckedSpills
            << " older_pop_new_spill=" << olderPopNewSpill << " accepted_miss_waiting=" << acceptedMissWaiting
            << " held_physical=" << heldPhysical << " held_responses=" << heldResponses
            << " checked_full=" << checkedFull << " translated_full=" << translatedFull << " owners_full=" << ownersFull
            << " full_release_events=" << fullReleaseEvents << '\n';
    }
};

int main(int argc, char **argv) { try {
    const std::string mode = argc > 1 ? argv[1] : "";
    require(argc <= 2 && (mode.empty() || mode == "--inject-pa" || mode == "--inject-data" ||
        mode == "--inject-fault" || mode == "--inject-canonical" || mode == "--force-undrained-flush"), "unknown option");
    {
        Bench b(mode); b.run(b.raw()); // Cold real Sv39 write walk also warms read/write reuse.
        b.measure("raw_single", 1, 0); b.measure("prechecked_single", 1, 1);
        b.measure("raw_stream", 128, 0); b.measure("prechecked_stream", 128, 1);
        b.measure("alternating_stream", 128, 2);
        b.measure("congested_raw", 128, 0, true); b.measure("congested_alternating", 128, 2, true);
        b.check(b.hitSpills && b.olderPopNewSpill && b.acceptedMissWaiting && b.checkedFull && b.translatedFull &&
            b.ownersFull && b.heldPhysical && b.heldResponses && b.heldUpstream,
            "raw miss/spill/older FIFO/full queue/held payload witnesses missing");
        b.check(!COMBINED_CHECKED_FLOW || b.precheckedSpills, "checked-full certified spill witness missing");
        b.report("matched_supply_and_congestion");
    }
    {
        Bench b(mode); b.periodic = true; b.pteLatency = 7; b.latency = 5;
        b.blockPhysical = b.cycle + 90; b.blockResponse = b.cycle + 150;
        for (unsigned n = 0; n < 64; ++n) {
            auto r = n % 2 ? b.certified(ram + (n % 16) * 8) : b.raw(va + (n % 16) * 8, n % 4 == 0);
            if (n % 11 == 3) --r.translationEpoch;
            if (n == 12 || n == 36) r.descriptor.virtualAddress = va + 9 * 4096;
            if (n == 16 || n == 40) r.descriptor.virtualAddress = va + 4096; // New real walk among held older work.
            if (n == 22) { r.descriptor.virtualAddress = va + 4 * 4096; r.write = false; r.origin = false; }
            if (n == 24) { r.uncached = true; r.origin = false; }
            if (n == 26) { r.atomic = true; r.atomicOp = 2; r.write = false; r.origin = false; }
            if (n == 28) { r.origin = false; r.lateError = true; }
            b.send(r);
        }
        b.drain();
        b.check(b.faults && b.lateErrors && b.walks >= 3 && b.certificates && b.acceptedMissWaiting &&
            b.heldPhysical && b.heldResponses && b.olderPopNewSpill, "mixed fault/data/walk/order coverage missing");
        b.report("mixed_fault_data_walk_order");
    }
    {
        Bench b(mode);
        for (unsigned kind = 0; kind < 9; ++kind) {
            auto r = b.certified();
            if (kind == 0) --r.translationEpoch;
            if (kind == 1) r.descriptor.virtualAddress = 0x10000000ULL;
            if (kind == 2) r.descriptor.virtualAddress = ram + ramBytes;
            if (kind == 3) r.write = true;
            if (kind == 4) { r.atomic = true; r.atomicOp = 2; }
            if (kind == 5) r.virt = true;
            if (kind == 6) r.uncached = true;
            if (kind == 7) r.descriptor.virtualAddress = ram + ramBytes - 4;
            if (kind == 8) r.descriptor.virtualAddress = ram | (1ULL << 48);
            b.run(r);
        }
        b.check(b.physical == 0 && b.certificates == 0 && b.faults == 9, "forged certificate escaped refusal");
        b.report("invalid_certified_loads");
    }
    {
        Bench b;
        for (unsigned size = 0; size < 4; ++size)
            for (unsigned offset = 0; offset < 8; offset += (1u << size)) b.run(b.certified(ram + offset, size));
        auto r = b.certified(ram + 1); b.run(r);
        r = b.certified(ram + 24); r.descriptor.mask = 0x7f; b.run(r);
        b.check(b.faults == (COMBINED_CHECKED_FLOW ? 2u : 0u), "documented control/candidate shape policy mismatch");
        b.report("shape_hardening");
    }
    {
        Bench b;
        // Raw MMIO/PBMT/atomic/uncached requests retain their architectural
        // behavior but may neither claim a canonical store nor a prefetch hint.
        for (unsigned pbmt : {1u, 2u, 3u}) {
            b.tables.pages[0] = {ram, 0xc7, pbmt}; b.maintenance();
            const auto cp = b.certificates, hp = b.hitPasses;
            b.run(b.raw()); b.run(b.raw(va + 8));
            b.check(b.certificates == cp && b.hitPasses == hp, "PBMT raw request gained direct/canonical authority");
        }
        b.tables.pages[0] = {ram, 0xc7}; b.maintenance();
        b.run(b.raw(va + 3 * 4096));
        for (unsigned op : {2u, 3u, 0u}) {
            auto r = b.raw(va, op != 2); r.atomic = true; r.atomicOp = op; r.origin = false;
            const auto cp = b.certificates, hp = b.hitPasses; b.run(r);
            r.descriptor.virtualAddress = va + 3 * 4096; b.run(r);
            b.check(b.certificates == cp && b.hitPasses == hp, "atomic gained direct/canonical authority");
        }
        auto uncached = b.raw(); uncached.uncached = true; uncached.origin = false;
        const auto cp = b.certificates, hp = b.hitPasses; b.run(uncached);
        b.check(b.certificates == cp && b.hitPasses == hp, "uncached raw store gained direct/canonical authority");
        b.report("pbmt_mmio_atomic_uncached");
    }
    {
        Bench b;
        b.run(b.raw()); // Real warm write translation, retained across final PMP change.
        const auto h = b.hits, w = b.walks, ph = b.physical, cp = b.certificates;
        b.cfg = 0x19; b.maintenance(false); b.run(b.raw());
        b.check(b.hits == h + 1 && b.walks == w && b.physical == ph && b.certificates == cp,
            "warm real TLB hit escaped final WRITE PMP denial");
        b.cfg = 0x1f; b.maintenance(false);
        b.run(b.certified(ram + 32)); b.run(b.certified(ram + 4032));
        b.pmpAddress = ram >> 2; b.maintenance(false); // Exactly 8 bytes: current load allowed, next line denied.
        b.run(b.certified());
        auto crossing = b.certified(ram + 4); b.run(crossing); // Whole-access PMP rejection, even in old shape policy.
        b.pmpAddress = virtual_load_test::allPmp; b.maintenance(false);
        b.run(b.certified(ram + ramBytes - 8));
        b.report("final_pmp_and_next_line");
    }
    {
        Bench b;
        for (unsigned change = 0; change < 8; ++change) {
            auto stale = b.certified();
            if (change == 1) b.context ^= 1ULL << 44;
            if (change == 2) b.context ^= 1ULL;
            if (change == 3) b.sum = !b.sum;
            if (change == 4) b.mxr = !b.mxr;
            if (change == 5) b.privilege = 0;
            if (change == 6) b.cfg = 0x18;
            if (change == 7) b.pmpAddress ^= 8;
            b.maintenance(change == 0);
            b.run(stale); b.run(b.certified(ram + 32));
        }
        b.privilege = 3; b.maintenance(false); b.run(b.certified());
        b.privilege = 1; b.context = 0; b.maintenance(false); b.run(b.certified());
        b.report("drained_flush_context_epoch");
    }
    {
        Bench b;
        for (unsigned flags : {0x43u, 0x47u, 0x87u, 0xc5u, 0xc3u}) {
            b.tables.pages[0] = {ram, flags}; b.maintenance(); b.run(b.raw());
        }
        b.tables.pages[0] = {ram + 4096, 0xc7}; b.maintenance(); b.run(b.raw());
        auto staleOrigin = b.raw(); --staleOrigin.descriptor.epoch; b.run(staleOrigin);
        auto absent = b.raw(); absent.origin = false; b.run(absent);
        auto wrongMask = b.raw(); wrongMask.descriptor.mask = 15; b.run(wrongMask);
        b.run(b.raw(va + 1));
        b.run(b.certified(ram + 24576)); // Trusted same-epoch PA, not a covert retranslation.
        b.report("pte_rights_canonical_shape_remap");
    }
    if (mode == "--force-undrained-flush") {
        Bench b; b.blockPhysical = b.cycle + 100; b.send(b.certified());
        for (unsigned n = 0; n < 10; ++n) b.tick();
        std::cout << "INJECT COMBINED_CHECKED_FLOW undrained flush\n" << std::flush;
        b.flush = true; b.tick();
        throw std::runtime_error("undrained flush assertion did not fire");
    }
    std::cout << "COMBINED_CHECKED_FLOW_PASS enabled=" << COMBINED_CHECKED_FLOW << '\n'; return 0;
} catch (const std::exception &e) {
    std::cerr << "COMBINED_CHECKED_FLOW_FAIL " << e.what() << '\n'; return 1;
} }
