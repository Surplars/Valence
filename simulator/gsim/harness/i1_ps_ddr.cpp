#include "I1PsDdrFixture.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
using Model = SI1PsDdrFixture;
static void check(bool ok, const char *why) { if (!ok) throw std::runtime_error(why); }
static void tick(Model &d) { d.set_clock(0);d.step();d.set_clock(1);d.step(); }
static uint64_t rng = 0x192ab7946cc81351ULL;
static uint64_t next() { rng ^= rng<<13; rng ^= rng>>7; rng ^= rng<<17; return rng; }
static void bootInputs(Model &d, bool start, bool ready) { d.set_start(start); d.set_ddrReady(ready); }
static void init(Model &d) {
    d.set_clock(0); d.set_reset(1); bootInputs(d,0,0);
    d.set_io$$offset$$ar$$valid(0); d.set_io$$offset$$aw$$valid(0); d.set_io$$offset$$w$$valid(0);
    d.set_io$$hp$$r$$valid(0); d.set_io$$hp$$b$$valid(0);
    tick(d);tick(d);d.set_reset(0);
}
int main(int argc, char **) { try {
    const bool badBase=argc>1;
    unsigned launches=0;
    for (bool startFirst:{false,true}) {
        Model d;init(d);
        bootInputs(d,startFirst,!startFirst);
        for(unsigned i=0;i<24;++i) {tick(d);check(d.get_heldReset()&&!d.get_started(),"one GPIO alone released reset");}
        bootInputs(d,1,1);
        unsigned delay=0;
        while(!d.get_started()&&delay<12) {tick(d);++delay;}
        check(delay>=2&&delay<12&&!d.get_heldReset()&&d.get_memoryReady(),"synchronized cold launch failed");
        for(unsigned i=0;i<200;++i) {bootInputs(d,next()&1,next()&1);tick(d);
            check(d.get_started()&&!d.get_heldReset()&&d.get_memoryReady(),"RPU GPIO change discarded live AXI epoch");}
        d.set_reset(1);d.set_clock(0);d.step();check(d.get_heldReset()&&!d.get_started(),"common cold reset did not clear launch");
        ++launches;
    }
    Model d;init(d);
    unsigned checks=0;
    for(unsigned cycle=0;cycle<20000;++cycle) {
        uint64_t a=next(), b=next(), payload=next();
        unsigned size=a&3,len=(a>>2)&15,id=(a>>6)&15;
        uint32_t offset=uint32_t(next())&0x0fffff80U;
        if(cycle<2) {offset=cycle?0x0fffff80U:0;size=3;len=15;}
        bool av=a>>15&1,ar=a>>16&1,wv=a>>17&1,wr=a>>18&1;
        bool rv=b>>15&1,rr=b>>16&1,bv=b>>17&1,br=b>>18&1;
        d.set_io$$offset$$ar$$valid(av);d.set_io$$hp$$ar$$ready(ar);
        d.set_io$$offset$$ar$$bits$$addr(offset);d.set_io$$offset$$ar$$bits$$id(id);
        d.set_io$$offset$$ar$$bits$$len(len);d.set_io$$offset$$ar$$bits$$size(size);
        d.set_io$$offset$$ar$$bits$$burst(1);d.set_io$$offset$$ar$$bits$$lock(a>>10&1);
        d.set_io$$offset$$ar$$bits$$cache(a>>20&15);d.set_io$$offset$$ar$$bits$$prot(a>>24&7);
        d.set_io$$offset$$ar$$bits$$qos(a>>27&15);
        d.set_io$$offset$$aw$$valid(!av);d.set_io$$hp$$aw$$ready(!ar);
        d.set_io$$offset$$aw$$bits$$addr(offset);d.set_io$$offset$$aw$$bits$$id(id^15);
        d.set_io$$offset$$aw$$bits$$len(len);d.set_io$$offset$$aw$$bits$$size(size);
        d.set_io$$offset$$aw$$bits$$burst(1);d.set_io$$offset$$aw$$bits$$lock(b>>10&1);
        d.set_io$$offset$$aw$$bits$$cache(b>>20&15);d.set_io$$offset$$aw$$bits$$prot(b>>24&7);
        d.set_io$$offset$$aw$$bits$$qos(b>>27&15);
        d.set_io$$offset$$w$$valid(wv);d.set_io$$hp$$w$$ready(wr);
        d.set_io$$offset$$w$$bits$$data(payload);d.set_io$$offset$$w$$bits$$strb(a>>32&255);
        d.set_io$$offset$$w$$bits$$last(a>>40&1);
        d.set_io$$hp$$r$$valid(rv);d.set_io$$offset$$r$$ready(rr);
        d.set_io$$hp$$r$$bits$$id(b&15);d.set_io$$hp$$r$$bits$$data(~payload);
        d.set_io$$hp$$r$$bits$$resp(b>>4&3);d.set_io$$hp$$r$$bits$$last(b>>6&1);
        d.set_io$$hp$$b$$valid(bv);d.set_io$$offset$$b$$ready(br);
        d.set_io$$hp$$b$$bits$$id(a&15);d.set_io$$hp$$b$$bits$$resp(a>>4&3);
        tick(d);
        const uint64_t expected=0x40000000ULL+offset+unsigned(badBase);
        check(d.get_io$$hp$$ar$$bits$$addr()==expected&&d.get_io$$hp$$aw$$bits$$addr()==expected,
            "independent PS physical address oracle");
        check(d.get_io$$hp$$ar$$valid()==av&&d.get_io$$offset$$ar$$ready()==ar&&
              d.get_io$$hp$$aw$$valid()==!av&&d.get_io$$offset$$aw$$ready()==!ar,"AXI address backpressure");
        check(d.get_io$$hp$$ar$$bits$$id()==id&&d.get_io$$hp$$aw$$bits$$id()==(id^15)&&
              d.get_io$$hp$$ar$$bits$$len()==len&&d.get_io$$hp$$aw$$bits$$len()==len&&
              d.get_io$$hp$$ar$$bits$$size()==size&&d.get_io$$hp$$aw$$bits$$size()==size&&
              d.get_io$$hp$$ar$$bits$$burst()==1&&d.get_io$$hp$$aw$$bits$$burst()==1,"AXI owner/burst metadata");
        check(d.get_io$$hp$$ar$$bits$$lock()==(a>>10&1)&&d.get_io$$hp$$aw$$bits$$lock()==(b>>10&1)&&
              d.get_io$$hp$$ar$$bits$$cache()==(a>>20&15)&&d.get_io$$hp$$aw$$bits$$cache()==(b>>20&15)&&
              d.get_io$$hp$$ar$$bits$$prot()==(a>>24&7)&&d.get_io$$hp$$aw$$bits$$prot()==(b>>24&7)&&
              d.get_io$$hp$$ar$$bits$$qos()==(a>>27&15)&&d.get_io$$hp$$aw$$bits$$qos()==(b>>27&15),
              "AXI attributes changed by address adapter");
        check(d.get_io$$hp$$w$$valid()==wv&&d.get_io$$offset$$w$$ready()==wr&&
              d.get_io$$hp$$w$$bits$$data()==payload&&d.get_io$$hp$$w$$bits$$strb()==(a>>32&255)&&
              d.get_io$$hp$$w$$bits$$last()==(a>>40&1),"AXI W data/strobe/last/backpressure");
        check(d.get_io$$offset$$r$$valid()==rv&&d.get_io$$hp$$r$$ready()==rr&&
              d.get_io$$offset$$r$$bits$$id()==(b&15)&&d.get_io$$offset$$r$$bits$$data()==~payload&&
              d.get_io$$offset$$r$$bits$$resp()==(b>>4&3)&&d.get_io$$offset$$r$$bits$$last()==(b>>6&1),
              "AXI R owner/data/error/backpressure");
        check(d.get_io$$offset$$b$$valid()==bv&&d.get_io$$hp$$b$$ready()==br&&
              d.get_io$$offset$$b$$bits$$id()==(a&15)&&d.get_io$$offset$$b$$bits$$resp()==(a>>4&3),
              "AXI B owner/error/backpressure");
        ++checks;
    }
    std::cout<<"I1_PS_DDR_PASS randomized_cycles="<<checks<<" cold_launches="<<launches<<"\n";
    return 0;
} catch(const std::exception &e) {std::cerr<<e.what()<<"\n";return 1;} }
