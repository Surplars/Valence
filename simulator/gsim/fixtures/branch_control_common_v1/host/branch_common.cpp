#include "CommonA1BenchmarkGsim.h"
#include "gsim_model_storage.h"
#include "branch_isa.h"
#include "branch_gold.h"
#include <memory>
#include <optional>
#include <set>
#include <chrono>
using matched::require;
struct Grant {uint64_t source;std::array<uint64_t,8> words{};std::optional<unsigned> sink;};
struct Native {unsigned owner;uint64_t due;};
class Run {
    matched::Image image;
    branch_isa::Oracle golden, reference;
    matched::Memory backing;
    std::unique_ptr<GsimModelStorage<SCommonA1BenchmarkGsim>> storage;
    SCommonA1BenchmarkGsim &dut;
    matched::ReadChannel iread,dread;
    matched::WriteChannel dwrite;
    std::set<unsigned> iowners,downers,sinks;
    std::map<unsigned,unsigned> isizes;
    std::map<unsigned,Grant> assembling;
    std::deque<Grant> grants;
    std::array<std::deque<Native>,2> native;
    std::array<std::set<unsigned>,2> nativeOwners;
    struct Release {uint64_t source,address;unsigned opcode,param,beat=0;};
    std::optional<Release> release;
    using Payload=std::array<uint64_t,8>;
    std::optional<Payload> heldI,heldA,heldC;
    static void heldCheck(std::optional<Payload>&held,bool valid,bool ready,const Payload&value,const char*name){if(held)require(valid&&*held==value,std::string(name)+" payload changed under backpressure");if(valid&&!ready)held=value;else held.reset();}
    uint64_t cycle=0,retired=0,beginCycle=0,endCycle=0,beginRetired=0,endRetired=0,trapCycle=0,storeCount=0;
    uint64_t grantsAccepted=0,acks=0,clearAccepted=0,clearReturned=0;
    bool terminal=false,mutate=false,mutated=false,trapMutation=false;
    std::set<std::pair<unsigned,uint64_t>> retiredTokens;
    std::chrono::steady_clock::time_point started=std::chrono::steady_clock::now();
    uint64_t maxCycles;
    void retirement(uint64_t pc,uint32_t inst,uint64_t data,uint64_t next,unsigned rd,bool writes,unsigned index,uint64_t tag) {
        require(!terminal,"retirement after terminal trap");
        const auto expected=golden.step();
        branch_gold::check_event(expected, retired);
        require(retiredTokens.emplace(index,tag).second,"duplicate retired full ROB token");
        if(mutate&&!mutated&&retired>=8&&writes){data^=1;mutated=true;std::cerr<<"BENCH_RETIRE_MUTANT_REACHED\n";}
        require(pc==expected.pc&&inst==expected.instruction&&next==expected.nextPc,"retirement PC/instruction/nextPC mismatch at "+std::to_string(retired));
        require(writes==expected.writes&&(!writes||(rd==expected.rd&&data==expected.data)),"retirement register mismatch at "+std::to_string(retired)+" pc="+std::to_string(pc));
        // Half-open marker window: count both cores from begin instruction to
        // before end instruction. Same-edge lane order remains architectural.
        if(pc==image.symbols.at("roi_begin")){require(!beginCycle,"duplicate ROI begin");beginCycle=cycle;beginRetired=retired;}
        if(pc==image.symbols.at("roi_end")){require(beginCycle&&!endCycle,"unmatched ROI end");endCycle=cycle;endRetired=retired;}
        ++retired;
    }
    bool tick(){
        // Internal 64-bit return assembly is part of the Valence interface;
        // no 512-bit grant may bypass the eight conceptual service beats.
        if(dread.valid(cycle)){
            auto beat=dread.offer(cycle);auto &g=assembling.at(unsigned(beat.tag));g.words.at(beat.index)=beat.data;
            if(beat.index+1==beat.count){grants.push_back(g);assembling.erase(unsigned(beat.tag));}
            dread.consume(cycle);
        }
        if(!grants.empty()&&!grants.front().sink&&sinks.size()<2){unsigned s=0;while(sinks.count(s))++s;sinks.insert(s);grants.front().sink=s;}
        const bool gv=!grants.empty()&&grants.front().sink.has_value();
        const bool iv=iread.valid(cycle),wv=dwrite.valid(cycle);
        const auto ib=iv?iread.offer(cycle):matched::ReadBeat{};
        const auto wa=wv?dwrite.offer(cycle):matched::WriteAck{};
        const bool ir=iread.ready()&&iowners.size()<16;
        // Addresses are combinational outputs of this same step; conflicts are
        // therefore checked at acceptance below. Read/write overlap is forbidden
        // by an older outstanding C burst; globally stall A until it completes.
        const bool ar=dread.ready()&&downers.size()<16&&!release;
        const bool cr=release.has_value()||dwrite.ready();
        const bool nr[2]={native[0].size()<16,native[1].size()<16};
        dut.set_io$$hold(terminal);dut.set_io$$inspectRegister(0);
        dut.set_io$$instructionA$$ready(ir);dut.set_io$$instructionD$$valid(iv);
        dut.set_io$$instructionD$$bits$$opcode(1);dut.set_io$$instructionD$$bits$$param(0);dut.set_io$$instructionD$$bits$$size(iv?isizes.at(unsigned(ib.tag)):0);
        dut.set_io$$instructionD$$bits$$source(iv?ib.tag:0);dut.set_io$$instructionD$$bits$$sink(0);
        dut.set_io$$instructionD$$bits$$data(iv?ib.data:0);dut.set_io$$instructionD$$bits$$denied(false);dut.set_io$$instructionD$$bits$$corrupt(false);
        dut.set_io$$dataA$$ready(ar);dut.set_io$$dataC$$ready(cr);dut.set_io$$dataE$$ready(true);
        dut.set_io$$dataGrant$$valid(gv);dut.set_io$$dataGrant$$bits$$source(gv?grants.front().source:0);dut.set_io$$dataGrant$$bits$$sink(gv?*grants.front().sink:0);
        dut.set_io$$dataGrant$$bits$$cap(0);dut.set_io$$dataGrant$$bits$$denied(false);dut.set_io$$dataGrant$$bits$$corrupt(false);
#define GW(N) dut.set_io$$dataGrant$$bits$$data##N(gv?grants.front().words[N]:0)
        GW(0);GW(1);GW(2);GW(3);GW(4);GW(5);GW(6);GW(7);
#undef GW
        dut.set_benchmark$$dataD$$valid(wv);dut.set_benchmark$$dataD$$bits$$opcode(6);dut.set_benchmark$$dataD$$bits$$param(0);
        dut.set_benchmark$$dataD$$bits$$size(6);dut.set_benchmark$$dataD$$bits$$source(wv?wa.tag:0);dut.set_benchmark$$dataD$$bits$$sink(0);
        dut.set_benchmark$$dataD$$bits$$data(0);dut.set_benchmark$$dataD$$bits$$denied(false);dut.set_benchmark$$dataD$$bits$$corrupt(false);
#define DRIVE_NATIVE(N) \
        dut.set_io$$scalar##N##$$request$$ready(nr[N]); \
        dut.set_io$$scalar##N##$$response$$valid(!native[N].empty()&&native[N].front().due<=cycle); \
        dut.set_io$$scalar##N##$$response$$bits$$owner(native[N].empty()?0:native[N].front().owner); \
        dut.set_io$$scalar##N##$$response$$bits$$clearReservation(true); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$data(0); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$error(false); \
        dut.set_io$$scalar##N##$$response$$bits$$memory$$pageFault(false)
        DRIVE_NATIVE(0);DRIVE_NATIVE(1);
#undef DRIVE_NATIVE
        dut.step();
#define A_PAYLOAD(N) Payload{dut.get_io$$##N##$$bits$$address(),dut.get_io$$##N##$$bits$$data(),dut.get_io$$##N##$$bits$$opcode(),dut.get_io$$##N##$$bits$$param(),dut.get_io$$##N##$$bits$$size(),dut.get_io$$##N##$$bits$$source(),dut.get_io$$##N##$$bits$$mask(),dut.get_io$$##N##$$bits$$corrupt()}
        heldCheck(heldI,dut.get_io$$instructionA$$valid(),ir,A_PAYLOAD(instructionA),"I A");
        heldCheck(heldA,dut.get_io$$dataA$$valid(),ar,A_PAYLOAD(dataA),"data A");
#undef A_PAYLOAD
        heldCheck(heldC,dut.get_io$$dataC$$valid(),cr,Payload{dut.get_io$$dataC$$bits$$address(),dut.get_io$$dataC$$bits$$data(),dut.get_io$$dataC$$bits$$opcode(),dut.get_io$$dataC$$bits$$param(),dut.get_io$$dataC$$bits$$size(),dut.get_io$$dataC$$bits$$source(),0,dut.get_io$$dataC$$bits$$corrupt()},"data C");
        require(!dut.get_io$$commit1$$valid()||dut.get_io$$commit0$$valid(),"nonprefix retirement");
#define RETIRE(N) if(dut.get_io$$commit##N##$$valid())retirement(dut.get_io$$commit##N##$$bits$$pc(),dut.get_io$$commit##N##$$bits$$instruction(),dut.get_io$$commit##N##$$bits$$data(),dut.get_io$$commit##N##$$bits$$nextPc(),dut.get_io$$commit##N##$$bits$$rd(),dut.get_io$$commit##N##$$bits$$writesRd(),dut.get_io$$commit##N##$$bits$$token$$index(),dut.get_io$$commit##N##$$bits$$token$$tag())
        RETIRE(0);RETIRE(1);
#undef RETIRE
        if(dut.get_io$$trap$$valid()){
            require(!terminal&&golden.pc==image.symbols.at("benchmark_terminal")&&retired==reference.retired,"early/repeated trap");
            uint64_t cause=dut.get_io$$trap$$bits$$cause();if(trapMutation){cause^=1;mutated=true;std::cerr<<"BENCH_TRAP_MUTANT_REACHED\n";}
            require(dut.get_io$$trap$$bits$$pc()==golden.pc&&cause==3&&dut.get_io$$trap$$bits$$tval()==golden.pc,"unexpected trap metadata");terminal=true;trapCycle=cycle;
        }
        // Responses retire before new requests. New reads precede new writes:
        // a simultaneous first write beat does not alter that read's snapshot.
        if(iv&&dut.get_io$$instructionD$$ready()){if(ib.index+1==ib.count){require(iowners.erase(unsigned(ib.tag))==1,"I response unowned");isizes.erase(unsigned(ib.tag));}iread.consume(cycle);}
        if(gv&&dut.get_io$$dataGrant$$ready()){require(downers.erase(grants.front().source)==1,"D grant unowned");grants.pop_front();++grantsAccepted;}
        if(wv&&dut.get_benchmark$$dataD$$ready()){dwrite.consume(cycle);++acks;}
        if(dut.get_io$$dataE$$valid())require(sinks.erase(dut.get_io$$dataE$$bits$$sink())==1,"E ack unowned");
        if(dut.get_io$$instructionA$$valid()&&ir){
            unsigned size=dut.get_io$$instructionA$$bits$$size(),source=dut.get_io$$instructionA$$bits$$source();uint64_t address=dut.get_io$$instructionA$$bits$$address();
            require(dut.get_io$$instructionA$$bits$$opcode()==4&&!dut.get_io$$instructionA$$bits$$param()&&!dut.get_io$$instructionA$$bits$$corrupt()&&(size==2||size==3||size==6)&&!(address&((1ULL<<size)-1))&&dut.get_io$$instructionA$$bits$$mask()==(size==2?(15u<<(address&7)):255u),"unsupported I Get");
            require(iowners.insert(source).second,"duplicate I source");isizes[source]=size;iread.enqueue(backing,source,address&~7ULL,size<=3?1:1u<<(size-3),cycle);
        }
        if(dut.get_io$$dataA$$valid()&&ar){
            unsigned source=dut.get_io$$dataA$$bits$$source();uint64_t address=dut.get_io$$dataA$$bits$$address();
            require(dut.get_io$$dataA$$bits$$opcode()==6&&dut.get_io$$dataA$$bits$$param()==1&&dut.get_io$$dataA$$bits$$size()==6&&!dut.get_io$$dataA$$bits$$corrupt()&&!(address&63)&&dut.get_io$$dataA$$bits$$mask()==255,"unsupported data Acquire");
            require(!dwrite.conflicts(address,64),"read accepted over incomplete older write");require(downers.insert(source).second,"duplicate data source");
            assembling.emplace(source,Grant{source,{},{}});dread.enqueue(backing,source,address,8,cycle);
        }
        if(dut.get_io$$dataC$$valid()&&cr){
            unsigned source=dut.get_io$$dataC$$bits$$source(),op=dut.get_io$$dataC$$bits$$opcode(),param=dut.get_io$$dataC$$bits$$param();uint64_t address=dut.get_io$$dataC$$bits$$address();
            require((op==6||op==7)&&param==1&&dut.get_io$$dataC$$bits$$size()==6&&!dut.get_io$$dataC$$bits$$corrupt()&&!(address&63),"unsupported C release/probe");
            if(!release)release=Release{source,address,op,param,0};auto&r=*release;
            require(r.source==source&&r.address==address&&r.opcode==op&&r.param==param,"C burst changed metadata");
            if(op==6){require(!r.beat,"clean release multibeat");dwrite.cleanRelease(source,cycle);release.reset();}
            else{dwrite.beat(backing,source,address,8,r.beat,dut.get_io$$dataC$$bits$$data(),255,cycle);if(++r.beat==8)release.reset();}
        }
#define NATIVE(N) \
        if(!native[N].empty()&&native[N].front().due<=cycle&&dut.get_io$$scalar##N##$$response$$ready()){require(nativeOwners[N].erase(native[N].front().owner)==1,"native response unowned");native[N].pop_front();++clearReturned;} \
        if(dut.get_io$$scalar##N##$$request$$valid()&&nr[N]){require(terminal&&dut.get_io$$scalar##N##$$request$$bits$$clearReservation(),"unexpected native data/MMIO/atomic request");unsigned owner=dut.get_io$$scalar##N##$$request$$bits$$owner();require(nativeOwners[N].insert(owner).second,"duplicate native owner");native[N].push_back({owner,cycle+3});++clearAccepted;}
        NATIVE(0);NATIVE(1);
#undef NATIVE
        if(dut.get_io$$physical$$valid()&&dut.get_io$$physical$$bits$$write()){
            require(storeCount<reference.stores.size(),"extra physical store");const auto&s=reference.stores.at(storeCount++);
            const unsigned mask=((1u<<s.size)-1)<<(s.address&7);uint64_t byteMask=0;for(unsigned i=0;i<8;++i)if(mask&(1u<<i))byteMask|=255ULL<<(8*i);
            require(dut.get_io$$physical$$bits$$address()==s.address&&dut.get_io$$physical$$bits$$mask()==mask&&((dut.get_io$$physical$$bits$$data()^(s.data<<(8*(s.address&7))))&byteMask)==0,"physical store diverged from independent guest sequence");
        }
        ++cycle;
        return terminal&&iread.idle()&&dread.idle()&&dwrite.idle()&&iowners.empty()&&downers.empty()&&sinks.empty()&&grants.empty()&&assembling.empty()&&!release&&!heldI&&!heldA&&!heldC&&native[0].empty()&&native[1].empty()&&dut.get_io$$fetchIdle()&&dut.get_io$$privateIdle()&&dut.get_io$$ownersIdle()&&!dut.get_io$$memoryBusy()&&dut.get_io$$robOccupancy()==0;
    }
public:
    Run(const std::string&e,const std::string&s,const std::string&test,uint64_t bound,const std::string&mode):image(e,s),golden(image),reference(image),backing(image.memory),storage(std::make_unique<GsimModelStorage<SCommonA1BenchmarkGsim>>()),dut(storage->get()),maxCycles(bound){
        mutate=mode=="mutate";trapMutation=mode=="trapmutate";require(mode.empty()||mutate||trapMutation,"unknown negative mode");reference.run(image);
        require(test=="branch-control-v1","unknown manifest workload");
        branch_gold::check_reference(reference);
        dut.set_io$$hold(true);dut.set_reset(true);dut.step();dut.step();dut.set_reset(false);
    }
    void run(){unsigned quiet=0;while(cycle<maxCycles&&quiet<4){if(tick())++quiet;else quiet=0;if(!(cycle%4096))require(std::chrono::steady_clock::now()-started<std::chrono::minutes(20),"20 minute host runtime bound");}
        require(quiet==4,"cycle bound before full owner drain");require(!mutate&&!trapMutation,"requested negative not rejected");
        require(golden.regs==reference.regs&&golden.hash==reference.hash&&retired==reference.retired,"final independent architectural state mismatch");
        require(beginCycle&&endCycle>beginCycle&&endRetired-beginRetired==reference.endCount-reference.beginCount,"ROI mismatch");
        require(storeCount==reference.stores.size()&&clearAccepted==clearReturned,"physical/native conservation");
        std::cout<<"VALENCE_BRANCH_MATCHED_PASS cycles="<<cycle<<" work="<<trapCycle+1<<" drain="<<cycle-trapCycle-1<<" roi_cycles="<<endCycle-beginCycle<<" retired="<<retired<<" roi_retired="<<endRetired-beginRetired<<" I_requests="<<iread.requests<<" I_bytes="<<iread.bytes<<" D_reads="<<dread.requests<<" D_read_bytes="<<dread.bytes<<" D_writes="<<dwrite.requests<<" D_write_bytes="<<dwrite.bytes<<" grants="<<grantsAccepted<<" release_acks="<<acks<<" hash="<<std::hex<<golden.hash<<" branch_x10="<<golden.regs[10]<<" dirty_resident_flush=not_requested\n";
    }
};
int main(int argc,char**argv){try{require(argc>=4,"ELF symbols workload [maxcycles] [mutate|trapmutate]");Run run(argv[1],argv[2],argv[3],argc>4?std::stoull(argv[4]):100000,argc>5?std::string(argv[5]):std::string());run.run();}catch(const std::exception&e){std::cerr<<"VALENCE_BRANCH_MATCHED_FAIL "<<e.what()<<"\n";return 1;}}
