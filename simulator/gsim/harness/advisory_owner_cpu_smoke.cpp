// Independent bounded M-mode AMO/LRSC + FP handoff guest on the existing tile.
// Reuse immutable raw-byte instruction transport and its separate manager oracle,
// NOT its normal-load-only Run observer or architectural oracle.
#define main historical_normal_guest_main_not_called
#include "registered_raw_certified_cpu.cpp"
#undef main

namespace {
constexpr uint64_t atomAddress = ramBase, fpAddress = ramBase + 64;
struct SmokeExpected { uint32_t instruction; bool writes; unsigned rd; uint64_t value; };
struct AtomicExpected { unsigned op, size; uint64_t address, operand, result; };
struct SmokeProgram {
    Program image{"advisory_owner_atomic_fp", "rom", {}, {}};
    std::vector<SmokeExpected> expected;
    std::vector<AtomicExpected> atomic;
    void emit(uint32_t instruction, bool writes=false, unsigned rd=0, uint64_t value=0) {
        image.code.push_back(instruction); expected.push_back({instruction,writes,rd,value});
    }
    void constant(unsigned rd,uint64_t value) {
        uint64_t current=value>>55;
        emit(imm(rd,0,int(current)),true,rd,current);
        for(int shift=44;shift>=0;shift-=11){
            current<<=11;emit(imm(rd,rd,11,1),true,rd,current);
            unsigned part=(value>>shift)&2047;current+=part;emit(imm(rd,rd,int(part)),true,rd,current);
        }
        require(current==value,"constant arithmetic oracle");
    }
    void amo(unsigned op,unsigned rd,unsigned rs,unsigned size,uint64_t wanted,unsigned addressRegister=1) {
        emit(op<<27|rs<<20|addressRegister<<15|size<<12|rd<<7|0x2f,true,rd,wanted);
        atomic.push_back({op,size,addressRegister==1?atomAddress:atomAddress+8,rs==14?UINT64_C(0x80000005):rs?7u:0u,wanted});
    }
    static uint32_t sd(unsigned rs,unsigned offset,unsigned baseReg=9,unsigned opcode=0x23) {
        return (offset>>5)<<25|rs<<20|baseReg<<15|3u<<12|(offset&31)<<7|opcode;
    }
    static uint32_t fld(unsigned rd,unsigned offset) {return offset<<20|9u<<15|3u<<12|rd<<7|7;}
    SmokeProgram() {
        constant(1,atomAddress);constant(19,atomAddress+8);emit(imm(2,0,7),true,2,7);
        // Initial atomic word 11 -> 18 -> LR18 -> SC7 -> failedSC -> AMO.W14.
        amo(0,3,2,3,11);amo(2,4,0,3,18);amo(3,5,2,3,0);amo(3,6,2,3,1);
        amo(2,21,0,3,7);amo(3,22,2,3,1,19);amo(3,23,2,3,1); // Wrong-address SC fails AND consumes reservation.
        amo(0,7,2,2,7);
        constant(14,UINT64_C(0x80000005));amo(1,15,14,2,14);amo(0,16,2,2,UINT64_C(0xffffffff80000005));
        constant(8,8192);emit(0x30042073); // CSRRS x0,mstatus,x8: FS=Initial.
        emit(0x300028f3,true,17,UINT64_C(0x0000000a00002000)); // CSRRS mstatus verifies actual FS=Initial.
        constant(9,fpAddress);emit(sd(2,56)); // Integer posted store before FP epoch.
        emit(fld(1,0));emit(fld(2,8));
        emit(0x02000053u|2u<<20|1u<<15|3u<<7); // FADD.D f3,f1,f2 RNE; 1.5+2.25=3.75 exact.
        emit(sd(3,16,9,0x27));emit(fld(4,16));
        emit(0xe2000053u|4u<<15|10u<<7,true,10,UINT64_C(0x400e000000000000)); // FMV.X.D
        emit(fld(5,56));emit(0xe2000053u|5u<<15|11u<<7,true,11,7);
        emit(0x00302673,true,12,0); // CSRRS x12,fcsr,x0: exact operation produced no flags.
        emit(0x30002973,true,18,UINT64_C(0x8000000a00006000)); // FS=Dirty and SD after FP writes.
        amo(0,13,2,3,UINT64_C(0x8000000c)); // FP epoch must drain before a subsequent integer AMO.
        image.code.push_back(ebreak);
        require(expected.size()<100 && atomic.size()==11,"bounded explicit guest geometry");
    }
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
    uint64_t cycle=0, atomWord=11, atomicAccepted=0, atomicReplied=0, starts=0, completes=0;
    uint64_t fpEpochCycles=0, fpRetired=0, physicalRequests=0, physicalReplies=0, clearRequests=0,clearReplies=0;
    size_t retired=0;uint64_t reservationAddress=0;unsigned reservationSize=0;
    bool terminal=false,reserved=false,inject=false,injected=false;
    static uint64_t initialWord(unsigned word) {
        return word==0?UINT64_C(0x3ff8000000000000):word==1?UINT64_C(0x4002000000000000):0;
    }
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
        require(pc==romBase+retired*4&&inst==e.instruction&&next==pc+4,"SMOKE_RETIRE_PC_INSTRUCTION");
        if(inject&&!injected&&(inst&127)==0x2f){data^=1;injected=true;std::cerr<<"SMOKE_RETIREMENT_RESULT_OBSERVATION_MUTANT_REACHED\n";}
        require(writes==e.writes&&(!writes||(rd==e.rd&&data==e.value)),"SMOKE_INDEPENDENT_RESULT");
        unsigned op=inst&127;if(op==7||op==0x27||op==0x53)++fpRetired;
        ++retired;
    }
    bool tick(unsigned inspect=0) {
        const auto reply=manager.offer(cycle);bool ready=manager.ready();auto g=grant();
        bool cacheReady=cacheOwners.size()<2&&sinks.size()<2;
        drive(inspect);d.step();
        require(d.get_io$$fetchPrivilege()==3 && d.get_io$$vm$$satp()==0 && d.get_io$$vm$$dataPrivilege()==3,"SMOKE_M_MODE_BARE");
        require(!d.get_proof$$queryOffer()&&!d.get_proof$$queryAccept(),"SMOKE_BARE_VIRTUAL_PROOF");
        fpEpochCycles+=bool(d.get_returnFlow$$fpEpoch());
        if(d.get_m3$$start$$valid()){
            auto token=std::make_pair(unsigned(d.get_m3$$start$$bits$$token$$index()),uint64_t(d.get_m3$$start$$bits$$token$$tag()));
            require(integerStarts.emplace(token,d.get_m3$$start$$bits$$pc()).second,"SMOKE_DUPLICATE_INTEGER_START");++starts;
        }
        if(d.get_m3$$complete$$valid()){
            auto token=std::make_pair(unsigned(d.get_m3$$complete$$bits$$token$$index()),uint64_t(d.get_m3$$complete$$bits$$token$$tag()));
            require(!d.get_m3$$complete$$bits$$exception()&&integerStarts.erase(token)==1,"SMOKE_UNOWNED_OR_FAULT_COMPLETION");++completes;
        }
        if(d.get_io$$physical$$valid()){physicalOwners.push_back(cycle);++physicalRequests;}
        if(d.get_io$$physicalResponse()){require(!physicalOwners.empty(),"SMOKE_UNOWNED_PHYSICAL_REPLY");physicalOwners.pop_front();++physicalReplies;}
#define RET(N) retirement(d.get_io$$commit##N##$$valid(),d.get_io$$commit##N##$$bits$$pc(),d.get_io$$commit##N##$$bits$$instruction(),d.get_io$$commit##N##$$bits$$writesRd(),d.get_io$$commit##N##$$bits$$rd(),d.get_io$$commit##N##$$bits$$data(),d.get_io$$commit##N##$$bits$$nextPc())
        RET(0);RET(1);
#undef RET
        if(d.get_io$$trap$$valid()){
            require(!terminal&&retired==p.expected.size()&&d.get_io$$trap$$bits$$pc()==romBase+4*retired&&
                d.get_io$$trap$$bits$$cause()==3&&d.get_io$$trap$$bits$$tval()==romBase+4*retired,"SMOKE_PRECISE_TERMINAL_TRAP");terminal=true;
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
            if(clear){require(N==1&&terminal,"SMOKE_UNEXPECTED_CLEAR");reserved=false;++clearRequests;}else{ \
                require(N==1&&atomicAccepted<p.atomic.size(),"SMOKE_NONATOMIC_NATIVE_REQUEST");const auto &e=p.atomic[atomicAccepted]; \
                require(d.get_io$$scalar##N##$$request$$bits$$memory$$atomic()&& \
                    d.get_io$$scalar##N##$$request$$bits$$memory$$atomicOp()==e.op&& \
                    d.get_io$$scalar##N##$$request$$bits$$memory$$address()==e.address&& \
                    d.get_io$$scalar##N##$$request$$bits$$memory$$size()==e.size&& \
                    d.get_io$$scalar##N##$$request$$bits$$memory$$mask()==(e.size==3?255:15)&& \
                    d.get_io$$scalar##N##$$request$$bits$$memory$$data()==e.operand&& \
                    !d.get_io$$scalar##N##$$request$$bits$$memory$$write()&& \
                    !d.get_io$$scalar##N##$$request$$bits$$memory$$virtualized(),"SMOKE_ATOMIC_REQUEST_RAW_ORACLE"); \
                if(e.op==2){require(e.address==atomAddress,"SMOKE_LR_EXPECTED_ADDRESS");value=atomWord;reserved=true;reservationAddress=e.address;reservationSize=e.size;}else if(e.op==3){bool success=reserved&&reservationAddress==e.address&&reservationSize==e.size;value=success?0:1;if(success){require(e.address==atomAddress,"SMOKE_SC_DESTINATION");atomWord=e.operand;}reserved=false;} \
                else {value=e.size==2?uint64_t(int64_t(int32_t(atomWord))):atomWord;uint64_t updated=e.op==1?e.operand:atomWord+e.operand;atomWord=e.size==2?((atomWord&UINT64_C(0xffffffff00000000))|uint32_t(updated)):updated;reserved=false;} \
                require(value==e.result,"SMOKE_ATOMIC_SERVICE_EXPECTED_VALUE");++atomicAccepted;} \
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
        if(valid){require(a.address==fpAddress&&a.size==6&&a.opcode==6&&a.param<=1&&!a.corrupt&&a.mask==255,"SMOKE_CACHE_REQUEST_OUTSIDE_ONE_LINE");
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
        require(atomicAccepted==11&&atomicReplied==11&&atomWord==UINT64_C(0x80000013)&&starts==completes&&integerStarts.empty()&&
            physicalRequests==physicalReplies&&physicalOwners.empty()&&clearRequests==clearReplies&&clearRequests>0&&
            fpEpochCycles>0&&fpRetired==8,"SMOKE_FINAL_OBLIGATION_OR_COVERAGE");
        for(unsigned reg:{3u,4u,5u,6u,7u,10u,11u,12u,13u,21u,22u,23u}){require(tick(reg),"SMOKE_INSPECTION_REOPENED_OWNER");
            uint64_t wanted=reg==3?11:reg==4?18:reg==5?0:reg==6?1:reg==7?7:reg==10?UINT64_C(0x400e000000000000):reg==11?7:reg==12?0:reg==13?UINT64_C(0x8000000c):reg==21?7:1;
            require(d.get_io$$committedValue()==wanted,"SMOKE_FINAL_INTEGER_REGISTER");}
        std::cout<<"ADVISORY_OWNER_CPU_SMOKE_PASS cycles="<<cycle<<" retired="<<retired<<" atomics="<<atomicAccepted
            <<" atomic_replies="<<atomicReplied<<" fp_retired="<<fpRetired<<" fp_epoch_cycles="<<fpEpochCycles
            <<" integer_starts="<<starts<<" integer_completes="<<completes<<" physical_requests="<<physicalRequests
            <<" physical_replies="<<physicalReplies<<" clears="<<clearRequests<<'\n';
    }
};
}
int main(int argc,char **argv){try{SmokeProgram program;
    if(argc==2&&std::string(argv[1])=="--oracle-only"){
        require(program.atomic[0].result==11&&program.atomic[3].result==1,"SMOKE_FIXED_ORACLE");
        std::cout<<"ADVISORY_OWNER_SMOKE_ORACLE instructions="<<program.expected.size()<<" atomics="<<program.atomic.size()<<'\n';return 0;}
    SmokeRun run(program,argc==2&&std::string(argv[1])=="--negative-result");run.run();return 0;
}catch(const std::exception &e){std::cerr<<"ADVISORY_OWNER_CPU_SMOKE_FAIL "<<e.what()<<'\n';return 1;}}
