#include "ProtectedFpRetirementGsim.h"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>
using Fields = std::map<std::string, uint64_t>;
static uint64_t get(const Fields& x, const std::string& k) { return x.at(k); }
static void json(std::ostream& o, const Fields& x) { o << '{'; bool first=true; for (auto& [k,v]:x) { if (!first) o << ','; first=false; o << '\"' << k << "\":" << v; } o << '}'; }
static std::string diagnosticContext;
static void check(bool ok, const std::string& name) { if (!ok) throw std::runtime_error("PROTECTED_FP_CHECK["+name+"]"+diagnosticContext); }
struct Row { std::string phase; Fields in, pre, post; };
static Fields defaults() { return Fields{
    {"issue_valid",0},
    {"issue_bits_token_index",0},
    {"issue_bits_token_tag",0},
    {"issue_bits_instruction",0},
    {"issue_bits_sources_0",0},
    {"issue_bits_sources_1",0},
    {"issue_bits_sources_2",0},
    {"issue_bits_checkSingleBox_0",0},
    {"issue_bits_checkSingleBox_1",0},
    {"issue_bits_checkSingleBox_2",0},
    {"issue_bits_integerSource",0},
    {"issue_bits_destination",0},
    {"issue_bits_singleResult",0},
    {"issue_bits_writesFp",0},
    {"issue_bits_writesFlags",0},
    {"issue_bits_usesRounding",0},
    {"issue_bits_rounding",0},
    {"execute_ready",1},
    {"result_valid",0},
    {"result_bits_token_index",0},
    {"result_bits_token_tag",0},
    {"result_bits_value",0},
    {"result_bits_flags",0},
    {"result_bits_exception",0},
    {"result_bits_cause",0},
    {"result_bits_tval",0},
    {"result_bits_guestFault_guestPageFault",0},
    {"result_bits_guestFault_guestAddress",0},
    {"result_bits_guestFault_guestPhysicalAddress",0},
    {"result_bits_guestFault_implicitPte",0},
    {"commit0_valid",0},
    {"commit0_bits_index",0},
    {"commit0_bits_tag",0},
    {"commit1_valid",0},
    {"commit1_bits_index",0},
    {"commit1_bits_tag",0},
    {"completeAccept",0},
    {"csr_valid",0},
    {"csr_bits_address",3},
    {"csr_bits_operation",0},
    {"csr_bits_write",0},
    {"csr_bits_value",0},
    {"status_valid",0},
    {"status_bits_address",0},
    {"status_bits_data",0},
    {"statusReadAddress",256},
    {"mret",0},
    {"sret",0},
}; }
static void drive(SProtectedFpRetirementGsim& d, const Fields& x) {
    d.set_io$$issue$$valid(get(x,"issue_valid"));
    d.set_io$$issue$$bits$$token$$index(get(x,"issue_bits_token_index"));
    d.set_io$$issue$$bits$$token$$tag(get(x,"issue_bits_token_tag"));
    d.set_io$$issue$$bits$$instruction(get(x,"issue_bits_instruction"));
    d.set_io$$issue$$bits$$sources_0(get(x,"issue_bits_sources_0"));
    d.set_io$$issue$$bits$$sources_1(get(x,"issue_bits_sources_1"));
    d.set_io$$issue$$bits$$sources_2(get(x,"issue_bits_sources_2"));
    d.set_io$$issue$$bits$$checkSingleBox_0(get(x,"issue_bits_checkSingleBox_0"));
    d.set_io$$issue$$bits$$checkSingleBox_1(get(x,"issue_bits_checkSingleBox_1"));
    d.set_io$$issue$$bits$$checkSingleBox_2(get(x,"issue_bits_checkSingleBox_2"));
    d.set_io$$issue$$bits$$integerSource(get(x,"issue_bits_integerSource"));
    d.set_io$$issue$$bits$$destination(get(x,"issue_bits_destination"));
    d.set_io$$issue$$bits$$singleResult(get(x,"issue_bits_singleResult"));
    d.set_io$$issue$$bits$$writesFp(get(x,"issue_bits_writesFp"));
    d.set_io$$issue$$bits$$writesFlags(get(x,"issue_bits_writesFlags"));
    d.set_io$$issue$$bits$$usesRounding(get(x,"issue_bits_usesRounding"));
    d.set_io$$issue$$bits$$rounding(get(x,"issue_bits_rounding"));
    d.set_io$$execute$$ready(get(x,"execute_ready"));
    d.set_io$$result$$valid(get(x,"result_valid"));
    d.set_io$$result$$bits$$token$$index(get(x,"result_bits_token_index"));
    d.set_io$$result$$bits$$token$$tag(get(x,"result_bits_token_tag"));
    d.set_io$$result$$bits$$value(get(x,"result_bits_value"));
    d.set_io$$result$$bits$$flags(get(x,"result_bits_flags"));
    d.set_io$$result$$bits$$exception(get(x,"result_bits_exception"));
    d.set_io$$result$$bits$$cause(get(x,"result_bits_cause"));
    d.set_io$$result$$bits$$tval(get(x,"result_bits_tval"));
    d.set_io$$result$$bits$$guestFault$$guestPageFault(get(x,"result_bits_guestFault_guestPageFault"));
    d.set_io$$result$$bits$$guestFault$$guestAddress(get(x,"result_bits_guestFault_guestAddress"));
    d.set_io$$result$$bits$$guestFault$$guestPhysicalAddress(get(x,"result_bits_guestFault_guestPhysicalAddress"));
    d.set_io$$result$$bits$$guestFault$$implicitPte(get(x,"result_bits_guestFault_implicitPte"));
    d.set_io$$commit0$$valid(get(x,"commit0_valid"));
    d.set_io$$commit0$$bits$$index(get(x,"commit0_bits_index"));
    d.set_io$$commit0$$bits$$tag(get(x,"commit0_bits_tag"));
    d.set_io$$commit1$$valid(get(x,"commit1_valid"));
    d.set_io$$commit1$$bits$$index(get(x,"commit1_bits_index"));
    d.set_io$$commit1$$bits$$tag(get(x,"commit1_bits_tag"));
    d.set_io$$completeAccept(get(x,"completeAccept"));
    d.set_io$$csr$$valid(get(x,"csr_valid"));
    d.set_io$$csr$$bits$$address(get(x,"csr_bits_address"));
    d.set_io$$csr$$bits$$operation(get(x,"csr_bits_operation"));
    d.set_io$$csr$$bits$$write(get(x,"csr_bits_write"));
    d.set_io$$csr$$bits$$value(get(x,"csr_bits_value"));
    d.set_io$$status$$valid(get(x,"status_valid"));
    d.set_io$$status$$bits$$address(get(x,"status_bits_address"));
    d.set_io$$status$$bits$$data(get(x,"status_bits_data"));
    d.set_io$$statusReadAddress(get(x,"statusReadAddress"));
    d.set_io$$mret(get(x,"mret"));
    d.set_io$$sret(get(x,"sret"));
}
static Fields observe(SProtectedFpRetirementGsim& d) { return Fields{
    {"issue_ready", uint64_t(d.get_io$$issue$$ready())},
    {"execute_valid", uint64_t(d.get_io$$execute$$valid())},
    {"execute_bits_command_token_index", uint64_t(d.get_io$$execute$$bits$$command$$token$$index())},
    {"execute_bits_command_token_tag", uint64_t(d.get_io$$execute$$bits$$command$$token$$tag())},
    {"execute_bits_command_instruction", uint64_t(d.get_io$$execute$$bits$$command$$instruction())},
    {"execute_bits_command_sources_0", uint64_t(d.get_io$$execute$$bits$$command$$sources_0())},
    {"execute_bits_command_sources_1", uint64_t(d.get_io$$execute$$bits$$command$$sources_1())},
    {"execute_bits_command_sources_2", uint64_t(d.get_io$$execute$$bits$$command$$sources_2())},
    {"execute_bits_command_checkSingleBox_0", uint64_t(d.get_io$$execute$$bits$$command$$checkSingleBox_0())},
    {"execute_bits_command_checkSingleBox_1", uint64_t(d.get_io$$execute$$bits$$command$$checkSingleBox_1())},
    {"execute_bits_command_checkSingleBox_2", uint64_t(d.get_io$$execute$$bits$$command$$checkSingleBox_2())},
    {"execute_bits_command_integerSource", uint64_t(d.get_io$$execute$$bits$$command$$integerSource())},
    {"execute_bits_command_destination", uint64_t(d.get_io$$execute$$bits$$command$$destination())},
    {"execute_bits_command_singleResult", uint64_t(d.get_io$$execute$$bits$$command$$singleResult())},
    {"execute_bits_command_writesFp", uint64_t(d.get_io$$execute$$bits$$command$$writesFp())},
    {"execute_bits_command_writesFlags", uint64_t(d.get_io$$execute$$bits$$command$$writesFlags())},
    {"execute_bits_command_usesRounding", uint64_t(d.get_io$$execute$$bits$$command$$usesRounding())},
    {"execute_bits_command_rounding", uint64_t(d.get_io$$execute$$bits$$command$$rounding())},
    {"execute_bits_operands_0", uint64_t(d.get_io$$execute$$bits$$operands_0())},
    {"execute_bits_operands_1", uint64_t(d.get_io$$execute$$bits$$operands_1())},
    {"execute_bits_operands_2", uint64_t(d.get_io$$execute$$bits$$operands_2())},
    {"execute_bits_rounding", uint64_t(d.get_io$$execute$$bits$$rounding())},
    {"result_ready", uint64_t(d.get_io$$result$$ready())},
    {"complete_valid", uint64_t(d.get_io$$complete$$valid())},
    {"complete_bits_token_index", uint64_t(d.get_io$$complete$$bits$$token$$index())},
    {"complete_bits_token_tag", uint64_t(d.get_io$$complete$$bits$$token$$tag())},
    {"complete_bits_value", uint64_t(d.get_io$$complete$$bits$$value())},
    {"complete_bits_flags", uint64_t(d.get_io$$complete$$bits$$flags())},
    {"complete_bits_exception", uint64_t(d.get_io$$complete$$bits$$exception())},
    {"complete_bits_cause", uint64_t(d.get_io$$complete$$bits$$cause())},
    {"complete_bits_tval", uint64_t(d.get_io$$complete$$bits$$tval())},
    {"complete_bits_guestFault_guestPageFault", uint64_t(d.get_io$$complete$$bits$$guestFault$$guestPageFault())},
    {"complete_bits_guestFault_guestAddress", uint64_t(d.get_io$$complete$$bits$$guestFault$$guestAddress())},
    {"complete_bits_guestFault_guestPhysicalAddress", uint64_t(d.get_io$$complete$$bits$$guestFault$$guestPhysicalAddress())},
    {"complete_bits_guestFault_implicitPte", uint64_t(d.get_io$$complete$$bits$$guestFault$$implicitPte())},
    {"retireAccepted", uint64_t(d.get_io$$retireAccepted())},
    {"csr_ready", uint64_t(d.get_io$$csr$$ready())},
    {"csrRead", uint64_t(d.get_io$$csrRead())},
    {"csrIllegal", uint64_t(d.get_io$$csrIllegal())},
    {"status_ready", uint64_t(d.get_io$$status$$ready())},
    {"statusReadData", uint64_t(d.get_io$$statusReadData())},
    {"statusShadow", uint64_t(d.get_io$$statusShadow())},
    {"virtualized", uint64_t(d.get_io$$virtualized())},
    {"hostFs", uint64_t(d.get_io$$hostFs())},
    {"hostSd", uint64_t(d.get_io$$hostSd())},
    {"guestFs", uint64_t(d.get_io$$guestFs())},
    {"guestSd", uint64_t(d.get_io$$guestSd())},
    {"mutation_valid", uint64_t(d.get_io$$mutation$$valid())},
    {"mutation_bits_guest", uint64_t(d.get_io$$mutation$$bits$$guest())},
    {"fcsr", uint64_t(d.get_io$$fcsr())},
    {"busy", uint64_t(d.get_io$$busy())},
    {"completionAccepted", uint64_t(d.get_io$$completionAccepted())},
    {"completionSeen", uint64_t(d.get_io$$completionSeen())},
    {"issueAccepted", uint64_t(d.get_io$$issueAccepted())},
    {"ownerActive", uint64_t(d.get_io$$ownerActive())},
    {"ownerToken_index", uint64_t(d.get_io$$ownerToken$$index())},
    {"ownerToken_tag", uint64_t(d.get_io$$ownerToken$$tag())},
    {"retired", uint64_t(d.get_io$$retired())},
    {"retireMatches", uint64_t(d.get_io$$retireMatches())},
    {"contextMemoryEpoch", uint64_t(d.get_io$$contextMemoryEpoch())},
    {"hMemoryEpoch", uint64_t(d.get_io$$hMemoryEpoch())},
    {"fpMemoryEpoch", uint64_t(d.get_io$$fpMemoryEpoch())},
    {"statePhase", uint64_t(d.get_io$$statePhase())},
    {"fpr_0", uint64_t(d.get_io$$fpr_0())},
    {"fpr_1", uint64_t(d.get_io$$fpr_1())},
    {"fpr_2", uint64_t(d.get_io$$fpr_2())},
    {"fpr_3", uint64_t(d.get_io$$fpr_3())},
    {"fpr_4", uint64_t(d.get_io$$fpr_4())},
    {"fpr_5", uint64_t(d.get_io$$fpr_5())},
    {"fpr_6", uint64_t(d.get_io$$fpr_6())},
    {"fpr_7", uint64_t(d.get_io$$fpr_7())},
    {"fpr_8", uint64_t(d.get_io$$fpr_8())},
    {"fpr_9", uint64_t(d.get_io$$fpr_9())},
    {"fpr_10", uint64_t(d.get_io$$fpr_10())},
    {"fpr_11", uint64_t(d.get_io$$fpr_11())},
    {"fpr_12", uint64_t(d.get_io$$fpr_12())},
    {"fpr_13", uint64_t(d.get_io$$fpr_13())},
    {"fpr_14", uint64_t(d.get_io$$fpr_14())},
    {"fpr_15", uint64_t(d.get_io$$fpr_15())},
    {"fpr_16", uint64_t(d.get_io$$fpr_16())},
    {"fpr_17", uint64_t(d.get_io$$fpr_17())},
    {"fpr_18", uint64_t(d.get_io$$fpr_18())},
    {"fpr_19", uint64_t(d.get_io$$fpr_19())},
    {"fpr_20", uint64_t(d.get_io$$fpr_20())},
    {"fpr_21", uint64_t(d.get_io$$fpr_21())},
    {"fpr_22", uint64_t(d.get_io$$fpr_22())},
    {"fpr_23", uint64_t(d.get_io$$fpr_23())},
    {"fpr_24", uint64_t(d.get_io$$fpr_24())},
    {"fpr_25", uint64_t(d.get_io$$fpr_25())},
    {"fpr_26", uint64_t(d.get_io$$fpr_26())},
    {"fpr_27", uint64_t(d.get_io$$fpr_27())},
    {"fpr_28", uint64_t(d.get_io$$fpr_28())},
    {"fpr_29", uint64_t(d.get_io$$fpr_29())},
    {"fpr_30", uint64_t(d.get_io$$fpr_30())},
    {"fpr_31", uint64_t(d.get_io$$fpr_31())},
}; }
static Fields architecture(const Fields& x) { Fields a; for (auto& [k,v]:x) if (k.rfind("fpr_",0)==0 || k=="fcsr" || k=="hostFs" || k=="guestFs" || k=="hostSd" || k=="guestSd" || k=="virtualized" || k=="ownerActive" || k=="ownerToken_index" || k=="ownerToken_tag" || k=="statePhase" || k=="completionSeen") a[k]=v; return a; }
// Encoded operations and decoded fields are frozen before model execution.
// Payloads are synthetic transport data, not arithmetic answers.
static std::vector<Fields> recipe() {
    std::vector<Fields> r;
    const uint32_t instructions[]={0x02007053,0x000072d3,0xc2007353,0xe20293d3};
    const uint64_t tags[]={0x1456000000000001ULL,0x2456000000000002ULL,0x3456000000000003ULL,0xb456000000000003ULL};
    const uint64_t values[]={0x400921fb54442d18ULL,0x123456783f400000ULL,0x1234ULL,0x80ULL};
    for (unsigned n=0;n<4;++n) {
        Fields x=defaults(); x["issue_valid"]=1; x["issue_bits_token_index"]=n==3?3:n+1; x["issue_bits_token_tag"]=tags[n];
        x["issue_bits_instruction"]=instructions[n]; x["issue_bits_destination"]=n==0?0:n+4;
        x["issue_bits_sources_0"]=(instructions[n]>>15)&31;
        x["issue_bits_sources_1"]=(instructions[n]>>20)&31; x["issue_bits_sources_2"]=(instructions[n]>>27)&31;
        x["issue_bits_singleResult"]=n==1; x["issue_bits_writesFp"]=n<2; x["issue_bits_writesFlags"]=n<3;
        x["issue_bits_usesRounding"]=n<3; x["issue_bits_rounding"]=(instructions[n]>>12)&7;
        x["issue_bits_checkSingleBox_0"]=n==1; x["issue_bits_checkSingleBox_1"]=n==1; x["issue_bits_checkSingleBox_2"]=n==1;
        x["result_bits_token_index"]=x["issue_bits_token_index"]; x["result_bits_token_tag"]=tags[n];
        x["result_bits_value"]=values[n]; x["result_bits_flags"]=1U<<(n+1); r.push_back(x);
    } return r;
}

static std::vector<Row> schedule(const std::string& name) {
    const unsigned eh=name=="baseline"?1:3, ch=name=="baseline"?2:5;
    std::vector<Row> rows;
    auto add=[&](std::string phase, Fields x=defaults()) { rows.push_back({phase,x,{},{}}); };
    auto grant=[](Fields& x,unsigned lane,const Fields& op) {
        const auto k="commit"+std::to_string(lane)+"_";
        x[k+"valid"]=1; x[k+"bits_index"]=get(op,"issue_bits_token_index"); x[k+"bits_tag"]=get(op,"issue_bits_token_tag");
    };
    Fields x=defaults(); x["commit0_valid"]=1; add("cold_lane0",x);
    x=defaults(); x["commit1_valid"]=1; add("cold_lane1",x);
    add("cold_invalid"); x=defaults(); x["commit0_valid"]=1; x["commit0_bits_tag"]=1ULL<<63; add("cold_tag",x);
    x=defaults(); x["commit1_valid"]=1; x["commit1_bits_index"]=1; add("cold_index",x);
    auto status=[&](std::string phase,unsigned address,uint64_t data) { Fields y=defaults(); y["status_valid"]=1; y["status_bits_address"]=address; y["status_bits_data"]=data; add(phase,y); };
    status("setup_host",0x300,2<<13); x=defaults(); x["csr_valid"]=x["csr_bits_write"]=1; x["csr_bits_value"]=97; add("setup_fcsr",x);
    status("clean_host",0x300,2<<13); status("setup_guest",0x200,2<<13);
    const auto r=recipe();
    for(unsigned n=0;n<4;++n) {
        const std::string p="op"+std::to_string(n)+"_";
        if(n==1) {
            status("guest_host_clean",0x300,2<<13); status("guest_vs_clean",0x200,2<<13);
            status("guest_spv",0x600,1<<7); x=defaults(); x["sret"]=1; add("guest_enter",x);
        }
        if(n==2) {
            status("flags_host_clean",0x300,2<<13); status("flags_vs_clean",0x200,2<<13);
        }
        x=r[n]; if(n==3) grant(x,1,r[2]); add(p+"issue",x);
        for(unsigned j=0;j<eh;++j) { x=defaults(); x["execute_ready"]=0;
            // A high-tag mismatch is legal while execute is held; never offer an early exact commit.
            grant(x,j%2,r[n]); x["commit"+std::to_string(j%2)+"_bits_tag"]^=1ULL<<63;
            add(p+"hold_execute_"+std::to_string(j),x);
        }
        add(p+"execute");
        x=defaults(); for(auto& [k,v]:r[n]) if(k.rfind("result_bits_",0)==0) x[k]=v;
        x["result_valid"]=1; x["result_bits_token_tag"]^=1ULL<<63;
        grant(x,1,r[n]); x["commit1_bits_index"]^=1; add(p+"stale_result",x);
        x["result_bits_token_tag"]^=1ULL<<63; x["commit1_bits_index"]^=1; x["commit1_valid"]=0; add(p+"result",x);
        for(unsigned j=0;j<ch;++j) { x=defaults(); x["completeAccept"]=1; add(p+"complete_hold_"+std::to_string(j),x); }
        x=defaults(); grant(x,0,r[n]); x["commit0_bits_tag"]^=1ULL<<63; add(p+"wrong_tag",x);
        x=defaults(); grant(x,1,r[n]); x["commit1_bits_index"]^=1; add(p+"wrong_index",x);
        x=defaults(); grant(x,0,r[n]); x["commit0_valid"]=0; add(p+"invalid",x);
        x=n==2?r[3]:defaults(); grant(x,n%2,r[n]); add(p+"retire",x);
        if(n!=2) for(unsigned lane=0;lane<2;++lane) { x=defaults(); grant(x,lane,r[n]); add(p+"repeat"+std::to_string(lane),x); }
    }
    add("final_idle_0"); add("final_idle_1"); return rows;
}

// Independent, input-driven software ledger. No expected state is learned from
// observations: raw values are checked only after all stimulus has completed.
static Fields verify(const std::vector<Row>& rows,const std::string& negative) {
    std::array<uint64_t,32> regs{};
    Fields pending=defaults(), response=defaults();
    std::array<uint64_t,3> operands{};
    unsigned state=0,host=0,guest=0,frm=0,flags=0,rm=0;
    uint64_t ownerTag=0,ownerIndex=0;
    bool active=false,v=false,spv=false,pendingGuest=false,seen=false,negativeHit=false;
    Fields metrics={{"schema",1},{"component_only",1},{"guest_fd_execution",0},{"issued",0},{"completion_accepts",0},{"owner_retired_pulses",0},{"successful_active_owner_retirements",0},{"inactive_owner_pulses",0},{"fp_retire_accepted",0},{"successful_fp_retirements",0},{"fp_architectural_mutations",0},{"fpr_writes",0},{"fflags_updates",0},{"host_dirty_events",0},{"guest_dirty_events",0}};
    unsigned cycle=0;
    for(const auto& row:rows) {
        diagnosticContext=" cycle="+std::to_string(cycle++)+" phase="+row.phase;
        const auto& x=row.in; Fields o=row.pre, post=row.post;
        const auto mutate=[&](const char* mode,const char* phase,Fields& target,const char* field,uint64_t value) {
            if(negative==mode && row.phase==phase) { target[field]=value; negativeHit=true; }
        };
        mutate("inactive_retire_accepted","cold_lane0",o,"retireAccepted",1);
        mutate("full_token","op0_hold_execute_0",o,"ownerToken_tag",uint32_t(ownerTag));
        mutate("premature_fpr","op0_hold_execute_0",o,"fpr_0",1);
        mutate("fflags_loss","op0_retire",post,"fcsr",frm<<5);
        mutate("guest_dirty","op1_retire",post,"guestFs",2);
        mutate("duplicate_retire","op0_repeat0",o,"retireAccepted",1);
        mutate("refill_credit","op2_retire",o,"issue_ready",1);
        const bool status=get(x,"status_valid"),csr=get(x,"csr_valid");
        const bool ready=state==0 && !status && !csr;
        const bool start=ready && get(x,"issue_valid");
        unsigned matches=0;
        for(unsigned lane=0;lane<2;++lane) {
            const auto k="commit"+std::to_string(lane)+"_";
            if(get(x,k+"valid") && get(x,k+"bits_index")==ownerIndex && get(x,k+"bits_tag")==ownerTag) matches|=1U<<lane;
        }
        const bool raw=matches!=0;
        const bool retire=state==3 && raw && ownerIndex==get(pending,"issue_bits_token_index") && ownerTag==get(pending,"issue_bits_token_tag");
        const bool complete=state==3,accepted=complete && get(x,"completeAccept") && !seen;
        const unsigned ca=get(x,"csr_bits_address");
        const bool illegal=host==0 || (v && guest==0) || ca<1 || ca>3 || get(x,"csr_bits_operation")==3;
        const uint64_t cr=ca==1?flags:ca==2?frm:ca==3?(frm<<5)|flags:0;
        const bool cm=csr && state==0 && !status && get(x,"csr_bits_write") && !illegal;
        const bool mutation=cm || (retire && (get(pending,"issue_bits_writesFp") || get(pending,"issue_bits_writesFlags")));
        const bool mutationGuest=cm?v:pendingGuest;
        auto eq=[&](const std::string& field,uint64_t expected,const std::string& diagnostic) { check(get(o,field)==expected,diagnostic); };
        eq("ownerActive",active,"owner_lifetime"); eq("ownerToken_index",ownerIndex,"full_token"); eq("ownerToken_tag",ownerTag,"full_token");
        eq("retired",raw,"raw_match"); eq("retireMatches",matches,"raw_match");
        eq("statePhase",state,"state_phase"); eq("busy",state!=0,"state_phase");
        eq("completionSeen",seen,"completion_once"); eq("completionAccepted",accepted,"completion_once");
        eq("issue_ready",ready,row.phase=="op2_retire"?"refill_credit":"issue_ready"); eq("issueAccepted",start,"issue_accepted");
        eq("retireAccepted",retire,row.phase=="cold_lane0"?"inactive_retire_accepted":row.phase=="op0_repeat0"?"duplicate_retire":"retire_accepted");
        eq("mutation_valid",mutation,"mutation"); if(mutation) eq("mutation_bits_guest",mutationGuest,"mutation_owner");
        eq("hostFs",host,"host_dirty"); eq("guestFs",guest,"guest_dirty"); eq("hostSd",host==3,"host_sd"); eq("guestSd",guest==3,"guest_sd");
        eq("fcsr",(frm<<5)|flags,"fflags_loss"); eq("virtualized",v,"virtualized");
        eq("contextMemoryEpoch",0,"memory_epoch"); eq("hMemoryEpoch",0,"memory_epoch"); eq("fpMemoryEpoch",0,"memory_epoch");
        eq("status_ready",state==0,"status_ready"); eq("csr_ready",state==0 && !status,"csr_ready"); eq("csrRead",cr,"csr_read"); eq("csrIllegal",illegal,"csr_illegal");
        const auto address=get(x,"statusReadAddress");
        const bool guestRead=address==0x200 || (address==0x100 && v);
        const unsigned readFs=guestRead?guest:host;
        const uint64_t mask=(3ULL<<13)|(1ULL<<63);
        check((get(o,"statusReadData")&mask)==((uint64_t(readFs)<<13)|(readFs==3?(1ULL<<63):0)),"status_read");
        eq("statusShadow",address==0x100 && v,"status_shadow");
        for(unsigned n=0;n<32;++n) eq("fpr_"+std::to_string(n),regs[n],"premature_fpr");
        eq("execute_valid",state==1,"execute_valid"); eq("complete_valid",complete,"complete_valid"); eq("result_ready",1,"result_ready");
        if(state==1) {
            for(const auto& [k,val]:pending) if(k.rfind("issue_bits_",0)==0) eq("execute_bits_command_"+k.substr(11),val,"execute_payload");
            for(unsigned lane=0;lane<3;++lane) eq("execute_bits_operands_"+std::to_string(lane),operands[lane],"execute_operand");
            eq("execute_bits_rounding",rm,"execute_rounding");
        }
        if(complete) for(const auto& [k,val]:response) if(k.rfind("result_bits_",0)==0) eq("complete_bits_"+k.substr(12),val,"complete_payload");
        if(raw) { ++metrics["owner_retired_pulses"]; ++metrics[active?"successful_active_owner_retirements":"inactive_owner_pulses"]; }
        if(accepted) { check(active,"completion_owner"); seen=true; ++metrics["completion_accepts"]; }
        if(status && state==0) {
            const auto a=get(x,"status_bits_address"),data=get(x,"status_bits_data");
            if(a==0x300 || (a==0x100 && !v)) host=(data>>13)&3;
            if(a==0x200 || (a==0x100 && v)) guest=(data>>13)&3;
            if(a==0x600) spv=(data>>7)&1;
        }
        if(cm) {
            const auto op=get(x,"csr_bits_operation"),value=get(x,"csr_bits_value");
            const auto written=op==0?value:op==1?(cr|value):(cr&~value);
            if(ca==1 || ca==3) flags=written&31;
            if(ca==2) frm=written&7;
            if(ca==3) frm=(written>>5)&7;
        }
        if(mutation) { host=3; if(mutationGuest) guest=3; }
        if(retire) {
            check(seen,"retire_before_completion_accept");
            if(get(pending,"issue_bits_writesFp")) {
                const auto value=get(response,"result_bits_value");
                regs[get(pending,"issue_bits_destination")]=get(pending,"issue_bits_singleResult")?(0xffffffff00000000ULL|uint32_t(value)):value;
                ++metrics["fpr_writes"];
            }
            if(get(pending,"issue_bits_writesFlags")) { flags|=get(response,"result_bits_flags"); ++metrics["fflags_updates"]; }
            if(mutation) { ++metrics["fp_architectural_mutations"]; ++metrics["host_dirty_events"]; if(pendingGuest) ++metrics["guest_dirty_events"]; }
            ++metrics["fp_retire_accepted"]; ++metrics["successful_fp_retirements"]; state=0;
        } else if(state==2 && get(x,"result_valid") && get(x,"result_bits_token_index")==get(pending,"issue_bits_token_index") && get(x,"result_bits_token_tag")==get(pending,"issue_bits_token_tag")) {
            response=x; state=3;
        } else if(state==1 && get(x,"execute_ready")) state=2;
        if(raw) active=false;
        if(start) {
            check(host && (!v || guest),"legal_issue"); pending=x; pendingGuest=v; seen=false; state=1;
            rm=get(x,"issue_bits_rounding")==7?frm:get(x,"issue_bits_rounding");
            for(unsigned lane=0;lane<3;++lane) {
                const auto suffix=std::to_string(lane); auto val=regs[get(x,"issue_bits_sources_"+suffix)];
                if(get(x,"issue_bits_checkSingleBox_"+suffix) && val>>32!=0xffffffffULL) val=0xffffffff7fc00000ULL;
                operands[lane]=val;
            }
            active=true; ownerIndex=get(x,"issue_bits_token_index"); ownerTag=get(x,"issue_bits_token_tag"); ++metrics["issued"];
        }
        if(get(x,"mret")) v=false;
        if(get(x,"sret") && !v) { v=spv; spv=false; }
        check(get(post,"ownerActive")==active && get(post,"ownerToken_index")==ownerIndex && get(post,"ownerToken_tag")==ownerTag,"full_token");
        check(get(post,"statePhase")==state && get(post,"completionSeen")==seen,"post_state");
        check(get(post,"fcsr")==((frm<<5)|flags),"fflags_loss");
        check(get(post,"hostFs")==host,"host_dirty"); check(get(post,"guestFs")==guest,"guest_dirty");
        check(get(post,"hostSd")==unsigned(host==3) && get(post,"guestSd")==unsigned(guest==3),"post_sd");
        check(get(post,"virtualized")==v,"post_v");
        for(unsigned n=0;n<32;++n) check(get(post,"fpr_"+std::to_string(n))==regs[n],"fpr_retirement");
    }
    check(negative.empty() || negativeHit,"negative_target_missing");
    check(state==0 && !active && metrics["issued"]==4 && metrics["completion_accepts"]==4 && metrics["fp_retire_accepted"]==4 && metrics["fp_architectural_mutations"]==3 && metrics["fpr_writes"]==2 && metrics["fflags_updates"]==3 && metrics["guest_dirty_events"]==2,"coverage");
    metrics["cycles"]=rows.size(); return metrics;
}

int main(int argc,char** argv) {
    try {
        std::string name="baseline",trace,negative;
        for(int n=1;n<argc;++n) {
            const std::string a=argv[n]; check(n+1<argc,"arguments");
            if(a=="--schedule") name=argv[++n]; else if(a=="--trace") trace=argv[++n]; else if(a=="--negative") negative=argv[++n]; else check(false,"arguments");
        }
        check((name=="baseline" || name=="staggered") && !trace.empty(),"arguments");
        const std::vector<std::string> negatives={"inactive_retire_accepted","full_token","premature_fpr","fflags_loss","guest_dirty","duplicate_retire","refill_credit"};
        bool known=negative.empty(); for(auto& n:negatives) known|=negative==n; check(known,"arguments");
        auto rows=schedule(name); check(rows.size()<=512,"cycle_bound");
        SProtectedFpRetirementGsim dut; drive(dut,defaults()); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        for(unsigned n=0;n<rows.size();++n) {
            drive(dut,rows[n].in); dut.step(); rows[n].pre=observe(dut);
            if(n) rows[n-1].post=architecture(rows[n].pre);
        }
        drive(dut,defaults()); dut.step(); rows.back().post=architecture(observe(dut));
        std::ofstream out(trace); check(bool(out),"trace_open");
        out << "{\"type\":\"header\",\"schema\":1,\"component_only\":true,\"guest_fd_execution\":false,\"cycle_limit\":512,\"schedule\":\"" << name << "\",\"execute_hold\":" << (name=="baseline"?1:3)
            << ",\"completed_hold\":" << (name=="baseline"?2:5) << ",\"recipe\":[";
        auto r=recipe(); for(unsigned n=0;n<r.size();++n) { if(n) out << ','; json(out,r[n]); } out << "]}\n";
        for(unsigned n=0;n<rows.size();++n) {
            out << "{\"type\":\"cycle\",\"cycle\":" << n << ",\"phase\":\"" << rows[n].phase << "\",\"in\":"; json(out,rows[n].in);
            out << ",\"pre\":"; json(out,rows[n].pre); out << ",\"post\":"; json(out,rows[n].post); out << "}\n";
        }
        out << "{\"type\":\"footer\",\"cycles\":" << rows.size() << ",\"complete\":true}\n";
        check(out.tellp()<=1048576,"trace_bound"); out.close(); check(bool(out),"trace_write");
        const auto metrics=verify(rows,negative);
        std::cout << "PROTECTED_FP_RETIREMENT_SUMMARY "; json(std::cout,metrics); std::cout << '\n'; return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
