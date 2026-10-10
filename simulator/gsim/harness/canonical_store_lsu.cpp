#include "CanonicalStoreLsuGsim.h"
#include "canonical_store_oracle.h"
#include <deque>
#include <iostream>
#include <optional>
#include <tuple>
#include <vector>
using namespace canonical_store_test;

struct Operation {
    Token token;
    uint64_t address = va, physical = ram, data = 0x123456789abcdef0ULL;
    unsigned size = 3;
    bool store = false, atomic = false, virt = true, prechecked = true;
    bool forward = false, parallel = true, origin = false, error = false;
};
struct Owner {
    Operation operation;
    bool request = false, response = false, completion = false, cancelled = false;
};
struct Reply { Token token; uint64_t due, data; bool error; };

class Bench {
    SCanonicalStoreLsuGsim d;
    std::vector<Owner> owners;
    std::deque<Reply> replies;
    using Payload = std::tuple<uint64_t, uint64_t, unsigned, unsigned, bool, bool, bool, bool,
        uint64_t, bool, unsigned, uint64_t, uint64_t>;
    std::optional<Payload> held;
    std::optional<Token> heldOwner;
public:
    uint64_t cycle = 0;
    uint32_t epoch = 9;
    bool memoryReady = true, completeReady = true, allowReplies = false;
    std::optional<Token> relaxed, cancel;
    std::optional<Token> lastResponse;
    unsigned starts = 0, requests = 0, responses = 0, completions = 0, discarded = 0, holds = 0;
    unsigned blockedBeforeAcceptance = 0, overlapStarts = 0;
    bool inject = false;
    Bench() {
        drive({}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); tick();
    }
    Owner &owner(Token token) {
        for (auto &item : owners) if (item.operation.token == token) return item;
        throw std::runtime_error("DUT invented an owner token");
    }
    void drive(std::optional<Operation> operation) {
        const auto op = operation.value_or(Operation{});
        d.set_io$$startValid(operation.has_value());
        d.set_io$$token$$index(op.token.index); d.set_io$$token$$tag(op.token.tag);
        d.set_io$$address(op.address); d.set_io$$physicalAddress(op.physical); d.set_io$$data(op.data);
        d.set_io$$size(op.size); d.set_io$$store(op.store); d.set_io$$atomic(op.atomic);
        d.set_io$$virtualized(op.virt); d.set_io$$prechecked(op.prechecked); d.set_io$$forwarded(op.forward);
        d.set_io$$parallel(op.parallel); d.set_io$$originValid(op.origin); d.set_io$$epoch(epoch);
        const auto r = relaxed.value_or(Token{}), c = cancel.value_or(Token{});
        d.set_io$$relaxOwner$$valid(relaxed.has_value());
        d.set_io$$relaxOwner$$bits$$index(r.index); d.set_io$$relaxOwner$$bits$$tag(r.tag);
        d.set_io$$cancelOwner$$valid(cancel.has_value());
        d.set_io$$cancelOwner$$bits$$index(c.index); d.set_io$$cancelOwner$$bits$$tag(c.tag);
        d.set_io$$memory$$request$$ready(memoryReady);
        const bool response = allowReplies && !replies.empty() && replies.front().due <= cycle;
        d.set_io$$memory$$response$$valid(response);
        d.set_io$$memory$$response$$bits$$data(response ? replies.front().data : 0);
        d.set_io$$memory$$response$$bits$$error(response && replies.front().error);
        d.set_io$$memory$$response$$bits$$pageFault(0);
        d.set_io$$complete$$ready(completeReady);
    }
    bool tick(std::optional<Operation> operation = {}) {
        const bool response = allowReplies && !replies.empty() && replies.front().due <= cycle;
        drive(operation); d.step(); lastResponse.reset();
        if (cancel) {
            auto &target = owner(*cancel);
            require(!target.operation.store && !target.operation.atomic, "driver tried cancelling irrevocable owner");
            target.cancelled = true;
        }
        const bool take = operation && d.get_io$$startReady();
        if (take) {
            for (const auto &o : owners) require(o.operation.token != operation->token, "driver reused a full token");
            if (operation->prechecked) {
                for (const auto &o : owners) if (o.operation.store && !o.response) {
                    require(o.request && relaxed && *relaxed == o.operation.token && o.operation.origin,
                        "younger load preceded registered actual store request ownership");
                    ++overlapStarts;
                }
            }
            owners.push_back({*operation}); ++starts;
        }
        const bool valid = d.get_io$$memory$$request$$valid();
        if (held) require(valid, "held/cancelled LSU request withdrew valid");
        if (valid) {
            // Only initialized valid payloads are sampled, including a replacement start/request.
            const bool origin = d.get_io$$origin$$valid();
            unsigned originIndex = 0;
            uint64_t originTag = 0, originEpoch = 0;
            if (origin) {
                originIndex = unsigned(d.get_io$$origin$$bits$$token$$index());
                originTag = d.get_io$$origin$$bits$$token$$tag();
                originEpoch = d.get_io$$origin$$bits$$epoch();
            }
            const Payload payload{d.get_io$$memory$$request$$bits$$address(),
                d.get_io$$memory$$request$$bits$$data(), unsigned(d.get_io$$memory$$request$$bits$$size()),
                unsigned(d.get_io$$memory$$request$$bits$$mask()), bool(d.get_io$$memory$$request$$bits$$write()),
                bool(d.get_io$$memory$$request$$bits$$atomic()), bool(d.get_io$$memory$$request$$bits$$virtualized()),
                bool(d.get_io$$memory$$request$$bits$$precheckedLoad()),
                d.get_io$$memory$$request$$bits$$translationEpoch(), origin, originIndex, originTag, originEpoch};
            if (held) require(payload == *held, "held/cancelled LSU request or exact origin changed");
            held = !memoryReady ? std::optional<Payload>{payload} : std::nullopt;
            holds += !memoryReady;
            require(d.get_io$$requestOwner$$valid(), "request lacks exact arbiter owner");
            const Token token{unsigned(d.get_io$$requestOwner$$bits$$index()),
                uint64_t(d.get_io$$requestOwner$$bits$$tag())};
            if (heldOwner) require(token == *heldOwner, "held arbiter owner changed despite equal request payload");
            heldOwner = !memoryReady ? std::optional<Token>{token} : std::nullopt;
            auto &o = owner(token); const auto &op = o.operation;
            const uint64_t address = op.prechecked ? op.physical : op.address;
            const uint64_t data = op.atomic ? op.data : op.data << ((op.address % 8) * 8);
            require(std::get<0>(payload) == (address ^ (inject ? 8ULL : 0ULL)) && std::get<1>(payload) == data &&
                std::get<2>(payload) == op.size && std::get<3>(payload) == lanes(op.address, op.size) &&
                std::get<4>(payload) == op.store && std::get<5>(payload) == op.atomic &&
                std::get<6>(payload) == (op.virt && !op.prechecked) && std::get<7>(payload) == op.prechecked &&
                std::get<8>(payload) == epoch && origin == op.origin,
                "LSU payload no longer belongs to the independently accepted start");
            require(d.get_io$$memory$$request$$bits$$atomicOp() == 0 &&
                !d.get_io$$memory$$request$$bits$$uncached() &&
                !d.get_io$$memory$$request$$bits$$prefetchNextAllowed(), "unexpected LSU memory attributes");
            if (origin) require(std::get<10>(payload) == token.index && std::get<11>(payload) == token.tag &&
                std::get<12>(payload) == epoch, "origin full token/epoch does not follow request owner");
            if (memoryReady) {
                require(!o.request, "duplicate request for one owner"); o.request = true; ++requests;
                replies.push_back({token, cycle + 7, op.store ? 0 : beatData(address), op.error});
            }
        }
        if (response && d.get_io$$memory$$response$$ready()) {
            const auto reply = replies.front(); replies.pop_front();
            auto &o = owner(reply.token);
            require(o.request && !o.response, "response lost original FIFO ownership");
            o.response = true; ++responses; lastResponse = reply.token;
        }
        if (d.get_io$$complete$$valid() && completeReady) {
            const Token token{unsigned(d.get_io$$complete$$bits$$token$$index()),
                uint64_t(d.get_io$$complete$$bits$$token$$tag())};
            auto &o = owner(token); const auto &op = o.operation;
            require(o.response && !o.completion && !o.cancelled, "cancelled, premature or duplicate completion");
            const uint64_t expected = op.store ? 0 : loadData(op.prechecked ? op.physical : op.address, op.size);
            require(d.get_io$$complete$$bits$$data() == expected &&
                bool(d.get_io$$complete$$bits$$exception()) == op.error &&
                d.get_io$$complete$$bits$$tval() == op.address && d.get_io$$complete$$bits$$nextPc() == 0x1004,
                "load/store completion bytes, original VA or precise exception mismatch");
            if (op.error) require(d.get_io$$complete$$bits$$cause() == (op.store ? 7 : 5),
                "late physical error did not retain architectural access-fault cause");
            o.completion = true; ++completions;
        }
        discarded += d.get_io$$discarded(); ++cycle; return take;
    }
    void reject(Operation op, unsigned cycles = 3) {
        for (unsigned n = 0; n < cycles; ++n)
            require(!tick(op), "serial-owner exemption escaped its exact accepted owner or candidate class");
    }
    void accept(Operation op) {
        for (unsigned n = 0; n < 200; ++n) if (tick(op)) return;
        throw std::runtime_error("expected LSU start timed out");
    }
    void drain() {
        memoryReady = true; completeReady = true; allowReplies = true; cancel.reset();
        for (unsigned n = 0; n < 400; ++n) { tick(); if (!d.get_io$$busy() && replies.empty()) break; }
        tick();
        require(!d.get_io$$busy() && !d.get_io$$liveMask() && replies.empty() && !held,
            "LSU cancelled/ordinary owners failed complete drain");
        require(requests == responses, "request/ordered-response conservation failure");
        for (const auto &o : owners) require(o.request && o.response && (o.completion != o.cancelled),
            "owner was lost, falsely completed or left outstanding");
    }
};

static Operation store(Token token) {
    Operation op; op.token = token; op.store = true; op.prechecked = false;
    op.parallel = false; op.origin = true; return op;
}
static Operation load(Token token) {
    Operation op; op.token = token; op.address = va + 8; op.physical = ram + 8; return op;
}

int main(int argc, char **argv) { try {
    unsigned totalOverlaps = 0, totalCancelled = 0;
    {
        Bench b; b.inject = argc > 1 && std::string(argv[1]) == "--inject-payload";
        const auto s = store({3, 7}), l = load({4, 8});
        b.memoryReady = false; b.accept(s); b.relaxed = s.token;
        b.reject(l, 5); b.blockedBeforeAcceptance += 5;
        // Even request acceptance on this edge is too early for the registered exception.
        b.memoryReady = true; require(!b.tick(l), "same-edge request fire bypassed acceptance register");
        ++b.blockedBeforeAcceptance;
        b.relaxed = Token{s.token.index, s.token.tag + 1}; b.reject(l);
        b.relaxed = Token{s.token.index + 1, s.token.tag}; b.reject(l);
        b.relaxed.reset(); b.reject(l);
        b.relaxed = s.token;
        auto ordinary = l; ordinary.prechecked = false; b.reject(ordinary);
        auto physical = ordinary; physical.virt = false; b.reject(physical);
        auto write = ordinary; write.store = true; b.reject(write);
        auto atomic = ordinary; atomic.atomic = true; b.reject(atomic);
        auto forwarded = ordinary; forwarded.forward = true; b.reject(forwarded);
        auto serial = l; serial.parallel = false; b.reject(serial);
        b.memoryReady = false; b.accept(l);
        for (unsigned n = 0; n < 4; ++n) b.tick();
        b.cancel = l.token; b.tick(); b.cancel.reset();
        // A killed held request is irrevocable, so retain payload and drain its real response.
        for (unsigned n = 0; n < 4; ++n) b.tick();
        b.drain(); require(b.discarded && b.holds && b.overlapStarts == 1 && b.completions == 1,
            "accepted-owner/held cancellation witness missing");
        totalOverlaps += b.overlapStarts; totalCancelled += b.discarded;
    }
    {
        Bench b; auto s = store({2, 31}); s.origin = false;
        b.accept(s); for (unsigned n = 0; n < 3; ++n) b.tick();
        b.relaxed = s.token; b.reject(load({3, 32}), 5); b.drain();
    }
    for (bool errorOnStore : {false, true}) {
        Bench b; auto s = store({5, 254}); auto l = load({6, 255});
        s.error = errorOnStore; l.error = !errorOnStore;
        b.accept(s); b.tick(); b.relaxed = s.token; b.accept(l);
        for (unsigned n = 0; n < 10; ++n) b.tick();
        b.allowReplies = true;
        if (errorOnStore) {
            for (unsigned n = 0; n < 40; ++n) {
                b.tick(); if (b.lastResponse && *b.lastResponse == s.token) break;
            }
            require(b.lastResponse && *b.lastResponse == s.token, "late store response witness missing");
            b.relaxed.reset(); b.cancel = l.token; b.tick(); b.cancel.reset();
        }
        b.drain(); totalOverlaps += b.overlapStarts; totalCancelled += b.discarded;
    }
    {
        Bench b; const auto first = store({1, 40});
        b.accept(first); b.allowReplies = true; b.completeReady = false;
        for (unsigned n = 0; n < 20; ++n) b.tick();
        auto replacement = store({1, 41});
        b.relaxed = first.token; b.memoryReady = false; b.completeReady = true;
        b.accept(replacement); // Completion and new owner may coincide; old acceptance must not survive.
        const auto next = load({2, 42}); b.reject(next, 4);
        b.relaxed = replacement.token; b.reject(next, 4);
        b.memoryReady = true; require(!b.tick(next), "replacement inherited old registered acceptance");
        b.allowReplies = false; b.accept(next); b.drain(); totalOverlaps += b.overlapStarts;
    }
    require(totalOverlaps >= 4 && totalCancelled >= 2, "required serial-overlap/cancellation coverage missing");
    std::cout << "CANONICAL_STORE_LSU_PASS overlaps=" << totalOverlaps
        << " cancelled=" << totalCancelled << '\n'; return 0;
} catch (const std::exception &e) { std::cerr << "CANONICAL_STORE_LSU_FAIL " << e.what() << '\n'; return 1; } }
