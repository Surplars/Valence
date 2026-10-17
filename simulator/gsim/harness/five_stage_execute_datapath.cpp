#include "I1ExecuteDatapathFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
#ifndef DUT_TIMING_CUTS
#define DUT_TIMING_CUTS 0
#endif

// Software semantic oracle: no decoded tables, shifts or masks imported from RTL.
constexpr uint64_t widthMask = DUT_XLEN == 64 ? UINT64_MAX : UINT64_C(0xffffffff);
static uint64_t signWord(uint64_t v) {
    return (v & UINT64_C(0x80000000)) ? (v | UINT64_C(0xffffffff00000000)) : (v & UINT64_C(0xffffffff));
}
static uint64_t arithmetic(uint64_t v, unsigned n) {
    const bool sign = (v >> (DUT_XLEN - 1)) & 1;
    uint64_t r = v >> n;
    if (sign && n) r |= (UINT64_MAX << (DUT_XLEN - n));
    return r & widthMask;
}
static uint64_t alu(unsigned op, bool word, uint64_t a, uint64_t b) {
    const unsigned amount = b & ((DUT_XLEN == 64 && !word) ? 63U : 31U);
    uint64_t rightSource = a;
    if (DUT_XLEN == 64 && word)
        rightSource = op == 7 ? signWord(a) : a & UINT64_C(0xffffffff);
    uint64_t r = 0;
    switch (op) {
    case 0: r = a + b; break;
    case 1: r = a - b; break;
    case 2: r = a << amount; break;
    case 3: r = (a ^ (UINT64_C(1) << (DUT_XLEN - 1))) < (b ^ (UINT64_C(1) << (DUT_XLEN - 1))); break;
    case 4: r = a < b; break;
    case 5: r = a ^ b; break;
    case 6: r = rightSource >> amount; break;
    case 7: r = arithmetic(rightSource, amount); break;
    case 8: r = a | b; break;
    case 9: r = a & b; break;
    default: r = 0; break;
    }
    if (DUT_XLEN == 64 && word) r = signWord(r);
    return r & widthMask;
}

int main(int argc, char **argv) { try {
    const bool wrong = argc == 2 && std::string(argv[1]) == "--wrong-result";
    SI1ExecuteDatapathFixture dut;
    dut.set_reset(0);
    unsigned checks = 0;
    auto test = [&](unsigned index, unsigned offers, unsigned op, bool word,
                    unsigned overrides, unsigned flags, std::array<uint64_t,6> values,
                    uint64_t pc, uint64_t immediate, std::array<uint64_t,4> other, unsigned available=63) {
        for (auto &v : values) v &= widthMask;
        for (auto &v : other) v &= widthMask;
        pc &= widthMask; immediate &= widthMask;
        dut.set_io$$index(index); dut.set_io$$offers(offers);
        dut.set_io$$available(available);
        dut.set_io$$value0(values[0]); dut.set_io$$value1(values[1]);
        dut.set_io$$value2(values[2]); dut.set_io$$value3(values[3]);
        dut.set_io$$value4(values[4]); dut.set_io$$value5(values[5]);
        dut.set_io$$usePc(overrides & 1); dut.set_io$$useRs1((overrides >> 1) & 1);
        dut.set_io$$useImmediate((overrides >> 2) & 1);
        dut.set_io$$pc(pc); dut.set_io$$immediate(immediate);
        dut.set_io$$operation(op); dut.set_io$$word(word); dut.set_io$$resultFlags(flags);
        dut.set_io$$other0(other[0]); dut.set_io$$other1(other[1]);
        dut.set_io$$other2(other[2]); dut.set_io$$other3(other[3]);
        dut.step();
        unsigned selected = 5;
        for (unsigned i=0;i<5;++i) if (offers & (1U << i)) { selected=i; break; }
        const unsigned wantedOwner = index ? 1U << selected : 0;
        const unsigned wantedMask = wantedOwner & available;
        const uint64_t operand = wantedMask ? values[selected] : 0;
        const uint64_t left = (overrides & 1) ? pc : ((overrides & 2) ? operand : 0);
        const uint64_t right = (overrides & 4) ? immediate : operand;
        const uint64_t expectedAlu = alu(op,word,left,right);
        unsigned chosenResult=4;
        for (unsigned i=0;i<4;++i) if (flags & (1U << i)) { chosenResult=i; break; }
        const uint64_t result = chosenResult==4 ? expectedAlu : other[chosenResult];
        const uint64_t actual = dut.get_io$$result() ^ uint64_t(wrong && checks==13);
        const uint64_t expectedSelectedAlu = DUT_TIMING_CUTS && chosenResult!=4 ? 0 : expectedAlu;
        if (dut.get_io$$ownerMask()!=wantedOwner || dut.get_io$$operandMask()!=wantedMask || dut.get_io$$operand()!=operand ||
            dut.get_io$$left()!=left || dut.get_io$$right()!=right || dut.get_io$$alu()!=expectedSelectedAlu ||
            dut.get_io$$resultMask()!=(1U << chosenResult) || actual!=result)
            throw std::runtime_error("independent EX operand/ALU/result oracle");
        ++checks;
    };
    std::mt19937_64 rng(UINT64_C(0x1e1b20261014));
    auto values = [&]() { std::array<uint64_t,6> v; for(auto &x:v)x=rng();return v; };
    auto other = [&]() { std::array<uint64_t,4> v; for(auto &x:v)x=rng();return v; };
    for (unsigned index : {0U,1U,31U}) for(unsigned offers=0;offers<32;++offers)
        for(unsigned op=0;op<16;++op) for(bool word:{false,true}) for(unsigned overrides=0;overrides<8;++overrides)
            test(index,offers,op,word,overrides,checks&15,values(),rng(),rng(),other());
    constexpr std::array<uint64_t,13> edges{0,1,2,31,32,63,64,UINT64_C(0x7fffffff),
        UINT64_C(0x80000000),UINT64_C(0xffffffff),UINT64_C(0x7fffffffffffffff),
        UINT64_C(0x8000000000000000),UINT64_MAX};
    for(auto a:edges) for(auto b:edges) for(unsigned op=0;op<16;++op) for(bool word:{false,true}) {
        auto v=values(); v[5]=a;
        test(1,0,op,word,6,checks&15,v,a,b,other());
    }
    for(unsigned i=0;i<8000;++i)
        test(rng()&31,rng()&31,rng()&15,rng()&1,rng()&7,rng()&15,values(),rng(),rng(),other());
    for(unsigned index : {0U,1U,31U}) for(unsigned offers=0;offers<32;++offers)
        for(unsigned available=0;available<64;++available)
            test(index,offers,rng()&15,rng()&1,rng()&7,rng()&15,values(),rng(),rng(),other(),available);
    std::cout<<"I1_EXECUTE_DATAPATH_PASS xlen="<<DUT_XLEN<<" timing_cuts="<<DUT_TIMING_CUTS
        <<" checks="<<checks<<" youngest_owner_blocks_fallback_x0_PC_immediate_word_shift_result_enable=PASS\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n';return 1; } }
