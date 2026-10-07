#include "MultiplyDivide.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include "muldiv_model.h"
static void check(bool ok, const char *message) { if (!ok) throw std::runtime_error(message); }
#ifndef REGISTERED_MULDIV_OPERANDS
#define REGISTERED_MULDIV_OPERANDS 0
#endif
static constexpr unsigned inputLatency=REGISTERED_MULDIV_OPERANDS;
int main(int argc,char** argv) {
    try {
        SMultiplyDivide d;
        const bool inject=argc==2 && std::string(argv[1])=="--inject-mismatch";
        d.set_io$$start$$valid(0); d.set_io$$start$$bits$$token$$index(0); d.set_io$$start$$bits$$token$$tag(0);
        d.set_io$$start$$bits$$pc(0); d.set_io$$start$$bits$$operation(0); d.set_io$$start$$bits$$word(0);
        d.set_io$$start$$bits$$left(0); d.set_io$$start$$bits$$right(0);
        d.set_io$$cancel(0); d.set_io$$complete$$ready(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        std::mt19937_64 rng(231064);
        uint64_t accepted = 0, completed = 0, cancelled = 0, held = 0;
        auto test = [&](unsigned op, bool word, uint64_t a, uint64_t b, unsigned kill = 0) {
            const unsigned latency = (op < 4 ? 6 : (word ? 34 : 66))+inputLatency, stalls = 1 + rng() % 7;
            const uint64_t tag = ++accepted, pc = 0x80000000 + 4 * tag;
            d.set_io$$start$$valid(1); d.set_io$$start$$bits$$operation(op); d.set_io$$start$$bits$$word(word);
            d.set_io$$start$$bits$$left(a); d.set_io$$start$$bits$$right(b);
            d.set_io$$start$$bits$$token$$index(tag % 32); d.set_io$$start$$bits$$token$$tag(tag);
            d.set_io$$start$$bits$$pc(pc); d.set_io$$cancel(0); d.set_io$$complete$$ready(0); d.step();
            check(d.get_io$$start$$ready(), "idle unit rejected request");
            const uint64_t expected = multiplyDivide(op, word, a, b);
            d.set_io$$start$$valid(0);
            // Poison input payload after handshake; computation must use its saved ownership/operands.
            d.set_io$$start$$bits$$left(~a); d.set_io$$start$$bits$$right(~b);
            for (unsigned cycle = 1; cycle <= latency + stalls; ++cycle) {
                d.set_io$$cancel(kill == cycle); d.set_io$$complete$$ready(cycle == latency + stalls); d.step();
                check(!d.get_io$$start$$ready() && d.get_io$$busy(), "busy unit accepted another operation");
                check(d.get_io$$owner$$tag() == tag, "owner changed while busy");
                check(bool(d.get_io$$complete$$valid()) == (cycle >= latency), "arithmetic response latency");
                if (d.get_io$$complete$$valid()) {
                    check((d.get_io$$complete$$bits$$data() ^ uint64_t(inject)) == expected, "arithmetic mismatch");
                    check(d.get_io$$complete$$bits$$token$$tag() == tag && d.get_io$$complete$$bits$$token$$index() == tag % 32,
                          "completion token mismatch");
                    check(d.get_io$$complete$$bits$$nextPc() == pc + 4 && !d.get_io$$complete$$bits$$exception(), "completion metadata");
                    if (cycle < latency + stalls) ++held;
                }
                if (kill == cycle) { ++cancelled; break; }
            }
            if (!kill) ++completed;
            d.set_io$$cancel(0); d.set_io$$complete$$ready(0); d.step();
            check(d.get_io$$start$$ready() && !d.get_io$$busy() && !d.get_io$$complete$$valid(), "cancel/complete did not release owner");
        };
        const std::array<uint64_t, 10> values{0,1,2,UINT64_MAX,UINT64_C(0x8000000000000000),UINT64_C(0x7fffffffffffffff),
            UINT64_C(0x80000000),UINT64_C(0xffffffff),UINT64_C(0xffffffff00000000),UINT64_C(0x123456789abcdef0)};
        for (bool word : {false,true}) for (unsigned op = 0; op < 8; ++op) {
            if (word && op > 0 && op < 4) continue;
            for (auto a : values) for (auto b : values) test(op,word,a,b);
            for (unsigned i=0; i<200; ++i) test(op,word,rng(),rng());
            const unsigned latency = (op < 4 ? 6 : (word ? 34 : 66))+inputLatency;
            for (unsigned kill : {1U, latency / 2, latency}) test(op,word,rng(),rng(),kill);
        }
        check(completed == 3900 && cancelled == 39 && held > 10000, "unit coverage");
        std::cout << "GSIM MultiplyDivide: PASS completed=" << completed << " cancelled=" << cancelled << " held=" << held
                  << " latencyMul="<<6+inputLatency<<" latencyDiv64="<<66+inputLatency
                  <<" latencyDiv32="<<34+inputLatency<<"\n";
    } catch (const std::exception &e) { std::cerr << "GSIM MultiplyDivide: FAIL " << e.what() << '\n'; return 1; }
}
