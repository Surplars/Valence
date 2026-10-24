#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <map>
#include <stdexcept>
#include <string>

// Independent byte/address and transaction accounting. This file imports no
// DUT encodings, generated headers, frontend implementation or old-core logic.
namespace a1_fetch_oracle {
inline void require(bool condition, const std::string &message) {
    if (!condition) throw std::runtime_error("A1_FETCH_ORACLE " + message);
}

enum class Pattern { plain32, mixed };
struct Image {
    uint64_t physicalBase = 0x80000000ULL;
    uint64_t virtualBase = 0x80000000ULL;
    Pattern pattern = Pattern::plain32;

    uint8_t byteAtOffset(uint64_t offset) const {
        if (pattern == Pattern::plain32) {
            // ADDI x1,x1,imm; differing immediate fields make shifted/repeated
            // word substitutions visible without introducing control flow.
            const uint32_t instruction = 0x00008093U | (uint32_t((offset / 4) & 4095) << 20);
            return uint8_t(instruction >> (8 * (offset % 4)));
        }
        // Repeating instruction lengths 2,4,4,2. In particular PC+6 straddles
        // an eight-byte packet and PC+4094 straddles a translation page.
        const unsigned position = offset % 12;
        if (position < 2) return uint8_t(0x0001U >> (8 * position)); // C.NOP
        if (position < 6) {
            const uint32_t instruction = 0x00008093U | (uint32_t((offset / 12) & 4095) << 20);
            return uint8_t(instruction >> (8 * (position - 2)));
        }
        if (position < 10) {
            const uint32_t instruction = 0x00010113U | (uint32_t((offset / 12 + 37) & 4095) << 20);
            return uint8_t(instruction >> (8 * (position - 6)));
        }
        return uint8_t(0x0085U >> (8 * (position - 10))); // C.ADDI x1,1
    }
    uint16_t parcel(uint64_t pc) const {
        const auto offset = pc - virtualBase;
        return uint16_t(byteAtOffset(offset)) | (uint16_t(byteAtOffset(offset + 1)) << 8);
    }
    unsigned length(uint64_t pc) const { return (parcel(pc) & 3) == 3 ? 4 : 2; }
    uint32_t instruction(uint64_t pc) const {
        uint32_t value = parcel(pc);
        if (length(pc) == 4) value |= uint32_t(parcel(pc + 2)) << 16;
        return value;
    }
    uint64_t beat(uint64_t physicalAddress) const {
        uint64_t value = 0;
        for (unsigned byte = 0; byte < 8; ++byte)
            value |= uint64_t(byteAtOffset(physicalAddress - physicalBase + byte)) << (8 * byte);
        return value;
    }
};

// Ordered InstructionPort ownership is deliberately separate from TL source
// ownership. A reply-before-new-request cycle may release then reuse a slot.
struct OrderedOwners {
    struct Owner { uint64_t address, start, generation; };
    std::deque<Owner> owners;
    uint64_t accepted = 0, completed = 0, latencySum = 0, maxLatency = 0, staleReplies = 0;
    size_t maximum = 0;
    void request(uint64_t address, uint64_t cycle, uint64_t generation) {
        owners.push_back({address, cycle, generation});
        ++accepted;
        maximum = std::max(maximum, owners.size());
    }
    Owner response(uint64_t cycle, uint64_t generation) {
        require(!owners.empty(), "reply without accepted instruction owner");
        const auto owner = owners.front();
        owners.pop_front();
        require(cycle > owner.start, "instruction reply did not cross an edge");
        ++completed;
        const auto latency = cycle - owner.start;
        latencySum += latency;
        maxLatency = std::max(maxLatency, latency);
        staleReplies += owner.generation != generation;
        return owner;
    }
};

struct TlOwners {
    struct Owner { uint64_t address, start; unsigned size, remaining; };
    std::map<unsigned, Owner> owners;
    uint64_t requests = 0, responses = 0, beats = 0;
    void request(unsigned source, uint64_t address, unsigned size, unsigned mask, uint64_t cycle) {
        require(!owners.count(source), "TL source reused before last D");
        require(size == 2 || size == 3 || size == 6, "unexpected instruction Get extent");
        const uint64_t bytes = uint64_t(1) << size;
        require((address & (bytes - 1)) == 0, "unaligned instruction Get");
        const unsigned wantedMask = size >= 3 ? 255 : (15U << (address & 7));
        require(mask == wantedMask, "Get mask differs from independently derived extent");
        owners.emplace(source, Owner{address, cycle, size, size == 6 ? 8U : 1U});
        ++requests;
    }
    void response(unsigned source, unsigned size, uint64_t cycle) {
        auto found = owners.find(source);
        require(found != owners.end(), "D without source owner");
        require(found->second.size == size, "D size differs from accepted Get");
        require(cycle > found->second.start, "D beat did not cross an edge");
        ++beats;
        if (--found->second.remaining == 0) { owners.erase(found); ++responses; }
    }
};

struct Counters {
    uint64_t cycles = 0, consumed = 0;
    std::array<uint64_t, 3> raw{}, captured{}, consume{};
    std::array<uint64_t, 5> occupancy{};
    std::array<uint64_t, 3> cache{};
    uint64_t tlbHits = 0, walks = 0, pteReads = 0, get8 = 0, get64 = 0, get4 = 0;
    void sample(unsigned r, unsigned c, unsigned n, unsigned fill, unsigned cacheClass) {
        require(r <= 2 && c <= 2 && n <= 2 && fill <= 4, "counter sample outside two-lane geometry");
        require(cacheClass == 0 || cacheClass == 1 || cacheClass == 2 || cacheClass == 4,
                "cache class is not exclusive");
        ++cycles; ++raw[r]; ++captured[c]; ++consume[n]; ++occupancy[fill]; consumed += n;
        for (unsigned bit = 0; bit < 3; ++bit) cache[bit] += bool(cacheClass & (1U << bit));
    }
    void validate() const {
        auto sum = [](const auto &a) { uint64_t n = 0; for (auto v : a) n += v; return n; };
        require(sum(raw) == cycles && sum(captured) == cycles && sum(consume) == cycles &&
                sum(occupancy) == cycles && consume[1] + 2 * consume[2] == consumed,
                "histograms do not partition sampled cycles");
    }
};
} // namespace a1_fetch_oracle
