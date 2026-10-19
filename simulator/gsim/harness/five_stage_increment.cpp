#include "I1IncrementTimingFixture.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
int main(int argc,char**argv)try {
    SI1IncrementTimingFixture d;
    bool wrong=argc>1&&std::string(argv[1])=="--wrong-carry";
    constexpr uint64_t mask=DUT_XLEN==32?0xffffffffULL:~uint64_t{0};
    unsigned checks=0;
    auto check=[&](uint64_t x) {
        x&=mask;d.set_io$$pc(x);d.set_reset(0);d.step();
        uint64_t p2=(x+2)&mask,p4=(x+4)&mask;
        if(wrong)p4^=uint64_t{1}<<16;
        if(d.get_io$$plusTwo()!=p2||d.get_io$$plusFour()!=p4)
            throw std::runtime_error("independent fixed PC increment wrap/carry oracle");
        ++checks;
    };
    for(unsigned bit=0;bit<DUT_XLEN;++bit)
        for(unsigned low=0;low<16;++low) {
            uint64_t edge=uint64_t{1}<<bit;
            check(edge-low);check(edge+low);check(mask-(edge-low));
        }
    std::mt19937_64 rng(0x5032433450524546ULL);
    for(unsigned i=0;i<12000;++i)check(rng());
    std::cout<<"I1_PC_INCREMENT_PASS xlen="<<DUT_XLEN<<" checks="<<checks<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
