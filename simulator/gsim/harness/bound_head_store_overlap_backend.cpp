#include "PendingStoreProofBackendGsim.h"
#include "pending_store_proof_reference.h"
#include <algorithm>
#include <array>
#include <cstring>
#include <deque>
#include <iostream>
#include <optional>
#include <set>
#include <tuple>
#include <type_traits>
#include <vector>
#ifndef PENDING_STORE_ENABLED
#define PENDING_STORE_ENABLED 0
#endif
#ifndef BOUND_HEAD_STORE_OVERLAP
#define BOUND_HEAD_STORE_OVERLAP 0
#endif
using namespace pending_store_reference;
static uint64_t sext(uint64_t v,unsigned bits) { return uint64_t(int64_t(v << (64-bits)) >> (64-bits)); }
static uint32_t imm(unsigned rd,unsigned rs,int n) { return (uint32_t(n)&4095)<<20 | rs<<15 | rd<<7 | 0x13; }
static uint32_t shift(unsigned rd,unsigned n) { return n<<20 | rd<<15 | 1<<12 | rd<<7 | 0x13; }
static uint32_t ld(unsigned rd,unsigned rs,int off=0,unsigned size=3) { return (uint32_t(off)&4095)<<20 | rs<<15 | size<<12 | rd<<7 | 3; }
static uint32_t st(unsigned rs,unsigned data,int off=0,unsigned size=3) {
    const unsigned v=unsigned(off)&4095; return (v>>5)<<25 | data<<20 | rs<<15 | size<<12 | (v&31)<<7 | 0x23;
}
static uint32_t beq(unsigned rs,int offset=32) {
    const unsigned v=unsigned(offset)&8191;return ((v>>12)&1)<<31|((v>>5)&63)<<25|rs<<20|rs<<15|((v>>1)&15)<<8|((v>>11)&1)<<7|0x63;
}
static uint32_t divu(unsigned rd,unsigned a,unsigned b) { return 1u<<25 | b<<20 | a<<15 | 5<<12 | rd<<7 | 0x33; }
struct Instruction { uint32_t word=0x13; uint64_t pc=0; };
struct Entry {
    Token token{}; Instruction inst{}; unsigned rd=0, rs1=0, rs2=0, size=0;
    bool writes=false,memory=false,store=false,system=false,divide=false,branch=false,atomic=false,fault=false,killed=false;
    uint64_t expected=0,address=0,pa=0,data=0,allocated=0,start=0,physical=0,response=0,complete=0,retire=0,checked=0,released=0;
    bool started=false,requested=false,completed=false,retired=false,frozen=false;
};
struct Reply { uint64_t due=0,data=0; Token token{}; bool error=false; };
struct PteReply { uint64_t due=0,data=0; };
struct Bench {
    SPendingStoreProofBackendGsim dut;
    Tables tables; Bytes actual, expected;
    std::array<uint64_t,32> architectural{},predicted{};
    std::map<Token,Entry> entries;
    std::deque<Token> live,requests;
    std::deque<Reply> replies;
    std::deque<PteReply> ptes;
    std::set<Token> completionTokens,retiredTokens;
    uint64_t cycle=0,nextPc=0x1000,physicalHold=0,responseHold=0,latency=8;
    uint64_t oldDataReady=0,proofCycle=0,firstEarlyPhysical=0,earlyReadDrain=0,overlapCapture=0;
    unsigned accepted=0,retired=0,physicalCount=0,responseCount=0,queryReads=0,queryWrites=0,walks=0,traps=0;
    unsigned earlyStarts=0,peakCredit=0,creditReturns=0,holds=0,killCount=0,reuse=0;
    std::map<unsigned,uint64_t> generations;
    std::optional<Token> oldStore,youngLoad,secondLoad,previousCredit,expectedCredit;
    std::optional<Proof> boundProof;
    bool faultStore=false,faultLoad=false,commitEnable=true,injectData=false,injectRetire=false;
    bool injectFrozenPa=false,injectLocalAck=false,injectLoadError=false,injectStoreError=false;
    unsigned overlappedStarts=0,checkedStores=0,corruptions=0,recoveryEdges=0,recoveryWithLiveRead=0;
    std::set<Token> previousLive;
    using Held=std::tuple<uint64_t,uint64_t,unsigned,unsigned,bool,bool>;
    std::optional<Held> heldPhysical,heldUpstream;
    bool previousCreditActive=false;
    Bench() {
        static_assert(std::is_trivially_copyable_v<SPendingStoreProofBackendGsim>);
        std::memset(&dut,0,sizeof(dut));dut.LOG_START=1;dut.activateAll();
        tick({}, {}, true);tick({}, {}, true);tick();tick();
    }
    void check(bool ok,const std::string &why) const { require(ok,"cycle="+std::to_string(cycle)+" "+why); }
    Entry interpret(Instruction inst,Token token) {
        Entry e; e.token=token;e.inst=inst;e.allocated=cycle;
        const uint32_t w=inst.word;const unsigned op=w&127,f=(w>>12)&7;
        e.rd=(w>>7)&31;e.rs1=(w>>15)&31;e.rs2=(w>>20)&31;
        const uint64_t a=predicted[e.rs1],b=predicted[e.rs2];
        if(op==0x13) {e.writes=true;
            if(f==0)e.expected=a+sext(w>>20,12);else if(f==1)e.expected=a<<((w>>20)&63);
            else throw std::runtime_error("unimplemented independent immediate opcode");
        } else if(op==0x33 && (w>>25)==1 && f==5) {
            e.writes=true;e.divide=true;e.expected=b?a/b:UINT64_MAX;
        } else if(op==3 || op==0x23) {
            e.memory=true;e.store=op==0x23;e.writes=!e.store;e.size=f&3;
            const uint64_t offset=sext(e.store?((w>>25)<<5 | ((w>>7)&31)):(w>>20),12);
            e.address=a+offset;e.pa=tables.physical(e.address);e.data=b;e.fault=e.store?faultStore:faultLoad;
            if(e.store) { if(!e.fault) expected.write(e.pa,b,e.size); }
            else {e.expected=expected.read(e.pa,e.size);if(!(f&4)&&e.size<3)e.expected=sext(e.expected,8u<<e.size);}
        } else if(op==0x63) {
            check(f==0&&a==b,"independent branch fixture must be a taken BEQ");
            e.branch=true;e.expected=inst.pc+sext(((w>>31)<<12)|(((w>>7)&1)<<11)|(((w>>25)&63)<<5)|(((w>>8)&15)<<1),13);
        } else if(op==0x73) {e.system=true;e.writes=e.rd!=0;e.expected=0;}
        else throw std::runtime_error("unknown raw instruction in independent interpreter");
        if(e.writes && e.rd)predicted[e.rd]=e.expected;
        return e;
    }
    void observeRetirement(Token t,uint64_t pc,uint32_t word,uint64_t data) {
        check(entries.count(t),"retirement has no allocated full token");auto &e=entries.at(t);
        check(!e.killed&&!e.fault&&!retiredTokens.count(t),"fault/killed/duplicate retirement");
        check(!live.empty()&&live.front()==t,"retirement lost exact program order");live.pop_front();retiredTokens.insert(t);
        check(word==e.inst.word&&pc==e.inst.pc,"retirement provenance mismatch");
        if(e.writes&&e.rd){check(data==e.expected,"architectural retirement data mismatch");architectural[e.rd]=e.expected;}
        if(e.memory)check(e.response && e.complete && cycle>=e.response,"memory retirement before actual response and completion");
        e.retired=true;e.retire=cycle;++retired;
    }
    std::vector<Token> tick(std::array<std::optional<Instruction>,2> offered={},
            std::optional<Token> recover={},bool reset=false) {
        check(!recover,"registered redirect profile forbids external recovery input");
        dut.set_reset(reset);
#define INPUT(N) \
        dut.set_io$$instruction##N##$$valid(offered[N].has_value()); \
        dut.set_io$$instruction##N##$$bits(offered[N]?offered[N]->word:0xffffffffU); \
        dut.set_io$$pc##N(offered[N]?offered[N]->pc:UINT64_MAX)
        INPUT(0);INPUT(1);
#undef INPUT
        dut.set_io$$commitEnable(commitEnable);dut.set_io$$inspectRegister(cycle%32);
        dut.set_io$$probeIndex(oldStore?oldStore->index:15);
        dut.set_io$$recover$$valid(recover.has_value());dut.set_io$$recover$$bits$$inclusive(true);
        dut.set_io$$recover$$bits$$token$$index(recover?recover->index:15);
        dut.set_io$$recover$$bits$$token$$tag(recover?recover->tag:UINT64_MAX);
        const bool ready=cycle>=physicalHold && cycle%7!=3;
        const bool response=!replies.empty()&&replies.front().due<=cycle&&cycle>=responseHold;
        dut.set_io$$physical$$request$$ready(ready);dut.set_io$$physical$$response$$valid(response);
        dut.set_io$$physical$$response$$bits$$data(response?replies.front().data:UINT64_MAX);
        bool responseError=response&&replies.front().error;
        if(response && responseError && ((injectLoadError&&!entries.at(replies.front().token).store)||(injectStoreError&&entries.at(replies.front().token).store))) {responseError=false;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
        dut.set_io$$physical$$response$$bits$$error(responseError);
        dut.set_io$$physical$$response$$bits$$pageFault(false);
        const bool pte=!ptes.empty()&&ptes.front().due<=cycle;
        dut.set_io$$pte$$request$$ready(cycle%5!=2);dut.set_io$$pte$$response$$valid(pte);
        dut.set_io$$pte$$response$$bits$$data(pte?ptes.front().data:UINT64_MAX);
        dut.set_io$$pte$$response$$bits$$error(false);
        dut.step();
        if(reset){dut.resetAll();++cycle;return{};}
        check(dut.get_io$$committedValue()==architectural[cycle%32],"architectural register snapshot mismatch");
        std::vector<Token> allocated;
        std::optional<Token> earlyThisCycle;
#define ACCEPT(N) \
        if(dut.get_io$$renamed##N##$$valid()) { \
            check(offered[N].has_value(),"rename without valid raw instruction"); \
            Token t{unsigned(dut.get_io$$renamed##N##$$bits$$token$$index()),uint64_t(dut.get_io$$renamed##N##$$bits$$token$$tag())}; \
            Entry e=interpret(*offered[N],t); \
            check(bool(dut.get_io$$decoded##N##$$memory())==e.memory && bool(dut.get_io$$decoded##N##$$store())==e.store && \
                bool(dut.get_io$$decoded##N##$$mulDiv())==e.divide && bool(dut.get_io$$decoded##N##$$system())==e.system, \
                "real decoder class differs from independent raw opcode"); \
            if(e.memory)check(dut.get_io$$decoded##N##$$rename$$rs1()==e.rs1 && \
                dut.get_io$$decoded##N##$$rename$$rs2()==(e.store?e.rs2:0) && \
                dut.get_io$$decoded##N##$$memorySize()==e.size,"real decoder memory operands/size mismatch"); \
            auto g=generations.find(t.index);if(g!=generations.end()&&g->second!=t.tag)++reuse;generations[t.index]=t.tag; \
            check(!entries.count(t),"full ROB generation reused");entries.emplace(t,e);live.push_back(t);allocated.push_back(t);++accepted; \
        }
        ACCEPT(0);ACCEPT(1);
#undef ACCEPT
        if(pte&&dut.get_io$$pte$$response$$ready())ptes.pop_front();
        if(dut.get_io$$pte$$request$$valid()&&cycle%5!=2)ptes.push_back({cycle+2,tables.pte(dut.get_io$$pte$$request$$bits())});
        walks+=dut.get_io$$translationWalk();
        if(dut.get_io$$queryValid()){dut.get_io$$queryWrite()?++queryWrites:++queryReads;}
        if(oldStore&&dut.get_io$$probePending()&&dut.get_io$$probeDataReady()&&!oldDataReady) {
            check(dut.get_io$$probeToken$$index()==oldStore->index&&dut.get_io$$probeToken$$tag()==oldStore->tag,
                "readiness probe mismatched full owner");oldDataReady=cycle;
        }
        if(dut.get_io$$proof$$valid()) {
            Proof p{{unsigned(dut.get_io$$proof$$bits$$token$$index()),uint64_t(dut.get_io$$proof$$bits$$token$$tag())},
                uint32_t(dut.get_io$$proof$$bits$$epoch()),uint64_t(dut.get_io$$proof$$bits$$payload$$address()),
                uint64_t(dut.get_io$$proof$$bits$$payload$$physicalAddress()),bool(dut.get_io$$proof$$bits$$payload$$write()),
                unsigned(dut.get_io$$proof$$bits$$payload$$size()),unsigned(dut.get_io$$proof$$bits$$payload$$mask())};
            check(entries.count(p.token),"proof has no allocated full token");const auto &e=entries.at(p.token);
            check(e.memory&&e.store&&!e.killed&&p.write&&p.original==e.address&&p.physical==e.pa&&p.size==e.size&&
                p.mask==lanes(e.pa,e.size)&&p.epoch==dut.get_io$$epoch(),"proof differs from host physical interval");
            if(oldStore&&p.token==*oldStore) { if(!proofCycle)proofCycle=cycle; if(!boundProof)boundProof=p; }
            if(dut.get_io$$bound()){if(boundProof)check(*boundProof==p,"bound proof changed after readiness/kill");boundProof=p;}
        }
        if(dut.get_io$$lsuOffer())check(dut.get_io$$lsuReady(),"backend valid=>ready profile contract violated");
        if(dut.get_io$$lsuStart()) {
            check(!dut.get_io$$recovering()&&!dut.get_io$$recoveryAccepted(),"same-edge registered recovery admitted a memory start");
            Token t{unsigned(dut.get_io$$lsuToken$$index()),uint64_t(dut.get_io$$lsuToken$$tag())};
            check(entries.count(t),"LSU start has no full-token owner");auto &e=entries.at(t);
            check(!e.started&&!e.killed&&e.memory,"duplicate/cancelled/nonmemory LSU start");e.started=true;e.start=cycle;
            check(dut.get_io$$lsuVa()==e.address&&bool(dut.get_io$$lsuStore())==e.store,"LSU original VA/type mismatch");
            if(e.store) {
                check(!dut.get_io$$lsuParallel(),"pending proof made actual store parallel");
                if(oldStore&&t==*oldStore&&youngLoad&&previousLive.count(*youngLoad)&&!entries.at(*youngLoad).response) {
                    check(BOUND_HEAD_STORE_OVERLAP,"OLD admitted store beside live early owner");
                    check(boundProof&&oldDataReady&&e.start>=oldDataReady,"overlap lost bound proof or data-ready authority");
                    ++overlappedStarts;overlapCapture=cycle;
                }
            }
            e.frozen=dut.get_io$$lsuFrozen$$valid();
            uint64_t observedFrozenPa=dut.get_io$$lsuFrozen$$bits$$physicalAddress();
            if(e.frozen&&injectFrozenPa){observedFrozenPa^=1ULL<<32;++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
            if(e.frozen)check(boundProof&&boundProof->token==t&&observedFrozenPa==e.pa&&
                dut.get_io$$lsuFrozen$$bits$$address()==e.address&&dut.get_io$$lsuFrozen$$bits$$mask()==lanes(e.pa,e.size),
                "bound store failed frozen physical handoff");
            if(oldStore&&!e.store&&!entries.at(*oldStore).started) {
                check(PENDING_STORE_ENABLED&&!oldDataReady&&boundProof,"new bypass without unavailable old data and bound proof");
                check(!previousCreditActive,"second early load acquired occupied credit");earlyThisCycle=t;++earlyStarts;
                check(disjoint(*boundProof,{t,uint32_t(dut.get_io$$epoch()),e.address,e.pa,false,e.size,lanes(e.pa,e.size)}),
                    "overlapping physical byte interval bypassed old store");
            }
        }
        if(dut.get_io$$canonicalChecked$$valid()) {
            Token t{unsigned(dut.get_io$$canonicalChecked$$bits$$origin$$token$$index()),uint64_t(dut.get_io$$canonicalChecked$$bits$$origin$$token$$tag())};
            check(entries.count(t)&&entries.at(t).store&&entries.at(t).started,"actual checked callback missing store owner");
            auto&e=entries.at(t);check(!e.checked&&dut.get_io$$canonicalChecked$$bits$$virtualAddress()==e.address&&
                dut.get_io$$canonicalChecked$$bits$$physicalAddress()==e.pa&&dut.get_io$$canonicalChecked$$bits$$mask()==lanes(e.pa,e.size),
                "actual checked callback tuple mismatch");e.checked=cycle;++checkedStores;
        }
        if(injectLocalAck&&oldStore&&entries.at(*oldStore).started&&!entries.at(*oldStore).response) {
            ++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';const auto&e=entries.at(*oldStore);observeRetirement(*oldStore,e.inst.pc,e.inst.word,e.expected);
        }
        if(dut.get_io$$lsuRequestFire()) {
            check(dut.get_io$$lsuRequestOwner$$valid(),"accepted LSU request missing exact owner");
            Token t{unsigned(dut.get_io$$lsuRequestOwner$$bits$$index()),uint64_t(dut.get_io$$lsuRequestOwner$$bits$$tag())};
            check(entries.count(t)&&entries.at(t).started,"LSU accepted request lacks prior start");requests.push_back(t);
        }
        if(response&&dut.get_io$$physical$$response$$ready()) {
            auto r=replies.front();replies.pop_front();auto &e=entries.at(r.token);e.response=cycle;++responseCount;
            if(e.store&&!r.error)actual.write(e.pa,e.data,e.size);
            if(youngLoad&&r.token==*youngLoad)earlyReadDrain=cycle;
        }
        const bool pv=dut.get_io$$physical$$request$$valid();
        if(pv) {
            Held now{uint64_t(dut.get_io$$physical$$request$$bits$$address()),uint64_t(dut.get_io$$physical$$request$$bits$$data()),
                unsigned(dut.get_io$$physical$$request$$bits$$size()),unsigned(dut.get_io$$physical$$request$$bits$$mask()),
                bool(dut.get_io$$physical$$request$$bits$$write()),bool(dut.get_io$$physical$$request$$bits$$uncached())};
            if(heldPhysical)check(now==*heldPhysical,"held physical request changed");heldPhysical=ready?std::nullopt:std::optional{now};holds+=!ready;
            if(ready) {
                check(!requests.empty(),"physical acceptance has no accepted LSU owner");Token t=requests.front();requests.pop_front();auto &e=entries.at(t);
                check(!e.requested,"duplicate physical acceptance");e.requested=true;e.physical=cycle;
                check(std::get<0>(now)==e.pa&&std::get<2>(now)==e.size&&std::get<3>(now)==lanes(e.pa,e.size)&&std::get<4>(now)==e.store,
                    "physical request differs from independent owner/byte oracle");
                if(e.store)check(std::get<1>(now)==(e.data<<((e.pa&7)*8)),"aligned store data mismatch");
                check(!dut.get_io$$physical$$request$$bits$$virtualized()&&!dut.get_io$$physical$$request$$bits$$precheckedLoad(),"private authority leaked to physical boundary");
                const uint64_t data=e.store?0:actual.read(e.pa&~7ULL,3);
                if(injectData){++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';}
                replies.push_back({cycle+latency,data^uint64_t(injectData),t,e.fault});++physicalCount;
                if(oldStore&&!e.store&&!entries.at(*oldStore).started){check(!oldDataReady||e.start<oldDataReady,"early operation was first offered after old data ready");if(!firstEarlyPhysical)firstEarlyPhysical=cycle;}
            }
        } else {check(!heldPhysical,"held physical VALID withdrawn");}
        std::set<Token> actualLive;
#define LIVE(N) \
        if(dut.get_io$$lsuOwner##N##$$valid())actualLive.insert({unsigned(dut.get_io$$lsuOwner##N##$$bits$$index()),uint64_t(dut.get_io$$lsuOwner##N##$$bits$$tag())})
        LIVE(0);LIVE(1);LIVE(2);LIVE(3);
        for(auto t:previousLive)if(!actualLive.count(t)){
            auto&e=entries.at(t);e.released=cycle;
            check(e.response||!e.requested,"accepted response owner released before held response drain");
        }
        if(overlapCapture&&cycle==overlapCapture+1)check(oldStore&&youngLoad&&actualLive.count(*oldStore)&&actualLive.count(*youngLoad),
            "NEW overlap did not preserve two distinct captured owners");
        previousLive=actualLive;
#undef LIVE
        const bool active=dut.get_io$$creditActive();
        check(active==expectedCredit.has_value()&&!dut.get_io$$creditReserved(),"credit lifetime differs from actual LSU full-token owner drain");
        if(active) {
            Token t{unsigned(dut.get_io$$creditOwner$$index()),uint64_t(dut.get_io$$creditOwner$$tag())};
            check(expectedCredit&&*expectedCredit==t&&entries.count(t)&&entries.at(t).started&&!entries.at(t).store,"credit has no actual load owner");
            if(previousCreditActive)check(previousCredit&&*previousCredit==t,"active credit owner substituted");previousCredit=t;peakCredit=1;
        }
        if(previousCreditActive&&!active)++creditReturns;previousCreditActive=active;
        if(expectedCredit&&!actualLive.count(*expectedCredit))expectedCredit.reset();
        if(earlyThisCycle){check(!active,"new early offer replaced an active credit");expectedCredit=earlyThisCycle;}
#define COMPLETE(N) \
        if(dut.get_io$$issued##N##$$valid()) { \
            Token t{unsigned(dut.get_io$$issued##N##$$bits$$token$$index()),uint64_t(dut.get_io$$issued##N##$$bits$$token$$tag())}; \
            check(entries.count(t)&&!entries.at(t).killed,"completion for nonexistent/killed full token"); \
            auto &e=entries.at(t);check(completionTokens.insert(t).second,"duplicate completion");e.completed=true;e.complete=cycle; \
            if(e.memory)check(bool(dut.get_io$$issued##N##$$bits$$exception())==e.fault && \
                (!e.fault || (dut.get_io$$issued##N##$$bits$$cause()==(e.store?7:5) && dut.get_io$$issued##N##$$bits$$tval()==e.address)), \
                "physical error lost exact completion cause/original VA"); \
            if(e.writes&&!e.fault)check(dut.get_io$$issued##N##$$bits$$data()==e.expected,"independent execution data mismatch"); \
        }
        COMPLETE(0);COMPLETE(1);
#undef COMPLETE
        if(dut.get_io$$redirect$$valid() && !dut.get_io$$trap$$valid()) {
            ++recoveryEdges;
            if(youngLoad&&previousLive.count(*youngLoad)&&!entries.at(*youngLoad).response)++recoveryWithLiveRead;
            check(!dut.get_io$$lsuStart(),"same-edge decoded branch recovery admitted a memory start");
            Token t{unsigned(dut.get_io$$redirect$$bits$$token$$index()),uint64_t(dut.get_io$$redirect$$bits$$token$$tag())};
            check(entries.count(t),"redirect has no exact decoded owner");const auto&e=entries.at(t);
            if(e.branch) {
                check(dut.get_io$$redirect$$bits$$target()==e.expected,"real taken branch target differs from instruction oracle");
                auto at=std::find(live.begin(),live.end(),t);check(at!=live.end(),"branch redirect owner is not live");
                for(auto i=at+1;i!=live.end();++i){entries.at(*i).killed=true;++killCount;}live.erase(at+1,live.end());
                predicted=architectural;for(auto k:live){const auto&keep=entries.at(k);if(keep.writes&&keep.rd)predicted[keep.rd]=keep.expected;}
            }
        }
#define COMMIT(N) \
        if(dut.get_io$$commit##N##$$valid()) { \
            Token t{unsigned(dut.get_io$$commit##N##$$bits$$token$$index()),uint64_t(dut.get_io$$commit##N##$$bits$$token$$tag())}; \
            observeRetirement(t,dut.get_io$$commit##N##$$bits$$pc(),dut.get_io$$commit##N##$$bits$$instruction(),dut.get_io$$commit##N##$$bits$$data()); \
        }
        COMMIT(0);COMMIT(1);
#undef COMMIT
        if(dut.get_io$$recoveryAccepted() && recover) {
            check(recover.has_value(),"unexpected external recovery acceptance");auto at=std::find(live.begin(),live.end(),*recover);
            check(at!=live.end(),"recovery boundary not live");for(auto i=at;i!=live.end();++i){entries.at(*i).killed=true;++killCount;}live.erase(at,live.end());
            predicted=architectural;for(auto t:live){const auto&e=entries.at(t);if(e.writes&&e.rd)predicted[e.rd]=e.expected;}
        }
        if(dut.get_io$$trap$$valid()) {
            check(!live.empty(),"trap without owner");Token t{unsigned(dut.get_io$$trap$$bits$$token$$index()),uint64_t(dut.get_io$$trap$$bits$$token$$tag())};
            const auto&e=entries.at(live.front());check(t==live.front()&&e.fault&&dut.get_io$$trap$$bits$$cause()==(e.store?7:5)&&dut.get_io$$trap$$bits$$tval()==e.address,
                "late memory fault lost exact owner/cause/original VA");
            for(auto k:live){entries.at(k).killed=true;++killCount;}live.clear();predicted=architectural;++traps;
        }
        if(injectRetire&&youngLoad&&entries.at(*youngLoad).killed) {
            ++corruptions;std::cerr<<"ACTUAL_CORRUPTION count="<<corruptions<<'\n';
            const auto&e=entries.at(*youngLoad);
            observeRetirement(*youngLoad,e.inst.pc,e.inst.word,e.expected);
        }
        ++cycle;return allocated;
    }
    std::vector<Token> submit(const std::vector<uint32_t>&words) {
        std::vector<Instruction> program;for(auto w:words){program.push_back({w,nextPc});nextPc+=4;}
        std::vector<Token> result;unsigned cursor=0;
        for(unsigned n=0;n<4096&&cursor<program.size();++n){std::array<std::optional<Instruction>,2> in{};in[0]=program[cursor];if(cursor+1<program.size())in[1]=program[cursor+1];
            auto got=tick(in);cursor+=got.size();result.insert(result.end(),got.begin(),got.end());}
        check(cursor==program.size(),"bounded instruction admission timeout");return result;
    }
    void wait(unsigned n){while(n--)tick();}
    void drain(){for(unsigned n=0;n<4096&&(!live.empty()||!requests.empty()||!replies.empty()||!ptes.empty());++n)tick();
        check(live.empty()&&requests.empty()&&replies.empty()&&ptes.empty(),"bounded pipeline drain timeout");wait(12);
        check(dut.get_io$$idle()&&physicalCount==responseCount,"idle/response accounting mismatch");
        for(const auto&[address,byte]:expected.changed){auto it=actual.changed.find(address);check(it!=actual.changed.end()&&it->second==byte,"final independent byte memory mismatch");}}
    void one(uint32_t w){submit({w});drain();}
    void constant(unsigned rd,uint64_t value){std::vector<uint32_t>w{imm(rd,0,int(value>>55))};for(int n=44;n>=0;n-=11){w.push_back(shift(rd,11));w.push_back(imm(rd,rd,int((value>>n)&2047)));}submit(w);drain();}
    void csr(unsigned n,uint64_t value){constant(31,value);one(n<<20|31<<15|1<<12|0x73);}
    void configure(){csr(0x3b0,allPmp);csr(0x3a0,0x1f);csr(0x180,satp);csr(0x300,(1ULL<<17)|(1ULL<<11));
        check(dut.get_io$$vm$$satp()==satp&&dut.get_io$$vm$$dataPrivilege()==1,"real CSR VM setup failed");
        constant(10,va);constant(11,va+4096);constant(12,va+8192);constant(25,0xfedcba987654321ULL);constant(26,7);constant(30,0x1122334455667788ULL);}
    void warm(){one(st(10,30));one(ld(5,11));one(ld(6,12));}
    void workload(unsigned loadBase=11,int loadOffset=0,unsigned storeSize=3,unsigned loadSize=3,bool twice=false,unsigned branchKind=0){
        oldDataReady=proofCycle=firstEarlyPhysical=earlyReadDrain=0;boundProof.reset();
        std::vector<uint32_t> words{divu(30,25,26)};
        if(branchKind==2)words.push_back(beq(30));
        words.push_back(st(10,30,0,storeSize));
        if(branchKind==1)words.push_back(beq(30));
        words.push_back(ld(20,loadBase,loadOffset,loadSize));
        auto t=submit(words);
        oldStore=t[branchKind==2?2:1];youngLoad=t.back();if(twice)secondLoad=submit({ld(21,11,16)})[0];}
    void witness(bool expectEarly){check(oldStore&&youngLoad,"missing witness owners");const auto&s=entries.at(*oldStore);const auto&l=entries.at(*youngLoad);
        check(bool(firstEarlyPhysical)==expectEarly,"early physical acceptance expectation mismatch");
        if(expectEarly){check(proofCycle&&oldDataReady&&l.physical<oldDataReady&&l.physical<s.start&&s.frozen,"missing before-data/serial/frozen witness");
            if(!BOUND_HEAD_STORE_OVERLAP)check(l.response<s.start,"serial old store started before early response drained");
            if(BOUND_HEAD_STORE_OVERLAP&&l.response>oldDataReady)check(s.start<l.response&&overlappedStarts,"NEW missed ready bound store/live early owner overlap");}
        check(s.response&&s.checked&&s.retired&&l.retired&&s.retire<=l.retire,"ordinary complete retirement witness missing");
        std::cout<<"PENDING_BACKEND_WITNESS enabled="<<PENDING_STORE_ENABLED<<" store="<<s.token.index<<":"<<s.token.tag<<" load="<<l.token.index<<":"<<l.token.tag
            <<" proof="<<proofCycle<<" load_physical="<<l.physical<<" data_ready="<<oldDataReady<<" load_response="<<l.response<<" store_start="<<s.start<<" store_checked="<<s.checked<<" store_physical="<<s.physical<<" load_release="<<l.released<<" overlaps="<<overlappedStarts<<" store_response="<<s.response<<" store_retire="<<s.retire<<" load_retire="<<l.retire<<'\n';}
};
int main(int argc,char**argv){try{
    std::cout.setf(std::ios::unitbuf);
    const std::string mode=argc>1?argv[1]:"";
    {Bench b;b.configure();b.warm();b.injectData=mode=="--mutate-data";b.injectFrozenPa=mode=="--mutate-frozen-pa";b.injectLocalAck=mode=="--mutate-local-ack";b.latency=80;b.workload(11,0,3,3,true);b.drain();b.witness(PENDING_STORE_ENABLED);
      if(PENDING_STORE_ENABLED)require(b.earlyStarts==1&&b.creditReturns==1,"one global credit allowed a second live early owner");
      std::cout<<"PENDING_BACKEND_CASE nonalias_credit_saturation reuse="<<b.reuse<<'\n';}
    for(unsigned which=0;which<4;++which){Bench b;b.configure();b.warm();
      if(which==0)b.workload(12); // distinct VA aliases the exact same PA
      if(which==1)b.workload(10,4,2,2); // same beat, disjoint words
      if(which==2)b.workload(10,2,2,1); // one overlapping halfword
      if(which==3)b.workload(10,1,0,0); // disjoint adjacent bytes
      b.drain();b.witness(PENDING_STORE_ENABLED&&(which==1||which==3));std::cout<<"PENDING_BACKEND_CASE byte_interval_"<<which<<'\n';}
    {Bench b;b.configure();b.warm();b.latency=100;b.workload(11,0,3,3,false,PENDING_STORE_ENABLED?1:0);
      if(PENDING_STORE_ENABLED){
        b.injectRetire=mode=="--mutate-retirement";
        for(unsigned n=0;n<300&&!b.entries.at(*b.youngLoad).killed;++n)b.tick();
        require(b.firstEarlyPhysical&&b.entries.at(*b.youngLoad).killed&&!b.entries.at(*b.youngLoad).response,
            "real selective branch did not kill an accepted undrained read");
        require(b.boundProof.has_value(),"surviving store lost its bound physical identity");
        const auto&s=b.entries.at(*b.oldStore);
        if(!s.started)require(b.dut.get_io$$proof$$valid()&&b.dut.get_io$$bound(),"pending surviving bound store proof lost after young branch kill");
        else require(s.frozen&&!s.response,"captured surviving store lost frozen/late-ACK responsibility");}
      b.drain();if(PENDING_STORE_ENABLED){const auto&s=b.entries.at(*b.oldStore);const auto&l=b.entries.at(*b.youngLoad);
        require(s.frozen&&s.retired&&l.killed&&!l.retired&&l.response&&b.creditReturns==1,"selective kill did not preserve store binding and drain credit");}
      if(PENDING_STORE_ENABLED)require(b.recoveryEdges&&b.recoveryWithLiveRead,"decoded branch did not exercise same-edge recovery with an accepted live read");
      std::cout<<"PENDING_BACKEND_CASE selective_branch_kill_drain recovery_edges="<<b.recoveryEdges<<" live_read_recovery="<<b.recoveryWithLiveRead<<'\n';}
    {Bench b;b.configure();b.warm();b.latency=100;const Bytes before=b.expected;b.workload(11,0,3,3,false,PENDING_STORE_ENABLED?2:0);
      if(PENDING_STORE_ENABLED){for(unsigned n=0;n<300&&!b.entries.at(*b.oldStore).killed;++n)b.tick();
        require(b.firstEarlyPhysical&&b.entries.at(*b.oldStore).killed&&!b.entries.at(*b.oldStore).started,
            "real full branch recovery lacked accepted read or failed to kill pending store");
        b.expected=before;b.wait(2);
        require(!b.dut.get_io$$proof$$valid()&&b.creditReturns==0,"recovery retained proof or returned accepted owner early");}
      b.drain();b.oldStore.reset();b.youngLoad.reset();b.boundProof.reset();
      b.csr(0x180,satp+(1ULL<<44));b.one(ld(22,11,24));
      require(!b.dut.get_io$$proof$$valid(),"old proof survived legal drain/context/new-token sequence");
      std::cout<<"PENDING_BACKEND_CASE branch_recovery_drain_epoch_reallocation\n";}
    {Bench b;b.configure();b.warm();b.faultStore=true;b.workload();b.drain();
      require(b.traps==1&&b.oldStore&&b.youngLoad&&!b.entries.at(*b.youngLoad).retired,"late store fault allowed young architectural effect");
      if(PENDING_STORE_ENABLED)require(b.entries.at(*b.youngLoad).completed&&b.entries.at(*b.oldStore).frozen,"late fault lacked early completed result/frozen write");
      std::cout<<"PENDING_BACKEND_CASE late_store_fault\n";}
    {Bench b;b.configure();b.warm();b.latency=80;b.workload();
      if(PENDING_STORE_ENABLED){for(unsigned n=0;n<200&&!b.firstEarlyPhysical;++n)b.tick();
        require(b.firstEarlyPhysical,"same-epoch mutation lacked early accepted read");const auto epoch=b.dut.get_io$$epoch();
        b.tables.pages[0].physical=ram+4096;b.drain();
        require(b.dut.get_io$$epoch()==epoch&&b.entries.at(*b.oldStore).frozen&&b.entries.at(*b.oldStore).pa==ram,
            "same-epoch external PTE mutation changed bound actual store PA");
      }else b.drain();std::cout<<"PENDING_BACKEND_CASE same_epoch_pte_mutation_frozen\n";}
    {Bench b;b.configure();b.warm();b.physicalHold=b.cycle+100;b.workload();b.drain();
      require(b.holds>0,"external held request not exercised");
      if(PENDING_STORE_ENABLED)require(b.boundProof&&b.entries.at(*b.oldStore).frozen,"data-ready rise retracted bound store binding");
      std::cout<<"PENDING_BACKEND_CASE held_request_ready_rise\n";}
    {Bench b;b.configure();b.warm();for(unsigned n=0;n<9;++n)b.one(imm(0,0,0));b.latency=80;b.workload();b.drain();b.witness(true);
      require(b.oldStore->index==15&&b.youngLoad->index==0,"real backend wrap fixture did not cross index15 to0");
      std::cout<<"BOUND_OVERLAP_BACKEND_CASE real_head15_young0_full_token_wrap\n";}
    for(unsigned errors=1;errors<=3;++errors){Bench b;b.configure();b.warm();
      b.faultLoad=errors&1;b.faultStore=errors&2;b.latency=120;
      b.injectLoadError=mode=="--mutate-load-error";b.injectStoreError=mode=="--mutate-store-error";
      b.workload();b.submit({imm(21,20,1)});b.drain();
      const auto&s=b.entries.at(*b.oldStore);const auto&l=b.entries.at(*b.youngLoad);
      require(b.traps==1&&s.checked&&s.response&&l.response,"error fixture missing real checked/response/trap lifecycle");
      if(BOUND_HEAD_STORE_OVERLAP)require(b.overlappedStarts==1&&s.start<l.response,"error fixture lacked actual store/live-load co-ownership");
      if(errors==1)require(s.retired&&!l.retired&&l.fault,"young load error lost successful older-store retirement");
      else require(!s.retired&&!l.retired&&s.fault,"older store error lost precise priority");
      std::cout<<"BOUND_OVERLAP_BACKEND_ERROR errors="<<errors<<" store_start="<<s.start<<" load_response="<<l.response
        <<" store_checked="<<s.checked<<" store_response="<<s.response<<" load_complete="<<l.complete
        <<" store_complete="<<s.complete<<" store_retire="<<s.retire<<" traps="<<b.traps<<'\n';}
    std::cout<<"BOUND_OVERLAP_BACKEND_PASS enabled="<<PENDING_STORE_ENABLED<<" coowner="<<BOUND_HEAD_STORE_OVERLAP<<'\n';return 0;
}catch(const std::exception&e){std::cerr<<"PENDING_BACKEND_FAIL "<<e.what()<<'\n';return 1;}}
