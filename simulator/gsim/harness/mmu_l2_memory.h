#pragma once
#include <cstdint>
#include <stdexcept>
#include <string>
#include <map>
namespace virtual_load_test {
constexpr uint64_t ram=0x80000000ULL, va=0x40000000ULL, root=0x81000000ULL;
constexpr uint64_t satp=(8ULL<<60)|(7ULL<<44)|(root>>12), allPmp=(1ULL<<54)-1;
inline void require(bool v,const std::string& s){if(!v)throw std::runtime_error(s);}
inline uint64_t readValue(uint64_t a){return 0x3a197fe20864bd55ULL^((a&~7ULL)*0x0102040810204081ULL);}
struct PageTables {
    uint64_t rootAddress=root; bool huge=false;
    std::map<unsigned,unsigned> flags;
    std::map<unsigned,uint64_t> physicals;
    uint64_t pte(uint64_t a) const {
        if(a==rootAddress+8)return ((rootAddress+4096)>>2)|1;
        if(a==rootAddress+4096 || a==rootAddress+4104) {
            if(huge)return (ram>>2)|0xc7;
            return ((rootAddress+(a==rootAddress+4096?8192:12288))>>2)|1;
        }
        for(unsigned stream=0;stream<2;stream++) {
            uint64_t table=rootAddress+8192+4096*stream;
            uint64_t first=stream?64:32;
            if(a>=table+first*8 && a<table+(first+256)*8 && !(a&7)) {
                uint64_t n=(a-table)/8-first;
                unsigned key=(stream?512:0)+first+n;
                uint64_t pa=physicals.count(key)?physicals.at(key):ram+(stream?0x40000:0x20000)+4096*n;
                unsigned attr=flags.count(key)?flags.at(key):0xc7;
                return (pa>>2)|attr;
            }
        }
        throw std::runtime_error("unexpected page table read "+std::to_string(a));
    }
};
}
