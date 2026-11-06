#include "I1SpinorTimingFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

static void need(bool ok) {
    if (!ok) throw std::runtime_error("independent Spinor timing algebra oracle mismatch");
}
int main(int argc, char **argv) { try {
    SI1SpinorTimingFixture d;
    const bool inject = argc > 1 && std::string(argv[1]) == "--inject";
    std::mt19937_64 random(0x2026110580ULL);
    for (unsigned sample = 0; sample < 65536; ++sample) {
        std::array<uint64_t, 5> a, b;
        for (auto &v : a) v = random();
        b = a;
        if (sample % 3) b[(sample % 320) / 64] ^= uint64_t(1) << (sample % 64);
        d.set_io$$left0(a[0]); d.set_io$$left1(a[1]); d.set_io$$left2(a[2]);
        d.set_io$$left3(a[3]); d.set_io$$left4(a[4]);
        d.set_io$$right0(b[0]); d.set_io$$right1(b[1]); d.set_io$$right2(b[2]);
        d.set_io$$right3(b[3]); d.set_io$$right4(b[4]);
        uint32_t i = uint32_t(random()) & 0xffff8f80U;
        i |= 0x7057U;
        // Visit all three source forms and every rd/rs1 combination.
        const unsigned rs1 = sample & 31, rd = (sample >> 5) & 31;
        i = (i & ~uint32_t(0x000f8f80)) | (rs1 << 15) | (rd << 7);
        if (sample % 3 == 0) i = (i & 0x01ffffffU) | 0x80000000U;
        if (sample % 3 == 1) i |= 0xc0000000U;
        if (sample % 3 == 2) i &= 0x7fffffffU;
        const uint64_t type = random(), avl = random();
        const uint8_t vl = uint8_t(random());
        d.set_io$$instruction(i); d.set_io$$scalarType(type);
        d.set_io$$sourceAvl(avl); d.set_io$$currentVl(vl); d.step();
        const bool same80 = a[0] == b[0] && uint16_t(a[1]) == uint16_t(b[1]);
        need(bool(d.get_io$$equal80()) == (same80 ^ inject));
        need(bool(d.get_io$$equal320()) == (a == b));
        const bool registerType = (i >> 25) == 0x40;
        const bool immediate = (i >> 30) == 3;
        const uint64_t expectedType = registerType ? type : (i >> 20) & (immediate ? 0x3ff : 0x7ff);
        const uint64_t expectedAvl = immediate ? rs1 : rs1 ? avl : rd ? UINT64_MAX : vl;
        need(d.get_io$$selectedType() == expectedType && d.get_io$$selectedAvl() == expectedAvl);
    }
    std::cout << "I1_SPINOR_TIMING_ALGEBRA_PASS cases=65536 equality80_320_every_bit_VSET_all_sources=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
