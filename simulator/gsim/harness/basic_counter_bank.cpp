#include "BasicCounterBankGsim.h"
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>

// GSIM exposes the combinational observation BEFORE each rising edge.
struct Bench {
    SBasicCounterBankGsim d;
    uint64_t cycle=0,instret=0,edges=0,checks=0,tag=0,data=0;
    unsigned inhibit=0,index=0,address=0;
    uint64_t zeroCommits=0,singleCommits=0,dualCommits=0,tagMisses=0,indexMisses=0;
    uint64_t delayedWrites=0,pendingEdges=0,cycleWraps=0,instretWraps=0,inhibitTransitions=0;
    bool pending=false,reset=true;
    std::string negative;
    explicit Bench(std::string n):negative(n) {
        std::memset(&d,0,sizeof(d));d.LOG_START=1;d.activateAll();
        d.set_reset(1);tick();tick();reset=false;d.set_reset(0);tick();
    }
    void check(uint64_t got,uint64_t expected,const char* name) {
        ++checks;if(got!=expected)throw std::runtime_error(std::string(name)+" edge="+std::to_string(edges));
    }
    void tick(unsigned commits=0,bool wr=false,unsigned addr=0,uint64_t value=0,
              unsigned wi=0,uint64_t wt=0,bool retire=false,unsigned ri=0,uint64_t rt=0) {
        d.set_io$$acceptedCommits(commits);d.set_io$$write$$valid(wr);
        d.set_io$$write$$bits$$address(addr);d.set_io$$write$$bits$$data(value);
        d.set_io$$write$$bits$$token$$index(wi);d.set_io$$write$$bits$$token$$tag(wt);
        d.set_io$$retire$$valid(retire);d.set_io$$retire$$bits$$index(ri);d.set_io$$retire$$bits$$tag(rt);
        d.step();++edges;
        if(edges>1){check(d.get_io$$cycle(),cycle,"cycle edge oracle");check(d.get_io$$instret(),instret,"instret edge oracle");check(d.get_io$$inhibit(),inhibit,"inhibit edge oracle");}
        if(reset){cycle=instret=inhibit=0;pending=false;return;}
        zeroCommits+=commits==0;singleCommits+=commits==1;dualCommits+=commits==2;
        pendingEdges+=pending;
        tagMisses+=pending&&retire&&ri==index&&rt!=tag;
        indexMisses+=pending&&retire&&ri!=index&&rt==tag;
        const uint64_t oldCycle=cycle,oldInstret=instret;
        if(!(inhibit&1))++cycle;
        if(!(inhibit&4))instret+=commits;
        cycleWraps+=cycle<oldCycle;instretWraps+=instret<oldInstret;
        bool match=pending&&retire&&ri==index&&rt==tag;
        if(negative=="owner-tag"&&pending&&retire&&ri==index)match=true;
        if(negative=="owner-index"&&pending&&retire&&rt==tag)match=true;
        if(match){
            if(address==0xb00)cycle=data;
            if(address==0xb02)instret=data;
            if(address==0x320){inhibitTransitions+=inhibit!=(data&5);inhibit=data&5;}
            if(negative=="write-precedence"&&address==0xb00)++cycle;
            pending=false;
        }
        if(wr){pending=true;index=wi;tag=wt;address=addr;data=value;}
        if(negative=="cycle")++cycle;
        if(negative=="instret"&&commits==2)--instret;
    }
    void write(unsigned addr,uint64_t value) {
        ++delayedWrites;
        constexpr uint64_t owner=0x8000000000000041ULL;
        tick(0,true,addr,value,7,owner);
        tick(1,false,0,0,0,0,true,7,owner^0x8000000000000000ULL);
        tick(1,false,0,0,0,0,true,6,owner);
        tick(0);tick(1,false,0,0,0,0,true,7,owner);tick();
    }
};
int main(int argc,char**argv){try{
    std::string n=argc==2?argv[1]:"";
    const std::string prefix="--negative-control=";
    if(!n.empty()){if(n.rfind(prefix,0)!=0)throw std::runtime_error("expected --negative-control=NAME");n=n.substr(prefix.size());
        if(n!="cycle"&&n!="instret"&&n!="owner-tag"&&n!="owner-index"&&n!="write-precedence")throw std::runtime_error("unknown negative control");}
    Bench b(n);for(unsigned c:{0u,1u,2u,0u,2u})b.tick(c);
    b.write(0x320,~0ULL);b.tick(2);b.write(0xb00,~0ULL);b.write(0xb02,~0ULL);
    b.write(0x320,0);b.tick(2);b.tick(1); // Both 64-bit counters wrap.
    b.write(0x320,1);b.tick(2);b.write(0x320,4);b.tick(2);b.write(0x320,0);b.tick();
    std::cout<<"BASIC_COUNTER_BANK_PASS edges="<<b.edges<<" checks="<<b.checks
        <<" zero_commit_edges="<<b.zeroCommits<<" single_commit_edges="<<b.singleCommits<<" dual_commit_edges="<<b.dualCommits
        <<" owner_tag_misses="<<b.tagMisses<<" owner_index_misses="<<b.indexMisses
        <<" delayed_writes="<<b.delayedWrites<<" pending_edges="<<b.pendingEdges
        <<" cycle_wraps="<<b.cycleWraps<<" instret_wraps="<<b.instretWraps<<" inhibit_transitions="<<b.inhibitTransitions<<"\n";
}catch(const std::exception&e){std::cerr<<"BASIC_COUNTER_BANK_FAIL "<<e.what()<<'\n';return 1;}}
