#include "UartConsole.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <vector>
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
struct Test {
    SUartConsole d;
    unsigned cycles=0,period=16,phase=0,timer=0,byte=0,transactions=0;
    std::vector<unsigned> sent;
    bool corrupt=false;
    void tick(){
        d.step();++cycles;
        bool tx=d.get_io$$tx();
        if(!phase){if(!tx){phase=1;timer=period+period/2-1;byte=0;}}
        else if(timer)--timer;
        else if(phase<=8){byte|=unsigned(tx)<<(phase-1);++phase;timer=period-1;}
        else {check(tx,"TX stop bit");sent.push_back(byte);phase=0;}
    }
    Test(){d.set_io$$rx(1);d.set_io$$mmio$$request$$valid(0);d.set_io$$mmio$$response$$ready(0);
        d.set_io$$mmio$$request$$bits$$address(0);d.set_io$$mmio$$request$$bits$$write(0);d.set_io$$mmio$$request$$bits$$data(0);
        d.set_io$$mmio$$request$$bits$$size(0);d.set_io$$mmio$$request$$bits$$byteEnable(1);
        d.set_reset(1);tick();tick();d.set_reset(0);}
    unsigned access(unsigned offset,bool write=false,unsigned value=0,unsigned hold=0,unsigned size=0,unsigned mask=1,bool error=false){
        d.set_io$$mmio$$request$$valid(1);d.set_io$$mmio$$request$$bits$$address(0x10000000ULL+offset);
        d.set_io$$mmio$$request$$bits$$write(write);d.set_io$$mmio$$request$$bits$$data(value);
        d.set_io$$mmio$$request$$bits$$size(size);d.set_io$$mmio$$request$$bits$$byteEnable(mask);
        d.set_io$$mmio$$response$$ready(0);
        unsigned wait=0;do{tick();check(++wait<100000,"request timeout");}while(!d.get_io$$mmio$$request$$ready());
        d.set_io$$mmio$$request$$valid(0);tick();check(d.get_io$$mmio$$response$$valid(),"response latency");
        auto data=d.get_io$$mmio$$response$$bits$$data();check(bool(d.get_io$$mmio$$response$$bits$$error())==error,"access error");
        for(unsigned i=0;i<hold;++i){tick();check(d.get_io$$mmio$$response$$valid()&&data==d.get_io$$mmio$$response$$bits$$data()&&bool(d.get_io$$mmio$$response$$bits$$error())==error,"held response changed");}
        d.set_io$$mmio$$response$$ready(1);tick();d.set_io$$mmio$$response$$ready(0);++transactions;
        return unsigned(data);
    }
    void rx(unsigned value,bool badStop=false){
        for(unsigned bit=0;bit<10;++bit){d.set_io$$rx(bit==0?0:bit==9?!badStop:(value>>(bit-1))&1);for(unsigned i=0;i<period;++i)tick();}
        d.set_io$$rx(1);for(unsigned i=0;i<period;++i)tick();
    }
};
int main(int argc,char**){try{
    Test t;
    check(t.access(5)==0x60&&t.access(2)==1,"reset status");
    t.access(3,true,0x80);check(t.access(3)==0x80,"8250 DLAB setup");
    t.access(0,true,2);t.access(1,true,0);
    check(t.access(0)==2&&t.access(1)==0,"divisor alias");t.access(3,true,3);t.period=32;
    t.access(7,true,0x5a);t.access(7,true,0xff,4,2,15,true);t.access(7,true,0xff,0,0,0,true);
    t.access(8,true,0xff,0,0,1,true);
    check(t.access(7)==0x5a&&t.access(3)==3,"bad access side effects");
    std::mt19937 random(415);for(unsigned i=0;i<500;++i){unsigned v=random()%256;t.access(7,true,v,random()%9);check(t.access(7,false,0,random()%9)==v,"scratch model");}
    t.access(1,true,2);check(t.access(2)==2&&t.access(2)==1,"THRE acknowledge");
    std::vector<unsigned> expected;for(unsigned i=0;i<40;++i){auto v=random()%256;expected.push_back(v);t.access(0,true,v,i%7);}
    check((t.access(5)&0x40)==0,"TEMT while shifting");
    for(unsigned i=0;i<1000;++i)t.tick();
    if(argc>1)expected[0]^=1;
    check(t.sent==expected,"serial byte mismatch");check(t.access(5)==0x60,"TX drain");
    t.access(1,true,7);t.rx(0xa5);check(t.access(2)==4,"RX priority over THRE");
    check(t.access(0)==0xa5&&t.access(2)==2&&t.access(2)==1,"RBR / IIR clear");
    t.rx(0x36);t.rx(0x73);check(t.access(2)==6,"line status priority");
    check((t.access(5)&3)==3,"overrun status");check(t.access(0)==0x36,"overrun preserves unread byte");
    t.rx(0x55,true);check(t.access(2)==6&&(t.access(5)&8),"framing status");t.access(0);
    t.rx(0xa2);t.access(2,true,7);check(t.access(2)==0xc2,"FIFO identification");t.access(2,true,6);check((t.access(5)&1)==0,"RX clear");
    // Short false start must not publish a byte.
    t.d.set_io$$rx(0);for(unsigned i=0;i<4;++i)t.tick();t.d.set_io$$rx(1);for(unsigned i=0;i<400;++i)t.tick();
    check((t.access(5)&1)==0,"false start rejected");
    // Read RBR every cycle throughout reception: includes an exact read/arrival collision.
    t.rx(0x36);t.d.set_io$$mmio$$request$$valid(1);t.d.set_io$$mmio$$request$$bits$$address(0x10000000);
    t.d.set_io$$mmio$$request$$bits$$write(0);t.d.set_io$$mmio$$response$$ready(1);
    unsigned oldSeen=0,newSeen=0,stream=0;
    auto collect=[&](){if(t.d.get_io$$mmio$$response$$valid()){
        auto v=t.d.get_io$$mmio$$response$$bits$$data();check(v==0||v==0x36||v==0x73,"RBR stream data");
        oldSeen+=v==0x36;newSeen+=v==0x73;++stream;}};
    for(unsigned cycle=0;cycle<12*t.period;++cycle){
        unsigned bit=cycle/t.period;t.d.set_io$$rx(bit==0?0:bit>=9?1:(0x73>>(bit-1))&1);
        t.tick();check(t.d.get_io$$mmio$$request$$ready(),"register stream throughput");collect();
    }
    t.d.set_io$$mmio$$request$$valid(0);t.tick();collect();t.d.set_io$$mmio$$response$$ready(0);
    check(oldSeen==1&&newSeen==1&&stream==12*t.period,"RBR concurrent read/arrival");
    // FIFO capacity/order, threshold crossing, four-character timeout and clear.
    t.access(1,true,1);t.access(2,true,0xc7); // trigger 14, enable and clear
    for(unsigned i=0;i<13;++i)t.rx(0x80+i);
    check(t.access(2)==0xc1,"RX below FIFO threshold");
    t.rx(0x8d);check(t.access(2)==0xc4,"RX FIFO threshold");
    check(t.access(0)==0x80,"FIFO oldest character");
    check(t.access(2)==0xc1,"RDA clears below threshold");
    for(unsigned i=0;i<42*t.period;++i)t.tick();
    check(t.access(2)==0xcc,"four-character receive timeout");
    check(t.access(0)==0x81&&t.access(2)==0xc1,"RBR acknowledges timeout");
    for(unsigned i=2;i<14;++i)check(t.access(0)==0x80+i,"FIFO ordered drain");
    check((t.access(5)&1)==0,"FIFO empty data-ready");
    for(unsigned trigger:{0U,1U,2U,3U}){
        const unsigned threshold[]={1,4,8,14};
        t.access(2,true,7|(trigger<<6));
        for(unsigned i=0;i<threshold[trigger];++i){
            if(i)check(t.access(2)==0xc1,"threshold raised too soon");
            t.rx(0x40+i);
        }
        check(t.access(2)==0xc4,"all receive trigger levels");
    }
    t.access(1,true,5);t.access(2,true,7);
    for(unsigned i=0;i<17;++i)t.rx(0x20+i);
    check(t.access(2)==0xc6&&((t.access(5)&3)==3),"FIFO overrun interrupt");
    for(unsigned i=0;i<16;++i)check(t.access(0)==0x20+i,"full FIFO preserves queued bytes");
    check((t.access(5)&1)==0,"overflow drops only newest byte");
    t.rx(0x12);t.rx(0x55,true);
    check((t.access(5)&0x81)==0x81,"queued error summarized in LSR");
    check(t.access(2)==0xc4,"line error waits behind normal FIFO head");
    check(t.access(0)==0x12&&t.access(2)==0xc6,"per-character framing reaches FIFO head");
    check((t.access(5)&8)!=0&&t.access(2)==0xc4,"LSR acknowledges head error");
    check(t.access(0)==0x55,"framing error keeps associated data");
    t.rx(0,true);check((t.access(5)&0x18)==0x18,"break plus framing detection");t.access(0);
    t.access(2,true,7);t.rx(0x69);t.access(2,true,0);
    check((t.access(5)&1)==0&&!(t.access(2)&0xc0),"FIFO mode change clears data and ID");

    // FIFO writes under backpressure must preserve every byte; THRE means FIFO empty.
    t.access(2,true,7);t.access(1,true,2);
    const auto txBefore=t.sent.size();
    for(unsigned i=0;i<40;++i)t.access(0,true,(i*37+11)&255);
    for(unsigned i=0;i<180*t.period;++i)t.tick();
    check(t.sent.size()==txBefore+40,"TX FIFO drain count");
    for(unsigned i=0;i<40;++i)check(t.sent[txBefore+i]==((i*37+11)&255),"TX FIFO serial order");
    check((t.access(5)&0x60)==0x60,"FIFO THRE and TEMT");
    check(t.access(2)==0xc2&&t.access(2)==0xc1,"FIFO THRE acknowledge");

    // RX programmable word length/parity; expectations from wire format, not DUT tables.
    t.access(1,true,5);
    for(unsigned width=5;width<=8;++width)for(unsigned parityMode=0;parityMode<5;++parityMode){
        // none, odd, even, mark, space; two stop bits for 6..8, 1.5 for 5.
        const unsigned format=(width-5)|4|(parityMode?8:0)|
            ((parityMode==2||parityMode==4)?16:0)|(parityMode>=3?32:0);
        t.access(2,true,7);t.access(3,true,format);
        const unsigned value=0xa5&((1U<<width)-1);
        for(unsigned inject=0;inject<(parityMode?2U:1U);++inject){
            auto bit=[&](unsigned level,unsigned ticks){t.d.set_io$$rx(level);for(unsigned i=0;i<ticks;++i)t.tick();};
            bit(0,t.period);for(unsigned i=0;i<width;++i)bit((value>>i)&1,t.period);
            if(parityMode){
                unsigned ones=0;for(unsigned i=0;i<width;++i)ones+=(value>>i)&1;
                unsigned parity=parityMode==3?1:parityMode==4?0:(ones&1)^(parityMode==1);
                bit(parity^inject,t.period);
            }
            bit(1,2*t.period);
            check((t.access(5)&4)==(inject?4U:0U),"parity error association");
            check(t.access(0)==value,"programmable receive width");
        }
    }
    t.access(3,true,3);t.access(2,true,6);t.access(1,true,0);
    for(unsigned div:{1U,3U,0U}){
        t.access(3,true,0x83);t.access(0,true,div);t.access(3,true,3);t.period=16*(div?div:1);
        auto count=t.sent.size();t.access(0,true,0xc3);for(unsigned i=0;i<12*t.period;++i)t.tick();
        check(t.sent.size()==count+1&&t.sent.back()==0xc3,"baud divisor / zero policy");
        t.rx(0x69);check(t.access(0)==0x69,"RX baud divisor");
    }
    std::cout<<"GSIM UartConsole: PASS transactions="<<t.transactions<<" serialBytes="<<t.sent.size()<<" cycles="<<t.cycles<<"\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"GSIM UART: FAIL "<<e.what()<<"\n";return 1;}}
