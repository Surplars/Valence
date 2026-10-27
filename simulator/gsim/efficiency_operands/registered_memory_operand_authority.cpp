#include "RegisteredMemoryOperandAuthorityGsim.h"
#include <cstdint>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
#include <utility>

struct Input {
    unsigned source1=7, source2=9, loadDestination=7, destination=7, ownerIndex=3, completionIndex=3;
    bool ready1=false, ready2=true, loadValid=true, completionValid=true, exception=false, live=true;
    bool ordinaryLoad=true, writesRd=true, producerKilled=false, useSecond=false;
    uint64_t stored1=0xabc, stored2=0xdef, loadData=0x0123456789abcdefULL;
    uint64_t ownerTag=0x923456789abcdef0ULL, completionTag=0x923456789abcdef0ULL;
};

int main(int argc,char **argv) { try {
    const std::string mutant=argc==2?argv[1]:"";
    SRegisteredMemoryOperandAuthorityGsim d;
    d.set_reset(false);
    uint64_t cases=0, numericBeforePublication=0, rejectedForward=0, dual=0;
    bool injected=false;
    auto check=[&](const Input &x,const std::string &label) {
#define SET(N) d.set_io$$##N(x.N)
        SET(source1); SET(source2); SET(ready1); SET(ready2); SET(stored1); SET(stored2);
        SET(loadValid); SET(loadDestination); SET(loadData); SET(completionValid); SET(exception); SET(live);
        SET(ownerTag); SET(ownerIndex); SET(completionTag); SET(completionIndex);
        SET(ordinaryLoad); SET(writesRd); SET(destination); SET(producerKilled); SET(useSecond);
#undef SET
        d.step();
        // Procedural source policy independent of the DUT expression syntax.
        auto source=[&](unsigned id,bool ready,uint64_t stored) {
            const bool matches=id!=0 && x.loadValid && id==x.loadDestination;
            const uint64_t value=ready?stored:(matches?x.loadData:stored);
            return std::pair<bool,uint64_t>{ready||matches,value};
        };
        const auto first=source(x.source1,x.ready1,x.stored1), second=source(x.source2,x.ready2,x.stored2);
        bool authorized=true;
        if(!x.loadValid || !x.completionValid) authorized=false;
        if(x.exception || !x.live || !x.ordinaryLoad || !x.writesRd) authorized=false;
        if(x.ownerTag!=x.completionTag || x.ownerIndex!=x.completionIndex) authorized=false;
        if(x.destination==0 || x.destination!=x.loadDestination) authorized=false;
        const bool hit1=x.source1!=0 && x.loadValid && x.source1==x.loadDestination;
        const bool hit2=x.source2!=0 && x.loadValid && x.source2==x.loadDestination;
        const bool forwarded=(!x.ready1&&hit1)||(x.useSecond&&!x.ready2&&hit2);
        bool allowed=true;
        if(forwarded) allowed=authorized&&!x.producerKilled;
        auto actualValue1=d.get_io$$numericalValue1();
        auto actualValue2=d.get_io$$numericalValue2();
        bool actualReady=d.get_io$$numericalReady1();
        bool actualAuthority=d.get_io$$producerAuthority(), actualAllowed=d.get_io$$captureAllowed();
        // Observation negatives, deliberately NOT described as production RTL mutants.
        if(!injected && mutant=="--inject-ready" && label=="ordinary") {actualReady=!actualReady;injected=true;}
        if(!injected && mutant=="--inject-value" && label=="ordinary") {actualValue1^=1;injected=true;}
        if(!injected && mutant=="--inject-high-tag" && label=="tag-high") {actualAuthority=true;injected=true;}
        if(!injected && mutant=="--inject-fault" && label=="fault") {actualAllowed=true;injected=true;}
        if(!injected && mutant=="--inject-kill" && label=="killed") {actualAllowed=true;injected=true;}
        if(!injected && mutant=="--inject-ready-priority" && label=="registered-priority") {actualValue1=x.loadData;injected=true;}
        if(!injected && mutant=="--inject-second" && label=="second-only") {actualValue2^=1;injected=true;}
        if(!injected && mutant=="--inject-x0" && label=="zero-source") {actualReady=true;injected=true;}
        auto fail=[&](const char *reason){throw std::runtime_error(std::string(reason)+":"+label);};
        if(actualReady!=first.first || bool(d.get_io$$numericalReady2())!=second.first)fail("OPERAND_READY");
        if(actualValue1!=first.second || actualValue2!=second.second)fail("OPERAND_VALUE");
        if(bool(d.get_io$$hit1())!=hit1 || bool(d.get_io$$hit2())!=hit2)fail("OPERAND_HIT");
        if(actualAuthority!=authorized)fail("PRODUCER_AUTHORITY");
        if(bool(d.get_io$$forwarded())!=forwarded)fail("FORWARDED_SELECTION");
        if(actualAllowed!=allowed)fail("CAPTURE_AUTHORIZATION");
        ++cases;numericBeforePublication+=forwarded&&allowed;rejectedForward+=forwarded&&!allowed;
        dual+=x.useSecond&&hit1&&hit2&&!x.ready1&&!x.ready2;
    };
    Input base;
    check(base,"ordinary");
    auto x=base; x.completionTag^=uint64_t(1)<<63;check(x,"tag-high");
    for(unsigned bit=0;bit<64;++bit){x=base;x.completionTag^=uint64_t(1)<<bit;check(x,"tag-bit");}
    for(unsigned bit=0;bit<4;++bit){x=base;x.completionIndex^=1u<<bit;check(x,"index-bit");}
    x=base;x.exception=true;check(x,"fault");
    x=base;x.producerKilled=true;check(x,"killed");
    x=base;x.live=false;check(x,"stale-producer");
    x=base;x.ordinaryLoad=false;check(x,"atomic-or-store");
    x=base;x.writesRd=false;check(x,"no-write-destination");
    x=base;x.destination=8;check(x,"wrong-destination");
    x=base;x.loadDestination=0;x.destination=0;check(x,"zero-destination");
    x=base;x.source1=0;check(x,"zero-source");
    x=base;x.loadValid=false;check(x,"invalid-promise");
    x=base;x.completionValid=false;check(x,"invalid-completion");
    x=base;x.ready1=true;check(x,"registered-priority");
    x=base;x.source1=9;x.source2=7;x.ready1=true;x.ready2=false;x.useSecond=true;check(x,"second-only");
    x=base;x.source2=7;x.ready2=false;x.useSecond=true;check(x,"both-operands");
    x=base;x.source1=9;x.source2=7;x.ready2=false;x.useSecond=false;x.producerKilled=true;check(x,"unused-second");
    // OLD producer token/data followed by a same-index new-generation result.
    x=base;check(x,"old-owner");x.completionTag++;check(x,"new-slot-stale-owner");
    x.ownerTag=x.completionTag;x.loadData^=0x8000000000000000ULL;check(x,"new-slot-current-owner");
    for(unsigned mask=0;mask<256;++mask){
        x=base;x.ready1=mask&1;x.ready2=mask&2;x.useSecond=mask&4;x.source2=(mask&8)?7:9;
        x.exception=mask&16;x.producerKilled=mask&32;x.loadValid=!(mask&64);x.live=!(mask&128);check(x,"bounded-flags");
    }
    std::mt19937_64 rng(0x20261026a117ULL);
    for(unsigned n=0;n<12000;++n){
        x=base;x.ownerTag=rng();x.completionTag=x.ownerTag;
        x.ownerIndex=rng()%16;x.completionIndex=x.ownerIndex;
        x.source1=rng()%48;x.source2=rng()%48;x.loadDestination=(n%3)?x.source1:x.source2;x.destination=x.loadDestination;
        x.ready1=rng()&1;x.ready2=rng()&1;x.useSecond=rng()&1;x.loadData=rng();x.stored1=rng();x.stored2=rng();
        x.loadValid=n%7!=0;x.completionValid=n%11!=0;x.live=n%13!=0;x.producerKilled=n%17==0;
        x.exception=n%19==0;x.ordinaryLoad=n%23!=0;x.writesRd=n%29!=0;
        if(n%31==0)x.completionTag^=uint64_t(1)<<(n%64);
        if(n%37==0)x.destination=(x.destination+1)%48;
        check(x,"random");
    }
    if(!mutant.empty()&&!injected)throw std::runtime_error("UNKNOWN_OR_UNEXERCISED_NEGATIVE");
    if(!numericBeforePublication||!rejectedForward||!dual)throw std::runtime_error("MISSING_DIRECTED_COVERAGE");
    std::cout<<"PASS_REGISTERED_MEMORY_OPERAND_HELPER cases="<<cases<<" numericOnly="<<numericBeforePublication
        <<" denied="<<rejectedForward<<" dual="<<dual<<" integrationConsumerEpochProofStart=NOT_COVERED\n";
    return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
