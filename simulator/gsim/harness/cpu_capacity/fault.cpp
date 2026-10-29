#ifndef CAPACITY_ROB_ENTRIES
#error "Bind CAPACITY_ROB_ENTRIES to the generated model specification"
#endif
static_assert(CAPACITY_ROB_ENTRIES==16 || CAPACITY_ROB_ENTRIES==32);
#include "CommonA1CapacityGsim.h"
#include "gsim_model_storage.h"
#include "fault_instruction_service.h"
namespace {
#include "fault_guest.h"
struct SmokeReply {unsigned owner;bool clear;uint64_t data,due;};
class SmokeRun {
    const SmokeProgram &p;
    std::unique_ptr<GsimModelStorage<SCommonA1CapacityGsim>> storage;
    SCommonA1CapacityGsim &d;
    InstructionManager manager;ManagerOracle audit;
    std::array<std::deque<SmokeReply>,2> native;
    std::array<std::set<unsigned>,2> nativeOwners;
    std::map<unsigned,CacheOwner> cacheOwners;
    std::set<unsigned> sinks;std::deque<unsigned> grants;
    std::optional<Request> heldCache;
    std::deque<uint64_t> physicalOwners;
    uint64_t cycle=0, atomicAccepted=0, atomicReplied=0;
    unsigned trapCount=0, certifiedWarm=0;
    uint64_t physicalRequests=0, physicalReplies=0, clearRequests=0,clearReplies=0;
    size_t retired=0;
    std::set<std::pair<unsigned,uint64_t>> retiredTokens;
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
        d.set_io$$dataD$$valid(false);
        auto g=grant();auto entry=g?cacheOwners.at(*g):CacheOwner{};
        d.set_io$$dataGrant$$valid(bool(g));d.set_io$$dataGrant$$bits$$source(g.value_or(0));
        d.set_io$$dataGrant$$bits$$sink(entry.sink);d.set_io$$dataGrant$$bits$$cap(entry.request.param==0?1:0);
        d.set_io$$dataGrant$$bits$$denied(false);d.set_io$$dataGrant$$bits$$corrupt(false);
#define WORD(N) d.set_io$$dataGrant$$bits$$data##N(initialWord(N))
        WORD(0);WORD(1);WORD(2);WORD(3);WORD(4);WORD(5);WORD(6);WORD(7);
#undef WORD
    }
    void retirement(bool valid,uint64_t pc,uint32_t inst,bool writes,unsigned rd,uint64_t data,uint64_t next,unsigned index,uint64_t tag) {
        if(!valid)return;
        require(index<CAPACITY_ROB_ENTRIES,"CAPACITY_RETIRED_INDEX_BOUND");
        require(retiredTokens.emplace(index,tag).second,"CAPACITY_DUPLICATE_RETIRED_TOKEN");
        require(!terminal&&retired<p.expected.size(),"SMOKE_EXTRA_RETIRE");
        const auto &e=p.expected[retired];
        require(pc==e.pc&&inst==e.instruction&&next==pc+4,"SMOKE_RETIRE_PC_INSTRUCTION");

        require(writes==e.writes&&(!writes||(rd==e.rd&&data==e.value)),"SMOKE_INDEPENDENT_RESULT");
        ++retired;
    }
    bool tick(unsigned inspect=0) {
        const auto reply=manager.offer(cycle);bool ready=manager.ready();auto g=grant();
        bool cacheReady=cacheOwners.size()<2&&sinks.size()<2;
        drive(inspect);d.step();
        require(d.get_io$$robOccupancy()<=CAPACITY_ROB_ENTRIES,"CAPACITY_OCCUPANCY_BOUND");
        if(d.get_io$$physical$$valid()){
            require(!d.get_io$$physical$$bits$$write()&&d.get_io$$physical$$bits$$address()==p.warmPa&&
                physicalRequests<p.expectedDataReads,"SECOND_FAULT_FORBIDDEN_PHYSICAL_ACCESS");
            physicalOwners.push_back(cycle);++physicalRequests;}
        if(d.get_io$$physicalResponse()){require(!physicalOwners.empty(),"SMOKE_UNOWNED_PHYSICAL_REPLY");physicalOwners.pop_front();++physicalReplies;}
#define RET(N) retirement(d.get_io$$commit##N##$$valid(),d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc(),d.get_io$$commit##N##$$bits$$token$$index(),d.get_io$$commit##N##$$bits$$token$$tag())
        require(!d.get_io$$commit1$$valid()||d.get_io$$commit0$$valid(),"CAPACITY_NONPREFIX_RETIREMENT");
        RET(0);RET(1);
#undef RET
        if(d.get_io$$trap$$valid()){
            if(inject&&!injected&&trapCount==0) {
                injected=true;std::cerr<<"SECOND_PMP_TVAL_OBSERVATION_MUTANT_REACHED\n";
                require((d.get_io$$trap$$bits$$tval()^1)==p.badVa,"SECOND_FAULT_PRECISE_TVAL");
            }
            if(trapCount==0){require(retired==p.beforeFault&&d.get_io$$trap$$bits$$pc()==p.faultPc&&
                d.get_io$$trap$$bits$$cause()==p.cause&&d.get_io$$trap$$bits$$tval()==p.badVa,
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
    SmokeRun(const SmokeProgram &program,bool negative):p(program),storage(std::make_unique<GsimModelStorage<SCommonA1CapacityGsim>>()),
        d(storage->get()),manager(p.image),audit(p.image),inject(negative){drive();d.set_reset(true);d.step();d.step();d.set_reset(false);}
    void run(){unsigned quiet=0;while(cycle<10000&&quiet<4){if(tick())++quiet;else quiet=0;}
        require(quiet==4,"SMOKE_BOUNDED_DRAIN_TIMEOUT");
        require(trapCount==2&&atomicAccepted==p.expectedPteReads&&atomicReplied==atomicAccepted&&
            physicalRequests==p.expectedDataReads&&
            physicalReplies==physicalRequests&&physicalOwners.empty()&&clearRequests==clearReplies,
            "SECOND_FAULT_FINAL_EXACT_OBLIGATIONS");
        require(!inject,"SECOND_FAULT_NEGATIVE_CONTROL_ESCAPED");
        for(unsigned reg:{2u,4u,21u,22u,23u}) {require(tick(reg),"SECOND_FAULT_INSPECTION_REOPENED_OWNER");
            const uint64_t wanted=reg==2?(p.expectedDataReads?p.warmResult:0):reg==4?0:
                reg==21?p.cause:reg==22?p.badVa:p.faultPc;
            require(d.get_io$$committedValue()==wanted,"SECOND_FAULT_FINAL_REGISTER");}
        std::cout<<"SECOND_PMP_FAULT_CPU_PASS case="<<p.name<<" cause="<<p.cause<<" tval="<<hex(p.badVa)
            <<" cycles="<<cycle<<" retired="<<retired<<" pte_reads="<<atomicAccepted
            <<" data_reads="<<physicalRequests<<" traps="<<trapCount<<'\n';

    }
};
}
int main(int argc,char **argv){try{
    require(argc==2||argc==3,"SECOND_FAULT_ARGUMENTS");
    const bool negative=argc==3&&std::string(argv[2])=="--negative-tval";
    require(argc!=3||negative,"SECOND_FAULT_ARGUMENT");
    require(std::string(argv[1])=="mprv-tor-revoke-load","CAPACITY_SELECTED_FAULT_CASE");
    SmokeProgram program(argv[1]);
    require(program.expected.size()==87,"CAPACITY_FIXED_FAULT_GOLD_COUNT");SmokeRun(program,negative).run();return 0;
}catch(const std::exception&e){std::cerr<<"SECOND_PMP_FAULT_CPU_FAIL "<<e.what()<<'\n';return 1;}}
