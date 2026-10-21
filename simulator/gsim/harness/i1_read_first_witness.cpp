#include "I1ReadFirstWitness.h"
#include <iostream>
#include <stdexcept>
int main(int argc,char**){
    try {
        SI1ReadFirstWitness d;
        // Do not observe uninitialized RAM. Seed and settle one synchronous read.
        d.set_write(1);d.set_data(11);d.step();
        d.set_write(0);d.step();d.step();
        if(d.get_result()!=11)throw std::runtime_error("ReadFirst seed oracle");
        for(unsigned n=0;n<32;++n){
            const uint64_t old=11+n,newValue=old+1;
            d.set_write(1);d.set_data(newValue);d.step();
            if(d.get_result()!=(argc>1?newValue:old))
                throw std::runtime_error("independent same-address ReadFirst oracle");
            d.set_write(0);d.step();
            if(d.get_result()!=newValue)throw std::runtime_error("ReadFirst publication oracle");
        }
        std::cout<<"I1_READ_FIRST_PASS collisions=32\n";return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<"\n";return 1;}
}
