// Reuse only the unchanged, independent byte-range and memory oracle. The old
// isolated fixture remains its own executable, including synthetic M-mode PA.
#define main isolated_permission_fixture_main
#include "instruction_permission.cpp"
#undef main
#include <deque>
#ifndef FETCH_REPLY_TURNOVER
#define FETCH_REPLY_TURNOVER 0
#endif
#ifndef FETCH_IDENTITY_TRANSLATION
#define FETCH_IDENTITY_TRANSLATION 0
#endif

namespace stream {
struct Owner {
    Case request;
    uint64_t root;
    bool sum, mxr;
    Expected expected;
    unsigned translations = 0, translationReplies = 0, physical = 0, physicalReplies = 0, held = 0;
    bool permissionOffered = false;
};
struct Translation { uint64_t due, pa; bool page, error; };
struct Physical { uint64_t due, pa; };
static Owner owner(unsigned index) {
    Owner o{};
    auto& c = o.request;
    c.va = 0x40001000ULL + index * 32;
    c.pa0 = 0x80001000ULL + index * 32;
    c.pa1 = 0x90003000ULL;
    c.privilege = index % 3 == 0 ? 3 : (index % 3 == 1 ? 1 : 0);
    o.root = (index % 4 == 0 ? 0ULL : 0x8000000000000000ULL) |
        (uint64_t(index + 1) << 44) | (0x1234 + index);
    o.sum = index & 1; o.mxr = index & 2;
    switch (index % 10) {
    case 1: c.cfg = {0x10, 0x0c}; c.addr = {c.pa0 / 4, addrMax}; break;
    case 2: c.cfg[0] = 0x08; break;
    case 3: c.cfg[0] = 0x88; break;
    case 4: c.mask = 0; break;
    case 5: c.page0 = true; c.access0 = true; break;
    case 6: c.access0 = true; break;
    case 7: c.mask = 2; break;
    case 8: c.cfg = {0x14, 0x08}; c.addr = {c.pa0 / 4, addrMax}; break;
    default: break;
    }
    // Architectural identity cases are isolated from synthetic translated-M
    // coverage. Sv39 owners always retain nonidentity physical addresses.
    const bool identity = c.privilege == 3 || (o.root >> 60) == 0;
    if (identity) {
        c.pa0 = c.va; c.pa1 = c.va + 4;
        c.page0 = c.access0 = false;
        if ((c.cfg[0] & 0x18) == 0x10) c.addr[0] = c.pa0 / 4;
    }
    if (!ALIGNED_PACKET && index >= 10) {
        c.va = index == 19 ? UINT64_MAX - 3 : 0x40000ffcULL;
        if (identity) { c.pa0 = c.va; c.pa1 = c.va + 4; }
        else { c.pa0 = 0x80000ffcULL; c.pa1 = 0x90003000ULL; }
        c.mask = index == 17 ? 2 : 3;
        if ((c.cfg[0] & 0x18) == 0x10) c.addr[0] = c.pa0 / 4;
        if (!identity && index == 11) { c.page1 = true; c.access1 = true; }
        if (!identity && index == 13) c.access1 = true;
        if (index == 15 || index == 16) {
            c.privilege = 1; o.root |= 0x8000000000000000ULL;
            c.pa0 = 0x80000ffcULL; c.pa1 = 0x90003000ULL;
            c.page0 = index == 15; c.access0 = true;
        }
        if (index == 18) { // Architectural M-mode identity crosses XLEN wrap.
            c.va = UINT64_MAX - 3; c.pa0 = c.va; c.pa1 = 0;
            c.cfg = {0, 0}; c.addr = {0, 0};
        }
        if (index == 19) { c.privilege = 1; o.root |= 0x8000000000000000ULL;
            c.pa0 = 0x80000ffcULL; c.pa1 = 0x90003000ULL; }
    }
    o.expected = oracle(c);
    return o;
}
static bool bypass(const Owner& o) {
    return FETCH_IDENTITY_TRANSLATION && (o.request.privilege == 3 || !(o.root >> 60));
}
static unsigned translationCount(const Owner& o) {
    return bypass(o) ? 0 : 1 + unsigned(o.expected.crosses && !o.request.page0 && !o.request.access0);
}
static void context(SInstructionPermissionGsim& d, const Owner& o) {
    d.set_io$$satp(o.root); d.set_io$$sum(o.sum); d.set_io$$mxr(o.mxr);
    d.set_io$$privilege(o.request.privilege);
}
static void permissions(SInstructionPermissionGsim& d, const Case& c) {
    d.set_io$$cfg0(c.cfg[0]); d.set_io$$cfg1(c.cfg[1]);
    d.set_io$$addr0(c.addr[0]); d.set_io$$addr1(c.addr[1]);
}
static void run(bool negative) {
    static_assert(PACKET_WORDS == 2, "short stream covers production two-word adapter");
    SInstructionPermissionGsim d;
    d.set_io$$virtualValid(0); d.set_io$$virtualResponseReady(0);
    d.set_io$$translationReady(0); d.set_io$$translationResponseValid(0);
    d.set_io$$translationPhysical(0); d.set_io$$translationPage(0); d.set_io$$translationError(0);
    d.set_io$$physicalReady(0); d.set_io$$physicalResponseValid(0);
    d.set_io$$physicalResponseLow(0); d.set_io$$physicalResponseHigh(0);
    d.set_io$$physicalErrors(0); d.set_io$$physicalPages(0);
    auto first = owner(1); context(d, first); permissions(d, first.request);
    d.set_io$$virtualPc(first.request.va); d.set_io$$virtualMask(first.request.mask);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    // Actual interface has reset and idle/drain, no flush/cancel port. Abandon
    // one accepted owner under whole-interface reset, then start a fresh epoch.
    d.set_io$$virtualValid(1); d.step(); check(d.get_io$$virtualReady(), "reset setup owner not accepted");
    d.set_io$$virtualValid(0); d.set_io$$translationReady(1); d.step();
    check(d.get_io$$translationValid(), "reset setup translation not accepted");
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    d.set_io$$translationReady(0); d.step();
    check(d.get_io$$idle() && !d.get_io$$virtualResponseValid() && !d.get_io$$physicalValid(),
        "reset retained abandoned owner");
    constexpr unsigned count = 20;
    std::deque<Owner> ledger;
    std::deque<Translation> translations;
    std::deque<Physical> physical;
    unsigned accepted = 0, retired = 0, simultaneous = 0, responseHolds = 0, physicalHolds = 0;
    unsigned translationRequests = 0, physicalRequests = 0, churn = 0, contextChurn = 0, drainCycles = 0;
    for (uint64_t cycle = 0; cycle < 3000; ++cycle) {
        auto next = owner(accepted < count ? accepted : 99);
        const bool offer = accepted < count;
        d.set_io$$virtualValid(offer); d.set_io$$virtualPc(next.request.va); d.set_io$$virtualMask(next.request.mask);
        // CSR churn is adversarial isolation stimulus. Real software uses the
        // adapter's idle/drain barrier before changing architectural context.
        const bool readyToRetire = !ledger.empty() && ledger.front().held >= 3;
        auto live = next;
        if (!ledger.empty() && !readyToRetire) {
            live.root ^= (cycle + 1) * 0x100000001ULL;
            live.sum = cycle & 1; live.mxr = cycle & 2;
            live.request.privilege = cycle % 4; ++contextChurn;
        }
        context(d, live);
        if (!ledger.empty() && !ledger.front().permissionOffered) permissions(d, ledger.front().request);
        else { auto poison = next.request; poison.cfg = {unsigned(cycle & 1 ? 0x88 : 0x0c), 0};
            poison.addr = {addrMax, 0}; permissions(d, poison); ++churn; }
        const bool tr = cycle % 4 != 0, pr = cycle % 5 == 0;
        const bool vr = readyToRetire;
        d.set_io$$translationReady(tr); d.set_io$$physicalReady(pr); d.set_io$$virtualResponseReady(vr);
        const bool tv = !translations.empty() && cycle >= translations.front().due;
        d.set_io$$translationResponseValid(tv);
        d.set_io$$translationPhysical(tv ? translations.front().pa : 0xdeadbeef);
        d.set_io$$translationPage(tv ? translations.front().page : true);
        d.set_io$$translationError(tv ? translations.front().error : true);
        const bool pv = !physical.empty() && cycle >= physical.front().due;
        const uint64_t pa = pv ? physical.front().pa : 0;
        d.set_io$$physicalResponseValid(pv); d.set_io$$physicalResponseLow(memoryPair(pa));
        d.set_io$$physicalResponseHigh(0); d.set_io$$physicalErrors(memoryErrors(pa));
        d.set_io$$physicalPages(memoryPages(pa));
        d.step();
        check(bool(d.get_io$$idle()) == ledger.empty(), "idle/drain disagrees with accepted owner ledger");
        const bool take = offer && d.get_io$$virtualReady();
        const bool retire = vr && d.get_io$$virtualResponseValid();
        if (d.get_io$$translationValid()) {
            check(!ledger.empty(), "unowned translation offer");
            auto& o = ledger.front(); const auto& c = o.request;
            check(o.translations < translationCount(o), "duplicated or bypassed translation offer");
            const bool second = o.translations == 1;
            check(d.get_io$$translationPc() == c.va + (second ? 4 : 0) &&
                d.get_io$$translationRoot() == (o.root & ((1ULL << 44) - 1)) &&
                d.get_io$$translationAsid() == ((o.root >> 44) & 65535) &&
                d.get_io$$translationMode() == o.root >> 60 && d.get_io$$translationPrivilege() == c.privilege &&
                d.get_io$$translationSum() == o.sum && d.get_io$$translationMxr() == o.mxr &&
                d.get_io$$translationAccess() == 2, "captured translation context mixed between owners");
            if (tr) { translations.push_back({cycle + 2 + o.translations, second ? c.pa1 : c.pa0,
                second ? c.page1 : c.page0, second ? c.access1 : c.access0});
                ++o.translations; ++translationRequests; }
        }
        if (tv && d.get_io$$translationResponseReady()) {
            check(!ledger.empty(), "unowned translation response");
            ++ledger.front().translationReplies; translations.pop_front();
        }
        if (d.get_io$$physicalValid()) {
            check(!ledger.empty(), "unowned physical offer");
            auto& o = ledger.front();
            check(o.physical < o.expected.requests.size(), "extra physical request");
            const auto& request = o.expected.requests[o.physical];
            check(d.get_io$$physicalPc() == request.address && d.get_io$$physicalMask() == request.mask,
                "stream physical permission/address/mask mismatch");
            o.permissionOffered = true;
            if (pr) { physical.push_back({cycle + 3, request.address}); ++o.physical; ++physicalRequests; }
            else ++physicalHolds;
        }
        if (pv && d.get_io$$physicalResponseReady()) {
            check(!ledger.empty(), "unowned physical response");
            ++ledger.front().physicalReplies; physical.pop_front();
        }
        if (d.get_io$$virtualResponseValid()) {
            check(!ledger.empty(), "duplicated/stale virtual reply");
            auto& o = ledger.front();
            const auto& e = o.expected;
            const uint64_t observed = d.get_io$$virtualResponseLow() ^ uint64_t(negative && retired == 7);
            check(observed == e.low && d.get_io$$virtualResponseHigh() == e.high &&
                d.get_io$$virtualErrors() == e.errors && d.get_io$$virtualPages() == e.pages,
                "independent multi-owner response oracle mismatch");
            check(o.translations == translationCount(o) && o.translationReplies == o.translations &&
                o.physical == e.requests.size() && o.physicalReplies == o.physical,
                "reply lacks exact owned translation/physical handshakes");
            ++o.held;
            if (!vr) { ++responseHolds; check(!take, "new owner accepted while reply blocked"); }
        }
        if (retire) { ledger.pop_front(); ++retired; }
        if (take) { check(ledger.empty(), "more than one active transaction owner");
            ledger.push_back(next); ++accepted; simultaneous += retire; }
        if (retired == count) {
            check(ledger.empty() && translations.empty() && physical.empty(), "stream did not drain");
            if (++drainCycles == 5) break;
        }
    }
    check(accepted == count && retired == count && drainCycles == 5, "stream lost owner or failed to drain");
    check(responseHolds >= 3 * count && physicalHolds && churn && contextChurn, "stream backpressure coverage missing");
    check(FETCH_REPLY_TURNOVER ? simultaneous == count - 1 : simultaneous == 0,
        "simultaneous old-reply/new-owner witness differs from selected feature");
    std::cout << "GSIM instruction permission stream: PASS aligned=" << ALIGNED_PACKET
        << " turnover=" << FETCH_REPLY_TURNOVER << " identity=" << FETCH_IDENTITY_TRANSLATION
        << " accepted=" << accepted << " retired=" << retired << " simultaneous=" << simultaneous
        << " translationRequests=" << translationRequests << " physicalRequests=" << physicalRequests
        << " responseHolds=" << responseHolds << " physicalHolds=" << physicalHolds
        << " livePmpChurn=" << churn << " liveContextChurn=" << contextChurn << " resetEpochs=2 drainCycles=" << drainCycles << '\n';
}
}
int main(int argc, char** argv) { try {
    check(argc == 1 || (argc == 2 && std::string_view(argv[1]) == "--inject-mismatch"), "unknown stream argument");
    stream::run(argc == 2); return 0;
} catch (const std::exception& error) {
    std::cerr << "GSIM instruction permission stream: FAIL " << error.what() << '\n'; return 1;
} }
