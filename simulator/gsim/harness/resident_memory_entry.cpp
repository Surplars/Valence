#include "ResidentMemoryEntryGsim.h"
#include <array>
#include <cstdint>
#include <compare>
#include <deque>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <new>

// This host is independent of the hardware decoder and resident selector.
// Full load data is checked at LSU start AND external request, even though the
// ISA ignores request.data for ordinary loads. OFF malformed loads retain rs2.
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    auto operator<=>(const Token &) const = default;
};
static uint64_t sext(uint64_t v, unsigned bits) {
    return uint64_t(int64_t(v << (64 - bits)) >> (64 - bits));
}
static uint32_t addi(unsigned rd, unsigned rs, int imm) {
    return (uint32_t(imm) & 4095) << 20 | rs << 15 | rd << 7 | 0x13;
}
static uint32_t load(unsigned rd, unsigned rs, int imm, unsigned funct3) {
    return (uint32_t(imm) & 4095) << 20 | rs << 15 | funct3 << 12 | rd << 7 | 3;
}
static uint8_t byteAt(uint64_t address) { return uint8_t((address * 73 + (address >> 3) * 19) ^ 0xa7); }
static uint64_t bytesAt(uint64_t address, unsigned size) {
    uint64_t value = 0;
    for (unsigned i = 0; i < (1u << size); ++i) value |= uint64_t(byteAt(address + i)) << (8 * i);
    return value;
}
struct Instruction {
    uint32_t raw = 0x13, expanded = 0x13;
    uint64_t pc = 0;
    bool bad = false;
};
struct Entry {
    Instruction inst;
    unsigned rd = 0, size = 0;
    bool memory = false, unsign = false, started = false, requested = false;
    uint64_t address = 0, data = 0, expected = 0;
};
struct Reply { uint64_t due, data, handle; };
using Offer = std::array<std::optional<Instruction>, 2>;
using RequestTuple = std::tuple<uint64_t, uint64_t, uint64_t, unsigned, unsigned,
    bool, bool, unsigned, bool, bool, uint64_t, bool, bool>;
struct Bench {
    alignas(SResidentMemoryEntryGsim) unsigned char dutStorage[sizeof(SResidentMemoryEntryGsim)]{};
    SResidentMemoryEntryGsim &dut;
    std::array<uint64_t, 32> predicted{}, architectural{};
    std::map<Token, Entry> entries;
    std::deque<Token> live, pendingRequests;
    std::deque<Reply> replies;
    std::optional<RequestTuple> held;
    std::ofstream trace;
    uint64_t cycle = 0, nextPc = 0x1000;
    unsigned accepted = 0, retired = 0, starts = 0, requests = 0, compressedCount = 0;
    unsigned requestHolds = 0, unacceptedBad = 0, badAccepted = 0;
    std::array<std::array<unsigned, 7>, 2> coverage{};
    bool commitEnable = true;
    explicit Bench(const char *tracePath)
        : dut(*::new (static_cast<void *>(dutStorage)) SResidentMemoryEntryGsim()) {
        dut.LOG_START = 1;
        dut.activateAll();
        if (tracePath) { trace.open(tracePath); check(bool(trace), "cannot open trace"); }
        tick({}, true); tick({}, true); tick(); tick();
    }
    ~Bench() { dut.~SResidentMemoryEntryGsim(); }
    Bench(const Bench &) = delete;
    Bench &operator=(const Bench &) = delete;
    void check(bool ok, const std::string &why) const {
        if (!ok) throw std::runtime_error("cycle=" + std::to_string(cycle) + " " + why);
    }
    Instruction make(uint32_t raw, uint32_t expanded = 0, bool bad = false) {
        Instruction result{raw, expanded ? expanded : raw, nextPc, bad};
        nextPc += (raw & 3) == 3 ? 4 : 2;
        return result;
    }
    Entry interpret(Instruction inst) {
        Entry e; e.inst = inst;
        const auto w = inst.expanded;
        const unsigned op = w & 127, f = (w >> 12) & 7, rs1 = (w >> 15) & 31;
        e.rd = (w >> 7) & 31;
        if (op == 0x13 && f == 0) e.expected = predicted[rs1] + sext(w >> 20, 12);
        else if (op == 3 && f < 7) {
            e.memory = true; e.size = f & 3; e.unsign = f & 4;
            e.address = predicted[rs1] + sext(w >> 20, 12);
            e.data = inst.bad ? predicted[5] : 0;
            check((e.address & ((1u << e.size) - 1)) == 0, "test offered a misaligned load");
            e.expected = bytesAt(e.address, e.size);
            if (!e.unsign && e.size < 3) e.expected = sext(e.expected, 8u << e.size);
        } else throw std::runtime_error("host lacks independent instruction interpretation");
        if (e.rd) predicted[e.rd] = e.expected;
        return e;
    }
    std::array<bool, 2> tick(Offer offered = {}, bool reset = false) {
        dut.set_reset(reset);
#define INPUT(N) \
        dut.set_io$$instruction##N##$$valid(offered[N].has_value()); \
        dut.set_io$$instruction##N##$$bits(offered[N] ? offered[N]->raw : 0x13); \
        dut.set_io$$pc##N(offered[N] ? offered[N]->pc : 0); \
        dut.set_io$$badSource2##N(offered[N] && offered[N]->bad)
        INPUT(0); INPUT(1);
#undef INPUT
        dut.set_io$$commitEnable(commitEnable);
        dut.set_io$$inspectRegister(cycle % 32);
        // External laws depend only on cycle and accepted requests, never reuse decisions.
        const bool ready = cycle % 7 != 2 && cycle % 7 != 3;
        const bool response = !replies.empty() && replies.front().due <= cycle;
        dut.set_io$$memory$$request$$ready(ready);
        dut.set_io$$memory$$response$$valid(response);
        dut.set_io$$memory$$response$$bits$$data(response ? replies.front().data : 0);
        dut.set_io$$memory$$response$$bits$$returnHandle(response ? replies.front().handle : 0);
        dut.set_io$$memory$$response$$bits$$error(false);
        dut.set_io$$memory$$response$$bits$$pageFault(false);
        dut.step();
        if (reset) { dut.resetAll(); ++cycle; return {}; }
        check(!dut.get_io$$headException$$valid() && !dut.get_io$$trap$$valid() &&
            !dut.get_io$$redirect$$valid(), "unexpected exception/trap/redirect");
        check(dut.get_io$$committedValue() == architectural[cycle % 32], "architectural inspection mismatch");
        std::array<bool, 2> result{};
#define ACCEPT(N) \
        result[N] = dut.get_io$$renamed##N##$$valid(); \
        if (result[N]) { \
            check(offered[N].has_value(), "accepted without offer"); \
            const auto inst = *offered[N]; \
            const unsigned f = (inst.expanded >> 12) & 7; \
            const Token token{unsigned(dut.get_io$$renamed##N##$$bits$$token$$index()), \
                uint64_t(dut.get_io$$renamed##N##$$bits$$token$$tag())}; \
            Entry e = interpret(inst); \
            check(!entries.count(token), "reused a full token"); \
            check(dut.get_io$$legal##N(), "real expansion/decode illegal"); \
            check(dut.get_io$$decoded##N##$$expandedInstruction() == inst.expanded, "compressed expansion mismatch"); \
            check(bool(dut.get_io$$compressed##N()) == ((inst.raw & 3) != 3), "compressed classification mismatch"); \
            check(dut.get_io$$offered##N##$$rename$$instruction() == inst.raw, "raw retirement instruction lost"); \
            if (e.memory) { \
                check(dut.get_io$$decoded##N##$$memory() && !dut.get_io$$decoded##N##$$store() && \
                    !dut.get_io$$decoded##N##$$atomic(), "decoder load class mismatch"); \
                check(dut.get_io$$decoded##N##$$rename$$rs2() == 0, "real decoder left immediate bits as rs2"); \
                check(dut.get_io$$decoded##N##$$rename$$rs1() == ((inst.expanded >> 15) & 31), "decoder rs1 mismatch"); \
                check(dut.get_io$$decoded##N##$$immediate() == sext(inst.expanded >> 20, 12), "load immediate mismatch"); \
                check(dut.get_io$$decoded##N##$$memorySize() == e.size && \
                    bool(dut.get_io$$decoded##N##$$memoryUnsigned()) == e.unsign, "load width/sign mismatch"); \
                check(dut.get_io$$offered##N##$$rename$$rs2() == (inst.bad ? 5 : 0), "malformed offer not exposed"); \
                check(inst.bad ? dut.get_io$$renamed##N##$$bits$$source2() != 0 : \
                    dut.get_io$$renamed##N##$$bits$$source2() == 0, "accepted physical source2 mismatch"); \
                if (inst.bad) ++badAccepted; else ++coverage[N][f]; \
                if ((inst.raw & 3) != 3) ++compressedCount; \
            } \
            entries.emplace(token, e); live.push_back(token); ++accepted; \
            if (trace) trace << "accept " << cycle << ' ' << N << ' ' << token.index << ' ' << token.tag \
                << ' ' << inst.raw << ' ' << inst.expanded << ' ' << e.address << ' ' << e.data << '\n'; \
        } else if (offered[N] && offered[N]->bad) ++unacceptedBad
        ACCEPT(0); ACCEPT(1);
#undef ACCEPT
        if (dut.get_io$$lsuOffer()) {
            const Token t{unsigned(dut.get_io$$lsu$$token$$index()), uint64_t(dut.get_io$$lsu$$token$$tag())};
            check(entries.count(t), "LSU offer has no accepted full-token owner");
            auto &e = entries.at(t);
            check(e.memory && !e.started, "nonmemory or duplicate LSU offer");
            check(dut.get_io$$lsu$$pc() == e.inst.pc && dut.get_io$$lsu$$address() == e.address &&
                dut.get_io$$lsu$$data() == e.data && dut.get_io$$lsu$$size() == e.size &&
                bool(dut.get_io$$lsu$$unsigned()) == e.unsign && !dut.get_io$$lsu$$store() &&
                !dut.get_io$$lsu$$atomic() && dut.get_io$$lsu$$atomicOp() == 0 &&
                !dut.get_io$$lsu$$accessDenied() && !dut.get_io$$lsu$$virtualized() &&
                !dut.get_io$$lsu$$precheckedLoad(), "full LSU load payload differs from independent oracle");
            if (dut.get_io$$lsuFire()) {
                e.started = true; ++starts;
                if (trace) trace << "start " << cycle << ' ' << t.index << ' ' << t.tag << ' '
                    << e.address << ' ' << e.data << ' ' << e.size << '\n';
            }
        }
        if (dut.get_io$$lsuRequestFire()) {
            check(dut.get_io$$lsuRequestOwner$$valid(), "LSU request lacks owner");
            Token t{unsigned(dut.get_io$$lsuRequestOwner$$bits$$index()),
                uint64_t(dut.get_io$$lsuRequestOwner$$bits$$tag())};
            check(entries.count(t) && entries.at(t).started, "request owner lacks accepted start");
            pendingRequests.push_back(t);
        }
        if (response && dut.get_io$$memory$$response$$ready()) replies.pop_front();
        if (dut.get_io$$memory$$request$$valid()) {
#define R(F) dut.get_io$$memory$$request$$bits$$##F()
            RequestTuple now{R(address), R(data), R(returnHandle), unsigned(R(size)), unsigned(R(mask)),
                bool(R(write)), bool(R(atomic)), unsigned(R(atomicOp)), bool(R(virtualized)),
                bool(R(precheckedLoad)), R(translationEpoch), bool(R(prefetchNextAllowed)), bool(R(uncached))};
            if (held) check(now == *held, "held request full tuple changed");
            held = ready ? std::nullopt : std::optional<RequestTuple>{now};
            if (!ready) ++requestHolds;
            check(!pendingRequests.empty(), "external request has no accepted LSU owner");
            const Token t = pendingRequests.front();
            auto &e = entries.at(t);
            const unsigned mask = ((1u << (1u << e.size)) - 1) << (e.address & 7);
            check(R(address) == e.address && R(data) == (e.data << ((e.address & 7) * 8)) &&
                R(size) == e.size && R(mask) == mask && !R(write) && !R(atomic) && R(atomicOp) == 0 &&
                !R(virtualized) && !R(precheckedLoad) && R(translationEpoch) == 0 &&
                !R(prefetchNextAllowed) && !R(uncached), "full external load request tuple mismatch");
            if (ready) {
                check(!e.requested, "duplicate memory request"); e.requested = true;
                pendingRequests.pop_front(); ++requests;
                replies.push_back({cycle + 4, bytesAt(e.address & ~uint64_t(7), 3), uint64_t(R(returnHandle))});
                if (trace) trace << "request " << cycle << ' ' << t.index << ' ' << t.tag << ' '
                    << R(address) << ' ' << R(data) << ' ' << R(returnHandle) << ' ' << R(size) << ' ' << R(mask)
                    << ' ' << R(write) << ' ' << R(atomic) << ' ' << R(atomicOp) << ' ' << R(virtualized)
                    << ' ' << R(precheckedLoad) << ' ' << R(translationEpoch) << ' ' << R(prefetchNextAllowed)
                    << ' ' << R(uncached) << '\n';
            }
#undef R
        } else check(!held, "stalled request withdrawn");
#define COMMIT(N) \
        if (dut.get_io$$commit##N##$$valid()) { \
            const Token t{unsigned(dut.get_io$$commit##N##$$bits$$token$$index()), \
                uint64_t(dut.get_io$$commit##N##$$bits$$token$$tag())}; \
            check(!live.empty() && live.front() == t, "retirement order/full-token mismatch"); \
            auto &e = entries.at(t); \
            check(dut.get_io$$commit##N##$$bits$$pc() == e.inst.pc && \
                dut.get_io$$commit##N##$$bits$$instruction() == e.inst.raw && \
                dut.get_io$$commit##N##$$bits$$rd() == e.rd && \
                dut.get_io$$commit##N##$$bits$$data() == e.expected, "retirement tuple mismatch"); \
            check(!e.memory || (e.started && e.requested), "load retired without start/request"); \
            if (e.rd) architectural[e.rd] = e.expected; \
            if (trace) trace << "commit " << cycle << ' ' << N << ' ' << t.index << ' ' << t.tag \
                << ' ' << e.inst.pc << ' ' << e.inst.raw << ' ' << e.rd << ' ' << e.expected << '\n'; \
            live.pop_front(); ++retired; \
        }
        COMMIT(0); COMMIT(1);
#undef COMMIT
        ++cycle;
        return result;
    }
    void submit(Instruction a, Instruction b) {
        Offer pending{a, b};
        for (unsigned tries = 0; pending[0] || pending[1]; ++tries) {
            check(tries < 128, "rename acceptance timeout");
            const auto acceptedNow = tick(pending);
            for (unsigned lane = 0; lane < 2; ++lane) if (acceptedNow[lane]) pending[lane].reset();
            // Rename consumes prefixes. Shift a lone unaccepted second lane only
            // for general setup; coverage cases must accept both immediately.
            if (!pending[0] && pending[1]) { pending[0] = pending[1]; pending[1].reset(); }
        }
    }
    void drain() {
        for (unsigned i = 0; i < 256; ++i) {
            tick();
            if (live.empty() && replies.empty() && pendingRequests.empty() && !dut.get_io$$memoryBusy()) return;
        }
        throw std::runtime_error("backend drain timeout");
    }
    void setup() {
        submit(make(addi(1, 0, 0x400)), make(addi(2, 0, 0x600))); drain();
        submit(make(addi(8, 0, 0x700)), make(addi(5, 0, 0x5a5))); drain();
    }
    void requirePair(Instruction a, Instruction b) {
        const auto acceptedNow = tick({a, b});
        check(acceptedNow[0] && acceptedNow[1], "coverage packet not accepted in its original two lanes");
        drain();
    }
    void positive() {
        setup();
        for (unsigned f = 0; f < 7; ++f) {
            const unsigned size = f & 3;
            for (int offset = 1; offset < 32; ++offset) if ((offset & ((1 << size) - 1)) == 0) {
                requirePair(make(load(10, 1, offset, f)), make(load(11, 2, offset, f)));
                requirePair(make(load(10, 1, offset - 32, f)), make(load(11, 2, offset - 32, f)));
            }
        }
        // Independent C encodings. Each case reaches production Compressed.expand
        // and preserves its original 16-bit instruction through retirement.
        for (unsigned kind = 0; kind < 4; ++kind) {
            const unsigned size = kind & 1 ? 3 : 2;
            const unsigned offset = kind & 1 ? 8 : 4;
            const unsigned base = kind < 2 ? 8 : 2;
            auto compressed = [&](unsigned rd) {
                uint32_t raw;
                if (kind < 2) {
                    raw = (size == 2 ? 2u : 3u) << 13 | (rd - 8) << 2;
                    raw |= size == 2 ? 1u << 6 : 1u << 10;
                } else {
                    raw = (size == 2 ? 2u : 3u) << 13 | rd << 7 | 2;
                    raw |= size == 2 ? 1u << 4 : 1u << 5;
                }
                return make(raw, load(rd, base, offset, size));
            };
            requirePair(compressed(10), compressed(11));
        }
        for (unsigned lane = 0; lane < 2; ++lane) for (unsigned f = 0; f < 7; ++f)
            check(coverage[lane][f] > 0, "missing legal funct3/lane coverage");
        check(compressedCount == 8 && requests == starts && requestHolds > 0 && accepted == retired,
            "positive coverage or complete-drain counters failed");
    }
    void rejectedOffers() {
        setup(); commitEnable = false;
        for (unsigned packet = 0; packet < 8; ++packet) {
            const auto a = tick({make(addi(0, 0, 0)), make(addi(0, 0, 0))});
            check(a[0] && a[1], "ROB-fill packet was not accepted");
        }
        for (unsigned cycle = 0; cycle < 8; ++cycle) {
            const auto a = tick({make(load(10, 1, 8, 3), 0, true), make(load(11, 2, 8, 3), 0, true)});
            check(!a[0] && !a[1] && dut.get_io$$occupancy() == 16,
                "malformed offer unexpectedly accepted by full ROB");
        }
        check(unacceptedBad == 16 && badAccepted == 0, "unaccepted negative coverage missing");
        commitEnable = true; drain();
        requirePair(make(load(10, 1, 8, 3)), make(load(11, 2, 8, 3)));
    }
    void acceptedBad(unsigned lane) {
        setup();
        std::cerr << "P2 presenting accepted noncanonical ordinary-load source2 on lane " << lane << '\n';
        const auto good = make(addi(0, 0, 0));
        const auto bad = make(load(10, 1, 8, 3), 0, true);
        const auto a = lane == 0 ? tick({bad, good}) : tick({good, bad});
        check(a[0] && a[1] && badAccepted == 1, "malformed load was not accepted in target lane");
        drain();
        check(requests == 1 && starts == 1, "OFF malformed legacy load did not execute");
    }
};
int main(int argc, char **argv) {
    try {
        const std::string mode = argc > 1 ? argv[1] : "positive";
        Bench bench(argc > 2 ? argv[2] : nullptr);
        if (mode == "positive") bench.positive();
        else if (mode == "unaccepted") bench.rejectedOffers();
        else if (mode == "accepted-bad0" || mode == "accepted-bad1") bench.acceptedBad(mode.back() - '0');
        else throw std::runtime_error("mode must be positive|unaccepted|accepted-bad0|accepted-bad1");
        std::cout << "P2 " << mode << " completed cycles=" << bench.cycle << " accepted=" << bench.accepted
            << " retired=" << bench.retired << " starts=" << bench.starts << " requests=" << bench.requests
            << " compressed=" << bench.compressedCount << " held=" << bench.requestHolds
            << " unaccepted_bad=" << bench.unacceptedBad << " accepted_bad=" << bench.badAccepted << '\n';
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "P2 HOST FAILURE: " << e.what() << '\n';
        return 1;
    }
}
