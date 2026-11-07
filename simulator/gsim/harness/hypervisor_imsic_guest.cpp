#include "HypervisorImsicGuestGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <type_traits>
class Bench {
public:
    SHypervisorImsicGuestGsim d;uint64_t cycles=0,checks=0,transactions=0;
    Bench(){static_assert(std::is_trivially_copyable_v<SHypervisorImsicGuestGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
        d.set_io$$response$$ready(1);d.set_io$$mmio$$response$$ready(1);d.set_reset(1);tick();tick();d.set_reset(0);tick();}
    void tick(){d.step();cycles++;}
    void check(uint64_t actual,uint64_t expected,const char* what){checks++;if(actual!=expected){
        std::cerr<<what<<" cycle="<<cycles<<" got="<<std::hex<<actual<<" expected="<<expected<<std::dec<<'\n';throw std::runtime_error(what);}}
    uint64_t csr(unsigned file,unsigned selector,unsigned op,uint64_t data=0,bool topei=false){
        d.set_io$$csr$$bits$$file(file);d.set_io$$csr$$bits$$selector(selector);d.set_io$$csr$$bits$$operation(op);
        d.set_io$$csr$$bits$$data(data);d.set_io$$csr$$bits$$topei(topei);d.set_io$$csr$$valid(1);
        unsigned budget=20;do{tick();if(!budget--)throw std::runtime_error("CSR admission timeout");}while(!d.get_io$$csr$$ready());
        d.set_io$$csr$$valid(0);budget=20;do{tick();if(!budget--)throw std::runtime_error("CSR response timeout");}while(!d.get_io$$response$$valid());
        check(d.get_io$$response$$bits$$error(),0,"IMSIC CSR error");transactions++;auto value=d.get_io$$response$$bits$$data();tick();return value;
    }
    void msi(unsigned guest,unsigned identity,bool machine=false){
        d.set_io$$mmio$$request$$bits$$address(machine?0x24000000ULL:0x28000000ULL+uint64_t(guest)*4096);
        d.set_io$$mmio$$request$$bits$$size(2);d.set_io$$mmio$$request$$bits$$write(1);
        d.set_io$$mmio$$request$$bits$$data(identity);d.set_io$$mmio$$request$$bits$$byteEnable(15);
        d.set_io$$mmio$$request$$valid(1);unsigned budget=20;
        do{tick();if(!budget--)throw std::runtime_error("MSI admission timeout");}while(!d.get_io$$mmio$$request$$ready());
        d.set_io$$mmio$$request$$valid(0);budget=20;
        do{tick();if(!budget--)throw std::runtime_error("MSI response timeout");}while(!d.get_io$$mmio$$response$$valid());
        check(d.get_io$$mmio$$response$$bits$$error(),0,"MSI response error");transactions++;tick();
    }
    void hwrite(unsigned address,uint64_t data){d.set_io$$write$$bits$$address(address);d.set_io$$write$$bits$$data(data);
        d.set_io$$write$$valid(1);tick();d.set_io$$write$$valid(0);tick();}
    void select(unsigned selection){d.set_io$$setVgein$$bits(selection);d.set_io$$setVgein$$valid(1);tick();d.set_io$$setVgein$$valid(0);tick();}
    void pending(uint64_t geip,uint64_t hip,bool hs,bool vs,const char* label){tick();check(d.get_io$$hgeip(),geip,label);check(d.get_io$$hip(),hip,label);
        check(d.get_io$$hsPending(),hs,label);check(d.get_io$$vsPending(),vs,label);}
};
int main(){try{
    Bench b;b.d.set_io$$hie(0x1444);b.d.set_io$$hideleg(0x444);b.d.set_io$$virtualized(1);b.d.set_io$$vsGlobalEnable(1);
    for(unsigned f=0;f<5;f++){b.csr(f,0x70,1,1);b.csr(f,0xc0,1,2);}
    b.select(1);b.msi(0,1,true);b.msi(0,1);b.pending(0,0,false,false,"host M/S must not leak into guests");
    b.msi(1,1);b.pending(2,0x400,false,true,"selected guest bypasses hgeie");
    b.check(b.d.get_io$$vsCause(),9,"VSEI translates to VS external cause 9");
    b.hwrite(0x607,4);b.pending(2,0x400,false,true,"summary enables another guest only");
    b.msi(2,1);b.pending(6,0x1400,true,true,"simultaneous HS summary and selected VS");
    b.check(b.d.get_io$$hsCause(),12,"HS summary cause 12");
    b.csr(2,0x72,1,1);b.pending(4,0x1000,true,false,"threshold suppresses guest1 only");
    b.csr(2,0x72,1,2);b.pending(6,0x1400,true,true,"strict threshold comparison");
    b.select(3);b.pending(6,0x1000,true,false,"nonpending selection");
    b.msi(3,1);b.pending(14,0x1400,true,true,"third guest mapped to hgeip bit3");
    b.select(0);b.pending(14,0x1000,true,false,"VGEIN zero disables selected injection");
    b.select(2);b.pending(14,0x1400,true,true,"guest2 selected");
    auto claimed=b.csr(3,0,1,0,true);b.check(claimed,0x10001,"claim identity and priority");
    b.pending(10,0,false,false,"claim clears only guest2 file");
    b.hwrite(0x645,0x400);b.pending(10,0x400,false,true,"software virtual injection independent of physical guest");
    b.hwrite(0x644,0);b.pending(10,0x400,false,true,"hip VSEIP is read-only");
    b.hwrite(0x645,0);b.select(1);b.csr(2,0xc0,1,0);b.pending(8,0,false,false,"guest1 interrupt mask");
    b.csr(2,0xc0,1,2);b.pending(10,0x400,false,true,"guest1 pending survives interrupt masking");
    b.d.set_io$$vsGlobalEnable(0);b.pending(10,0x400,false,false,"VS SIE masks VS delivery");
    b.d.set_io$$hideleg(0);b.pending(10,0x400,true,false,"undelegated VSEI routes HS even while VS SIE clear");
    b.check(b.d.get_io$$hsCause(),10,"HS keeps cause10");
    b.d.set_io$$virtualized(0);b.d.set_io$$hsGlobalEnable(0);b.pending(10,0x400,false,false,"HS SIE masks host delivery");
    b.d.set_io$$hsGlobalEnable(1);b.pending(10,0x400,true,false,"HS SIE enables host delivery");
    std::cout<<"H_IMSIC_GUEST_CHAIN_PASS edges="<<b.cycles<<" checks="<<b.checks<<" transactions="<<b.transactions<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
