#include "MemoryCapacityBackendGsim.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr uint64_t ram = UINT64_C(0x80200000);
constexpr uint64_t pc = UINT64_C(0x80001000);
constexpr uint64_t replacementData = UINT64_C(0x3141592653589793);
constexpr unsigned oldFirst = 4, oldLast = 7, replacement = 8;

struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Request {
    bool valid = false, writes = true, immediateOperand = true, memory = false, divide = false;
    unsigned id = 0, rd = 0, rs1 = 0, rs2 = 0, branch = 0;
    uint64_t immediate = 0, address = 0, expected = 0, pc = 0;
    uint32_t instruction = 0;
};
struct Input {
    std::array<Request, 2> requests{};
    bool commit = true, requestReady = false, response = false, error = false, pageFault = false;
    unsigned inspect = 0;
    uint64_t data = 0;
};
struct Completion {
    bool valid = false, exception = false;
    Token token{};
    uint64_t data = 0;
};
struct Commit {
    bool valid = false, writes = false;
    Token token{};
    unsigned rd = 0;
    uint64_t data = 0, pc = 0;
    uint32_t instruction = 0;
};
struct BusRequest {
    uint64_t address = 0, data = 0;
    unsigned size = 0, mask = 0, atomicOp = 0;
    bool write = false, atomic = false, virtualized = false, uncached = false;
    bool operator==(const BusRequest &) const = default;
};
struct Output {
    std::array<bool, 2> allocated{};
    std::array<Token, 2> tokens{};
    std::array<Completion, 2> completed{};
    std::array<Commit, 2> committed{};
    std::array<Token, 4> owners{};
    bool recovering = false, fault = false, redirect = false, request = false, responseReady = false;
    bool busy = false, discarded = false, forwarded = false;
    Token redirectToken{};
    uint64_t redirectTarget = 0, inspected = 0;
    unsigned occupancy = 0, liveMask = 0, discardMask = 0, lsuCredits = 0;
    unsigned queued = 0, storeCredits = 0, reads = 0, stores = 0, issueCount = 0;
    BusRequest bus{};
};

void drive(SMemoryCapacityBackendGsim &dut, const Input &in) {
    dut.set_io$$memory$$request$$ready(in.requestReady);
    dut.set_io$$memory$$response$$valid(in.response);
    dut.set_io$$memory$$response$$bits$$data(in.data);
    dut.set_io$$memory$$response$$bits$$error(in.error);
    dut.set_io$$memory$$response$$bits$$pageFault(in.pageFault);
#define DRIVE(N) \
    dut.set_io$$allocate##N##$$valid(in.requests[N].valid); \
    dut.set_io$$allocate##N##$$bits$$rename$$writesRd(in.requests[N].writes); \
    dut.set_io$$allocate##N##$$bits$$rename$$rs1(in.requests[N].rs1); \
    dut.set_io$$allocate##N##$$bits$$rename$$rs2(in.requests[N].rs2); \
    dut.set_io$$allocate##N##$$bits$$rename$$rd(in.requests[N].rd); \
    dut.set_io$$allocate##N##$$bits$$rename$$pc(in.requests[N].pc); \
    dut.set_io$$allocate##N##$$bits$$rename$$instruction(in.requests[N].instruction); \
    dut.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
    dut.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
    dut.set_io$$allocate##N##$$bits$$fetchFault(0); \
    dut.set_io$$allocate##N##$$bits$$fetchPageFault(0); \
    dut.set_io$$allocate##N##$$bits$$fetchTval(0); \
    dut.set_io$$allocate##N##$$bits$$expandedInstruction(0); \
    dut.set_io$$allocate##N##$$bits$$operation(0); \
    dut.set_io$$allocate##N##$$bits$$system(0); \
    dut.set_io$$allocate##N##$$bits$$mulDiv(in.requests[N].divide); \
    dut.set_io$$allocate##N##$$bits$$mulDivOp(in.requests[N].divide ? 5 : 0); \
    dut.set_io$$allocate##N##$$bits$$word(0); \
    dut.set_io$$allocate##N##$$bits$$usePc(0); \
    dut.set_io$$allocate##N##$$bits$$useImmediate(in.requests[N].immediateOperand); \
    dut.set_io$$allocate##N##$$bits$$immediate(in.requests[N].immediate); \
    dut.set_io$$allocate##N##$$bits$$controlFlow(in.requests[N].branch); \
    dut.set_io$$allocate##N##$$bits$$memory(in.requests[N].memory); \
    dut.set_io$$allocate##N##$$bits$$atomic(0); \
    dut.set_io$$allocate##N##$$bits$$atomicOp(0); \
    dut.set_io$$allocate##N##$$bits$$store(0); \
    dut.set_io$$allocate##N##$$bits$$memorySize(3); \
    dut.set_io$$allocate##N##$$bits$$memoryUnsigned(0);
    DRIVE(0)
    DRIVE(1)
#undef DRIVE
    dut.set_io$$commitEnable(in.commit);
    dut.set_io$$inspectRegister(in.inspect);
}

Output sample(SMemoryCapacityBackendGsim &dut) {
    Output out;
#define SAMPLE(N) \
    out.allocated[N] = dut.get_io$$renamed##N##$$valid(); \
    out.tokens[N] = {dut.get_io$$renamed##N##$$bits$$token$$index(), \
                     dut.get_io$$renamed##N##$$bits$$token$$tag()}; \
    out.completed[N] = {bool(dut.get_io$$issued##N##$$valid()), \
        bool(dut.get_io$$issued##N##$$bits$$exception()), \
        {dut.get_io$$issued##N##$$bits$$token$$index(), dut.get_io$$issued##N##$$bits$$token$$tag()}, \
        dut.get_io$$issued##N##$$bits$$data()}; \
    out.committed[N] = {bool(dut.get_io$$commit##N##$$valid()), bool(dut.get_io$$commit##N##$$bits$$writesRd()), \
        {dut.get_io$$commit##N##$$bits$$token$$index(), dut.get_io$$commit##N##$$bits$$token$$tag()}, \
        dut.get_io$$commit##N##$$bits$$rd(), dut.get_io$$commit##N##$$bits$$data(), \
        dut.get_io$$commit##N##$$bits$$pc(), dut.get_io$$commit##N##$$bits$$instruction()};
    SAMPLE(0)
    SAMPLE(1)
#undef SAMPLE
#define OWNER(N) out.owners[N] = {dut.get_io$$lsuOwner##N##$$index(), dut.get_io$$lsuOwner##N##$$tag()};
    OWNER(0)
    OWNER(1)
    OWNER(2)
    OWNER(3)
#undef OWNER
    out.recovering = dut.get_io$$recovering();
    out.occupancy = dut.get_io$$occupancy();
    out.fault = dut.get_io$$headException$$valid();
    out.redirect = dut.get_io$$redirect$$valid();
    out.redirectToken = {dut.get_io$$redirect$$bits$$token$$index(), dut.get_io$$redirect$$bits$$token$$tag()};
    out.redirectTarget = dut.get_io$$redirect$$bits$$target();
    out.inspected = dut.get_io$$committedValue();
    out.request = dut.get_io$$memory$$request$$valid();
    out.responseReady = dut.get_io$$memory$$response$$ready();
    out.bus = {dut.get_io$$memory$$request$$bits$$address(), dut.get_io$$memory$$request$$bits$$data(),
        dut.get_io$$memory$$request$$bits$$size(), dut.get_io$$memory$$request$$bits$$mask(),
        dut.get_io$$memory$$request$$bits$$atomicOp(), bool(dut.get_io$$memory$$request$$bits$$write()),
        bool(dut.get_io$$memory$$request$$bits$$atomic()), bool(dut.get_io$$memory$$request$$bits$$virtualized()),
        bool(dut.get_io$$memory$$request$$bits$$uncached())};
    out.busy = dut.get_io$$memoryBusy();
    out.discarded = dut.get_io$$memoryDiscarded();
    out.forwarded = dut.get_io$$memoryForwarded();
    out.liveMask = dut.get_io$$lsuLiveMask();
    out.discardMask = dut.get_io$$lsuDiscardMask();
    out.lsuCredits = dut.get_io$$lsuOwnerCredits();
    out.queued = dut.get_io$$queuedRequests();
    out.storeCredits = dut.get_io$$storeOwnerCredits();
    out.reads = dut.get_io$$pendingReads();
    out.stores = dut.get_io$$bufferedStores();
    out.issueCount = dut.get_io$$issueCount();
    return out;
}

// These are decoded backend stimuli. Architectural expectations are unsigned C++ arithmetic,
// and memory replies come from the fixed external memory model below, never from DUT data/owner decisions.
Request add(unsigned id, unsigned rd, uint64_t immediate, unsigned rs1 = 0, uint64_t expected = 0) {
    Request r;
    r.valid = true; r.id = id; r.rd = rd; r.rs1 = rs1; r.immediate = immediate;
    r.expected = rs1 ? expected : immediate; r.pc = pc + 4 * id;
    r.instruction = (uint32_t(immediate & 0xfff) << 20) | (rs1 << 15) | (rd << 7) | 0x13;
    return r;
}
Request load(unsigned id, unsigned rd, uint64_t address) {
    auto r = add(id, rd, address);
    r.memory = true; r.address = address;
    r.expected = id == replacement ? replacementData : 0;
    r.instruction = (rd << 7) | 0x3003;
    return r;
}
std::vector<Request> oldProgram() {
    std::vector<Request> p{add(0, 20, UINT64_MAX), add(1, 21, 3)};
    auto divide = add(2, 22, 0, 20, UINT64_MAX / 3);
    divide.rs2 = 21; divide.immediateOperand = false; divide.divide = true;
    divide.instruction = (1U << 25) | (21U << 20) | (20U << 15) | (5U << 12) | (22U << 7) | 0x33;
    p.push_back(divide);
    auto branch = add(3, 0, 0x100, 22, 0);
    branch.rs2 = 22; branch.immediateOperand = false; branch.writes = false; branch.branch = 1;
    branch.instruction = 0x116b0063; // BEQ x22,x22,+256; its full token must produce the redirect.
    p.push_back(branch);
    for (unsigned i = 0; i < 4; ++i) p.push_back(load(oldFirst + i, i + 1, ram + 8 * i));
    return p;
}
std::vector<Request> newProgram(bool inject) {
    auto first = load(replacement, 1, ram + 0x80);
    if (inject) first.expected ^= 1;
    return {first, add(9, 2, 91), add(10, 3, 107), add(11, 4, 123),
            add(12, 5, 1, 1, replacementData + 1)};
}
bool cancelledId(unsigned id) { return id >= oldFirst && id <= oldLast; }
struct Entry { Token token; Request request; bool completed = false; };
struct Reply { unsigned id; uint64_t data; bool error, pageFault; };

class Bench {
    SMemoryCapacityBackendGsim dut;
    std::array<uint64_t, 32> architectural{};
    std::deque<Entry> live;
    std::deque<Reply> replies;
    std::array<Token, 13> tokens{};
    std::array<bool, 13> allocated{}, accepted{}, answered{}, completed{}, retired{}, discarded{};
    uint64_t random;
    bool requestHeld = false, responseHeld = false;
    BusRequest heldRequest{};
    unsigned tail = 0;
    uint64_t nextTag = 0;
    bool inject = false;
    const char *phase = "initial admission";

    uint64_t nextRandom() {
        random ^= random << 13; random ^= random >> 7; random ^= random << 17;
        return random;
    }
    unsigned ownerId(Token token) const {
        for (unsigned id = 0; id < tokens.size(); ++id)
            if (allocated[id] && tokens[id] == token) return id;
        return unsigned(tokens.size());
    }
    bool creditsEmpty(const Output &out) const {
        return !out.liveMask && !out.lsuCredits && !out.queued && !out.storeCredits &&
               !out.reads && !out.stores && !out.busy;
    }
public:
    uint64_t cycles = 0;
    unsigned requestCount = 0, responseCount = 0, discardCount = 0, commitCount = 0;
    unsigned redirects = 0, maximumOutstanding = 0, stalledRequests = 0, fullWitnesses = 0;
    unsigned reusedWhileFourPending = 0, replacementCompleted = 0;
    bool commitEnable = true, releaseReplies = false;
    Output last{};

    Bench(uint64_t seed, bool injectOracle) : random(seed), inject(injectOracle) {
        drive(dut, {});
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    void check(bool condition, const std::string &message) const {
        if (!condition) throw std::runtime_error("cycle " + std::to_string(cycles) + ", phase " + phase + ": " +
            message + " [requests=" + std::to_string(requestCount) + " responses=" + std::to_string(responseCount) +
            " discarded=" + std::to_string(discardCount) + " redirects=" + std::to_string(redirects) +
            " commits=" + std::to_string(commitCount) + " completedNew=" + std::to_string(replacementCompleted) +
            " oracleLive=" + std::to_string(live.size()) + " rob=" + std::to_string(last.occupancy) +
            " lsuMask=" + std::to_string(last.liveMask) + " lsuCredits=" + std::to_string(last.lsuCredits) +
            " queued=" + std::to_string(last.queued) + " ownerCredits=" + std::to_string(last.storeCredits) +
            " readCredits=" + std::to_string(last.reads) + " busy=" + std::to_string(last.busy) + "]");
    }
    Output tick(Input in = {}) {
        check(cycles < 2000, "event-driven phase timeout");
        in.commit = commitEnable;
        // Force a witnessed held request, then use deterministic independent backpressure.
        in.requestReady = stalledRequests >= 3 && (nextRandom() & 3) != 0;
        const bool canReply = releaseReplies && !replies.empty() &&
            (cancelledId(replies.front().id) || discardCount == 4);
        in.response = canReply && (responseHeld || (nextRandom() & 3) != 0);
        if (in.response) {
            const auto &reply = replies.front();
            in.data = reply.data; in.error = reply.error; in.pageFault = reply.pageFault;
        }
        drive(dut, in); dut.step(); auto out = sample(dut); ++cycles;
        check(!out.fault, "stale response became a precise exception");
        check(!out.forwarded, "load-only program unexpectedly used store forwarding");
        check(out.issueCount <= 2, "selected two-issue limit");
        check(out.inspected == architectural[in.inspect], "committed register mismatch x" + std::to_string(in.inspect));
        if (!out.recovering && !out.redirect) check(out.occupancy == live.size(), "independent ROB occupancy");
        check(out.lsuCredits <= 4 && out.storeCredits <= 4 && out.reads <= 4 && out.queued <= 4,
              "memory credit capacity exceeded");
        check(out.stores == 0, "load-only program allocated store credits");
        if (requestHeld) check(out.request && out.bus == heldRequest, "request changed under backpressure");
        requestHeld = out.request && !in.requestReady;
        if (requestHeld) { heldRequest = out.bus; ++stalledRequests; }
        responseHeld = in.response && !out.responseReady;

        // Registered StoreBuffer owner/read credits must exactly conserve externally accepted requests.
        check(out.storeCredits == replies.size() && out.reads == replies.size(), "external owner/read credit conservation");
        if (out.liveMask == 15 && requestCount == 4 && responseCount == 0) {
            std::set<unsigned> owners;
            for (const auto &token : out.owners) owners.insert(ownerId(token));
            check(owners == std::set<unsigned>({4, 5, 6, 7}), "four live slots lost their original owners");
            check(out.lsuCredits == 4 && out.storeCredits == 4 && out.queued == 0,
                  "four live accepted loads must retain all response credits");
            ++fullWitnesses;
        }
        if (in.response && out.responseReady) {
            const auto reply = replies.front(); replies.pop_front();
            check(!answered[reply.id], "duplicate memory response");
            if (cancelledId(reply.id)) {
                check(redirects == 1 && reusedWhileFourPending == 1 && reply.error,
                      "old error released before actual cancellation and generation reuse");
            }
            answered[reply.id] = true; ++responseCount;
        }
        if (out.request && in.requestReady) {
            check(!out.bus.write && !out.bus.atomic && !out.bus.virtualized && !out.bus.uncached &&
                  out.bus.size == 3 && out.bus.mask == 255, "unexpected read request attributes");
            unsigned id = unsigned(tokens.size());
            for (unsigned i = 0; i < 4; ++i) if (out.bus.address == ram + 8 * i) id = oldFirst + i;
            if (out.bus.address == ram + 0x80) id = replacement;
            check(id < tokens.size() && allocated[id] && !accepted[id], "unowned, duplicate, or wrong-address memory request");
            if (cancelledId(id)) check(redirects == 0, "four old requests were not accepted before recovery");
            else check(reusedWhileFourPending == 1 && discardCount != 0,
                       "replacement used a memory slot before an old response released it");
            accepted[id] = true; ++requestCount;
            // Payload and flags are independent of the DUT's reported result.
            replies.push_back({id, cancelledId(id) ? UINT64_C(0xbad0000000000000) + id : replacementData,
                               cancelledId(id), cancelledId(id) && ((id & 1) != 0)});
            maximumOutstanding = std::max(maximumOutstanding, unsigned(replies.size()));
            check(replies.size() <= 4, "more than four external requests outstanding");
        }
        if (out.redirect) {
            check(redirects == 0 && allocated[3] && out.redirectToken == tokens[3], "unexpected redirect owner");
            check(out.redirectTarget == pc + 12 + 0x100, "independent taken-BEQ target");
            check(requestCount == 4 && responseCount == 0 && replies.size() == 4 && fullWitnesses != 0,
                  "recovery occurred before four accepted loads were simultaneously live");
            auto branch = std::find_if(live.begin(), live.end(), [](const Entry &e) { return e.request.id == 3; });
            check(branch != live.end(), "redirecting branch missing from independent ledger");
            check(std::distance(branch + 1, live.end()) == 4, "recovery did not cancel exactly four loads");
            for (auto at = branch + 1; at != live.end(); ++at)
                check(cancelledId(at->request.id) && !at->completed, "unexpected recovery victim");
            live.erase(branch + 1, live.end());
            tail = (tokens[3].index + 1) % 16;
            ++redirects;
        }
        check(out.discarded == (out.discardMask != 0), "discard aggregate witness");
        for (unsigned slot = 0; slot < 4; ++slot) if ((out.discardMask >> slot) & 1) {
            const unsigned id = ownerId(out.owners[slot]);
            check(id < tokens.size() && cancelledId(id) && answered[id] && !discarded[id],
                  "discarded response has wrong token, has not returned, or was already discarded");
            discarded[id] = true; ++discardCount;
        }
        for (const auto &result : out.completed) if (result.valid) {
            auto at = std::find_if(live.begin(), live.end(), [&](const Entry &e) { return e.token == result.token; });
            check(at != live.end() && !cancelledId(at->request.id), "stale token wrote back after cancellation");
            check(!at->completed && !result.exception, "duplicate or erroneous live completion");
            check(result.data == at->request.expected, "independent completion data mismatch for instruction " +
                  std::to_string(at->request.id));
            if (at->request.memory) check(answered[at->request.id], "load completed before its own external reply");
            at->completed = true; completed[at->request.id] = true;
            if (at->request.id >= replacement) ++replacementCompleted;
        }
        for (const auto &result : out.committed) if (result.valid) {
            check(in.commit && !live.empty(), "retirement without permission/live owner");
            const auto entry = live.front(); live.pop_front();
            const auto &r = entry.request;
            check(entry.completed && result.token == entry.token && !cancelledId(r.id), "stale or unordered retirement");
            check(result.pc == r.pc && result.instruction == r.instruction && result.rd == r.rd &&
                  result.writes == (r.writes && r.rd != 0), "retirement metadata mismatch");
            check(result.data == r.expected, "independent retirement data mismatch");
            check(!retired[r.id], "duplicate retirement");
            if (result.writes) architectural[r.rd] = r.expected;
            retired[r.id] = true; ++commitCount;
        }
        check(!out.allocated[1] || out.allocated[0], "non-prefix two-wide allocation");
        for (unsigned lane = 0; lane < 2; ++lane) if (out.allocated[lane]) {
            const auto &r = in.requests[lane];
            check(r.valid && !allocated[r.id], "unexpected or duplicate allocation");
            check(out.tokens[lane] == Token{tail, nextTag}, "independent ROB index/generation allocation");
            tail = (tail + 1) % 16; ++nextTag;
            allocated[r.id] = true; tokens[r.id] = out.tokens[lane];
            live.push_back({out.tokens[lane], r});
            if (r.id == replacement) {
                check(redirects == 1 && responseCount == 0 && replies.size() == 4 && out.liveMask == 15,
                      "generation reuse must precede all four stale error replies");
                check(out.tokens[lane].index == tokens[oldFirst].index && out.tokens[lane].tag != tokens[oldFirst].tag,
                      "replacement did not reuse canceled ROB index with a new generation");
                ++reusedWhileFourPending;
            }
        }
        last = out;
        return out;
    }
    void program(const std::vector<Request> &requests) {
        size_t at = 0;
        while (at < requests.size()) {
            Input in; in.requests[0] = requests[at];
            if (at + 1 < requests.size()) in.requests[1] = requests[at + 1];
            const auto out = tick(in);
            at += unsigned(out.allocated[0]) + unsigned(out.allocated[1]);
        }
    }
    void run() {
        program(oldProgram());
        phase = "await four loads and branch redirect";
        while (!redirects) tick();
        phase = "recovery and older retirement drain";
        while (last.recovering || !retired[3] || !live.empty()) tick();
        check(requestCount == 4 && responseCount == 0 && discardCount == 0, "old responses escaped before reuse");
        phase = "replacement admission before stale replies";
        program(newProgram(inject));
        check(reusedWhileFourPending == 1, "ROB generation reuse coverage");
        releaseReplies = true;
        // commitEnable also authorizes LSU starts in the real backend. Keep it high until the
        // replacement request has handshaken, then hold retirement before its external reply.
        // The unresolved replacement load is the head, so younger ALUs cannot retire meanwhile.
        phase = "replacement request after stale slot release";
        while (!accepted[replacement]) tick();
        check(!answered[replacement] && commitCount == 4, "replacement retired before the commit hold");
        commitEnable = false;
        phase = "stale errors and replacement reply drain";
        while (responseCount != 5 || discardCount != 4 || replacementCompleted != 5 || !creditsEmpty(last)) tick();
        check(live.size() == 5 && commitCount == 4, "retirement backpressure did not retain replacement program");
        commitEnable = true;
        phase = "replacement retirement drain";
        while (!live.empty() || last.occupancy != 0 || !creditsEmpty(last)) tick();
        // A complete architectural sweep also gives delayed erroneous faults/writebacks time to become observable.
        phase = "architectural register sweep";
        for (unsigned reg = 0; reg < 32; ++reg) { Input in; in.inspect = reg; tick(in); }
        check(creditsEmpty(last) && replies.empty() && !last.request && !last.responseReady,
              "response owners or request/LSU credits failed to drain");
        check(requestCount == 5 && responseCount == 5 && discardCount == 4 && commitCount == 9 &&
              maximumOutstanding == 4 && fullWitnesses != 0 && stalledRequests >= 3,
              "selected-profile cancellation coverage incomplete");
        for (unsigned id = oldFirst; id <= oldLast; ++id)
            check(allocated[id] && accepted[id] && answered[id] && discarded[id] && !completed[id] && !retired[id],
                  "canceled load escaped its independent ownership lifecycle");
    }
};
} // namespace

int main(int argc, char **argv) {
    try {
        const bool inject = argc == 2 && std::string(argv[1]) == "--inject-oracle-error";
        if (argc > 1 && !inject) throw std::runtime_error("usage: memory-capacity-backend [--inject-oracle-error]");
        uint64_t cycles = 0;
        unsigned stalls = 0, full = 0;
        for (const uint64_t seed : {UINT64_C(0x2341), UINT64_C(0xab918), UINT64_C(0x982fab)}) {
            Bench bench(seed, inject); bench.run();
            cycles += bench.cycles; stalls += bench.stalledRequests; full += bench.fullWitnesses;
        }
        std::cout << "GSIM selected four-slot backend: PASS profile=staged-fetch-turnover-mlp4"
                  << " issue=2 rob=16 physical=48 predictor=32 memory=4 seeds=3 cycles=" << cycles
                  << " acceptedOldLoads=12 staleErrorReplies=12 discarded=12 generationReuseBeforeReplies=3"
                  << " maxOutstanding=4 replacementRetirements=15 fullOwnerWitnesses=" << full
                  << " requestStalls=" << stalls << " allCreditsDrained=3\n";
    } catch (const std::exception &error) {
        std::cerr << "GSIM selected four-slot backend: FAIL " << error.what() << '\n';
        return 1;
    }
}
