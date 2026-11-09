#include "I1LoadExtractHarness.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

int main(int argc,char **argv) { try {
    constexpr unsigned width=DUT_XLEN, bytes=width/8, sizeCode=width==64?3:2;
    constexpr uint64_t mask=width==64?~uint64_t(0):uint64_t(0xffffffff);
    const bool inject=argc==2 && std::string(argv[1])=="--inject";
    std::vector<uint64_t> words{0,mask,0x0123456789abcdefULL,0xfedcba9876543210ULL};
    for(unsigned i=0;i<bytes;++i) words.push_back(uint64_t(0x80)<<(8*i));
    std::mt19937_64 rng(0x20261104);
    for(unsigned i=0;i<1024;++i) words.push_back(rng());
    SI1LoadExtractHarness d;d.set_reset(0);
    uint64_t cases=0;
    for(uint64_t word:words) for(unsigned offset=0;offset<bytes;++offset)
        for(unsigned f=0;f<8;++f) for(bool direct:{false,true}) for(bool selected:{false,true}) {
            word&=mask;
            const uint64_t shifted=direct?word:word>>(offset*8);
            uint64_t expected=shifted;
            const unsigned size=f&3;
            if(!direct && size<sizeCode) {
                const unsigned bits=8U<<size;
                const uint64_t low=(uint64_t(1)<<bits)-1;
                expected=shifted&low;
                if(!(f&4) && (expected&(uint64_t(1)<<(bits-1)))) expected|=mask^low;
            }
            const uint64_t fallback=rng()&mask;
            if(!selected) expected=fallback;
            d.set_io$$data(word);d.set_io$$offset(offset);d.set_io$$funct3(f);d.set_io$$direct(direct);
            d.set_io$$fallback(fallback);d.set_io$$selected(selected);d.step();
            if(inject && !cases) expected^=1;
            if(d.get_io$$shifted()!=shifted || d.get_io$$loaded()!=expected)
                throw std::runtime_error("load extraction independent shift/mask/sign oracle mismatch");
            ++cases;
        }
    std::cout<<"I1_LOAD_EXTRACT_PASS width="<<width<<" cases="<<cases
        <<" all_offsets_formats_SC_direct_sign_zero_extension=PASS\n";
    return 0;
} catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;} }
