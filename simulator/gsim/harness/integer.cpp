#include "IntegerBackendGsim.h"

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
    uint64_t immediate = 0, pc = 0;
    uint32_t instruction = 0;
};
struct Input {
    std::array<Request, 2> requests{};
    bool commit = true, recover = false, inclusive = false;
    Token boundary{};
    unsigned inspect = 0;
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
    std::array<Result, 2> issued{};
    std::array<Retired, 2> retired{};
    bool recoveryAccepted = false, recovering = false, fault = false;
    Token faultToken{};
    uint64_t faultPc = 0, faultCause = 0, faultTval = 0, inspected = 0;
    unsigned occupancy = 0;
};
static void drive(SIntegerBackendGsim &dut, const Input &in) {
    dut.set_io$$memory$$request$$ready(0);
    dut.set_io$$memory$$response$$valid(0);
    dut.set_io$$memory$$response$$bits$$data(0);
    dut.set_io$$memory$$response$$bits$$error(0);
#define DRIVE(N) \
    dut.set_io$$allocate##N##$$bits$$mulDiv(0); \
    dut.set_io$$allocate##N##$$bits$$mulDivOp(0); \
    dut.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
    dut.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
    dut.set_io$$allocate##N##$$bits$$memory(0); \
    dut.set_io$$allocate##N##$$bits$$fetchFault(0); \
    dut.set_io$$allocate##N##$$bits$$fetchPageFault(0); \
    dut.set_io$$allocate##N##$$bits$$fetchTval(0); \
    dut.set_io$$allocate##N##$$bits$$expandedInstruction(0); \
    dut.set_io$$allocate##N##$$bits$$atomic(0); \
    dut.set_io$$allocate##N##$$bits$$atomicOp(0); \
    dut.set_io$$allocate##N##$$bits$$store(0); \
    dut.set_io$$allocate##N##$$bits$$memorySize(0); \
    dut.set_io$$allocate##N##$$bits$$memoryUnsigned(0); \
    dut.set_io$$allocate##N##$$bits$$controlFlow(0); \
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
static Output sample(SIntegerBackendGsim &dut) {
    if (dut.get_io$$issueCount() > 2) throw std::runtime_error("global issue width exceeded");
    Output out;
#define SAMPLE(N) \
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
    return out;
}

// Functional reference: unsigned arithmetic only, including explicit sign fill (no C++ signed-overflow UB).
static bool legal(const Request &r) {
    return r.op < 12 && (!r.word || r.op < 2 || (r.op >= 5 && r.op <= 7));
}
static uint64_t evaluate(const Request &r, uint64_t a, uint64_t b) {
    const unsigned width = r.word ? 32 : 64;
    const unsigned shift = b % width;
    const uint64_t mask = r.word ? UINT64_C(0xffffffff) : UINT64_MAX;
    uint64_t result = 0;
    switch (r.op) {
    case 0: result = a + b; break;
    case 1: result = a - b; break;
    case 2: result = a ^ b; break;
    case 3: result = a | b; break;
    case 4: result = a & b; break;
    case 5: result = a << shift; break;
    case 6: result = (a & mask) >> shift; break;
    case 7:
        result = (a & mask) >> shift;
        if (shift && ((a >> (width - 1)) & 1)) result |= mask ^ (mask >> shift);
        break;
    case 8: result = (a ^ (UINT64_C(1) << 63)) < (b ^ (UINT64_C(1) << 63)); break;
    case 9: result = a < b; break;
    case 10: result = b == 0 ? 0 : a; break;
    case 11: result = b != 0 ? 0 : a; break;
    default: break;
    }
    if (r.word) {
        result &= UINT64_C(0xffffffff);
        if (result & UINT64_C(0x80000000)) result |= UINT64_C(0xffffffff00000000);
    }
    return result;
}
struct Transaction {
    Token token{};
    Request request{};
    uint64_t expected = 0;
    std::vector<uint64_t> dependencies;
    bool done = false;
};
struct Stats {
    uint64_t cycles = 0, allocations = 0, commits = 0, issues = 0, dualIssues = 0, redirects = 0;
    uint64_t outOfOrder = 0, exceptions = 0;
    unsigned independentTwoWideCycles = 0, dependentOneWideCycles = 0;
};
class Bench {
    SIntegerBackendGsim dut;
    std::array<uint64_t, 32> committed{};
    std::set<uint64_t> completed;
    bool recovering = false;
    size_t keep = 0;
    uint64_t nextTag = 0;
    unsigned tail = 0;
public:
    std::deque<Transaction> live;
    Stats stats;
    Bench() {
        drive(dut, Input{});
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
    }
    void check(bool condition, const std::string &message) {
        if (!condition) throw std::runtime_error("cycle " + std::to_string(stats.cycles) + ": " + message);
    }
    Output tick(Input in = {}) {
        drive(dut, in);
        dut.step();
        const Output out = sample(dut);
        ++stats.cycles;
        check(out.occupancy == live.size(), "ROB occupancy");
        check(out.recovering == recovering, "rollback state");
        check(out.inspected == committed[in.inspect], "committed PRF value x" + std::to_string(in.inspect));
        size_t requested = 0;
        bool accept = false;
        for (size_t i = 0; i < live.size(); ++i) {
            if (in.recover && live[i].token == in.boundary) {
                requested = i + !in.inclusive;
                accept = !recovering || requested < keep;
            }
        }
        check(out.recoveryAccepted == accept, "redirect authorization");
        if (accept) { keep = requested; ++stats.redirects; }
        const bool rollback = recovering || accept;
        const size_t survivors = rollback ? keep : live.size();
        const bool fault = !rollback && !live.empty() && live.front().done && !legal(live.front().request);
        check(out.fault == fault, "precise head exception valid");
        if (fault) {
            const auto &t = live.front();
            check(out.faultToken == t.token && out.faultPc == t.request.pc && out.faultCause == 2 &&
                  out.faultTval == t.request.instruction, "precise head exception payload");
            ++stats.exceptions;
        }
        // Dependencies are captured as architectural producer identities. No physical maps or RTL selection network.
        std::vector<size_t> candidates;
        for (size_t i = 0; i < survivors; ++i) {
            const auto &t = live[i];
            if (!t.done && std::all_of(t.dependencies.begin(), t.dependencies.end(),
                                      [&](uint64_t tag) { return completed.count(tag); })) candidates.push_back(i);
        }
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool valid = lane < candidates.size();
            check(out.issued[lane].valid == valid, "oldest-ready issue throughput");
            if (valid) {
                auto &t = live[candidates[lane]];
                const auto &result = out.issued[lane];
                check(result.token == t.token, "oldest-ready issue order");
                check(result.exception == !legal(t.request), "ALU operation legality, op=" +
                    std::to_string(t.request.op) + " word=" + std::to_string(t.request.word) +
                    " actual_exception=" + std::to_string(result.exception));
                if (legal(t.request)) check(result.data == t.expected, "ALU result, op=" + std::to_string(t.request.op));
                else check(result.cause == 2 && result.tval == t.request.instruction, "illegal operation metadata");
                for (size_t i = 0; i < candidates[lane]; ++i) {
                    if (!live[i].done && std::find(candidates.begin(), candidates.begin() + lane, i) == candidates.begin() + lane) {
                        ++stats.outOfOrder;
                        break;
                    }
                }
                ++stats.issues;
            }
        }
        if (out.issued[1].valid) ++stats.dualIssues;
        size_t retire = 0;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const bool completesNow = lane < live.size() &&
                std::find(candidates.begin(), candidates.begin() + std::min<size_t>(2, candidates.size()), lane) !=
                    candidates.begin() + std::min<size_t>(2, candidates.size());
            const bool valid = in.commit && !rollback && retire == lane && lane < live.size() &&
                               (live[lane].done || completesNow) && legal(live[lane].request);
            check(out.retired[lane].valid == valid, "ordered retirement");
            if (valid) {
                const auto &t = live[lane];
                const auto &r = out.retired[lane];
                check(r.token == t.token && r.pc == t.request.pc && r.instruction == t.request.instruction &&
                      r.rd == t.request.rd && r.writes == (t.request.writes && t.request.rd != 0) &&
                      r.data == t.expected, "architectural retirement payload");
                ++retire;
            }
        }
        // Rebuild speculative architectural values, independently of the DUT's PRF and rename policy.
        auto speculative = committed;
        std::array<std::vector<uint64_t>, 32> producers{};
        unsigned available = PHYSICAL_REGS - 32;
        for (const auto &t : live) {
            if (t.request.writes && t.request.rd) {
                --available;
                speculative[t.request.rd] = t.expected;
                producers[t.request.rd] = {t.token.tag};
            }
        }
        const size_t oldCount = live.size();
        std::vector<Transaction> added;
        bool prefix = !rollback;
        for (unsigned lane = 0; lane < 2; ++lane) {
            const auto &r = in.requests[lane];
            const bool writes = r.writes && r.rd;
            const bool valid = prefix && r.valid && oldCount + lane < ROB_ENTRIES && (!writes || available);
            check(out.allocated[lane] == valid, "allocation capacity/prefix");
            prefix = valid;
            if (!valid) continue;
            check(out.tokens[lane] == Token{tail, nextTag}, "allocation identity");
            nextTag++;
            tail = (tail + 1) % ROB_ENTRIES;
            Transaction t;
            t.token = out.tokens[lane];
            t.request = r;
            t.expected = evaluate(r, r.pcOperand ? r.pc : speculative[r.rs1],
                                 r.immediateOperand ? r.immediate : speculative[r.rs2]);
            if (!r.pcOperand) t.dependencies = producers[r.rs1];
            if (!r.immediateOperand) t.dependencies.insert(t.dependencies.end(), producers[r.rs2].begin(), producers[r.rs2].end());
            if (writes) {
                --available;
                speculative[r.rd] = t.expected;
                producers[r.rd] = {t.token.tag};
            }
            added.push_back(t);
            ++stats.allocations;
        }
        // Apply cycle events only after checking all outputs, to prohibit same-cycle dependency wakeup.
        for (unsigned lane = 0; lane < 2 && lane < candidates.size(); ++lane) {
            auto &t = live[candidates[lane]];
            t.done = true;
            if (legal(t.request)) completed.insert(t.token.tag);
        }
        if (rollback) {
            recovering = live.size() > keep + 1;
            if (live.size() > keep) {
                tail = live.back().token.index;
                live.pop_back();
            }
        } else {
            for (size_t i = 0; i < retire; ++i) {
                const auto &t = live.front();
                if (t.request.writes && t.request.rd) committed[t.request.rd] = t.expected;
                live.pop_front();
                ++stats.commits;
            }
            for (const auto &t : added) live.push_back(t);
        }
        return out;
    }
    void drain() {
        for (unsigned i = 0; !live.empty() && i < 1000; ++i) {
            Input in;
            in.inspect = i % 32;
            if (live.front().done && !legal(live.front().request)) {
                in.recover = in.inclusive = true;
                in.boundary = live.front().token;
            }
            tick(in);
        }
        check(live.empty(), "drain timeout");
        for (unsigned r = 0; r < 32; ++r) { Input in; in.inspect = r; tick(in); }
    }
    void submit(Request r) {
        Input in;
        in.requests[0] = r;
        for (unsigned i = 0; i < 1000; ++i) if (tick(in).allocated[0]) return;
        check(false, "submit timeout");
    }
};
static Request immediate(unsigned rd, uint64_t value) {
    Request r;
    r.valid = true;
    r.rd = rd;
    r.immediate = value;
    return r;
}
static void arithmetic(Bench &b) {
    const std::array<uint64_t, 9> values{0, 1, UINT64_MAX, UINT64_C(0x8000000000000000),
        UINT64_C(0x7fffffffffffffff), UINT64_C(0x80000000), UINT64_C(0xffffffff),
        UINT64_C(0x123456789abcdef0), UINT64_C(0xffffffff00000000)};
    for (auto a : values) {
        b.submit(immediate(1, a));
        for (unsigned op = 0; op < 12; ++op) {
            for (bool word : {false, true}) {
                Request r = immediate(2, 0);
                r.rs1 = 1; r.op = op; r.word = word;
                if (!legal(r)) continue;
                for (auto value : values) { r.immediate = value; b.submit(r); }
                for (unsigned shift : {0, 1, 31, 32, 63, 64, 65, 127}) {
                    r.immediate = shift; b.submit(r);
                }
            }
        }
    }
    b.drain();
}
static void directed(Bench &b) {
    // Same-packet RAW/WAW, x0 suppression, register operands and PC-relative inputs.
    Input in;
    in.requests[0] = immediate(1, 41);
    in.requests[1] = immediate(1, 1); in.requests[1].rs1 = 1;
    b.tick(in); b.drain();
    in.requests[0] = immediate(0, UINT64_MAX);
    in.requests[1] = immediate(2, 99); in.requests[1].immediateOperand = false;
    in.requests[1].rs1 = in.requests[1].rs2 = 1;
    b.tick(in); b.drain();
    auto pc = immediate(3, UINT64_MAX); pc.pcOperand = true; pc.pc = UINT64_C(0x80000000);
    b.submit(pc); b.drain();
    // Force a younger independent instruction to bypass an older dependency chain.
    in = {}; in.commit = false;
    in.requests[0] = immediate(4, 1); in.requests[0].rs1 = 1;
    in.requests[1] = immediate(5, 1); in.requests[1].rs1 = 4;
    b.tick(in);
    in.requests[0] = immediate(6, 1); in.requests[0].rs1 = 5;
    in.requests[1] = immediate(7, 123);
    b.tick(in);
    in.requests = {}; b.tick(in);
    b.check(b.stats.outOfOrder > 0, "directed out-of-order coverage");
    // Kill both executed and waiting younger writes; interrupt rollback with an older inclusive redirect.
    in.recover = true; in.boundary = b.live[1].token;
    b.tick(in);
    in.boundary = b.live.front().token; in.inclusive = true;
    b.tick(in); b.drain();
    // Stale redirect must not affect subsequent reuse of the same ROB slots/physical registers.
    b.tick(in); b.submit(immediate(4, 987)); b.drain();
    // Illegal operation blocks dependents and retires precisely through an explicit exception recovery.
    auto illegal = immediate(1, 0); illegal.op = 15; illegal.pc = 0x1234; illegal.instruction = 0xdeadbeef;
    b.submit(illegal);
    auto dependent = immediate(2, 1); dependent.rs1 = 1; b.submit(dependent);
    b.tick(); b.tick(); b.drain();
    illegal.op = 2; illegal.word = true; b.submit(illegal); b.tick(); b.tick(); b.drain();
    // W is illegal for unsigned-word address operations and byte/halfword extension controls.
    for (unsigned op : {16U, 19U, 23U, 34U, 36U, 44U, 45U, 63U}) {
        illegal.op = op; illegal.word = true;
        b.submit(illegal); b.tick(); b.tick(); b.drain();
    }
    for (unsigned op : {12U, 14U, 45U, 63U}) {
        illegal.op = op; illegal.word = false;
        b.submit(illegal); b.tick(); b.tick(); b.drain();
    }
    // Invalid lane zero prevents accepting lane one.
    in = {}; in.requests[1] = immediate(1, 7); b.tick(in);
    // Fill the ROB without consuming PRF capacity; a full ROB must block allocation despite completed ALUs.
    in = {}; in.commit = false;
    for (auto &r : in.requests) { r = immediate(0, 17); r.writes = false; }
    for (unsigned i = 0; i < ROB_ENTRIES / 2; ++i) b.tick(in);
    b.check(b.live.size() == ROB_ENTRIES, "full ROB coverage");
    b.check(!b.tick(in).allocated[0], "full ROB backpressure");
    b.drain();
}
static void throughput(Bench &b) {
    b.drain();
    for (unsigned i = 0; i < 100; ++i) {
        Input in;
        in.requests[0] = immediate(1, i);
        in.requests[1] = immediate(2, i + 100);
        const auto out = b.tick(in);
        if (PHYSICAL_REGS >= 40 && i >= 4) {
            b.check(out.allocated[1] && out.issued[1].valid && out.retired[1].valid,
                    "independent stream must sustain two allocations/issues/commits per cycle");
            ++b.stats.independentTwoWideCycles;
        }
    }
    b.drain();
    for (unsigned i = 0; i < 100; ++i) {
        Input in;
        in.requests[0] = immediate(1, 1); in.requests[0].rs1 = 1;
        const auto out = b.tick(in);
        if (i >= 4) {
            b.check(out.allocated[0] && out.issued[0].valid && out.retired[0].valid,
                    "dependent chain must sustain one ALU per cycle");
            ++b.stats.dependentOneWideCycles;
        }
    }
    b.drain();
}
static void randomized(Bench &b, uint64_t seed) {
    std::mt19937_64 random(seed);
    for (unsigned cycle = 0; cycle < 6000; ++cycle) {
        Input in;
        in.commit = random() % 4 != 0;
        in.inspect = random() % 32;
        for (auto &r : in.requests) {
            r.valid = random() % 8 != 0;
            r.writes = random() % 10 != 0;
            r.rd = random() % 32; r.rs1 = random() % 32; r.rs2 = random() % 32;
            r.op = random() % 12;
            r.word = random() % 2 && (r.op < 2 || (r.op >= 5 && r.op <= 7));
            r.pcOperand = random() % 12 == 0;
            r.immediateOperand = random() % 2;
            r.immediate = random(); r.pc = random() & ~UINT64_C(3); r.instruction = random();
        }
        if (!b.live.empty() && random() % 17 == 0) {
            in.recover = true; in.inclusive = random() % 2;
            in.boundary = b.live[random() % b.live.size()].token;
        } else if (random() % 25 == 0) {
            in.recover = true; in.boundary = {unsigned(random() % ROB_ENTRIES), UINT64_MAX};
        }
        b.tick(in);
    }
    b.drain();
}
static void redirectArbitration() {
    for (unsigned scenario = 0; scenario < 5; ++scenario) {
        SIntegerBackendGsim dut;
        drive(dut, Input{});
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        const unsigned branchLane = scenario == 1 ? 1 : 0;
        Input in;
        in.requests[branchLane] = immediate(1, 16);
        in.requests[branchLane].pcOperand = true;
        in.requests[branchLane].pc = 0x1000;
        in.requests[1 - branchLane] = immediate(2, 42);
        drive(dut, in);
        if (branchLane == 0) dut.set_io$$allocate0$$bits$$controlFlow(7);
        else dut.set_io$$allocate1$$bits$$controlFlow(7);
        dut.step();
        auto out = sample(dut);
        auto require = [&](bool ok, const char *message) {
            if (!ok) throw std::runtime_error("redirect arbitration case " + std::to_string(scenario) + ": " + message);
        };
        require(out.allocated[0] && out.allocated[1], "setup allocation");
        in = {}; in.recover = true;
        if (scenario == 0) in.boundary = {0, UINT64_MAX}; // invalid external request must not mask branch
        else in.boundary = out.tokens[scenario == 2 ? 1 : 0];
        in.inclusive = scenario == 2 || scenario == 4;
        drive(dut, in); dut.step(); out = sample(dut);
        const bool branchWins = scenario == 0 || scenario == 2;
        require(bool(dut.get_io$$redirect$$valid()) == branchWins, "oldest valid recovery must win");
        require(out.recoveryAccepted == !branchWins, "external acceptance");
        if (branchWins) {
            require(dut.get_io$$redirect$$bits$$target() == 0x1010 && out.issued[0].valid &&
                    out.issued[0].data == 0x1004 && !out.issued[1].valid, "link result and younger write suppression");
        }
        bool sawRetry = false;
        for (unsigned cycle = 0; cycle < 20; ++cycle) {
            in = {}; in.inspect = 1;
            drive(dut, in); dut.step(); out = sample(dut);
            if (dut.get_io$$redirect$$valid()) {
                require(scenario == 3 && dut.get_io$$redirect$$bits$$target() == 0x1010, "preserved boundary retry");
                sawRetry = true;
            }
        }
        require(out.occupancy == 0, "drain after arbitration");
        require(out.inspected == ((branchWins || scenario == 3) ? 0x1004 : 0), "committed link value");
        require(sawRetry == (scenario == 3), "retry coverage");
    }
}
static void memoryRetirementProtection(bool store) {
    SIntegerBackendGsim dut;
    drive(dut, Input{});
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    Input in;
    in.requests[0] = immediate(0, 0);
    in.requests[0].writes = false;
    drive(dut, in);
    dut.set_io$$allocate0$$bits$$memory(1);
    dut.set_io$$allocate0$$bits$$store(store);
    dut.set_io$$allocate0$$bits$$memorySize(3);
    dut.step();
    const auto allocated = sample(dut);
    if (!allocated.allocated[0]) throw std::runtime_error("memory protection setup");
    unsigned requests = 0, completions = 0, retirements = 0;
    for (unsigned cycle = 0; cycle < 16; ++cycle) {
        in = {};
        in.commit = cycle == 0 || cycle >= 10;
        in.recover = cycle >= 1;
        in.inclusive = true;
        in.boundary = allocated.tokens[0];
        drive(dut, in);
        // Hold the port for three cycles, then respond on the request handshake itself.
        if (cycle == 4) {
            dut.set_io$$memory$$request$$ready(1);
            dut.set_io$$memory$$response$$valid(1);
        }
        dut.step();
        const auto out = sample(dut);
        if (out.recoveryAccepted) throw std::runtime_error("external recovery cancelled authorized store");
        if (cycle == 4) {
            if (!dut.get_io$$memory$$request$$valid() || !dut.get_io$$memory$$response$$ready())
                throw std::runtime_error("same-cycle response handshake");
            ++requests;
        }
        completions += out.issued[0].valid;
        retirements += out.retired[0].valid;
        if (cycle < 10 && out.retired[0].valid) throw std::runtime_error("store ignored commit backpressure");
        if (cycle == 15 && out.occupancy != 0) throw std::runtime_error("protected store did not retire");
    }
    if (requests != 1 || completions != 1 || retirements != 1)
        throw std::runtime_error("store must request, complete, and retire exactly once");
}

// Cancel in request/backpressure, response wait, response handshake, and completed-result states.
// Reuse the same ROB slot and architectural destination while an old errored response is still in flight.
static void speculativeMemoryCancellation() {
    for (unsigned cancelCycle : {1U, 6U, 10U, 11U}) {
        SIntegerBackendGsim dut;
        drive(dut, Input{});
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        Input in;
        in.requests[0] = immediate(3, UINT64_C(0x80010000));
        drive(dut, in);
        dut.set_io$$allocate0$$bits$$memory(1);
        dut.set_io$$allocate0$$bits$$memorySize(3);
        dut.step();
        const auto old = sample(dut);
        if (!old.allocated[0]) throw std::runtime_error("cancelled load allocation");
        unsigned discarded = 0, retired = 0, requested = 0;
        bool reused = false;
        for (unsigned cycle = 0; cycle < 32; ++cycle) {
            in = {};
            in.inspect = 3;
            in.commit = cycle == 0 || cycle > cancelCycle;
            in.recover = cycle == cancelCycle;
            in.inclusive = true;
            in.boundary = old.tokens[0];
            if (cycle == cancelCycle + 3) in.requests[0] = immediate(3, 42);
            drive(dut, in);
            dut.set_io$$memory$$request$$ready(cycle == 5);
            dut.set_io$$memory$$response$$valid(cycle == 10);
            dut.set_io$$memory$$response$$bits$$data(UINT64_C(0xdeadbeef));
            dut.set_io$$memory$$response$$bits$$error(1);
            dut.step();
            const auto out = sample(dut);
            if (cycle == cancelCycle && !out.recoveryAccepted) throw std::runtime_error("RAM cancellation rejected");
            if (cycle >= 1 && cycle <= 5) {
                if (!dut.get_io$$memory$$request$$valid() ||
                    dut.get_io$$memory$$request$$bits$$address() != UINT64_C(0x80010000))
                    throw std::runtime_error("cancelled request not held stable");
            }
            if (cycle == 5) ++requested;
            if (cycle == 10 && !dut.get_io$$memory$$response$$ready()) throw std::runtime_error("cancelled response not drained");
            if (out.fault) throw std::runtime_error("cancelled load reported exception");
            for (const auto &issued : out.issued)
                if (issued.valid && issued.token == old.tokens[0]) throw std::runtime_error("cancelled load wrote back");
            if (out.allocated[0]) {
                if (out.tokens[0].index != old.tokens[0].index || out.tokens[0].tag == old.tokens[0].tag)
                    throw std::runtime_error("cancelled ROB slot reuse coverage");
                reused = true;
            }
            discarded += dut.get_io$$memoryDiscarded();
            for (const auto &c : out.retired) if (c.valid) {
                if (c.data != 42 || c.rd != 3) throw std::runtime_error("stale load damaged replacement");
                ++retired;
            }
            if (cycle == 31 && (out.inspected != 42 || out.occupancy || dut.get_io$$memoryBusy()))
                throw std::runtime_error("cancellation failed to drain");
        }
        if (!reused || retired != 1 || discarded != 1 || requested != 1)
            throw std::runtime_error("load cancellation coverage");
    }
}

// Two independent loads: completing the first may start the second, but recovery must cancel both.
static void memoryTurnaround() {
    for (unsigned scenario : {0U, 1U, 2U, 3U}) {
        const bool cancel = scenario == 1, protectedRead = scenario >= 2, youngerError = scenario == 3;
        SIntegerBackendGsim dut;
        drive(dut, Input{});
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        Input in;
        in.requests[0] = immediate(1, protectedRead ? 0 : UINT64_C(0x80010000));
        in.requests[1] = immediate(2, UINT64_C(0x80010008));
        drive(dut, in);
        dut.set_io$$allocate0$$bits$$memory(1);
        dut.set_io$$allocate0$$bits$$memorySize(3);
        dut.set_io$$allocate1$$bits$$memory(1);
        dut.set_io$$allocate1$$bits$$memorySize(3);
        dut.step();
        const auto allocated = sample(dut);
        if (!allocated.allocated[0] || !allocated.allocated[1]) throw std::runtime_error("turnaround allocation");
        std::deque<std::pair<unsigned, unsigned>> responses;
        unsigned requests = 0, completions = 0, retired = 0, discarded = 0;
        for (unsigned cycle = 0; cycle < 18; ++cycle) {
            in = {};
            in.recover = (cancel && cycle == 2) || (protectedRead && cycle >= 4 && cycle < 10);
            in.commit = !(protectedRead && cycle >= 4 && cycle < 10);
            in.inclusive = true;
            in.boundary = allocated.tokens[0];
            drive(dut, in);
            dut.set_io$$memory$$request$$ready(1);
            const bool responding = !responses.empty() && cycle == responses.front().first;
            dut.set_io$$memory$$response$$valid(responding);
            dut.set_io$$memory$$response$$bits$$data(responding && responses.front().second == 0 ? 17 : 29);
            dut.set_io$$memory$$response$$bits$$error(youngerError && responding && responses.front().second == 1);
            dut.step();
            const auto out = sample(dut);
            if (responding) {
                if (!dut.get_io$$memory$$response$$ready()) throw std::runtime_error("turnaround response refused");
                responses.pop_front();
            }
            if (dut.get_io$$memory$$request$$valid()) {
                // An authorized start presents its request immediately; separate RAM
                // loads may then use consecutive request cycles, while an irrevocable
                // non-RAM load still waits for completion/retirement before the next.
                if (cycle != requests * (protectedRead ? 2 : 1) ||
                    dut.get_io$$memory$$request$$bits$$address() !=
                        (protectedRead && requests == 0 ? 0 : UINT64_C(0x80010000) + requests * 8))
                    throw std::runtime_error("load turnaround timing/address scenario=" +
                        std::to_string(scenario) + " cycle=" + std::to_string(cycle) +
                        " request=" + std::to_string(requests));
                responses.emplace_back(cycle + 1, requests++);
            }
            if (protectedRead && out.recoveryAccepted) throw std::runtime_error("overlap released irrevocable owner");
            if (cancel && cycle == 2 && !out.recoveryAccepted) throw std::runtime_error("turnaround cancellation");
            discarded += dut.get_io$$memoryDiscarded();
            for (const auto &r : out.issued) if (r.valid) {
                if (cancel || r.exception != (youngerError && completions == 1) || r.data != (completions == 0 ? 17 : 29))
                    throw std::runtime_error("turnaround result ownership");
                ++completions;
            }
            for (const auto &r : out.retired) if (r.valid) {
                if (cancel || r.rd != retired + 1 || r.data != (retired == 0 ? 17 : 29))
                    throw std::runtime_error("turnaround retirement");
                ++retired;
            }
            if (cycle == 17 && (out.occupancy != unsigned(youngerError) || dut.get_io$$memoryBusy() ||
                out.fault != youngerError)) throw std::runtime_error("turnaround drain");
            if (out.fault && (!youngerError || out.faultCause != 5 || out.faultTval != UINT64_C(0x80010008)))
                throw std::runtime_error("turnaround fault ownership");
        }
        if (requests != 2U || completions != (cancel ? 0U : 2U) ||
            retired != completions - unsigned(youngerError) || discarded != 2 * unsigned(cancel)) throw std::runtime_error("turnaround coverage");
    }
}

// A completed RAM store forwards its own data, never the arbitrary write-response data.
// An errored store stops precisely; a later recovery can discard the forwarded load.
static void storeForwarding() {
    for (unsigned scenario : {0U, 1U, 2U}) {
        const bool error = scenario == 1, cancel = scenario == 2;
        SIntegerBackendGsim dut;
        drive(dut, Input{});
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        Input in;
        in.requests[0] = immediate(0, UINT64_C(0x80010000));
        in.requests[0].writes = false;
        in.requests[1] = immediate(2, UINT64_C(0x80010000));
        drive(dut, in);
        dut.set_io$$allocate0$$bits$$memory(1);
        dut.set_io$$allocate0$$bits$$store(1);
        dut.set_io$$allocate0$$bits$$memorySize(3);
        dut.set_io$$allocate1$$bits$$memory(1);
        dut.set_io$$allocate1$$bits$$memorySize(3);
        dut.step();
        const auto allocated = sample(dut);
        if (!allocated.allocated[1]) throw std::runtime_error("forwarding allocation");
        unsigned requests = 0, forwarded = 0, retired = 0;
        for (unsigned cycle = 0; cycle < 18; ++cycle) {
            in = {};
            in.recover = cancel && cycle == 4;
            in.inclusive = true;
            in.boundary = allocated.tokens[1];
            drive(dut, in);
            dut.set_io$$memory$$request$$ready(1);
            dut.set_io$$memory$$response$$valid(cycle == 2);
            dut.set_io$$memory$$response$$bits$$data(UINT64_C(0xdeadbeef));
            dut.set_io$$memory$$response$$bits$$error(error);
            dut.step();
            const auto out = sample(dut);
            if (dut.get_io$$memory$$request$$valid()) {
                if (!dut.get_io$$memory$$request$$bits$$write()) throw std::runtime_error("forwarded load read the bus");
                ++requests;
            }
            if (dut.get_io$$memoryForwarded()) {
                if (cycle != 3 || error) throw std::runtime_error("bad forwarding authorization");
                ++forwarded;
            }
            if (cancel && cycle == 4 && !out.recoveryAccepted) throw std::runtime_error("forwarded load recovery");
            for (const auto &r : out.issued)
                if (r.valid && r.token == allocated.tokens[1] && (r.data != 0 || r.exception))
                    throw std::runtime_error("forwarded value did not come from store data");
            for (const auto &r : out.retired) if (r.valid) {
                if (error || (cancel && r.token == allocated.tokens[1])) throw std::runtime_error("faulted or cancelled retirement");
                ++retired;
            }
            if (out.fault && (!error || out.faultCause != 7 || out.faultTval != UINT64_C(0x80010000)))
                throw std::runtime_error("forwarding store fault");
            if (cycle == 17 && (out.occupancy != (error ? 2U : 0U) || out.fault != error || dut.get_io$$memoryBusy()))
                throw std::runtime_error("forwarding drain");
        }
        if (requests != 1 || forwarded != unsigned(!error) || retired != (error ? 0U : cancel ? 1U : 2U))
            throw std::runtime_error("forwarding coverage");
    }
}

// Fill all slots, cancel before any response, reuse a ROB index, then drain four errored old responses.
static void parallelCancellation() {
    SIntegerBackendGsim dut;
    drive(dut, Input{});
    dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    Token first{};
    unsigned requests = 0, discarded = 0, retired = 0;
    int newResponse = -1;
    bool reused = false;
    for (unsigned cycle = 0; cycle < 50; ++cycle) {
        Input in;
        in.inspect = 1;
        if (cycle < 2) {
            in.requests[0] = immediate(1 + cycle * 2, UINT64_C(0x80010000) + cycle * 16);
            in.requests[1] = immediate(2 + cycle * 2, UINT64_C(0x80010008) + cycle * 16);
        }
        if (cycle == 14) in.requests[0] = immediate(1, UINT64_C(0x80010080));
        in.recover = cycle == 8;
        in.inclusive = true;
        in.boundary = first;
        drive(dut, in);
        dut.set_io$$allocate0$$bits$$memory(in.requests[0].valid);
        dut.set_io$$allocate1$$bits$$memory(in.requests[1].valid);
        dut.set_io$$allocate0$$bits$$memorySize(3);
        dut.set_io$$allocate1$$bits$$memorySize(3);
        dut.set_io$$memory$$request$$ready(cycle >= 5);
        const bool oldResponse = cycle >= 24 && cycle <= 27;
        const bool responding = oldResponse || int(cycle) == newResponse;
        dut.set_io$$memory$$response$$valid(responding);
        dut.set_io$$memory$$response$$bits$$error(oldResponse);
        dut.set_io$$memory$$response$$bits$$data(oldResponse ? UINT64_C(0xbad00000) + cycle : 42);
        dut.step();
        const auto out = sample(dut);
        if (cycle == 0) { if (!out.allocated[0]) throw std::runtime_error("parallel setup"); first = out.tokens[0]; }
        if (cycle < 2 && !out.allocated[1]) throw std::runtime_error("parallel four-slot allocation");
        if (cycle == 8 && !out.recoveryAccepted) throw std::runtime_error("parallel recovery");
        if (cycle == 14) {
            if (!out.allocated[0] || out.tokens[0].index != first.index || out.tokens[0].tag == first.tag)
                throw std::runtime_error("parallel ROB reuse");
            reused = true;
        }
        if (dut.get_io$$memory$$request$$valid()) {
            const uint64_t expected = requests < 4 ? UINT64_C(0x80010000) + requests * 8 : UINT64_C(0x80010080);
            if (dut.get_io$$memory$$request$$bits$$address() != expected || dut.get_io$$memory$$request$$bits$$write())
                throw std::runtime_error("parallel request ownership/backpressure");
            if (cycle >= 5) {
                if (requests >= 5 || (requests == 4 && cycle < 26)) throw std::runtime_error("parallel capacity/reuse");
                if (requests == 4) newResponse = int(cycle) + 3;
                ++requests;
            }
        }
        if (cycle == 10 && requests != 4) throw std::runtime_error("four requests were not outstanding together");
        if (responding && !dut.get_io$$memory$$response$$ready()) throw std::runtime_error("parallel response drain");
        if (out.fault) throw std::runtime_error("cancelled parallel error became precise fault");
        for (const auto &r : out.issued) if (r.valid && (r.exception || r.data != 42))
            throw std::runtime_error("late response contaminated reused slot");
        for (const auto &r : out.retired) if (r.valid) {
            if (r.rd != 1 || r.data != 42) throw std::runtime_error("parallel replacement retirement");
            ++retired;
        }
        discarded += dut.get_io$$memoryDiscarded();
        if (cycle == 49 && (out.occupancy || dut.get_io$$memoryBusy() || out.inspected != 42))
            throw std::runtime_error("parallel final state");
    }
    if (!reused || requests != 5 || discarded != 4 || retired != 1) throw std::runtime_error("parallel coverage");
}

int main() {
    try {
        redirectArbitration();
        memoryRetirementProtection(false);
        memoryRetirementProtection(true);
        speculativeMemoryCancellation();
        memoryTurnaround();
        storeForwarding();
        parallelCancellation();
        Bench bench;
        arithmetic(bench);
        directed(bench);
        throughput(bench);
        for (uint64_t seed : {UINT64_C(0x2341), UINT64_C(0xab918), UINT64_C(0x982fab)}) randomized(bench, seed);
        bench.check(bench.stats.dualIssues > 100 && bench.stats.redirects > 100 && bench.stats.exceptions > 0,
                    "coverage thresholds");
        const auto &s = bench.stats;
        std::cout << "GSIM IntegerBackend: PASS rob=" << ROB_ENTRIES << " physical=" << PHYSICAL_REGS
                  << " cycles=" << s.cycles << " allocations=" << s.allocations << " issues=" << s.issues
                  << " commits=" << s.commits << " dualIssues=" << s.dualIssues << " outOfOrder=" << s.outOfOrder
                  << " redirects=" << s.redirects << " exceptions=" << s.exceptions
                  << " independentTwoWideCycles=" << s.independentTwoWideCycles
                  << " dependentOneWideCycles=" << s.dependentOneWideCycles
                  << " randomCycles=18000 seeds=3\n";
    } catch (const std::exception &error) {
        std::cerr << "GSIM IntegerBackend: FAIL " << error.what() << '\n';
        return 1;
    }
}
