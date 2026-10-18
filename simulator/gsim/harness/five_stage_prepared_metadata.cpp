#include "I1PreparedMetadataFixture.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>

#ifndef I1_METADATA_ENTRIES
#define I1_METADATA_ENTRIES 4
#endif
static void need(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
int main(int argc, char** argv) { try {
    const bool wrong = argc > 1 && std::string(argv[1]) == "--wrong-lane";
    SI1PreparedMetadataFixture d;
    std::deque<unsigned> expected;
    unsigned accepted=0, returned=0, full=0, simultaneous=0, idleNoise=0, resets=0;
    uint64_t random=0x51ab1e74827ULL;
    auto next=[&] { random ^= random<<13; random ^= random>>7; random ^= random<<17; return random; };
    d.set_reset(1); d.set_io$$enq$$valid(0); d.set_io$$deq$$ready(0); d.step(); d.step();
    d.set_reset(0);
    for(unsigned cycle=0; cycle<24000; ++cycle) {
        const bool reset=cycle!=0 && cycle%4096==0;
        d.set_reset(reset);
        // Long full/stalled bursts, empty/no-VALID noise, simultaneous I/O,
        // pointer wrap and reset while occupied. VALID obeys no data assumptions.
        unsigned phase=cycle%128;
        bool valid=phase<24 || (phase>=64 && (next()&3)!=0);
        bool ready=(phase>=24 && phase<48) || (phase>=64 && (next()&3)!=0);
        // The pinned GSIM computes next-state after its reset pass. Quiesce
        // the producer/consumer during reset, as all active I1 harnesses do.
        // Reset still discards an occupied FIFO; no valid owner survives it.
        if(reset) { valid=false; ready=false; }
        unsigned data=next()&15;
        d.set_io$$enq$$valid(valid); d.set_io$$enq$$bits(data); d.set_io$$deq$$ready(ready);
        d.step();
        if(reset) { expected.clear(); ++resets; continue; }
        need(bool(d.get_io$$enq$$ready())==(expected.size()<I1_METADATA_ENTRIES),
            "independent metadata FIFO capacity oracle");
        if(bool(d.get_io$$deq$$valid())!=!expected.empty() || d.get_io$$count()!=expected.size()) {
            std::cerr<<"cycle="<<cycle<<" expected_count="<<expected.size()<<" actual_count="
                <<unsigned(d.get_io$$count())<<" valid="<<d.get_io$$deq$$valid()<<"\n";
            throw std::runtime_error("independent metadata FIFO latency/count oracle");
        }
        bool push=valid && d.get_io$$enq$$ready();
        bool pop=ready && d.get_io$$deq$$valid();
        if(!expected.empty()) need(d.get_io$$deq$$bits()==expected.front(),
            "independent metadata accepted-lane oracle");
        if(pop) { expected.pop_front(); ++returned; }
        if(push) { expected.push_back(data ^ ((wrong && accepted==0)?1:0)); ++accepted; }
        full+=!d.get_io$$enq$$ready(); simultaneous+=push&&pop; idleNoise+=!valid;
    }
    need(full>100 && simultaneous>100 && idleNoise>100 && resets==5,
        "missing independent FIFO stress coverage");
    std::cout<<"I1_PREPARED_METADATA_PASS entries="<<I1_METADATA_ENTRIES<<" accepted="<<accepted
        <<" returned="<<returned<<" full="<<full<<" simultaneous="<<simultaneous
        <<" idle_noise="<<idleNoise<<" resets="<<resets<<" paired_cycle_equivalence=1\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<"\n"; return 1; } }
