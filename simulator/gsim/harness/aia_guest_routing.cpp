#include "AiaGuestRoutingGsim.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool ok,const char* what) { if(!ok) throw std::runtime_error(what); }
struct Driver {
    SAiaGuestRoutingGsim d;
    unsigned cycle=0, msis=0;
    bool allow=true, negative=false;
    Driver(bool n):negative(n) {
        defaults(); d.set_io$$sources(0); d.set_io$$allowMsi(1);
        d.set_io$$commit(1); d.set_io$$hie(0x1444); d.set_io$$hideleg(0x444);
        d.set_io$$privilege(1); d.set_io$$virtualized(1);
        d.set_io$$hsGlobalEnable(0); d.set_io$$vsGlobalEnable(0);
        d.set_reset(1);tick();tick();d.set_reset(0);idle(3);
    }
    void defaults() {
        d.set_io$$machine$$request$$valid(0); d.set_io$$machine$$response$$ready(1);
        d.set_io$$supervisor$$request$$valid(0); d.set_io$$supervisor$$response$$ready(1);
        d.set_io$$csrRequest$$valid(0); d.set_io$$csrResponse$$ready(1);
        d.set_io$$write$$valid(0); d.set_io$$setVgein$$valid(0);
    }
    void tick() { d.set_io$$allowMsi(allow);d.step();++cycle;if(d.get_io$$msiFire())++msis; }
    void idle(unsigned n=12) { defaults();while(n--)tick(); }
    void write(unsigned address,uint64_t data) {
        d.set_io$$write$$valid(1);d.set_io$$write$$bits$$address(address);
        d.set_io$$write$$bits$$data(data);tick();d.set_io$$write$$valid(0);tick();
    }
    void select(unsigned guest) {
        d.set_io$$setVgein$$valid(1);d.set_io$$setVgein$$bits(guest);
        tick();d.set_io$$setVgein$$valid(0);tick();
    }
    uint64_t bus(unsigned port,unsigned offset,bool write,uint32_t data=0) {
        bool accepted=false;
        for(unsigned n=0;n<100;++n) {
#define DRIVE(name,base) \
            d.set_io$$##name##$$request$$valid(!accepted); \
            d.set_io$$##name##$$request$$bits$$address(base+offset); \
            d.set_io$$##name##$$request$$bits$$write(write); \
            d.set_io$$##name##$$request$$bits$$size(2); \
            d.set_io$$##name##$$request$$bits$$data(data); \
            d.set_io$$##name##$$request$$bits$$byteEnable(15)
            if(port==0){DRIVE(machine,0x0c000000);}else{DRIVE(supervisor,0x0c004000);}
#undef DRIVE
            tick();bool ready,valid,error;uint64_t value;
#define SAMPLE(name) \
            ready=d.get_io$$##name##$$request$$ready(); \
            valid=d.get_io$$##name##$$response$$valid(); \
            error=d.get_io$$##name##$$response$$bits$$error(); \
            value=d.get_io$$##name##$$response$$bits$$data()
            if(port==0){SAMPLE(machine);}else{SAMPLE(supervisor);}
#undef SAMPLE
            if(!accepted&&ready)accepted=true;
            if(valid){check(accepted&&!error,"APLIC MMIO completion");defaults();return value;}
        }
        throw std::runtime_error("APLIC MMIO timeout");
    }
    uint64_t csr(unsigned file,unsigned selector,unsigned operation=0,uint64_t data=0,
                 bool claim=false,unsigned hold=0) {
        bool accepted=false,seen=false;uint64_t saved=0;
        for(unsigned n=0;n<100;++n) {
            d.set_io$$csrRequest$$valid(!accepted);d.set_io$$csrRequest$$bits$$file(file);
            d.set_io$$csrRequest$$bits$$selector(selector);d.set_io$$csrRequest$$bits$$operation(operation);
            d.set_io$$csrRequest$$bits$$data(data);d.set_io$$csrRequest$$bits$$topei(claim);
            d.set_io$$csrResponse$$ready(n>=hold);tick();
            if(!accepted&&d.get_io$$csrRequest$$ready())accepted=true;
            if(d.get_io$$csrResponse$$valid()) {
                check(accepted&&!d.get_io$$csrResponse$$bits$$error(),"IMSIC CSR completion");
                uint64_t value=d.get_io$$csrResponse$$bits$$data();
                if(seen)check(saved==value,"claim response changed under backpressure");
                seen=true;saved=value;
                if(claim&&operation&&hold)check(d.get_io$$hgeip()==0,"claim did not clear IRQ while response held");
                if(n>=hold){defaults();return value;}
            }
        }
        throw std::runtime_error("IMSIC CSR timeout");
    }
    void state(uint64_t geip,uint64_t hip,uint64_t vsip,bool hs,unsigned hsCause,bool vs,unsigned vsCause) {
        idle(2);
        if(negative && geip==2)geip=4;
        bool ok=d.get_io$$hgeip()==geip&&d.get_io$$hip()==hip&&d.get_io$$vsip()==vsip&&
            bool(d.get_io$$hsPending())==hs&&bool(d.get_io$$vsPending())==vs&&
            (!hs||d.get_io$$hsCause()==hsCause)&&(!vs||d.get_io$$vsCause()==vsCause);
        if(!ok)std::cerr<<"cycle="<<cycle<<" actual="<<d.get_io$$hgeip()<<','<<d.get_io$$hip()<<','
            <<d.get_io$$vsip()<<','<<d.get_io$$hsPending()<<','<<d.get_io$$hsCause()<<','
            <<d.get_io$$vsPending()<<','<<d.get_io$$vsCause()<<" expected="<<geip<<','<<hip<<','
            <<vsip<<','<<hs<<','<<hsCause<<','<<vs<<','<<vsCause<<'\n';
        check(ok,"independent APLIC IMSIC guest routing oracle");
    }
};
int main(int argc,char**argv){try {
    Driver t(argc>1&&std::string(argv[1])=="--wrong-guest");
    t.bus(0,4,true,0x400);t.bus(0,8,true,0x400);
    t.bus(1,4,true,6);t.bus(1,8,true,1);
    t.bus(1,0x3004,true,0x100b);t.bus(1,0x3008,true,0x200d);
    t.bus(1,0x1e00,true,6);t.bus(1,0,true,0x100);
    t.csr(2,0x70,1,1);t.csr(2,0xc0,1,1U<<11);
    t.csr(3,0x70,1,1);t.csr(3,0xc0,1,1U<<13);
    t.select(1);
    // An actual level-sensitive APLIC wire traverses both controllers.
    t.d.set_io$$sources(1);t.idle();
    t.state(2,0x400,0x200,false,0,false,0); // VS global enable is clear.
    t.d.set_io$$vsGlobalEnable(1);t.state(2,0x400,0x200,false,0,true,9);
    t.d.set_io$$hie(0);t.state(2,0x400,0x200,false,0,false,0);
    t.d.set_io$$hie(0x1444);t.state(2,0x400,0x200,false,0,true,9);
    t.write(0x607,4);t.state(2,0x400,0x200,false,0,true,9);
    t.bus(1,0x1cdc,true,2);t.idle();
    t.state(6,0x1400,0x200,true,12,true,9); // Both local candidates; caller arbitrates.
    t.d.set_io$$hie(0x400);t.state(6,0x1400,0x200,false,0,true,9);
    t.d.set_io$$hie(0x1000);t.state(6,0x1400,0x200,true,12,false,0);
    t.d.set_io$$hie(0x1444);t.state(6,0x1400,0x200,true,12,true,9);
    t.write(0x607,0);t.state(6,0x400,0x200,false,0,true,9);
    t.select(2);check(t.d.get_io$$vgein()==2,"VGEIN update");
    check(t.csr(3,0,1,0,true)==0xd000d,"selected guest2 claim identity");
    t.state(2,0,0,false,0,false,0);
    t.write(0x607,2);t.state(2,0x1000,0,true,12,false,0);
    t.select(1);t.state(2,0x1400,0x200,true,12,true,9);
    t.d.set_io$$commit(0);t.select(2);t.write(0x607,0);
    check(t.d.get_io$$vgein()==1&&t.d.get_io$$hgeie()==2,"uncommitted update changed guest owner");
    t.state(2,0x1400,0x200,true,12,true,9);t.d.set_io$$commit(1);
    t.d.set_io$$hideleg(0);t.state(2,0x1400,0,true,12,false,0);
    t.write(0x607,0);t.state(2,0x400,0,true,10,false,0);
    t.d.set_io$$virtualized(0);t.state(2,0x400,0,false,0,false,0);
    t.d.set_io$$hsGlobalEnable(1);t.state(2,0x400,0,true,10,false,0);
    t.d.set_io$$privilege(3);t.state(2,0x400,0,false,0,false,0);
    t.d.set_io$$privilege(0);t.d.set_io$$virtualized(1);
    t.d.set_io$$vsGlobalEnable(0);t.d.set_io$$hideleg(0x444);
    t.state(2,0x400,0x200,false,0,true,9); // VU does not depend on VS.SIE.
    t.d.set_io$$privilege(1);t.d.set_io$$vsGlobalEnable(1);
    t.csr(2,0x70,1,0);t.state(0,0,0,false,0,false,0);
    check(t.csr(2,0,0,0,true)==0xb000b,"eidelivery masked TOPEI");
    t.csr(2,0x70,1,1);t.csr(2,0x72,1,11);t.state(0,0,0,false,0,false,0);
    check(t.csr(2,0,0,0,true)==0,"threshold did not mask TOPEI");
    t.csr(2,0x72,1,12);t.state(2,0x400,0x200,false,0,true,9);
    t.csr(2,0xc0,1,0);t.state(0,0,0,false,0,false,0);
    t.csr(2,0xc0,1,1U<<11);t.state(2,0x400,0x200,false,0,true,9);
    check(t.csr(2,0,1,0,true,10)==0xb000b,"backpressured guest claim identity");
    t.state(0,0,0,false,0,false,0);check(t.msis==2,"asserted level produced duplicate MSI");
    // A selected guest cannot observe a queued MSI before it enters IMSIC.
    t.allow=false;t.bus(1,0x1cdc,true,1);t.idle();
    check(t.d.get_io$$msiValid(),"MSI backpressure not reached");
    check(t.d.get_io$$msiAddress()==0x28001000&&t.d.get_io$$msiData()==11,"queued guest target");
    t.state(0,0,0,false,0,false,0);t.select(2);
    t.allow=true;t.idle();t.state(2,0,0,false,0,false,0);
    t.write(0x607,2);t.state(2,0x1000,0,true,12,false,0);
    t.select(1);t.state(2,0x1400,0x200,true,12,true,9);
    // Delegation revocation stops new forwarding, but never clears IMSIC state.
    t.bus(0,4,true,0);t.idle();t.state(2,0x1400,0x200,true,12,true,9);
    check(t.csr(2,0,1,0,true)==0xb000b,"revocation erased accepted guest interrupt");
    t.state(0,0,0,false,0,false,0);t.bus(1,0x1cdc,true,1);t.idle();
    check(t.msis==3,"revoked source forwarded a new MSI");
    t.bus(0,4,true,0x400);check(t.bus(1,4,false)==0,"redelegation restored old source config");
    t.select(0);t.write(0x645,0x400);t.state(0,0x400,0x200,false,0,true,9);
    t.write(0x645,0);t.state(0,0,0,false,0,false,0);
    std::cout<<"AIA_GUEST_ROUTING_PASS msis="<<t.msis<<" cycles="<<t.cycle
        <<" real_wire=1 guest_selection=1 hgeie_independent=1 hie_masks=1 delegated=1 masked=1 claim_stall=1\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"AIA_GUEST_ROUTING_FAIL "<<e.what()<<'\n';return 1;}}
