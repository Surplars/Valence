// Independent registered-owner mailbox oracle. Scheduling is a procedural walk
// around the ROB, not the DUT's pairwise age comparator. Source resolved-once
// state below changes only on expected capture, new owner, or cancellation.
#include "BranchResolutionMailboxGsim.h"
#include <array>
#include <cstdint>
#include <iostream>
#include <optional>
#include <random>
#include <set>
#include <stdexcept>
#include <string>
#include <utility>

namespace {
struct Owner {
    unsigned index;
    uint64_t tag, pc, target;
    bool sameToken(const Owner &other) const { return index == other.index && tag == other.tag; }
    bool operator==(const Owner &) const = default;
};
struct Source { std::optional<Owner> owner; bool resolved = false; };
struct Control { unsigned head = 0, killed = 0; bool ready = true, flush = false, cancel = false; };
struct Coverage {
    uint64_t cycles=0, captures=0, outputs=0, turns=0, stalls=0, killedWinners=0;
    uint64_t duplicates=0, resolvedOffers=0, cancelledNoCredit=0, flushes=0, reusedIndex=0;
};
class Oracle {
    SBranchResolutionMailboxGsim dut;
    std::array<Source,2> sources;
    std::optional<Owner> held;
    std::set<std::pair<unsigned,uint64_t>> acceptedOwners;
    std::array<std::optional<uint64_t>,16> priorGeneration;
    uint64_t nextTag=UINT64_C(0x1234000000000001);
    bool negative, injected=false;
    Coverage coverage;
    void require(bool ok,const std::string &message) const {
        if(!ok)throw std::runtime_error("branch resolution oracle cycle="+
            std::to_string(coverage.cycles)+" "+message);
    }
    void drive(const Control &c) {
        unsigned present=0,resolved=0;
        for(unsigned i=0;i<2;++i){present|=unsigned(sources[i].owner.has_value())<<i;resolved|=unsigned(sources[i].resolved)<<i;}
        dut.set_io$$head(c.head);dut.set_io$$present(present);dut.set_io$$resolved(resolved);
        dut.set_io$$killed(c.killed);dut.set_io$$outputReady(c.ready);dut.set_io$$flush(c.flush);dut.set_io$$cancelHeld(c.cancel);
        const Owner a=sources[0].owner.value_or(Owner{}),b=sources[1].owner.value_or(Owner{});
        dut.set_io$$index0(a.index);dut.set_io$$tag0(a.tag);dut.set_io$$pc0(a.pc);dut.set_io$$target0(a.target);
        dut.set_io$$index1(b.index);dut.set_io$$tag1(b.tag);dut.set_io$$pc1(b.pc);dut.set_io$$target1(b.target);
    }
public:
    explicit Oracle(bool inject):negative(inject){
        dut.LOG_START=1;dut.activateAll();drive({});dut.set_reset(true);dut.step();dut.step();dut.set_reset(false);
    }
    Owner make(unsigned index){
        const uint64_t tag=nextTag++;
        return {index,tag,UINT64_C(0x80200000)+(tag&0xffff)*4,
            UINT64_C(0x80400000)+((tag*37)&0xffff)*2};
    }
    void install(unsigned lane,Owner owner){
        require(!sources[lane].owner || sources[lane].resolved,"test attempted to overwrite an unresolved physical holder");
        sources[lane]={owner,false}; // Accepted NEW physical owner; not branch.valid.
    }
    void cancelSource(unsigned lane){sources[lane]={};}
    bool available(unsigned lane)const{return !sources[lane].owner||sources[lane].resolved;}
    std::optional<Owner> owner(unsigned lane)const{return sources[lane].owner;}
    unsigned tick(Control c={}){
        unsigned duplicate=0;
        for(unsigned lane=0;lane<2;++lane)if(sources[lane].owner){
            bool match=held&&held->sameToken(*sources[lane].owner);
            for(unsigned prior=0;prior<lane;++prior)match|=sources[prior].owner&&
                sources[prior].owner->sameToken(*sources[lane].owner);
            if(match)duplicate|=1u<<lane;
        }
        // Age order is independently expressed as a circular queue traversal.
        int chosen=-1;
        for(unsigned offset=0;offset<16&&chosen<0;++offset){
            const unsigned slot=(c.head+offset)%16;
            for(unsigned lane=0;lane<2;++lane)if(sources[lane].owner&&!sources[lane].resolved&&
                !(duplicate&(1u<<lane))&&sources[lane].owner->index==slot){chosen=int(lane);break;}
        }
        const bool credit=!held||c.ready;
        const bool output=held&&!c.flush&&!c.cancel;
        const unsigned winner=chosen<0?0u:1u<<chosen;
        const unsigned capture=credit&&!c.flush&&chosen>=0&&!(c.killed&winner)?winner:0u;
        drive(c);dut.step();
        require(bool(dut.get_io$$occupied())==bool(held),"registered occupancy");
        require(bool(dut.get_io$$canCapture())==credit,"early capacity depends on late cancellation");
        require(bool(dut.get_io$$outputValid())==output,"output validity/cancellation");
        if(output){
            const Owner observed{unsigned(dut.get_io$$outputIndex()),dut.get_io$$outputTag(),
                dut.get_io$$outputPc(),dut.get_io$$outputTarget()};
            require(observed==*held,"held full-token/payload changed or bypassed the register");
        }
        require(dut.get_io$$winner()==winner,"independent ROB-order winner mismatch");
        require(dut.get_io$$duplicate()==duplicate,"full-token duplicate mismatch");
        unsigned observed=dut.get_io$$capture();
        if(negative&&!injected&&coverage.cycles>=17){
            std::cerr<<"BRANCH_RESOLUTION_NEGATIVE_REACHED cycle="<<coverage.cycles<<" mutation=sampled_capture\n";
            observed^=1;injected=true;
        }
        require(observed==capture,"independent capture oracle mismatch");
        require((capture&(capture-1))==0,"more than one capture");
        coverage.stalls+=output&&!c.ready;
        coverage.turns+=output&&c.ready&&capture;
        coverage.outputs+=output&&c.ready;
        coverage.killedWinners+=winner&&(c.killed&winner);
        coverage.duplicates+=bool(duplicate);
        coverage.resolvedOffers+=bool((sources[0].owner&&sources[0].resolved)||(sources[1].owner&&sources[1].resolved));
        coverage.cancelledNoCredit+=held&&!c.ready&&c.cancel;
        coverage.flushes+=c.flush;
        if(c.flush||c.cancel||(output&&c.ready))held.reset();
        if(capture){
            const unsigned lane=capture==1?0:1;
            const Owner value=*sources[lane].owner;
            require(acceptedOwners.insert({value.index,value.tag}).second,"same source lifetime captured twice");
            if(priorGeneration[value.index]){
                require(*priorGeneration[value.index]!=value.tag,"ROB index reuse retained stale generation");
                ++coverage.reusedIndex;
            }
            priorGeneration[value.index]=value.tag;
            held=value;
            // This is the only successful-resolution update of source state.
            sources[lane].resolved=true;
            ++coverage.captures;
        }
        for(unsigned lane=0;lane<2;++lane)if(c.flush||(c.killed&(1u<<lane)))sources[lane]={};
        ++coverage.cycles;
        return capture;
    }
    void clean(){tick({.flush=true});}
    void directed(){
        // Wrapped age, then sustained turnover. Earlier killed winner cannot
        // fall back to a younger branch even though the mailbox is empty.
        install(0,make(1));install(1,make(15));require(tick({.head=14,.killed=2})==0,"killed oldest fallback");
        require(tick({.head=14})==1,"remaining live branch");
        for(unsigned i=0;i<4;++i)tick({.ready=false});
        for(unsigned i=0;i<4;++i)tick(); // Resolved source remains present after drain.
        install(1,make(2));require(tick()==2,"new source capture");
        install(0,make(3));require(tick()==1,"same-cycle registered turnover");
        clean();
        // One physical source keeps offering its captured owner while held,
        // on drain, and after consumption. Only capture set its resolved bit.
        const Owner shared=make(7);install(0,shared);
        require(tick()==1,"single source capture");
        tick({.ready=false});tick({.ready=false});
        require(tick()==0,"same-edge drain duplicate recapture");
        require(tick()==0,"consumed source lifetime captured twice");
        clean();
        // A killed stalled old owner cannot donate credit. Its ROB slot can
        // immediately name a NEW generation on the following cycle.
        const Owner old=make(9),fresh=make(9);install(0,old);require(tick()==1,"old generation capture");
        install(1,fresh);require(tick({.ready=false,.cancel=true})==0,"kill borrowed same-cycle credit");
        require(tick({.ready=false})==2,"fresh full generation blocked by old index");
        tick({.ready=false});tick({.ready=true});
        install(0,make(10));require(tick({.flush=true})==0,"flush accepted new resolution");
        tick();
        // A fresh physical owner every edge: exact capacity-one pipeline II=1,
        // one fill cycle, then old output and new capture overlap continuously.
        for(unsigned i=0;i<32;++i){install(0,make(i%16));require(tick()==1,"continuous-supply II=1 lost capture");}
        tick();clean();
    }
    void random(){
        std::mt19937_64 rng(0x2b4a8c1664ULL);
        for(unsigned cycle=0;cycle<6000;++cycle){
            for(unsigned lane=0;lane<2;++lane){
                if(available(lane)&&rng()%3==0)install(lane,make(rng()%16));
                else if(available(lane)&&rng()%13==0)cancelSource(lane);
            }
            Control c{unsigned(rng()%16),unsigned(rng()%4==0?rng()%4:0),bool(rng()%4),
                rng()%79==0,rng()%19==0};
            tick(c);
        }
        clean();
    }
    void illegalDuplicate(){
        const Owner shared=make(7);install(0,shared);install(1,shared);
        std::cerr<<"BRANCH_RESOLUTION_DUPLICATE_REACHED illegal=two_physical_sources_same_full_token\n";
        tick();
        throw std::runtime_error("illegal duplicate source was not rejected by the ownership assertion");
    }
    void finish(){
        require(!negative,"negative control failed to reject");
        require(coverage.captures>100&&coverage.turns>10&&coverage.stalls>10&&coverage.killedWinners>0&&
            coverage.duplicates>0&&coverage.resolvedOffers>10&&coverage.cancelledNoCredit>0&&coverage.reusedIndex>20,
            "bounded coverage obligations missing");
        std::cout<<"BRANCH_RESOLUTION_MAILBOX_PASS cycles="<<coverage.cycles<<" captures="<<coverage.captures
            <<" outputs="<<coverage.outputs<<" turnover="<<coverage.turns<<" held_stalls="<<coverage.stalls
            <<" killed_winner="<<coverage.killedWinners<<" duplicate_cycles="<<coverage.duplicates
            <<" resolved_source_cycles="<<coverage.resolvedOffers<<" cancel_without_credit="<<coverage.cancelledNoCredit
            <<" flushes="<<coverage.flushes<<" index_new_generation="<<coverage.reusedIndex
            <<" independent_rob_walk=1 executable_source_lifecycle=1 continuous_captures=32 backend_connected=0\n";
    }
};
}
int main(int argc,char**argv){
    try{
        const bool negative=argc==2&&std::string(argv[1])=="--inject-mismatch";
        const bool duplicate=argc==2&&std::string(argv[1])=="--duplicate-source";
        if(argc!=1&&!negative&&!duplicate)throw std::runtime_error("usage: mailbox [--inject-mismatch|--duplicate-source]");
        Oracle oracle(negative);
        if(duplicate)oracle.illegalDuplicate();
        oracle.directed();oracle.random();oracle.finish();return 0;
    }catch(const std::exception&error){std::cerr<<"BRANCH_RESOLUTION_MAILBOX_FAIL "<<error.what()<<'\n';return 1;}
}
