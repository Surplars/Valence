#include "PostedFrozenOverlapChainGsim.h"
#include "tagged_store_return_oracle.h"
#include <algorithm>
#include <cstring>
#include <iostream>
#include <optional>
#include <set>
#include <unordered_map>
#include <vector>
using namespace tagged_return_reference;
static void check(bool yes, const char* why) { require(yes, why); }
#define BOARD_DDR_BYTES 65536ULL
#define DDR_READ_CREDITS 4
#define DDR_READ_LATENCY 80
#define DDR_READ_BEAT_GAP 1
#include "board_ddr_multiid.h"
#ifndef TAGGED_STORE_RETURNS
#define TAGGED_STORE_RETURNS 0
#endif
static constexpr uint64_t ram = 0x80200000ULL, virt = 0x40000000ULL;
static std::string mutation;
static bool posted(const Operation& o) { return o.store && !o.virtualized; }
using Context = std::tuple<unsigned,uint64_t,unsigned,uint64_t,uint64_t,uint64_t>;
struct PostedRecord { Context context; unsigned ticket; bool acknowledged=false; };
struct Mmio { uint64_t due, data; };
struct Test {
    SPostedFrozenOverlapChainGsim d;
    Ledger ledger;
    std::map<unsigned,Token> cacheHandles;
    std::map<Token,PostedRecord> postedRecords;
    std::set<Token> sbCompleted;
    std::set<Context> contexts;
    uint64_t postedNew=0,postedJoin=0,postedAck=0,proofInput=0,proofOutput=0,proofChecked=0;
    uint64_t frozenChecked=0,overlapRead=0,overlapCapture=0;
    bool seal=false;

    DdrModel ddr;
    std::map<uint64_t,uint64_t> memory;
    std::optional<Operation> pending, dmaPending, dmaActive;
    std::set<Token> previous;
    std::deque<Mmio> local[2];
    std::optional<uint64_t> pteDue;
    std::optional<std::tuple<unsigned,uint64_t,bool,bool>> held;
    uint64_t cycle=1, qCount=0, cacheCount=0, cacheReturns=0, replies=0, completions=0, mutations=0, heldCycles=0, simultaneous=0;
    unsigned cancel=0, pmpCfg=0x1f;
    bool holdEnqueue=false, holdQueue=false, holdRequest=false, holdResponse=false, completionReady=true, flush=false, vmFlush=false;
    bool doMutation=false, pteRequestReady=false, localRequestReady[2]={false,false};
    static uint64_t initial(uint64_t address) { return 0xabcde98765432100ULL ^ (address * 0x100100101ULL); }
    static unsigned mask(const Operation& o) { return ((1u << (1u << o.size))-1) << (o.pa&7); }
    static uint64_t merge(uint64_t old, uint64_t value, unsigned lanes) {
        for(unsigned b=0;b<8;++b) if(lanes&(1u<<b)) old=(old&~(255ULL<<(8*b)))|(value&(255ULL<<(8*b)));
        return old;
    }
    void ok(bool yes, const std::string& why) { require(yes, "cycle="+std::to_string(cycle)+" "+why); }
    void corrupted() { ++mutations; std::cerr << "ACTUAL_CORRUPTION count=" << mutations << '\n'; }
    Test() {
        std::memset(&d,0,sizeof(d)); d.LOG_START=1; d.activateAll();
        for(unsigned a=0;a<65536;a+=8) memory[ram+a]=ddr.memory[a]=initial(ram+a);
        tick(true); tick(true); for(unsigned i=0;i<8;++i) tick();
        ok(d.get_io$$stable(),"authorization epoch never stabilized");
    }
    void drive() {
        Operation o=pending.value_or(Operation{});
        d.set_io$$start$$valid(bool(pending)); d.set_io$$parallel(o.parallel); d.set_io$$qualified(true);
        d.set_io$$start$$bits$$token$$index(o.token.index); d.set_io$$start$$bits$$token$$tag(o.token.generation);
        d.set_io$$start$$bits$$pc(0x1000+4*o.token.index); d.set_io$$start$$bits$$address(o.va);
        d.set_io$$start$$bits$$physicalAddress(o.pa); d.set_io$$start$$bits$$data(o.data);
        d.set_io$$start$$bits$$size(o.size); d.set_io$$start$$bits$$store(o.store);
        d.set_io$$start$$bits$$unsigned(true); d.set_io$$start$$bits$$atomic(false); d.set_io$$start$$bits$$atomicOp(0);
        d.set_io$$start$$bits$$forward$$valid(false); d.set_io$$start$$bits$$forward$$bits(0);
        d.set_io$$start$$bits$$accessDenied(false); d.set_io$$start$$bits$$virtualized(o.virtualized);
        d.set_io$$start$$bits$$precheckedLoad(o.prechecked); d.set_io$$start$$bits$$translationEpoch(o.epoch);
        d.set_io$$start$$bits$$canonicalStoreEpoch$$valid(o.frozen); d.set_io$$start$$bits$$canonicalStoreEpoch$$bits(o.epoch);
        d.set_io$$start$$bits$$frozenStoreProof$$valid(o.frozen);
        d.set_io$$start$$bits$$frozenStoreProof$$bits$$address(o.va);
        d.set_io$$start$$bits$$frozenStoreProof$$bits$$physicalAddress(o.pa);
        d.set_io$$start$$bits$$frozenStoreProof$$bits$$size(o.size);
        d.set_io$$start$$bits$$frozenStoreProof$$bits$$mask(mask(o));
        const bool proof=bool(pending)&&posted(o);
        d.set_io$$start$$bits$$postedProof$$valid(proof);
        d.set_io$$start$$bits$$postedProof$$bits$$token$$index(o.token.index);
        d.set_io$$start$$bits$$postedProof$$bits$$token$$tag(o.token.generation);
        d.set_io$$start$$bits$$postedProof$$bits$$epoch(d.get_io$$postedEpoch());
        d.set_io$$start$$bits$$postedProof$$bits$$address(o.pa);
        d.set_io$$start$$bits$$postedProof$$bits$$data(o.data << (8*(o.pa&7)));
        d.set_io$$start$$bits$$postedProof$$bits$$size(o.size);
        d.set_io$$start$$bits$$postedProof$$bits$$mask(mask(o));
        d.set_io$$start$$bits$$postedProof$$bits$$headAuthorized(proof);
        d.set_io$$start$$bits$$postedProof$$bits$$physicalPmpAllowed(proof);
        d.set_io$$start$$bits$$postedProof$$bits$$originalPhysical(proof);
        d.set_io$$start$$bits$$postedProof$$bits$$integerOrigin(proof);
        d.set_io$$start$$bits$$postedProof$$bits$$legacyPostedAccepted(false);
        d.set_io$$start$$bits$$postedProof$$bits$$finalChecked(false);
        d.set_io$$seal(seal);
        d.set_io$$cancel(cancel); d.set_io$$complete$$ready(completionReady);
        d.set_io$$vm$$satp((8ULL<<60)|0x100); d.set_io$$vm$$sum(false); d.set_io$$vm$$mxr(false);
        d.set_io$$vm$$dataPrivilege(1); d.set_io$$pmpCfg(pmpCfg); d.set_io$$pmpAddress((1ULL<<54)-1);
        d.set_io$$precheckFlush(vmFlush); d.set_io$$holdQueue(holdQueue); d.set_io$$holdEnqueue(holdEnqueue);
        d.set_io$$holdCacheRequest(holdRequest); d.set_io$$holdCacheResponse(holdResponse); d.set_io$$flushRequest(flush);
        pteRequestReady=!pteDue; d.set_io$$pte$$request$$ready(pteRequestReady); d.set_io$$pte$$response$$valid(pteDue&&*pteDue<=cycle);
        d.set_io$$pte$$response$$bits$$data(0); d.set_io$$pte$$response$$bits$$error(false);
#define LOCAL(N) localRequestReady[N]=local[N].empty(); d.set_io$$mmio##N##$$request$$ready(localRequestReady[N]); \
        d.set_io$$mmio##N##$$response$$valid(!local[N].empty()&&local[N].front().due<=cycle); \
        d.set_io$$mmio##N##$$response$$bits$$data(local[N].empty()?0:local[N].front().data); \
        d.set_io$$mmio##N##$$response$$bits$$error(false);
        LOCAL(0); LOCAL(1);
#undef LOCAL
        const auto dma=dmaPending.value_or(Operation{});
        d.set_io$$dma$$request$$valid(bool(dmaPending)); d.set_io$$dma$$response$$ready(true);
        d.set_io$$dma$$request$$bits$$address(dma.pa); d.set_io$$dma$$request$$bits$$write(dma.store);
        d.set_io$$dma$$request$$bits$$data(dma.data); d.set_io$$dma$$request$$bits$$size(3);
        d.set_io$$dma$$request$$bits$$mask(255); d.set_io$$dma$$request$$bits$$atomic(false);
        d.set_io$$dma$$request$$bits$$atomicOp(0); d.set_io$$dma$$request$$bits$$virtualized(false);
        d.set_io$$dma$$request$$bits$$precheckedLoad(false);d.set_io$$dma$$request$$bits$$translationEpoch(0);
        d.set_io$$dma$$request$$bits$$prefetchNextAllowed(false);d.set_io$$dma$$request$$bits$$uncached(false);
        ddr.drive(d,cycle);
    }
    void cacheReply(unsigned h, uint64_t value, bool error, bool pf) {
        ok(!ledger.cacheOrder.empty(),"cache response without accepted owner");
        ok(cacheHandles.count(h),"unknown or stale actual cache handle");
        const Token token=cacheHandles.at(h);
        auto& x=ledger.lives.at(token);
        ok(x.cache&&!x.cacheReply,"duplicate or unaccepted cache response");
        ok(!pf&&error==(x.op.fault==3),"cache architectural fault owner mismatch");
        if(!error) ok(value==(x.op.store?0:x.expectedBeat),"cache independent byte/owner mismatch");
        if(x.op.store) ok(cycle>x.cache,"store success before actual SRAM write");
        if(token!=ledger.cacheOrder.front()) {
            ok(TAGGED_STORE_RETURNS&&x.op.frozen&&x.hit&&!error,"response bypass exceeded successful ordinary store class");
            ok(cycle>=x.cache+2,"store bypass before registered complete result");
            for(auto t:ledger.cacheOrder) { if(t==token) break; auto& old=ledger.lives.at(t);
                ok(!old.op.store&&!old.cacheReply,"store passed an ordered/returned owner"); }
        }
        if(!x.op.store) ok(token==ledger.cacheOrder.front(),"tagged reads changed accepted request order");
        const bool ack=d.get_io$$postedAcknowledged$$valid();
        ok(ack==bool(postedRecords.count(token)),"posted ACK kind detached from real response.fire");
        if(ack) {
            auto& record=postedRecords.at(token);
            const Token observed{unsigned(d.get_io$$postedAcknowledged$$bits$$token$$index()),
                                 uint64_t(d.get_io$$postedAcknowledged$$bits$$token$$tag())};
            const Context context{unsigned(d.get_io$$postedAcknowledged$$bits$$context$$owner$$slot()),
                uint64_t(d.get_io$$postedAcknowledged$$bits$$context$$owner$$generation()),
                unsigned(d.get_io$$postedAcknowledged$$bits$$context$$cohortRoot$$slot()),
                uint64_t(d.get_io$$postedAcknowledged$$bits$$context$$cohortRoot$$generation()),
                uint64_t(d.get_io$$postedAcknowledged$$bits$$context$$epoch()),
                uint64_t(d.get_io$$postedAcknowledged$$bits$$context$$lineAddress())};
            ok(observed==token && context==record.context &&
               d.get_io$$postedAcknowledged$$bits$$responseTicket()==record.ticket && !record.acknowledged,
               "posted ACK lost full token context ticket or duplicated");
            record.acknowledged=true;++postedAck;
        }
        cacheHandles.erase(h);
        x.cacheReply=cycle; ++cacheReturns;
        ledger.cacheOrder.erase(std::find(ledger.cacheOrder.begin(),ledger.cacheOrder.end(),token));
    }
    void tick(bool reset=false) {
        ok(cycle<12000,"bounded chain timeout"); drive(); d.set_reset(reset); d.step();
        if(reset) { d.resetAll(); ++cycle; return; }
        ddr.sample(d);
        if(dmaPending&&d.get_io$$dma$$request$$ready()){ok(!dmaActive,"DMA owner reused");dmaActive=dmaPending;dmaPending.reset();}
        if(d.get_io$$dma$$response$$valid()){
            ok(dmaActive.has_value(),"DMA response lost accepted owner");
            ok(!d.get_io$$dma$$response$$bits$$error()&&!d.get_io$$dma$$response$$bits$$pageFault()&&d.get_io$$dma$$response$$bits$$data()==0,"coherent DMA store failed");
            memory[dmaActive->pa]=dmaActive->data;dmaActive.reset();
        }
        if(pteDue&&*pteDue<=cycle&&d.get_io$$pte$$response$$ready()) pteDue.reset();
        if(d.get_io$$pte$$request$$valid()&&pteRequestReady) {ok(!pteDue,"duplicate PTE request");pteDue=cycle+2;}
        if(pending&&d.get_io$$start$$ready()) {
            Operation op=*pending; unsigned slot=d.get_io$$chosen();
            ok(!ledger.lives.count(op.token),"duplicate full-generation start");
            if(d.get_io$$overlapAccepted()) ok(op.store&&op.frozen&&!(d.get_io$$live()&(1u<<slot)),"bound store replaced a busy/completing slot");
            ledger.lives.emplace(op.token,Life{op,slot,0,cycle}); pending.reset();
        }
        std::set<Token> live;
#define OWNER(N) if(d.get_io$$live()&(1u<<N)) {Token t{unsigned(d.get_io$$owner##N##$$index()),uint64_t(d.get_io$$owner##N##$$tag())}; \
            ok(ledger.lives.count(t),"live slot lost high generation"); live.insert(t); if(cancel&(1u<<N))ledger.lives.at(t).cancelled=true;}
        OWNER(0);OWNER(1);OWNER(2);OWNER(3);
#undef OWNER
        for(auto t:previous) if(!live.count(t)) ledger.release(t,cycle);
        previous=live;
        if(d.get_io$$queueFire()) {
            Token t{unsigned(d.get_io$$queueOwner$$index()),uint64_t(d.get_io$$queueOwner$$tag())};
            auto& x=ledger.lives.at(t); unsigned h=TAGGED_STORE_RETURNS?unsigned(d.get_io$$queueHandle()):x.slot;
            ledger.reserve(t,h,cycle,TAGGED_STORE_RETURNS); ++qCount;
            ok(d.get_io$$queueAddress()==(x.op.prechecked?x.op.pa:x.op.va),"request queue lost original VA/PA");
        }
        if(d.get_io$$physicalFire()) {
            ok(!ledger.physicalOrder.empty(),"fault placeholder issued physical traffic");
            Token t=ledger.physicalOrder.front();ledger.physicalOrder.pop_front(); auto& x=ledger.lives.at(t);
#if TAGGED_STORE_RETURNS
            if(posted(x.op)) ok(d.get_io$$physical$$returnHandle()>=4 && d.get_io$$physical$$returnHandle()<6,
                               "posted store did not use actual store-buffer handle");
            else ok(ledger.resolve(d.get_io$$physical$$returnHandle())==t,"physical request reordered handle owner");
#endif
            ok(!x.physical&&d.get_io$$physical$$address()==x.op.pa&&bool(d.get_io$$physical$$write())==x.op.store&&
               d.get_io$$physical$$size()==x.op.size&&d.get_io$$physical$$mask()==mask(x.op),"checked physical payload mismatch");
            x.physical=cycle;
            if(x.op.pa>=ram&&x.op.pa<ram+65536)ledger.cacheRequests.push_back(t);
        }
        if(d.get_io$$cacheFire()) {
            ok(!ledger.cacheRequests.empty(),"cache request without physical owner");
            Token t=ledger.cacheRequests.front();ledger.cacheRequests.pop_front();auto& x=ledger.lives.at(t);
#if TAGGED_STORE_RETURNS
            const unsigned cacheHandle=d.get_io$$cacheRequest$$returnHandle();
            if(posted(x.op)) ok(cacheHandle>=4 && cacheHandle<6,"posted cache handle class changed");
            else ok(ledger.resolve(cacheHandle)==t,"router cache handle mismatch");
            ok(!cacheHandles.count(cacheHandle),"actual cache handle reused while still live");
            cacheHandles.emplace(cacheHandle,t);
#endif
            ok(!x.cache&&d.get_io$$cacheRequest$$address()==x.op.pa,"cache PA or duplicate request");
            x.cache=cycle;x.hit=d.get_io$$cacheHit();
            if(x.op.frozen&&ledger.cacheOrder.size())ok(d.get_io$$independentStoreWrite(),"B2 store lacked actual SRAM write while read MSHR live");x.expectedBeat=x.op.store?0:memory.at(x.op.pa&~7ULL);
            if(x.op.store) {ok(d.get_io$$cacheRequest$$data()==(x.op.data<<(8*(x.op.pa&7))),"store SRAM byte data mismatch");
                memory[x.op.pa&~7ULL]=merge(memory.at(x.op.pa&~7ULL),x.op.data<<(8*(x.op.pa&7)),mask(x.op));}
            if(d.get_io$$postedAccepted$$valid()) {
                ok(posted(x.op),"posted owner created from virtual frozen or load authority");
                const Token member{unsigned(d.get_io$$postedAccepted$$bits$$member$$token$$index()),
                    uint64_t(d.get_io$$postedAccepted$$bits$$member$$token$$tag())};
                ok(member==t,"posted admission changed full token");
                const Context context{unsigned(d.get_io$$postedAccepted$$bits$$member$$context$$owner$$slot()),
                    uint64_t(d.get_io$$postedAccepted$$bits$$member$$context$$owner$$generation()),
                    unsigned(d.get_io$$postedAccepted$$bits$$member$$context$$cohortRoot$$slot()),
                    uint64_t(d.get_io$$postedAccepted$$bits$$member$$context$$cohortRoot$$generation()),
                    uint64_t(d.get_io$$postedAccepted$$bits$$member$$context$$epoch()),
                    uint64_t(d.get_io$$postedAccepted$$bits$$member$$context$$lineAddress())};
                if(d.get_io$$postedAccepted$$bits$$newLine()) {ok(contexts.insert(context).second,"duplicate posted context");++postedNew;}
                else {ok(contexts.count(context),"posted join lost original line context");++postedJoin;}
                ok(!postedRecords.count(t),"duplicate posted member");
                postedRecords.emplace(t,PostedRecord{context,unsigned(d.get_io$$postedAccepted$$bits$$member$$responseTicket())});
            }
            if(x.op.store && x.hit) {
                overlapRead+=bool(d.get_io$$victimRead());overlapCapture+=bool(d.get_io$$victimCapture());
            }
            ledger.cacheOrder.push_back(t);++cacheCount;
            if(doMutation&&mutation=="--mutate-early"&&x.op.store){corrupted();cacheReply(cacheHandle,0,false,false);}
        }
        const bool responseValid=d.get_io$$cacheResponseValid();
        if(held)ok(responseValid,"held complete response withdrawn");
        unsigned h=0;
#if TAGGED_STORE_RETURNS
        if(responseValid)h=d.get_io$$cacheResponse$$returnHandle();
#endif
        const auto payload=responseValid?std::tuple{h,uint64_t(d.get_io$$cacheResponse$$data()),bool(d.get_io$$cacheResponse$$error()),bool(d.get_io$$cacheResponse$$pageFault())}:std::tuple{0u,uint64_t(0),false,false};
        if(held){ok(d.get_io$$cacheResponseValid()&&payload==*held,"held complete payload/handle changed");++heldCycles;}
        held=d.get_io$$cacheResponseValid()&&!d.get_io$$cacheResponseReady()?std::optional{payload}:std::nullopt;
        if(d.get_io$$cacheResponseValid()&&d.get_io$$cacheResponseReady()) {
            if(d.get_io$$cacheFire())++simultaneous;
            unsigned observed=h;
            if(doMutation&&mutation=="--mutate-stale"){observed=7;corrupted();}
            if(doMutation&&mutation=="--mutate-owner"&&ledger.cacheOrder.size()>1){observed^=1;corrupted();}
            uint64_t observedData=std::get<1>(payload);
            if(doMutation&&mutation=="--mutate-data"){observedData^=1;corrupted();}
            cacheReply(observed,observedData,std::get<2>(payload),std::get<3>(payload));
            if(doMutation&&mutation=="--mutate-duplicate"){corrupted();cacheReply(observed,std::get<1>(payload),std::get<2>(payload),std::get<3>(payload));}
        }
#define SAMPLE_LOCAL(N) if(!local[N].empty()&&local[N].front().due<=cycle&&d.get_io$$mmio##N##$$response$$ready())local[N].pop_front(); \
        if(d.get_io$$mmio##N##$$request$$valid()&&localRequestReady[N]){ \
            ok(local[N].empty(),"local peripheral owner reused");local[N].push_back({cycle+3,0xa0+N});}
        SAMPLE_LOCAL(0);SAMPLE_LOCAL(1);
#undef SAMPLE_LOCAL
        if(d.get_io$$lsuResponseFire()) {
            ok(!ledger.queueOrder.empty(),"LSU reply without accepted request");
            Token t=ledger.queueOrder.front();
#if TAGGED_STORE_RETURNS
            t=ledger.resolve(d.get_io$$lsuResponse$$returnHandle());
#endif
            auto& x=ledger.lives.at(t);ok(!x.reply,"duplicate LSU reply");
            ok(posted(x.op)|| (x.op.fault?(!x.physical||x.op.fault==3):bool(x.physical)),"local fault/physical response double ownership");
            ok(bool(d.get_io$$lsuResponse$$error())==bool(x.op.fault)&&
               bool(d.get_io$$lsuResponse$$pageFault())==(x.op.fault==2),"LSU architectural error/page-fault owner mismatch");
            if(x.cache && !posted(x.op))ok(x.cacheReply,"LSU response preceded actual cache return");
            x.reply=cycle;++replies;ledger.queueOrder.erase(std::find(ledger.queueOrder.begin(),ledger.queueOrder.end(),t));
        }
        if(d.get_io$$complete$$valid()&&completionReady) {
            Token t{unsigned(d.get_io$$complete$$bits$$token$$index()),uint64_t(d.get_io$$complete$$bits$$token$$tag())};
            if(doMutation&&mutation=="--mutate-generation"){t.generation^=1ULL<<48;corrupted();}
            ok(ledger.lives.count(t),"completion changed high ROB generation");auto& x=ledger.lives.at(t);
            ok(!x.complete&&!x.cancelled&&x.reply,"duplicate/cancelled/early completion");
            ok(bool(d.get_io$$complete$$bits$$exception())==bool(x.op.fault),"precise completion fault mismatch");
            if(x.op.fault) ok(d.get_io$$complete$$bits$$cause()==(x.op.fault==2?13:(x.op.store?7:5))&&
                d.get_io$$complete$$bits$$tval()==x.op.va,"precise fault lost original VA/cause");
            else {uint64_t expected=x.op.store?0:(x.op.pa<ram?0xa0+(x.op.pa>=0x2000):x.expectedBeat>>(8*(x.op.pa&7)));
                if(x.op.size<3)expected&=(1ULL<<(8*(1u<<x.op.size)))-1;
                ok(d.get_io$$complete$$bits$$data()==expected,"completion independent bytes mismatch");}
            x.complete=cycle;++completions;
        }
        if(d.get_io$$sbInputFire() && d.get_io$$sbInputProof$$valid()) {
            ok(!d.get_io$$sbInputProof$$bits$$legacyPostedAccepted() && !d.get_io$$sbInputProof$$bits$$finalChecked(),
               "host supplied downstream posted permissions"); ++proofInput;
        }
        if(d.get_io$$sbOutputFire() && d.get_io$$sbOutputProof$$valid()) {
            ok(d.get_io$$sbOutputProof$$bits$$legacyPostedAccepted() && !d.get_io$$sbOutputProof$$bits$$finalChecked(),
               "real SB did not create exactly its acceptance permission"); ++proofOutput;
        }
        if(d.get_io$$physicalFire() && d.get_io$$checkedProof$$valid()) {
            ok(d.get_io$$checkedProof$$bits$$legacyPostedAccepted() && d.get_io$$checkedProof$$bits$$finalChecked(),
               "real DTA did not create final checked permission"); ++proofChecked;
        }
        if(d.get_io$$canonicalChecked$$valid()) ++frozenChecked;
        if(d.get_io$$sbPostedCompleted$$valid()) {
            Token t{unsigned(d.get_io$$sbPostedCompleted$$bits$$index()),uint64_t(d.get_io$$sbPostedCompleted$$bits$$tag())};
            ok(ledger.lives.count(t) && posted(ledger.lives.at(t).op) && ledger.lives.at(t).cacheReply,
               "SB completed posted token before real cache reply");
            ok(sbCompleted.insert(t).second,"duplicate SB posted completion");
        }
        if(d.get_io$$postedReleased$$valid()) {
            Context context{unsigned(d.get_io$$postedReleased$$bits$$context$$owner$$slot()),
                uint64_t(d.get_io$$postedReleased$$bits$$context$$owner$$generation()),
                unsigned(d.get_io$$postedReleased$$bits$$context$$cohortRoot$$slot()),
                uint64_t(d.get_io$$postedReleased$$bits$$context$$cohortRoot$$generation()),
                uint64_t(d.get_io$$postedReleased$$bits$$context$$epoch()),
                uint64_t(d.get_io$$postedReleased$$bits$$context$$lineAddress())};
            ok(contexts.erase(context)==1,"unknown released posted context");
        }
        ++cycle;
    }
    template<class P>void until(P done,const std::string& why,unsigned budget=1600){unsigned n=0;while(!done()&&n++<budget)tick();ok(done(),why);}
    Token start(Operation op) {op.epoch=d.get_io$$epoch()-unsigned(op.stale);ok(!pending,"start overwritten");pending=op;
        until([&]{return !pending;},"start never accepted");return op.token;}
    void drain(){seal=true;completionReady=true;holdEnqueue=holdQueue=holdRequest=holdResponse=false;cancel=0;
        until([&]{return d.get_io$$idle()&&ledger.queueOrder.empty()&&ledger.cacheOrder.empty()&&!pending;},"chain failed idle drain");tick();
        ok(ledger.handles.empty()&&cacheHandles.empty()&&qCount==replies&&cacheCount==cacheReturns,
            "exact accepted owner drain mismatch");
        ok(contexts.empty()&&postedAck==postedRecords.size(),"posted context/ACK lost drain");
        ok(proofInput==proofOutput&&proofOutput==proofChecked&&proofChecked==sbCompleted.size(),
            "posted proof producer or completion count mismatch"); seal=false;}
    void dmaWrite(uint64_t pa,uint64_t data){ok(!dmaPending&&!dmaActive,"DMA write overwritten");Operation o;o.pa=pa;o.data=data;o.store=true;dmaPending=o;
        until([&]{return !dmaPending&&!dmaActive;},"coherent DMA write failed drain");}
    void finish(){drain();flush=true;until([&]{return d.get_io$$flushDone();},"cache/home flush failed",4000);flush=false;tick();
        for(auto[a,value]:memory)ok(ddr.memory.at(unsigned(a-ram))==value,"final flushed independent byte memory mismatch");
        ok(ddr.pendingReads.empty()&&!ddr.writing&&!ddr.responding,"home declared drain with live AXI owner");
        for(const auto& [token,x]:ledger.lives) if(x.op.store) std::cout<<"STORE_LIFETIME posted="<<posted(x.op)
            <<" token="<<token.generation<<" start="<<x.start<<" queued="<<x.queued<<" physical="<<x.physical
            <<" cache="<<x.cache<<" cache_reply="<<x.cacheReply<<" lsu_reply="<<x.reply<<" complete="<<x.complete<<'\n';}
};
static Operation load(unsigned index,uint64_t pa,uint64_t generation=0xfedcba9876543200ULL){Operation o;o.token={index,generation+index};o.pa=pa;o.va=virt+(pa-ram);return o;}
static Operation store(unsigned index,uint64_t pa,uint64_t data,uint64_t generation=0x8edcba9876543200ULL){auto o=load(index,pa,generation);o.store=o.frozen=true;o.prechecked=o.parallel=false;o.data=data;return o;}
static void coreCase(unsigned kind) {
    Test b;auto warm=b.start(load(9,ram));b.drain();
    auto a=load(5,ram+4096);if(kind==1)a.fault=3;
    if(kind==1)b.ddr.denyReadAddress=4096;
    auto young=b.start(a);b.until([&]{return b.ledger.lives.at(young).cache;},"younger read never accepted first");
    b.doMutation=true;b.holdResponse=kind==3;
    auto head=b.start(store(0,ram,0x1928374655aabbccULL));
    b.until([&]{return b.ledger.lives.at(head).cache;},"head store did not reach SRAM");
    check(b.ledger.lives.at(head).hit,"B2 store was not real resident hit");
    check(b.ledger.lives.at(young).slot!=b.ledger.lives.at(head).slot,"B2 reused live read slot");
    if(kind==2){b.cancel=1u<<b.ledger.lives.at(young).slot;b.tick();b.cancel=0;}
    if(kind==3){b.until([&]{return b.d.get_io$$cacheResponseValid();},"no held complete response");
        for(unsigned n=0;n<120;++n)b.tick();b.holdResponse=false;}
    if(TAGGED_STORE_RETURNS&&kind!=3){b.until([&]{return b.ledger.lives.at(head).complete;},"ON head store did not return early");
        check(!b.ledger.lives.at(young).reply&&!b.ledger.lives.at(young).release,"ON early store freed delayed read owner");}
    if(!TAGGED_STORE_RETURNS&&kind!=3){for(unsigned n=0;n<8;++n)b.tick();check(!b.ledger.lives.at(head).reply,"OFF changed ordered return sequence");}
    if(kind==0){b.until([&]{return b.ledger.lives.at(head).complete;},"store completion missing before free-hole reuse");
        auto reused=b.start(load(6,ram+8,0xc123456789ab0000ULL));
        if(TAGGED_STORE_RETURNS){check(!b.ledger.lives.at(young).reply,"oldest read released before younger-hole reallocation");
            check(b.ledger.lives.at(reused).slot==b.ledger.lives.at(head).slot,"completed store slot was not reused independently of old read");}}
    b.finish();const auto& y=b.ledger.lives.at(young);const auto& s=b.ledger.lives.at(head);
    check(TAGGED_STORE_RETURNS?s.cacheReply<y.cacheReply:y.cacheReply<s.cacheReply,"paired cache return order mismatch");
    if(kind==2)check(y.cancelled&&!y.complete&&y.reply&&y.release,"cancelled read did not drain without completion");
    if(kind==3)check(b.heldCycles>=100,"held complete payload was not exercised");
    std::cout<<"TAGGED_CHAIN_CASE b2="<<kind<<" tagged="<<TAGGED_STORE_RETURNS<<" read_reply="<<y.reply<<" store_reply="<<s.reply<<" held="<<b.heldCycles<<'\n';
}
static Operation physicalStore(unsigned index,uint64_t pa,uint64_t data,uint64_t generation) {
    auto o=store(index,pa,data,generation);o.va=pa;o.virtualized=o.prechecked=o.frozen=false;return o;
}
static void postedMergeCase() {
    Test b;b.doMutation=true;b.holdResponse=true;
    const auto a=b.start(physicalStore(0,ram+256,0x1122334455667788ULL,0xAA00000000000000ULL));
    b.until([&]{return b.ledger.lives.at(a).complete;},"first posted local ACK did not complete");
    const auto c=b.start(physicalStore(1,ram+264,0x8877665544332211ULL,0xBB00000000000000ULL));
    b.until([&]{return b.postedRecords.size()==2;},"same-line posted pair not accepted");
    for(unsigned i=0;i<8;++i)b.tick();
    check(b.postedNew==1&&b.postedJoin==1&&b.postedAck==0&&b.contexts.size()==1,"real posted merge/held ACK witness absent");
    check(b.ledger.lives.at(a).complete && b.ledger.lives.at(c).complete,"buffered stores lost early LSU completion");
    b.holdResponse=false;b.seal=true;b.drain();
    check(b.sbCompleted.size()==2&&b.postedAck==2,"real posted ACK and SB credit drain mismatch");
    b.start(load(2,ram+256,0xCC00000000000000ULL));b.drain();b.finish();
    std::cout<<"POSTED_FROZEN_CASE posted_merge=2 actual_proof_chain="<<b.proofChecked<<" held="<<b.heldCycles<<'\n';
}
static void frozenCaptureCase() {
    Test b;b.doMutation=true;
    for(auto [address,value]:std::vector<std::pair<uint64_t,uint64_t>>{{ram+256,0x1111},{ram+16640,0x2222},{ram+512,0x3333}}) {
        b.start(store(0,address,value,0xD000000000000000ULL+address));b.drain();
    }
    b.holdRequest=true;
    auto old=b.start(load(5,ram+33024,0xE100000000000000ULL));
    auto head=b.start(store(0,ram+512,0xCAFEBABEDEAD1234ULL,0xE200000000000000ULL));
    for(unsigned n=0;n<24;++n)b.tick();
    b.holdRequest=false;b.finish();
    check(b.ledger.lives.at(head).hit,"frozen capture store was not resident");
    check(b.overlapCapture==unsigned(b.d.get_io$$overlapEnabled()),"frozen capture positive/negative witness missing");
    check(b.frozenChecked>=4&&b.postedRecords.empty(),"frozen permission crossed posted class");
    std::cout<<"POSTED_FROZEN_CASE frozen_capture="<<b.overlapCapture<<" read="<<b.overlapRead<<" checked="<<b.frozenChecked<<'\n';
}
int main(int argc,char**argv){try{
    std::cout.setf(std::ios::unitbuf);mutation=argc>1?argv[1]:"";
    postedMergeCase();frozenCaptureCase();
    {Test b;b.pmpCfg=0x19;for(unsigned n=0;n<8;++n)b.tick();auto s=store(0,ram,123);s.fault=1;b.start(s);b.finish();
     check(!b.ledger.lives.at(s.token).physical,"denied frozen store escaped DTA");std::cout<<"POSTED_FROZEN_CASE pmp_denied=1\n";}
    {Test b;auto a=load(1,ram);a.stale=true;a.fault=1;b.start(a);b.finish();
     check(!b.ledger.lives.at(a.token).physical,"stale permission escaped DTA");std::cout<<"POSTED_FROZEN_CASE stale_permission=1\n";}
    {Test b;b.holdQueue=true;auto a=b.start(load(1,ram));b.cancel=1u<<b.ledger.lives.at(a).slot;b.tick();b.cancel=0;b.holdQueue=false;b.finish();
     check(b.ledger.lives.at(a).reply&&!b.ledger.lives.at(a).complete,"cancelled request did not drain exact owner");std::cout<<"POSTED_FROZEN_CASE cancel_drain=1\n";}
    std::cout<<"POSTED_FROZEN_CHAIN_PASS\n";return 0;
}catch(const std::exception&e){std::cerr<<"POSTED_FROZEN_CHAIN_FAIL "<<e.what()<<'\n';return 1;}}
