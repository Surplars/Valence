#pragma once
// Independent flat byte contract: no bank parity, writer selector or packed RTL
// representation participates in expected values. Unknown rows are not zero.
#include <array>
#include <cstdint>
#include <stdexcept>
#include <string>

namespace completion_bytes {
constexpr unsigned fields = 3, bytes_per_field = 8, bytes_per_row = 24;
using Bytes = std::array<uint8_t, bytes_per_row>;
struct Payload { uint64_t data = 0, next_pc = 0, tval = 0; };
struct Row { bool defined = false; Bytes bytes{}; };
struct Write { bool valid = false; unsigned index = 0; Payload value{}; };
inline void require(bool ok, const std::string &why) {
    if (!ok) throw std::runtime_error(why);
}
inline Bytes encode(Payload value) {
    const std::array<uint64_t, 3> words{value.data, value.next_pc, value.tval};
    Bytes out{};
    for (unsigned f = 0; f < fields; ++f)
        for (unsigned b = 0; b < bytes_per_field; ++b) out[f * 8 + b] = uint8_t(words[f] >> (8 * b));
    return out;
}
inline uint64_t field(const Row &row, unsigned f) {
    require(row.defined && f < fields, "ORACLE_UNDEFINED_ROW_READ");
    uint64_t result = 0;
    for (unsigned b = 0; b < bytes_per_field; ++b) result |= uint64_t(row.bytes[f * 8 + b]) << (8 * b);
    return result;
}
inline void compare_field(uint64_t actual, const Row &expected, unsigned f, const std::string &diagnostic) {
    require(expected.defined, "ORACLE_UNDEFINED_ROW_COMPARE");
    for (unsigned b = 0; b < bytes_per_field; ++b)
        require(uint8_t(actual >> (8 * b)) == expected.bytes[f * 8 + b], diagnostic);
}
inline Payload pattern(uint64_t serial) {
    // Independent field markers exercise all byte positions and high bits.
    Payload out;
    std::array<uint64_t *, 3> words{&out.data, &out.next_pc, &out.tval};
    for (unsigned f = 0; f < fields; ++f) for (unsigned b = 0; b < bytes_per_field; ++b) {
        const uint8_t value = uint8_t((serial * 73 + serial / 251 + f * 89 + b * 31) ^ (serial >> (b % 5)));
        *words[f] |= uint64_t(value) << (8 * b);
    }
    return out;
}
class FlatMemory {
    unsigned size_;
public:
    std::array<Row, 32> rows{};
    explicit FlatMemory(unsigned size) : size_(size) { require(size >= 4 && size <= 32, "ORACLE_BAD_SIZE"); }
    unsigned size() const { return size_; }
    void write(const std::array<Write, 2> &writes) {
        require(!(writes[0].valid && writes[1].valid && writes[0].index == writes[1].index), "ORACLE_DUPLICATE_WRITE");
        for (const auto &w : writes) if (w.valid) {
            require(w.index < size_, "ORACLE_BAD_INDEX");
            rows[w.index] = {true, encode(w.value)};
        }
    }
    // No reset method: raw memories and latest-writer selection have no reset.
};
}
