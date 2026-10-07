#include "ReturnStackGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

struct Commit { bool valid; uint64_t pc; uint32_t inst; unsigned rd; bool writes; uint64_t data; };
enum Action { none, push, pop };
// Independently enumerate software encodings. Do not import DUT decode tables.
static Action action(const Commit &c) {
    if (!c.valid) return none;
    unsigned op = c.inst & 127, rd = c.inst >> 7 & 31, rs = c.inst >> 15 & 31;
    if ((c.inst & 3) != 3) {
        const unsigned half = c.inst & 65535, reg = half >> 7 & 31;
        if ((half & 0xe07f) != 0x8002 || !reg) return none;
        if (half & 0x1000) return push;
        return (reg == 1 || reg == 5) ? pop : none;
    }
    if ((c.rd == 1 || c.rd == 5) && c.writes && (op == 0x6f || op == 0x67)) return push;
    if (op == 0x67 && !rd && (rs == 1 || rs == 5) && !(c.inst >> 20) && !(c.inst & 0x7000)) return pop;
    return none;
}
int main(int argc, char **argv) { try {
    const bool inject = argc == 2 && std::string_view(argv[1]) == "--inject-mismatch";
    SReturnStackGsim d;
    std::mt19937_64 rng(0x20261001a5ULL);
    std::array<uint64_t, 8> ring{};
    unsigned pointer = 0, count = 0, pushes = 0, pops = 0, full = 0, emptyPop = 0, mixed = 0, checked = 0;
    auto drive = [&](const Commit &a, const Commit &b) {
        d.set_io$$commit0$$valid(a.valid); d.set_io$$commit0$$bits$$pc(a.pc);
        d.set_io$$commit0$$bits$$instruction(a.inst); d.set_io$$commit0$$bits$$rd(a.rd);
        d.set_io$$commit0$$bits$$writesRd(a.writes); d.set_io$$commit0$$bits$$data(a.data);
        d.set_io$$commit1$$valid(b.valid); d.set_io$$commit1$$bits$$pc(b.pc);
        d.set_io$$commit1$$bits$$instruction(b.inst); d.set_io$$commit1$$bits$$rd(b.rd);
        d.set_io$$commit1$$bits$$writesRd(b.writes); d.set_io$$commit1$$bits$$data(b.data);
    };
    auto reset = [&] { drive({}, {}); d.set_reset(1); d.step(); d.step(); d.set_reset(0); pointer = count = 0; };
    reset();
    for (unsigned cycle = 0; cycle < 20000; ++cycle) {
        if (cycle && cycle % 5000 == 0) reset();
        std::array<Commit, 2> packet;
        for (unsigned lane = 0; lane < 2; ++lane) {
            unsigned kind = cycle < 20 ? 0 : cycle < 40 ? 2 : rng() % 12;
            unsigned rs = (rng() & 1) ? 1 : 5, rd = (rng() & 1) ? 1 : 5;
            uint32_t inst;
            switch (kind) {
            case 0: inst = 0x6f | rd << 7; break;                 // JAL link x1/x5
            case 1: inst = 0x67 | rd << 7 | 7 << 15; break;       // JALR call
            case 2: inst = 0x67 | rs << 15; rd = 0; break;        // regular return
            case 3: inst = 0x9002 | 7 << 7; rd = 1; break;        // C.JALR
            case 4: inst = 0x8002 | rs << 7; rd = 0; break;       // C.JR return
            case 5: inst = 0x8002 | 7 << 7; rd = 0; break;        // non-link C.JR
            case 6: inst = 0x9002; rd = 0; break;                // C.EBREAK, not call
            case 7: inst = 0x6f; rd = 0; break;                  // J, no link
            case 8: inst = 0x67 | rs << 15 | 4 << 20; rd = 0; break; // offset JALR, not return
            case 9: inst = 0x00100093; rd = 1; break;            // ordinary rd=x1
            case 10: inst = 0x8086; rd = 1; break;               // C.MV, not control
            default: inst = 0x00600067; rd = 0; break;
            }
            packet[lane] = {cycle < 40 || rng() % 4 != 0, rng() & ~UINT64_C(1), inst, rd,
                            bool(rd && (cycle < 40 || rng() % 5 != 0)), rng()};
        }
        drive(packet[0], packet[1]); d.step();
        // step exposes pre-edge outputs, then advances sequential state.
        unsigned actual = d.get_io$$occupancy();
        uint64_t target = d.get_io$$target();
        if (inject && count) target ^= 1;
        if (actual != count || bool(d.get_io$$available()) != bool(count) ||
            (count && target != ring[(pointer + 7) % 8]))
            throw std::runtime_error("return stack oracle mismatch");
        Action first = action(packet[0]), second = action(packet[1]);
        mixed += first != none && second != none && first != second;
        for (const auto &c : packet) {
            switch (action(c)) {
            case push:
                full += count == 8;
                ring[pointer] = c.pc + ((c.inst & 3) == 3 ? 4 : 2);
                pointer = (pointer + 1) % 8;
                if (count < 8) ++count;
                ++pushes; break;
            case pop:
                emptyPop += !count;
                if (count) { pointer = (pointer + 7) % 8; --count; ++pops; }
                break;
            default: break;
            }
        }
        ++checked;
    }
    if (!full || !emptyPop || !mixed || !pushes || !pops) throw std::runtime_error("return stack coverage incomplete");
    std::cout << "GSIM retirement RAS: PASS cycles=" << checked << " pushes=" << pushes << " pops=" << pops
              << " overwrite=" << full << " empty_pop=" << emptyPop << " mixed_order=" << mixed
              << " resets=4 poisoned_completion_data=40000\n";
} catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; } }
