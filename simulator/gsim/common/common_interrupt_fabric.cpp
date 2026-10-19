#include "CommonInterruptFabric.h"
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>

static void check(bool good, const char* message) { if (!good) throw std::runtime_error(message); }
struct Driver {
    SCommonInterruptFabric dut;
    std::mt19937 random{3719};
    struct Completion { unsigned due; bool error; };
    std::deque<Completion> completions;
    std::map<std::pair<uint64_t,uint64_t>, unsigned> expected;
    unsigned cycles=0, deliveries=0, held=0, responses=0, delay=7, consecutive=0, maxConsecutive=0;
    bool block=false, holdResponses=false, expectedError=false, nextError=false, inject=false, randomReady=true;
    bool previousHeld=false;
    uint64_t previousAddress=0, previousData=0;
    Driver() {
        dut.set_io$$sources(0);
        dut.set_io$$machineRegisters$$request$$valid(0);
        dut.set_io$$supervisorRegisters$$request$$valid(0);
        dut.set_io$$machineRegisters$$response$$ready(0);
        dut.set_io$$supervisorRegisters$$response$$ready(0);
        dut.set_io$$msi$$request$$ready(0); dut.set_io$$msi$$response$$valid(0);
        dut.set_io$$msi$$response$$bits$$data(0); dut.set_io$$msi$$response$$bits$$error(0);
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
    }
    void tick() {
        bool ready=!block && (!randomReady || random()%4);
        bool reply=!holdResponses && !completions.empty() && completions.front().due<=cycles;
        dut.set_io$$msi$$request$$ready(ready);
        dut.set_io$$msi$$response$$valid(reply);
        dut.set_io$$msi$$response$$bits$$error(reply && completions.front().error);
        dut.step();
        if (previousHeld) check(dut.get_io$$msi$$request$$valid() &&
            dut.get_io$$msi$$request$$bits$$address()==previousAddress &&
            dut.get_io$$msi$$request$$bits$$data()==previousData, "held MSI changed");
        previousHeld=dut.get_io$$msi$$request$$valid() && !ready;
        previousAddress=dut.get_io$$msi$$request$$bits$$address();
        previousData=dut.get_io$$msi$$request$$bits$$data();
        held+=previousHeld;
        if (reply && dut.get_io$$msi$$response$$ready()) {
            expectedError|=completions.front().error; completions.pop_front(); ++responses;
        }
        if (dut.get_io$$msi$$request$$valid() && ready) {
            check(dut.get_io$$msi$$request$$bits$$write() &&
                dut.get_io$$msi$$request$$bits$$size()==2 &&
                dut.get_io$$msi$$request$$bits$$byteEnable()==15, "MSI format mismatch");
            auto key=std::make_pair(previousAddress,previousData^(inject?1:0)); inject=false;
            check(expected[key]>0, "MSI identity/address oracle mismatch"); --expected[key];
            completions.push_back({cycles+delay,nextError}); nextError=false; ++deliveries;
            ++consecutive; maxConsecutive=std::max(maxConsecutive,consecutive);
        } else consecutive=0;
        ++cycles;
        check(cycles<20000, "bounded completion failure");
    }
    void idle(unsigned count) { while(count--) tick(); }
    void access(bool supervisor,unsigned offset,uint32_t data,bool write=true,uint64_t expectedRead=0) {
        // Independent MMIO owner on each domain, with response backpressure.
#define SET(field,value) do { if(supervisor) dut.set_io$$supervisorRegisters##field(value); else dut.set_io$$machineRegisters##field(value); } while(0)
#define GET(field) (supervisor?dut.get_io$$supervisorRegisters##field():dut.get_io$$machineRegisters##field())
        SET($$request$$bits$$address,(supervisor?0x0c004000ULL:0x0c000000ULL)+offset);
        SET($$request$$bits$$write,write); SET($$request$$bits$$size,2);
        SET($$request$$bits$$byteEnable,15); SET($$request$$bits$$data,data);
        SET($$response$$ready,0); SET($$request$$valid,1);
        do {tick();} while(!GET($$request$$ready));
        SET($$request$$valid,0); idle(3); SET($$response$$ready,1);
        do {tick();} while(!GET($$response$$valid));
        check(!GET($$response$$bits$$error),"MMIO error");
        check(GET($$response$$bits$$data)==(write?0:expectedRead),"MMIO response oracle mismatch");
        SET($$response$$ready,0);
#undef SET
#undef GET
    }
    void drain() {
        for (;;) {
            bool pending=!completions.empty();
            for(auto [key,count]:expected) pending|=count!=0;
            if(!pending) break;
            tick();
        }
        idle(10); check(bool(dut.get_io$$msiError())==expectedError,"MSI response error lost");
    }
    void configure() {
        access(false,0,256); access(true,0,256);
        access(false,3*4,4); access(false,0x3000+3*4,11); access(false,0x1edc,3);
        access(false,4*4,1024); // Delegate source 4 to the supervisor domain.
        access(true,4*4,4); access(true,0x3000+4*4,19); access(true,0x1edc,4);
        access(false,0x1bc0,0,false,0x24000); access(true,0x1bc0,0,false,0x28000);
        access(false,0x1bc8,0,false,0x28000);
    }
    void run() {
        // A common cold reset cancels the entire epoch, including a selected
        // held offer. Inputs may withdraw only across that reset, never while locked.
        configure(); block=true;
        ++expected[{0x24000000,11}]; access(false,0x1cdc,3); idle(8);
        check(previousHeld,"reset scenario never established a locked offer");
        dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        expected.clear(); completions.clear(); previousHeld=false; block=false;
        idle(8); check(!dut.get_io$$msi$$request$$valid(),"cold reset retained stale MSI offer");
        configure(); block=true; holdResponses=true;
        ++expected[{0x24000000,11}]; ++expected[{0x28000000,19}];
        access(false,0x1cdc,3); access(true,0x1cdc,4); idle(20);
        check(deliveries==0 && held>0,"blocked MSI was acknowledged early");
        block=false; idle(30); check(deliveries==2 && responses==0,"both domains did not retain response owners");
        holdResponses=false; drain();
        for(unsigned i=0;i<12;++i) {
            ++expected[{0x24000000,11}]; ++expected[{0x28000000,19}];
            access(false,0x1cdc,3); access(true,0x1cdc,4); drain();
        }
        // Exercise physical source sampling and root-to-child delegation as well as set-pending MMIO.
        ++expected[{0x24000000,11}]; ++expected[{0x28000000,19}];
        dut.set_io$$sources((1ULL<<2)|(1ULL<<3)); idle(5);
        dut.set_io$$sources(0); drain();
        // Both domains continuously offer distinct identities. With a ready
        // consumer and one-cycle responses the selection lock must retain II=1.
        block=true; delay=1; randomReady=false;
        for(unsigned i=10;i<18;++i) {
            access(false,4*i,1); access(false,0x3000+4*i,40+i); access(false,0x1edc,i);
            ++expected[{0x24000000,40+i}];
        }
        for(unsigned i=20;i<28;++i) {
            access(false,4*i,1024); access(true,4*i,1);
            access(true,0x3000+4*i,80+i); access(true,0x1edc,i);
            ++expected[{0x28000000,80+i}];
        }
        access(false,0x1c00,0xffU<<10); access(true,0x1c00,0xffU<<20); idle(8);
        maxConsecutive=0; block=false; drain();
        check(maxConsecutive>=12,"shared MSI arbiter lost no-stall II=1 streaming");
        nextError=true; ++expected[{0x28000000,19}]; access(true,0x1cdc,4); drain();
        check(deliveries==45 && responses==45 && expectedError,"completion ledger mismatch");
        std::cout<<"COMMON_INTERRUPT_FABRIC_PASS cycles="<<cycles<<" msi="<<deliveries
                 <<" responses="<<responses<<" held="<<held<<" max_consecutive="<<maxConsecutive<<"\n";
    }
};
int main(int argc,char**argv) {
    try { Driver d; d.inject=argc>1 && std::string(argv[1])=="--inject-mismatch"; d.run(); return 0; }
    catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; }
}
