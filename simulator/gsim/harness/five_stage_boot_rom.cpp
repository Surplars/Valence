#include "FiveStageBootRomHarness.h"
#include <array>
#include <fstream>
#include <random>
#include <optional>
#include <iostream>
#include <stdexcept>

static void need(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
struct RomRequest { uint64_t address, data; unsigned opcode, size, source, mask; };
struct RomReply { uint64_t data; unsigned opcode, size, source; bool error; };
int main(int argc, char **argv) { try {
    need(argc >= 2, "ROM hex path required");
    SFiveStageBootRomHarness d; std::array<uint64_t, 512> words{};
    std::ifstream file(argv[1]); need(bool(file), "missing ROM hex");
    d.set_reset(1); d.set_io$$port0$$a$$valid(0); d.set_io$$port1$$a$$valid(0);
    d.set_io$$initialize$$valid(1);
    for (unsigned n = 0; n < 512; ++n) {
        need(bool(file >> std::hex >> words[n]), "short ROM");
        d.set_io$$initialize$$bits$$index(n); d.set_io$$initialize$$bits$$data(words[n]); d.step();
    }
    d.set_io$$initialize$$valid(0); d.step(); d.step(); d.set_reset(0);
    std::array<std::optional<RomRequest>, 2> offers;
    std::array<std::optional<RomReply>, 2> replies;
    std::array<unsigned, 2> count{}, completed{};
    std::mt19937_64 rng{0x524f4d};
    bool negative = argc > 2;
    for (unsigned cycle = 0; cycle < 30000 && (completed[0] < 1200 || completed[1] < 1200); ++cycle) {
        std::array<bool, 2> ready;
        for (unsigned p = 0; p < 2; ++p) {
            if (!offers[p] && !replies[p] && count[p] < 1200) {
                unsigned size = rng() % 4;
                uint64_t address = 0x10000 + ((rng() % 4608) & ~((1U << size) - 1));
                if (count[p] < 512) { size = 3; address = 0x10000 + count[p] * 8; }
                else if (count[p] % 7 == 0) { size = 3; address = 0x10001 + rng() % 4096; }
                offers[p] = {address, rng(), unsigned(count[p] < 512 || rng() % 3 ? 4 : 1),
                    size, unsigned(rng() & 1), 255};
            }
            ready[p] = rng() % 4 == 0;
        }
#define DRIVE(P) { \
        auto r = offers[P].value_or(RomRequest{}); \
        d.set_io$$port##P##$$a$$valid(bool(offers[P])); \
        d.set_io$$port##P##$$a$$bits$$address(r.address); d.set_io$$port##P##$$a$$bits$$opcode(r.opcode); \
        d.set_io$$port##P##$$a$$bits$$size(r.size); d.set_io$$port##P##$$a$$bits$$source(r.source); \
        d.set_io$$port##P##$$a$$bits$$mask(r.mask); d.set_io$$port##P##$$a$$bits$$data(r.data); \
        d.set_io$$port##P##$$d$$ready(ready[P]); }
        DRIVE(0) DRIVE(1)
#undef DRIVE
        d.step();
#define CHECK(P) { \
        need(bool(d.get_io$$port##P##$$d$$valid()) == bool(replies[P]), "ROM response owner"); \
        if (replies[P]) { \
            auto r = *replies[P]; \
            need(d.get_io$$port##P##$$d$$bits$$data() == r.data && \
                d.get_io$$port##P##$$d$$bits$$source() == r.source && \
                d.get_io$$port##P##$$d$$bits$$size() == r.size && \
                d.get_io$$port##P##$$d$$bits$$opcode() == r.opcode && \
                bool(d.get_io$$port##P##$$d$$bits$$denied()) == r.error, "ROM held reply/data/deny oracle"); \
            if (ready[P]) { replies[P].reset(); ++completed[P]; } \
        } \
        if (offers[P] && d.get_io$$port##P##$$a$$ready()) { \
            auto r = *offers[P]; bool legal = r.opcode == 4 && !(r.address % (1ULL << r.size)) && \
                r.address >= 0x10000 && \
                r.address + (1ULL << r.size) <= 0x11000; \
            uint64_t expected = legal ? words[(r.address - 0x10000) / 8] : 0; \
            if (negative && legal) expected ^= 1; \
            replies[P] = RomReply{expected, unsigned(r.opcode == 4 ? 1 : 0), r.size, r.source, !legal}; \
            offers[P].reset(); ++count[P]; \
        } }
        CHECK(0) CHECK(1)
#undef CHECK
    }
    need(completed[0] == 1200 && completed[1] == 1200, "ROM bounded completion");
    std::cout << "FIVE_STAGE_BOOT_ROM_PASS transactions=2400 ports=2 reads_writes_denied_backpressure=PASS\n";
    return 0;
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
