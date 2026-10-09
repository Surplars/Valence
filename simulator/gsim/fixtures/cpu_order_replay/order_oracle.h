#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
namespace order_oracle {
inline void require(bool ok,const std::string &message) { if(!ok)throw std::runtime_error("order oracle: "+message); }
constexpr uint64_t rom=0x80000000, overlap=0x80400000, cold=0x80401000, signature=0x80600000;
inline uint64_t value(uint64_t address) {
    if(address==overlap)return 0x1020304050607080ULL;
    for(unsigned i=0;i<4;++i)if(address==cold+64*i)return 0x8877665544332200ULL+i;
    throw std::runtime_error("order oracle: read outside independently known RAM");
}
inline int64_t sext(uint64_t n,unsigned bits) { return int64_t(n<<(64-bits))>>(64-bits); }
struct Architecture {
    std::vector<uint8_t> image;
    std::array<uint64_t,32> gpr{};
    uint64_t pc=rom, retired=0, loads=0, stores=0, signatureValue=0;
    explicit Architecture(std::vector<uint8_t> bytes={}):image(std::move(bytes)){}
    uint32_t instruction() const {
        require(pc>=rom && pc+4<=rom+image.size() && !(pc&3),"PC outside frozen guest");
        uint32_t v=0;for(unsigned i=0;i<4;++i)v|=uint32_t(image.at(pc-rom+i))<<(8*i);return v;
    }
    void retire(uint64_t observedPc) {
        require(observedPc==pc,"committed PC sequence mismatch");
        require(retired++<1024,"bounded architectural execution exceeded");
        const uint32_t w=instruction(); const unsigned op=w&127,rd=(w>>7)&31,f=(w>>12)&7,a=(w>>15)&31,b=(w>>20)&31,hi=w>>25;
        const uint64_t x=gpr[a],y=gpr[b]; const int64_t imm=sext(w>>20,12); uint64_t next=pc+4,result=0;bool writes=false;
        if(op==0x37){result=uint64_t(sext(w&0xfffff000U,32));writes=true;}
        else if(op==0x17){result=pc+uint64_t(sext(w&0xfffff000U,32));writes=true;}
        else if(op==0x13&&f==0){result=x+imm;writes=true;}
        else if(op==0x13&&f==1&&(w>>26)==0){result=x<<((w>>20)&63);writes=true;}
        else if(op==0x1b&&f==0){result=uint64_t(sext((x+imm)&0xffffffffU,32));writes=true;}
        else if((op==0x33||op==0x3b)&&f==5&&hi==1){
            if(op==0x33)result=y?x/y:~uint64_t(0);
            else result=uint64_t(sext(uint32_t(y)?uint32_t(x)/uint32_t(y):0xffffffffU,32));
            writes=true;
        } else if(op==0x03&&f==3){result=value(x+imm);writes=true;++loads;}
        else if(op==0x23&&f==3){
            const uint64_t address=x+sext(((w>>25)<<5)|((w>>7)&31),12);
            require(address==signature && y==value(overlap) && stores++==0,"signature store address/data/count mismatch");signatureValue=y;
        } else if(op==0x63&&f==0){
            const uint64_t off=((w>>31)<<12)|(((w>>7)&1)<<11)|(((w>>25)&63)<<5)|(((w>>8)&15)<<1);
            if(x==y)next=pc+sext(off,13);
        } else if(op==0x6f){
            const uint64_t off=((w>>31)<<20)|(((w>>12)&255)<<12)|(((w>>20)&1)<<11)|(((w>>21)&1023)<<1);
            result=pc+4;writes=true;next=pc+sext(off,21);
        } else if(op==0x0f&&(f==0||f==1)){}
        else throw std::runtime_error("order oracle: unsupported frozen guest instruction "+std::to_string(w));
        if(writes&&rd)gpr[rd]=result;
        gpr[0]=0;pc=next;
    }
    void compare(const std::array<uint64_t,32> &actual) const {
        for(unsigned r=0;r<32;++r)require(actual[r]==gpr[r],"committed register data mismatch x"+std::to_string(r));
    }
};
struct Token { uint64_t tag=0; unsigned index=0;bool operator==(const Token&)const=default; };
struct Replay {
    Token expected{}; bool selected=false,pending=false,accepted=false; uint64_t selectedCycle=0;
    void select(Token wanted,Token actual,uint64_t cycle) {require(!selected,"duplicate replay selection");require(wanted==actual,"selector full-token mismatch");expected=wanted;selected=true;selectedCycle=cycle;}
    void observePending(Token actual,uint64_t cycle) {require(selected&&cycle==selectedCycle+1,"missing selector to pending boundary");require(actual==expected,"pending full-token mismatch");pending=true;}
    void accept(Token actual) {require(pending,"missing registered pending replay");require(actual==expected,"accepted recovery full-token mismatch");accepted=true;}
    void verify() const {require(selected,"missing selector witness");require(pending,"missing pending witness");require(accepted,"missing accepted replay recovery");}
};
}
