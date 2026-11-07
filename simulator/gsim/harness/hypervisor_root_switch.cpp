#include "HypervisorTranslatedCoreGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

// Three address spaces, but deliberately no ASID/VMID differentiation.
static constexpr uint64_t BASE=0x80000000, HS=BASE+0x2000, MT=BASE+0x4000;
static constexpr uint64_t VA=0x40000000, DATA=VA+0x1000;
static constexpr uint64_t GR[2]={0x80010000,0x80020000}; // Sv39x4: 16 KiB aligned
static constexpr uint64_t VR[2]={0x10000000,0x10003000};
static constexpr uint64_t CODE[3]={0x80200000,0x80202000,0x80204000};
static constexpr uint64_t RAM[3]={0x80201000,0x80203000,0x80205000};
static uint32_t addi(unsigned d,unsigned s,int n){return (uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t slli(unsigned d,unsigned s,unsigned n){return n<<20|s<<15|1<<12|d<<7|0x13;}
static uint32_t csrw(unsigned c,unsigned r){return c<<20|r<<15|1<<12|0x73;}
static uint32_t csrr(unsigned c,unsigned r){return c<<20|2<<12|r<<7|0x73;}
static uint32_t ld(unsigned d,unsigned a,unsigned off){return off<<20|a<<15|3<<12|d<<7|3;}
static uint32_t sd(unsigned s,unsigned a,unsigned off){return(off>>5)<<25|s<<20|a<<15|3<<12|(off&31)<<7|0x23;}
struct Memory {
    std::map<uint64_t,uint8_t> bytes;
    void put(uint64_t a,uint64_t v,unsigned n){for(unsigned b=0;b<n;b++)bytes[a+b]=v>>(8*b);}
    uint64_t get(uint64_t a,unsigned n) const {uint64_t v=0;for(unsigned b=0;b<n;b++)v|=uint64_t(bytes.at(a+b))<<(8*b);return v;}
    void page(uint64_t a){for(unsigned b=0;b<4096;b++)bytes[a+b]=0;}
    void pte(uint64_t a,uint64_t dest,unsigned flags){put(a,(dest>>12)<<10|flags,8);}
};
struct Expected {uint64_t pc;uint32_t inst;unsigned rd;bool writes;uint64_t value,next;bool trap=false;};
struct Store {uint64_t address,value;};
struct Program {
    Memory memory;
    std::vector<Expected> expected;
    std::vector<Store> stores;
    uint64_t pc=BASE,physical=BASE,terminal=0,ecallPc=0;
    // This ledger is constructed before reset, not from memory reads or DUT results.
    void emit(uint32_t i,unsigned rd=0,uint64_t value=0,uint64_t next=0){
        memory.put(physical,i,4);expected.push_back({pc,i,rd,rd!=0,value,next?next:pc+4});pc+=4;physical+=4;
    }
    void at(uint64_t v,uint64_t p){pc=v;physical=p;}
    void li(unsigned rd,uint64_t value){
        uint64_t n=0;emit(addi(rd,0,0),rd,0);bool started=false;
        for(int b=7;b>=0;b--){unsigned byte=(value>>(8*b))&255;if(!started&&!byte)continue;
            if(started){n<<=8;emit(slli(rd,rd,8),rd,n);}n+=byte;emit(addi(rd,rd,byte),rd,n);started=true;}
    }
    void csr(unsigned c,uint64_t v){li(1,v);emit(csrw(c,1));}
    void roots(unsigned vs,unsigned g){
        csr(0x280,(8ULL<<60)|(VR[vs]>>12));csr(0x680,(8ULL<<60)|(GR[g]>>12));
        emit(csrr(0x280,20),20,(8ULL<<60)|(VR[vs]>>12));
        emit(csrr(0x680,21),21,(8ULL<<60)|(GR[g]>>12));
        emit(0x22000073);emit(0x62000073); // global HFENCE.VVMA / HFENCE.GVMA
    }
    Program(){
        for(uint64_t p=BASE;p<BASE+0x5000;p+=4096)memory.page(p);
        for(unsigned c=0;c<3;c++){memory.page(CODE[c]);memory.page(RAM[c]);}
        // Each G root maps all six VS page-table pages identically. Only guest
        // payload GPA mappings differ under G root B; no table changes after reset.
        for(unsigned g=0;g<2;g++){
            for(unsigned p=0;p<7;p++)memory.page(GR[g]+p*4096);
            uint64_t mid=GR[g]+0x4000,pt=GR[g]+0x5000,data=GR[g]+0x6000;
            memory.pte(GR[g],mid,1);memory.pte(mid+128*8,pt,1);memory.pte(mid+256*8,data,1);
            for(unsigned p=0;p<6;p++)memory.pte(pt+p*8,0x80300000+p*4096,0xdf);
            memory.pte(data,CODE[0],0xdf);memory.pte(data+8,RAM[0],0xdf);
            memory.pte(data+16,CODE[g?2:1],0xdf);memory.pte(data+24,RAM[g?2:1],0xdf);
        }
        for(unsigned p=0;p<6;p++)memory.page(0x80300000+p*4096);
        for(unsigned v=0;v<2;v++){
            uint64_t spa=0x80300000+v*0x3000;
            memory.pte(spa+8,VR[v]+4096,1);memory.pte(spa+4096,VR[v]+8192,1);
            memory.pte(spa+8192,0x20000000+v*8192,0xcb);
            memory.pte(spa+8200,0x20001000+v*8192,0xc7);
        }
        memory.put(RAM[0],0x1122334455667701ULL,8);memory.put(RAM[1],0x2233445566778802ULL,8);memory.put(RAM[2],0x3344556677889903ULL,8);
        // Explicitly initialize all architectural state this test relies upon.
        csr(0x300,0);csr(0x304,0);csr(0x180,0);csr(0x303,0);csr(0x602,0);csr(0x603,0);
        csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,MT);csr(0x105,HS);csr(0x302,1<<10);
        csr(0x600,1<<8);roots(0,0);csr(0x341,VA);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073,0,0,VA);
        // Independent context/visit signatures. First-visit values are zero;
        // revisits must see only that context's earlier store.
        constexpr unsigned context[5]={0,1,2,1,0};
        constexpr uint64_t initial[5]={0x1122334455667701ULL,0x2233445566778802ULL,0x3344556677889903ULL,0x2233445566778802ULL,0x1122334455667701ULL};
        constexpr uint64_t before[5]={0,0,0,0x22,0x11},after[5]={0x11,0x22,0x33,0x44,0x22};
        for(unsigned visit=0;visit<5;visit++){
            unsigned c=context[visit];at(VA,CODE[c]);
            emit(addi(9,0,0x11*(c+1)),9,0x11*(c+1));li(2,DATA);
            emit(ld(10,2,0),10,initial[visit]);emit(ld(11,2,8),11,before[visit]);
            emit(addi(12,11,0x11*(c+1)),12,after[visit]);emit(sd(12,2,8));
            stores.push_back({RAM[c]+8,after[visit]});emit(ld(13,2,8),13,after[visit]);
            ecallPc=pc;memory.put(physical,0x73,4);expected.push_back({pc,0x73,0,false,0,HS+visit*0x400,true});
            at(HS+visit*0x400,HS+visit*0x400);
            emit(csrr(0x142,22),22,10);emit(csrr(0x141,23),23,ecallPc);
            emit(csrr(0x143,24),24,0);emit(csrr(0x643,25),25,0);emit(csrr(0x64a,26),26,0);
            // SPV/SPVP set, GVA clear for an ordinary VS ECALL.
            emit(csrr(0x600,27),27,(2ULL<<32)|0x180);
            if(visit==4){terminal=pc;emit(0x6f,0,pc+4,pc);break;}
            unsigned next=context[visit+1];roots(next?1:0,next==2?1:0);
            csr(0x105,HS+(visit+1)*0x400);csr(0x141,VA);emit(0x10200073,0,0,VA);
        }
        memory.put(MT,0x6f,4);
    }
};
struct Check {
    uint64_t count=0;
    void eq(uint64_t a,uint64_t b,const char* name){++count;if(a!=b){std::cerr<<name<<" actual=0x"<<std::hex<<a<<" expected=0x"<<b<<std::dec<<'\n';throw std::runtime_error(name);}}
};
// One response owner per physical port. No owner is reused before consumption.
struct Port {
    bool valid=false,held=false;uint64_t value=0;unsigned delay=0;
    std::array<uint64_t,12> heldBits{};uint64_t accepted=0,returned=0,stalls=0;
    unsigned offerWait=0;
    uint64_t serviceDelayCycles=0,responseBlockedCycles=0;
    // A stalled port observes two full offered cycles before accepting each
    // request. This exercises every port, independently of modulo alignment.
    bool requestReady(bool stalled) const {return !valid&&(!stalled||offerWait>=2);}
    void advance(){if(delay)--delay;if(valid&&delay)++serviceDelayCycles;}
    void stability(bool offer,bool ready,std::array<uint64_t,12> bits,Check& check){
        if(held){check.eq(offer,1,"held request remains valid");for(unsigned i=0;i<bits.size();i++)check.eq(bits[i],heldBits[i],"held physical request stable");}
        held=offer&&!ready;if(held){heldBits=bits;++stalls;if(offerWait<2)++offerWait;}
    }
    void receive(bool ready){
        if(valid&&!delay){if(ready){valid=false;++returned;}else ++responseBlockedCycles;}
    }
    void accept(uint64_t data,unsigned latency,Check&check){check.eq(valid,0,"single physical response owner");valid=true;value=data;delay=latency;offerWait=0;++accepted;}
};
static void run(bool stalled,bool wrongFetch,bool wrongData){
    Program p;Check check;auto& memory=p.memory;
    // Controls corrupt only independent expected signatures, never code/tables/data.
    SHypervisorTranslatedCoreGsim d;
    static_assert(std::is_trivially_copyable_v<SHypervisorTranslatedCoreGsim>);
    memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();d.set_reset(1);d.step();d.step();d.set_reset(0);d.set_io$$enable(1);
    Port fi,fp,dp,da;size_t retired=0,storeIndex=0;unsigned traps=0,terminalCommits=0,visit=0;
    uint64_t commits=0,commitDisableCycles=0;
    std::array<uint64_t,5> codeReads{},dataReads{},dataWrites{},fetchGRoot{},fetchVRoot{},dataGRoot{},dataVRoot{};
    constexpr unsigned contexts[5]={0,1,2,1,0};
    for(unsigned cycle=0;cycle<160000;cycle++){
        bool commitEnable=!stalled||cycle%11!=3;
        if(!commitEnable)++commitDisableCycles;
        d.set_io$$commitEnable(commitEnable);
        for(Port* port:{&fi,&fp,&dp,&da})port->advance();
        bool ready_instruction=fi.requestReady(stalled);
        bool ready_fetchPte=fp.requestReady(stalled);
        bool ready_dataPte=dp.requestReady(stalled);
        bool ready_data=da.requestReady(stalled);
        d.set_io$$instruction$$request$$ready(ready_instruction);
        d.set_io$$instruction$$response$$valid(fi.valid&&!fi.delay);d.set_io$$instruction$$response$$bits(fi.value);
        d.set_io$$instruction$$responseError(0);d.set_io$$instruction$$responsePageFault(0);
#define DRIVE_PTE(P,N) d.set_io$$##N##$$request$$ready(ready_##N);d.set_io$$##N##$$response$$valid(P.valid&&!P.delay);d.set_io$$##N##$$response$$bits$$data(P.value);d.set_io$$##N##$$response$$bits$$error(0)
        DRIVE_PTE(fp,fetchPte);DRIVE_PTE(dp,dataPte);
#undef DRIVE_PTE
        d.set_io$$data$$request$$ready(ready_data);d.set_io$$data$$response$$valid(da.valid&&!da.delay);
        d.set_io$$data$$response$$bits$$data(da.value);d.set_io$$data$$response$$bits$$error(0);d.set_io$$data$$response$$bits$$pageFault(0);
        d.step();
        fi.receive(d.get_io$$instruction$$response$$ready());fp.receive(d.get_io$$fetchPte$$response$$ready());
        dp.receive(d.get_io$$dataPte$$response$$ready());da.receive(d.get_io$$data$$response$$ready());
        unsigned latency=stalled?2+cycle%5:1;
        auto acceptedPte=[&](uint64_t address,bool fetch){
            unsigned ctx=contexts[visit],g=ctx==2?1:0,v=ctx?1:0;
            if(address==GR[g])++(fetch?fetchGRoot[visit]:dataGRoot[visit]);
            if(address==0x80300000+v*0x3000+8)++(fetch?fetchVRoot[visit]:dataVRoot[visit]);
            check.eq((address>=0x80010000&&address<0x80027000)||(address>=0x80300000&&address<0x80306000),1,"PTE read physical table range");
        };
#define READ_PORT(P,N,SIZE) \
        {bool valid=d.get_io$$##N##$$request$$valid();uint64_t address=d.get_io$$##N##$$request$$bits(); \
        P.stability(valid,ready_##N,{address,0,0,0,0},check); \
        if(valid&&ready_##N){P.accept(memory.get(address,SIZE),latency,check);
        READ_PORT(fi,instruction,2)
            if(address>=CODE[contexts[visit]]&&address<CODE[contexts[visit]]+4096)++codeReads[visit];
        }}
        READ_PORT(fp,fetchPte,8) acceptedPte(address,true);}}
        READ_PORT(dp,dataPte,8) acceptedPte(address,false);}}
#undef READ_PORT
        {
            bool valid=d.get_io$$data$$request$$valid(),write=d.get_io$$data$$request$$bits$$write();
            uint64_t address=d.get_io$$data$$request$$bits$$address(),value=d.get_io$$data$$request$$bits$$data();
            unsigned mask=d.get_io$$data$$request$$bits$$mask();bool virt=d.get_io$$data$$request$$bits$$virtualized();
            unsigned size=d.get_io$$data$$request$$bits$$size();
            bool atomic=d.get_io$$data$$request$$bits$$atomic(),uncached=d.get_io$$data$$request$$bits$$uncached();
            da.stability(valid,ready_data,{address,value,mask,write,virt,size,atomic,
                d.get_io$$data$$request$$bits$$atomicOp(),d.get_io$$data$$request$$bits$$precheckedLoad(),
                d.get_io$$data$$request$$bits$$translationEpoch(),d.get_io$$data$$request$$bits$$prefetchNextAllowed(),uncached},check);
            if(valid&&ready_data){
                check.eq(virt,0,"external data request is physical");check.eq(size,3,"doubleword physical request size");
                check.eq(atomic,0,"no atomic physical operations");check.eq(uncached,0,"cacheable RAM physical operations");
                check.eq(address==RAM[contexts[visit]]||address==RAM[contexts[visit]]+8,1,"independent physical data destination");
                std::cout<<"ROOT_SWITCH_DATA schedule="<<(stalled?"stalled":"open")<<" phase="<<visit
                    <<" write="<<write<<" size="<<size<<" address=0x"<<std::hex<<address<<" value=0x"<<value<<" mask=0x"<<mask<<std::dec<<'\n';
                if(write){
                    check.eq(storeIndex<p.stores.size(),1,"no extra external store");const auto& e=p.stores.at(storeIndex++);
                    check.eq(address,e.address,"independent physical store address");check.eq(value,e.value,"independent physical store value");
                    check.eq(mask,255,"full doubleword store mask");memory.put(address,value,8);++dataWrites[visit];
                }else ++dataReads[visit];
                da.accept(memory.get(address&~7ULL,8),latency,check);
            }
        }
        auto commit=[&](uint64_t pc,uint32_t instruction,unsigned rd,bool writes,uint64_t value,uint64_t next){
            check.eq(commitEnable,1,"retirement obeys commit backpressure");
            const Expected& e=retired<p.expected.size()?p.expected[retired]:p.expected.back();
            check.eq(e.trap,0,"ECALL traps rather than retires");check.eq(pc,e.pc,"retired PC");
            if(pc==VA)check.eq(instruction,e.inst^(wrongFetch&&visit==1?0x100000:0),"independent root fetch signature");
            else check.eq(instruction,e.inst,"retired instruction");
            check.eq(writes,e.writes,"retired write enable");
            // RD/data without write enable are logged but have no architectural
            // meaning. Never turn an implementation's incidental zero into ISA.
            if(e.writes){
                check.eq(rd,e.rd,"retired RD");
                if(instruction==ld(10,2,0))check.eq(value,e.value^(wrongData&&visit==1?1:0),"independent root data signature");
                else check.eq(value,e.value,"retired data");
            }
            check.eq(next,e.next,"retired next PC");
            std::cout<<"ROOT_SWITCH_RETIRE schedule="<<(stalled?"stalled":"open")<<" index="<<commits
                <<" pc=0x"<<std::hex<<pc<<" instruction=0x"<<instruction<<" rd="<<std::dec<<rd
                <<" writes="<<writes<<" value=0x"<<std::hex<<value<<" nextPC=0x"<<next<<std::dec<<'\n';
            if(instruction==0x10200073)++visit;
            if(instruction==0x10200073||instruction==0x30200073)
                std::cout<<"ROOT_SWITCH_ENTER schedule="<<(stalled?"stalled":"open")<<" phase="<<visit
                    <<" context="<<contexts[visit]<<" vsatp=0x"<<std::hex<<((8ULL<<60)|(VR[contexts[visit]?1:0]>>12))
                    <<" hgatp=0x"<<((8ULL<<60)|(GR[contexts[visit]==2?1:0]>>12))<<std::dec<<'\n';
            if(pc==p.terminal)++terminalCommits;
            if(retired<p.expected.size())++retired;
            ++commits;
        };
#define COMMIT(N) if(d.get_io$$commit##N##$$valid())commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc())
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid()){
            const auto& e=p.expected.at(retired);check.eq(e.trap,1,"no unexpected trap");
            check.eq(d.get_io$$trap$$bits$$pc(),e.pc,"precise VS ECALL PC");
            check.eq(d.get_io$$trap$$bits$$cause(),10,"ordinary VS ECALL cause");check.eq(d.get_io$$trap$$bits$$tval(),0,"VS ECALL tval");
            check.eq(d.get_io$$trap$$bits$$guestFault$$guestPageFault(),0,"ECALL is not guest page fault");
            check.eq(d.get_io$$trap$$bits$$guestFault$$guestAddress(),0,"ECALL has no address provenance");
            check.eq(d.get_io$$trap$$bits$$guestFault$$implicitPte(),0,"ECALL is not implicit PTE");
            check.eq(d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),0,"ECALL has no GPA");++retired;++traps;
            std::cout<<"ROOT_SWITCH_ECALL schedule="<<(stalled?"stalled":"open")<<" phase="<<visit
                <<" pc=0x"<<std::hex<<e.pc<<" handler=0x"<<e.next<<std::dec
                <<" cause=10 tval=0 guestPageFault=0 guestAddress=0 implicitPte=0 GPA=0\n";
        }
        if(terminalCommits>=12){
            check.eq(retired,p.expected.size(),"complete independent retirement ledger");check.eq(traps,5,"five VS ECALLs");
            check.eq(storeIndex,5,"five physical stores");
            constexpr uint64_t final[3]={0x22,0x44,0x33};
            constexpr uint64_t initial[3]={0x1122334455667701ULL,0x2233445566778802ULL,0x3344556677889903ULL};
            for(unsigned c=0;c<3;c++){check.eq(memory.get(RAM[c]+8,8),final[c],"isolated final physical modification");check.eq(memory.get(RAM[c],8),initial[c],"immutable initial physical data");}
            for(unsigned phase=0;phase<5;phase++){
                check.eq(codeReads[phase]>0,1,"phase physical code traffic");check.eq(dataReads[phase],3,"phase physical data reads");check.eq(dataWrites[phase],1,"phase physical store");
                check.eq(fetchGRoot[phase]>0&&fetchVRoot[phase]>0,1,"phase fetch walks both roots");
                check.eq(dataGRoot[phase]>0&&dataVRoot[phase]>0,1,"phase data walks both roots");
                std::cout<<"ROOT_SWITCH_PHASE schedule="<<(stalled?"stalled":"open")<<" phase="<<phase<<" context="<<contexts[phase]
                    <<" fetch="<<codeReads[phase]<<" dataRead="<<dataReads[phase]<<" store="<<dataWrites[phase]
                    <<" fetchGRoot="<<fetchGRoot[phase]<<" fetchVRoot="<<fetchVRoot[phase]<<" dataGRoot="<<dataGRoot[phase]<<" dataVRoot="<<dataVRoot[phase]<<'\n';
            }
            for(Port* port:{&fi,&fp,&dp,&da})check.eq(port->accepted-port->returned,port->valid,"honest outstanding response ownership");
            check.eq(fp.valid||dp.valid||da.valid,0,"all table/data responses consumed at terminal");
            if(stalled){
                for(Port* port:{&fi,&fp,&dp,&da}){
                    check.eq(port->stalls>0,1,"each physical port observed held requests");
                    check.eq(port->serviceDelayCycles>0,1,"each physical port observed service delay");
                }
                check.eq(commitDisableCycles>0,1,"commit disable schedule exercised");
            }
            std::cout<<"HYPERVISOR_ROOT_SWITCH_PASS schedule="<<(stalled?"stalled":"open")<<" cycles="<<cycle+1<<" commits="<<commits<<" traps="<<traps<<" checks="<<check.count
                <<" accepted="<<fi.accepted<<','<<fp.accepted<<','<<dp.accepted<<','<<da.accepted
                <<" returned="<<fi.returned<<','<<fp.returned<<','<<dp.returned<<','<<da.returned
                <<" outstanding="<<fi.valid<<','<<fp.valid<<','<<dp.valid<<','<<da.valid
                <<" heldOffers="<<fi.held<<','<<fp.held<<','<<dp.held<<','<<da.held
                <<" portOrder=instruction,fetchPte,dataPte,data"
                <<" requestStalls="<<fi.stalls<<','<<fp.stalls<<','<<dp.stalls<<','<<da.stalls
                <<" serviceDelayCycles="<<fi.serviceDelayCycles<<','<<fp.serviceDelayCycles<<','<<dp.serviceDelayCycles<<','<<da.serviceDelayCycles
                <<" responseBlockedCycles="<<fi.responseBlockedCycles<<','<<fp.responseBlockedCycles<<','<<dp.responseBlockedCycles<<','<<da.responseBlockedCycles
                <<" commitDisableCycles="<<commitDisableCycles
                <<" terminalCommits="<<terminalCommits<<'\n';return;
        }
    }
    throw std::runtime_error("finite root-switch cycle bound exceeded");
}
int main(int argc,char**argv){try{
    bool wrongFetch=false,wrongData=false;
    for(int i=1;i<argc;i++){std::string arg=argv[i];if(arg=="--wrong-fetch")wrongFetch=true;else if(arg=="--wrong-data")wrongData=true;else throw std::runtime_error("unknown root-switch argument");}
    run(false,wrongFetch,wrongData);run(true,wrongFetch,wrongData);
    std::cout<<"HYPERVISOR_ROOT_SWITCH_ALL_PASS cases=2\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
