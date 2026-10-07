#include "RegisteredFetchWindowGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

#ifndef WINDOW_CAPACITY
#define WINDOW_CAPACITY 3
#endif
struct Packet { bool valid=false; uint64_t data=0; unsigned access=0,page=0; };
using Rows = std::array<Packet,5>;
static void check(bool ok,const char *why) {
    if(!ok) throw std::runtime_error(std::string("fetch window independent oracle mismatch: ")+why);
}
int main(int argc,char **argv) { try {
    const bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    SRegisteredFetchWindowGsim d;
    std::mt19937_64 random(0x76ab3910);
    Rows saved{};
    uint64_t savedBase=0; unsigned savedContext=0,checked=0,valid=0,streams=0;
    auto drive = [&](uint64_t queryBase,unsigned queryContext,uint64_t readBase,unsigned readContext,
                     const Rows& rows,bool invalidate) {
        d.set_io$$queryBase(queryBase); d.set_io$$readBase(readBase);
        d.set_io$$queryContext(queryContext); d.set_io$$readContext(readContext);
        d.set_io$$invalidate(invalidate);
#define QUERY(n) d.set_io$$query##n##$$valid(rows[n].valid); \
        d.set_io$$query##n##$$data(rows[n].data); d.set_io$$query##n##$$access(rows[n].access); \
        d.set_io$$query##n##$$page(rows[n].page)
        QUERY(0); QUERY(1); QUERY(2); QUERY(3); QUERY(4);
#undef QUERY
    };
    drive(0,0,0,0,saved,false); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    auto tick = [&](uint64_t queryBase,unsigned queryContext,uint64_t readBase,unsigned readContext,
                    const Rows& rows,bool invalidate,bool streaming=false) {
        drive(queryBase,queryContext,readBase,readContext,rows,invalidate); d.step();
        Rows got{};
#define PACKET(n) got[n]={bool(d.get_io$$packet##n##$$valid()),d.get_io$$packet##n##$$data(), \
        unsigned(d.get_io$$packet##n##$$access()),unsigned(d.get_io$$packet##n##$$page())}
        PACKET(0); PACKET(1); PACKET(2);
#undef PACKET
        for(unsigned packet=0;packet<3;++packet) {
            Packet expected{}; bool found=false;
            for(unsigned row=0;row<WINDOW_CAPACITY;++row) {
                // Independent modulo-XLEN ADDRESS arithmetic, not DUT key indices.
                if(savedBase+8*row==readBase+8*packet && savedContext==readContext && saved[row].valid) {
                    check(!found,"duplicate address"); expected=saved[row]; found=true;
                }
            }
            expected.valid=found && !invalidate;
            check(got[packet].valid==expected.valid,"address/context/invalidate validity");
            if(expected.valid) {
                if(inject && valid==0) expected.data^=1;
                check(got[packet].data==expected.data && got[packet].access==expected.access &&
                      got[packet].page==expected.page,"payload and both word faults"); ++valid;
            }
            if(streaming && packet<(WINDOW_CAPACITY==3?2:3))
                check(got[packet].valid,"cached mixed-width stream acquired a bubble");
            ++checked;
        }
        if(streaming) ++streams;
        saved=rows; savedBase=queryBase; savedContext=queryContext;
        if(invalidate) for(auto& row:saved) row.valid=false;
    };
    uint64_t base=0xfffffffffffffff8ULL;
    for(unsigned n=0;n<256;++n) {
        Rows rows{}; for(unsigned r=0;r<5;++r) rows[r]={true,random(),unsigned(random()&3),unsigned(random()&3)};
        tick(base,5,base,5,rows,false,n>0);
        base+=(WINDOW_CAPACITY==3?8:16);
    }
    // Sweep both sides of 64-byte, 4-GiB and modulo-XLEN boundaries.
    for(uint64_t anchor : {uint64_t{0},uint64_t{0xffffffc0},uint64_t{0xffffffffffffffc0}}) {
        for(unsigned offset=0;offset<8;++offset) {
            for(int delta=-4;delta<=5;++delta) {
                Rows rows{}; for(auto& row:rows) row={true,random(),unsigned(random()&3),unsigned(random()&3)};
                uint64_t address=anchor+8*offset;
                tick(address,3,savedBase,3,rows,false);
                tick(address,3,address+8*delta,3,rows,false);
            }
        }
    }
    for(unsigned n=0;n<6000;++n) {
        Rows rows{}; for(auto& row:rows) row={bool(random()&1),random(),unsigned(random()&3),unsigned(random()&3)};
        const uint64_t queryBase=random()&~uint64_t{7};
        uint64_t readBase=savedBase+8*(int(random()%11)-4);
        if(n%5==0) readBase^=uint64_t{1}<<63;
        const unsigned queryContext=random()&7,readContext=n%3?savedContext:unsigned(random()&7);
        tick(queryBase,queryContext,readBase,readContext,rows,n%29==0);
    }
    std::cout<<"GSIM registered fetch window: PASS checks="<<checked<<" valid="<<valid
             <<" steadyCycles="<<streams<<" capacity="<<WINDOW_CAPACITY<<" wrap faults contexts invalidate\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
