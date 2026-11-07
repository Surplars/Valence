// Consecutive VS traps with different metadata, without intermediate reset,
// image writes, table writes, or HS metadata writes. The expected program and
// retirement model are independent of DUT decode and translation logic.
// Native transport helpers follow the sealed VS-boundary driver's contract.
#include "HypervisorPlatformGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <set>
#include <stdexcept>
#include <type_traits>
#include <deque>
#include <memory>
#include <string>
#include <fstream>
#include <sstream>
#include <filesystem>
static constexpr uint64_t BASE=0x80000000, HS=BASE+0x2000, MT=BASE+0x3000;
static constexpr uint64_t START=0x401ff000, SPLIT=0x401ffffe;
static constexpr uint64_t DATA=0x401fe000, TARGET=0x40201000, SPA_DATA=0x8020c000;
static constexpr uint64_t GROOT=0x80200000, GMID=0x80204000, GPTLEAF=0x80205000, GDATALEAF=0x80206000;
static constexpr uint64_t VROOT=0x10000000, VMID=0x10001000, VLEFT=0x10002000, VRIGHT=0x10003000;
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
// Each row is an architectural expectation, not a DUT-derived translation.
struct Stage {
    const char* name;
    uint64_t target,cause,tval,gpa,htval,htinst,hstatus;
    bool guestPageFault,guestAddress,implicitPte;
};
static constexpr Stage stages[]={
    {"store_pte_g", TARGET,23,TARGET,0x10003008,0x04000c02,0x3000,0x2000001c0,true,true,true},
    {"ordinary_vs_leaf",0x401fc000,13,0x401fc000,0,0,0,0x2000001c0,false,true,false},
    {"split_fetch_pte_g",SPLIT,20,0x40200000,0x10003000,0x04000c00,0x3000,0x2000001c0,true,true,true},
    {"vs_ecall",0,10,0,0,0,0,0x200000180,false,false,false},
    {"load_final_g",0x401fd000,21,0x401fd000,0x20003000,0x08000c00,0,0x2000001c0,true,true,false}
};
static constexpr unsigned stageCount=5;
static uint64_t olderValue(unsigned stage){return 0x55+stage*0x11;}
struct Program {
    std::map<uint64_t,uint32_t> code;
    uint64_t pc=BASE,faultPc[stageCount]{},resume[stageCount]{};
    Program(){
        csr(0x3b0,~0ULL);csr(0x3a0,31);csr(0x305,MT);csr(0x105,HS);
        csr(0x304,0);csr(0x303,0);csr(0x604,0);csr(0x603,0);csr(0x602,0);
        csr(0x302,(1ULL<<10)|(1ULL<<13)|(1ULL<<20)|(1ULL<<21)|(1ULL<<23));
        csr(0x280,(8ULL<<60)|(VROOT>>12));csr(0x680,(8ULL<<60)|(GROOT>>12));csr(0x600,0);
        csr(0x341,START);csr(0x300,(1ULL<<39)|(1<<11));emit(0x30200073);
        for(unsigned s=0;s<stageCount;s++){
            pc=START+s*0x200;resume[s]=pc+0x100;
            li(2,DATA);li(3,olderValue(s));li(4,stages[s].target);li(6,resume[s]);li(10,0x77);
            li(7,0x321); // Faulting SD and younger SD use a distinct value.
            emit(sd(3,2,8));emit(ld(11,2,8));
            if(s==2){li(5,SPLIT);emit(0x00028067);faultPc[s]=SPLIT;}
            else{
                faultPc[s]=pc;
                emit(s==0?sd(7,4):s==3?0x00000073:ld(10,4));
                emit(sd(7,2,16));emit(0x00030067);
            }
            if(pc>=resume[s])throw std::runtime_error("stage preamble overlaps recovery");
            pc=resume[s];emit(ld(12,2,8));emit(ld(13,2));emit(ld(14,2,16));
            if(s+1<stageCount){li(5,START+(s+1)*0x200);emit(0x00028067);}
            else{li(31,99);emit(0x6f);}
        }
        pc=SPLIT;emit(addi(10,0,0x357));emit(sd(7,2,16));emit(0x00030067);
        pc=HS;emit(csrr(0x142,20));emit(csrr(0x141,21));emit(csrr(0x143,22));
        emit(csrr(0x600,23));emit(csrr(0x643,24));emit(csrr(0x64a,25));emit(csrr(0x100,26));
        // SEPC is the sole CSR written by the handler. Hardware must replace or
        // clear HTVAL/HTINST/GVA itself on each entry, including VS ECALL.
        emit(csrw(0x141,6));emit(0x10200073);
        pc=MT;emit(addi(31,0,-1));emit(0x6f);
    }
    void emit(uint32_t i){code[pc]=i;pc+=4;}
    void li(unsigned r,uint64_t n){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(n>>(8*b))&255;if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
    void csr(unsigned c,uint64_t n){li(1,n);emit(csrw(c,1));}
    uint64_t physical(uint64_t va)const{
        if(va>=START&&va<START+4096)return 0x8020b000+va-START;
        if(va>=0x40200000&&va<0x40201000)return 0x8020d000+va-0x40200000;
        return va;
    }
    void load(Memory&m)const{
        for(unsigned i=0;i<4;i++)m.page(BASE+i*4096);
        for(unsigned i=0;i<16;i++)m.page(GROOT+i*4096);
        m.pte(GROOT,GMID,1);m.pte(GMID+128*8,GPTLEAF,1);m.pte(GMID+256*8,GDATALEAF,1);
        // Right VS-table GPA 10003000 has no G mapping for the entire sequence.
        for(unsigned i=0;i<3;i++)m.pte(GPTLEAF+i*8,0x80207000+i*4096,0xdf);
        m.pte(GDATALEAF,0x8020b000,0xdf);m.pte(GDATALEAF+8,0x8020d000,0xdf);m.pte(GDATALEAF+16,SPA_DATA,0xdf);
        m.pte(0x80207008,VMID,1);m.pte(0x80208000,VLEFT,1);m.pte(0x80208008,VRIGHT,1);
        // Left VS leaf 508 is invalid; leaf 509 reaches the missing final G leaf.
        m.pte(0x80209000+509*8,0x20003000,0xc7);
        m.pte(0x80209000+510*8,0x20002000,0xc7);m.pte(0x80209000+511*8,0x20000000,0xcb);
        m.pte(0x8020a000,0x20001000,0xcb);m.pte(0x8020a008,0x20002000,0xc7);
        m.put(SPA_DATA,0x1234,8);m.put(SPA_DATA+8,0x5678,8);m.put(SPA_DATA+16,0x9abc,8);
        for(auto [va,ins]:code)for(unsigned b=0;b<4;b++)m.put(physical(va+b),ins>>(8*b),1);
    }
};
struct Oracle {
    const Program&p;std::string control;uint64_t r[32]{},pc=BASE,sepc=0;
    uint64_t checks=0,commits=0;unsigned traps=0,returns=0,csrReads=0,storeRetired=0,recoveryLoads=0;bool v=false,admitted=false;
    std::map<uint64_t,uint64_t> memory{{DATA,0x1234},{DATA+8,0x5678},{DATA+16,0x9abc}};
    Oracle(const Program&program,const std::string&negative):p(program),control(negative){}
    void check(uint64_t actual,uint64_t expected,const char*name){checks++;if(actual!=expected){std::cerr<<name<<" pc=0x"<<std::hex<<pc<<" actual=0x"<<actual<<" expected=0x"<<expected<<std::dec<<'\n';throw std::runtime_error(name);}}
    uint64_t csr(unsigned c){
        check(traps>0&&traps<=stageCount,1,"CSR follows trap");csrReads++;
        unsigned s=traps-1;const auto&t=stages[s];
        switch(c){
        case 0x142:return t.cause;case 0x141:return p.faultPc[s];case 0x143:return t.tval;
        case 0x100:return 0x200000100; // Every entry clears SPIE from the host SIE=0 state.
        case 0x600:return control=="stale-gva"&&s==3?stages[2].hstatus:t.hstatus;
        case 0x643:return control=="stale-htval"&&s==1?stages[0].htval:t.htval;
        case 0x64a:return control=="stale-htinst"&&s==1?stages[0].htinst:t.htinst;
        default:throw std::runtime_error("unplanned CSR read");}
    }
    const char* valueLabel(unsigned c)const{
        if(control=="stale-htval"&&traps==2&&c==0x643)return "stale HTVAL";
        if(control=="stale-htinst"&&traps==2&&c==0x64a)return "stale HTINST";
        if(control=="stale-gva"&&traps==4&&c==0x600)return "stale GVA";
        return "independent retired value";
    }
    void commit(uint64_t actualPc,uint32_t i,unsigned rd,uint64_t value,uint64_t actualNext,bool actualWrites){
        check(actualPc,pc,"retired PC");check(i,p.code.at(pc),"retired instruction");
        for(unsigned s=0;s<stageCount;s++)check(pc==p.faultPc[s],0,"fault instruction must not retire");
        check(pc>=MT&&pc<MT+4096,0,"unexpected M trap handler");
        unsigned op=i&127,d=(i>>7)&31,a=(i>>15)&31,b=(i>>20)&31,f=(i>>12)&7;
        uint64_t val=0,next=pc+4;bool wr=d!=0;
        if(op==0x13){if(f==0)val=r[a]+sext(i>>20,12);else if(f==1)val=r[a]<<((i>>20)&63);else throw std::runtime_error("unplanned OPIMM");}
        else if(op==3){
            check(v,1,"load is VS origin");val=memory.at(r[a]+sext(i>>20,12));
            if(d>=12&&d<=14){check(returns>0,1,"recovery load after SRET");check(pc,p.resume[returns-1]+(d-12)*4,"ordered recovery load");recoveryLoads++;}
        }
        else if(op==0x23){
            wr=false;check(v,1,"store is VS origin");uint64_t address=r[a]+sext((i>>25)<<5|((i>>7)&31),12);
            check(address,DATA+8,"only older store retires");check(storeRetired,returns,"one older store per stage");
            check(r[b],olderValue(storeRetired),"stage unique older store");storeRetired++;memory.at(address)=r[b];
        }
        else if(op==0x67){val=pc+4;next=(r[a]+sext(i>>20,12))&~1ULL;}
        else if(op==0x6f){check(i,0x6f,"only sentinel JAL");val=pc+4;next=pc;}
        else if(op==0x73&&f){
            unsigned c=i>>20;if(f==2){
                std::cout<<"CSR stage="<<traps<<" pc=0x"<<std::hex<<actualPc<<" csr=0x"<<c<<" rd="<<std::dec<<rd<<" value=0x"<<std::hex<<value<<std::dec<<'\n';
                val=csr(c);
            }else{
                check(f,1,"CSRRW encoding");check(d,0,"CSR writes discard old value");
                if(admitted){check(actualPc>=HS&&actualPc<MT,1,"post-admission CSR write is in handler");check(c,0x141,"handler only writes SEPC");sepc=r[a];}
            }
        }
        else if(i==0x30200073){wr=false;next=START;v=true;check(admitted,0,"one initial MRET");admitted=true;}
        else if(i==0x10200073){
            wr=false;check(traps,returns+1,"one SRET per trap");check(csrReads,traps*7,"seven CSR reads before SRET");
            next=sepc;check(next,p.resume[returns],"stage safe SRET continuation");v=true;returns++;
            std::cout<<"SRET stage="<<returns<<" pc=0x"<<std::hex<<actualPc<<" next_pc=0x"<<actualNext<<std::dec<<'\n';
        }
        else throw std::runtime_error("unplanned retired instruction");
        check(actualWrites,wr,"retirement write-enable");check(actualNext,next,"independent next PC");
        if(wr){check(rd,d,"architectural RD");check(value,val,op==0x73&&f==2?valueLabel(i>>20):"independent retired value");r[d]=val;}
        if(op==3&&d==14){
            check(r[10],0x77,"fault destination unchanged after recovery");
            check(r[12],olderValue(returns-1),"stage older value recovered");
            check(r[13],0x1234,"stage fault sentinel recovered");check(r[14],0x9abc,"stage younger sentinel recovered");
            std::cout<<"STAGE_PASS stage="<<returns<<" recovery_loads=3 older=0x"<<std::hex<<r[12]
                     <<" fault_sentinel=0x"<<r[13]<<" younger_sentinel=0x"<<r[14]<<std::dec<<'\n';
        }
        pc=next;commits++;
    }
    void trap(uint64_t epc,uint64_t actualCause,uint64_t tv,uint64_t rawGpa,bool gp,bool ga,bool implicit){
        check(traps<stageCount,1,"no extra trap");unsigned s=traps;const auto&t=stages[s];
        std::cout<<"TRAP stage="<<s+1<<" name="<<t.name<<" epc=0x"<<std::hex<<epc<<" cause=0x"<<actualCause<<" stval=0x"<<tv<<" raw_gpa=0x"<<rawGpa<<std::dec<<" gp="<<gp<<" gva="<<ga<<" implicit="<<implicit<<'\n';
        check(v,1,"fault originates in VS");check(traps,returns,"previous trap returned");
        check(epc,p.faultPc[s],"independent fault EPC");check(epc,pc,"precise retirement frontier");
        check(actualCause,t.cause,"independent fault cause");check(tv,t.tval,"independent fault STVAL");
        check(rawGpa,t.gpa,"independent raw GPA");check(gp,t.guestPageFault,"guest-page-fault classification");
        check(ga,t.guestAddress,"guest-address provenance");check(implicit,t.implicitPte,"implicit-PTE classification");
        check(r[10],0x77,"fault destination unchanged");check(r[11],olderValue(s),"older store read before fault");
        check(recoveryLoads,s*3,"previous stage recovery completed");check(storeRetired,s+1,"permitted store retired before fault");
        sepc=p.faultPc[s];pc=HS;v=false;traps++;
    }
};
static void run(unsigned schedule,const std::string&control){
    Program p;Memory m;p.load(m);Oracle o(p,control);
    auto allocated=std::make_unique<SHypervisorPlatformGsim>();auto&d=*allocated;
    static_assert(std::is_trivially_copyable_v<SHypervisorPlatformGsim>);std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();initialize(d,m);
    std::cout<<"INITIALIZED schedule="<<schedule<<" resets=1 image_loads=1 tables=static metadata_writes_after_bootstrap=0\n";
    std::deque<Request> owners[2];Request heldReq[2];Response heldRsp[2];bool holdQ[2]{},holdR[2]{};
    unsigned nextOwner[2]{},requests[2]{},replies[2]{},heldRequests[2]{},heldResponses[2]{};
    unsigned stores=0,clears=0,pteReads=0,parcels=0,commitClosed=0;std::set<uint64_t> reads;
    for(unsigned cycle=0;cycle<1000000;cycle++){
        unsigned rq=3,rp=3;bool commit=true;
        if(schedule==1){rq=(cycle%5==1?0:1)|(cycle%7==2?0:2);rp=(cycle%7<3?0:1)|(cycle%9<4?0:2);commit=cycle%11!=3;}
        if(schedule==2){rq=(cycle%41<29?0:1)|(cycle%43<31?0:2);rp=(cycle%47<35?0:1)|(cycle%53<39?0:2);commit=cycle%37>=23;}
        // Close each lane until its first real offer has been held twice.
        // Count observed backpressure, not merely cycles with a closed gate.
        if(schedule)for(unsigned lane=0;lane<2;lane++){
            if(heldRequests[lane]<2)rq&=~(1U<<lane);
            if(heldResponses[lane]<2)rp&=~(1U<<lane);
        }
        commitClosed+=!commit;d.set_io$$enable(1);d.set_io$$commitEnable(commit);d.set_io$$sources(0);
        d.set_io$$allowRequest(rq);d.set_io$$allowResponse(rp);d.step();
        for(unsigned lane=0;lane<2;lane++){
            Request q=request(d,lane);Response r=response(d,lane);
            bool qr=(d.get_io$$scalarRequestReady()>>lane)&1,rr=(d.get_io$$scalarResponseReady()>>lane)&1;
            if(holdQ[lane])o.check(q==heldReq[lane],1,"scalar request held stable");
            if(holdR[lane])o.check(r==heldRsp[lane],1,"scalar response held stable");
            holdQ[lane]=q.valid&&!qr;holdR[lane]=r.valid&&!rr;heldReq[lane]=q;heldRsp[lane]=r;
            heldRequests[lane]+=holdQ[lane];heldResponses[lane]+=holdR[lane];
            if(r.valid&&rr){
                o.check(!owners[lane].empty(),1,"native response has accepted owner");Request prior=owners[lane].front();owners[lane].pop_front();
                o.check(r.owner,prior.owner,"native response owner order");o.check(r.clear,prior.clear,"native clear identity");
                o.check(r.error,0,"physical response success");o.check(r.pageFault,0,"fabric does not invent page faults");
                if(!prior.clear&&!prior.write)o.check(r.data,m.get(prior.address&~7ULL,8),"native full 64-bit response beat");
                replies[lane]++;
            }
            if(q.valid&&qr){
                o.check(q.owner,nextOwner[lane]++&15,"native sequential owner allocation");o.check(q.lookup,1,"native coherence lookup");
                if(q.clear){
                    clears++;o.check(lane,0,"reservation clear on data lane");
                    o.check(owners[0].empty()&&owners[1].empty(),1,"clear waits for both older native lanes");
                }else{
                o.check(q.virtualized||q.prechecked||q.epoch||q.prefetch||q.atomic,0,"translation authorization consumed");
                if(q.write){
                    o.check(lane,0,"store on data lane");o.check(stores<stageCount,1,"no extra physical store");
                    o.check(q.address,SPA_DATA+8,"older store physical address");o.check(q.data,olderValue(stores),"stage older store physical data");stores++;
                    o.check(q.size,3,"store size");o.check(q.mask,255,"store byte mask");m.put(q.address,q.data,8);
                }else{
                    reads.insert(q.address);
                    if(lane==0){o.check(q.size,3,"data read width");o.check(q.mask,255,"data read byte mask");
                        o.check(q.address==SPA_DATA||q.address==SPA_DATA+8||q.address==SPA_DATA+16,1,"only safe physical data reads");}
                    else if(q.size==1){parcels++;o.check(q.mask,3U<<(q.address&7),"fetch parcel byte mask");
                        o.check((q.address>=BASE&&q.address<BASE+16384)||(q.address>=0x8020b000&&q.address<0x8020c000),1,"allowed physical instruction parcel");}
                    else{pteReads++;o.check(q.size,3,"physical PTE read width");o.check(q.mask,255,"PTE byte mask");
                        o.check((q.address&7)==0&&q.address>=GROOT&&q.address<0x8020b000,1,"physical table address");}
                    // These specific forbidden reads establish precedence without imposing
                    // an artificial total order on concurrent fetch and data walks.
                    o.check(q.address==GDATALEAF+8,0,"no final right-code G leaf after earlier fault");
                    o.check(q.address>=0x8020a000&&q.address<0x8020b000,0,"inaccessible right VS table must not be read");
                }
                }
                owners[lane].push_back(q);requests[lane]++;
            }
        }
        o.check(d.get_io$$msiRequest$$valid(),0,"no MSI request");o.check(d.get_io$$msiResponse$$valid(),0,"no MSI response");o.check(d.get_io$$msiError(),0,"no MSI error");
#define COMMIT(N) if(d.get_io$$commit##N##$$valid())o.commit(d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),d.get_io$$commit##N##$$bits$$writesRd())
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(d.get_io$$trap$$valid())o.trap(d.get_io$$trap$$bits$$pc(),d.get_io$$trap$$bits$$cause(),d.get_io$$trap$$bits$$tval(),d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),d.get_io$$trap$$bits$$guestFault$$guestPageFault(),d.get_io$$trap$$bits$$guestFault$$guestAddress(),d.get_io$$trap$$bits$$guestFault$$implicitPte());
        if(o.r[31]==99&&owners[0].empty()&&!request(d,0).valid){
            o.check(clears,stageCount,"five ordered reservation clears");o.check(o.traps,stageCount,"five different consecutive traps");
            o.check(o.returns,stageCount,"five SRET returns");o.check(o.csrReads,stageCount*7,"all 35 trap CSR reads retired");
            o.check(o.r[10],0x77,"no fault destination effect");o.check(o.recoveryLoads,stageCount*3,"all stage recovery loads");
            o.check(stores,stageCount,"five physical older stores");o.check(o.storeRetired,stageCount,"five architectural older stores");
            o.check(m.get(SPA_DATA+8,8),olderValue(4),"last older store preserved");
            o.check(m.get(SPA_DATA,8),0x1234,"fault sentinel unchanged");o.check(m.get(SPA_DATA+16,8),0x9abc,"younger store sentinel unchanged");
            o.check(o.r[12],olderValue(4),"older store read after final recovery");
            o.check(o.r[13],0x1234,"fault sentinel read after recovery");o.check(o.r[14],0x9abc,"younger sentinel read after recovery");
            for(uint64_t critical:{GPTLEAF+24,uint64_t(0x80209000)+508*8,uint64_t(0x80209000)+509*8,GDATALEAF+24})
                o.check(reads.count(critical),1,"critical fault-path PTE read occurred");
            o.check(reads.count(0x8020bffe),1,"split left physical parcel read");
            o.check(requests[0],replies[0],"data owner drain");o.check(pteReads>0&&parcels>0,1,"actual nested instruction traffic");
            if(schedule)o.check(heldRequests[0]>=2&&heldRequests[1]>=2&&heldResponses[0]>=2&&heldResponses[1]>=2,1,"both native lanes actually stalled twice");
            // Fetch may still have live owners for the terminal loop. This does
            // not claim total fetch quiescence or speculative younger issue.
            std::cout<<"TRAP_SEQUENCE_PASS schedule="<<schedule<<" stages=5 cycles="<<cycle+1<<" commits="<<o.commits
                     <<" checks="<<o.checks<<" traps="<<o.traps<<" returns="<<o.returns<<" clears="<<clears<<" stores="<<stores
                     <<" csr_reads="<<o.csrReads<<" pte_reads="<<pteReads<<" parcels="<<parcels
                     <<" requests="<<requests[0]<<","<<requests[1]<<" responses="<<replies[0]<<","<<replies[1]
                     <<" held_requests="<<heldRequests[0]<<","<<heldRequests[1]<<" held_responses="<<heldResponses[0]<<","<<heldResponses[1]
                     <<" commit_closed="<<commitClosed<<" fetch_owners_remaining="<<owners[1].size()<<'\n';
            return;
        }
    }
    throw std::runtime_error("bounded platform timeout pc="+std::to_string(o.pc));
}

int main(int argc,char**argv){
    try{
        if(argc<2||argc>3)throw std::runtime_error("usage: hypervisor_trap_sequence OUTPUT_DIRECTORY [stale-htval|stale-htinst|stale-gva]");
        const std::filesystem::path directory(argv[1]);std::filesystem::create_directories(directory);
        std::string control=argc==3?argv[2]:"";
        if(!control.empty()&&control!="stale-htval"&&control!="stale-htinst"&&control!="stale-gva")throw std::runtime_error("unknown expectation control");
        const char* schedules[]={"open","staggered","long"};
        auto execute=[&](unsigned schedule){
            std::string file=std::string(schedules[schedule])+(control.empty()?"":"-"+control)+".trace";
            std::ofstream trace(directory/file);if(!trace)throw std::runtime_error("cannot open trace file");
            std::ostringstream captured;auto* original=std::cout.rdbuf(captured.rdbuf());
            try{run(schedule,control);}
            catch(...){std::cout.rdbuf(original);trace<<captured.str();std::cout<<captured.str();throw;}
            std::cout.rdbuf(original);trace<<captured.str();std::cout<<captured.str();
        };
        if(!control.empty()){execute(0);throw std::runtime_error("stale expectation was not rejected");}
        for(unsigned schedule=0;schedule<3;schedule++)execute(schedule);
        std::cout<<"TRAP_SEQUENCES_ALL_PASS sequences=3 stages_per_sequence=5 traps=15\n";return 0;
    }catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}
}
