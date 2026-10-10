#pragma once
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <string>

// Standalone software truth. No hardware helpers, private DUT fields, certificates,
// translation hit bits or cache phase enter the expected permission calculation.
namespace canonical_store_test {
constexpr uint64_t ram = 0x80010000ULL, ramBytes = 65536, va = 0x40000000ULL;
inline void require(bool ok, const std::string &message) {
    if (!ok) throw std::runtime_error(message);
}
struct Token {
    unsigned index = 3;
    uint64_t tag = 7;
    bool operator==(const Token &b) const { return index == b.index && tag == b.tag; }
    bool operator!=(const Token &b) const { return !(*this == b); }
};
struct Descriptor {
    Token token;
    uint32_t epoch = 11;
    uint64_t virtualAddress = va, physicalAddress = ram;
    unsigned size = 3, mask = 255;
};
inline bool aligned(uint64_t address, unsigned size) {
    return size <= 3 && address % (uint64_t(1) << size) == 0;
}
inline unsigned lanes(uint64_t address, unsigned size) {
    if (size > 3) return 0;
    unsigned result = 0;
    for (unsigned byte = 0; byte < (1u << size); ++byte)
        result |= 1u << ((address + byte) % 8);
    return result;
}
inline bool wholeRam(uint64_t address, unsigned size) {
    if (size > 3) return false;
    const unsigned __int128 first = address;
    const unsigned __int128 last = first + (uint64_t(1) << size);
    return first >= ram && last <= static_cast<unsigned __int128>(ram) + ramBytes;
}
inline bool shape(const Descriptor &d) {
    return aligned(d.virtualAddress, d.size) && aligned(d.physicalAddress, d.size) &&
        d.virtualAddress % 4096 == d.physicalAddress % 4096 &&
        d.mask == lanes(d.physicalAddress, d.size) && wholeRam(d.physicalAddress, d.size);
}
inline bool sameDescriptor(const Descriptor &a, const Descriptor &b) {
    return a.token == b.token && a.epoch == b.epoch && a.virtualAddress == b.virtualAddress &&
        a.size == b.size && a.mask == b.mask;
}
inline bool disjoint(uint64_t first, unsigned firstSize, uint64_t second, unsigned secondSize) {
    if (!aligned(first, firstSize) || !aligned(second, secondSize)) return false;
    const unsigned __int128 firstEnd = static_cast<unsigned __int128>(first) + (1u << firstSize);
    const unsigned __int128 secondEnd = static_cast<unsigned __int128>(second) + (1u << secondSize);
    return firstEnd <= second || secondEnd <= first;
}
inline uint64_t beatData(uint64_t address) {
    uint64_t result = 0;
    const uint64_t first = address - address % 8;
    for (unsigned byte = 0; byte < 8; ++byte) {
        const uint8_t value = uint8_t(((first + byte) * 37) ^ ((first + byte) >> 13) ^ 0x5a);
        result |= uint64_t(value) << (byte * 8);
    }
    return result;
}
inline uint64_t loadData(uint64_t address, unsigned size) {
    const uint64_t data = beatData(address) >> ((address % 8) * 8);
    return size == 3 ? data : data & ((uint64_t(1) << ((1u << size) * 8)) - 1);
}
} // namespace canonical_store_test
