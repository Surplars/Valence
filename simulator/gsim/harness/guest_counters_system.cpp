#ifdef GUEST_COUNTERS_ABSENT
#include "GuestCountersAbsentSystemGsim.h"
using Model=SGuestCountersAbsentSystemGsim;
constexpr bool present=false;
#else
#include "GuestCountersSystemGsim.h"
using Model=SGuestCountersSystemGsim;
constexpr bool present=true;
#endif
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

static uint32_t csr(unsigned a,unsigned f=2,unsigned rs=0){return(a<<20)|(rs<<15)|(f<<12)|(1<<7)|0x73;}
struct Result {uint64_t data,cause,tval,next;bool exception,redirect;};
struct Bench {
    Model d;uint64_t cycle=0,instret=0,edges=0,checks=0,commands=0,serial=0;
    uint64_t absenceCases=0;
    unsigned inhibit=0,commits=0;bool reset=true,retire=false,pending=false;
    unsigned ownerIndex=0,retireIndex=0,pendingAddress=0;
    uint64_t ownerTag=0,retireTag=0,pendingValue=0;
    std::string negative;
    explicit Bench(std::string n):negative(n){
        std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
        d.set_reset(1);tick();tick();reset=false;d.set_reset(0);tick();
    }
    void check(uint64_t got,uint64_t expected,const char* label){
        ++checks;if(got!=expected){std::cerr<<label<<" edge="<<edges<<" got="<<std::hex<<got<<" expected="<<expected<<std::dec<<'\n';throw std::runtime_error(label);}
    }
    void tick(){
        d.set_io$$retired(commits);d.set_io$$retire(retire);d.set_io$$retireIndex(retireIndex);d.set_io$$retireTag(retireTag);
        d.step();++edges;
        if(edges>1){check(d.get_io$$cycle(),cycle,"cycle every edge");check(d.get_io$$instret(),instret,"instret every edge");check(d.get_io$$inhibit(),inhibit,"inhibit every edge");}
        if(reset){cycle=instret=inhibit=0;pending=false;return;}
        if(!present)return;
        if(!(inhibit&1))++cycle;
        if(!(inhibit&4))instret+=commits;
        bool match=pending&&retire&&ownerIndex==retireIndex&&ownerTag==retireTag;
        if(negative=="retire-owner"&&pending&&retire&&ownerIndex==retireIndex)match=true;
        if(match){if(pendingAddress==0xb00)cycle=pendingValue;if(pendingAddress==0xb02)instret=pendingValue;
            if(pendingAddress==0x320)inhibit=pendingValue&5;pending=false;}
    }
    Result result(){return {d.get_io$$data(),d.get_io$$cause(),d.get_io$$tval(),d.get_io$$nextPc(),bool(d.get_io$$exception()),bool(d.get_io$$redirect())};}
    void retireToken(unsigned index,uint64_t tag,unsigned count){retire=true;retireIndex=index;retireTag=tag;commits=count;tick();retire=false;commits=0;tick();}
    void idle(unsigned count){commits=count;tick();commits=0;}
    Result cmd(uint32_t instruction,uint64_t operand=0,unsigned fault=0,unsigned hold=0,bool delay=false){
        const unsigned address=instruction>>20,funct=(instruction>>12)&7,rs=(instruction>>15)&31;
        const bool isCsr=funct!=0,writes=isCsr&&((funct&3)==1||rs!=0);
        const bool bank=isCsr&&(address==0xb00||address==0xb02||address==0x320);
        const bool observed=bank||(isCsr&&(address==0xc00||address==0xc02));
        const unsigned index=(++serial)&15;const uint64_t tag=0x8000000000000000ULL+serial;
        d.set_io$$instruction(instruction);d.set_io$$operand(operand);d.set_io$$pc(0x80001000);
        d.set_io$$tokenIndex(index);d.set_io$$tokenTag(tag);d.set_io$$start(1);d.set_io$$completeReady(0);
        unsigned budget=64;do{tick();if(!--budget)throw std::runtime_error("start watchdog");}while(!d.get_io$$ready());
        d.set_io$$start(0);
        // Request was captured on the previous edge. Execute samples the bank
        // value on this next edge, independently of the eventual completion.
        uint64_t sampled=address==0x320?inhibit:((address==0xb02||address==0xc02)?instret:cycle);
        tick();
        budget=64;while(!d.get_io$$complete()){tick();if(!--budget)throw std::runtime_error("completion watchdog");}
        Result r=result();
        check(r.exception,fault!=0,"command exception");
        if(!present&&fault&&(observed||address==0xb80||address==0xb82||address==0xc80||address==0xc82||
            address==0xb03||address==0xc03||address==0x323))++absenceCases;
        if(fault){check(r.cause,fault+(negative=="exception-cause"),"precise counter access cause");check(r.tval,instruction,"precise counter access tval");
            if(negative=="denied-side-effect"&&present)++instret;
        }else if(observed)check(r.data,sampled^(negative=="sampled-data"),"sampled independent CSR data");
        if(!fault&&present&&bank&&writes){
            const uint64_t source=(funct&4)?rs:operand;
            pendingValue=(funct&3)==1?source:((funct&3)==2?(sampled|source):(sampled&~source));
            pendingAddress=address;ownerIndex=index;ownerTag=tag;pending=true;
        }
        for(unsigned i=0;i<hold;i++){idle(i%3);auto h=result();check(d.get_io$$complete(),1,"held completion valid");check(h.data,r.data,"held sampled data");check(h.cause,r.cause,"held cause");check(h.tval,r.tval,"held tval");check(h.next,r.next,"held next pc");check(h.exception,r.exception,"held exception");check(h.redirect,r.redirect,"held redirect");}
        d.set_io$$completeReady(1);tick();d.set_io$$completeReady(0);tick();
        if(!fault){
            if(delay){idle(0);idle(2);retireToken(index,tag^0x8000000000000000ULL,1);retireToken(index^1,tag,1);idle(1);}
            retireToken(index,tag,1);
        }
        ++commands;return r;
    }
    void write(unsigned a,uint64_t value,bool delay=false){cmd(csr(a,1,1),value,0,0,delay);}
    uint64_t read(unsigned a,unsigned hold=0){return cmd(csr(a),0,0,hold).data;}
    void fault(unsigned a,unsigned cause,unsigned f=2,unsigned rs=0,uint64_t value=0){cmd(csr(a,f,rs),value,cause,3);}
    void mode(unsigned privilege,bool v){write(0x341,0x80001000);write(0x300,(uint64_t(privilege)<<11)|(v?(1ULL<<39):0));cmd(0x30200073);tick();check(d.get_io$$privilege(),privilege,"MRET privilege");check(d.get_io$$virtualized(),v,"MRET V");}
};
int main(int argc,char**argv){try{
    std::string n=argc==2?argv[1]:"";const std::string prefix="--negative-control=";
    if(!n.empty()){if(n.rfind(prefix,0)!=0)throw std::runtime_error("expected --negative-control=NAME");n=n.substr(prefix.size());
        if(n!="sampled-data"&&n!="exception-cause"&&n!="retire-owner"&&n!="denied-side-effect")throw std::runtime_error("unknown negative control");}
    Bench b(n);
    const uint64_t misa=b.read(0x301);b.check((misa>>7)&1,0,"misa H remains clear");
    b.check(misa&1,present?0:1,"A is independent of counter availability");
    if(present){
        b.idle(0);b.idle(1);b.idle(2);
        b.write(0x320,~0ULL,true);b.check(b.read(0x320),5,"mcountinhibit WARL");
        b.write(0xb00,~0ULL,true);b.write(0xb02,~0ULL,true);
        b.cmd(csr(0xb00,3,1),0xf);b.cmd(csr(0xb00,2,1),3); // Frozen RMW operands.
        b.cmd(csr(0xb02,5,7));b.cmd(csr(0xb02,6,8));b.cmd(csr(0xb02,7,3));
        b.write(0xb00,~0ULL);b.write(0xb02,~0ULL);b.write(0x320,0,true);b.idle(2);b.idle(1);
        b.read(0xc00,7);b.read(0xc02,7);b.read(0xb00);b.read(0xb02);
        // A zero-valued register still encodes a write; rs1/zimm zero does not.
        b.cmd(csr(0xb00,2,1),0,0,4,true);b.cmd(csr(0xb02,3,1),0,0,4,true);
        b.cmd(csr(0xb00,6,0),0,0,4);b.cmd(csr(0xb02,7,0),0,0,4);
        for(unsigned a:{0xc00u,0xc02u}){
            b.cmd(csr(a,2,0));b.cmd(csr(a,3,0));b.cmd(csr(a,6,0));b.cmd(csr(a,7,0));
            b.fault(a,2,1,0);b.fault(a,2,2,1,0);b.fault(a,2,3,1,0);b.fault(a,2,5,0);
            b.cmd(csr(a,1,0)&~(31u<<7),0,2); // CSRRW rd=x0, rs1=x0 is still a write.
            b.cmd(csr(a,5,0)&~(31u<<7),0,2); // CSRRWI rd=x0, zimm=0 is still a write.
        }
    }else{
        for(unsigned a:{0xb00u,0xb02u,0x320u,0xc00u,0xc02u}){b.fault(a,2);b.fault(a,2,1,1,123);}
        b.idle(2);b.write(0x306,~0ULL);b.check(b.read(0x306),2,"absent mcounteren mask");
        b.write(0x106,~0ULL);b.check(b.read(0x106),2,"absent scounteren mask");
        b.write(0x606,~0ULL);b.check(b.read(0x606),7,"absent hcounteren baseline mask");
    }
    for(unsigned a:{0xb80u,0xb82u,0xc80u,0xc82u}){b.fault(a,2);b.fault(a,2,1,1,123);}
    if(present){
        b.write(0x306,~0ULL);b.check(b.read(0x306),7,"mcounteren implemented mask");
        b.write(0x606,~0ULL);b.check(b.read(0x606),7,"hcounteren implemented mask");
        b.write(0x106,~0ULL);b.check(b.read(0x106),7,"scounteren implemented mask");
    }
    for(unsigned a:{0xb03u,0xc03u,0x323u})b.fault(a,2); // HPM remains absent.
    uint64_t caseCommands=0,caseEdges=0,caseChecks=0,caseAbsences=0,permissionByMode[5]={},permissionByMask[8]={},permissionByCounter[2]={};
    auto collect=[&](const Bench& q){caseCommands+=q.commands;caseEdges+=q.edges;caseChecks+=q.checks;caseAbsences+=q.absenceCases;};
    // Each case boots in M and enters its target once. No synthetic trap is
    // used as a reset path, and no guest-to-M trap behavior is under test.
    const unsigned privileges[]={3,1,0,1,0};
    const bool virtualized[]={false,false,false,true,true}; // M, HS, U, VS, VU.
    if(present){
        for(unsigned mode=0;mode<5;++mode)for(unsigned counter=0;counter<2;++counter)for(unsigned mask=0;mask<8;++mask){
            const unsigned bit=counter==0?1:4,address=counter==0?0xc00:0xc02;
            const bool m=mask&1,h=mask&2,s=mask&4;
            Bench q(n);q.write(0x306,m?bit:0);q.write(0x606,h?bit:0);q.write(0x106,s?bit:0);
            if(mode!=0)q.mode(privileges[mode],virtualized[mode]);
            // M denial is illegal; H or VU S denial is virtual only after M grants access.
            unsigned cause=0;
            if(mode!=0){
                if(!m)cause=2;
                else if(virtualized[mode]&&(!h||(privileges[mode]==0&&!s)))cause=22;
                else if(!virtualized[mode]&&privileges[mode]==0&&!s)cause=2;
            }
            if(cause)q.fault(address,cause);else q.read(address,5);
            ++permissionByMode[mode];++permissionByMask[mask];++permissionByCounter[counter];
            if(mode!=0)q.fault(counter==0?0xb00:0xb02,2);
            q.fault(counter==0?0xc80:0xc82,2);
            q.cmd(csr(address,1,0)&~(31u<<7),0,2);q.cmd(csr(address,5,0)&~(31u<<7),0,2);
            collect(q);
        }
    }else{
        Bench q(n);q.write(0x306,~0ULL);q.write(0x606,~0ULL);q.mode(1,true);
        q.fault(0xc00,2);q.fault(0xc02,2);collect(q);
    }
    {
        // Existing time, htimedelta and Sstc must survive either feature profile.
        // Compare values exceed time, interrupt enables and external IRQs stay zero.
        Bench q(n);if(present)q.write(0x320,5);q.d.set_io$$time(100);q.check(q.read(0xc01),100,"host time preservation");
        q.write(0x605,7);q.check(q.read(0x605),7,"htimedelta preservation");
        q.write(0x30a,1ULL<<63);q.write(0x60a,1ULL<<63);
        q.write(0x14d,1000);q.write(0x24d,2000);
        q.check(q.read(0x14d),1000,"host Sstc preservation");q.check(q.read(0x24d),2000,"guest Sstc preservation");
        q.write(0x306,2);q.write(0x606,2);q.mode(1,true);
        q.check(q.read(0xc01,4),107,"guest time offset preservation");
        q.d.set_io$$time(200);q.check(q.read(0xc01),207,"external time advances despite inhibited basic counters");
        q.check(q.read(0x14d),2000,"VS Sstc shadow preservation");
        q.check(q.d.get_io$$interruptPending(),0,"preservation checks keep IRQs quiet");collect(q);
    }
    b.tick();std::cout<<(present?"GUEST_COUNTERS_SYSTEM_PASS":"GUEST_COUNTERS_ABSENT_PASS")<<" commands="<<(b.commands+caseCommands)<<" edges="<<(b.edges+caseEdges)<<" checks="<<(b.checks+caseChecks)
        <<" permission_cases="<<(permissionByCounter[0]+permissionByCounter[1])
        <<" permission_cy="<<permissionByCounter[0]<<" permission_ir="<<permissionByCounter[1]
        <<" permission_M="<<permissionByMode[0]<<" permission_HS="<<permissionByMode[1]
        <<" permission_U="<<permissionByMode[2]<<" permission_VS="<<permissionByMode[3]<<" permission_VU="<<permissionByMode[4];
    for(unsigned mask=0;mask<8;++mask)std::cout<<" permission_mask"<<mask<<"="<<permissionByMask[mask];
    std::cout<<" absence_cases="<<(b.absenceCases+caseAbsences)<<'\n';
}catch(const std::exception&e){std::cerr<<"GUEST_COUNTERS_FAIL "<<e.what()<<'\n';return 1;}}
