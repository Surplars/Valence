#include "Axi4CdcSameClock.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
using Word = std::pair<uint64_t, uint16_t>;
int main(int argc, char **argv) { try {
    const bool negative = argc > 1 && std::string_view(argv[1]) == "--inject-mismatch";
    SAxi4CdcSameClock d;
    std::array<std::deque<Word>, 5> expected;
    std::array<Word, 5> offered{}, held{};
    std::array<bool, 5> pending{}, stalled{};
    std::array<unsigned, 5> sent{}, received{};
    std::mt19937_64 rng(0x41584934434443ULL);
    const unsigned width[5] = {61, 73, 6, 61, 71};
    auto drive = [&]() {
#define DRIVE(N) d.set_inData##N(offered[N].first); d.set_inMeta##N(offered[N].second)
        DRIVE(0); DRIVE(1); DRIVE(2); DRIVE(3); DRIVE(4);
#undef DRIVE
    };
    auto output = [&](unsigned n) -> Word {
#define READ(N) case N: return {d.get_outData##N(), uint16_t(d.get_outMeta##N())}
        switch(n) { READ(0); READ(1); READ(2); READ(3); READ(4); }
#undef READ
        throw std::runtime_error("invalid lane");
    };
    d.set_inValid(0); d.set_outReady(0); drive(); d.set_reset(1); d.step(); d.step(); d.set_reset(0);
    for (unsigned i=0;i<16;++i) d.step();
    bool changed = false;
    unsigned stalls=0, full=0;
    for (unsigned cycle=0;cycle<12000;++cycle) {
        unsigned valid=0, ready=0;
        for (unsigned n=0;n<5;++n) {
            // W starts well before AW; each return channel is independently blocked.
            if (!pending[n] && sent[n]<400 && (n!=0 || cycle>64) && rng()%4!=0) {
                offered[n]={rng(), uint16_t(rng())};
                if (width[n]<64) offered[n].first &= (uint64_t(1)<<width[n])-1;
                offered[n].second &= width[n]>64 ? (1U<<(width[n]-64))-1 : 0;
                pending[n]=true;
            }
            valid |= unsigned(pending[n])<<n;
            bool consume=cycle>100 && ((cycle/(37+n))%4!=1) && rng()%4!=0;
            ready |= unsigned(consume)<<n;
        }
        drive(); d.set_inValid(valid); d.set_outReady(ready); d.step();
        for (unsigned n=0;n<5;++n) {
            const bool ov=(d.get_outValid()>>n)&1, ir=(d.get_inReady()>>n)&1;
            if (pending[n] && ir) {
                expected[n].push_back(offered[n]); ++sent[n]; pending[n]=false;
            } else if (pending[n]) ++full;
            if (stalled[n] && (!ov || output(n)!=held[n]))
                throw std::runtime_error("AXI CDC held payload changed");
            if (ov) {
                Word actual=output(n);
                if (negative && !changed) { actual.first^=1; changed=true; }
                if (expected[n].empty() || expected[n].front()!=actual)
                    throw std::runtime_error("AXI CDC independent channel oracle mismatch");
                held[n]=output(n); stalled[n]=!((ready>>n)&1);
                if (stalled[n]) ++stalls;
                else { expected[n].pop_front(); ++received[n]; }
            } else stalled[n]=false;
        }
        bool done=true;
        for(unsigned n=0;n<5;++n) done &= received[n]==400 && expected[n].empty();
        if(done && d.get_empty()==3) {
            if(!full || !stalls) throw std::runtime_error("missing backpressure coverage");
            std::cout<<"PASS same-clock AXI channel conservation only; five lanes=2000 beats, stalled="
                     <<stalls<<", input_backpressure="<<full<<", cycles="<<cycle<<"; no dual-clock/owner-drain/physical qualification\n";
            return 0;
        }
    }
    throw std::runtime_error("AXI CDC conservation timeout");
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
