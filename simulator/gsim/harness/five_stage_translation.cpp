#include "FiveStageTranslationHarness.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <map>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
static void need(bool ok, const char *s) { if (!ok) throw std::runtime_error(s); }
static constexpr uint64_t ROOT = 0x80020000, L1 = 0x80021000, L0 = 0x80022000, VA = 0x40000000;
#ifdef I1_INSTRUCTION_TRANSLATION
static constexpr bool INSTRUCTION = true;
#else
static constexpr bool INSTRUCTION = false;
#endif
static uint64_t pte(uint64_t pa, unsigned flags) { return (pa >> 12 << 10) | flags; }
static uint64_t pattern(uint64_t pa) { return (pa & ~7ULL) * 0x9e3779b97f4a7c15ULL ^ 0xc0011234abcdfed0ULL; }
struct Expected { uint64_t pa = 0; bool error = false, page = false; };
struct Test {
    SFiveStageTranslationHarness d;
    std::map<uint64_t, uint64_t> memory;
    struct Pending { uint64_t address, due; bool error; };
    std::optional<Pending> walk, physical;
    std::optional<std::array<uint64_t, 4>> heldWalk;
    std::optional<std::array<uint64_t, 5>> heldPhysical;
    std::optional<uint64_t> expectedPhysicalAddress;
    bool explicitNoAllocate = false, wrongPma = false, readAhead = false;
    uint64_t offeredVa = 0, candidateSelectMask = 0, candidateNoiseChanges = 0;
    struct Request {
        uint64_t address=0, data=0x12345678, mask=255;
        unsigned size=3, operation=0;
        bool write=false, noAllocate=false, atomic=false;
    } offeredRequest;
    std::optional<std::array<uint64_t, 3>> heldResponse;
    uint64_t cycle = 0, cases = 0, walks = 0, requests = 0, hits = 0, preparedPayloadCycles = 0;
    uint64_t top = 0x90000000, injectAddress = ~0ULL;
    unsigned privilege = 1, dataPrivilege = 1, pmpConfig = 15; bool sum = false, mxr = false;
    uint64_t satp = (8ULL << 60) | (ROOT >> 12);
    std::mt19937_64 random{0x533339};
    Test() {
        d.set_reset(1); d.set_io$$request$$valid(0); d.set_io$$response$$ready(0);
        d.set_io$$physicalResponse$$valid(0); d.set_io$$walkResponse$$valid(0);
        d.set_io$$invalidate(0); inputs(); d.step(); d.step(); d.set_reset(0);
    }
    void request(uint64_t address, bool write, unsigned size, bool noAllocate=false, int atomic=-1) {
        offeredVa = address;
        offeredRequest = {address, 0x12345678, 255, size, unsigned(atomic >= 0 ? atomic : 0),
            write, noAllocate, atomic >= 0};
        d.set_io$$request$$bits$$address(address); d.set_io$$request$$bits$$write(write);
        d.set_io$$request$$bits$$size(size); d.set_io$$request$$bits$$data(offeredRequest.data);
        d.set_io$$request$$bits$$mask(offeredRequest.mask); d.set_io$$request$$bits$$noAllocate(noAllocate);
        d.set_io$$request$$bits$$atomic(atomic >= 0);
        d.set_io$$request$$bits$$atomicOperation(atomic >= 0 ? atomic : 0);
    }
    void inputs() {
#ifdef I1_DATA_REPLY_HANDOFF
        d.set_io$$readAhead(readAhead);
#endif
#ifdef I1_SPLIT_INSTRUCTION_CANDIDATES
        const bool second = cases & 1;
        const uint64_t noise = 0xdead000040000000ULL ^ (cycle * 0x9e3779b97f4a7c15ULL);
        d.set_io$$candidate0(second ? noise : offeredVa);
        d.set_io$$candidate1(second ? offeredVa : noise);
        d.set_io$$candidateSecond(second);
        candidateSelectMask |= 1ULL << second;
        ++candidateNoiseChanges;
#endif
#ifdef I1_SPLIT_DATA_CANDIDATES
        const bool early = cases & 1;
        const uint64_t noise = 0xbeef000040000000ULL ^ (cycle * 0x9e3779b97f4a7c15ULL);
        const Request other{noise, noise ^ 0x7355, noise & 255, unsigned(cycle & 3),
            unsigned(cycle & 31), bool(cycle & 1), bool(cycle & 2), bool(cycle & 4)};
        const auto &a = early ? other : offeredRequest;
        const auto &b = early ? offeredRequest : other;
        d.set_io$$dataCandidateEarly(early);
        d.set_io$$dataCandidate0$$address(a.address); d.set_io$$dataCandidate1$$address(b.address);
        d.set_io$$dataCandidate0$$data(a.data); d.set_io$$dataCandidate1$$data(b.data);
        d.set_io$$dataCandidate0$$mask(a.mask); d.set_io$$dataCandidate1$$mask(b.mask);
        d.set_io$$dataCandidate0$$size(a.size); d.set_io$$dataCandidate1$$size(b.size);
        d.set_io$$dataCandidate0$$write(a.write); d.set_io$$dataCandidate1$$write(b.write);
        d.set_io$$dataCandidate0$$noAllocate(a.noAllocate); d.set_io$$dataCandidate1$$noAllocate(b.noAllocate);
        d.set_io$$dataCandidate0$$atomic(a.atomic); d.set_io$$dataCandidate1$$atomic(b.atomic);
        d.set_io$$dataCandidate0$$atomicOperation(a.operation); d.set_io$$dataCandidate1$$atomicOperation(b.operation);
        candidateSelectMask |= 1ULL << early; ++candidateNoiseChanges;
#endif
        d.set_io$$privilege(privilege); d.set_io$$dataPrivilege(dataPrivilege);
        d.set_io$$sum(sum); d.set_io$$mxr(mxr); d.set_io$$satp(satp);
        d.set_io$$pmpTop(top >> 2); d.set_io$$pmpConfig(pmpConfig);
    }
    void step(bool ready, bool invalidate = false) {
        inputs(); d.set_io$$invalidate(invalidate); d.set_io$$response$$ready(ready);
        bool wv = walk && cycle >= walk->due, pv = physical && cycle >= physical->due;
        bool wr = !walk && cycle % 4 != 1;
        bool pr = (!physical
#ifdef I1_DATA_REPLY_HANDOFF
            || pv
#endif
            ) && cycle % 3 != 1;
        d.set_io$$walkRequest$$ready(wr); d.set_io$$physicalRequest$$ready(pr);
        d.set_io$$walkResponse$$valid(wv); d.set_io$$physicalResponse$$valid(pv);
        d.set_io$$walkResponse$$bits$$data(walk ? memory[walk->address] : 0);
        d.set_io$$walkResponse$$bits$$error(walk && walk->error);
        d.set_io$$walkResponse$$bits$$pageFault(0);
        d.set_io$$physicalResponse$$bits$$data(physical ? pattern(physical->address) : 0);
        d.set_io$$physicalResponse$$bits$$error(physical && physical->error);
        d.set_io$$physicalResponse$$bits$$pageFault(0);
        d.step(); ++cycle; hits += d.get_io$$hit();
        std::array<uint64_t, 4> w{d.get_io$$walkRequest$$bits$$address(),
            d.get_io$$walkRequest$$bits$$write(), d.get_io$$walkRequest$$bits$$size(),
            d.get_io$$walkRequest$$bits$$noAllocate()};
        std::array<uint64_t, 5> p{d.get_io$$physicalRequest$$bits$$address(),
            d.get_io$$physicalRequest$$bits$$write(), d.get_io$$physicalRequest$$bits$$size(),
            d.get_io$$physicalRequest$$bits$$noAllocate(),
#ifdef I1_INSTRUCTION_PMA
            d.get_io$$physicalCacheable()
#else
            0
#endif
        };
        if (heldWalk) need(d.get_io$$walkRequest$$valid() && w == *heldWalk, "PTW offer changed under stalls");
        if (heldPhysical) need(d.get_io$$physicalRequest$$valid() && p == *heldPhysical,
            "physical offer changed under stalls");
        heldWalk.reset(); heldPhysical.reset();
        if (d.get_io$$walkRequest$$valid() && !wr) heldWalk = w;
        if (d.get_io$$physicalRequest$$valid() && !pr) heldPhysical = p;
        std::array<uint64_t, 3> r{d.get_io$$response$$bits$$data(), d.get_io$$response$$bits$$error(),
            d.get_io$$response$$bits$$pageFault()};
        if (heldResponse) need(d.get_io$$response$$valid() && r == *heldResponse, "MMU response changed under stalls");
        heldResponse.reset(); if (d.get_io$$response$$valid() && !ready) heldResponse = r;
        if (wv && d.get_io$$walkResponse$$ready()) walk.reset();
        if (pv && d.get_io$$physicalResponse$$ready()) physical.reset();
        if (wr && d.get_io$$walkRequest$$valid()) {
            need(!walk && !w[1] && w[2] == 3 && !(w[0] & 7) && pmpAllowed(w[0], 8, 1, false, false),
                "PTW physical PMP/geometry oracle");
            walk = Pending{w[0], cycle + 1 + random() % 7, w[0] == injectAddress}; ++walks;
        }
        if (pr && d.get_io$$physicalRequest$$valid()) {
            need(!physical, "duplicate physical owner");
            if (!expectedPhysicalAddress || p[0] != *expectedPhysicalAddress) {
                std::cerr << "MMU physical mismatch case=" << cases << " cycle=" << cycle
                          << " actual=0x" << std::hex << p[0] << " expected=0x"
                          << expectedPhysicalAddress.value_or(0) << std::dec << '\n';
            }
            need(expectedPhysicalAddress && p[0] == *expectedPhysicalAddress,
                "independent exact physical address oracle");
            if (explicitNoAllocate) need(p[3], "explicit noAllocate disappeared");
#ifdef I1_INSTRUCTION_PMA
#ifdef I1_PMA_SHIFTED
            constexpr uint64_t cacheBase = 0x80000040, cacheEnd = 0x90000040;
#elif defined(I1_PMA_BOARD)
            constexpr uint64_t cacheBase = 0x80200000, cacheEnd = 0x100200000ULL;
#else
            constexpr uint64_t cacheBase = 0x80000000, cacheEnd = 0x90000000;
#endif
            bool expectedPma = !p[3] && p[0] >= cacheBase && p[0] < cacheEnd;
            need(bool(p[4]) == (expectedPma ^ wrongPma), "independent instruction PMA/noAllocate oracle");
#endif
            unsigned priv = INSTRUCTION ? privilege : dataPrivilege;
            if (!pmpAllowed(p[0] & ~63ULL, 64, priv, INSTRUCTION, false))
                need(p[3], "PMP-denied neighbours must not be filled");
            physical = Pending{p[0], cycle + 1 + random() % 5, p[0] == injectAddress}; ++requests;
        }
    }
    bool pmpAllowed(uint64_t pa, uint64_t bytes, unsigned priv, bool execute, bool write) const {
        if (pa >= (1ULL << 36) || bytes > (1ULL << 36) - pa) return false;
        // Fixture has one TOR entry [0, top), followed by OFF entries.
        bool match = ((pmpConfig >> 3) & 3) && pa < top;
        if (!match) return priv == 3;
        if (pa + bytes > top) return false; // Partial first match denies even unlocked M-mode.
        return (priv == 3 && !(pmpConfig & 128)) ||
            (pmpConfig & (execute ? 4 : write ? 2 : 1));
    }
    Expected oracle(uint64_t va, bool write = false, int atomic = -1) {
        unsigned accessPrivilege = INSTRUCTION ? privilege : dataPrivilege;
        bool paging = accessPrivilege != 3 && (satp >> 60) == 8;
        uint64_t pa = va;
        if (paging) {
            uint64_t hi = va >> 39, sign = va >> 38 & 1;
            if (hi != (sign ? (1ULL << 25) - 1 : 0)) return {0, true, true};
            uint64_t table = (satp & ((1ULL << 44) - 1)) << 12;
            for (int level = 2; level >= 0; --level) {
                uint64_t at = table + ((va >> (12 + 9 * level)) & 511) * 8;
                if (!pmpAllowed(at, 8, 1, false, false) || at == injectAddress) return {0, true, false};
                uint64_t v = memory[at], flags = v & 255;
                if (!(v & 1) || (!(v & 2) && (v & 4)) || (v >> 54)) return {0, true, true};
                uint64_t page = (v >> 10) & ((1ULL << 44) - 1);
                if (flags & (2 | 8)) {
                    bool readable = flags & 2 || (mxr && (flags & 8));
                    bool permission = INSTRUCTION ? bool(flags & 8) : write ? bool(flags & 4) : readable;
                    if (!permission || !(flags & 64) || (write && !(flags & 128)) ||
                        (accessPrivilege == 0 ? !(flags & 16) : (flags & 16) && (INSTRUCTION || !sum)) ||
                        (page & ((1ULL << (9 * level)) - 1))) return {0, true, true};
                    uint64_t pageMask = (1ULL << (12 + 9 * level)) - 1;
                    pa = (page << 12) | (va & pageMask); break;
                }
                if (level == 0 || (flags & (16 | 64 | 128))) return {0, true, true};
                table = page << 12;
            }
        }
        if (!pmpAllowed(pa, INSTRUCTION ? 4 : 8, accessPrivilege, INSTRUCTION, write) ||
            (atomic >= 0 && atomic != 2 && atomic != 3 &&
             !pmpAllowed(pa, 8, accessPrivilege, false, false)))
            return {0, true, false};
        return {pa, pa == injectAddress, false};
    }
    void invalidate() { d.set_io$$request$$valid(0); step(false, true); }
    void tables(unsigned flags = INSTRUCTION ? 0xcf : 0xc7) {
        memory.clear(); memory[ROOT + 8] = pte(L1, 1); memory[L1] = pte(L0, 1);
        memory[L0] = pte(0x80030000, flags); privilege = 1; dataPrivilege = 1; sum = mxr = false;
        top = 0x90000000; pmpConfig = 15; injectAddress = ~0ULL;
        satp = (8ULL << 60) | (ROOT >> 12); invalidate();
    }
    uint64_t transact(uint64_t va, bool write = false, bool invalidatePending = false,
                  std::optional<Expected> override = {}, int atomic = -1, bool noAllocate = false) {
        if (INSTRUCTION) write = false;
        Expected e = override ? *override : oracle(va, write, atomic);
        // A deliberate response-fault mutation must not mutate the separate
        // physical address oracle. Explicit cached-old-PA expectations remain.
        Expected physicalExpectation = e.error && e.pa == 0 ? oracle(va, write, atomic) : e;
        expectedPhysicalAddress = (!physicalExpectation.error || physicalExpectation.pa == injectAddress) ?
            std::optional<uint64_t>{physicalExpectation.pa} : std::nullopt;
        explicitNoAllocate = noAllocate;
        uint64_t oldRequests = requests;
        request(va, write, INSTRUCTION ? 2 : 3, noAllocate, atomic);
        bool accepted = false, invalidated = false; unsigned replyStall = 0;
        uint64_t start = cycle;
        for (unsigned n = 0; n < 400; ++n) {
            d.set_io$$request$$valid(!accepted);
            bool ready = accepted && replyStall >= 5 && cycle % 3 == 0;
            bool inv = accepted && invalidatePending && !invalidated && bool(walk);
            step(ready, inv); invalidated |= inv;
            if (d.get_io$$request$$ready() && !accepted) accepted = true;
            if (d.get_io$$response$$valid()) {
                ++replyStall;
                if (!ready) continue;
                need(bool(d.get_io$$response$$bits$$error()) == e.error &&
                    bool(d.get_io$$response$$bits$$pageFault()) == e.page,
                    "independent Sv39/PMP/page-vs-access fault oracle");
                if (!e.error) need(d.get_io$$response$$bits$$data() == pattern(e.pa), "independent physical payload oracle");
                need(requests - oldRequests == (e.error && e.pa != injectAddress ? 0U : 1U),
                    "denied translation issued a physical demand");
                d.set_io$$request$$valid(0); ++cases;
                if (cases <= 2) std::cout << "MMU_LATENCY case=" << cases << " cycles=" << cycle - start << '\n';
                return cycle - start;
            }
        }
        throw std::runtime_error("MMU bounded completion failed");
    }
#ifdef I1_DATA_REPLY_HANDOFF
    void handoff(unsigned kind) {
        tables(); transact(VA);
        const uint64_t oldPa=0x80030000, newPa=oldPa+8;
        if (kind==1) injectAddress=oldPa;
        const uint64_t beforeRequests=requests;
        expectedPhysicalAddress=oldPa;
        request(VA,false,3); d.set_io$$request$$valid(1);
        bool accepted=false;
        for (unsigned n=0; n<100 && !accepted; ++n) {
            step(false); accepted=d.get_io$$request$$ready();
        }
        need(accepted,"old handoff read was not accepted");
        d.set_io$$request$$valid(0);
        for (unsigned n=0; n<30 && requests==beforeRequests; ++n) step(false);
        need(requests==beforeRequests+1, "old physical read was not issued exactly once");
        // Keep the existing result register stalled while the next proven
        // read replaces the physical owner. No result/owner may be lost.
        request(kind==5 ? VA+0x1008 : VA+8, kind==2, kind==4 ? 2 : 3, kind==3);
        if (kind==4) { request(VA+9,false,3); }
        expectedPhysicalAddress=newPa; readAhead=true; d.set_io$$request$$valid(1);
        bool handed=false, oldReply=false;
        for (unsigned n=0; n<150 && !oldReply; ++n) {
            const bool waiting=kind==0 && !handed && physical && cycle+1<physical->due;
            step(false);
            if(waiting){
                need(d.get_io$$physicalRequest$$bits$$address()==newPa &&
                    !d.get_io$$physicalRequest$$bits$$noAllocate(),
                    "next physical payload depends on old reply admission");
                ++preparedPayloadCycles;
            }
            if (d.get_io$$request$$ready()) {
                need(kind==0 && !handed,"unsafe/error/unproven read handoff admitted");
                handed=true; d.set_io$$request$$valid(0);
            }
            oldReply=d.get_io$$response$$valid();
        }
        need(oldReply && handed==(kind==0),"physical reply/read handoff witness mismatch");
        readAhead=false; d.set_io$$request$$valid(0);
        for (unsigned n=0; n<12; ++n) {
            step(false);
            need(d.get_io$$response$$valid() &&
                bool(d.get_io$$response$$bits$$error())==(kind==1) &&
                (kind==1 || d.get_io$$response$$bits$$data()==pattern(oldPa)),
                "registered old reply was overwritten by younger physical return");
        }
        step(true);
        if (handed) {
            bool done=false;
            for (unsigned n=0; n<100 && !done; ++n) {
                step(true);
                if (d.get_io$$response$$valid()) {
                    need(!d.get_io$$response$$bits$$error() &&
                        d.get_io$$response$$bits$$data()==pattern(newPa),
                        "independent handoff younger physical payload oracle");
                    done=true;
                }
            }
            need(done,"handed read did not complete");
        }
        injectAddress=~0ULL; ++cases;
    }
#endif
};
int main(int argc, char **argv) { try {
    Test t; bool mutate = argc > 1 && std::string(argv[1]) == "--wrong-page";
#ifdef I1_DATA_REPLY_HANDOFF
    for (unsigned kind=0; kind<6; ++kind) t.handoff(kind);
    need(t.preparedPayloadCycles>0,"missing reply-independent prepared address witness");
    std::cout << "MMU_HANDOFF_PASS accepted=1 blocked=5 held_reply_cycles=12 prepared_payload_cycles="
              << t.preparedPayloadCycles << '\n';
#endif
    t.wrongPma = argc > 1 && std::string(argv[1]) == "--wrong-pma";
    t.tables(); t.transact(VA, false, false, mutate ? std::optional<Expected>{Expected{0, true, true}} : std::nullopt);
    auto before = t.walks; t.transact(VA); need(t.walks == before && t.hits, "TLB hit walked again");
    t.memory[L0] = pte(0x80032000, INSTRUCTION ? 0xcf : 0xc7);
    t.transact(VA, false, false, Expected{0x80030000, false, false});
    t.invalidate(); t.transact(VA);
    t.tables(); t.transact(VA, false, true); before = t.walks; t.transact(VA);
    need(t.walks > before, "in-flight SFENCE resurrected old TLB entry");
    for (unsigned flags = 0; flags < 256; ++flags) {
        t.tables(flags);
        t.privilege = t.dataPrivilege = flags % 3 == 0 ? 0 : 1;
        t.sum = flags % 5 == 0; t.mxr = flags % 7 == 0;
        t.transact(VA + 8, flags % 2);
    }
    t.tables(); t.transact(0x0000008000000000ULL); t.transact(0xffffff8000000000ULL);
    t.tables(); t.memory[L1] = pte(0x80000000, INSTRUCTION ? 0xcf : 0xc7); t.transact(VA + 0x1ab008);
    before = t.walks; t.transact(VA + 0x128008);
    need(t.walks == before, "2MiB TLB entry did not cover another 4KiB slice");
    t.tables(); t.memory[L1] = pte(0x80001000, 0xc7); t.transact(VA);
    t.tables(); t.memory[ROOT + 8] = pte(0x80000000, INSTRUCTION ? 0xcf : 0xc7); t.transact(VA + 0xabc008);
    before = t.walks; t.transact(VA + 0x345008);
    need(t.walks == before, "1GiB TLB entry did not cover another 4KiB slice");
    t.tables(); t.memory[ROOT + 8] = pte(0x80200000, 0xc7); t.transact(VA);
    t.tables(); t.memory[L0] |= 1ULL << 63; t.transact(VA);
    t.tables(); t.memory[L1] |= 64; t.transact(VA);
    t.tables(); t.memory[L0] = pte(1ULL << 36, 0xc7); t.transact(VA);
    t.tables(); t.memory[L1] = pte(1ULL << 36, 1); t.transact(VA);
    t.tables(); t.top = ROOT; t.transact(VA);
    t.tables(); t.top = 0x80030000; t.transact(VA);
    t.tables(); t.injectAddress = L1; t.transact(VA);
    t.tables(); t.injectAddress = 0x80030000; t.transact(VA);
    t.tables(); t.privilege = 3; t.dataPrivilege = 3; t.transact(0x80030000);
    t.tables(); t.privilege = 3; t.dataPrivilege = 1; t.transact(VA);
    t.tables(); t.satp = 0; t.transact(0x80030000);
    t.tables(); t.top = 0x80030008; t.transact(VA);
    t.tables(); t.memory[ROOT + 8] = pte(0x80000000, INSTRUCTION ? 0xcf : 0xc7);
    t.top = 0x80031000;
    t.transact(VA + 0x30000);
    t.transact(VA + 0x40000);   // Same superpage, but PMP disallows this slice.
    t.transact(VA + 0x30008);   // Denied slice must not corrupt cached authorization of the legal slice.
    // A physical-width memo must reject high XLEN aliases of both R/W proofs.
    t.tables(); t.satp = 0; t.privilege = t.dataPrivilege = 3; t.invalidate();
    t.transact(0x80030000); t.transact(0x80030008);
    t.transact(0x1080030010ULL); t.transact(0x80030018);
    // Architectural all-OFF M grant must not be a one-page permission cache:
    // change pages on every access, then test the physical limit and MPRV/S/U.
    t.tables(); t.pmpConfig = 0; t.privilege = t.dataPrivilege = 3; t.invalidate();
    const auto machineHits = t.hits;
    for (unsigned page=0; page<4; ++page) t.transact(0x80203000ULL + page * 4096);
#ifdef I1_MACHINE_OFF_FAST
    need(t.hits >= machineHits + 4, "independent all-OFF M proof must not thrash across pages");
#else
    (void)machineHits;
#endif
    t.transact((1ULL << 36) - 8); t.transact(1ULL << 36); t.transact(0x1080203000ULL);
    t.transact(0x80203000, !INSTRUCTION, false, {}, -1, true);
    t.privilege = t.dataPrivilege = 1; t.invalidate(); t.transact(0x80203000);
    t.privilege = t.dataPrivilege = 0; t.invalidate(); t.transact(0x80203000);
    if (!INSTRUCTION) {
        t.privilege = 3; t.dataPrivilege = 1; t.invalidate(); t.transact(0x80203000);
    }
    t.pmpConfig = 8; t.top = 0x80030004; t.privilege = t.dataPrivilege = 3;
    t.invalidate(); t.transact(0x80030002);
    // Restore the exact original bare read-proof context before its separate
    // write/high-alias cases; the extra cases above must not weaken them.
    t.tables(); t.satp = 0; t.privilege = t.dataPrivilege = 3; t.invalidate();
    t.transact(0x80030000); t.transact(0x80030008);
    t.transact(0x1080030010ULL); t.transact(0x80030018);
    if (!INSTRUCTION) {
        t.transact(0x80030020, true); t.transact(0x80030028, true);
        t.transact(0x1080030030ULL, true); t.transact(0x80030038, true);
    }
#ifdef I1_INDEXED_DATA_PROOFS
    // Same eight permission slots, indexed by FULL virtual-page hash rather
    // than the shared superpage TLB owner. Read/write proofs stay separate.
    t.tables(); t.top=0x200000000ULL;
    t.memory[ROOT+8]=pte(0x80000000ULL,0xc7);
    t.memory[ROOT+16]=pte(0xc0000000ULL,0xc7);
    for(unsigned page=0;page<8;++page) {
        t.transact(VA+page*4096);t.transact(VA+page*4096+8,true);
    }
    const auto indexedHits=t.hits, indexedWalks=t.walks;
    for(unsigned page=0;page<8;++page) {
        t.transact(VA+page*4096+16);t.transact(VA+page*4096+24,true);
    }
    const bool wrongIndexed=argc>1&&std::string(argv[1])=="--wrong-indexed-count";
    need(t.hits>=indexedHits+(wrongIndexed?1000000:16)&&t.walks==indexedWalks,
         "independent indexed data superpage proof reuse oracle");
    t.memory[ROOT+8]=pte(0x100000000ULL,0xc7);
    t.transact(0x80001000ULL); // replace the REAL shared row0 first
    for(unsigned page=0;page<8;++page) {
        t.transact(VA+page*4096);t.transact(VA+page*4096+8,true);
    }
    // Leaf row replacement must invalidate BOTH proof classes bound to that
    // source, not whichever virtual proof index equals the source number.
    t.tables();t.top=0x200000000ULL;
    for(unsigned i=0;i<8;++i) {
        const unsigned page=(i<<3)|(i^1);
        t.memory[L0+page*8]=pte(0x100100000ULL+i*4096,0xc7);
    }
    for(unsigned i=0;i<8;++i) {
        const unsigned page=(i<<3)|(i^1);
        t.transact(VA+page*4096);t.transact(VA+page*4096+8,true);
    }
    t.memory[L0+8]=pte(0x100500000ULL,0xc7);
    t.transact(VA+4096);t.transact(VA+4096+8,true);
    // A newly installed dominant superpage must retire old leaf proofs.
    t.tables();t.memory[L0+8]=pte(0x80034000ULL,0xc7);
    t.transact(VA+4096);t.transact(VA+4096+8,true);
    t.memory[ROOT+8]=pte(0x80000000ULL,0xc7);
    t.transact(VA+8192);t.transact(VA+4096);t.transact(VA+4096+8,true);
    std::cout<<"I1_INDEXED_DATA_PROOF_REPLACEMENT_PASS proofs=8 read_write_owner_eviction=1 dominant_superpage=1 no_extra_TLB_rows=1\n";
#endif
#ifdef I1_INSTRUCTION_PMA
    t.tables(); t.transact(VA); t.transact(VA + 4, false, false, {}, -1, true);
    // A live row0 superpage dominates an older overlapping 4KiB proof.
    t.tables(); t.memory[L0 + 8] = pte(0x80034000, 0xcf);
    t.transact(VA + 0x1000); t.transact(VA + 0x1004);
    t.memory[ROOT + 8] = pte(0x80000000, 0xcf);
    t.transact(VA + 0x2000); t.transact(VA + 0x1000); t.transact(VA + 0x1004);
    // Multiple 4KiB proofs may refer to the SAME real superpage owner.
    // Replacing row0 must invalidate all of them, not create hidden TLB
    // capacity. The independent page-table oracle sees the changed mapping
    // only AFTER an unrelated superpage demonstrably evicts that row.
    t.tables(); t.top = 0x200000000ULL;
    t.memory[ROOT + 8] = pte(0x80000000ULL, 0xcf);
    t.memory[ROOT + 16] = pte(0xc0000000ULL, 0xcf);
    for (unsigned page = 0; page < 4; ++page) {
        t.transact(VA + page * 4096); t.transact(VA + page * 4096 + 4);
    }
    t.memory[ROOT + 8] = pte(0x100000000ULL, 0xcf);
    t.transact(0x80001000ULL);
    for (unsigned page = 0; page < 4; ++page) {
        t.transact(VA + page * 4096); t.transact(VA + page * 4096 + 4);
    }
    // Eight different leaves share the existing hashed TLB/proof index1.
    t.tables();
    for (unsigned i = 0; i < 8; ++i) {
        const unsigned page = (i << 3) | (i ^ 1);
        t.memory[L0 + page * 8] = pte(0x80210000ULL + i * 4096, 0xcf);
    }
    for (unsigned i = 0; i < 8; ++i) {
        const unsigned page = (i << 3) | (i ^ 1);
        t.transact(VA + page * 4096); t.transact(VA + page * 4096 + 4);
    }
    t.transact(VA + 4096);
    std::cout << "I1_INDEXED_IF_PROOF_REPLACEMENT_PASS source_owner_eviction=1 hashed_collisions=8 no_extra_TLB_rows=1\n";
    // Raw fixture mode1 is not Sv39 and cannot publish a virtual proof.
    t.tables(); t.transact(VA); t.satp = (1ULL << 60) | (ROOT >> 12);
    t.transact(VA); t.satp = (8ULL << 60) | (ROOT >> 12); t.transact(VA + 4);
    // Both sides of a window boundary WITHIN one page exercise the fallback
    // for a line-aligned but not page-aligned PMA window.
    t.tables(); t.satp = 0; t.privilege = t.dataPrivilege = 3; t.invalidate();
    for (auto pa : {0x80000000ULL, 0x80000080ULL, 0x90000000ULL, 0x90000080ULL})
        t.transact(pa);
    t.tables(); t.top = 0x200000000ULL; t.memory[L0] = pte(0x100000000ULL, 0xcf); t.invalidate();
    t.transact(VA); t.transact(VA + 4);
#endif
    if (!INSTRUCTION) {
        // Cached PTE permission must still observe SUM/MXR on every offered request.
        t.tables(0xd9); t.sum = true; t.mxr = true; t.transact(VA); t.transact(VA + 8);
        t.sum = false; t.transact(VA + 16);
        t.sum = true; t.mxr = false; t.transact(VA + 24);
        t.mxr = true; t.transact(VA + 32);
        // Effective privilege, not current M-mode, owns a bare PMP proof.
        t.tables(); t.satp = 0; t.pmpConfig = 8; t.privilege = t.dataPrivilege = 3; t.invalidate();
        t.transact(0x80030000); t.transact(0x80030008);
        t.dataPrivilege = 1; t.transact(0x80030010);
        // Locked read-only: writes/SC/AMO must never borrow the read proof.
        t.tables(); t.satp = 0; t.pmpConfig = 0x89; t.invalidate();
        t.transact(0x80030000); t.transact(0x80030008);
        t.transact(0x80030010, true); t.transact(0x80030018, true, false, {}, 3);
        t.transact(0x80030020, true, false, {}, 0);
        // Write-only PMP permits stores/SC, but neither RMW nor speculative line reads.
        t.tables(); t.satp = 0; t.pmpConfig = 0x8a; t.invalidate();
        t.transact(0x80030000, true); t.transact(0x80030008, true);
        t.transact(0x80030010, true, false, {}, 3);
        t.transact(0x80030018, true, false, {}, 0); t.transact(0x80030020);
        // Exact full physical page must survive cached R/W authorization above4GiB.
        t.tables(); t.top = 0x200000000ULL; t.memory[L0] = pte(0x100300000ULL, 0xc7); t.invalidate();
        t.transact(VA); t.transact(VA + 8); t.transact(VA + 16, true); t.transact(VA + 24, true);
        auto measure = [&](bool bare) {
            t.tables(); t.memory[ROOT + 8] = pte(0x80000000, 0xc7);
            if (bare) t.satp = 0;
            uint64_t base = bare ? 0x80000000 : VA;
            t.transact(base + 0x30000); t.transact(base + 0x40000, true);
            uint64_t oldWalks = t.walks, oldRequests = t.requests, oldHits = t.hits;
            uint64_t start = t.cycle;
            for (unsigned n = 0; n < 32; ++n) {
                t.transact(base + 0x30000 + 8 * n);
                t.transact(base + 0x40000 + 8 * n, true);
            }
            need(t.walks == oldWalks && t.requests - oldRequests == 64,
                "cached COPY authorization changed physical traffic or walked again");
            std::cout << "I1_DATA_AUTH_PERF {\"bare\":" << bare << ",\"pairs\":32,\"cycles\":"
                << t.cycle - start << ",\"requests\":64,\"pte_reads\":0,\"hits\":"
                << t.hits - oldHits << "}\n";
        };
        measure(true); measure(false);
    }
#ifdef I1_RETIREMENT_OVERLAP
    // Keep the next offer asserted while an old REGISTERED response is
    // stalled. The independent oracle sees accepted owners, not DUT state.
    uint64_t replacements = 0, heldCycles = 0, replacementCycles = 0;
    for (bool bare : {false, true}) for (bool inject : {false, true}) {
        t.tables(); if (bare) t.satp = 0;
        uint64_t base = bare ? 0x80030000 : VA;
        if (inject) t.injectAddress = 0x80030108;
        std::array<Expected, 48> expected;
        for (unsigned n = 0; n < expected.size(); ++n) expected[n] = t.oracle(base + n * 8, n % 2);
        uint64_t firstRequest = t.requests, start = t.cycle;
        unsigned offered = 0, completed = 0, held = 0;
        while (completed < expected.size() && t.cycle - start < 4000) {
            t.d.set_io$$request$$valid(offered < expected.size());
            t.request(base + offered * 8, offered % 2, 3);
            unsigned physicalIndex = t.requests - firstRequest;
            t.expectedPhysicalAddress = physicalIndex < expected.size() ?
                std::optional<uint64_t>{expected[physicalIndex].pa} : std::nullopt;
            bool ready = held >= 3 && t.cycle % 4 != 1;
            t.step(ready);
            bool accepted = offered < expected.size() && t.d.get_io$$request$$ready();
            bool retired = t.d.get_io$$response$$valid() && ready;
            if (t.d.get_io$$response$$valid() && !ready) {
                ++held; ++heldCycles;
                need(!accepted, "replacement accepted before old registered reply was consumed");
            }
            if (retired) {
                const auto &e = expected[completed];
                uint64_t actual = t.d.get_io$$response$$bits$$data();
                if (argc > 1 && std::string(argv[1]) == "--wrong-retirement" && completed == 3) actual ^= 1;
                need(bool(t.d.get_io$$response$$bits$$error()) == e.error &&
                    bool(t.d.get_io$$response$$bits$$pageFault()) == e.page &&
                    (e.error || actual == pattern(e.pa)), "independent replacement owner/data/error oracle");
                ++completed; held = 0; ++t.cases;
            }
            if (accepted && retired) ++replacements;
            if (accepted) ++offered;
            need(offered >= completed && offered - completed <= 1, "translation acquired more than one owner");
        }
        need(completed == expected.size() && offered == completed && !t.physical && !t.walk,
            "replacement bounded drain/response ledger");
        need(t.requests - firstRequest == expected.size(), "replacement duplicated/lost physical request");
        replacementCycles += t.cycle - start; t.d.set_io$$request$$valid(0);
    }
    need(heldCycles > 100 && (I1_RETIREMENT_OVERLAP ? replacements > 100 : replacements == 0),
        "replacement mode/backpressure coverage");
    std::cout << "I1_RETIREMENT_REPLACE_PASS enabled=" << I1_RETIREMENT_OVERLAP
        << " cases=192 replacements=" << replacements << " held_cycles=" << heldCycles
        << " cycles=" << replacementCycles << " single_owner_errors_backpressure=PASS\n";
#endif
#ifdef I1_SPLIT_INSTRUCTION_CANDIDATES
    need(t.candidateSelectMask == 3 && t.candidateNoiseChanges > 100,
        "independent instruction candidate selection/noise coverage");
    std::cout << "I1_INSTRUCTION_CANDIDATES_PASS candidate_select_mask=3 unselected_noise_changes="
        << t.candidateNoiseChanges << " single_owner_address_fault_PMA_oracle=PASS\n";
#endif
#ifdef I1_SPLIT_DATA_CANDIDATES
    need(t.candidateSelectMask == 3 && t.candidateNoiseChanges > 100,
        "independent data candidate selection/noise coverage");
    std::cout << "I1_DATA_CANDIDATES_PASS candidate_select_mask=3 unselected_noise_changes="
        << t.candidateNoiseChanges << " single_owner_address_fault_atomic_oracle=PASS\n";
#endif
    std::cout << "FIVE_STAGE_TRANSLATION_PASS instruction=" << INSTRUCTION << " cases=" << t.cases << " pte_reads=" << t.walks
        << " demand_requests=" << t.requests << " tlb_hits=" << t.hits
        << " 4K_2M_1G_Svade_SUM_MXR_MPRV_reserved_PMP_PTE_errors_SFENCE_stalls=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
