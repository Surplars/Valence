// Independent Sv39 warmed-page noncanonical fault/recovery guest; same saved tile objects.
// Reuse immutable raw-byte instruction transport and its separate manager oracle,
// NOT its normal-load-only Run observer or architectural oracle.
#define main historical_normal_guest_main_not_called
#include "registered_raw_certified_cpu.cpp"
#undef main

namespace {
constexpr uint64_t ncVa=0x40000000ULL, ncPa=ramBase+0x10000, ncRoot=ramBase+0x100000;
constexpr uint64_t ncWord=0x1122334455667788ULL, ncHandler=romBase+0x600;
struct SmokeExpected { uint64_t pc; uint32_t instruction; bool writes; unsigned rd; uint64_t value; };
struct SmokeProgram {
    Program image{"certified_ingress_noncanonical", "rom", {}, {}};
    std::vector<SmokeExpected> expected;
    bool superpage; unsigned highBit; uint64_t badVa, faultPc; size_t beforeFault;
    void emit(uint32_t ins,bool writes=false,unsigned rd=0,uint64_t value=0) {
        expected.push_back({romBase+4*image.code.size(),ins,writes,rd,value}); image.code.push_back(ins);
    }
    void constant(unsigned rd,uint64_t value) {
        uint64_t current=value>>55; emit(imm(rd,0,int(current)),true,rd,current);
        for(int shift=44;shift>=0;shift-=11){current<<=11;emit(imm(rd,rd,11,1),true,rd,current);
            unsigned part=(value>>shift)&2047;current+=part;emit(imm(rd,rd,int(part)),true,rd,current);}
        require(current==value,"NC_CONSTANT_ORACLE");
    }
    void writeCsr(unsigned csr,uint64_t value){constant(10,value);emit(csr<<20|10u<<15|1u<<12|0x73);}
    SmokeProgram(bool large,unsigned bit):superpage(large),highBit(bit),badVa(ncVa|(1ULL<<bit)) {
        writeCsr(0x3b0,0x40000000);writeCsr(0x3a0,15);writeCsr(0x305,ncHandler);
        writeCsr(0x180,(8ULL<<60)|(ncRoot>>12));emit(0x12000073);
        writeCsr(0x300,0x20800);constant(1,ncVa);
        for(unsigned n=0;n<16;++n){emit(1u<<15|3u<<12|2u<<7|3,true,2,ncWord);if(n==0||n==15)emit(0x0330000f);}
        constant(1,badVa);emit(0x0330000f);faultPc=romBase+4*image.code.size();beforeFault=expected.size();
        image.code.push_back(1u<<15|3u<<12|3u<<7|3); // Must fault, never retire or write x3.
        image.code.push_back(ebreak); // Wrong-path sentinel cannot become terminal success.
        while(romBase+4*image.code.size()<ncHandler)image.code.push_back(nop);
        require(romBase+4*image.code.size()==ncHandler,"NC_HANDLER_FIXED_APERTURE");
        emit(0x34202073u|21u<<7,true,21,13); // mcause
        emit(0x34302073u|22u<<7,true,22,badVa); // mtval
        emit(0x34102073u|23u<<7,true,23,faultPc); // mepc
        image.code.push_back(ebreak);
    }
    uint64_t pte(uint64_t address) const {
        if(address==ncRoot+8)return ((ncRoot+4096)>>12)<<10|1;
        if(address==ncRoot+4096)return superpage?((ramBase>>12)<<10)|0xc7:((ncRoot+8192)>>12)<<10|1;
        if(!superpage&&address==ncRoot+8192)return (ncPa>>12)<<10|0xc7;
        throw std::runtime_error("NC_UNEXPECTED_PTE_ADDRESS "+hex(address));
    }
    uint64_t physical()const{return superpage?ramBase:ncPa;}
};
struct SmokeReply {unsigned owner;bool clear;uint64_t data,due;};
class SmokeRun {
    const SmokeProgram &p;
    std::unique_ptr<GsimModelStorage<SCommonA1VmPipelineGsim>> storage;
    SCommonA1VmPipelineGsim &d;
    InstructionManager manager;ManagerOracle audit;
    std::array<std::deque<SmokeReply>,2> native;
    std::array<std::set<unsigned>,2> nativeOwners;
    std::map<unsigned,CacheOwner> cacheOwners;
    std::set<unsigned> sinks;std::deque<unsigned> grants;
    std::optional<Request> heldCache;
    std::map<std::pair<unsigned,uint64_t>,uint64_t> integerStarts;
    std::deque<uint64_t> physicalOwners;
    uint64_t cycle=0, atomicAccepted=0, atomicReplied=0, starts=0, completes=0;
    unsigned trapCount=0, certifiedWarm=0;
    uint64_t physicalRequests=0, physicalReplies=0, clearRequests=0,clearReplies=0;
    size_t retired=0;
    bool terminal=false,inject=false,injected=false;
    static uint64_t initialWord(unsigned) {return ncWord;}
    std::optional<unsigned> grant() const {
        if(grants.empty()||cacheOwners.at(grants.front()).due>cycle)return {};
        return grants.front();
    }
    void drive(unsigned inspect=0) {
        d.set_io$$hold(terminal);d.set_io$$inspectRegister(inspect);
        d.set_io$$instructionA$$ready(manager.ready());auto reply=manager.offer(cycle);auto b=reply.value_or(Reply{});
        d.set_io$$instructionD$$valid(bool(reply));
#define ID(F) d.set_io$$instructionD$$bits$$##F(b.F)
        ID(opcode);ID(param);ID(size);ID(source);ID(sink);ID(denied);ID(data);ID(corrupt);
#undef ID
#define NATIVE(N) \
        d.set_io$$scalar##N##$$request$$ready(true); \
        d.set_io$$scalar##N##$$response$$valid(!native[N].empty()&&native[N].front().due<=cycle); \
        d.set_io$$scalar##N##$$response$$bits$$owner(native[N].empty()?0:native[N].front().owner); \
        d.set_io$$scalar##N##$$response$$bits$$clearReservation(!native[N].empty()&&native[N].front().clear); \
        d.set_io$$scalar##N##$$response$$bits$$memory$$data(native[N].empty()?0:native[N].front().data); \
        d.set_io$$scalar##N##$$response$$bits$$memory$$error(false); \
        d.set_io$$scalar##N##$$response$$bits$$memory$$pageFault(false)
        NATIVE(0);NATIVE(1);
#undef NATIVE
        d.set_io$$dataA$$ready(cacheOwners.size()<2&&sinks.size()<2);
        d.set_io$$dataC$$ready(true);d.set_io$$dataE$$ready(true);
        auto g=grant();auto entry=g?cacheOwners.at(*g):CacheOwner{};
        d.set_io$$dataGrant$$valid(bool(g));d.set_io$$dataGrant$$bits$$source(g.value_or(0));
        d.set_io$$dataGrant$$bits$$sink(entry.sink);d.set_io$$dataGrant$$bits$$cap(entry.request.param==0?1:0);
        d.set_io$$dataGrant$$bits$$denied(false);d.set_io$$dataGrant$$bits$$corrupt(false);
#define WORD(N) d.set_io$$dataGrant$$bits$$data##N(initialWord(N))
        WORD(0);WORD(1);WORD(2);WORD(3);WORD(4);WORD(5);WORD(6);WORD(7);
#undef WORD
    }
    void retirement(bool valid,uint64_t pc,uint32_t inst,bool writes,unsigned rd,uint64_t data,uint64_t next) {
        if(!valid)return;
        require(!terminal&&retired<p.expected.size(),"SMOKE_EXTRA_RETIRE");
        const auto &e=p.expected[retired];
        require(pc==e.pc&&inst==e.instruction&&next==pc+4,"SMOKE_RETIRE_PC_INSTRUCTION");
        if(inject&&!injected&&rd==21){data^=1;injected=true;std::cerr<<"SMOKE_RETIREMENT_RESULT_OBSERVATION_MUTANT_REACHED\n";}
        require(writes==e.writes&&(!writes||(rd==e.rd&&data==e.value)),"SMOKE_INDEPENDENT_RESULT");
        ++retired;
    }
    bool tick(unsigned inspect=0) {
        const auto reply=manager.offer(cycle);bool ready=manager.ready();auto g=grant();
        bool cacheReady=cacheOwners.size()<2&&sinks.size()<2;
        drive(inspect);d.step();
        require(d.get_io$$fetchPrivilege()==3,"NC_FETCH_M_MODE");
        if(d.get_proof$$prepared$$valid()&&d.get_proof$$prepared$$bits$$allowed()){
            require(d.get_proof$$prepared$$bits$$address()==ncVa&&
                d.get_proof$$prepared$$bits$$physicalAddress()==p.physical()&&
                d.get_proof$$prepared$$bits$$size()==3,"NC_PEEK_NONCANONICAL_POSITIVE_CERTIFICATE");
        }
        if(d.get_m3$$start$$valid()){
            auto token=std::make_pair(unsigned(d.get_m3$$start$$bits$$token$$index()),uint64_t(d.get_m3$$start$$bits$$token$$tag()));
            require(integerStarts.emplace(token,d.get_m3$$start$$bits$$pc()).second,"SMOKE_DUPLICATE_INTEGER_START");++starts;
            const auto address=d.get_m3$$start$$bits$$address();
            require(address==ncVa||address==p.badVa,"NC_UNEXPECTED_LOAD_START");
            if(address==p.badVa)require(!d.get_m3$$start$$bits$$precheckedLoad(),"NC_NONCANONICAL_ACQUIRED_CERTIFICATE");
            else if(d.get_m3$$start$$bits$$precheckedLoad()){
                require(d.get_m3$$start$$bits$$physicalAddress()==p.physical(),"NC_WARM_CERTIFIED_PA");++certifiedWarm;}

        }
        if(d.get_m3$$complete$$valid()){
            auto token=std::make_pair(unsigned(d.get_m3$$complete$$bits$$token$$index()),uint64_t(d.get_m3$$complete$$bits$$token$$tag()));
            const auto found=integerStarts.find(token);
            require(found!=integerStarts.end(),"NC_UNOWNED_COMPLETION");
            const bool fault=found->second==p.faultPc;
            require(bool(d.get_m3$$complete$$bits$$exception())==fault&&(!fault||
                (d.get_m3$$complete$$bits$$cause()==13&&d.get_m3$$complete$$bits$$tval()==p.badVa)),
                "NC_COMPLETION_PRECISE_FAULT");integerStarts.erase(found);++completes;
        }
        if(d.get_io$$physical$$valid()){
            require(!d.get_io$$physical$$bits$$write()&&d.get_io$$physical$$bits$$address()==p.physical()&&
                physicalRequests<16,"NC_UNAUTHORIZED_PHYSICAL_ACCESS");
            physicalOwners.push_back(cycle);++physicalRequests;}
        if(d.get_io$$physicalResponse()){require(!physicalOwners.empty(),"SMOKE_UNOWNED_PHYSICAL_REPLY");physicalOwners.pop_front();++physicalReplies;}
#define RET(N) retirement(d.get_io$$commit##N##$$valid(),d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc())
        RET(0);RET(1);
#undef RET
        if(d.get_io$$trap$$valid()){
            if(trapCount==0){require(retired==p.beforeFault&&d.get_io$$trap$$bits$$pc()==p.faultPc&&
                d.get_io$$trap$$bits$$cause()==13&&d.get_io$$trap$$bits$$tval()==p.badVa,
                "NC_PRECISE_LOAD_PAGE_FAULT");}
            else {require(trapCount==1&&retired==p.expected.size()&&d.get_io$$trap$$bits$$pc()==ncHandler+12&&
                d.get_io$$trap$$bits$$cause()==3&&d.get_io$$trap$$bits$$tval()==ncHandler+12,
                "NC_HANDLER_TERMINAL_BREAKPOINT");terminal=true;}
            ++trapCount;
        }
        audit.d(bool(reply),d.get_io$$instructionD$$ready(),reply.value_or(Reply{}),cycle);
        if(reply&&d.get_io$$instructionD$$ready())manager.consume();
        Request request{d.get_io$$instructionA$$bits$$address(),d.get_io$$instructionA$$bits$$data(),
            unsigned(d.get_io$$instructionA$$bits$$opcode()),unsigned(d.get_io$$instructionA$$bits$$param()),
            unsigned(d.get_io$$instructionA$$bits$$size()),unsigned(d.get_io$$instructionA$$bits$$source()),
            unsigned(d.get_io$$instructionA$$bits$$mask()),bool(d.get_io$$instructionA$$bits$$corrupt())};
        audit.a(d.get_io$$instructionA$$valid(),ready,request,cycle);
        if(d.get_io$$instructionA$$valid()&&ready)manager.accept(request,cycle);
#define SERVICE(N) \
        if(!native[N].empty()&&native[N].front().due<=cycle&&d.get_io$$scalar##N##$$response$$ready()){ \
            auto old=native[N].front();native[N].pop_front();require(nativeOwners[N].erase(old.owner)==1,"SMOKE_REPLY_OWNER"); \
            if(old.clear)++clearReplies;else ++atomicReplied; } \
        if(d.get_io$$scalar##N##$$request$$valid()){ \
            unsigned owner=d.get_io$$scalar##N##$$request$$bits$$owner(); \
            require(nativeOwners[N].insert(owner).second,"SMOKE_NATIVE_DUPLICATE_OWNER"); \
            bool clear=d.get_io$$scalar##N##$$request$$bits$$clearReservation();uint64_t value=0; \
            if(clear){require(N==1,"SMOKE_UNEXPECTED_CLEAR");++clearRequests;}else{ \
                require(N==1&&!d.get_io$$scalar##N##$$request$$bits$$memory$$atomic()&& \
                    !d.get_io$$scalar##N##$$request$$bits$$memory$$write()&& \
                    d.get_io$$scalar##N##$$request$$bits$$memory$$size()==3,"NC_NON_PTE_NATIVE_REQUEST"); \
                value=p.pte(d.get_io$$scalar##N##$$request$$bits$$memory$$address());++atomicAccepted;} \
            native[N].push_back({owner,clear,value,cycle+serviceLatency}); }
        SERVICE(0);SERVICE(1);
#undef SERVICE
        require(!d.get_io$$dataC$$valid(),"SMOKE_UNEXPECTED_CACHE_RELEASE");
        if(d.get_io$$dataE$$valid())require(sinks.erase(d.get_io$$dataE$$bits$$sink())==1,"SMOKE_UNOWNED_GRANTACK");
        if(g&&d.get_io$$dataGrant$$ready()){require(cacheOwners.erase(*g)==1,"SMOKE_UNOWNED_GRANT");grants.pop_front();}
        Request a{d.get_io$$dataA$$bits$$address(),d.get_io$$dataA$$bits$$data(),unsigned(d.get_io$$dataA$$bits$$opcode()),
            unsigned(d.get_io$$dataA$$bits$$param()),unsigned(d.get_io$$dataA$$bits$$size()),unsigned(d.get_io$$dataA$$bits$$source()),
            unsigned(d.get_io$$dataA$$bits$$mask()),bool(d.get_io$$dataA$$bits$$corrupt())};
        bool valid=d.get_io$$dataA$$valid();if(heldCache)require(valid&&a==*heldCache,"SMOKE_HELD_ACQUIRE_CHANGED");
        if(valid){require((a.address==(p.physical()&~63ULL)||a.address==((p.physical()&~63ULL)+64))&&a.size==6&&a.opcode==6&&a.param<=1&&!a.corrupt&&a.mask==255,"SMOKE_CACHE_REQUEST_OUTSIDE_ONE_LINE");
            if(cacheReady){unsigned sink=0;while(sinks.count(sink))++sink;require(sink<2&&!cacheOwners.count(a.source),"SMOKE_CACHE_OWNER_REUSE");
                sinks.insert(sink);cacheOwners.emplace(a.source,CacheOwner{a,cycle+serviceLatency,sink});grants.push_back(a.source);heldCache.reset();}
            else heldCache=a;
        }else heldCache.reset();
        ++cycle;
        return terminal&&manager.idle()&&audit.idle()&&native[0].empty()&&native[1].empty()&&cacheOwners.empty()&&
            sinks.empty()&&grants.empty()&&!heldCache&&d.get_io$$fetchIdle()&&d.get_io$$privateIdle()&&
            d.get_io$$ownersIdle()&&!d.get_io$$memoryBusy()&&d.get_io$$robOccupancy()==0;
    }
public:
    SmokeRun(const SmokeProgram &program,bool negative):p(program),storage(std::make_unique<GsimModelStorage<SCommonA1VmPipelineGsim>>()),
        d(storage->get()),manager(p.image),audit(p.image),inject(negative){drive();d.set_reset(true);d.step();d.step();d.set_reset(false);}
    void run(){unsigned quiet=0;while(cycle<10000&&quiet<4){if(tick())++quiet;else quiet=0;}
        require(quiet==4,"SMOKE_BOUNDED_DRAIN_TIMEOUT");
        require(trapCount==2&&atomicAccepted==(p.superpage?2u:3u)&&atomicReplied==atomicAccepted&&
            starts==completes&&integerStarts.empty()&&physicalRequests==16&&physicalReplies==16&&
            physicalOwners.empty()&&clearRequests==clearReplies,"NC_FINAL_OBLIGATIONS");
        for(unsigned reg:{2u,3u,21u,22u,23u}){require(tick(reg),"SMOKE_INSPECTION_REOPENED_OWNER");
            uint64_t wanted=reg==2?ncWord:reg==3?0:reg==21?13:reg==22?p.badVa:p.faultPc;
            require(d.get_io$$committedValue()==wanted,"NC_FINAL_REGISTER");}
        std::cout<<"CERTIFIED_INGRESS_NONCANONICAL_CPU_PASS superpage="<<p.superpage<<" high_bit="<<p.highBit
            <<" cycles="<<cycle<<" retired="<<retired<<" pte_requests="<<atomicAccepted
            <<" physical_requests="<<physicalRequests<<" physical_replies="<<physicalReplies
            <<" certified_warm="<<certifiedWarm<<" traps="<<trapCount<<'\n';

    }
};
}
int main(int argc,char **argv){try{
    require(argc<=2,"NC_ARGUMENTS");const std::string arg=argc==2?argv[1]:"";
    require(arg.empty()||arg=="--oracle-only"||arg=="--negative-result","NC_ARGUMENT");
    for(bool superpage:{false,true})for(unsigned bit:{38u,39u}){
        SmokeProgram p(superpage,bit);
        require(p.badVa!=ncVa&&(p.badVa&((1ULL<<38)-1))==ncVa&&p.beforeFault+3==p.expected.size(),"NC_FIXED_ORACLE");
        if(arg!="--oracle-only")SmokeRun(p,arg=="--negative-result").run();
    }
    if(arg=="--oracle-only")std::cout<<"CERTIFIED_INGRESS_NONCANONICAL_ORACLE cases=4\n";
    return 0;
}catch(const std::exception&e){std::cerr<<"CERTIFIED_INGRESS_NONCANONICAL_CPU_FAIL "<<e.what()<<'\n';return 1;}}
