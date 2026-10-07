#include "LoadIssueForwardingGsim.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Request {
    bool valid = false, writes = true, word = false, pcOperand = false, immediateOperand = true;
    unsigned rs1 = 0, rs2 = 0, rd = 1, op = 0;
    bool memory = false, store = false, unsign = false; unsigned size = 3, branch = 0;
    uint64_t immediate = 0, pc = 0;
    uint32_t instruction = 0;
};
struct Input {
    std::array<Request, 2> requests{};
    bool commit = true, recover = false, inclusive = false;
    Token boundary{};
    unsigned inspect = 0;
    bool response = false, error = false, page = false; uint64_t data = 0;
};
struct Result {
    bool valid = false, exception = false;
    Token token{};
    uint64_t data = 0, cause = 0, tval = 0;
};
struct Retired {
    bool valid = false, writes = false;
    Token token{};
    unsigned rd = 0;
    uint64_t data = 0, pc = 0;
    uint32_t instruction = 0;
};
struct Output {
    std::array<bool, 2> allocated{};
    std::array<Token, 2> tokens{};
    std::array<unsigned, 2> destinations{};
    std::array<Result, 2> issued{};
    std::array<Retired, 2> retired{};
    bool recoveryAccepted = false, recovering = false, fault = false;
    Token faultToken{};
    uint64_t faultPc = 0, faultCause = 0, faultTval = 0, inspected = 0;
    unsigned occupancy = 0;
    bool request = false, requestWrite = false, responseReady = false; uint64_t requestData = 0; unsigned requestMask = 0; uint64_t address = 0;
    unsigned size = 0, forwarded = 0;
    bool rawComplete = false, held = false, replacement = false, mixed = false;
    bool redirect = false; Token redirectToken{}; uint64_t redirectTarget = 0;
};
static void drive(SLoadIssueForwardingGsim &dut, const Input &in) {
    dut.set_io$$memory$$request$$ready(1);
    dut.set_io$$memory$$response$$valid(in.response);
    dut.set_io$$memory$$response$$bits$$data(in.data);
    dut.set_io$$memory$$response$$bits$$error(in.error);
    dut.set_io$$memory$$response$$bits$$pageFault(in.page);
#define DRIVE(N) \
    dut.set_io$$allocate##N##$$bits$$mulDiv(0); \
    dut.set_io$$allocate##N##$$bits$$mulDivOp(0); \
    dut.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
    dut.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
    dut.set_io$$allocate##N##$$bits$$memory(in.requests[N].memory); \
    dut.set_io$$allocate##N##$$bits$$fetchFault(0); \
    dut.set_io$$allocate##N##$$bits$$fetchPageFault(0); \
    dut.set_io$$allocate##N##$$bits$$fetchTval(0); \
    dut.set_io$$allocate##N##$$bits$$expandedInstruction(0); \
    dut.set_io$$allocate##N##$$bits$$atomic(0); \
    dut.set_io$$allocate##N##$$bits$$atomicOp(0); \
    dut.set_io$$allocate##N##$$bits$$store(in.requests[N].store); \
    dut.set_io$$allocate##N##$$bits$$memorySize(in.requests[N].size); \
    dut.set_io$$allocate##N##$$bits$$memoryUnsigned(in.requests[N].unsign); \
    dut.set_io$$allocate##N##$$bits$$controlFlow(in.requests[N].branch); \
    dut.set_io$$allocate##N##$$valid(in.requests[N].valid); \
    dut.set_io$$allocate##N##$$bits$$rename$$writesRd(in.requests[N].writes); \
    dut.set_io$$allocate##N##$$bits$$rename$$rs1(in.requests[N].rs1); \
    dut.set_io$$allocate##N##$$bits$$rename$$rs2(in.requests[N].rs2); \
    dut.set_io$$allocate##N##$$bits$$rename$$rd(in.requests[N].rd); \
    dut.set_io$$allocate##N##$$bits$$rename$$pc(in.requests[N].pc); \
    dut.set_io$$allocate##N##$$bits$$rename$$instruction(in.requests[N].instruction); \
    dut.set_io$$allocate##N##$$bits$$system(0); \
    dut.set_io$$allocate##N##$$bits$$operation(in.requests[N].op); \
    dut.set_io$$allocate##N##$$bits$$word(in.requests[N].word); \
    dut.set_io$$allocate##N##$$bits$$usePc(in.requests[N].pcOperand); \
    dut.set_io$$allocate##N##$$bits$$useImmediate(in.requests[N].immediateOperand); \
    dut.set_io$$allocate##N##$$bits$$immediate(in.requests[N].immediate);
    DRIVE(0)
    DRIVE(1)
#undef DRIVE
    dut.set_io$$commitEnable(in.commit);
    dut.set_io$$recover$$valid(in.recover);
    dut.set_io$$recover$$bits$$inclusive(in.inclusive);
    dut.set_io$$recover$$bits$$token$$index(in.boundary.index);
    dut.set_io$$recover$$bits$$token$$tag(in.boundary.tag);
    dut.set_io$$inspectRegister(in.inspect);
}
static Output sample(SLoadIssueForwardingGsim &dut) {
    if (dut.get_io$$issueCount() > 2) throw std::runtime_error("global issue width exceeded");
    Output out;
#define SAMPLE(N) \
    out.destinations[N] = dut.get_io$$renamed##N##$$bits$$destination(); \
    out.allocated[N] = dut.get_io$$renamed##N##$$valid(); \
    out.tokens[N] = {dut.get_io$$renamed##N##$$bits$$token$$index(), \
                     dut.get_io$$renamed##N##$$bits$$token$$tag()}; \
    out.issued[N] = {bool(dut.get_io$$issued##N##$$valid()), \
        bool(dut.get_io$$issued##N##$$bits$$exception()), \
        {dut.get_io$$issued##N##$$bits$$token$$index(), dut.get_io$$issued##N##$$bits$$token$$tag()}, \
        dut.get_io$$issued##N##$$bits$$data(), dut.get_io$$issued##N##$$bits$$cause(), \
        dut.get_io$$issued##N##$$bits$$tval()}; \
    out.retired[N] = {bool(dut.get_io$$commit##N##$$valid()), bool(dut.get_io$$commit##N##$$bits$$writesRd()), \
        {dut.get_io$$commit##N##$$bits$$token$$index(), dut.get_io$$commit##N##$$bits$$token$$tag()}, \
        dut.get_io$$commit##N##$$bits$$rd(), dut.get_io$$commit##N##$$bits$$data(), \
        dut.get_io$$commit##N##$$bits$$pc(), dut.get_io$$commit##N##$$bits$$instruction()};
    SAMPLE(0)
    SAMPLE(1)
#undef SAMPLE
    out.recoveryAccepted = dut.get_io$$recoveryAccepted();
    out.recovering = dut.get_io$$recovering();
    out.occupancy = dut.get_io$$occupancy();
    out.inspected = dut.get_io$$committedValue();
    out.fault = dut.get_io$$headException$$valid();
    out.faultToken = {dut.get_io$$headException$$bits$$token$$index(), dut.get_io$$headException$$bits$$token$$tag()};
    out.faultPc = dut.get_io$$headException$$bits$$pc();
    out.faultCause = dut.get_io$$headException$$bits$$cause();
    out.faultTval = dut.get_io$$headException$$bits$$tval();
    out.redirect = dut.get_io$$redirect$$valid();
    out.redirectToken = {dut.get_io$$redirect$$bits$$token$$index(), dut.get_io$$redirect$$bits$$token$$tag()};
    out.redirectTarget = dut.get_io$$redirect$$bits$$target();
    out.rawComplete = dut.get_io$$rawLoadComplete();
    out.held = dut.get_io$$heldLoadComplete();
    out.replacement = dut.get_io$$slotReplacement();
    out.mixed = dut.get_io$$mixedForwarding();
    out.requestWrite = dut.get_io$$memory$$request$$bits$$write();
    out.requestData = dut.get_io$$memory$$request$$bits$$data();
    out.requestMask = dut.get_io$$memory$$request$$bits$$mask();
    out.request = dut.get_io$$memory$$request$$valid();
    out.responseReady = dut.get_io$$memory$$response$$ready();
    out.address = dut.get_io$$memory$$request$$bits$$address();
    out.size = dut.get_io$$memory$$request$$bits$$size();
    out.forwarded = dut.get_io$$forwarded0() | dut.get_io$$forwarded1();
    return out;
}

// Independent architectural oracle: software program order and integer arithmetic,
// with no copy of the hardware PRF mapping, wake/rank equations or slot allocator.
constexpr uint64_t base = UINT64_C(0x80010000);
constexpr uint64_t beat = UINT64_C(0x80f1e2d3c4b5a697);
static uint64_t memoryBeat(uint64_t address) { return beat ^ ((address & ~UINT64_C(7)) * UINT64_C(0x0102040810204081)); }
static uint64_t loadValue(uint64_t address, unsigned size, bool unsign) {
    unsigned bits = 8u << size;
    uint64_t value = memoryBeat(address) >> ((address & 7) * 8);
    if (bits == 64) return value;
    const uint64_t mask = (UINT64_C(1) << bits) - 1;
    value &= mask;
    if (!unsign && (value & (UINT64_C(1) << (bits - 1)))) value |= ~mask;
    return value;
}
struct Entry { Token token; Request r; uint64_t expected; };
struct Reply { uint64_t due; bool error, page; uint64_t data; };
class Bench {
    SLoadIssueForwardingGsim dut;
    std::array<uint64_t, 32> committed{};
    std::deque<Entry> live;
    std::deque<Reply> replies;
public:
    uint64_t cycles = 0, retired = 0, requests = 0, responses = 0, witnesses = 0;
    unsigned forwarded = 0, latency = 9;
    unsigned overlaps = 0, held = 0, replacements = 0, mixed = 0;
    unsigned redirects = 0, storeRequests = 0, storeCompletions = 0;
    uint64_t storedWord = 0;
    bool autoTrackMemory = false, trackReuse = false, robReused = false, prfReused = false; Token oldToken{}; unsigned oldDestination = 0;
    bool error = false, page = false, inject = false;
    Bench() { drive(dut, {}); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0); }
    void check(bool ok, const std::string &why) {
        if (!ok) throw std::runtime_error("load forwarding oracle cycle " + std::to_string(cycles) + ": " + why);
    }
    Output tick(Input in = {}) {
        in.response = !replies.empty() && replies.front().due <= cycles;
        in.data = in.response ? replies.front().data : 0;
        if (in.response) { in.error = replies.front().error; in.page = replies.front().page; }
        drive(dut, in); dut.step(); auto out = sample(dut); ++cycles;
        check(out.inspected == committed[in.inspect], "committed register state");
        if (in.response && out.responseReady) { replies.pop_front(); ++responses; }
        if (out.request) {
            check(out.address >= base && out.address < base + 4096, "memory address");
            if (out.requestWrite) {
                // This case writes one byte at base+16. Expected address/value
                // comes from the software test program, not a DUT-side owner map.
                check(out.address == base + 16 && out.size == 0 && out.requestMask == 1 &&
                    (out.requestData & 255) == 0x97, "independent store request/effect");
                storedWord = (memoryBeat(out.address) & ~UINT64_C(255)) | (out.requestData & 255);
                ++storeRequests;
            }
            replies.push_back({cycles + latency, error, page, memoryBeat(out.address)}); ++requests;
        }
        if (out.redirect) {
            auto at = std::find_if(live.begin(), live.end(), [&](const Entry &e) { return e.token == out.redirectToken; });
            check(at != live.end() && at->r.branch == 1, "redirect branch owner");
            check(out.redirectTarget == at->r.pc + at->r.immediate, "taken BEQ target");
            live.erase(at + 1, live.end());
            check(out.forwarded == 0, "cancelled producer captured on branch redirect edge");
            ++redirects;
        }
        if (out.recoveryAccepted) {
            auto at = std::find_if(live.begin(), live.end(), [&](const Entry &e) { return e.token == in.boundary; });
            check(at != live.end(), "recovery boundary owner");
            live.erase(at + !in.inclusive, live.end());
        }
        for (const auto &result : out.issued) if (result.valid) {
            auto owner = std::find_if(live.begin(), live.end(), [&](const Entry &e) { return e.token == result.token; });
            check(owner != live.end(), "completion without live owner (cancelled/stale)");
            if (owner->r.store) ++storeCompletions;
            if (!result.exception) check(result.data == owner->expected, "independent completion result mismatch");
        }
        if (!in.commit) check(!out.retired[0].valid && !out.retired[1].valid, "blocked retirement");
        for (const auto &r : out.retired) if (r.valid) {
            check(!live.empty(), "unexpected retirement");
            auto e = live.front(); live.pop_front();
            check(r.token == e.token && r.pc == e.r.pc && r.rd == e.r.rd, "retirement ownership/order");
            uint64_t expected = e.expected;
            if (inject && retired == 2) expected ^= 1;
            check(r.data == expected, "independent architectural result mismatch");
            check(r.writes == (e.r.writes && e.r.rd != 0), "x0 write suppression");
            if (r.writes) committed[r.rd] = expected;
            ++retired;
        }
        auto speculative = committed;
        for (const auto &e : live) if (e.r.writes && e.r.rd) speculative[e.r.rd] = e.expected;
        for (unsigned lane = 0; lane < 2; ++lane) if (out.allocated[lane]) {
            if (trackReuse && responses == 0) {
                robReused |= out.tokens[lane].index == oldToken.index && out.tokens[lane].tag != oldToken.tag;
                prfReused |= out.destinations[lane] == oldDestination;
            }
            auto r = in.requests[lane];
            uint64_t a = r.pcOperand ? r.pc : speculative[r.rs1];
            uint64_t b = r.immediateOperand ? r.immediate : speculative[r.rs2];
            uint64_t expected = (r.branch || r.store) ? 0 : r.memory ? loadValue(a + r.immediate, r.size, r.unsign) :
                r.op == 2 ? a ^ b : r.op == 1 ? a - b : a + b;
            if (autoTrackMemory && !trackReuse && r.memory) {
                trackReuse = true; oldToken = out.tokens[lane]; oldDestination = out.destinations[lane];
            }
            live.push_back({out.tokens[lane], r, expected});
            if (r.writes && r.rd) speculative[r.rd] = expected;
        }
        overlaps += out.rawComplete && (out.recoveryAccepted || out.redirect); held += out.held; replacements += out.replacement; mixed += out.mixed;
        forwarded |= out.forwarded; witnesses += bool(out.forwarded);
        return out;
    }
    void program(const std::vector<Request> &program, bool commit = true) {
        size_t at = 0;
        for (unsigned limit = 0; at < program.size() && limit < 500; ++limit) {
            Input in; in.commit = commit;
            in.requests[0] = program[at];
            if (at + 1 < program.size()) in.requests[1] = program[at + 1];
            auto out = tick(in); at += out.allocated[0] + out.allocated[1];
        }
        check(at == program.size(), "program admission timeout");
    }
    void idle(unsigned n, bool commit = true) { while (n--) { Input in; in.commit = commit; tick(in); } }
    void awaitRequest() {
        for (unsigned n = 0; requests == 0 && n < 80; ++n) tick();
        check(requests != 0, "load request handshake required before response/cancellation test");
    }
    void drain() {
        for (unsigned n = 0; (!live.empty() || !replies.empty()) && n < 1000; ++n) tick();
        check(live.empty() && replies.empty(), "drain timeout");
        for (unsigned r = 0; r < 32; ++r) { Input in; in.inspect = r; tick(in); }
    }
};
static Request alu(unsigned rd, unsigned a, unsigned b, uint64_t pc, bool immediate = false) {
    Request r; r.valid = true; r.rd = rd; r.rs1 = a; r.rs2 = immediate ? 0 : b; r.pc = pc;
    r.immediateOperand = immediate; r.immediate = b; return r;
}
static Request load(unsigned rd, unsigned size, bool unsign, unsigned offset, uint64_t pc) {
    Request r = alu(rd, 0, 0, pc, true); r.memory = true; r.size = size;
    r.unsign = unsign; r.immediate = base + offset; return r;
}
int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string(argv[1]) == "--inject-mismatch";
    uint64_t totalWitnesses = 0, totalRetired = 0; unsigned cases = 0, cancellations = 0, overlaps = 0, held = 0, replacements = 0, mixed = 0;
    std::cout << "Checking widths and blocked retirement" << std::endl;
    for (unsigned size = 0; size < 4; ++size) for (unsigned unsign = 0; unsign < (size == 3 ? 1u : 2u); ++unsign) {
        Bench b; b.inject = inject; unsigned offset = size == 3 ? 0 : 8 - (1u << size);
        b.program({load(1, size, unsign, offset, 4), alu(2, 1, 1, 8),
            alu(3, 1, 7, 12, true), alu(4, 0, 1, 16)}, false);
        b.awaitRequest(); b.idle(40, false); b.check(b.retired == 0, "retirement must remain blocked"); b.drain();
        b.check(b.forwarded == 3, "both source forwarded-enqueue witnesses required");
        overlaps += b.overlaps; held += b.held; replacements += b.replacements; mixed += b.mixed; totalWitnesses += b.witnesses; totalRetired += b.retired; ++cases;
    }
    // Sweep return timing against an independent ALU dependency chain. A
    // dedicated tap requires both producer promises on the SAME captured consumer.
    std::cout << "Checking mixed producer phase sweep" << std::endl;
    for (unsigned phase = 0; phase < 20; ++phase) {
        Bench b; b.latency = phase;
        b.program({load(1, 3, false, 0, 4)}, false); b.awaitRequest();
        std::vector<Request> p;
        for (unsigned n = 0; n < 5; ++n) {
            p.push_back(alu(7, 7, 1, 8 + n * 8, true));
            p.push_back(alu(5, 5, 1, 12 + n * 8, true));
        }
        p.push_back(alu(6, 1, 7, 64));
        b.program(p, false); b.idle(60, false); b.drain();
        overlaps += b.overlaps; held += b.held; replacements += b.replacements; mixed += b.mixed;
        totalWitnesses += b.witnesses; totalRetired += b.retired; ++cases;
    }
    // Architectural x0 must never manufacture a physical producer/wakeup.
    { Bench b; b.program({load(0, 3, false, 0, 4), alu(2, 0, 9, 8, true)}); b.drain();
      b.check(b.witnesses == 0, "x0 load forwarded"); totalRetired += b.retired; ++cases; }
    // A successful ordinary store has no destination promise. Observe both
    // its bus side effect and accepted completion, then require zero wakeups.
    { Bench b; auto store = load(0, 0, false, 16, 8);
      store.store = true; store.writes = false; store.rs2 = 5;
      b.program({alu(5, 0, 0x97, 4, true), store, alu(6, 5, 1, 12, true)}); b.drain();
      b.check(b.storeRequests == 1 && b.storeCompletions == 1 && (b.storedWord & 255) == 0x97,
          "successful store bus effect and completion required");
      b.check(b.witnesses == 0, "store manufactured load forwarding"); totalRetired += b.retired; ++cases; }
    // WAW with consumers on opposite sides plus many rounds to recycle ROB and PRF owners.
    { Bench b; std::vector<Request> p;
      for (unsigned n = 0; n < 80; ++n) {
          auto pc = 4 + n * 20;
          p.push_back(load(1, n % 4, n & 1, 0, pc)); p.push_back(alu(2, 1, 1, pc + 4));
          p.push_back(alu(1, 0, n + 1, pc + 8, true)); p.push_back(alu(3, 1, 2, pc + 12));
      }
      b.program(p); b.drain(); overlaps += b.overlaps; held += b.held; replacements += b.replacements; mixed += b.mixed; totalWitnesses += b.witnesses; totalRetired += b.retired; ++cases; }
    // Response access/page faults and local misalignment must not wake dependents.
    std::cout << "Checking faults" << std::endl;
    for (unsigned kind = 0; kind < 3; ++kind) {
        Bench b; b.error = kind == 0; b.page = kind == 1;
        b.program({load(1, 3, false, kind == 2 ? 1 : 0, 4), alu(2, 1, 1, 8)}, false);
        bool seen = false;
        for (unsigned n = 0; n < 80; ++n) { Input in; auto out = b.tick(in);
            if (out.fault) { b.check(out.faultCause == (kind == 0 ? 5u : kind == 1 ? 13u : 4u), "fault cause");
                b.check(out.faultTval == base + (kind == 2), "fault address"); seen = true; }
        }
        b.check(seen && b.witnesses == 0 && b.retired == 0, "fault/no-wakeup witness kind=" + std::to_string(kind) + " seen=" + std::to_string(seen) + " forwards=" + std::to_string(b.witnesses) + " retired=" + std::to_string(b.retired)); ++cases;
    }
    // An older taken BEQ waits on an ALU chain while its younger load
    // starts speculatively. Vary return latency around the actual redirect.
    // The response FIFO is intentionally NOT flushed by recovery.
    std::cout << "Before recovery: forwarded_cycles=" << totalWitnesses << " mixed=" << mixed
              << " held=" << held << " replacements=" << replacements << std::endl;
    std::cout << "Checking branch cancellation, delayed response and owner reuse" << std::endl;
    for (unsigned phase = 0; phase < 24; ++phase) {
        Bench b; b.latency = phase == 0 ? 150 : phase - 1; b.autoTrackMemory = phase == 0;
        std::vector<Request> p;
        for (unsigned n = 0; n < 10; ++n) p.push_back(alu(5, 5, 1, 4 + n * 4, true));
        auto branch = alu(0, 5, 5, 44); branch.branch = 1; branch.writes = false; branch.immediate = 32;
        p.push_back(branch); p.push_back(load(1, 3, false, 0, 48)); p.push_back(alu(2, 1, 1, 52));
        b.program(p);
        for (unsigned n = 0; b.redirects == 0 && n < 80; ++n) b.tick();
        b.check(b.redirects == 1 && b.requests > 0, "actual branch redirect after speculative request required");
        ++cancellations; b.idle(12);
        std::vector<Request> reuse;
        for (unsigned n = 0; n < 48; ++n) reuse.push_back(alu(1 + n % 12, 0, n + 7, 128 + n * 4, true));
        b.program(reuse); b.program({load(1, 3, false, 8, 512), alu(2, 1, 1, 516)}); b.drain();
        if (phase == 0) b.check(b.robReused && b.prfReused, "ROB and PRF owner reuse before delayed cancelled response");
        overlaps += b.overlaps; held += b.held; replacements += b.replacements; mixed += b.mixed;
        totalWitnesses += b.witnesses; totalRetired += b.retired; ++cases;
    }
    if (!mixed || !held || !replacements) throw std::runtime_error("missing forwarding stress witness: mixed=" +
        std::to_string(mixed) + " held=" + std::to_string(held) + " replacement=" + std::to_string(replacements));
    if (!overlaps) throw std::runtime_error("recovery and raw completion coincidence not exercised");
    std::cout << "GSIM load issue forwarding: PASS cases=" << cases << " forwarded_cycles=" << totalWitnesses
              << " retired=" << totalRetired << " recovery_phases=" << cancellations << " recovery_completion=" << overlaps
              << " held_load_completion=" << held << " same_slot_replacement=" << replacements << " mixed_forwarding=" << mixed << '\n';
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
