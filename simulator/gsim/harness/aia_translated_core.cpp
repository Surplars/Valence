#include "AiaTranslatedCoreGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <initializer_list>
#include <map>
#include <stdexcept>
#include <type_traits>

static constexpr uint64_t BASE=0x80000000, HS=BASE+0x2000, MT=BASE+0x3000;
static constexpr uint64_t VA=0x40000000, DATA=VA+0x1000, ISR=VA+0x800, SPA_DATA=0x80201000;
static constexpr uint64_t GROOT=0x80010000, GMID=0x80014000, GPTLEAF=0x80015000, GDATALEAF=0x80016000;
static constexpr uint64_t VROOT=0x10000000, VMID=0x10001000, VLEAF=0x10002000, IRQ=1ULL<<63;
static uint32_t addi(unsigned d,unsigned s,int n){return(uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t shift(unsigned d,unsigned s,unsigned n){return n<<20|s<<15|1<<12|d<<7|0x13;}
static uint32_t csrw(unsigned c,unsigned r){return c<<20|r<<15|1<<12|0x73;}
static uint32_t csrr(unsigned c,unsigned r){return c<<20|2<<12|r<<7|0x73;}
static uint32_t ld(unsigned d,unsigned a,int n=0){return(uint32_t(n)&4095)<<20|a<<15|3<<12|d<<7|3;}
static uint32_t sd(unsigned s,unsigned a,int n=0){unsigned u=n&4095;return(u>>5)<<25|s<<20|a<<15|3<<12|(u&31)<<7|0x23;}
static uint32_t beq(unsigned a,unsigned b,int n){unsigned u=n&8191;return((u>>12)&1)<<31|((u>>5)&63)<<25|b<<20|a<<15|((u>>1)&15)<<8|((u>>11)&1)<<7|0x63;}
static int64_t sext(uint64_t v,unsigned w){return int64_t(v<<(64-w))>>(64-w);}

struct Memory {
    std::map<uint64_t,uint8_t> bytes;
    unsigned writes=0;
    void put(uint64_t a,uint64_t d,unsigned n){for(unsigned i=0;i<n;i++)bytes[a+i]=d>>(8*i);}
    uint64_t get(uint64_t a,unsigned n){uint64_t d=0;for(unsigned i=0;i<n;i++){auto p=bytes.find(a+i);if(p==bytes.end())throw std::runtime_error("unmapped physical memory "+std::to_string(a));d|=uint64_t(p->second)<<(8*i);}return d;}
    void pte(uint64_t a,uint64_t page,unsigned flags){put(a,(page>>12)<<10|flags,8);}
    void page(uint64_t a){for(unsigned i=0;i<4096;i++)bytes[a+i]=0;}
};
struct Program {
    std::map<uint64_t,uint32_t> code;uint64_t pc=BASE;
    unsigned guest;bool hs;
    Program(unsigned selected,bool host):guest(selected),hs(host){
        csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,MT);csr(0x105,HS);csr(0x205,ISR);
        csr(0x280,(8ULL<<60)|(VROOT>>12));csr(0x680,(8ULL<<60)|(GROOT>>12));
        csr(0x603,1024);csr(0x304,hs?4096:1024);csr(0x607,hs?1U<<guest:0);csr(0x200,2);
        csr(0x600,uint64_t(guest)<<12);csr(0x250,0x70);csr(0x251,1);csr(0x250,0xc0);csr(0x251,32);
        if(hs)csr(0x600,1<<12);
        csr(0x341,VA);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
        pc=VA;emit((2<<13)|(9<<7)|(7<<2)|1); // C.LI; all following PCs retain bit1.
        li(2,DATA);emit(ld(10,2));li(3,0x55);emit(sd(3,2,16));emit(ld(11,2,16));li(28,1);
        const uint64_t loop=pc;emit(ld(12,2));emit(addi(26,26,1));emit(beq(27,0,int(loop-pc)));
        emit(ld(13,2,24));li(3,0x66);emit(sd(3,2,32));emit(ld(14,2,32));li(31,99);emit(0x6f);
        pc=ISR;emit(csrr(0x142,16));emit(csrr(0x141,17));emit(csrr(0x15c,18));emit(csrw(0x15c,0));emit(csrr(0x15c,19));
        li(3,0xaa);emit(sd(3,2,24));emit(ld(20,2,24));li(27,1);emit(0x10200073);
        pc=HS;emit(csrr(0x142,16));emit(csrr(0x141,17));emit(csrr(0xe12,18));emit(csrr(0x25c,19));
        csr(0x600,(uint64_t(guest)<<12)|0x180);emit(csrr(0x25c,21));emit(csrw(0x25c,0));emit(csrr(0x25c,22));emit(csrr(0xe12,23));
        li(4,SPA_DATA+24);li(3,0xbb);emit(sd(3,4));emit(ld(20,4));li(27,1);emit(0x10200073);
        pc=MT;li(31,~0ULL);emit(0x6f);
    }
    void emit(uint32_t i){code[pc]=i;pc+=(i&3)==3?4:2;}
    void li(unsigned r,uint64_t n){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(n>>(8*b))&255;if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
    void csr(unsigned c,uint64_t value){li(1,value);emit(csrw(c,1));}
    void load(Memory&m){
        for(unsigned i=0;i<4;i++)m.page(BASE+4096*i);
        for(uint64_t page:std::initializer_list<uint64_t>{GROOT,GROOT+4096,GROOT+8192,GROOT+12288,GMID,GPTLEAF,GDATALEAF,0x80300000ULL,0x80301000ULL,0x80302000ULL,0x80200000ULL,SPA_DATA})m.page(page);
        m.pte(GROOT,GMID,1);m.pte(GMID+128*8,GPTLEAF,1);m.pte(GMID+256*8,GDATALEAF,1);
        for(unsigned i=0;i<3;i++)m.pte(GPTLEAF+i*8,0x80300000+i*4096,0xdf);
        m.pte(GDATALEAF,0x80200000,0xdf);m.pte(GDATALEAF+8,SPA_DATA,0xdf);
        m.pte(0x80300000+8,VMID,1);m.pte(0x80301000,VLEAF,1);
        m.pte(0x80302000,0x20000000,0xcb);m.pte(0x80302008,0x20001000,0xc7);
        m.put(SPA_DATA,0x1122334455667788ULL,8);
        for(auto [va,instruction]:code)m.put(va>=VA&&va<VA+4096?va-VA+0x80200000:va,instruction,(instruction&3)==3?4:2);
    }
};
struct Oracle {
    unsigned guest;bool hs,v=false,spv=false,spvp=false,pending=false;unsigned vgein=0,traps=0,returns=0;
    uint64_t r[32]{},pc=BASE,sepc=0,vsepc=0,scause=0,vscause=0,checks=0,commits=0,trapPc=0;
    std::map<uint64_t,uint64_t> memory{{SPA_DATA,0x1122334455667788ULL}};
    Oracle(unsigned file,bool host):guest(file),hs(host){}
    void check(uint64_t actual,uint64_t expected,const char*name){checks++;if(actual!=expected){std::cerr<<name<<" pc="<<std::hex<<pc<<" actual="<<actual<<" expected="<<expected<<std::dec<<'\n';throw std::runtime_error(name);}}
    uint64_t address(uint64_t va){if(!v)return va;if(va>=DATA&&va<DATA+4096)return SPA_DATA+va-DATA;throw std::runtime_error("unexpected guest data address");}
    uint64_t csr(unsigned c){switch(c){case 0x142:return v?vscause:scause;case 0x141:return v?vsepc:sepc;case 0xe12:return pending?1ULL<<guest:0;case 0x15c:case 0x25c:return pending&&vgein==guest?0x50005:0;default:return 0;}}
    void write(unsigned c,uint64_t value){if(c==0x600){vgein=(value>>12)&63;spv=value&128;spvp=value&256;}if((c==0x15c||c==0x25c)&&vgein==guest)pending=false;}
    void commit(uint64_t actualPc,uint32_t i,unsigned rd,uint64_t value,uint64_t actualNext,const Program&p){
        check(actualPc,pc,"retired PC");check(i,p.code.at(pc),"retired instruction");
        unsigned op=i&127,d=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,f=(i>>12)&7;
        uint64_t val=0,next=pc+((i&3)==3?4:2);bool writes=d!=0;
        if((i&3)!=3){d=(i>>7)&31;writes=d!=0;val=sext(((i>>12)&1)<<5|((i>>2)&31),6);}
        else if(op==0x13){if(f==0)val=r[a]+sext(i>>20,12);else if(f==1)val=r[a]<<((i>>20)&63);else throw std::runtime_error("unexpected OPIMM");}
        else if(op==3)val=memory.at(address(r[a]+sext(i>>20,12)));
        else if(op==0x23){writes=false;int64_t offset=sext((i>>25)<<5|((i>>7)&31),12);memory[address(r[a]+offset)]=r[b];}
        else if(op==0x63){writes=false;unsigned raw=((i>>31)&1)<<12|((i>>7)&1)<<11|((i>>25)&63)<<5|((i>>8)&15)<<1;if(r[a]==r[b])next=pc+sext(raw,13);}
        else if(op==0x6f){unsigned raw=((i>>31)&1)<<20|((i>>12)&255)<<12|((i>>20)&1)<<11|((i>>21)&1023)<<1;val=pc+4;next=pc+sext(raw,21);}
        else if(op==0x73&&f){unsigned c=i>>20;val=csr(c);if(f==1)write(c,r[a]);}
        else if(i==0x30200073){writes=false;next=VA;v=true;}
        else if(i==0x10200073){returns++;writes=false;if(v)next=vsepc;else{next=sepc;v=spv;spv=false;}}
        else throw std::runtime_error("unexpected retired instruction");
        check(actualNext,next,"independent next PC");if(writes){check(rd,d,"architectural RD");check(value,val,"independent retired value");r[d]=val;}pc=next;commits++;
    }
    void trap(uint64_t actualPc,uint64_t cause,uint64_t tval,uint64_t gpa,bool gp,bool ga,bool implicit){
        check(actualPc,pc,"precise IRQ PC");check(v,1,"interrupt begins in translated guest");check(traps++,0,"exactly one interrupt");
        check(cause,IRQ|(hs?12:10),"precise raw H interrupt cause");check(tval,0,"interrupt tval");
        check(gpa,0,"IRQ GPA metadata is zero");check(gp,0,"IRQ not guest page fault");check(ga,0,"IRQ has no GVA provenance");check(implicit,0,"IRQ not implicit PTE fault");
        trapPc=pc;check(pc&2,2,"compressed program EPC bit1 retained");
        if(hs){sepc=pc;scause=cause;spv=v;spvp=true;v=false;pc=HS;}
        else{vsepc=pc;vscause=IRQ|9;pc=ISR;}
    }
};
struct Pending {bool valid=false;uint64_t data=0;unsigned delay=0;uint64_t address=0;};

static uint64_t mmio(SAiaTranslatedCoreGsim&d,bool supervisor,unsigned offset,bool write,uint32_t value=0){
    bool accepted=false;
    for(unsigned cycle=0;cycle<100;cycle++){
#define DRIVE(N) d.set_io$$##N##$$request$$valid(!accepted);d.set_io$$##N##$$request$$bits$$address((supervisor?0x0c004000:0x0c000000)+offset);d.set_io$$##N##$$request$$bits$$write(write);d.set_io$$##N##$$request$$bits$$data(value);d.set_io$$##N##$$request$$bits$$size(2);d.set_io$$##N##$$request$$bits$$byteEnable(15)
        if(supervisor){DRIVE(supervisorRegisters);}else{DRIVE(machineRegisters);}
#undef DRIVE
        d.step();bool ready,valid,error;uint64_t data;
#define SAMPLE(N) ready=d.get_io$$##N##$$request$$ready();valid=d.get_io$$##N##$$response$$valid();error=d.get_io$$##N##$$response$$bits$$error();data=d.get_io$$##N##$$response$$bits$$data();if(valid)d.set_io$$##N##$$request$$valid(0)
        if(supervisor){SAMPLE(supervisorRegisters);}else{SAMPLE(machineRegisters);}
#undef SAMPLE
        if(d.get_io$$cpu$$commit0$$valid()||d.get_io$$cpu$$commit1$$valid()||d.get_io$$cpu$$trap$$valid())throw std::runtime_error("core progressed during disabled setup");
        if(!accepted&&ready)accepted=true;if(valid){if(!accepted||error)throw std::runtime_error("APLIC MMIO response");return data;}
    }throw std::runtime_error("APLIC MMIO timeout");
}
static void run(unsigned guest,bool hs,bool dataEdge,bool negative){
    Program p(guest,hs);Memory m;p.load(m);Oracle o(guest,hs);SAiaTranslatedCoreGsim d;
    static_assert(std::is_trivially_copyable_v<SAiaTranslatedCoreGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
    d.set_reset(1);d.step();d.step();d.set_reset(0);d.set_io$$cpu$$enable(0);d.set_io$$machineRegisters$$response$$ready(1);d.set_io$$supervisorRegisters$$response$$ready(1);d.step();
    mmio(d,false,4,true,0x400);mmio(d,true,4,true,4);mmio(d,true,0x3004,true,(guest<<12)|5);mmio(d,true,0x1edc,true,1);mmio(d,true,0,true,256);
    o.check(mmio(d,true,0x3004,false),(guest<<12)|5,"real APLIC target");
    Pending fi,fp,dp,da;unsigned fetched=0,fetchPtes=0,dataPtes=0,dataOps=0;
    unsigned stagePtes[4]{},postReturnFetchPtes=0,postReturnDataPtes=0;
    unsigned msis=0,responses=0,heldRequests=0,heldResponses=0,edgeCycle=0,msiCycle=0,trapCycle=0,quiet=0,edgeDelay=0;
    bool source=false,finishing=false,heldRequest=false,heldResponse=false;uint64_t oldAddress=0,oldData=0,oldResponse=0,edgePteAddress=0;bool oldError=false,oldWrite=false;unsigned oldSize=0,oldByteEnable=0;
    for(unsigned c=0;c<100000;c++){
        d.set_io$$cpu$$enable(!finishing);d.set_io$$cpu$$commitEnable(c%7!=3);
        if(!source&&o.r[28]==1&&(dataEdge?dp.valid:fp.valid)){source=true;edgeCycle=c;const Pending& held=dataEdge?dp:fp;edgePteAddress=held.address;edgeDelay=held.delay;}
        d.set_io$$sources(source?1:0);d.set_io$$allowMsi(source&&c>=edgeCycle+8&&c%7==0);d.set_io$$allowMsiResponse(msis&&c>=msiCycle+5&&c%11==0);
        auto advance=[](Pending&x){if(x.delay)x.delay--;};advance(fi);advance(fp);advance(dp);advance(da);
#define DRIVE(P,N) bool ready_##N=!P.valid&&c%5!=2;d.set_io$$cpu$$##N##$$request$$ready(ready_##N);d.set_io$$cpu$$##N##$$response$$valid(P.valid&&!P.delay);d.set_io$$cpu$$##N##$$response$$bits(P.data)
        DRIVE(fi,instruction);d.set_io$$cpu$$instruction$$responseError(0);d.set_io$$cpu$$instruction$$responsePageFault(0);
#undef DRIVE
#define PTEDRIVE(P,N) bool ready_##N=!P.valid&&c%5!=2;d.set_io$$cpu$$##N##$$request$$ready(ready_##N);d.set_io$$cpu$$##N##$$response$$valid(P.valid&&!P.delay);d.set_io$$cpu$$##N##$$response$$bits$$data(P.data);d.set_io$$cpu$$##N##$$response$$bits$$error(0)
        PTEDRIVE(fp,fetchPte);PTEDRIVE(dp,dataPte);
#undef PTEDRIVE
        bool ready_data=!da.valid&&c%5!=2;d.set_io$$cpu$$data$$request$$ready(ready_data);d.set_io$$cpu$$data$$response$$valid(da.valid&&!da.delay);d.set_io$$cpu$$data$$response$$bits$$data(da.data);d.set_io$$cpu$$data$$response$$bits$$error(0);d.set_io$$cpu$$data$$response$$bits$$pageFault(0);
        d.step();
#define DONE(P,N) if(P.valid&&!P.delay&&d.get_io$$cpu$$##N##$$response$$ready())P.valid=false
        DONE(fi,instruction);DONE(fp,fetchPte);DONE(dp,dataPte);DONE(da,data);
#undef DONE
#define REQUEST(P,N,SIZE,COUNT,KIND) if(d.get_io$$cpu$$##N##$$request$$valid()&&ready_##N){ \
        o.check(P.valid,0,"physical responder has capacity");uint64_t address=d.get_io$$cpu$$##N##$$request$$bits(); \
        if(KIND){bool g=address>=GROOT&&address<GROOT+0x7000,vs=address>=0x80300000&&address<0x80303000; \
            o.check(g||vs,1,"PTE access is SPA table page, without GPA or VA alias");o.check(address&7,0,"PTE alignment"); \
            stagePtes[2*((KIND)-1)+(vs?1:0)]++;if(o.returns){if((KIND)==1)postReturnFetchPtes++;else postReturnDataPtes++;}} \
        else{o.check((address>=BASE&&address<BASE+0x4000)||(address>=0x80200000&&address<0x80201000),1,"instruction read is a physical code page");} \
        P={true,m.get(address,SIZE),1+c%3,address};COUNT++;}
        REQUEST(fi,instruction,2,fetched,0);REQUEST(fp,fetchPte,8,fetchPtes,1);REQUEST(dp,dataPte,8,dataPtes,2);
#undef REQUEST
        if(d.get_io$$cpu$$data$$request$$valid()&&ready_data){
            uint64_t a=d.get_io$$cpu$$data$$request$$bits$$address(),base=a&~7ULL;bool write=d.get_io$$cpu$$data$$request$$bits$$write();
            o.check(da.valid,0,"one physical data owner");o.check(d.get_io$$cpu$$data$$request$$bits$$virtualized(),0,"physical offer strips virtual proof");o.check(a>=SPA_DATA&&a<SPA_DATA+4096,1,"actual translated data SPA");
            if(write){uint64_t value=d.get_io$$cpu$$data$$request$$bits$$data();unsigned mask=d.get_io$$cpu$$data$$request$$bits$$mask();for(unsigned b=0;b<8;b++)if(mask&(1<<b))m.put(base+b,value>>(8*b),1);m.writes++;}
            da={true,m.get(base,8),2+c%4};dataOps++;
        }
        o.check(d.get_io$$msiError(),0,"APLIC sticky MSI status");
        if(heldRequest){o.check(d.get_io$$msiValid(),1,"held APLIC MSI valid");o.check(d.get_io$$msiAddress(),oldAddress,"held APLIC destination");o.check(d.get_io$$msiData(),oldData,"held APLIC payload");o.check(d.get_io$$msiWrite(),oldWrite,"held APLIC write");o.check(d.get_io$$msiSize(),oldSize,"held APLIC size");o.check(d.get_io$$msiByteEnable(),oldByteEnable,"held APLIC byte enable");}
        heldRequest=d.get_io$$msiValid()&&!d.get_io$$msiFire();oldAddress=d.get_io$$msiAddress();oldData=d.get_io$$msiData();oldWrite=d.get_io$$msiWrite();oldSize=d.get_io$$msiSize();oldByteEnable=d.get_io$$msiByteEnable();if(heldRequest)heldRequests++;
        if(d.get_io$$msiFire()){o.check(d.get_io$$msiAddress(),0x28000000ULL+uint64_t(guest+(negative?1:0))*4096,"independent MSI guest destination");o.check(d.get_io$$msiData(),5,"actual MSI identity");o.check(d.get_io$$msiWrite(),1,"MSI is a write");o.check(d.get_io$$msiSize(),2,"MSI is 32-bit");o.check(d.get_io$$msiByteEnable(),15,"MSI byte enable");o.check(msis++,0,"one actual MSI");msiCycle=c;o.pending=true;}
        if(heldResponse){o.check(d.get_io$$msiResponseValid(),1,"held real MSI response valid");o.check(d.get_io$$msiResponseData(),oldResponse,"held real MSI response data");o.check(d.get_io$$msiResponseError(),oldError,"held real MSI response error");}
        heldResponse=d.get_io$$msiResponseValid()&&!d.get_io$$msiResponseFire();oldResponse=d.get_io$$msiResponseData();oldError=d.get_io$$msiResponseError();if(heldResponse)heldResponses++;
        if(d.get_io$$msiResponseFire()){o.check(d.get_io$$msiResponseError(),0,"MSI response success");responses++;}
#define COMMIT(N) if(d.get_io$$cpu$$commit##N##$$valid())o.commit(d.get_io$$cpu$$commit##N##$$bits$$pc(),d.get_io$$cpu$$commit##N##$$bits$$instruction(),d.get_io$$cpu$$commit##N##$$bits$$rd(),d.get_io$$cpu$$commit##N##$$bits$$data(),d.get_io$$cpu$$commit##N##$$bits$$nextPc(),p)
        if(finishing){o.check(d.get_io$$cpu$$commit0$$valid()||d.get_io$$cpu$$commit1$$valid(),0,"no retirement after disabled success");o.check(d.get_io$$cpu$$trap$$valid(),0,"no trap after disabled success");}
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$cpu$$trap$$valid())trapCycle=c;
        if(d.get_io$$cpu$$trap$$valid())o.trap(d.get_io$$cpu$$trap$$bits$$pc(),d.get_io$$cpu$$trap$$bits$$cause(),d.get_io$$cpu$$trap$$bits$$tval(),d.get_io$$cpu$$trap$$bits$$guestFault$$guestPhysicalAddress(),d.get_io$$cpu$$trap$$bits$$guestFault$$guestPageFault(),d.get_io$$cpu$$trap$$bits$$guestFault$$guestAddress(),d.get_io$$cpu$$trap$$bits$$guestFault$$implicitPte());
        if(o.r[31]==~0ULL)throw std::runtime_error("unexpected machine trap");
        if(!finishing&&o.r[31]==99){
            o.check(o.traps,1,"one precise translated-guest interrupt");o.check(o.returns,1,"one retired SRET");o.check(d.get_io$$cpu$$virtualized(),1,"returned guest virtualization state");o.check(msis,1,"one source MSI");o.check(responses,1,"one actual response");o.check(o.pending,0,"claim clears pending");
            o.check(o.r[9],7,"C instruction retired");o.check(o.r[10],0x1122334455667788ULL,"guest initial load");o.check(o.r[11],0x55,"guest pre-IRQ store/load");o.check(o.r[13],hs?0xbb:0xaa,"post-return translated load sees handler store");o.check(o.r[14],0x66,"post-return guest store/load");
            o.check(o.r[16],IRQ|(hs?12:9),"retired handler cause");o.check(o.r[17],o.trapPc,"retired precise EPC");o.check(o.r[20],hs?0xbb:0xaa,"handler readback");
            if(hs){o.check(o.r[18],1ULL<<guest,"HS hgeip mapping");o.check(o.r[19],0,"non-selected guest file empty");o.check(o.r[21],0x50005,"VGEIN switch selects real guest");o.check(o.r[22],0,"claimed guest TOPEI zero");o.check(o.r[23],0,"claim clears hgeip");}
            else{o.check(o.r[18],0x50005,"VS real guest TOPEI");o.check(o.r[19],0,"VS postclaim TOPEI");}
            o.check(m.get(SPA_DATA+16,8),0x55,"physical pre-IRQ store");o.check(m.get(SPA_DATA+24,8),hs?0xbb:0xaa,"physical handler store");o.check(m.get(SPA_DATA+32,8),0x66,"physical post-return store");o.check(m.writes,3,"exact physical store count");
            for(unsigned n:stagePtes)if(!n)throw std::runtime_error("both translation stages must read actual PTEs on both ports");
            if(!postReturnFetchPtes||!postReturnDataPtes)throw std::runtime_error("post-return nested fetch/data not exercised");
            if(!source||!fetchPtes||!dataPtes||!heldRequests||!heldResponses)throw std::runtime_error("required nested/IRQ/stall coverage absent");finishing=true;
        }
        if(finishing){
            bool idle=!fi.valid&&!fp.valid&&!dp.valid&&!da.valid&&!d.get_io$$cpu$$instruction$$request$$valid()&&!d.get_io$$cpu$$fetchPte$$request$$valid()&&!d.get_io$$cpu$$dataPte$$request$$valid()&&!d.get_io$$cpu$$data$$request$$valid();quiet=idle?quiet+1:0;
            if(quiet==6){std::cout<<"AIA_GSTAGE_CORE_PASS guest="<<guest<<" route="<<(hs?"HS":"VS")<<" edge_during="<<(dataEdge?"data_pte":"fetch_pte")<<" cycles="<<c<<" commits="<<o.commits<<" traps="<<o.traps<<" fetchPtes="<<fetchPtes<<" dataPtes="<<dataPtes<<" parcels="<<fetched<<" dataOps="<<dataOps<<" checks="<<o.checks<<" held_request="<<heldRequests<<" held_response="<<heldResponses<<" g_fetch_pte="<<stagePtes[0]<<" vs_fetch_pte="<<stagePtes[1]<<" g_data_pte="<<stagePtes[2]<<" vs_data_pte="<<stagePtes[3]<<" post_return_fetch_pte="<<postReturnFetchPtes<<" post_return_data_pte="<<postReturnDataPtes<<" source_cycle="<<edgeCycle<<" msi_cycle="<<msiCycle<<" trap_cycle="<<trapCycle<<" edge_pte_spa="<<std::hex<<edgePteAddress<<std::dec<<" edge_response_delay="<<edgeDelay<<"\n";return;}
        }
    }throw std::runtime_error("translated AIA core timeout");
}
int main(int argc,char**argv){try{run(1,false,true,argc>1);run(3,false,false,false);run(2,true,false,false);std::cout<<"AIA_GSTAGE_ALL_CHAINS_PASS scenarios=3\n";return 0;}catch(const std::exception&e){std::cerr<<"AIA_GSTAGE_CORE_FAIL "<<e.what()<<'\n';return 1;}}
