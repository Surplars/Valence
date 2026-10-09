#pragma once
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace monitor_replay {
inline void require(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
constexpr uint64_t base = 0xfff78000, textEnd = 0xfff7daa0, dataStart = 0xfff7e940;
constexpr uint64_t bssEnd = 0xfff7f158, stackStart = 0xfff94000, stackEnd = 0xfff98000;
constexpr uint64_t aBase = 0xfff98000, bBase = 0xfffb8000, bufferBytes = 131072;
constexpr uint64_t mailbox = 0xffff7f00, romBase = 0x80000000;
inline bool inside(uint64_t a, uint64_t n, uint64_t lo, uint64_t hi) {
    return a >= lo && a <= hi && n <= hi - a;
}
inline uint64_t pattern(uint64_t i) { return 0x935b76124aedc087ULL ^ (i * 0x102040810204081ULL); }
inline uint64_t byteMask(unsigned mask) {
    uint64_t bits = 0;
    for (unsigned i = 0; i < 8; ++i) if (mask & (1U << i)) bits |= 255ULL << (8 * i);
    return bits;
}
struct MemoryOracle {
    std::map<uint64_t, uint64_t> words;
    uint64_t romBytes = 0, aWrites = 0, bWrites = 0, totalWrites = 0;
    void seed(uint64_t address, const std::vector<uint8_t> &bytes) {
        for (size_t i = 0; i < bytes.size(); ++i) {
            auto &w = words[(address + i) & ~7ULL];
            const unsigned shift = unsigned((address + i) & 7) * 8;
            w = (w & ~(255ULL << shift)) | (uint64_t(bytes[i]) << shift);
        }
    }
    void initialize(const std::vector<uint8_t> &image, const std::vector<uint8_t> &rom) {
        require(image.size() == 26952, "oracle archived image size drift");
        seed(base, image); seed(romBase, rom); romBytes = rom.size(); words[mailbox] = 'b';
        // Unseeded bytes in declared scratch/BSS/buffer regions are explicitly zero.
        // These are an independent map, never reads from the DUT or DDR model.
    }
    static bool uart(uint64_t address) { return address == 0x10000000 || address == 0x10000002 || address == 0x10000005; }
    bool mapped(uint64_t address, unsigned bytes) const {
        return inside(address, bytes, base, bssEnd) || inside(address, bytes, stackStart, stackEnd) ||
            inside(address, bytes, aBase, bBase + bufferBytes + 32) || // at most four final verification guard words; canceled-token proof required
            inside(address, bytes, mailbox, mailbox + 8) || inside(address, bytes, romBase, romBase + romBytes);
    }
    bool writable(uint64_t address, unsigned bytes) const {
        return inside(address, bytes, dataStart, bssEnd) || inside(address, bytes, stackStart, stackEnd) ||
            inside(address, bytes, aBase, bBase + bufferBytes);
    }
    uint64_t get(uint64_t address) const {
        auto found = words.find(address & ~7ULL);
        return found == words.end() ? 0 : found->second;
    }
    unsigned validate(uint64_t address, uint64_t meta) const {
        // Bit18 is the explicit uncached attribute, not instruction execute.
        // Frozen LoadStoreUnit initializes it false, and M-mode identity
        // translation preserves it even for UART; the address mapper selects
        // the device route. PBMT/VM-derived uncached requests are out of scope.
        require(!(meta & (2 | (1ULL << 17) | (1ULL << 18))), "oracle unexpected atomic/virtual/uncached request");
        const unsigned bytes = 1U << ((meta >> 7) & 3), offset = address & 7;
        const unsigned mask = (meta >> 9) & 255;
        require((address & (bytes - 1)) == 0 && offset + bytes <= 8 && mask == ((1U << bytes) - 1) << offset,
                "oracle illegal request alignment/size/mask");
        if (uart(address)) {
            require(bytes == 1 && ((meta & 1) ? address != 0x10000005 : address == 0x10000005),
                    "oracle unexpected UART register operation");
        } else {
            require(mapped(address, bytes), "oracle unexpected CPU memory region");
            if (meta & 1) require(writable(address, bytes), "oracle write outside mutable diagnostic region");
        }
        return mask;
    }
    void bufferWrite(uint64_t address, uint64_t value, uint64_t meta) {
        if (!inside(address, 1, aBase, bBase + bufferBytes)) return;
        require((meta & 3) == 1 && ((meta >> 7) & 3) == 3 && ((meta >> 9) & 255) == 255,
                "oracle buffer store is not aligned SD");
        bool a = address < bBase;
        uint64_t n = a ? aWrites++ : bWrites++;
        const unsigned stages = a ? 3 : 2;
        uint64_t size = 1024;
        if (n >= stages * size) { n -= stages * size; size = 16384; }
        require(n < stages * size, "oracle excess buffer stores");
        const uint64_t stage = n / size, index = n % size;
        uint64_t expected = a ? (stage == 1 ? ~pattern(index) : pattern(index)) : (stage == 0 ? 0 : pattern(index));
        require(address == (a ? aBase : bBase) + index * 8, "oracle buffer store ordinal/address mismatch");
        require(value == expected, "oracle buffer store pattern mismatch");
    }
    uint64_t accept(uint64_t address, uint64_t value, uint64_t meta, bool checkPattern = true) {
        const auto mask = validate(address, meta);
        const uint64_t old = get(address);
        if ((meta & 1) && !uart(address)) {
            if (checkPattern) bufferWrite(address, value, meta);
            const uint64_t bits = byteMask(mask);
            words[address & ~7ULL] = (old & ~bits) | (value & bits);
            ++totalWrites;
        }
        return old;
    }
    void verifyBuffers() const {
        require(aWrites == 3 * (1024 + 16384) && bWrites == 2 * (1024 + 16384), "oracle buffer store conservation mismatch");
        for (uint64_t i = 0; i < bufferBytes / 8; ++i) {
            require(get(aBase + 8 * i) == pattern(i), "oracle final A pattern mismatch");
            require(get(bBase + 8 * i) == pattern(i), "oracle final B pattern mismatch");
        }
    }
};
}
