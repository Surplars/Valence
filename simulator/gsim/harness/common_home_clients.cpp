#include "CommonHomeClientsGsim.h"
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <iostream>
#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>
#ifndef WHOLE_GRANT
#define WHOLE_GRANT 0
#endif
template<class> struct SetterArray;
template<class T, size_t N> struct SetterArray<void (SCommonHomeClientsGsim::*)(const T (&)[N])> { using Type = T[N]; };
#define CG(i, field) (d.get_io$$clients$$##field()[i])
#define CS(i, field, value) do { static SetterArray<decltype(&SCommonHomeClientsGsim::set_io$$clients$$##field)>::Type values{}; values[i]=(value); d.set_io$$clients$$##field(values); } while (0)
#define GG(i, field) (d.get_io$$grants$$##field()[i])
#define GS(i, field, value) do { static SetterArray<decltype(&SCommonHomeClientsGsim::set_io$$grants$$##field)>::Type values{}; values[i]=(value); d.set_io$$grants$$##field(values); } while (0)
static void check(bool yes, const char* message) { if (!yes) throw std::runtime_error(message); }
using Line = std::array<uint64_t, 8>;
static constexpr uint64_t base = 0x80010000ULL;
static uint64_t initial(uint64_t a) { return 0x8135792468000000ULL ^ a; }
struct Acquire { uint64_t address=0; unsigned source=0, beat=0, sink=0; Line words{}; };
struct Packet { uint64_t address=0; unsigned source=0, opcode=0, param=0, beat=0; Line words{}; };
struct Ack { unsigned client, source, sink; };
struct Reply { uint64_t address; unsigned source, beat=0; bool write=false; uint64_t due; Line words{}; };
struct Test {
    SCommonHomeClientsGsim d;
    uint64_t cycle=0;
    std::map<uint64_t,uint64_t> memory, reference;
    std::map<uint64_t,Line> cache[2];
    std::map<uint64_t,bool> dirty[2];
    std::deque<Acquire> requests[2];
    std::map<unsigned,Acquire> live;
    std::deque<Packet> c[2];
    std::vector<Ack> e;
    std::vector<Reply> pending;
    std::optional<Reply> held;
    std::optional<Packet> write;
    std::optional<uint64_t> releasing[2], upper, dataResponse;
    bool allowD[2]={true,true}, allowG[2]={true,true}, holdB[2]={false,false};
    bool allowE=true, reverseE=false, allowMemory=true, drain=false, upperAccepted=false;
    bool inject=false, badClient=false;
    unsigned accepted=0, grants=0, finished=0, releases=0, writes=0, writeAcks=0, probes=0;
    unsigned peak=0, peakWrites=0, readGets=0, simultaneousGrantAck=0, upperDone=0, reverseAcks=0;
    unsigned grantStalls=0, probeStalls=0, drainBlocked=0, simultaneousAE=0;
    std::optional<std::array<uint64_t,8>> heldD[2];
    std::optional<std::array<uint64_t,4>> heldB[2];
    std::optional<std::array<uint64_t,13>> heldG[2];
    std::optional<std::array<uint64_t,7>> heldA;
    uint64_t value(uint64_t a) const { auto p=memory.find(a); return p==memory.end()?initial(a):p->second; }
    uint64_t expected(uint64_t a) const { auto p=reference.find(a); return p==reference.end()?initial(a):p->second; }
    Test() {
        d.set_reset(1); d.set_io$$drainRequest(0);
        d.set_io$$upstream$$request$$valid(0); d.set_io$$downstream$$response$$valid(0);
        for (unsigned i=0;i<2;++i) { CS(i,a$$valid,0); CS(i,c$$valid,0); CS(i,e$$valid,0); }
        d.set_io$$line$$d$$valid(0); d.set_io$$line$$b$$valid(0);
        d.set_io$$line$$c$$ready(0); d.set_io$$line$$e$$ready(0);
        d.step(); d.step(); d.set_reset(0);
    }
    void acquire(unsigned i, uint64_t address, unsigned source=0) { requests[i].push_back({address,source}); }
    void modify(unsigned i, uint64_t address) {
        check(cache[i].count(address), "modify lacks software client owner");
        for(unsigned b=0;b<8;++b) { cache[i][address][b]=0xfedcba9800000000ULL ^ address ^ (uint64_t(i)<<40) ^ b;
            reference[address+8*b]=cache[i][address][b]; }
        dirty[i][address]=true;
    }
    void release(unsigned i, uint64_t address) {
        check(!releasing[i] && cache[i].count(address), "release lacks software client owner");
        releasing[i]=address;
        // Both independent clients intentionally use voluntary Release source zero.
        c[i].push_back({address,0,dirty[i][address]?7U:6U,1,0,cache[i][address]});
    }
    void grant(unsigned i,unsigned source,unsigned sink,unsigned beat,uint64_t got) {
        unsigned key=8*i+source;
        check(live.count(key), "Grant routed to wrong client/source");
        auto& q=live.at(key);
        check(q.beat==beat && beat<8, "Grant repeated or interleaved a beat");
        if(!beat) {
            for(auto& [other,entry]:live) if(other!=key && entry.beat) check(entry.sink!=sink,"Grant sink reused across clients");
            q.sink=sink;
        }
        check(q.sink==sink,"Grant changed its global sink");
        check(got==(expected(q.address+8*beat) ^ uint64_t(inject)),"independent Grant data mismatch");
        q.words[q.beat++]=got;
        if(q.beat==8) { e.push_back({i,source,sink}); ++grants; }
    }
    void tick() {
        if(!held && allowMemory) for(auto it=pending.rbegin();it!=pending.rend();++it) if(it->due<=cycle) {
            held=*it; pending.erase(std::next(it).base()); break;
        }
        const bool ev=allowE && !e.empty();
        const unsigned ei=reverseE && ev ? unsigned(e.size()-1) : 0;
        const Ack ack=ev?e[ei]:Ack{0,0,0};
        const unsigned ackClient=badClient && ev ? 1-ack.client : ack.client;
        const bool lr=cycle%5!=1;
        bool av[2],cv[2],dr[2],gr[2],br[2]; Acquire a[2]; Packet cp[2];
        for(unsigned i=0;i<2;++i) {
            av[i]=!requests[i].empty(); cv[i]=!c[i].empty();
            a[i]=av[i]?requests[i].front():Acquire{}; cp[i]=cv[i]?c[i].front():Packet{};
            dr[i]=allowD[i] && cycle%7!=3; gr[i]=allowG[i] && cycle%7!=3;
            br[i]=!holdB[i] && !releasing[i];
            CS(i,a$$valid,av[i]); CS(i,a$$bits$$opcode,6); CS(i,a$$bits$$param,1);
            CS(i,a$$bits$$address,a[i].address); CS(i,a$$bits$$size,6); CS(i,a$$bits$$source,a[i].source);
            CS(i,a$$bits$$mask,255); CS(i,a$$bits$$data,0); CS(i,a$$bits$$corrupt,0);
            CS(i,d$$ready,dr[i]); CS(i,b$$ready,br[i]); GS(i,ready,gr[i]);
            CS(i,c$$valid,cv[i]); CS(i,c$$bits$$opcode,cp[i].opcode); CS(i,c$$bits$$param,cp[i].param);
            CS(i,c$$bits$$address,cp[i].address); CS(i,c$$bits$$size,6); CS(i,c$$bits$$source,cp[i].source);
            CS(i,c$$bits$$data,cp[i].words[cp[i].beat]); CS(i,c$$bits$$corrupt,0);
            CS(i,e$$valid,ev && ackClient==i); CS(i,e$$bits$$sink,ack.sink);
        }
        d.set_io$$drainRequest(drain);
        d.set_io$$line$$a$$ready(lr); d.set_io$$line$$d$$valid(bool(held));
        d.set_io$$line$$d$$bits$$opcode(held && held->write?0:1); d.set_io$$line$$d$$bits$$param(0);
        d.set_io$$line$$d$$bits$$source(held?held->source:0); d.set_io$$line$$d$$bits$$sink(0);
        d.set_io$$line$$d$$bits$$size(6); d.set_io$$line$$d$$bits$$denied(0); d.set_io$$line$$d$$bits$$corrupt(0);
        d.set_io$$line$$d$$bits$$data(held && !held->write?value(held->address+8*held->beat):0);
        d.set_io$$upstreamRequestCpu(0);
        d.set_io$$upstream$$request$$valid(bool(upper) && !upperAccepted);
        d.set_io$$upstream$$request$$bits$$address(upper.value_or(0)); d.set_io$$upstream$$request$$bits$$size(3);
        d.set_io$$upstream$$request$$bits$$write(0); d.set_io$$upstream$$request$$bits$$data(0);
        d.set_io$$upstream$$request$$bits$$mask(255); d.set_io$$upstream$$request$$bits$$atomic(0);
        d.set_io$$upstream$$request$$bits$$atomicOp(0); d.set_io$$upstream$$request$$bits$$virtualized(0);
        d.set_io$$upstream$$request$$bits$$uncached(0); d.set_io$$upstream$$response$$ready(1);
        d.set_io$$downstream$$request$$ready(1); d.set_io$$downstream$$response$$valid(bool(dataResponse));
        d.set_io$$downstream$$response$$bits$$data(dataResponse.value_or(0));
        d.set_io$$downstream$$response$$bits$$error(0); d.set_io$$downstream$$response$$bits$$pageFault(0);
        d.step();
        bool firedGrant=false, firedRelease=false, firedAcquire=false;
        for(unsigned i=0;i<2;++i) {
            std::array<uint64_t,8> db{CG(i,d$$bits$$opcode),CG(i,d$$bits$$source),CG(i,d$$bits$$sink),
                CG(i,d$$bits$$size),CG(i,d$$bits$$denied),CG(i,d$$bits$$corrupt),CG(i,d$$bits$$data),CG(i,d$$bits$$param)};
            std::array<uint64_t,4> bb{CG(i,b$$bits$$address),CG(i,b$$bits$$source),CG(i,b$$bits$$opcode),CG(i,b$$bits$$param)};
            if(heldD[i]) check(CG(i,d$$valid) && db==*heldD[i],"D owner or payload changed under stall");
            if(heldB[i]) check(CG(i,b$$valid) && bb==*heldB[i],"B client or payload changed under stall");
            heldD[i]=CG(i,d$$valid) && !dr[i]?std::optional{db}:std::nullopt;
            heldB[i]=CG(i,b$$valid) && !br[i]?std::optional{bb}:std::nullopt;
            grantStalls+=bool(heldD[i]); probeStalls+=bool(heldB[i]);
            if(av[i] && CG(i,a$$ready)) {
                unsigned key=8*i+a[i].source; check(!live.count(key),"Acquire reused live client/source");
                live[key]=a[i]; requests[i].pop_front(); ++accepted; firedAcquire=true; peak=std::max(peak,unsigned(live.size()));
            }
            if(cv[i] && CG(i,c$$ready)) { unsigned length=cp[i].opcode==5 || cp[i].opcode==7?8:1;
                if(++c[i].front().beat==length) c[i].pop_front(); }
            if(CG(i,b$$valid) && br[i]) {
                uint64_t address=bb[0]; bool hit=cache[i].count(address), data=hit && dirty[i][address];
                check(bb[2]==6 && CG(i,b$$bits$$size)==6,"bad Probe framing");
                Line words{}; if(hit) words=cache[i][address];
                c[i].push_back({address,unsigned(bb[1]),data?5U:4U,hit?1U:5U,0,words});
                cache[i].erase(address); dirty[i].erase(address); ++probes;
            }
            if(CG(i,d$$valid) && dr[i]) {
                if(db[0]==6) {
                    check(releasing[i] && db[1]==0,"ReleaseAck routed to wrong client/source");
                    check(writeAcks || !dirty[i][*releasing[i]],"dirty ReleaseAck before backing completion");
                    cache[i].erase(*releasing[i]); dirty[i].erase(*releasing[i]); releasing[i].reset(); ++releases;
                    firedRelease=true;
                } else {
                    check(!WHOLE_GRANT && db[0]==5 && db[3]==6 && db[4]==0 && db[5]==0 && db[7]==0,"bad Grant framing");
                    auto key=8*i+unsigned(db[1]); check(live.count(key),"standard Grant lacks source owner");
                    grant(i,db[1],db[2],live.at(key).beat,db[6]); firedGrant=true;
                }
            }
#if WHOLE_GRANT
            unsigned _BitInt(512) gd=GG(i,bits$$data);
            std::array<uint64_t,13> gb{GG(i,bits$$source),GG(i,bits$$sink),GG(i,bits$$cap),GG(i,bits$$denied),GG(i,bits$$corrupt)};
            for(unsigned b=0;b<8;++b) gb[5+b]=uint64_t(gd>>(64*b));
            if(heldG[i]) check(GG(i,valid) && gb==*heldG[i],"whole Grant client or payload changed under stall");
            heldG[i]=GG(i,valid) && !gr[i]?std::optional{gb}:std::nullopt; grantStalls+=bool(heldG[i]);
            if(GG(i,valid) && gr[i]) {
                check(gb[2]==0 && !gb[3] && !gb[4],"bad whole Grant framing");
                for(unsigned b=0;b<8;++b) grant(i,gb[0],gb[1],b,gb[5+b]);
                firedGrant=true;
            }
#else
            check(!GG(i,valid),"whole Grant unexpectedly active");
#endif
        }
        simultaneousGrantAck+=firedGrant && firedRelease;
        if(ev && CG(ackClient,e$$ready)) {
            simultaneousAE+=firedAcquire;
            check(ackClient==ack.client,"wrong client E accepted");
            unsigned key=8*ack.client+ack.source; auto q=live.at(key);
            check(q.beat==8 && q.sink==ack.sink,"E lost full Grant owner");
            cache[ack.client][q.address]=q.words; dirty[ack.client][q.address]=false;
            live.erase(key); e.erase(e.begin()+ei); ++finished; reverseAcks+=reverseE;
        }
        std::array<uint64_t,7> ab{d.get_io$$line$$a$$bits$$opcode(),d.get_io$$line$$a$$bits$$source(),
            d.get_io$$line$$a$$bits$$address(),d.get_io$$line$$a$$bits$$size(),d.get_io$$line$$a$$bits$$mask(),
            d.get_io$$line$$a$$bits$$data(),d.get_io$$line$$a$$bits$$param()};
        if(heldA) check(d.get_io$$line$$a$$valid() && ab==*heldA,"backing A changed under stall");
        heldA=d.get_io$$line$$a$$valid() && !lr?std::optional{ab}:std::nullopt;
        if(d.get_io$$line$$a$$valid() && lr) {
            auto address=ab[2]; unsigned source=ab[1],op=ab[0];
            check(ab[3]==6 && ab[4]==255 && !(address&63),"backing request framing");
            if(op==4 || !write) { check(!held || held->source!=source,"backing source reused while D held");
                for(auto& q:pending) check(q.source!=source,"backing source reused before completion"); }
            if(op==4) {
                check(!write || write->address!=address,"refill overtook partial dirty writeback");
                check(!held || !held->write || held->address!=address,"refill overtook held write completion");
                for(auto& q:pending) check(!q.write || q.address!=address,"refill overtook true dirty write completion");
                pending.push_back({address,source,0,false,cycle+19+(source==0?11:0)}); ++readGets;
            } else {
                check(op==0,"unsupported backing opcode"); if(!write) write=Packet{address,source,0,0};
                check(write->address==address && write->source==source,"backing write interleaved");
                write->words[write->beat++]=ab[5];
                if(write->beat==8) {
                    for(unsigned b=0;b<8;++b) check(write->words[b]==expected(address+8*b),"independent writeback data mismatch");
                    pending.push_back({address,source,0,true,cycle+25,write->words}); write.reset(); ++writes;
                }
            }
        }
        if(held && d.get_io$$line$$d$$ready()) {
            if(held->write) { for(unsigned b=0;b<8;++b) memory[held->address+8*b]=held->words[b]; ++writeAcks; held.reset(); }
            else if(++held->beat==8) held.reset();
        }
        unsigned w=held && held->write; for(auto& q:pending) w+=q.write; peakWrites=std::max(peakWrites,w);
        if(upper && !upperAccepted && d.get_io$$upstream$$request$$ready()) upperAccepted=true;
        if(dataResponse && d.get_io$$downstream$$response$$ready()) dataResponse.reset();
        if(d.get_io$$downstream$$request$$valid()) { check(!dataResponse,"scalar downstream ownership overflow");
            dataResponse=value(d.get_io$$downstream$$request$$bits$$address()); }
        if(d.get_io$$upstream$$response$$valid()) { check(upper && upperAccepted && d.get_io$$upstream$$response$$bits$$data()==expected(*upper),"native owner lookup returned stale data");
            upper.reset(); upperAccepted=false; ++upperDone; }
        if(drain && !live.empty()) { check(!d.get_io$$drainDone(),"drain completed with live Acquire/E owner"); ++drainBlocked; }
        if(drain && (write || !pending.empty() || held || releasing[0] || releasing[1] || !c[0].empty() || !c[1].empty())) {
            check(!d.get_io$$drainDone(),"drain completed before actual write/C completion"); ++drainBlocked;
        }
        ++cycle;
    }
    template<class F> void until(F f,const char* message) { unsigned n=0; while(!f()) { check(++n<3000,message); tick(); } }
    void fill(unsigned i,uint64_t address,unsigned source=0) { auto goal=finished+1; acquire(i,address,source); until([&]{return finished==goal;},"Acquire failed to complete"); }
    void quiesce() { until([&]{return live.empty() && requests[0].empty() && requests[1].empty() && !releasing[0] && !releasing[1] && c[0].empty() && c[1].empty() && pending.empty() && !held && !write;},"ownership did not quiesce"); }
};
// Replays the boot direction with delayed E, then exercises E/Acquire edges.
// Native four-state cold-reset validation lives in common_home_arbiter.sv; GSIM
// validates the full Home owner/sink lifecycle without claiming X-state coverage.
static void startupAndSinkReuse() {
    Test t; t.allowE=false;
    t.acquire(1,base+4096,0);
    t.until([&]{return t.grants==1;},"client1-first Grant failed");
    check(t.e.size()==1 && t.e[0].client==1,"first Grant did not preserve client1");
    unsigned firstSink=t.e[0].sink;
    for(unsigned n=0;n<80;++n)t.tick();
    check(t.accepted==1 && t.grants==1 && t.finished==0 && t.live.size()==1,
        "delayed first E lost or repeated its Grant owner");
    // E frees sink0 while A allocates the other already-free sink in one cycle.
    t.acquire(0,base+4160,0);t.allowE=true;t.tick();
    check(t.accepted==2 && t.finished==1 && t.simultaneousAE==1,"first simultaneous A/E failed");
    t.allowE=false;t.until([&]{return t.grants==2;},"second startup Grant failed");
    check(t.e.size()==1 && t.e[0].client==0 && t.e[0].sink!=firstSink,
        "same-edge A/E corrupted the other sink owner");
    // Reuse the old sink while the other client's E completes on that edge.
    t.acquire(1,base+4224,0);t.allowE=true;t.tick();
    check(t.accepted==3 && t.finished==2 && t.simultaneousAE==2,"sink reuse A/E edge failed");
    t.allowE=false;t.until([&]{return t.grants==3;},"reused startup sink Grant failed");
    check(t.e.size()==1 && t.e[0].client==1 && t.e[0].sink==firstSink,"reused global sink was not preserved");
    t.allowE=true;t.quiesce();
    // With both sinks live, held A must not overwrite a sink on its E edge.
    // The released sink becomes eligible next cycle, alongside the other E.
    t.allowE=false;t.acquire(0,base+4288,0);t.acquire(1,base+4352,0);
    t.until([&]{return t.grants==5;},"dual source-zero lifecycle Grants failed");
    check(t.e.size()==2 && t.e[0].sink!=t.e[1].sink,"dual lifecycle sinks collapsed");
    t.reverseE=true;Ack released=t.e.back();
    t.acquire(released.client,base+4416,1);t.allowE=true;t.tick();
    check(t.accepted==5 && t.finished==4,"full Home overwrote a sink before E release");
    t.tick();
    check(t.accepted==6 && t.finished==5 && t.simultaneousAE==3,"next-edge released sink allocation failed");
    t.allowE=false;t.until([&]{return t.grants==6;},"post-release allocation Grant failed");
    check(t.e.size()==1 && t.e[0].client==released.client && t.e[0].source==1 && t.e[0].sink==released.sink,
        "reverse E/reallocation lost client, source, or sink");
    t.allowE=true;t.quiesce();
    check(t.finished==6 && t.peak==2,"startup lifecycle ownership accounting incomplete");
    std::cout<<"COMMON_HOME_STARTUP_PASS whole="<<WHOLE_GRANT<<" first_client=1 delayed_e=80 same_edge_a_e="
        <<t.simultaneousAE<<" acquires="<<t.accepted<<" reverse_e="<<t.reverseAcks<<" peak_acquire="<<t.peak<<" cycles="<<t.cycle<<"\n";
}
int main(int argc,char** argv) { try {
    startupAndSinkReuse();
    const std::string arg=argc>1?argv[1]:"";
    Test t; t.inject=arg=="--inject-data"; t.badClient=arg=="--bad-client-e";
    // Same client, distinct local sources: both owners survive held Grants and reverse E.
    t.allowE=false; t.allowD[0]=false; t.allowG[0]=false;
    t.acquire(0,base,0); t.acquire(0,base+64,1);
    t.until([&]{return t.accepted==2;},"same-client two-source capacity lost");
    for(unsigned n=0;n<80;++n)t.tick();
    check(t.live.size()==2 && !t.finished,"held Grant lost Acquire owner");
    t.allowD[0]=true; t.allowG[0]=true;
    t.until([&]{return t.grants==2;},"same-client two Grants failed");
    t.reverseE=true; t.allowE=true; t.quiesce();
    // Two clients with the same source zero, with late E and global sink uniqueness.
    unsigned before=t.finished; t.allowE=false;
    t.acquire(0,base+128,0); t.acquire(1,base+192,0);
    t.until([&]{return t.grants==before+2;},"same-source cross-client grants failed");
    check(t.live.count(0) && t.live.count(8),"client-local source zero collapsed");
    t.drain=true; for(unsigned n=0;n<9;++n)t.tick(); t.allowE=true; t.quiesce();
    t.tick(); check(t.d.get_io$$drainDone(),"drain did not finish after both E"); t.drain=false;
    // Dirty D-to-I handoff must wait for the true write response before any refill.
    uint64_t hand=base+256; t.fill(1,hand); t.modify(1,hand);
    unsigned oldProbes=t.probes, oldWrites=t.writes, oldDone=t.finished;
    t.acquire(0,hand); t.until([&]{return t.finished==oldDone+1;},"dirty D-to-I handoff deadlocked");
    check(t.probes==oldProbes+1 && t.writes==oldWrites+1 && !t.cache[1].count(hand) && t.cache[0].count(hand),"dirty D-to-I handoff witness missing");
    // A queued B may race a voluntary source-zero Release from its old owner.
    uint64_t race=base+320; t.fill(1,race); t.modify(1,race); t.holdB[1]=true;
    oldDone=t.finished; unsigned oldRelease=t.releases; t.acquire(0,race);
    t.until([&]{return t.d.get_io$$clients$$b$$valid()[1];},"handoff never offered B");
    t.release(1,race); t.holdB[1]=false;
    t.until([&]{return t.finished==oldDone+1 && t.releases==oldRelease+1;},"racing Release/Probe lost progress");
    // Both W owners and both M owners coexist, despite identical Release sources.
    uint64_t w0=base+384,w1=base+448; t.fill(0,w0);t.fill(1,w1);t.modify(0,w0);t.modify(1,w1);
    oldWrites=t.writes; oldRelease=t.releases; oldDone=t.finished;
    t.allowMemory=false; t.release(0,w0);t.release(1,w1);t.acquire(0,base+512,0);t.acquire(1,base+576,0);
    t.until([&]{return t.writes==oldWrites+2 && t.live.size()==2;},"independent M2 plus W2 capacity lost");
    check(t.peakWrites>=2 && t.releases==oldRelease,"writeback completed without backing responses");
    t.drain=true;for(unsigned n=0;n<13;++n)t.tick(); t.allowMemory=true;t.quiesce();t.tick();
    check(t.finished==oldDone+2 && t.releases==oldRelease+2 && t.d.get_io$$drainDone(),"M2/W2 drain failed");t.drain=false;
#if WHOLE_GRANT
    // A whole-line Grant held on client0 must not block an unrelated client1 D ReleaseAck.
    uint64_t heldVictim=base+640; t.fill(1,heldVictim); t.modify(1,heldVictim);
    oldDone=t.finished; oldRelease=t.releases; t.allowG[0]=false; t.acquire(0,base+704);
    t.until([&]{return t.d.get_io$$grants$$valid()[0];},"whole Grant not offered for independent D test");
    t.release(1,heldVictim);
    t.until([&]{return t.releases==oldRelease+1;},"held whole Grant blocked independent D ReleaseAck");
    check(t.finished==oldDone && t.d.get_io$$grants$$valid()[0],"independent ReleaseAck disturbed held whole Grant");
    t.allowG[0]=true;t.quiesce();
    // Hold both independent transports, then open them on exactly the same cycle.
    uint64_t simultaneousVictim=base+768;t.fill(1,simultaneousVictim);t.modify(1,simultaneousVictim);
    t.allowG[0]=false;t.allowD[1]=false;t.acquire(0,base+832);t.release(1,simultaneousVictim);
    t.until([&]{return t.d.get_io$$grants$$valid()[0] && t.d.get_io$$clients$$d$$valid()[1];},"independent Grant/D offers missing");
    t.allowG[0]=true;t.allowD[1]=true;t.quiesce();
    check(t.simultaneousGrantAck,"LineGrant and ReleaseAck never fired together");
#endif
    // Four different tags in one directory set, then exact-slot reuse after release.
    uint64_t set=base+1024;
    for(unsigned way=0;way<4;++way)t.fill(way%2,set+way*16384);
    for(unsigned way=0;way<4;++way)check(t.cache[way%2].count(set+way*16384),"four-way directory capacity lost");
    unsigned admitted=t.accepted; t.acquire(0,set+4*16384);
    for(unsigned n=0;n<20;++n)t.tick();check(t.accepted==admitted,"full four-way set over-admitted");
    t.modify(1,set+3*16384);t.release(1,set+3*16384);t.quiesce();
    check(t.cache[0].count(set+4*16384),"fourth-way eviction/reuse failed");
    // Native DMA/uncached owner lookup retains its original non-CPU policy.
    t.modify(0,hand); t.upper=hand;t.until([&]{return t.upperDone==1;},"native dirty owner lookup failed");
    check(t.accepted==t.grants && t.accepted==t.finished && t.peak==2 && t.grantStalls && t.probeStalls && t.reverseAcks && t.drainBlocked,"coverage or ownership accounting incomplete");
    std::cout<<"COMMON_HOME_CLIENTS_PASS whole="<<WHOLE_GRANT<<" geometry=1024x4x256 peak_acquire="<<t.peak<<" peak_writeback="<<t.peakWrites
        <<" acquires="<<t.accepted<<" releases="<<t.releases<<" writes="<<t.writes<<" probes="<<t.probes<<" reverse_e="<<t.reverseAcks
        <<" simultaneous_grant_ack="<<t.simultaneousGrantAck<<" grant_stalls="<<t.grantStalls<<" probe_stalls="<<t.probeStalls<<" drain_blocked="<<t.drainBlocked<<" cycles="<<t.cycle<<"\n";
    return 0;
} catch(const std::exception& e) { std::cerr<<e.what()<<"\n"; return 1; } }
