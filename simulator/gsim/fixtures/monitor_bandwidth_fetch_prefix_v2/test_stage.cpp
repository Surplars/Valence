#include "stage_trace.h"
#include "backend_ownership_ledger.h"
#include <functional>
#include <iostream>
#include <sstream>
using namespace monitor_stage;
unsigned negatives=0;
void rejects(const std::function<void()> &fn,const char *message){
    try{fn();}catch(const std::runtime_error &e){require(std::string(e.what()).find(message)!=std::string::npos,"wrong host negative reason");++negatives;return;}
    throw std::runtime_error("host negative accepted corruption");
}
void bit(BackendSample &s,unsigned n){s.events|=1ULL<<n;}
int main(){try{
    StageTrace trace;Snapshot s;
    Entry producer{{0x100000001ULL,0},0xfff787c8,0,0,5,true,false,true,true,true,false};
    Entry load{{0x200000001ULL,1},0xfff787d0,5,0,6,true,false,true,true,true,false};
    Entry pointer{{0x300000001ULL,2},0xfff787d4,5,0,7,true,false,true,true,true,false};
    Entry sum{{0x400000001ULL,3},0xfff787d8,0,6,8,true,false,true,false,true,false};
    Entry branch{{0x500000001ULL,4},0xfff787dc,5,7,0,false,false,true,false,true,false};
    s.allocations={producer.key};trace.sample(0,s);
    s.allocations={load.key,pointer.key};s.entries={producer};trace.sample(1,s);trace.retire(producer.key,producer.pc,1);
    s.allocations={sum.key,branch.key};s.entries={load,pointer};trace.sample(2,s);
    s.allocations.clear();s.entries={load,pointer,sum,branch};trace.sample(3,s);
    s.prepared=load.key;s.address=0xfff98000;s.capacityBlocked=true;trace.sample(4,s);
    s.available=true;s.capacityBlocked=false;s.start=load.key;trace.sample(5,s);trace.physical(load.key,s.address,5);
    rejects([&]{auto t=trace;auto bad=s;bad.start->first^=1ULL<<40;t.sample(6,bad);},"hot stage start lacks full-token ROB owner");
    rejects([&]{auto t=trace;t.physical(load.key,s.address+8,5);},"hot physical request lost staged full-token address");
    s.start.reset();s.prepared.reset();for(auto &e:s.entries){e.pending=false;e.done=true;e.ready1=e.ready2=true;}trace.sample(6,s);
    for(const auto &e:s.entries)trace.retire(e.key,e.pc,7);
    std::ostringstream rows,summary;trace.report(rows,summary,1);
    require(summary.str().find("retired_predecessor_retirement_without_done_joins=1")!=std::string::npos,"missing host predecessor join");
    rejects([&]{trace.retire(load.key,load.pc,8);},"hot stage duplicate/cancelled retirement");
    // Same ROB index, distinct full generations must never reuse an old node.
    s.entries.clear();Entry replacement=producer;replacement.key.first^=1ULL<<41;
    s.allocations={replacement.key};trace.sample(8,s);s.allocations.clear();s.entries={replacement};trace.sample(9,s);require(trace.active.contains(replacement.key)&&!trace.active.contains(producer.key),"hot stage truncated token alias");
    BackendOwnershipLedger ledger;
    static_assert(BackendSample::ownerCount==4&&BackendOwnershipLedger::trackSlotLifetimes);
    std::array<BackendToken,4> tokens{{{0x100000001ULL,1},{0x200000001ULL,2},{0x300000001ULL,3},{0x400000001ULL,4}}};
    auto resident=[&](unsigned count){BackendSample b;b.fifoCount=count;if(count)bit(b,22);for(unsigned i=0;i<count;++i){b.live[i]=true;b.phase[i]=2;b.parallel[i]=true;b.slots[i]=tokens[i];}return b;};
    for(unsigned n=0;n<4;++n){auto b=resident(n);b.start=b.request=tokens[n];for(unsigned k:{3,8,20,21,41})bit(b,k);ledger.advance(b);}
    auto b=resident(4);
    rejects([&]{auto copy=ledger;auto wrong=b;wrong.slots[2].tag^=1ULL<<40;copy.advance(wrong);},"slot full-token generation or position changed");
    for(unsigned n=0;n<4;++n){b={};b.fifoCount=4-n;bit(b,22);for(unsigned i=n;i<4;++i){b.live[i]=true;b.phase[i]=2;b.parallel[i]=true;b.slots[i]=tokens[i];}
        if(n){b.live[n-1]=true;b.phase[n-1]=3;b.parallel[n-1]=true;b.slots[n-1]=tokens[n-1];b.complete=tokens[n-1];bit(b,26);bit(b,27);}
        b.returnSlot=n;for(unsigned k:{23,24,25,28})bit(b,k);ledger.advance(b);
    }
    b={};b.live[3]=true;b.phase[3]=3;b.parallel[3]=true;b.slots[3]=tokens[3];b.complete=tokens[3];bit(b,26);bit(b,27);ledger.advance(b);ledger.advance({});
    require(ledger.requests.empty()&&ledger.responses.empty()&&!ledger.stalledRequest&&
        std::none_of(ledger.slotOwners.begin(),ledger.slotOwners.end(),[](auto owner){return owner.live;}),"host four-owner drain failed");
    BackendOwnershipLedger held;b={};b.start=b.request=tokens[0];for(unsigned k:{3,8,20,41})bit(b,k);held.advance(b);
    b={};b.live[0]=true;b.phase[0]=1;b.parallel[0]=true;b.slots[0]=tokens[0];b.request=tokens[1];bit(b,20);bit(b,41);
    rejects([&]{held.advance(b);},"stalled request full-token owner changed or vanished");
    std::cout<<"PASS_MONITOR_V2_STAGE_HOST negatives="<<negatives<<" four_owner_drain=1 producer_full_token_join=1 producer_retirement_without_registered_done=1\n";return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
