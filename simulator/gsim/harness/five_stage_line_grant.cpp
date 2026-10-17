#include "I1LineGrantTransportFixture.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>

#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void need(bool p,const char* why){if(!p)throw std::runtime_error(why);}
int main(int argc,char**argv){try{
    SI1LineGrantTransportFixture d;
    const bool wrong=argc>1&&std::string(argv[1])=="--wrong-word";
    const bool badSource=argc>1&&std::string(argv[1])=="--wrong-source";
    S(request$$valid,0);S(a$$ready,0);S(e$$ready,0);S(grantValid,0);S(responseReady,0);
    S(source,0);S(sink,0);S(cap,0);S(denied,0);S(corrupt,0);
    S(word0,0);S(word1,0);S(word2,0);S(word3,0);S(word4,0);S(word5,0);S(word6,0);S(word7,0);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    unsigned grants=0,ackStalls=0,resultStalls=0,denied=0,corrupt=0;
    for(unsigned n=0;n<192;++n){
        std::array<uint64_t,8> words{};
        for(unsigned b=0;b<8;++b)words[b]=0xb6e79130a4c85df2ULL^
            (uint64_t(n)*0x9e3779b97f4a7c15ULL)^(uint64_t(b)*0x102040810204081ULL);
        S(word0,words[0]);S(word1,words[1]);S(word2,words[2]);S(word3,words[3]);
        S(word4,words[4]);S(word5,words[5]);S(word6,words[6]);S(word7,words[7]);
        const bool deny=n%3==1,broken=n%3==2;
        S(denied,deny);S(corrupt,broken);S(sink,n&1);S(cap,0);
        S(request$$bits$$address,0x80200000ULL+n*64);
        S(request$$bits$$tag,n);S(request$$bits$$grow,1);S(request$$bits$$permissionOnly,0);
        bool allocated=false,sent=false,granted=false,acked=false,done=false;
        unsigned source=0;
        for(unsigned c=0;c<200&&!done;++c){
            S(request$$valid,!allocated);S(a$$ready,c>=3);
            S(grantValid,sent&&!granted);S(source,badSource?7:source);
            S(e$$ready,c>=17);S(responseReady,c>=27);
            d.step();
            if(!allocated&&G(request$$ready))allocated=true;
            if(G(a$$valid)&&c>=3){
                need(allocated&&!sent&&G(a$$bits$$address)==0x80200000ULL+n*64&&
                     G(a$$bits$$opcode)==6,"independent whole-grant A owner");
                source=G(a$$bits$$source);sent=true;
            }
            if(sent&&!granted&&G(grantReady)){granted=true;++grants;}
            if(G(e$$valid)){
                need(granted&&G(e$$bits$$sink)==(n&1),"independent whole-grant E identity");
                if(c>=17)acked=true;else ++ackStalls;
            }
            if(G(responseValid)){
                need(acked&&G(responseTag)==n&&bool(G(responseError))==(deny||broken),
                     "whole grant exposed data before genuine E acknowledgement or lost error");
                const std::array<uint64_t,8> actual{G(result0),G(result1),G(result2),G(result3),
                    G(result4),G(result5),G(result6),G(result7)};
                if(wrong)words[5]^=1;
                need(actual==words,"independent whole-grant eight-word/error oracle");
                if(c>=27)done=true;else ++resultStalls;
            }
        }
        need(done,"whole-grant bounded completion");denied+=deny;corrupt+=broken;
        S(request$$valid,0);S(grantValid,0);S(e$$ready,1);S(responseReady,1);d.step();
    }
    need(grants==192&&denied==64&&corrupt==64&&ackStalls>100&&resultStalls>100,
        "whole-grant independent coverage");
    std::cout<<"I1_LINE_GRANT_PASS transactions="<<grants<<" denied="<<denied<<" corrupt="<<corrupt
        <<" E_stalls="<<ackStalls<<" response_stalls="<<resultStalls
        <<" existing_sources=2 no_early_completion=1\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
