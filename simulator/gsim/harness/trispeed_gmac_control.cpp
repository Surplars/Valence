#include "TriSpeedControlGsim.h"
#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string_view>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool ok,const char*why){if(!ok)throw std::runtime_error(why);}
struct Test{
    STriSpeedControlGsim d;std::mt19937 random{0x64c5a};unsigned accesses=0,restarts=0,stalls=0;
    Test(){S(registers$$request$$valid,0);S(registers$$response$$ready,1);S(mediaStatus,0x010000000000902bULL);S(phyErrors,0x800000017ffffffeULL);S(phyPolls,0xffff000012345678ULL);S(phyTransitions,0x13579bdf2468ace0ULL);
        S(diagnosticIndex,0);S(diagnosticIncrement,0);S(totalIndex,0);S(totalIncrement,0);S(linkUp,1);S(txBusy,0);S(rxBusy,0);S(rxDrained,0);S(events,0);S(mdioCommand$$ready,1);S(mdioResponse$$valid,0);S(mdioResponse$$bits$$data,0);S(mdioResponse$$bits$$noAck,0);d.set_reset(1);d.step();d.step();d.set_reset(0);tick();}
    void tick(){d.step();restarts+=G(restartPhy);}
    uint64_t access(unsigned offset,bool write=false,uint64_t data=0,unsigned size=3,unsigned mask=255,bool error=false){
        S(registers$$request$$bits$$address,0x10040000ULL+offset);S(registers$$request$$bits$$write,write);S(registers$$request$$bits$$data,data);S(registers$$request$$bits$$size,size);S(registers$$request$$bits$$byteEnable,mask);S(registers$$request$$valid,1);S(registers$$response$$ready,0);
        unsigned n=0;do{tick();check(++n<1000,"tri-speed CSR request timed out");}while(!G(registers$$request$$ready));S(registers$$request$$valid,0);
        do{tick();check(++n<1000,"tri-speed CSR response timed out");}while(!G(registers$$response$$valid));const uint64_t result=G(registers$$response$$bits$$data);check(bool(G(registers$$response$$bits$$error))==error,"tri-speed CSR error/legality mismatch");
        for(unsigned hold=0;hold<random()%5;++hold){tick();++stalls;check(G(registers$$response$$valid)&&G(registers$$response$$bits$$data)==result&&bool(G(registers$$response$$bits$$error))==error,"tri-speed CSR reply changed under backpressure");}
        S(registers$$response$$ready,1);tick();++accesses;return result;
    }
};
int main(int argc,char**argv){try{
    Test t;bool inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    check(t.access(0)==0x56474d4100010001ULL,"legacy GMAC identity changed");const auto cap=t.access(8);check((cap&0x1f00)==0x1f00&&((cap>>24)&255)==4,"tri-speed capability advertisement mismatch");
    check(t.access(0x98)==(0x010000000000902bULL^inject),"tri-speed CSR independent 64-bit oracle mismatch");
    check(t.access(0xa0)==0x800000017ffffffeULL&&t.access(0xa8)==0xffff000012345678ULL&&t.access(0x110)==0x13579bdf2468ace0ULL,"PHY diagnostic64 snapshot mismatch");
    check(t.access(0xa4,false,0,2,15)==0x80000001ULL,"upper32 native CSR lane read mismatch");
    std::array<unsigned,14> offsets{0xb0,0xb8,0xc0,0xc8,0xd0,0xd8,0xe0,0xe8,0xf0,0xf8,0x100,0x108,0x120,0x128};
    for(unsigned index=0;index<offsets.size();++index){t.S(diagnosticIndex,index);t.S(diagnosticIncrement,0xffffffffU);t.tick();t.tick();t.S(diagnosticIncrement,0);check(t.access(offsets[index])==0x1fffffffeULL,"tri-speed diagnostic64 lost carry");check(t.access(offsets[index]+4,false,0,2,15)==1,"tri-speed diagnostic upper32 lane mismatch");}
    t.access(0x70,true,1);for(auto offset:offsets)check(t.access(offset)==0,"tri-speed clear-stats missed a diagnostic counter");
    t.access(0x118,true,1);check(t.restarts==1,"PHY restart command not one pulse");t.access(0x118,true,1,2,15,true);check(t.restarts==1,"partial PHY restart was not rejected");
    t.access(0x118,true,2,3,255,true);t.access(0x120,true,1,3,255,true);t.access(0x130,false,0,3,255,true);
    t.S(txBusy,1);t.access(0x10,true,3,3,255,true);t.S(txBusy,0);t.access(0x10,true,3);check(t.access(0x10)==3,"legacy control register changed");
    t.access(0x90,true,1);check(t.access(0x90)==1,"RX admission request changed");t.S(rxDrained,1);check(t.access(0x90)==3,"RX drain acknowledgement changed");
    // Complete native64 software command ABI into external serialized MDIO owner.
    const uint64_t command=0x1234ULL|(1ULL<<17)|(1ULL<<18)|(2ULL<<23);t.access(0x78,true,command);check(t.access(0x80)==1,"external MDIO command lost busy ownership");
    t.S(mdioResponse$$bits$$data,0x001c);t.S(mdioResponse$$bits$$noAck,0);t.S(mdioResponse$$valid,1);t.tick();t.S(mdioResponse$$valid,0);
    check(t.access(0x80)==2&&t.access(0x88)==0x001c&&t.access(0x30)==64,"external MDIO response/result/IRQ mismatch");
    std::cout<<"TRISPEED_CSR_PASS accesses="<<t.accesses<<" stalled_reply_cycles="<<t.stalls<<" counter64_carries=14 upper32_reads=15 readonly_denials=1 legacy_offsets=1 managed_mdio=1 restart_pulses="<<t.restarts<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
