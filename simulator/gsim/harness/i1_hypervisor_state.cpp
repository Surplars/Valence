#include "I1HypervisorStateFixture.h"
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <random>
static unsigned checks=0;
static void need(bool ok,const std::string &what){++checks;if(!ok)throw std::runtime_error(what);}
struct Test {
    SI1HypervisorStateFixture d;
    explicit Test(){
        d.set_clock(0);d.set_reset(1);d.set_io$$readAddress(0);d.set_io$$write$$valid(0);
        d.set_io$$write$$bits$$address(0);d.set_io$$write$$bits$$data(0);
        d.set_io$$retire(0);d.set_io$$trap$$valid(0);d.set_io$$trap$$bits$$pc(0);
        d.set_io$$trap$$bits$$cause(0);d.set_io$$trap$$bits$$tval(0);
        d.set_io$$trap$$bits$$guest$$address(0);d.set_io$$trap$$bits$$guest$$physical(0);
        d.set_io$$trap$$bits$$guest$$implicitPte(0);
        d.set_io$$mret(0);d.set_io$$sret(0);d.set_io$$sfence(0);d.set_io$$time(1000);
        d.set_io$$externalIrq(0);d.set_io$$supervisorExternalIrq(0);
        d.set_io$$timerIrq(0);d.set_io$$softwareIrq(0);
        d.set_io$$fpRetire(0);d.set_io$$fpFlags(0);d.set_io$$vectorRetire(0);
        d.step();cycle();cycle();d.set_reset(0);d.step();cycle();
    }
    void settle(){d.set_clock(0);d.step();}
    void cycle(){d.set_clock(0);d.step();d.set_clock(1);d.step();d.set_clock(0);d.step();}
    uint64_t read(unsigned a,bool legal=true,bool virt=false){
        d.set_io$$readAddress(a);settle();
        need(bool(d.get_io$$readLegal())==legal,"CSR permission address="+std::to_string(a));
        need(bool(d.get_io$$hypervisor$$csrVirtual())==virt,"CSR virtual cause address="+std::to_string(a));
        return d.get_io$$readData();
    }
    void eq(unsigned a,uint64_t value,uint64_t mask=~0ULL){
        auto got=read(a);need((got&mask)==(value&mask),"CSR value address="+std::to_string(a)+
            " got="+std::to_string(got)+" expected="+std::to_string(value));
    }
    void write(unsigned a,uint64_t value){
        read(a);d.set_io$$write$$valid(1);d.set_io$$write$$bits$$address(a);
        d.set_io$$write$$bits$$data(value);cycle();d.set_io$$write$$valid(0);settle();
    }
    void mret(){need(d.get_io$$mretLegal(),"MRET permission");d.set_io$$mret(1);cycle();d.set_io$$mret(0);settle();}
    void sret(){need(d.get_io$$sretLegal(),"SRET permission");d.set_io$$sret(1);cycle();d.set_io$$sret(0);settle();}
    void mode(unsigned priv,bool v){need(d.get_io$$context$$privilege()==priv&&
        bool(d.get_io$$hypervisor$$virtualized())==v,"independent privilege/V oracle");}
    void trap(uint64_t cause,uint64_t pc,uint64_t value,uint64_t target,
              bool gva=false,uint64_t gpa=0,bool implicit=false){
        d.set_io$$trap$$bits$$pc(pc);d.set_io$$trap$$bits$$cause(cause);d.set_io$$trap$$bits$$tval(value);
        d.set_io$$trap$$bits$$guest$$address(gva);d.set_io$$trap$$bits$$guest$$physical(gpa);
        d.set_io$$trap$$bits$$guest$$implicitPte(implicit);settle();
        need(d.get_io$$trapPc()==target,"independent trap-vector oracle");
        d.set_io$$trap$$valid(1);cycle();d.set_io$$trap$$valid(0);settle();
    }
};
int main(int argc,char **argv){try{
    const std::string arg=argc>1?argv[1]:"";
    const bool injectBank=arg=="--inject-bank",injectGva=arg=="--inject-gva";
    constexpr uint64_t MPP_S=1ULL<<11,MPV=1ULL<<39,FS=1ULL<<13,VS=1ULL<<9,IRQ=1ULL<<63;
    Test t;t.mode(3,false);
    t.eq(0x301,0x80000000003411adULL ^ (uint64_t(arg=="--inject-misa")<<21));
    t.eq(0x600,2ULL<<32);
    t.eq(0x303,0x444);t.eq(0x607,0);t.eq(0xe12,0);t.eq(0x60a,0);
    t.write(0x645,0x444);t.write(0x344,0);t.eq(0x645,0x440);
    t.write(0x344,4);t.eq(0x645,0x444);t.read(0x344);
    need((t.d.get_io$$readDataForWrite()&4)==4,"MIP CSR RMW preserves the virtual software latch");
    t.write(0x645,0);t.write(0x602,~0ULL);t.eq(0x602,0xcb1ff);
    t.write(0x680,(8ULL<<60)|0x12347);t.eq(0x680,(8ULL<<60)|0x12344);
    t.write(0x680,9ULL<<60);t.eq(0x680,0);
    t.write(0x280,(8ULL<<60)|0x1fffffff);t.eq(0x280,(8ULL<<60)|0x1fffffff);
    t.write(0x280,9ULL<<60);t.eq(0x280,(8ULL<<60)|0x1fffffff);t.write(0x280,0);
    t.write(0x140,0x1122334455667788ULL);t.write(0x240,0xaabbccddeeff0011ULL);
    t.write(0x305,0x80000800);t.write(0x105,0x80000900);t.write(0x205,0x80000a01);
    t.write(0x300,MPP_S|MPV|FS|VS);t.mret();t.mode(1,true);
    t.eq(0x140,0xaabbccddeeff0011ULL ^ uint64_t(injectBank));
    t.read(0x240,false,true);t.read(0x600,false,true);
    need(!t.d.get_io$$fpEnabled()&&!t.d.get_io$$vectorEnabled(),"guest Off must block both extensions");
    t.write(0x100,FS|VS|2);need(t.d.get_io$$fpEnabled()&&t.d.get_io$$vectorEnabled(),"guest and host Initial");
    t.write(0x140,0xdeadbeef12345678ULL);
    t.d.set_io$$fpRetire(1);t.d.set_io$$fpFlags(3);t.d.set_io$$vectorRetire(1);t.cycle();
    t.d.set_io$$fpRetire(0);t.d.set_io$$vectorRetire(0);t.settle();
    t.eq(0x100,0x6600,0x6600);t.eq(0x001,3);
    t.trap(21,0x40001234,0x12345000,0x80000800,true,0x12345000>>2,true);t.mode(3,false);
    t.eq(0x300,MPV|(uint64_t(!injectGva)<<38)|MPP_S|0x6600,MPV|(1ULL<<38)|(3ULL<<11)|0x6600);
    t.eq(0x34b,0x12345000>>2);t.eq(0x34a,0x3000);t.eq(0x341,0x40001234);
    t.eq(0x140,0x1122334455667788ULL);t.eq(0x240,0xdeadbeef12345678ULL);
    t.write(0x306,7);t.write(0x606,1);t.write(0x605,~0ULL-499); // time=1000 => guest time=500
    t.write(0x302,0xf0b7ff);t.eq(0x302,0xf0b7ff);t.write(0x303,0x222);
    t.write(0x602,0x1ff);t.write(0x603,0x444);t.write(0x304,0);
    t.write(0x300,MPP_S|FS|VS);t.mret();t.mode(1,false);
    t.write(0x600,0x180);t.write(0x100,0x100|FS|VS);t.sret();t.mode(1,true);
    t.read(0xc00);t.read(0xc01,false,true);
    t.trap(22,0x40002000,0x60002073,0x80000900);t.mode(1,false);
    t.eq(0x600,0x180,0x180);t.eq(0x142,22);t.eq(0x643,0);t.eq(0x64a,0);
    t.write(0x606,7);t.write(0x600,0x180);t.sret();t.mode(1,true);t.eq(0xc01,500);
    // Guest SRET selects VU using vsstatus.SPP; a delegated ECALL returns to VS.
    t.write(0x100,FS|VS|0x20);t.sret();t.mode(0,true);
    t.read(0x100,false,true);t.read(0x606,false,true);
    t.trap(8,0x40003000,0,0x80000a00);t.mode(1,true);t.eq(0x142,8);t.eq(0x141,0x40003000);
    t.trap(22,0x40003004,0x60002073,0x80000900);t.mode(1,false);
    t.write(0x205,0x80000a3d); // Guest IRQ 1 carries out of the low BASE word.
    t.write(0x604,4);t.eq(0x104,0);t.eq(0x204,2); // HS sie and hie are disjoint.
    t.write(0x645,4);t.eq(0x244,2);
    t.write(0x200,FS|VS|2);t.write(0x600,0x180);t.write(0x100,0x100|FS|VS);t.sret();
    t.cycle();t.cycle();need(t.d.get_io$$irqPending()&&t.d.get_io$$irqCause()==(IRQ|2),"virtual interrupt eligibility");
    t.trap(IRQ|2,0x40004000,0,0x80000a40);t.mode(1,true);t.eq(0x142,IRQ|1);t.eq(0x100,0,2);
    t.trap(22,0x40004004,0,0x80000900);t.mode(1,false);t.write(0x645,0);t.write(0x604,0);
    // Persistent host IRQ outranks guest state even with the host SIE bit clear.
    t.write(0x104,0x200);t.write(0x600,0x180);t.write(0x100,0x100|FS|VS);t.sret();
    t.d.set_io$$supervisorExternalIrq(1);t.cycle();t.cycle();
    need(t.d.get_io$$irqPending()&&t.d.get_io$$irqCause()==(IRQ|9),"host interrupt while V=1");
    t.trap(IRQ|9,0x40005000,0,0x80000900);t.mode(1,false);t.d.set_io$$supervisorExternalIrq(0);
    // HS TVM affects hgatp, while direct vsatp remains accessible.
    t.trap(11,0x80005004,0,0x80000800);t.mode(3,false);
    t.write(0x300,MPP_S|FS|VS|(1ULL<<20));t.mret();t.read(0x680,false,false);t.read(0x280);
    t.write(0x600,0x180|(1ULL<<20));t.write(0x100,0x100|FS|VS);t.sret();t.mode(1,true);
    t.read(0x180,false,true);need(!t.d.get_io$$sfenceLegal()&&t.d.get_io$$hypervisor$$sfenceVirtual(),"VTVM virtual fence");
    t.trap(22,0x40006000,0x18002073,0x80000900);t.mode(1,false);
    t.trap(11,0x80006004,0,0x80000800);t.mode(3,false);
    t.write(0x300,MPV|(1ULL<<17));need(t.d.get_io$$context$$guest$$dataVirtualized()&&t.d.get_io$$context$$dataPrivilege()==0,
        "MPRV+MPV uses VU translation");
    t.write(0x300,MPV|(3ULL<<11));t.mret();t.mode(3,false);t.eq(0x300,0,MPV);
    std::mt19937_64 rng(0x485653435352ULL);
    for(unsigned n=0;n<2000;++n){auto a=rng(),b=rng();t.write(0x140,a);t.write(0x240,b);
        t.eq(0x140,a);t.eq(0x240,b);t.write(0x645,rng()&0x444);t.eq(0x644,t.read(0x645));}
    std::cout<<"I1_HYPERVISOR_STATE_PASS checks="<<checks<<" banks_modes_delegation_IRQ_FS_VS_GVA_warl_time=PASS\n";
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
