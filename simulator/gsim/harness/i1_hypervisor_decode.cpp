// Independent mask/value ledger from RISC-V H 1.0 + riscv/riscv-opcodes rv_h/rv64_h.
// No DUT field helper or generated decode table is used by the oracle.
#include "I1HypervisorDecode.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#ifndef DUT_XLEN
#define DUT_XLEN 64
#endif
struct Encoding { uint32_t value, mask; unsigned kind, size; bool unsign, execute, only64; };
// kind: load=0, store=1, VS fence=2, G fence=3.
static constexpr std::array<Encoding,15> encodings{{
    {0x60004073,0xfff0707f,0,0,false,false,false}, {0x60104073,0xfff0707f,0,0,true,false,false},
    {0x64004073,0xfff0707f,0,1,false,false,false}, {0x64104073,0xfff0707f,0,1,true,false,false},
    {0x64304073,0xfff0707f,0,1,true,true,false}, {0x68004073,0xfff0707f,0,2,false,false,false},
    {0x68104073,0xfff0707f,0,2,true,false,true}, {0x68304073,0xfff0707f,0,2,true,true,false},
    {0x6c004073,0xfff0707f,0,3,false,false,true}, {0x62004073,0xfe007fff,1,0,false,false,false},
    {0x66004073,0xfe007fff,1,1,false,false,false}, {0x6a004073,0xfe007fff,1,2,false,false,false},
    {0x6e004073,0xfe007fff,1,3,false,false,true}, {0x22000073,0xfe007fff,2,0,false,false,false},
    {0x62000073,0xfe007fff,3,0,false,false,false}
}};
static void need(bool p) { if(!p) throw std::runtime_error("independent H encoding/permission oracle mismatch"); }
int main(int argc,char**) { try {
    SI1HypervisorDecode d;
    constexpr std::array<unsigned,5> privilege{3,1,0,1,0};
    uint64_t checks=0,recognized=0,virtualTraps=0,illegalTraps=0,allowedCount=0;
    auto check=[&](uint32_t instruction) {
        const Encoding *gold=nullptr;
        for(const auto &e:encodings) if((DUT_XLEN==64||!e.only64)&&(instruction&e.mask)==e.value) {
            need(!gold); gold=&e;
        }
        for(unsigned mode=0;mode<5;++mode) for(bool hu:{false,true}) for(bool tvm:{false,true}) {
            const bool virt=mode>=3;
            const bool isMemory=gold&&gold->kind<2;
            bool allowed=gold&&(mode==0||(mode==1&&!(gold->kind==3&&tvm))||(mode==2&&isMemory&&hu));
            const bool trap=gold&&!allowed;
            unsigned cause=virt?22:2;
            if(argc>1&&gold&&virt)cause^=1;
            d.set_io$$instruction(instruction);d.set_io$$privilege(privilege[mode]);d.set_io$$virtualized(virt);
            d.set_io$$hu(hu);d.set_io$$tvm(tvm);d.step();
            need(bool(d.get_io$$recognized())==bool(gold)&&bool(d.get_io$$allowed())==allowed);
            need(bool(d.get_io$$exception())==trap);
            if(trap)need(d.get_io$$cause()==cause);
            need(bool(d.get_io$$load())==bool(gold&&gold->kind==0));
            need(bool(d.get_io$$store())==bool(gold&&gold->kind==1));
            need(bool(d.get_io$$fenceVs())==bool(gold&&gold->kind==2));
            need(bool(d.get_io$$fenceGuest())==bool(gold&&gold->kind==3));
            if(gold&&isMemory)need(d.get_io$$size()==gold->size);
            need(bool(d.get_io$$unsigned())==bool(gold&&gold->unsign));
            need(bool(d.get_io$$executePermission())==bool(gold&&gold->execute));
            ++checks;recognized+=bool(gold);allowedCount+=allowed;
            virtualTraps+=trap&&virt;illegalTraps+=trap&&!virt;
        }
    };
    // All register combinations for every standard H encoding, including the
    // three RV64-only instructions as explicit unsupported RV32 inputs.
    for(const auto &e:encodings) {
        for(unsigned a=0;a<32;++a)for(unsigned b=0;b<32;++b)
            check(e.value|(a<<15)|(b<<(e.kind==0?7:20)));
        for(unsigned bit=0;bit<32;++bit)if((e.mask>>bit)&1)check(e.value^(uint32_t{1}<<bit));
    }
    std::mt19937 random(0x48595a31);
    for(unsigned i=0;i<30000;++i)check(random());
    need(allowedCount>10000&&virtualTraps>10000&&illegalTraps>1000);
    std::cout<<"I1_H_DECODE_PASS xlen="<<DUT_XLEN<<" checks="<<checks<<" recognized="<<recognized
        <<" allowed="<<allowedCount<<" virtual_traps="<<virtualTraps<<" illegal_traps="<<illegalTraps
        <<" all_registers_reserved_bits_RV32_HLVX_WU_HU_TVM_VS_VU=PASS\n";
    return 0;
} catch(const std::exception &e) {std::cerr<<e.what()<<'\n';return 1;} }
