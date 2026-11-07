// RV64 guest A qualification. Transport observation helpers are adapted from the
// platform harness; architectural and physical expectations are built independently.
#include "GuestAtomicsPlatformGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <vector>
#include <stdexcept>
#include <type_traits>
#include <deque>
#include <memory>
#include <string>
static constexpr uint64_t BASE=0x80000000, HS=BASE+0x2000, MT=BASE+0x3000;
static constexpr uint64_t VA=0x40000000, DATA=VA+0x1000, ALIAS=VA+0x2000, OTHER=VA+0x3000;
static constexpr uint64_t SPA=0x8020b000, SPA2=0x8020c000;
static constexpr uint64_t GROOT=0x80200000, GMID=0x80204000, GPTLEAF=0x80205000, GDATALEAF=0x80206000;
static constexpr uint64_t VROOT=0x10000000, VMID=0x10001000, VLEAF=0x10002000;
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
struct Request {
    uint64_t address=0,data=0;unsigned owner=0,size=0,mask=0,operation=0;
    bool valid=false,clear=false,write=false,atomic=false,lookup=false,virtualized=false,prechecked=false,uncached=false;
    uint32_t epoch=0;bool prefetch=false;
    bool operator==(const Request&)const=default;
};
struct Response {uint64_t data=0;unsigned owner=0;bool valid=false,clear=false,error=false,pageFault=false;bool operator==(const Response&)const=default;};
static Request request(SGuestAtomicsPlatformGsim&d,unsigned lane){Request r;
#define R(N) r.valid=d.get_io$$scalar##N##Request$$valid();r.owner=d.get_io$$scalar##N##Request$$bits$$owner();r.clear=d.get_io$$scalar##N##Request$$bits$$clearReservation();r.lookup=d.get_io$$scalar##N##Request$$bits$$needsCoherenceLookup();r.address=d.get_io$$scalar##N##Request$$bits$$memory$$address();r.data=d.get_io$$scalar##N##Request$$bits$$memory$$data();r.size=d.get_io$$scalar##N##Request$$bits$$memory$$size();r.mask=d.get_io$$scalar##N##Request$$bits$$memory$$mask();r.write=d.get_io$$scalar##N##Request$$bits$$memory$$write();r.atomic=d.get_io$$scalar##N##Request$$bits$$memory$$atomic();r.operation=d.get_io$$scalar##N##Request$$bits$$memory$$atomicOp();r.virtualized=d.get_io$$scalar##N##Request$$bits$$memory$$virtualized();r.prechecked=d.get_io$$scalar##N##Request$$bits$$memory$$precheckedLoad();r.epoch=d.get_io$$scalar##N##Request$$bits$$memory$$translationEpoch();r.prefetch=d.get_io$$scalar##N##Request$$bits$$memory$$prefetchNextAllowed();r.uncached=d.get_io$$scalar##N##Request$$bits$$memory$$uncached()
    if(lane){R(1);}else{R(0);}
#undef R
    if(r.clear){r.address=r.data=r.size=r.mask=r.epoch=r.operation=0;r.write=r.atomic=r.virtualized=r.prechecked=r.prefetch=r.uncached=false;}
    return r;
}
static Response response(SGuestAtomicsPlatformGsim&d,unsigned lane){Response r;
#define R(N) r.valid=d.get_io$$scalar##N##Response$$valid();r.owner=d.get_io$$scalar##N##Response$$bits$$owner();r.clear=d.get_io$$scalar##N##Response$$bits$$clearReservation();r.data=d.get_io$$scalar##N##Response$$bits$$memory$$data();r.error=d.get_io$$scalar##N##Response$$bits$$memory$$error();r.pageFault=d.get_io$$scalar##N##Response$$bits$$memory$$pageFault()
    if(lane){R(1);}else{R(0);}
#undef R
    return r;
}
static void initialize(SGuestAtomicsPlatformGsim&d,Memory&m){
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
// Encodings and expectations below are independent RV64A architectural rules.
static uint32_t amo(unsigned op,unsigned size,unsigned rd,unsigned rs1,unsigned rs2,unsigned order=0){
    return op<<27|order<<25|rs2<<20|rs1<<15|size<<12|rd<<7|0x2f;
}
enum Case { Clean, Ecall, VsDenied, GDenied, RomDenied, MmioDenied, Misaligned };
static const char* names[]={"clean","ecall","vs_write_denied","g_write_denied","rom_lr_denied","mmio_amo_denied","misaligned"};
struct Program {
    Case kind;std::map<uint64_t,uint32_t> code;uint64_t pc=BASE,faultPc=0,resume=0,target=DATA;
    explicit Program(Case k):kind(k){
        csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,MT);csr(0x105,HS);
        csr(0x304,0);csr(0x303,0);csr(0x604,0);csr(0x603,0);csr(0x602,0);
        csr(0x302,(1ULL<<5)|(1ULL<<6)|(1ULL<<7)|(1ULL<<10)|(1ULL<<15)|(1ULL<<23));
        csr(0x280,(8ULL<<60)|(VROOT>>12));csr(0x680,(8ULL<<60)|(GROOT>>12));csr(0x600,0);
        csr(0x341,VA);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
        pc=VA;li(2,DATA);li(3,0xfedcba9887654321ULL);
        if(kind==Clean){
            for(unsigned size:{2U,3U}){
                li(2,DATA+(size==2?4:0));
                emit(amo(2,size,10,2,0,2));emit(amo(3,size,11,2,3,1));
                emit(amo(3,size,12,2,3));emit(amo(3,size,13,2,3,3));
                for(unsigned op:{0U,1U,4U,8U,12U,16U,20U,24U,28U}){
                    // Reset each operation with a negative old value. W uses the upper beat lane.
                    li(3,0x8000000180000001ULL);emit(amo(1,size,14,2,3));
                    li(3,size==2?0xdeadbeef00000007ULL:7);emit(amo(op,size,15,2,3,op%4));
                }
                // Representative aq-only swap and aqrl add at each width. The
                // all-ones + one case wraps at XLEN or the 32-bit W boundary.
                li(3,~0ULL);emit(amo(1,size,14,2,3,2));
                li(3,1);emit(amo(0,size,15,2,3,3));
                emit(amo(2,size,10,2,0,2)); // independently observe wrapped zero
            }
            li(2,DATA);li(4,ALIAS);li(5,OTHER);li(3,0x123);
            emit(amo(2,3,10,2,0));emit(amo(3,3,11,4,3)); // same SPA alias exact match
            emit(amo(2,3,10,2,0));emit(sd(3,5));emit(amo(3,3,11,2,3)); // other SPA independent
            emit(amo(2,3,10,2,0));emit(sd(3,2,32));emit(amo(3,3,11,2,3)); // same line invalidates
            emit(amo(2,3,10,2,0));emit(amo(3,3,11,5,3));emit(amo(3,3,12,2,3)); // mismatch consumes
            emit(amo(2,3,10,2,0));emit(amo(2,3,10,5,0));emit(amo(3,3,11,2,3)); // LR replaces reservation
            emit(amo(0,3,0,2,3,3)); // rd=x0 still updates RAM
            const uint64_t retry=pc;emit(amo(2,3,10,2,0,2));emit(amo(3,3,11,2,3,1));
            emit(beq(11,0,int(retry-pc))|(1U<<12)); // constrained BNE retry, succeeds here
        }else if(kind==Ecall){
            emit(amo(2,3,10,2,0));faultPc=pc;emit(0x73);resume=pc;
            emit(amo(3,3,11,2,3));
        }else{
            if(kind==RomDenied||kind==MmioDenied)target=ALIAS;
            if(kind==Misaligned)target=DATA+2;
            li(2,target);faultPc=pc;
            emit(amo(kind==RomDenied?2:kind==MmioDenied?0:3,3,11,2,kind==RomDenied?0:3));resume=pc;
        }
        // Explicit CPU readbacks, never a debug read or software-backed DUT memory.
        li(2,DATA);emit(ld(16,2));emit(ld(17,2,8));emit(ld(18,2,32));li(4,OTHER);emit(ld(19,4));
        li(31,99);emit(0x6f);
        if(pc>VA+4096)throw std::runtime_error("guest program exceeds mapped code page");
        pc=HS;for(auto c:{0x142,0x141,0x143,0x600,0x643,0x64a,0x100})emit(csrr(c,20));
        csr(0x141,resume);emit(0x10200073);
        pc=MT;li(31,~0ULL);emit(0x6f);
    }
    void emit(uint32_t i){code[pc]=i;pc+=4;}
    void li(unsigned r,uint64_t n){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(n>>(8*b))&255;if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
    void csr(unsigned c,uint64_t n){li(1,n);emit(csrw(c,1));}
    uint64_t physical(uint64_t va)const{
        if(va>=DATA&&va<DATA+4096)return SPA+va-DATA;
        if(va>=ALIAS&&va<ALIAS+4096)return SPA+va-ALIAS;
        if(va>=OTHER&&va<OTHER+4096)return SPA2+va-OTHER;
        throw std::runtime_error("unplanned data VA");
    }
    uint64_t cause()const{return kind==Ecall?10:kind==VsDenied?15:kind==GDenied?23:kind==RomDenied?5:kind==Misaligned?6:7;}
    uint64_t gpa()const{return kind==GDenied?0x20001000:0;}
    uint64_t tval()const{return kind==Ecall?0:target;}
    void load(Memory&m)const{
        for(unsigned i=0;i<4;i++)m.page(BASE+4096*i);
        for(unsigned i=0;i<16;i++)m.page(GROOT+4096*i);
        m.pte(GROOT,GMID,1);m.pte(GMID+128*8,GPTLEAF,1);m.pte(GMID+256*8,GDATALEAF,1);
        for(unsigned i=0;i<3;i++)m.pte(GPTLEAF+i*8,0x80207000+i*4096,0xdf);
        m.pte(GDATALEAF,0x8020a000,0xdf);m.pte(GDATALEAF+8,SPA,kind==GDenied?0xd3:0xdf);
        m.pte(GDATALEAF+16,SPA2,0xdf);
        m.pte(GDATALEAF+24,kind==RomDenied?BASE:0x10000000,0xdf);
        m.pte(0x80207008,VMID,1);m.pte(0x80208000,VLEAF,1);
        m.pte(0x80209000,0x20000000,0xcb);m.pte(0x80209008,0x20001000,kind==VsDenied?0xc3:0xc7);
        m.pte(0x80209010,kind==RomDenied||kind==MmioDenied?0x20003000:0x20001000,0xc7);
        m.pte(0x80209018,0x20002000,0xc7);
        m.put(SPA,0x89abcdef81234567ULL,8);m.put(SPA+8,0x1122334455667788ULL,8);m.put(SPA+32,0x9988776655443322ULL,8);m.put(SPA2,0x76543210fedcba98ULL,8);
        for(auto [va,ins]:code)m.put(va>=VA&&va<VA+4096?va-VA+0x8020a000:va,ins,4);
    }
};
struct Expected {uint64_t pc,next,value;uint32_t instruction;unsigned rd;bool writes;};
struct Physical {uint64_t address,data,response;unsigned size,mask,operation;bool write,atomic;};
struct Model {
    std::vector<Expected> retire;std::vector<Physical> transactions;Memory finalMemory;
    unsigned atomics=0;uint64_t reservation=0;unsigned reservedSize=0;bool reserved=false;
    Model(const Program&p,Memory m):finalMemory(m){
        uint64_t r[32]{},pc=BASE,sepc=0;bool v=false;
        for(unsigned count=0;count<4000;count++){
            if(p.kind!=Clean&&pc==p.faultPc){reserved=false;sepc=pc;pc=HS;v=false;continue;}
            uint32_t i=p.code.at(pc);unsigned op=i&127,rd=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,f=(i>>12)&7;
            uint64_t val=0,next=pc+4;bool wr=rd!=0;
            if(op==0x13)val=f==0?r[a]+sext(i>>20,12):r[a]<<((i>>20)&63);
            else if(op==0x03||op==0x23||op==0x2f){
                if(!v)throw std::runtime_error("model data operation must be VS origin");
                bool at=op==0x2f,store=op==0x23;unsigned operation=at?i>>27:0,size=f;
                uint64_t va=r[a]+(at?0:store?sext((i>>25)<<5|((i>>7)&31),12):sext(i>>20,12));
                uint64_t address=p.physical(va),old=m.get(address,1U<<size),data=r[b],reply=m.get(address&~7ULL,8);
                unsigned mask=((1U<<(1U<<size))-1)<<(address&7);
                if(at){
                    atomics++;val=size==2?uint64_t(sext(old,32)):old;reply=val;
                    uint64_t operand=size==2?uint32_t(data):data,newValue=operand;
                    if(operation==2){reserved=true;reservation=address;reservedSize=size;}
                    else if(operation==3){val=reply=!(reserved&&reservation==address&&reservedSize==size);reserved=false;if(!val)m.put(address,data,1U<<size);}
                    else{
                        switch(operation){case 0:newValue=old+operand;break;case 1:break;case 4:newValue=old^operand;break;case 8:newValue=old|operand;break;case 12:newValue=old&operand;break;
                        case 16:newValue=sext(old,8U<<size)<sext(operand,8U<<size)?old:operand;break;
                        case 20:newValue=sext(old,8U<<size)>sext(operand,8U<<size)?old:operand;break;
                        case 24:newValue=old<operand?old:operand;break;case 28:newValue=old>operand?old:operand;break;default:throw std::runtime_error("unknown atomic");}
                        m.put(address,newValue,1U<<size);if((address>>6)==(reservation>>6))reserved=false;
                    }
                }else if(store){wr=false;m.put(address,data,1U<<size);if((address>>6)==(reservation>>6))reserved=false;reply=0;}
                else val=old;
                transactions.push_back({address,at?data:data<<((address&7)*8),reply,size,mask,operation,store,at});
            }else if(op==0x63){wr=false;unsigned raw=((i>>31)&1)<<12|((i>>7)&1)<<11|((i>>25)&63)<<5|((i>>8)&15)<<1;
                if(r[a]!=r[b])next=pc+sext(raw,13);
            }else if(op==0x73&&f){unsigned c=i>>20;if(f==1){if(c==0x141)sepc=r[a];}else{
                switch(c){case 0x142:val=p.cause();break;case 0x141:val=sepc;break;case 0x143:val=p.tval();break;
                case 0x600:val=(2ULL<<32)|(p.kind==Ecall?0x180:0x1c0);break;case 0x643:val=p.gpa()>>2;break;case 0x64a:val=0;break;case 0x100:val=(2ULL<<32)|0x100;break;default:throw std::runtime_error("unknown CSR");}
            }}else if(i==0x30200073){wr=false;v=true;next=VA;}
            else if(i==0x10200073){wr=false;v=true;next=sepc;}
            else if(i==0x6f){next=pc;val=pc+4;}
            else throw std::runtime_error("unknown oracle instruction");
            retire.push_back({pc,next,val,i,rd,wr});if(wr)r[rd]=val;pc=next;
            if(r[31]==99){finalMemory=m;return;}
        }
        throw std::runtime_error("oracle did not terminate");
    }
};
struct Check {
    uint64_t count=0;
    void operator()(uint64_t actual,uint64_t expected,const char*name){count++;if(actual!=expected){std::cerr<<name<<" actual=0x"<<std::hex<<actual<<" expected=0x"<<expected<<std::dec<<'\n';throw std::runtime_error(name);}}
};
struct Owner {Request request;uint64_t expected;bool checkData;};
static void run(Case kind,unsigned schedule,bool negative){
    Program p(kind);Memory initial;p.load(initial);
    // Both complete expectation streams exist before allocating or stepping the DUT.
    const Model model(p,initial);Check check;
    auto allocated=std::make_unique<SGuestAtomicsPlatformGsim>();auto&d=*allocated;
    static_assert(std::is_trivially_copyable_v<SGuestAtomicsPlatformGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();initialize(d,initial);
    std::deque<Owner> owners[2];Request heldReq[2];Response heldRsp[2];bool holdQ[2]{},holdR[2]{};
    unsigned nextOwner[2]{},requests[2]{},replies[2]{},heldRequests[2]{},heldResponses[2]{};
    size_t retired=0,physical=0;unsigned traps=0,clears=0,atomics=0,ptes=0,parcels=0;
    bool injected=false;
    auto commit=[&](uint64_t pc,uint32_t ins,unsigned rd,uint64_t value,uint64_t next,bool writes){
        check(retired<model.retire.size(),1,"finite retirement ownership");const auto&e=model.retire.at(retired);
        check(pc,e.pc,"independent retired PC");check(ins,e.instruction,"independent retired instruction");
        check(next,e.next,"independent next PC");check(writes,e.writes,"independent write-enable");
        if(writes){check(rd,e.rd,"independent destination");uint64_t expected=e.value;
            if((ins&127)==0x2f&&negative&&!injected){expected++;injected=true;}
            check(value,expected,(ins&127)==0x2f?"independent atomic result":"independent retired value");}
        std::cout<<"RETIRE case="<<names[kind]<<" schedule="<<schedule<<" index="<<retired<<" pc="<<pc<<" instruction="<<ins<<" writes="<<writes<<" rd="<<rd<<" value="<<value<<" next="<<next<<'\n';
        retired++;
    };
    // Two translated fetch parcels need up to 32 physical requests per retired
    // instruction; a data operation adds up to 16. Schedule 2 can close request
    // and response gates for 31 and 39 cycles respectively. Budget generously
    // per precomputed retirement (not observed progress), including walk/control
    // overhead and fixed trap/startup slack. This is a finite test timeout, not
    // a throughput or formal liveness bound.
    const uint64_t cycleLimit=65536+model.retire.size()*(schedule==1?2048ULL:8192ULL);
    for(unsigned cycle=0;cycle<cycleLimit;cycle++){
        unsigned rq=(cycle%5==1?0:1)|(cycle%7==2?0:2),rp=(cycle%7<3?0:1)|(cycle%9<4?0:2);
        if(schedule==2){rq=(cycle%41<29?0:1)|(cycle%43<31?0:2);rp=(cycle%47<35?0:1)|(cycle%53<39?0:2);}
        for(unsigned lane=0;lane<2;lane++){if(heldRequests[lane]<2)rq&=~(1U<<lane);if(heldResponses[lane]<2)rp&=~(1U<<lane);}
        d.set_io$$enable(1);d.set_io$$commitEnable(schedule==1?cycle%11!=3:cycle%37>=23);
        d.set_io$$sources(0);d.set_io$$allowRequest(rq);d.set_io$$allowResponse(rp);d.step();
        for(unsigned lane=0;lane<2;lane++){
            Request q=request(d,lane);Response r=response(d,lane);
            bool qr=(d.get_io$$scalarRequestReady()>>lane)&1,rr=(d.get_io$$scalarResponseReady()>>lane)&1;
            if(holdQ[lane])check(q==heldReq[lane],1,"request held stable");if(holdR[lane])check(r==heldRsp[lane],1,"response held stable");
            holdQ[lane]=q.valid&&!qr;holdR[lane]=r.valid&&!rr;heldReq[lane]=q;heldRsp[lane]=r;
            heldRequests[lane]+=holdQ[lane];heldResponses[lane]+=holdR[lane];
            if(r.valid&&rr){
                check(!owners[lane].empty(),1,"response has accepted owner");auto owner=owners[lane].front();owners[lane].pop_front();
                check(r.owner,owner.request.owner,"response owner identity");check(r.clear,owner.request.clear,"clear owner identity");
                check(r.error,0,"physical response success");check(r.pageFault,0,"physical page-fault forbidden");
                if(owner.checkData)check(r.data,owner.expected,"independent physical response");replies[lane]++;
                std::cout<<"RESPONSE case="<<names[kind]<<" schedule="<<schedule<<" lane="<<lane<<" owner="<<r.owner<<" data="<<r.data<<" clear="<<r.clear<<'\n';
            }
            if(q.valid&&!q.clear&&lane==0){
                check(physical<model.transactions.size(),1,"no forbidden physical data offer");
                const auto&planned=model.transactions.at(physical);
                check(q.address,planned.address,"authorized physical offer address");
                check(q.atomic,planned.atomic,"authorized physical offer kind");
            }
            if(q.valid&&qr){
                check(q.owner,nextOwner[lane]++&15,"sequential transport owner");check(q.lookup,1,"coherence lookup");
                uint64_t expected=0;bool checkData=false;
                if(q.clear){clears++;check(lane,0,"clear data lane");check(owners[0].empty()&&owners[1].empty(),1,"clear older owners drained");}
                else{
                    check(q.virtualized||q.prechecked||q.epoch||q.prefetch,0,"virtual proofs consumed before physical fabric");
                    if(lane==0){
                        check(physical<model.transactions.size(),1,"no forbidden physical data effect");const auto&e=model.transactions.at(physical++);
                        check(q.address,e.address,"independent physical address");check(q.atomic,e.atomic,"independent atomic qualifier");
                        check(q.write,e.write,"independent physical write");check(q.size,e.size,"independent width");check(q.mask,e.mask,"independent mask");
                        if(e.atomic)check(q.operation,e.operation,"independent atomic operation");
                        if(e.write||(e.atomic&&e.operation!=2))check(q.data,e.data,"independent physical operand");
                        expected=e.response;checkData=e.atomic||!e.write;atomics+=e.atomic;
                    }else{
                        check(q.atomic||q.write,0,"read-only fetch/table lane");
                        if(q.size==1){parcels++;check(q.mask,3U<<(q.address&7),"parcel mask");
                            check((q.address>=BASE&&q.address<BASE+16384)||(q.address>=0x8020a000&&q.address<0x8020b000),1,"bounded code physical window");}
                        else{ptes++;check(q.size,3,"PTE width");check(q.mask,255,"PTE mask");check(q.address>=GROOT&&q.address<0x8020a000,1,"bounded PTE physical window");}
                        expected=initial.get(q.address&~7ULL,8);checkData=true;
                    }
                }
                owners[lane].push_back({q,expected,checkData});requests[lane]++;
                std::cout<<"REQUEST case="<<names[kind]<<" schedule="<<schedule<<" lane="<<lane<<" owner="<<q.owner<<" address="<<q.address<<" data="<<q.data<<" size="<<q.size<<" mask="<<q.mask<<" atomic="<<q.atomic<<" operation="<<q.operation<<" clear="<<q.clear<<'\n';
            }
        }
        check(d.get_io$$msiRequest$$valid()||d.get_io$$msiResponse$$valid()||d.get_io$$msiError(),0,"all interrupt sources disabled");
#define COMMIT(N) if(d.get_io$$commit##N##$$valid())commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),d.get_io$$commit##N##$$bits$$writesRd())
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid()){
            check(kind!=Clean,1,"clean scenario no trap");check(traps++,0,"single trap");
            check(d.get_io$$trap$$bits$$pc(),p.faultPc,"independent fault PC");
            check(model.retire.at(retired).pc,HS,"trap at exact retirement frontier");
            check(d.get_io$$trap$$bits$$cause(),p.cause(),"independent cause");check(d.get_io$$trap$$bits$$tval(),p.tval(),"independent tval");
            check(d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),p.gpa(),"independent raw GPA");
            check(d.get_io$$trap$$bits$$guestFault$$guestPageFault(),kind==GDenied,"independent guest-page classification");
            check(d.get_io$$trap$$bits$$guestFault$$guestAddress(),kind!=Ecall,"independent guest-address provenance");
            check(d.get_io$$trap$$bits$$guestFault$$implicitPte(),0,"no implicit-PTE fault");
            std::cout<<"TRAP case="<<names[kind]<<" schedule="<<schedule<<" pc="<<p.faultPc<<" cause="<<p.cause()<<" tval="<<p.tval()<<" gpa="<<p.gpa()<<'\n';
        }
        if(retired==model.retire.size()){
            check(physical,model.transactions.size(),"all expected physical transactions");check(atomics,model.atomics,"all expected atomics");
            check(traps,kind==Clean?0:1,"trap count");check(clears,kind==Clean?0:1,"trap clears reservation");
            check(owners[0].empty(),1,"terminal data owners drained");check(request(d,0).valid,0,"no terminal data offer");
            for(unsigned lane=0;lane<2;lane++){check(requests[lane]-replies[lane],owners[lane].size(),"finite terminal owner accounting");check(heldRequests[lane]>0&&heldResponses[lane]>0,1,"actual lane backpressure");}
            check(ptes>0&&parcels>0,1,"actual nested translation and hardware fetch");
            // Finite prefix stops at the sentinel retirement. Any fetch-only owners
            // are enumerated, not silently treated as drained or reused in another run.
            for(const auto&owner:owners[1])std::cout<<"TERMINAL_FETCH_OWNER case="<<names[kind]<<" schedule="<<schedule<<" owner="<<owner.request.owner<<" address="<<owner.request.address<<'\n';
            std::cout<<"GUEST_ATOMICS_PASS case="<<names[kind]<<" schedule="<<schedule<<" cycles="<<cycle+1<<" commits="<<retired<<" traps="<<traps<<" atomicRequests="<<atomics<<" checks="<<check.count<<" ptes="<<ptes<<" parcels="<<parcels<<" clears="<<clears<<" requests="<<requests[0]<<","<<requests[1]<<" responses="<<replies[0]<<","<<replies[1]<<" heldRequests="<<heldRequests[0]<<","<<heldRequests[1]<<" heldResponses="<<heldResponses[0]<<","<<heldResponses[1]<<" fetchOwnersRemaining="<<owners[1].size()<<" readbacks=4\n";return;
        }
    }
    throw std::runtime_error("bounded guest atomic timeout");
}
int main(int argc,char**argv){try{
    bool negative=argc==2&&std::string(argv[1])=="--wrong-atomic";
    if(argc>2||(argc==2&&!negative))throw std::runtime_error("usage: guest_atomics [--wrong-atomic]");
    if(negative){run(Clean,1,true);throw std::runtime_error("negative control was not rejected");}
    for(unsigned k=0;k<7;k++)for(unsigned schedule:{1U,2U})run(Case(k),schedule,false);
    std::cout<<"GUEST_ATOMICS_ALL_PASS cases=7 runs=14\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
