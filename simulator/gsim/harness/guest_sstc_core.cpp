#include "GuestSstcCoreGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <type_traits>

static constexpr uint64_t BASE=0x80000000, VS=BASE+0x1000, HANDLER=BASE+0x2000;
static constexpr uint64_t DATA=BASE+0x3000, IRQ=1ULL<<63, SIGNATURE=0x5a5;
static uint32_t addi(unsigned d,unsigned s,int n){return (uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t slli(unsigned d,unsigned s,unsigned n){return n<<20|s<<15|1<<12|d<<7|0x13;}
static uint32_t csrw(unsigned c,unsigned r){return c<<20|r<<15|1<<12|0x73;}
static uint32_t csrr(unsigned c,unsigned r){return c<<20|2<<12|r<<7|0x73;}
static uint32_t beq(unsigned a,unsigned b,int offset){uint32_t u=uint32_t(offset)&8191;return ((u>>12)&1)<<31|((u>>5)&63)<<25|b<<20|a<<15|((u>>1)&15)<<8|((u>>11)&1)<<7|0x63;}
static uint32_t ld(unsigned d,unsigned a){return a<<15|3<<12|d<<7|3;}
static uint32_t sd(unsigned s,unsigned a){return s<<20|a<<15|3<<12|0x23;}
static int64_t sext(uint64_t value,unsigned width){return int64_t(value<<(64-width))>>(64-width);}
struct Check {
    uint64_t count=0;
    void eq(uint64_t a,uint64_t b,const char* name){++count;if(a!=b){std::cerr<<name<<" actual=0x"<<std::hex<<a<<" expected=0x"<<b<<std::dec<<'\n';throw std::runtime_error(name);}}
};
struct Memory {
    std::map<uint64_t,uint8_t> bytes;
    void put(uint64_t a,uint64_t v,unsigned n){for(unsigned b=0;b<n;b++)bytes[a+b]=v>>(8*b);}
    uint64_t get(uint64_t a,unsigned n)const{uint64_t v=0;for(unsigned b=0;b<n;b++)v|=uint64_t(bytes.at(a+b))<<(8*b);return v;}
};
struct Program {
    Memory memory;std::map<uint64_t,uint32_t> code;uint64_t pc=BASE,terminal=0,marker=0;
    void emit(uint32_t i){code[pc]=i;memory.put(pc,i,4);pc+=4;}
    void li(unsigned rd,uint64_t value){
        emit(addi(rd,0,0));bool started=false;
        for(int b=7;b>=0;b--){unsigned byte=(value>>(8*b))&255;if(!started&&!byte)continue;
            if(started)emit(slli(rd,rd,8));emit(addi(rd,rd,byte));started=true;}
    }
    void csr(unsigned address,uint64_t value){li(1,value);emit(csrw(address,1));}
    Program(){
        // Defined executable padding is NOP, not a fabricated fault response.
        for(uint64_t a=BASE;a<BASE+0x4000;a+=4)memory.put(a,0x13,4);
        memory.put(DATA,0,8);
        csr(0x300,0);csr(0x304,0);csr(0x302,0);csr(0x303,0);csr(0x602,0);csr(0x603,0);
        csr(0x180,0);csr(0x280,0);csr(0x680,0);csr(0x645,0);csr(0x609,0);
        csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,BASE+0x2800);csr(0x105,BASE+0x2800);
        csr(0x205,HANDLER);csr(0x30a,IRQ);csr(0x60a,IRQ);csr(0x306,2);csr(0x606,2);csr(0x605,7);
        csr(0x14d,3000);csr(0x24d,4000);
        emit(csrr(0x14d,10));emit(csrr(0x24d,11)); // independent host and guest banks before VS
        csr(0x603,64);csr(0x304,64);csr(0x200,2);
        csr(0x341,VS);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
        pc=VS;csr(0x14d,1007);emit(csrr(0x14d,12));emit(csrr(0xc01,13));
        li(26,0);li(27,0);marker=pc;emit(addi(28,0,1));
        uint64_t loop=pc;emit(addi(26,26,1));emit(beq(27,0,int(loop-pc)));
        emit(csrr(0x14d,20));emit(csrr(0xc01,21));li(2,DATA);li(3,SIGNATURE);emit(sd(3,2));emit(ld(22,2));
        terminal=pc;emit(0x6f);
        pc=HANDLER;emit(csrr(0x142,14));emit(csrr(0x141,15));emit(csrr(0x143,16));
        emit(csrr(0xc01,17));emit(csrr(0x14d,18));csr(0x14d,2000);emit(csrr(0x14d,19));
        emit(addi(27,0,1));emit(0x10200073);
    }
};
// The oracle executes the immutable program image. It never assigns an observed
// DUT RD, result, next PC, CSR value, or trap PC to expected architectural state.
struct Oracle {
    uint64_t regs[32]{},pc=BASE,hostCompare=0,guestCompare=0,sepc=0,cause=0;
    uint64_t commits=0,terminalCommits=0,returns=0;unsigned traps=0;bool v=false,raised=false;
    uint64_t csr(unsigned a,Check& check){
        switch(a){case 0x14d:return v?guestCompare:hostCompare;case 0x24d:return guestCompare;
            case 0xc01:return raised?1007:17;case 0x142:return cause;case 0x141:return sepc;case 0x143:return 0;
            default:check.eq(0,1,"oracle supports every CSR read");return 0;}
    }
    void commit(uint64_t actualPc,uint32_t inst,unsigned rd,bool writes,uint64_t data,uint64_t nextPc,
        const Program& p,Check& check,bool wrongTimer,bool stalled){
        check.eq(actualPc,pc,"independent retired PC");check.eq(inst,p.code.at(pc),"independent retired instruction");
        unsigned op=inst&127,r=(inst>>7)&31,a=(inst>>15)&31,fun=(inst>>12)&7;
        uint64_t value=0,next=pc+4;bool expectedWrite=false;
        if(op==0x13){expectedWrite=r!=0;if(fun==0)value=regs[a]+sext(inst>>20,12);
            else if(fun==1)value=regs[a]<<((inst>>20)&63);else throw std::runtime_error("oracle unsupported OPIMM");}
        else if(op==0x63){if(regs[a]==regs[(inst>>20)&31]){uint32_t raw=((inst>>31)&1)<<12|((inst>>7)&1)<<11|((inst>>25)&63)<<5|((inst>>8)&15)<<1;next=pc+sext(raw,13);}}
        else if(op==0x73&&fun){
            unsigned address=inst>>20;expectedWrite=r!=0;if(expectedWrite)value=csr(address,check);
            if(fun==1){if(address==0x14d){if(v)guestCompare=regs[a];else hostCompare=regs[a];}if(address==0x24d)guestCompare=regs[a];}
            else check.eq(fun,2,"oracle CSR read form");
        }else if(inst==0x30200073){next=VS;v=true;}
        else if(inst==0x10200073){check.eq(v,1,"SRET remains virtual");next=sepc;++returns;}
        else if(inst==0x6f){next=pc;++terminalCommits;}
        else if(op==3){check.eq(regs[a],DATA,"oracle load address");expectedWrite=true;value=SIGNATURE;}
        else if(op==0x23){check.eq(regs[a],DATA,"oracle store address");check.eq(regs[(inst>>20)&31],SIGNATURE,"oracle store value");}
        else throw std::runtime_error("oracle unsupported instruction");
        check.eq(writes,expectedWrite,"independent retired write enable");
        if(expectedWrite){check.eq(rd,r,"independent retired RD");
            if(inst==csrr(0x142,14))check.eq(data,value^(wrongTimer?1:0),"independent guest timer signature");
            else check.eq(data,value,"independent retired data");regs[r]=value;}
        check.eq(nextPc,next,"independent retired next PC");
        std::cout<<"GUEST_SSTC_RETIRE schedule="<<(stalled?"stalled":"open")<<" index="<<commits<<" pc=0x"<<std::hex<<pc
            <<" instruction=0x"<<inst<<std::dec<<" writes="<<writes<<" rd="<<rd<<" value=0x"<<std::hex<<data<<" nextPC=0x"<<nextPc<<std::dec<<'\n';
        if(pc==p.marker)raised=true;
        pc=next;++commits;
    }
    void trap(uint64_t actualPc,uint64_t actualCause,uint64_t tval,Check& check,bool stalled){
        check.eq(v,1,"timer trap originates VS");check.eq(raised,1,"timer trap after controlled time edge");
        check.eq(traps,0,"no duplicate timer trap");check.eq(actualPc,pc,"independent precise timer EPC");
        check.eq(actualCause,IRQ|6,"raw virtual timer cause");check.eq(tval,0,"timer trap tval");
        sepc=pc;cause=IRQ|5;pc=HANDLER;++traps;
        std::cout<<"GUEST_SSTC_TRAP schedule="<<(stalled?"stalled":"open")<<" pc=0x"<<std::hex<<sepc<<" handler=0x"<<HANDLER
            <<" rawCause=0x"<<actualCause<<" vsCause=0x"<<cause<<std::dec<<" tval=0 guestPageFault=0 guestAddress=0 implicitPte=0 GPA=0\n";
    }
};
// A physical response cannot be replaced until consumed, even on a redirect.
struct Port {
    bool valid=false,held=false;uint64_t value=0;unsigned delay=0,offerWait=0;
    std::array<uint64_t,12> heldBits{};uint64_t accepted=0,returned=0,stalls=0,serviceDelayCycles=0,responseBlockedCycles=0;
    bool requestReady(bool stalled)const{return !valid&&(!stalled||offerWait>=2);}
    void advance(){if(delay)--delay;if(valid&&delay)++serviceDelayCycles;}
    void stability(bool offer,bool ready,std::array<uint64_t,12> bits,Check& check){
        if(held){check.eq(offer,1,"held request remains valid");for(unsigned i=0;i<bits.size();i++)check.eq(bits[i],heldBits[i],"held physical request stable");}
        held=offer&&!ready;if(held){heldBits=bits;++stalls;if(offerWait<2)++offerWait;}
    }
    void receive(bool ready){if(valid&&!delay){if(ready){valid=false;++returned;}else ++responseBlockedCycles;}}
    void accept(uint64_t data,unsigned latency,Check& check){check.eq(valid,0,"single physical response owner");valid=true;value=data;delay=latency;offerWait=0;++accepted;}
};
static void run(bool stalled,bool wrongTimer){
    Program p;Oracle o;Check check;Port fi,da;unsigned stores=0,loads=0;uint64_t commitDisableCycles=0;
    SGuestSstcCoreGsim d;static_assert(std::is_trivially_copyable_v<SGuestSstcCoreGsim>);
    std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();d.set_io$$timeValue(10);
    d.set_reset(1);d.step();d.step();d.set_reset(0);d.set_io$$enable(1);
    for(unsigned cycle=0;cycle<40000;cycle++){
        bool commitEnable=!stalled||cycle%11!=3;if(!commitEnable)++commitDisableCycles;
        d.set_io$$commitEnable(commitEnable);d.set_io$$timeValue(o.raised?1000:10);
        fi.advance();da.advance();bool fiReady=fi.requestReady(stalled),daReady=da.requestReady(stalled);
        d.set_io$$instruction$$request$$ready(fiReady);d.set_io$$instruction$$response$$valid(fi.valid&&!fi.delay);
        d.set_io$$instruction$$response$$bits(fi.value);d.set_io$$instruction$$responseError(0);d.set_io$$instruction$$responsePageFault(0);
        d.set_io$$fetchPte$$request$$ready(1);d.set_io$$fetchPte$$response$$valid(0);
        d.set_io$$fetchPte$$response$$bits$$data(0);d.set_io$$fetchPte$$response$$bits$$error(0);
        d.set_io$$dataPte$$request$$ready(1);d.set_io$$dataPte$$response$$valid(0);
        d.set_io$$dataPte$$response$$bits$$data(0);d.set_io$$dataPte$$response$$bits$$error(0);
        d.set_io$$data$$request$$ready(daReady);d.set_io$$data$$response$$valid(da.valid&&!da.delay);
        d.set_io$$data$$response$$bits$$data(da.value);d.set_io$$data$$response$$bits$$error(0);d.set_io$$data$$response$$bits$$pageFault(0);
        d.step();fi.receive(d.get_io$$instruction$$response$$ready());da.receive(d.get_io$$data$$response$$ready());
        check.eq(d.get_io$$fetchPte$$request$$valid(),0,"bare fetch has no PTE traffic");
        check.eq(d.get_io$$dataPte$$request$$valid(),0,"bare data has no PTE traffic");
        unsigned latency=stalled?2+cycle%5:1;
        {bool valid=d.get_io$$instruction$$request$$valid();uint64_t address=d.get_io$$instruction$$request$$bits();
            fi.stability(valid,fiReady,{address},check);
            if(valid&&fiReady){check.eq(address>=BASE&&address<BASE+0x3000&&!(address&1),1,"owned physical fetch range");
                uint64_t value=p.memory.get(address,2);fi.accept(value,latency,check);
                std::cout<<"GUEST_SSTC_FETCH schedule="<<(stalled?"stalled":"open")<<" owner="<<fi.accepted<<" address=0x"<<std::hex<<address<<" parcel=0x"<<value<<std::dec<<'\n';}}
        {bool valid=d.get_io$$data$$request$$valid(),write=d.get_io$$data$$request$$bits$$write();
            uint64_t address=d.get_io$$data$$request$$bits$$address(),value=d.get_io$$data$$request$$bits$$data();
            unsigned mask=d.get_io$$data$$request$$bits$$mask(),size=d.get_io$$data$$request$$bits$$size();
            bool virt=d.get_io$$data$$request$$bits$$virtualized(),atomic=d.get_io$$data$$request$$bits$$atomic(),uncached=d.get_io$$data$$request$$bits$$uncached();
            da.stability(valid,daReady,{address,value,mask,write,virt,size,atomic,d.get_io$$data$$request$$bits$$atomicOp(),
                d.get_io$$data$$request$$bits$$precheckedLoad(),d.get_io$$data$$request$$bits$$translationEpoch(),
                d.get_io$$data$$request$$bits$$prefetchNextAllowed(),uncached},check);
            if(valid&&daReady){check.eq(address,DATA,"independent physical data address");check.eq(size,3,"doubleword physical data size");
                check.eq(virt,0,"physical request is not virtualized");check.eq(atomic,0,"ordinary physical RAM operation");check.eq(uncached,0,"cacheable physical RAM");
                if(write){check.eq(stores++,0,"one physical store");check.eq(value,SIGNATURE,"independent physical store data");check.eq(mask,255,"full store mask");p.memory.put(address,value,8);}
                else{check.eq(stores,1,"load follows physical store");check.eq(loads++,0,"one physical load");}
                da.accept(p.memory.get(address,8),latency,check);
                std::cout<<"GUEST_SSTC_DATA schedule="<<(stalled?"stalled":"open")<<" owner="<<da.accepted<<" write="<<write<<" address=0x"<<std::hex<<address<<" value=0x"<<value<<" mask=0x"<<mask<<std::dec<<'\n';}}
#define COMMIT(N) if(d.get_io$$commit##N##$$valid()){check.eq(commitEnable,1,"retirement obeys commit backpressure");o.commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),p,check,wrongTimer,stalled);}
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid()){
            check.eq(d.get_io$$trap$$bits$$guestFault$$guestPageFault(),0,"timer has no guest page fault");
            check.eq(d.get_io$$trap$$bits$$guestFault$$guestAddress(),0,"timer has no address provenance");
            check.eq(d.get_io$$trap$$bits$$guestFault$$implicitPte(),0,"timer has no implicit PTE");
            check.eq(d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),0,"timer has no GPA");
            o.trap(d.get_io$$trap$$bits$$pc(),d.get_io$$trap$$bits$$cause(),d.get_io$$trap$$bits$$tval(),check,stalled);
        }
        if(o.terminalCommits>=12){
            check.eq(o.pc,p.terminal,"finite terminal endpoint");check.eq(o.traps,1,"one clean guest timer interrupt");check.eq(o.returns,1,"one actual SRET");
            check.eq(o.hostCompare,3000,"host bank isolated");check.eq(o.guestCompare,2000,"guest timer rearmed");
            check.eq(stores,1,"one owned physical store");check.eq(loads,1,"one owned physical load");check.eq(p.memory.get(DATA,8),SIGNATURE,"final RAM signature");
            for(Port* port:{&fi,&da})check.eq(port->accepted-port->returned,port->valid,"honest outstanding response ownership");
            check.eq(da.valid,0,"all data responses consumed");
            if(stalled){for(Port* port:{&fi,&da}){check.eq(port->stalls>0,1,"active port held requests exercised");check.eq(port->serviceDelayCycles>0,1,"active port service delay exercised");}
                check.eq(commitDisableCycles>0,1,"commit disable schedule exercised");}
            std::cout<<"GUEST_SSTC_CORE_PASS schedule="<<(stalled?"stalled":"open")<<" cycles="<<cycle+1<<" commits="<<o.commits<<" traps="<<o.traps<<" returns="<<o.returns<<" checks="<<check.count
                <<" accepted="<<fi.accepted<<",0,0,"<<da.accepted<<" returned="<<fi.returned<<",0,0,"<<da.returned
                <<" outstanding="<<fi.valid<<",0,0,"<<da.valid<<" heldOffers="<<fi.held<<",0,0,"<<da.held
                <<" portOrder=instruction,fetchPte,dataPte,data requestStalls="<<fi.stalls<<",0,0,"<<da.stalls
                <<" serviceDelayCycles="<<fi.serviceDelayCycles<<",0,0,"<<da.serviceDelayCycles
                <<" responseBlockedCycles="<<fi.responseBlockedCycles<<",0,0,"<<da.responseBlockedCycles
                <<" commitDisableCycles="<<commitDisableCycles<<" terminalCommits="<<o.terminalCommits<<'\n';return;
        }
    }
    throw std::runtime_error("finite guest timer core cycle bound exceeded");
}
int main(int argc,char** argv){try{
    bool wrongTimer=false;for(int i=1;i<argc;i++){if(std::string(argv[i])=="--wrong-timer")wrongTimer=true;else throw std::runtime_error("unknown guest timer core argument");}
    run(false,wrongTimer);run(true,wrongTimer);std::cout<<"GUEST_SSTC_CORE_ALL_PASS cases=2\n";return 0;
}catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
