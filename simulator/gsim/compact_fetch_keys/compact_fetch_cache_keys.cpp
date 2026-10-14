#include "CompactFetchCacheKeysGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#ifndef CACHE_SETS
#define CACHE_SETS 16
#endif
static constexpr unsigned Sets = CACHE_SETS;
static constexpr unsigned tagLow = 3 + __builtin_ctz(Sets);
static void check(bool ok, const std::string &msg) { if (!ok) throw std::runtime_error(msg); }
int main() {
    try {
        SCompactFetchCacheKeysGsim dut;
        std::array<uint64_t, Sets * 2> fullBases{};
        std::array<bool, Sets * 2> initialized{};
        std::array<std::array<std::array<unsigned, 3>, 2>, Sets> coverage{};
        unsigned writes = 0, reads = 0, held = 0;
        dut.set_io$$writeEnable(0); dut.set_io$$writeAddress(0); dut.set_io$$writeWay(0);
        dut.set_io$$writeMinusHigh(0); dut.set_io$$readSlot(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        auto read = [&](unsigned slot) {
            dut.set_io$$writeEnable(0); dut.set_io$$readSlot(slot); dut.step();
            if (!initialized[slot]) return;
            const uint64_t actual[] = {dut.get_io$$key0(), dut.get_io$$key1(), dut.get_io$$key2()};
            for (unsigned off = 0; off < 3; ++off) {
                // Store one full original address. Modulo uint64 subtraction, not high-tag reconstruction.
                check(actual[off] == fullBases[slot] - 8 * off,
                      "COMPACT_KEYS_FULL64_ORACLE slot=" + std::to_string(slot) + " offset=" + std::to_string(off));
                ++coverage[slot / 2][slot % 2][off]; ++reads;
            }
        };
        auto write = [&](uint64_t base, unsigned way) {
            check(!(base & 7), "test packet alignment");
            const unsigned slot = ((base >> 3) % Sets) * 2 + way;
            dut.set_io$$writeEnable(1); dut.set_io$$writeAddress(base); dut.set_io$$writeWay(way);
            dut.set_io$$writeMinusHigh((base - UINT64_C(16)) >> tagLow); dut.step();
            fullBases[slot] = base; initialized[slot] = true; ++writes;
            for (unsigned row = 0; row < Sets * 2; ++row) read(row);
            // Changed inactive payload must not update any row.
            dut.set_io$$writeAddress(base ^ UINT64_C(0xfeed100000000080));
            dut.set_io$$writeMinusHigh(0); dut.set_io$$writeWay(!way);
            for (unsigned row = 0; row < Sets * 2; ++row) { read(row); ++held; }
        };
        const uint64_t regionMask = ~((UINT64_C(1) << tagLow) - 1);
        const std::array<uint64_t, 9> roots = {0, UINT64_C(0x80000000), UINT64_C(0x100000000),
            UINT64_C(1) << 32, UINT64_C(1) << 54, UINT64_C(1) << 56, UINT64_C(1) << 63,
            UINT64_MAX & regionMask, (UINT64_MAX & regionMask) - (UINT64_C(1) << tagLow)};
        for (auto root : roots) for (unsigned way = 0; way < 2; ++way)
            for (unsigned set = 0; set < Sets; ++set) write((root & regionMask) + set * 8, way);
        std::mt19937_64 rng(0x465443484b455953ULL);
        for (unsigned n = 0; n < 800; ++n) write(rng() & ~UINT64_C(7), rng() & 1);
        for (unsigned set = 0; set < Sets; ++set) for (unsigned way = 0; way < 2; ++way)
            for (unsigned off = 0; off < 3; ++off) check(coverage[set][way][off] != 0, "missing set/way/offset");
        std::cout << "COMPACT_FETCH_KEYS_FULL64_PASS sets=" << Sets << " writes=" << writes
                  << " reads=" << reads << " inactive_capture_checks=" << held
                  << " all_set_way_offsets=1 wrap=1 top_address=1\n";
    } catch (const std::exception &e) { std::cerr << "COMPACT_FETCH_KEYS_FAIL " << e.what() << '\n'; return 1; }
}
