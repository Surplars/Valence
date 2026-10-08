#include "ManagedMdioArbiter.h"
#include <deque>
#include <iostream>
#include <optional>
#include <random>
#include <stdexcept>
#include <string_view>
#define S(n,v) d.set_io$$##n(v)
#define G(n) d.get_io$$##n()
static void check(bool good,const char*why){if(!good)throw std::runtime_error(why);}
struct Cmd{unsigned phy,reg,write,data; bool operator==(const Cmd&)const=default;};
struct Test{
    SManagedMdioArbiter d;std::mt19937 random{0x22abcd};
    std::optional<Cmd> policy,software,engine;
    std::deque<std::pair<unsigned,bool>> expectPolicy,expectSoftware;
    unsigned latency=0,cycles=0,policyCount=0,softwareCount=0,denied=0,wire=0;
    bool lock=false,initialized=true,inject=false;
    Test(){S(policyCommand$$valid,0);S(softwareCommand$$valid,0);S(engineResponse$$valid,0);S(engineCommand$$ready,0);S(policyResponse$$ready,0);S(softwareResponse$$ready,0);S(policyLock,0);S(initialized,1);
        d.set_reset(1);d.step();d.step();d.set_reset(0);}
    void tick(){
        S(policyLock,lock);S(initialized,initialized);S(policyCommand$$valid,policy.has_value());S(softwareCommand$$valid,software.has_value());
        if(policy){S(policyCommand$$bits$$phy,policy->phy);S(policyCommand$$bits$$register,policy->reg);S(policyCommand$$bits$$write,policy->write);S(policyCommand$$bits$$data,policy->data);}
        if(software){S(softwareCommand$$bits$$phy,software->phy);S(softwareCommand$$bits$$register,software->reg);S(softwareCommand$$bits$$write,software->write);S(softwareCommand$$bits$$data,software->data);}
        const bool eReady=!engine&&random()%3!=0,pReady=random()%4!=0,sReady=random()%4!=0,eValid=engine&&latency==0;
        S(engineCommand$$ready,eReady);S(policyResponse$$ready,pReady);S(softwareResponse$$ready,sReady);S(engineResponse$$valid,eValid);
        const unsigned answer=engine?((engine->data^0x5a5a)+(engine->reg<<5)+engine->phy)&0xffff:0;S(engineResponse$$bits$$data,answer);S(engineResponse$$bits$$noAck,0);d.step();++cycles;
        if(eValid&&G(engineResponse$$ready))engine.reset();
        if(G(engineCommand$$valid)&&eReady){
            Cmd got{unsigned(G(engineCommand$$bits$$phy)),unsigned(G(engineCommand$$bits$$register)),unsigned(G(engineCommand$$bits$$write)),unsigned(G(engineCommand$$bits$$data))};
            check(lock?policy&&got==*policy:software&&got==*software,"MDIO independent command-owner oracle mismatch");
            if(inject)check(got.reg==(got.reg^1),"MDIO independent command-owner oracle mismatch");
            engine=got;latency=2+random()%13;++wire;
        }
        if(policy&&G(policyCommand$$ready)){check(lock,"MDIO manager command accepted without page lock");expectPolicy.push_back({((policy->data^0x5a5a)+(policy->reg<<5)+policy->phy)&0xffff,false});policy.reset();}
        if(software&&G(softwareCommand$$ready)){
            check(!lock,"software MDIO entered locked page sequence");bool allowed=initialized&&!software->write&&software->phy==1&&software->reg<16;
            expectSoftware.push_back({allowed?((software->data^0x5a5a)+(software->reg<<5)+software->phy)&0xffff:0xffff,!allowed});software.reset();
        }
        denied+=G(softwareDenied);
        if(G(policyResponse$$valid)&&pReady){check(!expectPolicy.empty()&&expectPolicy.front()==std::make_pair(unsigned(G(policyResponse$$bits$$data)),bool(G(policyResponse$$bits$$noAck))),"MDIO policy response went to wrong owner");expectPolicy.pop_front();++policyCount;}
        if(G(softwareResponse$$valid)&&sReady){check(!expectSoftware.empty()&&expectSoftware.front()==std::make_pair(unsigned(G(softwareResponse$$bits$$data)),bool(G(softwareResponse$$bits$$noAck))),"MDIO software response went to wrong owner");expectSoftware.pop_front();++softwareCount;}
        if(engine&&latency)--latency;
    }
    template<class F>void until(F done){unsigned n=0;do{tick();++n;}while(!done()&&n<1000);check(done(),"MDIO arbitration response timeout");}
};
int main(int argc,char**argv){try{
    Test t;t.inject=argc==2&&std::string_view(argv[1])=="--inject-mismatch";
    for(unsigned group=0;group<80;++group){
        t.lock=true;t.software=Cmd{1,group%32,group%3==0,group*17};
        for(unsigned op=0;op<5;++op){t.policy=Cmd{1,op==0||op==4?31U:17U,op%2,group*31+op};
            t.until([&]{return !t.policy&&t.expectPolicy.empty()&&!t.engine;});check(t.software.has_value(),"software consumed partway through PHY page transaction");}
        t.lock=false;t.initialized=group%7!=0;t.until([&]{return !t.software&&t.expectSoftware.empty()&&!t.engine;});
    }
    check(t.policyCount==400&&t.softwareCount==80&&t.denied>40,"MDIO arbitration coverage incomplete");
    std::cout<<"MANAGED_MDIO_ARBITER_PASS policy_commands="<<t.policyCount<<" software_commands="<<t.softwareCount<<" denied="<<t.denied<<" wire_transactions="<<t.wire<<" cycles="<<t.cycles<<" locked_page_sequences=80 randomized_backpressure=1\n";return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
