#pragma once
#include <array>
#include <cstdint>
#include <tuple>
namespace mul_cpu_capture {
struct Token {
    unsigned index=0; uint64_t tag=0;
    bool operator<(const Token& b) const { return std::tie(index,tag)<std::tie(b.index,b.tag); }
    bool operator==(const Token& b) const { return index==b.index&&tag==b.tag; }
};
struct Row {
    Token token; unsigned source1=0,source2=0,destination=0,operation=0;
    bool pending=false,memoryLive=false,killed=false,ready1=false,ready2=false;
    bool writes=false,memory=false,store=false,atomic=false,mulDiv=false,word=false;
    uint64_t robTag=0;
};
struct Allocation {
    bool valid=false,writes=false,alias=false; Token token;
    unsigned source1=0,source2=0,destination=0; uint32_t instruction=0;
    bool memory=false,store=false,atomic=false;
};
struct Completion { bool valid=false,exception=false; Token token; uint64_t data=0; };
struct Payload { Token token; uint64_t left=0,right=0; unsigned operation=0; bool word=false; };
struct Frame {
    std::array<Row,16> rows{};
    std::array<bool,48> ready{};
    std::array<Allocation,2> allocations{};
    std::array<Completion,2> completions{},commits{};
    std::array<bool,2> reserveValid{},writeValid{};
    std::array<unsigned,2> reserveDestination{},writeDestination{};
    unsigned head=0,count=0,mulCount=0,mulTail=0,capturedSlot=0,selectedIndex=0,divState=0;
    Token capturedReservation;
    bool mulReady=false,divReady=false,mulPop=false,mulFire=false,divFire=false;
    bool selectedValid=false,grantMul=false,grantDiv=false,lateAllowed=false;
    bool recovering=false,recoveryAccepted=false,systemReserve=false,headException=false;
    bool arithmeticFire=false;
    Payload start,captured;
    Completion load,mulResult;
    bool loadPromise=false; unsigned loadDestination=0;
};
}
