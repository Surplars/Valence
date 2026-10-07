#include "EthernetResetHoldGsim.h"
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
int main(int argc, char** argv) { try {
    bool inject=argc==2 && std::string_view(argv[1])=="--inject-mismatch";
    SEthernetResetHoldGsim d;
    std::mt19937 random(0x20261004);
    unsigned checks=0;
    for(unsigned epoch=0;epoch<20;++epoch) {
        d.set_io$$macIrq(0); d.set_io$$bufferIrq(0);
        d.set_reset(1); d.step(); d.step(); d.set_reset(0);
        bool last=false;
        for(unsigned cycle=0;cycle<64;++cycle) {
            bool a=random()&1, b=random()&1;
            d.set_io$$macIrq(a); d.set_io$$bufferIrq(b); d.step();
            // cycle is zero-based: release AFTER the seventh local rising edge.
            bool held=(cycle+1)<7;
            if(inject && epoch==0 && cycle==3) held=!held;
            if(bool(d.get_io$$held())!=held || bool(d.get_io$$irq())!=last) {
                std::cerr<<"epoch="<<epoch<<" cycle="<<cycle<<" held="<<bool(d.get_io$$held())
                         <<" expected="<<held<<" irq="<<bool(d.get_io$$irq())<<" expected_irq="<<last<<'\n';
                throw std::runtime_error("Ethernet reset/IRQ independent oracle mismatch");
            }
            last=a||b; ++checks;
        }
    }
    std::cout<<"ETHERNET_RESET_IRQ_PASS checks="<<checks<<" reset_epochs=20 hold_edges=7\n";
    return 0;
} catch(const std::exception &e) {std::cerr<<e.what()<<'\n'; return 1;} }
