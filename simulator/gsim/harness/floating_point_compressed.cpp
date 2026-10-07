#include "FloatingPointCompressedGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
static void check(bool value,const char* why) {if(!value) throw std::runtime_error(why);}
int main() {try {
    SFloatingPointCompressedGsim d;unsigned count=0;
    for(unsigned inst=0;inst<65536;++inst) {
        unsigned q=inst&3, f3=inst>>13;
        if((q!=0&&q!=2)||(f3!=1&&f3!=5))continue;
        bool store=f3==5;unsigned rd=(inst>>7)&31, rs2=(inst>>2)&31;
        unsigned prime=8+((inst>>2)&7), base=8+((inst>>7)&7);
        unsigned offset;
        if(q==0)offset=(((inst>>5)&3)<<6)|(((inst>>10)&7)<<3);
        else if(store)offset=(((inst>>7)&7)<<6)|(((inst>>10)&7)<<3);
        else offset=(((inst>>2)&7)<<6)|(((inst>>12)&1)<<5)|(((inst>>5)&3)<<3);
        unsigned target=q==0?prime:store?rs2:rd, address=q==0?base:2;
        uint32_t expected=store?((offset>>5)<<25)|(target<<20)|(address<<15)|(3<<12)|((offset&31)<<7)|0x27:
            (offset<<20)|(address<<15)|(3<<12)|(target<<7)|7;
        d.set_io$$instruction(inst);d.step();
        check(d.get_io$$legal()&&!d.get_io$$disabledLegal(),"compressed FP enable/disable");
        check(d.get_io$$expanded()==expected,"independent compressed immediate/register expansion");
        ++count;
    }
    check(count==8192,"exhaustive compressed count");
    std::cout<<"FP_COMPRESSED_PASS encodings=8192 disabled_illegal=8192 f0_stack_load=legal\n";
    return 0;
} catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}

