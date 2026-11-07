#include "FpGuestMemoryGsim.h"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

// Independent byte-memory, page-table and architectural state oracle. Only the
// native physical/PTE ports receive responses; FP result inputs do not exist.
// Pins: RV64 F/D and H v20250508. This is NOT architectural CPU retirement.
constexpr uint64_t MODE = uint64_t{8} << 60;
constexpr uint64_t V = 1, R = 2, W = 4, X = 8, U = 16, A = 64, D = 128;
enum class Fault { None, Misaligned, VsPage, ExplicitGuest, ImplicitGuest, Pmp, Pma, Bus };
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token&) const = default;
};
struct Envelope {
    Token token;
    uint64_t data = 0, nextPc = 0, cause = 0, tval = 0, gpa = 0;
    bool exception = false, guestPage = false, guestAddress = false, implicit = false;
    bool operator==(const Envelope&) const = default;
};
struct Request {
    uint64_t address = 0, data = 0, epoch = 0;
    unsigned mask = 0, size = 0, atomicOp = 0;
    bool write = false, atomic = false, uncached = false, virtualized = false;
    bool prechecked = false, prefetch = false;
    bool operator==(const Request&) const = default;
};
struct Reply {
    uint64_t data = 0, gpa = 0;
    bool error = false, page = false, guestPage = false, guestAddress = false, implicit = false;
    bool operator==(const Reply&) const = default;
};
struct Case {
    std::string name;
    unsigned kind = 0, mode = 2, privilege = 1, destination = 2;
    // kind 0=FLW, 1=FSW, 2=FLD, 3=FSD; mode 0=Bare/Bare, 1=Bare/G, 2=VS/G.
    Fault fault = Fault::None;
    unsigned lane = 0;
    bool userLeaf = false, sum = false, setup = false;
    uint64_t raw = 0x7ff01234ff800001ULL;
    uint64_t va = 0, gpa = 0, pa = 0, vsatp = 0, hgatp = 0, pmpTop = (uint64_t{1} << 54) - 1;
    uint64_t implicitGpa = 0;
    std::map<uint64_t, uint64_t> ptes;
    bool store() const { return kind & 1; }
    unsigned size() const { return kind < 2 ? 2 : 3; }
    bool faulted() const { return fault != Fault::None; }
    bool physical() const { return fault == Fault::None || fault == Fault::Bus; }
    unsigned cause() const {
        if (fault == Fault::Misaligned) return store() ? 6 : 4;
        if (fault == Fault::VsPage) return store() ? 15 : 13;
        if (fault == Fault::ExplicitGuest || fault == Fault::ImplicitGuest) return store() ? 23 : 21;
        return store() ? 7 : 5;
    }
};
static uint64_t pte(uint64_t address, uint64_t flags) { return ((address >> 12) << 10) | flags; }
static void mapG(Case& c, uint64_t guest, uint64_t physical, unsigned level, uint64_t flags) {
    uint64_t table = 0x200000;
    for (int l = 2; l >= int(level); --l) {
        const unsigned bits = l == 2 ? 11 : 9;
        const uint64_t at = table + ((guest >> (12 + l * 9)) & ((uint64_t{1} << bits) - 1)) * 8;
        if (l == int(level)) { c.ptes[at] = pte(physical, flags); return; }
        const uint64_t next = 0x400000 + ((guest >> 30) & 2047) * 0x3000 + (2 - l) * 0x1000;
        c.ptes[at] = pte(next, V);
        table = next;
    }
}
static Case prepare(Case c) {
    const uint64_t off = c.lane + (c.fault == Fault::Misaligned ? 1 : 0);
    c.va = (c.mode == 0 ? 0x60005000ULL : c.mode == 1 ? 0x112345000ULL : 0x12345000ULL) + off;
    c.gpa = c.mode == 2 ? 0x80000000 + off : c.va;
    c.pa = (c.mode == 2 ? 0xc0000000ULL : 0x60005000ULL) + off;
    if (c.mode != 0) {
        c.hgatp = MODE | 0x200;
        uint64_t gflags = V | R | W | U | A | D;
        if (c.fault == Fault::ExplicitGuest) gflags &= ~U;
        mapG(c, c.gpa, c.pa & ~uint64_t{4095}, 0, gflags);
    }
    if (c.mode == 1) c.pmpTop = 0x80000000ULL >> 2; // GVA outside, SPA and tables inside.
    if (c.mode == 2) {
        c.vsatp = MODE | 0x100;
        uint64_t implicitFlags = V | R | U | A;
        if (c.fault == Fault::ImplicitGuest) implicitFlags &= ~U;
        mapG(c, 0x100000, 0x40000000, 2, implicitFlags);
        uint64_t table = 0x100000;
        for (int l = 2; l >= 0; --l) {
            const uint64_t address = table + ((c.va >> (12 + 9 * l)) & 511) * 8;
            if (l == 2) c.implicitGpa = address;
            uint64_t flags = V | R | W | A | D | (c.userLeaf ? U : 0);
            if (c.fault == Fault::VsPage && c.privilege == 1) flags &= ~(R | W);
            if (l == 0) c.ptes[0x40000000 + address] = pte(0x80000000, flags);
            else c.ptes[0x40000000 + address] = pte(table + 0x1000, V);
            table += 0x1000;
        }
    }
    if (c.fault == Fault::Pmp) c.pmpTop = 0x80000000ULL >> 2;
    return c;
}
static std::vector<Case> matrix() {
    std::vector<Case> cases;
    const std::array<std::string, 4> ops{"flw", "fsw", "fld", "fsd"};
    for (unsigned mode = 0; mode < 3; ++mode) for (unsigned op = 0; op < 4; ++op)
        for (unsigned lane = 0; lane <= (op < 2 ? 4U : 0U); lane += 4) {
            Case c; c.name = "success_" + std::to_string(mode) + "_" + ops[op] + "_" + std::to_string(lane);
            c.kind = op; c.mode = mode; c.lane = lane;
            // FLW carries raw sNaN/qNaN payloads; FSW source is deliberately unboxed.
            c.raw = op == 1 ? 0x01234567ff800001ULL : lane ? 0xffc12345ULL : 0x7ff012347f800001ULL;
            cases.push_back(prepare(c));
        }
    const std::array<std::string, 7> names{"misaligned", "vs_page", "explicit_guest", "implicit_guest", "pmp", "pma", "bus"};
    // Interleave classes so unrelated exception kinds immediately follow each other.
    for (unsigned op = 0; op < 4; ++op) for (unsigned f = 1; f <= 7; ++f) {
        Case c; c.kind = op; c.fault = Fault(f); c.name = names[f - 1] + "_" + ops[op];
        c.raw = 0x02345678ffc12345ULL; cases.push_back(prepare(c));
    }
    for (unsigned op = 0; op < 4; ++op) {
        Case c; c.kind = op; c.privilege = 0; c.userLeaf = op == 1 || op == 2;
        c.fault = c.userLeaf ? Fault::None : Fault::VsPage;
        c.name = "vu_" + ops[op] + (c.userLeaf ? "_user_allowed" : "_supervisor_denied");
        cases.push_back(prepare(c));
    }
    return cases;
}

class Bench {
    SFpGuestMemoryGsim d{};
    std::ofstream* trace;
    std::string negative;
    unsigned schedule;
    std::array<uint64_t, 32> registers{};
    std::map<uint64_t, uint8_t> bytes;
    unsigned fs = 0, fcsr = 0;
    uint64_t sequence = 0;
public:
    uint64_t cycles = 0, commands = 0, mainCases = 0, setups = 0, faults = 0, physicalRequests = 0;
    uint64_t physicalResponses = 0, pteRequests = 0, pteResponses = 0, lsuAccepts = 0, adapterAccepts = 0;
    uint64_t responseBuffers = 0, heldPhysical = 0, heldPte = 0, heldCompletions = 0;
    uint64_t wrongTags = 0, wrongIndices = 0, deniedHead = 0, mutations = 0;
    uint64_t contextBefore = 0, contextAfter = 0, pmaChecks = 0;
    std::array<unsigned, 8> faultRows{};
    std::array<unsigned, 3> modeRows{};
    std::array<unsigned, 4> opRows{};
    Bench(unsigned s, std::string n, std::ofstream* t) : trace(t), negative(std::move(n)), schedule(s) {
        d.LOG_START = 1; d.activateAll(); defaults();
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        // Idle-only reset. Real authorized FS/fcsr initialization, no FPR injection.
        d.set_io$$setFs$$valid(1); d.set_io$$setFs$$bits(2); idleTick(1); fs = 2;
        d.set_io$$setFs$$valid(0); d.set_io$$csr$$valid(1); d.set_io$$csr$$bits$$write(1);
        d.set_io$$csr$$bits$$value(0x75); idleTick(2); fs = 3; fcsr = 0x75;
        d.set_io$$csr$$valid(0); idleTick(3);
    }
    void check(bool ok, const std::string& name, const std::string& detail) const {
        if (!ok) throw std::runtime_error("FP_GUEST_MEMORY_CHECK[" + name + "]: " + detail);
    }
    void defaults() {
        d.set_io$$issueValid(0); d.set_io$$instruction(0x0000b107); d.set_io$$base(0); d.set_io$$pc(0);
        d.set_io$$token$$index(0); d.set_io$$token$$tag(0); d.set_io$$headAuthorized(1);
        d.set_io$$retire$$valid(0); d.set_io$$retire$$bits$$index(0); d.set_io$$retire$$bits$$tag(0);
        d.set_io$$setFs$$valid(0); d.set_io$$setFs$$bits(0); d.set_io$$guestFs(2);
        d.set_io$$csr$$valid(0); d.set_io$$csr$$bits$$address(3); d.set_io$$csr$$bits$$operation(0);
        d.set_io$$csr$$bits$$write(0); d.set_io$$csr$$bits$$value(0);
        context(Case{}, false, false); d.set_io$$hostSatp(0);
        d.set_io$$pmpTop((uint64_t{1} << 54) - 1); d.set_io$$pmpPermission(7); d.set_io$$pmaDenied(0);
        d.set_io$$physical$$request$$ready(0); d.set_io$$physical$$response$$valid(0);
        d.set_io$$physical$$response$$bits$$data(0); d.set_io$$physical$$response$$bits$$error(0);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(0); d.set_io$$pte$$response$$valid(0);
        d.set_io$$pte$$response$$bits$$data(0); d.set_io$$pte$$response$$bits$$error(0);
    }
    void context(const Case& c, bool selected, bool perturb) {
        d.set_io$$context$$virtualAddress(perturb ? 0x9876543210ULL : 0x123);
        d.set_io$$context$$vsatp(perturb ? 0x8765432112345678ULL : selected ? c.vsatp : 0);
        d.set_io$$context$$hgatp(perturb ? 0x876543219abcdef0ULL : selected ? c.hgatp : 0);
        d.set_io$$context$$virtualized(selected && !perturb);
        d.set_io$$context$$effectivePrivilege(perturb ? 0 : selected ? c.privilege : 1);
        d.set_io$$context$$access(3); d.set_io$$context$$size(0);
        d.set_io$$context$$vsSum(perturb || c.sum); d.set_io$$context$$vsMxr(perturb);
        d.set_io$$context$$hsMxr(perturb); d.set_io$$context$$forceExecute(0);
        d.set_io$$context$$epoch(perturb ? 0xe3 : 0x51);
    }
    std::array<uint64_t, 32> observedRegisters() {
        return {
            d.get_io$$f0(), d.get_io$$f1(), d.get_io$$f2(), d.get_io$$f3(),
            d.get_io$$f4(), d.get_io$$f5(), d.get_io$$f6(), d.get_io$$f7(),
            d.get_io$$f8(), d.get_io$$f9(), d.get_io$$f10(), d.get_io$$f11(),
            d.get_io$$f12(), d.get_io$$f13(), d.get_io$$f14(), d.get_io$$f15(),
            d.get_io$$f16(), d.get_io$$f17(), d.get_io$$f18(), d.get_io$$f19(),
            d.get_io$$f20(), d.get_io$$f21(), d.get_io$$f22(), d.get_io$$f23(),
            d.get_io$$f24(), d.get_io$$f25(), d.get_io$$f26(), d.get_io$$f27(),
            d.get_io$$f28(), d.get_io$$f29(), d.get_io$$f30(), d.get_io$$f31()
        };
    }
    Request request(bool physical) {
        Request r;
#define REQUEST(prefix) \
        r.address = d.get_io$$##prefix##$$bits$$address(); r.data = d.get_io$$##prefix##$$bits$$data(); \
        r.mask = d.get_io$$##prefix##$$bits$$mask(); r.size = d.get_io$$##prefix##$$bits$$size(); \
        r.write = d.get_io$$##prefix##$$bits$$write(); r.atomic = d.get_io$$##prefix##$$bits$$atomic(); \
        r.atomicOp = d.get_io$$##prefix##$$bits$$atomicOp(); r.uncached = d.get_io$$##prefix##$$bits$$uncached(); \
        r.virtualized = d.get_io$$##prefix##$$bits$$virtualized(); r.prechecked = d.get_io$$##prefix##$$bits$$precheckedLoad(); \
        r.epoch = d.get_io$$##prefix##$$bits$$translationEpoch(); r.prefetch = d.get_io$$##prefix##$$bits$$prefetchNextAllowed()
        if (physical) { REQUEST(physical$$request); } else { REQUEST(virtualRequest); }
#undef REQUEST
        return r;
    }
    Envelope envelope(bool pipeline) {
        Envelope e;
#define ENVELOPE(prefix) \
        e.token = {unsigned(d.get_io$$##prefix##$$bits$$token$$index()), d.get_io$$##prefix##$$bits$$token$$tag()}; \
        e.data = d.get_io$$##prefix##$$bits$$data(); e.nextPc = d.get_io$$##prefix##$$bits$$nextPc(); \
        e.exception = d.get_io$$##prefix##$$bits$$exception(); e.cause = d.get_io$$##prefix##$$bits$$cause(); \
        e.tval = d.get_io$$##prefix##$$bits$$tval(); e.gpa = d.get_io$$##prefix##$$bits$$guestFault$$guestPhysicalAddress(); \
        e.guestPage = d.get_io$$##prefix##$$bits$$guestFault$$guestPageFault(); \
        e.guestAddress = d.get_io$$##prefix##$$bits$$guestFault$$guestAddress(); \
        e.implicit = d.get_io$$##prefix##$$bits$$guestFault$$implicitPte()
        if (pipeline) { ENVELOPE(pipelineComplete); } else { ENVELOPE(complete); }
#undef ENVELOPE
        return e;
    }
    Reply reply(bool buffered) {
        Reply r;
#define REPLY(prefix, meta) \
        r.data = d.get_io$$##prefix##$$bits$$data(); r.error = d.get_io$$##prefix##$$bits$$error(); \
        r.page = d.get_io$$##prefix##$$bits$$pageFault(); r.gpa = d.get_io$$##meta##$$guestPhysicalAddress(); \
        r.guestPage = d.get_io$$##meta##$$guestPageFault(); r.guestAddress = d.get_io$$##meta##$$guestAddress(); \
        r.implicit = d.get_io$$##meta##$$implicitPte()
        if (buffered) { REPLY(bufferedResponse, bufferedFault); } else { REPLY(adapterResponse, adapterFault); }
#undef REPLY
        return r;
    }
    static void writeEnvelope(std::ostream& o, const Envelope& e) {
        o << '[' << e.token.index << ',' << e.token.tag << ',' << e.data << ',' << e.nextPc << ',' << e.exception
          << ',' << e.cause << ',' << e.tval << ',' << e.guestPage << ',' << e.guestAddress << ',' << e.gpa << ',' << e.implicit << ']';
    }
    static void writeRequest(std::ostream& o, const Request& r) {
        o << '[' << r.address << ',' << r.data << ',' << r.mask << ',' << r.size << ',' << r.write << ',' << r.atomic
          << ',' << r.atomicOp << ',' << r.uncached << ',' << r.virtualized << ',' << r.prechecked << ',' << r.epoch << ',' << r.prefetch << ']';
    }
    static void writeReply(std::ostream& o, const Reply& r) {
        o << '[' << r.data << ',' << r.error << ',' << r.page << ',' << r.guestPage << ',' << r.guestAddress << ',' << r.gpa << ',' << r.implicit << ']';
    }
    void checkState(bool inject = false) {
        auto actual = observedRegisters();
        if (inject && negative == "state_mutation") actual[31] ^= 1;
        check(actual == registers && d.get_io$$fcsr() == fcsr && d.get_io$$fs() == fs,
            "state_mutation", "FPR/fcsr/FS changed outside an accepted successful load or authorized idle CSR access");
    }
    void idleTick(unsigned initialization) {
        d.step(); ++cycles; checkState();
        if (trace) {
            *trace << "{\"schedule\":" << schedule << ",\"cycle\":" << cycles << ",\"event\":\"idle_init\",\"fs\":"
                << unsigned(d.get_io$$fs()) << ",\"fcsr\":" << unsigned(d.get_io$$fcsr())
                << ",\"set_fs\":[" << (initialization == 1) << ",2],\"csr\":[" << (initialization == 2) << ",3,0,1,117]}\n";
        }
    }
    uint64_t beat(uint64_t address) const {
        uint64_t data = 0;
        for (unsigned n = 0; n < 8; ++n) data |= uint64_t(bytes.at((address & ~uint64_t{7}) + n)) << (n * 8);
        return data;
    }
    void run(Case c) {
        ++sequence;
        const Token token{5, 0x1357000000000000ULL ^ ((sequence & 1) << 63) ^ (sequence << 33) ^ 0x7b};
        const int offset = sequence & 1 ? -16 : 8;
        const unsigned imm = unsigned(offset) & 4095;
        const uint32_t instruction = c.store() ? ((imm >> 5) << 25) | (1U << 20) | (3U << 15) |
            (c.size() << 12) | ((imm & 31) << 7) | 0x27 : (imm << 20) | (3U << 15) |
            (c.size() << 12) | (c.destination << 7) | 7;
        const uint64_t pc = 0x80200000 + sequence * 4;
        const uint64_t base = c.va - uint64_t(offset);
        const unsigned width = 1U << c.size();
        const uint64_t aligned = c.pa & ~uint64_t{7};
        bytes.clear();
        for (uint64_t at = aligned - 8; at < aligned + 16; ++at) bytes[at] = uint8_t(0x91 + at % 23);
        if (!c.store()) for (unsigned n = 0; n < width; ++n) bytes[c.pa + n] = uint8_t(c.raw >> (8 * n));
        const auto beforeBytes = bytes;
        if (trace) {
            auto& o = *trace;
            o << "{\"schedule\":" << schedule << ",\"cycle\":" << cycles << ",\"event\":\"memory_init\",\"case\":\"" << c.name
              << "\",\"bytes\":[";
            bool first = true;
            for (const auto& [address, value] : bytes) { o << (first ? "" : ",") << '[' << address << ',' << unsigned(value) << ']'; first = false; }
            o << "],\"ptes\":["; first = true;
            for (const auto& [address, value] : c.ptes) { o << (first ? "" : ",") << '[' << address << ',' << value << ']'; first = false; }
            o << "]}\n";
        }
        const uint64_t source = registers[(instruction >> 20) & 31];
        const uint64_t expectedLoad = c.size() == 2 ? c.raw & UINT32_MAX : c.raw;
        bool issued = false, prepared = false, captured = false, executed = false, retired = false;
        bool ptePending = false, physPending = false;
        unsigned pteDelay = 0, physDelay = 0, completionCycles = 0, physicalCount = 0, responseCount = 0;
        uint64_t pteData = 0, physicalData = 0;
        std::optional<Request> heldRequest;
        std::optional<uint64_t> heldPteAddress;
        std::optional<Envelope> heldComplete, pipeline;
        std::optional<Reply> adapterReply;
        unsigned drainCycles = 0;
        for (unsigned local = 0; local < 900; ++local) {
            const bool perturb = captured;
            context(c, prepared, perturb);
            d.set_io$$pmpTop(c.pmpTop); d.set_io$$pmpPermission(7); d.set_io$$pmaDenied(c.fault == Fault::Pma);
            d.set_io$$issueValid(!issued); d.set_io$$instruction(instruction); d.set_io$$base(base); d.set_io$$pc(pc);
            d.set_io$$token$$index(token.index); d.set_io$$token$$tag(token.tag);
            const bool pteReady = schedule == 0 ? local % 4 != 0 : local % 7 >= 3;
            const bool physicalReady = schedule == 0 ? local % 5 >= 2 : local % 9 >= 5;
            const bool pteValid = ptePending && pteDelay == 0;
            const bool physicalValid = physPending && physDelay == 0;
            d.set_io$$pte$$request$$ready(pteReady); d.set_io$$pte$$response$$valid(pteValid);
            d.set_io$$pte$$response$$bits$$data(pteData); d.set_io$$pte$$response$$bits$$error(0);
            d.set_io$$physical$$request$$ready(physicalReady); d.set_io$$physical$$response$$valid(physicalValid);
            d.set_io$$physical$$response$$bits$$data(physicalData);
            d.set_io$$physical$$response$$bits$$error(c.fault == Fault::Bus);
            d.set_io$$physical$$response$$bits$$pageFault(0);
            Token grant = token;
            const bool grantValid = completionCycles >= 2 && !retired;
            const bool head = completionCycles != 5;
            if (completionCycles == 2) grant.tag ^= uint64_t{1} << 63;
            if (completionCycles == 3) grant.tag ^= uint64_t{1} << 33;
            if (completionCycles == 4) grant.index ^= 1;
            d.set_io$$retire$$valid(grantValid); d.set_io$$retire$$bits$$index(grant.index);
            d.set_io$$retire$$bits$$tag(grant.tag); d.set_io$$headAuthorized(head);
            d.step(); ++cycles;
            check(cycles <= 30000, "trace_bound", "schedule exceeded 30000 edges");
            // The generated GSIM step exposes this edge's combinational observations
            // before sequential updates. Trace them BEFORE any negative corruption.
            if (trace) {
                auto& o = *trace;
                o << "{\"schedule\":" << schedule << ",\"cycle\":" << cycles << ",\"case\":\"" << c.name
                  << "\",\"command\":[" << !issued << ',' << token.index << ',' << token.tag << ',' << instruction << ',' << base << ',' << pc
                  << "],\"context\":[" << (prepared && !perturb) << ',' << (perturb ? 0 : prepared ? c.privilege : 1)
                  << ',' << (perturb ? 0x8765432112345678ULL : prepared ? c.vsatp : 0)
                  << ',' << (perturb ? 0x876543219abcdef0ULL : prepared ? c.hgatp : 0)
                  << ',' << (perturb || c.sum) << ',' << perturb << ',' << perturb << ',' << (perturb ? 0xe3 : 0x51)
                  << ',' << c.pmpTop << ',' << 7 << ',' << (c.fault == Fault::Pma)
                  << "],\"handshake\":[" << bool(d.get_io$$issueReady()) << ',' << bool(d.get_io$$executeValid()) << ','
                  << bool(d.get_io$$executeFire()) << ',' << bool(d.get_io$$adapterFire()) << ',' << bool(d.get_io$$translatedHandling())
                  << "],\"pma\":[" << bool(d.get_io$$physicalCheck$$valid()) << ',' << d.get_io$$physicalCheck$$bits$$address()
                  << ',' << unsigned(d.get_io$$physicalCheck$$bits$$size()) << ',' << unsigned(d.get_io$$physicalCheck$$bits$$access())
                  << ',' << bool(d.get_io$$physicalCheck$$bits$$atomic()) << ',' << bool(d.get_io$$physicalCheck$$bits$$forceExecute())
                  << "],\"retire\":[" << grantValid << ',' << grant.index << ',' << grant.tag << ',' << head << ',' << bool(d.get_io$$retireAccepted())
                  << "],\"pte\":[" << bool(d.get_io$$pte$$request$$valid()) << ',' << pteReady << ',' << d.get_io$$pte$$request$$bits()
                  << ',' << pteValid << ',' << bool(d.get_io$$pte$$response$$ready()) << ',' << pteData
                  << "],\"physical\":[" << bool(d.get_io$$physical$$request$$valid()) << ',' << physicalReady << ',';
                writeRequest(o, request(true));
                o << ',' << physicalValid << ',' << bool(d.get_io$$physical$$response$$ready()) << ',' << physicalData << ',' << (c.fault == Fault::Bus)
                  << "],\"virtual_request\":[" << bool(d.get_io$$virtualRequest$$valid()) << ','; writeRequest(o, request(false));
                o << "],\"adapter_response\":[" << bool(d.get_io$$adapterResponse$$valid()) << ',' << bool(d.get_io$$adapterResponseFire()) << ',';
                writeReply(o, reply(false)); o << ',' << unsigned(d.get_io$$responseEpoch()) << "],\"buffer_response\":["
                  << bool(d.get_io$$bufferedResponse$$valid()) << ',' << bool(d.get_io$$bufferedResponseFire()) << ','; writeReply(o, reply(true));
                o << "],\"pipeline\":[" << bool(d.get_io$$pipelineComplete$$valid()) << ','; writeEnvelope(o, envelope(true));
                o << "],\"converted\":[" << bool(d.get_io$$convertedResult$$valid()) << ',' << unsigned(d.get_io$$convertedResult$$bits$$token$$index())
                  << ',' << d.get_io$$convertedResult$$bits$$token$$tag() << ',' << d.get_io$$convertedResult$$bits$$value()
                  << ',' << unsigned(d.get_io$$convertedResult$$bits$$flags()) << ',' << bool(d.get_io$$convertedResult$$bits$$exception())
                  << ',' << unsigned(d.get_io$$convertedResult$$bits$$cause()) << ',' << d.get_io$$convertedResult$$bits$$tval()
                  << ',' << bool(d.get_io$$convertedResult$$bits$$guestFault$$guestPageFault())
                  << ',' << bool(d.get_io$$convertedResult$$bits$$guestFault$$guestAddress())
                  << ',' << d.get_io$$convertedResult$$bits$$guestFault$$guestPhysicalAddress()
                  << ',' << bool(d.get_io$$convertedResult$$bits$$guestFault$$implicitPte());
                o << "],\"complete\":[" << bool(d.get_io$$complete$$valid()) << ','; writeEnvelope(o, envelope(false));
                o << "],\"state\":[" << unsigned(d.get_io$$fs()) << ',' << unsigned(d.get_io$$fcsr()) << ','
                  << bool(d.get_io$$mutation$$valid()) << ',' << bool(d.get_io$$mutation$$bits$$guest()) << "],\"fpr\":[";
                auto observed = observedRegisters(); for (unsigned i = 0; i < 32; ++i) o << (i ? "," : "") << observed[i];
                o << "],\"idle\":[" << !bool(d.get_io$$stateBusy()) << ',' << !bool(d.get_io$$memoryBusy()) << ','
                  << bool(d.get_io$$adapterIdle()) << ',' << bool(d.get_io$$translatorIdle()) << "]}\n";
            }
            checkState(completionCycles == 2);
            if (!issued && d.get_io$$issueReady()) { issued = true; ++commands; }
            if (d.get_io$$executeValid() && !d.get_io$$executeFire() && !prepared) { prepared = true; ++contextBefore; }
            if (d.get_io$$executeFire()) {
                check(prepared && !executed && d.get_io$$translatedHandling(), "guest_address", "LSU accepted without live guest translated handling");
                executed = true; ++lsuAccepts;
            }
            if (d.get_io$$adapterFire()) {
                check(executed && !captured, "credits", "adapter capture has no accepted LSU owner");
                captured = true; ++adapterAccepts; ++contextAfter;
                const auto r = request(false);
                check(r.address == c.va && r.virtualized && r.size == c.size() && r.write == c.store(),
                    "guest_address", "native virtual request lost accepted guest operation");
            }
            if (ptePending && pteDelay) --pteDelay;
            if (pteValid && d.get_io$$pte$$response$$ready()) { check(ptePending, "credits", "PTE response without credit"); ptePending = false; ++pteResponses; }
            const bool pteOffer = d.get_io$$pte$$request$$valid();
            const uint64_t pteAddress = d.get_io$$pte$$request$$bits();
            if (heldPteAddress) check(pteOffer && pteAddress == *heldPteAddress, "held_pte", "PTE valid/payload changed while held");
            heldPteAddress = pteOffer && !pteReady ? std::optional<uint64_t>(pteAddress) : std::nullopt;
            heldPte += bool(heldPteAddress);
            if (pteOffer) check(c.ptes.count(pteAddress), "pte_address", "unexpected physical PTE address");
            if (pteOffer && pteReady) {
                check(!ptePending, "credits", "multiple outstanding PTE reads");
                pteData = c.ptes.at(pteAddress); ptePending = true; pteDelay = 1 + (schedule ? (local % 4) : 1); ++pteRequests;
            }
            if (physPending && physDelay) --physDelay;
            if (physicalValid && d.get_io$$physical$$response$$ready()) {
                check(physPending, "credits", "physical response without credit"); physPending = false; ++responseCount; ++physicalResponses;
            }
            const bool offer = d.get_io$$physical$$request$$valid();
            const auto rawRequest = request(true);
            if (heldRequest) check(offer && rawRequest == *heldRequest, "held_physical", "physical valid/payload changed while held");
            heldRequest = offer && !physicalReady ? std::optional<Request>(rawRequest) : std::nullopt;
            heldPhysical += bool(heldRequest);
            if (d.get_io$$physicalCheck$$valid()) {
                ++pmaChecks;
                check(c.fault == Fault::None || c.fault == Fault::Pma || c.fault == Fault::Bus,
                    "faultclass", "denied translation reached final PMA");
                check(d.get_io$$physicalCheck$$bits$$address() == c.pa && d.get_io$$physicalCheck$$bits$$size() == c.size() &&
                    d.get_io$$physicalCheck$$bits$$access() == unsigned(c.store()) && !d.get_io$$physicalCheck$$bits$$atomic() &&
                    !d.get_io$$physicalCheck$$bits$$forceExecute(), "physical_address", "PMA query did not name final SPA operation");
            }
            if (offer) {
                check(c.physical(), "faultclass", "denied access offered final physical data traffic");
                auto r = rawRequest;
                if (negative == "physical_address") r.address ^= 8;
                if (negative == "physical_mask") r.mask ^= 1;
                check(r.address == c.pa, "physical_address", "physical SPA mismatch");
                check(r.mask == (((1U << width) - 1) << (c.va % 8)), "physical_mask", "physical byte mask mismatch");
                check(r.data == (source << (8 * (c.va % 8))) && r.size == c.size() && r.write == c.store() &&
                    !r.atomic && !r.atomicOp && !r.uncached && !r.virtualized && !r.prechecked && !r.epoch && !r.prefetch,
                    "physical_payload", "native physical operation/data/proof mismatch");
                if (physicalReady) {
                    check(!physPending && physicalCount == 0, "credits", "duplicate physical request");
                    physicalData = beat(c.pa); physPending = true; physDelay = schedule ? 4 : 2;
                    ++physicalCount; ++physicalRequests;
                    if (c.store() && c.fault != Fault::Bus) for (unsigned n = 0; n < 8; ++n)
                        if (r.mask & (1U << n)) bytes[aligned + n] = uint8_t(r.data >> (n * 8));
                }
            }
            if (d.get_io$$adapterResponseFire()) {
                check(!ptePending && !physPending, "credits", "adapter replied before child responses drained");
                adapterReply = reply(false);
                check(d.get_io$$responseEpoch() == 0x51, "guest_address", "response epoch used perturbed context");
            }
            if (d.get_io$$bufferedResponseFire()) {
                check(adapterReply && reply(true) == *adapterReply, "buffer_metadata", "joint response/fault envelope changed"); ++responseBuffers;
            }
            if (d.get_io$$pipelineComplete$$valid()) {
                check(!pipeline, "credits", "duplicate pipeline completion"); pipeline = envelope(true);
                const auto& e = *pipeline;
                check(d.get_io$$convertedResult$$valid() && d.get_io$$convertedResult$$bits$$token$$index() == e.token.index &&
                    d.get_io$$convertedResult$$bits$$token$$tag() == e.token.tag && d.get_io$$convertedResult$$bits$$value() == e.data &&
                    !d.get_io$$convertedResult$$bits$$flags() && bool(d.get_io$$convertedResult$$bits$$exception()) == e.exception &&
                    d.get_io$$convertedResult$$bits$$cause() == e.cause && d.get_io$$convertedResult$$bits$$tval() == e.tval &&
                    bool(d.get_io$$convertedResult$$bits$$guestFault$$guestPageFault()) == e.guestPage &&
                    bool(d.get_io$$convertedResult$$bits$$guestFault$$guestAddress()) == e.guestAddress &&
                    d.get_io$$convertedResult$$bits$$guestFault$$guestPhysicalAddress() == e.gpa &&
                    bool(d.get_io$$convertedResult$$bits$$guestFault$$implicitPte()) == e.implicit,
                    "conversion", "production memory-to-result conversion changed envelope");
            }
            const bool complete = d.get_io$$complete$$valid();
            const auto rawComplete = envelope(false);
            if (heldComplete) check(complete && rawComplete == *heldComplete, "held_completion", "full held completion envelope changed");
            if (complete) {
                check(pipeline && rawComplete == *pipeline, "conversion", "production result-to-backend conversion changed envelope");
                auto e = rawComplete;
                if (negative == "faultclass" && c.faulted()) e.cause ^= 1;
                if (negative == "gpa" && e.guestPage) e.gpa ^= 4;
                if (negative == "fpdata" && !c.store() && !c.faulted()) e.data ^= 1;
                if (negative == "token") e.token.tag ^= uint64_t{1} << 63;
                if (negative == "guest_address") e.guestAddress = !e.guestAddress;
                check(e.token == token, "token", "full completion token mismatch");
                check(e.exception == c.faulted() && (!e.exception || e.cause == c.cause()), "faultclass", "precise load/store fault class mismatch");
                const bool gpf = c.fault == Fault::ExplicitGuest || c.fault == Fault::ImplicitGuest;
                check(e.guestPage == gpf && e.implicit == (c.fault == Fault::ImplicitGuest), "faultclass", "guest fault/implicit classification mismatch");
                check(e.gpa == (gpf ? c.fault == Fault::ImplicitGuest ? c.implicitGpa : c.gpa : 0), "gpa", "unshifted GPA or stale metadata mismatch");
                check(e.guestAddress, "guest_address", "routed accepted guest address provenance missing");
                check(e.tval == c.va && e.nextPc == pc + 4, "fault_address", "original GVA or next PC mismatch");
                if (!c.faulted()) check(e.data == (c.store() ? 0 : expectedLoad), "fpdata", "raw FP load/store completion data mismatch");
                check(physicalCount == unsigned(c.physical()) && responseCount == physicalCount,
                    "credits", "physical operation/response count mismatch");
                ++completionCycles; ++heldCompletions;
            }
            bool retireAccepted = d.get_io$$retireAccepted();
            const bool correctGrant = complete && grantValid && head && grant == token;
            check(retireAccepted == correctGrant, "token", "wrong/blocked grant retired the component owner");
            check(bool(d.get_io$$mutation$$valid()) == (retireAccepted && !c.faulted() && !c.store()),
                "state_mutation", "mutation event did not match successful exact-token load retirement");
            if (d.get_io$$mutation$$valid()) check(d.get_io$$mutation$$bits$$guest(), "state_mutation", "mutation lost guest owner");
            if (complete && grantValid && grant.tag != token.tag) ++wrongTags;
            if (complete && grantValid && grant.index != token.index) ++wrongIndices;
            if (complete && grantValid && !head) ++deniedHead;
            heldComplete = complete && !retireAccepted ? std::optional<Envelope>(rawComplete) : std::nullopt;
            if (retireAccepted) {
                retired = true;
                if (!c.faulted() && !c.store()) {
                    registers[c.destination] = c.size() == 2 ? 0xffffffff00000000ULL | expectedLoad : expectedLoad;
                    fs = 3; ++mutations;
                }
            }
            if (retired && !d.get_io$$stateBusy() && !d.get_io$$memoryBusy() && d.get_io$$adapterIdle() && d.get_io$$translatorIdle()) {
                check(!ptePending && !physPending && !offer && !pteOffer && !complete, "credits", "residual child owner at drain");
                if (++drainCycles == 2) {
                    auto expectedBytes = beforeBytes;
                    if (c.store() && !c.faulted()) for (unsigned n = 0; n < width; ++n) expectedBytes[c.pa + n] = uint8_t(source >> (8 * n));
                    check(bytes == expectedBytes, "physical_mask", "failed store or neighboring sentinel changed");
                    if (trace) {
                        auto& o = *trace;
                        o << "{\"schedule\":" << schedule << ",\"cycle\":" << cycles << ",\"event\":\"memory_final\",\"case\":\"" << c.name << "\",\"bytes\":[";
                        bool first = true;
                        for (const auto& [address, value] : bytes) { o << (first ? "" : ",") << '[' << address << ',' << unsigned(value) << ']'; first = false; }
                        o << "]}\n";
                    }
                    check(executed && captured == (c.fault != Fault::Misaligned), "credits", "missing or unexpected translation owner");
                    if (c.setup) ++setups;
                    else { ++mainCases; ++faultRows[unsigned(c.fault)]; ++modeRows[c.mode]; ++opRows[c.kind]; faults += c.faulted(); }
                    return;
                }
            }
        }
        throw std::runtime_error("FP_GUEST_MEMORY_CHECK[timeout]: " + c.name);
    }
    void runMatrix() {
        for (auto c : matrix()) {
            if (c.store()) {
                Case setup; setup.name = "setup_" + c.name; setup.kind = 2; setup.mode = 0;
                setup.destination = 1; setup.setup = true; setup.raw = c.raw;
                run(prepare(setup));
            }
            run(c);
        }
        check(mainCases == 50 && setups == 25 && commands == 75 && faults == 30 && physicalRequests == 49 &&
            physicalResponses == 49 && adapterAccepts == 71 && lsuAccepts == 75 && responseBuffers == 71,
            "coverage", "matrix/credit totals differ from independently enumerated plan");
        check(wrongTags == 150 && wrongIndices == 75 && deniedHead == 75 && mutations == 35,
            "coverage", "exact-token retirement and mutation rows incomplete");
        check(heldPhysical > 0 && heldPte > 0 && heldCompletions >= 450 && contextBefore == 75 && contextAfter == 71 &&
            pteRequests == pteResponses, "coverage", "stall/context/child-drain coverage incomplete");
    }
    void summary(std::ostream& o) const {
        o << "{\"schedule\":" << schedule << ",\"cycles\":" << cycles << ",\"matrix_cases\":" << mainCases
          << ",\"setup_loads\":" << setups << ",\"commands\":" << commands << ",\"faults\":" << faults
          << ",\"physical_requests\":" << physicalRequests << ",\"physical_responses\":" << physicalResponses
          << ",\"pte_requests\":" << pteRequests << ",\"pte_responses\":" << pteResponses
          << ",\"lsu_accepts\":" << lsuAccepts << ",\"adapter_accepts\":" << adapterAccepts << ",\"buffer_responses\":" << responseBuffers
          << ",\"held_physical\":" << heldPhysical << ",\"held_pte\":" << heldPte << ",\"held_completions\":" << heldCompletions
          << ",\"wrong_tags\":" << wrongTags << ",\"wrong_indices\":" << wrongIndices << ",\"denied_head\":" << deniedHead
          << ",\"mutations\":" << mutations << ",\"context_before_accept\":" << contextBefore << ",\"context_after_capture\":" << contextAfter
          << ",\"pma_checks\":" << pmaChecks << ",\"fault_rows\":[";
        for (unsigned i = 0; i < 8; ++i) o << (i ? "," : "") << faultRows[i];
        o << "],\"mode_rows\":["; for (unsigned i = 0; i < 3; ++i) o << (i ? "," : "") << modeRows[i];
        o << "],\"op_rows\":["; for (unsigned i = 0; i < 4; ++i) o << (i ? "," : "") << opRows[i];
        o << "],\"drained\":true}";
    }
};
int main(int argc, char** argv) {
    try {
        std::string negative, tracePath;
        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--negative" && i + 1 < argc) negative = argv[++i];
            else if (arg == "--trace" && i + 1 < argc) tracePath = argv[++i];
            else throw std::runtime_error("FP_GUEST_MEMORY_CHECK[cli]: invalid argument");
        }
        const std::vector<std::string> negatives{"", "faultclass", "gpa", "physical_address", "physical_mask", "fpdata", "token", "state_mutation", "guest_address"};
        bool known = false; for (const auto& n : negatives) known |= negative == n;
        if (!known) throw std::runtime_error("FP_GUEST_MEMORY_CHECK[cli]: unknown negative");
        std::ofstream trace;
        if (!tracePath.empty()) { trace.open(tracePath); if (!trace) throw std::runtime_error("FP_GUEST_MEMORY_CHECK[trace]: cannot open trace"); }
        Bench first(0, negative, tracePath.empty() ? nullptr : &trace); first.runMatrix();
        Bench second(1, negative, tracePath.empty() ? nullptr : &trace); second.runMatrix();
        if (!negative.empty()) throw std::runtime_error("FP_GUEST_MEMORY_CHECK[negative_not_triggered]: " + negative);
        if (trace.is_open()) { trace.flush(); if (!trace) throw std::runtime_error("FP_GUEST_MEMORY_CHECK[trace]: write failed"); }
        std::cout << "FP_GUEST_MEMORY_PASS {\"schema\":1,\"component_only\":true,\"guest_fd_execution\":false,\"schedules\":[";
        first.summary(std::cout); std::cout << ','; second.summary(std::cout); std::cout << "]}\n";
        return 0;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
