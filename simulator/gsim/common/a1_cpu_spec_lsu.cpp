#include "CommonA1CpuSpecLsuGsim.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>

#ifndef A1_MEMORY_OWNER_SLOTS
#error "Set A1_MEMORY_OWNER_SLOTS to the emitted model's owner count"
#endif
static constexpr unsigned slots = A1_MEMORY_OWNER_SLOTS;
static_assert(slots == 2 || slots == 4);
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &b) const { return index == b.index && tag == b.tag; }
};
struct Operation {
    Token token;
    uint64_t address = 0x80200000, data = 0x123456789abcdef0ULL;
    bool store = false, parallel = true, error = false, pageFault = false;
};
struct Owner {
    Operation op;
    bool request = false, response = false, completion = false, cancelled = false;
};
struct Reply { Token token; uint64_t data; bool error, pageFault; };
// Independent memory contents, unrelated to DUT payload or completion values.
static uint64_t memoryWord(uint64_t address) { return 0xd3a52b718e49c6f0ULL ^ (address * 0x10101ULL); }
static Operation load(unsigned index, uint64_t tag) {
    Operation op; op.token = {index, tag}; op.address += index * 8; return op;
}

class Bench {
    SCommonA1CpuSpecLsuGsim d;
    std::vector<Owner> owners;
    std::deque<Reply> replies;
    using Payload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool>;
    std::optional<Payload> held;
    std::optional<Token> heldOwner;
    Owner &owner(Token token) {
        for (auto &o : owners) if (o.op.token == token) return o;
        throw std::runtime_error("DUT invented a full owner token");
    }
    void drive(std::optional<Operation> op) {
        const auto a = op.value_or(Operation{});
        d.set_io$$startValid(op.has_value());
        d.set_io$$token$$index(a.token.index); d.set_io$$token$$tag(a.token.tag);
        d.set_io$$address(a.address); d.set_io$$data(a.data); d.set_io$$store(a.store);
        d.set_io$$parallel(a.parallel);
        const auto c = cancel.value_or(Token{});
        d.set_io$$cancelOwner$$valid(cancel.has_value());
        d.set_io$$cancelOwner$$bits$$index(c.index); d.set_io$$cancelOwner$$bits$$tag(c.tag);
        d.set_io$$memory$$request$$ready(memoryReady);
        const bool response = allowReplies && !replies.empty();
        d.set_io$$memory$$response$$valid(response);
        d.set_io$$memory$$response$$bits$$data(response ? replies.front().data : 0);
        d.set_io$$memory$$response$$bits$$error(response && replies.front().error);
        d.set_io$$memory$$response$$bits$$pageFault(response && replies.front().pageFault);
        d.set_io$$complete$$ready(completeReady);
    }
public:
    bool memoryReady = true, completeReady = true, allowReplies = false, inject = false;
    std::optional<Token> cancel;
    unsigned starts = 0, requests = 0, responses = 0, completions = 0, discards = 0, holds = 0;
    unsigned offered = 0;
    Bench() { drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); tick(); }
    bool tick(std::optional<Operation> op = {}) {
        // GSIM step evaluates this cycle's inputs/outputs; commit software handshakes after step.
        const bool response = allowReplies && !replies.empty();
        drive(op); d.step();
        if (cancel) {
            auto &o = owner(*cancel);
            check(o.request && !o.response && !o.op.store, "cancel stimulus must target pending accepted read");
            o.cancelled = true;
        }
        const bool take = op && d.get_io$$startReady();
        if (take) {
            for (const auto &o : owners) check(!(o.op.token == op->token), "driver reused full token");
            owners.push_back({*op}); ++starts;
        }
        const bool valid = d.get_io$$memory$$request$$valid();
        if (held) check(valid, "held request withdrew valid");
        if (valid) {
            const Payload payload{d.get_io$$memory$$request$$bits$$address(),
                d.get_io$$memory$$request$$bits$$data(), unsigned(d.get_io$$memory$$request$$bits$$size()),
                unsigned(d.get_io$$memory$$request$$bits$$mask()), bool(d.get_io$$memory$$request$$bits$$write())};
            check(d.get_io$$requestOwner$$valid(), "memory offer lacks owner");
            const Token token{unsigned(d.get_io$$requestOwner$$bits$$index()), d.get_io$$requestOwner$$bits$$tag()};
            if (held) check(payload == *held && token == *heldOwner, "held request payload/full owner changed");
            held = memoryReady ? std::nullopt : std::optional<Payload>(payload);
            heldOwner = memoryReady ? std::nullopt : std::optional<Token>(token);
            holds += !memoryReady;
            auto &o = owner(token); const auto &a = o.op;
            check(std::get<0>(payload) == (a.address ^ (inject ? 8ULL : 0ULL)) &&
                std::get<1>(payload) == a.data && std::get<2>(payload) == 3 &&
                std::get<3>(payload) == 255 && std::get<4>(payload) == a.store,
                "request differs from independently accepted operation");
            check(!d.get_io$$memory$$request$$bits$$atomic() &&
                !d.get_io$$memory$$request$$bits$$atomicOp() &&
                !d.get_io$$memory$$request$$bits$$virtualized() &&
                !d.get_io$$memory$$request$$bits$$precheckedLoad() &&
                !d.get_io$$memory$$request$$bits$$translationEpoch() &&
                !d.get_io$$memory$$request$$bits$$uncached() &&
                !d.get_io$$memory$$request$$bits$$prefetchNextAllowed(), "unexpected request attributes");
            if (memoryReady) {
                check(!o.request, "duplicate memory request"); o.request = true; ++requests;
                replies.push_back({token, memoryWord(a.address), a.error, a.pageFault});
            }
        }
        if (response && d.get_io$$memory$$response$$ready()) {
            auto &o = owner(replies.front().token);
            check(o.request && !o.response, "ordered response lost original owner");
            o.response = true; replies.pop_front(); ++responses;
        }
        if (d.get_io$$complete$$valid()) {
            ++offered;
            const Token token{unsigned(d.get_io$$complete$$bits$$token$$index()), d.get_io$$complete$$bits$$token$$tag()};
            auto &o = owner(token); const auto &a = o.op;
            check(o.response && !o.completion && !o.cancelled, "premature/duplicate/cancelled completion");
            check(d.get_io$$complete$$bits$$data() == (a.store ? 0 : memoryWord(a.address)) &&
                bool(d.get_io$$complete$$bits$$exception()) == (a.error || a.pageFault) &&
                d.get_io$$complete$$bits$$tval() == a.address && d.get_io$$complete$$bits$$nextPc() == 0x1004,
                "completion data or precise fault metadata mismatch");
            if (a.error || a.pageFault)
                check(d.get_io$$complete$$bits$$cause() == (a.pageFault ? (a.store ? 15 : 13) : (a.store ? 7 : 5)),
                    "precise architectural cause mismatch");
            // Decoupled arbitration is not irrevocable: validate each offered owner, not a fabricated lock contract.
            if (completeReady) { o.completion = true; ++completions; }
        }
        discards += d.get_io$$discarded();
        return take;
    }
    void accept(Operation op) {
        for (unsigned n = 0; n < 100; ++n) if (tick(op)) return;
        throw std::runtime_error("start acceptance timeout");
    }
    void reject(Operation op) { for (unsigned n = 0; n < 4; ++n) check(!tick(op), "full/serial admission escaped"); }
    void idle(unsigned cycles = 12) { for (unsigned n = 0; n < cycles; ++n) tick(); }
    void drain() {
        memoryReady = completeReady = allowReplies = true; cancel.reset();
        for (unsigned n = 0; n < 200; ++n) { tick(); if (!d.get_io$$busy() && replies.empty()) break; }
        tick();
        check(!d.get_io$$busy() && !d.get_io$$liveMask() && replies.empty() && !held, "owners failed to drain");
        check(requests == responses, "request/response conservation failure");
        for (const auto &o : owners)
            check(o.request && o.response && (o.completion != o.cancelled), "lost owner or cancelled completion");
    }
};

int main(int argc, char **argv) { try {
    const bool negative = argc == 2 && std::string(argv[1]) == "--inject-oracle-error";
    check(argc == 1 || negative, "usage: a1_cpu_spec_lsu [--inject-oracle-error]");
    {
        Bench b; b.inject = negative; b.memoryReady = false; b.completeReady = false;
        for (unsigned i = 0; i < slots; ++i) b.accept(load(i + 1, 0x100000000ULL + i));
        b.reject(load(10, 0x200000000ULL)); b.idle();
        check(b.starts == slots && !b.requests && b.holds, "capacity/backpressure setup not exercised");
        b.memoryReady = true; b.idle();
        check(b.requests == slots && !b.responses, "owner capacity did not reach memory");
        auto store = load(11, 0x300000000ULL); store.store = true; store.parallel = false;
        b.reject(store);
        b.allowReplies = true; b.idle(30);
        check(b.responses == slots && !b.completions && b.offered, "completion hold not exercised");
        b.reject(load(12, 0x400000000ULL)); b.drain();
        b.accept(store); b.drain();
    }
    {
        Bench b;
        auto old = load(3, 0x1234567800000001ULL); old.error = true;
        b.accept(old); b.idle(); check(b.requests == 1 && !b.responses, "delayed read setup failed");
        b.cancel = old.token; b.tick(); b.cancel.reset(); b.idle();
        // Same ROB index, different HIGH tag bits, while the stale response is still pending.
        auto fresh = load(3, 0x8765432100000001ULL); fresh.address += 0x100;
        b.accept(fresh); b.idle();
        check(b.requests == 2 && !b.responses && !b.completions, "reuse did not overlap delayed stale reply");
        b.drain(); check(b.completions == 1 && b.discards == 1, "stale error reply affected reused owner");
        // Reuse a physically released reservation after all old response obligations have drained.
        auto reused = load(3, 0x7654321000000001ULL); reused.address += 0x200;
        b.accept(reused); b.drain();
        check(b.completions == 2 && b.discards == 1, "drained reservation reuse lost new owner");
    }
    {
        Bench b;
        for (unsigned store = 0; store < 2; ++store) {
            for (unsigned page = 0; page < 2; ++page) {
                auto op = load(4 + store * 2 + page, 0xfedcba9800000000ULL + store * 2 + page);
                op.store = store; op.parallel = !store; op.error = !page; op.pageFault = page;
                b.accept(op); b.drain();
            }
        }
        // This wrapper has no device decoder. It checks serial admission only, not MMIO routing.
        auto serial = load(9, 0xabcdef0100000000ULL); serial.address = 0x10000000; serial.parallel = false;
        b.accept(serial); b.drain();
    }
    std::cout << "A1_CPU_SPEC_LSU_PASS owners=" << slots
              << " capacity held_request held_completion cancel_stale_fulltag precise_faults store_drain serial_load\n";
    return 0;
} catch (const std::exception &e) {
    std::cerr << "A1_CPU_SPEC_LSU_FAIL " << e.what() << '\n'; return 1;
} }
