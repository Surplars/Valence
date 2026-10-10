#include "dmmu_observer.hpp"
#include <iostream>
#include <functional>
#include <vector>
using namespace dmmu;
static unsigned rejected=0;
void reject(const std::function<void()>&f){bool ok=false;try{f();}catch(const std::runtime_error&){ok=true;}need(ok,"D negative escaped");++rejected;}
std::vector<Sample> fixture(){std::vector<Sample>v(11);auto&r=v[0];r.incoming=r.req=r.active=true;r.va=0x40001000;r.mode=8;r.privilege=1;
 for(unsigned i=1;i<=4;++i){v[i].service=1;v[i].walker=i-1;}
 v[5].service=2;v[5].resp=v[5].enq=true;v[5].pa=0x80201000;
 v[6]=r;v[6].va=0x40001008;v[6].pa=0x80201008;v[6].fast=v[6].resp=v[6].enq=true;
 v[7].incoming=v[7].prechecked=true;v[8].checked=v[8].checkedPrechecked=true;return v;}
void play(std::vector<Sample>v){Observer o;for(unsigned i=0;i<v.size();++i)o.sample(v[i],i+10,i<9);o.finish(std::cout);}
int main(){auto v=fixture();for(const auto&mut:std::vector<std::function<void(std::vector<Sample>&)>>{
 [](auto&v){v[1].walker=1;},[](auto&v){v[2].walker=0;},[](auto&v){v[0].incoming=false;},[](auto&v){v[0].fast=true;},
 [](auto&v){v[0].active=false;},[](auto&v){v[0].prechecked=true;},[](auto&v){v[1].pa=3;},
 [](auto&v){v[5].enq=false;},[](auto&v){v[5].service=1;},[](auto&v){v[6].resp=false;},
 [](auto&v){v[2]=v[0];},[](auto&v){v[7].incoming=false;},[](auto&v){v[8].checked=false;}}){auto bad=v;mut(bad);reject([&]{play(bad);});}
 {Observer o;reject([&]{o.accept(v[5],15,false);});}play(v);std::cout<<"D_CONTROLS rejected="<<rejected<<"\n";}
