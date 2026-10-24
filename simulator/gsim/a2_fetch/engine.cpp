// Keep the prior independent byte-range PMP/memory oracle unchanged. This
// driver replaces only its single-owner stimulus/history, not its semantics.
#define main isolated_permission_fixture_main
#include "../harness/instruction_permission.cpp"
#undef main
#include <deque>
#include <optional>

namespace pipeline {
struct Owner {
    Case c;
    Expected e;
    uint64_t satp, accepted;
    bool sum, mxr, identity, translationIssued = false, translated = false, physicalIssued = false, physicalDone = false;
    unsigned id;
};
struct TlbReply { unsigned id; uint64_t due; };
struct PhysicalReply { unsigned id; uint64_t pa, due; };
static Owner make(unsigned id) {
    Owner o{}; o.id = id;
    o.c.va = 0x40000000ULL + 8 * id;
    o.c.pa0 = 0x80000000ULL + 8 * id;
    o.c.mask = id % 4; o.c.privilege = 1;
    o.c.cfg = {0x0c, 0}; o.c.addr = {0x90000000ULL / 4, 0};
    o.satp = (UINT64_C(8) << 60) | (uint64_t(23 + id) << 44) | (0x2345 + id);
    o.sum = id & 1; o.mxr = id & 2;
    if (id % 13 == 2) o.c.pa0 = 0x90000000ULL + 8 * id; // PMP denied, no physical transaction
    if (id % 11 == 3) o.c.page0 = true;
    if (id % 17 == 5) o.c.access0 = true;
    if (id % 5 == 4) { o.satp &= (UINT64_C(1) << 60) - 1; o.c.privilege = id & 1 ? 3 : 1; }
    // First owner deliberately has a long walk; second is held in old S context
    // while live privilege/SATP are changed to M/Bare by adversarial trap input.
    if (id == 0) { o.c.mask = 3; o.c.page0 = o.c.access0 = false; }
    if (id == 1) { o.c.mask = 3; o.c.page0 = true; }
    o.identity = o.c.privilege == 3 || !(o.satp >> 60);
    if (o.identity) { o.c.pa0 = o.c.va; o.c.page0 = o.c.access0 = false; }
    o.translated = o.identity;
    o.e = oracle(o.c);
    o.physicalDone = o.e.requests.empty();
    return o;
}
static void run(bool negative, bool unowned) {
    SInstructionPermissionGsim d;
    d.set_io$$virtualValid(0); d.set_io$$virtualPc(0); d.set_io$$virtualMask(0);
    d.set_io$$virtualResponseReady(0); d.set_io$$satp(0); d.set_io$$sum(0); d.set_io$$mxr(0);
    d.set_io$$privilege(1); d.set_io$$cfg0(0x0c); d.set_io$$cfg1(0);
    d.set_io$$addr0(0x90000000ULL / 4); d.set_io$$addr1(0);
    d.set_io$$translationReady(0); d.set_io$$translationResponseValid(0);
    d.set_io$$translationPhysical(0); d.set_io$$translationPage(0); d.set_io$$translationError(0);
    d.set_io$$physicalReady(0); d.set_io$$physicalResponseValid(0);
    d.set_io$$physicalResponseLow(0); d.set_io$$physicalResponseHigh(0);
    d.set_io$$physicalErrors(0); d.set_io$$physicalPages(0);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    std::deque<Owner> owners;
    std::optional<TlbReply> tlb;
    std::deque<PhysicalReply> physical;
    unsigned accepted = 0, retired = 0, maximum = 0, turnover = 0, responseHeld = 0, heldContext = 0;
    unsigned youngerFault = 0, simultaneousTranslation = 0, overlappedPhysical = 0, drained = 0;
    unsigned completionCollision = 0, earlyPhysicalOffers = 0;
    bool offerHeld = false;
    const unsigned count = 128;
    auto find = [&](unsigned id) -> Owner & {
        for (auto &o : owners) if (o.id == id) return o;
        throw std::runtime_error("engine service response lost accepted owner");
    };
    for (uint64_t cycle = 0; cycle < 10000; ++cycle) {
        auto next = make(accepted);
        const bool valid = accepted < count;
        const bool vr = cycle % 13 >= 4;
        const bool tr = cycle % 5 != 2;
        const bool pr = cycle % 7 != 3;
        std::optional<unsigned> translate;
        for (const auto &o : owners) if (!o.identity && !o.translationIssued) { translate = o.id; break; }
        // Actual service law: one miss owner. Some responses share the request
        // cycle; others take 2 or 17 cycles. It is not a duplicate DUT TLB.
        const bool instant = !tlb && translate && tr && (*translate % 3 == 1) && *translate != 1;
        const bool tv = (tlb && cycle >= tlb->due) || instant;
        const unsigned tid = tlb ? tlb->id : (translate ? *translate : 0);
        const Owner *to = tv ? &find(tid) : nullptr;
        std::optional<uint64_t> earlyPhysical;
        if (physical.empty() && pr) for (const auto &o : owners) {
            if (o.id == 9 && o.translated && !o.physicalIssued && !o.e.requests.empty())
                earlyPhysical = o.e.requests.front().address;
        }
        const bool badPhysical = unowned && cycle == 0;
        const bool pv = badPhysical || earlyPhysical || (!physical.empty() && cycle >= physical.front().due);
        const uint64_t pa = earlyPhysical ? *earlyPhysical : (pv && !physical.empty() ? physical.front().pa : 0);
        if (badPhysical) std::cerr << "INJECT unowned physical\n";
        d.set_io$$virtualValid(valid); d.set_io$$virtualPc(next.c.va); d.set_io$$virtualMask(next.c.mask);
        // This is legal trap-style live-context churn, not a change to the held
        // public address/mask. Expected context remains the FIRST offered one.
        d.set_io$$satp(offerHeld ? 0 : next.satp);
        d.set_io$$privilege(offerHeld ? 3 : next.c.privilege);
        d.set_io$$sum(offerHeld ? !next.sum : next.sum); d.set_io$$mxr(offerHeld ? !next.mxr : next.mxr);
        heldContext += offerHeld;
        d.set_io$$virtualResponseReady(vr);
        d.set_io$$translationReady(tr); d.set_io$$translationResponseValid(tv);
        d.set_io$$translationPhysical(to ? to->c.pa0 : 0);
        d.set_io$$translationPage(to && to->c.page0); d.set_io$$translationError(to && to->c.access0);
        d.set_io$$physicalReady(pr); d.set_io$$physicalResponseValid(pv);
        d.set_io$$physicalResponseLow(memoryPair(pa)); d.set_io$$physicalResponseHigh(0);
        d.set_io$$physicalErrors(memoryErrors(pa)); d.set_io$$physicalPages(memoryPages(pa));
        d.step();
        check(!badPhysical, "unowned physical input was not rejected by hardware");
        if (earlyPhysical) {
            check(d.get_io$$physicalValid() && pr && !d.get_io$$physicalResponseReady(),
                "first physical response offer must wait for registered route ownership");
            ++earlyPhysicalOffers;
        }
        const bool take = valid && d.get_io$$virtualReady();
        const bool retire = vr && d.get_io$$virtualResponseValid();
        completionCollision += tv && to && (to->c.page0 || to->c.access0) && pv &&
            d.get_io$$physicalResponseReady() && !d.get_io$$translationResponseReady();
        check(bool(d.get_io$$idle()) == (owners.empty() && !offerHeld), "engine idle skipped live/held context");
        if (d.get_io$$translationValid()) {
            check(translate.has_value(), "unowned/duplicated translation offer");
            auto &o = find(*translate);
            check(d.get_io$$translationPc() == o.c.va &&
                d.get_io$$translationRoot() == (o.satp & ((UINT64_C(1) << 44) - 1)) &&
                d.get_io$$translationAsid() == ((o.satp >> 44) & 65535) &&
                d.get_io$$translationMode() == o.satp >> 60 && d.get_io$$translationPrivilege() == o.c.privilege &&
                d.get_io$$translationSum() == o.sum && d.get_io$$translationMxr() == o.mxr &&
                d.get_io$$translationAccess() == 2, "held trap context was reinterpreted or mixed between owners");
            if (tr) {
                check(!tlb, "multiple TLB miss service owners");
                o.translationIssued = true;
                uint64_t due = instant ? cycle : cycle + (o.id % 8 == 0 ? 17 : 2);
                if (o.id == 1) {
                    if (!physical.empty()) {
                        check(physical.front().due > cycle,
                            "directed local/physical completion collision not scheduled");
                        due = physical.front().due;
                    } else {
                        check(d.get_io$$physicalValid() && pr && owners.front().id == 0,
                            "directed collision lacks old physical request");
                        due = cycle + 17; // The fixed service latency for owner zero accepted below.
                    }
                }
                tlb = TlbReply{o.id, due};
            }
        }
        if (tv && d.get_io$$translationResponseReady()) {
            auto &o = find(tid);
            check(o.translationIssued, "translation result precedes request");
            o.translated = true;
            youngerFault += (o.c.page0 || o.c.access0) && o.id != owners.front().id && !owners.front().physicalDone;
            simultaneousTranslation += instant;
            tlb.reset();
        }
        if (d.get_io$$physicalValid()) {
            Owner *selected = nullptr;
            for (auto &o : owners) if (!o.physicalIssued && !o.e.requests.empty()) { selected = &o; break; }
            check(selected && selected->translated, "physical request lost its translation/permission owner");
            const auto &r = selected->e.requests.front();
            check(d.get_io$$physicalPc() == r.address && d.get_io$$physicalMask() == r.mask,
                "independent two-owner physical mask/address mismatch");
            if (pr) {
                physical.push_back({selected->id, r.address,
                    earlyPhysical ? cycle : cycle + (selected->id % 8 == 0 ? 17 : 3)});
                selected->physicalIssued = true;
                overlappedPhysical += physical.size() > 1;
            }
        }
        if (pv && d.get_io$$physicalResponseReady()) {
            find(physical.front().id).physicalDone = true;
            physical.pop_front();
        }
        if (d.get_io$$virtualResponseValid()) {
            check(!owners.empty(), "unowned public response");
            const auto &o = owners.front();
            const uint64_t observed = d.get_io$$virtualResponseLow() ^ uint64_t(negative && retired == 7);
            check(o.translated && o.physicalDone && observed == o.e.low && d.get_io$$virtualResponseHigh() == 0 &&
                d.get_io$$virtualErrors() == o.e.errors && d.get_io$$virtualPages() == o.e.pages,
                "independent two-owner ordered response mismatch");
            responseHeld += !vr;
        }
        if (retire) { owners.pop_front(); ++retired; }
        if (take) { next.accepted = cycle; owners.push_back(next); ++accepted; turnover += retire; }
        maximum = std::max(maximum, unsigned(owners.size()));
        check(owners.size() <= 2, "engine exceeded reserved owner capacity");
        offerHeld = valid && !take;
        if (retired == count && ++drained == 5) break;
    }
    check(accepted == count && retired == count && owners.empty() && !tlb && physical.empty() && drained == 5,
        "two-owner engine failed to drain exactly once");
    check(maximum == 2 && turnover && responseHeld && heldContext && youngerFault && simultaneousTranslation &&
        overlappedPhysical && completionCollision && earlyPhysicalOffers == 1, "two-owner engine coverage incomplete");
    std::cout << "PASS A2_FETCH_ENGINE accepted=" << accepted << " retired=" << retired
        << " max_owners=" << maximum << " turnover=" << turnover << " response_held=" << responseHeld
        << " held_context_churn=" << heldContext << " younger_fault_before_old_physical=" << youngerFault
        << " same_cycle_translation=" << simultaneousTranslation << " physical_overlap=" << overlappedPhysical
        << " physical_local_completion_collision=" << completionCollision
        << " first_request_same_cycle_response_offer=" << earlyPhysicalOffers << '\n';
}
}
int main(int argc, char **argv) { try {
    const std::string_view mode = argc == 2 ? argv[1] : "";
    check(argc <= 2 && (mode.empty() || mode == "--inject-mismatch" || mode == "--unowned-physical"),
        "bad engine argument");
    pipeline::run(mode == "--inject-mismatch", mode == "--unowned-physical"); return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
