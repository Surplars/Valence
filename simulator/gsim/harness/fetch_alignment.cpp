#include "FetchAlignmentGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#ifndef FETCH_WIDTH
#define FETCH_WIDTH 2
#endif
static void check(bool ok,const char*m){if(!ok)throw std::runtime_error(m);}
int main(int argc,char**argv){try{
    bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    SFetchAlignmentGsim d;d.set_reset(0);std::mt19937_64 rng(0xf37c420261002ULL);
    uint64_t vectors=0, crossing=0, faultChecks=0;
    for(unsigned offset=0;offset<8;offset+=2)for(unsigned present=0;present<8;++present)
      for(unsigned errors=0;errors<64;++errors)for(unsigned pages=0;pages<64;++pages){
        uint64_t packet[3]={rng(),rng(),rng()};
        d.set_io$$packet0(packet[0]);d.set_io$$packet1(packet[1]);d.set_io$$packet2(packet[2]);
        d.set_io$$present(present);d.set_io$$errors(errors);d.set_io$$pages(pages);
        d.set_io$$offset(offset);d.step();
        uint32_t actual[4]={uint32_t(d.get_io$$instruction0()),uint32_t(d.get_io$$instruction1()),
          uint32_t(d.get_io$$instruction2()),uint32_t(d.get_io$$instruction3())};
        unsigned faults[4]={unsigned(d.get_io$$fault0()),unsigned(d.get_io$$fault1()),
          unsigned(d.get_io$$fault2()),unsigned(d.get_io$$fault3())};
        if(inject){actual[0]^=1;inject=false;}
        unsigned at=offset, valid=0,err=0,page=0;
        auto half=[&](unsigned byte){return uint16_t(packet[byte/8]>>(16*((byte%8)/2)));};
        for(unsigned lane=0;lane<FETCH_WIDTH;++lane){
            auto first=half(at);bool shortInst=(first&3)!=3;unsigned next=at+2;
            uint32_t want=first|(shortInst?0:uint32_t(half(next))<<16);
            bool has=(present>>(at/8))&1;
            has&=shortInst || ((present>>(next/8))&1);
            bool e=((errors>>(at/4))&1) || (!shortInst && ((errors>>(next/4))&1));
            bool p=((pages>>(at/4))&1) || (!shortInst && ((pages>>(next/4))&1));
            unsigned fault=(((errors|pages)>>(at/4))&1)?at:next;
            check(actual[lane]==want,"parallel fetch alignment data oracle mismatch");
            check(faults[lane]==fault,"parallel fetch alignment fault offset mismatch");
            valid|=unsigned(has)<<lane;err|=unsigned(e)<<lane;page|=unsigned(p)<<lane;
            crossing+=!shortInst && at/8!=next/8;faultChecks+=e||p;at+=shortInst?2:4;
        }
        check(d.get_io$$valid()==valid && d.get_io$$errorsOut()==err && d.get_io$$pagesOut()==page,
          "parallel fetch alignment validity/fault oracle mismatch");++vectors;
    }
    check(crossing && faultChecks,"parallel alignment coverage incomplete");
    std::cout<<"GSIM parallel fetch alignment: PASS width="<<FETCH_WIDTH<<" vectors="<<vectors
      <<" crossing="<<crossing<<" faults="<<faultChecks<<'\n';
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
