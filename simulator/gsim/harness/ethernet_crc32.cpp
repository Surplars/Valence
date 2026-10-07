#include "EthernetCrc32Gsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>

static uint32_t reference(uint32_t state, uint64_t data, unsigned bytes) {
    for (unsigned n=0; n<bytes; ++n) {
        state ^= uint8_t(data >> (8*n));
        for (unsigned b=0; b<8; ++b) state=(state>>1)^((state&1)?0xedb88320U:0U);
    }
    return state;
}
static void check(bool ok, const char *reason) { if(!ok) throw std::runtime_error(reason); }
int main(int argc, char **argv) { try {
    const bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    SEthernetCrc32Gsim d;
    std::mt19937_64 random(0x20261004c32ULL);
    unsigned vectors=0, invalid=0;
    auto probe=[&](uint32_t state,uint64_t data,unsigned mask) {
        unsigned count=0; while(count<8 && (mask&(1U<<count))) ++count;
        const bool legal=mask==((1U<<count)-1);
        uint32_t expected=legal?reference(state,data,count):state;
        if(inject && vectors==0) expected^=1;
        d.set_io$$state(state); d.set_io$$data(data); d.set_io$$keep(mask); d.step();
        check(d.get_io$$legal()==legal && uint32_t(d.get_io$$next())==expected &&
            uint32_t(d.get_io$$byteNext())==reference(state,data,1),"Ethernet CRC independent oracle mismatch");
        ++vectors; invalid+=!legal; return uint32_t(d.get_io$$next());
    };
    // Check values, every prefix and every sparse mask, using arbitrary CRC states.
    for(unsigned mask=0; mask<256; ++mask) for(unsigned n=0;n<32;++n) probe(random(),random(),mask);
    for(unsigned n=0;n<12000;++n) {
        unsigned count=n%9; probe(random(),random(),(1U<<count)-1);
    }
    uint32_t state=probe(0xffffffffU,0x3837363534333231ULL,255);
    state=probe(state,'9',1);
    check(~state==0xcbf43926U,"Ethernet CRC check-vector mismatch");
    state=probe(state,uint32_t(~state),15);
    check(state==0xdebb20e3U,"Ethernet FCS residue/byte-order mismatch");
    std::cout<<"ETHERNET_CRC32_PASS vectors="<<vectors<<" invalid_masks="<<invalid
        <<" check=cbf43926 residue=debb20e3\n";
    return 0;
} catch(const std::exception &e) { std::cerr<<e.what()<<'\n'; return 1; } }
