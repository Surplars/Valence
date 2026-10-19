#include "CommonInstructionRomContractGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

static void check(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
struct Driver {
    SCommonInstructionRomContractGsim dut;
    unsigned cycles=0, replies=0, deniedReplies=0, heldReplies=0;
    Driver() {
#define INIT(port) \
        dut.set_io##port##$$a$$valid(0); dut.set_io##port##$$a$$bits$$opcode(4); \
        dut.set_io##port##$$a$$bits$$param(0); dut.set_io##port##$$a$$bits$$size(3); \
        dut.set_io##port##$$a$$bits$$source(0); dut.set_io##port##$$a$$bits$$address(0); \
        dut.set_io##port##$$a$$bits$$mask(255); dut.set_io##port##$$a$$bits$$data(0); \
        dut.set_io##port##$$a$$bits$$corrupt(0); dut.set_io##port##$$b$$ready(1); \
        dut.set_io##port##$$c$$valid(0); dut.set_io##port##$$c$$bits$$opcode(0); \
        dut.set_io##port##$$c$$bits$$param(0); dut.set_io##port##$$c$$bits$$size(0); \
        dut.set_io##port##$$c$$bits$$source(0); dut.set_io##port##$$c$$bits$$address(0); \
        dut.set_io##port##$$c$$bits$$data(0); dut.set_io##port##$$c$$bits$$corrupt(0); \
        dut.set_io##port##$$d$$ready(0); dut.set_io##port##$$e$$valid(0); \
        dut.set_io##port##$$e$$bits$$sink(0)
        INIT($$defaultPort); INIT($$completePort);
#undef INIT
        dut.set_io$$initialize$$valid(0); dut.set_io$$initialize$$bits$$index(0);
        dut.set_io$$initialize$$bits$$data(0); dut.set_reset(1); tick(); tick(); dut.set_reset(0);
    }
    void tick() { dut.step(); check(++cycles<1000,"bounded ROM contract completion failure"); }
    void program(unsigned index,uint32_t data) {
        dut.set_io$$initialize$$valid(1); dut.set_io$$initialize$$bits$$index(index);
        dut.set_io$$initialize$$bits$$data(data); tick(); dut.set_io$$initialize$$valid(0);
    }
    void fetch(bool full,uint64_t address,unsigned size,uint64_t expected,bool denied=false,
               bool badMask=false) {
#define SET(field,value) do { if(full) dut.set_io$$completePort##field(value); \
                             else dut.set_io$$defaultPort##field(value); } while(0)
#define GET(field) (full?dut.get_io$$completePort##field():dut.get_io$$defaultPort##field())
        unsigned source=(replies+5)&15;
        SET($$a$$bits$$address,address); SET($$a$$bits$$size,size); SET($$a$$bits$$source,source);
        SET($$a$$bits$$mask,badMask?0:(((1U<<(1U<<size))-1U)<<(address&7)));
        SET($$a$$valid,1); SET($$d$$ready,0);
        do {tick();} while(!GET($$a$$ready));
        check((full?dut.get_io$$completeMask():dut.get_io$$defaultMask())==
            (full || size==3?3U:((address&4)?2U:1U)),"ROM request-bank contract mismatch");
        SET($$a$$valid,0);
        do {tick();} while(!GET($$d$$valid));
        for(unsigned stall=0;stall<4;++stall) {
            check(GET($$d$$valid) && GET($$d$$bits$$source)==source && GET($$d$$bits$$size)==size &&
                GET($$d$$bits$$opcode)==1 && bool(GET($$d$$bits$$denied))==denied &&
                !GET($$d$$bits$$corrupt) && GET($$d$$bits$$data)==expected,
                "ROM default/complete data, extent or held metadata mismatch");
            ++heldReplies; tick();
        }
        SET($$d$$ready,1); tick(); SET($$d$$ready,0); ++replies; if(denied) ++deniedReplies;
#undef SET
#undef GET
    }
    void run(const std::string& mode) {
        program(0,0x11223344); program(1,0x55667788); program(14,0xdecafbad); program(15,0x89abcdef);
        if(mode=="--misaligned") { fetch(false,0x80000002,2,0); throw std::runtime_error("missing alignment assertion"); }
        if(mode=="--bad-mask") { fetch(true,0x80000000,2,0,false,true); throw std::runtime_error("missing mask assertion"); }
        for(bool full:{false,true}) {
            fetch(full,0x80000000,3,0x5566778811223344ULL);
            for(unsigned size=0;size<3;++size) {
                fetch(full,0x80000000,size,full?0x5566778811223344ULL:0x11223344ULL);
                fetch(full,0x80000004,size,full?0x5566778811223344ULL:0x5566778800000000ULL);
            }
            fetch(full,0x8000003c,2,full?0x89abcdefdecafbadULL:0x89abcdef00000000ULL);
            fetch(full,0x80000040,2,0,true); fetch(full,0x80000040,3,0,true);
            fetch(full,0x7ffffffc,2,0,true);
        }
        std::cout<<"ROM_CONTRACT_PASS replies="<<replies<<" denied="<<deniedReplies
                 <<" held_checks="<<heldReplies<<" default_single_bank=6 complete_subword=6\n";
    }
};
int main(int argc,char**argv) {
    try { Driver d; d.run(argc>1?argv[1]:""); }
    catch(const std::exception& error) { std::cerr<<error.what()<<"\n"; return 1; }
}
