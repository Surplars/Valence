#include "passive.hpp"
#include <iostream>
using namespace posted_board;
static void end(AxiAccounting&a){a.sample({},Window::Kernel);a.sample({},Window::Flush);a.sample({},Window::None);a.finish();}
int main(){try{
    bandwidth::EdgeClock a;a.sample(10);a.sample(11);a.sample(12);unsigned rejected=0;
    for(auto bad:{12ULL,14ULL}){auto c=a;try{c.sample(bad);}catch(const std::runtime_error&){++rejected;}}
    for(unsigned control=0;control<4;++control){AxiAccounting l;AxiSample ar,r,aw,w,b;
        ar.arValid=ar.arReady=true;ar.arId=1;ar.arSize=3;
        r.rValid=r.rReady=r.rLast=true;r.rId=1;
        aw.awValid=aw.awReady=true;aw.awId=1;aw.awSize=3;
        w.wValid=w.wReady=w.wLast=true;w.wStrobe=255;
        b.bValid=b.bReady=true;b.bId=1;
        try{
            if(control<2){l.sample(ar,Window::None);if(control==0){l.sample(r,Window::None);l.sample(r,Window::None);}else end(l);}
            else {l.sample(aw,Window::None);l.sample(w,Window::None);if(control==2){l.sample(b,Window::None);l.sample(b,Window::None);}else end(l);}
        }catch(const std::runtime_error&){++rejected;}
    }
    {AxiAccounting read;read.sample({},Window::Kernel);read.sample({},Window::None);read.finish(false);}
    try{AxiAccounting read;read.sample({},Window::Kernel);read.sample({},Window::Flush);read.sample({},Window::None);read.finish(false);}catch(const std::runtime_error&){++rejected;}
    try{AxiAccounting read;read.sample({},Window::Kernel);read.sample({},Window::None);read.finish();}catch(const std::runtime_error&){++rejected;}
    if(rejected!=8)throw std::runtime_error("edge/duplicate/omitted-owner control escaped");
    std::cout<<"PASS passive controls edge_duplicate=1 gap_omitted_edge=1 duplicate_R=1 omitted_R_owner=1 duplicate_B=1 omitted_B_owner=1\n";
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
