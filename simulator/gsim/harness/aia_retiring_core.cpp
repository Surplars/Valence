#include "AiaRetiringCoreGsim.h"
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
    Program(unsigned targetGuest,bool hostIrq){
        li(1,-1);emit(csrw(0x3b0,1));write(0x3a0,31);
        addr(1,MT);emit(csrw(0x305,1));addr(1,HS);emit(csrw(0x105,1));addr(1,VI);emit(csrw(0x205,1));
        li(1,1);emit(slli(1,1,22));emit(addi(1,1,1024));emit(csrw(0x302,1));
        write(0x603,1024);
        if(hostIrq){li(1,1);emit(slli(1,1,12));emit(csrw(0x304,1));write(0x607,1<<targetGuest);}
        else write(0x304,1024);
        write(0x200,2);
        li(1,targetGuest);emit(slli(1,1,12));emit(csrw(0x600,1));
        write(0x250,0x70);write(0x251,1);write(0x250,0xc0);write(0x251,32);
        if(hostIrq){li(1,1);emit(slli(1,1,12));emit(csrw(0x600,1));}
        write(0x140,0x11);write(0x240,0x22);addr(1,VS);emit(csrw(0x341,1));
        li(1,1);emit(slli(1,1,39));li(2,1);emit(slli(2,2,11));emit(2<<20|1<<15|6<<12|1<<7|0x33);emit(csrw(0x300,1));emit(0x30200073);
        cursor=VS;emit(csrr(0x140,10));li(1,0x33);emit(csrw(0x140,1,10));emit(0x00000073);emit(csrr(0x600,12));
        li(28,1);uint64_t loop=cursor;emit(addi(26,26,1));emit(beq(27,0,int(loop-cursor)));li(31,99);emit(0x6f);
        cursor=HS;
        if(hostIrq){emit(beq(28,0,8));emit(beq(0,0,int(HS+0x80-cursor)));}
        emit(csrr(0x142,11));emit(csrr(0x600,12));emit(csrr(0x140,13));emit(csrr(0x240,14));emit(csrr(0x141,15));emit(addi(15,15,4));emit(csrw(0x141,15));emit(0x10200073);
        if(hostIrq){cursor=HS+0x80;emit(csrr(0x142,16));emit(csrr(0xe12,18));emit(csrr(0x25c,19));
            li(1,targetGuest);emit(slli(1,1,12));emit(addi(1,1,384));emit(csrw(0x600,1));
            emit(csrr(0x25c,17));emit(csrw(0x25c,0));emit(csrr(0x25c,20));emit(csrr(0xe12,21));li(27,1);emit(0x10200073);}
        cursor=VI;emit(csrr(0x142,16));emit(csrr(0x15c,17));emit(csrw(0x15c,0));emit(csrr(0x15c,20));li(27,1);emit(0x10200073);
        cursor=MT;li(31,-1);emit(0x6f);
    }
};
static int64_t sext(uint64_t value,unsigned width){return int64_t(value<<(64-width))>>(64-width);}
struct Oracle {
    unsigned targetGuest,vgein=0;bool hostIrq,pendingGuest=false;
    Oracle(unsigned guest,bool host):targetGuest(guest),hostIrq(host){}
    uint64_t regs[32]{},pc=BASE,hostScratch=0,guestScratch=0,sepc=0,vsepc=0,scause=0,vscause=0;
    bool v=false,spv=false,spvp=false;unsigned privilege=3,traps=0,irqCount=0,hostFaults=0;uint64_t commits=0,checks=0;
    void check(uint64_t actual,uint64_t expected,const char* label){checks++;if(actual!=expected){std::cerr<<label<<" pc="<<std::hex<<pc<<" got="<<actual<<" expected="<<expected<<std::dec<<'\n';throw std::runtime_error(label);}}
    uint64_t csr(unsigned a){switch(a){case 0x140:return v?guestScratch:hostScratch;case 0x240:return guestScratch;
        case 0x142:return v?vscause:scause;case 0x141:return v?vsepc:sepc;
        case 0x600:return(2ULL<<32)|(uint64_t(vgein)<<12)|(spv?128:0)|(spvp?256:0);
        case 0xe12:return pendingGuest?1ULL<<targetGuest:0;
        case 0x15c:case 0x25c:return pendingGuest&&vgein==targetGuest?0x50005:0;default:return 0;}}
    void write(unsigned a,uint64_t value){
        if(a==0x600){vgein=(value>>12)&63;spv=value&128;spvp=value&256;}
        if((a==0x15c||a==0x25c)&&vgein==targetGuest)pendingGuest=false;
        if(a==0x140){if(v)guestScratch=value;else hostScratch=value;}
        if(a==0x240)guestScratch=value;
        if(a==0x141){if(v)vsepc=value;else sepc=value;}
    }
    void commit(uint64_t actualPc,uint32_t inst,unsigned rd,uint64_t data,uint64_t nextPc,const Program& p){
        check(actualPc,pc,"precise retired PC");check(inst,p.code.at(pc),"retired instruction");
        unsigned op=inst&127,r=(inst>>7)&31,a=(inst>>15)&31,b=(inst>>20)&31,fun=(inst>>12)&7;
        uint64_t value=0,next=pc+4;bool writes=r!=0;
        if(op==0x13){if(fun==0)value=regs[a]+sext(inst>>20,12);else if(fun==1)value=regs[a]<<((inst>>20)&63);else throw std::runtime_error("unknown OPIMM");}
        else if(op==0x17)value=pc+sext(inst&0xfffff000,32);
        else if(op==0x33&&fun==6)value=regs[a]|regs[b];
        else if(op==0x63){writes=false;uint32_t raw=((inst>>31)&1)<<12|((inst>>7)&1)<<11|((inst>>25)&63)<<5|((inst>>8)&15)<<1;if(regs[a]==regs[b])next=pc+sext(raw,13);}
        else if(op==0x6f){
            uint32_t raw=((inst>>31)&1)<<20|((inst>>21)&1023)<<1|((inst>>20)&1)<<11|((inst>>12)&255)<<12;
            value=pc+4;next=pc+sext(raw,21);
        }
        else if(op==0x73&&fun){unsigned address=inst>>20;value=csr(address);if(fun==1)write(address,regs[a]);}
        else if(inst==0x30200073){writes=false;next=VS;v=true;privilege=1;}
        else if(inst==0x10200073){writes=false;if(v)next=vsepc;else{next=sepc;v=spv;spv=false;}privilege=1;}
        else {std::cerr<<"unknown retired PC="<<std::hex<<pc<<" instruction="<<inst<<std::dec<<"\n";throw std::runtime_error("unexpected committed instruction");}
        check(nextPc,next,"independent next PC");if(writes){check(rd,r,"architectural RD");check(data,value,"independent retired data");regs[r]=value;}
        pc=next;commits++;
    }
    void trap(uint64_t actualPc,uint64_t cause,uint64_t tval,const Program& p){
        check(actualPc,pc,"precise trap PC");traps++;
        if(cause==(1ULL<<63|12)){
            check(hostIrq,true,"SGEI route configured");check(v,true,"SGEI starts while guest executes");check(irqCount++,0,"one HS guest-summary IRQ");
            sepc=pc;scause=cause;spv=v;spvp=privilege==1;v=false;pc=HS;
        }
        else if(cause==(1ULL<<63|10)){check(hostIrq,false,"VS route configured");check(v,true,"IRQ starts in guest");check(irqCount++,0,"one guest IRQ");vsepc=pc;vscause=1ULL<<63|9;pc=VI;}
        else {check(v,true,"synchronous fault starts in guest");auto inst=p.code.at(pc);check(cause,inst==0x73?10:22,"VS synchronous trap cause");check(tval,inst==0x73?0:inst,"VS synchronous trap tval");sepc=pc;scause=cause;spv=v;spvp=privilege==1;v=false;pc=HS;hostFaults++;}
    }
};

static uint64_t mmio(SAiaRetiringCoreGsim&d,bool supervisor,unsigned offset,bool write,uint32_t data=0){
    bool accepted=false;
    for(unsigned cycle=0;cycle<100;++cycle){
#define DRIVE(name) \
        d.set_io$$##name##$$request$$valid(!accepted);d.set_io$$##name##$$request$$bits$$address((supervisor?0x0c004000:0x0c000000)+offset); \
        d.set_io$$##name##$$request$$bits$$write(write);d.set_io$$##name##$$request$$bits$$data(data); \
        d.set_io$$##name##$$request$$bits$$size(2);d.set_io$$##name##$$request$$bits$$byteEnable(15)
        if(supervisor){DRIVE(supervisorRegisters);}else{DRIVE(machineRegisters);}
#undef DRIVE
        d.step();bool ready,valid,error;uint64_t value;
#define SAMPLE(name) \
        ready=d.get_io$$##name##$$request$$ready();valid=d.get_io$$##name##$$response$$valid(); \
        error=d.get_io$$##name##$$response$$bits$$error();value=d.get_io$$##name##$$response$$bits$$data(); \
        if(valid)d.set_io$$##name##$$request$$valid(0)
        if(supervisor){SAMPLE(supervisorRegisters);}else{SAMPLE(machineRegisters);}
#undef SAMPLE
        if(d.get_io$$commit0$$valid()||d.get_io$$commit1$$valid()||d.get_io$$trap$$valid())throw std::runtime_error("core progressed during program hold");
        if(!accepted&&ready)accepted=true;
        if(valid){if(!accepted||error)throw std::runtime_error("APLIC MMIO response");return value;}
    }throw std::runtime_error("APLIC MMIO timeout");
}
static void run(unsigned guest,bool hostIrq,bool negative){
    Program p(guest,hostIrq);Oracle o(guest,hostIrq);SAiaRetiringCoreGsim d;
    static_assert(std::is_trivially_copyable_v<SAiaRetiringCoreGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
    d.set_io$$programHold(1);d.set_reset(1);d.step();d.step();d.set_reset(0);d.set_io$$commitEnable(1);
    d.set_io$$machineRegisters$$response$$ready(1);d.set_io$$supervisorRegisters$$response$$ready(1);
    d.set_io$$allowMsi(1);d.set_io$$allowMsiResponse(1);d.step();
    // Configure a real edge-sensitive source in the S child before executing code.
    mmio(d,false,4,true,0x400);mmio(d,true,4,true,4);mmio(d,true,0x3004,true,(guest<<12)|5);
    mmio(d,true,0x1edc,true,1);mmio(d,true,0,true,256);
    o.check(mmio(d,true,0x3004,false),(guest<<12)|5,"APLIC target programmed");
    for(unsigned i=0;i<1024;i++){auto word=p.code.find(BASE+4*i);d.set_io$$programWrite(1);d.set_io$$programIndex(i);d.set_io$$programData(word==p.code.end()?0x13:word->second);d.step();}
    d.set_io$$programWrite(0);d.step();d.set_io$$programHold(0);
    unsigned msiAccepted=0,msiResponses=0,sourceEdges=0,heldRequests=0,heldResponses=0;
    bool sourceHigh=false,previousHeld=false,previousResponseHeld=false;
    uint64_t heldAddress=0,heldData=0,heldResponseData=0;bool heldResponseError=false;
    unsigned sourceCycle=0,firstMsiCycle=0;
    for(unsigned cycle=0;cycle<20000;cycle++) {
        d.set_io$$commitEnable(cycle%7!=4);
        if(o.regs[28]==1&&!sourceHigh){sourceHigh=true;sourceEdges++;sourceCycle=cycle;}
        d.set_io$$sources(sourceHigh?1:0);
        bool requestReady=sourceHigh&&cycle>=sourceCycle+8&&cycle%7==0;
        bool responseReady=msiAccepted&&cycle>=firstMsiCycle+5&&cycle%11==0;
        d.set_io$$allowMsi(requestReady);d.set_io$$allowMsiResponse(responseReady);d.step();
        o.check(d.get_io$$memoryRequest(),0,"Bare program has no data memory requests");o.check(d.get_io$$msiError(),0,"APLIC sticky MSI status");
        if(previousHeld){o.check(d.get_io$$msiValid(),1,"held real APLIC MSI valid");o.check(d.get_io$$msiAddress(),heldAddress,"held real APLIC address");o.check(d.get_io$$msiData(),heldData,"held real APLIC data");}
        previousHeld=d.get_io$$msiValid()&&!d.get_io$$msiFire();heldAddress=d.get_io$$msiAddress();heldData=d.get_io$$msiData();if(previousHeld)heldRequests++;
        if(d.get_io$$msiFire()){
            o.check(d.get_io$$msiAddress(),0x28000000+uint64_t(guest+(negative?1:0))*4096,"independent APLIC-to-core MSI destination");
            o.check(d.get_io$$msiData(),5,"real APLIC MSI identity");msiAccepted++;firstMsiCycle=cycle;o.pendingGuest=true;
        }
        if(previousResponseHeld){
            o.check(d.get_io$$msiResponseValid(),1,"held real MSI response valid");
            o.check(d.get_io$$msiResponseData(),heldResponseData,"held real MSI response data");
            o.check(d.get_io$$msiResponseError(),heldResponseError,"held real MSI response error");
        }
        previousResponseHeld=d.get_io$$msiResponseValid()&&!d.get_io$$msiResponseFire();
        heldResponseData=d.get_io$$msiResponseData();heldResponseError=d.get_io$$msiResponseError();
        if(previousResponseHeld)heldResponses++;
        if(d.get_io$$msiResponseFire()){o.check(d.get_io$$msiResponseError(),0,"real MSI response success");msiResponses++;}
#define COMMIT(n) if(d.get_io$$commit##n##$$valid())o.commit(d.get_io$$commit##n##$$bits$$pc(),d.get_io$$commit##n##$$bits$$instruction(),d.get_io$$commit##n##$$bits$$rd(),d.get_io$$commit##n##$$bits$$data(),d.get_io$$commit##n##$$bits$$nextPc(),p)
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid())o.trap(d.get_io$$trap$$bits$$pc(),d.get_io$$trap$$bits$$cause(),d.get_io$$trap$$bits$$tval(),p);
        if(o.regs[31]==99){o.check(o.hostFaults,2,"two precise guest-to-HS exceptions");o.check(o.irqCount,1,"one physical-source guest interrupt");
            o.check(sourceEdges,1,"one physical source edge");o.check(msiAccepted,1,"one real APLIC MSI");o.check(msiResponses,1,"one real MSI response");
            o.check(o.pendingGuest,0,"architectural CSR claim cleared independent pending model");o.check(o.regs[20],0,"post-claim TOPEI zero retired");
            if(!heldRequests)throw std::runtime_error("MSI request backpressure not exercised");
            if(!heldResponses)throw std::runtime_error("real MSI response backpressure not exercised");
            if(hostIrq){o.check(o.regs[16],(1ULL<<63)|12,"retired HS SGEI cause");o.check(o.regs[18],1ULL<<guest,"retired hgeip mapping");o.check(o.regs[19],0,"inactive VGEIN file zero");o.check(o.regs[21],0,"retired hgeip cleared");}
            else o.check(o.regs[16],(1ULL<<63)|9,"retired VS external cause translation");
            std::cout<<"AIA_OOO_CHAIN_PASS guest="<<guest<<" route="<<(hostIrq?"HS":"VS")<<" cycles="<<cycle<<" commits="<<o.commits
                     <<" traps="<<o.traps<<" checks="<<o.checks<<" held_request="<<heldRequests<<" held_response="<<heldResponses<<" actual_source=1 real_retirement=1\n";return;}
    }
    throw std::runtime_error("real APLIC-to-OoO chain timeout");
}
int main(int argc,char**argv){try{run(1,false,argc>1);run(3,false,false);run(2,true,false);std::cout<<"AIA_OOO_ALL_CHAINS_PASS scenarios=3\n";}
catch(const std::exception&e){std::cerr<<"AIA_OOO_CHAIN_FAIL "<<e.what()<<'\n';return 1;}}
