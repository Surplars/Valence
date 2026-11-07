#include "GuestTranslationGsim.h"
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
static Response expected(const Case& c) {
    Response r;r.va=c.q.va;r.guest=c.q.guest;r.epoch=c.q.epoch;return r;
}
class Bench {
    SGuestTranslationGsim dut{};
    std::mt19937_64 random{0x535633395834ULL};
public:
    uint64_t cycles=0,requests=0,reads=0;
    Bench(){std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();dut.set_reset(1);dut.step();dut.set_reset(0);dut.step();}
    Response observe() {
        Response r;r.pa=dut.get_io$$response$$bits$$physicalAddress();r.va=dut.get_io$$response$$bits$$virtualAddress();
        r.gpa=dut.get_io$$response$$bits$$guestPhysicalAddress();r.level=dut.get_io$$response$$bits$$level();
        r.epoch=dut.get_io$$response$$bits$$epoch();r.pf=dut.get_io$$response$$bits$$pageFault();
        r.gpf=dut.get_io$$response$$bits$$guestPageFault();r.af=dut.get_io$$response$$bits$$accessFault();
        r.implicit=dut.get_io$$response$$bits$$implicitPte();r.guest=dut.get_io$$response$$bits$$guestAddress();
        r.cancelled=dut.get_io$$response$$bits$$cancelled();r.global=dut.get_io$$response$$bits$$global();
        return r;
    }
    void check(bool condition,const std::string& what){if(!condition)throw std::runtime_error(what);}
    Response run(const Case& c,int cancelCycle=-1,int cancelAtRead=-1,bool cancelOnOffer=false,bool cancelOnReply=false) {
        bool accepted=false,pending=false,heldOffer=false,heldReply=false,cancelled=false;
        uint64_t responseData=0,heldAddress=0;bool responseError=false;unsigned delay=0,replyStalls=0;
        Response held{};unsigned count=0;
        for(unsigned t=0;t<1000;t++){
            bool cancel=(cancelCycle>=0&&int(t)==cancelCycle)||
                (cancelAtRead>=0&&int(count)==cancelAtRead&&pending)||
                (cancelOnOffer&&heldOffer)||(cancelOnReply&&heldReply);
            if(cancel){cancelled=true;cancelCycle=-1;cancelAtRead=-1;cancelOnOffer=false;cancelOnReply=false;}
            dut.set_io$$cancel(cancel);dut.set_io$$request$$valid(!accepted);
            // Scramble the non-owned live inputs as soon as request acceptance is past.
            const Request& q=c.q;uint64_t scramble=accepted?random():0;
            dut.set_io$$request$$bits$$virtualAddress(q.va^scramble);
            dut.set_io$$request$$bits$$vsatp(q.vsatp^scramble);dut.set_io$$request$$bits$$hgatp(q.hgatp^scramble);
            dut.set_io$$request$$bits$$virtualized(q.guest^(accepted&&(scramble&1)));
            dut.set_io$$request$$bits$$effectivePrivilege(accepted?(scramble&3):q.privilege);
            dut.set_io$$request$$bits$$access(accepted?(scramble&3):q.access);
            dut.set_io$$request$$bits$$size(accepted?(scramble&7):q.size);
            dut.set_io$$request$$bits$$vsSum(q.sum^(accepted&&(scramble&1)));
            dut.set_io$$request$$bits$$vsMxr(q.vmxr^(accepted&&(scramble&1)));
            dut.set_io$$request$$bits$$hsMxr(q.hmxr^(accepted&&(scramble&1)));
            dut.set_io$$request$$bits$$forceExecute(q.hlvx^(accepted&&(scramble&1)));
            dut.set_io$$request$$bits$$epoch(q.epoch^(scramble&255));
            dut.set_io$$pmpTop(c.pmpTop);dut.set_io$$pmpPermission(c.permission);
            bool memoryReady=(random()%4)!=0;
            if(cancelOnOffer&&!heldOffer)memoryReady=false;
            bool memoryValid=pending&&delay==0;
            dut.set_io$$memory$$request$$ready(memoryReady);
            dut.set_io$$memory$$response$$valid(memoryValid);
            dut.set_io$$memory$$response$$bits$$data(responseData);
            dut.set_io$$memory$$response$$bits$$error(responseError);
            bool replyReady=replyStalls>=4&&(random()%4)!=0;
            dut.set_io$$response$$ready(replyReady);
            dut.step();cycles++;
            if(!accepted&&dut.get_io$$request$$ready()){accepted=true;requests++;}
            bool req=dut.get_io$$memory$$request$$valid();uint64_t addr=dut.get_io$$memory$$request$$bits();
            if(heldOffer)check(req&&addr==heldAddress,c.name+": held physical offer changed/cancelled");
            bool priorOffer=heldOffer;heldOffer=req&&!memoryReady;heldAddress=addr;
            if(pending&&delay)delay--;
            if(memoryValid&&dut.get_io$$memory$$response$$ready())pending=false;
            if(req&&memoryReady){
                check(!pending,c.name+": two outstanding PTE reads");
                check(!cancelled||priorOffer||cancel,c.name+": new PTE read after cancellation drain");
                check(c.memory.count(addr)!=0,c.name+": unexpected physical PTE address "+std::to_string(addr));
                responseData=c.memory.at(addr);responseError=addr==c.errorAddress;pending=true;delay=1+random()%4;count++;reads++;
            }
            bool valid=dut.get_io$$response$$valid();
            if(heldReply)check(valid&&observe()==held,c.name+": held response changed");
            if(valid){replyStalls++;held=observe();heldReply=true;
                if(replyReady){check(accepted&&!pending,c.name+": completed without drained owner");return held;}}
        }
        throw std::runtime_error(c.name+": timeout");
    }
    void verify(const Case& c,Response e){auto r=run(c);check(r.va==e.va&&r.epoch==e.epoch&&r.guest==e.guest,c.name+": context changed");
        check(r.pf==e.pf&&r.gpf==e.gpf&&r.af==e.af&&r.implicit==e.implicit&&!r.cancelled,c.name+": fault class");
        if(!r.pf&&!r.gpf&&!r.af)check(r.pa==e.pa,c.name+": physical result");
        if(r.gpf)check(r.gpa==e.gpa,c.name+": guest fault GPA");}
};
static bool permitted(unsigned flags,unsigned access,bool mxr){
    if(!(flags&V)||(flags&W)&&!(flags&R))return false;
    if(!(flags&A))return false;
    if(access==0)return (flags&R)||(mxr&&(flags&X));
    if(access==2)return flags&X;
    return (flags&(R|W|D))==(R|W|D);
}
int main(){try{
    Bench b;Case c;c.name="guest bare";c.q.va=0x4567;c.q.size=0;auto e=expected(c);e.pa=c.q.va;b.verify(c,e);
    c.q.guest=false;c.q.privilege=3;c.q.vsatp=MODE|0xff;c.q.hgatp=MODE|0x200;c.name="host M bypass";e=expected(c);e.pa=c.q.va;b.verify(c,e);
    for(unsigned quadrant=0;quadrant<4;quadrant++)for(unsigned level=0;level<3;level++) {
        c={};c.name="Sv39x4 quadrant "+std::to_string(quadrant)+" level "+std::to_string(level);
        c.q.va=(uint64_t(quadrant)<<39)|0x12345678;c.q.size=0;c.q.hgatp=MODE|0x200;
        mapG(c,c.q.va,0xc0000000,level,V|R|W|X|U|A|D);e=expected(c);e.pa=0xc0000000+leafOffset(c.q.va,level);b.verify(c,e);
        b.check(b.run(c).level==level,"G leaf level");
    }
    for(unsigned vl=0;vl<3;vl++)for(unsigned gl=0;gl<3;gl++){
        c=nested(vl,gl);c.name="nested levels";e=expected(c);e.pa=0xc0000000+leafOffset(0x80000000+leafOffset(c.q.va,vl),gl);b.verify(c,e);
        b.check(b.run(c).level==std::min(vl,gl),"combined leaf level");
    }
    // Exhaustive independent architectural permission oracle at the final G leaf.
    for(unsigned f=0;f<256;f++)for(unsigned access=0;access<4;access++)for(unsigned mxr=0;mxr<2;mxr++) {
        if(!(f&(R|X)))continue; // Non-leaf checks have dedicated structural cases below.
        c=nested(0,0,V|R|W|X|A|D,f);c.name="G permission "+std::to_string(f);c.q.access=access;c.q.hmxr=mxr;
        e=expected(c);e.pa=0xc0000678;
        if(!permitted(f,access,mxr)||!(f&U)){e.gpf=true;e.gpa=0x80000678;}
        b.verify(c,e);
    }
    for(unsigned f=0;f<256;f++)for(unsigned access=0;access<4;access++)for(unsigned privilege=0;privilege<2;privilege++)
    for(unsigned sum=0;sum<2;sum++)for(unsigned mxr=0;mxr<2;mxr++) {
        if(!(f&(R|X)))continue;
        c=nested(0,0,f);c.name="VS permission "+std::to_string(f);c.q.access=access;c.q.privilege=privilege;c.q.sum=sum;c.q.vmxr=mxr;
        bool user=privilege==0?(f&U):(access==2?!(f&U):(!(f&U)||sum));
        e=expected(c);e.pa=0xc0000678;if(!permitted(f,access,mxr)||!user)e.pf=true;b.verify(c,e);
    }
    // VS MXR must not grant G execute-only pages, while HS MXR covers both stages.
    c=nested(0,0,V|X|A,V|X|U|A);c.name="MXR separation";c.q.vmxr=true;e=expected(c);e.gpf=true;e.gpa=0x80000678;b.verify(c,e);
    c.q.hmxr=true;e=expected(c);e.pa=0xc0000678;b.verify(c,e);
    // The implicit PTE access is a LOAD even when the original is a STORE or FETCH.
    for(unsigned access=0;access<4;access++){
        c=nested();c.q.access=access;c.name="implicit load classification";e=expected(c);e.pa=0xc0000678;b.verify(c,e);
        c.memory[0x200000]=pte(0x40000000,V|R|A);e=expected(c);e.gpf=true;e.implicit=true;e.gpa=0x100000;b.verify(c,e);
    }
    c=nested();c.name="VS PTE bus error";c.errorAddress=0x40100000;e=expected(c);e.af=true;b.verify(c,e);
    c=nested();c.name="G PTE bus error";c.errorAddress=0x200000;e=expected(c);e.af=true;b.verify(c,e);
    c=nested();c.name="PMP deny G PTE";c.pmpTop=0x200000>>2;e=expected(c);e.af=true;b.verify(c,e);
    c=nested();c.name="PMP deny translated VS PTE";c.pmpTop=0x40100000>>2;e=expected(c);e.af=true;b.verify(c,e);
    c=nested();c.name="PMP deny final SPA";c.pmpTop=0xc0000000>>2;e=expected(c);e.af=true;b.verify(c,e);
    c=nested();c.name="GPA out of range final";c.q.vsatp=0;c.q.va=uint64_t(1)<<41;e=expected(c);e.gpf=true;e.gpa=c.q.va;b.verify(c,e);
    c=nested();c.name="GPA out of range implicit";c.q.vsatp=MODE|(uint64_t(1)<<29);e=expected(c);e.gpf=true;e.implicit=true;e.gpa=uint64_t(1)<<41;b.verify(c,e);
    c=nested();c.name="noncanonical VS";c.q.va=uint64_t(1)<<39;e=expected(c);e.pf=true;b.verify(c,e);
    c=nested();c.name="unaligned x4 root";c.q.hgatp|=1;e=expected(c);e.gpf=true;e.implicit=true;e.gpa=0x100000;b.verify(c,e);
    // Structural PTE faults: reserved, malformed nonleaf, missing A, misaligned superpage.
    for(uint64_t flags:{V|W,V|R,V|A,V|U,V|D,V|(uint64_t(1)<<54)}){
        c=nested();c.name="invalid G root";c.memory[0x200000]=pte(0x40000000,flags);e=expected(c);e.gpf=true;e.implicit=true;e.gpa=0x100000;b.verify(c,e);
    }
    c=nested();c.name="misaligned G superpage";c.memory[0x200000]=pte(0x40001000,V|R|U|A);e=expected(c);e.gpf=true;e.implicit=true;e.gpa=0x100000;b.verify(c,e);
    c=nested(2);c.name="misaligned VS superpage";c.memory[0x40100000]=pte(0x80001000,V|R|A);e=expected(c);e.pf=true;b.verify(c,e);
    // HLVX requires X in both stages and BOTH physical read and execute permission.
    for(unsigned permissions=0;permissions<8;permissions++){
        c=nested(0,0,V|X|A,V|X|U|A);c.name="HLVX physical RX";c.q.hlvx=true;c.permission=permissions;
        e=expected(c);e.pa=0xc0000678;if((permissions&5)!=5)e.af=true;b.verify(c,e);
    }
    c=nested(0,0,V|R|A,V|R|U|A);c.name="HLVX rejects nonexecute";c.q.hlvx=true;e=expected(c);e.pf=true;b.verify(c,e);
    c=nested();c.name="full fifteen-read nested walk";
    for(unsigned page=0;page<3;page++)mapG(c,0x100000+page*0x1000,0x40100000+page*0x1000,0,V|R|U|A);
    e=expected(c);e.pa=0xc0000678;auto beforeReads=b.reads;b.verify(c,e);
    b.check(b.reads-beforeReads==15,"nested full physical walk depth");
    c=nested();c.name="VS nonleaf global propagates";c.memory[0x40100000]|=G;
    b.check(b.run(c).global,"VS global propagation");
    c=nested();c.name="G global ignored";c.memory[0x200000]|=G;
    b.check(!b.run(c).global,"G global must be ignored");
    c=nested();c.name="alternate captured hgatp root";c.q.hgatp=MODE|0x300;c.q.epoch=127;
    c.memory[0x300000]=c.memory.at(0x200000);c.memory[0x300010]=c.memory.at(0x200010);
    c.memory.erase(0x200000);c.memory.erase(0x200010);e=expected(c);e.pa=0xc0000678;b.verify(c,e);
    // Cancellation before issue, after acceptance, and on a backpressured offer.
    for(int t=1;t<14;t++){c=nested();c.name="cancel cycle";auto r=b.run(c,t);b.check(r.cancelled&&r.epoch==c.q.epoch&&!r.pf&&!r.gpf&&!r.af,"cancel tombstone");}
    for(int n=1;n<=9;n++){c=nested();c.name="cancel PTE owner";auto r=b.run(c,-1,n);b.check(r.cancelled,"cancel read drain");}
    c=nested();c.name="cancel held offer";b.check(b.run(c,-1,-1,true).cancelled,"held offer cancellation");
    c=nested();c.name="cancel held response";b.check(!b.run(c,-1,-1,false,true).cancelled,"held response must remain immutable");
    // A following context with another root/epoch must have no stale result or translation cache hit.
    c=nested();c.name="fresh epoch after kill";c.q.epoch=231;e=expected(c);e.pa=0xc0000678;b.verify(c,e);
    std::cout<<"GUEST_TRANSLATION_PASS requests="<<b.requests<<" physical_reads="<<b.reads<<" cycles="<<b.cycles<<"\n";
    return 0;
}catch(const std::exception& e){std::cerr<<"GUEST_TRANSLATION_FAIL "<<e.what()<<"\n";return 1;}}
