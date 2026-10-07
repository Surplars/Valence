#pragma once
#include <algorithm>
#include <cstdint>
#include <vector>

// Independent sequential, reflected software CRC; no DUT tables or XOR matrix.
inline uint32_t ethernetReferenceCrc(const std::vector<uint8_t>& bytes) {
    uint32_t crc=0xffffffff;
    for(auto byte:bytes) for(unsigned bit=0;bit<8;++bit) {
        const bool feedback=(crc^(byte>>bit))&1;
        crc>>=1;if(feedback)crc^=0xedb88320;
    }
    return ~crc;
}
inline std::vector<uint8_t> ethernetBody(unsigned length,unsigned seed=0) {
    std::vector<uint8_t> body(length);
    for(unsigned n=0;n<length;++n)body[n]=(n*73+seed*19+11)^(n>>3);
    static constexpr uint8_t address[]{2,0x11,0x22,0x33,0x44,0x55};
    for(unsigned n=0;n<std::min(6U,length);++n)body[n]=address[n];
    if(length>=14){body[12]=8;body[13]=0;}
    return body;
}
inline std::vector<uint8_t> ethernetWire(std::vector<uint8_t> body,bool pad=true) {
    if(pad && body.size()<60)body.resize(60,0);
    const uint32_t fcs=ethernetReferenceCrc(body);
    std::vector<uint8_t> wire(7,0x55);wire.push_back(0xd5);
    wire.insert(wire.end(),body.begin(),body.end());
    for(unsigned n=0;n<4;++n)wire.push_back(fcs>>(8*n));
    return wire;
}
