#pragma once
#include <cstdint>
#include <cstddef>
#include <stdexcept>
// Host-only decoding of schema-pinned generated registers. These count retained
// cache miss owners, including completed results awaiting CPU acceptance.
// They are not AXI transactions, stalled loads, or a synthesized RTL counter.
struct MshrOccupancy {
    template<std::size_t N> static unsigned nonblocking(const uint8_t (&phase)[N]) {
        static_assert(N == 2 || N == 4);
        unsigned count=0;
        for(auto p:phase) { if(p>4) throw std::runtime_error("MSHR phase schema mismatch");count+=p!=0; }
        return count;
    }
    template<std::size_t N> static unsigned refilling(const uint8_t (&phase)[N]) {
        (void)nonblocking(phase);unsigned count=0;for(auto p:phase)count+=p==2||p==3;return count;
    }
    static unsigned legacy(uint8_t state,uint8_t resume,bool flush,bool bypass) {
        if(state>11||resume>11) throw std::runtime_error("legacy MSHR phase schema mismatch");
        if(flush||bypass)return 0;
        const auto p=(state==9||state==10)?resume:state;
        return p>=1&&p<=6;
    }
    static unsigned legacyRefilling(uint8_t state,uint8_t resume,bool flush,bool bypass) {
        if(!legacy(state,resume,flush,bypass))return 0;
        const auto p=(state==9||state==10)?resume:state;return p==4||p==5;
    }
    static void selfTest() {
        uint8_t phases[2]={0,0};
        if(nonblocking(phases))throw std::runtime_error("empty occupancy decode");
        phases[0]=1;phases[1]=4;
        if(nonblocking(phases)!=2||phases[0]!=1||phases[1]!=4)throw std::runtime_error("occupied decode changed source");
        if(refilling(phases))throw std::runtime_error("completed/victim owner counted as refill");
        phases[0]=2;phases[1]=3;
        if(refilling(phases)!=2)throw std::runtime_error("acquire/fill phase decode");
        phases[1]=5;bool rejected=false;
        try{(void)nonblocking(phases);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected||legacy(0,0,false,false)||legacy(4,0,true,false)||legacy(4,0,false,true)||
            legacy(4,0,false,false)!=1||legacy(9,5,false,false)!=1)
            throw std::runtime_error("occupancy decoder negative/reset contract");
    }
};
