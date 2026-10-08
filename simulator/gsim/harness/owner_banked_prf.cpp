#include "OwnerBankedPrfGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#ifndef PHYSICAL_REGS
#define PHYSICAL_REGS 48
#endif
int main(int argc, char** argv) { try {
    const std::string_view mode = argc == 2 ? argv[1] : "";
    const bool inject = mode == "--inject-mismatch";
    const bool badWrite = mode == "--invalid-write";
    const bool wrongPriority = mode == "--wrong-priority";
    SOwnerBankedPrfGsim d;
    d.set_select(PHYSICAL_REGS == 48 ? 0 : (PHYSICAL_REGS == 64 ? 1 : 2));
    std::array<uint64_t, PHYSICAL_REGS> expected{};
    unsigned width = 0;
    while ((1u << width) < PHYSICAL_REGS) ++width;
    const unsigned mask = (1u << width) - 1;
    std::mt19937_64 random(0x72616d6f776e6572ULL);
    uint64_t checks = 0, collisions = 0, zeroWrites = 0, disabledPoison = 0, resets = 0;
    auto tick = [&](bool reset, bool v0, unsigned a0, uint64_t w0,
                    bool v1, unsigned a1, uint64_t w1, std::array<unsigned,4> reads) {
        d.set_reset(reset); d.set_io$$valid0(v0); d.set_io$$valid1(v1);
        d.set_io$$address0(a0); d.set_io$$address1(a1);
        d.set_io$$word0(w0); d.set_io$$word1(w1);
        d.set_io$$read0(reads[0]); d.set_io$$read1(reads[1]);
        d.set_io$$read2(reads[2]); d.set_io$$read3(reads[3]);
        d.step();
        const std::array<uint64_t,4> legacy{d.get_io$$legacy0(),d.get_io$$legacy1(),d.get_io$$legacy2(),d.get_io$$legacy3()};
        std::array<uint64_t,4> actual{d.get_io$$result0(),d.get_io$$result1(),d.get_io$$result2(),d.get_io$$result3()};
        if (!reset) {
            if (inject && collisions && reads[0] > 0 && reads[0] < PHYSICAL_REGS && expected[reads[0]] != 0) actual[0] ^= 1;
            for (unsigned p=0;p<4;++p) {
                const auto want = reads[p] < PHYSICAL_REGS ? expected[reads[p]] : 0;
                if (actual[p] != want || legacy[p] != want)
                    throw std::runtime_error("PRF independent data oracle mismatch");
            }
            ++checks;
        }
        // Model ordinary architectural words, not bank contents or owner bits.
        if (reset) { expected.fill(0); ++resets; }
        else {
            if (v0 && a0 && a0 < PHYSICAL_REGS) expected[a0] = w0;
            if (v1 && a1 && a1 < PHYSICAL_REGS) expected[a1] = w1;
            if (wrongPriority && v0 && v1 && a0 == a1 && a0) expected[a0] = w0;
            collisions += v0 && v1 && a0 == a1 && a0 != 0;
            zeroWrites += (v0 && !a0) + (v1 && !a1);
            disabledPoison += (!v0 && a0 >= PHYSICAL_REGS) + (!v1 && a1 >= PHYSICAL_REGS);
        }
    };
    tick(true,false,mask,0,false,mask,0,{0,1,2,3});
    tick(true,false,mask,0,false,mask,0,{0,1,2,3});
    for (unsigned a=0; a<=mask; ++a) tick(false,false,mask,0,false,mask,0,{a,a,a,a});
    if (badWrite) {
        if (mask < PHYSICAL_REGS) throw std::runtime_error("invalid-address negative requires non-power-of-two depth");
        tick(false,true,PHYSICAL_REGS,1,false,0,0,{0,0,0,0});
        throw std::runtime_error("invalid write was not rejected by DUT");
    }
    for (unsigned a=0;a<PHYSICAL_REGS;++a) {
        tick(false,true,a,0x1111000000000000ULL+a,true,a,0xeeee000000000000ULL+a,{a,0,a,a});
        tick(false,false,mask,0,false,mask,0,{a,a,0,a});
        // Alternate bank ownership on consecutive cycles at the same address.
        for (unsigned i=0;i<8;++i)
            tick(false,i%2==0,a,random(),i%2==1,a,random(),{a,a,0,a});
    }
    for (unsigned n=0;n<16000;++n) {
        const unsigned a0=random()%PHYSICAL_REGS, a1=n%5 ? random()%PHYSICAL_REGS:a0;
        const bool v0=n%7!=0, v1=n%11!=0;
        std::array<unsigned,4> read{a0,a1,unsigned(random()&mask),unsigned(random()&mask)};
        tick(n%701==0,v0,v0?a0:mask,random(),v1,v1?a1:mask,random(),read);
    }
    tick(false,false,mask,0,false,mask,0,{0,1,2,3});
    if (!collisions || !zeroWrites || resets<3 || checks<10000 || (mask>=PHYSICAL_REGS && !disabledPoison))
        throw std::runtime_error("PRF directed coverage missing");
    std::cout << "PASS_PRF_DATA entries=" << PHYSICAL_REGS << " checks=" << checks
              << " collisions=" << collisions << " zeroWrites=" << zeroWrites
              << " disabledPoison=" << disabledPoison << " resets=" << resets << '\n';
    return 0;
} catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
