#include "GuardedFpFaultRecoveryGsim.h"
#include <array>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <functional>
#include <stdexcept>
#include <string>
#include <vector>
using Fields = std::map<std::string, uint64_t>;
static uint64_t get(const Fields& x, const std::string& k) { return x.at(k); }
static void json(std::ostream& o, const Fields& x) { o << '{'; bool first=true; for (auto& [k,v]:x) { if (!first) o << ','; first=false; o << '\"' << k << "\":" << v; } o << '}'; }
static std::string diagnosticContext;
static void check(bool ok, const std::string& name) { if (!ok) throw std::runtime_error("GUARDED_FP_FAULT_CHECK["+name+"]"+diagnosticContext); }
struct Row { std::string phase; Fields in, pre, post; };
static Fields defaults() { return Fields{
    {"start_valid",0ULL},
    {"start_bits_token_index",0ULL},
    {"start_bits_token_tag",0ULL},
    {"start_bits_pc",0ULL},
    {"start_bits_instruction",0ULL},
    {"start_bits_operand",0ULL},
    {"start_bits_operand2",0ULL},
    {"complete_ready",0ULL},
    {"csr_valid",0ULL},
    {"csr_bits_address",3ULL},
    {"csr_bits_operation",0ULL},
    {"csr_bits_write",0ULL},
    {"csr_bits_value",0ULL},
    {"status_valid",0ULL},
    {"status_bits_address",0ULL},
    {"status_bits_data",0ULL},
    {"statusReadAddress",256ULL},
    {"mret",0ULL},
    {"sret",0ULL},
    {"commit0_valid",0ULL},
    {"commit0_bits_index",0ULL},
    {"commit0_bits_tag",0ULL},
    {"commit1_valid",0ULL},
    {"commit1_bits_index",0ULL},
    {"commit1_bits_tag",0ULL},
    {"context_virtualAddress",0ULL},
    {"context_vsatp",0ULL},
    {"context_hgatp",0ULL},
    {"context_virtualized",0ULL},
    {"context_effectivePrivilege",1ULL},
    {"context_access",0ULL},
    {"context_size",3ULL},
    {"context_vsSum",0ULL},
    {"context_vsMxr",0ULL},
    {"context_hsMxr",0ULL},
    {"context_forceExecute",0ULL},
    {"context_epoch",81ULL},
    {"hostSatp",0ULL},
    {"pmpTop",18014398509481983ULL},
    {"pmpPermission",7ULL},
    {"pmaDenied",0ULL},
    {"trap_valid",0ULL},
    {"trap_bits_pc",0ULL},
    {"trap_bits_cause",0ULL},
    {"trap_bits_tval",0ULL},
    {"trap_bits_guestAddress",0ULL},
    {"trap_bits_guestPhysicalAddress",0ULL},
    {"trap_bits_implicitPte",0ULL},
    {"physical_request_ready",0ULL},
    {"physical_response_valid",0ULL},
    {"physical_response_bits_data",0ULL},
    {"physical_response_bits_error",0ULL},
    {"physical_response_bits_pageFault",0ULL},
    {"pte_request_ready",0ULL},
    {"pte_response_valid",0ULL},
    {"pte_response_bits_data",0ULL},
    {"pte_response_bits_error",0ULL},
}; }
static void drive(SGuardedFpFaultRecoveryGsim& d,const Fields& x) {
    d.set_io$$start$$valid(get(x,"start_valid"));
    d.set_io$$start$$bits$$token$$index(get(x,"start_bits_token_index"));
    d.set_io$$start$$bits$$token$$tag(get(x,"start_bits_token_tag"));
    d.set_io$$start$$bits$$pc(get(x,"start_bits_pc"));
    d.set_io$$start$$bits$$instruction(get(x,"start_bits_instruction"));
    d.set_io$$start$$bits$$operand(get(x,"start_bits_operand"));
    d.set_io$$start$$bits$$operand2(get(x,"start_bits_operand2"));
    d.set_io$$complete$$ready(get(x,"complete_ready"));
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
    d.set_io$$context$$virtualAddress(get(x,"context_virtualAddress"));
    d.set_io$$context$$vsatp(get(x,"context_vsatp"));
    d.set_io$$context$$hgatp(get(x,"context_hgatp"));
    d.set_io$$context$$virtualized(get(x,"context_virtualized"));
    d.set_io$$context$$effectivePrivilege(get(x,"context_effectivePrivilege"));
    d.set_io$$context$$access(get(x,"context_access"));
    d.set_io$$context$$size(get(x,"context_size"));
    d.set_io$$context$$vsSum(get(x,"context_vsSum"));
    d.set_io$$context$$vsMxr(get(x,"context_vsMxr"));
    d.set_io$$context$$hsMxr(get(x,"context_hsMxr"));
    d.set_io$$context$$forceExecute(get(x,"context_forceExecute"));
    d.set_io$$context$$epoch(get(x,"context_epoch"));
    d.set_io$$hostSatp(get(x,"hostSatp"));
    d.set_io$$pmpTop(get(x,"pmpTop"));
    d.set_io$$pmpPermission(get(x,"pmpPermission"));
    d.set_io$$pmaDenied(get(x,"pmaDenied"));
    d.set_io$$trap$$valid(get(x,"trap_valid"));
    d.set_io$$trap$$bits$$pc(get(x,"trap_bits_pc"));
    d.set_io$$trap$$bits$$cause(get(x,"trap_bits_cause"));
    d.set_io$$trap$$bits$$tval(get(x,"trap_bits_tval"));
    d.set_io$$trap$$bits$$guestAddress(get(x,"trap_bits_guestAddress"));
    d.set_io$$trap$$bits$$guestPhysicalAddress(get(x,"trap_bits_guestPhysicalAddress"));
    d.set_io$$trap$$bits$$implicitPte(get(x,"trap_bits_implicitPte"));
    d.set_io$$physical$$request$$ready(get(x,"physical_request_ready"));
    d.set_io$$physical$$response$$valid(get(x,"physical_response_valid"));
    d.set_io$$physical$$response$$bits$$data(get(x,"physical_response_bits_data"));
    d.set_io$$physical$$response$$bits$$error(get(x,"physical_response_bits_error"));
    d.set_io$$physical$$response$$bits$$pageFault(get(x,"physical_response_bits_pageFault"));
    d.set_io$$pte$$request$$ready(get(x,"pte_request_ready"));
    d.set_io$$pte$$response$$valid(get(x,"pte_response_valid"));
    d.set_io$$pte$$response$$bits$$data(get(x,"pte_response_bits_data"));
    d.set_io$$pte$$response$$bits$$error(get(x,"pte_response_bits_error"));
}
static Fields observe(SGuardedFpFaultRecoveryGsim& d) { return Fields{
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
    {"translationActive",uint64_t(d.get_io$$translationActive())},
    {"selectorDomain",uint64_t(d.get_io$$selectorDomain())},
    {"selectorBusy",uint64_t(d.get_io$$selectorBusy())},
    {"memoryDrained",uint64_t(d.get_io$$memoryDrained())},
    {"contextReplaceAllowed",uint64_t(d.get_io$$contextReplaceAllowed())},
    {"executeValid",uint64_t(d.get_io$$executeValid())},
    {"executeFire",uint64_t(d.get_io$$executeFire())},
    {"stateCompleteValid",uint64_t(d.get_io$$stateCompleteValid())},
    {"memoryBusy",uint64_t(d.get_io$$memoryBusy())},
    {"adapterIdle",uint64_t(d.get_io$$adapterIdle())},
    {"translatorIdle",uint64_t(d.get_io$$translatorIdle())},
    {"responseBufferIdle",uint64_t(d.get_io$$responseBufferIdle())},
    {"completionCount",uint64_t(d.get_io$$completionCount())},
    {"adapterFire",uint64_t(d.get_io$$adapterFire())},
    {"adapterResponseFire",uint64_t(d.get_io$$adapterResponseFire())},
    {"bufferedResponseFire",uint64_t(d.get_io$$bufferedResponseFire())},
    {"responseEpoch",uint64_t(d.get_io$$responseEpoch())},
    {"hstatus",uint64_t(d.get_io$$hstatus())},
    {"htval",uint64_t(d.get_io$$htval())},
    {"physical_request_valid",uint64_t(d.get_io$$physical$$request$$valid())},
    {"physical_response_ready",uint64_t(d.get_io$$physical$$response$$ready())},
    {"pte_request_valid",uint64_t(d.get_io$$pte$$request$$valid())},
    {"pte_request_bits",uint64_t(d.get_io$$pte$$request$$bits())},
    {"pte_response_ready",uint64_t(d.get_io$$pte$$response$$ready())},
    {"physicalCheck_valid",uint64_t(d.get_io$$physicalCheck$$valid())},
    {"virtualRequest_valid",uint64_t(d.get_io$$virtualRequest$$valid())},
    {"adapterResponse_valid",uint64_t(d.get_io$$adapterResponse$$valid())},
    {"bufferedResponse_valid",uint64_t(d.get_io$$bufferedResponse$$valid())},
    {"pipelineComplete_valid",uint64_t(d.get_io$$pipelineComplete$$valid())},
    {"convertedResult_valid",uint64_t(d.get_io$$convertedResult$$valid())},
    {"physical_request_bits_address",uint64_t(d.get_io$$physical$$request$$bits$$address())},
    {"physical_request_bits_data",uint64_t(d.get_io$$physical$$request$$bits$$data())},
    {"physical_request_bits_mask",uint64_t(d.get_io$$physical$$request$$bits$$mask())},
    {"physical_request_bits_size",uint64_t(d.get_io$$physical$$request$$bits$$size())},
    {"physical_request_bits_write",uint64_t(d.get_io$$physical$$request$$bits$$write())},
    {"physical_request_bits_atomic",uint64_t(d.get_io$$physical$$request$$bits$$atomic())},
    {"physical_request_bits_atomicOp",uint64_t(d.get_io$$physical$$request$$bits$$atomicOp())},
    {"physical_request_bits_uncached",uint64_t(d.get_io$$physical$$request$$bits$$uncached())},
    {"physical_request_bits_virtualized",uint64_t(d.get_io$$physical$$request$$bits$$virtualized())},
    {"physical_request_bits_precheckedLoad",uint64_t(d.get_io$$physical$$request$$bits$$precheckedLoad())},
    {"physical_request_bits_translationEpoch",uint64_t(d.get_io$$physical$$request$$bits$$translationEpoch())},
    {"physical_request_bits_prefetchNextAllowed",uint64_t(d.get_io$$physical$$request$$bits$$prefetchNextAllowed())},
    {"virtualRequest_bits_address",uint64_t(d.get_io$$virtualRequest$$bits$$address())},
    {"virtualRequest_bits_data",uint64_t(d.get_io$$virtualRequest$$bits$$data())},
    {"virtualRequest_bits_mask",uint64_t(d.get_io$$virtualRequest$$bits$$mask())},
    {"virtualRequest_bits_size",uint64_t(d.get_io$$virtualRequest$$bits$$size())},
    {"virtualRequest_bits_write",uint64_t(d.get_io$$virtualRequest$$bits$$write())},
    {"virtualRequest_bits_atomic",uint64_t(d.get_io$$virtualRequest$$bits$$atomic())},
    {"virtualRequest_bits_atomicOp",uint64_t(d.get_io$$virtualRequest$$bits$$atomicOp())},
    {"virtualRequest_bits_uncached",uint64_t(d.get_io$$virtualRequest$$bits$$uncached())},
    {"virtualRequest_bits_virtualized",uint64_t(d.get_io$$virtualRequest$$bits$$virtualized())},
    {"virtualRequest_bits_precheckedLoad",uint64_t(d.get_io$$virtualRequest$$bits$$precheckedLoad())},
    {"virtualRequest_bits_translationEpoch",uint64_t(d.get_io$$virtualRequest$$bits$$translationEpoch())},
    {"virtualRequest_bits_prefetchNextAllowed",uint64_t(d.get_io$$virtualRequest$$bits$$prefetchNextAllowed())},
    {"adapterResponse_bits_data",uint64_t(d.get_io$$adapterResponse$$bits$$data())},
    {"adapterResponse_bits_error",uint64_t(d.get_io$$adapterResponse$$bits$$error())},
    {"adapterResponse_bits_pageFault",uint64_t(d.get_io$$adapterResponse$$bits$$pageFault())},
    {"bufferedResponse_bits_data",uint64_t(d.get_io$$bufferedResponse$$bits$$data())},
    {"bufferedResponse_bits_error",uint64_t(d.get_io$$bufferedResponse$$bits$$error())},
    {"bufferedResponse_bits_pageFault",uint64_t(d.get_io$$bufferedResponse$$bits$$pageFault())},
    {"adapterFault_guestPageFault",uint64_t(d.get_io$$adapterFault$$guestPageFault())},
    {"adapterFault_guestAddress",uint64_t(d.get_io$$adapterFault$$guestAddress())},
    {"adapterFault_guestPhysicalAddress",uint64_t(d.get_io$$adapterFault$$guestPhysicalAddress())},
    {"adapterFault_implicitPte",uint64_t(d.get_io$$adapterFault$$implicitPte())},
    {"bufferedFault_guestPageFault",uint64_t(d.get_io$$bufferedFault$$guestPageFault())},
    {"bufferedFault_guestAddress",uint64_t(d.get_io$$bufferedFault$$guestAddress())},
    {"bufferedFault_guestPhysicalAddress",uint64_t(d.get_io$$bufferedFault$$guestPhysicalAddress())},
    {"bufferedFault_implicitPte",uint64_t(d.get_io$$bufferedFault$$implicitPte())},
    {"physicalCheck_bits_address",uint64_t(d.get_io$$physicalCheck$$bits$$address())},
    {"physicalCheck_bits_size",uint64_t(d.get_io$$physicalCheck$$bits$$size())},
    {"physicalCheck_bits_access",uint64_t(d.get_io$$physicalCheck$$bits$$access())},
    {"physicalCheck_bits_atomic",uint64_t(d.get_io$$physicalCheck$$bits$$atomic())},
    {"physicalCheck_bits_forceExecute",uint64_t(d.get_io$$physicalCheck$$bits$$forceExecute())},
    {"pipelineComplete_bits_token_index",uint64_t(d.get_io$$pipelineComplete$$bits$$token$$index())},
    {"pipelineComplete_bits_token_tag",uint64_t(d.get_io$$pipelineComplete$$bits$$token$$tag())},
    {"pipelineComplete_bits_data",uint64_t(d.get_io$$pipelineComplete$$bits$$data())},
    {"pipelineComplete_bits_nextPc",uint64_t(d.get_io$$pipelineComplete$$bits$$nextPc())},
    {"pipelineComplete_bits_exception",uint64_t(d.get_io$$pipelineComplete$$bits$$exception())},
    {"pipelineComplete_bits_cause",uint64_t(d.get_io$$pipelineComplete$$bits$$cause())},
    {"pipelineComplete_bits_tval",uint64_t(d.get_io$$pipelineComplete$$bits$$tval())},
    {"pipelineComplete_bits_guestFault_guestPageFault",uint64_t(d.get_io$$pipelineComplete$$bits$$guestFault$$guestPageFault())},
    {"pipelineComplete_bits_guestFault_guestAddress",uint64_t(d.get_io$$pipelineComplete$$bits$$guestFault$$guestAddress())},
    {"pipelineComplete_bits_guestFault_guestPhysicalAddress",uint64_t(d.get_io$$pipelineComplete$$bits$$guestFault$$guestPhysicalAddress())},
    {"pipelineComplete_bits_guestFault_implicitPte",uint64_t(d.get_io$$pipelineComplete$$bits$$guestFault$$implicitPte())},
    {"convertedResult_bits_token_index",uint64_t(d.get_io$$convertedResult$$bits$$token$$index())},
    {"convertedResult_bits_token_tag",uint64_t(d.get_io$$convertedResult$$bits$$token$$tag())},
    {"convertedResult_bits_value",uint64_t(d.get_io$$convertedResult$$bits$$value())},
    {"convertedResult_bits_flags",uint64_t(d.get_io$$convertedResult$$bits$$flags())},
    {"convertedResult_bits_exception",uint64_t(d.get_io$$convertedResult$$bits$$exception())},
    {"convertedResult_bits_cause",uint64_t(d.get_io$$convertedResult$$bits$$cause())},
    {"convertedResult_bits_tval",uint64_t(d.get_io$$convertedResult$$bits$$tval())},
    {"convertedResult_bits_guestFault_guestPageFault",uint64_t(d.get_io$$convertedResult$$bits$$guestFault$$guestPageFault())},
    {"convertedResult_bits_guestFault_guestAddress",uint64_t(d.get_io$$convertedResult$$bits$$guestFault$$guestAddress())},
    {"convertedResult_bits_guestFault_guestPhysicalAddress",uint64_t(d.get_io$$convertedResult$$bits$$guestFault$$guestPhysicalAddress())},
    {"convertedResult_bits_guestFault_implicitPte",uint64_t(d.get_io$$convertedResult$$bits$$guestFault$$implicitPte())},
}; }
static Fields architecture(const Fields& x) { Fields a; for (auto& [k,v]:x) if (k.rfind("fpr_",0)==0 ||
    k=="fcsr" || k=="hostFs" || k=="guestFs" || k=="hostSd" || k=="guestSd" || k=="virtualized" ||
    k=="ownerActive" || k=="ownerToken_index" || k=="ownerToken_tag" || k=="statePhase" || k=="completionSeen" ||
    k=="busy" || k=="hstatus" || k=="htval") a[k]=v; return a; }
constexpr uint64_t mode=8ULL<<60, seed=0x7ff0123456789abcULL, loaded=0x400921fb54442d18ULL;
using Image=std::map<uint64_t,uint64_t>;
static uint64_t pte(uint64_t pa,uint64_t flags) {
    return ((pa>>12)<<10)|flags;
}
static Image tables() {
    Image t;
    auto g=[&](uint64_t a,uint64_t pa,unsigned level,uint64_t flags) {
        uint64_t table=0x200000;
        for(int l=2;l>=int(level);--l) {
            const auto at=table+((a>>(12+9*l))& (l==2?2047:511))*8;
            if(l==int(level)) {
                t[at]=pte(pa,flags);
                break;
            }
            const auto next=0x400000+((a>>30)&2047)*0x3000+(2-l)*0x1000;
            t[at]=pte(next,1);
            table=next;
        }
    };
    g(0x100000,0x40000000,2,1|2|16|64);
    g(0x80000000,0xc0000000,0,1|2|4|16|64|128);
    g(0x112345028,0x60005000,0,1|2|4|64|128);
    // U=0 denies the explicit G read.
    uint64_t table=0x100000;
    for(int l=2;l>=0;--l) {
        t[0x40000000+table+((0x12345000ULL>>(12+9*l))&511)*8]=pte(l?table+4096:0x80000000,l?1:1|2|4|64|128);
        table+=4096;
    }
    return t;
}
static Image bytesInitial() {
    Image b;
    for(auto base: {
        0xc0000000ULL,0xc0000080ULL
    }
    ) for(uint64_t at=base-8;at<base+16;++at) b[at]=0x91+at%23;
    for(unsigned i=0;i<8;++i) b[0xc0000000+i]=(loaded>>(8*i))&255;
    return b;
}
static void imageJson(std::ostream& o,const Image& x) {
    o<<'[';
    bool first=true;
    for(auto [a,v]:x) {
        if(!first)o<<',';
        first=false;
        o<<'['<<a<<','<<v<<']';
    }
    o<<']';
}
static uint64_t beat(const Image& b,uint64_t at) {
    uint64_t v=0;
    for(unsigned i=0;i<8;++i)v|=b.at((at&~7ULL)+i)<<(8*i);
    return v;
}
static std::vector<Fields> recipe() {
    std::vector<Fields> result;
    for(unsigned n=0;n<11;++n) {
        auto x=defaults();
        x["start_valid"]=1;
        x["start_bits_token_index"]=5;
        x["start_bits_token_tag"]=0x135700000000007bULL ^ (uint64_t(n+1)<<33) ^ (uint64_t(n&1)<<63);
        x["start_bits_pc"]=0x80200000+4*n;
        x["start_bits_instruction"]=n==0?0xf2008053:n==2?0x0000b027:n>=4 && n%2==0?0xe2008153:0x0000b087;
        x["start_bits_operand"]=n==0?seed:n==2?0x12345080:n==7?0x12345001:n==9?0x112345028:0x12345000;
        if(n) {
            x["context_virtualized"]=1;
            x["context_vsatp"]=n==9?0:mode|0x100;
            x["context_hgatp"]=mode|0x200;
        }
        result.push_back(x);
    }
    return result;
}
static void grant(Fields& x,unsigned lane,const Fields& op) {
    const auto k="commit"+std::to_string(lane)+"_";
    x[k+"valid"]=1;
    x[k+"bits_index"]=get(op,"start_bits_token_index");
    x[k+"bits_tag"]=get(op,"start_bits_token_tag");
}
struct Run {
    std::vector<Row> rows;
    Image bytes=bytesInitial();
};
// Only physical/PTE responders inspect offered addresses. They never drive a
// producer result, FPR, decoded command, guest-fault flag or trap decision.
static Run run(SGuardedFpFaultRecoveryGsim& d,const std::string& name) {
    Run out;
    const auto ptes=tables();
    const bool stagger=name=="staggered";
    Fields context=defaults();
    // One outstanding PTE response and one outstanding native-data response.
    bool pp=false,dp=false;
    unsigned pteHolds=0,physicalHolds=0;
    unsigned pd=0,dd=0;
    uint64_t pv=0,dv=0;
    auto blank=[&]() {
        auto x=defaults();
        for(auto [k,v]:context) if(k.rfind("context_",0)==0)x[k]=v;
        return x;
    };
    auto add=[&](const std::string& phase,Fields x) {
        const unsigned c=out.rows.size();
        check(c<2048,"cycle_bound");
        x["pte_request_ready"]=pteHolds>=(stagger?3U:1U);
        x["physical_request_ready"]=physicalHolds>=(stagger?3U:1U);
        x["pte_response_valid"]=pp && !pd;
        x["pte_response_bits_data"]=pv;
        x["physical_response_valid"]=dp && !dd;
        x["physical_response_bits_data"]=dv;
        drive(d,x);
        d.step();
        auto pre=observe(d);
        if(!out.rows.empty())out.rows.back().post=architecture(pre);
        out.rows.push_back( {
            phase,x,pre, {}
        }
        );
        if(pd)--pd;
        if(dd)--dd;
        if(get(x,"pte_response_valid") && get(pre,"pte_response_ready"))pp=false;
        if(get(x,"physical_response_valid") && get(pre,"physical_response_ready"))dp=false;
        if(get(pre,"pte_request_valid") && !get(x,"pte_request_ready"))++pteHolds;
        if(get(pre,"physical_request_valid") && !get(x,"physical_request_ready"))++physicalHolds;
        if(get(pre,"pte_request_valid") && get(x,"pte_request_ready")) {
            pteHolds=0;
            check(!pp,"responder_pte_credit");
            pv=ptes.at(get(pre,"pte_request_bits"));
            pp=true;
            pd=stagger?4:2;
        }
        if(get(pre,"physical_request_valid") && get(x,"physical_request_ready")) {
            physicalHolds=0;
            check(!dp,"responder_physical_credit");
            const auto at=get(pre,"physical_request_bits_address");
            dv=beat(out.bytes,at);
            dp=true;
            dd=stagger?4:2;
            if(get(pre,"physical_request_bits_write")) for(unsigned i=0;i<8;++i)                 if(get(pre,"physical_request_bits_mask")&(1U<<i)) out.bytes[(at&~7ULL)+i]=(get(pre,"physical_request_bits_data")>>(8*i))&255;
        }
        return pre;
    };
    auto idle=[&](const std::string& phase) {
        return add(phase,blank());
    };
    auto status=[&](const std::string& phase,uint64_t addr,uint64_t value) {
        auto x=blank();
        x["status_valid"]=1;
        x["status_bits_address"]=addr;
        x["status_bits_data"]=value;
        add(phase,x);
    };
    status("setup_host",0x300,2<<13);
    status("setup_guest",0x200,2<<13);
    auto x=blank();
    x["csr_valid"]=1;
    x["csr_bits_write"]=1;
    x["csr_bits_value"]=0x75;
    add("setup_fcsr",x);
    const auto ops=recipe();
    for(unsigned n=0;n<11;++n) {
        const auto p="op"+std::to_string(n)+"_";
        // The entire previous FP lifecycle, including exceptional flush, is idle
        // before either translation image or architectural guest image changes.
        context=ops[n];
        idle(p+"context");
        status(p+"host_fs",0x300,(n==3?0:2)<<13);
        status(p+"guest_fs",0x200,(n==5?0:2)<<13);
        if(n==1 || (n>=4 && n%2==0)) {
            status(p+"spv",0x600,128);
            x=blank();
            x["sret"]=1;
            add(p+"guest_enter",x);
        }
        add(p+"issue",ops[n]);
        bool complete=false;
        for(unsigned j=0;j<320;++j) {
            auto o=idle(p+"wait_"+std::to_string(j));
            if(get(o,"complete_valid")) {
                complete=true;
                break;
            }
        }
        check(complete,"bounded_completion");
        for(unsigned j=0;j<(stagger?4U:1U);++j)idle(p+"complete_hold_"+std::to_string(j));
        x=blank();
        x["complete_ready"]=1;
        add(p+"accept",x);
        if(n==3 || n==5 || n==7 || n==9) {
            for(unsigned j=0;j<(stagger?6U:3U);++j) {
                x=blank();
                x["start_valid"]=1;
                x["start_bits_instruction"]=0xe2008153;
                add(p+"fault_pending_"+std::to_string(j),x);
            }
            x=blank();
            x["trap_valid"]=1;
            x["trap_bits_pc"]=get(ops[n],"start_bits_pc");
            x["trap_bits_cause"]=n<7?2:n==7?4:21;
            x["trap_bits_tval"]=n<7?0x0000b087:get(ops[n],"start_bits_operand");
            x["trap_bits_guestAddress"]=n>=7;
            x["trap_bits_guestPhysicalAddress"]=n==9?0x112345028:0;
            add(p+"trap",x);
            idle(p+"flushed");
            x=blank();
            grant(x,n%2,ops[n]);
            add(p+"inactive_token",x);
            idle(p+"idle");
        }
        else {
            for(unsigned j=0;j<(stagger?5U:2U);++j) {
                x=blank();
                x["complete_ready"]=1;
                add(p+"retire_hold_"+std::to_string(j),x);
            }
            x=blank();
            grant(x,0,ops[n]);
            x["commit0_bits_tag"]^=1ULL<<63;
            add(p+"wrong_tag",x);
            x=blank();
            grant(x,n%2,ops[n]);
            add(p+"retire",x);
            x=blank();
            grant(x,n%2,ops[n]);
            add(p+"inactive_token",x);
            idle(p+"idle");
        }
    }
    idle("final_idle");
    auto last=blank();
    drive(d,last);
    d.step();
    out.rows.back().post=architecture(observe(d));
    check(!pp && !dp,"responder_drain");
    return out;
}
struct Expected {
    uint64_t data=0,cause=0,tval=0,gpa=0,pa=0,va=0,storeData=0;
    unsigned rd=0;
    bool fault=false,guestAddress=false,guestPage=false,memory=false,store=false,writeFp=false,denied=false;
    std::vector<uint64_t> reads;
};
// Independent uncached Sv39/Sv39x4 walk over the input image. Never use a DUT
// address/result to choose the expected next address or exception.
static uint64_t walkG(uint64_t a,const Image& t,std::vector<uint64_t>& reads,bool store,bool& denied) {
    uint64_t table=0x200000;
    for(int level=2;level>=0;--level) {
        const auto at=table+((a>>(12+9*level))&(level==2?2047:511))*8;
        reads.push_back(at);
        const auto p=t.at(at),ppn=p>>10;
        check((p&1) && !((p&4) && !(p&2)),"pte_image");
        if(p&10) {
            if(!(p&16) || !(p&64) || !(p&(store?4:2)) || (store && !(p&128))) {
                denied=true;
                return 0;
            }
            const uint64_t low=(1ULL<<(12+9*level))-1;
            check(((ppn<<12)&low)==0,"pte_image");
            return (ppn<<12)|(a&low);
        }
        table=ppn<<12;
    }
    check(false,"pte_image");
    return 0;
}
static Expected answer(const Fields& in,const std::array<uint64_t,32>& fpr,unsigned host,unsigned guest,bool v) {
    Expected e;
    const auto inst=get(in,"start_bits_instruction");
    e.rd=(inst>>7)&31;
    const auto opcode=inst&127;
    e.memory=opcode==7 || opcode==0x27;
    e.store=opcode==0x27;
    if(!host || (v && !guest)) {
        e.fault=true;
        e.denied=true;
        e.cause=2;
        e.tval=inst;
        return e;
    }
    if(!e.memory) {
        if(inst==0xf2008053) {
            e.data=get(in,"start_bits_operand");
            e.writeFp=true;
        }
        else {
            check(inst==0xe2008153,"instruction_encoding");
            e.data=fpr[(inst>>15)&31];
        }
        return e;
    }
    check(((inst>>12)&7)==3,"instruction_encoding");
    const uint64_t raw=e.store?((inst>>25)<<5)|((inst>>7)&31):inst>>20;
    const int64_t offset=int64_t(raw&2047)-int64_t(raw&2048);
    e.va=get(in,"start_bits_operand")+uint64_t(offset);
    e.tval=e.va;
    e.guestAddress=get(in,"context_virtualized");
    e.storeData=fpr[(inst>>20)&31];
    e.cause=e.store?7:5;
    if(e.va&7) {
        e.fault=true;
        e.cause=e.store?6:4;
        return e;
    }
    check(e.guestAddress && get(in,"context_hgatp")== (mode|0x200),"translation_inputs");
    const auto t=tables();
    uint64_t gpa=e.va;
    bool denied=false;
    if(get(in,"context_vsatp")>>60) {
        uint64_t table=(get(in,"context_vsatp")&((1ULL<<44)-1))<<12;
        for(int level=2;level>=0;--level) {
            const auto at=table+((e.va>>(12+9*level))&511)*8;
            const auto pa=walkG(at,t,e.reads,false,denied);
            check(!denied,"implicit_permission");
            e.reads.push_back(pa);
            const auto p=t.at(pa),ppn=p>>10;
            check((p&1) && (p&10 || !(p&(16|64|128))),"pte_image");
            if(p&10) {
                check((p&64) && (p&(e.store?4:2)) && (!e.store || (p&128)) && !(p&16),"vs_permission");
                const auto low=(1ULL<<(12+9*level))-1;
                check(((ppn<<12)&low)==0,"pte_image");
                gpa=(ppn<<12)|(e.va&low);
                break;
            }
            table=ppn<<12;
        }
    }
    e.pa=walkG(gpa,t,e.reads,e.store,denied);
    if(denied) {
        e.fault=true;
        e.cause=e.store?23:21;
        e.guestPage=true;
        e.gpa=gpa;
        return e;
    }
    e.data=e.store?0:beat(bytesInitial(),e.pa);
    e.writeFp=!e.store;
    return e;
}
// Replay the full unmodified trace only after it has been written. The software
// ledger derives architectural data and the entire PTE address sequence from
// accepted input commands, not completion values or native summary counters.
static Fields verify(const Run& run,const std::string& name,const std::string& negative) {
    const bool stagger=name=="staggered";
    std::array<uint64_t,32> fpr {};
    Image bytes=bytesInitial();
    const auto ptes=tables();
    unsigned host=0,guest=0,fcsr=0;
    bool v=false,active=false,pending=false,seen=false,pendingGuest=false,hit=false;
    uint64_t index=0,tag=0,pc=0,hstatus=2ULL<<32,htval=0;
    Expected expected;
    Fields captured;
    unsigned acceptedCycle=0,op=0,readIndex=0,executeCount=0,adapterCount=0,physicalCount=0,pipelineCount=0,bufferCount=0;
    // One outstanding PTE response and one outstanding native-data response.
    bool pp=false,dp=false;
    unsigned pteHolds=0,physicalHolds=0;
    uint64_t pv=0,dv=0;
    unsigned pd=0,dd=0;
    std::optional<uint64_t> heldPte;
    std::optional<Fields> heldPhysical,heldComplete,adapterReply;
    Fields metrics= {
        {"schema", 1},
        {"component_only", 1},
        {"guest_fd_cpu_execution", 0},
        {"real_fp_memory", 1},
        {"external_trap_stimulus", 1},
        {"issued", 0},
        {"completion_accepts", 0},
        {"successful", 0},
        {"exceptional", 0},
        {"retirements", 0},
        {"traps", 0},
        {"recoveries", 0},
        {"fpr_writes", 0},
        {"mutations", 0},
        {"pte_requests", 0},
        {"pte_responses", 0},
        {"physical_requests", 0},
        {"physical_responses", 0},
        {"execute_accepts", 0},
        {"adapter_accepts", 0},
        {"buffer_responses", 0},
        {"pipeline_results", 0},
        {"inactive_tokens", 0},
        {"held_pte", 0},
        {"held_physical", 0},
        {"fault_pending_cycles", 0}
    };
    for(unsigned c=0;c<run.rows.size();++c) {
        const auto& row=run.rows[c];
        const auto& x=row.in;
        auto o=row.pre,post=row.post;
        diagnosticContext=" cycle="+std::to_string(c)+" phase="+row.phase;
        auto mutate=[&](const char* mode,const char* phase,Fields& target,const char* key,uint64_t value) {
            if(negative==mode && row.phase==phase) {
                target[key]=value;
                hit=true;
            }
        };
        mutate("denial_side_effect","op3_complete_hold_0",o,"executeValid",1);
        mutate("wrong_cause","op7_complete_hold_0",o,"complete_bits_cause",5);
        mutate("wrong_tval","op7_complete_hold_0",o,"complete_bits_tval",0x12345009);
        mutate("guest_metadata","op9_complete_hold_0",o,"complete_bits_guestFault_guestPhysicalAddress",0x11234502c);
        mutate("premature_owner_release","op1_complete_hold_0",o,"ownerActive",0);
        mutate("incomplete_release_drain","op9_accept",o,"memoryBusy",1);
        mutate("incomplete_release_drain","op9_accept",o,"selectorBusy",1);
        mutate("incomplete_release_drain","op9_accept",o,"memoryDrained",0);
        mutate("incomplete_trap_drain","op7_trap",o,"adapterIdle",0);
        mutate("incomplete_trap_drain","op7_trap",o,"memoryDrained",0);
        mutate("false_start_credit","op3_fault_pending_0",o,"start_ready",1);
        mutate("duplicate_completion","op3_fault_pending_0",o,"complete_valid",1);
        mutate("fault_mutation","op3_trap",post,"fpr_31",1);
        mutate("recovery_readback","op4_complete_hold_0",o,"complete_bits_data",loaded^1);
        auto eq=[&](const char* key,uint64_t value,const char* diagnostic) {
            check(get(o,key)==value,diagnostic);
        };
        const bool trap=get(x,"trap_valid"),status=get(x,"status_valid"),csr=get(x,"csr_valid");
        const bool ready=!pending && !status && !csr && !trap;
        eq("start_ready",ready,"false_start_credit");
        eq("busy",pending,"fp_busy");
        eq("ownerActive",active,"premature_owner_release");
        eq("ownerToken_index",index,"full_token");
        eq("ownerToken_tag",tag,"full_token");
        eq("completionSeen",seen,"completion_once");
        const bool complete=get(o,"stateCompleteValid") && !seen;
        eq("complete_valid",complete,"duplicate_completion");
        eq("stateCompleteValid",get(o,"statePhase")==3 && !trap,"state_complete");
        check((get(o,"statePhase")==0)==!pending,"state_phase");
        const bool start=ready && get(x,"start_valid"),accepted=get(o,"complete_valid") && get(x,"complete_ready");
        eq("issueAccepted",start,"start_accept");
        eq("completionAccepted",accepted,"complete_accept");
        const bool epoch=active && expected.memory;
        eq("fpMemoryEpoch",epoch,"memory_epoch");
        eq("contextMemoryEpoch",epoch,"memory_epoch");
        eq("hMemoryEpoch",0,"memory_epoch");
        eq("selectorDomain",epoch?2:0,"selector_domain");
        eq("selectorBusy",get(o,"memoryBusy"),"selector_busy");
const bool drained=!get(o,"memoryBusy") && get(o,"adapterIdle") && get(o,"translatorIdle") &&
            get(o,"responseBufferIdle") && !get(o,"completionCount");
        eq("memoryDrained",drained,"memory_drained");
        eq("contextReplaceAllowed",!pending && !active && drained,"context_permission");
eq("translationActive",get(x,"context_virtualized") || (get(x,"context_effectivePrivilege")!=3 &&
            (get(x,"hostSatp")>>60)),"translation_context");
        eq("fcsr",fcsr,"fcsr_preservation");
        eq("hostFs",host,"host_fs");
        eq("guestFs",guest,"guest_fs");
        eq("hostSd",host==3,"host_sd");
        eq("guestSd",guest==3,"guest_sd");
        eq("virtualized",v,"architectural_v");
        eq("hstatus",hstatus,"hstatus");
        eq("htval",htval,"htval");
        for(unsigned n=0;n<32;++n)check(get(o,"fpr_"+std::to_string(n))==fpr[n],"fpr_preservation");
        unsigned matches=0;
        for(unsigned lane=0;lane<2;++lane) {
            const auto k="commit"+std::to_string(lane)+"_";
            if(get(x,k+"valid") && get(x,k+"bits_index")==index && get(x,k+"bits_tag")==tag)matches|=1U<<lane;
        }
        const bool raw=matches,retire=pending && get(o,"statePhase")==3 && !trap && raw;
        eq("retireMatches",matches,"token_match");
        eq("retired",raw,"token_match");
        eq("retireAccepted",retire,"retirement");
        check(!(pending && expected.fault && raw),"no_fault_commit");
        const bool cm=csr && !pending && !status && get(x,"csr_bits_write");
        const bool mutation=cm || (retire && expected.writeFp && !expected.fault);
        eq("mutation_valid",mutation,"fault_mutation");
        if(mutation)eq("mutation_bits_guest",cm?v:pendingGuest,"mutation_owner");
        check(!(pending && (status || csr || get(x,"sret") || get(x,"mret"))),"idle_context");
        check(!get(x,"mret"),"no_m_origin");
if(pending) for(auto [k,value]:captured)if(k.rfind("context_",0)==0 || k=="hostSatp" ||
            k=="pmpTop" || k=="pmpPermission")check(get(x,k)==value,"stable_context");
if(pending && expected.denied)check(!get(o,"executeValid") && !get(o,"executeFire") && !get(o,"virtualRequest_valid") &&
            !get(o,"pte_request_valid") && !get(o,"physical_request_valid"),"denial_side_effect");
if(pending && expected.memory && (expected.va&7) && !expected.denied)check(!get(o,"virtualRequest_valid") &&
            !get(o,"pte_request_valid") && !get(o,"physical_request_valid"),"misalignment_side_effect");
        if(get(o,"executeFire")) {
            check(pending && !expected.denied && !executeCount,"execute_lifetime");
            ++executeCount;
            ++metrics["execute_accepts"];
        }
        if(get(o,"adapterFire")) {
check(pending && expected.memory && !expected.denied && !(expected.va&7) && executeCount==1 &&
                !adapterCount,"adapter_lifetime");
            ++adapterCount;
            ++metrics["adapter_accepts"];
        }
        if(get(o,"virtualRequest_valid")) {
            check(pending && expected.memory && !expected.denied && !(expected.va&7),"virtual_offer");
            eq("virtualRequest_bits_address",expected.va,"virtual_address");
            eq("virtualRequest_bits_size",3,"virtual_size");
            eq("virtualRequest_bits_write",expected.store,"virtual_store");
            eq("virtualRequest_bits_virtualized",1,"virtual_context");
        }
        // Reconstruct external ready/response timing independently of the driver.
        check(get(x,"pte_request_ready")==uint64_t(pteHolds>=(stagger?3U:1U)) &&
            get(x,"physical_request_ready")==uint64_t(physicalHolds>=(stagger?3U:1U)),"service_schedule");
        if(get(o,"pte_request_valid") && !get(x,"pte_request_ready"))++pteHolds;
        if(get(o,"physical_request_valid") && !get(x,"physical_request_ready"))++physicalHolds;
check(get(x,"pte_response_valid")==uint64_t(pp && !pd) && get(x,"pte_response_bits_data")==pv &&
            !get(x,"pte_response_bits_error"),"pte_response");
check(get(x,"physical_response_valid")==uint64_t(dp && !dd) && get(x,"physical_response_bits_data")==dv &&
            !get(x,"physical_response_bits_error") && !get(x,"physical_response_bits_pageFault"),"physical_response");
        if(pd)--pd;
        if(dd)--dd;
        if(get(x,"pte_response_valid") && get(o,"pte_response_ready")) {
            check(pp,"pte_credit");
            pp=false;
            ++metrics["pte_responses"];
        }
        if(get(x,"physical_response_valid") && get(o,"physical_response_ready")) {
            check(dp,"physical_credit");
            dp=false;
            ++metrics["physical_responses"];
        }
        if(heldPte)check(get(o,"pte_request_valid") && get(o,"pte_request_bits")==*heldPte,"held_pte");
        heldPte=get(o,"pte_request_valid") && !get(x,"pte_request_ready")?std::optional<uint64_t>(get(o,"pte_request_bits")):std::nullopt;
        if(heldPte)++metrics["held_pte"];
        if(get(o,"pte_request_valid")) {
            check(pending && readIndex<expected.reads.size() && get(o,"pte_request_bits")==expected.reads[readIndex],"pte_walk");
            if(get(x,"pte_request_ready")) {
                pteHolds=0;
                check(!pp,"pte_credit");
                pv=ptes.at(expected.reads[readIndex++]);
                pp=true;
                pd=stagger?4:2;
                ++metrics["pte_requests"];
            }
        }
        Fields request;
        for(auto [k,value]:o)if(k.rfind("physical_request_bits_",0)==0)request[k]=value;
        if(heldPhysical)check(get(o,"physical_request_valid") && request==*heldPhysical,"held_physical");
        heldPhysical=get(o,"physical_request_valid") && !get(x,"physical_request_ready")?std::optional<Fields>(request):std::nullopt;
        if(heldPhysical)++metrics["held_physical"];
        if(get(o,"physicalCheck_valid") || get(o,"physical_request_valid")) {
            check(pending && expected.memory && !expected.fault && readIndex==expected.reads.size(),"physical_permission");
            if(get(o,"physicalCheck_valid")) {
                eq("physicalCheck_bits_address",expected.pa,"physical_address");
                eq("physicalCheck_bits_access",expected.store,"physical_access");
                eq("physicalCheck_bits_size",3,"physical_access");
            }
        }
        if(get(o,"physical_request_valid")) {
            eq("physical_request_bits_address",expected.pa,"physical_address");
            eq("physical_request_bits_size",3,"physical_payload");
            eq("physical_request_bits_mask",255,"physical_payload");
            eq("physical_request_bits_write",expected.store,"physical_payload");
            eq("physical_request_bits_data",expected.storeData,"physical_payload");
            for(const char* field: {
                "atomic","atomicOp","uncached","virtualized","precheckedLoad","translationEpoch","prefetchNextAllowed"
            }
            )check(!get(o,std::string("physical_request_bits_")+field),"physical_payload");
            if(get(x,"physical_request_ready")) {
                physicalHolds=0;
                check(!dp && !physicalCount,"physical_credit");
                dv=beat(bytes,expected.pa);
                dp=true;
                dd=stagger?4:2;
                ++physicalCount;
                ++metrics["physical_requests"];
                if(expected.store)for(unsigned i=0;i<8;++i)bytes[expected.pa+i]=(expected.storeData>>(8*i))&255;
            }
        }
        auto reply=[&](const char* prefix,const char* fault) {
            Fields r;
            for(const char* field: {
                "data","error","pageFault"
            }
            )r[field]=get(o,std::string(prefix)+"_bits_"+field);
            for(const char* field: {
                "guestPageFault","guestAddress","guestPhysicalAddress","implicitPte"
            }
            )r[field]=get(o,std::string(fault)+"_"+field);
            return r;
        };
        if(get(o,"adapterResponse_valid")) {
            auto r=reply("adapterResponse","adapterFault");
            check(pending && adapterCount==1 && !pp && !dp && readIndex==expected.reads.size(),"adapter_response");
check(r.at("guestPageFault")==expected.guestPage && r.at("guestAddress")==1 && r.at("guestPhysicalAddress")==expected.gpa &&
                !r.at("implicitPte") && r.at("error")==expected.fault && !r.at("pageFault"),"guest_metadata");
            eq("responseEpoch",get(captured,"context_epoch"),"response_epoch");
            if(get(o,"adapterResponseFire")) {
                check(!adapterReply,"adapter_once");
                adapterReply=r;
            }
        }
        if(get(o,"bufferedResponse_valid"))check(adapterReply && reply("bufferedResponse","bufferedFault")==*adapterReply,"buffer_metadata");
        if(get(o,"bufferedResponseFire")) {
            ++bufferCount;
            ++metrics["buffer_responses"];
            check(bufferCount==1,"buffer_once");
        }
        // Preserve the whole completion envelope, including nonarchitectural
        // success cause/tval transport and unshifted guest fault provenance.
        auto envelope=[&](const char* prefix) {
            const std::string p=std::string(prefix)+"_bits_";
            check(get(o,p+"token_index")==index && get(o,p+"token_tag")==tag,"complete_token");
            check(get(o,p+"exception")==expected.fault,"exception_class");
            check(get(o,p+"cause")==expected.cause,"wrong_cause");
            check(get(o,p+"tval")==expected.tval,"wrong_tval");
            check(get(o,p+"nextPc")==pc+4,"complete_pc");
check(get(o,p+"guestFault_guestPageFault")==expected.guestPage && get(o,p+"guestFault_guestAddress")==expected.guestAddress &&
                get(o,p+"guestFault_guestPhysicalAddress")==expected.gpa && !get(o,p+"guestFault_implicitPte"),"guest_metadata");
            if(!expected.fault)check(get(o,p+"data")==expected.data,op>=4 && op%2==0?"recovery_readback":"completion_data");
        };
        if(get(o,"pipelineComplete_valid")) {
            check(pending && expected.memory && !expected.denied && !pipelineCount,"pipeline_once");
            envelope("pipelineComplete");
            ++pipelineCount;
            ++metrics["pipeline_results"];
            check(get(o,"convertedResult_valid"),"result_conversion");
            for(const char* key: {
                "token_index","token_tag","exception","cause","tval","guestFault_guestPageFault","guestFault_guestAddress","guestFault_guestPhysicalAddress","guestFault_implicitPte"
            }
            )check(get(o,std::string("convertedResult_bits_")+key)==get(o,std::string("pipelineComplete_bits_")+key),"result_conversion");
            check(get(o,"convertedResult_bits_value")==get(o,"pipelineComplete_bits_data") && !get(o,"convertedResult_bits_flags"),"result_conversion");
        }
        if(get(o,"complete_valid")) {
            check(pending && !seen,"duplicate_completion");
            envelope("complete");
        }
        Fields completion;
        for(auto [k,value]:o)if(k.rfind("complete_bits_",0)==0)completion[k]=value;
        if(heldComplete)check(get(o,"complete_valid") && completion==*heldComplete,"held_completion");
        heldComplete=get(o,"complete_valid") && !get(x,"complete_ready")?std::optional<Fields>(completion):std::nullopt;
        if(row.phase.find("complete_hold_")!=std::string::npos || row.phase.find("_accept")!=std::string::npos)check(get(o,"complete_valid"),"held_completion");
        if(pending && expected.fault && seen && !trap) {
check(!active && get(o,"busy") && !get(o,"start_ready") && !get(o,"complete_valid") &&
                get(o,"stateCompleteValid") && !get(o,"contextReplaceAllowed"),"fault_pending");
            ++metrics["fault_pending_cycles"];
        }
        if(accepted) {
            check(!seen && c-acceptedCycle<=320,"completion_once");
            check(executeCount==unsigned(!expected.denied),"execute_coverage");
            check(readIndex==expected.reads.size() && physicalCount==unsigned(expected.memory && !expected.fault),"memory_coverage");
check(adapterCount==unsigned(expected.memory && !expected.denied && !(expected.va&7)) &&
                bufferCount==adapterCount && pipelineCount==unsigned(expected.memory && !expected.denied),"transport_coverage");
            if(expected.fault) {
                check(drained && !pp && !dp && !get(o,"physical_request_valid") && !get(o,"pte_request_valid"),"incomplete_release_drain");
                active=false;
                ++metrics["exceptional"];
            }
            else ++metrics["successful"];
            seen=true;
            ++metrics["completion_accepts"];
        }
        // This checks a caller-supplied trap consumer edge, not ROB/MSU admission.
        if(trap) {
            check(pending && expected.fault && seen && !active && v,"trap_authority");
            check(drained && !pp && !dp && !get(o,"physical_request_valid") && !get(o,"pte_request_valid"),"incomplete_trap_drain");
check(get(x,"trap_bits_pc")==pc && get(x,"trap_bits_cause")==expected.cause && get(x,"trap_bits_tval")==expected.tval &&
                get(x,"trap_bits_guestAddress")==expected.guestAddress && get(x,"trap_bits_guestPhysicalAddress")==expected.gpa &&
                !get(x,"trap_bits_implicitPte"),"trap_envelope");
            check(!get(x,"start_valid") && !raw,"trap_exclusive");
            pending=false;
            seen=false;
            v=false;
            hstatus=(hstatus&~448ULL)|128|256|(expected.guestAddress?64:0);
            htval=expected.guestPage?expected.gpa>>2:0;
            ++metrics["traps"];
        }
        if(raw) {
            if(!active)++metrics["inactive_tokens"];
            active=false;
        }
        if(retire) {
            check(seen && !expected.fault,"retire_authority");
            pending=false;
            ++metrics["retirements"];
            if(expected.writeFp) {
                fpr[expected.rd]=expected.data;
                ++metrics["fpr_writes"];
            }
            if(op>=4 && op%2==0)++metrics["recoveries"];
        }
        if(status) {
            check(!pending && !active && drained,"status_idle");
            const auto addr=get(x,"status_bits_address"),data=get(x,"status_bits_data");
            if(addr==0x300)host=(data>>13)&3;
            else if(addr==0x200)guest=(data>>13)&3;
            else if(addr==0x600)hstatus=(2ULL<<32)|(data&0x7003c0);
            else check(false,"status_address");
        }
        if(cm) {
            check(host && (!v || guest) && get(x,"csr_bits_address")==3 && !get(x,"csr_bits_operation"),"csr_contract");
            fcsr=get(x,"csr_bits_value")&255;
        }
        if(mutation) {
            host=3;
            if(cm?v:pendingGuest)guest=3;
            if(!cm)++metrics["mutations"];
        }
        if(get(x,"sret")) {
            check(!v,"guest_return_origin");
            v=(hstatus>>7)&1;
            hstatus&=~128ULL;
        }
        if(start) {
            op=metrics["issued"];
            check(op<11,"issue_count");
            const auto wanted=recipe().at(op);
            for(const char* key: {
                "start_bits_instruction","start_bits_operand","start_bits_pc","start_bits_token_index","start_bits_token_tag"
            }
            )check(get(x,key)==get(wanted,key),"recipe_input");
            expected=answer(x,fpr,host,guest,v);
            captured=x;
            index=get(x,"start_bits_token_index");
            tag=get(x,"start_bits_token_tag");
            pc=get(x,"start_bits_pc");
            pending=true;
            active=true;
            seen=false;
            pendingGuest=v;
            acceptedCycle=c;
            readIndex=executeCount=adapterCount=physicalCount=pipelineCount=bufferCount=0;
            adapterReply.reset();
            ++metrics["issued"];
        }
check(get(post,"busy")==pending && get(post,"ownerActive")==active && get(post,"ownerToken_index")==index &&
            get(post,"ownerToken_tag")==tag,"post_lifecycle");
        check(get(post,"completionSeen")==seen && get(post,"virtualized")==v,"post_context");
        check(get(post,"hstatus")==hstatus && get(post,"htval")==htval,"post_hstate");
check(get(post,"fcsr")==fcsr && get(post,"hostFs")==host && get(post,"guestFs")==guest &&
            get(post,"hostSd")==unsigned(host==3) && get(post,"guestSd")==unsigned(guest==3),"post_fp_status");
        for(unsigned n=0;n<32;++n)check(get(post,"fpr_"+std::to_string(n))==fpr[n],"fault_mutation");
        if(c+1<run.rows.size())check(row.post==architecture(run.rows[c+1].pre),"post_link");
    }
    check(negative.empty() || hit,"negative_target_missing");
    // The surrounding bytes must remain identical, not merely the stored word.
    auto expectedBytes=bytesInitial();
    for(unsigned n=0;n<8;++n)expectedBytes[0xc0000080+n]=(seed>>(8*n))&255;
    check(bytes==expectedBytes && run.bytes==expectedBytes,"store_neighbor_bytes");
check(!pending && !active && !pp && !dp && metrics["issued"]==11 && metrics["completion_accepts"]==11 &&
        metrics["successful"]==7 && metrics["exceptional"]==4 && metrics["retirements"]==7 && metrics["traps"]==4 &&
        metrics["recoveries"]==4 && metrics["fpr_writes"]==2 && metrics["mutations"]==2 && metrics["execute_accepts"]==9 &&
        metrics["adapter_accepts"]==3 && metrics["buffer_responses"]==3 && metrics["pipeline_results"]==4 &&
        metrics["physical_requests"]==2 && metrics["physical_responses"]==2 && metrics["pte_requests"]==21 &&
        metrics["pte_responses"]==21 && metrics["held_pte"]==21*(stagger?3U:1U) && metrics["held_physical"]==2*(stagger?3U:1U) && fcsr==0x75,"coverage");
    metrics["cycles"]=run.rows.size();
    return metrics;
}
int main(int argc,char** argv) {
    try {
        std::string name="baseline",trace,negative;
        for(int n=1;n<argc;++n) {
            const std::string a=argv[n];
            check(n+1<argc,"arguments");
            if(a=="--schedule")name=argv[++n];
            else if(a=="--trace")trace=argv[++n];
            else if(a=="--negative")negative=argv[++n];
            else check(false,"arguments");
        }
        const std::vector<std::string> negatives= {
            "denial_side_effect","wrong_cause","wrong_tval","guest_metadata","premature_owner_release","incomplete_release_drain","incomplete_trap_drain","false_start_credit","duplicate_completion","fault_mutation","recovery_readback"
        };
        bool known=negative.empty();
        for(auto n:negatives)known|=n==negative;
        check(known && (name=="baseline" || name=="staggered") && !trace.empty(),"arguments");
        SGuardedFpFaultRecoveryGsim dut;
        drive(dut,defaults());
        dut.set_reset(1);
        dut.step();
        dut.step();
        dut.set_reset(0);
        const auto result=run(dut,name);
        std::ofstream out(trace);
        check(bool(out),"trace_open");
        out<<"{\"type\":\"header\",\"schema\":1,\"component_only\":true,\"guest_fd_cpu_execution\":false,\"real_fp_memory\":true,\"external_trap_stimulus\":true,\"cycle_limit\":2048,\"schedule\":\""<<name<<"\",\"recipe\":[";
        const auto ops=recipe();
        for(unsigned n=0;n<ops.size();++n) {
            if(n)out<<',';
            json(out,ops[n]);
        }
        out<<"],\"ptes\":";
        imageJson(out,tables());
        out<<",\"bytes\":";
        imageJson(out,bytesInitial());
        out<<"}\n";
        for(unsigned n=0;n<result.rows.size();++n) {
            const auto& row=result.rows[n];
            out<<"{\"type\":\"cycle\",\"cycle\":"<<n<<",\"phase\":\""<<row.phase<<"\",\"in\":";
            json(out,row.in);
            out<<",\"pre\":";
            json(out,row.pre);
            out<<",\"post\":";
            json(out,row.post);
            out<<"}\n";
        }
        out<<"{\"type\":\"footer\",\"cycles\":"<<result.rows.size()<<",\"complete\":true,\"bytes\":";
        imageJson(out,result.bytes);
        out<<"}\n";
        check(out.tellp()<=4194304,"trace_bound");
        out.close();
        check(bool(out),"trace_write");
        const auto metrics=verify(result,name,negative);
        std::cout<<"GUARDED_FP_FAULT_RECOVERY_SUMMARY ";
        json(std::cout,metrics);
        std::cout<<'\n';
        return 0;
    }
    catch(const std::exception& e) {
        std::cerr<<e.what()<<'\n';
        return 1;
    }
}
