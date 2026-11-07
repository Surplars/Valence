#include "HypervisorCoreGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <type_traits>
static constexpr uint64_t BASE=0x80000000, VS=BASE+0x400, HS=BASE+0x600, VI=BASE+0x800, MT=BASE+0xa00;
static uint32_t addi(unsigned rd,unsigned rs,int imm){return(uint32_t(imm)&4095)<<20|rs<<15|rd<<7|0x13;}
static uint32_t slli(unsigned rd,unsigned rs,unsigned n){return n<<20|rs<<15|1<<12|rd<<7|0x13;}
static uint32_t auipc(unsigned rd){return rd<<7|0x17;}
static uint32_t csrw(unsigned a,unsigned rs,unsigned rd=0){return a<<20|rs<<15|1<<12|rd<<7|0x73;}
static uint32_t csrr(unsigned a,unsigned rd){return a<<20|2<<12|rd<<7|0x73;}
static uint32_t beq(unsigned a,unsigned b,int offset){uint32_t u=uint32_t(offset)&8191;return ((u>>12)&1)<<31|((u>>5)&63)<<25|b<<20|a<<15|((u>>1)&15)<<8|((u>>11)&1)<<7|0x63;}
struct Program {
    std::map<uint64_t,uint32_t> code;uint64_t cursor=BASE;
    void emit(uint32_t i){code[cursor]=i;cursor+=4;}
    void li(unsigned r,int n){emit(addi(r,0,n));}
    void addr(unsigned r,uint64_t target){int64_t delta=int64_t(target-cursor),upper=(delta+0x800)>>12;emit(uint32_t(upper<<12)|auipc(r));emit(addi(r,r,int(delta-(upper<<12))));}
    void write(unsigned csr,int n){li(1,n);emit(csrw(csr,1));}
    Program(){
        li(1,-1);emit(csrw(0x3b0,1));write(0x3a0,31);
        addr(1,MT);emit(csrw(0x305,1));addr(1,HS);emit(csrw(0x105,1));addr(1,VI);emit(csrw(0x205,1));
        li(1,1);emit(slli(1,1,22));emit(addi(1,1,1024));emit(csrw(0x302,1));
        write(0x603,1024);write(0x304,1024);write(0x200,2);
        li(1,1);emit(slli(1,1,12));emit(csrw(0x600,1));
        write(0x250,0x70);write(0x251,1);write(0x250,0xc0);write(0x251,32);
        write(0x140,0x11);write(0x240,0x22);addr(1,VS);emit(csrw(0x341,1));
        li(1,1);emit(slli(1,1,39));li(2,1);emit(slli(2,2,11));emit(2<<20|1<<15|6<<12|1<<7|0x33);emit(csrw(0x300,1));emit(0x30200073);
        cursor=VS;emit(csrr(0x140,10));li(1,0x33);emit(csrw(0x140,1,10));emit(0x00000073);emit(csrr(0x600,12));
        li(28,1);uint64_t loop=cursor;emit(addi(26,26,1));emit(beq(27,0,int(loop-cursor)));li(31,99);emit(0x6f);
        cursor=HS;emit(csrr(0x142,11));emit(csrr(0x600,12));emit(csrr(0x140,13));emit(csrr(0x240,14));emit(csrr(0x141,15));emit(addi(15,15,4));emit(csrw(0x141,15));emit(0x10200073);
        cursor=VI;emit(csrr(0x142,16));emit(csrr(0x15c,17));emit(csrw(0x15c,0));li(27,1);emit(0x10200073);
        cursor=MT;li(31,-1);emit(0x6f);
    }
};
static int64_t sext(uint64_t value,unsigned width){return int64_t(value<<(64-width))>>(64-width);}
struct Oracle {
    uint64_t regs[32]{},pc=BASE,hostScratch=0,guestScratch=0,sepc=0,vsepc=0,scause=0,vscause=0;
    bool v=false,spv=false,spvp=false;unsigned privilege=3,traps=0,irqCount=0,hostFaults=0;uint64_t commits=0,checks=0;
    void check(uint64_t actual,uint64_t expected,const char* label){checks++;if(actual!=expected){std::cerr<<label<<" pc="<<std::hex<<pc<<" got="<<actual<<" expected="<<expected<<std::dec<<'\n';throw std::runtime_error(label);}}
    uint64_t csr(unsigned a){switch(a){case 0x140:return v?guestScratch:hostScratch;case 0x240:return guestScratch;
        case 0x142:return v?vscause:scause;case 0x141:return v?vsepc:sepc;
        case 0x600:return(2ULL<<32)|(1<<12)|(spv?128:0)|(spvp?256:0);
        case 0x15c:return 0x50005;default:return 0;}}
    void write(unsigned a,uint64_t value){if(a==0x140){if(v)guestScratch=value;else hostScratch=value;}if(a==0x240)guestScratch=value;if(a==0x141){if(v)vsepc=value;else sepc=value;}}
    void commit(uint64_t actualPc,uint32_t inst,unsigned rd,uint64_t data,uint64_t nextPc,const Program& p){
        check(actualPc,pc,"precise retired PC");check(inst,p.code.at(pc),"retired instruction");
        unsigned op=inst&127,r=(inst>>7)&31,a=(inst>>15)&31,b=(inst>>20)&31,fun=(inst>>12)&7;
        uint64_t value=0,next=pc+4;bool writes=r!=0;
        if(op==0x13){if(fun==0)value=regs[a]+sext(inst>>20,12);else if(fun==1)value=regs[a]<<((inst>>20)&63);else throw std::runtime_error("unknown OPIMM");}
        else if(op==0x17)value=pc+sext(inst&0xfffff000,32);
        else if(op==0x33&&fun==6)value=regs[a]|regs[b];
        else if(op==0x63){writes=false;uint32_t raw=((inst>>31)&1)<<12|((inst>>7)&1)<<11|((inst>>25)&63)<<5|((inst>>8)&15)<<1;if(regs[a]==regs[b])next=pc+sext(raw,13);}
        else if(op==0x73&&fun){unsigned address=inst>>20;value=csr(address);if(fun==1)write(address,regs[a]);}
        else if(inst==0x30200073){writes=false;next=VS;v=true;privilege=1;}
        else if(inst==0x10200073){writes=false;if(v)next=vsepc;else{next=sepc;v=spv;spv=false;}privilege=1;}
        else throw std::runtime_error("unexpected committed instruction");
        check(nextPc,next,"independent next PC");if(writes){check(rd,r,"architectural RD");check(data,value,"independent retired data");regs[r]=value;}
        pc=next;commits++;
    }
    void trap(uint64_t actualPc,uint64_t cause,uint64_t tval,const Program& p){
        check(actualPc,pc,"precise trap PC");traps++;
        if(cause==(1ULL<<63|10)){check(v,true,"IRQ starts in guest");check(irqCount++,0,"one guest IRQ");vsepc=pc;vscause=1ULL<<63|9;pc=VI;}
        else {check(v,true,"synchronous fault starts in guest");auto inst=p.code.at(pc);check(cause,inst==0x73?10:22,"VS synchronous trap cause");check(tval,inst==0x73?0:inst,"VS synchronous trap tval");sepc=pc;scause=cause;spv=v;spvp=privilege==1;v=false;pc=HS;hostFaults++;}
    }
};
int main(){try{
    Program p;Oracle o;SHypervisorCoreGsim d;static_assert(std::is_trivially_copyable_v<SHypervisorCoreGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
    d.set_io$$programHold(1);d.set_reset(1);d.step();d.step();d.set_reset(0);d.set_io$$commitEnable(1);d.step();
    for(unsigned i=0;i<1024;i++){auto word=p.code.find(BASE+4*i);d.set_io$$programWrite(1);d.set_io$$programIndex(i);d.set_io$$programData(word==p.code.end()?0x13:word->second);d.step();}
    d.set_io$$programWrite(0);d.step();d.set_io$$programHold(0);
    unsigned msiAccepted=0,msiResponses=0;bool offer=false;
    for(unsigned cycle=0;cycle<20000;cycle++) {
        d.set_io$$commitEnable(cycle%7!=4);
        if(o.regs[28]==1&&!msiAccepted)offer=true;
        d.set_io$$msi$$request$$valid(offer);d.set_io$$msi$$request$$bits$$address(0x28001000);
        d.set_io$$msi$$request$$bits$$write(1);d.set_io$$msi$$request$$bits$$size(2);d.set_io$$msi$$request$$bits$$byteEnable(15);d.set_io$$msi$$request$$bits$$data(5);
        bool responseReady=cycle%5==0;d.set_io$$msi$$response$$ready(responseReady);d.step();
        o.check(d.get_io$$memoryRequest(),0,"Bare program has no data memory requests");
        if(offer&&d.get_io$$msi$$request$$ready()){offer=false;msiAccepted++;}
        if(d.get_io$$msi$$response$$valid()&&responseReady){o.check(d.get_io$$msi$$response$$bits$$error(),0,"MSI success");msiResponses++;}
#define COMMIT(n) if(d.get_io$$commit##n##$$valid())o.commit(d.get_io$$commit##n##$$bits$$pc(),d.get_io$$commit##n##$$bits$$instruction(),d.get_io$$commit##n##$$bits$$rd(),d.get_io$$commit##n##$$bits$$data(),d.get_io$$commit##n##$$bits$$nextPc(),p)
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid())o.trap(d.get_io$$trap$$bits$$pc(),d.get_io$$trap$$bits$$cause(),d.get_io$$trap$$bits$$tval(),p);
        if(o.regs[31]==99){o.check(o.hostFaults,2,"two precise guest-to-HS exceptions");o.check(o.irqCount,1,"one actual guest IMSIC interrupt");o.check(msiAccepted,1,"one accepted MSI");o.check(msiResponses,1,"one MSI response");
            std::cout<<"H_OOO_BARE_PASS cycles="<<cycle<<" commits="<<o.commits<<" traps="<<o.traps<<" checks="<<o.checks<<"\n";return 0;}
    }
    throw std::runtime_error("core timeout");
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
