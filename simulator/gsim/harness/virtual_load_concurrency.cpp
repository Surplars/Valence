#include "VirtualLoadConcurrencyGsim.h"
#include "virtual_load_test_memory.h"
#include <algorithm>
#include <array>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <tuple>
#include <vector>
#ifndef PRECHECK_ENABLED
#define PRECHECK_ENABLED 0
#endif
using namespace virtual_load_test;
struct Token { unsigned index = 0; uint64_t tag = 0; bool operator==(const Token &) const = default; };
struct Request {
    bool valid = false, memory = false, store = false, system = false, writes = true, branch = false, mulDiv = false;
    unsigned rd = 1, rs1 = 0, rs2 = 0;
    uint64_t immediate = 0, pc = 0, expected = 0, expectedCause = 0, virtualAddress = 0;
    uint32_t instruction = 0x13;
    bool fault = false, physicalError = false;
};
struct Entry { Token token; Request request; bool requested = false, started = false, canonical = false, upstreamSeen = false; };
struct Pending { uint64_t due = 0, data = 0; Token token{}; bool error = false; };
struct Input { std::array<Request, 2> requests{}; bool recover = false, inclusive = true; Token boundary{}; };
struct Result { std::array<bool, 2> accepted{}; std::array<Token, 2> tokens{}; bool recovered = false; };
static Request add(unsigned rd, uint64_t value) { Request r; r.valid = true; r.rd = rd; r.immediate = value; r.expected = value; return r; }
static Request load(unsigned rd, uint64_t address) { Request r = add(rd, address); r.memory = true; r.virtualAddress = address; return r; }
static Request store(uint64_t address, unsigned rs2 = 30) { Request r = load(0, address); r.store = true; r.rs2 = rs2; r.writes = false; r.instruction = 0x3023; return r; }
// A real 64-iteration DIV keeps the retirement head busy while independent
// younger virtual loads obtain their registered certificates.
static Request divide() {
    Request r = add(24, 0); r.mulDiv = true; r.rs1 = 25; r.rs2 = 26;
    r.expected = 123456789ULL / 7; r.instruction = (1U << 25) | (26U << 20) | (25U << 15) | (4U << 12) | (24U << 7) | 0x33;
    return r;
}
static Request system(uint32_t instruction, unsigned rs1 = 0) { Request r = add(0, 0); r.writes = false; r.system = true; r.rs1 = rs1; r.instruction = instruction; return r; }
class Bench {
    SVirtualLoadConcurrencyGsim d;
    std::deque<Entry> live;
    std::deque<Pending> replies, ptes;
    std::array<uint64_t, 32> architectural{};
    std::map<uint64_t, uint64_t> expectedMemory, physicalMemory;
    std::optional<std::tuple<uint64_t, uint64_t, bool, unsigned, bool>> held;
    std::map<uint64_t, uint64_t> firstPeek;
    uint64_t nextPc = 0x1000;
public:
    PageTables tables;
    uint64_t cycle = 0, caseStart = 0, coldCycles = 0, trace = 1469598103934665603ULL;
    unsigned latency = 35, holdPhysicalUntil = 0, holdReplyUntil = 0, secondLatency = 0;
    unsigned allocated = 0, retired = 0, physicalRequests = 0, physicalResponses = 0, peak = 0;
    unsigned precheckedStarts = 0, serialStarts = 0, serialBeforeProof = 0, pteReads = 0, walks = 0, hits = 0, queryHits = 0;
    unsigned trapCount = 0, physicalHolds = 0, cancellations = 0, reuse = 0, redirects = 0, cancelledSlotReuse = 0;
    bool commitEnable = true, inject = false;
    std::set<std::pair<unsigned, uint64_t>> killed;
    std::map<unsigned, uint64_t> generations;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); for (unsigned n = 0; n < 5; ++n) tick(); }
    void check(bool ok, const std::string &why) const { require(ok, "cycle " + std::to_string(cycle) + ": " + why); }
    uint64_t expectedAt(uint64_t address) { auto p = tables.physical(address); return expectedMemory.count(p) ? expectedMemory[p] : readValue(p); }
    void drive(const Input &in) {
#define DRIVE(N) \
        d.set_io$$allocate##N##$$valid(in.requests[N].valid); \
        d.set_io$$allocate##N##$$bits$$rename$$writesRd(in.requests[N].writes); \
        d.set_io$$allocate##N##$$bits$$rename$$rs1(in.requests[N].rs1); \
        d.set_io$$allocate##N##$$bits$$rename$$rs2(in.requests[N].rs2); \
        d.set_io$$allocate##N##$$bits$$rename$$rd(in.requests[N].rd); \
        d.set_io$$allocate##N##$$bits$$rename$$pc(in.requests[N].pc); \
        d.set_io$$allocate##N##$$bits$$rename$$instruction(in.requests[N].instruction); \
        d.set_io$$allocate##N##$$bits$$expandedInstruction(in.requests[N].instruction); \
        d.set_io$$allocate##N##$$bits$$system(in.requests[N].system); \
        d.set_io$$allocate##N##$$bits$$memory(in.requests[N].memory); \
        d.set_io$$allocate##N##$$bits$$store(in.requests[N].store); \
        d.set_io$$allocate##N##$$bits$$memorySize(3); \
        d.set_io$$allocate##N##$$bits$$memoryUnsigned(0); \
        d.set_io$$allocate##N##$$bits$$immediate(in.requests[N].immediate); \
        d.set_io$$allocate##N##$$bits$$operation(0); \
        d.set_io$$allocate##N##$$bits$$word(0); \
        d.set_io$$allocate##N##$$bits$$usePc(0); \
        d.set_io$$allocate##N##$$bits$$useImmediate(!in.requests[N].branch && !in.requests[N].mulDiv); \
        d.set_io$$allocate##N##$$bits$$controlFlow(in.requests[N].branch ? 1 : 0); \
        d.set_io$$allocate##N##$$bits$$mulDiv(in.requests[N].mulDiv); \
        d.set_io$$allocate##N##$$bits$$mulDivOp(in.requests[N].mulDiv ? 4 : 0); \
        d.set_io$$allocate##N##$$bits$$atomic(0); \
        d.set_io$$allocate##N##$$bits$$atomicOp(0); \
        d.set_io$$allocate##N##$$bits$$predictedNextPc$$valid(0); \
        d.set_io$$allocate##N##$$bits$$predictedNextPc$$bits(0); \
        d.set_io$$allocate##N##$$bits$$fetchFault(0); \
        d.set_io$$allocate##N##$$bits$$fetchPageFault(0); \
        d.set_io$$allocate##N##$$bits$$fetchTval(0);
        DRIVE(0) DRIVE(1)
#undef DRIVE
        d.set_io$$commitEnable(commitEnable); d.set_io$$inspectRegister(cycle % 32);
        d.set_io$$recover$$valid(in.recover); d.set_io$$recover$$bits$$inclusive(in.inclusive);
        d.set_io$$recover$$bits$$token$$index(in.boundary.index); d.set_io$$recover$$bits$$token$$tag(in.boundary.tag);
        d.set_io$$physical$$request$$ready(cycle >= holdPhysicalUntil && cycle % 9 != 5);
        const bool reply = !replies.empty() && replies.front().due <= cycle && cycle >= holdReplyUntil;
        d.set_io$$physical$$response$$valid(reply);
        d.set_io$$physical$$response$$bits$$data(reply ? replies.front().data : 0);
        d.set_io$$physical$$response$$bits$$error(reply && replies.front().error);
        d.set_io$$physical$$response$$bits$$pageFault(0);
        d.set_io$$pte$$request$$ready(cycle % 5 != 3);
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        d.set_io$$pte$$response$$valid(pte); d.set_io$$pte$$response$$bits$$data(pte ? ptes.front().data : 0);
        d.set_io$$pte$$response$$bits$$error(0);
    }
    Result tick(Input in = {}) {
        const bool reply = !replies.empty() && replies.front().due <= cycle && cycle >= holdReplyUntil;
        const bool pte = !ptes.empty() && ptes.front().due <= cycle;
        drive(in); d.step(); Result out;
        check(d.get_io$$committedValue() == architectural[cycle % 32], "committed register architectural oracle mismatch");
#define ACCEPT(N) \
        out.accepted[N] = d.get_io$$renamed##N##$$valid(); \
        out.tokens[N] = {unsigned(d.get_io$$renamed##N##$$bits$$token$$index()), uint64_t(d.get_io$$renamed##N##$$bits$$token$$tag())};
        ACCEPT(0) ACCEPT(1)
#undef ACCEPT
        for (unsigned n = 0; n < 2; ++n) if (out.accepted[n]) {
            check(in.requests[n].valid, "allocation without offered instruction");
            auto r = in.requests[n];
            if (r.memory && !r.fault) {
                const uint64_t address = r.virtualAddress;
                if (r.store) expectedMemory[tables.physical(address)] = architectural[r.rs2];
                else r.expected = expectedAt(address);
            }
            auto old = generations.find(out.tokens[n].index);
            if (old != generations.end() && old->second != out.tokens[n].tag) ++reuse;
            generations[out.tokens[n].index] = out.tokens[n].tag;
            for (const auto &[index, tag] : killed)
                if (index == out.tokens[n].index && tag != out.tokens[n].tag) ++cancelledSlotReuse;
            live.push_back({out.tokens[n], r}); ++allocated;
        }
        out.recovered = d.get_io$$recoveryAccepted();
        if (out.recovered && in.recover) {
            auto at = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == in.boundary; });
            check(at != live.end(), "recovery boundary lost full-token owner");
            auto first = at + !in.inclusive;
            for (auto it = first; it != live.end(); ++it) { killed.insert({it->token.index, it->token.tag}); ++cancellations; }
            live.erase(first, live.end());
        }
        if (d.get_io$$redirect$$valid() && !d.get_io$$trap$$valid()) {
            const Token token{unsigned(d.get_io$$redirect$$bits$$token$$index()), uint64_t(d.get_io$$redirect$$bits$$token$$tag())};
            auto at = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == token; });
            check(at != live.end() && (at->request.branch || at->request.system), "redirect lost branch/system full-token owner");
            if (at->request.branch) {
                check(d.get_io$$redirect$$bits$$target() == at->request.pc + at->request.immediate,
                    "taken branch target/provenance mismatch");
                ++redirects;
            }
            for (auto it = at + 1; it != live.end(); ++it) { killed.insert({it->token.index, it->token.tag}); ++cancellations; }
            live.erase(at + 1, live.end());
        }
        if (reply && d.get_io$$physical$$response$$ready()) { replies.pop_front(); ++physicalResponses; }
        if (pte && d.get_io$$pte$$response$$ready()) ptes.pop_front();
        if (d.get_io$$pte$$request$$valid() && cycle % 5 != 3) {
            ptes.push_back({cycle + 2, tables.pte(d.get_io$$pte$$request$$bits())}); ++pteReads;
        }
        if (d.get_io$$queryHit()) {
            ++queryHits; const uint64_t address = d.get_io$$queryAddress();
            check(d.get_io$$queryPhysical() == tables.physical(address), "peek differed from independent page tables");
            if (!firstPeek.count(address)) firstPeek[address] = cycle;
        }
        if (d.get_io$$lsuStart()) {
            const Token token{unsigned(d.get_io$$lsuToken$$index()), uint64_t(d.get_io$$lsuToken$$tag())};
            auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) { return e.token == token; });
            check(owner != live.end(), "LSU start used cancelled/stale full ROB token"); owner->started = true;
            check(d.get_io$$lsuVa() == owner->request.virtualAddress, "LSU lost original virtual address");
            if (d.get_io$$lsuPrechecked()) {
                ++precheckedStarts; owner->canonical = true; const auto address = d.get_io$$lsuVa();
                check(PRECHECK_ENABLED && !owner->request.store && (!owner->request.fault || owner->request.physicalError) && d.get_io$$lsuParallel(), "invalid speculative certificate use");
                check(d.get_io$$lsuPa() == tables.physical(address), "canonical physical alias mismatch");
                check(firstPeek.count(address) && cycle >= firstPeek[address] + 2, "lookup/PMP/issue register cut collapsed");
                for (auto older = live.begin(); older != owner; ++older)
                    check(!older->request.memory || (!older->request.store && older->canonical), "younger certified load crossed older live store/uncanonical memory");
            } else {
                ++serialStarts;
                const auto found = firstPeek.find(owner->request.virtualAddress);
                if (found != firstPeek.end() && cycle < found->second + 2) ++serialBeforeProof;
            }
        }
        if (d.get_io$$upstreamFire()) {
            const uint64_t address = d.get_io$$upstreamAddress();
            auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) {
                return e.request.memory && !e.upstreamSeen && address ==
                    (e.canonical ? tables.physical(e.request.virtualAddress) : e.request.virtualAddress);
            });
            check(owner != live.end(), "upstream request lost captured VA/PA owner");
            check(bool(d.get_io$$upstreamPrechecked()) == owner->canonical,
                "accepted serial request changed authorization class after late certificate");
            owner->upstreamSeen = true;
        }
        const bool valid = d.get_io$$physical$$request$$valid();
        auto payload = std::make_tuple(uint64_t(d.get_io$$physical$$request$$bits$$address()),
            uint64_t(d.get_io$$physical$$request$$bits$$data()), bool(d.get_io$$physical$$request$$bits$$write()),
            unsigned(d.get_io$$physical$$request$$bits$$mask()), bool(d.get_io$$physical$$request$$bits$$uncached()));
        const bool ready = cycle >= holdPhysicalUntil && cycle % 9 != 5;
        if (held) check(valid && payload == *held, "held data request payload changed");
        held = valid && !ready ? std::optional{payload} : std::nullopt; physicalHolds += valid && !ready;
        if (valid && ready) {
            const auto address = std::get<0>(payload); const bool write = std::get<2>(payload);
            auto owner = std::find_if(live.begin(), live.end(), [&](const auto &e) {
                return e.request.memory && !e.requested && (!e.request.fault || e.request.physicalError) &&
                    e.request.store == write && tables.physical(e.request.virtualAddress) == address;
            });
            check(owner != live.end(), "speculative fault/MMIO traffic, duplicate, or unowned physical request");
            owner->requested = true;
            const auto &mapping = tables.pages.at(unsigned((owner->request.virtualAddress - va) / 4096));
            check(std::get<4>(payload) == (mapping.pbmt != 0), "PBMT cacheability mismatch");
            if (address < ram || address >= ram + ramBytes || mapping.pbmt)
                check(owner == live.begin() && replies.empty(), "device/PBMT request speculated or overlapped");
            check(!d.get_io$$physical$$request$$bits$$virtualized() && !d.get_io$$physical$$request$$bits$$precheckedLoad(),
                "internal authorization metadata leaked downstream");
            if (write) { check(std::get<1>(payload) == architectural[owner->request.rs2] && std::get<3>(payload) == 255,
                "store physical payload mismatch"); physicalMemory[address] = std::get<1>(payload); }
            const uint64_t data = write ? 0 : (physicalMemory.count(address) ? physicalMemory[address] : readValue(address));
            replies.push_back({cycle + ((secondLatency && physicalRequests == 1) ? secondLatency : latency), data, owner->token, owner->request.physicalError});
            ++physicalRequests; peak = std::max(peak, unsigned(replies.size()));
        }
#define RETIRE(N) \
        if (d.get_io$$commit##N##$$valid()) { \
            check(!live.empty(), "retirement without live owner"); auto e = live.front(); live.pop_front(); \
            const Token token{unsigned(d.get_io$$commit##N##$$bits$$token$$index()), uint64_t(d.get_io$$commit##N##$$bits$$token$$tag())}; \
            check(e.token == token && !e.request.fault && !killed.count({token.index, token.tag}), "retirement full-token order/cancellation mismatch"); \
            check(d.get_io$$commit##N##$$bits$$pc() == e.request.pc && d.get_io$$commit##N##$$bits$$instruction() == e.request.instruction, "retirement provenance mismatch"); \
            if (e.request.writes && e.request.rd) { \
                check(d.get_io$$commit##N##$$bits$$data() == (e.request.expected ^ (inject ? 1ULL : 0ULL)), "independent architectural result mismatch"); \
                architectural[e.request.rd] = e.request.expected; \
            } \
            trace ^= e.request.pc; trace *= 1099511628211ULL; trace ^= e.request.writes ? e.request.expected : 0; trace *= 1099511628211ULL; ++retired; \
        }
        RETIRE(0) RETIRE(1)
#undef RETIRE
        if (d.get_io$$trap$$valid()) {
            check(!live.empty(), "trap without live owner"); const auto e = live.front();
            const Token token{unsigned(d.get_io$$trap$$bits$$token$$index()), uint64_t(d.get_io$$trap$$bits$$token$$tag())};
            check(e.request.fault && token == e.token && d.get_io$$trap$$bits$$pc() == e.request.pc &&
                d.get_io$$trap$$bits$$cause() == e.request.expectedCause &&
                d.get_io$$trap$$bits$$tval() == e.request.virtualAddress, "precise fault must retain original VA, PC and full token");
            live.clear(); ++trapCount;
        }
        walks += d.get_io$$translationWalk(); hits += d.get_io$$translationHit();
        ++cycle; return out;
    }
    std::vector<Token> submit(std::vector<Request> requests) {
        for (auto &r : requests) { r.pc = nextPc; nextPc += 4; }
        std::vector<Token> tokens; unsigned cursor = 0;
        for (unsigned n = 0; n < 2000 && cursor < requests.size(); ++n) {
            Input in; in.requests[0] = requests[cursor]; if (cursor + 1 < requests.size()) in.requests[1] = requests[cursor + 1];
            const auto out = tick(in);
            for (unsigned lane = 0; lane < 2; ++lane) if (out.accepted[lane]) { tokens.push_back(out.tokens[lane]); ++cursor; }
        }
        check(cursor == requests.size(), "allocation timed out"); return tokens;
    }
    void drain() {
        for (unsigned n = 0; n < 4000 && (!live.empty() || !replies.empty() || !ptes.empty()); ++n) tick();
        check(live.empty() && replies.empty() && ptes.empty(), "pipeline failed to drain");
        for (unsigned n = 0; n < 12; ++n) tick();
        check(d.get_io$$idle(), "idle omitted accepted ownership");
    }
    void one(Request r) { submit({r}); drain(); }
    void csr(unsigned address, uint64_t value) { one(add(31, value)); one(system((address << 20) | (31 << 15) | (1 << 12) | 0x73, 31)); }
    void divideOperands() { one(add(25, 123456789)); one(add(26, 7)); }
    void configure() {
        csr(0x3b0, allPmp); csr(0x3a0, 0x1f); csr(0x180, satp); csr(0x300, (1ULL << 17) | (1ULL << 11));
        check(d.get_io$$vm$$satp() == satp && d.get_io$$vm$$dataPrivilege() == 1, "real CSR setup did not establish virtual S data access");
    }
    void warm() { const auto begin = cycle; one(load(1, va)); one(load(2, va + 4096)); coldCycles = cycle - begin; }
    void clearCounters() { caseStart = cycle; peak = physicalRequests = physicalResponses = precheckedStarts = serialStarts = serialBeforeProof = physicalHolds = queryHits = 0; firstPeek.clear(); }
    void wait(unsigned count) { for (unsigned n = 0; n < count; ++n) tick(); }
    void recover(Token token) {
        Input in; in.recover = true; in.boundary = token;
        bool accepted = false; for (unsigned n = 0; n < 100 && !accepted; ++n) accepted = tick(in).recovered;
        check(accepted, "recovery not accepted");
    }
    void report(const std::string &name) const {
        std::cout << "VIRTUAL_LOAD_CASE name=" << name << " trace=" << trace << " retired=" << retired << " physical=" << physicalRequests
            << " cycles=" << cycle - caseStart << " cold_cycles=" << coldCycles << " serial_before_proof=" << serialBeforeProof << " peak=" << peak << " prechecked=" << precheckedStarts << " serial=" << serialStarts << " traps=" << trapCount
            << " holds=" << physicalHolds << " cancellations=" << cancellations << " reuse=" << reuse << " cancelled_slot_reuse=" << cancelledSlotReuse << std::endl;
    }
};
int main(int argc, char **argv) { try {
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject-result";
    { Bench b; b.inject = inject; b.configure(); b.warm(); b.divideOperands(); b.clearCounters();
      b.holdReplyUntil = b.cycle + 100; b.submit({divide(), load(3, va + 8), load(4, va + 4096 + 16)}); b.drain();
      b.check(b.physicalRequests == 2 && b.peak == (PRECHECK_ENABLED ? 2U : 1U), "two warm virtual RAM loads did not establish expected physical overlap");
      b.check(b.precheckedStarts == (PRECHECK_ENABLED ? 2U : 0U), "warm loads did not use the certified path"); b.report("warm_overlap"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters(); b.one(load(3, va + 8));
      b.check(b.physicalRequests == 1 && b.serialStarts == 1 && b.precheckedStarts == 0,
          "unprepared head load did not use original serial translation"); b.report("head_serial_single"); }
    { Bench b; b.configure(); b.clearCounters(); b.one(load(3, va + 8));
      b.check(b.physicalRequests == 1 && b.serialStarts == 1 && b.precheckedStarts == 0,
          "cold head load waited for or used an optional certificate"); b.report("cold_head_serial_single"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters();
      b.holdPhysicalUntil = b.cycle + 100; b.submit({load(3, va + 8)}); b.wait(20);
      b.check(b.serialStarts == 1 && b.precheckedStarts == 0 && b.physicalRequests == 0 &&
          (!PRECHECK_ENABLED || (b.queryHits > 0 && b.serialBeforeProof == 1)),
          "head serial owner was not held across late certificate arrival");
      b.drain(); std::vector<Request> reuseProgram;
      for (unsigned n = 0; n < 32; ++n) reuseProgram.push_back(add(3 + n % 20, 0x200 + n));
      b.submit(reuseProgram); b.drain(); b.one(load(3, va + 8));
      b.check(b.reuse > 0 && b.precheckedStarts == 0, "late head certificate escaped through owner reuse");
      b.report("head_serial_held_proof"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters(); b.holdPhysicalUntil = b.cycle + 65;
      b.submit({load(3, va + 8), load(4, va + 4096 + 16)}); b.wait(35); b.commitEnable = false; b.wait(70);
      b.commitEnable = true; b.drain(); b.check(b.physicalHolds > 0, "request backpressure not exercised"); b.report("backpressure"); }
    { Bench b; b.configure(); b.warm(); b.clearCounters();
      auto dependentAddress = load(11, va + 4096 + 8); dependentAddress.rs1 = 10;
      dependentAddress.immediate = dependentAddress.virtualAddress - readValue(ram + 8);
      b.submit({load(10, va + 8), dependentAddress, load(12, va + 32)}); b.drain();
      b.check(b.physicalRequests == 3, "uncanonical older load lost demand ownership"); b.report("older_uncanonical_load"); }
    { Bench b; b.configure(); b.warm(); b.one(load(5, va + 2 * 4096)); b.one(add(30, 0x1122334455667788ULL)); b.clearCounters();
      b.submit({store(va), load(6, va + 2 * 4096)}); b.drain(); b.report("physical_alias_store_order"); }
    for (unsigned page : {3U, 4U, 7U}) {
      Bench b; b.configure(); b.one(load(1, va + page * 4096)); b.warm(); b.clearCounters();
      b.submit({load(3, va + 8), load(4, va + page * 4096), load(5, va + 4096 + 16)}); b.drain();
      b.report("serial_page_" + std::to_string(page));
    }
    { Bench b; b.configure(); b.warm(); b.divideOperands(); b.clearCounters();
      Request branch = add(0, 32); branch.branch = true; branch.writes = false; branch.rs1 = branch.rs2 = 3;
      branch.instruction = 0x02318063;
      b.holdReplyUntil = b.cycle + 150; b.secondLatency = 400;
      b.submit({divide(), load(3, va + 8), branch, load(4, va + 4096 + 16)});
      for (unsigned n = 0; n < 400 && !b.redirects; ++n) b.tick();
      b.check(b.redirects == 1, "real mispredicted branch did not cancel younger load");
      b.wait(12);
      std::vector<Request> reuseProgram;
      for (unsigned n = 0; n < 32; ++n) reuseProgram.push_back(add(3 + n % 20, 0x100 + n));
      b.submit(reuseProgram);
      if (PRECHECK_ENABLED) b.check(b.physicalResponses < b.physicalRequests && b.cancelledSlotReuse > 0,
          "ROB token was not reused while cancelled physical response remained in flight");
      b.drain(); b.secondLatency = 0;
      b.one(load(3, va + 24));
      b.check(b.cancellations == 1 && b.reuse > 0, "cancellation/token generation reuse not exercised"); b.report("cancel_token_reuse"); }
    { Bench b; b.configure(); b.warm(); const auto oldEpoch = b.cycle; (void)oldEpoch;
      b.one(system(0x12000073)); b.tables.pages[0].physical = ram + 24576;
      b.one(load(7, va)); b.one(load(8, va + 8)); b.report("sfence_remap"); }
    { Bench b; b.configure(); b.warm(); b.one(add(31, 0x18)); b.clearCounters();
      auto denied = load(5, va + 4096 + 8); denied.fault = true; denied.expectedCause = 5;
      const auto revoke = system((0x3a0 << 20) | (31 << 15) | (1 << 12) | 0x73, 31);
      b.submit({load(4, va + 8), revoke, denied}); b.drain();
      b.check(b.trapCount == 0 && b.cancellations == 1,
          "PMP permission change did not flush the younger pre-revocation instruction");
      b.one(denied);
      b.check(b.trapCount == 1 && b.physicalRequests == 1,
          "PMP CSR failed to drain older load or revoked younger proof escaped"); b.report("csr_epoch_drain"); }
    for (unsigned kind = 0; kind < 5; ++kind) {
      Bench b; b.configure(); b.warm(); auto r = load(3, kind == 0 ? va + 9 * 4096 : va + 8);
      r.fault = true; r.expectedCause = kind == 0 ? 13 : kind == 3 ? 4 : 5; r.physicalError = kind == 2 || kind == 4;
      if (kind == 1) b.csr(0x3a0, 0x18);
      if (kind == 2) b.divideOperands();
      if (kind == 3) r.immediate = r.virtualAddress = va + 3;
      b.clearCounters(); if (kind == 2) { b.submit({divide(), r}); b.drain(); } else b.one(r);
      if (kind == 2) b.check(b.precheckedStarts == (PRECHECK_ENABLED ? 1U : 0U),
          "speculative downstream-error certificate path was not exercised");
      if (kind == 4) b.check(b.serialStarts == 1 && b.precheckedStarts == 0,
          "head-serial physical-error path was not exercised");
      b.check(b.trapCount == 1 && b.physicalRequests == ((kind == 2 || kind == 4) ? 1U : 0U), "fault generated unauthorized data traffic");
      b.report("fault_" + std::to_string(kind));
    }
    std::cout << "VIRTUAL_LOAD_CONCURRENCY_PASS enabled=" << PRECHECK_ENABLED << "\n"; return 0;
} catch (const std::exception &e) { std::cerr << "VIRTUAL_LOAD_CONCURRENCY_FAIL " << e.what() << "\n"; return 1; } }
