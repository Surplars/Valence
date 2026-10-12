#pragma once
#include <cstdint>
#include <deque>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>

// Independent transport oracle. No DUT arrays, state, ready hints or result-based
// owner search enter this ledger. Reserve on the original request-queue fire;
// release only after the exact slot's real response and completion/discard drain.
namespace tagged_return_reference {
struct Token {
    unsigned index = 0; uint64_t generation = 0;
    auto operator<=>(const Token&) const = default;
};
struct Operation {
    Token token; uint64_t va = 0, pa = 0, data = 0; unsigned size = 3;
    bool store = false, prechecked = true, virtualized = true, parallel = true, frozen = false;
    // 1 architectural access fault, 2 architectural page fault, 3 backing access error.
    unsigned fault = 0; uint32_t epoch = 0; bool stale = false;
};
struct Life {
    Operation op; unsigned slot = 0, handle = 0;
    uint64_t start = 0, queued = 0, physical = 0, cache = 0, cacheReply = 0, reply = 0, complete = 0, release = 0;
    uint64_t expectedBeat = 0; bool cancelled = false, hit = false;
};
inline void require(bool condition, const std::string& message) {
    if (!condition) throw std::runtime_error(message);
}
struct Ledger {
    std::map<Token, Life> lives;
    std::map<unsigned, Token> handles;
    std::deque<Token> queueOrder, physicalOrder, cacheRequests, cacheOrder;
    void reserve(const Token& token, unsigned handle, uint64_t cycle, bool tagged) {
        auto& x = lives.at(token);
        require(!x.queued, "duplicate accepted full token");
        require(!handles.count(handle), "live return handle reused before real reply and slot drain");
        require(!tagged || handle == x.slot, "accepted return handle disagrees with actual reserved LSU slot");
        x.queued = cycle; x.handle = handle; handles.emplace(handle, token); queueOrder.push_back(token);
        if (x.op.fault != 1 && x.op.fault != 2) physicalOrder.push_back(token);
    }
    Token resolve(unsigned handle) const {
        auto found = handles.find(handle);
        require(found != handles.end(), "unknown or stale return handle");
        return found->second;
    }
    void release(const Token& token, uint64_t cycle) {
        auto& x = lives.at(token);
        require(!x.release, "duplicate slot release");
        require(x.reply || !x.queued, "cancelled owner released before actual response drain");
        require(x.complete || x.cancelled, "slot released without completion or discard");
        x.release = cycle;
        if (x.queued) { require(handles.at(x.handle) == token, "full generation lost at handle release"); handles.erase(x.handle); }
    }
};
}
