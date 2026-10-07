#include "FpgaFetchGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

using Wide = unsigned __int128;
static bool denied(uint64_t address, unsigned cfg, uint64_t encoded, unsigned priv) {
    // Independent interval/permission oracle for entry zero. The full multi-entry
    // first-overlap priority is covered separately by pmp_checker.cpp.
    unsigned kind = (cfg >> 3) & 3;
    Wide low = 0, high = 0;
    bool active = kind != 0;
    if (kind == 1) { high = Wide(encoded) * 4; active = high != 0; }
    if (kind == 2) { low = Wide(encoded) * 4; high = low + 4; }
    if (kind == 3) {
        unsigned ones = 0;
        while (ones < 54 && ((encoded >> ones) & 1)) ++ones;
        // PMP addresses have 54 encoded bits / 56 implemented physical bits.
        Wide bytes = Wide(1) << (ones >= 53 ? 56 : ones + 3);
        low = (Wide(encoded) * 4) & ~(bytes - 1);
        high = low + bytes;
    }
    Wide start = address, end = start + 4;
    if (!active || start >= high || end <= low) return priv != 3;
    return start < low || end > high || !((priv == 3 && !(cfg & 128)) || (cfg & 4));
}

int main(int argc, char **argv) { try {
    bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SFpgaFetchGsim d;
    uint64_t checked = 0, held = 0, stale = 0;
    auto one = [&](uint64_t pc, unsigned cfg, uint64_t addr, unsigned priv) {
        d.set_io$$write(0); d.set_io$$writeIndex(0); d.set_io$$writeData(0);
        d.set_io$$rom$$request$$valid(0); d.set_io$$rom$$request$$bits(0);
        d.set_io$$rom$$requestMask(3); d.set_io$$rom$$response$$ready(1);
        d.set_io$$pc(pc); d.set_io$$enable(0); d.set_io$$invalidate(0); d.set_io$$pause(0);
        d.set_io$$bootHold(1); d.set_io$$commitEnable(1);
        d.set_io$$pmpCfg0(cfg); d.set_io$$pmpAddr0(addr); d.set_io$$privilege(priv);
        d.set_io$$fetch$$request$$ready(0); d.set_io$$fetch$$response$$valid(0);
        d.set_io$$fetch$$response$$bits(0x0001000100010001ULL);
        d.set_io$$fetch$$responseError(0);
        d.set_reset(1); d.step(); d.set_reset(0); d.step();
        uint64_t base = pc & ~uint64_t(7);
        unsigned mask = 0;
        for (unsigned lane = 0; lane < 2; ++lane)
            if (!denied(base + lane * 4, cfg, addr, priv)) mask |= 1U << lane;
        if (inject && checked == 100) mask ^= 1;
        auto checkHeld = [&] {
            if (!d.get_io$$fetch$$request$$valid() || d.get_io$$fetch$$request$$bits() != base ||
                d.get_io$$fetch$$requestMask() != mask)
                throw std::runtime_error("fetch PMP mask oracle mismatch");
        };
        d.set_io$$enable(1); d.step(); checkHeld();
        // A permission/context/PC change under backpressure must NOT rewrite
        // the already-presented transaction, even when it is invalidated.
        d.set_io$$pc(pc ^ 0x100); d.set_io$$pmpCfg0(cfg ^ 0x84);
        d.set_io$$privilege(priv == 3 ? 1 : 3); d.step(); checkHeld(); ++held;
        d.set_io$$invalidate(1); d.set_io$$pause(1); d.step(); checkHeld();
        d.set_io$$fetch$$request$$ready(1); d.step(); checkHeld();
        d.set_io$$fetch$$response$$valid(1); d.step();
        if (d.get_io$$instruction0$$valid() || d.get_io$$instruction1$$valid())
            throw std::runtime_error("stale fetch response escaped invalidation");
        ++checked; ++stale;
    };
    for (unsigned kind = 0; kind < 4; ++kind)
        for (unsigned lock : {0U, 128U})
            for (unsigned permissions : {0U, 1U, 3U, 4U, 5U, 7U})
                for (unsigned priv : {0U, 1U, 3U})
                    for (uint64_t pc : {0xffcULL, 0x1000ULL, 0x1004ULL, 0x1008ULL,
                                        0xfffffffffffffffcULL, 0x100000000000000ULL}) {
                        uint64_t addr = kind == 1 ? 0x402 : kind == 2 ? 0x401 : 0x403;
                        one(pc, (kind << 3) | lock | permissions, addr, priv);
                    }
    std::mt19937_64 rng(0x20261002f0ULL);
    for (uint64_t addr : {(uint64_t(1) << 53) - 1, (uint64_t(1) << 54) - 1})
        for (unsigned priv : {0U, 1U, 3U})
            for (unsigned cfg : {0x18U, 0x1cU, 0x98U, 0x9cU})
                for (uint64_t pc : {(uint64_t(1) << 56) - 4, uint64_t(1) << 56, UINT64_MAX - 3})
                    one(pc, cfg, addr, priv);
    for (unsigned i = 0; i < 1000; ++i) {
        uint64_t pc = (i % 4 == 0 ? uint64_t(1) << 56 : 0x1000) + (rng() & 0x3fe);
        unsigned cfg = rng() & 0x9f, priv = i % 3 == 0 ? 3 : i % 2;
        uint64_t addr = (pc >> 2) ^ (rng() & 15);
        one(pc, cfg, addr & ((uint64_t(1) << 54) - 1), priv);
    }
    std::cout << "GSIM fetch PMP mask: PASS vectors=" << checked << " held_context_changes=" << held
              << " invalidated_responses=" << stale << '\n';
#ifdef RAW_FETCH_PRESENCE
    // An unlocked, INVALID request retains the early next-packet payload when
    // invalidation arrives. This is not permission to consume stale instructions:
    // every instruction-valid and new request-valid must still be suppressed.
    constexpr uint64_t base = 0x80000000ULL;
    d.set_io$$pc(base); d.set_io$$enable(0); d.set_io$$invalidate(0); d.set_io$$pause(0);
    d.set_io$$pmpCfg0(0); d.set_io$$pmpAddr0(0); d.set_io$$privilege(3);
    d.set_io$$fetch$$request$$ready(1); d.set_io$$fetch$$response$$valid(0);
    d.set_reset(1); d.step(); d.set_reset(0); d.step();
    d.set_io$$enable(1); d.step();
    if (!d.get_io$$fetch$$request$$valid() || d.get_io$$fetch$$request$$bits() != base)
        throw std::runtime_error("raw fetch initial request mismatch");
    d.set_io$$fetch$$response$$valid(1); d.step();
    if (!d.get_io$$fetch$$request$$valid() || d.get_io$$fetch$$request$$bits() != base + 8)
        throw std::runtime_error("raw fetch prefetch request mismatch");
    d.step();
    d.set_io$$fetch$$response$$valid(0); d.set_io$$enable(0);
    d.set_io$$fetch$$request$$ready(0); d.step();
    d.set_io$$pc(base + 8); d.step();
    if (!d.get_io$$quiescent() || d.get_io$$fetch$$request$$valid() ||
        d.get_io$$fetch$$request$$bits() != base + 16)
        throw std::runtime_error("raw fetch cached next-packet fixture mismatch");
    d.set_io$$invalidate(1); d.step();
    if (d.get_io$$fetch$$request$$valid() || d.get_io$$fetch$$request$$bits() != base + 16 ||
        d.get_io$$instruction0$$valid() || d.get_io$$instruction1$$valid())
        throw std::runtime_error("raw fetch invalidation payload isolation mismatch");
    d.set_io$$invalidate(0); d.set_io$$enable(1); d.step();
    if (!d.get_io$$fetch$$request$$valid() || d.get_io$$fetch$$request$$bits() != base + 8 ||
        d.get_io$$instruction0$$valid() || d.get_io$$instruction1$$valid())
        throw std::runtime_error("raw fetch post-invalidation refetch mismatch");
    std::cout << "GSIM raw fetch request payload isolation: PASS invalid/kill/refetch\n";
#endif
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
