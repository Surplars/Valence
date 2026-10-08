#include "HomeMshrGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <tuple>
#include <vector>
#ifndef HOME_ENTRIES
#define HOME_ENTRIES 2
#endif
static void check(bool p,const char* s){if(!p)throw std::runtime_error(s);}
using Line=std::array<uint64_t,8>;
#ifndef HOME_BASE
#define HOME_BASE 0x80010000ULL
#endif
static constexpr uint64_t base=HOME_BASE;
static uint64_t initial(uint64_t address){return 0x8135792468000000ULL^address;}
struct Acquisition {uint64_t address;unsigned source,beat=0,sink=0;bool error=false;Line words{};};
struct CPacket {uint64_t address;unsigned source,opcode,param,beat=0;Line words{};};
struct Ack {unsigned sink,source;};
struct Reply {uint64_t address;unsigned source,beat=0;bool write=false,error=false;uint64_t due;};
struct Test {
    SHomeMshrGsim d;
    uint64_t cycle=0;
    std::map<uint64_t,uint64_t> memory,reference;
    std::map<uint64_t,Line> cache;
    std::map<uint64_t,bool> dirty;
    std::deque<Acquisition> requests;
    std::map<unsigned,Acquisition> live;
    std::deque<CPacket> c;
    std::deque<Ack> e;
    std::vector<Reply> pending;
    std::optional<Reply> held;
    std::optional<CPacket> write;
    std::optional<uint64_t> releasing,upper;
    std::optional<uint64_t> dataResponse;
    std::optional<uint64_t> denyAddress;
    bool upperAccepted=false,allowD=true,allowE=true,holdB=false,badSink=false,inject=false;
    unsigned accepted=0,grants=0,finished=0,releases=0,cBeats=0,writes=0,probes=0,upperDone=0,peak=0,readGets=0;
    std::optional<std::array<uint64_t,7>> heldGrant,heldRequest;
    std::optional<std::array<uint64_t,4>> heldProbe;
    uint64_t value(uint64_t a){auto p=memory.find(a);return p==memory.end()?initial(a):p->second;}
    uint64_t expected(uint64_t a){auto p=reference.find(a);return p==reference.end()?initial(a):p->second;}
    explicit Test(){
        d.set_reset(1);
        d.set_io$$dispatchOffer_0(0);d.set_io$$dispatchOffer_1(0);
        d.set_io$$dispatchSeed_0(0);d.set_io$$dispatchSeed_1(0);d.set_io$$dispatchReady(0);
        d.set_io$$upstream$$request$$valid(0);d.set_io$$downstream$$response$$valid(0);
        d.set_io$$client$$a$$valid(0);d.set_io$$client$$c$$valid(0);d.set_io$$client$$e$$valid(0);
        d.set_io$$line$$d$$valid(0);d.set_io$$line$$b$$valid(0);d.set_io$$line$$c$$ready(0);d.set_io$$line$$e$$ready(0);
        d.step();d.step();d.set_reset(0);
    }
    void resetEpoch(){
        d.set_io$$upstream$$request$$valid(0);d.set_io$$downstream$$response$$valid(0);
        d.set_io$$client$$a$$valid(0);d.set_io$$client$$c$$valid(0);d.set_io$$client$$e$$valid(0);d.set_io$$line$$d$$valid(0);
        d.set_reset(1);d.step();d.step();d.set_reset(0);
        requests.clear();live.clear();c.clear();e.clear();pending.clear();held.reset();write.reset();releasing.reset();upper.reset();dataResponse.reset();
        cache.clear();dirty.clear();reference=memory;denyAddress.reset();upperAccepted=false;holdB=false;allowD=true;allowE=true;
        heldGrant.reset();heldRequest.reset();heldProbe.reset();
    }
    void acquire(uint64_t a,unsigned source){requests.push_back({a,source});}
    void modify(uint64_t a){check(cache.count(a),"modify lacks software owner");for(unsigned b=0;b<8;++b){cache[a][b]=0xfedcba9800000000ULL^a^b;reference[a+8*b]=cache[a][b];}dirty[a]=true;}
    void release(uint64_t a){check(!releasing&&cache.count(a),"release lacks software owner");releasing=a;c.push_back({a,4,dirty[a]?7U:6U,1,0,cache[a]});}
    void tick(){
        if(!held){for(auto i=pending.rbegin();i!=pending.rend();++i)if(i->due<=cycle){held=*i;pending.erase(std::next(i).base());break;}}
        const bool av=!requests.empty(),cv=!c.empty(),ev=!e.empty()&&allowE;
        Acquisition a=av?requests.front():Acquisition{};CPacket cp=cv?c.front():CPacket{};
        bool dr=allowD&&cycle%7!=3,br=!holdB&&!releasing;
        const bool lr=cycle%5!=1,ur=cycle%5!=2;
        d.set_io$$client$$a$$valid(av);d.set_io$$client$$a$$bits$$opcode(6);d.set_io$$client$$a$$bits$$param(1);
        d.set_io$$client$$a$$bits$$address(a.address);d.set_io$$client$$a$$bits$$size(6);d.set_io$$client$$a$$bits$$source(a.source);
        d.set_io$$client$$a$$bits$$mask(255);d.set_io$$client$$a$$bits$$data(0);d.set_io$$client$$a$$bits$$corrupt(0);
        d.set_io$$client$$d$$ready(dr);d.set_io$$client$$b$$ready(br);
        d.set_io$$client$$c$$valid(cv);d.set_io$$client$$c$$bits$$opcode(cp.opcode);d.set_io$$client$$c$$bits$$param(cp.param);
        d.set_io$$client$$c$$bits$$address(cp.address);d.set_io$$client$$c$$bits$$size(6);d.set_io$$client$$c$$bits$$source(cp.source);
        d.set_io$$client$$c$$bits$$data(cp.words[cp.beat]);d.set_io$$client$$c$$bits$$corrupt(0);
        d.set_io$$client$$e$$valid(ev);d.set_io$$client$$e$$bits$$sink(ev?(badSink?(HOME_ENTRIES==1?1:HOME_ENTRIES-1):e.front().sink):0);
        d.set_io$$line$$a$$ready(lr);d.set_io$$line$$d$$valid(bool(held));
        d.set_io$$line$$d$$bits$$opcode(held&&held->write?0:1);d.set_io$$line$$d$$bits$$param(0);
        d.set_io$$line$$d$$bits$$source(held?held->source:0);d.set_io$$line$$d$$bits$$sink(0);
        d.set_io$$line$$d$$bits$$size(6);d.set_io$$line$$d$$bits$$denied(held&&held->error);
        d.set_io$$line$$d$$bits$$corrupt(held&&held->error&&!held->write);
        d.set_io$$line$$d$$bits$$data(held&&!held->write?value(held->address+8*held->beat):0);
        d.set_io$$upstreamRequestCpu(0);d.set_io$$upstream$$request$$valid(bool(upper)&&!upperAccepted);
        d.set_io$$upstream$$request$$bits$$address(upper.value_or(0));d.set_io$$upstream$$request$$bits$$size(3);
        d.set_io$$upstream$$request$$bits$$write(0);d.set_io$$upstream$$request$$bits$$data(0);d.set_io$$upstream$$request$$bits$$mask(255);
        d.set_io$$upstream$$request$$bits$$atomic(0);d.set_io$$upstream$$request$$bits$$atomicOp(0);
        d.set_io$$upstream$$request$$bits$$virtualized(0);d.set_io$$upstream$$request$$bits$$uncached(0);
        d.set_io$$upstream$$response$$ready(1);d.set_io$$downstream$$request$$ready(ur);
        d.set_io$$downstream$$response$$valid(bool(dataResponse));d.set_io$$downstream$$response$$bits$$data(dataResponse.value_or(0));
        d.set_io$$downstream$$response$$bits$$error(0);d.set_io$$downstream$$response$$bits$$pageFault(0);
        d.step();
        std::array<uint64_t,7> grantBits{d.get_io$$client$$d$$bits$$opcode(),d.get_io$$client$$d$$bits$$source(),d.get_io$$client$$d$$bits$$sink(),d.get_io$$client$$d$$bits$$size(),d.get_io$$client$$d$$bits$$denied(),d.get_io$$client$$d$$bits$$corrupt(),d.get_io$$client$$d$$bits$$data()};
        std::array<uint64_t,7> requestBits{d.get_io$$line$$a$$bits$$opcode(),d.get_io$$line$$a$$bits$$source(),d.get_io$$line$$a$$bits$$address(),d.get_io$$line$$a$$bits$$size(),d.get_io$$line$$a$$bits$$mask(),d.get_io$$line$$a$$bits$$data(),d.get_io$$line$$a$$bits$$param()};
        std::array<uint64_t,4> probeBits{d.get_io$$client$$b$$bits$$address(),d.get_io$$client$$b$$bits$$source(),d.get_io$$client$$b$$bits$$opcode(),d.get_io$$client$$b$$bits$$param()};
        if(heldGrant)check(d.get_io$$client$$d$$valid()&&grantBits==*heldGrant,"home D changed under stall");
        if(heldRequest)check(d.get_io$$line$$a$$valid()&&requestBits==*heldRequest,"home backing A changed under stall");
        if(heldProbe)check(d.get_io$$client$$b$$valid()&&probeBits==*heldProbe,"home B changed under stall");
        heldGrant=d.get_io$$client$$d$$valid()&&!dr?std::optional{grantBits}:std::nullopt;
        heldRequest=d.get_io$$line$$a$$valid()&&!lr?std::optional{requestBits}:std::nullopt;
        heldProbe=d.get_io$$client$$b$$valid()&&!br?std::optional{probeBits}:std::nullopt;
        if(av&&d.get_io$$client$$a$$ready()){check(!live.count(a.source),"Acquire source reused");a.error=denyAddress&&a.address==*denyAddress;live[a.source]=a;requests.pop_front();++accepted;peak=std::max(peak,unsigned(live.size()));}
        if(ev&&d.get_io$$client$$e$$ready()){auto ack=e.front();auto q=live.at(ack.source);if(!q.error){cache[q.address]=q.words;dirty[q.address]=false;}live.erase(ack.source);e.pop_front();++finished;}
        if(cv&&d.get_io$$client$$c$$ready()){++cBeats;unsigned length=cp.opcode==5||cp.opcode==7?8:1;if(++c.front().beat==length)c.pop_front();}
        if(d.get_io$$client$$b$$valid()&&br){
            uint64_t address=d.get_io$$client$$b$$bits$$address();unsigned src=d.get_io$$client$$b$$bits$$source();
            check(d.get_io$$client$$b$$bits$$opcode()==6&&d.get_io$$client$$b$$bits$$size()==6,"bad Probe framing");
            bool hit=cache.count(address),data=hit&&dirty[address];Line words{};if(hit)words=cache[address];
            c.push_back({address,src,data?5U:4U,hit?1U:5U,0,words});cache.erase(address);dirty.erase(address);++probes;
        }
        if(d.get_io$$client$$d$$valid()&&dr){
            unsigned op=d.get_io$$client$$d$$bits$$opcode(),src=d.get_io$$client$$d$$bits$$source();
            if(op==6){check(releasing&&src==4,"ReleaseAck lacks owner");cache.erase(*releasing);dirty.erase(*releasing);releasing.reset();++releases;}
            else{
                check(op==5&&live.count(src),"Grant lacks source owner");auto& q=live.at(src);unsigned sink=d.get_io$$client$$d$$bits$$sink();
                check(q.beat<8,"duplicate Grant beat");if(q.beat==0){for(const auto& [other,entry]:live)if(other!=src&&entry.beat)check(entry.sink!=sink,"Grant sink reused before E");q.sink=sink;}check(q.sink==sink&&d.get_io$$client$$d$$bits$$size()==6,"Grant metadata changed");
                check(bool(d.get_io$$client$$d$$bits$$denied())==q.error&&bool(d.get_io$$client$$d$$bits$$corrupt())==q.error,"Grant error mismatch");
                uint64_t got=d.get_io$$client$$d$$bits$$data();if(!q.error)check(got==(expected(q.address+8*q.beat)^(inject?1ULL:0ULL)),"independent Grant data mismatch");
                q.words[q.beat]=got;if(++q.beat==8){e.push_back({sink,src});++grants;}
            }
        }
        if(d.get_io$$line$$a$$valid()&&lr){
            uint64_t address=d.get_io$$line$$a$$bits$$address();unsigned src=d.get_io$$line$$a$$bits$$source(),op=d.get_io$$line$$a$$bits$$opcode();
            check(d.get_io$$line$$a$$bits$$size()==6&&d.get_io$$line$$a$$bits$$mask()==255&&(address&63)==0,"backing request is not a full aligned line");
            if(op==4||!write){check(!held||held->source!=src,"backing source reused while D held");for(const auto& reply:pending)check(reply.source!=src,"backing source reused before response");}
            if(op==4){++readGets;pending.push_back({address,src,0,false,bool(denyAddress&&address==*denyAddress),cycle+15+(src==0?12:0)});}
            else{
                check(op==0,"unsupported backing opcode");if(!write)write=CPacket{address,src,0,0};
                check(write->address==address&&write->source==src,"backing write interleaved");
                write->words[write->beat++]=d.get_io$$line$$a$$bits$$data();
                if(write->beat==8){for(unsigned b=0;b<8;++b){check(write->words[b]==expected(address+8*b),"independent writeback data mismatch");memory[address+8*b]=write->words[b];}pending.push_back({address,src,0,true,false,cycle+3});write.reset();++writes;}
            }
        }
        if(held&&d.get_io$$line$$d$$ready()){if(held->write||++held->beat==8)held.reset();}
        if(upper&&!upperAccepted&&d.get_io$$upstream$$request$$ready())upperAccepted=true;
        if(dataResponse&&d.get_io$$downstream$$response$$ready())dataResponse.reset();
        if(d.get_io$$downstream$$request$$valid()&&ur){check(!dataResponse,"downstream response ownership overflow");check(!d.get_io$$downstream$$request$$bits$$write(),"unexpected downstream write");dataResponse=value(d.get_io$$downstream$$request$$bits$$address());}
        if(d.get_io$$upstream$$response$$valid()){check(upper&&upperAccepted&&!d.get_io$$upstream$$response$$bits$$error()&&d.get_io$$upstream$$response$$bits$$data()==expected(*upper),"independent DMA probe/read mismatch");upper.reset();upperAccepted=false;++upperDone;}
        ++cycle;
    }
    template<class F>void until(F f,const char* message){unsigned n=0;while(!f()){check(++n<2000,message);tick();}}
    void fill(uint64_t a,unsigned source=0){unsigned goal=finished+1;acquire(a,source);until([&]{return finished==goal;},"Acquire did not complete");}
};
static void exerciseDispatch(bool inject) {
    Test t;
    using Item=std::pair<unsigned,uint64_t>;
    std::deque<uint64_t> inputs[2];std::deque<Item> expected;
    std::optional<std::array<uint64_t,10>> held;
    unsigned direct=0,spill=0,bothQueued=0,fullStalls=0;
    auto step=[&](bool ready) {
        const bool empty=expected.empty(),both=!inputs[0].empty()&&!inputs[1].empty();
        const uint64_t seed0=inputs[0].empty()?0:inputs[0].front(),seed1=inputs[1].empty()?0:inputs[1].front();
        t.d.set_io$$dispatchOffer_0(!inputs[0].empty());t.d.set_io$$dispatchOffer_1(!inputs[1].empty());
        t.d.set_io$$dispatchSeed_0(seed0);t.d.set_io$$dispatchSeed_1(seed1);t.d.set_io$$dispatchReady(ready);t.tick();
        unsigned accepted=0;
        if(t.d.get_io$$dispatchAccepted_0()){check(!inputs[0].empty(),"dispatch input0 ghost");expected.push_back({0,seed0});inputs[0].pop_front();++accepted;}
        if(t.d.get_io$$dispatchAccepted_1()){check(!inputs[1].empty(),"dispatch input1 ghost");expected.push_back({1,seed1});inputs[1].pop_front();++accepted;}
        check(accepted<=1,"dispatch accepted two origins in one cycle");
        const bool valid=t.d.get_io$$dispatchValid();
        std::array<uint64_t,10> payload{};
        if(valid)payload={t.d.get_io$$dispatchTag(),t.d.get_io$$dispatchAddress(),
            t.d.get_io$$dispatchWords_0(),t.d.get_io$$dispatchWords_1(),t.d.get_io$$dispatchWords_2(),t.d.get_io$$dispatchWords_3(),
            t.d.get_io$$dispatchWords_4(),t.d.get_io$$dispatchWords_5(),t.d.get_io$$dispatchWords_6(),t.d.get_io$$dispatchWords_7()};
        if(held)check(valid&&payload==*held,"dispatch stalled offer changed after spill");
        if(valid){check(!expected.empty(),"dispatch output without origin");auto [tag,seed]=expected.front();
            check(payload[0]==tag&&payload[1]==(seed<<6),"dispatch origin/address mismatch");
            for(unsigned i=0;i<8;++i)check(payload[i+2]==((seed+i)^uint64_t(inject)),"dispatch independent payload mismatch");}
        direct+=empty&&accepted&&valid&&ready;spill+=empty&&accepted&&valid&&!ready;
        bothQueued+=empty&&both&&accepted&&!valid;fullStalls+=expected.size()==2&&!ready&&!accepted;
        held=valid&&!ready?std::optional{payload}:std::nullopt;
        if(valid&&ready)expected.pop_front();check(expected.size()<=2,"dispatch queue overflow");
    };
    inputs[0].push_back(0x100);step(true);
    inputs[0].push_back(0x200);step(false);
    inputs[0].push_back(0x300);inputs[1].push_back(0x400);step(false);step(false);step(false);
    for(unsigned n=0;n<12;++n)step(true);
    check(expected.empty()&&inputs[0].empty()&&inputs[1].empty(),"dispatch first batch did not drain");
    inputs[0].push_back(0x500);inputs[1].push_back(0x600);step(true);
    for(unsigned n=0;n<8;++n)step(true);
    inputs[0].push_back(0x700);step(false);
    t.d.set_io$$dispatchOffer_0(0);t.d.set_io$$dispatchOffer_1(0);t.resetEpoch();expected.clear();held.reset();step(true);
    inputs[1].push_back(0x800);step(true);step(true);
    check(direct&&spill&&bothQueued&&fullStalls&&expected.empty(),"dispatch mode witnesses missing");
    std::cout<<"HOME_WRITE_DISPATCH_PASS direct="<<direct<<" spill="<<spill<<" both_queued="<<bothQueued<<" full_stalls="<<fullStalls<<" reset=1\n";
}
int main(int argc,char**argv){try{
    exerciseDispatch(argc>1&&std::string(argv[1])=="--inject-dispatch");
    Test t;std::string arg=argc>1?argv[1]:"";t.inject=arg=="--inject-data";t.badSink=arg=="--bad-sink";
#ifdef COMPACT_TAG_TEST
    Test aliases; aliases.fill(base); aliases.modify(base);
    const uint64_t highAlias = base | (1ULL << 40);
    aliases.upper = highAlias;
    aliases.until([&]{ return aliases.upperDone == 1; }, "high-alias DMA failed bypass");
    check(aliases.probes == 0 && aliases.cache.count(base), "high-alias DMA probed low owner");
    aliases.upper = base;
    aliases.until([&]{ return aliases.upperDone == 2; }, "low dirty owner lost after high alias");
    check(aliases.probes == 1, "low dirty owner was not preserved");
    aliases.fill(base + 4096); aliases.modify(base + 4096); aliases.release(base + 4096);
    aliases.until([&]{ return aliases.releases == 1; }, "high-side4GiB release failed");
    if (arg == "--bad-release-aperture") {
        aliases.c.push_back({highAlias, 7, 6, 1, 0, {}});
        for (unsigned n=0; n<100; ++n) aliases.tick();
        throw std::runtime_error("invalid aperture Release was not rejected");
    }
    if (arg == "--bad-aperture") {
        aliases.acquire(highAlias, 0);
        for (unsigned n=0; n<100; ++n) aliases.tick();
        throw std::runtime_error("invalid aperture Acquire was not rejected");
    }
#endif
    t.fill(base);t.fill(base+64);t.modify(base);
    unsigned start=t.finished;for(unsigned i=0;i<HOME_ENTRIES;++i)t.acquire(base+128+64*i,i);
    t.allowD=false;t.allowE=false;
    t.until([&]{return t.d.get_io$$client$$d$$valid();},"no stalled Grant offered");
    t.release(base);unsigned oldWrites=t.writes;
    if(HOME_ENTRIES>1)t.until([&]{return t.writes>oldWrites;},"release writeback blocked by held Grant");
    t.allowD=true;
    if(HOME_ENTRIES>1)t.until([&]{return t.releases==1&&t.grants>=start+HOME_ENTRIES;},"ReleaseAck blocked by outstanding E");
    t.allowE=true;t.until([&]{return t.finished==start+HOME_ENTRIES&&t.releases==1;},"held work failed to drain");
    check(t.peak>=HOME_ENTRIES,"home did not expose configured Acquire capacity");
    t.modify(base+64);t.holdB=true;t.upper=base+64;
    t.until([&]{return t.d.get_io$$client$$b$$valid();},"DMA failed to probe owned line");
    t.release(base+64);t.holdB=false;
    t.until([&]{return t.upperDone==1&&t.releases==2;},"same-victim probe/release deadlock");
    t.modify(base+128);t.upper=base+128;
    t.until([&]{return t.upperDone==2;},"dirty probe writeback did not complete");
    t.denyAddress=base+448;t.fill(base+448);check(!t.cache.count(base+448),"denied Grant installed owner");
    t.denyAddress.reset();t.fill(base+448);
    check(t.requests.empty()&&t.live.empty()&&t.c.empty()&&t.e.empty()&&!t.releasing&&t.pending.empty()&&!t.held&&!t.write&&!t.dataResponse&&t.accepted==t.grants&&t.accepted==t.finished,"lost/duplicate ownership at drain");
    std::cout<<"HOME_MSHR_PASS entries="<<HOME_ENTRIES<<" peak="<<t.peak<<" acquires="<<t.accepted<<" finished="<<t.finished<<" releases="<<t.releases<<" writes="<<t.writes<<" probes="<<t.probes<<" cycles="<<t.cycle<<"\n";
    t.allowD=false;t.allowE=false;t.acquire(base+640,0);
    t.until([&]{return t.d.get_io$$client$$d$$valid();},"no live Grant for reset case");
    check(!t.live.empty(),"reset case lacked ownership");t.resetEpoch();t.fill(base+640);
    check(t.live.empty()&&t.cache.count(base+640),"post-reset owner did not complete");
    std::cout<<"HOME_RESET_PASS coordinated_downstream_flush=1\n";
    if(HOME_ENTRIES>1) {
        Test quota;quota.fill(base);quota.fill(base+64);quota.fill(base+128);
        quota.modify(base+64);quota.modify(base+128);
        const unsigned beforeReads=quota.readGets,beforeFinished=quota.finished;
        // Offer the victim with the Acquire, so the new idle direct-fill path
        // must enqueue behind an already admissible release, not withdraw a dispatched read.
        quota.release(base+64);
        quota.acquire(base+192,0);
        quota.until([&]{return quota.accepted==beforeFinished+1;},"quota Acquire acceptance");
        quota.until([&]{return quota.releases==1;},"first release priority drain");
        check(quota.readGets==beforeReads,"new refill overtook offered victim writeback");
        quota.release(base+128);
        quota.until([&]{return quota.readGets>beforeReads||quota.releases==2;},"bounded release priority made no progress");
        check(quota.readGets==beforeReads+1&&quota.releases==1,"second release starved a refill after its one-release quota");
        quota.until([&]{return quota.releases==2&&quota.finished==beforeFinished+1;},"quota work did not drain");
        std::cout<<"HOME_RELEASE_QUOTA_PASS yields=1 forced_refill_before_second_release_ack=1\n";
    }
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<"\n";return 1;}}
