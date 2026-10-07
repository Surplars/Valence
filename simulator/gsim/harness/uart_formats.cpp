#include "UartConsole.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
static void check(bool b,const char*m){if(!b)throw std::runtime_error(m);}
struct Test {
    SUartConsole d;
    std::vector<unsigned> wire;
    void tick(){d.step();wire.push_back(d.get_io$$tx());}
    Test(){
        d.set_io$$rx(1);d.set_io$$mmio$$request$$valid(0);d.set_io$$mmio$$response$$ready(0);
        d.set_io$$mmio$$request$$bits$$size(0);d.set_io$$mmio$$request$$bits$$byteEnable(1);
        d.set_reset(1);tick();tick();d.set_reset(0);
    }
    unsigned access(unsigned off,bool write=false,unsigned value=0){
        d.set_io$$mmio$$request$$bits$$address(0x10000000ULL+off);
        d.set_io$$mmio$$request$$bits$$write(write);d.set_io$$mmio$$request$$bits$$data(value);
        d.set_io$$mmio$$request$$valid(1);d.set_io$$mmio$$response$$ready(0);
        unsigned wait=0;do{tick();check(++wait<10000,"MMIO stalled");}while(!d.get_io$$mmio$$request$$ready());
        d.set_io$$mmio$$request$$valid(0);tick();
        check(d.get_io$$mmio$$response$$valid()&&!d.get_io$$mmio$$response$$bits$$error(),"MMIO response");
        unsigned result=d.get_io$$mmio$$response$$bits$$data();
        d.set_io$$mmio$$response$$ready(1);tick();d.set_io$$mmio$$response$$ready(0);
        return result;
    }
    void idle(unsigned cycles){while(cycles--)tick();}
};
int main(int argc,char**){
    try{
        Test t;t.access(3,true,0x83);t.access(0,true,2);t.access(1,true,0);t.access(3,true,3);
        unsigned cases=0;
        for(unsigned width=5;width<=8;++width)for(unsigned parity=0;parity<5;++parity)
        for(unsigned stops=0;stops<2;++stops){
            const unsigned format=(width-5)|(stops?4:0)|(parity?8:0)|
                ((parity==2||parity==4)?16:0)|(parity>=3?32:0);
            t.access(3,true,format);t.access(2,true,7);
            const unsigned byte=0xa5&((1U<<width)-1);
            const size_t begin=t.wire.size();t.access(0,true,0xa5);t.idle(450);
            size_t start=begin;while(start<t.wire.size()&&t.wire[start])++start;
            check(start<t.wire.size(),"TX start absent");
            check(!t.wire.at(start+16),"TX start-bit center");
            for(unsigned i=0;i<width;++i){
                unsigned expected=(byte>>i)&1;if(argc>1&&cases==0&&i==0)expected^=1;
                check(t.wire.at(start+32*(i+1)+16)==expected,"TX wire format mismatch");
            }
            unsigned next=width+1;
            if(parity){
                unsigned ones=0;for(unsigned i=0;i<width;++i)ones+=(byte>>i)&1;
                const unsigned expected=parity==3?1:parity==4?0:(ones&1)^(parity==1);
                check(t.wire.at(start+32*next+16)==expected,"TX parity bit");++next;
            }
            check(t.wire.at(start+32*next+16),"TX stop-bit center");
            if(stops)check(t.wire.at(start+32*(next+1)+(width==5?8:16)),"TX extended stop");
            check((t.access(5)&0x60)==0x60,"TX format drain");++cases;
        }
        t.access(3,true,3);t.access(2,true,7);t.access(1,true,8);t.access(4,true,0x1f);
        check(t.access(2)==0xc0,"modem interrupt");
        check(t.access(6)==0xfb&&t.access(6)==0xf0,"loopback modem and read-clear");
        check(t.access(2)==0xc1,"modem acknowledge");
        t.access(4,true,0x1b);check(t.access(6)==0xb4,"trailing ring edge");
        const auto begin=t.wire.size();t.access(0,true,0x5a);t.idle(450);
        check((t.access(5)&1)&&t.access(0)==0x5a,"internal loopback RX");
        for(size_t i=begin;i<t.wire.size();++i)check(t.wire[i],"loopback isolates external TX");
        t.access(3,true,0x43);t.idle(400);
        check((t.access(5)&0x18)==0x18,"loopback break detection");
        t.access(0);t.access(3,true,3);t.idle(50);t.access(4,true,0);
        std::cout<<"GSIM UART formats/modem/loopback: PASS cases="<<cases<<"\n";
        return 0;
    }catch(const std::exception&e){std::cerr<<"GSIM UART formats: FAIL "<<e.what()<<"\n";return 1;}
}
