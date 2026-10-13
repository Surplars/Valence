#include "RetirementSlotPairGsim.h"
#include "retirement_slot_rob_oracle.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <new>
#include <stdexcept>
#include <string>
#include <vector>

static void check(bool ok, const char* why) { if (!ok) throw std::runtime_error(why); }
struct Offer { bool valid=false; unsigned kind=0; uint64_t value=0; uint32_t instruction=0x13; unsigned rd=0; };
static Offer alu(uint64_t value=0, unsigned rd=0) { return {true,0,value,0x13,rd}; }
static Offer special(unsigned kind, uint64_t value=0) {
    return {true,kind,value,kind==3?0x63u:kind==4?0x100fu:kind==5?0x3003u:0x13u,0};
}
struct Result { bool valid=false; unsigned index=0; uint64_t tag=0,data=0,next=0; bool fault=false; };
struct Row { unsigned index; uint64_t tag,pc,data,next; unsigned kind; bool done=false,fault=false; };
class BackendTest {
public:
    SRetirementSlotPairGsim& d;
    std::deque<Row> rows;
    unsigned tail=0,head=0; uint64_t nextTag=0;
    unsigned cycles=0,renames=0,commits=0,dual=0,held=0,cancelled=0,recovery=0,rawDifference=0;
    unsigned seenProducers=0,overlapProducers=0,bothExec=0,branchWithAlu=0,wrap=0,traps=0,prfWrites=0;
    unsigned keep=0; bool recovering=false,enable=true;
    std::deque<uint64_t> responses;
    explicit BackendTest(SRetirementSlotPairGsim& model):d(model) {}
    void drive(unsigned lane,const Offer& o) {
#define L(n) case n: d.set_io$$offer##n##$$valid(o.valid); d.set_io$$offer##n##$$kind(o.kind); d.set_io$$offer##n##$$value(o.value); d.set_io$$offer##n##$$instruction(o.instruction); d.set_io$$offer##n##$$rd(o.rd); break
        switch(lane){L(0);L(1);}
#undef L
    }
    Result issue(unsigned lane) {
#define L(n) case n:return {bool(d.get_io$$reference$$issued##n##$$valid()),unsigned(d.get_io$$reference$$issued##n##$$bits$$token$$index()),d.get_io$$reference$$issued##n##$$bits$$token$$tag(),d.get_io$$reference$$issued##n##$$bits$$data(),d.get_io$$reference$$issued##n##$$bits$$nextPc(),bool(d.get_io$$reference$$issued##n##$$bits$$exception())}
        switch(lane){L(0);L(1);}return {};
#undef L
    }
    Result commit(unsigned lane) {
#define L(n) case n:return {bool(d.get_io$$reference$$commit##n##$$valid()),unsigned(d.get_io$$reference$$commit##n##$$bits$$token$$index()),d.get_io$$reference$$commit##n##$$bits$$token$$tag(),d.get_io$$reference$$commit##n##$$bits$$data(),d.get_io$$reference$$commit##n##$$bits$$nextPc(),false}
        switch(lane){L(0);L(1);}return {};
#undef L
    }
    Result renamed(unsigned lane) {
#define L(n) case n:return {bool(d.get_io$$reference$$renamed##n##$$valid()),unsigned(d.get_io$$reference$$renamed##n##$$bits$$index()),d.get_io$$reference$$renamed##n##$$bits$$tag(),0,0,false}
        switch(lane){L(0);L(1);}return {};
#undef L
    }
    void neutral() {
        drive(0,{});drive(1,{});d.set_io$$pc(0x80000000);d.set_io$$commitEnable(false);
        d.set_io$$memoryReady(true);d.set_io$$memoryResponse$$valid(false);
        d.set_io$$memoryResponse$$bits$$returnHandle(0);d.set_io$$memoryResponse$$bits$$data(0x1122334455667788ULL);
        d.set_io$$memoryResponse$$bits$$error(false);d.set_io$$memoryResponse$$bits$$pageFault(false);
    }
    void reset() {
        neutral();idle_retirement_rob(d);d.set_reset(1);d.step();d.step();d.set_reset(0);
        rows.clear();tail=head=0;nextTag=0;keep=0;recovering=false;responses.clear();enable=true;
        tick();
    }
    void tick(Offer a={},Offer b={}) {
        const uint64_t pc=0x80000000ULL+8ULL*cycles;
        drive(0,a);drive(1,b);d.set_io$$pc(pc);d.set_io$$commitEnable(enable);
        d.set_io$$memoryResponse$$valid(!responses.empty());
        d.set_io$$memoryResponse$$bits$$returnHandle(responses.empty()?0:responses.front());
        d.step();++cycles;
        check(unsigned(d.get_io$$reference$$occupancy())==rows.size(),"BACKEND_OWNER_COUNT");
        check(unsigned(d.get_io$$reference$$head())==head,"BACKEND_OWNER_HEAD");
        const bool rc=d.get_io$$reference$$recoveryCycle();
        const unsigned occupied=d.get_io$$candidate$$execOccupied(),ready=d.get_io$$candidate$$execReady();
        const unsigned producers=d.get_io$$candidate$$producers(),raw=d.get_io$$candidate$$intent();
        const unsigned actual=d.get_io$$candidate$$actual(),classes=d.get_io$$candidate$$retireClass();
        seenProducers|=producers; if(occupied&1)overlapProducers|=producers;
        const unsigned writes=d.get_io$$candidate$$physicalWriteMask();
        prfWrites+=(writes&1)+((writes>>1)&1);
        if(occupied==3)++bothExec;
        if(occupied==3 && d.get_io$$candidate$$execBranch()!=0 && d.get_io$$candidate$$execBranch()!=3)++branchWithAlu;
        held+=bool(occupied&~ready);cancelled+=bool(d.get_io$$candidate$$execCancel());
        rawDifference+=bool(raw!=actual);traps+=bool(d.get_io$$candidate$$trap());
        if(!producers) check(raw==(occupied&ready),"BACKEND_RAW_EXEC_OFFER");
        else if(producers&7) check(raw&1,"BACKEND_PRIORITY_OFFER");
        if(producers&15) check(classes&1,"BACKEND_PRIORITY_CLASS");
        if(!rc) check(raw==actual,"BACKEND_NO_RECOVERY_VALID_EQUALITY");
        const auto issued=std::array<Result,2>{issue(0),issue(1)};
        for(const auto& r:issued) if(r.valid) {
            auto it=std::find_if(rows.begin(),rows.end(),[&](const Row& x){return x.index==r.index&&x.tag==r.tag;});
            check(it!=rows.end(),"BACKEND_COMPLETION_OWNER");check(!it->done,"BACKEND_DUPLICATE_COMPLETION");
            check(r.fault==(it->kind==6),"BACKEND_COMPLETION_FAULT");
            if(!r.fault)check(r.data==it->data&&r.next==it->next,"BACKEND_COMPLETION_DATA");
        }
        unsigned want=0;
        if(!rc && d.get_io$$reference$$commitEnable()) {
            for(unsigned lane=0;lane<2&&lane<rows.size();++lane) {
                const auto& row=rows[lane];bool done=row.done,fault=row.fault;
                for(const auto& r:issued)if(r.valid&&r.index==row.index&&r.tag==row.tag&&row.kind!=3){done=true;fault=r.fault;}
                if(!done||fault)break;
                ++want;if(row.kind==4)break;
            }
        }
        for(unsigned lane=0;lane<2;++lane) {
            const auto c=commit(lane);check(c.valid==(lane<want),"BACKEND_COMMIT_PREFIX");
            if(c.valid){const auto& row=rows[lane];check(c.index==row.index&&c.tag==row.tag,"BACKEND_COMMIT_OWNER");
                check(c.data==row.data&&c.next==row.next,"BACKEND_COMMIT_DATA");}
        }
        for(const auto& r:issued)if(r.valid)for(auto& row:rows)if(row.index==r.index&&row.tag==r.tag){row.done=true;row.fault=r.fault;}
        if(rc) {
            ++recovery;check(!want,"BACKEND_RECOVERY_COMMIT");
            if(d.get_io$$reference$$recovery$$valid()) {
                const auto idx=unsigned(d.get_io$$reference$$recovery$$bits$$token$$index());
                const auto tag=d.get_io$$reference$$recovery$$bits$$token$$tag();
                auto it=std::find_if(rows.begin(),rows.end(),[&](const Row& x){return x.index==idx&&x.tag==tag;});
                check(it!=rows.end(),"BACKEND_RECOVERY_OWNER");
                keep=unsigned(it-rows.begin())+!d.get_io$$reference$$recovery$$bits$$inclusive();
            }
            check(rows.size()>=keep,"BACKEND_RECOVERY_BOUNDARY");
            const unsigned remove=std::min<unsigned>(4,rows.size()-keep);
            for(unsigned i=0;i<remove;++i)rows.pop_back();tail=(tail+16-remove)%16;recovering=rows.size()>keep;
        } else {
            for(unsigned i=0;i<want;++i)rows.pop_front();commits+=want;if(want==2)++dual;
            const auto prev=head;head=(head+want)%16;if(head<prev)++wrap;
        }
        const std::array<Offer,2> offers{a,b};
        for(unsigned lane=0;lane<2;++lane){const auto r=renamed(lane);if(!r.valid)continue;
            check(!rc&&offers[lane].valid,"BACKEND_RENAME_AUTHORITY");
            check(r.index==tail&&r.tag==nextTag,"BACKEND_RENAME_INDEPENDENT_TOKEN");
            const auto& o=offers[lane];const uint64_t ownerPc=pc+4*lane;
            uint64_t data=o.value,next=ownerPc+4;
            if(o.kind==1||o.kind==3||o.kind==4)data=0;
            if(o.kind==2)data=~uint64_t(0);
            if(o.kind==3)next=ownerPc+o.value;
            if(o.kind==5)data=0x1122334455667788ULL;
            rows.push_back({tail,nextTag,ownerPc,data,next,o.kind});tail=(tail+1)%16;++nextTag;++renames;
        }
        if(!responses.empty()&&d.get_io$$memoryResponseReady())responses.pop_front();
        if(d.get_io$$memoryRequest$$valid())responses.push_back(d.get_io$$memoryRequest$$bits$$returnHandle());
    }
    void drain(){for(unsigned i=0;i<200;++i){tick();if(rows.empty()&&responses.empty())return;}throw std::runtime_error("BACKEND_DRAIN_TIMEOUT");}
    void run(){
        reset();for(unsigned i=0;i<64;++i)tick(alu(i+1),alu(i+100));drain();
        // Nonzero destinations make paired PRF-write authority an exercised property.
        reset();for(unsigned i=0;i<48;++i)tick(alu(i+901,1+i%31),alu(i+1901,1+(i+17)%31));drain();
        // A ready execution slot is held whenever an older result wins lane 0.
        for(unsigned kind:{1u,2u,4u,5u}){
            reset();tick(special(kind,kind==5?0x80200000:0),alu(7));
            for(unsigned i=0;i<88;++i)tick(alu(i+10),alu(i+300));drain();
        }
        // Keep room for a fixed burst near the long divider's completion.
        // A continuously full ROB otherwise lets every younger ALU finish early.
        reset();tick(special(2));for(unsigned i=0;i<60;++i)tick();
        for(unsigned i=0;i<16;++i)tick(alu(1000+i),alu(2000+i));drain();
        // Mispredicted branch uses the supported local recovery, with both
        // execution slots occupied and a younger add available for cancellation.
        for(unsigned shift=0;shift<5;++shift){
            reset();for(unsigned i=0;i<shift;++i)tick(alu(i+1),alu(i+2));
            tick(special(3,16),alu(777));for(unsigned i=0;i<12;++i)tick(alu(20+i),alu(90+i));drain();
        }
        reset();tick(special(6),alu(33));for(unsigned i=0;i<20;++i)tick();drain();
        // Recovery removed owners; allocation can legally reuse their indices
        // on subsequent edges with new complete tags.
        for(unsigned i=0;i<20;++i)tick(alu(i),alu(i+100));drain();
        std::cerr<<"BACKEND_COVERAGE_OBSERVED held="<<held<<" cancelled="<<cancelled<<" recovery="<<recovery<<" rawDifference="<<rawDifference<<" producers="<<seenProducers<<" priorityOverlap="<<overlapProducers<<" branchWithAlu="<<branchWithAlu<<" traps="<<traps<<"\n";
        check(dual&&wrap&&bothExec&&held&&cancelled&&recovery&&rawDifference&&branchWithAlu&&traps,"BACKEND_COVERAGE_EXEC_RECOVERY");
        check((seenProducers&15)==15,"BACKEND_COVERAGE_PRODUCERS");
        check(prfWrites>0,"BACKEND_COVERAGE_PRF_WRITES");
        check((overlapProducers&7)==7,"BACKEND_COVERAGE_PRIORITY_OVERLAP");
        std::cout<<"RETIREMENT_BACKEND_ORACLE_PASS cycles="<<cycles<<" renamed="<<renames<<" commits="<<commits<<" dual="<<dual<<" held="<<held<<" cancelled="<<cancelled<<" recovery="<<recovery<<" rawDifference="<<rawDifference<<" producers="<<seenProducers<<" priorityOverlap="<<overlapProducers<<" branchWithAlu="<<branchWithAlu<<" prfWrites="<<prfWrites<<'\n';
    }
};
int main(int argc,char**argv){try{
    // Initialize object storage before constructor/reset; never change legal
    // DUT state through generated hierarchy fields after construction.
    void* storage=std::calloc(1,sizeof(SRetirementSlotPairGsim));check(storage,"allocation failed");
    auto* model=new(storage)SRetirementSlotPairGsim;
    BackendTest t(*model);t.run();t.neutral();
    std::string mutation=argc>1?argv[1]:"";
    if(mutation.starts_with("--mutate-"))mutation=mutation.substr(9);
    run_retirement_rob(*model,mutation);
    model->~SRetirementSlotPairGsim();std::free(storage);
    std::cout<<"RETIREMENT_SLOT_PAIR_PASS\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
