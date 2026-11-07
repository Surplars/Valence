#include "Aplic.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>

static void check(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
constexpr unsigned N=APLIC_SOURCES;
constexpr uint64_t base=APLIC_BASE,msiBase=APLIC_MSI_BASE;
struct Bench {
    SAplic d;
    bool allow=true,ack=false,wrong=false;
    unsigned cycles=0;
    std::vector<unsigned> sent;
    Bench(bool negative):wrong(negative){
        d.set_io$$sources(0);d.set_io$$mmio$$request$$valid(0);d.set_io$$mmio$$response$$ready(1);
        d.set_io$$msi$$request$$ready(1);d.set_io$$msi$$response$$valid(0);
        d.set_io$$msi$$response$$bits$$data(0);d.set_io$$msi$$response$$bits$$error(0);
        d.set_reset(1);tick();tick();d.set_reset(0);idle(3);
    }
    void tick(){
        d.set_io$$msi$$request$$ready(allow);d.set_io$$msi$$response$$valid(ack);d.step();++cycles;
        if(ack&&d.get_io$$msi$$response$$ready())ack=false;
        if(d.get_io$$msi$$request$$valid()&&allow){
            check(d.get_io$$msi$$request$$bits$$address()==msiBase+(wrong?4096:0),"independent boundary MSI address");
            check(d.get_io$$msi$$request$$bits$$write()&&d.get_io$$msi$$request$$bits$$size()==2&&
                  d.get_io$$msi$$request$$bits$$byteEnable()==15,"boundary MSI format");
            sent.push_back(d.get_io$$msi$$request$$bits$$data());ack=true;
        }
        check(!d.get_io$$msiError(),"boundary MSI error");
    }
    void idle(unsigned n=12){d.set_io$$mmio$$request$$valid(0);while(n--)tick();}
    uint64_t bus(unsigned offset,bool write=false,uint32_t data=0){
        bool accepted=false;
        for(unsigned n=0;n<30;++n){
            d.set_io$$mmio$$request$$valid(!accepted);d.set_io$$mmio$$request$$bits$$address(base+offset);
            d.set_io$$mmio$$request$$bits$$write(write);d.set_io$$mmio$$request$$bits$$data(data);
            d.set_io$$mmio$$request$$bits$$size(2);d.set_io$$mmio$$request$$bits$$byteEnable(15);tick();
            if(!accepted&&d.get_io$$mmio$$request$$ready())accepted=true;
            if(d.get_io$$mmio$$response$$valid()){
                check(accepted&&!d.get_io$$mmio$$response$$bits$$error(),"boundary MMIO response");
                d.set_io$$mmio$$request$$valid(0);return d.get_io$$mmio$$response$$bits$$data();
            }
        }throw std::runtime_error("boundary MMIO timeout");
    }
};
int main(int argc,char **argv){try{
    Bench b(argc>1);
    check(b.bus(0x1bc0)==((msiBase>>12)&0xffffffff),"boundary M MSI address low");
    check(b.bus(0x1bc4)==(0x80000000|(msiBase>>44)),"boundary M MSI address high");
    for(unsigned id=1;id<=N;++id){
        b.bus(4*id,true,1);b.bus(0x3000+4*id,true,0xffffffff);
        check(b.bus(4*id)==1&&b.bus(0x3000+4*id)==2047,"boundary source/target identity width");
        b.bus(0x1edc,true,id);b.bus(0x1cdc,true,id);
    }
    for(unsigned group=0;group<=N/32;++group){
        uint32_t mask=0;for(unsigned bit=0;bit<32;++bit){unsigned id=32*group+bit;if(id&&id<=N)mask|=uint32_t(1)<<bit;}
        check(b.bus(0x1c00+4*group)==mask&&b.bus(0x1e00+4*group)==mask,"boundary source bitmap");
    }
    b.allow=false;b.bus(0,true,256);b.idle();
    check(b.d.get_io$$msi$$request$$valid(),"boundary output stall");
    b.allow=true;b.idle(N+20);check(b.sent.size()==N,"boundary source forwarding count");
    for(unsigned id:b.sent)check(id==2047,"boundary EIID2047 truncation");
    for(unsigned group=0;group<=N/32;++group)check(b.bus(0x1c00+4*group)==0,"boundary pending not consumed");
    // Highest wire bit and highest target register must not alias a lower source.
    for(unsigned id=1;id<N;++id)b.bus(4*id,true,0);
    b.bus(4*N,true,4);b.bus(0x3000+4*N,true,2046);
    b.d.set_io$$sources((static_cast<unsigned _BitInt(APLIC_SOURCES)>(1))<<(N-1));b.idle();
    check(b.sent.size()==N+1&&b.sent.back()==2046,"boundary highest source wire");
    b.idle();check(b.sent.size()==N+1,"boundary edge repeated while high");
    b.bus(4*N,true,0);check(b.bus(4*N)==0&&b.bus(0x3000+4*N)==0,"boundary inactive reset");
    std::cout<<"APLIC_BOUNDARY_PASS sources="<<N<<" identities=2047 msis="<<b.sent.size()<<" cycles="<<b.cycles
             <<" highest_wire=1 highest_bitmap=1 address_end=1 stalled=1\n";
}catch(const std::exception&e){std::cerr<<"APLIC_BOUNDARY_FAIL "<<e.what()<<'\n';return 1;}}
