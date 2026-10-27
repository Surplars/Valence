#include "CoexistingPhysicalIngressDtaGsim.h"
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

#ifndef COEXISTING_PHYSICAL_LOAD_INGRESS
#define COEXISTING_PHYSICAL_LOAD_INGRESS 0
#endif
#ifndef REGISTERED_RAW_CERTIFIED_FLOW
#define REGISTERED_RAW_CERTIFIED_FLOW 0
#endif
#ifndef GUARDED_NATURAL_DTA
#define GUARDED_NATURAL_DTA 1
#endif
#ifndef CERTIFIED_LOAD_INGRESS
#define CERTIFIED_LOAD_INGRESS 1
#endif
using namespace canonical_store_test;

// Independent architectural oracle: software PTEs, byte ranges, R/W/X/U/A/D,
// PMP and expected ordered memory replies. Passive DUT events establish where
// an owner moved, never whether its address, rights or canonical proof is valid.
struct Request {
    Descriptor descriptor;
    bool origin = false, write = true, atomic = false, virt = true;
    bool prechecked = false, uncached = false, lateError = false, walkAccessFault = false;
    unsigned atomicOp = 0;
    uint32_t translationEpoch = 0;
    uint64_t data = 0;
};
struct Entry {
    Request request;
    uint64_t id = 0, acceptedCycle = 0, physical = 0;
    bool pageFault = false, accessFault = false, uncached = false, certify = false, prefetch = false, bare = false;
    bool routed = false, checked = false, physicalSeen = false, certificateSeen = false;
    bool fault() const { return pageFault || accessFault; }
};
struct Reply { uint64_t due, data; bool error = false; };
using Payload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, unsigned,
    bool, bool, bool, uint64_t, bool>;
using Response = std::tuple<uint64_t, bool, bool>;

class Bench {
    SCoexistingPhysicalIngressDtaGsim d;
    std::deque<Reply> ptes, replies;
    std::map<uint64_t, Entry> records;
    std::deque<uint64_t> ordered, ingress, translated, checked, owners;
    std::optional<uint64_t> waiting, pendingFullRelease;
    std::optional<Payload> held;
    std::optional<Response> heldResponse;
    bool injected = false;
    using Authorization = std::tuple<uint64_t,unsigned,bool,bool,unsigned,uint64_t,unsigned,uint64_t,unsigned,uint64_t>;
    std::optional<Authorization> previousAuthorization;
    unsigned quietEdges = 0;
public:
    bool waitingForTranslation() const { return waiting.has_value(); }
    virtual_load_test::PageTables tables;
    uint64_t cycle = 0, blockPhysical = 0, blockResponse = 0, context = virtual_load_test::satp;
    uint64_t pmpAddress = virtual_load_test::allPmp;
    uint32_t epoch = 1;
    unsigned cfg1 = 0, cfg2 = 0; uint64_t pmpAddress1 = 0, pmpAddress2 = 0;
    unsigned physicalDirect = 0, certifiedDirect = 0, eligibleSpills = 0;
    unsigned ingressFullNoBorrow = 0, ordinaryOlderIngress = 0, ordinaryOlderTranslated = 0, ordinaryWaiting = 0;
    bool superpage = false; unsigned ingressDirect = 0, nominalReject = 0, fullCheckedDequeue = 0;
    unsigned cfg = 0x1f, privilege = 1, latency = 1, pteLatency = 2;
    bool sum = false, mxr = false, flush = false, periodic = false, pteMemoryError = false;
    unsigned accepted = 0, returned = 0, physical = 0, certificates = 0, faults = 0;
    unsigned incomingFires = 0, translationFires = 0, translatedPushes = 0, translatedPops = 0, checkedPushes = 0;
    unsigned hitPasses = 0, precheckedPasses = 0, identityPasses = 0, hitSpills = 0, precheckedSpills = 0;
    unsigned ownerPushes = 0, ownerPops = 0, walks = 0, hits = 0, pteReads = 0;
    unsigned heldPhysical = 0, heldResponses = 0, heldUpstream = 0;
    unsigned checkedFull = 0, translatedFull = 0, ownersFull = 0, fullReleaseEvents = 0;
    unsigned olderPopNewSpill = 0, acceptedMissWaiting = 0, lateErrors = 0, rawReplySpills = 0;
    unsigned identityHintAllowed = 0, identityHintDenied = 0, bareHintAllowed = 0, bareHintDenied = 0;
    uint64_t trace = 1469598103934665603ULL;
    std::vector<uint64_t> acceptCycles, physicalCycles, returnCycles, physicalLatencies, releaseGaps;
    std::vector<std::string> physicalKinds;
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
        // Architectural first-overlapping-entry rule, independently decoded
        // with widened arithmetic. Partial matches deny, even unlocked M-mode.
        const unsigned configs[3] = {cfg, cfg1, cfg2};
        const uint64_t addresses[3] = {pmpAddress, pmpAddress1, pmpAddress2};
        using Wide = unsigned __int128;
        const Wide start = address, end = start + bytes;
        for (unsigned i = 0; i < 3; ++i) {
            const unsigned c = configs[i], mode = (c >> 3) & 3;
            if (!mode) continue;
            Wide lo = 0, hi = 0;
            if (mode == 1) { lo = i ? Wide(addresses[i-1]) * 4 : 0; hi = Wide(addresses[i]) * 4; }
            else if (mode == 2) { lo = Wide(addresses[i]) * 4; hi = lo + 4; }
            else {
                unsigned n = 0; while (n < 54 && ((addresses[i] >> n) & 1)) ++n;
                const Wide mask = (Wide(1) << n) - 1;
                lo = (Wide(addresses[i]) & ~mask) * 4; hi = lo + (Wide(1) << (n + 3));
            }
            if (lo >= hi || start >= hi || end <= lo) continue;
            if (start < lo || end > hi) return false;
            if (privilege == 3 && !(c & 0x80)) return true;
            return (!read || (c & 1)) && (!write || (c & 2));
        }
        return privilege == 3;
    }

    Entry truth(const Request &r) const {
        Entry e; e.request = r; const auto &a = r.descriptor;
        const bool needsRead = r.atomic ? r.atomicOp != 3 : !r.write;
        const bool needsWrite = r.atomic ? r.atomicOp != 2 : r.write;
        e.physical = a.virtualAddress; e.uncached = r.uncached;
        e.bare = r.virt && !r.prechecked && (privilege == 3 || !(context >> 60));
        if (r.prechecked) {
            e.accessFault = r.virt || r.write || r.atomic || r.uncached || privilege == 3 || !(context >> 60) ||
                r.translationEpoch != epoch || flush || !previousAuthorization ||
                *previousAuthorization != authorization() || !wholeRam(e.physical, a.size) ||
                (!aligned(e.physical, a.size) || a.mask != lanes(e.physical, a.size));
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
        if (r.walkAccessFault) { e.pageFault = false; e.accessFault = true; }
        if (!e.pageFault && (r.virt || r.prechecked))
            e.accessFault |= !pmpAllows(e.physical, uint64_t(1) << a.size, needsRead, needsWrite) ||
                (r.atomic && !wholeRam(e.physical, a.size));
        // Independent arithmetic divisibility, not the DUT low-bit mask.
        if (GUARDED_NATURAL_DTA && e.physical % (uint64_t(1) << a.size) != 0)
            e.accessFault = true;
        auto actualShape = a; actualShape.physicalAddress = e.physical;
        e.certify = !e.fault() && r.origin && r.virt && r.write && !r.atomic && !r.prechecked &&
            !e.uncached && a.epoch == epoch && shape(actualShape);
        const uint64_t next = (e.physical & ~63ULL) + 64;
        e.prefetch = !e.fault() && !r.write && !r.atomic && !e.uncached && wholeRam(e.physical, a.size) &&
            (e.physical & 4095) < 4032 && next >= ram && next + 64 <= ram + ramBytes &&
            pmpAllows(next, 64, true, false);
        return e;
    }
    Authorization authorization() const { return {context, privilege, sum, mxr, cfg, pmpAddress,
        cfg1,pmpAddress1,cfg2,pmpAddress2}; }
    // A synthetic memory response includes accepted ordinal as well as address,
    // so equal-address reads cannot hide dropped/reordered owners. This is a
    // transport fixture, not a CPU memory image or an architectural read model.
    uint64_t replyData(const Entry &e) const {
        return beatData(e.physical) ^ (0x9e3779b97f4a7c15ULL * (e.id + 1));
    }
    bool ordinary(const Request &r) const {
        const auto &a=r.descriptor;
        return !r.virt && !r.prechecked && !r.write && !r.atomic && !r.uncached && !r.origin &&
            aligned(a.virtualAddress,a.size) && a.mask == lanes(a.virtualAddress,a.size) &&
            wholeRam(a.virtualAddress,a.size);
    }
    bool physicalReady() const { return cycle >= blockPhysical && (!periodic || cycle % 7 != 5); }
    bool pteReady() const { return !periodic || cycle % 5 != 3; }
    void drive(std::optional<Request> request) {
        Request idle; idle.descriptor.virtualAddress = ram + 1; idle.descriptor.size = 3;
        const auto r = request.value_or(idle); const auto &a = r.descriptor;
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
        d.set_io$$pte$$response$$bits$$data(pte ? ptes.front().data : 0); d.set_io$$pte$$response$$bits$$error(pte && ptes.front().error);
        d.set_io$$context$$satp(context); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(pmpAddress);
        d.set_io$$pmpCfg1(cfg1); d.set_io$$pmpAddress1(pmpAddress1);
        d.set_io$$pmpCfg2(cfg2); d.set_io$$pmpAddress2(pmpAddress2); d.set_io$$flush(flush);
    }
    bool tick(std::optional<Request> request = {}) {
        const bool response = !replies.empty() && replies.front().due <= cycle;
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        drive(request); d.step();
        const bool take = request && d.get_io$$upstream$$request$$ready();
        // All expectations use pre-edge ledger occupancy, before acceptance.
        check(d.get_io$$ingressCount() == ingress.size(), "ingress exact owner count mismatch");
        const bool nominal = CERTIFIED_LOAD_INGRESS && request && ingress.empty() && translated.empty() && !waiting &&
            request->prechecked && !request->virt && !request->write && !request->atomic && !request->uncached && !request->origin;
        const auto oldIngressSize = ingress.size();
        const bool contextChanged = !previousAuthorization || *previousAuthorization != authorization();
        const bool stable = quietEdges >= 1 && !flush && !contextChanged;
        const bool qualified = (context >> 60) == 8 && (privilege == 0 || privilege == 1) && stable;
        const bool certifiedPass = nominal && qualified && !truth(*request).fault() && checked.size() < 2;
        check(!d.get_io$$incomingFire() || oldIngressSize != 0,
            "incoming consumed a new same-edge owner through forbidden flow");
        const bool physicalContext = (privilege == 0 || privilege == 1 || privilege == 3) &&
            (privilege == 3 || (context >> 60) == 0);
        const bool physicalOffer = COEXISTING_PHYSICAL_LOAD_INGRESS && request && ordinary(*request) &&
            ingress.empty() && translated.empty() && !waiting && stable && physicalContext;
        const bool physicalPass = physicalOffer && checked.size() < 2;
        const bool direct = certifiedPass || physicalPass;
        const bool poisonRoute = mutate("--inject-route", "INJECT COEXISTING_INGRESS observed route", take);
        check(bool(d.get_io$$certifiedIngressNominal()) == nominal, "independent nominal source mismatch");
        check(bool(d.get_io$$certifiedIngressPass()) == certifiedPass, "independent certified ingress grant mismatch");
        check(bool(d.get_io$$physicalIngressOffer()) == physicalOffer, "independent ordinary physical offer mismatch");
        check((bool(d.get_io$$physicalIngressPass()) ^ poisonRoute) == physicalPass,
            "independent ordinary physical pass mismatch");
        check(bool(d.get_io$$ingressReady()) == (ingress.size() < 2) &&
            bool(d.get_io$$upstream$$request$$ready()) == (ingress.size() < 2),
            "upstream credit differs from old incoming occupancy");
        check(bool(d.get_io$$ingressPush()) == (take && !direct), "three-route acceptance conservation mismatch");
        check(unsigned(certifiedPass) + unsigned(physicalPass) + unsigned(d.get_io$$ingressPush()) == unsigned(take),
            "accepted request did not choose exactly one destination");
        ingressFullNoBorrow += ingress.size()==2 && d.get_io$$incomingFire() && request.has_value();
        if (request && ordinary(*request)) {
            eligibleSpills += take && physicalOffer && checked.size()==2;
            ordinaryOlderIngress += take && !ingress.empty();
            ordinaryOlderTranslated += take && !translated.empty();
            ordinaryWaiting += take && waiting.has_value();
        }
        physicalDirect += physicalPass; certifiedDirect += certifiedPass;
        if (checked.size()==2) check(!d.get_io$$checkedPush(), "full checked queue borrowed same-cycle pop credit");
        check(!direct || take, "direct capture without upstream acceptance");
        const std::optional<uint64_t> directId = direct ? std::optional<uint64_t>{accepted} : std::nullopt;
        nominalReject += nominal && !direct;
        if (take) {
            auto e = truth(*request); e.id = accepted; e.acceptedCycle = cycle;
            e.routed = direct;
            records.emplace(e.id, e); ordered.push_back(e.id);
            if (!direct) ingress.push_back(e.id); else ++ingressDirect;
            acceptCycles.push_back(cycle); ++accepted;
        }
        heldUpstream += request && !take;
        if (response && d.get_io$$physical$$response$$ready()) replies.pop_front();
        if (pte && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && pteReady()) {
            ptes.push_back({cycle + pteLatency, (superpage && d.get_io$$pte$$request$$bits() == virtual_load_test::root + 4096 ?
                ((ram >> 12) << 10) | 0xc7ULL : tables.pte(d.get_io$$pte$$request$$bits())), pteMemoryError}); ++pteReads;
        }
        // Queue counts are checked before applying this edge's independent events.
        check(d.get_io$$translatedCount() == translated.size() && d.get_io$$checkedCount() == checked.size() &&
            d.get_io$$ownerCount() == owners.size(), "passive queue counts disagree with exact owner ledger");
        const bool hp = d.get_io$$hitPass(), pp = d.get_io$$precheckedPass(), ip = d.get_io$$identityPass();
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
        check(unsigned(hp) + unsigned(pp) + unsigned(ip) <= 1,
            "raw hit, certified and identity direct paths claimed one result twice");
        if (REGISTERED_RAW_CERTIFIED_FLOW) {
            check(!hp && !d.get_io$$hitOffer(), "registered raw result escaped its mandatory result register");
            if (tr) { check(tp, "raw translation reply failed to enter registered result FIFO"); ++rawReplySpills; }
        }
        if (resultId) {
            auto &e = records.at(*resultId);
            check(!e.routed && (unsigned(tp) + unsigned(hp) + unsigned(pp) + unsigned(ip) == 1),
                "exact raw result must enter translated XOR direct checked once");
            e.routed = true;
            check(!hp || (e.request.virt && !e.request.prechecked && !e.request.atomic && !e.uncached && !e.pageFault),
                "raw translation hit bypass accepted a forbidden request kind");
            check(!pp || e.request.prechecked, "prechecked direct owner mismatch");
            check(!ip || (!e.request.virt && !e.request.prechecked), "identity direct owner mismatch");
            if (tp) {
                check(d.get_io$$translatedData() == e.request.data, "translated spill payload/owner mismatch");
                if (!e.pageFault && !e.request.walkAccessFault)
                    check(d.get_io$$translatedAddress() == e.physical, "translated spill PA mismatch");
            }
        } else check(!tp && !hp && !pp && !ip, "result appeared without current or saved raw owner");
        // Older FIFO -> checked and new raw -> FIFO are LEGAL on one edge.
        // Their identities must not be conflated into global push exclusivity.
        if (tq) {
            check(!translated.empty(), "translated FIFO popped without an older owner");
            checkedId = translated.front(); translated.pop_front();
        }
        if (hp || pp || ip) {
            check(!checkedId && resultId, "direct source overtook an older translated owner"); checkedId = resultId;
        }
        if (directId) {
            check(!checkedId && !resultId && !tp && !tf && !tr && !tq,
                "certified ingress overtook or duplicated older result");
            checkedId = directId;
        }
        fullCheckedDequeue += checked.size() == 2 && cq;
        check(cp == checkedId.has_value(), "checked admission lacked exactly one source owner");
        olderPopNewSpill += tq && tp;
        if (cp) {
            auto &e = records.at(*checkedId);
            check(!e.checked && d.get_io$$checkedData() == e.request.data, "checked payload/owner duplicated or changed");
            if (!e.pageFault && !e.request.walkAccessFault)
                check(d.get_io$$checkedAddress() == e.physical, "checked physical address mismatch");
            check(bool(d.get_io$$checkedFault()) == e.fault() && bool(d.get_io$$checkedPageFault()) == e.pageFault,
                "checked authorization disagrees with independent permissions");
            const bool poisonHint = mutate("--inject-hint", "INJECT GUARDED_NATURAL_DTA checked hint");
            check((bool(d.get_checkedHint()) ^ poisonHint) == e.prefetch,
                "independent captured next-line permission mismatch");
            e.checked = true;
        }
        if (d.get_io$$certificate$$valid()) {
            check(checkedId.has_value() && cp, "canonical event without same-edge checked owner");
            if (REGISTERED_RAW_CERTIFIED_FLOW)
                check(tq && !hp && !pp && !ip, "registered canonical event lacks real raw-store FIFO dequeue");
            auto &e = records.at(*checkedId); const auto &a = e.request.descriptor;
            const bool poison = mutate("--inject-canonical", "INJECT REGISTERED_RAW_CERTIFIED_FLOW canonical attribution");
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
                const bool poison = mutate("--inject-pa", "INJECT COEXISTING_INGRESS physical PA");
                const bool poisonOwner = mutate("--inject-owner", "INJECT COEXISTING_INGRESS observed owner payload");
                check(!e.fault() && !e.physicalSeen && (std::get<0>(payload) ^ (poison ? 8ULL : 0ULL)) == e.physical,
                    "independent physical PA/order mismatch");
                check((std::get<1>(payload) ^ (poisonOwner ? 1ULL : 0ULL)) == r.data && std::get<2>(payload) == r.descriptor.size &&
                    std::get<3>(payload) == r.descriptor.mask && std::get<4>(payload) == r.write &&
                    std::get<5>(payload) == r.atomic && std::get<6>(payload) == r.atomicOp &&
                    std::get<7>(payload) == e.uncached && !std::get<8>(payload) && !std::get<9>(payload) &&
                    std::get<10>(payload) == 0, "independent physical shape/private-metadata mismatch");
                check(std::get<11>(payload) == e.prefetch, "independent next-line READ PMP/page/range mismatch");
                if (!r.write && !r.atomic && !r.prechecked) {
                    if (!r.virt) { if (e.prefetch) ++identityHintAllowed; else ++identityHintDenied; }
                    if (e.bare) { if (e.prefetch) ++bareHintAllowed; else ++bareHintDenied; }
                }
                check(e.certificateSeen == e.certify, "physical owner missing canonical attribution");
                e.physicalSeen = true; ++physical;
                physicalCycles.push_back(cycle); physicalLatencies.push_back(cycle - e.acceptedCycle);
                physicalKinds.push_back(r.prechecked ? "prechecked" : (r.write ? "raw_store" : "raw_load"));
                replies.push_back({cycle + latency, r.write ? 0 : replyData(e), r.lateError});
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
                const bool poisonFault = mutate("--inject-fault", "INJECT REGISTERED_RAW_CERTIFIED_FLOW response fault", fault);
                check((std::get<1>(payload) ^ poisonFault) == fault && std::get<2>(payload) == e.pageFault,
                    "independent ordered fault classification mismatch");
                const uint64_t data = e.fault() || e.request.write ? 0 : replyData(e);
                const bool poisonData = mutate("--inject-data", "INJECT REGISTERED_RAW_CERTIFIED_FLOW response data", !e.request.write);
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
        ownerPushes += op; ownerPops += oq; hitPasses += hp; precheckedPasses += pp; identityPasses += ip;
        translationFires += tf;
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit();
        quietEdges = contextChanged || flush ? 0 : std::min(quietEdges + 1, 2u);
        previousAuthorization = authorization();
        ++cycle; return take;
    }
    void settle() { for (unsigned n = 0; n < 5; ++n) tick(); }
    Request raw(uint64_t address = va, bool write = true, unsigned size = 3) const {
        Request r; r.descriptor.virtualAddress = address; r.descriptor.size = size;
        r.descriptor.mask = lanes(address, size); r.descriptor.epoch = epoch;
        r.descriptor.token = Token{unsigned(accepted % 16), 0xfedcba9876543210ULL ^ (uint64_t(accepted) * 0x100010001ULL)};
        r.data = 0x8877665544332211ULL ^ (uint64_t(accepted) * 0x0102040810204081ULL);
        r.write = write; r.origin = write; return r;
    }
    Request certified(uint64_t address = ram, unsigned size = 3) const {
        auto r = raw(address, false, size); r.prechecked = true; r.virt = false; r.translationEpoch = epoch;
        // A certified load has no store-origin sideband; it must still never emit a store certificate.
        return r;
    }
    Request physicalRead(uint64_t address = ram, unsigned size = 3) const {
        auto r=raw(address,false,size); r.virt=false; return r;
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
        check(accepted == returned && accepted == incomingFires + ingressDirect && accepted == checkedPushes &&
            accepted == ownerPushes && accepted == ownerPops && translatedPushes == translatedPops &&
            accepted == translatedPushes + hitPasses + precheckedPasses + identityPasses + ingressDirect,
            "exact raw request -> checked XOR translated -> owner conservation failed");
        pendingFullRelease.reset();
    }
    void run(const Request &r) { send(r); drain(); }
    void maintenance(bool translationFlush = true) {
        check(ordered.empty() && d.get_io$$idle(), "driver attempted illegal undrained maintenance");
        flush = translationFlush; tick(); flush = false; ++epoch; settle();
        check(d.get_io$$epoch() == epoch && d.get_io$$stable(), "drained authorization epoch mismatch");
    }
    void report(const std::string &name) const {
        std::cout << "REGISTERED_RAW_CERTIFIED_FLOW_CASE name=" << name << " accepted=" << accepted << " returned=" << returned
            << " physical=" << physical << " certificates=" << certificates << " faults=" << faults
            << " physical_direct=" << physicalDirect << " certified_direct=" << certifiedDirect
            << " eligible_spills=" << eligibleSpills << " ingress_full_no_borrow=" << ingressFullNoBorrow
            << " ordinary_older_ingress=" << ordinaryOlderIngress << " ordinary_older_translated=" << ordinaryOlderTranslated
            << " ordinary_waiting=" << ordinaryWaiting << " ingress_direct=" << ingressDirect << " nominal_reject=" << nominalReject
            << " full_checked_dequeue=" << fullCheckedDequeue << " incoming=" << incomingFires << " checked_push=" << checkedPushes
            << " translated_push=" << translatedPushes << " translated_pop=" << translatedPops
            << " owner_push=" << ownerPushes << " owner_pop=" << ownerPops
            << " trace=" << trace << " walks=" << walks << " hits=" << hits
            << " hit_pass=" << hitPasses << " prechecked_pass=" << precheckedPasses << " identity_pass=" << identityPasses
            << " hit_spills=" << hitSpills << " prechecked_spills=" << precheckedSpills
            << " older_pop_new_spill=" << olderPopNewSpill << " accepted_miss_waiting=" << acceptedMissWaiting
            << " held_physical=" << heldPhysical << " held_responses=" << heldResponses
            << " checked_full=" << checkedFull << " translated_full=" << translatedFull << " owners_full=" << ownersFull
            << " full_release_events=" << fullReleaseEvents << " raw_reply_spills=" << rawReplySpills
            << " identity_hint_allowed=" << identityHintAllowed << " identity_hint_denied=" << identityHintDenied
            << " bare_hint_allowed=" << bareHintAllowed << " bare_hint_denied=" << bareHintDenied << '\n';
    }
};

int main(int argc, char **argv) { try {
    const std::string mode = argc > 1 ? argv[1] : "";
    require(argc <= 2 && (mode.empty() || mode == "--inject-pa" || mode == "--inject-data" ||
        mode == "--inject-fault" || mode == "--inject-canonical" || mode == "--inject-hint" ||
        mode == "--inject-route" || mode == "--inject-owner" ||
        mode == "--force-undrained-flush" || mode == "--force-invalid-sidecar"), "unknown option");
    {
        Bench b(mode); b.privilege=3; b.context=0; b.maintenance();
        for (unsigned size=0;size<4;++size)
            for(unsigned offset=0;offset<8;offset+=(1u<<size)) {
                const auto ph=b.physical;
                b.run(b.physicalRead(ram+offset,size));
                b.check(b.physicalLatencies.at(ph)==(COEXISTING_PHYSICAL_LOAD_INGRESS?1u:2u),
                    "empty physical first acceptance crossed wrong register count");
            }
        for(unsigned size=0;size<4;++size) {
            b.run(b.physicalRead(ram,size));
            b.run(b.physicalRead(ram+ramBytes-(1u<<size),size));
        }
        // Identical architectural address, distinct accepted ordinals and request
        // data. Synthetic reply data also identifies each accepted transaction.
        for(unsigned i=0;i<16;++i) b.run(b.physicalRead(ram+128));
        b.check(b.accepted==39 && b.physical==39 && !b.faults &&
            b.physicalDirect==(COEXISTING_PHYSICAL_LOAD_INGRESS?39u:0u) && !b.certifiedDirect,
            "ordinary shape/boundary/repeated-address coverage missing");
        b.report("ordinary_empty_shapes_boundaries_same_address");
    }
    for(unsigned privilege : {0u,1u,3u}) {
        Bench b; b.privilege=privilege; b.context=0; b.maintenance();
        b.run(b.physicalRead());
        b.check(b.physical==1 && b.physicalDirect==(COEXISTING_PHYSICAL_LOAD_INGRESS?1u:0u),
            "valid Bare privilege classification lost direct path");
        b.report("bare_privilege_"+std::to_string(privilege));
    }
    {
        Bench b; b.privilege=3; b.context=0; b.maintenance();
        const auto a=b.accepted, ph=b.physical; const auto start=b.cycle;
        for(unsigned n=0;n<64;++n) b.send(b.physicalRead(ram+(n%4)*8));
        b.drain();
        const auto acceptanceSpan=b.acceptCycles.back()-b.acceptCycles.at(a)+1;
        const auto physicalSpan=b.physicalCycles.back()-b.physicalCycles.at(ph)+1;
        b.check(acceptanceSpan==64 && physicalSpan==64 && b.accepted-a==64 && b.physical-ph==64,
            "ordinary continuous supply lost II=1 or request count");
        for(unsigned n=ph;n<b.physical;++n)
            b.check(b.physicalLatencies.at(n)==(COEXISTING_PHYSICAL_LOAD_INGRESS?1u:2u),
                "ordinary continuous fixed ingress latency mismatch");
        std::cout<<"COEXISTING_INGRESS_METRIC name=ordinary_continuous cycles="<<b.cycle-start
            <<" accepted=64 acceptance_span="<<acceptanceSpan<<" physical_span="<<physicalSpan
            <<" first_physical_latency="<<b.physicalLatencies.at(ph)<<'\n';
        b.report("ordinary_continuous");
    }
    {
        Bench b; b.privilege=3; b.context=0; b.maintenance();
        b.blockPhysical=b.cycle+80; b.blockResponse=b.cycle+130;
        b.periodic=true; b.latency=5;
        for(unsigned n=0;n<80;++n) b.send(b.physicalRead(ram+(n%8)*8));
        b.drain();
        b.check(b.accepted==80 && b.returned==80 && b.physical==80 &&
            b.checkedFull && b.fullCheckedDequeue && b.heldPhysical && b.heldResponses &&
            b.heldUpstream && b.ingressFullNoBorrow && b.ordinaryOlderIngress,
            "ordinary congestion/full-credit/held witnesses missing");
        if(COEXISTING_PHYSICAL_LOAD_INGRESS)
            b.check(b.eligibleSpills && b.physicalDirect>=2,"ordinary blocked checked spill witness missing");
        b.report("ordinary_checked_full_single_spill_old_credit");
    }
    {
        Bench b(mode);
        // Existing certified path is enabled in BOTH profiles. Its first edge
        // and all permissions must remain unchanged by the new ordinary route.
        for(unsigned size=0;size<4;++size)
            for(unsigned offset=0;offset<8;offset+=(1u<<size)) {
                auto ph=b.physical; b.run(b.certified(ram+offset,size));
                b.check(b.physicalLatencies.at(ph)==1,"certified ingress latency regressed");
            }
        b.check(b.physical==15 && b.certifiedDirect==15 && !b.physicalDirect,
            "certified selected ordinary route or lost direct path");
        b.report("certified_empty_shapes_unchanged");
    }
    {
        Bench b(mode); b.run(b.raw());
        // Directed witness: create an uncached-in-TLB page miss, then accept
        // an ordinary request while the independent saved-request ledger waits.
        b.pteLatency=7;
        b.send(b.raw(va+8*4096));
        for(unsigned n=0;n<64 && !b.waitingForTranslation();++n) b.tick();
        b.check(b.waitingForTranslation(),"directed ordinary waiting precondition missing");
        const auto beforeWaiting=b.ordinaryWaiting;
        b.send(b.physicalRead(ram));
        b.check(b.ordinaryWaiting==beforeWaiting+1,"ordinary accepted waiting witness missing");
        b.drain();
        b.blockPhysical=b.cycle+90; b.blockResponse=b.cycle+150;
        b.periodic=true; b.latency=5; b.pteLatency=7;
        for(unsigned n=0;n<120;++n) {
            auto r=n%3==0?b.physicalRead(ram+(n%16)*8):
                n%3==1?b.certified(ram+(n%16)*8):b.raw(va+(n%16)*8,n%4==0);
            // Ordinary physicals in an active S VM context are route-negative
            // boundary inputs, not a claim of a valid integrated producer.
            if(n%13==4)--r.translationEpoch;
            if(n==14 || n==38){r=b.raw(va+9*4096,false);}
            if(n==20 || n==44){r=b.raw(va+4096,true);}
            if(n==26){r=b.raw(va+4*4096,false);}
            if(n==32){r=b.raw(va,false);r.uncached=true;}
            if(n==35){r=b.raw(va,false);r.atomic=true;r.atomicOp=2;}
            if(n==47){r=b.raw(va,false);r.lateError=true;}
            b.send(r);
        }
        b.drain();
        b.check(b.faults && b.lateErrors && b.walks>=3 && b.certificates && b.acceptedMissWaiting &&
            b.heldPhysical && b.heldResponses && b.heldUpstream && b.olderPopNewSpill &&
            b.checkedFull && b.translatedFull && b.fullCheckedDequeue && b.ordinaryWaiting &&
            b.ordinaryOlderTranslated && !b.physicalDirect,
            "mixed same-address ordinary/certified/raw ownership or congestion coverage missing");
        b.report("mixed_three_classes_older_waiting_translated");
    }
    {
        Bench b; b.privilege=3; b.context=0; b.maintenance();
        for(unsigned kind=0;kind<11;++kind) {
            auto r=b.physicalRead();
            if(kind==0) r.write=true;
            if(kind==1){r.atomic=true;r.atomicOp=2;}
            if(kind==2) r.uncached=true;
            if(kind==3) r.descriptor.virtualAddress=0x10000000ULL;
            if(kind==4) r.descriptor.virtualAddress=ram+ramBytes;
            if(kind==5) r.descriptor.virtualAddress=ram+ramBytes-4;
            if(kind==6) r.descriptor.virtualAddress=ram|(1ULL<<48);
            if(kind==7) r.descriptor.virtualAddress=~3ULL;
            if(kind==8) r.descriptor.mask=0x7f;
            if(kind==9) r.descriptor.virtualAddress=ram+1;
            if(kind==10) r.virt=true;
            const auto direct=b.physicalDirect; b.run(r);
            b.check(b.physicalDirect==direct,"forbidden ordinary class used new route");
        }
        // Wrong mask / out-of-aperture is a route rejection, not a fictional
        // additional permission fault. The unchanged fallback is independently
        // checked, including exact original payload and existing alignment fault.
        b.check(b.faults==3 && b.accepted==11,"fallback shape fault contract changed");
        b.report("ordinary_rejected_routes_original_fallback");
    }
    {
        Bench b;
        for(unsigned kind=0;kind<12;++kind){
            auto r=b.certified();
            if(kind==0)--r.translationEpoch;
            if(kind==1)r.descriptor.virtualAddress=0x10000000ULL;
            if(kind==2)r.descriptor.virtualAddress=ram+ramBytes;
            if(kind==3)r.write=true;
            if(kind==4){r.atomic=true;r.atomicOp=2;}
            if(kind==5)r.virt=true;
            if(kind==6)r.uncached=true;
            if(kind==7)r.descriptor.virtualAddress=ram+ramBytes-4;
            if(kind==8)r.descriptor.virtualAddress=ram|(1ULL<<48);
            if(kind==9)r.descriptor.virtualAddress=~3ULL;
            if(kind==10)r.descriptor.mask=0x7f;
            if(kind==11)r.descriptor.virtualAddress=ram+1;
            b.run(r);
        }
        b.check(!b.physical && b.faults==12 && !b.physicalDirect && !b.certifiedDirect,
            "forged certified request escaped unchanged fault path");
        b.report("certified_stale_shape_faults_unchanged");
    }
    {
        Bench b;
        b.cfg=0x18;b.pmpAddress=ram>>2;b.cfg1=0x1f;b.pmpAddress1=virtual_load_test::allPmp;b.maintenance(false);
        b.run(b.certified());b.run(b.certified(ram+8));
        b.check(b.faults==1 && b.physical==1,"first overlapping PMP deny lost priority");
        b.cfg=0x11;b.maintenance(false);b.run(b.certified());b.run(b.certified(ram,2));
        b.check(b.faults==2 && b.physical==2,"partial PMP NA4 borrowed later coverage");
        b.cfg=0;b.pmpAddress=ram>>2;b.cfg1=0x09;b.pmpAddress1=(ram+8)>>2;
        b.cfg2=0x18;b.pmpAddress2=virtual_load_test::allPmp;b.maintenance(false);
        b.run(b.certified());b.run(b.certified(ram+8));
        b.check(b.faults==3 && b.physical==3,"TOR OFF predecessor mismatch");
        b.report("certified_pmp_priority_partial_tor");
    }
    {
        Bench b;
        for(unsigned n=0;n<4;++n) {
            b.privilege=3;b.context=0;b.maintenance();
            b.run(b.physicalRead(ram));
            b.privilege=1;b.context=virtual_load_test::satp;b.maintenance();
            b.run(b.certified(ram));
        }
        b.check(b.accepted==8 && b.certifiedDirect==4 &&
            b.physicalDirect==(COEXISTING_PHYSICAL_LOAD_INGRESS?4u:0u),
            "drained Bare/certified same-address context transitions failed");
        b.report("same_address_drained_authorization_transition");
    }
    {
        Bench b; b.privilege=3;b.context=0;b.maintenance();
        // A drained same-edge CSR change suppresses shortcut. The accepted
        // ordinary request must still enter the old queue and drain once.
        const auto pd=b.physicalDirect; b.mxr=!b.mxr; b.send(b.physicalRead()); ++b.epoch; b.drain();
        b.check(b.physicalDirect==pd && b.physical==1 && b.incomingFires==1,
            "same-edge authorization change did not conservatively spill");
        b.flush=true; b.send(b.physicalRead(ram+8));b.flush=false;++b.epoch;b.drain();
        b.check(b.physicalDirect==pd && b.physical==2 && b.incomingFires==2,
            "drained same-edge flush did not preserve exact fallback");
        b.report("same_edge_context_and_flush_route_spill");
    }
    for(bool superpage:{false,true}) {
        Bench b;b.superpage=superpage;b.run(b.raw(va,false));
        const auto ph=b.physical,h=b.hits,w=b.walks;
        b.run(b.raw(va|(1ULL<<39),false));b.run(b.raw(va|(1ULL<<38),false));
        b.check(b.physical==ph && b.faults==2 && b.hits==h && b.walks==w+2,
            "noncanonical VM address gained new physical shortcut");
        b.report(superpage?"noncanonical_superpage":"noncanonical_4k");
    }
    if(mode=="--force-invalid-sidecar") {
        Bench b; b.privilege=3;b.context=0;b.maintenance();auto r=b.physicalRead();r.origin=true;
        std::cout<<"INJECT COEXISTING_INGRESS illegal canonical sidecar\n"<<std::flush;
        b.send(r);throw std::runtime_error("producer sidecar assertion did not fire");
    }
    if(mode=="--force-undrained-flush") {
        Bench b;b.privilege=3;b.context=0;b.maintenance();b.blockPhysical=b.cycle+100;b.send(b.physicalRead());
        for(unsigned i=0;i<10;++i)b.tick();
        std::cout<<"INJECT COEXISTING_INGRESS undrained flush\n"<<std::flush;
        b.flush=true;b.tick();throw std::runtime_error("undrained flush assertion did not fire");
    }
    std::cout<<"COEXISTING_PHYSICAL_INGRESS_PASS enabled="<<COEXISTING_PHYSICAL_LOAD_INGRESS<<'\n';return 0;
} catch(const std::exception&e) {
    std::cerr<<"COEXISTING_PHYSICAL_INGRESS_FAIL "<<e.what()<<'\n';return 1;
} }
