#include "InstructionPermissionGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string_view>
#include <vector>
#ifndef PACKET_WORDS
#define PACKET_WORDS 2
#endif
#ifndef RETIMED_PERMISSIONS
#define RETIMED_PERMISSIONS 1
#endif
#ifndef ALIGNED_PACKET
#define ALIGNED_PACKET 0
#endif
static void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
using Wide = unsigned __int128;
static constexpr unsigned wordMask = (1U << PACKET_WORDS) - 1;
static constexpr uint64_t addrMax = (uint64_t(1) << 54) - 1;
static constexpr uint64_t satp = 0x8012300000001234ULL;
struct Case {
    uint64_t va = 0x40000000ULL, pa0 = 0x80000010ULL, pa1 = 0x90001000ULL;
    unsigned mask = wordMask, privilege = 1;
    std::array<unsigned, 2> cfg{0x0c, 0};
    std::array<uint64_t, 2> addr{addrMax, 0};
    bool page0 = false, access0 = false, page1 = false, access1 = false, mutateHeld = false;
    bool mutateBeforeOffer = false;
    unsigned delay = 0, stall = 0;
};
// Independent byte-range PMP oracle. The fixture has two architectural
// entries; the remaining fourteen are OFF. Never read DUT decoded ranges.
static bool permitted(const Case& c, uint64_t address) {
    const Wide start = address, end = Wide(address) + 3;
    for (unsigned entry = 0; entry < 2; ++entry) {
        const unsigned mode = (c.cfg[entry] >> 3) & 3;
        if (!mode) continue;
        Wide lo = 0, hi = 0;
        if (mode == 1) {
            lo = entry ? Wide(c.addr[entry - 1]) * 4 : 0;
            hi = Wide(c.addr[entry]) * 4;
        } else if (mode == 2) {
            lo = Wide(c.addr[entry]) * 4; hi = lo + 4;
        } else {
            unsigned trailing = 0;
            while (trailing < 54 && ((c.addr[entry] >> trailing) & 1)) ++trailing;
            const Wide length = Wide(1) << (trailing + 3);
            lo = (Wide(c.addr[entry]) * 4) & ~(length - 1); hi = lo + length;
        }
        if (hi <= lo || start >= hi || end < lo) continue;
        const bool covers = start >= lo && end < hi;
        const bool permission = (c.privilege == 3 && !(c.cfg[entry] & 128)) || (c.cfg[entry] & 4);
        return covers && permission; // first overlapping entry owns the decision
    }
    return c.privilege == 3;
}
static uint32_t memoryWord(uint64_t address) { return 0xa5000000U ^ uint32_t(address >> 2); }
static uint64_t memoryPair(uint64_t address) {
    return uint64_t(memoryWord(address)) | (uint64_t(memoryWord(address + 4)) << 32);
}
static unsigned memoryErrors(uint64_t address) {
    unsigned errors = 0;
    for (unsigned word = 0; word < PACKET_WORDS; ++word)
        errors |= unsigned(((address + 4 * word) >> 2 & 15) == 5) << word;
    return errors;
}
static unsigned memoryPages(uint64_t address) {
    unsigned pages = 0;
    for (unsigned word = 0; word < PACKET_WORDS; ++word)
        pages |= unsigned(((address + 4 * word) >> 2 & 15) == 9) << word;
    return pages;
}
struct Request { uint64_t address; unsigned mask; bool second; };
struct Expected {
    bool crosses = false;
    unsigned errors = PACKET_WORDS == 4 ? wordMask : 0, pages = 0, allowed = 0;
    uint64_t low = 0, high = 0;
    std::vector<Request> requests;
};
static Expected oracle(const Case& c) {
    Expected e;
    e.crosses = PACKET_WORDS == 2 && (c.va & 4095) == 4092 && (c.mask & 2);
    e.errors = PACKET_WORDS == 4 ? ((~c.mask) & wordMask) : 0;
    if (c.page0) { e.pages = c.mask; return e; }
    if (c.access0) { e.errors = PACKET_WORDS == 4 ? wordMask : c.mask; return e; }
    if (!c.mask) return e;
    for (unsigned word = 0; word < PACKET_WORDS; ++word) {
        const unsigned bit = 1U << word;
        if (!(c.mask & bit)) continue;
        if (e.crosses && word == 1 && c.page1) { e.pages |= bit; continue; }
        if (e.crosses && word == 1 && c.access1) { e.errors |= bit; continue; }
        const uint64_t pa = e.crosses && word == 1 ? c.pa1 : c.pa0 + 4 * word;
        if (permitted(c, pa)) e.allowed |= bit;
        else e.errors |= bit;
    }
    if (e.crosses) {
        if (e.allowed & 1) e.requests.push_back({c.pa0, 1, false});
        if (e.allowed & 2) e.requests.push_back({c.pa1, 1, true});
    } else if (e.allowed) e.requests.push_back({c.pa0, e.allowed, false});
    for (const auto& request : e.requests) {
        if (request.second) {
            e.low = (e.low & 0xffffffffULL) | (uint64_t(memoryWord(request.address)) << 32);
            e.errors |= (memoryErrors(request.address) & 1) << 1;
            e.pages |= (memoryPages(request.address) & 1) << 1;
        } else {
            e.low = memoryPair(request.address);
            if (PACKET_WORDS == 4) e.high = memoryPair(request.address + 8);
            e.errors |= memoryErrors(request.address) & (PACKET_WORDS == 4 ? wordMask : request.mask);
            e.pages |= memoryPages(request.address) & (PACKET_WORDS == 4 ? wordMask : request.mask);
        }
    }
    return e;
}
struct Stats {
    unsigned cases = 0, normalLaunch = 0, partialLaunch = 0, allRejected = 0;
    unsigned cross = 0, secondOnly = 0, translationFault = 0, delayed = 0, held = 0, heldChanges = 0;
    unsigned responseHeld = 0, faultExtraCycle = 0, beforeOfferChanges = 0;
};
static Stats stats;
static bool inject = false;
static void runCase(const Case& c) {
    // An artificial pre-offer CSR change demonstrates the declared sampling
    // point. Real software CSR writes must first drain this active adapter.
    // Legacy samples on translation reply; retimed samples on first offer.
    auto permissionCase = c;
    if (c.mutateBeforeOffer && RETIMED_PERMISSIONS) {
        permissionCase.cfg = {0x08, 0}; permissionCase.addr = {addrMax, 0};
    }
    const auto wanted = oracle(permissionCase);
    SInstructionPermissionGsim d;
    unsigned cycle = 0;
    auto tick = [&]() { d.step(); return cycle++; };
    auto pmp = [&](bool denyAll) {
        d.set_io$$cfg0(denyAll ? 0x08 : c.cfg[0]); d.set_io$$cfg1(denyAll ? 0 : c.cfg[1]);
        d.set_io$$addr0(denyAll ? addrMax : c.addr[0]); d.set_io$$addr1(denyAll ? 0 : c.addr[1]);
    };
    d.set_io$$virtualValid(0); d.set_io$$virtualPc(c.va); d.set_io$$virtualMask(c.mask);
    d.set_io$$virtualResponseReady(0); d.set_io$$satp(satp); d.set_io$$sum(1); d.set_io$$mxr(0);
    d.set_io$$privilege(c.privilege); pmp(false);
    d.set_io$$translationReady(0); d.set_io$$translationResponseValid(0);
    d.set_io$$translationPhysical(0xdeadbeef); // deliberately unaligned INVALID payload
    d.set_io$$translationPage(0); d.set_io$$translationError(0);
    d.set_io$$physicalReady(0); d.set_io$$physicalResponseValid(0);
    d.set_io$$physicalResponseLow(0); d.set_io$$physicalResponseHigh(0);
    d.set_io$$physicalErrors(0); d.set_io$$physicalPages(0);
    d.set_reset(1); tick(); tick(); d.set_reset(0); cycle = 0;
    d.set_io$$virtualValid(1); tick();
    check(d.get_io$$virtualReady() && d.get_io$$idle(), "fixture virtual request was not accepted");
    d.set_io$$virtualValid(0);
    // Mutating the live request and VM context cannot change the accepted owner.
    d.set_io$$virtualPc(c.va ^ (uint64_t(1) << 63)); d.set_io$$virtualMask(0);
    d.set_io$$satp(0); d.set_io$$sum(0); d.set_io$$mxr(1); d.set_io$$privilege(0);
    auto checkTranslation = [&](bool second) {
        check(d.get_io$$translationValid() && d.get_io$$translationPc() == c.va + (second ? 4 : 0) &&
            d.get_io$$translationRoot() == (satp & ((uint64_t(1) << 44) - 1)) &&
            d.get_io$$translationAsid() == ((satp >> 44) & 65535) &&
            d.get_io$$translationMode() == (satp >> 60) &&
            d.get_io$$translationPrivilege() == c.privilege && d.get_io$$translationAccess() == 2 &&
            d.get_io$$translationSum() && !d.get_io$$translationMxr(),
            "accepted translation owner/context changed");
        check(!d.get_io$$physicalValid() && !d.get_io$$virtualReady() && !d.get_io$$idle(),
            "translation escaped its drain boundary");
    };
    auto translation = [&](bool second) {
        for (unsigned stalled = 0; stalled < 2; ++stalled) {
            tick(); checkTranslation(second);
        }
        d.set_io$$translationReady(1);
        d.set_io$$translationResponseValid(c.delay == 0);
        d.set_io$$translationPhysical(second ? c.pa1 : c.pa0);
        d.set_io$$translationPage(second ? c.page1 : c.page0);
        d.set_io$$translationError(second ? c.access1 : c.access0);
        unsigned responseCycle = tick(); checkTranslation(second);
        check(d.get_io$$translationResponseReady(), "translation response not owned");
        if (c.delay) {
            d.set_io$$translationReady(0);
            for (unsigned delayed = 0; delayed < c.delay; ++delayed) {
                tick(); check(!d.get_io$$translationValid() && !d.get_io$$physicalValid(),
                    "translation request duplicated while waiting");
            }
            d.set_io$$translationResponseValid(1);
            responseCycle = tick();
            check(d.get_io$$translationResponseReady(), "delayed translation response not owned");
            ++stats.delayed;
        }
        d.set_io$$translationResponseValid(0); d.set_io$$translationReady(0);
        d.set_io$$translationPhysical(0xdeadbeef); d.set_io$$translationPage(1); d.set_io$$translationError(1);
        return responseCycle;
    };
    unsigned lastTranslation = translation(false);
    if (wanted.crosses && !c.page0 && !c.access0) lastTranslation = translation(true);
    if (c.mutateBeforeOffer) { pmp(true); ++stats.beforeOfferChanges; }
    for (unsigned index = 0; index < wanted.requests.size(); ++index) {
        const auto& request = wanted.requests[index];
        d.set_io$$physicalReady(0);
        const unsigned offeredCycle = tick();
        auto checkOffer = [&]() {
            check(d.get_io$$physicalValid() && d.get_io$$physicalPc() == request.address &&
                d.get_io$$physicalMask() == request.mask, "independent physical permission/request oracle mismatch");
            check(!d.get_io$$idle() && !d.get_io$$virtualReady() && !d.get_io$$virtualResponseValid(),
                "physical request escaped its drain boundary");
        };
        checkOffer();
        if (!index) {
            check(offeredCycle == lastTranslation + 1, "permission retiming added a successful launch cycle");
            ++stats.normalLaunch;
            stats.partialLaunch += wanted.allowed != c.mask;
        }
        if (c.mutateHeld) { pmp(true); ++stats.heldChanges; }
        for (unsigned stalled = 0; stalled < c.stall; ++stalled) {
            tick(); checkOffer(); ++stats.held;
        }
        d.set_io$$physicalReady(1); tick(); checkOffer();
        d.set_io$$physicalReady(0);
        for (unsigned wait = 0; wait < 2; ++wait) {
            tick();
            check(d.get_io$$physicalResponseReady() && !d.get_io$$physicalValid(),
                "physical completion owner was not retained");
        }
        d.set_io$$physicalResponseValid(1);
        d.set_io$$physicalResponseLow(memoryPair(request.address));
        d.set_io$$physicalResponseHigh(memoryPair(request.address + 8));
        d.set_io$$physicalErrors(memoryErrors(request.address));
        d.set_io$$physicalPages(memoryPages(request.address));
        tick(); check(d.get_io$$physicalResponseReady(), "physical response was not accepted");
        d.set_io$$physicalResponseValid(0);
    }
    unsigned responseCycle = 0;
    bool foundResponse = false;
    auto checkResponse = [&]() {
        unsigned actualErrors = d.get_io$$virtualErrors();
        if (inject && stats.cases == 10) actualErrors ^= 1;
        check(d.get_io$$virtualResponseValid() && actualErrors == wanted.errors &&
            d.get_io$$virtualPages() == wanted.pages && d.get_io$$virtualResponseLow() == wanted.low &&
            d.get_io$$virtualResponseHigh() == wanted.high,
            "independent I-fetch permission oracle mismatch");
        check(!d.get_io$$idle() && !d.get_io$$virtualReady() && !d.get_io$$physicalValid(),
            "reply escaped its drain boundary");
    };
    for (unsigned waiting = 0; waiting < 8; ++waiting) {
        responseCycle = tick();
        check(!d.get_io$$physicalValid(), "unauthorized extra physical request");
        if (d.get_io$$virtualResponseValid()) { checkResponse(); foundResponse = true; break; }
    }
    check(foundResponse, "instruction permission response missing");
    if (wanted.requests.empty()) {
        const bool permissionReject = !c.page0 && !c.access0 && c.mask;
        const unsigned extra = RETIMED_PERMISSIONS && permissionReject ? 1 : 0;
        check(responseCycle == lastTranslation + 1 + extra,
            "permission fault latency differs from the explicit retiming contract");
        stats.faultExtraCycle += extra; ++stats.allRejected;
    }
    for (unsigned stalled = 0; stalled < 3; ++stalled) { tick(); checkResponse(); ++stats.responseHeld; }
    d.set_io$$virtualResponseReady(1); tick(); checkResponse();
    d.set_io$$virtualResponseReady(0); tick();
    check(d.get_io$$idle() && d.get_io$$virtualReady() && !d.get_io$$virtualResponseValid(),
        "completed instruction owner did not drain");
    ++stats.cases; stats.cross += wanted.crosses;
    stats.secondOnly += wanted.requests.size() == 1 && wanted.requests[0].second;
    stats.translationFault += c.page0 || c.access0 || (wanted.crosses && (c.page1 || c.access1));
}
int main(int argc, char** argv) { try {
    check(argc == 1 || (argc == 2 && std::string_view(argv[1]) == "--inject-mismatch"), "unknown permission argument");
    inject = argc == 2;
    for (unsigned mask = 0; mask <= wordMask; ++mask) for (unsigned kind = 0; kind < 6; ++kind) {
        Case c; c.mask = mask; c.delay = kind % 3; c.stall = 3; c.mutateHeld = true;
        if (kind == 1) { c.cfg = {0x10, 0x0c}; c.addr = {c.pa0 / 4, addrMax}; } // deny first, permit later
        if (kind == 2) { c.cfg = {0x14, 0x08}; c.addr = {c.pa0 / 4, addrMax}; } // permit first only
        if (kind == 3) c.cfg[0] = 0x08; // all execute denied
        if (kind == 4) { c.privilege = 3; c.cfg[0] = 0x08; } // unlocked M bypass
        if (kind == 5) { c.privilege = 3; c.cfg[0] = 0x88; } // locked M deny
        runCase(c);
    }
    for (bool page : {false, true}) {
        Case c; c.page0 = page; c.access0 = true; c.pa0 = 0xdeadbeef; c.delay = 2; runCase(c);
    }
    Case high; high.va = UINT64_MAX - (PACKET_WORDS * 4 - 1); high.pa0 = 0x80000000ULL + (high.va & 4095);
    high.stall = 3; high.mutateHeld = true; runCase(high);
    Case permissionSampling; permissionSampling.mutateBeforeOffer = true; runCase(permissionSampling);
    if (PACKET_WORDS == 2 && !ALIGNED_PACKET) {
        for (unsigned kind = 0; kind < 8; ++kind) for (unsigned mask : {2U, 3U}) {
            Case c; c.va = 0x40000ffcULL; c.pa0 = 0x80000ffcULL; c.pa1 = 0x90001000ULL;
            c.mask = mask; c.delay = kind % 3; c.stall = 3; c.mutateHeld = true;
            if (kind == 1 || kind == 3 || kind == 5) { c.cfg = {0x10, 0x0c}; c.addr = {c.pa0 / 4, addrMax}; }
            if (kind == 2 || kind == 3) { c.page1 = true; c.pa1 = 0xdeadbeef; }
            if (kind == 4 || kind == 5) { c.access1 = true; c.pa1 = 0xdeadbeef; }
            if (kind == 6) c.cfg[0] = 0x08;
            if (kind == 7) c.va = UINT64_MAX - 3; // second VA must wrap to zero, PA need not be contiguous
            runCase(c);
        }
    }
    check(stats.normalLaunch && stats.partialLaunch && stats.allRejected && stats.translationFault &&
        stats.delayed && stats.held && stats.heldChanges && stats.responseHeld && stats.beforeOfferChanges,
        "instruction permission coverage incomplete");
    if (PACKET_WORDS == 2 && !ALIGNED_PACKET)
        check(stats.cross && stats.secondOnly, "cross-page independent PA coverage missing");
    if (RETIMED_PERMISSIONS) check(stats.faultExtraCycle, "retimed all-denied fault-cycle coverage missing");
    std::cout << "GSIM instruction permission: PASS words=" << PACKET_WORDS
        << " retimed=" << RETIMED_PERMISSIONS << " aligned=" << ALIGNED_PACKET << " cases=" << stats.cases
        << " normalLaunch=" << stats.normalLaunch << " partialLaunch=" << stats.partialLaunch
        << " allRejected=" << stats.allRejected << " crossPage=" << stats.cross << " secondOnly=" << stats.secondOnly
        << " translationFault=" << stats.translationFault << " delayed=" << stats.delayed
        << " held=" << stats.held << " heldPmpChanges=" << stats.heldChanges
        << " responseHeld=" << stats.responseHeld << " faultExtraCycles=" << stats.faultExtraCycle
        << " preOfferPmpChanges=" << stats.beforeOfferChanges << '\n';
    return 0;
} catch (const std::exception& error) {
    std::cerr << "GSIM instruction permission: FAIL " << error.what() << '\n'; return 1;
} }
