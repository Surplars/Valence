#include "AlignedMemoryDisjointGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

int main(int argc, char**) { try {
    SAlignedMemoryDisjointGsim dut;
    std::mt19937_64 random(0x56616c656e6365ULL);
    unsigned cases=0, overlaps=0, separated=0, misaligned=0;
    auto check = [&](uint64_t load, unsigned ls, uint64_t store, unsigned ss) {
        const unsigned lb=1U<<ls, sb=1U<<ss;
        const bool aligned=(load&(lb-1))==0 && (store&(sb-1))==0;
        // Independent, overflow-safe half-open byte intervals. Do not mirror
        // the DUT's beat/lane implementation or import its constants.
        const unsigned __int128 le=static_cast<unsigned __int128>(load)+lb;
        const unsigned __int128 se=static_cast<unsigned __int128>(store)+sb;
        const bool expected=aligned && (le<=store || se<=load);
        dut.set_io$$loadAddress(load); dut.set_io$$storeAddress(store);
        dut.set_io$$loadSize(ls); dut.set_io$$storeSize(ss); dut.step();
        const bool actual=bool(dut.get_io$$disjoint()) ^ bool(argc>1 && cases==20);
        if(actual!=expected) throw std::runtime_error("independent memory interval mismatch");
        ++cases;
        if(!aligned) ++misaligned; else if(expected) ++separated; else ++overlaps;
    };
    dut.set_reset(0);
    for(uint64_t base : {0ULL,0x801ffff8ULL,0x80200000ULL,0xa01ffff8ULL,
                         0xffffffffffffff00ULL,0xfffffffffffffff8ULL}) {
        for(unsigned ls=0;ls<4;++ls) for(unsigned ss=0;ss<4;++ss)
            for(unsigned l=0;l<16;++l) for(unsigned s=0;s<16;++s)
                check(base+l,ls,base+s,ss);
    }
    for(unsigned n=0;n<30000;++n) {
        uint64_t load=random(), store=n%2 ? random() : load+(random()%25)-12;
        unsigned ls=random()%4, ss=random()%4;
        if(n%3) {load &= ~uint64_t((1U<<ls)-1); store &= ~uint64_t((1U<<ss)-1);}
        check(load,ls,store,ss);
    }
    if(!overlaps || !separated || !misaligned) throw std::runtime_error("interval coverage missing");
    std::cout<<"ALIGNED_MEMORY_DISJOINT_PASS cases="<<cases<<" overlaps="<<overlaps
        <<" disjoint="<<separated<<" misaligned="<<misaligned<<'\n';
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;} }
