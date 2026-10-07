// Independent ISA oracle: pinned Berkeley SoftFloat, no HardFloat/DUT expressions.
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
extern "C" {
#include "softfloat.h"
}
struct Answer { uint64_t value; unsigned flags; };
static uint64_t box(uint32_t v) { return 0xffffffff00000000ULL | v; }
static uint32_t single(uint64_t v) { return v >> 32 == 0xffffffffULL ? uint32_t(v) : 0x7fc00000U; }
static bool nan(uint64_t v, bool d) {
    return d ? (v & 0x7fffffffffffffffULL) > 0x7ff0000000000000ULL
             : (uint32_t(v) & 0x7fffffffU) > 0x7f800000U;
}
static bool signaling(uint64_t v, bool d) {
    return nan(v,d) && !(v & (d ? 0x0008000000000000ULL : 0x00400000ULL));
}
static uint64_t canonical(uint64_t v, bool d) {
    if(nan(v,d)) v = d ? 0x7ff8000000000000ULL : 0x7fc00000U;
    return d ? v : box(uint32_t(v));
}
static unsigned flags() {
    unsigned f=softfloat_exceptionFlags;
    return unsigned(bool(f&softfloat_flag_invalid))*16 +
        unsigned(bool(f&softfloat_flag_infinite))*8 + unsigned(bool(f&softfloat_flag_overflow))*4 +
        unsigned(bool(f&softfloat_flag_underflow))*2 + unsigned(bool(f&softfloat_flag_inexact));
}
static uint64_t classification(uint64_t v, bool d) {
    const unsigned s = d ? 63 : 31, fraction = d ? 52 : 23;
    const uint64_t expMask = d ? 2047 : 255;
    const bool negative = (v >> s) & 1;
    const uint64_t exp = (v >> fraction) & expMask, frac = v & ((1ULL << fraction)-1);
    if(exp==expMask) return 1ULL << (frac ? (signaling(v,d)?8:9) : (negative?0:7));
    if(!exp) return 1ULL << (frac ? (negative?2:5) : (negative?3:4));
    return 1ULL << (negative?1:6);
}
// IDs are reference-tool data only: never imported by or generated from the DUT decoder.
static uint32_t instruction(unsigned id,bool d,unsigned rm) {
    static constexpr unsigned function[] = {
        0x00,0x04,0x08,0x0c,0x2c, 0,0,0,0,
        0x10,0x10,0x10,0x14,0x14,0x50,0x50,0x50,0x70,0x78,0x70,
        0x60,0x60,0x60,0x60,0x68,0x68,0x68,0x68,0x20 };
    unsigned f3=rm, rs2=2;
    if(id>=5 && id<=8) return (3U<<27)|(unsigned(d)<<25)|(2U<<20)|(1U<<15)|(rm<<12)|(3U<<7)|
        std::array<unsigned,4>{0x43,0x47,0x4b,0x4f}[id-5];
    if(id==4 || id==17 || id==18 || id==19) rs2=0;
    if(id>=9 && id<=11) f3=id-9;
    if(id>=12 && id<=13) f3=id-12;
    if(id>=14 && id<=16) f3=id-14;
    if(id==17) f3=1;
    if(id==18 || id==19) f3=0;
    if(id>=20 && id<=27) rs2=(id-20)%4;
    if(id==28) rs2=d?0:1;
    return ((function[id]+unsigned(d))<<25)|(rs2<<20)|(1U<<15)|(f3<<12)|(3U<<7)|0x53;
}
static Answer reference(unsigned id,bool d,unsigned rm,uint64_t rawA,uint64_t rawB,uint64_t rawC,uint64_t integer) {
    softfloat_roundingMode=rm; softfloat_detectTininess=softfloat_tininess_afterRounding; softfloat_exceptionFlags=0;
    const uint64_t a=d?rawA:single(rawA), b=d?rawB:single(rawB), c=d?rawC:single(rawC);
    const float32_t a32{uint32_t(a)},b32{uint32_t(b)},c32{uint32_t(c)};
    const float64_t a64{a},b64{b},c64{c};
    uint64_t result=0; bool numerical=false;
    switch(id) {
    case 0: result=d?f64_add(a64,b64).v:f32_add(a32,b32).v; numerical=true; break;
    case 1: result=d?f64_sub(a64,b64).v:f32_sub(a32,b32).v; numerical=true; break;
    case 2: result=d?f64_mul(a64,b64).v:f32_mul(a32,b32).v; numerical=true; break;
    case 3: result=d?f64_div(a64,b64).v:f32_div(a32,b32).v; numerical=true; break;
    case 4: result=d?f64_sqrt(a64).v:f32_sqrt(a32).v; numerical=true; break;
    case 5: case 6: case 7: case 8: {
        const uint64_t sign=d?1ULL<<63:1ULL<<31;
        const uint64_t left=a ^ ((id>=7)?sign:0);
        const uint64_t third=c ^ ((id==6 || id==8)?sign:0);
        result=d?f64_mulAdd(float64_t{left},b64,float64_t{third}).v:
            f32_mulAdd(float32_t{uint32_t(left)},b32,float32_t{uint32_t(third)}).v;
        numerical=true; break;
    }
    case 9: case 10: case 11: {
        const uint64_t sign=d?1ULL<<63:1ULL<<31;
        const uint64_t signResult=id==9?(b&sign):id==10?((~b)&sign):((a^b)&sign);
        result=(a&~sign)|signResult; result=d?result:box(uint32_t(result)); break;
    }
    case 12: case 13: {
        const bool an=nan(a,d), bn=nan(b,d);
        const uint64_t sign=d?1ULL<<63:1ULL<<31;
        bool lt=false,eq=false;
        if(!an && !bn) {lt=d?f64_lt_quiet(a64,b64):f32_lt_quiet(a32,b32);eq=d?f64_eq(a64,b64):f32_eq(a32,b32);}
        const bool zero=(a&~sign)==0 && (b&~sign)==0;
        const bool choose=eq ? (!zero || (id==12?bool(a&sign):!bool(a&sign))) : (id==12?lt:!lt);
        result=an?b:bn?a:choose?a:b;
        softfloat_exceptionFlags=(signaling(a,d)||signaling(b,d))?softfloat_flag_invalid:0;
        numerical=true; break;
    }
    case 14: result=d?f64_le(a64,b64):f32_le(a32,b32); break;
    case 15: result=d?f64_lt(a64,b64):f32_lt(a32,b32); break;
    case 16: result=d?f64_eq(a64,b64):f32_eq(a32,b32); break;
    case 17: result=classification(a,d); break;
    case 18: result=d?integer:box(uint32_t(integer)); break;
    case 19: result=d?rawA:uint64_t(int64_t(int32_t(rawA))); break;
    case 20: case 21: case 22: case 23: {
        bool u=(id-20)&1, l=(id-20)&2;
        if(l) result=u?(d?f64_to_ui64(a64,rm,true):f32_to_ui64(a32,rm,true)):
            uint64_t(d?f64_to_i64(a64,rm,true):f32_to_i64(a32,rm,true));
        else result=u?(d?f64_to_ui32(a64,rm,true):f32_to_ui32(a32,rm,true)):
            uint32_t(d?f64_to_i32(a64,rm,true):f32_to_i32(a32,rm,true));
        // 8086-SSE uses different invalid sentinels. RISC-V clips by sign,
        // treating NaN as positive, and must suppress NX when NV is raised.
        if(softfloat_exceptionFlags&softfloat_flag_invalid) {
            const bool negative=!nan(a,d) && (d?bool(a>>63):bool(uint32_t(a)>>31));
            result=u?(negative?0:(l?UINT64_MAX:UINT32_MAX)):
                (negative?(l?1ULL<<63:1ULL<<31):(l?INT64_MAX:INT32_MAX));
            softfloat_exceptionFlags=softfloat_flag_invalid;
        }
        if(!l) result=uint64_t(int64_t(int32_t(result)));
        break;
    }
    case 24: result=d?i32_to_f64(int32_t(integer)).v:i32_to_f32(int32_t(integer)).v; numerical=true; break;
    case 25: result=d?ui32_to_f64(uint32_t(integer)).v:ui32_to_f32(uint32_t(integer)).v; numerical=true; break;
    case 26: result=d?i64_to_f64(int64_t(integer)).v:i64_to_f32(int64_t(integer)).v; numerical=true; break;
    case 27: result=d?ui64_to_f64(integer).v:ui64_to_f32(integer).v; numerical=true; break;
    case 28: result=d?f32_to_f64(float32_t{single(rawA)}).v:f64_to_f32(float64_t{rawA}).v; numerical=true; break;
    default: throw std::runtime_error("bad oracle instruction ID");
    }
    return {numerical?canonical(result,d):result,flags()};
}
int main(int argc,char** argv) { try {
    if(argc!=2) throw std::runtime_error("vector output path required");
    const std::array<uint32_t,24> edgeS = {0,0x80000000,1,0x80000001,0x7fffff,0x807fffff,
        0x800000,0x80800000,0x3f800000,0xbf800000,0x3f000000,0x40000000,0x40400000,
        0x3f800001,0x33800000,0x7f7fffff,0xff7fffff,0x7f800000,0xff800000,0x7f800001,
        0x7fc12345,0xffc12345,0x4f000000,0xcf000001};
    const std::array<uint64_t,24> edgeD = {0,1ULL<<63,1,(1ULL<<63)|1,0xfffffffffffffULL,
        0x800fffffffffffffULL,0x10000000000000ULL,0x8010000000000000ULL,
        0x3ff0000000000000ULL,0xbff0000000000000ULL,0x3fe0000000000000ULL,
        0x4000000000000000ULL,0x4008000000000000ULL,0x3ff0000000000001ULL,
        0x3ca0000000000000ULL,0x7fefffffffffffffULL,0xffefffffffffffffULL,
        0x7ff0000000000000ULL,0xfff0000000000000ULL,0x7ff0000000000001ULL,
        0x7ff8123456789abcULL,0xfff8123456789abcULL,0x43e0000000000000ULL,0xc3e0000000000001ULL};
    const std::array<uint64_t,10> ints = {0,1,UINT64_MAX,0x7fffffff,0x80000000,0xffffffff,
        INT64_MAX,1ULL<<63,0x100000001,0x1000000000000001};
    auto anchor=[](unsigned id,bool d,unsigned rm,uint64_t a,uint64_t b,uint64_t c,uint64_t i,uint64_t v,unsigned f) {
        auto r=reference(id,d,rm,a,b,c,i);
        if(r.value!=v || r.flags!=f) throw std::runtime_error("independent known-answer anchor failed id="+std::to_string(id));
    };
    anchor(2,false,0,box(0x3fc00000),box(0x40000000),0,0,box(0x40400000),0);
    anchor(3,true,0,0x3ff0000000000000ULL,0,0,0,0x7ff0000000000000ULL,8);
    anchor(4,true,0,0x4010000000000000ULL,0,0,0,0x4000000000000000ULL,0);
    anchor(5,false,0,box(0x3fc00000),box(0x40000000),box(0xbf800000),0,box(0x40000000),0);
    anchor(7,false,0,box(0x3fc00000),box(0x40000000),box(0x3f800000),0,box(0xc0000000),0);
    anchor(12,true,0,1ULL<<63,0,0,0,1ULL<<63,0);
    anchor(20,false,0,box(0x7fc00000),0,0,0,INT32_MAX,16);
    anchor(21,false,0,box(0x7fc00000),0,0,0,UINT64_MAX,16);
    anchor(28,true,0,box(0x3f800000),0,0,0,0x3ff0000000000000ULL,0);
    for(bool d:{false,true}) {
        const uint64_t z=d?0:box(0), nz=d?(1ULL<<63):box(0x80000000);
        const uint64_t inf=d?0x7ff0000000000000ULL:box(0x7f800000);
        const uint64_t qnan=d?0x7ff8000000000000ULL:box(0x7fc00000);
        // RISC-V mandates NV for 0*infinity even with a quiet-NaN addend.
        for(unsigned id=5;id<=8;++id) anchor(id,d,0,z,inf,qnan,0,qnan,16);
        anchor(12,d,0,z,nz,0,0,nz,0);
        anchor(13,d,0,nz,z,0,0,z,0);
    }
    std::ofstream out(argv[1]); if(!out) throw std::runtime_error("cannot open vector output");
    std::mt19937_64 random(0xfd20261003ULL);
    unsigned count=0,seen=0;
    for(bool d : {false,true}) for(unsigned id=0;id<29;++id) for(unsigned rm=0;rm<5;++rm) {
        for(unsigned i=0;i<96;++i) {
            uint64_t a,b,c,integer;
            if(i<24) {
                a=d?edgeD[i]:box(edgeS[i]);
                b=d?edgeD[(i*7+5)%24]:box(edgeS[(i*7+5)%24]);
                c=d?edgeD[(i*11+8)%24]:box(edgeS[(i*11+8)%24]);
                integer=ints[i%ints.size()];
            } else {
                a=d?random():box(uint32_t(random()));b=d?random():box(uint32_t(random()));c=d?random():box(uint32_t(random()));
                integer=random();
                if(!d && i%17==0) a &= 0xffffffffULL; // unboxed computational S
                if(i%7==0) b=a ^ (d?1ULL<<63:1ULL<<31); // cancellation
            }
            // A cross-format conversion reads the source precision, not its destination.
            if(i>=88 && (id<=3 || (id>=5 && id<=8) || (id>=12 && id<=16))) {
                // Signed zeros, both NaNs, 0*inf with qNaN/sNaN, opposing
                // infinities: deterministic cases absent from random sampling.
                const std::array<unsigned,8> ai={0,1,17,0,20,19,17,8};
                const std::array<unsigned,8> bi={0,0,0,17,21,20,18,9};
                const std::array<unsigned,8> ci={0,1,20,19,8,17,17,0};
                unsigned k=i-88;
                a=d?edgeD[ai[k]]:box(edgeS[ai[k]]);
                b=d?edgeD[bi[k]]:box(edgeS[bi[k]]);
                c=d?edgeD[ci[k]]:box(edgeS[ci[k]]);
            }
            if(id==28) a=d?box(edgeS[i%24]):edgeD[i%24];
            auto r=reference(id,d,rm,a,b,c,integer);
            out<<std::hex<<instruction(id,d,rm)<<' '<<rm<<' '<<a<<' '<<b<<' '<<c<<' '<<integer<<' '<<r.value<<' '<<r.flags<<'\n';
            ++count; seen|=r.flags;
        }
    }
    out.close(); if(!out || seen!=31) throw std::runtime_error("incomplete oracle flags/output");
    std::cout<<"SOFTFLOAT_FD_PASS anchors=21 encodings=58 rounding_modes=5 vectors="<<count<<" flags_seen="<<seen<<'\n';
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
