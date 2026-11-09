#include "DecoderImmediateGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static uint64_t signedValue(uint32_t value, unsigned bits) {
    return (value & (uint32_t(1) << (bits - 1))) ? uint64_t(value) - (uint64_t(1) << bits) : value;
}

int main(int argc, char** argv) { try {
    const bool inject = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SDecoderImmediateGsim d;
    d.set_io$$instruction(0); d.set_io$$compressed(0);
    d.set_reset(1); d.step(); d.set_reset(0);
    unsigned count = 0, exact = 0;
    auto probe = [&](uint32_t instruction, bool compressed) {
        d.set_io$$instruction(instruction); d.set_io$$compressed(compressed); d.step();
        uint64_t actual = d.get_io$$immediate();
        if (inject && count == 100) actual ^= uint64_t(1) << 40;
        // Check the numeric range without mirroring RTL sign-concatenation.
        if (actual > 0x7fffffffULL && actual < 0xffffffff80000000ULL)
            throw std::runtime_error("decoder immediate outside signed32");
        ++count;
        if (compressed) return; // Expansion correctness is not claimed by this range test.
        const unsigned opcode = instruction & 127;
        uint64_t expected;
        switch (opcode) {
            case 0x37: case 0x17: expected = signedValue(instruction & 0xfffff000U, 32); break;
            case 0x23:
                expected = signedValue(((instruction >> 25) << 5) | ((instruction >> 7) & 31), 12); break;
            case 0x63:
                expected = signedValue(((instruction >> 31) << 12) | (((instruction >> 7) & 1) << 11) |
                    (((instruction >> 25) & 63) << 5) | (((instruction >> 8) & 15) << 1), 13); break;
            case 0x6f:
                expected = signedValue(((instruction >> 31) << 20) | (((instruction >> 12) & 255) << 12) |
                    (((instruction >> 20) & 1) << 11) | (((instruction >> 21) & 1023) << 1), 21); break;
            case 0x2f: expected = 0; break;
            case 0x03: case 0x13: case 0x1b: case 0x67:
                expected = signedValue(instruction >> 20, 12); break;
            default: return;
        }
        if (actual != expected) throw std::runtime_error("decoder immediate encoding oracle mismatch");
        ++exact;
    };
    for (uint32_t word = 0; word < 65536; ++word) probe(word, true);
    const std::array<uint32_t, 16> patterns = {0, 0xffffffffU, 0x80000000U, 0x7fffffffU,
        0xaaaaaaaaU, 0x55555555U, 0x00000800U, 0x00001000U, 0x00080000U, 0x00100000U,
        0x7ff00000U, 0x80000080U, 0xfff00000U, 0x01f00000U, 0xfe000f80U, 0x000ff000U};
    for (uint32_t opcode = 0; opcode < 128; ++opcode)
        for (uint32_t funct3 = 0; funct3 < 8; ++funct3)
            for (uint32_t pattern : patterns) probe((pattern & ~0x707fU) | (funct3 << 12) | opcode, false);
    std::mt19937 random(0x891231);
    for (unsigned n = 0; n < 20000; ++n) probe(random(), false);
    if (exact < 1000) throw std::runtime_error("missing decoder exact immediate coverage");
    std::cout << "GSIM decoder immediate: PASS compressed=65536 directed=16384 random=20000 exact=" << exact << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; } }
