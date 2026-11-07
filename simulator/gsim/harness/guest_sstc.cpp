#include "HypervisorSystemGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <type_traits>
#include <string>
#include <array>
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

static constexpr uint64_t STCE=1ULL<<63, MPV=1ULL<<39;
static uint32_t csr(unsigned address,unsigned funct,unsigned source){return address<<20|source<<15|funct<<12|1<<7|0x73;}
struct Form {unsigned funct,source;uint64_t operand;const char* name;};
static const Form forms[]={
    {1,1,0,"rw-register-zero"},{1,0,0,"rw-x0"},
    {2,0,0,"rs-x0-read"},{3,0,0,"rc-x0-read"},
    {2,1,0,"rs-register-zero-write"},{3,1,0,"rc-register-zero-write"},
    {5,0,0,"rwi-zero-write"},{6,0,0,"rsi-zero-read"},{7,0,0,"rci-zero-read"},
    {2,1,0x100,"rs-register-bits"},{3,1,0x200,"rc-register-bits"}};
static uint64_t modified(uint64_t old,const Form& f){
    uint64_t source=f.funct>=5?f.source:f.operand;
    switch(f.funct&3){case 1:return source;case 2:return old|source;default:return old&~source;}
}
static void enter(Bench& b,unsigned mode){
    if(mode==0)return; // M, HS, U, VS, VU
    b.write(0x341,0x80001000);b.write(0x300,((mode==1||mode==3)?1ULL<<11:0)|(mode>=3?MPV:0));
    b.mret(0x80001000);b.mode(mode==1||mode==3?1:0,mode>=3);
}
static void matrix(bool wrong,uint64_t& cases,uint64_t& commands,uint64_t& checks){
    constexpr uint64_t host=0x12500,guest=0x23600;
    // Every combination of M.STCE/M.TM/H.STCE/H.TM; all five modes;
    // both compare addresses; encoded zero versus a register containing zero.
    // VTI is checked only in virtual modes, where it changes permissions.
    for(unsigned gates=0;gates<16;gates++)for(unsigned mode=0;mode<5;mode++)
    for(unsigned address:{0x14du,0x24du})for(unsigned vti=0;vti<=(mode>=3?1u:0u);vti++)
    for(const auto& f:forms){
        Bench b;bool ms=gates&1,mt=gates&2,hs=gates&4,ht=gates&8;
        b.write(0x14d,host);b.write(0x24d,guest);
        b.write(0x30a,ms?STCE:0);b.write(0x306,mt?2:0);
        b.write(0x60a,hs?STCE:0);b.write(0x606,ht?2:0);
        // IID=9 suppresses the VTI other-interrupt candidate. No SEI source
        // or interrupt enables are present, including when testing VU.
        b.write(0x609,vti?(1ULL<<30)|(9<<16):0);enter(b,mode);
        bool writes=(f.funct&3)==1||f.source!=0;
        unsigned cause=0;
        if(mode!=0){
            if(!ms||!mt)cause=2;
            else if(mode==2)cause=2;
            else if(mode>=3&&(address==0x24d||mode==4||!hs||!ht||(vti&&writes)))cause=22;
        }
        b.check(b.d.get_io$$interruptPending(),0,"matrix has no interrupt before CSR");
        uint32_t instruction=csr(address,f.funct,f.source);
        auto r=b.cmd(instruction,f.operand,0x80001000,(cases%7==0)?3:0);
        b.check(b.d.get_io$$interruptPending(),0,"matrix has no interrupt after CSR");
        b.check(r.exception,cause!=0,"independent timer access permission");
        if(cause){b.check(r.cause,cause,"independent timer access cause");b.check(r.tval,instruction,"denied timer tval");}
        bool guestBank=address==0x24d||mode>=3;
        uint64_t old=guestBank?guest:host;
        if(!cause)b.check(r.data,old,"independent timer read result");
        // The fixture caller delivers this verified ECALL to trap entry.
        // No ROB-retirement claim is made for the component-level matrix.
        // Exception delegation and every interrupt enable remain zero.
        if(mode!=0){
            auto ecall=b.cmd(0x73,0,0x80001004);
            unsigned recoveryCause=mode==1?9:mode==3?10:8;
            b.check(ecall.exception,1,"mode recovery ECALL exception");
            b.check(ecall.cause,recoveryCause,"mode recovery ECALL cause");
            b.check(ecall.tval,0,"mode recovery ECALL tval");
            b.check(b.d.get_io$$interruptPending(),0,"no interrupt during mode recovery");
            b.trap(recoveryCause,0x80001004,0,0);b.mode(3,false);
        }
        uint64_t expectedHost=host,expectedGuest=guest;
        if(!cause&&writes)(guestBank?expectedGuest:expectedHost)=modified(old,f);
        b.check(b.read(0x14d),expectedHost,"host compare isolation and denied-write stability");
        b.check(b.read(0x24d),expectedGuest^(wrong?1:0),"independent guest compare signature");
        std::cout<<"GUEST_SSTC_ACCESS mode="<<mode<<" gates="<<gates<<" address=0x"<<std::hex<<address
            <<std::dec<<" vti="<<vti<<" form="<<f.name<<" cause="<<cause<<" host=0x"<<std::hex<<expectedHost
            <<" guest=0x"<<expectedGuest<<std::dec<<'\n';
        ++cases;commands+=b.commands;checks+=b.checks;
    }
}
static void timers(uint64_t& cases,uint64_t& commands,uint64_t& checks){
    Bench b;b.write(0x30a,STCE);b.write(0x60a,STCE);b.write(0x603,0x40);
    b.write(0x14d,~0ULL); // isolate the host comparator
    struct Sample {uint64_t time,offset,compare;};
    const Sample samples[]={{100,0,100},{100,0,99},{100,0,101},{100,7,107},{100,7,108},
        {100,uint64_t(-7),93},{100,uint64_t(-7),94},{~0ULL-3,7,3},{~0ULL-3,7,4},
        {3,uint64_t(-7),~0ULL-3},{3,uint64_t(-7),~0ULL-2},{0,0,~0ULL}};
    for(auto s:samples){
        b.d.set_io$$time(s.time);b.write(0x605,s.offset);b.write(0x24d,s.compare);b.tick();b.tick();
        bool pending=uint64_t(s.time+s.offset)>=s.compare;
        b.check(b.read(0x644)&0x40,pending?0x40:0,"unsigned modulo guest time compare");
        b.check(b.read(0x244)&0x20,pending?0x20:0,"VSIP translated hardware timer");
        b.check(b.read(0x645)&0x40,0,"hardware never contaminates HVIP");
        b.check(b.d.get_io$$interruptPending(),0,"M masks guest interrupt eligibility");
        b.check(b.read(0x14d),~0ULL,"host comparator remains independent");
        std::cout<<"GUEST_SSTC_COMPARE time=0x"<<std::hex<<s.time<<" offset=0x"<<s.offset
            <<" compare=0x"<<s.compare<<std::dec<<" pending="<<pending<<'\n';++cases;
    }
    b.d.set_io$$time(100);b.write(0x605,0);b.write(0x24d,100);
    // Counter enables do not gate the hardware source, and V remains zero.
    for(unsigned tm=0;tm<4;tm++){
        b.write(0x306,(tm&1)?2:0);b.write(0x606,(tm&2)?2:0);
        b.check(b.read(0x644)&0x40,0x40,"counteren does not gate comparator");++cases;
    }
    b.write(0x644,0);b.write(0x244,0);
    b.check(b.read(0x644)&0x40,0x40,"HIP VSIP cannot clear hardware timer");
    b.write(0x645,0x40);b.write(0x645,0);
    b.check(b.read(0x644)&0x40,0x40,"software clearing cannot clear hardware timer");
    b.write(0x645,0x40);b.write(0x24d,200);
    b.check(b.read(0x644)&0x40,0x40,"software injection survives rearm");
    b.write(0x645,0);b.check(b.read(0x644)&0x40,0,"independent software clearing");
    b.write(0x644,0x40);b.write(0x244,0x20);
    b.check(b.read(0x644)&0x40,0,"HIP VSIP cannot set timer pending");
    b.write(0x24d,100);b.write(0x645,0x40);b.write(0x60a,0);
    b.check(b.read(0x644)&0x40,0x40,"H STCE gates hardware not injection");
    b.write(0x645,0);b.check(b.read(0x644)&0x40,0,"H STCE disables hardware");
    b.write(0x60a,STCE);b.check(b.read(0x644)&0x40,0x40,"H STCE reenable");
    b.write(0x30a,0);b.check(b.read(0x60a),0,"M STCE masks H STCE read");
    b.write(0x60a,STCE);b.check(b.read(0x60a),0,"H STCE nonwritable without M STCE");
    b.check(b.read(0x644)&0x40,0,"M STCE disables guest hardware");
    b.write(0x645,0x40);b.check(b.read(0x644)&0x40,0x40,"M STCE does not gate injection");b.write(0x645,0);
    b.write(0x30a,STCE);b.check(b.read(0x60a),0,"M STCE disable clears stored H STCE");
    b.check(b.read(0x644)&0x40,0,"H STCE must be explicitly restored");b.write(0x60a,STCE);
    b.write(0x603,0);b.check(b.read(0x244)&0x20,0,"VSIP delegation mask");
    b.check(b.read(0x644)&0x40,0x40,"delegation does not gate hardware source");
    b.write(0x306,2);b.write(0x606,2);
    b.write(0x603,0x40);b.write(0x604,0x40);b.write(0x200,0);
    enter(b,3);b.check(b.d.get_io$$interruptPending(),0,"VS SIE blocks delivery");
    b.write(0x100,2);b.check(b.d.get_io$$interruptPending(),1,"VS SIE enables timer delivery");
    b.check(b.d.get_io$$interruptCause(),6,"raw virtual timer cause");
    b.write(0x104,0);b.check(b.d.get_io$$interruptPending(),0,"VS timer enable masks delivery");
    b.write(0x104,0x20);b.check(b.d.get_io$$interruptPending(),1,"VS timer enable restores delivery");
    // Legal rearm in VS; no exception is requested while IRQ is pending.
    b.write(0x14d,200);b.check(b.d.get_io$$interruptPending(),0,"guest rearm clears delivery");
    // GSIM observations are pre-edge. A new time input must not leak
    // through the registered comparator on its first evaluation.
    b.d.set_io$$time(200);b.tick();
    b.check(b.d.get_io$$interruptPending(),0,"one-cycle timer assertion latency");b.tick();
    b.check(b.d.get_io$$interruptPending(),1,"registered timer equality assertion");
    b.d.set_io$$time(199);b.tick();
    b.check(b.d.get_io$$interruptPending(),1,"one-cycle timer deassertion latency");b.tick();
    b.check(b.d.get_io$$interruptPending(),0,"registered timer future deassertion");
    commands+=b.commands;checks+=b.checks;++cases;
    Bench h;h.d.set_io$$time(100);h.write(0x30a,STCE);h.write(0x60a,STCE);
    h.write(0x24d,100);h.write(0x604,0x40);enter(h,1);
    h.check(h.d.get_io$$interruptPending(),0,"HS global gate blocks undelegated timer");
    h.write(0x100,2);h.check(h.d.get_io$$interruptPending(),1,"HS global gate enables undelegated timer");
    h.check(h.d.get_io$$interruptCause(),6,"HS raw timer cause");
    h.write(0x603,0x40);h.check(h.d.get_io$$interruptPending(),0,"VS delegation excludes HS delivery while V zero");
    h.check(h.read(0x644)&0x40,0x40,"hardware pending retained while V zero");
    commands+=h.commands;checks+=h.checks;++cases;
}
int main(int argc,char** argv){try{
    bool wrong=false;for(int i=1;i<argc;i++){if(std::string(argv[i])=="--wrong-compare")wrong=true;else throw std::runtime_error("unknown guest Sstc argument");}
    uint64_t cases=0,commands=0,checks=0;matrix(wrong,cases,commands,checks);timers(cases,commands,checks);
    std::cout<<"GUEST_SSTC_MSU_PASS cases="<<cases<<" commands="<<commands<<" checks="<<checks<<'\n';return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
