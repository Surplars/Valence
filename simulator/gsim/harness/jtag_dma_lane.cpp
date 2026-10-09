#include "DmaRegisterDataAdapter.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
static void check(bool v,const char*m){if(!v)throw std::runtime_error(m);}
int main()try{
    SDmaRegisterDataAdapter d;
    d.set_io$$registers$$request$$valid(0);d.set_io$$registers$$response$$ready(1);
    d.set_io$$data$$request$$ready(0);d.set_io$$data$$response$$valid(0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);d.step();
    for(unsigned n=0;n<64;++n){
        unsigned lane=(n%2)*4;uint32_t word=0x87654321U^(n*0x1020301U);bool write=(n/2)%2;
        d.set_io$$registers$$request$$bits$$address(0x80200000ULL+lane);
        d.set_io$$registers$$request$$bits$$write(write);d.set_io$$registers$$request$$bits$$size(2);
        d.set_io$$registers$$request$$bits$$data(word);d.set_io$$registers$$request$$bits$$byteEnable(15);
        d.set_io$$registers$$request$$valid(1);
        for(unsigned k=0;k<4;++k){d.step();check(d.get_io$$data$$request$$valid(),"adapter offer missing");
            check(d.get_io$$data$$request$$bits$$data()==(uint64_t(word)<<(8*lane)),"high-word write lane wrong");
            check(d.get_io$$data$$request$$bits$$mask()==(15U<<lane),"high-word mask wrong");
            check(d.get_io$$data$$request$$bits$$size()==2,"SBA size changed");
            check(!d.get_io$$data$$request$$bits$$atomic()&&!d.get_io$$data$$request$$bits$$virtualized(),"debug request gained atomic/virtual permission");}
        d.set_io$$data$$request$$ready(1);d.step();check(d.get_io$$registers$$request$$ready(),"adapter accept missing");
        d.set_io$$registers$$request$$valid(0);d.set_io$$data$$request$$ready(0);d.step();
        uint64_t bus=(uint64_t(word)<<(8*lane))|(lane?0xdecafbadULL:0xabcdef0100000000ULL);
        d.set_io$$data$$response$$valid(1);d.set_io$$data$$response$$bits$$data(bus);
        d.set_io$$data$$response$$bits$$error(n==13);d.set_io$$data$$response$$bits$$pageFault(n==17);
        d.set_io$$registers$$response$$ready(0);
        for(unsigned k=0;k<3;++k){d.step();check(d.get_io$$registers$$response$$valid(),"adapter response missing");
            check((d.get_io$$registers$$response$$bits$$data()&0xffffffffULL)==word,"high-word read lane wrong");
            check(bool(d.get_io$$registers$$response$$bits$$error())==(n==13||n==17),"bus error propagation");}
        d.set_io$$registers$$response$$ready(1);d.step();check(d.get_io$$data$$response$$ready(),"response not consumed");
        d.set_io$$data$$response$$valid(0);d.step();
    }
    std::cout<<"JTAG_DMA_LANES_PASS cases=64 low/high read/write stalled request+response error/pageFault\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}
