#include "NearbyWordRelationsGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#ifndef WORD_WIDTH
#error WORD_WIDTH must match generated model
#endif
#ifndef MAX_OFFSET
#error MAX_OFFSET must match generated model
#endif
static_assert(WORD_WIDTH >= 8 && WORD_WIDTH < 64 && MAX_OFFSET < 64);
static constexpr uint64_t mask=(uint64_t(1)<<WORD_WIDTH)-1;
int main(int argc,char **argv) {
    try {
        const bool inject=argc==2&&std::string(argv[1])=="--inject-mismatch";
        if(argc!=1&&!inject)throw std::runtime_error("usage: nearby_word [--inject-mismatch]");
        SNearbyWordRelationsGsim dut;dut.set_reset(1);dut.step();dut.set_reset(0);
        uint64_t checked=0;
        auto one=[&](uint64_t base,uint64_t bound) {
            base&=mask;bound&=mask;dut.set_io$$base(base);dut.set_io$$bound(bound);dut.step();
            uint64_t a=0,b=0;
            for(unsigned n=0;n<=MAX_OFFSET;++n){const uint64_t word=(base+n)&mask;a|=uint64_t(bound<=word)<<n;b|=uint64_t(word<=bound)<<n;}
            if(inject&&checked==0)a^=1;
            if(dut.get_io$$boundLeWord()!=a||dut.get_io$$wordLeBound()!=b)throw std::runtime_error("independent nearby-word ordering mismatch");
            checked+=MAX_OFFSET+1;
        };
        one(0,0);
        if constexpr(WORD_WIDTH<=8){
            for(uint64_t base=0;base<=mask;++base)for(uint64_t bound=0;bound<=mask;++bound)one(base,bound);
        } else {
            std::mt19937_64 rng(0x504d505348415245ULL);
            for(uint64_t center:std::array<uint64_t,8>{0ULL,4ULL,8ULL,64ULL,1ULL<<32,1ULL<<54,1ULL<<56,mask})
                for(int i=-256;i<=256;++i)for(int j=-16;j<=16;++j)one(center+uint64_t(i),center+uint64_t(i+j));
            for(unsigned i=0;i<250000;++i){const uint64_t base=rng()&mask;one(base,(i&1)?rng():(base+int64_t(rng()%513)-256));}
        }
        std::cout<<"NEARBY_WORD_PASS word_width="<<WORD_WIDTH<<" max_offset="<<MAX_OFFSET<<" comparisons="<<checked<<" latency=0\n";
        return 0;
    } catch(const std::exception&e){std::cerr<<"NEARBY_WORD_FAIL "<<e.what()<<"\n";return 1;}
}
