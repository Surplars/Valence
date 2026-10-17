#include "I1PeripheralDecodeFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#ifndef I1_DISABLED_PERIPHERALS
#define I1_DISABLED_PERIPHERALS 0
#endif
static void need(bool ok,const char *m) { if(!ok) throw std::runtime_error(m); }
int main(int argc,char **argv) { try {
    SI1PeripheralDecodeFixture d;
    const bool wrong=argc>1 && std::string(argv[1])=="--wrong-owner";
    const bool wrongPayload=argc>1 && std::string(argv[1])=="--wrong-payload";
    std::mt19937_64 rng(0x1915dead);
    d.set_reset(1);d.set_io$$control$$request$$valid(0);d.set_io$$control$$response$$ready(0);
    d.set_io$$allow(0);d.step();d.step();d.set_reset(0);
    unsigned checks=0, forwards=0;
    auto test=[&](uint64_t address,int owner,bool error,bool write=false,
                  unsigned size=3,unsigned mask=255,uint64_t local=0) {
        const uint64_t data=rng();
        d.set_io$$control$$request$$bits$$address(address);
        d.set_io$$control$$request$$bits$$write(write);
        d.set_io$$control$$request$$bits$$data(data);
        d.set_io$$control$$request$$bits$$size(size);
        d.set_io$$control$$request$$bits$$byteEnable(mask);
        d.set_io$$control$$request$$valid(1);d.set_io$$control$$response$$ready(0);
        bool accepted=false,replied=false; unsigned launched=0,stalled=0;
        uint64_t heldData=0;bool heldError=false;
        for(unsigned n=0;n<120;++n) {
            // Hold all external targets initially, then independent bounded
            // request stalls. Retain the reply for six edges before consuming.
            d.set_io$$allow(n<6?0:unsigned(rng())&255);
            d.set_io$$control$$response$$ready(replied && stalled>=6);
            d.step();
            const unsigned actual=d.get_io$$forwarded() ^ unsigned(wrong && checks==0 && n==7);
            if(actual) {
                need(owner>=0 && actual==(1U<<owner) && !accepted,
                     "independent peripheral owner/address oracle");
                need(d.get_io$$address()==address && (d.get_io$$data()^uint64_t(wrongPayload))==data &&
                     bool(d.get_io$$write())==write && d.get_io$$size()==size && d.get_io$$mask()==mask,
                     "peripheral request payload changed");
                ++launched;++forwards;
            }
            if(!accepted && d.get_io$$control$$request$$ready()) {
                accepted=true;d.set_io$$control$$request$$valid(0);
            }
            if(d.get_io$$control$$response$$valid()) {
                const uint64_t wanted=owner<0?local:address^(uint64_t(owner)<<56);
                need(accepted && d.get_io$$control$$response$$bits$$data()==wanted &&
                     bool(d.get_io$$control$$response$$bits$$error())==error,
                     "independent peripheral response oracle");
                if(replied) need(heldData==d.get_io$$control$$response$$bits$$data() &&
                    heldError==bool(d.get_io$$control$$response$$bits$$error()),"held peripheral reply changed");
                else {replied=true;heldData=d.get_io$$control$$response$$bits$$data();
                    heldError=d.get_io$$control$$response$$bits$$error();}
                if(stalled++>=6) {
                    need(launched==unsigned(owner>=0),"duplicate or missing peripheral side effect");
                    ++checks;return;
                }
            } else need(!replied,"peripheral reply withdrawn");
        }
        throw std::runtime_error("bounded peripheral completion");
    };
    struct Window { uint64_t base,bytes;int owner; };
    constexpr std::array<Window,5> windows{{
        {0x10000000,8,0},{0x10003000,64,4},{0x10040000,4096,5},
        {0x10080000,4096,6},{0x10005000,256,7}}};
    for(auto w:windows) for(unsigned n=0;n<8;++n) {
        const auto a=w.base+(n<2?n*w.bytes-w.bytes/2:rng()%w.bytes);
        // The first two addresses may be outside. Full 64-bit static software
        // windows decide routing, never a DUT selected/decoded signal.
        auto oracle=[&](uint64_t address) {
            int result=-1;
            if(!I1_DISABLED_PERIPHERALS) for(auto v:windows)
                if(address>=v.base && address-v.base<v.bytes) result=v.owner;
            return result;
        };
        const int owner=oracle(a);
        test(a,owner,owner<0);
        for(uint64_t high:{UINT64_C(0x100000000),UINT64_C(0x8000000000000000)}) {
            test(a+high,-1,true,true);
        }
        const auto inside=w.base+(rng()%w.bytes);
        test(inside,oracle(inside),I1_DISABLED_PERIPHERALS,true,n%4,unsigned(rng())&255);
    }
    // Local boot status and MSIP still work without selecting any external IP.
    test(0x10002000,-1,false,false,3,255,I1_DISABLED_PERIPHERALS?1:11);
    test(0x10002008,-1,false,false,3,255,0x80200000);
    test(0x02000000,-1,I1_DISABLED_PERIPHERALS,false,2,15);
    std::cout<<"I1_PERIPHERAL_DECODE_PASS checks="<<checks<<" forwarded="<<forwards
        <<" disabled="<<I1_DISABLED_PERIPHERALS<<" full64_aliases_payload_stalls_disabled_windows=PASS\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n';return 1; } }
