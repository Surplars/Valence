#include "HypervisorPlatformGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <initializer_list>
#include <map>
#include <stdexcept>
#include <type_traits>
#include <deque>
#include <memory>
#include <array>

static constexpr uint64_t BASE=0x80000000, HS=BASE+0x2000, MT=BASE+0x3000;
static constexpr uint64_t VA=0x40000000, DATA=VA+0x1000, ISR=VA+0x800, SPA_DATA=0x8020b000;
static constexpr uint64_t GROOT=0x80200000, GMID=0x80204000, GPTLEAF=0x80205000, GDATALEAF=0x80206000;
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
        mmio(0x0c000004,0x400);mmio(0x0c004004,4);mmio(0x0c007004,(guest<<12)|5);
        mmio(0x0c005edc,1);mmio(0x0c004000,256);
        csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,MT);csr(0x105,HS);csr(0x205,ISR);
        csr(0x280,(8ULL<<60)|(VROOT>>12));csr(0x680,(8ULL<<60)|(GROOT>>12));
        csr(0x603,1024);csr(0x304,hs?4096:1024);csr(0x607,hs?1U<<guest:0);csr(0x200,2);
        csr(0x600,uint64_t(guest)<<12);csr(0x250,0x70);csr(0x251,1);csr(0x250,0xc0);csr(0x251,32);
        if(hs)csr(0x600,1<<12);
        emit(0x100f);csr(0x341,VA);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
        pc=VA;emit((2<<13)|(9<<7)|(7<<2)|1); // C.LI; all following PCs retain bit1.
        li(2,DATA);emit(ld(10,2));li(3,0x55);emit(sd(3,2,16));emit(ld(11,2,16));emit(0x100f);li(28,1);
        const uint64_t loop=pc;emit(ld(12,2));emit(addi(26,26,1));emit(beq(27,0,int(loop-pc)));
        emit(ld(13,2,24));li(3,0x66);emit(sd(3,2,32));emit(ld(14,2,32));emit(0x100f);li(31,99);emit(0x6f);
        pc=ISR;emit(csrr(0x142,16));emit(csrr(0x141,17));emit(csrr(0x15c,18));emit(csrw(0x15c,0));emit(csrr(0x15c,19));
        li(3,0xaa);emit(sd(3,2,24));emit(ld(20,2,24));li(27,1);emit(0x10200073);
        pc=HS;emit(csrr(0x142,16));emit(csrr(0x141,17));emit(csrr(0xe12,18));emit(csrr(0x25c,19));
        csr(0x600,(uint64_t(guest)<<12)|0x180);emit(csrr(0x25c,21));emit(csrw(0x25c,0));emit(csrr(0x25c,22));emit(csrr(0xe12,23));
        li(4,SPA_DATA+24);li(3,0xbb);emit(sd(3,4));emit(ld(20,4));li(27,1);emit(0x10200073);
        pc=MT;li(31,~0ULL);emit(0x6f);
    }
    void emit(uint32_t i){code[pc]=i;pc+=(i&3)==3?4:2;}
    void li(unsigned r,uint64_t n){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(n>>(8*b))&255;if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
    void mmio(uint64_t a,uint32_t d){li(4,a);li(5,d);emit(5<<20|4<<15|2<<12|0x23);}
    void csr(unsigned c,uint64_t value){li(1,value);emit(csrw(c,1));}
    void load(Memory&m){
        for(unsigned i=0;i<4;i++)m.page(BASE+4096*i);
        for(unsigned i=0;i<16;i++)m.page(0x80200000+i*4096);
        m.pte(GROOT,GMID,1);m.pte(GMID+128*8,GPTLEAF,1);m.pte(GMID+256*8,GDATALEAF,1);
        for(unsigned i=0;i<3;i++)m.pte(GPTLEAF+i*8,0x80207000+i*4096,0xdf);
        m.pte(GDATALEAF,0x8020a000,0xdf);m.pte(GDATALEAF+8,SPA_DATA,0xdf);
        m.pte(0x80207000+8,VMID,1);m.pte(0x80208000,VLEAF,1);
        m.pte(0x80209000,0x20000000,0xcb);m.pte(0x80209008,0x20001000,0xc7);
        m.put(SPA_DATA,0x1122334455667788ULL,8);
        for(auto [va,instruction]:code)m.put(va>=VA&&va<VA+4096?va-VA+0x8020a000:va,instruction,(instruction&3)==3?4:2);
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
    void commit(uint64_t actualPc,uint32_t i,unsigned rd,uint64_t value,uint64_t actualNext,bool actualWrites,const Program&p){
        check(actualPc,pc,"retired PC");check(i,p.code.at(pc),"retired instruction");
        unsigned op=i&127,d=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,f=(i>>12)&7;
        uint64_t val=0,next=pc+((i&3)==3?4:2);bool writes=d!=0;
        if((i&3)!=3){d=(i>>7)&31;writes=d!=0;val=sext(((i>>12)&1)<<5|((i>>2)&31),6);}
        else if(op==0x13){if(f==0)val=r[a]+sext(i>>20,12);else if(f==1)val=r[a]<<((i>>20)&63);else throw std::runtime_error("unexpected OPIMM");}
        else if(op==3)val=memory.at(address(r[a]+sext(i>>20,12)));
        else if(op==0x23){writes=false;int64_t offset=sext((i>>25)<<5|((i>>7)&31),12);memory[address(r[a]+offset)]=r[b];}
        else if(op==0x63){writes=false;unsigned raw=((i>>31)&1)<<12|((i>>7)&1)<<11|((i>>25)&63)<<5|((i>>8)&15)<<1;if(r[a]==r[b])next=pc+sext(raw,13);}
        else if(op==0x6f){unsigned raw=((i>>31)&1)<<20|((i>>12)&255)<<12|((i>>20)&1)<<11|((i>>21)&1023)<<1;val=pc+4;next=pc+sext(raw,21);}
        else if(i==0x100f){writes=false;}
        else if(op==0x73&&f){unsigned c=i>>20;val=csr(c);if(f==1)write(c,r[a]);}
        else if(i==0x30200073){writes=false;next=VA;v=true;}
        else if(i==0x10200073){returns++;writes=false;if(v)next=vsepc;else{next=sepc;v=spv;spv=false;}}
        else throw std::runtime_error("unexpected retired instruction");
        check(actualWrites,writes,"retirement write-enable");check(actualNext,next,"independent next PC");if(writes){check(rd,d,"architectural RD");check(value,val,"independent retired value");r[d]=val;}pc=next;commits++;
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
struct Request {
    uint64_t address=0,data=0;unsigned owner=0,size=0,mask=0;
    bool valid=false,clear=false,write=false,atomic=false,lookup=false,virtualized=false,prechecked=false,uncached=false;
    uint32_t epoch=0;bool prefetch=false;
    bool operator==(const Request&)const=default;
};
struct Response {uint64_t data=0;unsigned owner=0;bool valid=false,clear=false,error=false,pageFault=false;bool operator==(const Response&)const=default;};
static Request request(SHypervisorPlatformGsim&d,unsigned lane){Request r;
#define R(N) r.valid=d.get_io$$scalar##N##Request$$valid();r.owner=d.get_io$$scalar##N##Request$$bits$$owner();r.clear=d.get_io$$scalar##N##Request$$bits$$clearReservation();r.lookup=d.get_io$$scalar##N##Request$$bits$$needsCoherenceLookup();r.address=d.get_io$$scalar##N##Request$$bits$$memory$$address();r.data=d.get_io$$scalar##N##Request$$bits$$memory$$data();r.size=d.get_io$$scalar##N##Request$$bits$$memory$$size();r.mask=d.get_io$$scalar##N##Request$$bits$$memory$$mask();r.write=d.get_io$$scalar##N##Request$$bits$$memory$$write();r.atomic=d.get_io$$scalar##N##Request$$bits$$memory$$atomic();r.virtualized=d.get_io$$scalar##N##Request$$bits$$memory$$virtualized();r.prechecked=d.get_io$$scalar##N##Request$$bits$$memory$$precheckedLoad();r.epoch=d.get_io$$scalar##N##Request$$bits$$memory$$translationEpoch();r.prefetch=d.get_io$$scalar##N##Request$$bits$$memory$$prefetchNextAllowed();r.uncached=d.get_io$$scalar##N##Request$$bits$$memory$$uncached()
    if(lane){R(1);}else{R(0);}
#undef R
    if(r.clear){r.address=r.data=r.size=r.mask=r.epoch=0;r.write=r.atomic=r.virtualized=r.prechecked=r.prefetch=r.uncached=false;}
    return r;
}
static Response response(SHypervisorPlatformGsim&d,unsigned lane){Response r;
#define R(N) r.valid=d.get_io$$scalar##N##Response$$valid();r.owner=d.get_io$$scalar##N##Response$$bits$$owner();r.clear=d.get_io$$scalar##N##Response$$bits$$clearReservation();r.data=d.get_io$$scalar##N##Response$$bits$$memory$$data();r.error=d.get_io$$scalar##N##Response$$bits$$memory$$error();r.pageFault=d.get_io$$scalar##N##Response$$bits$$memory$$pageFault()
    if(lane){R(1);}else{R(0);}
#undef R
    return r;
}
static void initialize(SHypervisorPlatformGsim&d,Memory&m){
    d.set_io$$enable(0);d.set_io$$commitEnable(0);d.set_io$$sources(0);d.set_io$$program$$valid(0);d.set_io$$ramProgram$$valid(0);
    d.set_io$$allowRequest(3);d.set_io$$allowResponse(3);d.set_io$$allowMsi(1);d.set_io$$allowMsiResponse(1);d.set_io$$allowDrain(1);
    d.set_reset(1);d.step();d.step();d.step();d.set_reset(0);
    for(unsigned i=0;i<8192;i++){
        d.set_io$$program$$valid(i<4096);d.set_io$$program$$bits$$index(i&4095);d.set_io$$program$$bits$$data(i<4096?m.get(BASE+i*4,4):0);
        d.set_io$$ramProgram$$valid(1);d.set_io$$ramProgram$$bits$$index(i);d.set_io$$ramProgram$$bits$$data(m.get(0x80200000+i*8,8));d.step();
        if(d.get_io$$commit0$$valid()||d.get_io$$commit1$$valid()||d.get_io$$trap$$valid()||request(d,0).valid||request(d,1).valid)throw std::runtime_error("cold setup produced architectural or memory work");
    }
    d.set_io$$program$$valid(0);d.set_io$$ramProgram$$valid(0);d.step();
}
static void run(unsigned guest,bool hs,bool negative,bool interruptReset){
    Program p(guest,hs);Memory m;p.load(m);Oracle o(guest,hs);
    auto allocated=std::make_unique<SHypervisorPlatformGsim>();auto&d=*allocated;
    static_assert(std::is_trivially_copyable_v<SHypervisorPlatformGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();initialize(d,m);
    std::deque<Request> owners[2];Request heldReq[2];Response heldRsp[2];bool holdQ[2]{},holdR[2]{};
    unsigned nextOwner[2]{},requests[2]{},replies[2]{},heldRequests[2]{},heldResponses[2]{};
    unsigned msis=0,msiResponses=0,msiHeld=0,msiResponseHeld=0,clears=0,stores=0,mmio=0,pteReads=0,parcels=0,offsets=0;
    unsigned fences=0,statuses=0,drains=0,drainHeld=0,drainSeenCycle=0,edgeCycle=0,msiCycle=0;
    bool source=false,resetDone=false,heldMsi=false,heldMsiResponse=false,heldDrain=false;unsigned lastDrain=0;
    std::array<uint64_t,5> lastMsi{};uint64_t lastMsiResponse=0;unsigned epoch=0;
    const std::array<std::pair<uint64_t,uint64_t>,5> config{{{0x0c000004,0x400},{0x0c004004,4},{0x0c007004,(guest<<12)|5},{0x0c005edc,1},{0x0c004000,256}}};
    for(unsigned c=0;c<200000;c++){
        d.set_io$$enable(1);d.set_io$$commitEnable(c%11!=3);
        if(!source&&o.r[28]==1&&!owners[1].empty()){source=true;edgeCycle=c;}
        d.set_io$$sources(source?1:0);
        d.set_io$$allowRequest((c%5==1?0:1)|(c%7==2?0:2));d.set_io$$allowResponse((c%7<3?0:1)|(c%9<4?0:2));
        d.set_io$$allowMsi(!source||(c>=edgeCycle+8&&c%7==0));d.set_io$$allowMsiResponse(msis&&c>=msiCycle+5&&c%11==0);
        d.set_io$$allowDrain(drainSeenCycle&&c>=drainSeenCycle+7);
        d.step();
        for(unsigned lane=0;lane<2;lane++){
            Request q=request(d,lane);Response r=response(d,lane);bool qr=(d.get_io$$scalarRequestReady()>>lane)&1,rr=(d.get_io$$scalarResponseReady()>>lane)&1;
            if(holdQ[lane])o.check(q==heldReq[lane],1,"scalar request held stable");
            if(holdR[lane])o.check(r==heldRsp[lane],1,"scalar response held stable");
            holdQ[lane]=q.valid&&!qr;holdR[lane]=r.valid&&!rr;heldReq[lane]=q;heldRsp[lane]=r;
            heldRequests[lane]+=holdQ[lane];heldResponses[lane]+=holdR[lane];
            if(r.valid&&rr){
                o.check(!owners[lane].empty(),1,"real scalar response owner");Request prior=owners[lane].front();owners[lane].pop_front();
                o.check(r.owner,prior.owner,"transport owner identity");o.check(r.clear,prior.clear,"transport clear identity");o.check(r.error,0,"physical fabric access success");o.check(r.pageFault,0,"fabric cannot invent page fault");
                if(!prior.clear&&!prior.write)o.check(r.data,m.get(prior.address&~7ULL,8),"independent physical read beat");
                replies[lane]++;
            }
            if(q.valid&&qr){
                o.check(q.owner,nextOwner[lane]++&15,"monotonic transport owner");o.check(q.lookup,1,"uncached client coherence lookup");
                if(q.clear){clears++;o.check(lane,0,"clear remains data lane");o.check(owners[0].empty()&&owners[1].empty(),1,"clear waits for both older scalar lanes");}
                else{
                    o.check(q.virtualized||q.prechecked||q.epoch||q.prefetch||q.atomic,0,"virtual authorization consumed before fabric");
                    if(q.write){
                        o.check(lane,0,"read-only fetch/PTE lane");
                        if(q.address>=0x0c000000&&q.address<0x0c008000){o.check(mmio<config.size(),1,"APLIC writes bounded");o.check(q.address,config.at(mmio).first,"CPU-configured APLIC address");o.check(q.data>>((q.address&7)*8),config.at(mmio).second,"CPU-configured APLIC data");o.check(q.size,2,"APLIC SW width");o.check(q.mask,15U<<(q.address&7),"APLIC SW byte lanes");o.check(q.uncached,1,"MMIO uncached");mmio++;}
                        else{
                            const uint64_t expected=stores==0?0x55:stores==1?(hs?0xbb:0xaa):0x66;
                            o.check(q.address,SPA_DATA+(stores==0?16:stores==1?24:32),"independent platform store address");
                            o.check(q.data,expected+(negative?1:0),"independent platform store value");
                            o.check(q.mask,255,"RAM store full mask");m.put(q.address,q.data,8);stores++;
                        }
                    }else if(lane==1){
                        if(q.size==1){parcels++;offsets|=1U<<(q.address&7);o.check(q.mask,3U<<(q.address&7),"fetch parcel physical byte mask");}
                        else{o.check(q.size,3,"PTE width");o.check(q.address>=GROOT&&q.address<0x8020a000,1,"PTE only real RAM tables");o.check(q.mask,255,"PTE full beat mask");pteReads++;}
                    }
                }
                owners[lane].push_back(q);requests[lane]++;
            }
        }
        if(d.get_io$$msiRequest$$valid()){
            std::array<uint64_t,5> now{d.get_io$$msiRequest$$bits$$address(),d.get_io$$msiRequest$$bits$$data(),d.get_io$$msiRequest$$bits$$size(),d.get_io$$msiRequest$$bits$$byteEnable(),d.get_io$$msiRequest$$bits$$write()};
            if(heldMsi)o.check(now==lastMsi,1,"MSI offer held stable");heldMsi=!d.get_io$$msiRequestReady();lastMsi=now;msiHeld+=heldMsi;
            if(!heldMsi){o.check(now[0],0x28000000+4096*guest,"actual APLIC guest destination");o.check(now[1],5,"actual APLIC identity");o.check(now[2],2,"MSI width");o.check(now[3],15,"MSI bytes");o.check(now[4],1,"MSI write");o.check(msis++,0,"exactly one real MSI");o.pending=true;msiCycle=c;}
        }else{o.check(heldMsi,0,"MSI cannot withdraw");}
        if(d.get_io$$msiResponse$$valid()){
            o.check(d.get_io$$msiResponse$$bits$$error(),0,"actual IMSIC reply");
            if(heldMsiResponse)o.check(d.get_io$$msiResponse$$bits$$data(),lastMsiResponse,"IMSIC reply held stable");
            lastMsiResponse=d.get_io$$msiResponse$$bits$$data();heldMsiResponse=!d.get_io$$msiResponseReady();msiResponseHeld+=heldMsiResponse;
            if(!heldMsiResponse){msiResponses++;}
        }else{o.check(heldMsiResponse,0,"IMSIC cannot withdraw reply");}
        if(d.get_io$$maintenance$$valid()&&d.get_io$$maintenanceReady()){
            o.check(d.get_io$$maintenance$$bits$$privateOwnersDrained(),1,"real private owner drain");o.check(d.get_io$$maintenance$$bits$$dirtyWritebackCompleted(),1,"cacheless dirty completion");o.check(d.get_io$$maintenance$$bits$$fetchQuiescent(),1,"real assembler drain");
            o.check(owners[0].empty()&&owners[1].empty(),1,"native responses before maintenance");o.check(d.get_io$$maintenance$$bits$$epoch(),++epoch,"new fence epoch");statuses++;
        }
        if(heldDrain){o.check(d.get_io$$drained$$valid(),1,"drained response cannot withdraw");o.check(d.get_io$$drained$$bits(),lastDrain,"drained response held epoch");}
        heldDrain=d.get_io$$drained$$valid()&&!d.get_io$$drainedReady();lastDrain=d.get_io$$drained$$bits();
        if(d.get_io$$drained$$valid()){
            if(!drainSeenCycle)drainSeenCycle=c;
            o.check(d.get_io$$drained$$bits(),epoch,"matching Home drain epoch");
            if(d.get_io$$drainedReady()){drains++;drainSeenCycle=0;}else drainHeld++;
        }
#define COMMIT(N) if(d.get_io$$commit##N##$$valid()){auto ins=d.get_io$$commit##N##$$bits$$instruction();if(ins==0x100f)o.check(drains,++fences,"FENCE.I only after real fabric drain");o.commit(d.get_io$$commit##N##$$bits$$pc(),ins,d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),d.get_io$$commit##N##$$bits$$writesRd(),p);}
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid())o.trap(d.get_io$$trap$$bits$$pc(),d.get_io$$trap$$bits$$cause(),d.get_io$$trap$$bits$$tval(),d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),d.get_io$$trap$$bits$$guestFault$$guestPageFault(),d.get_io$$trap$$bits$$guestFault$$guestAddress(),d.get_io$$trap$$bits$$guestFault$$implicitPte());
        o.check(d.get_io$$msiError(),0,"APLIC completed MSI success");
        if(interruptReset&&!resetDone&&source&&!owners[1].empty()){
            // Whole-DUT cold reset abandons both ends of the same owner graph.
            // Never reset just the CPU or reuse a pre-reset response queue.
            resetDone=true;Memory fresh;p.load(fresh);m=fresh;initialize(d,m);o=Oracle(guest,hs);
            for(unsigned i=0;i<2;i++){owners[i].clear();holdQ[i]=holdR[i]=false;nextOwner[i]=requests[i]=replies[i]=heldRequests[i]=heldResponses[i]=0;}
            msis=msiResponses=msiHeld=msiResponseHeld=clears=stores=mmio=pteReads=parcels=offsets=fences=statuses=drains=drainHeld=drainSeenCycle=edgeCycle=msiCycle=epoch=0;
            source=heldMsi=heldMsiResponse=heldDrain=false;lastDrain=0;continue;
        }
        if(o.r[31]==99&&clears==1&&msiResponses==1&&owners[0].empty()){
            o.check(o.traps,1,"single precise IRQ");o.check(o.returns,1,"one SRET");o.check(stores,3,"three real RAM stores");o.check(mmio,5,"CPU configures all APLIC registers");o.check(o.r[11],0x55,"guest store before IRQ");o.check(o.r[13],hs?0xbb:0xaa,"handler store visible after SRET");o.check(o.r[14],0x66,"guest store after SRET");o.check(o.pending,0,"IMSIC claimed by CPU");o.check(fences,3,"host and guest FENCE.I count");o.check(statuses,3,"three real platform drain requests");o.check(drains,3,"three real Home drain responses");o.check(offsets,0x55,"all four physical halfword lanes");o.check(pteReads>100&&parcels>100,1,"actual nested translation and instruction traffic");o.check(msiHeld>0&&msiResponseHeld>0&&drainHeld>=21,1,"MSI and drain stall coverage");o.check(heldRequests[0]>0&&heldRequests[1]>0&&heldResponses[0]>0&&heldResponses[1]>0,1,"both scalar lane backpressure");o.check(!interruptReset||resetDone,1,"cold reset with live owner exercised");
            std::cout<<"PLATFORM_CHAIN_PASS guest="<<guest<<" hs="<<hs<<" coldRestart="<<interruptReset<<" cycles="<<c+1<<" commits="<<o.commits<<" checks="<<o.checks<<" ptes="<<pteReads<<" parcels="<<parcels<<" requests="<<requests[0]<<","<<requests[1]<<" responses="<<replies[0]<<","<<replies[1]<<" heldRequests="<<heldRequests[0]<<","<<heldRequests[1]<<" heldResponses="<<heldResponses[0]<<","<<heldResponses[1]<<" fences="<<fences<<" drainHeld="<<drainHeld<<" msiHeld="<<msiHeld<<","<<msiResponseHeld<<'\n';return;
        }
    }
    throw std::runtime_error("platform timeout pc="+std::to_string(o.pc));
}
int main(int argc,char**argv){try{bool negative=argc>1;run(1,false,negative,false);if(negative)throw std::runtime_error("negative control was not rejected");run(3,false,false,false);run(2,true,false,false);run(1,false,false,true);std::cout<<"HYPERVISOR_PLATFORM_PASS\n";return 0;}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
