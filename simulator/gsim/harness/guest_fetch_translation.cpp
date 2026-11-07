#include "GuestFetchTranslationGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <vector>

static constexpr uint64_t MODE=uint64_t(8)<<60, V=1,R=2,W=4,X=8,U=16,G=32,A=64,D=128;
struct Request {
    uint64_t va=0x12345000,vsatp=0,hgatp=0;
    unsigned privilege=1,access=0,size=3,epoch=17;
    bool guest=true,sum=false,vmxr=false,hmxr=false,hlvx=false;
};
struct Response {
    uint64_t pa=0,va=0,gpa=0;
    unsigned level=0,epoch=0;
    bool pf=false,gpf=false,af=false,implicit=false,guest=false,cancelled=false,global=false;
    bool operator==(const Response&) const = default;
};
struct Case {
    Request q;
    std::map<uint64_t,uint64_t> memory;
    uint64_t pmpTop=(uint64_t(1)<<54)-1,errorAddress=~uint64_t(0);
    unsigned permission=7;
    std::string name;
};
static uint64_t pte(uint64_t pa,uint64_t flags){return (pa>>12<<10)|flags;}
static uint64_t leafOffset(uint64_t address,unsigned level){return address&((uint64_t(1)<<(12+9*level))-1);}
static void mapG(Case& c,uint64_t gpa,uint64_t spa,unsigned level,uint64_t flags) {
    uint64_t table=0x200000;
    for(int l=2;l>=int(level);--l){
        unsigned bits=l==2?11:9;
        uint64_t address=table+(((gpa>>(12+9*l))&((1<<bits)-1))*8);
        if(l==int(level)){c.memory[address]=pte(spa,flags);return;}
        // Distinct physical subtree per top-level index avoids accidental overlap.
        uint64_t next=0x400000+((gpa>>30)&2047)*0x3000+(2-l)*0x1000;
        c.memory[address]=pte(next,V);table=next;
    }
}
static Case nested(unsigned vl=0,unsigned gl=0,uint64_t vf=V|R|W|X|A|D,uint64_t gf=V|R|W|X|U|A|D) {
    Case c;c.name="nested";c.q.va=0x12345678;c.q.size=0;c.q.vsatp=MODE|0x100;c.q.hgatp=MODE|0x200;
    // VS PTEs are guest physical addresses. Their G mapping is intentionally
    // separate from the final page, so implicit load permissions are independent.
    mapG(c,0x100000,0x40000000,2,V|R|U|A);
    const uint64_t gbase=0x80000000,spabase=0xc0000000;
    uint64_t table=0x100000;
    for(int l=2;l>=int(vl);--l){
        uint64_t address=table+(((c.q.va>>(12+9*l))&511)*8);
        if(l==int(vl))c.memory[0x40000000+address]=pte(gbase,vf);
        else {uint64_t next=table+0x1000;c.memory[0x40000000+address]=pte(next,V);table=next;}
    }
    uint64_t gpa=gbase+leafOffset(c.q.va,vl);
    mapG(c,gpa,spabase,gl,gf);
    return c;
}
#ifndef PARCEL_BYTES
#error PARCEL_BYTES required
#endif
struct Expect {
    bool pf=false,gpf=false,af=false,implicit=false,pma=false,busError=false;
    uint64_t gpa=0,pa=0xc0000678;
    unsigned cancel=0; // PTW wait, held physical offer, physical wait, held response, translation offer.
};
struct Reply {
    uint64_t data=0,gpa=0,va=0;unsigned epoch=0;
    bool error=false,pf=false,gpf=false,guest=false,implicit=false,cancelled=false;
    bool operator==(const Reply&) const = default;
};
class Bench {
    SGuestFetchTranslationGsim dut{};std::mt19937_64 random{0x4645544348414441ULL};
public:
    uint64_t cycles=0,requests=0,pteReads=0,physicalAccesses=0;
    Bench(){std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();dut.set_reset(1);dut.step();dut.set_reset(0);dut.step();}
    void check(bool yes,const std::string& what){if(!yes)throw std::runtime_error(what);}
    Reply observe(){Reply r;r.data=dut.get_io$$virtual$$response$$bits();
        r.error=dut.get_io$$virtual$$responseError();r.pf=dut.get_io$$virtual$$responsePageFault();
        r.gpf=dut.get_io$$guestFault$$guestPageFault();r.guest=dut.get_io$$guestFault$$guestAddress();
        r.gpa=dut.get_io$$guestFault$$guestPhysicalAddress();r.implicit=dut.get_io$$guestFault$$implicitPte();
        r.cancelled=dut.get_io$$cancelled();r.epoch=dut.get_io$$responseEpoch();r.va=dut.get_io$$responseAddress();return r;}
    void run(Case c,Expect expected={}) {
        bool accepted=false,ptePending=false,physicalPending=false,heldPhysical=false,heldReply=false,cancelSent=false,pmaSeen=false;
        unsigned pteDelay=0,physicalDelay=0,responseStalls=0,physCount=0;uint64_t pteData=0,priorPa=0;bool pteError=false;
        Reply prior{};
        for(unsigned cycle=0;cycle<1500;cycle++){
            bool cancel=!cancelSent&&((expected.cancel==1&&ptePending)||(expected.cancel==2&&heldPhysical)||
                (expected.cancel==3&&physicalPending)||(expected.cancel==4&&heldReply)||(expected.cancel==5&&accepted));
            if(cancel)cancelSent=true;
            dut.set_io$$cancel(cancel);dut.set_io$$virtual$$request$$valid(!accepted);
            uint64_t noise=accepted?random():0;const Request& q=c.q;
            dut.set_io$$virtual$$request$$bits(q.va^noise);
            dut.set_io$$context$$virtualAddress(noise);dut.set_io$$context$$vsatp(q.vsatp^noise);dut.set_io$$context$$hgatp(q.hgatp^noise);
            dut.set_io$$context$$virtualized(q.guest^(accepted&&(noise&1)));dut.set_io$$context$$effectivePrivilege(accepted?(noise&3):q.privilege);
            // The fetch adapter, not a caller placeholder, chooses X, parcel size and no HLVX override.
            dut.set_io$$context$$access(3);dut.set_io$$context$$size(0);dut.set_io$$context$$forceExecute(1);
            dut.set_io$$context$$vsSum(q.sum^(accepted&&(noise&1)));dut.set_io$$context$$vsMxr(q.vmxr^(accepted&&(noise&1)));
            dut.set_io$$context$$hsMxr(q.hmxr^(accepted&&(noise&1)));dut.set_io$$context$$epoch(q.epoch^(noise&255));
            dut.set_io$$pmpTop(c.pmpTop);dut.set_io$$pmpPermission(c.permission);
            dut.set_io$$pmaDenied(pmaSeen?(random()&1):expected.pma);
            bool pteReady=random()%4!=0,pteValid=ptePending&&pteDelay==0;
            dut.set_io$$memory$$request$$ready(pteReady);dut.set_io$$memory$$response$$valid(pteValid);
            dut.set_io$$memory$$response$$bits$$data(pteData);dut.set_io$$memory$$response$$bits$$error(pteError);
            bool physicalReady=random()%4!=0;if(expected.cancel==2&&!cancelSent)physicalReady=false;
            bool physicalValid=physicalPending&&physicalDelay==0;
            dut.set_io$$physical$$request$$ready(physicalReady);dut.set_io$$physical$$response$$valid(physicalValid);
            dut.set_io$$physical$$response$$bits(PARCEL_BYTES==2?0xbeef:0xdeadbeef);
            dut.set_io$$physical$$responseError(expected.busError);dut.set_io$$physical$$responsePageFault(0);
            bool replyReady=responseStalls>=4&&(random()%3!=0);dut.set_io$$virtual$$response$$ready(replyReady);
            dut.step();cycles++;
            if(!accepted&&dut.get_io$$virtual$$request$$ready()){accepted=true;requests++;}
            if(dut.get_io$$physicalCheck$$valid()){pmaSeen=true;
                check(dut.get_io$$physicalCheck$$bits$$address()==expected.pa,c.name+": PMA address");
                check(dut.get_io$$physicalCheck$$bits$$size()==(PARCEL_BYTES==2?1:2)&&dut.get_io$$physicalCheck$$bits$$access()==2&&
                    !dut.get_io$$physicalCheck$$bits$$forceExecute(),c.name+": PMA instruction execute/parcel size");}
            if(ptePending&&pteDelay)pteDelay--;
            if(pteValid&&dut.get_io$$memory$$response$$ready())ptePending=false;
            if(dut.get_io$$memory$$request$$valid()&&pteReady){auto address=dut.get_io$$memory$$request$$bits();
                check(!ptePending&&c.memory.count(address),c.name+": PTE address or credit");
                pteData=c.memory.at(address);pteError=address==c.errorAddress;ptePending=true;pteDelay=1+random()%3;pteReads++;}
            bool offer=dut.get_io$$physical$$request$$valid();auto address=dut.get_io$$physical$$request$$bits();
            if(heldPhysical)check(offer&&address==priorPa,c.name+": held physical offer changed");
            if(offer){check(!expected.pma&&!expected.pf&&!expected.gpf&&!expected.af,c.name+": fault issued instruction fetch");
                check(address==expected.pa,c.name+": wrong physical fetch address");}
            heldPhysical=offer&&!physicalReady;priorPa=address;
            if(physicalPending&&physicalDelay)physicalDelay--;
            if(physicalValid&&dut.get_io$$physical$$response$$ready())physicalPending=false;
            if(offer&&physicalReady){check(!physicalPending,c.name+": duplicated physical credit");physicalPending=true;physicalDelay=2+random()%5;physCount++;physicalAccesses++;}
            bool valid=dut.get_io$$virtual$$response$$valid();
            if(heldReply)check(valid&&observe()==prior,c.name+": held fetch response/provenance changed");
            if(valid){responseStalls++;prior=observe();heldReply=true;
                if(replyReady){auto r=prior;check(!ptePending&&!physicalPending,c.name+": response did not drain children");
                    bool cancelled=expected.cancel&&expected.cancel!=4;
                    check(r.va==q.va&&r.epoch==q.epoch,c.name+": original parcel/epoch owner changed");
                    check(r.cancelled==cancelled,c.name+": cancellation disposition");
                    if(cancelled){check(!r.error&&!r.pf&&!r.gpf&&!r.implicit&&r.gpa==0,c.name+": cancelled trap escaped");
                        check(physCount==((expected.cancel==2||expected.cancel==3)?1:0),c.name+": cancelled physical count");}
                    else {bool error=expected.pf||expected.gpf||expected.af||expected.pma||expected.busError;
                        check(r.error==error&&r.pf==expected.pf&&r.gpf==expected.gpf&&r.implicit==expected.implicit&&r.gpa==expected.gpa&&r.guest==q.guest,
                            c.name+": precise fetch fault provenance");
                        check(physCount==((expected.pf||expected.gpf||expected.af||expected.pma)?0:1),c.name+": physical instruction count");
                        if(!error)check(r.data==(PARCEL_BYTES==2?0xbeef:0xdeadbeef),c.name+": physical parcel data");}
                    return;}
            }
        }
        throw std::runtime_error(c.name+": timeout");
    }
};
int main(){try{
    Bench b;
    for(unsigned n=0;n<128;n++){Case c=nested();c.name="captured fetch context";c.q.epoch=n;b.run(c);}
    for(unsigned cancel=1;cancel<=5;cancel++){auto c=nested();c.name="fetch cancellation/drain";Expect e;e.cancel=cancel;b.run(c,e);}
    {auto c=nested(0,0,V|X|A,V|X|U|A);c.name="execute-only nested leaves";b.run(c);}
    {auto c=nested(0,0,V|R|A,V|X|U|A);c.name="read-only VS cannot fetch";Expect e;e.pf=true;b.run(c,e);}
    {auto c=nested(0,0,V|X|A,V|R|U|A);c.name="read-only G cannot fetch";Expect e;e.gpf=true;e.gpa=0x80000678;b.run(c,e);}
    {auto c=nested();c.name="instruction implicit guest fault";c.memory[0x200000]=pte(0x40000000,V|X|U|A);Expect e;e.gpf=true;e.implicit=true;e.gpa=0x100000;b.run(c,e);}
    {auto c=nested(0,0,V|X|A,V|X|A);c.name="instruction G U denial";Expect e;e.gpf=true;e.gpa=0x80000678;b.run(c,e);}
    {auto c=nested(0,0,V|X|U|A);c.name="supervisor U fetch denied despite SUM";c.q.sum=true;Expect e;e.pf=true;b.run(c,e);}
    {auto c=nested(0,0,V|X|U|A);c.name="VU execute permission";c.q.privilege=0;b.run(c);}
    {auto c=nested();c.name="physical PTE access fault";c.errorAddress=0x200000;Expect e;e.af=true;b.run(c,e);}
    {auto c=nested();c.name="final execute PMA denial";Expect e;e.pma=true;b.run(c,e);}
    {auto c=nested();c.name="physical instruction bus error";Expect e;e.busError=true;b.run(c,e);}
    {Case c;c.name="guest Bare still uses G";c.q.va=0x12345678;c.q.hgatp=MODE|0x200;mapG(c,c.q.va,0xc0000000,0,V|X|U|A);b.run(c);}
    {Case c;c.name="host Bare execute-only PMP";c.q.guest=false;c.q.va=0x678;c.permission=4;Expect e;e.pa=0x678;b.run(c,e);}
    {auto c=nested();c.name="page final parcel";c.q.va=0x12346000-PARCEL_BYTES;Expect e;e.pa=0xc0001000-PARCEL_BYTES;b.run(c,e);}
    {auto c=nested();c.name="next page precise guest GPA";c.q.va=0x12346000;
        c.memory[0x40102000+(((c.q.va>>12)&511)*8)]=pte(0x80001000,V|X|A);
        c.memory[0x407008]=0;Expect e;e.gpf=true;e.gpa=0x80001000;b.run(c,e);}
    {Case c;c.name="x4 high quadrant fetch";c.q.va=(uint64_t(3)<<39)|0x12345678;c.q.hgatp=MODE|0x200;
        mapG(c,c.q.va,0xc0000000,0,V|X|U|A);b.run(c);}
    std::cout<<"GUEST_FETCH_ADAPTER_PASS parcel_bytes="<<PARCEL_BYTES<<" requests="<<b.requests<<" physical_ops="<<b.physicalAccesses<<" pte_reads="<<b.pteReads<<" cycles="<<b.cycles<<"\n";return 0;
}catch(const std::exception& e){std::cerr<<"GUEST_FETCH_ADAPTER_FAIL "<<e.what()<<"\n";return 1;}}
