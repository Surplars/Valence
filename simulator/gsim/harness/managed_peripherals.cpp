#include "ManagedPeripheralGsim.h"
#include "gmii_reference.h"
#include <array>
#include <cmath>
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#include <tuple>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
struct Reply{uint64_t data;bool error;bool operator==(const Reply&)const=default;};
struct Test{
    SManagedPeripheralGsim d;
    std::mt19937 rng{0x261004};
    std::deque<std::vector<uint8_t>> expectedTx,expectedRx;
    std::deque<unsigned> statusLengths;
    std::vector<uint8_t> burst,received;
    std::vector<bool> serial;
    using Beat=std::tuple<uint32_t,unsigned,bool>;
    std::optional<Beat> heldData,heldStatus;
    bool dataReady=true,statusReady=true,injectFrame=false;
    unsigned cycles=0,mmio=0,txFrames=0,rxFrames=0,statusFrames=0,statusIndex=0,stalls=0;
    uint64_t txBytes=0,rxBytes=0;
    Test(bool inject):injectFrame(inject){
        for(unsigned p=0;p<3;++p)bus(p,0,false,0,false);
        S(streams$$txData$$valid,0);S(streams$$txControl$$valid,0);
        S(rxValid,0);S(rxError,0);S(rxData,0);S(uartRx,1);
        d.set_reset(1);tick();tick();d.set_reset(0);idle(100);
    }
    void bus(unsigned p,unsigned off,bool write,uint64_t value,bool valid){
#define BUS(ID,NAME,BASE,SIZE,MASK) case ID: \
        d.set_io$$##NAME##$$request$$valid(valid);d.set_io$$##NAME##$$request$$bits$$address(BASE+off); \
        d.set_io$$##NAME##$$request$$bits$$write(write);d.set_io$$##NAME##$$request$$bits$$data(value); \
        d.set_io$$##NAME##$$request$$bits$$size(SIZE);d.set_io$$##NAME##$$request$$bits$$byteEnable(MASK);break;
        switch(p){BUS(0,cmu,0x10080000ULL,3,255);BUS(1,uart,0x10000000ULL,0,1);BUS(2,gmac,0x10040000ULL,3,255);}
#undef BUS
    }
    void responseReady(unsigned p,bool ready){
        switch(p){case 0:S(cmu$$response$$ready,ready);break;
            case 1:S(uart$$response$$ready,ready);break;default:S(gmac$$response$$ready,ready);}
    }
    bool requestReady(unsigned p){switch(p){case 0:return G(cmu$$request$$ready);
        case 1:return G(uart$$request$$ready);default:return G(gmac$$request$$ready);}}
    bool responseValid(unsigned p){switch(p){case 0:return G(cmu$$response$$valid);
        case 1:return G(uart$$response$$valid);default:return G(gmac$$response$$valid);}}
    Reply response(unsigned p){switch(p){case 0:return {G(cmu$$response$$bits$$data),bool(G(cmu$$response$$bits$$error))};
        case 1:return {G(uart$$response$$bits$$data),bool(G(uart$$response$$bits$$error))};
        default:return {G(gmac$$response$$bits$$data),bool(G(gmac$$response$$bits$$error))};}}
    void tick(){
        bool takeData=dataReady&&rng()%4!=0,takeStatus=statusReady&&rng()%3!=0;
        S(streams$$rxData$$ready,takeData);S(streams$$rxStatus$$ready,takeStatus);d.step();++cycles;
        serial.push_back(G(uartTx));
        check(!G(txError),"managed GMAC emitted unexpected TX_ER");
        if(G(txEnable))burst.push_back(G(txData));
        else if(!burst.empty()){
            check(!expectedTx.empty(),"managed GMAC emitted unsolicited frame");
            auto expected=expectedTx.front();if(injectFrame&&txFrames==0)expected.back()^=1;
            check(burst==expected,"managed GMAC independent wire oracle mismatch");
            expectedTx.pop_front();txBytes+=burst.size()-12;burst.clear();++txFrames;
        }
        if(G(streams$$rxData$$valid)){
            Beat value{uint32_t(G(streams$$rxData$$bits$$data)),unsigned(G(streams$$rxData$$bits$$keep)),
                bool(G(streams$$rxData$$bits$$last))};
            if(heldData)check(value==*heldData,"managed RX data changed under backpressure");
            heldData=takeData?std::nullopt:std::optional{value};stalls+=!takeData;
            if(takeData){
                auto [word,keep,last]=value;
                check(!expectedRx.empty()&&(keep==1||keep==3||keep==7||keep==15)&&
                    (last||keep==15),"managed RX unexpected data or keep");
                for(unsigned n=0;n<4;++n)if(keep&(1U<<n))received.push_back(word>>(8*n));
                if(last){
                    check(received==expectedRx.front(),"managed RX independent payload oracle mismatch");
                    rxBytes+=received.size();statusLengths.push_back(received.size());
                    expectedRx.pop_front();received.clear();++rxFrames;
                }
            }
        }else check(!heldData,"managed RX withdrew stalled data");
        if(G(streams$$rxStatus$$valid)){
            Beat value{uint32_t(G(streams$$rxStatus$$bits$$data)),unsigned(G(streams$$rxStatus$$bits$$keep)),
                bool(G(streams$$rxStatus$$bits$$last))};
            if(heldStatus)check(value==*heldStatus,"managed RX status changed under backpressure");
            heldStatus=takeStatus?std::nullopt:std::optional{value};stalls+=!takeStatus;
            if(takeStatus){
                check(!statusLengths.empty(),"managed RX status without complete payload");
                const uint32_t expected=statusIndex==0?0x50000000:statusIndex==3?64:
                    statusIndex==5?statusLengths.front():0;
                auto [word,keep,last]=value;
                check(word==expected&&keep==15&&last==(statusIndex==5),"managed RX independent status oracle mismatch");
                if(++statusIndex==6){statusIndex=0;statusLengths.pop_front();++statusFrames;}
            }
        }else check(!heldStatus,"managed RX withdrew stalled status");
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
    void drain(unsigned limit=20000){
        unsigned n=0;while((!expectedTx.empty()||!expectedRx.empty()||!burst.empty()||!statusLengths.empty())&&n++<limit)tick();
        check(n<limit,"managed frame/status drain timed out");idle(180);
    }
    void sleep(unsigned mask){
        idle(180);write(0,0x50,0x68);write(0,0x68,0x68);write(0,0x20,mask);
        for(unsigned n=0;n<1000&&(G(enabled)&mask);++n)tick();
        check(!(G(enabled)&mask)&&(G(isolate)&mask)==mask,"managed endpoint failed to stop after full drain");
        check((G(enabled)&7)==7,"managed CMU gated CPU/time/AON");
    }
    void serialByte(unsigned value){
        // Independent8N1 waveform at50MHz/460800; no DUT divider tables.
        const double period=50000000.0/460800.0;
        unsigned end=0;
        for(unsigned bit=0;bit<10;++bit){
            S(uartRx,bit==0?0:bit==9?1:(value>>(bit-1))&1);
            unsigned next=unsigned(std::llround(period*(bit+1)));idle(next-end);end=next;
        }
        S(uartRx,1);idle(180);
    }
    void controlWord(unsigned index){
        S(streams$$txControl$$valid,1);S(streams$$txControl$$bits$$data,index==0?0xa0000000:0);
        S(streams$$txControl$$bits$$keep,15);S(streams$$txControl$$bits$$last,index==5);
        unsigned n=0;do{tick();check(++n<1000,"managed TX control hung");}while(!G(streams$$txControl$$ready));
        S(streams$$txControl$$valid,0);
    }
    void transmit(const std::vector<uint8_t>&body,bool stopInFlight=false){
        expectedTx.push_back(ethernetWire(body));
        for(unsigned n=0;n<6;++n)controlWord(n);
        for(unsigned pos=0;pos<body.size();pos+=4){
            unsigned count=std::min(4U,unsigned(body.size()-pos));uint32_t word=0;
            for(unsigned n=0;n<count;++n)word|=uint32_t(body[pos+n])<<(8*n);
            S(streams$$txData$$valid,1);S(streams$$txData$$bits$$data,word);
            S(streams$$txData$$bits$$keep,(1U<<count)-1);S(streams$$txData$$bits$$last,pos+count==body.size());
            unsigned n=0;do{tick();check(++n<10000,"managed TX payload hung");}while(!G(streams$$txData$$ready));
            S(streams$$txData$$valid,0);
        }
        if(stopInFlight){write(0,0x50,0x68);write(0,0x20,32);}
        drain();
        if(stopInFlight)check(!(G(enabled)&32),"managed TX stopped request lost after wire/IFG drain");
    }
    void receive(std::vector<uint8_t>body,bool bad=false){
        body.resize(std::max(60U,unsigned(body.size())),0);auto wire=ethernetWire(body,false);
        if(bad)wire.back()^=1;else expectedRx.push_back(body);
        for(auto byte:wire){S(rxData,byte);S(rxValid,1);S(rxError,0);tick();}
        S(rxValid,0);idle(180);
    }
};
int main(int argc,char**argv){try{
    bool injectUart=argc==2&&std::string_view(argv[1])=="--inject-uart";
    bool injectFrame=argc==2&&std::string_view(argv[1])=="--inject-frame";
    Test t(injectFrame);
    check(t.access(0,0)==0x56434d5500010001ULL&&t.access(0,0x18)==0x68&&
        t.access(2,0)==0x56474d4100010001ULL,"managed peripheral inventory mismatch");
    t.write(0,0x70,0x68);t.write(2,0x18,0x021122334455ULL);t.idle(100);
    t.write(2,0x10,11);t.idle(100);t.write(2,0x38,127);t.write(2,0x30,127);
    // MMIO must wake an isolated UART without resetting retained registers.
    t.write(1,7,0x39);t.sleep(0x68);check(t.access(1,7)==0x39,"UART retained scratch lost on wake");
    check((t.G(enabled)&8)&&!(t.G(isolate)&8)&&!(t.G(enabled)&96),"UART MMIO woke unrelated media domains");
    unsigned uartCases=0;
    for(unsigned n=0;n<24;++n){
        t.sleep(8);t.idle(n%13);unsigned byte=(n*73+17)&255;t.serialByte(byte);
        check((t.access(1,5)&0x1f)==1,"UART first-character wake caused line error or lost DR");
        check(t.access(1,0)==(byte^(injectUart&&n==0)),"managed UART first-character independent oracle mismatch");
        ++uartCases;
    }
    // Unread RX and a stalled reply both prevent gate closure.
    t.serialByte(0x5a);t.write(0,0x50,8);t.write(0,0x20,8);t.idle(80);
    check(t.G(enabled)&8,"UART gated with an unread FIFO byte");
    check(t.access(1,0)==0x5a,"UART pending RBR lost during quiesce");t.idle(180);
    // Masked wake must return a bounded error, not deadlock the CPU or modify SCR.
    t.sleep(8);t.write(0,0x58,0x60);t.write(1,7,0xa7,true);
    check(!(t.G(enabled)&8),"masked UART wake unexpectedly opened clock");
    t.write(0,0x58,0x68);t.write(0,0x60,8);t.idle(180);
    check(t.access(1,7)==0x39,"failed isolated write had a side effect");
    // Full UART TX completes before drain/gate; use independent bit centers.
    size_t begin=t.serial.size();t.write(1,0,0xa5);t.write(0,0x50,8);t.write(0,0x20,8);t.idle(1600);
    size_t start=begin;while(start<t.serial.size()&&t.serial[start])++start;
    check(start<t.serial.size(),"managed UART TX start missing");
    for(unsigned bit=0;bit<8;++bit)check(t.serial.at(start+unsigned(std::llround((bit+1.5)*50000000/460800.0)))==
        bool((0xa5>>bit)&1),"managed UART TX independent wire oracle mismatch");
    check(!(t.G(enabled)&8)&&t.G(uartTx),"UART gated before complete idle-high stop bit");
    // First packet and first TX descriptor wake only their own domain.
    t.sleep(96);t.transmit(ethernetBody(65,1),true);t.sleep(96);
    t.receive(ethernetBody(127,2));t.drain();
    check((t.G(enabled)&64)&&!(t.G(enabled)&32),"RX first-frame wake affected TX or failed");
    for(unsigned length:{14U,60U,61U,128U,511U,1518U,2048U}){
        t.sleep(96);t.transmit(ethernetBody(length,length));t.sleep(96);
        t.receive(ethernetBody(length,length+1));t.drain();
    }
    // Pending RX status tail is part of ownership; pointer-empty is insufficient.
    t.statusReady=false;t.receive(ethernetBody(63,73));
    for(unsigned n=0;n<1000&&t.statusLengths.empty();++n)t.tick();
    check(!t.statusLengths.empty(),"missing RX status-backpressure case");
    t.write(0,0x50,0x68);t.write(0,0x20,64);t.idle(100);
    check(t.G(enabled)&64,"RX gated before DMA status tail consumption");
    t.statusReady=true;t.drain();check(!(t.G(enabled)&64),"RX failed to stop after final status/stats drain");
    t.sleep(64);auto before=t.rxFrames;t.receive(ethernetBody(64,76),true);t.idle(1000);
    check(t.rxFrames==before&&t.expectedRx.empty(),"bad-FCS wake leaked a frame to DMA");
    t.receive(ethernetBody(64,77));t.drain();
    check(t.access(2,0x40)==t.txFrames&&t.access(2,0x48)==t.rxFrames&&t.access(2,0x50)==1&&
        t.access(2,0x58)==1&&t.access(2,0x60)==t.txBytes&&t.access(2,0x68)==t.rxBytes,
        "managed GMAC independent coalesced statistics mismatch");
    check(t.statusFrames==t.rxFrames&&t.stalls>0,"managed RX status/capacity coverage missing");
    t.sleep(0x68);
    std::cout<<"MANAGED_PERIPHERALS_PASS uart_first_bytes="<<uartCases<<" tx_frames="<<t.txFrames
        <<" rx_frames="<<t.rxFrames<<" status_frames="<<t.statusFrames<<" bad_fcs=1 masked_wake_error=1"
        <<" mmio="<<t.mmio<<" stalls="<<t.stalls<<" single_clock_only=1 cycles="<<t.cycles<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
