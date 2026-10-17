#include "I1AddressWindowFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
int main(int argc, char **argv) { try {
    using Wide = __uint128_t;
    constexpr Wide end = Wide(1) << DUT_XLEN;
    constexpr std::array<std::pair<Wide,Wide>,12> windows{{
        {0,0}, {0,4096}, {0x80010000,65536}, {1234,65537}, {end-4096,4096}, {0,end},
        {0x2345,1}, {0x80200000,DUT_XLEN==64 ? Wide(1)<<31 : Wide(0x7fe00000)},
        {DUT_XLEN==64 ? Wide(0xfffffffd) : end-7,7}, {0x10000007,33}, {4095,2}, {0xff00,0xabcdef}
    }};
    const bool inject = argc==2 && std::string(argv[1])=="--wrong-window";
    SI1AddressWindowFixture dut;
    dut.set_reset(0);
    unsigned checks=0;
    auto test=[&](uint64_t raw) {
        const uint64_t address=uint64_t(Wide(raw)&(end-1));
        unsigned wanted=0;
        for(unsigned i=0;i<windows.size();++i) {
            const auto [base,bytes]=windows[i];
            if(Wide(address)>=base && Wide(address)<base+bytes) wanted|=1U<<i;
        }
        dut.set_io$$address(address);dut.step();
        const unsigned actual=dut.get_io$$hits()^unsigned(inject && checks==13);
        if(actual!=wanted) throw std::runtime_error("independent byte-window bounds oracle");
        ++checks;
    };
    for(const auto [base,bytes]:windows) for(int d=-2;d<=2;++d) {
        test(uint64_t(base+Wide(d)));test(uint64_t(base+bytes+Wide(d)));
    }
    std::mt19937_64 rng(0x1a14b2026);
    for(unsigned i=0;i<12000;++i) {
        const uint64_t value=rng();
        test(value);
        // Random low physical addresses, not just almost-always-denied XLEN noise.
        test(value&0x1ffffffffULL);
        test(0x80000000ULL+(value&0x3fffff));
    }
    std::cout<<"I1_ADDRESS_WINDOW_PASS xlen="<<DUT_XLEN<<" checks="<<checks
        <<" windows=12 empty_single_unaligned_full_width_above4G_boundary=PASS\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n';return 1; } }
