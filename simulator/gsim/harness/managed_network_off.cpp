#include "CommonManagedNetworkOffGsim.h"
#include "gsim_model_storage.h"
#include <cmath>
#include <cstdint>
#include <iostream>
#include <optional>
#include <memory>
#include <stdexcept>
#include <string_view>
#include <vector>

// UART/CMU bus ordering and independent 8N1 waveform/bit-center oracles are
// extracted from managed_peripherals.cpp. GMAC/stream tests are inapplicable
// here; the actual bank omits that hardware. No expected value comes from RTL.
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
struct Reply{uint64_t data;bool error;bool operator==(const Reply&)const=default;};
struct Test {
    std::unique_ptr<GsimModelStorage<SCommonManagedNetworkOffGsim>> storage=
        std::make_unique<GsimModelStorage<SCommonManagedNetworkOffGsim>>();
    SCommonManagedNetworkOffGsim& d=storage->get();
    std::vector<bool> serial;
    unsigned cycles=0,mmio=0;
    Test(){
        for(unsigned p=0;p<2;++p){bus(p,0,false,0,false);responseReady(p,false);}
        S(uartRx,1);
        d.set_reset(1);d.step();d.step();d.set_reset(0);idle(100);
    }
    void bus(unsigned p,unsigned off,bool write,uint64_t value,bool valid){
#define BUS(ID,NAME,BASE,SIZE,MASK) case ID: \
        d.set_io$$##NAME##$$request$$valid(valid);d.set_io$$##NAME##$$request$$bits$$address(BASE+off); \
        d.set_io$$##NAME##$$request$$bits$$write(write);d.set_io$$##NAME##$$request$$bits$$data(value); \
        d.set_io$$##NAME##$$request$$bits$$size(SIZE);d.set_io$$##NAME##$$request$$bits$$byteEnable(MASK);break;
        switch(p){BUS(0,cmu,0x10080000ULL,3,255);BUS(1,uart,0x10000000ULL,0,1);}
#undef BUS
    }
    void responseReady(unsigned p,bool ready){
        if(p==0){S(cmu$$response$$ready,ready);}else{S(uart$$response$$ready,ready);}
    }
    bool requestReady(unsigned p){return p==0?G(cmu$$request$$ready):G(uart$$request$$ready);}
    bool responseValid(unsigned p){return p==0?G(cmu$$response$$valid):G(uart$$response$$valid);}
    Reply response(unsigned p){
        if(p==0)return {G(cmu$$response$$bits$$data),bool(G(cmu$$response$$bits$$error))};
        return {G(uart$$response$$bits$$data),bool(G(uart$$response$$bits$$error))};
    }
    void tick(){
        d.step();++cycles;serial.push_back(G(uartTx));
        check(cycles<60000,"managed network-off cycle bound");
        check((G(enabled)&0x60)==0 && (G(quiesce)&0x60)==0 && (G(isolate)&0x60)==0,
            "absent network clock resource became active");
        check((G(enabled)&0x17)==0x17,"network-off CMU gated fixed resources");
    }
    void idle(unsigned n){while(n--)tick();}
    uint64_t access(unsigned p,unsigned off,bool write=false,uint64_t value=0,bool error=false){
        bool sent=false;std::optional<Reply> held;
        for(unsigned n=0;n<20000;++n){
            bus(p,off,write,value,!sent);bool ready=n>=5&&n%3!=0;responseReady(p,ready);tick();
            if(!sent&&requestReady(p))sent=true;
            if(responseValid(p)){
                auto reply=response(p);if(held)check(reply==*held,"managed MMIO reply changed while stalled");
                held=reply;
                if(ready){check(sent&&reply.error==error,"managed MMIO independent status mismatch");
                    bus(p,off,write,value,false);responseReady(p,false);++mmio;return reply.data;}
            }
        }
        throw std::runtime_error("managed MMIO request hung");
    }
    void write(unsigned p,unsigned off,uint64_t value,bool error=false){access(p,off,true,value,error);}
    void sleep(){
        idle(180);write(0,0x50,8);write(0,0x68,8);write(0,0x20,8);
        for(unsigned n=0;n<1000&&(G(enabled)&8);++n)tick();
        check(!(G(enabled)&8)&&(G(isolate)&8),"managed UART failed to stop after full drain");
    }
    void serialByte(unsigned value){
        // Original independent 8N1 waveform at 50 MHz / 460800 baud.
        const double period=50000000.0/460800.0;
        unsigned end=0;
        for(unsigned bit=0;bit<10;++bit){
            S(uartRx,bit==0?0:bit==9?1:(value>>(bit-1))&1);
            unsigned next=unsigned(std::llround(period*(bit+1)));idle(next-end);end=next;
        }
        S(uartRx,1);idle(180);
    }
};
int main(int argc,char **argv){
    try {
        check(argc==1 || (argc==2&&std::string_view(argv[1])=="--inject-uart"),
            "unexpected managed network-off arguments");
        bool inject=argc==2;
        Test t;
        check(t.access(0,0)==0x56434d5500010001ULL && t.access(0,0x10)==0x1f &&
            t.access(0,0x18)==8,"network-off CMU inventory mismatch");
        for(unsigned index : {5U,6U}){
            check(t.access(0,0x100+index*0x40)==index &&
                t.access(0,0x110+index*0x40)==0 && t.access(0,0x118+index*0x40)==0,
                "absent CMU resource identity/flags/status mismatch");
        }
        // Keep ABI indices; reject forbidden STOP bits without side effects.
        for(unsigned mask : {0x20U,0x40U,0x60U,0x68U}){
            t.write(0,0x20,mask,true);
            check(t.access(0,0x20)==0 && t.access(0,0x28)==0x1f && t.access(0,0x68)==0,
                "rejected absent-resource STOP modified clock policy");
        }
        t.write(1,7,0x39);t.sleep();
        check(t.access(1,7)==0x39,"UART retained scratch lost on wake");
        check((t.G(enabled)&8)&&!(t.G(isolate)&8),"UART MMIO wake failed");
        unsigned uartCases=0;
        for(unsigned n=0;n<4;++n){
            t.sleep();t.idle(n%13);unsigned byte=(n*73+17)&255;t.serialByte(byte);
            check((t.access(1,5)&0x1f)==1,"UART first-character wake caused line error or lost DR");
            uint64_t observed=t.access(1,0);
            if(inject&&n==0){std::cerr<<"MANAGED_NETWORK_OFF_MUTANT_REACHED\n";observed^=1;}
            check(observed==byte,"managed UART first-character independent oracle mismatch");
            ++uartCases;
        }
        t.serialByte(0x5a);t.write(0,0x50,8);t.write(0,0x20,8);t.idle(80);
        check(t.G(enabled)&8,"UART gated with an unread FIFO byte");
        check(t.access(1,0)==0x5a,"UART pending RBR lost during quiesce");t.idle(180);
        t.sleep();t.write(0,0x58,0);t.write(1,7,0xa7,true);
        check(!(t.G(enabled)&8),"masked UART wake unexpectedly opened clock");
        t.write(0,0x58,8);t.write(0,0x60,8);t.idle(180);
        check(t.access(1,7)==0x39,"failed isolated write had a side effect");
        // Original wire oracle: no software-loopback shortcut for real TX.
        size_t begin=t.serial.size();t.write(1,0,0xa5);t.write(0,0x50,8);t.write(0,0x20,8);t.idle(1600);
        size_t start=begin;while(start<t.serial.size()&&t.serial[start])++start;
        check(start<t.serial.size(),"managed UART TX start missing");
        for(unsigned bit=0;bit<8;++bit)check(t.serial.at(start+unsigned(std::llround((bit+1.5)*50000000/460800.0)))==
            bool((0xa5>>bit)&1),"managed UART TX independent wire oracle mismatch");
        check(!(t.G(enabled)&8)&&t.G(uartTx),"UART gated before complete idle-high stop bit");
        t.idle(32);
        check(!t.responseValid(0)&&!t.responseValid(1),"managed network-off duplicate MMIO reply");
        check(t.access(0,0x10)==0x1f && t.access(0,0x18)==8,"network-off inventory changed after UART traffic");
        t.idle(32);check(!t.responseValid(0)&&!t.responseValid(1),"managed network-off terminal reply replay");
        std::cout<<"MANAGED_NETWORK_OFF_PASS uart_rx="<<uartCases<<" uart_tx=1 absent_stop=4 mmio="
                 <<t.mmio<<" cycles="<<t.cycles<<"\n";
    }catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}
}
