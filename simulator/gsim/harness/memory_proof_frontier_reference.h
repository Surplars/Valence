#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>

// Authored Sv39 leaf/PMP/byte oracle. No production permission helpers, selector
// state, GSIM internals or summary PASS counters contribute to expected values.
namespace memory_proof_reference {
constexpr uint64_t va = 0x40000000ULL, ram = 0x80010000ULL, ramBytes = 65536;
constexpr uint64_t root = 0x81000000ULL;
constexpr uint64_t satp = (8ULL << 60) | (9ULL << 44) | (root >> 12);
constexpr uint64_t allPmp = (1ULL << 54) - 1;
inline void require(bool ok, const std::string &why) { if (!ok) throw std::runtime_error(why); }
struct Token {
    unsigned index = 0;
    uint64_t tag = 0;
    bool operator==(const Token &) const = default;
};
struct Proof {
    Token token;
    uint32_t epoch = 0;
    uint64_t original = 0, physical = 0;
    bool write = false;
    unsigned size = 3, mask = 255;
    bool operator==(const Proof &) const = default;
};
struct Page { uint64_t physical; unsigned flags = 0xc7, pbmt = 0; };
struct Tables {
    std::map<unsigned, Page> pages{{0, {ram}}, {1, {ram + 4096}}, {2, {ram}},
                                 {3, {0x10000000}}, {4, {ram + 8192, 0xc7, 1}},
                                 {5, {ram + 12288, 0xc3, 0}}};
    uint64_t pte(uint64_t address) const {
        if (address == root + 8) return (((root + 4096) >> 12) << 10) | 1;
        if (address == root + 4096) return (((root + 8192) >> 12) << 10) | 1;
        require(address >= root + 8192 && address < root + 12288 && !(address & 7),
                "unexpected raw page-table address");
        const auto it = pages.find(unsigned((address - root - 8192) / 8));
        if (it == pages.end()) return 0;
        return ((it->second.physical >> 12) << 10) | it->second.flags | (uint64_t(it->second.pbmt) << 61);
    }
    uint64_t physical(uint64_t address) const {
        const auto it = pages.find(unsigned((address - va) / 4096));
        require(address >= va && it != pages.end(), "expected page missing");
        return it->second.physical + (address & 4095);
    }
    bool normalAllowed(uint64_t address, bool write, unsigned size, unsigned cfg = 0x1f) const {
        if (address < va || size > 3 || (address & ((1ULL << size) - 1))) return false;
        const auto it = pages.find(unsigned((address - va) / 4096));
        if (it == pages.end()) return false;
        const auto p = it->second;
        const bool v = p.flags & 1, r = p.flags & 2, w = p.flags & 4, a = p.flags & 64, d = p.flags & 128;
        if (!v || !r || !a || p.pbmt || (write && (!w || !d))) return false;
        const __uint128_t begin = physical(address), end = begin + (__uint128_t(1) << size);
        return begin >= ram && end <= __uint128_t(ram) + ramBytes &&
               (cfg & (write ? 2 : 1)) && ((cfg >> 3) & 3) == 3;
    }
};
inline bool disjoint(const Proof &a, const Proof &b) {
    return __uint128_t(a.physical) + (__uint128_t(1) << a.size) <= b.physical ||
           __uint128_t(b.physical) + (__uint128_t(1) << b.size) <= a.physical;
}
inline uint8_t initialByte(uint64_t address) {
    return uint8_t(((address * 17) ^ (address >> 7) ^ 0xA6) & 255);
}
struct Bytes {
    std::map<uint64_t, uint8_t> changed;
    uint64_t read(uint64_t address, unsigned size) const {
        uint64_t value = 0;
        for (unsigned i = 0; i < (1u << size); ++i) {
            auto it = changed.find(address + i);
            value |= uint64_t(it == changed.end() ? initialByte(address + i) : it->second) << (8 * i);
        }
        return value;
    }
    void write(uint64_t address, uint64_t data, unsigned size) {
        for (unsigned i = 0; i < (1u << size); ++i) changed[address + i] = uint8_t(data >> (8 * i));
    }
};
}
