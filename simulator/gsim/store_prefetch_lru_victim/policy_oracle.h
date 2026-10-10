#pragma once
#include <array>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

// Specification model: conventional two-way LRU is authored here using access
// order. No DUT selector, tag codec, generated constant, or hardware helper is
// imported. Physical addresses remain full-width until the RAM backing edge.
namespace lru_victim_oracle {
inline void require(bool ok, const char* why) {
    if (!ok) throw std::runtime_error(why);
}
struct Line {
    bool valid = false, dirty = false;
    uint64_t address = 0;
};
struct Set {
    std::array<Line, 2> ways{};
    unsigned oldest = 0;
};
struct Choice {
    unsigned set = 0, way = 0, slot = 0;
    Line victim{};
    bool admissible = false;
};
class Policy {
    unsigned setCount_, wayCount_;
    bool lruStore_;
    std::vector<Set> state_;
public:
    explicit Policy(unsigned sets, bool lruStore, unsigned ways = 2)
        : setCount_(sets), wayCount_(ways), lruStore_(lruStore), state_(sets) {
        require(sets && (ways == 1 || ways == 2), "invalid oracle geometry");
    }
    static uint64_t line(uint64_t address) { return address - address % 64; }
    unsigned set(uint64_t address) const { return (address / 64) % setCount_; }
    unsigned slot(uint64_t address, unsigned way) const { return way * setCount_ + set(address); }
    const Set& state(uint64_t address) const { return state_.at(set(address)); }
    std::optional<unsigned> find(uint64_t address) const {
        const auto& s = state(address);
        for (unsigned w = 0; w < wayCount_; ++w)
            if (s.ways[w].valid && s.ways[w].address == line(address)) return w;
        return std::nullopt;
    }
    Choice choose(uint64_t address, bool prefetch, bool storeOrigin) const {
        const auto& s = state(address);
        unsigned selected = 0;
        bool invalid = false;
        for (unsigned w = 0; w < wayCount_; ++w) if (!s.ways[w].valid) {
            selected = w; invalid = true; break;
        }
        if (!invalid) {
            selected = wayCount_ == 1 ? 0 : s.oldest;
            if (prefetch && !(storeOrigin && lruStore_)) {
                for (unsigned w = 0; w < wayCount_; ++w) if (!s.ways[w].dirty) {
                    selected = w; break;
                }
            }
        }
        const auto victim = s.ways[selected];
        const bool permission = !prefetch || storeOrigin || !victim.valid || !victim.dirty;
        return {set(address), selected, slot(address, selected), victim, permission};
    }
    void hit(uint64_t address, bool write) {
        const auto way = find(address);
        require(bool(way), "accepted hit missing independent full-PA residency");
        auto& s = state_.at(set(address));
        s.ways[*way].dirty |= write;
        s.oldest = wayCount_ == 1 ? 0 : 1 - *way;
    }
    void install(uint64_t address, unsigned way, bool write, bool prefetch, bool storeOrigin, bool error) {
        require(way < wayCount_, "installation outside oracle ways");
        if (error) return;
        auto& s = state_.at(set(address));
        require(!s.ways[way].valid || s.ways[way].address == line(address), "installation overwrote retained line");
        s.ways[way] = {true, write, line(address)};
        s.oldest = wayCount_ == 1 ? 0 : (prefetch && !storeOrigin ? way : 1 - way);
    }
    void invalidate(uint64_t address) {
        if (const auto way = find(address)) state_.at(set(address)).ways[*way] = {};
    }
    void capture(uint64_t address, bool dirty) {
        const auto way = find(address);
        require(bool(way), "captured victim absent from independent full-PA residency");
        require(state(address).ways[*way].dirty == dirty, "captured victim dirty state differs from authored stores");
        invalidate(address);
    }
};
}  // namespace lru_victim_oracle
