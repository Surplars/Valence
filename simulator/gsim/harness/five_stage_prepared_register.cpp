#include "I1PreparedRegisterQueueFixture.h"
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <stdexcept>
#include <string>

static void need(bool ok, const char* message) { if (!ok) throw std::runtime_error(message); }
int main(int argc, char** argv) { try {
    const bool wrong = argc > 1 && std::string(argv[1]) == "--wrong-payload";
    SI1PreparedRegisterQueueFixture d;
    std::deque<std::array<uint64_t,3>> expected;
    unsigned accepted=0, returned=0, full=0, simultaneous=0, idleNoise=0, resets=0;
    uint64_t random=0x51ab1e74827ULL;
    auto next=[&] { random^=random<<13; random^=random>>7; random^=random<<17; return random; };
    d.set_reset(1); d.set_io$$valid(0); d.set_io$$consume(0); d.step(); d.step();
    d.set_reset(0);
    for (unsigned cycle=0; cycle<24000; ++cycle) {
        const bool reset=cycle!=0 && cycle%4096==0;
        d.set_reset(reset);
        const unsigned phase=cycle%128;
        bool valid=phase<24 || (phase>=64 && (next()&3)!=0);
        bool ready=(phase>=24 && phase<48) || (phase>=64 && (next()&3)!=0);
        if (reset) { valid=false; ready=false; }
        std::array<uint64_t,3> data={next(),next(),next()};
        d.set_io$$valid(valid); d.set_io$$consume(ready);
        d.set_io$$data_0(data[0]); d.set_io$$data_1(data[1]); d.set_io$$data_2(data[2]);
        d.step();
        if (reset) { expected.clear(); ++resets; continue; }
        need(bool(d.get_io$$ready())==(expected.size()<2), "independent two-slot credit oracle");
        need(bool(d.get_io$$available())==!expected.empty() && d.get_io$$count()==expected.size(),
            "independent two-slot latency/count oracle");
        const bool push=valid && d.get_io$$ready(), pop=ready && d.get_io$$available();
        if (!expected.empty()) need(std::array<uint64_t,3>{d.get_io$$result_0(), d.get_io$$result_1(),
            d.get_io$$result_2()}==expected.front(), "independent prepared payload byte/order oracle");
        if (pop) { expected.pop_front(); ++returned; }
        if (push) { if (wrong && accepted==0) data[1]^=1; expected.push_back(data); ++accepted; }
        full+=!d.get_io$$ready(); simultaneous+=push&&pop; idleNoise+=!valid;
    }
    need(full>100 && simultaneous>100 && idleNoise>100 && resets==5, "missing queue stress coverage");
    std::cout<<"I1_PREPARED_REGISTER_PASS accepted="<<accepted<<" returned="<<returned<<" full="<<full
        <<" simultaneous="<<simultaneous<<" idle_noise="<<idleNoise<<" resets="<<resets
        <<" paired_cycle_equivalence=1 slots=2 payload_bits=192\n";
    return 0;
} catch (const std::exception& e) { std::cerr<<"FAIL: "<<e.what()<<'\n'; return 1; } }
