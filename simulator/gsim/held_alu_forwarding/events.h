#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <tuple>
#include <vector>
namespace b1 {
struct Token {
    unsigned index=0; uint64_t tag=0;
    bool operator==(const Token&) const = default;
    bool operator<(const Token& b) const { return std::tie(index,tag)<std::tie(b.index,b.tag); }
};
struct Rename {
    bool valid=false, writes=false, moveAlias=false;
    Token token{}; uint64_t pc=0; uint32_t instruction=0;
    unsigned source1=0, source2=0, destination=0, oldDestination=0, rd=0;
};
struct Stage {
    bool occupied=false,cancel=false,enqValid=false,enqReady=false,deqValid=false,deqReady=false;
    Token held{},incoming{}; unsigned destination=0,source1=0,source2=0,heldSource1=0,heldSource2=0;
    bool heldUsePc=false,heldUseImmediate=false;
    uint64_t left=0,right=0,result=0,incomingLeft=0,incomingRight=0;
    bool forwardable=false,promise=false; unsigned promiseDestination=0;
    bool incomingUsePc=false,incomingUseImmediate=false,incomingMemory=false;
    bool capture() const { return enqValid&&enqReady; }
    bool drain() const { return deqValid&&deqReady; }
};
enum class Producer { none, execution0, execution1, lsu, divider, multiplier, system, heldBranch };
struct Completion {
    bool valid=false,accepted=false,exception=false;Token token{};
    uint64_t data=0,nextPc=0,cause=0,tval=0;Producer producer=Producer::none;
};
struct Write { bool valid=false;unsigned destination=0;uint64_t data=0; };
struct ReadyEvent { bool valid=false;unsigned destination=0; };
struct Start {
    bool fire=false,store=false,virtualized=false,prechecked=false,accessDenied=false;
    Token token{};uint64_t address=0,data=0,left=0,right=0;unsigned destination=0,size=0;
    uint32_t epoch=0;
};
struct StorePrepare { bool grant=false,dataReady=false;Token token{};uint64_t base=0,immediate=0,data=0; };
enum class RecoveryKind { none, branch, trap, system, replay };
struct Recovery { bool accepted=false,inclusive=false;RecoveryKind kind=RecoveryKind::none;Token token{};uint64_t target=0; };
struct Trap { bool valid=false;Token token{};uint64_t pc=0,cause=0,tval=0; };
struct Retire { bool valid=false,writes=false,dataValid=false;Token token{};uint64_t pc=0,data=0,nextPc=0;uint32_t instruction=0;unsigned rd=0,destination=0; };
struct SystemStart { bool fire=false;Token token{};uint64_t pc=0,operand=0;uint32_t instruction=0; };
struct MemoryRequest {
    bool valid=false,ready=false,write=false,atomic=false,virtualized=false,prechecked=false,ownerValid=false;
    unsigned handle=0,size=0,mask=0;Token token{};uint64_t address=0,data=0;uint32_t epoch=0;
    bool fire() const {return valid&&ready;}
};
struct MemoryResponse { bool valid=false,ready=false,error=false,pageFault=false;unsigned handle=0;uint64_t data=0;bool fire() const{return valid&&ready;} };
// Existing backend/tagged boundaries: CPU virtual request and final physical
// request use separate records. OwnerValid forbids inventing a token from PA.
struct PhysicalRequest { bool valid=false,ready=false,write=false,ownerValid=false;unsigned handle=0,size=0,mask=0;Token token{};uint64_t address=0,data=0;bool fire() const{return valid&&ready;} };
struct LsuOwner {
    bool live=false,cancel=false,discard=false,complete=false,savedDestinationValid=false,store=false,parallel=false,certifiedStore=false,requestAccepted=false;
    Token token{};unsigned phase=0,savedDestination=0,handle=0;
};
struct Proof {
    std::string name;bool valid=false,created=false,cleared=false,bound=false,bind=false,result=false,authorized=false;
    Token token{};uint32_t epoch=0;uint64_t virtualAddress=0,physicalAddress=0;unsigned size=0,mask=0;
};
struct Snapshot {
    uint64_t cycle=0;
    std::array<Rename,2> rename{};std::array<Stage,2> stage{};
    std::array<Completion,2> complete{};std::array<Write,2> prfWrite{};
    std::array<ReadyEvent,2> wake{},reserve{};
    std::array<bool,64> ready{};std::array<uint64_t,64> physical{};
    std::array<Retire,2> retire{};std::array<StorePrepare,2> storePrepare{};
    Start memory{},multiplier{},divider{};SystemStart system{};
    std::array<LsuOwner,4> lsuOwners{};bool systemProtected=false;Token systemOwner{};
    Recovery recovery{};Trap trap{},pendingException{};
    bool recovering=false,headValid=false,headDone=false;Token head{};
    unsigned pendingMask=0,killedMask=0,preparedMask=0;
    bool rawLsu=false,rawDivider=false,rawMultiplier=false,rawSystem=false;
    MemoryRequest request{};MemoryResponse response{};PhysicalRequest physicalRequest{};
    std::vector<Proof> proofs;uint32_t epoch=0;bool contextFlush=false,pmpChanged=false;
    uint64_t satp=0;unsigned dataPrivilege=3;bool sum=false,mxr=false;
    std::array<uint64_t,16> pmpAddress{};std::array<unsigned,16> pmpConfig{};
};
} // namespace b1
