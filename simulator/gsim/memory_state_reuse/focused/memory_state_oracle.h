#pragma once
#include <array>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
namespace memory_state_oracle {
inline void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
struct Token { unsigned index; uint64_t tag; bool operator==(const Token &) const = default; };
struct Intent { Token token; bool memory, store, atomic; uint64_t address; unsigned size; };
struct Row { std::optional<Intent> owner; bool payloadKnown = false; uint64_t address = 0; unsigned lanes = 0; };
inline unsigned byteLanes(uint64_t address, unsigned size) {
    check(size < 4, "oracle memory width out of range");
    return (((1u << (1u << size)) - 1u) << (address & 7)) & 255;
}
class Oracle {
    std::array<Row, 64> rows;
public:
    void verify(unsigned slot, uint64_t tag, bool live, uint64_t address, unsigned lanes) const {
        const auto &row = rows.at(slot);
        if (live) check(row.owner && row.owner->token == Token{slot, tag}, "live row lost independent accepted full token");
        if (row.payloadKnown) check(row.address == address && row.lanes == lanes, "shared address row changed outside its authorized write");
    }
    bool known(unsigned slot) const { return rows.at(slot).payloadKnown; }
    bool matches(Token token) const { const auto &row = rows.at(token.index); return row.owner && row.owner->token == token; }
    Intent owner(Token token) const {
        const auto &row = rows.at(token.index);
        check(row.owner && row.owner->token == token, "write used stale or unknown full token");
        return *row.owner;
    }
    void allocate(Intent intent) { rows.at(intent.token.index).owner = intent; }
    void store(Token token, bool killed) {
        const auto intent = owner(token);
        check(intent.memory && intent.store && !killed, "prepared write lacks an independently decoded live store");
        auto &row = rows.at(token.index);
        row.payloadKnown = true; row.address = intent.address; row.lanes = byteLanes(intent.address, intent.size);
    }
    void load(Token token, bool killed, bool finalStore, bool finalAtomic, bool canonical,
              uint64_t expectedPhysical, uint64_t observedBeat, unsigned observedLanes) {
        const auto intent = owner(token);
        check(intent.memory && !intent.store && !intent.atomic && !finalStore && !finalAtomic && !killed,
              "shared load write used nonordinary or killed owner");
        auto &row = rows.at(token.index);
        if (!canonical) { row.payloadKnown = false; return; }
        const auto beat = expectedPhysical >> 3;
        const auto mask = byteLanes(expectedPhysical, intent.size);
        check(observedBeat == beat && observedLanes == mask, "final canonical load metadata differs from independent address and width");
        row.payloadKnown = true; row.address = beat << 3; row.lanes = mask;
    }
};
}
