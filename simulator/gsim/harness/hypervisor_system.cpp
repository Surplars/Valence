#include "HypervisorSystemGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <type_traits>
struct Result {uint64_t data,cause,tval,next;bool exception,redirect;};
struct Bench {
    SHypervisorSystemGsim d;uint64_t cycles=0,checks=0,commands=0;
    Bench(){static_assert(std::is_trivially_copyable_v<SHypervisorSystemGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
        d.set_reset(1);tick();tick();d.set_reset(0);tick();}
    void tick(){d.step();cycles++;}
    void check(uint64_t got,uint64_t expected,const char* label){checks++;if(got!=expected){std::cerr<<label<<" cycle="<<cycles<<" got="<<std::hex<<got<<" expected="<<expected<<std::dec<<'\n';throw std::runtime_error(label);}}
    Result result(){return{d.get_io$$data(),d.get_io$$cause(),d.get_io$$tval(),d.get_io$$nextPc(),bool(d.get_io$$exception()),bool(d.get_io$$redirect())};}
    Result cmd(uint32_t instruction,uint64_t operand=0,uint64_t pc=0x80000000,unsigned stall=0){
        d.set_io$$completeReady(0);d.set_io$$instruction(instruction);d.set_io$$operand(operand);d.set_io$$pc(pc);
        d.set_io$$start(1);unsigned budget=100;
        do{tick();if(!budget--)throw std::runtime_error("start timeout");}while(!d.get_io$$ready());
        d.set_io$$start(0);budget=100;
        do{tick();if(!budget--)throw std::runtime_error("completion timeout");}while(!d.get_io$$complete());
        auto r=result();
        for(unsigned i=0;i<stall;i++){tick();auto held=result();check(held.data,r.data,"held CSR data");check(held.next,r.next,"held nextPC");check(held.cause,r.cause,"held cause");check(d.get_io$$ready(),0,"capacity one during completion stall");}
        d.set_io$$completeReady(1);tick();d.set_io$$completeReady(0);tick();commands++;return r;
    }
    uint64_t read(unsigned csr){auto r=cmd((csr<<20)|(2<<12)|(1<<7)|0x73);check(r.exception,0,"legal CSR read");return r.data;}
    uint64_t write(unsigned csr,uint64_t value,unsigned stall=0){auto r=cmd((csr<<20)|(1<<15)|(1<<12)|(1<<7)|0x73,value,0x80000000,stall);check(r.exception,0,"legal CSR write");return r.data;}
    void fault(uint32_t instruction,unsigned cause){auto r=cmd(instruction);check(r.exception,1,"expected instruction fault");check(r.cause,cause,"precise instruction cause");check(r.tval,instruction,"fault tval instruction");}
    void trap(uint64_t cause,uint64_t pc,uint64_t tval,uint64_t target){
        check(d.get_io$$trapReady(),1,"trap admission");d.set_io$$trapPc(pc);d.set_io$$trapCause(cause);d.set_io$$trapTval(tval);d.set_io$$trap(1);
        tick();check(d.get_io$$trapTarget(),target,"trap vector");d.set_io$$trap(0);tick();
    }
    void mode(unsigned privilege,bool v){tick();check(d.get_io$$privilege(),privilege,"privilege");check(d.get_io$$virtualized(),v,"V state");}
    void mret(uint64_t pc){auto r=cmd(0x30200073);check(r.exception,0,"MRET legal");check(r.redirect,1,"MRET redirect");check(r.next,pc,"MRET pc");}
    void sret(uint64_t pc){auto r=cmd(0x10200073);check(r.exception,0,"SRET legal");check(r.redirect,1,"SRET redirect");check(r.next,pc,"SRET pc");}
};
static uint32_t rd(unsigned csr){return(csr<<20)|(2<<12)|(1<<7)|0x73;}
int main(){try{
    constexpr uint64_t irq=1ULL<<63,mpv=1ULL<<39;Bench b;
    b.check(b.read(0x301)&(1<<7),0,"experimental H does not advertise ISA support");
    b.check(b.read(0x303)&0x1444,0x1444,"H interrupts forced M delegation");
    b.write(0x100,(1<<18)|2);b.write(0x200,(1<<19)|2);
    b.write(0x140,0x1234);b.write(0x240,0x5678);b.write(0x105,0x80000101);b.write(0x205,0x80000201);
    b.write(0x305,0x80000301);b.write(0x302,0xffffff);b.write(0x602,0xffffff);
    b.check(b.read(0x602),0xcb1ff,"hedeleg excludes VS/HS ecalls and guest faults");
    b.write(0x303,0x200);b.write(0x304,0x1644);b.write(0x603,0x444);
    b.write(0x607,0xffff);b.check(b.read(0x607),14,"hgeie implemented mask");b.write(0x607,0);
    b.write(0x600,1<<12);b.write(0x341,0x80001003);b.write(0x300,mpv|(1<<11)|2);
    b.mret(0x80001000);b.mode(1,true);
    b.check(b.read(0x140),0x5678,"VS scratch shadow");b.write(0x140,0xabcd,7);
    b.check(b.read(0x100)&((1<<18)|(1<<19)|2),(1<<19)|2,"VS sstatus shadow");
    b.fault(rd(0x600),22);b.fault(rd(0x200),22);b.fault(rd(0x300),2);b.fault(rd(0x6ff),2);
    b.d.set_io$$guestExternal(1);b.tick();b.check(b.d.get_io$$interruptPending(),1,"guest IRQ pending");b.check(b.d.get_io$$interruptCause(),10,"raw VSEI trap cause");
    b.trap(irq|10,0x80001004,0,0x80000224);b.mode(1,true);
    b.check(b.read(0x142),irq|9,"VS interrupt cause translation");b.check(b.read(0x141),0x80001004,"VS EPC");
    b.d.set_io$$guestExternal(0);b.sret(0x80001004);b.mode(1,true);
    b.d.set_io$$hostExternal(1);b.tick();b.check(b.d.get_io$$interruptPending(),1,"HS interrupts preempt VS regardless HS SIE");
    b.trap(irq|9,0x80001008,0,0x80000124);b.d.set_io$$hostExternal(0);b.mode(1,false);
    b.check(b.read(0x140),0x1234,"host scratch preserved");b.check(b.read(0x240),0xabcd,"guest scratch preserved");
    b.check(b.read(0x600)&0x180,0x180,"HS trap records SPV and SPVP");b.sret(0x80001008);b.mode(1,true);
    auto ecall=b.cmd(0x00000073);b.check(ecall.exception,1,"VS ECALL");b.check(ecall.cause,10,"VS ECALL cause");
    b.trap(10,0x8000100c,0,0x80000100);b.mode(1,false);b.check(b.read(0x142),10,"VS ECALL cannot delegate back VS");
    // Guest IMSIC selection goes through the real system-unit CSR decoder and real file banks.
    b.write(0x250,0x70);b.write(0x251,1);b.write(0x250,0xc0);b.write(0x251,16);b.write(0x250,0x80);b.write(0x251,16);
    b.check(b.read(0x25c),0x40004,"VS IMSIC file1 identity");b.write(0x600,2<<12);b.check(b.read(0x25c),0,"VS IMSIC file2 isolation");
    b.write(0x600,1<<12);b.check(b.write(0x25c,0),0x40004,"claim real guest file");b.check(b.read(0x25c),0,"claim cleared real guest file");
    b.write(0x600,0);b.fault(rd(0x25c),2); // Zero selection HS access is illegal.
    b.write(0x600,(1<<12)|(1<<7)|(1<<22));b.sret(0x8000100c);b.mode(1,true);b.fault(0x10200073,22);
    b.trap(22,0x80001010,0x10200073,0x80000100);b.write(0x600,(1<<12)|(1<<7)|(1<<20));b.sret(0x80001010);
    b.fault(rd(0x180),22);b.fault(0x12000073,22);
    b.trap(22,0x80001014,0x12000073,0x80000100);b.write(0x600,(1<<12)|(1<<7)|(1<<21));b.sret(0x80001014);b.fault(0x10500073,22);
    b.trap(22,0x80001018,0x10500073,0x80000100);b.write(0x600,(1<<12)|(1<<7));
    b.write(0x241,0x80002000);b.write(0x200,0);b.sret(0x80001018);b.mode(1,true);b.sret(0x80002000);b.mode(0,true);
    ecall=b.cmd(0x00000073);b.check(ecall.cause,8,"VU ECALL cause");b.trap(8,0x80002000,0,0x80000200);b.mode(1,true);
    b.check(b.read(0x142),8,"VU ECALL delegated VS");b.check(b.read(0x100)&0x100,0,"VU trap saves VS SPP zero");
    // Machine trap retains virtualization state for MRET and precise guest-address indication.
    b.trap(11,0x80002004,0,0x80000300);b.mode(3,false);b.check(b.read(0x300)&mpv,mpv,"M trap MPV");
    b.check(b.read(0x341),0x80002004,"M trap EPC");b.mret(0x80002004);b.mode(1,true);
    b.trap(16,0x80002008,0,0x80000300);b.mode(3,false);
    b.write(0x302,0);b.mret(0x80002008);b.trap(5,0x8000200c,0x123456,0x80000300);b.mode(3,false);
    b.check(b.read(0x300)&((1ULL<<39)|(1ULL<<38)),(1ULL<<39)|(1ULL<<38),"M trap MPV/GVA");b.check(b.read(0x34b),0,"non-guest-page mtval2 zero");
    b.write(0x306,2);b.write(0x606,2);b.write(0x605,7);b.d.set_io$$time(100);b.mret(0x8000200c);b.check(b.read(0xc01),107,"guest time offset");
    b.trap(16,0x80002010,0,0x80000300);b.write(0x606,0);b.mret(0x80002010);b.fault(rd(0xc01),22);
    b.trap(22,0x80002014,rd(0xc01),0x80000300);b.mode(3,false);
    b.write(0x64a,0x3000);b.check(b.read(0x64a),0x3000,"htinst retains hardware-supported pseudoinstruction");
    b.write(0x34a,0x3000);b.check(b.read(0x34a),0x3000,"mtinst retains hardware-supported pseudoinstruction");
    b.write(0x680,(8ULL<<60)|0x1237);b.check(b.read(0x680),(8ULL<<60)|0x1234,"hgatp root 16KiB alignment");
    b.write(0x680,(15ULL<<60)|0x5678);b.check(b.read(0x680),0,"unsupported hgatp mode is legalized not ignored");
    b.write(0x300,(1<<11)|(1<<20));b.write(0x341,0x80003000);b.mret(0x80003000);b.mode(1,false);
    b.fault(rd(0x680),2);b.fault(rd(0x180),2);b.check(b.read(0x280),0,"TVM does not prohibit direct vsatp");
    b.trap(16,0x80003004,0,0x80000300);b.write(0x300,mpv);b.write(0x606,2);b.write(0x106,0);b.mret(0x80003004);b.mode(0,true);
    b.fault(rd(0xc01),22);b.fault(0x10500073,22);
    b.trap(22,0x80003008,0x10500073,0x80000300);b.write(0x300,mpv|(1<<21));b.mret(0x80003008);b.mode(0,true);b.fault(0x10500073,2);
    b.trap(2,0x8000300c,0x10500073,0x80000300);b.write(0x300,mpv);b.write(0x106,2);b.write(0x606,0);b.mret(0x8000300c);b.fault(rd(0xc01),22);
    b.trap(22,0x80003010,rd(0xc01),0x80000300);b.write(0x300,mpv);b.write(0x606,2);b.mret(0x80003010);b.check(b.read(0xc01),107,"VU time requires both counters enabled");
    b.trap(16,0x80003014,0,0x80000300);b.write(0x300,0);b.write(0x303,0x200);b.write(0x304,0x222);b.write(0x344,2);b.d.set_io$$hostExternal(1);b.mret(0x80003014);b.mode(0,false);
    b.check(b.d.get_io$$interruptCause(),1,"M SSI outranks delegated HS SEI");
    b.trap(irq|1,0x80003018,0,0x80000304);b.write(0x344,32);b.write(0x300,0);b.mret(0x80003018);b.mode(0,false);
    b.check(b.d.get_io$$interruptCause(),5,"M STI outranks delegated HS SEI");
    {
        Bench a;
        a.write(0x304,0x222);a.write(0x309,0x222);
        a.check(a.read(0x308),0,"mvien RO0");a.check(a.read(0x309),0x222,"mvip software aliases");
        a.check(a.read(0x344)&0x222,0x222,"mvip aliases mip");
        a.check(a.read(0xfb0),0x90001,"mtopi not gated by MIE global");a.check(a.d.get_io$$interruptPending(),0,"global MIE blocks actual trap");
        a.write(0x303,0x222);a.check(a.read(0xfb0),0,"mtopi delegation exclusion");a.check(a.read(0xdb0),0x90001,"stopi ignores privilege/global SIE");
        a.write(0x309,0);a.d.set_io$$hostExternal(1);a.tick();
        auto rmw=a.cmd((0x344u<<20)|(1<<15)|(2<<12)|(1<<7)|0x73,2);
        a.check(rmw.data&0x200,0x200,"MIP read sees external SEIP");a.check(a.read(0x309)&0x200,0,"MIP RMW never copies external into software SEIP");
        a.d.set_io$$hostExternal(0);a.tick();a.check(a.read(0x344)&0x200,0,"external removal clears pending");
        a.write(0x30a,1ULL<<63);a.check(a.read(0x309)&32,0,"mvip STIP reads zero with STCE");a.write(0x309,32);a.write(0x30a,0);a.check(a.read(0x309)&32,0,"mvip STIP write ignored with STCE");
        for(unsigned sel=0x30;sel<=0x3e;sel+=2){a.write(0x350,sel);a.check(a.read(0x351),0,"machine priority register RO0");a.write(0x351,~0ULL);a.check(a.read(0x351),0,"priority remains RO0");}
        a.write(0x350,0x31);a.fault(rd(0x351),2);
        a.write(0x150,0x30);a.check(a.read(0x151),0,"supervisor priority register RO0");a.write(0x250,0x30);a.write(0x600,1<<12);a.fault(rd(0x251),2);
        a.write(0x609,0x40000100u|(33<<16)|7);a.check(a.read(0x609),0x40000100u|(33<<16)|7,"hvictl IID six-bit and priority storage");
        a.check(a.read(0xeb0),(33<<16)|7,"VTI nomination independent of pending and enable");
        a.write(0x205,0x80000201);a.write(0x305,0x80000301);a.write(0x200,2);a.write(0x341,0x80001000);a.write(0x300,mpv|(1<<11));a.mret(0x80001000);a.mode(1,true);
        a.check(a.read(0xdb0),(33<<16)|7,"VS stopi redirects to vstopi");a.check(a.d.get_io$$interruptPending(),1,"VTI generates VS interrupt");a.check(a.d.get_io$$interruptCause(),33,"VTI six-bit cause preserved");
        a.fault(rd(0x104),22);a.fault(rd(0x144),22);a.fault(rd(0x151),22);
        a.fault((0x14du<<20)|(1<<15)|(1<<12)|(1<<7)|0x73,2); // HS-unqualified overrides VTI.
        a.trap(irq|33,0x80001004,0,0x80000284);a.check(a.read(0x142),irq|33,"VTI precise VS cause");
        a.trap(16,0x80001008,0,0x80000300);a.write(0x609,~0ULL);a.check(a.read(0x609),0x403f03ff,"hvictl WARL mask");
        a.write(0x609,1ULL<<30);a.write(0x300,mpv);a.write(0x341,0x8000100c);a.mret(0x8000100c);a.mode(0,true);
        a.fault(rd(0x14d),2);a.fault((0x14du<<20)|(1<<15)|(1<<12)|(1<<7)|0x73,2);
        b.commands+=a.commands;b.cycles+=a.cycles;b.checks+=a.checks;
    }
    {
        // AIA v1.0 IMSIC 2.1.8.3/4: RV64 odd EIP/EIE selectors are
        // illegal in M/HS but virtual instructions in VS. Reserved window
        // slots and implemented-range padding are distinct RAZ/WI cases.
        Bench q;
        constexpr uint32_t wrGuest = (0x251u<<20)|(1<<15)|(1<<12)|(1<<7)|0x73;
        constexpr uint32_t wrSupervisor = (0x151u<<20)|(1<<15)|(1<<12)|(1<<7)|0x73;
        q.write(0x600,1<<12);
        for(unsigned sel : {0x81u,0xbfu,0xc1u,0xffu}) {
            q.write(0x250,sel);q.fault(rd(0x251),2);q.fault(wrGuest,2);
        }
        q.write(0x341,0x80004000);q.write(0x300,mpv|(1<<11));q.mret(0x80004000);q.mode(1,true);
        for(unsigned sel : {0x81u,0xbfu,0xc1u,0xffu}) {
            q.write(0x150,sel);q.fault(rd(0x151),22);q.fault(wrSupervisor,22);
        }
        for(unsigned sel : {0x71u,0x73u,0x7fu,0x84u,0xbeu,0xc4u,0xfeu}) {
            q.write(0x150,sel);q.check(q.read(0x151),0,"VS indirect reserved/padding reads zero");
            q.write(0x151,~0ULL);q.check(q.read(0x151),0,"VS indirect reserved/padding ignores write");
        }
        for(unsigned sel : {0x40u,0x100u}) {
            q.write(0x150,sel);q.fault(rd(0x151),2);q.fault(wrSupervisor,2);
        }
        q.trap(16,0x80004004,0,0);q.write(0x600,0);q.write(0x250,0x71);
        q.write(0x300,mpv|(1<<11));q.mret(0x80004004);q.mode(1,true);
        q.fault(rd(0x151),22);q.fault(wrSupervisor,22);
        b.commands+=q.commands;b.cycles+=q.cycles;b.checks+=q.checks;
    }
    {
        Bench f;f.check(f.cmd(0x22000073).exception,0,"M HFENCE.VVMA");f.check(f.cmd(0x62000073).exception,0,"M HFENCE.GVMA");
        f.write(0x300,(1<<11)|(1<<20));f.write(0x341,0x80001000);f.mret(0x80001000);f.mode(1,false);
        f.check(f.cmd(0x22000073).exception,0,"HS HFENCE.VVMA ignores TVM");f.fault(0x62000073,2);
        f.trap(16,0x80001004,0,0);f.write(0x300,mpv|(1<<11));f.mret(0x80001004);f.mode(1,true);
        f.fault(0x22000073,22);f.fault(0x62000073,22);f.fault(0x6c004073,22);f.fault(0x6e004073,22);f.fault(0x64304073,22);
        f.fault(0x6c104073,2); // Reserved HLV.D variant is illegal, not virtual.
        b.commands+=f.commands;b.cycles+=f.cycles;b.checks+=f.checks;
    }
    std::cout<<"H_SYSTEM_BARE_PASS commands="<<b.commands<<" edges="<<b.cycles<<" checks="<<b.checks<<"\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
