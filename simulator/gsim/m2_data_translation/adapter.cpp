#include "M2DataTranslationGsim.h"
#define CANONICAL_TEST_RAM_BASE 0x80200000ULL
#define VIRTUAL_LOAD_TEST_RAM_BASE 0x80200000ULL
#define VIRTUAL_LOAD_TEST_RAM_BYTES (1ULL << 31)
#include "oracle.h"
#include "../harness/virtual_load_test_memory.h"
#include <deque>
#include <iostream>
#include <optional>
#include <tuple>
#include <vector>
#include <algorithm>
using namespace canonical_store_test;

struct Request {
    Descriptor descriptor;
    bool origin = true, write = true, atomic = false, virt = true;
    bool lateError = false, prechecked = false;
    unsigned atomicOp = 0;
    uint32_t translationEpoch = 0;
    uint64_t data = 0x8877665544332211ULL;
};
struct Expected {
    Request request;
    bool pageFault = false, accessFault = false, uncached = false, certify = false;
    uint64_t physical = 0;
    bool physicalSeen = false, certificateSeen = false;
    uint64_t acceptedCycle = 0;
};
struct Reply { uint64_t due, data; bool error; };

class Bench {
    SM2DataTranslationGsim d;
    std::deque<Reply> ptes, replies;
    std::deque<Expected> expected;
    using Payload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, bool, bool, bool, uint64_t, bool>;
    std::optional<Payload> held;
    using Response = std::tuple<uint64_t, bool, bool>;
    std::optional<Response> heldResponse;
public:
    virtual_load_test::PageTables tables;
    uint64_t cycle = 0, blockPhysical = 0, blockResponse = 0, context = virtual_load_test::satp;
    uint32_t epoch = 1;
    unsigned cfg = 0x1f, privilege = 1, latency = 9;
    bool sum = false, mxr = false, flush = false, inject = false, ideal = false;
    unsigned translatedPushes = 0, translatedPops = 0, translationFires = 0, fullReleaseEvents = 0;
    std::optional<uint64_t> pendingFullRelease;
    std::vector<uint64_t> fullReleaseResumeGaps;
    std::vector<uint64_t> acceptCycles, physicalCycles, returnCycles, physicalLatencies;
    std::string mutation;
    unsigned hitCertificates = 0, hitSpills = 0, checkedFull = 0, translatedFull = 0, ownersFull = 0;
    unsigned heldResponses = 0, warmPmpDenied = 0;
    unsigned accepted = 0, returned = 0, certificates = 0, physical = 0, pteReads = 0, walks = 0, hits = 0;
    unsigned heldPhysical = 0, heldUpstream = 0, lateErrors = 0, noCertificate = 0;
    Bench() {
        drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        for (unsigned n = 0; n < 5; ++n) tick();
        require(d.get_io$$epoch() == epoch && d.get_io$$stable(), "initial authorization epoch did not settle");
    }
    Expected truth(const Request &r) const {
        Expected e; e.request = r;
        const auto &a = r.descriptor;
        if (r.prechecked) {
            e.physical = a.virtualAddress;
            e.accessFault = r.virt || r.write || r.atomic || privilege == 3 || !(context >> 60) ||
                r.translationEpoch != epoch || !wholeRam(e.physical, a.size);
        } else if (r.virt) {
            const bool canonical = (a.virtualAddress >> 39) == 0 && ((a.virtualAddress >> 38) & 1) == 0;
            const auto i = tables.pages.find(unsigned((a.virtualAddress - va) / 4096));
            if (!canonical || i == tables.pages.end()) { e.pageFault = true; return e; }
            const auto &mapping = i->second;
            const unsigned flags = mapping.flags;
            const bool readable = flags & 2, writable = flags & 4, executable = flags & 8;
            const bool user = flags & 16, accessed = flags & 64, dirty = flags & 128;
            const bool leaf = readable || executable;
            const bool needsRead = r.atomic ? r.atomicOp != 3 : !r.write;
            const bool needsWrite = r.atomic ? r.atomicOp != 2 : r.write;
            const bool allowed = (!needsRead || readable || (mxr && executable)) &&
                (!needsWrite || (writable && dirty));
            e.pageFault = !(flags & 1) || (!readable && writable) || !leaf || !accessed || !allowed ||
                (privilege == 1 && user && !sum) || (privilege == 0 && !user) || mapping.pbmt == 3;
            e.physical = mapping.physical + a.virtualAddress % 4096;
            e.uncached = mapping.pbmt != 0;
        } else e.physical = a.virtualAddress;
        // This fixture uses one all-address NAPOT entry, independent of the DUT's decoded region.
        const bool needsRead = r.atomic ? r.atomicOp != 3 : !r.write;
        const bool needsWrite = r.atomic ? r.atomicOp != 2 : r.write;
        e.accessFault |= !e.pageFault && (r.virt || r.prechecked) &&
            ((needsRead && !(cfg & 1)) || (needsWrite && !(cfg & 2)) ||
             (r.atomic && !wholeRam(e.physical, a.size)));
        auto actualShape = a; actualShape.physicalAddress = e.physical;
        e.certify = !e.pageFault && !e.accessFault && r.origin && r.virt && r.write && !r.atomic && !r.prechecked &&
            !e.uncached && a.epoch == epoch && shape(actualShape);
        return e;
    }
    void drive(std::optional<Request> request) {
        const auto r = request.value_or(Request{}); const auto &a = r.descriptor;
        d.set_io$$upstream$$request$$valid(request.has_value());
        d.set_io$$upstream$$request$$bits$$address(a.virtualAddress);
        d.set_io$$upstream$$request$$bits$$data(r.data);
        d.set_io$$upstream$$request$$bits$$size(a.size);
        d.set_io$$upstream$$request$$bits$$mask(a.mask);
        d.set_io$$upstream$$request$$bits$$write(r.write);
        d.set_io$$upstream$$request$$bits$$atomic(r.atomic);
        d.set_io$$upstream$$request$$bits$$atomicOp(r.atomicOp);
        d.set_io$$upstream$$request$$bits$$virtualized(r.virt);
        d.set_io$$upstream$$request$$bits$$uncached(0);
        d.set_io$$upstream$$request$$bits$$precheckedLoad(r.prechecked);
        d.set_io$$upstream$$request$$bits$$translationEpoch(r.translationEpoch);
        d.set_io$$upstream$$request$$bits$$prefetchNextAllowed(0);
        d.set_io$$origin$$valid(request && r.origin);
        d.set_io$$origin$$bits$$token$$index(a.token.index);
        d.set_io$$origin$$bits$$token$$tag(a.token.tag);
        d.set_io$$origin$$bits$$epoch(a.epoch);
        d.set_io$$upstream$$response$$ready(cycle >= blockResponse);
        d.set_io$$physical$$request$$ready(cycle >= blockPhysical && (ideal || cycle % 7 != 5));
        const bool response = !replies.empty() && replies.front().due <= cycle;
        d.set_io$$physical$$response$$valid(response);
        d.set_io$$physical$$response$$bits$$data(response ? replies.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(response && replies.front().error);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$request$$ready((ideal || cycle % 5 != 3));
        d.set_io$$pte$$response$$valid(pte);
        d.set_io$$pte$$response$$bits$$data(pte ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
        d.set_io$$context$$satp(context); d.set_io$$context$$dataPrivilege(privilege);
        d.set_io$$context$$sum(sum); d.set_io$$context$$mxr(mxr);
        d.set_io$$pmpCfg(cfg); d.set_io$$pmpAddress(virtual_load_test::allPmp);
        d.set_io$$flush(flush);
    }
    bool tick(std::optional<Request> request = {}) {
        const bool response = !replies.empty() && replies.front().due <= cycle;
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        drive(request); d.step();
        const bool take = request && d.get_io$$upstream$$request$$ready();
        if (take) {
            auto item = truth(*request); item.acceptedCycle = cycle; expected.push_back(item);
            acceptCycles.push_back(cycle); ++accepted;
        }
        heldUpstream += request && !take;
        if (response && d.get_io$$physical$$response$$ready()) replies.pop_front();
        if (pte && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && (ideal || cycle % 5 != 3)) {
            ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits()), false}); ++pteReads;
        }
        if (d.get_io$$certificate$$valid()) {
            Token token{unsigned(d.get_io$$certificate$$bits$$origin$$token$$index()),
                uint64_t(d.get_io$$certificate$$bits$$origin$$token$$tag())};
            auto owner = expected.begin();
            while (owner != expected.end() && owner->request.descriptor.token != token) ++owner;
            require(owner != expected.end() && owner->certify && !owner->certificateSeen,
                "unexpected, forbidden, duplicate or unowned canonical certificate");
            const auto &a = owner->request.descriptor;
            const bool mutateCertificate = true;
            if (inject || mutation == "--inject-epoch" || mutation == "--inject-token")
                std::cout << "INJECT M2_ADAPTER certificate observation\n";
            require(d.get_io$$certificate$$bits$$origin$$epoch() == (a.epoch ^ (mutateCertificate && mutation == "--inject-epoch" ? 1u : 0u)) &&
                token.tag == (a.token.tag ^ (mutateCertificate && mutation == "--inject-token" ? 1u : 0u)) &&
                d.get_io$$certificate$$bits$$virtualAddress() == a.virtualAddress &&
                d.get_io$$certificate$$bits$$physicalAddress() == (owner->physical ^ (inject && mutateCertificate ? 4096ULL : 0ULL)) &&
                d.get_io$$certificate$$bits$$size() == a.size && d.get_io$$certificate$$bits$$mask() == a.mask,
                "independent PTE/write-PMP/byte-range certificate mismatch");
            require(!owner->physicalSeen, "certificate did not precede its registered physical request");
            owner->certificateSeen = true; ++certificates;
            require(d.get_io$$checkedPush(), "certificate escaped actual checked acceptance");
            hitCertificates += d.get_io$$hitPass();
        }
        const bool valid = d.get_io$$physical$$request$$valid();
        const bool ready = cycle >= blockPhysical && (ideal || cycle % 7 != 5);
        if (held) require(valid, "held physical request withdrew valid");
        // Invalid request bits may be uninitialized in generated host storage. Never evaluate
        // their getters eagerly and pass them to a conditionally checking helper.
        if (valid) {
            const Payload payload{d.get_io$$physical$$request$$bits$$address(),
                d.get_io$$physical$$request$$bits$$data(), unsigned(d.get_io$$physical$$request$$bits$$size()),
                unsigned(d.get_io$$physical$$request$$bits$$mask()), bool(d.get_io$$physical$$request$$bits$$write()),
                bool(d.get_io$$physical$$request$$bits$$atomic()), bool(d.get_io$$physical$$request$$bits$$uncached()),
                bool(d.get_io$$physical$$request$$bits$$virtualized()),
                bool(d.get_io$$physical$$request$$bits$$precheckedLoad()),
                d.get_io$$physical$$request$$bits$$translationEpoch(),
                bool(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())};
            if (held) require(payload == *held, "held physical request changed payload or attributes");
            held = !ready ? std::optional<Payload>{payload} : std::nullopt;
            heldPhysical += !ready;
            if (ready) {
                auto owner = expected.begin();
                while (owner != expected.end() && (owner->pageFault || owner->accessFault || owner->physicalSeen)) ++owner;
                require(owner != expected.end(), "unexpected physical request bypassed a fault or duplicated ownership");
                const auto &r = owner->request;
                require(std::get<0>(payload) == owner->physical && std::get<1>(payload) == r.data &&
                    std::get<2>(payload) == r.descriptor.size && std::get<3>(payload) == r.descriptor.mask &&
                    std::get<4>(payload) == r.write && std::get<5>(payload) == r.atomic &&
                    std::get<6>(payload) == owner->uncached && !std::get<7>(payload) && !std::get<8>(payload) &&
                    std::get<9>(payload) == 0 &&
                    d.get_io$$physical$$request$$bits$$atomicOp() == r.atomicOp,
                    "independent ordered physical payload mismatch");
                require(owner->certificateSeen == owner->certify, "missing required checked-boundary certificate");
                owner->physicalSeen = true; ++physical;
                physicalCycles.push_back(cycle); physicalLatencies.push_back(cycle - owner->acceptedCycle);
                replies.push_back({cycle + latency, r.write ? 0 : beatData(owner->physical), r.lateError});
            }
        }
        const bool responseValid = d.get_io$$upstream$$response$$valid();
        if (heldResponse) require(responseValid, "held upstream response withdrew valid");
        if (responseValid) {
            const Response payload{d.get_io$$upstream$$response$$bits$$data(),
                bool(d.get_io$$upstream$$response$$bits$$error()),
                bool(d.get_io$$upstream$$response$$bits$$pageFault())};
            if (heldResponse) require(payload == *heldResponse, "held ordered response changed");
            heldResponse = cycle < blockResponse ? std::optional<Response>{payload} : std::nullopt;
            heldResponses += cycle < blockResponse;
        }
        if (responseValid && cycle >= blockResponse) {
            require(!expected.empty(), "unowned upstream response");
            const auto e = expected.front(); expected.pop_front();
            const bool fault = e.pageFault || e.accessFault || e.request.lateError;
            if (mutation == "--inject-permission" && e.accessFault)
                std::cout << "INJECT M2_ADAPTER permission observation\n";
            require(bool(d.get_io$$upstream$$response$$bits$$error()) ==
                (fault != (mutation == "--inject-permission" && e.accessFault)) &&
                bool(d.get_io$$upstream$$response$$bits$$pageFault()) == e.pageFault,
                "ordered real response lost page/access/late physical error");
            const uint64_t data = e.pageFault || e.accessFault || e.request.write ? 0 : beatData(e.physical);
            require(d.get_io$$upstream$$response$$bits$$data() == data, "ordered response data mismatch");
            require(e.physicalSeen == !(e.pageFault || e.accessFault) && e.certificateSeen == e.certify,
                "response arrived without exactly the independently required physical/certificate events");
            lateErrors += e.request.lateError; noCertificate += !e.certify; ++returned; returnCycles.push_back(cycle);
        }
        const auto checked = d.get_io$$checkedCount();
        checkedFull += checked == 2;
        translatedFull += d.get_io$$translatedCount() == 8;
        ownersFull += d.get_io$$ownerCount() == 8;
        hitSpills += d.get_io$$hitOffer() && !d.get_io$$hitPass() && checked == 2;
        if (pendingFullRelease && d.get_io$$translatedPush()) {
            fullReleaseResumeGaps.push_back(cycle - *pendingFullRelease); pendingFullRelease.reset();
        }
        if (d.get_io$$translatedCount() == 8 && d.get_io$$translatedPop()) {
            require(!d.get_io$$translatedPush(), "full result queue borrowed same-cycle pop credit");
            ++fullReleaseEvents; pendingFullRelease = cycle;
        }
        translatedPushes += d.get_io$$translatedPush(); translatedPops += d.get_io$$translatedPop();
        translationFires += d.get_io$$translationFire();
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit(); ++cycle;
        return take;
    }
    Request request(uint64_t address = va, unsigned size = 3) const {
        Request r; r.descriptor.virtualAddress = address; r.descriptor.size = size;
        r.descriptor.mask = lanes(address, size); r.descriptor.epoch = epoch;
        r.descriptor.token = Token{unsigned(accepted % 16), 1 + accepted / 16};
        r.data ^= uint64_t(accepted) * 0x0102040810204081ULL;
        return r;
    }
    void send(Request r) {
        for (unsigned n = 0; n < 1000; ++n) if (tick(r)) return;
        throw std::runtime_error("upstream acceptance timed out");
    }
    void drain() {
        for (unsigned n = 0; n < 2000 && (!expected.empty() || !replies.empty() || !ptes.empty()); ++n) tick();
        for (unsigned n = 0; n < 5; ++n) tick();
        require(expected.empty() && replies.empty() && ptes.empty() && !held && d.get_io$$idle(),
            "all real owners, fault placeholders and certificate-only state failed to drain");
        require(accepted == returned, "request/response conservation failure");
    }
    void run(Request r) { send(r); drain(); }
    void measure(const std::string &name, unsigned count, bool congested = false) {
        drain(); ideal = true; latency = 1;
        const auto start = cycle;
        const auto a = accepted, r = returned, ph = physical, h = hits, w = walks;
        const auto hp = hitCertificates, tp = translatedPushes, pp = translatedPops, tf = translationFires;
        const auto fr = fullReleaseEvents, gapIndex = unsigned(fullReleaseResumeGaps.size());
        if (congested) { blockPhysical = cycle + 64; blockResponse = cycle + 96; }
        for (unsigned n = 0; n < count; ++n) send(request(va + (n % 64) * 8));
        drain();
        require(accepted - a == count && returned - r == count && physical - ph == count &&
            hits - h == count && walks == w && translationFires - tf == count,
            "warm stream did not actually traverse a real demand TLB hit per owner");
        const auto acceptanceSpan = acceptCycles.back() - acceptCycles.at(a) + 1;
        const auto physicalSpan = physicalCycles.back() - physicalCycles.at(ph) + 1;
        if (!congested) require(acceptanceSpan == count && physicalSpan == count,
            "continuous warm supply lost II=1 at upstream or physical boundary");
        const auto resumeGap = fullReleaseResumeGaps.size() > gapIndex ? fullReleaseResumeGaps.at(gapIndex) : 0;
        if (congested) require(fullReleaseEvents > fr && resumeGap == 1,
            "full result boundary release must expose one no-borrow edge then resume next cycle");
        std::cout << "M2_TRANSLATION_METRIC scenario=" << name << " count=" << count
                  << " cycles=" << cycle - start << " acceptance_span=" << acceptanceSpan
                  << " physical_span=" << physicalSpan << " first_physical_latency=" << physicalLatencies.at(ph)
                  << " first_return_latency=" << returnCycles.at(r) - acceptCycles.at(a)
                  << " hit_pass=" << hitCertificates - hp << " translated_push=" << translatedPushes - tp
                  << " translated_pop=" << translatedPops - pp << " demand_hits=" << hits - h
                  << " full_release_events=" << fullReleaseEvents - fr << " first_release_resume_gap=" << resumeGap << '\n';
        ideal = false; latency = 9;
    }
    void maintenance(bool translationFlush = true) {
        require(expected.empty() && replies.empty() && d.get_io$$idle(), "driver attempted illegal undrained maintenance");
        flush = translationFlush; tick(); flush = false; ++epoch;
        for (unsigned n = 0; n < 5; ++n) tick();
        require(d.get_io$$epoch() == epoch && d.get_io$$stable(), "legal maintenance epoch mismatch");
    }
};

int main(int argc, char **argv) { try {
    Bench b; const std::string mode = argc > 1 ? argv[1] : "";
    require(mode.empty() || mode == "--inject-pa" || mode == "--inject-epoch" || mode == "--inject-token" ||
        mode == "--inject-permission" || mode == "--force-undrained-flush", "unknown option");
    b.inject = mode == "--inject-pa"; b.mutation = mode;
    // Cold walk then warm translation hit, with checked proof preceding a delayed actual write response.
    b.blockPhysical = b.cycle + 60; b.run(b.request());
    require(b.certificates == 1 && b.walks == 1 && b.heldPhysical, "cold checked-store witness missing");
    b.run(b.request(va + 8)); require(b.hits, "warm write translation hit witness missing");
    b.measure("warm_single", 1); b.measure("warm_stream", 256); b.measure("congested_stream", 256, true);
    for (unsigned size = 0; size < 4; ++size) {
        const unsigned width = 1u << size;
        for (unsigned offset = 0; offset < 8; offset += width) b.run(b.request(va + offset, size));
    }
    // Distinct VAs with identical PA, adjacent PA and normal uncached/out-of-aperture mappings.
    for (unsigned page : {2u, 1u, 3u, 4u, 5u, 6u, 7u, 9u}) b.run(b.request(va + page * 4096));
    auto stale = b.request(); --stale.descriptor.epoch; b.run(stale);
    auto absent = b.request(); absent.origin = false; b.run(absent);
    auto mask = b.request(); mask.descriptor.mask = 15; b.run(mask);
    b.run(b.request(va + 1, 3)); b.run(b.request(va + 4092, 3));
    auto read = b.request(); read.origin = false; read.write = false; b.run(read);
    auto atomic = b.request(); atomic.origin = false; atomic.atomic = true; b.run(atomic);
    for (unsigned op : {2u, 3u, 0u}) {
        auto normal = b.request(); normal.origin = false; normal.atomic = true; normal.atomicOp = op; normal.write = op != 2;
        b.run(normal);
        auto mmio = b.request(va + 3 * 4096); mmio.origin = false; mmio.atomic = true; mmio.atomicOp = op; mmio.write = op != 2;
        b.run(mmio);
    }
    auto prechecked = b.request(ram); prechecked.origin = false; prechecked.virt = false; prechecked.write = false;
    prechecked.prechecked = true; prechecked.translationEpoch = b.epoch; b.run(prechecked);
    --prechecked.translationEpoch; b.run(prechecked);
    auto physical = b.request(ram); physical.origin = false; physical.virt = false; b.run(physical);
    for (unsigned flags : {0x43u, 0x47u, 0x87u, 0xc5u, 0xc3u}) {
        b.tables.pages[0] = {ram, flags}; b.maintenance(); b.run(b.request());
    }
    b.tables.pages[0] = {ram, 0xc7}; b.maintenance();
    for (unsigned pbmt : {1u, 2u, 3u}) {
        b.tables.pages[0] = {ram, 0xc7, pbmt}; b.maintenance(); b.run(b.request());
    }
    b.tables.pages[0] = {ram, 0xc7}; b.maintenance();
    b.run(b.request()); // Explicitly populate a successful WRITE translation before PMP changes.
    const auto warmHits = b.hits, warmWalks = b.walks, warmPhysical = b.physical, warmCert = b.certificates;
    b.cfg = 0x19; b.maintenance(false); b.run(b.request()); // PTE reads allowed, final physical write denied.
    require(b.hits == warmHits + 1 && b.walks == warmWalks && b.physical == warmPhysical &&
        b.certificates == warmCert, "warm TLB hit escaped final PMP write denial");
    ++b.warmPmpDenied;
    b.cfg = 0x1f; b.maintenance(false);
    b.sum = true; b.maintenance(false); b.run(b.request(va + 6 * 4096));
    b.sum = false; b.maintenance(false);
    // Explicit upper PA bits and the exact aperture end are independent software mapping cases.
    b.tables.pages[0] = {ram | (1ULL << 48), 0xc7}; b.maintenance(); b.run(b.request());
    b.tables.pages[0] = {ram + ramBytes - 4096, 0xc7}; b.maintenance();
    b.run(b.request(va + 4095, 0)); b.run(b.request(va + 4088, 3));
    b.run(b.request(va + 4092, 3));
    // Legal same-VA remap and ASID change retain the original VA but demand fresh PA/epoch truth.
    b.tables.pages[0] = {ram + 4096, 0xc7}; b.maintenance(); b.run(b.request());
    b.context ^= 1ULL << 44; b.maintenance(false); b.run(b.request());
    for (uint64_t generation : {254ULL, 255ULL}) {
        auto wrapped = b.request(va + 6, 1); wrapped.descriptor.token = {3, generation}; b.run(wrapped);
    }
    // Late store errors still produce the real response after successful authorization.
    auto late = b.request(); late.lateError = true; b.run(late);
    if (mode == "--force-undrained-flush") {
        b.blockPhysical = b.cycle + 100; b.send(b.request());
        for (unsigned n = 0; n < 10; ++n) b.tick();
        std::cout << "INJECT M2_ADAPTER undrained flush\n" << std::flush;
        b.flush = true; b.tick();
        throw std::runtime_error("undrained context-change assertion did not fire");
    }
    // Fill existing queues, hold request payload/origin across changing offered owners, and drain every response.
    b.blockPhysical = b.cycle + 220; b.blockResponse = b.cycle + 300;
    for (unsigned n = 0; n < 40; ++n) {
        auto queued = b.request(va + (n % 8) * 8);
        if (n == 7 || n == 19) queued.descriptor.virtualAddress = va + 9 * 4096;
        if (n % 11 == 5) --queued.descriptor.epoch;
        queued.lateError = n % 13 == 9;
        b.send(queued);
    }
    b.drain();
    require(b.heldUpstream && b.heldPhysical && b.lateErrors && b.noCertificate,
        "backpressure/negative permission/late-error coverage missing");
    require(b.checkedFull && b.translatedFull && b.ownersFull && b.heldResponses && b.warmPmpDenied,
        "combined full-queue/held-response/PMP witness missing");
    require(b.translatedPushes == b.translatedPops, "translation result descriptor conservation failed");

    std::cout << "M2_TRANSLATION_ADAPTER_PASS accepted=" << b.accepted << " returned=" << b.returned
        << " certificates=" << b.certificates << " physical=" << b.physical << " walks=" << b.walks
        << " holds=" << b.heldUpstream << "/" << b.heldPhysical << "/" << b.heldResponses
        << " hit_certificates=" << b.hitCertificates << " hit_spills=" << b.hitSpills
        << " full=" << b.checkedFull << "/" << b.translatedFull << "/" << b.ownersFull
        << " warm_pmp_denied=" << b.warmPmpDenied << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << "M2_TRANSLATION_ADAPTER_FAIL " << e.what() << '\n'; return 1; } }
