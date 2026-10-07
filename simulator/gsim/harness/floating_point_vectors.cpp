// Independent reference: Berkeley SoftFloat, never DUT/HardFloat calculations.
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
extern "C" {
#include "softfloat.h"
}
static uint64_t box(uint32_t x) { return 0xffffffff00000000ULL | x; }
static uint32_t operand(uint64_t x) { return x>>32==0xffffffffULL?uint32_t(x):0x7fc00000; }
struct Answer {uint64_t value;unsigned flags;};
static Answer reference(uint64_t a,uint64_t b,bool sub,unsigned rm) {
    softfloat_roundingMode=rm;softfloat_detectTininess=softfloat_tininess_afterRounding;softfloat_exceptionFlags=0;
    const float32_t left{operand(a)},right{operand(b)};
    uint32_t result=(sub?f32_sub(left,right):f32_add(left,right)).v;
    if((result&0x7fffffffU)>0x7f800000U) result=0x7fc00000;
    unsigned f=softfloat_exceptionFlags;
    return {box(result),unsigned(bool(f&softfloat_flag_invalid))*16+
        unsigned(bool(f&softfloat_flag_infinite))*8+unsigned(bool(f&softfloat_flag_overflow))*4+
        unsigned(bool(f&softfloat_flag_underflow))*2+unsigned(bool(f&softfloat_flag_inexact))};
}
int main(int argc,char** argv) {try {
    if(argc!=2) throw std::runtime_error("output path required");
    auto anchor=[](uint64_t a,uint64_t b,bool sub,unsigned rm,uint32_t expected,unsigned flags) {
        auto x=reference(a,b,sub,rm);
        if(x.value!=box(expected)||x.flags!=flags) throw std::runtime_error("SoftFloat known-answer anchor failed");
    };
    anchor(box(0x3f800000),box(0x33800000),false,0,0x3f800000,1); // exact half-ulp
    anchor(box(0x3f800000),box(0x33800000),false,4,0x3f800001,1);
    anchor(box(1),box(1),false,0,2,0);
    anchor(box(0x7f800000),box(0x7f800000),true,0,0x7fc00000,16);
    anchor(box(0x7fc12345),box(0x3f800000),false,0,0x7fc00000,0);
    anchor(box(0x7f800001),box(0x3f800000),false,0,0x7fc00000,16);
    anchor(box(0x7f7fffff),box(0x7f7fffff),false,0,0x7f800000,5);
    anchor(box(0x7f7fffff),box(0x7f7fffff),false,1,0x7f7fffff,5);
    anchor(0x123456007f800001ULL,box(0x3f800000),false,0,0x7fc00000,0);
    anchor(box(0x3f800000),box(0x3f800000),true,2,0x80000000,0);
    const std::array<uint32_t,22> edge={0,0x80000000,1,0x80000001,0x007fffff,0x807fffff,
        0x00800000,0x80800000,0x3f800000,0xbf800000,0x3f800001,0x3f7fffff,0x33800000,
        0xb3800000,0x7f7fffff,0xff7fffff,0x7f800000,0xff800000,0x7f800001,0xff800001,
        0x7fc12345,0xffc12345};
    std::ofstream out(argv[1]);if(!out) throw std::runtime_error("cannot write vector file");
    uint64_t count=0;unsigned seenFlags=0;std::array<unsigned,5> modes{};
    auto emit=[&](uint64_t a,uint64_t b,bool sub,unsigned rm) {
        auto r=reference(a,b,sub,rm);++count;++modes[rm];seenFlags|=r.flags;
        out<<std::hex<<a<<' '<<b<<' '<<sub<<' '<<rm<<' '<<r.value<<' '<<r.flags<<'\n';
    };
    for(unsigned rm=0;rm<5;++rm) for(unsigned sub=0;sub<2;++sub)
        for(auto a:edge) for(auto b:edge) emit(box(a),box(b),sub,rm);
    std::mt19937_64 random(0xadd5f20261003ULL);
    for(unsigned i=0;i<30000;++i) {
        uint32_t a=random(),b=random();
        if(i%4==0) b=a^0x80000000U; // exact/near cancellation
        if(i%4==1) b=(a&0xff800000U)|(b&0x007fffffU); // close magnitudes
        if(i%4==2) {a&=0x807fffffU;b&=0x807fffffU;} // subnormal inputs
        emit(i%29?box(a):uint64_t(a),i%31?box(b):uint64_t(b),i%2,i%5);
    }
    out.close();if(!out) throw std::runtime_error("vector write failed");
    if(seenFlags!=21) throw std::runtime_error("missing NV/OF/NX or impossible UF/DZ in add/sub");
    std::cout<<"SOFTFLOAT_VECTORS_PASS anchors=10 cases="<<count<<" flags_seen="<<seenFlags<<" modes=5\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}}
