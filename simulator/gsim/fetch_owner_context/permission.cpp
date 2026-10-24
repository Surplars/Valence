#include "FetchOwnerPermissionGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <tuple>
#include <vector>

namespace {
constexpr uint64_t ram = UINT64_C(0x80200000);
using Dut = SFetchOwnerPermissionGsim;
void check(bool ok, const std::string &why) {
    if (!ok) throw std::runtime_error(why);
}
// Fixed byte-addressed memory. No DUT decoder, returned value, or test fixture
// signal is used to generate an expected instruction word.
uint8_t memoryByte(uint64_t a) {
    uint64_t x = a ^ (a >> 11) ^ (a >> 23) ^ UINT64_C(0x91a7c653);
    return uint8_t((x * 73 + (x >> 7) * 19 + 0x35) & 255);
}
uint64_t memoryBytes(uint64_t a, unsigned bytes) {
    uint64_t result = 0;
    for (unsigned i = 0; i < bytes; ++i) result |= uint64_t(memoryByte(a + i)) << (8 * i);
    return result;
}
struct Policy {
    uint64_t low = ram + 16, high = ram + 32;
    bool locked = false, execute = true;
    // Independent byte-range rule for the programmed OFF/TOR pair. Even an
    // unlocked M access cannot straddle the first matching PMP region. M may
    // bypass permissions of a fully matching unlocked entry, or an unmatched
    // region. This is deliberately not the DUT's decoded-region checker.
    bool permits(uint64_t address, unsigned bytes, unsigned privilege) const {
        bool any = false, every = true;
        for (unsigned i = 0; i < bytes; ++i) {
            const bool in = address + i >= low && address + i < high;
            any |= in;
            every &= in;
        }
        if (!any) return privilege == 3;
        return every && (execute || (privilege == 3 && !locked));
    }
    unsigned cfg() const { return 0x08 | (execute ? 4 : 0) | (locked ? 0x80 : 0); }
};
// Pure architectural property, independent of the fixture and its published
// PMP state. Each trial programs a stable sixteen-entry raw PMP image. Packet
// permission is the conjunction of the two separately checked requested words,
// which also covers allowed words on different priority-region boundaries.
struct RawPmpEntry { unsigned cfg = 0; uint64_t addr = 0; };
using RawPmp = std::array<RawPmpEntry, 16>;
struct ByteRegion { uint64_t low = 0, high = 0; bool active = false; };
ByteRegion rawRegion(const RawPmp &raw, unsigned index) {
    const auto &e = raw[index];
    switch ((e.cfg >> 3) & 3) {
    case 0: return {};
    case 1: {
        const uint64_t low = index ? raw[index - 1].addr * 4 : 0;
        const uint64_t high = e.addr * 4;
        return {low, high, high > low};
    }
    case 2: return {e.addr * 4, e.addr * 4 + 4, true};
    default: {
        unsigned ones = 0;
        while (ones < 54 && ((e.addr >> ones) & 1)) ++ones;
        const uint64_t bytes = UINT64_C(1) << (ones + 3);
        const uint64_t low = (e.addr * 4) & ~(bytes - 1);
        return {low, low + bytes, true};
    }
    }
}
unsigned matchingBytes(const ByteRegion &region, uint64_t address, unsigned bytes) {
    unsigned matched = 0;
    for (unsigned byte = 0; byte < bytes; ++byte)
        matched += region.active && address + byte >= region.low && address + byte < region.high;
    return matched;
}
bool rawExecute(const RawPmp &raw, uint64_t address, unsigned bytes, unsigned privilege) {
    for (unsigned index = 0; index < raw.size(); ++index) {
        const unsigned matched = matchingBytes(rawRegion(raw, index), address, bytes);
        if (!matched) continue;
        // Priority chooses the first entry overlapping any byte. Partial
        // coverage fails even when M may otherwise ignore an unlocked X bit.
        if (matched != bytes) return false;
        return (privilege == 3 && !(raw[index].cfg & 0x80)) || (raw[index].cfg & 4);
    }
    return privilege == 3;
}
void checkLineImplication() {
    uint64_t rng = UINT64_C(0x61da93e570b4c82f);
    auto random = [&]() { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; return rng; };
    uint64_t samples = 0, antecedents = 0, priority = 0, locked = 0, unmatched = 0, partial = 0;
    uint64_t uAntecedents = 0, sAntecedents = 0;
    for (unsigned trial = 0; trial < 1024; ++trial) {
        const uint64_t line = ram + 64 * (random() % 32);
        RawPmp raw{};
        // Lower-priority random entries exercise all four address modes,
        // reversed/empty TOR regions, mixed permissions, and priority overlap.
        for (unsigned i = 2; i < raw.size(); ++i) {
            raw[i].cfg = unsigned(random() % 4) * 8 + (random() & 1 ? 4 : 0) + (random() & 1 ? 128 : 0);
            raw[i].addr = (ram - 256 + 4 * (random() % 768)) / 4;
        }
        switch (trial % 8) {
        case 0: raw = {}; break; // no match: M succeeds, S/U cannot supply the premise
        case 1:
            raw[0] = {0x0cU | (trial & 8 ? 0x80U : 0U), (ram + 4096) / 4};
            break; // first TOR covers the whole line
        case 2:
            raw[0] = {0, (line - 64) / 4}; raw[1] = {0x0c, (line + 128) / 4};
            break;
        case 3:
            raw[0] = {0x1c, ((line & ~UINT64_C(127)) / 4) | 15};
            raw[1] = {0x90, (line + 20) / 4};
            break; // broad first NAPOT outranks a later locked NA4 deny
        case 4:
            raw[0] = {0x14, (line + 16) / 4};
            raw[1] = {0x1c, ((line & ~UINT64_C(127)) / 4) | 15};
            break; // a first NA4 prevents line expansion despite allowed words
        case 5:
            raw[0] = {0, (line + 8) / 4}; raw[1] = {0x08, (line + 16) / 4};
            raw[2] = {0x1c, ((line & ~UINT64_C(127)) / 4) | 15};
            break; // high-priority deny misses some packets but intersects the line
        case 6:
            raw[0] = {0x98U | (trial & 8 ? 4U : 0U), line / 4 | 7};
            raw[1] = {0x1c, ((line & ~UINT64_C(127)) / 4) | 15};
            break; // locked entire-line allow and deny
        case 7:
            raw[0] = {0, line / 4}; raw[1] = {0x0c, (line + 4) / 4};
            raw[2] = {0x0c, (line + 64) / 4};
            break; // adjacent first-word and remaining-word TOR permissions
        }
        unsigned matchingEntries = 0, firstBytes = 0, firstIndex = 0;
        for (unsigned i = 0; i < raw.size(); ++i) {
            const auto bytes = matchingBytes(rawRegion(raw, i), line, 64);
            if (bytes) {
                if (!matchingEntries) { firstBytes = bytes; firstIndex = i; }
                ++matchingEntries;
            }
        }
        for (unsigned offset = 0; offset < 64; offset += 8) for (unsigned privilege : {0U, 1U}) {
            const uint64_t packet = line + offset;
            const bool packetAllowed = rawExecute(raw, packet, 4, privilege) &&
                rawExecute(raw, packet + 4, 4, privilege);
            const bool machineLineAllowed = rawExecute(raw, line, 64, 3);
            ++samples; priority += matchingEntries > 1; unmatched += matchingEntries == 0;
            partial += firstBytes != 0 && firstBytes != 64;
            locked += matchingEntries && (raw[firstIndex].cfg & 0x80);
            if (packetAllowed && machineLineAllowed) {
                ++antecedents; uAntecedents += privilege == 0; sAntecedents += privilege == 1;
                check(rawExecute(raw, line, 64, privilege),
                    "independent stable-PMP implication failed: S/U words + M line did not imply S/U line");
            }
        }
    }
    check(samples && antecedents && uAntecedents && sAntecedents && priority && locked && unmatched && partial,
        "independent PMP implication sample categories/antecedent were empty");
    std::cout << "PASS PMP_FETCH_LINE_IMPLICATION samples=" << samples << " antecedents=" << antecedents
        << " U_antecedents=" << uAntecedents << " S_antecedents=" << sAntecedents
        << " priority_overlap=" << priority << " locked_first=" << locked
        << " no_match=" << unmatched << " partial_first=" << partial << '\n';
}
struct Owner {
    uint64_t address, firstOffer;
    unsigned mask, privilege, id, allowed = 0, errors = 0;
    uint64_t expectedData = 0, getAddress = 0;
    unsigned getSize = 0, getMask = 0;
    bool accepted = false, buffered = false, cached = false, physicalDone = false, returned = false;
    unsigned gets = 0, beats = 0;
};
struct Counts {
    uint64_t accepted = 0, returned = 0, get4 = 0, get8 = 0, get64 = 0;
    uint64_t mask1 = 0, mask2 = 0, old8 = 0, machine64 = 0, locked8 = 0, faultOnly = 0;
    uint64_t bufferHeld = 0, cacheHeld = 0, responseHeld = 0, aHeld = 0, dHeld = 0;
    uint64_t trapOldHeld = 0, trapCacheHeld = 0, flow = 0, queued = 0, mixedQueued = 0;
    uint64_t maximumOwners = 0, maximumQueue = 0, csrCommands = 0;
    void add(const Counts &x) {
#define ADD(field) field += x.field
        ADD(accepted); ADD(returned); ADD(get4); ADD(get8); ADD(get64); ADD(mask1); ADD(mask2);
        ADD(old8); ADD(machine64); ADD(locked8); ADD(faultOnly); ADD(bufferHeld); ADD(cacheHeld);
        ADD(responseHeld); ADD(aHeld); ADD(dHeld); ADD(trapOldHeld); ADD(trapCacheHeld);
        ADD(flow); ADD(queued); ADD(mixedQueued); ADD(csrCommands);
#undef ADD
        maximumOwners = std::max(maximumOwners, x.maximumOwners);
        maximumQueue = std::max(maximumQueue, x.maximumQueue);
    }
};
struct Transaction {
    unsigned owner, source, size, beat = 0;
    uint64_t address, due;
};
struct DBeat { unsigned source, size; uint64_t data; };
using Payload = std::tuple<uint64_t, unsigned, unsigned>;
using AOffer = std::tuple<uint64_t, unsigned, unsigned, unsigned, unsigned>;

class Driver {
public:
    Dut d;
    Policy policy;
    std::string name;
    Counts c;
    uint64_t cycle = 0, token = 0;
    unsigned slots = 0, mode = 3;
    bool allowCache = true, blockD = false, allowResponse = true, forceAStall = false;
    bool inject = false, injected = false, contextMismatch = false, componentContract = false;
    bool start = false, trap = false;
    uint32_t instruction = 0;
    uint64_t operand = 0;
    std::vector<Owner> owners;
    std::optional<unsigned> offered;
    std::deque<unsigned> queued, cacheOwners;
    std::deque<Transaction> memory;
    std::array<bool, 8> sources{};
    std::optional<DBeat> offeredD;
    std::optional<Payload> heldBuffer, heldQueue, heldCache;
    std::optional<std::tuple<uint64_t, unsigned, unsigned>> heldResponse;
    std::optional<AOffer> heldA;

    Driver(std::string n, Policy p = {}, bool negative = false)
        : policy(p), name(std::move(n)), inject(negative) {
        drive();
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        tick();
        slots = unsigned(d.get_io$$slots());
        check(slots == 1 || slots == 2, where("unsupported owner capacity"));
        check(d.get_io$$livePrivilege() == 3 && d.get_io$$satp() == 0, where("MSU reset context"));
        program(0x3b0, policy.low / 4);
        program(0x3b1, policy.high / 4);
        program(0x3a0, uint64_t(policy.cfg()) << 8);
        check(d.get_io$$cfg0() == 0 && d.get_io$$cfg1() == policy.cfg() &&
            d.get_io$$addr0() == policy.low / 4 && d.get_io$$addr1() == policy.high / 4,
            where("real CSR publication differs from programmed OFF/TOR policy"));
    }
    std::string where(const std::string &why) const {
        return name + " cycle=" + std::to_string(cycle) + " " + why;
    }
    Owner &nextPhysical(bool cache) {
        for (auto &o : owners)
            if (o.accepted && o.allowed && !(cache ? o.cached : o.buffered)) return o;
        throw std::runtime_error(where(cache ? "unowned cache offer" : "unowned adapter physical offer"));
    }
    void samePayload(const Payload &actual, const Owner &o, const char *stage) const {
        const auto expected = Payload{o.address, o.allowed, o.privilege};
        if (actual != expected) {
            std::ostringstream s;
            s << stage << " owner=" << o.id << " original_privilege=" << o.privilege
              << " actual_privilege=" << std::get<2>(actual) << " expected_mask=" << o.allowed
              << " actual_mask=" << std::get<1>(actual) << std::hex << " expected_pa=0x" << o.address
              << " actual_pa=0x" << std::get<0>(actual);
            throw std::runtime_error(where(s.str()));
        }
    }
    void drive() {
        d.set_io$$start(start); d.set_io$$instruction(instruction); d.set_io$$operand(operand);
        d.set_io$$token(token); d.set_io$$trap(trap);
        d.set_io$$trapPc(ram + 0x180); d.set_io$$trapCause(mode == 0 ? 8 : mode == 1 ? 9 : 3);
        d.set_io$$requestValid(offered.has_value());
        d.set_io$$requestAddress(offered ? owners[*offered].address : ram);
        d.set_io$$requestMask(offered ? owners[*offered].mask : 0);
        d.set_io$$responseReady(allowResponse && cycle % 13 >= 4);
        d.set_io$$allowCache(allowCache); d.set_io$$injectCacheContext(injected);
        d.set_io$$forceCacheLiveSupervisor(componentContract);
        d.set_io$$aReady(!forceAStall && cycle % 7 != 2 && cycle % 7 != 3);
        d.set_io$$dValid(offeredD.has_value()); d.set_io$$dData(offeredD ? offeredD->data : 0);
        d.set_io$$dSize(offeredD ? offeredD->size : 3);
        d.set_io$$dSource(offeredD ? offeredD->source : 0);
    }
    void tick() {
        if (!offeredD && !blockD && !memory.empty() && cycle >= memory.front().due) {
            const auto &t = memory.front();
            offeredD = DBeat{t.source, t.size, memoryBytes((t.address & ~UINT64_C(7)) + 8 * t.beat, 8)};
        }
        const bool responseReady = allowResponse && cycle % 13 >= 4;
        const bool aReady = !forceAStall && cycle % 7 != 2 && cycle % 7 != 3;
        drive();
        // GSIM get() after step() observes the handshakes evaluated for this
        // edge. Host ledgers below advance once, after inspecting those values.
        d.step();
        check(d.get_io$$satp() == 0, where("Bare SATP changed"));
        if (offered && d.get_io$$requestReady()) {
            auto &o = owners[*offered];
            check(!o.accepted, where("public owner accepted twice"));
            o.accepted = true; ++c.accepted; offered.reset();
        }
        if (offeredD && d.get_io$$dReady()) {
            check(!memory.empty(), where("D accepted without an A owner"));
            auto &t = memory.front();
            check(sources[t.source] && offeredD->source == t.source && offeredD->size == t.size,
                where("D source/size lost its accepted Get owner"));
            auto &o = owners[t.owner];
            ++o.beats;
            if (++t.beat == (t.size == 6 ? 8U : 1U)) {
                sources[t.source] = false; memory.pop_front();
            } else t.due = cycle + 1;
            offeredD.reset();
        } else if (offeredD) ++c.dHeld;

        if (d.get_io$$physicalResponse()) {
            check(!cacheOwners.empty(), where("physical response has no accepted cache owner"));
            auto &o = owners[cacheOwners.front()];
            check(o.gets == 1 && o.beats == (o.getSize == 6 ? 8U : 1U) && !o.physicalDone,
                where("physical response preceded or duplicated exact TL completion"));
            o.physicalDone = true; cacheOwners.pop_front();
        }
        const bool bv = d.get_io$$bufferValid(), br = d.get_io$$bufferReady();
        const Payload bp{d.get_io$$bufferAddress(), unsigned(d.get_io$$bufferMask()),
            unsigned(d.get_io$$bufferPrivilege())};
        check(!heldBuffer || (bv && *heldBuffer == bp), where("held adapter context changed"));
        std::optional<unsigned> bufferOwner;
        if (bv) {
            auto &o = nextPhysical(false); bufferOwner = o.id; samePayload(bp, o, "buffer input");
            if (br) { o.buffered = true; queued.push_back(o.id); }
        }
        heldBuffer = bv && !br ? std::optional<Payload>(bp) : std::nullopt;
        const bool qv = d.get_io$$queuedValid(), qr = d.get_io$$queuedReady();
        const Payload qp{d.get_io$$queuedAddress(), unsigned(d.get_io$$queuedMask()),
            unsigned(d.get_io$$queuedPrivilege())};
        check(!heldQueue || (qv && *heldQueue == qp), where("held buffer output context changed"));
        if (qv) {
            check(!queued.empty() || bufferOwner, where("buffer output has no independent input owner"));
            const unsigned id = queued.empty() ? *bufferOwner : queued.front();
            samePayload(qp, owners[id], "buffer output");
        }
        if (qv && !qr) ++c.bufferHeld;
        heldQueue = qv && !qr ? std::optional<Payload>(qp) : std::nullopt;
        const bool cv = d.get_io$$cacheValid(), cr = d.get_io$$cacheReady();
        const Payload cp{d.get_io$$cacheAddress(), unsigned(d.get_io$$cacheMask()),
            unsigned(d.get_io$$cachePrivilege())};
        check(!heldCache || (cv && *heldCache == cp), where("held cache offer mutated/withdrew"));
        if (cv) {
            auto &o = nextPhysical(true);
            // Injection never changes the oracle. Defer its context diagnostic
            // only so the actual incorrect Get size, not an early tap check,
            // is the required failure of the explicit component negative control.
            if (inject && injected && std::get<2>(cp) != o.privilege) {
                check(std::get<0>(cp) == o.address && std::get<1>(cp) == o.allowed,
                    where("negative control unexpectedly changed PA/mask"));
                contextMismatch = true;
            } else samePayload(cp, o, "cache input");
            if (cr) {
                check(!queued.empty() && queued.front() == o.id && qr && qv,
                    where("cache acceptance differs from buffer dequeue"));
                c.flow += bufferOwner && *bufferOwner == o.id && br;
                c.queued += !(bufferOwner && *bufferOwner == o.id && br);
                queued.pop_front(); o.cached = true; cacheOwners.push_back(o.id);
            } else ++c.cacheHeld;
        }
        check(!(qr && qv) || (cv && cr), where("valve lost atomic valid/ready"));
        heldCache = cv && !cr ? std::optional<Payload>(cp) : std::nullopt;
        if (trap && qv && !qr && std::get<2>(qp) != 3) ++c.trapOldHeld;
        if (trap && cv && !cr && std::get<2>(cp) != 3) ++c.trapCacheHeld;
        if (queued.size() == 2 && owners[queued[0]].privilege != owners[queued[1]].privilege) ++c.mixedQueued;
        c.maximumQueue = std::max(c.maximumQueue, uint64_t(queued.size()));

        const bool av = d.get_io$$aValid();
        const AOffer a{d.get_io$$aAddress(), unsigned(d.get_io$$aSize()), unsigned(d.get_io$$aSource()),
            unsigned(d.get_io$$aMask()), unsigned(d.get_io$$aOpcode())};
        check(!heldA || (av && *heldA == a), where("TL A held payload changed"));
        if (av) {
            const auto [address, size, source, mask, opcode] = a;
            // A fallback Get may precede cache acceptance only because A.ready
            // is low. Its owner is the independently offered cache head.
            Owner *owner = nullptr;
            for (auto id : cacheOwners) if (!owners[id].gets) { owner = &owners[id]; break; }
            if (!owner && cv) owner = &nextPhysical(true);
            check(owner != nullptr, where("unowned/duplicate TL A offer"));
            auto &o = *owner;
            check(opcode == 4 && (size == 2 || size == 3 || size == 6), where("non-Get/unsupported TL request"));
            const unsigned bytes = 1U << size;
            if (!policy.permits(address, bytes, o.privilege)) {
                std::ostringstream s;
                s << "old owner unauthorized expanded Get owner=" << o.id << " original_privilege="
                  << o.privilege << " live_privilege=" << d.get_io$$livePrivilege()
                  << " size=" << size << std::hex << " address=0x" << address
                  << " allowed_low=0x" << policy.low << " allowed_high=0x" << policy.high;
                throw std::runtime_error(where(s.str()));
            }
            if (componentContract && o.getSize == 6 && size != 6)
                throw std::runtime_error(where("owner context not used for legal M line authorization"));
            check(address == o.getAddress && size == o.getSize && mask == o.getMask,
                where("Get address/size/mask differs from independent requested-byte plan"));
            check(source < sources.size() && ((source >= 4) == (size != 6)), where("TL source namespace"));
            if (aReady) {
                check(o.cached && !o.gets && !sources[source], where("Get duplicated/reused a live source"));
                ++o.gets; sources[source] = true;
                memory.push_back({o.id, source, size, 0, address, cycle + 3});
                c.get4 += size == 2; c.get8 += size == 3; c.get64 += size == 6;
                c.mask1 += size == 2 && o.mask == 1; c.mask2 += size == 2 && o.mask == 2;
                c.old8 += size == 3 && o.privilege != 3 && d.get_io$$livePrivilege() == 3;
                c.machine64 += size == 6 && o.privilege == 3;
                c.locked8 += size == 3 && policy.locked && o.privilege == 3;
            } else ++c.aHeld;
        }
        heldA = av && !aReady ? std::optional<AOffer>(a) : std::nullopt;
        if (d.get_io$$responseValid()) {
            Owner *head = nullptr;
            for (auto &o : owners) if (o.accepted && !o.returned) { head = &o; break; }
            check(head, where("public response has no accepted owner"));
            auto &o = *head;
            check(!o.allowed || o.physicalDone, where("public response before physical completion"));
            check(d.get_io$$responseError() == o.errors && !d.get_io$$responsePageFault(),
                where("public fault vector differs from byte-range policy"));
            check(d.get_io$$responseData() == o.expectedData, where("requested words differ from fixed memory bytes"));
            const auto rp = std::make_tuple(uint64_t(d.get_io$$responseData()),
                unsigned(d.get_io$$responseError()), unsigned(d.get_io$$responsePageFault()));
            check(!heldResponse || *heldResponse == rp, where("public held response changed"));
            if (responseReady) {
                check(o.gets == (o.allowed ? 1U : 0U), where("fault-only request issued Get or reply duplicated"));
                o.returned = true; ++c.returned; c.faultOnly += !o.allowed; heldResponse.reset();
            } else { heldResponse = rp; ++c.responseHeld; }
        } else check(!heldResponse, where("public held response withdrew valid"));
        uint64_t active = 0;
        for (const auto &o : owners) active += o.accepted && !o.returned;
        c.maximumOwners = std::max(c.maximumOwners, active);
        check(active <= (slots ? slots : 2), where("accepted owners exceeded configured credits"));
        ++cycle;
        check(cycle < 20000, where("scenario watchdog"));
    }
    template<class Predicate> void until(Predicate done, const char *why) {
        for (unsigned n = 0; !done(); ++n) { check(n < 1000, where(why)); tick(); }
    }
    void command(uint32_t inst, uint64_t value) {
        check(!offered && c.accepted == c.returned && d.get_io$$quiescent(),
            where("CSR/MRET requires drained fetch"));
        instruction = inst; operand = value; ++token; start = true;
        do { tick(); } while (!d.get_io$$systemReady());
        start = false;
        do { tick(); } while (!d.get_io$$complete());
        check(!d.get_io$$completeException() && d.get_io$$completeToken() == token,
            where("MSU command exception/token mismatch"));
        ++c.csrCommands; tick();
    }
    void program(unsigned csr, uint64_t value) {
        command((csr << 20) | (1U << 15) | (1U << 12) | 0x73, value);
    }
    void enter(unsigned privilege) {
        check(mode == 3 && (privilege == 0 || privilege == 1), where("invalid MRET setup"));
        program(0x300, uint64_t(privilege) << 11);
        program(0x341, policy.low);
        command(0x30200073, 0);
        mode = privilege;
        check(d.get_io$$livePrivilege() == privilege, where("real MRET did not enter requested privilege"));
    }
    void trapToMachine() {
        check(d.get_io$$trapReady() && !start, where("trap issuer lacks idle MSU"));
        trap = true; tick(); trap = false; mode = 3; tick();
        check(d.get_io$$livePrivilege() == 3, where("real trap entry did not enter M mode"));
    }
    unsigned begin(uint64_t address, unsigned mask) {
        check(!offered, where("host replaced an unaccepted public offer"));
        check(d.get_io$$livePrivilege() == mode, where("software issuer privilege differs from real MSU"));
        Owner o{};
        o.address = address; o.mask = mask; o.privilege = mode;
        o.id = unsigned(owners.size()); o.firstOffer = cycle;
        for (unsigned word = 0; word < 2; ++word) if (mask & (1U << word)) {
            if (policy.permits(address + 4 * word, 4, mode)) {
                o.allowed |= 1U << word;
                o.expectedData |= memoryBytes(address + 4 * word, 4) << (32 * word);
            } else o.errors |= 1U << word;
        }
        if (o.allowed == 3 && policy.permits(address & ~UINT64_C(63), 64, mode)) {
            o.getAddress = address & ~UINT64_C(63); o.getSize = 6; o.getMask = 255;
        } else if (o.allowed == 3) {
            o.getAddress = address; o.getSize = 3; o.getMask = 255;
        } else if (o.allowed) {
            o.getAddress = address + (o.allowed == 2 ? 4 : 0); o.getSize = 2;
            o.getMask = (o.getAddress & 4) ? 240 : 15;
        }
        owners.push_back(o); offered = o.id;
        return o.id;
    }
    unsigned issue(uint64_t address, unsigned mask) {
        const auto id = begin(address, mask);
        until([&] { return owners[id].accepted; }, "public offer was never accepted");
        return id;
    }
    void drain() {
        until([&] { return !offered && c.accepted == c.returned && memory.empty() && !offeredD &&
            d.get_io$$quiescent(); }, "fetch chain failed to drain");
        for (unsigned i = 0; i < 5; ++i) tick();
        check(queued.empty() && cacheOwners.empty() && !heldA && !heldCache && !heldQueue && !heldResponse,
            where("drain leaked request/response obligation"));
        check(std::none_of(sources.begin(), sources.end(), [](bool v) { return v; }), where("live TL source at drain"));
    }
    void machineControl() {
        check(mode == 3, where("M control needs real machine mode"));
        const auto before = c.machine64;
        issue(ram + 0x110, 3); drain();
        check(c.machine64 == before + 1, where("new M owner failed to issue actual 64-byte Get"));
    }
};

Counts heldCase(unsigned privilege, unsigned mask) {
    Driver s("trap_queued_" + std::to_string(privilege) + "_mask" + std::to_string(mask));
    s.enter(privilege); s.allowCache = false;
    const auto id = s.issue(s.policy.low, mask);
    s.until([&] { return s.owners[id].buffered && s.d.get_io$$queuedValid(); }, "old owner never reached buffer");
    s.trapToMachine();
    check(s.c.trapOldHeld != 0, s.where("trap did not overlap old buffered owner"));
    // With a stable policy, old live-M line checking is also range-safe by
    // the implication checked below. This case proves preserved ownership,
    // not a previously demonstrated production over-fetch vulnerability.
    s.allowResponse = false;
    s.allowCache = true;
    s.until([&] { return s.d.get_io$$responseValid(); }, "old owner never produced a response");
    for (unsigned n = 0; n < 3; ++n) s.tick();
    s.allowResponse = true; s.drain();
    check(s.owners[id].getSize == (mask == 3 ? 3U : 2U), s.where("directed old-owner plan"));
    s.machineControl();
    return s.c;
}
Counts faultCases() {
    Driver s("fault_only"); s.enter(1);
    s.issue(s.policy.low, 0); s.drain();
    s.issue(s.policy.high + 8, 3); s.drain();
    check(s.c.faultOnly == 2 && s.c.get4 + s.c.get8 + s.c.get64 == 0,
        s.where("mask-zero/full-deny emitted memory traffic"));
    s.trapToMachine(); s.machineControl(); return s.c;
}
Counts lockedCase() {
    Policy p; p.locked = true;
    Driver s("locked_machine_boundary", p);
    s.issue(p.low, 3); s.drain();
    check(s.c.locked8 == 1 && !s.c.get64, s.where("locked TOR boundary expanded in M"));
    s.machineControl(); return s.c;
}
Counts mixedQueue() {
    Driver s("two_context_queue");
    if (s.slots != 2) return s.c;
    s.enter(1); s.allowCache = false;
    const auto old = s.issue(s.policy.low, 3);
    s.until([&] { return s.owners[old].buffered; }, "S owner failed to queue");
    s.trapToMachine();
    const auto young = s.issue(ram + 0x210, 3);
    s.until([&] { return s.owners[young].buffered; }, "new M owner failed to queue behind S");
    check(s.queued.size() == 2 && s.c.mixedQueued, s.where("S and M contexts were not simultaneously queued"));
    s.allowCache = true; s.drain();
    check(s.c.old8 == 1 && s.c.machine64 == 1 && s.c.maximumOwners == 2,
        s.where("two-context old narrow/new wide results incomplete"));
    return s.c;
}
Counts heldCacheCase() {
    Driver s("two_context_cache_held");
    if (s.slots != 2) return s.c;
    s.enter(1); s.blockD = true;
    const auto first = s.issue(s.policy.low, 3);
    s.until([&] { return s.owners[first].gets == 1; }, "first Get never accepted");
    const auto second = s.issue(s.policy.low + 8, 3);
    s.until([&] { return s.d.get_io$$cacheValid() && !s.d.get_io$$cacheReady() &&
        s.d.get_io$$cacheAddress() == s.owners[second].address; }, "second real cache offer never stalled");
    s.trapToMachine();
    check(s.c.trapCacheHeld && s.owners[first].beats == 0, s.where("trap did not occur before delayed first D"));
    s.blockD = false; s.drain();
    check(s.owners[second].gets == 1 && s.c.old8 >= 1, s.where("held S cache owner was not preserved"));
    s.machineControl(); return s.c;
}
Counts cacheContextContract(bool negative) {
    Policy p; p.low = ram; p.high = ram + 64; p.execute = false;
    Driver s("component_M_owner_live_S", p, negative);
    s.componentContract = true; s.allowCache = false;
    const auto id = s.issue(ram + 16, 3);
    s.until([&] { return s.owners[id].buffered && s.d.get_io$$queuedValid(); },
        "M owner did not reach closed cache valve");
    check(s.d.get_io$$livePrivilege() == 3 && s.d.get_io$$cacheLivePrivilege() == 1,
        s.where("component fixture did not separate real M owner from live S cache input"));
    if (negative) {
        s.injected = true;
        std::cerr << "INJECT cache context owner=" << id << " original_privilege=3 cache_live_privilege=1\n";
    }
    s.allowCache = true; s.drain();
    check(!negative, s.where("cache-context mutation did not change the actual line authorization"));
    check(s.c.machine64 == 1 && s.c.get64 == 1 && !s.c.get8 && !s.contextMismatch,
        s.where("legal M owner did not retain whole-line authorization under live S input"));
    return s.c;
}
} // namespace

int main(int argc, char **argv) {
    try {
        check(argc == 1 || (argc == 2 && std::string_view(argv[1]) == "--inject-cache-context"),
            "usage: fetch-owner-permission [--inject-cache-context]");
        checkLineImplication();
        if (argc == 2) { cacheContextContract(true); return 2; }
        Counts total;
        total.add(heldCase(1, 1)); total.add(heldCase(0, 2));
        total.add(heldCase(1, 3)); total.add(heldCase(0, 3));
        total.add(faultCases()); total.add(lockedCase()); total.add(cacheContextContract(false));
        total.add(mixedQueue()); total.add(heldCacheCase());
        check(total.mask1 && total.mask2 && total.old8 && total.machine64 && total.locked8 && total.faultOnly == 2 &&
            total.trapOldHeld && total.flow && total.queued && total.responseHeld,
            "permission oracle directed coverage incomplete");
        std::cout << "PASS FETCH_OWNER_PERMISSION accepted=" << total.accepted << " returned=" << total.returned
            << " Get4=" << total.get4 << " Get8=" << total.get8 << " Get64=" << total.get64
            << " mask1_4B=" << total.mask1 << " mask2_4B=" << total.mask2 << " old8B=" << total.old8
            << " M64B=" << total.machine64 << " lockedM8B=" << total.locked8 << " fault_only=" << total.faultOnly
            << " trap_oldheld=" << total.trapOldHeld << " trap_cacheheld=" << total.trapCacheHeld
            << " queue=" << total.queued << " flow=" << total.flow << " mixed_queue=" << total.mixedQueued
            << " max_queue=" << total.maximumQueue << " max_owners=" << total.maximumOwners
            << " buffer_held=" << total.bufferHeld << " cache_held=" << total.cacheHeld
            << " response_held=" << total.responseHeld << " A_held=" << total.aHeld << " D_held=" << total.dHeld
            << " real_system_commands=" << total.csrCommands << '\n';
        return 0;
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
