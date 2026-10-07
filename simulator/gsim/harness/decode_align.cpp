#include "DecodeAlignGsim.h"
#include <cstdint>
#include <array>
#include <vector>
constexpr uint64_t dataBase = 0x80010000;
using Memory = std::array<uint8_t, 4096>;
#include "isa_model.h"
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
static void check(bool ok, const char *m) { if (!ok) throw std::runtime_error(m); }
// Independent field-based class oracle. The B fixed-field decoder is unchanged;
// its input is intentionally varied independently to test the class OR boundary.
static bool legal(uint32_t i, bool sys, bool atom, bool bit) {
    unsigned op=i&127, f=(i>>12)&7, hi=i>>25, a=i>>27, rs=(i>>20)&31;
    if(bit) return true;
    if(op==0x37 || op==0x17 || op==0x6f) return true;
    if(op==0x67) return f==0;
    if(op==0x63) return f!=2 && f!=3;
    if(op==3) return f!=7;
    if(op==0x23) return f<4;
    if(op==0x2f && atom) {
        bool supported=false;
        for(unsigned n:{0U,1U,2U,3U,4U,8U,12U,16U,20U,24U,28U}) supported|=a==n;
        return (f==2 || f==3) && supported && (a!=2 || rs==0);
    }
    if(sys && op==0xf) return f<2;
    if(sys && op==0x73) {
        if(f==1 || f==2 || f==3 || f==5 || f==6 || f==7) return true;
        for(uint32_t c:{0x73U,0x100073U,0x30200073U,0x10200073U,0x10500073U})
            if(i==c) return true;
        return hi==9 && ((i>>7)&255)==0;
    }
    bool imm=op==0x13 || op==0x1b, reg=op==0x33 || op==0x3b;
    bool word=op==0x1b || op==0x3b;
    if(reg && hi==1 && (!word || f==0 || f>=4)) return true;
    if(op==0x33 && hi==7 && (f==5 || f==7)) return true;
    if(!(imm || reg)) return false;
    switch(f) {
      case 0: return imm || hi==0 || hi==32;
      case 1: return imm && !word ? (i>>26)==0 : hi==0;
      case 5: return imm && !word ? ((i>>26)==0 || (i>>26)==16) : hi==0 || hi==32;
      default: return !word && (imm || hi==0);
    }
}
int main(int argc,char **argv) { try {
    bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    SDecodeAlignGsim d; d.set_reset(0); std::mt19937_64 rng(0xd3c0de20261002ULL);
    uint64_t vectors=0; unsigned privileged=0;
    auto test=[&](uint32_t i) {
        bool b=bool(rng()&1); unsigned want=0;
        for(unsigned m=0;m<4;++m) want|=unsigned(legal(i,m&1,m&2,b))<<m;
        d.set_io$$instruction(i); d.set_io$$pc(rng()&~1ULL); d.set_io$$bitLegal(b); d.step();
        unsigned actual=d.get_io$$classLegal();
        if(inject) { actual^=1; inject=false; }
        check(actual==want,"parallel legality class oracle mismatch");
        check(d.get_io$$equal()==15,"parallel decode full payload equivalence mismatch");
        const auto *encoding = decode(i);
        check(bool(d.get_io$$bitDecodedLegal()) == bool(encoding && encoding->alu >= 16 && encoding->alu <= 44),
              "B fixed-field legality oracle mismatch");
        ++vectors;
    };
    for(unsigned op=0;op<128;++op) for(unsigned hi=0;hi<128;++hi)
      for(unsigned f=0;f<8;++f) for(unsigned rs:{0U,1U,31U,17U})
        test((hi<<25)|(rs<<20)|(unsigned(rng()&31)<<15)|(f<<12)|(unsigned(rng()&31)<<7)|op);
    // All unary rs2 and RV64 shift6 values, using the unchanged mask/match ISA oracle.
    for(unsigned op:{0x13U,0x1bU,0x33U,0x3bU}) for(unsigned hi=0;hi<128;++hi)
      for(unsigned f=0;f<8;++f) for(unsigned rs=0;rs<32;++rs)
        test((hi<<25)|(rs<<20)|(unsigned(rng()&31)<<15)|(f<<12)|(unsigned(rng()&31)<<7)|op);
    for(uint32_t c:{0x73U,0x100073U,0x30200073U,0x10200073U,0x10500073U,0x12000073U})
      for(unsigned rd=0;rd<32;++rd) { test(c|(rd<<7)); ++privileged; }
    for(unsigned n=0;n<131072;++n) test(uint32_t(rng()));
    std::cout<<"GSIM decode alignment: PASS vectors="<<vectors<<" configurations=4 privileged="<<privileged<<'\n';
} catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;} }
