#include "AiaSupervisorUartGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>

static void check(bool ok,const char*message){if(!ok)throw std::runtime_error(message);}
static SAiaSupervisorUartGsim dut;

static void idle(bool rx=true){dut.set_io$$uartRx(rx);dut.step();}
static void defaults(){
    dut.set_io$$machine$$request$$valid(0);dut.set_io$$machine$$response$$ready(1);
    dut.set_io$$supervisor$$request$$valid(0);dut.set_io$$supervisor$$response$$ready(1);
    dut.set_io$$uartRegisters$$request$$valid(0);dut.set_io$$uartRegisters$$response$$ready(1);
    dut.set_io$$csrRequest$$valid(0);dut.set_io$$csrResponse$$ready(1);
    dut.set_io$$uartRx(1);
}
static uint64_t registerAccess(unsigned port,uint64_t address,bool write,uint32_t data=0){
    bool accepted=false;
    for(unsigned cycle=0;cycle<100;++cycle){
#define DRIVE(name) \
        dut.set_io$$##name##$$request$$valid(!accepted); \
        dut.set_io$$##name##$$request$$bits$$address(address); \
        dut.set_io$$##name##$$request$$bits$$write(write); \
        dut.set_io$$##name##$$request$$bits$$size(port==2?0:2); \
        dut.set_io$$##name##$$request$$bits$$data(data); \
        dut.set_io$$##name##$$request$$bits$$byteEnable(port==2?1:15)
        switch(port){case 0: DRIVE(machine);break;case 1: DRIVE(supervisor);break;
            default: DRIVE(uartRegisters);break;}
#undef DRIVE
        idle();
        bool ready=false,valid=false,error=false;uint64_t result=0;
#define SAMPLE(name) \
        ready=dut.get_io$$##name##$$request$$ready(); \
        valid=dut.get_io$$##name##$$response$$valid(); \
        error=dut.get_io$$##name##$$response$$bits$$error(); \
        result=dut.get_io$$##name##$$response$$bits$$data()
        switch(port){case 0: SAMPLE(machine);break;case 1: SAMPLE(supervisor);break;
            default: SAMPLE(uartRegisters);break;}
#undef SAMPLE
        if(!accepted && ready)accepted=true;
        if(valid){check(accepted && !error,"register transaction failed");defaults();return result;}
    }
    throw std::runtime_error("register transaction timeout");
}
static uint64_t csr(unsigned selector,unsigned operation,uint64_t data=0,bool topei=false){
    bool accepted=false;
    for(unsigned cycle=0;cycle<100;++cycle){
        dut.set_io$$csrRequest$$valid(!accepted);
        dut.set_io$$csrRequest$$bits$$file(1);
        dut.set_io$$csrRequest$$bits$$selector(selector);
        dut.set_io$$csrRequest$$bits$$operation(operation);
        dut.set_io$$csrRequest$$bits$$data(data);
        dut.set_io$$csrRequest$$bits$$topei(topei);
        idle();
        if(!accepted && dut.get_io$$csrRequest$$ready())accepted=true;
        if(dut.get_io$$csrResponse$$valid()){
            check(accepted && !dut.get_io$$csrResponse$$bits$$error(),"IMSIC CSR transaction failed");
            const auto result=dut.get_io$$csrResponse$$bits$$data();
            dut.set_io$$csrRequest$$valid(0);return result;
        }
    }
    throw std::runtime_error("IMSIC CSR transaction timeout");
}
static void sendByte(uint8_t value){
    for(unsigned bit=0;bit<10;++bit){
        const bool level=bit==0?false:bit==9?true:((value>>(bit-1))&1)!=0;
        for(unsigned n=0;n<16;++n)idle(level);
    }
    for(unsigned n=0;n<24;++n)idle();
}
int main(){try{
    defaults();dut.set_reset(1);idle();idle();dut.set_reset(0);
    constexpr uint64_t m=0x0c000000,s=0x0c004000,u=0x10000000;
    check(registerAccess(0,m+0x1bc8,false)==0x28000,"S MSI address configuration");
    registerAccess(0,m+12,true,0x400); // Delegate UART source 3 to child index 0.
    check(registerAccess(0,m+12,false)==0x400 && (dut.get_io$$childEnabled()&4),
          "M root did not delegate UART source");
    registerAccess(1,s+12,true,4); // Active high level.
    registerAccess(1,s+0x300c,true,3); // S identity 3.
    registerAccess(1,s+0x1edc,true,3);
    registerAccess(1,s,true,0x100);
    csr(0x70,1,1); // S eidelivery.
    csr(0xc0,1,1U<<3); // S eie[3].
    registerAccess(2,u+1,true,1); // UART receive interrupt enable.
    sendByte('Z');
    check(!dut.get_io$$machineInterrupt() && dut.get_io$$supervisorInterrupt(),
          "UART interrupt did not reach only the S IMSIC file");
    check(registerAccess(2,u,false)=='Z',"UART RBR data mismatch");
    check(csr(0,1,0,true)==0x30003,"S TOPEI did not claim UART identity 3");
    for(unsigned n=0;n<20;++n)idle();
    check(!dut.get_io$$supervisorInterrupt(),"S interrupt did not clear after claim");
    registerAccess(0,m+12,true,0);
    check(registerAccess(0,m+12,false)==0 && !(dut.get_io$$childEnabled()&4),
          "M root did not revoke delegation");
    sendByte('Q');
    check(!dut.get_io$$supervisorInterrupt() && !dut.get_io$$machineInterrupt(),
          "revoked UART source still delivered an MSI");
    std::cout<<"GSIM AIA S-domain UART: PASS delegated=3 identity=3 uart=Z revoked=1\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"GSIM AIA S-domain UART: FAIL "<<e.what()<<'\n';return 1;}}
