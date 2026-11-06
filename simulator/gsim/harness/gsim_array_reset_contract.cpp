#include "GsimArrayResetContract.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>

int main(int argc,char **argv) {try {
    const bool inject=argc==2&&std::string(argv[1])=="--inject-array";
    SGsimArrayResetContract d;
    constexpr std::array<uint8_t,4> initialA{0x11,0x42,0x83,0xf0};
    constexpr std::array<uint8_t,3> initialB{0xa0,5,0x7e};
    constexpr std::array<uint8_t,6> initialMatrix{0x20,0x21,0x22,0x23,0x24,0x25};
    auto a=initialA;auto b=initialB;auto matrix=initialMatrix;
    d.set_clockA(0);d.set_clockB(0);d.set_asyncResetA(1);d.set_resetB(1);
    d.set_io$$indexA(0);d.set_io$$indexB(0);d.set_io$$row(0);d.set_io$$column(0);
    d.set_io$$writeA(0);d.set_io$$writeB(0);d.set_io$$writeMatrix(0);
    d.set_io$$dataA(0);d.set_io$$dataB(0);d.set_io$$dataMatrix(0);d.step();
    d.set_clockB(1);d.step();d.set_clockB(0);d.step();
    bool oldA=false,oldB=false;uint64_t checks=0,asyncWithoutEdge=0,syncHeld=0,writes=0;
    std::mt19937_64 rng(0x6172726179727374ULL);
    for(unsigned t=0;t<50000;++t) {
        const unsigned ia=rng()%4,ib=rng()%3,row=rng()%2,column=rng()%3;
        const bool ra=rng()%9==0,rb=rng()%7==0,wa=rng()%3==0,wb=rng()%3==0,wm=rng()%3==0;
        const uint8_t da=rng(),db=rng(),dm=rng();const bool nextA=rng()&1,nextB=rng()&1;
        d.set_clockA(oldA);d.set_clockB(oldB);d.set_asyncResetA(ra);d.set_resetB(rb);
        d.set_io$$indexA(ia);d.set_io$$indexB(ib);d.set_io$$row(row);d.set_io$$column(column);
        d.set_io$$writeA(wa);d.set_io$$writeB(wb);d.set_io$$writeMatrix(wm);
        d.set_io$$dataA(da);d.set_io$$dataB(db);d.set_io$$dataMatrix(dm);
        if(ra) {a=initialA;matrix=initialMatrix;++asyncWithoutEdge;}
        d.step();
        auto check=[&]() {
            if(d.get_io$$a()!=a[ia]||d.get_io$$b()!=b[ib]||d.get_io$$matrix()!=matrix[row*3+column])
                throw std::runtime_error("independent reset-array oracle at iteration "+std::to_string(t));
            ++checks;
        };
        check();
        if(nextA&&!oldA&&!ra) {if(wa){a[ia]=da;++writes;}if(wm){matrix[row*3+column]=dm;++writes;}}
        if(nextB&&!oldB) {if(rb)b=initialB;else if(wb){b[ib]=db;++writes;}}
        else if(rb)++syncHeld;
        d.set_clockA(nextA);d.set_clockB(nextB);d.step();
        if(inject&&t==80)a[ia]^=1;
        check();d.step();check();oldA=nextA;oldB=nextB;
    }
    if(asyncWithoutEdge<1000||syncHeld<1000||writes<1000)throw std::runtime_error("array reset coverage incomplete");
    std::cout<<"GSIM_ARRAY_RESET_CONTRACT_PASS checks="<<checks<<" async_without_edge="<<asyncWithoutEdge
        <<" sync_held="<<syncHeld<<" writes="<<writes<<" one_two_dimensional_mixed_constants=PASS\n";
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
