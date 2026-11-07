#include "GuardedFpBridgeGsim.h"
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
static void check(bool ok, const std::string& name) { if (!ok) throw std::runtime_error("GUARDED_FP_CHECK["+name+"]"+diagnosticContext); }
struct Row { std::string phase; Fields in, pre, post; };
static Fields defaults() { return Fields{
    {"start_valid",0},
    {"start_bits_token_index",0},
    {"start_bits_token_tag",0},
    {"start_bits_pc",0},
    {"start_bits_instruction",0},
    {"start_bits_operand",0},
    {"start_bits_operand2",0},
    {"complete_ready",0},
    {"translationActive",1},
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
    {"commit0_valid",0},
    {"commit0_bits_index",0},
    {"commit0_bits_tag",0},
    {"commit1_valid",0},
    {"commit1_bits_index",0},
    {"commit1_bits_tag",0},
}; }
static void drive(SGuardedFpBridgeGsim& d, const Fields& x) {
    d.set_io$$start$$valid(get(x,"start_valid"));
    d.set_io$$start$$bits$$token$$index(get(x,"start_bits_token_index"));
    d.set_io$$start$$bits$$token$$tag(get(x,"start_bits_token_tag"));
    d.set_io$$start$$bits$$pc(get(x,"start_bits_pc"));
    d.set_io$$start$$bits$$instruction(get(x,"start_bits_instruction"));
    d.set_io$$start$$bits$$operand(get(x,"start_bits_operand"));
    d.set_io$$start$$bits$$operand2(get(x,"start_bits_operand2"));
    d.set_io$$complete$$ready(get(x,"complete_ready"));
    d.set_io$$translationActive(get(x,"translationActive"));
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
    d.set_io$$commit0$$valid(get(x,"commit0_valid"));
    d.set_io$$commit0$$bits$$index(get(x,"commit0_bits_index"));
    d.set_io$$commit0$$bits$$tag(get(x,"commit0_bits_tag"));
    d.set_io$$commit1$$valid(get(x,"commit1_valid"));
    d.set_io$$commit1$$bits$$index(get(x,"commit1_bits_index"));
    d.set_io$$commit1$$bits$$tag(get(x,"commit1_bits_tag"));
}
static Fields observe(SGuardedFpBridgeGsim& d) { return Fields{
    {"start_ready",uint64_t(d.get_io$$start$$ready())},
    {"complete_valid",uint64_t(d.get_io$$complete$$valid())},
    {"complete_bits_token_index",uint64_t(d.get_io$$complete$$bits$$token$$index())},
    {"complete_bits_token_tag",uint64_t(d.get_io$$complete$$bits$$token$$tag())},
    {"complete_bits_data",uint64_t(d.get_io$$complete$$bits$$data())},
    {"complete_bits_nextPc",uint64_t(d.get_io$$complete$$bits$$nextPc())},
    {"complete_bits_exception",uint64_t(d.get_io$$complete$$bits$$exception())},
    {"complete_bits_cause",uint64_t(d.get_io$$complete$$bits$$cause())},
    {"complete_bits_tval",uint64_t(d.get_io$$complete$$bits$$tval())},
    {"complete_bits_guestFault_guestPageFault",uint64_t(d.get_io$$complete$$bits$$guestFault$$guestPageFault())},
    {"complete_bits_guestFault_guestAddress",uint64_t(d.get_io$$complete$$bits$$guestFault$$guestAddress())},
    {"complete_bits_guestFault_guestPhysicalAddress",uint64_t(d.get_io$$complete$$bits$$guestFault$$guestPhysicalAddress())},
    {"complete_bits_guestFault_implicitPte",uint64_t(d.get_io$$complete$$bits$$guestFault$$implicitPte())},
    {"retireAccepted",uint64_t(d.get_io$$retireAccepted())},
    {"csr_ready",uint64_t(d.get_io$$csr$$ready())},
    {"csrRead",uint64_t(d.get_io$$csrRead())},
    {"csrIllegal",uint64_t(d.get_io$$csrIllegal())},
    {"status_ready",uint64_t(d.get_io$$status$$ready())},
    {"statusReadData",uint64_t(d.get_io$$statusReadData())},
    {"statusShadow",uint64_t(d.get_io$$statusShadow())},
    {"virtualized",uint64_t(d.get_io$$virtualized())},
    {"hostFs",uint64_t(d.get_io$$hostFs())},
    {"hostSd",uint64_t(d.get_io$$hostSd())},
    {"guestFs",uint64_t(d.get_io$$guestFs())},
    {"guestSd",uint64_t(d.get_io$$guestSd())},
    {"mutation_valid",uint64_t(d.get_io$$mutation$$valid())},
    {"mutation_bits_guest",uint64_t(d.get_io$$mutation$$bits$$guest())},
    {"fcsr",uint64_t(d.get_io$$fcsr())},
    {"busy",uint64_t(d.get_io$$busy())},
    {"completionAccepted",uint64_t(d.get_io$$completionAccepted())},
    {"completionSeen",uint64_t(d.get_io$$completionSeen())},
    {"issueAccepted",uint64_t(d.get_io$$issueAccepted())},
    {"ownerActive",uint64_t(d.get_io$$ownerActive())},
    {"ownerToken_index",uint64_t(d.get_io$$ownerToken$$index())},
    {"ownerToken_tag",uint64_t(d.get_io$$ownerToken$$tag())},
    {"retired",uint64_t(d.get_io$$retired())},
    {"retireMatches",uint64_t(d.get_io$$retireMatches())},
    {"contextMemoryEpoch",uint64_t(d.get_io$$contextMemoryEpoch())},
    {"hMemoryEpoch",uint64_t(d.get_io$$hMemoryEpoch())},
    {"fpMemoryEpoch",uint64_t(d.get_io$$fpMemoryEpoch())},
    {"statePhase",uint64_t(d.get_io$$statePhase())},
    {"fpr_0",uint64_t(d.get_io$$fpr_0())},
    {"fpr_1",uint64_t(d.get_io$$fpr_1())},
    {"fpr_2",uint64_t(d.get_io$$fpr_2())},
    {"fpr_3",uint64_t(d.get_io$$fpr_3())},
    {"fpr_4",uint64_t(d.get_io$$fpr_4())},
    {"fpr_5",uint64_t(d.get_io$$fpr_5())},
    {"fpr_6",uint64_t(d.get_io$$fpr_6())},
    {"fpr_7",uint64_t(d.get_io$$fpr_7())},
    {"fpr_8",uint64_t(d.get_io$$fpr_8())},
    {"fpr_9",uint64_t(d.get_io$$fpr_9())},
    {"fpr_10",uint64_t(d.get_io$$fpr_10())},
    {"fpr_11",uint64_t(d.get_io$$fpr_11())},
    {"fpr_12",uint64_t(d.get_io$$fpr_12())},
    {"fpr_13",uint64_t(d.get_io$$fpr_13())},
    {"fpr_14",uint64_t(d.get_io$$fpr_14())},
    {"fpr_15",uint64_t(d.get_io$$fpr_15())},
    {"fpr_16",uint64_t(d.get_io$$fpr_16())},
    {"fpr_17",uint64_t(d.get_io$$fpr_17())},
    {"fpr_18",uint64_t(d.get_io$$fpr_18())},
    {"fpr_19",uint64_t(d.get_io$$fpr_19())},
    {"fpr_20",uint64_t(d.get_io$$fpr_20())},
    {"fpr_21",uint64_t(d.get_io$$fpr_21())},
    {"fpr_22",uint64_t(d.get_io$$fpr_22())},
    {"fpr_23",uint64_t(d.get_io$$fpr_23())},
    {"fpr_24",uint64_t(d.get_io$$fpr_24())},
    {"fpr_25",uint64_t(d.get_io$$fpr_25())},
    {"fpr_26",uint64_t(d.get_io$$fpr_26())},
    {"fpr_27",uint64_t(d.get_io$$fpr_27())},
    {"fpr_28",uint64_t(d.get_io$$fpr_28())},
    {"fpr_29",uint64_t(d.get_io$$fpr_29())},
    {"fpr_30",uint64_t(d.get_io$$fpr_30())},
    {"fpr_31",uint64_t(d.get_io$$fpr_31())},
}; }
static Fields architecture(const Fields& x) { Fields a; for (auto& [k,v]:x) if (k.rfind("fpr_",0)==0 || k=="fcsr" || k=="hostFs" || k=="guestFs" || k=="hostSd" || k=="guestSd" || k=="virtualized" || k=="ownerActive" || k=="ownerToken_index" || k=="ownerToken_tag" || k=="statePhase" || k=="completionSeen" || k=="busy") a[k]=v; return a; }
// Independently encoded RV64 F/D instructions; no DUT decode header is included.
static std::vector<Fields> recipe() {
    const uint32_t inst[]={0xf20080d3,0xf2008153,0xf00081d3,0xf0008253,0xf20082d3,0xf2008353,0xf00083d3,0x02208053,0xe2000653,0x0041f453,0x004184d3,0x0262f553,0xa033a6d3,0xe2029753,0xe00407d3,0xe2050853};
    const uint64_t data[]={0x3ff8000000000000ULL,0x4002000000000000ULL,0x3f800000,0x33800000,0x3ff0000000000000ULL,0x3ca0000000000000ULL,0x7f800001};
    std::vector<Fields> ops;
    for(unsigned n=0;n<16;++n) {
        Fields x=defaults(); x["start_valid"]=1; x["start_bits_instruction"]=inst[n];
        x["start_bits_operand"]=n<7?data[n]:0; x["start_bits_pc"]=0x80000000ULL+4*n;
        x["start_bits_token_index"]=n==15?1:n%14+1;
        x["start_bits_token_tag"]=n==15?(0x145600000000000fULL^(1ULL<<63)):0x1456000000000001ULL+n;
        x["translationActive"]=n<9; ops.push_back(x);
    } return ops;
}
static void grant(Fields& x,unsigned lane,const Fields& op) {
    const auto k="commit"+std::to_string(lane)+"_";
    x[k+"valid"]=1; x[k+"bits_index"]=get(op,"start_bits_token_index"); x[k+"bits_tag"]=get(op,"start_bits_token_tag");
}
// Misc complete latency is four cycles from start; shared add latency is five.
// These source-audited bounds are not calibrated from simulation observations.
static unsigned latency(unsigned op) { return op==7 || op==9 || op==10 || op==11?5:4; }
static std::vector<Row> run(SGuardedFpBridgeGsim& dut,const std::string& name) {
    std::vector<Row> rows; bool guest=false;
    auto blank=[&]() { Fields x=defaults(); x["translationActive"]=!guest; return x; };
    auto add=[&](const std::string& phase,const Fields& x) {
        check(rows.size()<2048,"cycle_bound"); drive(dut,x); dut.step(); Fields pre=observe(dut);
        if(!rows.empty()) rows.back().post=architecture(pre);
        rows.push_back({phase,x,pre,{}});
    };
    auto idle=[&](const std::string& phase) { add(phase,blank()); };
    auto status=[&](const std::string& phase,unsigned address,uint64_t value) { auto x=blank(); x["status_valid"]=1; x["status_bits_address"]=address; x["status_bits_data"]=value; add(phase,x); };
    auto csr=[&](const std::string& phase,bool write) { auto x=blank(); x["csr_valid"]=1; x["csr_bits_write"]=write; x["csr_bits_value"]=96; add(phase,x); };
    for(unsigned lane=0;lane<2;++lane) { auto x=blank(); x["commit"+std::to_string(lane)+"_valid"]=1; add("cold_lane"+std::to_string(lane),x); }
    status("setup_host",0x300,2<<13); status("setup_guest",0x200,2<<13);
    csr("host_csr_write",true); csr("host_csr_read",false);
    const auto ops=recipe();
    for(unsigned n=0;n<ops.size();++n) {
        if(n==7 || n==9 || n==12 || n==13) {
            status("op"+std::to_string(n)+"_host_clean",0x300,2<<13);
            status("op"+std::to_string(n)+"_vs_clean",0x200,2<<13);
        }
        if(n==9) {
            status("guest_spv",0x600,128); auto x=blank(); x["sret"]=1; add("guest_enter",x); guest=true;
            csr("guest_csr_write",true); csr("guest_csr_read",false);
            status("guest_csr_host_clean",0x300,2<<13); status("guest_csr_vs_clean",0x200,2<<13);
        }
        const auto p="op"+std::to_string(n)+"_";
        auto x=ops[n]; if(n==8) grant(x,1,ops[7]); add(p+"issue",x);
        for(unsigned j=0;j<latency(n);++j) idle(p+"wait_"+std::to_string(j));
        const unsigned readyHold=name=="baseline"?1:4,retireHold=name=="baseline"?2:5;
        for(unsigned j=0;j<readyHold;++j) idle(p+"complete_hold_"+std::to_string(j));
        x=blank(); x["complete_ready"]=1; add(p+"accept",x);
        for(unsigned j=0;j<retireHold;++j) add(p+"retire_hold_"+std::to_string(j),x);
        x=blank(); grant(x,0,ops[n]); x["commit0_bits_tag"]^=1ULL<<63; add(p+"wrong_tag",x);
        x=blank(); grant(x,1,ops[n]); x["commit1_bits_index"]^=1; add(p+"wrong_index",x);
        x=blank(); grant(x,0,ops[n]); x["commit0_valid"]=0; add(p+"invalid",x);
        x=n==7?ops[8]:blank(); grant(x,n%2,ops[n]); add(p+"retire",x);
        if(n!=7) for(unsigned lane=0;lane<2;++lane) { x=blank(); grant(x,lane,ops[n]); add(p+"repeat"+std::to_string(lane),x); }
    }
    idle("final_idle_0"); idle("final_idle_1");
    drive(dut,blank()); dut.step(); rows.back().post=architecture(observe(dut)); return rows;
}
struct Answer { uint64_t value; unsigned flags, destination; bool writesFp,writesFlags; };
// Small independently audited IEEE corpus, not a floating-point implementation.
// Golden operands come exclusively from the software retirement ledger.
static Answer answer(uint32_t inst,uint64_t integer,const std::array<uint64_t,32>& regs,unsigned frm) {
    unsigned fn=inst>>25,a=(inst>>15)&31,b=(inst>>20)&31,rd=(inst>>7)&31,rm=(inst>>12)&7;
    if(fn==0x78 || fn==0x79) return {fn==0x78?0xffffffff00000000ULL|uint32_t(integer):integer,0,rd,true,false};
    if(fn==0x70 || fn==0x71) {
        if(rm==1) { check(fn==0x71 && regs[a]==0x3ff0000000000000ULL,"class_operands"); return {64,0,rd,false,false}; }
        check(rm==0,"move_encoding");
        return {fn==0x70?uint64_t(int64_t(int32_t(regs[a]))):regs[a],0,rd,false,false};
    }
    if(fn==0x50) {
        check(rm==2 && regs[a]==0xffffffff7f800001ULL && regs[b]==0xffffffff3f800000ULL,"compare_operands");
        return {0,16,rd,false,true};
    }
    check(fn==0 || fn==1,"arithmetic_encoding"); const unsigned rounding=rm==7?frm:rm;
    if(fn==1 && regs[a]==0x3ff8000000000000ULL && regs[b]==0x4002000000000000ULL)
        return {0x400e000000000000ULL,0,rd,true,true};
    if(fn==1) {
        check(regs[a]==0x3ff0000000000000ULL && regs[b]==0x3ca0000000000000ULL && rounding==3,"double_round_operands");
        return {0x3ff0000000000001ULL,1,rd,true,true};
    }
    check(regs[a]==0xffffffff3f800000ULL && regs[b]==0xffffffff33800000ULL && (rounding==0 || rounding==3),"single_round_operands");
    return {0xffffffff3f800000ULL+(rounding==3),1,rd,true,true};
}
static Fields verify(const std::vector<Row>& rows,const std::string& negative) {
    std::array<uint64_t,32> regs{}; unsigned host=0,guest=0,frm=0,flags=0,spv=0;
    bool v=false,active=false,pending=false,seen=false,pendingGuest=false,negativeHit=false;
    uint64_t index=0,tag=0,pc=0; unsigned startCycle=0,op=0; Answer expected{};
    Fields metrics={{"schema",1},{"component_only",1},{"guest_fd_cpu_execution",0},{"real_fp_arithmetic",1},
        {"issued",0},{"completion_accepts",0},{"fp_retire_accepted",0},{"fpr_writes",0},{"fflags_updates",0},
        {"fp_architectural_mutations",0},{"host_dirty_events",0},{"guest_dirty_events",0},{"csr_mutations",0},
        {"owner_retired_pulses",0},{"inactive_owner_pulses",0},{"successful_active_owner_retirements",0}};
    for(unsigned cycle=0;cycle<rows.size();++cycle) {
        const auto& row=rows[cycle]; diagnosticContext=" cycle="+std::to_string(cycle)+" phase="+row.phase;
        const auto& x=row.in; auto o=row.pre,post=row.post;
        auto mutate=[&](const char* mode,const char* phase,Fields& target,const char* field,uint64_t val) {
            if(negative==mode && row.phase==phase) { target[field]=val; negativeHit=true; }
        };
        mutate("numerical_value","op7_complete_hold_0",o,"complete_bits_data",0x400e000000000001ULL);
        mutate("boxed_single","op9_retire",post,"fpr_8",0x3f800001);
        mutate("rounding_selection","op10_complete_hold_0",o,"complete_bits_data",0xffffffff3f800001ULL);
        mutate("premature_mutation","op7_wait_0",o,"mutation_valid",1);
        mutate("fflags_accumulation","op12_retire",post,"fcsr",96);
        mutate("guest_dirty","op9_retire",post,"guestFs",2);
        mutate("duplicate_completion","op0_retire_hold_0",o,"complete_valid",1);
        mutate("refill_credit","op7_retire",o,"start_ready",1);
        const unsigned age=cycle-startCycle;
        const unsigned state=!pending?0:age==1?1:age<latency(op)?2:3;
        const bool done=state==3,complete=done && !seen;
        const bool status=get(x,"status_valid"),csr=get(x,"csr_valid");
        const bool ready=!pending && !status && !csr,start=ready && get(x,"start_valid");
        unsigned matches=0;
        for(unsigned lane=0;lane<2;++lane) { const auto k="commit"+std::to_string(lane)+"_";
            if(get(x,k+"valid") && get(x,k+"bits_index")==index && get(x,k+"bits_tag")==tag) matches|=1U<<lane; }
        const bool raw=matches!=0,retire=done && raw,accepted=complete && get(x,"complete_ready");
        const unsigned ca=get(x,"csr_bits_address");
        const bool illegal=!host || (v && !guest) || ca<1 || ca>3 || get(x,"csr_bits_operation")==3;
        const unsigned cr=ca==1?flags:ca==2?frm:ca==3?(frm<<5)|flags:0;
        const bool cm=csr && !pending && !status && get(x,"csr_bits_write") && !illegal;
        const bool mutation=cm || (retire && (expected.writesFp || expected.writesFlags));
        const bool mutationGuest=cm?v:pendingGuest;
        auto eq=[&](const std::string& field,uint64_t value,const std::string& name) { check(get(o,field)==value,name); };
        eq("statePhase",state,"state_phase"); eq("busy",pending,"state_phase");
        eq("ownerActive",active,"owner_lifetime"); eq("ownerToken_index",index,"full_token"); eq("ownerToken_tag",tag,"full_token");
        eq("completionSeen",seen,"completion_once"); eq("complete_valid",complete,"duplicate_completion"); eq("completionAccepted",accepted,"completion_once");
        eq("start_ready",ready,"refill_credit"); eq("issueAccepted",start,"start_accepted");
        eq("retired",raw,"raw_match"); eq("retireMatches",matches,"raw_match"); eq("retireAccepted",retire,"retire_accepted");
        eq("mutation_valid",mutation,"premature_mutation"); if(mutation) eq("mutation_bits_guest",mutationGuest,"mutation_owner");
        eq("fcsr",(frm<<5)|flags,"fflags_accumulation"); eq("hostFs",host,"host_dirty"); eq("guestFs",guest,"guest_dirty");
        eq("hostSd",host==3,"host_sd"); eq("guestSd",guest==3,"guest_sd"); eq("virtualized",v,"virtualized");
        eq("csr_ready",!pending && !status,"csr_ready"); eq("csrRead",cr,"csr_read"); eq("csrIllegal",illegal,"csr_illegal"); eq("status_ready",!pending,"status_ready");
        eq("contextMemoryEpoch",0,"memory_epoch"); eq("hMemoryEpoch",0,"memory_epoch"); eq("fpMemoryEpoch",0,"memory_epoch");
        eq("statusShadow",get(x,"statusReadAddress")==0x100 && v,"status_shadow");
        const unsigned readFs=(get(x,"statusReadAddress")==0x200 || (get(x,"statusReadAddress")==0x100 && v))?guest:host;
        check((get(o,"statusReadData")&((3ULL<<13)|(1ULL<<63)))==((uint64_t(readFs)<<13)|(readFs==3?1ULL<<63:0)),"status_read");
        for(unsigned n=0;n<32;++n) eq("fpr_"+std::to_string(n),regs[n],"premature_fpr");
        if(done) {
            eq("complete_bits_data",expected.value,op==10?"rounding_selection":"numerical_value");
            eq("complete_bits_token_index",index,"complete_token"); eq("complete_bits_token_tag",tag,"complete_token"); eq("complete_bits_nextPc",pc+4,"complete_pc");
            for(const auto* field:{"exception","cause","tval","guestFault_guestPageFault","guestFault_guestAddress","guestFault_guestPhysicalAddress","guestFault_implicitPte"}) eq(std::string("complete_bits_")+field,0,"successful_completion");
        }
        check(!(pending && (status || csr || get(x,"sret") || get(x,"mret"))),"idle_context");
        check(!get(x,"mret"),"no_m_origin");
        if(raw) { ++metrics["owner_retired_pulses"]; ++metrics[active?"successful_active_owner_retirements":"inactive_owner_pulses"]; active=false; }
        if(accepted) { seen=true; ++metrics["completion_accepts"]; }
        if(status) {
            const auto address=get(x,"status_bits_address"),data=get(x,"status_bits_data");
            if(address==0x300 || (address==0x100 && !v)) host=(data>>13)&3;
            if(address==0x200 || (address==0x100 && v)) guest=(data>>13)&3;
            if(address==0x600) spv=(data>>7)&1;
        }
        if(cm) {
            const auto value=get(x,"csr_bits_value"),operation=get(x,"csr_bits_operation");
            const auto written=operation==0?value:operation==1?cr|value:cr&~value;
            if(ca==1 || ca==3) flags=written&31;
            if(ca==2) frm=written&7;
            if(ca==3) frm=(written>>5)&7;
            ++metrics["csr_mutations"];
        }
        if(mutation) { host=3; if(mutationGuest) guest=3; }
        if(retire) {
            check(seen,"retire_before_completion_accept"); pending=false;
            if(expected.writesFp) { regs[expected.destination]=expected.value; ++metrics["fpr_writes"]; }
            if(expected.writesFlags) { flags|=expected.flags; ++metrics["fflags_updates"]; }
            if(mutation) { ++metrics["fp_architectural_mutations"]; ++metrics["host_dirty_events"]; if(pendingGuest) ++metrics["guest_dirty_events"]; }
            ++metrics["fp_retire_accepted"];
        }
        if(start) {
            check(host && (!v || guest),"legal_issue"); op=metrics["issued"];
            expected=answer(get(x,"start_bits_instruction"),get(x,"start_bits_operand"),regs,frm);
            pending=true; pendingGuest=v; active=true; seen=false; startCycle=cycle;
            index=get(x,"start_bits_token_index"); tag=get(x,"start_bits_token_tag"); pc=get(x,"start_bits_pc"); ++metrics["issued"];
        }
        if(get(x,"sret") && !v) { v=spv; spv=0; }
        const unsigned nextAge=cycle+1-startCycle;
        const unsigned nextState=!pending?0:nextAge==1?1:nextAge<latency(op)?2:3;
        check(get(post,"statePhase")==nextState && get(post,"busy")==pending,"post_state");
        check(get(post,"completionSeen")==seen,"post_completion_once");
        check(get(post,"ownerActive")==active && get(post,"ownerToken_index")==index && get(post,"ownerToken_tag")==tag,"post_owner");
        check(get(post,"fcsr")==((frm<<5)|flags),"fflags_accumulation");
        check(get(post,"hostFs")==host,"host_dirty"); check(get(post,"guestFs")==guest,"guest_dirty");
        check(get(post,"hostSd")==unsigned(host==3) && get(post,"guestSd")==unsigned(guest==3),"post_sd"); check(get(post,"virtualized")==v,"post_v");
        for(unsigned n=0;n<32;++n) check(get(post,"fpr_"+std::to_string(n))==regs[n],n==8?"boxed_single":"fpr_retirement");
    }
    check(negative.empty() || negativeHit,"negative_target_missing");
    check(!pending && !active && metrics["issued"]==16 && metrics["completion_accepts"]==16 && metrics["fp_retire_accepted"]==16 && metrics["fpr_writes"]==11 && metrics["fflags_updates"]==5 && metrics["fp_architectural_mutations"]==12 && metrics["guest_dirty_events"]==4 && metrics["csr_mutations"]==2 && flags==17 && frm==3,"coverage");
    metrics["cycles"]=rows.size(); return metrics;
}
int main(int argc,char** argv) {
    try {
        std::string name="baseline",trace,negative;
        for(int n=1;n<argc;++n) { const std::string a=argv[n]; check(n+1<argc,"arguments");
            if(a=="--schedule") name=argv[++n]; else if(a=="--trace") trace=argv[++n]; else if(a=="--negative") negative=argv[++n]; else check(false,"arguments"); }
        check((name=="baseline" || name=="staggered") && !trace.empty(),"arguments");
        const std::vector<std::string> negatives={"numerical_value","boxed_single","rounding_selection","premature_mutation","fflags_accumulation","guest_dirty","duplicate_completion","refill_credit"};
        bool known=negative.empty(); for(const auto& n:negatives) known|=negative==n; check(known,"arguments");
        SGuardedFpBridgeGsim dut; drive(dut,defaults()); dut.set_reset(1); dut.step(); dut.step(); dut.set_reset(0);
        const auto rows=run(dut,name);
        std::ofstream out(trace); check(bool(out),"trace_open");
        out << "{\"type\":\"header\",\"schema\":1,\"component_only\":true,\"guest_fd_cpu_execution\":false,\"real_fp_arithmetic\":true,\"cycle_limit\":2048,\"schedule\":\"" << name << "\",\"ready_hold\":" << (name=="baseline"?1:4) << ",\"retire_hold\":" << (name=="baseline"?2:5) << ",\"recipe\":[";
        const auto ops=recipe(); for(unsigned n=0;n<ops.size();++n) { if(n) out << ','; json(out,ops[n]); } out << "]}\n";
        for(unsigned n=0;n<rows.size();++n) { out << "{\"type\":\"cycle\",\"cycle\":" << n << ",\"phase\":\"" << rows[n].phase << "\",\"in\":"; json(out,rows[n].in); out << ",\"pre\":"; json(out,rows[n].pre); out << ",\"post\":"; json(out,rows[n].post); out << "}\n"; }
        out << "{\"type\":\"footer\",\"cycles\":" << rows.size() << ",\"complete\":true}\n";
        check(out.tellp()<=4194304,"trace_bound"); out.close(); check(bool(out),"trace_write");
        const auto metrics=verify(rows,negative); std::cout << "GUARDED_FP_BRIDGE_SUMMARY "; json(std::cout,metrics); std::cout << '\n'; return 0;
    } catch(const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
