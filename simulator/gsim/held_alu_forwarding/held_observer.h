#pragma once
#include "architecture_oracle.h"
#include "events.h"
#include "scenario.h"
#include <algorithm>
#include <iostream>
#include <limits>
#include <optional>
#include <set>
#include <sstream>
namespace b1 {
constexpr uint64_t never=std::numeric_limits<uint64_t>::max();
inline std::string token_text(Token t){return std::to_string(t.index)+":"+std::to_string(t.tag);}
inline bool ordinary(ArchKind k){return k==ArchKind::Addi||k==ArchKind::Slli||k==ArchKind::Auipc||k==ArchKind::Add||k==ArchKind::Branch||k==ArchKind::Jal||k==ArchKind::Jalr;}
inline bool control(ArchKind k){return k==ArchKind::Branch||k==ArchKind::Jal||k==ArchKind::Jalr;}
inline bool system_kind(ArchKind k){return !ordinary(k)&&k!=ArchKind::Load&&k!=ArchKind::Store&&k!=ArchKind::Mul&&k!=ArchKind::Divu;}
struct History {
    Token token{};ArchInstruction instruction{};unsigned destination=0,source1=0,source2=0;
    std::optional<Token> leftWriter,rightWriter,heldProducer;
    uint64_t observedData=0;
    uint64_t allocation=0,capture=never,completed=never,started=never,prepared=never,retired=never,killed=never;
    unsigned captureLane=2;bool evaluationReady=false,declaredIllegal=false;ArchEvaluation evaluation{};
};
class HeldObserver {
public:
    Scenario scenario;Architecture architecture{UINT64_C(0x80000000)};
    bool enabled=false,terminalSeen=false;uint64_t cycle=0,terminalCycle=never,faults=0,retired=0;
    std::map<std::string,uint64_t> counters;
    std::map<Token,History> history;std::vector<Token> live;
    std::map<uint64_t,std::pair<unsigned,uint64_t>> terminalStores;
    std::map<unsigned,Token> requests;
    std::string mutation;bool applied=false;
private:
    std::array<std::optional<Token>,32> committedWriter{};
    Snapshot previous{};bool havePrevious=false;
    std::set<Token> exactPrfReuse,exactRobReuse;
    uint64_t architecturalHash=UINT64_C(1469598103934665603);
public:
    HeldObserver(Scenario s,bool on,std::string mutate={}) : scenario(std::move(s)),enabled(on),mutation(std::move(mutate)) {
        for(auto [a,v]:scenario.seed)architecture.seed_qword(a,v);
        for(uint64_t p=0x80000008;p<0x80000040;p+=8)architecture.seed_qword(p,0);
        if(scenario.family.rfind("D3",0)==0)architecture.inject_load_fault(scenario.faultPc,scenario.faultCause,scenario.faultTval);
    }
    void seed_image(const std::vector<uint8_t>& bytes){auto padded=bytes;padded.resize((bytes.size()+63)&~size_t(63),0);architecture.seed_bytes(Architecture::entry_pc,padded);}
    void check(bool ok,const std::string& why)const{
        if(!ok)throw std::runtime_error("B1_ORACLE case="+scenario.name+" cycle="+std::to_string(cycle)+" "+why);
    }
    History& owner(Token t){auto i=history.find(t);check(i!=history.end(),"UNKNOWN_FULL_TOKEN "+token_text(t));return i->second;}
    const History& owner(Token t)const{auto i=history.find(t);check(i!=history.end(),"UNKNOWN_FULL_TOKEN "+token_text(t));return i->second;}
    bool is_live(Token t)const{return std::find(live.begin(),live.end(),t)!=live.end();}
    bool old_ready(std::optional<Token> t,uint64_t edge)const{return !t || (owner(*t).completed<edge&&!owner(*t).evaluation.trap&&owner(*t).killed>edge);}
    uint64_t source(std::optional<Token> writer){return writer?evaluate(*writer).result:0;}
    ArchEvaluation& evaluate(Token token){
        auto& e=owner(token);if(e.evaluationReady)return e.evaluation;
        if(e.declaredIllegal){e.evaluation.instruction=e.instruction;e.evaluation.nextpc=e.instruction.pc+2;e.evaluation.trap=ArchFault{2,e.instruction.word};e.evaluationReady=true;return e.evaluation;}
        if(!ordinary(e.instruction.kind))check(e.started!=never,"NON_ALU_EVALUATION_WITHOUT_REAL_START");
        auto left=source(e.leftWriter),right=source(e.rightWriter);
        if(e.instruction.kind==ArchKind::Load){
            // This fixed guest never relies on a load forwarding from an older
            // unretired same-address store. Reject an unsupported extension.
            const uint64_t va=left+e.instruction.immediate;
            for(Token t:live){if(t==token)break;auto& old=owner(t);if(old.instruction.kind==ArchKind::Store&&old.killed==never&&old.evaluationReady)
                check(old.evaluation.address!=va,"UNSUPPORTED_UNRETIRED_STORE_ALIAS_IN_FROZEN_GUEST");}
        }
        e.evaluation=architecture.evaluate(e.instruction.pc,e.instruction.word,left,right);e.evaluationReady=true;return e.evaluation;
    }
    uint64_t expected_pa(Token token){auto& e=owner(token);check(e.started!=never,"TRANSPORT_BEFORE_REAL_START");return evaluate(token).physical_address;}
    bool expected_local_fault(Token token,unsigned flags){
        auto& e=owner(token);auto& result=evaluate(token);
        return e.started!=never&&result.translation.fault&&flags==(result.translation.fault->cause==13||result.translation.fault->cause==15?3U:1U);
    }
    bool mutate(const std::string& name){
        if(applied||mutation!=name)return false;applied=true;
        std::cerr<<"B1_MUTATION_APPLIED name="<<name<<" case="<<scenario.name<<" cycle="<<cycle<<"\n";return true;
    }
    bool still_held(Token token,const Snapshot& s,uint64_t edge)const{
        const auto& p=s.stage[0];const auto& e=owner(token);
        return p.occupied&&p.held==token&&!p.deqReady&&e.completed>edge&&e.killed>edge;
    }
    void chain(History& e,unsigned kind,const Snapshot& s){
        for(auto writer:{e.leftWriter,e.rightWriter})if(writer){
            const auto& c=owner(*writer);if(!c.heldProducer)continue;
            check(c.completed<cycle,"DESCENDANT_BEFORE_C1_REGISTERED_READY_EDGE");
            const char* type=kind==0?"load":kind==1?"M":"store";
            ++counters[std::string(type)+"_after_held_C1"];
            if(still_held(*c.heldProducer,s,cycle)){++counters[std::string(type)+"_while_exact_P0_held"];
                std::cout<<"B1_CHAIN kind="<<type<<" P0="<<token_text(*c.heldProducer)<<" C1="<<token_text(*writer)<<" descendant="<<token_text(e.token)<<" cycle="<<cycle<<"\n";}
            break;
        }
    }
    // Capture is checked one sample after its real handshake. Stage enqueue is
    // last-priority over old-owner cancel/drain, so the next held payload is the
    // exact accepted incoming payload. All source authority uses previous edge.
    void delayed_captures(Snapshot& now){
        if(!havePrevious)return;
        for(unsigned n=0;n<2;++n){
            const auto& old=previous.stage[n];auto& held=now.stage[n];
            if(old.capture()){
                check(held.occupied,"ACCEPTED_CAPTURE_NOT_RETAINED");auto& e=owner(held.held);
                check(e.allocation<=previous.cycle&&e.capture==never&&e.killed>previous.cycle,"CAPTURE_KILLED_DUPLICATE_OR_UNALLOCATED");
                check(ordinary(e.instruction.kind),"NON_ALU_ENTERED_EXECUTION_STAGE");
                check(held.heldSource1==e.source1&&held.heldSource2==e.source2&&held.destination==e.destination,"CAPTURE_PHYSICAL_ASSOCIATION");
                const bool needsLeft=e.instruction.kind!=ArchKind::Auipc&&e.instruction.kind!=ArchKind::Jal;
                const bool needsRight=e.instruction.kind==ArchKind::Add||e.instruction.kind==ArchKind::Branch;
                check(held.heldUsePc==(!needsLeft)&&held.heldUseImmediate==(!needsRight),"CAPTURE_DECODED_OPERAND_SELECTION");
                auto l=source(e.leftWriter),r=source(e.rightWriter);
                auto available=[&](std::optional<Token> writer,unsigned physical){
                    if(old_ready(writer,previous.cycle))return true;
                    for(const auto& p:previous.stage)if(p.promise&&!p.cancel&&p.promiseDestination==physical&&writer==p.held)return true;
                    const auto& load=previous.complete[0];
                    return writer&&load.valid&&load.accepted&&!load.exception&&load.producer==Producer::lsu&&load.token==*writer;
                };
                if(needsLeft)check(available(e.leftWriter,e.source1),"CAPTURE_LEFT_LACKS_AUTHORITY");
                if(needsRight)check(available(e.rightWriter,e.source2),"CAPTURE_RIGHT_LACKS_AUTHORITY");
                auto left=held.left,right=held.right;
                const auto& p=previous.stage[0];unsigned heldMask=0;
                if(p.occupied&&!p.deqReady&&p.promise){if(needsLeft&&e.leftWriter==p.held)heldMask|=1;if(needsRight&&e.rightWriter==p.held)heldMask|=2;}
                bool replacement=false,mixed=false;
                for(const auto& producer:previous.stage){
                    const bool uses=(needsLeft&&e.leftWriter==producer.held)||(needsRight&&e.rightWriter==producer.held);
                    if(producer.promise&&producer.deqReady&&producer.capture()&&uses){replacement=true;if(mutate("replacement")){if(needsLeft&&e.leftWriter==producer.held)left^=1;else right^=1;}}
                }
                const auto& load=previous.complete[0];
                if(load.valid&&load.accepted&&load.producer==Producer::lsu&&!load.exception){
                    bool leftLoad=needsLeft&&e.leftWriter==load.token,rightLoad=needsRight&&e.rightWriter==load.token;
                    for(const auto& producer:previous.stage)if(producer.promise&&((leftLoad&&needsRight&&e.rightWriter==producer.held)||(rightLoad&&needsLeft&&e.leftWriter==producer.held))){mixed=true;if(mutate("priority")){if(leftLoad)left=producer.result;else right=producer.result;}}
                }
                if(needsLeft)check(left==l,replacement?"OLD_VALUE_REFILL_OPERAND":mixed?"SELECTED_LOAD_PRIORITY_OPERAND":"INDEPENDENT_CAPTURE_LEFT");
                if(needsRight)check(right==r,replacement?"OLD_VALUE_REFILL_OPERAND":mixed?"SELECTED_LOAD_PRIORITY_OPERAND":"INDEPENDENT_CAPTURE_RIGHT");
                if(heldMask){
                    check(enabled&&n==1&&!p.cancel&&still_held(p.held,previous,previous.cycle),"HELD_CAPTURE_EXACT_OLD_OWNER");
                    check(!previous.ready[p.destination],"HELD_PROMISE_PREMATURE_REGISTERED_READY");
                    e.heldProducer=p.held;++counters["held_captures"];++counters[heldMask==1?"held_left":heldMask==2?"held_right":"held_both"];
                    std::string cause=previous.complete[0].producer==Producer::lsu?"lsu":previous.complete[0].producer==Producer::divider?"divider":previous.complete[0].producer==Producer::multiplier?"multiplier":previous.complete[0].producer==Producer::system?"system":"other";
                    ++counters["held_capture_selected_"+cause];
                    std::cout<<"B1_HELD_CAPTURE P0="<<token_text(p.held)<<" C1="<<token_text(e.token)<<" edge="<<previous.cycle<<" selected="<<cause<<"\n";
                }
                counters["consume_refill"]+=replacement;counters["mixed_load_alu"]+=mixed;
                e.capture=previous.cycle;e.captureLane=n;
            }else if(old.occupied&&!old.deqReady&&!old.cancel){
                check(held.occupied&&held.held==old.held&&held.destination==old.destination&&held.left==old.left&&held.right==old.right&&held.result==old.result&&held.forwardable==old.forwardable,"STALLED_FULL_PAYLOAD_CHANGED");
            }else if(old.occupied&&(old.cancel||old.drain()))check(!held.occupied,"DRAINED_OR_CANCELLED_OLD_OWNER_RETAINED");
        }
    }
    void recover(const Snapshot& s){
        if(!s.recovery.accepted)return;
        const auto& recovery=s.recovery;auto& boundary=owner(recovery.token);
        check(is_live(recovery.token),"RECOVERY_UNKNOWN_LIVE_BOUNDARY");
        if(recovery.kind==RecoveryKind::branch){check(control(boundary.instruction.kind),"BRANCH_RECOVERY_CLASS");check(evaluate(boundary.token).nextpc==recovery.target,"INDEPENDENT_BRANCH_TARGET");}
        if(recovery.kind==RecoveryKind::system)check(system_kind(boundary.instruction.kind),"SYSTEM_RECOVERY_CLASS");
        auto at=std::find(live.begin(),live.end(),recovery.token);auto first=at+(recovery.inclusive?0:1);
        for(auto i=first;i!=live.end();++i){auto& e=owner(*i);e.killed=cycle;++counters["killed_owners"];}
        live.erase(first,live.end());++counters["recoveries"];
    }
    void starts(const Snapshot& s){
        auto start=[&](const Start& t,unsigned kind){if(!t.fire)return;auto& e=owner(t.token);
            check(is_live(t.token)&&e.killed==never&&e.started==never,"START_FULL_TOKEN_LIFETIME");
            check(old_ready(e.leftWriter,cycle),"NON_ALU_START_LEFT_BEFORE_REGISTERED_READY");
            if(kind||e.instruction.kind==ArchKind::Store)check(old_ready(e.rightWriter,cycle),"NON_ALU_START_RIGHT_BEFORE_REGISTERED_READY");
            // Evaluate at real start, after all prior protected system changes.
            e.started=cycle;e.evaluationReady=false;auto& value=evaluate(e.token);
            if(kind==0){check(e.instruction.kind==(t.store?ArchKind::Store:ArchKind::Load),"LSU_START_CLASS");check(t.address==value.address,"LSU_START_ORIGINAL_VA");if(t.store)check(t.data==value.store_value,"LSU_START_RAW_STORE_DATA");}
            else {check(e.instruction.kind==(kind==1?ArchKind::Mul:ArchKind::Divu),"M_START_CLASS");check(t.left==source(e.leftWriter)&&t.right==source(e.rightWriter),"M_START_RAW_PRF_OPERANDS");}
            e.started=cycle;if(!t.store||kind)chain(e,kind?1:0,s);
        };
        start(s.memory,0);start(s.multiplier,1);start(s.divider,2);
        for(const auto& p:s.storePrepare)if(p.grant){auto& e=owner(p.token);check(is_live(p.token)&&e.killed==never&&e.instruction.kind==ArchKind::Store,"STORE_GRANT_FULL_TOKEN");
            check(old_ready(e.leftWriter,cycle),"STORE_BASE_BEFORE_REGISTERED_READY");check(p.base==source(e.leftWriter)&&p.immediate==e.instruction.immediate,"STORE_RAW_BASE_IMMEDIATE");
            check(p.dataReady==old_ready(e.rightWriter,cycle),"STORE_DATA_READY_HISTORY");if(p.dataReady){check(p.data==source(e.rightWriter),"STORE_RAW_PRF_DATA");if(e.prepared==never){e.prepared=cycle;chain(e,2,s);}}}
        if(s.system.fire){auto& e=owner(s.system.token);check(is_live(e.token)&&s.headValid&&s.head==e.token&&system_kind(e.instruction.kind),"SYSTEM_REAL_PROTECTED_HEAD_START");
            check(s.system.pc==e.instruction.pc&&s.system.instruction==e.instruction.word,"SYSTEM_START_PC_INSTRUCTION");
            check(old_ready(e.leftWriter,cycle)&&s.system.operand==source(e.leftWriter),"SYSTEM_REGISTERED_RAW_OPERAND");e.started=cycle;e.evaluationReady=false;(void)evaluate(e.token);}
        if(s.systemProtected)check(s.headValid&&s.systemOwner==s.head&&is_live(s.systemOwner),"SYSTEM_PROTECTED_FULL_TOKEN_HEAD");
    }
    void sample(Snapshot s){
        cycle=s.cycle;check(cycle<30000,"DIRECTED_30000_CYCLE_BOUND");
        counters["context_flush_events"]+=s.contextFlush;
        counters["pmp_change_events"]+=s.pmpChanged;
        counters["actual_virtual_lsu_starts"]+=s.memory.fire&&s.memory.virtualized;
        delayed_captures(s);
        if(havePrevious){for(unsigned p=0;p<48;++p){bool expected=previous.ready[p];for(auto w:previous.wake)if(w.valid&&w.destination==p)expected=true;for(auto r:previous.reserve)if(r.valid&&r.destination==p)expected=false;check(s.ready[p]==expected,"REGISTERED_READY_WAKE_RESERVE_EDGE");}}
        recover(s);
        for(unsigned n=0;n<2;++n){const auto& p=s.stage[n];check(p.enqReady==(!p.occupied||p.deqReady),"STAGE_CREDIT_EQUATION");check(p.deqValid==(p.occupied&&!p.cancel),"STAGE_CANCEL_VALID_EQUATION");
            if(!p.occupied){check(!p.promise,"EMPTY_STAGE_PROMISE");continue;}auto& e=owner(p.held);
            check(e.capture<cycle&&e.captureLane==n,"HELD_STAGE_LACKS_ACCEPTED_CAPTURE");check(p.cancel==(e.killed<=cycle),"STAGE_CANCEL_PRECISE_SUFFIX");
            const bool legal=e.instruction.writes&&ordinary(e.instruction.kind)&&!control(e.instruction.kind);
            check(p.forwardable==legal,"INDEPENDENT_HELD_LEGALITY");check(p.promise==(legal&&((enabled&&n==0)||p.deqReady)),"HELD_PROMISE_EQUATION");
            if(legal){check(p.result==evaluate(e.token).result,"INDEPENDENT_HELD_RESULT");if(p.promise)check(p.promiseDestination==e.destination,"PROMISE_DESTINATION_FULL_OWNER");}
            if(!p.deqReady&&!p.cancel){check(!p.capture()&&e.completed==never,"STALLED_OWNER_NO_COMPLETION_OR_CREDIT");if(e.instruction.writes)check(!s.ready[e.destination],"HELD_PRODUCER_REGISTERED_READY");++counters["occupied_stall_cycles"];}
        }
        if(s.stage[0].occupied&&s.stage[0].cancel&&s.stage[1].occupied&&s.stage[1].cancel&&owner(s.stage[1].held).heldProducer==s.stage[0].held)++counters["same_edge_P0_C1_cancel"];
        starts(s);
        if(s.response.fire()){
            auto i=requests.find(s.response.handle);check(i!=requests.end(),"INTEGER_REPLY_NO_ACCEPTED_HANDLE");auto token=i->second;
            if(owner(token).killed!=never){++counters["killed_response_drains"];if(mutate("stale_response"))token.tag^=UINT64_C(1)<<63;}
            (void)owner(token);check(token==i->second,"STALE_RESPONSE_FULL_TOKEN_ATTRIBUTION");
            requests.erase(i);++counters["integer_replies"];
        }
        if(s.request.fire()){check(s.request.ownerValid,"QUEUED_REQUEST_MISSING_AUTHORITATIVE_OWNER");auto& e=owner(s.request.token);check(e.started!=never,"QUEUED_REQUEST_NO_PRIOR_START");
            if(e.killed!=never){
                const bool ownedDiscard=std::any_of(s.lsuOwners.begin(),s.lsuOwners.end(),[&](const LsuOwner& slot){return slot.live&&slot.token==e.token&&!slot.store&&(slot.cancel||slot.discard);});
                check(e.instruction.kind==ArchKind::Load&&e.started<cycle&&e.started<e.killed&&ownedDiscard&&!s.request.write&&!s.request.atomic,"KILLED_REQUEST_LACKS_PRIOR_OWNED_LSU_DRAIN");
                ++counters["killed_owned_request_drains"];
            }
            check(requests.emplace(s.request.handle,e.token).second,"LIVE_INTEGER_HANDLE_REUSED");++counters["integer_requests"];}
        for(const auto& slot:s.lsuOwners)if(slot.live){auto& e=owner(slot.token);check(e.started<cycle,"LSU_SLOT_NO_PRIOR_START");if(slot.savedDestinationValid)check(slot.savedDestination==e.destination&&!slot.store,"LSU_SAVED_DESTINATION_FULL_OWNER");}
        // Sample-only mutations fire exactly once at their actual causal events.
        for(auto& c:s.complete)if(c.valid&&c.accepted&&history.contains(c.token)&&owner(c.token).heldProducer){if(mutate("value"))c.data^=1;if(mutate("owner"))c.token.tag^=UINT64_C(1)<<63;}
        if(s.recovery.accepted&&mutation=="kill"&&!applied){for(const auto& [t,e]:history)if(e.killed==cycle&&e.heldProducer){if(mutate("kill")){s.complete[1].valid=s.complete[1].accepted=true;s.complete[1].token=t;}break;}}
        std::set<Token> priorOffered;
        for(unsigned n=0;n<2;++n){auto& c=s.complete[n];bool expected=false;
            if(c.valid&&history.contains(c.token)){auto& e=owner(c.token);expected=is_live(c.token)&&e.killed==never&&e.completed==never&&!priorOffered.contains(c.token)&&!s.trap.valid;
                if(s.recovery.accepted&&s.recovery.kind==RecoveryKind::system)expected=expected&&s.headValid&&c.token==s.head;}
            check(c.accepted==expected,"INDEPENDENT_FULL_TOKEN_COMPLETION_ADMISSION");if(c.valid)priorOffered.insert(c.token);
            if(!c.accepted){check(!s.prfWrite[n].valid&&!s.wake[n].valid,"PRF_WAKE_WITHOUT_ACCEPTED_COMPLETION");continue;}
            auto& e=owner(c.token);
            if(!ordinary(e.instruction.kind))check(e.started<cycle,"ACCEPTED_COMPLETION_WITHOUT_PRIOR_START");
            else check(e.capture<cycle,"ACCEPTED_EXECUTION_WITHOUT_PRIOR_CAPTURE");
            auto& v=evaluate(e.token);check(c.exception==bool(v.trap),"INDEPENDENT_COMPLETION_EXCEPTION");
            if(v.trap)check(c.cause==v.trap->cause&&c.tval==v.trap->tval,"INDEPENDENT_PRECISE_COMPLETION_FAULT");
            else if(e.instruction.writes)check(c.data==v.result,"INDEPENDENT_COMPLETION_VALUE");
            const bool write=e.instruction.writes&&!v.trap;check(s.prfWrite[n].valid==write&&s.wake[n].valid==write,"ACCEPTED_PRF_READY_QUALIFICATION");
            if(write){check(s.prfWrite[n].destination==e.destination&&s.prfWrite[n].data==v.result&&s.wake[n].destination==e.destination,"INDEPENDENT_PRF_VALUE_OWNER");}
            if(e.heldProducer){++counters["held_C1_accepted"];if(still_held(*e.heldProducer,s,cycle))++counters["C1_accepted_while_exact_P0_held"];}
            e.completed=cycle;e.observedData=c.data;
        }
        for(const auto& r:s.retire)if(r.valid){check(!live.empty()&&live.front()==r.token,"INDEPENDENT_ORDERED_RETIRE_FULL_TOKEN");auto& e=owner(r.token);
            check(e.killed==never&&e.completed<=cycle&&!evaluate(e.token).trap&&e.retired==never,"RETIRE_KILLED_FAULTING_OR_UNCOMPLETED");
            check(r.pc==e.instruction.pc&&r.instruction==e.instruction.word&&r.writes==e.instruction.writes,"RETIRE_ACCEPTED_INSTRUCTION_IDENTITY");
            if(r.writes)check(r.destination==e.destination,"RETIRE_PHYSICAL_DESTINATION_GENERATION");
            const uint64_t retiredData=r.dataValid?r.data:e.observedData;
            if(r.dataValid&&r.writes)check(r.data==e.observedData,"RETIRE_ACCEPTED_COMPLETION_DATA");
            architecture.retire(r.pc,r.instruction,uint8_t(r.rd),retiredData,r.nextPc);e.retired=cycle;live.erase(live.begin());++retired;
            if(terminalSeen&&e.instruction.kind==ArchKind::Store)++counters["postterminal_handler_stores"];
            if(e.instruction.writes)committedWriter[e.instruction.rd]=e.token;
            architecturalHash=(architecturalHash^r.pc)*UINT64_C(1099511628211);architecturalHash=(architecturalHash^(e.instruction.writes?retiredData:0))*UINT64_C(1099511628211);
            if(r.pc==scenario.terminal&&!terminalSeen){terminalSeen=true;terminalCycle=cycle;
                for(const auto& store:architecture.store_history())terminalStores[store.physical_address]={store.size,architecture.read_memory(store.physical_address,store.size)};
            }
        }
        if(s.trap.valid){auto actual=s.trap;if(mutate("trap"))actual.tval^=1;auto& e=owner(actual.token);
            check(e.instruction.pc==actual.pc,"TRAP_FULL_TOKEN_PC");architecture.trap(actual.pc,actual.cause,actual.tval);++faults;
            if(actual.pc==scenario.faultPc){check(scenario.fault&&actual.cause==scenario.faultCause&&actual.tval==scenario.faultTval,"PRECISE_GUEST_TRAP");++counters["expected_faults"];}
            else check(terminalSeen&&actual.pc==scenario.terminal+4&&actual.cause==9,"UNEXPECTED_GUEST_TRAP");
        }
        // Accepted rename is last; source association comes from independent
        // program order and logical register writers, including same packet.
        auto writers=committedWriter;
        for(Token t:live){const auto& e=owner(t);if(e.instruction.writes)writers[e.instruction.rd]=t;}
        check(!s.rename[1].valid||s.rename[0].valid,"RENAME_NONPREFIX_PACKET");
        for(const auto& r:s.rename)if(r.valid){check(!history.contains(r.token)&&r.token.index<16,"REUSED_FULL_RENAME_TOKEN");
            check(r.instruction==uint32_t(architecture.read_memory(r.pc,4)),"ACCEPTED_INSTRUCTION_FROZEN_BYTES");
            History e;e.token=r.token;
            if(r.instruction==0){e.declaredIllegal=true;e.instruction.word=0;e.instruction.writes=false;}else e.instruction=Architecture::decode(r.instruction);e.instruction.pc=r.pc;e.allocation=cycle;e.destination=r.destination;e.source1=r.source1;e.source2=r.source2;
            check(!r.moveAlias&&r.writes==e.instruction.writes,"RENAME_WRITES_OR_ALIAS_CONTRACT");
            e.leftWriter=e.instruction.rs1?writers[e.instruction.rs1]:std::nullopt;e.rightWriter=e.instruction.rs2?writers[e.instruction.rs2]:std::nullopt;
            if(e.leftWriter)check(r.source1==owner(*e.leftWriter).destination,"INDEPENDENT_RENAME_SOURCE1_WRITER");
            if(e.rightWriter)check(r.source2==owner(*e.rightWriter).destination,"INDEPENDENT_RENAME_SOURCE2_WRITER");
            for(const auto& [oldToken,old]:history)if(old.killed!=never&&is_role(old,"p0","c1")){
                bool owed=false;for(auto [handle,token]:requests)if(owner(token).killed!=never&&is_role(owner(token),"load",""))owed=true;
                if(owed&&r.token.index==oldToken.index&&r.token.tag!=oldToken.tag)exactRobReuse.insert(oldToken);
                if(owed&&e.instruction.writes&&old.instruction.writes&&r.destination==old.destination)exactPrfReuse.insert(oldToken);
            }
            history.emplace(e.token,e);live.push_back(e.token);if(e.instruction.writes)writers[e.instruction.rd]=e.token;
        }
        previous=std::move(s);havePrevious=true;
    }
    bool is_role(const History& e,const std::string& a,const std::string& b)const{
        auto matches=[&](const std::string& n){auto i=scenario.roles.find(n);return i!=scenario.roles.end()&&e.instruction.pc==i->second;};return matches(a)||(!b.empty()&&matches(b));
    }
    void verify_terminal(){
        check(terminalSeen,"TERMINAL_MARKER_NOT_REACHED");check(counters["expected_faults"]==scenario.expectedFaults,"EXPECTED_FAULT_COUNT");check(requests.empty(),"UNDRAINED_INTEGER_OBLIGATIONS");
        check(architecture.read_memory(scenario.signatureAddress)==scenario.signature,"ARCHITECTURAL_TERMINAL_SIGNATURE");
        check(architecture.read_memory(scenario.sentinelAddress)==scenario.sentinel,"ARCHITECTURAL_SENTINEL_EFFECT");
        check(enabled||counters["held_captures"]==0,"OFF_HELD_CAPTURE_FORBIDDEN");
        if(!mutation.empty())check(applied,"MUTATION_NOT_REACHED");
    }
    void report(){
        counters["exact_P0_C1_rob_reuse_before_reply"]=exactRobReuse.size();counters["exact_P0_C1_prf_reuse_before_reply"]=exactPrfReuse.size();
        std::cout<<"B1_DIRECTED_CASE {\"name\":\""<<scenario.name<<"\",\"enabled\":"<<enabled<<",\"cycles\":"<<cycle<<",\"retired\":"<<retired<<",\"architectural_hash\":\""<<architecturalHash<<"\",\"observations\":{";
        bool first=true;for(auto [name,n]:counters){if(!first)std::cout<<',';first=false;std::cout<<'"'<<name<<"\":"<<n;}std::cout<<"},\"coverage_verdict\":\"REQUIRES_FAMILY_AGGREGATION\"}\n";
    }
};
} // namespace b1
