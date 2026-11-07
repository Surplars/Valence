// Independent RV64 privileged counter oracle. Real ROM/RAM and fetch/ROB/MSU are
// in the GSIM model; this driver supplies only cold images and legal backpressure.
#include "GuestCountersPlatformGsim.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <deque>
#include <iostream>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <vector>

static constexpr uint64_t BASE=0x80000000, GUEST=BASE+0x600, HANDLER=BASE+0xc00;
static uint32_t addi(unsigned d,unsigned s,int n){return(uint32_t(n)&4095)<<20|s<<15|d<<7|0x13;}
static uint32_t shift(unsigned d,unsigned s,unsigned n){return n<<20|s<<15|1<<12|d<<7|0x13;}
static uint32_t csr(unsigned c,unsigned f,unsigned s,unsigned d=0){return c<<20|s<<15|f<<12|d<<7|0x73;}
static int64_t sext(uint64_t v,unsigned n){return int64_t(v<<(64-n))>>(64-n);}
struct Check {
    uint64_t count=0;
    void operator()(uint64_t got,uint64_t expected,const char* text){
        ++count;if(got!=expected){std::cerr<<text<<" got=0x"<<std::hex<<got<<" expected=0x"<<expected<<std::dec<<'\n';throw std::runtime_error(text);}
    }
};
struct Profile {const char*name;bool vu;unsigned m,h,s;};
static const Profile profiles[]={{"vs",false,5,5,5},{"vs-h-denied",false,5,1,5},
    {"vu-s-denied",true,5,5,1},{"vs-m-priority",false,1,0,5}};
struct Instruction {uint32_t bits;unsigned bytes;};
struct Event {uint64_t pc;Instruction instruction;unsigned cause;};
struct Program {
    std::map<uint64_t,Instruction> code;std::array<uint8_t,4096> image{};
    std::vector<Event> trace;uint64_t pc=BASE,holdMarker=0,done=0;Profile profile;
    explicit Program(Profile p):profile(p){
        set(0x3b0,~0ULL);set(0x3a0,31);set(0x105,HANDLER);set(0x305,BASE+0xe00);
        for(unsigned c:{0x304U,0x104U,0x204U,0x604U,0x603U,0x602U,0x303U,0x645U})set(c,0);
        set(0x302,(1ULL<<2)|(1ULL<<22)); // only synchronous guest faults are delegated to HS
        set(0x320,5);set(0xb00,~0ULL-2);set(0xb02,~0ULL-1);
        emit(csr(0xb00,2,0,10));emit(csr(0xb02,2,0,11));emit(csr(0x320,2,0,12));
        li(1,1);emit(csr(0xb00,2,1,13));emit(csr(0xb00,3,1,14));
        set(0x320,0);holdMarker=pc;emit(csr(0x320,2,0,15));
        // A deliberate retirement pause lets real scalar fetch fill a ROB with
        // independent 16- and 32-bit instructions before the two-lane release.
        for(unsigned n=0;n<8;n++){emit(uint16_t(0x0001),2);emit(addi(8+n,0,30+n));}
        set(0x320,5);emit(csr(0xb00,2,0,16));emit(csr(0xb02,2,0,17));
        set(0xb00,0x100);set(0xb02,0x200);set(0x320,0);
        set(0x306,p.m);set(0x606,p.h);set(0x106,p.s);set(0x280,0);set(0x680,0);
        set(0x341,GUEST);set(0x300,(1ULL<<39)|(p.vu?0:1ULL<<11));emit(0x30200073);
        pc=GUEST;
        emit(0x0001,2);emit(addi(5,0,7));emit(0x0285,2); // C.ADDI x5,1
        emit(csr(0xc00,2,0,18));emit(csr(0xc02,2,0,19));
        li(1,0);emit(csr(0xc00,2,1,20)); // nonzero encoded rs1, zero value: still RO write
        emit(csr(0xc82,2,0,21));emit(csr(0xb02,2,0,22));
        emit(csr(0xc00,6,0,23));emit(csr(0xc02,7,0,24));
        emit(0x0001,2);done=pc;emit(addi(31,0,99));emit(0x6f);
        pc=HANDLER;emit(csr(0x142,2,0,25));emit(csr(0x141,2,0,26));emit(csr(0x143,2,0,27));
        emit(addi(26,26,4));emit(csr(0x141,1,26));emit(0x10200073);
        pc=BASE+0xe00;emit(addi(31,0,-1));emit(0x6f);
        // Build the complete finite architectural event stream before allocating DUT.
        uint64_t next=BASE,resume=0;bool guest=false;
        for(unsigned budget=0;budget<1000;budget++){
            const auto i=code.at(next);unsigned cause=guest?permission(i.bits):0;
            trace.push_back({next,i,cause});
            if(cause){resume=next+4;next=HANDLER;guest=false;}
            else if(i.bits==0x30200073){next=GUEST;guest=true;}
            else if(i.bits==0x10200073){next=resume;guest=true;}
            else if(next==done)return;
            else next+=i.bytes;
        }
        throw std::runtime_error("finite reference trace did not reach sentinel");
    }
    unsigned permission(uint32_t i)const{
        if((i&127)!=0x73||!((i>>12)&7))return 0;
        unsigned c=i>>20,f=(i>>12)&7,s=(i>>15)&31;
        bool write=(f&3)==1||s!=0;
        if(c!=0xc00&&c!=0xc02)return 2;
        if(write)return 2;
        unsigned bit=c==0xc00?1:4;
        if(!(profile.m&bit))return 2;
        if(!(profile.h&bit)||(profile.vu&&!(profile.s&bit)))return 22;
        return 0;
    }
    void emit(uint32_t i,unsigned bytes=4){code[pc]={i,bytes};if(pc<BASE||pc+bytes>BASE+image.size())throw std::runtime_error("program image range");
        for(unsigned n=0;n<bytes;n++)image.at(pc-BASE+n)=i>>(8*n);pc+=bytes;}
    void li(unsigned r,uint64_t value){emit(addi(r,0,0));bool seen=false;for(int b=7;b>=0;b--){unsigned v=(value>>(8*b))&255;
        if(!seen&&!v)continue;if(seen)emit(shift(r,r,8));emit(addi(r,r,v));seen=true;}}
    void set(unsigned c,uint64_t value){li(1,value);emit(csr(c,1,1));}
    uint64_t memory(uint64_t address,unsigned bytes)const{uint64_t v=0;for(unsigned n=0;n<bytes;n++)v|=uint64_t(image.at(address-BASE+n))<<(8*n);return v;}
};
struct Token {uint64_t index=0,tag=0;bool operator==(const Token&)const=default;};
struct Command {Token token;uint64_t pc=0,data=0,operand=0,writeValue=0;unsigned address=0,cause=0;bool write=false;uint32_t instruction=0;};
struct Request {uint64_t owner=0,address=0,data=0,epoch=0;unsigned size=0,mask=0,atomicOp=0;
    bool valid=false,clear=false,write=false,atomic=false,virtualized=false,prechecked=false,prefetch=false,uncached=false,lookup=false;
    bool operator==(const Request&)const=default;};
struct Response {uint64_t owner=0,data=0;bool valid=false,clear=false,error=false,pageFault=false;bool operator==(const Response&)const=default;};
static Request request(SGuestCountersPlatformGsim&d,unsigned lane){Request r;
#define READ(N) r.valid=d.get_io$$scalar##N##Request$$valid();r.owner=d.get_io$$scalar##N##Request$$bits$$owner();r.clear=d.get_io$$scalar##N##Request$$bits$$clearReservation();r.lookup=d.get_io$$scalar##N##Request$$bits$$needsCoherenceLookup();r.address=d.get_io$$scalar##N##Request$$bits$$memory$$address();r.data=d.get_io$$scalar##N##Request$$bits$$memory$$data();r.size=d.get_io$$scalar##N##Request$$bits$$memory$$size();r.mask=d.get_io$$scalar##N##Request$$bits$$memory$$mask();r.write=d.get_io$$scalar##N##Request$$bits$$memory$$write();r.atomic=d.get_io$$scalar##N##Request$$bits$$memory$$atomic();r.atomicOp=d.get_io$$scalar##N##Request$$bits$$memory$$atomicOp();r.virtualized=d.get_io$$scalar##N##Request$$bits$$memory$$virtualized();r.prechecked=d.get_io$$scalar##N##Request$$bits$$memory$$precheckedLoad();r.epoch=d.get_io$$scalar##N##Request$$bits$$memory$$translationEpoch();r.prefetch=d.get_io$$scalar##N##Request$$bits$$memory$$prefetchNextAllowed();r.uncached=d.get_io$$scalar##N##Request$$bits$$memory$$uncached()
    if(lane){READ(1);}else{READ(0);}
#undef READ
    if(r.clear){r.address=r.data=r.epoch=0;r.size=r.mask=r.atomicOp=0;r.write=r.atomic=r.virtualized=r.prechecked=r.prefetch=r.uncached=false;}
    return r;
}
static Response response(SGuestCountersPlatformGsim&d,unsigned lane){Response r;
#define READ(N) r.valid=d.get_io$$scalar##N##Response$$valid();r.owner=d.get_io$$scalar##N##Response$$bits$$owner();r.clear=d.get_io$$scalar##N##Response$$bits$$clearReservation();r.data=d.get_io$$scalar##N##Response$$bits$$memory$$data();r.error=d.get_io$$scalar##N##Response$$bits$$memory$$error();r.pageFault=d.get_io$$scalar##N##Response$$bits$$memory$$pageFault()
    if(lane){READ(1);}else{READ(0);}
#undef READ
    return r;
}
struct Owner {Request request;uint64_t data;};
struct Oracle {
    uint64_t cycle=0,instret=0,registers[32]{},commits=0,traps=0,samples=0,compressed=0;
    unsigned inhibit=0;std::map<unsigned,uint64_t> csrs;std::map<uint64_t,Command> commands;
    size_t event=0;bool guest=false;uint64_t resume=0;const Program&p;Check&check;std::string negative;bool injected=false;
    Oracle(const Program&program,Check&c,std::string n):p(program),check(c),negative(n){}
    uint64_t read(unsigned c)const{
        if(c==0xb00||c==0xc00)return cycle;if(c==0xb02||c==0xc02)return instret;if(c==0x320)return inhibit;
        auto i=csrs.find(c);return i==csrs.end()?0:i->second;
    }
    void start(SGuestCountersPlatformGsim&d){
        Command c;c.pc=d.get_io$$systemPc();c.instruction=d.get_io$$systemInstruction();c.operand=d.get_io$$systemOperand();
        c.token={d.get_io$$systemToken$$index(),d.get_io$$systemToken$$tag()};
        check(c.pc,p.trace.at(event).pc,"system sample exact architectural frontier");
        check(c.instruction,p.trace.at(event).instruction.bits,"system sample independent instruction");
        unsigned f=(c.instruction>>12)&7,s=(c.instruction>>15)&31;c.address=c.instruction>>20;c.cause=p.trace.at(event).cause;
        if(f){check(c.operand,registers[s],"system operand from independent retired registers");c.data=0;
            c.write=(f&3)==1||s!=0;uint64_t source=f>=5?s:registers[s];
            c.writeValue=source;
        }
        check(commands.empty(),1,"one actual system owner at a time");commands.emplace(c.token.tag,c);++samples;
        std::cout<<"COUNTER_SAMPLE case="<<p.profile.name<<" pc="<<c.pc<<" instruction="<<c.instruction<<" index="<<c.token.index<<" tag="<<c.token.tag
            <<" operand="<<c.operand<<" cycle="<<cycle<<" instret="<<instret<<" inhibit="<<inhibit<<" expected="<<c.data<<" cause="<<c.cause<<'\n';
    }
    void execute(){
        check(commands.size(),1,"execute has captured start owner");auto&c=commands.begin()->second;
        unsigned f=(c.instruction>>12)&7,s=(c.instruction>>15)&31;
        if(f){c.data=read(c.address);uint64_t source=f>=5?s:c.operand;
            c.writeValue=(f&3)==1?source:(f&3)==2?c.data|source:c.data&~source;}
        std::cout<<"COUNTER_EXECUTE case="<<p.profile.name<<" pc="<<c.pc<<" index="<<c.token.index<<" tag="<<c.token.tag
            <<" cycle="<<cycle<<" instret="<<instret<<" inhibit="<<inhibit<<" expected="<<c.data<<" writeValue="<<c.writeValue<<'\n';
    }
    void completion(SGuestCountersPlatformGsim&d){
        check(!commands.empty(),1,"completion has sampled owner");auto&c=commands.begin()->second;
        check(d.get_io$$systemException(),c.cause!=0,"sampled exception stable");
        unsigned f=(c.instruction>>12)&7;bool read=(f&3)!=1||((c.instruction>>7)&31)!=0;
        if(!c.cause&&f)check(d.get_io$$systemData(),read?c.data:0,"sampled read held independently");
        std::cout<<"COUNTER_COMPLETE case="<<p.profile.name<<" pc="<<c.pc<<" tag="<<c.token.tag<<" data="<<d.get_io$$systemData()<<" exception="<<unsigned(d.get_io$$systemException())<<'\n';
    }
    void commit(uint64_t pc,uint32_t bits,unsigned rd,bool writes,uint64_t data,uint64_t next,Token token,
                bool&counterWrite,unsigned&writeAddress,uint64_t&writeValue){
        check(event<p.trace.size(),1,"finite retirement stream");const auto&e=p.trace.at(event);
        check(e.cause,0,"faulted instructions excluded from retirement");check(pc,e.pc,"independent retired PC");
        check(bits,e.instruction.bits,"independent retired instruction");uint64_t value=0,target=pc+e.instruction.bytes;
        bool wr=false;unsigned destination=(bits>>7)&31,op=bits&127,f=(bits>>12)&7,a=(bits>>15)&31;
        if(e.instruction.bytes==2){++compressed;if(bits==0x0001){destination=0;wr=false;}else if(bits==0x0285){destination=5;wr=true;value=registers[5]+1;}else throw std::runtime_error("unrecognized compressed reference instruction");}
        else if(op==0x13){wr=destination!=0;value=f==0?registers[a]+sext(bits>>20,12):registers[a]<<((bits>>20)&63);}
        else if(op==0x73){auto it=commands.find(token.tag);check(it!=commands.end(),1,"retired system has sampled token");auto c=it->second;
            check(c.token==token,1,"full system retirement token");check(c.pc,pc,"system owner PC");check(c.cause,0,"no faulting system retirement");
            if(f){wr=destination!=0;value=c.data;
                if(c.write){if(c.address==0xb00||c.address==0xb02||c.address==0x320){check(counterWrite,0,"single counter write per edge");counterWrite=true;writeAddress=c.address;writeValue=c.writeValue;}
                    else csrs[c.address]=c.writeValue;}
            }else if(bits==0x30200073){target=GUEST;guest=true;}
            else if(bits==0x10200073){target=csrs[0x141];guest=true;}
            else throw std::runtime_error("unrecognized system reference instruction");
            commands.erase(it);
        }else throw std::runtime_error("unrecognized retired reference instruction");
        check(writes,wr,"independent retired write enable");if(wr){check(rd,destination,"independent retired destination");
            uint64_t expected=value;if(negative=="retired-value"&&!injected&&op==0x73&&f){expected^=1;injected=true;}
            check(data,expected,"independent retired value");registers[destination]=value;}
        check(next,target,"independent retired next PC");
        std::cout<<"COUNTER_RETIRE case="<<p.profile.name<<" index="<<commits<<" pc="<<pc<<" instruction="<<bits<<" tokenIndex="<<token.index<<" tokenTag="<<token.tag
            <<" writes="<<writes<<" rd="<<rd<<" value="<<data<<" next="<<next<<" cycle="<<cycle<<" instret="<<instret<<'\n';
        ++event;++commits;
    }
    void trap(SGuestCountersPlatformGsim&d){
        check(guest,1,"synchronous trap originates only in VS or VU");const auto&e=p.trace.at(event);check(e.cause!=0,1,"expected finite synchronous trap");
        check(d.get_io$$trap$$bits$$pc(),e.pc,"independent trap PC");unsigned cause=e.cause;
        if(negative=="trap-cause"&&!injected){cause^=1;injected=true;}
        check(d.get_io$$trap$$bits$$cause(),cause,"independent trap cause");check(d.get_io$$trap$$bits$$tval(),e.instruction.bits,"independent trap tval");
        check(d.get_io$$trap$$bits$$guestFault$$guestPageFault()||d.get_io$$trap$$bits$$guestFault$$guestAddress()||
            d.get_io$$trap$$bits$$guestFault$$implicitPte()||d.get_io$$trap$$bits$$guestFault$$guestPhysicalAddress(),0,"counter trap has no guest memory fault metadata");
        auto tag=d.get_io$$trap$$bits$$token$$tag();auto it=commands.find(tag);check(it!=commands.end(),1,"fault has sampled owner");
        check(it->second.token.index,d.get_io$$trap$$bits$$token$$index(),"fault full owner index");commands.erase(it);
        csrs[0x142]=e.cause;csrs[0x141]=e.pc;csrs[0x143]=e.instruction.bits;guest=false;++traps;++event;
        std::cout<<"COUNTER_TRAP case="<<p.profile.name<<" pc="<<d.get_io$$trap$$bits$$pc()<<" cause="<<d.get_io$$trap$$bits$$cause()<<" tval="<<d.get_io$$trap$$bits$$tval()<<" tokenIndex="<<unsigned(d.get_io$$trap$$bits$$token$$index())<<" tokenTag="<<d.get_io$$trap$$bits$$token$$tag()<<" instruction="<<e.instruction.bits<<" instret="<<instret<<'\n';
    }
    void edge(unsigned count,bool write,unsigned address,uint64_t value,bool fault){
        if(!(inhibit&1))++cycle;if(!(inhibit&4))instret+=count;
        if(write){if(address==0xb00)cycle=value;else if(address==0xb02)instret=value;else inhibit=value&5;}
        if(negative=="fault-count"&&!injected&&fault){++instret;injected=true;}
    }
    void observed(SGuestCountersPlatformGsim&d){uint64_t expected=cycle;if(negative=="counter-edge"&&!injected&&samples){expected++;injected=true;}
        check(d.get_io$$cycle(),expected,"independent cycle edge");check(d.get_io$$instret(),instret,"independent instret edge");
        check(d.get_io$$inhibit(),inhibit,"independent inhibit edge");}
};
static void run(Profile profile,unsigned schedule,const std::string&negative){
    const Program p(profile);Check check;Oracle o(p,check,negative);
    auto storage=std::make_unique<SGuestCountersPlatformGsim>();auto&d=*storage;
    static_assert(std::is_trivially_copyable_v<SGuestCountersPlatformGsim>);
    std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
    d.set_io$$enable(0);d.set_io$$commitEnable(0);d.set_io$$allowRequest(3);d.set_io$$allowResponse(3);
    d.set_reset(1);d.step();d.step();d.set_reset(0);
    // Programming clocks are real uninhibited mcycle clocks, even with enable=0.
    for(unsigned n=0;n<1024;n++){
        d.set_io$$program$$valid(1);d.set_io$$program$$bits$$index(n);d.set_io$$program$$bits$$data(p.memory(BASE+n*4,4));
        d.set_io$$ramProgram$$valid(n<512);d.set_io$$ramProgram$$bits$$index(n&511);d.set_io$$ramProgram$$bits$$data(0);
        d.step();o.observed(d);check(d.get_io$$commit0$$valid()||d.get_io$$commit1$$valid()||d.get_io$$trap$$valid(),0,"cold image has no retirement");
        check(request(d,0).valid||request(d,1).valid,0,"cold image has no physical requests");o.edge(0,false,0,0,false);
    }
    d.set_io$$program$$valid(0);d.set_io$$ramProgram$$valid(0);
    std::deque<Owner> owners[2];Request heldQ[2];Response heldR[2];bool holdQ[2]{},holdR[2]{};
    unsigned accepted[2]{},returned[2]{},requestStalls[2]{},responseStalls[2]{};
    uint64_t dual=0,commitHolds=0,writeHolds=0,burstHolds=0,clears=0,cycleEdges=1024;
    unsigned hold=0;bool delayed=false,burst=false,terminal=false;
    // The prebuilt trace bounds the number of ROM parcels and control drains.
    // Each parcel needs one finite scalar-fabric owner. Schedule 2 closes its
    // request/response gates for at most 9/11 clocks; 512 clocks/event is generous
    // fixed service slack, not a measured-throughput or formal liveness claim.
    const uint64_t limit=4096+p.trace.size()*512ULL;
    std::cout<<"COUNTER_RUN case="<<profile.name<<" schedule="<<schedule<<" coldEdges=1024 traceEvents="<<p.trace.size()<<" watchdog="<<limit<<'\n';
    for(uint64_t edge=0;edge<limit;edge++){
        bool allowCommit=!terminal&&hold==0&&(schedule==1||edge%13>=3);
        if(hold)--hold;if(!allowCommit)++commitHolds;
        unsigned rq=schedule==1?3:((edge%13<7?0:1)|(edge%17<9?0:2));
        unsigned rp=schedule==1?3:((edge%17<9?0:1)|(edge%19<11?0:2));
        // On each lane, first deliberately hold at least two offered requests and
        // responses. This never withdraws a valid already exposed to the receiver.
        if(schedule==2)for(unsigned lane=0;lane<2;lane++){
            if(requestStalls[lane]<2)rq&=~(1U<<lane);if(responseStalls[lane]<2)rp&=~(1U<<lane);
        }
        d.set_io$$enable(1);d.set_io$$commitEnable(allowCommit);d.set_io$$allowRequest(rq);d.set_io$$allowResponse(rp);
        d.step();o.observed(d);++cycleEdges;
        check(d.get_io$$msiActive()||d.get_io$$msiError()||d.get_io$$interruptPending(),0,"all IRQ sources and enables disabled");
        for(unsigned lane=0;lane<2;lane++){
            Request q=request(d,lane);Response r=response(d,lane);
            bool qr=(d.get_io$$scalarRequestReady()>>lane)&1,rr=(d.get_io$$scalarResponseReady()>>lane)&1;
            if(holdQ[lane])check(q==heldQ[lane],1,"held physical request unchanged");
            if(holdR[lane])check(r==heldR[lane],1,"held physical response unchanged");
            holdQ[lane]=q.valid&&!qr;holdR[lane]=r.valid&&!rr;heldQ[lane]=q;heldR[lane]=r;
            requestStalls[lane]+=holdQ[lane];responseStalls[lane]+=holdR[lane];
            if(q.valid&&lane==0)check(q.clear,1,"no unexpected physical data offer");
            if(r.valid&&rr){check(!owners[lane].empty(),1,"response has accepted real fabric owner");auto old=owners[lane].front();owners[lane].pop_front();
                check(r.owner,old.request.owner,"physical response owner");check(r.clear,old.request.clear,"physical clear response");
                check(r.error||r.pageFault,0,"hardware fabric response success");if(!r.clear)check(r.data,old.data,"independent ROM response bytes");++returned[lane];}
            if(q.valid&&qr){check(q.owner,accepted[lane]&15,"physical full owner sequence");++accepted[lane];check(q.lookup,1,"real common coherence lookup");
                uint64_t expected=0;if(q.clear){check(lane,0,"trap clear only data lane");++clears;}
                else{check(lane,1,"no program physical data transaction");check(q.write||q.atomic||q.virtualized||q.prechecked||q.epoch||q.prefetch||q.uncached,0,"bare ordinary fetch physical attributes");
                    check(q.size,1,"real two-byte fetch parcel");check(q.address>=BASE&&q.address+2<=BASE+4096&&!(q.address&1),1,"bounded ROM parcel");
                    check(q.mask,3U<<(q.address&7),"fetch parcel byte mask");expected=p.memory(q.address&~7ULL,8);}
                owners[lane].push_back({q,expected});
                std::cout<<"COUNTER_REQUEST case="<<profile.name<<" schedule="<<schedule<<" edge="<<edge<<" lane="<<lane<<" owner="<<q.owner<<" address="<<q.address<<" clear="<<q.clear<<'\n';
            }
        }
        bool systemStart=d.get_io$$systemStart();
        if(systemStart){o.start(d);unsigned c=d.get_io$$systemInstruction()>>20;
            if(c==0xb00&&!delayed){hold=9;delayed=true;++writeHolds;}}
        if(d.get_io$$systemExecute())o.execute();
        if(d.get_io$$systemComplete())o.completion(d);
        unsigned count=d.get_io$$commit0$$valid()+d.get_io$$commit1$$valid();
        check(!count||allowCommit,1,"retirement obeys public backpressure");dual+=count==2;
        bool write=false;unsigned address=0;uint64_t value=0;
#define COMMIT(N) if(d.get_io$$commit##N##$$valid()){auto pc=d.get_io$$commit##N##$$bits$$pc();o.commit(pc,d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),{d.get_io$$commit##N##$$bits$$token$$index(),d.get_io$$commit##N##$$bits$$token$$tag()},write,address,value);if(pc==p.holdMarker&&!burst){hold=768;burst=true;++burstHolds;}}
        COMMIT(0);COMMIT(1);
#undef COMMIT
        bool fault=d.get_io$$trap$$valid();if(fault)o.trap(d);
        std::cout<<"COUNTER_EDGE case="<<profile.name<<" schedule="<<schedule<<" edge="<<edge<<" cycle="<<d.get_io$$cycle()<<" instret="<<d.get_io$$instret()<<" inhibit="<<unsigned(d.get_io$$inhibit())
            <<" commits="<<count<<" fault="<<fault<<" write="<<write<<" address="<<address<<" value="<<value<<'\n';
        o.edge(count,write,address,value,fault);
        if(o.event==p.trace.size()){
            // One disabled-retirement observation verifies the sentinel increment too.
            if(!terminal){terminal=true;continue;}
            size_t faults=0;for(const auto&e:p.trace)faults+=e.cause!=0;
            check(o.traps,faults,"all finite expected synchronous faults");check(o.commits,p.trace.size()-faults,"all and only successful instructions counted");
            check(o.compressed>=10,1,"real C and 32-bit instructions retired");check(dual>0,1,"deliberate two-lane retirement burst");
            check(writeHolds,1,"counter write held after accepted command");check(burstHolds,1,"deliberate ROB fill pause");
            check(clears,faults,"one physical reservation clear per synchronous trap");check(owners[0].empty(),1,"terminal data clear owners drained");
            for(unsigned lane=0;lane<2;lane++)check(accepted[lane]-returned[lane],owners[lane].size(),"honest terminal fabric ownership");
            if(schedule==2)check(requestStalls[1]>0&&responseStalls[1]>0&&commitHolds>0,1,"legal fetch and commit backpressure exercised");
            for(const auto&owner:owners[1])std::cout<<"COUNTER_TERMINAL_FETCH_OWNER case="<<profile.name<<" schedule="<<schedule<<" owner="<<owner.request.owner<<" address="<<owner.request.address<<'\n';
            std::cout<<"GUEST_COUNTERS_PLATFORM_PASS case="<<profile.name<<" schedule="<<schedule<<" cycles="<<cycleEdges<<" activeCycles="<<edge+1
                <<" commits="<<o.commits<<" traps="<<o.traps<<" compressed="<<o.compressed<<" dual="<<dual<<" checks="<<check.count
                <<" cycle="<<d.get_io$$cycle()<<" instret="<<d.get_io$$instret()<<" inhibit="<<unsigned(d.get_io$$inhibit())<<" accepted="<<accepted[0]<<","<<accepted[1]
                <<" returned="<<returned[0]<<","<<returned[1]<<" terminalFetchOwners="<<owners[1].size()<<" writeHolds="<<writeHolds<<" commitHolds="<<commitHolds<<'\n';
            return;
        }
    }
    throw std::runtime_error("finite trace-derived counter watchdog");
}
int main(int argc,char**argv){try{
    std::string negative;if(argc==2){std::string arg=argv[1],prefix="--negative-control=";
        if(arg.rfind(prefix,0)!=0)throw std::runtime_error("expected --negative-control=NAME");negative=arg.substr(prefix.size());
        if(negative!="retired-value"&&negative!="counter-edge"&&negative!="fault-count"&&negative!="trap-cause")throw std::runtime_error("unknown negative control");
    }else if(argc!=1)throw std::runtime_error("expected zero or one counter argument");
    if(!negative.empty()){run(profiles[0],1,negative);return 0;}
    for(auto profile:profiles)for(unsigned schedule:{1U,2U})run(profile,schedule,negative);
    std::cout<<"GUEST_COUNTERS_ALL_PASS cases=4 runs=8\n";return 0;
}catch(const std::exception&e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
