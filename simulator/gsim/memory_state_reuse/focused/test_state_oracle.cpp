#include "memory_state_oracle.h"
#include <iostream>
using namespace memory_state_oracle;
template<class F> void rejects(F f) { bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}check(rejected,"poison was not rejected"); }
int main(){
    Oracle o;
    o.allocate({{63,7},true,true,false,0x40000003,0});
    o.store({63,7},false);o.verify(63,7,true,0x40000003,8);
    rejects([&]{o.verify(63,7,true,0x80200000,255);}); // Unsafe store-start alias write.
    rejects([&]{o.load({63,7},false,true,false,true,0x80200003,0x10040000,8);});
    rejects([&]{o.store({63,7},true);});
    o.allocate({{63,(1ULL<<63)+7},true,false,false,0x40000100,3});
    rejects([&]{o.store({63,7},false);}); // Full high tag, same index.
    rejects([&]{o.verify(63,7,true,0x40000003,8);});
    o.load({63,(1ULL<<63)+7},false,false,false,true,0x80200100,0x80200100>>3,255);
    o.verify(63,(1ULL<<63)+7,true,0x80200100,255);
    rejects([&]{o.load({63,(1ULL<<63)+7},false,false,false,true,0x80200100,0,255);});
    o.allocate({{0,9},true,true,false,0x40000006,1});o.store({0,9},false);
    o.allocate({{1,10},true,true,false,0x40000004,2});o.store({1,10},false);
    o.verify(0,9,true,0x40000006,192);o.verify(1,10,true,0x40000004,240);
    o.verify(63,(1ULL<<63)+7,true,0x80200100,255);
    o.allocate({{0,11},true,false,true,0x40000006,1});
    rejects([&]{o.load({0,11},false,false,true,true,0x80200006,0x80200006>>3,192);});
    std::cout<<"MEMORY_STATE_ORACLE_PASS positive lifecycle + 8 rejecting poisons\n";
}
