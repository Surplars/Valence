// Zero-latency AR/R offer and invalid A-data noise, independent beat ledger.
#include "TileLinkAxi4Bridge.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
static void need(bool p, const char* message) { if (!p) throw std::runtime_error(message); }
static uint64_t pattern(unsigned beat) { return 0x91abfd654320ULL ^ (uint64_t(beat) * 0x124812481ULL); }
static void run(unsigned beats, bool badId, bool inject) {
    STileLinkAxi4Bridge d;
    d.set_io$$tl$$a$$valid(0); d.set_io$$tl$$c$$valid(0); d.set_io$$tl$$e$$valid(0);
    d.set_io$$tl$$d$$ready(0); d.set_io$$axi$$ar$$ready(0); d.set_io$$axi$$aw$$ready(0);
    d.set_io$$axi$$w$$ready(0); d.set_io$$axi$$r$$valid(0); d.set_io$$axi$$b$$valid(0);
    d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    d.set_io$$tl$$a$$valid(1);
    d.set_io$$tl$$a$$bits$$opcode(4); d.set_io$$tl$$a$$bits$$param(0);
    d.set_io$$tl$$a$$bits$$size(beats == 1 ? 3 : 6); d.set_io$$tl$$a$$bits$$source(3);
    d.set_io$$tl$$a$$bits$$address(0x100000000ULL);
    d.set_io$$tl$$a$$bits$$mask(255); d.set_io$$tl$$a$$bits$$data(0); d.set_io$$tl$$a$$bits$$corrupt(0);
    d.step(); need(d.get_io$$tl$$a$$ready(), "initial TL credit");
    d.set_io$$tl$$a$$valid(0);
    bool ar=false;
    for (unsigned n=0; n<20 && !ar; ++n) { d.step(); ar=d.get_io$$axi$$ar$$valid(); }
    need(ar, "bounded AR offer");
    unsigned id=d.get_io$$axi$$ar$$bits$$id();
    need(d.get_io$$axi$$ar$$bits$$addr()==0x7fe00000ULL &&
         d.get_io$$axi$$ar$$bits$$len()==beats-1, "independent above4G AR geometry");
    d.set_io$$axi$$ar$$ready(1);
    d.set_io$$axi$$r$$valid(1);
    d.set_io$$axi$$r$$bits$$id(badId ? 15 : id);
    d.set_io$$axi$$r$$bits$$data(pattern(0));
    d.set_io$$axi$$r$$bits$$resp(0);
    d.set_io$$axi$$r$$bits$$last(beats==1);
    d.step();
    need(d.get_io$$axi$$ar$$valid(), "zero-delay R displaced held AR");
    need(!d.get_io$$axi$$r$$ready(), "R capture borrowed same-edge AR forwarding");
    d.set_io$$axi$$ar$$ready(0);
    unsigned received=0, completed=0, idle=0;
    for (unsigned cycle=0; cycle<100 && completed<beats; ++cycle) {
        d.set_io$$axi$$r$$valid(received<beats);
        d.set_io$$axi$$r$$bits$$data(pattern(received));
        d.set_io$$axi$$r$$bits$$last(received+1==beats);
        // Valid is false. These unrelated write bits must NEVER select R data.
        d.set_io$$tl$$a$$bits$$opcode(1);
        d.set_io$$tl$$a$$bits$$mask((cycle*13)&255);
        d.set_io$$tl$$a$$bits$$data(~pattern(cycle+5));
        bool ready=cycle%4!=1;
        d.set_io$$tl$$d$$ready(ready);
        d.step();
        if (received<beats) {
            need(d.get_io$$axi$$r$$ready(), "registered R credit lost one-beat-per-cycle flow");
            ++received;
        } else ++idle;
        if (!d.get_io$$tl$$d$$valid()) continue;
        need(received==beats && idle>0, "TL D exposed before complete captured R");
        need(d.get_io$$tl$$d$$bits$$source()==3 &&
             d.get_io$$tl$$d$$bits$$opcode()==1 &&
             !d.get_io$$tl$$d$$bits$$denied() && !d.get_io$$tl$$d$$bits$$corrupt(),
             "independent R capture metadata");
        need(d.get_io$$tl$$d$$bits$$data()==(pattern(completed)^(inject?1ULL:0ULL)),
             "independent R capture byte oracle");
        if (ready) ++completed;
    }
    need(received==beats && completed==beats, "zero-delay R count/drain");
}
int main(int argc, char** argv) { try {
    std::string mode=argc>1?argv[1]:"";
    for (unsigned beats : {1U, 8U}) run(beats, mode=="--bad-id", mode=="--inject");
    std::cout<<"I1_AXI_CAPTURE_PASS zero_delay_AR_R=2 invalid_A_data_noise=PASS consecutive_R=PASS\n";
    return 0;
} catch (const std::exception& error) { std::cerr<<error.what()<<'\n'; return 1; } }
