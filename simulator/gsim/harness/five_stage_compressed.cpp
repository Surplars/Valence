#include "FiveStageCompressed.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
static unsigned bits(unsigned v, unsigned high, unsigned low) { return (v >> low) & ((1U << (high-low+1))-1); }
static uint32_t sext(uint32_t v, unsigned n) { return (v ^ (1U << (n-1))) - (1U << (n-1)); }
static uint32_t i(unsigned op, unsigned rd, unsigned f, unsigned rs, uint32_t imm) {
    return (imm & 4095) << 20 | rs << 15 | f << 12 | rd << 7 | op;
}
static uint32_t r(unsigned op, unsigned rd, unsigned f, unsigned a, unsigned b, unsigned h = 0) {
    return h << 25 | b << 20 | a << 15 | f << 12 | rd << 7 | op;
}
static uint32_t s(unsigned f, unsigned a, unsigned b, uint32_t imm) {
    return (imm & 4064) << 20 | b << 20 | a << 15 | f << 12 | (imm & 31) << 7 | 0x23;
}
static uint32_t j(unsigned rd, uint32_t imm) {
    return (imm >> 20 & 1) << 31 | (imm >> 1 & 1023) << 21 | (imm >> 11 & 1) << 20 |
        (imm >> 12 & 255) << 12 | rd << 7 | 0x6f;
}
static uint32_t b(unsigned f, unsigned a, uint32_t imm) {
    return (imm >> 12 & 1) << 31 | (imm >> 5 & 63) << 25 | a << 15 | f << 12 |
        (imm >> 1 & 15) << 8 | (imm >> 11 & 1) << 7 | 0x63;
}
// Independent software oracle: extract-and-position expressions, not imported DUT decode tables.
struct Expected { bool legal = false; uint32_t value = 0; };
static Expected decode(unsigned c) {
    unsigned q = c & 3, f = c >> 13, rd = bits(c,11,7), rs2 = bits(c,6,2);
    unsigned a = 8 + bits(c,9,7), z = 8 + bits(c,4,2);
    uint32_t simm = sext((c >> 12 & 1) * 32 + rs2, 6);
    unsigned sh = (c >> 12 & 1) * 32 + rs2;
    unsigned lw = (c >> 5 & 1) * 64 + bits(c,12,10) * 8 + (c >> 6 & 1) * 4;
    unsigned ld = bits(c,6,5) * 64 + bits(c,12,10) * 8;
    uint32_t ji = sext((c >> 12 & 1) * 2048 + (c >> 8 & 1) * 1024 + bits(c,10,9) * 256 +
        (c >> 6 & 1) * 128 + (c >> 7 & 1) * 64 + (c >> 2 & 1) * 32 +
        (c >> 11 & 1) * 16 + bits(c,5,3) * 2, 12);
    uint32_t bi = sext((c >> 12 & 1) * 256 + bits(c,6,5) * 64 + (c >> 2 & 1) * 32 +
        bits(c,11,10) * 8 + bits(c,4,3) * 2, 9);
    Expected out;
    auto yes = [&](uint32_t v) { out = {true, v}; };
    if (q == 0) {
        if (f == 0) {
            unsigned off = bits(c,10,7) * 64 + bits(c,12,11) * 16 + (c >> 5 & 1) * 8 + (c >> 6 & 1) * 4;
            if (off) yes(i(0x13,z,0,2,off));
        }
        if (f == 2) yes(i(3,z,2,a,lw));
        if (f == 3 && DUT_XLEN == 64) yes(i(3,z,3,a,ld));
        if (f == 6) yes(s(2,a,z,lw));
        if (f == 7 && DUT_XLEN == 64) yes(s(3,a,z,ld));
    }
    if (q == 1) {
        if (f == 0) yes(i(0x13,rd,0,rd,simm));
        if (f == 1) {
            if (DUT_XLEN == 32) yes(j(1,ji));
            else if (rd) yes(i(0x1b,rd,0,rd,simm));
        }
        if (f == 2) yes(i(0x13,rd,0,0,simm));
        if (f == 3) {
            if (rd == 2) {
                uint32_t off = sext((c >> 12 & 1) * 512 + bits(c,4,3) * 128 + (c >> 5 & 1) * 64 +
                    (c >> 2 & 1) * 32 + (c >> 6 & 1) * 16, 10);
                if (off) yes(i(0x13,rd,0,rd,off));
            } else if (simm) yes((simm & 0xfffff) << 12 | rd << 7 | 0x37);
        }
        if (f == 4) {
            unsigned sub = bits(c,11,10), alu = bits(c,6,5);
            if (sub == 0 && (DUT_XLEN == 64 || sh < 32)) yes(i(0x13,a,5,a,sh));
            if (sub == 1 && (DUT_XLEN == 64 || sh < 32)) yes(i(0x13,a,5,a,1024 + sh));
            if (sub == 2) yes(i(0x13,a,7,a,simm));
            if (sub == 3 && !(c & 4096)) {
                if (alu == 0) yes(r(0x33,a,0,a,z,32));
                if (alu == 1) yes(r(0x33,a,4,a,z));
                if (alu == 2) yes(r(0x33,a,6,a,z));
                if (alu == 3) yes(r(0x33,a,7,a,z));
            }
            if (sub == 3 && (c & 4096) && DUT_XLEN == 64 && alu < 2)
                yes(r(0x3b,a,0,a,z,alu == 0 ? 32 : 0));
        }
        if (f == 5) yes(j(0,ji));
        if (f == 6) yes(b(0,a,bi));
        if (f == 7) yes(b(1,a,bi));
    }
    if (q == 2) {
        if (f == 0 && (DUT_XLEN == 64 || sh < 32)) yes(i(0x13,rd,1,rd,sh));
        if (f == 2 && rd) {
            unsigned off = bits(c,3,2) * 64 + (c >> 12 & 1) * 32 + bits(c,6,4) * 4;
            yes(i(3,rd,2,2,off));
        }
        if (f == 3 && DUT_XLEN == 64 && rd) {
            unsigned off = bits(c,4,2) * 64 + (c >> 12 & 1) * 32 + bits(c,6,5) * 8;
            yes(i(3,rd,3,2,off));
        }
        if (f == 4) {
            if (!rs2) {
                if (rd) yes(i(0x67,(c & 4096) ? 1 : 0,0,rd,0));
                else if (c & 4096) yes(0x00100073);
            } else yes(r(0x33,rd,0,(c & 4096) ? rd : 0,rs2));
        }
        if (f == 6) yes(s(2,2,rs2,bits(c,8,7) * 64 + bits(c,12,9) * 4));
        if (f == 7 && DUT_XLEN == 64) yes(s(3,2,rs2,bits(c,9,7) * 64 + bits(c,12,10) * 8));
    }
    return out;
}
int main(int argc, char **argv) { try {
    SFiveStageCompressed d; d.set_reset(0); unsigned legal = 0;
    bool mutate = argc > 1 && std::string(argv[1]) == "--wrong-expansion";
    for (unsigned c = 0; c < 65536; ++c) {
        auto expected = decode(c); if (mutate && c == 1) expected.value ^= 1;
        d.set_io$$instruction(c); d.step();
        if (bool(d.get_io$$legal()) != expected.legal || (expected.legal && d.get_io$$expanded() != expected.value)) {
            std::cerr << "C mismatch encoding=0x" << std::hex << c << " expected=" << expected.value
                << " got=" << d.get_io$$expanded() << '\n';
            throw std::runtime_error("independent exhaustive C expansion oracle");
        }
        legal += expected.legal;
    }
    std::cout << "FIVE_STAGE_COMPRESSED_PASS xlen=" << DUT_XLEN << " encodings=65536 legal=" << legal
        << " hints_reserved_integer_only_immediates_registers=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
