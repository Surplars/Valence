// Final-SPA PMP and static A-off execution boundaries on the real H platform.
// Independent architectural streams are complete before DUT allocation. No RTL
// response injection, permission repair, DMA, interrupts, or writable-misa switch.
#ifdef GUEST_ATOMIC_DISABLED
#include "GuestAtomicDisabledGsim.h"
using Dut = SGuestAtomicDisabledGsim;
static constexpr bool A_ENABLED = false;
static constexpr const char* PROFILE = "a_off";
#else
#include "GuestAtomicPmpGsim.h"
using Dut = SGuestAtomicPmpGsim;
static constexpr bool A_ENABLED = true;
static constexpr const char* PROFILE = "pmp";
#endif
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
static constexpr uint64_t VA=0x40000000, DATA=VA+0x1000, OTHER=VA+0x3000;
static constexpr uint64_t SPA=0x8020b000, SPA2=0x8020c000;
static constexpr uint64_t GROOT=0x80200000, GMID=0x80204000, GPTLEAF=0x80205000, GDATALEAF=0x80206000;
static constexpr uint64_t VROOT=0x10000000, VMID=0x10001000, VLEAF=0x10002000;
static uint32_t addi(unsigned d,unsigned s,int n){return(uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t shift(unsigned d,unsigned s,unsigned n){return n<<20|s<<15|1<<12|d<<7|0x13;}
static uint32_t csrw(unsigned c,unsigned r){return c<<20|r<<15|1<<12|0x73;}
static uint32_t csrr(unsigned c,unsigned r){return c<<20|2<<12|r<<7|0x73;}
static uint32_t ld(unsigned d,unsigned a,int n=0){return(uint32_t(n)&4095)<<20|a<<15|3<<12|d<<7|3;}
static uint32_t sd(unsigned s,unsigned a,int n=0){unsigned u=n&4095;return(u>>5)<<25|s<<20|a<<15|3<<12|(u&31)<<7|0x23;}
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
static Request request(Dut&d,unsigned lane){Request r;
#define R(N) r.valid=d.get_io$$scalar##N##Request$$valid();r.owner=d.get_io$$scalar##N##Request$$bits$$owner();r.clear=d.get_io$$scalar##N##Request$$bits$$clearReservation();r.lookup=d.get_io$$scalar##N##Request$$bits$$needsCoherenceLookup();r.address=d.get_io$$scalar##N##Request$$bits$$memory$$address();r.data=d.get_io$$scalar##N##Request$$bits$$memory$$data();r.size=d.get_io$$scalar##N##Request$$bits$$memory$$size();r.mask=d.get_io$$scalar##N##Request$$bits$$memory$$mask();r.write=d.get_io$$scalar##N##Request$$bits$$memory$$write();r.atomic=d.get_io$$scalar##N##Request$$bits$$memory$$atomic();r.operation=d.get_io$$scalar##N##Request$$bits$$memory$$atomicOp();r.virtualized=d.get_io$$scalar##N##Request$$bits$$memory$$virtualized();r.prechecked=d.get_io$$scalar##N##Request$$bits$$memory$$precheckedLoad();r.epoch=d.get_io$$scalar##N##Request$$bits$$memory$$translationEpoch();r.prefetch=d.get_io$$scalar##N##Request$$bits$$memory$$prefetchNextAllowed();r.uncached=d.get_io$$scalar##N##Request$$bits$$memory$$uncached()
    if(lane){R(1);}else{R(0);}
#undef R
    if(r.clear){r.address=r.data=r.size=r.mask=r.epoch=r.operation=0;r.write=r.atomic=r.virtualized=r.prechecked=r.prefetch=r.uncached=false;}
    return r;
}
static Response response(Dut&d,unsigned lane){Response r;
#define R(N) r.valid=d.get_io$$scalar##N##Response$$valid();r.owner=d.get_io$$scalar##N##Response$$bits$$owner();r.clear=d.get_io$$scalar##N##Response$$bits$$clearReservation();r.data=d.get_io$$scalar##N##Response$$bits$$memory$$data();r.error=d.get_io$$scalar##N##Response$$bits$$memory$$error();r.pageFault=d.get_io$$scalar##N##Response$$bits$$memory$$pageFault()
    if(lane){R(1);}else{R(0);}
#undef R
    return r;
}
static void initialize(Dut&d,Memory&m){
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
enum Case { LrW, LrD, ScW, ScD, AmoW, AmoD };
static const char* names[]={"lr_w","lr_d","sc_w","sc_d","amo_w","amo_d"};
static constexpr uint64_t RD_SENTINEL=0xfedcba9876543210ULL;
static constexpr uint64_t INITIAL_TARGET=0x89abcdef81234567ULL;
static constexpr uint64_t INITIAL_NEIGHBOR=0x76543210fedcba98ULL;
static constexpr uint64_t INITIAL_POISON=0x1122334455667788ULL;
struct Program {
    Case kind;std::map<uint64_t,uint32_t> code;uint64_t pc=BASE,faultPc=0,resume=0,target=DATA;
    uint32_t faultInstruction=0;
    bool lr()const{return kind==LrW||kind==LrD;}
    unsigned size()const{return (unsigned(kind)&1)?3:2;}
    unsigned operation()const{return lr()?2:kind==ScW||kind==ScD?3:0;}
    unsigned readbacks()const{return A_ENABLED&&lr()?3:5;}
    explicit Program(Case k):kind(k){
        // Entry zero wins over broad RWX entry one. Both remain unlocked and
        // unchanged after boot. The narrow 4 KiB NAPOT region names final SPA,
        // neither 0x40001000 GVA nor 0x20001000 GPA.
        csr(0x3b0,(SPA>>2)|0x1ff);csr(0x3b1,~0ULL);
        csr(0x3a0,0x1f00|(A_ENABLED?(lr()?0x1c:0x19):0x1f));
        emit(csrr(0x301,21)); // actual misa, including A and deliberately clear H
        csr(0x305,MT);csr(0x105,HS);
        csr(0x304,0);csr(0x303,0);csr(0x604,0);csr(0x603,0);csr(0x602,0);
        csr(0x302,(1ULL<<2)|(1ULL<<5)|(1ULL<<7));
        csr(0x280,(8ULL<<60)|(VROOT>>12));csr(0x680,(8ULL<<60)|(GROOT>>12));
        // Dirty trap CSRs make the required trap-time zero writes observable.
        csr(0x643,0x55);csr(0x64a,0x3000);csr(0x143,0x77);csr(0x142,0x88);csr(0x600,0);
        csr(0x341,VA);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
        pc=VA;target=DATA+(size()==2?4:0);
        li(2,target);li(3,0x123);li(4,OTHER);li(11,RD_SENTINEL);
        faultPc=pc;faultInstruction=amo(operation(),size(),11,2,lr()?0:3);
        emit(faultInstruction);
        // This immediate younger store must be squashed, not replayed. The HS
        // handler skips it deliberately, then resumes an intended separate store.
        emit(sd(3,4,8));resume=pc;
        emit(addi(12,11,0)); // fault must not overwrite destination x11
        emit(sd(3,4,16));emit(ld(16,4));emit(ld(17,4,8));emit(ld(18,4,16));
        // LR's no-read PMP region cannot be weakened just to inspect it. Its
        // unchanged target proof is zero physical offers plus unchanged rd and
        // accessible neighboring RAM. SC/AMO and A-off also read the target beat.
        if(!A_ENABLED||!lr()){li(2,DATA);emit(ld(19,2));emit(ld(22,2,8));}
        li(31,99);emit(0x6f);
        if(pc>VA+4096)throw std::runtime_error("guest program exceeds mapped code page");
        pc=HS;for(auto c:{0x142,0x141,0x143,0x600,0x643,0x64a,0x100})emit(csrr(c,20));
        // Advance actual captured sepc across the atomic and poison store.
        emit(csrr(0x141,20));emit(addi(20,20,8));emit(csrw(0x141,20));emit(0x10200073);
        pc=MT;li(31,~0ULL);emit(0x6f);
    }
    void emit(uint32_t i){code[pc]=i;pc+=4;}
    void li(unsigned r,uint64_t n){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(n>>(8*b))&255;if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
    void csr(unsigned c,uint64_t n){li(1,n);emit(csrw(c,1));}
    uint64_t physical(uint64_t va)const{
        if(va>=DATA&&va<DATA+4096)return SPA+va-DATA;
        if(va>=OTHER&&va<OTHER+4096)return SPA2+va-OTHER;
        throw std::runtime_error("unplanned data VA");
    }
    uint64_t cause()const{return !A_ENABLED?2:lr()?5:7;}
    uint64_t tval()const{return A_ENABLED?target:uint64_t(faultInstruction);}
    void load(Memory&m)const{
        for(unsigned i=0;i<4;i++)m.page(BASE+4096*i);
        for(unsigned i=0;i<16;i++)m.page(GROOT+4096*i);
        m.pte(GROOT,GMID,1);m.pte(GMID+128*8,GPTLEAF,1);m.pte(GMID+256*8,GDATALEAF,1);
        for(unsigned i=0;i<3;i++)m.pte(GPTLEAF+i*8,0x80207000+i*4096,0xdf);
        m.pte(GDATALEAF,0x8020a000,0xdf);m.pte(GDATALEAF+8,SPA,0xdf);
        m.pte(GDATALEAF+16,SPA2,0xdf);
        m.pte(0x80207008,VMID,1);m.pte(0x80208000,VLEAF,1);
        m.pte(0x80209000,0x20000000,0xcb);m.pte(0x80209008,0x20001000,0xc7);
        m.pte(0x80209018,0x20002000,0xc7);
        m.put(SPA,INITIAL_TARGET,8);m.put(SPA+8,0x9988776655443322ULL,8);
        m.put(SPA2,INITIAL_NEIGHBOR,8);m.put(SPA2+8,INITIAL_POISON,8);m.put(SPA2+16,0,8);
        for(auto [va,ins]:code)m.put(va>=VA&&va<VA+4096?va-VA+0x8020a000:va,ins,4);
    }
};
struct Expected {uint64_t pc,next,value;uint32_t instruction;unsigned rd;bool writes;};
struct Physical {uint64_t address,data,response;unsigned size,mask,operation;bool write,atomic;};
struct Model {
    std::vector<Expected> retire;std::vector<Physical> transactions;
    Model(const Program&p,Memory m){
        uint64_t r[32]{},pc=BASE,sepc=0;bool v=false;
        for(unsigned count=0;count<4000;count++){
            if(pc==p.faultPc){sepc=pc;pc=HS;v=false;continue;}
            uint32_t i=p.code.at(pc);unsigned op=i&127,rd=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,f=(i>>12)&7;
            uint64_t val=0,next=pc+4;bool wr=rd!=0;
            if(op==0x13)val=f==0?r[a]+sext(i>>20,12):r[a]<<((i>>20)&63);
            else if(op==0x03||op==0x23){
                if(!v)throw std::runtime_error("model data operation must be VS origin");
                bool store=op==0x23;unsigned size=f;
                uint64_t va=r[a]+(store?sext((i>>25)<<5|((i>>7)&31),12):sext(i>>20,12));
                uint64_t address=p.physical(va),data=r[b],reply=m.get(address&~7ULL,8);
                unsigned mask=((1U<<(1U<<size))-1)<<(address&7);
                if(store){wr=false;m.put(address,data,1U<<size);reply=0;}else val=m.get(address,1U<<size);
                transactions.push_back({address,data<<((address&7)*8),reply,size,mask,0,store,false});
            }else if(op==0x73&&f){unsigned c=i>>20;if(f==1){if(c==0x141)sepc=r[a];}else{
                switch(c){case 0x301:val=0x8000000000141104ULL|(A_ENABLED?1:0);break;
                case 0x142:val=p.cause();break;case 0x141:val=sepc;break;case 0x143:val=p.tval();break;
                case 0x600:val=(2ULL<<32)|(A_ENABLED?0x1c0:0x180);break;
                case 0x643:case 0x64a:val=0;break;case 0x100:val=(2ULL<<32)|0x100;break;
                default:throw std::runtime_error("unknown CSR");}
            }}else if(i==0x30200073){wr=false;v=true;next=VA;}
            else if(i==0x10200073){wr=false;v=true;next=sepc;}
            else if(i==0x6f){next=pc;val=pc+4;}
            else throw std::runtime_error("unknown oracle instruction");
            retire.push_back({pc,next,val,i,rd,wr});if(wr)r[rd]=val;pc=next;
            if(r[31]==99)return;
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
    auto allocated=std::make_unique<Dut>();auto&d=*allocated;
    static_assert(std::is_trivially_copyable_v<Dut>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();initialize(d,initial);
    std::deque<Owner> owners[2];Request heldReq[2];Response heldRsp[2];bool holdQ[2]{},holdR[2]{};
    unsigned nextOwner[2]{},requests[2]{},replies[2]{},heldRequests[2]{},heldResponses[2]{};
    size_t retired=0,physical=0;unsigned traps=0,clears=0,atomics=0,ptes=0,parcels=0;
    unsigned forbiddenOffers=0,dataTranslationsBeforeTrap=0,dataPteOffersBeforeTrap=0;
    auto commit=[&](uint64_t pc,uint32_t ins,unsigned rd,uint64_t value,uint64_t next,bool writes){
        check(retired<model.retire.size(),1,"finite retirement ownership");const auto&e=model.retire.at(retired);
        check(pc==p.faultPc||pc==p.faultPc+4,0,"rejected atomic and younger poison never retire");
        check(pc,e.pc,"independent retired PC");check(ins,e.instruction,"independent retired instruction");
        check(next,e.next,"independent next PC");check(writes,e.writes,"independent write-enable");
        if(writes){check(rd,e.rd,"independent destination");uint64_t expected=e.value;
            check(value,expected,"independent retired value");
            if(ins==csrr(0x301,21)){check(value&1,A_ENABLED,"actual misa A profile");check((value>>7)&1,0,"actual misa H remains clear");}}
        std::cout<<"RETIRE profile="<<PROFILE<<" case="<<names[kind]<<" schedule="<<schedule<<" index="<<retired<<" pc="<<pc<<" instruction="<<ins<<" writes="<<writes<<" rd="<<rd<<" value="<<value<<" next="<<next<<'\n';
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
        // No earlier guest data instructions exist. A-off must be rejected
        // before *any* accepted data translation request or data PTE offer, not merely
        // before a final fabric request. Taps observe the real production tile.
        if(!traps){
            dataTranslationsBeforeTrap+=d.get_io$$dataTranslationRequest();
            dataPteOffersBeforeTrap+=d.get_io$$dataPteRequest();
        }
        if(!A_ENABLED&&!traps){
            check(d.get_io$$dataTranslationRequest(),0,"A-off no data translation request");
            check(d.get_io$$dataPteRequest(),0,"A-off no data PTE offer");
        }
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
                std::cout<<"RESPONSE profile="<<PROFILE<<" case="<<names[kind]<<" schedule="<<schedule<<" lane="<<lane<<" owner="<<r.owner<<" data="<<r.data<<" error="<<r.error<<" pageFault="<<r.pageFault<<" clear="<<r.clear<<'\n';
            }
            if(q.valid&&!q.clear&&lane==0){
                bool forbidden=q.atomic||!traps||(q.write&&q.address==SPA2+8)||
                    (A_ENABLED&&p.lr()&&q.address>=SPA&&q.address<SPA+4096);
                forbiddenOffers+=forbidden;
                check(forbidden,0,"zero forbidden physical offers");
                check(physical<model.transactions.size(),1,"no forbidden physical data offer");
                const auto&planned=model.transactions.at(physical);
                check(q.address,planned.address,"authorized physical offer address");
                check(q.atomic,planned.atomic,"authorized physical offer kind");
            }
            if(q.valid&&!q.clear&&lane==1){
                check(q.atomic||q.write,0,"no forbidden fetch/table write offer");
                bool code=(q.address>=BASE&&q.address<BASE+16384)||
                    (q.address>=0x8020a000&&q.address<0x8020b000);
                bool table=q.address>=GROOT&&q.address<0x8020a000;
                check(q.size==1?code:q.size==3&&table,1,"authorized fetch/table physical offer");
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
                std::cout<<"REQUEST profile="<<PROFILE<<" case="<<names[kind]<<" schedule="<<schedule<<" lane="<<lane<<" owner="<<q.owner<<" address="<<q.address<<" data="<<q.data<<" size="<<q.size<<" mask="<<q.mask<<" write="<<q.write<<" atomic="<<q.atomic<<" operation="<<q.operation<<" clear="<<q.clear<<'\n';
            }
        }
        check(d.get_io$$msiRequest$$valid()||d.get_io$$msiResponse$$valid()||d.get_io$$msiError(),0,"all interrupt sources disabled");
#define COMMIT(N) if(d.get_io$$commit##N##$$valid())commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),d.get_io$$commit##N##$$bits$$writesRd())
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid()){
            check(traps++,0,"single trap");
            check(d.get_io$$trap$$bits$$pc(),p.faultPc,"independent fault PC");
            check(model.retire.at(retired).pc,HS,"trap at exact retirement frontier");
            check(d.get_io$$trap$$bits$$cause(),p.cause()+(negative?1:0),"independent atomic permission cause");check(d.get_io$$trap$$bits$$tval(),p.tval(),"independent tval");
            check(d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),0,"independent raw GPA");
            check(d.get_io$$trap$$bits$$guestFault$$guestPageFault(),false,"independent guest-page classification");
            check(d.get_io$$trap$$bits$$guestFault$$guestAddress(),A_ENABLED,"independent guest-address provenance");
            check(d.get_io$$trap$$bits$$guestFault$$implicitPte(),0,"no implicit-PTE fault");
            std::cout<<"TRAP profile="<<PROFILE<<" case="<<names[kind]<<" schedule="<<schedule<<" pc="<<d.get_io$$trap$$bits$$pc()<<" cause="<<d.get_io$$trap$$bits$$cause()<<" tval="<<d.get_io$$trap$$bits$$tval()<<" gpa="<<d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress()<<" guestAddress="<<unsigned(d.get_io$$trap$$bits$$guestFault$$guestAddress())<<" guestPageFault="<<unsigned(d.get_io$$trap$$bits$$guestFault$$guestPageFault())<<" implicitPte="<<unsigned(d.get_io$$trap$$bits$$guestFault$$implicitPte())<<'\n';
        }
        if(retired==model.retire.size()){
            check(physical,model.transactions.size(),"all expected physical transactions");check(atomics,0,"no atomic request reaches fabric");
            check(dataTranslationsBeforeTrap>0,A_ENABLED,"data translation occurs only in A-enabled profile");
            check(dataPteOffersBeforeTrap>0,A_ENABLED,"data walk occurs only in A-enabled profile");
            check(traps,1,"trap count");check(clears,1,"trap clears reservation");
            check(owners[0].empty(),1,"terminal data owners drained");check(request(d,0).valid,0,"no terminal data offer");
            for(unsigned lane=0;lane<2;lane++){check(requests[lane]-replies[lane],owners[lane].size(),"finite terminal owner accounting");check(heldRequests[lane]>0&&heldResponses[lane]>0,1,"actual lane backpressure");}
            check(ptes>0&&parcels>0,1,"actual nested translation and hardware fetch");
            // Finite prefix stops at the sentinel retirement. Any fetch-only owners
            // are enumerated, not silently treated as drained or reused in another run.
            for(const auto&owner:owners[1])std::cout<<"TERMINAL_FETCH_OWNER profile="<<PROFILE<<" case="<<names[kind]<<" schedule="<<schedule<<" owner="<<owner.request.owner<<" address="<<owner.request.address<<'\n';
            std::cout<<"GUEST_ATOMIC_PERMISSIONS_PASS profile="<<PROFILE<<" case="<<names[kind]<<" schedule="<<schedule<<" cycles="<<cycle+1<<" commits="<<retired<<" traps="<<traps<<" atomicRequests="<<atomics<<" checks="<<check.count<<" ptes="<<ptes<<" parcels="<<parcels<<" clears="<<clears<<" requests="<<requests[0]<<","<<requests[1]<<" responses="<<replies[0]<<","<<replies[1]<<" heldRequests="<<heldRequests[0]<<","<<heldRequests[1]<<" heldResponses="<<heldResponses[0]<<","<<heldResponses[1]<<" fetchOwnersRemaining="<<owners[1].size()<<" readbacks="<<p.readbacks()<<" forbiddenOffers="<<forbiddenOffers<<" dataTranslationsBeforeTrap="<<dataTranslationsBeforeTrap<<" dataPteOffersBeforeTrap="<<dataPteOffersBeforeTrap<<" skippedPc="<<p.faultPc+4<<"\n";return;
        }
    }
    throw std::runtime_error("bounded guest atomic permission timeout");
}
int main(int argc,char**argv){try{
    bool negative=argc==2&&std::string(argv[1])=="--wrong-cause";
    if(argc>2||(argc==2&&!negative))throw std::runtime_error("usage: guest_atomic_permissions [--wrong-cause]");
    if(negative){run(LrW,1,true);throw std::runtime_error("negative control was not rejected");}
    for(unsigned k=0;k<6;k++)for(unsigned schedule:{1U,2U})run(Case(k),schedule,false);
    std::cout<<"GUEST_ATOMIC_PERMISSIONS_ALL_PASS profile="<<PROFILE<<" cases=6 runs=12\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
