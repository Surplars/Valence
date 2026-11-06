#pragma once
// Exact independent program/oracle excerpt from i1_spinor_cpu.cpp.
// Excerpt SHA-256: 9c5e03fe1543b928290b152722f4396025a3a328cfcee5628b6ec2032d1e628f
struct Expected {
    uint64_t pc, next, value, mask = UINT64_MAX, cause = 0, tval = 0;
    uint32_t instruction;
    unsigned rd, flags = 0;
    bool integer, floating = false, trap = false;
};
struct Offer { uint32_t instruction; uint64_t sequence; std::optional<uint64_t> scalar; };
struct Program {
    std::vector<uint8_t> image = std::vector<uint8_t>(0x12000);
    std::vector<Expected> expected;
    std::vector<Offer> offers;
    unsigned cursor = 0, traps = 0, sequence = 0;
    void bytes(unsigned offset, uint64_t value, unsigned size) {
        for (unsigned n=0;n<size;++n) image.at(offset+n)=value>>(n*8);
    }
    void emit(uint32_t i, unsigned rd=0, uint64_t value=0, bool fp=false, unsigned flags=0,
              uint64_t mask=UINT64_MAX) {
        expected.push_back({BASE+cursor,BASE+cursor+4,value,mask,0,0,i,rd,flags,rd!=0&&!fp,fp,false});
        bytes(cursor,i,4);cursor+=4;
    }
    void vec(uint32_t i, unsigned rd=0, uint64_t value=0, bool fp=false, unsigned flags=0,
             std::optional<uint64_t> scalar={}) {
        offers.push_back({i,sequence++,scalar}); emit(i,rd,value,fp,flags);
    }
    void trap(uint32_t i, bool native) {
        unsigned pc=cursor;
        if(native) offers.push_back({i,sequence,{}});
        ++sequence;
        expected.push_back({BASE+pc,BASE+0x400,0,UINT64_MAX,2,i,i,0,0,false,false,true});
        bytes(cursor,i,4);cursor+=4;
        // One literal handler; append the executed path without changing main cursor.
        unsigned saved=cursor; cursor=0x400;
        emit(ri(0x13,25,0,25,1),25,++traps);
        emit(ri(0x73,26,2,0,0x342),26,2);
        emit(ri(0x73,27,2,0,0x343),27,i);
        emit(ri(0x73,28,2,0,0x341),28,BASE+pc);
        emit(ri(0x13,28,0,28,4),28,BASE+pc+4);
        emit(ri(0x73,0,1,28,0x341));
        emit(0x30200073); expected.back().next=BASE+pc+4;
        cursor=saved;
    }
    Program() {
        bytes(0x2000,0x0000000200000001ULL,8);bytes(0x2008,0x0000000400000003ULL,8);
        bytes(0x2040,0x3f800000,4);
        bytes(0x2050,0x400000003fc00000ULL,8);bytes(0x2058,0x4080000040600000ULL,8);
        bytes(0x2070,0x3380000033800000ULL,8);bytes(0x2078,0x3380000033800000ULL,8);
        emit(0x00000097,1,BASE);emit(ri(0x13,1,0,1,0x400),1,BASE+0x400);
        emit(ri(0x73,0,1,1,0x305));emit(ri(0x13,25,0,0,0),25,0);
        trap(0x0103f357,false); // VS=Off: CPU rejects before native offer.
        emit(0x000022b7,5,0x2000);emit(ri(0x13,5,0,5,0x200),5,0x2200);
        emit(ri(0x73,0,2,5,0x300)); // VS/FS Initial, independent dirty transitions.
        emit(ri(0x13,7,0,0,4),7,4);
        vec(0x0103f357,6,4,false,0,4); // vsetvli e32,m1
        unsigned auipc=cursor;emit(0x00002417,8,BASE+auipc+0x2000);
        emit(ri(0x13,8,0,8,-int(auipc)),8,BASE+0x2000);
        emit(ri(0x03,10,3,8,0x20),10,0); // Prime destination D-cache line.
        vec(0x02046107,0,0,false,0,BASE+0x2000); // vle32.v v2
        vec(0x0221b0d7); // vadd.vi v1,v2,3
        emit(ri(0x13,9,0,8,0x20),9,BASE+0x2020);
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020); // vse32.v v1
        emit(ri(0x03,10,3,9,0),10,0x0000000500000004ULL);
        emit(ri(0x03,11,3,9,8),11,0x0000000700000006ULL);
        emit((2u<<27)|(9<<15)|(2<<12)|(22<<7)|0x2f,22,4); // LR.W
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020);
        emit((3u<<27)|(9<<15)|(2<<12)|(23<<7)|0x2f,23,1); // SC.W fails after vector store.
        vec(ri(0x73,12,2,0,0xc20),12,4);
        vec(ri(0x73,13,2,0,0xc21),13,16);
        vec(ri(0x73,14,2,0,0xc22),14,16);
        vec(ri(0x73,15,2,0,0x008),15,0);
        emit(ri(0x73,16,2,0,0x300),16,0x8000000000002600ULL,false,0,0x8000000000006600ULL);
        emit(ri(0x07,0,2,8,0x40),0,0xffffffff3f800000ULL,true); // FLW f0=1
        emit(ri(0x13,14,0,8,0x50),14,BASE+0x2050);
        vec(0x02076107,0,0,false,0,BASE+0x2050); // vle32.v v2,(x14)
        vec(0x022050d7,0,0,false,0,0xffffffff3f800000ULL); // vfadd.vf v1,v2,f0
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020);
        emit(ri(0x03,10,3,9,0),10,0x4040000040200000ULL);
        emit(ri(0x03,11,3,9,8),11,0x40a0000040900000ULL);
        vec(0x42101057,0,0xffffffff40200000ULL,true); // vfmv.f.s f0,v1
        emit(0xe2000953,18,0xffffffff40200000ULL); // fmv.x.d x18,f0
        emit(ri(0x07,0,2,8,0x40),0,0xffffffff3f800000ULL,true);
        emit(ri(0x73,0,5,3,0x002)); // frm=RUP
        emit(ri(0x73,0,5,0,0x001)); // clear CPU fflags
        emit(ri(0x13,14,0,8,0x70),14,BASE+0x2070);
        vec(0x02076107,0,0,false,0,BASE+0x2070);
        vec(0x022050d7,0,0,false,1,0xffffffff3f800000ULL);
        vec(0x0204e0a7,0,0,false,0,BASE+0x2020);
        emit(ri(0x03,10,3,9,0),10,0x3f8000013f800001ULL);
        emit(ri(0x73,19,2,0,0x001),19,1);
        trap(ri(0x73,0,1,5,0xc22),true); // native read-only CSR exception.
        emit(ri(0x13,20,0,0,1),20,1);
        emit(st(3,8,20,0x180)); // completion sentinel
        emit(0x0000006f); // stop at preceding sentinel retirement
        expected.pop_back();
    }
};
