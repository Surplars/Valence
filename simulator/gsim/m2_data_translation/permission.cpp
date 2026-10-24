#include "M2DataPermissionGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

// Independent byte-range and raw PMP oracle, not a copy of the Chisel helpers.
using Wide = unsigned __int128;
static constexpr uint64_t ram = 0x80200000ULL, ramBytes = 1ULL << 31;
static void need(bool b, const std::string &why) { if (!b) throw std::runtime_error(why); }
struct Region { unsigned cfg = 0; uint64_t addr = 0; };
struct Request {
    uint64_t address = ram, data = 0x13579bdf2468ace0ULL;
    unsigned size = 3, mask = 255, op = 0;
    bool write = true, atomic = false, virt = false, prechecked = false, uncached = false;
    uint32_t epoch = 17;
};
struct Case {
    Request request, hint;
    std::array<Region, 16> pmp{};
    unsigned privilege = 1, hintPrivilege = 1, index = 5;
    uint64_t va = 0x40000000, tag = 0xfedcba9876543210ULL;
    uint32_t epoch = 17, originEpoch = 17;
    bool stable = true, changing = false, flush = false, origin = true;
    bool check = true, page = false, access = false, hintBypass = false;
    Case() { pmp[0] = {0x1f, (1ULL << 54) - 1}; hint = request; }
};
static bool inRam(const Request &r) {
    return Wide(r.address) >= ram && Wide(r.address) + (1u << r.size) <= Wide(ram) + ramBytes;
}
static bool denied(const std::array<Region, 16> &pmp, uint64_t address, unsigned size,
                   unsigned privilege, unsigned access) {
    const Wide first = address, last = first + (1ULL << size) - 1;
    for (unsigned i = 0; i < pmp.size(); ++i) {
        const auto &e = pmp[i]; const unsigned mode = (e.cfg >> 3) & 3;
        if (!mode) continue;
        Wide low = Wide(e.addr) * 4, end = low + 4;
        if (mode == 1) { low = i ? Wide(pmp[i-1].addr) * 4 : 0; end = Wide(e.addr) * 4; }
        if (mode == 3) {
            // A raw all-ones entry covers the implemented 56-bit PA domain.
            const uint64_t mask = (((e.addr ^ (e.addr + 1)) << 2) | 3) & ((1ULL << 56) - 1);
            low = (e.addr << 2) & ~mask; end = low + mask + 1;
        }
        if (end <= low || last < low || first >= end) continue;
        bool everyByte = true;
        for (unsigned n = 0; n < (1u << size); ++n)
            everyByte &= first + n >= low && first + n < end;
        const bool permission = access == 0 ? e.cfg & 1 : access == 1 ? e.cfg & 2 : (e.cfg & 3) == 3;
        return !everyByte || !((privilege == 3 && !(e.cfg & 128)) || permission);
    }
    return privilege != 3;
}
static unsigned lanes(const Request &r) {
    unsigned result = 0;
    for (unsigned n = 0; n < (1u << r.size); ++n)
        if ((r.address % 8) + n < 8) result |= 1u << ((r.address % 8) + n);
    return result;
}
static bool aligned(uint64_t address, unsigned size) { return address % (1u << size) == 0; }
struct Truth { bool fault, pmp, next, canonical; unsigned access; };
static Truth oracle(const Case &c) {
    const auto &r = c.request;
    Truth t{};
    t.access = r.atomic ? (r.op == 2 ? 0 : r.op == 3 ? 1 : 3) : (r.write ? 1 : 0);
    t.pmp = denied(c.pmp, r.address, r.size, c.privilege, t.access);
    t.fault = c.page || c.access || (c.check && t.pmp) || (r.atomic && c.check && !inRam(r)) ||
        (r.prechecked && (r.epoch != c.epoch || c.changing || c.flush || !inRam(r)));
    t.canonical = c.origin && r.write && !r.atomic && !r.virt && !r.prechecked && !r.uncached && c.check &&
        aligned(c.va, r.size) && aligned(r.address, r.size) && c.va % 4096 == r.address % 4096 &&
        r.mask == lanes(r) && inRam(r) && c.stable && !c.changing && !c.flush &&
        c.originEpoch == c.epoch && !t.fault && !t.pmp;
    const auto &h = c.hint;
    const uint64_t next = (h.address & ~63ULL) + 64;
    // Selected enables load next-line prefetch, but not store next-line prefetch.
    t.next = (!t.fault || c.hintBypass) && !h.write && !h.atomic && !h.uncached && !h.virt && inRam(h) &&
        h.address % 4096 < 4032 && Wide(next) >= ram && Wide(next) + 64 <= Wide(ram) + ramBytes &&
        !denied(c.pmp, next, 6, c.hintPrivilege, 0);
    return t;
}
static void drive(SM2DataPermissionGsim &d, const Case &c) {
    const auto &r = c.request; const auto &h = c.hint;
#define REQ(prefix, x) \
    d.set_io$$##prefix##$$atomic(x.atomic); d.set_io$$##prefix##$$atomicOp(x.op); \
    d.set_io$$##prefix##$$address(x.address); d.set_io$$##prefix##$$write(x.write); \
    d.set_io$$##prefix##$$size(x.size); d.set_io$$##prefix##$$data(x.data); \
    d.set_io$$##prefix##$$mask(x.mask); d.set_io$$##prefix##$$virtualized(x.virt); \
    d.set_io$$##prefix##$$precheckedLoad(x.prechecked); d.set_io$$##prefix##$$translationEpoch(x.epoch); \
    d.set_io$$##prefix##$$prefetchNextAllowed(1); d.set_io$$##prefix##$$uncached(x.uncached)
    REQ(result$$request, r); REQ(hintRequest, h);
#undef REQ
    d.set_io$$result$$canonicalStoreOrigin$$valid(c.origin);
    d.set_io$$result$$canonicalStoreOrigin$$bits$$token$$index(c.index);
    d.set_io$$result$$canonicalStoreOrigin$$bits$$token$$tag(c.tag);
    d.set_io$$result$$canonicalStoreOrigin$$bits$$epoch(c.originEpoch);
    d.set_io$$result$$originalVirtualAddress(c.va); d.set_io$$result$$privilege(c.privilege);
    d.set_io$$result$$checkPhysical(c.check); d.set_io$$result$$pageFault(c.page); d.set_io$$result$$accessFault(c.access);
    d.set_io$$authorization$$epoch(c.epoch); d.set_io$$authorization$$stable(c.stable);
    d.set_io$$authorization$$changing(c.changing); d.set_io$$authorization$$flush(c.flush);
    d.set_io$$hintPrivilege(c.hintPrivilege); d.set_io$$hintBypassFault(c.hintBypass);
#define PMP(n) d.set_io$$cfg##n(c.pmp[n].cfg); d.set_io$$addr##n(c.pmp[n].addr)
    PMP(0); PMP(1); PMP(2); PMP(3); PMP(4); PMP(5); PMP(6); PMP(7);
    PMP(8); PMP(9); PMP(10); PMP(11); PMP(12); PMP(13); PMP(14); PMP(15);
#undef PMP
}
static uint64_t randomWord(uint64_t &x) { x ^= x << 13; x ^= x >> 7; x ^= x << 17; return x; }
int main(int argc, char **argv) { try {
    SM2DataPermissionGsim d; Case init; drive(d, init); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    const std::string mode = argc > 1 ? argv[1] : "";
    need(mode.empty() || mode == "--inject-permission" || mode == "--inject-certificate", "unknown option");
    unsigned cases = 0, faults = 0, certificates = 0, hints = 0, atomics = 0, mmio = 0, stale = 0;
    bool injected = false;
    auto run = [&](Case c) {
        const auto t = oracle(c); drive(d, c); d.step();
        bool fault = d.get_io$$fault();
        if (!injected && mode == "--inject-permission" && t.fault) {
            fault = !fault; injected = true; std::cout << "INJECT M2_PERMISSION fault observation\n";
        }
        need(fault == t.fault && bool(d.get_io$$pmpDenied()) == t.pmp && d.get_io$$access() == t.access,
            "permission fault/PMP/access differs from independent byte oracle at case " + std::to_string(cases));
        need(bool(d.get_io$$nextAllowed()) == t.next, "independent next-line read authorization mismatch at case " + std::to_string(cases));
        need(bool(d.get_io$$canonical$$valid()) == t.canonical, "canonical qualification mismatch at case " + std::to_string(cases));
        if (t.canonical) {
            uint64_t pa = d.get_io$$canonical$$bits$$physicalAddress();
            if (!injected && mode == "--inject-certificate") {
                pa ^= 1ULL << 40; injected = true; std::cout << "INJECT M2_PERMISSION certificate PA observation\n";
            }
            need(pa == c.request.address && d.get_io$$canonical$$bits$$virtualAddress() == c.va &&
                d.get_io$$canonical$$bits$$origin$$token$$index() == c.index &&
                d.get_io$$canonical$$bits$$origin$$token$$tag() == c.tag &&
                d.get_io$$canonical$$bits$$origin$$epoch() == c.originEpoch &&
                d.get_io$$canonical$$bits$$size() == c.request.size && d.get_io$$canonical$$bits$$mask() == c.request.mask,
                "canonical descriptor owner/token/epoch/payload mismatch");
        }
        ++cases; faults += t.fault; certificates += t.canonical; hints += t.next;
        atomics += c.request.atomic; mmio += !inRam(c.request); stale += c.request.prechecked && c.request.epoch != c.epoch;
    };
    run(Case{});
    for (unsigned op : {0u, 1u, 2u, 3u, 4u, 8u, 12u, 16u, 20u, 24u, 28u})
        for (unsigned cfg : {0x18u, 0x19u, 0x1au, 0x1bu, 0x98u, 0x99u, 0x9au, 0x9bu})
            for (unsigned priv : {0u, 1u, 3u}) {
                Case c; c.request.atomic = true; c.request.op = op; c.privilege = priv; c.pmp[0].cfg = cfg; run(c);
                c.request.address = 0x10000000; c.va = c.request.address; run(c);
            }
    for (unsigned kind = 0; kind < 14; ++kind) {
        Case c;
        if (kind == 0) c.page = true;
        if (kind == 1) c.access = true;
        if (kind == 2) c.originEpoch--;
        if (kind == 3) c.stable = false;
        if (kind == 4) c.flush = true;
        if (kind == 5) c.changing = true;
        if (kind == 6) c.request.prechecked = true, c.request.epoch--;
        if (kind == 7) c.request.address = ram + ramBytes - 4;
        if (kind == 8) c.request.address |= 1ULL << 48;
        if (kind == 9) c.va += 1;
        if (kind == 10) c.request.mask = 15;
        if (kind == 11) c.request.uncached = true;
        if (kind == 12) c.request.virt = true;
        if (kind == 13) c.request.address = 0x10000000;
        run(c);
    }
    // A full captured owner context matters: no matching PMP permits M, not S/U.
    for (unsigned privilege : {0u, 1u, 3u}) { Case c; c.pmp = {}; c.privilege = privilege; run(c); }
    // First-overlap partial TOR coverage denies even M/unlocked; later permissive entries cannot repair it.
    for (unsigned privilege : {0u, 1u, 3u}) {
        Case c; c.pmp[0] = {0, ram / 4}; c.pmp[1] = {0x0b, (ram + 4) / 4};
        c.pmp[2] = {0x1f, (1ULL << 54) - 1}; c.privilege = privilege; run(c);
    }
    for (uint64_t address : {ram, ram + 4024, ram + 4032, ram + ramBytes - 64})
        for (bool fault : {false, true}) for (bool bypass : {false, true}) {
            Case c; c.hint.address = address; c.hint.write = false; c.page = fault; c.hintBypass = bypass; run(c);
        }
    uint64_t rng = 0x914ed7aca6935f0bULL;
    for (unsigned n = 0; n < 4096; ++n) {
        Case c;
        c.request.size = randomWord(rng) % 4;
        c.request.address = ram + randomWord(rng) % 8192;
        if (n % 3) c.request.address &= ~((1ULL << c.request.size) - 1);
        c.va += c.request.address % 4096; c.request.mask = lanes(c.request);
        c.request.write = randomWord(rng) & 1; c.request.atomic = n % 13 == 0;
        c.request.op = randomWord(rng) % 32; c.request.uncached = n % 17 == 0;
        c.request.prechecked = n % 19 == 0; c.request.epoch -= n % 2;
        c.originEpoch -= n % 7 == 0; c.tag = randomWord(rng); c.index = randomWord(rng) % 16;
        c.privilege = std::array<unsigned,3>{0,1,3}[n % 3]; c.hintPrivilege = c.privilege;
        c.hint = c.request; c.hint.write = false; c.hint.atomic = false;
        if (n % 5 == 0) c.pmp = {};
        if (n % 5 == 1) c.pmp[0].cfg = (randomWord(rng) & 0x87) | 0x18;
        if (n % 5 >= 2) {
            c.pmp = {};
            for (unsigned i = 0; i < 16; ++i) {
                c.pmp[i].addr = (ram + (randomWord(rng) % 8320)) / 4;
                c.pmp[i].cfg = (randomWord(rng) & 0x87) | ((1 + randomWord(rng) % 3) << 3);
            }
        }
        run(c);
    }
    need(mode.empty() || injected, "negative observation was not reached");
    need(certificates > 20 && faults > 100 && hints > 20 && atomics > 300 && mmio && stale,
        "permission coverage was vacuous");
    std::cout << "M2_PERMISSION_PASS cases=" << cases << " faults=" << faults << " canonical=" << certificates
              << " next=" << hints << " atomics=" << atomics << " outside_ram=" << mmio << " stale=" << stale << '\n';
    return 0;
} catch (const std::exception &e) { std::cerr << "M2_PERMISSION_FAIL " << e.what() << '\n'; return 1; } }
