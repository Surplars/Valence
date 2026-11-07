#include "GuestDataTranslationGsim.h"
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
struct Data {
    bool write=false,atomic=false,uncached=false;unsigned op=0,handle=37,mask=0xa5;
    uint64_t data=0x83749105fabe1134ULL;
};
struct Expect {
    bool pf=false,gpf=false,af=false,implicit=false,pma=false,busError=false;
    uint64_t gpa=0,pa=0xc0000678;
    unsigned cancel=0; // 1=PTW wait, 2=held physical offer, 3=physical wait, 4=held reply, 5=translation offer.
};
struct Reply {
    uint64_t data=0,gpa=0;unsigned handle=0,epoch=0;
    bool error=false,pf=false,gpf=false,guest=false,implicit=false,cancelled=false;
    bool operator==(const Reply&) const = default;
};
class Bench {
    SGuestDataTranslationGsim dut{};std::mt19937_64 random{0x41444150544552ULL};
public:
    uint64_t cycles=0,requests=0,pteReads=0,physicalAccesses=0;
    Bench(){std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();dut.set_reset(1);dut.step();dut.set_reset(0);dut.step();}
    void check(bool yes,const std::string& what){if(!yes)throw std::runtime_error(what);}
    Reply observe(){Reply r;r.data=dut.get_io$$virtual$$response$$bits$$data();r.handle=dut.get_io$$virtual$$response$$bits$$returnHandle();
        r.error=dut.get_io$$virtual$$response$$bits$$error();r.pf=dut.get_io$$virtual$$response$$bits$$pageFault();
        r.gpf=dut.get_io$$guestFault$$guestPageFault();r.guest=dut.get_io$$guestFault$$guestAddress();
        r.gpa=dut.get_io$$guestFault$$guestPhysicalAddress();r.implicit=dut.get_io$$guestFault$$implicitPte();
        r.cancelled=dut.get_io$$cancelled();r.epoch=dut.get_io$$responseEpoch();return r;}
    void run(Case c,Data data={},Expect expected={}) {
        bool accepted=false,ptePending=false,physicalPending=false,heldPhysical=false,heldReply=false,cancelSent=false,pmaSeen=false;
        unsigned pteDelay=0,physicalDelay=0,responseStalls=0,physCount=0;uint64_t pteData=0;bool pteError=false;
        Reply prior{};
        for(unsigned cycle=0;cycle<1500;cycle++){
            bool cancel=!cancelSent&&((expected.cancel==1&&ptePending)||(expected.cancel==2&&heldPhysical)||
                (expected.cancel==3&&physicalPending)||(expected.cancel==4&&heldReply)||(expected.cancel==5&&accepted));
            if(cancel)cancelSent=true;
            dut.set_io$$cancel(cancel);dut.set_io$$virtual$$request$$valid(!accepted);
            uint64_t noise=accepted?random():0;const Request& q=c.q;
            dut.set_io$$virtual$$request$$bits$$address(q.va^noise);
            dut.set_io$$virtual$$request$$bits$$size(accepted?(noise&3):q.size);
            dut.set_io$$virtual$$request$$bits$$write(data.write^(accepted&&(noise&1)));
            dut.set_io$$virtual$$request$$bits$$atomic(data.atomic^(accepted&&(noise&1)));
            dut.set_io$$virtual$$request$$bits$$atomicOp(data.op^(noise&31));
            dut.set_io$$virtual$$request$$bits$$data(data.data^noise);dut.set_io$$virtual$$request$$bits$$mask(data.mask^(noise&255));
            dut.set_io$$virtual$$request$$bits$$returnHandle(data.handle^(noise&63));
            dut.set_io$$virtual$$request$$bits$$virtualized(1);dut.set_io$$virtual$$request$$bits$$precheckedLoad(1);
            dut.set_io$$virtual$$request$$bits$$translationEpoch(0xfedcba98);dut.set_io$$virtual$$request$$bits$$prefetchNextAllowed(1);
            dut.set_io$$virtual$$request$$bits$$uncached(data.uncached);
            dut.set_io$$context$$virtualAddress(noise);dut.set_io$$context$$vsatp(q.vsatp^noise);dut.set_io$$context$$hgatp(q.hgatp^noise);
            dut.set_io$$context$$virtualized(q.guest^(accepted&&(noise&1)));dut.set_io$$context$$effectivePrivilege(accepted?(noise&3):q.privilege);
            dut.set_io$$context$$access(3);dut.set_io$$context$$size(0);
            dut.set_io$$context$$vsSum(q.sum^(accepted&&(noise&1)));dut.set_io$$context$$vsMxr(q.vmxr^(accepted&&(noise&1)));
            dut.set_io$$context$$hsMxr(q.hmxr^(accepted&&(noise&1)));dut.set_io$$context$$forceExecute(q.hlvx^(accepted&&(noise&1)));
            dut.set_io$$context$$epoch(q.epoch^(noise&255));
            dut.set_io$$pmpTop(c.pmpTop);dut.set_io$$pmpPermission(c.permission);
            // Once authorized, later PMA input changes cannot revoke a held offer.
            dut.set_io$$pmaDenied(pmaSeen?(random()&1):expected.pma);
            bool pteReady=random()%4!=0,pteValid=ptePending&&pteDelay==0;
            dut.set_io$$memory$$request$$ready(pteReady);dut.set_io$$memory$$response$$valid(pteValid);
            dut.set_io$$memory$$response$$bits$$data(pteData);dut.set_io$$memory$$response$$bits$$error(pteError);
            bool physicalReady=random()%4!=0;if(expected.cancel==2&&!cancelSent)physicalReady=false;
            bool physicalValid=physicalPending&&physicalDelay==0;
            dut.set_io$$physical$$request$$ready(physicalReady);dut.set_io$$physical$$response$$valid(physicalValid);
            dut.set_io$$physical$$response$$bits$$data(0x1234abcd99887766ULL);
            dut.set_io$$physical$$response$$bits$$error(expected.busError);dut.set_io$$physical$$response$$bits$$pageFault(0);
            dut.set_io$$physical$$response$$bits$$returnHandle(data.handle);
            bool replyReady=responseStalls>=4&&(random()%3!=0);dut.set_io$$virtual$$response$$ready(replyReady);
            dut.step();cycles++;
            if(!accepted&&dut.get_io$$virtual$$request$$ready()){accepted=true;requests++;}
            bool checkValid=dut.get_io$$physicalCheck$$valid();
            if(checkValid){pmaSeen=true;unsigned access=data.atomic?(data.op==2?0:data.op==3?1:3):(data.write?1:0);
                check(dut.get_io$$physicalCheck$$bits$$address()==expected.pa,c.name+": PMA address");
                check(dut.get_io$$physicalCheck$$bits$$size()==q.size&&dut.get_io$$physicalCheck$$bits$$access()==access&&
                    bool(dut.get_io$$physicalCheck$$bits$$forceExecute())==q.hlvx,c.name+": PMA owner/access");}
            if(ptePending&&pteDelay)pteDelay--;
            if(pteValid&&dut.get_io$$memory$$response$$ready())ptePending=false;
            if(dut.get_io$$memory$$request$$valid()&&pteReady){auto address=dut.get_io$$memory$$request$$bits();
                check(!ptePending&&c.memory.count(address),c.name+": PTE address or credit");
                pteData=c.memory.at(address);pteError=address==c.errorAddress;ptePending=true;pteDelay=1+random()%3;pteReads++;}
            bool offer=dut.get_io$$physical$$request$$valid();
            if(heldPhysical)check(offer,c.name+": physical offer revoked");
            if(offer){
                check(!expected.pma&&!expected.pf&&!expected.gpf&&!expected.af,c.name+": fault issued physical traffic");
                check(dut.get_io$$physical$$request$$bits$$address()==expected.pa,c.name+": wrong physical address");
                check(dut.get_io$$physical$$request$$bits$$data()==data.data&&dut.get_io$$physical$$request$$bits$$mask()==data.mask&&
                    dut.get_io$$physical$$request$$bits$$returnHandle()==data.handle,c.name+": physical payload/handle changed");
                check(bool(dut.get_io$$physical$$request$$bits$$write())==data.write&&bool(dut.get_io$$physical$$request$$bits$$atomic())==data.atomic&&
                    dut.get_io$$physical$$request$$bits$$atomicOp()==data.op&&dut.get_io$$physical$$request$$bits$$size()==q.size&&
                    bool(dut.get_io$$physical$$request$$bits$$uncached())==data.uncached,c.name+": physical operation changed");
                check(!dut.get_io$$physical$$request$$bits$$virtualized()&&!dut.get_io$$physical$$request$$bits$$precheckedLoad()&&
                    !dut.get_io$$physical$$request$$bits$$translationEpoch()&&!dut.get_io$$physical$$request$$bits$$prefetchNextAllowed(),
                    c.name+": virtual proof leaked into physical port");
            }
            heldPhysical=offer&&!physicalReady;
            if(physicalPending&&physicalDelay)physicalDelay--;
            if(physicalValid&&dut.get_io$$physical$$response$$ready())physicalPending=false;
            if(offer&&physicalReady){check(!physicalPending,c.name+": duplicated physical credit");physicalPending=true;physicalDelay=2+random()%5;physCount++;physicalAccesses++;}
            bool valid=dut.get_io$$virtual$$response$$valid();
            if(heldReply)check(valid&&observe()==prior,c.name+": held response/guest metadata changed");
            if(valid){responseStalls++;prior=observe();heldReply=true;
                if(replyReady){auto r=prior;check(!ptePending&&!physicalPending,c.name+": completion did not drain children");
                    bool cancelled=expected.cancel&&expected.cancel!=4&&!data.write&&!data.atomic;
                    check(r.handle==data.handle&&r.epoch==q.epoch,c.name+": return owner changed");
                    check(r.cancelled==cancelled,c.name+": cancellation disposition");
                    if(cancelled){check(!r.error&&!r.pf&&!r.gpf&&!r.implicit&&r.gpa==0,c.name+": cancelled trap escaped");
                        check(physCount==((expected.cancel==2||expected.cancel==3)?1:0),c.name+": cancelled physical count");}
                    else {bool error=expected.pf||expected.gpf||expected.af||expected.pma||expected.busError;
                        check(r.error==error&&r.pf==expected.pf&&r.gpf==expected.gpf&&r.implicit==expected.implicit&&r.gpa==expected.gpa&&r.guest==q.guest,
                            c.name+": precise fault provenance");
                        check(physCount==((expected.pf||expected.gpf||expected.af||expected.pma)?0:1),c.name+": physical operation count");
                        if(!error)check(r.data==0x1234abcd99887766ULL,c.name+": physical response data");}
                    return;}
            }
        }
        throw std::runtime_error(c.name+": timeout");
    }
};
int main(){try{
    Bench b;
    for(unsigned n=0;n<64;n++){
        Case c=nested();c.name="read payload/context";c.q.epoch=n;Data d;d.handle=n;b.run(c,d);
        d.write=true;d.data^=n;d.mask=n;c.name="write real completion";b.run(c,d);
    }
    for(unsigned op:{0,1,2,3,4,8,12,16,20,24,28}){auto c=nested();c.name="atomic access classification";Data d;d.atomic=true;d.op=op;b.run(c,d);}
    for(unsigned cancel=1;cancel<=5;cancel++)for(unsigned kind=0;kind<3;kind++){
        auto c=nested();c.name="cancellation/drain";Data d;d.write=kind==1;d.atomic=kind==2;d.op=0;Expect e;e.cancel=cancel;b.run(c,d,e);}
    {auto c=nested();c.name="guest implicit fault";c.memory[0x200000]=pte(0x40000000,V|R|A);Expect e;e.gpf=true;e.implicit=true;e.gpa=0x100000;b.run(c,{},e);}
    {auto c=nested(0,0,V|R|A,V|R|A);c.name="guest final fault";Expect e;e.gpf=true;e.gpa=0x80000678;b.run(c,{},e);}
    {auto c=nested(0,0,V|R);c.name="VS page fault";Expect e;e.pf=true;b.run(c,{},e);}
    {auto c=nested();c.name="physical PTE access fault";c.errorAddress=0x200000;Expect e;e.af=true;b.run(c,{},e);}
    {auto c=nested();c.name="final PMA denial";Expect e;e.pma=true;b.run(c,{},e);}
    {auto c=nested();c.name="final physical bus error";Expect e;e.busError=true;b.run(c,{},e);}
    {auto c=nested(0,0,V|X|A,V|X|U|A);c.q.hlvx=true;c.name="HLVX physical execute query";b.run(c);}
    {Case c;c.name="guest Bare still translates G";c.q.va=0x12345678;c.q.size=0;c.q.hgatp=MODE|0x200;mapG(c,c.q.va,0xc0000000,0,V|R|U|A);b.run(c);}
    {Case c;c.name="host Bare context preserved";c.q.guest=false;c.q.va=0x678;c.q.size=0;Expect e;e.pa=0x678;b.run(c,{},e);}
    std::cout<<"GUEST_DATA_ADAPTER_PASS requests="<<b.requests<<" physical_ops="<<b.physicalAccesses<<" pte_reads="<<b.pteReads<<" cycles="<<b.cycles<<"\n";return 0;
}catch(const std::exception& e){std::cerr<<"GUEST_DATA_ADAPTER_FAIL "<<e.what()<<"\n";return 1;}}
