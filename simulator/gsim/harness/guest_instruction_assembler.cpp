#include "GuestInstructionAssemblerGsim.h"
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
struct InstructionCase {
    Case c;
    std::map<uint64_t,uint16_t> code;
    uint64_t owner=0xfedcba9876543210ULL,firstPa=0,secondPa=0,faultAddress=0,gpa=0,busErrorPa=~uint64_t(0);
    uint32_t instruction=0;
    unsigned bytes=2,parcels=1,cancel=0,pmaDenyParcel=0;
    bool compressed=false,unsupported=false,error=false,pf=false,gpf=false,implicit=false;
};
static InstructionCase instruction(uint32_t value,uint64_t pc=0x12345678) {
    InstructionCase t;t.c=nested();t.c.q.va=pc;t.c.name="instruction";t.instruction=value;
    t.compressed=(value&3)!=3;t.unsupported=(value&31)==31;
    t.bytes=(!t.compressed&&!t.unsupported)?4:2;t.parcels=t.bytes/2;
    t.c.memory[0x40102000+(((pc>>12)&511)*8)]=pte(0x80000000,V|X|A);
    t.firstPa=0xc0000000+(pc&4095);t.code[t.firstPa]=value&65535;
    if(t.bytes==4){uint64_t next=pc+2;
        if((pc>>12)!=(next>>12)){
            t.c.memory[0x40102000+(((next>>12)&511)*8)]=pte(0x80001000,V|X|A);
            mapG(t.c,0x80001000,0xd1234000,0,V|X|U|A);t.secondPa=0xd1234000;
        }else t.secondPa=t.firstPa+2;
        t.code[t.secondPa]=value>>16;
    }else t.instruction&=65535;
    return t;
}
struct Reply {
    uint64_t pc=0,tval=0,owner=0,gpa=0;uint32_t instruction=0;unsigned bytes=0,epoch=0;
    bool compressed=false,unsupported=false,error=false,pf=false,gpf=false,implicit=false,guest=false,cancelled=false;
    bool operator==(const Reply&) const = default;
};
class Bench {
    SGuestInstructionAssemblerGsim dut{};std::mt19937_64 random{0x415353454d424c59ULL};
public:
    uint64_t cycles=0,instructions=0,parcels=0,pteReads=0,physicalReads=0;
    Bench(){std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();dut.set_reset(1);dut.step();dut.set_reset(0);dut.step();}
    void check(bool yes,const std::string& what){if(!yes)throw std::runtime_error(what);}
    Reply observe(){Reply r;r.pc=dut.get_io$$response$$bits$$pc();r.tval=dut.get_io$$response$$bits$$faultAddress();
        r.owner=dut.get_io$$response$$bits$$owner();r.instruction=dut.get_io$$response$$bits$$instruction();
        r.bytes=dut.get_io$$response$$bits$$bytes();r.epoch=dut.get_io$$response$$bits$$epoch();
        r.compressed=dut.get_io$$response$$bits$$compressed();r.unsupported=dut.get_io$$response$$bits$$unsupportedLength();
        r.error=dut.get_io$$response$$bits$$error();r.pf=dut.get_io$$response$$bits$$pageFault();
        r.gpf=dut.get_io$$response$$bits$$guestFault$$guestPageFault();r.implicit=dut.get_io$$response$$bits$$guestFault$$implicitPte();
        r.guest=dut.get_io$$response$$bits$$guestFault$$guestAddress();r.gpa=dut.get_io$$response$$bits$$guestFault$$guestPhysicalAddress();
        r.cancelled=dut.get_io$$response$$bits$$cancelled();return r;}
    void run(const InstructionCase& t){
        const auto& q=t.c.q;bool accepted=false,ptePending=false,physicalPending=false,heldPhysical=false,heldParcel=false,heldReply=false,cancelSent=false;
        unsigned parcelCount=0,physicalCount=0,pteDelay=0,physicalDelay=0,replyStalls=0;
        uint64_t pteData=0,previousPhysical=0,previousParcel=0;bool pteError=false,physicalError=false;uint16_t physicalData=0;Reply previous{};
        for(unsigned cycle=0;cycle<2500;cycle++){
            bool cancel=!cancelSent&&((t.cancel==1&&parcelCount==1&&ptePending)||(t.cancel==5&&parcelCount==2&&ptePending)||
                (t.cancel==2&&parcelCount==1&&heldPhysical)||(t.cancel==6&&parcelCount==2&&heldPhysical)||
                (t.cancel==3&&parcelCount==1&&physicalPending)||(t.cancel==7&&parcelCount==2&&physicalPending)||
                (t.cancel==4&&heldReply)||(t.cancel==9&&parcelCount==0&&heldParcel)||(t.cancel==10&&parcelCount==1&&heldParcel));
            if(cancel)cancelSent=true;
            bool parcelStall=random()%4==0;
            if(!cancelSent&&((t.cancel==9&&parcelCount==0)||(t.cancel==10&&parcelCount==1)))parcelStall=true;
            dut.set_io$$parcelStall(parcelStall);dut.set_io$$cancel(cancel);dut.set_io$$request$$valid(!accepted);
            uint64_t noise=accepted?random():0;
            dut.set_io$$request$$bits$$pc(q.va^noise);dut.set_io$$request$$bits$$owner(t.owner^noise);
            dut.set_io$$request$$bits$$context$$virtualAddress(noise);dut.set_io$$request$$bits$$context$$vsatp(q.vsatp^noise);
            dut.set_io$$request$$bits$$context$$hgatp(q.hgatp^noise);dut.set_io$$request$$bits$$context$$virtualized(q.guest^(accepted&&(noise&1)));
            dut.set_io$$request$$bits$$context$$effectivePrivilege(accepted?(noise&3):q.privilege);
            dut.set_io$$request$$bits$$context$$access(3);dut.set_io$$request$$bits$$context$$size(0);dut.set_io$$request$$bits$$context$$forceExecute(1);
            dut.set_io$$request$$bits$$context$$vsSum(q.sum^(accepted&&(noise&1)));dut.set_io$$request$$bits$$context$$vsMxr(q.vmxr^(accepted&&(noise&1)));
            dut.set_io$$request$$bits$$context$$hsMxr(q.hmxr^(accepted&&(noise&1)));dut.set_io$$request$$bits$$context$$epoch(q.epoch^(noise&255));
            dut.set_io$$pmpTop(t.c.pmpTop);dut.set_io$$pmpPermission(t.c.permission);
            dut.set_io$$pmaDenied(t.pmaDenyParcel&&parcelCount==t.pmaDenyParcel);
            bool pteReady=random()%4!=0,pteValid=ptePending&&pteDelay==0;
            dut.set_io$$memory$$request$$ready(pteReady);dut.set_io$$memory$$response$$valid(pteValid);
            dut.set_io$$memory$$response$$bits$$data(pteData);dut.set_io$$memory$$response$$bits$$error(pteError);
            bool physicalReady=random()%4!=0;
            if(!cancelSent&&((t.cancel==2&&parcelCount==1)||(t.cancel==6&&parcelCount==2)))physicalReady=false;
            bool physicalValid=physicalPending&&physicalDelay==0;
            dut.set_io$$physical$$request$$ready(physicalReady);dut.set_io$$physical$$response$$valid(physicalValid);
            dut.set_io$$physical$$response$$bits(physicalData);dut.set_io$$physical$$responseError(physicalError);dut.set_io$$physical$$responsePageFault(0);
            bool replyReady=replyStalls>=5&&random()%3!=0;dut.set_io$$response$$ready(replyReady);
            dut.step();cycles++;
            if(!accepted&&dut.get_io$$request$$ready()){accepted=true;instructions++;}
            bool parcelOffer=dut.get_io$$parcelOffer(),parcelAccepted=dut.get_io$$parcelAccepted();auto parcelAddr=dut.get_io$$parcelAddress();
            if(heldParcel)check(parcelOffer&&parcelAddr==previousParcel&&dut.get_io$$parcelEpoch()==q.epoch,t.c.name+": held parcel owner changed");
            heldParcel=parcelOffer&&!parcelAccepted;previousParcel=parcelAddr;
            if(parcelAccepted){check(parcelAddr==q.va+parcelCount*2&&dut.get_io$$parcelEpoch()==q.epoch,t.c.name+": parcel sequence/context changed");parcelCount++;parcels++;
                check(parcelCount<=2,t.c.name+": fetched more than two parcels");}
            if(ptePending&&pteDelay)pteDelay--;
            if(pteValid&&dut.get_io$$memory$$response$$ready())ptePending=false;
            if(dut.get_io$$memory$$request$$valid()&&pteReady){auto address=dut.get_io$$memory$$request$$bits();
                check(!ptePending&&t.c.memory.count(address),t.c.name+": PTE address/credit "+std::to_string(address));
                pteData=t.c.memory.at(address);pteError=address==t.c.errorAddress;ptePending=true;pteDelay=1+random()%3;pteReads++;}
            bool offer=dut.get_io$$physical$$request$$valid();auto pa=dut.get_io$$physical$$request$$bits();
            if(heldPhysical)check(offer&&pa==previousPhysical,t.c.name+": held physical parcel changed");
            heldPhysical=offer&&!physicalReady;previousPhysical=pa;
            if(physicalPending&&physicalDelay)physicalDelay--;
            if(physicalValid&&dut.get_io$$physical$$response$$ready())physicalPending=false;
            if(offer&&physicalReady){check(!physicalPending&&t.code.count(pa),t.c.name+": unexpected physical parcel "+std::to_string(pa));
                physicalData=t.code.at(pa);physicalError=pa==t.busErrorPa;physicalPending=true;physicalDelay=1+random()%4;physicalCount++;physicalReads++;}
            bool valid=dut.get_io$$response$$valid();
            if(heldReply)check(valid&&observe()==previous,t.c.name+": held instruction/fault owner changed");
            if(valid){replyStalls++;previous=observe();heldReply=true;
                if(replyReady){auto r=previous;check(!physicalPending&&!ptePending,t.c.name+": response before child drain");
                    check(r.pc==q.va&&r.owner==t.owner&&r.epoch==q.epoch,t.c.name+": architectural EPC/owner/epoch changed");
                    bool cancelled=t.cancel&&t.cancel!=4;check(r.cancelled==cancelled,t.c.name+": cancellation disposition");
                    if(cancelled){check(!r.error&&!r.pf&&!r.gpf&&!r.implicit&&!r.unsupported&&r.gpa==0,t.c.name+": cancelled fault escaped");
                        unsigned expectedParcels=(t.cancel>=5&&t.cancel!=9)?2:1;
                        unsigned expectedPhysical=(t.cancel==1||t.cancel==9)?0:((t.cancel==6||t.cancel==7)?2:1);
                        check(parcelCount==expectedParcels&&physicalCount==expectedPhysical,t.c.name+": cancellation child count");}
                    else {check(r.error==t.error&&r.pf==t.pf&&r.gpf==t.gpf&&r.implicit==t.implicit&&r.gpa==t.gpa&&r.guest==q.guest,t.c.name+": precise fault class/GPA");
                        check(parcelCount==t.parcels,t.c.name+": unexpected parcel count");
                        if(t.error){check(r.tval==t.faultAddress,t.c.name+": exact faulting parcel tval");
                            if(t.parcels==2)check(r.bytes==4&&!r.compressed&&r.instruction==(t.instruction&65535),t.c.name+": second fault lost first parcel");}
                        else check(r.instruction==t.instruction&&r.compressed==t.compressed&&r.unsupported==t.unsupported&&r.bytes==t.bytes,
                            t.c.name+": little-endian C/32 instruction assembly");}
                    return;}
            }
        }
        throw std::runtime_error(t.c.name+": timeout");
    }
};
int main(){try{
    Bench b;
    // A range of raw C encodings and real 32-bit encodings, at both word alignments.
    for(unsigned n=0;n<128;n++){
        uint16_t half=uint16_t((n<<5)|1);auto t=instruction(0xbeef0000|half,0x12345600+2*(n%32));
        t.c.name="C single parcel";t.c.q.epoch=n;t.owner+=n;b.run(t);
        t=instruction((n<<20)|0x00000093,0x12345600+2*(n%32));t.c.name="32-bit cross-word";t.c.q.epoch=255-n;t.owner+=n;b.run(t);
    }
    for(uint16_t prefix:{0x001f,0x003f,0x007f,0xffff}){auto t=instruction(prefix,0x12345ffe);t.c.name="unsupported long encoding no tail";b.run(t);}
    {auto t=instruction(0x0001,0x12345ffe);t.c.name="C at page end needs no next page";b.run(t);}
    {auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="32-bit cross-page noncontiguous SPA";b.run(t);}
    {auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="second VS page fault EPC and tval";
        t.c.memory[0x40102000+(((t.c.q.va+2)>>12&511)*8)]=0;t.error=true;t.pf=true;t.faultAddress=t.c.q.va+2;b.run(t);}
    {auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="second final guest fault EPC GPA tval";
        t.c.memory[0x407008]=0;t.error=true;t.gpf=true;t.gpa=0x80001000;t.faultAddress=t.c.q.va+2;b.run(t);}
    {auto t=instruction(0x05aa0093,0x123ffffe);t.c.name="second implicit PTE guest fault";
        // Preserve the first VS hierarchy; the second 2-MiB region points at a guest
        // page-table page whose G L1 entry is invalid, independently of instruction X.
        t.c.memory[0x40101000+((((t.c.q.va+2)>>21)&511)*8)]=pte(0x300000,V);
        for(unsigned page=0;page<3;page++)mapG(t.c,0x100000+page*0x1000,0x40100000+page*0x1000,0,V|R|U|A);
        t.c.memory[0x400008]=0;t.error=true;t.gpf=true;t.implicit=true;t.gpa=0x300000;t.faultAddress=t.c.q.va+2;b.run(t);}
    {auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="second physical bus fault";t.busErrorPa=t.secondPa;t.error=true;t.faultAddress=t.c.q.va+2;b.run(t);}
    {auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="second execute PMA fault";t.pmaDenyParcel=2;t.error=true;t.faultAddress=t.c.q.va+2;b.run(t);}
    {auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="second execute PMP fault";t.c.pmpTop=t.secondPa>>2;t.error=true;t.faultAddress=t.c.q.va+2;b.run(t);}
    {auto t=instruction(0x05aa0093);t.c.name="first parcel guest fault";t.c.memory[0x200000]=0;t.error=true;t.gpf=true;t.implicit=true;
        t.gpa=0x100000;t.faultAddress=t.c.q.va;t.parcels=1;b.run(t);}
    for(unsigned cancel:{1,2,3,4,5,6,7,9,10}){auto t=instruction(0x05aa0093,0x12345ffe);t.c.name="first/second parcel cancellation";t.cancel=cancel;b.run(t);}
    // Alternate ASID/root-like context inputs after acceptance must never affect the second parcel.
    {auto t=instruction(0xa55a0013,0x12345ffe);t.c.name="new owner after cancellation";t.owner=0x123456789abcdef0;t.c.q.epoch=231;b.run(t);}
    std::cout<<"GUEST_INSTRUCTION_ASSEMBLER_PASS instructions="<<b.instructions<<" parcels="<<b.parcels<<" physical_reads="<<b.physicalReads<<" pte_reads="<<b.pteReads<<" cycles="<<b.cycles<<"\n";return 0;
}catch(const std::exception& e){std::cerr<<"GUEST_INSTRUCTION_ASSEMBLER_FAIL "<<e.what()<<"\n";return 1;}}
